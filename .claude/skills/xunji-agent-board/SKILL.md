---
name: xunji-agent-board
description: Claude-driver guide for Xunji Agent Board coordination. Use when Claude Code is the primary Root driver and needs to plan, assign, audit, merge, or review specialized Subagents through `tools/workers.py`, context packs, graph/saturation passes, conflicts, and synthesis while preserving candidate-only agent output and Single Synthesizer control.
---

# Xunji Agent Board

This is the Claude-driver guide for Xunji's Agent Board. Claude Code is the live
Root driver. Agents are specialized lanes that write candidate material into the
run directory; the Single Synthesizer remains the sole integrator.

## Source Of Truth

Read these when exact behavior matters:

- `docs/WORKFLOW.md` for the Root graph pass and serial/parallel decision.
- `docs/WORKFLOW-reference.md` "Agent Board" for the full board contract.
- `docs/templates/agents/` for role prompts.
- `tools/work_plan.py`, `tools/workers.py`, `tools/runtime_receipts.py`,
  `tools/context_pack.py`, and `tools/loop_journal.py` for the current
  transactional plan/assignment/return/review/merge contract.
- `tools/graph.py` and `tools/saturation.py` for derived planning inputs.
- `xunji-reviewops` when board output affects closure, report, or review.

Claude Code primary-driver behavior lives in `.claude/skills/`. The parallel
`.agents/skills/` tree is Codex-side guidance for advisory/maintenance work and
must not be treated as the Root driver's instruction source.

## Root Posture

- Root chooses fronts autonomously while safe open fronts remain.
- Agents own one assigned front/role/asset package and coordinate only through the run
  directory.
- Agents write `phenomenon`, `candidate`, `refutes`, `barrier`, or
  `next-evidence`; they do not write final findings or closure.
- Single Synthesizer merges through the evidence gate, allocates canonical E-ids,
  resolves conflicts, and updates canonical Markdown.
- The current lifecycle is `work_plan.py commit -> workers.py delegate -> real
  Hunter Agent -> real Reviewer Agent -> review-disposition -> Root finish ->
  typed cycle_end`. `workers.py assign` is a compatibility/manual preparation
  primitive, not the primary driver path; neither command spawns an Agent.
- Complex serial work still uses one real Hunter Agent. Root may execute directly
  only a single dependency-free atomic `ROOT_DIRECT` lane whose exact registry
  capability is explicitly eligible; target, control, model-egress, repository
  mutation, and multi-step work do not qualify.
- Treat `delegate`'s exact `subagent_type` plus exact `launch_prompt` as one binary
  Agent tool-input contract. Canonical roles `surface`, `web-auth`, `web-hunter`,
  `code-audit`, `exploit`, `verify`, and `report` map only to `xunji-hunter`; role
  `review` maps only to `xunji-reviewer`. Missing/null/blank, `general-purpose`,
  aliases, case drift, or whitespace-padded types fail closed. Pass the launch
  prompt unchanged. `tool_input.prompt` is compared as the complete
  UTF-8 string: do not prepend/append instructions, add whitespace/newlines, reorder
  fields, or reconstruct it in `description`. Hunter prompts bind
  `XUNJI_ASSIGNMENT=A-...`, `XUNJI_FRONT=F-...`, `XUNJI_ASSETS=h1,h2`,
  `XUNJI_LANE=L-...`, and `XUNJI_PLAN=<64hex>`; Reviewer prompts also bind
  `XUNJI_RESULT_DIGEST=<64hex>` to the frozen Hunter bytes.
- `Agent PostToolUse(status=async_launched)` proves launch only. The matching
  same-session `SubagentStop` is the successful return boundary and freezes the
  result snapshot/merge draft. `heartbeat`, Agent prose, Task/Todo state, and a
  parent Post without Stop never prove return or merge. The requested parent
  `subagent_type`, actual `SubagentStart.agent_type`, and Stop snapshot type must
  all agree with the assignment role.
- Do not configure a per-Agent `maxTurns` cap on the current Claude Code runtime.
  Its max-turn termination path can emit only an internal task notification and
  omit `SubagentStop`, leaving a launched attempt as honest lifecycle debt. Bound
  work with the plan lane/stop condition, loop/request/model budgets, and guard;
  a task notification never substitutes for a successful return receipt.
- Every execution lane has exactly one dependent Reviewer. Root cannot call
  `finish` before the Reviewer returns and `review-disposition` binds its result
  to the target digest. Closure is blocked while any plan-bound return, review,
  Root disposition, or typed `cycle_end` remains missing.
