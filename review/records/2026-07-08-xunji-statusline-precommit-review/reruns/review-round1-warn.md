# Peer Review Panel — 2026-07-08-xunji-statusline-precommit-review

_backend: panel:arkcli+claude · 2026-07-08T07:44Z_
> 候选, 非裁决。driver 须逐条过证据门。

## Verdict: WARN

_backend: panel:arkcli+claude_  
_brain: codex_  
_bundle_hash: b8bba7e48413521c53ff239a5e1e0ae2c8e4d780_  
_evidence_index_hash: 5bac5cfc957369168d9154ced3e246f99164c1ef_  

## Findings
- [WARN] PR-001 The registration of xunji_statusline in tools/selftest_all.py is claimed but not backed by a patch artifact; only a passing test run is shown. | Evidence: report.md:Diff Stat, E-005, evidence/test-log.txt | Why: [panel:arkcli] [arkcli:kimi-k2.7-code] Claim integrity for F-004 requires evidence for every changed file. The test log shows selftest_all knows the suite, but the wiring change itself is not present as an artifact. [review-output-invalid: PR-001 references unknown affected_eids: F-004]
- [WARN] PR-002 The actual Claude Code statusline color path using XUNJI_COLOR=1 is not exercised in the test evidence. | Evidence: E-002, evidence/patches/_claude__settings_json.patch.txt, E-005, evidence/test-log.txt | Why: [panel:arkcli] [arkcli:kimi-k2.7-code] settings.json sets XUNJI_COLOR=1, but the selftest only passes explicit color=True/False. Without inspecting status_style.py, the colored statusline in Claude Code is assumed, not confirmed. [review-output-invalid: PR-002 references unknown affected_eids: F-001]
- [WARN] PR-003 All five confirmed evidence entries have has_control=false and the machine findings flag missing controls, yet the report does not address them. | Evidence: evidence_index:E-001, evidence_index:E-002, evidence_index:E-003, evidence_index:E-004, evidence_index:E-005, machine_findings | Why: [panel:arkcli] [arkcli:kimi-k2.7-code] Schema/machine warnings treat confirmed findings as lacking controls. For a code-only change this may be a false positive, but it should be explicitly resolved rather than ignored.
- [WARN] PR-004 arkcli panel had backend errors; review is partial | Evidence: minimax-m3: parse error; output tail: `evidence/test-log.txt` showing actual test results** — Wait, it does (E-005 is the test log). OK.

9. **The review bundle itself is what we're reviewing** — this is a self-referential review: the run is `2026-07-08-xunji-statusline-precommit-review` and we're reviewing that very run's diff. So we need to check if the diff is committed-ready.

