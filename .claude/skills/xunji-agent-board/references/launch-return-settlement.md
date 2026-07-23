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
python3 tools/workers.py status runs/<dir>
```

Proceed only when that exact assignment is `state=done`. If it is still
`running`, reconcile the derived projection once and repeat the status read:

```bash
python3 tools/runtime_receipts.py runs/<dir> --reproject
python3 tools/workers.py status runs/<dir>
```

`status=reconciled` alone is not return proof. If the assignment is still
`running`, wait for hook delivery and repeat this checkpoint; do not end the
phase, delegate, or call `finish`. Root never writes `done`: `SubagentStop`
projects it.
Do not express that wait as `sleep ... && workers.py status ...`; it is one
retryable command-shape denial, not framework maintenance. Retry the clean owner
status argv in the same turn and continue from its actual state.

Treat task/completion notifications as wake-up signals only. After `state=done`,
the immutable `state/merge_results/<assignment>/...` bytes and merge-draft digest
are the result; notification prose may be stale or interleaved and must not be
copied into evidence or a disposition note.

Start/Stop/Post ordering variants join only through one frozen causal identity.
Cross-session, unmatched, ambiguous, duplicated, or conflicting attempts remain
lifecycle debt; never select the newest by arrival order. A result becomes
journal-eligible only after its immutable file and merge-result directory chain
cross the durability barrier. Retry the same Stop after a pre-journal crash; the
checkpoint above recovers only derived projection.

## Hunter Then Reviewer

After the Hunter Stop freezes bytes, repeat the single registered delegate command
owned by `plan-and-delegate.md`, with budgets justified by the ready Reviewer lane.
That creates the now-ready Reviewer assignment; do not reconstruct a second argv
example here.

This remains true when the committed plan is `WORK_PLAN_TURN_STALE`: the old plan
is settlement identity only. The current `EXECUTE` turn must have its own normal
iteration-plan receipt, and only the unique digest/assignment/lane-bound Reviewer
may launch. If an old non-Reviewer assignment has no authentic launch attempt,
settle it with `cancel-unlaunched`; do not re-run it or replan around either kind
of assignment debt.

Invoke the returned exact `xunji-reviewer` binary contract. Its result digest
must match the frozen Hunter bytes. Reviewer supplies a candidate disposition;
Root/Single Synthesizer decides what canonical evidence or front state follows.

## Review And Root Settlement

Choose statuses from the returned evidence; the command grammar does not choose a
disposition or grant merge authority:

```bash
python3 tools/workers.py review-disposition runs/<dir> A-<target> A-<reviewer> --status <accept-candidate|needs-control|duplicate|refute|out-of-scope|retry|blocked> --note "<digest-bound review reason>"
python3 tools/workers.py finish runs/<dir> A-<target> --status <merged|blocked|failed|abandoned> --note "<status-specific literal grammar below>"
```

For an accepted target-effect result, `review-disposition` verifies that the
frozen Hunter and Reviewer name the same run-local artifact set, every file
exists, and each replay sidecar binds its request/response, saved body, and body
hash. Use its `VERIFIED_ARTIFACT` lines as factual input to canonical evidence;
never substitute notification prose.

Before `merged`, verify every assigned asset has the required transcript-backed
target receipt and the frozen candidate has any control/replay evidence needed for
later promotion. Root `finish` accepts the reviewed result into synthesis; it does
not itself create an E-id or finding. A zero-tool or partial package cannot merge.
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
python3 tools/workers.py finish runs/<dir> A-web-hunter-002 --status blocked --note "Reason: corrected barrier; Front: F-002" --amend
```

Only anchors in canonical `evidence.md`, `frontier.md`, or `decisions.md` count;
an artifact file alone is not an E-id.

## Typed Cycle End

After every lane has its required return/failure, Reviewer disposition, and Root
disposition, derive typed `cycle_end` through the cycle/journal owner:

```bash
python3 tools/loop_journal.py runs/<dir> end --next-action "运行 check_run 验证当前计划" --note "plan cycle disposition complete"
```

The example next action is not universal. Use the one concrete action justified by
the current plan; the final Coda must project the receipt's `next_action` exactly.
Missing, stale, duplicate, or out-of-order debt fails closed.

Typed `cycle_end` settles this committed plan cycle only. It does not close its
front or the engagement. If target effects were denied and network classes remain
unruled, preserve that front as open/deferred, record the barrier without an E-id,
and project the exact next evidence action in Coda. `STRUCTURAL_PASS` or warnings
from `check_run` never justify a finding, front closure, or “Residual risk: none”.

Before synthesis/closure, inspect Agent, lifecycle, merge, and conflict debt in the
following owner-defined order:

```bash
python3 tools/workers.py agent-check runs/<dir>
python3 tools/workers.py lifecycle-check runs/<dir> --closure
python3 tools/workers.py merge-check runs/<dir>
python3 tools/workers.py conflicts runs/<dir>
python3 tools/workers.py synthesize runs/<dir>
```

Treat runtime projection diagnostics as unresolved until a later validated
generation covers the journal prefix; same-sequence hash conflicts remain debt.

## Global Completion Is Separate

The global completion challenge is a separate assignment-free Reviewer envelope,
not a plan-bound lane and not an independent peer-review replacement. Read the
exact formatter-owned prompt and verdict contract in
`docs/WORKFLOW-reference.md` "Assignment-free global completion Reviewer" and the Agent boundary in
`.claude/agents/xunji-reviewer.md`; do not reconstruct placeholder hashes or the
final line from this summary.

It requires a real same-session Reviewer Start and Stop and creates only the
pseudo `XUNJI-COMPLETION` / `REVIEW` lifecycle receipt. It creates no assignment,
immutable plan result, merge draft, review disposition, evidence item, or closure
authority. The independent content-addressed ReviewReceipt remains a separate
gate owned by `xunji-reviewops`.
