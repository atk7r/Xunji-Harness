# Resume-safe lifecycle admission and settlement E2E

- Date: 2026-07-24
- Author/driver: Codex-authored framework change; configured DeepSeek-backed Claude Code primary driver
- Candidate checkout: isolated detached worktree at commit `bae75da`, with only the scoped candidate files overlaid
- Live run recovered: `runs/www-scshr-com_20260723`
- Target/network effects during all recovery driver runs: 0
- Agent launches during all recovery driver runs: 0

## Failure reproduced

The physical runtime journal contained five bare `SubagentStop` receipts with no
Xunji type, assignment, parent tool-use, Start/launch, or assignment-ledger
owner: event seq `163`, `171`, `192`, `232`, and `233`. The events immediately
preceded Claude Code `system/subtype=away_summary` records. Projection stopped at
the first orphan and exposed `runtime_projection_error.json`.

## Isolated primary-driver validation

Two fresh Claude Code primary-driver runs received an ordinary natural-language
request to continue the copied run but perform only local lifecycle recovery.
They exercised the real turn Hook, capability registry, runtime receipt owner,
projection, and output gate.

- First driver session: `f01c9aa9-a5a6-45bf-af6d-8e0b77229b63`
- Final-candidate driver session: `0860e6cf-62e8-4258-a831-f6a534570280`
- Required owner action observed:
  `control.runtime-receipts-quarantine`
- Quarantine result: five content-addressed
  `xunji.foreign_agent_lifecycle.v1` receipts
- Final runtime read: `errors=[]`
- Projection diagnostic: absent
- New target receipts: 0
- New Agent lifecycle receipts: 0

Denied exploratory `ls`, wrapped commands, wrong interpreter, and unrelated
control attempts remained denials/failures and were not counted as results.
Claude's final prose was not used as the pass criterion.

## Live recovery

The typed recovery owner quarantined the same five immutable event identities.
`runtime_events.jsonl` SHA-256 was
`f0927bf076d2ef4bfea72c72c7c9dfe451d3dcf06bee5b03db8df25d7ebcf292`
both before and after recovery. Projection advanced through event seq `233`,
`runtime_projection_error.json` was cleared, and runtime integrity returned no
errors.

## Live resume and stale-assignment settlement

The supplied session `c706831c-6700-4fbe-9d49-a00029bbed50` exposed two more
causal defects after quarantine:

1. Eight exact parent `PreToolUseDenied Agent` receipts for
   `A-web-hunter-003` were counted as positive runtime activity, even though
   every call was rejected before launch.
2. The current offline turn revalidated all old plan lanes and raised
   `WORK_PLAN_OPERATOR_TARGET_EGRESS_DENIED` before the local cancellation
   proof.
3. Natural wording that combined an affirmative action with scoped denials,
   such as “继续修复当前运行；不要联网、不要启动 Agent”, let a broad denial
   regex cross punctuation and incorrectly installed `EXPLAIN_ONLY`.

The final candidate treats only exact plan/lane/session/transcript-bound
`PreToolUseDenied Agent` receipts as negative launch proof. A failed/successful
Post, Start/Stop, or child action still forms runtime debt. Cancellation loads
immutable transaction identity and proves turn/input staleness under its locks;
current target denial still blocks target effects but no longer re-authorizes
the old plan before local settlement. Lifecycle denial matching is clause-local,
and natural-language fixtures cover five execute and five read-only variants.

The real resumed Claude driver then completed the public typed cancellation.
Independent state adjudication found:

- assignment row `A-web-hunter-003`: absent
- cancellation transaction: `committed`
- immutable tombstone status: `cancelled-unlaunched`
- tombstone stale basis: `both`
- tombstone receipt digest:
  `c742140e56c194356bd8578e4f4000d0d9d4c61beca88e275de30c475f6f41e8`
- Agent Board: four historical settled assignments, no `A-web-hunter-003`
- runtime projection diagnostic: absent
- target receipts and Agent lifecycle events added by settlement: 0

No assignment or journal was directly edited. Earlier driver attempts proposed
destructive manual cleanup, but the Hook denied the actions and those proposals
were not executed.

## Isolated validation boundary

The isolated worktree successfully exercised foreign lifecycle quarantine.
It cannot truthfully replay this existing cancellation transaction after copying
the live run: loop-journal and plan-transaction receipts intentionally freeze the
original absolute `run_dir`, so the copy fails closed with
`WORK_PLAN_TRANSACTION_JOURNAL_DIVERGED`. Two exploratory copied-run driver
attempts were stopped and are not counted as passes. The path-bound cancellation
E2E is therefore the successful live resumed session above; focused synthetic
selftests provide the isolated deny/offline cancellation regression.
