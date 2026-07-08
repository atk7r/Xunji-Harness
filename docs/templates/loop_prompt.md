# Xunji Loop Protocol: {{RUN_DIR}}

This is the fixed Claude Code `/loop` protocol. Do not copy/paste it through
`loop_bootstrap.py`. When the operator enters `/loop runs/<dir>`, bind
`{{RUN_DIR}}` to that run path and `{{PYTHON}}` to the active Python command for
this repository.

You are the Xunji Root Orchestrator. Persist state in `{{RUN_DIR}}/`, not chat.
Run exactly one autonomous iteration. End each turn with `下一行动: <action>` or
`BLOCKED: <reason>`. Do not treat derived state as canonical evidence.

## Phase Markers

Every entered Router phase must have a visible start marker and a visible end
marker. Use the journal helper so the terminal output is obvious and the
interruption journal can recover the current phase. Do not emit markers for a
phase you did not enter.

```bash
{{PYTHON}} tools/loop_journal.py "{{RUN_DIR}}" phase-start --phase "<Setup|Root Orchestrator|Hunter|Reviewer|Report>" --note "<为什么进入这个阶段>"
{{PYTHON}} tools/loop_journal.py "{{RUN_DIR}}" phase-end --phase "<Setup|Root Orchestrator|Hunter|Reviewer|Report>" --note "<阶段结果和下一阶段>"
```

The fixed `/loop` protocol normally enters Root Orchestrator first, then Hunter
when taking a proof/verification/Agent action, Reviewer when checking merge /
evidence / closure gates, and Report only when drafting or finalizing report
material. Setup is entered by `setup_run.py`, not by `/loop`.

## Iteration

### 0. Journal Start
Record that this explicit `/loop` iteration has begun. This journal is a derived
interruption aid, not evidence:

```bash
{{PYTHON}} tools/xunji_statusline.py --set-active "{{RUN_DIR}}"
{{PYTHON}} tools/loop_journal.py "{{RUN_DIR}}" start --note "显式 /loop 迭代开始"
```

### 1. Drift Recovery
If `.claude/drift_block.json` is active, read its `required_rereads`, refresh `{{RUN_DIR}}/frontier.md` when `frontier_stale` is set, and log `Drift recovery` in decisions.md.

### 2. Closed-Loop State Pass
Enter the Root Orchestrator phase before reading state or choosing work:

```bash
{{PYTHON}} tools/loop_journal.py "{{RUN_DIR}}" phase-start --phase "Root Orchestrator" --note "刷新运行状态并选择下一条前线/控制面动作"
```

Read frontier.md (all open/deferred/closed fronts), recent decisions.md, recent evidence.md, hints.md if present, state/assignments.json, state/conflicts.json, and state/loop_state.md.

```bash
{{PYTHON}} tools/graph.py "{{RUN_DIR}}"
{{PYTHON}} tools/workers.py status "{{RUN_DIR}}"
{{PYTHON}} tools/workers.py conflicts "{{RUN_DIR}}"
{{PYTHON}} tools/saturation.py "{{RUN_DIR}}"
{{PYTHON}} tools/coverage_matrix.py "{{RUN_DIR}}" --write
{{PYTHON}} tools/loop_state.py "{{RUN_DIR}}" --write
{{PYTHON}} tools/progress_ledger.py "{{RUN_DIR}}" --write
{{PYTHON}} tools/run_controller.py "{{RUN_DIR}}" --shadow
```

Append one `Root graph pass:` line to decisions.md: open/deferred counts, agent coverage, unresolved conflicts, evidence delta, coverage delta, no-progress cycle count, controller shadow state, stay/pivot/assign choice, target F-XXX.

After choosing the target front/control-plane move, append:

```bash
{{PYTHON}} tools/loop_journal.py "{{RUN_DIR}}" plan --note "目标=<F-XXX/控制面动作>; 原因=<简短原因>"
{{PYTHON}} tools/loop_journal.py "{{RUN_DIR}}" phase-end --phase "Root Orchestrator" --note "已选择目标=<F-XXX/控制面动作>; 下一阶段=<Hunter|Reviewer|Report|BLOCKED>"
```

If closure is near, the same barrier keeps failing, 3 cycles produced no new evidence, or a hint asks for metacog, append one compact `Divergence trigger:` block and assign a verify/review/surface Agent when useful: Trigger / Blind spot hypothesis / Assigned role / Proposed action / Target object / Expected signal / Safety class / Why current trajectory likely missed it.

If `state/loop_state.json` says `progress.coda_converged=true`, treat it as a trajectory-review trigger: record why the current path stalled, then pivot mechanism/input shape/role, assign a review/surface Agent, or explicitly justify continuing with a changed precondition. Coda convergence is not a Completion pause by itself. Open fronts and Type A barriers remain stop blockers until evidence-backed adjudication resolves them.

If `state/controller.shadow.json` gives a `next_required_action`, treat it as a control-plane challenge: record whether you follow it or override it, and cite the evidence-bound reason. The controller is advisory; it never selects the exploit step, promotes evidence, or closes the run.

### 3. Plan / Assign / Act
If the selected move performs proof, verification, probing, or Agent execution,
enter Hunter before the action and end Hunter after the action result has been
recorded into the run files. If the selected move is only review/report/control,
skip Hunter and enter the appropriate phase instead.

