# Bench Review: Ultra-native Agent Board

- Date: 2026-06-29
- Scope: selftest isolation fixes, minimal context pack, agent templates, and agent board commands in `tools/workers.py`.
- Command: `python3 tools/selftest_all.py`
- Result: 32 passed, 0 failed.
- Command: `python3 tools/bench.py score-all bench --json-out /tmp/xunji-bench-current.json`
- Result: 10/10 fixtures clean; detection 10/10; calibration 10/10; false positives 0; closure 1/1 correct.

## Notes

- `probe.selftest_isolation()` isolates local selftests from persistent guard state and gitignored engagement proxy config only during selftests.
- Runtime proxy fail-closed behavior remains unchanged and is covered by `tools/harness/proxy.py --selftest`.
- `context_pack.py` writes non-canonical context slices only; Markdown run files remain the canonical narrative.
- Context packs now include concise public knowledge pointers and local xday/weaponized pointers when the assigned front or matched coverage carries `kb:<id>` fingerprints; local weaponized note bodies are not dumped into the pack.
- `workers.py` preserves legacy `workers/` flow while adding `agents/`, `context/`, and `state/{assignments,conflicts,synthesis}.json` projections.
