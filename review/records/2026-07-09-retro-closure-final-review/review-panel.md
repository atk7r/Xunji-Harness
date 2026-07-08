# Peer Review Panel — 2026-07-09-retro-closure-final-review

_backend: panel:arkcli+claude · 2026-07-08T17:46Z_
> 候选, 非裁决。driver 须逐条过证据门。

## Verdict: BLOCKER

_backend: panel:arkcli+claude_
_brain: codex_
_bundle_hash: 21c4e4fb4733cc9856c0522a01e5868bedaaabdd_
_evidence_index_hash: d8836dc204326aede7a05ef3880b9a2833c5f33f_

## Findings
- [BLOCKER] PR-001 Four confirmed evidence entries (E-002–E-005) at certainty 1.0 lack any artifact in the review bundle. | Evidence: evidence_index:E-002 (artifacts=[]), evidence_index:E-003 (artifacts=[]), evidence_index:E-004 (artifacts=[]), evidence_index:E-005 (artifacts=[]), report.md:Verification Already Run | Why: [panel:arkcli] [arkcli:kimi-k2.7-code] Confirmed findings must be backed by artifacts. The report's list of self-test commands is narrative, not proof of execution. Attach logs (selftest_all, check_run, check_hook, safety_gate, run_gate, output_gate, loop_state, run_controller, git diff --check) or downgrade to candidate certainty ≤0.5.
- [WARN] PR-002 E-001’s staged-diff artifact proves the diff exists but does not substantiate that the regression battery, safety-boundary checks, or referenced-run structural checks passed. | Evidence: evidence_index:E-001 artifact evidence/staged-diff.txt sha1=859c0cffe76b402608d23dca8b6cd0654ba3763a, report.md:Verification Already Run | Why: [panel:arkcli] [arkcli:kimi-k2.7-code] A source diff is not evidence of test execution. Claims that tests passed still need command-output artifacts; otherwise the diff review rests on unrecorded assertions.
- [WARN] PR-003 Frontier F-001 remains open and no completion marker is recorded; the run is not in a final-closable state. | Evidence: frontier.md:F-001 status open, report.md Expected Invariants | Why: [panel:arkcli] [arkcli:kimi-k2.7-code] Hard closure gates require open fronts = 0 and a completion marker. The report correctly notes this is maintenance work, but the run cannot be treated as final until F-001 is closed or deferred with evidence. [review-output-invalid: PR-003 references unknown affected_eids: F-001]
- [WARN] PR-004 D-002’s rationale for omitting artifacts conflates live-target replay with local self-test logging. | Evidence: decisions.md:D-002, report.md:Verification Already Run | Why: [panel:arkcli] [arkcli:kimi-k2.7-code] --replay-verify is for live egress replay, but the listed local self-tests produce no live-target traffic and should have been logged as artifacts. Their absence is not excused by the replay-verify policy.
- [WARN] PR-005 arkcli panel had backend errors; review is partial | Evidence: minimax-m3: parse error; output tail:  selftest for the legacy path fallback behavior. Cases 1-3 of the existing selftest are about agent board gates, not path resolution. Did the new path resolution get tested? Probably not in the run_gate selftest.

8. **The new `docs/AI_ENV_SETUP.md`** (226 lines) is added. The report doesn't review this content for accuracy — it just mentions it in the change groups. Is there anything wrong with the AI_ENV_SETUP doc?

9. **The report claims**: "Safety-critical hook behavior is not weakened: hard; glm-5.2: arkcli exit 1; stderr/stdout tail: {
  "ok": false,
  "error": {
    "type": "error",
    "message": "arkruntime.create_responses: RequestError code: 500, err: Post \"https://ark.cn-beijing.volces.com/api/plan/v3/responses\": net/http: TLS handshake timeout, request_id: 202607090143070000720BEA7741E92B31"
  }
}
 | Why: [panel:arkcli] At least one arkcli reviewer failed, so PASS only means the completed panel members found no blocker.

