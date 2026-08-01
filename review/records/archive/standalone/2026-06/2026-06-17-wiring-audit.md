# 2026-06-17 接线审计:死功能与未接触发(Codex 异构复审)

## 范围与方法
纯静态"接线"审计,找一类结构性缺陷:**某能力(工具/flag/产物/钩子/检测器)存在且能用,
但运行循环里没有任何指令在对的时刻触发它 → driver 永不自发调用 = 死功能。**
判例:knowledge_match.py 当初"列在 ROUTER 工具清单"却没进运行循环,整场不查知识库(已修)。

方法 = 能力清单(A:`tools/*.py` 每工具+每有意义 flag/模式;`.claude/hooks/*`;`sentinel/*`;
每个产物)× 触发清单(B:`CLAUDE.md`/`docs/WORKFLOW*.md`/`docs/ROUTER.md`/`docs/cognition/README.md`/
`.claude/skills/*`)交叉比对,外加"产物→消费者""教义→机制"两向 + 正反悬空引用。
**不改代码、不跑实弹、不碰 runs/。** 标签沿用:TRIGGERED / LISTED-ONLY / ORPHAN / DEV-ONLY / ON-DEMAND。

## 复审后端(异构独立复审)
`codex exec -s read-only`(codex-cli 0.140.0)用同一份 brief 独立跑了一遍(~106K tokens),
Claude 作唯一整合者把 Codex 候选过证据门(候选≠裁决)。两边核心结论收敛;Codex 额外逮到
render 输出未消费两条(我原先低估)。分歧如实记录在末尾。

## 能力表(缩,只列缺口 + 关键判定)
| 能力 | 标签 | 触发在哪 | 证据 |
|---|---|---|---|
| `peer_review.py` 异构复审 + `check_run --auto-peer-review` | LISTED-ONLY/ORPHAN | 运行循环无,仅 ROADMAP+帮助 | 收口门只点名同族子代理 `WORKFLOW.md`/`ROUTER.md`;强工具只在 `ROADMAP.md:143` |
| `render.py`→`network.json`(观测 API 请求) | LISTED-ONLY | 无 | 产者 `render.py:156`;无消费指令 |
| `render.py`→`cookies.json`/`--cookies-file`(会话) | LISTED-ONLY | 无 | 产者 `render.py:164`;无"会话喂下一探"指令 |
| `probe.py DIFF` + `--samples`(受控差分) | LISTED-ONLY | 无 | Control 教义满篇,机制 `probe.py:349` 不被点名 |
| `rerun_deferred.py`→`coverage_rerun.json` | 弱/输出死端 | 仅 ROUTER 清单 | `rerun_deferred.py:90` 产 newly_reachable;无回并指令 |
| `fetch_assets.py`(N==M JS 完整性) † | LISTED-ONLY(我)/TRIGGERED(Codex) | 仅 `ROUTER.md:293` 清单 | 同 knowledge_match 病样,触发埋清单非判断时刻 |
| `pending_approval.md`(sentinel L3 队列) | ORPHAN | 无 | 产者 `sentinel/state.py:214`;docs 完全没有 |
| `alerts.md`(sentinel L2/L4) | LISTED-ONLY | 仅布局清单 `WORKFLOW-reference.md:22` | 循环里无人读 |
| `classify_hosts.py --hosts` | LISTED-ONLY | 无 | flag 在;文档只触发 recon-JSON |
| `evidence.json` | 死端(有意) | 消费者是 ROADMAP 项 | 只写不读;`ROADMAP.md:168` 推迟 |

健康(TRIGGERED,无需动):指纹飞轮 `knowledge_match`/`xday_match`/`kb:<id>`、`graph.py`、`workers.py`、
`setup_run`/`ingest_recon`/`classify_hosts`/`coverage.json`、`replay.py`/`--replay-verify`、
`probe --save/--run`/`.replay.json`、`scan.py`(opt-in)、`render --run`、四钩子、sentinel 钩子、四技能。
DEV-ONLY(正确不进循环):`check_*`、`bench`、`selftest_all`、`sentinel/replay.py`/`verify_layers.py`。
悬空引用:无断裂(`review/independent-reviewer.md`/`harmless-verification.md`/`templates/*` 都在;
`review/peer_review.json` 缺失但可选,有 `DEFAULT_CONFIG`)。

## 缺口与处置(本轮已接线 6 条,纯文档)
接线 = 在**已有教义**上挂**条件式提醒**("命中触发条件后才做、按目标适配"),非机械死步骤。

1. **[HIGH] peer_review 异构复审未接进收口门。** 硬收口门只引向更弱的同族子代理,
   ROADMAP 明写异构更强(同族只减 bias 不减 A2 盲点)。
   → 处置:`docs/WORKFLOW.md` Closure Discipline 独立复审条 + `docs/ROUTER.md` Reviewer 段,
   加"操作者接受数据出境且后端可用时优先 `peer_review.py --into-run`/`check_run --auto-peer-review`,
   否则退回 fresh-context 子代理"。**框法 = 同意时优先**(出境=operator-gated,不默认开)。
2/3. **[MOD] render `network.json`/`cookies.json` 产而不用。** 浏览器看到的 API 端点/会话蒸发。
   → 处置:`docs/WORKFLOW-reference.md` Run-directory-layout render 处加条件消费:
   "network.json 有 API 端点→折进 surface/frontier;需会话→`--cookies-file`/`probe -H Cookie` 复用"。
