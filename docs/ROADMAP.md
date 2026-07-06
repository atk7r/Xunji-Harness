# Xunji Roadmap

Forward-looking work, distilled from a survey of the 2025–2026 autonomous-pentest
/ LLM-vuln-research landscape (see Sources). It is a backlog, not a commitment —
each item must still earn its place by the gating principle below.

## The gating principle: measure before you add

This roadmap exists because the framework grew fast (the Cairn borrowings —
Reason pass, state graph, hints, parallel fan-out — plus the guard concurrency
hardening; see the `cairn-borrowings` memory and git history) and there is **no
way yet to tell which additions actually improve vuln-finding**. The field's own
consensus is "measure what matters" (SoK below). So:

1. **P0 (measurement) is a prerequisite for the rest.** Adopt P1–P3 only once the
   eval harness can show the change helps. Plausible-sounding mechanism != better.
2. Every item must pass the project's three tests, or it does not ship:
   - **not a playbook** — structure/discipline, never a fixed attack checklist;
   - **not an orchestrator** — tooling assists/derives, never auto-drives or
     auto-closes; markdown/the driver stays the source of truth;
   - **attacker, not a scanner** — payload knowledge is used per-target through the
     evidence gate, never fired as a blind checklist; public tier = grounding,
     weapons live in the gitignored `knowledge/weaponized/` tier
     (`docs/cognition` "Knowledge: Grounding vs Weaponized — never a blind scanner").
3. Prefer the smallest doc/discipline + a light tool with teeth in `check_run.py`,
   the pattern the rest of the repo already uses.

---

## P0 — Measurement (do this first)

### R-1. Self-eval / regression harness  ⭐ highest value
- **Gap**: you cannot A/B a framework change. Did the 4 Cairn borrowings help, or
  just add surface? Unknown.
- **Steal**: a small regression suite of **locally reproducible known-vuln
  fixtures** (DVWA / Juice Shop / intentionally-vuln containers, or recorded run
  fixtures) + a scorer that reports **detection rate, false-positive rate,
  certainty calibration, and request budget spent**. Borrow Cybench's
  **subtask decomposition** so partial progress scores partial credit (not 0/1).
- **Shape**: `tools/bench.py` + a `bench/` dir of fixtures; pure-local, no live
  targets, no network. Output a scorecard so any change is measurable.
- **Guardrail**: it measures the driver; it never becomes the driver. Fixtures are
  benign known-vuln targets, never real engagements.
- **Source**: SoK closed-loop, Cybench, NYU CTF Bench, HackSynth, CyberExplorer.

---

## P1 — Cognition (cheap, doc-level; validate via R-1)

### R-2. Hierarchical front decomposition (task tree)
- **Gap**: `frontier.md` is fairly flat; "where am I in the big picture" is implicit.
- **Steal**: PentestGPT's finding that LLMs lose the plot to recency bias (= the
  tunnel vision the Reason pass already fights). Add **sub-fronts** — a front may
  decompose into child fronts — so the graph shows the hierarchy, not just a list.
- **Guardrail**: a tree of *the driver's own* fronts, not a prescribed attack tree.
- **Source**: PentestGPT, Pentest-R1.

### R-3. Falsification-first Hunter gate
- **Gap**: confirmation bias — the deepest cognitive failure. The Hunter phase and
  `What would reject:` / `Control:` fields exist, but confirming is still the default.
- **Steal**: Popperian discipline — **before raising a finding's certainty, attempt
  a refutation** (a control that *should* fail if the vuln is real). Make it an
  explicit gate, not just a field.
- **Guardrail**: pure discipline + a `check_run.py` warn; no new machinery.
- **Source**: scientific-method / closed-loop measurement literature.

---

## P2 — Depth & knowledge (conditional; careful with the line)

### R-4. Code-level vuln-research tooling (only if extending past web打点)
- **Gap**: Xunji is strong at web initial access, thin on source/binary-level
  discovery (in scope per `CLAUDE.md`, but unsupported by tooling).
