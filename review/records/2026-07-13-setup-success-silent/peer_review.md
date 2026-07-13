# Peer Review Panel — 2026-07-13-setup-success-silent

_backend: panel:arkcli+claude · 2026-07-13T06:34Z_
> 候选, 非裁决。driver 须逐条过证据门。

## Verdict: WARN

_backend: panel:arkcli+claude_  
_brain: codex_  
_bundle_hash: ab4561d26b5459d7522f17f4fb80a862f477ceba_  
_evidence_index_hash: 6b23bae8c49b2d349d4a3459f6dbac6d52f898f9_  

## Findings
- [WARN] PR-001 Explicit --help output preservation is asserted only by policy excerpts and the selftest's own stdout audit; no captured --help invocation or .replay.json independently verifies it. | Evidence: evidence/selftest.log, evidence/setup_success_silent.diff, evidence/docs.md | Why: [panel:arkcli] [arkcli:kimi-k2.7-code] The report's review question 3 is answered by documentation and self-reported audit prose, not by an independent observation. The diff shown does not include --help handling, so argparse's default stdout behavior could be inadvertently redirected or suppressed. [review-output-invalid: PR-001 references unknown affected_eids: E-SILENT-002, E-SILENT-003]
- [WARN] PR-002 None of the evidence_index entries carry certainty grades or confirmed flags, so the report's conclusions should be treated as candidate-level only. | Evidence: evidence_index: E-SILENT-001, evidence_index: E-SILENT-002, evidence_index: E-SILENT-003 | Why: [panel:arkcli] [arkcli:kimi-k2.7-code] Per review discipline, only certainty >= 0.8 may be reported as confirmed. All entries are marked maturity candidate with empty certainties and confirmed false. [review-output-invalid: PR-002 references unknown affected_eids: E-SILENT-001, E-SILENT-002, E-SILENT-003]
- [WARN] PR-003 arkcli panel had backend errors; review is partial | Evidence: glm-5.2: parse error; output tail: et ledger: ...")
+            coverage_matrix.write_outputs(run_dir)
         except Exception as e:
             print(f"[!] asset ledger 初始化失败(目标动作前必须修复): {e}", file=sys.stderr)
-        print("[下一步] ...")
-    else:
-        print("[下一步] ...")
```
Wait, where did the `if/else` go?
```
-        print("[下一步] ...")
-    else:
-        print("[下一步] ...")
```
This implies there was an `if coverage_ready:` (or similar) block, and an `else:` block. The `else:` block is completely removed in the diff | Why: [panel:arkcli] At least one arkcli reviewer failed, so PASS only means the completed panel members found no blocker.

## Blind-spot check
- [arkcli] [kimi-k2.7-code] xunji_statusline.set_active_run() may itself emit stdout/stderr on success, but no artifact checks its output after the caller's success print was removed.
- [arkcli] [kimi-k2.7-code] No impact analysis of other tooling or scripts that may have parsed setup_run.py stdout before this change.
- [arkcli] [kimi-k2.7-code] Long-running setup steps (recon ingest, classify_hosts) are now silent on stdout, which an operator could mistake for a hang; no UX note or progress spinner was added.
- [arkcli] [kimi-k2.7-code] No separate CI replay artifact is included for --help or --selftest output; only the selftest log's own assertions are present.
- [claude] **`classify_hosts` stdout discard is the biggest miss**: The author treated `sys.stdout.write(r.stdout or "")` as "setup progress" to be silenced, but it's actually subprocess passthrough. The correct fix would be to redirect classify output to stderr or a log file, not discard it entirely. The operator who requested this feature likely expects some feedback from `--classify`.
- [claude] **No `--classify` regression test**: The selftest checks stdout/stderr silence on a plain setup, but if `--classify` is a documented flag, the test suite should verify its behavior hasn't regressed. The current test can't distinguish between "classify runs and its output is intentionally discarded" vs "classify silently broke and produces nothing."
- [claude] **No automated stdout lint**: The manual audit claim in the selftest log is fragile. A pre-commit hook or CI lint rule (e.g., grep for `print(` that doesn't target `file=sys.stderr`) would be a durable enforcement mechanism, but wasn't added.
- [claude] **The `_set_active_run` success print removal may affect other callers**: If `_set_active_run()` is called from outside `main()` (e.g., from `loop_bootstrap.py` or `xunji_statusline.py`), those callers previously got a stdout confirmation that is now gone. The diff doesn't show whether `_set_active_run` has other call sites.
- [claude] **`scaffold()` return value is now ignored**: Previously `made = scaffold(run_dir)` captured the return value and printed `len(made)`. Now `scaffold(run_dir)` ignores it. If `scaffold()` has side effects communicated only through its return value (e.g., returning files that failed to create), those are now silently swallowed.

## Context-limit notes
- [arkcli] glm-5.2: parse error; output tail: et ledger: ...")
+            coverage_matrix.write_outputs(run_dir)
         except Exception as e:
             print(f"[!] asset ledger 初始化失败(目标动作前必须修复): {e}", file=sys.stderr)
-        print("[下一步] ...")
-    else:
-        print("[下一步] ...")
```
Wait, where did the `if/else` go?
```
-        print("[下一步] ...")
-    else:
-        print("[下一步] ...")
```
This implies there was an `if coverage_ready:` (or similar) block, and an `else:` block. The `else:` block is completely removed in the diff
- [arkcli] PR-001 references unknown affected_eids: E-SILENT-002, E-SILENT-003
- [arkcli] PR-002 references unknown affected_eids: E-SILENT-001, E-SILENT-002, E-SILENT-003
- [claude] I was unable to read the full `tools/setup_run.py` source, the `CLAUDE.md`, `docs/WORKFLOW.md`, or `.claude/skills/xunji-run-lifecycle/SKILL.md` live files due to tool restrictions in this environment. My analysis is based solely on the review bundle artifacts. The claim that policy files were updated (E-SILENT-003) is taken on the evidence artifact's authority — I cannot verify those are the live file contents, nor that no other policy files contain contradictory instructions.
- [claude] The Chinese-language policy paragraph in `docs/WORKFLOW.md` (E-SILENT-003) was machine-translatable and its meaning aligns with the English `CLAUDE.md` excerpt, so I have medium confidence in this cross-reference.
- [claude] I cannot run `tools/setup_run.py --help` or `tools/setup_run.py --classify` to verify their runtime behavior, so my warning about `--classify` output discard is based on diff analysis alone — if the subprocess is actually piped to a log file elsewhere outside the diff excerpt, the concern would be invalid.
- [claude] The diff format (`@@ _set_active_run` without line numbers) is unusual. It may be a tool-specific format (e.g., `git diff --function-context` or an AI-generated summary). If the full unified diff is larger and covers additional hunks, my line-coverage concerns may be partially addressed by material I cannot see.