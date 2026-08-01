# Bench Review: Agent Conflict Gate

- Date: 2026-06-29
- Scope: `check_run.py` closure gate for unresolved `state/conflicts.json` entries.
- Command: `python3 tools/selftest_all.py`
- Result: 32 passed, 0 failed.
- Command: `python3 tools/bench.py score-all bench --json-out /tmp/xunji-bench-current.json`
- Result: 10/10 fixtures clean; detection 10/10; calibration 10/10; false positives 0; closure 1/1 correct.

## Notes

- Closure now warns when `state/conflicts.json` contains unresolved conflicts.
- Closure hard-fails when unresolved conflicts coexist with confirmed `Severity: HIGH` or `Severity: CRITICAL` findings.
- The gate reads conflict state as a projection; Markdown evidence remains canonical.
- Claude Code review recommended distinguishing malformed projection JSON from true unresolved conflicts; bad `state/conflicts.json` now emits a projection warning and does not masquerade as a conflict hard fail.
