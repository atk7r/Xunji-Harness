# Peer Review Panel — 2026-07-13-setup-success-silent

_backend: panel:arkcli+claude · 2026-07-13T07:07Z_
> 候选, 非裁决。driver 须逐条过证据门。

## Verdict: WARN

_backend: panel:arkcli+claude_
_brain: codex_
_bundle_hash: 4f5a053be46e661202927b4aee005fea1003b436_
_evidence_index_hash: 8b23d049826832fbba4f588c6fe094ad1fb22b12_

## Findings
- [WARN] PR-001 Broad 'stdout audit' claim in selftest.log is not independently reproducible from provided artifacts | Evidence: evidence/selftest.log, evidence/setup_success_silent.diff | Why: [panel:arkcli] [arkcli:kimi-k2.7-code] The log asserts every normal-path print/write targets stderr, but the bundle only contains the diff and selftest output; a reviewer cannot independently verify no other stdout prints remain in the unchanged portions of the files.
- [WARN] PR-002 Failure and degraded-path stderr diagnostics are asserted but not exercised in evidence | Evidence: evidence/setup_success_silent.diff, evidence/selftest.log | Why: [panel:arkcli] [arkcli:kimi-k2.7-code] The selftest only validates success paths and a mocked --classify success; no evidence demonstrates that exception-handler stderr prints actually occur and are visible in failure scenarios.
- [WARN] PR-003 loop_bootstrap.py change suppresses whitespace-only output, not merely blank lines | Evidence: evidence/setup_success_silent.diff:@@ cmd_new | Why: [panel:arkcli] [arkcli:kimi-k2.7-code] Changing `print(r.stdout.rstrip())` to `if r.stdout.strip(): print(r.stdout.rstrip())` suppresses any whitespace-only output, which is broader than the stated goal of avoiding a blank line.
- [WARN] PR-004 No real-run integration evidence beyond isolated selftest | Evidence: evidence/selftest.log | Why: [panel:arkcli] [arkcli:kimi-k2.7-code] The selftest uses an isolated root, redirects streams, and mocks the classifier subprocess; it does not prove silent behavior in the actual run lifecycle with real modules.

## Blind-spot check
- [arkcli] [kimi-k2.7-code] Full current source files are not artifacts; review relies on a diff that may omit unchanged print statements.
- [arkcli] [kimi-k2.7-code] xunji_statusline.set_active_run() internal stdout/stderr/file side effects are not evidenced.
- [arkcli] [kimi-k2.7-code] No artifact verifies journal files contain phase_start/phase_end after a real run.
- [arkcli] [kimi-k2.7-code] No regression check for downstream consumers that may have parsed setup stdout.
- [arkcli] [glm-5.2] No confirmed (certainty >= 0.8) findings are missing from the report: the evidence_index has only three candidate entries, all of which are carried into report.md's review questions, and none are over-claimed as confirmed vulnerabilities. This is correctly scoped as repository maintenance with `has_control: false` and `confirmed: false` on every evidence entry.
- [arkcli] [glm-5.2] Single-observation / redirect / block-page / timeout discipline is not in play here — there is no target traffic, so there are no such observations to downgrade. The only "observations" are selftest stdout, which is an environment-provided artifact; however, the diff artifact independently proves the code state, so the claim does not rest on selftest alone.
- [arkcli] [glm-5.2] The author did not silently drop any unclassified asset: there is no coverage/classify ledger and no recon asset list in this run because it is a tooling-maintenance change, not a pentest run. The coverage-ledger rubric is therefore non-applicable rather than violated.
- [arkcli] [glm-5.2] One narrow thing the author could have made stronger but did not: the selftest does not appear to assert that `--selftest` itself remains stdout-non-empty (it asserts the result block exists only via the external `selftest.log` prose, not via a captured-stdout assertion in the diff). This is a very minor hardening gap, not a defect.
- [arkcli] [glm-5.2] No artifact cross-check failure: I opened the cited artifacts in the bundle. `setup_success_silent.diff` contains the exact hunk headers and code shown; `selftest.log` contains the listed passing checks; `docs.md` contains the quoted policy excerpts. No empty/missing/inconsistent artifact was found for any confirmed claim.
- [claude] **classify_hosts output discard is the critical miss**: The author treated all stdout as "setup progress noise" but `sys.stdout.write(r.stdout or "")` was a passthrough of a tool subprocess. This is the difference between silencing `[setup] 建 run 骨架 /tmp/...` (correct) and silencing `Host 10.0.0.1: fingerprint=nginx/1.24, reachable=true` (incorrect — operational data).
- [claude] **The selftest architecture has a fundamental blind spot**: It verifies silence by faking the subprocess that could produce output. The test proves "if classify_hosts produces output, we discard it" but never tests "what does real classify_hosts produce?" This is testing the wrong thing — it should test that real classify output goes somewhere useful, not that it's silently dropped.
- [claude] **No forward-compatibility guard**: The selftest enforces stdout-silence as a contract, but what happens when a future developer adds `import logging; logging.basicConfig(level=logging.INFO)` to setup_run.py? The logging module defaults to stdout. The manual "stdout audit" line in the selftest log is a one-time human check — there's no automated lint/CI rule to prevent future stdout emissions.
- [claude] **`_set_active_run` called twice but once silently**: The function is called via `_set_active_run(run_dir)` after the journal phase-end. The earlier call inside `_set_active_run`'s own body had its success print removed. If `xunji_statusline.set_active_run()` itself prints to stdout on success, that print is not controlled by this diff and could break the silence contract.

