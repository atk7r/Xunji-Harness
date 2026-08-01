# Claude primary-driver skill consolidation E2E

- Date: 2026-07-18
- Candidate base: `5d0a99c0170194fd3445db8a3040d759a64f3bba`
- Isolated candidate: detached worktree containing only the Phase 1 file set
- Driver: Claude Code 2.1.201 through the locally configured DeepSeek API
- Model / effort: `deepseek-v4-pro[1m]` / `high`
- arkcli: explicitly not used
- Source mutations during E2E: none
- Final E2E disposition: **PASS**

This is a primary-driver execution record, not the independent review vote. A
separate fresh Claude session reviews the final staged fingerprint before commit.

## Discarded environment attempt

Session `1f0aaaf2-9d42-45a7-a4f1-d6dd8940a8dc` selected macOS system Python
3.9 for project hooks. Importing the existing `dict | bytes` type expression in
`setup_transaction.py` failed before the candidate could be tested, so the run
was interrupted and never counted as PASS.

- Transcript SHA-256:
  `72d6933905e9a5250b62b0943051d431f01a685775db59bf1c94b6f23deadab3`
- Recovery: fixed the isolated process `PATH` to the project Python/Claude Code
  environment and started fresh sessions; no repository source changed.

## Web-research compatibility route

- Session: `cbe7e0c3-ab78-4adb-a7f8-0a0c0a2dbaaf`
- Transcript SHA-256:
  `80fedf3931c2c373f51ee7b19ef3172c5310f34cb3783cbd1864adb7bd13388d`
- Actual invocation: `/xunji-web-research-sync`
- Verdict: `PHASE1_WEB_VERDICT=PASS`

Claude Code loaded the 13-line alias as a real skill command, then read the
canonical `web-research` owner and its Router/Workflow/tool contracts. It:

- executed both exact registered time-gate argv forms;
- confirmed neither generated hint required WebFetch;
- performed one public WebSearch for the official Python 3.14 release date with
  the 2026/current-date constraint and used no WebFetch;
- returned a structured `phenomenon` / `0.3` lead without an E-id or canonical
  evidence/decision write;
- confirmed the timestamp argv maps to `read.timestamp-gate` / `local_read` and
  active-run WebFetch is denied;
- ran `timestamp_gate.py --selftest` and `check_templates.py` successfully.

An initial `check_templates.py --selftest` attempt was correctly denied because
that argv is not documented; Claude repaired it by running the exact no-argument
command. Denied or compound diagnostic attempts were not counted as results.

## Review-panel compatibility route

- Session: `b281ff84-b1fb-4f6a-872f-15c5b3914f87`
- Transcript SHA-256:
  `e0cbcc30d39b6c36c394599a4951e6f23a3b55753f1c23a4edc4bfe1d2f52765`
- Actual invocation: `/xunji-peer-review-panel`
- Verdict: `PHASE1_REVIEW_ROUTE_VERDICT=PASS`

Claude Code loaded the 14-line alias as a real skill command and followed both
canonical destinations. It confirmed:

- the alias owns no commands or author matrix;
- `xunji-reviewops` owns adjudication while its peer-review reference owns
  backend selection, author matrix, CLI, egress, and fallback behavior;
- Claude-driven work with no Codex/arkcli records the weaker same-family
  fallback, while Claude Code CLI is independent for Codex-authored work under
  `--driver codex`;
- every reviewer result remains candidate material.

The hook rejected initial commands containing `2>&1`. Claude then retried the
same tests with the trusted Python executable and clean argv. Final results were:

- `tools/peer_review.py --selftest`: 79 passed;
- `tools/selftest_all.py --only peer_review`: 1 passed, 0 failed;
- `tools/check_templates.py`: passed.

No review backend was invoked in this routing test, and arkcli was never called.

## Frozen candidate regression

After both Claude sessions, the isolated worktree still contained exactly the
copied Phase 1 diff and no additional source/run-state files. The same isolated
candidate passed `tools/selftest_all.py`: **69 passed, 0 failed (104.0s)**,
including the real localhost probe suite authorized by the operator.
