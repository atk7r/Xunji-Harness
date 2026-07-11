# Peer Review Panel — turn-scope

_backend: panel:arkcli+claude · 2026-07-10T16:41Z_
> 候选, 非裁决。driver 须逐条过证据门。

## Verdict: WARN

_backend: panel:arkcli+claude_  
_brain: codex_  
_bundle_hash: c4000f86452b8ba7352ac7f601efeb8cdd0dc195_  
_evidence_index_hash: 2be823efc73af07fa0bd7329e850c765a5fabf0b_  

## Findings
- [WARN] PR-001 review.md records accepted dispositions for historical peer-review rounds PR-001 through PR-005 and claims peer_review.round1.* / peer_review.round2.* artifacts are retained, but those artifacts are not present in the evidence_index or bundle. | Evidence: review.md:Round 1 Disposition, review.md:Round 2 Disposition, evidence_index:artifacts | Why: [panel:arkcli] [arkcli:kimi-k2.7-code] Under the rubric, report.md/review.md/decisions.md are claims, not facts. The review.md dispositions are unsupported by any evidence_index entry or artifact hash, and the run is still marked REVIEW_ONLY awaiting arkcli + fresh Claude review.
- [WARN] PR-002 The execute_fanout live Claude smoke case response contains fabricated probe measurements despite the Bash probe being blocked by the hook. | Evidence: live_claude_smoke.summary.json:execute_fanout.result, live_claude_smoke.summary.json:execute_fanout.permission_denials | Why: [panel:arkcli] [arkcli:kimi-k2.7-code] E-002's core claim—that the hook denied the tool—is supported by the artifact. However, the response text includes specific TLS, server banner, and latency details that could not have been observed because the Bash command was denied. The current framework does not flag this, creating a potential misreading of the evidence.
- [WARN] PR-003 arkcli panel had backend errors; review is partial | Evidence: minimax-m3: parse error; output tail:  target file or probe artifact**. The review_bundle has no target files. target.md is 193 bytes. Let me see — actually the target.md exists, size 193 bytes, but I don't have its content in the bundle. It's probably empty or just target definition.

13. **The "live_claude_smoke" tests all used example.test** — not the actual target. So E-002 is testing the HOOK, not the TARGET. This is appropriate for a framework maintenance task.

14. **Is the FANOUT gate test sufficient?** The `execute_requires; glm-5.2: parse error; output tail: run_model selftest explicitly. The turn_contract selftest imports run_model, so it's tested indirectly. But there's no standalone run_model selftest in the log. Wait, the run_model.diff includes a `_selftest()` function. Is it run? Looking at the adversarial_selftests.log... I see "turn_contract selftest passed", "runtime_receipts selftest passed", "anti_drift selftest passed", "output_gate selftest passed", "run_gate selftest passed". No "run_model selftest passed" line. So run_model's own self | Why: [panel:arkcli] At least one arkcli reviewer failed, so PASS only means the completed panel members found no blocker.

## Blind-spot check
- [arkcli] [kimi-k2.7-code] Live smoke validates hook denials but not the accuracy or hallucination-resistance of the model's post-denial prose.
- [arkcli] [kimi-k2.7-code] No bundle artifact represents the frozen bundle sha1 or arkcli panel receipt required by decisions.md for exit.
- [arkcli] [kimi-k2.7-code] E-001 relies heavily on self-tests and code diffs; E-002 is the only independent live-Claude validation and it covers only the pre-fan-out block.
- [claude] **Scope fragmentation creates an unproven integration surface**: The report carves out "Agent receipt/merge/release" to "receipts scope" and "full repository regression" to "parent maintenance record." None of the three scopes (turn-scope, receipts-scope, parent) individually test the complete enforcement chain. The coupling points — e.g., the turn contract's `fanout_override` boolean being read by both output_gate (for Coda enforcement) and run_gate (for Agent Board gate) — are never integration-tested against real Claude Code.
- [claude] **`output_gate.py` and `run_gate.py` selftest assertion visibility**: Unlike `turn_contract.py` which prints 38 named checks, these two selftests print per-check lines (70+ for output_gate, 40+ for run_gate in the adversarial log), but a regression that silently no-ops the selftest body after the `if __name__ == "__main__"` guard would produce identical empty output and an exit code of 0 — invisible in any log. The current log DOES show output, so this is not a current problem, but the architecture lacks a self-test-integrity check.
- [claude] **6-hour `STALE_SECONDS` creates a narrow replay window**: If an operator issues a PAUSE, then within 6 hours starts a new session with an ambiguous prompt, the contract is still valid (not stale) with the same session_id check, and `classify_prompt` re-classifies independently — but if the new prompt happens to contain an EXECUTE_RE keyword by accident, the mode switches to EXECUTE without the operator realizing. The operator thinks they paused, but the contract has moved on.
- [claude] **`turn_contract.py` selftest injects `tools/` into `sys.path` at import time**: `sys.path.insert(0, str(ROOT / "tools"))` at line 24. This means the selftest imports from the installed tools directory with modified `sys.path`. The live smoke test imports the same modules via `PYTHONPATH` implicitly. Any import-order or path-resolution difference between selftest and live environments is not tested.
- [claude] **Context-limited review of diffs**: The output_gate.diff shows 9 hunks out of a 39KB file; run_gate diffs show 33 hunks out of a 77KB file. Interactions between changed and unchanged code (e.g., shared helper functions, global state mutated in one codepath and read in another) cannot be evaluated from diffs alone.

## Context-limit notes
- [arkcli] minimax-m3: parse error; output tail:  target file or probe artifact**. The review_bundle has no target files. target.md is 193 bytes. Let me see — actually the target.md exists, size 193 bytes, but I don't have its content in the bundle. It's probably empty or just target definition.

13. **The "live_claude_smoke" tests all used example.test** — not the actual target. So E-002 is testing the HOOK, not the TARGET. This is appropriate for a framework maintenance task.

14. **Is the FANOUT gate test sufficient?** The `execute_requires
- [arkcli] glm-5.2: parse error; output tail: run_model selftest explicitly. The turn_contract selftest imports run_model, so it's tested indirectly. But there's no standalone run_model selftest in the log. Wait, the run_model.diff includes a `_selftest()` function. Is it run? Looking at the adversarial_selftests.log... I see "turn_contract selftest passed", "runtime_receipts selftest passed", "anti_drift selftest passed", "output_gate selftest passed", "run_gate selftest passed". No "run_model selftest passed" line. So run_model's own self
- [claude] I reviewed `classify_prompt` regex patterns (EXECUTE_RE, EXPLAIN_RE, PAUSE_RE) against Chinese prompt semantics. My Chinese reading is functional but not native — I may miss edge cases where multi-character compounds that contain EXECUTE_RE substrings change the meaning (e.g., 执行董事 = "executive director" is a title, not "execute director").
- [claude] The `peer_review.round1.json` contains garbled output from arkcli backend failures (minimax-m3 and glm-5.2). I cannot parse these to extract partial review signals that might have been lost.
- [claude] The `output_gate.diff`, `run_gate.hunks-01.diff`, and `run_gate.hunks-02.diff` are diff excerpts. Subtle interactions between changed and unchanged code in the full 39KB/77KB files could create edge cases I cannot evaluate from diffs alone.