- All Agents share the same hook, guard state, request budget, and host breakers.
- Root and Agents must keep generated project/run/Agent/operator identity and real
  personal data out of outbound URL payloads, headers, bodies, multipart
  names/content, and target writes. Use neutral synthetic values. Required auth
  Cookie/Authorization is destination-bound; personal auth-body fields require
  the guarded explicit auth exception.
- Target-side temp artifacts created by Root or Agents must use neutral
  `tmp-YYYYMMDD-<6-12hex>`, `diag-YYYYMMDD-<6-12hex>`, or
  `proof-YYYYMMDD-<6-12hex>` names. Never include `xunji`, run dirs, Agent ids,
  vuln names, exploit names, or internal tool labels in target-side paths.
- Cleanup/delete/overwrite of any target-side artifact is operator-gated. Root or
  Agents must ask the operator and only execute the exact cleanup after an
  explicit `yes`; otherwise leave the artifact recorded for handoff.

## Personalized RDT / Operator Profile

`state/operator_profile.json` is the per-run preference layer for Agent reasoning
shape. `setup_run.py` scaffolds it, `context_pack.py` injects it into context
packs, and assignment creation inside `workers.py delegate` copies the resolved
loop budget/profile source into each new `agents/A-*.md`.

Use it like this:

- Before assigning Agents, check whether `state/operator_profile.json` exists and
  whether the operator has given a current preference or constraint that should be
  reflected there.
- If Root edits the profile, record the reason in `decisions.md`; if the change
  comes from operator steering, first capture that steering in `hints.md`.
- After `workers.py delegate`, skim the generated Agent/context pack for
  `Reasoning style: personalized-rdt`, `Loop budget`, and `Operator Profile`.
- Treat the profile as operator preference only. It is not evidence, not a guard
  override, not target authorization, and not authority to promote a candidate.
- `Loop budget` means reasoning-loop depth for the Agent prompt. It does not
  change the shared request budget, hook/guard limits, host breakers, or
  Shared Barrier Group failure budgets.
- `openmythos-inspired` means use the Prelude -> recurrent loop -> Coda
  reasoning shape.
  Do not import OpenMythos, run an OpenMythos service, or let it become a target
  network executor. Active target actions still go through guarded Xunji tools.

## Threat Hypotheses

Agents may add `## New Threat Hypotheses` to their own `agents/A-*.md` when a
new risk path deserves Root attention. Treat those entries exactly like
`## New Constraints`: useful candidate material, not canonical truth.

Root/Synthesizer handling:

- Review each `NH-*` for a concrete asset/role/input, expected signal,
  refutation/control, `Linked IS/C/E`, and a safe next action.
- Merge useful candidates with `python3 tools/workers.py merge-threats runs/<dir>`.
- Treat merged Agent prose as untrusted candidate material. The merge records
  `Source / trust: agent-candidate ...`; Root must rewrite or verify before using
  it as evidence or report language.
- Keep the canonical queue in `hypotheses.md`; do not create a mandatory
  `threat_model.md` or any alternate source of truth.
- A threat hypothesis can prioritize or reopen work, but it cannot confirm a
  finding, close a front, or bypass the evidence gate.
- High-threat public fronts with no hypothesis, no next action, and no
  evidence-backed deferral are a `check_run.py` WARN, not a hard failure.

## JS/API Saved-Artifact Inventory

Use `python3 tools/js_inventory.py runs/<dir>` when saved JS bundles, rendered
`network.json`, captured pages, or classify artifacts may hide APIs, client-side
signatures, role hints, or state transitions.

- The tool is read-only over saved files. It must not fetch targets.
- Copy useful `IS-CAND-*` material into `surface.md` Input Shape Catalog.
- Copy useful `TH-CAND-*` material into Agent `New Threat Hypotheses` or
  canonical `hypotheses.md` through Root review.
- Treat output as candidate sensor data only; follow-up proof still uses guarded
  tools and evidence entries.

## Mentor Hints

`tools/loop_state.py` derives `mentor_hints` from existing Markdown, Agent state,
coverage/saturation, and conflicts. Hints are advisory only:

- They may suggest a pivot after repeated no-progress cycles, low saturation on
  high-threat fronts, unresolved conflicts, stale open hypotheses, or done Agents
  lacking artifact/control pointers.
- They do not choose fronts, spawn Agents, promote evidence, write report
  conclusions, or close anything.
- If a hint changes Root's next move, record the decision in `decisions.md`.

