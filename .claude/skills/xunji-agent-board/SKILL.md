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
- `tools/work_plan.py`, `tools/workers.py`, `tools/runtime_receipts.py`, and
  `tools/loop_journal.py` own executable validation and state transitions.
- Read `references/plan-and-delegate.md` completely before planning, committing,
  delegating, or settling a stale unlaunched assignment.
- Read `references/launch-return-settlement.md` completely before invoking an
  Agent or writing review, Root disposition, recovery, or `cycle_end` state.
- Before this flow's first Bash, Read the applicable exact path under
  `.claude/skills/xunji-agent-board/references/`. Never discover its owner CLI
  through Bash, `--help`, redirects, chains, or path guessing.
- Use `xunji-reviewops` for independent review and review-ledger adjudication.
- Use `xunji-evidence-replay-gate` for candidate promotion and replay quality.
- Use `src-safety-boundary` for privacy, target artifact, cleanup, and effect
  limits; this skill does not restate those rules.

`.agents/skills/` is Codex-side guidance, not Claude Root instruction.

## Execution Ownership

- `ROOT_DIRECT` is only one dependency-free atomic lane whose exact capability
  is registry-eligible. It does not cover target, control, model-egress,
  repository mutation, or multi-step work.
- Complex serial work still uses one real Hunter Agent followed by its Reviewer.
- Follow `docs/WORKFLOW.md` for `SERIAL_AGENT` versus `PARALLEL_AGENTS`; parallel
  breadth never expands scope or relaxes evidence and closure gates.

## Non-Negotiable Agent-Mode Cycle

For `SERIAL_AGENT` / `PARALLEL_AGENTS`:

```text
committed work plan
-> delegate ready Hunter lane
-> exact Hunter Agent launch and durable `state=done` return checkpoint
-> delegate its digest-bound Reviewer lane
-> exact Reviewer Agent launch and durable `state=done` return checkpoint
-> review-disposition
-> Root/Single-Synthesizer finish
-> typed cycle_end
```

Every Agent execution lane has exactly one dependent Reviewer. `done`, Agent prose,
launch acknowledgement, or reviewer confidence cannot skip any arrow. Reviewer
supplies a candidate disposition only; Root makes the final evidence-gated
decision.

## Runtime Invariants

- `delegate` never spawns. Its returned exact `subagent_type` plus exact
  `launch_prompt` form one binary Agent tool-input contract; copy both unchanged.
- Role/type mapping, prompt bytes, plan/result digests, and actual Start/Stop type
  must all agree. `description`, reconstructed tokens, aliases, added context, or
  whitespace changes grant no authority.
- An async parent Post proves launch only. Only the uniquely matching,
  same-session `SubagentStop` plus the owner reference's `state=done` checkpoint
  proves durable return and freezes result bytes.
- Do not place two unbound Agent calls in one assistant message. Stagger real
  parallel launches across messages while earlier Agents remain running.
- Agents do not spawn Agents. All canonical writes, conflict resolution, finding
  promotion, and closure remain Root-owned.
- The global completion challenge is assignment-free and separate from a
  plan-bound Reviewer and from independent peer review. Load the exact owner
  reference before using it; never reconstruct its envelope from memory.
- A current-turn `maintenance_action=true` denial freezes Agent/control/target
  and canonical progression. Read the receipt and stop; a later success elsewhere
  cannot erase it.

## Root Merge Check

Before Root disposition, verify exact assigned assets, immutable returned bytes,
Reviewer digest binding, canonical E/F/D anchors, target receipts where required,
and unresolved conflicts. Candidate output never becomes a finding merely because
an Agent returned it. Use the commands and recovery rules in the two references,
then run the relevant structural checks before closure.

## Maintenance Checks

```bash
python3 tools/selftest_all.py --only work_plan,workers,runtime_receipts,turn_contract,context_pack,run_model
```
