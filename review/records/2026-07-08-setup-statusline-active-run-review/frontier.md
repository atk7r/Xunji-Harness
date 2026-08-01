# Review Fronts

## F-001 Setup Active-Run Linkage

- Status: closed
- Question: Does `setup_run.py` set `.claude/xunji_active_run` after creating a new run skeleton?
- Expected check: Verify `tools/setup_run.py` calls `xunji_statusline.set_active_run()` only after `scaffold(run_dir)` succeeds.

## F-002 Boundary Preservation

- Status: closed
- Question: Does the change preserve setup boundaries: no `/loop` entry, no front selection, no evidence or closure decision?
- Expected check: Verify the active-run pointer is local display state only and failures are best-effort warnings.

## F-003 Regression Coverage

- Status: closed
- Question: Is there a focused selftest proving setup writes and restores the active-run pointer?
- Expected check: Verify `tools/setup_run.py --selftest` covers the active pointer and restores any pre-existing pointer.

## F-004 Documentation Consistency

- Status: closed
- Question: Do Claude primary-driver docs and skills say setup now updates the statusline pointer?
- Expected check: Verify `.claude/skills/*` and `docs/WORKFLOW.md` no longer claim only loop bootstrap or `/loop` update the pointer.
