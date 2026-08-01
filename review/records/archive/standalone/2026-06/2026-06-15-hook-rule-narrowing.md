# Independent Review — safety_rules.json false-positive narrowing

- **Date**: 2026-06-15
- **Subject**: narrowing two over-broad PreToolUse deny rules in `.claude/hooks/safety_rules.json`
  (the "rm shipped to target" co-location rule, and the secure-wipe `scrub` alternative), plus
  regression tests in `tools/check_hook.py`.
- **Reviewer**: fresh-context `general-purpose` sub-agent, per [`../independent-reviewer.md`](../independent-reviewer.md). Read-only, no network, no edits.
- **Why**: behavior change to safety-critical code (`.claude/hooks/`). CLAUDE.md mandates an
  independent review before declaring such a change done — self-review does not fix self-review bias.
- **Trigger**: two real false positives during a real run — (1) a standalone local scratch
  `rm -f` sharing a command line with a probe URL was hard-denied; (2) the English word "SCRUB" in
  an `echo` matched `\bscrub\b` in the secure-wipe rule. Operator directed narrowing to cut FPs.

## Change summary

- **rm-to-target rule**: old `(?=.*rm -rf)(?=.*https?://)` (any rm-rf + any URL anywhere) →
  new `(?=[\s\S]*['"][^'"]*\brm\s+-{1,2}[a-z]*[rf])(?=[\s\S]*(?:https?|ftp)://)` — the destructive
  `rm -rf` must now appear **inside a quoted string** (i.e. injected as request payload) alongside a URL.
- **scrub alternative**: `\bscrub\b` → `\bscrub\s+(?:-{1,2}[a-zA-Z]|/dev/)` — only the disk-wipe tool
  invoked with a flag (short or long) or a `/dev/` target; not the bare English word / read-only
  `zpool|btrfs scrub`.
- Tests: added BLOCKED (`scrub -p dod /dev/sda`, `scrub --remove /data/dir`, double-quoted +
  long-flag rm payloads) and ALLOWED (standalone local rm + probe URL on one line, `rm -rf tmp/build
  && curl ...`, unquoted inert `?c=rm+-rf+...`, `zpool scrub tank`, `echo 'SCRUB verify'`).

## Verdict: **PASS — landed as-is.**

Reviewer confirmed `python tools/check_hook.py` passes and the narrowing opens **no new real-harm
bypass**: the rm-rule's true threat model is a destructive payload *injected into a request* (a `rm`
token in a URL/`-d` body is inert data, never executed), which the quoted-string pattern matches
better than the old co-location form; **local** destructive `rm` is — and always was — the
catastrophic-path rule's job (rules[0]), unchanged by this edit.

## Findings & disposition

| ID | Finding | Severity | Disposition |
|----|---------|----------|-------------|
| F1 | scrub long-flag gap: `scrub --remove <file>` escaped `-[a-zA-Z]` (single dash only). | low | **FIXED** — broadened to `-{1,2}[a-zA-Z]`; added `scrub --remove /data/dir` to BLOCKED tests. |
| F2 | Recommended regression tests (unquoted inert `?c=rm+-rf`, `rm -rf tmp/build && curl`, double-quoted + long-flag rm payloads). | test gap | **FIXED** — all added to `check_hook.py`; suite passes. |
| F3 | `scrub <file>` bare (no flag, non-`/dev/`) now allows, though it would wipe that file. | edge | **ACCEPTED** — rare shape; realistic destructive scrub is `-p`/`/dev/`; trade-off justified vs the common "scrub" FP. Documented here as a conscious decision. |
| F4 | Regex backtracking: two `[\s\S]*` lookaheads ~1.46s on a 20KB no-match input; linear-ish, terminates, fail-closed only on exceptions. Latency note, not a hole. | low/latent | **ACCEPTED** — no security impact; optional future hardening (length cap) noted, not done. |
| F5 | **Pre-existing, NOT from this change**: catastrophic-path rule (rules[0]) does not list `/data`, `/var/lib/mysql`, `/home/<user>/...` → local `rm -rf` of those falls through to ask/allow. | pre-existing | **OUT OF SCOPE** — surfaced by review, not introduced here. Logged as a separate follow-up to decide whether those data paths belong in the catastrophic list. |

## Result
`python tools/check_hook.py` → `hook check passed`. Change is behavior-correct (FPs fixed, real
destructive effects still denied) and recorded. F5 left as a separate, pre-existing ticket.
