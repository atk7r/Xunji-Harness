# Peer Review Panel — 2026-07-08-setup-statusline-active-run-review

_backend: panel:claude · 2026-07-08T11:50Z_
> 候选, 非裁决。driver 须逐条过证据门。

## Verdict: NEEDS_DRIVER

_backend: panel:claude_
_brain: codex_
_bundle_hash: 1919204b2176bec6c74a8d0a09cbb7d934b94689_
_evidence_index_hash: 1e8825cb9a1ff6833ec78a63df19bad564ef8a38_

## Findings
- [WARN] PR-001 review panel had backend errors; aggregation is partial | Evidence: arkcli: ERROR arkcli panel 全部模型失败: kimi-k2.7-code: parse error; output tail: I'll inspect the run directory and the cited artifacts to verify the confirmed findings and look for blind spots.; minimax-m3: parse error; output tail: maining concerns are:
      - Process limitation: arkcli panel partial due to parse errors
      - Deliberate limitation: no production CLI e2e test for real pointer mutation
      - Import-time behavior of `xunji_statusline.py` (dismissed, probably correct)

8. **My independent assessment as evidence_skeptic:**

   - The change is well-scoped and well-tested
   - The diff is small and the test additions are clear
   - The author made good progress through 3 rounds
   - The main concerns I would; glm-5.2: parse error; output tail: touched. The `active=runs/scshr-r2_20260708` would be reading from the real pointer file. This seems fine.

**Issue 4: No evidence of the actual production behavior.** The report acknowledges this as a "deliberate limitation": "no production CLI end-to-end test mutates the real `.claude/xunji_active_run`". But the core claim of the maintenance diff is that `setup_run.py` now sets the active run pointer after creating a run. This is ONLY tested via selftest with monkeypatched pointers. There's no | Why: At least one requested heterogeneous reviewer failed or was unavailable.

