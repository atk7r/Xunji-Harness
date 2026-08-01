# P0-2 Setup Transaction Review Record

- Date: 2026-07-14
- Verdict: WARN WITH RECORDED REVIEW-MATRIX LIMITATION
- diff_fingerprint: 98c8243c6f15e92c
- reviewed_diff: 98c8243c6f15e92c
- Author/driver: Codex
- Final staged fingerprint: `98c8243c6f15e92c`
- Base commit: `dd64cf8ee986b1ee2f8701897e1a99b3688d1f01`
- Scope: P0-2 transactional setup, active-pointer CAS/recovery, setup adapters,
  turn-contract/prepared-state gates, conformance fixture, architecture/lifecycle
  documentation, and the active-pointer sole-writer rule.
- Final synthesis: **WARN — code findings were repaired and regression is green;
  independent-review coverage is partial and is not represented as matrix PASS.**

## Final behavior reviewed

The staged implementation establishes `tools/setup_transaction.py` as the only
direct active-pointer writer and makes the setup path:

```text
validate source
-> build complete same-filesystem staging run
-> write prepared receipt
-> record prepared_not_active publish intent
-> atomic rename
-> locked compare-and-swap pointer activation
-> committed/recovered receipt
```

The same activation primitive is used by setup, same-transaction retry, explicit
resume/set-active, statusline selection, and clear. A compare snapshot is required
at the primitive boundary. Formal receipts require transaction/source identity;
missing-receipt legacy runs are supported only because `activate_existing_run()`
explicitly calls the primitive with `allow_legacy=True`. Corrupt or mismatched
formal receipts cannot fall back to legacy behavior.

## Verification observations

All observations below are real command results, but local execution alone is not
promoted into an independent review vote.

- Focused checks passed:
  - `python3 tools/setup_transaction.py --selftest`
  - `python3 tools/setup_run.py --selftest`
  - `python3 tools/loop_bootstrap.py --selftest`
  - `python3 tools/xunji_statusline.py --selftest`
  - `python3 tools/turn_contract.py --selftest`
  - `python3 tools/check_run.py --selftest`
  - `python3 tools/check_rules.py`
  - `git diff --cached --check`
- Exact code candidate full regression: `62 passed, 0 failed (86.8s total)`.
  Raw log SHA1: `499ca44fda961a99b88b6c808098848d94fbc05b`.
- At the operator's explicit request, Claude Code ran as the primary driver and
  actually executed transaction selftest, rules check, full selftest, and staged
  diff check. Its process exited 0, reported all four command exit codes as 0,
  and recorded `permission_denials: []`. Raw JSON SHA1:
  `de84a47629821584538d72417b8ece139ef3efb2`.
- Claude primary-driver execution is runtime verification only. It is not counted
  as the independent reviewer of Codex-authored work.

## Independent review chronology

### Round 1 — code bundle before final hardening

- Candidate fingerprint: `26d692ddb03716c7`
- Frozen bundle: `8a06c662b32dac3173607547774511f911d7270b`
- Evidence index: `bd48928f59fcc866e4bb91574cb1e10f22dcd465`
- arkcli verdict: WARN; Kimi completed, GLM response could not be parsed.

Material findings and dispositions:

1. The full regression log was a single observation and was overstated at
   certainty 1.0. Accepted. Final synthesis treats runtime results as observations;
   Claude's separate execution is corroboration, not a review vote.
2. `commit_activation_cas(expected=None)` could bypass comparison. Accepted and
   fixed: `expected: PointerSnapshot` is mandatory; the conditional `None` bypass
   was removed and the missing-expected call is tested.
3. The sole-writer claim lacked a repository-wide tripwire. Accepted and fixed:
   `tools/check_rules.py` now AST-scans watched Python files for direct pointer
   mutations outside `tools/setup_transaction.py`, and self-checks one forbidden
   writer plus one allowed reader.
4. One arkcli model failed parsing. Retained as a backend limitation.

