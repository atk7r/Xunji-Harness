# Decisions

## D-001

- Loaded rule files this cycle: `AGENTS.md`, `xunji-web-research-sync`, `xunji-peer-review-panel`
- Chosen front: F-001 web-research evidence recorder
- Why this is worth pursuing now: `.claude/skills/web-research` made recording evidence the completion condition, but the referenced recorder did not exist.
- Decision: implement the recorder, update Claude-side skills, add aggregate selftest coverage, and record an independent maintenance review.
