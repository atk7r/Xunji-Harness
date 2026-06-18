---
id: vsb-cms
product: VSB 院系门户内容管理系统 (department portal CMS)
vendor: VSB (university department website-group CMS)
aliases: [VSB, 院系门户, system/resource, dynclicks, vsbscreen, 网站群]
category: cms
last_reviewed: 2026-06-12
maturity: seed
signatures: ["/system/resource/", "dynclicks", "/__local/", "vsbscreen"]
---

<!--
Grounding knowledge, not a weapon. Source: <run> run-observation +
public disclosure (external-cited). No payloads / steps / PoC.
-->

## Recognition (identification only)

- Signature: static resource prefix `/system/resource/` (`/system/resource/js/dynclicks.js`,
  `vsbscreen.min.js`, `/system/resource/code/...`); upload/media path `/__local/`.
- Signature: article URL rewrite `/info/<column-id>/<article-id>.htm` (static-ized pages); the homepage carries a
  click-count span `dynclicks_u<owner>_<clickid>`; search at `/search/modules/resultpc/soso.html`.
- Signature: the reverse proxy often masks the `Server` header (e.g. shows a string of `**********`), appearing
  together with the VSB content signatures.
- Distinguishing notes: department-site titles are usually "<school>-<department/office>"; what separates it from
  business systems like ZFSoft/Wisedu is `/system/resource/` + `dynclicks` + static-ized `/info/.../.htm`.

## Weak-Point Anchors (variant-analysis input — NOT exploit steps)

- Anchor: unauthenticated click-count endpoint `dynclicks.jsp` injection flaw class
  - Affected: `/system/resource/code/news/click/dynclicks.jsp?clickid&owner&clicktype`
  - Mechanism: clickid/owner have historically been concatenated into SQL; but some deployments int-cast/parameterize
    them (this repo's engagement was one such), with a front WAF blocking keywords → needs per-target verification,
    do not assume it is injectable
  - Reference: public "VSB dynclicks SQL injection" material; this repo's run-observation (a refutation record)
  - source: external-cited
- Anchor: injection / file surface in search and other `/system/resource/code/` jsp
  - Affected: dynamic jsp for search, lists, media
  - Mechanism: beyond dynclicks, VSB also has search/list interfaces; do not negate the whole stack from a single endpoint
  - Reference: this repo's run-observation
  - source: driver-reasoning
- Anchor: internal-network link / internal-system disclosure (low severity)
  - Affected: department sites often hardcode internal OPAC/journal/management-system direct links
  - Mechanism: public pages accidentally expose internal IPs/paths, useful for internal-network intel
  - Reference: this repo's run-observation (an engagement's lib leaked a 192.168.x OPAC)
  - source: run-observation

## Verification Principle (existence proof)

- Existence proof: `/system/resource/` + `dynclicks` confirms VSB. Injection must be tested live: numeric-equivalence /
  arithmetic to judge context; a quote → DB error vs WAF block must be distinguished (a block page ≠ a DB error).
- Hard stops: proof-level boolean/differential, no database dump; avoid high-frequency requests to the dynclicks
  count endpoint (easily triggers a WAF IP block — unrelated to SMS but it is high-frequency).

## False-Positive / Confounders

- **A WAF block ≠ injectable**: a quote triggering a block page / connection reset is the WAF, not a DB error;
  conversely "the WAF blocked the oracle-producing payload, so I judge it not-injectable with a no-oracle test" is
  **circular reasoning** — avoid (engagement lesson). See [[waf-block-recognition]].
- Dozens of department sites sharing one VSB + a masked reverse proxy are same-stack aliases; do not lump them as
  "all safe" — same-stack still needs per-site confirmation of search and other surfaces.

## References

- https://www.cnvd.org.cn/ (search "VSB / dynclicks")
- This repo's run-observation: runs/<run>/ evidence E-003/E-007 (an engagement's department portal group); related [[waf-block-recognition]]
