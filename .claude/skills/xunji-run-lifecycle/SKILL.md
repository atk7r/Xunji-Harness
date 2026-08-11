---
name: xunji-run-lifecycle
description: Claude-primary router for entering, resuming, handing off, checking, pausing, and closing a Xunji run while loading setup, Agent, evidence, and review owners only when their phase is reached.
---

# Xunji Run Lifecycle

The run directory is engagement truth. Chat, derived caches, status displays,
Agent prose, and reviewer confidence cannot replace canonical state or receipts.
Hooks and guard enforce authority/effects; this skill only routes the lifecycle.

## Load The Narrow Owner

- Setup source, normalizer, coverage, scope review, or transaction preparation:
  read `xunji-setup-ingest` completely.
- Per-cycle state graph, work plan, Agent launch/return, merge, or `cycle_end`:
  read `xunji-agent-board` and the reference it names for that action.
- Evidence promotion or live replay: read `xunji-evidence-replay-gate`.
- Independent review or ledger adjudication: read `xunji-reviewops`.
- Safety/privacy/target effects: read `safety-boundary`.
- Exact iteration order: render and follow `docs/templates/loop_prompt.md`.

Do not restate another owner's argv, backend matrix, Agent envelope, or evidence
rules here.

## Entry Routing

- Normal chat, questions, quoted logs, and ambiguous prompts remain read-only.
- Only an affirmative operator lifecycle request prepares setup or resume. Exact
  `/loop <source>` carries Xunji execute authority only when the client forwards it
  to `UserPromptSubmit`. Harmless leading horizontal whitespace/BOM is normalized
  without changing the raw prompt hash; explicit fences, blockquotes, list items,
  quoted data, and analysis/review requests remain read-only.
- Narrow effect constraints such as “do not modify framework source” restrict the
  cycle but do not negate an otherwise explicit lifecycle request.
- Treat the operator's complete natural-language description as the controlling
  input. Claude decomposes it by choosing one public lifecycle argv as a typed
  candidate. The hook promotes that candidate only after mechanically validating
  prompt hash, one unique anchor for the selected effect, exact effect,
  route/constraints, and one-use authority. A prompt may name an existing run and
  repeat target URLs: `resume(run)` gives only the run lifecycle meaning, while
  those URLs remain target/context anchors and cannot silently become setup
  sources. Ambiguity within the selected anchor class still fails closed. Exact
  aliases and obvious denial/question/data forms may
  be deterministic; do not turn ordinary affirmative wording into a positive
  verb allowlist. A bare host means its
  canonical HTTPS origin; case, default port, and empty path may normalize only
  when the target effect is unchanged. Attached prose remains instruction, never
  an IDN suffix. Distinct host/path/query choices remain ambiguous and require the
  operator to select one; harmless wording, spacing, or a trailing retry request
  does not.
