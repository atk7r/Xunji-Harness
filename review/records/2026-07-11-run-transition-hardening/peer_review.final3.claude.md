# Peer Review — 2026-07-11-run-transition-hardening

_backend: claude:code-cli · 2026-07-11T02:38Z_
> 候选, 非裁决。driver 须逐条过证据门: 不盲从(驳工具/语境误报), 不忽视(采纳真盲补)。

## Verdict: WARN

_backend: claude:code-cli_  
_brain: codex_  
_bundle_hash: 91c52fdaf74f05fbc3c95903b9aa05608f3c8232_  
_evidence_index_hash: 6164b0f7ec60bd2733052809d432a9461ef7bc39_  

## Findings
- [WARN] PR-001 review.md references non-existent peer_review.final3.claude.md | Evidence: review.md:6 | Why: review.md claims See peer_review.final3.claude.md for the final refreshed fingerprint but Glob confirms no final3 file exists. This erodes audit trail integrity.
- [WARN] PR-002 Evidence maturity field inconsistent between evidence.md (verified) and review bundle (candidate) | Evidence: evidence.md:5,15,25,35, review bundle evidence_index.entries[].maturity | Why: All four entries show Maturity: verified in evidence.md but maturity: candidate in the review bundle JSON. Consumers of the bundle see stale/contradictory maturity metadata.
- [WARN] PR-003 _lifecycle_target_name argument parser is coupled to setup_run.py flag schema and not forward-compatible | Evidence: evidence/transition-core.diff:340-375 | Why: The hand-rolled positional parser only knows --date and --target. A new value-consuming flag added to setup_run.py would silently break claim binding without any test catching it.
- [WARN] PR-004 run_gate stop_hook_active early exit swallows all gate evaluations and drift notifications | Evidence: evidence/stop-hooks.diff:220-226 | Why: The early exit at line 226 fires before active_run resolution and Phase 3 drift checks. If a transient issue caused the first block and was resolved before retry, the retry silently passes without informing the operator or re-evaluating the now-resolved state.
- [WARN] PR-005 No integration test for the full pending-contract-to-pointer chain as a single subprocess flow | Evidence: evidence/transition-core.diff:819-941 | Why: Each component is tested in isolation (separate subprocess invocations) but no single test drives the complete hook-to-tool-to-hook chain. The contract between hook evaluation and tool runtime is untested at the integration level.
- [WARN] PR-006 _control_invocation suffix stripping asymmetry: only one redirect suffix is stripped despite claiming to fold benign fd redirections | Evidence: evidence/transition-core.diff:523-526 | Why: The break after the first match means only one redirect suffix is handled. 2>&1 2>/dev/null is rejected (not stripped) while 2>/dev/null 2>&1 is accepted. This asymmetry is flagged in every review round and consistently dismissed, but it remains surprising to future maintainers.

## Blind-spot check
- The review.md never updated after the final2 review — the bundle hash in final2.claude.md (6952cbb4e...) differs from the review bundles own sha1 (91c52fda...), meaning review.md references a different evidence snapshot than what the reviewer saw
- _active_protocol_fronts function in output_gate has no implementation visible in any diff — front bypass prevention depends entirely on selftest assertions without source-level verification
- Approximately 45% of transition-core.diff is truncated from the excerpt (25,000 of 55,711 characters missing), including portions of xunji_statusline.py set_active_run implementation and late selftest assertions
- _lifecycle_target_name returns empty string for setup_run.py --target without a positional slug — correct fail-closed behavior but untested in selftest
- Chinese-language semantic concern: the denial envelope text _未执行目标动作；不存在该动作的实测结果_ strongly asserts the absence of results; if paraphrased out of context after a different type of failure, this could be misleading

## Context-limit notes
- Live source files were inaccessible; all analysis relies on evidence diff artifacts and selftest log
- _active_protocol_fronts function cited as the anchor-resolver for output_gate is not visible in any diff
- I may miss subtle semantic nuances in Chinese policy text around 当前操作者 vs 当前 session authority gradient
- This is a code-maintenance run with no web target — rubric items 2/3/6 are adapted accordingly