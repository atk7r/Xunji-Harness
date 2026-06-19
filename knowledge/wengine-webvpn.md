---
id: wengine-webvpn
product: WebVPN (wengine / WRDVPN path-rewriting proxy)
vendor: 网瑞达 WRD / wengine
aliases: [wengine, wrdvpn, webvpn, wengine_vpn_ticket]
category: webvpn-proxy
last_reviewed: 2026-06-20
maturity: seed
signatures: ["wengine_vpn_ticket", "wrdvpn", "/webvpn/urlgen", "wengine"]
---

<!-- PUBLIC grounding tier. Recognition + weak-point anchors only; no payloads. -->

## Recognition (identification only)

- Signature: `Set-Cookie: wengine_vpn_ticket<host>=...`; root 302 → `/login`; proxied URLs of the form
  `https://<webvpn>/http(s)/<hex-blob>/...`; a URL encoder at `/webvpn/urlgen/?url=`.
- Signature: the hex blob in proxied paths is the target host encrypted with the PUBLIC hardcoded key
  `wrdvpnisthebest!` (hex prefix `7772647670...`).
- Distinguishing notes: path-rewriting WebVPN (one host fronts many internal apps), distinct from
  SSL-VPN appliances (Sangfor etc.).

## Weak-Point Anchors (variant-analysis input — NOT exploit steps)

- Anchor: pre-auth URL encoder + public hardcoded key
  - Affected: `/webvpn/urlgen/?url=` accepts arbitrary URLs (incl. internal/loopback) with no allowlist.
  - Mechanism: the host is encrypted with a public static key, so proxied URLs to ANY internal host are
    constructable client-side. NOTE: reaching the proxied URL still requires a session in a hardened
    deployment (302 → /login when unauth) — so this is an info/encoder exposure, not pre-auth SSRF, unless
    the proxy serves without a ticket.
  - Reference: public wengine/WRDVPN write-ups (hardcoded `wrdvpnisthebest!` key)
  - source: external-cited
- Anchor: authenticated internal-network pivot (post-auth)
  - Affected: any internal host reachable through the proxy once authenticated.
  - Mechanism: a WebVPN proxies the internal network; with a valid ticket the urlgen+proxy becomes a
    broad internal-access pivot.
  - Reference: run-observation (ujs_20260619 E-022)
  - source: run-observation

## Verification Principle (existence proof)

- Existence proof: confirm `wengine_vpn_ticket` + urlgen behavior; test whether the proxy serves a
  proxied internal URL WITHOUT a session (pre-auth SSRF) vs bounces to /login (auth-gated).
- Hard stops: do NOT mass-scan the internal network through the proxy (availability line); one reach
  proves the capability.

## False-Positive / Confounders

- urlgen returning an encoded URL ≠ access; the access test is fetching the proxied URL unauth.

## References

- public wengine / WRDVPN WebVPN technical write-ups (hardcoded encoding key)
