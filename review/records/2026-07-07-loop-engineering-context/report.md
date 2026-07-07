# Loop Engineering Maintenance Review Context

## Scope

This review covers a Codex-authored repository maintenance diff implementing the operator request:

> 实现完整的可闭环的方案，完成后需要 arkcli + claude code 复审。复审通过并且全部完成后提交。

The implementation should be judged against these requirements:

- Adds a complete closed-loop engineering layer for AI-autonomous Xunji runs.
- Keeps Markdown run files as canonical truth.
- Does not recreate an orchestrator or let a tool choose/close/promote findings.
- Wires loop state into bootstrap, loop prompt, workflow docs, and aggregate selftests.
- Preserves Agent Board advisory boundaries.
- Supports Coda/no-progress detection through evidence delta, certainty upgrades, and coverage-matrix improvement.
- Exposes closure/fan-out/conflict/saturation hints without bypassing evidence gates.

## Changed Files

- `tools/loop_state.py` — new derived closed-loop progress and gate snapshot.
- `tools/saturation.py` — exposes a public `front_saturation()` helper consumed by `loop_state.py`.
- `tools/loop_bootstrap.py` — refreshes loop state on new/resume and emits current Python command.
- `docs/templates/loop_prompt.md` — updates the per-iteration prompt to run graph, workers, saturation, coverage matrix, loop state, Agent Board checks, and closure gates.
- `tools/selftest_all.py` — adds `loop_state` suite.
- `docs/WORKFLOW.md` — adds `coverage_matrix --write` and `loop_state --write` to the Root graph pass.
- `docs/WORKFLOW-reference.md` — documents `state/loop_state.*` and the state directory layout.
- `docs/ROUTER.md` — adds `loop_state.py` to the verification tool list.

## Evidence

- `E-001`: full maintenance diff at `evidence/diff.patch`.
- `E-002`: full aggregate selftest output at `evidence/selftest_all.txt`.
- `E-003`: benchmark score-all output at `evidence/bench_score_all.txt`.
- `E-004`: architecture/template/compile checks.
- `E-005`: focused loop selftests for no-write mode, Coda/no-progress behavior, coverage deltas, cache writes, and bootstrap refresh/fail-closed.
- `E-006`: real recorded-run loop_state smoke output without `--write`.

## Review Questions

- Does `tools/loop_state.py` stay derived/advisory, or does any behavior drift into orchestration?
- Are Coda convergence and progress deltas calculated from appropriate signals?
- Does bootstrap/resume wiring fail safely if loop-state refresh fails?
- Does `loop_prompt.md` give Claude Code enough complete cycle instructions without adding unsafe or stale requirements?
- Are generated caches kept out of canonical evidence/facts?
- Are tests sufficient for this change, and are there missing regressions around no-write mode, Agent Board conflicts, and coverage deltas?

## Expected Reviewer Output

Return PASS only if there is no blocker. WARN is acceptable only for non-blocking improvement suggestions. BLOCKER requires a concrete file/line or artifact reference and a recommended fix. Do not treat the review-scope evidence IDs as the same IDs that appear inside benchmark fixture output; benchmark output reports fixture-internal E-ids.
