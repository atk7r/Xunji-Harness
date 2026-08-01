# Peer Review — xunji-agent-board-control-review-core

_backend: arkcli:kimi-k2.7-code+glm-5.2 · 2026-07-13T02:47Z_
> 候选, 非裁决。driver 须逐条过证据门: 不盲从(驳工具/语境误报), 不忽视(采纳真盲补)。

## Verdict: WARN

_backend: arkcli:kimi-k2.7-code+glm-5.2_
_brain: codex_
_bundle_hash: c3a953c21c3b31c78882e4e97598a6ee41573e68_
_evidence_index_hash: 6f70fe2e5be3019ef86b5eff723c82c183f121c5_

## Findings
- [WARN] PR-001 arkcli panel had backend errors; review is partial | Evidence: kimi-k2.7-code: timeout >300s | Why: At least one arkcli reviewer failed, so PASS only means the completed panel members found no blocker.

## Blind-spot check
- [glm-5.2] <things the author likely overlooked>

## Context-limit notes
- [glm-5.2] <where you are unsure or might be wrong due to Chinese-language or local (CNVD / Taiwan) context you do not fully grasp>
- [glm-5.2] `evidence/diff-runtime-receipts-v2.patch` (sha1: 701fbb...)
- [glm-5.2] Changes to `tools/runtime_receipts.py`
- [glm-5.2] Adds `disposition_note_issues` function to validate terminal disposition against canonical run anchors.
- [glm-5.2] Extracts this logic from `agent_disposition` and uses `disposition_note_issues` instead.
- [glm-5.2] Adds selftest for missing anchor.
- [glm-5.2] `evidence/diff-turn-contract-v2.patch` (sha1: d0f0d2...)
- [glm-5.2] Changes to `tools/turn_contract.py`
- [glm-5.2] Replaces regex `[;&|><\`]|\\$\\(|\\$\\{|\\n|\\r` with `_has_unquoted_shell_control(normalized)`.
- [glm-5.2] Adds `_has_unquoted_shell_control(command)` function. This function parses quotes and escapes to only reject shell control syntax outside quotes. Inside double quotes, it still rejects backticks (`), `$(`, `${`. Inside single quotes, everything is literal. Outside quotes, it rejects `;&|><` etc., backticks, `$(`, `${`, newlines.
- [glm-5.2] Changes `_is_target_action`:
- [glm-5.2] Before: `if tool == "WebFetch" or (tool == "Bash" and not _fanout_control_bash(command)): return True`
- [glm-5.2] After:
- [glm-5.2] Updates `evaluate_pretool` to include up to 4 pending disposition issues in the return error message.
- [glm-5.2] Adds extensive selftests for shell quoting and substitutions.
- [glm-5.2] `evidence/diff-workers-v2.patch` (sha1: 50b9e4...)
- [glm-5.2] Changes to `tools/workers.py`
- [glm-5.2] Adds `"hunter": "web-hunter"` to ROLE_ALIASES.
- [glm-5.2] Adds `CANONICAL_AGENT_ROLES = frozenset(ROLE_ALIASES.values())`.
- [glm-5.2] `create_agent_assignment`: raises ValueError if role not in CANONICAL_AGENT_ROLES.
- [glm-5.2] `update_agent_lifecycle`:
- [glm-5.2] Adds `amend: bool = False` parameter.
- [glm-5.2] `allowed = TERMINAL_AGENT_STATUSES if terminal else NONTERMINAL_AGENT_STATUSES` (previously allowed terminal in non-terminal? Wait, `allowed = TERMINAL_AGENT_STATUSES if terminal else (NONTERMINAL_AGENT_STATUSES | TERMINAL_AGENT_STATUSES)`. Now it's just `NONTERMINAL_AGENT_STATUSES`).
- [glm-5.2] Adds logic for amendment, disposition history, preventing heartbeat from reopening terminal status, and preventing silent terminal rewrite without `--amend`.
- [glm-5.2] Validates `disposition_note_issues` from `runtime_receipts` before state mutation.
- [glm-5.2] Fails closed if `_runtime_receipts` is None.
- [glm-5.2] `print_finish` updated to pass `amend`.
- [glm-5.2] CLI `heartbeat` --status choices changed to `NONTERMINAL_AGENT_STATUSES`.
- [glm-5.2] CLI `finish` adds `--amend` flag.
- [glm-5.2] Adds tests for all these.
- [glm-5.2] `evidence/full-selftest-v3.log` (sha1: 19c18b...)
- [glm-5.2] Logs show 60 passed, 0 failed.
- [glm-5.2] `evidence/source-context.txt` (sha1: 76c540...)
- [glm-5.2] Shows some of the source code context.
- [glm-5.2] Report.md: "The final core diff repairs the reproduced control-plane deadlock while preserving fail-closed target egress and terminal-state auditability."
- [glm-5.2] Wait, where is the "reproduced control-plane deadlock" fixed? The diffs are about:
- kimi-k2.7-code: timeout >300s