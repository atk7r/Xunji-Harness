---
name: poc-package
description: Procedure for turning an authored PoC/exploit into a clean, handoff-ready artifact — pick its xday/normal home, build hardened cross-platform binaries (garble), scrub real-target instances before any handoff or publish, verify source AND binaries, then hand off (author-and-handoff). Invoke when packaging/delivering/committing a PoC. Procedure and tooling only — no attack methodology, no target selection, no payload guidance.
---

# PoC Packaging & Handoff

A **capability/procedure** skill, not a playbook. It does not decide *what* to
attack or *how* to exploit — that is the driver's free method. It encodes the
recurring, error-prone steps of taking an already-authored PoC and packaging it
so it is clean, reproducible, and safe to hand off or commit. The one discipline
it exists to enforce: **scrub real-target instances before anything leaves
local.** That is findings hygiene (the publishing axis), independent of the
weapon itself — authoring the weapon is free and uncapped.

## When to invoke

- You have authored a working PoC (`poc.py` / `poc.go` / binary) and are about to
  **hand it to the operator, commit it, or send it to a disclosure platform**.
- You are about to `git add` anything under `poc_library/`.
- You built or rebuilt a PoC binary and need the obfuscation + scrub verified.

## Where it lives (decide first)

Per `poc_library/README.md`:

- `poc_library/xday/<id>/` — self-discovered, **undisclosed** vuln (vendor unpatched,
  no public PoC). **Content stays local**; the repo keeps only the `xday/` folder
  scaffolding (`.gitkeep`). Never push xday source/binaries (see
  `repo-publishing-policy`).
- `poc_library/normal/<id>/` — already-disclosed N-day (public CVE/CNVD + public PoC
  exists). May ship with the repo.

Entry layout: `<id>/` holds `README.md` (metadata table + principle + usage), the
`poc.py`/`poc.go`/binaries, and links to `knowledge/<id>.md` + `runs/<...>/`.

## The pipeline

```text
author (free, full impact)
  -> harden  (build + obfuscate cross-platform binaries)
  -> SCRUB   (remove every real-target instance)        <- the gate
  -> verify  (grep source AND binaries; nothing residual)
  -> hand off / commit / submit  (per home + publishing policy)
```

### 1. Harden (build)

- Full-featured driver in Python source (`poc.py`) — batch / visible / read-only
  probe flags as the case needs.
- Cross-platform handoff binaries from the Go source with **garble**:
  `garble -literals build` → `poc_win64.exe`, `poc_linux64`. Goal: `strings` on the
  binary leaks nothing (no endpoints, no logic, no target). Single-file, zero-dep,
  Chromium auto-fetched at first run if the PoC drives a browser.

### 2. Scrub — real-target instances (the reason this skill exists)

Before any handoff/commit/submit, replace every concrete engagement artifact with
a placeholder. This is what the OURS eHR packaging missed and had to fix:

| Leak class | Example found | Replace with |
|------------|---------------|--------------|
| Example target in usage/comments | `--target http://shop.example.com` | `--target http://<target>` |
| Hardcoded host/IP in code | a baked-in `https://real.host/...` | arg-driven / `<target>` |
| Run/registry tags | `UploadRegistry().register("acme_20250131", …)` | a generic tag, e.g. `"<id>-upload"` |
| Reproduction-ledger paths | `runs/acme_20250131/` | `runs/<target>_<date>/` |
| Instance lists in README | "11 instances：Xi'an…、Shenzhen…" | drop or genericize |

Keep the weapon fully functional — every scrub is to a placeholder/arg, never a
removal of capability. The vuln *class* and the grounding `knowledge/<id>.md`
(recognition only) may stay; the **specific live targets** must not travel.

### 3. Verify (do not skip)

Grep both the **text** and the **binaries** for any residual real-target token —
the org slug, domain root, and IPs from the engagement:

```bash
# text sources
grep -rniE "<org-slug>|<host>|\.edu\.cn|<your-target-tokens>" poc_library/<home>/<id>/ \
  --include=*.go --include=*.py --include=*.md | grep -viE "<target>|<date>|example"

# binaries (garble should leave nothing; confirm the domain root is absent)
grep -aoiE "<org-slug>|<domain-root>|\.edu\.cn" poc_library/<home>/<id>/poc_* | sort -u
```

Empty = clean. A stray mixed-case fragment (garble noise) is fine **only** if the
real domain root / org slug is provably absent.

## Handoff / publish rules

- **author-and-handoff**: deliver complete, runnable, full-impact assessment code
  to the operator, who runs it. Do not weaken legitimate exploit methods; the
  `safety-boundary` harm-as-purpose floor remains excluded. What the driver
  *auto-runs* against the live target stays proof-level (prove-and-stop); hard-effect
  classes (database dump / DoS / destruction) are never auto-run regardless of handoff.
- **xday → operator/local only**: hand off out of band; do not commit content
  (repo keeps the folder only). If history already carries it, a `git filter-repo`
  purge + force-push is required (see `repo-publishing-policy`).
- **External disclosure platform (CNVD/EDUSRC/…)**: ship the **obfuscated binary
  only, no source**; desensitize the written writeup per the run's submission
  draft. `src-rules` tightens this further when active.
- **normal (disclosed N-day)**: source + binary may ship with the repo after scrub.

## Boundary

This skill is procedure; the limits are still `safety-boundary` (effect, not
method) and the `.claude/hooks/` gate. Packaging never weakens them, and the
scrub step is hygiene, not a safety control — describe what the PoC does, never
annotate it with self-labeling restraint fields.
