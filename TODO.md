# Xunji 项目待办

> 最后更新: 2026-06-29。
> 本文件只保留未完成事项和下一阶段方向。已完成的历史流水账不再保留。

## 0. 当前最高优先级

### 0.1 修复本地自检红灯

`python3 tools/selftest_all.py` 当前结果: 32 passed, 0 failed。

- [x] `classify_hosts`: 修复 same-host redirect integration 用例。
  - 失败点: followed same-host redirect。
  - 失败点: resolved page classified AIS。
  - 失败点: resolved body has app marker。
- [x] `probe`: 修复响应头、cookie、保存体、no-redirect、replay metadata 相关回归。
  - 失败点: Set-Cookie 未完整捕获。
  - 失败点: `Identity.External` / antiforgery cookie 提取失败。
  - 失败点: `--save` 写 body / len / sha1 summary 不符合预期。
  - 失败点: replay response status / full sha1 / response headers 不完整。
  - 失败点: `--no-redirect` 未稳定保留 302、Location、跳转 cookie。
- [x] `proxy`: 明确 PySocks 依赖处理。
  - 当前失败信息: socks 代理需要 PySocks, 不应静默直连。
  - 选择: 将 PySocks 作为可选依赖写入安装文档, 或让 selftest 在未安装时 SKIP 而非 FAIL。
- [x] `replay`: 修复 IDENTICAL / CONSISTENT / UNREACHABLE / in-scope batch replay 判定。
  - 失败点: 正确录像未判为 IDENTICAL。
  - 失败点: status 同 sha 异未判为 CONSISTENT。
  - 失败点: 目标不可达未判为 UNREACHABLE。
  - 失败点: scope 内 host 未正常重放。
  - 失败点: 批量重放 run 目录缺 IDENTICAL。

### 0.2 保持 bench 基线可用

`python3 tools/bench.py score-all bench --json-out /tmp/xunji-bench-current.json` 当前基线:

- [x] 10/10 fixtures clean。
- [x] detection 10/10。
- [x] calibration 10/10。
- [x] false positives 0。
- [x] closure 1/1 correct。
- [x] 后续每个架构改动都必须追加一条 `review/records/<date>-bench-*.md`。

## 1. 核心优化方向: Ultra-native Xunji

这不是新增一个 `Ultra Run Mode`。项目优化方向本身就是 Ultra-native:

```text
Xunji =
  Root Orchestrator
  + role-based Subagents
  + each subagent has recurrent-depth reasoning
  + single Synthesizer / evidence gate
  + guard / hook / bench / review
```

设计来源:

- GPT-5.6 Sol Ultra: 重点学习多 Subagent 并行协作, 不是单 Agent 想更久。
- OpenMythos: 重点学习单个 Agent 内部的 Prelude / Recurrent Loop / Coda 深度结构。
- Xunji 自身约束: 多 Agent 只能扩大探索广度, 不能放松证据门, 不能污染事实源。

### 1.1 不可破坏的工程约束

- [x] Subagent 只能写 `phenomenon` / `candidate` / `refutes` / `barrier` / artifact pointer。
- [x] 只有 Root Synthesizer 可以把 candidate 升格为 `finding`。
- [x] 只有 Root Synthesizer 可以写最终 certainty、report conclusion、closure。
- [x] Markdown run files 仍是 canonical narrative。
- [x] `state/*.json` 只做投影、索引、调度缓存, 不反向覆盖人工叙事。
- [x] 所有主动动作仍必须走 guard / hook / scope / request budget。
- [x] 多 Agent 不得变成按技术清单盲跑的 scanner 或 playbook。
- [x] worker / subagent 之间不直接聊天; 只通过 run dir 黑板协作。

## 2. 目标架构

### 2.1 Root Orchestrator / Synthesizer

职责:

- [x] 吸收 Guanlan / recon / coverage / operator hints。
- [x] 拆分 fronts, 判断哪些 front 可并行。
- [x] 给 Subagents 分配 disjoint front / role / budget。
- [x] 聚合 Subagent 产物, 去重、查冲突、补证据。
- [x] 对冲突派 Verification Agent, 不凭直觉二选一。
- [x] 将过 evidence gate 的 candidate 升格为 finding。
- [x] 触发 Independent Review / report / closure。

Root 循环:

```text
project state
  -> decompose fronts
  -> assign agents
  -> collect candidates
  -> detect conflicts
  -> verify / falsify
  -> synthesize findings
  -> update graph
  -> continue or close
```

### 2.2 Subagent roles

- [x] `surface-agent`
  - 吸收 recon、coverage、fingerprint、threat role。
  - 产出 attack surface candidates, 不确认漏洞。
- [x] `web-hunter-agent`
  - 黑盒 Web 漏洞探索。
  - 可按 front 分成 auth / upload / frontend / API / SSRF / SSTI / RCE proof path。
