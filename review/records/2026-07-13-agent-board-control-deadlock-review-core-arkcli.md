# Peer Review — xunji-agent-board-control-review-core

_backend: arkcli:kimi-k2.7-code+glm-5.2 · 2026-07-13T02:32Z_
> 候选, 非裁决。driver 须逐条过证据门: 不盲从(驳工具/语境误报), 不忽视(采纳真盲补)。

## Verdict: WARN

_backend: arkcli:kimi-k2.7-code+glm-5.2_
_brain: codex_
_bundle_hash: 466a51112e1dc364439f599f26fff8eafea86efc_
_evidence_index_hash: 78705b16384a59c991f6641301bad3a3f69f4e86_

## Findings
- [WARN] PR-001 Confirmed fail-closed egress boundary is carried at certainty 0.8 on a single environment selftest log | Evidence: evidence/full-selftest-v2.log, evidence/diff-turn-contract.patch | Why: [arkcli:kimi-k2.7-code] One passing selftest run is an environment artifact, not independent confirmation. The adversarial shell cases are synthetic and cover only the explicitly listed strings.
- [WARN] PR-002 New `_has_unquoted_shell_control` parser leaves residual shell-control surface uncovered | Evidence: evidence/diff-turn-contract.patch:_has_unquoted_shell_control | Why: [arkcli:kimi-k2.7-code] The parser rejects `$(`, `${`, backticks, and unquoted metacharacters, but not bash process substitution, ANSI-C quoting, or comment truncation, which could bypass `_control_invocation`.
- [WARN] PR-003 Target-action classification is fail-closed only through `_fanout_control_bash`, creating a single-point regression | Evidence: evidence/diff-turn-contract.patch:_is_target_action | Why: [arkcli:kimi-k2.7-code] All Bash commands except recognized fanout/control are treated as target-capable; a future change to `CONTROL_SCRIPTS`, `_fanout_control_bash`, or `_readonly_shell` could silently weaken egress separation, and this run did not externally probe egress.
- [WARN] PR-004 Canonical disposition anchor validation reads mutable markdown at validation time and accepts any `[EDF]-\d+` string | Evidence: evidence/diff-runtime-receipts.patch:disposition_note_issues | Why: [arkcli:kimi-k2.7-code] The function recomputes the canonical set from mutable files at finish time, creating time-of-check/time-of-use drift, and treats any matching anchor token as valid regardless of confirmation status.
- [WARN] PR-005 No evidence that the original control-plane deadlock was reproduced in a live multi-agent run | Evidence: evidence/diff-workers.patch:done_to_adjudicated, frontier.md | Why: [arkcli:kimi-k2.7-code] The report asserts the diff repairs a reproduced deadlock, but only a synthetic `_selftest()` case is shown; there is no live assignment audit trail or replay artifact.

## Blind-spot check
- [kimi-k2.7-code] The author likely treated the single passing full-selftest-v2.log as sufficient confirmation of a fail-closed safety property; as a different model I would not grant >=0.8 on one environment artifact.
- [kimi-k2.7-code] The author likely assumes shlex.split plus the new quote/escape parser fully captures shell grammar; bash-specific constructs such as <(...), $'...' were not considered.
- [kimi-k2.7-code] The author likely missed that canonical anchor validation is time-of-check/time-of-use because it re-reads mutable markdown rather than snapshotting anchors at assignment creation.
- [kimi-k2.7-code] The author did not flag that no real multi-agent deadlock reproduction is present; the run is a pure code-review diff with synthetic selftests.
- [glm-5.2] <things the author likely overlooked>

