# Runtime Receipt Evidence

## E-001 - Receipt implementation invariants

- Maturity: finding
- Action: Review receipt normalization, hash chain, transcript lookup, per-session fan-out, post-return disposition, exact Cron ownership, and protected state paths.
- Result: Static implementation and synthetic transcript fixtures reject manual files, old sessions, unmerged results, tampered chains, response-substring job IDs, stale CronList, and direct control-file edits. Real Claude runtime behavior is claimed only in `live-scope`.
- Control: Focused selftests include every rejected bypass and bind installed source hashes to hook settings.
- Replicated: yes
- Artifacts: `runtime_receipts.lines-001-150.txt`, `runtime_receipts.lines-151-300.txt`, `runtime_receipts.lines-301-450.txt`, `runtime_receipts.lines-451-600.txt`, `runtime_receipts.lines-601-750.txt`, `runtime_receipts.lines-751-end.txt`, `workers.diff`, `settings.diff`, `installed-settings.json`, `installed-runtime-manifest.json`, `adversarial_selftests.log`, `adversarial_selftests.summary.json`, `selftest_all.log`
- Certainty: 0.8
