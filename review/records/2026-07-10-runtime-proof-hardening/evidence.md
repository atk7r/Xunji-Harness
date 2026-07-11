# Maintenance Evidence Ledger

## E-001 - Turn mode and pause transaction

- Maturity: finding
- Action: Review prompt classification, PreToolUse restrictions, Stop exemptions, and current-run migration.
- Result: Explain-only is read-only without Coda; ambiguous prompts default read-only; operator pause preserves active fronts and only permits bound Cron cleanup; execute requires explicit action intent.
- Control: Negative selftests cover mixed why/fix prompts, ambiguous history prompts, pause, prohibited Bash/write actions, and no-active-run CronCreate. The installed hook snapshot and runtime observation verify wiring and execution.
- Replicated: yes
- Artifacts: `output_gate.diff`, `run_gate.hunks-01.diff`, `run_gate.hunks-02.diff`, `settings.diff`, `installed-settings.json`, `turn_contract.lines-001-170.txt`, `turn_contract.lines-171-340.txt`, `turn_contract.lines-341-510.txt`, `turn_contract.lines-511-680.txt`, `turn_contract.lines-681-end.txt`, `run_model.diff`
- Certainty: 1.0
- Supports: E-005

## E-002 - Agent and Cron runtime authenticity

- Maturity: finding
- Action: Review the hook-derived receipt chain and per-turn Agent/Cron gates.
- Result: Fan-out requires two current-turn transcript-backed Agent calls on distinct assignments/fronts, followed by newer anchored dispositions; Cron mutation requires current-turn list state and run-job binding.
- Control: Tests reject hand-written heartbeat, old-session receipts, old dispositions, unlisted Cron deletion, stale CronList, direct receipt mutation, and bare completion PASS. The installed-entrypoint observation records 19 passing checks and a ten-event valid receipt chain.
- Replicated: yes
- Artifacts: `runtime_receipts.lines-001-150.txt`, `runtime_receipts.lines-151-300.txt`, `runtime_receipts.lines-301-450.txt`, `runtime_receipts.lines-451-end.txt`, `workers.diff`, `runtime_observation.py`, `runtime_observation.lines-001-190.txt`, `runtime_observation.lines-191-380.txt`, `runtime_observation.lines-381-end.txt`
- Certainty: 1.0
- Supports: E-005

## E-003 - Review and completion provenance

- Maturity: finding
- Action: Review content-addressed peer-review receipts, current evidence hashes, ledger IDs, and completion Agent proof.
- Result: Manual/copied prose cannot pass; peer review must be a time-bound foreground invocation; stale evidence invalidates the latest receipt; old stale hashes no longer poison a newer review; duplicate PR IDs hard-fail; completion needs a current evidence-bound Agent receipt that echoes all four closure checks.
- Control: Negative tests cover manual Reviewer/Verdict, missing receipt, stale hash, stale invocation, duplicate PR IDs, journal-only Cron claims, and prose-only completion review. Round-one independent findings and their disposition are retained.
- Replicated: yes
- Artifacts: `check_run.hunks-01.diff`, `check_run.hunks-02.diff`, `check_run.hunks-03.diff`, `check_run.hunks-04.diff`, `peer_review.diff`, `disposition.md`
- Certainty: 1.0
- Supports: E-005

## E-004 - Canonical state and operator visibility

- Maturity: finding
- Action: Review canonical parser adoption by loop, workers, graph, projection, coverage, gates, and statusline.
- Result: Compound/missing/conflicting statuses and duplicate front IDs are surfaced; paused/interrupted and planned/real Agent state are distinct; stale caches use read-only live derivation.
- Control: Parser and statusline tests include compound status, section fallback, duplicate ID, pause display, stale cache, and missing cache cases.
- Replicated: yes
- Artifacts: `canonical_consumers.diff`, `status_journal.diff`
- Certainty: 1.0
- Supports: E-005

## E-005 - Full regression

- Maturity: finding
- Action: Run the complete repository selftest suite after all implementation and documentation changes.
- Result: 57 suites passed and 0 failed; raw log retains timing.
- Control: The raw captured command output is retained in the review scope.
- Replicated: yes
- Artifacts: `test_registry.diff`, `selftest_all.log`
- Certainty: 1.0
- Supports: E-001, E-002, E-003, E-004
