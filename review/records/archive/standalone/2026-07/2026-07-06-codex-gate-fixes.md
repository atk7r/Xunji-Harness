# Independent Review - Codex gate fixes

- Time: 2026-07-05T23:54:03Z
- Driver: Codex code-maintenance mode
- Reviewer: arkcli +chat fresh-context review
- Scope:
  - `.claude/hooks/pre-commit`
  - `tools/setup_run.py`
  - `tools/check_run.py`
- Diff fingerprint: eeea145a99f3ae00

## Reviewer Verdict

The external review returned **WARN**. All actionable warnings were accepted and
fixed, or adjudicated with local evidence.

## Findings And Disposition

| Finding | Disposition |
|---|---|
| Pre-commit fingerprint flow was fragile and under-documented. | Fixed. The hook now exposes `--fingerprint`, warns on empty staged framework diffs, and prints the required stage-fingerprint-record-stage workflow. |
| Manual fallback review records could approve without binding to the reviewed diff. | Fixed. All accepted review records, including `manual-fallback-*`, must contain `Verdict: PASS/WARN` and a current `diff_fingerprint` / `reviewed_diff` value. |
| `setup_run.py` could claim coverage was ready when no target-derived coverage was created. | Fixed. No-recon setup now validates explicit targets, refuses placeholders/prose, checks actual `coverage.json` assets, and only prints the ready message when coverage exists. |
| The no-recon `target->coverage` label implied success even when derivation was skipped. | Fixed. The success label is only used when `_coverage_ready()` confirms a nonempty asset list. |
| `check_run.py` documented Type B evidence as mandatory but emitted only a warning. | Fixed. `blocked_type_b` closures without an `E-xxx` evidence id are now hard gate errors with selftest coverage. |
| Type B migration could break existing runs. | Checked. `rg -n "blocked_type_b" runs` found no current historical run entries using that status. |
| Review worried that diff fingerprint matching might compare bytes and text. | Adjudicated false positive. `_git()` uses `capture_output=True, text=True`, and the fingerprint path encodes text intentionally before hashing. |

## Verification

- `python3 .claude/hooks/pre-commit --fingerprint && python3 .claude/hooks/pre-commit` - passed with empty-diff warning.
- `python3 tools/setup_run.py --selftest` - passed.
- `python3 tools/check_run.py --selftest` - passed.
- `python3 tools/selftest_all.py --only check_run,setup_run,peer_review,check_hook,safety_gate,run_gate,output_gate` - 7/7 passed.
- `python3 tools/selftest_all.py` - 37/37 passed.
- `python3 tools/bench.py score-all bench --json-out /tmp/xunji-bench-current.json` - 11/11 fixtures clean.
- `python3 -m py_compile .claude/hooks/pre-commit tools/setup_run.py tools/check_run.py` - passed.
- `git diff --check` - passed; Git still warns about CRLF normalization on existing/touched files.

## Final Gate Note

This record binds to the staged framework diff fingerprint above.

## Verdict: WARN
