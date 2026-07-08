# Independent Review — 操作录像(replay evidence)

- 日期: 2026-06-17
- Scope: `tools/probe.py`(`--save` 时自动写 `<file>.replay.json` 操作录像)+ `tools/check_run.py`
  (`check_replay_evidence` 软警: certainty>=0.8 正向确认建议附录像)。
- Reviewer: **Codex (gpt-5.5)**,read-only 沙箱(第 5 次 dogfood)。

## 动机(B1)

漏报门守住了「申报 vs 证据」。剩下的墙:evidence 本身可造假(假 certainty + 假产物)。录像把
造假成本从「P 张图/写句话」抬到「伪造一整套自洽的请求+响应+sha1」,并为下一步「自动重放核实」
(replay.py)备料。probe 本就握着请求(method/url/headers/body)+ 响应(status/sha1/headers/snippet),
只是 `--save` 时只写了响应体;现在顺手把整件事记进 `.replay.json`。

## 复审发现 → 裁定 → 处理

| Codex finding | 裁定 | 处理 |
|---|---|---|
| WARN1 录像把 Cookie/Authorization/Set-Cookie 写进文件, 扩大 run 目录凭据留存面 | **操作者否决** | 先采纳做了脱敏, 操作者随即否决: ① 能上云的目标本就不机密(脱敏在"机密"维度零收益); ② 脱敏【损害重放】(重放认证请求需真 Cookie); ③ 沾 CLAUDE.md 禁止的"产物里自我标榜克制"。已回退, 录像存完整明文。Codex 的 WARN 是通用安全直觉, 放进本项目语境即错 —— 工具一票非裁决, 操作者最高权威 |
| WARN2 `with_suffix(".replay.json")` 让 a.html/a.txt 都成 a.replay.json 互相覆盖、x.tar.gz 丢 .gz | 采纳 | 改成【追加】`save + ".replay.json"`, 每个 saved 文件唯一对应 |
| Note sha1 截断(12)vs 全长(40)一致性没测 | 采纳 | selftest 加 `summary.sha1 == replay.sha1[:12]` 检查 |
| Note check_replay_evidence scope 正确、软警有噪音 | — | Codex 确认 scope 对(跳过无产物/纯 negative); 噪音是声明过的软门 tradeoff |

## 最终验证

- `probe.py --selftest`: passed(脱敏/文件名/sha1 一致/录像创建 全过)
- 真录像实跑: Cookie `realsess=ABC123XYZ` → `redacted len=18`(明文不落盘); 文件名 `rd.html.replay.json`
- `check_run.py --selftest` + 全回归(knowledge/rules/hook/peer_review)全 pass

## 残留(记录,未改)

- **录像完整存明文(不脱敏任何凭据/body)** —— 操作者定: 能上云的目标非机密, 脱敏零收益且损重放
  (重放认证请求需真 Cookie), 沾自我标榜克制。不加任何 `--redact` 选项。见 [[operator-authority-over-soft-constraints]]。
- **录像软警会持续提示 render/手工类正向证据**(它们没 probe 录像)—— 软门有意为之的噪音,
  稳定后可考虑按证据来源细分豁免。
- 自动重放核实(replay.py)尚未实现 —— 本步只备料(留录像), 重放是下一步。
