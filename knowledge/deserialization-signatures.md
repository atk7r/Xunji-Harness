---
id: deserialization-signatures
product: Deserialization weak-point recognition (Shiro / .NET ViewState / Fastjson-Jackson / native)
vendor: cross-product
aliases: [deser, shiro, rememberme, viewstate, fastjson, jackson, java-deser]
category: weakness-recognition
last_reviewed: 2026-06-20
maturity: seed
signatures: ["rememberme=deleteme", "__viewstate", "__viewstategenerator", "fastjson", "x-java-serialized-object"]
---

<!-- PUBLIC grounding tier. RECOGNITION of deser surface, surfaced when a signature appears in a saved
response (knowledge_match) — consulted on a hit, NEVER fired as a blind sweep. No payloads/gadgets. -->

## Recognition (identification only)

- Signature (Shiro): response `Set-Cookie` contains `rememberMe=deleteMe` after sending any
  `Cookie: rememberMe=<x>` — strong tell of Apache Shiro rememberMe handling.
- Signature (.NET ViewState): page body contains hidden `__VIEWSTATE` (+ `__VIEWSTATEGENERATOR`) —
  ASP.NET WebForms; deserializes the ViewState blob server-side.
- Signature (Fastjson/Jackson): JSON endpoints; error/behavior referencing `fastjson`/`autotype`, or a
  Jackson polymorphic-typing setup.
- Signature (native Java): `Content-Type: application/x-java-serialized-object`, or endpoints accepting
  serialized blobs (ac/ed/00/05 `rO0` base64 prefix).
- Distinguishing notes: these are CROSS-product signatures — pair them with the product fingerprint
  (e.g. weaver-emobile, a Spring app, an ASP.NET OA) before reasoning about exploitability.

## Weak-Point Anchors (variant-analysis input — NOT exploit steps)

- Anchor: Shiro rememberMe deserialization → RCE
  - Affected: Shiro with a default/leaked AES `rememberMe` key (CVE-2016-4437 class).
  - Mechanism: the rememberMe cookie is AES-encrypted then Java-deserialized; a known key enables a
    gadget-chain RCE. Pre-auth detectable (the deleteMe tell); exploitation needs the key + a gadget.
  - Reference: CVE-2016-4437
  - source: external-cited
- Anchor: .NET ViewState deserialization → RCE
  - Affected: ASP.NET with a leaked/known MachineKey, or `EnableViewStateMac=false` / no-MAC config.
  - Mechanism: ViewState is a deserialized object graph; with the validation/decryption key (or no MAC)
    a crafted ViewState yields RCE. Without the key it is NOT exploitable — flag as "candidate, needs key".
  - Reference: known ASP.NET ViewState deserialization (ysoserial.net class)
  - source: external-cited
- Anchor: Fastjson/Jackson autotype deserialization → RCE
  - Affected: vulnerable Fastjson autotype / Jackson polymorphic configs on JSON endpoints.
  - Mechanism: untrusted JSON instantiates attacker-chosen types; proof usually needs OOB (dnslog).
  - Reference: CVE-2022-25845 (Fastjson) and related
  - source: external-cited

## Verification Principle (existence proof)

- Existence proof: the SIGNATURE (deleteMe / __VIEWSTATE / autotype behavior) proves the surface is
  present; exploitability is gated by a key/gadget/OOB and is version/config-dependent.
- Hard stops: deser → RCE is deep exploitation = **authored-and-handed-off, never auto-run**. Auto-exec
  stays at signature recognition.

## False-Positive / Confounders

- `__VIEWSTATE` present with a strong MachineKey + MAC is not exploitable; Shiro deleteMe without a
  weak/known key is not exploitable. Recognition ≠ vulnerability — adjudicate per target.

## References

- https://nvd.nist.gov/ (CVE-2016-4437 Shiro; CVE-2022-25845 Fastjson)
