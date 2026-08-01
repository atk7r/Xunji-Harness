# Staged Framework Pre-commit Review

- Date: 2026-07-06
- Author: Codex staged commit driver
- Review target: staged framework diff for the operator-requested "commit all changes" action.
- diff_fingerprint: 8889026b15a0b467
- reviewed_diff: 8889026b15a0b467

## Verdict: WARN

Independent arkcli direct review of the staged framework diff found no BLOCKER.
The reviewed scope included the staged framework changes under `tools/`,
`.claude/`, and `docs/`, plus the local-maintenance skill diff that controls the
operator-requested "复审" routing behavior.

## Reviewer Summary

- `.claude/skills/src-safety-boundary/SKILL.md` only quotes the description; no
  safety-boundary weakening was identified.
- `.agents/skills/xunji-local-maintenance/SKILL.md` strengthens review routing:
  authors cannot satisfy review by rereading their own work, Claude Code-authored
  review targets route through read-only Codex via `tools/harness/codex_proxy.py`,
  and Codex-authored changes still use the peer-review matrix.
- `tools/replay.py` and `tools/classify_hosts.py` move selftests into
  `probe.selftest_isolation()`; the reviewer saw this as selftest side-effect
  containment, not a scope or guard weakening.
- `tools/peer_review.py` increases artifact excerpt coverage while adding bundle
  caps, warnings, and selftest coverage for truncation behavior.
- `tools/coverage_matrix.py` and `docs/templates/run/frontier.md` keep explicit
  `Assets:` / `Targets:` attribution aligned with selftests.
- `docs/templates/run/review.md` hardens review-ledger closure expectations.

## Warnings / Driver Disposition

- `tools/workers.py` subcommand references in docs were not revalidated here.
  Disposition: accepted as non-blocking for this commit; follow-up smoke test is
  appropriate when exercising the Agent Board workflow.
- `BundleHash` / `EvidenceIndexHash` template fields may still require driver
  fill-in depending on review path. Disposition: accepted; the template is useful
  in the manual path and `peer_review.py` already carries bundle/evidence hashes
  in result objects.
- Reviewer recommended running `replay` and `classify_hosts` selftests because
  both changed. Disposition: completed; both passed.
- `audio_samples/*.mp3` are binary additions outside the framework fingerprint.
  Disposition: included because the operator requested committing all changes.

## Verification

```bash
python3 tools/replay.py --selftest
python3 tools/classify_hosts.py --selftest
python3 tools/check_rules.py
```
