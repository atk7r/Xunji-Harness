# Evidence Ledger

> Certainty: only `>= 0.8` may be reported confirmed, and a confirmed entry MUST
> carry a `Replicated / Control` field AND a saved `Artifacts` path under the run
> dir (check_run hard-fails a confirmed entry with no artifact, warns with no
> control). Full scale + meanings: `docs/cognition/README.md` "Evidence Confidence".

## E-001: WordPress REST API 用户枚举

- Maturity: candidate
- Reportable: yes
- Severity: LOW (信息泄露 — 用户列表, 非直接可利用漏洞)
- Superseded:
- Time: 2026-07-02T01:28Z
- Action: GET /wp-json/wp/v2/users + /wp-json/wp/v2/users?per_page=100
- Source: probe.py via proxy http://127.0.0.1:7892
- Result: 7 个 WordPress 用户完整信息泄露: id=1 nick (admin), id=2 Liu Tony, id=4 sc_admin (管理员), id=6 Ann, id=10 威霖, id=12 Allison, id=14 吳沛杰
- Caused by us: no (REST API 默认公开用户端点)
- Alternative explanation: WordPress 默认配置允许未认证用户枚举
- Certainty: 0.5 (单次直接观察, 数据完整可重现, 但属信息泄露非关键漏洞)
- Replicated / Control: 已通过 /wp-json/wp/v2/users/1 单独验证用户存在
- Artifacts: evidence/wp-users.html, evidence/wp-user-1.html
- Supports: F-001 (WordPress 攻击面)
- Refutes:
- Unlocks:
- Next: 已知用户列表可用于弱口令爆破/wp-login.php

## E-002: WordPress 内部 IP 泄露

- Maturity: candidate
- Reportable: yes
- Severity: LOW (信息泄露 — 内网 IP, 非直接可利用)
- Superseded:
- Time: 2026-07-02T01:30Z
- Action: GET /wp-json/wp/v2/users/1
- Source: probe.py via proxy http://127.0.0.1:7892
- Result: 用户 nick (id=1) 的 url 字段为 `http://192.168.8.221:8087` — 泄露内部网络地址和端口, 揭示 nginx → 内网 WordPress 后端架构
- Caused by us: no (WordPress 用户 profile 中存储的 url 被 REST API 公开)
- Alternative explanation: 可能是用户手动填写的测试 URL, 但 id=1 为管理员, url 格式符合内网架构地址
- Certainty: 0.5 (内网 IP 是环境信息但非直接可利用漏洞; 需结合 SSRF 或其他内网访问才能利用, 属于侦察性泄露)
- Replicated / Control: 已通过 replay 文件确认
- Artifacts: evidence/wp-user-1.html
- Supports: F-001
- Refutes:
- Unlocks: 若发现 SSRF 可尝试访问 192.168.8.221:8087
- Next: 搜索其他用户 url 字段, 检查是否有更多内网泄露

## E-003: HR SaaS 统一 JSON-RPC API 端点暴露

- Maturity: phenomenon
- Reportable: no (待进一步确认可利用性)
- Superseded:
- Time: 2026-07-02T01:35Z
- Action: GET/POST /api/ on ai.scshr.com, cloud.scshr.com, schedule.scshr.com
- Source: probe.py via proxy
- Result: 3 个 HR SaaS 主机在 /api/ 暴露相同 JSON-RPC 接口, 响应格式:
  `{"ObjectType":"","ProgID":"","Action":"","Format":"","Value":"","Exception":{"Message":"Must specify valid information for parsing in the string.","StackTrace":"","IsHandle":false}}`
  ObjectType/ProgID 模式疑似 .NET 类型反序列化接口
- Caused by us: no
- Alternative explanation: 正常的业务 API 参数验证提示
- Certainty: 0.3 (API 面已测绘但未确认可利用, 需反序列化 payload 测试)
- Replicated / Control:
- Artifacts: evidence/schedule-api.html
- Supports: F-002, F-005, F-006
- Refutes:
- Unlocks: 若确认反序列化漏洞, 可打 ai/cloud/schedule 三个主机
- Next: .NET 反序列化 payload 测试 (LosFormatter, BinaryFormatter, TypeConfuseDelegate)

