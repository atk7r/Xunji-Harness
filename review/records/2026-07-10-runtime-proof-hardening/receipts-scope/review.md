# Review

This Codex-authored static/control scope requires arkcli panel plus fresh Claude
review. This file does not claim a completed ReviewReceipt or PASS.

## Driver Disposition

- Earlier action-hash and peer-review provenance findings were accepted: unknown
  tool semantics now participate in action hashes, and review validation binds
  exact foreground invocation, receipt marker, bundle marker, and content hash.
- Former live/entrypoint E-002 was moved to `live-scope`; this scope does not
  relabel fixture transcript IDs as live observations.
- The stale unreferenced `adversarial_selftests.log` copy was removed. The cited
  summary carries per-command check names/counts, failure counts, output hashes,
  and one source hash from the same generated run.
- E-001 is calibrated to 0.8 and limited to implementation invariants plus
  synthetic adversarial controls. Real Claude behavior remains in `live-scope`.
- Backend parse/timeout failures remain explicit limitations and never count as
  PASS votes.
