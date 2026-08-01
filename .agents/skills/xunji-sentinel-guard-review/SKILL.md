---
name: xunji-sentinel-guard-review
description: Codex-side Xunji safety boundary maintenance and review guide. Use when Codex is writing, fixing, or reviewing project code, docs, tests, or diffs for `.claude/hooks/`, `tools/harness/guard.py`, `sentinel/`, safety rules, L1-L4 sentinel decisions, hard deny/ask/notify behavior, runtime boundary checks, or safety-critical independent review without acting as the live run Root driver.
---

# Xunji Sentinel Guard Review

Use this skill for Codex-side maintenance of the Xunji safety boundary. Codex may
write and fix these project components, but safety-critical behavior changes need
the project's independent review path.

## Boundary Model

- `.claude/hooks/safety_gate.py` is the deterministic hard boundary for
  irreversible harm classes.
- `tools/harness/guard.py` protects active tool traffic with rate/body/session
  controls.
- `sentinel/` classifies behavior and autonomy risk; observe-only behavior must
  not silently become enforcement.
- Skills and docs do not waive hook or guard requirements.

## Code To Read

- `.claude/hooks/safety_gate.py`, `run_gate.py`, `output_gate.py`,
  `safety_rules.json`.
- `tools/harness/guard.py` and `tools/harness/proxy.py` when runtime traffic is
  affected.
- `sentinel/README.md`, `sentinel/TUNING.md`, and changed `sentinel/*.py`.
- `docs/WORKFLOW-reference.md` safety-critical review section.
- `xunji-reviewops` for review ledger handling.

## Required Checks

Run narrow suites for touched layers:

```bash
python tools/check_hook.py
python .claude/hooks/safety_gate.py --selftest
python .claude/hooks/run_gate.py --selftest
python .claude/hooks/output_gate.py --selftest
python tools/harness/guard.py
python sentinel/replay.py
python sentinel/verify_layers.py
```

When feasible:

```bash
python tools/selftest_all.py
```

## Independent Review

For behavior changes under `.claude/hooks/`, `tools/harness/guard.py`, or
`sentinel/`, use the Codex-maintenance review matrix; Codex self-review is not
independent:

```bash
python tools/peer_review.py <scope> --driver codex --out review/records/<date>-<topic>.md
```

Review must check false positives, missed hard blocks, scope drift,
fail-open/fail-closed behavior, and whether the live boundary is weakened.

## Review Checklist

- Is the change behavior-changing or only text/test metadata?
- Does a hard block become soft, or soft behavior become silent allow?
- Are L1/L2/L3/L4 semantics preserved?
- Are tests proving both allowed proof actions and denied harm actions?
- Is rollback obvious if the boundary over-blocks or under-blocks?
