# Autonomous Workflow — Reference

Load on demand. The lean per-cycle core is [`docs/WORKFLOW.md`](WORKFLOW.md); this
holds the full file templates, the derived state graph, parallel fan-out, the
detailed evidence/closure mechanics, and the safety-critical-code review gate. Read
the relevant section when you write that run file or hit that gate — not every cycle.

## File Templates

### target.md — engagement boundary

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
directed target as authorized and proceed — stop only if an action would cross the
hard boundary. If an existing recon / OSINT report is supplied, record its path here
and ingest it (core "Ingest Existing Intelligence First") before any probing.

### surface.md — observed attack surface (not a playbook)

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

### hypotheses.md — queue of falsifiable claims

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

One hypothesis = one concrete risk. Do not bundle multiple investigation ideas into
a single hypothesis.

### frontier.md — exploration frontier (not a fixed checklist)

Fronts are areas of possible risk selected by the AI from the current target
context.

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
- Unlocked-by: (conditional — the E-id whose confirmation makes this front actionable; a chain / 组合利用 dependency. Most relevant on a deferred front waiting on a prior fact. Omit when there is no such dependency.)

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

A high-value front must not disappear from the investigation. It must remain open,
become confirmed, become rejected, be deferred with a blocker, or be closed with
Type B reasoning.

