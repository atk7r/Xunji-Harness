# Autonomous Workflow (core)

The lean, every-cycle operating memory for autonomous vulnerability discovery. It
defines what must be recorded so work continues, audits, and resists false
confirmation — not attack techniques.

**Load-on-demand reference:** per-file templates/fields, the derived state graph,
parallel fan-out, and the detailed evidence/closure/safety-review rules live in
[`docs/WORKFLOW-reference.md`](WORKFLOW-reference.md). Read it when writing a
specific run file or at a closure / fan-out gate — not every cycle.

## Run Directory

One directory per authorized target:

```text
runs/<target_slug>_<YYYYMMDD>/
  target · surface · frontier · hypotheses · evidence · false_positive
  decisions · review · report
  chains.md   # conditional — only when a vulnerability chain exists
  hints.md    # conditional — only when the operator injects steering
```

Short slugs. Do not store secrets, tokens, real personal data, or unnecessary
sensitive content in the run directory. Field templates for each file: reference.

## Cycle

```text
observe
  -> update surface / frontier / hypotheses
  -> REASON over the whole frontier (re-read all live fronts, not just the active one)
  -> choose one safe verification
  -> record evidence
  -> run false-positive checks
  -> continue / confirm / reject
```

Creative in discovery; precise in the written state. **Do not ask the user what to
test next while safe open fronts remain** — choose the next front autonomously and
record why in `decisions.md`.

### Reason pass (every cycle, cheap)

Before the next move, re-read the **open** fronts in `frontier.md`, the evidence
added since the last pass, and any **pending hints in `hints.md`**. If sentinel has
written `alerts.md` / `pending_approval.md` in the run dir, scan any unresolved entry
too — each flags an action of yours that hit the risky / approval-gated class; note
the disposition in `decisions.md` or hand it to the operator. (Sentinel stays
observe-only — this is self-awareness and audit, not a gate that stops you.) For the
deferred dimension run `python tools/graph.py runs/<dir>` — it lists *actionable*
and *unlocked-but-deferred* fronts, so "what just got unlocked / neglected" is a
query, not a full re-read of every block. Ask:

1. Did new evidence **confirm, refute, or unlock** any front?
2. Are you **tunnel-visioned** — grinding one front while a higher-value /
   newly-unblocked one sits idle?
3. Is the active front still the best move, or should you **pivot**?

Output: one line in `decisions.md` (`Reason: re-read N fronts; staying on F-00X /
pivoting to F-00Y because Z`). It only re-prioritizes — it **never closes a front**
(that is the Reviewer's job: heavier, every 3–5 cycles / at a closure gate, with the
independent-reviewer hard gate).

When a finding **confirms**, ask: does its proven output state satisfy another
finding's precondition? If so that is a chain edge (chaining) — open a front and
record it in `chains.md` (conditional; skip when no edge).

