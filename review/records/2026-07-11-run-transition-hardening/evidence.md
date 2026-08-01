# Evidence Ledger

## E-001 - Current transition implementation diff

- Maturity: finding
- Result: Current code changes for pending contracts, explicit active pointers,
  contract transfer, guarded lifecycle commands, post-setup activation, and
  removal of recent-run inference from anti-drift/Stop gates.
- Certainty: 0.9
- Replicated / Control: Review against the parent commit and attempt cross-run/session bypasses.
- Artifacts: evidence/transition-core.diff
- Supports: F-001, F-002

## E-002 - Current Stop-hook implementation diff

- Maturity: finding
- Result: First invalid Stop blocks; `stop_hook_active` retries do not re-enter a block loop; no-front denial uses `frontier.md`.
- Certainty: 0.9
- Replicated / Control: Compare normal Stop and retry subprocess cases in hook selftests.
- Artifacts: evidence/stop-hooks.diff
- Supports: F-003

## E-003 - Claude-primary documentation diff

- Maturity: finding
- Result: Primary rules describe transactional setup/resume, pointer protection, pending bootstrap, Cron ordering, and Stop retry semantics.
- Certainty: 0.9
- Replicated / Control: Compare every stated command and invariant with code and registered selftests.
- Artifacts: evidence/docs.diff
- Supports: F-004

## E-004 - Full repository regression

- Maturity: finding
- Result: Full `tools/selftest_all.py --timeout 600` regression output captured after the implementation.
- Certainty: 1.0
- Replicated / Control: Inspect exact suite count and failures in the artifact; rerun after review fixes.
- Artifacts: evidence/selftest_all.log
- Supports: F-001, F-002, F-003, F-004
