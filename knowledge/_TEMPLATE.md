---
id: kebab-case-id            # filename matches this id
product: Product Name
vendor: Vendor
aliases: [alias1, alias2]
category: short-category     # e.g. cms | framework-management-endpoint | device
last_reviewed: YYYY-MM-DD
maturity: seed               # seed | verified | stale
---

<!--
This file is grounding knowledge, not a weapon. See knowledge/README.md.
Allowed: recognition signatures, weak-point anchors (class + mechanism +
reference), safe-verification principles. Forbidden: payloads, exploit chains,
request bodies, step-by-step PoC, scanner rules, blind checklists.
Every anchor needs a source. "Found nothing verifiable" beats inventing.
-->

## Recognition (identification only)

- Signature: <path / response header / body marker / favicon hash / default
  behavior that identifies this product>
- Signature: <...>
- Distinguishing notes: <what separates it from look-alikes; what would be a
  false match>

## Weak-Point Anchors (variant-analysis input — NOT exploit steps)

Each anchor = weakness CLASS + affected scope + mechanism (why it is weak) +
reference + source class. No payloads. No steps. The driver derives the specific
check for the live target itself.

- Anchor: <weakness class, e.g. "sensitive management endpoint exposure">
  - Affected: <versions / config conditions>
  - Mechanism: <one or two sentences — conceptual, why this is weak>
  - Reference: <CVE-xxxx-xxxxx / CNVD-xxxx-xxxxx / advisory URL>
  - source: external-cited | run-observation | driver-reasoning

## Safe-Verification Principle (harmless confirmation)

- Existence proof: <what "the weakness exists" looks like here — presence, not
  impact>
- Hard stops (per the harmless-verification boundary — confidentiality /
  availability / integrity): <e.g. confirm endpoint identity only; do NOT pull
  data bytes, extract secrets, RCE, tamper, or dump>

## False-Positive / Confounders

- <what mimics the recognition signature: decoy, honeypot, gateway stub,
  unrelated tech — ties to cognition Attribution Checks>

## References

- <primary, clickable URL: NVD / CNVD / CNNVD / vendor advisory>
