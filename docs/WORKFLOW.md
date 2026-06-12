# Autonomous Workflow

This workflow is the operating memory for autonomous vulnerability discovery.
It does not prescribe attack techniques. It only defines what must be recorded
so the work can continue, be audited, and resist false confirmation.

## Run Directory

Create one directory per authorized target:

```text
runs/<target_slug>_<YYYYMMDD>/
  target.md
  surface.md
  frontier.md
  hypotheses.md
  evidence.md
  false_positive.md
  decisions.md
  review.md
  report.md
  chains.md         # conditional — only when a vulnerability chain exists
```

Use short target slugs. Do not store secrets, private tokens, real personal
data, or unnecessary sensitive content in the run directory.

## Cycle

Every autonomous cycle follows this shape:

```text
observe
  -> update surface
  -> update frontier
  -> update hypotheses
  -> REASON over the whole frontier (re-read ALL fronts, not just the active one)
  -> choose one safe verification
  -> record evidence
  -> run false-positive checks
  -> continue / confirm / reject
```

The cycle may be creative, but the written state must stay precise.

### Reason pass (high-frequency whole-frontier re-read)

Before choosing the next move, do a cheap, self-only re-read of the **entire**
`frontier.md` (every open *and* deferred front) plus the evidence added since the
last pass — not only the front you are on. Ask three questions:

1. Did new evidence just **confirm, refute, or unlock** any front (e.g. a Fact
   that satisfies a previously-blocked front's precondition)?
2. Are you **tunnel-visioned** — grinding the current front while a
   higher-value or newly-unblocked one sits idle?
3. Is the active front still the best next move, or should you **pivot**?

Output is one line in `decisions.md`, e.g. `Reason: re-read N fronts; staying on
F-00X / pivoting to F-00Y because Z`. That is the whole cost.

This is **not** the Reviewer. It is lighter and runs **every cycle**; it only
re-prioritizes and surfaces neglected/unblocked fronts — it **never closes a
front** and needs no independent reviewer. Closing/downgrading/reopening stays
the Reviewer phase's job (heavier, every 3–5 cycles or at a closure gate, with the
independent-reviewer hard-gate). The Reason pass exists to catch tunnel vision
*early*, between Reviewer checkpoints — an earlier run dug one front deep while
higher-value fronts sat idle, exactly what this pass surfaces.

When a finding **confirms**, before moving on ask one more question: does its
proven output state satisfy the precondition of another finding? If so, that is
a chain edge (组合利用) — open it as a new front and record it in `chains.md`.
This is conditional: skip it when no such edge exists.

Do not ask the user what to test next while safe open fronts remain. Choose the
next front autonomously and record the reasoning in `decisions.md`.

## Ingest Existing Intelligence First

If the user supplies, or the run already has, a recon / OSINT / asset report,
ingest it before any probing:

- Fold its assets, entry points, and signals into `surface.md`. Cite the report
  as the source.
- Treat its already-collected facts (live hosts, resolved IPs, titles, service
  banners, business classification) as given. Do not re-run discovery to
  reproduce data the report already contains.
- Only probe to (1) fill a gap the report does not cover, (2) verify a specific
  signal needed for a hypothesis, or (3) refresh a fact with reason to believe
  it changed. Each probe must say which of these it is in `decisions.md`.

Re-collecting data that already exists wastes the request budget — and against a
rate-limited or WAF-protected target, the budget is the scarce resource. Spend
it advancing a front, not reproducing the report.

## target.md

Purpose: define the engagement boundary.

Template:

```markdown
# Target

- Program:
- Target:
- Authorization basis:
- In-scope assets:
- Out-of-scope assets:
- Test accounts:
- Forbidden actions:
- Rate / availability constraints:
- Existing intel / recon report:
- Notes:
```

The operator runs authorized targets and is the authority on scope; treat the
directed target as authorized and proceed — stop only if an action would cross
the hard boundary.
If an existing recon / OSINT report is supplied, record its path here and ingest
it per "Ingest Existing Intelligence First" before any probing.

## surface.md

