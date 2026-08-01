# Decisions

## D-001

- Driver: Codex code-maintenance mode
- Request: continue from personalized OpenMythos-inspired subagent enhancement plan
- Decision: implement as a thin per-run preference/config layer on the existing Agent Board, not as an OpenMythos dependency or separate runtime.
- Functional diff fingerprint: `d0a4c06ecafe953e`
- Fingerprint scope: `AGENTS.md`, `.claude/skills/xunji-agent-board/SKILL.md`, `docs/WORKFLOW-reference.md`, `docs/templates/agents/`, `docs/templates/run/operator_profile.json`, `tools/context_pack.py`, `tools/setup_run.py`, `tools/workers.py`.
- Reason: review artifacts under `review/records/` are excluded from this functional fingerprint, so the review record can evolve without changing the implementation fingerprint it adjudicates.

## D-002

- Boundary: no changes under `.claude/hooks/`, `tools/harness/guard.py`, or `sentinel/`.
- Safety rationale: Agent personalization changes prompt shape, loop budget, and context hints only. It does not alter guard/hook enforcement, target egress, request budgets, or evidence promotion.

## D-003

- Compatibility adjustment: old agent files no longer emit personalized-RDT warnings unless they declare the new `personalized-rdt` markers.
- Reason: the first implementation made `tools/workers.py agent-check runs/oppo_20260707_20260707` return 24 warnings against historical agent files. That was too noisy for framework ergonomics.
- Verification: after narrowing the check, `agent-check` on the OPPO run is clean while the selftest still catches incomplete new RDT steps.

## D-004

- Peer-review fix: Claude fresh-context review found malformed numeric profile values could crash `resolve_rdt_profile()`.
- Resolution: added `_as_int()` fallback handling, stopped `web-auth` from falling back to `web-hunter`, and added a selftest for malformed numeric profile values.
- Verification: `python3 tools/context_pack.py --selftest`, `python3 tools/workers.py --selftest`, and `python3 tools/selftest_all.py --only context_pack,workers,setup_run,check_templates` passed after the fix.

## D-005

- Operator correction: Claude Code is the primary live driver, so primary-driver skill guidance must live in `.claude/skills/`; `.agents/skills/` is Codex-side guidance.
- Resolution: updated `.claude/skills/xunji-agent-board/SKILL.md` with the personalized RDT / operator profile workflow and an explicit `.agents/skills/` boundary note.
- Verification: `rg -n "Personalized RDT|operator_profile|\\.agents/skills|Loop budget|openmythos-inspired|Reasoning style" .claude/skills/xunji-agent-board/SKILL.md` shows the intended guidance; `check_rules`, targeted selftests, and `git diff --check` pass.

## D-006

- Operator correction: write the default-target boundary into `AGENTS.md` so Codex does not repeat the `.agents/skills` vs `.claude/skills` mistake.
- Resolution: added `Default Edit Target` section: ambiguous framework/Root/subagent/skills requests default to Claude Code primary-driver behavior and `.claude/skills/`; `.agents/skills/` is Codex-side unless explicitly requested.
- Verification: Claude fresh-context review of the `AGENTS.md` diff returned PASS; `check_rules` and `git diff --check` pass.
