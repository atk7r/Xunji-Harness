# Review

## Independent Review

### Round 1

- Command: `python3 tools/peer_review.py review/records/2026-07-08-setup-statusline-active-run-review --driver codex --out review/records/2026-07-08-setup-statusline-active-run-review/review-panel.md --json-out review/records/2026-07-08-setup-statusline-active-run-review/review_result.json --timeout 900`
- Backend: `panel:arkcli+claude`
- Verdict: WARN
- Full output: `review-panel.md`

Driver disposition:

- PR-001 accepted: selftest should not mutate the real `.claude/xunji_active_run`; fixed by monkeypatching `xunji_statusline.ACTIVE_RUN` to a temp pointer path during the test.
- PR-002 dismissed: `--classify` is part of one-shot run creation, so selecting the newly created run remains expected display behavior.
- PR-003 accepted as process limitation: arkcli panel was partial because two arkcli model outputs had parse errors; rerun after fixes.
- PR-004 accepted: selftest leaked temp directories; fixed with `shutil.rmtree(active_parent, ignore_errors=True)`.
- PR-005 dismissed: `xunji_statusline.py` import-time behavior is limited to stdout encoding, constants, path setup, and importing `status_style`; no pointer write occurs at import.
- PR-006 noted: `check_rules.py` output is intentionally concise; no code change.
- PR-007 superseded: the revised selftest no longer uses the real no-prior-pointer path and now verifies cleanup of the isolated temp pointer.
- PR-008 accepted: this review file was initially pending; the completed review is now recorded here.

### Round 2

- Command: `python3 tools/peer_review.py review/records/2026-07-08-setup-statusline-active-run-review --driver codex --out review/records/2026-07-08-setup-statusline-active-run-review/review-panel-rerun.md --json-out review/records/2026-07-08-setup-statusline-active-run-review/review_result-rerun.json --timeout 900`
- Backend: `panel:arkcli+claude`
- Verdict: WARN
- Full output: `review-panel-rerun.md`

Driver disposition:

- PR-001 / PR-006 accepted: E-001/E-002/E-003 still cited stale artifacts; updated them to current `evidence/final-diff.txt` and `evidence/final-test-log.txt`.
- PR-002 / PR-007 accepted: primary report section embedded stale initial diff; changed it to superseded history and made `evidence/final-diff.txt` the authoritative current diff.
- PR-003 accepted: selftest now explicitly checks `xunji_statusline.ACTIVE_RUN` module constant restoration and real pointer file non-mutation.
- PR-004 accepted: clarified in `.claude/skills/*` and `docs/ROUTER.md` that `--classify` is a new-run setup option, not existing-run refresh.
- PR-005 accepted as process limitation: arkcli panel remained partial because two arkcli model outputs had parse errors; rerun after updated evidence.
- PR-008 noted: failure-path warning branch remains untested; acceptable residual WARN because the helper is best-effort display-state only and success plus non-mutation are covered.
- PR-009 dismissed: import-time behavior of `xunji_statusline.py` is visible in source and performs no pointer write; setup should fail loudly if the statusline module itself is syntactically broken because setup now depends on that local helper.
- PR-010 accepted: review fronts will be closed after the final rerun if no blocker remains.

### Round 3

- Command: `python3 tools/peer_review.py review/records/2026-07-08-setup-statusline-active-run-review --driver codex --out review/records/2026-07-08-setup-statusline-active-run-review/review-panel-final.md --json-out review/records/2026-07-08-setup-statusline-active-run-review/review_result-final.json --timeout 900`
- Backend: `panel:arkcli+claude`
- Verdict: WARN
- Full output: `review-panel-final.md`

Driver disposition:

- PR-001 accepted: E-004 still cited superseded Round-1 artifacts; updated confirmed evidence entries to current `evidence/final2-diff.txt` and `evidence/final2-test-log.txt`.
- PR-002 accepted: `_set_active_run()` failure branches were untested; added selftests for `set_active_run()` returning `False` and raising an exception.
- PR-003 accepted as residual limitation: no production CLI end-to-end test mutates the real `.claude/xunji_active_run`; this is intentional to avoid disturbing the operator's current active run. Repository-side helper behavior, validation, failure handling, and non-mutation of the real pointer during selftest are covered.
- PR-004 accepted as process limitation: arkcli panel remained partial because two arkcli model outputs had parse errors; `kimi-k2.7-code` and Claude Code CLI completed and found no blocker.

Final synthesis: no BLOCKER remains. Residual WARNs are review-process limitations
and the deliberate absence of a real-pointer-mutating production CLI e2e test.

### Round 4

- Command: `python3 tools/peer_review.py review/records/2026-07-08-setup-statusline-active-run-review --driver codex --out review/records/2026-07-08-setup-statusline-active-run-review/review-panel-final2.md --json-out review/records/2026-07-08-setup-statusline-active-run-review/review_result-final2.json --timeout 900`
- Backend: `panel:claude`; arkcli failed across all models.
- Verdict: NEEDS_DRIVER
- Full output: `review-panel-final2.md`

Driver disposition:

- Panel limitation accepted: arkcli parse errors prevented 2/2 matrix completion.
- Claude reviewer completed and found no blocker; standalone Claude final review saved as `review-claude-final2.md`.
- Claude PR-004 accepted: move `xunji_statusline` import into `_set_active_run()` so import failure is also best-effort.
- Claude PR-006 accepted: add a comment at the unconditional call site explaining the new-run assumption.
- Claude PR-001/PR-002 accepted: remove stale `final-diff` prose and make `final3` artifacts authoritative.
- Claude PR-003 accepted as process limitation: panel NEEDS_DRIVER is recorded here rather than hidden.
- Claude PR-005 noted: `check_rules.py` concise output is accepted as residual audit-opacity risk outside this change.

### Final Claude Review

- Command: `python3 tools/peer_review.py review/records/2026-07-08-setup-statusline-active-run-review --driver codex --backend claude --out review/records/2026-07-08-setup-statusline-active-run-review/review-claude-final3.md --json-out review/records/2026-07-08-setup-statusline-active-run-review/review_result-claude-final3.json --timeout 900`
- Backend: `claude:code-cli`
- Verdict: WARN
- Full output: `review-claude-final3.md`

Driver disposition:

- No concrete findings were returned.
- Blind-spot note about stale embedded report log accepted: the initial verification log is now labeled superseded and the current log is `evidence/final3-test-log.txt`.
- Blind-spot note about ROUTER.md scope drift accepted: `report.md` now records why ROUTER entered scope.
- Residual WARN accepted: `check_rules.py` output remains concise/opaque, and arkcli panel parse errors prevented a clean 2/2 final matrix. Claude Code CLI final review completed with no blocker.

Final synthesis after final Claude review: no BLOCKER remains. The implementation
change is accepted with recorded residual process limitations.
