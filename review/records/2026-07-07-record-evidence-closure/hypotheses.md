# Hypotheses

## H-001

- Status: confirmed
- Claim: `.claude/skills/web-research/SKILL.md` referenced a non-existent evidence recorder, breaking the "research complete when recorded" protocol.
- What would confirm: command-reference scan shows the missing tool before the fix; post-fix scan shows no missing `python tools/*.py` commands.
- What would reject: the tool already existed or the skill no longer referenced it.
