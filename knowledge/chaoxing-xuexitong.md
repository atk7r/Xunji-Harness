---
id: chaoxing-xuexitong
product: 超星学习通 / 泛雅 (Chaoxing)
vendor: 超星 Chaoxing
aliases: [超星, 学习通, 泛雅, chaoxing, fanya, AI平台]
category: framework-management-endpoint
last_reviewed: 2026-06-12
maturity: seed
---

<!--
Grounding knowledge, not a weapon. 来源: <run> 实测(run-observation) +
公开披露(external-cited)。无 payload/步骤/PoC。
-->

## Recognition (identification only)

- Signature: 登录跳转到第三方统一认证 `passport2.chaoxing.com`（refer 回业务域）。
- Signature: 本域后端 REST 接口前缀 `/v1/...`（如 `/v1/user/...`、`/v1/manage/...`），未登录
  常返回 HTTP 200 但 body `{"msg":"未登录","statusCode":-1}`。
- Signature: 前端 Vue SPA；遥测打到 `sentry-stats.chaoxing.com`；验证码 `captcha.chaoxing.com`。
- Distinguishing notes: 业务子域（学校 AI 平台/学习通）是部署点，统一认证 passport 在
  `chaoxing.com` 厂商域；二者范围归属不同。

## Weak-Point Anchors (variant-analysis input — NOT exploit steps)

- Anchor: 组件级已知缺陷类（越权 / SSRF / 信息泄露 历史披露）
  - Affected: 受影响的超星组件版本
  - Mechanism: 大型多租户平台历史上有越权取数、服务端请求伪造等公开披露类；属厂商代码面，
    具体随版本
  - Reference: CNVD 检索“超星 / 学习通” https://www.cnvd.org.cn/
  - source: external-cited
- Anchor: API 鉴权边界（本次实测为应用层强制）
  - Affected: `/v1/manage/*` 等管理命名空间
  - Mechanism: 接口返回 HTTP 200 但应用层校验登录态（`{"msg":"未登录"}`）；勿把 200 误判为
    未授权可访问 —— 须看 body 语义
  - Reference: 本仓 run-observation
  - source: run-observation

## Verification Principle (existence proof)

- Existence proof: passport.chaoxing.com 跳转 + `/v1/` API 形态即确认产品。鉴权判定**以 body
  语义为准**（200 + “未登录” = 已鉴权），不以 HTTP 状态码为准。
- Hard stops: 越权/信息泄露证明止于“可达本不该可达的对象/数据项存在性”，不批量取数；登录在
  厂商 passport 域，注意范围边界。

## False-Positive / Confounders

- **HTTP 200 ≠ 未授权访问**：超星接口惯于 200 包裹业务错误码，未登录请求也回 200。这是本次
  一个被证伪的方向（见 runs/<run> 证据 E-003）。
- passport 在 `chaoxing.com` 域，可能超出对单一学校的授权范围。

## References

- https://www.cnvd.org.cn/ （检索“超星 / 学习通”）
- 本仓实测: runs/<run>/ 证据 E-003（某真实主机）
