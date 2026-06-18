# Vuln-class anchor lexicon

> **Purpose**: when forming a hypothesis, anchor it on the **precise vuln-class term** —
> this localizes the model's knowledge and retrieves the right weak-point anchor (PDF
> "precise terminology": say "SQLi" not "fuzz the param", "IDOR" not "broken access",
> "path traversal" not "read a file").
>
> **This is recognition + anchoring vocabulary, NOT a "fire all of these at every target"
> checklist** (that is the blind scanner / playbook the project forbids). Discipline (see
> docs/cognition): the class you test **must be justified by an observed surface signal**;
> name the signal that made it relevant; a negative / deferred record states the barrier or
> why the class did not apply; **this table lists coverage, never payloads** (payloads are
> crafted live from internet research, or retrieved from the local xday tier).
> The `_` prefix makes check_knowledge skip this file (it is not a product-fingerprint
> entry); product entries' class names should be drawn from this canonical vocabulary.
>
> Pick the anchor by attack-surface **subtype** (see docs/WORKFLOW depth phases: LOGIN /
> API / UPLOAD / ADMIN / ACTUATOR / SWAGGER / GRAPHQL / WEBSOCKET / SSO / FILE_DOWNLOAD /
> URL_FETCH / DEBUG / CLOUD). Format: `canonical name (aliases) — recognition signal — anchor direction`

## 1. Injection — param/API + query surfaces
- **SQLi** — error/boolean diff (`AND 1=1` vs `1=2`) / time delay — union·blind·stacked
- **NoSQLi** — Mongo/Redis `$ne`/`$gt`/`[$regex]` operator injection — auth bypass / data extraction
- **OS command injection** (shell concat) — `; | & backtick $()` echo / time delay — ffmpeg·ping·parse-arg concat
- **Code / expression injection** — OGNL (Struts2) / SpEL (Spring) / EL / Groovy — `%{}` `#{}` `${}` evaluation
- **SSTI** (server-side template injection) — `{{7*7}}` `${7*7}` eval diff — Jinja2·Freemarker·Velocity·Thymeleaf
- **LDAP / XPath / CRLF / HTTP-header / SMTP / ORM injection** — metachar break-out per context
- (deserialization / XXE are in §3 server-side — usually fingerprint-driven gadget reachability, not pure param injection)

## 2. Access control / authn (authz) — login + interface surfaces (**one family, do NOT tunnel on this alone**)
- **auth bypass** — logic short-circuit / SQLi-in-login / JWT alg=none / default creds — straight to backend
- **unauthenticated access** — interface checks no identity — pull data / call functions directly
- **IDOR / horizontal authz bypass** (BOLA) — change id/seq to read another same-role user's data — control-variable diff (self vs other)
- **vertical privilege escalation** (BFLA) — low-role calls high-role interface — role boundary bypass
- **JWT / session flaws** — weak key / alg confusion / session fixation / no-expiry — forge / hijack
- **default / weak credentials** — admin/admin etc. (few tries, not brute) — appliance / backend
- **captcha / OTP / SMS bypass** — replayable / front-end-only check / no rate limit (bombing has side effects, careful)
- **SSO / OAuth / SAML flaws** — loose redirect_uri / missing state·nonce·PKCE / audience / signature wrapping (XSW) / ticket reuse

## 3. Server-side impact — interface + file surfaces
- **SSRF** — url/external-link/webhook/avatar/preview param — internal probe / cloud metadata / protocol smuggling
- **deserialization** — Java (ysoserial) / PHP (`O:`) / .NET (ViewState) / Python (pickle) — fastjson·Shiro·ViewState etc. **fingerprint-driven gadget reachability**
- **XXE** (XML external entity) — XML entry + `<!ENTITY>` — file read / SSRF / blind OOB
- **file upload → shell** (upload-to-RCE) — type/extension/content/parser bypass — webshell; also image/parser RCE·polyglot·zip-bomb·storage-bucket ACL
- **path traversal / LFI / RFI** — `../` / encoding / absolute path — arbitrary file read / include / source leak
- **arbitrary file read/write/delete/download** — filename/path param — config / creds / overwrite
- **RCE chain / getshell** — any of the above ending in command execution (prove-and-stop; deeper is operator-gated)

