# Claude primary-driver Agent runtime — independent review

- Date: 2026-07-18
- Author under review: Codex
- Reviewer: fresh Claude Code 2.1.201 session through the locally configured
  DeepSeek API
- Model / effort: `deepseek-v4-pro[1m]` / `high`
- Session: `cedeedd9-899f-4d68-b4fe-986eebae642d`
- Backend policy: Claude Code only; arkcli was explicitly not used
- Base: `9b9f51e127c3727b6fcb98c5b672c6b2025535c3`
- Frozen candidate: `e3b5c60c354f8254107589563661be474ad44ba4`
- Frozen tree: `2c0c2f01896e2983bba94a0ce84c55660eab8e2c`
- diff_fingerprint: 27e97384b2c63362
- Transcript SHA-256:
  `7598d0b2a7dc8bdc166ef7a52172c1579c0facce387b321986867de964194a92`
- Verdict: PASS
- Reviewer finding counts: **P0=0, P1=0, P2=0, P3=2**
- Actionable finding counts after Codex synthesis: **P0=0, P1=0, P2=0, P3=0**

The reviewer received a detached, clean worktree created from the exact staged
index. It reviewed the complete 47-file base-to-candidate diff and treated the
earlier Claude-primary E2E record as a claim to cross-check rather than proof.
`.agents/skills`, statusline source/acceptance, the project-introduction deletion,
CCB/TypeScript, target artifacts, and unrelated dirty-worktree files were excluded.

## Verification rerun by the reviewer

- `git diff --check <base>..<candidate>`: passed;
- `python3 tools/check_rules.py`: passed;
- `python3 tools/check_templates.py`: passed;
- `python3 tools/check_runtime_boundary.py`: passed;
- `python3 tools/selftest_all.py --only
  work_plan,workers,runtime_receipts,turn_contract,context_pack,check_templates`:
  6 passed, 0 failed in 15.5 seconds;
- `python3 tools/selftest_all.py`: 69 passed, 0 failed in 103.0 seconds,
  including the authorized real localhost probe;
- final `git status --short`: clean.

## Reviewer conclusions

The reviewer passed all requested focus areas: Root authority remains separate
from effect execution; the optional assignment cap is compatible and freezes at
`SubagentStart`; child attempts are claimed before later policy gates through the
locked append/fsync journal; same-session denied or failed parent tool IDs cannot
win a later async Start allocation; launch, result, review, Root settlement, and
typed `cycle_end` remain causally bound; prompt/skill executable ownership is
consolidated; capability argv validation stays typed and fail-closed; and the
ordinary plus hard-cap E2E assertions agree with the implementation.

The reviewer reported two P3 observations while still returning PASS and stating
that the commit may proceed:

1. It inspected the claim ordinal transaction and concluded that the lock covers
   load, chain validation, ordinal computation, append, and durability barriers.
   It assigned no impact and recommended no change.
2. It claimed the final admitted call (`ordinal == limit`) receives no last-call
   context. This conflicts with the reviewed code and its focused fixture.

## Codex disposition

PASS accepted as the independent vote; Codex retains final synthesis.

- Observation 1 is not an actionable defect. It is a confirmation that the
  read-validate-append transaction is correctly serialized and durable.
- Observation 2 is dismissed as a reviewer false positive. At
  `ordinal == limit`, `ordinal < limit - 1` is false, so execution continues to
  the `else` branch and emits `这是最后一次允许的工具调用`. The selftest fixture at
  `tools/turn_contract.py` constructs ordinal 6 / limit 6 and requires that exact
  final-call context; it passed in both the focused and full reviewer reruns.

No code or documentation change is required by the independent review. This
record covers Phase 2 only; common-role template composition and version/hash
drift or tamper enforcement remain a later phase.

## Limitations

- The review used DeepSeek-backed Claude Code at `high`; no Anthropic API,
  arkcli, MCP, browser, network search, or `ultra` run was used.
- The reviewer did not spawn Agents or replay the two long E2E sessions. It
  cross-checked their committed receipt summaries against the implementation;
  the actual ordinary and deliberate hard-cap runs are recorded separately.
- Passing the framework suite does not bring statusline or other excluded
  working-tree changes into this phase's acceptance or commit scope.
