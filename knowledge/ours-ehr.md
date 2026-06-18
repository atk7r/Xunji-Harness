---
id: ours-ehr
product: 致远薪事力 数智化人力云平台 (OURS eHR)
vendor: 北京致远互联软件股份有限公司 (科创板 688369) / 致远薪事力(苏州)云科技有限公司
aliases: [ours, ours-ehr, 薪事力, 致远薪事力, x-dhr, DHR人力云]
category: framework-management-endpoint
last_reviewed: 2026-06-12
maturity: verified
signatures: ["/res_common/ours/", "ours_user_token", "ours_pc.min.js", "薪事力"]
---

<!--
Grounding knowledge, not a weapon. Recognition + weakness class + references +
proof-only verification principle only. No payloads/steps/slider-solver code —
the driver derives the specific proof check at runtime (tools/probe.py,
tools/render.py). The reproduction PoC and exploit chain live in the run
directory (runs/<run>/), never here.
-->

## Recognition (identification only)

- Signature: request dispatch via the `*.do?method=*` shape; login page `/login.do`, homepage 302 → `/login.do`.
- Signature: static resource prefix `/res_common/ours/`, core bundle `/res_common/ours_pc.min.js`, captcha component
  `/res_common/ours/system/ours-verify.js`.
- Signature: business response JSON wrapper `{"errcode":...,"msg":...,"success":...,"async":...,"waitSecond":...}`.
- Signature: session cookie family `ours_user_token` + `_csrf` (some instances `DHRSESSIONID`).
- Signature: inline `ours_context` / `ours_contextPath` global objects; CSS `ehrIconFont.css`, `/ehr/common/...` module paths.
- Signature: site/brand meta `薪事力,致远互联薪事力,致远薪事力` (vendor-attribution anchor, vendor = 致远互联 688369).
- Distinguishing notes: the version is in the resource `?V=` query string (e.g. `?V=7.11.01.1172`, `?V=8.04.01.1360`,
  `?V=4.03.01.94`) — the same stack across v4~v8. What separates it from other `.do`-dispatch OA (e.g. Seeyon A8 /
  Weaver) is the `/res_common/ours/` prefix + `ours_user_token`.

## Weak-Point Anchors (variant-analysis input — NOT exploit steps)

- Anchor: file-upload interface unauthenticated-reachable (authentication bypass on upload handler)
  - Affected: OURS eHR v4.03 ~ v8.04 same stack (run-verified consistent across versions); a framework-level flaw,
    not a single-instance config.
  - Mechanism: the upload handler lacks a session/permission interception layer before business logic, so an anonymous
    request reaches business code directly and returns a business-level parameter-validation response (rather than a
    login redirect / 401). Other interfaces of the same framework correctly 302 anonymous requests to login, proving the
    auth mechanism itself works and only this interface omits it. The only front gate is a client-side slider captcha, and
    the captcha-challenge interface is likewise unauthenticated, has no rate limit, and ships the decryption key in
    plaintext with the challenge — so it is not effective authentication.
  - Reference: CWE-434 (Unrestricted Upload of File with Dangerous Type) + CWE-306 (Missing Authentication for Critical Function).
  - source: run-observation (<run>: 11/12 internet instances confirmed an uploaded file landed and was readable;
    100-sample Part-A hit 56%)
- Anchor: the slider captcha is not an authentication boundary (client-side challenge, server trusts trajectory only)
  - Affected: the `ours-verify.js` slider component (common to the stack).
  - Mechanism: the challenge-generation interface is anonymously fetchable; the DES decryption key (a short key) is in
    plaintext in the challenge response; the server only validates the drag trajectory data, which can be reproduced in a
    real browser environment. Treating the captcha as an auth substitute for the upload interface is a design flaw.
  - Reference: CWE-602 (Client-Side Enforcement of Server-Side Security).
  - source: run-observation (<run>)
- Anchor: uploaded-file access signature is session-bound (impact boundary, not an extra vuln)
  - Affected: the returned `preview4Pub`/`download4Pub` carry an `ours_as` signature parameter.
  - Mechanism: the signature is bound to the upload-time session, so external direct access needs the same session cookie.
    This bounds "unauthorized write" as holding but "arbitrary public read" as limited — it does not change the upload
    vuln itself holding.
  - Reference: impact-boundary note (CWE-434 still holds).
  - source: run-observation (<run>)

## Verification Principle (existence proof)

- Existence proof (read-only layer): an anonymous POST to the upload handler returns a business-level
  parameter-validation response (not 302/401), and an anonymous GET to the captcha-challenge interface returns challenge
  parameters — the two together are the existence proof of "missing authentication". A control group (other business
  interfaces returning anonymous 302 → login) rules out an "overall auth-free" misjudgment.
- Existence proof (landing layer, needs platform/operator authorization): after completing the captcha in a real browser
  environment, upload a **harmless plain-text file** (randomly named, no executable content); the server returning a file
  id/URL proves unauthorized write holds. Register and clean up afterward (guard UploadRegistry / leave no residue).
- Hard stops: stop once unauthorized write is proven. Do **not** upload a parseable script/webshell, do not leave any
  control code, do not pull others' data, do not damage. The landing proof is limited to a harmless file and goes through
  the cleanup gate — beyond that hits the hard boundary.

## False-Positive / Confounders

- The upload handler returning `参数缺失: verifyCode` or Spring's `RequestFacade cannot be cast to ... MultipartRequest`
  (two shapes across versions) both mean "auth was penetrated through to the business layer" — a positive signal, not an
  error page.
- Passing only Part-A (A1+A2) is just "suspected", not confirmable; a successful landing upload + readable content is
  needed for `certainty >= 0.8`. In the run, 90% of Part-A positives were uploadable on Part-B verification.
- The vendor marketing site (e.g. `www.x-dhr.com`) may pass A2 but be blocked on A1 — it is a website, not a product
  deployment instance, and is not counted as an affected instance.
- For an HTTPS instance whose cert CN does not match the IP (shared hosting), read-only probing must ignore cert
  validation, otherwise it is misjudged as unreachable (the run once under-reported 3 HTTPS targets this way).

## References

- CWE-434: Unrestricted Upload of File with Dangerous Type.
- CWE-306: Missing Authentication for Critical Function.
- CWE-602: Client-Side Enforcement of Server-Side Security.
- Vendor: 北京致远互联软件股份有限公司 (科创板 688369), product site x-dhr.com.
- Per-target: before submission, verify the affected entity's attribution via ICP / cyberspace-mapping; a generic-type
  submission needs ≥3 internet instances as corroboration (CNVD generic-vuln requirement).
- This workspace's reproduction material: `runs/<run>/` (PoC, evidence, batch results — not in the knowledge base).
