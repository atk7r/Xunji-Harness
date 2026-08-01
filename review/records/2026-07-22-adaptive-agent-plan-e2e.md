# Adaptive Agent Plan Claude Primary-Driver E2E

- Date: 2026-07-22
- Candidate worktree: isolated temporary worktree at base `fc0e2e4`
- Driver: Claude Code 2.1.201 / DeepSeek `deepseek-v4-pro[1m]`
- Session: `ec6aa655-48cc-4bfc-9371-e5487d2649b7`
- Run: `adaptive_plan_final_e2e_20260722`
- Claude return code: 0
- Stream SHA-256: `cdbe31dbacbfaa8c02ea5daec612c8a53617e22e45db0c1ad500a2e5e6a2c8a8`
- Transcript SHA-256: `e08a13d3f55dec2cb48b16c50719e01356a0ed5fe624a0ab02a0021ff9985c86`
- Verdict: PASS for the adaptive planning and Agent lifecycle path

## Natural-Language Contract

The representative operator prompt requested two independent local readers under
the same semantic `F-001`, no fake subfronts, no target/model egress, one
digest-bound Reviewer per result, Root settlement, and a typed cycle end. It used
the ordinary phrase `不访问任何目标` rather than an operator DSL.

The resulting `state/turn_contract.json` was `EXECUTE` with
`target_egress_denied=true` and `web_tools_denied=false`. The generated proposal
seed explicitly omitted TARGET and target-dependent verification. This confirms
that the harness compiled operator intent into a bounded effect contract without
turning natural language into a fixed strategy grammar.

## Independently Adjudicated Receipts

Root reshaped the non-authorizing seed and committed proposal SHA-256
`d8922b0a77c90e5c34101f09eb8898bea534218ffbd49e3eb6457de7bc43612e`
through `commit-proposal`. The authoritative plan was
`WP-1-5d2bb9c8`, digest
`5d2bb9c8dc0ee003bc2f2f2393ca59e8e10dc346376b9eadcc8158f364fda5fc`,
mode `PARALLEL_AGENTS`, with exactly four lanes:

- `L-F-001-LOCAL1` and `L-F-001-LOCAL2`: dependency-free `local_read`
  Hunter lanes, both naming `F-001` and `fixture.example`.
- `L-F-001-LOCAL1-REVIEW` and `L-F-001-LOCAL2-REVIEW`: `local_verify`
  Reviewer lanes, each depending on exactly one Hunter lane.

Runtime receipts contain four `SubagentStart` and four `SubagentStop` events.
Both Hunter starts precede the Reviewer starts. The terminal assignment ledger
records Hunters `merged` and Reviewers `reviewed`; Reviewer rows bind the exact
Hunter result digests, and Root dispositions bind review receipt hashes
`2e317869...778c` and `617c6d21...5bea`.

The runtime receipt ledger contains zero rows with `target_action=true` or
`capability_effect=target`. Request and model-egress budgets were zero. The final
append-only journal has one `cycle_end` containing all four terminal assignments,
both review receipt hashes, and a single explicit next action while `F-001`
remains open.

## Recoverable Denials And Limits

The real driver first supplied insufficient merge capacity, omitted required
evidence tags in two Root settlement notes, and used two invalid cycle-end next
actions. Each attempt was denied or failed, was not treated as a result, and was
repaired by retrying the same typed action. No target effect occurred during the
retries.

The run is a deliberately abbreviated offline lifecycle fixture, not a closable
engagement. Full `check_run.py` therefore reports missing canonical report and
coverage markers; this is not used as closure evidence. The acceptance evidence
for this test is the exact turn/plan/assignment/runtime/journal state chain and
the absence of forbidden effects.
