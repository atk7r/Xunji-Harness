# Independent Reviewer (收口前独立复审)

Self-review does not fix self-review bias: a driver that wants to conclude will
rationalize through its own re-reading. The fix is an **independent reviewer with
fresh context** — an agent that did not run the engagement, has no investment in
closing it, and reads only the run artifacts.

## When it runs

**Mandatory before any "explored enough / no attack surface / 打不动" claim** (the
closure gate). The operator has granted standing authorization to spawn this
reviewer at the closure gate (option A) — do it without re-asking; do not skip it.

Also mandatory before declaring a **behavior change to safety-critical framework
code** done — `.claude/hooks/`, `tools/harness/guard.py`, `sentinel/` — with
findings recorded under `review/records/`. Narrow scope and rationale: see
`docs/WORKFLOW-reference.md` "Independent review of safety-critical code".

## How

Spawn a `general-purpose` sub-agent (fresh context) with the prompt below. Capture
its findings into `runs/<target>/review.md` under a `## Independent Review` heading
(this marker is what `tools/check_run.py` looks for at closure). **Address every
finding** — re-examine, reopen, or downgrade — before claiming the work is done.
`check_run.py` **hard-fails** a closure claim that has no `Independent Review`
record — this is a gate, not a suggestion: you cannot mark the run closed without it.

## Reviewer prompt (copy, fill `<target>`)

```
你是独立复审员。你没有参与这次渗透,对"收工"没有任何投入——你的职责是用全新视角
挑出过早收口与过度自信。只读 runs/<target>_<date>/ 下的文件(target/surface/frontier/
hypotheses/evidence/false_positive/decisions/report),不要联网、不要执行任何探测。

逐项审,给出可执行的结论(不是泛泛而谈):
1. 过早收口:哪些 front 被 closed/deferred 得太早? 哪些"打不动/无攻击面"的断言其实
   没有充分证据? 具体到 front 编号。
2. Lump 风险:哪些资产是只按 server 头/recon 分类就被归入"共享栈/默认页",而没有逐个
   看过实际内容? (对照 surface/classify 记录)
3. "够不着"≠"它安全":哪些 front 以 WAF/限流/超时/登录门控 关门(closed)却无 Refutes/
   正面证据? 这些应是 deferred(我够不着)而非 closed(它安全)——指出来。
4. 证据质量:哪些结论赋了 certainty≥0.8 却没有对照/复现? 哪些该降级?
5. 漏测面:基于 surface/frontier,还有哪些可达的攻击面根本没被测过?
6. 过度断言 / 过度保守:报告里有没有夸大(把疑似当确认)或缩水(把确认写成疑似)的?

输出格式:
- 【必须重开/再测的 front】(编号 + 为什么 + 下一步具体动作)
- 【该降级的结论】(证据 ID + 当前 certainty → 建议 certainty + 理由)
- 【未测的攻击面】(资产 + 类型)
- 【收口判定】:当前是否真的可以收口? 还是有 N 个未尽事项必须先处理?
诚实尖锐,宁可多挑。你的价值在于挑出驱动者自己看不见/不愿看见的东西。
```

## Reading its output

The reviewer's findings are advisory but **must be resolved on the record**: for
each, either act on it (reopen/re-test/downgrade) or write in `review.md` why it
is dismissed with evidence. A closure claim stands only after the Independent
Review findings are all addressed.
