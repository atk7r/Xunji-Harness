# Decisions

- D-001: Codex will not mark `runs/scshr_20260708` complete. The referenced run remains Claude primary-driver source of truth; this maintenance diff only fixes the framework/tooling failure modes and exposes the remaining loop state.
- D-002: No `--replay-verify` was run because it performs live GET replay; the current task is repository maintenance, not live target closure.
- D-003: Final commit requires full selftest, safety-boundary checks, `git diff --cached --check`, and independent review disposition.
- D-004: Arkcli panel failure is a recorded limitation for this Codex-authored maintenance review; final independent review falls back to Claude Code CLI per the no-arkcli row of the review matrix.
