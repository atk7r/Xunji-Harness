# Round 1 Disposition

## Accepted And Fixed

### R1-01 - Coverage derivation could fail open
- Source: arkcli GLM raw output recovered from parse-error tail.
- Disposition: accepted.
- Fix: `turn_contract.py` now derives inventory through `coverage_matrix`, returns an explicit derivation error, and denies target work when a coverage file exists but no valid rows can be produced.
- Verification: turn-contract selftests cover corrupt-only coverage and corrupt-root plus valid nested coverage.

### R1-02 - SubagentStop may precede async launch acknowledgement
- Source: Claude blind-spot review.
- Disposition: accepted.
- Fix: runtime attempt matching uses the nearest `SubagentStart` generation within a bounded hook race window, so a stop after that start may precede PostToolUse without being lost. Launch projection replays the derived attempt and writes `done` when the stop already exists.
- Verification: runtime-receipts selftest records Start, Stop, then PostToolUse and requires a returned attempt plus done projection.

## Dismissed With Evidence

### R1-03 - Dot-containing hostname boundary allegedly fails
- Disposition: dismissed.
- Reason: the hostname is `re.escape`d and the lookarounds only reject adjacent hostname characters; dots inside the escaped token are matched literally. The gate now also consumes the same derived rows as coverage_matrix rather than stopping at the first coverage path.
- Verification: turn-contract tests enforce `nested.example` from valid nested coverage when root coverage is corrupt.

### R1-04 - DIFF explicit no-suffix paths allegedly collide
- Disposition: dismissed.
- Reason: A is `<base>` and B is `<base>.b`; replay suffixes are appended, yielding `<base>.replay.json` and `<base>.b.replay.json`.
- Verification: probe selftest writes both no-suffix bodies and both replay files and asserts distinct paths.

### R1-05 - Claude and Codex skill trees differ
- Disposition: dismissed as an authority-boundary misunderstanding.
- Reason: repository `AGENTS.md` explicitly makes `.claude/skills` the Claude primary-driver source and `.agents/skills` the Codex maintenance guide. They intentionally differ in scope; both now state the same asset-token and attempt semantics.

## Residual Limitation

### R1-06 - No live Claude Agent integration spawned by this Codex task
- Disposition: recorded limitation, not silently dismissed.
- Mitigation: tests replay exact real hook payload shapes observed in the supplied Claude histories, including `status=async_launched`, real `agentId`, actor `agent_id`, SubagentStart/Stop, normal order, and reverse race order. A future live-driver smoke fixture would further reduce schema-drift risk.

## Panel Availability

- Claude fresh-context review completed.
- `kimi-k2.7-code` timed out at 300 seconds.
- `glm-5.2` produced a useful finding but failed the strict output parser.
- Round 2 must rerun arkcli after fixes; backend failure is not treated as PASS.

# Round 2 Disposition

## Accepted And Fixed

### R2-01 - Unknown WebFetch destination could bypass proxy enforcement
- Source: arkcli Kimi PR-001 (BLOCKER).
- Disposition: accepted.
- Fix: active-run `WebFetch` is now denied regardless of whether its destination already appears in coverage; public research must use WebSearch/knowledge tools, while target traffic uses the proxy-aware project tools.
- Verification: turn-contract selftest covers both known and unknown WebFetch destinations.

### R2-02 - Legacy empty-asset child assignment could skip the actor boundary
- Source: arkcli Kimi PR-002 (WARN).
- Disposition: accepted.
- Fix: any child target action from a legacy/empty-asset assignment is denied; Root must create a new explicit asset-bound assignment.
- Verification: turn-contract selftest removes a running child's asset package and proves its target action is rejected.

### R2-03 - Proxy-aware tool could target a host absent from coverage
- Source: arkcli Kimi PR-004 (WARN).
- Disposition: accepted.
- Fix: the turn gate extracts explicit URL, hostname, and IP destinations and compares them with host-only keys derived from the coverage ledger. Unknown destinations are denied before execution.
- Verification: a known `probe.py` URL remains allowed and `https://unknown.example/` is denied with an explicit unknown-target error.

## Dismissed With Evidence

### R2-04 - Per-asset activity helper could not be verified
- Source: arkcli Kimi PR-003 (WARN).
- Disposition: dismissed as review-bundle excerpt truncation.
- Reason: `runtime_receipts.agent_asset_activity()` exists in the live diff and is called by `workers.py`; both modules contain direct selftests for per-asset receipt counting and zero/partial-asset merge rejection.
- Verification: `runtime_receipts`, `workers`, and the full 57-suite run pass on the current tree.

## Panel Availability

