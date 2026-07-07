# Optimized Xunji Plan After Review

## Review Result

- Independent arkcli panel verdict: WARN.
- Claude Code CLI leg: WARN, produced by direct `claude -p` review and saved as
  `claude-cli-review.md`.
- Synthesis: the framework direction is sound, but the original plan added too
  many ledgers/tools before proving discovery lift. The optimized plan keeps
  Xunji's existing Agent Board, Markdown canonical source, evidence gate, and
  bench-first discipline.

## North Star

Judge every change by whether it improves AI autonomous vulnerability discovery:
more confirmed findings or stronger refutations at equal or lower false-positive
and request budget cost.

Use `tools/bench.py` as the short-term yardstick:

- no regression across existing fixtures;
- new canaries fail before the change and pass after the change;
- detection/calibration do not drop;
- false positives stay zero on declared traps;
- request count/time-to-first-evidence does not grow without a justified gain;
- process/collaboration signals show the intended capability actually fired.

## Phase 0 - Measure First

Add canaries before adding new heavy mechanisms. Start with consumption and
outcome, not field presence:

1. `existing-mechanism-consumption`: proves Agents actually consume current
   `surface.md` discovery channels, `frontier.md` unruled-out fields, and
   `loop_state.py` no-progress/saturation hints.
2. `js-hidden-api-threat`
3. `signed-client-param`
4. `permission-matrix-idor`
5. `state-machine-skip`
6. `threat-hypothesis-to-evidence`
7. `mentor-no-progress-pivot`

Acceptance:

- Current `bench/` remains clean.
- At least one new canary demonstrates the specific missing behavior before a
  corresponding template/tool/check ships.
- A canary cannot pass only because a field exists. It must show a linked
  action, evidence id, constraint/refutation, certainty upgrade, or finding.
- Any later framework change must be compared with `bench.py compare` or an
  equivalent before/after score record.

## Phase 1 - Repair Earlier Learning First

Do not add a standalone mandatory `threat_model.md` yet. Instead, strengthen the
existing run artifacts:

- Extend `hypotheses.md` or front blocks with optional threat hypothesis fields:
  `Threat hypothesis`, `Asset/role/input`, `Expected signal`,
  `Refutation/control`, `Linked IS/C/E`, `Status`, and `Next action`.
- Add Agent `## New Threat Hypotheses` output, mirroring existing
  `## New Constraints`.
- Root/Synthesizer merges only useful candidates into canonical Markdown; Agents
  still produce candidates only.
- Initial gate is WARN only, and only for high-threat public fronts that have no
  hypothesis, no next action, and no evidence-backed deferral.
- Because Claude Code is the primary live driver, prompt/skill behavior changes
  land in `.claude/skills/` and shared templates/tools first. `.agents/skills/`
  changes are only for Codex-side advisory behavior or an explicitly recorded
  mirror.

Acceptance:

- `threat-hypothesis-to-evidence` fails before and passes after.
- No new file becomes an alternate source of truth.
- `check_run.py` does not hard-fail old runs for missing threat hypotheses.

## Phase 2 - JS/API Discovery As Sensor, Not New Ledger

Do not create a separate mandatory `js_analysis.md`. Keep `surface.md` as the
surface ledger and add optional fields under Input Shape Catalog:

- `Source JS/artifact`
- `Client-controlled params`
- `Client-side signature/token/nonce logic`
- `Role or permission hint`
- `State transition`
- `Linked threat hypothesis`

Add `tools/js_inventory.py` only if it reads saved artifacts, replay outputs, or
already-captured pages. It must not fetch targets by itself.

Acceptance:

- `js-hidden-api-threat` and `signed-client-param` canaries improve.
- The tool emits candidate input shapes or hypotheses; it does not confirm
  findings, probe targets, or overwrite Markdown.

## Phase 3 - Conditional Permission And State Modeling

Permission/state modeling is useful only when the run has multiple roles,
accounts, or observable state transitions.

- If only one account/role exists, record `cross-role: N/A (single account)`.
- If multiple roles exist, create a small working matrix linked to front,
  request/action, role A/B, expected behavior, observed E-id, and next control.
- Treat the matrix as a working note; findings still live in evidence/report and
  closure still depends on the evidence gate.

Acceptance:

- `permission-matrix-idor` and `state-machine-skip` canaries pass.
- No matrix row can close a front without E/C/H linkage.
- Secrets, cookies, and account identifiers are redacted.

## Phase 4 - Mentor Hints From Existing State

Do not build a separate Pentagi-like orchestrator. Add mentor hints as a derived
field in `loop_state.py` or a tiny read-only checker over existing state.

Triggers:

- two or more no-progress cycles;
- repeated same barrier;
- low saturation with open high-threat front;
- done Agent without artifact/control;
- unresolved Agent conflict;
- high-threat deferred front without E-entry;
- open threat hypothesis with no attempted action.

Acceptance:

- `mentor-no-progress-pivot` canary shows the hint appears at the right time.
- Hints are advisory only: they do not pick fronts, spawn Agents, promote
  evidence, or close anything.

## Phase 5 - Events Schema Discipline

Do not ship `state/events.jsonl v2` as a new truth source.

Allowed:

- keep `state_project.py` schema v1 derived from Markdown;
- first verify current v1 consumers: `bench.py`, `loop_state.py`, `workers.py`,
  `check_run.py`, and any review records that depend on `state/events.jsonl`;
- let `bench.py` tolerate optional telemetry fields when present;
- if active tools already emit request/action/evidence telemetry, record it as
  optional artifact-only metadata.

Deferred:

- rich action/tool/result timelines;
- Graphiti/pgvector memory;
- PentAGI runtime-style execution monitor.

These wait until bench/review shows that current loop_state signals cannot answer
the operational question.

## Explicit Non-Goals

- No OpenMythos runtime, service, or target executor.
- No PentAGI, MopMonk, cochise, or Pentest-Lyan runtime import.
- No fixed attack checklist.
- No agent auto-promotion.
- No JSON source of truth.
- No new hard gate until at least one canary proves value and old-run compatibility
  is checked.

## Implementation Order

1. Add/extend bench canaries and record baseline.
2. Add optional threat hypothesis fields in templates and Agent output.
3. Add soft `check_run.py`/`workers.py` checks for threat hypothesis freshness.
4. Add JS inventory sensor only over saved artifacts.
5. Add conditional permission/state matrix support.
6. Add derived mentor hints from `loop_state.py`.
7. Re-run bench and only then decide whether any WARN deserves promotion to a
   harder gate.
