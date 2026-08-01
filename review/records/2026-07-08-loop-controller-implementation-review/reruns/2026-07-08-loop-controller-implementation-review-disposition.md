# Loop Controller Implementation Review Disposition

Review artifact: `review/records/2026-07-08-loop-controller-implementation-peer-review-final.md`

Final reviewed verdict: WARN, no BLOCKER. The third panel completed with `arkcli+claude`; one arkcli submodel still produced a parse error, so the panel result is partial but includes independent Claude Code CLI review plus two arkcli model outputs.

## Pre-Commit Diff Binding

- Verdict: WARN
- diff_fingerprint: daf510a627650f3e
- reviewed_diff: daf510a627650f3e

## Disposition

- PR-001: Accepted as review-context discipline. I downgraded maintenance verification entries from confirmed finding-style evidence to candidate/phenomenon evidence so selftests and local audits are not represented as vulnerability-grade confirmed facts.
- PR-002: Accepted as a limitation. The bundle uses snippets, not full artifact bodies. The artifact hashes and excerpts are retained; this is acceptable for maintenance review, not a live exploit proof.
- PR-003: Partially accepted. Added explicit `advisory_only=true`, `can_stop_reason`, documentation that shadow `can_stop` never grants stop, and a production-path audit artifact showing writes are limited to derived `state/` outputs.
- PR-004: Accepted. Added exact adversarial regression artifact `evidence/adversarial-type-a-coda.json` covering `coda_converged=true` with open Type A fronts; also expanded status parser tests for hyphenated Type A, unknown status, and conflicting terminal statuses.
- PR-005: Accepted as measurement limitation. No old pre-fix artifact was preserved. The post-fix regression now proves the target behavior directly; the report wording is kept as maintenance implementation, not real-world finding-yield proof.
- PR-006: Accepted as inherent limitation. Synthetic and real-run smoke artifacts are generated locally by the code under test, so they are regression evidence rather than independent ground truth. Independent review remains the challenge layer.
- PR-007: Recorded. `minimax-m3` parse error makes the arkcli panel partial; the completed reviewers found no blocker after the review-context downgrade and adversarial regression artifact.

## Additional Claude Blind-Spot Items

- Malformed `closed, deferred` statuses could be double-counted. Fixed: deferred/closed parsing is now mutually exclusive and conflicting terminal statuses are classified as closure blockers.
- `progress_ledger.py` silently retains only the last 50 cycles. Fixed: added code comment documenting that this is a bounded derived cache and canonical history remains Markdown.
- `loop_prompt.md` over-weighted controller recommendations. Fixed: changed from "follow unless override" to "treat as a control-plane challenge" with recorded follow/override rationale.
- Report questions were not answered directly. Fixed in `report.md` with a `Driver Answers` section.

## Post-Fix Peer Review Disposition

Post-fix review artifact: `review/records/2026-07-08-loop-controller-implementation-peer-review-postfix.md`

The post-fix review returned BLOCKER before disposition. The blocker was valid: `report.md` answered the review questions with categorical Yes/No language even though the evidence ledger intentionally kept all support at phenomenon/candidate certainty.

- PR-001: Accepted and fixed. `report.md` now frames all five Driver Answers as bounded maintenance-review conclusions supported by candidate evidence, not confirmed vulnerability findings or confirmed real-world yield.
- PR-002: Accepted as residual limitation with mitigation. Added post-fix source audit artifact `evidence/loop-state-postfix-audit.out` and refreshed `evidence/implementation.diff`; this improves traceability but remains a candidate maintenance audit, not formal proof.
- PR-003: Accepted as residual limitation. Real-run validation remains a no-write representative smoke, not live replay. The report now avoids claiming more than the artifact can support.
- PR-004: Accepted with mitigation. Added `evidence/doc-right-tree-files.out` to show the staged right-tree doc paths; correctness still relies on review of the diff and stale-wording scan.
- PR-005: Accepted and fixed for the concrete gap. Added detailed `loop_state` selftest coverage for fenced-code front filtering and all-`blocked_type_b` handling.
- PR-006: Recorded. The arkcli panel remained partial because one model leg had a parse error; the Claude Code CLI review and other arkcli reviewer outputs were still preserved as challenge material.

Additional blind spots addressed after the post-fix review:

- Fenced-code `### F-xxx` headings could be counted as real fronts by the projection path. Fixed by stripping fenced code and filtering projected fronts back to canonical frontier headings.
- `workers.agent_discipline_issues()` failure was silently swallowed. Fixed by adding an advisory `agent-discipline-audit-unavailable` mentor hint.
- Pure `blocked_type_b` runs lacked regression coverage. Fixed with a selftest that pins non-open, non-unclassified, review-candidate behavior.

## Post-Fix Rerun Disposition

Post-fix rerun artifact: `review/records/2026-07-08-loop-controller-implementation-peer-review-postfix-rerun.md`

Final rerun verdict: WARN, no BLOCKER.

- PR-001/PR-005 py-compile artifact missing/empty: fixed by making `evidence/py-compile.out` non-empty and regenerating `evidence.json`; dangling citations are now `{}`.
- PR-002 no confirmed evidence: accepted as intended limitation. This maintenance review keeps all entries phenomenon/candidate and does not claim confirmed security findings or measured real-target yield.
- PR-003 missing review/decisions trail: fixed by adding `review.md` and `decisions.md` to the review bundle.
- PR-004 partial arkcli panel: recorded. One arkcli model leg still had a parse error; completed reviewers returned WARN with no BLOCKER.
- PR-006 stale wording command irreproducible: fixed by replacing the prose command with the concrete `rg` invocation.
- PR-007 adjacent scope under-described: fixed by adding an `Adjacent Scope In This Diff` section to `report.md`.

## Post-Disposition Verification

- `python3 tools/loop_state.py --selftest`
- `python3 tools/run_controller.py --selftest`
- `python3 tools/selftest_all.py --only loop_state,progress_ledger,run_controller,loop_bootstrap`
- `python3 tools/check_rules.py`
- `python3 tools/check_templates.py`
- `git diff --check`
- Refreshed bundle: `review/records/2026-07-08-loop-controller-implementation-review/review/review_bundle.json`
  - bundle hash: `c8d97dd2e3b4181d594c855e3ca1280ea8983184`
  - evidence index hash: `aef38ec658adb469d9ee78c32d04bc48fad00e90`
