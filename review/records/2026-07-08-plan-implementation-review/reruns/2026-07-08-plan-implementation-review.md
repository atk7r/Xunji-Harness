# Peer Review Panel — 2026-07-08-plan-implementation-review

_backend: panel:arkcli+claude · 2026-07-07T22:01Z_
> 候选, 非裁决。driver 须逐条过证据门。

## Verdict: WARN

_backend: panel:arkcli+claude_
_brain: codex_
_bundle_hash: a9670e665a3c843d170c03ca19d1cd7d5e42f5cb_
_evidence_index_hash: 6f2facf22da955a1d79968bb07d80c63ecfc603f_

## Findings
- [BLOCKER] PR-001 Report treats multiple command-line verification results (selftests, bench 18/18, check_rules, check_templates, git diff --check) as established fact, but the evidence_index contains only the code diff (E-001, certainty 0.3) and no execution artifacts. | Evidence: report.md: section 'Verification Already Run', evidence_index: E-001 only (maturity phenomenon, certainty 0.3), evidence/implementation.diff (sha1 a881fbdac8b9e1ce29a48deafe5dc403f4e5ee52) | Why: [panel:arkcli] [arkcli:kimi-k2.7-code] A diff is not proof that the commands were run or produced the claimed results. Per the evidence gate, only certainty >= 0.8 backed by direct evidence may be reported as confirmed; these verification claims are unsupported.
- [BLOCKER] PR-002 Report's assurance that js_inventory.py is read-only over saved artifacts and performs no network target fetch is not backed by runtime or isolation evidence. | Evidence: report.md: Review Question 3, evidence_index: no entry for js_inventory.py runtime/network behavior, evidence/implementation.diff | Why: [panel:arkcli] [arkcli:kimi-k2.7-code] Source code in a diff shows intent but cannot prove absence of network activity at runtime. A control test or sandbox evidence entry is required.
- [WARN] PR-003 Only one evidence entry (E-001) covers the entire set of plan-implementation changes, so there is no per-change traceability to the five review questions. | Evidence: evidence_index: E-001 only, report.md: 'Main Changes' and 'Review Questions' | Why: [panel:arkcli] [arkcli:kimi-k2.7-code] A single diff entry makes it impossible to verify that each new mechanism was independently assessed for the risks the report claims to address.
- [WARN] PR-004 The '18/18 clean' bench score is asserted without an indexed bench JSON artifact or per-canary output. | Evidence: report.md: 'Verification Already Run' (bench score-all), evidence_index: lacks bench result entry | Why: [panel:arkcli] [arkcli:kimi-k2.7-code] Without the bench output, reviewers cannot confirm the canaries exercise the claimed failure modes or that the score is meaningful.
- [WARN] PR-005 Claims that new Agent instructions remain soft/advisory and do not bypass the evidence gate lack a control test or evidence entry. | Evidence: report.md: Review Questions 1 and 2, evidence/implementation.diff, evidence_index: no control-test entry | Why: [panel:arkcli] [arkcli:kimi-k2.7-code] Review question 1 explicitly asks whether Agents can promote findings/closure; the report answers by description only, with no proof the evidence gate still overrides hypotheses and hints.
- [WARN] PR-006 The sole supporting artifact evidence/implementation.diff is 84 KB and its content is not excerpted in the bundle, preventing line-level cross-check of reported changes. | Evidence: evidence_index E-001 artifact evidence/implementation.diff size 84509, egress_redaction settings | Why: [panel:arkcli] [arkcli:kimi-k2.7-code] Artifact cross-check requires reading the cited file; reviewers cannot verify the diff actually contains the described skill, tool, and template modifications.
- [WARN] PR-007 arkcli panel had backend errors; review is partial | Evidence: minimax-m3: parse error; output tail: o the "report" is the brief + verification log. The reviewer (me) needs to actually verify the claims.

