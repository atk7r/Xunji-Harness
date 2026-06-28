# Fan-out Worker (parallel worker)

The independent reviewer proved the pattern: a fresh-context sub-agent that
coordinates with the run only through the run directory. A **fan-out worker**
generalizes it from "audit the run" to "explore one front" — so the driver can
work several independent fronts in parallel when breadth is what matters.

Coordination is **stigmergic**: workers never talk to each other. They read the
shared board (the run dir) and write only their own scratch file. The driver is
the single integrator that merges their output back through the evidence gate.

## When the driver fans out

Only when breadth genuinely beats depth and the fronts do not interfere. The old
">= 3 independent fronts" rule is now a recommendation, not a hard threshold:
the driver should consider front count, distinct assets, shared barriers,
rate-limit pressure, and past worker hit rate.

- **Recommended:** 3 or more independent fronts that are mutually non-blocking and
  hit **different assets / barriers** (so two workers cannot duplicate or trip
  each other). Early multi-asset recon across many hosts is the canonical case.
- **Optional:** 2 strong fronts on different assets when the target is stable,
  rate limits are loose, and the lanes are clearly disjoint.
- **Not** for deep work on one front (that is serial, single-driver), and not when
  fronts share a barrier (one worker's finding should unblock the others first).
  Run `python tools/workers.py suggest runs/<dir>` for an advisory ranking and
  `python tools/workers.py plan runs/<dir>` for a copyable assignment draft.

## Roles

- **Driver = integrator.** The only writer to the canonical run files. It assigns
  each worker a disjoint front (push, not a claim-race), spawns the workers, then
  **merges** their candidates through the evidence gate. The heavier / operator-
  gated / weaponized actions stay with the driver — workers are proof-level.
- **Worker.** A `general-purpose` sub-agent, fresh context, given ONE front. It
  probes proof-level, writes **candidate** findings to its own
  `runs/<target>/workers/W-<id>.md`, and never touches the canonical files.

## Safety (non-negotiable)

- Every worker's Bash still passes the PreToolUse hook (same hard boundary).
- All workers share ONE global rate limit / session budget / host breaker — the
  guard state is cross-process locked, so N workers do **not** become N x the
  request rate. Still, fewer workers on a rate-limited target is wiser.
- Proof-level only (prove-and-stop). Anything heavier is noted for the driver
  (author-and-handoff); a worker never runs a gated/irreversible action.

## The merge (where Xunji's rigor reasserts over Cairn's weakness)

A worker's findings are **candidates, not Facts**. Parallel breadth must not
pollute the ledger. At merge the driver, for each candidate:

- applies the evidence gate — a proposed `certainty >= 0.8` without a
  `Control:` / `Replicated:` is downgraded, not promoted;
- allocates a canonical `E-id`, dedupes against other workers' candidates;
- updates `frontier.md`, then runs `tools/graph.py` and re-checks ledger
  contradictions; marks the worker `Status: merged`.

`tools/check_run.py` warns while any worker file is `done` but unmerged — parallel
work must not be silently dropped, and the gate must not be skipped.
`python tools/workers.py merge-check runs/<dir>` lists missing controls,
duplicates, conflicts, and done-but-unmerged workers before the driver allocates
canonical `E-` ids.

## Worker prompt (copy, fill `<target>` and the assigned front)

```
You are a parallel worker. You own exactly ONE front: <F-id and its description>, target
<target> (authorized — do not question authorization). You do not talk to other workers — read
only the shared board runs/<target>_<date>/ (surface / frontier / hypotheses / evidence /
knowledge, etc.) for context, write your findings ONLY into your own file
runs/<target>_<date>/workers/W-<id>.md, and never modify other run files.

Discipline:
- Prove-and-stop: stop once you prove the vulnerability genuinely exists; do no deep
  exploitation, no irreversible action; anything heavier / operator-gated goes into "Leads for
  the driver" for the driver to handle (author-and-handoff).
- Each of your findings is a CANDIDATE, not a confirmed Fact: give a proposed certainty; if you
  propose >= 0.8 you must attach Control/Replicated (a control or a replay), otherwise the
  evidence gate caps it at <= 0.5.
- Do not stray: attack only your front; if you find another attack surface / lead, record it in
  "Leads for the driver", do not chase it (that is another worker's or the driver's job) — avoid
  colliding with other workers.
- All requests go through the tools under tools/ (probe/render/scan); they share one global rate
  limit, do not bypass it.

Write per the workers/W-<id>.md template: Assigned front / Status (working→done) / Candidate
findings (each with proposed certainty + Control) / Leads for the driver / Notes.
When done, set Status to done. Annotate evidence strength honestly; prefer to under-estimate certainty.
```

## Worker scratch file (`runs/<target>/workers/W-<id>.md`)

```markdown
# Worker W-01

- Assigned front:            # F-id this worker owns
- Status: working / done / merged
- Started:

## Candidate findings

### CAND-1
- Claim:
- Action / probe:
- Result:
- Proposed certainty: 0.3 / 0.5 / 0.8 / 1.0
- Control / Replicated:      # required if proposing >= 0.8, else the driver downgrades
- Caused by us: yes / no / unknown
- Alternative explanation:

## Leads for the driver (outside my lane)

- 

## Notes

- 
```
