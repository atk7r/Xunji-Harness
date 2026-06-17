---
id: ida-zerotrust-iam
product: IDA 零信任 / IAM 统一身份接入网关
vendor: 未定厂商（"IDA" 零信任 / SDP，环境感知准入）
aliases: [IDA, 零信任, IAM, SDP, 环境感知, iam/auth, trustAssess, startTunnel]
category: framework-management-endpoint
last_reviewed: 2026-06-12
maturity: seed
signatures: ["/iam/auth/", "trustassess", "getmachineiduuid", "idastrategyid"]
---

<!--
Grounding knowledge, not a weapon. 来源: <run> 实测(run-observation)。
厂商未定 → 不臆造 CVE。无 payload/步骤/PoC。
-->

## Recognition (identification only)

- Signature: 后端 API 前缀 `/iam/auth/`（`/iam/auth/login/*`、`/iam/auth/index/*`、
  `/iam/auth/noLogin/*`、`/iam/auth/qrcode/*`、`/iam/auth/dingApi/*`）。
- Signature: 前端 Vue 门户在 `/app/`（`LoginedShow` chunk）；客户端隧道逻辑
  `/startTunnel`、`/tunnelConnect`，连本地 agent `http://127.0.0.1:60001/getMachineIdUuid`。
- Signature: 零信任术语 `trustAssess`(信任评估)、"IDA环境感知"、`idaStrategyId`、`sdpOn`、
  `agentIdentifyConfig`；统一错误体 `{"code":<int>,"msg":..,"content":..}`(code 5002/5000 等)。
- Distinguishing notes: 多租户(按 host 解析租户)；认证流 `initial → prepare(instId) → auth →
  trustAssess(环境感知) → flowSuccess`。

## Weak-Point Anchors (variant-analysis input — NOT exploit steps)

- Anchor: 登录前 `/iam/auth/*` 接口未授权信息泄露 缺陷类
  - Affected: `login/initial`(返认证配置+口令策略)、`index/getAgentConfig`(返 agent/SDP/网络策略)
  - Mechanism: 登录前页面所需配置接口未鉴权且返回过多内部字段(ServiceImpl 类名/CAS 内网地址/
    口令策略/零信任策略)
  - Reference: 本仓 run-observation（某实战 E-011）
  - source: run-observation
- Anchor: `login/forgetPwd` 未授权密码修改端点 / 账号接管 缺陷类
  - Affected: `/iam/auth/login/forgetPwd`(字段 account/code/password/passwordTwo/mobile)
    + `/iam/auth/login/sendValidCode`(notifyCode=forget_code)
  - Mechanism: 未授权可达的“发码→改密”链; 危害取决于短信码逻辑(可否绕过/爆破/篡改/为他人账号指定手机)。
    无害测试(假账号)可排除“空码即改密”类平凡绕过, 但码逻辑健全性需真实测试账号判定
  - Reference: 本仓 run-observation（某实战 E-017/E-018）
  - source: run-observation
- Anchor: noLogin / 第三方 OAuth / QR 登录 面
  - Affected: `noLogin/getDingUserByCode`、`qrcode/getQrcode`+`qrcode/polling`、`dingApi/*`
  - Mechanism: 未授权命名空间; QR 登录劫持(qrId 绑定/可预测)、OAuth code 处理需逐接口核; 本部署钉钉多未配
  - Reference: 本仓 run-observation
  - source: driver-reasoning
- Anchor: 认证流环境感知(零信任)绕过 缺陷类
  - Affected: `prepare`(未授权下发 SESSION)、`trustAssess`(需 agent machineId)、`auth`、`flowSuccess`
  - Mechanism: 逐步门控；本仓实测三路(空会话打 flowSuccess/伪造 machineId/auth 探)均被正确门控(无绕过),
    但 prepare 预认证 SESSION 复用、instId 全枚举、nasIp/inIframe 语义仍是逻辑探测面
  - Reference: 本仓 run-observation（某实战 E-016）
  - source: run-observation

## Verification Principle (existence proof)

- Existence proof: `/iam/auth/` + `trustAssess`/"IDA环境感知" 即确认产品。未授权面用良性 GET 枚举
  (不触发 WAF)；**端点枚举须先 `fetch_assets.py` 抓全 SPA 的全部 chunk**(否则漏端点, 见 某实战 4/13 教训)。
- Hard stops: 信息泄露止于证明返回敏感字段(不批量取数)；forgetPwd 改密=完整性破坏(operator-gated, 不自动改)；
  sendValidCode 单发用假号(短信轰炸=flooding 硬禁)；QR 劫持需真人扫码(不自主)。

## False-Positive / Confounders

- 同 IP 多主机(cw/ots/quest/static/trust/wisdom…)从外部均落同一 `/app/` 默认页, 是同应用别名, 非独立面。
- `trustAssess` 返 "需开启终端" 是零信任正常拦截(会话≠访问), 不是可绕过信号。
- 端点清单若基于部分 chunk → "已枚举完"不成立(必 fetch_assets 核完整性)。

## References

- 本仓实测: runs/<run>/ 证据 E-011~E-018；报告 report_iam_unauth_disclosure.md /
  report_iam_forgetpwd_ato.md
