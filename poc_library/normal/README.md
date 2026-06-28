# 普通 PoC

产品特定发现、已知技术应用、配置/条件依赖的 PoC。外发纪律见上级
[`poc_library/README.md`](../README.md)。

每个漏洞一个目录：`<漏洞id>/`，含 `README.md`（元数据+用法）与验证工具。

⚠️ 未公开披露的条目（厂商未修复、无 CVE/CNVD）在 `.gitignore` 中单独登记，
不随仓库推送。公开索引仅列已披露条目。

## 公开索引（已披露 / 可公开）

- （暂无条目）

## 本地条目（未披露，gitignored）

- **soarcloud-ais** — 飛騰雲端 AIS HR: 开放自助注册 + CustomerID 未校验 + ViewState RCE（条件性：需 machineKey）；关联 `runs/scshr_20260614/`