Purpose: maintain the observed attack surface without turning it into a
playbook.

Template:

```markdown
# Surface

## Assets

- 

## Entry Points

- 

## Trust Boundaries

- 

## Interesting Signals

- Signal:
  - Source:
  - Why it matters:
  - Normal explanations:
  - Follow-up:
```

## hypotheses.md

Purpose: keep a queue of falsifiable claims.

Template:

```markdown
# Hypotheses

## H-001

- Claim:
- Status: open / suspected / confirmed / rejected / abandoned
- Why plausible:
- What would confirm:
- What would reject:
- Safety boundary:
- Next safe verification:
- Linked evidence:
```

One hypothesis should describe one concrete risk. Do not bundle multiple
investigation ideas into a single hypothesis.

## frontier.md

Purpose: keep the exploration frontier alive without turning it into a fixed
checklist. Fronts are areas of possible risk selected by the AI from the current
target context.

Template:

```markdown
# Frontier

## Open Fronts

### F-001

- Front:
- Why it matters:
- Current depth: shallow / moderate / deep
- Status: open / probing / blocked_type_a / blocked_type_b / deferred / closed
- Barrier class: none / app-layer / auth-layer / WAF-layer / routing-layer / network-layer / scope-credential-layer
- Failure budget:
  - Same barrier failures:
  - Same bypass family attempts:
  - Same tech-stack assets tried:
- Best current evidence:
- Next autonomous move:
- Stop condition:
- Linked hypotheses:

## Deferred Fronts

### F-002

- Front:
- Why deferred:
- What would make it worth revisiting:
- Safety / authorization issue:
- Linked evidence:

## Closed Fronts

### F-003

- Front:
- Why closed:
- Evidence:
- Type A/B reason:
- Residual risk:
```

A high-value front must not disappear from the investigation. It must remain
open, become confirmed, become rejected, be deferred with a blocker, or be
closed with Type B reasoning.

## Failure Budget

Autonomy requires persistence. Real vulnerabilities often surrender only on a
later attempt, so a rigid "N tries then stop" would abandon hard-but-real fronts
one step short. The budget is therefore a heuristic that forces a conscious
decision — not an automatic kill switch.

The one substance-based stop signal:

- A work block passes with **no new evidence**. "No new evidence" — not attempt
  count — is what actually means the front is stalled. This is the primary
  trigger.

Review checkpoints (counts that prompt a deliberate decision, not a stop):

- ~3 failures against the same barrier class.
- ~3 variants in the same bypass family.
- 2 assets in the same technology stack fail on the same upstream barrier.

When a checkpoint is reached, pause and make an explicit, recorded choice — do
not silently fire off another variant. Choose one:

- **Continue (override).** Keep the front only if the next attempt is materially
  different and you can name the new evidence it should produce. Record this in
  `decisions.md` under `Difference from previous failed attempts:` and
  `Failure budget state:` — e.g. "exceeding count deliberately: the next attempt
  changes the barrier class / uses a different primitive / targets new data, and
  should yield X." Judgement stays with the driver; the only hard rule is that
  the justification is written, not skipped.
- **Pivot / defer / close.** If the honest answer is "just another variant of
  the same idea against the same barrier with no new evidence in sight," defer or
  close the front and move on.

Repeated overrides that keep producing no new evidence collapse back to the
primary signal: stop. The override buys persistence for a reasoned front; it
does not license an endless loop.

## Keep the Ledger Light

The written state must stay precise, but bookkeeping must not crowd out the
actual investigation. Two rules:

- Do not add new always-fill per-cycle fields. New discipline should be
  conditional (filled only when it applies) or enforced in `tools/`, not added
  as another mandatory field on every cycle.
- A passing `tools/check_run.py` means the structure is present, never that the
  work is good. Do not let filling fields substitute for advancing a front.

## evidence.md

Purpose: record evidence before conclusions.

Template:

```markdown
# Evidence Ledger

## E-001

- Time:
- Action:
- Source:
- Result:
- Caused by us: yes / no / unknown
- Alternative explanation:
- Certainty: 0.3 / 0.5 / 0.8 / 1.0
- Replicated / Control: (conditional — required when Certainty >= 0.8)
- Supports:
- Refutes:
- Next:
```

