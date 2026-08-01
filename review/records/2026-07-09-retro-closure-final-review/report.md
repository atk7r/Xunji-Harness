# Retrospective Closure Fix Review Scope

## Review Object

This review covers the active code/documentation behavior diff saved at
`evidence/active-diff.txt`. It is generated from the staged index while excluding
`review/records/**`, so historical audit artifacts do not obscure the active
changes. The full commit still includes the review records themselves. The diff
repairs framework behavior and documentation around the issues recorded in
`runs/scshr_20260708/retrospective.md`.

## Main Change Groups

- Claude primary-driver guidance and hook block messages now require same-cycle
  handling in the displayed instruction when local hooks or `check_run.py` block
  closure. The hard enforcement remains the existing stop/check gates; the text
  change makes the required action explicit instead of allowing a future TODO.
- `run_gate.py` tightens Agent Board enforcement for many independent open fronts
  and makes closure-block messages demand same-turn fix plus rerun.
- `check_run.py`, `classify_hosts.py`, and setup guidance distinguish
  non-actionable `AUTH_GATE` / `STUB_PAGE` coverage noise from actionable
  independent app candidates, without allowing prose waivers to close coverage.
  Non-actionable-only assets now carry `verdict_required: true` and are printed
  under `VERDICT REQUIRED`, so they are not silently dropped from driver review.
- `coverage_matrix.py` supports structured coverage waivers and does not treat
  ad hoc prose as tested coverage.
- `probe.py` adds structured JSON body/value inputs so hostile or awkward form
  values do not require shell quoting or lossy string parsing.
- `loop_state.py`, `run_controller.py`, `loop_bootstrap.py`, statusline, and
  `/loop` template handling now distinguish closure-candidate state from actual
  loop completion. A completion marker is required before auto-stop behavior.
- `setup_run.py` / statusline docs record the active-run pointer behavior from
  earlier review rounds; the pointer remains display state, not evidence.
- `knowledge/soarcloud-ais-hr.md` records the current ZUSO / NVD 2025 AIS HR CVE
  cluster and DXR.axd 304 interpretation as public grounding, without embedding
  exploit payloads.
- `peer_review.py` and review docs preserve the Codex-authored maintenance matrix
  and backend limitation recording.
- The full commit also includes audit records from earlier Codex-authored review
  rounds. Those records are evidence trail additions, not extra framework
  behavior changes.

## Expected Invariants

- Codex remains auxiliary. No `.codex` hook runtime or parallel safety boundary is
  introduced.
- Claude Code primary-driver behavior defaults to `.claude/skills`, `CLAUDE.md`,
  shared docs, and `tools/`; `.agents/skills` is only Codex auxiliary behavior.
- Safety-critical hook behavior is not weakened: hard closure blocks remain hard,
  safety gate L4 blocks remain blocks, and same-turn guidance cannot bypass gates.
- `AUTH_GATE` and `STUB_PAGE` reduce anti-lump noise only. They do not create a
  closure waiver, do not mark a host tested, and do not skip required verdicts.
- `/loop` cannot auto-stop merely because `check_run.py` passes. It requires an
  explicit completion marker such as `GHOST_COMPLETE` / `NORMAL_COMPLETE`.
- `runs/scshr_20260708` remains a live-run source of truth. Codex should not mark
  it complete or write `GHOST_COMPLETE`; this framework change only makes the
  remaining state explicit.
- Review outputs are candidate findings. Codex must adjudicate them through tests,
  changed code, and recorded rationale before committing.

## Verification Already Run

- `python3 tools/selftest_all.py --timeout 600` -> 53 passed, 0 failed.
- `python3 tools/check_run.py runs/scshr_20260708` -> passed with non-blocking anti-lump warning.
- `python3 tools/loop_state.py runs/scshr_20260708 --write` -> 0 closure blockers; loop complete is false because no completion marker exists.
- `python3 tools/run_controller.py runs/scshr_20260708 --shadow` -> `NEEDS_PIVOT`, `can_stop=false`, 0 stop blockers.
- `python3 tools/check_hook.py` -> passed.
- `python3 .claude/hooks/safety_gate.py --selftest` -> passed.
- `python3 .claude/hooks/run_gate.py --selftest` -> passed.
- `python3 .claude/hooks/output_gate.py --selftest` -> passed.
- `python3 tools/harness/guard.py` -> passed.
- `python3 sentinel/replay.py` -> 26/26 passed.
- `python3 sentinel/verify_layers.py` -> effective, no false positives.
- `python3 tools/check_rules.py` -> passed.
- `git diff --cached --check` -> passed.

## Review Questions

- Does the staged diff actually address all retrospective failure classes without
  converting documentation wishes into unenforced behavior?
- Are the anti-lump suppressions too broad, especially for default pages or HTTP
  403/401 responses that may still hide important routes?
- Can `/loop` completion now get stuck or fail to stop after a real completion
  marker, or can it stop without one?
- Did the hook changes preserve fail-closed closure behavior and avoid weakening
  safety-boundary semantics?
- Are test additions close enough to the changed behavior to prevent recurrence?
