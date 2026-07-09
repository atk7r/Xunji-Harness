# Peer Review Panel — 2026-07-10-claude-flow-enforcement

_backend: panel:arkcli+claude · 2026-07-09T19:50Z_
> 候选, 非裁决。driver 须逐条过证据门。

## Verdict: BLOCKER

_backend: panel:arkcli+claude_  
_brain: codex_  
_bundle_hash: 75c0a1cbf70d306acad2c9818e664644a3720aa7_  
_evidence_index_hash: 3b2c4de172651fd1498fa1d55b09ad4b31ae3105_  

## Findings
- [WARN] PR-001 Probe.py cookie-chain / atomic-jar fixes claimed in E-001 are not independently verifiable from the supplied bundle excerpt | Evidence: reviewed.diff:tools/probe.py hunks @@ -307,12 +308,25 @@ etc. (truncated before changed body); evidence_index:E-001 | Why: [panel:arkcli] [arkcli:kimi-k2.7-code] The bundle excerpt only lists probe.py hunk headers; the actual implementations of _save_cookie_jar, Set-Cookie precedence, and explicit-Cookie handling are missing, so a reviewer cannot confirm the stated gaps were fixed.
- [WARN] PR-002 Active-run pointer containment and stale-pointer fallback are asserted but not demonstrated in the visible diff | Evidence: context.md (Review question 2); reviewed.diff:tools/anti_drift.py / .claude/hooks/output_gate.py active-run code not shown in excerpt | Why: [panel:arkcli] [arkcli:kimi-k2.7-code] One of the stated review questions is whether XUNJI_ACTIVE_RUN_FILE stays inside RUNS_ROOT and falls back safely, but the excerpt does not contain the pointer-resolution implementation.
- [WARN] PR-003 output_gate._turn_coda's "vague continuation" regex is over-broad and may block legitimate concrete Codas | Evidence: reviewed.diff:.claude/hooks/output_gate.py hunk @@ -103,15 +106,47 @@ (_turn_coda paraphrase regex) | Why: [panel:arkcli] [arkcli:kimi-k2.7-code] A Coda such as "下一行动：根据前面的结果继续用 render 验证 F-001" matches the reference-to-prior + continue pattern and would be rejected even though it names a concrete tool and front.
- [WARN] PR-004 output_gate._turn_coda's multi-action regex rejects conjunctions inside a single concrete action | Evidence: reviewed.diff:.claude/hooks/output_gate.py hunk @@ -103,15 +106,47 @@ (_turn_coda multi-action check) | Why: [panel:arkcli] [arkcli:kimi-k2.7-code] Codas like "下一行动：验证 F-001 和 F-002 的响应差异" or "先检查日志然后再运行工具" contain 和/然后 and would be blocked as multi-action.
- [WARN] PR-005 output_gate._protocol_block_reason process_anchor regex allows bypass via the substring "agent" | Evidence: reviewed.diff:.claude/hooks/output_gate.py hunk @@ -146,36 +181,71 @@ (process_anchor regex) | Why: [panel:arkcli] [arkcli:kimi-k2.7-code] The "Agent" alternative is case-insensitive and unanchored, matching words like "management"; a Coda such as "下一行动：运行 Agent" would satisfy the control-plane anchor while naming no concrete front or action.
- [WARN] PR-006 run_gate._fallback_status_is_active may count parenthetical closed/deferred notes as active | Evidence: reviewed.diff:.claude/hooks/run_gate.py hunk @@ -648,9 +653,22 @@ (_fallback_status_is_active) | Why: [panel:arkcli] [arkcli:kimi-k2.7-code] Tokenizing the first segment and checking set intersection means a status like "working (closed)" is treated as active because "working" is in the active set, despite the parenthetical closure note.
- [WARN] PR-007 report.md does not carry the confirmed evidence entries E-001/E-002 into findings | Evidence: report.md (scope only); evidence_index:E-001; evidence_index:E-002 | Why: [panel:arkcli] [arkcli:kimi-k2.7-code] The review note only states scope and instructs opening reviewed.diff; it does not summarize the confirmed frozen-diff finding or the full-regression result.
- [WARN] PR-008 arkcli panel had backend errors; review is partial | Evidence: minimax-m3: parse error; output tail: ns. The regex would NOT split on ASCII `(`. So tokens would be {"closed_type_b", "was", "blocked_type_a"}. The first token "closed_type_b" is NOT in the active set. But "blocked_type_a" IS. So the function would return True. But the test asserts it returns False!

   Wait, let me re-read the test:
   ```python
   checks.append(("fallback status parser ignores historical type-a note on closed status",
                  not _fallback_status_is_active("closed_type_b (was blocked_type_a)")))
   ```
; glm-5.2: parse error; output tail: ?** E-001 confirms that a frozen diff exists and matches the sha1. E-002 confirms that 54 selftests passed. But the report doesn't claim anything specific - it just says "review the diff." So the confirmed evidence is not being carried into any report finding.

4. **No claim integrity**: The report says "Do not treat this report as evidence; open reviewed.diff and cite specific files/hunks." But the report itself doesn't cite any specific files or hunks. It's a scope statement, not a review.

5. | Why: [panel:arkcli] At least one arkcli reviewer failed, so PASS only means the completed panel members found no blocker.

