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

### IS-xxx

- URL pattern:
- Content-Type:
- Key params:
- Auth required:
- Response shape:
- Seen on hosts:
- Source JS/artifact:
- Client-controlled params:
- Client-side signature/token/nonce logic:
- Role or permission hint:
- State transition:
- Linked threat hypothesis:
- Tested payload classes:
- Saturation:

## Permission / State Working Matrix (Conditional)

<!-- 条件段 —— 只有存在多角色/多账号或可观察状态机时填写。
     单账号时写 cross-role: N/A (single account)。矩阵只是工作笔记:
     不能凭矩阵关闭 front, 结论仍要回到 H/IS/C/E 和 evidence gate。 -->

- cross-role: N/A (single account)

| Front | Action/request | Role A expected | Role B observed E-id | State edge | Next control |
|---|---|---|---|---|---|
| | | | | | |

## Discovery Channels

<!-- 六个 bool 自检，不是台账。每渠道走过即打勾，防止"某类入口整体没看"导致整类漏洞丢失。
     漏读内联脚本是漏接口的首要原因——每个抓取页面的 <script> 标签都要解析。 -->

- JS refs (独立.js fetch/axios调用已提取): yes / no
- Inline scripts (每个页面的内联 <script> 已解析): yes / no
- Asset refs (<script src>/<link> 资产已抓取, src相对其所在页面解析): yes / no
- Page links (导航/页内链接的页面入口已纳入): yes / no
- Path inference (batch→单品 list→export 等路径推断已探活): yes / no
- Response body (运行时响应体里出现的新接口已追加到 api_inventory): yes / no
