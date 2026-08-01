# Same-target lifecycle recovery real-driver adjudication

- Date: 2026-07-31
- Candidate base: `ad25477`
- Candidate framework diff SHA-256: `0113b8c3814ef29620cd9679a7bdadcb75ccfa849cbdf4aaec4351b7a85d9160`
- Driver: Claude Code `2.1.201`, configured `deepseek-v4-flash[1m]`
- Successful session: `9e4982fd-7203-4130-ba75-ceedbd46b8f0`
- Verdict: PASS

## Fixture and prompt

The detached worktree was seeded through the public adapter, without Hook claim
material and without target access:

```text
python3 tools/loop_bootstrap.py --source 'https://same-target-driver-r2.invalid/' --type auto
```

This created and selected
`runs/same-target-driver-r2-invalid_20260731` with transaction
`3cdcc7d3a88044a8944e464b96869396`. Its committed receipt deliberately had
`contract_binding=null`, `transition_claim=null`, and `activation_attempt=null`.
The real primary-driver prompt was:

```text
为 https://same-target-driver-r2.invalid/ 创建新 run，只完成本地 setup。请实际执行，不访问目标，不创建 Cron。
```

Claude loaded the primary lifecycle/setup skills and issued the exact public
adapter argv (using Claude Code's resolved trusted Python interpreter):

```text
/Library/Developer/CommandLineTools/Library/Frameworks/Python3.framework/Versions/3.9/bin/python3.9 /private/tmp/xunji-same-target-driver.r2sF8w/candidate/tools/loop_bootstrap.py --source https://same-target-driver-r2.invalid/ --type auto
```

## Independent state adjudication

The successful Hook/transaction path produced all required facts:

- current contract session: `9e4982fd-7203-4130-ba75-ceedbd46b8f0`
- current prompt SHA-256:
  `72fc49fcb46098c39595d50922d7e07c4e17539b4b142c6e29df334160ec5301`
- `transition_claim.origin_run == transition_claim.target_run ==
  same-target-driver-r2-invalid_20260731`
- create effect SHA-256:
  `972f8bfca1104840f72728175db95bcea601e14296460c069810146ef48d32fa`
- contract transaction/source identity exactly matched the original committed
  transaction; `setup_transaction.validate_committed_transition_contract()`
  returned PASS
- the original receipt remained `committed`, kept transaction
  `3cdcc7d3a88044a8944e464b96869396`, and retained its top-level
  `contract_binding` and `transition_claim` as null; reconciliation did not
  relabel an unbound direct-CLI original create
- `.claude/xunji_transition_claims/` contained zero files after success, proving
  the fresh same-target claim was retired
- runtime receipt seq 1 is successful `control.loop-bootstrap` with
  `target_action=false`; later seq 2-5 are only local read/verify denials or an
  expected incomplete-run verification failure, all with `target_action=false`
- transcript tool counts were Skill=2, Bash=6, Read=13, with Edit/Write=0,
  Agent=0, Cron=0, WebFetch/WebSearch=0. No target capability was invoked.

Claude Code returned `subtype=success`, `is_error=false`, `stop_reason=end_turn`,
and zero server web-search requests. It spent extra read-only turns investigating
an unrelated empty-template `check_run` warning; that prose and its git-history
inference were not used as setup evidence. No repository or canonical run edit
was accepted after setup.

## Artifact hashes

```text
setup_transaction.json   7d3e615b54df9bf3d88ee0d504cdaab7344236bd6a1a1c7e373763ee3a946a9d
turn_contract.json       34ffaf116b183d933240e6fc46cae64a448e5f971a2da32efff3f002263398a9
runtime_events.jsonl     7be8bfbf7fc4a8438f336bfe348a6ffc3ce6e580c0f5ec0b7b13e6ae63b24e2b
Claude transcript        36473f4ed7360873052b6c16467d9383b5b545b4b2c4edbafbcd2435027e41ee
raw Claude result JSON   3d35573d687b8bd8ae84d54379e61aba200611b4b51ee399baab6049b94252e4
```

The detached fixture contains no real target traffic and no live-checkout runtime
state. Runtime/transcript files remain test artifacts outside the repository; the
stable result and adjudication are recorded here.
