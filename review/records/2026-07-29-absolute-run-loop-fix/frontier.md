# Frontier

## F-001 — absolute existing-run token with attached prose

- Status: closed
- Evidence: E-001, E-002, E-003, E-004
- Resolution: the attached description is stripped only after the remaining lexical
  source resolves into the repository's authoritative `runs/` root.

## F-002 — authority expansion outside the repository

- Status: closed
- Evidence: E-001, E-002
- Resolution: a same-shaped foreign absolute path remains a file source and cannot
  mint run authority.

## F-003 — Claude client scheduler interaction

- Status: closed
- Evidence: E-004
- Resolution: Claude Code 2.1.201 expanded `/loop` as a client skill, but the
  original prompt still reached UserPromptSubmit before any effect. Xunji injected
  the exact resume adapter; the transcript contains no CronCreate and the typed
  resume committed successfully.
