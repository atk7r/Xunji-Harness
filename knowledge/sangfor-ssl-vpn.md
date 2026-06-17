---
id: sangfor-ssl-vpn
product: Sangfor SSL VPN
vendor: 深信服 Sangfor
aliases: [深信服SSL VPN, EasyConnect, svpn, 深信服远程接入]
category: device
last_reviewed: 2026-06-12
maturity: seed
signatures: ["/por/login_auth.csp", "/por/login_psw.csp", "<twfid>", "svpntool"]
---

<!--
Grounding knowledge, not a weapon. Recognition + weak-point anchors (class +
mechanism + reference) + proof-only principle. No payloads / steps / PoC.
来源: <run> 实测指纹(run-observation) + 公开披露(external-cited)。
-->

## Recognition (identification only)

- Signature: 登录路径 `/por/login_psw.csp`（口令登录页）、`/por/login_cert.csp`、
  `/por/login_token.csp` —— `/por/*.csp` 路由族是深信服 SSL VPN 的强指纹。
- Signature: `GET /por/login_auth.csp` 返回 XML，含标签 `<TwfID>`（会话令牌）、
  `<RndImg>`（验证码开关）、`<Anonymous>`（匿名登录开关）、`<StartAuth>`。该 XML 形态
  为深信服唯一标识。
- Signature: 登录页内含版本串形如 `M7.xRy`（如 M7.1R1）与客户端 `svpntool`、以及一段
  RSA 公钥（`EncryptKey` 模数 + `EncryptExp` 指数 65537），口令登录用其加密。
- Distinguishing notes: 与其它国产 VPN（启明星辰天清汉马 appframe、华为/H3C）区分点是
  `/por/` + `.csp` + `login_auth.csp` 的 `<TwfID>` XML；仅凭 “VPN/用户登录” 标题不足以判定。

## Weak-Point Anchors (variant-analysis input — NOT exploit steps)

- Anchor: 互联网暴露的旧版本 SSL VPN 网关本身即高风险面
  - Affected: M7.x 等较老固件区间，直接暴露公网
  - Mechanism: VPN 网关是无需凭据即可触达的内网边界设备；一旦被攻破即获内网入口，
    历史固件存在多个已公开披露的未授权缺陷类
  - Reference: 深信服安全应急响应中心 https://sec.sangfor.com.cn/ ；CNCERT 2020 年
    深信服 SSL VPN 安全事件通报
  - source: external-cited
- Anchor: 未授权命令执行 / 系统文件读取 缺陷类
  - Affected: 受影响固件分支（具体版本以厂商公告为准）
  - Mechanism: 部分历史固件在未鉴权接口存在命令拼接或路径处理缺陷，可被无凭据触发
  - Reference: CNVD 检索“深信服 SSL VPN” https://www.cnvd.org.cn/ ；精确编号随固件分支，
    由 driver 对实机 build 核验后确定
  - source: driver-reasoning
- Anchor: 认证逻辑缺陷 / 越权访问 缺陷类
  - Affected: 受影响固件分支
  - Mechanism: 历史披露存在绕过或越权登录的认证逻辑问题；匿名登录开关（`<Anonymous>`）
    若被开启亦扩大未授权面
  - Reference: CNVD/CNNVD 深信服条目检索
  - source: external-cited

## Verification Principle (existence proof)

- Existence proof: `/por/login_auth.csp` 的 `<TwfID>` XML 指纹 + 登录页 `M7.xRy` 版本串
  即可确认“设备身份与版本暴露”。匿名/验证码开关读 `<Anonymous>`/`<RndImg>`。
- Hard stops（按证明边界 机密/可用/完整）：自动执行止于指纹与版本识别；**不**自动发 RCE、
  **不**自动登录、**不**自动读系统文件、**不**触动可用性。武器化利用属跨 web 层 operator-gated，
  author-and-handoff。

## False-Positive / Confounders

- 蜜罐 / 仿真 VPN 登录页可复刻 `/por/login_psw.csp` 外观；以 `login_auth.csp` 的 `<TwfID>`
  XML 与版本串交叉确认，避免被静态仿真页误导。
- 同主机不同端口可能是管理面（常被过滤/独立），不要把用户面版本直接当管理面版本。

## References

- https://sec.sangfor.com.cn/ （深信服 安全应急响应中心）
- https://www.cnvd.org.cn/ （检索“深信服 SSL VPN”）
- 本仓实测: runs/<run>/ 证据 E-010（某真实主机 = M7.1R1）
