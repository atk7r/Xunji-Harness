# 独立复审记录 — 收口/覆盖/纵深护栏(P0-1/2/3)

- 日期: 2026-06-17
- 触发: `.claude/hooks/` 安全关键代码行为变更(P0-2 新增 Stop hook)→ CLAUDE.md「Independent
  review of safety-critical code」硬要求
- 复审者: fresh-context `general-purpose` 子代理(standing-authorized),对抗性审视
- 自评不治自评偏见 → 本记录满足收口前安全码复审硬门

## 改动范围

| 项 | 文件 | 性质 |
|---|---|---|
| P0-1 | `tools/setup_run.py`(新增) | 纪律工具:一键建 run 骨架 + ingest_recon +(可选)classify_hosts |
| P0-2 | `.claude/hooks/run_gate.py`(新增) + `.claude/settings.json`(加 Stop + SessionStart selftest) | **安全关键**:Stop hook,收尾时替 driver 跑 check_run,未过则拦一次 |
| P0-3 | `tools/check_run.py` | 纪律工具:`check_shallow_close` 纵深护栏 + `_recon_cited` 占位排除 |

动机:hamastar run 因"过早收口/漏挖/假证据"被操作者催 6 次。P0-2 治"闸门被动"(聊天里收口、不跑 check_run),P0-1 治"手工誊录资产=选择偏见",P0-3 治"高价值前沿浅尝即弃"。

## 复审结论

**可以合入。BLOCKER = 0。** 复审实测三个 selftest 全绿 + 对 run_gate 做真实 stdin 注入(空/空JSON/畸形/stop_hook_active)+ 真实 run 端到端。

逐项 PASS:
1. **fail-open 真实性** — main 两层 try 兜住全部路径,畸形输入实测静默 exit 0;import 顶层 try→`_cr=None`。
2. **防循环** — `stop_hook_active=true → notify` 实测成立;单续跑链内不可能 block→block。
3. **误拦(FP)** — 三重与门(active+report_is_final+check 失败)够严;空壳 report 实测不触发。
4. **性能** — `find_active_run` 只 glob `runs/*/report.md`(非 rglob),仅收尾态 fork check_run。
5. **配置** — Stop hook 语法/路径正确,与 safety_gate/sentinel 无冲突(Stop 事件此前无钩子)。
6. **P0-1** — 不覆盖守卫双保险;Windows 反斜杠用 lambda 替换避开组引用坑(selftest 断言)。
7. **P0-3** — 模板占位 `shallow / moderate / deep` 实测不 FP;`Vectors tried:` 已写则不催;无 depth 字段旧 run 不报。

## Findings 与 Resolution

- **SHOULD-FIX-1**(run_check timeout=120 卡死会静默阻塞 120s)→ **已修**:timeout 120→30,
  且 `run_check` 内 catch 异常返回 `(0,"")`(超时=放行,会话停顿 ≤30s)。
- **SHOULD-FIX-2**(run_gate 无 SessionStart selftest,哑火不可发现)→ **已修**:`run_gate.py
  --selftest` 接入 SessionStart;selftest 输出改到 stderr(不刷 context,与 safety_gate 一致)。
- **NIT-1**(parents[2] 路径耦合)→ 记录,与 safety_gate 一致,非问题。
- **NIT-2**(mtime 15 分钟窗口:对历史 run 的 report.md 的非 driver 改动(如复审 touch)会偶发
  一次多余提醒)→ **接受**:fail-open + 只 notify/block 不毁数据,实际 driver 场景 mtime 即 driver 自身所写。
- **NIT-3**(reason 截尾 1600 字符)→ 取尾部恰好保住 check_run 的 errors(打印在结尾),设计合理。

## 复审后验证(全绿)

```
run_gate   selftest passed (10/10)
check_run  selftest passed (22/22)
setup_run  selftest passed (10/10)
hook check passed        (check_hook.py)
rule check passed        (check_rules.py)
safety gate healthy      (safety_gate --selftest 未受影响)
端到端: Stop 事件 → hamastar(终版+check失败)→ decision=block;stop_hook_active=true → notify
```

## 增量:gate_skipped 豁免(同日,Stop hook 实战触发后追加)

