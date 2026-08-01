# Peer Review Panel — 2026-07-29-interrupted-reviewer-recovery

_backend: panel:arkcli+claude · 2026-07-29T07:42Z_
> 候选, 非裁决。driver 须逐条过证据门。

## Verdict: WARN

_backend: panel:arkcli+claude_
_brain: codex_
_bundle_hash: a25b1be188e991528a9820ec3cd2306fffd1eb4d_
_evidence_index_hash: 404024c546bda6ea83191cb37c222826a7b90221_

## Findings
- [WARN] PR-001 The report states that 'Independent transcript/runtime inspection finds zero target actions and no source edits by the driver', but the only evidence for this is a driver-produced adjudication artifact, not a separate inspection record or raw transcript excerpt. | Evidence: evidence/driver-adjudication.json, evidence/driver-session-transcript.jsonl | Why: [panel:arkcli] [arkcli:kimi-k2.7-code] The negative_controls block in driver-adjudication.json is generated inside the same driver session it claims to vouch for. Without an external or replayed inspection artifact, the statement overstates the independence of the check.
- [WARN] PR-002 The report claims the full framework suite result was '69 passed, 0 failed', but the provided evidence excerpt does not show that aggregate line. | Evidence: evidence/test-results.txt | Why: [panel:arkcli] [arkcli:kimi-k2.7-code] The test-results excerpt is truncated (excerpt_truncated_chars=26699) and only shows individual selftest ok lines for runtime_receipts.py, workers.py and turn_contract.py. The aggregate count is plausible because the artifact exists, but it is not directly visible in the review bundle.
- [WARN] PR-003 F-004 full-lifecycle E2E deferred leaves highest-risk feature path unqualified | Evidence: report.md, decisions.md D-007, driver-adjudication.json | Why: [panel:claude] the original production run profile is not exercised end-to-end by the decisive test; only the recovery phase used 25 MB, the launch/settlement phase used a small synthetic run
- [WARN] PR-004 Performance benchmark certainty overestimated | Evidence: evidence/performance-benchmark.txt (single `/usr/bin/time -p` run) | Why: [panel:claude] evidence rubric explicitly warns against single-observation confirmation; 1.61s vs 600s is a large margin, but the certainty stricture was not formally relaxed for this experiment type
- [WARN] PR-005 arkcli GLM parse failure dismissed without root-cause or re-run | Evidence: report.md ("arkcli 内部 GLM parse error 保留为 partial-panel 限制") | Why: [panel:claude] the independent review panel is the gate for organizational approval; a known parse failure reduces panel diversity and the residual impact on the final WARN verdict is unquantified

## Blind-spot check
- [arkcli] [kimi-k2.7-code] The decisive real-driver E2E uses a synthetic targetless fixture; while the report explicitly defers the unified high-load full-lifecycle test, there is no evidence that the synthetic 25 MB parent transcript matches the shape/distribution of the original A-review-012 transcript that caused the timeout.
- [arkcli] [kimi-k2.7-code] Concurrency serialization of the receipt publish path is demonstrated only by selftests; no real-driver or copied-run concurrent writer experiment is shown.
- [arkcli] [kimi-k2.7-code] The v1 receipt validation hardcodes role==review and a single reason string; there is no evidence of regression tests that attempt to widen the reason or apply the recovery to non-Reviewer roles, which would be the natural failure mode for future schema drift.
- [arkcli] [glm-5.2] <things the author likely overlooked>
- [claude] The interruption string match `[Request interrupted by user for tool use]` is a fragile literal match that could break with Claude Code client updates. The author documented this exactly (D-008), but the operational consequence of a mismatch is a silent fail-closed that an operator might not immediately attribute to a new client version rather than a framework bug.
- [claude] The global projection snapshot optimization is validated by unit tests and a single-launch synthetic driver, but a heavily loaded production run with concurrent `reconcile` calls competing for the same journal could expose lock contention on the snapshot build that the tests do not measure and the driver fixture did not provoke.
- [claude] If an OOM or process-kill cancels the Start hook instead of a client interruption, the typed recovery explicitly does not apply. The operator receives no automatic diagnostic — the `running` assignment simply stays. The report states this clearly, but no post-deployment monitoring gap analysis is provided to bridge the operator workflow between reading this document and acting on a live stale run.

## Context-limit notes
- [arkcli] [glm-5.2] <where you are unsure or might be wrong due to Chinese-language or local (CNVD / Taiwan) context you do not fully grasp>
- [claude] The architecture docs and in-code comments are in Chinese, with references to CNVD-style lifecycle integrity (不可取消、不可绕过). I am evaluating conformance to this philosophy at a linguistic remove and may misread a subtle constraint.
- [claude] The `target.md` file (401 bytes, SHA-1 `af83d7c41544e6ad6994f16a789326c956d828df`) is not excerpted in the review bundle. I cannot confirm the fix exactly matches the declared target surface or if any surface constraints were silently dropped.