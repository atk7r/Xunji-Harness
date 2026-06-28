---
id: backup-config-discovery
product: Backup and configuration file exposure patterns
vendor: cross-product
aliases: [backup files, config leak, source disclosure, 备份文件, 配置文件泄露]
category: weakness-recognition
last_reviewed: 2026-06-28
maturity: seed
signatures: ["config.php~", "config.php.bak", ".git/HEAD", ".env", "web.config.bak", ".DS_Store", "package.json"]
---

<!--
PUBLIC grounding tier. Generic recognition of backup/config file exposure patterns —
cross-product, not tied to any single app. Source: mokwon run-observation (ownCloud
config.php~ → DB credentials), tongda_oa run-observation (Service.ini plaintext).
No payloads. Driver checks the live target for these paths; existence ≠ vuln until
content proves sensitive data exposure.
-->

## Recognition (identification only)

- Signature: editor/version-control backup extensions — `file~` (vim/gedit), `file.bak`,
  `file.old`, `file.swp`, `file.save`, `file.orig`, `file.tmp`.
- Signature: version-control metadata — `/.git/HEAD` (200 = git repo exposed),
  `/.svn/entries`, `/.hg/store`, `/.bzr/`.
- Signature: framework config files — `/.env` (Laravel/Symfony), `/config.php~`,
  `/config.php.bak`, `/wp-config.php~` (WordPress), `web.config.bak` (IIS/ASP.NET),
  `settings.py.bak`, `application.properties.bak` (Spring), `Service.ini` (通达OA).
- Signature: system artifacts — `/.DS_Store` (macOS, leaks directory structure),
  `Thumbs.db` (Windows), `desktop.ini`.
- Signature: package manifests — `package.json` (Node.js deps + scripts),
  `composer.json` (PHP deps), `Gemfile` (Ruby), `requirements.txt` (Python),
  `pom.xml` (Java/Maven) — not secrets per se, but version intel.
- Distinguishing notes: a 200 on `.git/HEAD` is high-signal (full repo likely
  cloneable); a 200 on `config.php~` means the PHP interpreter does NOT process
  the `~` extension → source disclosed. A 403 on these paths is normal hardening,
  not a finding.

## Weak-Point Anchors (variant-analysis input — NOT exploit steps)

- Anchor: backup file discloses secrets (credentials / keys / connection strings)
  - Affected: any deployment where editor backups or "copy before edit" files are
    left in webroot and the server serves them as static text.
  - Mechanism: the file extension is not processed by the app server (`.php~` is
    not PHP; `.bak` is not ASPX), so the source is served verbatim. Credentials in
    these files grant direct database/API access.
  - Reference: CWE-530 (backup file exposure), CWE-538 (file disclosure)
  - source: run-observation + external-cited
- Anchor: version-control metadata enables source reconstruction
  - Affected: deployments where `.git/` is web-accessible.
  - Mechanism: `/.git/HEAD` → ref → `/.git/objects/` walkable → full source
    reconstruction; also reveals `/.git/config` (remote origin + credentials
    sometimes).
  - Reference: public git-exposure tools (git-dumper class)
  - source: external-cited
- Anchor: system artifact leaks internal paths / directory structure
  - Affected: macOS `.DS_Store` files in webroot.
  - Mechanism: `.DS_Store` is a binary plist of directory contents; reveals
    hidden directories and file names not linked from any page.
  - Reference: CWE-548 (directory listing via exposed file)
  - source: driver-reasoning

## Verification Principle (existence proof)

- Existence proof: a GET to the path returns 200 with file content (not a redirect /
  login page / empty body). If the content contains credentials/secrets → confirmed
  info leak. If the content is only version numbers / harmless config → low-severity
  config hygiene.
- Hard stops: confirm the file is accessible and review its content for secrets.
  Do NOT use discovered credentials to access databases/APIs in autonomous mode
  (that crosses into data access — operator-gated). Do NOT attempt git clone of
  exposed repos (operator-gated bandwidth + data exfil).

## False-Positive / Confounders

- A 200 with a login page / CMS front page (soft-404) is NOT file exposure —
  verify the response body actually contains config syntax or git objects.
- A 403 Forbidden is normal hardening, not a finding.
- `composer.json` / `package.json` existing and readable is low-severity at most
  (dependency version disclosure), not a critical finding on its own.
- Some frameworks ship default config files that are intentionally public
  (e.g. `config.sample.php`) — distinguish sample from actual config.

## References

- CWE-530: Exposure of Backup File to an Unauthorized Control Sphere
- CWE-538: Insertion of Sensitive Information into Externally-Accessible File or Directory
- This repo's run-observation: mokwon E-010 (ownCloud config.php~ → DB credentials);
  tongda_oa run (Service.ini → MySQL root password)
- Related: [[tech-stack-fingerprint]] [[error-disclosure-signatures]]