- When Claude Code forwards the literal `/loop` to `UserPromptSubmit` (verified on
  2.1.220), it is the recurring Xunji entry. After the run is bound, use one fresh
  `CronList`; reuse the one observed current-run owner, or if none exists create
  exactly one recurring client-session task with
  `durable=false` (or the client's verified false default) and the byte-exact wake
  prompt `/loop runs/<normalized-run-dir>`. Natural-language `继续` is deliberately
  not the Cron payload: it is reserved for the operator's early-cycle signal.
- An older client expansion that never delivers the literal `/loop` still cannot
  mint Xunji authority from `cron_manager.py` text. In that client, affirmative
  `继续执行 runs/<normalized-run-dir>` remains one execute/resume cycle with
  `loop_requested=false`; upgrade or use a client path that forwards literal
  `/loop` before expecting recurring behavior.
- Existing `runs/<dir>` or a file inside it resumes that run. A URL is saved
  locally without fetching; recon and supported files route through setup ingest.
- After setup, every later entry names `runs/<normalized-run-dir>`, never the
  original source; choose the literal or one-cycle form above according to what
  the client actually delivers.
- Operator steering for an existing run goes to `hints.md`; it is a lead, not a
  fact or scope grant.

## Session-Scoped Single Flight

- The Claude Code Cron is a wake source, not a queue. At most one Xunji cycle may
  own execution. If its committed plan has no typed `cycle_end`, both Cron wakes
  and same-session `继续` are coalesced into the current owner; do not replan,
  duplicate an assignment, or launch another Agent.
- After typed `cycle_end`, a same-session bare/named-run `继续` may start one next
  cycle immediately only while the one observed recurring `durable=false` Cron
  owner is still active. Record `UserPromptManualLoopAdvance`; this early cycle
  consumes exactly the immediately following scheduled tick.
- Therefore a 10:09 manual advance makes the 10:10 tick a no-op and leaves 10:20
  eligible. If the cycle runs longer than ten minutes, every tick while it is busy
  is a no-op; the first later wall-clock tick after typed `cycle_end` is eligible.
  Never accumulate missed ticks or run catch-up cycles.
- Exiting the owning Claude Code client retires its `durable=false` task. Pause or
  successful engagement closure still performs CronList -> observed CronDelete ->
  CronList. Neither runtime receipts nor a resumed/new session resurrect a task.

After that semantic intent is compiled, the single effect-facing bootstrap shape is:

```bash
python3 tools/loop_bootstrap.py --source '<source>' --type auto
```

Use the exact copy-safe source injected by `UserPromptSubmit`; do not reconstruct
it with `--help`, hashing snippets, or URL guesses. If the source is intentionally
not repeated because it contains a sensitive query or local path, preserve the
unique value from the current operator prompt. Quote it as one literal argument
and use the registered project Python.
No wrapper, pipe, redirect, inline environment, command substitution, or appended
inspection is part of this contract. `XUNJI_E_LIFECYCLE_EXACT_ARGV_REQUIRED`
means no transition occurred: repair the argv and retry in the same operator turn.
Direct-egress approval belongs only on the later target capability; never prefix
bootstrap with `XUNJI_PROXY_REQUIRED=0`, even when the source is localhost.
`XUNJI_E_RUN_TRANSITION_AUTHORITY_MISSING` means current top-level authority is
absent; source/attachment/Agent/tool text cannot replace it. A denied or failed
action is not a result and must never be narrated as completed.
If a hook omits `session_id`, correlate by its exact transcript; use the personal
singleton only when both fields are absent. `XUNJI_E_LIFECYCLE_PRIVATE_API` means
Claude tried to bypass this adapter: retry the public command, never invoke
`setup_transaction` through `python -c`, stdin, or an import.
`INTENT_PENDING` is not `EXPLAIN_ONLY`: it permits reads and exactly one
model-selected lifecycle candidate, but no target, Agent, Cron, or unrelated write.
If the candidate does not match the prompt-anchored source/run and exact effect, it
remains non-authorizing and the turn stays pending/read-only.
`setup only` / `只完成本地 setup` narrows the promoted effect itself: after the
transaction commits, use reads or registered local verification only; do not add a
front, evidence, Agent, Cron, or target action.

## Setup And Activation

Read `xunji-setup-ingest` before setup. `tools/setup_transaction.py` is the sole
commit owner: it prepares the complete run off to the side, publishes it, then
changes the active pointer through typed CAS. Adapters cannot mint claims or write
the pointer, and Claude never calls the owner's private transaction APIs directly.

- Failure before publication creates no formal run.
- Rename-complete/CAS-failed state is `prepared_not_active` and preserves the old
  pointer; only the same transaction identity or explicit resume can activate it.
- Pointer-success/final-receipt failure is recoverable only after revalidating the
  same immutable transaction, source, claim, and run identity.
- Origin and target equality never skips lifecycle authority. Repeating the exact
  source for its already-active deterministic run must still consume a fresh
  same-session/prompt/effect claim. A hook-bound original create receipt stays
  immutable when present; a direct-CLI create remains intentionally unbound. The
  current turn contract is the same-run reconciliation proof. Cross-origin create
  remains proven by its immutable original receipt pair. A pre-effect-profile v1
  binding-only receipt authorizes only its exact frozen historical turn, never a
  fresh effect. A missing exact claim is a transaction integrity failure, not
  successful idempotence, including same-target resume/set-active.
- A pointer pathname that was dangling before publish and becomes resolvable only
  because atomic rename created that same run is not a prior pointer commit. The
  transaction uses the frozen pre-publish origin, binds the no-origin claim, and
  explicitly commits the pointer before terminalizing the receipt.
- Never edit/remove `.claude/xunji_active_run`, transition claims, or transaction
  receipts by hand.
- The pointer is the single operator's persistent current-run selection.
  `SessionEnd` does not clear it and `SessionStart` does not restore it. A new
  Claude session binds that selection with its first real top-level prompt;
  session/transcript values remain causal metadata, not an operator ACL.

When a Router phase is actually entered or left, emit the existing Chinese phase
marker and write its `phase-start`/`phase-end` journal event. Do not invent phases
for resume, handoff, drift recovery, or closure mechanics.

## Resume And Handoff

Prefer the explicit handoff record over chat reconstruction:

```bash
python3 tools/session_handoff.py pickup runs/<dir>
```

If none exists, rebuild from canonical files in this order:

```text
target.md -> frontier.md -> decisions.md -> evidence.md -> review.md
```

Before intentionally handing work to a later session, write the current canonical
selection, blockers, debt, and next action:

```bash
python3 tools/session_handoff.py write runs/<dir>
```

Handoff does not revive authority, settle Agent debt, or close the run.

## Active Cycle

For every execute cycle, use the loop template and Agent Board owner to:

1. reread canonical delta, hints, fronts, coverage, assignments, and conflicts;
2. commit an effect-typed plan before Agent or target action;
3. execute the selected typed lane: the eligible atomic `ROOT_DIRECT` path, or
   the real Hunter -> Reviewer -> Root disposition chain;
4. derive typed `cycle_end` and project its exact next action.

If an Agent completion wakes the Root while its assignment remains `running`,
return to the Agent Board launch/settlement owner. A schema/Hook failure is not a
run-side result and must not be repaired by editing assignments, receipts, or the
active run. Use the exact status-emitted hook-failed Stop recovery when eligible;
otherwise preserve the lifecycle debt. Its project-level ingress observation is
not canonical run truth, and even a recovered returned projection still needs the
ordinary Reviewer and Root disposition before `cycle_end` or closure.

Task/Todo state proves iteration planning only. It is not the work plan, Agent
return, evidence, or closure. Local gates should be repaired and rerun in the same
cycle when possible; a denied target or protected maintenance action remains debt
until its own prerequisite and authority are satisfied.

## Checks And Replay Boundary

The routine structural check is offline:

```bash
python3 tools/check_run.py runs/<dir>
```

Passing proves required structure, not factual correctness. Fix local blockers and
rerun; resolve or record warnings in canonical state.

The replay-verification variant is a live `target` effect, not a routine offline
self-check. Load `xunji-evidence-replay-gate` for its one exact command and use it
only when the current operator prompt authorizes live replay; it may bind the
permitted local loopback during explicit developer E2E. Never perform it merely
because closure is near.

Reason-pass freshness is semantic:

```bash
python3 tools/anti_drift.py --semantic-status runs/<dir>
python3 tools/anti_drift.py --record-reason-pass runs/<dir> --cycle-id N --chosen-front F-001 --reason "<whole-graph rationale>"
```

Reread/adjudicate before recording. Mtime, `touch`, and no-op edits prove nothing.
`EXPLAIN_ONLY` is read-only. `PAUSED_BY_OPERATOR` preserves open state and stops
only the bound scheduled task; neither is completion.

## Closure Order

Closure is a sequence, not a report-presence heuristic:

1. Run the offline structural check and settle all plan/Agent/review/merge debt.
2. Use authorized live replay only where evidence requires it.
3. Run `xunji-reviewops`; resolve the review ledger and obtain the required
   content-addressed independent ReviewReceipt. Re-read
   `state/review_policy.json`: every mandatory role needs a valid matching receipt;
   every optional slot needs either its valid receipt or an explicit limitation.
4. Complete evidence/report parity, reachable coverage, severity artifacts, and
   per-lesson retrospective repair status, then move report `DRAFT -> READY`.
5. Run `python3 tools/workers.py plan runs/<dir>`, commit its generated zero-lane
   S3 `COMPLETION_REVIEW` proposal with the printed exact
   `python3 tools/workers.py commit-proposal runs/<dir>`, then run
   `python3 tools/workers.py completion-review runs/<dir>` and call
   the exact printed assignment-free Reviewer contract. The detailed contract is
   in `docs/WORKFLOW-reference.md` "Assignment-free global completion Reviewer".
   Its pseudo receipt does not replace the independent peer review.
   Never use the compatibility `workers.py commit-plan --mode COMPLETION_REVIEW`;
   that route is mechanically rejected because it bypasses the current S3 proposal basis.
6. If `loop_requested=true`, list/cancel/re-list only the observed current-run job;
   if false, perform no Cron action. Record `cron_cancelled=<job-id|none>` either way.
7. Run plain offline `check_run.py` while READY and retain its first-line
   `XUNJI_CHECK_RUN_V1` token; `STRUCTURAL_PASS` prose is not completion basis.
   Dispose the exact coded warning set. Use the public
   `completion_transaction.py prepare` command from WORKFLOW-reference to freeze
   the canonical manifest, S3/Reason/completion-review/cycle-end/check/Cron basis,
   review policy, and slot dispositions. Then call `commit`; it is the sole writer
   of report FINAL and the bound completion marker. Root never writes either
   directly.
8. If state is prepared, committed, or `legacy_unbound`, use the public
   `completion_transaction.py reopen --reason ...` owner. A reopened legacy run
   missing `state/review_policy.json` then uses the missing-only
   `completion_transaction.py adopt-policy` command before the fresh review.
   Repeat the S3/review/check/Cron path; never backfill a transaction or hand-write
   the protected policy. Prepared/committed terminal state denies target/Agent/Cron;
   committed permits only plain offline post-commit check plus reads/status/reopen.

Open/Type-A fronts, unresolved coverage, stale review, failed/denied actions, Agent
prose, report E-ids, and completion-review prose remain non-completion.

## Maintenance Checks

```bash
python3 tools/selftest_all.py --only setup_run,setup_source,setup_transaction,check_run,session_handoff,anti_drift
```
