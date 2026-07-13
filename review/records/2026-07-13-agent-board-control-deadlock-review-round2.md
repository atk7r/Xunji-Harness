# Peer Review Panel — xunji-agent-board-control-review

_backend: panel:arkcli+claude · 2026-07-13T01:47Z_
> 候选, 非裁决。driver 须逐条过证据门。

## Verdict: WARN

_backend: panel:arkcli+claude_
_brain: codex_
_bundle_hash: 302943b7a92acc7322cf57984a757eaac8983271_
_evidence_index_hash: a6d7f8a30c25da0160649fc90db7a9382b7a62c0_

## Findings
- [WARN] PR-001 E-001 is confirmed at certainty 1.0 as evidence for the Agent Board control-plane deadlock maintenance claim | Evidence: evidence_index:E-001, evidence/bench.log, evidence/change-v2.diff, evidence/full-selftest.log | Why: [panel:arkcli] [arkcli:kimi-k2.7-code] bench.log records auth-idor, sqli, xss, upload and other pentest benchmarks with no mention of agent-board, disposition, workers.py, or turn_contract.py; it therefore does not support the deadlock-fix claim and inflates confidence.
- [WARN] PR-002 Terminal adjudicated dispositions are immutable except through explicit --amend | Evidence: evidence/change-v2.diff:workers.py update_agent_lifecycle hunk, evidence/source-context.txt | Why: [panel:arkcli] [arkcli:kimi-k2.7-code] The guard `if terminal and previous_status in adjudicated` only protects terminal-to-terminal rewrites; the terminal=False path used by print_heartbeat allows working/assigned/running to overwrite blocked/merged/failed/abandoned records without an audit trail.
- [WARN] PR-003 The full change-v2.diff and its selftests can be cross-checked against the bundle artifacts | Evidence: evidence/change-v2.diff, evidence/full-selftest.log | Why: [panel:arkcli] [arkcli:kimi-k2.7-code] The bundle excerpt ends before the amended_disposition assertion and the xunji_statusline.py hunk, so reviewers cannot verify those code paths or their test assertions from the bundle alone.
- [WARN] PR-004 Frontier ledger documents all fronts referenced in run state | Evidence: evidence/run-state.json, frontier.md | Why: [panel:arkcli] [arkcli:kimi-k2.7-code] A-hunter-002 is assigned to F-003 in run-state.json, but frontier.md (size 349 bytes) only documents F-001, creating a ledger inconsistency.
- [WARN] PR-005 arkcli panel had backend errors; review is partial | Evidence: glm-5.2: parse error; output tail: ol commands like `python3 tools/workers.py ...` are NOT read-only shell commands (they're Python scripts). So `_fanout_control_bash` would return False for them. Under the new logic, they would be classified as target actions. Is that a problem?

Actually, let me re-read the original code more carefully. The `_is_target_action` function determines if a tool use is a "target action" (i.e., an action against the target). This is used for coverage tracking and egress enforcement. Control commands ( | Why: [panel:arkcli] At least one arkcli reviewer failed, so PASS only means the completed panel members found no blocker.

## Blind-spot check
- [arkcli] [kimi-k2.7-code] Non-terminal heartbeat updates can overwrite adjudicated dispositions because the immutability guard is scoped to terminal=True rewrites only.
- [arkcli] [kimi-k2.7-code] No visible selftest specifically exercises done -> merged/blocked/failed/abandoned compatibility without using --amend.
- [arkcli] [kimi-k2.7-code] evidence/bench.log appears to be residual from an unrelated benchmark run and was not screened for relevance before inclusion under E-001.
- [arkcli] [kimi-k2.7-code] The xunji_statusline.py changes are not reviewed in decisions.md and are truncated in the bundle.
- [claude] **The `_has_unquoted_shell_control` escaped-backslash skip is my most significant technical finding.** The author appears to have assumed that the escaped-character skip is safe because the character is "escaped" — but when the character doing the escaping is itself escaped (i.e., `\\`), the skip consumes the NEXT character, not an escape-relevant one. In the `\\$(` case, the `$` is skipped despite being syntactically active in shell. The author tested `\\` at end of string (trailing backslash → rejected via `return bool(escaped)`) but did not test `\\$(`. I consider this a genuine blind spot.
- [claude] **The statusline test assertion relaxation (`"子任务 计划2/真实0"` → `"子任务 计划2/" in plain and "真实0" in plain`) is marginally weaker.** The new assertion matches more strings than intended. While the commit explains the environment-dependent label change, the substring match could theoretically pass when the underlying logic is broken (e.g., `"真实10"` would match `"真实0" in plain`). This is low-severity but worth noting as a test-quality regression.
- [claude] **No test exercises the `_runtime_receipts is None` fallback path.** The selftest creates a scenario where `_runtime_receipts` is available and validates rejection — but it doesn't test the behavior when the import fails. This is the exact path where the new hard-dependency deadlock would manifest, and it's untested.
- [claude] **The `workers_shell_chain` test (`python3 ... list {run}; echo unsafe`) is tested separately from `adversarial_control_commands`.** In V2, `workers_shell_chain` is a standalone variable tested via `workers_shell_chain_rejected`, AND the adversarial_control_commands list begins with piping/redirection variants. There's no duplication issue, but the two test vectors should be unified for clarity.

## Context-limit notes
- [arkcli] glm-5.2: parse error; output tail: ol commands like `python3 tools/workers.py ...` are NOT read-only shell commands (they're Python scripts). So `_fanout_control_bash` would return False for them. Under the new logic, they would be classified as target actions. Is that a problem?

Actually, let me re-read the original code more carefully. The `_is_target_action` function determines if a tool use is a "target action" (i.e., an action against the target). This is used for coverage tracking and egress enforcement. Control commands (
- [claude] I am a different model (DeepSeek) reviewing Claude-authored code. I may not share Claude's code-generation blind spots, but I also may misunderstand Claude-specific conventions or Xunji framework idioms.
- [claude] The review is being conducted entirely in Chinese-language context (many code comments, error messages, and documentation are in Chinese). While I can read Chinese, there may be nuances in the CNVD/local pentesting terminology that I miss.
- [claude] I am assuming the `subprocess.run` calls within the Xunji framework use `shell=False` (list form). If any code path uses `shell=True`, my assessment of the `_has_unquoted_shell_control` edge case severity would need to be upgraded to BLOCKER. I cannot verify this from the diff alone.
- [claude] I cannot assess whether the `--amend` flag was propagated to all callers of `update_agent_lifecycle`/`print_finish`. The diff shows the CLI change and the internal function change, but there could be Python-level callers that are not visible in the diff's hunk context.