# Decisions

- Treat this as safety-critical Claude-primary maintenance because it changes `.claude/hooks/` and PreToolUse control behavior.
- Do not count Codex self-review as independent.
- Lifecycle commands may bypass an old run's fan-out only when they are exact in-repository commands and current operator intent authorizes the run transition.
- Direct pointer/pending/runtime writes remain denied even when no active run exists.
- A Stop retry may end the chat turn, but it must not write completion state, close fronts, or change `check_run` results.
- Any accepted reviewer finding requires code/test repair and a refreshed review bundle.

