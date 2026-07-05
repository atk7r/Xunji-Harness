---
name: xunji-benchmark-eval
description: Claude-driver benchmark evaluation protocol for Xunji framework changes. Use when scoring completed fixture runs with `bench.py`, comparing baseline/change runs, editing `bench/`, interpreting detection/calibration/false-positive/budget/process/collaboration metrics, or making sure benchmarks measure the driver without driving real engagements.
---

# Xunji Benchmark Eval

Use this skill to measure framework changes after a run has completed. Benchmarks
measure the driver output; they never choose fronts, perform probes, or grade real
engagements as fixtures.

## Overlap Routing

- Use this skill only for fixture scoring, baseline/change comparison, and
  benchmark fixture hygiene.
- Use `xunji-local-maintenance` to edit the project or choose general selftests.
- Use `xunji-agent-board` when interpreting collaboration failures that require
  workflow changes.
- Use `xunji-reviewops` if benchmark output feeds a release or closure review.

## Boundary

- Use only benign known-vulnerability fixtures or recorded sample runs.
- Do not put real target findings, secrets, or engagement artifacts in `bench/`.
- Treat scores as regression signals, not final security judgment.
- A benchmark is useful before/after a framework change, especially for changes
  to Agent Board, evidence gates, knowledge matching, or closure behavior.

## Commands

Score one run:

```bash
python tools/bench.py score runs/<dir> bench/<fixture>/truth.json
```

Score all fixtures:

```bash
python tools/bench.py score-all bench/
python tools/bench.py score-all bench --json-out tmp/baseline.json
```

Compare before/after:

```bash
python tools/bench.py compare tmp/baseline.json tmp/change.json
```

Regression test:

```bash
python tools/bench.py --selftest
```

## Interpretation

- `detection`: expected confirmed findings found.
- `calibration`: matched findings reach the truth file's certainty floor.
- `false-pos`: traps wrongly confirmed.
- `budget`: lower-bound request count from replay artifacts.
- `process`: whether expected capabilities left traces in run files.
- `collaboration`: Agent Board coverage, conflict resolution, and candidate to
  finding discipline when the fixture declares those expectations.

If a framework change improves prose but hurts calibration, false positives, or
coverage, treat that as a regression until explained.

## Fixture Hygiene

When adding fixtures, include `truth.json`, expected markers, any
`must_not_flag` traps, and process/collaboration expectations that are stable
enough to measure. Prefer robust capability traces over brittle wording.