10. **Coverage of cyber-security concerns**:
   - The diff is internal tooling, not a security fix. No security findings claimed.
   - There are no `front; glm-5.2: parse error; output tail: ftest partially serves as a control for E-005 (the tests pass with the changes), but for E-001 through E-004, there's no control showing the "before" state or a negative test.

   h. **`_is_xunji_context` checks**: It checks for `CLAUDE.md`, `tools/loop_state.py`, and `.claude/skills` directory. If any of these are missing, the statusline returns empty. But what if someone creates these files in a different project? The check is based on file existence, not on any cryptographic identity. However | Why: [panel:arkcli] At least one arkcli reviewer failed, so PASS only means the completed panel members found no blocker.

## Blind-spot check
- [arkcli] [kimi-k2.7-code] Missing patch artifact for tools/selftest_all.py registration despite diff stat claiming the change.
- [arkcli] [kimi-k2.7-code] No integration test inside Claude Code's proprietary renderer; local selftests are the only validation.
- [arkcli] [kimi-k2.7-code] status_style.color_enabled() implementation not supplied, so the XUNJI_COLOR=1 path is unverified.
- [arkcli] [kimi-k2.7-code] No negative test for an invalid/malformed active-run pointer or for a workspace dir that is a repo subdirectory without run markers.
- [claude] **Race condition on `xunji_active_run` read/write**: The statusline refreshes every 2 seconds while `loop_bootstrap.py` or `/loop` may concurrently write `.claude/xunji_active_run`. `Path.write_text()` is not atomic (it opens and writes in-place), so a concurrent reader could see a truncated file. `active_run()` catches the resulting JSON/parse error and returns `None` gracefully, so the worst case is a single refresh cycle showing "未选择运行目录" before self-correcting on the next cycle. This is cosmetic-only for a display feature — the author focused on correctness guarantees for evidence/write paths but may have overlooked this display-only race.
- [claude] **`_phase_tag` fallback color "white" is untested and may be invalid**: `PHASE_COLOR.get(phase, "white")` at line 233 of the statusline patch — if an unknown phase string appears (e.g., a typo in `loop_journal.jsonl`), the fallback color is "white". Whether `status_style.tag()` accepts "white" depends on `status_style` internals. The selftest only tests known phases (Hunter, Root Orchestrator). If "white" isn't a valid color name in `status_style`, an unknown phase would cause a runtime error in the statusline, making it silently fail to render.
- [claude] **`_last_plan_note` cleanup regex is a maintenance coupling point**: The fallback `re.sub(r"^(即将执行|结果已写入运行文件|已选择目标=)", "", note)` at line 260 hardcodes three Chinese prefixes. If `loop_journal.py` introduces new note prefixes, the statusline will display them verbatim (potentially including internal metadata the operator shouldn't see in a 1-line status display). This coupling isn't documented.
- [claude] **No test verifies `render_statusline` never writes to disk**: The central claim in all docs (CLAUDE.md, WORKFLOW.md, SKILL.md) and decisions (D-002) is that the statusline is "read-only" during normal rendering. The selftest checks that output is correct, but there's no explicit test that `render_statusline()` does not call `write_text()`, `mkdir()`, or any other mutation — the guarantee relies entirely on code review of the function body. A regression that accidentally adds a `_load_json(path, default).update(...)` call inside `render_statusline` would not be caught by any test.
- [claude] **`ROOT/tmp/` directory may not be gitignored**: The `.gitignore` patch only adds `.claude/xunji_active_run`. If `ROOT/tmp/` is not already gitignored (I cannot verify from the review bundle), the leaked selftest directories could accidentally be committed. The `loop_bootstrap.py` selftest previously used system temp dirs to avoid this problem.

## Context-limit notes
- [arkcli] minimax-m3: parse error; output tail: `evidence/test-log.txt` showing actual test results** — Wait, it does (E-005 is the test log). OK.

9. **The review bundle itself is what we're reviewing** — this is a self-referential review: the run is `2026-07-08-xunji-statusline-precommit-review` and we're reviewing that very run's diff. So we need to check if the diff is committed-ready.

10. **Coverage of cyber-security concerns**:
   - The diff is internal tooling, not a security fix. No security findings claimed.
   - There are no `front
- [arkcli] glm-5.2: parse error; output tail: ftest partially serves as a control for E-005 (the tests pass with the changes), but for E-001 through E-004, there's no control showing the "before" state or a negative test.

   h. **`_is_xunji_context` checks**: It checks for `CLAUDE.md`, `tools/loop_state.py`, and `.claude/skills` directory. If any of these are missing, the statusline returns empty. But what if someone creates these files in a different project? The check is based on file existence, not on any cryptographic identity. However
- [arkcli] PR-001 references unknown affected_eids: F-004
- [arkcli] PR-002 references unknown affected_eids: F-001
- [claude] I cannot access the live repository files outside the review bundle directory (permission denied in this read-only context). Cross-checks against `status_style.py` internals (to verify `color_enabled()` reads `XUNJI_COLOR`, and that `tag()` accepts "white") and `ROOT/.gitignore` (to verify `tmp/` coverage) rely solely on the patch evidence in the bundle.
- [claude] The `statusLine` JSON key spelling (camelCase `"statusLine"` vs lowercase `"statusline"`) depends on Claude Code's actual settings schema, which I cannot verify. The report and test log treat it as correct.
- [claude] Chinese-language content in `loop_journal.jsonl` notes, `_last_plan_note` regex patterns, and documentation — I read these but may miss subtle semantic drift between what the journal records and what the statusline extracts.