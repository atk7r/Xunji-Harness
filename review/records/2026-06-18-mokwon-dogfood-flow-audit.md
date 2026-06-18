# 2026-06-18 mokwon 实弹 dogfood — 流程问题审计 + #1 scope 修复

操作者要"把真目标当任务跑,看流程有没有问题,给修复方案"。在 `mokwon.ac.kr`(목원대학교,
真授权目标)上 proof-level 跑了 Setup→侦察→飞轮→replay→check_run,记录流程问题。**骨架通,
问题在接缝。** 授权非概念(操作者最高权限),问题是【目标卫生/接线】。

## dogfood 实跑(proof-level,均经 guard)
setup_run+ingest_recon(134 资产,原生认 osint_ai schema)→ 4 皇冠 front 真探(SSO ucm /
群件 gwdev·gwmobile / Tomcat 9.0.58)→ knowledge_match(3 miss)→ knowledge_seed(Tomcat)→
replay 真 .replay.json(3 IDENTICAL+1 CONSISTENT,我整轮修的绑定在真数据上工作)→ check_run。
egress 通(www 200 PHP)。无确认漏洞(Tomcat manager 403、群件均登录门)。

## 流程问题(7,均现场实测)
1. **[中] recon 交接断层** — 操作者给 `report.md`(人看),管线要同目录 `recon.json`,无自动桥。
2+6. **[高] scope 脊梁从不填充** — Setup 把 134 资产折进 surface,却把 target.md 的 Target/
   In-scope/Out-of-scope 全留空 → classify/probe/replay 范围检查无真值源;classify 默认会群发
   个人 NAS/外部域。anti-lump 与 scope 硬撞,全靠 driver 手搓。**← 头号,本轮已修。**
3. **[中] `probe --save NAME` 体存成裸 `NAME`(无扩展名)** — driver 自然以为 `.html` → 路径报错;
   裸体丢 content-type。
4. **[中] `knowledge_match` miss 提示过时** — 喊"收口时申报入库",不提我刚焊进教义的
   `knowledge_seed.py` 写回端。教义焊了、工具提示没跟上(本轮反复治的病又犯)。
5. **[低] `--from-body` 抽的 signature 带版本号** `apache tomcat/9.0.58` → 太 specific。
6. (并入 2)
7. **[低] 模板占位噪音** — evidence.md 模板自带假 `E-001` 引 `evidence/foo.html` → 开局报死引用。
- **[注] 知识库 China 严重偏斜**(16 条几乎全国产栈),Korean 目标 ~0 锚点 → 写回端 load-bearing。

## #1 已修(本轮,非安全关键码)
**scope 从 recon 派生 → 填 target.md → classify 默认 honor。**
- 新 `tools/scope.py`(单一权威,像 evidence_parse): `derive_scope(recon)`(ownership unrelated→out,
  core/secondary→in,压成 `*.<registrable>`+IP /24)、`parse_target_scope(md)`(target.md 是源)、
  `in_scope(host)→in/out/unknown`。selftest 17 例。
- `setup_run.record_scope`: 填 target.md Target/In-scope/Out-of-scope/Notes(原全空)。mokwon 实测:
  9 in-模式 / 3 out / 4 复核;**修了我手工过滤误删的 2 个 IDN 别名**。
- `classify_hosts`: 默认跳过 out-of-scope(`--all` 覆盖)。mokwon 实测: 134→探 131,跳过个人 NAS×2+edutrack。
- 注册 selftest_all(17 suite 全绿)、check_rules 绿、ROUTER 文档。
- **派生不驱动**: 写的是默认,driver 改 target.md 即覆盖(scope.py 重解析)。
- 分层: scope=【打谁】目标卫生,非授权门(操作者的事)、非 safety_gate 硬地板。

## 仍待(下轮)
- **guard.py 硬强制 scope**(out-of-scope 默认拦+显式覆盖)= 安全关键码,单独 commit 过独立复审。
  本轮授权既非概念,硬拦优先级降,先落派生+classify 过滤这非安全高价值部分。
- 接缝 #1/#3/#4/#5/#7(report→json 桥 / probe --save 扩展名 / knowledge_match miss 提示 /
  signature 剥版本 / 模板占位)逐条修。
- 知识库喂非国产栈(把这次 Tomcat/ezMobile/SSO 真入库)。
- 未 dogfood: 完整 Driver→Hunter→Reviewer→收口、fan-out、graph、peer_review、sentinel 消费。
