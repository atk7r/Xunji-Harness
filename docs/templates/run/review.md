# Review

## Independent Review

> 独立复审记录。check_run 识别此标记 + 时间戳作为有效复审。peer_review.py 成功后自动写入。
> 当 codex API 不可达时，driver 可手工填写此节。

- Reviewer: (codex / arkcli-panel / manual-driver)
- Time: (ISO timestamp)
- Verdict: (PASS / WARN / BLOCKER)
- BundleHash: (review_bundle hash, if produced)
- EvidenceIndexHash: (content-addressed evidence_index hash, if produced)

## Review Finding Ledger

> peer_review.py 写入的 PR-xxx 待处理账本。BLOCKER 不能保持 pending/unresolved 收口。
> DriverResolution 必须引用 E-id / artifact / control，或写清 accepted/dismissed/superseded/escalated。
> 本节默认留空；不要手工保留 PR-xxx 占位。只有真实 peer_review 输出才写 `### PR-xxx`。

## R-001

- Time:
- Reviewed files:
- Shallow work smells:
- Fronts closed too early:
- Fronts waiting for user direction:
- Evidence gaps:
- False-positive risks:
- Untrusted content handling:
- Repeated-barrier loops:
- Failure-budget triggers:
- Conclusions to downgrade:
- Fronts to reopen:
- Fronts to defer or close:
- Next autonomous front:
- Required file updates:
