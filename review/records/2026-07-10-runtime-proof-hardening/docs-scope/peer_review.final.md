# Peer Review Panel — docs-scope

_backend: panel:arkcli+claude · 2026-07-11T00:16Z_
> 候选, 非裁决。driver 须逐条过证据门。

## Verdict: WARN

_backend: panel:arkcli+claude_  
_brain: codex_  
_bundle_hash: 3b73989a15aae773683232cd2082d79ea568a742_  
_evidence_index_hash: 0855f8ee0b61f6ecac485be8f751dca3fc80cd86_  

## Findings
- [WARN] PR-001 review.md asserts an unparsable arkcli backend limitation and a fallback to Kimi+fresh Claude without an evidence_index artifact or runtime event trace. | Evidence: review.md:PR-004, evidence_index entries (only E-001) | Why: [panel:arkcli] [arkcli:kimi-k2.7-code] Report/review/decisions.md are claims, not facts. The bundle contains no evidence_index entry for the alleged arkcli parse failure, so the limitation cannot be confirmed.
- [WARN] PR-002 E-001 is confirmed at certainty 0.8, but its 'enforcement' claim rests on component selftests and a static manifest rather than an integration trace of the new driver contract in a real run. | Evidence: E-001, selftest_all.log, installed-runtime-manifest.json, primary_skills.diff, agent_role_templates.diff | Why: [panel:arkcli] [arkcli:kimi-k2.7-code] Selftests and hashes prove files exist and components pass in isolation, not that the updated contract is exercised end-to-end. The current wording 'Rules, skills, and templates match enforcement' could be read as stronger than the evidence.
- [WARN] PR-003 stale_reference_audit.json only guards against the six known historical shortcut patterns; it will miss novel shortcut language introduced outside those patterns. | Evidence: stale_reference_audit.json:patterns, historical_failures.md | Why: [panel:arkcli] [arkcli:kimi-k2.7-code] A regex/pattern-only guard has coverage limited to its pattern set. The mapped failures are six specific cases; new drift could evade detection.
- [WARN] PR-004 arkcli panel had backend errors; review is partial | Evidence: minimax-m3: parse error; output tail:  the peer review panel was incomplete, then the "independent" review is less independent. However, the work is documentation parity, not a security finding - the calibration should be on whether the documentation is correct.

- The legacy `review/independent-reviewer.md` is now a "fail-safe deprecation pointer" (review.md). But looking at the actual file change, it's been rewritten to a much shorter content. The diff shows most of the original content was removed. Good.

