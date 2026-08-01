# Peer Review Panel — 2026-07-13-outbound-privacy-hardening

_backend: panel:arkcli+claude · 2026-07-12T20:16Z_
> 候选, 非裁决。driver 须逐条过证据门。

## Verdict: WARN

_backend: panel:arkcli+claude_
_brain: codex_
_bundle_hash: c571d7ef78bf99c40fce76d0611b74d54910cf1e_
_evidence_index_hash: 6a26e7dbe6ec92368f610e66ac8f701a3fecf405_

## Findings
- [BLOCKER] PR-001 E-004 is reported as confirmed (certainty 1.0), but it rests on a single privacy-redacted replay record and a single derived verdict. | Evidence: privacy-replay-sample.txt.replay.json (sha1 cf51435e3b34cfa057631d090b7cfeabb1e03e5f), privacy-replay-verdict.txt (sha1 b2387eb27d7144de6e0a96e0a43bfaad58460e4b), evidence_index:E-004 | Why: [panel:arkcli] [arkcli:kimi-k2.7-code] Evidence discipline says single observations are never confirmation on their own. Only one loopback request/response pair is shown, and the verdict file is derived from that same artifact. No replicated second run or control disproves incidental behavior.
- [WARN] PR-002 Claim 2 (auth/PII stripped across origin redirects and kept destination-bound) is not confirmed; the only redirect evidence is the 0.5-candidate E-006 with no raw per-hop replay artifacts. | Evidence: redirect-wire.json (sha1 e308220b8b437187e20756cf18eb1bd8d806d7fe), evidence_index:E-006 (certainties [0.5], confirmed false), verification.txt:item 6, report.md:Claim 2 | Why: [panel:arkcli] [arkcli:kimi-k2.7-code] A single loopback JSON summary with boolean flags is a single observation; redirects/block pages cannot confirm a control. The actual request/response chain for each hop is missing.
- [WARN] PR-003 The review bundle truncates privacy.py.txt and reviewed.diff, so key functions (URL userinfo redaction, hook --allow-sensitive-auth parsing, the full changed-file set) cannot be independently cross-checked. | Evidence: privacy.py.txt (size 46949, excerpt 22947, sha1 39a7519fb9be3a3a80ef54a148aa162390654507), reviewed.diff (size 145845, excerpt 118778, sha1 8b3c1171f226c7152c8a011e60639e9420ebfae6) | Why: [panel:arkcli] [arkcli:kimi-k2.7-code] The excerpt ends before redact_url and the tail of the diff; the reviewer cannot verify that URL userinfo is hash-redacted, that the command gate correctly honors the sensitive-auth exception, or that all claimed files/hunks are present. This breaks the artifact cross-check mandate.
- [WARN] PR-004 Adversarial bypass surfaces (percent/base64/hex nested encodings, file-backed curl uploads, custom network scripts, browser fetch headers/multipart/redirects) are documented only as candidate summary prose and selftests, not as saved runtime probe/replay artifacts. | Evidence: verification.txt:items 5,6,8, browser-integration.txt (single fetch-body case), evidence_index:E-002 (certainties [0.5]), evidence_index:E-003 (certainties [0.5]) | Why: [panel:arkcli] [arkcli:kimi-k2.7-code] The report explicitly asks reviewers to look for these bypasses, but the ledger contains only code-level assertions. Runtime confirmation requires per-class artifacts with controls.
- [WARN] PR-005 No confirmed runtime evidence verifies that all tools/exploit.py plugins route through probe.send, that tools/render.py intercepts page-initiated navigation/forms/multipart/websocket traffic, or that tools/scan.py does not leak run paths via the nuclei command line. | Evidence: reviewed.diff:tools/exploit.py hunks, reviewed.diff:tools/render.py hunks, reviewed.diff:tools/scan.py hunks, verification.txt:item 8, report.md:Claim 6 | Why: [panel:arkcli] [arkcli:kimi-k2.7-code] The diff excerpts show partial changes; the verification summary asserts the properties but does not supply per-layer .replay.json/wire-capture controls. Broad consistency claims across layers are therefore unconfirmed.
- [WARN] PR-006 arkcli panel had backend errors; review is partial | Evidence: glm-5.2: parse error; output tail: ifferent. This is consistent.

11. **Looking at the diff more carefully for the `safety_gate.py` changes**: The hook now imports privacy module and calls `outbound_command_privacy_reason`. If the module can't import, URL-bearing commands fail closed. The selftest tests this. But there's a subtlety: `TARGET_URL_RE` is `re.compile(r"(?:https?|wss?|ftp)://", re.IGNORECASE)` - this matches `ws://` and `wss://` too. But what about `gopher://`, `file://`, `dict://`, or other protocols? The report says | Why: [panel:arkcli] At least one arkcli reviewer failed, so PASS only means the completed panel members found no blocker.

