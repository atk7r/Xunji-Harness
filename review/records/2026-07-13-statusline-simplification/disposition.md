# Statusline Simplification Review Disposition

## Scope

Codex-authored maintenance change for `tools/xunji_statusline.py`, Claude-primary
instructions, and shared lifecycle/setup documentation.

## Accepted and fixed

- Round 1: isolated selftests from the operator's real active-run pointer.
- Round 1: added explicit Setup, cached Reviewer, Paused, Interrupted, and fallback
  phase coverage.
- Round 1: synchronized `CLAUDE.md` with the new statusline contract.
- Round 2: populated legacy controller, assignment, and asset state in the fixture
  and proved it cannot leak extra fields.
- Round 2: split code and documentation diffs so reviewers can read every assertion
  within the artifact excerpt cap.
- Round 3: inspected the installed Claude Code v2.1.201 payload constructor and
  recorded its unconditional `workspace.current_dir` contract.
- Round 3: added missing/blank workspace, cwd-only, and nested-workspace tests.
- Round 4: restored an isolated stdin-to-CLI-to-stdout ANSI integration test.
- Round 4: added before/after fingerprints for both the real active pointer and the
  real active run's turn contract.
- Round 4: documented the correct manual stdin simulation command.

## Deliberately not adopted

- Restoring `PWD`, `os.getcwd()`, or top-level `cwd` fallback: rejected because the
  operator explicitly requires empty output until a workspace is specified. The
  installed Claude Code payload supplies `workspace.current_dir` directly.
- Restoring controller, Agent, asset, blocker, cache-health, or next-action suffixes:
  rejected because the requested persistent format is exactly status tag, phase,
  and run name. Detailed health remains in phase banners, journals, and checks.

## Final independent-review status

The acceptance panel ran arkcli plus fresh Claude review. Completed Kimi and Claude
reviewers found no new substantive implementation issue. The remaining panel WARN
is a documented limitation: `glm-5.2` returned output that the review parser could
not parse. It is not represented as an independent PASS vote.

Final verification: `python3 tools/check_rules.py` passed; the focused statusline,
setup, and loop-bootstrap suites passed; `python3 tools/selftest_all.py` passed all
60 suites with 0 failures.
