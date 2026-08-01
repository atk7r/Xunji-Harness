# Peer Review — 2026-07-08-optimization-plan-review

_backend: arkcli:kimi-k2.7-code+minimax-m3+glm-5.2 · 2026-07-07T21:06Z_
> 候选, 非裁决。driver 须逐条过证据门: 不盲从(驳工具/语境误报), 不忽视(采纳真盲补)。

## Verdict: WARN

_backend: arkcli:kimi-k2.7-code+minimax-m3+glm-5.2_  
_brain: codex_  
_bundle_hash: 8f44b7bd146b39def60facb17e88a2513d21ca5d_  
_evidence_index_hash: cba66f20669004a6330988747f4b721dfb6cd03a_  

## Findings
- [WARN] PR-001 New threat_model.md/tool and TM-001 fields duplicate existing surface/frontier/constraints ledgers and risk becoming a hard merge gate. | Evidence: docs/templates/run/surface.md:23-49, docs/templates/run/frontier.md:17-22, docs/templates/run/frontier.md:36-39, docs/templates/run/constraints.md:3-15, docs/WORKFLOW-reference.md:439-451, docs/WORKFLOW-reference.md:453-483 | Why: [arkcli:kimi-k2.7-code] Xunji already records input shapes, unruled-out vectors, stop conditions, and negative evidence. A separate threat model ledger adds double-entry and, combined with 'Root merge discipline'/'WARN if open TM items', can evolve into a derived cache that drives closure or overrides the Single Synthesizer.
- [WARN] PR-002 Plan ships multiple new templates and tools before proving A/B improvement with tools/bench.py. | Evidence: docs/ROADMAP.md:7-26, tools/bench.py:3-34, docs/ROADMAP.md:191-195 | Why: [arkcli:kimi-k2.7-code] ROADMAP and bench.py treat measurement as a prerequisite for adding framework mechanisms. Steps 2-7 add templates, tools, and mentor checks while bench canaries are step 8, so the plan claims discovery improvement before any fixture exists.
- [WARN] PR-003 events.jsonl v2 and Pentagi-style mentor checks overlap existing loop_state.py advisory signals. | Evidence: tools/loop_state.py:2-11, tools/loop_state.py:227-254, tools/state_project.py:2-6, tools/state_project.py:97-123, docs/WORKFLOW-reference.md:439-451 | Why: [arkcli:kimi-k2.7-code] loop_state.py already surfaces no-progress, fanout, saturation, conflict, and closure hints from derived Markdown. Adding a richer events schema and mentor layer before using those signals risks derived-cache bloat and second-guessing the Synthesizer.
- [WARN] PR-004 JS analysis template/tooling overlaps discovery channels already in surface.md and risks becoming a fixed attack checklist. | Evidence: docs/templates/run/surface.md:23-49, .claude/skills/xunji-agent-board/SKILL.md:38-63, docs/WORKFLOW-reference.md:453-483 | Why: [arkcli:kimi-k2.7-code] surface.md already catalogs JS refs, inline scripts, asset refs, page links, path inference, and response bodies. Re-encoding those as a separate JS-analysis template with enumerated categories (token, nonce, role hints, hidden routes) can become a fixed checklist and slow the Agent Board without proven gain.
- [WARN] PR-005 Permission matrix and state-machine checks are promising but lack bench fixtures and could create a new canonical ledger. | Evidence: docs/ROADMAP.md:7-26, tools/bench.py:3-34, docs/WORKFLOW-reference.md:439-451 | Why: [arkcli:kimi-k2.7-code] Conditional permission matrices can improve IDOR discovery, but without canaries they add paperwork and a potential new source-of-truth. Markdown must remain canonical; any matrix must be derived from agent candidate output.
- [WARN] PR-006 docs/research-learnings.md is decoupled from acceptance criteria and likely to become stale paperwork. | Evidence: docs/ROADMAP.md:7-26, tools/bench.py:3-34 | Why: [arkcli:kimi-k2.7-code] A static mapping of external projects to Xunji landing points does not improve vulnerability discovery by itself and can diverge from the actual code/ROADMAP.
- [WARN] PR-007 Plan does not repair or measure existing templates before layering new borrowings. | Evidence: docs/templates/run/frontier.md:17-22, docs/templates/run/frontier.md:36-39, docs/templates/run/surface.md:23-49, docs/templates/run/constraints.md:3-15, tools/bench.py:3-34 | Why: [arkcli:kimi-k2.7-code] Earlier learning is already partially implemented in frontier.md, surface.md, constraints.md, and loop_state.py. Adding new mechanisms before confirming that the current templates pass/fail the new canaries weakens the feedback loop.
- [WARN] PR-008 arkcli panel had backend errors; review is partial | Evidence: minimax-m3: parse error; output tail: t_model.md templates can become stale faster than surface.md because threats evolve with target

