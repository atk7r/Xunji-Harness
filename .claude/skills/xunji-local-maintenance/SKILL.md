---
name: xunji-local-maintenance
description: Claude-driver local repository maintenance discipline for Xunji. Use when editing docs, templates, tools, skills, non-live-run code, or project hygiene; when choosing selftests; when avoiding unrelated dirty worktree changes; or when ensuring architecture drift checks and independent review requirements are satisfied for repository changes.
---

# Xunji Local Maintenance

Use this skill for repository maintenance outside a live target action: docs,
templates, tools, skills, checks, and local hygiene. It keeps project work scoped
and testable.

## Overlap Routing

- Use this skill for repository edits, hygiene, test selection, and worktree
  discipline.
- Use `xunji-run-lifecycle` when the work is about an active run's setup,
  handoff, check, or closure state.
- Use `xunji-reviewops` when resolving reviewer findings, report issues,
  peer-review ledgers, or evidence-quality disputes.
- Use `xunji-sentinel-guard-review` for `.claude/hooks/`,
  `tools/harness/privacy.py`, `tools/harness/command_shape.py`,
  `tools/setup_transaction.py`, `tools/harness/guard.py`, or `sentinel/`
  behavior changes.
- Use `xunji-benchmark-eval` for bench fixture scoring or A/B metric comparison.

## Worktree Discipline

- Inspect current dirty state before editing.
- Do not revert unrelated user changes.
- Keep edits scoped to the requested file family.
- Use existing project patterns and tools before adding new abstractions.
- Do not create a parallel runtime or hook boundary.

## Check Selection

For docs/templates/skills, run skill or template validators when applicable.

For lifecycle or run-gate tooling, prefer one registered aggregate:

```bash
python3 tools/selftest_all.py --only check_run,setup_run,session_handoff,anti_drift
```

For repository architecture and hook behavior:

```bash
python3 tools/check_rules.py
python3 tools/check_hook.py
```

For a broad local scorecard:

```bash
python3 tools/selftest_all.py
python3 tools/selftest_all.py --only <suite1,suite2>
python3 tools/selftest_all.py --list
```

## Safety-Critical Changes

For any safety-critical boundary change, load `xunji-sentinel-guard-review`; it
owns the authoritative path set, focused checks, mandatory full aggregate, and
fresh independent-review gate. Green selftests are the floor, not proof that the
design is right.

## Reporting Back

Report changed files, tests run, failures not run, and residual risk. If a test
failure is unrelated, say why and preserve the evidence instead of hiding it.
