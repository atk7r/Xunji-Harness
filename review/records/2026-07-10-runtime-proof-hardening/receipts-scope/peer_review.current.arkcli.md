# Peer Review — receipts-scope

_backend: arkcli:kimi-k2.7-code+glm-5.2 · 2026-07-11T00:28Z_
> 候选, 非裁决。driver 须逐条过证据门: 不盲从(驳工具/语境误报), 不忽视(采纳真盲补)。

## Verdict: WARN

_backend: arkcli:kimi-k2.7-code+glm-5.2_  
_brain: codex_  
_bundle_hash: 23d841ba31a5119f04675844d9a67f031bb7fc80_  
_evidence_index_hash: de1e0d14ca8edb640323ceef2a2b06bd62e940bb_  

## Findings
- [WARN] PR-001 E-001’s 0.8 confirmation rests on synthetic selftest summaries and source excerpts, with no observed runtime hook transcript or runtime_events.jsonl | Evidence: adversarial_selftests.summary.json, selftest_all.log, runtime_receipts.lines-001-150.txt, installed-runtime-manifest.json | Why: [arkcli:kimi-k2.7-code] The static/control scope deliberately limits evidence, but F-001 is an open runtime-integrity front. Static selftests validate logic but cannot confirm hooks fired for real Agent/Cron/Bash events in this run.
- [WARN] PR-002 Hook deployment is inferred from a diff and a manifest, but the actual .claude/settings.json artifact is not present in the bundle | Evidence: settings.diff, installed-runtime-manifest.json | Why: [arkcli:kimi-k2.7-code] The reviewer cannot cross-check that the currently installed settings match the manifest; deployment drift between the diff and the live settings remains possible.
- [WARN] PR-003 selftest_all.log is a high-level pass/fail summary without per-suite stderr/stdout attachments | Evidence: selftest_all.log | Why: [arkcli:kimi-k2.7-code] Independent replay of failures or inspection of actual check output is impossible; the evidence is self-reported at the summary level only.
- [WARN] PR-004 evidence.md exists in the run directory but its content is not exposed in the bundle | Evidence: files/evidence.md | Why: [arkcli:kimi-k2.7-code] Any additional observations or claims in evidence.md are unavailable to the panel, creating an unreviewed surface gap.
- [WARN] PR-005 arkcli panel had backend errors; review is partial | Evidence: glm-5.2: arkcli exit 1; stderr/stdout tail: {
  "ok": false,
  "error": {
    "type": "error",
    "message": "arkruntime.create_responses: RequestError code: 500, err: Post \"https://ark.cn-beijing.volces.com/api/plan/v3/responses\": net/http: TLS handshake timeout, request_id: 2026071108280500007ED8BCB3DFB08A03"
  }
}
 | Why: At least one arkcli reviewer failed, so PASS only means the completed panel members found no blocker.

## Blind-spot check
- [kimi-k2.7-code] No live runtime_events.jsonl or hook-transcript artifact was generated for this run; chain validation, fanout, cron-quiescence, and denial-resolution paths have only been exercised in synthetic temp directories.
- [kimi-k2.7-code] The adversarial selftest summary reports per-command output SHA-256s, but the actual selftest output streams are not included, so reviewers must trust the summary generator.
- [kimi-k2.7-code] The full repository regression includes many unrelated suites; while correctly treated as a control artifact, it does not strengthen the receipt-specific claim.
- [kimi-k2.7-code] installed-runtime-manifest.json records local absolute paths; reproducibility would benefit from normalized paths or environment metadata.

## Context-limit notes
- glm-5.2: arkcli exit 1; stderr/stdout tail: {
  "ok": false,
  "error": {
    "type": "error",
    "message": "arkruntime.create_responses: RequestError code: 500, err: Post \"https://ark.cn-beijing.volces.com/api/plan/v3/responses\": net/http: TLS handshake timeout, request_id: 2026071108280500007ED8BCB3DFB08A03"
  }
}
