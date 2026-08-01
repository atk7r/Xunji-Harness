---
name: xunji-reviewops
description: Canonical Claude-primary ReviewOps discipline for evidence-bound adjudication, PR-ledger resolution, report parity, closure, and safety-critical maintenance review. Use when review output or check_run results must change run or repository decisions.
---

# Xunji ReviewOps

ReviewOps owns adjudication, not reviewer-backend mechanics. Reviewer output is
a candidate challenge; Root/Single Synthesizer alone promotes, downgrades,
deduplicates, reports, reopens, or closes through evidence, tests, and recorded
rationale.

Before invoking or auditing `tools/peer_review.py`, read
`references/peer-review-panel.md` completely. That reference is the sole
Claude-primary owner for backend selection, author matrix, CLI usage, egress,
and fallback semantics. `xunji-peer-review-panel` is only a compatibility alias.

## Core Posture

- Prefer evidence-backed disagreement over agreement with an operator, reviewer,
  report, or prior decision.
- Keep every disposition attributable to E-ids, artifacts, controls, hashes,
  file paths, tests, or review records. Confidence and green tooling are not
  evidence by themselves.
- Keep the driver autonomous: this skill governs truth and closure integrity; it
  is not a process script or vulnerability checklist.

## Triggers

Run a ReviewOps pass when any of these is true:

- The run is preparing `report.md`, summarizing, or claiming closure.
- `tools/check_run.py` reports hard gates or meaningful warnings.
- `review.md` contains pending Review Finding Ledger items.
- Evidence, artifacts, replay status, report text, or the reviewed diff changed.
- A HIGH/CRITICAL or `certainty >= 0.8` claim needs independent severity support.
- A repository change enters the mandatory independent-review behavior set.

## Adjudication Loop

1. Read current canonical state and cited artifacts, not only reviewer prose.
2. Run the routine offline structural check owned by `xunji-run-lifecycle`; treat
   hard gates as next work.
3. If independent review is required, follow the peer-review reference with the
   correct author driver. Refresh review when its content hash no longer matches.
4. For load-bearing replay, invoke `xunji-evidence-replay-gate`; do not duplicate
   replay rules here.
5. Resolve every candidate by reopening work, adding a control/artifact,
   downgrading, accepting, dismissing, superseding, escalating, or changing the
   report. Record why.

Passing `check_run` proves required structure, not report truth. A review receipt
is freshness-bearing only for the content it binds; unresolved historical
BLOCKERs still matter.

## PR Ledger

For each `PR-xxx` under `## Review Finding Ledger`:

- `BLOCKER` cannot remain pending/open/unresolved at closure.
- Resolve `WARN` before closure unless the evidence-bound deferral is recorded.
- Accept only claims that survive artifact and evidence checks.
- Dismiss only with a concrete alternate explanation and supporting evidence.
- Use only the statuses and resolver contract documented in the peer-review
  reference. `DriverResolution` must cite the E-id, artifact, control, decision,
  test, diff, or reopened front that supports it.

## Evidence And Report QA

Before promotion or reporting, require:

- **Mechanism:** the artifact explains why the condition caused the response.
- **Control:** a replicated control addresses the obvious alternate explanation.
- **Impact:** the capability reaches a meaningful unauthorized boundary.
- **Artifact:** the saved response/replay/screenshot/output contains the claim.
- **Report parity:** confirmed `certainty >= 0.8` findings are reported or
  excluded with an evidence-bound reason; report E-ids passed the evidence gate.

HIGH/CRITICAL claims retain the independent severity fields required by the run
rules. CRITICAL pause requires its additional review before pausing.

## Closure

Do not declare FINAL, complete, 收工, or "explored enough" unless both are true:

- The lifecycle owner's routine offline structural check has no hard gates.
- No front remains open, and every deferred/closed front has an evidence-backed
  rationale accepted through adjudication.

Otherwise continue the highest-value safe work: reopen, verify, obtain a control,
repair the ledger, or downgrade the claim.

## Repository Maintenance Review

For changes in the mandatory independent-review behavior set, read
`xunji-sentinel-guard-review` and the narrow gate in
`docs/WORKFLOW-reference.md` completely. Run affected focused tests plus the
required aggregate validation, obtain a fresh-context review of the changed
behavior, and record findings/dispositions under `review/records/`.

For a Codex-authored candidate, use author driver `codex` as documented in the
peer-review reference. Codex self-review never counts as its independent vote;
Claude Code remains the acceptance-side reviewer and the live-run boundary is
unchanged.

## Exclusions

- Do not add generic exploit lists or replace the live graph with a checklist.
- Do not treat reviewer confidence, model identity, report prose, or tool green
  status as evidence.
- Do not use Codex or `.codex/` artifacts as proof that Claude live hooks ran.