## Blind-spot check
- [claude] **As a different model from the author**, my primary blind spot is that I'm evaluating Claude-authored code — the heterogeneity is practical (fresh context) but not architectural. The arkcli panel (kimi-k2.7-code + glm-5.2) in prior rounds provided the strongest heterogeneity signal, and those findings were properly adjudicated.
- [claude] **Encoding-defense mechanism**: The `_decoded_variants` function in `privacy.py.txt:181-251` does up to 8 passes of percent decoding and inspects all discovered base64/hex tokens. I confirmed there is NO 32-token cap (contrary to a prior-round blind-spot). Both `re.findall` calls return ALL matches. The prior concern was based on outdated code. This mechanism is solid.
- [claude] **Response-snippet redaction**: The E-004 replay JSON snippet (`privacy-replay-sample.txt.replay.json:24`) says `"privacy-replay-ok"` — a harmless value. E-004 proves header redaction, not response-body redaction. E-007 is supposed to cover response-body redaction but the bodies were deleted. The `privacy.py` selftest at line 984-1000 covers JSON body redaction in code, but no preserved artifact proves the runtime replay path redacts a real PII-laden response body.
- [claude] **`check_run.py` SKIPPED-PRIVACY-REDACTED enforcement**: The code in `check_run.py` (diff hunks) adds hard-gate enforcement for unaddressed privacy-redacted replays. The `check_run` selftest at line 770-776 tests the `_replay_unacked_findings` function. No end-to-end test artifact proves a run is actually blocked by this gate. The mechanism code is correct; the integration test is not preserved.
- [claude] **New since prior reviews**: The false-positive fix for `/home/dashboard`, `/Users/settings`, `/runs/list` (disposition.md final-3 PR-002) is directly visible in the selftest at `privacy.py.txt:807-814`. I verified the code uses only actual local home values (`_local_home_values()` at line 164-169) and dated-framework-run patterns (`_INTERNAL_PATTERNS` at line 50-53) rather than generic path shapes. This fix is correct.
- [claude] **E-006 redirect-wire.json**: The three-hop booleans in `redirect-wire.json:1-18` correctly show auth present at hop1 and absent at hops 2-3. The candidate status (certainty 0.5) is appropriate — it's a synthesized server-side assertion, not raw wire capture. The evidence.md correctly refrains from promoting this.

## Context-limit notes
- [arkcli] glm-5.2: parse error; output tail: ifferent. This is consistent.

11. **Looking at the diff more carefully for the `safety_gate.py` changes**: The hook now imports privacy module and calls `outbound_command_privacy_reason`. If the module can't import, URL-bearing commands fail closed. The selftest tests this. But there's a subtlety: `TARGET_URL_RE` is `re.compile(r"(?:https?|wss?|ftp)://", re.IGNORECASE)` - this matches `ws://` and `wss://` too. But what about `gopher://`, `file://`, `dict://`, or other protocols? The report says
- [arkcli] arkcli succeeded after 2 attempt(s); previous failures: attempt 1: arkcli panel 全部模型失败: kimi-k2.7-code: timeout >300s; glm-5.2: parse error; output tail: al_home_values()`:
```python
def _local_home_values() -> list[str]:
    values = [str(Path.home()), str(os.environ.get("USERPROFILE", ""))]
    return list(dict.fromkeys(
        value.rstrip("/\\") for value in values
        if value and value not in {"/", ".", "\\"}
    ))
```
What if `home` is empty? It returns empty. What if `Path.home()` is `/root`? It returns `/root`.

Wait, look at `_decoded_variants`:
```python
    tokens = re.findall(r"(?<![A-Za-z0-9+/_-])[A-Za-z0-9+/_-]{6,}={0,2}(?![A
- [claude] I had full access to all files in the review bundle directory. The privacy.py.txt file is 46,949 bytes and was read in its entirety (1009 lines).
- [claude] I did not have direct filesystem access to the main repository's `tools/harness/guard.py` or `.claude/hooks/safety_gate.py`. My analysis of pre-existing (non-diff'd) portions of these files relies on the diff hunks in `reviewed.diff`. The functions `extract_command`, `cleanup_requires_ask`, `load_rules`, and `deny` in safety_gate.py are pre-existing and not shown in the diff — I cannot independently verify they don't have interactions with the new privacy code beyond what the diff reveals.
- [claude] The Chinese-language content in `evidence.md`, `disposition.md`, `target.md`, and denial messages appears syntactically consistent. I may miss subtle semantic nuances in Chinese error messages or documentation.
- [claude] The CN phone/ID regexes (`privacy.py.txt:62-63`) cover standard mainland China formats. Hong Kong (8-digit), Macau (8-digit), and Taiwan (10-character new-format) ID numbers are not matched. This is an acknowledged scope limitation.
- [claude] I cannot independently recompute the SHA-1 hashes cited in the evidence index; I rely on the bundle's hash claims. All artifacts I directly read match their described content.