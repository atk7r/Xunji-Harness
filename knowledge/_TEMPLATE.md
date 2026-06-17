---
id: kebab-case-id            # filename matches this id
product: Product Name
vendor: Vendor
aliases: [alias1, alias2]
category: short-category     # e.g. cms | framework-management-endpoint | device
last_reviewed: YYYY-MM-DD
maturity: seed               # seed | verified | stale
signatures: ["sig1", "sig2"] # 机器可匹配的小写 substring; classify_hosts 据此识别【已入库】产品(飞轮读取端)
---

<!--
This is the PUBLIC grounding tier (ships to GitHub). See knowledge/README.md.
Allowed here: recognition signatures, weak-point anchors (class + mechanism +
reference), proof-only verification principles. Payloads / exploit chains / PoC
go in the gitignored knowledge/weaponized/ tier, NOT here. Use any knowledge as a
reasoning attacker (look up after fingerprint, adapt, evidence-gate) — never as a
blind scanner. Every anchor needs a source. "Found nothing verifiable" beats inventing.
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

## Verification Principle (existence proof)

- Existence proof: <what "the weakness exists" looks like here — presence, not
  impact>
- Hard stops (per the proof boundary — confidentiality /
  availability / integrity): <e.g. confirm endpoint identity only; do NOT pull
  data bytes, extract secrets, RCE, tamper, or dump>

## False-Positive / Confounders

- <what mimics the recognition signature: decoy, honeypot, gateway stub,
  unrelated tech — ties to cognition Attribution Checks>

## References

- <primary, clickable URL: NVD / CNVD / CNNVD / vendor advisory>
