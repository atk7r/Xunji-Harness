# Primary Driver Documentation Review Scope

- Status: REVIEW
- Author: Codex
- Kind: framework maintenance
- Evidence IDs: E-001

This scope asks whether Claude-facing prose still teaches or permits the exact
shortcuts observed in the historical sessions. Documentation is not treated as
proof of enforcement; it is checked for parity with the separately reviewed
hooks and state machines. `historical_failures.md` maps six observed shortcuts
to both prose changes and mechanical controls. `stale_reference_audit.json`
hashes the complete `docs/`, primary skill, root-rule, and legacy-review Markdown
inventory and fails generation if a mapped historical shortcut remains. It is a
regression for known patterns, not a proof that novel future wording cannot drift.
No network target or vulnerability claim is involved.
