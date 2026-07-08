# Peer Review Panel — 2026-07-07-personalized-rdt-subagents

_backend: panel:arkcli · 2026-07-06T22:29Z_
> 候选, 非裁决。driver 须逐条过证据门。

## Verdict: NEEDS_DRIVER

_backend: panel:arkcli_  
_brain: codex_  
_bundle_hash: 03f9b9a44feec92d83aceff8e262dcef9a15ec49_  
_evidence_index_hash: 9fc8320eeed8c6c9e6beba32c6eb2720a3548448_  

## Findings
- [WARN] PR-001 E-001 is confirmed at certainty 1.0 that the personalized RDT enhancement is implemented with no OpenMythos runtime dependency and all tests pass | Evidence: evidence.md#E-001, evidence/diff-summary.txt:sha1=475f62797f0e2a9aee9eabd5e4922b0613a9ecb1, evidence/test-summary.txt:sha1=451e296952fc7c7a139dbb165f3f704ad313dc7c | Why: [panel:arkcli] [arkcli:kimi-k2.7-code] The cited artifacts are prose summaries, not raw git diff output or test command transcripts. A self-generated summary cannot support certainty 1.0. The no-OpenMythos-dependency boundary claim rests on a summary assertion rather than a grep/import-scan artifact.
- [WARN] PR-002 report.md confirms diff fingerprint 4cb050ea106eec62 for the reviewed change | Evidence: decisions.md#D-001, evidence/diff-summary.txt:sha1=475f62797f0e2a9aee9eabd5e4922b0613a9ecb1 | Why: [panel:arkcli] [arkcli:kimi-k2.7-code] The confirmed fingerprint explicitly includes an untracked file. If that file changes before staging, the confirmed fingerprint becomes invalid, breaking the audit trail binding the decision to code state.
- [WARN] PR-003 Compatibility check is strict enough for new personalized-RDT files without spamming old runs | Evidence: decisions.md#D-003, review.md | Why: [panel:arkcli] [arkcli:kimi-k2.7-code] The check was narrowed because it produced 24 warnings on historical agents. Verification only shows clean behavior on an old run and incomplete-step detection for new files; no artifact demonstrates behavior on agents that accidentally contain partial RDT markers.
- [WARN] PR-004 arkcli panel had backend errors; review is partial | Evidence: minimax-m3: parse error; output tail: ety check mentioned in the evidence. The D-002 claim that this "does not alter...request budgets" contradicts the diff-summary's mention of "loop budget" being injected.

Wait, let me re-read. The report says: "context_pack.py injects resolved RDT style, loop budget, role focus, review/evidence preference, replay policy, and retrospective lessons." So loop budget IS injected. And D-002 says: "Agent personalization changes prompt shape, loop budget, and context hints only. It does not alter guard; glm-5.2: parse error; output tail: arnings unless they declare the new `personalized-rdt` markers." This is consistent but reveals the suppression approach.

The report says "New personalized-RDT files are checked for required Step fields." The diff-summary.txt confirms: "`agent-check` validates RDT fields only when a file declares `personalized-rdt`, `Loop budget`, `Operator profile`, or the RDT controls section." Consistent.

Now for the blind-spot check:
- The author didn't consider that narrowing the check (D-003) to suppress | Why: [panel:arkcli] At least one arkcli reviewer failed, so PASS only means the completed panel members found no blocker.
- [WARN] PR-005 review panel had backend errors; aggregation is partial | Evidence: claude: NEEDS_DRIVER erage empty" / "coverage.json missing" / "no classify" as BLOCKER. These are expected.
- You may still flag them as WARN if the report makes claims that depend on coverage data it doesn't have.
- For any other rubric items, apply the normal severity standards — no-recon only relaxes coverage checks. | Why: At least one requested heterogeneous reviewer failed or was unavailable.

## Blind-spot check
- [arkcli] [kimi-k2.7-code] No raw git diff artifact is present; only diff-summary.txt
- [arkcli] [kimi-k2.7-code] No raw test transcript or console log artifact is present; only test-summary.txt
- [arkcli] [kimi-k2.7-code] No independent CI or reviewer re-run artifact
- [arkcli] [kimi-k2.7-code] No grep/import-scan artifact proving OpenMythos is absent from the codebase
- [arkcli] [kimi-k2.7-code] The state/operator_profile.json location is questioned in review.md but not resolved
- [arkcli] [kimi-k2.7-code] No artifact shows how the 'openmythos-inspired' style string is rendered in actual prompts

## Context-limit notes
- [arkcli] minimax-m3: parse error; output tail: ety check mentioned in the evidence. The D-002 claim that this "does not alter...request budgets" contradicts the diff-summary's mention of "loop budget" being injected.

Wait, let me re-read. The report says: "context_pack.py injects resolved RDT style, loop budget, role focus, review/evidence preference, replay policy, and retrospective lessons." So loop budget IS injected. And D-002 says: "Agent personalization changes prompt shape, loop budget, and context hints only. It does not alter guard
- [arkcli] glm-5.2: parse error; output tail: arnings unless they declare the new `personalized-rdt` markers." This is consistent but reveals the suppression approach.

The report says "New personalized-RDT files are checked for required Step fields." The diff-summary.txt confirms: "`agent-check` validates RDT fields only when a file declares `personalized-rdt`, `Loop budget`, `Operator profile`, or the RDT controls section." Consistent.

Now for the blind-spot check:
- The author didn't consider that narrowing the check (D-003) to suppress
- claude: NEEDS_DRIVER erage empty" / "coverage.json missing" / "no classify" as BLOCKER. These are expected.
- You may still flag them as WARN if the report makes claims that depend on coverage data it doesn't have.
- For any other rubric items, apply the normal severity standards — no-recon only relaxes coverage checks.
- panel completed 1/2 required heterogeneous backends

> ERROR: claude: NEEDS_DRIVER erage empty" / "coverage.json missing" / "no classify" as BLOCKER. These are expected.
- You may still flag them as WARN if the report makes claims that depend on coverage data it doesn't have.
- For any other rubric items, apply the normal severity standards — no-recon only relaxes coverage checks.