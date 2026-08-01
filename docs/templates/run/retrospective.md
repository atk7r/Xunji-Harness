# Retrospective

> 强制收口产物 (mandatory closure artifact). 每次渗透收口都要诚实复盘 —— 不是免责声明,
> 是下一次更强的依据。check_run 收口硬门要求下面【自身问题】与【框架/工具问题】两节有真实内容
> (非空占位); 深浅由 driver 负责。把空泛套话留白, 写具体到本 run 的判断与摩擦。

## Run summary / 本次概述
<one short paragraph: target, what was attempted, what was confirmed / rejected / deferred>

## Self (driver) problems / 自身问题
<这一 run 我自己哪里做错/做慢/漏看: 错误判断、隧道视野、过早收口、证据门松动、
漏掉或过早关闭的前沿、绕远路。具体到本次, 别写通用套话。>

## Framework / tooling problems / 框架与工具问题
<tools/ hooks guard 知识库 文档 哪里拖了本 run 后腿: 缺能力、误报闸门、消息误导、
知识陈旧、模板不顺手。每条问题必须单独带 `- Status: fixed|open|deferred`；
不能用整节共用的一个 Status 蒙混。fixed 必须填 Fixed by + Verification，
open/deferred 必须填 Residual risk；或明确写 no framework/tooling issue。>

### FW-xxx

- Problem:
- Status: <fixed|open|deferred>
- Fixed by:
- Verification:
- Residual risk:

## Improvements / 改进项
<具体可落地的下一步: 要改的文件/工具/知识条目, 或确无则写 none。>