- Kimi produced a valid blocker-bearing vote.
- GLM again produced useful partial text but failed the strict parser; this is recorded as a backend limitation, not PASS.
- Fresh-context Claude produced blind-spot notes; the coverage-warning concern was already directly asserted by `coverage_matrix.py --selftest`, while the live-Agent smoke remains the residual limitation recorded in R1-06.

# Final-Review Disposition

## Accepted And Fixed

### FR-01 - Direct-egress opt-out lacked current-turn attestation
- Source: arkcli Kimi PR-002 (WARN).
- Disposition: accepted.
- Fix: `XUNJI_PROXY_REQUIRED=0/false/no/off` in either Bash text or its environment is denied unless the current operator prompt explicitly approves direct egress. The approval is stored in the current turn contract and transfers with a controlled run transition.
- Verification: turn-contract selftests cover inline and structured-env opt-out denial plus current-prompt approval.

### FR-02 - Non-Bash target network tools were not proxy-attested
- Source: arkcli Kimi PR-003 (WARN).
- Disposition: accepted.
- Fix: non-local tool categories with explicit URL/IP destinations are target actions; non-Bash target network tools are denied because they cannot attest `XUNJI_PROXY`. WebSearch and local read/write/control tools remain non-egress categories.
- Verification: a synthetic browser navigation to a ledger host is denied while WebSearch remains outside the target-action path.

### FR-03 - Assignment projection failures were silent
- Source: arkcli Kimi PR-004 (WARN).
- Disposition: accepted.
- Fix: malformed assignment state now raises inside the convenience projection and writes protected `state/runtime_projection_error.json` bound to the immutable receipt seq/hash. A later successful lifecycle projection clears the stale error.
- Verification: runtime-receipts selftest corrupts assignments.json and requires the projection error record.

### FR-04 - Reverse lifecycle matching used a fixed 10-second window
- Source: arkcli Kimi PR-005 (WARN) and Claude blind spot.
- Disposition: accepted.
- Fix: matching now uses the closest `SubagentStart` for the unique Claude agent id, without a wall-clock cutoff; the matching Stop must still be at or after that causal Start.
- Verification: selftest records Start/Stop 35-40 seconds before a delayed launch acknowledgement and still projects the unique attempt as returned.

### FR-05 - Schema-v1 assignment handling was implicit
- Source: arkcli Kimi PR-007 (WARN).
- Disposition: accepted.
- Fix: `workers.load_assignments()` explicitly migrates schema-v1 rows to schema 2 with empty `assets` and `attempts` defaults while preserving their identity/status. Empty legacy target packages remain fail-closed until Root creates a new explicit package.
- Verification: workers selftest loads an actual schema-v1 fixture and asserts the schema-v2 shape.

## Dismissed With Evidence

### FR-06 - `agent_asset_activity` dependency may be missing
- Source: arkcli Kimi PR-001 (WARN).
- Disposition: dismissed as excerpt truncation.
- Reason: the live file defines `runtime_receipts.agent_asset_activity()` and both `runtime_receipts.py --selftest` and `workers.py --selftest` directly exercise per-asset receipt counting and zero/partial-package merge rejection.

### FR-07 - Global unassigned-asset gate may deadlock assigned work
- Source: arkcli Kimi PR-006 (WARN).
- Disposition: dismissed as an intentional control-plane ordering constraint.
- Reason: the gate blocks target traffic, not frontier/assignment edits or workers/control commands. Root can and must map every reachable/unknown asset before probing any one asset; this is the requested prevention against selective-asset laundering, not an execution deadlock.

## Panel Availability

- Kimi produced a valid WARN-bearing vote.
- GLM again failed strict parsing and is not counted as a clean vote.
- Fresh-context Claude completed and confirmed the post-BLOCKER hashes; a final current-hash rerun remains required because FR-01 through FR-05 changed production code.

# Current-Hash Review Disposition

## Accepted And Fixed

### CH-01 - Projection stopped silently on assignment/front mismatch
- Source: arkcli Kimi PR-002 (WARN).
- Disposition: accepted.
- Fix: a row with the matching assignment but a different front now raises a projection error bound to the immutable receipt instead of returning silently.
- Verification: runtime projection errors are persisted and protected; normal exact-front projection tests remain green.

### CH-02 - Negated direct-egress wording could resemble approval
- Source: arkcli Kimi PR-003 (WARN).
- Disposition: accepted.
- Fix: the current-prompt approval parser now has an explicit denial grammar for Chinese and English (`不要/禁止/拒绝`, `do not/don't/never/deny/forbid`). Approval requires a positive phrase and absence of a denial phrase in the current `UserPromptSubmit` event.
- Verification: turn-contract selftests distinguish positive approval from both Chinese and English negation.

