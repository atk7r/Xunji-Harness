# Review Records Index

Updated: 2026-07-08

## Active Topic Directories

| Topic | Purpose | Notes |
|---|---|---|
| `2026-07-08-xunji-statusline-precommit-review/` | Precommit review for Claude Code project statusline. | Review bundle, patch evidence, test log, and final gate record live here after commit cleanup. |
| `2026-07-08-phase-status-output-precommit-review/` | Precommit review for visible loop phase/status panels. | Full bundle, final WARN review, patch evidence, test log, and the moved fingerprint gate record live here. |
| `2026-07-08-loop-controller-implementation-review/` | Loop controller / Coda / shadow-controller implementation review. | Earlier peer-review reruns and dispositions are under `reruns/`. |
| `2026-07-08-plan-implementation-review/` | Autonomous discovery optimization implementation review. | Final/rerun/disposition companions are under `reruns/`. |
| `2026-07-08-optimization-plan-review/` | Optimization plan review material. | Plan-level review bundle only. |
| `2026-07-07-loop-engineering-context/` | Loop engineering context and external panel records. | Arkcli/Claude/disposition companions are under `reruns/`. |
| `2026-07-07-personalized-rdt-subagents/` | Personalized RDT/subagent learning and boundary review. | Claude/arkcli/peer-review companions are under `reruns/`. |
| `2026-07-07-record-evidence-closure/` | `record_evidence.py` closure review. | Claude/peer-review/disposition companions are under `reruns/`. |
| `2026-07-07-retro-framework-fixes/` | Retrospective-driven framework fix review. | Arkcli/disposition companions are under `reruns/`. |
| `2026-07-07-network-proxy-closure-audit/` | Network-proxy skill closure audit. | Disposition companion is under `reruns/`. |

## Archives

| Path | Contents |
|---|---|
| `archive/standalone/2026-06/` | Older June one-file review records with no topic directory. |
| `archive/standalone/2026-07/` | Older July one-file review records with no topic directory. |

## Operating Rule

New substantial review work should create `review/records/<date>-<topic>/` and
put raw evidence inside that directory. Only keep a root-level gate record while
a staged framework diff needs `.claude/hooks/pre-commit` to find a current
`diff_fingerprint`; archive it into the topic directory after the gated commit
is complete.
