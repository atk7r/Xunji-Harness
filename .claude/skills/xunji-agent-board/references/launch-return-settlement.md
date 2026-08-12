# Launch, Return, And Settlement Contract

Read this reference completely before invoking an Agent or settling a returned
lane. `runtime_receipts.py`, `workers.py`, `loop_journal.py`, and the frozen run
records are authoritative over prose.

## Binary Launch Contract

`workers.py delegate` returns an exact `subagent_type` plus exact `launch_prompt`.
Use those two returned values unchanged in one Agent tool input. `delegate` never
spawns the Agent.

Canonical execution roles map only to `xunji-hunter`; role `review` maps only to
`xunji-reviewer`. Missing, null, blank, `general-purpose`, aliased,
case-shifted, role-swapped, or whitespace-padded types fail closed. The requested
type and actual same-session Start/Stop type must agree.

The complete Hunter prompt has this formatter-owned shape:

```text
XUNJI_ASSIGNMENT=A-... XUNJI_FRONT=F-... XUNJI_ASSETS=h1,h2 XUNJI_LANE=L-... XUNJI_PLAN=<64hex> XUNJI_INSTRUCTION_BUNDLE=<64hex>
```

The dependent Reviewer also binds `XUNJI_RESULT_DIGEST=<64hex>` and its required
completion marker. Complete-string equality is the boundary: do not prepend,
append, normalize, trim, reorder, or rebuild it in `description`.

The instruction digest binds the manifest-selected common/role/live Agent
sources and the generated context/scaffold bytes. Root launch, `SubagentStart`,
and every child PreToolUse revalidate it; a source drift or artifact mismatch is
a blocker requiring material replan/delegate, never in-place repair.

## Launch And Return

- An async Agent Post with `status=async_launched` proves launch only.
- Only one uniquely matching `SubagentStop` from the same Claude session proves
  return and freezes the final assistant response.
- Parent Post without Stop, heartbeat, Agent prose, Task state, copied output,
  completion notification, or an internal max-turn notification is not return.
- Do not configure `maxTurns`. Each Agent must end with a final assistant response;
  near its lane budget it returns a bounded candidate, refutation, or blocker.
- Root alone spawns Agents. Child fan-out is rejected.
- Never put two unbound Agent calls in one assistant message. For real parallel
  work, launch the next Agent in a later message while the prior one runs.
- Turn authority is checked again at every child tool call. A newer explain,
  review, pause, or ambiguous operator turn may therefore deny an already-running
  Hunter's next effect; do not preserve target authority with a background lease.
  Its eventual returned blocker/candidate still crosses the same immutable return
  checkpoint and must receive its exact Reviewer in a later `EXECUTE` turn.

After a completion notification, cross the durable return barrier with the
read-only owner command:

```bash
.venv/bin/python tools/workers.py status
```

Proceed only when that exact assignment is `state=done`. If it is still
`running`, reconcile the derived projection once and repeat the status read:

```bash
.venv/bin/python tools/runtime_receipts.py --reproject
.venv/bin/python tools/workers.py status
```

If `workers.py status` instead identifies one exact completed model result whose
`SubagentStop` was followed immediately by host-authored
`XUNJI_E_RUNTIME_RECEIPT_HOOK_FAILED` feedback, do not wait for a physical Stop or
invent one. Run only the exact typed owner command printed by status:

```bash
.venv/bin/python tools/workers.py recover-hook-failed-stop A-<assignment>
```

Eligibility binds one successful plan-bound launch, one exact `SubagentStart`,
the assignment/lane/plan/prompt/type/result identity, the child's final assistant
bytes, the child final's immediately following host Hook feedback, the parent
transcript's exact completed task notification, the frozen transcript/runtime prefixes, no journaled
Stop, and no later child/runtime activity. The content-addressed recovery
receipt preserves that the physical Stop is missing while projecting only the
authentic returned result. It grants no finding, evidence, review disposition,
merge, front closure, or completion.