So the things I should check:
- Is there a "decisions.md" or "review.md" with the answers? Looking at the bundle... no. Only report.md, evidence.md, target.md.
- The brief says "Review the Codex-authored implementation" and lists review questions. The author (Claude) ran the verifications and noted them. But where are the ANSWERS to the review questions?

This is actually a significant issue — | Why: [panel:arkcli] At least one arkcli reviewer failed, so PASS only means the completed panel members found no blocker.

## Blind-spot check
- [claude] **Regex edge cases not examined**: The `_blankish` regex `<[^>]*>` won't match multi-line template placeholders. The `_extract_calls` regexes in `js_inventory.py` won't match computed URLs (e.g., `fetch(baseUrl + '/api/x')`). The `_load_front_hypotheses` front-ID matching could false-match if a front ID appears in a URL or description. None of these edge cases are discussed.
- [claude] **No adversarial selftest coverage**: All selftests test happy paths — one well-formed hypothesis, one agent file, one JS bundle. No tests for: empty files, malformed markdown, BOM-prefixed files, extremely large hypotheses, concurrent modifications, files with mixed encodings, or `js_inventory.py` encountering a corrupted JSON file in the evidence directory.
- [claude] **The diff adds "pending" to `_blankish` but doesn't audit existing callers**: In `workers.py`, `_blankish` now returns True for "pending". This changes behavior for all existing callers (`_field`, `_int_field`, discipline checks, etc.). A field previously treated as "has a value" when set to "pending" is now treated as blank. The review doesn't check whether this semantic change breaks any existing agent or check behavior.
- [claude] **Chinese-language warning strings**: `check_run.py:504-508` emits warnings in Chinese. If a non-Chinese-speaking operator uses this toolkit, the warnings will be opaque. The review doesn't flag this as an accessibility/i18n concern.
- [claude] **The `_front_blocks_text` parsing pattern varies between files**: `loop_state.py` uses `(?ms)^###[ \t]+(F-\d+).*?(?=^###[ \t]+F-\d+|\Z)` while `check_run.py` uses `re.split(r"(?=^###\s+F-\d+)"` with multiline flag. These should produce the same results but use different approaches — another subtle duplication that could diverge.

## Context-limit notes
- [arkcli] [glm-5.2] The report claims "Verification Already Run" and lists several commands including `python3 tools/bench.py score-all bench --json-out /tmp/xunji-bench-after-plan.json -> 18/18 clean`.
- [arkcli] [glm-5.2] The evidence_index has NO entry for the test runs. There is no artifact for the bench scores or selftest outputs.
- [arkcli] [glm-5.2] The report's main objective is to "Judge whether the diff makes AI autonomous vulnerability discovery more likely..." but it doesn't actually provide a verdict or conclusion. It just lists the questions and the verification steps.
- [arkcli] [glm-5.2] The report doesn't cite E-001 or any evidence index entries.
- [arkcli] minimax-m3: parse error; output tail: o the "report" is the brief + verification log. The reviewer (me) needs to actually verify the claims.

So the things I should check:
- Is there a "decisions.md" or "review.md" with the answers? Looking at the bundle... no. Only report.md, evidence.md, target.md.
- The brief says "Review the Codex-authored implementation" and lists review questions. The author (Claude) ran the verifications and noted them. But where are the ANSWERS to the review questions?

This is actually a significant issue —
- [claude] This is a code/architecture review, not a vulnerability assessment — the "findings" rubric is applied to code quality and safety concerns rather than security vulnerabilities. Certainty 0.3 for E-001 is correct for a maintenance artifact.
- [claude] The bench canary files are synthetic fixtures — I cannot verify they exercise real attack paths since they contain placeholder data. This is inherent to synthetic benchmarks, not a flaw.
- [claude] The Chinese-language content in `check_run.py` warnings and `bench/README.md` was read via the diff; my assessment of the warning strings' correctness relies on the English field names and structural patterns rather than the Chinese prose content.
