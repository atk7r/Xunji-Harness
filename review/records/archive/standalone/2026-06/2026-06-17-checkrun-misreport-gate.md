# Independent Review — check_run 漏报一致性硬门 + peer_review 模块

- 日期: 2026-06-17
- Scope(安全关键行为改变): `tools/check_run.py` 新增收口硬门「漏报一致性」+ `parse_evidence`
  新字段 `refutes_any`; 新模块 `tools/peer_review.py`(异构复审,可接入)。
- Reviewer: **Codex (gpt-5.5)**,经 `tools/peer_review.py` 的 codex 后端,read-only 沙箱
  —— 即用新建的异构复审模块复审它自己引出的改动(dogfood)。这是 CLAUDE.md 要求的
  「安全关键代码行为改变须独立 fresh-context 复审」。

## 改动动机

hamastar run 的 report 把一个 certainty 1.0 的 [CRITICAL] SimMAGIC 越权(E-017)漏报了
(只在头部 `Evidence IDs:` 行机械列出,确认发现章节/证据清单只到 E-012),还反向声称产品平台
「CDN 阻断不可达」,与 evidence E-016/E-017 自相矛盾。老 check_run 放行。一次异构复审(Codex)
逮到(见 `2026-06-17-hamastar-codex-peer-review.md`)。故补一道纯静态、可机械化的门:evidence
里 certainty>=0.8 且非排除性、未降级的正向发现,必须在 report 正文(非头部 IDs 行)被引用。

## 复审发现 → 裁定 → 处理(逐条 on the record)

| Codex finding | 裁定 | 处理 |
|---|---|---|
| BLOCKER 代码块/注释/废话行里的 E-id 算"已报"(bypass,与指纹门 S2 同类) | 采纳 | report_body 先 `re.sub(\`\`\`/<!-- -->)` 再判;selftest E-204/E-205 |
| BLOCKER header 变体绕过(`IDs :` 空格 / `ID(s):` / 换行列 ID) | 部分采纳 | 「冒号前空格」原正则 `\s*` 已处理(此例无效);`ID(s)`/变体确实能绕 → 正则改 `^\s*Evidence\s+IDs?.*$` 不依赖冒号;selftest header 变体用例。残留(换行另起行列 ID / 正文显式写"E-x 不报")= contrived,driver 不会自伤,接受 |
| WARN 任何 `Refutes:` 字段无条件豁免 → mixed Supports+Refutes 正向发现可漏报 | 采纳 | 豁免判据收紧为「有 Refutes 且**无 Supports**」(纯 negative)才豁免;selftest E-206 |
| WARN selftest 只覆盖 happy-path | 采纳 | 补 E-204/205/206 + header 变体 = 9 用例 |

## 最终验证

- `check_run.py --selftest`: passed(漏报门 9 用例含 4 bypass 防御全过)
- `runs/hamastar_20260615`: 正确硬拦 E-013/E-014/E-015/E-016/E-017(真漏报),不误拦 E-011(negative)
- 回归: check_knowledge / check_rules / check_hook / peer_review selftest 全 pass

## 残留风险(记录,未修)

- 换行另起一行列 Evidence ID、或正文显式写「E-x 不报」仍会被算引用 —— contrived,driver 是
  帮自己的工具不会自伤,且这类显式声明会被操作者看见;模板是同行列 IDs。
- E-id 精确匹配:evidence `E-017` 与 report `E-17` 不等价(要求 canonical ID),刻意如此。
- peer_review 数据出境:API/codex 后端把 run 内容发外部厂商,仅操作者接受时用。