There are two mechanically disjoint contracts. Legacy
`xunji.hook-failed-agent-stop.v1` accepts only direct-`turn_contract.py` feedback
whose normalized `returned_at` is at or before the frozen
`2026-08-08T01:10:00Z` cutover, and its ingress hash must be empty. This narrow
migration branch covers the observed pre-wrapper incident class; a direct-Hook
event after the cutover fails closed even if its transcript otherwise matches.
Current `xunji.hook-failed-agent-stop.v2` accepts only
`schema_independent_wrapper` feedback and requires the exact content-addressed
ingress observation captured by the schema-independent wrapper before any
contract-schema import. The project-level ingress has no run owner and is not
canonical lifecycle, assignment, review,
evidence, merge, or closure truth; it can be consumed only after this recovery
owner selects one run-owned launch and Start. Raw ingress bytes or notification
prose can never settle an assignment by themselves.

Exact recovery replay is idempotent. If the receipt is already committed but its
derived assignment/result projection is pending, preserve it and run the exact
`runtime_receipts.py ... --reproject` command shown above, then repeat the exact
`workers.py status` read. Do not delete the receipt, recapture ingress, rewrite the
journal/assignment, or launch a second Reviewer. A late Stop or later child call is
an integrity conflict with the recovery receipt, not authority to replace it.

A separately versioned non-Reviewer failure covers only Claude Code's stream
watchdog terminal shape. If `workers.py status` proves one successful plan-bound
Hunter launch and Start, no Stop, no later child/runtime activity, one exact
host-authored failed task notification ending in
`Agent stalled: no progress for 600s (stream watchdog did not recover)`, and the
same child's final two records are the synthetic
`API Error: Stream idle timeout - no chunks received` followed immediately by
`[Request interrupted by user]`, run only:

```bash
.venv/bin/python tools/workers.py settle-stream-stalled A-<assignment>
```

The `xunji.stream-stalled-agent.v1` receipt binds the assignment/session/tool/
agent/lane/plan/prompt identity, exact Agent description and notification, child
error/interruption UUIDs, runtime launch/Start/head, parent prefix through the
notification, full child transcript, and deterministic failed-result snapshot.
Notification summary/note drift, another API error, another timeout, missing
interruption, Reviewer role, a Stop, later child/runtime activity, transcript
mutation, or ambiguous identity fails closed. The notification's partial
`<result>` remains frozen source data and is never promoted as the Agent result.

This projects `failed`, never `returned`, and grants no evidence, finding, merge,
front closure, or cycle completion. Launch the unique digest-bound Reviewer,
record its disposition, then Root may settle blocked/failed/abandoned but never
merged. Do not resume or relabel the killed attempt; replan the still-open lane
only after this settlement chain completes. Receipt replay is idempotent and any
late Stop/call becomes integrity conflict. OOM, process kill, generic network
loss, other watchdog text, or future host shapes require another versioned
reason and transcript-proof fixture; do not widen this contract by analogy.

Exception: when the foreground Reviewer parent call itself ended with
`[Request interrupted by user for tool use]` after a
`SubagentStart:xunji-reviewer` hook cancellation, do not loop on `--reproject`
or try `SendMessage`. Repeat the registered `.venv/bin/python tools/workers.py delegate`
owner command from `plan-and-delegate.md`. It automatically attempts the narrow
interrupted-Start recovery before ordinary delegation. Recovery succeeds only
when parent and exact child transcripts prove the frozen prompt, hook timeout,
zero assistant/tool activity, zero admitted parent terminal, and no Stop; it
then returns the same durable Reviewer contract. If those facts are absent or
ambiguous, the row remains `running` and this exception gives no authority to
cancel, edit, abandon, or synthesize a Reviewer result.

This Reviewer v1 recovery contract covers only that exact Claude Code interruption shape.
OOM, process kill, a different hook terminal, or any other
pre-model failure must remain `running`/integrity debt until a separately
versioned reason and transcript-proof contract is added with its own fixtures.
Do not widen the v1 reason string or infer equivalence from prose.

A separate non-Reviewer path exists when Claude Code itself has already reported
one started child as user-stopped and permanently non-resumable. Run only the
exact typed owner command named by `workers.py status`:

```bash
.venv/bin/python tools/workers.py settle-stopped A-<assignment>
```

