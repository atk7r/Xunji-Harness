# Maintenance Review Decisions

## D-001

- Decision: Root cause accepted: new runs created by `setup_run.py` did not automatically set `.claude/xunji_active_run`, so Claude Code statusline rendered `Idle｜空闲 未选择运行目录`.
- Rationale: `xunji_statusline.py` renders Idle when `active_run()` cannot read or resolve the pointer.
- Outcome: Add best-effort active-run pointer update to `setup_run.py`.

## D-002

- Decision: Keep pointer update as display state only.
- Rationale: Setup must not enter `/loop`, select fronts, promote evidence, or close anything.
- Outcome: Helper prints success or warning and does not block setup success on pointer-write failure.

## D-003

- Decision: Run independent review because this is a Codex-authored maintenance diff.
- Rationale: Codex self-review and passing selftests do not satisfy the Xunji maintenance review matrix.
- Outcome: Use `tools/peer_review.py` with `--driver codex` and record findings under this review scope.

## D-004

- Decision: Accept the review finding that `setup_run.py --selftest` should not mutate the real `.claude/xunji_active_run` pointer.
- Rationale: Even with `try/finally`, a crash could leave the operator statusline pointing at a temporary run.
- Outcome: The selftest now monkeypatches `xunji_statusline.ACTIVE_RUN` to a temp pointer path, restores the module constant, and removes the temp directory.

## D-005

- Decision: Dismiss the review concern that `setup_run.py --classify` unexpectedly changes an existing run pointer.
- Rationale: In this CLI, `--classify` is an option on one-shot run creation, not a recheck mode for an existing run directory. Setting the pointer to the newly created run is consistent with setup linkage.
- Outcome: No code change. Documentation already says the pointer is local display state and setup does not enter `/loop`.

## D-006

- Decision: Accept final Claude review's scope-drift note for `docs/ROUTER.md`.
- Rationale: ROUTER became relevant only because review found `--classify` semantics ambiguous.
- Outcome: Record the ROUTER change as documentation-only scope expansion in `report.md`.

## D-007

- Decision: Accept final residual review limitations.
- Rationale: arkcli panel repeatedly failed with parse errors; Claude Code CLI final review completed and returned no concrete findings. A production CLI e2e that mutates the real active pointer was intentionally not run to avoid disturbing the operator's current state.
- Outcome: Close with residual process limitations recorded in `review.md`.
