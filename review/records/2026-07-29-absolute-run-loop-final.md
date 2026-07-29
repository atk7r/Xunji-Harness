# Absolute Run Loop Repair — Final Disposition

Verdict: WARN
diff_fingerprint: bd4fedce691ce5b3
reviewed_diff: bd4fedce691ce5b3

- Author/integrator: Codex; Codex self-review is not counted.
- Functional diff SHA-256:
  `bd4fedce691ce5b3424639207506799a5f78bfc65ec5b604e40612fb23d10e07`
- Final frozen bundle: `815e141072a94074f8ce645889fd8762be143ee7`
- Evidence index: `d3bb8f0889dc048b670c0ac3e4b04baa145e0677`
- Independent backends: arkcli GLM + fresh Claude Code CLI.
- Backend limitation: Kimi timed out after 300 seconds and is not counted as a
  PASS vote.
- Source blockers: none.

The initial matrix BLOCKER treated client-reserved `/loop` scheduling as a bypass.
That premise was refuted by the real-driver event order: the original prompt reached
UserPromptSubmit before effects, Xunji injected the exact public resume adapter, the
transcript contained no CronCreate, and the activation receipt committed
`loop_bootstrap.resume`. The useful concern was accepted by making the scheduler
interaction an explicit front and by freezing separate failed/successful driver
artifacts.

Remaining WARN items are accepted limitations, not source contradictions:

- the external bundle contains redacted transcript excerpts rather than the full
  private Claude transcript;
- the foreign-path fail-closed case is a deterministic Hook/selftest negative
  control rather than a third model-driven run;
- the real-driver result is scoped to configured Claude Code 2.1.201 with a
  DeepSeek-backed model and is not projected onto future client versions;
- Kimi reviewer availability remained partial.

Verification: Python compile, focused turn-contract regression, rule check, diff
check, and full 69/69 framework scorecard PASS. In an isolated detached worktree,
the first driver attempt failed on `/tmp` versus `/private/tmp` and was not counted;
the repaired rerun switched the pointer from `driver-origin_20260729` to
`driver-abs_20260729` with a committed prompt/session/effect-bound activation
receipt and no Cron, Agent, target, or editor effects.