run_gate 上线当天即被自己触发(hamastar 有终版 report + check_run 失败)。处理:
① 按证据门降级 4 条无产物的 ≥0.8 假证据(E-006/007/010/018 → 0.3/0.5);② 操作者决定把
hamastar 留作"未充分收尾的教学样本";③ 为此给 run_gate 加 `gate_skipped`:report.md 含
`run-gate: skip` 标记时 Stop hook 不再主动提醒。

**第二次独立复审(fresh-context,聚焦后门判定)结论:可以合入,0 BLOCKER / 0 SHOULD-FIX。**
实测证明隔离成立:`check_run runs/hamastar_20260615` 仍 exit 1(覆盖台账缺建照常 fail),
`tools/check_run.py` 对 `run-gate` **零引用** —— 豁免只让 Stop hook 闭嘴,**不豁免事实闸门**,
不构成"标注一下就过门"的后门。滥用面:driver 自加标记只换来"少一次提醒",换不来"通过";
标记明文进 diff 可审。token `run-gate: skip` 够特异(全仓仅 hook 自身命中)。fail 方向正确
(读不到 report → 不豁免 → 继续拦)。NIT 2 条(重复读 report 的 I/O 洁癖;hook 无法区分标记
是操作者还是 driver 所写——威胁模型内已由"check_run 仍 fail + diff 可审"缓解),均不需改。

## check_run certainty 解析坑 —— 已根治(同日,第三次复审)

- 根因:旧 `parse_evidence` 从 "Certainty" 关键词扫到**块尾**抓所有网格数字 → 降级说明里的
  解释数字("原 0.8""升回 1.0")被误当 certainty 值,降级无效仍判 ≥0.8。
- 修复:certainty 改取 `Certainty:` 字段【值区域】(`_CERT_FIELD_RE`,到下一字段/空行/块尾)
  + 剥括号说明(`_PAREN_RE`);off-grid 兜底加可选括号 `[\(（]?` 覆盖"值本身写在括号内"。
- **第三次独立复审(fresh-context,聚焦反向风险)结论:可合入,0 BLOCKER。** 自建 ~20 对抗
  用例 + selftest 实跑证明:① 降级生效(说明含网格数字不再误判);② 未破坏 split / off-grid /
  跨行 split;③ **无"假证据蒙混过门"风险**。唯一狭窄漏判(真值首字符即括号,如 `Certainty: (0.8)`)
  方向是"真高值被低估"(暴露给 driver、不绕过安全门)且全仓零先例 —— 已按复审建议(S1)用
  off-grid 可选括号修掉,并补 N2 跨行 split 回归。selftest 25/25。

## 指纹入库收口门(同日,第四次独立复审)

- 需求:每次渗透收口都把识别的产品指纹入 `knowledge/` grounding 库(喂飞轮)。机制:`check_run`
  收口门(`_closure_claimed`/`_report_is_final` 触发)要求 report 申报 `Fingerprints captured:` ——
  缺=硬错;无 `knowledge/` 路径却有独立应用候选=软警。不进 REQUIRED_MARKERS(不破坏历史 run 日常 check)。
- **第四次独立复审(对抗性,FP/绕过)结论:可合入,0 BLOCKER。** 实跑发现并已修:
  - **S1(真误伤,已修)**:旧空值正则 `re.match("(…|无|none|…)")` 把"以否定词开头的真实申报"
    (如"无法测X; 主站 WP → knowledge/wp.md")误判为"无新指纹"。改判据为"有无 `knowledge/` 入库路径"
    (明确信号,不靠脆弱否定词正则)→ 根治。
  - **S2(易绕过,已修)**:正则整篇 search → 注释/代码块里的字段被当真申报。改为先剥 ```/`<!-- -->` 再匹配。
  - N1(空值无候选静默全过)/ N2(终版强制非误伤)接受为设计内。
- 回归:selftest +5 用例(缺/有/无+候选/S1 含 knowledge 路径不误判/S2 注释→硬错)全过 **30/30**;
  hamastar 补申报(含 knowledge/ 路径)后 PASS。新指纹 `knowledge/hamastar-cms.md`、
  `knowledge/simmagic-reg.md` 过 `check_knowledge`(17 条目)。

## 残留(不阻塞)

无。SHOULD-FIX 全 resolve(含指纹门 S1/S2);NIT 记录或接受;指纹门已过第四次独立复审。
