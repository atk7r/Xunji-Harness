# Review Scope

Codex authored a maintenance change to the Claude-primary Xunji statusline.

Review questions:

1. Does the implementation print nothing when the Claude payload does not explicitly identify a workspace, when the workspace is outside Xunji, or when no active run is selected?
2. With an active Xunji run, is the output limited to `[Xunji-status] [<phase>] <run>`?
3. Does phase derivation remain read-only and preserve setup, paused, interrupted, cached, and fallback behavior without unnecessary controller, Agent, coverage, blocker, or next-action work?
4. Do the selftests materially cover the changed behavior without mutating the operator's persistent active-run pointer?
5. Are the Claude-primary skill and shared documentation consistent with the code?

Do not evaluate live pentest evidence; this is repository maintenance only.
