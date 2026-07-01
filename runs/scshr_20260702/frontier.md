# Frontier

> SharedBarrier groups: GUID-routing = [F-003~F-010] | budget exhausted: 4 methods | all downgraded Type B
>
> 消费 Guanlan recon 2026-06-14 | 14 confirmed reachable | Proxy: http://127.0.0.1:7892 | **FINAL — operator 收工** | Agent Board 强制门已接入

## Open Fronts

### F-001: www.scshr.com — WordPress 官网

- Front: WordPress CMS 漏洞 (plugins / themes / wp-json / xmlrpc / wp-login / 用户枚举)
- Why it matters: 唯一 PHP 栈 + WordPress (最大攻击面)
- Current depth: moderate (完整 wp-json 测绘 + 插件版本识别 + 74 弱口令尝试)
- Status: open
- Barrier class: auth-layer (wp-login 未突破, xmlrpc 禁用, 注册禁用)
- Failure budget: same-barrier=74 (弱口令尝试) / same-bypass=0 / same-tech=1 (www.scshr.com wordpress)
- Best current evidence: E-001 用户枚举, E-002 内部IP泄露, E-006 插件版本, E-009 REST API 开放, **E-015 RSSSL CVE-2026-48970 (CVSS 8.1 未认证绕过, v9.5.8 受影响)**
- Next autonomous move: 深入逆向 CVE-2026-48970 利用路径; 下载 RSSSL 9.5.8 全部源码搜索未授权入口点
- Stop condition: 发现可确认漏洞 或 穷举所有非破坏性向量
- Linked hypotheses: H-001

### F-002: api.scshr.com — API 接口

- Front: API 鉴权/接口文档暴露 / .NET 类库文档泄露
- Why it matters: recon 标记为 API 入口, 但实际 HTTP API 端点未发现; Sandcastle 文档泄露内部框架
- Current depth: moderate
- Status: open
- Barrier class: app-layer (HTTP API 端点未公开, 仅暴露类库文档)
- Failure budget: same-barrier=0 / same-bypass=0 / same-tech=0
- Best current evidence: E-008 .NET 类库文档泄露 (AIS_Define)
- Next autonomous move: 分析 AIS_Define 类结构; 尝试 WebAPI 路径发现
- Stop condition: 确认无可利用 HTTP 端点 或 发现可利用接口
- Linked hypotheses: H-002

### F-003: wpgbeta.scshr.com — Beta 环境 (GUID 门控)

- Front: nginx+ASP.NET placeholder, 200 仅 71 字节空白页
- Why it matters: 原以为 Beta 环境, 实际为空占位 — 根路径 71B, default.aspx/login.aspx 全部 404, 无可攻击面
- Current depth: moderate (ASP.NET 全路径扫描 + 登录页搜索全部 404)
- Status: blocked_type_a (需有效 GUID 才能访问真实应用, 同 F-008~F-010)
- Barrier class: routing-layer (GUID-based tenant routing)
- Failure budget: same-barrier=10+ / same-bypass=0 / same-tech=1
- Best current evidence: 根 71B, 所有路径 404, 无表单/脚本
- Next autonomous move: 同 F-008 — 需外部 GUID 来源
- Stop condition: 获得有效 GUID 或确认无可攻击面
- Linked hypotheses: H-006 (refuted — 非真实 Beta 环境)

### F-004: client.scshr.com — 客户端门户 (ASP.NET Web Forms)

- Front: ASP.NET Web Forms 应用, 200 "伺服端資訊" 含完整系统属性表
- Why it matters: 含 __UNIQUEGUID/ParentUniqueGUID 路由机制, __LOGINCOMPANYID 空字段, ais.webform.js v7.3.2026.0612; 10 隐藏字段 + 4 脚本 + __doPostBack
- Current depth: moderate (完整页面提取 + GUID 测试 + 隐藏字段分析)
- Status: blocked_type_a (无有效租户 GUID 无法接触登录/业务逻辑)
- Barrier class: routing-layer (GUID-based tenant routing) + app-layer (无认证下的 webform 占位)
- Failure budget: same-barrier=5 / same-bypass=2 / same-tech=2
- Best current evidence: E-013 (系统信息泄露), E-014 (Web Forms 结构)
- Next autonomous move: __LOGINCOMPANYID 枚举; GUID 跨主机复用测试
- Stop condition: 获取有效 GUID 或确认该上下文无法突破
- Linked hypotheses: H-004 (修订: 有认证面但需 GUID)

