# Peer Review Panel — 2026-07-12-agent-asset-runtime-hardening

_backend: panel:arkcli+claude · 2026-07-12T14:43Z_
> 候选, 非裁决。driver 须逐条过证据门。

## Verdict: BLOCKER

_backend: panel:arkcli+claude_
_brain: codex_
_bundle_hash: d1fe84ca9cda31638f636a15172e1d05d5edd82a_
_evidence_index_hash: 019fcc211d59607177e424f06d6b1c52b3b50785_

## Findings
- [BLOCKER] PR-001 Proxy enforcement is fail-closed for all target egress, including WebFetch; raw network clients are rejected. | Evidence: tools/turn_contract.py:930-944, evidence/turn-contract.diff, evidence/driver-docs.diff | Why: [panel:arkcli] [arkcli:kimi-k2.7-code] The turn-contract diff only rejects WebFetch when _event_known_hosts returns a non-empty touched set. If a model uses WebFetch against an un-inventoried host/IP, touched is empty and the gate returns '' (allow). This directly contradicts the documentation that target WebFetch is rejected and creates a proxy bypass for out-of-scope/unlisted targets.
- [WARN] PR-002 Child Agent gates cannot be bypassed through asset escape. | Evidence: tools/turn_contract.py:978-1015, evidence/workers.diff | Why: [panel:arkcli] [arkcli:kimi-k2.7-code] The per-asset boundary is guarded by 'if _is_target_action(event) and assigned_assets'. Legacy assignments or non-target roles with empty assets skip the check, letting the child operate on any known host. This leaves a backward-compatibility / schema-migration bypass for asset escape.
- [WARN] PR-003 Per-asset merge requires successful target-action receipts and canonical E-entry coverage. | Evidence: tools/workers.py:1114-1130, evidence/runtime-receipts.diff | Why: [panel:arkcli] [arkcli:kimi-k2.7-code] The workers diff invokes _runtime_receipts.agent_asset_activity, but the bundled runtime-receipts diff is truncated mid-function and never shows that helper. Without verifying its existence and behavior, the per-asset merge gate cannot be treated as confirmed.
- [WARN] PR-004 Approved proxy-aware target tools are constrained by the asset coverage ledger. | Evidence: tools/turn_contract.py:960-980, evidence/turn-contract.diff | Why: [panel:arkcli] [arkcli:kimi-k2.7-code] For approved Python tools the gate only verifies that a coverage ledger exists and that there are no unassigned known assets. It does not stop Root from probing an unknown host (touched_hosts empty) with tools/probe.py, so arbitrary out-of-scope probing is possible while the ledger looks clean.
- [WARN] PR-005 arkcli panel had backend errors; review is partial | Evidence: glm-5.2: parse error; output tail:  first sample is an outlier, the saved artifact might not represent the stable response.

**E-004: Driver and documentation diff**

Key changes:
- Agent board SKILL.md updated with asset package requirements
- CLAUDE.md updated with coordination epoch, asset packages, proxy fail-closed
- Various docs updated

Critical observations:
1. The coordination epoch concept is introduced. The claim is that "bare continue prompts preserve valid fan-out work without letting stale topology satisfy a changed | Why: [panel:arkcli] At least one arkcli reviewer failed, so PASS only means the completed panel members found no blocker.

