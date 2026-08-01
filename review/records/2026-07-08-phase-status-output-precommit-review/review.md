# Peer Review Panel — 2026-07-08-phase-status-output-precommit-review

_backend: panel:arkcli+claude · 2026-07-08T06:34Z_
> 候选, 非裁决。driver 须逐条过证据门。

## Verdict: WARN

_backend: panel:arkcli+claude_  
_brain: codex_  
_bundle_hash: 289aea4cd3b391e278b1826db45a3efa3724bd30_  
_evidence_index_hash: 0a40eb5775f604f5b6cf485fbd24925fd1e42c82_  

## Findings
- [WARN] PR-001 Report claims downstream-parser risk is addressed, but the scan only checked for consumers of English Markdown prose in docs/tools, not JSON consumers of the canonical `state/loop_state.json` `phase` field, which changed from 'Driver'/'Closure' to 'Root Orchestrator'/'Report' | Evidence: `evidence/patches/tools__loop_state_py.patch.txt`, `evidence/consumer-scan.txt` | Why: [panel:arkcli] [arkcli:kimi-k2.7-code] The consumer-scan artifact greps references to the Markdown files, not runtime string consumers; the loop_state.py patch alters the machine-readable JSON phase value, so closing the prior parser WARN is overreached for machine consumers.
- [WARN] PR-002 No end-to-end verification exists that the Claude Code `/loop` slash command and the new phase-marker/journal flow behave correctly in an actual loop turn; only unit selftests cover the new code | Evidence: `evidence/test-log.txt`, `evidence/patches/docs__templates__loop_prompt_md.patch.txt` | Why: [panel:arkcli] [arkcli:kimi-k2.7-code] Journal/event-ordering bugs (e.g., phase_start without matching phase_end under interrupts) only surface in real loop semantics, and the report itself acknowledges `/loop` e2e testing as a documented limitation.
- [WARN] PR-003 arkcli panel had backend errors; review is partial | Evidence: minimax-m3: parse error; output tail: directory is rejected" - YES
- "evidence-only directory is rejected" - YES (this works because evidence.md isn't in the list, but `evidence/` is)

Wait, looking at the test:
```python
evidence_only_dir = d / "evidence_only"
(evidence_only_dir / "evidence").mkdir(parents=True)
rejected_evidence_only_dir = False
try:
    append_event(evidence_only_dir, "cycle_start")
except ValueError:
    rejected_evidence_only_dir = True
```

This creates an `evidence_only_dir/evidence/` subdirectory, then tries; glm-5.2: parse error; output tail: file might have this import. The diff only shows a portion of the file. Since the test log claims the selftest passed, and the selftest calls `_read_json`, either:
1. `_json_mod` is defined somewhere not shown in the diff, or
2. The test log is wrong

I can't be 100% certain from the diff alone. But this is worth flagging as something to verify.

Actually, looking more carefully at the loop_bootstrap.py patch, the original file probably already had `import json` and the new code uses `_json_mod` | Why: [panel:arkcli] At least one arkcli reviewer failed, so PASS only means the completed panel members found no blocker.

## Blind-spot check
- [arkcli] [kimi-k2.7-code] Downstream consumers of `state/loop_state.json` `phase` and of `controller.shadow.json` state/action keys were not exhaustively searched.
- [arkcli] [kimi-k2.7-code] Long-running `/loop` sessions could append many events to `state/loop_journal.jsonl`; there is no rotation, truncation, or size-budget check.
- [arkcli] [kimi-k2.7-code] Chinese output has not been verified on terminals with non-UTF-8 or no-color environments beyond unit assertions.
- [arkcli] [kimi-k2.7-code] Other model-specific skill directories (e.g., `.agents/skills`) were not modified, but the review did not scan them for stale references to 'Driver'/'Closure' or per-run `loop_prompt.md`.
- [claude] **Phase-name consistency across the full codebase**: The consumer-scan.txt reveals that the old `"Driver"` / `"Closure"` phase names were used in at least `docs/ANTI-DRIFT-DECAY.md` (line 378) and potentially in `tools/cross_run.py` (which prints `e['phase']` from loop_state data — it will now print "Root Orchestrator" instead of "Driver" from the JSON, but cross_run.py itself isn't patched, so if it ever hardcodes a string match, it would silently break). The cross_run.py reference at lines 516/580 appears benign (just printing), but a grep of the full repo for "Driver" as a phase-related string would have caught the stale ANTI-DRIFT-DECAY reference.
- [claude] **The `plan` journal event in the loop protocol has ambiguous semantics**: Looking at `evidence/patches/docs__templates__loop_prompt_md.patch.txt`, the `plan` event is described as "目标=<F-XXX/控制面动作>; 原因=<简短原因>" — it records what was chosen. But the same protocol later records `action` events with "即将执行 <工具/动作>". These could overlap — plan says "I will target F-001" and action says "I will run probe.py". The distinction is useful but the protocol doesn't document it clearly. A resume could misinterpret a `plan` event as meaning the action was already executed.
- [claude] **`loop_journal.py` append_event creates `state/` directory with `parents=True`**: At line 119, `path.parent.mkdir(parents=True, exist_ok=True)` — if the run directory exists but `state/` doesn't (unlikely in practice since tools like `setup_run.py` create it), this would create the directory silently. This is fine in practice but contradicts the explicit scope check (`_looks_like_scope_dir`) that runs just before — a directory with only marker files but no `state/` subdirectory would pass the scope check and then silently create state/. This is a very minor edge case.
- [claude] **The `review.md` file says "Pending refreshed peer_review.py run"** — this review IS the refreshed peer_review run, but the file wasn't updated. The claim integrity of `review.md` itself is stale at review-time (though this is expected — the review output is what updates it).

## Context-limit notes
- [arkcli] [kimi-k2.7-code] Review is based on patch excerpts and test-log excerpt in the review bundle, not a full line-by-line read of every modified file.
- [arkcli] [kimi-k2.7-code] Phase/status Chinese translations appear technically consistent; subtle operator-facing nuance is not fully assessable without native-language review.
- [arkcli] [kimi-k2.7-code] The proprietary Claude Code `/loop` command cannot be exercised in this read-only review environment.
- [arkcli] minimax-m3: parse error; output tail: directory is rejected" - YES
- "evidence-only directory is rejected" - YES (this works because evidence.md isn't in the list, but `evidence/` is)

Wait, looking at the test:
```python
evidence_only_dir = d / "evidence_only"
(evidence_only_dir / "evidence").mkdir(parents=True)
rejected_evidence_only_dir = False
try:
    append_event(evidence_only_dir, "cycle_start")
except ValueError:
    rejected_evidence_only_dir = True
```

This creates an `evidence_only_dir/evidence/` subdirectory, then tries
- [arkcli] glm-5.2: parse error; output tail: file might have this import. The diff only shows a portion of the file. Since the test log claims the selftest passed, and the selftest calls `_read_json`, either:
1. `_json_mod` is defined somewhere not shown in the diff, or
2. The test log is wrong

I can't be 100% certain from the diff alone. But this is worth flagging as something to verify.

Actually, looking more carefully at the loop_bootstrap.py patch, the original file probably already had `import json` and the new code uses `_json_mod`
- [claude] I cannot verify the actual `git diff --check` output on disk — the test-log.txt records that it passed (exit code 0), and I trust the artifact hash (sha1: `9ae1040254bc19e52e5ee28bd702e97c56578b88`) matches. If the diff contained whitespace errors, `git diff --check` would have caught them.
- [claude] The full 52-suite `selftest_all.py` output is not visible to me — I can only see the representative excerpts in test-log.txt. The claim "52 passed, 0 failed (46.0s total)" is accepted as recorded evidence with matching sha1.
- [claude] I have no insight into whether Claude Code's `/loop` slash-command parser would correctly interpret `/loop runs/<dir>` with the new fixed-template protocol vs the old copy/paste approach. This is the documented end-to-end limitation and I accept it as stated.
- [claude] The `.replay.json` artifact format doesn't apply here (this is a code review, not a pentest run), so the artifact cross-check rubric item is adapted to checking patch file hashes against the evidence_index.