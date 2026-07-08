# Independent Review: output_gate.py (Stop Hook — Output Drift Gate)

_backend: claude (manual review) · 2026-06-25_
> 对 `.claude/hooks/output_gate.py` 的安全关键代码独立评审，依据 CLAUDE.md 第134行和 `review/independent-reviewer.md` 的复审标准。

## Scope

评审对象：`.claude/hooks/output_gate.py`（341行，commit `a8b4598` 创建，后续多次演进）

评审重点：
- Stop hook 逻辑是否正确（FAIL-OPEN 设计）
- Driver delegation drift 检测是否有效
- 是否存在绕过或误阻断风险
- 与 run_gate.py / safety_gate.py 的协调是否正确

## Verdict: APPROVED WITH FINDINGS

代码整体设计合理，FAIL-OPEN 架构正确，与 run_gate.py / anti_drift.py 的协调管线清晰。
发现 2 个 WARN 和 3 个 INFO 级别的问题，均不构成安全阻断，建议后续迭代修复。

---

## Findings

### [WARN] W1 — Race window: run_gate and output_gate both write drift_block.json in the same Stop event

**Evidence**: `output_gate.py:122-137` (`write_drift_block`) and `run_gate.py:194-205` (`_mark_drift_block_processed`) both write to `.claude/drift_block.json` via atomic rename (`.tmp` → final). Both are Stop hooks triggered by the same event.

**Why it matters**: If both hooks execute concurrently or in reverse order within the same Stop event, the following race can occur:
1. Turn N: `output_gate` detects drift, writes `drift_block.json` (no `_run_gate_processed` flag)
2. Turn N (same event): `run_gate` reads it, marks `_run_gate_processed=true`, blocks
3. Turn N+1: `output_gate` detects drift AGAIN, **overwrites** `drift_block.json` (no `_run_gate_processed` flag)
4. Turn N+1 (same event): `run_gate` reads it, sees NO `_run_gate_processed`, treats as fresh block, blocks again — but `stop_active=true`, so it downgrades to notify

The last-write-wins behavior in step 3 means `output_gate`'s `write_drift_block()` erases `run_gate`'s `_run_gate_processed` marker. In practice this is self-correcting (the anti-loop at `run_gate.py:269-270` catches it), but the coordination is implicit — the two hooks share mutable state on the filesystem with no explicit ordering contract.

**Recommendation**: Consider having `output_gate` read-modify-write (preserve `_run_gate_processed` and `_prompt_injected_at` flags) rather than fully replacing the block file, OR document the expected hook execution order explicitly.

---

### [WARN] W2 — False positive risk: legitimate evidence text with trailing question marks

**Evidence**: `output_gate.py:61-66` (`_tail_has_question`) matches any `?` or `？` in the last 300 characters. `output_gate.py:174` flags `protocol_violation` when `tail_has_question` AND `tail_missing_close`.

**Why it matters**: A response that includes a log excerpt, code sample, or HTTP response containing a `?` in its tail will trigger `protocol_violation` if the proper close formula (`下一行动:` or `BLOCKED:`) is not in the last 500 characters. Example:

```
下一行动: F-010 SQL injection verification.

Detailed evidence:
GET /api?id=1' OR '1'='1 HTTP/1.1
Response: "error in your SQL syntax?"
```

Here `_tail_has_question` = True (trailing `?` in evidence), `_tail_has_proper_close` = False (the close "下一行动:" is in the middle, not in the 500-char tail), so `protocol_violation` fires. The driver did include a proper close — it's just not at the very end.

**Mitigation in current code**: The `protocol_violation` flag only triggers a `systemMessage` warning on first offense (drift_count=1). It escalates to hard block only on the second consecutive violation. So a single false positive would produce a warning, not a block — which is acceptable for a heuristic detector.

**Recommendation**: Consider extending `_tail_has_proper_close` to search the full response (not just the 500-char tail) for the close formula, and only flag `protocol_violation` if no proper close exists ANYWHERE in the message. This trades a small amount of protection (delegation phrases near a stale close) for significantly fewer false positives.