- [x] `code-audit-agent` / `zhaoxuan`
  - source-sink、patch diff、dependency、配置、路由、鉴权边界。
  - 输出 source-level phenomenon / candidate。
- [x] `exploit-construction-agent`
  - payload adaptation、PoC 草案、harmless proof path。
  - 可写 author-and-handoff 代码, 但自动执行仍受 guard / hook / proof-only 约束。
- [x] `verification-agent`
  - replay、control、replication、falsification、certainty calibration。
  - 专门处理 Agent 间冲突和高危 finding 复现。
- [x] `independent-review-agent`
  - clean-context review。
  - 高危 finding / closure / safety-critical code change 前运行。
- [x] `report-agent`
  - 只起草 report skeleton 和一致性检查。
  - 不得新增未过 evidence gate 的 finding。

### 2.3 每个 Subagent 的 OpenMythos-style 内部循环

每个 Subagent 不做一次性回答, 而是固定三段:

```text
Prelude
  读取最小 context pack

Recurrent Loop
  hypothesis
  expected signal
  action / analysis
  observation
  refutation
  next hypothesis

Coda
  candidate / refutes / barrier / artifact / next action
```

统一输出契约:

```text
Agent:
Role:
Assigned front:
Scope:
Budget used:
Maturity: phenomenon | candidate
Supports:
Refutes:
Artifacts:
Control:
Replicated:
Confidence:
Barrier:
Conflict candidates:
Recommended next action:
Merge note:
```

## 3. Run directory 目标结构

当前 run dir 不要一次性大迁移; 先兼容旧结构, 新结构按功能渐进落地。

```text
runs/<target>/
  target.md
  surface.md
  frontier.md
  hypotheses.md
  evidence.md
  false_positive.md
  decisions.md
  review.md
  report.md

  agents/
    A-surface-001.md
    A-web-auth-001.md
    A-code-001.md
    A-exploit-001.md
    A-verify-001.md
    A-review-001.md

  context/
    F-001.surface.md
    F-002.web-auth.md
    F-003.code.md

  state/
    events.jsonl
    graph.json
    assignments.json
    conflicts.json
    synthesis.json

  artifacts/
    evidence/
    replay/
    render/
    oob/
    code/
```

待办:

- [x] 兼容现有 `workers/` 文件夹, 决定是否迁移到 `agents/` 或保留别名。
- [x] 明确 `agents/*.md` 是 Subagent scratch, 不是 canonical evidence。
- [x] 明确 `context/*.md` 是最小上下文包, 可由工具生成。
- [x] 明确 `state/conflicts.json` 的 schema。
- [x] 明确 `state/assignments.json` 的 schema。
- [x] 明确 `state/synthesis.json` 的 schema。

## 4. 工具改造 backlog

### 4.1 `tools/context_pack.py`

新增最小上下文打包器:

```bash
python3 tools/context_pack.py runs/<dir> --front F-001 --role web-auth
python3 tools/context_pack.py runs/<dir> --agent A-web-auth-001
```

输出:

- [x] front 摘要。
- [x] scope / target / threat role。
- [x] 相关 evidence / false_positive。
- [x] 相关 artifacts。
- [x] 相关 knowledge / xday 命中。
- [x] 最近 Reason / Metacog / barrier。
- [x] agent role-specific instructions。

约束:

- [x] 不写 canonical finding。
- [x] 不自动选择漏洞清单。
- [x] 打包内容要短, 目标是减少上下文污染。

### 4.2 `tools/workers.py` -> agent board

保留现有 worker 思路, 但升级为多 Agent 黑板工具:

```bash
python3 tools/workers.py plan runs/<dir>
python3 tools/workers.py assign runs/<dir> --role web-auth --front F-001
python3 tools/workers.py status runs/<dir>
python3 tools/workers.py merge-check runs/<dir>
python3 tools/workers.py conflicts runs/<dir>
python3 tools/workers.py synthesize runs/<dir>
```

待办:

- [x] `plan`: 读取 frontier / coverage / state graph, 给出可并行 agent plan。
- [x] `assign`: 生成 `agents/A-*.md` + `context/*.md`。
- [x] `status`: 列出 assigned / working / done / merged / blocked。
- [x] `merge-check`: 检查 done-but-unmerged、candidate 缺 control、重复、冲突。
- [x] `conflicts`: 把 supports/refutes 冲突写入 `state/conflicts.json`。
- [x] `synthesize`: 生成 Root Synthesizer 合并草案, 只做建议, 不写 canonical evidence。

### 4.3 Agent templates

新增:

```text
docs/templates/agents/surface.md
docs/templates/agents/web-hunter.md
docs/templates/agents/code-audit.md
docs/templates/agents/exploit.md
docs/templates/agents/verify.md
docs/templates/agents/review.md
docs/templates/agents/report.md
docs/templates/agents/synthesizer.md
```

每个模板必须包含:

