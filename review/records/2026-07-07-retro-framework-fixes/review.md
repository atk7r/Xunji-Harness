# Verification Evidence

Commands run after the final patch set:

- `python3 tools/probe.py --selftest` PASS
- `python3 tools/check_templates.py` PASS
- `python3 tools/check_run.py runs/oppo_20260707_20260707` PASS
- `python3 tools/check_knowledge.py` PASS (`40 file(s)`)
- `python3 tools/selftest_all.py --only probe,check_templates,check_run,check_knowledge,coverage_matrix,workers,replay,run_gate,check_hook` PASS (`9 passed, 0 failed`)
- `python3 tools/selftest_all.py` PASS (`45 passed, 0 failed`)
- Earlier focused checks also passed for `check_run --selftest`, `check_knowledge --selftest`, `coverage_matrix --selftest`, and `workers --selftest`.

Artifacted command outputs:

- `evidence/selftest_all.txt`
- `evidence/check_run.txt`
- `evidence/check_knowledge.txt`
- `evidence/check_templates.txt`
- `evidence/git_diff_stat.txt`

Live replay note:

- `python3 tools/replay.py runs/oppo_20260707_20260707` was intentionally interrupted after the guard warned that `connect-origin-2877ec-in.oppo.com` had received 90 requests. The run's ordinary structural gate passes, and local replay selftests pass; full live replay was not continued to avoid turning maintenance verification into excess target traffic.

Scope note:

- `runs/oppo_20260707_20260707/` remains gitignored and is not part of the commit. The committed diff covers reusable framework/tooling/template fixes and the review record. The run directory has local ignored updates that make `check_run` pass.
