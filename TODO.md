# Xunji 统一实施计划

> 最后更新：2026-08-12。
> 本文件是当前 Python/Harness 修复、三段 Run Macro-Stage 和 Agent/Worker 调度的唯一正式
> backlog。`[x] 已实现` 表示当前代码、fixture/回归和现行架构共同支持；
> `[x] 已决策` 表示已明确不采用或暂不准入，不能解读为代码实现；`[ ]` 表示仍未完成，
> 其中写明“部分实现”的条目只列剩余验收。原 `todo1.md` 已于 2026-08-11 合并到本文件，
> 其逐节处置见第 6 节；历史 review record 只提供来源与论证，不建立第二套 backlog 真值。
> CCB/TypeScript 迁移不在当前路线；除非 operator 以后重新立项，不为它保留迁移任务。
>
> 本次盘点基线：当前工作树 `python3 tools/selftest_all.py` 为 **80 passed, 0 failed**；
> `check_rules.py`、`check_templates.py`、`check_runtime_boundary.py` 与本机/封闭式 hygiene
> 检查均通过，新增可信入口已与 safety-critical manifest 同步。
> 历史隔离分支 `f1a186e` 的“全勾选”结果不在当前 HEAD 祖先链，未作为当前完成证据。

## 0. 总体目标与设计原则

目标：修复当前 Python/Harness 的执行边界和主动委派缺口，建立可回退的三段运行、
计划、Agent 调度、复审和收口契约，并由 Claude Code 主驾驶真实验证。

架构名称：**能力导向、证据治理的 Agent 架构**（Capability-Oriented, Evidence-Governed Agent Architecture）。

核心原则：

- 按 Agent 要完成的能力拆 Tool，不按现有 Python 文件机械拆分。
- 每个模型可见 Tool 保持单一职责、结构化输入和结构化输出。
- 不以 registry 中 Tool 数量少为目标；最小化的是每个 assignment 的运行时暴露面和
  Claude 本机 auto-allow，所有能力继续复用统一 typed capability/effect/Hook 契约。
- `scope / guard / privacy / proxy / evidence recorder` 属于不可绕过的内部执行链，不暴露成可选 Tool。
- `runs/<target>/` Markdown、证据产物和审查记录继续作为事实来源；聊天、模型置信度和派生缓存不是证据。
- 子代理只产生候选；Root/Synthesizer 负责去重、冲突处理、证据晋级、报告纳入和收口。
- 独立 reviewer 只提供挑战和候选意见，不能直接批准 finding 或 closure。
- Macro-Stage、计划、Worker/Lane 和 Agent 调度是控制面；它们不能复制或覆盖 canonical
  run 事实，也不能把计划完成误写成 finding、coverage 或 closure。
- 当前实现和待实现目标必须分开描述；TODO 勾选前需要代码、fixture、
  验证和独立复审共同证明，不能用文档存在代替实现。

## 1. 当前 Python/Harness 优先修复

当前边界没有恢复为可测、可解释的稳定基线前，不通过降低阈值、
扩大 Bash 白名单或增加 prompt 规则绕过问题。

### 1.1 P0：恢复执行边界基线

- [x] 修复 Claude Hook 事件缺 `session_id`/`transcript_path` 时 pending contract 静默不落盘：
  按 `session -> transcript -> personal singleton` 做因果降级，UserPromptSubmit 与 PreToolUse
  可恢复同一操作者意图；缺全部 metadata fixture 与真实新 run bootstrap E2E 均通过。
- [x] 在调整 Agent、Coda、allowlist 或 lifecycle 策略前，恢复 turn-contract、command-shape、
  runtime-receipts、setup-transaction 和 Stop hooks 的 focused selftest 全绿。
- [x] 为文档展示的命令增加端到端 conformance fixture，证明用户复制的解释器/argv 形状
  与 Hook 实际接受的入口一致；不再让“文档可执行”与“内部绝对解释器可执行”分叉。

### 1.2 P0：统一 typed capability 与 effect 分类

- [x] 建立唯一 capability registry，至少包含 `id / script / effect / argv_validator /
  allowed_env / scope / privacy / proxy / guard / recorder policy`。
- [x] 将 effect 冻结为可测试的有限集合，例如 `local_read / local_verify / control /
  target / model_egress / repo_mutation`；路径是否 safety-critical 不能替代 effect 判断。
- [x] 修复 trusted `probe.py`、`workers.py`、control/review 入口被误标为
  `maintenance_action` 的问题；target/control 执行失败不得进入 maintenance blocker。
- [x] 注册 `timestamp_gate.py` 的纯读参数；注册 `check_run.py <active-run>` 的离线检查，
  将 `--replay-verify` 独立建模为 target capability，将 `--auto-peer-review` 独立建模为
  model/reviewer egress。
- [x] 保留 `peer_review.py`、`loop_journal.py` 和 proxy-aware target Tool 的窄入口；禁止把
  整个 safety-critical manifest 粗暴变成可执行白名单。
- [x] 保持不含 URL 的本地 `rg/grep` 不进入 outbound privacy；继续阻止 run/project/operator
  identity、secret、PII 被发送到目标或外部 reviewer。
