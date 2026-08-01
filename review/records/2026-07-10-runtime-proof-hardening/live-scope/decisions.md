# Decisions

- Treat a missing requested tool call as an inconclusive harness failure, not an enforcement failure.
- Require real PreToolUse/PostToolUse/Stop events and state effects for PASS.
- Require Cron cleanup and a final quiescent List so no scheduler fixture remains.
