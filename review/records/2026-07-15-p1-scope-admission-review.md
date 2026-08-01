# P1 Scope Admission Review

- Date: 2026-07-15
- Verdict: PASS
- diff_fingerprint: 1a448f4d7825aa1f
- reviewed_diff: 1a448f4d7825aa1f
- Full reviewed staged-diff SHA-256:
  `c69c8bce82cd9338f981a242e301259fe615a4e17010bee0c25b47e27c5ddf12`
- Base commit: `edf571c`
- Author/driver and final synthesis: Codex. Codex self-review is not counted as
  an independent vote.
- Review limitation: both arkcli models failed to produce a valid structured
  vote. Kimi timed out and GLM's long-form output failed parsing. The valid
  independent coverage is the two final-fingerprint Claude Code fresh-context
  reviews below; the arkcli limitation and candidate tail are retained.

## Reviewed scope

The frozen implementation contains 18 files, 1,220 insertions, and 42 deletions:

- primary-driver guidance and design:
  `.claude/skills/xunji-run-lifecycle/SKILL.md`,
  `.claude/skills/xunji-setup-ingest/SKILL.md`, `CLAUDE.md`,
  `docs/ARCHITECTURE.md`, `docs/ROUTER.md`,
  `docs/WORKFLOW-reference.md`, and `docs/WORKFLOW.md`;
- admission contract and implementation:
  `contracts/scope-admission.v1.schema.json`,
  `tools/harness/fixtures/scope-admission.json`, and
  `tools/scope_admission.py`;
- authority, transaction, target-gate, and ledger integration:
  `tools/turn_contract.py`, `tools/setup_transaction.py`,
  `tools/coverage_matrix.py`, `tools/harness/maintenance_authority.py`,
  `tools/harness/safety_critical_paths.json`, and `.gitignore`;
- regression wiring: `tools/check_rules.py` and `tools/selftest_all.py`.

The change introduces the only executable transition for file-derived
`scope_status=review` assets. A new operator turn must use the exact first-line
`/xunji-scope-admit --run runs/<name> --assets <host[,host...]> --reason <text>`
shape. The active-run Hook writes a session/prompt/reason-bound one-use claim;
the local zero-probe tool consumes it, commits coverage plus a prepared/committed
receipt under the pointer-owner activation lock, and regenerates the derived
asset ledger. Target effects verify committed receipt identity, the current
setup-source hash, and the scope projection.

Candidate identity is re-derived from the validator-bound frozen setup bundle,
not only from mutable coverage labels. Stripping the `source` marker while
forging `scope_status=in` therefore remains blocked. Absolute/traversing run
aliases, stale prior-turn claims, wildcard/port/zoned-IP assets, missing/inactive
runs, duplicate/conflicting rows, `out|unknown|legacy` promotion, prepared
receipts, invalid source bundles, replay, target/network, Agent, and Cron paths
fail closed.

## Verification identity

- `python3 tools/selftest_all.py`: **67 passed, 0 failed (90.3s)**.
- Raw full-suite log: `/tmp/xunji-p1-scope-admission-selftest-all.log`.
- Raw log SHA-256:
  `da766ece5e69bbf015c487260766de23d657ac6386eb0c02f084c2718da3aa34`.
- Focused setup-transaction, setup-source, normalizer, scope-admission,
  setup-run, turn-contract, coverage-matrix, maintenance-authority, Hook, and
  rule checks passed.
- Python compilation and staged diff-format checks passed.
- Final framework fingerprint remained `1a448f4d7825aa1f` and full staged hash
  remained `c69c8bce82cd9338f981a242e301259fe615a4e17010bee0c25b47e27c5ddf12`
  throughout final review.

These are controlled local observations, not independent reviewer votes. This
record is excluded from the reviewed framework fingerprint by the commit gate,
avoiding a self-referential hash.

## Bundle integrity

The implementation was split into core and integration bundles to keep every
artifact below the external excerpt cap.

- Core bundle: `/tmp/xunji-p1-scope-core-1a448f4d/`;
  bundle `71ffdfb6ef189d8d357fef3a25777c52ae4ca843`;
  evidence index `719694c53e72bc8a0e47d6fa695f08666885a789`.
- Integration bundle: `/tmp/xunji-p1-scope-integration-1a448f4d/`;
  bundle `bd18bf114005431ee43bbd0f3a13aaca32430064`;
  evidence index `67529fb77c3a112f58794b5eab8a3a283081295e`.
