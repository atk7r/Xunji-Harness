# Claude Code primary-driver E2E record

- Date: 2026-07-18
- Scope: current Python harness and Claude Code primary-driver Agent lifecycle
- Driver: Claude Code 2.1.201, DeepSeek `deepseek-v4-pro[1m]`; the final
  Phase 2 runs used effort `high`. No `ultra` run was used.
- Historical base: `1a2170eb6e1a6d7a31d37d8ef8310db9ba7b4bbb`
- Phase 2 base: `9b9f51e`; frozen v11 candidate
  `7cf3330d3e5c2e122dd8ebface14bc492e653bdd`, tree
  `94fdc7a286860ffaccea5d719434d808be409541`
- Target: reserved `.invalid` fixture only; no target action was authorized or executed
- Privacy: no secret, bulk transcript, or target artifact is stored in this record

This is developer-style primary-driver evidence, not a claim that a Python
selftest alone proves the workflow. Claude Code created a real task list and a
four-lane work plan, delegated two real asynchronous Hunters, waited for their
causal `SubagentStop` results, delegated two digest-bound Reviewers, recorded
Reviewer and Root dispositions, and derived a typed `cycle_end` through the
registered control commands.

## Attempts

| Attempt | Frozen candidate | Session | Disposition | Evidence SHA-256 | What it proved |
|---|---|---|---|---|---|
| 1 | `6d3a007bbc9bead94eb9fd8250d8e63245ee5169` | `225bdb13-d366-4cf1-8759-ee0d6cefd8b4` | FAIL, stopped after root-cause capture | `b1b36c30fb0d2e6860fe95b09f9b202b43b65aa4d9a12b0b96e08a5e3ba65d76` | An incomplete registered `work_plan.py` command and documentation-probing `python -c` could be misclassified as maintenance debt. The capability remained denied, but recovery truth was wrong. |
| 2 | `b70704b803444049cdf4bc3a9613651503b341f4` | `67a82d4e-159d-49e5-b1ae-4f8c4ef8b0cb` | ABORTED, `error_during_execution` after root-cause capture | `15497d570b007a97791b2ba57b349be47d493bea97325314ae5b90dd56962f54` | A Reviewer's denied compound local-read shell inherited maintenance truth solely from generic denial prose. The run was stopped before it could be counted as a pass. |
| 3 | `80c5ec42087f5c1ec3694057ad4433c3c89fd3bf` | `b952a327-f98c-4550-98a4-ce35e87ba139` | PASS, Claude result `success`, 99 turns | `5eb3a333899a5008bbc601eab8de61b341c7d51fa3a8831cb076003594654798` | Both defects were fixed without widening execution authority, and the full Hunter/Reviewer/Root/cycle lifecycle completed. |

The full JSONL logs remain ephemeral under `/tmp`; their hashes make the three
attempts distinguishable without committing transcripts. The replay prompt hash
is `5fc26cb317e2f754b4a0502eaa0ff5b622d6ba4df885577c806fcfa6350df293` and the
runner hash is `c9833b2fa18bfd5f82ce5fb18359520d367b13f61a1968f160023b7ab0c7c16d`.
Neither helper is part of the staged framework diff.

## PASS evidence

- Invalid-argv canary: receipt seq 13 denied with
  `XUNJI_E_LIFECYCLE_EXACT_ARGV_REQUIRED`, category `invalid-argv`,
  `retryable_same_turn=true`, `maintenance_action=false`, and
  `target_action=false`; it did not create a plan or journal event.
- Exact-prompt canary: receipt seq 20 denied an appended Hunter prompt with
  `XUNJI_E_DELEGATION_REQUIRED`; it did not create a launch attempt.
- Hunter F-001: parent Post / Start / Stop at seq 23 / 24 / 31, immutable result
  digest `8607ace7b59a9b8b412e50cfd8f38e787582273c0cdf5281c46a3656c16c5b78`.
- Hunter F-002: parent Post / Start / Stop at seq 25 / 26 / 32, immutable result
  digest `19fb6783003543be464e604be0260a02c2aaec061f7020fb9b57cfc9091a11db`.
- Reviewer F-001: parent Post / Start / Stop at seq 36 / 37 / 41, bound to the
  F-001 result digest. Reviewer F-002: seq 38 / 39 / 42, bound to F-002.
- The real compound local-read denial at seq 29 stayed fail-closed for execution
  while recording `maintenance_action=false` and `target_action=false`.
- Root terminal dispositions were recorded at seq 53 and 58. Typed journal end
  was recorded at seq 61.
