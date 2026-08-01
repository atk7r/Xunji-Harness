# Independent Review — Session Circuit Breaker (Part A + Part B)

- **Date**: 2026-06-14
- **Subject**: the session circuit-breaker work (sentinel Part B + guard Part A)
- **Commits reviewed**: `9f1fb27` (Part B), `3bd97f8` (Part A), `17fb623` (self-audit fixes), `d1b0cfb` (docs reorg)
- **Reviewer**: fresh-context `general-purpose` sub-agent, per [`../independent-reviewer.md`](../independent-reviewer.md). Read-only, no network, no edits.
- **Why**: framework code, not a run — but self-review does not fix self-review bias. The author's own "自检" earlier missed real issues; this is the independent pass. (First time the independent-review pattern was applied to *code* rather than a pentest run.)

This record exists because the review must leave an audit trail, not live only in chat
(CLAUDE.md: "the run directory is the audit trail"). For code reviews there is no run
dir, so the record lives here under `review/records/`.

## Findings & disposition

Every finding is resolved on the record (act / downgrade / dismiss-with-reason), as the
template requires.

| ID | Finding | Severity | Disposition |
|----|---------|----------|-------------|
| **B1** | `--retry N` fires up to N+1 real requests (each through `RateLimiter.gate`) but `SessionBudget` recorded only once → whole-session volume breaker undercounts; **directly contradicts commit `17fb623`'s claim that failed requests are counted**. | real bug | **FIXED** `6216dee`. `SessionBudget.record(nbytes, count)` records `count` requests; `probe.send()` tracks `attempts` and passes it on both success and error paths. Guard selftest gains a retry-count regression. |
| **B2** | `apply_breaker` clamped on `level >= GATE`, which would downgrade a hypothetical `(BLOCK,"AUTO")` to GATE — violates "the breaker only ever escalates". Unreachable today (`autonomy_decision` never emits BLOCK+AUTO) but a latent invariant landmine. | latent | **FIXED** `6216dee`. Tightened to `GATE <= level < BLOCK`. |
| **T-gap 1** | The breaker's MAIN job — an effectful AUTO decision clamped to GATE via the live `M.assess()` path — was never asserted (only the `apply_breaker` unit was). | test gap | **FIXED** `6216dee`. Added an assess-level clamp case (operator-directed reverse shell to in-scope target = `(GATE,"AUTO")`, genuinely effectful).补测时还抓出一个 fixture bug(chmod 被判 housekeeping rule 1)。 |
| **T-gap 2** | operator-reset's T2 re-baseline path was untested (the earlier reset test used `risk_score=0`). | test gap | **FIXED** `6216dee`. Added a distinct operator-reset re-baseline regression. |
| **T-gap 3** | `record(count=N)` retry accounting had no test. | test gap | **FIXED** `6216dee`. Added to guard selftest. |
| **T-gap 4** | Full hook-level end-to-end (`_taint_active` + session persistence + taint decrement → T1 trip via `handle_event`) is covered only by a manual smoke, not an automated regression. | test gap | **RESIDUAL — accepted for now.** assess-level + unit coverage added; the live `handle_event` IO path was smoke-tested (exit 0, no traceback) but not auto-tested. Revisit if the breaker moves from observe-only toward enforcement. |
| **Doc 1** | `SESSION_TRIP_BYTES` doc said "retained-egress bytes" but code measures pre-cap wire bytes (`len(raw)`). | doc | **FIXED** `6216dee`. guard.py + TUNING.md reworded to "pre-cap wire bytes". |
| **Doc 2** | T1 "consecutive effectful" wording vs the mechanism (hot taint forces actions ≥GATE). Net effect correct. | doc | **FIXED** `6216dee`. TUNING.md T1 row clarified. |
| **Doc 3** | commit `17fb623` said "27 cases", actual `26`. | nit | **Noted, not corrected** — committed history; accuracy maintained going forward. |
| **By-design** | T3 `escalation_hits` has no time window (3 high findings any time apart → trip). | observation | **Dismissed** — by design (cumulative since clear), documented in TUNING.md. A windowed variant is a future tuning option. |
| **Confirmed honest** | The author's disclosed scope limits (scan.py not in Part A, Part B per-session, `check()` lock-free read) | — | Reviewer verified these are honest disclosures, not cover. `check()` lock-free read is bounded (arming completes under lock), not a correctness hole. |

## Closure judgment

Reviewer's verdict: not "done" until B1 + B2 fixed and the live-path tests added.
**All blocking items (B1, B2, T-gap 1/2/3, Doc 1/2) resolved in `6216dee`.** One
non-blocking residual (T-gap 4, full hook e2e) is accepted and recorded above.

Post-fix state: replay 26/26 · verify_layers 0 FP / 0 miss · guard selftest OK
(incl. retry-count). This round stands.

## Meta

This is evidence for extending the independent-review gate from pentest-run closure to
significant framework changes ("option #2"): the independent pass found a real bug (B1)
the author's self-audit missed, and that bug contradicted the author's own commit claim
— the exact self-review blind spot the mechanism targets, now demonstrated on code.
