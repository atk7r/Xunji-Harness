# Peer Review Panel — 2026-07-12-agent-asset-runtime-hardening

_backend: panel:arkcli+claude · 2026-07-12T14:58Z_
> 候选, 非裁决。driver 须逐条过证据门。

## Verdict: WARN

_backend: panel:arkcli+claude_
_brain: codex_
_bundle_hash: bea3df3d569ecde1d150524eee3542b7a3ee77b2_
_evidence_index_hash: 4f685b2113ffdf44614fdb97ce6f4aa10e20bf9f_

## Findings
- [WARN] PR-001 workers.py merge gate calls `runtime_receipts.agent_asset_activity`, but the provided E-001 artifact excerpt is truncated and does not show this function, leaving a critical merge-gate dependency unverified | Evidence: evidence/workers.diff (`update_agent_lifecycle` / `_validate_asset_merge` calls `_runtime_receipts.agent_asset_activity`) and evidence/runtime-receipts.diff (excerpt ends before any `agent_asset_activity` definition) | Why: [panel:arkcli] [arkcli:kimi-k2.7-code] The “zero-tool / partial-package completion” claim depends on per-asset activity proof; if the method is missing or has the wrong signature, merged status becomes unreachable and the asset-enforcement chain breaks.
- [WARN] PR-002 Direct-egress opt-out `XUNJI_PROXY_REQUIRED=0` is environment-based and not attested per turn; a model could export it in a persistent shell session to bypass fail-closed proxy enforcement | Evidence: evidence/proxy-diff-save.diff (`tools/harness/proxy.py` `required()` reads `os.environ`) and evidence/turn-contract.diff (`_proxy_egress_reason` never inspects or locks that variable) | Why: [panel:arkcli] [arkcli:kimi-k2.7-code] Environment variables are not a security boundary when the model can issue Bash commands; the gate should not rely solely on env absence for operator approval.
- [WARN] PR-003 `_proxy_egress_reason` only enforces proxy/coverage proof for `Bash` and `WebFetch`, leaving other target-egress tool categories unaudited | Evidence: evidence/turn-contract.diff (`if tool != "Bash": return ""` after touched-host check) | Why: [panel:arkcli] [arkcli:kimi-k2.7-code] Any non-Bash tool that can issue network requests would silently bypass the proxy-aware gate.
- [WARN] PR-004 `_project_agent_lifecycle` swallows all exceptions when updating `state/assignments.json`, so malformed or locked state silently disables the async lifecycle projection the report relies on | Evidence: evidence/runtime-receipts.diff (`append_hook_event` `try: ... _project_agent_lifecycle ... except Exception: pass`) | Why: [panel:arkcli] [arkcli:kimi-k2.7-code] Silent failures hide the exact drift the new async logic is meant to surface.
- [WARN] PR-005 Async agent start/stop matching relies on a fixed 10-second window (`AGENT_LIFECYCLE_RACE_SECONDS`), which may miss delayed `SubagentStart` events | Evidence: evidence/runtime-receipts.diff (`AGENT_LIFECYCLE_RACE_SECONDS = 10.0` and `near_starts` filter in `agent_attempts`) | Why: [panel:arkcli] [arkcli:kimi-k2.7-code] Real async agents can start after 10 s due to queueing; missed starts could produce inconsistent `running`/`returned` state and block merge gates.
- [WARN] PR-006 The asset-coverage hard gate rejects any target action touching a known host while any reachable/unknown asset remains unassigned, even if the action targets only already-assigned assets | Evidence: evidence/turn-contract.diff (`if touched_hosts and unassigned_assets:` branch in `evaluate_pretool`) | Why: [panel:arkcli] [arkcli:kimi-k2.7-code] This global check can deadlock a run by preventing work on assigned assets until every other asset is also mapped.
- [WARN] PR-007 `load_assignments` bumps the default schema to 2 and new merge/attempt fields are assumed present, risking breakage for legacy assignments.json from older runs | Evidence: evidence/workers.diff (`load_assignments` default schema changed to 2) and evidence/runtime-receipts.diff (`_project_agent_lifecycle` expects `attempts` list) | Why: [panel:arkcli] [arkcli:kimi-k2.7-code] Reopened old runs may crash or skip enforcement due to missing keys.
- [WARN] PR-008 arkcli panel had backend errors; review is partial | Evidence: glm-5.2: parse error; output tail: igration - assignments.json schema 1 to 2**
In E-003 (workers.diff), the `load_assignments` function changes:
```python
-        data = {"schema": 1, "assignments": []}
-    data.setdefault("schema", 1)
+        data = {"schema": 2, "assignments": []}
+    data.setdefault("schema", 2)
```

This means old runs with schema 1 assignments.json will be loaded and their schema will be upgraded to 2 via `setdefault`. But `setdefault` only sets if the key doesn't exist. If an old file has `"schema": 1`, | Why: [panel:arkcli] At least one arkcli reviewer failed, so PASS only means the completed panel members found no blocker.