- Both bundles have `warnings: []`; all eight referenced diff artifacts have
  `excerpt_truncated_chars=0`.
- The four core tool chunks concatenate to SHA-256
  `8a3a8419110b44f308cb1267ce2b5cc82b65f0224d1e9f2534e3890653a4f842`,
  identical to the full `tools/scope_admission.py` staged diff.

## Independent review results

### Core transaction and verifier

- Claude result: **SHIPPABLE, zero findings**.
- Claude parsed-result SHA-256:
  `ba07225f646317940793c569c9d98df80051efc96db1d4f50b6b5dfe9ff077f4`.
- Claude raw-result SHA-256:
  `6a3da11639ec3ad5c0580ad13469496015315c86dd59f137d1b7f6a76d2c7719`.
- The first fresh-context attempt lacked a recognized verdict; the second
  produced the valid result above.
- Arkcli parsed-result SHA-256:
  `403d64eccbbc31cfb68cd35c8222e51c0b6648e1592b1848007fb0abaca9b285`.
- Arkcli result: **ERROR, no vote**. Kimi timed out after 300 seconds; GLM
  produced code-oriented prose but not a parseable panel result.

### Hook, target gate, ledger, docs, and regression integration

- Initial Claude parsed result: **ERROR, no vote** after two responses without
  a recognized verdict; SHA-256
  `8d320561d846373a4f0d92f1bee1e4594e14e86d375f62e05c1aa557e4ad16ba`.
- Fresh-context Claude rerun: **SHIP, zero findings**.
- Rerun parsed-result SHA-256:
  `09616c75d460f193663358a3a145cb7d5911bc1e5ffc2887e5e8409decc01638`.
- Rerun raw-result SHA-256:
  `0dcf0ec572c796f1f688b43c0fb4eeb21199f4fdd6d56e0d79e4583d6683d23b`.
- Arkcli parsed-result SHA-256:
  `dcf4dd95d78adc52d72f1dad576594d1152074eeca61d0da7473bc374b81bf8b`.
- Arkcli result: **ERROR, no vote**. Kimi timed out after 300 seconds; GLM's
  long-form output failed structured parsing.

## Driver dispositions

The two valid Claude reviews contain no finding. The invalid arkcli output is not
promoted into either approval or blocker. Its retained integration tail raised a
specific question: an early `scope_admission.py` deny might reject valid calls.
Inspection of the frozen `handle_event()` control flow disproves that candidate:

- the unconditional deny is inside the `run_dir is None` bootstrap branch, where
  scope admission must be denied because there is no active run;
- with an active run, `handle_event()` loads the current session contract, calls
  `evaluate_pretool()`, and writes the exact claim only after the policy returns
  allow;
- the focused Hook and turn-contract suites exercise the active and no-active
  paths and pass.

No final-fingerprint change was required. Earlier pre-freeze review and driver
audit findings were already incorporated before this round: asset lists are
canonically sorted, absent hosts fail verification, interrupted claim transports
are cleaned after durable commit, stale prior-turn claims cannot create false
ambiguity, frozen source provenance defeats source-label stripping, lexical run
aliases are rejected, and missing runs fail before lock/state creation. A
hypothetical future reordering of the before/after coverage serialization was
not changed because the current ordering is explicit and regression-tested.

## Residual limitations

- Arkcli produced no valid vote despite two-model panel attempts. The fallback
  independent coverage is Claude Code fresh-context as allowed by the Codex
  maintenance matrix; this reduces heterogeneous model diversity and is recorded
  rather than relabelled as a panel pass.
- External reviewers saw the complete hard-redacted frozen bundles and did not
  execute the repository. Local regression evidence supports the synthesis but
  does not count as an independent vote.
- Admission deliberately does not infer scope, probe assets, admit wildcard
  patterns, or promote `out|unknown|legacy`; those remain operator/workflow
  decisions outside this tool.

## Final synthesis

There is no unresolved evidence-backed BLOCKER. Both final-fingerprint bundles
have a valid independent Claude Code approval with zero findings, the arkcli
failure and its candidate tail are explicitly adjudicated, the complete local
regression is green, the architecture checkpoint names the correct authority,
state, lock, receipt, and target-gate owners, and this P1 scope-admission stage is
ready to commit.
