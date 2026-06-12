---
id: shibboleth-idp
product: Shibboleth Identity Provider (IdP)
vendor: Shibboleth Consortium
aliases: [Shibboleth IdP, SAML IdP, 统一身份认证, SSO]
category: framework-management-endpoint
last_reviewed: 2026-06-12
maturity: seed
---

<!--
Grounding knowledge, not a weapon. 来源: <run> 实测(run-observation) +
公开披露(external-cited)。无 payload/步骤/PoC。
-->

## Recognition (identification only)

- Signature: 路径 `/idp/`，标题/页面 “Shibboleth IdP”；`/idp/css/placeholder.css` 等默认资源。
- Signature: `/idp/shibboleth` 返回 SAML 元数据（entityID、证书）；部分部署仍是未替换的
  “example metadata”（页头自带 “This is example metadata only …”）。
- Signature: `/idp/status` 在加固部署返回 403（已锁），未加固则可读运行状态。
- Distinguishing notes: 与其它 SAML IdP（SimpleSAMLphp、ADFS）区分点是 `/idp/` 路径族与
  `shibboleth` 元数据端点。

## Weak-Point Anchors (variant-analysis input — NOT exploit steps)

- Anchor: 旧版本认证/请求处理 缺陷类
  - Affected: 较老的 IdP / OpenSAML / 依赖库版本
  - Mechanism: 历史披露存在认证处理、XML 解析（XXE）、会话处理等缺陷类；以版本对位为准
  - Reference: Shibboleth 安全公告 https://shibboleth.net/community/advisories/
  - source: external-cited
- Anchor: 默认/示例元数据暴露（配置卫生，非直接漏洞）
  - Affected: `/idp/shibboleth` 仍为示例 metadata 的部署
  - Mechanism: 暴露 entityID/证书结构与“未完成生产配置”信号；本身不可直接利用，是运维卫生项
  - Reference: 本仓 run-observation；Shibboleth 部署文档（metadata 生成指引）
  - source: run-observation
- Anchor: 运行状态端点暴露
  - Affected: `/idp/status` 未限制访问的部署
  - Mechanism: 泄露版本/运行信息，利于版本对位与情报收集
  - Reference: Shibboleth IdP 文档（status 端点访问控制）
  - source: driver-reasoning

## Verification Principle (existence proof)

- Existence proof: `/idp/` + `/idp/shibboleth` 元数据即确认产品；`/idp/status` 403 vs 可读区分
  加固程度；示例 metadata 的页头文案确认“默认未替换”。
- Hard stops: 止于指纹/版本/配置卫生识别；不对解析层发破坏性 payload，不触动认证服务可用性。

## False-Positive / Confounders

- **示例 metadata 暴露本身不是漏洞**，只是配置卫生信号——勿拔高为高危（本次教训，
  runs/<run> 证据 E-004 / FP-003）。
- `/idp/status` 返回 403 是“已加固”的正向信号，不是缺陷。

## References

- https://shibboleth.net/community/advisories/ （官方安全公告）
- 本仓实测: runs/<run>/ 证据 E-004（某真实主机）
