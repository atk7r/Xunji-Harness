# Codex-Authored Maintenance Diff Review Scope

- Review target: current uncommitted Xunji repository maintenance diff before commit.
- Author mode: Codex-authored maintenance; Codex self-review does not count as independent review.
- Required matrix: arkcli panel + Claude Code CLI when available.
- Requested by operator: implement the statusline, review it, and commit it.
- Refreshed: 2026-07-08.

## Change Intent

The diff adds a Claude Code project statusline for Xunji:

1. Configure `.claude/settings.json` to run a project-local statusline command every 2 seconds.
2. Add `tools/xunji_statusline.py`, a read-only renderer that returns no output outside the Xunji checkout.
3. Track the active run through local `.claude/xunji_active_run`, ignored by Git.
4. Update `loop_bootstrap.py` and the fixed `/loop` template so new, resumed, and explicit loop runs set the active pointer.
5. Document that the statusline does not replace Chinese phase boxes, `loop_journal.py`, hooks, or evidence gates.
6. Add statusline selftest coverage and include it in `tools/selftest_all.py`.

## First Review Disposition

Independent review rounds:

- Round 1 returned WARN, not BLOCKER.
- Round 2 returned WARN, not BLOCKER.
- Round 3 returned BLOCKER because E-006 cited official docs URLs without local artifacts; fixed by adding `evidence/official-docs/*-excerpt.txt`.
- Round 4 returned NEEDS_DRIVER because Claude Code review completed but arkcli panel failed across all arkcli models; a compact manual arkcli review scope is recorded under `review/arkcli-manual-scope.md`.
- Manual arkcli retry was blocked by expired Volc SSO credentials; see `review/arkcli-auth-blocker.md`.

The follow-up diff addresses actionable warnings by:

- adding a selftest for the real `XUNJI_COLOR=1` command path;
- adding checks for unknown-phase color fallback, invalid outside run pointers, and read-only render mtimes;
- making active-run pointer writes atomic with `Path.replace()`;
- adding a bootstrap selftest that exercises the `cmd_new` and `cmd_resume` active-run hook call sites;
- adding a real `cmd_resume` -> active pointer -> rendered statusline selftest;
- clarifying maintenance evidence controls and adding the `tools/selftest_all.py` patch artifact to E-005.

## External Schema Check

The Claude Code statusline/settings shape was checked against official docs on
2026-07-08:

- https://code.claude.com/docs/en/statusline
- https://code.claude.com/docs/en/settings

Those docs describe a project/user `statusLine` settings key for command-backed
statuslines, with `command`, `refreshInterval`, `padding`, and stdin JSON that
includes the workspace current directory context.

## Expected Operator View

```text
[Xunji-status] [Hunter｜验证] scshr_20260709 | 待验证入口 6 个 | 子任务 2 个进行中 | 无阻断 | 下一步 F-004 接口枚举
```

This intentionally avoids cryptic counters like `F 6/1/3 E 4/0 B 0`.

## Review Questions

- Does the statusline really stay display-only during normal Claude Code refresh?
- Does it return no output outside this Xunji project?
- Does it avoid turning ordinary chat into `/loop`?
- Does the active-run pointer update on both bootstrap/resume and explicit `/loop` entry?
- Does the project setting follow Claude Code statusline shape and avoid global activation?
- Are subagent states aggregated without making the line unreadable?
- Are remaining limitations clearly documented, especially that local tests cannot fully emulate Claude Code's proprietary renderer?

## Diff Stat

```text
 .claude/settings.json                       |   6 +
 .claude/skills/xunji-run-lifecycle/SKILL.md |   6 +
 .gitignore                                  |   2 +
 CLAUDE.md                                   |   4 +
 docs/WORKFLOW.md                            |   9 +
 docs/templates/loop_prompt.md               |   1 +
 tools/loop_bootstrap.py                     |  77 ++++-
 tools/selftest_all.py                       |   1 +
 tools/xunji_statusline.py                   | 418 ++++++++++++++++++++++++++++
 9 files changed, 523 insertions(+), 1 deletion(-)
```

## Test Evidence

The focused test log is in `evidence/test-log.txt`. Commands covered:

- `python3 -m py_compile tools/xunji_statusline.py tools/loop_bootstrap.py tools/selftest_all.py`
- `python3 -m json.tool .claude/settings.json`
- `python3 tools/xunji_statusline.py --selftest`
- `python3 tools/loop_bootstrap.py --selftest`
- `python3 tools/selftest_all.py --only xunji_statusline,loop_bootstrap,status_style,loop_journal,loop_state,run_controller,check_templates`
- `python3 tools/check_rules.py`
- `python3 tools/check_templates.py`
- `git diff --check`
