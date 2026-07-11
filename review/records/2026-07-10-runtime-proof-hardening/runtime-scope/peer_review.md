# Peer Review Panel — runtime-scope

_backend: panel:arkcli+claude · 2026-07-10T15:30Z_
> 候选, 非裁决。driver 须逐条过证据门。

## Verdict: BLOCKER

_backend: panel:arkcli+claude_  
_brain: codex_  
_bundle_hash: f415bda7eed4e6ab4cf8673a0de16063a2420363_  
_evidence_index_hash: 87f81a9f56c4d749309e0d1aab44960d3c9711cc_  

## Findings
- [BLOCKER] PR-001 E-003 "Installed runtime observation" is reported as confirmed (certainty 0.8) based only on the static `installed-settings.json` configuration file, with no current-turn hook receipt or `runtime_events.jsonl` trace. | Evidence: evidence_index:E-003, installed-settings.json | Why: [panel:arkcli] [arkcli:kimi-k2.7-code] Evidence discipline states that environment-provided artifacts and single observations are never confirmation on their own; a settings file alone cannot prove the hooks fire or that prompt-mode / Agent-Board enforcement occurs in real sessions.
- [WARN] PR-002 E-001 and E-002 are marked certainty 1.0 from code diffs and source snippets, but no installed hook-file hashes or real Claude Code hook receipts demonstrate deployment beyond the run directory. | Evidence: evidence_index:E-001, output_gate.diff, run_gate.hunks-01.diff, evidence_index:E-002, runtime_receipts.lines-001-150.txt, workers.diff | Why: [panel:arkcli] [arkcli:kimi-k2.7-code] Diffs prove intended code changes, not that `.claude/hooks/*.py` are the deployed versions or that the gates actually blocked/allowed real tool events.
- [WARN] PR-003 No adversarial or bypass-test artifacts are present for the new prompt-mode classifier, `fanout_override`, or Agent Board enforcement; only happy-path self-tests are shown. | Evidence: turn_contract.lines-001-170.txt, turn_contract.lines-171-340.txt, run_gate.hunks-01.diff, run_gate.hunks-02.diff | Why: [panel:arkcli] [arkcli:kimi-k2.7-code] Closing high-value control-plane fronts after self-tested happy paths leaves bypass surfaces uncharacterized; fail-closed claims need adversarial validation.
- [WARN] PR-004 The audit trail lacks `decisions.md` and any `CodexCompletionReview` runtime receipt required by the updated `run_gate` normal-closure logic. | Evidence: run_gate.hunks-01.diff, runtime_receipts.lines-301-450.txt, review_bundle.files | Why: [panel:arkcli] [arkcli:kimi-k2.7-code] `run_gate` now enforces `_normal_closure_prerequisite` with `review.md` + `decisions.md` and `completion_review_valid`; the provided file list contains `review.md` but not `decisions.md`, and no completion-review receipt is indexed.
- [WARN] PR-005 arkcli panel had backend errors; review is partial | Evidence: minimax-m3: parse error; output tail:  fcntl serializes the writes, so race should be prevented at write time. But on Windows fallback (no fcntl), locking is lost. The code acknowledges this with a comment.

11. **Agent Disposition validation**:
    - The check is that merged status requires `(Evidence|Front|Decision|Refuted|Barrier)[:：]` and E/F/D anchors exist in canonical files.
    - The check for "anchors_exist" uses `canonical.upper() for anchor in anchors` - this uppercases both sides, so case doesn't matter. Good.
    - But:; glm-5.2: parse error; output tail: n response:
    observed.add(job_id)
