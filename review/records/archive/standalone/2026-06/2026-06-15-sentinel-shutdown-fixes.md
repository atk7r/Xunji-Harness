# Independent Review — sentinel scope fixes + shutdown-rule narrowing

- **Date**: 2026-06-15
- **Subject**: P1 retrospective fixes to the behavior monitor and the host-shutdown deny rule:
  - `sentinel/state.py` — `scope_hosts()` extracts bare domains (was URL/IP only → empty scope on
    a `Target: example.com` line → false `scope_drift` all run); + skip exclusion lines; + bounded domain regex.
  - `sentinel/classifier.py` — `_host_in_scope()` subdomain-aware (api.example.com ∈ example.com),
    leading-dot suffix guards look-alikes.
  - `.claude/hooks/safety_rules.json` — host shutdown/reboot rule narrowed to command-position
    (was bare `\b(shutdown|…)\b`, false-fired on `srv.shutdown()`, `grep 'shutdown'`, `?x=1&shutdown`).
  - tests in `tools/check_hook.py`.
- **Reviewer**: fresh-context `general-purpose` sub-agent, per [`../independent-reviewer.md`](../independent-reviewer.md). Read-only, ran the self-tests, no edits.
- **Why**: behavior change to safety-critical code (`.claude/hooks/`, `sentinel/`). CLAUDE.md mandates
  independent review before done. (`tools/probe.py`, `classify_hosts.py`, `check_run.py` were fixed in
  the same retrospective but are not the safety floor; tested, not part of this record's mandate.)
- **Context**: trigger was a real-run retrospective — sentinel ran the whole engagement on an empty/
  stale scope (every action false-tripped `scope_drift` + breaker, observe-only so nothing blocked).

## Reviewer verdict: initially **NOT final — 2 should-fix + 1 latent**; all resolved below.

| ID | Finding | Severity | Disposition |
|----|---------|----------|-------------|
| H1 | Shutdown narrowing **dropped canonical forms**: `systemctl poweroff/reboot/halt`, absolute-path `/sbin/shutdown`, `/sbin/reboot` — non-evasion host-shutdowns the old rule caught; the enforcing hook now let them through (sentinel labels BLOCK but never enforces). | hard-hook regression | **FIXED** — rule now allows an optional `/path/` prefix and `systemctl …` (and `||`/`sudo`) at command position; added a separate `init 0|6` / `telinit 0|6` rule (closes a pre-existing gap too). check_hook BLOCKED cases added: `systemctl poweroff/reboot/halt`, `/sbin/shutdown -h now`, `/sbin/reboot`, `sudo systemctl poweroff`, `init 0`, `telinit 6`. |
| H2 | Bare-domain scope extraction **slurped `Out-of-scope:` / `Scope exclusions:` lines** (and prose) into the in-scope set → an explicitly-excluded host would NOT raise `scope_drift` (the exact miss the monitor exists to prevent). | sentinel 漏警 | **FIXED** — `_EXCL_RE` skips exclusion/negation lines (out-of-scope / exclu… / black\|deny-list / do not / 不测 / 排除 / 禁止 / 黑名单 / 不在范围). Verified: `Out-of-scope:` + `Scope exclusions:` + `排除:` domains are no longer in scope; `app.example.com` still is. (Residual: same-line prose infra domains can still bleed in — observe-only, low; noted, not fixed.) |
| L1 | `_DOMAIN_RE` catastrophic backtracking on a pathological many-dotted line (~80s), runs inside the state-lock. | low/latent | **FIXED** — label count bounded `{1,16}`; pathological 9k-label line now 0.010s. |
| OK | `_host_in_scope` subdomain + leading-dot look-alike defense (`example.com.evil.com`, `evil-example.com`, `xexample.com` rejected; case-insensitive; empty-host safe). | sound | kept as-is (reviewer confirmed correct). |
| OK | All intended FP fixes (`srv.shutdown()`, `logging.shutdown()`, `grep 'shutdown'`, `echo shutdown`, `?x=1&shutdown=now`, comments). | sound | kept; ALLOWED tests added incl. `echo systemctl …`, `git init`, `npm init -y`. |

## Result
`python tools/check_hook.py` → hook check passed; `sentinel/verify_layers.py` → EFFECTIVE, NO FALSE
POSITIVES; `sentinel/replay.py` → 26/26; `tools/check_run.py` / `check_rules.py` / `check_knowledge.py`
all pass. Both should-fix findings + the latent are resolved with regression tests pinning each.
Residual accepted: same-line prose-infra domain bleed (observe-only, low); `bash -c "shutdown"` /
`cmd & shutdown` (recoverable, evasion-shaped).
