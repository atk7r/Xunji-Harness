# AI Semantic Lifecycle Real-Driver Validation

- Date: 2026-07-23
- Driver: configured DeepSeek-backed Claude Code
- Author/orchestrator: Codex
- Isolation: fresh clones under `/tmp`; the operator's live active pointer and runs were not used
- Representative prompt: natural-language request to create a run for
  `https://semantic-intent.example/`, complete local setup only, perform no target
  access, create no Cron, and stop after success
- Fixture: `.claude/xunji_active_run` already contained
  `runs/semantic-intent-example_20260723`, while that run did not yet exist

## First Run — Accepted Failure

Session `e35a9e91-b657-4ede-b1f9-162208fc47bc` selected the correct public
`loop_bootstrap.py --source ... --type auto` candidate and committed setup, but
then edited `frontier.md`. That contradicted the prompt's setup-only narrowing, so
the run was not counted as a pass. The repair added `lifecycle_scope=setup_only`,
bound it into the candidate constraint digest, and made post-setup mutation fail
closed while retaining reads and registered local verification.

## Final Run — Pass

Session `3b94bd34-733b-49b5-874f-7c3b04fa6be5` independently chose this tool path:

1. load `xunji-run-lifecycle`;
2. load `xunji-setup-ingest`;
3. run the exact public `loop_bootstrap.py --source ... --type auto` adapter;
4. run registered `check_run.py` verification;
5. list the resulting run directory read-only.

There was no target request, WebSearch/WebFetch, Cron, Agent, Edit, Write, or
frontier/evidence mutation. The model's prose was not used as the pass signal.

Independent receipt/state adjudication:

- setup transaction: `committed`, not `recovered`;
- transaction id: `6a1f3f7956c54a28aec9869ec2a9c784`;
- prompt SHA-256: `1815623b09ca5ff3238df9dde115215b00af1ed47fdae3bcf93aaf455e1eb4b5`;
- source SHA-256: `3fca0c15c6060bb79727be09b6a75ad36c865254871b41f9e065423b07f21604`;
- candidate SHA-256: `709228f2e2723383d2977329844743c6b72a4a503b1e015c00e10464b75ca0ae`;
- effect SHA-256: `5495bac031cd8d95d95eb529f9d4d7c46878aa17c86ee7a840cfdd8d64a7130f`;
- constraints SHA-256: `04fca33e7d884c9d237bd76a3b9e4ac13d8b6ae1b2ec7b149da16821c15624ce`;
- frozen pre-publish origin: invalid/missing, with empty `expected_origin_run`;
- transition claim origin: empty, bound to the same prompt, source, target,
  transaction, and exact effect;
- final contract: `EXECUTE`, `intent_resolution=model_tool_candidate`,
  `lifecycle_scope=setup_only`, `target_egress_denied=true`;
- active pointer: exact new run;
- pending and transition-claim directories: no residual authority files.

This demonstrates both repaired boundaries: Claude performs the semantic choice,
the Hook promotes only a prompt/effect/constraint-bound candidate, and an unchanged
dangling pointer pathname cannot impersonate a prior pointer commit after atomic
publish materializes its referent.
