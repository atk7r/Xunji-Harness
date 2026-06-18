---
id: sangfor-ssl-vpn
product: Sangfor SSL VPN
vendor: 深信服 Sangfor
aliases: [深信服SSL VPN, EasyConnect, svpn, 深信服远程接入]
category: device
last_reviewed: 2026-06-12
maturity: seed
signatures: ["/por/login_auth.csp", "/por/login_psw.csp", "<twfid>", "svpntool"]
---

<!--
Grounding knowledge, not a weapon. Recognition + weak-point anchors (class +
mechanism + reference) + proof-only principle. No payloads / steps / PoC.
Source: <run> run-observation fingerprints + public disclosure (external-cited).
-->

## Recognition (identification only)

- Signature: login paths `/por/login_psw.csp` (password login), `/por/login_cert.csp`, `/por/login_token.csp` —
  the `/por/*.csp` route family is a strong fingerprint of the Sangfor SSL VPN.
- Signature: `GET /por/login_auth.csp` returns XML containing tags `<TwfID>` (session token), `<RndImg>` (captcha
  toggle), `<Anonymous>` (anonymous-login toggle), `<StartAuth>`. This XML shape is a unique Sangfor identifier.
- Signature: the login page carries a version string like `M7.xRy` (e.g. M7.1R1) and the `svpntool` client, plus an
  RSA public key (`EncryptKey` modulus + `EncryptExp` exponent 65537) used to encrypt the password login.
- Distinguishing notes: what separates it from other domestic VPNs (Venustech appframe, Huawei/H3C) is `/por/` +
  `.csp` + the `<TwfID>` XML of `login_auth.csp`; a "VPN / user login" title alone is not enough.

## Weak-Point Anchors (variant-analysis input — NOT exploit steps)

- Anchor: an internet-exposed older SSL VPN gateway is itself a high-risk surface
  - Affected: older firmware ranges like M7.x, directly exposed to the internet
  - Mechanism: a VPN gateway is an internal-boundary device reachable without credentials; once compromised it yields
    an internal entry point, and older firmware has several publicly-disclosed unauth flaw classes
  - Reference: Sangfor SRC https://sec.sangfor.com.cn/ ; CNCERT 2020 Sangfor SSL VPN security incident notice
  - source: external-cited
- Anchor: unauthenticated command execution / system file read flaw classes
  - Affected: affected firmware branches (specific versions per the vendor advisory)
  - Mechanism: some older firmware has command-concat or path-handling flaws on unauthenticated interfaces, triggerable
    without credentials
  - Reference: CNVD search "深信服 SSL VPN" https://www.cnvd.org.cn/ ; exact IDs vary by firmware branch, determined
    after the driver verifies the live build
  - source: driver-reasoning
- Anchor: authentication-logic flaw / authz-bypass classes
  - Affected: affected firmware branches
  - Mechanism: historical disclosures include bypass or authz-login auth-logic issues; if the anonymous-login toggle
    (`<Anonymous>`) is enabled it also widens the unauth surface
  - Reference: CNVD/CNNVD Sangfor entry search
  - source: external-cited

## Verification Principle (existence proof)

- Existence proof: the `<TwfID>` XML fingerprint of `/por/login_auth.csp` + the `M7.xRy` version string on the login
  page confirms "device identity and version exposure". Read `<Anonymous>`/`<RndImg>` for the anonymous/captcha toggles.
- Hard stops (per the proof boundary — confidentiality/availability/integrity): auto-execution stops at fingerprint and
  version identification; do **not** auto-send RCE, do **not** auto-login, do **not** auto-read system files, do **not**
  touch availability. Weaponized exploitation is cross-web-layer, operator-gated, author-and-handoff.

## False-Positive / Confounders

- A honeypot / simulated VPN login page can replicate the `/por/login_psw.csp` look; cross-confirm with the `<TwfID>`
  XML of `login_auth.csp` and the version string to avoid being misled by a static simulated page.
- A different port on the same host may be the management plane (often filtered/separate); do not treat the user-plane
  version as the management-plane version.

## References

- https://sec.sangfor.com.cn/ (Sangfor SRC)
- https://www.cnvd.org.cn/ (search "深信服 SSL VPN")
- This repo's run-observation: runs/<run>/ evidence E-010 (a real host = M7.1R1)
