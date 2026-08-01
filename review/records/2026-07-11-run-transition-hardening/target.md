# Target

- Target: Xunji Claude Code run-transition and Stop-hook maintenance diff
- Authorization: local repository maintenance only
- Driver: Codex
- Independent reviewers required: arkcli panel and Claude Code CLI
- No live target traffic: yes

## Review Questions

1. Can setup/resume/set-active still be used to evade an existing run's Agent Board or unresolved denial?
2. Can pending or transferred contracts cross sessions, bind the wrong run, remain stale, or be forged by Claude tools?
3. Does `stop_hook_active` handling prevent churn without falsely changing canonical completion state?
4. Is every documented lifecycle command executable while target actions remain constrained?

