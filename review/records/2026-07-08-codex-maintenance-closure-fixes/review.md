# Codex Maintenance Review - Closure Fixes

- Author: Codex
- Scope: working-tree diff for closed-loop repair work on 2026-07-08
- Review matrix required: arkcli panel + Claude Code fresh-context/API
- Synthesis owner: Codex

## arkcli Panel Attempt

- Backend: arkcli +chat, model `kimi-k2.7-code`
- Result: limitation recorded
- Evidence:
  - `arkcli auth status` passed with active SSO/API key.
  - `arkcli +chat --input @/tmp/xunji-codex-maintenance.diff ...` failed with `unsupported_input_modality` because the active agent-plan profile does not support document/file input.
  - Retried as pure text prompt with the diff embedded; command was manually interrupted after more than five minutes with no output.
- Disposition: no arkcli review vote. This is recorded as the missing arkcli-panel limitation.

## Claude Fresh-Context Review

- Backend: `claude -p --permission-mode dontAsk --tools ""`
- Input: `/tmp/xunji-codex-maintenance.diff` embedded in stdin prompt
- Verdict: WARN

Findings and resolution:

- HIGH false positive: `_append_manual_driver_template` called `_strip_template_review_placeholders`, which already existed in `tools/peer_review.py`; covered by `tools/peer_review.py --selftest`.
- HIGH false positive: `check_loop_state_closure_blockers` called `_closure_gate_active`, which already existed in `tools/check_run.py`; covered by `tools/check_run.py --selftest`.
- MEDIUM accepted: `check_loop_state_closure_blockers` silently returned no blockers if `loop_state` import failed. Fixed to fail closed during closure-gate-active runs.
- MEDIUM accepted: `SessionStateManager.save` deleted legacy root `session_state.json` after writing `state/session_state.json`. Fixed to keep legacy as compatibility backup while reads prefer `state/`.
- LOW accepted: `probe.py` surfaced raw JSON decode errors through a broad exception. Fixed with explicit `json.JSONDecodeError` handling and selftest coverage.
- LOW noted: duplicate fallback `SessionStateManager` stub remains in `run_gate.py` for fail-open import fallback. This is intentional hook resilience; the authoritative implementation is `tools/anti_drift.py`.

## Verification

- `python3 tools/selftest_all.py` -> 53 passed, 0 failed.
- `python3 tools/check_run.py runs/scshr_20260708` -> passed with non-blocking coverage/lump warning.
- `python3 tools/loop_state.py runs/scshr_20260708 --write` -> 0 closure blockers.
- `python3 tools/run_controller.py runs/scshr_20260708 --shadow` -> closure-candidate/needs-pivot advisory, 0 stop blockers.
