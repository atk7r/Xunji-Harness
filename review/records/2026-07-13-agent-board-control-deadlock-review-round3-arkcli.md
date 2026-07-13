# Peer Review — xunji-agent-board-control-review

_backend: arkcli:kimi-k2.7-code+glm-5.2 · 2026-07-13T02:21Z_
> 候选, 非裁决。driver 须逐条过证据门: 不盲从(驳工具/语境误报), 不忽视(采纳真盲补)。

## Verdict: ERROR

_backend: arkcli:kimi-k2.7-code+glm-5.2_
_brain: codex_
_bundle_hash: 086ee8f9d5842b5233f8f2878c5f41f0ccd6c4df_
_evidence_index_hash: fe2816fbfeffaed50fa637438eb618d5749122a6_

## Findings
- (none)

## Blind-spot check
- (none)

## Context-limit notes
- kimi-k2.7-code: timeout >300s
- glm-5.2: parse error; output tail: ract.patch ✓
  - Unknown role rejection - present in diff-workers.patch (`if role not in CANONICAL_AGENT_ROLES: raise ValueError(...)`) ✓
  - Terminal amendment - present in diff-workers.patch (`amend: bool = False`) ✓
  - Disposition history preservation - present in diff-workers.patch (`history = rec.setdefault("disposition_history", [])`) ✓
  - Done-to-adjudicated transition - present in diff-workers.patch selftest (`done_to_adjudicated = update_agent_lifecycle(..., status="blocked", ...)`) ✓
- attempt 1: arkcli panel 全部模型失败: kimi-k2.7-code: timeout >300s; glm-5.2: parse error; output tail: y." This means the author is worried that if someone adds "Bash" to NON_EGRESS_TOOLS in the future, the old code would let fanout control bash commands fall through and potentially be classified as non-target, which could weaken the boundary. The new code explicitly returns False for fanout control bash, and True for all other bash.

Actually wait - I need to think about this differently. The concern is about the ORDER of checks. In the old code:
1. If WebFetch OR (Bash AND NOT fanout_control) →
- attempt 2: arkcli panel 全部模型失败: kimi-k2.7-code: timeout >300s; glm-5.2: parse error; output tail: ract.patch ✓
  - Unknown role rejection - present in diff-workers.patch (`if role not in CANONICAL_AGENT_ROLES: raise ValueError(...)`) ✓
  - Terminal amendment - present in diff-workers.patch (`amend: bool = False`) ✓
  - Disposition history preservation - present in diff-workers.patch (`history = rec.setdefault("disposition_history", [])`) ✓
  - Done-to-adjudicated transition - present in diff-workers.patch selftest (`done_to_adjudicated = update_agent_lifecycle(..., status="blocked", ...)`) ✓
- arkcli: arkcli panel 全部模型失败: kimi-k2.7-code: timeout >300s; glm-5.2: parse error; output tail: ract.patch ✓
  - Unknown role rejection - present in diff-workers.patch (`if role not in CANONICAL_AGENT_ROLES: raise ValueError(...)`) ✓
  - Terminal amendment - present in diff-workers.patch (`amend: bool = False`) ✓
  - Disposition history preservation - present in diff-workers.patch (`history = rec.setdefault("disposition_history", [])`) ✓
  - Done-to-adjudicated transition - present in diff-workers.patch selftest (`done_to_adjudicated = update_agent_lifecycle(..., status="blocked", ...)`) ✓

> ERROR: arkcli panel 全部模型失败: kimi-k2.7-code: timeout >300s; glm-5.2: parse error; output tail: ract.patch ✓
  - Unknown role rejection - present in diff-workers.patch (`if role not in CANONICAL_AGENT_ROLES: raise ValueError(...)`) ✓
  - Terminal amendment - present in diff-workers.patch (`amend: bool = False`) ✓
  - Disposition history preservation - present in diff-workers.patch (`history = rec.setdefault("disposition_history", [])`) ✓
  - Done-to-adjudicated transition - present in diff-workers.patch selftest (`done_to_adjudicated = update_agent_lifecycle(..., status="blocked", ...)`) ✓