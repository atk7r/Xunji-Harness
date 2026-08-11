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

## Contract Schema Publication

`contracts/*.schema.json` is live control-plane source. Never publish one through
incremental Edit/Write on the final path: a concurrent Hook could observe the
temporary invalid bytes. The registered local-read index for this tool is:

```bash
python3 tools/contract_schema.py --help
```

For an existing or new `<name.schema.json>`, use this exact maintenance workflow:

```bash
python3 tools/contract_schema.py prepare <name.schema.json>
```

This command remains the repair entrypoint when the published file already
exists but cannot load: it returns `status=prepared_repair`, copies the exact
malformed bytes into the CAS-bound candidate, and reports `target_diagnostic`.
Repair only the candidate; do not patch the live schema path in place.

Edit only the exact candidate printed by that command,
`tmp/contract_schema_candidates/<name.schema.json>`, using a structured Edit/Write
tool. Then run the exact `next_argv` from the prepare result:

```bash
python3 tools/contract_schema.py publish <name.schema.json>
```

`publish` validates strict UTF-8/JSON, the Draft 2020-12 declaration and `$id`,
preloads every other published schema, checks the frozen base with CAS, and uses
file/directory fsync plus atomic replacement. A failed validation or CAS does not
partially publish the candidate; a post-replace validation failure rolls the target
back. `status=unchanged` and exact replay are idempotent. Run the returned
`verification_argv` before handoff.

If the candidate is intentionally abandoned, remove only its ignored candidate
and base pair with:

```bash
python3 tools/contract_schema.py discard <name.schema.json>
```

On `SCHEMA_CANDIDATE_STALE` or `SCHEMA_PUBLISH_CAS_MISMATCH`, preserve the
candidate for inspection. Discard and prepare again only when intentionally
starting from the new published base; never repair the final schema path directly
or use `python -c` as a publication bypass. Loader failures retain a stable cause:
`SCHEMA_NOT_FOUND`, `SCHEMA_UTF8_INVALID`, `SCHEMA_JSON_INVALID`,
`SCHEMA_READ_FAILED`, or `SCHEMA_INVALID`. Diagnose them with the exact selftest:

```bash
python3 tools/contract_schema.py --selftest
```

If an active-run Hook encounters that typed fault outside a maintenance turn,
it stays fail-closed and prints the exact `prepare <name.schema.json>` recovery
argv. Start a separate framework-maintenance turn for that command; do not mix
schema publication with live-run progression in one authority mode.

## Check Selection

For docs/templates/skills, run skill or template validators when applicable.

For lifecycle or run-gate tooling, prefer one registered aggregate:

```bash
python3 tools/selftest_all.py --only check_run,setup_run,session_handoff,anti_drift
```

For repository architecture and hook behavior:

```bash
python3 tools/contract_schema.py --selftest
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