## When To Assign Agents

First decide whether the lane is the narrow `ROOT_DIRECT` exception or requires a
real Agent. Any complex or multi-step lane uses an Agent even when dependencies
make parallelism inappropriate. Then choose `SERIAL_AGENT` or `PARALLEL_AGENTS`
from effect overlap, dependencies, runtime slots, request/model-egress budgets,
and merge capacity.

Go parallel when:

- Independent fronts hit different assets, roles, or barriers.
- A high-value or business-critical front needs breadth.
- Code-audit and blackbox lanes can test the same claim independently.
- 0day/xday work needs hypothesis variance or independent falsification.
- Closure is near and conflicts, missed high-value fronts, or shallow work risk
  remain.

Stay serial when:

- There is one front, one asset, or one shared barrier.
- One lane's result would materially change the next step for all others.

Serial means one real Hunter Agent followed by its Reviewer; it does not mean Root
absorbs the Hunter chain. `ROOT_DIRECT` remains the separate typed atomic exception.

When at least four active fronts do not all share one concrete barrier, the current
**coordination epoch** must contain two real Agents on disjoint assignment/front
pairs. The epoch persists across bare `continue` prompts; do not create replacement
Agents merely because the operator continued. It resets only when the active-front
topology or asset coverage debt materially changes. Only the operator's current
prompt may grant a serial override. `heartbeat`, Agent files, model-claimed budgets,
and decisions prose never prove execution.

## Commands

Start with the Root graph pass:

```bash
python3 tools/graph.py runs/<dir>
python3 tools/workers.py status runs/<dir>
python3 tools/workers.py lifecycle-check runs/<dir>
python3 tools/workers.py conflicts runs/<dir>
python3 tools/saturation.py runs/<dir>
```

Plan, commit, and delegate. The lane JSON below is one exact local-read example:
normally use the exact JSON printed by `workers.py plan`, repeat `--lane` for every
execution and dependent Reviewer lane, and choose the ready S1/S2/S3 goal rather
than copying S2 blindly.
`work_plan.py` is the current Python owner; this stage does not add another plan,
assignment, or merge runtime.

```bash
python3 tools/workers.py suggest runs/<dir>
python3 tools/workers.py plan runs/<dir> --limit 2
python3 tools/work_plan.py commit runs/<dir> --stage S2 --objective "review one bounded front" --mode SERIAL_AGENT --reason "one dependency chain" --exit-gate "frozen result reviewed and Root-disposed" --lane '{"id":"L-F001-HUNTER","role":"web-hunter","front":"F-001","effect":"local_read","assets":[],"dependencies":[],"expected_evidence":"attributable candidate or refutation","expected_information_gain":"high","stop_condition":"candidate or refutation returned","request_cost":0,"request_budget":0,"merge_cost":20,"atomic":false}' --lane '{"id":"L-F001-REVIEW","role":"review","front":"F-001","effect":"local_verify","assets":[],"dependencies":["L-F001-HUNTER"],"expected_evidence":"digest-bound review disposition","expected_information_gain":"medium","stop_condition":"exact frozen result challenged","request_cost":0,"request_budget":0,"merge_cost":10,"atomic":false}'
python3 tools/work_plan.py status runs/<dir>
python3 tools/workers.py delegate runs/<dir> --runtime-slots 1 --request-budget 0 --model-egress-budget 0 --merge-capacity 40 --limit 1
```

If a clean registered plan command returns
`XUNJI_E_LIFECYCLE_EXACT_ARGV_REQUIRED` with category `invalid-argv`, it was not
executed and did not become maintenance authority. Rebuild the complete argv from
the owner example or the exact lane JSON printed by `workers.py plan`, then retry
in the same operator turn. Inspect implementation or manifests only with
Read/Grep/Glob; do not use `python -c`, redirects, or output-filter pipes to guess
the CLI.

`delegate` atomically creates only the ready assignment, its context pack, and an
exact launch prompt; it never spawns. Every target-facing lane has a bounded asset
package whose hosts are present in coverage and named by the front. Invoke the
indicated real `xunji-hunter` Agent with the launch prompt unchanged. Complete-string
equality is the authority boundary: token presence is insufficient, no normalization
or `strip()` is performed, and any prefix, suffix, added context, reordered field,
whitespace change, or description-only copy fails closed. It contains
the exact package
`XUNJI_ASSIGNMENT=A-... XUNJI_FRONT=F-... XUNJI_ASSETS=h1,h2
XUNJI_LANE=L-... XUNJI_PLAN=<64hex>`. The values must match the committed plan,
assignment row, and context. Unknown roles, stale digests, overlapping active
target packages, and hand-written launch prompts fail closed.

