# Peer Review Panel — 2026-07-08-plan-implementation-review

_backend: panel:arkcli+claude · 2026-07-07T22:10Z_
> 候选, 非裁决。driver 须逐条过证据门。

## Verdict: BLOCKER

_backend: panel:arkcli+claude_
_brain: codex_
_bundle_hash: 6fa574b27ae284b85a65ef44f1e25c62f59adfde_
_evidence_index_hash: 4230b0ece81a8e316f7f51e3f239ee4e182eda78_

## Findings
- [BLOCKER] PR-001 E-004 is marked confirmed (certainty 0.8) but its cited artifact evidence/git-diff-check.out is missing, so the claim that git diff --check passed is unsupported. | Evidence: evidence_index:E-004, evidence/git-diff-check.out, machine_findings:artifact_reference_missing | Why: [panel:arkcli] [arkcli:kimi-k2.7-code] The evidence_index explicitly lists evidence/git-diff-check.out as exists:false and includes it in artifacts_missing. Confirmed findings require an existing artifact; until the artifact is produced, E-004 cannot stand as confirmed.
- [WARN] PR-002 Report asserts the diff introduces no second source of truth, no unsafe executor, and no hard gate breaking old runs, but only synthetic bench/selftest evidence is supplied and the git diff check artifact is absent. | Evidence: report.md:Driver Answers 1, evidence_index:E-001, evidence_index:E-003, evidence_index:E-004 | Why: [panel:arkcli] [arkcli:kimi-k2.7-code] E-001 is a low-certainty (0.3) phenomenon artifact; E-003 validates canary linkage but not global safety properties; E-004 is missing the git-diff-check output. The report therefore overstates confidence in high-level architectural guarantees.
- [WARN] PR-003 js_inventory.py no-network guarantee rests on a single 84-byte selftest output, which is insufficient to prove the production tool never fetches network or escapes the run directory. | Evidence: evidence_index:E-005, evidence/js-inventory-no-network-control.out, report.md:Driver Answer 3 | Why: [panel:arkcli] [arkcli:kimi-k2.7-code] Selftest monkeypatching may not cover all code paths or import-time side effects. The tiny artifact lacks request/response detail and should be supplemented with a read-only run-dir audit of implementation.diff.
- [WARN] PR-004 The 560-byte selftest-selected.out summary cannot verify that each listed tool selftest exercised the new logic (e.g., workers.py rejecting agent finding maturity, context-pack threat-hypothesis injection). | Evidence: evidence_index:E-002, evidence/selftest-selected.out, report.md:Verification Already Run | Why: [panel:arkcli] [arkcli:kimi-k2.7-code] The report lists seven distinct verification commands, but only one aggregated artifact is provided. Without per-tool output, the reviewer cannot confirm the asserted guardrails are actually tested.
- [WARN] PR-005 Bench 18/18 clean (E-003) demonstrates canary conformance but does not independently prove old runs are not broken or that no hard gate was introduced. | Evidence: evidence_index:E-003, evidence/bench-score-all.json, report.md:Driver Answers 1 and 4 | Why: [panel:arkcli] [arkcli:kimi-k2.7-code] The same fixture set may be tuned to the new code; absence of regression against a pre-change baseline means the 'no hard gate' claim is extrapolated rather than evidenced.
- [WARN] PR-006 arkcli panel had backend errors; review is partial | Evidence: minimax-m3: parse error; output tail: diff contains many changes. It's not a finding per se. But the bench is mapping findings to E-001 because the diff is the evidence that the canary fixture's process was supported. This makes sense in the Xunji context: the canary fixtures are about pipeline discipline, and E-001 is the diff that adds the pipeline features. The bench confirms that the new canary mechanisms work (process+linkage detection) by exercising them against the diff. That's the design.

    But still — E-001 at certainty ; glm-5.2: parse error; output tail: quest-based and process-only fixtures without distinction.

### Finding 4 (WARN): No `.agents/skills` update acknowledged but not explained
Report acknowledges `.agents/skills` was not edited but doesn't explain whether this creates a coverage gap for non-Claude agents.

### Finding 5 (WARN): check-rules.out and check-templates.out are trivially small
18 and 22 bytes respectively. For confirmed findings (E-004, certainty 0.8), these artifacts don't demonstrate meaningful rule/template validation | Why: [panel:arkcli] At least one arkcli reviewer failed, so PASS only means the completed panel members found no blocker.

