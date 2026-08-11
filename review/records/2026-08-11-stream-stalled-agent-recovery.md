# Stream-stalled Agent typed recovery review

- Date: 2026-08-11
- Author/synthesizer: Codex
- Scope: add a separately versioned, failed-only recovery for one exact
  plan-bound non-Reviewer Agent killed by Claude Code's stream watchdog after
  600 seconds of idle stream, where the runtime journal has launch and Start
  but no Stop.
- Review matrix: external assistance is disabled by project policy. The
  independent vote is one fresh-context, no-tools DeepSeek-backed Claude Code
  review; no heterogeneous external-provider vote is claimed.

## Contract and implementation

The public owner command is:

```text
python3 tools/workers.py settle-stream-stalled runs/<dir> A-<assignment>
```

Eligibility requires one exact successful plan-bound Hunter launch and Start,
the same assignment/session/tool/agent/lane/plan/prompt identity, no Stop, no
later attempt-owned runtime activity, one host system failed task-notification
with the exact 600-second unrecovered stream-watchdog summary and frozen note,
and a full child transcript ending with the exact synthetic idle-timeout API
error immediately followed by the exact interruption record. The parent prefix
through the notification and full child transcript are hashed. The
content-addressed `xunji.stream-stalled-agent.v1` receipt also binds the
launch/Start/runtime head, notification/error/interruption UUIDs, normalized
failure time, and deterministic failure snapshot.

The notification's partial `<result>` remains source data and is never used as
the Agent result. Projection is `failed`, never `returned`; it creates no Stop,
evidence, finding, merge, front closure, or cycle completion. The unique
digest-bound Reviewer and Root blocked/failed/abandoned disposition remain
mandatory, and the killed attempt must not be resumed. Receipt loading is
mutually exclusive with external-stop and hook-failed-Stop receipts and is
validated by every effective-event/attempt/append consumer. Late Stop or child
calls become integrity conflicts.

## Verification

- Python compilation passed for every changed module.
- Focused contract-schema, capability-registry, command-shape,
  runtime-receipts, workers, agent-settlement, turn-contract, and run-model
  suites passed.
- Exact final `python3 tools/selftest_all.py`: 78 passed, 0 failed in 141.9
  seconds with Python 3.14.
- `check_templates.py`, `check_hook.py`, and `git diff --check` passed.
- `check_rules.py` remains HOLD only for three pre-existing safety-manifest
  omissions: `tools/artifact_view.py`, `tools/barrier_state.py`, and
  `tools/completion_transaction.py`. This change does not claim that unrelated
  debt is green.
- The named stream fixture covers exact eligibility, summary drift, prior Stop,
  stale-plan routing, schema, failed-only/source projection, receipt replay,
  late physical Stop, child transcript tamper, and restored integrity.

## Claude Code real-driver validation

The candidate repository and copied run were isolated at
`/private/tmp/xunji-stream-stall-driver.T2Kxhe/Xunji`. The copied historical
runtime receipts retain absolute transcript paths to the original read-only
Claude transcript; all state writes and the active pointer were confined to the
copy.

Two preliminary prompts are not counted as PASS:

- Session `75157f12-d10b-40f9-a91f-4b7e81885e97` used maintenance wording, so
  the real Hook correctly denied the live control command. Transcript SHA-256:
  `f5d1f9abaee093187cadb27ff06ac2f5cbf8fd6b415023d4ca4e7e7648473a87`.
- Session `d5c2d21c-794b-4d4f-bba7-1533cba4f082` did not name the run path, so
  the existing lifecycle intent compiler kept `INTENT_PENDING` and denied even
  status. Transcript SHA-256:
  `d8a33487c080439547b773662e7c082e109c8d8e7080aeec41f3abd626ae78f2`.

The representative explicit-run prompt passed. Fresh driver session
`1d505eae-aa41-41c4-8b01-a206450d4e09` used the real Claude-primary skill,
Hooks, lifecycle bootstrap, public status, and exact printed settlement command.
Runtime seq 488 recorded
`capability_id=control.workers-settle-stream-stalled`, `effect=control`, and
`success=true`. Receipt
`26d76b03c708f48f016f27421cb3b239355a03fd38bf08a8ac3033dc69c45d72`
validated with a clean chain/integrity projection, attempt `failed`, source
`stream_stall_receipt`, and no Agent, Reviewer, Cron, target, WebSearch, or
WebFetch action in that driver session. Transcript SHA-256:
`bf4ace0f6d0c266470f3f51f3782494b7e1c0b269e14ebf0f9b51cfe55b89829`.

## Independent review

The exact frozen no-tools review prompt was 167,166 bytes, SHA-256
`91d6ce452808cfb207e3b96db2d16141969f8417100c7af04aa2271c37752a5a`.
Fresh review session `165d7cf4-23c3-45b2-9bf0-85fb6fc96f71` returned
`VERDICT: PASS`, no required fixes, and no P0-P2 finding. Transcript SHA-256:
`892e9214199ecd60ea35472d35779e9d44878aea8199aebe0533ab84add19c37`.

Accepted LOW residuals:

- More than one exact matching task-notification keeps the attempt fail closed
  instead of choosing one. That can preserve lifecycle debt after an improper
  resume, but cannot mint return/evidence/merge; the contract explicitly forbids
  resuming the killed attempt.