- The `installed-runtime; glm-5.2: parse error; output tail: tem context says "the author is Claude." This matters because the peer review panel is supposed to be heterogeneous (different model from author). If the author is Codex, then a Claude reviewer IS heterogeneous. If the author is Claude, a Claude reviewer is NOT heterogeneous. The evidence suggests Codex is the author.

Now let me formulate my findings. I need to be focused and evidence-based.

Actually, let me reconsider the severity levels. The system says "ONLY certainty >= 0.8 may be reported | Why: [panel:arkcli] At least one arkcli reviewer failed, so PASS only means the completed panel members found no blocker.

## Blind-spot check
- [claude] **The missing docs/cognition/README.md gap**: CLAUDE.md references `docs/cognition/README.md` as "always loaded" and containing the canonical certainty table. The stale_reference_audit.json scans 53 files but does NOT include `docs/cognition/README.md`. Any Claude-facing Markdown that shapes behavior is within scope. If this file contains old shortcut language (e.g., "heartbeat proves execution," "heading satisfies review gate"), it would be a gap. The audit should be extended to cover ALL behavior-shaping prose, not just the template/skill/rule inventory.
- [claude] **installed-runtime-manifest.json has 8 identical turn_contract.py hook references**: The manifest records `turn_contract_hook_references` as 8 identical entries. This suggests the hook is configured to invoke turn_contract.py in 8 lifecycle positions, but the manifest doesn't distinguish which hook position each reference maps to. This is a documentation clarity issue — if a future maintainer needs to verify that all 8 hook positions are correctly wired, the manifest alone is insufficient.
- [claude] **The review.md driver dispositions are sound**: PR-001 (certainty 1.0→0.8), PR-002 (historical_failures.md added), PR-003 (explicitly prospective), PR-004 (limitation retained) are all correctly addressed. The driver did not dismiss or rationalize any finding — every panel finding was either acted on or honestly acknowledged. This is strong evidence of good review discipline.
- [claude] **The diffs are internally consistent across all 7 artifacts**: The same pattern transformation (heartbeat-as-proof → transcript-backed-receipt-as-proof, manual-fallback → foreground-invocation-required, prose-gate → content-addressed-gate) appears consistently across CLAUDE.md, WORKFLOW.md, WORKFLOW-reference.md, ROUTER.md, 4 skills, 8 agent templates, 3 lifecycle templates, and the independent-reviewer.md deprecation. No contradictory or half-updated language was found. The stale_reference_audit.json confirms 0 forbidden matches across 53 files. This is genuinely strong evidence of thoroughness.
- [claude] **This same-family Claude review is advisory per updated rules**: The updated CLAUDE.md (root_rules.diff) and xunji-peer-review-panel/SKILL.md both state: "a local same-family review is advisory and does not close the independent-review gate." My review here adds value as a fresh-context perspective (I see things the author may have missed), but it cannot substitute for a heterogeneous backend (Codex + arkcli panel) or a transcript-observed foreground peer_review.py invocation.

## Context-limit notes
- [arkcli] minimax-m3: parse error; output tail:  the peer review panel was incomplete, then the "independent" review is less independent. However, the work is documentation parity, not a security finding - the calibration should be on whether the documentation is correct.

- The legacy `review/independent-reviewer.md` is now a "fail-safe deprecation pointer" (review.md). But looking at the actual file change, it's been rewritten to a much shorter content. The diff shows most of the original content was removed. Good.

- The `installed-runtime
- [arkcli] glm-5.2: parse error; output tail: tem context says "the author is Claude." This matters because the peer review panel is supposed to be heterogeneous (different model from author). If the author is Codex, then a Claude reviewer IS heterogeneous. If the author is Claude, a Claude reviewer is NOT heterogeneous. The evidence suggests Codex is the author.

Now let me formulate my findings. I need to be focused and evidence-based.

Actually, let me reconsider the severity levels. The system says "ONLY certainty >= 0.8 may be reported
- [claude] I was unable to read `review/independent-reviewer.md` from the repo directly (read denied). The root_rules.diff shows it was changed from a full reviewer prompt template to a deprecation pointer, and the stale_reference_audit.json confirms it exists at the expected hash with 0 forbidden matches. I'm relying on the diff + audit evidence rather than direct file verification.
- [claude] I was unable to verify the actual CLAUDE.md, skills, and template files in the repo against what the diffs claim. The git status in the environment shows them as modified (`M`), which is consistent with the diffs, and the stale_reference_audit.json hashes provide integrity anchors.
- [claude] The `historical_failures.md` source files (pasted-text.txt) are only referenced by SHA-256 hash. I cannot verify the line-number trace anchors without these files. The historical failure map's credibility depends on operator-supplied histories I cannot independently verify.
- [claude] This is a documentation maintenance scope with no network targets, vulnerability claims, or Guanlan recon. The normal pentest evidence rules (multi-observation confirmation, control experiments for vulnerability claims) apply awkwardly. I've calibrated severity for a documentation review: the key question is whether documentation accurately describes enforcement, not whether a vulnerability exists.
- [claude] I am running as deepseek-v4-pro, a different model family from the author (Claude). This gives me genuine heterogeneity for blind-spot detection, but I do not have access to the Codex or arkcli backends that the review architecture prefers.