---
name: xunji-local-maintenance
description: Codex-side Xunji repository maintenance guide. Use when Codex is writing or fixing project code, docs, templates, tools, tests, skills, local hygiene, or review notes; choosing selftests; handling dirty worktrees; checking architecture drift; or preparing Codex-authored maintenance changes for independent review without acting as the live project-running driver.
---

# Xunji Local Maintenance

Use this skill for Codex-side repository work. Codex may write and fix project
code, docs, tests, templates, and skills. Codex does not run live engagements as
the Root driver.

## Worktree Discipline

- Inspect dirty state before editing.
- Do not revert unrelated user changes.
- Keep changes scoped to the requested component.
- Prefer existing tools and patterns.
- Do not create a parallel Codex hook/runtime boundary.

## Routing

- Use this skill for ordinary repository edits and selftest selection.
- Use `xunji-sentinel-guard-review` for `.claude/hooks/`,
  `tools/harness/guard.py`, or `sentinel/` behavior changes.
- Use `xunji-peer-review-panel` when Codex-authored maintenance needs external
  review. Codex does not count as independent reviewer of its own diff.
- Use the more specific Xunji skill when working on setup, replay, benchmark,
  knowledge, Agent Board, or web research behavior.

## Commands

```bash
git status --short
python tools/check_rules.py
python tools/check_hook.py
python tools/selftest_all.py --list
python tools/selftest_all.py --only <suite1,suite2>
```

For Codex-authored maintenance review:

```bash
python tools/peer_review.py <scope> --driver codex --out review/records/<date>-<topic>.md
```

## Report Back

Summarize changed files, tests run, tests not run, review status, and residual
risk. Mention pre-existing dirty files only when they affect the task.
