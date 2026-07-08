---
id: soarcloud-ais-hr
product: 飛騰雲端 AIS 人資系統 (Soar Cloud AIS HR) + eServices portal
vendor: 飛騰雲端系統股份有限公司 (Soar Cloud System CO., LTD.)
aliases: [AIS, SoarCloud HR, 飛騰雲端, scshr, eServices]
category: saas-hr
last_reviewed: 2026-07-09
maturity: seed
signatures: ["ais.webform.js", "__logincompanyid", "伺服端資訊", "eservices.styles.css"]
---

<!--
PUBLIC grounding tier. Recognition + weak-point anchors + proof principles only.
No payloads/PoC. Seeded from a real run (see runs/<run>/ in workspace, not here).
-->

## Recognition (identification only)

- Two distinct stacks under one vendor:
  - **AIS core (backend service endpoints):** ASP.NET WebForms + DevExpress. Markers:
    `<title>伺服端資訊</title>` or `錯誤訊息` at host root; hidden fields
    `__LOGINCOMPANYID`, `__UNIQUEGUID`, `__ROOTPATH`, `__VALUECHANGEID`; assets
    `/Scripts/ais.webform.js`, `/css/base.css?v=<Version>`, DevExpress `/DXR.axd`,
    `/WebResource.axd`. Subdomains seen: api/app/client/cloud/services/schedule/ai.
  - **eServices portal (human login):** ASP.NET Core Razor Pages + Identity. Markers:
    `<title>Log in - eServices</title>`, scoped CSS `eServices.styles.css`, cookies
    `Identity.External` / `.AspNetCore.Antiforgery.*` (`CfDJ8…` tokens), fields
    `Input.Email`/`Input.Password`/`Input.CustomerID`. Often on a high non-standard port
    on on-prem IIS hosts, not the Azure SaaS subdomains.
- Server-info page (`伺服端資訊`) dumps Version (e.g. 7.3.YYYY.MMDD), APPVersion, MachineName,
  Environment (Azure), Mode (Rent = multi-tenant), DeploymentDate, sometimes RunTimeLogActions /
  DbCommand* / ProgramItems. Acts as an unauth version oracle.
- DevExpress `DXR.axd` can return 304/conditional-cache-shaped responses on otherwise
  reachable hosts. Treat that as a component/routing signal to correlate with saved
  headers and other ASP.NET assets, not as proof that the endpoint is empty.
- Distinguishing notes: per-tenant builds can diverge by years (oracle gives exact build).
  Do not confuse the WebForms backend subdomains (machine-to-machine) with the eServices
  human login.

## Weak-Point Anchors (variant-analysis input — NOT exploit steps)

- Anchor: unauthenticated diagnostic/server-info endpoint exposure
  - Affected: AIS WebForms hosts where the root serves `伺服端資訊`/verbose dump
  - Mechanism: a diagnostics page is reachable pre-auth, leaking build/host/log/deployment
    metadata usable to fingerprint exact version and target n-day windows.
  - Reference: CWE-200 (information exposure) — class anchor, no public CVE for this product
  - source: run-observation
- Anchor: exposed product SDK/API reference documentation
  - Affected: AIS API host with `/api/help` → `/api/help/html/N_AIS_Define.htm` (Sandcastle)
  - Mechanism: full server-side customization/event model (Before/After Add/Edit/Delete/
    Approve/Save/ProcessExecute/ExecReport) published unauth → maps internal attack surface.
  - Reference: CWE-200
  - source: run-observation
- Anchor: open self-registration with unvalidated tenant binding (ASP.NET Core Identity)
  - Affected: eServices portals exposing `/Identity/Account/Register`
  - Mechanism: scaffolded Identity Register left enabled; `CustomerID` (tenant code) accepted
    as unvalidated free text and weak password policy (min 6) → arbitrary outsiders create
    accounts; account usability typically gated by `RequireConfirmedAccount` (email confirm).
  - Reference: CWE-1392 / CWE-862 (improper/ missing authorization on registration)
  - source: run-observation
- Anchor: ASP.NET WebForms ViewState deserialization (conditional)
  - Affected: WebForms postback pages where machineKey is static/shared across a multi-tenant
    single-codebase deployment or MAC validation is weak
  - Mechanism: forgeable `__VIEWSTATE` → .NET deserialization → RCE if the signing key is
    known/recoverable. Requires a key signal before it is more than a hypothesis.
  - Reference: CWE-502; ASP.NET ViewState deserialization advisories
  - source: driver-reasoning
- Anchor: 2025 ZUSO ART / NVD HRD CVE cluster
  - Affected: HRD Human Resource Management System through version 7.3.2025.0408.
    Live version strings above that range should still receive at least one safe
    function-level control before closure; version alone is not a refutation.
  - CVE-2025-5192 / ZA-2025-04: missing authentication in the client application.
  - CVE-2025-48780 / ZA-2025-05: deserialization in the download-file function.
  - CVE-2025-48781 / ZA-2025-06: externally controlled path in the download-file
    function, partial arbitrary file read.
  - CVE-2025-48782 / ZA-2025-07: unrestricted upload of dangerous file type in
    the upload-file function.
  - CVE-2025-48783 / ZA-2025-08: externally controlled path in the delete-file
    function. This is destructive; do not auto-execute delete proofs.
  - CVE-2025-48784 / ZA-2025-09: missing authorization allowing system-setting
    modification. Treat setting changes as operator-gated state changes.
  - References: ZUSO ART advisories ZA-2025-04..09; NVD CVE-2025-5192,
    CVE-2025-48780..48784.
  - source: public-advisory

## Verification Principle (existence proof)

- Server-info: GET root unauth, confirm `伺服端資訊` markers + a fresh `ASP.NET_SessionId`
  (no auth sent). Presence is the proof; do not mine for secrets beyond identification.
- CVE lookup: once a live page yields product+version, run the current web-research
  protocol in the same cycle and record the CVE range comparison before closing
  or assigning severity.
- File-function probes: record the request shape separately from the security
  conclusion. For JSON APIs that wrap an inner object as a string `Value`, use
  `probe.py --value-json` or `--value-json-file` so the inner JSON is escaped
  consistently. Exercise a path-format matrix before concluding a function is
  absent: benign relative name, traversal-shaped relative path, absolute Windows
  path, and an expected-deny control. An error changing from null-reference to
  access-denied is evidence that the function exists but is blocked by filesystem
  permissions, not evidence that the function is absent.
- Open registration: prove with a controlled differential — a second register of the SAME
  throwaway email returns `Username '…' is already taken.`, attributing creation to the prior
  matched-password POST. One throwaway account only; do NOT access tenant data after.
- Hard stops: confirm identity/capability only. No tenant-data pull, no database dump, no tampering,
  no second-order use of created accounts beyond proving existence. Clean up created artifacts
  (flag the account for operator deletion).

## False-Positive / Confounders

- Soft-200 error page (`錯誤訊息`, ~650 bytes) and the login page (~7 KB) are returned for many
  unmatched routes — treat consistent-length 200s as not-found, not real endpoints (generic 404
  here is a tiny ~103-byte body).
- eServices uses generic auth/forgot-password failure messages → absence of enumeration is
  expected, not evidence of a fix elsewhere.
- A bogus `CustomerID` being accepted means it is unvalidated free text, NOT proof of cross-tenant
  access; cross-tenant impact requires a valid tenant code + confirmation and must be proven.

## References

- CWE-200, CWE-502, CWE-862, CWE-1392 (class anchors)
- Vendor: https://www.scshr.com/ (product/changelog: /news/scschangelog/)
