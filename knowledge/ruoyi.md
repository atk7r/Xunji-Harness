---
id: ruoyi
product: RuoYi / RuoYi-Cloud (若依)
vendor: RuoYi (open source)
aliases: [ruoyi, ruoyi-vue, ruoyi-cloud, 若依]
category: framework-management-endpoint
last_reviewed: 2026-06-11
maturity: verified
signatures: ["/prod-api/", "欢迎使用ruoyi后台管理框架", "/captchaimage"]
---

<!--
Grounding knowledge, not a weapon. Recognition + weakness class + references +
safe-verification principle only. No payloads/steps — the driver derives the
specific proof check at runtime (tools/probe.py, tools/scan.py).
-->

## Recognition (identification only)

- Signature: API base path `/prod-api/` (Vue build) or `/dev-api/`; backend
  greeting `欢迎使用RuoYi后台管理框架，当前版本：vX.Y.Z` at the API root — leaks
  exact version.
- Signature: management route family `/system/user`, `/system/role`,
  `/system/menu`, `/system/dict/data/type/...`, `/system/config/configKey/...`,
  `/monitor/...`; AjaxResult JSON wrapper `{"msg":...,"code":...}`; unauth
  `/captchaImage` and `/login`.
- Signature (RuoYi-Cloud): a Spring Cloud Gateway at `/api` aggregating per-service
  swagger via `/swagger-resources` (services like system / schedule / file /
  gen / job), each at `/{service}/v2/api-docs`; internal host marker like
  `gateway:8081` inside the docs.
- Distinguishing notes: layui-based admin templates (layuimini) are a different
  family; RuoYi is Vue/ElementUI + Spring Boot. The `/prod-api` + AjaxResult
  combo is the reliable tell.

## Weak-Point Anchors (variant-analysis input — NOT exploit steps)

- Anchor: unauthenticated Swagger / OpenAPI documentation exposure
  - Affected: default deployments that ship springfox/springdoc enabled in prod;
    seen on RuoYi single-app and RuoYi-Cloud gateway (aggregated).
  - Mechanism: SecurityConfig permits `/swagger-ui/**`, `/v2|v3/api-docs`,
    `/swagger-resources` while business endpoints stay token-gated; result is
    full internal API surface + version + internal hostnames disclosed to anon.
  - Reference: CWE-200; product hardening guidance (disable swagger in prod).
  - source: run-observation (<run> E-012 zsxcx v3.8.8; E-016 rlkxt
    RuoYi-Cloud) + external-cited
- Anchor: exact version disclosure at API root
  - Affected: all versions (the greeting string).
  - Mechanism: enables version-specific variant analysis (map vX.Y.Z to known
    advisories).
  - Reference: CWE-200.
  - source: run-observation (E-012)
- Anchor: known higher-severity classes are AUTHENTICATED (record, do not chase
  unauth): `/common/download/resource` path traversal; `/tool/gen` & SnakeYAML/
  scheduled-task SSTI/RCE; `params[dataScope]` SQLi. All require a session in
  current versions.
  - Affected: version-dependent; verify the live version against advisories.
  - Mechanism: post-auth admin features; need a sanctioned test account.
  - Reference: search NVD/CNVD by "RuoYi" + the disclosed version.
  - source: external-cited (verify per target; do not assert a CVE from memory)

## Verification Principle (existence proof)

- Existence proof: anonymous GET of the swagger/api-docs paths returns the real
  Swagger UI / structured OpenAPI JSON, and the API root returns the version
  string. That presence is the finding.
- Hard stops: confirm the docs/version are reachable, then STOP. Do NOT call the
  documented data endpoints to pull records, and do NOT chase auth'd RCE/SQLi/
  file-read without an authorized test account (those add/extract/destroy →
  authorization gate). Bound impact at information disclosure unless a credentialed
  scope is granted.

## False-Positive / Confounders

- A 200 response carrying a login page or a unified `{"code":500,"404 NOT_FOUND"}`
  wrapper at api-docs is NOT exposure — the doc must be real OpenAPI JSON.
- Business endpoints returning `{"code":401}` (HTTP 200 body) is correct auth
  enforcement, not a vuln — do not report it.

## References

- CWE-200: Exposure of Sensitive Information.
- RuoYi project security/deployment docs (disable Swagger in production).
- Per-target: query NVD / CNVD for "RuoYi" + the version string disclosed at
  `/prod-api/` before asserting any version-specific CVE.
