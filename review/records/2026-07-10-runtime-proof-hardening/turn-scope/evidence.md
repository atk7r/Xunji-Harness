# Turn Enforcement Evidence

## E-001 - Turn modes and fail-closed state

- Maturity: finding
- Action: Review prompt modes, global PreTool ordering, Stop behavior, canonical front parsing, and invalid-state handling.
- Result: Ambiguous or explanation prompts are read-only; pause preserves fronts; explicit execution blocks target actions until current-turn fan-out and post-return disposition; malformed/missing/stale/cross-session contracts and malformed frontier state fail closed. A denied target action remains unresolved until the same tool/input receives a later successful receipt; while unresolved, free-form output is rejected rather than semantically guessed.
- Control: Source selftests exercise mixed-language classifiers, missing and corrupt state, wrong schema/session, stale state, serial-override provenance, and malformed frontier.
- Replicated: yes
- Artifacts: `output_gate.diff`, `run_gate.hunks-01.diff`, `run_gate.hunks-02.diff`, `settings.diff`, `turn_contract.lines-001-170.txt`, `turn_contract.lines-171-340.txt`, `turn_contract.lines-341-510.txt`, `turn_contract.lines-511-680.txt`, `turn_contract.lines-681-end.txt`, `adversarial_selftests.lines-001-170.txt`, `adversarial_selftests.lines-171-end.txt`
- Certainty: 1.0
