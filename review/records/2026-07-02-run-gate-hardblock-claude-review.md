# Independent Review — run_gate hard-block anti-loop removal

- **Date**: 2026-07-02
- **Reviewer**: Claude Code (`claude -p --model opus --effort high`)
- **Subject**: `.claude/hooks/run_gate.py`, `.codex/hooks/run_gate.py`, `.codex/hooks/output_gate.py`
- **Why**: safety-critical Stop hook behavior change after `cqytxy_20260702` showed that reminder-only and `stop_hook_active -> notify` downgrade let hard gates be bypassed.

## Change

Objective hard gates now continue to emit `decision=block` even when the Stop event has `stop_hook_active=true`.

Hard gates covered:
- `check_run` closure gate
- Phase 4 evidence severity gate
- Phase 2 session timeout gate
- Phase 6 replay-quality gate
- Phase 5 Agent Board gate
- Normal-mode `CodexCompletionReview` gate

Phase 3 drift remains `systemMessage` only because it is advisory.

The Codex hook copy was synced from the Claude hook copy. `.codex/` and `.Codex/` are hard-linked on this checkout, so the runtime Codex hook path sees the same content.

## Claude Code Verdict

**APPROVED**.

Claude Code verified that every hard-gate path now blocks without consulting `stop_hook_active`, and that the remaining `systemMessage` paths are advisory-only.

Second review also verified the Phase 6 replay-quality fix:
- `_check_replay_quality()` now reuses `evidence_parse.parse_evidence(run_dir)`.
- It gates only confirmed `E-*` records.
- It requires a real existing artifact in `artifacts_present` ending in `.replay.json`.
- Import or parse failure remains fail-open.

## Findings

| Severity | Finding | Disposition |
|---|---|---|
| LOW | Phase 6 code appears before Phase 5 in `main()`. | Accepted. Independent block-and-exit gates; ordering has no behavioral impact. |
| LOW | `decide()` keeps an unused `stop_hook_active` parameter. | Accepted. Preserves call/test API and makes the regression assertion explicit. |

## Fixes After First Review

First Claude Code review approved the hard-block change but noted that Phase 6 had no dedicated selftest and used a broad raw-string `.replay.json` check. That was fixed before final approval:
- Added replay-quality selftests for confirmed without replay, existing replay, prose mention not counting, missing replay file, and low-certainty pass.
- Replaced raw block string matching with structured `artifacts_present` checking.

## Validation

- `python3 .claude/hooks/run_gate.py --selftest` -> passed
- `python3 .codex/hooks/run_gate.py --selftest` -> passed
- `python3 .codex/hooks/output_gate.py --selftest` -> passed
- `python3 .codex/hooks/safety_gate.py --selftest` -> healthy
- `python3 tools/selftest_all.py --only run_gate,check_hook,check_run,safety_gate,output_gate` -> 5 passed, 0 failed
- `python3 tools/check_hook.py` -> passed
- `python3 tools/check_rules.py` -> passed
- `python3 tools/check_run.py --selftest` -> passed

## Conclusion

Approved for use. The hard gates no longer degrade to reminder-only behavior, while fail-open handling for hook/tooling failures remains intact.
