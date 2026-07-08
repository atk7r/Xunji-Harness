# Independent Review - drift gate tightening

- **Date**: 2026-07-03
- **Reviewer**: Claude Code (`claude -p --permission-mode dontAsk --model opus --effort high`)
- **Subject**: `.claude/hooks/output_gate.py`, `.claude/hooks/run_gate.py`, `.claude/settings.json`
- **Why**: safety-critical Stop hook behavior change to tighten repeated drift handling while preserving advisory detection and fail-open parsing.

## Change

`output_gate` remains advisory only:
- Detects drift.
- Writes `session_state.json`.
- Maintains consecutive `drift_block_count`.
- Adds `drift_started_at` to preserve the age of an unresolved drift streak.
- Emits only `systemMessage`, never `decision=block`.

`run_gate` now escalates repeated protocol/autonomy drift:
- `protocol_violation` or `option_list` with `drift_block_count == 1` -> `systemMessage`.
- `protocol_violation` or `option_list` with `drift_block_count >= 2` -> `decision=block`, requiring reread and protocol-correct output.
- `protocol_violation` or `option_list` with `drift_block_count >= 4` -> `decision=block`, requiring `session_handoff.md` and session restart.
- `frontier_stale` alone remains advisory, even at high count.
- Phase 2 timeout is now 30 minutes and uses `drift_started_at` when present, so running `output_gate` first does not reset the unresolved-drift clock.
- Phase 2 has its own long candidate window (`DRIFT_TIMEOUT_WINDOW_SEC = 6h`) so a run that is already older than the ordinary 15-minute active window can still be blocked when unresolved drift has lasted over 30 minutes.

Stop hook order was changed to `output_gate` before `run_gate`, matching the state-write/state-read design.

The local Codex hook copy was synced from the Claude hook copy. `.codex/` and `.Codex/` are local runtime copies on this checkout, so the runtime Codex hook path sees the same content.

## Claude Code Verdict

**APPROVED**.

Claude Code confirmed:
- `output_gate` is still fully soft and never blocks.
- `run_gate` Phase 3 hard-blocks only repeated `protocol_violation` / `option_list`.
- `frontier_stale` alone stays notify-only.
- The Stop hook order change is correct.
- `drift_started_at` preserves Phase 2 timeout semantics after the order change.
- Dev mode still skips run_gate Phase 3 interruption while output_gate warnings remain visible.
- Fail-open behavior for malformed or missing state remains.
- No bypasses were found in hook order, dev mode, mixed flags, malformed state, or threshold logic.

## Claude Code Final Re-review

After the Phase 2 active-window fix, Claude Code re-reviewed the final state and returned **APPROVED** again.

Final re-review confirmed:
- `output_gate` remains soft-only and writes `drift_block_count` plus `drift_started_at`.
- Stop order is `output_gate` then `run_gate`.
- Phase 3 count 1 notifies, count >=2 blocks for `protocol_violation` / `option_list`, and count >=4 requires `session_handoff.md`.
- `frontier_stale` alone remains notify-only.
- Phase 2 uses the 30-minute timeout, prioritizes `drift_started_at`, and uses the 6-hour fallback window only for unresolved drift timeout checks.
- Other run_gate phases still use the ordinary 15-minute active-run window.
- Fail-open behavior remains for malformed or missing state.

The only final observation was non-defect behavior: when there is no active run, `output_gate` can still emit a warning but does not persist per-run drift count, which is expected because the count is run-scoped.

## Review Findings

| Severity | Finding | Disposition |
|---|---|---|
| LOW | `output_gate` used the anti-drift default active window while `run_gate` used a 15-minute active window, so the 30-minute Phase 2 timeout could miss runs in the 15-minute to 6-hour gap. | Fixed. Phase 2 now uses `DRIFT_TIMEOUT_WINDOW_SEC = 6h`; ordinary active-run gates still use the narrow 15-minute window. Added selftest `session timeout: >15m drift candidate still blocks`. |
| INFO | `drift_started_at or max(updated_at, sf_mtime)` relies on the invariant that non-empty `drift_flags` are checked first. | Accepted. Current invariant is explicit and covered by stale/empty-drift selftests. |
| INFO | If notification printing failed after state write, fail-open behavior would leave state persisted without immediate user feedback. | Accepted by design. The next hook cycle sees persisted state. |

## Validation

- `python3 .claude/hooks/output_gate.py --selftest` -> passed
- `python3 .claude/hooks/run_gate.py --selftest` -> passed
- `python3 .codex/hooks/output_gate.py --selftest && python3 .codex/hooks/run_gate.py --selftest` -> passed
- `python3 tools/selftest_all.py --only output_gate,run_gate,check_hook,check_run,safety_gate` -> 5 passed, 0 failed
- `python3 tools/check_hook.py` -> passed
- `python3 tools/check_rules.py` -> passed
- `python3 tools/check_run.py --selftest` -> passed
- JSON syntax for `.claude/settings.json` and `.codex/hooks.json` -> ok
- Stop hook order assertion for `.claude/settings.json` and `.codex/hooks.json` -> output_gate before run_gate
- `.claude` and `.codex` hook copies for `output_gate.py` and `run_gate.py` -> identical

## Conclusion

Approved for use. Drift handling is now tighter: repeated protocol/autonomy drift blocks on the second consecutive violation, handoff is required on the fourth, unresolved drift times out after 30 minutes, and purely stale-frontier reminders remain soft.
