# Peer Review Panel — 2026-07-10-claude-flow-enforcement

_backend: panel:arkcli+claude · 2026-07-09T21:51Z_
> 候选, 非裁决。driver 须逐条过证据门。

## Verdict: WARN

_backend: panel:arkcli+claude_  
_brain: codex_  
_bundle_hash: 17790a248822a54d0923af526c9eed23638c151f_  
_evidence_index_hash: 22c2420a9b4b761ecc9c5987fcffb74041db45f7_  

## Findings
- [WARN] PR-001 run_gate.py independent-review fallback is weaker than check_run.py's canonical gate | Evidence: run_gate.diff:function _has_completed_independent_review fallback regex, check_run.diff:function has_completed_independent_review implementation, selftest_all.log:run_gate test suite passed | Why: [panel:arkcli] [arkcli:kimi-k2.7-code] run_gate.py's fallback accepts a heading plus any Verdict line anywhere in review.md, while check_run.py requires non-placeholder identity and block-scoped verdict. This creates an inconsistent two-tier gate.
- [WARN] PR-002 Aggregate diff provenance is incomplete in the external bundle | Evidence: diff_manifest.md:reviewed.diff aggregate SHA1 c01e2ad6e35044cca33d7ffe67dbf086c888e027, evidence_index:E-004:artifacts list lacks reviewed.diff | Why: [panel:arkcli] [arkcli:kimi-k2.7-code] The manifest references an aggregate diff that is not supplied; external reviewers cannot verify the aggregate SHA1 from component diffs alone.
- [WARN] PR-003 disposition.md is referenced in report.md but not present in the bundle | Evidence: report.md:last maintenance assertion, evidence_index:files list | Why: [panel:arkcli] [arkcli:kimi-k2.7-code] The report makes a factual claim about a file that is not included in the supplied audit trail, so the claim cannot be arbitrated.
- [WARN] PR-004 Hook binding evidence is selftest-only with no live-run integration artifact | Evidence: E-003:selftest_all.log 54 passed, 0 failed, report.md:E-001 maintenance assertion | Why: [panel:arkcli] [arkcli:kimi-k2.7-code] Unit/selftest logs validate code modules individually but do not demonstrate end-to-end Stop-hook binding during an actual run closure.
- [WARN] PR-005 arkcli panel had backend errors; review is partial | Evidence: minimax-m3: parse error; output tail: -reading: "the author is Claude" - the author of the framework changes. The report's "Author: Codex" claim is about who wrote the report.md. The meta-prompt says the author (of the changes) is Claude. So the report author is Codex reviewing Claude's changes. That makes sense.

**Key blind spots to report**:

1. **E-003 selftest is not independent evidence of correctness** - it's a self-test by the same code that was changed. The tests pass because they were written/updated to match the new code,; glm-5.2: parse error; output tail: id"
process_anchor = re.search(...)
if not coda_error and active and not cited_fronts and not process_anchor:
    coda_error = "..."
if not coda_error:
    return ""
