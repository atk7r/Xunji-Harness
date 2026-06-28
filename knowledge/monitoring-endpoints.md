---
id: monitoring-endpoints
product: Infrastructure and microservice monitoring endpoint recognition
vendor: cross-product
aliases: [monitoring, prometheus, nacos, eureka, jolokia, stub_status, metrics, 监控端点, 注册中心]
category: weakness-recognition
last_reviewed: 2026-06-28
maturity: seed
signatures: ["/nacos/v1/", "/eureka/apps", "/jolokia/list", "stub_status", "actuator/prometheus", "/prometheus/metrics", "netdata dashboard"]
---

<!--
PUBLIC grounding tier. Generic recognition of monitoring, metrics, and service
registry endpoints — cross-product, beyond the common Actuator/Druid covered in
api-docs-surface.md and spring-boot-actuator.md. Covers Nacos, Eureka, Jolokia,
Prometheus, Nginx stub_status, Netdata, and generic /metrics endpoints.
-->

## Recognition (identification only)

- Signature (Nacos): `/nacos/` path, `/nacos/v1/auth/`, `/nacos/v1/ns/` —
  Alibaba Nacos service registry and config center. `/nacos/v1/console/server/state`
  returns cluster state without auth on default deployments.
- Signature (Eureka): `/eureka/`, `/eureka/apps`, `/eureka/status` —
  Netflix Eureka service registry (Spring Cloud). `/eureka/apps` returns full
  service instance registry in XML/JSON — internal hostnames and ports of all
  registered microservices.
- Signature (Jolokia): `/jolokia/`, `/jolokia/list`, `/jolokia/version`,
  `/actuator/jolokia` — JMX-over-HTTP bridge. `/jolokia/list` returns all
  available MBeans including JVM internals, Spring beans, and sometimes
  datasource credentials. `/jolokia/exec` allows MBean operation invocation.
- Signature (Prometheus): `/metrics`, `/prometheus`, `/actuator/prometheus` —
  OpenMetrics/Prometheus text format endpoints. The output format is distinct:
  `metric_name{label="value"} value` lines. Often exposed on separate port
  (e.g. :9090, :9100).
- Signature (Nginx): `/nginx_status`, `/stub_status`, `/basic_status` —
  Nginx status page (stub_status module). Shows active connections, accepted
  connections, handled requests.
- Signature (Netdata): `/netdata/`, port 19999 — real-time infrastructure
  monitoring dashboard. Default install has no authentication.
- Signature (generic): `/health`, `/status`, `/info`, `/monitor`, `/stats`,
  `/server-status` (Apache mod_status), `/phpfpm_status` (PHP-FPM).
- Distinguishing notes: these endpoints are distinct from Swagger/OpenAPI
  (API docs) and Actuator (Spring Boot management). The unifying feature is
  they expose operational/internal state, not application data.

## Weak-Point Anchors

- Anchor: Nacos/Eureka unauth → internal network topology disclosure
  - Affected: default Nacos/Eureka deployments without authentication enabled.
  - Mechanism: the service registry returns the full list of registered
    microservices including internal IP:port pairs, enabling server-side
    request forgery (SSRF) targeting internal services and lateral movement
    from a compromised web app.
  - Reference: CWE-200; known Nacos/Eureka unauth access incidents (CNVD)
  - source: external-cited
- Anchor: Jolokia unauth → JMX MBean invocation
  - Affected: Jolokia deployments with no access restriction.
  - Mechanism: `/jolokia/exec` can invoke arbitrary MBean operations; some
    MBeans expose file read/write, command execution, or JNDI injection
    capabilities. `/jolokia/list` reveals the full attack surface of
    available MBeans.
  - Reference: CWE-306; known Jolokia exploit classes (JNDI, MLet)
  - source: external-cited
- Anchor: Prometheus/metrics endpoint exposes internal counters
  - Affected: unauthenticated Prometheus endpoints.
  - Mechanism: metrics often include request counts by URL path (revealing
    hidden admin endpoints), error rates (revealing failed exploitation
    attempts by others), and JVM/application metrics that leak internal
    configuration. Not directly exploitable but powerful reconnaissance.
  - Reference: CWE-200
  - source: driver-reasoning

## Verification Principle

- Existence proof: GET the endpoint path → confirm the response body is the
  expected format (Nacos JSON, Eureka XML/JSON, Jolokia JSON, Prometheus
  text). Record the endpoint URL + type. Classify by sensitivity: Nacos/
  Eureka service listing = HIGH (internal topology), Jolokia exec available
  = CRITICAL, Prometheus counters = LOW (recon only).
- Hard stops: confirm the endpoint is accessible. For Jolokia `/exec`, do NOT
  invoke MBean operations autonomously (that crosses into code execution).
  For service registries, do NOT use the discovered internal addresses to
  probe internal services (lateral movement is operator-gated).

## False-Positive / Confounders

- `/metrics` returning a login page or 404 is not exposure — Prometheus
  endpoints return a distinctive text format; classify by content, not path.
- Nacos login page at `/nacos/` is the default — verify whether the console
  is actually accessible without login (some versions allow read-only API
  access without authentication even when the UI shows a login form).
- Netdata on port 19999 is often firewalled separately from HTTP — 200 on
  :19999 from a different source IP is a stronger signal.
- Some CDNs/load-balancers expose their own `/status` endpoints that are
  intentionally public — distinguish from backend monitoring endpoints.

## References

- Nacos: https://nacos.io/en/docs/security/auth/ (authentication configuration)
- Eureka: https://docs.spring.io/spring-cloud-netflix/docs/current/reference/html/#securing-eureka-server (Spring Cloud Netflix Eureka security)
- Jolokia: https://jolokia.org/reference/html/security.html
- Prometheus: https://prometheus.io/docs/operating/security/
- This repo's run-observation: various EDU runs (Nacos/Eureka on campus
  microservice deployments)
- Related: [[api-docs-surface]] [[spring-boot-actuator]]
