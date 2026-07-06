---
id: lumen
product: Lumen (Laravel micro-framework)
vendor: Laravel LLC
aliases: [Laravel Lumen, Lumen framework]
category: web-framework
last_reviewed: 2026-07-07
maturity: seed
signatures: ["Lumen (", "Laravel Components"]
---

<!--
SEED scaffold (knowledge_seed.py), filled. PUBLIC grounding tier — ships to GitHub.
Allowed: recognition signatures, weak-point anchors (class + mechanism + reference),
proof-only verification. NO payloads / exploit chains / PoC here.
-->

## Recognition (identification only)

- Signature: GET / returns plain-text `Lumen (<version>) (Laravel Components <ver>.*)` — the default Lumen root route handler. Observed: `Lumen (5.4.6) (Laravel Components 5.4.*)` on ossapihd.oppo.com (2026-07-07).
- Distinguishing notes: plain-text version banner at root is Lumen's default; full Laravel shows a different root. Framework 404 is a custom HTML page (no server banner in body). `Server: nginx` (reverse proxy → PHP-FPM) not distinctive alone. Banner version maps to release line: 5.4.* = 2017-era, **EOL** (Laravel deprecated Lumen after 5.7).

## Weak-Point Anchors (variant-analysis input — NOT exploit steps)

- Anchor: APP_KEY deserialization RCE (CVE-2018-15133) — deser/RCE
  - Affected: Laravel < 5.6.30 / 5.5.x < 5.5.40 (Lumen 5.4.* in scope); requires a LEAKED APP_KEY.
  - Mechanism: APP_KEY (base64) encrypts/serializes cookies + signed request data; the decryption path calls unserialize on attacker-controlled ciphertext when APP_KEY is known → forge an encrypted payload that unserialize()s into a PHP object-gadget chain → RCE. Without APP_KEY, NOT exploitable.
  - Reference: NVD CVE-2018-15133
  - source: primary-reference

- Anchor: version disclosure / EOL framework — infoleak/misconfig
  - Affected: any Lumen with default root route; 5.4.* = EOL (no security patches).
  - Mechanism: root banner discloses exact version → aids targeting known CVEs for the release line.
  - Reference: Lumen docs compatibility / new-project guidance
  - source: primary-reference

- Anchor: debug-mode / .env leak — misconfig/infoleak
  - Affected: APP_DEBUG=true OR /.env web-exposed.
  - Mechanism: APP_DEBUG=true → framework dumps a stack trace with env vars on any exception (JSON error body in Lumen; HTML whoops page in full Laravel). /.env served → full env file.
  - Reference: Laravel production hardening best-practices
  - source: run-observation

- Anchor: Ignition debug RCE (CVE-2021-3129) — debug/RCE
  - Affected: only when Ignition is installed in the app and debug mode is exposed; not a default Lumen assumption.
  - Mechanism: vulnerable Ignition file operations can become unauthenticated code execution on debug-exposed Laravel-family apps. Treat as a conditional lead after confirming Ignition/debug exposure, not from the Lumen banner alone.
  - Reference: NVD CVE-2021-3129
  - source: primary-reference

## Verification Principle (existence proof)

- Existence proof: GET / → `Lumen (...)` banner = framework identity + version. For CVE-2018-15133: confirm APP_KEY reachability FIRST (/.env 200, debug output renders APP_KEY, or log/vendor exposure). Without APP_KEY, the CVE is not exploitable — record version-disclosure LOW only. For CVE-2021-3129, first confirm Ignition and debug exposure; the Lumen banner alone is insufficient.
- Hard stops: proof-of-existence only — confirm framework + version + whether APP_KEY is reachable; do NOT extract APP_KEY values into the run dir, do NOT deserialize/RCE on the live target (author-and-handoff for any exploit).

## False-Positive / Confounders

- A reverse proxy could echo a static "Lumen (...)" string; confirm via a framework 404 (custom HTML, no server banner) + a Lumen-style error shape.
- Default "Hello World!" root (e.g. Spring/Tomcat) is a DIFFERENT framework — don't conflate with Lumen banner.

## References

- https://nvd.nist.gov/vuln/detail/CVE-2018-15133 (Laravel APP_KEY deser RCE)
- https://nvd.nist.gov/vuln/detail/CVE-2021-3129 (Ignition debug-mode RCE)
- https://lumen.laravel.com/docs (EOL notice: Lumen deprecated after 5.7)
