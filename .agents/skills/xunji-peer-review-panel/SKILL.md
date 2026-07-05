---
name: xunji-peer-review-panel
description: Codex-side Xunji heterogeneous peer-review panel protocol. Use when Codex is the auxiliary reviewer or code-maintenance driver, when auditing `tools/peer_review.py`, choosing arkcli/Claude review backends for Codex-authored diffs, checking arkcli panel default models and thinking behavior, or recording Codex-side review findings under `review/records/`.
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
- When Codex drives repository maintenance, Codex does not count as an
  independent reviewer of its own diff. Use the Codex-driver matrix below.
- Do not use `.codex/` artifacts as proof that the live engagement boundary was
  active.

## Driver Matrix

For a Claude Code live run, Codex is normally the heterogeneous reviewer:

- Preferred full review: Codex + arkcli panel.
- No Codex: arkcli panel.
- No arkcli: Codex.
- Neither external backend: fresh-context Claude same-family fallback only
  transparently; it reduces bias but not shared blind spots.

For Codex-driven code maintenance, use:

```bash
python3 tools/peer_review.py <scope> --driver codex --out review/records/<date>-<topic>.md
```

In this mode:

- Codex is the synthesis brain but not an independent vote.
- Independent votes are arkcli panel plus Claude Code/API when available.
- If one external side is unavailable, use the other and record the limitation.
- If neither external reviewer is available, do not pretend Codex self-review is
  independent.

## Arkcli Panel Defaults

The default arkcli panel models are:

1. `kimi-k2.7-code`
2. `minimax-m3`
3. `glm-5.2`

Default arkcli panel behavior does not disable thinking. Only pass `--thinking`
when a private config explicitly sets a `thinking` field for a model.

## Common Commands

Generate the review bundle without model egress:

```bash
python3 tools/peer_review.py runs/<dir> --bundle-only
```

Review a Codex-authored maintenance diff:

```bash
python3 tools/peer_review.py <scope> --driver codex --out review/records/<date>-<topic>.md
```

Append an independent review into a Claude-run directory when acting as helper:

```bash
python3 tools/peer_review.py runs/<dir> --into-run
```

Force the arkcli panel:

```bash
python3 tools/peer_review.py runs/<dir> --backend arkcli
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
- Record Codex-authored review dispositions in `review/records/<date>-<topic>.md`
  when they affect closure, report text, or safety-critical code.
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
