# Setup Banner Dedup Review Disposition

## Accepted and fixed

- The first review correctly found that checking only the final `phase_end` did
  not independently prove that Setup had opened. The selftest now requires the
  exact journal sequence `phase_start`, `phase_end`.
- The first review correctly found that helper-name absence was weaker than
  behavioral output verification. The selftest now runs the complete `main()`
  success path under an isolated temporary ROOT, captures stdout, requires normal
  `[setup]` progress, and rejects start/end markers in both Chinese and stable
  `XUNJI PHASE` forms.
- The documentation artifact was expanded to include both the general visible
  marker rule and the narrow `setup_run.py` exception.
- `loop_bootstrap.py` was searched for independent Setup banner rendering; it has
  no such path. Its focused selftest also passes.

## Dismissed with evidence

- Final PR-001 and PR-002 ask the test to prohibit every hypothetical helper name
  or future banner format. That is not a finite behavioral contract. The captured
  full-main output plus four stable marker checks covers the repository's actual
  `loop_journal.render_phase_banner()` format, and the complete `setup_run.py` diff
  is below the bundle excerpt cap.
- The final file-open limitation is a reviewer sandbox limitation, not evidence
  that the on-disk file differs from the frozen diff. `git diff --check`, focused
  tests, and the 60-suite run all executed against the live workspace.

## Final review status

Fresh Claude review judged the implementation solid and specifically confirmed
that the integration test catches inline or alternative existing banner paths.
Kimi retained only the over-broad future-format warnings above. GLM output parsing
failed in the final panel and is recorded as a missing independent vote, not PASS.

Verification: setup selftest passed; four focused lifecycle/status suites passed;
rule check passed; diff check passed; all 60 repository suites passed.
