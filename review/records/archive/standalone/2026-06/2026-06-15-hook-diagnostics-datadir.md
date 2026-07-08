# Independent Review — hook deny-diagnostics + data-dir rm rule (F5 follow-up)

- **Date**: 2026-06-15
- **Subject**: two safety-floor changes (`.claude/hooks/`):
  1. `safety_gate.py` — deny message now echoes the **matched substring + offset** (`m.group(0)`,
     `start-end`) so the driver sees what tripped which rule and rewords fast (most of this session's
     stop-and-reword churn was not knowing the matched token). Also realigned the in-file `selftest()`
     `must_block` (the rm-to-target case → quoted form, matching the earlier narrowing) + added a
     `/var/lib/mysql` must_block.
  2. `safety_rules.json` — **new data-dir rm rule** closing the F5 gap from
     `2026-06-15-hook-rule-narrowing.md`: `rm -rf` of `/data`, `/backup(s)`, `/var/lib`, `/var/www`,
     `/home/<user>/<deep>` (the catastrophic rule only matched one level under listed system dirs).
  3. (follow-up applied during this review) **D1/F4 ReDoS fix** — anchored the rm-to-target lookahead
     rule with `\A` (behavior-equivalent: re.search already only needed pos 0; the anchor stops it
     retrying every position) → O(N²) → O(N).
- **Reviewer**: fresh-context `general-purpose` sub-agent, per [`../independent-reviewer.md`](../independent-reviewer.md). Read-only, ran both self-tests + live hook subprocess checks, no edits.
- **Why**: machine hard-boundary change (`.claude/hooks/`) — mandatory independent review.

## Verdict: **PASS — land as-is.** No new bypass, no FP regression, no weakened guarantee.

Reviewer verified live (actual hook subprocess) that all true-harm data-dir cases block
(`/var/lib/mysql`, `/data`, `/var/www/html`, `/home/<u>/x`, `sudo rm -rf /var/lib/postgresql`,
long-flag `--recursive --force`) and benign/relative cases pass (`./var/lib/x`, `var/www/cache`,
`/tmp/x`, `runs/x`, `/databases`, `/backupsxyz`). The deny-echo round-trips safely through
`repr()`+`json.dumps` (cannot break the deny JSON, flip the decision, or inject; no meaningful leak).
The selftest realignment correctly reflects the narrowed rule.

## Findings & disposition

| ID | Finding | Severity | Disposition |
|----|---------|----------|-------------|
| D1 | rm-to-target rule[2] is O(N²) (~14s on 58KB; `[^'"]*` made the quote-dense constant ~1.6× worse). Pre-existing (= F4, prev review ACCEPTED), but a self-hang risk on a large legit command. | low/latent | **FIXED** this review — `\A` anchor → 16k-quote no-match now **0.5ms** (was seconds). Behavior-equivalent; check_hook + selftest still green. |
| D2 | Deep data dirs under `/opt|/srv|/mnt/<x>/...` slip BOTH rules (rule[0] one-level only; rule[1] list is literal). | low | **LOGGED, not fixed (conscious).** These fall to the native ask flow (not silent-allow). `/opt`,`/srv` hold software too → blanket deep-block raises FPs. Named clear-cut data dirs are covered; `rm -rf /opt/app/data` added to check_hook ALLOWED to record the decision. Revisit if a run needs it. |
| D3 | rule[1] also fires on force-only `rm -f /data` (no `-r`). | info | **ACCEPTED** — errs safe on an unambiguously catastrophic target. |
| OK | deny-echo harmless; selftest change correct; regex boundaries sound (`/data\b` rejects `/databases`); sudo-prefix caught; no catastrophic backtracking in rules[0]/[1]. | sound | kept. |

## Result
`tools/check_hook.py` → hook check passed (48 blocked / 41 allowed). `safety_gate.py --selftest` →
healthy. Full repo battery green (check_run/classify/probe selftests, check_rules, check_knowledge,
verify_layers NO-FP, replay 26/26). Reviewer-suggested regression cases (sudo, long-flag, TLD-boundary
look-alikes, D2 residual) all added. D1 resolved; D2 logged as a conscious residual.
