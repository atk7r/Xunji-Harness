# Peer Review Panel — Xunji

## Verdict: PASS

- diff_fingerprint: 93394e19a04b4672
- reviewed_diff: 93394e19a04b4672
- Scope: staged framework diff for loop lifecycle, Agent lifecycle gates,
  closure gates, target cleanup ASK boundary, TRUNCATE safety rules, probe
  chunked saves, peer-review idempotency, and status/operator guidance.
- Review basis: focused arkcli rerun
  `resp_02178350788094580c56aa2c9b300d5cdd78b61f7b93dd630e094`, earlier Claude
  Code CLI direct review, and the verification suites listed below.
- Driver disposition: all material WARN findings were accepted or explicitly
  dispositioned; remaining arkcli lows are non-blocking warning-surface tradeoffs.

---

_backend: panel: · 2026-07-08T09:52Z_
> 候选, 非裁决。driver 须逐条过证据门。

## Verdict: NEEDS_DRIVER

_backend: panel:_  
_brain: codex_  
_bundle_hash: e1b8f79c4239b6b707ee8425ca16a7921eb36671_  
_evidence_index_hash: cba66f20669004a6330988747f4b721dfb6cd03a_  

## Findings
- [WARN] PR-001 review panel had backend errors; aggregation is partial | Evidence: arkcli: ERROR arkcli panel 全部模型失败: kimi-k2.7-code: arkcli exit 1; stderr/stdout tail: {
  "ok": false,
  "error": {
    "type": "error",
    "message": "arkruntime.create_responses: arkruntime: API error: Requests are too frequent. Please reduce your request frequency, wait a short moment, and retry your request. Request id: 02178350415609074362bddaa0737e4d4745c12c1558f84e4d020"
  }
}
; minimax-m3: arkcli exit 1; stderr/stdout tail: {
  "ok": false,
  "error": {
    "type": "error",
    "message": "arkruntime.create_responses: arkruntime: API error: Requests are too frequent. Please reduce your request frequency, wait a short moment, and retry your request. Request id: 021783504158001fc7bcbb7d43fe183dbed5bfff3b26ba2410959"
  }
}
; glm-5.2: arkcli exit 1; stderr/stdout tail: {
  "ok": false,
  "error": {
    "type": "error",
    "message": "arkruntime.create_responses: arkruntime: API error: Requests are too frequent. Please reduce your request frequency, wait a short moment, and retry your request. Request id: 02178350415996165a9bdff76a2fbd6d7791d2335c6a9988cc6d5"
  }
}
; claude: ERROR claude code cli failed: Command '['claude', '-p', '--output-format', 'json', '--no-session-persistence', '--permission-mode', 'dontAsk', '--effort', 'high', '--tools', 'Read,Grep,Glob', '--add-dir', '/Users/ccj/Documents/AI/Xunji']' timed out after 180 seconds | Why: At least one requested heterogeneous reviewer failed or was unavailable.

## Blind-spot check
- (none)

## Context-limit notes
- arkcli: ERROR arkcli panel 全部模型失败: kimi-k2.7-code: arkcli exit 1; stderr/stdout tail: {
  "ok": false,
  "error": {
    "type": "error",
    "message": "arkruntime.create_responses: arkruntime: API error: Requests are too frequent. Please reduce your request frequency, wait a short moment, and retry your request. Request id: 02178350415609074362bddaa0737e4d4745c12c1558f84e4d020"
  }
}
; minimax-m3: arkcli exit 1; stderr/stdout tail: {
  "ok": false,
  "error": {
    "type": "error",
    "message": "arkruntime.create_responses: arkruntime: API error: Requests are too frequent. Please reduce your request frequency, wait a short moment, and retry your request. Request id: 021783504158001fc7bcbb7d43fe183dbed5bfff3b26ba2410959"
  }
}
; glm-5.2: arkcli exit 1; stderr/stdout tail: {
  "ok": false,
  "error": {
    "type": "error",
    "message": "arkruntime.create_responses: arkruntime: API error: Requests are too frequent. Please reduce your request frequency, wait a short moment, and retry your request. Request id: 02178350415996165a9bdff76a2fbd6d7791d2335c6a9988cc6d5"
  }
}

- claude: ERROR claude code cli failed: Command '['claude', '-p', '--output-format', 'json', '--no-session-persistence', '--permission-mode', 'dontAsk', '--effort', 'high', '--tools', 'Read,Grep,Glob', '--add-dir', '/Users/ccj/Documents/AI/Xunji']' timed out after 180 seconds
- panel completed 0/2 required heterogeneous backends

