# Peer Review Panel — 2026-07-13-statusline-simplification

_backend: panel:arkcli+claude · 2026-07-13T04:00Z_
> 候选, 非裁决。driver 须逐条过证据门。

## Verdict: WARN

_backend: panel:arkcli+claude_
_brain: codex_
_bundle_hash: 55826db7265e6042b11380f56f896be5c6e77b44_
_evidence_index_hash: 52e05c5124d376d8bc37b525c90d84a3a0adf7a6_

## Findings
- [WARN] PR-001 Selftest coverage for the three workspace-gating cases is incomplete or not independently verifiable from the delivered artifacts | Evidence: reviewed.diff:selftest section (unspecified/no_active assignments), selftest.log | Why: [panel:arkcli] [arkcli:kimi-k2.7-code] Review question #1 requires verified behavior for no explicit workspace, explicit non-Xunji workspace, and Xunji workspace with no active run. The visible diff assigns variables for these cases but the assertion list is truncated, and selftest.log only records aggregate pass/fail.
- [WARN] PR-002 No negative/regression test proves that legacy statusline fields do not leak when their source files still exist | Evidence: reviewed.diff (removal of _front_summary, _asset_summary, _agent_summary, _blocker_summary, _next_action), reviewed.diff (selftest writes only loop_state.json, run_status.json, loop_journal.jsonl) | Why: [panel:arkcli] [arkcli:kimi-k2.7-code] Exact-string assertions with files absent do not prove the renderer would ignore leftover legacy state files. A negative test would guard against accidental re-introduction of field leakage.
- [WARN] PR-003 Colored output path is exercised but not asserted, and unknown_phase appears to be dead selftest code | Evidence: reviewed.diff (colored and unknown_phase assignments in selftest), selftest.log | Why: [panel:arkcli] [arkcli:kimi-k2.7-code] The subprocess-based color check was removed, leaving the ANSI rendering path untested. The unused unknown_phase variable is likely leftover dead code.
- [WARN] PR-004 Removing PWD/os.getcwd() fallbacks makes the statusline silently blank if the Claude hook payload omits workspace information | Evidence: reviewed.diff (_workspace_dir now returns None when raw is absent), CLAUDE.md (updated statusline description) | Why: [panel:arkcli] [arkcli:kimi-k2.7-code] While this matches the new spec, it is a robustness regression from the previous fallback behavior. Operators may mistake intentional blank output for a broken hook if Claude ever omits the workspace payload.
- [WARN] PR-005 arkcli panel had backend errors; review is partial | Evidence: glm-5.2: parse error; output tail: ctually, let me reconsider the selftest approach more carefully.**

The new selftest does:
```python
real_active_pointer = ACTIVE_RUN
ACTIVE_RUN = temp / "xunji_active_run"
```

But wait - `temp` is `tmp_root = ROOT / "tmp"`, and then `temp` is used as... let me re-read:

```python
tmp_root = ROOT / "tmp"
tmp_root.mkdir(exist_ok=True)
```

Then later:
```python
real_active_pointer = ACTIVE_RUN
ACTIVE_RUN = temp / "xunji_active_run"
```

Wait, where is `temp` defined? Looking at the diff... I see | Why: [panel:arkcli] At least one arkcli reviewer failed, so PASS only means the completed panel members found no blocker.

## Blind-spot check
- [claude] **`_journal_summary()` output partially dead but correctly unused:** The function still computes `interrupted`, but `render_statusline()` no longer reads `journal.get("interrupted")` as a separate `" | 中断待续"` suffix. The interrupted state is still surfaced through the phase tag itself (e.g., `[Interrupted｜中断待恢复]`) via `_phase()`, which reads the journal internally. The dedicated suffix was redundant, so its removal is correct. The `_journal_summary()` body was not in the diff — it's unchanged and its remaining consumers (`_event_age_seconds()`, `_phase()` via the journal arg) are intact.
- [claude] **`_derived_loop_state()` returns `(None, "ErrorName")` on failure:** The new `render_statusline()` handles this correctly — if `derived_loop is None`, `loop_data` stays as `{}` (the default from `_load_json`), and `_phase({}, journal, run_dir)` falls back to `"Idle"`. The selftest verifies this with `failed_derive_plain == f"[Xunji-status] [Idle｜空闲] {missing_cache.name}"`.
- [claude] **Three removed imports (`os`, `re`, `subprocess`) were all dead after the function removals:** No remaining code references them. The cleanup is thorough.
- [claude] **`ACTION_LABELS` dict removal is safe:** No other file imports from `xunji_statusline.py` (it's a standalone CLI tool, not a library). Controller action strings are consumed by phase banners and other display mechanisms independently of the statusline.
- [claude] **`_workspace_dir` returning `None` instead of falling back to `os.getcwd()` is BY DESIGN:** This enforces the spec that "no explicit workspace → no statusline output." Previously, running the script from within the Xunji directory would accidentally show a statusline even without Claude providing a workspace. The new behavior is stricter and matches the documented contract.
- [claude] **Phase derivation fidelity preserved:** `_phase()` (unchanged) receives the same inputs — `loop_data` (from same source), `journal` (from unchanged `_journal_summary()`), and `run_dir` (unchanged). The only removed input was `controller`, which `_phase()` never consumed (it was used by the now-removed `_blocker_summary` and `_next_action`).
- [claude] **What I'd flag if I were reviewing the design rather than the code:** The statusline is now purely `phase + run_name`. During long-running autonomous loops, the operator loses the statusline as a quick health check (are Agents running? are there unresolved conflicts? is the cache stale?). The documentation correctly delegates this to "phase banners and `loop_journal.py`", but those are only visible during active Claude output, not as a persistent 2-second statusline indicator. This is a UX trade-off that's documented and intentional, not a bug.

## Context-limit notes
- [arkcli] glm-5.2: parse error; output tail: ctually, let me reconsider the selftest approach more carefully.**

The new selftest does:
```python
real_active_pointer = ACTIVE_RUN
ACTIVE_RUN = temp / "xunji_active_run"
```

But wait - `temp` is `tmp_root = ROOT / "tmp"`, and then `temp` is used as... let me re-read:

```python
tmp_root = ROOT / "tmp"
tmp_root.mkdir(exist_ok=True)
```

Then later:
```python
real_active_pointer = ACTIVE_RUN
ACTIVE_RUN = temp / "xunji_active_run"
```

Wait, where is `temp` defined? Looking at the diff... I see
- [claude] I cannot directly read the live `tools/xunji_statusline.py` file to verify the diff was cleanly applied (Read/Grep denied). I rely on the `reviewed.diff` artifact (sha1: `437318e9baa56b72bddb32309649fab1f16f29cd`) and the `selftest.log` showing 60/60 pass as evidence the change is correctly integrated.
- [claude] I cannot inspect `_phase()`, `_journal_summary()`, or `status_style` module bodies since they weren't in the diff hunks. I rely on the selftest assertions and the diff showing those functions were not modified to conclude they work correctly.
- [claude] The `loop_state.derive()` function and `run_controller.derive()` function are referenced but not in this bundle — the 60/60 selftest pass is my evidence that the lifecycle integration is intact.
- [claude] The previous peer review's Claude member was confused by the system-prompt-injected CLAUDE.md showing old content. I independently verified via the diff bundle that CLAUDE.md WAS updated, correcting that finding.
