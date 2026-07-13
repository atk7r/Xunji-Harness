# Peer Review Panel — xunji-agent-board-control-review

_backend: panel:arkcli+claude · 2026-07-13T01:31Z_
> 候选, 非裁决。driver 须逐条过证据门。

## Verdict: WARN

_backend: panel:arkcli+claude_
_brain: codex_
_bundle_hash: d9da8a49895356a4dca8bc45dbc83eb44989d5de_
_evidence_index_hash: 065fc8d737736f7108bca8967e0e2b03c066464a_

## Findings
- [WARN] PR-001 E-001 treats evidence/tests.txt as confirmation of selftest/bench/live-run success, but the file is a prose summary without raw logs, hashes, or run artifacts. | Evidence: evidence/tests.txt:1-13, evidence.md E-001, report.md | Why: [panel:arkcli] [arkcli:kimi-k2.7-code] Certainty >= 0.8 requires evidence, not self-reported claims. tests.txt only asserts passes and a run state; it does not contain command outputs, fixture details, or the referenced run directory.
- [WARN] PR-002 The live-run control-state verification for runs/sxtbu_20260713 cannot be cross-checked because no artifact from that run is present in the bundle. | Evidence: evidence/tests.txt (Live run control-state verification), frontier.md F-001 | Why: [panel:arkcli] [arkcli:kimi-k2.7-code] A prose claim that legacy empty-asset assignments are blocked and disposition_satisfied=true is not confirmation on its own per the evidence discipline.
- [WARN] PR-003 workers.py invokes _runtime_receipts.disposition_note_issues, but the diff excerpt does not show the import or lazy binding that makes the symbol available. | Evidence: evidence/change.diff tools/workers.py hunk @@ -2152,... | Why: [panel:arkcli] [arkcli:kimi-k2.7-code] Without seeing the binding, an independent reviewer cannot confirm the terminal-disposition validator is reachable; relying on tests.txt alone is circular.
- [WARN] PR-004 The hunk in tools/xunji_statusline.py is included in the change set but has no explanatory note, test, or evidence that it cannot affect control-plane state. | Evidence: evidence/change.diff tools/xunji_statusline.py hunk @@ -550,... | Why: [panel:arkcli] [arkcli:kimi-k2.7-code] Any change to a tool that renders run/control state should be reviewed for unintended control-plane side effects.
- [WARN] PR-005 Egress-denial regression coverage for adversarial quoting in Bash control commands is shallow: only _control_invocation is tested, not the full evaluate_pretool path for quoted shell metacharacters. | Evidence: evidence/change.diff tools/turn_contract.py _has_unquoted_shell_control, evidence/change.diff tools/turn_contract.py _selftest additions | Why: [panel:arkcli] [arkcli:kimi-k2.7-code] The new parser intentionally permits punctuation inside quotes; the security-critical property is what evaluate_pretool does with such inputs, which is not directly exercised in the provided tests.
- [WARN] PR-006 arkcli panel had backend errors; review is partial | Evidence: glm-5.2: parse error; output tail:  `command.startswith("$( ", i)`. The first argument is `"$( "` - that's dollar, open-paren, space. But that would miss `$(command)` without a space!

Actually, wait. Let me re-read the diff more carefully. The excerpt might have whitespace issues. Let me look at the raw text again:

