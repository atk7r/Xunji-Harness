# Statusline and Setup Output Final Review

Verdict: WARN
diff_fingerprint: 01eb049cc9f5c8d2
reviewed_diff: 01eb049cc9f5c8d2

## Scope

- `tools/xunji_statusline.py`: render nothing without an explicit Xunji
  workspace or active run; otherwise render only
  `[Xunji-status] [<phase>] <run>`.
- `tools/setup_run.py`: keep successful setup stdout/stderr silent while
  preserving Setup journal events, atomic active-run selection, explicit
  `--help`/`--selftest`, and stderr failure diagnostics.
- `tools/loop_bootstrap.py`: do not forward an empty/whitespace-only setup stdout
  as a blank line.
- Claude-primary lifecycle and environment documentation updated to match.

## Independent review

Codex authored and synthesized the maintenance change. Independent review used
the required Codex-authored matrix:

- arkcli panel and Claude Code review records:
  `review/records/2026-07-13-statusline-simplification/`
- Setup banner review and disposition:
  `review/records/2026-07-13-setup-banner-dedup/`
- Final success-silent review and disposition:
  `review/records/2026-07-13-setup-success-silent/`

The final panel verdict was WARN with no BLOCKER. Accepted warnings added
explicit `--help`, isolated `--classify`, active-run success-silence, and
failure-stderr regression checks. Remaining warnings were dismissed with
evidence in the corresponding `disposition.md` files or recorded as reviewer
context limitations.

## Verification

- Actual explicit-workspace statusline:
  `[Xunji-status] [Setup｜准备] sxtbu_20260713_20260713`
- Empty workspace payload: zero-byte output.
- `python3 tools/selftest_all.py`: 60 passed, 0 failed.
- `python3 tools/check_rules.py`: passed.
- `python3 tools/check_local_hygiene.py`: passed after staging.
- `git diff --cached --check`: passed after generated-review whitespace cleanup.

Residual WARN: independent reviewers consumed frozen review bundles rather than
executing the live repository. Codex verified the final staged implementation
and tests locally; this self-verification is synthesis evidence, not an
independent reviewer vote.
