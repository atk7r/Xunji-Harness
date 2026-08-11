# Runtime tool exposure optimization review

Verdict: PASS
diff_fingerprint: a57c0e30a785783c
reviewed_diff: a57c0e30a785783c

- Date: 2026-08-12
- Author/synthesizer: Codex
- Baseline: `7de2eda9dde4c94464bc0e1e01d054b0da73d266`
- Candidate branch: `codex/tool-exposure-optimization-20260812`
- Review matrix: external assistance is disabled. Independent votes use fresh,
  no-tools DeepSeek-backed Claude Code sessions; Codex author review is not a vote.

## Architecture disposition

The accepted design is **rich typed capabilities with minimum runtime exposure**,
not a minimum number of tools. Semantically different operations remain separate
registry entries so each keeps exact argv validation, effect classification,
scope/privacy/proxy/guard/recorder services, permission treatment, rendering, and
audit identity. Each assignment derives zero to three complete candidate argv from
its frozen lane/front. This block is guidance only: an empty projection does not
remove built-ins or capabilities, and a populated projection does not grant authority.
The existing Hook chain remains the admission boundary.

The first producer set is deliberately closed: one explicit HTTP GET liveness action
or one explicit saved evidence artifact for bounded search/range/strings/JS inventory.
Negation, exclusion, completion, conditional suffixes, ambiguity, multiple inputs,
unsafe bounds, route/barrier mismatch, redirect, and artifact collision all derive zero.
WebSocket is not implemented: recognizing `ws://`/`wss://` text is not a transport.

## Implementation reviewed

- `tools/harness/capability_registry.py` keeps exact typed capability matching and
  mandatory services. `tools/context_pack.py` derives at most three candidates and
  reverse-validates every registry id, argv, run reference, effect, env, route, asset,
  budget, save path, and barrier fingerprint before rendering a marker.
- `tools/agent_instruction_bundle.py` separates live source-fresh verification,
  strict frozen artifact verification, exact-context replay, and measurement. Context
  bytes remain exact; the generated Agent file is lifecycle-mutable only on the latter
  two surfaces. Runtime attribution additionally requires the immutable launch-prompt
  hash reconstructed from the assignment row.
- `tools/artifact_view.py` performs bounded, read-only, no-follow opening and re-walks
  the entire directory chain after reading. `tools/js_inventory.py` accepts exactly one
  supported evidence artifact, scans at most 2 MiB, returns at most 64 candidates and
  64 KiB JSON, and exposes neither raw content nor an enumerable content digest.
- `.claude/settings.local.example.json` fixes host `permissions.allow=[]`; local hygiene
  reports only counts and shape problems, never permission contents. This shrinks native
  auto-approval convenience but does not replace Hook/capability authority.
- `runtime_receipts.py` joins plan-bound claims to denial/Post/transcript terminals only
  through full identity and the same Start/Stop interval. `claim.success=false` is an
  attempt reservation, not a failure. Prepared markers require one exact generated
  section, Bash tool identity, registry reverse match, action hash, context bytes, and
  launch binding. Public output is aggregate-only.
- `bench.py` activates tool-friction only for fixtures that declare it, validates the
  producer's closed shape and invariants, requires unknown=0, keeps prepared attribution
  separate, freezes fixture population, and fails closed on missing metrics, threshold
  failure, producer exception, or removed difficult fixtures.

## Backup and rollback

Before implementation, the complete working tree, `.git`, tracked/untracked/ignored
files, local settings, and existing run data were copied to:

```text
/Users/ccj/Documents/AI/Xunji-backups/20260812T005431+0800-7de2eda
```

Restore instructions are in:

```text
/Users/ccj/Documents/AI/Xunji-backups/20260812T005431+0800-7de2eda.RESTORE.md
```

The backup branch is `codex/backup-tool-exposure-20260812`. The prior ignored local
Claude permission file is present in the backup; its SHA-256 is
`a5aeffb49c03f44c7fcc73ece1368f1b926b6fa0e99f08cc75196de00f05b9c2`.
No permission rule value is reproduced in this record.

## Verification

