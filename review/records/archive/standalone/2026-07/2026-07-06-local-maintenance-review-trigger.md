# Local Maintenance Review Trigger Patch

- Date: 2026-07-06
- Author: Codex
- Scope: `.agents/skills/xunji-local-maintenance/SKILL.md`
- Trigger: add an explicit operator-requested "复审" routing rule.

## Change

- Added "复审" / review trigger wording to the skill description.
- Added a routing rule that the author cannot satisfy review by rereading their
  own work.
- For Claude Code-authored review targets, the rule now requires a context file
  at `review/records/<date>-<topic>-context.md`, a read-only Codex review through
  `python tools/harness/codex_proxy.py codex exec -s read-only < ...`, findings
  saved to `review/records/<date>-<topic>-codex-review.md`, and driver disposition
  recorded under `review/records/`.
- For Codex-authored changes, the rule preserves the existing Codex-authored
  maintenance matrix in `xunji-peer-review-panel`.

## Review

### Claude Code Direct Review

- Method: direct `claude -p` review of the final diff.
- Limitation: local Claude Code printed the same auth-source precedence warning
  seen earlier even after unsetting Anthropic API environment variables for the
  command.
- Final verdict: PASS.
- Findings: no BLOCKER/WARN. Earlier BLOCKER findings about raw `CODEX_PROXY`,
  undefined context files, and bypassing the review panel were fixed.

### arkcli Direct Review

- Method: direct `arkcli +chat` review of the final diff.
- Final verdict: PASS.
- Findings: no BLOCKER/WARN. Only non-gating nits about naming/documentation.

## Verification

```bash
python3 tools/check_rules.py
```