- [x] tracked `.claude/settings.local.example.json` 固定 `permissions.allow=[]`；ignored 本机
  settings 只要出现任何 auto-allow 就由 bounded/no-leak hygiene preflight HOLD。该检查只
  收缩 Claude 原生自动批准面，不冒充 Hook/capability registry 的 authority/safety 边界；
  仓库自身 `.gitignore` 与 publication gate 同时阻止 operator-local settings 被误跟踪。

### 1.3 P0：统一 Stop 终态与 Coda

- [x] 把 Stop 输出冻结为互斥联合类型：`NORMAL_CODA | TARGET_DENIED |
  MAINTENANCE_BLOCKED`。
- [x] 固定 deny/blocked envelope 绕过普通 Coda validator；不得出现“按要求输出五行后，
  又因 Coda 多动作被第二个 validator 拒绝”的循环。
- [x] 为 Coda 增加稳定错误码和具体谓词，例如 `CODA_MISSING`、`CODA_TRAILING_FENCE`、
  `CODA_MULTIPLE_ACTIONS`、`CODA_WRONG_FRONT`；保留一个具体下一动作，但不要求命中工具名。
- [x] 将文本 Coda 改为结构化 `cycle_end.next_action` receipt 的投影；自由文本解析只
  作为兼容层，不能继续承担唯一控制契约。
- [x] 按 denial 类型区分恢复语义：前置条件可重试、命令形状可替代、需要新 operator
  authority、硬安全拒绝；不再用“所有失败必须相同 action hash 成功”覆盖不同 effect。

### 1.4 P0：把 anti-drift 从 mtime 改成语义新鲜度

- [x] 保留全图 Reason pass 与 knowledge-first；优化目标是删除仪式性状态写入，不是削弱
  前沿重读、知识接地或证据约束。
- [x] 删除 `frontier.md` 15/30 分钟 mtime stale 和“Read 后必须 Edit”的规则；禁止为了
  freshness 对 canonical 文件做无语义 touch/edit。
- [x] 建立 Reason-pass receipt，至少绑定 `cycle_id / frontier_digest / evidence_digest /
  coverage_digest / read_at / chosen_front / reason`。
- [x] 只有 canonical 输入发生变化而本轮尚未重读/裁定，或连续周期没有语义进展时才提醒；
  内容未变时允许只读确认。
- [x] 用 journal/receipt/Agent 状态判断 operational liveness，用 digest/coverage/evidence
  delta 判断 trajectory convergence；二者不得混成文件时间戳。

### 1.5 P1：Guard、网络归因与离线分析能力

- [x] 将 HostHealth breaker 从单一 host 计数升级为至少 `(egress_route, host,
  error_class)`，区分 `proxy_connect / proxy_tls / local_dns / target_tls / target_reset`。
- [x] 只有可归因于目标的连续失败才打开 target-host breaker；proxy/local 出口故障进入
  独立 breaker，并提供 cooldown 后的 half-open lease、确定性时钟测试、有界 jitter/
  backoff 和结构化 provenance。
- [x] 保留真实请求计数和全局预算，不把 warning 当请求；阈值调整必须由 fixture/bench
  证明，不能用简单调大数字掩盖错误归因。
- [x] typed `artifact_view.py` 已提供有界 range/search/strings，`js_inventory.py inspect`
  已提供 active-run 单 evidence artifact 的 2 MiB/64-candidate/64 KiB 脱敏 JSON 分析；两者
  都经 exact `local_read` capability、safety-critical manifest、secure-open/identity fence
  与 fixture 接线；JS 模型可见输出不携带原始内容或其 unkeyed digest，避免低熵秘密枚举。
  继续禁止任意 `python -c`、`awk/xargs`、重定向、`pip/cp` 或自定义网络脚本。
- [x] 超大响应/JS 的流式保存与字节范围已有 `probe.py` 的受控入口、receipt 与回归覆盖；
  结构化本地检索的剩余接线由上一项承担。
- [x] **已决策（本轮不准入）**：不新增 live WebSocket capability。当前缺少复用统一
  raw-socket proxy、帧/消息/字节/时长预算和握手/消息 recorder 的完整 transport；在这些
  mandatory services 与回归具备前，裸 shell、自定义网络脚本或仅靠 URL 文本识别都会形成
  第二出口，必须继续拒绝。未来若重启该能力，需单独更新架构和安全复审。

## 2. 三段 Run Macro-Stage 与统一工作计划

`S1 / S2 / S3` 是可回退的运行目标视图，不是新的 Router phase、canonical 真值或
单向瀑布。`Root / Hunter / Reviewer` 是每段内部反复运行的小周期角色，不是三个只走
一次的大阶段；`Setup` 是循环前置，`Report` 是持续投影并在 S3 完成收口。Macro-Stage
只表达当前小周期服务于哪个运行目标。事实仍由 `runs/<dir>` canonical 文件、artifact、
receipt 和 journal 承载；`state/work_plan.json` 等计划投影必须可删除重建。

```text
信息收集 --exit gate--> 渗透测试 + 持续复审 --closure-ready--> 最终收口
    ^                         |                              |
    +---- 资产/知识缺口 -------+---- 新证据/复审缺口 ---------+
```

