# Peer Review — 2026-07-09-statusline-live-derive-fix

_backend: claude:code-cli · 2026-07-08T19:02Z_
> 候选, 非裁决。driver 须逐条过证据门: 不盲从(驳工具/语境误报), 不忽视(采纳真盲补)。

## Verdict: WARN

_backend: claude:code-cli_
_brain: codex_
_bundle_hash: f03000d215b887b8e62e9199a2308503846f6929_
_evidence_index_hash: c6a1bc58a2917a0ea1ab60c2fbc9778a8da37c30_

## Findings
- (none)

## Blind-spot check
- **The fix relies on `loop_state.derive(write=False)` respecting the `write` parameter.** The selftest verifies that no files are written to the run directory during statusline rendering, but it can only catch writes to the test fixture directory. If `loop_state.derive()` writes to a location outside the run directory (e.g., a global state file, a temp directory, or stdout), the read-only test would pass while side effects occurred. This is inherent to any dependency trust, but worth noting since the `write=False` contract is not independently verified by the statusline test suite.
- **The selftest fixture for "missing cache" creates a journal with only two events (phase_start + phase_end, both Setup).** This tests the Setup-journal-note suppression, but it doesn't test what happens when the journal has intermixed events (e.g., Setup phase_start → a plan event → Setup phase_end). The `_last_plan_note` function picks the *last* event, so if Setup phase_end is the last event, it's correctly suppressed. But if a plan/action event from Setup exists after the phase_end (which shouldn't happen in a well-formed journal but could in edge cases), it wouldn't be filtered by the phase check.
- **No test for the case where `loop_data` is non-empty but `controller` is empty (or vice versa).** The condition `if stale or not loop_data or not controller` triggers derivation when EITHER is missing. But the code only replaces both if BOTH derivations succeed (`if derived_loop is not None and derived_controller is not None`). If only one succeeds, the fallback is partially applied, potentially mixing derived data with empty/stale cached data.

## Context-limit notes
- I could not read `tools/xunji_statusline.py` directly (permission denied in non-interactive mode). My analysis of `_state_stale()` relies entirely on the diff artifact. The function itself is not modified by this change, so its implementation is invisible to me. If `_state_stale()` already has internal try/except guards against filesystem edge cases, my WARN about its crash risk may be unfounded. The diff shows only the call site, not the implementation.
- I could not verify the actual implementations of `loop_state.derive()` and `run_controller.derive()` to confirm their signatures match the calls in `_derived_state`. The selftest passing is indirect evidence.
- This is a code-maintenance run, not a web-pentest run. Standard rubric items about false positives, coverage ledger vs. recon assets, and target-side artifacts (probe_*.html, .replay.json) do not apply. I adapted the rubric to the code-review context.
- The Chinese-language journal notes and statusline output were correctly interpreted for this review, but subtle nuance in phrasing (e.g., `分派子任务` vs. `继续验证可行动入口` as correct next-action text) may have been missed as I cannot independently run the controller to verify the expected output.