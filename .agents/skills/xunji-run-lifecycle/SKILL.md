---
name: xunji-run-lifecycle
description: Codex-side guide for Xunji run lifecycle project work. Use when Codex is writing or fixing Xunji project code, auditing, advising on, or maintaining run setup, resume, handoff, structural checks, closure gates, retrospective requirements, run directory layout, `setup_run.py`, `check_run.py`, `session_handoff.py`, `anti_drift.py`, or template consistency without acting as the live project-running driver.
---

# Xunji Run Lifecycle

Use this skill for project-side work on the mechanical lifecycle of a Xunji run:
write or fix lifecycle code/docs, create a run workbench, resume from files,
check structural gates, prepare handoff, and review closure readiness. Do not use
it to choose exploit fronts, confirm findings, replace Claude Code hooks, or turn
Codex into the project-running driver.

## Authority Boundary

- Treat Claude Code as the live Root driver for running the project. Codex may
  write and fix project code, maintain docs/tools, audit behavior, reproduce
  issues, review, and disagree.
- Keep `runs/<target>/` as the source of truth. Chat memory, reviewer confidence,
  and generated graph files are not evidence.
- Do not recreate `.codex/hooks` or use Codex runtime files as safety evidence.
- For live attack decisions, hand back a recommendation with file/command
  citations; the Root records decisions in the run.

## Sources To Read

Read only the source needed for the lifecycle task:

- Setup or router questions: `docs/ROUTER.md`, `docs/WORKFLOW.md`, then
  `docs/WORKFLOW-reference.md` only for templates or closure detail.
- File fields: `docs/templates/run/*.md`.
- Tools: `tools/setup_run.py`, `tools/check_run.py`,
  `tools/session_handoff.py`, `tools/anti_drift.py`, `tools/graph.py`.
- Review gates: `xunji-reviewops` and `xunji-peer-review-panel`.
- Agent fan-out mechanics: `xunji-agent-board`.
- Knowledge hits or fingerprint writeback: `xunji-knowledge-flywheel`.

## Overlap Routing

- Use this skill for run setup, resume, handoff, structural checks, and closure
  readiness.
- Use `xunji-reviewops` to adjudicate review findings, peer-review ledgers,
  report closure, false-positive handling, or evidence quality.
- Use `xunji-agent-board` for multi-agent assignments, context packs,
  conflicts, synthesis, or candidate-only agent output.
- Use `xunji-knowledge-flywheel` for fingerprint-grounded knowledge retrieval or
  writeback.
- If a task touches multiple areas, load the narrow lifecycle facts here, then
  route the judgment to the more specific skill.

## Setup

Prefer the one-shot scaffold:

```bash
python tools/setup_run.py <slug> [recon.json]
```

Key invariants:

- `setup_run.py` prepares the workbench; it does not select fronts or make attack
  judgments.
- With Guanlan recon, it ingests the full asset table, records the recon path in
  `target.md`, derives default scope for review, builds `classify/coverage.json`
  with zero re-probe, and writes `knowledge_hits.md` when signatures match.
- Do not hand-curate a subset of assets into `surface.md` as ground truth.
- Use `--classify` only when a current egress recheck is authorized; it is active
  probing, not the default setup path.
- After setup, the Root still assigns threat role and threat exposure per
  distinct-app cluster in `frontier.md`.

## Resume And Handoff

To snapshot a run for the next session:

```bash
python tools/session_handoff.py write runs/<dir>
```

To produce a pickup prompt:

```bash
python tools/session_handoff.py pickup runs/<dir>
```

Resume from files, not prior chat. Start with `session_handoff.md` when present,
then read `target.md`, `frontier.md`, `decisions.md`, `evidence.md`, and
`review.md`. If `state/workflow_checkpoint.json` exists, treat it as a derived
projection; verify important facts against Markdown.

## Per-Cycle Structure Check

For an active run, recommend the cheap state pass before choosing work:

```bash
python tools/graph.py runs/<dir>
python tools/check_run.py runs/<dir>
```

`graph.py` writes derived state such as `state/workflow_checkpoint.json`.
`check_run.py` checks structure, evidence maturity, coverage health, hints,
pending review issues, layout drift at closure, and closure gates. Passing
`check_run.py` means required structure exists; it is not a quality certificate.

When the operator gives a directive, lead, or constraint, ensure `hints.md`
exists and the hint is recorded before the next lifecycle state decision. Pending
hints must not rot.

## Closure Readiness

Before any "done", "exhausted", final report, or ghost completion claim, verify:

```bash
python tools/check_run.py runs/<dir>
python tools/check_run.py runs/<dir> --replay-verify   # explicit, live GET replay only
```

Use `--auto-peer-review --review-driver codex` only when Codex authored or is
maintaining the repo-side change and external review is allowed:

```bash
python tools/check_run.py runs/<dir> --auto-peer-review --review-driver codex
```

Closure hard points to preserve:

- `review.md` needs an `Independent Review` record; self-review is not enough.
- Any `PR-xxx` blocker or unresolved review ledger item must be resolved.
- `retrospective.md` must contain real Self and Framework/tooling sections.
- Confirmed evidence needs finding maturity, allowed certainty scale, saved
  artifacts, and replicated/control rationale.
- If recon is cited, coverage must exist and reachable assets must be driven to
  recorded verdicts instead of lumped away.
- `GHOST_COMPLETE` belongs only after hard gates pass, independent review is
  resolved, and retrospective is written.

## Maintenance Checks

When editing lifecycle docs or tools, run the narrow checks first:

```bash
python tools/setup_run.py --selftest
python tools/check_run.py --selftest
python tools/session_handoff.py --selftest
python tools/anti_drift.py --selftest
```

Use broader checks when the change touches shared gates or review behavior:

```bash
python tools/selftest_all.py --only peer_review
python tools/selftest_all.py
```

For safety-critical changes under `.claude/hooks/`, `tools/harness/guard.py`, or
`sentinel/`, keep the independent-review requirement from
`docs/WORKFLOW-reference.md`; this skill does not waive it.
