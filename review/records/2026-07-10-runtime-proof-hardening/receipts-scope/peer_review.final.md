# Peer Review Panel — receipts-scope

_backend: panel:arkcli+claude · 2026-07-10T23:47Z_
> 候选, 非裁决。driver 须逐条过证据门。

## Verdict: WARN

_backend: panel:arkcli+claude_  
_brain: codex_  
_bundle_hash: 43ff4a535a2d6b5e7c2dd0e53c807cd03f3dfc1d_  
_evidence_index_hash: 54eb4ccd02a56f9261b439c7d3807c963a7de051_  

## Findings
- [WARN] PR-001 E-001 'Transcript-backed receipt enforcement' is reported as confirmed (certainty 1.0) but is supported only by adversarial selftests and code diffs, not by a live runtime_events.jsonl or session transcript artifact in this run. | Evidence: evidence_index:E-001, adversarial_selftests.summary.json, runtime_receipts.lines-001-150.txt, runtime_receipts.lines-451-600.txt, selftest_all.log | Why: [panel:arkcli] [arkcli:kimi-k2.7-code] The selftests exercise synthetic temp directories and mocked transcripts, so they validate code logic rather than demonstrating that the current run produced transcript-backed runtime receipts. Reporting this as confirmed overstates the evidence.
- [WARN] PR-002 review.md describes Round 2 driver dispositions including E-002 relabeling and external Kimi/fresh Claude model completions, but no evidence_index entry for E-002 or artifacts verifying those completions are present in the bundle. | Evidence: review.md, evidence_index | Why: [panel:arkcli] [arkcli:kimi-k2.7-code] Because review.md is a claim file, its assertions need evidence_index/artifact backing if they are used to justify scope decisions; currently they are unverified.
- [WARN] PR-003 arkcli panel had backend errors; review is partial | Evidence: minimax-m3: parse error; output tail: 97cf857c4de16bbaadb5f69190f3fa62bf38): I can see the contents. It lists 8 files with SHA256 hashes. Repository root is /Users/ccj/Documents/AI/Xunji. ✓
   
   - `runtime_receipts.lines-001-150.txt` through `runtime_receipts.lines-751-end.txt`: Source code split into chunks. The content matches the runtime_receipts.py file as referenced in the manifest. ✓
   
   - `selftest_all.log` (sha1: 657bbdf518e00f7e39f92608e921fb81b72aa590): I can see the 57 suites, all passed. ✓
   
   - `settings.diff` (; glm-5.2: parse error; output tail: 

Does the report contradict its own evidence ledger? The report says "E-001 covers implementation invariants and named adversarial controls, including the full selftest_all.log." The evidence does include selftest_all.log. The report says "Real Claude Agent/Cron/tool integration is intentionally reviewed in live-scope without duplicating its source and summaries here." This means the report acknowledges it doesn't cover live integration.

But here's the issue: E-001 is titled "Transcript-backed | Why: [panel:arkcli] At least one arkcli reviewer failed, so PASS only means the completed panel members found no blocker.

## Blind-spot check
- [claude] **The `_action_hash` function (line 41-47) only strips `description` and `timeout` from Bash tool_input**: Other metadata fields that Claude Code might inject (e.g., `dangerouslyDisablePermissions`, model-specific flags, or future hook-added fields) would cause the action_hash to differ even when the semantically meaningful command is identical. This could cause `unresolved_target_denials` to fail matching a retry to its original denial because the hash differs due to non-semantic metadata. The selftest's "successful same command resolves despite description drift" check (line 718) only tests description variation, not other metadata.
- [claude] **The `cron_quiescent` function uses `run_name.lower() in response.lower()` as a substring check (line 530)**: If a run is named `test` and CronList output contains the word `test` in an unrelated context (e.g., a different job's description), it would falsely report the run as non-quiescent. Similarly, if the run name is very short (e.g., `a`), it could match many CronList responses. The selftest uses `deadbeef` as the Cron job ID but the run name is a tempdir path which is unlikely to collide — this edge case isn't tested.
- [claude] **The `_peer_review_command_matches` function (lines 426-456) rejects any command containing shell metacharacters (`;&|$\`\<\>\n\r`) on line 428**: This correctly blocks injection, but it also means legitimate commands with env vars (e.g., `PYTHONPATH=/foo python3 tools/peer_review.py ...`) are rejected. The selftest tests `echo fake; python3 ...` as shell-decorated rejection but doesn't test an env-var-prefixed invocation, which is a legitimate use case.
- [claude] **The settings.diff hooks don't include a `timeout` or `dangerouslyDisablePermissions` field**: If turn_contract.py hangs, there's no hook-level timeout to kill it. The Claude Code hook runner may have its own timeout, but no artifact documents what that timeout is or whether it's configured.
- [claude] **The `installed-runtime-manifest.json` shows 8 turn_contract_hook_references but 9 hook wiring points in settings.diff**: SessionStart has `--selftest` (reference 1), UserPromptSubmit has one (ref 2), PreToolUse has two matchers (refs 3-4), PostToolUse has two matchers (refs 5-6), PostToolUseFailure (ref 7), SubagentStart (ref 8), SubagentStop — wait, let me recount. The manifest lists 8 references: one `--selftest` + 7 plain `turn_contract.py` invocations = 8 total. But the settings.diff adds hooks to: SessionStart (1 selftest + 1 hook), UserPromptSubmit (1 hook), PreToolUse (2 matchers), PostToolUse (2 matchers), PostToolUseFailure (1 matcher), SubagentStart (1 hook), SubagentStop (1 hook) = 10 hook invocations. The manifest only records 8. This mismatch suggests either some hooks share the same manifest entry (unlikely — each hook is a separate settings.json entry) or the manifest count is wrong. I cannot verify without seeing the full settings.json.
- [claude] **The `adversarial_selftests.summary.json` and `adversarial_selftests.log` contain different checks for output_gate**: The JSON summary.json shows 93 checks for output_gate. The plain log (`adversarial_selftests.log`) shows different check names — e.g., "honest denial statement remains allowed" in the log vs "free-form honest denial is still blocked" in the JSON. Wait — looking more carefully, these are DIFFERENT checks at different positions in the list. The log might be from a different run. But the JSON summary.json's output_sha256 is `611103d07b881a27750208df85dd1fe77a404cf25bd5f2f65c2d856b1a884841` — this should match the log output. Let me check: the summary.json says "free-form honest denial is still blocked" (check 3) while the log says "honest denial statement remains allowed" (check 3). These are genuinely different check names. This means the `adversarial_selftests.log` and `adversarial_selftests.summary.json` are from DIFFERENT selftest runs. The summary.json claims `source_sha256: 8f00005c...` but I cannot verify what source produced that hash. **This is a cross-check discrepancy**: the log file and the summary JSON were not generated in the same run, so the summary's output_sha256 doesn't match the log's output. I cannot confirm the selftests summarized in the JSON are the same ones whose output appears in the log.

## Context-limit notes
- [arkcli] minimax-m3: parse error; output tail: 97cf857c4de16bbaadb5f69190f3fa62bf38): I can see the contents. It lists 8 files with SHA256 hashes. Repository root is /Users/ccj/Documents/AI/Xunji. ✓
   
   - `runtime_receipts.lines-001-150.txt` through `runtime_receipts.lines-751-end.txt`: Source code split into chunks. The content matches the runtime_receipts.py file as referenced in the manifest. ✓
   
   - `selftest_all.log` (sha1: 657bbdf518e00f7e39f92608e921fb81b72aa590): I can see the 57 suites, all passed. ✓
   
   - `settings.diff` (
- [arkcli] glm-5.2: parse error; output tail: 

Does the report contradict its own evidence ledger? The report says "E-001 covers implementation invariants and named adversarial controls, including the full selftest_all.log." The evidence does include selftest_all.log. The report says "Real Claude Agent/Cron/tool integration is intentionally reviewed in live-scope without duplicating its source and summaries here." This means the report acknowledges it doesn't cover live integration.

But here's the issue: E-001 is titled "Transcript-backed
- [arkcli] arkcli succeeded after 2 attempt(s); previous failures: attempt 1: arkcli panel 全部模型失败: kimi-k2.7-code: arkcli exit 1; stderr/stdout tail: {
  "ok": false,
  "error": {
    "type": "error",
    "message": "arkruntime.create_responses: RequestError code: 500, err: Post \"https://ark.cn-beijing.volces.com/api/plan/v3/responses\": net/http: TLS handshake timeout, request_id: 2026071107365700001C9A14EC050AA31C"
  }
}
; minimax-m3: parse error; output tail: ioning this for external validation.

**Blind spot 4**: There's no evidence the adversarial selftests were run with a specific Python version or that the tests cover the deployed code. The selftest_all.log shows `/opt/homebrew/opt/python@3.14/bin/python3.14` was used. The adversarial_selftests summary has output_sha256 values for each suite.

**Blind spot 5**: The `workers.diff` shows significant code changes. Let me look more carefully:
   - Changed `_check_agent_board_needed` to use `run_model; glm-5.2: parse error; output tail: ript-backed receipt enforcement" sounds like it's claiming runtime enforcement, but the evidence only shows *static* and *self-test* enforcement. The report.md clarifies this: "The full repository regression is included as a control artifact, not presented as a separate finding."

Wait, the `runtime_receipts.py` code has `_transcript_has()`:
```python
def _transcript_has(record: dict) -> bool:
    tool_use_id = str(record.get("tool_use_id") or "")
    transcript = Path(str(record.get("transcript
- [claude] The Chinese-language content in all files (frontier.md, decisions.md, evidence.md, review.md, report.md) is straightforward technical documentation. The PR-002 discussion about `--dangerously-skip-permissions` being the "operator's actual launch mode" is concerning but I've interpreted it correctly — it means the operator intentionally runs without permission prompts, which the driver accepted as a harder boundary to test against. No Taiwan/CNVD-specific context applies.
- [claude] The Xunji-internal conventions (Agent Board, SharedBarrierGroup, `run_model.summary()`, `fanout_required`) appear to be correctly understood from code context. The anti_drift.py refactoring from inline regex to `run_model.summary()` is a significant architectural change — the old code only counted `Status: open` fronts while the new code counts `active(open/probing/working/type-A)` fronts via `data.get("open", [])`. This means "probing" fronts that were previously excluded now count toward the >= 4 threshold for Agent Board enforcement. If `run_model.summary()` returns "probing" fronts in its `open` list (which the selftest "probing is active" at adversarial_selftests.log:9 suggests it does), this is a behavior change that could trigger Agent Board in scenarios where the old code wouldn't.