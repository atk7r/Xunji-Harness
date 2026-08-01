# Knowledge Scaffold and History Sanitization Review

Verdict: PASS

diff_fingerprint: 2c6180dbf1fdaa0e
reviewed_diff: 2c6180dbf1fdaa0e
full_reviewed_patch_sha256: 16a4704705d31f7d262d8500a28867832895fb2ef5df557fc89b3c81b8c947ae

- Date: 2026-08-01
- Author and final synthesizer: Codex; Codex self-review is not counted.
- Independent reviewer: fresh-context Claude Code, tools disabled, no edits.
- Review boundary: Claude Code reviewed the maintenance diff; arkcli was excluded
  per the operator's standing instruction.
- Publication target: `https://github.com/atk7r/Xunji-Harness.git`.

## Reviewed contract

- The public repository tracks exactly five knowledge scaffold files:
  `knowledge/README.md`, `_TEMPLATE.md`, `_lexicon.md`,
  `weaponized/README.md`, and `weaponized/.gitkeep`.
- Populated grounding and weaponized entries are operator-local and ignored by
  Git. The generic lexicon is vocabulary only, not product or target knowledge.
- Local matching, seeding, xday lookup, context packing, and knowledge validation
  retain their runtime behavior on operator-populated local entries.
- The two remote branches containing the former unredacted corpus are replaced by
  one parentless clean snapshot; local private knowledge is not deleted.

## Review findings and dispositions

The full review returned WARN because `_lexicon.md` was only implicitly skipped by
`knowledge_match.py`, fresh-clone coverage did not prove the skip, cognition called
all vocabulary local, and the Architecture checkpoint did not name the lexicon.

All findings were accepted:

1. `knowledge_match.py` now explicitly skips README, template, and lexicon.
2. Its selftest gives `_lexicon.md` entry-like frontmatter and proves it is still
   excluded, so a scaffold-only clone yields no false knowledge entry.
3. Cognition now distinguishes the public generic lexicon scaffold from local
   product-specific entries.
4. The Architecture checkpoint explicitly lists `_lexicon.md`.

Fresh-context follow-up verdict: PASS; required dispositions: None. Its optional
docstring nit was also applied verbatim after review and revalidated by the same
focused selftest; it does not alter behavior.

## Verification

- `git diff --cached --check`: PASS
- `python3 tools/check_knowledge.py`: PASS on the scaffold-only tree
- `python3 tools/selftest_all.py --only check_knowledge,knowledge_match,xday_match,context_pack`:
  4 passed, 0 failed
- `tools/check_rules.py`, `tools/check_templates.py`,
  `tools/check_runtime_boundary.py`, and `tools/check_local_hygiene.py`: PASS
- Tracked knowledge allowlist: exactly 5 expected scaffold files
- Scaffold scan for URLs, IPv4 addresses, email addresses, home paths, and
  secret-like assignments: no matches
- No target-facing, run-state, Hook, guard, privacy, or evidence-gate behavior changed.

## Residual platform boundary

Replacing branch refs removes the old knowledge corpus from reachable repository
history, but does not itself purge GitHub cached commit views, pull-request refs,
forks, or third-party clones. Those require GitHub's sensitive-data removal process
and coordination with any fork/clone owners.
