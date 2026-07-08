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

## #3 加固到真·逐发现绑定 + Codex 多轮复审到 PASS(2026-06-18 续)
操作者要"复审通过的依据"——我承认首轮"Codex 过了"说重了(裁决是 WARN)。于是把修复本身再送独立
复审,连跑 4 轮,**每轮都逮到 selftest 放过的真缺陷**,逐步把 #3 从弱实现推到真 PASS:
- 第1轮 WARN(4 个): json 转义 bug / payload 过滤窄 / replay ack 全局计数 false-ack / 文档矛盾 —— 全修。
- 第2轮 confirm WARN: #3 的"全局数 `- Replay:` 条数"仍非逐分歧(别处/模板的 Replay 能误清)。→ 重写成
  **逐发现绑定**(录像 ↔ 它支撑的确认发现, 查那条自己的 ack); evidence_parse 加 per-entry `has_replay_ack`。
- 第3轮 confirm **BLOCKER**: 绑定栽在命名上 —— probe 是【全名追加】(sqli.html→sqli.html.replay.json,
  probe.py:182), 我却按去扩展名的 `sqli` 比 → **真分歧被当 owner=None 悄悄丢(假阴)**; 且我的 selftest
  用了错命名 `sqli.replay.json` 所以假绿。→ 改全名匹配 + selftest 改真命名 + 同产物多发现都报(防遮蔽)。
- 第4轮 confirm WARN: 多余的去扩展名键让 `sqli.replay.json` 误绑 `sqli.json`(假阳硬拦)。→ 删该键。
- **第5轮 confirm PASS**: "correct for canonical usage and safe to ship; no silent drop, no spurious hard-fail"。
  唯一残留=同名不同目录的 basename 碰撞, 但 probe 产物都落单一 `<run>/evidence/`, 非典型用法且只会保守
  误拦不会漏放, 非 shipping blocker。

**教训(对操作者那句"自测绿≠对"的实证)**: selftest 全绿但连续 4 轮各藏一个真 bug(含一个会"静默放过
存疑证据"的 BLOCKER); 全靠异构独立复审逼出来。复审"通过"的依据 = **独立后端连续复审至 PASS + 每个发现
都加了回归测例锁住**, 不是"自测绿"。`selftest_all` 16/16 + check_rules + check_knowledge 绿。

## 仍开
- **#1a 活靶子** —— 需操作者定(站 DVWA/Juice Shop / 指在线靶场 / 暂只合成样例)。没有真 fixture,
  #1b 机制能跑通但量不到"真实检出变化"。
