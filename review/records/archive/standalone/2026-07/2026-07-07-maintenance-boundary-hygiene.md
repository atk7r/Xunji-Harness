# Maintenance Review — Boundary And Hygiene

- Date: 2026-07-07
- Author: Codex
- Scope: Codex-authored repository maintenance diff before commit.
- Review target: publication hygiene, Codex runtime boundary cleanup, guarded network helper changes, knowledge matcher checks, and selftest/doc drift.
- Verdict: WARN
- diff_fingerprint: 280e6911eda6dca7
- reviewed_diff: 280e6911eda6dca7
- Temporary review scope: `/tmp/xunji-maintenance-review-20260707`

## Review Inputs

- Frozen bundle hash: `46ab637272102e287fd0391b0652b81129bd5dd5`
- Evidence index hash: `1ef4a27b48d42ca86c8b58c850ce270c5efec6e4`
- Staged state after review hardening: `0` unstaged files, `221` staged paths (`5 A`, `14 M`, `202 D`).
- External review egress: arkcli direct review against the temporary bundle.

## Backend Attempts

- `peer_review.py . --driver codex`: invalid attempt. Repository root is not a run-shaped scope, so the bundle was empty. The resulting blocker is accepted as a tool-use failure, not as a finding against the maintenance diff.
- `peer_review.py /tmp/xunji-maintenance-review-20260707 --driver codex --panel-backends arkcli,claude`: produced a valid bundle, but arkcli model outputs did not satisfy the parser's JSON/Markdown shape and Claude fallback had no API key. This is recorded as a limitation.
- Direct arkcli reviews of the same frozen bundle completed with `glm-5.2`, `minimax-m3`, and `kimi-k2.7-code`. No reviewer reported a BLOCKER. All reported WARN items are disposed below.
- Missing-Claude limitation: accepted. No Claude Code/API independent vote was available in this environment; per the Codex-authored maintenance matrix, arkcli review plus this recorded limitation is the available path.

## Findings And Disposition

| ID | Reviewer Finding | Disposition |
|---|---|---|
| R1 | `review/review_bundle.json` was a generated artifact at risk of being committed. | **Accepted and fixed.** Added `review/review_bundle.json` to `.gitignore` and to `tools/check_local_hygiene.py` forbidden tracked paths. `tools/check_local_hygiene.py --selftest` now rejects it. |
| R2 | `tools/harness/proxy.py` is load-bearing for guard/proxy behavior but outside the narrow `.claude/hooks` / `tools/harness/guard.py` / `sentinel` safety-critical diff gate. | **Accepted as a recorded limitation, not a blocker.** The staged diff has no changes under the narrow safety-critical paths. `proxy.py` was reviewed through arkcli, compiled, and passed `tools/harness/proxy.py --selftest`; full `selftest_all.py` passed. |
| R3 | Source diff visibility was weak in the first bundle because `.patch` artifacts were hashed but not excerpted. | **Accepted and fixed for review.** The temporary scope now includes `.txt` copies of the staged target diff and guarded-network-tools diff so reviewers can inspect excerpts. |
| R4 | `cdn_bypass.alternate_ports` now returns candidate-only output, which could confuse operators if undocumented. | **Dismissed as already handled.** `tools/cdn_bypass.py` labels the function "candidate", sets `tested: False`, adds a `note`, and the verdict text says ports require one-at-a-time `tools/probe.py` verification. |
| R5 | Root-level date workbench ignore patterns are broad. | **Accepted by design.** The pattern is root-only and exists to keep real target workbenches out of the published repo. Intentional future root dirs matching that shape can still be force-added after review. |
| R6 | The staged deletion set is large and should remain atomic. | **Accepted.** The commit keeps the 202 run/config removals together with the hygiene gate that prevents recurrence. Splitting only the deletions would be unsafe. |
| R7 | Evidence is partially self-referential because the modified test registry appears in `selftest_all.py`. | **Accepted as residual risk.** The arkcli reviews are the independent check; verification also includes focused checks (`check_local_hygiene.py`, `check_knowledge.py`, `proxy.py --selftest`, py_compile, bench) outside the aggregate runner. |
| R8 | Remaining raw `urllib.request` call sites were not enumerated in the bundle. | **Accepted and checked.** `rg` shows remaining direct urllib use in `tools/peer_review.py` model API calls, `tools/harness/proxy.py` handler construction, `tools/sensors/oob_listener.py` local sensor selftest path, and `tools/probe.py` itself. The reviewed active helper paths in `exploit.py` and `cdn_bypass.py` now go through `probe.send`. |

## Verification

Commands run after fixes:

```bash
venv/bin/python tools/harness/proxy.py --selftest
venv/bin/python tools/check_knowledge.py
venv/bin/python tools/check_local_hygiene.py
venv/bin/python tools/check_local_hygiene.py --selftest
venv/bin/python tools/selftest_all.py
venv/bin/python tools/bench.py score-all bench --json-out /tmp/xunji-bench-current.json
venv/bin/python -m py_compile tools/harness/proxy.py tools/exploit.py tools/cdn_bypass.py tools/check_local_hygiene.py tools/check_knowledge.py tools/selftest_all.py
git ls-files -ci --exclude-standard
rg -n "urlopen|urllib\\.request|socket\\.create_connection|build_opener" tools .claude/hooks sentinel .agents/skills
```

Result: no BLOCKER remains. Proceed to final verification and commit.