## E-004: DevExpress ASP.NET 多租户架构 (GUID 路由)

- Maturity: phenomenon
- Reportable: no
- Superseded:
- Time: 2026-07-02T01:32Z
- Action: 跟随 ai.scshr.com/app.scshr.com 302 重定向
- Source: probe.py via proxy
- Result: 两个主机重定向到 Error.aspx?ParentUniqueGUID=xxx, 使用 DevExpress DXR.axd 组件; 无有效 GUID 时显示错误页 "錯誤訊息"
- Caused by us: no
- Alternative explanation: 正常的租户隔离路由机制
- Certainty: 0.5 (架构已理解但无漏洞确认, GUID 枚举无差异化响应)
- Replicated / Control:
- Artifacts:
- Supports: F-003, F-004
- Refutes:
- Unlocks: GUID 枚举或绕过可能访问其他租户数据
- Next: GUID 预测/枚举尝试, 检查是否有默认 GUID

## E-005: IIS 裸机 — 无应用部署

- Maturity: phenomenon
- Reportable: no
- Superseded:
- Time: 2026-07-02T01:33Z
- Action: 扫描 kh.scshr.com, payment.scshr.com, 122.117.135.182, 20.198.176.62
- Source: probe.py via proxy
- Result: 四个 IIS 主机仅响应 iisstart.htm 默认页面 (696-703 bytes), 所有应用路径返回 404; 判断为反向代理源站/裸 IIS, 无可攻击的 web 应用
- Caused by us: no
- Alternative explanation: 这些 IP 可能是 CDN 回源地址或反向代理后端
- Certainty: 0.5 (基于路径扫描和响应一致性, nginx 反代前端的后端)
- Replicated / Control:
- Artifacts:
- Supports:
- Refutes: F-011, F-012, F-013, F-014 (降低这些前沿的攻击价值)
- Unlocks:
- Next: 可将 F-011~F-014 降级为 deferred/closed

## E-006: WordPress 插件枚举

- Maturity: phenomenon
- Reportable: no
- Superseded:
- Time: 2026-07-02T01:38Z
- Action: 扫描 wp-content/plugins/ 已知插件列表
- Source: probe.py via proxy
- Result: 确认 4 个插件 — wp-file-manager v8.0.4 (Stable tag), Yoast SEO (wordpress-seo), Advanced Custom Fields, Really Simple SSL; wp-file-manager v8.0.4 为较新版本(CVE-2020-25213 等老漏洞不适用), PHP 文件被 nginx 保护无法直接访问
- Caused by us: no
- Alternative explanation: 正常的 WordPress 插件部署
- Certainty: 0.5 (插件已确认但未发现可利用漏洞)
- Replicated / Control: wp-file-manager readme.txt 验证版本号
- Artifacts: evidence/wp-file-manager-readme.html
- Supports: F-001
- Refutes:
- Unlocks:
- Next: 监控 wp-file-manager 新版 CVE

## E-007: FortiGate SSL VPN — Azure AD SAML SSO

- Maturity: phenomenon
- Reportable: yes (租户 ID 泄露)
- Superseded:
- Time: 2026-07-02T01:42Z
- Action: GET yk50lan.scshr.com:12443
- Source: probe.py via proxy
- Result: FortiGate SSL VPN 配置 Azure AD SAML SSO 认证, SAML 重定向泄露 Azure AD 租户 ID: `fd4fe7e3-9e23-455a-8a67-1eca0be0465a`; FortiOS 已修补 CVE-2022-40684 (API 端点返回 403); banner 已混淆 (xxxxxxxx-xxxxx)
- Caused by us: no
- Alternative explanation: 正常的 SAML SSO 配置 (但租户 ID 不应在公开重定向中泄露)
- Certainty: 0.5 (Azure AD 租户 ID 确认泄露, FortiOS 版本未知但已知 CVE 已修补)
- Replicated / Control:
- Artifacts: evidence/yk50lan-saml.html (SAML redirect with tenant ID + SAMLRequest + RelayState + Signature)
- Supports: F-103
- Refutes:
- Unlocks: Azure AD 租户 ID 可用于钓鱼/用户枚举/密码喷洒
- Next: Azure AD 用户枚举, 密码喷洒 (注意速率限制, 生产租户)

