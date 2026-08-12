---
name: xunji-knowledge-flywheel
description: Claude-primary guide for match-gated local grounding during a live run and separately authorized repository knowledge writeback, without turning the base into a checklist scanner.
---

# Xunji Knowledge Flywheel

Use knowledge only after a live artifact or `kb:<id>` grounds a specific product,
framework, or component. A match is a lead, not a finding.

## Owners

- `knowledge/README.md` owns public grounding versus local weaponized tiers.
- `docs/cognition/README.md` "Grounding and Variant Analysis" owns reasoning use.
- `knowledge/_TEMPLATE.md` and `_lexicon.md` own entry shape.
- `xunji-evidence-replay-gate` owns proof and promotion.
- `web-research` owns the public-search order after local grounding.

## Live Run: Bounded Read Only

In an active `/loop`, the Root freezes the smallest matching knowledge paths into
the Agent context. The Agent uses built-in Read on those exact paths:

1. Read the saved live artifact or the exact `kb:<id>` tag.
2. Extract the observed vendor/product/component/version signature.
3. Read only the matching `knowledge/*.md` entry named by the context. If a local
   weaponized/xday entry is named, inspect it only after the public grounding
   match; never inventory or discover the corpus from the Agent.
4. Record in `decisions.md` the observed fingerprint, loaded ID, 1–3
   target-specific hypotheses, and the control/artifact that would confirm or
   refute each.

`tools/knowledge_match.py` and `tools/xday_match.py` are offline helper CLIs, not
registered live-run capabilities. Do not invoke, wrap, pipe, or emulate them with
`python -c` during `/loop`; a gate denial is not a lookup result. The built-in
exact-path read above keeps the required grounding step executable without
granting a new control-plane capability.

Allowed reasoning:

```text
grounded signature -> one matching entry -> target-specific hypothesis
-> guarded proof/control -> evidence gate
```

Forbidden reasoning:

```text
preload entries -> fire every anchor/payload family -> call matches findings
```

If the entry is stale or unsupported, keep it as a lead and use `web-research` to
check primary/public sources. Local weaponized material never becomes public
grounding; whether its body may enter the current driver context remains governed
by the existing privacy/model-egress boundary, not by this skill.

## Misses And Writeback

During a live run, record a clearly fingerprinted miss as a deferred knowledge
gap with its artifact and proposed ID. Do not mutate repository knowledge from
the engagement turn.

Writeback happens only in a separate, explicitly authorized repository
maintenance turn. Curate one entry:

- Public `knowledge/*.md`: recognition signatures, aliases, weak-point anchors,
  mechanism, primary references, and proof-only verification principles.
- Local `knowledge/weaponized/*.md`: payloads, exploit chains, request bodies,
  PoC recipes, and undisclosed working material.
- Use `seed` for unsupported scaffolds; use `verified` only with primary-source
  or first-hand evidence.

Review the resulting diff and validate the base before relying on the new entry.
Knowledge writeback never grants target authority, changes canonical run facts,
or closes a front.

## Offline Developer Checks

Outside a live run, developers may validate the helper implementations directly:

```bash
.venv/bin/python tools/selftest_all.py --only check_knowledge,knowledge_match,xday_match
```

If knowledge affects a report or closure claim, adjudicate it through
`xunji-reviewops` and the evidence gate.
