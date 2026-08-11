---
name: xunji-agent-board
description: Claude-primary coordination guide for choosing execution ownership and driving Xunji plan, Agent, review, and Root-settlement work without duplicating the exact runtime contracts.
---

# Xunji Agent Board

Claude Code is the live Root. Agents execute bounded lanes and return candidate
material; Root/Single Synthesizer alone promotes evidence, resolves conflicts,
writes canonical state, and closes fronts.

## Owners And Routing

- `docs/WORKFLOW.md` owns the Root cycle, serial/parallel judgment, operator hints,
  and saved-artifact JS inventory.
- `docs/WORKFLOW-reference.md` "Work plan" and "Agent Board" own optional board
  details such as operator profile and threat-hypothesis candidates;
  "Assignment-free global completion Reviewer" owns that separate envelope.
- `contracts/agent-instruction-sources.v1.json`,
  `tools/agent_instruction_bundle.py`, `tools/work_plan.py`, `tools/workers.py`,
  `tools/runtime_receipts.py`, and `tools/loop_journal.py` own executable source,
  validation, and state transitions.
- Read `references/plan-and-delegate.md` completely before planning, committing,
  delegating, or settling a stale unlaunched assignment.
- Read `references/launch-return-settlement.md` completely before invoking an
  Agent or writing review, Root disposition, recovery, or `cycle_end` state.
- Before this flow's first Bash, Read the applicable exact path under
  `.claude/skills/xunji-agent-board/references/`. Never discover its owner CLI
  through Bash, `--help`, redirects, chains, or path guessing.
- Use `xunji-reviewops` for independent review and review-ledger adjudication.
  A plan-bound Reviewer is never that independent review; when report/closure
  quality requires the latter, pause this board flow at its normal boundary and
  load the ReviewOps owner rather than relabeling an Agent receipt.
- Use `xunji-evidence-replay-gate` for candidate promotion and replay quality.
- Use `safety-boundary` for privacy, target artifact, cleanup, and effect
  limits; this skill does not restate those rules.

`.agents/skills/` is Codex-side guidance, not Claude Root instruction.

## Execution Ownership

- `ROOT_DIRECT` is only one dependency-free atomic lane whose exact capability
  is registry-eligible. It does not cover target, control, model-egress,
  repository mutation, or multi-step work.
- Complex serial work still uses one real Hunter Agent followed by its Reviewer.
- Follow `docs/WORKFLOW.md` for `SERIAL_AGENT` versus `PARALLEL_AGENTS`; parallel
  breadth never expands scope or relaxes evidence and closure gates.
- `COMPLETION_REVIEW` is the only zero-lane plan. It is legal only at S3 and
  authorizes only the assignment-free global Reviewer contract printed by
  `workers.py completion-review`; it cannot authorize ordinary Agent work.

## Non-Negotiable Agent-Mode Cycle

A **lane** is one plan-bound work unit (one node in the plan dependency DAG),
not an Agent process and not a front. It freezes that unit's role, effect,
assets, dependencies, expected evidence/information gain, stop condition, and
request/merge budget. Delegation turns one ready execution lane into an
assignment; its dependent Reviewer lane adjudicates that exact frozen result.
Several lanes may advance one semantic front, while the S3 global completion
challenge deliberately has no lanes or assignments.

For `SERIAL_AGENT` / `PARALLEL_AGENTS`:

```text
`workers.py plan` writes one turn/input-bound non-authorizing proposal seed
-> Root reshapes its typed lane DAG for the current strategy
-> one `workers.py commit-proposal` transaction
-> delegate ready Hunter lane
-> exact Hunter Agent launch and durable `state=done` return checkpoint
-> delegate its digest-bound Reviewer lane
-> exact Reviewer Agent launch and durable `state=done` return checkpoint
-> review-disposition
-> Root/Single-Synthesizer finish
-> obey the owner-emitted NEXT_OWNER_ACTION (delegate, material replan, or typed cycle_end)
```

Every Agent execution lane has exactly one dependent Reviewer. Under an explicit
operator target-egress denial, the offline Hunter/Reviewer pair is the complete
offline suffix; do not manufacture a second verification pair. `done`, Agent prose,
launch acknowledgement, or reviewer confidence cannot skip any arrow. Reviewer
supplies a candidate disposition only; Root makes the final evidence-gated
decision. A `finish` settles one execution/review pair, not necessarily the plan;
follow its owner-emitted next action before closing/deferring a front.

For zero-open-front S3 closure, the owner flow is instead:

```text
python3 tools/workers.py plan runs/<dir> -> generated COMPLETION_REVIEW proposal with lanes=[]
-> python3 tools/workers.py commit-proposal runs/<dir>
-> python3 tools/workers.py completion-review runs/<dir>
-> one exact xunji-reviewer Agent call from the printed tool_input
-> typed cycle_end
```

Do not invent a lane, reuse `delegate`, hand-calculate the proposal basis, or
reconstruct the completion envelope.

