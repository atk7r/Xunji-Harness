# Peer Review Panel — docs-scope

_backend: panel:arkcli+claude · 2026-07-10T22:21Z_
> 候选, 非裁决。driver 须逐条过证据门。

## Verdict: BLOCKER

_backend: panel:arkcli+claude_  
_brain: codex_  
_bundle_hash: ca743bfea9a4e209a94142ca9eaaa5e8201c38e0_  
_evidence_index_hash: d4fb40a778e550ee2a38e0b8a21294e1479eaf63_  

## Findings
- [WARN] PR-001 E-001 is marked confirmed (certainty 1.0) for 'Rules, skills, and templates match enforcement', but the only runtime control is a single selftest_all.log run; diffs show textual parity, not live enforcement behavior. | Evidence: evidence_index:E-001, selftest_all.log sha1:93ebddc9828ef662afa820b6f311388d40dafad8, agent_role_templates.diff sha1:2898c51d8e0dd9daee8a5961ca9ead9c03595b87, root_rules.diff sha1:62e30d9e09d3a0b327e6af49d78ae1812b4d640e | Why: [panel:arkcli] [arkcli:kimi-k2.7-code] A passing selftest is a single observation, and text diffs align documentation to intended enforcement without proving enforcement occurs. Certainty 1.0 implies no residual uncertainty, which is not justified.
- [WARN] PR-002 The documentation review did not map the revised prose to the specific historical shortcut sessions it is meant to prevent; no before/after behavior trace from those sessions is in the evidence bundle. | Evidence: report.md, decisions.md, agent_role_templates.diff, lifecycle_templates.diff, primary_skills.diff, root_rules.diff, workflow_core.diff, workflow_reference.diff | Why: [panel:arkcli] [arkcli:kimi-k2.7-code] Without tracing to the actual historical failure mode, the review cannot confirm the prose no longer teaches or permits the exact shortcuts observed earlier.
- [WARN] PR-003 review.md contains a process claim that 'arkcli panel plus fresh Claude review' is required, but the file is a stub with no actual independent ReviewReceipt or ledger resolution. | Evidence: review.md sha1:bf5729b7c139b0d5cd72ee4971341d90d26284ae, lifecycle_templates.diff (run/review.md hunk), workflow_reference.diff | Why: [panel:arkcli] [arkcli:kimi-k2.7-code] The updated rules require a transcript-observed foreground peer-review invocation; the current review.md is only a declaration of intent, not the required receipt.
- [WARN] PR-004 arkcli panel had backend errors; review is partial | Evidence: minimax-m3: parse error; output tail: **:

1. The "deep depth" closure of F-001 relies on the standard selftest as a "regression control" - but this is a generic tool smoke test, not a test of the new doc-enforced behavior. The diffs themselves are the closure evidence, not actual validation that the changes work.

2. The report doesn't cite which "shortcuts observed in the historical sessions" the docs previously taught. Without that, the depth claim is hard to evaluate.

3. The evidence artifacts are diffs - they show what changed; glm-5.2: parse error; output tail: he "has_control=true" is plausible but thin.

