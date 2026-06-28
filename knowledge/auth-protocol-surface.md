---
id: auth-protocol-surface
product: Authentication and SSO protocol endpoint recognition
vendor: cross-product
aliases: [OAuth, SAML, CAS, JWT, LDAP, SSO, 统一认证, 单点登录]
category: weakness-recognition
last_reviewed: 2026-06-28
maturity: seed
signatures: ["/idp/shibboleth", "/cas/", "/oauth2/", "/.well-known/openid-configuration", "/SAML2/", "/adfs/"]
---

<!--
PUBLIC grounding tier. Generic recognition of authentication protocol
endpoints — SAML, OAuth2/OIDC, CAS, JWT, LDAP injection. Source: 4 SAML
runs (sxtbu×2, ujs, nuist), CAS in multiple EDU runs, OAuth2 in sxtbu cx AI.
-->

## Recognition (identification only)

### SAML
- Signature: `/idp/shibboleth` → Shibboleth IdP SAML metadata.
- Signature: `/idp/profile/SAML2/Redirect/SSO`, `/idp/profile/SAML2/POST/SSO`,
  `/idp/profile/SAML2/POST/SLO`, `/idp/profile/SAML2/SOAP/ECP` — SAML SSO
  endpoints. `/idp/status` — operational status.
- Signature: `/adfs/ls/`, `/adfs/services/trust` — ADFS (Microsoft).
- Signature: `/simplesaml/`, `/saml/`, `/sso/saml` — SimpleSAMLphp / generic.

### OAuth2 / OpenID Connect
- Signature: `/.well-known/openid-configuration` → OIDC discovery document.
- Signature: `/oauth2/authorize`, `/oauth2/token`, `/oauth2/revoke` —
  standard OAuth2 endpoints. `/connect/authorize`, `/connect/token` —
  IdentityServer4.
- Signature: `/auth/realms/<name>` → Keycloak.
- Signature: `grant_type=password` in login requests → OAuth2 resource owner
  password grant (sxtbu cx AI pattern).

### CAS (Central Authentication Service — common in China EDU)
- Signature: `/cas/login`, `/cas/logout`, `/cas/serviceValidate`,
  `/cas/proxyValidate` — Apereo CAS.
- Signature: `/authserver/` — Wisedu CAS (China EDU common).
- Signature: `/lyuapServer/`, `/zftal-uaa/` — custom China EDU SSO gateways.

### JWT
- Signature: `Authorization: Bearer eyJ...` — JWT in request/response headers.
- Signature: `access_token=` in URL fragment or response body.
- Signature: `/.well-known/jwks.json` — JWKS key set (public key for JWT
  verification).

### LDAP injection surface
- Signature: login form with username field that accepts `*`, `()`, `\` as
  valid characters (LDAP filter syntax). Error messages containing
  "javax.naming" or "LDAPSearch" or "Bad search filter".

- Distinguishing notes: SAML endpoints are XML/SOAP-based, OAuth2 are
  JSON/REST, CAS is a mix. The `/idp/` path family + Shibboleth metadata
  uniquely identifies Shibboleth (see [[shibboleth-idp]]). CAS `/cas/login`
  returning a login form challenges is normal — the attack surface is in
  the ticket validation chain, not the login page.

## Weak-Point Anchors

- Anchor: SAML WantAuthnRequestsSigned=false → unsigned assertion acceptance
  - Affected: SAML IdP/SP with signature verification disabled.
  - Mechanism: if the SP does not require signed AuthnRequests, an attacker
    can craft assertions; combined with XML signature wrapping (XSW) this
    enables identity forging. Check the IdP metadata for `WantAuthnRequestsSigned`.
  - Reference: CWE-347; SAML security advisories
  - source: external-cited
- Anchor: OAuth2 redirect_uri validation bypass
  - Affected: OAuth2 authorization servers with loose redirect_uri matching.
  - Mechanism: open redirect in the OAuth flow allows authorization code
    theft; pattern-based matching (`startswith`, `contains`) is weaker than
    exact matching. Test with `redirect_uri=https://target.com.evil.com/cb`.
  - Reference: CWE-601; OAuth 2.0 Security Best Current Practice (RFC 6819)
  - source: external-cited
- Anchor: CAS ticket reuse / proxy ticket abuse
  - Affected: CAS deployments where service tickets are not single-use.
  - Mechanism: a captured ST (service ticket) replayed to `/serviceValidate`
    returns a fresh PGT (proxy-granting ticket) if the ticket is not consumed.
  - Reference: CAS protocol security considerations
  - source: driver-reasoning
- Anchor: JWT alg=none / weak HMAC key
  - Affected: JWT libraries that accept `"alg":"none"` or use weak HMAC secrets.
  - Mechanism: changing the JWT header to `alg: none` bypasses signature
    verification; a weak HMAC secret (e.g., `secret`, app name, empty string)
    can be brute-forced.
  - Reference: CWE-347; JWT attack class
  - source: external-cited
- Anchor: LDAP injection in login form
  - Affected: login forms that construct LDAP filters from user input without
    escaping `*()\&|`.
  - Mechanism: `*` wildcard + boolean logic in username field → authentication
    bypass; `)(|(uid=*))` style injection. The tell is LDAP-specific error
    messages or timing.
  - Reference: CWE-90; OWASP LDAP Injection
  - source: external-cited

## Verification Principle

- Existence proof: confirm the endpoint is live and the protocol is correct
  (metadata XML valid / OIDC discovery JSON valid). For injection classes:
  a harmless probe payload triggers a protocol-level error (not a generic
  500). Classify as: endpoint present + protocol confirmed + access control
  tested (is the endpoint supposed to be public?).
- Hard stops: do NOT authenticate — protocol fingerprinting and access-
  control checking only. For injection classes, use harmless probes (extra
  `*` in username to check for LDAP error). Do NOT craft forged SAML
  assertions or JWT tokens autonomously (that is authorization bypass —
  proof-level but needs operator awareness).

## False-Positive / Confounders

- `/idp/shibboleth` returning 404 = not Shibboleth, or path rewritten.
- OAuth2 `/authorize` returning 302 to login is normal, not a finding.
- CAS `/login` redirecting to a different domain = federated CAS, not
  necessarily a vuln.
- JWT tokens are stateless by design — their presence in browser storage
  is not a vulnerability per se; the finding is in weak verification.
- SAML metadata is SUPPOSED to be public (it's the IdP's public descriptor);
  only example/unreplaced metadata is a config-hygiene issue (LOW).

## References

- SAML: https://shibboleth.net/community/advisories/
- OAuth2: RFC 6819 (OAuth 2.0 Threat Model)
- OWASP: LDAP Injection, JWT Attack Cheat Sheet
- This repo's run-observation: sxtbu (Shibboleth IdP SAML assessment ×2 +
  OAuth2 password grant), ujs (IdP metadata + CAS), nuist (CAS/Wisedu)
- Related: [[shibboleth-idp]] [[wisedu-ecampus]]
