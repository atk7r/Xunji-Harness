# Evidence Ledger

## E-001

- Maturity: phenomenon
- Certainty: 0.3
- Source: local-maintenance-diff
- Result: Frozen implementation diff for independent maintenance review.
- Artifacts: evidence/implementation.diff
- Supports: maintenance review context

## E-002

- Maturity: finding
- Certainty: 0.8
- Source: local-command-output
- Result: Selected selftest suite passed: check_run, bench, check_templates, js_inventory, context_pack, loop_state, workers.
- Control: command output captured after implementation with exit code 0
- Artifacts: evidence/selftest-selected.out, evidence/workers-selftest.out, evidence/context-pack-selftest.out, evidence/check-run-selftest.out, evidence/loop-state-selftest.out, evidence/js-inventory-selftest.out, evidence/bench-selftest.out
- Supports: verification claims

## E-003

- Maturity: finding
- Certainty: 0.8
- Source: local-command-output
- Result: `tools/bench.py score-all bench` reported 18/18 clean with 100% detection/calibration and zero false positives.
- Control: JSON and text outputs captured after implementation with exit code 0
- Artifacts: evidence/bench-score-all.out, evidence/bench-score-all.json
- Supports: canary and regression claims

## E-004

- Maturity: finding
- Certainty: 0.8
- Source: local-command-output
- Result: `tools/check_rules.py`, `tools/check_templates.py`, and `git diff --check` completed without errors.
- Control: command outputs captured after implementation with exit code 0
- Artifacts: evidence/check-rules.out, evidence/check-templates.out, evidence/git-diff-check.out
- Supports: static verification claims

## E-005

- Maturity: finding
- Certainty: 0.8
- Source: local-command-output
- Result: `tools/js_inventory.py` completed inventory while socket and urllib network calls were monkeypatched to fail; source audit found no network client imports/calls.
- Control: runtime no-network control plus AST/source audit; any target network fetch through these standard paths would have raised
- Artifacts: evidence/js-inventory-no-network-control.out, evidence/js-inventory-source-audit.out
- Supports: js_inventory read-only claim

## E-006

- Maturity: finding
- Certainty: 0.8
- Source: local-command-output
- Result: Individual tool selftests exercise the new mechanisms: `workers.py` covers merge-threats and Agent threat discipline; `context_pack.py` covers relevant threat hypothesis injection; `check_run.py` covers high-threat public no-H/next/E WARN; `loop_state.py` covers mentor hints; `js_inventory.py` covers saved-artifact extraction.
- Control: individual outputs captured after implementation with exit code 0
- Artifacts: evidence/workers-selftest.out, evidence/context-pack-selftest.out, evidence/check-run-selftest.out, evidence/loop-state-selftest.out, evidence/js-inventory-selftest.out
- Supports: per-change traceability
