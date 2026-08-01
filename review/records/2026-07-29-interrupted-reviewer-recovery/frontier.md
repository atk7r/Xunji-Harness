# Review Fronts

## F-001 — Recovery proof is narrow and fail-closed

- Status: closed
- Evidence: E-001, E-003, E-004
- Closure: only an exact parent interruption plus exact child hook timeout and
  zero child model/tool/terminal activity may supersede the immutable Start.
  Exact A-review-012 bytes are exercised for recovery; later lifecycle settlement
  is exercised by the targetless native fixture.

## F-002 — Reviewer invariants survive recovery

- Status: closed
- Evidence: E-001, E-002, E-004
- Closure: the physical journal is append-only; the Reviewer is not cancelled,
  bypassed, or recreated; the same assignment row and frozen launch contract are
  replayed.

## F-003 — Projection no longer times out on the observed transcript size

- Status: closed
- Evidence: E-001, E-002, E-003
- Closure: token lookup is batched per transcript and the attempt graph is built
  once per projection snapshot. The real `workers.py delegate` owner path recovered
  an isolated copy of the observed 25 MB case in 1.61 seconds under `/usr/bin/time`.

## F-004 — Claude primary driver can complete the repaired path

- Status: deferred
- Evidence: E-004
- Disposition: a real Claude Code 2.1.201 / configured DeepSeek driver recovered
  the synthetic interrupted Reviewer, replayed its exact contract, launched the
  real Reviewer, settled the Hunter, and emitted cycle_end without target effects.
  A single unified E2E combining the original 25 MB copied run with full
  launch/settlement remains deferred because the copied work-plan transaction
  correctly binds its original absolute run_dir and the live run is out of this
  maintenance mutation scope.