```

So if `active` is empty (no active fronts found in fallback), and the Coda is well-formed but references an F-id, it would be rejected with "当前没有 active 前沿". But if the Coda doesn't reference an F-id and has no process_anchor, and `active` is empty, then `not coda_error and active and not cited_fronts and not process_anchor` is | Why: [panel:arkcli] At least one arkcli reviewer failed, so PASS only means the completed panel members found no blocker.

## Blind-spot check
- [arkcli] [kimi-k2.7-code] Author likely missed the divergence between run_gate.py and check_run.py independent-review validation.
- [arkcli] [kimi-k2.7-code] Author likely assumed component diffs plus manifest prove aggregate provenance without providing the aggregate or recomputation path.
- [arkcli] [kimi-k2.7-code] Author likely treated the selftest log as sufficient proof of hook binding without a live-run trace.
- [arkcli] [kimi-k2.7-code] Author referenced disposition.md as part of the audit trail but did not include it.
- [claude] **The selftest pass/fail threshold for `_retro_framework_items` with free-form body**: When no `Problem:` fields or numbered/heading structure is detected, `_retro_framework_items` returns `[body]` — lumping the entire free-form section into one item (check_run.diff:118-121). This means one `Status: fixed` line discharges every issue in a free-form retrospective. The disposition.md:49-51 documents this as "one unstructured issue remains supported for legacy compatibility." However, the template in docs.diff now explictly warns against this pattern — the gap is that `check_run.py` cannot enforce template compliance, only validate what's written. A legacy retrospective with 5 framework issues and one `Status: fixed` at the bottom would pass the gate. This is a documented tradeoff, not a defect, but the weakness should be explicit in the report rather than implied.
- [claude] **`_cookie_expired` returns safely on parse failure**: probe.diff:20-28 catches `TypeError, ValueError, OverflowError` and returns `False` (not expired). This is the safe default (don't delete cookies on parse errors). But it also means a server sending `Expires: 0` (invalid HTTP-date) would have cookies that SHOULD be expired treated as valid. This is correct behavior per the HTTP spec (RFC 7231 §7.1.1.1: invalid dates should be treated as "already expired" for new cookies, but for existing Set-Cookie validation the behavior is less clear). The solution matches browser behavior — browsers ignore malformed Expires values rather than deleting the cookie.
- [claude] **The `output_gate.py` selftest monkeypatches `globals()` to test fallback paths**: output_gate.diff:286-316 temporarily sets `globals()["_loop_state"]` to `None` and `globals()["_protocol_state"]` to a lambda, then restores in `finally`. This is correct for selftest isolation. However, if the test fails between the `try` and `finally` (e.g., assertion error), the globals are still restored. This is safe. ✓
- [claude] **No adversarial test for fuzzy Coda matching**: The `vague_only` set and `vague_phrase` regex cover specific documented bypass patterns. Chinese has many paraphrases not in the deny-list (e.g., "按计划推进", "沿当前路径深挖", "依照原定方向继续"). The layered defense (vague check → concrete_anchor → action verb → multi-action) means a purely vague Coda without a concrete anchor is still rejected. This is a well-designed defense-in-depth approach.
- [claude] **The `docs.diff` changes to `review.md` template say "不能由 driver 自评冒充" but don't define what constitutes "自评"**: The template instructs that a fresh-context reviewer can manually fill the review, but "不能由 driver 自评冒充" (cannot be impersonated by the driver's self-review). The check_run.py code enforces this by requiring non-blank, non-placeholder Reviewer/Backend identifiers and rejecting generic fresh-context headings that lack backend metadata. However, there's no mechanical way to verify that the person filling in `Reviewer: independent-claude-instance` is actually a different Claude instance. This is inherently unenforceable at the code level — it relies on operator audit of the review record.
- [claude] **The selftest_all.log was run on Python 3.14 on macOS arm64**: probe.py's cookie-jar permission test (`os.chmod(tmp_name, 0o600)`) and file-atomic-replace behavior could differ on Linux (different umask defaults) or Windows (no POSIX permissions). The test framework only validates the deployment platform, which is acceptable.

## Context-limit notes
- [arkcli] minimax-m3: parse error; output tail: -reading: "the author is Claude" - the author of the framework changes. The report's "Author: Codex" claim is about who wrote the report.md. The meta-prompt says the author (of the changes) is Claude. So the report author is Codex reviewing Claude's changes. That makes sense.

**Key blind spots to report**:

1. **E-003 selftest is not independent evidence of correctness** - it's a self-test by the same code that was changed. The tests pass because they were written/updated to match the new code,
- [arkcli] glm-5.2: parse error; output tail: id"
process_anchor = re.search(...)
if not coda_error and active and not cited_fronts and not process_anchor:
    coda_error = "..."
if not coda_error:
    return ""
```

So if `active` is empty (no active fronts found in fallback), and the Coda is well-formed but references an F-id, it would be rejected with "当前没有 active 前沿". But if the Coda doesn't reference an F-id and has no process_anchor, and `active` is empty, then `not coda_error and active and not cited_fronts and not process_anchor` is
- [claude] I reviewed the complete diffs as provided. The aggregate `reviewed.diff` (98,785 bytes, SHA1 `c01e2ad6...`) was not in the egress bundle but its component diffs were all present and complete. The SHA1 claim is taken as stated.
- [claude] Chinese-language regex patterns in `_turn_coda` (vague phrases, multi-action conjunctions, action verbs) are syntactically well-formed based on my reading. The semantic coverage of the deny-list is inherently incomplete for a morphologically rich language, but the layered approach provides defense-in-depth.
- [claude] The `loop_state.py` module is not in the diff scope and is treated as a black-box dependency. Both hooks depend on it with documented fallback paths when unavailable.
- [claude] The `peer_review.round6.md` shows the arkcli panel members (minimax-m3, glm-5.2) continue to have parse errors, making that round's panel review effectively single-model (kimi-k2.7-code + Claude reviewer). My review as a different model family adds heterogeneity.
- [claude] I cannot independently recompute SHA1 hashes without shell access. The evidence_index SHA1 claims are accepted as stated in the bundle; file contents were verified by reading actual files.