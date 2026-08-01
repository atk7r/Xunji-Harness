# Peer Review Panel — 2026-07-08-loop-controller-implementation-review

_backend: panel:arkcli+claude · 2026-07-08T02:06Z_
> 候选, 非裁决。driver 须逐条过证据门。

## Verdict: BLOCKER

_backend: panel:arkcli+claude_
_brain: codex_
_bundle_hash: 009c810e9420ee9033b809aab7bc0f48d9a1525c_
_evidence_index_hash: dfb96c54c70ee63b3209318ef5299b8673f4c082_

## Findings
- [BLOCKER] PR-001 Confirmed findings E-002 through E-006 rest on author-authored selftests and audits while the implementation diff E-001 is unconfirmed at certainty 0.3. | Evidence: evidence_index:E-001, evidence_index:E-002, evidence_index:E-003, evidence_index:E-004, evidence_index:E-005, evidence_index:E-006, report.md | Why: [panel:arkcli] [arkcli:kimi-k2.7-code] The 60KB implementation.diff is the actual change under review. Derivative selftest pass outputs and a small audit file cannot independently confirm the code is correct; they only confirm that the implementer’s tests and audit logic pass.
- [BLOCKER] PR-002 The report asserts the shadow controller 'never chooses exploit steps, promotes evidence, or grants closure' and that E-004 is a no-write snapshot, but the evidence does not support these broad negative claims. | Evidence: evidence_index:E-004, evidence/scshr-real-run-validation.json, report.md | Why: [panel:arkcli] [arkcli:kimi-k2.7-code] A single JSON state dump is one observation and cannot prove a negative. The report’s strong claims about absence of orchestration and writes exceed what the evidence can support.
- [BLOCKER] PR-003 tools/progress_ledger.py and tools/run_controller.py --shadow create derived state files that can become a second source of truth, and this risk is insufficiently audited. | Evidence: report.md, evidence_index:E-006, evidence/run-controller-advisory-audit.out | Why: [panel:arkcli] [arkcli:kimi-k2.7-code] Derived progress ledgers and controller shadow state can drift from Markdown as source of truth. An 813-byte audit file is too small to substantiate that these new files remain advisory and harmless.
- [WARN] PR-004 Selftest pass outputs are treated as confirmed findings with has_control=true despite lacking independence from the implementation under test. | Evidence: evidence_index:E-002, evidence_index:E-003, evidence/selftest-loop-controller.out, report.md | Why: [panel:arkcli] [arkcli:kimi-k2.7-code] Tests written by the same entity that wrote the implementation validate intended behavior, not adversarial reality. has_control=true is inappropriate for internal selftests.
- [WARN] PR-005 E-005 stale wording scan is elevated to a confirmed finding despite being a minor maintenance observation with no security impact. | Evidence: evidence_index:E-005, evidence/stale-wording-scan.out | Why: [panel:arkcli] [arkcli:kimi-k2.7-code] A 331-byte stale-wording scan is doc drift, not a vulnerability, and treating it as confirmed dilutes the review.
- [WARN] PR-006 No evidence demonstrates the exact adversarial state (Coda convergence + Type A blocked fronts + open fronts) that the fix is designed to handle. | Evidence: evidence_index:E-004, evidence/scshr-real-run-validation.json, report.md | Why: [panel:arkcli] [arkcli:kimi-k2.7-code] The fix targets a specific corner case, but the 'real run smoke' shows 'coda_converged': false, leaving the critical path unverified.
- [WARN] PR-007 evidence.md prose is not visible in the bundle, preventing full claim-to-evidence cross-check. | Evidence: review_bundle.files.evidence.md | Why: [panel:arkcli] [arkcli:kimi-k2.7-code] Without the actual evidence descriptions, independent reviewers cannot verify whether the written claims for each EID match the recorded artifacts.
- [WARN] PR-008 No replay-style artifacts exist; all confirmed behavior rests on non-replayable stdout or text dumps. | Evidence: evidence_index | Why: [panel:arkcli] [arkcli:kimi-k2.7-code] The absence of .replay.json files means no confirmed finding can be independently replayed or verified against actual request/response behavior.
- [WARN] PR-009 E-004 "real run validation" is a hand-shaped JSON snapshot, not a captured parse of the live run's loop_state; the "mixed status format" claim is not directly evidenced. | Evidence: evidence/scshr-real-run-validation.json | Why: [panel:arkcli] [arkcli:glm-5.2] No raw status-line input artifact is included; a reviewer cannot confirm the parser actually consumed the run's tokens.
- [WARN] PR-010 E-003 bundles eight selftest/gate artifacts under one confirmed finding with no per-suite excerpts; several are ~18-24 bytes (likely bare OK), so the relevant loop-controller suites cannot be distinguished from generic hygiene passes. | Evidence: evidence/check-rules.out, evidence/check-templates.out, evidence/git-diff-check.out, evidence/py-compile.out, evidence/check-run-selftest.out, evidence/session-handoff-selftest.out, evidence/setup-run-selftest.out, evidence/anti-drift-selftest.out | Why: [panel:arkcli] [arkcli:glm-5.2] Confirmed finding lacks traceable sub-evidence for the specific fix.
- [WARN] PR-011 Advisory controller audit (E-006) does not exercise the adversarial case the fix targets: `coda_converged=true` with open Type A fronts. | Evidence: evidence/run-controller-advisory-audit.out | Why: [panel:arkcli] [arkcli:glm-5.2] The core regression (Coda convergence leaking to Completion pause) is asserted, not replayed.
- [WARN] PR-012 E-001 implementation.diff (60KB, certainty 0.3) is the central object of review yet is not excerpted or cross-checked; report claims about token parsing and Coda pivot logic are unverifiable from the bundle. | Evidence: evidence/implementation.diff | Why: [panel:arkcli] [arkcli:glm-5.2] Lowest-certainty item carries the entire behavioral claim base.
- [WARN] PR-013 arkcli panel had backend errors; review is partial | Evidence: minimax-m3: parse error; output tail: vidence-based.

