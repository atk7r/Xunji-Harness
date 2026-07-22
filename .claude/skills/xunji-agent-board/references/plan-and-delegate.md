# Plan And Delegate Contract

Read this reference completely when Claude Root needs to choose a stage/mode,
commit lanes, delegate ready work, or retire a stale unlaunched assignment. The
CLI validators and persisted receipts are authoritative over this explanation.

## Plan From The Completed State Pass

The fixed `loop_prompt` owns the every-cycle graph/status/lifecycle/conflict state
pass. Do not copy or repeat that pass here. After it is complete, draft ready lanes
with the Agent Board planner:

```bash
python3 tools/workers.py suggest runs/<dir>
python3 tools/workers.py plan runs/<dir> --limit 2
```

`workers.py suggest` and `workers.py plan` already consume the saturation model
through their registered owner path. Do not invoke the unregistered
`saturation.py` helper directly from a live run.

Root chooses the reversible goal view:

- `S1`: information collection after meaningful target/scope exists.
- `S2`: testing and continuous review after usable coverage/front state exists.
- `S3`: closure only after open/Type-A fronts and plan-bound merge/review debt are
  absent.

These stages are derived goals, not canonical truth or Router phases. A premise
change may move backward only through a material replan after the prior plan is
debt-free and has typed `cycle_end`.

## Commit The Plan

Treat a successful planner draft as indivisible. Commit it through the planner
owner so Claude never transports, splits, or shell-wraps lane JSON:

```bash
python3 tools/workers.py commit-plan runs/<dir> --stage <S1|S2|S3> --objective "<current reversible goal>" --mode <SERIAL_AGENT|PARALLEL_AGENTS> --reason "<current scheduler reason>" --exit-gate "<evidence-bound exit>" --limit <1|2>
```

`commit-plan` recomputes the current complete draft and calls the existing
`work_plan` transaction owner once. On a material same-run replan, the owner
inherits only identity-equal lanes already proven complete by Agent return,
Reviewer disposition, and Root settlement, then commits the unfinished suffix;
never repeat an inherited lane. "Ready" applies only after that commit when
`delegate` selects dependency-satisfied work; it never selects a plan subset.
If it exits nonzero with `NO_STRONG_CANDIDATE`, do not commit, invent lanes, or
copy a documentation example. Repair the canonical frontier/coverage mapping,
rerun the state pass, then rerun the planner. For diagnostics, `workers.py plan`
still prints the exact lanes. Do not manually copy them into `work_plan.py commit`
during a live Agent-mode run.

`work_plan.py` is the sole plan transaction writer. A current plan requires its
committed v2 receipt, content-addressed archive, and intact prior-receipt lineage.
Prepared, missing, unreadable, unarchived, broken, or mismatched provenance fails
closed. `migrate-legacy` is only for an exactly reconstructible pre-transaction or
native-v1 state; it cannot mint missing history.

Input-stale blocks new execution, but the digest proves only that some input
changed; never infer a file path from it. Terminal lanes settle against the bound
transaction before typed `cycle_end`; do not replan to manufacture `current=true`.
Only independently observed material canonical change justifies stale unlaunched
cancellation and replan.

If the gate returns `XUNJI_E_LIFECYCLE_EXACT_ARGV_REQUIRED` with
`invalid-argv`, the command did not execute. Rebuild the complete `commit-plan`
direct argv and retry in the same operator turn. Do not add pipes,
redirects, wrappers, environment assignments, or `python -c` inspection.

## Delegate Ready Work

Budget values must match the ready lanes and current shared capacity. Zero
request/model-egress budgets are valid only when ready lanes need neither target
requests nor model egress:

```bash
python3 tools/workers.py delegate runs/<dir> --runtime-slots <n> --request-budget <n> --model-egress-budget <n> --merge-capacity <n> --limit <n>
```

The owner supplies the normal typed `tool_call_limit=24`; use the optional
`--tool-call-limit <5-64>` override only when the lane has a concrete smaller or
larger bound. It counts all child calls, including binding reads and denials.
Each committed lane's `request_budget` is also copied into the assignment and
frozen by `SubagentStart`. It counts attempted target calls only; child PreToolUse
claims them atomically, so concurrent calls cannot oversubscribe the lane and the
first over-budget call is denied before execution. An exhausted-budget notice
means return the evidence already collected, not vary the method/path/argv.
`delegate` atomically creates only ready assignments, exact context
packs, and binary launch contracts. It does not spawn. Every target lane must carry a
bounded asset package present in coverage and named by its front. Unknown roles,
overlapping target packages, stale plan digests, or inadequate budgets fail
closed.

Invoke Agents only after reading `launch-return-settlement.md`.
`no unassigned lane has satisfied runtime dependencies` routes back to that
reference's durable-return checkpoint; it does not authorize `finish`, replan, or
an invented transition.

## Scheduler Boundaries

- Use `SERIAL_AGENT` when one result changes the next lane, one shared barrier
  dominates, or effect overlap prevents safe concurrency.
- Use `PARALLEL_AGENTS` only for dependency-free/effect-compatible lanes within
  runtime, request, egress, and merge capacity.
- Complex serial work remains Agent work. Root does not absorb it merely because
  parallelism is inappropriate.
- `ROOT_DIRECT` accepts one dependency-free atomic lane, at most one request, and
  one exact `root_direct_eligible` capability. A terminal receipt settles only
  that mechanical action; it proves no evidence, review, exit gate, or closure.

## Stale Plan Settlement

If conditional canonical inputs such as `chains.md` or `hints.md` stale the plan,
do not reuse an unlaunched assignment. A returned/failed execution can unlock
only its exact dependent Reviewer. A non-Reviewer assignment with zero launch
facts may be retired through the typed command:

```bash
python3 tools/workers.py cancel-unlaunched runs/<dir> A-<assignment> --reason "canonical inputs changed before launch"
```

Cancellation is auditable settlement, not a result, review, refutation, merge,
evidence item, or completed cycle. Commit a material replan before replacement
work.
