# Peer Review Panel — 2026-07-08-xunji-statusline-precommit-review

_backend: panel:arkcli+claude · 2026-07-08T08:07Z_
> 候选, 非裁决。driver 须逐条过证据门。

## Verdict: BLOCKER

_backend: panel:arkcli+claude_  
_brain: codex_  
_bundle_hash: fed951d5c3e605ab4663391381749ae8be8fc089_  
_evidence_index_hash: c252e7f4dd749a35b4ddf775551ae52dc56b6186_  

## Findings
- [BLOCKER] PR-001 E-006 is marked confirmed (certainty 0.8) but has no supporting artifact in the review bundle | Evidence: evidence_index:E-006 | Why: [panel:arkcli] [arkcli:kimi-k2.7-code] Evidence discipline requires confirmed findings to be backed by artifacts or replay recordings. E-006 has an empty artifacts list, so it cannot support F-001/F-002 at certainty >=0.8.
- [WARN] PR-002 report.md's External Schema Check cites Claude Code docs URLs without archived evidence | Evidence: report.md:External Schema Check section | Why: [panel:arkcli] [arkcli:kimi-k2.7-code] Claims about third-party documentation compatibility must cite evidence_index entries or artifact hashes, not only URLs in prose.
- [WARN] PR-003 The read-only claim is supported by a single-render mtime check, not by repeated Claude Code refreshes or concurrent --set-active races | Evidence: evidence/patches/tools__xunji_statusline_py.patch.txt, evidence/test-log.txt | Why: [panel:arkcli] [arkcli:kimi-k2.7-code] The selftest shows one render pass did not modify four watched files, but does not prove the 2-second statusline refresh path is side-effect-free under concurrency.
- [WARN] PR-004 F-003 lifecycle integration is tested only through a stubbed hook call count, not through the real set-active → render path | Evidence: evidence/patches/tools__loop_bootstrap_py.patch.txt, evidence/patches/docs__templates__loop_prompt_md.patch.txt | Why: [panel:arkcli] [arkcli:kimi-k2.7-code] The bootstrap selftest asserts cmd_new/cmd_resume call the hook, but does not verify the pointer resolves or that the rendered statusline reflects the newly selected run.
- [WARN] PR-005 arkcli panel had backend errors; review is partial | Evidence: minimax-m3: parse error; output tail: :
1. BLOCKER: E-006 is confirmed at certainty 0.8 but has no artifacts - this is a violation of the evidence gate.

Blind spots:
- E-006's content is completely unknown - what does it claim?
- The "first independent review returned WARN" claim has no backing artifact
- External doc validation against Claude Code docs is not backed by captured artifacts
- The statusline was never tested in a real Claude Code environment

Let me also think about the report.md more carefully. Looking at the report,; glm-5.2: parse error; output tail: this.

**WARN**: No performance consideration for 2-second refresh interval with journal reading (up to 500 lines).

**WARN**: The selftest doesn't test error paths for malformed state files (valid JSON but wrong types in nested fields beyond what _load_json catches).

Let me also check: does every evidence item with certainty >= 0.8 get carried into the report's confirmed findings?

The report doesn't have explicit "confirmed findings" - it's a maintenance diff review, not a pentest report. The | Why: [panel:arkcli] At least one arkcli reviewer failed, so PASS only means the completed panel members found no blocker.

## Blind-spot check
- [arkcli] [kimi-k2.7-code] E-006 is the only confirmed evidence entry with zero artifacts; likely a manual review note that was not attached or downgraded.
- [arkcli] [kimi-k2.7-code] Selftests do not exercise malformed stdin, missing state files, or a run dir without a state/ subdirectory.
- [arkcli] [kimi-k2.7-code] No evidence tests the actual Claude Code statusline invocation path; the selftest emulates it via subprocess and environment variables.
- [arkcli] [kimi-k2.7-code] The active-run pointer write is atomic but the read path has no locking; concurrent refresh and bootstrap could race.

## Context-limit notes
- [arkcli] minimax-m3: parse error; output tail: :
1. BLOCKER: E-006 is confirmed at certainty 0.8 but has no artifacts - this is a violation of the evidence gate.

Blind spots:
- E-006's content is completely unknown - what does it claim?
- The "first independent review returned WARN" claim has no backing artifact
- External doc validation against Claude Code docs is not backed by captured artifacts
- The statusline was never tested in a real Claude Code environment

Let me also think about the report.md more carefully. Looking at the report,
- [arkcli] glm-5.2: parse error; output tail: this.

**WARN**: No performance consideration for 2-second refresh interval with journal reading (up to 500 lines).

**WARN**: The selftest doesn't test error paths for malformed state files (valid JSON but wrong types in nested fields beyond what _load_json catches).

Let me also check: does every evidence item with certainty >= 0.8 get carried into the report's confirmed findings?

The report doesn't have explicit "confirmed findings" - it's a maintenance diff review, not a pentest report. The
- [claude] I cannot access files outside the review bundle directory, so I cannot independently verify: (a) whether `status_style.tag()` accepts "white" as a color argument, (b) whether `ROOT/tmp/` is already in `.gitignore`, (c) whether `status_style.color_enabled()` actually reads `XUNJI_COLOR` from the environment, (d) the full `selftest_all.py` suite for regression analysis.
- [claude] I cannot verify the Claude Code settings schema to confirm `"statusLine"` (camelCase) is the correct key name. This is the single most impactful uncertainty in this review.
- [claude] Chinese-language content in journal notes, documentation, and the `_last_plan_note` regex — I read these but may miss subtle semantic drift between what `loop_journal.py` actually writes and what the statusline regex extracts.
- [claude] This is a maintenance diff review, not a web pentest. The rubric items about recon assets, coverage ledgers, and exploit depth have limited applicability — the "frontier" consists of 4 review fronts (F-001 through F-004) all at "open-for-review" status, and evidence covers them.
- [claude] The Round 1 and Round 2 arkcli panels both had backend errors (minimax-m3 and glm-5.2 parse errors), meaning prior review coverage was partial. Findings from those reviews that cite those backends should be weighted accordingly.