## Blind-spot check
- [claude] **Selftest-only evidence chain with no live Claude Agent integration**: Every piece of runtime behavior evidence (async launch projection, SubagentStop matching, actor-scoped gates, merge validation, per-asset receipt counting) is proven only through fabricated hook events in `_selftest()` functions. A real Claude Code session that launches `Agent tool_use`, receives `SubagentStart`/`SubagentStop` hooks from the actual Claude runtime, and exercises the full pipeline end-to-end has never been executed. Hook payload schema drift (Claude adding/renaming fields), timing edge cases at the 10-second `AGENT_LIFECYCLE_RACE_SECONDS` boundary, and concurrent hook delivery are all untested. This was recorded as limitation R1-06 but remains the single largest unverified assumption in the entire change.
- [claude] **`_event_known_hosts` string-matching against normalized asset names is fragile in two directions**: (a) An asset named `api` (short hostname) would match any command text containing "api" as a substring — false positive triggering the proxy gate on legitimate non-target operations. (b) An asset with a Chinese-language or IDN hostname would fail `_normalized_assets` which only handles ASCII URL schemes and dot-separated domains. The `re.sub(r"^[a-z][a-z0-9+.\-]*://", "", value)` regex uses ASCII-only character class `[a-z]`.
- [claude] **Coverage matrix selftest adds E-005/E-006 but the evidence host-matching logic never tests the warning path**: The selftest (asset-coverage.diff `@@ -802,6 +948,22 @@`) adds front F-006 with "Vectors tried: SQLi, IDOR" covering multi-a.example and multi-b.example, plus E-005 naming a.example and E-006 naming b.example. But the test never asserts that the warning `"front-level Vectors tried 不直接计入"` is actually generated. The coverage_warnings list is populated but never checked in assertions — the warning could silently fail to generate.
- [claude] **`_resolve_assignment_assets` validates asset presence in front text via regex but front text is not normalized**: The function reads `_front_text(run_dir, front).lower()` and searches with the normalized hostname. But if the front text contains the host in a URL (e.g., `https://app.example.com:8443/login`) and the normalized name is `app.example.com`, the regex search would still match because `re.escape("app.example.com")` matches the literal substring. However, if the front uses an IP address while the coverage has a hostname (or vice versa), the match fails — the code raises `ValueError("asset(s) are not explicitly named in the selected frontier block")` even though the operator intended the asset to be covered.
- [claude] **`write_contract` recomputes coordination signature on every hook event, not just on turn boundaries**: The signature computation involves `run_model.summary()`, JSON parsing of `coverage.json`, glob of nested coverage files, and `coverage_matrix.derive()`. For runs with large coverage files or many nested subdirectories, this could add measurable latency to every single hook invocation — not just the first one in a turn.
- [claude] **Review architecture obligation unsatisfied**: `review.md` states "Round 2 is pending; Codex self-review does not count." The review architecture requires an arkcli panel (kimi-k2.7-code + glm-5.2) per the rubric: "Codex authored the diff and cannot count as its own independent reviewer." Kimi timed out at 300s and GLM's output failed parsing. The matrix is not satisfied — a bare Claude-Claude review (my vote) cannot close the review gate alone unless arkcli is confirmed unavailable. The review.md doesn't declare arkcli as definitively unavailable, only that round 1 failed.

## Context-limit notes
- [arkcli] glm-5.2: parse error; output tail:  first sample is an outlier, the saved artifact might not represent the stable response.

**E-004: Driver and documentation diff**

Key changes:
- Agent board SKILL.md updated with asset package requirements
- CLAUDE.md updated with coordination epoch, asset packages, proxy fail-closed
- Various docs updated

Critical observations:
1. The coordination epoch concept is introduced. The claim is that "bare continue prompts preserve valid fan-out work without letting stale topology satisfy a changed
- [claude] The evidence diffs in the review bundle are truncated (each at ~14K chars excerpt out of 27-39K total). The non-excerpted portions of `runtime_receipts.py` and `turn_contract.py` likely contain the `agent_actor`, `agent_asset_activity`, and additional `_selftest` code that I cannot verify. My cross-module dependency concern could be resolved by confirming these functions exist in the full file.
- [claude] I cannot inspect the live `tools/runtime_receipts.py`, `tools/turn_contract.py`, or `tools/workers.py` to verify the diff was applied correctly to the working tree (Read permission denied in this read-only mode). I'm relying solely on the diff artifacts.
- [claude] The Chinese-language operator markers, error messages in `_proxy_egress_reason` (e.g., "交战代理硬门"), and setup documentation may contain nuance I parse structurally but may not fully grasp semantically. My documentation-drift finding is based on structural code-vs-claim comparison, not Chinese semantic analysis.
- [claude] I cannot run `python3 tools/selftest_all.py` to verify the 57/57 suites actually pass with the current tree state. The evidence.md claims they passed at the time of writing.
- [claude] `peer_review.round1.json` exists in the directory but was not queried — it may contain additional structured findings from the round 1 panel not captured in `peer_review.round1.md`.