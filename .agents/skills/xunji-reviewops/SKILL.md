---
name: xunji-reviewops
description: ReviewOps discipline for Xunji autonomous runs. Use when reviewing run evidence, resolving peer_review PR ledger items, judging Codex/heterogeneous review findings, closing reports, handling check_run failures, replay/artifact QA, or declaring safety-critical changes to .claude/hooks/, tools/harness/guard.py, or sentinel/ done. Protects autonomous AI closure from self-deception without adding exploit playbooks.
---

# Xunji ReviewOps

## Overview

This is the review and closure discipline layer for Xunji. It protects autonomous
drive by forcing evidence-bound adjudication at the points where an agent is most
likely to rationalize: review findings, report inclusion, closure, replay drift,
and safety-critical framework changes.

It is not a process script and not a vulnerability checklist. Keep the driver
autonomous: use the gates below to decide what is true, what must be reopened,
and what can be closed.

## Core Posture

- Treat review output as a high-signal challenge, not as final truth. Codex,
  peer_review, and subagents produce candidates; the Single Synthesizer owns
  promotion, downgrade, dedupe, report inclusion, and closure.
- Prefer disagreement when the evidence requires it. If the operator, reviewer,
  report, or prior decision contradicts artifacts, state the contradiction and
  reopen or downgrade.
- Keep every ReviewOps decision attributable in the run record. Chat confidence is
  not evidence; cite E-ids, artifacts, controls, hashes, file paths, or reviewer
  records.
- Do not convert this skill into a checklist scanner. It governs evidence posture
  and closure integrity only.

## Review Triggers

Run a ReviewOps pass when any of these are true:

- The run is summarizing, claiming closure, or preparing `report.md`.
- `tools/check_run.py runs/<dir>` reports hard gates or meaningful warnings.
- `review.md` contains `## Review Finding Ledger` with pending PR items.
- Evidence, report text, replay status, or artifacts changed after a review.
- A HIGH/CRITICAL or `certainty >= 0.8` item needs independent severity support.
- A change alters behavior under `.claude/hooks/`, `tools/harness/guard.py`, or
  `sentinel/`.

## Run Review Loop

Before final report or closure, and every 3-5 Root/Hunter cycles during a rich
run:

1. Read the current run state: `frontier.md`, `hypotheses.md`, `evidence.md`,
   `false_positive.md`, `decisions.md`, `review.md`, `report.md`, and relevant
   artifacts.
2. Run `python tools/check_run.py runs/<dir>` from the repo root. Treat hard
   gates as next work, not paperwork.
3. If closure is being claimed and egress is accepted, prefer
   `python tools/peer_review.py runs/<dir> --into-run`. If an independent review
   already exists but evidence changed, rerun or record a fresh evidence-bound
   review because stale review hashes no longer certify the current run.
   Heterogeneous verdicts are challenges, not proof; accept them only when they
   cite current run artifacts or lead to a driver resolution that does.
4. If replay evidence is load-bearing or closure is near, run
   `python tools/check_run.py runs/<dir> --replay-verify` and re-adjudicate any
   `DIVERGED` evidence before relying on it.
5. Convert findings into action: reopen fronts, downgrade certainty, add
   controls/artifacts, update report scope, or write an evidence-backed
   resolution.

Passing `check_run` means the structure is present. It does not prove the report
is correct. Keep hunting if the evidence graph still exposes a live front.

## Codex Code-Maintenance Mode

This mode is only for repository maintenance, code changes, documentation changes,
tooling changes, and review of those diffs. It is not a live engagement runtime
and must not replace the Claude Code guard/hook boundary for target-facing work.

When Codex is the code-maintenance driver:

- Daily/live run work is still not Codex's runtime; do not use Codex or `.codex/`
  artifacts as proof that a live run was safe.