## E-008: .NET 类库文档公开暴露

- Maturity: phenomenon
- Reportable: yes (信息泄露)
- Superseded:
- Time: 2026-07-02T01:45Z
- Action: GET /api/help on api.scshr.com
- Source: probe.py via proxy
- Result: api.scshr.com 公开暴露 Sandcastle 生成的 .NET 类库文档 (AIS_Define 命名空间), 554KB 文档包含完整类结构、事件处理模型 (AfterAdd/AfterApprove/AfterCancel/AfterDelete/AfterEdit/AfterExecReport/AfterFieldValueChange), 888 个关联页面; 该文档为内部业务框架文档, 非 HTTP API 端点
- Caused by us: no
- Alternative explanation: 开发文档误部署到生产环境
- Certainty: 0.5 (确认文档公开暴露, 属于信息泄露但非直接可利用)
- Replicated / Control:
- Artifacts: evidence/api-help-namespace.html
- Supports: F-002
- Refutes:
- Unlocks: 了解内部 AIS 框架架构, 辅助后续渗透
- Next: 分析 AIS_Define 类结构寻找可滥用的业务逻辑

## E-009: WordPress REST API 完全开放

- Maturity: phenomenon
- Reportable: yes
- Superseded:
- Time: 2026-07-02T01:31Z
- Action: GET /wp-json/wp/v2/posts, /pages, /media
- Source: probe.py via proxy
- Result: WordPress REST API 未鉴权完全开放 — 文章 (847KB), 页面 (1MB), 媒体文件均可未认证访问; wp-json 路由索引 316KB 全部暴露
- Caused by us: no
- Alternative explanation: WordPress 默认 REST API 行为 (内容端点默认公开)
- Certainty: 0.5 (内容端点是设计如此, 但暴露完整路由索引 + 媒体元数据 属于信息泄露)
- Replicated / Control:
- Artifacts: evidence/wp-json-root.html, evidence/wp-media.html
- Supports: F-001
- Refutes:
- Unlocks:
- Next:

## E-010: llms.txt AI 知识源泄露内部结构

- Maturity: phenomenon
- Reportable: no
- Superseded:
- Time: 2026-07-02T01:46Z
- Action: GET /llms.txt (从 robots.txt 发现)
- Source: probe.py via proxy
- Result: llms.txt 是专为 AI 爬虫设计的结构化 markdown, 泄露: 客户列表(IKEA/虎航/肯德基), 产品定价(735 TWD/点), 内部页面路径(/ailaborlaw/, /cloudboss/, /projectb/, /scsclients/), ISO 27001 认证信息; 所有内部页面均为 WordPress, 无独立应用
- Caused by us: no
- Alternative explanation: llms.txt 是新兴的 AI 友好 sitemap 标准, 设计为公开
- Certainty: 0.3 (标准化的公开文件, 非漏洞, 但泄露客户信息)
- Replicated / Control:
- Artifacts: evidence/www-llms.html
- Supports:
- Refutes:
- Unlocks:
- Next:

## E-011: WordPress 扩展插件 REST API 结构泄露

