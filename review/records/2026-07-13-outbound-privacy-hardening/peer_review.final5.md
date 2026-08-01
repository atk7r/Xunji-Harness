# Peer Review Panel — 2026-07-13-outbound-privacy-hardening

_backend: panel:arkcli+claude · 2026-07-12T20:25Z_
> 候选, 非裁决。driver 须逐条过证据门。

## Verdict: WARN

_backend: panel:arkcli+claude_
_brain: codex_
_bundle_hash: 0d8aa74a123d2608c3363b95d1cbeb6a79748a79_
_evidence_index_hash: 6162abc7af835898713e0abfdd7b1ededddb88fb_

## Findings
- [WARN] PR-001 E-005 confirmed claim of neutral upload wire bytes is undermined by multipart boundary values that do not match the documented neutral marker format | Evidence: upload-wire.txt, upload-wire-2.txt, privacy.py.txt | Why: [panel:arkcli] [arkcli:kimi-k2.7-code] The captured wire files show boundaries whose core token is proof-<16hex> with no date, while privacy.py NEUTRAL_MARKER_RE requires proof-YYYYMMDD-<6-12hex>. The report asserts no project label in boundary, but the boundary still carries the framework-internal proof prefix in a non-compliant shape.
- [WARN] PR-002 E-004 replay artifacts use inconsistent privacy schema field names for response redactions | Evidence: privacy-replay-sample.txt.replay.json, privacy-replay-sample-2.txt.replay.json | Why: [panel:arkcli] [arkcli:kimi-k2.7-code] One record stores response redactions under response_header_redactions with bare key header:set-cookie, while the other uses response_redactions with response.header:set-cookie. This normalization gap could cause tooling to miss redacted fields.
- [WARN] PR-003 decisions.md records non-terminal statuses that conflict with presenting the bundle as finalized | Evidence: decisions.md | Why: [panel:arkcli] [arkcli:kimi-k2.7-code] D-001 is marked final-4-evidence-blocker-replicated; evidence-rereview-pending and D-002 is fixed-pending-rereview. Pending re-review is not a closed state.
- [WARN] PR-004 surface.md contents are not inspectable in the bundle, so the coverage ledger cannot be independently cross-checked | Evidence: surface.md | Why: [panel:arkcli] [arkcli:kimi-k2.7-code] The bundle only provides SHA1/size for surface.md. Rubric item 6 requires comparing surface*.md against the report, which is impossible without the file text.
- [WARN] PR-005 arkcli panel had backend errors; review is partial | Evidence: glm-5.2: parse error; output tail: le only through explicit/destination-bound paths" and "A body carrying necessary login PII requires the explicit `allow_sensitive_auth` flag." If `token=` and `api_key=` bodies don't require the flag, that's a gap. But it might be intentional - the design might only require the flag for password/secret fields specifically. Let me check the report's claims more carefully...

Report claim 2: "Necessary authentication data remains usable only through explicit/destination-bound paths." This is broad | Why: [panel:arkcli] At least one arkcli reviewer failed, so PASS only means the completed panel members found no blocker.

## Blind-spot check
- [arkcli] [kimi-k2.7-code] upload sensor boundary token shape was likely missed because review attention focused on filename/content redaction
- [arkcli] [kimi-k2.7-code] response-body redaction records are marked replayable:true, but replay would likely DIVERGE because the server returns fresh secrets while the record contains redacted placeholders
- [arkcli] [kimi-k2.7-code] fail-closed behavior on privacy import failure does not obviously cover non-URL network tools such as nc, telnet, or raw Python sockets
- [arkcli] [kimi-k2.7-code] no artifact independently proves scan.py refuses custom nuclei templates/user-data at runtime
- [arkcli] [kimi-k2.7-code] saved_body convention differs between replay records, indicating the replay schema is still stabilizing
- [claude] **Encoding recursion depth vs performance**: The `_decoded_variants` function at `privacy.py.txt:164-251` performs up to 8 levels of URL decode, plus base64 decode of every 6+ char token, plus hex decode of every 8+ char token. For large request bodies containing many base64-looking tokens, this could be computationally expensive. The author tested this with the "base64 marker after 32 benign tokens" case (line 795-796), but the general case of thousands of tokens in a large multipart upload is untested.
- [claude] **JSON field-name sensitivity matching in multipart Content-Disposition**: `_redact_multipart` at `privacy.py.txt:506-546` checks `_SENSITIVE_KEY_RE.search(field)` against the `name` attribute of multipart parts at line 530, but `validate_outbound_request` only validates multipart *filenames* (line 338-343), not *field names*. A multipart part with `name="xunji-project"` in Content-Disposition would be caught by the body-level `_raise_if_private` at line 350, so this is unlikely to be a practical bypass.
- [claude] **`tempfile` import is unused**: `privacy.py.txt:29` imports `tempfile` but the privacy.py selftest uses it only at line 931 (`with tempfile.TemporaryDirectory() as td:`). This is a selftest-only usage; the production code doesn't use tempfile. Not a problem, but worth cleaning up.
- [claude] **`unicode_escape` decoding is Python-version-dependent**: Line 187-193 of privacy.py uses `value.encode("utf-8").decode("unicode_escape")`, which behaves differently across Python versions and locales. The try/except catches decode errors, but subtle locale differences could cause inconsistent behavior.
- [claude] **No test for empty/DELETE replay with redacted URLs**: The replay tests cover GET with Cookie redaction and GET with response-body redaction, but do not cover replay of POST/PUT requests (which require `--force`) or the behavior when a replay URL itself contains hash-redacted userinfo that `redact_url` produced.

## Context-limit notes
- [arkcli] glm-5.2: parse error; output tail: le only through explicit/destination-bound paths" and "A body carrying necessary login PII requires the explicit `allow_sensitive_auth` flag." If `token=` and `api_key=` bodies don't require the flag, that's a gap. But it might be intentional - the design might only require the flag for password/secret fields specifically. Let me check the report's claims more carefully...

Report claim 2: "Necessary authentication data remains usable only through explicit/destination-bound paths." This is broad
- [claude] I was unable to read the live `tools/harness/privacy.py`, `tools/sensors/client_graybox.py`, and `tools/exploit.py` source files from the repository due to read-permission scope being limited to the review directory. My review relies on the `privacy.py.txt` copy and `reviewed.diff` excerpts provided in the review bundle. If the frozen `privacy.py.txt` in the review directory differs from the live file at `tools/harness/privacy.py`, my conclusions about fragment handling and other behavior could be invalidated.
- [claude] The review bundle's `privacy.py.txt` excerpt was truncated at ~22947 characters out of 46949 total (about 48%). I was able to read the complete file from the review directory copy, so this truncation did not affect my analysis.
- [claude] I relied on the review bundle's embedded `reviewed.diff` hunks excerpt — I did not read the full 145KB diff. If there are additional hunks beyond the 96 listed that modify the validation paths in ways relevant to fragment handling or custom script blocking, I would not have seen them.
- [claude] The CN-specific regex patterns (`_CN_PHONE_RE`, `_CN_ID_RE`) are culturally specific and I cannot fully assess whether they cover edge cases in Chinese phone number and identity card formats.