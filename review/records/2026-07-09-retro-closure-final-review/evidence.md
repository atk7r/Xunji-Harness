# Evidence

## E-001 — active behavior diff under review

- Maturity: artifact
- Certainty: 1.0
- Control: generated from the Git index while excluding `review/records/**`, so reviewers can inspect current code/docs behavior without historical audit-record interleaving.
- Artifacts: `evidence/active-diff.txt`

## E-002 — full local regression battery passed

- Maturity: verification
- Certainty: 1.0
- Control: command exited 0 and reported `53 passed, 0 failed`.
- Command: `python3 tools/selftest_all.py --timeout 600`
- Artifacts: `evidence/selftest-all-final-log.txt`

## E-003 — safety boundary explicit checks passed

- Maturity: verification
- Certainty: 1.0
- Control: each command exited 0.
- Commands: `python3 tools/check_hook.py`; `python3 .claude/hooks/safety_gate.py --selftest`; `python3 .claude/hooks/run_gate.py --selftest`; `python3 .claude/hooks/output_gate.py --selftest`; `python3 tools/harness/guard.py`; `python3 sentinel/replay.py`; `python3 sentinel/verify_layers.py`; `python3 tools/check_rules.py`.
- Artifacts: `evidence/safety-boundary-log.txt`

## E-004 — referenced scshr run is structurally passable but not auto-complete

- Maturity: verification
- Certainty: 1.0
- Control: local structural checks only; no live replay verification was run.
- Commands: `python3 tools/check_run.py runs/scshr_20260708`; `python3 tools/loop_state.py runs/scshr_20260708 --write`; `python3 tools/run_controller.py runs/scshr_20260708 --shadow`.
- Result: `check_run.py` passed with a non-blocking anti-lump warning; loop state reported 0 closure blockers and `Loop 已完成: 否`; controller reported `NEEDS_PIVOT`, `can_stop=false`.
- Artifacts: `evidence/scshr-state-log.txt`

## E-005 — staged diff whitespace check passed

- Maturity: verification
- Certainty: 1.0
- Control: command exited 0 after mechanical whitespace cleanup of review artifacts.
- Command: `git diff --cached --check`
- Artifacts: `evidence/diff-check-log.txt`
