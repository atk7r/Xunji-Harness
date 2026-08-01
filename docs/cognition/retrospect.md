# Retrospect Notes

Record false positives, retreats, and confirmation failures. Each retrospective should answer:

- What the hypothesis was at the time.
- Which link in the evidence chain was missing.
- Which signal came from a controlled action, and which signal might come from the
  environment itself.
- Whether the Verifier should return `needs_more_evidence`, `rejected`, or
  `confirmed_candidate`.
- What the smallest safe next action is.

Experience that succeeds and is stably reusable can be collected into
`docs/cognition/cases/`, then a human decides whether it enters long-term memory.

## Mandatory closure retrospective (`retrospective.md`)

These per-finding notes are continuous. Separately, **every run must close with a
`retrospective.md`** (scaffolded by `setup_run`, template at
`docs/templates/run/retrospective.md`). It is a whole-run post-mortem with two
required, content-checked sections: **Self problems** (where the driver went
wrong/slow/missed this run) and **Framework / tooling problems** (where tools/, hooks,
guard, knowledge, or docs held the run back). `tools/check_run.py` hard-fails closure
if the file is missing or those sections are empty placeholders — see
`docs/WORKFLOW.md` "Mandatory retrospective before closure".
