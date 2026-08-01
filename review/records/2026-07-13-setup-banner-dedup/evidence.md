# Maintenance Evidence Ledger

## E-001 - setup phase banner deduplication

- Maturity: finding
- Action: Review removal of setup_run terminal box banners while preserving lifecycle journal events.
- Result: The banner renderer and both start/end banner print calls are removed; phase_start and phase_end journal calls remain.
- Control: The setup selftest asserts that the banner helper is absent and the Setup journal cycle closes without an open phase.
- Replicated: yes
- Artifacts: `setup_run.diff`, `docs_excerpt.md`, `selftest.log`
- Certainty: 1.0

## E-002 - focused regression

- Maturity: finding
- Action: Run setup, statusline, loop journal, and loop bootstrap regressions.
- Result: All four focused suites passed and repository rule checks passed.
- Control: Static assertions are visible in setup_run.diff.
- Replicated: yes
- Artifacts: `setup_run.diff`, `selftest.log`
- Certainty: 1.0

## E-003 - full repository regression

- Maturity: finding
- Action: Run the complete repository selftest set after the behavior and documentation changes.
- Result: All 60 suites passed with 0 failures.
- Control: Focused setup assertions remain visible in `setup_run.diff` and the full-suite summary is retained separately.
- Replicated: yes
- Artifacts: `setup_run.diff`, `selftest.log`
- Certainty: 1.0
