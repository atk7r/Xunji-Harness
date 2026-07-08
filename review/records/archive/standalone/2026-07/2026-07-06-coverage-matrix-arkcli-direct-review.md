# Coverage Matrix Arkcli Direct Review

- Date: 2026-07-06
- Author: Codex
- Reviewer: arkcli `+chat` direct, pure text prompt
- Scope: `tools/coverage_matrix.py`, `tools/check_run.py`, `tools/selftest_all.py`, `CLAUDE.md`, `docs/WORKFLOW.md`
- Verdict: WARN
- diff_fingerprint: 6904c8b11651c5fb
- Note: `--input @file` was unsupported by the current Agent Plan, so the full diff/source/test log was sent as text. A previous `peer_review.py --panel-backends arkcli` attempt is treated as input-packaging failure because its artifact excerpts truncated the implementation under review.

## Arkcli Verdict

PASS overall, with WARN findings.

## Findings And Driver Resolution

### PR-001 -- WARN -- Coda improvement term under-specified

- Claim: `coverage-matrix improvement` was added to the Coda convergence gate without defining what counts as improvement, creating pressure to fill cells.
- Evidence: `CLAUDE.md` convergence-gate diff.
- DriverResolution: accepted. `CLAUDE.md` now defines improvement as a previously `□` cell becoming tested through a recorded front/evidence update; relabeling, unsupported applicability, or firing a class only to fill a cell does not count.
- Status: accepted

### PR-002 -- WARN -- XXE overlap could mark multiple groups tested

- Claim: `XXE` appeared under both `SSRF` and `Upload`, so one XXE attempt could mark both families as tested and hide gaps.
- Evidence: `tools/coverage_matrix.py` `GROUPS`.
- DriverResolution: accepted. Split `XXE` into its own matrix group; removed `XXE` from `SSRF` and `Upload`.
- Status: accepted

### PR-003 -- WARN -- free-text keyword heuristics too broad

- Claim: Applicability keywords such as `auth`, `api`, and `admin` were checked across noisy free-text fields like title/note/stack, which could create false `□` gaps.
- Evidence: `tools/coverage_matrix.py` `_asset_subtypes`.
- DriverResolution: accepted. Keyword fallback is now limited to inventory/category fields plus host naming; live body-derived signals should arrive as `SURFACE:*` flags. Added selftest that title `Admin API docs` does not create applicability by itself.
- Status: accepted

## Additional Blind Spots Recorded

- Front-to-asset attribution still requires a literal host token in the front text. If a front is written only as a feature name, the matrix may not credit it to the asset. This is an acceptable residual risk for the first advisory version and should be considered for a later front metadata field.
- The matrix remains warning-only in `check_run.py`; future changes must not turn coverage warnings into hard errors without a separate review.

## Verification After Fixes

```text
python3 -m py_compile tools/coverage_matrix.py tools/check_run.py
python3 tools/coverage_matrix.py --selftest
python3 tools/selftest_all.py --only coverage_matrix,saturation,check_run --timeout 300
python3 tools/check_rules.py
```

All passed after applying the arkcli findings.