## 4. Client-side — browser trust boundaries
- **XSS** (reflected / stored / DOM) — input reflected unencoded — credential theft (prove DOM XSS with render headless browser)
- **CSRF** — state-changing request with no token / same-origin check — request-on-behalf
- **CORS misconfiguration** — reflected `ACAO` + `ACAC: true` — cross-origin read of credentialed response
- **clickjacking / postMessage / prototype pollution** — missing X-Frame / cross-window message no origin check / `__proto__` pollution
- **open redirect** — redirect/url param external jump (often chains with SSRF/OAuth)

## 5. Business / workflow logic — pure reasoning, no generic payload
- **race / TOCTOU** — concurrent double-spend / stock oversell / invite-code·token reuse / missing idempotency key
- **flow bypass** — step-skip / price tamper / quantity tamper / negative / out-of-range quantity / coupon stacking / state-machine tamper
- **replay** — request/ticket replayable — duplicate order / duplicate claim

## 6. Information disclosure / exposure — unauth, ready-made
- **source / sourcemap leak** — `.js.map` / webpack — restore source → logic bugs / secrets / API route discovery
- **VCS leak** — `.git/.svn/.hg/.DS_Store` — pull source / history
- **backup / temp files** — `.bak .swp .old .zip .sql ~` — source / database
- **debug / admin interface exposure** — actuator / swagger·openapi / druid / nacos / eureka / debug / phpinfo / console — info → RCE chain
- **hardcoded secrets / tokens** — AK/SK·JWT·API key in JS / config / responses
- **directory listing / error stack** — autoindex / 500 stack — paths / tech stack / internal IPs

## 7. Config / components — assets / middleware
- **unauthenticated services** — Redis / Mongo / ES / Memcached / Docker API / K8s — direct connect, no auth
- **known component CVE** (n-day) — Log4Shell·fastjson·Shiro·Struts2·Spring (SpEL/Cloud)·Weblogic·Seeyon/Weaver/Tongda OA·Tomcat — on fingerprint hit, pull the knowledge/xday anchor
- **middleware / parsing quirks** — Nginx misconfig·parsing bug·WAF/rate-limit bypass (Content-Type/encoding/chunked)·HTTP request smuggling
- **cache / CDN** — cache poisoning / web cache deception / Host-header trust / route abuse
- **security headers / cookie / session config** (low sev but grounding) — SameSite/Secure/HttpOnly·HSTS·missing-or-bypassable CSP

## 8. Cloud / container / IAM
- **metadata SSRF** (IMDS) — 169.254.169.254 — IMDSv1 direct read / v2 bypass — cloud role temp creds
- **storage bucket exposure** — public S3 / OSS / blob ACL — list / download / overwrite
- **K8s / container** — dashboard/API-server/kubelet/etcd exposure · Docker socket · container escape
- **over-broad IAM / credential scope** — excessive role perms / cred scope·audience·expiry·refresh-rotation flaws

## 9. Host / network / OS — full red-team surface
- **weak network services** — SMB/NFS/FTP/Telnet/SNMP/RDP exposure · appliance default creds
- **domain / directory** — AD/Kerberos (AS-REP/Kerberoast) / LDAP misconfig
- **local privilege escalation** — sudo/SUID / cron·systemd·PATH hijack / writable service dirs / kernel·package n-day
- **lateral movement / credentials** — pass-the-hash / tickets / credential reuse (deeper is operator-gated)

## 10. Supply-chain / tenancy / resource (DoS)
- **supply chain** — dependency confusion / typosquatting / malicious update channel / CI-CD secret exposure / build-artifact leak / package·registry takeover / signed-release trust mistakes
- **multi-tenant isolation** — tenant-ID confusion / workspace·org boundary bypass / cross-tenant search·export·logs
- **resource exhaustion / DoS** (bounded class — keep the irreversible-harm boundary strict, do NOT actually take it down) — algorithmic complexity / regex backtracking / decompression bomb / GraphQL depth

---
**Adding a class**: put it under the right family (keep the `name — signal — anchor` three-part form, **no payloads**)
and keep the reference in docs/cognition's anchoring discipline consistent. **Never fire a class the target gives no
signal for** (that is the blind scanner the project rejects).