## Blind-spot check
- [claude] **The `rd3` variable used in the failure-branch selftest is not defined in the diff context** — it's an existing selftest directory created earlier in `_selftest()`. The test log confirms it resolves (line 1: `/var/folders/.../t3_20260101`), but a reader of the diff alone cannot verify this. Not a defect since the test passes, but a diff-readability blind spot.
- [claude] **`shutil` and `tempfile` imports are not shown in the diff** — `shutil.rmtree()` and `tempfile.mkdtemp()` appear in the new selftest code, but the diff doesn't show their import statements. Since `setup_run.py` already uses `shutil.copy` for template scaffolding in earlier parts of `_selftest()`, they're certainly already imported, and the test passing doubly confirms this. The Round 2 `review-panel-rerun.md:24-28` flagged this as "Critical Issue 6: Missing `import shutil`" but it's a false alarm.
- [claude] **`_set_active_run()` call site is unconditionally after `scaffold()` but before coverage logic in `main()`** — this means ANY code path that reaches that point (including `--classify`, if a future developer repurposes it for existing-runs) would set the active pointer. D-005 explicitly states `--classify` is new-run-only, and the updated docs confirm this. However, the diff adds no guard or comment at the call site documenting *why* it should fire unconditionally or *when* it shouldn't. A future mode added to `main()` could unknowingly inherit the pointer-set behavior. This was noted in the Round 2 blind-spot check (`review-panel-rerun.md:42: "the general principle is under-documented"`) but not formally dispositioned.
- [claude] **The three review rounds caught and fixed every concrete defect** — the Round 0 diff had real pointer mutation and temp dir leaks. Round 1 fixed those. Round 2 added module-pointer restoration assertions and `--classify` doc clarity. Round 3 added failure-branch tests. The evolution is well-documented and each fix addresses a substantive concern.
- [claude] **The report's structure now correctly directs readers to the authoritative artifacts** — `report.md:33-34` says "The authoritative current diff is saved at `evidence/final2-diff.txt`. The authoritative current test log is saved at `evidence/final2-test-log.txt`." The initial v1 diff is explicitly labeled "Superseded Initial Diff (Round 0, Not Current)" at line 36. The follow-up sections for Rounds 1-3 track the revision history. This is well-organized.
- [claude] **The selftest monkeypatches `xunji_statusline.ACTIVE_RUN` as a module constant, not via a parameterized path** — while the `finally` block restores it, if the monkeypatch assignment at line 138 (`xunji_statusline.ACTIVE_RUN = active_pointer`) itself raises (unlikely since it's a simple attribute assignment), or if a signal/interrupt occurs before `finally`, the module constant would remain pointing at a temp path. However, this is an extremely narrow race condition and the `finally` block is the standard Python idiom. The real safeguard is lines 144-152 which verify `real_active_after == real_active_before` by independently re-reading the original file. This double-checks the restoration worked.
- [claude] **`check_rules.py` output remains a single opaque "rule check passed" line** — flagged in all three rounds. Without access to the tool's source (denied in my context), I cannot assess whether the checks are substantive. The Round 2 Claude reviewer described this as a "transparency gap, not a code bug" — I concur.

## Context-limit notes
- [claude] I was denied read access to `tools/setup_run.py` (full source), `tools/xunji_statusline.py`, `tools/check_rules.py`, and `.claude/skills/*` (full source). My assessment of `shutil`/`tempfile` import existence, `xunji_statusline` import-time behavior, `clear_active_run()` internals, and `--classify` code paths relies on diff fragments, test output, and prior review claims. The test log passing provides strong circumstantial evidence for correctness, but I cannot independently verify the non-diff portions of the source files.
- [claude] The Chinese-language skill files (`.claude/skills/xunji-run-lifecycle/SKILL.md`, `.claude/skills/xunji-setup-ingest/SKILL.md`) were only seen through diff hunks. The diff shows additions of English text alongside existing Chinese prose. I cannot verify whether the surrounding Chinese prose creates any contradiction with the new English additions.
- [claude] `check_rules.py` is referenced as a safety gate in the test log but its contents are not in this review scope. I cannot assess what "rule check passed" substantively means.
- [claude] The `rd3` variable used in the failure-branch tests (`_set_active_run(rd3)` at lines 159/169 of final2-diff.txt) is not defined in the diff context. Based on the test log, it resolves to a temporary run directory at `/var/folders/.../t3_20260101`. This is likely one of the existing selftest directories (`rd1`, `rd2`, `rd3`) created earlier in `_selftest()`, but I cannot verify this without full source access.
- arkcli: ERROR arkcli panel 全部模型失败: kimi-k2.7-code: parse error; output tail: I'll inspect the run directory and the cited artifacts to verify the confirmed findings and look for blind spots.; minimax-m3: parse error; output tail: maining concerns are:
      - Process limitation: arkcli panel partial due to parse errors
      - Deliberate limitation: no production CLI e2e test for real pointer mutation
      - Import-time behavior of `xunji_statusline.py` (dismissed, probably correct)

8. **My independent assessment as evidence_skeptic:**

   - The change is well-scoped and well-tested
   - The diff is small and the test additions are clear
   - The author made good progress through 3 rounds
   - The main concerns I would; glm-5.2: parse error; output tail: touched. The `active=runs/scshr-r2_20260708` would be reading from the real pointer file. This seems fine.

**Issue 4: No evidence of the actual production behavior.** The report acknowledges this as a "deliberate limitation": "no production CLI end-to-end test mutates the real `.claude/xunji_active_run`". But the core claim of the maintenance diff is that `setup_run.py` now sets the active run pointer after creating a run. This is ONLY tested via selftest with monkeypatched pointers. There's no
- panel completed 1/2 required heterogeneous backends

> ERROR: arkcli: ERROR arkcli panel 全部模型失败: kimi-k2.7-code: parse error; output tail: I'll inspect the run directory and the cited artifacts to verify the confirmed findings and look for blind spots.; minimax-m3: parse error; output tail: maining concerns are:
      - Process limitation: arkcli panel partial due to parse errors
      - Deliberate limitation: no production CLI e2e test for real pointer mutation
      - Import-time behavior of `xunji_statusline.py` (dismissed, probably correct)

8. **My independent assessment as evidence_skeptic:**

   - The change is well-scoped and well-tested
   - The diff is small and the test additions are clear
   - The author made good progress through 3 rounds
   - The main concerns I would; glm-5.2: parse error; output tail: touched. The `active=runs/scshr-r2_20260708` would be reading from the real pointer file. This seems fine.

**Issue 4: No evidence of the actual production behavior.** The report acknowledges this as a "deliberate limitation": "no production CLI end-to-end test mutates the real `.claude/xunji_active_run`". But the core claim of the maintenance diff is that `setup_run.py` now sets the active run pointer after creating a run. This is ONLY tested via selftest with monkeypatched pointers. There's no