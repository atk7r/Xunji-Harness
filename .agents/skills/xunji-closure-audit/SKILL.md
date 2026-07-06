---
name: xunji-closure-audit
description: Codex-side Xunji closure-audit guide. Use when Codex is asked to check whether `.claude/skills`, docs, tools, templates, run lifecycle flows, evidence recording, or selftest registration are disconnected, stale, unimplemented, or not closed-loop; when auditing Claude primary-driver skill/tool wiring without acting as Root; or when turning a one-off framework audit into reusable checks.
---

# Xunji Closure Audit

Use this skill for Codex-side maintenance audits of Xunji's process wiring.
Claude Code remains the primary driver for live runs; this skill audits the repo
and may propose or implement maintenance fixes when the operator asks.

## Boundary

- Default target for Root/skill/run lifecycle behavior is `.claude/skills/` and
  shared framework files, not `.agents/skills/`.
- This skill itself is Codex-side guidance under `.agents/skills/`.
- Do not create a Codex hook/runtime boundary.
- Treat review confidence as a lead. Accepted conclusions still need concrete
  file refs, command output, or review records.

## Read First

- `AGENTS.md` for the Claude-primary / Codex-auxiliary boundary.
- `.agents/skills/xunji-local-maintenance/SKILL.md` for worktree discipline.
- `.agents/skills/xunji-peer-review-panel/SKILL.md` if you author a maintenance
  diff that needs independent review.
- The specific skill(s), docs, tools, or templates under audit.

## Fast Audit

Run the bundled deterministic scan from the repo root:

```bash
python3 .agents/skills/xunji-closure-audit/scripts/closure_audit.py
```

Hard failures from this script mean real wiring gaps until disproven:

- a documented `python tools/*.py` / `.claude/hooks/*.py` command references a
  missing file;
- a Python entry point containing `--selftest` is not registered in
  `tools/selftest_all.py`.

Then run the relevant project gates:

```bash
python3 tools/check_rules.py
python3 tools/check_templates.py
python3 tools/check_runtime_boundary.py
python3 tools/selftest_all.py --list
```

Use targeted selftests while iterating. Before claiming broad closure, prefer a
full `python3 tools/selftest_all.py` unless the change is docs-only or the
operator asked for a lightweight audit.

## Manual Audit Passes

Search for stale prose and classify it:

```bash
rg -n "TODO|FIXME|not implemented|unimplemented|stub|placeholder|fallback|not available|manual|手动|未实现|占位|兜底" \
  .claude/skills docs tools AGENTS.md CLAUDE.md
```

Most hits are legitimate doctrine, templates, or fallback policy. Treat a hit as
a gap only when prose promises a mechanical action, tool, template, review, or
evidence step that the repo cannot execute.

For path-like references, expect false positives from natural language such as
`tools/reviewers` or `docs/tools/skills edits`. Verify before fixing. Real
examples worth fixing:

- a file command in a skill does not exist;
- docs say a template is scaffolded but `setup_run.py` does not copy it;
- a tool has `--selftest` but is absent from `selftest_all.py`;
- a skill completion condition depends on a missing recorder/checker;
- a recovery path produces non-canonical `evidence.md` blocks.

## Fix Pattern

1. Preserve the Claude-primary boundary: update `.claude/skills/` for Root
   behavior; update `.agents/skills/` only for Codex-side audit guidance.
2. Prefer adding or wiring the missing local tool over documenting around it.
3. Keep evidence discipline conservative: source/research leads stay
   `phenomenon` or `candidate` until active proof passes the evidence gate.
4. Add or update `--selftest` coverage for new tools, then register it in
   `tools/selftest_all.py`.
5. Re-run the bundled scan and relevant gates.

## Review And Commit Discipline

For Codex-authored maintenance diffs that touch framework skills/tools/tests,
follow the repository review matrix:

```bash
python3 .claude/hooks/pre-commit --fingerprint
python3 tools/peer_review.py <review-scope> --driver codex --out review/records/<date>-<topic>.md
```

Record `diff_fingerprint` and `reviewed_diff` in the disposition before commit.
If backends are partial, record the limitation and supplement with the best
available independent review. Never count Codex self-review as independent.

## Report Back

Include:

- hard gaps found and fixed;
- scans/tests run, with pass/fail counts;
- review status and limitations;
- residual risks that are content/backlog rather than wiring bugs.
