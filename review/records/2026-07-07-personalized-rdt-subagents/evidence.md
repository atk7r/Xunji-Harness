# Evidence Ledger

## E-001

- Maturity: finding
- Reportable: yes
- Time: 2026-07-07
- Action: local maintenance verification of personalized RDT Agent Board diff
- Source: local tool selftests and run compatibility smoke tests
- Result: targeted context pack, worker, setup, saturation, benchmark, check_rules, py_compile, diff whitespace, OPPO run agent-check, and OPPO check_run checks passed.
- Caused by us: yes
- Alternative explanation: tests are local and cover framework mechanics, not external model review quality or every historical run.
- Certainty: 1.0
- Replicated / Control: `tools/selftest_all.py --only context_pack,workers,setup_run,check_templates` re-ran the key suites after the compatibility narrowing; `tools/workers.py agent-check runs/oppo_20260707_20260707` is clean on a pre-existing run.
- Artifacts: `evidence/test-summary.txt`, `evidence/diff-summary.txt`, `evidence/raw-test-transcript.txt`, `evidence/implementation-grep.txt`, `evidence/scaffold-context-sample.txt`
- Supports: F-001, F-002
- Refutes:
- Next: run independent peer review and adjudicate any findings.
