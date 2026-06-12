---
id: waf-block-recognition
product: WAF 拦截行为识别与假阳性混淆
vendor: 安恒 / 通用 WAF
aliases: [WAF, 安恒云WAF, 网站防火墙, 拦截页识别, false-positive]
category: confounder
last_reviewed: 2026-06-12
maturity: seed
---

<!--
Grounding knowledge, not a weapon. 这是“识别 + 混淆”条目: 帮助把 WAF 拦截与真实漏洞
区分开, 不是绕过手册。来源: <run> 实测(run-observation)。无 payload/步骤/PoC。
-->

## Recognition (identification only)

- Signature: 注入特殊字符（如引号）触发**固定的小体积拦截响应**（如 302 跳一个固定拦截页，
  或固定 403 页），与正常业务页大小/哈希迥异且稳定。
- Signature: 含 SQL 关键字或重言式特征的请求触发拦截页或**直接连接重置（RST/超时）**。
- Signature: 拦截页 body 常**回显被拦的 payload/URL**（故不同 payload 的拦截页哈希可不同，
  但都是同一拦截模板）。
- Distinguishing notes: 同一套 WAF 可能护着多个同机构站点——多个不同主机出现**字节一致的同一
  拦截页**，是“共用一套 WAF”的强信号。
- Signature(某实战 新增): **`Server` 响应头被掩码**（替换成一串星号 `**********` 之类），是网关/
  WAF 抹去后端指纹的标志；常与“同机构多主机共用”叠加出现。
- Signature(某实战 新增): **激进型——首个恶意特征请求即封源 IP**：良性请求 200 通过，但**第一个**
  带关键字/引号/扫描器特征路径（如 `/_vti_bin/...`）的请求一发，**之后该源 IP 的所有请求被连接
  拒绝(10061)/丢包**。良性 vs 恶意的对照能确认这是 WAF/IPS 按【请求特征】封，而非端口真关。

## Weak-Point Anchors (variant-analysis input — NOT exploit steps)

- Anchor: WAF 检测覆盖盲区（按请求方法/位置）缺陷类
  - Affected: 仅对部分请求面挂载检测的 WAF 部署（如只查 GET query 不查 POST body，或反之）
  - Mechanism: 检测策略未覆盖全部输入通道时，同一参数换一个未被检测的通道即可绕过 WAF；
    这是变体分析输入——是否“可利用”仍取决于后端本身是否存在漏洞
  - Reference: OWASP《Web Application Firewall Evasion》通用原理；本仓 run-observation
  - source: run-observation
- Anchor: 字符级编码归一化差异 缺陷类
  - Affected: WAF 与后端对编码（如 overlong UTF-8 / 多字节 / 二次编码）解码不一致的部署
  - Mechanism: WAF 与应用对同一字节序列解码结果不同，可能造成漏检或误拦；需对位实测，
    不可假设“绕过 WAF = 到达漏洞”
  - Reference: OWASP 编码归一化议题；本仓 run-observation
  - source: driver-reasoning

## Verification Principle (existence proof)

- Existence proof（识别 WAF，而非漏洞）：把特殊字符放进**任意参数/位置**都触发同一拦截响应，
  即证明该响应来自 WAF（全局字符拦截），而非应用/DB。
- **关键混淆纪律**：WAF 拦截响应（302/403/RST/固定页）**不是** DB 报错、**不是**漏洞证据。
  绕过 WAF 把字符送达应用后，仍须用受控布尔/差异**多次采样**确认后端真有漏洞——绕过 WAF ≠
  漏洞存在。
- Hard stops: 仅做识别与去噪；不把去噪手段升级为对生产的破坏性测试。

## False-Positive / Confounders

- 本条目本身就是为消解假阳性而设：本次 lib `tsg_list.asp?sid` 与 www `nyshow.asp?sxid` 的
  “引号→302 / 关键字→RST”一度被疑为注入，判别后确认是 WAF 字符拦截；绕过 WAF 直达应用后，
  后端对引号安全转义、**无注入**（runs/<run> 证据 E-009 / E-013 / E-014）。
- 多 IP 负载均衡 / 动态内容会让响应长度自然波动；任何“差异”须先对每侧**多次采样**确认稳定，
  再判定（probe.py DIFF `--samples` 即为此）。
- 拦截页哈希因回显 payload 而不同，不要据此当作“响应随注入变化”。
- **【最易错】自己打爆的单 IP 限流 ≠ 目标整站封锁**（某实战 E-010 教训）：连续大量请求后出现
  连接拒绝(10061)/超时，**不要**直接判“目标 WAF 把我源 IP 全站封了”。必做对照：(a) **另一个
  不同承载 IP 上的主机**还通不通？(b) **公网无关站点**还通不通？若它们还 200 → 这是**你自己的
  请求量触发了被你猛探的那几个 IP 的【per-IP 限流】**，是临时的、会冷却恢复，**不是**全站封锁、
  **更不是**那几个 IP 没攻击面。某实战 当时把它误记成“整站封锁 certainty 1.0”，被 E-011/E-013 的
  对照实验证伪。**给任何“被封”结论赋高 certainty 前，必须先做这个 per-IP 对照。**
- “App 层弱鉴权(未授权返数据)” 与 “WAF 有无” 是**两件事**：一个有激进 WAF 的站，其 app 层接口
  仍可能未授权泄露（某实战 零信任 IAM 即如此）——WAF 拦的是恶意特征，良性接口枚举照样能挖。

## References

- OWASP: Web Application Firewall / WAF Evasion 通用原理
- 本仓实测: runs/<run>/ E-009 / E-013 / E-014（字符拦截 + GET-only 盲区）;
  runs/<run>/ E-010 / E-011 / E-013（per-IP 自限流误判 + 掩码服务器 + 激进封 IP）
- 关联 [[zfsoft-jwgl]] [[vsb-cms]] [[wisedu-ecampus]] [[ida-zerotrust-iam]]
