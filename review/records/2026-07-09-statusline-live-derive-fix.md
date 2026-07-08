# Statusline Live-Derive Fix Review Disposition

- Verdict: WARN
- diff_fingerprint: eac82310e9b80645
- reviewed_diff: eac82310e9b80645
- Review record: `review/records/2026-07-09-statusline-live-derive-fix/`

## Disposition

Accepted as a narrow statusline fix. The bug was that `xunji_statusline.py`
defaulted to cached `loop_state.json` / `controller.shadow.json`; when caches were
missing or stale, it rendered false `Idle｜空闲`, zero fronts, and no blockers.

The fix keeps statusline read-only but derives `loop_state` and `run_controller`
in memory when caches are missing or stale. It also ignores setup/bootstrap
`phase_end` journal notes like `run prepared`, so stale setup text does not mask
the controller-required action.

Claude Code CLI review returned WARN. All concrete findings were accepted:

- PR-001: added saved command-output artifacts under the review scope.
- PR-002: changed setup-note suppression to use structured journal phase
  `data.phase == Setup`; the English string filter remains only as compatibility
  fallback.
- PR-003: live derivation failure now renders `推导失败` instead of silently
  degrading to the old false-idle path, and selftest covers that branch.

Final Claude Code CLI review returned WARN with no concrete findings. Residual
blind spots are accepted dependency-contract risks, not current blockers.

Verification after these fixes:

- `python3 tools/selftest_all.py --only xunji_statusline,loop_state,run_controller,loop_bootstrap --timeout 300` -> 4/4 passed.
- `python3 tools/xunji_statusline.py` on `runs/hamastar_20260709` now renders `Root｜调度`, 5 open fronts, 3 blockers, and next action `分派子任务`.
- `git diff --cached --check` passed.

Residual risk: live derivation is more expensive than cached reads, but it only
runs when caches are missing/stale and does not write run state.
