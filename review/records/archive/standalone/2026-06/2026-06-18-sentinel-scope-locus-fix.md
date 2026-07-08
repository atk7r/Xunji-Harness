# 2026-06-18 sentinel scope/locus FP 修复 — 安全关键码独立复审记录

mokwon 实弹 dogfood 暴露 sentinel 三个误报(observe-only, 未拦, 但 alerts 满屏 + 熔断误触):
- **#10** scope 过期: sentinel 用上一个 run 的 scope(`hamastar.com.tw`)判 mokwon 探测 → 26 次 scope_drift 误报 + 熔断。
- **#11** locus 误判: 清理自己 scratch 的 `rm -rf runs/x 2>/dev/null` 因 `/dev/null`(系统路径)被判 LOCAL_OTHER → 误标 L4「目标销毁」(比真 safety_gate 地板还激进)。

改动文件: `sentinel/classifier.py` `sentinel/detectors.py` `sentinel/monitor.py` `sentinel/verify_layers.py`。

## 最终设计
- **#11**: `_REDIR_SINK`(/dev/null 等重定向汇)从 `paths` 滤掉 → 不参与 locus 判定; `rm 仓库 scratch` 归 LOCAL_WORKSPACE 清理, 不再 L4。
- **#10a**: 新 `monitor._refresh_run_ctx(sess, run)` —— 每个决策事件(SessionStart/PreToolUse)据【当前】active run
  刷 scope_hosts+plan_keywords; **run=None 则清空, 绝不留过期值**。治真正的过期 scope FP。
- **#10b(撤掉)**: 一度想"空 scope 不判越界", 但与残留 plan 组合 → target 漏放 AUTO(见下复审)。撤回 ——
  空 scope = 未定义, 保守 `not host_in_scope` → 仍 GATE(observe-only, 噪音可接受; 安全优先)。
- 回归: `verify_layers.scope_edge_cases`(空 scope target≥GATE / 真越界仍报 / redirect=workspace / run=None 清空)。

## 独立复审(Codex 异构, 3 轮) —— 每轮都逮到真【漏放】洞, selftest 全程绿
> 安全关键码: 自测绿是地板不是目标; 独立复审防的就是 selftest 看不见的地板削弱(under-label)。

- **轮1 BLOCKER**: `#10a` 只刷 scope_hosts 没刷 plan_keywords + `#10b` 空 scope 放宽门 → 空 scope + 残留 plan token
  误判 PLAN_DERIVED → 绕过 unattributed fail-safe → **L1/AUTO 漏放**。→ 撤 #10b + 补刷 plan。
- **轮2 BLOCKER**: 刷新用 `if run is not None` 守卫 → **run=None 时残留 scope/plan 仍在** → target 匹配过期 scope
  得 host_in_scope=True → **L1/AUTO 漏放**(Codex 直接复现)。→ 改 `_refresh_run_ctx`: run=None 清空。
- **轮3 WARN(仅环境)**: **"No under-label / floor-weakening path found"**; WARN 唯一原因是 Codex 沙箱 Python 坏、
  跑不了 `verify_layers.py`。该测试我本地跑过: **17/17, EFFECTIVE / NO FALSE POSITIVES**, 含 run=None 清空用例。

## 处置(driver 整合)
- 两个 BLOCKER 均真实, 已修并各加回归用例。轮3 无地板削弱; WARN 是环境限制(Codex 跑不了 py), 由我本地跑全
  battery 补上(Codex 跑不了的那个测试, 我跑了, 绿)。→ **实质 PASS**。
- 保真核对: 真越界仍报 scope_drift + GATE; 真危害(`rm -rf /`/`DROP DATABASE`/`dd of=/dev/sda`)仍 BLOCK;
  operator-directed 本地清理仍 AUTO(directives 与 plan 分开, 不受清空影响)。
- `selftest_all` 17/17 + `check_rules` 绿。

## 教训
3 轮独立复审, 2 轮各逮到一个"selftest 全绿却能把 target 动作欠标成 AUTO"的真洞。**安全关键码改动必须过异构
独立复审到无地板削弱 + 跑全 battery, 缺一不可**(延续 review-of-safety-critical-code 纪律)。
