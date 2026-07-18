# Xunji Loop Protocol: {{RUN_DIR}}

This is the fixed Claude Code `/loop` protocol. Do not copy/paste it through
`loop_bootstrap.py`. When the operator enters `/loop runs/<dir>`, bind
`{{RUN_DIR}}` to that run path and `{{PYTHON}}` to the active Python command for
this repository.

This fixed protocol applies once a run is bound. For a first `/loop <source>`
turn, stay in the same top-level operator turn and execute exactly one argv-only
bootstrap command: `python3 tools/loop_bootstrap.py --source '<source>' --type auto`.
Use the current registered Python executable (a bare name is valid only when it
resolves to that same executable) and shell-quote the source as one literal argv
token. Do not use `tool_input.env`, inline environment assignments, unquoted URL
query/glob characters, brace/tilde/EQUALS/parameter/command expansion, redirects,
chains, comments, newlines, `2>&1`, a pipe, `head`/`tail`, or another shell wrapper.
After the transaction binds the new run, perform a fresh CronList and a
CronCreate whose prompt names that new run, then create/update the iteration task
list before any Agent or target action. A premature CronCreate denial is a
fail-closed recovery signal, not the recommended bootstrap step. Never clear the
old pointer or schedule the old run to get past the gate.

`XUNJI_E_LIFECYCLE_EXACT_ARGV_REQUIRED` is a non-authorizing command-shape denial.
Remove any observational wrapper; for `invalid-argv`, return to the corresponding
owner document and supply every required registered argument. Retry in the same
operator turn. Inspect source or manifests with Read/Grep/Glob, never `python -c`.
Do not wait for a bare “继续”: a new prompt revokes the previous source transition
authority and may return `XUNJI_E_RUN_TRANSITION_AUTHORITY_MISSING`.

You are the Xunji Root Orchestrator. Persist state in `{{RUN_DIR}}/`, not chat.
Run one **material** autonomous iteration: state pass, required Agent execution,
merge/verification, canonical writes, and refreshed gates. Planning, one request,
one file edit, or satisfying a hook format is not an iteration result. Until the
run has a valid completion marker, an `EXECUTE` turn ends with exactly one final
Coda line: `下一行动: <object + concrete
action>`. Empty/template values, generic "continue", multiple Coda lines, and an
unrelated or multiple F-id/action list are invalid. `BLOCKED:` cannot discharge
an unfinished active run; record the external dependency in canonical state and
make that record or the next viable pivot the single next action. Do not treat
derived state as canonical evidence.

Stop output is an exclusive union: ordinary `NORMAL_CODA`, receipt-backed
`TARGET_DENIED`, or receipt-backed `MAINTENANCE_BLOCKED`. Never mix variants or
append success prose to a fixed envelope. A Stop output is not the plan's typed
`cycle_end` and cannot create completion.

## Phase Markers

Every entered Router phase must have a visible start marker and a visible end
marker. Use the journal helper so the terminal output is obvious and the
interruption journal can recover the current phase. Do not emit markers for a
phase you did not enter.

```bash
{{PYTHON}} tools/loop_journal.py "{{RUN_DIR}}" phase-start --phase "<Setup|Root Orchestrator|Hunter|Reviewer|Report>" --note "<为什么进入这个阶段>"
{{PYTHON}} tools/loop_journal.py "{{RUN_DIR}}" phase-end --phase "<Setup|Root Orchestrator|Hunter|Reviewer|Report>" --note "<阶段结果和下一阶段>"
```

Setup-only does not enter this protocol. A first-source `/loop` may run its setup
adapter in the same authorized turn; the fixed protocol begins after that adapter
binds the run and normally enters Root Orchestrator first, then Hunter
when taking a proof/verification/Agent action, Reviewer when checking merge /
evidence / closure gates, and Report only when drafting or finalizing report
material. Record Setup only when the first-source adapter actually entered it.

## Iteration

### 0. Completion Guard, Then Journal Start

Before any journal `start`, phase marker, task, work plan, Agent, or target action,
check whether this run already has a valid `GHOST_COMPLETE` or `NORMAL_COMPLETE`
marker. If it does, perform a fresh CronList, delete only a scheduled `/loop` job
whose prompt names this exact run if one exists, then CronList again to verify it is
gone. Do not create or reschedule a Cron. Do not call `loop_journal.py ... start` or
`loop_journal.py ... end` for this already-completed run: its existing typed
`cycle_end` remains terminal, so a new empty cycle or repeated end is invalid.
Return directly with `BLOCKED: run already complete` after the Cron check/cleanup;
do not create tasks, plans, receipts, phases, or canonical writes.

