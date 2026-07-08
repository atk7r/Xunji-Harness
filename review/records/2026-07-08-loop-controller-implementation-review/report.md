# Maintenance Review Brief

## Objective

Review the Codex-authored implementation that fixes the `/loop` control-plane bug where Coda/no-progress and Type A blocked fronts could be interpreted as a Completion pause. Judge whether the diff keeps Claude Code as the primary driver, preserves Markdown as the source of truth, and makes autonomous vulnerability discovery less likely to stop prematurely.

## Main Changes

- `tools/loop_state.py`: parse status tokens so `open, blocked_type_a`, `open (blocked_type_a: ...)`, `working (blocked_type_a)`, and plain `blocked_type_a` remain open/stop-blocking; Coda convergence now produces pivot/review guidance instead of a closure candidate.
- `tools/loop_state.py`: section fallback ignores fenced-code example F-IDs, filters projection fronts back to real canonical frontier headings, and emits an advisory hint if Agent discipline audit is unavailable instead of failing silently.
- `tools/progress_ledger.py`: new derived progress ledger that records material progress and artifact-backed progress from loop state plus `evidence.md`.
- `tools/run_controller.py --shadow`: new advisory controller writing only `state/controller.shadow.json` and `state/controller_diff.md`; it reports stop blockers and next required lifecycle action but never chooses exploit steps, promotes evidence, or grants closure.
- `tools/loop_bootstrap.py`: refreshes loop state, progress ledger, and shadow controller before printing `/loop` launch instructions.
- Claude primary-driver docs updated: `CLAUDE.md`, `docs/templates/loop_prompt.md`, `.claude/skills/xunji-run-lifecycle/SKILL.md`, `docs/WORKFLOW*.md`, and `docs/ROUTER.md`.
- `tools/selftest_all.py`: registers `progress_ledger` and `run_controller` suites.

## Adjacent Scope In This Diff

This maintenance diff also includes the earlier autonomous-discovery optimization work that the same review bundle covers:

- Agent Board threat-hypothesis and candidate-evidence discipline updates in `.claude/skills/xunji-agent-board/SKILL.md`, `tools/workers.py`, and agent templates.
- Input Shape Catalog, Permission/State Working Matrix, and threat-hypothesis fields in `docs/WORKFLOW-reference.md`, `docs/templates/run/surface.md`, and `docs/templates/run/hypotheses.md`.
- `tools/js_inventory.py` plus `selftest_all.py` registration for read-only JavaScript inventory.
- Benchmark canaries under `bench/` for threat modeling, hidden JS APIs, permission/state reasoning, state-machine skip, mentor no-progress pivot, and existing-mechanism consumption.

These adjacent changes are reviewed as control-plane and canary improvements. They do not prove higher real-target finding yield by themselves.

## Review Questions

1. Does any new tool become a second source of truth or an orchestrator?
2. Does Coda convergence still accidentally trigger Completion pause while Type A/open fronts remain?
3. Are Claude primary-driver rules updated in the right tree (`.claude/skills`, not `.agents/skills`)?
4. Are bootstrap and aggregate selftests wired so the behavior does not rot?
5. Does the implementation improve vulnerability discovery behavior by preventing premature stop and forcing pivot/fanout/review?

## Driver Answers

These are maintenance-review answers, not confirmed vulnerability findings. The evidence ledger deliberately keeps the supporting artifacts at phenomenon/candidate certainty because they are local diffs, selftests, smoke checks, and source audits.

1. Second source of truth/orchestrator: the review bundle supports "not in the covered code paths." `loop_state.py`, `progress_ledger.py`, and `run_controller.py --shadow` are intended to write only derived `state/` outputs, and E-006 audits that boundary. This is not a proof against future code paths or every CLI misuse.
2. Coda versus Completion pause: the covered regression evidence supports "fixed for the exercised cases." E-007 exercises `coda_converged=true` with open Type A fronts and observes `completion_pause_candidate=false`, `NEEDS_PIVOT`, and `can_stop=false`.
3. Claude primary-driver tree: the staged diff and wording scan support "updated in the intended tree for this maintenance change." The change touches `CLAUDE.md`, `.claude/skills/xunji-run-lifecycle/SKILL.md`, and shared docs/templates; `.agents/skills` is not treated as the Root driver's instruction source.
4. Selftest wiring: the covered commands support "registered and passing for the selected suites." Bootstrap refreshes the derived caches, and `selftest_all.py` includes `loop_state`, `progress_ledger`, `run_controller`, and `loop_bootstrap`.
5. Vulnerability discovery behavior: the evidence supports only a directional control-plane improvement. The change reduces one premature-stop path and redirects the Root toward pivot/review/fanout; it does not prove higher real-target finding yield.

## Verification Already Run

- `python3 -m py_compile tools/loop_state.py tools/progress_ledger.py tools/run_controller.py tools/loop_bootstrap.py`
- `python3 tools/selftest_all.py --only loop_state,progress_ledger,run_controller,loop_bootstrap`
- `python3 tools/loop_state.py --selftest` with code-block and blocked_type_b regression coverage
- `python3 tools/check_rules.py`
- `python3 tools/check_templates.py`
- `python3 tools/check_run.py --selftest`
- `python3 tools/session_handoff.py --selftest`
- `python3 tools/setup_run.py --selftest`
- `python3 tools/anti_drift.py --selftest`
- Real run smoke: a no-write snapshot of `runs/scshr_20260708` now reports 4 open `blocked_type_a` fronts and `can_stop=false` for that representative mixed status format.
- Adversarial regression: a synthetic run forced `coda_converged=true` while two Type A fronts remained open; loop state refused closure and the shadow controller returned `NEEDS_PIVOT`, `advisory_only=true`, and `can_stop=false`.

## Frozen Artifacts

- `evidence/implementation.diff`
- `evidence/selftest-loop-controller.out`
- `evidence/loop-state-selftest-detailed.out`
- `evidence/py-compile.out`
- `evidence/check-rules.out`
- `evidence/check-templates.out`
- `evidence/git-diff-check.out`
- `evidence/check-run-selftest.out`
- `evidence/session-handoff-selftest.out`
- `evidence/setup-run-selftest.out`
- `evidence/anti-drift-selftest.out`
- `evidence/run-controller-advisory-audit.out`
- `evidence/loop-state-postfix-audit.out`
- `evidence/doc-right-tree-files.out`
- `evidence/scshr-real-run-validation.json`
- `evidence/scshr-frontier-status-lines.out`
- `evidence/adversarial-type-a-coda.json`
- `evidence/stale-wording-scan.out`
