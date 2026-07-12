# Maintenance Evidence

## E-001 - Agent runtime and assignment enforcement diff
- Maturity: finding
- Action: Review async launch/return modeling, actor-scoped gates, persistent coordination epochs, exact asset prompt binding, and per-asset merge validation.
- Result: Codex-authored implementation with targeted regression tests embedded in runtime_receipts.py, turn_contract.py, and workers.py.
- Certainty: 1.0
- Control: `python3 tools/runtime_receipts.py --selftest`, `python3 tools/turn_contract.py --selftest`, and `python3 tools/workers.py --selftest` all passed.
- Replicated: Full `python3 tools/selftest_all.py` passed 57/57 suites.
- Artifacts: evidence/runtime-receipts.diff, evidence/runtime-agent-activity.py.txt, evidence/turn-contract.diff, evidence/workers.diff, evidence/workers-asset-merge.py.txt
- Supports: F-001

## E-002 - Asset ledger and coverage enforcement diff
- Maturity: finding
- Action: Review stable asset inventory, out-of-scope accounting, front linkage, evidence-only tested cells, closure debt, setup initialization, loop steering, and statusline counters.
- Result: Full in-scope ledger is retained; reachable/unknown unassigned assets block target traffic; multi-asset front prose cannot create tested coverage.
- Certainty: 1.0
- Control: `coverage_matrix.py`, `ingest_recon.py`, `setup_run.py`, `loop_state.py`, and `xunji_statusline.py` selftests passed.
- Replicated: Current Hamastar run derives total=80, reachable=15, unknown=18, unreachable=47, front-linked=29, unassigned=11, closure-debt=25 without writing the run.
- Artifacts: evidence/asset-coverage.diff
- Supports: F-002

## E-003 - Proxy and differential evidence diff
- Maturity: finding
- Action: Review default proxy fail-closed behavior, raw target-client denial, target WebFetch denial, and DIFF two-side save/replay behavior.
- Result: Proxy enforcement no longer depends on an Agent export reminder; DIFF saves A/B bodies and both replay records.
- Certainty: 1.0
- Control: `python3 tools/harness/proxy.py --selftest` and `python3 tools/probe.py --selftest` passed, including local loopback proof.
- Replicated: Full selftest suite passed with proxy-aware imports and sensors.
- Artifacts: evidence/proxy-diff-save.diff, evidence/turn-contract-egress.py.txt
- Supports: F-003

## E-004 - Claude driver and documentation diff
- Maturity: finding
- Action: Review whether CLAUDE.md, primary Claude skills, workflow docs, router, setup guide, loop prompt, Agent templates, and Codex maintenance guide agree with implementation.
- Result: Commands require explicit asset packages; docs distinguish async launch from SubagentStop return and explain persistent epochs and proxy defaults.
- Certainty: 1.0
- Control: `python3 tools/check_rules.py`, `python3 tools/check_templates.py`, `python3 tools/check_hook.py`, and `python3 tools/check_runtime_boundary.py` passed.
- Replicated: Repository-wide stale-token search found no remaining two-token Agent launch contract in active guidance.
- Artifacts: evidence/driver-docs.diff
- Supports: F-004
