# Retrospective

> 强制收口产物 (mandatory closure artifact). 每次渗透收口都要诚实复盘 —— 不是免责声明,
> 是下一次更强的依据。check_run 收口硬门要求下面【自身问题】与【框架/工具问题】两节有真实内容
> (非空占位); 深浅由 driver 负责。把空泛套话留白, 写具体到本 run 的判断与摩擦。

## Run summary / 本次概述

scshr.com (飛騰雲端) — 14 确认可达资产全覆盖, 12 条证据, 0 confirmed HIGH/CRITICAL。WordPress 安全配置良好 (REST API 用户枚举 + 内部IP泄露为主要发现), HR SaaS 全系 GUID 多租户门控 (无有效租户 GUID 无法接触业务逻辑), FortiGate SSL VPN 使用 Azure AD SAML (CVE-2022-40684 已修补), IIS 裸机 ×4 无应用。codex peer_review 发现重大遗漏 (保存文件未读取, GUID 值未分析, client 页面错误标记为无表单), 均已修复。

## Self (driver) problems / 自身问题

1. **保存文件 vs stdout 读取盲区 (最严重)**: probe.py 的 stdout JSON body 字段常为空, 而实际完整内容保存在 `.html` 文件中。我在第一轮过度依赖 stdout JSON, 没有交叉验证保存的文件, 导致错误分析 `client-default.aspx` (声称"无表单/脚本/隐藏字段", 实际含 10 个隐藏字段 + 4 个脚本) 和遗漏 `schedule-root.html` 中的完整系统信息 (version/ProgramItems/DB 日志配置等)。教训: **每次 probe --save 后必须先读保存的 .html 文件, 不能只解析 stdout JSON body**。

2. **隧道视野 (Type A vs B 判断过急)**: 在 GUID 枚举第一次失败后, 没有深入分析保存文件中的 `__UNIQUEGUID`/`ParentUniqueGUID` 参数。这些 GUID 值被 codex 从保存文件中发现, 而我在做出 "GUID 枚举不可行" 结论时未检查已保存的页面内容。应养成习惯: **下结论前先 grep 所有保存文件中的潜在攻击参数**。

3. **过早关闭前沿**: F-003~F-010 被我标记为 blocked_type_a 时, 部分判断基于错误的事实基础 (client "无表单" 等)。前沿不应该在事实基础有误的情况下关闭。

4. **证据引用的 artifact 路径不精确**: E-007 引用了 yk50lan-root.html 但实际 SAML 证据在 yk50lan-saml.html (两个不同的端点)。证据 Artifacts 字段应引用具体相关的文件。

## Framework / tooling problems / 框架与工具问题

1. **probe.py stdout JSON body 不可靠**: 多次出现 stdout JSON body 为空 (len>0 但 body 字段为空字符串) 的情况, 导致分析完全依赖 snippet 而遗漏关键内容。建议 probe.py 在 --save 时自动输出 "saved to <path>" 并附带文件大小/校验, 或者确保 body 字段始终包含内容。

2. **check_run 未检测到 "空分析"**: check_run 通过了即便 frontier 中有明显错误 (client "无表单" vs 实际 10 个隐藏字段)。check_run 可能无法交叉验证 frontier 声明与 artifacts 内容。

3. **coverage.json 语义混淆**: coverage.json 由 Guanlan 的 setup_run 生成, `examined: 0` 字段含义与 Xunji driver 的 "已检查" 不同, 且无法通过工具自动回填。导致代码合规性检查误报。

## Improvements / 改进项

1. **SOP 修改**: 每轮 probe 后必须立即读取保存的 .html 文件 (不依赖 stdout JSON body 字段), grep 关键模式 (GUID/hidden/scripts/version/input), 记录到 decisions.md
2. **工具改进**: 修改 probe.py 确保 stdout JSON body 始终包含完整响应 (或至少警告 if body empty but response had content)
3. **知识条目**: 创建 knowledge/ais-webform.md 记录 AIS WebForm 框架指纹 (__UNIQUEGUID/ais.webform.js/ParentUniqueGUID/伺服端資訊 页面结构)
4. **frontier 模板**: 在 Closed Front 模板中增加 "Artifacts checked: <列出用于做结论的 evidence 文件>" 字段, 防止基于空 stdout 的错误关闭