### CH-03 - Runtime projection did not revalidate asset tokens
- Source: arkcli Kimi PR-004 (WARN).
- Disposition: accepted.
- Fix: immutable launch receipts now store normalized `assignment_assets`, and projection requires them to exactly equal the assignment row's asset package. Mismatch raises an auditable projection error.
- Verification: runtime-receipts selftest submits `b.example` against an `a.example` assignment and requires the asset-mismatch error.

## Dismissed With Evidence

### CH-04 - `coverage_merge_satisfied` has no setter
- Source: arkcli Kimi PR-001 (BLOCKER).
- Disposition: dismissed as frozen-bundle visibility failure, not an implementation defect.
- Reason: `workers.update_agent_lifecycle()` calls `_validate_asset_merge()` before changing status and, only after successful validation, sets `coverage_merge_satisfied=True` and stores the per-asset validation record. Its selftest proves zero-tool and partial-package rejection plus full-package success.
- Evidence improvement: `evidence/workers-asset-merge.py.txt` now freezes the complete validator/setter chain so the next reviewer need not infer beyond a truncated diff.

### CH-05 - Egress enforcement cannot be verified after excerpt truncation
- Source: arkcli Kimi PR-005 (WARN).
- Disposition: dismissed as artifact visibility limitation.
- Evidence improvement: `evidence/turn-contract-egress.py.txt` freezes the destination parser, coverage comparison, non-Bash denial, direct-egress turn check, and Agent/Root gate flow.

## Panel Availability

- Kimi produced a valid vote after one timeout/retry.
- GLM again failed strict parsing and is not counted as a clean vote.
- Fresh-context Claude completed. One further current-hash rerun is required because CH-01 through CH-03 changed production code.

# Post-Fix Review Disposition

## Accepted And Fixed

### PF-01 - Coordination signature could fail before writing a contract
- Source: fresh-context Claude PR-001 (WARN).
- Disposition: accepted.
- Fix: `_safe_run_summary()` converts `run_model.summary()` exceptions or invalid output into an explicit schema-error state. The coordination signature includes the error marker, and target PreToolUse remains fail-closed instead of losing the whole turn contract hook.
- Verification: turn-contract selftest forces `run_model.summary()` to raise and requires a deterministic signature plus target-action denial.

### PF-02 - Asset baseline could be directly rewritten to bypass accounting
- Source: fresh-context Claude adversarial blind-spot prompt (PR-006).
- Disposition: accepted as a related hardening improvement.
- Fix: `coverage.json` and `state/asset_ledger.json` join the protected control-plane files; direct Write/Edit/Bash text mutation is denied. `coverage_matrix.py --sync`, `ingest_recon.py`, and setup remain controlled tool paths.
- Verification: direct coverage Write is denied and controlled coverage sync remains allowed.

## Dismissed Or Recorded

### PF-03 - Canonical E-entry is not temporally attributed to the Agent
- Source: fresh-context Claude PR-002 (WARN).
- Disposition: dismissed as a claim-scope mismatch.
- Reason: merge requires both an Agent-id/launch-time-scoped successful target receipt for every asset and a canonical E-entry naming the asset. The E-entry gate proves canonical synthesis coverage, not authorship; Agent authorship is neither claimed nor desirable because Root is the sole canonical synthesizer.

### PF-04 - `.agents` and `.claude` skills may drift
- Source: fresh-context Claude PR-003 (WARN).
- Disposition: recorded non-blocking maintenance risk.
- Reason: repository `AGENTS.md` deliberately assigns different authorities: `.claude/skills` drives Claude Root, while `.agents/skills` guides Codex auxiliary maintenance. They must share tokens where applicable but must not be forced byte-identical.

### PF-05 - No live Claude Agent integration smoke
- Source: fresh-context Claude PR-004 (WARN).
- Disposition: retained as residual limitation R1-06.
- Mitigation: normal/reverse/delayed lifecycle ordering, real observed payload fields, nested fanout denial, actor asset escape, and projection errors are all replayed deterministically. A future Claude-primary live smoke can further reduce runtime-schema drift.

### PF-06 - Claimed absence of adversarial tests
- Source: fresh-context Claude PR-006 (WARN).
- Disposition: dismissed with direct test evidence.
- Reason: current selftests explicitly cover mismatched prompt assets, nested Agent fanout, structured-env and inline direct-egress bypass, unknown hosts, corrupt coverage, delayed reverse lifecycle, tampered receipt chains, zero-tool merge, partial-package merge, and now direct coverage rewrite.

## Panel Availability

- This current-hash arkcli attempt produced no valid model vote: Kimi timed out and GLM failed strict parsing.
- Fresh-context Claude completed with WARN and no BLOCKER.
- Under the Codex-authored matrix, arkcli is treated as unavailable for this final hash after repeated timeouts/parser failures; a final Claude-only fresh-context review will certify the last small PF-01/PF-02 delta, with the missing-arkcli limitation preserved.