## Blind-spot check
- [claude] **Review artifact inflation**: The staged diff is 409KB, but roughly 300KB+ consists of new review record files being committed (`review/records/2026-07-08-*/evidence/*.txt`, `review_result*.json`, `review_bundle.json`). These are legitimate audit trail records from previous Codex-authored maintenance rounds, not framework changes. The report's "Main Change Groups" section doesn't clearly separate framework-code changes from audit-record additions. A reviewer who only skims the diff file list might mistake the volume of review-artifact additions for extensive framework changes.
- [claude] **Same-turn guidance is text-only**: The "same-cycle handling" and "CVE trigger" guidance added to SKILL.md files, anti_drift.py binding rules, and closure messages are all textual instructions to the AI driver. None are programmatically enforced. An AI that ignores these instructions (due to context pressure, drift, or model limitations) faces no hard gate. The only hard enforcement is the `check_loop_state_closure_blockers` call in `check_run.py` — but that only fires when `_closure_gate_active` returns True, and that function's definition was not in the diff excerpt I could read. The anti-drift CVE trigger rule (`anti_drift.py:3843`) is in the BINDING_RULES_TIER1 list, which is injected as a flashcard — it's a reminder, not a guard.
- [claude] **STUB_PAGE / AUTH_GATE classification could mask real applications**: The `classify_hosts.py` COMMON_SUBPATHS list (`/SCSRwd/`, `/Identity/Account/Login`, `/Identity/Account/Register`, `/eServices/`, `/Login.aspx`, `/Default.aspx`) is narrow and AIS-specific. A host serving an IIS default page at root but having a real application at `/app/v2/admin/` or `/api/` would be classified as STUB_PAGE and excluded from the "interesting" candidate list, with no common subpath probe reaching it. The SKILL.md guidance says "The run still needs a frontier/evidence verdict" for STUB_PAGE/AUTH_GATE assets, but the classification output would mark them as uninteresting, potentially causing them to be overlooked during front creation.
- [claude] **`_closure_gate_active` function not visible in diff**: The new `check_loop_state_closure_blockers` function gates on `_closure_gate_active(run_dir)`, but the definition of that function wasn't in the diff (it appears to be pre-existing code). I cannot verify that it correctly identifies when a run is attempting closure — it might check for `report.md` existence or a "FINAL" keyword, which could have edge cases.
- [claude] **No heterogeneous review of the safety-critical changes**: The diff modifies `run_gate.py` (hook code — safety-critical). Per the Review Architecture table in CLAUDE.md, when Codex and arkcli are both available, the review panel should include heterogeneous backends (kimi-k2.7-code, minimax-m3, glm-5.2). The `review.md` placeholder references `tools/peer_review.py ... --driver codex`, suggesting a Codex-authored review, but no actual panel run is recorded. The `target.md` says "Codex self-review does not count" — which is exactly the situation we have (Codex authored the diff, and the review was supposed to be done by Codex via peer_review.py, which hasn't run).

## Context-limit notes
- [arkcli] minimax-m3: parse error; output tail:  selftest for the legacy path fallback behavior. Cases 1-3 of the existing selftest are about agent board gates, not path resolution. Did the new path resolution get tested? Probably not in the run_gate selftest.

8. **The new `docs/AI_ENV_SETUP.md`** (226 lines) is added. The report doesn't review this content for accuracy — it just mentions it in the change groups. Is there anything wrong with the AI_ENV_SETUP doc?

9. **The report claims**: "Safety-critical hook behavior is not weakened: hard
- [arkcli] glm-5.2: arkcli exit 1; stderr/stdout tail: {
  "ok": false,
  "error": {
    "type": "error",
    "message": "arkruntime.create_responses: RequestError code: 500, err: Post \"https://ark.cn-beijing.volces.com/api/plan/v3/responses\": net/http: TLS handshake timeout, request_id: 202607090143070000720BEA7741E92B31"
  }
}

- [arkcli] PR-003 references unknown affected_eids: F-001
- [claude] The `_closure_gate_active` function in `check_run.py` is referenced but its definition was not in the diff excerpt I could read. Without seeing it, I cannot fully verify that the loop_state closure blocker hard-gate activates at the right time. This could be a pre-existing function I'm missing, or it could have an edge case.
- [claude] The `peer_review.py` changes add a `_strip_template_review_placeholders` function that is called but not defined in the diff excerpt — it may be pre-existing or defined elsewhere in the same file.
- [claude] Some Chinese-language CVE/CNVD context in `knowledge/soarcloud-ais-hr.md` (ZUSO ART advisories ZA-2025-04..09) references Taiwanese HRD products I cannot independently verify against public databases.