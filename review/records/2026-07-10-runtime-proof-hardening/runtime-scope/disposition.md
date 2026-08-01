# Runtime Scope Round 1 Disposition

## PR-001 - Runtime observation certainty

- Status: accepted
- Resolution: E-003 is capped at 0.8. The installed-entrypoint observation now includes negative and positive completion paths and is replicated by separate module selftests. It is process evidence, not OS-level attestation.

## PR-002 - Report and review stubs

- Status: accepted
- Resolution: `report.md` now maps every claim to E-001 through E-004, states the maintenance threat boundary, and identifies the first-round review record and this disposition.

## PR-003 - Missing target vulnerability artifacts

- Status: dismissed
- Resolution: This is explicitly a framework-maintenance scope with no network target. HTTP vulnerability artifacts would be unrelated evidence; code diffs, installed hook observations, and regression logs are the applicable artifacts.

## PR-004 - Agent Board parser failure was fail open

- Status: accepted
- Resolution: `_check_agent_board_needed` now returns a four-front fail-closed reminder when the canonical parser fails while a frontier exists. Its selftest injects the parser failure.
- Evidence: `workers.diff`, E-002, `selftest_all.log`.

## PR-005 - `probing` and `working` policy shift

- Status: accepted
- Resolution: Both statuses are unfinished active work. Excluding them would allow a front to be relabeled and evade fan-out. The rationale is now explicit in `context.md` and E-001.

## PR-006 - Partial arkcli panel

- Status: accepted
- Resolution: Round one remains retained as partial. The final rerun uses the Codex-authored review matrix (arkcli panel plus fresh Claude) and records any backend failure without counting Codex self-review.

## Blind Spots

- Automatic fail-open is intentionally rejected: it converts hook breakage into an unobserved process bypass. Recovery is an explicit operator/local-maintenance action while active-run actions remain fail closed.
- `workers.py assign` creates the assignment row and agent file in the same command path; the PreTool gate requires both before accepting an Agent token.
- The six-hour session-bound turn contract avoids ordinary long-analysis expiry. A new prompt refreshes it, and a mismatched session cannot reuse it.
- The isolated subprocess observation uses the installed settings and exact hook entrypoint with Claude-shaped events. A newly restarted interactive Claude session remains the final deployment smoke test, not a claim made by these artifacts.

# Runtime Scope Round 2 Disposition

## R2-PR-001 - E-003 observation support

- Status: accepted
- Resolution: The round-two statement that E-003 indexed only `installed-settings.json` contradicts the frozen bundle, which indexed settings plus all three observation chunks. Even so, the evidence is strengthened: the same frozen entrypoint now runs twice in separate temporary runs, both traces are retained, and E-001/E-002 explicitly limit themselves to code/selftest claims while E-003 owns runtime activation.

## R2-PR-002 - Missing SessionStart selftest

- Status: accepted
- Resolution: `.claude/settings.json` now runs `tools/turn_contract.py --selftest` at SessionStart. The module selftest verifies this wiring and that the global PreToolUse contract remains first.

## R2-PR-003 - Code findings versus runtime activation

- Status: accepted
- Resolution: E-001 and E-002 now state that they prove code behavior and negative controls; E-003 separately carries the installed-entrypoint execution traces with transcript-backed runtime receipts.

## R2-PR-004 - Partial arkcli panel

- Status: accepted
- Resolution: The partial result is retained as round two. The repaired frozen bundle is rerun; failed arkcli members remain explicit and are not silently counted.

## Round 2 Blind Spots

- The archived observation script now locates the repository root by searching ancestors for `tools/turn_contract.py`, so it executes from both the parent record and runtime-scope copy.
- Hook messages and anti-drift reminders now explicitly name `open/probing/working/type-A` as active states.
- Automatic fail-open remains dismissed by design. Startup selftest plus explicit local repair is the recovery path; silently disabling gates would violate this task's threat objective.
- Negative paths are first-class assertions: ambiguous/explain/pause writes, old/manual/unmerged Agents, stale/unlisted Cron state, direct receipt edits, background review, and bare completion PASS are all rejected.
