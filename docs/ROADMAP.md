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
   - **grounding, not a weapon** — knowledge is recognition + anchors, never
     turnkey payloads (`docs/cognition` "Grounding Knowledge Is Not a Weapon").
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
