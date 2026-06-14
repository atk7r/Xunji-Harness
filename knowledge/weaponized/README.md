# Weaponized Knowledge Tier (local · gitignored)

This is the **weaponized** half of the knowledge base. The goal of the project is
to **use vulnerability / payload knowledge to attack** — not to be a payload
scanner. So payload-level knowledge is a first-class, expected input here, **not**
something to strip out.

> Public `knowledge/` (the repo root) is the **grounding tier**: recognition +
> weak-point anchors, no raw payloads, because it ships to GitHub. **This tier is
> the weaponized one** and is **gitignored** — entries stay local and are never
> pushed (same discipline as `poc_library/xday/`). Only this `README.md` and a
> `.gitkeep` are tracked.

## What goes here

Entries keyed to the same recognition signatures as the public tier, but carrying
the weaponized detail the grounding tier deliberately omits:

- working payloads / request bodies / exploit chains for an identified product,
- target-specific PoC recipes and gadget notes,
- anything that is "method" (free to author) but that you do **not** publish.

## The ONE line that still holds: attacker, not scanner

Having payloads here does **not** make this a scanner. What separates an attacker
from a scanner is **how the knowledge is used**, enforced by access discipline, not
by stripping payloads:

1. **Look up only after a recognition match** on a live, identified target — never
   pre-load the whole tier and walk it as a checklist.
2. **Adapt to the specific target** — the entry is a starting recipe, not a
   fire-and-forget round; the driver tailors it.
3. **Still go through the evidence gate** (`certainty >= 0.8` with control /
   replication). A matching weaponized entry is a lead, not a confirmed finding.
4. **Auto-execution still respects the hard floor** (`.claude/hooks/`): proof-level
   by default; irreversible / harm-as-purpose effects are never auto-fired.

A blind, target-agnostic run of these payloads is the scanner/playbook the project
rejects — that prohibition is about **use pattern**, not about possessing payloads.

## Format

Use the same schema as `../_TEMPLATE.md` (Recognition / Weak-Point Anchors /
Verification Principle / False-Positive / References), plus a weaponized section,
e.g.:

```markdown
## Weaponized (local only — payloads / chains, target-specific)
- For <anchor / CVE>: <working payload or chain recipe>, adapt <what to tailor per target>.
  - Pre-req: <conditions> · Proof-stop: <where to stop for proof> · source: <ref>
```

Entries here are gitignored. `tools/check_knowledge.py` does **not** police this
tier (it is local working material, like `runs/` and `poc/`); the grounding-tier
structural contract applies to the public root only.
