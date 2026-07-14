---
name: xunji-run-lifecycle
description: Claude-driver guide for Xunji run lifecycle work. Use when starting, resuming, handing off, structurally checking, reviewing, or closing a Xunji run, including `setup_run.py`, run templates, `check_run.py`, `session_handoff.py`, `anti_drift.py`, `retrospective.md`, `hints.md`, coverage, closure gates, and independent review through `peer_review.py`, Codex, arkcli, or a heterogeneous reviewer panel when applicable.
---

# Xunji Run Lifecycle

Use this skill for the mechanical lifecycle of a live Xunji run: create the
workbench, keep state recoverable, absorb operator steering, check gates, hand off
between sessions, and close only when the run files support it.

## Driver Boundary

- Act as the live Root driver for the run. Use delegated help when useful, but
  keep decisions attributable in the run.
- Codex, arkcli, `peer_review.py`, heterogeneous review panels, and sub-agents
  are tools/reviewers used under this driver. They do not become the Root, bypass
  `.claude/hooks/`, or turn reviewer confidence into evidence.
- The source of truth is `runs/<target>/`, not chat. Markdown run files carry
  decisions and evidence; derived JSON only helps query that state.
- The `.claude/hooks/` and guard boundary remains authoritative. Do not weaken it
  with a skill shortcut.
- Reviewer confidence is not evidence. Evidence IDs, saved artifacts, controls,
  and rationale decide what can close.

## Overlap Routing

- Use this skill for setup, resume, handoff, structural checks, hints, and
  closure readiness.
- Use `xunji-reviewops` for reviewer findings, PR ledgers, false-positive
  adjudication, report closure, and evidence-quality decisions.
- Use `xunji-agent-board` for sub-agent fan-out, assignments, context packs,
  merge-check, conflicts, and synthesis.
- Use `xunji-knowledge-flywheel` after a live fingerprint grounds a product hit
  or misses and needs writeback.
- When a cycle touches several areas, keep lifecycle state here and let the
  narrower skill govern the specialized judgment.

## Entry Routing

Classify the operator message before touching run state:

- Ordinary project questions or normal chat stay chat. Do not mutate a run and do
  not start `/loop`.
- Natural-language targets, URLs, markdown notes, or recon paths without `/loop`
  mean setup/preparation only. Create or identify the run when appropriate, but
  do not enter autonomous loop mode.
- Existing `runs/<dir>` plus continue/resume/previous intent means resume from
  files: read `session_handoff.md` when present, then the canonical Markdown
  files. Do not start `/loop` unless the operator explicitly wrote `/loop`.
- Operator leads, constraints, and priorities during an active run become
  `hints.md` entries before the next lifecycle decision. Leads are not evidence.
- Only an explicit `/loop` token enters loop mode. If `/loop` lacks a run path or
  setup inputs, ask for the missing run/target boundary instead of guessing.
- For `/loop runs/<dir>`, read the fixed protocol in `docs/templates/loop_prompt.md`
  and bind `{{RUN_DIR}}` to the provided run path. Do not require or regenerate a
  per-run `loop_prompt.md`.

When the message shape is ambiguous, use Claude Code's language understanding and
the run files to choose chat/setup/resume/hint. You may explain the chosen route
in `decisions.md` or `hints.md` when it affects a run. The binding invariant is:
natural language never starts loop by itself; `/loop` does.

## Phase Visibility

The run has five Router phases: `Setup`, `Root Orchestrator`, `Hunter`,
`Reviewer`, and `Report`. Every phase that is actually entered must have an
obvious Chinese, box-style operator-facing start marker and an obvious end
marker. Use `[标签]` as the no-color fallback and ANSI color when the terminal
supports it. Do not emit a marker for a phase you skipped.

When a run directory exists, use the loop journal marker so interruptions can
recover the open phase:

```bash
python tools/loop_journal.py runs/<dir> phase-start --phase "Root Orchestrator" --note "why this phase starts"
python tools/loop_journal.py runs/<dir> phase-end --phase "Root Orchestrator" --note "result and next phase"
```

For mechanical `Setup`, `tools/setup_run.py` keeps a successful invocation
stdout-silent; the selected-run statusline is its visible state. Failures and
fail-closed setup diagnostics remain on stderr. For `/loop`, follow
`docs/templates/loop_prompt.md`: enter Root Orchestrator before
the state graph pass, Hunter before proof/verification/Agent action, Reviewer
before merge/evidence/closure checks, and Report only when report material is
being drafted or finalized. `Resume`, handoff, drift recovery, and closure gates
are lifecycle mechanics, not extra phases.

