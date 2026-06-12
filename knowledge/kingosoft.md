---
id: kingosoft
product: KINGOSOFT 高校教务网络管理系统
vendor: 湖南青果软件有限公司 (Hunan Qinguo Software)
aliases: [kingosoft, 青果教务, 青果教务网络管理系统, 高校教务网络管理系统]
category: edu-academic-administration
last_reviewed: 2026-06-10
maturity: seed
---

<!--
Grounding knowledge, not a weapon. See knowledge/README.md.
Seed: recognition unconfirmed first-hand; one anchor has a primary CVE, one is
secondary-sourced. Promote to verified only after first-hand recognition + a
primary CNVD/CNNVD page is opened.
-->

## Recognition (identification only)

- Tentative: ASP.NET stack (`.aspx`) with paths under `/xsweb/` (e.g.
  `/xsweb/...`), MSSQL backend, product name "高校教务网络管理系统". Source is
  secondary disclosure, not a vendor doc — confirm a concrete signature
  (login-page title, copyright/footer, vendor banner) from a first-hand run and
  record it with the run/evidence id before relying on this.

## Weak-Point Anchors (variant-analysis input — NOT exploit steps)

- Anchor: Apache Struts2 S2-045 remote code execution (framework anchor)
  - Affected: KINGOSOFT deployments built on Struts2 2.3.x < 2.3.32 / 2.5.x <
    2.5.10.1 and left unpatched (advisory CNNVD-201705-1419 records an S2-045 RCE
    in this product, 2017-05).
  - Mechanism: the Struts2 Jakarta Multipart parser mishandles a crafted
    Content-Type / Content-Disposition / Content-Length header, leading to OS
    command execution (CWE-755). Variant check: confirm the product runs an
    unpatched Struts2 before treating this as live.
  - Reference: https://nvd.nist.gov/vuln/detail/CVE-2017-5638 (primary, CVSS 9.8,
    CISA KEV); https://vul.wangan.com/a/CNNVD-201705-1419 (product manifestation)
  - source: external-cited

- Anchor: SQL injection in the academic web tier (secondary-sourced lead)
  - Affected: older deployments; disclosures cite a `/xsweb/pub/temp.aspx`-style
    entry point reaching MSSQL with high (SA) privileges, reportedly across many
    universities.
  - Mechanism: insufficient input handling reaches a SQL interpreter; the path is
    a location hint, not a payload. Treat as a class anchor pending primary
    confirmation.
  - Reference: https://vulners.com/seebug/SSV:95365 ;
    https://vulners.com/seebug/SSV:95367 (Seebug/WooYun, secondary — primary
    CNVD/CNNVD page not yet opened)
  - source: external-cited

## Verification Principle (existence proof)

- Existence proof: demonstrate the weakness logic is reachable with a controlled,
  benign marker — for S2-045, a non-destructive proof that input reaches command
  execution (e.g. a benign environment-identity echo); for SQLi, prove
  reachability and the DB instance / library names only. Then stop.
- Hard stops (confidentiality / availability / integrity): do NOT run OS commands
  beyond a benign identity proof, do NOT dump rows or read student/business data,
  do NOT modify records, no webshell/backdoor residue, no pivot. EDUSRC harmless
  principle: prove existence only.

## False-Positive / Confounders

- Vendor/product naming: "KINGOSOFT" and "青果教务(网络管理)系统" refer to the
  same product line by 湖南青果软件有限公司 — they are NOT separate products.
  (Earlier conflation corrected on 2026-06-10.)
- WAF present in many edu deployments; a block page / filtered response is
  `certainty 0.3`, not a finding.
- S2-045 is a framework CVE — a patched Struts2 (or a non-Struts2 build) is not
  vulnerable; confirm the framework/version before applying the anchor.

## References

- https://nvd.nist.gov/vuln/detail/CVE-2017-5638
- https://vul.wangan.com/a/CNNVD-201705-1419
- https://vulners.com/seebug/SSV:95365
- https://vulners.com/seebug/SSV:95367