> ERROR: arkcli: ERROR arkcli panel 全部模型失败: kimi-k2.7-code: arkcli exit 1; stderr/stdout tail: {
  "ok": false,
  "error": {
    "type": "error",
    "message": "arkruntime.create_responses: arkruntime: API error: Requests are too frequent. Please reduce your request frequency, wait a short moment, and retry your request. Request id: 02178350415609074362bddaa0737e4d4745c12c1558f84e4d020"
  }
}
; minimax-m3: arkcli exit 1; stderr/stdout tail: {
  "ok": false,
  "error": {
    "type": "error",
    "message": "arkruntime.create_responses: arkruntime: API error: Requests are too frequent. Please reduce your request frequency, wait a short moment, and retry your request. Request id: 021783504158001fc7bcbb7d43fe183dbed5bfff3b26ba2410959"
  }
}
; glm-5.2: arkcli exit 1; stderr/stdout tail: {
  "ok": false,
  "error": {
    "type": "error",
    "message": "arkruntime.create_responses: arkruntime: API error: Requests are too frequent. Please reduce your request frequency, wait a short moment, and retry your request. Request id: 02178350415996165a9bdff76a2fbd6d7791d2335c6a9988cc6d5"
  }
}
; claude: ERROR claude code cli failed: Command '['claude', '-p', '--output-format', 'json', '--no-session-persistence', '--permission-mode', 'dontAsk', '--effort', 'high', '--tools', 'Read,Grep,Glob', '--add-dir', '/Users/ccj/Documents/AI/Xunji']' timed out after 180 seconds

---

## Focused External Review Attempt — arkcli +chat

Because the full `peer_review.py --driver codex` matrix failed with arkcli rate
limits and Claude Code CLI timeout, Codex ran a smaller, diff-only arkcli review
over the safety-boundary changes.

- Backend: `arkcli +chat`
- Mode: independent external model review, JSON output, thinking disabled on the
  successful compact pass
- Result: `PASS` with WARN findings

### arkcli Findings

1. `WARN` — `.claude/hooks/safety_gate.py`
   - Issue: cleanup word matching was broad and could ask on benign commands when
     cleanup words and a proof-temp artifact token co-occurred.
   - Disposition: accepted. `cleanup_requires_ask()` now requires cleanup words
     to be near the artifact token, or an explicit cleanup effect such as
     `DELETE`, `PUT`, `PATCH`, `rm -f`, or `unlink`.

2. `WARN` — `sentinel/detectors.py` / `.claude/hooks/safety_rules.json`
   - Issue: narrowing recursive target-rm detection to options containing both
     `r` and `f` would miss `rm -r`.
   - Disposition: accepted. The hard target-payload rule and sentinel L4 patterns
     now catch `rm -r`, `rm -rf`, and `rm --recursive`, while `rm -f` target
     proof-artifact cleanup remains `ASK`.

3. `WARN` — `tools/workers.py`
   - Issue: Agent OPSEC artifact-name check only caught `xunji*` names even though
     the guidance forbids project/run/Agent/vuln/exploit/tool labels.
   - Disposition: accepted. The detector now also warns on common internal or
     vulnerability/tool labels such as `agent`, `worker`, `exploit`, `webshell`,
     `poc`, `vuln`, `rce`, `sqli`, `xss`, `idor`, `ssrf`, `lfi`, `csrf`,
     `scanner`, and `probe` when used as target-side artifact filenames.

### Follow-up Review Limitation

A second focused arkcli review after the fixes was attempted but hit ARK runtime
rate limiting:

```text
arkruntime.create_responses: Requests are too frequent. Please reduce your
request frequency, wait a short moment, and retry your request.
```

Claude Code CLI direct review was also attempted with a reduced diff prompt, but
did not produce output after several minutes and was interrupted.

## Final Driver Disposition

The full heterogeneous matrix was not completed: arkcli panel was rate-limited and
Claude Code CLI timed out. A focused arkcli review did complete once, returned
`PASS` with WARN findings, and all WARN findings were accepted and fixed. Residual
risk: low-to-moderate review coverage risk from the incomplete full matrix; low
runtime risk based on targeted selftests and the external WARN fixes above.

## Follow-up Review — Retrospective Closure Fixes

