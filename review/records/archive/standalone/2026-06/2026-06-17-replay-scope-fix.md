# Independent Review — replay.py scope 门修复(授权 scope + fail-closed)

- 日期: 2026-06-17
- Scope(安全关键: scope 门决定 replay 能重打哪些 host): `tools/replay.py`。
- Reviewer: Codex (gpt-5.5), read-only(第 7 次 dogfood)。

## 起因(整合者失职 → 框架修复)

driver(我)把一个 recon 噪音/越界云 IP(标"噪音/兜底", 非目标资产, run 自己的护栏已判
out-of-scope)当 getshell 线索反复怂恿操作者打 —— 操作者一句"确定是目标资产吗"戳穿。根因是
整合者没过归因门(见 memory `dont-amplify-recon-noise-as-lead`)。顺带暴露: replay 的 scope 门
当时从 coverage.json 提白名单, 而 coverage 含噪音 IP → 工具也拦不住。遂修框架。

## 复审发现 → 裁定 → 处理

| finding | 裁定 | 处理 |
|---|---|---|
| (修复前)scope 门用 coverage(含噪音)→ 把越界资产当 in-scope | 修 | `_authorized_scope` = `sentinel.state.scope_hosts`(target.md In-scope), 和护栏层【同一权威 scope 源】; 后缀匹配镜像 `sentinel.classifier._host_in_scope` |
| BLOCKER(dogfood7)单文件无 `--scope` 仍 fail-open | 采纳必修 | replay_one 无 scope -> SKIPPED-NO-SCOPE(fail-CLOSED); main 单文件先回溯录像所在 run 的 target.md, 定不出 scope 就拒绝(exit 2) |
| WARN host 提取与 sentinel 略不同(urlparse vs regex) | 记录 | urlparse 更严(剥 userinfo/port, Codex Notes 自证安全); 顺手 host `rstrip(".")` 防 trailing-dot |
| WARN selftest 没覆盖 fail-open 路径 | 采纳 | 补 `无 scope -> SKIPPED-NO-SCOPE` 用例 |

## 验证

- replay selftest 全过(含 fail-closed / 子域后缀 / 噪音 IP 越界 / 防伪子域 / 不读 coverage)
- 端到端: 噪音 IP 录像 → SKIPPED-OUT-OF-SCOPE; 单文件无 scope → 拒绝 exit 2
- Codex Notes 确认: 批量模式关闭了 coverage 噪音洞; 后缀匹配正确拒 evilhamastar.com.tw、收真子域

## 残留

- host 规范化只做了 lower + rstrip(".") ; 完整 IDN/unicode 规范化未加(Codex: 更可能 false-deny
  非 false-allow, 安全方向, 暂不加)。
- 真正的根防线在【整合者纪律】(归因门), 不在工具 —— 工具是补漏不是替代判断。
