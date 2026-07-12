# Peer Review Panel — 2026-07-13-outbound-privacy-hardening

_backend: panel:arkcli+claude · 2026-07-12T20:52Z_
> 候选, 非裁决。driver 须逐条过证据门。

## Verdict: WARN

_backend: panel:arkcli+claude_
_brain: codex_
_bundle_hash: 8490930eb06f4da0cef977e151a5d97bd3954b81_
_evidence_index_hash: 08c90bc9cfbb7288b8e0e8e815d239c95a9c1778_

## Findings
- [WARN] PR-001 E-005 upload sensor emits a fresh dated neutral multipart boundary for each upload | Evidence: upload-wire-3.txt, upload-wire-4.txt, upload-result-3.json, upload-result-4.json | Why: [panel:arkcli] [arkcli:kimi-k2.7-code] The captured wire files show boundary=proof-20260712-... while the transmitted filename and marker are proof-20260713-..., indicating the boundary is stale (likely generated once at import or earlier run). This does not leak identity but violates the documented 'proof-YYYYMMDD-<hex>' shape for each upload and could cause replay/cache correlation issues.
- [WARN] PR-002 E-004 and E-007 confirm that privacy redaction works for target-facing replay records | Evidence: privacy-replay-sample-2.txt.replay.json, privacy-replay-sample-3.txt.replay.json, response-redaction-runtime.replay.json, response-redaction-runtime-2.replay.json | Why: [panel:arkcli] [arkcli:kimi-k2.7-code] All replay artifacts are from 127.0.0.1 fixtures under the author's control. Per evidence discipline, environment-provided/self-generated artifacts are not standalone confirmation; real targets may produce auth headers, redirects, and response bodies outside the tested redaction paths.
- [WARN] PR-003 The confirmed findings can be accepted without the independent rereview mandated by D-001 | Evidence: decisions.md, reviewed.diff, verification.txt | Why: [panel:arkcli] [arkcli:kimi-k2.7-code] Decisions.md D-001 explicitly states that Codex self-review is not an independent vote and lists status as 'new-boundary-code-rereview-pending'. Treating the current confirmed findings as final would violate the run's own governance gate.
- [WARN] PR-004 E-002 confirms the full regression battery passed | Evidence: verification.txt | Why: [panel:arkcli] [arkcli:kimi-k2.7-code] verification.txt is a prose summary authored in the same context; it cannot be independently verified without logs or exit-code records.
- [WARN] PR-005 E-003 browser integration and E-006 redirect credential controls are ready for promotion beyond candidate | Evidence: browser-integration.txt, redirect-wire.json | Why: [panel:arkcli] [arkcli:kimi-k2.7-code] E-003 is a single loopback fixture observation and E-006 is a boolean JSON table without hop-by-hop wire captures; neither meets the evidence standard for confirmed findings.
- [WARN] PR-006 arkcli panel had backend errors; review is partial | Evidence: glm-5.2: parse error; output tail: ct this. This is a claim integrity issue - the evidence ledger says confirmed but the artifacts say candidate.

**Issue 5: No probe for bypasses through encoding**
The report says "Look for bypasses through percent/base64/hex encoding, file-backed payloads, headers, redirects, browser XHR/fetch, custom scripts, and legacy cleanup." The verification.txt item 5 says these are covered, but I don't see separate replay artifacts or .replay.json files for encoding bypass attempts. The only evidence is | Why: [panel:arkcli] At least one arkcli reviewer failed, so PASS only means the completed panel members found no blocker.

