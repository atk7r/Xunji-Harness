# Prior Panel Disposition

This record covers the two review rounds run before the final frozen diff. Their
findings were treated as candidates and resolved as follows.

## Accepted And Fixed

- Coda accepted vague paraphrases. Added vague-phrase detection, then narrowed it
  so a concrete F-id/tool/file remains valid.
- Coda multi-action matching was first too broad around `和`, then the final
  reviewer found the narrowed separator list could miss `运行 check_run 与
  peer_review`. Replaced separator-only matching with executable-clause counting:
  two tools/actions joined by punctuation or conjunctions are blocked, while one
  action with multiple parameters (for example ports `80，443`) remains valid.
- Bare/unanchored `Agent` could act as a control-plane anchor. Restricted it to
  `Agent Board`, `subagent`, worker commands, conflicts, assignment, or review.
- No active fronts plus an arbitrary F-id could pass. Closure-stage Coda now
  rejects any F-id when no active front exists.
- Loop-state import/derive failure disabled the Coda hard gate. Added a read-only
  canonical Markdown fallback that preserves Coda and active-front enforcement.
- Hook integration was only unit-level. Added a subprocess regression where both
  Stop hooks resolve the same explicit pointer: output_gate accepts one concrete
  Coda, then run_gate blocks the same closure candidate for missing review.
- Retrospective item splitting missed repeated `Problem:` fields. Added that
  structured format and a per-item failure regression.
- `Independent Review` and `CodexCompletionReview` were substring gates. Replaced
  them with structured completion predicates; prose mentions, untouched template
  choices, and a later self-review no longer satisfy closure. The completion
  predicate is enforced by both `run_gate.py` and `check_run.py`, so it is not a
  single-hook control.
- Cookie deletion initially covered empty values and `Max-Age=0` only. Added
  expired `Expires` handling using parsed absolute time, with a focused regression.
- Raw full-suite evidence was missing. Added `selftest_all.log` and its SHA1.
- API reviewers saw only a truncated monolithic diff. Added per-component diff
  artifacts, each below the configured per-artifact excerpt cap.

## Dismissed Or Accepted Tradeoffs

- Maintenance review directories do not need live-run frontier/decisions/
  retrospective closure artifacts. Those panel findings applied the pentest-run
  rubric to a repository diff and are not code defects.
- `_fallback_status_is_active("working (closed)")` intentionally treats the
  leading canonical status as current. Historical parenthetical text cannot
  override it; the inverse `closed_type_b (was blocked_type_a)` is regression-tested
  as terminal.
- Strict Coda enforcement on all responses while an explicit active run is
  unfinished is intentional and operator-requested. Completion releases the gate;
  ordinary prose can still precede the one final concrete action line.
- Free-form framework retrospectives cannot be mechanically split by semantics.
  The maintained template requires numbered/heading/`Problem:` records; one
  unstructured issue remains supported for legacy compatibility.
- Two arkcli models repeatedly returned parse errors. This remains a panel
  availability limitation; the Claude Code reviewer and successful arkcli member
  still provide independent votes, and the final synthesis records the limitation.

## Fourth-Round Adjudication

- **PR-003 accepted and fixed.** Added Chinese `和/与/及/或`, action-leading
  `并`, and bare English `and/or` to executable-clause splitting. Regressions
  prove two actions are rejected while one scan/verify action with multiple
  parameters or objects remains valid.
- **PR-002 policy claim dismissed, spoof path tightened.** The governing workflow
  explicitly permits a fresh-context Claude same-family reviewer only when no
  heterogeneous reviewer is available; it is weaker but intentionally remains an
  egress-free fallback. However, a generic heading containing `peer_review` no
  longer gains identity from `_backend` metadata: only the exact generated
  `heterogeneous peer_review` or `same-family peer_review fallback` forms do.
- **PR-001 and PR-004 dismissed as bundle misreads.** E-002 indexes the existing
  `selftest_all.log` with size and SHA1. E-001 indexes `run_gate.diff` as an
  existing 10,925-byte stand-alone artifact; both are present in
  `review_bundle.json`. The unsupported manual Stop-event wording was also
  replaced with the exact focused-selftest claim.
- **PR-005 dismissed.** E-001/E-002 are the evidence IDs explicitly cited by the
  maintenance report; empty `supports`/`refutes` arrays represent no cross-EID
  relationship, not a missing artifact or unbound report claim.
- **Fallback-heading blind spot accepted and fixed.** The last-resort Markdown
  parser now recognizes an F-id anywhere in an H3 heading, including
  `### Front F-001`; a regression proves the active front remains enforced.
- The free-form multi-issue retrospective limitation remains the documented
  template tradeoff. The tempfile permission concern is not a code defect:
  Python's `NamedTemporaryFile` creates the file with owner-only mode before the
  explicit `chmod(0600)` and atomic replace.

## Fifth-Round Adjudication

