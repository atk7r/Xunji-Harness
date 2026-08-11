# Session-scoped single-flight loop review

Verdict: WARN
diff_fingerprint: 0099fa09db1064ed
reviewed_diff: 0099fa09db1064ed

- Date: 2026-08-11
- Author / synthesizer: Codex
- Independent reviewer: fresh-context Claude Code, DeepSeek-backed
- External assistance: disabled by local policy; no heterogeneous external vote
- Final task-delta fingerprint: `e930969b55329012c5d401bacbb992ad9dec1e818ad55e13cb3d07f9a64cbe14`
- Final `tools/turn_contract.py` SHA-256: `0a3b5be51b03e68e113b9ba0a23179dd3edcc3fdaa2c8632e96e2cd844be99dd`
- Disposition: the two independent WARN findings are accepted and resolved; the
  same reviewer returned an explicit remediation PASS. No P0-P2 remains open.
  Two later safe-mode attempts failed before producing a structured full-patch
  vote and are recorded as review-transport limitations, not additional PASSes.

The machine verdict remains WARN because this commit-only fingerprint necessarily
contains pre-task changes already present in the same five framework files; the
task-only delta does not apply to HEAD independently. Those earlier ranges retain
their own dated review/driver records in the Architecture checkpoint, but no fresh
reviewer produced one new structured vote over the combined 4,253-line staged
snapshot. This is a review-provenance limitation, not an unresolved loop finding.
The operator's broader pre-existing index fingerprint was `749c46052e97c9cd`;
it is not this explicit-path commit and remains outside the commit.

## Reviewed contract

Literal `/loop` must establish or reuse one run-bound Claude Code Cron with
`recurring=true`, `durable=false`, and exact wake `/loop runs/<dir>`. The Cron is
client-session scoped. Closure deletes it. A wake while a cycle is active is
coalesced without a queue. Same-session `继续` after typed `cycle_end` starts one
early cycle and consumes only the adjacent wall-clock tick; a later tick remains
eligible.

The scoped candidate covers:

- `tools/turn_contract.py`
- `.claude/skills/xunji-run-lifecycle/SKILL.md`
- `docs/templates/loop_prompt.md`
- `docs/ARCHITECTURE.md`
- `tools/harness/fixtures/driver-doc-conformance.json`

## Independent findings and disposition

Fresh-context session `42827ac2-a9ed-45a8-9949-ba442f48b042` reviewed the
initial targeted implementation and returned `VERDICT: WARN` with two findings.
The combined transcript after remediation follow-ups has SHA-256
`0ee287c3730b668714cbc25cbe4514177edff52976c4f3673f775aa8d4fb4b45`.

1. P1 — invalid receipt/owner state could fall through to an ordinary EXECUTE
   replacement. Accepted. Scheduler-shaped wakes now validate the full runtime
   chain and owner projection first. Invalid chain, ambiguous CronList, multiple
   owners, or wake/owner mismatch produce `TICK_STATE_INVALID` and a new
   EXPLAIN-only loop contract. A clean zero-owner state remains eligible for an
   operator's explicit `/loop` to create a new Cron.
2. P2 — the manual-advance receipt could survive a failed contract commit and
   consume a later real tick. Accepted. The owner now builds the exact contract
   first and hashes its canonical bytes into a preparation receipt. Pending-tick
   projection requires the current contract hash, prompt, session, and transcript
   to match. Failed persistence leaves an `orphaned` preparation that cannot
   consume a future tick.

Negative fixtures inject both an invalid runtime chain and a manual contract
persistence failure. The same reviewer was then given the exact final code hash,
the two mechanical fixes, and their passing fault-injection fixtures; it returned
the explicit conclusion `评审结论已定（PASS），无需再改代码`. Its unrelated live-run
next-action text came from project context and is excluded from this maintenance
disposition; no live action was delegated or executed from reviewer prose.

Two extra fresh `--safe-mode --tools ""` review attempts were made against the
full patch/current exact excerpts. Session `6a6f1c27-9e28-497b-9df8-1dab457d6b9d`
ended with stream idle timeout (transcript SHA-256
`f3673d08926a1c36ee77808473e9acf49bf3ac8af36cdb98b10358a901d45470`).
Session `f6527e24-f2ba-45b9-b7fe-5a18eb4f0752` exhausted its output/budget before
a verdict (transcript SHA-256
`e385fce6a3ac6c1e38c1cd854bc03546df8eb5c3e57e9709e9c9b20f08420517`).
Neither is counted as a vote.

## Verification

- `python3 tools/selftest_all.py`: `78 passed, 0 failed` in 141.4 seconds.
- Focused `turn_contract`, `setup_transaction`, `xunji_statusline`, template,
  bootstrap, Python compilation, JSON parsing, and scoped diff checks passed.
- Final exact-candidate real-driver session
  `81d9b2a6-8fef-484a-afc9-481c4769e5cd` used the actual Claude client `/loop`
  expansion and real Hooks. Runtime receipts show: CronList seq 21 empty;
  CronCreate seq 22 job `84f15657`, `*/10 * * * *`, exact wake,
  `recurring=true`, `durable=false`; CronList seq 29 observed it; CronDelete seq
  30 removed it; CronList seq 31 was empty. Transcript SHA-256 is
  `ddd1cade988f775ec018726069f67febd26c0a96d086d5d9a607878f015bda21`.
  It contained no Agent, Web, Bash, Write, or Edit call.
- TaskUpdate attempts after deletion were correctly denied with
  `XUNJI_E_CRON_CREATE_REQUIRED`; they neither recreated the job nor changed run
  evidence. This is a bookkeeping UX limitation, not a scheduler safety failure.

## Residual limits

- The live driver proved session-only create/list/delete/quiescence. The 10:09 /
  10:10 / 10:20 collision and over-ten-minute cycle cases are deterministic
  fault/timing fixtures, not a ten-minute wall-clock live wait.
- Session exit stopping the task is owned by Claude Code's `durable=false`
  scheduler lifetime. Xunji records and validates that property but does not run
  a second daemon or resurrect a job from historical receipts.