Evidence confidence:

- `1.0`: direct, reproducible, boundary-clear evidence.
- `0.8`: stable controlled difference with enough comparison or replay.
- `0.5`: suspicious signal without enough baseline, replay, or impact.
- `0.3`: clue, one-sided observation, inference, timeout, redirect, block page,
  or environmental noise.

A `Certainty` of `0.8` or `1.0` **requires** a `Replicated:` field (how it was
re-observed) or a `Control:` field (the comparison/baseline that rules out the
environmental/alternative explanation). A single observation, or a conclusion
drawn without testing the alternative, may not be assigned `>= 0.8` — name the
control or downgrade. `tools/check_run.py` warns on any `>= 0.8` entry missing
this. (This guards against the failure where a hasty conclusion — e.g. "the whole
site blocked my IP" — is recorded at `1.0` without testing a control such as
"is another host on a different IP still reachable?".)

## false_positive.md

Purpose: make the hunter phase explicit.

Template:

```markdown
# False-Positive Checks

## FP-001

- Related hypothesis:
- Signal:
- Could be environmental: yes / no / unknown
- Could be normal business logic: yes / no / unknown
- Could be encoding / reflection / cache / dynamic content: yes / no / unknown
- Asset ownership verified: yes / no / unknown
- Impact verified: yes / no / unknown
- Decision: continue / downgrade / reject / confirm
- Missing evidence:
```

## decisions.md

Purpose: make autonomy auditable. This file explains why Claude chose the next
front instead of handing the choice back to the user.

Template:

```markdown
# Decisions

## D-001

- Time:
- Loaded rule files this cycle:
- Chosen front:
- Chosen hypothesis:
- Why this is worth pursuing now:
- Why other open fronts are lower priority:
- Expected evidence:
- Safety boundary:
- Barrier class: (none on a first attempt; fill once a barrier is hit)
- Difference from previous failed attempts: (n/a on first attempt; required when repeating a front)
- Failure budget state: (n/a on first attempt; required once any budget counter is non-zero)
- Stop / pivot condition:
- Result:
```

The three barrier fields above are conditional by definition: on a first attempt
there is no prior failure to compare against, so they are `none` / `n/a`. Once a
front is blocked or repeated they become mandatory and must be filled honestly.
This is a correctness rule, not a shortcut — a strong model should still reason
about whether a barrier exists on every cycle; it simply records `none` when it
does not.

Each cycle should add or update a decision entry. If the investigation asks the
user for input, the decision entry must state why autonomy is blocked.

## review.md

Purpose: periodically audit whether the run has become shallow, user-driven, or
over-confirmed.

Template:

```markdown
# Review

## R-001

- Time:
- Reviewed files:
- Shallow work smells:
- Fronts closed too early:
- Fronts waiting for user direction:
- Evidence gaps:
- False-positive risks:
- Repeated-barrier loops:
- Failure-budget triggers:
- Conclusions to downgrade:
- Fronts to reopen:
- Fronts to defer or close:
- Next autonomous front:
- Required file updates:
```

Run a review before final reporting and whenever the investigation starts
summarizing instead of advancing a front.

## report.md

Purpose: final report draft that cites the evidence ledger.

Allowed states:

- `confirmed`: requires certainty `>= 0.8`.
- `suspected`: useful signal that needs more evidence.
- `rejected`: disproven or too weak to report.

Template:

```markdown
# Report

## Summary

- Status:
- Severity candidate:
- Affected asset:
- Evidence IDs:

## Impact

## Evidence

## False-Positive Review

## Reproduction Notes

## Remediation

## Open Questions
```

Do not promote a finding to confirmed unless the evidence ledger supports it.

## chains.md (conditional)

