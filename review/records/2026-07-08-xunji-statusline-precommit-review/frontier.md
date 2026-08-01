# Frontier

## F-001 — Claude Code Project Statusline

- Status: open-for-review
- Goal: Add a concise Chinese statusline driven by Claude Code's project `statusLine` command.
- Expected behavior: show current phase, active run, pending verification entries, aggregated subagent state, blockers, and next action.
- Boundary: display-only. The renderer reads derived state and the active run pointer, but does not update evidence, refresh loop state, or enforce workflow gates.

## F-002 — Xunji-Only Activation

- Status: open-for-review
- Goal: Prevent status output outside this Xunji checkout.
- Expected behavior: the renderer returns no line if Claude Code's `workspace.current_dir` is not under the repository root.
- Boundary: an active run pointer is accepted only when the run directory resolves under the Xunji root and looks like a run directory.

## F-003 — Loop Lifecycle Integration

- Status: open-for-review
- Goal: Keep the active run pointer current when a run is bootstrapped, resumed, or entered by `/loop`.
- Expected behavior: `loop_bootstrap.py` sets the pointer best-effort; the fixed `/loop` template sets it at journal start.
- Boundary: pointer failure is visible but non-blocking because it is local display state only.

## F-004 — Regression Coverage

- Status: open-for-review
- Goal: Add selftest coverage for the new renderer and include it in `selftest_all.py`.
- Expected behavior: tests cover readable Chinese output, ANSI color support, subagent aggregation, next-action text, and project-outside silence.
