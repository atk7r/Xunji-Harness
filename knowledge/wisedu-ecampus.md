---
id: wisedu-ecampus
product: 金智教育 数字校园 (unified auth authserver / online service hall ehall)
vendor: 江苏金智教育 Wisedu
aliases: [金智教育, wisedu, ehall, authserver, 网上办事大厅, 今日校园, 统一身份认证]
category: framework-management-endpoint
last_reviewed: 2026-06-12
maturity: seed
signatures: ["/qljfwapp/", "checkneedcaptcha.htl", "schoolcombinedlogin.js", "/publicapp/"]
---

<!--
Grounding knowledge, not a weapon. Source: <run> run-observation +
public disclosure (external-cited). No payloads / steps / PoC.
-->

## Recognition (identification only)

- Signature: response header `Server: wisedu` (a strong fingerprint of the Wisedu application server).
- Signature: unified auth at `/authserver/`: `/authserver/login` login page (class `root-main`), static resources
  at `/authserver/<school-custom-Theme>/static/...?v=<date version>` (e.g. `<engagement>Theme v=20240524`),
  containing `encrypt.js` (password encryption) / `login.js` / `fido.js` / `schoolCombinedLogin.js`.
- Signature: the ehall service-app namespaces `/qljfwapp/<app>/sys/...`, `/publicapp/...`;
  `/authserver/checkNeedCaptcha.htl?username=` returns `{"isNeed":..}`, `/authserver/getCaptcha.htl` returns an image captcha.
- Distinguishing notes: what separates it from other CAS (apereo native, other IdPs) is `Server: wisedu` +
  the `/authserver/<Theme>/static/` custom theme + the ehall `qljfwapp`/`publicapp` service-app structure.

## Weak-Point Anchors (variant-analysis input — NOT exploit steps)

- Anchor: ehall service-app unauthenticated SQLi / authz-bypass flaw classes
  - Affected: some `/qljfwapp/*/sys/*` service interfaces in specific versions lack enforced authz or object-level authz
  - Mechanism: many service-app modules, incomplete authz-filter coverage; historical disclosures cluster around
    `/sys/...Controller/...`-type interfaces
  - Reference: CNVD search "金智教育 / ehall" https://www.cnvd.org.cn/
  - source: external-cited
- Anchor: authserver (CAS) authentication-logic / arbitrary-user-login flaw classes
  - Affected: older authserver versions
  - Mechanism: password RSA encryption + CAS ticket flow; historically had encryption-bypass / arbitrary-login classes
  - Reference: CNVD/CNNVD Wisedu authserver entries
  - source: external-cited
- Anchor: service-app enumeration depends on the post-authorization app list
  - Affected: un-logged-in `/qljfwapp/sys/` → CAS login, app names not directly enumerable
  - Mechanism: the unauth surface is limited, most services need a login state; testing authz-bypass/injection usually
    needs a test account or the exact app/module name
  - Reference: this repo's run-observation (an engagement's ehall)
  - source: run-observation

## Verification Principle (existence proof)

- Existence proof: `Server: wisedu` + `/authserver/login` + ehall `/qljfwapp/` confirms the product.
  Take the version from the `/authserver/<Theme>/static/...?v=` timestamp, for matching known flaws.
- Hard stops: the unauth surface stops at fingerprint/version; service-app authz-bypass/injection proof needs an
  account or exact app name, a proof-level boolean differential, no database dump; do not do account-enumeration-style
  high-frequency requests against checkNeedCaptcha.

## False-Positive / Confounders

- Multiple hosts behind `Server: wisedu` are CAS login pages (jxpg/jsfzzx/kyc, etc.) — they are the same login entry,
  not independent apps; do not lump-count them as multiple surfaces.
- `checkNeedCaptcha` may return the same `isNeed` for existing/non-existing users (no user enumeration); do not infer
  an enumeration vuln from it.

## References

- https://www.cnvd.org.cn/ (search "金智教育 / ehall / authserver")
- This repo's run-observation: runs/<run>/ evidence E-002/E-004/E-008 (a real host authserver/ehall)