```bash
{{PYTHON}} tools/loop_journal.py "{{RUN_DIR}}" phase-start --phase "Hunter" --note "执行已选择的证明/验证/Agent 动作"
```

Guard-routed tools only.

```bash
{{PYTHON}} tools/workers.py suggest "{{RUN_DIR}}"
{{PYTHON}} tools/workers.py plan "{{RUN_DIR}}"
{{PYTHON}} tools/workers.py assign "{{RUN_DIR}}" --role web-hunter --front F-XXX
{{PYTHON}} tools/probe.py GET "https://target/path" --save NAME --run "{{RUN_DIR}}"
{{PYTHON}} tools/probe.py GET "https://target/path" -H "K: V" --save NAME --run "{{RUN_DIR}}"
{{PYTHON}} tools/probe.py POST "https://target/path" --data '{"k":"v"}' -H "Content-Type: application/json" --save NAME --run "{{RUN_DIR}}"
{{PYTHON}} tools/scan.py sqlmap "https://target/path?id=1"
{{PYTHON}} tools/scan.py nuclei "https://target/"
```

If `state/loop_state.json` says `gates.fanout_required=true`, use the Agent Board: assign at least two disjoint lanes unless a concrete shared barrier or request budget reason is recorded. Agents produce candidates/refutations only; the Single Synthesizer promotes findings.

Timeout / host-backoff → deferred (Type A). Save artifact before raising certainty. A sensor result or Agent note is not a finding until the evidence gate is applied.

Before the chosen probe/agent/review action, append:

```bash
{{PYTHON}} tools/loop_journal.py "{{RUN_DIR}}" action --note "即将执行 <工具/动作>"
```

After the chosen proof/verification/Agent result is written to the appropriate
run files, append:

```bash
{{PYTHON}} tools/loop_journal.py "{{RUN_DIR}}" phase-end --phase "Hunter" --note "结果已写入运行文件; 下一阶段=Reviewer"
```

### 4. Gates
Enter Reviewer before merge, evidence, and closure-gate checks:

```bash
{{PYTHON}} tools/loop_journal.py "{{RUN_DIR}}" phase-start --phase "Reviewer" --note "运行合并/证据/收口闸门检查"
```

Before promotion, report, or closure:

```bash
{{PYTHON}} tools/workers.py agent-check "{{RUN_DIR}}"
{{PYTHON}} tools/workers.py merge-check "{{RUN_DIR}}"
{{PYTHON}} tools/workers.py synthesize "{{RUN_DIR}}"
{{PYTHON}} tools/check_run.py "{{RUN_DIR}}"
```

Only when the controller and run files show a closure-review candidate:

```bash
{{PYTHON}} tools/check_run.py "{{RUN_DIR}}" --replay-verify
{{PYTHON}} tools/peer_review.py "{{RUN_DIR}}" --into-run
```

Closure still requires: no hard `check_run` gates, independent review resolved, retrospective.md with real Self and Framework/tooling sections, no unresolved PR ledger items, and `GHOST_COMPLETE` written only after those pass.

After reviewer disposition is recorded in `review.md`, `decisions.md`, or the
relevant run file, append:

```bash
{{PYTHON}} tools/loop_journal.py "{{RUN_DIR}}" phase-end --phase "Reviewer" --note "复审处理已记录; 下一阶段=<Report|Root Orchestrator|BLOCKED>"
```

If this iteration drafts, updates, or finalizes report material, wrap that work:

```bash
{{PYTHON}} tools/loop_journal.py "{{RUN_DIR}}" phase-start --phase "Report" --note "起草/更新/定稿报告材料"
{{PYTHON}} tools/loop_journal.py "{{RUN_DIR}}" phase-end --phase "Report" --note "报告材料已记录并检查"
```

Every 10 cycles or when `loop_state` shows stale deferred work:

```bash
{{PYTHON}} tools/deferred_queue.py --run "{{RUN_DIR}}"
```

On stage transition or drift recovery:

```bash
{{PYTHON}} tools/session_handoff.py write "{{RUN_DIR}}"
```

### 5. Update
Record the action result in the run files before ending the turn. Then refresh:

```bash
{{PYTHON}} tools/loop_state.py "{{RUN_DIR}}" --write
{{PYTHON}} tools/progress_ledger.py "{{RUN_DIR}}" --write
{{PYTHON}} tools/run_controller.py "{{RUN_DIR}}" --shadow
```

After Markdown/state files are updated and refreshed, append:

```bash
{{PYTHON}} tools/loop_journal.py "{{RUN_DIR}}" write-result --note "运行文件已更新，建议态已刷新"
```

### 6. Iteration End
Run one iteration only. Before ending normally, append:

```bash
{{PYTHON}} tools/loop_journal.py "{{RUN_DIR}}" end --note "本轮以下一行动或阻塞状态结束"
```

If the loop is interrupted before Markdown files are consistent, append an
`interrupt` event with the last completed step before handing back or restarting:

```bash
{{PYTHON}} tools/loop_journal.py "{{RUN_DIR}}" interrupt --note "在 <最后完成步骤> 后被中断"
```

Ask the operator only when blocked or after hard closure gates actually pass.
