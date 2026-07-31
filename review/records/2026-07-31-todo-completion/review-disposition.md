# Independent Review Disposition

This record disposes the fresh-context Claude Code review of the complete frozen
maintenance diff before the final review rerun. Codex is the author and does not
count as the independent reviewer. arkcli is excluded by operator direction.

- Reviewed candidate SHA-1: `349278a1c2fa77459f54c00b5fe66e3a7ced1f98`
- Reviewer session: `64581a20-cfe2-44bd-b269-0570426a6655`
- Reviewer verdict: `WARN`
- Reviewer boundary: fresh context, no tools, complete maintenance-diff bundle
- Status: all nine findings adjudicated below; this hash is stale after repair

## Finding dispositions

1. **Commit-plan stage argument — factual misread; coverage improvement accepted.**
   `workers.print_commit_plan` and the `commit-plan` parser already require and
   pass `stage`. The selftest previously called the function directly, so it now
   invokes the real CLI with `--stage S2`.
2. **Stage lane visibility — partially accepted.** S1 now rejects every target
   lane and S3 applies its target cap across the full plan, including dependent
   lanes. The S2 concern is not accepted as stated: its contract is one
   *dependency-ready* target lane per asset, and the validated DAG may serialize
   same-asset successors. Fixtures cover both boundaries.
3. **Hard-coded stage exit facts — accepted with owner separation.** Merge,
   review, and Agent debt now come from `run_model.py`; terminal journal comes
   from `loop_journal.py`. `check_run`, independent review, and report/evidence
   parity deliberately remain `owner_required_exit_facts`; duplicating a weaker
   closure predicate in stage policy would be incorrect. Unknown facts block
   `exit_ready`.
4. **Historical canonical shapes — accepted.** Duplicate/missing-Front
   constraints are explicit compatibility warnings, and `PR-*` prose is parsed
   only inside an actual review finding ledger. New native shapes remain strict.
5. **Review scope/hash completeness — accepted.** Git diff failure is a typed
   error; docs include every path hash; bundle metadata reports completeness and
   omissions; incomplete non-live context cannot return PASS.
6. **Input-set expansion staling plans — accepted.** New plans bind the expanded
   set. An immutable in-flight plan can dual-read only an exact legacy digest;
   it is not rewritten and all other mismatches remain stale.
7. **Repository-root turn-contract scratch — accepted.** The fixture now uses a
   system temporary directory, restores cwd, and removes the scratch tree.
8. **Context budget diagnostics and duplicate limit — accepted.** Missing files
   produce bounded diagnostics; the contract validates and enforces the duplicate
   owner-rule limit.
9. **Benchmark attribution/direction — accepted.** Only attributable event types
   feed metric totals, unknown-event noise is ignored, and closure reopen is
   lower-is-better.

## Blind-spot dispositions

- Relative Markdown, explicit URL, bare-host, IDNA, default-port, userinfo, path,
  alias, symlink, and nonexistent-tail source identity already have focused
  fixtures; the relative-path fixture was repaired to use cwd consistently.
- Symlink rejection remains exercised on platforms that permit symlink creation;
  Windows no-privilege environments skip only the OS-unavailable construction.
- CI now runs ruff over all touched standalone tools and adds a bounded mypy gate
  for the newly typed modules, while the portable matrix runs the focused suite.
- `real-driver-evidence.json` brings the relevant raw field projections, chain
  heads, and source hashes into the review record without copying an active run.
- Closure audit remains a repository-level deterministic integration command,
  exercised directly in CI and preflight rather than wrapped by a second
  selftest-only implementation.

The repaired candidate requires a new complete-bundle hash and a fresh independent
review. This record does not claim that later review result.

## Second review and disposition

- Reviewed candidate SHA-1: `f49443998d9397b3ea9089734c506bf1c2d1c613`
- Reviewer session: `f3a0c140-2a80-4895-8a2a-9588f7289495`
- Reviewer verdict: `WARN`
- Reviewer boundary: fresh context, no tools, complete 252,918-character diff
- Status: four findings and one material blind spot repaired; this hash is stale

1. **Review-ledger historical shapes — accepted.** PR headings outside a native
   ledger stay non-authoritative but now emit a compatibility warning; missing
   legacy title severity and pre-typed field-shape errors are warning-only.
   Duplicate native PR IDs remain a hard error.
