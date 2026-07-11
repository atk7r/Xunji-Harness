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
   In Claude Code live runs, the review matrix is: full setup uses Codex plus the
   arkcli panel, with Codex as the synthesis brain; no Codex uses the arkcli
   panel as both reviewer set and brain; no arkcli uses Codex; neither available
   leaves closure incomplete. A same-family pass can advise but is not an
   independent vote. The arkcli panel is Kimi-K2.7-Code + GLM-5.2 only.
4. If replay evidence is load-bearing or closure is near, run
   `python tools/check_run.py runs/<dir> --replay-verify` and re-adjudicate any
   `DIVERGED` evidence before relying on it.
5. Convert findings into action: reopen fronts, downgrade certainty, add
   controls/artifacts, update report scope, or write an evidence-backed
   resolution.

Passing `check_run` means the structure is present. It does not prove the report
is correct. Keep hunting if the evidence graph still exposes a live front.
The independent-review gate additionally requires the latest content-addressed
ReviewReceipt to match the current evidence index and a transcript-observed
foreground invocation with matching receipt and bundle-hash output markers.
Historical receipts remain audit history; only the latest
hash is freshness-bearing, while every unresolved historical BLOCKER still matters.

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

## Accepting Codex-Authored Diffs

This applies when Claude Code integrates repository code or documentation edits
authored by Codex. It is not a live engagement runtime change: target-facing work
still runs under Claude Code's guard/hook boundary.

Claude Code's responsibilities are acceptance-side only:

- Keep authorship attributable: Codex wrote the candidate diff; Claude Code owns
  integration, tests, and final acceptance.
- Do not count Codex as an independent reviewer of its own diff.
- Require a review record for high-risk code, report, closure-impacting, or
  safety-critical changes; reject or refresh stale/missing records.
- The record must name reviewers, note unavailable reviewer limitations, and tie
  dispositions to tests, diffs, artifacts, or rationale.
- The narrow safety-critical gate above still applies to `.claude/hooks/`,
  `tools/harness/guard.py`, and `sentinel/`: run the required tests and write the
  independent review record before declaring the change done.

The Codex-side author/review matrix belongs in `AGENTS.md`.

## What Not To Add

- Do not add generic exploit-technique lists such as IDOR, SQLi, XSS, Swagger,
  default credentials, or config leak methods.
- Do not replace the live run graph with a fixed checklist.
- Do not treat reviewer confidence, tool green status, or report prose as
  evidence.
- Do not use Codex or `.codex/` artifacts as proof that the live Claude Code
  engagement boundary was active.
