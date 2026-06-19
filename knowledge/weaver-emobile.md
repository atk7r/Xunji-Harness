---
id: weaver-emobile
product: 泛微 e-mobile 移动管理平台 (EMP)
vendor: 泛微 Weaver
aliases: [e-mobile, emobile, 移动管理平台, weaver emp, /emp]
category: oa-mobile-platform
last_reviewed: 2026-06-20
maturity: seed
signatures: ["移动管理平台", "apiprifix", "/emp/", "window.version", "/page/manage/"]
---

<!-- PUBLIC grounding tier. Recognition + weak-point anchors only; no payloads. -->

## Recognition (identification only)

- Signature: SPA whose JS sets `window.apiPrifix="/emp"` (note the vendor's misspelling
  "apiPrifix"), title "移动管理平台-企业管理", assets under `/page/manage/...`, `window.version=`<build>.
- Signature: Spring Boot backend — unknown paths return Spring's default error JSON
  `{"timestamp":...,"status":404,"error":"Not Found","path":"/emp/..."}`.
- Distinguishing notes: the `/emp` context + 企业管理 + Spring error JSON distinguish it from generic
  "移动办公" lookalikes; build version is a date string (e.g. 20260306).

## Weak-Point Anchors (variant-analysis input — NOT exploit steps)

- Anchor: unauthenticated arbitrary file upload (legacy)
  - Affected: older e-mobile (e.g. v9.5); endpoint `lang2sql`. REMOVED in current builds (returns 404).
  - Mechanism: an unauth interface wrote uploaded content without validation.
  - Reference: CNVD-2017-02376
  - source: external-cited
- Anchor: arbitrary file read / SSRF (legacy)
  - Affected: older e-mobile; `client/cdnfile`. Absent in current builds (404).
  - Mechanism: a file/url fetch parameter without path/host restriction.
  - Reference: public "泛微 e-mobile cdnfile 任意文件读取" advisories (CN-SEC)
  - source: external-cited
- Anchor: Spring Boot actuator / management-endpoint exposure
  - Affected: deployments exposing `/emp/actuator/*` or `/actuator/*`.
  - Mechanism: see knowledge/spring-boot-actuator.md (env/heapdump/jolokia info-disclosure → RCE class).
  - Reference: knowledge/spring-boot-actuator.md
  - source: external-cited
- Anchor: Fastjson/Jackson deserialization on the JSON API surface (post-auth)
  - Affected: `/emp/*` JSON endpoints if a vulnerable Fastjson autotype/Jackson polymorphic config is present.
  - Mechanism: untrusted JSON deserialized into types → gadget RCE; proof typically needs OOB/dnslog.
  - Reference: see knowledge/deserialization-signatures.md
  - source: driver-reasoning

## Verification Principle (existence proof)

- Existence proof: confirm the product (apiPrifix=/emp + Spring error JSON), then test whether a
  named legacy endpoint is present (404 = patched) and whether actuator/JSON-deser surface is exposed.
- Hard stops: prove endpoint presence / unauth reachability only; no file pull, no heapdump bytes, no
  deser RCE auto-run (author-and-handoff).

## False-Positive / Confounders

- A non-Weaver "移动管理平台" without the `/emp` apiPrifix and Spring error JSON is a different product.

## References

- https://www.cnvd.org.cn/ (search "泛微 e-mobile / CNVD-2017-02376")
