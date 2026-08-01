# Peer Review Panel — turn-scope

_backend: panel:claude · 2026-07-10T23:25Z_
> 候选, 非裁决。driver 须逐条过证据门。

## Verdict: NEEDS_DRIVER

_backend: panel:claude_  
_brain: codex_  
_bundle_hash: 82dcb735d334a813f250ba86edbc83444b3b625f_  
_evidence_index_hash: 55fe18956656bad0cc9dd1685bea2bef60ed566d_  

## Findings
- [WARN] PR-001 review panel had backend errors; aggregation is partial | Evidence: arkcli: ERROR arkcli panel 全部模型失败: kimi-k2.7-code: timeout >300s; minimax-m3: parse error; output tail: tional given the "REVIEW_ONLY" scope.

Now let me think about what I, as a different model, would catch that the author might miss:

1. **The "review.md" is NOT a completed independent review** - It's a Codex-authored round 4/5 disposition. The harness's `_has_completed_independent_review` looks for "## Independent Review" in review.md. There is no such section. The harness's `_has_codex_completion_review` looks for "## CodexCompletionReview" in decisions.md. There is no such section. This means; glm-5.2: arkcli exit 1; stderr/stdout tail: {
  "ok": false,
  "error": {
    "type": "error",
    "message": "arkruntime.create_responses: RequestError code: 500, err: Post \"https://ark.cn-beijing.volces.com/api/plan/v3/responses\": unexpected EOF, request_id: 202607110721270000C0EFCFB187BEFAD3"
  }
}
 | Why: At least one requested heterogeneous reviewer failed or was unavailable.

## Blind-spot check
- [claude] **Manifest hook-reference deduplication gap**: `installed-runtime-manifest.json` shows 8 identical `turn_contract.py` references under `turn_contract_hook_references` but doesn't map them to specific hook events. The selftest checks `wired("UserPromptSubmit")` etc. verify that at least one reference exists per hook event, but if a hook event were accidentally wired twice (duplicate configuration) or a hook event's command path were silently wrong (e.g., missing `"$CLAUDE_PROJECT_DIR"` wrapper), the manifest wouldn't surface it. The manifest serves as a hash-chain anchor for the installed configuration but its self-description is coarse.
- [claude] **PR-008 dismissal creates a session-replay vector**: Review round 4 says PR-008 (old execute prompts restarting sessions) was "dismissed as intended per-prompt authority." The rationale — "age does not override session binding or UserPromptSubmit reclassification" — is architecturally correct. But it means that if an operator accidentally pastes an old prompt containing `/loop` or `继续执行` into a new session, `UserPromptSubmit` will reclassify it and write a new EXECUTE contract. The `turn_contract.py` session binding (session_id match in `load_contract`) prevents cross-session contract reuse, but the initial classification itself fires before the session check. This is subtle: the old prompt's content triggers a new EXECUTE mode, not the old contract. It's correct behavior per the design but worth documenting as a footgun.
- [claude] **The `_safe_sed` regex `r"(?:\d+|\$)(?:,(?:\d+|\$))?p"` allows degenerate ranges**: The sed safety check accepts patterns like `999999999999,999999999999p` which would be extremely slow on large files. Not a security issue (it's read-only and the file comes from the local repo), but a resource-exhaustion edge case in the read grammar.
- [claude] **No verification that the settings.json diffs were actually applied**: The `settings.diff` artifact shows what changed, and the selftest checks `wired("UserPromptSubmit")` etc. by reading the live settings.json. But the evidence doesn't include a snapshot of the current `settings.json` to prove the diff represents the current state. The selftest passing implies it, but the hash-chain link is indirect (selftest reads settings → passes → assumes settings match diff).
- [claude] **`turn_contract.lines-341-510.txt` line [REDACTED] at token parsing**: Line 199 shows `token = [REDACTED]` — this appears to be egress redaction of a token assignment inside `_safe_sed`. Since the review bundle has `egress_redaction.enabled: true`, this is expected bundle redaction, not a code issue. But it means I can't fully verify the sed safety logic from the bundle alone.

## Context-limit notes
- [claude] The review bundle mentions "Historical round files remain on disk for audit but are deliberately not evidence for this focused scope" (review.md:4-6). I cannot see rounds 1-3 or the original PR texts (PR-001 through PR-009), which limits my ability to assess whether dismissals (especially PR-008, PR-004) were appropriate.
- [claude] The `live-scope` is referenced as a separate scope containing actual Claude model testing. Without access to that scope, I cannot verify whether the claims deferred to it are substantiated there.
- [claude] Some selftest cases reference Chinese-language patterns (e.g., `是否继续`, `当前控制面建议`) that I can parse but where my understanding of nuance in operator-model interaction might be incomplete.
- [claude] The `[REDACTED]` token in `turn_contract.lines-341-510.txt` line 199 prevents full verification of the `_safe_sed` token-iteration logic.
- arkcli: ERROR arkcli panel 全部模型失败: kimi-k2.7-code: timeout >300s; minimax-m3: parse error; output tail: tional given the "REVIEW_ONLY" scope.

Now let me think about what I, as a different model, would catch that the author might miss:

1. **The "review.md" is NOT a completed independent review** - It's a Codex-authored round 4/5 disposition. The harness's `_has_completed_independent_review` looks for "## Independent Review" in review.md. There is no such section. The harness's `_has_codex_completion_review` looks for "## CodexCompletionReview" in decisions.md. There is no such section. This means; glm-5.2: arkcli exit 1; stderr/stdout tail: {
  "ok": false,
  "error": {
    "type": "error",
    "message": "arkruntime.create_responses: RequestError code: 500, err: Post \"https://ark.cn-beijing.volces.com/api/plan/v3/responses\": unexpected EOF, request_id: 202607110721270000C0EFCFB187BEFAD3"
  }
}

- panel completed 1/2 required heterogeneous backends

> ERROR: arkcli: ERROR arkcli panel 全部模型失败: kimi-k2.7-code: timeout >300s; minimax-m3: parse error; output tail: tional given the "REVIEW_ONLY" scope.

Now let me think about what I, as a different model, would catch that the author might miss:

1. **The "review.md" is NOT a completed independent review** - It's a Codex-authored round 4/5 disposition. The harness's `_has_completed_independent_review` looks for "## Independent Review" in review.md. There is no such section. The harness's `_has_codex_completion_review` looks for "## CodexCompletionReview" in decisions.md. There is no such section. This means; glm-5.2: arkcli exit 1; stderr/stdout tail: {
  "ok": false,
  "error": {
    "type": "error",
    "message": "arkruntime.create_responses: RequestError code: 500, err: Post \"https://ark.cn-beijing.volces.com/api/plan/v3/responses\": unexpected EOF, request_id: 202607110721270000C0EFCFB187BEFAD3"
  }
}
