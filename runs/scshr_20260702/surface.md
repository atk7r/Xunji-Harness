# Surface

## Assets

- **www.scshr.com** (WordPress + nginx/1.14.1): 官网 — 用户枚举 7人, REST API 开放, 插件 wp-file-manager 8.0.4 / Yoast SEO / ACF / Really Simple SSL, 内部IP泄露 192.168.8.221:8087, xmlrpc 禁用, 注册禁用
- **api.scshr.com** (IIS/10.0 + ASP.NET): API 入口 — Sandcastle .NET 类库文档泄露 (AIS_Define 框架), 无 HTTP API 端点发现, swagger 未找到
- **ai.scshr.com** (ASP.NET + DevExpress DXR.axd + Azure ARR): HR SaaS AI 模块 — GUID 多租户路由, JSON-RPC /api/ type-lookup, 无有效 GUID 返回错误页
- **app.scshr.com** (ASP.NET + DevExpress DXR.axd + Azure ARR): HR SaaS 主应用 — 同 ai 模式, GUID 路由
- **client.scshr.com** (ASP.NET + CDN): 客户端门户 — 200 "伺服端資訊", login.aspx 652B, default.aspx 4238B
- **cloud.scshr.com** (jQuery + CDN): 云端模块 — 200 "伺服端資訊", /api/ JSON-RPC type-lookup (同 ai)
- **schedule.scshr.com** (ASP.NET + jQuery + CDN): 排班模块 — 200 "伺服端資訊", /api/ JSON-RPC type-lookup (同 ai)
- **services.scshr.com** (ASP.NET + Azure ARR): 服务中心 — 302 → GUID 错误页 (同 ai/app)
- **tscs.scshr.com** (nginx/1.14.1 + ASP.NET + jQuery): 区域实例 — 200 "SCSHR", robots.txt 26B
- **wpgbeta.scshr.com** (nginx/1.14.1 + ASP.NET + jQuery): Beta 环境 — 200 "SCSHR", Trace.axd 403, 路径扫描全部 404
- **kh.scshr.com** (IIS/10.0): 裸 IIS — 仅 iisstart.htm, 无应用 (CLOSED)
- **payment.scshr.com** (IIS/10.0 + CDN): 裸 IIS — 同 kh (CLOSED)
- **122.117.135.182** (IIS/10.0): 裸 IIS 源站 — TLS SAN *.scshr.com (CLOSED)
- **20.198.176.62** (IIS/10.0 + CDN): 裸 IIS CDN 节点 (CLOSED)
- **yk50lan.scshr.com:12443** (FortiOS): SSL VPN — Azure AD SAML SSO, 租户ID fd4fe7e3-9e23-455a-8a67-1eca0be0465a, CVE-2022-40684 已修补
- **tp.scshr.com** (nginx): 403 Forbidden (deferred)
- **scs-ad.scshr.com** (nginx): 403 Forbidden — 疑似 AD 端点 (deferred)

## Entry Points

- **WordPress REST API** (www.scshr.com/wp-json/): 完全开放 — /wp/v2/users (7用户), /wp/v2/posts (847KB), /wp/v2/pages (1MB), /wp/v2/media
- **WordPress wp-login.php** (www.scshr.com/wp-login.php): 登录表单, 74 次弱口令尝试无突破, xmlrpc 禁用
- **JSON-RPC /api/** (ai/cloud/schedule): .NET type-lookup 接口, 响应 ObjectType/ProgID/Action/Format/Value 结构
- **DevExpress DXR.axd** (ai/app): ASP.NET 组件处理器, 304 存在但无直接利用
- **Sandcastle 文档** (api.scshr.com/api/help/): .NET 类库文档 (AIS_Define), 888 页
- **FortiOS SSL VPN** (yk50lan.scshr.com:12443): SAML SSO → Azure AD

## Trust Boundaries

- CDN (Azure) → nginx → ASP.NET/IIS 后端 (HR SaaS)
- nginx → 内网 WordPress (192.168.8.221:8087)
- FortiGate → Azure AD SAML (tenant: fd4fe7e3-9e23-455a-8a67-1eca0be0465a)
- IIS 裸机 (122.117.135.182, 20.198.176.62, kh, payment) 为反代源站, 无独立应用

## Interesting Signals

- Signal: 内部 IP 192.168.8.221:8087 通过 WordPress 用户 profile 泄露
  - Source: E-002 /wp-json/wp/v2/users/1
  - Why it matters: 揭示内网架构, 若发现 SSRF 可攻击内网
  - Normal explanations: 用户 profile url 字段, WordPress 开发时配置
  - Follow-up: 搜索 SSRF 入口; 监控其他用户 url 字段

- Signal: Azure AD 租户 ID fd4fe7e3-9e23-455a-8a67-1eca0be0465a 通过 FortiGate SAML 重定向泄露
  - Source: E-007 yk50lan:12443/remote/login
  - Why it matters: 可用于 Azure AD 用户枚举/密码喷洒/钓鱼
  - Normal explanations: SAML SSO 重定向必然暴露租户 ID
  - Follow-up: Azure AD 侦察 (需评估 生产租户 风险)
