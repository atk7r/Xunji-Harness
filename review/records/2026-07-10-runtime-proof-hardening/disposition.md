# Independent Review Round 1 Disposition

## PR-001 - Invalid byte-split diff fragments

- Status: accepted
- Resolution: The byte-split fragments were removed. Hook changes now use one complete valid diff per file; `check_run.py` uses two hunk-boundary patches, each with a repeated file header and each verified by `git apply --check --reverse --unidiff-zero`.
- Evidence: `output_gate.diff`, `run_gate.hunks-01.diff`, `run_gate.hunks-02.diff`, `settings.diff`, `check_run.hunks-01.diff`, `check_run.hunks-02.diff`, `check_run.hunks-03.diff`, `check_run.hunks-04.diff`.

## PR-002 - No runtime execution observation

- Status: accepted
- Resolution: Added and executed an isolated installed-entrypoint observation. All 19 checks pass, including weak/structured completion responses, with a ten-event valid receipt chain.
- Evidence: `runtime_observation.py`, `runtime_observation.lines-001-190.txt`, `runtime_observation.lines-191-380.txt`, `runtime_observation.lines-381-end.txt`.

## PR-003 - Review report is intentionally concise

- Status: dismissed
- Resolution: Reason: this is a maintenance review scope, not a vulnerability deliverable. `report.md` is a scope/index; detailed claims and artifacts live in `evidence.md`, `context.md`, and independent review records. No confirmed claim is omitted from the evidence ledger.

## PR-004 - Review provenance absent before first review

- Status: accepted
- Resolution: The first independent panel's raw Markdown and JSON are retained in this review record; this second round reviews the repaired package. Live-run closure receipt semantics are separately exercised in the runtime-observation artifacts and full selftests.
- Evidence: `peer_review.round1.md`, `peer_review.round1.json`, and all three runtime-observation chunks.

## PR-005 - No installed settings snapshot

- Status: accepted
- Resolution: Added an exact post-change snapshot and runtime wiring checks for UserPromptSubmit, global PreToolUse, PostToolUse, PostToolUseFailure, SubagentStart, and SubagentStop.
- Evidence: `installed-settings.json`, `settings.diff`, all three runtime-observation chunks, `selftest_all.log`.

## PR-006 - Partial arkcli panel

- Status: accepted
- Resolution: Round one is retained as partial and non-final. The heterogeneous panel is rerun after all evidence repairs; any remaining backend limitation will stay explicit.

## Blind Spots

- Same-user malicious forgery is explicitly outside this feature's threat claim. Receipts constrain a lazy/noncompliant model and provide audit evidence; they are not a privileged OS attestation service.
- Documentation drift was searched after edits; stale manual-review, budget-reason, and heartbeat-as-proof language was removed from the primary Claude rules, skills, workflow, and templates. `check_templates` and the full suite pass.
- The slow `classify_hosts` selftest is pre-existing and outside this process-hardening change; it passed twice in the full suite.