6. Missed surface: The diffs change loop_prompt.md, CLAUDE.md, WORKFLOW.md, WORKFLOW-reference.md, ROUTER.md, worker.md, run/review.md, 4 SKILL.md, 8 agent templates. Are there other behavior-shaping docs not touched? E.g., AGENTS.md (Codex's own), README, other skills not in the list. The bundle doesn't show an inventory of all docs that mention heartbeat/finish/proof. A stale-reference audit is missing.

Also: the diffs introduce new requirements ( | Why: [panel:arkcli] At least one arkcli reviewer failed, so PASS only means the completed panel members found no blocker.

## Blind-spot check
- [arkcli] [kimi-k2.7-code] The actual hook implementations (tools/runtime_receipts.py, tools/turn_contract.py, tools/output_gate.py) are only represented by a passing selftest log, not by source diffs or a live trace.
- [arkcli] [kimi-k2.7-code] The diff set may not cover all Claude-facing prose; remaining docs/templates/run/*, docs/CHANGELOG, or issue templates could still contain shortcut language.
- [arkcli] [kimi-k2.7-code] No end-to-end evidence shows the new XUNJI_COMPLETION_REVIEW Agent prompt and its four required checks functioning in a real turn.
- [arkcli] [kimi-k2.7-code] The fan-out rule ('two actual Agent calls per EXECUTE turn') was added to multiple docs, but no runtime evidence demonstrates it is being mechanically enforced.
- [claude] **The diffs are internally coherent and directionally correct.** All 7 artifact files exist, are non-empty, and show consistent changes across CLAUDE.md, WORKFLOW.md, WORKFLOW-reference.md, 4 skills, 8 agent templates, 2 lifecycle templates, and the review template. The new language consistently replaces "prose/heartbeat/manual-fallback proves execution" with "transcript-backed receipt proves execution." This is a genuine hardening.
- [claude] **The evidence.md "Result" prose is more accurate than the certainty rating suggests.** The seven removed patterns are correctly identified in the diffs. If certainty were 0.8 with a caveat that "parity is confirmed by edit+regression, not by direct cross-reference," the evidence would be solid. The problem is strictly that 1.0 overstates what's proven.
- [claude] **The frontier closure might be procedural rather than substantive.** F-001 "closed" may mean "the documentation editing work is complete and internally consistent" while the separate review gate (which I am performing) is the next step. However, the frontier file doesn't distinguish "edit-complete" from "review-passed," and the project's closure machinery treats any "closed" front as adjudicated.
- [claude] **Missing negative check: does `review/independent-reviewer.md` still exist in the repo?** The old docs referenced it as a review template. The diffs remove all references but I cannot verify the file was deleted (read permission denied on the repo path). If it exists, it contradicts the new docs.

## Context-limit notes
- [arkcli] minimax-m3: parse error; output tail: **:

1. The "deep depth" closure of F-001 relies on the standard selftest as a "regression control" - but this is a generic tool smoke test, not a test of the new doc-enforced behavior. The diffs themselves are the closure evidence, not actual validation that the changes work.

2. The report doesn't cite which "shortcuts observed in the historical sessions" the docs previously taught. Without that, the depth claim is hard to evaluate.

3. The evidence artifacts are diffs - they show what changed
- [arkcli] glm-5.2: parse error; output tail: he "has_control=true" is plausible but thin.

6. Missed surface: The diffs change loop_prompt.md, CLAUDE.md, WORKFLOW.md, WORKFLOW-reference.md, ROUTER.md, worker.md, run/review.md, 4 SKILL.md, 8 agent templates. Are there other behavior-shaping docs not touched? E.g., AGENTS.md (Codex's own), README, other skills not in the list. The bundle doesn't show an inventory of all docs that mention heartbeat/finish/proof. A stale-reference audit is missing.

Also: the diffs introduce new requirements (
- [claude] I cannot verify that `review/independent-reviewer.md` was deleted from the repo (permission denied on `/Users/ccj/Documents/AI/Xunji/review/independent-reviewer.md`). If it still exists, it would be an orphaned artifact teaching the old manual-fallback review pattern that the diffs explicitly remove. This should be checked.
- [claude] I cannot verify the actual CLAUDE.md, skills, and template files in the repo match what the diffs claim (permission denied for some paths). I'm relying on git status showing them as modified, which is consistent.
- [claude] This is a documentation-only scope with no network target, no vulnerability claims, and no Guanlan recon. The normal evidence rules (control experiment, multi-observation confirmation) are designed for vulnerability findings and apply awkwardly to a documentation review. I've adjusted my severity accordingly — what would be a routine WARN in a vuln run (e.g., missing coverage) is not applicable here, while what would be a minor WARN in a vuln run (e.g., certainty calibration) becomes a BLOCKER here because certainty IS the core claim.