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
XUNJI_ASSIGNMENT=A-... XUNJI_FRONT=F-... XUNJI_ASSETS=h1,h2 XUNJI_LANE=L-... XUNJI_PLAN=<64hex>
```

The dependent Reviewer also binds `XUNJI_RESULT_DIGEST=<64hex>` and its required
completion marker. Complete-string equality is the boundary: do not prepend,
append, normalize, trim, reorder, or rebuild it in `description`.

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

Before `merged`, verify every assigned asset has the required transcript-backed
target receipt and canonical E-entry, plus any control/replay evidence needed for
promotion. A zero-tool or partial package cannot merge. `blocked`, `failed`, and
`abandoned` use the literal note grammar `Reason: <exact barrier>; Front: F-xxx`;
optional E/D anchors must already exist. These statuses preserve unresolved
coverage debt.
`done` means returned but not Root-disposed; it is not a valid Root-authored
`finish` transition.
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
