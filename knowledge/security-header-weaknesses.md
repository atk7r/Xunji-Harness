---
id: security-header-weaknesses
product: Security header and cookie attribute weakness recognition
vendor: cross-product
aliases: [missing headers, XFO, CSP, HSTS, HttpOnly, Secure cookie, 安全头缺失, cookie安全]
category: weakness-recognition
last_reviewed: 2026-06-28
maturity: seed
signatures: ["x-frame-options: deny", "content-security-policy: default-src", "strict-transport-security: max-age", "set-cookie: .*httponly", "set-cookie: .*secure"]
---

<!--
PUBLIC grounding tier. Generic recognition of missing or weak security headers
and cookie attributes — cross-product. Source: DVWA run-observation (missing XFO/CSP/
HSTS, cookie no HttpOnly/Secure), mokwon run (session_regenerate_id not enforced).
-->

## Recognition (identification only)

- Signature (missing clickjacking protection): response lacks `X-Frame-Options`
  or `Content-Security-Policy` with `frame-ancestors` directive.
- Signature (missing CSP): response lacks `Content-Security-Policy` header
  entirely, or CSP contains `unsafe-inline` / `unsafe-eval` without nonce/hash.
- Signature (missing HSTS): response on HTTPS lacks `Strict-Transport-Security`
  header, or `max-age` is very short (< 1 year).
- Signature (cookie security): `Set-Cookie` lacks `HttpOnly` (accessible to JS →
  XSS exfiltration), lacks `Secure` (sent over HTTP), lacks `SameSite` (CSRF
  protection absent). Multiple cookies with same name but different paths.
- Signature (session fixation risk): session ID does not change after login
  (same `Set-Cookie` value pre and post auth). `session_regenerate_id` not
  enforced in PHP apps.
- Distinguished notes: these are config-hygiene signals, not direct
  vulnerabilities. Missing HSTS on a plain-HTTP site is not applicable. A site
  with no user login may not need HttpOnly cookies. Judge per context.

## Weak-Point Anchors

- Anchor: missing HttpOnly on session cookie enables XSS-based session theft
  - Affected: any site with reflected/stored XSS and a session cookie without
    HttpOnly flag.
  - Mechanism: an XSS payload can execute `document.cookie` and exfiltrate the
    session token to an attacker-controlled endpoint.
  - Reference: CWE-1004 (Sensitive Cookie Without 'HttpOnly' Flag)
  - source: external-cited
- Anchor: missing SameSite enables CSRF
  - Affected: state-changing endpoints (POST/PUT/DELETE) without CSRF tokens,
    and session cookie without `SameSite=Lax` or `Strict`.
  - Mechanism: browser automatically attaches the session cookie to cross-site
    requests, enabling CSRF attacks on state-changing endpoints.
  - Reference: CWE-1275 (Sensitive Cookie with Improper SameSite Attribute)
  - source: external-cited
- Anchor: HSTS missing on HTTPS site → MITM downgrade risk
  - Affected: HTTPS sites without HSTS header.
  - Mechanism: an active MITM can strip HTTPS and serve HTTP, intercepting
    traffic; HSTS with `max-age` and `includeSubDomains` prevents this.
  - Reference: CWE-319 (Cleartext Transmission of Sensitive Information)
  - source: external-cited
- Anchor: CSP with unsafe-inline → XSS protection weakened
  - Affected: sites that deploy CSP but include `unsafe-inline` for scripts
    without nonce or hash-based whitelisting.
  - Mechanism: inline scripts are the most common XSS vector; `unsafe-inline`
    neutralizes CSP's primary defense against them.
  - Reference: OWASP: Content Security Policy
  - source: external-cited

## Verification Principle

- Existence proof: a single benign GET → examine response headers. Absence of
  a header is a config-hygiene signal (LOW at most). The finding is informational
  unless combined with a demonstrated exploit (XSS + cookie theft, CSRF + state
  change).
- Hard stops: header checking is read-only reconnaissance. Do not attempt MITM
  or XSS exploitation to prove the impact — the finding is the missing
  protection layer.

## False-Positive / Confounders

- Some security headers (CSP, HSTS) may be set by a CDN/WAF upstream, not
  visible in the origin response. Check both with and without CDN bypass.
- A site serving only static content may legitimately have minimal headers.
- `X-Frame-Options: DENY` on a single page is not site-wide protection.
- SameSite=Lax is the browser default in modern browsers even without the
  header — check the actual browser behavior.

## References

- OWASP Secure Headers Project: https://owasp.org/www-project-secure-headers/
- CWE-1004: https://cwe.mitre.org/data/definitions/1004.html (Sensitive Cookie Without 'HttpOnly' Flag)
- CWE-1275: https://cwe.mitre.org/data/definitions/1275.html (Sensitive Cookie with Improper SameSite Attribute)
- This repo's run-observation: DVWA (missing XFO/CSP/HSTS, cookie flags);
  mokwon (session not regenerated after login)
- Related: [[error-disclosure-signatures]] [[tech-stack-fingerprint]]
