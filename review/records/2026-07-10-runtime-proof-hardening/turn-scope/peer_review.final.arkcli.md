# Peer Review — turn-scope

_backend: arkcli:kimi-k2.7-code+minimax-m3+glm-5.2 · 2026-07-10T23:36Z_
> 候选, 非裁决。driver 须逐条过证据门: 不盲从(驳工具/语境误报), 不忽视(采纳真盲补)。

## Verdict: WARN

_backend: arkcli:kimi-k2.7-code+minimax-m3+glm-5.2_  
_brain: codex_  
_bundle_hash: 82dcb735d334a813f250ba86edbc83444b3b625f_  
_evidence_index_hash: 55fe18956656bad0cc9dd1685bea2bef60ed566d_  

## Findings
- [WARN] PR-001 arkcli panel had backend errors; review is partial | Evidence: kimi-k2.7-code: arkcli exit 1; stderr/stdout tail: {
  "ok": false,
  "error": {
    "type": "error",
    "message": "arkruntime.create_responses: RequestError code: 500, err: Post \"https://ark.cn-beijing.volces.com/api/plan/v3/responses\": unexpected EOF, request_id: 20260711073239000080DAECF556C405B9"
  }
}
; minimax-m3: parse error; output tail: k is critical** - what might Codex have missed?
   - The fact that "EXPLAIN_ONLY" mode still allows WebSearch - this is in the allow list. Could an attacker use WebSearch for OSINT to bypass controls? Probably not directly, since WebSearch is read-only.
   - The "EXPLAIN_ONLY" mode allows reading files - is there a risk of information disclosure via the additional context? The contract says "可读文件，不修改、不探测、不派 Agent" - this is the right scope.
   - The PAUSE mode allows CronList and CronDelete - is | Why: At least one arkcli reviewer failed, so PASS only means the completed panel members found no blocker.

## Blind-spot check
- (none)

## Context-limit notes
- [glm-5.2] It's a review of the "turn enforcement" framework controls.
- [glm-5.2] E-001 is the only evidence entry. It contains a huge `adversarial_selftests.log` with selftest outputs for run_model, turn_contract, runtime_receipts, anti_drift, output_gate, run_gate.
- [glm-5.2] There are also artifacts: installed-runtime-manifest.json, output_gate.diff, run_gate.hunks-01.diff, run_gate.hunks-02.diff, settings.diff, and turn_contract source code excerpts.
- [glm-5.2] The claim is that the turn enforcement (turn modes EXPLAIN/PAUSE/EXECUTE, fail-closed behavior, Agent Board fanout enforcement, etc.) is correctly implemented and tested.
- [glm-5.2] "E-001 binds the installed settings and file hashes to the turn, output, Stop, and canonical-front code."
- [glm-5.2] "Its named adversarial log covers missing, malformed, wrong-schema, stale, and cross-session contracts; missing/malformed frontier; manual or old Agent proof; background review; direct receipt mutation; and Coda bypasses."
- [glm-5.2] "The full repository regression remains in the parent maintenance record and is not presented as a separate finding in this focused scope."
- [glm-5.2] "This Codex-authored scope requires arkcli panel plus fresh Claude review. No completion or PASS is claimed before peer_review.md and peer_review.json are generated from the frozen bundle."
- [glm-5.2] Various Round 4 and Round 5 dispositions (PR-001 through PR-009, blind spots).
- [glm-5.2] D-001: REVIEW_ONLY status. "This scope validates framework controls; it is not a live engagement closure." Completion marker absent by design. Required exit: arkcli plus fresh Claude independent review.
- [glm-5.2] F-001: Turn and active-front enforcement. Status: closed. Barrier class: none. Current depth: deep. Evidence: E-001.
- [glm-5.2] certainty 1.0, confirmed, maturity finding.
- [glm-5.2] Artifacts: adversarial_selftests.log, installed-runtime-manifest.json, output_gate.diff, run_gate.hunks-01.diff, run_gate.hunks-02.diff, settings.diff, turn_contract.lines-001-170.txt, turn_contract.lines-171-340.txt, turn_contract.lines-341-510.txt, turn_contract.lines-511-680.txt, turn_contract.lines-681-end.txt.
- [glm-5.2] run_model selftest: 9 checks, all ok.
- [glm-5.2] turn_contract selftest: many checks, all ok.
- [glm-5.2] runtime_receipts selftest: many checks, all ok.
- [glm-5.2] anti_drift selftest: many checks, all ok.
- [glm-5.2] output_gate selftest: many checks, all ok.
- [glm-5.2] run_gate selftest: many checks, all ok.
- [glm-5.2] output_gate.diff: Shows addition of `_DENIED_ONLY_RE`, `_active_run_declared`, `_denied_result_claim_reason`, fail-closed exception handler, EXPLAIN_ONLY exemption, selftest cases. This matches the review.md claims about "denied target cannot invent HTTP/TLS measurements" etc.
- [glm-5.2] run_gate.hunks-01.diff: Shows `_check_agent_board` rewrite to require real Agent receipts + disposition, fail-closed exception handling, EXPLAIN/PAUSE handling, normal closure fail-closed.
- [glm-5.2] run_gate.hunks-02
- kimi-k2.7-code: arkcli exit 1; stderr/stdout tail: {
  "ok": false,
  "error": {
    "type": "error",
    "message": "arkruntime.create_responses: RequestError code: 500, err: Post \"https://ark.cn-beijing.volces.com/api/plan/v3/responses\": unexpected EOF, request_id: 20260711073239000080DAECF556C405B9"
  }
}

- minimax-m3: parse error; output tail: k is critical** - what might Codex have missed?
   - The fact that "EXPLAIN_ONLY" mode still allows WebSearch - this is in the allow list. Could an attacker use WebSearch for OSINT to bypass controls? Probably not directly, since WebSearch is read-only.
   - The "EXPLAIN_ONLY" mode allows reading files - is there a risk of information disclosure via the additional context? The contract says "可读文件，不修改、不探测、不派 Agent" - this is the right scope.
   - The PAUSE mode allows CronList and CronDelete - is
- arkcli succeeded after 2 attempt(s); previous failures: attempt 1: arkcli panel 全部模型失败: kimi-k2.7-code: timeout >300s; minimax-m3: parse error; output tail:  a potential gap: if the hook crashes AND there's no active run, the tool is allowed. But if there's no active run, there shouldn't be enforcement anyway, so this is arguably correct.

10. **The reviewer.md says "PR-003 retained limitation: two arkcli outputs were unparsable"**: 
    - The review panel had two unparsable outputs (Kimi and fresh Claude)
    - This means the panel is incomplete
    - The review says "no partial panel is represented as a PASS" - this is good discipline
    - But it; glm-5.2: parse error; output tail: Y_RE` that requires an EXACT match of the three-line denial envelope. But what if the model outputs the denial with slightly different whitespace, or with different front ID format? The regex requires `F-\d{3}` exactly. This is intentionally strict, but could cause operational friction.

11. **Missing check: does the settings.json actually wire output_gate.py and run_gate.py?** The evidence doesn't show this. The settings.diff only shows turn_contract.py additions. If output_gate.py and run_gate