Context limits:
- I don't have access to the actual repo files, only the claims document
- I can't verify line numbers in the actual code
- I don't know what the current bench fixtures look like
- I don't know if there are existing threat-modeling touchpoints I haven't seen mentioned

Let me draft the JSON output. I need to be careful with severity gradation.

Looking again at the plan more carefully; glm-5.2: parse error; output tail: is template/tooling (item 6) overlaps with surface.md Input Shape Catalog and Discovery Channels (surface.md 23-49 already include JS refs, inline scripts, asset refs). A separate template risks duplication and stale state. Category: redundancy. Recommended: extend surface.md discovery channels or add a focused JS analysis tool (not a new run template) gated behind `js-hidden-api-threat` and `signed-client-param` canaries.

Finding 5 (WARN): Pentagi-style mentor checks (item 5) overlap with loop | Why: At least one arkcli reviewer failed, so PASS only means the completed panel members found no blocker.

## Blind-spot check
- [kimi-k2.7-code] The author treats surface.md and frontier.md as static containers and misses that they already encode JS discovery, anti-early-closure, and negative evidence, so much of threat_model.md/JS tooling is redundant.
- [kimi-k2.7-code] The plan does not address skill/tool placement under the Claude-primary/Codex-auxiliary driver model; new skills should land in .claude/skills/ and be reviewed by the live driver.
- [kimi-k2.7-code] The canary list is broad and may exceed current bench fixtures; the author did not baseline request-per-finding or runtime cost before adding six new canaries plus tooling.
- [kimi-k2.7-code] No-recon mode means coverage.json/classify do not exist, so any threat-ledger/coverage self-check logic must not assume coverage data.

## Context-limit notes
- [kimi-k2.7-code] Findings rely on line-range claims in report.md, not verified file snippets or live runs.
- [kimi-k2.7-code] We have no diff of the proposed templates/tools, only the plan summary.
- [kimi-k2.7-code] Actual agent runtime impact and bench fixture feasibility are unknown without executing tools/bench.py.
- [kimi-k2.7-code] The exact boundary between advisory guard and hard hook in the proposed Root merge discipline is unspecified.
- minimax-m3: parse error; output tail: t_model.md templates can become stale faster than surface.md because threats evolve with target

Context limits:
- I don't have access to the actual repo files, only the claims document
- I can't verify line numbers in the actual code
- I don't know what the current bench fixtures look like
- I don't know if there are existing threat-modeling touchpoints I haven't seen mentioned

Let me draft the JSON output. I need to be careful with severity gradation.

Looking again at the plan more carefully
- glm-5.2: parse error; output tail: is template/tooling (item 6) overlaps with surface.md Input Shape Catalog and Discovery Channels (surface.md 23-49 already include JS refs, inline scripts, asset refs). A separate template risks duplication and stale state. Category: redundancy. Recommended: extend surface.md discovery channels or add a focused JS analysis tool (not a new run template) gated behind `js-hidden-api-threat` and `signed-client-param` canaries.

Finding 5 (WARN): Pentagi-style mentor checks (item 5) overlap with loop