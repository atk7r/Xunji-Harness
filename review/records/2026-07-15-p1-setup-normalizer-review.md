# P1 Setup Normalizer Pilot Review

- Date: 2026-07-15
- Verdict: PASS
- Review limitation: arkcli produced no valid vote because Kimi timed out and
  GLM output failed structured parsing; the valid independent coverage is the
  two Claude Code fresh-context reviews recorded below.
- diff_fingerprint: e43f1bbef5d98f8f
- reviewed_diff: e43f1bbef5d98f8f
- Full reviewed staged-diff SHA-256:
  `996e5fa8f9d853181fb2261b24aded9144d19dc754382ec897e324c8899e7b51`
- Base commit: `656c1cf8dbad67a8257ad07fa74abaf23336dc74`
- Author/driver and final synthesis: Codex. Codex self-review is not counted as
  an independent vote.

## Reviewed scope

The frozen candidate contains 26 files and 2,285 insertions / 60 deletions:

- primary-driver contracts and guidance:
  `.claude/skills/xunji-run-lifecycle/SKILL.md`,
  `.claude/skills/xunji-setup-ingest/SKILL.md`, `CLAUDE.md`,
  `docs/ARCHITECTURE.md`, `docs/ROUTER.md`,
  `docs/WORKFLOW-reference.md`, and `docs/WORKFLOW.md`;
- normalizer contracts, implementation, and benchmark:
  `contracts/setup-normalizer-candidate.v1.schema.json`,
  `contracts/setup-source.v1.schema.json`, `tools/setup_normalizer.py`,
  `tools/setup_normalizer_bench.py`, `bench/setup-normalizer-pilot/cases.json`,
  and `bench/README.md`;
- setup/lifecycle integration: `tools/setup_source.py`, `tools/setup_run.py`,
  `tools/loop_bootstrap.py`, `tools/turn_contract.py`, and
  `tools/coverage_matrix.py`;
- guard, fixture, and regression registration: `tools/harness/command_shape.py`,
  `tools/harness/maintenance_authority.py`,
  `tools/harness/safety_critical_paths.json`, the setup/privacy fixtures,
  `tools/check_rules.py`, and `tools/selftest_all.py`.

The candidate implements a reference-only Markdown/ordinary-JSON setup
normalizer. Deterministic code inventories source-backed tokens and references,
requires a mechanically unique labelled target, hard-redacts a path-free external
surrogate, reconstructs selected values from the frozen source, and hash-binds
source/request/candidate artifacts before the existing setup transaction owns
activation. `--ai off` remains the default. External AI requires the current
operator turn and may return identifiers only. Local AI and HTML/PDF/DOCX/plain
text remain fail closed and are not represented as implemented.

The same diff preserves `scope_status` through the coverage ledger and makes
`review`, `out`, `unknown`, and conflicting duplicate statuses inspection-only
for target-facing execution. Operator admission of review rows is deliberately a
later transition and is not silently performed here.

## Verification identity

- `python3 tools/selftest_all.py`: **66 passed, 0 failed (90.5s)**.
- Raw full-suite log: `/tmp/xunji-p1-normalizer-selftest.log`.
- Raw log SHA-256:
  `a15b3962337c27842014166b9b1ea0d2896a43d00a66f5a97c86afe0a4955d55`.
- Focused normalizer, benchmark, source, setup, transaction, bootstrap,
  turn-contract, coverage, command-shape, privacy, maintenance-authority,
  check-run, hook, runtime-boundary, template, rule, and bench checks passed.
- Python compilation and staged diff-format checks passed.
- The pre-commit framework-subset fingerprint remained
  `e43f1bbef5d98f8f` after the complete suite and frozen reviews.

These are controlled local observations, not independent reviewer votes. This
record is excluded from the reviewed implementation fingerprint by design to
avoid a self-referential review hash.

## Independent review results

The candidate was split into core and integration bundles so every disclosed
diff artifact fit without excerpt truncation. Both bundles report `warnings: []`
and all disclosed artifacts report zero truncated excerpt characters.

### Core normalizer and source/benchmark contract

- Frozen scope: `/tmp/xunji-p1-normalizer-core-e43f1bbe/`.
- Bundle: `708134c3f2db35e978e8eb05a25b6a68477b9126`.
- Evidence index: `4fcf3fefdd6a4d023153608e30169c486add921d`.
- Claude result SHA-256:
  `2aab109bfc6791ac9b6426c25335bb69e6d1936366197bc0cdc47e975349f384`.
- Claude fresh-context result: **APPROVE, zero findings**. The first attempt
  lacked a verdict; the retry produced a valid structured result.
- Arkcli result SHA-256:
  `6839bef6bbcd91273f20fe86f90aa0292ea3fc8a4e762ec64d1433a4c9cdf7f3`.
- Arkcli result: **ERROR, no vote**. Kimi timed out after 300 seconds and GLM
  returned useful-looking prose that the structured parser could not accept.

### Setup, authority, scope, docs, and regression integration

- Frozen scope: `/tmp/xunji-p1-normalizer-integration-e43f1bbe/`.
- Bundle: `30bd4482b843302cc3c190c115a3c6cd9a0e74f0`.
- Evidence index: `f13de86eb6c03dba455e3255686320a387165657`.
- Claude result SHA-256:
  `c9ddb850ecda325be9efa69e1050a944e962d482d013b6961e76d07efcb03bcb`.
- Claude fresh-context result: **SHIP, zero findings**. The first attempt lacked
  a verdict; the retry produced a valid structured result.
- Arkcli result SHA-256:
  `cfc487cc15eb442c7a0cb55eb25743b01ff4a898c56496eb09b5b6435e1ceaf9`.
- Arkcli result: **ERROR, no vote**. Kimi timed out after 300 seconds and GLM
  again returned prose that failed structured parsing.

## Driver dispositions

Neither valid Claude review contained a finding. Arkcli's malformed outputs are
not promoted into either PASS or BLOCKER. Their retained tails did identify
specific review questions, which the driver checked against the frozen code:

- AI extractor metadata is all-or-none: partial population is rejected by
  `setup_source.py` before a manifest can validate.
- `in + legacy` duplicate scope provenance remains blocked. Only a uniformly
  `in` or uniformly legacy destination is executable; ambiguity is intentionally
  fail closed rather than a backward-compatibility bypass.
- External preparation is not inspection authority by itself. The hook-level
  `normalizer_prepare` path requires a pending operator bootstrap contract and
  explicit external mode, while creating no transition claim.

No code change was required by these checks, so the reviewed fingerprint did not
change and the two valid Claude votes remain current.

## Residual limitations

- Arkcli produced no valid vote. Kimi timeouts and GLM parser failures are
  disclosed rather than relabelled as reviewer approval.
- Claude reviewed frozen hard-redacted artifacts and did not execute the
  repository. The complete local suite supports the synthesis but is not an
  independent vote.
- The offline `reference_candidate` benchmark is an oracle over exposed IDs. It
  proves the contract can improve recall without value invention; it does not
  measure a live provider and is not a provider rollout claim.
- Unsupported file types and the separate operator-admission transition remain
  deferred and fail closed.

## Final synthesis

There is no unresolved evidence-backed BLOCKER. Both valid independent Claude
reviews approved their respective final-fingerprint bundles with zero findings.
The incomplete arkcli coverage is explicit, the complete regression is green,
the architecture checkpoint names the correct candidate/validator/transaction
owners and transitional boundary, and the Codex-authored P1-3/P1-4 normalizer
pilot may proceed to commit.