- Python compilation passed for every changed Python owner.
- Direct instruction-bundle selftest and the final focused integration matrix passed.
- Final focused result: 15 passed, 0 failed.
- Final full result: 80 passed, 0 failed in 139.4 seconds with Python 3.14.
- `check_rules.py`, `check_templates.py`, runtime-boundary, live local hygiene,
  hermetic local-permission/publication hygiene, and `git diff --check` passed.
- The safety-critical JSON manifest, compiled fallback, trusted entrypoints, and
  selftest registry agree; `selftest_all.py` is the single project regression battery.

Named negative coverage includes marker injection/duplication, wrong tool with the same
hash, changed launch, future or after-Stop terminal, mutable Agent lifecycle status,
context/path/descriptor/symlink drift, directory replacement, artifact mutation, low-
entropy secret and its SHA-256, single/double percent-encoded path and query-name
redaction, missing-run JSON errors, permission-template drift,
redirect and save collision, target barrier mismatch, English/Chinese negation,
exclusion and conditional suffixes, conditional words inside URL queries/artifact names,
producer exception redaction, outcome/attribution unknown, malformed rates, failed
thresholds, and benchmark fixture-population deletion.

## Claude Code real-driver validation

Validation used only the isolated worktree:

```text
/private/tmp/xunji-tool-exposure-driver.H9kMiv/Xunji
```

The accepted natural-language driver session was
`b21ef597-ecaa-4b08-8ed1-a91ed3da4983` (result UUID
`fdfcd321-085d-4b2b-a156-9e99818c1d2d`). It ran without `/loop` and completed the
minimum valid plan: one offline Hunter execution lane plus its mandatory Reviewer,
followed by Root settlement. The synthetic setup and `frontier.md` were isolated test
preconditions; this test does not claim Claude created those inputs.

The Hunter received one prepared capability:

```text
read.js-inventory
python3 tools/js_inventory.py inspect runs/driverjs_20260812 evidence/app.js
action_sha256=c133210dbff54132ec5941fe1736b73571560877587e70d192d2798a1a8ccfb8
```

Its child sequence read the active pointer, assignment ledger, exact generated Agent
file and context, ran that exact command, and performed one additional ordinary local
`Read` of the saved JS. The latter is permitted built-in capability and demonstrates
that prepared guidance does not cap the model's ordinary local ability.

Runtime adjudication:

- hash chain errors: none;
- events: 64 total; AgentToolCallClaim 14, PostToolUse 42,
  PostToolUseFailure 3, PreToolUseDenied 1, SubagentStart 2, SubagentStop 2;
- Agent launches: 2; Cron/Web/target/request action: 0;
- the one denial was a Root compound Bash wrapper; Root retried clean owner commands;
  no child tool was denied;
- Hunter assignment merged, Reviewer reviewed, typed cycle ended, front remained open;
- no offline output was promoted to canonical evidence, finding, report, or closure.

The inventory output contained two bounded route candidates including
`/api/users?id=*&token=*`; it did not contain the sentinel secret, absolute path, run
name, `scanned_sha256`, or `content_sha256`. Frozen-receipt replay under the final code
returned:

```text
attempted_calls=14
outcomes.unknown=0
non_denied_terminals=14
prepared_capability_hits=2
prepared_capability_offered_calls=14
prepared_capability_hit_rate=0.142857
prepared_attribution_unknown=0
```

Both the Hunter and Reviewer contexts exposed the same single
`read.js-inventory` prepared capability, and each Agent used its exact Bash action once.
The offered denominator is claim-level: it counts every child call from assignments with
at least one valid prepared capability, not prepared entries or Bash calls. That is why
the two exact hits are measured against 14 offered child calls.

This proves exact Xunji non-denial/terminal and prepared-use attribution, not native
host permission, effect success, evidence usefulness, or token savings.

Independent hashes:

- parent transcript: `440f5126eec76a30f4ff8f8af5a968c005e41a13638b64150ea18584d9de9fb9`
- Hunter child transcript: `65681d58725d628593dac2e440f1516c18b96e981fc8fece3eb5bac5163a14b7`
- Reviewer child transcript: `2f84fc2de92b343651001e818280bc8d5ac7851999dd28a623bfdc97c514ad1b`
- runtime journal: `2ac40d3417e3a8ea8c2538fffd06eeecdcef30ec40fd8c044984bbb5a2ac2942`
- loop journal: `92450326494ee278c5a4d4a41506bfca6b37ccb0f826a640a4085086278b11bd`

