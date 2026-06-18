---
id: zfsoft-jwgl
product: 正方教务管理系统 (ZFSoft jwglxt)
vendor: 正方软件 ZFSoft
aliases: [正方教务, jwglxt, 教学管理信息服务平台, 正方新版教务]
category: framework-management-endpoint
last_reviewed: 2026-06-12
maturity: seed
signatures: ["/jwglxt/", "login_slogin.html", "login_getpublickey.html", "教学管理信息服务平台"]
---

<!--
Grounding knowledge, not a weapon. Source: <run> run-observation +
public disclosure (external-cited). No payloads / steps / PoC.
-->

## Recognition (identification only)

- Signature: path `/jwglxt/`; the homepage often meta-refreshes to `/jwglxt`, login page
  `xtgl/login_slogin.html`, title "教学管理信息服务平台".
- Signature: login uses RSA, the public-key endpoint `xtgl/login_getPublicKey.html` returns `{"modulus","exponent"}`.
- Signature: static resources carry a `?ver=<build>` build number (e.g. `jw-login.css?ver=29564678`), class prefixes
  `globalweb` / `jw-`; the cookie has `JSESSIONID` + `route` (cluster routing).
- Distinguishing notes: it is commonly confused with Qiangzhi jwmis (path `/jsxsd/`); the new ZFSoft is told apart by
  `/jwglxt/` + `login_slogin.html` + `login_getPublicKey.html`.

## Weak-Point Anchors (variant-analysis input — NOT exploit steps)

- Anchor: SQL injection flaw class
  - Affected: specific interfaces across many historical builds (including some unauth points, varying by version)
  - Mechanism: older versions have an injection surface where params are concatenated into SQL; newer builds are mostly
    fixed — verify by matching the `?ver=` build
  - Reference: CNVD search "正方 教务" https://www.cnvd.org.cn/ ; specific IDs vary by build
  - source: external-cited
- Anchor: unauthenticated access / authz-bypass flaw class
  - Affected: some interfaces in specific versions lack enforced authz or allow reading others' data
  - Mechanism: incomplete authz-filter coverage / missing object-level permission check
  - Reference: CNVD/CNNVD ZFSoft jwgl entry search
  - source: external-cited
- Anchor: weak-credential / default-account surface
  - Affected: the student/teacher account system
  - Mechanism: common pattern of student-id/staff-id as username and weak default passwords; this is a
    credential-trying surface, not a direct unauth hit
  - Reference: general account-security practice (the driver decides whether to proceed per authorization and platform rules)
  - source: driver-reasoning

## Verification Principle (existence proof)

- Existence proof: `/jwglxt/` + `login_slogin.html` + `login_getPublicKey.html` confirms the product and login flow;
  `?ver=` gives the build, for matching known flaws. Whether a data interface redirects un-logged-in back to login
  distinguishes whether authz is enforced.
- Hard stops: injection proof stops at boolean/differential evidence (no database dump); authz-bypass proof stops at
  "another user's object is reachable" rather than bulk data pull; weak-credential testing must follow authorization and
  the platform's harmless rules, auto-execution stays controlled (avoid brute-force lockout).

## False-Positive / Confounders

- A front WAF (e.g. Anheng cloud) returns a block page for quotes/keywords; **a block page ≠ a DB error**, do not judge
  injection from it (see [[waf-block-recognition]]).
- The `route`/`JSESSIONID` dual cookie is normal cluster session affinity, not a vuln signal.

## References

- https://www.cnvd.org.cn/ (search "正方 教务 / jwglxt")
- This repo's run-observation: runs/<run>/ evidence E-001/E-002 (a real host, build 29564678)
