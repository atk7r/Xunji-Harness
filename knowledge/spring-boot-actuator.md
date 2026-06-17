---
id: spring-boot-actuator
product: Spring Boot Actuator
vendor: VMware (Spring)
aliases: [actuator, spring actuator, spring boot management endpoints]
category: framework-management-endpoint
last_reviewed: 2026-06-10
maturity: verified
signatures: ["/actuator/health", "/actuator/env", "/actuator/configprops"]
---

<!--
Grounding knowledge, not a weapon. See knowledge/README.md.
Anchors carry weakness class + mechanism + reference only. No payloads/steps.
-->

## Recognition (identification only)

- Signature: management base path `/actuator` returns a JSON link inventory
  (`{"_links":{...}}`); legacy Boot 1.x exposes flat paths like `/env`,
  `/health`, `/dump`, `/trace` instead of under `/actuator`.
- Signature: `/actuator/health` returns JSON `{"status":"UP"}` (or `DOWN`); the
  actuator inventory body carries `"_links":` and `"self":` JSON markers.
- Signature: favicon fingerprint — mmh3 favicon hash `116323821`
  (`shodan-query: http.favicon.hash:116323821`). Mined from nuclei detection
  template `springboot-actuator` (detection metadata; source: external-cited).
- Signature: sensitive endpoints when exposed: `/actuator/env`,
  `/actuator/heapdump` (binary HPROF download), `/actuator/configprops`,
  `/actuator/mappings`, `/actuator/jolokia`, `/actuator/threaddump`.
- Signature: commonly on the app port or a separate management port (8080 /
  8081 / 9001), often behind paths a reverse proxy forgot to block.
- Distinguishing notes: a plain `/health` returning 200 is NOT proof — many apps
  ship a custom non-actuator health route. Confirm the actuator JSON shape.

## Weak-Point Anchors (variant-analysis input — NOT exploit steps)

- Anchor: Unauthenticated sensitive-endpoint exposure (information disclosure)
  - Affected: any Boot version where actuator is exposed without auth and
    `management.endpoints.web.exposure.include` is broad (`*`). Veracode 2024:
    ~18% of scanned Boot apps expose actuator unauthenticated.
  - Mechanism: `/heapdump` is a full JVM heap (HPROF) that can contain in-memory
    secrets (passwords, tokens, cloud keys); `/env` and `/configprops` can echo
    configuration including credential properties; in cloud, `/env` may surface
    instance-metadata tokens.
  - Reference: https://www.wiz.io/blog/spring-boot-actuator-misconfigurations
  - source: external-cited

- Anchor: Jolokia endpoint → JMX MBean access (documented RCE vectors)
  - Affected: deployments exposing `/actuator/jolokia` (or `/jolokia`) with the
    Jolokia library on the classpath.
  - Mechanism: Jolokia bridges HTTP to JMX MBeans; documented vectors include
    logback `JMXConfigurator.reloadByURL` (blind XXE / remote config load) and
    creating a JNDIRealm reachable to JNDI injection — i.e. config-disclosure
    escalating to code execution under the right MBeans.
  - Reference: https://book.hacktricks.xyz/network-services-pentesting/pentesting-web/spring-actuators
  - source: external-cited

- Anchor: Spring Cloud Gateway actuator SpEL injection (component-specific)
  - Affected: Spring Cloud Gateway 3.1.0, 3.0.0–3.0.6 and older with the gateway
    actuator enabled.
  - Mechanism: the gateway actuator accepts route definitions whose predicate /
    filter SpEL is evaluated, allowing remote code execution.
  - Reference: https://nvd.nist.gov/vuln/detail/CVE-2022-22947
  - source: external-cited

## Verification Principle (existence proof)

- Existence proof: a GET to `/actuator` (or the specific endpoint) returns the
  actuator JSON shape / expected content-type, unauthenticated. That proves the
  endpoint is exposed — stop there.
- Existence proof for `/heapdump` without exfiltration: a ranged or truncated
  read whose response shows gzip magic (`1f8b08`) or the HPROF profiler marker
  (`JAVA PROFILE` / `HPROF`) confirms a real heap dump is served — without
  downloading the multi-GB body. Confirm the marker, then stop. (Signature mined
  from nuclei `springboot-heapdump` detection logic.)
- Hard stops (confidentiality / integrity): do NOT download or parse the
  heapdump bytes, do NOT read credential values out of `/env`/`/configprops`, do
  NOT invoke any Jolokia write/exec MBean operation, do NOT post a gateway route
  to trigger SpEL. Prove "exposed and unauthenticated," not impact extraction.
- This is presence, not data: per the harmless-verification boundary, proving
  reachability of a sensitive endpoint is enough; pulling the data is out.

## False-Positive / Confounders

- A custom `/health` route unrelated to actuator (check the actuator JSON shape).
- A reverse proxy / WAF returning 200 (or a stub body) for everything.
- A honeypot presenting a fake actuator inventory — a single 200 cannot rule
  this out; corroborate the JSON structure and an independent endpoint.
- Endpoints behind auth returning 401/403 mean NOT exposed — not a finding.

## References

- https://www.wiz.io/blog/spring-boot-actuator-misconfigurations
- https://book.hacktricks.xyz/network-services-pentesting/pentesting-web/spring-actuators
- https://nvd.nist.gov/vuln/detail/CVE-2022-22947
