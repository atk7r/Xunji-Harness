---
id: api-docs-surface
product: API documentation and monitoring endpoint exposure
vendor: cross-product
aliases: [swagger, openapi, graphql, druid, actuator, api-docs, 接口文档暴露, 监控端点]
category: weakness-recognition
last_reviewed: 2026-06-28
maturity: seed
signatures: ["/swagger-ui.html", "/v2/api-docs", "/v3/api-docs", "/swagger-resources", "/actuator", "/druid", "/graphql"]
---

<!--
PUBLIC grounding tier. Generic recognition of API documentation and monitoring
endpoint exposure — cross-product, covers Swagger/OpenAPI, Spring Boot Actuator,
Druid, GraphQL introspection. Source: cqytxy run-observation (RuoYi Swagger),
scshr run-observation (SDK docs), multiple EDU runs.
-->

## Recognition (identification only)

- Signature (Swagger/OpenAPI): `/swagger-ui.html`, `/swagger-ui/index.html`,
  `/swagger-resources`, `/v2/api-docs`, `/v3/api-docs`, `/api-docs` (JSON),
  `/doc.html` (Knife4j/Swagger-Bootstrap-UI, common in Chinese Spring apps).
- Signature (Spring Boot Actuator): `/actuator`, `/actuator/health`,
  `/actuator/env`, `/actuator/mappings`, `/actuator/heapdump` — Spring Boot
  management endpoints; health is often public, env/mappings/heapdump are
  sensitive.
- Signature (Druid): `/druid/index.html`, `/druid/statview.html`,
  `/druid/websession.html`, `/druid/spring.html` — Alibaba Druid connection
  pool monitor; unauthenticated access leaks SQL stats, URIs, session data.
- Signature (GraphQL): `/graphql` (common), `/api/graphql`, `/gql` — GraphQL
  endpoint; GET returns "query not found" or a GraphiQL IDE; POST with
  `{"query":"{__schema{types{name}}}"}` confirms introspection enabled.
- Signature (generic API docs): `/api/help`, `/api/docs`, `/docs/api`,
  `/api/swagger.json`, `/openapi.json` — vendor-neutral paths.
- Distinguishing notes: a Swagger UI page is the UI shell; the actual data is
  the JSON at `/v2/api-docs` or `/v3/api-docs`. Confirm the JSON is real
  (contains `paths` with actual endpoints), not a static error page.

## Weak-Point Anchors

- Anchor: unauthenticated API documentation exposes internal endpoints + version
  - Affected: deployments where Swagger/OpenAPI is enabled in production without
    auth on the doc paths.
  - Mechanism: the OpenAPI JSON enumerates every endpoint, parameter, request
    body schema, and often internal hostnames; this is a blueprint for the
    attacker. Version info in the doc enables CVE matching.
  - Reference: CWE-200 (sensitive information exposure)
  - source: run-observation (cqytxy E-012/E-016, scshr E-002)
- Anchor: Actuator env/heapdump exposes secrets
  - Affected: Spring Boot with `management.endpoints.web.exposure.include=*`
    and no auth on `/actuator`.
  - Mechanism: `/actuator/env` lists all `application.properties` including
    `spring.datasource.password`; `/actuator/heapdump` contains in-memory
    secrets extractable with heapdump analysis tools.
  - Reference: CWE-200; Spring Boot production hardening docs
  - source: external-cited
- Anchor: Druid StatViewServlet unauth → SQL execution stats + session data
  - Affected: Druid with `stat-view-servlet.enabled=true` and no login configured.
  - Mechanism: real SQL statements, execution counts, and active sessions are
    visible; URI monitoring reveals hidden API paths not linked anywhere.
  - Reference: CNVD Druid unauth disclosures
  - source: external-cited
- Anchor: GraphQL introspection enabled
  - Affected: GraphQL endpoints with introspection not disabled in production.
  - Mechanism: `__schema` query reveals every type, field, and mutation —
    full API schema, including admin-only mutations that can then be tested.
  - Reference: OWASP: GraphQL introspection in production
  - source: external-cited

## Verification Principle

- Existence proof: GET the doc path → verify the response body is real API
  documentation (valid OpenAPI JSON / real Druid HTML / GraphQL introspection
  result with types). Then test the listed data endpoints for auth enforcement
  — but do NOT pull data (stop at 401/403 vs 200 check).
- Hard stops: confirm doc exposure + version leak. Do NOT call documented
  business endpoints to extract data. Impact boundary: information disclosure.

## False-Positive / Confounders

- `/swagger-ui.html` returning a login page (redirect to /login) = auth-gated,
  not exposed. A static "no docs" JSON (`{"swagger":"2.0","paths":{}}`) = empty
  stub.
- `/actuator/health` returning `{"status":"UP"}` is by-design and not a finding.
  Only `/actuator/env` or `/actuator/heapdump` with real data is sensitive.
- Druid returning a deny page with HTTP 200 (body says "Sorry, not permitted")
  is a WAF/access-control page, NOT Druid exposure (cqytxy E-009 lesson).
- GraphQL returning 404 on GET (POST-only) is normal; test POST introspection.

## References

- OWASP: API documentation in production
- Spring Boot: production-ready features / security
- This repo's run-observation: cqytxy E-012 (RuoYi Swagger v3.8.8), E-016
  (RuoYi-Cloud gateway Swagger aggregation); scshr E-002 (SDK docs)
- Related: [[spring-boot-actuator]] [[waf-block-recognition]]
