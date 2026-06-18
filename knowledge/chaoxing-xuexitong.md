---
id: chaoxing-xuexitong
product: 超星学习通 / 泛雅 (Chaoxing)
vendor: 超星 Chaoxing
aliases: [超星, 学习通, 泛雅, chaoxing, fanya, AI平台]
category: framework-management-endpoint
last_reviewed: 2026-06-12
maturity: seed
signatures: ["passport2.chaoxing.com", "sentry-stats.chaoxing.com", "captcha.chaoxing.com"]
---

<!--
Grounding knowledge, not a weapon. Source: <run> run-observation +
public disclosure (external-cited). No payloads / steps / PoC.
-->

## Recognition (identification only)

- Signature: login redirects to the third-party unified auth `passport2.chaoxing.com` (referer back to the business domain).
- Signature: same-domain backend REST prefix `/v1/...` (e.g. `/v1/user/...`, `/v1/manage/...`); when not logged in
  it usually returns HTTP 200 but with body `{"msg":"未登录","statusCode":-1}`.
- Signature: front-end Vue SPA; telemetry to `sentry-stats.chaoxing.com`; captcha `captcha.chaoxing.com`.
- Distinguishing notes: the business subdomain (a school's AI platform / 学习通) is the deployment point, while the
  unified-auth passport lives on the vendor domain `chaoxing.com`; the two have different scope ownership.

## Weak-Point Anchors (variant-analysis input — NOT exploit steps)

- Anchor: component-level known-flaw classes (authz bypass / SSRF / info disclosure — historical disclosures)
  - Affected: affected Chaoxing component versions
  - Mechanism: a large multi-tenant platform has historically had publicly-disclosed authz-bypass data reads,
    server-side request forgery, etc.; these are in the vendor's code surface, specifics vary by version
  - Reference: CNVD search "超星 / 学习通" https://www.cnvd.org.cn/
  - source: external-cited
- Anchor: API authorization boundary (this run found it enforced at the application layer)
  - Affected: management namespaces such as `/v1/manage/*`
  - Mechanism: the interface returns HTTP 200 but checks login state at the application layer (`{"msg":"未登录"}`);
    do NOT mistake 200 for "unauthenticated-accessible" — read the body semantics
  - Reference: this repo's run-observation
  - source: run-observation

## Verification Principle (existence proof)

- Existence proof: a passport.chaoxing.com redirect + the `/v1/` API shape confirms the product. Judge
  authorization **by body semantics** (200 + "未登录" = authenticated), not by the HTTP status code.
- Hard stops: authz-bypass / info-disclosure proof stops at "the existence of an object/data item that should not
  be reachable"; no bulk data pull; login is on the vendor passport domain, mind the scope boundary.

## False-Positive / Confounders

- **HTTP 200 ≠ unauthenticated access**: Chaoxing interfaces habitually wrap business error codes in 200, and an
  un-logged-in request also returns 200. This was a refuted direction this run (see runs/<run> evidence E-003).
- passport is on the `chaoxing.com` domain, which may exceed the authorization scope of a single school.

## References

- https://www.cnvd.org.cn/ (search "超星 / 学习通")
- This repo's run-observation: runs/<run>/ evidence E-003 (a real host)
