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
  state/            derived caches: projection.json · events.jsonl ·
                    workflow_checkpoint.json · coverage_matrix.* · loop_state.* ·
                    progress_ledger.* · controller.shadow.json · controller_diff.md ·
                    loop_journal.jsonl
  evidence/         sensor proof artifacts: *.html, *.replay.json, render_<host>/, screenshots
  classify/         classify_hosts output: coverage.json + per-host bodies
  scripts/          PoC / helper scripts (author-and-handoff)
  sources/          immutable setup input + normalized candidate + validator receipt
  chains.md · hints.md · alerts.md   conditional (created only when they apply)
```

Keep the run **root** to the core `.md` files plus the auto-derived
`evidence.json` / `coverage.json` / `graph.json`; broader derived projections belong under
`state/`. Proof artifacts belong under
`evidence/`, PoC under `scripts/`, coverage under `classify/`. Setup provenance
belongs under `sources/`: `sources/original/<snapshot>`,
`sources/normalized.json`, and `sources/validator_receipt.json` implement the
versioned `xunji.setup-source.v1` contract.
`target.md` cites the source hash and receipt but remains the canonical human
boundary; source JSON cannot silently overwrite it. Any adjacent recon `report.md`
that affects baseline reachability is a hashed `related_sources` snapshot rather
than an invisible second input. To make the right
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

## Input Shape Catalog

### IS-001

- URL pattern:
- Content-Type:
- Key params:
- Auth required:
- Response shape:
- Seen on hosts:
- Source JS/artifact:
- Client-controlled params:
- Client-side signature/token/nonce logic:
- Role or permission hint:
- State transition:
- Linked threat hypothesis:
- Tested payload classes:
- Saturation:

## Permission / State Working Matrix (Conditional)

- cross-role: N/A (single account)

| Front | Action/request | Role A expected | Role B observed E-id | State edge | Next control |
|---|---|---|---|---|---|
```

### hypotheses.md — queue of falsifiable claims

```markdown
# Hypotheses

## H-001

- Claim:
- Status: open / suspected / confirmed / rejected / abandoned
- Source / trust: <operator-reviewed | agent-candidate from A-...; untrusted until Root verifies>
- Threat hypothesis: <optional; concrete asset/role/input abuse path>
- Asset/role/input:
- Expected signal:
- Refutation/control:
- Why plausible:
- What would confirm:
- What would reject:
- Safety boundary:
- Next safe verification:
- Linked IS/C/E:
- Linked evidence:
```

