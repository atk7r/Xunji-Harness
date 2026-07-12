# Peer Review Panel — 2026-07-12-agent-asset-runtime-hardening

_backend: panel:claude · 2026-07-12T15:56Z_
> 候选, 非裁决。driver 须逐条过证据门。

## Verdict: NEEDS_DRIVER

_backend: panel:claude_
_brain: codex_
_bundle_hash: 735808eb98a9c1f9c5cecbf5e9442e89ccd8c272_
_evidence_index_hash: 0ac66ec12f3802e879a6525c07129e862c93e152_

## Findings
- [WARN] PR-001 `_coordination_signature` calls `run_model.summary()` without exception handling | Evidence: `evidence/turn-contract.diff` line 85 (`state = run_model.summary(run_dir)` — no try/except, while lines 114-124 wrap `coverage_matrix.derive` in try/except) | Why: [panel:claude] Any `run_model` failure (corrupt state, missing module) propagates unhandled from `write_contract`, which is invoked on every hook event. This is a fragility point in the contract-writing pipeline. While arguably fail-closed (no contract → no target actions), the asymmetry with the guarded `coverage_matrix` path below it implies the risk was recognized for one data source but not the other.
- [WARN] PR-002 E-entry merge gate is temporally unanchored in `_validate_asset_merge` | Evidence: `evidence/workers-asset-merge.py.txt` lines 13-15 (`_canonical_evidence_text(run_dir)` searched for hostname anywhere in ALL evidence blocks, not scoped by agent-id or launch-time) | Why: [panel:claude] A pre-existing E-entry from a prior agent or earlier exploration phase naming the same host satisfies the gate. The concurrent `agent_asset_activity` check (line 15-18, agent-scoped and temporal) mitigates this to grant-only-no-revoke (the E-entry check adds no independent security), but the prose claim "每一资产必须由点名该 host 的 E-entry 证明测试覆盖" implies attribution that the code does not enforce. The E-entry check uses `(?<![\w.\-])re.escape(host)(?![\w.\-])` which could produce false-positive matches for very short hostnames that appear as substrings in unrelated evidence blocks.
- [WARN] PR-003 `.agents/skills/` vs `.claude/skills/` dual-copy drift hazard with no synchronization gate | Evidence: `evidence/driver-docs.diff` hunk at `.agents/skills/xunji-agent-board/SKILL.md` and `.claude/skills/xunji-agent-board/SKILL.md` (both updated with asset-token and coordination-epoch rules); R1-05 disposition declares them "intentionally different" | Why: [panel:claude] A future change that updates only one copy of `xunji-agent-board/SKILL.md` creates silent protocol drift between Claude's native skill and the Agent-invoked Codex guide. No automated test or CI check verifies that the asset-token format (`XUNJI_ASSETS=h1,h2`), attempt-semantics, and merge-gate rules remain synchronized across both copies. The claim in report.md item 4 ("Explicit asset packages...prevent selective...completion") depends on both Agent prompt construction (`.claude/skills`) and Agent behavior compliance (`.agents/skills`) agreeing on the same contract.
- [WARN] PR-004 Selftest-only evidence chain with zero live Claude Agent integration | Evidence: All four evidence entries (E-001 through E-004) cite selftest passing as control; `peer_review.round1.md` line 28 ("No actual live Agent lifecycle exercised"); R1-06 disposition records this as a residual limitation | Why: [panel:claude] Hook payload schema drift (Claude adding/renaming fields), timing edge cases at real concurrency, and `TaskCreate`/`TaskOutput` lifecycle events that don't map to `SubagentStop` are untested. The fabricated events in `_selftest()` prove the code handles the shapes it was designed for — not the shapes the real Claude runtime will produce in a future release. This is the single largest unverified assumption in all four closed fronts.
- [WARN] PR-005 Arkcli review panel consistently degraded to 2/3 across all rounds | Evidence: `peer_review.round1.md` line 38 ("arkcli panel 全部模型失败"); `peer_review.round2.md` line 33 ("glm-5.2: parse error; output tail"); `peer_review.final.md` line 62 ("glm-5.2: parse error"); `disposition.md` lines 76-79, 128-131, 169-172 all record GLM as "not counted as a clean vote" | Why: [panel:claude] The review architecture (CLAUDE.md "审查架构") requires kimi-k2.7-code + glm-5.2 as a panel. GLM produced useful raw findings (R1-01 was recovered from its parse-error tail) but never completed a valid structured vote. The panel effectively operated at 2/3 (kimi + fresh-context Claude) throughout. A finding that only GLM would have caught — particularly around the `.agents/` vs `.claude/` dual-copy drift or selftest-assumption blindness — may be absent.
- [WARN] PR-006 Zero adversarial/sabotage test coverage | Evidence: All selftests across all four evidence entries exercise happy-path scenarios; `peer_review.final.md` line 39 ("there are no adversarial tests for forged coverage, nested Agent fan-out, env-variable bypass, or delayed async starts") | Why: [panel:claude] A malicious or confused model could: (a) construct a prompt with `XUNJI_ASSETS=app1.example` while the assignment record binds `app2.example` — this IS caught by line 352 of turn-contract-egress.py.txt, but only via the `_resolve_assignment_assets` / `expected_assets` comparison; (b) set `XUNJI_PROXY_REQUIRED=0` in a subprocess environment via `env=` parameter — this IS caught by the direct-egress turn check (lines 206-211), but only if `direct_env_opt_out` is detected; (c) write a fake `coverage.json` with only one asset to bypass the unassigned-assets gate. None of these bypass paths have affirmative tests proving they are blocked.
- [WARN] PR-007 review panel had backend errors; aggregation is partial | Evidence: arkcli: ERROR arkcli panel 全部模型失败: kimi-k2.7-code: timeout >300s; glm-5.2: parse error; output tail: et("returned_at") or 0.0)
    if assignment and returned_at:
        latest_return_ts[assignment] = max(latest_return_ts.get(assignment, 0.0), returned_at)
