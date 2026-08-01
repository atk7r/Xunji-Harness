# Codex Maintenance Review Context

Scope: Codex-authored framework/tooling fixes derived from `runs/oppo_20260707_20260707/retrospective.md`.

Changed tracked files:

- `docs/templates/run/evidence.md`
- `tools/evidence_parse.py`
- `tools/check_run.py`
- `tools/check_knowledge.py`
- `tools/selftest_all.py`
- `tools/probe.py`
- `tools/coverage_matrix.py`
- `tools/workers.py`

Intent:

- Fix evidence artifact parsing fragility around `Artifacts (...)` labels and shorthand notes such as `(+.replay.json)` / glob prose.
- Fix report maturity false positives for explicitly lower-maturity context sections.
- Avoid Guanlan adapter coverage false positives when the adapter is intentionally scoped and not a raw recon mirror.
- Make `check_knowledge.py --selftest` enforce inline JSON signatures, reject invisible YAML signatures, and reject public payload headings.
- Add `probe.py --range` for large JS/body inspection without changing the 256KB safety cap.
- Make `coverage_matrix.py` reflect evidence-derived coverage and stop marking generic param APIs as SSRF without SSRF/url-fetch signal.
- Make `workers.py status` sync assignment state to `done` when agent files are complete or contain `## Findings`.
- Inline the canonical certainty scale in the evidence template.

Review questions:

1. Does any parser change weaken evidence gates, especially confirmed evidence artifact requirements?
2. Are the ignored shorthand/glob artifact tokens narrow enough to avoid hiding real missing artifacts?
3. Does evidence-derived coverage over-credit assets or vulnerability classes?
4. Does workers status auto-sync risk marking incomplete agents done?
5. Does `probe.py --range` preserve caller-supplied headers and avoid bypassing proxy/guard logic?
6. Are tests broad enough for the framework regressions named in the retrospective?
