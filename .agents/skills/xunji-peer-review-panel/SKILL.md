---
name: xunji-peer-review-panel
description: Codex-side Xunji heterogeneous review and external/third-party assistance protocol. Use when Codex is the auxiliary reviewer or code-maintenance driver, when auditing `tools/peer_review.py`, choosing external-assistance or Claude review backends for Codex-authored diffs, checking the current arkcli provider adapter, or recording Codex-side review findings under `review/records/`.
---

# Xunji Peer Review Panel

This is the Codex-side operating guide for Xunji's heterogeneous review matrix.
Codex is auxiliary in Xunji live engagements, but it may be asked to review,
advise, or drive repository maintenance. Keep those modes separate.

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

## Codex Posture

- Do not treat Codex as the live engagement driver. Claude Code remains primary
  for target-facing runs, guard/hook enforcement, and final integration.
- When Codex reviews a Claude-driven run, act as an external reviewer: produce
  candidates, contradictions, and missing-evidence calls. Claude/Root still
  decides through the run evidence gate.
- When Codex authors repository maintenance, Codex does not count as an
  independent reviewer of its own diff. Use the Codex-authored matrix below.
- Do not use `.codex/` artifacts as proof that the live engagement boundary was
  active.

## Driver Matrix

For Claude Code-driven live runs or Claude-authored code/report/closure changes:

- Full availability: Claude Code modifies/drives; Codex + external/third-party assistance review;
  Codex is the synthesis brain.
- No Codex: Claude Code modifies/drives; external/third-party assistance reviews;
  Claude Code remains the synthesis brain.
- No external assistance: Claude Code modifies/drives; Codex reviews; Codex is the synthesis
  brain.
- Neither Codex nor external assistance: fresh-context Claude same-family fallback only
  transparently; it reduces bias but not shared blind spots.

For Codex-authored code maintenance, use:

```bash
.venv/bin/python tools/peer_review.py <scope> --driver codex --out review/records/<date>-<topic>.md
```

In this mode:

- Codex authors the change and remains the final synthesis brain.
- Codex does not count as an independent reviewer of its own diff.
- Full availability: external/third-party assistance plus Claude Code CLI review.
- No external assistance: Claude Code CLI or fresh-context Claude Code review is required.
- No Claude Code but external assistance available: use the external module and record the missing
  Claude limitation.
- If neither external reviewer is available, do not pretend Codex self-review is
  independent.

## External Assistance Providers

Provider definitions belong to the trusted registry in `tools/peer_review.py` or
`review/peer_review.json`; local `config.ini [external_assistance]` only enables
an ordered list of registered names. It cannot supply commands. Each external
provider must declare `role = external-assistance` and use an allowlisted adapter
kind; core fallbacks declare `role = core-reviewer`, and unclassified backends
never execute. Missing/false/invalid config, unknown providers, role mismatches, and
unknown kinds fail closed with diagnostics; `--backend` does not bypass the gate.

The current selected provider adapter is `arkcli`; it is a backend/CLI
compatibility name, not a synthesis or authority role. Its default models are:

1. `kimi-k2.7-code`
2. `glm-5.2`

Default arkcli adapter behavior does not disable thinking. Only pass `--thinking`
when a private config explicitly sets a `thinking` field for a model.
For Codex-authored work with multiple enabled providers, the default two slots
remain the first external provider plus Claude Code. Additional providers are
fallbacks or explicit extra slots; they do not displace the Claude acceptance vote.

## Common Commands

Generate the review bundle without model egress:

```bash
.venv/bin/python tools/peer_review.py runs/<dir> --bundle-only
```

Review a Codex-authored maintenance diff:

```bash
.venv/bin/python tools/peer_review.py <scope> --driver codex --out review/records/<date>-<topic>.md
```

Append an independent review into a Claude-run directory when acting as helper:

```bash
.venv/bin/python tools/peer_review.py runs/<dir> --into-run
```

Inspect provider activation and adapter availability:

```bash
.venv/bin/python tools/peer_review.py --list-backends
```

Force the current arkcli provider adapter after local activation:

```bash
.venv/bin/python tools/peer_review.py runs/<dir> --backend arkcli
```

Validate the panel implementation:

```bash
.venv/bin/python tools/peer_review.py --selftest
```

## Review Handling Rules

- Treat panel output as candidate review, not final truth.
- Require accepted findings to cite run artifacts, evidence IDs, hashes, or
  concrete diffs.
- Dismiss findings only with a concrete alternate explanation and evidence.
- Record Codex-authored review dispositions in `review/records/<date>-<topic>.md`
  when they affect closure, report text, or safety-critical code.
- Preserve the data-egress distinction: external providers/Codex/API review send bundle
  content to external model providers; use bundle-only or fresh-context local
  review when egress is not accepted.

## Maintenance Checks

After changing panel defaults, docs, or parser behavior, run:

```bash
.venv/bin/python tools/peer_review.py --selftest
.venv/bin/python tools/selftest_all.py --only peer_review
```

Then grep for stale claims:

```bash
rg -n "external/third-party|arkcli|kimi-k2.7-code|glm-5.2|thinking" tools review docs README.md AGENTS.md .agents/skills .claude/skills
```

If the change affects `.claude/hooks/`, `tools/harness/privacy.py`,
`tools/harness/command_shape.py`, `tools/harness/guard.py`, or `sentinel/`,
also follow `xunji-reviewops` safety-critical review requirements.
