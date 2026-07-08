# Independent Review — anti-drift anchor hook (tools/anti_drift.py)

_backend: codex (heterogeneous) · 2026-06-20_
> Candidate vote, not verdict. Driver integrated each finding through the evidence gate.

## Change

A UserPromptSubmit hook (`tools/anti_drift.py`, wired in `.claude/settings.json`) that injects
binding rules + the active run's process-state/overdue-steps into the recency zone every turn — to
counter instruction/process drift over long context (Lost-in-the-Middle / multi-turn degradation).
Advisory only; deterministic gates (safety_gate / run_gate / check_run) remain the floor.

## Verdict: WARN → all findings resolved

- [WARN] per-prompt `evidence_entries_missing_artifact` does an uncapped `rglob` → latency risk every
  turn → FIXED: removed from the per-turn path (still enforced by check_run at closure). Measured
  latency after fix: ~0.05s.
- [WARN] codex-checkpoint-due was "any review exists" → wouldn't re-fire for later findings → FIXED:
  now also fires when `evidence.md` is newer than `review.md` (evidence changed since last review).
- [WARN] `n_conf` counted non-`E-` blocks → FIXED: restricted to `E-` confirmed entries.
- [PASS] advisory + fail-open (only prints context, never gates/denies a tool call; main() catches
  build_anchor exceptions, exits 0).
- [PASS] settings.json wiring valid + correctly under UserPromptSubmit (not PreToolUse/Stop, so it
  cannot gate execution).
- [PASS] output bounded (fixed rules + one run + small flag set; coverage text truncated).

## Validation

selftest_all 20/20 (anti_drift registered), check_rules pass, anti_drift --selftest pass, hook
runs on stdin event and emits the anchor (exit 0). A 3rd codex pass was skipped for the three minor
resolved WARNs (Verifier-Tax: calibrate review to risk; the fixes are mechanically verified).

## Note

This hook is the mechanical answer to "the operator kept having to remind me" — process/goal anchors
now surface every turn in the recency zone, derived from run files (not self-reported), with the
deterministic gates as the non-drifting floor and codex as the periodic orthogonal supervisor.
