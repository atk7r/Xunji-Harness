---
name: xunji-evidence-replay-gate
description: Claude-driver evidence replay discipline for Xunji runs. Use when saving proof artifacts, writing `evidence.md`, raising certainty, using `probe.py --save`, handling `.replay.json`, running `replay.py` or `check_run.py --replay-verify`, adjudicating DIVERGED replay, or preventing scripts and prose from being treated as evidence.
---

# Xunji Evidence Replay Gate

Use this skill when a run depends on proof artifacts or replayability. It keeps
evidence grounded in saved target responses and safe replays, not prose.

## Evidence Rule

- Treat `evidence.md` prose as a claim until it points to a saved artifact.
- Set `Maturity:` explicitly: `phenomenon`, `candidate`, or `finding`.
- Only `Maturity: finding` with canonical certainty `>= 0.8` belongs in
  `report.md` `Evidence IDs:`.
- A confirmed entry needs `Artifacts:` plus `Replicated / Control:`.
- Script output is not proof by itself. If a script performed the proof, preserve
  the request/response with recorder or re-run the proof with `probe --save`.

## Save Proof

Prefer guard-routed probe artifacts:

```bash
python tools/probe.py GET "<url>" --save <name> --run runs/<dir>
python tools/probe.py DIFF "<baseline-url>" "<mutant-url>" --save <name> --run runs/<dir>
```

This places the response and the `.replay.json` under `runs/<dir>/evidence/`.
For rendered/browser proof, save screenshots or render directories under
`evidence/` and cite that path.

Do not leave proof or scratch files in the run root at closure. Root-level proof
files are tolerated by parsers but become layout-drift warnings.

## Replay

Use replay only as a verification aid; it does not auto-decide truth:

```bash
python tools/replay.py runs/<dir>
python tools/check_run.py runs/<dir> --replay-verify
```

Replay rules:

- Automatic replay is for idempotent in-scope `GET` recordings through guard.
- Write methods are skipped unless explicitly forced; destructive methods are
  never automatically replayed.
- `IDENTICAL` supports the artifact strongly.
- `CONSISTENT` means status matches but content changed; manually confirm the
  new content is still the vulnerable response.
- `DIVERGED` means re-adjudicate: downgrade the finding, refresh evidence, or add
  a `- Replay:` explanation to the affected `E-xxx`.
- `UNREACHABLE` is inconclusive; "could not reach" is not "safe".

## Closure Gate

Before final report or `GHOST_COMPLETE`:

```bash
python tools/check_run.py runs/<dir>
python tools/check_run.py runs/<dir> --replay-verify
```

Resolve every hard error. Treat replay warnings as evidence-quality work, not
cosmetic cleanup. If a replay diverged after a final report cites that finding,
the specific `E-xxx` must carry the re-adjudication.

## Related Skills

- Use `xunji-reviewops` to resolve peer-review ledger findings.
- Use `xunji-run-lifecycle` for overall closure sequencing.
- Use `xunji-sentinel-guard-review` only when changing hooks, guard, or sentinel.
