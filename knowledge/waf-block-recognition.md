---
id: waf-block-recognition
product: WAF block-behavior recognition and false-positive confounder
vendor: 安恒 / generic WAF
aliases: [WAF, 安恒云WAF, 网站防火墙, 拦截页识别, false-positive]
category: confounder
last_reviewed: 2026-06-12
maturity: seed
signatures: ["**********", "网站防火墙", "blocked payload"]
---

<!--
Grounding knowledge, not a weapon. This is a "recognition + confounder" entry: it helps
tell a WAF block apart from a real vulnerability, not a bypass manual. Source: <run>
run-observation. No payloads / steps / PoC.
-->

## Recognition (identification only)

- Signature: injecting a special character (e.g. a quote) triggers a **fixed small-size block response** (e.g. a 302 to
  a fixed block page, or a fixed 403 page), wildly different in size/hash from the normal business page and stable.
- Signature: a request with SQL keywords or a tautology signature triggers a block page or **a direct connection reset
  (RST/timeout)**.
- Signature: the block page body often **echoes the blocked payload/URL** (so block-page hashes can differ per payload,
  but they are all the same block template).
- Distinguishing notes: one WAF may protect multiple sites of the same organization — the **byte-identical same block
  page** appearing across several different hosts is a strong "shared WAF" signal.
- Signature (added from an engagement): **the `Server` response header is masked** (replaced with a string of asterisks
  like `**********`), a sign the gateway/WAF erases the backend fingerprint; often co-occurs with "shared across the org's
  multiple hosts".
- Signature (added from an engagement): **aggressive — the first malicious-signature request blocks the source IP**:
  benign requests pass 200, but the **first** request with a keyword/quote/scanner-signature path (e.g. `/_vti_bin/...`)
  causes **all subsequent requests from that source IP to be connection-refused (10061) / dropped**. A benign-vs-malicious
  control confirms this is a WAF/IPS blocking by **request signature**, not the port actually being closed.

## Weak-Point Anchors (variant-analysis input — NOT exploit steps)

- Anchor: WAF detection-coverage blind spot (by request method/location) flaw class
  - Affected: WAF deployments that only mount detection on part of the request surface (e.g. only inspect GET query, not
    POST body, or vice versa)
  - Mechanism: when the detection policy does not cover all input channels, the same parameter moved to an uninspected
    channel bypasses the WAF; this is variant-analysis input — whether it is "exploitable" still depends on whether the
    backend itself has a vuln
  - Reference: OWASP "Web Application Firewall Evasion" general principles; this repo's run-observation
  - source: run-observation
- Anchor: character-level encoding-normalization difference flaw class
  - Affected: deployments where the WAF and backend decode encodings (e.g. overlong UTF-8 / multibyte / double-encoding) inconsistently
  - Mechanism: the WAF and the app decode the same byte sequence to different results, possibly causing a miss or a
    false block; verify per-target, do not assume "bypassing the WAF = reaching the vuln"
  - Reference: OWASP encoding-normalization topic; this repo's run-observation
  - source: driver-reasoning

## Verification Principle (existence proof)

- Existence proof (recognizing the WAF, not a vuln): putting a special character into **any parameter/location** triggers
  the same block response — that proves the response comes from the WAF (global character block), not the app/DB.
- **Key confounder discipline**: a WAF block response (302/403/RST/fixed page) is **not** a DB error, **not** evidence of a
  vuln. After bypassing the WAF to deliver the character to the app, you still need a controlled boolean/differential with
  **multiple samples** to confirm the backend really has a vuln — bypassing the WAF ≠ the vuln exists.
- Hard stops: only do recognition and de-noising; do not escalate the de-noising technique into destructive testing of production.

## False-Positive / Confounders

- This entry itself exists to dissolve false positives: the lib `tsg_list.asp?sid` and www `nyshow.asp?sxid`
  "quote→302 / keyword→RST" were once suspected to be injection; after discrimination they were confirmed to be WAF
  character blocking; after bypassing the WAF to the app, the backend safely escapes the quote, **no injection** (runs/<run>
  evidence E-009 / E-013 / E-014).
- Multi-IP load balancing / dynamic content make response length naturally fluctuate; any "difference" must first be
  confirmed stable by **multiple samples per side** before judging (probe.py DIFF `--samples` is for this).
- A block-page hash differs because it echoes the payload — do not take that as "the response changes with the injection".
- **[Most error-prone] a single-IP rate-limit you triggered yourself ≠ a whole-site block of the target** (engagement
  E-010 lesson): after many consecutive requests, a connection-refused (10061)/timeout appears — do **not** directly judge
  "the target WAF blocked my source IP site-wide". A control is mandatory: (a) is a host **on a different hosting IP** still
  reachable? (b) is an **unrelated public site** still reachable? If they still return 200 → it is **your own request
  volume triggering the [per-IP rate limit] of the few IPs you hammered**, which is temporary and cools down — it is **not**
  a site-wide block, and **certainly not** "those IPs have no attack surface". An engagement once mis-recorded this as
  "site-wide block certainty 1.0", refuted by the E-011/E-013 control experiments. **Before assigning high certainty to any
  "blocked" conclusion, do this per-IP control first.**
- "App-layer weak authz (unauthenticated data return)" and "WAF presence" are **two different things**: a site with an
  aggressive WAF may still have app-layer interfaces leaking unauthenticated (the engagement's zero-trust IAM was exactly
  like this) — the WAF blocks malicious signatures, while benign interface enumeration still finds things.

## References

- OWASP: Web Application Firewall / WAF Evasion general principles
- This repo's run-observation: runs/<run>/ E-009 / E-013 / E-014 (character block + GET-only blind spot);
  runs/<run>/ E-010 / E-011 / E-013 (per-IP self-rate-limit misjudgment + masked server + aggressive IP block)
- Related [[zfsoft-jwgl]] [[vsb-cms]] [[wisedu-ecampus]] [[ida-zerotrust-iam]]
