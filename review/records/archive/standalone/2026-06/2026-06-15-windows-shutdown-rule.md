# Independent Review — Windows host-shutdown deny rule (B2)

- **Date**: 2026-06-15
- **Subject**: new deny rule in `.claude/hooks/safety_rules.json` (code "B2") hard-blocking the
  native PowerShell host power-control cmdlets `Stop-Computer` / `Restart-Computer`, command-position
  anchored: `(?:^|\n|;|&&|\|\|)\s*(?:Stop|Restart)-Computer\b`. Plus its `tools/check_hook.py` tests.
- **Reviewer**: fresh-context `general-purpose` sub-agent, per [`../independent-reviewer.md`](../independent-reviewer.md). Read-only, ran the self-tests + a standalone 40-input regex probe, no edits.
- **Why**: behavior change to safety-critical code (`.claude/hooks/`) — CLAUDE.md mandates an
  independent review before declaring it done.
- **Context**: the rule was added because this is a Windows host and the agent auto-executes
  PowerShell; the old shutdown rule covered only `shutdown/reboot/halt/poweroff/init`, not the
  PS-native cmdlets. It was first written as a bare `\b(?:Stop|Restart)-Computer\b` and **immediately
  false-fired** on an `echo` that merely contained the cmdlet name as data, so it was narrowed to the
  command-position anchor (same shape as the neighboring shutdown rule). The operator separately
  decided to **keep** host shutdown/restart as a hard block (not demote to ask).

## Verdict: **PASS — land as-is.** No new bypass beyond the gaps already accepted on the sibling shutdown rule; no false positives; regex clean. Only test coverage was thin — fixed this review.

Reviewer verified live (`check_hook` + selftest + standalone probe) that B2 fires on command-position
`Stop/Restart-Computer` across `^` / `\n` / `;` / `&&` / `||` / leading-whitespace / mixed-case, and
stays silent on every name-as-data form (`echo '…'`, `grep Restart-Computer`, `Get-Help`, mid-line
`$x='Restart-Computer'`). `shutdown.exe` is correctly the neighboring rule's job, not B2's.

## Findings & disposition

| ID | Finding | Severity | Disposition |
|----|---------|----------|-------------|
| B2-9 | Test coverage thin on the **anchor itself**: BLOCKED pinned only `^`-anchored forms; nothing pinned the `;`/`&&` separators firing, nor that mid-line name-as-data stays silent. A future anchor "simplification" could regress with green tests. | med | **FIXED** this review — added BLOCKED `1; Stop-Computer`, `true && Restart-Computer`; ALLOWED `grep Restart-Computer …`, `Get-Help Restart-Computer`. `check_hook` green. |
| nit | B2's `reason` enumerated **no** accepted gaps, while the sibling shutdown rule documents its own (`bash -c …`, `cmd & shutdown`) — the one place B2 was *less* documented than its sibling. | low | **FIXED** — B2 `reason` now lists the accepted gaps (scriptblock/Invoke-Command, single-pipe, call-operator, single-&). No pattern change. |
| B2-1 | Scriptblock / call-operator bypass: `&{Restart-Computer}`, `& Restart-Computer` reboot the host but pass. | low | **ACCEPTED** — symmetric to the shutdown rule's accepted `bash -c "shutdown"` gap; wrapped invocation, recoverable effect, robust match needs PS-grammar parsing. |
| B2-2 | Single-pipe bypass `X \| Restart-Computer -Force` passes; sharper here than on shutdown because PS `Restart-Computer` **does** accept pipeline input. | low | **ACCEPTED / LOGGED** — still recoverable + evasion-shaped; adding single-`\|` as a separator would risk FPs on benign pipelines naming the cmdlet. Recorded as a PS-specific residual. |
| B2-3 | `Invoke-Command -ScriptBlock {Stop-Computer}` (local/remote) bypasses both rules — the most realistic PS "reboot a box" form. | low | **ACCEPTED/LOGGED** — same wrapped-invocation class as B2-1. |
| B2-4 | Single-`&` background `X & Restart-Computer` passes. | low | **ACCEPTED** — explicitly mirrors the shutdown rule's accepted `cmd & shutdown` gap. |
| B2-5 | **No false positives found.** Command-position anchor has no benign victims (no benign command begins with these cmdlets); `\b` after `-Computer` lets longer tokens through. | info | sound, kept. |
| B2-6 | **Regex / ReDoS clean.** Fixed alternation anchor + one `\s*` + literal alternation + literal `-Computer\b`; no nested quantifiers, no catastrophic backtracking. | info | sound, kept. |
| B2-7 | **Consistency appropriate.** B2 omits the shutdown rule's `\bsudo\s+` and `(?:/\S+/)?` prefixes — correct, since PS cmdlets are neither sudo-gated nor path-prefixed. Anchor = shutdown rule's minus the `sudo` alternative. | info | sound, kept. |
| B2-8 | **Doctrine:** host shutdown/restart is *recoverable*, so it is the softest member of an "irreversible-only" hard floor; the file's top `_comment` charter still says only "irreversible," which now under-describes what's enforced (shutdown + B2 are recoverable-but-highly-disruptive). B2 isn't *adding* the inconsistency — it matches the pre-existing shutdown rule. | info | **LOGGED, not fixed.** Operator consciously decided to keep recoverable host-power in the hard floor (see [[hook-fp-handling-operational]]). Optional future: reconcile the top `_comment` wording to "irreversible **or** highly-disruptive never-auto". Out of scope for this rule. |

## Result
`tools/check_rules.py` → rule check passed. `tools/check_hook.py` → hook check passed (with the B2-9
regressions). `safety_gate.py --selftest` → healthy. All MED/should-fix findings resolved with
regression tests pinning each anchor; bypass residuals accepted on the same standard as the sibling
shutdown rule; the doctrine note (B2-8) logged as a conscious operator decision.

> Note (from the reviewer, worth keeping): authoring B2 regression cases as **inline shell literals**
> trips this very rule — its first probe heredoc containing `; Restart-Computer` was itself denied.
> Regression cases must live as **quoted data inside the Python test file** (where they do), never as
> raw shell. A live demonstration of [[hook-fp-handling-operational]]: the gate matches raw script text.
