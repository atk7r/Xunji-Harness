---
id: webdav-exposure
product: WebDAV and extended HTTP method recognition
vendor: cross-product
aliases: [WebDAV, PROPFIND, OPTIONS, HTTP methods, PUT upload, 方法探测]
category: weakness-recognition
last_reviewed: 2026-06-28
maturity: seed
signatures: ["propfind", "webdav", "dav:", "ms-author-via", "allow: put", "allow: delete"]
---

<!--
PUBLIC grounding tier. Generic recognition of WebDAV and extended HTTP method
support — cross-product. Source: mokwon run-observation (WebDAV enabled on
ownCloud, student:12345678 → course materials), DVWA run-observation (PUT method
on upload paths).
-->

## Recognition (identification only)

- Signature (WebDAV): response to `OPTIONS` includes `PROPFIND`, `PROPPATCH`,
  `MKCOL`, `COPY`, `MOVE`, `LOCK`, `UNLOCK` in the `Allow` or `DAV` header.
- Signature (WebDAV paths): `/webdav/`, `/dav/`, `/remote.php/webdav/`
  (ownCloud/Nextcloud), `/dav.php/` (SabreDAV), `/_dav/`.
- Signature (generic method support): `OPTIONS` on a path returns `Allow: PUT`,
  `Allow: DELETE`, `Allow: PATCH` — extended write methods beyond GET/POST.
- Signature (Microsoft WebDAV): `MS-Author-Via` header, `Microsoft-WebDAV` or
  `MiniRedir` in response, IIS WebDAV module on `/` with `PROPFIND` enabled.
- Signature (ownCloud/Nextcloud): `/remote.php/webdav/` path, SabreDAV powered,
  `OC-Checksum` header, `OC-FileId` header.
- Distinguishing notes: `Allow: GET, HEAD, POST` is standard, not WebDAV.
  Only flag when extended methods (PUT/DELETE/PROPFIND) are present. A 405
  Method Not Allowed on PUT is secure, not a finding.

## Weak-Point Anchors

- Anchor: WebDAV methods accessible without authentication
  - Affected: WebDAV-enabled directories with no access control on PROPFIND
    and GET methods.
  - Mechanism: PROPFIND returns directory listing in XML format (more detailed
    than Apache/Nginx autoindex — includes file sizes, dates, resource types);
    GET allows reading any file in the listing. Combined, this enables
    unauthenticated data access.
  - Reference: CWE-306 (Missing Authentication)
  - source: run-observation (mokwon — WebDAV access to course materials)
- Anchor: PUT method allowed → unauthenticated file write
  - Affected: directories where PUT is allowed without authentication.
  - Mechanism: an unauthenticated PUT request can create or overwrite files on
    the server; if combined with a parseable extension or server-side includes,
    this leads to code execution.
  - Reference: CWE-434 (Unrestricted File Upload) + CWE-306
  - source: external-cited
- Anchor: TRACE method enabled → XST (Cross-Site Tracing)
  - Affected: servers where TRACE method is enabled.
  - Mechanism: TRACE echoes back the full request including headers; combined
    with XSS, an attacker can read HttpOnly cookies via the TRACE reflection.
  - Reference: CWE-200; known XST attack class (historical, modern browsers
    block TRACE via XMLHttpRequest, but still a config-hygiene signal)
  - source: external-cited

## Verification Principle

- Existence proof: an OPTIONS response listing WebDAV methods (PROPFIND, MKCOL,
  etc.) in the Allow or DAV header confirms WebDAV is enabled. A subsequent
  GET on the same path returning normal content (not 401/403) suggests the
  methods may be available without authentication.
- Hard stops: observe which extended methods are advertised and whether the path
  requires authentication. Do NOT upload files, create directories, or download
  files via WebDAV in autonomous mode (file creation and data access are
  guard-managed).

## False-Positive / Confounders

- OPTIONS returning 200 with Allow headers is normal (server capability
  advertisement) — the question is whether the listed methods actually work
  on an unauthenticated request, not whether they're advertised.
- PROPFIND returning 401/403 is correct hardening — not a finding.
- Some load-balancers respond to OPTIONS independently of the backend;
  verify the actual method support with a real PROPFIND or PUT request.
- WebDAV is intentionally enabled for legitimate file-sharing use cases —
  the finding is in missing access control, not the protocol's presence.

## References

- WebDAV RFC 4918: https://datatracker.ietf.org/doc/html/rfc4918
- OWASP: Testing for HTTP Methods (https://owasp.org/www-project-web-security-testing-guide/)
- This repo's run-observation: mokwon (ownCloud WebDAV with weak credentials)
- Related: [[directory-listing]] [[backup-config-discovery]]
