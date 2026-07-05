---
name: xunji-peer-review-panel
description: Claude-driver Xunji heterogeneous peer-review panel protocol. Use when Claude Code is the primary live-run or integration driver and needs to run or audit `tools/peer_review.py`, choose Codex/arkcli/Claude review backends, check arkcli panel default models and thinking behavior, append independent review to a run, or record dispositions under `review.md` / `review/records/`.
---

# Xunji Peer Review Panel

This is the Claude-driver operating guide for Xunji's heterogeneous review
matrix. Claude Code is primary for live runs and integration; Codex and arkcli
are review backends that supply candidates and blind-spot pressure.

## Source Of Truth

Read these files when exact behavior matters:

- `tools/peer_review.py` for backend order, default models, CLI flags, parser
  shape, driver handling, and selftests.
- `review/independent-reviewer.md` for the human-facing review contract, data
  egress warning, and Codex proxy notes.
- The active skill tree's `xunji-reviewops/SKILL.md` for adjudication and
  closure discipline.

If docs and code disagree, treat `tools/peer_review.py` plus passing selftests as
current behavior and update the stale doc.

## Claude Driver Posture

- Claude Code remains the primary driver for target-facing work, guard/hook
  enforcement, run state, final integration, and report closure.
- Codex is a heterogeneous reviewer or delegated helper, not a replacement live
  runtime.
- Arkcli panel is an external heterogeneous reviewer set.
- Reviewer output is candidate material. Claude/Root must adjudicate it through
  evidence, tests, diffs, and recorded rationale.

## Live-Run Matrix

For Claude Code live runs and closure/reporter review:

- Preferred full review: Codex + arkcli panel.
- No Codex: arkcli panel.
- No arkcli: Codex.
- Neither external backend: fresh-context Claude same-family fallback only
  transparently; it reduces bias but not shared blind spots.

Use the default Claude-driver command for run closure:

```bash
python3 tools/peer_review.py runs/<dir> --into-run
```

Use bundle-only when egress is not yet accepted or the operator wants to inspect
the review material first:

```bash
python3 tools/peer_review.py runs/<dir> --bundle-only
```

## Delegated Codex Diffs

When Claude delegates repository edits to Codex, Claude remains the integration
driver. Do not count Codex as an independent reviewer of its own diff.

For high-risk Codex-authored code, report, or closure-impacting changes:

- Review the diff with Claude Code plus arkcli panel when available.
- Record findings and Claude's dispositions in `review/records/<date>-<topic>.md`.
- If arkcli is unavailable, record that limitation and review with tests plus a
  fresh-context Claude/available external reviewer.

## Arkcli Panel Defaults

The default arkcli panel models are:

1. `kimi-k2.7-code`
2. `minimax-m3`
3. `glm-5.2`

Default arkcli panel behavior does not disable thinking. Only pass `--thinking`
when a private config explicitly sets a `thinking` field for a model.

## Common Commands

Append an independent review into a run:

```bash
python3 tools/peer_review.py runs/<dir> --into-run
```

Force the arkcli panel:

```bash
python3 tools/peer_review.py runs/<dir> --backend arkcli
```

Resolve a PR ledger item:

```bash
python3 tools/peer_review.py runs/<dir> --resolve PR-001 --status accepted --resolution "Evidence: E-007 and replay hash confirm the issue; reopened F-003."
```

Validate the panel implementation:

```bash
python3 tools/peer_review.py --selftest
```

## Review Handling Rules

- Treat panel output as candidate review, not final truth.
- Require accepted findings to cite run artifacts, evidence IDs, hashes, or
  concrete diffs.
- Dismiss findings only with a concrete alternate explanation and evidence.
- Record dispositions in `review.md` or `review/records/<date>-<topic>.md` when
  the review affects closure, report text, or safety-critical code.
- Preserve the data-egress distinction: arkcli/Codex/API review sends bundle
  content to external model providers; use bundle-only or fresh-context local
  review when egress is not accepted.

## Maintenance Checks

After changing panel defaults, docs, or parser behavior, run:

```bash
python3 tools/peer_review.py --selftest
python3 tools/selftest_all.py --only peer_review
```

Then grep for stale claims:

```bash
rg -n "arkcli panel|kimi-k2.7-code|minimax-m3|glm-5.2|thinking" tools review docs README.md AGENTS.md .agents/skills .claude/skills
```

If the change affects `.claude/hooks/`, `tools/harness/guard.py`, or `sentinel/`,
also follow `xunji-reviewops` safety-critical review requirements.
