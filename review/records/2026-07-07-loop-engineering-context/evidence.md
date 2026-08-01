# Evidence Ledger

## E-001
- Maturity: finding
- Source: code-maintenance-diff
- Trust: operator-reviewed
- Claim: The maintenance diff modifies `tools/loop_state.py`, `tools/loop_bootstrap.py`, `docs/templates/loop_prompt.md`, `tools/selftest_all.py`, `docs/WORKFLOW.md`, `docs/WORKFLOW-reference.md`, and `docs/ROUTER.md`.
- Certainty: 0.8
- Artifacts: evidence/diff.patch, evidence/diff.txt
- Supports: F-001, F-002, F-003
- Control: The artifact is a full git diff including the new file; reviewer judgement is still required for semantic correctness.

## E-002
- Maturity: candidate
- Source: local-selftest
- Trust: operator-reviewed
- Claim: Full local selftest battery passed after implementation.
- Certainty: 0.5
- Artifacts: evidence/selftest_all.txt
- Supports: F-001, F-002, F-003
- Control: Selftests are structure/regression evidence only; reviewers should still inspect semantic fit.

## E-003
- Maturity: candidate
- Source: local-benchmark
- Trust: operator-reviewed
- Claim: Existing benchmark fixtures stayed clean after the loop engineering change.
- Certainty: 0.5
- Artifacts: evidence/bench_score_all.txt
- Supports: F-001, F-002, F-003
- Control: Benchmark pass shows no fixture regression, not proof of live target quality.

## E-004
- Maturity: candidate
- Source: local-rule-checks
- Trust: operator-reviewed
- Claim: Architecture and template checks passed after the change.
- Certainty: 0.5
- Artifacts: evidence/check_rules.txt, evidence/check_templates.txt, evidence/py_compile.txt
- Supports: F-001, F-002, F-003
- Control: Reviewers should still check for stale documentation, generated cache churn, and unintended orchestration semantics.

## E-005
- Maturity: finding
- Source: focused-loop-selftests
- Trust: operator-reviewed
- Claim: Focused loop selftests cover Coda convergence, no-progress reset on certainty upgrade, coverage-matrix improvement delta, no-write derive mode, loop-state cache writes, and bootstrap loop-state refresh/fail-closed behavior.
- Certainty: 0.8
- Artifacts: evidence/loop_state_selftest.txt, evidence/loop_bootstrap_selftest.txt, evidence/loop_focused_selftest.txt, evidence/saturation_selftest.txt
- Supports: F-001, F-002, F-003
- Control: The focused selftest output names the specific loop behaviors; full selftest and bench outputs remain broader regression evidence only.

## E-006
- Maturity: finding
- Source: real-run-loop-state-smoke
- Trust: operator-reviewed
- Claim: `tools/loop_state.py` can derive loop snapshots from existing recorded run markdown without `--write`, covering an Agent Board fixture and a closure fixture.
- Certainty: 0.8
- Artifacts: evidence/real_run_loop_state_ultra_agent.txt, evidence/real_run_loop_state_recorded_closure.txt
- Supports: F-001, F-002
- Control: The command was run without `--write`; it prints loop-state Markdown and should not create canonical run facts.
