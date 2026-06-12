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
  -> choose one safe verification
  -> record evidence
  -> run false-positive checks
  -> continue / confirm / reject
```

The cycle may be creative, but the written state must stay precise.

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
