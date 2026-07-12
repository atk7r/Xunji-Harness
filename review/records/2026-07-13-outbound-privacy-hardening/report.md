# Independent Maintenance Review Request

This is a frozen Codex-authored framework diff, not a live target report.

## Claims To Challenge

1. Guarded framework execution paths reject project/run/Agent/operator identity or obvious real PII in generated target-facing fields; Agent prose instructions alone are not claimed as hard enforcement.
2. Necessary authentication data remains usable only through explicit/destination-bound paths. Guarded redirect code revalidates hops and strips cross-origin auth; its loopback behavior remains candidate evidence rather than a raw-wire claim. Request/response authentication or PII fields are redacted from replay evidence.
3. Neutral proof names use a fixed format plus a random nonce; the upload sensor emits no project label in filename, content, or multipart boundary.
4. Covered raw uninspectable file-upload and redirect-following auth command forms fail before I/O; URL-hidden custom network scripts remain author-and-handoff rather than claimed as hook-verifiable.
5. Privacy-redacted replay cannot be sent or counted as verification; final confirmed evidence requires a per-entry replay disposition and fresh guarded replication.
6. Claude Root, Agent templates, loop prompt, workflow docs, hook, guard, probe, render, scan, replay, closure and sentinel layers remain consistent.

## Reviewer Focus

- Look for bypasses through percent/base64/hex encoding, file-backed payloads, headers, redirects, browser XHR/fetch, custom scripts, and legacy cleanup.
- Re-check URL userinfo/fragment handling, multipart filename/boundary recording,
  response Location/custom-auth headers, and response-preview redaction.
- Verify that `tools/exploit.py` really inherits guarded HTTP and that
  `client_graybox.py` has no active egress path.
- Look for false positives that would block ordinary target paths, query payloads, proof methods, target-provided destination names, or necessary auth.
- Check whether logs/replay retain reusable secrets or whether redaction breaks evidence semantics silently.
- Check fail-open behavior if the privacy module cannot import.
- Check tests for circular assumptions and missing end-to-end proof.

- Evidence IDs: E-001, E-004, E-005, E-007
- Candidate validation context: E-002, E-003, E-006
- Fingerprints captured: none; local maintenance only