Operator-facing lifecycle output should be Chinese first and bracket-tagged.
Detailed phase banners may summarize front counts, evidence/coverage delta, stop
blockers, and next actions before raw state paths or JSON; the persistent
statusline is intentionally narrower.
`setup_run.py` keeps Setup start/end in the loop journal without printing normal
success progress. Explicit `--help` and `--selftest` output are diagnostics, not
normal setup progress.

Claude Code's project statusline is enabled for Xunji through
`.claude/settings.json` and `tools/xunji_statusline.py`. It should stay concise:
`[Xunji-status] [Hunter｜验证] <run>`. It prints nothing until Claude supplies an
explicit Xunji workspace and that workspace has an active run. Treat it as
read-only display. Outside mechanical Setup, it does not replace phase markers;
it never replaces `loop_journal.py` or PreToolUse enforcement.

## Setup

Create a new run in one shot:

```bash
python tools/setup_run.py <slug> <recon.json>
python tools/setup_run.py <slug> --target <http-or-https-url>
```

`setup_run.py` validates input and delegates the whole commit to
`tools/setup_transaction.py`: hidden same-filesystem staging, complete canonical
and initial derived state, source/prepared receipts, atomic rename, then
`commit_activation_cas()`. Setup, bootstrap, resume, set-active, and recovery are
adapters to that one pointer writer. A CAS failure is `prepared_not_active`; a
pointer-success/receipt-failure is recovered idempotently without a duplicate run.
This does not enter `/loop`, choose a front, or make any evidence/closure decision.
Never clear or Write/Edit the pointer directly. When `/loop` initially attempts CronCreate for
a requested new run, let the gate reject that premature schedule, run setup, then
CronList and CronCreate again with the new run directory name.

Use `--classify` only while creating a new run, and only when an authorized
current egress recheck is allowed. It is not an existing-run refresh mode:

```bash
python tools/setup_run.py <slug> <recon.json> --classify
```

Setup rules:

- Do not hand-curate `surface.md` from a human report. Ingest the full recon asset
  table so coverage and anti-lump checks can see the real surface.
- Treat `coverage.json` from Guanlan as the zero-reprobe baseline. Bulk
  `classify_hosts` is opt-in, not default setup.
- After setup, assign threat role and threat exposure for distinct-app clusters in
  `frontier.md`; same IP or hostname pattern is not enough to lump business roles.
- Ask the operator only for missing authorization, target, account, or boundary
  data.

## Resume

If a handoff exists, begin there:

```bash
python tools/session_handoff.py pickup runs/<dir>
```

Otherwise rebuild context from files:

```text
session_handoff.md -> target.md -> frontier.md -> decisions.md -> evidence.md -> review.md
```

Run a Root graph pass before selecting work:

```bash
python tools/graph.py runs/<dir>
python tools/workers.py status runs/<dir>
python tools/workers.py conflicts runs/<dir>
python tools/saturation.py runs/<dir>
python tools/coverage_matrix.py runs/<dir> --write --sync-coverage
```

`--sync-coverage` treats evidence/report host mentions as examination signals
only. It writes a coverage `verdict` only when the canonical frontier has a
terminal status, so prose cannot make unfinished work disappear from worker
suggestions or closure review.

Read `hints.md` every cycle when it exists. If the operator gives a directive,
constraint, or lead in chat, write or update `hints.md` before choosing the next
front. Leads are not facts; verify them through the evidence gate.

## Active Run Checks

Run structural checks at reviewer checkpoints and before report work:

```bash
python tools/check_run.py runs/<dir>
```

For loop/control-plane state, refresh the advisory caches:

```bash
python tools/loop_journal.py runs/<dir> status
python tools/loop_state.py runs/<dir> --write
python tools/progress_ledger.py runs/<dir> --write
python tools/run_controller.py runs/<dir> --shadow
```

Interpretation:

- Passing means the required structure is present, not that the work is correct.
- Warnings should either be fixed or explicitly resolved in run files.
- Blockers must be fixed before closure.
- If a local hook or `check_run` blocks, handle it in the same cycle: read the
  blocker, edit the canonical run file or tool issue that caused it, rerun the
  blocked command, and repeat until it passes or becomes a real external Type A
  blocker. Do not end the turn with "next action: fix gate" when the fix is
  local and executable now.
