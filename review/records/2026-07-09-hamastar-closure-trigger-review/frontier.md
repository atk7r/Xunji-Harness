# Frontier

## Open Fronts

## Deferred Fronts

## Closed Fronts

### F-001 — Closure trigger consistency

- Status: closed
- Front: check_run/run_gate closure detection for retrospective-only FINAL claims.
- Assets: tools/check_run.py, .claude/hooks/run_gate.py
- Current depth: deep
- Why closed: `check_run.py` now centralizes closure-trigger detection across report finality, decisions CLOSING/FINAL, completion markers, and `retrospective.md` Status/Verdict fields; `run_gate.py` delegates to the same predicate. Selftests cover retrospective FINAL activation and GHOST_COMPLETE prose non-activation.
- Evidence: E-001, E-002, E-003
- Vectors tried: report-final path, retrospective-final path, decisions completion-marker path, prose false-positive path, hook delegation path.

### F-002 — Scheduled loop cancellation auditability

- Status: closed
- Front: ensure completion markers leave an auditable scheduled-loop disposition.
- Assets: tools/check_run.py, docs/templates/loop_prompt.md, .claude/skills/xunji-run-lifecycle/SKILL.md
- Current depth: deep
- Why closed: completion markers now hard-fail without a loop journal `cycle_end` / `end` event containing `cron_cancelled=<job-id|none>`; loop prompt and Claude driver skill require same-turn cancellation/recording.
- Evidence: E-001, E-002, E-003
- Vectors tried: no journal, non-end event with cron disposition, journal without cron disposition, cron_cancelled=none, cron_cancelled=<id>, normal non-completion iteration.

### F-003 — Hamastar run state honesty

- Status: closed
- Front: make the local ignored hamastar retrospective stop asserting unsupported FINAL.
- Assets: runs/hamastar_20260709/retrospective.md
- Current depth: moderate
- Why closed: local ignored retrospective now states NEEDS_REPAIR, includes real Self and Framework/tooling sections, and records concrete blockers. `check_run.py runs/hamastar_20260709` passes structurally with non-closure warnings instead of silently accepting a false FINAL.
- Evidence: E-004
- Vectors tried: check_run before/after closure-trigger change, loop_state readout, retrospective closure-source probe.