- Replay after review was questioned from the scoped excerpt. Direct inspection
  confirms `_write_merge_draft` preserves `review_receipt`, `review_status`, and
  per-asset outcomes only when every frozen binding remains exact; otherwise it
  correctly reopens review rather than silently carrying a stale disposition.
- Raw receipt result paths and run-model safe-attempt paths coincide because
  `_TRANSCRIPT_ID_RE` permits only filesystem-safe `[A-Za-z0-9_-]` identities.
- Read-only eligibility maps owner errors to `not_eligible`; the independent
  runtime projection remains fail closed. This is a diagnostic-quality residual,
  not an authority broadening.

## Concurrent live-run attribution

While Codex was completing the test and review gates, the already-running Claude
primary session observed the shared candidate files and independently executed
the new command on the original run. Codex did not issue that live mutation and
does not roll it back. Live runtime seq 401 records the exact registered control
success. Receipt
`ca65346ea3ee1b693b4d069444040b71ebf8fd60796f0c9fb6dd32f7d296ce71`
projects A-web-hunter-005/ac7d443b1007b9605 failed with source
`stream_stall_receipt`; the live chain and Agent integrity check are clean.
The same Claude owner then completed A-review-005 and Root non-merged blocked
settlement before continuing later lanes. Those later target actions belong to
that pre-existing Claude run, not to Codex's isolated driver validation.

## Final disposition

PASS. No unresolved correctness or safety finding. Missing heterogeneous
external-provider review, conservative duplicate-notification behavior, the
absolute transcript dependency in the copied fixture, and unrelated existing
`check_rules.py` debt remain explicit limitations.

## Integrated candidate commit review — 2026-08-12

- Verdict: WARN
- reviewed_diff: b57d324f8494cc01
- Candidate branch: `codex/fix-stream-stalled-agent`, isolated from the
  operator's dirty worktree and index.
- Candidate scope: the stream-stall recovery plus the current uncommitted
  lifecycle, closure, ingress, capability, output-layout, safety, documentation,
  and schema dependencies required for the clean checkout to pass. Run evidence,
  target HTML, images, and unrelated local target material are excluded.

The exact staged snapshot passed `/opt/homebrew/bin/python3
tools/selftest_all.py` with 78 passed and 0 failed in 134.5 seconds.
`tools/check_templates.py`, `tools/check_hook.py`, and `git diff --check` also
passed. `check_rules.py` remains HOLD for the three pre-existing manifest
omissions named above; it is not represented as green.

External assistance was disabled. Fresh-context, no-tools Claude Code review
used the configured DeepSeek backend, so these are same-family independent
votes, not heterogeneous votes. Successful review sessions were:

- safety surface: `ea8a7a47-48c4-4f5c-bb44-489196d86541` — WARN, P3 only;
- lifecycle surfaces: `613f7f19-b25b-4932-acfd-079541925054` and
  `ed051055-c421-4b17-801b-f5cd0d733677` — WARN, P3 only;
- runtime slices: `fb1b745d-1c8e-4ee9-a38b-611711f4676c`,
  `94407c6a-7972-4aee-93e5-6a08e497aa17`,
  `3d44f26a-b9cf-4ccc-9109-426eb3d5ed97`, and
  `cc123d9f-4da6-4504-a999-82f8b6b5533a` — alleged P1/P2 findings were
  adjudicated against full code and tests;
- projection-cursor follow-up: `788ae737-17c5-4905-9d68-9f1b9102ebaa` — PASS.

The valid runtime review identified one real P2: a successful reconciliation
could advance the projection cursor before proving that its snapshot covered an
older diagnostic. The final patch validates current and snapshot coverage first,
then advances the cursor; the selftest now also proves that a conflicting
diagnostic publishes no cursor. The focused runtime suite and the full suite pass,
and session `788ae737-17c5-4905-9d68-9f1b9102ebaa` approved that follow-up.

A later narrow review session `c5094f15-ae10-404c-9e22-f625b87cf328`
correctly rejected an attempted over-broad hard failure for every failed Agent
without a termination hash. That attempted change was removed before this
fingerprint: ordinary launch failures and compatible historical failure rows are
not external-stop receipts.

Other P1/P2 allegations were dismissed only after source adjudication: stream
notification multiplicity is an intentional fail-closed no-resume rule; Agent
tool-use collection already deduplicates; result bytes remain bound by raw
response semantics and content-addressed snapshots; changed merge bindings clear
old review receipts; and registered target actions are derived rather than trusted
from raw caller metadata. Accepted P3 debt includes conservative replay/diagnostic
compatibility, cache invalidation granularity, diagnostic race hardening, and
some validator/diagnostic usability gaps. None broadens outbound authority,
promotes evidence, or closes a lifecycle without a typed receipt.

Three oversized review attempts
(`58bed85b-7f77-41bd-8217-fef27c9e971a`,
`2c754278-617b-48b0-ae4b-540b0db5904c`, and
`981f2bec-7c88-403c-81b5-8e7b8168c894`) exceeded output limits, and two later
runtime slices (`d83d7d77-d0d7-4968-9e18-a3279da6552e` and
`df5b5954-e8fe-4c43-bed6-49c6780b49ea`) were stopped after more than ten minutes
without output. None is counted as a vote.

Integrated disposition: WARN, with no unresolved P0-P2 finding. The warning is
for the accepted P3 items, the existing `check_rules.py` HOLD, the lack of a
heterogeneous provider, and the fact that the large integrated diff required
owner-surface review slices rather than one reliable full-diff model response.
