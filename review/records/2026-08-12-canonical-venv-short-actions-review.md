# Canonical venv + short typed project actions — maintenance review

Verdict: PASS
diff_fingerprint: 334a51f5777f058c
reviewed_diff: 334a51f5777f058c

- Date: 2026-08-12
- Author/synthesizer: Codex (`/root`); author self-review is not an independent vote.
- Scope: repository Python runtime identity, short active-run-bound Worker/Cycle
  actions, capability/Hook/receipt validation, and driver guidance.
- Explicit non-scope: Claude Code native `Read` / `Edit` / `Bash` / `Agent`
  schemas were not changed; no MCP server or universal Tool wrapper was added.
- Tracked implementation slice diff SHA-256 (excluding this record/checkpoint):
  `005519b33a67f24a2511e7a62a1bd6067e28f321765291bed4c7b3ab98e10488`.
  New-file SHA-256 values: bootstrap
  `297ef8b56e930fbd324a9642d830254143f0f59e76d749cbbeced86fb23bc610`,
  environment checker
  `5f43f1a886c564294520bdb4a7a7faadee6cb2f02222aa90e142807265378b06`,
  active-run resolver
  `faa4623346a84e7fc59a7fadb92218ee75039013aecf2c95467526bca63e683a`,
  Python runtime owner
  `4b18024cd3d8d830743cdbb59d23f778cc8a243f37383f7c097b5b8de39e01bc`.

## Deterministic verification

- Final `.venv/bin/python tools/selftest_all.py`: **83 passed, 0 failed**
  in 139.2 seconds.
- `check_project_env.py --selftest`, `check_rules.py`, `check_templates.py`,
  Python compilation, and `git diff --check`: PASS.
- The focused suites cover environment identity, active pointer containment,
  closed argv parsing, Registry/turn-contract binding, short Worker/Cycle
  derivation, scheduler receipt validation, frozen result integrity, historical
  receipt compatibility, transaction replay/recovery, and output truth gates.
- Ignored local settings had `permissions.allow` count 0; no entry values were
  printed or admitted as framework evidence.

## Claude Code real-driver adjudication

All driver runs used isolated repository copies and the configured DeepSeek-backed
Claude Code 2.1.220; none used the operator's original live run.

- Exploratory session `7d1dcf97-f2a9-4925-a68a-3925e7cbbbd2` exposed eight
  denied discovery/wrapper command shapes. The guidance was tightened rather
  than expanding permissions.
- Session `46ee5dbf-9f14-4054-9f8a-e93156cc542d` used short reads with zero
  denials and honestly failed `check_run` on an incomplete synthetic run.
- Clean session `b7a76eb2-46f4-4bf9-a102-77025dc9e4ba` executed four exact
  active-run-bound read commands with no explicit run path and produced four
  successful Bash PostToolUse receipts. It had zero denials and zero target,
  model-egress, Agent, Cron, Web, or MCP effect.
- Final exact-candidate session `c100dc63-f020-4787-b77c-193d8049d1e9`
  executed exactly:
  `.venv/bin/python tools/check_project_env.py`,
  `.venv/bin/python tools/workers.py status`,
  `.venv/bin/python tools/runtime_receipts.py`,
  `.venv/bin/python tools/loop_journal.py status`, and
  `.venv/bin/python tools/check_run.py`.
  There were zero permission denials and no Web/MCP/Agent/Cron/target action.
  The first four succeeded. The intentionally incomplete synthetic run made
  `check_run` exit 1; the Stop truth gate rejected completion-shaped prose, and
  Claude then stated explicitly that nothing had been fixed or completed.
  The isolated pointer bytes stayed unchanged. Only Hook-owned derived
  turn/status/runtime audit files changed; no canonical evidence, finding,
  report, assignment, or target artifact was promoted.

## Independent review and dispositions

Fresh-context Claude reviews were run without edit/tool authority. Codex review
does not count.

- Environment slice session `6ca85e2e-14c0-44db-bd6e-cc70522b6c0f` returned
  HOLD because the settings checker used substring containment. Accepted:
  `check_project_env.py` now tokenizes the command, permits only the exact first
  executable after environment assignments, and rejects control operators or a
  second interpreter. Fresh session `97528849-7ac0-4174-9a67-fb1b78168820`
  returned PASS with no P0-P2.
- Loop-journal slice sessions including
  `581c01c5-0692-4262-a4b1-16af5168548b` returned actionable HOLD findings.
  Accepted fixes: strict integer receipt sequence; strict job-id grammar;
  current-run Create/List/Delete binding; missing-delete rejection; duplicate
  current-run scheduler-job rejection; and direct-helper state revalidation.
  The suggested permissive multi-job rendering was dismissed because the
  published cycle-action schema admits only one job id or `none`; duplication
  must be settled before cycle completion.
- Worker slice sessions `b99f6cfa-278e-49d8-b876-a9ec2077d409` and
  `1281cdfb-445e-4afb-999e-e3d22cb36490` identified missing frozen-result
  digest/current-review binding and a truthiness-based length check. Accepted:
  settlement now reopens a contained regular result under a hard byte cap,
  recomputes digest and exact typed length, binds the current review receipt,
  and carries the result digest into owner prose. The claimed
  `request_cost`/`request_budget` mismatch was dismissed: the canonical plan
  schema enforces `request_cost <= request_budget`; the latter is lane
  authorization while the scheduler deducts the former as wave cost. Assigned
  or running lanes do not re-enter `ready`.
- Final minimal no-tool review session
  `46ba4225-ad2e-477a-b72b-1b9622d7fcc9` returned **PASS**, no P0-P2.
- Several earlier final-review CLI attempts produced only session attachments or
  hung before model output due incorrect print/no-tool invocation. They are not
  votes and are not used as evidence.

External/third-party assistance was unavailable by local policy:
`peer_review.py --list-backends` reported `external_assistance.enabled=false`
and no active external provider. This is a recorded limitation; no unavailable
backend is counted as a vote.

## Final disposition

**PASS for the requested optimization, with the external-provider limitation
recorded.** The result is an optimized Xunji project-command surface, not a
modified Claude native Tool system: native Bash remains the transport;
`.venv/bin/python` is the one live Python identity; short typed input is expanded
by the existing semantic owner; Registry/Hook/turn-contract/receipt layers still
validate the exact effect. Long explicit CLI compatibility is not rendered as
ordinary model guidance and is not an authorization bypass.
