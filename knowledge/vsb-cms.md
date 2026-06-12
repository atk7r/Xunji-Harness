---
id: vsb-cms
product: VSB 院系门户内容管理系统
vendor: VSB（高校院系网站群 CMS）
aliases: [VSB, 院系门户, system/resource, dynclicks, vsbscreen, 网站群]
category: cms
last_reviewed: 2026-06-12
maturity: seed
---

<!--
Grounding knowledge, not a weapon. 来源: <run> 实测(run-observation) +
公开披露(external-cited)。无 payload/步骤/PoC。
-->

## Recognition (identification only)

- Signature: 静态资源前缀 `/system/resource/`（`/system/resource/js/dynclicks.js`、
  `vsbscreen.min.js`、`/system/resource/code/...`）；上传/媒体路径 `/__local/`。
- Signature: 文章 URL 重写 `/info/<栏目id>/<文章id>.htm`（静态化页）；首页含点击计数
  span `dynclicks_u<owner>_<clickid>`；搜索 `/search/modules/resultpc/soso.html`。
- Signature: 反代常把 `Server` 头掩码（如显示一串 `**********`），与 VSB 内容特征叠加出现。
- Distinguishing notes: 院系站标题多为“<学校>-<院系/部处>”；与正方/金智等业务系统区分点是
  `/system/resource/` + `dynclicks` + 静态化 `/info/.../.htm`。

## Weak-Point Anchors (variant-analysis input — NOT exploit steps)

- Anchor: 未授权点击计数接口 `dynclicks.jsp` 注入 缺陷类
  - Affected: `/system/resource/code/news/click/dynclicks.jsp?clickid&owner&clicktype`
  - Mechanism: clickid/owner 历史上拼接进 SQL; 但部分部署对其 int 转换/参数化(本仓实测 某实战 即此),
    且前置 WAF 拦关键字 → 需对位实测, 不可假设可注入
  - Reference: 公开“VSB dynclicks SQL注入”资料; 本仓 run-observation(证伪记录)
  - source: external-cited
- Anchor: 搜索 / 其它 `/system/resource/code/` jsp 的注入/文件面
  - Affected: 搜索、列表、媒体等动态 jsp
  - Mechanism: dynclicks 之外 VSB 还有搜索/列表接口, 不应以单接口否定整栈
  - Reference: 本仓 run-observation
  - source: driver-reasoning
- Anchor: 内网链接 / 内部系统泄露（低危）
  - Affected: 院系站常硬编码内网 OPAC/期刊/管理系统直链
  - Mechanism: 公网页面误暴露内网 IP/路径, 利于内网情报
  - Reference: 本仓 run-observation（某实战 lib 泄露 192.168.x OPAC）
  - source: run-observation

## Verification Principle (existence proof)

- Existence proof: `/system/resource/` + `dynclicks` 即确认 VSB。注入须实测：数字等价/算术判上下文,
  引号→DB 报错 vs WAF 拦截 须区分（拦截页≠报错）。
- Hard stops: proof 级布尔/差异, 不拖库; dynclicks 计数接口避免高频(易触发 WAF 封 IP 与短信无关但属高频)。

## False-Positive / Confounders

- **WAF 拦截 ≠ 可注入**：引号触发拦截页/连接重置是 WAF, 不是 DB 报错; 反过来“WAF 挡掉了
  能产生 oracle 的 payload, 再用无 oracle 判不可注入”是**循环论证**, 避免（某实战 教训）。见 [[waf-block-recognition]]。
- 几十个院系站共享同一 VSB + 掩码反代, 是同栈别名, 勿 lump 成“都安全”——同栈也要逐站确认搜索等其它面。

## References

- https://www.cnvd.org.cn/ （检索“VSB / dynclicks”）
- 本仓实测: runs/<run>/ 证据 E-003/E-007（某实战 院系门户群）; 关联 [[waf-block-recognition]]