- **Steal**: Big Sleep's lesson — code comprehension + reasoning + **good tools
  (debugger, code navigation) and reasoning space, not a workflow** — which is
  exactly this project's anti-playbook bet, applied to source/binary. Pair with
  reproduction rigor (dual-loop reproduction paper).
- **Shape**: source/binary navigation as **sensors** (like `probe`/`scan`), routed
  and bounded; keep the reasoning-space philosophy.
- **Guardrail**: sensors feed the evidence gate; they do not auto-exploit.
- **Source**: Big Sleep, dual-loop vulnerability reproduction.

### R-5. Knowledge retrieval over `knowledge/` (borderline — gate hard) ✅ v0 landed
- **Gap**: grounding knowledge is consulted **manually**; the relevant entry may be
  missed when a stack is fingerprinted.
- **Steal**: RAG-enhanced pentest knowledge (PentestAgent, xOffense) — auto-surface
  the matching `knowledge/` entry on a fingerprint hit.
- **Guardrail**: ⚠️ must stay recognition + anchors. Retrieving signatures = fine;
  retrieving turnkey payloads = the forbidden weapon kit. **Only build this if it
  passes the grounding-vs-weapon test**; `check_knowledge.py` stays the contract.
- **Source**: PentestAgent, xOffense.
- **Status (2026-06-17)**: the flywheel is now end-to-end. Write end = check_run
  `Fingerprints captured` gate; match end = `classify_hosts` signature matching →
  `kb:<id>` tag; **retrieval end = `tools/knowledge_match.py`** (`--body` matches a
  saved response against the grounding `signatures:` and prints the matched entry's
  Recognition + Weak-Point Anchors; `--id` surfaces a known entry). Passes the gate
  by construction: reads `knowledge/*.md` non-recursively (never `weaponized/`),
  surfaces recognition + anchors only (public tier has no payloads — `check_knowledge`
  enforces). **Remaining = content, not tooling**: only ~4 of ~18 entries have
  `signatures:` filled, so body-match recognizes only those; fill `signatures:` on
  the rest (a per-entry chore done as runs re-touch each stack) to widen recall.
- **xday retrieval end (2026-06-17, mirror of R-5)**: `tools/xday_match.py` — same
  signature match, but reads the **local gitignored** weaponized/xday tiers
  (`knowledge/weaponized/` + `poc_library/xday/`) and surfaces the stored exploit
  path/chain for a matched stack. Rationale (operator): public vulns can be crafted
  from the internet off the anchor, so they need no local payload; **xday has no
  public payload — the local copy is the only source**, so local retrieval is where
  it earns its keep. Match-gated, local-only behavior, stores never ship. Proven
  end-to-end on `scshr` (AIS page → `soarcloud-ais-hr` → local `poc_library/xday/
  soarcloud-ais/`). 2 real xday currently retrievable (ours-ehr, soarcloud-ais).

---

## P3 — Scale (when triage becomes the bottleneck)

### R-6. Finding-validator (generalize the independent reviewer)
- **Gap**: as more is found, false-positive suppression / triage dominates.
- **Steal**: the independent-reviewer pattern, pointed at *findings*: each
  high-severity finding is **re-proven from clean context** before it is reported.
  The evidence gate is the seed; this makes confirmation independent, not
  self-administered.
- **Guardrail**: advisory/independent; it raises the bar to report, never lowers it.
- **Source**: dual-loop reproduction, SoK closed-loop.

---

## Validation, not just borrowing

The multi-agent literature (VulnBot, "Teams exploit zero-day", PentestAgent)
mostly **validates** choices already made — parallel teams beat solo on multi-step
work. One explicit non-goal: their **inter-agent chat coordination**. Xunji (like
Cairn) keeps **stigmergy — board-only coordination** — which is cleaner and avoids
re-introducing orchestration. Do not adopt chatty inter-worker messaging, and do
not specialize workers by *technique* (that drifts toward a playbook); scope them
by *front/asset*, as now.

