# Evidence Ledger

> Certainty: use only the canonical scale: `1.0` direct/reproducible,
> `0.8` controlled/replayed confirmed, `0.5` suspected candidate, `0.3` clue/noise.

## E-001 - Claude-side web-research skills referenced a missing evidence recorder;

- Maturity: finding
- Reportable: yes
- Time: 2026-07-06T23:03:38Z
- Action: Web research query: web-research record_evidence closure
- Source: source-code-review
- Trust: operator-reviewed
- Query: web-research record_evidence closure
- Result: Claude-side web-research skills referenced a missing evidence recorder; tools/record_evidence.py now provides canonical E-entry writing, conservative web-research maturity defaults, template E-001 replacement, selftest coverage, and aggregate selftest registration.
- Provenance: evidence/diff.patch
- Caused by us: no
- Alternative explanation: Recorded source may be stale, wrong, incomplete, or not applicable until verified against current target artifacts.
- Certainty: 0.8
- Replicated / Control: Post-fix command scan shows all_doc_python_commands 160 missing 0 and all_selftests 42 not_registered 0; targeted selftests passed; full selftest_all passed 46/46; check_rules, check_templates, runtime_boundary, py_compile, and git diff --check passed.
- Artifacts: evidence/diff.patch, evidence/selftest_all_full.txt, evidence/selftest_all.txt, evidence/closure_scan.txt, evidence/check_rules.txt, evidence/check_templates.txt, evidence/check_runtime_boundary.txt, evidence/git_diff_check.txt, evidence/py_compile.txt
- Supports: H-001
- Refutes: -
- Next: Peer-review findings were adjudicated in the disposition record.