The generated OFFLINE/target/verify sequence is a conservative seed, not a fixed
playbook. Root may omit work already satisfied by current canonical state, add
independent lanes under one semantic front, and express dependencies that make
one result change the next move. Never split one semantic front merely to inflate
Agent count. The proposal has no authority until the transaction owner validates
its exact turn/input basis, Reviewer topology, effects, assets, budgets, and DAG.

`NO_TARGET_DATA_FOR_OFFLINE_ANALYSIS` is a barrier, not target evidence: allocate
no E-id or finding. Even an `accept-candidate` review of that result finishes the
execution assignment as `blocked`. Keep the front open/deferred with the exact
barrier and next evidence action.

## Runtime Invariants

- `delegate` never spawns. Its returned exact `subagent_type` plus exact
  `launch_prompt` form one binary Agent tool-input contract; copy both unchanged.
- Role/type mapping, prompt bytes, plan/result digests, and actual Start/Stop type
  must all agree. `description`, reconstructed tokens, aliases, added context, or
  whitespace changes grant no authority.
- The delegate-returned instruction-bundle digest is part of the binary launch
  contract. On source/artifact integrity denial, stop and material replan/delegate;
  never edit generated context/scaffold to repair it in place.
- An async parent Post proves launch only. Only the uniquely matching,
  same-session `SubagentStop` plus the owner reference's `state=done` checkpoint
  proves durable return and freezes result bytes.
- If `workers.py status` proves that the model returned but the Stop Hook itself
  failed closed, follow the exact `recover-hook-failed-stop` route in the owner
  reference. The pre-schema project ingress is only a non-canonical observation;
  it cannot replace the typed recovery receipt, Reviewer, or Root disposition.
- If status proves the exact host stream-watchdog failure plus the child's
  terminal synthetic idle-timeout/interruption pair, use only the owner
  reference's `settle-stream-stalled` command. It is a failed-only termination,
  never a return or evidence, and the old attempt must not be resumed.
- Do not place two unbound Agent calls in one assistant message. Stagger real
  parallel launches across messages while earlier Agents remain running.
- A superseding non-execute turn revokes subsequent child effects but does not
  erase an authentic return. In the next authorized execute turn, use the normal
  plan/delegate owner to launch only its exact Reviewer; never replay the stale
  Hunter or restore background target authority.
- A `UserPromptContinuationCoalesced` / `XUNJI_CONTINUATION_COALESCED` receipt
  means the same session supplied no semantic delta while this exact fresh plan
  remained current-input-bound and unended. Treat it only as a wake-up and
  continue the existing owner chain; do not replan, recreate, or relaunch. A
  different session's `UserPromptWakeCoalesced` / `XUNJI_E_RUN_BUSY` is
  non-authorizing: preserve the current owner contract but do not let the wake
  session continue it. Missing receipt, semantic/input delta, or ended cycle uses
  ordinary fresh-contract/stale-plan settlement.
- After a target `PreToolUseDenied`, use `barrier_state.py observe` only with its
  exact runtime receipt hash. Carry the emitted closed infra-barrier binding into
  every later lane for that front. The exact key preserves cause/precondition diagnostics,
  but after two distinct same-action zero-byte denials—even if those diagnostics rotate—
  commit and delegate reject a third same-action target attempt; a changed actual action,
  repair, or local_verify remains eligible, but changing only cause/precondition
  text does not. Clear only with matching target success or an exact barrier-bound
  repair receipt later than the active failure epoch; an epoch-tail CAS rejects
  concurrent new failure, and unrelated local verification does not clear it. Never derive this
  control from prose counts.
- Inspect large run artifacts through bounded `artifact_view.py range|search|strings`
  under `evidence/`; do not load the entire body merely because chunks exist.
- Agents do not spawn Agents. All canonical writes, conflict resolution, finding
  promotion, and closure remain Root-owned.
- The global completion challenge is assignment-free and separate from a
  plan-bound lane Reviewer and from independent peer review. It still requires
  the current zero-lane S3 `COMPLETION_REVIEW` plan. Load the exact owner
  reference and use its formatter command; never reconstruct its envelope. After
  the challenge and typed cycle end, route to `xunji-run-lifecycle` for READY
  check/Cron plus completion transaction prepare/commit; never write FINAL or the
  marker from Agent Board.
- A current-turn `maintenance_action=true` denial freezes Agent/control/target
  and canonical progression. Read the receipt and stop; a later success elsewhere
  cannot erase it.

## Root Merge Check

Before Root disposition, verify exact assigned assets, immutable returned bytes,
Reviewer digest binding, an existing F/D anchor for the disposition note, target
receipts where required, and unresolved conflicts. Perform `finish` before any
canonical promotion; the Hook enforces this order. Candidate output never becomes
a finding merely because an Agent or Reviewer accepted it. Structural PASS is not
completion proof.

## Maintenance Checks

```bash
python3 tools/selftest_all.py --only work_plan,workers,runtime_receipts,turn_contract,context_pack,run_model,check_templates
```