This command requires one exact successful plan-bound Hunter launch, its exact
`SubagentStart`, no `SubagentStop`, and the same parent transcript's structured
`SendMessage` result: `Agent <id> was stopped by the user and won't be resumed...`.
It freezes the parent prefix through that result, the full child transcript, the
validated journal head, and a content-addressed
`xunji.externally-stopped-agent.v1` receipt. Any message drift, different agent,
late child/runtime activity, transcript mutation, OOM/process/network inference,
Reviewer role, or ambiguous identity fails closed.
The parent-prefix hash preserves the exact transcript timestamp bytes while the
receipt normalizes an otherwise valid ISO-8601 instant to canonical millisecond
UTC `Z` form; this harmless spelling normalization does not relax the exact
structured message or identity proof.

Settlement projects the authentic attempt as `failed` and writes a deterministic
failure result under `state/merge_results/`; it never fabricates a return, Stop,
finding, evidence, or successful lane. Repeat the ordinary delegate checkpoint
to create/replay the unique digest-bound Reviewer. After its disposition, Root
may settle `blocked`, `failed`, or `abandoned`, never `merged`. Exact command
replay is idempotent, and late Stop/child calls conflict with the termination
receipt rather than replacing it. The projected `status=failed` is runtime
outcome pending Root disposition, not an earlier Root adjudication; after the
Reviewer receipt, the first non-merged `finish` does not require `--amend`.

If `workers.py status` instead names
`foreign-lifecycle-quarantine-required` or gives event sequences for proven
non-Xunji lifecycle receipts, run the typed supersession owner first:

```bash
.venv/bin/python tools/runtime_receipts.py --quarantine-unowned-lifecycle
.venv/bin/python tools/workers.py status
```

This path never deletes or rewrites `runtime_events.jsonl`. It admits only a
bare Stop with no Xunji Agent type, assignment, parent tool-use, same-session
Start/launch, or assignment-ledger owner; the content-addressed quarantine
receipt binds the original event seq/hash and validated journal head. A Stop
with any Xunji ownership signal remains lifecycle debt and must not use this
recovery.

`status=reconciled` alone is not return proof. If the assignment is still
`running` and none of the exact recovery paths above applies, wait
for hook delivery and repeat this checkpoint; do not end the phase, delegate, or
call `finish`. Root never writes `done`: `SubagentStop` projects it.
Do not express that wait as `sleep ... && workers.py status ...`; it is one
retryable command-shape denial, not framework maintenance. Retry the clean owner
status argv in the same turn and continue from its actual state.

Treat task/completion notifications as wake-up signals only. After `state=done`,
the immutable `state/merge_results/<assignment>/...` bytes and merge-draft digest
are the result; notification prose may be stale or interleaved and must not be
copied into evidence or a disposition note.

Start/Stop/Post ordering variants join only through one frozen causal identity.
Cross-session, Xunji-owned unmatched, ambiguous, duplicated, or conflicting
attempts remain lifecycle debt; never select the newest by arrival order.
Claude-internal lifecycle events with no Xunji causal owner are recorded in a
separate foreign-lifecycle receipt directory and do not become Agent attempts.
A result becomes
journal-eligible only after its immutable file and merge-result directory chain
cross the durability barrier. Retry the same Stop after a pre-journal crash; the
checkpoint above recovers only derived projection.

If a scheduler/operator wake-up arrives during this chain and the Hook reports
`XUNJI_CONTINUATION_COALESCED`, it retained the exact current unended plan turn
binding. Re-read status and continue the unique return/Reviewer/Root settlement
action; do not material-replan or duplicate the Hunter/Reviewer solely because of
that prompt. A different session's strict no-delta wake may instead report
`UserPromptWakeCoalesced` / `XUNJI_E_RUN_BUSY`; it does not supersede the owner
contract but also does not authorize the wake session to settle it. A new
constraint, stale input, ended cycle, or missing coalescing receipt remains an
ordinary fresh/superseding turn.

## Hunter Then Reviewer

