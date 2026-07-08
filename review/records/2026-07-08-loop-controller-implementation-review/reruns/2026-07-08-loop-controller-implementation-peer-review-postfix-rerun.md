# Peer Review Panel — 2026-07-08-loop-controller-implementation-review

_backend: panel:arkcli+claude · 2026-07-08T03:27Z_
> 候选, 非裁决。driver 须逐条过证据门。

## Verdict: WARN

_backend: panel:arkcli+claude_
_brain: codex_
_bundle_hash: c5a280efde0b30c227d9ac8ba03c145981b11109_
_evidence_index_hash: c1eac00c8c60515d141501466cff38ff63311f00_

## Findings
- [WARN] PR-001 report.md claims `python3 -m py_compile ...` was run and lists `evidence/py-compile.out` as a frozen artifact, but evidence_index marks that artifact missing. | Evidence: evidence_index:E-003 (py-compile.out exists:false), report.md:Verification Already Run, report.md:Frozen Artifacts | Why: [panel:arkcli] [arkcli:kimi-k2.7-code] Evidence discipline requires artifact-backed verification. A missing artifact for a claimed verification step prevents artifact cross-check and weakens confidence in the selftest coverage ledger.
- [WARN] PR-002 No evidence_index entry reaches certainty >= 0.8 or confirmed:true; the bundle contains only phenomenon/candidate artifacts. | Evidence: evidence_index entries E-001..E-008 (certainties <= 0.5, confirmed:false) | Why: [panel:arkcli] [arkcli:kimi-k2.7-code] The rubric permits confirmed findings only at certainty >= 0.8. The current ledger cannot support any confirmed security or behavior finding, which is consistent with the report's disclaimer but limits evidentiary strength.
- [WARN] PR-003 review.md and decisions.md are absent from the bundle, so there is no separate adjudication trail beyond report.md. | Evidence: review_bundle.files (report.md, evidence.md, target.md only) | Why: [panel:arkcli] [arkcli:kimi-k2.7-code] Without a separate decisions artifact, report narrative and adjudication are conflated, making it harder to verify that evidence was weighed independently.
- [WARN] PR-004 arkcli panel had backend errors; review is partial | Evidence: minimax-m3: parse error; output tail: laim": "Real-run validation (E-004) is a no-write snapshot, not a real execution; the controller state could differ in a real run",
      "evidence_refs": ["evidence_index:E-004", "evidence/scshr-real-run-validation.json"],
      "affected_eids": ["E-004"],
      "recommended_action": "Run the loop controller in a real-run mode and capture the resulting state files",
      "why": "Snapshot is structural validation only; it does not exercise the controller's write path"
    },
    {
      "id": " | Why: [panel:arkcli] At least one arkcli reviewer failed, so PASS only means the completed panel members found no blocker.
- [WARN] PR-005 `evidence/py-compile.out` artifact metadata inconsistent with disk state | Evidence: `evidence.json:119-121` shows `artifacts_missing: ["evidence/py-compile.out"]` and `evidence.json:7-8` shows `dangling_citations` for E-003; the file exists on disk (empty, likely py_compile success with no output) | Why: [panel:claude] The evidence index was generated before the artifact was frozen; subsequent runs of `check_run.py` would flag this as a dangling citation. The file should either be removed or the evidence index regenerated.
- [WARN] PR-006 `stale-wording-scan.out` command transcription is garbled/irreproducible | Evidence: `evidence/stale-wording-scan.out:1` reads `Command: rg -n Coda stop/Completion-pause stale wording in Claude/root loop paths` — this is not a valid rg invocation and cannot be reproduced from the transcript alone | Why: [panel:claude] The audit trail should contain reproducible commands. The actual patterns searched are implied but not explicit. This doesn't affect the correctness of the fix but reduces review auditability.
- [WARN] PR-007 Report does not acknowledge scope creep in the diff | Evidence: The implementation diff (120KB) includes changes beyond the loop-controller fix: agent-board SKILL.md threat hypothesis sections (lines 9-53 of diff), workers.py `merge-threats` command and `_new_threat_hypotheses()` (lines 2309+ of diff), WORKFLOW-reference.md Input Shape Catalog template (lines 188-213 of diff), and `js_inventory` tool registration. The report mentions only "Claude primary-driver docs updated" without surfacing these additional functional additions | Why: [panel:claude] An independent reviewer cannot assess whether these adjacent changes were reviewed with the same scrutiny as the core loop-controller fix.

## Blind-spot check
- [claude] **`_strip_fenced_code` regex fragility:** The regex `(?ms)^(```|~~~)[^\n]*\n.*?^\1[ \t]*\n?` uses a backreference to match closing fences. If `frontier.md` contains a code block with ` ``` ` that itself contains a differently-lengthed fence (e.g., an example showing ` ````` `), the regex could under-strip or over-strip. This is a known Markdown-regex limitation and unlikely to hit in practice, but worth noting since `_strip_fenced_code` is the gate preventing example F-IDs in fenced code blocks from being treated as real fronts.
- [claude] **Progress ledger doesn't check missing artifacts:** `progress_ledger.py:_artifact_backing()` checks `artifacts_present` but ignores `artifacts_missing`. An evidence entry claiming an artifact that doesn't exist on disk would still show `artifact_backed_progress=true` if other artifacts are present. `check_run.py` catches this separately, but the ledger's own `artifact_backed_progress` signal could be misleading if used in isolation.
- [claude] **Section-vs-status priority ambiguity:** When `frontier.md` section heading says "Deferred Fronts" but the front's status field says `open, blocked_type_a`, the code prioritizes the explicit status field over the section heading (line 1308-1310: section fallback only applies when raw status is empty/"unknown"). This is reasonable but undocumented behavior — a future maintainer might expect the section heading to win.
- [claude] **No adversarial test for `_strip_fenced_code` failure:** The selftest covers section-fallback with an example fenced-code block (F-999 in the test), but doesn't test edge cases like nested fences, empty code blocks, or code blocks with only whitespace content. A fenced code block containing a valid-looking `### F-xxx` heading with a `- Status: open, blocked_type_a` line would be a real-world parsing hazard.
- [claude] **Mentor hints could produce noisy "advisory only" warnings:** The `_mentor_hints()` function adds up to 7 different hint kinds per cycle. Since hints are written into `loop_state.md` and surfaced to the Root, there's a risk of alert fatigue — the Root might start ignoring mentor hints if they fire too frequently on routine states. The current trigger thresholds (2+ no-progress cycles, 2+ same-barrier failures) seem reasonable, but this is a behavioral concern, not a code defect.

## Context-limit notes
- [arkcli] minimax-m3: parse error; output tail: laim": "Real-run validation (E-004) is a no-write snapshot, not a real execution; the controller state could differ in a real run",
      "evidence_refs": ["evidence_index:E-004", "evidence/scshr-real-run-validation.json"],
      "affected_eids": ["E-004"],
      "recommended_action": "Run the loop controller in a real-run mode and capture the resulting state files",
      "why": "Snapshot is structural validation only; it does not exercise the controller's write path"
    },
    {
      "id": "
- [claude] I read the implementation diff in sections (lines 1-100, 100-300, 1141-1220, 1219-1418, 1418-1618, 1618-1818, 1818-2018, 2012-2288, 2288-2400) — approximately 90% of the 120KB diff. I may have missed changes at the very end of the diff (selftest_all.py additions beyond line 2300, workers.py changes beyond line 2400).
- [claude] The Chinese-language content in artifacts (e.g., `scshr-frontier-status-lines.out` lines with Chinese annotations like `wp-login 49次 Type B, REST全鉴权, xmlrpc禁用`) was readable but I may miss domain-specific nuances in Chinese red-team terminology.
- [claude] I did not test-run the actual Python tools against real run directories — my assessment is based solely on code review of the diff and artifact cross-check.