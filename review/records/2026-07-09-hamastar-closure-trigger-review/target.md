# Target

- Review object: Codex-authored Xunji maintenance diff for hamastar retrospective closure-trigger repair.
- Scope:
  - `tools/check_run.py`
  - `.claude/hooks/run_gate.py`
  - `docs/templates/loop_prompt.md`
  - `.claude/skills/xunji-run-lifecycle/SKILL.md`
  - local ignored run artifact `runs/hamastar_20260709/retrospective.md`
- Purpose: prevent a run from declaring closure through `retrospective.md` or completion markers while report, coverage, loop state, replay/review, or scheduled-loop cleanup remain incomplete.
- Boundary: repository maintenance only. Codex is not acting as live Xunji Root driver and does not add a parallel Codex hook runtime.