---

### [INFO] I1 — Dead code: identical branches in escalation logic

**Evidence**: `output_gate.py:212-217`

```python
if drift_flags:
    # REREAD was offered but driver re-violated -> escalate
    if reread_pending:
        drift_count += 1
    else:
        drift_count += 1
```

Both the `reread_pending=True` and `reread_pending=False` branches execute `drift_count += 1`. The comment says "REREAD was offered but driver re-violated → escalate" implying more aggressive escalation (e.g., `+= 2` or setting a different flag), but the code does not differentiate.

**Impact**: No functional bug — the counter still increments correctly. The dead branch is a code quality issue that may mislead future readers into thinking there is differentiated escalation.

**Recommendation**: Either implement differentiated escalation (e.g., `+= 2` when `reread_pending`) or collapse to a single `drift_count += 1` with an updated comment.

---

### [INFO] I2 — Finite drift pattern list allows adversarial bypass

**Evidence**: `output_gate.py:38-42` (inline fallback) and `tools/anti_drift.py:61-65` (canonical source) define an explicit list of 11 drift patterns.

**Why it matters**: A driver (human or AI) that is aware of the detection patterns can trivially bypass detection by using alternative phrasing not in the list (e.g., "您希望我如何推进" instead of "是否继续", "请告知方向" instead of "请指示下一步"). The current pattern list covers the most common delegation phrases observed in practice, but is not exhaustive.

**Impact**: Low. The gate is not a security boundary against adversarial humans — it's a drift detector for an AI driver that may unconsciously slip into delegation patterns. The finite list is an acceptable trade-off between detection coverage and false-positive rate.

**Recommendation**: No action required. Document this as a known limitation (the gate detects common patterns, not all possible delegation language).

---

### [INFO] I3 — frontier_stale detection has one-turn delay on first occurrence

**Evidence**: `output_gate.py:194-206`

```python
if frontier.exists():
    frontier_mtime = frontier.stat().st_mtime
    if time.time() - frontier_mtime > 900:
        last_alert = prev_state.get("frontier_alerted_at", 0)
        if time.time() - last_alert > 600:
            drift_flags.append("frontier_stale")
```

On first detection, `last_alert` defaults to `0` (integer, not float), so `time.time() - 0 > 600` is always True, and the flag fires immediately. This is correct. However, the suppression window (600 seconds) means that after the initial alert, if the driver hasn't updated `frontier.md` within the next 10 minutes, the flag re-fires. The 15-minute staleness threshold + 10-minute re-alert cooldown creates a reasonable cadence. No issue here — documenting for reviewer awareness.

---

## Architecture Assessment

### FAIL-OPEN Design: PASS

| Component | Mechanism | Verdict |
|---|---|---|
| `main()` outer try/except | `except Exception: sys.exit(0)` (line 261-263) | Correct — any unhandled exception silently passes |
| Event parsing | `except Exception: sys.exit(0)` (line 148-149) | Correct — unreadable stdin = pass |
| `write_drift_block()` | Internal try/except pass (line 132-137) | Correct — write failure = silent pass |
| `load_session_state()` | Returns `{}` on missing/corrupt (line 92-97) | Correct |
| `save_session_state()` | try/except pass (line 104-108) | Correct |
| Import of anti_drift | Inline fallback patterns if import fails (line 36-45) | Correct |

**Conclusion**: The gate never blocks the session due to its own failure. Every I/O and parse operation has a safe fallback. This is the correct design for a drift detector.

### Coordination with run_gate.py: PASS

The three-component pipeline is well-architected:

```
output_gate.py (detect) --> drift_block.json (signal) --> run_gate.py Phase 3 (enforce)
                                                      --> anti_drift.py (context inject)
```

**Cross-run contamination**: Both `run_gate.py` (`_check_drift_block`, line 167-169) and `anti_drift.py` (`_check_hard_block`, line 261-264) implement cross-run guards: if the block's `run` field doesn't match the active run, the block is silently ignored. This prevents a stale block from run A from blocking work on run B.