- `cycle_end` hash:
  `92bda304fa77603d0aeeabc5dec64e419cf75bd9458970b61aecf339949e4189`;
  it links to `delegation_committed` hash
  `798576f90229822b7bcca42d89f57552532ef146ef2150deb697e46c5832a90d`,
  carries all four lane dispositions, and has no pending assignment.
- All 62 runtime receipts have `maintenance_action=false` and
  `target_action=false`. Runtime projection reports four returned attempts,
  no running attempts, `errors=[]`, and satisfied fan-out.
- The driver's final non-empty line was exactly
  `下一行动: 运行 check_run 验证当前计划`; it did not claim overall run closure.

## Reviewer challenge and Root disposition

The F-001 Reviewer initially returned `needs-control`: the Hunter described
`*_before` fields in `delegate_transaction.json` as newly created fields. This
left `review_status=action_required`, correctly preventing Root from finishing
the Hunter. Root re-read the frozen artifacts, accepted the core cross-file
binding while explicitly correcting that field attribution, recorded a new
`accept-candidate` disposition, and then used terminal `blocked` because the
fixture was local-only and contained no target evidence. This recovery path is
kept as evidence; the initial Reviewer disagreement is not rewritten as a pass.

## Frozen-candidate regression checks

- Focused contract suites: 6/6 passed.
- `tools/selftest_all.py`: 69/69 passed. The omnibus suite happens to include the
  existing statusline test, but statusline behavior is excluded from this stage's
  acceptance and main-repository staging.
- `tools/bench.py score-all bench/`: 18/18 fixtures clean, 18/18 detection and
  calibration, zero false positives, zero budget overruns.
- `tools/check_rules.py`, `tools/check_hook.py`,
  `tools/check_runtime_boundary.py`, template checks, and baseline-to-candidate
  `git diff --check`: passed.
- `tools/probe.py --selftest`: passed against its real local loopback server,
  including redirects, auth stripping, replay, range, preflight, and save paths.

This E2E record is primary-driver execution evidence. The independent
fresh-context Claude review required for the Codex-authored maintenance diff is
recorded separately and remains a commit gate.

## Phase 2: plan-bound Agent runtime and tool-call cap

This continuation validates the Claude-primary typed work-plan, assignment,
launch, return, review, Root settlement, and per-assignment child-tool boundary.
It does not claim engagement closure and does not cover statusline, `.agents`,
CCB/TypeScript, a live target, or assignment-free global-completion budgeting.

The final candidate materializes a default plan-bound `tool_call_limit=6`, freezes
the assignment value at `SubagentStart`, and appends/fsyncs one idempotent
`AgentToolCallClaim` before every later policy gate. Denied attempts count. The
first over-limit claim is recorded but cannot execute. Root/global-completion work
does not borrow this plan-bound counter.

### Failure and recovery ledger

No failed or interrupted attempt below is counted as PASS merely because Claude
later described it as successful.

| Run | Session | Disposition | Developer finding |
|---|---|---|---|
| normal v7 | `d8a1f5e9-1c05-46b5-964f-0aac825a0a56` | Product PASS; outer harness initially rc=2 | Transcript path encoding in the test runner was wrong; receipt chain itself was valid. |
| hard-cap v7 / v7b / v7c | `963c18ac…` / `3d30ac3a…` / `362592f8…` | FAIL / terminated | Removed stale fixture assumptions, premature `cycle_end`, and an invalid expectation that later assignments must reuse cap 6. |
| hard-cap v7d | `16ffe8e5-00d8-4d1b-ab5b-941d8492bc58` | FAIL | The seventh call was denied correctly, but blocked settlement lacked literal `Reason:` and a later Reviewer naturally exceeded disposable cap 8. Both were retained as defects, not hidden. |
| normal v8 | `3bbd184f-1095-46ac-9ac6-1c7ed776b706` | FAIL / terminated | A denied canary remained eligible during a later async parent-Post/child-Start race. Same-session denied/failed parent tool IDs now retire permanently from Start allocation. |
| normal v10 | `6a19875e-2106-4947-a6ad-9b2866f4fc04` | PASS after test-only validator correction | The canonical value was correctly at `cycle_end.data.next_action`; the runner incorrectly read the event top level. Product source was unchanged. |
| hard-cap v10 | `825727d3-fe03-40a8-867f-1b8eb9123c3c` | FAIL / terminated | Core seventh-call denial passed, but a normal Reviewer naturally exceeded disposable cap 16, creating extra denials. |
| hard-cap v10b | `4cd880a0-3af7-47a9-98a0-862bbc98d240` | FAIL / terminated | Claude reused cap 6 for the first Reviewer despite the intended later-lane cap 64. The test prompt was made mutually exclusive and output-checked. |
| hard-cap v11 | `af0b8511-229f-445a-9635-9dcab783f2d6` | FAIL / terminated | Core denial and later cap 64 passed, but Claude edited `decisions.md` after plan commit, caused a real stale-plan failure, then recovered. The clean-run prompt now treats the seeded graph pass as final test input. |
| normal v11 | `0e28ee7c-6329-41a6-bd86-aa5ee551dca8` | PASS | Final ordinary four-lane vertical slice. |
| hard-cap v11b | `6dabe0a6-f9ad-4df9-b90d-1ea696ce7384` | PASS | Final deliberate seventh-call fault injection plus unaffected downstream settlement. |

