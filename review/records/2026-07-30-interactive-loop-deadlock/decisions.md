# Decisions

- D-001: Treat interactive `/loop` as one execute cycle, not as recurring
  scheduling authority. Root keeps strategy autonomy inside that cycle.
- D-002: A normal cycle ends only after the exact typed `cycle_end`; whole-run
  completion remains the separate `check_run` plus review/closure predicate.
- D-003: Another cycle requires a new top-level execute prompt. Xunji does not
  inject periodic prompts into the same growing Claude conversation.
- D-004: Preserve plan and runtime journals. Prevent repeat work by projecting
  settled identities through verified transaction lineage, not by deleting or
  editing old assignments.
- D-005: Bound the default status projection rather than hiding active debt;
  retain `--all` for explicit ledger inspection.
- D-006: Count only the second path-native, target-network-denied DeepSeek
  Claude Code run as decisive real-driver validation. Preserve the first
  overconstrained run as a failed fixture, not a product failure or pass.
- D-007: Per operator instruction, use no arkcli. Independent maintenance
  review is fresh-context Claude Code only.
