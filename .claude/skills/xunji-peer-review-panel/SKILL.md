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

## Claude Driver Matrix

For Claude Code live runs and Claude-authored code/report/closure review:

- Full availability: Claude Code modifies/drives; Codex + arkcli panel review;
  Codex is the synthesis brain.
- No Codex: Claude Code modifies/drives; arkcli panel reviews; arkcli panel is
  the synthesis brain.
- No arkcli: Claude Code modifies/drives; Codex reviews; Codex is the synthesis
  brain.
- Neither Codex nor arkcli: record `NEEDS_DRIVER`/backend limitation and keep
  closure open. A fresh-context Claude same-family pass may advise the driver but
  cannot become the independent closure receipt.

Use the default Claude-driver command for run closure:

```bash
python3 tools/peer_review.py runs/<dir> --into-run
```

The default path retries transient/empty-output backend failures, then falls
through to the next independent backend in the active matrix. A Codex timeout
should therefore become arkcli panel review when arkcli is available, not a
silent manual-review shortcut.

Use bundle-only when egress is not yet accepted or the operator wants to inspect
the review material first:

```bash
python3 tools/peer_review.py runs/<dir> --bundle-only
```

## Accepting Codex-Authored Diffs

When Claude Code integrates a Codex-authored repository diff, Claude Code only
needs the acceptance contract:

- Codex self-review is not an independent review vote.
- Require a review record for high-risk code, report, closure-impacting, or
  safety-critical changes.
- Check that the record names the external reviewer(s), notes any missing
  reviewer limitation, and includes dispositions tied to tests, diffs, or
  artifacts.
- If the record is missing or stale, run or request a fresh Claude-side review
  before accepting the diff.

The Codex-side author/review matrix belongs in `AGENTS.md`, not this Claude
driver skill.

## Arkcli Panel Defaults

The default arkcli panel models are:

1. `kimi-k2.7-code`
2. `glm-5.2`

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
  content to external model providers. Use bundle-only for inspection when egress
  is not accepted; a local same-family review is advisory and does not close the
  independent-review gate.

## Maintenance Checks

After changing panel defaults, docs, or parser behavior, run:

```bash
python3 tools/peer_review.py --selftest
python3 tools/selftest_all.py --only peer_review
```

Then grep for stale claims:

```bash
rg -n "arkcli panel|kimi-k2.7-code|glm-5.2|thinking" tools review docs README.md AGENTS.md .agents/skills .claude/skills
```

If the change affects `.claude/hooks/`, `tools/harness/privacy.py`,
`tools/harness/command_shape.py`, `tools/harness/guard.py`, or `sentinel/`,
also follow `xunji-reviewops` safety-critical review requirements.
