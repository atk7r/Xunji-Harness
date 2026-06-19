---
id: synjones-ecard
product: Synjones 新中新 一卡通 (campus card / e-card)
vendor: 新中新 Synjones
aliases: [synjones, 新中新, 一卡通, ecard, ykt]
category: campus-card-platform
last_reviewed: 2026-06-20
maturity: seed
signatures: ["welcome to synjones", "synjones"]
---

<!-- PUBLIC grounding tier. Recognition + weak-point anchors only; no payloads. -->

## Recognition (identification only)

- Signature: vendor default landing page titled "Welcome to Synjones!" (nginx-default style 35em body)
  served at the host root; the real app lives on a sub-path (e.g. `/charge`, requiring auth).
- Distinguishing notes: the default page alone proves the vendor, not a reachable app; the app paths
  are usually auth-gated (401).

## Weak-Point Anchors (variant-analysis input — NOT exploit steps)

- Anchor: SQL injection / authentication-bypass flaw classes (historical)
  - Affected: various Synjones 一卡通 app interfaces in specific versions.
  - Mechanism: app interfaces historically concatenated parameters into SQL or had weak auth on
    selected endpoints; version-dependent.
  - Reference: CNVD search "新中新 / 一卡通 / Synjones"
  - source: external-cited
- Anchor: payment-adjacent business logic
  - Affected: the card/charge subsystem.
  - Mechanism: e-card systems touch balance/recharge flows.
  - Reference: run-observation (ujs `/charge` 401)
  - source: run-observation

## Verification Principle (existence proof)

- Existence proof: identify the vendor (Welcome to Synjones!), enumerate app paths, prove an unauth
  data-returning endpoint or an injection differential.
- Hard stops: **NEVER touch money/recharge/balance flows** (availability+integrity hard line); prove
  capability only, no transactions.

## False-Positive / Confounders

- The default page is a vendor stub; do not infer a reachable/vulnerable app from it alone.

## References

- https://www.cnvd.org.cn/ (search "新中新 一卡通 / Synjones")
