# Peer Review — docs-scope

_backend: arkcli:kimi-k2.7-code+glm-5.2 · 2026-07-11T00:42Z_
> 候选, 非裁决。driver 须逐条过证据门: 不盲从(驳工具/语境误报), 不忽视(采纳真盲补)。

## Verdict: WARN

_backend: arkcli:kimi-k2.7-code+glm-5.2_  
_brain: codex_  
_bundle_hash: 8787bc6e5db6a6202432f06cc681ed4c1a5001d2_  
_evidence_index_hash: 43699a337c9d7985731163027f3442b9d64bd2da_  

## Findings
- [WARN] PR-001 E-001 documentation-parity finding should not be read as runtime enforcement parity; enforcement truth is not evidenced in this bundle. | Evidence: installed-runtime-manifest.json, report.md:1-10, evidence_index:E-001 | Why: [arkcli:kimi-k2.7-code] The bundle contains documentation diffs, a passing stale-reference audit, and a manifest that hashes but does not display enforcement code. No source or transcript-backed runtime traces are included, so the gap between documented contract and hook behavior remains unverified.
- [WARN] PR-002 Final post-change file contents are not independently reviewable because only diffs are present in the evidence bundle. | Evidence: root_rules.diff, primary_skills.diff, lifecycle_templates.diff, workflow_core.diff, workflow_reference.diff, agent_role_templates.diff | Why: [arkcli:kimi-k2.7-code] Diffs prove that changes occurred but do not let a reviewer verify that final files contain only the intended contract text. Integrity hashes exist, yet content review is impossible from this bundle alone.
- [WARN] PR-003 stale_reference_audit.json only detects six mapped historical shortcut patterns and cannot catch novel reformulations of the same failures. | Evidence: stale_reference_audit.json, report.md:1-10 | Why: [arkcli:kimi-k2.7-code] The audit is explicitly a regression for known patterns, not a general language-consistency checker. The report acknowledges this limitation, but it is a real blind spot for drift detection.
- [WARN] PR-004 arkcli panel had backend errors; review is partial | Evidence: glm-5.2: parse error; output tail:  source verification** - historical_failures.md makes specific claims about what `turn_contract.py`, `output_gate.py`, `check_run.py`, `xunji_statusline.py` do. The installed-runtime-manifest.json shows their hashes and sizes but not their contents. The selftests pass, but the selftest results don't prove the specific behavioral claims.

3. **Trace anchors unverified** - historical_failures.md cites specific line numbers in source files that aren't in the evidence bundle. These can't be verified | Why: At least one arkcli reviewer failed, so PASS only means the completed panel members found no blocker.

## Blind-spot check
- [kimi-k2.7-code] Hook source files and live runtime traces are absent; enforcement parity is assumed from hashes, not evidenced.
- [kimi-k2.7-code] Historical source excerpts referenced by line number in historical_failures.md are not supplied for independent verification.
- [kimi-k2.7-code] No artifact confirms review/independent-reviewer.md's final text is solely a deprecation pointer.
- [kimi-k2.7-code] minimax-m3 removal is consistent across diffs but not verified against actual arkcli backend configuration.

## Context-limit notes
- glm-5.2: parse error; output tail:  source verification** - historical_failures.md makes specific claims about what `turn_contract.py`, `output_gate.py`, `check_run.py`, `xunji_statusline.py` do. The installed-runtime-manifest.json shows their hashes and sizes but not their contents. The selftests pass, but the selftest results don't prove the specific behavioral claims.

3. **Trace anchors unverified** - historical_failures.md cites specific line numbers in source files that aren't in the evidence bundle. These can't be verified