- Maturity: phenomenon
- Reportable: yes (信息泄露)
- Superseded:
- Time: 2026-07-02T02:05Z
- Action: GET /wp-json (namespace 枚举) + 逐个 namespace 路由索引
- Source: probe.py via proxy
- Result: 发现额外 6 个未通过路径扫描检测的插件/主题 — code-snippets (Code Snippets, 含完整 CRUD REST API)、contact-form-7、leadin (HubSpot)、litespeed (LiteSpeed Cache v1+v3)、pum (Popup Maker)、divi (Divi 主题); code-snippets 暴露 17 个 REST 路由含文件导入/解析/激活端点, schema 公开可读; 所有敏感端点正确返回 401 鉴权
- Caused by us: no
- Alternative explanation: WordPress REST namespace 注册是设计行为
- Certainty: 0.5 (确认插件结构泄露但鉴权配置正确)
- Replicated / Control: schema 端点验证 (200:2100)
- Artifacts: evidence/wp-codesnippets.html, evidence/wp-leadin.html, evidence/wp-litespeed.html
- Supports: F-001
- Refutes:
- Unlocks: 若获取凭证, code-snippets 可直连 RCE (执行 PHP 代码片段)
- Next:

## E-012: WordPress 用户枚举 (lostpassword 响应大小差异)

- Maturity: candidate
- Reportable: yes (用户枚举)
- Superseded:
- Time: 2026-07-02T02:10Z
- Action: POST /wp-login.php?action=lostpassword 对不同用户名
- Source: probe.py via proxy
- Result: lostpassword 端点存在响应大小差异 — 不存在用户返回 ~5900-5915 bytes, 存在用户返回 4709 bytes (普通用户) 或 6052 bytes (管理员); 确认 7 个 WordPress 用户均存在, 枚举 oracle 可靠
- Caused by us: no (WordPress 默认 HTML 结构差异)
- Alternative explanation: 不同用户角色/语言设置导致页面 HTML 大小差异
- Certainty: 0.5 (双通道确认: REST API + lostpassword 独立验证)
- Replicated / Control: 已对所有 7 用户 + 3 不存在用户测试确认
- Artifacts:
- Supports: F-001 (强化 E-001 用户枚举)
- Refutes:
- Unlocks: 确认用户列表可用于定向密码喷洒
- Next:

## E-013: AIS 框架系统信息泄露 (schedule/cloud/client)

