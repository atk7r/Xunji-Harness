# Retrospect Notes

记录误报、撤离和确认失败。每条复盘应回答：

- 当时的假设是什么。
- 证据链缺了哪一环。
- 哪个信号来自受控动作，哪个信号可能来自环境本身。
- Verifier 应该返回 `needs_more_evidence`、`rejected` 还是 `confirmed_candidate`。
- 下次最小安全动作是什么。

成功并稳定复用的经验可以整理到 `docs/cognition/cases/`，再由人工决定是否进入长期 memory。
