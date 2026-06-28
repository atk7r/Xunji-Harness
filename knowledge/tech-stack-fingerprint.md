---
id: tech-stack-fingerprint
product: Web technology stack fingerprint patterns
vendor: cross-product
aliases: [stack fingerprint, server header, 技术栈识别, IIS, Apache, Nginx, Tomcat, PHP, ASP.NET, Java]
category: weakness-recognition
last_reviewed: 2026-06-28
maturity: seed
signatures: ["__viewstate", "jsessionid=", "phpsessid=", "asp.net_sessionid=", "microsoft-iis", "x-aspnet-version", "dhn ws/"]
---

<!--
PUBLIC grounding tier. Generic recognition of web technology stacks from
response headers, cookies, and page markers — cross-product. Source: every
run starts with this; the patterns below are synthesized from 18 runs across
Chinese universities, Taiwanese SaaS, Korean universities, and lab targets.
-->

## Recognition (identification only)

### Server header tells
- `Microsoft-IIS/X.Y` → IIS (Windows); ASP.NET likely if `.aspx` paths exist.
- `Apache` (Unix) → usually PHP; `Apache-Coyote/X.Y` → Tomcat (Java).
- `nginx` → reverse proxy (backend hidden); check `X-Powered-By` or cookies
  for the real backend.
- `DHN WS/X.Y` → 大汉网络 JCMS (Chinese government/EDU CMS).
- `*******` (masked) → reverse-proxy/WAF deliberately erasing the header;
  common on China EDU sites with 安恒云 WAF.
- No `Server` header → could be stripped at proxy; not diagnostic.

### Cookie tells
- `JSESSIONID` → Java (Tomcat/Jetty/Spring); `PHPSESSID` → PHP;
  `ASP.NET_SessionId` → ASP.NET/IIS; `laravel_session` → Laravel;
  `wsessid` or `route=` → various Chinese frameworks.
- Cookie with `Domain=.xxx.edu.cn` → shared SSO domain (CAS or custom).

### Page body tells
- `<meta name="generator" content="...">` → strong CMS fingerprint
  (XpressEngine, VSB, WordPress, etc.).
- `__VIEWSTATE` hidden input → ASP.NET WebForms.
- `/prod-api/` paths → RuoYi (Spring Boot + Vue).
- `DXR.axd` → DevExpress (ASP.NET component suite).
- `wp-content/`, `wp-includes/` → WordPress.
- `/resource/` + `dynclicks.js` → 博达 VSB.
- `/idp/shibboleth` → Shibboleth SAML IdP.
- `/por/login_auth.csp` → Sangfor SSL VPN.

### Distinguishing notes
- A site can be multilingual: IIS fronting Tomcat (AJP connector), nginx
  fronting PHP-FPM + Java microservices. Fingerprint each layer.
- Masked `Server` header + VSB paths = "WAF masking the ASP/IIS behind
  VSB" — common China EDU pattern.

## Weak-Point Anchors

- Anchor: version disclosure enables targeted CVE matching
  - Affected: any stack that leaks exact version in headers or error pages.
  - Mechanism: `X-AspNet-Version: 4.0.30319`, `Server: Apache/2.4.6 (CentOS)`,
    PHP version in `X-Powered-By` or phpinfo — each enables lookup of known
    vulnerabilities for that exact version.
  - Reference: CWE-200
  - source: run-observation (all runs)
- Anchor: stack combination reveals likely attack surface
  - Affected: any target.
  - Mechanism: IIS + ASP.NET + `__VIEWSTATE` → ViewState deserialization surface;
    PHP + Apache + `PHPSESSID` → file upload / LFI / SQLi (PHP mysql_ legacy);
    Java + `JSESSIONID` + Spring → Actuator / Swagger / deserialization;
    nginx reverse proxy → try Host-header bypass to reach backend directly.
  - Reference: this is the driver's reasoning input, not an exploit
  - source: driver-reasoning
- Anchor: masked/erased Server header indicates WAF or reverse proxy presence
  - Affected: sites behind a WAF or reverse proxy that strips Headers.
  - Mechanism: a masked header signals a gateway layer that may inspect or
    filter traffic; its presence and coverage (GET vs POST, encoding handling)
    is the variant-analysis input (see [[waf-block-recognition]]).
  - Reference: this repo's run-observation
  - source: run-observation

## Verification Principle

- Existence proof: collect headers + cookies + key page markers from a
  single benign GET. Match against the patterns above. Produce a
  structured fingerprint: `{frontend: nginx, backend: PHP/Apache, CMS: VSB,
  WAF: Anheng (masked Server)}`.
- Hard stops: fingerprinting is read-only; the above is reconnaissance.
  Product-specific attack follows the corresponding knowledge entry.

## False-Positive / Confounders

- `X-Powered-By: PHP/5.3.24` may be spoofed or the version may be from a
  single virtual host among many. Cross-confirm with behavior (PHP-specific
  URLs, session cookie format).
- A CDN (Cloudflare, Alibaba CDN) may add its own headers — distinguish CDN
  headers from origin headers.
- `Server: Apache` on a site serving `.aspx` means Apache reverse-proxying
  IIS — the platform is IIS, not Apache.

## References

- OWASP: Fingerprint Web Server / Application
- Wappalyzer / BuiltWith fingerprinting methodology
- This repo's run-observation: synthesized from 18 runs across multiple
  tech stacks
- Related: [[waf-block-recognition]] [[deserialization-signatures]]
  [[api-docs-surface]] [[error-disclosure-signatures]]
