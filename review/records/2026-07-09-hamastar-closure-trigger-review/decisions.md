# Decisions

## D-001 — Repair false-closure trigger path

- Time: 2026-07-09
- Loaded rule files this cycle: AGENTS.md, xunji-local-maintenance, xunji-run-lifecycle, xunji-reviewops, xunji-sentinel-guard-review, xunji-peer-review-panel
- Chosen front: F-001 closure trigger consistency
- Why this is worth pursuing now: hamastar retrospective had `Verdict: FINAL` while `report.md` stayed a template and loop_state still showed blockers. Previous gates only used report finality, so closure-only hard gates could be bypassed.
- Expected evidence: check_run selftest covers retrospective FINAL activation; hamastar check_run no longer silently treats unsupported FINAL as closed.
- Safety boundary: local repository maintenance; no target traffic.
- Result: implemented centralized closure predicate and hook delegation.

## D-002 — Add cron disposition gate

- Time: 2026-07-09
- Loaded rule files this cycle: xunji-run-lifecycle, xunji-reviewops
- Chosen front: F-002 scheduled loop cancellation auditability
- Why this is worth pursuing now: the retrospective explicitly recorded a `/loop` cron job left running after closure. A doc-only fix would not be auditable.
- Expected evidence: completion marker without an end-of-cycle cron disposition hard-fails; cron_cancelled=none and cron_cancelled=<id> pass only on loop journal end/cycle_end events.
- Safety boundary: local repository maintenance; no automation state mutated by this patch.
- Result: added `check_completion_cron_record` and updated driver loop guidance.

## D-003 — Preserve hamastar truth without forcing ignored run data into git

- Time: 2026-07-09
- Loaded rule files this cycle: xunji-run-lifecycle
- Chosen front: F-003 hamastar run state honesty
- Why this is worth pursuing now: the operator requested repair starting from `runs/hamastar_20260709/retrospective.md`, but `runs/*` is ignored and may contain engagement-specific artifacts.
- Expected evidence: local file is corrected; review artifact captures the current retrospective text; tracked code prevents recurrence.
- Safety boundary: do not force-add ignored run directories unless explicitly requested.
- Result: local retrospective now says NEEDS_REPAIR and the review artifact records its current content.
