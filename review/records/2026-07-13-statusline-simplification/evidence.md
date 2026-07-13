# Maintenance Evidence Ledger

## E-001 - Statusline workspace gating and concise rendering

- Maturity: finding
- Action: Review the frozen statusline code and documentation diff.
- Result: Rendering is empty without an explicit Xunji workspace or active run; an active run renders only the status tag, phase tag, and run name.
- Control: Selftests cover unspecified workspace, outside workspace, no active run, exact concise output, an isolated stdin-to-CLI-to-stdout color path, read-only rendering, missing cache, active-run contract transfer, and before/after fingerprints of the real pointer and real run contract.
- Replicated: yes
- Artifacts: `statusline.diff`, `docs.diff`, `reviewed.diff`, `selftest.log`
- Certainty: 1.0

## E-002 - Regression verification

- Maturity: finding
- Action: Run the focused statusline suite, rule check, and complete repository selftest set.
- Result: Focused statusline suite passed; rule check passed; all 60 repository selftest suites passed with 0 failures.
- Control: `statusline.diff` statically records the exact selftest assertions; `selftest.log` separately records their successful execution.
- Replicated: yes
- Artifacts: `statusline.diff`, `selftest.log`
- Certainty: 1.0

## E-003 - Installed Claude Code statusLine payload contract

- Maturity: finding
- Action: Inspect the locally installed Claude Code v2.1.201 statusLine schema and payload construction.
- Result: Both the embedded schema and runtime payload constructor include `workspace.current_dir`; the constructor writes it unconditionally from the current directory.
- Control: The same schema also carries top-level `cwd`, but Xunji intentionally ignores that fallback so only an explicit workspace selects display context.
- Replicated: yes
- Artifacts: `claude_statusline_contract.txt`
- Certainty: 1.0