When an observation **grounds a product fingerprint** — i.e. while attacking an asset you
fetch it and recognize the stack (or an opt-in `classify_hosts` tagged it `kb:<id>`) —
consult the grounding base for that stack **before** crafting the next probe; do not
re-derive a known stack's weak points from memory:
`tools/knowledge_match.py --body <saved-response>` for its weak-point anchors (+ CVE
leads), `tools/xday_match.py --body …` for any stored **local** exploit. Consult on
the hit and adapt per-target — not a pre-loaded checklist (cognition "Grounding and
Variant Analysis"). If that lookup **misses** on a clearly-fingerprinted product, seed
the base back (`tools/knowledge_seed.py <id> --product … --from-body <saved>`) so the
next run recognizes it — the flywheel's write-back end; fill the TODOs, `check_knowledge`
validates.

## Ingest Existing Intelligence First

If a recon / OSINT / asset report exists, ingest it before probing: fold its
assets / entry-points / signals into `surface.md` (cite it), treat its collected
facts (hosts, IPs, titles, banners) as given, and probe only to (1) fill a gap,
(2) verify a signal a hypothesis needs, or (3) refresh a fact you believe changed —
saying which in `decisions.md`. Re-collecting existing data wastes the request
budget, the scarce resource against a rate-limited / WAF target.

## Failure Budget

Autonomy needs persistence — real vulns often surrender only on a later attempt —
so this forces a conscious decision, not an automatic kill switch.

- **Primary stop signal (substance):** a work block passes with **no new
  evidence**. That, not attempt count, means the front is stalled.
- **Review checkpoints (prompt a decision, not a stop):** ~3 failures on the same
  barrier class · ~3 variants in the same bypass family · 2 assets in the same
  stack failing on the same upstream barrier.

At a checkpoint, make an explicit recorded choice — never silently fire another
variant. **Continue** only if the next attempt is materially different and you can
name the new evidence it should produce (record under `Difference from previous
failed attempts:` / `Failure budget state:` in `decisions.md`). Otherwise
**pivot / defer / close**. Repeated overrides that keep producing no new evidence
collapse back to: stop.

## Keep the Ledger Light

- Do not add new always-fill per-cycle fields. New discipline is conditional
  (filled only when it applies) or enforced in `tools/`.
- A passing `tools/check_run.py` means the structure is present, never that the
  work is good. Filling fields is not advancing a front.
- **Every line earns its tokens** (PDF "token economics"): a note must do one of —
  narrow the asset scope, narrow the vuln class, raise/lower a certainty, explain a
  barrier, or preserve a reproducible evidence pointer. A token that neither anchors a
  fact nor shrinks the search space is noise — cut it. Same test for prompts and docs.

## Evidence Gate

Only `certainty >= 0.8` may be reported confirmed. The four-level scale + meanings
is the canonical table in `docs/cognition/README.md` "Evidence Confidence" (always
loaded) — not restated here, to keep one source of truth.

A `>= 0.8` entry **requires** a `Replicated:` or `Control:` field **and** a cited
**saved artifact** that exists and is non-empty under the run dir (a `--save`d
`*.html` / `*.json`, a `render_*/` dir, a screenshot). `tools/check_run.py`
**hard-fails** the closure gate on a `>= 0.8` entry missing the artifact, and
**warns** on one missing the control/replication (which the evidence-gate
definition then says to downgrade). (Both holes were caught by real independent
reviews — a `1.0` whose only saved file was a login redirect; conclusions claimed
but never saved.) When that control is a baseline-vs-mutant difference (boolean SQLi,
auth-bypass, IDOR on/off), `tools/probe.py DIFF <urlA> <urlB>` produces it in one call
— it reports `reliable_differential` only when each side is stable *and* the two differ
(`--samples N` raises the stability bar): the purpose-built control, not a hand-rolled
second probe. Rationale + the `evidence.md` template: reference.

## Operator Hints (`hints.md`, conditional)

Operator steering is a first-class, persistent, **re-read-every-cycle** node, not an
ephemeral chat message (Operator Authority). Create / append only when the operator
injects direction. Absorb by `Kind`:

- **directive** (do / skip / prioritize / open / close) — controlling; act on it
  (overrides soft constraints, never the hard hook).
- **lead / claim** about the target — a `<= 0.5` lead; verify through the evidence
  gate (operator suspicion is not a Fact).
- **constraint** — a soft rule for the run; honour until lifted.

Set `Status: absorbed` and link the `D-xxx` / front when acted on. `check_run.py`
warns while any hint is `pending`. Template + full absorb rules: reference.

## Explored Enough

Do not claim the target / surface is exhausted unless: `frontier.md` has no
high-value open front without a next move · `hypotheses.md` has no high-priority
open hypothesis · every deferred / closed front has evidence, a safety boundary,
missing authorization, or Type B reasoning · `false_positive.md` addresses the
report's evidence · `report.md` cites evidence IDs, not chat memory. Otherwise
write the current best finding and the next autonomous action.

### Closure Discipline (premature-closure guard)

The most common failure is declaring "no attack surface / exhausted / can't crack" while
assets were only header / recon-classified, never examined. Before any such claim:

- **No lump.** No collapsing N hosts into "a shared stack" without a per-asset,
  by-content examination. `coverage.json` is the source of truth for "which assets exist
  + which are reachable" — **built by `setup_run` directly from the Guanlan recon (zero
  re-probe; Guanlan already did dedup / wildcard-fold / liveness). Do NOT bulk-run
  classify_hosts to rebuild it (= re-OSINT).** `check_run.py` reads it every run and
  lists distinct-app candidates to investigate (per-asset content examination happens
  when you actually attack the asset, not in a bulk pre-scan).
- **Every reachable asset reaches a verdict — "examined" ≠ "tested".** Prioritising
  high-value is right, but low-value is **not** skipped: after the high-value depth
  pass, **auto-continue to the low-value assets** (cheap breadth via `tools/scan.py`).
  Each reachable in-scope asset must be driven to a verdict — confirmed / rejected /
  `deferred` **with a reason** (login-gated · no creds · can't-reach · WAF). Only
  fingerprinted (classify looked at it) is **not** a verdict and **not** closure.
  `check_run.py` **hard-fails** a final report with reachable assets never named in a
  front / evidence (same-stack siblings may share one front that lists them all — do
  not re-attack each, but every member must be accounted for). This forces a driver
  *judgement on every asset*, never a blind scan of every host.
- **Breadth before depth; `deferred` on attack surface is NOT free.** The flow is:
  preliminary-detect **every** asset's surface first (high-value → low-value; do **not**
  tunnel deep on one app while others are unexamined), **then** go to depth. A `deferred`
  verdict must be *earned*: for any asset `coverage` flagged `LOGIN` (from the Guanlan
  category, or a live probe — a real attack surface), the deferral must be backed by an
  **evidence (`E-xxx`) attack record** —
  symmetric to `confirmed` needing evidence. A bare "deferred (need creds / low value)"
  on a login surface with **no attack attempt** is the *deferred-is-the-new-lump* hole:
  laundering "didn't attack" into "closure". `check_run.py` **hard-fails** a closure with
  `LOGIN` assets absent from `evidence.md`. Attack the unauth layer first (SQLi / user-enum
  / default-creds / WAF-bypass), record the `E-xxx` — its result counts whether it lands,
  is hardened, or is egress-blocked — **then** defer the post-auth (creds-gated) depth. Do
  not stop and ask the operator while attack surface remains unattacked.
