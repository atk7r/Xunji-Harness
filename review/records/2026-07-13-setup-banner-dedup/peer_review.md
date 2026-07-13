# Peer Review Panel — 2026-07-13-setup-banner-dedup

_backend: panel:arkcli+claude · 2026-07-13T05:52Z_
> 候选, 非裁决。driver 须逐条过证据门。

## Verdict: WARN

_backend: panel:arkcli+claude_  
_brain: codex_  
_bundle_hash: c2f686c1bed2b408c6e8b4405abfc9528c8ea147_  
_evidence_index_hash: 75f89afcfce57b7b964fa116630699c0370d6452_  

## Findings
- [WARN] PR-001 The setup_run selftest verifies a closed Setup journal cycle (both phase_start and phase_end). | Evidence: setup_run.diff (sha1:08587978b12e81229fff3672c23cc36ae6656748) hunk '@@ -539,11 +526,10 @@ def _selftest() -> int:', selftest.log (sha1:1f4546bb7d65b9ef0ff03151c92b325c7483b309) | Why: [panel:arkcli] [arkcli:kimi-k2.7-code] The renamed assertion only checks that _phase_banner is absent, the last recorded event is phase_end, and open_phase is false. A regression that removed the phase_start call while leaving phase_end would still satisfy these checks, so the selftest does not independently confirm the cycle opened before it closed.
- [WARN] PR-002 The selftest assertion '_phase_banner not in globals() is brittle and does not prevent reintroduction of banners via direct loop_journal calls or alternative helpers. | Evidence: setup_run.diff | Why: [panel:arkcli] [arkcli:glm-5.2] The current test only checks if a specific function name was deleted, not that the behavior (printing a banner) is prevented.
- [WARN] PR-003 The report claims canonical docs clearly describe the setup exception without weakening visible markers for Root Orchestrator, Hunter, etc., but the provided docs_excerpt.md only shows the Setup exception lines. | Evidence: docs_excerpt.md, report.md | Why: [panel:arkcli] [arkcli:glm-5.2] The evidence excerpt is too narrow to confirm that other phase markers remain intact; the claim cannot be fully verified from the provided artifact.
- [WARN] PR-004 Selftest only checks function absence, not terminal output | Evidence: `setup_run.diff` hunk 4 — new selftest assertion `"_phase_banner" not in globals()` | Why: [panel:claude] An inline `print("[Xunji] [阶段开始] [Setup｜准备运行]")` or direct `render_phase_banner` import would bypass the selftest. A stdout-capture assertion would be stronger. Low severity — the function-name check catches the most likely regression vector.
- [WARN] PR-005 No behavioral integration test of full setup_run main() output | Evidence: `selftest.log` — only unit-level assertions | Why: [panel:claude] The selftest validates journal state and function absence but doesn't run `main()` and verify its stdout is free of phase banner text. Adding a subprocess invocation with stdout capture would close this gap.

## Blind-spot check
- [arkcli] [kimi-k2.7-code] Selftest no longer asserts that phase_start is recorded; it only checks the end-of-cycle state, weakening regression coverage for the 'preserved journal events' requirement.
- [arkcli] [kimi-k2.7-code] Evidence bundle contains doc excerpts but no diffs or commit metadata for CLAUDE.md, WORKFLOW.md, ROUTER.md, or SKILL.md, so we cannot confirm whether the setup-only exception language was introduced in this change or already present.
- [arkcli] [kimi-k2.7-code] Diff only inspects the success path of main(); no artifact verifies that early-return/error paths also omit box banners.
- [arkcli] [kimi-k2.7-code] Pentest-specific checks (coverage ledger, RCE/frontier depth, target-facing behavior) are correctly out of scope for this maintenance-only review.
- [claude] **loop_bootstrap.py not audited for Setup banners:** The test suite covers `loop_bootstrap` but the diff only touches `setup_run.py`. If `loop_bootstrap.py` independently prints `[Xunji] [阶段开始] [Setup]` banners, this change doesn't address them. The docs identify `setup_run.py` as "the" exception, which implies no other file produces Setup banners — but this assumption is untested.
- [claude] **`_phase_journal` exception-swallowing:** While pre-existing and not introduced by this diff, the try/except in `_phase_journal` (visible in the diff context) discards journal write failures silently. The selftest's journal-closure check catches the aftermath, but a future change that adds a code path between `phase_start` and `phase_end` without checking the journal state could mask silent failures.
- [claude] **The docs_excerpt is a curated 2-3 line context window around each match.** Full file context might contain subtle qualifications or nearby contradictory language. Given the consistency across four independent docs, this is unlikely but procedurally notable.

## Context-limit notes
- [claude] Unable to independently verify `tools/setup_run.py` on disk — analysis relies entirely on the review bundle's embedded diff (sha1 `08587978b12e81229fff3672c23cc36ae6656748`). Read/Grep/Bash are all unavailable in this execution context.
- [claude] Cannot verify whether `loop_journal.render_phase_banner` itself has side effects or changes that might interact with this removal — the function definition is outside the diff scope. The selftest passing suggests no issues, but I cannot confirm independently.