# Decisions

- D-001: Do not make statusline write `loop_state.json` or `controller.shadow.json`; preserve read-only rendering.
- D-002: Use live in-memory derivation only when caches are missing/stale.
- D-003: Treat setup/bootstrap journal notes as stale display text, not next action.