- **Depth covers the applicable vuln classes per surface — not just auth.** A
  surface's depth = the vuln classes its observed signals justify, anchored on the
  precise class name (`knowledge/_lexicon.md`), by subtype: login→auth-bypass/SQLi-login/
  enum/default-creds then [creds] horizontal/vertical privilege-escalation; param-API→injection(SQLi/cmd/
  SSTI/deser)/IDOR/SSRF/mass-assignment; upload→upload-shell/traversal/XXE; URL-fetch→SSRF/
  open-redirect; admin/actuator/swagger→unauth/default-creds/debug→RCE; SSO/OAuth→redirect/
  state/signature; file-download→traversal/arbitrary-download; exposure→source/secret/debug.
  **Discipline (not a fire-list):** test only the classes the surface's signals justify;
  name the signal that made each relevant; a negative/deferred record states the barrier
  or why the class did not apply; no fixed payload list (payloads stay local/operator-chosen);
  the gate wants evidence of *reasoning/attack attempt*, not exhaustive exploitation.
- **"Can't reach" ≠ "is safe".** A WAF / throttle / timeout / login-gate stop is a
  `deferred` (Type A), **not** a `closed` (Type B). A `closed` front needs positive
  evidence (a `Refutes:` or a proof), not a barrier. When egress changes (cooldown,
  switched egress, run in-country) and egress-deferred assets remain, re-probe them
  with `tools/rerun_deferred.py --run runs/<dir>`; whatever it returns as
  newly-reachable is **new attack surface** (it lands in `coverage_rerun.json`) —
  open/update those fronts and record the decision rather than leaving it parked.
- **Closed fronts cite an `E-` evidence id**, not prose.
- **Credentials are ask-then-fallback, never a blocker.** Ask the operator; if none,
  fall back to unauth / harmless methods and push the unauth surface as far as it
  goes (`docs/cognition/harmless-verification.md`). Record "needs account (asked,
  none available)" and keep moving — never fabricate or brute.
- **Capture grounding knowledge.** If the run fingerprinted a product with no
  `knowledge/` entry, add a `seed` grounding entry before closing
  (`tools/knowledge_seed.py <id> --product … --from-body <saved>` scaffolds a
  `check_knowledge`-compliant skeleton — fill the TODOs).
- **Independent review before closure (mandatory · HARD gate).** Self-review does
  not fix self-review bias. Spawn an independent fresh-context `general-purpose`
  reviewer (`review/independent-reviewer.md`), record findings under an
  `## Independent Review` heading in `review.md`, and address every one. **Prefer a
  heterogeneous reviewer when its cost is paid:** if the operator accepts data egress
  (the run findings go to an external vendor — Codex→OpenAI) and a backend is up,
  `tools/peer_review.py --into-run runs/<dir>` (or `check_run.py --auto-peer-review`)
  satisfies this gate with an *orthogonal* model — a same-model sub-agent only reduces
  bias, not the shared blind spots a different vendor catches. Absent that consent, the
  fresh-context `general-purpose` sub-agent is the always-available, egress-free
  fallback. `check_run.py` **hard-fails** a closure claim with no `Independent Review`
  record. Standing authorization granted for the sub-agent — do it without re-asking.

- **Mandatory retrospective before closure (HARD gate).** Every pentest closes with an
  honest `retrospective.md` (scaffolded from `docs/templates/run/retrospective.md`):
  what *I* (the driver) got wrong/slow/missed this run — wrong calls, tunnel vision,
  premature closure, evidence-gate slips — and where the *framework/tooling* (tools/,
  hooks, guard, knowledge base, docs) held the run back. Not a disclaimer — the basis
  for the next run being stronger. `check_run.py` **hard-fails** closure if
  `retrospective.md` is missing or its **Self problems** / **Framework problems**
  sections are empty placeholders. Quality stays the driver's job; the gate only blocks
  empty stubs (same line as the independent-review gate).

`check_run.py` HARD-fails / WARN mechanics for closure, and the same independent
review applied to **safety-critical code** changes, are in the reference.

## Reference

Per-file templates & fields · derived state graph (`graph.py`) · parallel fan-out ·
detailed evidence/closure mechanics · independent review of **safety-critical code**
→ [`docs/WORKFLOW-reference.md`](WORKFLOW-reference.md).