Only when no valid completion marker is present, record that this explicit `/loop`
iteration has begun. This journal is a derived interruption aid, not evidence:

```bash
{{PYTHON}} tools/xunji_statusline.py --set-active "{{RUN_DIR}}"
{{PYTHON}} tools/loop_journal.py "{{RUN_DIR}}" start --note "显式 /loop 迭代开始"
```

After run/Cron binding, use Claude Code TaskCreate/TaskUpdate for this `/loop`
iteration before choosing the next Agent or target action (TodoWrite is accepted
only as a compatibility surface). The task list must cover the concrete
assets/vectors/Agent lanes/evidence writes/gates for this single iteration.
Update it as work finishes. A task list is planning proof, not Agent execution:
continue through graph/front decomposition, workers assignments, real Agent tool
launches, adjudication, and synthesis. Do not impose this rule on normal chat
outside `/loop`.

The Task receipt is also not `xunji.work-plan.v1`. Root must declare one derived,
reversible goal view in the work plan: S1 information collection, S2 testing and
continuous review, or S3 closure. `run_model.py` derives readiness; these labels
are not Router phases or canonical truth. S2 requires the S1 scope baseline plus
coverage/front readiness. S3 additionally requires zero open or Type-A/deferred
fronts and zero plan merge/review debt. If the premise changes, move backward
with a material `--replan-reason` only after the prior plan has a debt-free typed
`cycle_end`. This is the current Python/Hook control implementation; this stage
does not add a parallel plan, assignment, or merge runtime.

Material floor: do not end after the first response or local gate repair. When
fan-out is required, wait for at least two disjoint Agent results, adjudicate both,
and merge/refute their candidate material before ending. Otherwise continue the
selected front through a saved result plus control/pivot, or through an
evidence-backed barrier/failure-budget decision. A Coda is the final projection of
that work, never the work product itself.

### 1. Drift Recovery
Use the semantic status in the next step. If canonical input digests changed since
the last Reason-pass receipt, reread and adjudicate those exact inputs, then record
a new receipt after final canonical writes. If the content is unchanged, a read-only
confirmation is sufficient. Never touch or no-op edit a canonical file to manufacture
freshness; operational liveness comes from journal/runtime receipts instead.

### 2. Closed-Loop State Pass
Enter the Root Orchestrator phase before reading state or choosing work:

```bash
{{PYTHON}} tools/loop_journal.py "{{RUN_DIR}}" phase-start --phase "Root Orchestrator" --note "刷新运行状态并选择下一条前线/控制面动作"
```

Read frontier.md (all open/deferred/closed fronts), recent decisions.md, recent evidence.md, hints.md if present, state/assignments.json, state/conflicts.json, and state/loop_state.md.

```bash
{{PYTHON}} tools/anti_drift.py --semantic-status "{{RUN_DIR}}"
{{PYTHON}} tools/graph.py "{{RUN_DIR}}"
{{PYTHON}} tools/workers.py status "{{RUN_DIR}}"
{{PYTHON}} tools/workers.py lifecycle-check "{{RUN_DIR}}"
{{PYTHON}} tools/workers.py conflicts "{{RUN_DIR}}"
{{PYTHON}} tools/saturation.py "{{RUN_DIR}}"
{{PYTHON}} tools/coverage_matrix.py "{{RUN_DIR}}" --write --sync-coverage
{{PYTHON}} tools/loop_state.py "{{RUN_DIR}}" --write
{{PYTHON}} tools/progress_ledger.py "{{RUN_DIR}}" --write
{{PYTHON}} tools/run_controller.py "{{RUN_DIR}}" --shadow
```

Append one `Root graph pass:` line to decisions.md: open/deferred counts, agent coverage, unresolved conflicts, evidence delta, coverage delta, no-progress cycle count, controller shadow state, stay/pivot/assign choice, target F-XXX.

Remember the next strictly increasing Reason-pass cycle id shown by semantic
status. Record the receipt after this iteration's final canonical writes, so the
snapshot is not immediately stale. Do not `touch` or no-op edit canonical files
to satisfy freshness. Reason-pass is content-digest bound; operational liveness
comes separately from journal/runtime receipts. The receipt grants no authority,
evidence status, or closure.

Draft effect lanes and commit the current-turn work plan while Root Orchestrator
still owns planning:

```bash
{{PYTHON}} tools/workers.py suggest "{{RUN_DIR}}"
{{PYTHON}} tools/workers.py plan "{{RUN_DIR}}" --limit 2
{{PYTHON}} tools/work_plan.py commit "{{RUN_DIR}}" --stage S2 --objective "review one bounded front" --mode SERIAL_AGENT --reason "one dependency chain" --exit-gate "frozen result reviewed and Root-disposed" --lane '{"id":"L-F001-HUNTER","role":"web-hunter","front":"F-001","effect":"local_read","assets":[],"dependencies":[],"expected_evidence":"attributable candidate or refutation","expected_information_gain":"high","stop_condition":"candidate or refutation returned","request_cost":0,"request_budget":0,"merge_cost":20,"atomic":false}' --lane '{"id":"L-F001-REVIEW","role":"review","front":"F-001","effect":"local_verify","assets":[],"dependencies":["L-F001-HUNTER"],"expected_evidence":"digest-bound review disposition","expected_information_gain":"medium","stop_condition":"exact frozen result challenged","request_cost":0,"request_budget":0,"merge_cost":10,"atomic":false}'
{{PYTHON}} tools/work_plan.py status "{{RUN_DIR}}"
```

The commit line is a SERIAL/local example. Use the exact lane JSON emitted by
`workers.py plan`, choose the ready S1/S2/S3 goal and SERIAL/PARALLEL mode from
dependencies, effect overlap, runtime slots, request/model-egress budgets, and
merge capacity, and repeat `--lane` in the same argv for every lane. Do not copy
the example IDs onto a different run. If a prior plan exists, add a material
`--replan-reason`; a stage change also requires that plan's typed `cycle_end`.

After choosing the target front/control-plane move, append:

```bash
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

Before target I/O, keep generated project/run/Agent/operator identity and real
personal data out of request paths/queries, headers, bodies, multipart
names/content, and target writes. Use neutral unique
`tmp/diag/proof-YYYYMMDD-<6-12hex>` values. Only required authentication PII may
use the guarded explicit auth exception; a privacy-redacted replay is not a
successful verification.

```bash
{{PYTHON}} tools/workers.py delegate "{{RUN_DIR}}" --runtime-slots 1 --request-budget 0 --model-egress-budget 0 --merge-capacity 40 --limit 1
```

The selected Hunter Agent, and only a lane whose committed effect/assets allow
it, may use registered guarded target capabilities such as these exact shapes:

```bash
{{PYTHON}} tools/probe.py GET "https://target/path" --save NAME --run "{{RUN_DIR}}"
{{PYTHON}} tools/probe.py GET "https://target/large-doc" --save NAME --run "{{RUN_DIR}}" --save-chunks
{{PYTHON}} tools/probe.py GET "https://target/path" -H "K: V" --save NAME --run "{{RUN_DIR}}"
{{PYTHON}} tools/probe.py POST "https://target/path" --data '{"k":"v"}' -H "Content-Type: application/json" --save NAME --run "{{RUN_DIR}}"
{{PYTHON}} tools/probe.py POST "https://target/path" --preflight-get "https://target/form" --extract-csrf 'name="__RequestVerificationToken" value="([^"]+)"' --cookie-jar "{{RUN_DIR}}/state/probe-cookies.json" --preflight-save FORM --data 'field=value' --save NAME --run "{{RUN_DIR}}"
{{PYTHON}} tools/scan.py --run "{{RUN_DIR}}" sqlmap "https://target/path?id=1"
{{PYTHON}} tools/scan.py --run "{{RUN_DIR}}" nuclei "https://target/"
```

`workers.py delegate` only creates the ready assignment, context pack, and exact
binary launch contract. It does not spawn an Agent. For every returned assignment,
Claude must copy both exact `subagent_type` and exact `launch_prompt` into the real
Agent tool call. Role `review` requires `xunji-reviewer`; canonical execution roles
`surface|web-auth|web-hunter|code-audit|exploit|verify|report` require
`xunji-hunter`. Missing/null/blank, `general-purpose`, role-swapped, case-shifted,
or whitespace-padded types fail closed. The parent request and actual same-session
Start/Stop types must agree.
The hook-observed return freezes the content-addressed response snapshot and
merge draft. A launch acknowledgement, Agent file, heartbeat, Task receipt, or
`done` prose is not a return or merge.

Launch only one previously unbound Agent per assistant message. Start hooks may
not carry the parent tool id/prompt, so two candidates in one message are ambiguous
and fail closed; arrival order is never identity. For real parallelism, call Agent A,
then in the next assistant message call Agent B while A remains running.

Before consuming an existing plan, require its matching committed v2 work-plan
transaction, immutable receipt-hash archive, and intact prior-receipt chain. Do
not commit over a missing/prepared/unreadable/unarchived transaction. Only a
genuine pre-transaction plan with an exact typed journal and already frozen snapshot may use
`{{PYTHON}} tools/work_plan.py migrate-legacy "{{RUN_DIR}}"`; this is an explicit
control action, never `ROOT_DIRECT`; the same command may visibly upgrade only an
exact committed native v1 receipt, retaining both archived receipts. Assignment
creation, runtime projection, heartbeat, review, and Root finish share one lock.
Exact Agent hook replay is idempotent; conflicting reuse or duplicate attempts
fail closed. A `SubagentStop` closes only one same-session unique launch;
cross-session, unmatched, or ambiguous Stops remain lifecycle debt.

If `chains.md` or `hints.md` changes after delegation, do not launch a stale
assignment. A returned/failed lane may proceed only to its unique exact
`XUNJI_COMPLETION_REVIEW` Reviewer. A non-Reviewer with no launch/runtime/result/review
fact may be retired with:

```bash
{{PYTHON}} tools/workers.py cancel-unlaunched "{{RUN_DIR}}" A-<assignment> --reason "canonical inputs changed before launch"
```

Root must then commit a material replan. Cancellation is not a result, merge, review,
evidence item, or `cycle_end`.

Choose concurrency from effect/dependency/resource compatibility first. If
`state/loop_state.json` says `gates.fanout_required=true`, the historical `>=4`
diverse-front breadth fallback additionally requires the current coordination
epoch to have two disjoint Agent lanes. Bare continue/resume keeps existing
attempts; do not spawn duplicates unless front topology or asset debt changed. Every
target-facing assignment uses explicit `--asset` members and its Agent prompt carries
the exact `XUNJI_ASSIGNMENT=A-...`, `XUNJI_FRONT=F-...`,
`XUNJI_ASSETS=h1,h2`, `XUNJI_LANE=L-...`, and `XUNJI_PLAN=<64hex>` package.
Async PostToolUse is launch only; SubagentStop is return. Running children are not
blocked by Root's global disposition debt and cannot spawn nested Agents. Planning
files, heartbeat, and model-written budget reasons do not prove execution. Agents
produce candidates/refutations only; the Single Synthesizer promotes findings.

`ROOT_DIRECT` is one dependency-free atomic lane with at most one request and one
exact registry `capability_id`. Only capabilities explicitly marked
`root_direct_eligible` may be used (currently four local read/verify entries; no
target/control/model-egress/repository mutation). PreToolUse freezes one claim and
only its matching transcript-backed terminal projects the self-hashed Root-action
receipt. Missing terminal, a second action, stale binding or mutation retains debt.
The typed succeeded/failed outcome proves only the mechanical action, never
evidence, review, finding promotion, exit-gate satisfaction or closure.

Do not run `workers.py finish` before the dependent Reviewer returns. After
`review-disposition` and Root's canonical adjudication, use `--status merged` with
`--note "Evidence: E-xxx; Front: F-xxx; <disposition>"`, or a non-success terminal
status with `--note "Reason: <why>; Front: F-xxx"`. `done` without this anchored
disposition is deliberately blocked at Stop. `merged` additionally requires every
assigned host to have that Agent's successful target-action receipt and an exact-host
canonical E-entry; zero-tool and partial packages fail.

Timeout / host-backoff → deferred (Type A). Save artifact before raising certainty. A sensor result or Agent note is not a finding until the evidence gate is applied.

Version strings and 403/error pages are not closure evidence by themselves. If a
version appears patched/not affected, record a safe live payload/control E-entry
before closing that vector. If a front returns 403/default/error page, record
E-backed Host header/routing header, path transformation, and HTTP method
variation attempts before Type B closure; otherwise leave it Type A or assign an
Agent lane.

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
{{PYTHON}} tools/workers.py delegate "{{RUN_DIR}}" --runtime-slots 1 --request-budget 0 --model-egress-budget 0 --merge-capacity 40 --limit 1
```

The second `delegate` is ready only after the Hunter's real return. Claude must
call the indicated `xunji-reviewer` Agent with the exact launch prompt, including
`XUNJI_RESULT_DIGEST=<64hex>`. After the real Reviewer return, bind its disposition
to the frozen target result, then record Root's evidence-backed disposition:

```bash
{{PYTHON}} tools/workers.py review-disposition "{{RUN_DIR}}" A-<target> A-<reviewer> --status accept-candidate --note "exact digest and controls reviewed"
{{PYTHON}} tools/workers.py finish "{{RUN_DIR}}" A-<target> --status merged --note "Evidence: E-001; Front: F-001; Root accepted reviewed candidate"
```

