---
id: zfsoft-jwgl
product: 正方教务管理系统 (ZFSoft jwglxt)
vendor: 正方软件 ZFSoft
aliases: [正方教务, jwglxt, 教学管理信息服务平台, 正方新版教务]
category: framework-management-endpoint
last_reviewed: 2026-06-12
maturity: seed
signatures: ["/jwglxt/", "login_slogin.html", "login_getpublickey.html", "教学管理信息服务平台"]
---

<!--
Grounding knowledge, not a weapon. 来源: <run> 实测(run-observation) +
公开披露(external-cited)。无 payload/步骤/PoC。
-->

## Recognition (identification only)

- Signature: 路径 `/jwglxt/`；首页常 meta-refresh 跳 `/jwglxt`，登录页
  `xtgl/login_slogin.html`，标题“教学管理信息服务平台”。
- Signature: 登录用 RSA，公钥接口 `xtgl/login_getPublicKey.html` 返回 `{"modulus","exponent"}`。
- Signature: 静态资源带 `?ver=<build>` 构建号（如 `jw-login.css?ver=29564678`），class 前缀
  `globalweb` / `jw-`；Cookie 含 `JSESSIONID` + `route`（集群路由）。
- Distinguishing notes: 与强智教务（路径 `/jsxsd/`）是常见混淆对；正方新版以 `/jwglxt/` +
  `login_slogin.html` + `login_getPublicKey.html` 区分。

## Weak-Point Anchors (variant-analysis input — NOT exploit steps)

- Anchor: SQL 注入 缺陷类
  - Affected: 多个历史 build 的特定接口（含部分未授权点，随版本而异）
  - Mechanism: 历史版本存在参数拼接进 SQL 的注入面；新 build 多有修复，需按 `?ver=` 对位核验
  - Reference: CNVD 检索“正方 教务” https://www.cnvd.org.cn/ ；具体编号随 build
  - source: external-cited
- Anchor: 未授权访问 / 越权 缺陷类
  - Affected: 部分接口在特定版本未强制鉴权或越权可读他人数据
  - Mechanism: 鉴权过滤覆盖不全 / 对象级权限校验缺失
  - Reference: CNVD/CNNVD 正方教务条目检索
  - source: external-cited
- Anchor: 弱口令 / 默认账号面
  - Affected: 学生/教师账号体系
  - Mechanism: 常见学号/工号即用户名、弱默认口令模式；属需凭据尝试的面，非未授权直打
  - Reference: 通用账号安全实践（driver 按授权与平台规则决定是否进行）
  - source: driver-reasoning

## Verification Principle (existence proof)

- Existence proof: `/jwglxt/` + `login_slogin.html` + `login_getPublicKey.html` 即确认产品与
  登录流；`?ver=` 给出 build，用于已知缺陷对位。数据接口未登录是否重定向回登录页，区分
  鉴权是否生效。
- Hard stops: 注入证明止于布尔/差异证据（不拖库）；越权证明止于“可达他人对象”而非批量取数；
  弱口令须遵守授权与平台无害化规则，自动执行不失控（防爆破锁定）。

## False-Positive / Confounders

- 前置 WAF（如安恒云）会对引号/关键字返回拦截页，**拦截页 ≠ DB 报错**，勿据此判定注入
  （见 [[waf-block-recognition]]）。
- `route`/`JSESSIONID` 双 Cookie 是正常集群会话保持，非漏洞信号。

## References

- https://www.cnvd.org.cn/ （检索“正方 教务 / jwglxt”）
- 本仓实测: runs/<run>/ 证据 E-001/E-002（某真实主机，build 29564678）
