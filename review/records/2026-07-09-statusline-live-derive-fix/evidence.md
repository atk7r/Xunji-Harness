# Evidence

## E-001 — active diff

- Artifacts: `evidence/active-diff.txt`

## E-002 — focused selftests passed

- Command: `python3 tools/selftest_all.py --only xunji_statusline,loop_state,run_controller,loop_bootstrap --timeout 300`
- Result: 4 passed, 0 failed.
- Artifacts: `evidence/selftest-log.txt`

## E-003 — hamastar active statusline corrected

- Command: `python3 tools/xunji_statusline.py`
- Result: `[Xunji-status] [Root｜调度] hamastar_20260709 | 现场推导 | 待验证入口 5 个 | 无子任务 | 阻断 3 个 | 下一步 分派子任务`
- Artifacts: `evidence/statusline-log.txt`

## E-004 — staged diff check passed

- Command: `git diff --cached --check`
- Result: exit 0.
- Artifacts: `evidence/diff-check-log.txt`
