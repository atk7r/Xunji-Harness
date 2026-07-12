# Review Decisions

## D-001

- Decision: Treat this as Codex-authored safety-critical maintenance.
- Rationale: the diff changes `.claude/hooks/safety_gate.py`, `tools/harness/guard.py`, replay closure behavior, browser/probe/scan request paths, and sentinel cross-layer tests.
- Required review: arkcli panel plus fresh-context Claude Code when available; Codex self-review is not an independent vote.
- Status: final-reviewed; no-unresolved-blocker

## D-002

- Decision: accept PR-004 as a real fail-closed coverage defect.
- Resolution: when `privacy.py` cannot import, every URL-bearing Bash action fails closed. With the module available, guarded framework tools use per-request validation; URL-bearing custom Python/shell scripts remain denied for driver auto-execution even if their source/command mentions a validation function, and hidden-destination custom network code is author-and-handoff.
- Evidence: final frozen `reviewed.diff` plus the final-8 arkcli/fresh-context-Claude independent review; selftests remain candidate regression context only.
- Status: fixed-and-reviewed
