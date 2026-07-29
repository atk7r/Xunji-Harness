# Evidence

## E-001 — candidate diff and authority boundary

- Maturity: finding
- Action: Inspect the exact normalization diff and its positive/negative authority
  fixtures.
- Result: only a stripped source that resolves under authoritative `RUNS` compiles
  as an existing run; a foreign same-shaped path remains a file source.
- Control: the foreign absolute path and run-internal subpath are negative controls.
- Replicated: yes
- Artifacts: `evidence/active-diff.txt`
- Certainty: 0.8

## E-002 — focused and full selftests

- Maturity: finding
- Action: Run focused turn-contract checks and the complete framework scorecard.
- Result: the new regression and all 69 framework suites pass.
- Control: rule, compile, diff, foreign-path, and existing run-file cases remain.
- Replicated: yes
- Artifacts: `evidence/test-results.txt`
- Certainty: 0.8

## E-003 — failed first real-driver attempt

- Maturity: finding
- Action: Run the original attached absolute form from a `/tmp` isolated worktree.
- Result: session `329f3cbb-22af-4c35-a88c-394f209ace7a` stayed on the origin run
  because `/tmp` and resolved `/private/tmp` spellings differed.
- Control: pointer and compiled contract were read after the attempt.
- Replicated: yes
- Artifacts: `evidence/driver-attempt-1.json`
- Certainty: 1.0

## E-004 — successful isolated Claude primary-driver rerun

- Maturity: finding
- Action: Rerun the same client-reserved `/loop` shape after resolution-aware
  normalization, starting from a different active run.
- Result: session `518f475c-db62-48fb-9375-6c790da231ac` committed the typed resume
  and independently verified the pointer.
- Control: exact wrapper denial/clean retry, origin/target pointer transition,
  activation receipt, and forbidden tool inventory are frozen separately.
- Replicated: yes
- Artifacts: `evidence/driver-attempt-2.json`
- Certainty: 1.0