### 2.1 S1：信息收集

- [ ] 阶段计划覆盖 scope、输入来源、资产/应用聚类、技术栈、knowledge/xday 命中、
  coverage debt、初始 hypothesis/front、预算和停止条件。
- [ ] 优先并行互不依赖的 `local_read/local_verify` lane：recon ingestion、已有 knowledge、
  静态 JS/API 和资产聚类；公开资料研究必须单列为 `model_egress`/open-world effect，经过
  timestamp、privacy 与 egress gate，不能伪装成离线只读。
- [ ] exit gate 至少要求 scope/资产 inventory 可解释、distinct app/高价值资产已归属、
  coverage ledger 与初始 fronts 已建立；“还没收集完互联网”不是阻止转阶段的理由。
- [ ] 信息收集只产生 observation/phenomenon/lead，不能直接确认 finding 或完成 coverage。

### 2.2 S2：渗透测试与持续复审

- [ ] 每个 cycle 在动作前生成 lane plan：当前 front/hypothesis、expected signal、control、
  effect、assets、dependency、request budget、drop/stop condition、merge owner。
- [x] 每个 Agent 返回后立即执行 candidate/refutation merge review；finding 晋级、高危结论、
  多 Agent 冲突和连续低信息增益时触发 checkpoint review。
- [x] 同一资产默认只有一个 `target` lane；`local_read/local_verify` 可并行，Reviewer 若调用
  外部模型则显式记为 `model_egress`。所有 target lanes 共用全局 request budget/host health，
  所有 model egress lanes 共用独立出境预算。
- [x] exit gate 要求高价值 fronts 已确认、证伪，或按硬规则/evidence-backed Type B 完成
  close/defer；Type A 仍保持 open/deferred 并阻止 closure-ready。所有 Agent 均须
  merge/adjudicate，coverage/review debt 可解释；报告存在不等于 closure-ready。
- [x] 新资产、新技术栈或知识缺口可回到 S1；不为保持阶段单调而忽略新信息。

### 2.3 S3：最终收口

- [ ] 入口先生成 closure-gap plan：open/deferred fronts、coverage、evidence maturity、
  replay、report parity、review ledger、retrospective、Cron/loop 终态。
- [ ] 主要使用 verify、independent-review、report-parity Agent；不再盲目扩大 target probing，
  但 closure review 发现实质缺口时必须重开 front 并回到 S2。
- [x] Single Synthesizer 保持 report/finding/review disposition/closure 单写者；Agent/reviewer
  只提供候选与挑战。
- [x] final gate 继续由 `check_run`、独立 review、report/evidence parity、零未合并 Agent、
  retrospective 和 terminal journal evidence 共同决定。

### 2.4 Root → Hunter → Reviewer 小周期

- [x] 每个小周期由 Root 重读 canonical delta，选择 active front/control object，生成或刷新
  work plan，并先完成 `delegation_decision`；仅 `SERIAL_AGENT/PARALLEL_AGENTS` 创建真实
  assignments，`ROOT_DIRECT` 只写机械理由和原子动作 receipt。
- [x] Hunter 执行一个或多个 lanes；复杂串行工作也由真实 Agent 承担，effect-disjoint lanes
  才并行，Root 只在机械满足 `ROOT_DIRECT` 时兼任单个原子 Hunter 动作。
- [x] Reviewer 对本周期的 observation/candidate/refutation、控制组、证据引用、重复与越界做
  结构化复核；普通周期可用低成本 review lane，finding 晋级、高危冲突和 S3 completion gate
  必须升级为符合作者/独立性矩阵的 reviewer。
- [x] Root 作为 Single Synthesizer 消费 Hunter return 与 Reviewer disposition，完成 merge、
  adjudicate、front/coverage 更新，并只输出 `continue / replan / stage-transition / blocked /
  closure-ready / complete`；后两者只允许 S3 final gate 全部通过后使用。
- [x] journal/receipt 显式关联 `cycle_plan -> hunter_attempts -> review_disposition -> cycle_end`；
  Hunter done、Reviewer PASS 或文本 Report 都不能跳过 Root 合并裁决。

### 2.5 `xunji.work-plan.v1` 与 receipt

- [x] Macro-Stage 入口写 stage-entry plan，定义 objective、输入 digest、资源上限和 exit gate；
  每个 cycle 只写同一计划的 replan，不再建立平行的 iteration/phase 计划真值。
- [x] 新证据、canonical fingerprint、front topology、coverage/review debt、barrier、预算或冲突
  发生 material change 时使旧计划 stale 并写 cycle replan。
- [x] 冻结 `xunji.work-plan.v1`：Root 基于 canonical state 选择并声明 `macro_stage`，Schema 为
  `macro_stage / objective / inputs_digest / replan_reason /
  lanes / execution_mode / merge_owner / exit_gate`。
- [x] 每条 lane 至少包含 `id / role / effect / assets / dependencies / expected_evidence /
  stop_condition / request_budget`。
- [x] journal 记录 `stage_plan / replan / stage_exit` digest；Task/Todo 只证明已规划，不能
  替代 front、assignment、Agent receipt、evidence 或 closure。
