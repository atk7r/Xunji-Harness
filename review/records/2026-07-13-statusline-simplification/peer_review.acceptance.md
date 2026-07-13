# Peer Review Panel — 2026-07-13-statusline-simplification

_backend: panel:arkcli+claude · 2026-07-13T05:40Z_
> 候选, 非裁决。driver 须逐条过证据门。

## Verdict: WARN

_backend: panel:arkcli+claude_
_brain: codex_
_bundle_hash: 2ac9ab5f5ba9553b8b2e4d96aea0ea34ffb6e18e_
_evidence_index_hash: f322dcce4eae29e630ecf833db2cecedb3de7938_

## Findings
- [WARN] PR-001 arkcli panel had backend errors; review is partial | Evidence: glm-5.2: parse error; output tail:  output. This is reasonable.

4. **The `nested_workspace` test case:**
```python
nested_workspace = render_statusline(
    {"workspace": {"current_dir": str(ROOT / "tools")}}, color=False)
```
And the check:
```python
("nested Xunji workspace renders the selected run",
 nested_workspace == f"[Xunji-status] [Hunter｜验证] {run.name}"),
```

This tests that a nested directory within the Xunji project still renders. This depends on `_is_xunji_context()` recognizing `ROOT / "tools"` as a Xunji context. | Why: [panel:arkcli] At least one arkcli reviewer failed, so PASS only means the completed panel members found no blocker.

## Blind-spot check
- [arkcli] [kimi-k2.7-code] No .claude/settings.json artifact is included in the evidence bundle, so the actual statusLine command wiring (arguments, stdin, env) was not cross-checked against the code. The unit/selftest evidence is strong, but a true integration artifact would close this gap.
- [arkcli] [kimi-k2.7-code] _phase() and _is_xunji_context() are not excerpted in the bundle; the review relies on the passing selftest to imply they handle nested workspaces, pause/interrupt, and fallback correctly. Direct artifact lines for those functions would make the evidence gate tighter.
- [claude] **The subprocess CLI test was REPLACED, not removed.** Final peer review round 4 blind-spot says "the hook invocation path is now entirely untested." This is factually incorrect. `statusline.diff:361-377` shows a new subprocess test that invokes `main([])` via `sys.executable -c` with stdin JSON — this IS the production hook path. The old test ran `Path(__file__).resolve()` as a script; the new test calls `main()` via import. Both exercise stdin→stdout. The final review's highest-priority blind-spot is based on a reading error.
- [claude] **`_journal_summary()` is NOT dead code.** Its `interrupted` key is consumed by `_phase()` (unchanged per diff). The `paused` key is also consumed by `_phase()`. The function call on line 268 of the diff is necessary and correct. However, there's a subtle coupling: if someone later removes the `interrupted` computation from `_journal_summary()` because "the statusline doesn't display it," the `_phase()` function's interruption-detection would silently break. A cross-reference comment in `_journal_summary()` noting that `_phase()` consumes `interrupted` would prevent this.
- [claude] **The `_is_xunji_context` function's upward-tree traversal means opening any subdirectory of the Xunji project (including `tools/`, `runs/some-run/`, etc.) will still display the active run's statusline.** This is tested and intentional (`nested_workspace` check at line 482-483), but it means an operator who `cd`s into a specific run directory to inspect files will see another run's name in the statusline if `active_run()` points elsewhere. Minor confusion risk.
- [claude] **The evidence chain is structurally appropriate for a maintenance review.** E-001 cites `statusline.diff` + `docs.diff` (static proof of what changed) + `selftest.log` (execution corroboration). For a pentest, certainty 1.0 from a single execution log would violate the evidence discipline, but for a deterministic, verifiable code change backed by static diffs and a 60/60 full-suite pass, the combined evidence meets the bar. E-003 is the exception (see PR finding above).
- [claude] **The positive negative-test design is a model of good practice.** Writing populated `controller.shadow.json` (with a blocker string), `assignments.json` (with active agents), and `asset_ledger.json` (with summary data) — then asserting `" | " not in plain` — is a robust field-leakage regression guard. This explicitly proves that legacy summary data cannot accidentally reappear in the simplified output.
- [claude] **The `failed_derive_plain` check at line 501-502 tests the mock path correctly.** When `_derived_loop_state` is replaced with `lambda _run_dir: (None, "RuntimeError")`, the fallback to `_load_json({})` produces `{}`, and `_phase({}, journal, missing_cache)` returns `"Idle"`. The assertion `failed_derive_plain == f"[Xunji-status] [Idle｜空闲] {missing_cache.name}"` correctly captures this behavior — the concern is that this behavior (silent Idle masking a crash) is the wrong trade-off, not that the test is wrong.

## Context-limit notes
- [arkcli] glm-5.2: parse error; output tail:  output. This is reasonable.

4. **The `nested_workspace` test case:**
```python
nested_workspace = render_statusline(
    {"workspace": {"current_dir": str(ROOT / "tools")}}, color=False)
```
And the check:
```python
("nested Xunji workspace renders the selected run",
 nested_workspace == f"[Xunji-status] [Hunter｜验证] {run.name}"),
```

This tests that a nested directory within the Xunji project still renders. This depends on `_is_xunji_context()` recognizing `ROOT / "tools"` as a Xunji context.
- [claude] I cannot directly Grep/Read the live `tools/xunji_statusline.py` or `CLAUDE.md` (hooks denied both). My analysis relies entirely on the review bundle artifacts: `statusline.diff`, `docs.diff`, `reviewed.diff`, `selftest.log`, `claude_statusline_contract.txt`, `evidence.md`, `report.md`, `evidence.json`, and the 4 peer review rounds. The system-prompt-injected CLAUDE.md confirms the live update is present.
- [claude] The `_phase()` and `_journal_summary()` function bodies are not in any diff — they appear unchanged. I rely on the diffs showing no hunks for these functions plus the `60/60` full-suite selftest pass as indirect evidence they were not modified.
- [claude] This is a repository maintenance change, not a pentest. Evidence discipline rules (certainty ≥ 0.8 = confirmed, no single-observation confirmation) are applied with appropriate judgment — static diffs plus passing test execution are stronger evidence than an environment-provided log alone would be for a live target.
- [claude] Chinese documentation in `docs/WORKFLOW.md:82-104` and `docs/AI_ENV_SETUP.md:53-74` was read for consistency with the code changes. The simplified descriptions are accurate; I may have missed operator-facing nuance a native speaker would catch.
