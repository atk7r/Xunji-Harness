# Peer Review Panel — xunji-agent-board-control-review

_backend: panel:claude · 2026-07-13T02:09Z_
> 候选, 非裁决。driver 须逐条过证据门。

## Verdict: NEEDS_DRIVER

_backend: panel:claude_
_brain: codex_
_bundle_hash: 086ee8f9d5842b5233f8f2878c5f41f0ccd6c4df_
_evidence_index_hash: fe2816fbfeffaed50fa637438eb618d5749122a6_

## Findings
- [WARN] PR-001 review panel had backend errors; aggregation is partial | Evidence: arkcli: ERROR arkcli panel 全部模型失败: kimi-k2.7-code: timeout >300s; glm-5.2: parse error; output tail: ds are not.
  - This is a fail-closed improvement: previously, if NON_EGRESS_TOOLS got a Bash entry, the old logic might miss it.

But wait - the new logic uses `_fanout_control_bash` which uses `_readonly_shell` (which is "narrow shell read grammar") AND `_control_invocation`. Let me check the source-context.txt:

```python
def _readonly_shell(command: str) -> bool:
    """Allow a narrow shell read grammar; unknown syntax remains write-capable."""
    if not command.strip() or re.search(r">|`|\ | Why: At least one requested heterogeneous reviewer failed or was unavailable.

## Blind-spot check
- (none)

## Context-limit notes
- [claude] The project appears to be a Chinese-language automated pentesting/security verification framework ("Xunji"/迅即). I may misunderstand some domain-specific conventions around evidence maturity, coverage gates, or the "Codex-authored" workflow.
- [claude] The "Codex" reference may refer to a specific code-review pipeline or tool within this framework's ecosystem — I'm treating it as the author identity for the diff under review.
- [claude] Some terminology in the Chinese-language comments and test assertion labels (e.g., "本轮真实", "处置锚点") is understood but I may miss nuances in the exact semantics of the control-plane state machine.
- [claude] The decision F-001's "safety boundary" states this is "repository maintenance only; no live target actions." This means the review scope is purely code quality and regression testing, which I've applied. If there are additional operational concerns about the agent board control plane that only manifest in live runs, I would not detect them from these artifacts alone.
- arkcli: ERROR arkcli panel 全部模型失败: kimi-k2.7-code: timeout >300s; glm-5.2: parse error; output tail: ds are not.
  - This is a fail-closed improvement: previously, if NON_EGRESS_TOOLS got a Bash entry, the old logic might miss it.

But wait - the new logic uses `_fanout_control_bash` which uses `_readonly_shell` (which is "narrow shell read grammar") AND `_control_invocation`. Let me check the source-context.txt:

```python
def _readonly_shell(command: str) -> bool:
    """Allow a narrow shell read grammar; unknown syntax remains write-capable."""
    if not command.strip() or re.search(r">|`|\
- panel completed 1/2 required heterogeneous backends

> ERROR: arkcli: ERROR arkcli panel 全部模型失败: kimi-k2.7-code: timeout >300s; glm-5.2: parse error; output tail: ds are not.
  - This is a fail-closed improvement: previously, if NON_EGRESS_TOOLS got a Bash entry, the old logic might miss it.

But wait - the new logic uses `_fanout_control_bash` which uses `_readonly_shell` (which is "narrow shell read grammar") AND `_control_invocation`. Let me check the source-context.txt:

```python
def _readonly_shell(command: str) -> bool:
    """Allow a narrow shell read grammar; unknown syntax remains write-capable."""
    if not command.strip() or re.search(r">|`|\