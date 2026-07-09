# Maintenance Evidence Ledger

## E-001 - Stop and active-run enforcement

- Maturity: finding
- Action: Review active-run resolution plus both Stop hooks as one enforcement path.
- Result: The explicit pointer, strict single-action Coda, fail-closed fallback, active-front counting, independent-review gate, and completion-review gate are implemented with focused regressions.
- Control: `output_gate.py --selftest` and `run_gate.py --selftest` are included in the complete E-003 test run.
- Replicated: yes
- Artifacts: `anti_drift.diff`, `output_gate.diff`, `run_gate.diff`, `docs.diff`
- Certainty: 1.0
- Supports: E-003

## E-002 - Lifecycle, coverage, and probe enforcement

- Maturity: finding
- Action: Review per-item retrospective proof, structured review predicates, conservative coverage writes, and browser-like cookie chaining.
- Result: Every structured retrospective issue needs its own disposition/proof; prose cannot satisfy review gates; mention-only coverage cannot create verdicts; cookie precedence, deletion, UTC expiry, null filtering, and atomic owner-only persistence are implemented.
- Control: Focused `check_run.py`, `coverage_matrix.py`, and `probe.py` selftests are included in E-003.
- Replicated: yes
- Artifacts: `check_run.diff`, `coverage_matrix.diff`, `probe.diff`
- Certainty: 1.0
- Supports: E-003

## E-003 - Full regression result

- Maturity: finding
- Action: Run `python3 tools/selftest_all.py --timeout 600` after all behavior changes.
- Result: The captured log ends with 54 suites passed and 0 failed in 76.9 seconds.
- Control: Raw command output is retained and hashed; focused hook, lifecycle, coverage, retrospective, and probe assertions are visible in their component diffs.
- Replicated: yes
- Artifacts: `selftest_all.log`
- Artifact SHA1: `085d417bc85599247e7b15128c881f64e9c077d0`
- Certainty: 1.0
- Supports: E-001, E-002

## E-004 - Frozen scope and provenance

- Maturity: finding
- Action: Bind the reviewed component set to one Git base and one aggregate working-tree diff.
- Result: Seven non-overlapping component diffs cover all 13 framework paths; the local aggregate is retained without duplicating its 100,139 bytes into the external review bundle.
- Control: Component and aggregate SHA1 values are recorded in the manifest and can be recomputed locally; `base_commit.txt` records the exact base.
- Replicated: yes
- Artifacts: `base_commit.txt`, `diff_manifest.md`
- Certainty: 1.0
- Supports: E-001, E-002, E-003