```
+            elif char == "`" or command.startswith("$( ", i) or command.startswith("${", i):
```

Hmm, but this is inside double quotes. Let me also look at the unquoted case:

```
+        elif char in ";&|><`\ | Why: [panel:arkcli] At least one arkcli reviewer failed, so PASS only means the completed panel members found no blocker.

## Blind-spot check
- [arkcli] [kimi-k2.7-code] No raw execution artifacts: all test outcomes and the live-run state are self-reported in evidence/tests.txt.
- [arkcli] [kimi-k2.7-code] No captured pre-fix deadlock reproduction, so the fix cannot be verified against the exact failure mode.
- [arkcli] [kimi-k2.7-code] No adversarial end-to-end test of evaluate_pretool for Bash control commands containing quoted shell metacharacters.
- [arkcli] [kimi-k2.7-code] The import/binding of runtime_receipts inside workers.py is not visible in the excerpt.
- [arkcli] [kimi-k2.7-code] The xunji_statusline.py change is unexplained and untested.
- [arkcli] [kimi-k2.7-code] No evidence that legacy empty-asset assignments in an existing run can be cleanly closed as blocked.
- [claude] **Shell parser is the primary blind spot.** The `_has_unquoted_shell_control` function (25 lines, new code) is the entire security boundary for control-command shell injection. The author invested significant rigor in the disposition audit trail and role validation (10+ new selftests in workers.py) but gave the shell parser only 3 assertions. This is an inverted testing pyramid — the hardest-to-get-right code got the least testing.
- [claude] **The `_is_target_action` refactor has a subtle logic equivalence question.** The BEFORE code had Bash fall through to `NON_EGRESS_TOOLS` check when `_fanout_control_bash` returned True (which was a bug — it classified control commands as target egress). The AFTER code has Bash returning False early for control commands. However, the AFTER code also makes the `NON_EGRESS_TOOLS` check unreachable for ALL Bash commands (both control and non-control). This is semantically correct (Bash is capably an egress tool), but the author didn't document that this was intentional. If Bash were ever added to `NON_EGRESS_TOOLS` in the future, the current code would silently ignore it for non-control Bash commands.
- [claude] **The `disposition_history` entries use `stamp` (the current timestamp) as `amended_at` but `finished_at` from the previous record.** On the first disposition, `finished_at` was set to the then-current timestamp. On amend, the history entry records `finished_at` from the prior record and `amended_at` = now. The new record's `finished_at` is NOT updated on amend. This means the new record's `finished_at` reflects the ORIGINAL finish time, not the amendment time. This is arguably correct (the assignment was "finished" at the original time, just the note/status was corrected) but differs from some audit systems that would record when the correction was made as the new completion time.
- [claude] **Chinese-language error messages.** The disposition validation messages are in Chinese (e.g., "缺 canonical E/F/D 锚点", "canonical 锚点不存在"). If the operator doesn't read Chinese, these errors are opaque. This is a design choice, not a bug, but it limits the operator pool.
- [claude] **The statusline selftest split** (`evidence/change.diff:487-489`) is described as fixing an "environment-dependent" assertion. The split from `"子任务 计划2/真实0"` to `"子任务 计划2/" in plain and "真实0" in plain` is reasonable if ANSI codes or spacing appear between the segments, but there's no comment explaining WHY the assertion was environment-dependent, making it hard for future maintainers to know whether further splits might be needed.
- [claude] **Missing surface: the `_has_unquoted_shell_control` return value.** The function returns `bool(quote or escaped)`. If a command ends with an unclosed quote, it's rejected (fail-closed). If a command ends with a dangling backslash (`escaped=True`), it's also rejected. The latter could reject legitimate control commands that end with a trailing backslash (e.g., `python3 -c "print(1)"\`). This is undocumented behavior.

## Context-limit notes
- [arkcli] glm-5.2: parse error; output tail:  `command.startswith("$( ", i)`. The first argument is `"$( "` - that's dollar, open-paren, space. But that would miss `$(command)` without a space!

Actually, wait. Let me re-read the diff more carefully. The excerpt might have whitespace issues. Let me look at the raw text again:

```
+            elif char == "`" or command.startswith("$( ", i) or command.startswith("${", i):
```

Hmm, but this is inside double quotes. Let me also look at the unquoted case:

```
+        elif char in ";&|><`\
- [claude] **Chinese-language context.** The error messages, test assertions, and documentation are in Chinese. I can read them but may miss nuanced connotations. For example, "处置锚点" (disposition anchor) vs "处置" — the distinction between "dispose" and "adjudicate" in the code's terminology may carry semantic weight I don't fully grasp.
- [claude] **I cannot verify the `_fanout_control_bash` / `_readonly_shell` implementation.** These functions are outside the diff scope and would be needed to completely verify the `_is_target_action` refactoring. The diff doesn't include their source.
- [claude] **I cannot verify production callers of `heartbeat`.** The heartbeat restriction may or may not break production. Without seeing the full codebase, this is an inference from the interface change, not confirmed breakage.
- [claude] **Local (CNVD / Taiwan) terminology gaps.** Terms like "xunji" (迅迹), "Guanlan" (观澜), and the specific pentest workflow conventions may have domain-specific meanings I am approximating.