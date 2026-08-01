# Evidence Ledger

## E-001 — Reviewed staged diff

- Maturity: finding
- Certainty: 1.0
- Action: captured the full staged maintenance diff for independent review.
- Result: `reviewed.diff` contains the Codex-authored changes under review.
- Control: SHA1 recorded in `context.md` and `report.md`.
- Artifacts: `reviewed.diff`

## E-002 — Full selftest output

- Maturity: finding
- Certainty: 1.0
- Action: ran `python3 tools/selftest_all.py --timeout 600`.
- Result: 54 passed, 0 failed.
- Control: raw stdout/stderr captured for reviewer cross-check.
- Artifacts: `selftest_all.log`

## E-003 — Latest run structural check

- Maturity: finding
- Certainty: 1.0
- Action: ran `python3 tools/check_run.py runs/hamastar_20260709-test1_20260709`.
- Result: run check passed with warnings only.
- Control: raw stdout/stderr captured for reviewer cross-check.
- Artifacts: `check_run_hamastar.log`

## E-004 — Framework/knowledge/template checks

- Maturity: finding
- Certainty: 1.0
- Action: ran knowledge, template, runtime-boundary, and closure-audit checks.
- Result: all checks passed.
- Control: raw stdout/stderr captured for reviewer cross-check.
- Artifacts: `framework_checks.log`

## E-005 — Git whitespace checks

- Maturity: finding
- Certainty: 1.0
- Action: ran `git diff --check && git diff --cached --check`.
- Result: both commands exited 0.
- Control: explicit pass log plus command exit status from the shell invocation.
- Artifacts: `diff_check.log`

## E-006 — Output gate real-run subprocess regression

- Maturity: finding
- Certainty: 1.0
- Action: ran `python3 .claude/hooks/output_gate.py --selftest`.
- Result: selftest passed, including a hook subprocess against a temporary real runs root with an open front.
- Control: raw stdout/stderr captured for reviewer cross-check.
- Artifacts: `output_gate_selftest.log`

## E-007 — check_run retrospective/status gate regression

- Maturity: finding
- Certainty: 1.0
- Action: ran `python3 tools/check_run.py --selftest`.
- Result: selftest passed, including retrospective framework-status and evidence artifact parsing cases.
- Control: raw stdout/stderr captured for reviewer cross-check.
- Artifacts: `check_run_selftest.log`

## E-008 — Captcha OCR real sample smoke

- Maturity: observation
- Certainty: 1.0
- Action: ran `python3 tools/captcha_ocr.py captcha-ocr.gif --psm 7 --psm 8 --psm 13 --timeout 10`.
- Result: local tesseract processed the real sample image and returned non-empty OCR text; the all-empty barrier branch is covered by selftest_all/captcha_ocr selftest.
- Control: raw JSON captured for reviewer cross-check.
- Artifacts: `captcha_ocr_sample.json`

## E-009 — Latest run loop-state/statusline source snapshot

- Maturity: finding
- Certainty: 1.0
- Action: ran `python3 tools/loop_state.py runs/hamastar_20260709-test1_20260709`.
- Result: latest run derives open 0 / deferred 6 / closed 4 and closure-review candidate state.
- Control: raw stdout/stderr captured for reviewer cross-check.
- Artifacts: `loop_state_hamastar.log`

## E-010 — Coverage sync closed_type_b regression

- Maturity: finding
- Certainty: 1.0
- Action: ran `python3 tools/coverage_matrix.py --selftest` and `python3 tools/coverage_matrix.py runs/hamastar_20260709-test1_20260709 --write --sync-coverage --json`.
- Result: coverage selftest passed, including `closed_type_b` -> `closed` verdict sync; latest run sync reports changed=0 because the prior sync already updated coverage.json.
- Control: raw stdout/stderr and JSON output captured for reviewer cross-check.
- Artifacts: `coverage_matrix_selftest.log`, `coverage_sync_hamastar.json`
