# Coverage Matrix Codex Maintenance Review

- Date: 2026-07-06
- Author: Codex
- Review target: `tools/coverage_matrix.py`, `tools/check_run.py`, `tools/selftest_all.py`, `CLAUDE.md`, `docs/WORKFLOW.md`
- Independent reviewer: Claude Code CLI direct (`claude -p`), fresh context
- Verdict: WARN
- diff_fingerprint: 6904c8b11651c5fb
- Note: Claude API backend was not used. An earlier arkcli-only peer_review attempt was incomplete for this diff and is superseded by this direct Claude Code review plus the fixes below.

## Reviewer Verdict

WARN, no blockers.

## Findings And Driver Resolution

### PR-001 -- WARN -- keyword substring false positives

- Claim: `coverage_matrix.py` matched short keywords as arbitrary substrings, so strings such as `profile` could trigger the `file-download` subtype and false `PathTraversal` / `InfoLeak` gaps.
- Evidence: `tools/coverage_matrix.py` keyword matching in `_asset_subtypes`.
- DriverResolution: accepted. Replaced substring matching with `_keyword_present()` using alnum boundaries. Added selftest coverage for `profile.example` not triggering file-download categories.
- Status: accepted

### PR-002 -- WARN -- corrupt primary coverage fallback was silent

- Claim: `_load_coverage()` swallowed JSON parse errors and could fall through to another `coverage.json` without warning.
- Evidence: `tools/coverage_matrix.py` coverage loader.
- DriverResolution: accepted. `_load_coverage()` now returns parse warnings; `check()` surfaces them as matrix warnings. Added selftest for corrupt root `coverage.json` plus nested fallback.
- Status: accepted

### PR-003 -- WARN -- fallback canonicalization undercounts on import failure

- Claim: fallback `_canonical()` only stripped whitespace, so if importing `saturation` failed, case variants like `sqli` could fail group matching.
- Evidence: `tools/coverage_matrix.py` fallback import block.
- DriverResolution: accepted. Fallback `_canonical()` now lowercases; group map and parsed vectors share the same fallback normalization.
- Status: accepted

## Verification

```text
python3 -m py_compile tools/coverage_matrix.py tools/check_run.py
python3 tools/coverage_matrix.py --selftest
python3 tools/selftest_all.py --only coverage_matrix,saturation,check_run --timeout 300
```

All passed after the fixes.
