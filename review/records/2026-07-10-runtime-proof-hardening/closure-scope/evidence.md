# Closure Evidence

## E-001 - Closure and maturity gates

- Maturity: finding
- Action: Review canonical front schema, composed-chain maturity, Agent integration, review receipt, completion receipt, Cron receipt, and ledger freshness changes.
- Result: Manual/stale/prose-only process claims fail; current content/runtime proof is required.
- Control: Negative selftests cover every listed bypass.
- Replicated: yes
- Artifacts: `check_run.hunks-01.diff`, `check_run.hunks-02.diff`, `check_run.hunks-03.diff`, `check_run.hunks-04.diff`, `test_registry.diff`, `selftest_all.log`, `closure_selftests.summary.json`, `closure-source-manifest.json`
- Certainty: 1.0

## E-002 - Peer-review provenance

- Maturity: finding
- Action: Review content-addressed review receipt creation, global PR identity, and stable evidence hashing.
- Result: Receipts are atomic/content-addressed; repeated ledgers get unique IDs; current evidence invalidates stale review.
- Control: Peer-review and check-run selftests cover stale hashes, duplicate IDs, missing artifacts, and invalid review output.
- Replicated: yes
- Artifacts: `peer_review.diff`
- Certainty: 1.0

## E-003 - Canonical projections and statusline

- Maturity: finding
- Action: Review canonical parser adoption, journal chaining, paused/interrupted rendering, and real/planned Agent visibility.
- Result: Critical consumers share front semantics and stale state is visibly derived/interrupted rather than false idle.
- Control: State, loop, coverage, journal, and statusline selftests.
- Replicated: yes
- Artifacts: `canonical_consumers.diff`, `status_journal.diff`
- Certainty: 1.0