- [x] 明确组件 owner：Root 选择 Macro-Stage；`run_model.py` 只派生候选 readiness/blockers 并
  检查声明与 canonical state 是否一致，不替模型选择策略；`workers.py` 规划 lanes；
  `turn_contract.py` 绑定 cycle plan/delegation decision；`context_pack.py` 生成 exact lane
  context；`loop_journal.py` 记录计划事件；`check_run.py` 校验 stage exit/merge；
  `run_gate.py` 只机械执法，不替模型选择攻击策略。

## 3. Delegation-first Agent/Worker 调度

Worker/Lane 是逻辑工作单元，Agent 是运行时执行者。计划先拆 lanes，再由 scheduler 根据
依赖、副作用、预算、运行槽位和 merge capacity 映射到一个或多个 Agent。

### 3.1 委派决策

- [x] 每个 EXECUTE cycle 在 Root target action 前记录 `delegation_decision`，取值为
  `ROOT_DIRECT | SERIAL_AGENT | PARALLEL_AGENTS`，并绑定 plan/lane digest 与机械理由。
- [x] `ROOT_DIRECT` 只用于一个廉价、明确、原子的步骤；复杂但依赖串行或共享主动 barrier
  的工作默认交给一个专业 Agent，若 barrier 下没有可执行 lane 则进入 `blocked`，不能把
  “不宜并行”偷换成 Root 自己长链执行。
- [x] 存在两个以上 effect-disjoint lanes 且预算/merge capacity 允许时使用并行 Agent；
  不再把 `open fronts >= 4` 当日常使用 Agent 的唯一触发器。
- [x] 现有 `>=4 diverse fronts` 规则在新 scheduler/bench 证明前只保留为强制 breadth
  safety net；不得把阈值简单降为“两个任务必并行”。
- [x] coordinator mode：发现有效 delegation lane 后，Root 先只使用 plan/assign/
  message/merge/control 工具；完成派发或形成合规 `ROOT_DIRECT` receipt 后才开放目标动作。

### 3.2 Lane planner 与 effect overlap

- [x] `workers.py suggest/plan` 从 front/asset 排名升级为 lane planner，输出
  `effect_class / dependency / request_cost / expected_information_gain / merge_cost`。
- [x] 即使只有一个 front/asset，也能提出 offline JS/source analysis、target probe、verify、
  review 等角色化 lane；“一个 front”不能自动推导为“没有委派机会”。
- [x] role 与 effect 分栏：Hunter/Verifier/Reviewer/Synthesizer 是 role；effect 只使用
  `local_read / local_verify / control / target / model_egress / repo_mutation`。overlap matrix
  允许 local read/verify 并行，target 同资产默认互斥，model egress 使用独立出境预算，
  control/repo mutation 与 canonical synthesis 保持单写者。
- [x] overlap key 至少绑定 `run + asset + front + lane + effect`；Reviewer/Verifier 的有限例外
  也必须显式预算和 receipt，不能靠 role 名称自动放宽。
- [x] scheduler 的并行度取 `independent_lanes / runtime_slots / request_budget /
  merge_capacity` 的共同上限，Agent 数量不能线性放大目标请求率。
- [ ] 每段采用不同默认倾向：S1 高 offline fan-out；S2 选择性 target/verify 并行；S3 低
  target fan-out、高独立 review/parity breadth。

### 3.3 委派、上下文与合并闭环

- [x] 由 `PlanWork + AssignWork`/当前 Python 等价入口完成统一 delegate 操作：`plan ->
  assign -> exact context -> Agent launch -> launch receipt`；不另造平行 Tool，`workers.py`
  台账也不能继续被误当自动编排器。
- [x] context pack 使用 `agent-id + front + asset-digest + attempt` 唯一路径，顶部写 exact assignment/front/
  assets/effect；同 front/role 的不同资产或 attempt 不得覆盖上下文。
- [x] context pack 从完整 frozen lane/front 按 assignment 重新计算 0–3 个 registry-backed
  prepared capability；只投影窄肯定、唯一可绑定的 GET 或单 evidence artifact 本地读取，
  否定/完成/条件/歧义/越界均为 0。投影不授予权限，Hook 仍全量重验；历史 assignment
  只重放 bundle 验证过的 frozen context，不因后来 role/scaffold 维护而生成新 argv。
- [x] Agent start/return/failure 只接受 matching assignment、tool-use-id、runtime agent id 和
  exact asset package；过滤 active-run hook 收到的无归属 SubagentStop。
- [x] Agent 返回自动生成 merge draft 与 per-asset outcome；`done` 必须进入 merge/refute/
  blocked/failed disposition，不能长期停在 done-but-unmerged。
- [x] synthesizer 设为 Root-owned singleton，不作为可重复 fan-out 的普通 role；任何 Agent
  输出仍只能是 phenomenon/candidate/refutation/barrier/artifact pointer。
- [x] 修复 coordination epoch 语义：PreToolUse 与 Stop gate 统一使用
  `coordination_signature + fanout_epoch_started_at`，bare continue 不重复索要已满足的 Agent。
