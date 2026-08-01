# Review Records Layout

This directory is for maintenance-review and closure-review records.

Keep the root small:

- `INDEX.md` is the human map.
- One directory per substantial review topic.
- `archive/standalone/<yyyy-mm>/` stores older one-file records that do not have
  a topic directory.
- During a gated framework commit, `.claude/hooks/pre-commit` may require a
  temporary root-level `<date>-<topic>.md` containing `Verdict:` plus the current
  `diff_fingerprint` / `reviewed_diff`. After the commit is accepted, move that
  gate record into the topic directory on a later review-record cleanup commit.

Inside a topic directory:

- `report.md`, `review.md`, `review_result.json`, `target.md`, `frontier.md`,
  `evidence.md`, and `decisions.md` are the readable review scope and result.
- `evidence/` holds patch, test, scan, and bundle artifacts.
- `review/` holds generated review bundles.
- `reruns/` holds superseded panel outputs, disposition notes, postfix/rerun
  files, and old root-level companion files.

Do not rewrite raw review outputs just to make them prettier. They may contain
provider error tails, Markdown hard-line spaces, or raw patch formatting that
preserves the exact artifact seen by the reviewer.