Round-1 blind spots were also dispositioned:

- Target-only setup does persist `classify/coverage.json`; `_coverage_ready()` and
  prepared-run validation require a host-bearing asset before commit.
- Empty formal identity no longer doubles as legacy compatibility; `allow_legacy`
  defaults false and only the existing-run adapter opts in for a missing receipt.
- Ambiguous `PermissionError`/`OSError` during lock-owner probing remains treated
  as live. This conservative choice may cause a bounded timeout but cannot steal
  an uncertain lock.
- Wrapper invocation passed the live project hooks during the final Claude primary
  execution, including its exit-code collection wrapper.
- Lock order is setup then activation. Standalone activate/clear acquires activation
  only; no reverse activation-then-setup edge exists.

### Round 2 — final production-code bundle

- Code candidate fingerprint: `23de5415adbdebd2`
- Frozen bundle: `d07f126b6c88bacfc6224a0fd3899d1fc12bb7eb`
- Evidence index: `f9ab8287e5583030cb101a1328c1167f44a42c58`
- arkcli result: partial WARN.

The structured result contains one finding only: a backend-error warning because
Kimi exceeded 300 seconds. The blind-spot list is empty and no new code finding
was emitted. Retry context records an earlier all-model failure including a GLM
parse error. This is independent coverage of the final code, but not a complete
two-model panel.

The stored Markdown output ends with a truncated failed-backend tail (`This is a
significant...`). That tail is not treated as a completed finding or evidence.
The structured result and exact bundle hashes above are the auditable result.

### Round 3 — final checkpoint/fingerprint supplement

`docs/ARCHITECTURE.md` was updated after code review so the Maintenance Checkpoint
would record the actual operator-requested Claude role and partial arkcli result,
instead of preserving the obsolete future requirement "arkcli + Claude review".
Production code did not change in this step.

- Final fingerprint: `98c8243c6f15e92c`
- Supplemental bundle: `620d142a15eef7b6fe321da6c565c84925116937`
- Evidence index: `303baa5b101752a7ef5f97c19f3b9b5822d78671`
- arkcli verdict: WARN, no blocker.

Supplemental warnings and synthesis:

1. The supplied final-code-review Markdown is truncated. Accepted as an artifact
   limitation; this record cites the structured finding and does not infer text
   beyond it.
2. This permanent record was absent from the pre-record bundle. Resolved by this
   file; review records are excluded from the staged fingerprint by design.
3. The small supplemental bundle did not repeat full post-fix code. Accepted as a
   packaging limitation; the complete production source/diffs remain frozen in
   code bundle `d07f126...`.
4. The selftest log is environment-provided. Accepted; it remains a verification
   observation and is not used as an independent reviewer vote.
5. GLM parsing failed in the supplemental panel. Retained as a limitation.

## Review matrix limitation

The normal Codex-authored matrix requests arkcli plus Claude fresh-context review.
The operator explicitly clarified that Claude Code was to act as the primary
driver running the modified code, **not** as another reviewer. This instruction
was respected. Consequently:

- Codex self-review is not counted;
- Claude primary execution is not counted as a reviewer;
- arkcli supplied independent review, but its model panel was incomplete;
- the final status is WARN, not PASS.

This limitation is acceptable for committing this non-live-run maintenance diff
because the independent reviewer emitted no unresolved code blocker, all concrete
code findings were repaired, the final code candidate passed focused and complete
regression, and the missing review vote is disclosed rather than fabricated.

## Final disposition

- Unresolved BLOCKER: none.
- Accepted code findings: fixed in fingerprint `98c8243c6f15e92c` (production
  code identical to reviewed code candidate `23de5415adbdebd2`; later delta is the
  checkpoint truth update).
- Residual limitations: arkcli backend timeout/parse failures, no Claude review
  vote by operator instruction, local verification remains environment-provided.
- Commit decision: proceed with WARN and preserve this record as the auditable
  limitation/disposition source.