## Blind-spot check
- [arkcli] [kimi-k2.7-code] The review does not show verification that the new XUNJI_ACTIVE_RUN_FILE pointer is validated against RUNS_ROOT, sanitized for symlinks, or falls back safely when stale/missing.
- [arkcli] [kimi-k2.7-code] The probe.py cookie-chain fix is safety-critical, yet the actual changed code was truncated in the bundle — this is exactly the code an independent reviewer must open in full.
- [arkcli] [kimi-k2.7-code] No adversarial selftests are visible for output_gate bypasses using homoglyphs, zero-width characters in the Coda prefix, or control-plane anchor keywords.
- [arkcli] [kimi-k2.7-code] The hard Normal closure gate now requires the substrings "Independent Review" and "CodexCompletionReview"; the review did not assess whether these can be satisfied by prose mentions rather than real review artifacts.
- [arkcli] [kimi-k2.7-code] Only one happy-path integration test between output_gate and run_gate is shown; edge cases where output_gate passes a Coda that run_gate rejects for a different reason are not demonstrated.
- [claude] **No end-to-end integration test for the active-run pointer pipeline.** The selftest in output_gate.py (line 544-558) uses a pointer file set in the test's temp directory. The selftest in anti_drift.py (line 658-670) tests `find_active_run` with an explicit pointer. But there is no test that verifies: setup_run writes the pointer → anti_drift reads it → output_gate enforces Coda against the pointed run → run_gate enforces closure against the same run — all through the same pointer file, without manually injecting `XUNJI_ACTIVE_RUN_FILE` in each test. Each module tests its own pointer resolution in isolation; the cross-module contract is asserted but not integration-tested.
- [claude] **`_protocol_block_reason` returns empty string when `state` is empty AND when `loop_complete` is true.** The condition `if not state or state.get("loop_complete"): return ""` means that if `_protocol_state` returns `{}` (e.g., because `_loop_state` is `None` or `derive()` fails), the protocol enforcement is silently disabled for ALL output. This is the documented fail-open design ("output_gate is process discipline, not the safety boundary"), but a reviewer should flag that ANY transient failure in loop_state loading (file parse error, schema mismatch, import failure) silently disables ALL Coda enforcement for that turn — not just the F-id matching. The `protocol_violation` drift flag from anti_drift would still fire, but the hard block is gone.
- [claude] **The `_retro_framework_items` splitter may mis-split on unusual retrospective formats.** The splitter looks for `Problem:` lines first, then falls back to `### heading` or `1. numbered` patterns. If a retrospective has a free-form paragraph describing multiple issues with no heading/numbering structure, all issues are lumped into one item, and the splitter finds one Status line that "covers" the entire block — exactly the pattern the fix was designed to prevent. This is a format-enforcement issue: the retrospective template says "每条问题必须单独带 Status," but the parser can't enforce what it can't split. The blind-spot is that format flexibility and enforcement are in tension here.
- [claude] **Diff quality assessment (not in scope statement but reviewer should note):** The code changes in `reviewed.diff` are well-structured and defensive. Each gap from context.md is addressed with a specific code change + selftest. The `_turn_coda` function is comprehensive, `_normal_closure_prerequisite` correctly converts a soft `systemMessage` bypass to a hard `block`, the `_save_cookie_jar` atomic write with `0o600` is correct, and the coverage sync migration of `evidence-recorded`/`reported` pseudo-verdicts is clean. The selftest coverage added (~200 lines) tests positive cases, negative cases, edge cases (legacy migration, parenthetical status notes, completion marker release, wrong front ID rejection, control-plane object bypass). I found no logic bugs in the diff itself.

## Context-limit notes
- [arkcli] [kimi-k2.7-code] Chinese-language Coda style: my judgement of "vague" vs "concrete" may differ from project convention; some rejections I flag as false positives may be intentional.
- [arkcli] [kimi-k2.7-code] Local terms such as 下一行动, BLOCKED, 收口, and 独立复审 carry project-specific meaning I may not fully capture.
- [arkcli] [kimi-k2.7-code] The bundle excerpt for reviewed.diff is truncated before probe.py and anti_drift.py implementations, and evidence.md content is not included; findings are limited to visible excerpts and artifact hashes.
- [arkcli] minimax-m3: parse error; output tail: ns. The regex would NOT split on ASCII `(`. So tokens would be {"closed_type_b", "was", "blocked_type_a"}. The first token "closed_type_b" is NOT in the active set. But "blocked_type_a" IS. So the function would return True. But the test asserts it returns False!

   Wait, let me re-read the test:
   ```python
   checks.append(("fallback status parser ignores historical type-a note on closed status",
                  not _fallback_status_is_active("closed_type_b (was blocked_type_a)")))
   ```

- [arkcli] glm-5.2: parse error; output tail: ?** E-001 confirms that a frozen diff exists and matches the sha1. E-002 confirms that 54 selftests passed. But the report doesn't claim anything specific - it just says "review the diff." So the confirmed evidence is not being carried into any report finding.

4. **No claim integrity**: The report says "Do not treat this report as evidence; open reviewed.diff and cite specific files/hunks." But the report itself doesn't cite any specific files or hunks. It's a scope statement, not a review.

5.
- [claude] I am confident in my reading of all Chinese strings in the diff and evidence files. The Coda enforcement messages, retrospective validation error strings, and closure gate messages are correctly constructed for their intended purpose.
- [claude] The `_turn_coda` vague-phrase regex patterns for Chinese (e.g., `根据前面的分析继续做下一步`) are well-constructed but rely on exact phrasing patterns. A sufficiently creative rephrasing could produce semantically vague but syntactically valid Codas that bypass both the deny-list and the regex filter. This is inherent in any mechanical filter, not a bug.
- [claude] The prior peer review (panel:arkcli+claude) was partially degraded by arkcli backend errors (minimax-m3 and glm-5.2 both produced garbled output). I concur with its BLOCKER on PR-001 but note the panel's Claude blind-spot analysis contains several valid observations that I've referenced.
- [claude] I do not have access to the actual `loop_state.py` module to verify that `derive(run_dir, write=False)` returns the expected `fronts` and `gates` structure, or that `open_count` is correctly computed. My analysis treats `loop_state` as a black box that the output_gate and run_gate depend on.