## Blind-spot check
- [arkcli] [kimi-k2.7-code] implementation.diff (E-001, certainty 0.3) is treated as a phenomenon, so the detailed code changes are not confirmed and are not linked to the driver answers.
- [arkcli] [kimi-k2.7-code] The report notes .agents/skills was not edited, but provides no evidence that agents consume .claude/skills updates equivalently; divergence could leave agent behavior stale.
- [arkcli] [kimi-k2.7-code] No runtime/replay evidence of the full agent threat-hypothesis lifecycle (NH-* -> H-001 -> E-entry) is provided beyond bench process flags.
- [arkcli] [kimi-k2.7-code] The bundle lacks surface.md, coverage ledger, or recon assets, so the coverage-ledger rubric cannot be evaluated; the report does not explicitly mark this N/A.
- [claude] **The report answers review question 1 ("second source of truth") but misses the verbatim-prose injection concern.** The answer correctly states that `loop_state.py` is a derived cache and Agents cannot promote findings. But it does not address that `merge-threats` writes Agent-controlled text into `hypotheses.md` — which, while not a "second source of truth," IS a path for untrusted Agent output to enter a run's permanent state file. This is the kind of blind spot a heterogeneous reviewer catches that Claude might share with itself: the focus on "does this create a new truth source?" obscures "does this inject untrusted content into existing truth sources?"
- [claude] **The `checked-recorded_requests` in several bench fixtures is 0** (e.g., `example-dvwa-sqli: 0 requests`, `js-hidden-api-threat: 0`, `signed-client-param: 0`). The bench output notes this as "lower bound: saved replay or recorded events" — meaning the bench scorer cannot verify request counts for fixtures that don't use Xunji's request-recording mechanism. This is documented behavior but worth noting: fixtures with `recorded_requests: 0` have a weaker budget enforcement at bench time. The report doesn't call this out.
- [claude] **The diff is 84KB across ~35 files, but the review report is only ~3.7KB.** The review answers 5 questions at a summary level but doesn't reference specific diff hunks or file:line locations (unlike typical Xunji evidence which cites specific findings). This is appropriate for a maintenance review (reviewing architectural correctness, not bug-hunting) but means any line-level issues in the diff would not have been caught by this review process.
- [claude] **The `merge-threats` function adds both `Linked IS/C/E` and `Linked evidence` fields with the same value** (lines 1032-1033 of the diff). This creates redundant data in `hypotheses.md` entries. Not a bug, but suggests the merge logic wasn't fully cleaned up.

## Context-limit notes
- [arkcli] minimax-m3: parse error; output tail: diff contains many changes. It's not a finding per se. But the bench is mapping findings to E-001 because the diff is the evidence that the canary fixture's process was supported. This makes sense in the Xunji context: the canary fixtures are about pipeline discipline, and E-001 is the diff that adds the pipeline features. The bench confirms that the new canary mechanisms work (process+linkage detection) by exercising them against the diff. That's the design.

    But still — E-001 at certainty
- [arkcli] glm-5.2: parse error; output tail: quest-based and process-only fixtures without distinction.

### Finding 4 (WARN): No `.agents/skills` update acknowledged but not explained
Report acknowledges `.agents/skills` was not edited but doesn't explain whether this creates a coverage gap for non-Claude agents.

### Finding 5 (WARN): check-rules.out and check-templates.out are trivially small
18 and 22 bytes respectively. For confirmed findings (E-004, certainty 0.8), these artifacts don't demonstrate meaningful rule/template validation
- [claude] I read the full 84KB diff and all artifacts. The Chinese-language content (check_run WARN messages, bench README, workflow docs) was understood without issues — the mixed Chinese/English is consistent with the rest of the Xunji codebase.
- [claude] The bench fixtures use synthetic data (app.example, fake endpoints). I'm confident this is test infrastructure, not real targets — confirmed by `bench/README.md` which states "它们只用于离线评估, 不含真实交战发现物."
- [claude] I did not verify the `recorded-closure-static-site` fixture sample_run files in detail because that fixture is pre-existing (not one of the 7 new ones). Its presence in the 18/18 clean score is sufficient.
- [claude] CNVD/CVE context is not relevant to this review (it's a code maintenance review, not a vulnerability assessment against a specific product).
