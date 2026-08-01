# Arkcli Manual Review Scope

This is a compact, frozen review scope for the Xunji Claude Code statusline maintenance diff.

## Author And Review Need

- Author: Codex.
- Required independent review: arkcli + Claude Code where available.
- Reason for this compact scope: `peer_review.py` fourth round completed Claude Code review but arkcli panel failed across all arkcli models. This file is a smaller arkcli review input to obtain a direct arkcli vote without the large generated bundle.

## Final Diff Stat

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

## Intended Behavior

- `.claude/settings.json` defines Claude Code `statusLine` for this project only:
  `XUNJI_COLOR=1 python3 "$CLAUDE_PROJECT_DIR/tools/xunji_statusline.py"`
- `tools/xunji_statusline.py` renders one concise Chinese line:
  `[Xunji-status] [Hunter｜验证] <run> | 待验证入口 N 个 | 子任务 ... | 无阻断 | 下一步 ...`
- Normal statusline rendering is read-only. It reads `.claude/xunji_active_run`, derived `state/*.json`, and `state/loop_journal.jsonl`.
- Mutation is limited to explicit maintenance commands `--set-active` and `--clear-active`.
- It returns an empty line outside this Xunji repository.
- Active run pointer paths are accepted only if the resolved run directory is under the repository root and has run markers.
- Active pointer writes use a unique temp file and atomic replace.
- `loop_bootstrap.py` sets the active pointer on new/resume; the fixed `/loop` template sets it at explicit loop start.
- This does not make normal chat a loop and does not replace Chinese phase boxes, `loop_journal.py`, hooks, guard layer, evidence gates, or closure rules.

## Evidence Artifacts To Inspect

- `evidence/patches/tools__xunji_statusline_py.patch.txt`
- `evidence/patches/tools__loop_bootstrap_py.patch.txt`
- `evidence/patches/_claude__settings_json.patch.txt`
- `evidence/patches/docs__templates__loop_prompt_md.patch.txt`
- `evidence/patches/_gitignore.patch.txt`
- `evidence/test-log.txt`
- `evidence/official-docs/claude-code-statusline-excerpt.txt`
- `evidence/official-docs/claude-code-settings-excerpt.txt`
- `review.md`
- `review_result.json`
- `reruns/review-round1-warn.md`
- `reruns/review-round2-warn.md`
- `reruns/review-round3-blocker.md`

## Test Results

The latest `evidence/test-log.txt` records exit 0 for:

- `python3 -m py_compile tools/xunji_statusline.py tools/loop_bootstrap.py tools/selftest_all.py`
- `python3 -m json.tool .claude/settings.json`
- `python3 tools/xunji_statusline.py --selftest`
- `python3 tools/loop_bootstrap.py --selftest`
- `python3 tools/selftest_all.py --only xunji_statusline,loop_bootstrap,status_style,loop_journal,loop_state,run_controller,check_templates`
- `python3 tools/check_rules.py`
- `python3 tools/check_templates.py`
- `git diff --check`

Important selftest lines include:

```text
ok   XUNJI_COLOR command path has ansi
ok   unknown phase fallback is styled
ok   normal render is read-only
ok   invalid outside run pointer is rejected
ok   cmd_resume real set-active renders selected run
```

## Prior Review Disposition

- Round 1 WARN: missing explicit `XUNJI_COLOR=1` command-path test and weak evidence controls. Addressed.
- Round 2 WARN: bootstrap call sites not integration-tested; Claude Code proprietary renderer not fully emulated. Addressed where local tests can: `cmd_new`, `cmd_resume`, and real resume render path now covered.
- Round 3 BLOCKER: E-006 official-doc evidence was confirmed but only cited URLs. Addressed by adding local official-doc excerpt artifacts.
- Round 4 NEEDS_DRIVER: Claude Code review completed with only WARN/context notes; arkcli panel failed completely due arkcli model timeout/parse failures. This manual arkcli review is the follow-up.

## Review Questions

Please review for commit-blocking issues only:

- Is there any code path where normal statusline rendering writes evidence, refreshes loop state, or drives the engagement?
- Is project-only activation correctly enforced?
- Does the change accidentally make normal Claude Code chat enter `/loop`?
- Are active-run pointer updates sufficiently safe for display-only state?
- Are tests enough to prevent likely regressions for this statusline feature?
- Are the remaining limitations acceptable as WARN rather than BLOCKER?

Return:

```text
## Verdict: PASS | WARN | BLOCKER
## Findings
- [BLOCKER|WARN] <claim> | Evidence: <file/path> | Why: <reason>
```
