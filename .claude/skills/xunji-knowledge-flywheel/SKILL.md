---
name: xunji-knowledge-flywheel
description: Claude-driver guide for Xunji grounding knowledge use and writeback. Use when a live run recognizes a product fingerprint or kb-id tag, needs `knowledge_match.py` / `xday_match.py`, misses a clearly fingerprinted product and should seed knowledge, or must preserve the public grounding vs local weaponized tier boundary without becoming a checklist scanner.
---

# Xunji Knowledge Flywheel

This is the Claude-driver guide for Xunji's knowledge flywheel. The Root uses
knowledge after recognizing a live target technology, adapts it to the current
front, and writes back durable grounding when the base misses.

## Source Of Truth

Read these when exact behavior matters:

- `knowledge/README.md` for grounding vs weaponized tiers.
- `docs/cognition/README.md` "Grounding and Variant Analysis".
- `docs/WORKFLOW.md` for the Root-cycle lookup trigger.
- `tools/knowledge_match.py`, `tools/xday_match.py`, `tools/knowledge_seed.py`,
  and `tools/check_knowledge.py` for command behavior.
- `knowledge/_TEMPLATE.md` and `knowledge/_lexicon.md` when creating entries.

## Trigger

Use this skill only after a live observation grounds a technology:

- A saved body, title, banner, JS bundle, or UI identifies a product/framework.
- `classify_hosts` or `coverage.json` tags an asset as `kb:<id>`.
- A run artifact clearly fingerprints a product but `knowledge_match` misses.
- The operator asks whether a knowledge entry belongs in public grounding or
  local weaponized material.

Do not load the whole knowledge base at run start. A knowledge anchor is not a
finding.

## Read Path

From a saved live response:

```bash
python tools/knowledge_match.py --body runs/<dir>/evidence/<saved-body>
python tools/xday_match.py --body runs/<dir>/evidence/<saved-body>
```

From a known ID:

```bash
python tools/knowledge_match.py --id <knowledge-id>
python tools/xday_match.py --id <knowledge-id>
```

Then record in `decisions.md`:

- What fingerprint matched.
- Which knowledge ID was loaded.
- Which 1-3 target-specific hypotheses it produced.
- What control or proof artifact would confirm/refute them.

## Writeback Path

When a clear fingerprint misses the base:

```bash
python tools/knowledge_seed.py <id> --product "<product>" --from-body runs/<dir>/evidence/<saved-body>
```

Curate the entry before relying on it:

- Public `knowledge/*.md`: recognition signatures, aliases, weak-point anchors,
  mechanism, CVE/CNVD or primary references, proof-only verification principles.
- Local `knowledge/weaponized/*.md`: payloads, exploit chains, request bodies,
  PoC recipes, and undisclosed working material.
- Mark unsupported entries `seed`; use `verified` only with primary-source or
  first-hand evidence.

Validate:

```bash
python tools/check_knowledge.py
```

## Autonomy Guard

Allowed:

```text
recognized stack -> load matching entry -> derive target-specific check -> guarded proof/control -> evidence gate
```

Forbidden:

```text
preload entries -> run every anchor/payload family -> treat matches as findings
```

If a hit is stale or unsupported, treat it as a lead and research the primary
source before recording fact. If a local xday exists, use it as local working
material for the current authorized target; never publish it into public
grounding.

## Maintenance Checks

After changing entries or tooling, run:

```bash
python tools/check_knowledge.py
python tools/knowledge_match.py --selftest
python tools/xday_match.py --selftest
```

If the knowledge result affects a report or closure claim, run `xunji-reviewops`
before finalizing.
