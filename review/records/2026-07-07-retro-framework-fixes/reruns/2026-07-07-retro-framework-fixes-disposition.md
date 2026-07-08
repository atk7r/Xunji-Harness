# Driver Disposition — Retrospective Framework Fixes

- Verdict: WARN
- Time: 2026-07-07
- Author: Codex
- Review scope: `review/records/2026-07-07-retro-framework-fixes/`
- Final review bundle hash: `825d7b705ecee1ed6362729233f243a8352cf75f`
- Final evidence index hash: `da1596a8f4fa782370013c24f48c758d99110209`
- diff_fingerprint: c173034eb8c49adc
- Independent review available: arkcli panel. Claude Code/API reviewer was unavailable in this environment; this is recorded as a limitation, not counted as a Codex self-review.

## Dispositions

### PR-001 — workers.py status sync may mark barrier-only notes done

- Status: accepted/fixed.
- Resolution: `_has_completion_findings` no longer treats `Barrier` or `Next-evidence` fields as completion markers and rejects investigatory placeholders such as `Candidate: still investigating`. It still treats explicit result/candidate/refutation/evidence/control/verdict lines and common negative-completion phrases as assignment completion. This updates assignment state only; it does not close fronts or promote findings.
- Verification: `python3 tools/workers.py --selftest`; `python3 tools/selftest_all.py` artifact `evidence/selftest_all.txt`.

### PR-002 — coverage_matrix evidence-derived groups may over-credit classes

- Status: accepted/fixed.
- Resolution: evidence-derived groups now require `Certainty >= 0.5`, scan only tested/proven fields (`Action`, `Result`, `Control`, `Replicated`, `Status`, `Verdict`), and avoid known overlapping signals (`APP_KEY`, generic version disclosure, org-ID). Added regression tests for bare HTTP status, low-cert auth clues, and SQLi mentioned only in a confounder note.
- Verification: `python3 tools/coverage_matrix.py --selftest`; `python3 tools/selftest_all.py` artifact `evidence/selftest_all.txt`.

### PR-003 — maintenance review relies on selftests and one local evidence entry

- Status: accepted limitation.
- Resolution: added review-scope `evidence.md` and command-output artifacts so the review bundle is no longer prose-only. This remains a repository maintenance review, not a fresh target-run audit. The ignored run directory is intentionally not committed.
- Verification: final review bundle/evidence hashes above; artifacts under `review/records/2026-07-07-retro-framework-fixes/evidence/`.

### PR-004 — broad report-maturity `not confirmed` heading regex

- Status: accepted/fixed.
- Resolution: removed the broad `.*not confirmed.*` heading branch and kept explicit lower-maturity section names (`Candidate / Phenomena`, `Background Evidence`, `False-Positive Review`, `Open Questions`, `Not-Confirmed Findings`).
- Verification: `python3 tools/check_run.py --selftest`; `python3 tools/selftest_all.py` artifact `evidence/selftest_all.txt`.

### PR-005 — artifact shorthand relaxation remains heuristic

- Status: accepted/residual warning.
- Resolution: parser remains intentionally strict for concrete artifact tokens while ignoring common shorthand/glob prose. Added regression coverage for `(+.replay.json)`, `*.replay.json`, `evidence/glob_*.html`, `evidence/*.html`, and `file.txt*` footnote/marker syntax so glob forms do not create dead-reference noise and footnote markers do not hide real artifacts. Unknown shorthand can still warn and should be rewritten to concrete artifact paths.
- Verification: `python3 tools/check_run.py --selftest`; `python3 tools/selftest_all.py` artifact `evidence/selftest_all.txt`.

### PR-006 — review panel partial failures / missing Claude reviewer

- Status: accepted limitation.
- Resolution: arkcli panel was run repeatedly and findings above were adjudicated. Some arkcli sub-results had parser errors and Claude Code/API review was unavailable, so this is not a full arkcli+Claude matrix. The limitation is recorded here per AGENTS.md and the Codex-authored maintenance matrix.

## Residual Risk

- `runs/oppo_20260707_20260707/` contains local ignored run-record fixes and passes ordinary `check_run`, but those ignored files are not part of this commit.
- Full live replay for the target run was intentionally interrupted after the guard warned about 90 requests to one host. Local replay selftests pass; target replay drift is not claimed as fully reverified in this maintenance commit.
