# Claude Fresh-Context Skill Review — Personalized RDT Root Guidance

_backend: claude CLI · driver=codex · read-only prompt · 2026-07-07_

## Verdict: PASS

## Findings

- [PASS] Profile-to-code consistency is accurate. The skill correctly describes `setup_run.py` scaffolding `state/operator_profile.json`, `context_pack.py` injecting the resolved RDT profile, and `workers.py assign` copying loop budget/profile source into agent records.
- [PASS] Guard/evidence discipline is explicitly preserved. The skill says the profile is not evidence, not a guard override, not target authorization, and not authority to promote a candidate. It also states loop budget does not change request budget, hook/guard limits, host breakers, or Shared Barrier Group budgets.
- [PASS] OpenMythos scoping is correct. The skill limits `openmythos-inspired` to reasoning shape and forbids importing/running OpenMythos or making it a target network executor.
- [PASS] Skill placement is correct. `.claude/skills/` is Claude primary-driver guidance; `.agents/skills/` is Codex-side advisory/maintenance guidance.
- [WARN] Minor wording: "learn the Prelude / recurrent loop / Coda idea" could be misread as a prompt to search/study OpenMythos externally. Resolution: changed wording to "use the Prelude -> recurrent loop -> Coda reasoning shape."
- [WARN] Minor wording: "decisions.md or hints.md" was correct but imprecise. Resolution: clarified Root edits go in `decisions.md`; operator steering is captured in `hints.md`.