## Context-limit notes
- [glm-5.2] <where you are unsure or might be wrong due to Chinese-language or local (CNVD / Taiwan) context you do not fully grasp>
- [glm-5.2] `decisions.md`: D-001 chosen front F-001. Result: Inspect three diff artifacts. Challenge shell escaping, command substitution, control-command vs target-action, heartbeat/finish transitions, done-to-adjudicated, missing validator, canonical anchor, test coverage. Safety: Read-only repo maintenance review; no live target actions.
- [glm-5.2] `frontier.md`: F-001 closed. Barrier: app-layer. Depth: deep. Best evidence: E-001.
- [glm-5.2] `report.md`: "The final core diff repairs the reproduced control-plane deadlock while preserving fail-closed target egress and terminal-state auditability."
- [glm-5.2] E-001: certainty 0.8, confirmed. Artifacts: 3 diff patches (`diff-runtime-receipts.patch`, `diff-turn-contract.patch`, `diff-workers.patch`), `full-selftest-v2.log`, `source-context.txt`.
- [glm-5.2] Extracts `disposition_note_issues` function from `agent_disposition`.
- [glm-5.2] `disposition_note_issues` validates terminal disposition against canonical run anchors.
- [glm-5.2] It checks for `E/F/D` anchors in the note and ensures they exist in `evidence.md`, `frontier.md`, `decisions.md`.
- [glm-5.2] For "merged", it requires `Evidence|Front|Decision|Refuted|Barrier` label and anchors.
- [glm-5.2] For "blocked/failed/abandoned", it requires `Reason` label and `Front: F-xxx`.
- [glm-5.2] Adds tests for missing anchors.
- [glm-5.2] Replaces a regex `re.search(r"[;&|><`]|\$\(|\$\{|\n|\r", normalized)` with `_has_unquoted_shell_control(normalized)`.
- [glm-5.2] `_has_unquoted_shell_control` implements a state machine to reject shell control syntax while allowing punctuation inside quoted data.
- [glm-5.2] `_is_target_action` is changed: if `tool == "Bash" and _fanout_control_bash(command)`, return False. Then if `tool == "WebFetch" or tool == "Bash"`, return True.
- [glm-5.2] Adds a bunch of tests for shell escaping, quoting, and adversarial commands.
- [glm-5.2] Adds `hunter` alias for `web-hunter`.
- [glm-5.2] Adds `CANONICAL_AGENT_ROLES` and rejects unknown roles.
- [glm-5.2] `update_agent_lifecycle`: removes `TERMINAL_AGENT_STATUSES` from non-terminal allowed statuses (so heartbeat cannot set terminal). Adds `amend` bool. If terminal and status is adjudicated, validates note via `disposition_note_issues`. If terminal and previous_status is adjudicated, requires `amend` or returns existing. Appends to `disposition_history` if amending.
- [glm-5.2] `print_finish` updated with `amend`.
- [glm-5.2] Tests added for `hunter` alias, unknown role rejection, disposition validation, amendment, heartbeat cannot set terminal, done-to-adjudicated, missing validator fail-closed.
- [glm-5.2] CLI `finish` gets `--amend` flag. `heartbeat` `--status` choices reduced to `NONTERMINAL_AGENT_STATUSES`.
- [glm-5.2] Claim: "repairs the reproduced control-plane deadlock" - where is the evidence of a deadlock? The diffs don't explicitly mention a deadlock, but the changes to `update_agent_lifecycle` (e.g., heartbeat cannot set terminal, terminal rewrite requires amendment) might be related to a state machine issue. However, there is no evidence of a "reproduced deadlock" in the provided artifacts. The selftest log just says "PASS".
- [glm-5.2] Claim: "preserving fail-closed target egress" - The `_is_target_action` change in `turn_contract.py` does this: `if tool == "Bash" and _fanout_control_bash(command): return False`. Wait, if `_fanout_control_bash` is true, it's NOT a target action. Then if `tool == "Bash"`, it IS a target action. The comment says: "Every other Bash command remains target-capable. Do not let a future NON_EGRESS_TOOLS entry silently weaken the fail-closed shell boundary." This is a safety improvement.
- [glm-5.2] Claim: "terminal-state auditability" - `disposition_history` and `disposition_note_issues` provide this.
- [glm-5.2] But the claim about "reproduced control-plane deadlock" is not backed by evidence. It's a claim about a past state that isn't in the provided artifacts.
- [glm-5.2] `_has_unquoted_shell_control` in `turn_contract.py`:
- [glm-5.2] It handles single quotes, double quotes, backslash escaping.
- [glm-5.2] Inside double quotes, it rejects `` ` ``, `$(`, `${`.
- [glm-5.2] What about `\` inside single quotes? In bash, backslash inside single quotes is literal. The code: `if quote == "'": if char == "'": quote = ""`. It does not handle backslash inside single quotes, which is correct (it treats it as literal).
- [glm-5.2] What about newlines inside double quotes? Bash allows newlines inside double quotes. The code: `elif char in ";&|><`\n\r" or ...: return True`. Wait, if `quote == '"'` and `char == '\n'`, it goes to the `elif char in ";&|><`\n\r"` block? No, because it's inside the `if quote == '"':` block.
- [glm-5.2] What about unquoted `\n`? It's caught by `elif char in ";&|><`\n\r"`.
- [glm-5.2] Wait, the old regex was `r"[;&|><`]|\$\(|\$\{|\n|\r"`. The new one allows `; & | > <` inside quotes. This is the whole point: "allowing punctuation inside quoted data". But does `_control_invocation` then parse it safely? It uses `shlex.split(normalized)`. `shlex` will handle the quotes. Then it checks if the script is in `CONTROL_SCRIPTS`. So if a command is `python3 workers.py finish run A --status blocked
- arkcli succeeded after 2 attempt(s); previous failures: attempt 1: arkcli panel 全部模型失败: kimi-k2.7-code: timeout >300s; glm-5.2: parse error; output tail: r as exc:
        receipts_missing_fails_closed = "runtime_receipts unavailable" in str(exc)
    finally:
        globals()["_runtime_receipts"] = saved_runtime_receipts
        heartbeat_cannot_set_terminal = True
```
Yes, it is. The `heartbeat_cannot_set_terminal = True` is in the `finally` block of the `receipts_missing` test. This is definitely a copy-paste error or refactoring artifact. It makes the `heartbeat_cannot_set_terminal` test meaningless. This is a significant test coverage gap.
