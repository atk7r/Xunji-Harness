# Claude Fresh-Context Review — Personalized RDT Subagents

_backend: claude CLI · driver=codex · read-only prompt · 2026-07-07_

## Verdict: WARN

## Findings

- [WARN] Fingerprint binding to untracked template creates audit-trail fragility | Evidence: `decisions.md#D-001`, `review/review_bundle.json:claims.decisions.md` | Why: The original diff fingerprint included `docs/templates/run/operator_profile.json` while it was untracked. If edited before staging, the binding could drift.
- [WARN] E-001 certainty 1.0 initially rested on prose summaries; now backed by raw artifacts but those artifacts were post-hoc additions | Evidence: `evidence.md#E-001`, `implementation-grep.txt`, `raw-test-transcript.txt`, `scaffold-context-sample.txt` | Why: The added artifacts support the claim, but the review trail should record that they were added after the first arkcli finding.
- [WARN] `_front_profile` regex ordering is first-match-wins with no tie-breaking for ambiguous front texts | Evidence: `tools/context_pack.py` `_FRONT_PROFILE_RULES` and `_front_profile` | Why: Generic role/front text can match `candidate_verification` before `auth_sso_token_signature`; low severity because `max(role_budget, front_budget)` mitigates budget under-allocation.
- [WARN] No selftest for profile JSON edge cases | Evidence: `tools/context_pack.py` profile loader and original selftest fixture | Why: malformed/non-numeric profile values were untested and could crash `int()` casts.
- [WARN] Panel review was partial | Evidence: `peer_review.py` output and `review/review_bundle.json` | Why: minimax-m3 and glm-5.2 parse errors, Claude API unavailable; effective automated panel was single-backend until this direct Claude CLI supplement.

## Blind-Spot Check

- Convergence gate interaction with loop budget remains a future behavior test.
- Profile numeric fields need safe type handling.
- Future list-valued profile fields may need merge semantics beyond replacement.
- Shared barrier budget pooling is not implemented; current budgets are per-agent hints.
- `setup_run --classify` profile scaffolding interaction is not separately tested.

## Context-Limit Notes

- The review scope is a maintenance bundle, not a live target run.
- The implementation grep artifact shows no OpenMythos import dependency in in-scope files.
- The scaffold/context sample verifies the profile to scaffold to context-pack path.

