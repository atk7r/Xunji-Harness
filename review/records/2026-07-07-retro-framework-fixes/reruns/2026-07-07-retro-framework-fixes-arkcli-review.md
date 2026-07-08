# Peer Review — 2026-07-07-retro-framework-fixes

_backend: arkcli:kimi-k2.7-code+minimax-m3+glm-5.2 · 2026-07-06T21:53Z_
> 候选, 非裁决。driver 须逐条过证据门: 不盲从(驳工具/语境误报), 不忽视(采纳真盲补)。

## Verdict: WARN

_backend: arkcli:kimi-k2.7-code+minimax-m3+glm-5.2_  
_brain: codex_  
_bundle_hash: a3b5988178b3a92b31e4a88fe8aac9e17898ef44_  
_evidence_index_hash: 558dde58524fd1c0797a61330b28d654f912c13d_  

## Findings
- [WARN] PR-001 Verification claims about the ignored target run directory `runs/oppo_20260707_20260707` cannot be audited from this bundle because no recon, coverage, surface, or replay artifacts from that run are indexed. | Evidence: evidence_index:E-001 (only entry; artifacts: check_run.txt sha1:3e9d2392f2ac4887ccb33c6c561a212d39778cba), review.md:Live replay note | Why: [arkcli:kimi-k2.7-code] The evidence_index contains only local maintenance verification artifacts. Review.md references `check_run` and live replay against an external gitignored run, but those outputs are not hashed or indexed, so the structural/coverage claims for that run are unverifiable.
- [WARN] PR-002 Live replay verification of the target run was abandoned after the guard warned of 90 requests, leaving target-side confirmed findings without replay artifact cross-check. | Evidence: review.md:Live replay note | Why: [arkcli:kimi-k2.7-code] A stopped/limited replay session is not confirmation on its own; any claim that target findings replay cleanly is not evidenced in this bundle.
- [WARN] PR-003 `workers.py` agent-status auto-sync may mark an assignment `done` when its `## Findings` section contains only placeholder or investigatory markers. | Evidence: frontier.md:workers.py:647 `_has_completion_findings` | Why: [arkcli:kimi-k2.7-code] The regex matches `Candidate`, `Result`, `Phenomenon`, etc., so a note such as `Candidate: still investigating` would satisfy the completion detector and flip `assignments.json` to `done`, prematurely closing a front.
- [WARN] PR-004 `coverage_matrix.py` evidence-derived group patterns can over-credit a vulnerability family when an Action/Result line describes a negative finding (e.g., "checked for SQL injection; none observed"). | Evidence: frontier.md:coverage_matrix.py:80 `EVIDENCE_GROUP_PATTERNS`, frontier.md:coverage_matrix.py `_evidence_signal_text` | Why: [arkcli:kimi-k2.7-code] `_evidence_signal_text` keeps Action/Result lines and the `Injection` pattern matches the generic word "injection"; absence language is not excluded, so the matrix could mark Injection as tested.
- [WARN] PR-005 `check_run.py` Guanlan-adapter exception is gated only by unauthenticated `coverage.json` literal fields and could be bypassed by fabricating adapter-shaped records. | Evidence: frontier.md:check_run.py:529 `_is_verified_guanlan_adapter` | Why: [arkcli:kimi-k2.7-code] No provenance signature is checked; a coverage file could set `source: guanlan-adapter(no re-probe)` and populate `assets` with synthetic `source: guanlan` dicts to avoid the 80% subset warning. The selftest only covers the empty-assets case.
- [WARN] PR-006 `evidence_parse.py` shorthand/glob suppression could drop a concrete artifact token if it is immediately followed by an asterisk used as a footnote or emphasis marker. | Evidence: frontier.md:evidence_parse.py:24 `_artifact_tokens` | Why: [arkcli:kimi-k2.7-code] The `next_ch == '*'` branch skips any artifact token whose next character is `*`, which may remove a real filename from the present/missing audit if the author writes `file.txt*` to mark a note.
- [WARN] PR-007 arkcli panel had backend errors; review is partial | Evidence: minimax-m3: parse error; output tail: ange": "invalid"}`? The probe would send "invalid" as-is. That's fine.

**Issue 6: The selftest for the regex `_is_verified_guanlan_adapter`**
```python
if cov.get("source") != "guanlan-adapter(no re-probe)" or cov.get("partial") is not False:
    return False
```
What if the source string is updated? The check is string-exact. Brittle but acceptable.

**Issue 7: The report.md doesn't include any explicit verification of the changes against real targets**
The selftest_all passed 45/45 but that's; glm-5.2: parse error; output tail: but discards the result, then manually overwrites and re-checks. The test passes but for the wrong reason potentially.

4. **Guanlan adapter exception is too permissive**: `_is_verified_guanlan_adapter` checks for `source == "guanlan-adapter(no re-probe)"` but this string could be spoofed in coverage.json. The test `cc_spoof_adapter` checks for empty assets list, but a real spoof with fake assets would pass.

5. **No evidence of the actual run being tested**: The review.md says the run directory | Why: At least one arkcli reviewer failed, so PASS only means the completed panel members found no blocker.

## Blind-spot check
- [kimi-k2.7-code] The workers status-sync selftests do not cover `## Findings` sections containing `Candidate: pending`, `Result: TBC`, or similar investigatory placeholders.
- [kimi-k2.7-code] `coverage_matrix.py` selftests do not exercise negative Result lines or refuted families mixed with confirmed ones.
- [kimi-k2.7-code] No artifact hash or excerpt is provided for `evidence/check_run.txt`, so the claim that `check_run` passed on the external run cannot be independently verified beyond its existence in E-001.
- [kimi-k2.7-code] The external run directory is gitignored; this bundle cannot evaluate coverage ledger completeness, false positives, or shallow closure against actual target findings.
- [kimi-k2.7-code] `probe.py --range` is tested only against a local HTTP server; no target-derived replay artifact validates its behavior behind WAFs, CDNs, or rate-limiters.
- [kimi-k2.7-code] `check_knowledge.py` selftest creates temp directories but never removes them; minor local hygiene blind spot.

## Context-limit notes
- [kimi-k2.7-code] Bundle excerpts do not include full artifact file contents, so artifact cross-check for E-001 relies on existence/size/sha1 metadata rather than line-by-line parsing.
- [kimi-k2.7-code] Chinese-language headings and local conventions (e.g., 非确认发现) are referenced in code comments but not exercised in the provided diff; my assessment of their coverage implications is limited.
- minimax-m3: parse error; output tail: ange": "invalid"}`? The probe would send "invalid" as-is. That's fine.

**Issue 6: The selftest for the regex `_is_verified_guanlan_adapter`**
```python
if cov.get("source") != "guanlan-adapter(no re-probe)" or cov.get("partial") is not False:
    return False
```
What if the source string is updated? The check is string-exact. Brittle but acceptable.

**Issue 7: The report.md doesn't include any explicit verification of the changes against real targets**
The selftest_all passed 45/45 but that's
- glm-5.2: parse error; output tail: but discards the result, then manually overwrites and re-checks. The test passes but for the wrong reason potentially.

4. **Guanlan adapter exception is too permissive**: `_is_verified_guanlan_adapter` checks for `source == "guanlan-adapter(no re-probe)"` but this string could be spoofed in coverage.json. The test `cc_spoof_adapter` checks for empty assets list, but a real spoof with fake assets would pass.

5. **No evidence of the actual run being tested**: The review.md says the run directory