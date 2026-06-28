---
id: directory-listing
product: Web server directory listing and index exposure
vendor: cross-product
aliases: [directory listing, autoindex, 目录遍历, 目录列表, open directory]
category: weakness-recognition
last_reviewed: 2026-06-28
maturity: seed
signatures: ["Index of /", "Directory Listing", "To Parent Directory", "<title>index of", "autoindex on"]
---

<!--
PUBLIC grounding tier. Generic recognition of directory listing (web server
auto-index) — Apache mod_autoindex, Nginx ngx_http_autoindex_module, IIS
directory browsing. Source: mokwon run-observation (Apache directory listing
enabled ownCloud config/ → backup file discovery), multiple runs.
-->

## Recognition (identification only)

- Signature (Apache): `<title>Index of /path</title>`, `Parent Directory`,
  `<address>Apache/X.Y.Z Server at host Port N</address>`, file-size column.
- Signature (Nginx): same `Index of /` title but footer says `nginx/X.Y.Z`.
- Signature (IIS): table-based listing with column headers "Name / Last
  Modified / Size", no "Parent Directory" link (uses breadcrumb instead);
  IIS version in response headers.
- Signature (generic): a GET on a directory path (trailing `/`) returns a
  page listing files/directories instead of the default index page (index.html,
  index.php, etc.). Key: the body is an HTML file listing, not the app UI.
- Signature (JSON API directory): some apps return JSON directory listings
  (e.g., `/api/files/` returning `["file1", "file2"]`).
- Distinguishing notes: directory listing ≠ the app's normal file-browser
  UI (like a CMS media library). The tell is: no app chrome/header/sidebar,
  just a raw HTML table of files. Apache's `<address>` footer is the most
  reliable marker.

## Weak-Point Anchors

- Anchor: directory listing exposes sensitive files not linked anywhere
  - Affected: any web server with autoindex enabled on directories containing
    configs, backups, logs, or uploads.
  - Mechanism: the listing reveals files that are never referenced by the
    application (config.php, database.sql.gz, backup_2024.tar.gz, error.log).
    These files are otherwise invisible to reconnaissance. In mokwon, the
    ownCloud `/config/` listing showed `config.php~` which was then downloaded.
  - Reference: CWE-548 (Exposure of Information Through Directory Listing)
  - source: run-observation (mokwon E-009 — config/ directory listing
    exposing config.php, config.sample.php)
- Anchor: directory listing + executable backup files = source disclosure
  - Affected: PHP/ASP.NET deployments with editor backup files in listed
    directories.
  - Mechanism: the listing shows `file.php~` or `file.aspx.bak`; accessing
    these returns source code (not executed by the interpreter). Combined
    with directory listing, this is a two-step recon-to-exploit path without
    any brute-force guessing.
  - Reference: CWE-530 + CWE-548 combined
  - source: run-observation
- Anchor: directory listing on upload/media directories
  - Affected: `/uploads/`, `/attachments/`, `/media/`, `/files/`,
    `/userfiles/` with autoindex enabled.
  - Mechanism: reveals every file ever uploaded, including files that were
    "private" or unlisted in the app UI. Combined with an upload vuln, shows
    the attacker's own files in the listing (confirms upload worked).
  - Reference: CWE-548
  - source: driver-reasoning

## Verification Principle

- Existence proof: a GET on a common directory path (`/uploads/`, `/config/`,
  `/backup/`, `/admin/`, `/includes/`) returns an HTML file listing (not the
  app UI, not a 404, not a redirect). Cross-confirm with the server footer
  (Apache/Nginx/IIS). Classify severity by what is exposed: empty media
  directory = INFO, config directory with config.php = HIGH.
- Hard stops: confirm listing exists and identify exposed file types. Do NOT
  download every file in the listing (data exfiltration). Downloading a single
  config file to verify source disclosure is proof-level if the file content
  is config syntax (not user data).

## False-Positive / Confounders

- A CMS "file manager" or "media library" page that lists files within the
  app's admin UI is NOT directory listing — it's the app's intended feature
  (may be an auth issue, but not a server config issue).
- A 403 Forbidden on a directory path is the secure default, not a finding.
- Some sites return a soft-404 (200 with a "not found" message) — verify
  the body actually contains a file table.
- WebDAV PROPFIND returning an XML directory listing is a different protocol
  — see WebDAV-specific assessment.

## References

- CWE-548: Exposure of Information Through Directory Listing
- Apache: mod_autoindex documentation
- This repo's run-observation: mokwon E-009 (ownCloud /config/ directory
  listing exposing config files + backup)
- Related: [[backup-config-discovery]] [[error-disclosure-signatures]]
