# Review Notes

## Driver Self-Assessment

- The change is intentionally narrow: profile parsing, context injection, new assignment scaffold fields, setup scaffold, template instructions, and workflow reference.
- Main risk: profile JSON could be mistaken for evidence or for a safety override. Mitigation is explicit wording in context packs, agent templates, workflow reference, and scaffold.
- Main compatibility risk: old agent files could fail or become noisy. Mitigation is marker-gated RDT checks and an OPPO run smoke test.

## Verification Already Run

- `python3 tools/context_pack.py --selftest`
- `python3 tools/workers.py --selftest`
- `python3 tools/setup_run.py --selftest`
- `python3 -m py_compile tools/context_pack.py tools/workers.py tools/setup_run.py`
- `python3 tools/selftest_all.py --only context_pack,workers,setup_run,check_templates`
- `python3 tools/saturation.py --selftest`
- `python3 tools/bench.py score-all bench --json-out /tmp/xunji-bench-agent-board.json`
- `python3 tools/check_rules.py`
- `python3 tools/workers.py agent-check runs/oppo_20260707_20260707`
- `python3 tools/check_run.py runs/oppo_20260707_20260707`
- `git diff --check`

## Independent Review Status

- `tools/peer_review.py ... --driver codex`: returned `NEEDS_DRIVER` because Claude API was unavailable and arkcli panel was partial, but produced useful WARN findings.
- Direct `claude -p` fresh-context review was run with a read-only/no-write prompt and saved to `review/records/2026-07-07-personalized-rdt-subagents-claude-review.md`.
- Driver disposition is recorded in `review/records/2026-07-07-personalized-rdt-subagents-disposition.md`.

## Review Questions

- Does `state/operator_profile.json` fit the state/cache conventions, or should it move to a different run path?
- Is the marker-gated `agent-check` strict enough for new personalized-RDT files without spamming old runs?
- Are the template instructions clear that personalization is preference only, not evidence or safety authority?