- **PR-003 partially accepted and fixed.** A leading bullet is intentionally
  rejected because the contract requires the final line to begin exactly with
  `下一行动:`. The real verb-list bypass was fixed by expanding common Chinese
  and English actions (including save/write/commit/create/delete) and requiring
  every non-BLOCKED Coda to contain an executable action or known tool. Tests
  cover a bare F-id with no action and a hidden second save action.
- **PR-004 accepted and fixed.** Cookie `Expires` values parsed without timezone
  are normalized to UTC before epoch comparison. A deterministic epoch-boundary
  regression would fail under the local Asia/Shanghai interpretation.
- **PR-005 claim was inaccurate but exposed a load-path gap.** Deletion markers
  are removed before `_save_cookie_jar`, so `None` was not serialized by the
  preflight path. `_load_cookie_jar` now nevertheless drops JSON `null` values so
  a manually edited or legacy jar cannot emit `name=None`.
- **PR-006/PR-009 accepted and fixed.** Merely writing `fresh-context` in the
  heading no longer establishes reviewer identity. Manual fallback records need
  a non-placeholder Reviewer/Backend; generated peer-review records need their
  exact kind plus backend metadata.
- **PR-010 accepted and fixed.** An impossible/empty protocol state now returns
  an explicit hard-block message instead of a future fail-open. A monkeypatched
  regression proves the branch.
- The cross-module fallback-heading observation was also addressed: the
  read-only fallback now recognizes F-id sections at H2 through H6, matching the
  broader closure counter while retaining canonical Status parsing.
- **PR-001 again dismissed by direct bundle inspection:** E-002 and
  `selftest_all.log` are present; E-001 includes `run_gate.diff` with SHA1 and
  size. **PR-002** is a review-ledger granularity preference, not missing proof:
  E-001 binds the frozen diff and per-component artifacts while E-002 binds the
  complete test run. **PR-007** is already respected: context/disposition are
  claims and adjudication; the diff/log/hash artifacts are the evidence.

## Sixth-Round Packaging Fix

- **PR-001/PR-002/PR-003 accepted as review-egress packaging defects.** The JSON
  bundle contained E-002 and `run_gate.diff`, but duplicating the aggregate
  aggregate after all component diffs pushed the external prompt over its global
  excerpt cap before later evidence could be seen. The ledger now uses four
  scoped EIDs and indexes only seven complete, non-overlapping component diffs;
  E-003 carries the raw test log and E-004 carries base/hash provenance.
- The aggregate `reviewed.diff` remains a local recomputation artifact with its
  SHA1 in `diff_manifest.md`; excluding its duplicate excerpt from the egress
  bundle is deliberate, not evidence deletion.
- **PR-004/PR-005 addressed by structure.** Cross-EID Supports now show which
  behavior claims are controlled by E-003, and the report names each subsystem
  assertion instead of relying on disposition prose.

## Seventh-Round Adjudication

- **PR-001 accepted and fixed.** `run_gate.py` no longer degrades to a weaker
  heading-plus-verdict regex when the canonical `check_run` predicate is missing
  or raises. Closure stays blocked until the structured validator is available;
  a focused regression monkeypatches the import away and proves fail-closed.
- **PR-002 dismissed as an intentional egress design.** External reviewers
  received every changed line through the seven complete component diffs. The
  aggregate is retained locally for Git-base recomputation but omitted from the
  external prompt solely to avoid duplicating the same source and hiding
  later evidence under the total cap.
- **PR-003 removed at the source.** The final report no longer asks external
  reviewers to arbitrate the local multi-round disposition narrative.
- **PR-004 remains a transparent limitation.** The suite includes an actual
  subprocess `output_gate -> run_gate` integration with one explicit pointer,
  but no production run was mutated merely to manufacture a trace. The full
  selftest log and implementation are retained; current live-run checks pass with
  four pre-existing soft warnings.

## Eighth-Round Adjudication

- **PR-003 accepted and fixed.** An unfinished run with zero active fronts now
  requires the Coda to name a concrete closure/control-plane object such as
  `check_run`, coverage, review, report, decisions, or retrospective. Generic
  “analyze another issue” output is regression-tested and blocked.
- **PR-004 accepted and fixed.** The substantial-length legacy prose bypass was
  removed. Independent review now always needs a real non-placeholder
  reviewer/backend identity and a verdict scoped to that review block.
- **PR-005 accepted and fixed.** Completion review no longer has a weaker
  `run_gate` fallback, and the canonical gate no longer accepts a self-asserted
  single line. Completion requires a substantive `## CodexCompletionReview`
  section with Reviewer, Verdict, and concrete cross-check detail; docs and
  tests now match.
- **PR-001/PR-002 remain evidence limitations, not code regressions.** The full
  suite is locally re-executed and raw output retained; external review receives
  every changed line through complete component diffs while the aggregate stays
  locally recomputable. Arkcli minimax/glm parse failures remain recorded.
