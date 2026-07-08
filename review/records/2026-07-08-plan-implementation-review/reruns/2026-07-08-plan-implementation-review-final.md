# Peer Review Panel — 2026-07-08-plan-implementation-review

_backend: panel:arkcli+claude · 2026-07-07T22:29Z_
> 候选, 非裁决。driver 须逐条过证据门。

## Verdict: WARN

_backend: panel:arkcli+claude_
_brain: codex_
_bundle_hash: ebf25ac4035f615af094044b34ae067032af7192_
_evidence_index_hash: c258a06af115d86a9b472a4bfa8782bde951e4c6_

## Findings
- [WARN] PR-001 Confirmed evidence entries E-002 through E-006 cannot be independently verified because their artifact contents are not included in the review bundle; only size and sha1 metadata are present. | Evidence: evidence_index:E-002, evidence_index:E-003, evidence_index:E-004, evidence_index:E-005, evidence_index:E-006 | Why: [panel:arkcli] [arkcli:kimi-k2.7-code] External review requires inspecting actual selftest output, bench JSON, and control recordings; relying on artifact metadata alone fails the evidence gate.
- [WARN] PR-002 Bench fixture results inside E-003 cite matched_eid "E-001", but evidence_index E-001 is an unconfirmed phenomenon (certainty 0.3, confirmed:false). | Evidence: evidence_index:E-001, evidence/bench-score-all.json (excerpt in E-003) | Why: [panel:arkcli] [arkcli:kimi-k2.7-code] Either the bench reuses a bundle evidence ID for unrelated synthetic findings, or confirmed fixture results are anchored to an unconfirmed entry; both break traceability.
- [WARN] PR-003 Reported updates to .claude/skills/xunji-agent-board/SKILL.md, docs/WORKFLOW*.md, docs/templates, and tools are not represented in the evidence_index; the only diff artifact is E-001 and is unconfirmed. | Evidence: report.md:Main Changes, report.md:Driver Answers, evidence_index:E-001 | Why: [panel:arkcli] [arkcli:kimi-k2.7-code] Without seeing the changed files, an independent reviewer cannot verify that the claimed documentation and skill updates happened or are complete.
- [WARN] PR-004 E-003 reports 18/18 clean with perfect detection and calibration, yet many fixtures have recorded_requests:0 and time_to_first_evidence_sec:null, indicating they are process canaries rather than live request-confirmed findings. | Evidence: evidence/bench-score-all.json (summary and fixture scores in E-003) | Why: [panel:arkcli] [arkcli:kimi-k2.7-code] A self-scoring benchmark with no recorded requests for many fixtures does not demonstrate improved real autonomous discovery; it only shows internal consistency.
- [WARN] PR-005 The no-network/read-only property of js_inventory.py is supported only by small selftest outputs (E-005) whose contents are unavailable; a runtime monkeypatch selftest is not independent proof of production isolation. | Evidence: report.md:Driver Answer 3, evidence_index:E-005 | Why: [panel:arkcli] [arkcli:kimi-k2.7-code] A selftest can monkeypatch functions that production code calls differently or miss import-time side effects; external reviewers need source-level evidence.
- [WARN] PR-006 E-002 and E-006 are both marked confirmed (0.8) and cite five identical selftest artifact files; their heads/descriptions are not distinct in the evidence_index, suggesting the same verification output is double-counted. | Evidence: evidence_index:E-002, evidence_index:E-006 | Why: [panel:arkcli] [arkcli:kimi-k2.7-code] Double-counting selftest artifacts inflates the apparent volume of confirmed evidence without adding independent support.
- [WARN] PR-007 arkcli panel had backend errors; review is partial | Evidence: minimax-m3: parse error; output tail: structure for a peer review note.

Let me also think about what "blind spots" the author likely missed:
1. The cert escalation from 0.3 (diff) to 0.8 (derived) is unaddressed
2. The 6/18 fixtures with no HTTP evidence - what if those are the most important canaries?
3. E-004 tiny artifacts - what do they actually contain?
4. The framework's own selftests might not catch subtle issues in the new code
5. The "18/18 clean" stat is for synthetic fixtures - real-world yield unproven

