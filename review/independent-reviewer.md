# Independent Review (Deprecated Entry Point)

This file is retained only so old links fail safely. It is not a reviewer prompt
and must never be copied into `review.md`.

Use the current foreground workflow:

```bash
python tools/peer_review.py runs/<target> --into-run
```

Closure requires the content-addressed `ReviewReceipt`, the matching
`XUNJI_REVIEW_RECEIPT` and `XUNJI_REVIEW_BUNDLE` output markers observed by the
Claude Code hook, a current evidence-index hash, and disposition of every review
ledger item. A heading, manually filled reviewer identity, copied model output,
fresh-context prose, timeout, or hand-written PASS never satisfies the gate.

Authoritative behavior is defined in `CLAUDE.md`, `docs/WORKFLOW.md`,
`docs/WORKFLOW-reference.md`, `.claude/skills/xunji-peer-review-panel/SKILL.md`,
and `.claude/skills/xunji-reviewops/SKILL.md`.
