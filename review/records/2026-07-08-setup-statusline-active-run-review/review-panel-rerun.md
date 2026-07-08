# Peer Review Panel — 2026-07-08-setup-statusline-active-run-review

_backend: panel:arkcli+claude · 2026-07-08T11:33Z_
> 候选, 非裁决。driver 须逐条过证据门。

## Verdict: WARN

_backend: panel:arkcli+claude_
_brain: codex_
_bundle_hash: 6ddeb13bff54bc7e068005f002d84400dc0ad9df_
_evidence_index_hash: 4320dbe9a491042982bf0caa97a189e9c1ebb82b_

## Findings
- [WARN] PR-001 Confirmed evidence E-001/E-002/E-003 still rests on the original diff/test log, whose selftest mutates the real .claude/xunji_active_run pointer and leaks temp directories. | Evidence: evidence_index:E-001, evidence_index:E-002, evidence_index:E-003, evidence/diff.txt:575-595, evidence/test-log.txt, decisions.md:D-004, evidence/followup-diff.txt:575-601, evidence/test-log-rerun.txt | Why: [panel:arkcli] [arkcli:kimi-k2.7-code] The original selftest reads and writes the real ACTIVE_RUN path and leaves temp directories behind. D-004 explicitly accepts this as a defect, so evidence that violates an expected invariant cannot support a confirmed (>=0.8) finding.
- [WARN] PR-002 The report's 'Diff Under Review' section presents the original diff, while the Round 1 Follow-Up states the current diff is evidence/followup-diff.txt. | Evidence: report.md:Diff Under Review, report.md:Round 1 Follow-Up, evidence/followup-diff.txt, evidence/test-log-rerun.txt | Why: [panel:arkcli] [arkcli:kimi-k2.7-code] Readers verifying the change against the stated invariants will see the unsafe original selftest instead of the fixed version, creating a contradiction within the report.
- [WARN] PR-003 The revised selftest restores the original ACTIVE_RUN module constant in finally but does not assert that the original pointer/file is actually restored. | Evidence: evidence/followup-diff.txt:575-601, evidence/test-log-rerun.txt:last line active=runs/scshr-r2_20260708 | Why: [panel:arkcli] [arkcli:kimi-k2.7-code] Restoration is only demonstrated by an external post-test print. A silent failure in finally would not be caught by the selftest, weakening the regression coverage claim.
- [WARN] PR-004 --classify semantics are ambiguous: the skill doc describes it as an authorized current egress recheck, while D-005 treats it strictly as one-shot run creation. | Evidence: .claude/skills/xunji-run-lifecycle/SKILL.md excerpt in evidence/diff.txt, decisions.md:D-005, report.md:Expected Invariants | Why: [panel:arkcli] [arkcli:kimi-k2.7-code] If --classify can target an existing run, automatically repointing the active-run pointer may surprise the operator. The docs and the decision contradict each other.
- [WARN] PR-005 arkcli panel had backend errors; review is partial | Evidence: minimax-m3: parse error; output tail:  a potential issue worth flagging. The decision D-005 dismisses a concern that may actually be valid based on the documentation.

Let me think more carefully. The diff adds `_set_active_run(run_dir)` which is called unconditionally in `main()` after `scaffold(run_dir)`. The `scaffold()` function creates a NEW run directory. If `--classify` is for rechecking an existing run, then calling `setup_run.py --classify` would:
1. Create a new run directory (via scaffold)
2. Set the active-run pointer to; glm-5.2: parse error; output tail: ferent final state. But the report.md shows the original diff (ff2f45a), not the followup (9d8f26c).

## Critical Issue 6: Missing `import shutil` in followup-diff.txt

Looking at the followup-diff.txt, the selftest uses `shutil.rmtree(active_parent, ignore_errors=True)` but I don't see `import shutil` being added in the diff. Let me check if it's already imported elsewhere...