- [x] **已决策（不采用消息作为协作真值）**：Agent 状态、追问、取消和实质结果继续落
  assignment/receipt/run dir；runtime notification 只作唤醒信号，`SendMessage` 仅保留外部
  operator stop/no-resume 的窄恢复语义，不能成为 evidence、authority 或 merge 证明。
- [ ] 代码维护型并行 Agent 可选择 worktree 隔离；live engagement 的 canonical run 写入仍
  遵守单写者/CAS/merge contract，不因 worktree 建立第二 evidence store。

## 4. 实施顺序、验证与度量

### 4.1 Delivery Wave（依赖顺序，不是状态轴）

W0/W1 已完成生产代码、synthetic/fault fixtures、冻结 staged candidate 全量回归、真实
Claude Code/DeepSeek 主驾驶 E2E 与 fresh-context 独立复审。W2 核心垂直切片已由真实
Claude 主驾驶完成 `work-plan→delegate→Hunter→Reviewer→Root finish→canonical→cycle-end`：
离线约束只生成 Hunter/Reviewer 两条 lane，无目标数据按 barrier/blocked 处置，front 保持
open，零目标/Web 请求且 Coda 精确投影 receipt。W2 整体仍保持未完成：
A/B scheduler 收益、stage 默认资源策略和代码维护 worktree 隔离仍是验收/剩余工作；消息
控制通道已决策不作为协作真值。W3 已完成 route-aware guard、流式大响应、typed 本地有界
artifact/JS 分析与 opt-in 工具摩擦投影；live WebSocket 已明确 NO-GO，不以第二出口补缺。
长期 A/B 收益、其余协作指标与完整可观测性仍开放。

- [x] **W0 — contract/fixture 先行**：冻结 capability/effect、Stop union、work plan、
  delegation decision、lane、Agent event 和 error-code schema。
- [x] **W1 — 当前 P0 修复**：恢复 turn-contract 基线，修 effect/maintenance 分类、
  Stop/Coda 终态和 semantic anti-drift。
- [ ] **W2 — Macro-Stage 与主动调度**：实现统一 work plan、Root/Hunter/Reviewer 小周期、
  lane planner、serial/parallel
  Agent、effect overlap、自动 receipt/merge 和 coordinator-like Root gate。
- [ ] **W3 — Guard/分析能力与可观测性**：route-aware breaker、typed offline artifact/JS
  capability 和工具摩擦投影已实现；剩余工作是长期 A/B/协作指标与在完整 transport 契约后
  重新评估 WebSocket，不把当前 NO-GO 写成已实现。

### 4.2 必备 fixtures 与测试

- [x] capability registry：文档命令 allow、未知 argv/env/shell shape deny、offline
  `check_run` 与 live replay/model egress 分流。
- [x] receipt/effect：trusted target/control failure 不生成 maintenance blocker；真实 repo
  mutation 仍 fail closed。
- [x] Stop：三种互斥终态、fixed envelope、trailing fence、same-turn retry 和跨新 prompt
  expiry 的完整 `main()` 回归。
- [x] anti-drift：内容未变只读不写；digest 改变未重读才提醒；连续无语义进展触发 trajectory
  review 而非 touch。
- [x] Agent：单 front 的 offline+target+verify、effect overlap matrix、epoch 跨 continue、
  四 front shared/diverse barrier、unmatched SubagentStop、return-to-merge。
- [x] Macro-Stage：S1/S2/S3 正常转换、S2/S3 回退、失效 plan replan、计划不能伪造 evidence/
  coverage/closure。
- [x] 小周期：Root plan 先于 Hunter attempt、Hunter return 必经 Reviewer disposition、Root merge
  后才允许 cycle end；缺失、重复、乱序或 stale receipt 全部 fail closed。
- [x] work-plan transaction v2：native-v1/legacy migration、content-addressed archive lineage、
  四个 crash window 与重试产生同一 receipt/hash/current state；缺锚或断链不得现场补信任。
- [x] Agent runtime：真实 Claude async `SubagentStop.last_assistant_message`、同步
  Start→Stop→Post 顺序、跨 session/重复/歧义匹配，以及 journal-fsync 后 projection crash 的
  幂等 reconcile；启动 ack 不能冒充最终结果。
- [x] Agent runtime synthetic/fault contract：无 causal identity 的 same-message Start fail
  closed，child 首条 prompt/完整 token/final assistant envelope 严格绑定；runtime journal
  rollback+fsync、immutable result 目录 crash/retry、projection diagnostic absence barrier、
  `success_generation` CAS 与 post-success failure debt 均有回归。
- [x] Agent launch type contract：canonical role→type 精确映射；missing/null/blank、大小写/
  首尾空白、`general-purpose`、role swap、parent requested 与 actual Start/Stop type mismatch
  全部 fail closed，`description` 不能提供或修复 authority。
- [x] Global completion Reviewer：exact assignment-free type+prompt、真实 parent→Start→Stop、
  current S3 plan/evidence hash/completion bundle 与四项显式 :PASS checks；parent-only/no-Stop、
  wrong actual type、mixed assignment fields、prompt 后缀、latest FAIL/running/stale、重复 verdict、
  任一显式 FAIL/WARN/false 和无 assignment/merge projection 都有回归，并证明它与独立
  `peer_review.py` ReviewReceipt 互不替代。
