# Peer Review — live-scope

_backend: arkcli:kimi-k2.7-code+minimax-m3+glm-5.2 · 2026-07-10T23:08Z_
> 候选, 非裁决。driver 须逐条过证据门: 不盲从(驳工具/语境误报), 不忽视(采纳真盲补)。

## Verdict: WARN

_backend: arkcli:kimi-k2.7-code+minimax-m3+glm-5.2_  
_brain: codex_  
_bundle_hash: 00ccc0c02a1a01c61545be487a71cca31a244989_  
_evidence_index_hash: 27ae8744b984cc7845409447b86982d0112b7d3f_  

## Findings
- [WARN] PR-001 arkcli panel had backend errors; review is partial | Evidence: kimi-k2.7-code: arkcli exit 1; stderr/stdout tail: {
  "ok": false,
  "error": {
    "type": "error",
    "message": "arkruntime.create_responses: RequestError code: 500, err: Post \"https://ark.cn-beijing.volces.com/api/plan/v3/responses\": net/http: TLS handshake timeout, request_id: 2026071107073500006576E7C2375B3A43"
  }
}
; minimax-m3: parse error; output tail: actually runs: Claude Code. It covers action denial, output truth, Agent receipts and disposition, internal task notifications, Stop/Coda, non-Bash tool surfaces, and Cron pause current-run binding."

Wait — the report claims to cover "internal task notifications" but I don't see any test for the Notification hook event! Let me search the evidence...

Looking at all 4 source files, I see no test for `Notification` hook. The `turn_contract.py --selftest` is mentioned but we don't have its output. | Why: At least one arkcli reviewer failed, so PASS only means the completed panel members found no blocker.

## Blind-spot check
- (none)

## Context-limit notes
- kimi-k2.7-code: arkcli exit 1; stderr/stdout tail: {
  "ok": false,
  "error": {
    "type": "error",
    "message": "arkruntime.create_responses: RequestError code: 500, err: Post \"https://ark.cn-beijing.volces.com/api/plan/v3/responses\": net/http: TLS handshake timeout, request_id: 2026071107073500006576E7C2375B3A43"
  }
}

- minimax-m3: parse error; output tail: actually runs: Claude Code. It covers action denial, output truth, Agent receipts and disposition, internal task notifications, Stop/Coda, non-Bash tool surfaces, and Cron pause current-run binding."

Wait — the report claims to cover "internal task notifications" but I don't see any test for the Notification hook event! Let me search the evidence...

Looking at all 4 source files, I see no test for `Notification` hook. The `turn_contract.py --selftest` is mentioned but we don't have its output.
- arkcli succeeded after 2 attempt(s); previous failures: attempt 1: arkcli panel 全部模型失败: kimi-k2.7-code: arkcli exit 1; stderr/stdout tail: {
  "ok": false,
  "error": {
    "type": "error",
    "message": "arkruntime.create_responses: RequestError code: 500, err: Post \"https://ark.cn-beijing.volces.com/api/plan/v3/responses\": unexpected EOF, request_id: 2026071107002900009913B76FB7D8C57D"
  }
}
; minimax-m3: parse error; output tail: is valid JSONL". 
- Wait, but blocked_effect_observed starts as `not sentinel.exists()`. So if sentinel exists, blocked_effect_observed is initially False. Then for receipt_not_overwritten, it sets blocked_effect_observed to whether the receipt lines are valid JSONL. So the test ultimately requires the receipt file to contain valid JSONL, regardless of whether sentinel.exists() or not.
- The summary shows sentinel_created=true AND blocked_effect_observed=true. So the receipt file exists (created; glm-5.2: parse error; output tail:  this test restores frontier.md after. However, if the test crashes between `frontier_path.mkdir()` and the restore, the run state is corrupted. This is a test reliability concern, not a security finding.

g) **The `post_denial_fabrication_blocked` test**: This relies on Claude actually attempting to fabricate output. The system prompt instructs Claude to "deliberately output" a false claim. But if Claude chooses not to follow this instruction (which is an alignment property, not a hook property