# Claude-primary Agent Runtime E2E — 2026-07-22

- Scope: staged Claude-primary Agent planning, launch/return, request-budget,
  review/Root settlement, material replan, VERIFY suffix, and typed cycle closure.
- Candidate: temporary commit `f4c18d6cec7d23488b47978104c39355c5162fe9`,
  tree `c2f1057355c0904e0b98fd05b1e9e3e9810e3868`.
- Primary driver: DeepSeek-backed Claude Code, effort `high`, session
  `ecbdc231-0a62-4316-bc39-8b644f8156d1`.
- Fresh closure validation: DeepSeek-backed Claude Code, effort `high`, session
  `52982078-1e29-4725-88d6-c88d0a8cdc56`, verdict `PASS`.
- Arkcli: not used.

## Real Operator Flow

The primary driver received one natural operator request for
`http://127.0.0.1:18765`, with localhost direct egress explicitly allowed. It
created `runs/127-0-0-1_20260722`, committed a six-lane serial plan, launched real
Claude Agents, recorded immutable returns, obtained exact Review dispositions,
performed Root settlements, saved target artifacts, replanned only the remaining
VERIFY suffix, and wrote a debt-free typed `cycle_end`.

The initial plan was `WP-2-1a8e86eb` / digest
`1a8e86ebd55700991a3077caf6181a8b267f6bb754b19857246d6b0b7f85e791`.
After canonical evidence changed, `workers.py commit-plan` produced
`WP-2-f7b9122b` / digest
`f7b9122bcb3e5859e6d579d0e141e9df007881049308b748c99ce43f0d2d9b75`
with exactly two lanes:

- `L-F-001-VERIFY`
- `L-F-001-VERIFY-REVIEW`

It explicitly inherited the completed OFFLINE, OFFLINE-REVIEW, TARGET, and
TARGET-REVIEW lanes. No `A-web-hunter-003` was created and no target work was
replayed.

## Runtime Evidence

- Assignments: `A-web-hunter-001=merged`, `A-review-001=reviewed`,
  `A-web-hunter-002=merged`, `A-review-002=reviewed`,
  `A-verify-001=merged`, `A-review-003=reviewed`.
- Target request claims: exactly three, ordinals `1/3`, `2/3`, `3/3`, all
  admitted for `A-web-hunter-002`; no fourth request claim.
- Target PostToolUse receipts: exactly three successful receipts.
- Saved body/replay pairs:
  - `evidence/initial-liveness.html` + `.replay.json`
  - `evidence/health-endpoint.html` + `.replay.json`
  - `evidence/options-root.html` + `.replay.json`
- Review disposition printed `VERIFIED_ARTIFACT` for every admitted artifact set.
- The final `cycle_end` binds the VERIFY plan digest and reports no pending,
  blocked, failed, or abandoned disposition.

## Denial And Recovery Observations

- Invalid lifecycle argv and the pre-plan work attempt were denied; Claude
  repaired the exact prerequisite and retried.
- A passive `sleep && workers.py status` chain was denied as
  `registered-chain-passive` with `maintenance_action=false`; the clean status
  retry remained usable.
- The OFFLINE Hunter's 25th child call was denied by
  `XUNJI_E_AGENT_TOOL_CALL_LIMIT_EXCEEDED`; it returned and the Reviewer chain
  continued.
- The first cycle-end Coda contained multiple next actions and was rejected;
  Claude reduced it to one next action and the typed cycle ended successfully.
- Canonical certainty/frontier corrections after `cycle_end` initially exposed a
  false `WORK_PLAN_INPUTS_STALE` closure failure. The checker now keeps active
  plans input-fresh while validating ended plans through the immutable
  transaction and re-derived cycle receipt.
- Replan initially hid prior-plan Reviewer admissions from lifecycle warnings.
  Review lookup now projects the assignment's immutable plan snapshot; the false
  warnings disappeared without weakening receipt validation.

## Verification

- `python3 tools/workers.py --selftest`: PASS.
- `python3 tools/work_plan.py --selftest`: PASS.
- `python3 tools/run_model.py --selftest`: PASS.
- `python3 tools/check_run.py --selftest`: PASS.
- `python3 tools/turn_contract.py --selftest`: PASS.
- `/usr/bin/python3 tools/turn_contract.py --selftest`: PASS on system Python 3.9.
- `python3 tools/check_templates.py`: PASS.
- `python3 tools/check_rules.py`: PASS.
- Actual completed run: `STRUCTURAL_PASS`; the remaining asset tested-cell
  warning is run-content coverage mapping, not an Agent/runtime closure blocker.
- Fresh Claude verdict: `PASS`; active-plan stale detection remains enforced,
  ended-plan canonical correction no longer produces a false hard failure, and
  the transaction/cycle/assignment receipts remain exact.

## UX Notes

The hard limits recovered correctly, but the default Agents still spend many
read calls on small lanes, and the target Hunter consumed all three allowed
requests for a minimal liveness task. These are efficiency observations, not
authority, privacy, receipt, or closure failures.
