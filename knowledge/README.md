# Knowledge Base — Grounding (public) + Weaponized (local)

The project's goal is to **use vulnerability / payload knowledge to attack** — it is
a reasoning attacker, **not a payload scanner**. Payload knowledge is therefore a
first-class, expected input, not something to strip out. The base is split into two
tiers, and the line between them is **where it publishes**, not whether it is "a
weapon":

- **Grounding tier — `knowledge/*.md` (this dir root · public · shipped to GitHub):**
  recognition signatures + weak-point anchors (weakness *class* + mechanism +
  CVE/CNVD reference) + proof-only verification principles. **No raw payloads here**
  — because this tier ships publicly.
- **Weaponized tier — `knowledge/weaponized/*.md` (local · gitignored):** working
  payloads, exploit chains, PoC recipes, keyed to the same recognition. The weapons
  live here and are never pushed (same discipline as `poc_library/xday/`). See
  `knowledge/weaponized/README.md`.

This dir is governed by `docs/cognition/README.md` ("Knowledge: Grounding vs
Weaponized — never a blind scanner"). If anything here contradicts that section,
that section wins.

## The one line that gates USE (attacker, not scanner)

> Is the knowledge looked up by a reasoning driver **after** it identifies a
> specific target, then adapted to that target and run through the evidence gate
> (allowed) — or fired the **same way regardless of target** as a blind checklist
> (forbidden: that is the scanner / playbook the project rejects)?

This gate is about **use pattern**, not about possessing payloads. You cannot attack
without payload knowledge; running it blindly is the only thing forbidden. The two
tiers differ only by **publication** — payloads go in the gitignored weaponized
tier, not the public root.

- **Grounding tier holds:** recognition signatures, weak-point anchors (class +
  mechanism + CVE/CNVD reference), proof-only verification principles.
- **Weaponized tier holds:** payloads, exploit chains, request bodies, PoC recipes
  — keyed to recognition, gitignored, used per-target through the evidence gate
  (never pre-loaded and walked as a blind checklist).

## How To Use (and How Not To)

- Consult an entry **only after** recognition signatures match a live target,
  during the Driver/Hunter phase. Then derive the specific check for that
  specific target from the anchor — the entry does not hand you the check.
- Do **not** pre-load the whole base at run start and walk it as a checklist.
  That violates the evidence-gated commitment rule in `docs/ROUTER.md`.
- An anchor tells you *where to look* and *why it is weak*. Confirmation still
  goes through the evidence gate (`certainty >= 0.8`); a matching anchor is not
  a finding.

### Durable entry vs on-demand lead

Store the anchor, not the scanner template. Decide by recurrence:

- **Durable (store an entry):** a technology you recurringly target, or anything
  a run confirmed first-hand. Curate it into a small, reviewed, `verified`
  entry. External catalogs (e.g. Nuclei templates) are *one source you mine when
  authoring* — take `info` (CVE/product/references) and detection-only matchers
  (`technologies/`, fofa/shodan fingerprints); never the request/payload bodies,
  and never mirror the catalog wholesale (that is the forbidden checklist).
- **On-demand (do not store):** a long-tail / one-off technology met mid-run.
  Read its lead (a template's `info`, a CVE record) at use-time, derive the
  check, move on. Promote it into a durable entry only if it proves recurring or
  high-value — the run -> knowledge feedback loop.

## Source Discipline

Every fact must be traceable. Three source classes, kept distinct via the
`source:` tag on each anchor:

1. **External cited fact** — CVE/CNVD record, vendor advisory, official docs.
   Requires a primary, clickable URL. Prerequisite for `maturity: verified`.
2. **First-hand run observation** — a signature or weakness this workspace
   confirmed on a real target. Cite the run and evidence ID. Runs feed the base;
   the base grounds the next run.
3. **Driver-authored reasoning** — proof-only verification principles and
   confounders, derived from the safety boundary and Attribution Checks. Marked as reasoning,
   not external fact.

### Where knowledge must NOT come from

- Parametric/model memory treated as authority — the primary hallucination
  source named in `docs/cognition/README.md`. Memory is a lead for *what to look
  up*, never a fact to record. Never write a CVE/CNVD id from memory.
- Exploit-DB / GitHub PoC repos / PacketStorm **payload content** in the PUBLIC
  tier. The existence of a PoC is a citable fact; its content is a weapon — it
  belongs in the gitignored `knowledge/weaponized/` tier, never in the public root.
- Scanner template catalogs (e.g. Nuclei) **as a mirror**. Mining their `info`
  and detection-only matchers for anchors/recognition is allowed; copying their
  request/payload bodies, or bulk-importing the catalog, is not. Cite the
  primary CVE/advisory the template references, not the template itself. The
  mining source may be a local, offline clone of the catalog (fine for
  air-gapped / no-GitHub environments) — keep it outside the repo (external or
  gitignored), read it read-only, never run it, and never commit it into the
  tree.
- Untraceable forum "0day" or second-hand retellings. At most `maturity: seed`
  with an explicit "unverified" note; never `verified`.

## Maturity

- `seed` — drafted; anchors not yet verified against a primary source.
- `verified` — every anchor carries a verified primary reference.
- `stale` — `last_reviewed` is old or a referenced product/version has moved on.

"Found nothing verifiable" is a valid outcome. Leave anchors empty rather than
inventing them.

## Files

- `_TEMPLATE.md` — blank schema for the public grounding tier. Copy to start an entry.
- One file per technology / product, named by `id` (kebab-case).
- `weaponized/` — the local, gitignored weaponized tier (payloads / chains / PoC);
  see `weaponized/README.md`. Only its `README.md` + `.gitkeep` are tracked.

`tools/check_knowledge.py` validates the PUBLIC tier only (its glob is
non-recursive — `knowledge/*.md`), so the weaponized tier is out of scope: it is
local working material, like `runs/` and `poc/`. A payload that lands in the public
tier hard-fails the checker (publish-routing error → move it to `weaponized/`).
