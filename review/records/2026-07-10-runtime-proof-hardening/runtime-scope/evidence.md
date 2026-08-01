# Runtime Evidence

## E-001 - Prompt modes and active-run hooks

- Maturity: finding
- Action: Review turn classification, PreToolUse restrictions, output/run Stop gates, and canonical active-front parsing.
- Result: Code review and negative selftests show explicit execute intent is required; explain/pause are read-only; active-run exceptions fail closed; fan-out is current-turn. Live-entrypoint activation is claimed separately in E-003.
- Policy rationale: `probing` and `working` are unfinished active work; counting them prevents status relabeling from bypassing Agent fan-out.
- Control: Focused negative selftests and installed observation.
- Replicated: yes
- Artifacts: `output_gate.diff`, `run_gate.hunks-01.diff`, `run_gate.hunks-02.diff`, `settings.diff`, `turn_contract.lines-001-170.txt`, `turn_contract.lines-171-340.txt`, `turn_contract.lines-341-510.txt`, `turn_contract.lines-511-680.txt`, `turn_contract.lines-681-end.txt`, `run_model.diff`
- Certainty: 1.0

## E-002 - Agent and Cron receipts

- Maturity: finding
- Action: Review hash-linked transcript-backed receipts, per-turn Agent disposition, and Cron list/create/delete/list ownership.
- Result: Code review and negative selftests show old/manual/unmerged Agent state and stale/unlisted Cron state do not satisfy gates. Runtime activation is claimed separately in E-003.
- Control: Negative selftests cover each rejected bypass.
- Replicated: yes
- Artifacts: `runtime_receipts.lines-001-150.txt`, `runtime_receipts.lines-151-300.txt`, `runtime_receipts.lines-301-450.txt`, `runtime_receipts.lines-451-end.txt`, `workers.diff`
- Certainty: 1.0

## E-003 - Installed runtime observation

- Maturity: finding
- Action: Execute installed hook entrypoints against an isolated temporary active run.
- Result: Two independent installed-entrypoint executions each cover 20 denied/allowed turn, Agent, Cron, review, startup-selftest, and completion assertions; each ten-event runtime chain validates.
- Control: Both executions reject a bare completion `PASS` and accept only the evidence-hash-bound four-check response; separate module selftests replicate the logic.
- Replicated: yes
- Artifacts: `runtime_observation.source.txt`, `installed-settings.json`, `runtime_observation.summary.json`, `runtime_observation.replica.summary.json`
- Certainty: 0.8

## E-004 - Repository regression

- Maturity: finding
- Action: Run the complete selftest suite after implementation.
- Result: 57 passed, 0 failed; raw log retains per-suite and total timing.
- Control: Raw output retained.
- Replicated: yes
- Artifacts: `selftest_all.log`, `peer_review.round2.md`, `disposition.md`
- Certainty: 1.0
