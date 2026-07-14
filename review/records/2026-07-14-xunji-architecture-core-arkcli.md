# Peer Review — Xunji

_backend: arkcli:kimi-k2.7-code+glm-5.2 · 2026-07-14T09:43Z_
> 候选, 非裁决。driver 须逐条过证据门: 不盲从(驳工具/语境误报), 不忽视(采纳真盲补)。

## Verdict: WARN

_backend: arkcli:kimi-k2.7-code+glm-5.2_
_brain: codex_
_bundle_hash: e65ec07afbd2c40e1e19d74b1312fbb519f27160_
_evidence_index_hash: cba66f20669004a6330988747f4b721dfb6cd03a_

## Findings
- [WARN] PR-001 docs/ARCHITECTURE.md embeds a literal 'recently verified' date that invites timestamp-only churn despite the explicit anti-churn rule. | Evidence: docs/ARCHITECTURE.md:4, docs/ARCHITECTURE.md:389-396 | Why: [arkcli:kimi-k2.7-code] The change protocol rejects updating the doc solely to refresh timestamps, but a static 'recently verified' field becomes stale and creates pressure to violate that rule.
- [WARN] PR-002 docs/ARCHITECTURE.md lacks a dedicated transitional-architecture section and owner map, despite requiring current/transitional/target labels. | Evidence: docs/ARCHITECTURE.md:114, docs/ARCHITECTURE.md:300, docs/ARCHITECTURE.md:333-334 | Why: [arkcli:kimi-k2.7-code] The intended result requires clear separation of current, transitional, and target CCB architecture; only current and target are sectioned, so transitional state is buried in migration invariants and easy to confuse with implemented behavior.
- [WARN] PR-003 `src-safety-boundary` skill is named as a current safety-boundary owner, but it is not an existing Xunji artifact. | Evidence: docs/ARCHITECTURE.md:20, CLAUDE.md:415 | Why: [arkcli:kimi-k2.7-code] Current Xunji boundary enforcement lives in hooks and guard; citing a skill that does not exist risks sending agents to a target/roadmap artifact when they should operate in current scope.
- [WARN] PR-004 AGENTS.md assigns 'final synthesis and decision responsibility' to Codex for its own authored diffs. | Evidence: AGENTS.md:157-158 | Why: [arkcli:kimi-k2.7-code] Author synthesis is appropriate, but 'decision responsibility' can be read as Codex having merge/disposition authority over its own changes, blurring the independent-review boundary.
- [WARN] PR-005 check_rules.py only enforces the existence of ARCHITECTURE.md section headers, not transitional-state separation or owner-map completeness. | Evidence: tools/check_rules.py:85-90 | Why: [arkcli:kimi-k2.7-code] The mechanical guard can pass while the doc omits the transitional section or key owners, leaving the current-vs-target confusion unguarded.
- [WARN] PR-006 arkcli panel had backend errors; review is partial | Evidence: glm-5.2: parse error; output tail: ines 37-42:** WATCH_DIRS = .claude, docs, tools. Scans these for forbidden text patterns.

**Lines 44-62:** SKIP_DIRS and SKIP_FILES. Skip self-reference files and safety files from text scanning.

**Lines 66-70:** FORBIDDEN_TEXT_PATTERNS - apps.orchestrator, schemas/action.schema.json, prompts/planner.system.md. These are specific legacy architecture references. Reasonable.

**Lines 72-80:** REQUIRED_FILES - AGENTS.md, CLAUDE.md, docs/ARCHITECTURE.md, docs/ROUTER.md, docs/WORKFLOW.md, docs/WORK | Why: At least one arkcli reviewer failed, so PASS only means the completed panel members found no blocker.

## Blind-spot check
- [kimi-k2.7-code] Evidence index is empty and no artifact hashes are provided; claimed test results (check_rules.py PASS, selftest_all.py 60/0) are treated as author claims, not verified facts.
- [kimi-k2.7-code] We do not have the full current CLAUDE.md, docs/WORKFLOW-reference.md, TODO.md, or skills trees, so cross-reference completeness and owner-map accuracy cannot be fully validated.
- [kimi-k2.7-code] The runtime effect of the new Codex maintenance-review matrix under failure/no-reviewer scenarios has not been exercised.

## Context-limit notes
- [kimi-k2.7-code] AGENTS.md (~170 lines) is loaded as Codex project instructions, and ARCHITECTURE.md is required reading before non-trivial work; together they add significant token overhead per turn.
- [kimi-k2.7-code] While the doc routes detail to owner files, the architecture doc itself is long; consider whether it should be split into a short index plus deeper sections, or explicitly loaded on demand.
- glm-5.2: parse error; output tail: ines 37-42:** WATCH_DIRS = .claude, docs, tools. Scans these for forbidden text patterns.

**Lines 44-62:** SKIP_DIRS and SKIP_FILES. Skip self-reference files and safety files from text scanning.

**Lines 66-70:** FORBIDDEN_TEXT_PATTERNS - apps.orchestrator, schemas/action.schema.json, prompts/planner.system.md. These are specific legacy architecture references. Reasonable.

**Lines 72-80:** REQUIRED_FILES - AGENTS.md, CLAUDE.md, docs/ARCHITECTURE.md, docs/ROUTER.md, docs/WORKFLOW.md, docs/WORK