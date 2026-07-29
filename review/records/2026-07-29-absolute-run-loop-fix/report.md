# Absolute Run `/loop` Repair

## Claim

This is a repository-maintenance verification, not a target pentest or coverage
assessment.

The candidate compiles relative, repository-absolute, and resolution-equivalent
spellings of the same existing run to the existing typed `resume` effect when
non-ASCII operator prose is attached directly to its ASCII basename.

It does not treat a foreign path containing `/runs/` as a run and does not create a
new lifecycle effect, bypass activation CAS, or edit live run state.

## Verification

- Focused `turn_contract` selftest: PASS, including exact resume admission,
  resolution-equivalent spelling, and a foreign-path negative control.
- Rule check, Python compile, and diff check: PASS.
- Full framework scorecard: 69 passed, 0 failed in 119.2 seconds.
- DeepSeek-backed Claude Code 2.1.201 real-driver rerun in an isolated detached
  worktree: the exact public `loop_bootstrap.py --source ... --type auto` clean retry
  changed the pointer from `driver-origin_20260729` to `driver-abs_20260729`.
- The activation receipt records `operation=loop_bootstrap.resume`,
  `target_run=driver-abs_20260729`, `status=committed`, and binds the exact
  session/prompt/effect.
- The real-driver transcript contains no CronCreate, Agent, WebFetch, WebSearch,
  Edit, Write, or target request. The first output-wrapped adapter call was denied
  and then corrected in the same operator turn.

## Client scheduler interaction

Claude Code 2.1.201 still treats literal `/loop` as its own scheduler skill before
the task body runs. This client-owned parse is not Xunji authority, but it also did
not bypass Xunji in the tested dispatch: the original prompt reached
UserPromptSubmit, Xunji supplied the exact local lifecycle action, no CronCreate
occurred, and the typed resume receipt committed. This behavior is F-003/E-004,
not an untested residual claim.

Independent review remains a separate gate; software test PASS is not a review
verdict.
