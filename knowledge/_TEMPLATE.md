---
id: replace-with-local-id
product: replace-with-product
vendor: replace-with-vendor
aliases: []
category: replace-with-category
last_reviewed: YYYY-MM-DD
maturity: seed
signatures: []
---

<!-- Local-only grounding entry. Do not stage or publish populated copies. -->

## Recognition (identification only)

- Signature: <observable product marker>
- Distinguishing notes: <how to reject lookalikes>

## Weak-Point Anchors (reasoning input, not exploit steps)

- Anchor: <precise weakness class>
  - Affected: <version or configuration condition>
  - Mechanism: <why the condition matters>
  - Reference: <primary advisory or first-hand evidence>
  - source: <primary-source or run-observation>

## Verification Principle (existence proof)

- Existence proof: <minimal observation that supports the hypothesis>
- Hard stops: <effects that require separate authorization>
- Required control: <obvious alternate explanation to rule out>

## False-Positive / Confounders

- <normal behavior, proxy response, WAF page, redirect, or version ambiguity>

## References

- <primary source>

## Local Notes

- Keep target identifiers, credentials, payloads, request bodies, PoCs, internal
  paths, and engagement artifacts outside grounding entries.
