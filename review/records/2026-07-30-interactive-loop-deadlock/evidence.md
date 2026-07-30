# Interactive Loop Deadlock Repair Evidence

## Observed failure

- The supplied Claude Code 2.1.201 transcript interpreted schedule-less `/loop`
  as a recurring ten-minute client job and created Cron job `a9eb77ea`.
- The same run was re-entered repeatedly. Its Agent ledger grew to 73 rows and
  the parent transcript ended with repeated DeepSeek context-window errors.
- The same generated offline work identity reappeared as
  `L-F-002-OFFLINE` in plans associated with A-web-hunter-025, -027, -029,
  -031, and -033.
- `_remaining_replan_lanes()` consulted only the immediate predecessor plan.
  Once one shortened replan omitted a settled prefix, a later replan could no
  longer see that completed identity and generated it again.

## Repair

- Newly compiled `/loop` contracts record
  `loop_entry_delivered=true, loop_requested=false`. `CronCreate` is denied
  with `XUNJI_E_CRON_CREATE_NOT_REQUESTED`.
- The literal entry still requires one material execute cycle: task/work plan,
  Hunter, Reviewer, Root settlement, and typed `cycle_end`. Another cycle
  requires a new top-level execute prompt and fresh authority.
- Generated replans inherit identity-equal, fully settled lanes across the
  verified transaction/archive lineage. An all-duplicate proposal fails with
  `WORK_PLAN_DUPLICATE_SETTLED_WORK`.
- `workers.py status` keeps every active/debt row but bounds historical terminal
  output to the newest eight rows unless `--all` is explicit.

## Deterministic verification

- Focused selftests passed for turn contract, work plan, workers, capability
  registry, templates, and rules.
- `tools/workers.py --selftest` includes the exact regression: a middle replan
  drops the settled prefix, then a later generated replan must still inherit it
  from the grandparent transaction.
- Full suite: 69 passed, 0 failed. Raw output:
  `evidence/test-results.txt`.

## Claude Code real driver

Decisive command:

```text
claude --dangerously-skip-permissions --output-format json -p \
'/loop http://127.0.0.2:65533 ... 禁止任何目标网络请求 ... 允许按 Xunji 协议更新这个 run ... 完成一个 material cycle ...'
```

The configured DeepSeek-backed Claude Code 2.1.201 session
`0eb64b14-f43c-4496-8136-e7053b466495` completed successfully:

- model: `deepseek-v4-flash[1m]`;
- turn contract: `loop_entry_delivered=true`, `loop_requested=false`;
- Cron events: 0;
- target actions: 0;
- WebFetch/WebSearch: 0;
- real Hunter Start/Stop: A-web-hunter-001;
- real Reviewer Start/Stop: A-review-001;
- Root settlement: Hunter `blocked`, Reviewer `reviewed`;
- typed `cycle_end` hash:
  `2b867f56f447cef5deff033833073c06b2c4935f581a4fb9fbd321eb63d50373`;
- no candidate framework file was changed by the driver.

The first driver attempt is not counted as a pass. Its prompt also prohibited
Edit/Write, which made the required new-run frontier mapping impossible. It
proved zero Cron and zero target actions but correctly failed closed before
`cycle_end`; the decisive rerun removed only that fixture contradiction while
retaining the target/network and framework-source prohibitions.

## Frozen artifact hashes

```text
91b923b459f70f429782c99e10e190894b9ec35142ef5f6765eaf733053f409a  evidence/driver-assignments.json
3ac18c5c9fe1f1298827deaeb3441ea80ee13172c744ac0ce55d289058d9d08e  evidence/driver-loop-journal.jsonl
a60e36531dcd3d49528d730528503cc9e54f55b198e28b392a8159925aefc52d  evidence/driver-output.json
aa639de241683138573480ada15446d6005a6de667cc97669d7ead14125c0535  evidence/driver-runtime-events.jsonl
e91cf61a6d7e9138bd4cdee9dd0972f61bf2127278ab96635463e8aa2147a2c7  evidence/driver-session-transcript.jsonl
23e0cf340ce65d9624d176ccaed3d7c40c330beca0a9fc66104865f720a116bb  evidence/driver-turn-contract.json
79e0bd73b73c861a75366977026e8944fba24c530ce7a0814fa57e3ae202406c  evidence/driver-work-plan.json
43deca520a3cedeca7721a4c3224da64e73bc3abea281095c1a2c226e1ebfcb0  evidence/test-results.txt
```