Actually, I realize I should be careful - the rubric says "Only certainty >= 0.8 may be reported as confirmed" but this is for findings, not for the review. My review findings are about the report's quality, not new vulnerabilities.

Let me structure my findings around the rubric:

1. **Evidence gate**: For E-002 through E-006 (all 0.8 confirmed), do artifacts support claims? Yes, mostly. The artifacts exist. But the claims are self-affirming.

2. **Coverage**: Is the loop_state, | Why: [panel:arkcli] At least one arkcli reviewer failed, so PASS only means the completed panel members found no blocker.

## Blind-spot check
- [arkcli] [glm-5.2] No artifact shows the negative/control case: a run where Coda converged AND the controller still refuses closure. E-004 has `coda_converged:false`, so the targeted regression path is not directly exercised.
- [arkcli] [glm-5.2] E-005 stale-wording scan (331 bytes) is not excerpted; cannot confirm it catches the specific stale terms ("Completion pause", "closure candidate") the report claims were removed.
- [arkcli] [glm-5.2] `runs/scshr_20260708` is referenced as the real-run smoke, but only the derived validation JSON is in the bundle; the run's own `state/loop_state.md` or `/loop` transcript is absent.
- [arkcli] [glm-5.2] Report claims `.claude/skills` (not `.agents/skills`) was updated, but no artifact enumerates the touched skill files; the diff hash is the only trace.
- [arkcli] [glm-5.2] No before/after control artifact demonstrates the OLD behavior producing a false Completion pause; the fix's impact is asserted, not measured.
- [claude] **(Token parsing edge case)**: The `_status_tokens` regex (`[a-z0-9_]+`) under-splits on hyphens and over-splits on parentheses. A status like `blocked_type_a(waiting_for_creds)` would extract `["blocked_type_a", "waiting_for_creds"]` — correct match. But `blocked-type-a` (hyphenated) would extract `["blocked", "type", "a"]` — miss. The current frontier.md convention uses underscores, not hyphens, so this may not be a live bug. But no selftest validates the hyphen-failure path, meaning a future format change could silently break the gate.
- [claude] **(CLOSURE_CANDIDATE with `can_stop=false`)**: The controller correctly identifies `CLOSURE_CANDIDATE` state (E-006 selftest: `closed_ctl["state"] == "CLOSURE_CANDIDATE"`) but `can_stop` stays `False`. The `/loop` prompt template (`loop_prompt.md`) says "Only when the controller and run files show a closure-review candidate:" — it gates on `closure_review_candidate` signal, not `can_stop`. So the dead `can_stop` boolean doesn't affect the intended workflow, but it's a misleading signal that a future Root or agent might interpret incorrectly.
- [claude] **(Evidence index `has_control` for E-002 through E-006 is `true`, but these are self-reported tool outputs)**: The control-concept in Xunji's evidence framework is designed for live-target probing (positive control: "first show the mechanism works normally, then show its absence"). For maintenance tool outputs, "control" means "exit code 0 was verified." The artifacts don't show exit codes — they show success messages. The evidence ledger's `has_control: true` is a generous interpretation for tool-output evidence, but this is consistent with maintenance-review practice where tool output IS the control.
- [claude] **(No evidence of the /loop command actually being tested end-to-end)**: All selftests create synthetic run directories. There's no evidence that `loop_bootstrap.py` was invoked against a real run and that the generated `/loop` prompt actually invokes the new tools in the correct order during a live Claude Code session. This is an integration-test gap.
- [claude] **(The `scshr-real-run-validation.json` shows `material_progress: true` but `artifact_backed_progress: false`)**: For the scshr run, there are 4 open blocked_type_a fronts, `material_progress: true` (new evidence entries exist) but `artifact_backed_progress: false` (no saved artifacts). While this doesn't affect the gate behavior (stop is correctly blocked), it suggests the scshr run has evidence entries without saved artifacts — a quality signal the review doesn't comment on.

