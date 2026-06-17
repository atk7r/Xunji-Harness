---
id: simmagic-reg
product: SimMAGIC Reg 註冊管理 (SimMAGIC / MAGIC VR licensing portal)
vendor: 哈瑪星科技股份有限公司 (Hamastar Technology)
aliases: [SimMAGIC, MAGICVR, SimMAGIC Reg, Reg Manager]
category: saas-licensing
last_reviewed: 2026-06-17
maturity: seed
signatures: ["simmagic reg", "/reghome/", "simmagic註冊管理", "magicvr"]
---

<!--
PUBLIC grounding tier. Recognition + weak-point anchors + proof principles only.
No payloads/PoC. Seeded from a real run (see runs/<run>/ in workspace, not here).
Product signatures are public; specific customer/license data is NOT reproduced here.
-->

## Recognition (identification only)

- ASP.NET MVC licensing portal. Markers: login title `登入 - SimMAGIC Reg`; routes
  `/Account/Login` + `/Account/Register`; cookie `.AspNet.ApplicationCookie` +
  `__RequestVerificationToken`; post-login title `Reg Manager - SimMAGIC Reg` /
  heading `SimMAGIC註冊管理`; product dropdown `SimMAGIC` / `MAGIC VR`;
  Bootstrap + `jquery-3.1.1`.
- Controllers seen: `/RegHome` (Create / Edit / Index), `/User?sn=<license>`, `/Organization`.
- Distinguishing notes: unlike the vendor's WebForms CMS (`css_v4.5` prefix), this is a
  standalone MVC licensing portal — different stack, same vendor.

## Weak-Point Anchors (variant-analysis input — NOT exploit steps)

- Anchor: open self-registration (no email, no captcha, no approval)
  - Affected: instances exposing `/Account/Register`
  - Mechanism: registration takes only a username (letters/digits) + password (min 6); no
    email verification, no captcha, no admin approval → arbitrary outsiders create accounts.
  - Reference: CWE-1392 (use of insufficiently trusted input at registration) / CWE-862
  - source: run-observation
- Anchor: missing object-level authorization on licenses (IDOR)
  - Affected: authenticated users reaching `/RegHome/Edit/<serial>`
  - Mechanism: no per-user license scoping — a self-registered user can view/edit any
    organization's license addressed directly by serial number; no object-level authz check.
  - Reference: CWE-639 (IDOR) / CWE-862
  - source: run-observation
- Anchor: end-user directory sensitive-data exposure
  - Affected: `/User?sn=<license>`
  - Mechanism: any authenticated user can list end-users under a license — hardware/computer
    IDs, usernames, emails, phone numbers, job titles, first/last login times — with delete controls.
  - Reference: CWE-200 / CWE-359 (PII exposure)
  - source: run-observation
- Anchor: database schema disclosure via verbose 500
  - Affected: instances with customErrors off
  - Mechanism: invalid input triggers a foreign-key constraint 500 that leaks the database
    name, table name, constraint name and column.
  - Reference: CWE-209
  - source: run-observation
- Anchor: embedded CKEditor pinned to an old version
  - Affected: instances bundling CKEditor 4.9.1
  - Mechanism: outdated CKEditor 4.x carries known XSS / upload-filter-bypass CVEs; requires
    an authenticated editing context.
  - Reference: CVE-2018-17960, CVE-2023-28439
  - source: external-cited

## Verification Principle (existence proof)

- Open registration: register ONE throwaway account and confirm login; or use a controlled
  differential (re-register the same username → "already exists"). Flag the test account for
  operator deletion afterward.
- IDOR: while authenticated, GET `/RegHome/Edit/<another-serial>` and confirm it returns
  pre-filled license data belonging to another org. Read the edit page only — do NOT submit
  any change.
- User directory: GET `/User?sn=<license>` and confirm the sensitive columns are present.
  Do NOT export or delete user data.
- DB schema: an invalid `ORGANIZATION_ID` triggering an FK 500 with schema text is the proof;
  do NOT pursue extraction / 拖库.
- Hard stops: prove existence only — never edit/delete licenses or users, never dump, never
  leave the test account active (hand to operator for cleanup).

## False-Positive / Confounders

- A "shared management portal" might be by-design (all users manage all licenses); but combined
  with end-user PII exposure + delete controls it is still an access-control flaw. Judge by
  "can a user reach objects that are not theirs," not by the portal's intended convenience.
- The 500 schema leak is verbose-error disclosure, NOT SQL injection — do not conflate; a real
  injection must be proven separately.

## References

- CWE-1392, CWE-862, CWE-639, CWE-200, CWE-359, CWE-209 (class anchors)
- CKEditor 4.x: CVE-2018-17960, CVE-2023-28439
- Vendor: https://www.hamastar.com.tw/ (product: SimMAGIC)