## Blind-spot check
- [arkcli] [kimi-k2.7-code] The merge gate depends on `runtime_receipts.agent_asset_activity`, which is not visible in the truncated E-001 excerpt; this is the most likely unverified dependency.
- [arkcli] [kimi-k2.7-code] Proxy opt-out via environment is model-mutable in a persistent shell; the reviewer should confirm whether each tool invocation starts with a sanitized environment.
- [arkcli] [kimi-k2.7-code] Non-Bash target tools are not routed through `_proxy_egress_reason`; an inventory of all network-capable tools is missing.
- [arkcli] [kimi-k2.7-code] Async lifecycle matching uses an arbitrary 10 s tolerance rather than agent-id causal matching.
- [arkcli] [kimi-k2.7-code] `_project_agent_lifecycle` fails open (silent pass) on any projection error.
- [arkcli] [kimi-k2.7-code] The unassigned-assets hard gate is over-broad and may stall valid work.
- [arkcli] [kimi-k2.7-code] Tests appear to be selftests that prove happy-path assumptions; there are no adversarial tests for forged coverage, nested Agent fan-out, env-variable bypass, or delayed async starts.
- [arkcli] [kimi-k2.7-code] GLM’s repeated parse failures are recorded as a backend limitation; ensure those failures do not count as an independent “no findings” vote.
- [claude] **Documentation duplication as latent drift**: The `.agents/skills/xunji-agent-board/SKILL.md` and `.claude/skills/xunji-agent-board/SKILL.md` files are near-duplicates. Both were updated in this diff, but there's no automated check ensuring they stay in sync. A future change that updates only one copy would create silent protocol drift between Claude's native skill and the agent-invoked version.
- [claude] **AGENT_LIFECYCLE_RACE_SECONDS=10.0 hardcoded**: The 10-second window for associating SubagentStart with Agent PostToolUse may be too narrow on heavily loaded systems where SubagentStart can legitimately arrive 15-30 seconds after launch. If missed, the attempt's `started_at` field stays 0.0, and `lifecycle_floor` falls back to `launched_at`, which could place SubagentStop events before the floor, causing them to be missed. This is unlikely in normal operation but would produce a confusing "launched but never returned" state. The race test only covers SubagentStop-before-PostToolUse, not slow SubagentStart.
- [claude] **`_validate_asset_merge` evidence search is overly broad**: The function searches for hostname anywhere in evidence blocks. An E-entry that mentions an asset in passing (e.g., "also checked foo.example but...") satisfies the gate for that asset. This makes the gate slightly too permissive — but in the benign direction (more evidence credit, not less).
- [claude] **No integration test covering full write-through race**: The selftests test `_project_agent_lifecycle` and `update_agent_lifecycle` in isolation. No test writes to `assignments.json` from both paths simultaneously to verify conflict-free operation. Given they run in the same process, this is unlikely but represents untested behavior.
- [claude] **Backward compatibility with older runs**: Schema bump from v1→v2 and the removal of `_asset_relevant()` filtering means ALL assets (including unreachable) now appear in the coverage matrix. This is correct for the new behavior, but older runs that relied on `_asset_relevant()` to filter noise will now show every asset, increasing the visible "unassigned" count. The E-002 evidence claims this was tested against a real "Hamastar run" showing total=80, reachable=15, unreachable=47 — demonstrating the expected inflation. No migration code is needed, but operators with in-progress runs should expect their coverage dashboards to show more assets.

## Context-limit notes
- [arkcli] [kimi-k2.7-code] The bundle excerpts are heavily truncated; I cannot open the actual run-dir files, so line-level cross-checks are limited to the provided snippets and SHA1s.
- [arkcli] [kimi-k2.7-code] Several doc strings and error messages are in Chinese; nuanced intent (especially CNVD/Taiwan-specific scope terminology) may be slightly misread.
- [arkcli] [kimi-k2.7-code] This is a local framework-maintenance bundle, not a live target, so “exploitation” findings are about control bypasses and enforcement gaps rather than confirmed target compromise.
- [arkcli] [kimi-k2.7-code] I cannot verify whether `agent_asset_activity` exists later in `runtime_receipts.py` beyond the excerpt; the finding is about unverified dependency, not confirmed absence.
- [arkcli] glm-5.2: parse error; output tail: igration - assignments.json schema 1 to 2**
In E-003 (workers.diff), the `load_assignments` function changes:
```python
-        data = {"schema": 1, "assignments": []}
-    data.setdefault("schema", 1)
+        data = {"schema": 2, "assignments": []}
+    data.setdefault("schema", 2)
```

This means old runs with schema 1 assignments.json will be loaded and their schema will be upgraded to 2 via `setdefault`. But `setdefault` only sets if the key doesn't exist. If an old file has `"schema": 1`,
- [claude] All artifacts were provided as diffs in the review bundle. I could not verify the diffs against the live repository files due to read restrictions on `tools/` paths. The sha1 hashes in the evidence_index serve as the integrity anchor.
- [claude] This is a maintenance review, not a pentest. "Confirmed" findings with certainty=1.0 are based on selftest passing, which is appropriate for code correctness claims. No target-side artifacts exist to cross-check.
- [claude] Chinese-language documentation and error messages were understood through the diff context. Some nuanced policy declarations in Chinese may carry implications I cannot fully evaluate.
- [claude] Prior review findings (Kimi BLOCKER + WARNs) were accepted and fixed per review.md. I conducted this review on the post-fix code (the current hashes in the bundle).