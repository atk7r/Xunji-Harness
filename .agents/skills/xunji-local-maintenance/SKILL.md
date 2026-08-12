---
name: xunji-local-maintenance
description: Codex-side Xunji repository maintenance guide. Use when Codex is writing or fixing project code, docs, templates, tools, tests, skills, local hygiene, or review notes; choosing selftests; handling dirty worktrees; checking architecture drift; when the operator asks for "复审" / review of a plan, diff, or maintenance change; or preparing Codex-authored maintenance changes for independent review without acting as the live project-running driver.
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
  `tools/setup_transaction.py`, `tools/harness/guard.py`, or `sentinel/` behavior changes.
- Use `xunji-peer-review-panel` when Codex-authored maintenance needs external
  review. Codex does not count as independent reviewer of its own diff.
- When the operator asks to "复审" / review a plan, diff, or maintenance change,
  use `xunji-peer-review-panel`; the author cannot satisfy review by rereading
  their own work. For Claude Code-authored targets, write the target paths, diff
  or plan, tests, and review questions to
  `review/records/<date>-<topic>-context.md`, then run Codex read-only through
  `tools/harness/codex_proxy.py` (which maps `CODEX_PROXY` / `codex_proxy.conf`
  into Codex CLI proxy env), for example
  `.venv/bin/python tools/harness/codex_proxy.py codex exec -s read-only < review/records/<date>-<topic>-context.md`.
  Save the Codex findings to `review/records/<date>-<topic>-codex-review.md`
  and record driver disposition under `review/records/`. For Codex-authored
  changes, Codex self-review still does not count; use the Codex-authored
  maintenance matrix in `xunji-peer-review-panel`.
- Use the more specific Xunji skill when working on setup, replay, benchmark,
  knowledge, Agent Board, or web research behavior.

## Commands

```bash
git status --short
.venv/bin/python tools/check_rules.py
.venv/bin/python tools/check_hook.py
.venv/bin/python tools/selftest_all.py --list
.venv/bin/python tools/selftest_all.py --only <suite1,suite2>
```

For Codex-authored maintenance review:

```bash
.venv/bin/python tools/peer_review.py <scope> --driver codex --out review/records/<date>-<topic>.md
```

## Report Back

Summarize changed files, tests run, tests not run, review status, and residual
risk. Mention pre-existing dirty files only when they affect the task.