### evidence.md — record evidence before conclusions

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
- Unlocks: (conditional — the F-id this confirmed fact makes actionable, satisfying that front's precondition. The 组合利用 edge; omit when it unlocks nothing.)
- Next:
```

Evidence confidence: `1.0` direct, reproducible, boundary-clear · `0.8` stable
controlled difference with enough comparison or replay · `0.5` suspicious signal
without enough baseline, replay, or impact · `0.3` clue, one-sided observation,
inference, timeout, redirect, block page, or environmental noise.

A `Certainty` of `0.8`/`1.0` **requires** a `Replicated:` field (how it was
re-observed) or a `Control:` field (the comparison / baseline that rules out the
environmental / alternative explanation). A single observation, or a conclusion
drawn without testing the alternative, may not be `>= 0.8` — name the control or
downgrade. (This guards the failure where "the whole site blocked my IP" is recorded
at `1.0` without testing a control such as "is another host on a different IP still
reachable?".)

A `>= 0.8` entry **must also cite a saved artifact** — a path under the run dir that
actually exists and is non-empty (a `--save`d response `*.html`/`*.json`, a
`render_*/` dir, a screenshot, a captured header dump). The proof has to be on disk
and **named in the entry** so a reviewer can re-open it; prose while the backing file
is unsaved (or absent) is not confirmation. (The hole two independent reviews caught
after the structural gate passed: a `1.0` DOM-XSS whose only saved file was a
redirect-to-login page, and `1.0` blind-SQLi / CSRF conclusions never saved at all.)
`tools/check_run.py` warns on a missing control and **hard-fails the closure gate**
on a missing artifact.

### false_positive.md — make the hunter phase explicit

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

### decisions.md — make autonomy auditable

Explains why Claude chose the next front instead of handing the choice back.

```markdown
# Decisions

## D-001

- Time:
- Loaded rule files this cycle:
- Reason: (whole-frontier re-read before choosing — N fronts seen; staying on F-00X / pivoting to F-00Y because Z; any front newly unlocked/refuted by recent evidence)
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

The three barrier fields are conditional by definition: on a first attempt there is
no prior failure to compare against, so they are `none` / `n/a`; once a front is
blocked or repeated they become mandatory and must be filled honestly. Each cycle
adds or updates a decision entry. If the investigation asks the user for input, the
entry must state why autonomy is blocked.

### review.md — periodic audit (shallow / user-driven / over-confirmed)

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
summarizing instead of advancing a front. (The independent-review hard gate at
closure is in core "Closure Discipline".)

### report.md — final draft that cites the evidence ledger

Allowed states: `confirmed` (requires certainty `>= 0.8`) · `suspected` (useful
signal needing more evidence) · `rejected` (disproven or too weak).

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

### hints.md — operator steering (conditional)

Make operator steering a first-class, persistent, re-read node instead of an
ephemeral chat message. Create / append only when the operator injects direction.
Each hint is `HINT-xxx` with `Time`, `From`, `Kind`, the `Hint` text, `Status`, and
`Absorbed by`. See `docs/templates/run/hints.md` for the template. Absorb by `Kind`
(directive = controlling · lead/claim = `<= 0.5` lead, verify · constraint = soft
rule), set `Status: absorbed` and link the `D-xxx` / front, re-read every cycle as
part of the Reason pass; `check_run.py` warns while any hint is `pending`. (Core
"Operator Hints" has the short version.)

### chains.md — vulnerability chain / 组合利用 (conditional)

Confirmed findings linked because one's proven output state meets the next's
precondition. Create only when such an edge exists; copy the shape from
`docs/templates/run/chains.md`. The discipline (weakest-hop gate, terminal node,
stop at proof, pivot is operator-gated) is in `docs/cognition/README.md`
"Vulnerability Chains". In `report.md`, report the atomic findings and, when a chain
exists, the composed chain with its higher composite severity.

## State Graph (derived)

The run files already hold typed nodes (H-/F/E-xxx) and most of their edges:
evidence `Supports:` / `Refutes:`, front `Linked hypotheses:`. The one edge that
used to live only in your head is **`Unlocked-by:` / `Unlocks:`** — a confirmed Fact
(E with `Certainty >= 0.8`) satisfying a front's precondition. That is the
`chains.md` (组合利用) edge, generalized to the whole frontier.

`python tools/graph.py runs/<dir>` parses these into a **derived** graph
(`<run>/graph.json`) and prints what is otherwise easy to miss:

- **actionable** — open fronts plus deferred fronts a confirmed Fact has unlocked.
- **unlocked-but-deferred** — a Fact confirmed, the front it unlocks still sitting in
  Deferred. The classic miss: you proved the precondition and never went back.
- **closed-but-unlocked** — a front you closed that a confirmed Fact actually reopens
  (contradiction).
- **dangling Facts** — a confirmed Fact that supports / unlocks / refutes nothing.
- **orphan hypotheses** and **confirmed chains** (組合利用 candidates to record).

Run it at the start of a **Reason pass** so "what just got unlocked / neglected" is a
query, not a re-derivation. `check_run.py` reuses the same parse to warn on the two
contradiction classes (unlocked-but-deferred, closed-but-unlocked).

**Guardrail**: the graph is derived and **advisory only — it never drives or closes
anything**. Choosing the next front stays the driver's judgement; the graph just lays
the current state out. A graph that becomes the source of truth or auto-selects work
is the JSON orchestrator this project deleted (and `check_rules.py` guards against).
Markdown stays the source of truth; the graph is a projection, like `coverage.json`.

## Parallel Fan-out

The run directory is a blackboard; the independent reviewer was the first parallel
worker. When breadth beats depth, the driver may fan **several independent fronts**
out to fresh-context sub-agent workers at once. Full mechanics and prompts are in
`docs/templates/worker.md`; the essentials:

- **When**: only with **>= 3 mutually-non-blocking fronts on different
  assets/barriers** (early multi-asset recon is the case). Not for deep single-front
  work, and not when fronts share a barrier (unblock it serially first).
- **Stigmergy**: workers coordinate **only through the run dir** — they never message
  each other. The driver assigns each a disjoint front (push, not a claim-race); each
  worker writes only its own `runs/<target>/workers/W-<id>.md`.
- **Driver = sole integrator.** Workers produce **candidates, not Facts**. At merge
  the driver runs every candidate through the **evidence gate** (proposed `>= 0.8`
  without `Control:`/`Replicated:` is downgraded), allocates the canonical `E-id`,
  dedupes, updates `frontier.md`, then `graph.py` + contradiction checks. This
  single-writer gated merge is the antidote to the parallel-pollution failure
  (workers writing unconfirmed "Facts") — breadth never relaxes the evidence gate.
- **Safety**: every worker's Bash still hits the hook; all workers share ONE global
  rate limit (the guard state is cross-process locked). Workers are proof-level;
  heavier / gated / weaponized actions stay with the driver (author-and-handoff).
- `tools/workers.py` scaffolds worker files and lists merge status; `check_run.py`
  warns while any worker is `done` but unmerged. It is **not** an orchestrator — it
  never spawns workers or picks fronts (that is the driver's judgement, via the Agent
  tool). Same guardrail as the graph: tooling assists, it never drives.

## Closure gate — `check_run.py` mechanics

`tools/check_run.py` enforces closure discipline (core "Closure Discipline") only
when `report.md` makes a strong closure claim:

- **HARD FAIL** if `review.md` has no `Independent Review` record. Self-review does
  not fix self-review bias, so the independent reviewer is a hard requirement to
  close — not a suggestion. (某实战 showed that even after this guard was built, the
  driver still tried to close prematurely twice; a soft warning does not hold.)
  Resolve by spawning the reviewer and recording it, or by retracting the closure
  language.
- **HARD FAIL** on any `>= 0.8` evidence entry that references no existing saved
  artifact under the run dir (see "evidence.md" above).
- **WARN** (advisory) if the run lacks a `classify.txt`, a Closed Front lacks an
  evidence id, or a front was closed on a barrier without a Refutes — signals you are
  about to close too early; look harder or downgrade `closed` to `deferred`.

## Independent review of safety-critical code (narrow gate)

The same self-review-bias fix applies beyond pentest runs to **safety-critical
framework code** — the machinery that decides what is allowed or destructive:

- `.claude/hooks/` (safety_gate + rules — the hard block)
- `tools/harness/guard.py` (rate / volume / auth / body / circuit breakers)
- `sentinel/` (behavior classification + autonomy decision + circuit breaker)

**Before declaring a behavior change to any of the above "done", spawn an
independent `general-purpose` reviewer** (fresh context, per
`review/independent-reviewer.md`, pointed at the changed files + commits) and
**record its findings + your disposition of each in `review/records/<date>-<topic>.md`.**
This is evidence-backed, not precautionary: an independent pass on the session
circuit breaker caught a real bug (retry undercount) and a latent invariant break
that the author's own self-audit missed — and one of them contradicted the author's
own commit message (`review/records/2026-06-14-session-circuit-breaker.md`).

**Scope is deliberately narrow** (same discipline as "approval gates only for the
few highest-power actions" — do not turn it into "every commit needs review"):

- **In scope**: a change that alters *what these layers allow, block, escalate, or
  measure* (a new rule, a threshold, a decision branch, a guard wiring).
- **Out of scope**: docs / comments / pure refactor with no behavior change /
  test-only edits / changes outside the three areas above. Trivial and reversible
  work does not pay for a review.

Unlike run closure, code has no `report.md` closure artifact, so `check_run.py` does
**not** mechanically enforce this — it is driver discipline. If it gets skipped in
practice, add a mechanical aid then (e.g. a pre-commit/CI check that a behavior diff
under these paths has a matching `review/records/` entry) — measured, not pre-built.
