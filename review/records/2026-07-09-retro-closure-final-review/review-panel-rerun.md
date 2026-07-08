# Peer Review Panel — 2026-07-09-retro-closure-final-review

_backend: panel:claude · 2026-07-08T18:10Z_
> 候选, 非裁决。driver 须逐条过证据门。

## Verdict: NEEDS_DRIVER

_backend: panel:claude_
_brain: codex_
_bundle_hash: 3d0c6603d9f8292d95e8bdb63db87f6edbe48599_
_evidence_index_hash: 74190a924720565e138dd838496dba1b10f58c33_

## Findings
- [WARN] PR-001 review panel had backend errors; aggregation is partial | Evidence: arkcli: ERROR arkcli panel 全部模型失败: kimi-k2.7-code: timeout >300s; minimax-m3: arkcli exit 1; stderr/stdout tail: {
  "ok": false,
  "error": {
    "type": "error",
    "message": "arkruntime.create_responses: RequestError code: 500, err: Post \"https://ark.cn-beijing.volces.com/api/plan/v3/responses\": net/http: TLS handshake timeout, request_id: 202607090205440000CDFB3D6A656D7736"
  }
}
; glm-5.2: parse error; output tail: -hr.md`, and `peer_review.py`, but the visible diff excerpt doesn't show these. The reviewer should have either verified these exist in the full diff or flagged that they couldn't be verified.

2. **Missing evidence for `check_rules.py`**: The report claims this passed but no evidence entry exists.

3. **No evidence of actual code review of the diff**: The report lists "change groups" and "expected invariants" and "review questions" but doesn't actually report any findings about potential issues | Why: At least one requested heterogeneous reviewer failed or was unavailable.

## Blind-spot check
- [claude] **The same-cycle guidance is a phrasing change in hook messages, not enforced machinery**: The diff changes `build_message` and `build_open_fronts_message` in run_gate.py to say "同一回合内" (same cycle) and "请在同一回合继续推进" (please continue in the same cycle). These are natural-language messages displayed to the model, not programmatic enforcement. The model could still end the turn despite receiving this message, especially in non-interactive contexts (like this very review). The report claims "guidance now forces same-cycle handling" but "forces" overstates the mechanism — it's advisory text, not a hard gate. An actual enforcement mechanism would require the hook to refuse to stop until the gate passes, which no hook change implements.
- [claude] **The `_append_manual_driver_template` function added to peer_review.py handles NEEDS_DRIVER verdicts gracefully but review.md was never populated by it**: The diff at lines 8924-8942 adds a function that writes a "not a completed review" template when review backends fail. The current review.md content ("Independent review will be generated...") doesn't match the template format — meaning peer_review.py was likely never invoked against this scope, or invoked and got an ERROR rather than NEEDS_DRIVER. Either way, the review gap is a process failure, not a tooling gap.
- [claude] **The diff interleaving makes it impossible to distinguish "current changes" from "prior review audit trail"**: The staged diff has two complete sets of changes for check_run.py, probe.py, peer_review.py, loop_state.py, and others — one set with `+` prefix (from prior review rounds saved as audit trail) and one set without (the actual staged changes). For files like coverage_matrix.py, check_run.py, and classify_hosts.py, there are duplicates. This means a reviewer reading the diff linearly cannot easily tell which change is "active" vs. "historical record." This directly undermines the auditability the CLAUDE.md promises.
- [claude] **The --replay-verify decision (D-002) is rational but leaves a verification gap**: D-002 correctly notes that live replay verification is inappropriate for a maintenance diff. However, this means no end-to-end integration test was performed with the actual scshr_20260708 run directory against the changed tools. The selftest passes on isolated test fixtures, but we don't know whether check_run.py with the new loop_state integration actually works correctly against the scshr run that triggered the retrospective.
- [claude] **The reported "53 passed, 0 failed" selftest includes classify_hosts which took 39.9s**: This is the longest test in the suite and likely exercises real network/file I/O. The long runtime could hide flakes or environment dependencies that only manifest in CI or on a different machine.
- [claude] **Chinese-language context-limit caveat**: The retrospective.md and many hook messages are in Chinese. I can read them, but nuanced enforcement semantics (especially around "同一回合" — same cycle — and whether Chinese politeness particles in hook messages affect model compliance) depend on interpretation conventions established within the Xunji project that I may not fully share.

## Context-limit notes
- [claude] The ZUSO ART advisories (ZA-2025-04..09) and NVD CVEs (CVE-2025-5192, CVE-2025-48780..48784) referenced in the knowledge entry are Taiwanese HRD product disclosures. I cannot independently verify these CVE IDs against public databases — my knowledge cutoff may not include all of them. The previous review round's context-limit notes flagged this same concern.
- [claude] The `runs/scshr_20260708/` directory is gitignored and I was denied read access. My assessment of whether the diff addresses the retrospective failure classes is therefore incomplete — I'm relying on the report's characterization.
- [claude] Some Chinese-language edge cases in the anti-lump classification (e.g., whether "伺服端資訊" == server-info page detection logic is correct for all Chinese-language server variants) may have vendor-specific quirks I cannot fully assess.
- arkcli: ERROR arkcli panel 全部模型失败: kimi-k2.7-code: timeout >300s; minimax-m3: arkcli exit 1; stderr/stdout tail: {
  "ok": false,
  "error": {
    "type": "error",
    "message": "arkruntime.create_responses: RequestError code: 500, err: Post \"https://ark.cn-beijing.volces.com/api/plan/v3/responses\": net/http: TLS handshake timeout, request_id: 202607090205440000CDFB3D6A656D7736"
  }
}
; glm-5.2: parse error; output tail: -hr.md`, and `peer_review.py`, but the visible diff excerpt doesn't show these. The reviewer should have either verified these exist in the full diff or flagged that they couldn't be verified.

2. **Missing evidence for `check_rules.py`**: The report claims this passed but no evidence entry exists.

3. **No evidence of actual code review of the diff**: The report lists "change groups" and "expected invariants" and "review questions" but doesn't actually report any findings about potential issues
- panel completed 1/2 required heterogeneous backends

> ERROR: arkcli: ERROR arkcli panel 全部模型失败: kimi-k2.7-code: timeout >300s; minimax-m3: arkcli exit 1; stderr/stdout tail: {
  "ok": false,
  "error": {
    "type": "error",
    "message": "arkruntime.create_responses: RequestError code: 500, err: Post \"https://ark.cn-beijing.volces.com/api/plan/v3/responses\": net/http: TLS handshake timeout, request_id: 202607090205440000CDFB3D6A656D7736"
  }
}
; glm-5.2: parse error; output tail: -hr.md`, and `peer_review.py`, but the visible diff excerpt doesn't show these. The reviewer should have either verified these exist in the full diff or flagged that they couldn't be verified.

2. **Missing evidence for `check_rules.py`**: The report claims this passed but no evidence entry exists.

3. **No evidence of actual code review of the diff**: The report lists "change groups" and "expected invariants" and "review questions" but doesn't actually report any findings about potential issues