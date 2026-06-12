---
id: wisedu-ecampus
product: 金智教育 数字校园（统一认证 authserver / 网上办事大厅 ehall）
vendor: 江苏金智教育 Wisedu
aliases: [金智教育, wisedu, ehall, authserver, 网上办事大厅, 今日校园, 统一身份认证]
category: framework-management-endpoint
last_reviewed: 2026-06-12
maturity: seed
---

<!--
Grounding knowledge, not a weapon. 来源: <run> 实测(run-observation) +
公开披露(external-cited)。无 payload/步骤/PoC。
-->

## Recognition (identification only)

- Signature: 响应头 `Server: wisedu`（金智应用服务器的强指纹）。
- Signature: 统一认证在 `/authserver/`：`/authserver/login` 登录页（class `root-main`），
  静态资源在 `/authserver/<校定制Theme>/static/...?v=<日期版本>`（如 `某实战Themea v=20240524`），
  含 `encrypt.js`(口令加密) / `login.js` / `fido.js` / `schoolCombinedLogin.js`。
- Signature: 办事大厅 ehall 的服务应用命名空间 `/qljfwapp/<app>/sys/...`、`/publicapp/...`；
  `/authserver/checkNeedCaptcha.htl?username=` 返 `{"isNeed":..}`、`/authserver/getCaptcha.htl` 图片码。
- Distinguishing notes: 与其它 CAS（apereo 原生、其它 IdP）区分点是 `Server: wisedu` +
  `/authserver/<Theme>/static/` 定制主题 + ehall 的 `qljfwapp`/`publicapp` 服务应用结构。

## Weak-Point Anchors (variant-analysis input — NOT exploit steps)

- Anchor: ehall 服务应用未授权 SQLi / 越权 缺陷类
  - Affected: 部分 `/qljfwapp/*/sys/*` 服务接口在特定版本未强制鉴权或对象级越权
  - Mechanism: 服务应用模块多, 鉴权过滤覆盖不全; 历史披露集中在 `/sys/...Controller/...` 类接口
  - Reference: CNVD 检索“金智教育 / ehall” https://www.cnvd.org.cn/
  - source: external-cited
- Anchor: authserver(CAS) 认证逻辑 / 任意用户登录 缺陷类
  - Affected: 较老 authserver 版本
  - Mechanism: 口令 RSA 加密 + CAS ticket 流; 历史有加密绕过/任意登录类
  - Reference: CNVD/CNNVD 金智 authserver 条目
  - source: external-cited
- Anchor: 服务应用枚举依赖授权后的应用清单
  - Affected: 未登录时 `/qljfwapp/sys/`→CAS 登录, 应用名不可直接列举
  - Mechanism: 未授权面有限, 多数服务需登录态; 测越权/注入通常需测试账号或精确 app/module 名
  - Reference: 本仓 run-observation（某实战 ehall）
  - source: run-observation

## Verification Principle (existence proof)

- Existence proof: `Server: wisedu` + `/authserver/login` + ehall `/qljfwapp/` 即确认产品。
  版本取 `/authserver/<Theme>/static/...?v=` 时间戳, 用于已知缺陷对位。
- Hard stops: 未授权面止于指纹/版本; 服务应用越权/注入证明需账号或精确 app 名,
  proof 级布尔差异不拖库; checkNeedCaptcha 不做账号枚举式高频请求。

## False-Positive / Confounders

- `Server: wisedu` 后多主机为 CAS 登录页（jxpg/jsfzzx/kyc 等）——是同一登录入口, 非独立应用,
  勿当多个面 lump 计数。
- `checkNeedCaptcha` 对存在/不存在用户可能返回相同 `isNeed`（无用户枚举）, 勿据此判枚举漏洞。

## References

- https://www.cnvd.org.cn/ （检索“金智教育 / ehall / authserver”）
- 本仓实测: runs/<run>/ 证据 E-002/E-004/E-008（某真实主机 authserver/ehall）
