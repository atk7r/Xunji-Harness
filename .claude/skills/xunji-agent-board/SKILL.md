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
- `tools/workers.py`, `tools/context_pack.py`, `tools/graph.py`, and
  `tools/saturation.py` for command behavior.
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
- `workers.py assign` means "lane prepared", not "Claude Agent is running".
  When Root actually starts a Claude Agent tool, its prompt must include
  `XUNJI_ASSIGNMENT=A-... XUNJI_FRONT=F-... XUNJI_ASSETS=h1,h2`, exactly matching
  the assignment's explicit `--asset` package. The hook records launch and return
  attempts automatically. `heartbeat` is optional display state and never proves
  execution.
  When the Agent returns or is intentionally abandoned/blocked, record
  `workers.py finish <run> <agent> --status <done|blocked|failed|abandoned>`.
  Closure is blocked while any assigned Agent remains non-terminal.
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
packs, and `workers.py assign` copies the resolved loop budget/profile source into
each new `agents/A-*.md`.

Use it like this:

- Before assigning Agents, check whether `state/operator_profile.json` exists and
  whether the operator has given a current preference or constraint that should be
  reflected there.
- If Root edits the profile, record the reason in `decisions.md`; if the change
  comes from operator steering, first capture that steering in `hints.md`.
- After `workers.py assign`, skim the generated Agent/context pack for
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
- Merge useful candidates with `python tools/workers.py merge-threats runs/<dir>`.
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

Use `python tools/js_inventory.py runs/<dir>` when saved JS bundles, rendered
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
python tools/graph.py runs/<dir>
python tools/workers.py status runs/<dir>
python tools/workers.py lifecycle-check runs/<dir>
python tools/workers.py conflicts runs/<dir>
python tools/saturation.py runs/<dir>
```

Plan and assign:

```bash
python tools/workers.py suggest runs/<dir>
python tools/workers.py plan runs/<dir>
python tools/workers.py assign runs/<dir> --role web-hunter --front F-001 \
  --asset app1.example --asset app2.example
python tools/context_pack.py runs/<dir> --agent A-web-hunter-001
rg -n "Reasoning style|Loop budget|Operator Profile" runs/<dir>/agents/A-web-hunter-001.md runs/<dir>/context/F-001.web-hunter.md
```

Every target-facing assignment requires a bounded, explicit asset package. Each
asset must already be named in that front and present in `coverage.json`; overlapping
non-terminal packages are rejected except for verification/review roles. Then invoke
the Claude `Agent` tool with the exact tokens
`XUNJI_ASSIGNMENT=A-web-hunter-001 XUNJI_FRONT=F-001 XUNJI_ASSETS=app1.example,app2.example`.
The package in the prompt must exactly match `state/assignments.json`.
Use a documented role such as `web-hunter`; the compatibility alias `hunter` maps to
`web-hunter` and therefore still requires explicit assets. Unknown roles fail closed.

For an async Agent, `Agent PostToolUse(status=async_launched)` proves **launch only**.
The hook records the returned `agentId` as a unique attempt and projects the
assignment to `running`; only the matching `SubagentStop` means the attempt returned.
Running Agents never owe post-return disposition and must remain able to use their own
assigned tools. Global fan-out/disposition gates apply to Root, not to a running child
lane. Only Root may spawn Agents; nested Agent fan-out is rejected.

After Root adjudicates the result, close the assignment with an auditable note:

```bash
python tools/workers.py finish runs/<dir> A-web-hunter-001 --status merged --note "Evidence: E-007; Front: F-001; candidate merged"
python tools/workers.py finish runs/<dir> A-web-hunter-002 --status blocked --note "Reason: shared auth barrier; Front: F-002"
```

`done` means a real Agent returned but Root still owes merge/refute/adjudication; it
does not satisfy the Stop gate. The disposition timestamp must be newer than the
matching `SubagentStop`. `merged` additionally requires, for **every** assigned asset,
at least one transcript-backed successful target action by that Agent and a canonical
`E-xxx` entry naming the exact host. A zero-tool Agent or a partially completed asset
package cannot be marked merged. `blocked/failed/abandoned` may end the attempt but do
not erase that asset's coverage debt.

An adjudicated terminal state is immutable through ordinary `finish`. If its note was
wrong, amend it explicitly so the prior state remains auditable:

```bash
python tools/workers.py finish runs/<dir> A-web-hunter-002 --status blocked \
  --note "Reason: corrected barrier; Front: F-002" --amend
```

Only anchors present in canonical `evidence.md`, `frontier.md`, or `decisions.md`
count. A standalone file under `evidence/` is an artifact, not a canonical `E-xxx`
ledger entry.

Before merging:

```bash
python tools/workers.py agent-check runs/<dir>
python tools/workers.py lifecycle-check runs/<dir> --closure
python tools/workers.py merge-check runs/<dir>
python tools/workers.py conflicts runs/<dir>
python tools/workers.py synthesize runs/<dir>
python tools/workers.py merge-threats runs/<dir>
python tools/js_inventory.py runs/<dir>
```

Record the Root decision in `decisions.md`: what graph state was reviewed, why
the lane is worth assigning, why serial work is not enough, expected evidence,
and stop/pivot condition.

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

## Maintenance Checks

After changing Agent Board behavior, templates, or checks, run:

```bash
python tools/workers.py --selftest
python tools/run_model.py --selftest
python tools/runtime_receipts.py --selftest
python tools/turn_contract.py --selftest
python tools/context_pack.py --selftest
python tools/js_inventory.py --selftest
python tools/saturation.py --selftest
python tools/bench.py score-all bench --json-out /tmp/xunji-bench-agent-board.json
```
