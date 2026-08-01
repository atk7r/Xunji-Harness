# Maintenance Report

## Confirmed Findings

### Personalized RDT subagent enhancement

- Evidence IDs: E-001
- Functional diff fingerprint: `d0a4c06ecafe953e`
- Summary: The existing Agent Board now supports per-run operator personalization through `state/operator_profile.json`. `context_pack.py` injects resolved RDT style, loop budget, role focus, review/evidence preference, replay policy, and retrospective lessons. `workers.py assign` writes the resolved loop budget/profile source into new Agent scaffolds and `state/assignments.json`.
- Boundary: no OpenMythos runtime dependency was added; only its idea pattern is reflected as `openmythos-inspired`. The Single Synthesizer and evidence gate remain authoritative.
- Compatibility: old Agent files are not forced into the new RDT schema. New personalized-RDT files are checked for required Step fields.
- Hardening after peer review: malformed numeric profile fields now fall back safely instead of crashing profile resolution.
- Primary-driver skill alignment: `.claude/skills/xunji-agent-board/SKILL.md` now tells Claude Root how to use `state/operator_profile.json` and explicitly treats `.agents/skills/` as Codex-side guidance.
- Codex rule alignment: `AGENTS.md` now states that ambiguous framework/Root/subagent/skills edits default to Claude Code primary-driver behavior and `.claude/skills/`.

## Candidate / Phenomena

- Peer review produced WARN items about evidence packaging and partial backend availability; see the disposition record before commit.