**TTL-based cleanup**: `DRIFT_BLOCK_TTL_SEC = 600` (10 minutes) — stale blocks are auto-cleared by `run_gate.py` (line 160-163) and `anti_drift.py` (line 256-259).

**Anti-loop**: `run_gate.py` tracks `_run_gate_processed` and `stop_hook_active` to prevent infinite block→continue→block loops (line 266-284). First offense = block, subsequent = notify only.

### Coordination with safety_gate.py: PASS (No Direct Coordination Required)

`safety_gate.py` is a PreToolUse hook that blocks destructive actions (rm -rf, mkfs, etc.). `output_gate.py` is a Stop hook that detects conversational drift. They operate on different events, different threat models, and different failure modes — no coordination is needed between them.

### Detection Logic: ADEQUATE

| Detection | Mechanism | False Positive Risk | False Negative Risk |
|---|---|---|---|
| Drift phrases | Pattern list match in full message | Low (patterns are distinctive) | Medium (finite list, see I2) |
| Tail drift | Patterns in last 500 chars only | Very low | Low (delegation in middle but not end = intentional) |
| Tail question | `?` / `？` / Chinese question particles | Medium (evidence text, see W2) | Low (most delegation ends with ?) |
| Option list | >=2 numbered lines (1. / 1) / 1、) | Low (legitimate numbered lists are rare in protocol responses) | Low |
| Frontier stale | mtime > 15 min | Low | None (objective check) |
| Protocol violation | (tail_hits OR tail_question) AND missing close | Medium (see W2) | Low (requires both signal AND missing close) |

### Zero-width Character Handling: PASS

`_strip_invisible()` strips common invisible Unicode characters (zero-width space `​`, zero-width non-joiner `‌`, zero-width joiner `‍`, word joiner `⁠`, byte order mark `﻿`, non-breaking space ` `). This prevents bypass by inserting invisible characters into drift phrases. The regex covers the most common invisible codepoints.

### Selftest Coverage: PASS

The `_selftest()` function (lines 266-337) covers:
- `detect_drift()` — empty, clean, BLOCKED, Chinese patterns, English patterns
- `DRIFT_PATTERNS` loading — verifies non-empty
- Tail context check — pattern deep in context not in tail
- `_tail_has_question()` — positive, negative, empty
- `_tail_has_proper_close()` — both formats, trailing whitespace, prose, question, empty, mid-sentence
- `detect_option_list()` — detected, with paren, with Chinese, single only, none
- Zero-width char handling — strip, proper close, drift detect, option list
- `_strip_invisible()` — removes ZWSP, no-op on clean
- `session_state` read/write roundtrip
- `_valid_ts()` — valid, negative, future, zero, non-numeric

Total: 33 checks. All must pass for exit code 0.

---

## Summary Table

| # | Level | Category | Description | Recommendation |
|---|---|---|---|---|
| W1 | WARN | Coordination | Race window on drift_block.json between output_gate and run_gate | Read-modify-write or document ordering |
| W2 | WARN | Detection | False positive when evidence text contains ? in tail | Extend close detection to full message |
| I1 | INFO | Code quality | Dead code in escalation logic (identical branches) | Collapse or implement differentiated escalation |
| I2 | INFO | Detection | Finite pattern list allows adversarial bypass | Document as known limitation |
| I3 | INFO | Detection | frontier_stale first-occurrence timing | No action (correct behavior, documented for awareness) |

---

## Final Verdict

**APPROVED** — No safety-critical defects found. The FAIL-OPEN architecture is correct, the coordination pipeline with run_gate.py and anti_drift.py is well-designed, and the detection logic is adequate for its purpose. The two WARN findings (race window, false-positive risk) and three INFO findings (dead code, finite pattern list, timing note) are non-blocking and can be addressed in follow-up iterations.

The most significant finding is W2 (false positive from evidence text), which could cause spurious `protocol_violation` warnings when a driver includes technical evidence with question marks at the end of a response. In practice, the first-offense warning-only behavior (not a hard block) makes this tolerable.
