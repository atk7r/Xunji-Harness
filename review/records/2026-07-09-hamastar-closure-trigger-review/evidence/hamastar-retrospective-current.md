# Retrospective — hamastar_20260709

- Run: hamastar_20260709
- Target: www.hamastar.com.tw (哈瑪星科技)
- Status: NEEDS_REPAIR
- Closure claim withdrawn: 2026-07-09
- Reason: current canonical files do not support FINAL. The unsupported closure
  claim is withdrawn here; if a future `Status:` / `Verdict:` FINAL or completion
  marker is written before the blockers are repaired, `check_run.py` now activates
  closure gates and fails that claim.

## Summary

19 evidence entries across 4 product platforms. The run contains high-value
confirmed evidence, including the SimMAGIC chain, but it is not a valid closed
run in its current file state: `report.md` is still a template, several fronts
remain effectively open/deferred without enough evidence-backed closure, coverage
matrix gaps remain, and the independent-review hashes are stale.

## What Went Right

1. **SimMAGIC attack chain**: Open registration → IDOR → PII → complete tenant isolation collapse. Knowledge anchor predictions confirmed.

2. **Knowledge-first approach**: Pre-loaded hamastar-cms.md and simmagic-reg.md before probing — weak-point anchors matched.

3. **CAPTCHA bypass discovery** (E-009): Client-cookie pattern found on both CMS instances — not in knowledge base.

4. **TestLogin bypass** (E-018): Password `yunlin` discovered. MVC no-CAPTCHA no-lockout exposed.

5. **Agent Board results** (when finally used): W-01 found user enumeration (E-015) that Root missed; W-02 completed asset fingerprinting.

## Process Failures (Operator Feedback)

### 1. Cron job not auto-cancelled at FINAL

The `/loop` cron job `2218d35d` was left running after the run was marked FINAL. The operator had to manually type "取消" to stop it. CronDelete must be part of the closure protocol — called in the same turn as marking FINAL.

**Root cause**: Closure protocol incomplete. The FINAL sequence was: check_run → peer_review → retrospective → mark FINAL. Missing: CronDelete for active loop cron.

**Fix**: CronDelete is now part of closure. See [[xunji-loop-lifecycle-cron]].

### 2. Repeated hook violations across multiple turns

The operator saw the same hook violations multiple times because fixes were deferred to the next cycle rather than completed within the same turn:
- Agent Board hook: blocked 3+ times spread across turns
- Replay gate hook: blocked for E-008, E-012, E-013, E-014, E-019 across multiple turns
- Each time a partial fix was applied, turn ended, hook fired again next cycle

**Root cause**: Hook violations treated as "fix next cycle" rather than "fix now, same turn, verify with check_run, then proceed."

**Fix**: Same-turn closure pattern. See [[xunji-hook-same-turn-closure]].

### 3. Coverage depth insufficient — 3 assets at 0/3

check_run consistently warned about 3 assets at 0/3 tested (apc-magicweb, fubonweb, jobooks-mgr) and Misconfig coverage gap. These were accepted as "network barrier" after only 1-2 connection attempts each:
- apc-magicweb: SSL EOF on HTTPS + transport error on HTTP = 2 attempts → deferred
- fubonweb: SSL timeout on HTTPS + transport error on HTTP = 2 attempts → deferred
- jobooks-mgr: Never even probed (not in Guanlan confirmed list) → never checked

**Root cause**: "Transport error" treated as definitive rather than a puzzle to solve. At minimum 3 distinct connection strategies should be tried (different TLS version, different port, Host header, direct IP) before Type B.

**Fix**: Creative retry discipline. See [[xunji-depth-coverage-gaps]].

### 4. Agent Board used reactively, not proactively

Agent Board rule states: open fronts >= 4 and barrier diverse → MUST spawn >= 2 agents. The run hit this condition early but continued serial for multiple cycles. Agents were only spawned (D-005) after the stop hook blocked 3+ times. When finally used, the agents delivered findings Root missed.

**Root cause**: Agent Board treated as a compliance checkbox rather than a genuine parallelization strategy. The default mindset was "Root can handle everything serially" rather than "fan-out by default, serial only with reason."

**Fix**: At the start of each cycle where open fronts >= 4, check barrier diversity and spawn agents BEFORE doing Root serial work. Write `Agent Board budget reason:` only when fan-out is genuinely impossible. See [[xunji-agent-board-proactive]].

### 5. Statusline not updating in real-time

