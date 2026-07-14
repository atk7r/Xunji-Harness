---
name: xunji-setup-ingest
description: Codex-side Xunji setup ingestion maintenance guide. Use when Codex is writing or fixing project code, docs, tests, or review notes for `setup_run.py`, `ingest_recon.py`, `scope.py`, `classify_hosts.py`, Guanlan recon ingestion, `surface_recon.md`, `coverage.json`, scope derivation, threat triage setup, or anti-lump setup behavior without acting as the live run Root driver.
---

# Xunji Setup Ingest

Use this skill when maintaining setup and recon ingestion code or docs. Codex may
fix project issues here; Claude remains the live Root driver during real runs.

## Authority Boundary

- `setup_run.py` prepares a workbench. It must not choose fronts or make attack
  judgments.
- Recon ingestion should consume existing intelligence first and avoid re-OSINT
  by default.
- Coverage is an anti-lump ledger, not proof that assets are safe.
- Keep live authorization and scope decisions in `target.md`.

## Code And Docs To Read

- `tools/setup_run.py` for skeleton creation, recon recording, scope derivation,
  coverage adaptation, and knowledge hits.
- `tools/setup_transaction.py` for hidden staging, source/transaction receipts,
  atomic publish, active-pointer CAS, and prepared recovery.
- `tools/ingest_recon.py` for recon rendering and Guanlan-to-coverage mapping.
- `tools/scope.py` for in/out scope derivation and matching.
- `tools/classify_hosts.py` for optional current-egress recheck behavior.
- `docs/ROUTER.md`, `docs/WORKFLOW.md`, `docs/templates/run/target.md`,
  `docs/templates/run/surface.md`, and `docs/templates/run/frontier.md`.

## Invariants

- With recon, setup should ingest the full asset table into `surface_recon.md`.
- Invalid slug/date/URL, missing/damaged/unknown recon, or any ingest/coverage/
  ledger/journal/loop-state failure must leave the old pointer unchanged and no
  half-built formal run.
- Setup/bootstrap/resume/set-active must share `commit_activation_cas()`; adapters
  never write the pointer or accept hook claim contents.
- `coverage.json` should be built from Guanlan baseline with zero re-probe unless
  the user explicitly chooses current egress recheck.
- `--classify` is active probing and must stay opt-in.
- Manual curated subsets must not masquerade as the full surface.
- Threat role/exposure triage is a Root decision after setup, not a setup script
  conclusion.

## Commands

```bash
python tools/setup_run.py --selftest
python tools/setup_transaction.py --selftest
python tools/ingest_recon.py <recon.json>
python tools/classify_hosts.py --selftest
python tools/scope.py --selftest
python tools/check_run.py --selftest
python tools/selftest_all.py --only setup_transaction,setup_run,classify_hosts,scope,check_run
```

## Review Checklist

- Does the change preserve no-overwrite run directory behavior?
- Does a rename-complete CAS failure remain `prepared_not_active`, and does a
  pointer-before-receipt failure recover idempotently?
- Does `target.md` record recon path or `none` accurately?
- Does scope derivation label heuristic uncertainty without driving attack
  choices?
- Does coverage count all appropriate in-scope assets instead of a subset?
- Do closure gates still hard-fail cited recon without coverage?