```

It only tracks returned attempts. Running attempts are ignored for disposition. So if an Agent is launched but never returns, it won't block disposition of other assignments. But it also means the work of that Agent might be silently lost.

**E-002 - Coverage matrix:**

In the `derive()` function:
```python
assets = [a for a in cov.get(" | Why: At least one requested heterogeneous reviewer failed or was unavailable.

## Blind-spot check
- [claude] **Epoch signature collision risk under concurrent writes**: The `_coordination_signature` function reads `run_model.summary()` and `coverage_matrix.derive()` on every `write_contract` call. If two Root turns run in different Claude sessions against the same run dir, and one turn writes `frontier.md` between the signature computation and the contract write, the other turn's contract carries a stale signature. This isn't a correctness bug (the next turn will recompute), but it means epoch boundaries are eventually-consistent, not strictly serialized.
- [claude] **`_validate_asset_merge` double-gate asymmetry**: The function requires both a target-action receipt AND a canonical E-entry. The target-action receipt is agent-scoped and temporal; the E-entry is global and temporal-unaware. A correct implementation would scope the E-entry search to this agent's launch window (similar to how `agent_asset_activity` scopes to `since=first_launch`). The current implementation makes the E-entry check a weaker redundant gate — it passes whenever the asset was EVER mentioned in evidence, which makes it a granting gate that never independently rejects. This asymmetry is not documented.
- [claude] **`_event_destinations` doesn't handle IPv6 bracketed addresses or IDN**: The `bare_host` regex (`(?i)^(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z]{2,63}(?::\d+)?(?:/.*)?$`) uses ASCII-only character classes. IPv6 bracket notation `[::1]` or `[2001:db8::1]` won't match the domain pattern (but WOULD be caught by `ipaddress.ip_address()` which handles IPv6), and IDN/punycode hostnames like `xn--fsq.example` would match but their Unicode equivalents wouldn't. The `ipaddress` path handles IPv4/IPv6 but not hostnames that aren't dot-separated FQDNs. Single-label hosts (common in internal networks) are invisible to destination extraction.
- [claude] **`_proxy_egress_reason` correctly denies all WebFetch** (R2-01 fix confirmed at line 74-79 of turn-contract-egress.py.txt), but the ERROR MESSAGE says "目标请求必须改用 tools/probe.py/render.py/scan.py" without checking whether those tools are configured with a proxy. An operator reading this error might try `probe.py` without realizing proxy is still required — the denial message could be more explicit about the proxy requirement chain.
- [claude] **`_project_agent_lifecycle` raises RuntimeError on front mismatch** (CH-01 fix: line 305-309 of the runtime-receipts diff), but the `append_hook_event` caller wraps the projection in `try: ... except Exception: pass` (per the disposition's claim in FR-03, the fix writes `runtime_projection_error.json` instead of silently passing). However, the evidence bundle shows the FR-03 fix writes the error record but doesn't show whether the hook gate that reads this record actually BLOCKS further actions. The projection error is written to disk but whether it's enforced as a gate is not visible in the provided excerpts.
- [claude] **The `direct_egress_approved` contract field is computed once** from the prompt text at contract creation time. If an operator writes "I allow direct egress for this command only" in a chat message, the approval regex matches, and `direct_egress_approved=True` for the ENTIRE turn — not just the one command. This is acceptable behavior (turn-scoped approval) but the documentation doesn't clarify that approval scope is per-turn, not per-command. A cautious operator might expect per-command opt-in.
- [claude] **Schema v1→v2 migration is lazy and read-triggered**: `load_assignments()` (workers.diff line 201-207) adds `assets: []` and `attempts: []` to v1 rows in memory, but the file is only rewritten when a write operation follows. A read-only operation (statusline, coverage_matrix derive) sees the migrated structure, but the disk still carries v1 with no assets field. A concurrent process reading the raw file would see the unmigrated structure. This inconsistency window was noted in the round2 Claude blind-spot but never addressed.

## Context-limit notes
- [claude] I cannot verify whether the live files in `tools/runtime_receipts.py`, `tools/turn_contract.py`, and `tools/workers.py` match the diff evidence. The SHA1 hashes in the evidence index serve as integrity anchors but cannot be independently verified from a frozen bundle.
- [claude] I cannot run `python3 tools/selftest_all.py` to confirm the 57/57 suites pass on the current tree.
- [claude] The `.agents/skills/` vs `.claude/skills/` drift concern depends on how Xunji dispatches skills to Claude vs Codex Agents. If both always consume the same file (e.g., `.claude/skills/` is authoritative and `.agents/skills/` is never read), the dual-copy drift is cosmetic rather than operational. The review bundle doesn't clarify the dispatch path.
- [claude] Chinese-language error messages and policy declarations in `_proxy_egress_reason` (e.g., "交战代理硬门") and documentation may carry nuance I parse structurally but may not fully grasp semantically.
- [claude] The `_coordination_signature` function's behavior depends on `run_model.summary()` internals. I'm inferring fragility from the absence of try/except at line 85; the actual failure mode in production depends on what exceptions `run_model.summary()` can raise.
- [claude] This is a maintenance review of framework code, not a live-target pentest. Certainty=1.0 is appropriate for "the code change exists and selftests pass." The concerns raised are about the gap between selftest-proven and production-proven behavior.
- arkcli: ERROR arkcli panel 全部模型失败: kimi-k2.7-code: timeout >300s; glm-5.2: parse error; output tail: et("returned_at") or 0.0)
    if assignment and returned_at:
        latest_return_ts[assignment] = max(latest_return_ts.get(assignment, 0.0), returned_at)
```

It only tracks returned attempts. Running attempts are ignored for disposition. So if an Agent is launched but never returns, it won't block disposition of other assignments. But it also means the work of that Agent might be silently lost.

**E-002 - Coverage matrix:**

In the `derive()` function:
```python
assets = [a for a in cov.get("
- panel completed 1/2 required heterogeneous backends

> ERROR: arkcli: ERROR arkcli panel 全部模型失败: kimi-k2.7-code: timeout >300s; glm-5.2: parse error; output tail: et("returned_at") or 0.0)
    if assignment and returned_at:
        latest_return_ts[assignment] = max(latest_return_ts.get(assignment, 0.0), returned_at)
```

It only tracks returned attempts. Running attempts are ignored for disposition. So if an Agent is launched but never returns, it won't block disposition of other assignments. But it also means the work of that Agent might be silently lost.

**E-002 - Coverage matrix:**

In the `derive()` function:
```python
assets = [a for a in cov.get("