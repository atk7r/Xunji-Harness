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

### R-5. Knowledge retrieval over `knowledge/` (borderline — gate hard)
- **Gap**: grounding knowledge is consulted **manually**; the relevant entry may be
  missed when a stack is fingerprinted.
- **Steal**: RAG-enhanced pentest knowledge (PentestAgent, xOffense) — auto-surface
  the matching `knowledge/` entry on a fingerprint hit.
- **Guardrail**: ⚠️ must stay recognition + anchors. Retrieving signatures = fine;
  retrieving turnkey payloads = the forbidden weapon kit. **Only build this if it
  passes the grounding-vs-weapon test**; `check_knowledge.py` stays the contract.
- **Source**: PentestAgent, xOffense.

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
- **异构独立复审 = R-6 的实现** — `tools/peer_review.py`(Codex>DeepSeek/GLM>Claude兜底, 候选非
  裁决)+ check_run `--auto-peer-review`。R-6「从干净上下文重证发现」由【异构】模型落地; 同模型只
  减 bias 不减盲区(A2)。6 次实战 dogfood 各逮到真问题(漏报/bypass/同族蒙混/凭据/越界/重放DELETE)。
- **B1 证据可重放化(缓解 A1)** — probe `--save` 留 `.replay.json` 录像; `tools/replay.py` 走 guard 重放
  比对(幂等 GET 自动 / DELETE 永不重放 / host 白名单)。造假成本从"P 张图"抬到"伪造自洽请求+响应+sha1"。
- **漏报一致性硬门** — check_run: certainty>=0.8 正向发现必须进 report(防 hamastar 漏报 E-017 那类)。

### 未完成 / 预留(卡点已标)
- ⬜ **B2-② 多异构 panel** — 扩展点已留(peer_review.py 注释; 配 ≥2 异构 key + `review_panel()` 即可,
  不改现有结构)。卡: key + API 成本。
- ⬜ **B1-③ API 后端核对产物** — codex 版已做(rubric 第7点); API 版卡 key。
- ⬜ **B3-② 通用利用原语**(撬 A3 能力墙, 当前方向): ① OOB 带外回调监听器(推荐起点, 盲 RCE/SSRF/
  盲注→铁证) ② 编码/序列化 ③ multipart 上传发送 ④ 盲注提取引擎。**铁律: 工具是枪, payload 靠 AI
  临场定制, 不做 playbook**(同 R-4 sensor 精神)。
- ⬜ **replay 接进收口** — 现为独立工具(手动跑); 可加 check_run 可选 `--replay-verify` 收口前自动核实。
- ⬜ **历史 run 过新漏报门** — 早期 run 当年无此门, 可能也漏报高 certainty 发现, 各跑一遍 check_run。
- ⬜ **C2 workers 实战压测 / C3 runtime 解耦 / deepseek-project 适配** — 见 P3 与各自 memory。
- ⬜ **R-1 自评 harness 仍是最高价值缺口** — 上面所有"改进"都还没法 A/B 证明真提升了找洞率(度量先行)。

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