Let me also note; glm-5.2: parse error; output tail: ec: 1.75`. But many fixtures have `time_to_first_evidence_sec: null`. How is the average computed with nulls? This could be a bench scoring bug.

Now let me also consider: is there anything in the evidence that contradicts the report?

The report says "18/18 clean" - the bench summary shows fixtures: 18, clean: 18. Consistent.
The report says false_positives: 0 - bench summary shows false_positives: 0. Consistent.
The report says detection_rate: 1.0 - bench summary confirms. Consistent.

But the | Why: [panel:arkcli] At least one arkcli reviewer failed, so PASS only means the completed panel members found no blocker.

## Blind-spot check
- [arkcli] [kimi-k2.7-code] No independent red-team or intentionally vulnerable target run is included; the only validation is the self-scoring synthetic bench.
- [arkcli] [kimi-k2.7-code] The actual source changes in implementation.diff are not excerpted, so an external reviewer cannot see what was added to workers.py, check_run.py, loop_state.py, context_pack.py, or js_inventory.py.
- [arkcli] [kimi-k2.7-code] There is no evidence documenting the operator boundary that excludes .agents/skills; the report's claim is unsubstantiated.
- [arkcli] [kimi-k2.7-code] False-positive suppression events (14 in the bench summary) are reported but not analyzed for potential signal loss.
- [arkcli] [kimi-k2.7-code] No evidence shows that mentor_hints stay advisory-only and do not leak into agent prompts as authoritative constraints.
- [arkcli] [kimi-k2.7-code] Bench fixtures with recorded_requests:0 lack request/replay artifacts, so they cannot demonstrate actual HTTP behavior.
- [claude] **Self-test circularity**: The author (Claude driver) both wrote the implementation AND the selftests that validate it. Every selftest assertion was designed by the same entity that designed the feature. This isn't "wrong" per se — but it means the bench `18/18 clean` result measures compliance with the author's own specification, not correctness against an independent standard. As a heterogeneous reviewer, I flag that no adversarial test exists: no attempt to make `merge-threats` produce malformed output, no attempt to feed `js_inventory.py` a crafted path like `../../etc/passwd`, no attempt to inject prompt-manipulating content into a threat hypothesis.
- [claude] **The `check_threat_hypotheses` WARN label is in the code comment and test name, not verified in output**: The selftest at `check-run-selftest.out:150-151` uses the test name `威胁假设软警` (threat hypothesis soft warning) which implies WARN-level. But the test assertion is `bool(threat_warn)` — it only checks that something was returned, not that it was categorized as WARN rather than ERROR. The `main()` function at `implementation.diff` line 550 shows `warnings.extend(check_threat_hypotheses(run_dir))` — appended to the warnings list, not errors. This is distinguishable in the source code but NOT in the captured test output. A reader of the artifacts alone cannot confirm this is WARN-level without reading the diff.
- [claude] **The bench fixtures for the 7 new canaries have `recorded_requests: 0`**: This is acknowledged in the report's "Residual Limits" but deserves emphasis: `existing-mechanism-consumption`, `js-hidden-api-threat`, `mentor-no-progress-pivot`, `permission-matrix-idor`, `signed-client-param`, `state-machine-skip`, and `threat-hypothesis-to-evidence` all show `recorded_requests: 0` in the bench output. The bench validates process markers but cannot validate that the framework correctly records HTTP request evidence for these new paths — because no requests were made.
- [claude] **No `review.md` in the review bundle**: The bundle contains `target.md`, `report.md`, `evidence.md`, and artifacts. There's no `review.md`, no `decisions.md`, no `frontier.md`. For a maintenance review, the report IS the review output — but per CLAUDE.md's review architecture: "复审输出是候选，不是证据；最终结论仍要过 evidence/artifact/tests/recorded rationale." The absence of a separate review.md means the report's self-review IS the only review on record. This review (my output) fills that gap.
- [claude] **The `merge-threats` selftest only tests the happy path**: It tests that one valid Agent threat hypothesis is written and that a duplicate is skipped. It does NOT test: (a) Agent output with missing required fields, (b) Agent output with injection-like content, (c) an Agent file with no `## New Threat Hypotheses` section, (d) multiple Agents contributing conflicting hypotheses, (e) an already-full `hypotheses.md` with existing H-entries. The code appears to handle these gracefully (it skips missing sections, checks existing keys), but the selftest doesn't exercise these edge cases.

## Context-limit notes
- [arkcli] [kimi-k2.7-code] Artifact file contents are not included in the review bundle; judgments rely on metadata, hashes, and a single truncated bench-score excerpt.
- [arkcli] [kimi-k2.7-code] If any run files are in Chinese, I cannot read them; the provided bundle is mostly English.
- [arkcli] [kimi-k2.7-code] The relationship between the bench-internal "E-001" IDs and the bundle evidence_index E-001 is unclear.
- [arkcli] [kimi-k2.7-code] The expected evidence schema for a plan-implementation review (as opposed to a live web-pentest run) is not fully specified, so some rubric points apply weakly.
- [arkcli] minimax-m3: parse error; output tail: structure for a peer review note.

Let me also think about what "blind spots" the author likely missed:
1. The cert escalation from 0.3 (diff) to 0.8 (derived) is unaddressed
2. The 6/18 fixtures with no HTTP evidence - what if those are the most important canaries?
3. E-004 tiny artifacts - what do they actually contain?
4. The framework's own selftests might not catch subtle issues in the new code
5. The "18/18 clean" stat is for synthetic fixtures - real-world yield unproven

Let me also note
- [arkcli] glm-5.2: parse error; output tail: ec: 1.75`. But many fixtures have `time_to_first_evidence_sec: null`. How is the average computed with nulls? This could be a bench scoring bug.

Now let me also consider: is there anything in the evidence that contradicts the report?

The report says "18/18 clean" - the bench summary shows fixtures: 18, clean: 18. Consistent.
The report says false_positives: 0 - bench summary shows false_positives: 0. Consistent.
The report says detection_rate: 1.0 - bench summary confirms. Consistent.

But the
- [claude] I read the implementation.diff through sampled sections (~300 lines out of 85KB). The diff covers 7 bench fixtures, 7 Agent templates, 3 core tools (workers.py, check_run.py, loop_state.py), 1 new tool (js_inventory.py), 2 doc files, and 1 skill file. I verified the specific claims made in the report but did not exhaustively review every line of the diff. A latent bug in an unread portion (e.g., a regression in `context_pack.py`'s non-threat-hypothesis code paths) would be missed.
- [claude] The bench JSON excerpt in the review bundle was truncated at ~5000 chars. I read the full `evidence/bench-score-all.json` (28KB) and the full text output. All 18 fixtures' scores match the reported summary.
- [claude] Chinese terminology: "软警" (soft warning), "硬门" (hard gate), "报警" (alert/report). My reading of these terms is based on context and code structure (warnings list vs errors list in `main()`). I may miss nuance in security-specific Chinese terminology.
