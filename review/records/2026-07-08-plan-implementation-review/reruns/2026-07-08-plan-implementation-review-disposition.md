# Disposition — Plan Implementation Review

Review records:

- Initial review: `review/records/2026-07-08-plan-implementation-review.md`
- Evidence-improved rerun: `review/records/2026-07-08-plan-implementation-review-rerun.md`
- Final rerun: `review/records/2026-07-08-plan-implementation-review-final.md`

Final verdict: WARN, no BLOCKER.

## Findings

### PR-001 — artifact contents not included in bundle

- Status: accepted as review-evidence limitation
- DriverResolution: Evidence: final review context notes Claude read the full `evidence/bench-score-all.json` and full text output; all artifacts exist and are indexed under E-002 through E-006. No implementation change required.

### PR-002 — bench fixture E-001 confused with review E-001

- Status: dismissed
- DriverResolution: Reason: bench `matched_eid` values are per-fixture sample-run evidence IDs, not review-bundle evidence IDs. They intentionally live in separate run directories and do not refer to `review/.../evidence.md` E-001.

### PR-003 — source diff represented by low-certainty E-001

- Status: dismissed
- DriverResolution: Reason: E-001 is correctly a phenomenon artifact for the maintenance diff, not proof of behavior. Behavior claims are supported by command artifacts E-002 through E-006 and the final peer review.

### PR-004 — new canaries have recorded_requests=0

- Status: accepted as residual limitation
- DriverResolution: Evidence: report.md `Residual Limits` explicitly records that the new fixtures are process canaries, not live HTTP A/B runs. This is aligned with the optimized plan's Phase 0 short-term yardstick; live-yield proof remains future work.

### PR-005 — js_inventory no-network evidence is limited

- Status: accepted with mitigation
- DriverResolution: Evidence: E-005 adds both a runtime socket/urlopen monkeypatch control and an AST/source audit. This is enough for the local read-only tool boundary; stronger isolation can be added later if `js_inventory.py` grows new IO paths.

### PR-006 — E-002/E-006 reuse selftest artifacts

- Status: accepted as presentation issue
- DriverResolution: Reason: E-002 records aggregate verification; E-006 records per-change traceability using the same command outputs. This does not create independent evidence, and final report language should not count them as separate proof sources.

### PR-007 — arkcli panel backend errors

- Status: accepted as review limitation
- DriverResolution: Evidence: final review still completed with `panel:arkcli+claude` and no BLOCKER. Some arkcli panel legs had parse errors; this is recorded and not hidden.

## Residual Risk

- Synthetic canaries prove framework signals and regression behavior, not real target yield.
- Request-budget metrics remain weaker for process-only fixtures with no replay/events.
- `merge-threats` now labels Agent text as untrusted candidate material, but Root still must avoid copying target-controlled prose into reports without rewriting/verification.
