---
name: xunji-knowledge-flywheel
description: Codex-side guide for Xunji grounding knowledge use and writeback. Use when Codex is auditing, advising on, or maintaining `knowledge/`, `knowledge_match.py`, `xday_match.py`, `knowledge_seed.py`, or knowledge-first workflow decisions, while preserving the rule that knowledge is consulted after live fingerprint recognition and never used as a blind checklist.
---

# Xunji Knowledge Flywheel

This is the Codex-side guide for Xunji's grounding knowledge loop. Codex may
review or maintain the knowledge workflow, but Claude Code remains the live
driver for target-facing runs.

## Source Of Truth

Read these when exact behavior matters:

- `knowledge/README.md` for the public-scaffold vs local-entry contract.
- `docs/cognition/README.md` "Grounding and Variant Analysis".
- `docs/WORKFLOW.md` for when the Root consults knowledge during a run.
- `tools/knowledge_match.py`, `tools/xday_match.py`, `tools/knowledge_seed.py`,
  and `tools/check_knowledge.py` for command behavior.
- `knowledge/_TEMPLATE.md` and the generic `_lexicon.md` scaffold when creating local entries.

If an entry contradicts the cognition notes or `knowledge/README.md`, fix the
entry or the stale documentation; do not turn the mismatch into a new rule.

## Codex Posture

- Do not preload `knowledge/` as a hunting checklist.
- Treat knowledge hits as grounding and weak-point anchors, not findings.
- Keep payloads, exploit chains, request bodies, and PoCs out of grounding
  `knowledge/*.md`; local weapons belong under `knowledge/weaponized/`.
- Never write CVE/CNVD/vendor facts from model memory. Use primary sources or
  first-hand run observations.
- When reviewing a Claude-driven run, check whether the driver consulted relevant
  knowledge after a fingerprint hit, and whether it avoided blind scanning.

## Read Path

Use this after a live observation recognizes a product, framework, version, or a
coverage tag such as `kb:<id>`:

```bash
python tools/knowledge_match.py --body runs/<dir>/evidence/<saved-body>
python tools/xday_match.py --body runs/<dir>/evidence/<saved-body>
```

Or direct lookup from a known tag:

```bash
python tools/knowledge_match.py --id <knowledge-id>
python tools/xday_match.py --id <knowledge-id>
```

Convert the hit into a small number of target-specific hypotheses. Do not sweep
every anchor or payload family. Confirmation still requires the evidence gate.

## Writeback Path

Seed a local grounding entry when a product is clearly fingerprinted but no
knowledge entry matches:

```bash
python tools/knowledge_seed.py <id> --product "<product>" --from-body runs/<dir>/evidence/<saved-body>
```

Then curate the entry:

- Add recognition signatures and aliases.
- Add weak-point anchors as class + mechanism + primary reference.
- Mark unverified material as `seed`; use `verified` only when every anchor has
  primary-source support or first-hand evidence.
- Leave payloads and request bodies in the local weaponized tier, not grounding files.

Validate before treating the entry as usable:

```bash
python tools/check_knowledge.py
```

## Autonomy Guard

Allowed use pattern:

```text
live fingerprint -> knowledge lookup -> target-specific hypothesis -> guarded proof/control -> evidence gate -> optional writeback
```

Forbidden use pattern:

```text
load all knowledge -> walk anchors as a checklist -> call matches findings
```

If a knowledge anchor is stale, generic, or unsupported, downgrade it to a lead
and research the primary source before recording it as fact.

## Maintenance Checks

After changing knowledge tooling or entries, run:

```bash
python tools/check_knowledge.py
python tools/knowledge_match.py --selftest
python tools/xday_match.py --selftest
```

If the change affects report or closure claims, also use `xunji-reviewops`.
