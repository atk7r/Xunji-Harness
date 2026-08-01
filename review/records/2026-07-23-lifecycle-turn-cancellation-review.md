# Natural-Language Lifecycle + Turn-Stale Cancellation Review

Verdict: WARN
diff_fingerprint: fb4689e072268bc9
reviewed_diff: fb4689e072268bc9

- Date: 2026-07-23
- Author/driver: Codex
- Synthesis owner: Codex
- Codex self-review counted as an independent vote: no
- Final staged candidate SHA-256:
  `95d491f2fe052b69ecbdb627fbd0d1280da92f8c10464e373619a0187d047972`
- Final staged scope: 15 files, 976 additions, 167 deletions
- Final source findings: none unresolved
- WARN reason: required heterogeneous panel was partial because both arkcli
  backends failed; the available fresh-context Claude reviews and all source
  findings are recorded below.

## Reviewer Availability

The Codex-authored matrix was attempted with `tools/peer_review.py` against a
frozen maintenance bundle. The Claude backend completed. The arkcli panel did
not produce a valid vote: `kimi-k2.7-code` timed out after 300 seconds and
`glm-5.2` returned truncated/unparseable output. This is recorded as a review
availability limitation, not a PASS.

The formal panel record initially returned `NEEDS_DRIVER` with five items.
Fresh-context/no-tools Claude was then run against the complete source diff,
schema, selftest output, and real-driver record:

- source review session: `c96f494c-dba3-4b67-aa80-8929050d28e4`
- final exact-diff review session: `2a59ab7d-b42c-42f7-8182-0f0a585621c6`
- supplemental authoritative-source review session:
  `a45bfe61-5dd8-46c0-8581-c45c6d45f614`
- configured backend: DeepSeek-backed Claude Code 2.1.201

## Findings And Dispositions

### PR-001 — require HTTP `.replay.json` for local driver — rejected

The formal reviewer applied the target HTTP evidence replay rule to a local
framework-maintenance driver. The driver acceptance surface is the Claude
transcript, Hook/runtime receipts, cancellation tombstone, work plan, loop
journal, hashes, and forbidden-effect absence. No target finding or HTTP
response was promoted. The durable E2E record binds these artifacts and does
not use Claude's prose as acceptance evidence.

### PR-002 — missing selftest artifact — resolved

The review bundle was refreshed with the full verbose selftest output. The
final candidate passed `tools/selftest_all.py`: 69 passed, 0 failed in 115.2
seconds. Focused `turn_contract`, `workers`, template, rule, and diff checks
were rerun after the final regression additions and passed.

### PR-003 — natural-language boundary coverage too narrow — resolved

`turn_contract.py` now exercises ten Chinese/English resume forms, including
mixed run+URL prompts and the reviewer's exact pure forms:

- `恢复 run runs/other_20260101`
- `Resume run runs/other_20260101`

The regression directly asserts that the Chinese form produces
`natural_bind=True`, then proves all ten contracts remain least-authority
`INTENT_PENDING` until the exact public resume argv is model-selected. Existing
negative fixtures cover denial, questions, quoted data, multiple URLs, absent
anchors, and source substitution.

### PR-004 — no v1/v2 mix rejection test — accepted and fixed

The final `workers.py` selftest constructs both directions:

- legacy v1 transaction with a v2 tombstone;
- v2 transaction with a valid legacy v1 tombstone.

Both must fail with
`ASSIGNMENT_CANCELLATION_TRANSACTION_VERSION_DIVERGED`.

### PR-005 — no `stale_basis=both` path — accepted and fixed

A real delegated-but-unlaunched fixture now changes canonical inputs and turn
binding before cancellation. The v2 receipt must record `stale_basis=both`,
different plan/observed input digests, different plan/observed turn bindings,
and removal of only the exact unlaunched assignment. Inputs-only and turn-only
paths remain covered.

### FR-001 — alleged `INTENT_PENDING`/resume invariant crash — rejected

Two fresh reviews claimed `_contract_from_event` could set
`mode=INTENT_PENDING` and retain `lifecycle_operation=resume`. Authoritative
source does the opposite:

```python
if mode != EXECUTE:
    lifecycle_operation = "none"
```

It also clears `loop_source`, derives `loop_source_kind=none`, leaves
`run_transition_requested=false`, and validates the compiled state before
returning. The pure natural-language fixtures above execute the claimed path
and pass.

The supplemental reviewer was given the exact compiler source and final test
delta. It returned `NOT_CRASH`, confirmed that `INTENT_PENDING` carries safe
defaults, and rated the ten-variant regression `SOUND`. Its only informational
note suggested redundant intermediate assertions for one older single fixture;
the ten-variant aggregate already asserts those exact fields for every prompt,
so no additional change was needed.

### FR-002 — receipt validator does not independently load live turn — noted

`agent_settlement.validate_cancellation` validates the immutable receipt and
cross-field identity. It intentionally does not own the live run. The
single-writer `workers.cancel_unlaunched_assignment` loads the current turn and
input truth, computes the stale basis, freezes the artifacts, and commits the
transaction. Moving live-run ownership into the value validator would duplicate
the transaction owner rather than strengthen the boundary.

## Verification And Acceptance

- focused lifecycle/cancellation/schema/doc checks: PASS
- `tools/selftest_all.py`: 69/69 PASS
- isolated Claude primary-driver through real Hooks/receipts: PASS
- target actions in driver: 0
- v2 inputs/turn/both cancellation coverage: PASS
- bidirectional v1/v2 mix rejection: PASS
- final supplemental independent source review: no concrete defect
- heterogeneous arkcli availability: partial/unavailable, therefore overall
  review record remains WARN rather than claiming a full panel PASS

The remaining WARN is a reviewer-availability limitation, not an unresolved
source defect.