The shown statuses are examples, not permission to accept unsupported material.
Use `needs-control`/`retry`/`refute`/other supported review disposition and the
matching Root status when evidence requires it. `review-disposition` marks the
Reviewer lane reviewed; Root remains the Single Synthesizer and must write the
canonical E/F/D decision before claiming `merged`.

Before promotion, report, or closure:

```bash
{{PYTHON}} tools/workers.py agent-check "{{RUN_DIR}}"
{{PYTHON}} tools/workers.py lifecycle-check "{{RUN_DIR}}"
{{PYTHON}} tools/workers.py merge-check "{{RUN_DIR}}"
{{PYTHON}} tools/workers.py synthesize "{{RUN_DIR}}"
{{PYTHON}} tools/check_run.py "{{RUN_DIR}}"
```

Only when the controller and run files show a closure-review candidate:

```bash
{{PYTHON}} tools/check_run.py "{{RUN_DIR}}" --replay-verify
{{PYTHON}} tools/peer_review.py "{{RUN_DIR}}" --into-run
{{PYTHON}} tools/check_run.py "{{RUN_DIR}}"
```

Closure still requires: no hard `check_run` gates, a current content-addressed
ReviewReceipt, independent review ledger resolved, retrospective.md with real Self
and Framework/tooling sections, and no unresolved PR items. Invoke the completion
Agent with exact `subagent_type=xunji-reviewer` and exact assignment-free formatter
output `XUNJI_COMPLETION_REVIEW EVIDENCE_INDEX=<current evidence_index sha1>
COMPLETION_BUNDLE=<current completion bundle sha256> run=<run.name>
CHECKS=report_parity,severity_artifacts,reachable_frontier,review_ledger`.
Do not add assignment/front/assets/lane/plan/result-digest fields; require a real
same-session Start and Stop. This pseudo completion receipt creates no assignment
or merge projection and does not replace the independent peer-review ReviewReceipt.
`## CodexCompletionReview` is only the compatible storage heading. Require the last
non-empty response line to exactly equal
`XUNJI_COMPLETION_VERDICT=PASS EVIDENCE_INDEX=<same 40hex>
COMPLETION_BUNDLE=<same 64hex> run=<same run.name>
CHECKS=report_parity:PASS,severity_artifacts:PASS,reachable_frontier:PASS,review_ledger:PASS`,
then record its substantive section before writing a completion marker. In that same
turn, CronList, delete only the listed job for this run, CronList again, and record
`cron_cancelled=<job-id|none>` in the journal end event.

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
{{PYTHON}} tools/anti_drift.py --record-reason-pass "{{RUN_DIR}}" --cycle-id 1 --chosen-front F-001 --reason "whole-graph adjudication after final canonical writes"
{{PYTHON}} tools/loop_journal.py "{{RUN_DIR}}" write-result --note "运行文件已更新，建议态已刷新"
```

Replace `1` with the next strictly increasing Reason-pass cycle id and `F-001`
with the actual chosen front (or `NONE`). If canonical content changes again,
record a newer receipt after adjudicating that change; never use mtime/touch as a
substitute.

### 6. Iteration End
End only after the material floor above is met. Before ending normally, append:

```bash
{{PYTHON}} tools/workers.py lifecycle-check "{{RUN_DIR}}"
{{PYTHON}} tools/work_plan.py status "{{RUN_DIR}}"
{{PYTHON}} tools/loop_journal.py "{{RUN_DIR}}" end \
  --next-action "<与本轮最终 `下一行动:` 完全相同的文本>" \
  --note "plan cycle disposition complete"
```

For a plan-bound cycle, `end` derives the typed `cycle_end` from every declared
lane, immutable result digest, Reviewer receipt, and Root disposition. It must
first validate the current plan's committed v2 transaction/archive lineage and
fail closed on missing/pending debt. The CLI-supplied `next_action` is the only
caller field and must be projected exactly after `下一行动:` in the final response;
never replace the receipt with a hand-written journal row or a Coda. A later
same-stage replan or stage transition references this content-addressed prior
plan/cycle.

If this iteration wrote `GHOST_COMPLETE` or `NORMAL_COMPLETE`, the `end` note
must instead include `cron_cancelled=<job-id|none>` after cancelling the active
scheduled `/loop` job if one exists.

If the loop is interrupted before Markdown files are consistent, append an
`interrupt` event with the last completed step before handing back or restarting:

```bash
{{PYTHON}} tools/loop_journal.py "{{RUN_DIR}}" interrupt --note "在 <最后完成步骤> 后被中断"
```

Ask the operator only when blocked or after hard closure gates actually pass.
