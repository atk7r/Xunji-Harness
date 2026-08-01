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

If that state pass exposes a product/version, CVE/CNVD id, advisory-shaped lead,
or current configuration fact, load `.claude/skills/web-research/SKILL.md` and
complete its time-gate -> knowledge-owner -> public WebSearch -> structured-lead
route before committing another target lane. This Root research route is not an
OFFLINE or TARGET Agent lane and must not be deferred to report cleanup.

Root chooses the reversible goal view:

- `S1`: information collection after meaningful target/scope exists.
- `S2`: testing and continuous review after usable coverage/front state exists.
- `S3`: closure only after open/Type-A fronts and plan-bound merge/review debt are
  absent.

These stages are derived goals, not canonical truth or Router phases. A premise
change may move backward only through a material replan after the prior plan is
debt-free and has typed `cycle_end`.

## Commit The Plan

`workers.py plan` atomically writes `state/work_plan_proposal.json`. This is a
derived, non-authorizing seed bound to the exact current turn and canonical input
digest. It is deliberately editable by Root: the generated six-step front chain
is a conservative fallback, not a mandatory attack playbook.

Before commit, use the built-in Edit/Write tool on that exact proposal file:

- keep `schema` and `basis` byte-for-byte semantically unchanged;
- fill `macro_stage`, `objective`, `delegation_reason`, and `exit_gate` from the
  current natural-language goal and state graph;
- keep, omit, reorder, or add execution/Reviewer pairs as the actual strategy
  requires, up to 16 total lanes;
- give every execution lane exactly one `role=review`, `effect=local_verify`
  Reviewer whose sole dependency is that execution lane;
- make a later execution depend on prior Reviewer lane ids when its action should
  change based on earlier results;
- use multiple lanes under the same F-id for distinct investigation tasks. Do not
  split one semantic front into fake sub-fronts merely to increase Agent count;
- use `SERIAL_AGENT` for one ready execution chain and `PARALLEL_AGENTS` for at
  least two dependency-free, effect-compatible ready executions.

Then commit the exact proposal through the single transaction owner:

```bash
python3 tools/workers.py commit-proposal runs/<dir>
```

`commit-proposal` reads only the exact in-run regular proposal, rejects unknown
fields, stale basis, unknown fronts/assets, impossible assignment scope, invalid
effects, dependency cycles, missing/duplicate Reviewers, same-asset ready TARGET
overlap, and invalid mode topology, then calls the existing `work_plan`
transaction owner once. Proposal prose, Agent output, and imported target text
cannot authorize anything by writing this file; only the validated transaction
can authorize delegation.

On a material same-run replan, the owner
inherits only identity-equal lanes already proven complete by Agent return,
Reviewer disposition, and Root settlement, then commits the unfinished suffix;
never repeat an inherited lane. "Ready" applies only after that commit when
`delegate` selects dependency-satisfied work; it never selects a plan subset.
If `workers.py plan` exits nonzero with `NO_STRONG_CANDIDATE`, do not commit, invent lanes,
or copy a documentation example. Repair the canonical
frontier/coverage mapping and rerun the state pass. If commit reports
`WORK_PLAN_PROPOSAL_STALE`, rerun
`workers.py plan` before editing a fresh proposal. For a structural proposal
error, repair that same derived file and retry `commit-proposal`; never bypass it
with direct `work_plan.py commit` or shell-transported lane JSON.

The planner prints one `topology_mode` for the generated seed. It separately
labels candidate/asset/barrier counts as breadth signals, never as a scheduler
verdict. The commit receipt records proposal hash, typed objective, fronts, ready
lane count, and whether execution mode matches the committed topology. Actual
delegate width remains bounded by runtime slots, target/model-egress budgets, and
merge capacity. This is observable validation, not a prose parser: Root retains
strategy ownership.

`work_plan.py` is the sole plan transaction writer. A current plan requires its
committed v2 receipt, content-addressed archive, and intact prior-receipt lineage.
Prepared, missing, unreadable, unarchived, broken, or mismatched provenance fails
closed. `migrate-legacy` is only for an exactly reconstructible pre-transaction or
native-v1 state; it cannot mint missing history.

Input-stale or turn-stale blocks new execution; the digest proves only that some input
changed, while the old plan proves only its immutable work identity. Never infer a
changed file path or revive its execution authority.
Terminal lanes settle against the bound transaction before typed `cycle_end`;
do not replan to manufacture `current=true`.
Only a newer prompt-bound authority epoch, an independently observed material
canonical change, or both justify stale unlaunched cancellation and replan. The
v2 cancellation receipt records that basis explicitly; identical prompt prose in
a later turn is still a new authority epoch and does not revive the old Hunter.

When the current turn explicitly denies target egress, the planner emits only the
offline Hunter and its Reviewer. That pair is the complete offline suffix; do not
add a verification pair for a target artifact that does not exist.

If the gate returns `XUNJI_E_LIFECYCLE_EXACT_ARGV_REQUIRED` with
`invalid-argv`, the command did not execute. Rebuild the exact direct
`commit-proposal` argv and retry in the same operator turn. Do not add pipes,
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

If a ready lane already has exactly one durable `assigned` row with no authentic
launch attempt, `delegate` does not allocate another assignment. It revalidates
the row, instruction bundle, generated artifacts, plan/lane binding, and runtime
journal, then returns the same exact binary launch contract without mutating the
assignment ledger. This recovery is especially important for a stale plan's
mandatory Reviewer after a denied or interrupted parent launch. Never reconstruct
the prompt from chat text. A replay whose row, bundle, dependency result digest,
tool-call limit, or runtime state differs fails closed.

One interrupted launch has a narrower typed bridge into that same no-attempt
replay. If a Reviewer `SubagentStart` receipt exists but Claude cancelled the
Start hook before the child produced any assistant message or tool call,
`delegate` first verifies the exact parent interrupted tool result, the exact
child prompt, the timed-out `SubagentStart:xunji-reviewer` hook, and the absence
of child claims, parent terminal receipts, and `SubagentStop`. It then appends a
content-addressed interrupted-Start receipt, leaves `runtime_events.jsonl`
untouched, resets only the derived attempt on the same Reviewer row, and returns
the original persisted launch contract. Any ambiguous or later lifecycle
activity stays `running` debt. This is not Reviewer cancellation, recreation, or
force settlement.

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

If conditional canonical inputs such as `chains.md`/`hints.md` change, or a newer
operator turn supersedes the plan's prompt binding, do not reuse an unlaunched
execution assignment. In a later `EXECUTE` turn, first satisfy that turn's normal
iteration-plan receipt, then run the same `delegate` owner command. It may load
the transaction-bound old plan only to create the unique exact Reviewer for an
authentic returned/failed execution, or to replay that Reviewer's already
persisted `assigned`/no-attempt launch contract. Exact parent
`PreToolUseDenied Agent` is negative launch proof: rerun `delegate --limit 1`
to recover the durable Reviewer contract. All old Hunter, target, model-egress,
and unrelated Reviewer launches remain denied. A non-Reviewer assignment with
zero launch facts may be retired through the typed command:

```bash
python3 tools/workers.py cancel-unlaunched runs/<dir> A-<assignment> --reason "turn or canonical inputs changed before launch"
```

Cancellation is auditable settlement, not a result, review, refutation, merge,
evidence item, or completed cycle. Commit a material replan before replacement
work.
