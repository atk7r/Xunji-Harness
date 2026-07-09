# Peer Review Panel — 2026-07-10-claude-flow-enforcement

_backend: panel:arkcli+claude · 2026-07-09T20:21Z_
> 候选, 非裁决。driver 须逐条过证据门。

## Verdict: BLOCKER

_backend: panel:arkcli+claude_  
_brain: codex_  
_bundle_hash: f10df3f874ebfa8de43e81ed5ef2e085d8e3799d_  
_evidence_index_hash: 0c4f279f22848adf2a472dbb755cec04397821b9_  

## Findings
- [BLOCKER] PR-001 output_gate.py 的 Coda 多动作分隔符正则过窄，无法落实单动作 Stop 协议 | Evidence: evidence_index:E-001, output_gate.diff, disposition.md | Why: [panel:arkcli] [arkcli:kimi-k2.7-code] 当前正则仅拦截 `、|&&|\s+\+\s|(?:以及|并且|然后|随后|再去|and then)`，遗漏 `，`、`；`、`/`、`与`、`及`、`或`、`再`、`接着`、`同时` 等高频中文分隔。模型可发出 `下一行动：运行 check_run 与 peer_review` 或 `下一行动：扫描 80，443 端口` 等仍通过校验的 Coda，实质包含多个动作。这与操作者“maximize mechanical compliance”的目标冲突，也与 disposition.md 中“multiple F-ids and actual action separators remain blocked”的声明不符。
- [WARN] PR-002 arkcli panel had backend errors; review is partial | Evidence: minimax-m3: parse error; output tail: ction? The Coda would be about checking the closure. The code says `if not state or state.get("loop_complete"): return ""` so if loop_complete is True, it returns early. But if loop_complete is False and there are no active fronts, the code falls through to the `not active and cited_fronts` check.

Actually, looking at the flow: if `not state or state.get("loop_complete")` returns "" (no block). Otherwise, it checks coda_error, then if active, then if not active but cited_fronts. So if there are; glm-5.2: parse error; output tail: se` and then does `os.chmod(tmp_name, 0o600)`. But between `NamedTemporaryFile` creation and `os.chmod`, the file exists with default permissions (typically 0o600 on Linux for temp files, but on some systems could be 0o644). There's a brief window where the file might be world-readable. This is a minor TOCTOU issue.

   Another blind spot: `_cookie_dict_from_set_cookies` checks `str(morsel["max-age"] or "").strip() == "0"` for deletion, but doesn't check `expires` in the past. Some servers use ` | Why: [panel:arkcli] At least one arkcli reviewer failed, so PASS only means the completed panel members found no blocker.

## Blind-spot check
- [arkcli] [kimi-k2.7-code] 本 run 为框架/代码审计，不是外部渗透测试，surface/ledger/RCE/getshell/浅关闭等检查项基本不适用。
- [arkcli] [kimi-k2.7-code] output_gate 的模糊 Coda 检测可能无法覆盖“按当前情况继续”等换壳表述。
- [arkcli] [kimi-k2.7-code] active-run 指针虽被限制在 runs_root 内，但缺少时间戳或所有权 freshness 校验。
- [arkcli] [kimi-k2.7-code] reviewed.diff 在面板展示中被截断，但已拆分为多个符合单文件上限的组件 diff。
- [arkcli] [kimi-k2.7-code] selftest_all.log 是环境产物，确认应依赖 diff 工件及其中嵌入的聚焦自测。
- [claude] **The diff correctly fixes all 6 audit gaps listed in `context.md:15-29`** — explicit active-run pointer resolution, Coda enforcement for closure candidates, Normal-mode closure now uses `decision: block` instead of `systemMessage`, wide active-status counting includes probing/working/type-a, per-item retrospective validation with fix proof/residual risk, coverage sync no longer invents pseudo-verdicts, and probe cookie handling is browser-correct with atomic jar writes. No missed fixes.
- [claude] **The `_merge_cookies_into_headers` signature change** (adding `*, prefer_cookies: bool = False`) is backward-compatible: the `*` makes the new parameter keyword-only, and no existing caller passes it. All 54 selftests pass including probe's cookie-chain selftest, confirming no regression.
- [claude] **The `_retro_framework_items` splitter** on `check_run.diff:89-98` correctly handles: numbered items (`1.`, `2)`), heading-based items (`###`), and `Problem:` structured fields. The selftest at lines 254-268 adds regression coverage for both "Second tool issue: missing Status" (numbered item without Status) and "Problem: second parser issue: missing Status" (Problem field without Status). The legacy fallback (one unstructured paragraph → one item, one Status) is the documented tradeoff in `disposition.md:42-44`.
- [claude] **anti_drift.py path traversal hardening**: `_run_from_pointer` on `anti_drift.diff:37-63` resolves the pointer path and validates it's inside `runs_root` via `run_dir.relative_to(root)`. Symlink traversal is also blocked because `resolve()` follows symlinks before the `relative_to()` check. The selftest at line 106-107 confirms `outside pointer is ignored`. No path traversal risk.
- [claude] **coverage_matrix.py source tracking**: The new `verdict_source` / `tested_groups_source` fields on `coverage_matrix.diff:26-61` create a clean ownership model — sync only writes when `verdict_source == "coverage_matrix_sync"` or there's no existing verdict. Manual verdicts are preserved. Legacy pseudo-verdicts (`evidence-recorded`, `reported`) are migrated away with a warning. The selftest confirms: evidence/report mentions mark `examined=True` but never invent verdicts, and legacy verdicts are cleaned. No coverage suppression risk.
- [claude] **No false-positive blocks identified**: The `vague_only` set and `vague_phrase` regex in output_gate.py are carefully scoped — a legitimate Coda like `下一行动: 根据前面的结果继续用 render 验证 F-001` passes because `concrete_anchor` detects `F-001` and `render`. The `、` (enumeration comma) multi-action detector correctly blocks `运行 check_run、回放验证和独立复审` while allowing `验证 F-001 登录和会话边界` (single front, natural conjunction). The selftest at `output_gate.diff:225-226` explicitly tests this distinction.
- [claude] **The `task_name` mismatch in selftest at `run_gate.diff:164-166`**: The test string writes `## Independent Review\n- Reviewer: test\n- Verdict: PASS\n` and expects `_normal_closure_prerequisite` to detect missing CodexCompletionReview. This correctly tests the layered check: independent review exists, but codex completion review doesn't. ✓

