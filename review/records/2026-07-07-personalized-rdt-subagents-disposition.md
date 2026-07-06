# Disposition — Personalized RDT Subagents

- Driver: Codex code-maintenance mode
- Functional diff fingerprint: `d0a4c06ecafe953e`
- diff_fingerprint: 1604edfeb7ae3b9c
- reviewed_diff: 1604edfeb7ae3b9c
- Review scope: `review/records/2026-07-07-personalized-rdt-subagents/`
- Arkcli/peer_review record: `review/records/2026-07-07-personalized-rdt-subagents-peer-review.md`
- Claude fresh-context record: `review/records/2026-07-07-personalized-rdt-subagents-claude-review.md`
- Verdict: WARN

## Findings Disposition

| Finding | Disposition |
|---|---|
| Arkcli PR-001: evidence was summary-only. | Accepted and fixed. Added `implementation-grep.txt`, `raw-test-transcript.txt`, and `scaffold-context-sample.txt`; updated `evidence.md` artifact list. |
| Arkcli/Claude: fingerprint fragility around untracked template. | Accepted and fixed. Review scope now records a functional fingerprint that excludes `review/records/` and includes the new operator profile template explicitly. |
| Arkcli PR-003: compatibility check needs proof for partial RDT markers. | Accepted as already covered after implementation. `tools/workers.py --selftest` includes `agent-check catches incomplete personalized RDT step`; OPPO old-run `agent-check` is clean. |
| Claude: malformed numeric profile values can crash `int()` casts. | Accepted and fixed. Added `_as_int()` fallback, stopped `web-auth` from falling back to `web-hunter`, and added malformed numeric profile selftest. |
| Operator correction: primary-driver skill guidance belongs in `.claude/skills/`, not `.agents/skills/`. | Accepted and fixed. Updated `.claude/skills/xunji-agent-board/SKILL.md`; `.agents/skills/` remains Codex-side guidance. |
| Operator correction: encode the default-target boundary in `AGENTS.md`. | Accepted and fixed. Added `Default Edit Target`; Claude fresh-context review of the AGENTS diff returned PASS. |
| Claude: `_front_profile` first-match ordering can be ambiguous. | Dismissed as non-blocking residual. `max(role_budget, front_budget)` prevents budget under-allocation for the observed default families; future front-profile weighting can improve precision. |
| Panel/backend errors. | Accepted limitation. `peer_review.py` arkcli panel completed one coherent backend and had parse errors in two arkcli model outputs; Claude API backend was unavailable. Supplemented with direct `claude -p` fresh-context review using read-only/no-write prompt. |

## Residual Risk

- Loop budget is advisory prompt/context shape, not an enforced scheduler. A future convergence-gate test can check how agents report budget exhaustion.
- Shared barrier group budget pooling remains Root/guard discipline; this change does not implement cross-agent budget pooling.
- The profile is stored under `state/operator_profile.json`; docs now state it is preference only and cannot overwrite Markdown evidence or safety rules.

## Verification After Fixes

- `python3 tools/context_pack.py --selftest`
- `python3 tools/workers.py --selftest`
- `python3 tools/setup_run.py --selftest`
- `python3 tools/selftest_all.py --only context_pack,workers,setup_run,check_templates`
- `python3 -m py_compile tools/context_pack.py tools/workers.py tools/setup_run.py`
- `python3 tools/workers.py agent-check runs/oppo_20260707_20260707`
- `python3 tools/check_run.py runs/oppo_20260707_20260707`
- `python3 tools/saturation.py --selftest`
- `python3 tools/check_rules.py`
- `git diff --check`
- Claude fresh-context review of `AGENTS.md` boundary diff: PASS
