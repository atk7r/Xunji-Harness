# 2026-06-18 流水线闭环补全 #1b/#2/#3(Codex 异构复审)

接 `2026-06-17-wiring-audit.md`("还有哪些环节没闭环"诊断)。操作者定:**4 跳过,1/2/3 完善**。
本轮把诊断里的真开环补上(纯能力建设, 非接线), 全程 Codex 异构复审。

## 处置
**#1 度量闭环**
- ✅ **#1b 过程断言(核心)** — `bench.py` 加 `expected_process`: truth.json 声明"该不该触发
  knowledge_match/fetch_assets/独立复审", bench 去 run 产物查【真触发了没】; `must` 未触发计入
  `_is_clean` 回归门。补"bench 只量结果、量不到接线/过程类改动"的洞。纯读产物, 不发包。
- ⚠️ **#1a 真 fixture —— 卡在活靶子(未完成)**: 勘察发现现有 `bench/example-dvwa-sqli` 是
  **合成样例(非活靶子)**, "复用 DVWA"扑空。真量"改动让 driver 多检出"需站一个良性靶场
  (DVWA/Juice Shop Docker)做真 run —— 这步需操作者定环境。**留待操作者拍板**, 不擅自伪造 fixture。

**#2 知识写回端** — ✅ 新建 `tools/knowledge_seed.py`: 据识别起一条合规 grounding **seed**
(过 check_knowledge), `--from-body` 抽候选 signature 供核对。注册进 `selftest_all`。触发接好:
`knowledge_match --body` miss → seed(`WORKFLOW.md` Reason pass + cognition 写回端 + 收口"捕获知识"
+ `ROUTER.md` 目录)。把飞轮写回端从"裸手编/只收口"补成"有脚手架 + miss 即捕获"。

**#3 过期证据** — ✅ `check_run.py`: 跑了 replay 得 DIVERGED + report 终版 + 未 re-adjudication →
**硬拦**(`run_replay_verify` 改返回 (warns, errors))。**守住 replay 'opt-in/建议'原设计**: 没传
`--replay-verify`/没 DIVERGED 都不触发; 目标合法变更可逐条加 `- Replay:` 说明保留。只堵"跑了又装没看见"。

## 自测
`selftest_all` 16/16 绿(含新 knowledge_seed 套件 + bench 过程断言 4 例 + check_run replay 门 7 例);
`check_rules` / `check_knowledge` 绿。纯文档+工具, **未碰 sentinel/hooks/guard**(check_run 是收口结构门,
非那三个效果门; 但仍按本会话惯例过 Codex 复审)。

## Codex 异构复审(`codex exec -s read-only`)—— WARN, 4 真问题, 已全修
selftest 全绿仍逮到 4 个(异构复审补盲的价值):
1. **真 bug** `knowledge_seed` 手拼 signatures JSON 不转义 → 含 `"`/`\` 的 signature 产出非法 JSON,
   过 check_knowledge 结构门但 `knowledge_match` 的 `json.loads` 静默吞成 `sigs=[]` → 永不匹配(飞轮白写)。
   → 改 `json.dumps`。烟测 `he said "hi"`/`a\b` 现产合法 JSON。
2. **payload 形状过滤太窄** extract_signatures 只挡 5 种, 漏 `/dev/tcp/`/`<?php`/`eval($_`/`sleep(`/SQLi
   → 可能把武器形状串写进公开层。→ 对齐 check_knowledge.PAYLOAD_SHAPE_PATTERNS 全集。
3. **false-ack 绕过** replay ack 原是"全局有无一条 `- Replay:`"→ ack 一条放过所有分歧。
   → 改【逐条计数】: `- Replay:` 条数 < DIVERGED 条数即拦。加 "2 分歧只 1 ack 仍拦" 测例。
4. **文档自相矛盾** `WORKFLOW-reference.md` 仍写 replay "never a hard gate", 与新硬门冲突。→ 改文档
   说清"仍 opt-in、但跑了又忽略 DIVERGED 会硬拦; 逐条 `- Replay:` 处理; 不强制跑、不自动否定发现"。
- 非问题(Codex 确认): 调用点/opt-in/定义顺序均正确; bench 子串 signal 脆弱性=固有取舍(已加文档提示选稳健踪迹)。

## 改动文件
- `tools/bench.py`(#1b + 文档)、`tools/knowledge_seed.py`(新, #2 + Codex#1/#2 修)、
  `tools/check_run.py`(#3 + Codex#3 修)、`tools/selftest_all.py`(注册)、
  `docs/WORKFLOW.md`/`docs/cognition/README.md`/`docs/ROUTER.md`(#2 触发)、
  `docs/WORKFLOW-reference.md`(Codex#4 doc 修)、本记录。

## 仍开
- **#1a 活靶子** —— 需操作者定(站 DVWA/Juice Shop / 指在线靶场 / 暂只合成样例)。没有真 fixture,
  #1b 机制能跑通但量不到"真实检出变化"。