- [x] stale plan settlement：`chains.md`/`hints.md` create/modify/delete 使 plan stale；只允许
  exact returned/failed Reviewer settlement，或 typed `cancel-unlaunched` 前向恢复事务退休零
  launch-fact 非 Reviewer，且 cancellation 不生成 result/review/merge/cycle-end。
- [x] lifecycle activation：formal `prepared_not_active` run 的 create identity 与后续 activation
  attempt 分层冻结；pointer 前/后 crash、same-target、revocation、cross-operation 与 tamper retry
  都保持精确 claim 且不残留 authority。
- [x] lifecycle authority durability synthetic/fault contract：active/claimed/revoked、target
  contract、claim/pending durable absence 与 SessionStart selection consume 具有 file/directory
  barrier 和 exact retry；不宣称 builder 整树或 SessionEnd create/clear 已 durable。
- [x] structured edit path：递归覆盖 Edit/Write/Update/MultiEdit/NotebookEdit 所有 path-like 字段、
  run-relative/absolute/alias/symlink/nonexistent tail，并让 deny/success receipt 绑定同一 normalized set。
- [x] guard：proxy/local/target error attribution、half-open、共享多 Agent 预算和真实 request
  count。
- [x] 真实操作者离线 E2E：新 run setup、Reason pass、exact 两 lane 计划、真实 Hunter/Reviewer
  Start/Stop、review-disposition→Root blocked→canonical 顺序、typed cycle_end/Coda；无 E-id、
  finding、假 closure 或 target/Web 请求，Agent 不撞 tool-call hard cap。

### 4.3 度量与完成门

- [x] Bench 已记录 time-to-first-evidence、front/collaboration coverage、request budget、
  conflict 和 false-positive 等当前基础指标。
- [x] 对显式 opt-in fixture，runtime/Bench 已记录 plan-bound child claim 的 denial、invalid-argv、
  same-turn retry、Xunji non-denied terminal、prepared capability offered/hit 与首个可证明
  non-denied terminal 时延；unknown、归因 unknown、阈值失败和 A/B fixture 集变化均 fail closed。
  该 terminal 不等于原生权限批准、effect 执行成功或 evidence 形成。
- [ ] 补齐 time-to-first-delegation、有效 lane 捕获率、Agent useful-yield、重复目标请求、
  merge debt、信息增益、provider token budget 和 closure reopen 正确率，并统一统计口径；
  当前没有 provider usage receipt，不编造 token 节省。
- [ ] 用 A/B fixture 比较 Root-direct、serial-Agent、parallel-Agent；只有质量/速度/覆盖收益
  超过调度与合并成本时才把 soft recommendation 升为 hard gate。
- [x] 当前 `selftest_all.py` 为 80/80，focused、Bench、rule、template、runtime-boundary、
  local hygiene 与 diff check 均通过；可信入口、compiled floor 与 safety-critical manifest
  已恢复一致，完成门不再携带旧的 3-entry HOLD。
- [x] safety-critical 变更完成作者感知的独立 fresh-context 复审并记录 disposition；
  external assistance 被禁用，本轮不声称存在异构外部票。
> 治理边界：`runs/test0_20260716` 的 E-006 maturity、Reason/marker、Agent merge、coverage
> 和 independent review 属于该 run 的 canonical 修复，不复制进项目 TODO 充当实现进度。

### 4.4 非阻断 hardening backlog

- [ ] 评估在受保护 state/agents/context 目录上使用 descriptor-relative open/unlink/rename，
  进一步收窄恶意本机并发替换 ancestor/path 的 fd-level TOCTOU；先用跨平台 fault/soak 证明，
  不为理论加固破坏当前单写者和 macOS/Linux 兼容性。
- [ ] 设计不可归属 assignment 的畸形 orphan `SubagentStop` quarantine。它当前会留下明确
  lifecycle debt 且不能形成 return/merge；若改为全局 tombstone barrier，必须证明不会误伤
  其他合法在途 Agent。

## 5. 共享工程与输入链剩余工作

本节只保留原 `todo1.md` 审计中仍未完成或需要 decision gate 的事项。已经进入当前实现和
Maintenance Checkpoint 的 setup-source、single-owner transaction、activation CAS、maintenance
authority 等工作不重新伪装成未完成计划；发现回归时按其现有 contract/fixture 修复。

### 5.1 输入适配与 normalizer 增量

- [ ] 在现有 URL/recon/Markdown/普通 JSON 基线上，按格式逐类评估 HTML/PDF/DOCX/text/OCR
  adapter；每类先有 deterministic inventory、source span/ref、大小/TOCTOU/path 边界 fixture，
  再允许 AI 只选择机械 token/ref 生成候选。
- [x] 固定 `--ai off | local | external` 的 effect 与 receipt：`off` 为确定性路径，`external`
  只接收不可逆脱敏 surrogate 并记录 provider/model/schema/redaction hash；`local` 在可信
  provider registry 落地前显式 fail closed。模型不能恢复 secret 或铸造 scope、authority、
  finding、certainty、severity、pointer、Cron 或 closure。
