# Evidence Ledger

## E-001 — Frozen Codex-authored maintenance diff

- Maturity: finding
- Reportable: yes
- Action: froze the privacy-hardening tracked diff plus the new outbound privacy module before independent review, explicitly excluding the concurrent unrelated `TODO.md` roadmap replacement.
- Result: `reviewed.diff` is the exact review subject.
- Certainty: 1.0
- Replicated / Control: reviewer must cite concrete hunks from the frozen diff; narrative files are claims only. `reviewed.diff` contains no `TODO.md` hunk.
- Artifacts: `reviewed.diff`, `privacy.py.txt`
- Supports: F-001 review scope

## E-002 — Full regression battery

- Maturity: candidate
- Reportable: no
- Action: `python3 tools/check_rules.py` and `python3 tools/selftest_all.py`
- Result: rule check passed; after final-3 fixes all 60 registered suites passed, 0 failed in 84.7s, including exploit, scan privacy plus privacy, hook, probe, render, replay, check_run, workers, sentinel and guard suites.
- Certainty: 0.5
- Replicated / Control: the first full run exposed a stale harmless-upload cross-layer fixture; it was fixed. After each independent-review fix round the complete suite was rerun; the final frozen code passed 60/60.
- Artifacts: `verification.txt`
- Supports: F-001 regression claim

## E-003 — Browser pre-I/O integration

- Maturity: candidate
- Reportable: no
- Action: launched a loopback-only HTTP fixture whose page attempted `POST marker=xunji-proof`, then ran `render.render(...)` with Playwright routing.
- Result: server-side POST count remained zero and render returned `outbound privacy blocked request body: project identifier`.
- Certainty: 0.5
- Replicated / Control: the server counter is independent of the browser error string and proves the request was not delivered.
- Artifacts: `browser-integration.txt`
- Supports: F-001

## E-004 — Runtime replay redaction and non-replay verdict

- Maturity: finding
- Reportable: yes
- Action: twice sent a loopback GET with distinct client Cookie values to fresh-port fixtures returning distinct Set-Cookie values, saved through the current `probe.send` recorder, then invoked `tools/replay.py` separately on both records with explicit loopback scope.
- Result: both request Cookie and response Set-Cookie pairs are represented only by distinct hash redactions in their runtime `.replay.json`; both replay invocations returned `SKIPPED-PRIVACY-REDACTED` without sending placeholders.
- Certainty: 1.0
- Replicated / Control: the two runs used different ports, bodies, client Cookie values and server Set-Cookie values. Inspect both runtime records for different hashes and absence of reusable values, then compare the two separate replay verdicts.
- Artifacts: `privacy-replay-sample-2.txt.replay.json`, `privacy-replay-verdict-2.txt`, `privacy-replay-sample-3.txt.replay.json`, `privacy-replay-verdict-3.txt`
- Supports: F-001 replay/privacy closure behavior

## E-005 — Actual neutral upload wire bytes

- Maturity: finding
- Reportable: yes
- Action: sent the upload sensor to a loopback fixture and captured the server-observed Content-Type plus complete multipart request body.
- Result: both servers returned 201; wire bodies contain fresh dated neutral markers/filenames, use `----proof-YYYYMMDD-<8hex>` boundaries, and contain no project identifier.
- Certainty: 1.0
- Replicated / Control: two independent loopback requests used marker/filename/boundary values derived from `proof-20260713-e5f6a7b8` and `proof-20260713-f6a7b8c9`; both returned 201 and each server-observed multipart boundary exactly matches its request's marker.
- Artifacts: `upload-wire-5.txt`, `upload-result-5.json`, `upload-wire-6.txt`, `upload-result-6.json`, `upload-replication.txt`
- Supports: F-001

## E-006 — Loopback three-origin redirect credential candidate

- Maturity: candidate
- Reportable: no
- Action: sent a loopback GET with Cookie and Authorization through three HTTP servers on different origins (ports), with hop 1 and hop 2 returning 302.
- Result: hop 1 received both auth headers; hop 2 and hop 3 received neither; final response was 200.
- Certainty: 0.5
- Replicated / Control: three server-side header booleans from one loopback harness distinguish initial intended delivery from both redirected hops; no raw wire capture is claimed.
- Artifacts: `redirect-wire.json`
- Supports: F-001

## E-007 — Runtime response replay redaction

- Maturity: finding
- Reportable: yes
- Action: ran two fresh loopback responses containing distinct JSON token/email values plus distinct `X-Session-ID` and `Location?access_token=` values, saving each through `probe.send`.
- Result: both replay JSON artifacts retain status/hash/length and hash placeholders, while all eight raw response values are absent; response redaction metadata identifies JSON fields and response headers.
- Certainty: 1.0
- Replicated / Control: two independent loopback servers used different ports and different raw values; both recordings produced the same field-class redaction behavior. Raw response bodies were ephemeral and removed after the replay JSON was checked.
- Artifacts: `response-redaction-runtime.replay.json`, `response-redaction-runtime-2.replay.json`
- Supports: F-001 response-record privacy behavior
