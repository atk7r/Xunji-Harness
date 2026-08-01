# Xunji Roadmap

Research candidates distilled from a survey of the 2025–2026 autonomous-pentest /
LLM-vuln-research landscape (see Sources). This file is **not the implementation
backlog**. `TODO.md` is the only forward backlog; a candidate below must first be
admitted there with an owner, acceptance evidence, and dependency before work starts.

## The gating principle: measure before you add

The framework grew fast (Reason pass, state graph, hints, parallel fan-out, and
guard concurrency hardening). `tools/bench.py` and local fixtures now provide a v0
scorer, but fixture breadth and repeatable driver A/B coverage remain too small to
support universal benefit claims. The field's own consensus is "measure what
matters" (SoK below). So:

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

## P0 — Measurement (v0 landed; expand before adopting more mechanisms)

### R-1. Self-eval / regression harness  ⭐ highest value
- **Current gap**: a scorer exists, but there are not enough representative fixtures
  or repeatable driver A/B runs to show whether a framework change improves discovery
  rather than merely adding surface.
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

## Dated implementation evidence (2026-06-17 snapshot; not current backlog)

At that checkpoint, replay sidecars and guarded replay verification, report/evidence
consistency checks, the first `tools/bench.py` scorer and fixture, grounding knowledge
retrieval, and independent ReviewOps had landed. This is historical evidence, not a
promise that backend names, model defaults, test counts, or fallback order remain
current.

Current implementation truth comes from the owner code and schemas, the single
`Maintenance Checkpoint` in `docs/ARCHITECTURE.md`, registered selftests, and current
review receipts. Forward work lives only in `TODO.md`. In particular, R-1 is no
longer “no measurement”; it is “v0 scorer exists, fixture breadth and repeatable A/B
coverage remain insufficient.” R-2 through R-6 remain research candidates unless
their current owner surface explicitly records a landed slice.

Durable limits still apply: saved/replayable evidence narrows but does not eliminate
the gap between a claim and reality; independent reviewers reduce correlated bias
but depend on backend availability and acceptable data boundaries; guardrails raise
minimum reliability but do not create exploitation capability.

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