## Context-limit notes
- [arkcli] [glm-5.2] Several code strings are in Chinese (e.g., `ingest_recon 失败`, `scope 派生失败`). I read them as failure/degraded diagnostics, which the surrounding `file=sys.stderr` and the selftest's stderr-empty success-path assertion corroborate. I do not believe I am misreading these, but a native-CN reviewer could double-check that none of the removed Chinese prints were actually operator-required success banners rather than progress chit-chat.
- [arkcli] [glm-5.2] The run name and docs reference the Xunji / Guanlan / CNVD-adjacent toolchain; I am treating this purely as an internal repo-maintenance audit and not as an authorized-target pentest. If the broader program considers `tools/setup_run.py` changes to be in-scope for security review (e.g., because silent setup could mask a malicious run-dir switch), that is a program-policy question outside what the evidence_index supports here.
- [arkcli] [glm-5.2] I cannot run `tools/setup_run.py --selftest` myself (read-only review), so I rely on `selftest.log` plus the diff. The two are mutually consistent, but independent re-execution would be the strongest possible confirmation and is not available to me.
- [claude] I cannot read the live `tools/setup_run.py`, `CLAUDE.md`, `docs/WORKFLOW.md`, or `.claude/skills/xunji-run-lifecycle/SKILL.md` due to tool restrictions. My analysis is based on the review bundle artifacts. The claim that policy files match E-SILENT-003 is taken on the evidence artifact's authority.
- [claude] I cannot run `tools/setup_run.py --classify` to verify real classify_hosts behavior. The warning about stdout discard is based on diff analysis — if classify_hosts writes its operational output to a file (not stdout), then the concern is partially mitigated, but the selftest's faked output suggests stdout is the primary channel.
- [claude] The diff format (`@@ _set_active_run` without line numbers or context) is unusual. If the full unified diff has additional context lines showing the `if` condition handling, my concern about the if/else ambiguity would be resolved.
- [claude] The Chinese policy paragraphs in E-SILENT-003 were machine-readable and consistent with the English excerpts. I have medium-high confidence in the cross-language consistency.
- [claude] This is repository maintenance (code change review), not a pentest finding review. The pentest rubric (certainty grades, coverage ledger, false positives, etc.) does not directly apply, and I have adapted my analysis to the code-review domain.