```
This adds a job_id to the observed set if it appears in the CronList response AND the run name is in the response. But this is a substring check - if the job_id is a substring of another job_id, it could match incorrectly. For example, if job_id "abc" appears in "abcdef" in the response. However, job_ids are typically long enough that this is unlikely.

3. **The `agent_disposition` function** checks if disposition timestamps are after receipt timestamps:
 | Why: [panel:arkcli] At least one arkcli reviewer failed, so PASS only means the completed panel members found no blocker.

## Blind-spot check
- [arkcli] [kimi-k2.7-code] The author likely conflated "code exists in the run directory" with "controls are enforced at runtime"; no `runtime_events.jsonl` or actual hook trace is present.
- [arkcli] [kimi-k2.7-code] The author likely overlooked that `installed-settings.json` is a single static environment artifact and cannot demonstrate that Claude Code actually loads or executes the configured hooks.
- [arkcli] [kimi-k2.7-code] The author likely did not adversarially test the prompt-mode regexes for edge cases (e.g., English "deploy"/"start", indirect execution requests) or probe `fanout_override` / Agent Board bypasses.
- [arkcli] [kimi-k2.7-code] The author likely missed that the self-tests create temporary runs with mock events and do not exercise the real active run or installed hook files.
- [arkcli] [kimi-k2.7-code] The author likely missed the absence of `decisions.md` and a current-turn completion-review receipt, which the new `run_gate` requires before normal closure.
- [claude] **Stop-gate fail-closed path has no cross-model adversarial test.** Every test in the observation script and selftests follows the expected execution flow: write contract → read contract → evaluate. No test simulates a scenario where a different model or concurrent process has corrupted the contract state mid-execution. The fail-closed design assumes the contract is trustworthy; if a crash or partial write leaves a stale `turn_contract.json`, the six-hour expiry is the only safety valve. There's no evidence testing what happens when the contract file is truncated, contains malformed JSON, or has a schema version mismatch at the moment the Stop hook fires.
- [claude] **The observation script constructs its own `assignments.json` and `frontier.md` in a temp directory — it never tests what happens when a real Claude session leaves behind malformed state files from a previous crash.** The `workers.diff` and `anti_drift.diff` show the parser was hardened, but the observation never injects broken state to verify the fail-closed recovery paths.
- [claude] **`runtime_observation.py` line 83 checks `proc.returncode != 0` and raises RuntimeError** — but `turn_contract.py` main() exits 0 even when it emits a `decision: block` JSON (it only exits non-zero on selftest failure or missing args, per `turn_contract.lines-511-end.txt:514-526`). This means the observation script would NOT catch a case where turn_contract.py returns a block decision — it only checks the return code, not the JSON content. This is corrected at the observations level (where `deny()` checks `permissionDecision`), but the `hook()` function itself only validates `returncode`, which could mask unexpected output formats.
- [claude] **The `selftest_all.log` shows `classify_hosts` took 39.8s** — the second-slowest test. This is a recon/OSINT tool irrelevant to this framework-maintenance scope. Its inclusion in the "full regression" claim is correct (it's part of the suite), but its runtime dominates the 76.9s total. If `classify_hosts` had network-dependent failures, the regression suite would report a false failure unrelated to the hook changes.
- [claude] **E-004 lists `peer_review.round2.md` and `disposition.md` as artifacts** — but these are process artifacts, not regression evidence. They document peer review results, not the software's behavior. Including them under E-004 ("Repository regression") conflates two evidence categories. The `selftest_all.log` is the actual regression evidence; the peer review files belong in the review ledger, not under regression.
- [claude] **The "two independent installed-entrypoint executions" claim (evidence.md:28) is same-script, same-Python, same-settings.** The two `summary.json` files have different receipt hashes (confirming separate temp directories and timestamps), but both were generated by the identical `runtime_observation.py` invoking the identical `turn_contract.py` with the identical `installed-settings.json`. This is replication of execution, not independent verification by a different method or observer.

## Context-limit notes
- [arkcli] [kimi-k2.7-code] The review bundle was truncated to 120000 characters, so full artifact contents (especially `installed-settings.json`) may be incomplete.
- [arkcli] [kimi-k2.7-code] `report.md`, `review.md`, `frontier.md`, and `target.md` contents were not supplied as text; only hashes and sizes are available, so full report-parity and claim-integrity checks could not be performed.
- [arkcli] [kimi-k2.7-code] Several artifacts contain Chinese-language code comments; nuanced intent may be lost.
- [arkcli] [kimi-k2.7-code] This is a meta/control-plane run (Xunji framework hooks) rather than a traditional web target, so severity framing focuses on control validity rather than CVE-style impact.
- [arkcli] minimax-m3: parse error; output tail:  fcntl serializes the writes, so race should be prevented at write time. But on Windows fallback (no fcntl), locking is lost. The code acknowledges this with a comment.

11. **Agent Disposition validation**:
    - The check is that merged status requires `(Evidence|Front|Decision|Refuted|Barrier)[:：]` and E/F/D anchors exist in canonical files.
    - The check for "anchors_exist" uses `canonical.upper() for anchor in anchors` - this uppercases both sides, so case doesn't matter. Good.
    - But:
- [arkcli] glm-5.2: parse error; output tail: n response:
    observed.add(job_id)
```
This adds a job_id to the observed set if it appears in the CronList response AND the run name is in the response. But this is a substring check - if the job_id is a substring of another job_id, it could match incorrectly. For example, if job_id "abc" appears in "abcdef" in the response. However, job_ids are typically long enough that this is unlikely.

3. **The `agent_disposition` function** checks if disposition timestamps are after receipt timestamps:

- [claude] I reviewed only the frozen artifacts in this review bundle directory, not the live source files at `.claude/hooks/output_gate.py`, `.claude/hooks/run_gate.py`, or `tools/turn_contract.py` at the repository root. The diffs in this bundle may or may not represent the current state of those files on disk at HEAD (`0447297` per `context.md:4`).
- [claude] The Chinese-language hook messages (输出协议 fail-closed, 收口 fail-closed, 暂停事务) are project-specific idioms. I interpret them through CLAUDE.md's rules, but I may miss nuances in how "Coda" enforcement and "硬门" (hard gate) terminology interact with the new turn-mode exemption paths.
- [claude] The certainty scale reference document (`docs/cognition/README.md`) was not provided in my review bundle. I derive the 0.3/0.5/0.8/1.0 tiers from the task description header and CLAUDE.md's declaration that "only ≥ 0.8 may be reported as confirmed." My certainty-calibration objection may be refined if the canonical scale has subtiers or exceptions I cannot see.
- [claude] `context.md:8-9` says "It repairs round-one PR-001/PR-002/PR-005" — I have `peer_review.round1.md` in the directory listing but did not deeply analyze it; my review focuses on the round-2 state and what remains unresolved after both disposition rounds.