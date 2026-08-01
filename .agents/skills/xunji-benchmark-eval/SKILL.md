---
name: xunji-benchmark-eval
description: Codex-side Xunji benchmark evaluation maintenance guide. Use when Codex is writing or fixing project code, docs, fixtures, tests, or review notes for `tools/bench.py`, `bench/`, truth fixtures, baseline/change comparisons, detection/calibration/false-positive/budget/process/collaboration metrics, or benchmark regression behavior without letting benchmarks drive live engagements.
---

# Xunji Benchmark Eval

Use this skill when maintaining the benchmark harness or interpreting benchmark
results for project changes. Benchmarks measure completed fixture runs; they do
not drive real engagements.

## Boundary

- Fixtures must be benign known-vulnerability targets or recorded sample runs.
- Real engagement findings, secrets, and live target artifacts do not belong in
  `bench/`.
- Scores are regression signals, not final security truth.
- Do not change the framework just to satisfy brittle fixture wording.

## Code And Docs To Read

- `tools/bench.py` for metric definitions and scoring behavior.
- `bench/README.md` for fixture schema and A/B workflow.
- `tools/evidence_parse.py` when detection/calibration changes touch evidence
  parsing.
- `xunji-agent-board` if collaboration metrics are involved.
- `xunji-local-maintenance` for general repo edit discipline.

## Commands

```bash
python tools/bench.py --selftest
python tools/bench.py score runs/<dir> bench/<fixture>/truth.json
python tools/bench.py score-all bench/
python tools/bench.py compare tmp/baseline.json tmp/change.json
python tools/selftest_all.py --only bench
```

## Review Checklist

- Are marker matches robust and not overfit to prose?
- Does calibration require the fixture certainty floor?
- Are false-positive traps explicit?
- Do process/collaboration checks measure stable capability traces?
- Does the change keep benchmark code read-only against target systems?