After the Hunter Stop freezes bytes, repeat the single registered delegate command
owned by `plan-and-delegate.md`, with budgets justified by the ready Reviewer lane.
That creates the now-ready Reviewer assignment, or idempotently returns the same
durable contract when the assignment already exists but has no authentic launch
attempt. Do not reconstruct a second argv example here. A denied wrong prompt
does not create an attempt and does not strand the assignment: repeat the owner
`delegate --limit 1` command and invoke the returned exact contract.

This remains true when the committed plan is `WORK_PLAN_TURN_STALE`: the old plan
is settlement identity only. The current `EXECUTE` turn must have its own normal
iteration-plan receipt, and only the unique digest/assignment/lane-bound Reviewer
may launch. An already-assigned Reviewer is replayed from its immutable row; it
is never cancelled, recreated, or bypassed by replan. If an old non-Reviewer
assignment has no authentic launch attempt,
settle it with `cancel-unlaunched`; do not re-run it or replan around either kind
of assignment debt. Exact parent `PreToolUseDenied Agent` receipts prove their
matching transcript tool-uses never launched and therefore do not block this
cancellation or Reviewer contract replay. A parent `PostToolUseFailure`,
successful Post, Start/Stop, or child action is an attempt and must not be
relabeled as unlaunched. Current offline/target denial narrows external effects;
it does not revoke this local settlement owner.

The interrupted-Start exception does not relabel an admitted
`PostToolUseFailure`. It applies only when the parent transcript reports the
client interruption but no matching Agent terminal entered the runtime journal,
and the child sidechain proves that the Start hook was cancelled before model
execution.

Invoke the returned exact `xunji-reviewer` binary contract. Its result digest
must match the frozen Hunter bytes. Reviewer supplies a candidate disposition;
Root/Single Synthesizer decides what canonical evidence or front state follows.

## Review And Root Settlement

Choose statuses from the returned evidence; the command grammar does not choose a
disposition or grant merge authority:

```bash
.venv/bin/python tools/workers.py review-disposition A-<reviewer> --status <accept-candidate|needs-control|duplicate|refute|out-of-scope|retry|blocked>
.venv/bin/python tools/workers.py finish A-<target> --status <merged|blocked|failed|abandoned>
```

These short forms preserve Root judgment in the status enum while the owner
derives the active run, target/Reviewer binding, frozen-result digest note, front,
and canonical anchors. The longer explicit-run/note forms remain historical and
operator compatibility only; Claude does not reconstruct them.

For an accepted target-effect result, `review-disposition` verifies that the
frozen Hunter and Reviewer name the same run-local artifact set, every file
exists, and each replay sidecar binds its request/response. Replay v2 keeps
full-wire `wire_len`/`wire_sha1` separate from capped
`saved_body_meta.len`/`saved_body_meta.sha1`; a truncated saved body is valid
partial storage and cannot be compared to the full wire hash. Only a complete
validated chunk manifest upgrades `wire_verified=true`. Use the resulting
`VERIFIED_ARTIFACT` wire/saved/truncation fields as factual input to canonical
evidence; never clear a digest or substitute notification prose.

Before `merged`, verify every assigned asset has the required transcript-backed
target receipt and the frozen candidate has any control/replay evidence needed for
later promotion. Root `finish` accepts the reviewed result into synthesis; it does
not itself create an E-id or finding. A zero-tool or partial package cannot merge.
The receipt owner derives asset activity only from the successful target tool's
destination-bearing input. Bash must revalidate as one exact registered target
capability and only its target-bearing argv slots count; typed tools use destination
fields. Payload/header/save values, arbitrary URL-shaped argv, `description`, and
prompt prose never count. URL destinations
normalize an omitted default port to `https=443` or `http=80`; an explicit
assignment port must match that effective endpoint exactly. This interpretation is
also applied to existing immutable receipts whose frozen input contains a parseable
destination. Missing or ambiguous identity remains fail-closed settlement debt; do
not edit the journal or replay an already successful request as a workaround.
`blocked`, `failed`, and
`abandoned` use the literal note grammar `Reason: <exact barrier>; Front: F-xxx`;
optional E/D anchors must already exist. These statuses preserve unresolved
coverage debt.
`done` means returned but not Root-disposed; it is not a valid Root-authored
`finish` transition.
After `review-disposition`, obey its `NEXT_OWNER_ACTION` and perform Root `finish`
before canonical promotion or successor delegation. `needs-control`/`retry` means
the review of these frozen bytes is complete but the attempt must settle as the
evidence-supported `blocked`/`failed` state before the planned control/retry lane
can unlock. After every `finish`, obey its
next action: a fresh plan routes to `delegate`; materially changed inputs route to
owner-generated replan with inherited completed lanes; no debt routes to typed
`cycle_end`. Keep the assigned front open until that route settles.
The assignment's typed `tool_call_limit` covers every attempted child call from
Agent start, including the four binding Reads and denials; an RDT loop budget
cannot raise it. `SubagentStart` freezes the value, and PreToolUse atomically
appends one idempotent call claim before any later policy decision. Calls above
the limit receive `XUNJI_E_AGENT_TOOL_CALL_LIMIT_EXCEEDED` before tool execution;
return the best supported disposition instead of attempting another call.

