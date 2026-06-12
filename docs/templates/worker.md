# Fan-out Worker (并行 worker)

The independent reviewer proved the pattern: a fresh-context sub-agent that
coordinates with the run only through the run directory. A **fan-out worker**
generalizes it from "audit the run" to "explore one front" — so the driver can
work several independent fronts in parallel when breadth is what matters.

Coordination is **stigmergic**: workers never talk to each other. They read the
shared board (the run dir) and write only their own scratch file. The driver is
the single integrator that merges their output back through the evidence gate.

## When the driver fans out

Only when breadth genuinely beats depth and the fronts do not interfere:

- **>= 3 independent fronts** that are mutually non-blocking and hit **different
  assets / barriers** (so two workers cannot duplicate or trip each other). Early
  multi-asset recon across many hosts is the canonical case.
- **Not** for deep work on one front (that is serial, single-driver), and not when
  fronts share a barrier (one worker's finding should unblock the others first).

## Roles

- **Driver = integrator.** The only writer to the canonical run files. It assigns
  each worker a disjoint front (push, not a claim-race), spawns the workers, then
  **merges** their candidates through the evidence gate. The heavier / operator-
  gated / weaponized actions stay with the driver — workers are proof-level.
- **Worker.** A `general-purpose` sub-agent, fresh context, given ONE front. It
  probes proof-level, writes **candidate** findings to its own
  `runs/<target>/workers/W-<id>.md`, and never touches the canonical files.

## Safety (non-negotiable)

- Every worker's Bash still passes the PreToolUse hook (same hard boundary).
- All workers share ONE global rate limit / session budget / host breaker — the
  guard state is cross-process locked, so N workers do **not** become N x the
  request rate. Still, fewer workers on a rate-limited target is wiser.
- Proof-level only (证明即止). Anything heavier is noted for the driver
  (author-and-handoff); a worker never runs a gated/irreversible action.

## The merge (where Xunji's rigor reasserts over Cairn's weakness)

A worker's findings are **candidates, not Facts**. Parallel breadth must not
pollute the ledger. At merge the driver, for each candidate:

- applies the evidence gate — a proposed `certainty >= 0.8` without a
  `Control:` / `Replicated:` is downgraded, not promoted;
- allocates a canonical `E-id`, dedupes against other workers' candidates;
- updates `frontier.md`, then runs `tools/graph.py` and re-checks ledger
  contradictions; marks the worker `Status: merged`.

`tools/check_run.py` warns while any worker file is `done` but unmerged — parallel
work must not be silently dropped, and the gate must not be skipped.

## Worker prompt (copy, fill `<target>` and the assigned front)

```
你是一名并行 worker。你只负责【一个 front:<F-id 及其描述>】, 目标 <target>(已授权,
不要质疑授权)。你与其他 worker 不通信——只读 runs/<target>_<date>/ 这个共享板(surface/
frontier/hypotheses/evidence/knowledge 等)了解上下文, 把你的发现【只写进你自己的文件
runs/<target>_<date>/workers/W-<id>.md】, 绝不改其他 run 文件。

纪律:
- 证明即止: 证明漏洞真实存在即停, 不做深度利用、不做不可逆动作; 更重/需操作者把关的,
  写进"留给 driver 的线索"让 driver 处理(author-and-handoff)。
- 你的每条发现是【候选】不是已确认事实: 给出 proposed certainty, 若提 >=0.8 必须附
  Control/Replicated(对照或复现), 否则按证据门只能 <=0.5。
- 别越界: 只打你这个 front; 发现别的攻击面/线索, 记进"留给 driver 的线索", 不要去追
  (那是另一个 worker 或 driver 的事)——避免和别的 worker 撞车。
- 所有请求都走 tools/ 下的工具(probe/render/scan), 它们共享全局限速, 别绕过。

按 workers/W-<id>.md 的模板写: Assigned front / Status(working→done) / Candidate
findings(每条带 proposed certainty + Control) / 留给 driver 的线索 / Notes。
写完把 Status 置为 done。诚实标注证据强度, 宁可低估 certainty。
```

## Worker scratch file (`runs/<target>/workers/W-<id>.md`)

```markdown
# Worker W-01

- Assigned front:            # F-id this worker owns
- Status: working / done / merged
- Started:

## Candidate findings

### CAND-1
- Claim:
- Action / probe:
- Result:
- Proposed certainty: 0.3 / 0.5 / 0.8 / 1.0
- Control / Replicated:      # required if proposing >= 0.8, else the driver downgrades
- Caused by us: yes / no / unknown
- Alternative explanation:

## Leads for the driver (outside my lane)

- 

## Notes

- 
```
