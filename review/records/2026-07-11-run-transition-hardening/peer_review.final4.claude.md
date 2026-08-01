# Peer Review — 2026-07-11-run-transition-hardening

_backend: claude:code-cli · 2026-07-11T02:47Z_
> 候选, 非裁决。driver 须逐条过证据门: 不盲从(驳工具/语境误报), 不忽视(采纳真盲补)。

## Verdict: WARN

_backend: claude:code-cli_  
_brain: codex_  
_bundle_hash: 65075c1202db854de49ebdd5ebdea86c27483800_  
_evidence_index_hash: 9ee7ed0e57e8377a44395927ec8f4525248b29ef_  

## Findings
- (none)

## Blind-spot check
- **`decide()` dead code is the most actionable finding none of the Claude reviews caught.** Every Claude reviewer (round1, round2, final, final2, final3) read this code and accepted the selftest's assertion that `decide(True, 1, True) == "notify"` is correct — without noticing that `main()` exits before `decide()` is ever called. This is a classic "selftests create a false sense of coverage" blind spot where same-model reviewers share the same assumption: that if a function is tested, it must be reachable.
- **The 57/57 selftest output (`evidence/selftest_all.log`) masks component-level gaps.** The `turn_contract` suite (0.5s), `output_gate` suite (0.4s), and `run_gate` suite (1.2s) each pass individually. But their combined execution time of ~2.1s for what are now hundreds of assertions across multiple subprocess invocations suggests most tests exercise narrow code paths. The dead-code finding above is one consequence — the `decide()` selftest exercises a code path that `main()` makes unreachable, and no test catches this because no test runs `main()` with `stop_hook_active=True` AND `is_final=True` AND `check_rc != 0` through the actual event-processing flow (the subprocess test exits before reaching `decide()`).
- **The review process itself shows a non-converging pattern across 6 rounds** (round1, round2-arkcli, final, final2, final3, now me). Each round found issues the previous round missed, and the final3 review added 6 PR findings plus 5 blind-spot notes. This suggests the review surface is large enough that single-reviewer passes have systematic gaps. The arkcli heterogeneous panel was supposed to help but failed completely (ARK 500 errors) — leaving only Claude-on-Claude review, which is structurally limited.
- **The `CLEAR_ACTIVE_RE` regex** (`evidence/transition-core.diff:177-181`) only matches `(?:清除|清空|取消|移除).{0,20}(?:active[ -]?run|运行指针)` and English equivalents. An operator typing "删掉 active 指针" (delete active pointer) or "把运行指针重置" (reset the run pointer) would not match this regex. The `--clear-active` command would be blocked by PreToolUse because the prompt doesn't match the allowlist. Defaults to safe denial, but represents a completeness gap in operator intent recognition.
- **The `_lifecycle_target_name` parser's `--date` handling** (`evidence/transition-core.diff:354-367`) uses `re.sub(r"[^A-Za-z0-9_-]", "_", positionals[0])` to sanitize the slug. If the slug contains non-ASCII characters (e.g., Chinese characters in a slug), they would be replaced with underscores, creating an unexpected run directory name. The sanitized name would differ from what the operator expects, potentially causing confusion when the claim's target name doesn't match. This edge case is untested.

## Context-limit notes
- I cannot access live source files outside the review directory (`.claude/hooks/output_gate.py`, `.claude/hooks/run_gate.py`, `tools/turn_contract.py`, `tools/xunji_statusline.py`) — all analysis relies on evidence diffs and selftest log. If the live code has been modified since the evidence was captured, my dead-code finding about `decide()` may be stale.
- The `_active_protocol_fronts` function I flagged as invisible may be a simple wrapper that reads `frontier.md` and extracts open front IDs — without seeing its implementation, I cannot assess whether it could return incorrect results. My WARN is about the lack of visibility, not a confirmed bug.
- Chinese-language policy text (CLAUDE.md additions, hook denial messages) may contain operational nuance I partially miss. My regex over-match analysis for `RUN_TRANSITION_RE` is based on pattern matching, not native Chinese semantic understanding.
- This is a code-maintenance run (no web target), so rubric items 2 (coverage ledger), 3 (false positives), and 6 (missed surface) are adapted accordingly.