# Statusline Live-Derive Fix

## Problem

`tools/xunji_statusline.py` used cached `state/loop_state.json` and
`state/controller.shadow.json`. For `runs/hamastar_20260709`, those caches were
missing/stale while Markdown files had advanced, so statusline showed:

- `Idle｜空闲`
- `待验证入口 0 个`
- `无阻断`
- stale setup next action text: `run prepared...`

## Fix

- When caches are missing or stale, derive `loop_state` and `run_controller`
  in memory with write disabled.
- Keep normal statusline rendering read-only.
- Show `现场推导` when live fallback is used.
- Ignore structured Setup `phase_start` / `phase_end` journal notes as
  next-action candidates, so controller-required action is visible.
- Render `推导失败` if read-only live derivation fails, instead of silently
  returning to false idle/zero-front output.

## Verification

- `python3 tools/selftest_all.py --only xunji_statusline,loop_state,run_controller,loop_bootstrap --timeout 300` -> passed.
- `python3 tools/xunji_statusline.py` on active `runs/hamastar_20260709` -> `[Root｜调度] ... 待验证入口 5 个 ... 阻断 3 个 ... 下一步 分派子任务`.
- `git diff --check` -> passed.