For an async Agent, `Agent PostToolUse(status=async_launched)` proves **launch only**.
The hook records the returned `agentId` as a unique attempt and projects the
assignment to `running`; only the matching `SubagentStop` means the attempt returned.
Running Agents never owe post-return disposition and must remain able to use their own
assigned tools. Global fan-out/disposition gates apply to Root, not to a running child
lane. A synchronous Start→Stop→Post and a Post→Start→Stop delivery both join the
same unique attempt; parent Post alone remains unconfirmed debt. Only Root may spawn
Agents; nested Agent fan-out is rejected.

The current `xunji-hunter` and `xunji-reviewer` definitions deliberately omit a
per-Agent `maxTurns` field. A max-turn task notification is status/control data,
not a final result: it cannot freeze bytes, satisfy a dependency, or authorize a
manual `finish`. Each Agent must return a final assistant response; if its lane
budget is nearly exhausted it returns a bounded candidate/refutation/blocker
instead of ending on another tool call.

Do not put two unbound Agent tool uses in one assistant message. Current Start payloads
may lack the parent tool id/prompt, and arrival order is not identity; more than one
remaining candidate therefore fails closed. To run real parallel lanes, launch the
first Agent, then launch the next in a later assistant message while the first is still
running.

After the Hunter's real Stop freezes the immutable result, delegate the now-ready
Reviewer lane. Invoke the indicated real `xunji-reviewer` Agent with its exact
launch prompt, including `XUNJI_RESULT_DIGEST=<64hex>` for those frozen bytes. The
digest and `XUNJI_COMPLETION_REVIEW` marker are part of the same byte-exact prompt;
Reviewer context is already frozen in its context pack and must not be appended.
The Stop receipt is not appendable until the result file and its
`state/merge_results/<assignment>/` directory chain are durable. A crash before that
point leaves the assignment running; retry the same Stop so the full barrier is
reconfirmed and exactly one receipt is appended.

```bash
python3 tools/workers.py delegate runs/<dir> --runtime-slots 1 --request-budget 0 --model-egress-budget 0 --merge-capacity 40 --limit 1
```

Only after the Reviewer returns may Root bind the review and write its canonical
Single-Synthesizer disposition. Use the status justified by the result; these
commands show the accepted-candidate path, not permission to accept weak evidence:

```bash
python3 tools/workers.py review-disposition runs/<dir> A-<target> A-<reviewer> --status accept-candidate --note "exact digest and controls reviewed"
python3 tools/workers.py finish runs/<dir> A-<target> --status merged --note "Evidence: E-001; Front: F-001; Root accepted reviewed candidate"
python3 tools/loop_journal.py runs/<dir> end \
  --next-action "运行 check_run 验证当前计划" \
  --note "plan cycle disposition complete"
```

The final command validates the committed v2 transaction/archive lineage and
derives the typed `cycle_end`; callers cannot hand-write it. The final text Coda
must project that receipt's `next_action` exactly. Missing, duplicate, stale, or
out-of-order Hunter/Reviewer/Root receipts retain debt and fail closed.

The global completion challenge is a separate assignment-free Reviewer envelope,
not a plan-bound lane and not an independent peer-review replacement. Invoke exact
`subagent_type=xunji-reviewer` with the formatter output
`XUNJI_COMPLETION_REVIEW EVIDENCE_INDEX=<40hex> COMPLETION_BUNDLE=<64hex> run=<run.name>
CHECKS=report_parity,severity_artifacts,reachable_frontier,review_ledger` and no
assignment/front/assets/lane/plan/result-digest tokens. It becomes the pseudo
`XUNJI-COMPLETION` / `REVIEW` receipt only after a real Start and Stop; it never
creates an assignment row, immutable plan result, merge draft, review disposition,
evidence item, or closure authority. Parent Post, async acknowledgement, a copied
response, or `## CodexCompletionReview` prose alone does not count. A PASS must end
with the exact non-empty line
`XUNJI_COMPLETION_VERDICT=PASS EVIDENCE_INDEX=<same 40hex>
COMPLETION_BUNDLE=<same 64hex> run=<same run.name>
CHECKS=report_parity:PASS,severity_artifacts:PASS,reachable_frontier:PASS,review_ledger:PASS`.