## 实现状态 & 未完成清单(2026-06-17 本轮)

R-1~R-6 是研究借鉴 backlog; 下面是**实际实现状态** —— 这一轮围绕"证据可信度"落地了一批,
也明确了哪些是改不动的本质墙(A 类)。

### 已落地
- **异构独立复审 = R-6 的实现** — `tools/peer_review.py` 默认按 Claude Code 主驾驶运行
  Codex gpt-5.5 high + arkcli 三模型 panel(Kimi-K2.7-Code/MiniMax-M3/GLM-5.2), 单点高危和
  代码/报告/收口复审都走这套; 缺 Codex 用 arkcli, 缺 arkcli 用 Codex, 都缺才 Claude 同族兜底。
  Codex-authored maintenance diff 的复审矩阵放在 Codex 根指令 `AGENTS.md`, 不在公共流程文档展开。
  arkcli panel 默认允许各模型自己的 thinking/推理策略, 不写 `--thinking disabled`。
  候选非裁决, 接 `check_run --auto-peer-review`。
  R-6「从干净上下文重证发现」由【异构】模型落地; 同模型只减 bias 不减盲区(A2)。
  6 次实战 dogfood 各逮到真问题(漏报/bypass/同族蒙混/凭据/越界/重放DELETE)。
- **B1 证据可重放化(缓解 A1)** — probe `--save` 留 `.replay.json` 录像; `tools/replay.py` 走 guard 重放
  比对(幂等 GET 自动 / DELETE 永不重放 / host 白名单)。造假成本从"P 张图"抬到"伪造自洽请求+响应+sha1"。
- **漏报一致性硬门** — check_run: certainty>=0.8 正向发现必须进 report(防 hamastar 漏报 E-017 那类)。

### 全流程贯通(2026-06-17 本轮: 先把闭环焊齐再实践微调)
做了一次 setup→recon→classify→侦察→证据→收口→报告→复审 的端到端贯通体检, 焊了真断点:
- **聚合自测 `tools/selftest_all.py`** — 一条命令跑全部 12 个 selftest 入口(工具/hook/sentinel),
  一张红绿卡; 改安全关键码、独立复审前的第一道自动回归。是 R-1 度量的地基。
- **断-2 产物布局统一** — `probe --save NAME --run`、`render --run` 让产物(含 `.replay.json` 录像)
  自动落 `<run>/evidence/`; check_run 加**收口时**布局漂移 WARN(主动验证期静默, 降噪)。
  标准布局成文(WORKFLOW-reference「Run directory layout」)。让"正确放法=省事放法"。
- **断-1 replay 接进收口** — check_run `--replay-verify`(收口前自动重放 `.replay.json`, DIVERGED=
  证据存疑升警告; 走 guard / target.md 授权 scope / 幂等 GET 才重放)。replay 从孤岛焊进闭环。
- **断-3 历史 run 过新门体检** — 12 run 全过一遍; **确认无历史漏洞漏报**(被标的全是环境/防御/
  工具就绪条目), 失败几乎全是后加门+格式漂移; grandfather 不回填。详见
  `review/records/2026-06-17-historical-run-gate-audit.md`。
- **半连缝定性(不投机堆工具, 守 measure-before-add)**:
  - **recon 前门 = 有意外部接缝** — 框架是【给定攻击面】的 web 打点武器, 侦察采集(子域/端口/OSINT)
    在上游, 操作者/外部扫描器喂 `recon.json`(ingest_recon/setup_run 已收)。自建采集器 = 大幅越界 +
    漂向"扫描器", 不做。明确记为设计, 非缺口。
  - **传感器→证据 = 有意人工接缝** — 什么算证据是 driver 的判断, 不自动写 evidence(自动桩有橡皮图章
    之险)。`.replay.json` 已结构化留底; 转录成本低。保持 driver 亲笔。
  - **report 脚手架 = 候选, gate 在 R-1 之后** — 从 evidence.json 预填确认发现清单骨架(不下结论)能补
    报告阶段唯一无工具的环节, 且过反编排测试; 但本会话已加多件未度量工具, 不再投机加码 —— 待 R-1
    能 A/B 证明它真帮上找洞/防漏报, 再建。

