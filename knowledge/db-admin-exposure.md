---
id: db-admin-exposure
product: Database administration tool and management interface exposure
vendor: cross-product
aliases: [phpmyadmin, adminer, pgadmin, mongoexpress, rediscommander, 数据库管理, DB管理暴露]
category: weakness-recognition
last_reviewed: 2026-06-28
maturity: seed
signatures: ["/phpmyadmin/", "/adminer", "/pgadmin", "/phpPgAdmin", "/rockmongo", "/mongo-express"]
---

<!--
PUBLIC grounding tier. Generic recognition of database administration tools
exposed at the web layer — cross-product, covers MySQL/MariaDB, PostgreSQL,
MongoDB, Redis tools. Source: mokwon run-observation (phpMyAdmin at webroot
accessible after credential discovery), tongda_oa run (MySQL 3336 open).
-->

## Recognition (identification only)

- Signature (MySQL/MariaDB): `/phpmyadmin/`, `/phpMyAdmin/`, `/pma/`,
  `/mysql/`, `/adminer.php`, `/adminer/` (single-file DB manager, common
  in Chinese deployments), `/chive/`.
- Signature (PostgreSQL): `/phppgadmin/`, `/pgadmin/`, `/pgadmin4/`,
  `/adminer.php?pgsql=`.
- Signature (MongoDB): `/rockmongo/`, `/mongo-express/`, `/adminMongo/`,
  `/mongoui/`; also NoSQLBooster/Studio3T connection banners on exposed
  MongoDB ports.
- Signature (Redis): `/redis-commander/`, `/phpredmin/`, `/redisadmin/`;
  also direct Redis response on `redis-cli PING` → `+PONG` on port 6379
  (non-HTTP, but reconnaissance-significant).
- Signature (generic): `/db/`, `/database/`, `/sql/`, `/backup/` (SQL dump
  files: `.sql`, `.sql.gz`, `.dump`), `/export/`.
- Distinguishing notes: a 200 on `/phpmyadmin/` with the phpMyAdmin login
  page is the tool present; if credentials are discovered elsewhere
  (config backup, log file) the attacker has direct DB access. The web tool
  existing without auth (some old Adminer deployments) is CRITICAL.

## Weak-Point Anchors

- Anchor: database admin tool at predictable path with weak/no auth
  - Affected: deployments where phpMyAdmin/Adminer is installed at default
    path and either has no additional auth layer or uses default credentials.
  - Mechanism: the tool provides full SQL execution, file read/write (MySQL
    `SELECT ... INTO OUTFILE`, `LOAD_FILE`), and sometimes server command
    execution — direct database takeover from the browser.
  - Reference: CWE-200 + CWE-306 (Missing Authentication)
  - source: run-observation (mokwon — phpMyAdmin in webroot, accessed after
    discovering credentials from config.php~)
- Anchor: SQL dump file in webroot
  - Affected: deployments where database backups (`.sql`, `.dump`) are stored
    in web-accessible directories.
  - Mechanism: the dump file contains the full database schema + all data in
    plaintext SQL; no tool needed — just download via GET.
  - Reference: CWE-530
  - source: driver-reasoning
- Anchor: Redis/MongoDB without authentication on public interface
  - Affected: NoSQL databases bound to 0.0.0.0 without `requirepass` (Redis)
    or `--auth` (MongoDB).
  - Mechanism: Redis without auth → `CONFIG SET dir /var/www/html` + `CONFIG
    SET dbfilename shell.php` → webshell via Redis protocol. MongoDB without
    auth → full database dump via `mongoexport` equivalent.
  - Reference: CWE-306; public Redis/MongoDB exposure incidents
  - source: external-cited

## Verification Principle

- Existence proof: GET the management tool path → 200 with login page confirms
  the tool is present. If auth is required, presence alone is LOW (config
  hygiene). If no auth → CRITICAL (direct DB access). For command-line
  databases (Redis/MongoDB), a non-HTTP connection attempt confirming open
  port + protocol response is the existence proof.
- Hard stops: confirm the tool/port is accessible. Do NOT attempt login
  (even with default creds) — authentication attempt = crossing proof
  boundary into access. If credentials are already discovered from a
  separate finding (config backup), record the chain potential but do not
  autonomously combine them on the live target.

## False-Positive / Confounders

- A 403 Forbidden on `/phpmyadmin/` is hardened, not a finding.
- A redirect to a different host or a WAF block page at the path is not
  evidence of the tool being present.
- Some CMS (WordPress, Drupal) ship their own DB management interfaces —
  distinguish those from standalone tools.
- Redis/MongoDB bound to 127.0.0.1 only (not publicly accessible) is the
  secure default — do not report as a finding.

## References

- CWE-306: Missing Authentication for Critical Function
- OWASP: administrative interface exposure
- This repo's run-observation: mokwon (phpMyAdmin in webroot);
  tongda_oa (MySQL port 3336 remote root access)
- Related: [[backup-config-discovery]] [[error-disclosure-signatures]]
