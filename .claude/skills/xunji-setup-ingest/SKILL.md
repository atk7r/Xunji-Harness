---
name: xunji-setup-ingest
description: Claude-driver setup and recon ingestion discipline for Xunji runs. Use when creating a run directory, ingesting Guanlan/recon JSON, deriving scope, building `coverage.json`, reviewing `surface_recon.md`, handling `--classify`, assigning threat role/exposure, or preventing hand-curated asset subsets and anti-lump blind spots.
---

# Xunji Setup Ingest

Use this skill at the beginning of a run or when fixing a bad setup. It consumes
existing intelligence first and builds the asset ledger without re-OSINT by
default.

## Overlap Routing

- Use this skill for setup-time recon ingestion, scope derivation, coverage, and
  threat triage.
- Use `xunji-run-lifecycle` for resume, handoff, per-cycle checks, and closure
  sequencing after setup exists.
- Use `xunji-knowledge-flywheel` for interpreting `knowledge_hits.md` or seeding
  missing fingerprints.
- Use `xunji-reviewops` when coverage or anti-lump warnings become review
  findings or closure blockers.

## One-Shot Setup

```bash
python tools/setup_run.py <slug> [recon.json]
```

With recon, setup should:

- create the run skeleton from `docs/templates/run/`;
- record the recon path in `target.md`;
- derive default scope into `target.md` for review and correction;
- write `surface_recon.md` from the full recon asset table;
- build `classify/coverage.json` directly from Guanlan data with zero re-probe;
- write `knowledge_hits.md` when local signatures match.

`setup_run.py` prepares the workbench. It does not pick fronts, decide findings,
or attack the target.

## Scope And Coverage

- Review `target.md` after setup. Correct in-scope, out-of-scope, accounts,
  forbidden actions, and rate constraints before probing.
- Treat `coverage.json` as the anti-lump ledger: it says which assets exist and
  which reachable assets need a recorded verdict.
- Do not hand-copy a curated subset of hosts into `surface.md` as ground truth.
  That bakes driver selection bias into the run.
- Do not bulk-run `classify_hosts` just to rebuild Guanlan coverage.

Use active egress recheck only when authorized:

```bash
python tools/setup_run.py <slug> <recon.json> --classify
```

## Threat Triage

After setup, assign each distinct-app cluster in `frontier.md`:

- `Threat role`: `admin-mgmt`, `identity-auth`, `data-pii`, `transaction`,
  `content-cms`, `proxy-relay`, or `infra`.
- `Threat exposure`: `public-unauth`, `login-gated`, or `hardened`.

Clusters with different business roles must stay as independent fronts even if
they share IP ranges, naming patterns, CDN, or server headers.

## Checks

```bash
python tools/setup_run.py --selftest
python tools/classify_hosts.py --selftest
python tools/scope.py --selftest
python tools/check_run.py runs/<dir>
```

If setup was done manually and recon is cited but `coverage.json` is missing,
fix setup before closure claims.
