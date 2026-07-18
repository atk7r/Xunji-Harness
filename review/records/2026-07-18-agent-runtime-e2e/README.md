# Claude Code primary-driver E2E record

- Date: 2026-07-18
- Scope: current Python harness and Claude Code primary-driver Agent lifecycle
- Driver: Claude Code 2.1.201, DeepSeek `deepseek-v4-pro[1m]`, effort `max`
- Main-repository base: `1a2170eb6e1a6d7a31d37d8ef8310db9ba7b4bbb`
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
