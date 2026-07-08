# Peer Review Panel — 2026-07-08-loop-controller-implementation-review

_backend: panel:arkcli+claude · 2026-07-08T01:53Z_
> 候选, 非裁决。driver 须逐条过证据门。

## Verdict: WARN

_backend: panel:arkcli+claude_
_brain: codex_
_bundle_hash: b7dda4747f340afa74060a4f7d9f39e0af260e0c_
_evidence_index_hash: 6f05f8498d1c9aa9c35cee998d962194aa7c89b0_

## Findings
- [WARN] PR-001 E-004 real-run snapshot confirms the fix broadly prevents premature Completion pause across Coda/no-progress and Type-A blocked-front cases | Evidence: evidence_index:E-004, evidence/scshr-real-run-validation.json | Why: [panel:arkcli] [arkcli:kimi-k2.7-code] The artifact is a single environment-provided run snapshot. Per evidence discipline a single observation is not general confirmation, and it shows neither the old failure mode nor causality.
- [WARN] PR-002 Report lists multiple verification commands as already run, but only aggregate artifacts are provided | Evidence: report.md:Verification Already Run, evidence_index:E-003, evidence/lifecycle-selftests.out, evidence_index:E-005, evidence/stale-wording-scan.out | Why: [panel:arkcli] [arkcli:kimi-k2.7-code] The evidence index contains no separate artifacts for check_rules.py, check_templates.py, check_run --selftest, session_handoff, setup_run, or anti_drift, so their execution/pass status is unverified.
- [WARN] PR-003 E-005 stale-wording-scan.out confirms a stale-wording scan passed | Evidence: evidence_index:E-005, evidence/stale-wording-scan.out | Why: [panel:arkcli] [arkcli:kimi-k2.7-code] The artifact is only 23 bytes, too small to independently verify it scanned all updated docs/templates or evaluated stale wording.
- [WARN] PR-004 The reported source/design changes are fully verified by the confirmed evidence | Evidence: evidence_index:E-001, evidence/implementation.diff, evidence_index:E-002, evidence/selftest-loop-controller.out | Why: [panel:arkcli] [arkcli:kimi-k2.7-code] E-001 is a 0.3-certainty unconfirmed diff; the behavioral selftests do not cover every architectural claim in the report.
- [WARN] PR-005 arkcli panel had backend errors; review is partial | Evidence: minimax-m3: parse error; output tail: 002 through E-005) all have certainty 0.8 and has_control=true. They seem well-formed. But the supports arrays being empty is a process issue.

Actually, I realize I should focus on the evidence_skeptic role. Let me think harder about whether the evidence actually supports the claims.

The report claims:
- "Real run smoke: runs/scshr_20260708 now reports 4 open blocked_type_a fronts and can_stop=false"

E-004 excerpt shows:
```json
"open": ["F-001", "F-005", "F-002", "F-003"],
"open_count": 4,
" | Why: [panel:arkcli] At least one arkcli reviewer failed, so PASS only means the completed panel members found no blocker.

## Blind-spot check
- [arkcli] [kimi-k2.7-code] No control experiment showing the pre-fix parser would have treated the same state as a Completion pause, so causality is unproven.
- [arkcli] [kimi-k2.7-code] Missing per-tool artifacts for check_rules.py, check_templates.py, check_run --selftest, session_handoff, setup_run, and anti_drift.
- [arkcli] [kimi-k2.7-code] No static or unit proof that run_controller --shadow is strictly advisory and cannot write exploit/closure decisions.
- [arkcli] [kimi-k2.7-code] stale-wording-scan.out is tiny and its coverage is undocumented.
- [arkcli] [kimi-k2.7-code] Real-run validation is a single snapshot and does not exercise edge cases such as Coda convergence with zero open fronts or mixed Type A/B fronts.
- [arkcli] [glm-5.2] <things the author likely overlooked>
- [claude] The author (Claude) shares the same model architecture as the reviewer, so shared blind spots are possible. Specific areas the author likely missed:

## Context-limit notes
- [arkcli] [glm-5.2] <where you are unsure or might be wrong due to Chinese-language or local (CNVD / Taiwan) context you do not fully grasp>
- [arkcli] minimax-m3: parse error; output tail: 002 through E-005) all have certainty 0.8 and has_control=true. They seem well-formed. But the supports arrays being empty is a process issue.

Actually, I realize I should focus on the evidence_skeptic role. Let me think harder about whether the evidence actually supports the claims.

The report claims:
- "Real run smoke: runs/scshr_20260708 now reports 4 open blocked_type_a fronts and can_stop=false"

E-004 excerpt shows:
```json
"open": ["F-001", "F-005", "F-002", "F-003"],
"open_count": 4,
"
- [claude] All files in this review are in Chinese or mixed Chinese/English. I read Chinese fluidly and have no uncertainty about the content.
- [claude] The `scshr` run referenced in E-004 is a real target run; I cannot access it from this review directory, so I trust the artifact JSON for that claim but cannot verify the underlying `frontier.md` of that run independently.
- [claude] The `js_inventory` tool referenced in the selftest registration — I have not read its source, so I cannot judge whether its inclusion is a complete feature or a stub. It's flagged for scope reasons regardless.
- [claude] The `/loop` command handler — I cannot verify whether it exists outside the review scope. The concern is that it's absent from the diff, not a claim that it's broken.
