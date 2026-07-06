---
id: sudy-cms
product: 苏迪 CMS (Sudy CMS)
vendor: 苏迪 (Sudy)
aliases: [苏迪cms, sudy cms, 苏迪建站]
category: cms
last_reviewed: 2026-06-10
maturity: seed
signatures: ["sudy cms", "苏迪CMS", "苏迪建站"]
---

<!--
Grounding knowledge, not a weapon. See knowledge/README.md.
Seed: no verifiable public anchor confirmed this pass. Do not invent CVE/CNVD.
-->

## Recognition (identification only)

- Pending: no reliable public fingerprint confirmed this pass. This entry was
  seeded from the lygsf_edu_cn run lead, not from a vendor doc or a verified
  signature database. Capture concrete signatures (page title, copyright/footer
  string, distinctive static paths, CMS-specific markers) from a first-hand run
  and record them here with the run/evidence id before relying on this entry.

## Weak-Point Anchors (variant-analysis input — NOT exploit steps)

- None verified yet. Verification pass 2026-06-10 (cnvd.org.cn product search +
  general web) returned no primary-source weakness record attributable to 苏迪
  CMS; the platform search surfaced only unrelated CMS (MyuCMS / 极致CMS /
  PbootCMS) — do not borrow their CVEs. Leave empty rather than inventing
  anchors; promote here only with a verified reference and a `source:` tag.
  Next pass: try the exact vendor/product string from a first-hand run banner,
  and search CNVD by vendor company name once it is known.

## Verification Principle (existence proof)

- General CMS principle until anchors exist: once a concrete weakness is grounded
  on a live target, prove existence and stop — for injection, prove reachability
  and the DB instance / library names only (no dumping); for file read/upload,
  prove the parse/read logic without retaining data or leaving residue.
- Hard stops (confidentiality / availability / integrity): no data export, no
  record modification, no webshell/backdoor residue, no pivot.

## False-Positive / Confounders

- Misidentification risk is high for a niche product: confirm the CMS identity
  before applying any future anchor; do not assume look-alike CMS behavior.
- WAF / gateway block pages and redirects are `certainty 0.3`, not findings.

## References

- (none verified yet — pending primary-source CNVD/CNNVD/vendor confirmation)
