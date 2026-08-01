# Evidence Ledger

## E-001

- Maturity: finding
- Reportable: no
- Time: 2026-07-08T11:17:46Z
- Action: Implemented automatic active-run pointer update in `setup_run.py`.
- Source: repository diff
- Result: `setup_run.py` imports `xunji_statusline`, adds `_set_active_run(run_dir)`, and calls it after successful run skeleton creation.
- Control: The helper is best-effort and uses `xunji_statusline.set_active_run()` validation instead of writing the pointer directly.
- Caused by us: yes
- Alternative explanation: A future manual setup path outside `setup_run.py` could still skip the pointer; this diff fixes the one-shot setup path.
- Certainty: 0.8
- Artifacts: evidence/final3-diff.txt
- Supports: F-001, F-002
- Next: Independent review should verify the call site is late enough that invalid or partially-created run directories are not selected.

## E-002

- Maturity: finding
- Reportable: no
- Time: 2026-07-08T11:17:46Z
- Action: Added regression coverage for active-run pointer writing and restoration.
- Source: local command output
- Result: `tools/setup_run.py --selftest`, `tools/xunji_statusline.py --selftest`, `tools/check_rules.py`, and selected `selftest_all.py` suites passed.
- Control: The selftest stores any existing `.claude/xunji_active_run`, points at a temporary run under repo `tmp/`, asserts `active_run()` resolves that run, then restores the old pointer.
- Caused by us: yes
- Alternative explanation: The test does not invoke Claude Code's proprietary statusline renderer; it verifies the repository-side pointer and renderer contract.
- Certainty: 0.8
- Artifacts: evidence/final3-test-log.txt, evidence/final3-diff.txt
- Supports: F-003
- Next: Independent review should check whether the selftest can accidentally leave a temporary pointer behind.

## E-003

- Maturity: finding
- Reportable: no
- Time: 2026-07-08T11:17:46Z
- Action: Updated Claude primary-driver lifecycle and setup documentation.
- Source: repository diff
- Result: `docs/WORKFLOW.md`, `.claude/skills/xunji-run-lifecycle/SKILL.md`, and `.claude/skills/xunji-setup-ingest/SKILL.md` now state that `setup_run.py` updates the active-run pointer as local display state.
- Control: Documentation explicitly says this does not enter `/loop`, choose a front, or make evidence/closure decisions.
- Caused by us: yes
- Alternative explanation: Codex-side `.agents/skills` may still omit this detail, but the requested behavior is Claude primary-driver behavior.
- Certainty: 0.8
- Artifacts: evidence/final3-diff.txt
- Supports: F-002, F-004
- Next: Independent review should verify the docs no longer contradict the implementation.

## E-004

- Maturity: finding
- Reportable: no
- Time: 2026-07-08T11:30:00Z
- Action: Fixed independent review WARN about selftest mutating the real active-run pointer and leaking temp directories.
- Source: repository diff
- Result: The selftest now creates a temp run and temp pointer path, temporarily assigns `xunji_statusline.ACTIVE_RUN` to that temp pointer, restores the original module constant in `finally`, and removes the temp parent directory with `shutil.rmtree`.
- Control: Rerun test log shows the new `setup active-run selftest cleans temp dir` assertion passing, and the real `.claude/xunji_active_run` still points to `runs/scshr-r2_20260708`.
- Caused by us: yes
- Alternative explanation: A process-kill during selftest can still interrupt cleanup of filesystem temp files, but it no longer changes the real active-run pointer path.
- Certainty: 0.8
- Artifacts: evidence/final3-diff.txt, evidence/final3-test-log.txt
- Supports: F-003
- Next: Independent review should verify PR-001 and PR-004 are resolved.

## E-005

- Maturity: finding
- Reportable: no
- Time: 2026-07-08T11:45:00Z
- Action: Addressed second-round stale-evidence and `--classify` ambiguity review warnings.
- Source: repository diff and local command output
- Result: The authoritative current diff is now `evidence/final3-diff.txt`; the primary report points reviewers there instead of the older initial diff. Claude primary-driver docs now state that `--classify` is a new-run setup option, not an existing-run refresh mode. The selftest now asserts module pointer restoration, real pointer non-mutation, and temp cleanup.
- Control: Rerun test log shows the added assertions passing and confirms the real active pointer remains `runs/scshr-r2_20260708`.
- Caused by us: yes
- Alternative explanation: Review artifacts are still snapshots; rerun review must use this updated bundle hash.
- Certainty: 0.8
- Artifacts: evidence/final3-diff.txt, evidence/final3-test-log.txt
- Supports: F-002, F-003, F-004
- Next: Third-round independent review should verify no stale evidence remains.

## E-006

- Maturity: finding
- Reportable: no
- Time: 2026-07-08T12:05:00Z
- Action: Added tests for `_set_active_run()` best-effort failure branches.
- Source: repository diff and local command output
- Result: The selftest monkeypatches `xunji_statusline.set_active_run` to return `False` and to raise an exception; `_set_active_run()` tolerates both and the checks pass.
- Control: The rerun output includes `active-run helper tolerates rejected pointer` and `active-run helper tolerates pointer exception`.
- Caused by us: yes
- Alternative explanation: These are unit-level branch tests, not a production CLI end-to-end invocation that mutates the real pointer.
- Certainty: 0.8
- Artifacts: evidence/final3-diff.txt, evidence/final3-test-log.txt
- Supports: F-002, F-003
- Next: Residual limitation: production CLI end-to-end pointer mutation was not exercised to avoid disturbing the operator's active run.

## E-007

- Maturity: finding
- Reportable: no
- Time: 2026-07-08T12:20:00Z
- Action: Addressed final Claude review warnings about import coupling and call-site assumptions.
- Source: repository diff and local command output
- Result: `xunji_statusline` is now imported lazily inside `_set_active_run()`, so statusline import failures are handled by the same best-effort warning path as pointer write failures. The `main()` call site now comments that this branch creates a new run and future existing-run modes should not pass through it unless they intentionally select the run in the statusline.
- Control: Rerun test log shows setup/statusline selftests and selected suites still pass, including rejected-pointer and exception-path checks.
- Caused by us: yes
- Alternative explanation: This remains repository-side unit/contract coverage; it deliberately avoids mutating the real pointer via a production CLI e2e.
- Certainty: 0.8
- Artifacts: evidence/final3-diff.txt, evidence/final3-test-log.txt
- Supports: F-001, F-002, F-003
- Next: Final Claude review should verify PR-004 and PR-006 from `review-claude-final2.md` are resolved.