2. **Constraint historical shapes — accepted.** Canonical fields are read
   case-insensitively. Duplicate/oversize/missing-Front pre-typed shapes stay
   bounded and visible as compatibility warnings, while templates/native owners
   continue to emit the canonical shape.
3. **Non-live review writes — accepted with factual correction.** The ignored
   bundle did not make the existing preflight fail, but the read-only contract
   violation was real. Normal non-live review no longer refreshes evidence or
   writes a bundle; explicit `--bundle-only` remains the diagnostic writer.
4. **Empty review scope — accepted.** Empty maintenance diffs and zero-byte/empty
   plan/docs inputs now fail with `REVIEW_SCOPE_EMPTY`; fixtures cover both.

The reviewer also identified that stage policy's independent-review signal was
weaker than the closure receipt. It is now an owner-required unknown, like
`check_run` and report/evidence parity; prose cannot make `exit_ready` true.

The new repairs require another complete-bundle hash and final independent
review. Neither WARN above is presented as a PASS.

## Third review and disposition

- Reviewed candidate SHA-1: `a3076fd739f8408f801e0cdfbbf16e517b8f387e`
- Reviewer session: `c01532f6-af32-4332-9d02-df592d07e4a2`
- Reviewer verdict: `WARN`
- Reviewer boundary: fresh context, no tools, complete 263,368-character diff
- Status: all three findings repaired; this hash is stale

1. **Non-live panel write path — accepted.** `review_panel()` now mirrors
   `review()` and writes the bundle only for `live-run`; a fake-backend panel
   fixture proves plan review leaves no evidence/bundle sidecars.
2. **Constraint parser availability — accepted.** An unavailable shared parser is
   a closure hard error, matching the review-ledger consumer; the gate no longer
   fails open.
3. **Real context contract in CI — accepted.** Linux full CI now executes
   `python tools/context_budget.py`, so required markers and duplicate-owner rules
   are checked against repository files, not only temporary selftest fixtures.

The review also listed legacy stage-policy validation as a blind spot. Exact
pre-expansion-digest plans now retain their already-admitted lane shape while
target-egress, DAG, Reviewer, budget, and effect gates still revalidate; new
plans always use current stage policy. A target-lane legacy fixture covers this
migration seam.

The repaired candidate requires a new complete-bundle hash and final independent
review. This WARN is not presented as a PASS.

## Fourth review and disposition

- Reviewed candidate SHA-1: `917801b80d262f9108cbc8ce50230ac61cd1968a`
- Reviewer session: `162b4021-ae0b-41cd-91ae-11e6a5684eeb`
- Reviewer verdict: `WARN`
- Reviewer boundary: fresh context, no tools, complete 268,838-character diff
- Status: both findings repaired; this hash is stale

1. **Untracked maintenance scope — accepted.** Maintenance-diff collection now
   rejects any non-ignored untracked path with `REVIEW_SCOPE_UNTRACKED`; a
   tracked-diff-plus-untracked-source fixture proves omitted new files cannot
   receive a complete reviewed hash. The default non-live bundle cap is raised
   to 350,000 characters; overflow still reports incomplete context.
2. **Scheduler caps — accepted.** A/B decisions require exactly three explicit,
   finite, non-negative caps. Missing/malformed caps raise
   `SCHEDULER_AB_CAPS_INVALID`; the checked-in decision is unchanged.

The repaired candidate requires a new complete-bundle hash and final independent
review. This WARN is not presented as a PASS.

## Fifth review and disposition

- Reviewed candidate SHA-1: `b7e1ce053f78b14024f43952d029df5565a37dd6`
- Reviewer session: `04004c61-9779-453f-9dd4-7d431ab4c6e1`
- Reviewer verdict: `WARN`
- Reviewer boundary: fresh context, no tools, complete maintenance-diff bundle
- Status: all three WARN findings and the concrete engineering blind spots were
  repaired; this hash is stale

1. **Scheduler row typing — accepted.** Every mode now requires finite,
   non-negative numeric quality/elapsed/coverage/merge/request/token values;
   quality and coverage are bounded to one. Malformed rows fail with stable
   `SCHEDULER_AB_ROW_INVALID:<mode>`.
2. **Lane-capture denominator — accepted.** The metric uses only the intersection
   of assignment lane IDs and current canonical plan lane IDs. Missing plan data
   produces unknown, while stale assignments cannot raise the rate above one.
