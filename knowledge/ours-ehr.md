---
id: ours-ehr
product: 致远薪事力 数智化人力云平台 (OURS eHR)
vendor: 北京致远互联软件股份有限公司 (科创板 688369) / 致远薪事力(苏州)云科技有限公司
aliases: [ours, ours-ehr, 薪事力, 致远薪事力, x-dhr, DHR人力云]
category: framework-management-endpoint
last_reviewed: 2026-06-12
maturity: verified
signatures: ["/res_common/ours/", "ours_user_token", "ours_pc.min.js", "薪事力"]
---

<!--
Grounding knowledge, not a weapon. Recognition + weakness class + references +
proof-only verification principle only. No payloads/steps/slider-solver code —
the driver derives the specific proof check at runtime (tools/probe.py,
tools/render.py). The reproduction PoC and exploit chain live in the run
directory (runs/<run>/), never here.
-->

## Recognition (identification only)

- Signature: 请求派发走 `*.do?method=*` 形态；登录页 `/login.do`，首页 302 跳
  `/login.do`。
- Signature: 静态资源前缀 `/res_common/ours/`、核心 bundle
  `/res_common/ours_pc.min.js`，验证码组件 `/res_common/ours/system/ours-verify.js`。
- Signature: 业务响应 JSON 包裹 `{"errcode":...,"msg":...,"success":...,"async":...,"waitSecond":...}`。
- Signature: 会话 Cookie 家族 `ours_user_token` + `_csrf`（部分实例 `DHRSESSIONID`）。
- Signature: 内联 `ours_context` / `ours_contextPath` 全局对象；CSS
  `ehrIconFont.css`、`/ehr/common/...` 模块路径。
- Signature: 官网/品牌 meta `薪事力,致远互联薪事力,致远薪事力`（厂商归属锚点，
  vendor=致远互联 688369）。
- Distinguishing notes: 版本号见资源 `?V=` 查询串（如 `?V=7.11.01.1172`、
  `?V=8.04.01.1360`、`?V=4.03.01.94`）——跨 v4~v8 多版本同栈。与其他 `.do` 派发
  的 OA（如致远 A8/泛微）区分点是 `/res_common/ours/` 前缀 + `ours_user_token`。

## Weak-Point Anchors (variant-analysis input — NOT exploit steps)

- Anchor: 文件上传接口未授权可达（authentication bypass on upload handler）
  - Affected: OURS eHR v4.03 ~ v8.04 同栈（run 实测跨版本一致）；框架级缺陷，
    非单点配置。
  - Mechanism: 上传 handler 在业务逻辑前缺少会话/权限拦截层，匿名请求直达业务
    代码并返回业务级参数校验响应（而非登录重定向/401）。同框架其他接口对匿名
    请求正确 302 跳登录，证明鉴权机制本身正常、仅该接口遗漏。唯一前置门槛是
    客户端滑块验证码，而验证码挑战接口同样未授权、无频率限制、解密密钥明文
    随挑战下发——不构成有效鉴权。
  - Reference: CWE-434 (Unrestricted Upload of File with Dangerous Type) +
    CWE-306 (Missing Authentication for Critical Function)。
  - source: run-observation (<run>：11/12 互联网实例确认上传落地可读；
    100 抽样 Part-A 命中 56%)
- Anchor: 滑块验证码不构成认证边界（client-side challenge, server trusts
  trajectory only）
  - Affected: `ours-verify.js` 滑块组件（同栈通用）。
  - Mechanism: 挑战生成接口匿名可取；DES 解密密钥（短密钥）明文包含在挑战
    响应中；服务端仅校验拖拽轨迹数据，可被真实浏览器环境复现。把验证码当作
    上传接口的鉴权替代是设计缺陷。
  - Reference: CWE-602 (Client-Side Enforcement of Server-Side Security)。
  - source: run-observation (<run>)
- Anchor: 上传文件访问签名为会话绑定（影响边界，非额外漏洞）
  - Affected: 返回的 `preview4Pub`/`download4Pub` 带 `ours_as` 签名参数。
  - Mechanism: 签名与上传时会话绑定，外部直接访问需携带同会话 Cookie。这界定
    了"未授权写入"成立、但"任意公开读取"受限——不改变上传漏洞本身的成立。
  - Reference: 影响边界说明（CWE-434 仍成立）。
  - source: run-observation (<run>)

## Verification Principle (existence proof)

- Existence proof（只读层）：匿名 POST 上传 handler 返回业务级参数校验响应
  （非 302/401），且匿名 GET 验证码挑战接口返回挑战参数——两者并存即"鉴权
  缺失"存在性证明。对照组（其他业务接口匿名 302 跳登录）用于排除"整体免鉴权"
  误判。
- Existence proof（落地层，需平台/操作者授权）：以真实浏览器环境完成验证码后
  上传**无害纯文本**（随机命名、无可执行内容），服务端返回文件 id/URL 即证明
  未授权写入成立。测后登记并清理（guard UploadRegistry / 不留残留）。
- Hard stops: 证明未授权写入即停。**不**上传可解析脚本/webshell、不驻留任何
  控制性代码、不取他人数据、不破坏。落地证明仅限无害文件且走清理闸——超出
  即触硬边界。

## False-Positive / Confounders

- 上传 handler 返回 `参数缺失: verifyCode` 或 Spring 的
  `RequestFacade cannot be cast to ... MultipartRequest`（不同版本两种形态）均
  属"已穿透鉴权到业务层"——是阳性信号，非错误页。
- 仅 Part-A 通过（A1+A2）只是"疑似"，不可作为确认；落地上传成功 + 内容可读
  才达 `certainty >= 0.8`。run 中 90% 的 Part-A 阳性在 Part-B 实测可上传。
- 厂商营销官网（如 `www.x-dhr.com`）可能 A2 通过但 A1 被拦——是站点而非产品
  部署实例，不计入受影响实例。
- HTTPS 实例若证书 CN 与 IP 不符（共享托管），只读探测需忽略证书校验，否则
  会被误判为不可达（run 中曾因此漏报 3 个 HTTPS 目标）。

## References

- CWE-434: Unrestricted Upload of File with Dangerous Type.
- CWE-306: Missing Authentication for Critical Function.
- CWE-602: Client-Side Enforcement of Server-Side Security.
- 厂商：北京致远互联软件股份有限公司（科创板 688369），产品官网 x-dhr.com。
- Per-target: 提交前以 ICP/网络空间测绘核对涉事单位归属；通用型提交需 ≥3 个
  互联网实例佐证（CNVD 通用漏洞要求）。
- 本工作区复现资料：`runs/<run>/`（PoC、证据、批量结果——不入知识库）。
