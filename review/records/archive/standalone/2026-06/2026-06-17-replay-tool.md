# Independent Review — replay.py 自动重放核实(B1-②)

- 日期: 2026-06-17
- Scope(新 active 能力): `tools/replay.py`(读录像走 guard 重放、比对核实证据对应现实)+ `probe.py`
  新增 `sha1_full`。
- Reviewer: Codex (gpt-5.5), read-only(第 6 次 dogfood)。

## 复审发现 → 裁定 → 处理

| finding | 裁定 | 处理 |
|---|---|---|
| BLOCKER 无 scope 检查就打录像 URL(篡改/越界录像能打 scope 外, 绕过 hook 的 scope 拦截 —— replay 命令行只有 run 路径, 真 URL 在录像里) | 采纳必修 | `_allowed_hosts` 从 coverage/target/surface 提 host 白名单; scope 外 → SKIPPED-OUT-OF-SCOPE; `--scope` 可显式给 |
| BLOCKER `--force` 批量重放 DELETE(再删一次, 撞 CLAUDE.md 硬边界 删资源 never) | 采纳必修 | DELETE 列 `DESTRUCTIVE_METHODS`, 永不重放(--force 也不解锁)→ SKIPPED-DESTRUCTIVE |
| WARN guard 熔断异常没接住会崩 | 采纳 | try/except → GUARD-BLOCKED |
| WARN CONSISTENT 对过期 session 太弱(登录页同 status 被当"仍支持") | 采纳 | note 强化: CONSISTENT≠核实通过, 须核对内容(过期 cookie 返回同 status 登录页) |
| WARN IDENTICAL 只比 48-bit sha1 前缀 | 采纳 | probe.send 加 `sha1_full`, replay 比全 40 位 sha1 |
| WARN selftest 没覆盖危险 case | 采纳 | 补 DELETE/scope/guard/全sha1 → 13 用例 |

## 验证

- replay selftest 13/13(含 scope/DELETE/guard/全sha1); probe selftest pass(sha1_full 不破坏现有)
- 端到端: probe 留录像 → replay IDENTICAL; `--scope nonexist` → SKIPPED-OUT-OF-SCOPE

## 残留(Codex Notes, 诚实记录)

- **replay 核实的是"录像的请求/响应在当下还成立", 不是"该响应证明了所声称的漏洞"** —— 伪造录像
  指向任意稳定端点仍能自洽。replay 闭合「证据 vs 现实」的一部分(请求可重现), 但「证据是否证明
  漏洞」仍靠 driver 判断。这是 B1 的根本边界(B 墙分析: 墙后移、不消失)。
- 破坏性/一次性/会话时效证据无法或难安全重放(SKIPPED-DESTRUCTIVE / CONSISTENT 弱化), 停在人工。
- Codex 确认 replay 实际经 probe.send 继承 guard(RateLimiter/cap_body/HostHealth/SessionBudget)。
