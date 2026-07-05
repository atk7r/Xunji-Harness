---
name: xunji-sentinel-guard-review
description: Claude-driver safety boundary review for Xunji. Use when editing or reviewing `.claude/hooks/`, `tools/harness/guard.py`, `sentinel/`, safety rules, runtime boundary behavior, L1-L4 sentinel decisions, hard deny/ask/notify semantics, or safety-critical diffs that require selftests plus independent review.
---

# Xunji Sentinel Guard Review

Use this skill for safety-boundary code and review. This is not a vulnerability
playbook; it protects the run boundary.

## Overlap Routing

- Use this skill for behavior changes to hooks, guard, sentinel, safety rules, or
  L1-L4 semantics.
- Use `xunji-local-maintenance` for ordinary docs/tools/skills edits outside the
  safety boundary.
- Use `xunji-reviewops` to record and adjudicate the independent review findings.
- Use `src-safety-boundary` for live-run action limits; this skill is for
  maintaining the boundary implementation.

## Boundary Model

- `.claude/hooks/safety_gate.py` is the deterministic hard boundary for
  irreversible harm classes.
- `tools/harness/guard.py` enforces runtime request/body/rate/session safety for
  active tools.
- `sentinel/` is behavior monitoring and autonomy classification; current design
  is observe-first unless explicitly changed.
- Skills and docs do not waive hook, guard, or sentinel requirements.

## Before Editing

Read the exact touched component:

- `.claude/hooks/safety_gate.py`
- `.claude/hooks/run_gate.py`
- `.claude/hooks/output_gate.py`
- `.claude/hooks/safety_rules.json`
- `tools/harness/guard.py`
- `sentinel/README.md`
- `sentinel/TUNING.md`
- changed `sentinel/*.py`

Define whether the change alters hard deny, soft ask/notify, replay safety,
scope classification, rate/body/session boundaries, or just text/tests.

## Required Checks

Run the narrow tests for touched layers:

```bash
python tools/check_hook.py
python .claude/hooks/safety_gate.py --selftest
python .claude/hooks/run_gate.py --selftest
python .claude/hooks/output_gate.py --selftest
python tools/harness/guard.py
python sentinel/replay.py
python sentinel/verify_layers.py
```

When feasible, run the aggregate:

```bash
python tools/selftest_all.py
```

If only a subset is run, record exactly why.

## Review Gate

Any behavior change under `.claude/hooks/`, `tools/harness/guard.py`, or
`sentinel/` needs independent review per `docs/WORKFLOW-reference.md`. A reviewer
must check false positives, missed hard blocks, scope drift, over-clamping,
fail-open/fail-closed behavior, and whether the change weakens the live boundary.

Do not mark safety-critical work done only because tests pass. Tests prove known
cases; review judges the new behavior.

## Report Shape

Summarize:

- touched boundary and behavior class;
- tests run and exact failures;
- independent review status;
- remaining risk and rollback path;
- whether operator approval is needed before live use.
