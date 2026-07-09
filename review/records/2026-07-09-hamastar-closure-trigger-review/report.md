# Hamastar Closure Trigger Maintenance Review Scope

## Summary

- Status: ready for independent review
- Severity candidate: safety-critical maintenance (closure gate / hook behavior)
- Affected asset: Xunji repository lifecycle and hook tooling
- Evidence IDs: E-001, E-002, E-003, E-004
- Fingerprints captured: no new product fingerprints; framework maintenance only.

## Change Summary

This patch fixes a closure bypass exposed by `runs/hamastar_20260709/retrospective.md`: a retrospective could declare `Verdict: FINAL` while `report.md` stayed a template and generated loop state still had closure blockers. The patch makes `tools/check_run.py` the single closure-signal source for report finality, decisions CLOSING/FINAL, completion markers, and retrospective Status/Verdict fields. `.claude/hooks/run_gate.py` delegates to that same predicate.

It also turns the scheduled `/loop` cancellation lesson into an auditable gate: once `GHOST_COMPLETE` or `NORMAL_COMPLETE` is present, `check_run.py` requires a loop journal note containing `cron_cancelled=<job-id|none>`.

The local ignored hamastar retrospective was updated to withdraw unsupported FINAL and record NEEDS_REPAIR with concrete blockers. It is captured as review evidence but not force-added to git because `runs/*` is ignored engagement state.

## Expected Invariants

- No `.codex` hook runtime or parallel safety boundary is introduced.
- Retrospective drafts/templates do not trigger closure unless they have explicit `Status:` or `Verdict:` fields with final/complete values.
- Prose that merely mentions `GHOST_COMPLETE` does not trigger closure; completion markers remain canonical in `decisions.md`.
- Retrospective `Status:` / `Verdict:` fields are closure signals; `GHOST_COMPLETE` / `NORMAL_COMPLETE` in `decisions.md` are completion actions. The cron disposition hard gate applies to completion actions.
- A completion marker without a loop journal `cycle_end` / `end` event containing
  `cron_cancelled=<job-id|none>` hard-fails closure.
- `run_gate.py` and manual `check_run.py` agree on whether closure gates are active.
- Hamastar remains non-final unless the canonical run files are actually repaired.

## Verification Already Run

- `python3 tools/check_run.py --selftest` -> passed.
- `python3 .claude/hooks/run_gate.py --selftest` -> passed.
- `python3 tools/check_run.py runs/hamastar_20260709` -> passed with non-closure warnings.
- `python3 tools/check_hook.py` -> passed.
- `python3 .claude/hooks/safety_gate.py --selftest` -> passed.
- `python3 .claude/hooks/output_gate.py --selftest` -> passed.
- `python3 tools/setup_run.py --selftest` -> passed.
- `python3 tools/session_handoff.py --selftest` -> passed.
- `python3 tools/anti_drift.py --selftest` -> passed.
- `python3 tools/harness/guard.py` -> passed.
- `python3 sentinel/replay.py` -> 26/26 passed.
- `python3 sentinel/verify_layers.py` -> effective, no false positives.
- `python3 tools/check_rules.py` -> passed.
- `python3 tools/selftest_all.py --timeout 600` -> 53 passed, 0 failed.
- `git diff --check` -> passed.
- `python3 -m py_compile tools/check_run.py .claude/hooks/run_gate.py` -> passed.
- `python3 tools/peer_review.py review/records/2026-07-09-hamastar-closure-trigger-review --driver codex --backend claude ...` -> final Claude Code CLI review PASS, findings none.
- Full arkcli+Claude panel attempt was recorded in `review-panel.md`; arkcli
  failed with TLS handshake timeouts, so the no-arkcli matrix fallback used the
  fresh Claude Code CLI review.

## Review Questions

- Does `_closure_gate_active` cover the right closure signals without making retrospective prose or templates noisy?
- Does the cron disposition hard gate create a practical closure requirement without blocking normal non-completion loop iterations?
- Does `run_gate.py` remain fail-open only when `check_run` is unavailable, while otherwise matching manual check behavior?
- Are the selftests close enough to the hamastar failure mode?
- Should ignored run-file repairs remain local plus review evidence, or should any part be force-added in a separate operator-approved step?
