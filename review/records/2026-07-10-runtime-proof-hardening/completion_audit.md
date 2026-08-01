# Completion Audit

Date: 2026-07-11
Scope: maximum mechanical resistance to lazy/non-compliant Claude Code driver behavior

## Requirements And Evidence

| Requirement | Current-state evidence | Verdict |
|---|---|---|
| Per-prompt EXECUTE / EXPLAIN_ONLY / PAUSED_BY_OPERATOR modes | `tools/turn_contract.py`; 57-suite regression; real `live_claude_smoke` | Proven |
| Internal task notifications cannot replace operator authority | byte-stable contract selftest plus `live_fanout_flow.summary.json: operator_contract_preserved=true` | Proven |
| Four diverse active fronts force real Agent fan-out before Root target work | strict PreTool control-script allow-list, transcript-backed Agent receipts, real two-Agent flow | Proven |
| Agent return is not enough; every assignment needs canonical merge/block/fail disposition | `runtime_receipts.agent_disposition`; denied-before-disposition and released-after-disposition live flow | Proven |
| Pause preserves fronts and only performs current-run Cron quiescence | real wrong-ID denial, exact current-run deletion, final CronList quiescence | Proven |
| Model cannot write runtime receipts/turn state or unapproved long-term memory | Bash/Write/Edit live denials; memory-read control remains allowed | Proven |
| A denied target action cannot be narrated as measured output | action hash includes all unknown semantic fields; only a later successful same action resolves; deliberate 200/nginx/TLS/12ms fabrication was Stop-blocked | Proven |
| Coda is required only for EXECUTE and must name one concrete current action | output gate selftests and final Agent-to-Stop live flow | Proven |
| Completion cannot be forged with prose/manual review | content-addressed review receipt, exact foreground command, receipt+bundle output markers, evidence hash, PR ledger, structured completion Agent checks | Proven |
| Status/front consumers share canonical active-front semantics | `run_model.py` plus consumer diffs and registered selftests | Proven |
| Claude-facing rules no longer teach historical shortcuts | historical failure map; full docs/skills inventory; zero mapped stale-reference matches | Proven |
| Arkcli default models are limited to Kimi-K2.7-Code and GLM-5.2 | `tools/peer_review.py` default config + 75-check selftest + Claude/Codex skill/docs diffs | Proven |
| Current live run is not falsely closed by maintenance work | statusline: Paused, interrupted, 8 pending entries, 3 blockers; `check_run` says structural pass only | Proven |

## Verification Snapshot

- Full repository regression: 57 passed, 0 failed.
- Real Claude programs: smoke 8/8; fan-out/disposition/retry PASS; WebFetch/Write/Edit 3/3; pause/Cron PASS.
- Review bundles: turn, receipts, closure, docs, and live all have no truncation, no machine findings, and no bundle warnings.
- Static gates: closure audit, rule check, template check, runtime-boundary check, Python compilation, and `git diff --check` passed.
- Generated diffs: 20/20 passed reverse `git apply --check --unidiff-zero`.

## Independent Review Record

- Fresh Claude and arkcli reviews discovered and drove fixes for action-hash semantics, review-receipt provenance, internal task-notification overwrite, stale Coda advice, control-script basename spoofing, mutating read-only shell forms, stale documentation, premature review-front closure, and bundle truncation.
- Final arkcli operation is limited to Kimi-K2.7-Code and GLM-5.2. Backend timeouts/JSON parse failures remain recorded as limitations and are never counted as PASS votes.

## Residual Boundary

- Same-user direct filesystem replacement, symlink/settings substitution outside Claude tools, and OS-level attestation are outside the repository Hook threat model.
- Real lifecycle tests intentionally use `--dangerously-skip-permissions`, matching the operator launch mode; they do not test Claude's separate native permission UI.
- The tests cover representative mode/tool interactions rather than every future Claude Code tool schema. Unknown action fields fail conservatively by participating in the action hash.
