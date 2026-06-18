---
id: shibboleth-idp
product: Shibboleth Identity Provider (IdP)
vendor: Shibboleth Consortium
aliases: [Shibboleth IdP, SAML IdP, 统一身份认证, SSO]
category: framework-management-endpoint
last_reviewed: 2026-06-12
maturity: seed
signatures: ["/idp/shibboleth", "/idp/css/placeholder.css", "shibboleth idp"]
---

<!--
Grounding knowledge, not a weapon. Source: <run> run-observation +
public disclosure (external-cited). No payloads / steps / PoC.
-->

## Recognition (identification only)

- Signature: path `/idp/`, title/page "Shibboleth IdP"; default resources like `/idp/css/placeholder.css`.
- Signature: `/idp/shibboleth` returns SAML metadata (entityID, certificate); some deployments still ship the
  un-replaced "example metadata" (page header carries "This is example metadata only …").
- Signature: `/idp/status` returns 403 on a hardened deployment (locked); an un-hardened one exposes the running status.
- Distinguishing notes: what separates it from other SAML IdPs (SimpleSAMLphp, ADFS) is the `/idp/` path family and
  the `shibboleth` metadata endpoint.

## Weak-Point Anchors (variant-analysis input — NOT exploit steps)

- Anchor: older-version authentication / request-handling flaw classes
  - Affected: older IdP / OpenSAML / dependency-library versions
  - Mechanism: historical disclosures include auth-handling, XML-parsing (XXE), and session-handling flaw classes;
    judged by version matching
  - Reference: Shibboleth security advisories https://shibboleth.net/community/advisories/
  - source: external-cited
- Anchor: default / example metadata exposure (config hygiene, not a direct vuln)
  - Affected: deployments where `/idp/shibboleth` is still example metadata
  - Mechanism: exposes the entityID/certificate structure and a "production config not finished" signal; not directly
    exploitable on its own — it is an ops-hygiene item
  - Reference: this repo's run-observation; Shibboleth deployment docs (metadata generation guide)
  - source: run-observation
- Anchor: running-status endpoint exposure
  - Affected: deployments where `/idp/status` access is unrestricted
  - Mechanism: leaks version/runtime info, useful for version matching and intel gathering
  - Reference: Shibboleth IdP docs (status endpoint access control)
  - source: driver-reasoning

## Verification Principle (existence proof)

- Existence proof: `/idp/` + `/idp/shibboleth` metadata confirms the product; `/idp/status` 403 vs readable
  distinguishes the hardening level; the example-metadata page-header text confirms "default not replaced".
- Hard stops: stop at fingerprint/version/config-hygiene identification; do not send destructive payloads at the
  parsing layer, do not touch the auth service's availability.

## False-Positive / Confounders

- **Example-metadata exposure is not itself a vulnerability**, only a config-hygiene signal — do not inflate it to
  high severity (lesson this run, runs/<run> evidence E-004 / FP-003).
- `/idp/status` returning 403 is a positive "already hardened" signal, not a flaw.

## References

- https://shibboleth.net/community/advisories/ (official security advisories)
- This repo's run-observation: runs/<run>/ evidence E-004 (a real host)
