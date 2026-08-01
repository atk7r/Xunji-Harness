# Natural-Language Lifecycle + Turn-Stale Cancellation Real-Driver Validation

- Date: 2026-07-23
- Candidate base: `c4378527d50eef8bea9a06740500f0c7f17b0257`
- Candidate file-set SHA-256: `45ad02236d5004342dbb8f86797bf3b61efa63bbd2a19260abf10758860b3d4a`
- Isolated worktree: `/tmp/xunji-lifecycle-fix.HneX2x/worktree`
- Fixture run: `runs/driver_turn_recover_final_20260723`
- Claude Code: `2.1.201`, DeepSeek-backed `deepseek-v4-flash[1m]`
- Driver session: `6b5afaf6-fd40-44df-af06-e28710d340e4`
- Result: PASS

## Natural Operator Prompt

> 继续 runs/driver_turn_recover_final_20260723 -
> http://127.0.0.1:18765。先恢复这个 run；若 receipts 证明旧 assignment
> 从未启动，先用 typed cancellation 结算。随后按当前 canonical front
> 重新规划，只允许 local_read/local_verify，不访问目标、不修改框架、不关闭
> front、不写 evidence/decision；完成新的 Hunter、唯一 Reviewer、Root settlement
> 和 typed cycle_end，并独立核对 receipts。

The fixture began with an active formal run, one committed old-turn plan, and
`A-web-hunter-001` in `assigned` state with an empty attempt list and no parent
transcript launch fact. The current prompt intentionally combined one named run
and its target URL, matching the operator form that previously selected the URL
as a new-run source.

## Independently Adjudicated Chain

1. The stored contract promoted Claude's exact lifecycle argv to
   `lifecycle_operation=resume`, `loop_source_kind=run`,
   `intent_resolution=model_tool_candidate`, and
   `run_transition_requested=false`. The URL stayed a target anchor and compiled
   `target_egress_denied=true`; it did not become the selected lifecycle source.
2. `loop_bootstrap --resume` completed successfully through the real Hook and
   produced a successful `control.loop-bootstrap` receipt.
3. `A-web-hunter-001` had no `SubagentStart`, `SubagentStop`, failure receipt, or
   parent transcript Agent tool-use. `cancel-unlaunched` committed receipt
   `0993be330bf67142ddd36c3d74ffb76dbb34f9757c249146140d4958dffc4793`
   with schema `xunji.assignment-cancellation.v2` and
   `stale_basis=turn`. Its plan and observed input digests were identical while
   its plan/current turn bindings differed.
4. The Root then committed fresh plan `WP-2-12309295`, digest
   `12309295f5bc4c42e28d3cde0b46dc264b16f75db554ebc65e4143a39b08c120`,
   containing one `local_read` Hunter lane and its unique `local_verify`
   Reviewer lane.
5. Exactly two new Agents started and stopped: Hunter
   `A-web-hunter-002` and Reviewer `A-review-001`. Both receipts bind the fresh
   plan/lane/type; the Reviewer binds Hunter result digest
   `803d19263b1d924ae847c3cd1e53789e6001933fb2024dc705a86e5bfc32a1ab`.
6. Review receipt
   `124171d5fd99d70e9718f9dc4e26381644bd2f7052098f9301b06fee7394b5d1`
   supports the Root `blocked` disposition. The final projection has both lanes
   complete, no merge/review debt, and one typed `cycle_end`; `F-030` remains
   open.
7. Runtime receipts contain zero target actions and no target capability. No
   evidence or decision entry was written.

Claude's final prose was not used as acceptance evidence. Durable hashes:

- transcript:
  `8b4e542e07469a07f813e1f52e31f9c53ca8d4d6af8f784904a455fd0204c202`
- runtime receipts:
  `dce4c316223bc5404c793ab2d4e59ec95670b20636dab2ce5bb6b11acfa3149c`
- cancellation receipt:
  `d0dfb463a702b6b70491d72c7e1a14db073a3fc86e8f19392c912ed028dee277`
- fresh work plan:
  `bb4f90c068af2e29b6dd9b964dadf5dcaef9384d0f59175bdb1f6538a37f7114`
- loop journal:
  `709af3538188c2bab404d71dedf183927d00f99ec4f743cd598d7c4d06caaa42`

## Iteration Notes

The first setup attempt used an intentionally minimal directory that was not a
formal run; its failed resume was rejected as acceptance evidence. A later
cancel-only prompt exposed that a successful cancellation's raw JSON did not
remind the model that the front stays open. The candidate was tightened so the
CLI now emits one explicit next-owner boundary: cancellation settles assignment
debt only and is not a result, review, evidence item, refutation, lane/cycle
completion, or front-closure authority. The final PASS above uses that candidate.

This fixture validates lifecycle role selection, turn-only unlaunched
cancellation, normal replan, Agent/Reviewer settlement, and cycle completion. It
does not validate target probing, public web research, engagement closure, or
independent source review.