### F-005: cloud.scshr.com — 云端模块 (GUID 门控)

- Front: jQuery 轻量页, 200 "伺服端資訊", /api/ JSON-RPC
- Why it matters: /api/ 端点可交互 (POST 200), 但 type-lookup 非反序列化; 无 JS 资源/API 端点泄露
- Current depth: moderate
- Status: blocked_type_a
- Barrier class: routing-layer (GUID) + app-layer (API type-lookup)
- Failure budget: same-barrier=5 / same-bypass=0 / same-tech=1
- Best current evidence: E-003 JSON-RPC API
- Next autonomous move: 需 GUID
- Stop condition: 同
- Linked hypotheses: H-005

### F-006: schedule.scshr.com — 排班模块 (GUID 门控)

- Front: ASP.NET, /api/ JSON-RPC 端点 (GET+POST 均可)
- Why it matters: API 端点可交互, 同 cloud/ai 的 type-lookup 模式
- Current depth: moderate
- Status: blocked_type_a
- Barrier class: routing-layer (GUID)
- Failure budget: same-barrier=3 / same-bypass=0 / same-tech=1
- Best current evidence: E-003
- Next autonomous move: 需 GUID
- Stop condition: 同
- Linked hypotheses: H-003

### F-007: tscs.scshr.com — 区域实例 (GUID 门控)

- Front: nginx+ASP.NET, 200 "SCSHR", 根仅 71B
- Why it matters: 根几乎空白 (71B), robots.txt 26B, 所有路径 404; 最轻量的占位
- Current depth: moderate
- Status: blocked_type_a
- Barrier class: routing-layer (GUID)
- Failure budget: same-barrier=3 / same-bypass=0 / same-tech=1
- Best current evidence: 71B 空白根页
- Next autonomous move: 需 GUID
- Stop condition: 同
- Linked hypotheses: H-003

### F-008: ai.scshr.com — AI HR 模块 (GUID 门控)

- Front: DevExpress ASP.NET, 302→Error.aspx?ParentUniqueGUID, DXR.axd 存在, /api/ JSON-RPC
- Why it matters: /api/ 端点 POST 200 返回 JSON; 已深度测试 type-lookup/反序列化 — 非可 exploitable 的 .NET 反序列化, 仅为 enum 查找
- Current depth: moderate (完整路径扫描 + API fuzzing + GUID 枚举 + type fuzzing)
- Status: blocked_type_a
- Barrier class: routing-layer (GUID-based tenant routing)
- Failure budget: same-barrier=20+ / same-bypass=3 (GUID 模式猜测) / same-tech=3 (ai/app/services)
- Best current evidence: E-003 (API), E-004 (DevExpress GUID)
- Next autonomous move: 搜索外部 GUID 泄露源 (Google dork / 文档 / 客户端推荐) — Type A 问题, 当前上下文无突破
- Stop condition: 获取有效 GUID 或确认当前上下文无法突破 (已达到)
- Linked hypotheses: H-003

### F-009: app.scshr.com — 主应用 (GUID 门控)

- Front: 同 F-008, DevExpress ASP.NET, 302→Error.aspx?ParentUniqueGUID
- Why it matters: 核心租户应用, 同 ai 模式, 但首个 GUID 为 5cdbef18 (不同于 ai 的 062b80e7)
- Current depth: moderate
- Status: blocked_type_a
- Barrier class: routing-layer (GUID)
- Failure budget: 同 F-008 (共享)
- Best current evidence: E-004
- Next autonomous move: 同 F-008
- Stop condition: 同 F-008
- Linked hypotheses: H-003

### F-010: services.scshr.com — 服务中心 (GUID 门控)