3. **Legacy explicit findings — accepted.** Ordinary historical PR prose remains
   advisory, but an exact pre-ledger heading carrying BLOCKER or WARN is typed and
   disposition-gated. Compatibility no longer weakens an existing hard gate.
4. **Clean-checkout preflight — accepted.** CI fetches history and passes the PR
   base or push event's `before` commit to `preflight.py`; the scan covers the
   complete committed base-to-HEAD change, not an empty worktree or only the last
   commit. Initial pushes use Git's empty-tree object.
5. **Process-global WebSocket proxy — accepted.** The bounded proxy swap/send/
   restore transaction is serialized and the selftest verifies restoration.
6. **Duplicate request identity — clarified and tightened.** Identity binds
   method, asset/host, and URL/path; the counter explicitly means extra
   occurrences beyond the first.

The repaired candidate requires a new complete-bundle hash and final independent
review. This WARN is not presented as a PASS.

## Sixth review and disposition

- Reviewed candidate SHA-1: `f4115ce99cdcaa40daf3b3134dfe2d655d25ee41`
- Reviewer boundary: fresh Claude Code context, no tools, complete
  299,812-character maintenance-diff bundle; the first attempt reached the model
  output-token limit without a verdict, and a bounded retry returned the result
  below
- Reviewer verdict: `WARN` (five minor findings, one evidence-record INFO)
- Status: every actionable finding repaired; this hash is stale

1. **Onboarding paragraph ownership — accepted.** The setup transaction/CAS/
   resume paragraph is again adjacent to the setup entry points, before the new
   scratch section.
2. **Multi-commit push range — accepted.** Push CI uses
   `github.event.before..HEAD`; an all-zero initial `before` falls back to Git's
   empty tree. `preflight.py` accepts explicit endpoints so that fallback is
   valid.
3. **Stage owner diagnostics and T11 attribution — accepted.** Owner import/API
   failures stay fail-closed and now emit stable owner/type diagnostics. T11 is
   attributed to the work-plan owner and its settled S2→S1 fixture, not
   `run_model.py`.
4. **A/B expected decision — accepted.** A recorded `expected_decision` is
   compared with the computed result; contradiction raises
   `SCHEDULER_AB_EXPECTED_MISMATCH`.
5. **Closure-audit migration evidence — accepted.** Running the candidate's new
   template/schema checks against baseline `28929965…` found schema wiring clean
   and exactly one pre-existing template gap (`constraints.md`). This candidate
   adds its canonical owner reference and the current audit passes; the raw
   before/after output is retained with the verification log.
6. **Raw verification record — accepted.** The record now contains the exact
   76-suite output, complete 18/18 benchmark output, current and baseline audit
   output, and the raw sixth-review WARN. A final PASS receipt is necessarily
   appended only after its exact implementation hash is frozen, to avoid changing
   the diff it claims to review.

The repaired candidate requires a new complete-bundle hash and final independent
review. This WARN is not presented as a PASS.

## Seventh review and disposition

- Reviewed candidate SHA-1: `72532a01935a89545cd3e838999aa5cba16bff0b`
- Reviewer boundary: fresh Claude Code context, no tools, complete
  322,892-character maintenance-diff bundle; the first attempt hit the explicit
  USD cap without a verdict, and the exact retry returned the result below
- Reviewer verdict: `WARN` (two minor findings, two INFO observations)
- Status: both actionable findings repaired; this hash is stale

1. **Statusline paragraph ownership — accepted.** The active-run/statusline
   paragraph and command now begin the Claude hooks/statusline section rather
   than ending the scratch section.
2. **ROOT_DIRECT stage-policy coverage — accepted.** Every mode now calls
   `validate_lane_shape`; assignment-free ROOT_DIRECT skips only synthetic
   Reviewer topology. S1 offline-only and S3 target-cap rules still inspect the
   whole plan, with focused stage-policy and work-plan negative fixtures.
3. **CI provenance INFO — recorded, not promoted to a local PASS.** Local raw
   verification proves the same deterministic commands. The first hosted CI log
   must be retained after push; it cannot truthfully be manufactured in this
   isolated, unpushed maintenance worktree.

The repaired candidate requires a new complete-bundle hash and final independent
review. This WARN is not presented as a PASS.
