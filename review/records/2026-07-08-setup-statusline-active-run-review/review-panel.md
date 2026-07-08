# Peer Review Panel — 2026-07-08-setup-statusline-active-run-review

_backend: panel:arkcli+claude · 2026-07-08T11:25Z_
> 候选, 非裁决。driver 须逐条过证据门。

## Verdict: WARN

_backend: panel:arkcli+claude_
_brain: codex_
_bundle_hash: d9619d6bfc04f4c908191bd741cd69d68c7a4d9b_
_evidence_index_hash: 7077e865ffae7f5133146362baac14f694855fd2_

## Findings
- [WARN] PR-001 Selftest mutates the real .claude/xunji_active_run pointer and its restoration is only crash-safe inside the try/finally; a crash before or during read/restore can leave the operator’s active-run pointer corrupted or pointing at a deleted temp directory. | Evidence: evidence/diff.txt:selftest block showing old_active read, _set_active_run, finally restore, evidence/test-log.txt | Why: [panel:arkcli] [arkcli:kimi-k2.7-code] The Expected Invariant requires selftests to restore pre-existing active-run pointer. While the diff attempts restoration, the test reads and writes the actual global state file without isolation. A crash before the finally block executes can corrupt operator statusline state. This is a testing-hygiene blind spot not acknowledged in the report.
- [WARN] PR-002 The report does not verify whether setup_run.py --classify also sets the active-run pointer, which could overwrite the operator's current run pointer during an egress recheck. | Evidence: evidence/diff.txt:main() _set_active_run insertion location, frontier.md:F-002 boundary preservation question | Why: [panel:arkcli] [arkcli:kimi-k2.7-code] The skill docs state --classify is for authorized egress recheck only and setup_run.py should not choose fronts or make evidence decisions. If the classify code path reaches the same main() location, it would silently change the active-run display state, potentially surprising the operator.
- [WARN] PR-003 arkcli panel had backend errors; review is partial | Evidence: minimax-m3: parse error; output tail: ates up. The active pointer would remain set to the temp run. **This is a potential bug** - the restore is not robust.

   Looking again:
   ```python
   old_active = xunji_statusline.ACTIVE_RUN.read_text(encoding="utf-8", errors="replace") \
       if xunji_statusline.ACTIVE_RUN.exists() else None
   try:
       _set_active_run(active_rd)
       active = xunji_statusline.active_run()
   finally:
       if old_active is None:
           xunji_statusline.clear_active_run()
       else:
          ; glm-5.2: parse error; output tail:  Claude. The report.md says "This is Codex-authored maintenance. Codex self-review is not an independent review." So the author of the diff is Codex, and the review is asking for independent review. The review.md says "Pending `tools/peer_review.py --driver codex` run." - so the independent review hasn't been done yet. I'm being asked to be that independent reviewer.

Wait, the report says "Codex-authored maintenance" and "Codex self-review is not an independent review." So the diff was authored | Why: [panel:arkcli] At least one arkcli reviewer failed, so PASS only means the completed panel members found no blocker.
- [WARN] PR-004 Selftest leaks temp directories — never cleans up `tmp/tmpXXXXXX/run/` after scaffold test | Evidence: `evidence/diff.txt:88-104` (selftest block lacks `shutil.rmtree` or equivalent cleanup of `active_rd.parent`) | Why: [panel:claude] Each selftest invocation leaves an orphaned scaffolded run under `repo/tmp/`; repeated runs accumulate garbage. The `finally` block only restores the active-run pointer, not the filesystem.
- [WARN] PR-005 `import xunji_statusline` module-level side effects are unverified | Evidence: `evidence/diff.txt:54` adds `import xunji_statusline` at module top; no audit of `xunji_statusline.py` import-time behavior in evidence or review scope | Why: [panel:claude] If `xunji_statusline` has import-time side effects (file reads, connections, hooks), they would execute whenever `setup_run.py` is imported — not just when `_set_active_run()` runs. Likely innocuous but unverified.
- [WARN] PR-006 `check_rules.py` evidence is a single opaque line | Evidence: `evidence/test-log.txt:40` shows only "rule check passed" with no individual rule names or check output | Why: [panel:claude] Unlike the 26-line setup_run selftest output or the 10-line statusline selftest output, the rules check provides zero transparency into what was evaluated.
- [WARN] PR-007 Selftest doesn't assert correctness of `clear_active_run()` for the no-prior-pointer case | Evidence: `evidence/diff.txt:98-99` calls `clear_active_run()` when `old_active is None` but never asserts the result | Why: [panel:claude] The first-ever-run scenario is tested for non-crashing but not for correctness — the test never verifies that after clearing, `active_run()` returns `None`/empty.
- [WARN] PR-008 `review.md` was empty at review start — the independent review process was incomplete | Evidence: `review.md:5` states "Pending tools/peer_review.py --driver codex run." | Why: [panel:claude] This is a process gap — the review file should not have been committed/registered as complete before the independent reviewer ran. Now resolved by this review.

## Blind-spot check
- [claude] Temp directory leak in selftest is the clearest concrete defect — every other concern is a documentation/transparency gap, not a code bug.
- [claude] The `_set_active_run()` call site placement (after scaffold, before coverage) is a deliberate design choice, not a bug — but it means the statusline can transiently point at a partially-built run. The "display state only" documentation mitigates this.
- [claude] The diff doesn't modify `xunji_statusline.py` at all — it only consumes its public API (`set_active_run`, `active_run`, `clear_active_run`, `ACTIVE_RUN`). This is good separation of concerns.
- [claude] The combined selftest output format (individual checks appearing before the test suite header) is unusual but not incorrect — likely concatenated from `setup_run --selftest` + `xunji_statusline --selftest` + `check_rules` output.

## Context-limit notes
- [arkcli] minimax-m3: parse error; output tail: ates up. The active pointer would remain set to the temp run. **This is a potential bug** - the restore is not robust.

   Looking again:
   ```python
   old_active = xunji_statusline.ACTIVE_RUN.read_text(encoding="utf-8", errors="replace") \
       if xunji_statusline.ACTIVE_RUN.exists() else None
   try:
       _set_active_run(active_rd)
       active = xunji_statusline.active_run()
   finally:
       if old_active is None:
           xunji_statusline.clear_active_run()
       else:

- [arkcli] glm-5.2: parse error; output tail:  Claude. The report.md says "This is Codex-authored maintenance. Codex self-review is not an independent review." So the author of the diff is Codex, and the review is asking for independent review. The review.md says "Pending `tools/peer_review.py --driver codex` run." - so the independent review hasn't been done yet. I'm being asked to be that independent reviewer.

Wait, the report says "Codex-authored maintenance" and "Codex self-review is not an independent review." So the diff was authored
- [claude] I cannot verify `xunji_statusline.py` import-time behavior since that file is not in the review scope and read access was denied. My concern about module-level side effects could be confirmed or dismissed by a 10-second audit of that file.
- [claude] The Chinese-language skill files (`.claude/skills/xunji-run-lifecycle/SKILL.md`, `.claude/skills/xunji-setup-ingest/SKILL.md`) and `docs/WORKFLOW.md` are partially in Chinese — I verified the diff hunk additions but cannot fully assess whether the surrounding Chinese prose in those files creates any contradiction with the new English-language additions.
- [claude] `check_rules.py` is referenced as a safety gate but its contents are not in the review scope — I cannot assess whether "rule check passed" means anything substantive.