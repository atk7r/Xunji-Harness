# Peer Review Panel — 2026-07-13-statusline-simplification

_backend: panel:arkcli+claude · 2026-07-13T03:48Z_
> 候选, 非裁决。driver 须逐条过证据门。

## Verdict: WARN

_backend: panel:arkcli+claude_  
_brain: codex_  
_bundle_hash: bad2250c00693074f03016c23669b256693ff6e1_  
_evidence_index_hash: 48d79e7a87f278d0bac715ca515abb4c05cdb454_  

## Findings
- [WARN] PR-001 E-002 regression verification is confirmed at certainty 1.0 solely from selftest.log, an environment-generated execution artifact, without a static reference to the selftest assertions. | Evidence: evidence_index:E-002, selftest.log | Why: [panel:arkcli] [arkcli:kimi-k2.7-code] Evidence discipline states environment-provided artifacts are never confirmation on their own. The log shows '1 passed' but does not expose which assertions ran; the assertion code in reviewed.diff is the real evidence and is not cited by E-002.
- [WARN] PR-002 The selftest mutates the operator's persistent active-run pointer (.claude/xunji_active_run) during execution, contrary to review question 4's expectation that selftests not mutate it. | Evidence: reviewed.diff:@@ -548,28 +388,30 @@ def _selftest() -> int:, reviewed.diff:set_active_run(str(run)) and clear_active_run() calls in _selftest | Why: [panel:arkcli] [arkcli:kimi-k2.7-code] The test saves the old pointer and restores it in a finally block, but it still writes/clears the real .claude/xunji_active_run. A crash or concurrent process could observe or leave a changed active run.
- [WARN] PR-003 The selftest does not exercise Setup, Interrupted, Cached, or fallback phase states, so the claim that these behaviors are preserved (review question 3) is under-verified. | Evidence: reviewed.diff:@@ -548,28 +388,30 @@ def _selftest() -> int: checks list, selftest.log:manual Setup render | Why: [panel:arkcli] [arkcli:kimi-k2.7-code] The selftest checks only Hunter and Paused phases. The manual render shows Setup but is a single observation. The _phase derivation logic is not visible in the provided diff hunks, so preservation of the remaining states is assumed rather than demonstrated.
- [WARN] PR-004 arkcli panel had backend errors; review is partial | Evidence: glm-5.2: parse error; output tail: oot)}}`. Wait, if `clear_active_run()` is called, then `active_run()` returns `None`. `render_statusline(root_current)` will return `""`. Good.
But wait! The old code tested:
```python
-        future = max(p.stat().st_mtime for p in watched) + 5
-        os.utime(run / "frontier.md", (future, future))
-        stale_plain = render_statusline(root_current, color=False)
```
The new code replaced this with `clear_active_run()` and `no_active = render_statusline(root_current, color=False)`. This is | Why: [panel:arkcli] At least one arkcli reviewer failed, so PASS only means the completed panel members found no blocker.

## Blind-spot check
- [claude] **CLAUDE.md not updated**: This is the most concrete miss. Every session loads CLAUDE.md; the description there is now wrong. The author changed SKILL.md (the skill's own doc), AI_ENV_SETUP.md, and WORKFLOW.md — but skipped the primary project instruction file. This looks like a genuine oversight rather than an intentional omission.
- [claude] **Statusline health signals gone**: The old statusline had three distinct health indicators (interrupted, stale-cache, derivation-failed). All three were removed in the simplification. If the intended contract is that phase banners handle this, then a cross-reference from the statusline doc to "check phase banners for health signals" would be appropriate — but no such cross-reference exists in the updated docs.
- [claude] **Selftest coverage of stale/interrupted paths removed but not replaced**: The old selftest had specific assertions for stale-cache behavior (`"现场推导" in stale_plain`) and next-action behavior (`"下一步 F-004 接口枚举" in plain`). The new selftest correctly tests the new concise format, but no test verifies that the `_journal_summary()` interrupted key still gets populated — it's dead output but might matter to downstream consumers (e.g., phase banners, loop journal readers). If nothing else consumes that key, it's dead code that should be cleaned up; if something else does consume it, the statusline's silent removal of the display might surprise operators who relied on the statusline for that signal.
- [claude] **`_derived_loop_state()` still imports `loop_state` lazily**: This is unchanged behavior and works, but it's worth noting that the function now has a narrower contract (only loop data, no controller). The docstring correctly says "Controller, coverage, Agent, and next-action derivations are deliberately outside statusline scope" — this is clear and intentional.
- [claude] **No regression test for `_journal_summary()` output integrity**: Since the interrupt key is still computed but no longer displayed, there's no selftest assertion that `_journal_summary()` continues to produce a correct `"interrupted"` value. This is minor since the function body wasn't changed, but it's a coverage gap.

## Context-limit notes
- [arkcli] glm-5.2: parse error; output tail: oot)}}`. Wait, if `clear_active_run()` is called, then `active_run()` returns `None`. `render_statusline(root_current)` will return `""`. Good.
But wait! The old code tested:
```python
-        future = max(p.stat().st_mtime for p in watched) + 5
-        os.utime(run / "frontier.md", (future, future))
-        stale_plain = render_statusline(root_current, color=False)
```
The new code replaced this with `clear_active_run()` and `no_active = render_statusline(root_current, color=False)`. This is
- [claude] I cannot directly grep CLAUDE.md to verify its current content, but the system prompt context includes CLAUDE.md verbatim, and it clearly describes the old multi-field statusline behavior. The diff does not list CLAUDE.md as a changed file (`changed_files_count: 4`, no CLAUDE.md).
- [claude] I cannot inspect `_phase()` or `_journal_summary()` in full since they weren't in the diff, but the diff shows they weren't modified. My analysis of phase-preservation is based on the diff showing no changes to those functions.
- [claude] The `loop_state.derive()` function and `run_controller.derive()` function are referenced but not included in this review bundle — I trust the selftest passing (60/60) as evidence that the lifecycle is intact.
- [claude] The review scope explicitly says "Do not evaluate live pentest evidence; this is repository maintenance only." I've respected this.