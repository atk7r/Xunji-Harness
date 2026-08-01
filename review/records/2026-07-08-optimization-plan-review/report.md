# Xunji Optimization Plan Review Context

## Review Object

Codex-authored plan under review: combine earlier learning from OpenMythos,
Pentest-Lyan, Pentagi, MopMonkAgent, cochise, and newer AI vulnerability
research into a project-fit optimization plan for Xunji.

The project core is AI autonomous vulnerability discovery. The review must judge
whether the plan plausibly improves discovery under the existing Xunji
discipline, not whether the borrowed projects are interesting in isolation.

## Current Repo Constraints

- Claude Code is the primary live driver; Codex is auxiliary. Ambiguous Root,
  Agent/Subagent, skill, framework, or lifecycle behavior changes default to the
  Claude primary-driver tree and `.claude/skills/`, not `.agents/skills/`.
- Xunji already has the Agent Board. Agents are candidate producers; the Single
  Synthesizer is the sole integrator. Agents coordinate only through the run dir.
- Markdown run files remain canonical. `state/projection.json`,
  `state/events.jsonl`, `state/loop_state.json`, Agent Board state, and graphs
  are derived/advisory caches.
- `tools/bench.py` is the existing A/B yardstick. ROADMAP says measurement is a
  prerequisite before shipping more framework mechanisms.
- Existing templates already contain:
  - `frontier.md` with `Unruled out` anti-early-closure fields;
  - `surface.md` with Input Shape Catalog and Discovery Channels, including JS
    refs, inline scripts, asset refs, page links, path inference, and response
    body discovery;
  - `constraints.md` for ruled-out mechanism class + input shape pairs;
  - Agent prompts with recurrent loop, control/refutation, constraint carryover,
    and coverage self-check fields.
- OpenMythos is already scoped as reasoning shape only:
  `openmythos-inspired` Prelude -> recurrent loop -> Coda. No runtime import,
  service, or target network executor is allowed.

## Prior Plan Being Reviewed

1. Add `docs/research-learnings.md` mapping source project/research -> learned
   point -> Xunji landing -> gap -> adopt/reject/defer -> validation.
2. Add a MopMonk-inspired `docs/templates/run/threat_model.md`,
   `tools/threat_model.py`, `TM-001` fields, Agent `New Threats` output, Root
   merge discipline, and a WARN if closed/deferred fronts still have open threat
   model items.
3. Add Pentest-Lyan-style feature-level threat modeling through generic
   self-questions, not STRIDE or a fixed vulnerability checklist.
4. Add cochise-style `state/events.jsonl v2` with richer action/tool/result
   telemetry and metrics such as repeated action ratio, no-progress, first
   evidence, and request per finding.
5. Add Pentagi-style mentor checks for no-progress, repeated barriers, done
   agent without artifact, low/noise without pivot, high-value deferred, and
   open threat model item with no action.
6. Add JS analysis template/tooling for JS files, APIs, client-controlled params,
   signature/token/nonce logic, role/permission hints, state transitions,
   sensitive comments, hidden routes, and threat links.
7. Add conditional permission matrix when multiple roles/accounts exist.
8. Add bench canaries:
   `js-hidden-api-threat`, `signed-client-param`, `permission-matrix-idor`,
   `state-machine-skip`, `replay-or-race-logic`,
   `threat-ledger-open-tm-closure`.
9. Defer heavy runtime imports: no Pentagi runtime, no OpenMythos runtime, no
   MCP/tool ocean, no state JSON source of truth, no agent auto-promotion, no
   fixed threat checklist.

## Review Questions

- Does the plan actually make Xunji better at finding vulnerabilities, or does
  it mainly add paperwork?
- What must be measured first with `tools/bench.py` before adopting new
  templates/checkers?
- Does `state/events.jsonl v2` violate the Markdown-canonical boundary, or can
  it stay derived/advisory?
- Is `threat_model.md` a useful missing bridge between surface/frontier and
  exploit hypotheses, or redundant with current `surface.md`, `frontier.md`, and
  Agent coverage checks?
- Which earlier learning was insufficiently implemented and should be fixed
  before learning more projects?
- Which proposed changes are too broad, unsafe, stale-prone, or likely to make
  agents slower without improving findings?
- What is the smallest project-fit sequence that can be A/B tested?

## Evidence Anchors To Use

- `tools/bench.py` lines 3-34: scorer exists specifically to avoid plausible
  mechanism claims without A/B evidence.
- `tools/state_project.py` lines 2-6 and 97-123: Markdown canonical; current
  event stream is derived from fronts/decisions/evidence.
- `tools/loop_state.py` lines 2-11 and 227-254: loop state is derived/advisory;
  it already exposes no-progress, fanout, saturation, conflict, and closure
  hints.
- `docs/WORKFLOW-reference.md` lines 439-451: projection/events/loop state must
  never overwrite Markdown or drive closure.
- `docs/WORKFLOW-reference.md` lines 453-483: Agent Board contract and Single
  Synthesizer boundary.
- `docs/templates/run/frontier.md` lines 17-22 and 36-39: vectors, untried
  classes, next move, stop condition, and unruled-out anti-early-closure field.
- `docs/templates/run/surface.md` lines 23-49: input shape catalog and discovery
  channels already include JS/inline/asset/path/response discovery.
- `docs/templates/run/constraints.md` lines 3-15: negative evidence is already a
  structured ledger.
- `.claude/skills/xunji-agent-board/SKILL.md` lines 38-63: OpenMythos-style RDT
  is reasoning shape only, no runtime dependency or network executor.
- `docs/ROADMAP.md` lines 7-26 and 191-195: measurement before adding, bench v0
  landed but fixtures are still sparse.

## Requested Output

Return findings first. Classify each issue as BLOCKER, WARN, or PASS. Then
propose an optimized implementation sequence that preserves project boundaries
and has concrete acceptance criteria.