If `chains.md` or `hints.md` makes the plan stale, an already returned/failed execution
can unlock only its unique Reviewer with the exact completion marker, reviewed
assignment, and frozen result digest. A non-Reviewer assignment with zero launch facts
may be removed only through:

```bash
python3 tools/workers.py cancel-unlaunched runs/<dir> A-<assignment> \
  --reason "canonical inputs changed before launch"
```

The prepared cancellation is itself a runtime/replan barrier. It publishes an immutable
tombstone only after the exact generated artifacts and assignment row are durably absent.
Never count cancellation as a returned result, refutation, review, merge, evidence, or
completed cycle; replan materially before delegating replacement work.

`done` means a real Agent returned but Root still owes review and disposition; it
does not satisfy the Stop gate. `merged` additionally requires, for **every**
assigned asset, at least one transcript-backed successful target action by that
Agent and a canonical `E-xxx` entry naming the exact host. A zero-tool Agent or a
partially completed asset package cannot be marked merged. `blocked`, `failed`, or
`abandoned` ends the attempt only with an anchored reason and does not erase the
asset's coverage debt.

An adjudicated terminal state is immutable through ordinary `finish`. If its note was
wrong, amend it explicitly so the prior state remains auditable:

```bash
python3 tools/workers.py finish runs/<dir> A-web-hunter-002 --status blocked \
  --note "Reason: corrected barrier; Front: F-002" --amend
```

Only anchors present in canonical `evidence.md`, `frontier.md`, or `decisions.md`
count. A standalone file under `evidence/` is an artifact, not a canonical `E-xxx`
ledger entry.

Before merging:

```bash
python3 tools/workers.py agent-check runs/<dir>
python3 tools/workers.py lifecycle-check runs/<dir> --closure
python3 tools/workers.py merge-check runs/<dir>
python3 tools/workers.py conflicts runs/<dir>
python3 tools/workers.py synthesize runs/<dir>
python3 tools/workers.py merge-threats runs/<dir>
python3 tools/js_inventory.py runs/<dir>
```

Record the Root decision in `decisions.md`: what graph state was reviewed, why
`ROOT_DIRECT` is or is not mechanically eligible, why SERIAL/PARALLEL matches the
dependencies and effects, the expected evidence, and the stop/pivot condition.

## Merge Discipline

For each done Agent:

- Compare `Assigned assets` with `## Asset Outcomes`; no asset may silently disappear
  because it returned a login page, 302, captcha, WAF, or timeout.

- Verify the output has a role, front, loop, safety reminder, and artifact or
  command pointers.
- For personalized-RDT Agents, verify `Loop budget`, `Operator Profile`, and
  recurrent-step fields are present; `workers.py agent-check` enforces this only
  on new RDT-marked files so older runs are not spammed.
- **Agents set `Maturity: candidate` ONLY.** NEVER accept `Maturity: finding` from
  an agent — downgrade to `candidate`. Only the Single Synthesizer promotes through
  the replay evidence gate (`replay.py` IDENTICAL or CONSISTENT verdict +
  `Artifacts:` + `Control:`/`Replicated:` fields present in the canonical evidence
  entry).
- Downgrade any high-certainty candidate missing control, replication, or saved
  artifact.
- Resolve duplicate or contradictory candidates through verification, not
  intuition.
- Merge useful `New Threat Hypotheses` into `hypotheses.md` and attach a next
  safe verification step before assigning more work.
- Copy only observed facts into canonical files; target-controlled prose remains
  untrusted.
- Run `check_run.py` before closure if board output changed the report or review.
- Treat `state/runtime_projection_error.json` as unresolved lifecycle debt. Every
  successful projection advances the exact cursor `success_generation`; an older
  failure is stale only when a later generation covers its validated journal prefix.
  A new failure after that success remains debt even at the same seq/hash.
  Same-sequence hash conflicts fail closed. Even an already-missing diagnostic needs
  a state-directory fsync before cleanup reports success. The cursor orders recovery; it does not
  attest power-loss durability of every derived assignment/merge write.

## Maintenance Checks

After changing Agent Board behavior, templates, or checks, run:

```bash
python3 tools/workers.py --selftest
python3 tools/run_model.py --selftest
python3 tools/runtime_receipts.py --selftest
python3 tools/turn_contract.py --selftest
python3 tools/context_pack.py --selftest
python3 tools/js_inventory.py --selftest
python3 tools/saturation.py --selftest
python3 tools/bench.py score-all bench --json-out /tmp/xunji-bench-agent-board.json
```