### Final ordinary-run evidence

- Claude return code 0; `UserPromptSubmit` transcript line 11 preceded first tool
  line 15; outer result was `RECEIPT_VALIDATION=normal:PASS`.
- Assignment/Start caps were `[6, 6, 6, 6]`; statuses were
  `blocked, reviewed, blocked, reviewed`.
- Parent Post / Start / Stop were 33/34/43, 50/51/62, 71/72/84, and
  90/91/100. Child claims were 4, 6, 6, and 6, all admitted.
- The sole denial was seq 32 `XUNJI_E_DELEGATION_REQUIRED` for the mutated
  canary. Its tool ID had no Start/Post. `PostToolUseFailure` count was zero.
- Typed plan `WP-2-84bd69b6` ended with cycle hash
  `a50f927464a994068cc034fe4a98e8df7d869cb011653a6a90949924597adccc`
  and `data.next_action=运行 check_run 验证当前计划`.
- Claude reported 165 Root turns, $6.275644, and 623018 ms foreground duration.
  Stream/transcript SHA-256 values are
  `bcbd1877fe8270356c9f6368d4d9ea4d7da8bdc1002b4cdc4a9d87cf3038fdfd`
  and `a9d3d40d56855d51897c83dccef8d6a7b45a2fda1af5b1dba724e2f2b3f49ee3`.

### Final hard-cap evidence

- Claude return code 0; `UserPromptSubmit` transcript line 11 preceded first tool
  line 16; outer result was `RECEIPT_VALIDATION=hard-cap:PASS`.
- Assignment/Start caps were `[6, 64, 64, 64]`; statuses were
  `blocked, reviewed, blocked, reviewed`. The wider later caps are disposable
  fault-isolation values, not a change to the product default.
- The first Hunter's claims were ordinals 1–6 admitted and ordinal 7 denied.
  Seq 21 recorded `XUNJI_E_AGENT_TOOL_CALL_LIMIT_EXCEEDED`; the denied tool ID
  `call_00_bCZrRwn8BTOeluYjBTj72375` had no `PostToolUse`.
- Parent Start/Stop were 13/22, 27/59, 67/81, and 84/103. Later claim counts were
  31, 13, and 18; every one was admitted. No other denial or
  `PostToolUseFailure` occurred.
- Typed plan `WP-2-fc6045e3` ended with cycle hash
  `1f90caa5aedd87d8c2705f54ae759575947dcd06cc726aeb4cdd3da492012d37`.
- Claude reported 13 Root turns and $4.472211; asynchronous child work is not
  represented by the 42181 ms Root foreground duration. Stream/transcript hashes
  are `e3a02a74f235db755bc9cc4ba282efaf2a78d3795694d657d22c4a6814c9acbb`
  and `5e5fe0308ecbaa64a423033728c7dcdafff445143c63ee7e54b3dc206197bc24`.

### Frozen-candidate checks and test-scaffold boundary

- Final v11 source: 46 selected Claude-primary/shared-runtime files; `.agents`,
  statusline, project-introduction deletion, target artifacts, and CCB/TypeScript
  work were excluded.
- `tools/selftest_all.py`: 69 passed, 0 failed in 107.9s with the authorized real
  loopback probe. Focused template/context/work-plan/workers/runtime/turn-contract
  aggregate: 6 passed, 0 failed. `git diff --check` passed.
- Runner SHA-256:
  `81f74149ff5389c17734c22a8c08c765c5c06d7114c0c3cbd730d06a9a3cd2e7`;
  ordinary/hard-cap prompt hashes:
  `d85dfa22159ee9f9410265628bed26b9f3adf8fa7b260e1a80bdee4b3a35c863` /
  `38c28bc4d88f064adc606e5d70237d8cb2148ca60c36b9011a704f6c211a94f7`.
- The runner, prompts, run directories, transcripts, and disposable Hunter fault
  injection are test scaffolding only and are not part of the framework commit.