- Front: ASP.NET, 302→GUID 错误页, 无 /api/ 端点
- Why it matters: 302 模式同 ai/app, 但更轻量 (2949B)
- Current depth: moderate
- Status: blocked_type_a
- Barrier class: routing-layer (GUID)
- Failure budget: 同 F-008
- Best current evidence: E-004
- Next autonomous move: 同 F-008
- Stop condition: 同 F-008
- Linked hypotheses: H-003

## Deferred Fronts

### F-101: tp.scshr.com — 台北区域 (403)
- Front: 403 Forbidden "禁止: 拒絕存取", nginx
- Deferred reason: 403 ACL, 需 IP 白名单绕过或特殊路径
- Residual risk: 内部管理面板被 ACL 保护

### F-102: scs-ad.scshr.com — AD 认证 (403)
- Front: 403, 疑似 Active Directory 端点
- Deferred reason: 403; 需更多上下文
- Residual risk: AD 端点可能泄露内部域信息

### F-103: yk50lan.scshr.com — FortiOS SSL VPN (port 12443)
- Front: Fortinet SSL VPN, 200, port 12443
- Deferred reason: FortiOS exploit 需专门开发; 先完成 web 面
- Residual risk: FortiOS 已知 CVE 池

### F-104: self-learning.ddns.net — 疑似旁站 (共享 TLS)
- Front: DDNS, 200 IIS, TLS SAN *.scshr.com
- Deferred reason: 第三方 DDNS, 归属不明确; 共享证书 = 可能是公司资产
- Residual risk: 被遗忘的自助平台, 弱安全

### F-105: elearning.scshr.com — 私网 (192.168.8.200)
- Front: 200 nginx, 解析到私网
- Deferred reason: 外部不可达; 内网资产
- Residual risk: 内网学习平台, 外部无法验证

## Closed Fronts

### F-011: kh.scshr.com — 高雄区域 (IIS 裸机)
- Front: IIS Windows 直接暴露 → 确认仅 iisstart.htm, 无应用部署
- Current depth: moderate
- Why closed: 完整路径扫描确认无 web 应用; 裸 IIS 反代源站, 攻击面为零
- Vectors tried: /api/, /login.aspx, /default.aspx, /owa/, /exchange/, /ecp/, /Autodiscover/, /Microsoft-Server-ActiveSync, 敏感文件扫描
- Artifacts verified: evidence/kh_scshr_com-root.html (iisstart.htm 696B), evidence/122_117_135_182-root.html (iisstart.htm 696B, SAN *.scshr.com)
- Evidence: E-005
- Type A/B reason: Type B — 无应用, 继续攻击不会产生价值
- Residual risk: 低 (未来可能部署新应用)

### F-012: payment.scshr.com — 支付模块 (IIS 裸机)
- Front: IIS Windows Server → 同 F-011, 裸 IIS
- Current depth: moderate
- Why closed: 同 F-011, 仅 iisstart.htm
- Vectors tried: 同 F-011 路径扫描
- Artifacts verified: evidence/payment_scshr_com-root.html (iisstart.htm 703B, CDN)
- Evidence: E-005
- Type A/B reason: Type B
- Residual risk: 低

### F-013: 122.117.135.182 — Core IP (IIS 源站)
- Front: 直接 IP IIS → 裸 IIS 源站, TLS SAN *.scshr.com
- Current depth: moderate
- Why closed: 同 F-011, 无应用; CDN 源站不存在独立漏洞面
- Vectors tried: 同 F-011 路径扫描
- Artifacts verified: evidence/122_117_135_182-root.html (iisstart.htm 696B, TLS SAN *.scshr.com)
- Evidence: E-005
- Type A/B reason: Type B
- Residual risk: 低 (未来可能变更)

### F-014: 20.198.176.62 — Core IP (IIS+CDN)
- Front: CDN 边缘节点 → 裸 IIS, 同 F-013
- Current depth: moderate
- Why closed: 同 F-011, 无应用
- Vectors tried: 同 F-011 路径扫描
- Artifacts verified: evidence/20_198_176_62-root.html (iisstart.htm 703B, CDN)
- Evidence: E-005
- Type A/B reason: Type B
- Residual risk: 低