The original workspace active pointer matches the backup, and a dry-run byte inventory
found zero differences under its `runs/` tree.

A preliminary `/loop` driver session `0fe5dfae-0137-4433-85f6-ef83889d9b03`
exercised the core path but created Cron `0339a73e`; it is not counted as the accepted
driver. A later isolated execute turn confirmed no such job remained and `CronList`
returned no jobs. No preliminary effect touched the original workspace.

## Independent review and disposition

External assistance was disabled, so there is no heterogeneous provider vote.

- Oversized full-diff session `1125b72c-60a3-47cc-9c4d-00701140b5f1` and capability
  session `3831d061-7086-4256-870a-ef64fe0ac920` reached output limits without a
  verdict. They are not votes.
- Offline/privacy/permission session `ffffb632-be0b-4c4e-97fa-84adda92550c` returned
  PASS with no P0-P2. Accepted P3 work aligned one workflow sentence, added hermetic
  successful/missing CLI coverage, and enforced the tracked permission example. Its
  alleged fd leak was rejected after source inspection and 1000 normal plus 1000
  exceptional reads both held the process fd count at 4.
- Tool-friction/integration session `92695bae-a257-48a9-932b-7712566b00d9` returned
  WARN with one real P2: `build_from_agent` rejected normal lifecycle mutation of the
  generated Agent file. The final split verifier keeps exact context and safe Agent
  identity/path/shape while live and strict frozen admission remain unchanged.
- Focused follow-up session `ab148be8-7894-44f1-9b56-56d39e8d6162` returned PASS and
  no unresolved P0-P2 for that repair.
- Final capability-exposure session `4bf04860-687c-47ba-8c9d-c89ca03ac7c0` returned
  PASS and no unresolved P0-P2. Its P3 observation that generic `if/when/如果/若`
  suffixes still projected was mechanically reproduced and fixed before final tests.
- Final exact-slice capability session `dee35f05-fdb1-44f3-91b2-ec7aca691bc4` and
  metrics/integration session `f18942ee-a484-4362-a95a-5efc292dbf53` returned PASS.
  The metrics review's empty-projection concern was rejected from the exact branch:
  a verified zero-entry section records the assignment with an empty action set, so its
  calls are neither offered nor attribution-unknown; only missing/invalid attribution is
  unknown.
- Final offline slice `82ee9844-3957-427a-b191-8e11b5cf6a2b` returned HOLD for one
  real P1: percent-encoded short path material was decoded before length/keyword checks
  and could render as plaintext. The fix treats raw `%` in any path segment or query-key
  source as a fixed redaction marker before decoded material can render. Named single and
  double encoding fixtures pass, the final full suite is 80/80, and fresh focused session
  `b4fe2fbb-c8a2-4731-ba8c-fa39647d19e2` returned PASS/no unresolved P0-P2.
- Final governance/integration session `e9813812-a653-4d64-8d8b-1abc854f4349`
  returned PASS with no unresolved P0-P2. Its delivery-only P3s were dispositioned by
  explicitly staging both new files, removing the unsupported heterogeneous-vote wording,
  and documenting the claim-level prepared-offered denominator above.

Accepted remaining limitations:

- WebSocket remains NO-GO until a unified guarded transport, scope/proxy/privacy,
  frame/message/byte/time budgets, recorder, fixtures, and independent review exist.
- The current benchmark defines reliable friction metrics but has not yet proved a
  long-term quality, latency, or token-cost improvement. There is no provider token
  receipt, so no token-saving number is claimed.
- `xunji_non_denied_terminal` can include a native-host permission error represented
  only in the transcript. It deliberately means no matching Xunji denial plus an exact
  terminal, not successful execution.
- The real driver is a synthetic offline capability-path test, not live-target proof.

Final disposition: **PASS with documented limitations; no unresolved P0-P2 finding.**
