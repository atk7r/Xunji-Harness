# Agent Asset Runtime Hardening Final Review

Verdict: WARN
diff_fingerprint: db15f519bb135bd4
reviewed_diff: db15f519bb135bd4

Author: Codex
Date: 2026-07-12
Base commit: `d0584a6`
Review record: `review/records/2026-07-12-agent-asset-runtime-hardening/`

## Independent Review

- Multiple fresh-context Claude Code reviews completed; the final current-hash
  fallback returned WARN with no formal findings.
- Final reviewed bundle hash: `0b06d9b4f8d6be88582cc65227ae74c37f319112`.
- Final evidence-index hash: `e2418ad2d234670d5232469bc1e017d43245a47d`.
- Arkcli was limited to the required defaults `kimi-k2.7-code` and `glm-5.2`.
  Earlier Kimi votes identified and helped fix the unknown-destination proxy
  bypass and several lifecycle hardening gaps. On the final hash Kimi timed out
  and GLM failed strict parsing, so arkcli is recorded as unavailable, not PASS.
- Every formal finding and actionable WARN from prior rounds is dispositioned in
  `disposition.md`; accepted issues were fixed and re-reviewed.

## Verification

- `python3 tools/selftest_all.py` -> 57 passed, 0 failed.
- `python3 tools/bench.py score-all bench` -> 18/18 fixtures clean, 100%
  detection/calibration, zero false positives.
- `python3 tools/check_rules.py`, `python3 tools/check_hook.py`, Python compile,
  narrow runtime/turn/worker tests, and `git diff --check` passed.
- Regression coverage includes async launch vs SubagentStop ordering, delayed
  reverse lifecycle events, exact assignment/front/assets binding, zero/partial
  asset merge rejection, unknown target and non-Bash egress denial, turn-scoped
  direct-egress approval, corrupt/forged asset state, and schema-v1 migration.

## Residual Limits

- No live Claude-primary Agent smoke was spawned by this Codex maintenance task;
  observed payload shapes and timing orders are replayed deterministically instead.
- GLM did not emit a valid structured vote in any final attempt; the raw failures
  and useful partial reasoning remain in the review directory.
- Static command/destination analysis is intentionally conservative and may need
  extension if Claude Code adds new network-capable tool categories or payload
  schemas.
