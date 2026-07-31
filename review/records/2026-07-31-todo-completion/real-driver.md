# Claude Code Real-Driver Adjudication

- Candidate source: uncommitted diff over
  `28929965d81eac66ffbc58b2c20b37ac69f5a7c2`, copied to a detached isolated
  worktree before the run.
- Driver: Claude Code 2.1.201, configured DeepSeek backend.
- Session: `150e22e1-afea-474a-822e-a8dab97dfccf`.
- Prompt boundary: natural-language offline S1 lifecycle task; no exact
  implementation commands supplied.
- Terminal result: success after 937286 ms and 115 turns.

## Independent receipt adjudication

| Check | Result |
|---|---|
| setup and activation | committed isolated run |
| committed macro-stage | `S1` |
| committed lane shape | `local_read Hunter -> local_verify Reviewer` |
| delegation mode | `SERIAL_AGENT` |
| authentic Agent lifecycle | 2 `SubagentStart`, 2 matching `SubagentStop` |
| final assignment state | Hunter `merged`, Reviewer `reviewed`, active/debt 0 |
| typed journal | `cycle_start -> stage_plan -> delegation_committed -> Hunter start/end -> Reviewer start/end -> cycle_end -> Root phase_end` |
| structural check | `STRUCTURAL_PASS` (explicitly not completion proof) |
| target actions | 0 |
| WebFetch/WebSearch | 0 |
| Cron tools | 0 |
| Hook denials | 3; corrected exact shapes were retried, not narrated as results |
| findings/closure | none; the front remains open and coverage/saturation blockers remain |

The driver first proposed insufficient merge capacity and a Root note without
the required anchors. Both were rejected by the real gates; it repaired the
prerequisite and retried the same action. This is expected fail-closed recovery.
The cycle ended exactly once. It did not schedule or re-enter another cycle.

The synthetic relative filename contained a dot and the tested candidate
normalized it as a bare host rather than reading the existing Markdown file.
That did not cause network traffic or invalidate the stage/Agent receipts, but
it exposed a real setup-routing ambiguity. The delivery now makes an existing
local path outrank the bare-host convenience grammar in `auto` mode; explicit
HTTP(S)/`--type url` remains URL authority. A focused relative-filename fixture
passes in `setup_source.py --selftest`.

## Frozen hashes

| Artifact | SHA-256 |
|---|---|
| terminal typescript | `2466de4e1150b80d08fe1df77617177154c86bf4feecfef471697674a27d4015` |
| Claude transcript JSONL | `6f8dc6bc00d3c09e9c90e6b0e95abf614f9459f72c9d437561872684011c8fff` |
| runtime receipt journal | `8b4e93d6c11b33e69525cf59f90fb5f0b03f35c64bbe0a2a238613b66fc71290` |
| loop journal | `6c8785fee026b491169376b4157992091ff7ba1c47ea8bf53f95737d0dd1a11e` |
| committed work plan | `0e6a59d84d9fe58e131707e3e1c5956542894719a6c8039d069061e1095e8350` |
| assignments projection | `761eec7e6de6a85785cd3ad225dec6c0dbe554fc5d2184bcad2945b295928514` |

Raw artifacts remain outside the operator worktree under the isolated validation
directory and Claude session store; no synthetic run or active pointer is copied
into the repository patch. `real-driver-evidence.json` preserves a minimal
field-for-field projection of the raw plan/assignment/receipt/journal/setup state,
including raw file hashes and receipt-chain heads, so the maintenance reviewer can
adjudicate the claimed counts without receiving an unrelated live run tree.

## Relative Markdown follow-up

The first narrow follow-up exposed a second defect: the natural operator wording
was classified as maintenance because its affirmative lifecycle clause started
with “use the auto route” and the later “do not modify framework source” clause
matched maintenance words. The isolated session
`38c5ccb9-383b-426d-892b-3247e8ea9268` was manually stopped after its registered
bootstrap command was denied; it created no run and is not counted as a pass.

The final candidate aligns both authority and effect identity:

- `setup_source.py` gives an existing local path precedence over bare-host
  convenience in `auto` mode.
- `turn_contract.py` recognizes the natural “use ... to create a run” lifecycle
  clause, compiles the existing relative source to the same absolute identity
  used by effect projection, and still requires Claude's exact argv candidate
  before authority promotion.

Claude Code session `0c740375-5ca2-41b8-8197-d245c10fc1cf` then completed the
same setup-only task in 79982 ms / 16 turns. Independent receipt adjudication:

| Check | Result |
|---|---|
| source kind | `markdown` |
| frozen snapshot | `sources/original/source.md` |
| manifest/source SHA-256 | `bd903053a64181e200f1d7f848be1375c43a2a636aac2e5067907c5d83f4cbec` |
| snapshot SHA-256 | exact match |
| setup transaction | `committed` |
| normalized target | `https://example.test/` |
| target/Web/Cron/Agent | 0 / 0 / 0 / 0 |

Follow-up hashes:

| Artifact | SHA-256 |
|---|---|
| terminal typescript | `9d21a8c40062805d032fc1b1eb565d45e9fe3702eeaccb8f7ffaf385cdec251a` |
| Claude transcript JSONL | `9a32ae83787d56ed70236e97388101dbd9fb6028652220bd16c6818b88463120` |
| runtime receipt journal | `0c0d1bc4216a4580094374323b1c7351e92a9cf7df2f04a0f45a94ffb6f37a9c` |
| setup source manifest | `8f1cdf2cf7595dd0f86ea99945c13ad7c804061d0287d5285c86e1944353eaa2` |
| setup transaction | `85c5789e00f9cb0e85c58d24e61f4cd1a1250232b0153edd93698c0a421fdc94` |
