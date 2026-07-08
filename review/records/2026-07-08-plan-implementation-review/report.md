# Maintenance Review Brief

## Objective

Review the Codex-authored implementation of the optimized Xunji plan. Judge whether the diff makes AI autonomous vulnerability discovery more likely to produce confirmed findings or stronger refutations without adding a new truth source, unsafe executor, or hard gate that breaks old runs.

## Main Changes

- Added seven bench canaries: existing mechanism consumption, JS hidden API threat, signed client param, permission matrix IDOR, state machine skip, threat hypothesis to evidence, and mentor no-progress pivot.
- Added Agent `## New Threat Hypotheses`, `workers.py merge-threats`, context-pack injection of relevant hypotheses, and `check_run.py` WARN for high-threat public fronts with no H/next/E-backed deferral.
- Added `tools/js_inventory.py`, a read-only saved-artifact JS/API sensor; registered its selftest.
- Added conditional JS/API input-shape fields and permission/state matrix fields to `surface.md`.
- Added derived `mentor_hints` to `loop_state.py`; hints are advisory only.
- Updated Claude primary-driver skill `.claude/skills/xunji-agent-board/SKILL.md` and shared workflow docs/templates.

## Review Questions

1. Does any change create a second source of truth, bypass the evidence gate, or let Agents promote findings/closure?
2. Are the new checks soft where promised, especially threat hypotheses and mentor hints?
3. Is `js_inventory.py` truly read-only over saved artifacts, with no network target fetch?
4. Do the canaries require outcome/action/evidence linkage rather than field presence only?
5. Is any important Claude primary-driver behavior missing from `.claude/skills` or shared templates/tools?

## Driver Answers

1. No second source of truth is introduced: threat candidates merge into `hypotheses.md`; JS candidates merge into `surface.md`/`hypotheses.md`; `loop_state.py` remains a derived cache. Agents still cannot promote findings or closure; `workers.py agent-check` errors on Agent `Maturity: finding` and final conclusion fields. `merge-threats` now labels merged Agent prose as `Source / trust: agent-candidate ...; untrusted until Root verifies`, so target/Agent text is not silently treated as evidence.
2. Threat hypotheses and mentor hints are soft/advisory: `check_run.py` adds only WARN text for high-threat public fronts lacking H/next/E-backed deferral, and `loop_state.py` emits `mentor_hints` without writing canonical evidence/front/report state.
3. `js_inventory.py` reads files under the run directory only. It blocks explicit paths outside the run in selftest and passed a runtime no-network control with socket/urlopen monkeypatched to fail; see E-005.
4. The seven new canaries require process plus linkage/outcome. Examples: `threat-hypothesis-to-evidence` requires Agent `NH-*`, canonical H fields, and an E-entry; `permission-matrix-idor` requires matrix row linked to E-001; `mentor-no-progress-pivot` requires hint plus decision plus E-entry. The full bench run is E-003.
5. Claude primary-driver behavior was updated in `.claude/skills/xunji-agent-board/SKILL.md`; shared behavior was updated in `docs/WORKFLOW*.md`, `docs/templates`, and `tools`. `.agents/skills` was not edited.

## Residual Limits

- Synthetic bench fixtures prove framework process and regression signals, not real-world vulnerability yield by themselves.
- Several fixtures intentionally have `recorded_requests: 0` because bench request count is a lower bound from saved replay/events; this is acceptable for process canaries but weaker than live A/B request accounting.
- `.agents/skills` was not edited because the operator explicitly set the boundary: default framework behavior is Claude primary-driver plus shared templates/tools; `.agents/skills` is Codex auxiliary guidance only.

## Verification Already Run

- `python3 tools/workers.py --selftest`
- `python3 tools/context_pack.py --selftest`
- `python3 tools/check_run.py --selftest`
- `python3 tools/loop_state.py --selftest`
- `python3 tools/js_inventory.py --selftest`
- `python3 tools/bench.py --selftest`
- `python3 tools/selftest_all.py --only context_pack,workers,loop_state,check_run,js_inventory,bench,check_templates`
- `python3 tools/bench.py score-all bench --json-out /tmp/xunji-bench-after-plan.json` -> 18/18 clean
- `python3 tools/check_rules.py`
- `python3 tools/check_templates.py`
- `git diff --check`

## Frozen Diff Artifact

- `evidence/implementation.diff`
