# Codex-authored Maintenance Diff Review Scope

- Review target: current uncommitted Xunji repository maintenance diff before commit.
- Author mode: Codex-authored maintenance; Codex self-review does not count as independent review.
- Required matrix: arkcli panel + Claude Code CLI when available.
- Requested by operator: submit all uncommitted changes after review, not just the latest one.
- Refreshed: 2026-07-08T14:25:42

## Change Intent

The diff consolidates Claude primary-driver lifecycle fixes:

1. Clarify Claude Code primary-driver boundaries and `/loop` entry semantics.
2. Replace generated per-run loop prompt behavior with a fixed `/loop runs/<dir>` protocol.
3. Add an append-only loop journal for interruption recovery and phase-start/phase-end markers.
4. Add Chinese operator-facing status panels with bracket tags and ANSI color fallback.
5. Refresh loop state/controller/bootstrap outputs so the operator can see current phase, blockers, and next required action.

## Prior Review Disposition

- Prior PR-001 BLOCKER: fixed. Persisted Markdown writers call `render_markdown(..., color=False)` in `tools/loop_state.py` and `tools/run_controller.py`; selftests force `XUNJI_COLOR=1` and assert no ANSI escapes persist in `state/loop_state.md` or `state/controller_diff.md`.
- Prior PR-002/PR-003 WARN: addressed. `tools/loop_journal.py` rejects ordinary directories and evidence-only directories; it now requires explicit Xunji Markdown marker files.
- Prior PR-004 WARN: addressed. `setup_run.py` prints and journals Setup phase-start only after `scaffold(run_dir)` succeeds.
- Prior PR-007/PR-009 WARN: addressed with selftests for Setup/Reviewer/Report phase inference and phase-end banner rendering.
- Prior PR-008 WARN: addressed by running full `python3 tools/selftest_all.py`, which passed 52/52 suites.
- Prior downstream-parser WARN: checked with a focused source scan; tool code writes/displays the Markdown but no tool consumer was found parsing the old English `loop_state.md`/`controller_diff.md` prose. Machine consumers should use JSON caches.
- Prior `/loop` end-to-end WARN remains a documented limitation: the proprietary Claude Code `/loop` slash command is not directly invokable from local Python tests; the fixed template protocol, bootstrap refresh, phase journal CLI, and no-per-run-prompt behavior are covered.
- arkcli backend parse/internal-error WARN remains a review-system limitation when model backends fail or return unparsable output; the verdict should be read with emitted backend notes.

## Patch Artifacts

Patch artifacts use `.patch.txt` so `peer_review.py` includes text excerpts in the review bundle. Artifact sizes and hashes are intentionally left to `review/review_bundle.json`.

- `.claude/skills/xunji-run-lifecycle/SKILL.md` -> `evidence/patches/_claude__skills__xunji-run-lifecycle__SKILL_md.patch.txt`
- `CLAUDE.md` -> `evidence/patches/CLAUDE_md.patch.txt`
- `docs/ROUTER.md` -> `evidence/patches/docs__ROUTER_md.patch.txt`
- `docs/WORKFLOW-reference.md` -> `evidence/patches/docs__WORKFLOW-reference_md.patch.txt`
- `docs/WORKFLOW.md` -> `evidence/patches/docs__WORKFLOW_md.patch.txt`
- `docs/templates/loop_prompt.md` -> `evidence/patches/docs__templates__loop_prompt_md.patch.txt`
- `tools/loop_bootstrap.py` -> `evidence/patches/tools__loop_bootstrap_py.patch.txt`
- `tools/loop_state.py` -> `evidence/patches/tools__loop_state_py.patch.txt`
- `tools/run_controller.py` -> `evidence/patches/tools__run_controller_py.patch.txt`
- `tools/selftest_all.py` -> `evidence/patches/tools__selftest_all_py.patch.txt`
- `tools/setup_run.py` -> `evidence/patches/tools__setup_run_py.patch.txt`
- `tools/loop_journal.py` (new) -> `evidence/patches/tools__loop_journal_py.patch.txt`
- `tools/status_style.py` (new) -> `evidence/patches/tools__status_style_py.patch.txt`

Test evidence: `evidence/test-log.txt`.
Consumer scan evidence: `evidence/consumer-scan.txt`.

## Review Questions

Please check for blockers before commit:

- Does any change accidentally make natural-language chat enter `/loop` automatically?
- Does any change generate per-run `loop_prompt.md` again or require copy/paste prompt flow?
- Are ANSI colors kept out of persisted Markdown files while terminal output can still be colored?
- Are `[标签]` visible without color support?
- Are phase names consistent with the five Router phases?
- Does the new journal remain derived and non-canonical, and is its write boundary reasonable?
- Do selftests cover the new status output enough to prevent silent regressions?
- Is any Codex-side `.agents/skills` tree incorrectly changed for Claude primary-driver behavior?

## Git Status

```text
 M .claude/skills/xunji-run-lifecycle/SKILL.md
 M CLAUDE.md
 M docs/ROUTER.md
 M docs/WORKFLOW-reference.md
 M docs/WORKFLOW.md
 M docs/templates/loop_prompt.md
 M tools/loop_bootstrap.py
 M tools/loop_state.py
 M tools/run_controller.py
 M tools/selftest_all.py
 M tools/setup_run.py
?? review/records/2026-07-08-phase-status-output-precommit-review/
?? tools/loop_journal.py
?? tools/status_style.py
```

## Diff Stat

```text
 .claude/skills/xunji-run-lifecycle/SKILL.md |  56 ++++++++-
 CLAUDE.md                                   |  16 +++
 docs/ROUTER.md                              |  49 ++++++++
 docs/WORKFLOW-reference.md                  |   9 +-
 docs/WORKFLOW.md                            |  24 ++++
 docs/templates/loop_prompt.md               | 106 ++++++++++++++++-
 tools/loop_bootstrap.py                     | 177 ++++++++++++++++++----------
 tools/loop_state.py                         | 159 +++++++++++++++++++++----
 tools/run_controller.py                     |  99 ++++++++++++++--
 tools/selftest_all.py                       |   2 +
 tools/setup_run.py                          |  33 ++++++
 11 files changed, 636 insertions(+), 94 deletions(-)
```

## Name Status

```text
M	.claude/skills/xunji-run-lifecycle/SKILL.md
M	CLAUDE.md
M	docs/ROUTER.md
M	docs/WORKFLOW-reference.md
M	docs/WORKFLOW.md
M	docs/templates/loop_prompt.md
M	tools/loop_bootstrap.py
M	tools/loop_state.py
M	tools/run_controller.py
M	tools/selftest_all.py
M	tools/setup_run.py
```