- A denied target action remains unresolved until the hook ledger contains a
  later successful receipt for the same tool and identical execution-relevant
  input. Descriptive tool metadata does not count. Do not turn a
  denial into a result, even by paraphrase. Retry after fixing the prerequisite;
  if that is impossible, use only the exact three-line denial envelope required
  by `output_gate.py`.
- `state/workflow_checkpoint.json`, `evidence.json`, `graph.json`,
  `state/loop_state.json`, `state/progress_ledger.json`, and
  `state/controller.shadow.json` are derived projections. `state/loop_journal.jsonl`
  is an append-only derived interruption journal. Never edit any of them as
  primary truth.
- `state/runtime_events.jsonl`, `state/turn_contract.json`, and
  `state/run_status.json` are hook-owned process records. Never edit them directly.
- `EXPLAIN_ONLY` is read-only and has no Coda. `PAUSED_BY_OPERATOR` keeps active
  fronts intact, stops the current run task through bound CronList/Delete/List,
  and is not a completion action. A later execute/resume prompt starts a new turn.
- Coda convergence means the current trajectory needs review, pivot, or Agent
  variance. It is not a Completion pause while open fronts, Type A barriers,
  coverage gaps, saturation gaps, or unresolved review/Agent conflicts remain.

Keep artifacts in their lanes: proof under `evidence/`, PoC/helper scripts under
`scripts/`, coverage under `classify/`, and only core Markdown plus derived indexes
in the run root.

## Closure

Before final report, explored-enough, or `GHOST_COMPLETE`:

```bash
python tools/check_run.py runs/<dir>
python tools/check_run.py runs/<dir> --replay-verify
```

Record or obtain the required independent review according to `xunji-reviewops`
and the run's data-egress boundary. When egress is accepted, use the normal
Claude-driver review paths:

```bash
python tools/peer_review.py runs/<dir> --into-run
python tools/check_run.py runs/<dir>
```

Closure gates:

- `review.md` must contain a current content-addressed `ReviewReceipt` generated
  by a transcript-observed foreground peer-review invocation whose output has
  matching receipt and bundle-hash markers. A heading, copied
  output, manual reviewer prose, or untouched template does not count.
- Resolve `PR-xxx` review ledger blockers before closure.
- `retrospective.md` must honestly fill the Self problems and Framework/tooling
  problems sections. Every Framework/tooling lesson needs its own repair status
  such as `- Status: fixed|open|deferred`; fixed items also need `Fixed by` +
  `Verification`, and open/deferred items need `Residual risk`. One section-wide
  status cannot close multiple lessons.
- `report.md` may list only finding-maturity evidence in `Evidence IDs:`.
- Confirmed entries need the canonical certainty scale, saved artifacts, and
  Replicated or Control rationale.
- If `target.md` cites recon, `coverage.json` must exist, reachable assets must be
  named, and high-value/login surfaces cannot be silently lumped away.
- `retrospective.md` `Status:` / `Verdict:` values such as `FINAL` are closure
  signals: they activate closure gates, but they are not completion actions.
- `GHOST_COMPLETE` is written only after check_run hard gates pass, independent
  review is resolved, retrospective is filled, and the report is final.
- Before the marker, invoke a completion Agent with
  `XUNJI_COMPLETION_REVIEW EVIDENCE_INDEX=<current evidence_index sha1>
  CHECKS=report_parity,severity_artifacts,reachable_frontier,review_ledger`.
  Require `XUNJI_COMPLETION_VERDICT=PASS`, the same hash, and all four checks in
  the response, then record substantive cross-check results in `decisions.md`.
- When writing `GHOST_COMPLETE` or `NORMAL_COMPLETE`, cancel any active scheduled
  `/loop` job in the same turn: current-turn CronList, delete only the observed
  current-run job, then CronList again. Append an `end` loop journal note containing
  `cron_cancelled=<job-id|none>`. `check_run.py` hard-fails a completion marker
  without that auditable cron disposition.

Probe chain note:

- For token/cookie flows, keep evidence inside `probe.py`: use
  `--preflight-get`, `--extract-csrf`, `--csrf-field`, `--cookie-jar`, and
  `--preflight-save` instead of hand-running curl outside the replay chain.

## Tool Selftests

After editing lifecycle tools or templates, run:

```bash
python tools/setup_run.py --selftest
python tools/setup_transaction.py --selftest
python tools/check_run.py --selftest
python tools/session_handoff.py --selftest
python tools/anti_drift.py --selftest
```

For shared gate or safety-adjacent changes, also run the relevant aggregate checks
and obtain the independent review required by `docs/WORKFLOW-reference.md`.