After the retrospective-driven fixes expanded the diff to include Agent lifecycle,
coverage-matrix closure gates, `probe.py --save-chunks`, peer-review idempotency,
version/403 closure checks, Evidence IDs parsing, retrospective nested-section
parsing, and SQL TRUNCATE false-positive narrowing, Codex attempted another
external review.

- `arkcli auth status` failed before review: Volc SSO STS refresh token was
  invalid and the CLI requested `arkcli auth login volc-sso`. No arkcli model
  review was run in this follow-up pass.
- Claude Code CLI direct review was run with `claude -p` in read-only/diff-review
  mode against the current working tree.
- Result: `PASS`.
- Claude CLI info finding: `safety_gate.py` cleanup ask branch relies on `ask()`
  exiting before the subsequent deny path. Disposition: accepted; an explicit
  comment now documents that `ask()` exits and the deny path is unreachable for
  that match.

### Follow-up Verification

- `python3 tools/check_run.py --selftest` — PASS
- `python3 tools/workers.py --selftest` — PASS
- `python3 tools/coverage_matrix.py --selftest` — PASS
- `python3 tools/probe.py --selftest` — PASS
- `python3 tools/peer_review.py --selftest` — PASS
- `python3 tools/check_hook.py` — PASS
- `python3 .claude/hooks/safety_gate.py --selftest` — PASS
- `python3 sentinel/replay.py` — PASS
- `python3 sentinel/verify_layers.py` — PASS
- `python3 tools/check_rules.py` — PASS
- `python3 tools/selftest_all.py` — PASS, 53 passed / 0 failed
- `git diff --check` — PASS

## Tests After Disposition

- `python3 .claude/hooks/safety_gate.py --selftest` — PASS
- `python3 tools/check_hook.py` — PASS
- `python3 sentinel/replay.py` — PASS
- `python3 sentinel/verify_layers.py` — PASS
- `python3 tools/workers.py --selftest` — PASS
- `python3 tools/check_rules.py` — PASS
- `python3 .claude/hooks/run_gate.py --selftest` — PASS
- `python3 .claude/hooks/output_gate.py --selftest` — PASS
- `python3 tools/selftest_all.py --only safety_gate,check_hook,sentinel_replay,verify_layers,workers` — PASS
- `python3 tools/selftest_all.py` — PASS, 53 passed / 0 failed
- `git diff --check` — PASS

## arkcli Rerun After WARN Fixes

Codex reran a focused `arkcli +chat` review after accepting the previous arkcli
WARN findings and tightening the cleanup/TRUNCATE/Agent-warning code paths.

- Backend: `arkcli +chat`
- Response ID: `resp_02178350788094580c56aa2c9b300d5cdd78b61f7b93dd630e094`
- Status: completed
- Result: `PASS`

### Rerun Findings

- `PASS` — cleanup ASK is now target-context bound: local trailing comments such
  as `curl https://t/ # cleanup tmp-...` stay silent, while proof-artifact
  cleanup remains `ASK`.
- `PASS` — generic target DELETE remains `DENY` unless it is recognizable
  proof-artifact cleanup.
- `PASS` — TRUNCATE now covers direct `TRUNCATE TABLE`, quoted/schema-qualified
  forms, and no-`TABLE` forms in SQL-client context, while the benign
  `Truncate mode enabled` wording remains allowed.
- `PASS` — Sentinel shares the TRUNCATE pattern between effect tier and autonomy
  level, keeping classification consistent.
- `PASS` — Agent cleanup warning now checks a window around the target artifact
  URL, so cleanup action before or after the URL is detected.
- `LOW/non-blocking` — a negated note such as "we will not delete anything" near
  a proof-artifact URL can still warn. Disposition: accepted; this is a warning,
  not a hard block, and keeps operator visibility on cleanup-like notes.
- `LOW/non-blocking` — the legacy `xunji_*.<ext>` cleanup escape hatch remains.
  Disposition: accepted; it exists only so cleanup of old bad target-side names
  asks for explicit yes instead of becoming permanently hard-denied. New target
  artifacts still use neutral `tmp|diag|proof-YYYYMMDD-<hex>` names.

### Verification After Rerun

- `python3 .claude/hooks/safety_gate.py --selftest` — PASS
- `python3 tools/check_hook.py` — PASS
- `python3 sentinel/verify_layers.py` — PASS
- `python3 sentinel/replay.py` — PASS
- `python3 tools/workers.py --selftest` — PASS
- `python3 tools/check_rules.py` — PASS
- `python3 tools/selftest_all.py` — PASS, 53 passed / 0 failed
- `git diff --check` — PASS
