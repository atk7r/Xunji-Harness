# Xunji 项目待办

> 最后更新:2026-06-28。本文件记录跨会话的未决事项,避免被上下文压缩冲掉。
> 分两个独立项目:**父项目**(Claude/Codex 工作区)与 **deepseek-project/**(DeepSeek 实例)。
>
> **核心思想(勿忘)**:让 AI 自主、像人类猎手一样推理;框架只给判断纪律+接地知识+硬边界,
> 绝不做清单/playbook。扩展前过 grounding-vs-weapon 测试。详见持久记忆 `core-philosophy-ai-autonomy`。

## 0. 2026-06-28 优化落地计划(按阶段提交)

背景:对比 TianTi 与 2026 年 autonomous security agent / vuln-research agent 研究后,确认 Xunji 的优势仍是证据门、审计、硬边界、反过早收口;短板是评估闭环弱、能力 sensor 薄、Metacog 不显式、worker 摩擦大、hostile-content 风险没有独立建模。

原则:

- 不把 Xunji 改成 TianTi;吸收其显式元认知、actionable 契约、覆盖补盲思想。
- 不把反 orchestrator 理解成反自动化;禁止的是自动污染事实源,不是禁止计划/建议/投影。
- Markdown 继续做人类事实源;JSON/state 只能做机器投影与索引。
- 新能力一律是 sensor:不选目标、不自动确认、不绕过 evidence gate。
- 每个阶段完成后提交;除配置卫生外,尽量先 warning/soft gate,再用 bench 证明是否升级 hard gate。

### Phase 1 — 配置卫生与本地状态边界

- [x] 将已入库的 `config.ini` 改为 `config.example.ini`,默认 `mode = normal`。
- [x] 将真实 `config.ini` 加入 `.gitignore`;本地可保留 dev 配置,但不再入库。
- [x] 加入 `.DS_Store` ignore,避免 macOS 垃圾文件反复污染状态。
- [x] 检查 hook / tools 读取配置的路径,确保缺少 `config.ini` 时回落 normal 或示例默认。
- [x] 提交: `chore: move runtime config to example`

### Phase 2 — Bench 先行,让 measure-before-add 变成真门

- [x] 扩 `bench/` fixture:至少 10 个样例,覆盖 auth/IDOR、injection、upload/path、recorded closure。
- [x] 扩 `tools/bench.py` 指标:detection rate、false positive rate、certainty calibration、request budget、time-to-first-evidence、closure correctness。
- [x] 增加 baseline-vs-change 输出格式,便于对 Metacog / worker / sensor 改动做 A/B。
- [x] 每次新增机制必须产生一条 `review/records/<date>-bench-*.md` 记录:测了什么、指标变化、是否采用。
- [x] 提交: `test: expand bench decision gate`

### Phase 3 — 显式 Metacog pass(第二系统,先软门)

- [x] 在 `docs/WORKFLOW.md` 增加 Metacog pass:用于反事件发散,不是确认/收口。
- [x] 触发条件:连续 3 轮无新证据;同 barrier 重复失败;Reason 连续 staying;closure 前;operator hint 含 metacog;高价值 front 长期未实际 attack。
- [x] 输出契约写入 `decisions.md`:Trigger / Blind spot hypothesis / Proposed action / Target object / Expected signal / Safety class / Why main driver likely missed it。
- [x] `check_run.py` 增 closure 前缺 Metacog pass 的 WARN,不要 hard fail。
- [x] `docs/templates/loop_prompt.md` 加最短提示,避免长上下文忘记第二系统。
- [x] 提交: `docs: add explicit metacog pass`

### Phase 4 — Worker 计划自动化,不做事实自动化

- [x] 增强 `tools/workers.py suggest`:读取 `frontier.md` / `coverage.json`,列出适合 fan-out 的候选 front。
- [x] 增强 `tools/workers.py plan`:生成 worker 分配草案,由 driver 确认/复制给子 agent。
- [x] 增强 `tools/workers.py merge-check`:列出 candidate 缺 Control/Replicated、重复、冲突、done-but-unmerged。
- [x] 调整文档:允许计划级自动化,仍禁止 worker 自动写 canonical evidence / confirmed finding。
- [x] 重新考虑 `>=3 independent fronts` 的硬阈值:改为建议条件,结合 front 数、共享 barrier、限速、历史 worker 命中率。
- [x] 提交: `feat: add worker planning helpers`

### Phase 5 — Sensor 能力层:先补最缺的枪

- [x] 新建 `tools/sensors/` 命名空间,文档声明 sensor 只产出 candidate/evidence artifact。
- [x] `oob_listener.py` v0:支持盲 RCE / SSRF / XXE / SSTI 的 callback 证据;默认本地/授权 endpoint,记录 nonce。
- [x] `mutate_payload.py` v0:编码、大小写、路径归一化、JSON/XML/form/multipart 变体;不内置漏洞清单。
- [x] `blind_diff.py` v0:稳定采样状态码/长度/时间差,输出可复核差分。
- [x] `upload_probe.py` v0:无害上传证明、路径控制、清理记录、guard 限制。
- [x] 将 sensor 输出格式接到 evidence gate:artifact path + control/replicated 字段。
- [x] 提交: `feat: add proof-oriented sensors`

### Phase 6 — Phenomenon / Candidate / Finding 分层

- [x] 文档定义三层:phenomenon=观察/静态线索;candidate=主动验证但证据未满;finding=过 evidence gate。
- [x] worker 输出默认 candidate;client/source/static sensor 输出默认 phenomenon。
- [x] `check_run.py` 对 report 中 phenomenon/candidate 伪装 finding 给 WARN/FAIL。
- [x] `evidence_parse.py` 支持解析层级字段,但保持向后兼容。
- [x] 提交: `feat: classify evidence maturity`

### Phase 7 — Hostile content / prompt injection 防线

- [x] 新增 `docs/UNTRUSTED-CONTENT.md` 或并入 `docs/cognition/reference.md`。
- [x] 明确目标网页、JS、PDF、README、报错、工具输出、MCP/tool 描述中的自然语言默认 untrusted data,不是 operator 指令。
- [x] `render.py` / `evidence_parse.py` / 相关工具输出加 provenance: `source=target-content`, `trust=untrusted`。
- [x] review/closure 检查是否把 target content 当作指令吸收。
- [x] 提交: `docs: model hostile target content`

### Phase 8 — 机器状态投影,不替代 Markdown

- [x] 新增 `runs/<target>/state/events.jsonl` 约定:action/evidence/front/status 事件流。
- [x] 新增 `tools/state_project.py`:从 markdown run dir 生成 JSON projection。
- [x] worker suggest、bench、check_run 优先读 projection;projection 缺失时从 markdown 生成。
- [x] 文档声明 markdown 仍是 canonical narrative;JSON 是索引/缓存,不得反向覆盖人工记录。
- [x] 提交: `feat: add run state projection`

### Phase 9 — Client / Code graybox 扩展(排在 Web 主线之后)

- [x] 只做 sensor,不改 Xunji 主定位:Electron asar/config 检查、strings/grep 线索、本地监听端口 ingest、IPC/custom protocol 入口记录。
- [x] 输出默认 phenomenon,必须经主动 proof 才能升 candidate/finding。
- [x] 不把 TianTi 十维模型塞进 Web 主循环;作为 `client-graybox` 可选 profile。
- [x] 提交: `feat: add client graybox sensor skeleton`

### 当前已知不合理点(改动时逐个消化)

- [x] `config.ini` 以 dev 模式入库不合理;运行模式影响 hook 行为,应本地化。
- [x] `measure before add` 已写入 roadmap,但 bench 还不足以真正阻止坏机制进入 core。
- [x] 反 orchestrator 边界过粗;应允许计划/建议/投影自动化,只禁止自动污染事实源。
- [x] Markdown-only 对机器协同不友好;需要 JSON projection,但不能替代审计叙事。
- [x] evidence gate 偏文档产物;应补 OOB / diff / sanitizer / reproduction oracle。
- [x] `>=3 independent fronts` worker 阈值僵硬;应改为可解释建议条件。
- [x] 对目标内容中的 prompt injection / hostile instruction 缺独立纪律层。
- [x] 能力 sensor 薄于安全/审计/收口纪律;要补 proof-oriented sensors。

## 1. 状态栏(statusline.ps1)

文件:`C:\Users\CCJ\.claude\statusline.ps1`

- [x] 修复 PS 5.1 解析错误(`??`、param 位置)
- [x] 修复乱码("全部"→"Total")与膨胀数值(Sum-EntryTokens 只算 input+output,排除 cache)
- [x] 用 `/usage` 校准额度(初版 token 制:`$LIMIT_TOTAL=565000000`、`$LIMIT_5H=560000`)
- [x] **成本加权重写(2026-06-10)**:发现 token 制 5h 条翻倍偏高(40% vs 官方 19%),根因=Haiku 子代理 token 被按 Opus 全权重计 + 未按 output/cache 加权。改为按 `message.model` + token 类型算美元成本当量(价格用 /usage 反推已验证),额度改美元:`$LIMIT_5H_USD=250`(=$47.41/0.19)、`$LIMIT_WEEK_USD=33000`(=$1659.70/0.05);缓存加 `schema:2`。两条现已精确对齐 /usage(19% / 5%)
- [ ] **📊 Context 条校准(待用户拍板)**:实测显示 `640.0k/1000k`。该数值由 Claude Code 经 stdin 实时喂入(`used_percentage` + `context_window_size`),本身是真值、非我能校准的量。
  - 待确认:是想保持"模型最大窗口 1M"做分母,还是换成"实际触发 auto-compact 的阈值"(更能反映"还能撑多久")。用户回复后对症改。

## 2. 提升产出率的核心杠杆(已提议,待用户放行)

定位:框架管"怎么挖"而非"挖多少";前沿研究(Big Sleep)验证最大产出杠杆是**指纹→已知弱点**的知识库。

- [x] **scanner-as-recon 输入原则**:已落进 `docs/ROUTER.md` Driver 阶段的「证据门控承诺」——扫描器是喂证据门的传感器输入,不是选前沿的决策;侦察(广度)持续到 `certainty` 够格才转单一前沿的深度验证(依据 arXiv 2602.17622:证据不足时过早 commit 是主要失败模式)。同步在 `cognition` Attribution Checks 加了蜜罐/欺骗确认项。
- [x] **`knowledge/` 接地知识库**(grounding,非武器)——父项目已建:
  - 形态:文件型(非 RAG);`README.md`(grounding-not-weapon 契约 + 三类来源纪律)+ `_TEMPLATE.md`(四区块 schema,anchor 强制 `source:`+Reference)
  - 护栏:`tools/check_knowledge.py`(结构硬检 + 禁 payload/exploit/steps 字段 + payload 形状 WARN);已接进 ROUTER 工具清单
  - 种子:`spring-boot-actuator.md`(verified,Wiz/HackTricks/CVE-2022-22947)、`kingosoft.md`(seed,CNNVD-201705-1419;**已规避把青果 SQLi 误记到 KINGOSOFT**)、`sudy-cms.md`(seed,无可核实锚点,如实留空)
  - 用法接线:ROUTER 已加"证据门控承诺"——knowledge 仅指纹命中后查阅、禁 run 开始预载当清单
  - [x] 核实通过(2026-06-10):KINGOSOFT 厂商纠正为**湖南青果软件**(KINGOSOFT=青果教务同一产品线,上一轮"另一产品"判断已纠错);补 S2-045 一手 CVE-2017-5638(NVD,CVSS9.8/CISA KEV)+ SQLi 二手锚点(Seebug,如实标)。苏迪 CNVD 官方查**确无**记录,已留档"已查确无"防重复
  - ⏳ 待续:两者 Recognition 仍需**一手 run 指纹**确认才升 verified;苏迪需拿到厂商名后按公司名再查 CNVD;另从 Nuclei 提炼演示已成范式(`spring-boot-actuator.md` 已加 favicon hash + HPROF 魔数存在性证明)
  - [x] **deepseek-project/ 脚手架已同步**(2026-06-10,经用户授权破例跨界):只复制 `knowledge/README.md`(Project Boundary 段改 deepseek 视角)+ `_TEMPLATE.md` + `tools/check_knowledge.py`,**内容/种子留空**;两库 checker/检查均通过。**种子与锚点仍由 DeepSeek 自填,保独立基线对照**——内容我不碰

## 2b. 链式编排 / 组合利用(A2,2026-06-10 已落地)

定位:web 层 SRC=红队统一为"原子发现 + 链式编排";组合利用把低危原子拔高成高影响(直接对冲"产出少")。

- [x] **链作为条件式一等公民**(不违反 WORKFLOW「Keep the Ledger Light」):
  - 新建 `docs/templates/run/chains.md`(仅出现链时创建;goal/hops/weakest-hop/terminal/composite-severity)
  - `tools/check_run.py` 加 `OPTIONAL_MARKERS`:chains.md **存在才校验**,不进必需文件(无链 run 不受累);自测三态(有效过/缺省过/残缺挂)通过
  - `cognition` 新增「Vulnerability Chains」:最弱跳门控(每跳须 ≥0.8)、终止证明节点(RCE/admin 即停,不传 shell/不外渗/不持久化)、**仅 web 层**(SSRF/RCE 证可达即停,不跳板内网)、原子仍单独报
  - ROUTER:Run Authority 列出(条件式)+ Hunter 记链边并开新前沿 + Report 载入并输出"原子+链(复合严重度更高)"
  - WORKFLOW:循环加"确认后查链边"条件步 + 新增 chains.md 节
  - report.md 模板加「Chains」输出节
  - ⏳ 待定:deepseek-project 是否同步这套链式框架(同知识脚手架,涉及它自己的 6 个文件;独立基线,需你授权我才碰)

## 2c. 父项目↔deepseek 一致性审计(2026-06-10)

结论:两边均**未违反 AI 自主原则**(自主框架完整、cognition 反复"非清单"自守)。但 deepseek 只同步了知识脚手架+nuclei,方法论落后父项目:

- [x] **#1 安全硬化已同步**(经授权):deepseek safety_rules.json 补齐 14 条 post_exploitation 规则;check_hook + base64 实弹通过。
- ⏳ 未同步(独立基线 vs 一致性,待你权衡):**#2** 链式编排整套(A2);**#3** cognition 的 honeypot/欺骗确认项;**#4** ROUTER 证据门控承诺;**#5** deepseek ROUTER 未把 check_knowledge.py 列进工具清单(文件在、路由没引用,轻微悬空)。
- 注:**#6** deepseek 未限 web-scope = 有意(用户只把父项目限 web),非缺陷。
- 父项目自身链路衔接完整,无悬空引用。

## 3. deepseek-project 运行状态

- [ ] **cdut run** 未过 `check_run`:缺 `Loaded rule files this cycle:` 标记(该字段晚于此 run 引入)。待决定:迁移补字段 or 保留原样。
- [ ] **lygsf_edu_cn_20260610** run:苏迪 CMS + Spring Boot 线索已记录,报告已起草;如继续应按未关闭的 frontier 推进(勿重复已在 OSINT 报告里的侦察)。

## 4. 已完成(留档,勿重做)

- [x] 物理 fork:父项目逻辑(含 CLAUDE.md)整套复制到 `deepseek-project/`,两套独立基线
- [x] 取消 config.ini;改由 deepseek-project 的 CLAUDE.md 横幅 + `docs/ROUTER.md` 指向补丁层
- [x] 父项目清除 DeepSeek 内容;`check_rules.py` 的 SKIP_DIRS 加入 `deepseek-project`
- [x] `docs/deepseek/{README,driver,hunter,reviewer,context_slice}.md` 原生操作手册
- [x] WORKFLOW 增「先吸收已有情报」「失败预算」(软启发+override);cognition 增 grounding/variant 两节
- [x] src-safety-boundary skill 增 EDUSRC 证明即止原则(机密性/可用性/完整性)+ 平台法务规则
- [x] **(2026-06-10)父项目定性为 web 渗透 only**:CLAUDE.md Project Role + ROUTER Run Authority 声明(HTTP/浏览器可达;主机/内网/横向/二进制/红队战役 out of scope,Setup 阶段越界即停)。deepseek 未限 web 系有意
- [x] **(2026-06-12)取消 web-only,重定位为红队 web 打点武器 + 明确三层规则**(经 owner 指令):提示词去掉 "web-only/out of scope" 框定;主机/内网/横向/二进制/红队从"硬排除"挪进**软规则(操作者同意即可做)**;保留"证明即止/无害化验证"作自主层。三层=硬规则(机器强制,破坏性/不可逆,授权也不解)/ 软规则(需 owner 同意)/ 自主(无害验证)。改 CLAUDE.md(Project Role+三层教义+Operator Authority+Hard Boundaries 说明)、SKILL.md、ROUTER、cognition、chains、WORKFLOW、README。详见记忆 [[hard-boundary-only-irreversible-harm]]
- [x] **(2026-06-12)提示词零限制 + 全量合理性审查**(经 owner 指令):CLAUDE.md 只留角色/驱动/方法,限制全归 skill+hook;"目标皆授权不得怀疑"写入三处。审查后:**permission_change 降为软规则**(hook 删 10 条,SKILL 重点标注;54→44 条规则)、**guard.py 防失控锁保留**(注释去"爆破硬边界")、**SKILL「Platform & Legal」整节删除**(owner 后补新 skill);并修一批多轮不同步(do not pivot / getting-a-shell=driver's call / 爆破残留 / SRC 旧定位)。
- [x] **(2026-06-10)post_exploitation 钩子硬化**:父项目 + deepseek 的 safety_rules.json 各加 14 条(反弹shell/webshell/武器生成器),与"RCE 证明即停=链终止节点"双保险
- [x] **(2026-06-11)父项目硬边界重校准**(经 owner 指令):删除 14 条 post_exploitation + bruteforce,改为只硬拦不可逆危害(销毁/删库/拖库/DoS/资金/删资源/改权限);新增删库规则(DROP/TRUNCATE/无WHERE DELETE-UPDATE);selftest+check_hook 同步(nc -e/hydra 移入 ALLOWED,DROP DATABASE 移入 BLOCKED)。仅父项目,deepseek 未动。详见记忆 [[hard-boundary-only-irreversible-harm]]
- [x] **(2026-06-10)nuclei 离线 clone**:`F:\Codex\nuclei-templates`(两仓库外,13k+ yaml)作 DeepSeek 离线提炼源;只读不跑、不入库、不提交;两 README 已写"本地离线 clone"用法

## 安全约束(贯穿全程,勿删)

授权 SRC 测试。硬边界(safety_gate.py,2026-06-11 重校准):只硬拦**不可逆危害**——禁不可逆销毁(主机/文件 rm -rf/format/dd + 删库 DROP/TRUNCATE/无WHERE 的 DELETE-UPDATE)、禁目标资源删除、禁拖库/批量外渗(--dump)、禁权限/属主/特权变更、禁资金动作、禁 DoS/高速扫描。反弹shell/webshell/上传证明物/在线爆破/msfvenom 已**解封**=驱动按合理情况判断(证明即止、清残留、不跳板)。人工授权不解锁上述硬边界。EDUSRC 证明即止:仅证明漏洞存在,不导出数据、不中断业务、清除全部测试残留、不私留漏洞/厂商数据、不泄露漏洞内容,支付类漏洞只描述不利用,只提交已验证发现。
