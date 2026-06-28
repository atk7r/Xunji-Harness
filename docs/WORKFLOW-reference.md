# Autonomous Workflow — Reference

Load on demand. The lean per-cycle core is [`docs/WORKFLOW.md`](WORKFLOW.md); this
holds the full file templates, the derived state graph, parallel fan-out, the
detailed evidence/closure mechanics, and the safety-critical-code review gate. Read
the relevant section when you write that run file or hit that gate — not every cycle.

## Run directory layout (canonical)

One place for each kind of artifact, so a run stays auditable and the closure gate
never has to guess. `tools/setup_run.py` scaffolds it; the sensors default into it.

```text
runs/<slug>_<date>/
  <core .md>        target · surface · frontier · hypotheses · evidence ·
                    false_positive · decisions · review · report
  evidence.json     auto-derived index of evidence.md (check_run writes it)
  graph.json        derived state graph (graph.py writes it)
  evidence/         sensor proof artifacts: *.html, *.replay.json, render_<host>/, screenshots
  classify/         classify_hosts output: coverage.json + per-host bodies
  scripts/          PoC / helper scripts (author-and-handoff)
  chains.md · hints.md · alerts.md   conditional (created only when they apply)
```

Keep the run **root** to the core `.md` files plus the auto-derived
`evidence.json` / `coverage.json` / `graph.json`. Proof artifacts belong under
`evidence/`, PoC under `scripts/`, coverage under `classify/`. To make the right
place the easy place: `probe --save NAME --run runs/<dir>` drops the body **and** its
`.replay.json` into `<run>/evidence/`; `render --run runs/<dir>` defaults its output
to `<run>/evidence/render_<host>/`. A render also drops `network.json` (every request
the page made, capped at 500 — the app/API calls, `xhr`/`fetch` + `/api`·`/rest`·`.do`,
are in there; render's stdout also echoes that filtered subset as `api_requests`) and
`cookies.json` (its session) there — don't let them evaporate: if those requests
surface app/API endpoints, fold them into `surface.md`/`frontier.md`; if a follow-up
check needs the authenticated session, reuse `cookies.json` via `render --cookies-file`
or a `probe -H 'Cookie: …'`. The closure gate still resolves a cited artifact
wherever it sits (it is layout-tolerant), but `check_run.py` **warns on layout
drift at closure** — proof/scratch files left loose in the run root once a final
report exists — because mixing evidence with scratch is what makes a run hard to
audit (the original break-2 finding: `scshr` dumped 33 `ev_*.html` in the root,
`cqytxy` 21 scratch files). The warn is **closure-gated** (silent during active
verification, where mid-flight scratch in the root is normal — same cadence as
`check_shallow_close`) and never hard-fails, so legacy runs are not punished; it
just nudges you to tidy before the report is final (`tools/cleanup.py --scratch`
clears `tmp/` / `__pycache__` / `.state` scratch — dry-run by default, `--apply` to
delete).

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

<!-- NOT OPTIONAL: 攻击过程中将发现的 distinct app 及其入口点路径(URI、参数、方法、auth 要求)
写入此处。攻击面记录 = 攻击过程的自然产物, 不是独立文档工作 —— 每发现一个独立应用就补一条,
不要等"写完文档再攻击"。 -->
- 

## Trust Boundaries

<!-- NOT OPTIONAL: 记录 auth 边界关系(SSO 域、登录门、内外网隔离、角色域)。这些关系决定
攻击面之间的 trust 传递(一个入口的凭据能访问哪些其它面), 是组合利用/横向移动的前提信息。
同样随攻击过程填充, 不作为独立文档任务。 -->
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
- Threat role: <admin-mgmt|identity-auth|data-pii|transaction|content-cms|proxy-relay|infra>
- Threat exposure: <public-unauth|login-gated|hardened>
> **Threat weight matrix (driver-derived priority):**
>
> | Threat Role   | public-unauth | login-gated | hardened |
> |---------------|---------------|-------------|----------|
> | admin-mgmt    | CRITICAL      | HIGH        | MEDIUM   |
> | identity-auth | CRITICAL      | HIGH        | MEDIUM   |
> | data-pii      | HIGH          | MEDIUM      | LOW      |
> | transaction   | HIGH          | MEDIUM      | LOW      |
> | content-cms   | MEDIUM        | LOW         | LOW      |
> | proxy-relay   | MEDIUM        | MEDIUM      | LOW      |
> | infra         | Depends on specific exposure surface  |           |
>
> **Anti-lump rule:** merged assets MUST share the same threat role, else split into separate fronts.
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
- Unlocked-by: (conditional — the E-id whose confirmation makes this front actionable; a chain / chaining dependency. Most relevant on a deferred front waiting on a prior fact. Omit when there is no such dependency.)

## Deferred Fronts

### F-002

- Front:
- Threat role: <admin-mgmt|identity-auth|data-pii|transaction|content-cms|proxy-relay|infra>
- Threat exposure: <public-unauth|login-gated|hardened>
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
  - Observed: <仅事实 — HTTP状态码/响应长度/SHA1/URL/页面标题, 禁止推测词>
  - DataObtained: <none | N条-TYPE — 如 'none' 或 '128条-姓名电话邮箱'>
  - Mechanism: <利用机制 | none — 如 'POST布尔盲注' 'GET无鉴权返回模板' 'none'>
  - SeverityBasis: <从 Observed / DataObtained 直接推导, 禁止引用 DataObtained:none>
  - CodexReview: <条件字段 — Severity >= HIGH 时必填。codex agent 输出: 推荐的 severity + 一句话理由。Driver 只能采纳或降级, 不能升级。>
- Caused by us: yes / no / unknown
- Alternative explanation:
- Certainty: 0.3 / 0.5 / 0.8 / 1.0
- Replicated / Control: (conditional — required when Certainty >= 0.8)
- Artifacts: (conditional — required when Certainty >= 0.8; the saved file/dir that proves it, e.g. `evidence/foo.html`. check_run hard-fails a confirmed entry with none. `probe --save NAME --run runs/<dir>`.)
- Supports:
- Refutes:
- Unlocks: (conditional — the F-id this confirmed fact makes actionable, satisfying that front's precondition. The chaining edge; omit when it unlocks nothing.)
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

**Replay-verify the evidence (close the trust loop).** A saved `*.html` proves a
response existed; a `.replay.json` (written automatically by `probe --save`) proves
*what request produced it*, so the claim can be re-checked against the live target
instead of taken on faith. At closure run `python tools/check_run.py runs/<dir>
--replay-verify`: it replays each `.replay.json` through the guard (idempotent `GET`
only — `POST`/`PUT` need `--force`, `DELETE` is never replayed; host must be in
`target.md` In-scope). A `DIVERGED` verdict (status changed) means the evidence no
longer matches reality — the target was fixed/changed, or the finding was shaky —
and the driver must re-adjudicate before reporting it. `UNREACHABLE` is not a failure
(can't-reach ≠ false). Replay stays **opt-in** (live traffic, slow) — *not* running
`--replay-verify` never fails a run, and the gate never forces you to run it. But once
you **do** run it at a **final** report, a `DIVERGED` you leave **unaddressed** hard-fails
the closure gate: re-adjudicate each one — downgrade the finding, or add a `- Replay:`
field to that `E-` entry saying why it still stands (a target legitimately changing is
fine to keep *with* that note; one `- Replay:` per diverged finding). The gate never
auto-rejects a finding and never forces a replay — it only stops you from running
replay and then ignoring a divergence. Standalone `python tools/replay.py runs/<dir>`
replays outside the gate (no closure hard-fail).

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

### chains.md — vulnerability chain / chaining (conditional)

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
`chains.md` (chaining) edge, generalized to the whole frontier.

`python tools/graph.py runs/<dir>` parses these into a **derived** graph
(`<run>/graph.json`) and prints what is otherwise easy to miss:

- **actionable** — open fronts plus deferred fronts a confirmed Fact has unlocked.
- **unlocked-but-deferred** — a Fact confirmed, the front it unlocks still sitting in
  Deferred. The classic miss: you proved the precondition and never went back.
- **closed-but-unlocked** — a front you closed that a confirmed Fact actually reopens
  (contradiction).
- **dangling Facts** — a confirmed Fact that supports / unlocks / refutes nothing.
- **orphan hypotheses** and **confirmed chains** (chaining candidates to record).

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
  close — not a suggestion. (a real engagement showed that even after this guard was built, the
  driver still tried to close prematurely twice; a soft warning does not hold.)
  Resolve by spawning the reviewer and recording it, or by retracting the closure
  language.
- **HARD FAIL** on any `>= 0.8` evidence entry that references no existing saved
  artifact under the run dir (see "evidence.md" above).
- **WARN** (advisory) if the run lacks a `classify.txt`, a Closed Front lacks an
  evidence id, or a front was closed on a barrier without a Refutes — signals you are
  about to close too early; look harder or downgrade `closed` to `deferred`.

### Run-closure detail (core "Closure Discipline" points that load here)

**Independent review before closure — procedure.** Self-review doesn't fix self-review bias.
Spawn an independent fresh-context `general-purpose` reviewer
(`review/independent-reviewer.md`), record findings under `## Independent Review` in
`review.md`, address every one. **Prefer a heterogeneous reviewer when its cost is paid:**
if the operator accepts data egress (run findings go to an external vendor — Codex→OpenAI)
and a backend is up, `tools/peer_review.py --into-run runs/<dir>` (or
`check_run.py --auto-peer-review`) satisfies the gate with an *orthogonal* model — a
same-model sub-agent only reduces bias, not the shared blind spots a different vendor
catches. Absent that consent, the fresh-context sub-agent is the always-available,
egress-free fallback. Standing authorization granted for the sub-agent — do it without
re-asking. `check_run.py` HARD-fails a closure claim with no `Independent Review` record.

**Codex proxy is mandatory for the codex backend.** Codex CLI calls OpenAI API through its
own dedicated proxy channel (`tools/harness/codex_proxy.py`, configured via `CODEX_PROXY`
env or `tools/harness/codex_proxy.conf`), isolated from the engagement proxy
(`XUNJI_PROXY`) and the model-API direct channel. Without it, codex is unreachable and
peer_review falls through to the next backend. See `review/independent-reviewer.md` "Codex
代理（必须）".

**Mandatory retrospective before closure — procedure.** Every pentest closes with an honest
`retrospective.md` (scaffolded from `docs/templates/run/retrospective.md`): what *I* (the
driver) got wrong/slow/missed (wrong calls, tunnel vision, premature closure, evidence-gate
slips) and where the *framework/tooling* (tools/, hooks, guard, knowledge base, docs) held
the run back — the basis for the next run being stronger, not a disclaimer. `check_run.py`
HARD-fails closure if `retrospective.md` is missing or its **Self problems** / **Framework
problems** sections are empty placeholders.

## Independent review of safety-critical code (narrow gate)

The same self-review-bias fix applies beyond pentest runs to **safety-critical
framework code** — the machinery that decides what is allowed or destructive:

- `.claude/hooks/` (safety_gate + rules — the hard block)
- `tools/harness/guard.py` (rate / volume / auth / body / circuit breakers)
- `sentinel/` (behavior classification + autonomy decision + circuit breaker)

**Before declaring a behavior change to any of the above "done", first run the
whole regression battery in one shot — `python tools/selftest_all.py` (every
tool / hook / sentinel selftest; green is the floor, not the goal) — then spawn an
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
