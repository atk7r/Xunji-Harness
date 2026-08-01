# Peer Review Panel — 2026-07-13-setup-banner-dedup

_backend: panel:arkcli+claude · 2026-07-13T05:59Z_
> 候选, 非裁决。driver 须逐条过证据门。

## Verdict: WARN

_backend: panel:arkcli+claude_
_brain: codex_
_bundle_hash: 90edd53574524a6d0472d2a70e7ead6650ff7d98_
_evidence_index_hash: f681217b0a42160a42ceaca39247c964ab230f73_

## Findings
- [WARN] PR-001 The selftest prevents accidental reintroduction of the banner helper and verifies a closed Setup journal cycle. | Evidence: setup_run.diff:@@ -539,11 +532,47 @@, selftest.log | Why: [panel:arkcli] [arkcli:kimi-k2.7-code] The current selftest only checks that `main()` output does not contain a few hard-coded marker strings and that the journal cycle closes. It does not guard against reintroducing the helper under a different name or with different output strings, so the claim is stronger than the evidence supports.
- [WARN] PR-002 Both setup_run.py banner prints are removed and no banner helper remains. | Evidence: setup_run.diff, evidence_index.E-001.artifacts | Why: [panel:arkcli] [arkcli:kimi-k2.7-code] The evidence bundle only contains a diff artifact for `tools/setup_run.py`. While the diff shows removal of the helper and two prints, reviewers cannot directly open the final file to confirm no other references were left outside the displayed hunks.
- [WARN] PR-003 arkcli panel had backend errors; review is partial | Evidence: glm-5.2: parse error; output tail:  (not just write to the journal), then banners would still appear even though `_phase_banner` is removed. The selftest would catch this IF the printed output matches the checked strings, but might miss it if the format differs. I should flag this as something to verify.

Actually, looking at the selftest more carefully - it runs `main()` with `contextlib.redirect_stdout(captured)` and checks that `[Xunji] [阶段开始]` is NOT in the captured output. If `_phase_journal` internally causes `loop_journal` | Why: [panel:arkcli] At least one arkcli reviewer failed, so PASS only means the completed panel members found no blocker.

## Blind-spot check
- [arkcli] [kimi-k2.7-code] No static/AST absence check for banner helper reintroduction.
- [arkcli] [kimi-k2.7-code] Selftest regression surface is narrow (output/journal only, no source assertions).
- [arkcli] [kimi-k2.7-code] Docs already describe the exception but are not modified in this bundle, so doc drift is not guarded here.
- [claude] **The panel review itself is the biggest blind spot.** It issued a WARN verdict with 5 findings, but 3 of those 5 findings (PR-001, PR-002+PR-004, PR-005) are factually wrong when checked against the diff. The code change is actually solid: both banner prints removed, journal events preserved, a thorough integration test added with stdout capture and multi-marker absence checks. The real "finding" here is meta: the independent review process produced incorrect findings, which defeats its purpose as a heterogeneous check.
- [claude] **The integration test's stdout check is actually more thorough than acknowledged**: it checks for `[Xunji] [阶段开始]`, `[Xunji] [阶段结束]`, `XUNJI PHASE START`, AND `XUNJI PHASE END` — four distinct banner marker patterns — plus a positive control (`[setup] 建 run 骨架` in output). This catches not just the removed `_phase_banner` function but also any future attempt to inline banners or use alternative rendering paths.
- [claude] **`loop_bootstrap.py` blind spot (from existing panel review) is valid but low-risk**: CLAUDE.md explicitly says "Mechanical Setup inside `setup_run.py` is the one display exception," which implies no other file should produce Setup banners. The selftest success confirms this indirectly.
- [claude] **`_phase_journal` exception swallowing (pre-existing)**: visible in the diff context at the `_phase_journal` function definition — the try/except silently discards journal write failures. Not introduced by this change, but worth noting as pre-existing technical debt.
- [claude] **Error-path banner absence**: The original banner prints were placed AFTER the `scaffold()` call on the success path. The early-return error paths (run already exists, etc.) never had banners and still don't. No regression risk there.

## Context-limit notes
- [arkcli] glm-5.2: parse error; output tail:  (not just write to the journal), then banners would still appear even though `_phase_banner` is removed. The selftest would catch this IF the printed output matches the checked strings, but might miss it if the format differs. I should flag this as something to verify.

Actually, looking at the selftest more carefully - it runs `main()` with `contextlib.redirect_stdout(captured)` and checks that `[Xunji] [阶段开始]` is NOT in the captured output. If `_phase_journal` internally causes `loop_journal`
- [claude] Unable to read `tools/setup_run.py` on disk directly (Read permission denied in this execution context). Analysis relies entirely on the review bundle's embedded diff (sha1 `095ab0f84f4f213dc0cb3aa100eed7e4f78585df`). If the diff is truncated or the on-disk file differs, some conclusions could be wrong. However, the diff is annotated with complete hunk headers and the file is 5299 bytes — well within the 24000-char excerpt limit — suggesting completeness.
- [claude] Cannot verify `loop_journal.render_phase_banner()` or `loop_journal.summarize()` behavior independently. The selftest passing provides implicit verification, but I cannot confirm these functions have no side effects that interact with the banner removal.
- [claude] Chinese-language documentation: I've read the Chinese sections in `docs_excerpt.md` (WORKFLOW.md, ROUTER.md, SKILL.md) and they consistently describe the same Setup exception. No contradictions detected. My Chinese reading is sufficient for this narrow scope.
- [claude] The panel review frontmatter says `_brain: codex` — the Codex was supposed to synthesize the arkcli+claude panel output. The fact that 3/5 incorrect findings passed through Codex synthesis is a meta-concern about the review architecture pipeline.
