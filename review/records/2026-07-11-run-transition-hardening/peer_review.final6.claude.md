# Peer Review — 2026-07-11-run-transition-hardening

_backend: claude:code-cli · 2026-07-11T03:02Z_
> 候选, 非裁决。driver 须逐条过证据门: 不盲从(驳工具/语境误报), 不忽视(采纳真盲补)。

## Verdict: WARN

_backend: claude:code-cli_  
_brain: codex_  
_bundle_hash: b9bf19894a208d85525f9878db5a44e3aef72e4d_  
_evidence_index_hash: 6b6c926bdfd37169f824dbdc41fd8334d8e65cf4_  

## Findings
- [WARN] PR-001 `_lifecycle_target_name` `--resume` branch has no direct selftest | Evidence: `turn_contract.py` _selftest in transition-core.diff lines 880-895 — tests only setup_run.py tuples | Why: Regression in resume argument parsing would not be caught by selftest suite
- [WARN] PR-002 `run_gate.py` early-return on `stop_hook_active` masks independent co-occurring gate failures | Evidence: `run_gate.py` diff line 276-277 (`if stop_active: sys.exit(0)`) in stop-hooks.diff | Why: Operator loses diagnostic visibility when multiple gates fail simultaneously; only the first blocking hook's reason is surfaced
- [WARN] PR-003 `_denied_result_claim_reason` depends on unguarded external function `_active_protocol_fronts` | Evidence: `output_gate.py` diff lines 24-25 in stop-hooks.diff | Why: If `_active_protocol_fronts` returns empty list for a run with active fronts, the denial gate silently falls back to `frontier.md` anchor
- [WARN] PR-004 Pending-bootstrap tool allowlist test coverage is single-point (only `probe.py`) | Evidence: `turn_contract.py` subprocess tests in transition-core.diff lines 968-978 | Why: The `tool not in {...}` gate at line 811 is tested for only one denied tool; regression in the allowlist set may not be caught

## Blind-spot check
- Cross-session pending contract collision if Claude Code reuses session IDs across processes
- Date-boundary race: `_lifecycle_target_name` and tool execution compute run-name dates independently; midnight crossing causes fail-closed mismatch
- `CLEAR_ACTIVE_RE` regex greediness: ambiguous operator prompts like "clear evidence and restart the active run" could inadvertently authorize clear-active
- `_control_invocation` accepts bare `python` without version check — deployment risk on systems where `python` ≠ Python 3
- Selftest for `_lifecycle_target_name` covers setup_run.py paths thoroughly but misses `loop_bootstrap.py --resume` and `xunji_statusline.py --set-active` tuples directly

## Context-limit notes
- All analysis based on diff artifacts in review bundle; live working tree not accessible for cross-check
- `_active_protocol_fronts` function not shown in any diff — assumed correct based on selftest assertions
- One token redacted by egress filter at turn_contract.py line 473 — does not affect findings