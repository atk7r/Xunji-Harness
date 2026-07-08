# Coverage Matrix Follow-up Review

- Date: 2026-07-06
- Author: Codex
- Scope: `tools/coverage_matrix.py`, `docs/templates/run/frontier.md`, `tools/peer_review.py`
- Trigger: follow-up fixes for the Claude Code / arkcli review issues found while landing the asset x vuln-family coverage matrix.

## Fixed

- Added explicit `Asset(s)` / `Target(s)` attribution for coverage-matrix fronts, including URL and `host:port` selftest coverage.
- Kept `Host:` out of explicit attribution to avoid confusion with HTTP Host header semantics.
- Added `Assets:` guidance to the run frontier template.
- Replaced the old 1200-character artifact snippet cutoff in `peer_review.py` with configurable `artifact_excerpt_chars` defaulting to 24000.
- Threaded artifact excerpt and bundle-size caps through `review()`, `review_panel()`, `--bundle-only`, and backend fallback paths.
- Made `max_bundle_chars` effective: bundle generation shrinks artifact excerpts when possible, records requested/effective caps, emits warnings when claims or evidence metadata still exceed the cap, and backend context caps use the smaller of backend limit and bundle cap.

## Review Results

### Claude Code direct

- Method: direct `claude -p` review from the repo root, not `tools/peer_review.py` Anthropic API backend.
- Limitation: local Claude Code still printed that an auth source takes precedence over claude.ai login even after unsetting `ANTHROPIC_AUTH_TOKEN`, `ANTHROPIC_API_KEY`, and `ANTHROPIC_BASE_URL` for the command.
- Final verdict: PASS.
- Findings: none at BLOCKER/WARN.
- Residual notes: `max_bundle_chars=0` acts as disabled/unlimited; `Target(s)` support is code-level convenience while `Assets:` is the documented template field.

### arkcli direct

- Method: direct `arkcli +chat` with the final diff in the prompt; no `@file` upload because the current Agent Plan does not support file input.
- Final verdict: PASS.
- Findings: none at BLOCKER/WARN.
- Residual notes: cosmetic/doc nits only; no gating issues.

## Verification

```bash
python3 -m py_compile tools/coverage_matrix.py tools/peer_review.py tools/check_run.py
python3 tools/coverage_matrix.py --selftest
python3 tools/peer_review.py --selftest
python3 tools/selftest_all.py --only coverage_matrix,peer_review,check_run --timeout 300
python3 tools/check_rules.py
```
