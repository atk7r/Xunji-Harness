# Report

This maintenance diff repairs the reproduced Claude Code deadlock where `/loop`
attempted Cron creation for an old run, setup was blocked by the old Agent Board,
the model cleared the active pointer, setup switched runs without carrying the
turn contract, and two Stop rules required mutually exclusive Coda forms.

The implemented design makes run selection an operator-authorized transition:

- no-active-run lifecycle prompts receive a short-lived pending contract and an
  exact target/session/prompt-hash transition claim;
- setup/resume/set-active copy or consume the contract before pointer replacement;
- contract hooks bind only the explicit pointer and never infer a recent run;
- anti-drift, output, and closure Stop hooks also bind only that pointer, so
  clearing it cannot silently reactivate the most recently modified old run;
- direct pointer/pending/runtime writes and unrelated transitions are denied;
- exact local lifecycle/state commands are not mistaken for target actions;
- new-run Cron creation remains blocked until setup and a new-run CronList occur;
- a no-front denial envelope uses `frontier.md`;
- Stop re-entry does not loop until Claude Code forcibly overrides hooks.

Reviewers must look for authorization confusion, cross-session pending selection,
partial setup activation, control-command argument abuse, loss of unresolved-denial
truth, and any path by which Stop retry changes canonical completion state.
