# Peer Review — 2026-07-09-statusline-live-derive-fix

_backend: claude:code-cli · 2026-07-08T18:58Z_
> 候选, 非裁决。driver 须逐条过证据门: 不盲从(驳工具/语境误报), 不忽视(采纳真盲补)。

## Verdict: WARN

_backend: claude:code-cli_
_brain: codex_
_bundle_hash: 6d852579aabe35495821ce64bd79f0d48a3ef688_
_evidence_index_hash: 48087a68a3db7683bed884b4918a1b23dbbc392f_

## Findings
- [WARN] PR-001 E-002, E-003, E-004 have zero captured artifacts; evidence is ephemeral prose | Evidence: `evidence.md:9-19` | Why: Three of four evidence entries describe command output (selftest results, statusline render, diff check) without saving that output to the run directory. The run's audit trail is incomplete — a future reviewer cannot independently verify these claims.
- [WARN] PR-002 Journal note filtering uses fragile English-string heuristics with no regression guard | Evidence: `evidence/active-diff.txt:46-51` | Why: The `_last_plan_note` filter matches three hardcoded English substrings (`"run prepared"`, `"prepare authorized run workbench"`, `"next phase=root orchestrator"`). Minor changes to journal note text (capitalization, spacing, Chinese localization) would cause silent regression to stale display text.
- [WARN] PR-003 `except Exception: return None` in `_derived_state` silently swallows genuine bugs | Evidence: `evidence/active-diff.txt:34-35` | Why: A broad except clause masks all errors from `loop_state.derive()` and `run_controller.derive()`, including `AttributeError` from API mismatches and `TypeError` from schema drift. Failed derivation degrades silently to the old broken behavior with no diagnostic.

## Blind-spot check
- The fix assumes `loop_state.derive(write=False)` and `run_controller.derive(run_dir, loop_data=loop_data)` have stable, matching signatures. Neither module is visible in the run artifacts. If either function's API changes, the statusline silently degrades.
- The `_state_stale()` function is called unconditionally before the live-derivation guard. If it crashes on edge cases (e.g., `(run_dir / "state")` is a file instead of a directory, or permissions deny listing), the fallback derivation is never reached. The selftest only exercises clean directories.
- The report.md `## Verification` section claims specific output strings for the hamastar run (`[Root｜调度] ... 待验证入口 5 个 ... 阻断 3 个 ... 下一步 分派子任务`), but these strings are part of the operator-facing claim, not backed by a captured artifact. The actual statusline output may have slightly different formatting (e.g., ANSI escapes, whitespace) that was trimmed in the report.

## Context-limit notes
- I could not read `tools/xunji_statusline.py` directly (permission denied in this non-interactive session) to verify the full `_state_stale` implementation or the `_phase`/`_blocker_summary` functions. My analysis relies on the diff artifact and review bundle JSON. If `_state_stale` has edge-case guards not visible in the diff, my concern about the unconditional call may be unfounded.
- I could not verify that `loop_state.derive()` and `run_controller.derive()` exist with the exact signatures used. The selftest passing is indirect evidence they do, but I cannot independently confirm.
- This is a code-maintenance run, not a web-pentest run. The standard pentest rubric categories (false positives, coverage ledger vs recon assets, artifact artifacts like `probe_*.html` or `.replay.json`) do not apply. I adapted the rubric to the code-review context.