- [ ] `--intel-url` 保持独立、默认关闭的 candidate capability；若启用，使用专门只读 fetch
  contract，并逐跳执行 DNS/IP、scope、privacy、credential、timeout、body/MIME 和 redirect gate，
  不能借 local setup metadata 通道联网。
- [x] URL/recon/Markdown/普通 JSON 输入矩阵已覆盖 userinfo、symlink/path traversal、source
  mutation、prompt injection 与 pointer/Cron fail-closed 等关键边界。
- [ ] 补齐域名/IP/IPv6/IDN/非法端口，损坏/未知/超大/重复 JSON，Markdown code fence/表格/
  多域，PDF/DOCX/OCR 抽取失败和 context bomb；任一失败仍不得移动 pointer 或创建 Cron。
- [x] normalizer 上线硬门保持“零无来源高风险字段、零 pointer 错提、零 source instruction
  执行”；AI 相对 deterministic-only 没有可测收益时不扩大格式面。

### 5.2 Canonical parser 与复审产品化

- [ ] 收敛 frontier/status、evidence、constraints、review ledger 和 agent-result parser，输出
  typed record、source span 与显式 schema error；`cross_run/workers/coverage/saturation/state`
  等消费者逐步移除重复正则，禁止把格式错误吞成空列表。
- [ ] 为 canonical/legacy/重复 ID/code fence/中文标点/恶意或超长字段建立 parser contract
  fixtures；共享 parser 变更必须证明所有消费者 verdict 不漂移。
- [ ] `peer_review.py` 增加 `live-run | maintenance-diff | plan | docs` scope kind，各自使用正确
  bundle/rubric；maintenance 不伪装成 `report.md`，plan 不套漏洞报告成熟度规则。
- [ ] review 输出固定 `scope_kind / reviewer identity / reviewed hash / context limits /
  backend failures`，原始输出与 Root disposition 同记录；文件或 diff 改变后自动 stale。

### 5.3 Decision-gated AI 候选结构化推广

- [ ] 在 setup normalizer 之后，按 `Agent output -> maintenance review -> evidence candidate ->
  JS/API -> scope -> cross-run/knowledge -> report/retrospective/hints` 的顺序逐项评估；每一项
  单独冻结 candidate schema、source ref/hash、机械 validator、canonical writer 和 rollback。
- [x] AI 在当前已开放边界只做不稳定输入到稳定候选结构的转换，不能掌握 assignment/merge、
  reviewer independence、evidence maturity、scope authority、finding/severity 或 closure 裁决。
- [x] 当前 Agent/review/evidence/scope/report 候选已分别绑定 assignment/front/assets/artifacts、
  reviewer matrix/bundle/diff hash、recorder/source bytes/operator authority/knowledge validator/
  report-parity gate；未来新候选面仍须逐项证明相同绑定，不能从本项自动继承准入。
- [ ] 每类候选用 benchmark 证明比 deterministic parser/人工誊录有净收益后才开启下一类；
  无收益、错误不可机械验证或扩大 model egress 时明确 supersede，而不是一次铺满。

### 5.4 测试、CI 与可复现开发环境

- [ ] 建立 CI：PR 运行 closure/rules/templates/runtime-boundary/local-hygiene、focused selftests
  和 bench；Linux 跑全量 suite，macOS/Windows 至少覆盖路径、编码、atomic replace、proxy、
  setup/turn-contract/guard，Python 最低版与最新支持版组成矩阵。
- [x] 已移除对 `tests/` 的一概禁止，P0 fault injection 不等待目录重构。
- [ ] 逐步把大型模块尾部 selftest 搬到正式 suite，同时保留 CLI `--selftest` 兼容入口。
- [x] `pyproject.toml` 已声明 Python 最低版本、dev extra 与 Ruff 基础配置。
- [ ] 固定 dev dependency lock/解析方式；CI 增加 `ruff check` 和 schema/model/transaction 等
  纯逻辑的最小 type-check，不以一次类型化全部历史工具为前置。
- [x] 本地提交前检查已固定 `git diff --check`、敏感文件扫描和 review fingerprint。
- [ ] CI artifact 只允许 bench JSON/失败日志，不上传真实 target/run 产物；随 CI 落地验收。

### 5.5 文档、模板与 backlog 真值

- [x] 清理 ROADMAP/selftest 中已过时的“无法度量/尚未落地”叙述；区分 scorer 已存在与
  fixture/A-B 仍不足。未实现 adapter 不得写成稳定入口。
- [x] Agent instruction 垂直切片：versioned manifest、common+role delta+scaffold 组合、
  assignment bundle，以及 source/artifact SHA drift gate。
- [x] Router/WORKFLOW/reference/skill 的 owner-specific generated/excerpt 治理已有 conformance/
  drift gate；手工复制受 owner 对应检查拒绝，不再等待一个通用文本去重器。
- [x] `check_templates.py` 覆盖 Agent manifest/common/role/scaffold、手工 common 重复与 bundle
  prompt parity。