## Blind-spot check
- [arkcli] [kimi-k2.7-code] No runtime evidence against an authorized real target; every confirmed replay/upload artifact is localhost.
- [arkcli] [kimi-k2.7-code] E-006 only provides a boolean JSON table, not actual hop-by-hop request/response captures, so cross-origin auth-stripping is not demonstrated on the wire.
- [arkcli] [kimi-k2.7-code] The boundary/date mismatch suggests tests only checked for absence of 'xunji' labels, not date consistency or per-upload freshness.
- [arkcli] [kimi-k2.7-code] Fail-closed behavior when privacy.py cannot import is asserted in code but not demonstrated by an artifact where the module is deliberately removed mid-run.
- [arkcli] [kimi-k2.7-code] tools/exploit.py inheritance of guarded HTTP and client_graybox.py passivity are claimed from diff hunks, not from live network captures or selftest logs.
- [arkcli] [kimi-k2.7-code] No coverage ledger reconciliation is shown; surface.md exists but there is no mapping to classified or probed assets.
- [arkcli] [kimi-k2.7-code] Privacy.py's local-identity blocklist could false-block legitimate target routes containing the operator's username/home path; the escape is author-and-handoff with no documented target-side allowlist.
- [claude] **Boundary generation independence**: The upload sensor's multipart boundary date is generated independently from the marker date — they can diverge by up to 24 hours (as seen in E-005). If a boundary is generated at 23:59 and the marker at 00:01, the dates will differ. This doesn't break the privacy contract but means the "matching" claim needs a narrower scope (same format family, not same date).
- [claude] **POST/PUT replay with `--force` is untested**: Every replay artifact in this bundle is a GET request. The replay system's `--force` flag for POST/PUT/DELETE has no test coverage with redacted records. If a redacted POST body contains a hash placeholder, replay with `--force` would send the literal `<redacted:...>` string to the target — a potential information leak of the redaction format itself.
- [claude] **`saved_body` convention is loopback-only**: All replay artifacts use `<ephemeral-loopback-body-removed>`. There is zero evidence of how a real target response body would be handled in a privacy-redacted replay record. The `privacy.py.txt` redaction functions exist, but their integration with the recorder for non-loopback responses is untested.
- [claude] **Encoding depth: tested with 32 tokens, not thousands**: The `_decoded_variants` function decodes every base64/hex-looking token in the entire body. A large multipart upload with thousands of tokens (e.g., a binary file upload that happens to contain many hex-like substrings) could trigger expensive per-token UTF-8 decode attempts. The selftest covers "base64 marker after 32 benign tokens" but not worst-case throughput.
- [claude] **`unicode_escape` decoding is Python-version and locale dependent**: `privacy.py.txt:195` uses `value.encode("utf-8").decode("unicode_escape")` which behaves differently across CPython versions (3.9 vs 3.12 vs 3.13) and can be affected by the process locale. The try/except is a safety net but doesn't guarantee consistent detection across environments.
- [claude] **`tempfile` import unused in production**: `privacy.py.txt:29` imports `tempfile` but the only usage is in the selftest at line 931. A minor hygiene issue but worth cleaning up before declaring the module frozen.
- [claude] **No end-to-end cross-process privacy test**: Every test is either a selftest (code tests itself) or a single-process loopback (probe connects to a Python fixture in the same repo). There's no test where a separate Claude Code process sends a command through the hook, the hook calls privacy.py, and the blocked/approved decision is observed from outside. This means we've never observed the privacy gate operating in its actual deployment context (Claude Code hook → privacy module → allow/deny).

## Context-limit notes
- [arkcli] glm-5.2: parse error; output tail: ct this. This is a claim integrity issue - the evidence ledger says confirmed but the artifacts say candidate.

**Issue 5: No probe for bypasses through encoding**
The report says "Look for bypasses through percent/base64/hex encoding, file-backed payloads, headers, redirects, browser XHR/fetch, custom scripts, and legacy cleanup." The verification.txt item 5 says these are covered, but I don't see separate replay artifacts or .replay.json files for encoding bypass attempts. The only evidence is
- [claude] I read the complete `privacy.py.txt` (1009 lines) from the review directory, not the truncated excerpt from the bundle. The bundle excerpt was cut at ~48%.
- [claude] I relied on the `reviewed.diff` hunks excerpt embedded in the bundle — I did not read the full 145KB diff. If there are hunks beyond the 96 listed (the bundle says 99 hunks) that materially change validation paths, I did not see them.
- [claude] The CN-specific regex patterns (`_CN_PHONE_RE`, `_CN_ID_RE`) are culturally specific. I cannot assess whether they cover edge cases in Chinese phone number formats (e.g., virtual operators, IoT numbers) or identity card formats (e.g., Hong Kong/Macau/Taiwan ID variants, new-format 18-digit cards with X suffix variants).
- [claude] My review is scoped to the review directory files only — I did not read live `tools/harness/privacy.py`, `tools/sensors/client_graybox.py`, or `tools/exploit.py` from the repository. If the frozen `privacy.py.txt` in the review directory differs from the live source, my conclusions could be invalidated.
- [claude] The review bundle's `surface.md` was inspectable via file read, so PR-004 from final-5 is resolved from my perspective.