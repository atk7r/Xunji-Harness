# Evidence Ledger

## E-001

- Maturity: phenomenon
- Certainty: 0.3
- Source: local-maintenance-diff
- Result: Frozen implementation diff and new source files for independent maintenance review.
- Artifacts: evidence/implementation.diff
- Supports: maintenance review context

## E-002

- Maturity: candidate
- Certainty: 0.5
- Source: local-command-output
- Result: Focused aggregate selftests passed for loop state, progress ledger, run controller, and loop bootstrap; detailed loop_state selftest includes code-block front filtering and blocked_type_b regression coverage.
- Control: command output captured after implementation with exit code 0
- Artifacts: evidence/selftest-loop-controller.out, evidence/loop-state-selftest-detailed.out
- Supports: selftest registration and execution claims

## E-003

- Maturity: candidate
- Certainty: 0.5
- Source: local-command-output
- Result: Static and lifecycle checks passed: py_compile, check_rules, check_templates, check_run selftest, session_handoff selftest, setup_run selftest, anti_drift selftest, and git diff check.
- Control: command outputs captured after implementation with exit code 0
- Artifacts: evidence/py-compile.out, evidence/check-rules.out, evidence/check-templates.out, evidence/git-diff-check.out, evidence/check-run-selftest.out, evidence/session-handoff-selftest.out, evidence/setup-run-selftest.out, evidence/anti-drift-selftest.out
- Supports: regression verification claims

## E-004

- Maturity: candidate
- Certainty: 0.5
- Source: local-command-output
- Result: Representative no-write real run smoke on `runs/scshr_20260708` counted four `blocked_type_a` fronts as open, set `completion_pause_candidate=false`, and returned controller `can_stop=false`.
- Control: command output captured from no-write derive path after implementation
- Artifacts: evidence/scshr-real-run-validation.json, evidence/scshr-frontier-status-lines.out
- Supports: Type A open-front regression fix

## E-005

- Maturity: candidate
- Certainty: 0.5
- Source: local-command-output
- Result: Stale wording scan found no remaining user-facing `Coda stop signal`, `stop the autonomous drive`, or `Completion pause checks` wording in Claude/root loop paths.
- Control: command output captured after implementation with exit code 0
- Artifacts: evidence/stale-wording-scan.out, evidence/doc-right-tree-files.out
- Supports: prompt/root wording fix

## E-006

- Maturity: candidate
- Certainty: 0.5
- Source: local-source-audit
- Result: Source audit of `tools/run_controller.py` and `tools/progress_ledger.py` found writes limited to derived `state/` outputs and no probe/scan/subprocess execution path.
- Control: grep audit over write/action-related symbols after implementation
- Artifacts: evidence/run-controller-advisory-audit.out
- Supports: shadow/advisory boundary claim

## E-007

- Maturity: candidate
- Certainty: 0.5
- Source: local-adversarial-regression
- Result: Synthetic run exercised the exact target state: `coda_converged=true` with two open Type A fronts, including one hyphenated `blocked-type-a` spelling. `loop_state` kept both fronts open, set `completion_pause_candidate=false`, and `run_controller --shadow` returned `NEEDS_PIVOT`, `advisory_only=true`, and `can_stop=false`.
- Control: repeated loop-state refresh produced no-progress convergence before controller derivation
- Artifacts: evidence/adversarial-type-a-coda.json
- Supports: Coda convergence must pivot/review, not Completion pause, while Type A/open fronts remain

## E-008

- Maturity: candidate
- Certainty: 0.5
- Source: local-source-audit
- Result: Post-fix source audit shows fenced-code stripping, canonical frontier ID filtering, non-silent agent discipline audit failure handling, and explicit blocked_type_b/code-block selftest coverage in `tools/loop_state.py`.
- Control: `rg` audit and detailed loop_state selftest captured after the post-fix review blocker was addressed
- Artifacts: evidence/loop-state-postfix-audit.out, evidence/loop-state-selftest-detailed.out
- Supports: post-fix response to reviewer PR-002/PR-005 blind spots