4. **[MOD] probe DIFF 未被 Control 教义点名。** → 处置:`docs/WORKFLOW.md` Evidence Gate 加
   "当 control 是 baseline-vs-mutant 差异时,`probe DIFF urlA urlB` 一调即出,reliable_differential
   仅在两侧各稳且互异时为真(`--samples` 抬稳定门)"。
5. **[MOD] rerun_deferred 输出/触发未接 deferred 重访。** → 处置:`docs/WORKFLOW.md`
   "Can't reach ≠ is safe" 条加"出口变化且有 deferred 资产→`rerun_deferred`;newly_reachable=新攻击面,
   开 front 写决策,别留在 coverage_rerun.json"。
6. **[MOD] fetch_assets 触发埋 ROUTER 清单。** → 处置:`docs/cognition/README.md` Shallow Work Smells
   加"SPA 声称端点枚举完前,确认 fetch_assets 报 N==M"。

## 纪律红线核对
6 条均为条件式提醒,无一是"每台主机都跑 X":#1 卡同意+后端;#2/#3 卡产物确有内容;
#4 卡"证明本身即差异";#5/#6 卡"有 deferred 资产"/"SPA 上声称完整"。
会退化成盲扫的写法(把 peer_review/fetch_assets 改无条件)被明确否掉。
本轮改的全是教义文档,**不属安全关键码**(`.claude/hooks/`、`guard.py`、`sentinel/`),不触发安全关键码复审门。

## 我与 Codex 的分歧(如实)
- **fetch_assets †**:Codex 判 TRIGGERED(ROUTER:292 有"run before claiming…");我持 LISTED-ONLY
  (那句在工具清单非判断时刻,按项目自己的 knowledge_match 先例不够)。结论:无论标签,
  在判断时刻露出来低成本 → 保留并已接到 Shallow Work Smells。
- **evidence.json**:Codex 判 TRIGGERED("被 check_run 消费");我读为 check_run 写它/列白名单非读回。
  低严重度,两边都认同非有意义缺陷。
- **sentinel 产物**:Codex 提议把 driver 侧消费接进 Reason pass;我降为给操作者的设计问题(见下)。

## 第二轮:剩余项处置(操作者"全部修复")
- **#7 sentinel `pending_approval.md`/`alerts.md`** → 已接(**纯文档,sentinel 代码不动,保持 observe-only**):
  `WORKFLOW.md` Reason pass 加"若存在未处理项,选下一步前扫一眼、记 decisions 或交操作者"。
  坦白:observe-only 下动作其实已执行(只记不拦),接它=driver 自知 + 给将来铺路,当前价值有限。
  **明确不做**:翻 inline 强制审批=动 sentinel 代码、改"拦不拦"行为、过安全关键码复审、且 sentinel
  路线图要求先有实网误报数据才翻 → 另立项,本轮不碰。
- **#8a classify_hosts --hosts** → 已接:`ROUTER.md` 该工具描述加"无 recon JSON 时用 --hosts 接主机列表"。
- **#8b cleanup.py 何时用** → 已接:`WORKFLOW-reference.md`"收尾前清理"句点名 `cleanup.py --scratch`(默认 dry-run)。
- **#8c evidence.json 只写不读** → **不建消费者**。ROADMAP 明记 report 脚手架消费者待 R-1 用 bench 证明
  价值再建(measure-before-add 纪律);现在建即违纪。确认为有意推迟,不动。

## 改动文件清单
- `docs/WORKFLOW.md` — Closure Discipline 独立复审条(#1)、"Can't reach" 条(#5)、Evidence Gate(#4)
- `docs/ROUTER.md` — Reviewer 独立复审段(#1)
- `docs/cognition/README.md` — Shallow Work Smells(#6)
- `docs/WORKFLOW-reference.md` — Run directory layout render 处(#2/#3)、tidy 句点名 cleanup.py(#8b)
- `docs/WORKFLOW.md` — Reason pass 加 sentinel 产物消费(#7);`docs/ROUTER.md` — classify_hosts --hosts(#8a)
- 新增本记录 `review/records/2026-06-17-wiring-audit.md`

## 复查 + Codex 异构复审(改动落地后)
全面复查 10 条改动:引用准确性、纪律红线(条件式非机械)、矛盾/悬空、落点。我自审 PASS。
Codex 独立复审 diff(`codex exec -s read-only`)判 **WARN,1 条实质发现**:
- **network.json 描述夸大** —— 我写成"`/api·/rest·.do·.json` 请求",但 `render.py:152-157`:
  `api` 是过滤子集(进 stdout `api_requests`),`network.json` 实际写的是 `requests[:500]`
  **全量请求日志**(封顶 500)。已核 `render.py:156` 属实 → 已改 `WORKFLOW-reference.md`
  措辞为"全量请求(封顶 500),API 调用在其中;过滤子集另在 stdout `api_requests`"。消费指引不变。
- Codex 明确**未发现纪律红线违规**(逐条列出 sentinel/DIFF/rerun/peer/fetch 均条件式),无矛盾/悬空。
处置:采纳唯一发现并修;其余 9 条两边一致 PASS。`check_rules.py` 复跑仍绿。
