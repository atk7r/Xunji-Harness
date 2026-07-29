# Decisions

- D-001: Treat the durable Start as immutable physical history. Recovery creates
  a content-addressed supersession receipt and changes only the effective
  projection.
- D-002: Keep Reviewer cancellation forbidden. The only post-recovery action is
  exact replay of the original assignment row's type and prompt.
- D-003: Require transcript proof from both sides of the interrupted foreground
  launch. Parent interruption alone or child timeout alone is insufficient.
- D-004: Publish the recovery receipt while holding runtime then assignment locks,
  then reset only the exact matching derived row. This is the documented narrow
  exception to the ordinary single-assignment-lock path.
- D-005: Count the first copied-live-run driver attempt as a fixture failure after
  it proved recovery but hit an absolute run_dir journal binding. Do not weaken
  work-plan binding to make a relocated run pass.
- D-006: Use a fresh targetless run created through production APIs for the
  decisive real-driver test. Do not use the live run or issue target requests.
- D-007: Keep the unified original-25-MB plus full-lifecycle E2E deferred. Exact
  observed bytes prove recovery and a path-native synthetic fixture proves later
  settlement; the evidence does not claim they were composed.
- D-008: Treat the rigid v1 interruption reason as a safety boundary. Other
  pre-model failure mechanisms require a separately versioned contract and
  fixtures rather than broadening the observed reason.
- D-009: Retain arkcli timeout/parse failures as review history, but exclude
  arkcli from the final gate after the operator explicitly said not to use it.
  Final review is fresh-context Claude only; no failed or unparseable arkcli
  response is promoted to a vote.