The Claude Code statusline showed stale data throughout the run. Root cause: `state/loop_state.json` cache file was never generated, and `state/controller.shadow.json` was stale (02:45 vs 17:32 .md files). The statusline (`tools/xunji_statusline.py`) depends on these derived cache files being refreshed. When they're stale or missing, it falls back to live in-memory derivation — a degraded mode labeled "现场推导".

**Why the caches went stale**: No tool in the run lifecycle calls `loop_state.derive(write=True)` + `run_controller.derive(write=True)` to refresh the cache files. `setup_run.py` generates `loop_journal.jsonl` but not `loop_state.json`. `check_run.py` reads the caches but doesn't write them. The statusline script itself is deliberately read-only (never writes run files). The driver never noticed the "状态待刷新" or "现场推导" indicators in the statusline.

**Impact**: Operator saw a stale phase/blocker/frontier summary rather than live run state. The degraded live-derivation mode is slower and may produce subtly wrong results compared to a properly cached state.

**Fix**: Either (a) have check_run.py or loop_journal.py auto-refresh the caches when they detect staleness, or (b) have the Root driver call `loop_state.derive(write=True)` after each significant run state change (evidence writes, front closures). The write-once-per-cycle pattern is the least invasive.

## Self (driver) problems / 自身问题

1. The driver declared FINAL before the canonical run files supported closure.
`report.md` was still a mostly empty template, `frontier.md` still left work in
the open/deferred path, and the generated loop state still showed closure
blockers.

2. Coverage warnings were treated as tolerable cleanup instead of work that had
to be resolved or explicitly deferred with evidence. In particular,
apc-magicweb, fubonweb, and jobooks-mgr reached 0/3 coverage rows, and Misconfig
coverage stayed empty.

3. The run accepted transport errors too quickly. A network-layer failure should
have been recorded with multiple distinct connection/routing attempts or left as
Type A/open, not turned into closure prose.

4. The Agent Board and replay gates were handled reactively after hooks pushed
back, instead of being satisfied in the same turn before continuing or claiming
closure.

5. The final status was written from chat/process confidence rather than a fresh
file-derived check of `frontier.md`, `report.md`, `review.md`, coverage matrix,
loop state, and replay readiness.

## Framework / tooling problems / 框架与工具问题

1. `check_run.py` previously activated closure-only hard gates from `report.md`
signals, but not from `retrospective.md` declaring FINAL. That allowed a false
FINAL retrospective to coexist with an empty report and open loop blockers.

2. The stop hook used the same narrow report-final predicate, so hook behavior
and manual `check_run.py` could miss retrospective-only closure claims.

3. The `/loop` closure protocol did not make scheduled-loop cancellation a
verified artifact. It needed an explicit same-turn CronDelete step, followed by
a recorded `loop_journal end` note naming the cancelled job or stating none.

4. Statusline freshness depended on derived caches that the driver did not keep
refreshed reliably during this run. The statusline correctly stayed read-only,
but the loop protocol needed a stronger per-cycle cache refresh habit.

5. Review records were allowed to grow stale after evidence/report state
changed. Closure must treat stale `EvidenceIndexHash` as invalid review, not as
historical comfort.

## Product Coverage

| Product | Instances | Findings | Severity |
|---------|-----------|----------|----------|
| SimMAGIC Reg | 1 | 7 | CRITICAL (IDOR chain) |
| Hamastar CMS v4.5 WebForms | 2 | 6 | MEDIUM (CAPTCHA bypass) |
| Hamastar CMS MVC | 1 | 3 | MEDIUM (TestLogin bypass) |
| Magic Modules CMS | 2 | 2 | MEDIUM (SPA pre-auth) |
| Custom apps (jobooks, auden-esgp, ylweb) | 3 | 1 | INFO |
| Unreachable (apc-magicweb, fubonweb, jobooks-mgr, ebooks) | 4 | 0 | DEFERRED (0/3) |

## Lessons

1. SimMAGIC has no tenant isolation — complete security model failure.
2. MVC CMS variant is LESS secure than WebForms (no CAPTCHA, no lockout).
3. Client-cookie CAPTCHA pattern should be added to knowledge/hamastar-cms.md.
4. The operator feedback items above are not enough by themselves; they must be
enforced through tool gates, run-file state, and review records.

## Closure

Not closed. Current required repair before any new FINAL/GHOST_COMPLETE claim:

- Write a real `report.md` or explicitly keep the run non-final.
- Resolve coverage matrix gaps or record structured, evidence-backed waivers.
- Re-adjudicate open/deferred fronts against current `loop_state.py` blockers.
- Refresh stale independent review after evidence/report changes.
- Rerun `check_run.py`, `check_run.py --replay-verify` when proxy dependencies are
  available, and peer review before any closure marker.
