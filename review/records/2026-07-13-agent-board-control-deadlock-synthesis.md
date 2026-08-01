# Agent Board control deadlock repair — Codex synthesis

- Date: 2026-07-13
- Author: Codex
- Verdict: WARN
- diff_fingerprint: 234d36ca173494c1
- reviewed_diff: 234d36ca173494c1
- Scope: `.claude/skills/xunji-agent-board/SKILL.md`, `docs/WORKFLOW.md`,
  `tools/runtime_receipts.py`, `tools/turn_contract.py`, `tools/workers.py`,
  and the environment-independent assertion in `tools/xunji_statusline.py`.
- Final validation: `python3 tools/selftest_all.py` → 60 passed, 0 failed;
  `tools/check_rules.py` and `tools/check_hook.py` passed; Agent Board bench →
  18/18 clean, 0 false positives, 0 over budget.

## Independent review matrix

- Full final-diff Claude Code fresh-context review:
  `2026-07-13-agent-board-control-deadlock-review-round3.md`.
  Claude completed the final six-file review with no code finding; the combined
  panel returned `NEEDS_DRIVER` only because the arkcli side failed.
- Final core safety review through arkcli:
  `2026-07-13-agent-board-control-deadlock-review-core-arkcli-final.md`.
  GLM completed the final `turn_contract.py` / `workers.py` /
  `runtime_receipts.py` review with no code finding. Kimi exceeded its internal
  300-second timeout; this missing vote remains an explicit limitation.
- Earlier rounds are retained because their findings materially changed the diff:
  round 1 expanded shell and statusline evidence; round 2 caught terminal-to-
  nonterminal heartbeat rollback; the first core arkcli review caught a stray
  selftest assignment that overwrote the real assertion result.

## Driver dispositions

### Accepted and fixed

- Control-shell adversarial coverage was too narrow. Added end-to-end
  `evaluate_pretool` cases for quoted punctuation, single/ANSI-C literals,
  escaped and double-escaped substitution, command substitution, backticks,
  process substitution, pipes, chains, redirects, comments, unmatched quotes,
  and dangling escapes.
- `heartbeat` could reopen a terminal assignment as `running`. It now rejects
  every terminal-to-nonterminal transition; `done` may still advance through
  `finish` to an adjudicated terminal state.
- Invalid terminal notes were written before canonical anchor validation.
  `finish` now validates first, fails closed without `runtime_receipts`, and
  requires explicit `--amend` with preserved history for terminal corrections.
- Review evidence was initially summary-only and truncated. Final review inputs
  use raw selftest output, a sanitized live-run disposition snapshot, dependency
  context, and one patch artifact per changed file.
- The statusline assertion depended on whether an inherited EXECUTE contract
  rendered `真实` or `本轮真实`; it now uses an exact regex for either label and
  retains the existing read-only render check.
- A stray `heartbeat_cannot_set_terminal = True` in selftest cleanup masked the
  real assertion. It was removed, and both the narrow suite and final 60-suite
  run pass without the override.

### Dismissed with evidence

- `runtime_receipts` binding is not missing: `tools/workers.py` imports it into
  `_runtime_receipts` and terminal disposition validation explicitly fails
  closed when the import is unavailable; the latter path has a dedicated test.
- Amendment timestamps are not stale: the prior `finished_at` is copied into
  `disposition_history`, while the amended record receives the new `stamp` as
  `updated_at`, `last_seen_at`, and `finished_at`.
- Process substitution is not an uncovered allow path: unquoted `<` and `>` are
  denied, and final tests exercise both `<(id)` and `>(id)`. ANSI-C and
  single-quoted substitutions are literal shell data and are tested as allowed.
- Canonical anchors intentionally resolve against the current Markdown source
  of truth at disposition time. A blocked disposition needs a real current
  Front, while merged asset work separately requires transcript-backed target
  activity and canonical evidence coverage. Requiring finding-level maturity
  for every merge would incorrectly prevent candidate/refutation synthesis.

## Residual limitations

- Kimi timed out on the final full and focused bundles; GLM supplied the final
  arkcli vote. This is recorded rather than treated as a clean Kimi vote.
- No live target probing was performed during maintenance. The existing
  `sxtbu_20260713` control state was repaired only: both legacy empty-asset
  assignments remain blocked, prior notes are preserved in history, and
  `agent_disposition` reports `pending=[]` and `disposition_satisfied=true`.
  Resuming the engagement requires new explicit-asset assignments under the
  Claude primary driver.

## Final verdict

No unresolved code blocker remains. The final diff is supported by a completed
Claude full-scope review, a completed arkcli GLM core-safety review, retained
review-driven fixes, and final green local regression evidence. The missing
Kimi vote is a documented reviewer-availability limitation, not silently counted
as approval.
