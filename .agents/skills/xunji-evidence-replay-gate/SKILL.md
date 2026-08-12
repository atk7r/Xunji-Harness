---
name: xunji-evidence-replay-gate
description: Codex-side Xunji evidence replay maintenance guide. Use when Codex is writing or fixing project code, docs, tests, or review notes around `probe.py --save`, `.replay.json`, `replay.py`, `evidence_parse.py`, `check_run.py --replay-verify`, evidence maturity/certainty parsing, artifact requirements, DIVERGED replay handling, or script-output-versus-proof policy without acting as the live run Root driver.
---

# Xunji Evidence Replay Gate

Use this skill when maintaining or reviewing Xunji evidence replay behavior.
Codex may edit the project code, tests, docs, and skills in this area. Codex does
not become the live Root driver for target-facing runs.

## Authority Boundary

- Treat `runs/<target>/` Markdown and saved artifacts as canonical.
- Do not treat reviewer confidence, script stdout, or chat as proof.
- Do not weaken `.claude/hooks/` or guard behavior while changing replay docs.
- If a live run needs an action, provide a concrete recommendation for the Root
  to record and execute.

## Code And Docs To Read

- `tools/probe.py` for saving response bodies and `.replay.json` recordings.
- `tools/replay.py` for replay verdicts and scope/HTTP method behavior.
- `tools/evidence_parse.py` and `tools/check_run.py` for certainty, maturity,
  artifacts, report maturity, replay divergence, and closure gates.
- `docs/WORKFLOW.md`, `docs/WORKFLOW-reference.md`, and
  `docs/templates/run/evidence.md` for the policy text.
- `xunji-reviewops` when a review ledger or report closure is involved.

## Maintenance Rules

- Confirmed evidence needs canonical certainty, finding maturity, saved
  artifacts, and `Replicated / Control:`.
- `probe.py --save NAME --run runs/<dir>` should make the correct path easy.
- `.replay.json` is a verification aid, not an auto-verdict.
- `DIVERGED` should force re-adjudication of the affected `E-xxx`, not silent
  closure.
- Script output is not proof unless the request/response is preserved through a
  recorder, replay artifact, or saved target artifact.

## Commands

```bash
.venv/bin/python tools/probe.py --selftest
.venv/bin/python tools/replay.py --selftest
.venv/bin/python tools/check_run.py --selftest
.venv/bin/python tools/selftest_all.py --only probe,replay,check_run
```

For a run-level replay check:

```bash
.venv/bin/python tools/replay.py runs/<dir>
.venv/bin/python tools/check_run.py runs/<dir> --replay-verify
```

## Review Checklist

- Does the change preserve safe replay defaults: GET automatic, write skipped
  unless explicit, destructive never replayed?
- Are scope checks fail-closed when scope cannot be determined?
- Do warnings/errors distinguish missing artifact, missing control, divergent
  replay, and lower-maturity report claims?
- Do docs avoid implying that `check_run.py` certifies quality?
- Are tests narrow enough to catch the bug and broad enough for parser changes?