- [ ] 其余 run templates 与完整 closure audit：skill→tool、tool→selftest、
  template→scaffold、schema→validator、docs claim→contract 接线。
  当前治理不变量：`TODO.md` 是唯一前向 backlog，`docs/ROADMAP.md` 只保留研究候选/度量
  结论；原 `todo1.md` 的历史处置已并入第 6 节。

- [ ] 为正式待办逐步补齐 owner、dependency、size、acceptance、status、evidence；不得再把
  同一计划复制成另一份长期清单。

### 5.6 Benchmark 与本地卫生

- [x] setup-source/normalizer pilot bench 已覆盖字段 precision/recall、无来源字段、幻觉/漏资产、
  schema failure、Root 驳回代理指标、source instruction 与 model-egress leak。
- [ ] 补齐 parser drift、done-but-unmerged、冲突未裁决、Agent 越界、stale receipt/partial backend，
  以及结构绿但 review hash/Cron/report parity 失败的 closure negative fixtures。
- [ ] 增加 pointer 原子性失败 benchmark，并让协作指标与第 4.3 节共用同一 A/B 口径；事务
  fault selftest 已存在，但不能冒充 benchmark 指标。
- [x] `check_local_hygiene.py` 以 warning 识别根目录未跟踪 HTML/replay/常见截图与 OCR 命名等现场产物，
  只提示迁入 ignored run/evidence 目录，不读取内容、不自动删除。
- [x] 提供 `clean_scratch.py --dry-run --older-than <days>` 等限定范围、默认不删除的 TTL 工具；
  自测优先使用系统 temp 并 finally 清理，cache/review/OCR/browser/bench 保留策略写入 onboarding。
- [x] 统一 `probe` / `render` / `fetch_assets` / `classify_hosts` 输出 owner：live 产物绑定
  run canonical bucket，standalone 产物绑定 `tmp/<tool>/<invocation>/`；旧散落产物由默认
  dry-run、body/sidecar 成组、哈希 manifest 的迁移器处理，不自动晋级 evidence。

### 5.7 Decision-gated 重构

- [x] **已决策（当前不准入 repository 抽象）**：只有至少两个真实消费者并证明耦合成本时，
  才实现最薄 adapter；不为假想消费者提前抽象。
- [x] **已决策（不做无收益的预拆分）**：大型模块只在触碰对应边界且有可测收益时拆分，
  不作为 P0 或 Macro-Stage 前置；拆分必须保持 CLI、error/receipt、canonical verdict 与
  selftest 兼容。
- [ ] 常驻上下文减肥按 token/字符预算和漏规则 fixture 验收：`CLAUDE.md` 只保留硬原则，
  Router/WORKFLOW/skills 各守职责，loop prompt 不重复全量 workflow；不能只凭“变短”判完成。

## 6. 原 `todo1.md` 合并处置（2026-08-11）

本节保存原审计文件的唯一有效增量：它不是第二份计划，也不复刻已经由 architecture、
contract、fixture 和 review record 承载的长篇论证。状态按当前工作树重新裁定；旧隔离分支
`f1a186e` 不在当前 HEAD 祖先链，因此其“全部完成”不能提升这里的状态。

| 原审计主题 | 当前处置 | 归并位置 / 依据 |
|---|---|---|
| P0 privacy/command channel | 已实现 | 1.2 capability/effect/privacy gates |
| setup transaction、single pointer owner、activation CAS | 已实现 | 1.1、4.2 lifecycle/transaction fixtures |
| maintenance authority | 已实现但原 DSL 已被取代 | 自然语言 operator intent + typed effect/protected-path receipt；不恢复 scope/reason DSL |
| setup-source v1 | 已实现 | 4.2 setup/lifecycle 回归与现行 Architecture |
| URL/recon/Markdown/JSON normalizer | 已实现基线、格式面部分完成 | 5.1；HTML/PDF/DOCX/text/OCR 仍未实现 |
| `--ai off/local/external` | 已实现现行契约 | 5.1；local 未注册时 fail closed，不宣称本地模型可用 |
| `--intel-url` | 未实现 | 5.1 独立 candidate capability |
| canonical parser 收敛 | 未实现 | 5.2 typed parser 与 drift fixtures |
| maintenance/plan/docs review scope | 未实现 | 5.2；当前 `peer_review.py` 仍缺 `scope_kind` 产品契约 |
| Agent 候选、证据与 closure authority | 已实现当前边界 | 2.4、4.2、5.3；新增候选面仍逐项准入 |
| CI、正式 tests、dev lock/type-check | 部分实现 | 5.4；本地规则/配置已具备，CI 与迁移仍未实现 |
| 文档/模板漂移治理 | 已实现 owner-specific 基线、closure audit 部分完成 | 5.5 |
| 本地卫生、scratch TTL、产物 owner | 已实现 | 5.6 |
| CCB/TypeScript/Grok 迁移 | 已决策不纳入当前路线 | 本文件头部与 5.7；未来需 operator 重新立项 |

合并后删除原 `todo1.md`（原文件未被 Git 跟踪，删除后不能从仓库 Git 恢复）。其已接受的
复审发现保存在 `review/records/2026-07-13-xunji-optimization-plan-review.md`，逐主题当前
处置保存在本节；前向状态只看本文件。
