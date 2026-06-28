# Cognition Notes — Reference (on-demand)

Phase-specific judgment detail split out of `docs/cognition/README.md` to keep the
always-active core lean. Load on demand:

- **Attribution Checks** — Hunter phase, when judging a signal.
- **Knowledge: Grounding vs Weaponized** — when handling the knowledge base.

The canonical Evidence Confidence table, Dual Mind, grounding principle, chain hard
rules, and the drift-detector smells stay in `README.md` (always active).

## Attribution Checks

Before treating a signal as proof, answer:

- Was this caused by the current verification action?
- Did the page or environment already contain this signal?
- Is there a normal explanation such as encoding, reflection, dynamic content,
  caching, access control, gateway behavior, or test data?
- Could the vulnerable-looking response be deceptive — a honeypot, instrumented
  decoy, or gateway stub that presents a convincing weakness it does not
  actually have? A single convincing observation cannot rule this out; require
  controlled replay or a second independent signal before confirming.
- Is the asset definitely in scope and owned by the target program?
- Is the weakness merely present, or is impact actually demonstrated?

If the answer is unclear, keep the finding as suspected and record the missing
evidence in the run ledger.

## Knowledge: Grounding vs Weaponized — never a blind scanner

The project is a weapon, and the goal is to **use vulnerability / payload knowledge
to attack** — it is a reasoning attacker, **not a payload scanner**. So the forbidden
thing is **not "weaponization"**; it is **the blind scanner / playbook** (knowledge
fired the same way regardless of target) and **publishing weapons** (shipping a
turnkey kit to the world). Two axes, kept separate:

**Axis 1 — use pattern (attacker vs scanner).** The line is *how* knowledge is used,
not whether it contains payloads:

- Allowed: a reasoning driver looks knowledge up **after** it identifies a specific
  target, **adapts** it to that target, and confirms through the evidence gate.
- Forbidden: pre-loading knowledge and firing it the **same way regardless of
  target** — exploit playbooks run blindly, scanner wrappers, a JSON orchestrator,
  mechanical fixed checklists. That is the scanner/playbook the project rejects, and
  it is forbidden **whether or not** it contains payloads.

**Axis 2 — publication (what ships).** Weaponization is free to author and possess;
what is gated is publishing it:

- Public grounding tier (`knowledge/*.md`, shipped): recognition signatures,
  weak-point anchors (class + mechanism + CVE/CNVD reference), verification notes.
- Weaponized tier (`knowledge/weaponized/*.md`, gitignored) + `poc_library/` + the
  driver's authored exploits: payloads, chains, PoC. Free to hold; **not pushed**
  (publishing a turnkey kit is the indiscriminate-harm family the hard floor rejects).

The mistake to avoid: conflating "has payloads" with "is a scanner". Payload
knowledge makes the attacker sharper; using *any* knowledge as a blind checklist —
payload or not — is what's forbidden.
