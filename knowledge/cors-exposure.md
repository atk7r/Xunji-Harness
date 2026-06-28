---
id: cors-exposure
product: Cross-Origin Resource Sharing misconfiguration recognition
vendor: cross-product
aliases: [CORS, cross-origin, Access-Control, 跨域配置, ACAO]
category: weakness-recognition
last_reviewed: 2026-06-28
maturity: seed
signatures: ["access-control-allow-origin", "access-control-allow-credentials", "access-control-allow-methods", "acaorigin"]
---

<!--
PUBLIC grounding tier. Generic recognition of CORS misconfiguration patterns —
cross-product. Source: jou run-observation (CORS * with credential cookies +
CSP allowing localhost), multiple EDU runs.
-->

## Recognition (identification only)

- Signature (universal wildcard): `Access-Control-Allow-Origin: *` on a response
  that also carries `Set-Cookie` or `Authorization` headers.
- Signature (reflected origin): `Access-Control-Allow-Origin` echoes the request's
  `Origin` header value without validation (wildcard reflection).
- Signature (credentials with wildcard): `Access-Control-Allow-Credentials: true`
  combined with a reflected or wildcard `Access-Control-Allow-Origin`.
- Signature (dangerous methods): `Access-Control-Allow-Methods: PUT, DELETE`
  or `*` on preflight responses from unauthenticated endpoints.
- Signature (null origin allowed): server accepts `Origin: null` (from sandboxed
  iframes, file:// URLs, data: URLs) with credentials.
- Distinguishing notes: CORS headers alone are not a vulnerability — they exist
  to ENABLE cross-origin access. The finding is in the COMBINATION: wildcard
  origin + credentials, or reflected origin + sensitive data endpoint.

## Weak-Point Anchors

- Anchor: `ACAO: *` with credentials → cross-origin data theft
  - Affected: endpoints that return sensitive data (user info, tokens, API responses)
    with both `ACAO: *` and `ACAC: true`.
  - Mechanism: any malicious page on any origin can make a credentialed fetch
    to the endpoint and read the response; the user's browser session is exploited
    to exfiltrate their own data.
  - Reference: CWE-942 (Permissive Cross-domain Policy with Untrusted Domains)
  - source: external-cited
- Anchor: reflected Origin with credentials → arbitrary-origin data access
  - Affected: endpoints that copy the request `Origin` header into `ACAO` without
    a whitelist, while also setting `ACAC: true`.
  - Mechanism: the attacker hosts a page on any origin; the browser sends that
    origin in the CORS request, the server reflects it back, and the attacker
    reads the authenticated response. Same impact as wildcard but harder to detect
    (looks like per-origin to the server).
  - Reference: CWE-942
  - source: external-cited
- Anchor: CORS on authentication endpoints → token exfiltration
  - Affected: login/token endpoints that return session tokens or JWTs in the
    response body with permissive CORS headers.
  - Mechanism: a phishing page triggers a CORS request to the real login endpoint;
    if the user is already authenticated, the response (with token) is readable
    by the attacker page. Pre-flight bypass via simple request methods.
  - Reference: CWE-942
  - source: driver-reasoning

## Verification Principle

- Existence proof: send an OPTIONS preflight with a non-whitelisted Origin and
  observe whether `Access-Control-Allow-Origin` in the response reflects that
  origin. Then send a real GET with the same Origin to confirm the reflection.
  The endpoint URL + response headers are the artifact.
- Hard stops: confirm the CORS misconfiguration exists. Do NOT host a malicious
  page to prove data exfiltration — the header combination alone is the finding.
  Do not extract real user data via CORS.

## False-Positive / Confounders

- `ACAO: *` on a public API with no authentication is by-design (CDN, public
  assets) — CORS is intended for this use case. Only flag when combined with
  credentials or sensitive data.
- Some apps use a dynamic CORS filter that only reflects whitelisted origins;
  test with multiple origins (own domain, subdomain, unrelated domain) to
  distinguish whitelist from reflection.
- Preflight responses may show broader permissions than actual requests; always
  confirm with a real (non-OPTIONS) request.

## References

- CWE-942: https://cwe.mitre.org/data/definitions/942.html (Permissive Cross-domain Policy)
- OWASP: https://owasp.org/www-project-web-security-testing-guide/stable/4-Web_Application_Security_Testing/11-Client-side_Testing/07-Testing_Cross_Origin_Resource_Sharing
- Fetch Standard: CORS protocol (https://fetch.spec.whatwg.org/#http-cors-protocol)
- This repo's run-observation: jou (CORS * with credential cookies)
- Related: [[security-header-weaknesses]] [[auth-protocol-surface]]
