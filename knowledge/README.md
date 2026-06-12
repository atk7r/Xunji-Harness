# Grounding Knowledge Base

This directory holds **grounding knowledge**, not weapons. Each file anchors
hypotheses for one identified technology so the autonomous driver can reason
about variants instead of guessing in the open. It is variant-analysis input,
consulted contextually after a target is fingerprinted — never a checklist that
runs the same way regardless of target.

This directory is governed by `docs/cognition/README.md`
("Grounding Knowledge Is Not a Weapon"). If anything here contradicts that
section, that section wins.

## The Contract (the one test that gates every entry)

> Does this artifact carry knowledge a reasoning driver looks up for a specific
> identified target (allowed), or does it carry weapons / steps that execute the
> same way regardless of target (forbidden)?

- **Allowed (grounding):** recognition signatures, known weak-point anchors
  (weakness *class* + mechanism + CVE/CNVD reference), and proof-only
  verification principles derived from the proof boundary.
- **Forbidden (weapons / automation):** payloads, exploit chains, request bodies,
  step-by-step PoC, scanner rules, or any fixed checklist meant to be run
  blindly. Citing that "a public PoC exists for CVE-X" is an allowed *fact*;
  copying the PoC content here is forbidden.

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
- Exploit-DB / GitHub PoC repos / PacketStorm **payload content**. The existence
  of a PoC is a citable fact; its content is a weapon and stays out.
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

- `_TEMPLATE.md` — blank schema. Copy it to start a new entry.
- One file per technology / product, named by `id` (kebab-case).

The structural and anti-weaponization checks live in
`tools/check_knowledge.py` (added with the first entries).

## Project Boundary

This base belongs to the parent workspace only. `deepseek-project/` maintains its
own independent `knowledge/`, driven by DeepSeek inside its own root. Do not
share, symlink, or read across the boundary.