- Codex does not count as an independent reviewer of its own code change.
- Use `python tools/peer_review.py <scope> --driver codex` for Codex-driven code
  review. The reviewer votes are `arkcli panel` plus `Claude Code/API` when
  available; the synthesis brain remains Codex, which must adjudicate their
  findings through evidence, tests, diffs, and recorded rationale.
- If arkcli is unavailable, use Claude Code/API or a fresh-context Claude Code
  review as the external vote. If Claude is unavailable, use arkcli panel. If
  neither external reviewer is available, record that limitation and do not
  pretend Codex self-review is independent.
- For safety-critical behavior changes under `.claude/hooks/`,
  `tools/harness/guard.py`, or `sentinel/`, still run the required tests and
  record an independent review in `review/records/<date>-<topic>.md`.

## PR Ledger Closure

For each `PR-xxx` under `## Review Finding Ledger`:

- `BLOCKER` cannot remain `pending`, `open`, or `unresolved`.
- `WARN` should be resolved before closure unless the reason to defer is itself
  recorded.
- Accept reviewer claims only when they survive artifact and evidence checks.
- Dismiss reviewer claims only with a concrete alternate explanation, not with
  "reviewer is wrong" or "driver disagrees".
- Use the narrow resolver when available:
  `python tools/peer_review.py runs/<dir> --resolve PR-001 --status accepted --resolution "Evidence: E-007 and evidence/probe.replay.json confirm missing control; reopened F-003."`

Allowed statuses are `accepted`, `dismissed`, `superseded`, and `escalated`.
Every `DriverResolution` must cite the E-id, artifact, control, decision id, or
new front that makes the resolution auditable.

## Evidence And Report QA

Before promoting or reporting a finding, require:

- **Mechanism:** the artifact shows why the condition caused the response.
- **Control:** at least one control rules out the obvious alternate explanation.
- **Impact:** the capability reaches a meaningful unauthorized object,
  privilege, write path, assertion decision, upload path, relay, or secret-bearing
  boundary.
- **Artifact:** saved body, request/response pair, HAR, screenshot, replay JSON,
  or script output actually contains the cited evidence.
- **Report parity:** every confirmed `certainty >= 0.8` finding is either in
  `report.md` or explicitly excluded with an evidence-bound reason; report
  `Evidence IDs:` lists only entries that passed the evidence gate.

For HIGH/CRITICAL severity, preserve the Codex review fields required by the run
rules. For CRITICAL pause, require the extra critical review before pausing.

## Closure Discipline

Do not declare FINAL, 收工, complete, or "explored enough" unless both are true:

- `python tools/check_run.py runs/<dir>` has no hard gates.
- `frontier.md` has zero open fronts, or every remaining front has an evidence-
  backed deferred/closed rationale that the review accepts.

If either fails, the next action is not closure. Continue autonomous work:
reopen, verify, gather a missing control, fix the ledger, or downgrade the claim.

## Safety-Critical Code Review

Use this path only for behavior changes to:

- `.claude/hooks/`
- `tools/harness/guard.py`
- `sentinel/`

Before declaring such a change done:

1. Run `python tools/selftest_all.py` or a justified focused subset plus the
   directly affected selftests.
2. Get an independent fresh-context review of the changed behavior, not a
   self-summary.
3. Record the findings and driver dispositions in
   `review/records/<date>-<topic>.md`.

This gate is narrow. Documentation, comments, pure refactors, test-only edits, or
unrelated files do not automatically need this path unless they alter what the
guard, hook, or sentinel layers allow, block, escalate, or measure.
If a change outside the listed paths is load-bearing for those layers, such as a
shared utility they import or a configuration they consume, treat it as in scope.

## What Not To Add

- Do not add generic exploit-technique lists such as IDOR, SQLi, XSS, Swagger,
  default credentials, or config leak methods.
- Do not replace the live run graph with a fixed checklist.
- Do not treat reviewer confidence, tool green status, or report prose as
  evidence.
- Do not use Codex or `.codex/` artifacts as proof that the live Claude Code
  engagement boundary was active.