### 未完成 / 预留(卡点已标)
- ✅ **B2-② 多异构 panel** — 默认链路已接 arkcli 三模型 panel(GLM5.2/Kimi2.7/MiniMax-M3);
  Claude Code 主驾驶时满配默认跑 Codex+arkcli panel, 大脑为 Codex; 无 Codex 时大脑为 arkcli
  panel; 无 arkcli 时大脑为 Codex。Codex-authored maintenance review 细节见 `AGENTS.md`。
  旧 DeepSeek/GLM OpenAI-compatible 后端保留为
  `--backend`/私有配置扩展, 不再是默认链路。
- ⬜ **B1-③ API 后端核对产物** — codex 版已做(rubric 第7点); API 版卡 key。
- ⬜ **B3-② 通用利用原语**(撬 A3 能力墙, 当前方向): ① OOB 带外回调监听器(推荐起点, 盲 RCE/SSRF/
  盲注→铁证) ② 编码/序列化 ③ multipart 上传发送 ④ 盲注提取引擎。**铁律: 工具是枪, payload 靠 AI
  临场定制, 不做 playbook**(同 R-4 sensor 精神)。
- ✅ **replay 接进收口** — 已落地: check_run `--replay-verify`(见上「全流程贯通」)。
- ✅ **历史 run 过新门体检** — 已做: 确认无漏洞漏报(见审计记录)。
- ⬜ **report 脚手架** — 候选, 待 R-1 度量后再建(见上半连缝定性)。
- ⬜ **C2 workers 实战压测 / C3 runtime 解耦** — 见 P3 与各自 memory。
- 🟡 **R-1 自评 harness v0 已落地** — `tools/bench.py` + `bench/`(检出率/校准/误报/预算 打分,
  对照 fixture 真值; `bench/example-dvwa-sqli/` 合成样例 + 随附回归)。这是把尺子。**边界(诚实标)**:
  ① 它是 scorer, 跑 fixture 的那次 run 仍要 driver(agent)亲自打 —— 不是全自动 A/B; ② fixture 还少,
  需扩(DVWA 各关 / Juice Shop / 录制 run 真值标注); ③ marker 子串匹配是近似。下一步: 用它把本会话
  这批改动(断-1/2/3 + selftest_all)真正 A/B —— 在它能证明价值前, 别再凭手感堆工具。

### 承认的本质墙(不可"完成", 只记录边界)
- **A1 申报即过 verify-real**: B1 把墙后移到「证据 vs 现实」; 破坏性/一次性/目标下线证据仍停人工。
- **A2 同模型盲点**: 异构复审已破解, 依赖后端可用 + 可接受数据出境 + 多正交收敛。
- **A3 护栏≠能力**: 无护栏方案, 只能 B3 真加能力(慢/长期); 最硬的墙。

> 真实目标 run 待办(发现物, 红线不进仓)在各 `runs/<t>/`。

## Sources

- SoK: Measuring What Matters for Closed-Loop Security Agents — arxiv 2510.01654
- Cybench (subtask-scored CTF eval) — arxiv 2510.17521
- HackSynth (agent + eval framework) — arxiv 2412.01778
- NYU CTF Bench — arxiv 2412.01778 ; CyberExplorer — arxiv 2602.08023
- AI agents vs human pentesters — arxiv 2512.09882 ; Pentest-R1 — arxiv 2508.07382
- Big Sleep (Google) — code-level 0day research, foiled an in-the-wild exploit
- Dual-Loop Agent Framework for Automated Vulnerability Reproduction — arxiv 2602.05721
- VulnBot / xOffense — arxiv 2509.13021 ; Teams exploit zero-day — arxiv 2406.01637
- PentestAgent — arxiv 2411.05185
