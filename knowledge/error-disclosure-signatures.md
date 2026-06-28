---
id: error-disclosure-signatures
product: Error message and debug information disclosure patterns
vendor: cross-product
aliases: [stack trace, verbose error, debug mode, 报错信息泄露, customErrors, DB error]
category: weakness-recognition
last_reviewed: 2026-06-28
maturity: seed
signatures: ["stack trace", "debug mode", "customerrors", "tracerdroute", "trace.axd", "phpinfo", "detailed error"]
---

<!--
PUBLIC grounding tier. Generic recognition of error/disclosure patterns across
tech stacks — .NET yellow-screen / customErrors, PHP errors/phpinfo, Java
stack traces, database error messages. Source: hamastar run-observation
(customErrors=Off), DVWA run-observation (phpinfo), mokwon run (log exposure).
-->

## Recognition (identification only)

- Signature (.NET/ASP.NET): `customErrors="Off"` or `mode="Off"` in error page
  source (yellow-screen-of-death); `/trace.axd` (ASP.NET tracing); verbose
  `NullReferenceException` with full source-path disclosure.
- Signature (PHP): `/phpinfo.php`, `/info.php`, `/test.php` returning
  `phpinfo()` output (PHP version, extensions, env vars, loaded ini);
  `display_errors=On` leaking DB credentials in connection-failure messages.
- Signature (Java): Spring Boot `/error` with `include-stacktrace: always`;
  Tomcat error-page revealing `Exception: ...\n\tat com.example... (Class.java:NNN)`
  with full internal package structure.
- Signature (database errors): SQL syntax error messages with table/column
  names; "transaction log full" errors (MSSQL) revealing database name +
  internal server name; connection-refused messages with internal host:port.
- Signature (generic): `/debug/`, `/test/`, `/dev/` paths left in production;
  verbose error in JSON wrapper (e.g. `{"msg":"SQLException: ...", "code":500}`);
  `.log` files in webroot (e.g. `error.log`, `app.log`, `debug.log`).
- Distinguishing notes: a 500 status is normal — what matters is whether the
  body contains exploitable detail (paths, SQL, credentials) or a generic
  "Internal Server Error" page.

## Weak-Point Anchors

- Anchor: stack trace discloses internal paths + framework versions
  - Affected: any production deployment with debug/verbose errors enabled.
  - Mechanism: error messages reveal the server filesystem layout, framework
    version, and package names; combined these identify the exact stack and
    its known vulnerabilities.
  - Reference: CWE-209 (Generation of Error Message Containing Sensitive Information)
  - source: run-observation (hamastar E-001/E-002, cqytxy)
- Anchor: phpinfo / info.php exposes full runtime configuration
  - Affected: PHP deployments where info files are left in webroot.
  - Mechanism: `phpinfo()` outputs PHP version, loaded extensions,
    `DOCUMENT_ROOT`, `SCRIPT_FILENAME`, env vars (sometimes including
    `DB_PASSWORD`), and `disable_functions` status — complete recon in one page.
  - Reference: CWE-200
  - source: run-observation (DVWA phpinfo)
- Anchor: database error with table/column names
  - Affected: apps that do not suppress DB exceptions in production.
  - Mechanism: "Unknown column 'foo' in 'where clause'" reveals the real table
    schema; "transaction log for database 'XYZ_DB' is full" reveals the internal
    database name; MSSQL errors with server name enable internal-network mapping.
  - Reference: CWE-209
  - source: run-observation (hamastar E-002/E-007)
- Anchor: log files in webroot
  - Affected: deployments where application/debug logs are written to webroot
    without access restriction.
  - Mechanism: log files often contain usernames, internal IPs, file paths,
    stack traces, and sometimes credentials from failed login attempts with
    debug logging.
  - Reference: CWE-532 (Insertion of Sensitive Information into Log File)
  - source: run-observation (mokwon E-014 — owncloud.log 1.5MB with usernames)

## Verification Principle

- Existence proof: a request that triggers an error (invalid param, bad auth)
  returns a response body containing stack-trace/internal-path/DB-schema
  information. Classify by what is disclosed: paths-only = LOW, DB schema
  = MEDIUM, credentials in error = HIGH.
- Hard stops: trigger an error via a harmless invalid input; do NOT send
  payloads designed to maximize damage (e.g., SQLi payload to read tables via
  error). The goal is to see IF the app leaks errors, not to extract data.

## False-Positive / Confounders

- A generic "500 Internal Server Error" with empty body is NOT disclosure.
- A custom error page that says "An error occurred" without technical detail
  is CORRECT hardening — not a finding.
- `customErrors="RemoteOnly"` (default in ASP.NET) may show detail to
  localhost only — but the proxy or load-balancer can make the server see
  all requests as local. Check what you actually receive.
- `phpinfo()` may be intentionally left for monitoring — but still a
  config-hygiene finding in production (LOW at most).

## References

- CWE-209: Generation of Error Message Containing Sensitive Information
- CWE-200: Exposure of Sensitive Information
- OWASP: Improper Error Handling
- This repo's run-observation: hamastar E-001 (NullReferenceException +
  source path), E-002 (MSSQL transaction log full + server name); mokwon
  E-014 (owncloud.log with usernames + internal IPs)
- Related: [[backup-config-discovery]] [[tech-stack-fingerprint]]