One hypothesis = one concrete risk. Do not bundle multiple investigation ideas into
a single hypothesis. Threat hypothesis fields are optional discovery aids, not a
separate threat-model source of truth.

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
  - CodexReview: <条件字段 — Severity >= HIGH 时必填。Codex reviewer 输出: 推荐的 severity + 一句话理由。Driver 只能采纳或降级, 不能升级。>
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
instead of taken on faith. At closure run `python3 tools/check_run.py runs/<dir>
--replay-verify`: it replays each `.replay.json` through the guard (idempotent `GET`
only — `POST`/`PUT` need `--force`, `DELETE` is never replayed; host must be in
`target.md` In-scope). A `DIVERGED` verdict (status changed) means the evidence no
longer matches reality — the target was fixed/changed, or the finding was shaky —
and the driver must re-adjudicate before reporting it. `UNREACHABLE` is not a failure
(can't-reach ≠ false). Replay stays **opt-in** (live traffic, slow) — *not* running
`SKIPPED-PRIVACY-REDACTED` means the recorder correctly removed reusable
Cookie/token/PII. It must never send placeholders or count that result as a
verification. Re-acquire the intended session, perform a fresh guarded
replication, cite the new artifact/control, and add a per-entry `- Replay:` note.
At a final report an unaddressed privacy-redacted replay supporting a confirmed
finding is a hard closure error, just like an ignored load-bearing divergence.

`--replay-verify` never fails a run, and the gate never forces you to run it. But once
you **do** run it at a **final** report, a `DIVERGED` you leave **unaddressed** hard-fails
the closure gate: re-adjudicate each one — downgrade the finding, or add a `- Replay:`
field to that `E-` entry saying why it still stands (a target legitimately changing is
fine to keep *with* that note; one `- Replay:` per diverged finding). The gate never
auto-rejects a finding and never forces a replay — it only stops you from running
replay and then ignoring a divergence. Standalone `python3 tools/replay.py runs/<dir>`
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
- Evidence IDs:   (finding maturity only; do not list phenomenon/candidate here)
- Fingerprints captured:   (识别的产品指纹是否入库: '<产品> → knowledge/<id>.md'; 或 "无新指纹")

## Impact

## Chains (组合利用 — only if a chain exists)

- Chain: <C-id from chains.md>
- Composed path: <Hop 1 -> Hop 2 -> terminal state>
- Composite severity: <usually higher than any single hop>

## Confirmed Findings

Only finding-maturity evidence belongs here and in `Evidence IDs:`.

## Candidate / Phenomena

Use this section for leads, background behavior, or lower-maturity observations.
Do not phrase these as confirmed impact.

## Background Evidence

Context that explains scope, fingerprints, controls, or exclusions.

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
part of the Root graph pass; `check_run.py` warns while any hint is `pending`. (Core
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

`python3 tools/graph.py runs/<dir>` parses these into a **derived** graph
(`<run>/graph.json`) and prints what is otherwise easy to miss:

- **actionable** — open fronts plus deferred fronts a confirmed Fact has unlocked.
- **unlocked-but-deferred** — a Fact confirmed, the front it unlocks still sitting in
  Deferred. The classic miss: you proved the precondition and never went back.
- **closed-but-unlocked** — a front you closed that a confirmed Fact actually reopens
  (contradiction).
- **dangling Facts** — a confirmed Fact that supports / unlocks / refutes nothing.
- **orphan hypotheses** and **confirmed chains** (chaining candidates to record).

Run it at the start of a **Root-level state graph pass** so "what just got unlocked /
neglected" is a query, not a re-derivation. `check_run.py` reuses the same parse to warn on the two
contradiction classes (unlocked-but-deferred, closed-but-unlocked).

**Guardrail**: the graph is derived and facts-only — it never drives, closes, or
assigns work. Choosing the next front stays the Root's judgement. Worker/agent
suggestions belong in `tools/workers.py suggest`; the graph just lays the current
state out. A graph that becomes the source of truth or auto-selects work is the
JSON orchestrator this project deleted (and `check_rules.py` guards against).
Markdown stays the source of truth; the graph is a projection, like `coverage.json`.

`tools/state_project.py` provides the broader machine projection:
`<run>/state/projection.json` and `<run>/state/events.jsonl`. The event stream uses
`type=front|status|action|evidence` records derived from Markdown. It is cache/index
data for tools such as `workers`, `bench`, and `check_run`; it must never be edited
as the narrative source of truth or used to overwrite Markdown.

`tools/loop_state.py` joins the graph, projection, Agent Board conflict state,
saturation, evidence parser, and coverage matrix into `<run>/state/loop_state.json`
and `<run>/state/loop_state.md`. This is the per-cycle closed-loop snapshot:
evidence delta, certainty upgrades, coverage-matrix improvement, no-progress
cycle count, Coda convergence, fan-out-required hints, unresolved conflicts, and
closure-review hints. It is derived and advisory only. It never selects the next
front, promotes Agent output, closes a front, or writes report conclusions.

`tools/progress_ledger.py` writes `<run>/state/progress_ledger.json` and `.md`.
It records whether the last cycle produced material progress, whether evidence
progress has saved artifact backing, and whether Coda/no-progress counters are
accumulating. It is a progress audit cache, not evidence.

`tools/run_controller.py --shadow` writes `<run>/state/controller.shadow.json`
and `<run>/state/controller_diff.md`. It consumes loop/progress state and reports
the shadow control-plane state, stop blockers, and next required lifecycle action.
It is advisory only: it never chooses exploit steps, promotes evidence, or grants
`GHOST_COMPLETE`. Its `can_stop` field is intentionally false in shadow mode;
only hard closure gates plus Root adjudication can authorize a stop.

`tools/loop_journal.py` writes `<run>/state/loop_journal.jsonl`. It is an
append-only interruption journal for explicit `/loop` cycles. The typed subset
adds `stage_plan`, `replan`, `stage_exit`, `delegation_committed`, and plan-bound
`cycle_end` to the legacy start/plan/action/write-result/interrupt/end surface.
`tools/loop_journal.py <run> end --next-action "<exact final Coda action>"` is the
public and sole producer CLI for plan-bound `cycle_end`. It validates the current
work plan through its committed v2 transaction, immutable transaction
archive, and lineage before deriving exhaustive assignment/result/review/Root
dispositions from typed receipts. The caller supplies only `next_action`, never
completion summaries or disposition arrays. The newest validated structured
`next_action` for the exact current, ended v2 plan is authoritative for the final
`下一行动:` projection. The producer and Stop consumer both apply the normal
single-action, concrete-object, and active-front semantics; an older ended plan
never shadows a newer active plan. The Stop consumer independently revalidates
the committed transaction archive and lineage, while compatibility free-text
checks apply only when the current plan has no structured end. The command
rejects provenance errors and open debt. The journal helps resume after a
broken loop turn. An append returns success only after flush and file fsync under
the journal lock; creating or retrying a zero-byte journal also fsyncs the parent
directory. A write, flush, file-fsync, or directory-fsync failure truncates the
uncommitted tail back to the prior byte length and fails closed, preserving an
exactly-once retry and the existing hash chain. The journal is not evidence and
never replaces `decisions.md`,
`evidence.md`, or `session_handoff.md`.

`tools/anti_drift.py --semantic-status <run>` derives Reason-pass freshness from
canonical content digests, never mtimes. After a whole-graph reread/adjudication,
`tools/anti_drift.py --record-reason-pass <run> --cycle-id N --chosen-front F-001
--reason "<rationale>"` appends a hash-chained v1 receipt covering frontier,
evidence, coverage, decisions, and the derived graph. `touch`, file age, or a no-op
Edit cannot mint freshness. Operational liveness is a separate projection of
journal/runtime/Agent events. The receipt itself is derived audit state, not proof
of reading, authority, evidence, or closure.

`tools/run_model.py` is the sole parser for canonical front status, barrier, and
depth fields. `tools/turn_contract.py` writes the current prompt's
`EXECUTE`/`EXPLAIN_ONLY`/`PAUSED_BY_OPERATOR` contract. Hook-observed Agent, Cron,
and foreground peer-review events are appended to the hash-linked
`state/runtime_events.jsonl`; only transcript-backed events validate process claims.
These control-plane files are hook-owned and are not editable narrative state.
Run selection is also hook/tool-owned. `tools/setup_transaction.py` is the only
active-pointer and session-selection-receipt writer: operator setup/resume,
prompt-named set-active, and prepared recovery call its commit CAS; exact Claude
`SessionStart.source=resume` calls its narrower resume CAS. New setup validates source
before formal directory creation, builds a complete run in hidden same-filesystem
staging, writes `state/setup_source.json`, the matching versioned bundle under
`sources/`, plus a prepared
`state/setup_transaction.json`, then atomically renames and attempts pointer CAS.
CAS failure preserves the old pointer and an auditable `prepared_not_active` run;
pointer-success/receipt-failure is recovered idempotently from the pointer, source
hash, and transaction id and never creates a second run.

A no-active-run EXECUTE prompt uses a short-lived pending contract that is consumed
on first binding. Direct pointer edits, unrelated run switches, and unrequested
clear-active operations are rejected. The hook-owned `SessionEnd` cleanup is the
only exception: the transaction owner rechecks the ending session, transcript,
exact active-contract digest, and pointer under the same lock; it installs an
`EXPLAIN_ONLY session_ended` barrier, saves a hashed per-session derived receipt,
retires claims, and then clears the pointer. Only the exact later Claude resume
event may install an `EXPLAIN_ONLY resume_barrier`, restore the pointer, and consume
that receipt. `startup`, `clear`, `compact`, fork/new sessions, and ordinary prompts
do not restore; a first post-resume prompt must mint fresh authority. Pending
bootstrap permits only reads and its
current-session lifecycle transition until binding. A target/session/prompt-hash
claim prevents cross-session pending selection; concurrent claims fail closed. The
transaction binds the consumed hook claim to source hash, transaction id, and exact
expected run; CLI/source adapters never accept claim contents, claim paths, or
operator-authority fields.
The setup receipt's top-level `effect_profile`, `contract_binding`, and
`transition_claim` describe only the original create identity. Later
resume/set-active effects cannot overwrite those fields or use an activation
prompt to rebind setup-source authority. A formal run instead stores its latest
activation under the self-validating `activation_attempt`: the exact activation
profile/effect, prior pointer snapshot, and hook binding are persisted before the
pointer write, then terminalized as `committed` or post-pointer `recovered`.
Consequently a pending activation remains recoverable state even when the outer
create receipt is already `committed`; cross-operation retries, attempt tampering,
and a different pointer snapshot fail closed. If a later operator prompt invokes
the same effect after post-pointer recovery, the owner first settles the frozen
old attempt and then records/terminalizes a new exact follow-up attempt so the
fresh claim cannot remain replayable. Create recovery applies the same rule only
when source, profile, pointer, and transaction identity all match; a different
effect remains unconsumed and the call is denied. The compatibility port maps only a
truly omitted `activate_existing_run(operation=...)` argument to statusline
set-active. Explicit `None`, empty, and unknown operations are rejected, and new
callers must pass their exact operation.
Authority state is durable, not merely visible: pending contracts, active/claimed/
revoked claims, and the target turn contract use file plus fixed artifact-directory
and owner-directory barriers. Finalize
repeats the claim/pending directory fsync even when an unlink already made the path
absent. Post-pointer recovery first settles the immutable binding belonging to the
create or current activation attempt, then handles a fresh exact claim; it never
relabels the old origin. `SessionStart.source=resume` consumes its selection receipt
with the same durable-absence rule. These guarantees cover transaction authority
metadata only, not the complete builder tree or SessionEnd selection creation/pointer
clear.
The validator resolves every candidate asset/scope/auth `source_ref` against the
frozen snapshot and checks that the referenced content contains the claimed value.
Only the hook-bound top-level prompt hash can mint `authority=operator`; source,
attachment, target, tool, and reviewer prose remain untrusted data.
The JSON Schema is the structural layer, not a complete validator. Every runtime
must also enforce source-reference value containment, IDNA host rules,
URL/host/scheme/port consistency, operator-prompt binding, asset URL/host
consistency, and snapshot/bundle hashes. `tools/setup_source.py::validate_manifest`
owns those semantics today; a replacement runtime must pass the shared fixtures
and Python differential tests before it can become authoritative.
The Markdown/ordinary-JSON pilot adds a narrower
`setup-normalizer-candidate.v1` contract. `tools/setup_normalizer.py` inventories
mechanically source-backed tokens/references, rejects instruction/fenced-code
lanes, and requires exactly one deterministic target-labelled URL/host. External
AI receives only a hard-redacted surrogate with no source path and returns IDs,
never values. The local layer reconstructs values from the unchanged snapshot,
rejects forged/ineligible IDs, keeps source authorization at `source-data`, and
freezes `sources/normalizer_request.json` plus
`sources/normalizer_candidate.json` with validator-bound hashes. `--ai off` is the
default. `--ai external` needs current-prompt consent and provider/model identity;
`--ai local` fails until a trusted backend registry exists. HTML/PDF/DOCX/plain
text remain deferred until their selector/page/offset provenance fixtures pass.
The derived asset ledger must retain coverage `scope_status`. Target-facing tools
fail closed for `review|out|unknown`; only `in` and pre-contract legacy rows keep
their prior behavior. Setup-source candidate `in` additionally requires a valid
committed `xunji.scope_admission.v1` receipt、current setup-source hash and scope
projection hash. Candidate identity is re-derived from the validator-bound frozen
setup bundle, so changing or removing a mutable coverage/asset-ledger `source`
label cannot bypass the receipt gate. The only
promotion path is a new operator turn whose first non-empty line is
`/xunji-scope-admit --run runs/<name> --assets <host[,host...]> --reason <text>`,
followed by the exact matching `tools/scope_admission.py` call. The hook owns the
single-use claim. The turn is local-only/zero-probe; `out`, `unknown`, wildcard,
inactive-run, target, Agent, Cron, replay, and direct ledger edits fail closed.
Scope commit shares the activation lock with the sole pointer owner, so the
active-run identity cannot change between the check and the receipt/ledger commit.
If a crash leaves a prepared admission, it remains non-executable; a new exact
operator claim for the same assets may finalize the unchanged prepared projection.
Stop hooks select exactly one `xunji.stop-output.v1` variant: `NORMAL_CODA`,
receipt-backed `TARGET_DENIED`, or receipt-backed `MAINTENANCE_BLOCKED`. Their
fields are mutually exclusive. The two fixed-envelope variants reject free-form
success prose; none grants authority or substitutes for a plan-bound `cycle_end`.
The first invalid output is blocked, and Claude Code's `stop_hook_active` retry is
idempotent; retry never marks a run complete or changes a front.

## Work plan and reversible Macro-Stage

TaskCreate/TaskUpdate is current-turn iteration-planning proof only. It is not
`xunji.work-plan.v1`, does not create a lane, and cannot satisfy an Agent receipt.
The plan declares one reversible goal view while deterministic code derives its
readiness:

- `S1`: meaningful target/scope exists.
- `S2`: S1 plus coverage and a valid canonical frontier schema.
- `S3`: S2 plus no open or Type-A/deferred fronts and no plan-bound merge/review
  debt.

These labels are not Router phases and are not another canonical truth. Root may
move backward after a changed premise, but a later `work_plan.py commit` needs a
material `--replan-reason`; stage change also needs the prior plan's debt-free
typed `cycle_end`. `work_plan.py` alone writes the typed stage/replan sequence.
The current owner is the Python/Hook control path. This stage does not add a
parallel plan, assignment, or merge runtime.

`state/work_plan.json` is consumable only when its matching
`state/work_plan_transaction.json` is committed as v2 and the current receipt,
its immutable `state/work_plan_transactions/<receipt_hash>.json` archive, complete
`prior_transaction_receipt_hash` lineage, typed journal sequence,
content-addressed snapshot, current plan, turn binding, and input digest all
revalidate. A missing, prepared, unreadable, unarchived, broken-lineage, or
mismatched transaction fails closed; `commit` cannot overwrite that state to
manufacture provenance. A genuine pre-transaction plan has one explicit recovery
path:

```bash
python3 tools/work_plan.py migrate-legacy runs/<dir>
```

This exact active-run control capability is not `ROOT_DIRECT`. It succeeds only
when the current turn/input, one unambiguous typed plan+delegation journal sequence,
active plan digest, stage-exit state, and an already frozen snapshot agree, then
records a self-hashed committed transaction with `provenance=legacy_migration`
and a recomputable migration-source digest. The same command upgrades only an
exact committed native v1 receipt to `provenance=native_v1_upgrade`; both the old
and new receipts remain archived and chained. It never creates a missing snapshot,
and there is no implicit legacy acceptance.

The exact lifecycle is:

```text
work_plan commit
  -> workers delegate: ready assignment + context pack + exact launch prompt
  -> PreToolUse compares the complete raw prompt byte-for-byte
  -> Claude invokes the real Hunter Agent; lifecycle hooks bind its exact hash
  -> hook return: content-addressed response snapshot + merge-draft.v1
  -> workers delegate: dependent Reviewer prompt + exact XUNJI_RESULT_DIGEST
  -> Claude invokes the real Reviewer Agent
  -> workers review-disposition: digest-bound review receipt
  -> Root canonical adjudication + workers finish
  -> loop_journal end --next-action "<exact final Coda action>": derived typed cycle_end
```

`workers.py delegate` never spawns. Each returned assignment is one binary Agent
launch contract: copy its exact `subagent_type` and its byte-exact `launch_prompt`.
Role `review` maps only to `xunji-reviewer`; canonical execution roles
`surface|web-auth|web-hunter|code-audit|exploit|verify|report` map only to
`xunji-hunter`. Missing/null/blank, `general-purpose`, aliases, case/whitespace
variants, and role swaps fail closed. The parent requested type and actual
same-session Start/Stop type must agree. A launch acknowledgement, Task receipt,
heartbeat, Agent prose, `done`, or an unbound Reviewer PASS cannot skip a link.
The delegate output is the entire authoritative `tool_input.prompt`, not a set of
independently matchable fields. Consumers perform no trim/normalization: any
prefix, suffix, newline, extra context, token reorder, whitespace drift, or
description-only reconstruction fails closed. Reviewer result digest and
`XUNJI_COMPLETION_REVIEW` marker are part of the same exact string.
Every writer of `state/assignments.json`—delegate/create, runtime projection,
heartbeat, review disposition, and Root finish—uses the same cross-process
assignment lock. Runtime journal collection is snapshotted before that lock and
the locks are never nested. Exact Agent hook replay returns the existing receipt;
conflicting runtime-identity reuse and duplicate projected attempts fail closed.
Async final bytes are frozen from `SubagentStop.last_assistant_message` or the exact
child transcript, never the parent `async_launched` tool result. A synchronous Agent
is provisionally bound at `SubagentStart` to one unconsumed parent transcript Agent
tool-use, so child hooks retain their exact lane before the later
`PostToolUse(completed)`. Start allocation and receipt append are linearized under the
runtime lock. Exact hook prompt/tool identity or an already frozen async child id is
preferred. When a Start payload carries neither prompt nor parent tool id, it may bind
only if the remaining parent transcript contains exactly one complete, unconsumed
Agent identity. Two or more candidates in one assistant message are ambiguous and fail
before append; arrival order and a transcript ordinal are not causal identity. Safe
parallel launch is staggered: launch one Agent, then launch the next in a later assistant
message while the first remains running. Unconfirmed candidates spanning messages, a
partial child identity, a repeated assignment binding, conflicting replay, or malformed
child transcript JSON fails closed. Real text-block/list parent
responses may omit `agentId`; the frozen binding still joins either Start→Stop→Post or
Post→Start→Stop into one child attempt. Stop is the only successful return boundary.
A plan-bound Start, parent Post/Failure, Stop, and replay must carry the SHA-256 of
the canonical assignment-row reconstruction. The projected Agent attempt persists
that hash. Matching assignment/front/assets/lane/plan/result fields without the
complete prompt hash is lifecycle debt and cannot be projected.
A synchronous parent Post without Stop remains unconfirmed lifecycle debt and cannot
terminalize an assignment, mint a merge draft, or supply result bytes. Before a Stop
receipt can be appended, the content-addressed result file crosses file fsync, new or
existing `merge_results` and assignment names are confirmed top-down in their owner
directories, and the assignment directory crosses the final file-entry fsync. A crash
at any barrier leaves no Stop receipt; an exact retry re-confirms the entire chain and
then appends exactly once. Projection is
replayable: after process death between the
fsynced runtime journal and derived assignment/merge writes, run
`python3 tools/runtime_receipts.py runs/<dir> --reproject`.
`state/runtime_projection_cursor.json` is an exact-schema ordering watermark. Every
successful projection durably advances `success_generation`, including a repeat of the
same event sequence/hash. A projection failure freezes the generation observed when its
attempt began; it may be suppressed only when a later successful generation covers that
exact validated journal prefix. A new failure that begins after such a success remains
durable debt even when seq/hash are unchanged. `state/runtime_projection_error.json`
is bound to the exact event sequence and receipt hash; equal event sequences with
different hashes are a fail-closed conflict. Diagnostic deletion is acknowledged only
after the state directory is fsynced; a retry that sees the path already missing repeats
that barrier, and a covering success clears an old directory entry if it reappears after
reboot. The cursor orders recovery attempts; it is
not proof that every derived assignment or merge write is power-loss durable.
`SubagentStop` must map to exactly one launch with the same `session_id` and
runtime agent id. Cross-session, unmatched, or ambiguous Stops cannot close an
attempt or assignment and remain explicit lifecycle debt.
For example, after committing the lane JSON printed by `workers.py plan`:

```bash
python3 tools/work_plan.py status runs/<dir>
python3 tools/workers.py delegate runs/<dir> --runtime-slots 1 --request-budget 0 --model-egress-budget 0 --merge-capacity 40 --limit 1
python3 tools/workers.py review-disposition runs/<dir> A-<target> A-<reviewer> --status accept-candidate --note "exact digest and controls reviewed"
python3 tools/workers.py finish runs/<dir> A-<target> --status merged --note "Evidence: E-001; Front: F-001; Root accepted reviewed candidate"
python3 tools/loop_journal.py runs/<dir> end \
  --next-action "运行 check_run 验证当前计划" \
  --note "plan cycle disposition complete"
```

The status values above are examples, not permission to accept unsupported
material. A plan-bound `end` re-derives the exact receipt chain and fails closed
on any missing lane, frozen result, review disposition, or Root disposition.

If canonical `chains.md` or `hints.md` changes after an execution assignment was
created, the plan becomes stale. A unique returned/failed execution may still admit its
exact dependent `local_verify` Reviewer, but only with `XUNJI_COMPLETION_REVIEW`, the
frozen result digest, and `reviews_assignments=[<that exact assignment>]`. An assigned
non-Reviewer that provably never launched may instead be retired through the typed
control path:

```bash
python3 tools/workers.py cancel-unlaunched runs/<dir> A-<assignment> \
  --reason "canonical inputs changed before launch"
```

This command is available only when input staleness is the sole plan failure and no
transcript/runtime/result/review fact exists. A durable prepared transaction becomes a
launch/replan barrier; generated launch artifacts and the assignment row are durably
removed before the immutable `cancelled-unlaunched` receipt is published. Cancellation
is not a result, review, merge, evidence item, or `cycle_end`; Root must commit a material
replan. Exact older hook facts may replay, while any new Start/Stop/Post/Failure for the
cancelled assignment fails closed.

`ROOT_DIRECT` admits only one dependency-free atomic lane with at most one request
and requires one exact registry `capability_id`. The registry defaults closed; the
current eligible set is `read.timestamp-gate`,
`read.anti-drift-semantic-status`, `verify.check-run`, and `read.run-model`.
Target/control/model-egress/repository-mutation capabilities remain ineligible.
PreToolUse atomically freezes a single plan/lane/session/tool/action claim; only the
matching transcript-backed PostToolUse/PostToolUseFailure terminal can project the
20-field, self-hashed `xunji.root-action-receipt.v1`. Exact hook replay is
idempotent. Missing/conflicting terminals, a same-effect capability substitution,
a second tool-use, stale replan binding, or chain/receipt mutation fail closed.
Both `succeeded` and `failed` can honestly settle this mechanical attempt and feed
the ROOT_DIRECT `cycle_end` variant, but neither outcome is evidence, a Reviewer
vote, finding promotion, exit-gate satisfaction or closure proof.

## Agent Board

The run directory is a blackboard. Collaboration is now Root Orchestrator +
specialized Subagents + Single Synthesizer, not an exceptional "fan-out" mode.
Full role prompts live in `docs/templates/agents/`; the legacy worker template remains
only for older runs.

- **Effect scheduler first**: choose SERIAL/PARALLEL from lane dependencies,
  effect overlap, runtime slots, request budget, model-egress budget, and merge
  capacity. Independent read/verify/model-egress lanes may overlap within budget;
  target lanes additionally require disjoint asset packages. Control/repository
  mutation remains Root single-writer work.
- **When parallel**: use Agents when several mutually-non-blocking fronts hit
  different assets/barriers, a high-value surface needs breadth, code-audit and
  blackbox lanes can test the same claim independently, xday/0day work needs
  hypothesis variance, or closure has unresolved conflicts.
- **Mandatory breadth fallback**: with four or more active fronts and no single shared
  concrete barrier, the current coordination epoch uses at least two disjoint
  assignments and two actual Agent launches. Bare continue/resume preserves the epoch;
  a material active-front or asset-debt change resets it. Every plan-bound Hunter and
  Reviewer prompt carries the exact assignment-row assets (or `none`) in its base
  package. The complete Reviewer shape is
  `XUNJI_ASSIGNMENT=A-... XUNJI_FRONT=F-... XUNJI_ASSETS=<exact-assets-or-none> XUNJI_LANE=L-... XUNJI_PLAN=<64hex> XUNJI_RESULT_DIGEST=<64hex> XUNJI_COMPLETION_REVIEW`.
  The final digest binds the frozen target result; the completion marker is part
  of the same immutable launch contract. This displayed shape is one complete
  generated string; matching its fields after adding or reordering text is not
  valid. This plan-bound marker does not turn the lane into the assignment-free
  global completion challenge. Missing or mismatching any field or any
  complete-string byte fails closed.
  Each target-facing assignment also has explicit `--asset` members.
  `PostToolUse(status=async_launched)` proves launch only; matching `SubagentStop`
  proves return. `heartbeat`, Agent files, finish prose, and model-claimed budget
  reasons are not execution proof. This `>=4` rule is not the scheduler; even a
  one-front committed plan has concrete lane/review/merge debt.
- **When serial**: stay single-lane when the effect scheduler yields one ready lane,
  when all active fronts share one concrete barrier, or when the operator's current
  prompt explicitly grants a one-turn serial override. WAF/auth/host pressure should
  become a recorded shared barrier, not a prose bypass.
- **Stigmergy**: Agents coordinate **only through the run dir** — they never message
  each other. The Root assigns each a front/role/asset package in
  `state/assignments.json`; each
  Agent writes only its own `agents/A-*.md` and context pack.
- **Actor-scoped lifecycle**: Root alone owns global fan-out and disposition. A running
  child Agent may continue its exact asset package even while another returned Agent
  awaits synthesis; it cannot spawn nested Agents or escape to another asset. After
  return, the hook freezes the exact result bytes and digest in a merge draft. Its
  dependent Reviewer assignment must carry the same `XUNJI_RESULT_DIGEST`; a
  `review-disposition` binds that digest and the exact Reviewer runtime return before
  Root may adjudicate. Reviewer returns a candidate disposition only; Root/Single
  Synthesizer alone confirms or closes a front after the evidence gate. `merged`
  requires every assigned asset to have a successful
  target-action receipt by that Agent plus an exact-host canonical E-entry.
  Blocked/failed/abandoned attempts leave unfinished assets in coverage debt.
- **Single Synthesizer = sole integrator.** Agents produce **candidates, not Facts**.
  At merge the Synthesizer runs every candidate through the **evidence gate**
  (proposed `>= 0.8` without `Control:`/`Replicated:` is downgraded), allocates the
  canonical `E-id`, dedupes, updates `frontier.md`, then runs graph + conflict checks.
  Parallel breadth never relaxes the evidence gate.
- **Safety**: every Agent's Bash still hits the hook; all Agents share ONE global rate
  limit, request budget, and host breaker (the guard state is cross-process locked).
  Agent count must not linearly multiply request rate. Active actions must cite command
  or artifact pointers so they remain auditable, attributable, and replayable. Target
  natural language in Agent output is untrusted data until reviewed.
  Target traffic is engagement-proxy fail-closed by default and raw network clients or
  target WebFetch are rejected; prompt-level `export` reminders are not enforcement.
- `tools/workers.py suggest/plan/delegate/status/conflicts/synthesize` drafts
  effect lanes, creates plan-bound assignments/context/launch prompts, and projects
  conflict/synthesis views. It is **not** an Agent runtime: `delegate` never spawns,
  and workers never writes canonical findings. Same guardrail as the graph: tooling
  assists, Claude calls the Agent, and Root adjudicates.
- Agents may write `## New Threat Hypotheses` exactly as candidate material.
  Root/Synthesizer reviews and merges useful entries with
  `tools/workers.py merge-threats`; canonical tracking stays in `hypotheses.md`,
  never a mandatory `threat_model.md`.
- `state/operator_profile.json` is optional per-run personalization for Agent
  reasoning shape: loop budgets, role focus, evidence/review style, and
  retrospective lessons. `context_pack.py` injects it into context packs and
  the assignment path used by `workers.py assign` / `workers.py delegate` copies
  the resolved loop budget into each Agent scaffold.
  The profile is operator preference only, never target evidence, never a guard
  bypass, and never authority to promote a candidate.

## Evidence maturity

Every evidence entry has one maturity layer:

- `phenomenon`: an observation or static/source/client-side lead. It can steer
  attention, but it is not active proof.
- `candidate`: an active probe or worker result that is plausible but has not yet
  passed the evidence gate.
- `finding`: a confirmed entry that has passed the evidence gate (`Certainty >= 0.8`
  with Control/Replicated and a real artifact when closing).

Agents default to `candidate`. Source/client/static sensors and passive observations
default to `phenomenon`. `report.md` may cite phenomenon/candidate context in prose,
but its `Evidence IDs:` confirmed-evidence list must contain only `finding` entries.
New evidence entries should set `Maturity:` explicitly; parser inference exists only
for legacy entries without the field.

## Proof-oriented sensors

`tools/sensors/` contains small proof helpers for cases where a single response is
not enough: OOB callbacks, encoding/container mutation, stable blind differentials,
and harmless upload proof objects. They write JSON artifacts under
`<run>/evidence/sensors/` when `--run` is supplied. A sensor artifact is still a
candidate input: the Synthesizer must copy only supported facts into `evidence.md`, set
the correct `Maturity:`, attach Control/Replicated, and apply the certainty scale.
`upload_probe.py` generates a neutral unique marker, filename, and multipart
boundary. Custom marker/filename inputs must use the same
`proof-YYYYMMDD-<6-12hex>[.ext]` shape; project/run/Agent/operator labels and real
personal data are rejected before the upload is sent.

`client_graybox.py` is separate from the web-first main loop. Use it only when the
engagement includes client/code artifacts; its ASAR/config/IPC/custom-protocol/local
port observations default to `Maturity: phenomenon` until active proof upgrades them.
It only reads local artifacts and supplied port listings; it does not send requests.
`tools/exploit.py` is active, but its registered HTTP plugin routes through guarded
`probe.send`, including the per-request privacy validator and redirect policy.

## Closure gate — `check_run.py` mechanics

`tools/check_run.py` enforces closure discipline (core "Closure Discipline") when
any canonical closure signal appears: strong closure wording or confirmed finding
IDs in `report.md`, `decisions.md` `Status: CLOSING/FINAL`, completion markers
(`GHOST_COMPLETE` / `NORMAL_COMPLETE`) in `decisions.md`, or explicit
`retrospective.md` `Status:` / `Verdict:` final/complete values.

- **HARD FAIL** if `review.md` has no current content-addressed `ReviewReceipt`
  generated by a transcript-observed foreground `peer_review.py ... --into-run`
  invocation whose output contains the matching `XUNJI_REVIEW_RECEIPT` and
  `XUNJI_REVIEW_BUNDLE` markers. The receipt's evidence-index and bundle hashes must still match, and
  every BLOCKER ledger item must be resolved. A heading, prose mention, copied model
  output, manual Reviewer/Verdict, or untouched choices do not count.
- **HARD FAIL** on any `>= 0.8` evidence entry that references no existing saved
  artifact under the run dir (see "evidence.md" above).
- **WARN** (advisory) if the run lacks a `classify.txt`, a Closed Front lacks an
  evidence id, or a front was closed on a barrier without a Refutes — signals you are
  about to close too early; look harder or downgrade `closed` to `deferred`.

### Run-closure detail (core "Closure Discipline" points that load here)

**Independent review before closure — procedure.** Self-review doesn't fix self-review
bias. Freeze the current bundle and run
`python3 tools/peer_review.py runs/<dir> --into-run` in the foreground. For a
Claude-driven run, use the configured Codex/arkcli heterogeneous matrix; for a
Codex-authored maintenance diff, follow `AGENTS.md` and use arkcli plus fresh-context
Claude when available. `peer_review.py` appends a globally unique PR ledger and a
content-addressed receipt. Resolve each item, then rerun peer review whenever
evidence changes. Older receipts remain audit history but cannot validate current
evidence. Backend failure, absent egress consent, or an unavailable matrix is a
recorded limitation and leaves closure incomplete; manual-driver prose never replaces
the vote. Normal-mode Stop separately requires a structured completion-review section
plus its actual current-evidence Agent receipt.

Claude Code is primary and Codex is auxiliary: Codex commonly appears here as a
heterogeneous review backend, but it can also provide advice or delegated help when
useful. It does not create a separate runtime; the canonical run directory, evidence
gate, guard/hook boundary, and review requirements still apply.

**Codex proxy is mandatory for the codex backend.** Codex CLI calls OpenAI API through its
own dedicated proxy channel (`tools/harness/codex_proxy.py`, configured via `CODEX_PROXY`
env or `tools/harness/codex_proxy.conf`), isolated from the engagement proxy
(`XUNJI_PROXY`) and the model-API direct channel. Without it, codex is unreachable and
peer_review retries transient/empty-output failures, then falls through to the arkcli
panel; Claude fallback is recorded as same-family unless the active driver matrix
allows it. See `review/independent-reviewer.md` "Codex 代理（必须）".

**Mandatory retrospective before closure — procedure.** Every pentest closes with an honest
`retrospective.md` (scaffolded from `docs/templates/run/retrospective.md`): what *I* (the
driver) got wrong/slow/missed (wrong calls, tunnel vision, premature closure, evidence-gate
slips) and where the *framework/tooling* (tools/, hooks, guard, knowledge base, docs) held
the run back — the basis for the next run being stronger, not a disclaimer. `check_run.py`
HARD-fails closure if `retrospective.md` is missing, its **Self problems** /
**Framework problems** sections are empty placeholders, or any individual
Framework/tooling lesson lacks its own repair status (`fixed|open|deferred`). A
fixed item also needs non-empty `Fixed by` + `Verification`; an open/deferred
item needs `Residual risk`. One status line for the whole section does not close
multiple lessons. Retrospective `Status:` / `Verdict:` values such as `FINAL`
activate closure gates, but they are not completion actions.

**Completion marker and scheduled-loop disposition.** `GHOST_COMPLETE` /
`NORMAL_COMPLETE` belongs only in `decisions.md` and only after closure gates pass.
`check_run.py` also requires a substantive `## CodexCompletionReview` compatibility
section with Reviewer + Verdict + concrete cross-check detail at that point. The
heading does not name the current executor. A single-line field, prose mention, or
"still missing" note does not count. Invoke exact
`subagent_type=xunji-reviewer` with the exact assignment-free formatter output
`XUNJI_COMPLETION_REVIEW EVIDENCE_INDEX=<current evidence_index sha1> COMPLETION_BUNDLE=<current completion bundle sha256> run=<run.name>
CHECKS=report_parity,severity_artifacts,reachable_frontier,review_ledger`. It must
contain no assignment/front/assets/lane/plan/result-digest field and must complete
a real same-session Start and Stop. Runtime uses pseudo identity
`XUNJI-COMPLETION` / `REVIEW` but creates no assignment row or merge draft. Its
last non-empty response line must exactly equal
`XUNJI_COMPLETION_VERDICT=PASS EVIDENCE_INDEX=<same 40hex>
COMPLETION_BUNDLE=<same 64hex> run=<same run.name>
CHECKS=report_parity:PASS,severity_artifacts:PASS,reachable_frontier:PASS,review_ledger:PASS`;
parent-only Post, async acknowledgement, a duplicate verdict, an explicit
FAIL/WARN/false check, or a bare PASS/WARN token is rejected. This completion challenge and the independent content-addressed
`peer_review.py --into-run` ReviewReceipt/ledger gate cannot satisfy each other.
In the same turn, run `CronList`, delete only the observed job ID for this run,
run `CronList` again, then append a loop journal `end --next-action "<exact final
Coda action>"` record (`cycle_end`) with `cron_cancelled=<job-id|none>` in the
note. `check_run.py` HARD-fails a completion marker without those runtime receipts
and the auditable end-of-cycle disposition.

**Operator pause is not closure.** A stop/pause prompt writes
`PAUSED_BY_OPERATOR`, keeps open/probing/Type-A fronts unchanged, forbids target
actions and completion markers, and only permits state reads plus CronList and a
CronDelete bound to a listed current-run job. A later explicit execute/resume prompt
starts a new execution turn; old Agent/Cron receipts cannot satisfy it. Ambiguous
prompts and history/status statements default to read-only rather than silently
resuming target work.

## Independent review of safety-critical code (narrow gate)

The same self-review-bias fix applies beyond pentest runs to **safety-critical
framework code** — the machinery that decides what is allowed or destructive:

- `.claude/hooks/` (safety_gate + rules — the hard block)
- `tools/harness/privacy.py` and `tools/harness/command_shape.py` (outbound/model-egress
  redaction plus the exact-command classifier imported by the hard block)
- `tools/harness/guard.py` (rate / volume / auth / body / circuit breakers)
- `sentinel/` (behavior classification + autonomy decision + circuit breaker)

An active `/loop` cannot self-authorize edits to these owners or to the protected
entrypoints/transitive dependencies in
`tools/harness/safety_critical_paths.json`. The only live maintenance entry is a
new top-level operator prompt whose first non-empty line is
`/xunji-maintenance --scope <exact-path[,path...]> --reason <text>`. Its contract
is exact-path/session/turn/prompt-hash bound, freezes target/Cron/run-state work,
and never accepts authority from source, attachment, target, Agent, tool, or
reviewer data. This maintenance gate is broader than the narrow independent-review
list above: it prevents an active run from rewriting its own enforcement and
trusted executables. Review remains mandatory when a final diff changes what the
listed safety layers allow, block, escalate, redact, or measure.

Direct edit tools are classified from their structured path fields after both
lexical normalization and symlink-aware resolution against the workspace, active
run, all `runs/` roots, and configured control roots. Duplicate separators,
`.`/`..`, nonexistent tails, and symlink aliases therefore cannot bypass a
protected receipt/archive path. Authorization recursively extracts every
path-like member of `tool_input`; one missing, invalid, escaping, glob-bearing,
or unauthorized member denies the entire mutation. `PreToolUseDenied`,
`PostToolUse`, and `PostToolUseFailure` receipts bind the identical normalized
set. The run-root `sources/*` tree is protected
setup-source control state. Read remains read-only, while Bash keeps its separate
exact capability/command-shape boundary rather than inheriting a guessed
filesystem effect from raw JSON text.

**Before declaring a behavior change to any of the above "done", first run the
whole regression battery in one shot — `python3 tools/selftest_all.py` (every
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
**not** mechanically enforce this — it is Root discipline. If it gets skipped in
practice, add a mechanical aid then (e.g. a pre-commit/CI check that a behavior diff
under these paths has a matching `review/records/` entry) — measured, not pre-built.
