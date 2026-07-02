# Surface

## Assets

- 

## Entry Points

- 

## Trust Boundaries

- 

## Interesting Signals

- Signal:
  - Source:
  - Why it matters:
  - Normal explanations:
  - Follow-up:

## Input Shape Catalog

<!-- 条件段 —— 随着攻击深入逐步填充。每个 IS-xxx 记录一个已探测的输入形状。
     跨 front 可复用的请求模板。 -->

### IS-001

- URL pattern: POST /authService/authUser/v2/login/phone
- Content-Type: application/x-www-form-urlencoded
- Key params: phone (numeric, 11-digit), password (string)
- Auth required: none
- Response shape: JSON {code: int, msg: string, data: object|null}
- Seen on hosts: app.example.com
- Tested payload classes: SQLi-login (C-004), NoSQLi (C-005)
- Saturation: 2/5 (SQLi, NoSQLi, type-confusion, SSTI, auth-bypass)

## Discovery Channels

<!-- 六个 bool 自检，不是台账。每渠道走过即打勾，防止"某类入口整体没看"导致整类漏洞丢失。
     漏读内联脚本是漏接口的首要原因——每个抓取页面的 <script> 标签都要解析。 -->

- JS refs (独立.js fetch/axios调用已提取): yes / no
- Inline scripts (每个页面的内联 <script> 已解析): yes / no
- Asset refs (<script src>/<link> 资产已抓取, src相对其所在页面解析): yes / no
- Page links (导航/页内链接的页面入口已纳入): yes / no
- Path inference (batch→单品 list→export 等路径推断已探活): yes / no
- Response body (运行时响应体里出现的新接口已追加到 api_inventory): yes / no
