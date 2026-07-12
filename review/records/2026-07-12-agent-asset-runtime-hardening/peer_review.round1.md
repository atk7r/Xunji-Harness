# Peer Review Panel — 2026-07-12-agent-asset-runtime-hardening

_backend: panel:claude · 2026-07-12T13:30Z_
> 候选, 非裁决。driver 须逐条过证据门。

## Verdict: NEEDS_DRIVER

_backend: panel:claude_
_brain: codex_
_bundle_hash: 5f959a270ccb380efe730435ff8082dd41dd3d5d_
_evidence_index_hash: 2ae349e09f0f4c03fb50a3c2ab53b291d05c9089_

## Findings
- [WARN] PR-001 review panel had backend errors; aggregation is partial | Evidence: arkcli: ERROR arkcli panel 全部模型失败: kimi-k2.7-code: timeout >300s; glm-5.2: parse error; output tail:    ```python
    def _unassigned_assets(run_dir: Path) -> list[str]:
        try:
            import coverage_matrix
            data = coverage_matrix.derive(run_dir)
        except Exception:
            return []
        return [str(item.get("asset") or "") for item in data.get("accounting_gaps", [])
                if str(item.get("asset") or "")]
    ```
    If `coverage_matrix` import fails, it returns an empty list, meaning the asset coverage gate is silently bypassed. This is a fail-open | Why: At least one requested heterogeneous reviewer failed or was unavailable.

## Blind-spot check
- [claude] **No actual live Agent lifecycle exercised**: The entire evidence chain depends on selftests that fabricate hook events. None of the tests run a real Claude `Agent` tool call, wait for real `SubagentStop`, or exercise the actual hook pipeline. A real integration test with `claude --agent` is the only way to catch timing issues, missing fields in real hook payloads, or the hook event JSON schema not matching the normalization code's expectations.
- [claude] **`_event_known_hosts` token matching fragility**: The function uses regex word-boundary matching (`(?<![\w.\-])hostname(?![\w.\-])`) which would fail for hostnames that contain dots as part of the boundary logic. More critically, it only searches against coverage.json's first matching file (the `break` on line 157 of turn_contract.diff). If coverage.json is at a nested path that should be checked first but is sorted after the root, the root's entries are used — potentially missing hosts declared in subdirectories.
- [claude] **No test for the SubagentStop-after-PostToolUse race**: The selftest at `evidence/runtime-receipts.diff:445-523` always injects PostToolUse before SubagentStop. The reverse order (stop before launch) is never tested. This is the most likely edge case in the code but has zero test coverage.
- [claude] **Documentation drift between `.agents/skills/` and `.claude/skills/`**: Both directories contain `xunji-agent-board/SKILL.md` files that were both updated with different content. The `.agents/` version (line 1 of driver-docs.diff) adds new output contract text, while `.claude/` version (line 8 of driver-docs.diff) changes the asset package and asset token format. It's unclear which one takes precedence — if they diverge, the Agent receiving `.agents/` vs Root reading `.claude/` could have conflicting rules.
- [claude] **DIFF artifact save path**: The `_diff_side_save` function (probe.py diff line 108-114) handles the case where `base` has no suffix — it appends `.b` to the filename. But if `base = "evidence/boolean"` (no extension), the B-side becomes `"evidence/boolean.b"` while the A-side stays as `"evidence/boolean"`. The replay file would be `"evidence/boolean.replay.json"` shared by both sides — only the B-side replay would overwrite the A-side replay. This is a minor artifact collision bug.

## Context-limit notes
- [claude] My analysis relies on the review bundle's embedded diff excerpts (truncated at ~14K chars per artifact). The full diffs for `workers.diff` and `turn-contract.diff` likely contain additional context I haven't seen, particularly in the `_selftest` functions.
- [claude] I cannot verify whether the live `tools/coverage_matrix.py` actually has the stale `declared_tokens` bug or if the diff format misrepresents indentation — my finding is based on the unified diff as provided.
- [claude] The Chinese-language comments in documentation (CLAUDE.md, docs/*.md) may contain nuance I don't fully parse. My documentation-drift assessment is based on structural changes (added sections, changed tokens, modified commands) rather than semantic nuance of Chinese policy language.
- [claude] I cannot check whether `agents/skills/xunji-agent-board/SKILL.md` and `.claude/skills/xunji-agent-board/SKILL.md` are currently identical in the live tree without Read access to the live files (denied in this read-only mode).
- arkcli: ERROR arkcli panel 全部模型失败: kimi-k2.7-code: timeout >300s; glm-5.2: parse error; output tail:    ```python
    def _unassigned_assets(run_dir: Path) -> list[str]:
        try:
            import coverage_matrix
            data = coverage_matrix.derive(run_dir)
        except Exception:
            return []
        return [str(item.get("asset") or "") for item in data.get("accounting_gaps", [])
                if str(item.get("asset") or "")]
    ```
    If `coverage_matrix` import fails, it returns an empty list, meaning the asset coverage gate is silently bypassed. This is a fail-open
- panel completed 1/2 required heterogeneous backends

> ERROR: arkcli: ERROR arkcli panel 全部模型失败: kimi-k2.7-code: timeout >300s; glm-5.2: parse error; output tail:    ```python
    def _unassigned_assets(run_dir: Path) -> list[str]:
        try:
            import coverage_matrix
            data = coverage_matrix.derive(run_dir)
        except Exception:
            return []
        return [str(item.get("asset") or "") for item in data.get("accounting_gaps", [])
                if str(item.get("asset") or "")]
    ```
    If `coverage_matrix` import fails, it returns an empty list, meaning the asset coverage gate is silently bypassed. This is a fail-open