The diff only shows the changes. `shutil` might already be imported at the top of `setup_run.py`. But if it's not, this | Why: [panel:arkcli] At least one arkcli reviewer failed, so PASS only means the completed panel members found no blocker.
- [WARN] PR-006 E-002 evidence entry is stale — describes corrected behavior but cites v1 (unsafe) artifacts `evidence/diff.txt` and `evidence/test-log.txt` instead of the followup versions. | Evidence: evidence.md:29 (E-002 Artifacts field) vs evidence/followup-diff.txt (actual corrected code) | Why: [panel:claude] A reader following E-002's artifact references sees the old, unsafe selftest that the review flagged. E-004 was added to document the fix but E-002 was never updated to point to corrected artifacts or cross-reference E-004.
- [WARN] PR-007 Report embeds stale v1 diff as "Diff Under Review" — only the separate "Round 1 Follow-Up" section points to the corrected followup-diff.txt. | Evidence: report.md:31-142 (v1 diff) vs report.md:195-204 (acknowledges followup) | Why: [panel:claude] The report's primary diff section presents code that was already found to have two defects (pointer mutation, temp dir leak). This is misleading on first read even though the follow-up section corrects it.
- [WARN] PR-008 No test coverage for `_set_active_run()` failure/warning path — the "best-effort" guarantee is only tested for success. | Evidence: evidence/followup-diff.txt:95-105 (selftest block only tests success, never `set_active_run()` returning False or raising) | Why: [panel:claude] The function is documented as best-effort with printed warnings, but the warning path is untested. If `set_active_run()` changes behavior, the warning might silently break.
- [WARN] PR-009 No import resilience — `import xunji_statusline` at module level in `setup_run.py` with no `try/except ImportError` fallback. | Evidence: evidence/followup-diff.txt:54 | Why: [panel:claude] If `xunji_statusline.py` gains a broken import, `setup_run.py` becomes completely unusable even for operations that don't touch the statusline. PR-005 dismissal only covered "side effects" not dependency resilience.
- [WARN] PR-010 All four frontier entries (F-001 through F-004) remain "open-for-review" — no formal front closure. | Evidence: frontier.md:5,10,15,20 (all Status: open-for-review) | Why: [panel:claude] After two rounds of review, the fronts should be explicitly adjudicated with a verdict and rationale, not left open indefinitely.

## Blind-spot check
- [arkcli] [kimi-k2.7-code] The evidence ledger was not pruned after the follow-up diff was produced; original-diff entries remain confirmed.
- [arkcli] [kimi-k2.7-code] The report body was not updated to display the follow-up diff, so the primary artifact a reviewer sees is stale.
- [arkcli] [kimi-k2.7-code] No in-test assertion verifies restoration of the pre-existing active-run pointer.
- [arkcli] [kimi-k2.7-code] The import-time side effects of xunji_statusline are asserted in review.md PR-005 but not independently evidenced in this bundle.
- [arkcli] [kimi-k2.7-code] The actual behavior of --classify and whether it can target an existing run directory was not probed in the provided artifacts.
- [claude] The `evidence.md` format lacks a "superseded-by" or "obsoleted" field, making it easy for stale entries (E-001, E-002) to coexist with their corrections (E-004) without cross-referencing. This is a process design issue, not a one-off mistake — it will recur.
- [claude] The `_set_active_run()` unconditional main() call means ANY future code path through main() sets the active-run pointer. D-005 dismisses the `--classify` concern, but the general principle is under-documented: there's no comment explaining *why* it's desirable for every invocation to set the pointer, or when a future mode should skip it.
- [claude] The followup selftest creates `.claude` as a side effect of `set_active_run()` but never asserts it exists explicitly — the test passes because `active_run()` returns the right value, not because the file was written to the correct path.
- [claude] The `xunji_statusline.py` module itself was never in-scope for review — all claims about its import-time behavior, API contracts, and safety rest on trust, not verification.

## Context-limit notes
- [arkcli] minimax-m3: parse error; output tail:  a potential issue worth flagging. The decision D-005 dismisses a concern that may actually be valid based on the documentation.

Let me think more carefully. The diff adds `_set_active_run(run_dir)` which is called unconditionally in `main()` after `scaffold(run_dir)`. The `scaffold()` function creates a NEW run directory. If `--classify` is for rechecking an existing run, then calling `setup_run.py --classify` would:
1. Create a new run directory (via scaffold)
2. Set the active-run pointer to
- [arkcli] glm-5.2: parse error; output tail: ferent final state. But the report.md shows the original diff (ff2f45a), not the followup (9d8f26c).

## Critical Issue 6: Missing `import shutil` in followup-diff.txt

Looking at the followup-diff.txt, the selftest uses `shutil.rmtree(active_parent, ignore_errors=True)` but I don't see `import shutil` being added in the diff. Let me check if it's already imported elsewhere...

The diff only shows the changes. `shutil` might already be imported at the top of `setup_run.py`. But if it's not, this
- [claude] I was unable to read `xunji_statusline.py` and `setup_run.py` full source — read access outside the review scope was denied. My assessment of import-time behavior, `set_active_run()` internals, and `--classify` code paths relies entirely on the diff fragments and review claims.
- [claude] The Chinese-language skill files (`.claude/skills/*`) were only seen through diff hunks. Their surrounding prose might contain language about setup boundaries that I can't fully verify.
- [claude] `check_rules.py` output is a single opaque line — I cannot assess whether the safety checks are substantive.