- [x] Role boundary。
- [x] Allowed inputs。
- [x] Forbidden writes。
- [x] Prelude / Recurrent Loop / Coda。
- [x] Output contract。
- [x] Safety / guard reminder。
- [x] Evidence maturity rule。

### 4.4 Conflict gate

新增冲突规则:

```text
Agent A supports F-001
Agent B refutes F-001
=> state/conflicts.json
=> Verification Agent
=> control / replay / replication
=> Root Synthesizer decision
```

待办:

- [x] 定义 conflict 类型: direct contradiction / duplicate / confidence mismatch / artifact mismatch / scope mismatch。
- [x] `check_run.py` closure 前 warning: unresolved conflict。
- [x] high-severity finding 若有 unresolved conflict, closure hard fail。

### 4.5 Bench 扩展: 评估 Ultra-native 架构

现有 bench 主要评估 finding 结果。下一步增加协同指标:

- [x] agent coverage: 高价值 front 是否被分配到合适 role。
- [x] candidate-to-finding conversion: candidate 有多少成功过证据门。
- [x] conflict resolution correctness: 冲突是否被 verification 解决。
- [x] missed high-value front: closure 前是否仍遗漏 high-value front。
- [x] request budget by agent: 多 Agent 是否放大请求量。
- [x] time-to-first-evidence by mode: 多 Agent 是否真实缩短首证时间。
- [x] false-positive suppression: verification/review 是否减少误报。

新增对照:

```text
single-driver baseline
vs
ultra-native agent board
```

## 5. 文档改造 backlog

### 5.1 重新定位 Xunji

待改文件:

- [x] `README.md`
- [x] `README.en.md`
- [x] `CLAUDE.md`
- [x] `docs/XUNJI_PROJECT_INTRO.md`
- [x] `docs/WORKFLOW.md`
- [x] `docs/WORKFLOW-reference.md`
- [x] `docs/ROUTER.md`
- [x] `docs/templates/loop_prompt.md`
- [x] `docs/templates/worker.md` 或迁移到 `docs/templates/agents/`

核心措辞:

```text
从:
  单一 AI 驱动者

改为:
  Root Orchestrator + Subagents + Single Synthesizer
```

同时保留:

- [x] 单一最终裁决者。
- [x] 证据门。
- [x] guard / hook / sentinel。
- [x] 反 playbook。
- [x] grounding-vs-weapon 分层。
- [x] run dir 审计轨迹。

### 5.2 更新工作流

新核心循环:

```text
observe
  -> update state graph
  -> decompose fronts
  -> plan / assign agents
  -> agents produce candidates
  -> merge-check / conflict-check
  -> verify / falsify
  -> synthesize findings
  -> review / report / closure
```

待办:

- [x] 把 Reason pass 改成 Root-level state graph pass。
- [x] 把 Metacog 改成 Root 可派发的 divergence agent / verification trigger。
- [x] 把 worker fan-out 改成默认协作模型, 不是例外机制。
- [x] 明确何时串行: 单 front / 低价值 / 请求预算紧张 / 强共享 barrier。
- [x] 明确何时并行: 多独立 front / 高价值 / code+blackbox / 0day/xday / closure 前 unresolved。

## 6. 与 Guanlan / Zhaoxuan 的关系

### 6.1 Guanlan

- [ ] Guanlan 继续作为上游 recon / surface provider。
- [ ] Xunji 不回收 Guanlan 职责, 只吸收其输出。
- [ ] `surface-agent` 负责把 Guanlan 结果投影到 Xunji fronts / threat roles。

### 6.2 Zhaoxuan

- [ ] 将 Zhaoxuan 定义为 code-audit agent 方向。
- [ ] 先通过 `context_pack.py --role code-audit` 与 Xunji run dir 接缝。
- [ ] 不让 code-audit 输出直接成为 finding; 必须经过 verification / evidence gate。

## 7. 状态栏待办

文件: `C:\Users\CCJ\.claude\statusline.ps1`

- [ ] Context 条校准待拍板。
  - 当前显示来自 Claude Code stdin 的 `used_percentage` + `context_window_size`。
  - 选择 A: 分母保持模型最大窗口 1M。
  - 选择 B: 分母改为实际触发 auto-compact 的阈值, 更能反映还能撑多久。

## 8. 安全约束

授权 SRC / 授权测试前提不变。

硬边界继续只按不可逆危害拦截:

- 不可逆销毁。
- 删库 / 无范围 destructive update。
- 目标资源删除。
- 批量外渗 / 拖库。
- 权限 / 属主 / 特权变更。
- 资金动作。
- DoS / 高速压测。

多 Agent 化后的额外要求:

- [x] 所有 Agent 共用全局 guard state / request budget。
- [x] Agent 数量不能线性放大请求速率。
- [x] 每个 Agent 的主动动作仍必须可审计、可归因、可回放。
- [x] Agent 产物中的目标自然语言仍按 untrusted content 处理。
