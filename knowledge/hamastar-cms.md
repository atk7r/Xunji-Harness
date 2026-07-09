---
id: hamastar-cms
product: 哈瑪星 CMS / WSP 網站共構平台 (Hamastar CMS v4.5 + WSP)
vendor: 哈瑪星科技股份有限公司 (Hamastar Technology)
aliases: [Hamastar CMS, WSP, 網站共構系統, css_v4.5, Scripts_v4.5]
category: cms
last_reviewed: 2026-06-17
maturity: seed
signatures: ["css_v4.5/", "scripts_v4.5/", "網站共構系統", "/common/checkcode.aspx", "/common/testlogin"]
---

<!--
PUBLIC grounding tier. Recognition + weak-point anchors + proof principles only.
No payloads/PoC. Seeded from a real run (see runs/<run>/ in workspace, not here).
Product/framework signatures are public; specific customer instances are NOT named here.
-->

## Recognition (identification only)

- **Admin backstage (ASP.NET WebForms):** title `…網站共構系統網站管理系統`; asset path
  prefix `css_v4.5/bg-global.css`, `css_v4.5/Mylogin.css`, `Scripts_v4.5/…`
  (the `_v4.5` suffix is the framework generation marker); hidden fields
  `__VIEWSTATE` / `__VIEWSTATEGENERATOR` / `__EVENTVALIDATION` + ScriptManager;
  login fields `txtAccount` / `txtPW` / `txtVali` with captcha `Common/CheckCode.aspx?t=<hex>`;
  the observed text captcha may be a small noisy GIF where local OCR returns empty
  across bounded PSM attempts;
  inline `var lang = {…}` multi-language JSON; fancybox + `vue.min.js` + `jquery.min.js`;
  buttons `btnApplyAccount` (apply account) / `btnForgotPasswd` / `btnICLogin` (natural-person cert);
  banner `登入錯誤 3 次後…帳號即被鎖定`.
- **MVC variant:** some management systems are ASP.NET MVC (`X-AspNetMvc-Version` header),
  fronted by a test-period password gate at `/Common/TestLogin` (`測試期通關密碼`).
- **Public customer sites (same framework):** government/enterprise sites whose images load
  from a WSP upload VIP `ws<NNNN>.<vendor-host>/001/Upload/…`.
- Distinguishing notes: `-mgr` subdomain = admin backstage; `-ws` subdomain = web service
  endpoint; no suffix = public site. Look-alike ASP.NET WebForms gov CMS differ by the
  `_v4.5` asset prefix + the `lang` JSON block.

## Weak-Point Anchors (variant-analysis input — NOT exploit steps)

- Anchor: unhandled-exception verbose error on the forgot-password page
  - Affected: deployments where the language module is uninitialized for that page
  - Mechanism: requesting `/ForgotPasswd.aspx` raises a NullReferenceException (HTTP 500);
    with customErrors off the page leaks internal class names (e.g. a localization helper)
    and source line numbers.
  - Reference: CWE-209 (verbose error) / CWE-200
  - source: run-observation
- Anchor: route-level authorization gap behind the test-period password gate
  - Affected: MVC instances with the `/Common/TestLogin` `測試期通關密碼` gate
  - Mechanism: the gate filters only a subset of routes (`/`, `/Login`, `/Common`); other
    controllers (e.g. `/Admin/*`) are not covered, so the gate is bypassable to reach the
    admin SPA shell — real data still needs a genuine login.
  - Reference: CWE-862 (missing authorization) / CWE-425 (direct request)
  - source: run-observation
- Anchor: post-login open redirect via reflected ReturnUrl
  - Affected: admin backstage login page
  - Mechanism: the `ReturnUrl` query parameter is reflected into the form `action` with no
    host allow-list; a successful login then redirects to an attacker URL.
  - Reference: CWE-601 (open redirect)
  - source: run-observation
- Anchor: ASP.NET trace/diagnostics handler reachable
  - Affected: instances with tracing enabled
  - Mechanism: `trace.axd` is installed; usually IP-restricted (403), but a misconfig can
    expose per-request traces (headers, session) pre-auth.
  - Reference: CWE-200; ASP.NET trace documentation
  - source: run-observation
- Anchor: embedded rich-text editor pinned to an old version
  - Affected: management instances bundling CKEditor (this family seen at 4.5.11 / 4.9.1)
  - Mechanism: outdated CKEditor 4.x carries known XSS / upload-filter-bypass CVEs; requires
    an authenticated editing context to reach.
  - Reference: CVE-2018-17960, CVE-2023-28439 (CKEditor 4.x)
  - source: external-cited

## Verification Principle (existence proof)

- Verbose error: GET `/ForgotPasswd.aspx`, confirm HTTP 500 + an error page containing
  internal class names / source line numbers. Presence is the proof; read it, do not mine.
- Password-gate gap: differential between `/` (small gate page) and `/Admin` (large admin
  shell) under the same gate — confirms the route-coverage hole. Do not submit changes or
  touch admin data.
- Open redirect: confirm `ReturnUrl` reflected into the form action; do not actually phish.
- Captcha barrier: if `Common/CheckCode.aspx` returns a small noisy GIF and 3-5 bounded
  OCR attempts through `tools/captcha_ocr.py` all return empty, record the OCR barrier
  and switch to server-side captcha-enforcement or post-captcha boundary evidence. Do
  not continue blind captcha guessing.
- Hard stops (confidentiality / availability / integrity): prove existence only — no data
  pull, no database dump, no tamper, no persistence. One probe per finding, proof-level.

## False-Positive / Confounders

- `/Admin/*` returning the SPA shell is NOT "admin access" — the data APIs still require a
  real login. It is a route-coverage gap, not an auth bypass; grade it as such.
- A 500 may mean the feature is simply unconfigured (e.g. forgot-password not wired up), not
  an exploitable flaw — the info-disclosure stands, RCE does not follow from it.
- OCR failure on this captcha shape is not evidence of a bypass or password weakness; it is
  a testing barrier unless the captcha answer leaks client-side or the server accepts a
  controlled post-captcha request.
- Customer sites share the framework, but each instance must be verified on its own (same
  framework ≠ same config / same patch level).

## References

- CWE-209, CWE-200, CWE-862, CWE-601, CWE-425 (class anchors)
- CKEditor 4.x: CVE-2018-17960, CVE-2023-28439
- Vendor: https://www.hamastar.com.tw/