Purpose: record a vulnerability chain (组合利用) — confirmed findings linked
because one's proven output state meets the next one's precondition. Create the
file only when such an edge exists; a chain-free run does not need it. Copy the
shape from `docs/templates/run/chains.md`. The discipline (weakest-hop gate,
terminal node, stop at proof, pivot is operator-gated) is in `docs/cognition/README.md`
"Vulnerability Chains". In `report.md`, report the atomic findings and, when a
chain exists, the composed chain with its higher composite severity.

## Explored Enough

Do not claim the target or surface is exhausted unless:

- `frontier.md` has no high-value open front without a next move.
- `hypotheses.md` has no high-priority open hypothesis.
- every deferred or closed front has evidence, a safety boundary, missing
  authorization, or Type B reasoning.
- `false_positive.md` addresses the evidence used in the report.
- `report.md` cites evidence IDs rather than chat memory.

If these conditions are not met, write the current best finding and the next
autonomous action instead of saying the work is done.

### Closure Discipline (premature-closure guard)

The most common failure is declaring "no attack surface / 探尽 / 打不动" while
assets were only header- or recon-classified and never actually examined. Before
any such claim:

- **No lump.** You may not collapse N hosts into "a shared stack / default pages"
  without a per-asset, by-content examination. Run `tools/classify_hosts.py`
  (fingerprints each host by live content, not by Server header) — it writes a
  structured **`coverage.json`** (per-asset: reachable / examined / stack / flags),
  the single source of truth for "was this asset actually looked at". A host that
  returns the same default page is fine to note as such, but only after its content
  was actually fetched and read. **`tools/check_run.py` reads `coverage.json` on
  every run** (not just at closure) and lists the **distinct-app candidates**
  (unrecognized stack / Spring / Vue-SPA / LOGIN·DYN·FRAMEWORK) that must be
  investigated per-asset — so lumping is surfaced when it happens, not at closure.
- **"Can't reach" is not "is safe".** Closing a front because a WAF / throttle /
  timeout / login-gate stopped you is a `deferred` (barrier-class Type A: you
  couldn't reach the app layer), **not** a `closed` (Type B: the app layer was
  examined and is safe). A `closed` front needs positive evidence (a `Refutes:`
  or a proof), not just a barrier.
- **Closed fronts cite evidence.** Each Closed Front in `frontier.md` references
  an `E-` evidence id, not prose.

- **Credentials are ask-then-fallback, never a blocker.** When a front would go
  deeper with a test account (authenticated 越权 / SQLi / business logic), **ask the
  operator** for one. If they have none, **fall back to the unauth / harmless
  methods** (`docs/cognition/harmless-verification.md`) and push the unauth surface
  as far as it goes — do not stall the front waiting for credentials, and never
  fabricate or brute them. Record "needs account (asked, none available)" and keep
  the unauth front moving.
- **Capture grounding knowledge.** If the run fingerprinted a product / stack that
  has no entry in `knowledge/`, add a `seed` entry before closing (recognition
  signatures + weak-point anchors, grounding-only). The knowledge base must grow
  with what you actually meet in the field, not lag behind it.
- **Independent review before closure (mandatory).** Self-review does not fix
  self-review bias. Before any closure claim, spawn an independent `general-purpose`
  reviewer (fresh context, no investment in concluding) per
  `docs/templates/independent-reviewer.md`; record its findings under an
  `## Independent Review` heading in `review.md` and address every one. The
  operator has granted standing authorization to spawn this reviewer at the
  closure gate — do it without re-asking.

`tools/check_run.py` enforces this at the closure gate (only when `report.md` makes
a strong closure claim):

- **HARD FAIL** if `review.md` has no `Independent Review` record. Self-review does
  not fix self-review bias, so the independent reviewer is a hard requirement to
  close — not a suggestion. (某实战 showed that even after this guard was built, the
  driver still tried to close prematurely twice; a soft warning does not hold, so
  the missing-review case fails the check.) Resolve by spawning the reviewer and
  recording it, or by retracting the closure language.
- **WARN** (advisory) if the run lacks a `classify.txt`, a Closed Front lacks an
  evidence id, or a front was closed on a barrier without a Refutes — signals you
  are about to close too early; look harder or downgrade `closed` to `deferred`.