- Maturity: candidate
- Reportable: yes (信息泄露)
- Severity: LOW (信息泄露 — 版本/配置字符串, 非直接可利用)
- Superseded:
- Time: 2026-07-02T02:40Z
- Action: 读取保存的 evidence/*.html 文件 (此前 probe stdout body 为空被遗漏, codex review 发现)
- Source: probe.py via proxy
- Result: HR SaaS 主机默认页泄露完整系统信息 — schedule: v7.3.2023.0705/APP 1.7.13.6 (2023年7月), client/cloud: v7.3.2026.0612 (2026年6月); Azure Standard Edition Rent 多租户模式; ProgramItems 1918; RunTimeLogActions 含 LoginLog/FormLog/ViewLog/DownloadLog/DbCommandLog; DbCommandTimeout 60s; 隐藏字段含 __RequestVerificationToken/__UNIQUEGUID/__VIEWSTATE; 脚本含 ais.webform.js
- Caused by us: no (默认 Server Info 页面无鉴权)
- Alternative explanation: 伺服端資訊页面设计为公开(但不应公开版本/日志/配置)
- Certainty: 0.5 (确认信息泄露, 版本信息精准, 但非直接可利用漏洞)
- Replicated / Control: schedule/cloud/client 三个主机独立验证
- Artifacts: evidence/schedule-root.html, evidence/client-sysinfo.html, evidence/cloud-sysinfo.html
- Supports: F-004, F-005, F-006
- Refutes: 此前 F-004 "无表单/脚本" 分析 (client-default.aspx 实际含 10 隐藏字段 + 4 脚本)
- Unlocks: 版本差异 (schedule 2023 vs client 2026) 暗示 schedule 可能未更新; 了解 AIS WebForm 框架结构
- Next:

## E-014: HR SaaS DevExpress 页面分析修正 (GUID + 隐藏字段)

- Maturity: phenomenon
- Reportable: no
- Supersedes: E-004 (修正此前"无表单/脚本"的错误分析)
- Time: 2026-07-02T02:45Z
- Action: 重新分析保存的 evidence/*.html 文件 (codex review 发现遗漏)
- Source: probe.py via proxy + saved artifacts
- Result: client-default.aspx 含 10 个隐藏字段 (__RequestVerificationToken/__UNIQUEGUID/__ROOTPATH/__LOGINCOMPANYID/__VALUECHANGEID/__VIEWSTATE/__SCROLLPOSITION/__EVENTTARGET/__EVENTARGUMENT) + 4 个脚本 (WebResource.axd/language/jquery/ais.webform.js); ai-follow.html 含 ParentUniqueGUID `64f4e5c5-b362-4149-a130-a365c303013f` + 3 个 GUID 值; schedule-root.html 含 "伺服端資訊" 系统属性表; 所有页面为 ASP.NET Web Forms (非静态占位)
- Caused by us: no (此前的分析错误是因为 probe.py stdout JSON body 为空, 未读取保存的 .html 文件)
- Alternative explanation: 标准 ASP.NET Web Forms 页面结构
- Certainty: 0.5 (纠正了之前错误的分析, 但仍无直接可利用漏洞)
- Replicated / Control: 多个保存文件交叉验证
- Artifacts: evidence/client-default.html, evidence/ai-follow.html, evidence/schedule-root.html
- Supports: F-004, F-006, F-008 (修正了这些前沿的基础事实)
- Refutes: 此前 F-004 "无表单/脚本/隐藏字段" 的断言 (错误)
- Unlocks: __UNIQUEGUID/ParentUniqueGUID 参数可作为租户路由突破口; __LOGINCOMPANYID 可能用于租户枚举
- Next:

## E-015: Really Simple SSL v9.5.8 — CVE-2026-48970 未认证认证绕过

- Maturity: candidate
- Reportable: yes
- Superseded:
- Time: 2026-07-02T18:50Z
- Action: 识别 WordPress 插件版本 → 搜索 CVE → 下载 9.5.8 vs 9.5.10.1 源码对比
- Source: probe.py via proxy + WordPress SVN 源码分析
- Result: 目标运行 Really Simple SSL (Really Simple Security) v9.5.8, 受 CVE-2026-48970 (CVSS 8.1, CWE-288 认证绕过替代路径) 影响。该 CVE 2026-06-15 公布, 影响 ≤ 9.5.10 (修复于 9.5.10.1)。源码对比发现: class-rsssl-passkey-list-table.php 的 wp_ajax_remove_passkey handler 在 9.5.10.1 中被移除; security/wordpress/vulnerabilities.php 重构为 core/app/Features/Vulnerability/; RequestBody.php helper 删除; 新增 DoActionInterface.php。REST API (really-simple-security/v1) 在未认证状态下不注册; AJAX handlers 全部返回标准 WordPress -1。确切利用路径尚未确定 (攻击复杂度 HIGH, 安全站点被阻塞)
- Caused by us: no
- Alternative explanation: 插件正常安全更新; 实际可利用性取决于找到具体未授权端点
- Certainty: 0.3 (版本+CVE 确认, 但利用路径未验证 — 攻击复杂度 AC:H, 前置条件 2FA 未在目标上启用)
- Replicated / Control: 版本通过 readme.txt (Stable tag: 9.5.8) 确认; 源码通过 WordPress SVN 下载对比
- Artifacts: evidence/rsssl-readme.txt, evidence/rsssl-9.5.8-settings.php, evidence/rsssl-9.5.10.1-settings.php
- Supports: F-001 (WordPress 攻击面)
- Refutes:
- Unlocks: 若找到利用路径 → WordPress 管理员权限 → 完整站点控制
- Next: 持续监控 PoC 公开; 深入逆向 rsssl_do_action filter 链和 EndpointManager 权限回调