## Context-limit notes
- [arkcli] minimax-m3: parse error; output tail: ction? The Coda would be about checking the closure. The code says `if not state or state.get("loop_complete"): return ""` so if loop_complete is True, it returns early. But if loop_complete is False and there are no active fronts, the code falls through to the `not active and cited_fronts` check.

Actually, looking at the flow: if `not state or state.get("loop_complete")` returns "" (no block). Otherwise, it checks coda_error, then if active, then if not active but cited_fronts. So if there are
- [arkcli] glm-5.2: parse error; output tail: se` and then does `os.chmod(tmp_name, 0o600)`. But between `NamedTemporaryFile` creation and `os.chmod`, the file exists with default permissions (typically 0o600 on Linux for temp files, but on some systems could be 0o644). There's a brief window where the file might be world-readable. This is a minor TOCTOU issue.

   Another blind spot: `_cookie_dict_from_set_cookies` checks `str(morsel["max-age"] or "").strip() == "0"` for deletion, but doesn't check `expires` in the past. Some servers use `
- [claude] This is a framework maintenance review, not a pentest run — the traditional pentest rubric items (coverage ledger of recon assets, missed surface, shallow closure of attack fronts) do not apply. I've adapted my review to the actual scope: framework correctness, regression safety, and enforcement bypass analysis.
- [claude] I cannot verify whether `_merge_cookies_into_headers` has callers outside the diff that might break due to the signature change — the `*` makes `prefer_cookies` keyword-only, so all existing positional callers remain compatible. The 54/0 selftest pass provides strong evidence no breakage occurred.
- [claude] The `task_name` discrepancy between the bundle reference to `_has_codex_completion_review` field-mode and whether check_run.py independently validates CodexCompletionReview: I verified that `check_run.diff` does NOT add a `CodexCompletionReview` content check to `check_closure_discipline` — the only closure discipline change is the independent review gate upgrade at lines 181-189. CodexCompletionReview validation lives solely in `run_gate.py`, which makes the field-mode leniency in run_gate a genuine single-point-of-failure.
- [claude] Chinese-language regex patterns in output_gate (vague phrase detection, multi-action detection) might have edge cases I cannot fully assess as a non-native speaker. The selftest coverage appears comprehensive for the documented bypass patterns.
- [claude] The `peer_review` heading + `_backend:` meta path in `check_run.diff:38,44` uses the regex `(?im)^_backend\s*[:：]\s*([^_\n]+)_` which expects the backend name to be wrapped in underscores (e.g., `_backend: claude_`). If peer_review.py's output format ever drops the trailing underscore, this path would fail and fall through to other identity checks — not a safety regression, just a potential future maintenance surprise.