# Driver Disposition - Claude CLI Peer Review Backend

- Verdict: WARN
- Time: 2026-07-08
- Author: Codex
- diff_fingerprint: 2b601230a1b99784
- reviewed_diff: 2b601230a1b99784
- Review scope: `review/records/2026-07-08-optimization-plan-review/`
- Arkcli review: `review/records/2026-07-08-optimization-plan-review/arkcli-review.md`
- Claude Code CLI review: `review/records/2026-07-08-optimization-plan-review/claude-cli-review.md`

## Disposition

The operator corrected the intended reviewer boundary: the Claude reviewer should
be invoked through Claude Code CLI, not by direct Anthropic API calls from
`tools/peer_review.py`.

Resolution:

- `tools/peer_review.py` now defines the Claude backend as `claude-code-cli`.
- The backend invokes `claude -p --output-format json --no-session-persistence`
  and parses the CLI JSON `result`.
- The Codex-authored review matrix still treats Claude as independent from Codex,
  while same-family Claude remains a weak fallback for Claude-driven work.
- `tools/check_run.py` and Codex-side review skills now say `Claude Code CLI`
  instead of `Claude Code/API`.
- The optimization plan review was rerun with the direct Claude Code CLI backend;
  the result was WARN and is saved in the review scope above.

## Accepted Review Warnings

- Canary acceptance must measure outcome or consumption, not only field presence.
  The optimized plan now requires a linked action, E-id, constraint/refutation,
  certainty upgrade, or finding.
- Agent/Root behavior changes must land in `.claude/skills/` and shared
  templates/tools first because Claude Code is the primary live driver. Codex-side
  `.agents/skills/` changes are only advisory or explicit mirrors.
- `events.jsonl` v2 remains deferred until v1 consumers are verified.

## Verification

- `python3 tools/peer_review.py --selftest`
- `python3 tools/check_run.py --selftest`
- `python3 tools/selftest_all.py --only peer_review`
- `python3 -m py_compile tools/peer_review.py tools/check_run.py`
- `git diff --check`
