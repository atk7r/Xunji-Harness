# Bench Decision Gate Expansion

- Date: 2026-06-28
- Scope: `bench/`, `tools/bench.py`, `bench/README.md`
- Purpose: make measure-before-add executable before Metacog / worker / sensor changes.

## What Changed

- Fixture set expanded to 10 synthetic fixtures.
- Coverage now includes auth/IDOR, injection, upload/path, path traversal, and recorded closure.
- `bench.py` now reports detection rate, false positive rate, certainty calibration, request budget, time-to-first-evidence, and closure correctness.
- Added JSON output and `compare` for baseline-vs-change A/B records.

## Verification

Command:

```bash
python3 tools/bench.py score-all bench --json-out tmp/bench-current.json
python3 tools/bench.py compare tmp/bench-current.json tmp/bench-current.json
python3 tools/selftest_all.py --only bench
```

Observed result:

- Fixtures: 10/10 clean.
- Detection: 10/10, 100%.
- Calibration: 10/10, 100%.
- False positives: 0.
- Request budget: 20 recorded requests, 0 fixture over max.
- Time-to-first-evidence average: 1.922 seconds across event-backed fixtures.
- Closure correctness: 1/1.
- Bench selftest: pass.

## Decision

Adopt. This is a measurement-only change: it adds offline fixtures and scorer output, but does not alter driver workflow, evidence gates, sensors, or target-facing behavior.