An adjudicated terminal state is immutable through ordinary `finish`. Correct an
incorrect note explicitly while preserving history:

```bash
.venv/bin/python tools/workers.py finish runs/<dir> A-web-hunter-002 --status blocked --note "Reason: corrected barrier; Front: F-002" --amend
```

Amendment is the deliberate operator-compatible exception: changing an already
audited terminal decision requires explicit run, exact replacement note, and
`--amend`; the ordinary short form never rewrites history.

Only anchors in canonical `evidence.md`, `frontier.md`, or `decisions.md` count;
an artifact file alone is not an E-id.

## Typed Cycle End

After every lane has its required return/failure, Reviewer disposition, and Root
disposition, derive typed `cycle_end` through the cycle/journal owner:

```bash
.venv/bin/python tools/loop_journal.py end --action <replan|delegate|verify|review|wait|complete> --front F-<id>
```

`complete` takes no `--front`; every other action binds one exact active front.
The owner derives the stable note and display text. The final Coda must project
the receipt's `next_action` exactly; do not append `--next-action` or `--note`.
Missing, stale, duplicate, or out-of-order debt fails closed.

Typed `cycle_end` settles this committed plan cycle only. It does not close its
front or the engagement. If target effects were denied and network classes remain
unruled, preserve that front as open/deferred, record the barrier without an E-id,
and project the exact next evidence action in Coda. `STRUCTURAL_PASS` or warnings
from `check_run` never justify a finding, front closure, or “Residual risk: none”.

Before synthesis/closure, inspect Agent, lifecycle, merge, and conflict debt in the
following owner-defined order:

```bash
.venv/bin/python tools/workers.py agent-check
.venv/bin/python tools/workers.py lifecycle-check --closure
.venv/bin/python tools/workers.py merge-check
.venv/bin/python tools/workers.py conflicts
.venv/bin/python tools/workers.py synthesize
```

Treat runtime projection diagnostics as unresolved until a later validated
generation covers the journal prefix; same-sequence hash conflicts remain debt.

## Global Completion Is Separate

The global completion challenge is a separate assignment-free Reviewer envelope,
not a plan-bound lane and not an independent peer-review replacement. It is
authorized only by the current zero-lane S3 `COMPLETION_REVIEW` plan. Run
`.venv/bin/python tools/workers.py completion-review` and use the printed Agent
`tool_input` byte-for-byte. Read the exact formatter-owned prompt and verdict contract in
`docs/WORKFLOW-reference.md` "Assignment-free global completion Reviewer" and the Agent boundary in
`.claude/agents/xunji-reviewer.md`; do not reconstruct placeholder hashes or the
final line from this summary.

It requires a real same-session Reviewer Start and Stop and creates only the
pseudo `XUNJI-COMPLETION` / `REVIEW` lifecycle receipt. It creates no assignment,
immutable plan result, merge draft, review disposition, evidence item, or closure
authority. The independent content-addressed ReviewReceipt remains a separate
gate owned by `xunji-reviewops`. After the typed cycle end, return to
`xunji-run-lifecycle`: keep report READY, run check/Cron reconciliation, and use
completion transaction prepare/commit. Agent Board must never write report FINAL
or a completion marker directly.