## Context-limit notes
- [arkcli] [glm-5.2] Artifact contents were not opened beyond the evidence_index excerpts; only E-004 had a content excerpt. Size/sha1 alone were used for other artifacts.
- [arkcli] [glm-5.2] `scshr` run naming is interpreted as a red-team run identifier; any CNVD/Taiwan-specific semantics are not fully graspable from this bundle.
- [arkcli] [glm-5.2] Report's "Verification Already Run" list is treated as claims; only evidence_index entries with artifacts are treated as facts.
- [arkcli] [glm-5.2] Certainty grading is inherited from the evidence_index and not re-derived from raw bytes.
- [arkcli] minimax-m3: parse error; output tail: vidence-based.

Actually, I realize I should be careful - the rubric says "Only certainty >= 0.8 may be reported as confirmed" but this is for findings, not for the review. My review findings are about the report's quality, not new vulnerabilities.

Let me structure my findings around the rubric:

1. **Evidence gate**: For E-002 through E-006 (all 0.8 confirmed), do artifacts support claims? Yes, mostly. The artifacts exist. But the claims are self-affirming.

2. **Coverage**: Is the loop_state,
- [claude] I did not have access to the actual live run directory `runs/scshr_20260708/` to independently verify the `frontier.md` status format used in the real run. The E-004 JSON output is trusted only as far as the bundle provides it.
- [claude] The full 60KB implementation diff was read in 4 chunks (~100, ~200, ~300, ~300 lines). Some middle sections of the diff (primarily WORKFLOW-reference.md template additions for `Input Shape Catalog` and `Permission/State Working Matrix`) contain documentation-only changes. I may have missed late-diff details in `loop_state.py`'s `_mentor_hints` implementation between lines 600-650, though I covered the key functions.
- [claude] I am reviewing Chinese-language code comments and documentation (CLAUDE.md, WORKFLOW.md, loop_prompt.md). My understanding of project-specific Chinese terminology (e.g., `收口` for closure, `漏测` for coverage gap) is based on context from the codebase and may miss domain-specific nuance.
