# sentinel — tuning & thresholds

Every tunable in the behavior layer, what it catches, and what moving it costs.
Sentinel is **observe-only**: changing these changes what gets *recorded / clamped*,
never what is *blocked* (the hard block is `safety_gate.py`). Defaults are
deliberately loose — the goal is to catch aggregate runaway, not to nag.

After changing any value here, re-run both:

```
python sentinel/replay.py          # golden regression (lane + detectors + decision + breaker)
python sentinel/verify_layers.py   # FP guard + effectiveness + breaker over-clamp guard
```

---

## 1. Per-action detector thresholds (`detectors.py`)

Cumulative session signals that raise a `Finding` (each adds `risk` to the
session `risk_score`). All are session-scoped (reset per session file).

| Constant | Default | Fires | Lower it if… | Raise it if… |
|---|---|---|---|---|
| `EGRESS_WARN` | 2 MB | cumulative retained response bytes | you want earlier exfil/over-pull notice | a legitimately data-heavy engagement keeps flagging |
| `REQS_WARN` | 300 | cumulative requests this session | long quiet recon should still be noticed sooner | a big-but-legit sweep is noisy |
| `AUTHFAIL_WARN` | 8 | cumulative auth failures | you want earlier brute-pattern notice | a known weak-cred dictionary run is expected |

These are **soft** (a `med`/`low` Finding + risk, not a decision change on their
own). The exception: cumulative volume bumps an `AUTO` decision to `NOTIFY`
(audited) in `monitor.assess`.

Note the separation from `guard.py`: `guard.py` *enforces* speed/volume at the
tool layer (it can actually abort); these `*_WARN` values only *observe*. The
real brute-force throttle is `RateLimiter` (per-host 1 rps), not a count — see
`tools/harness/guard.py` and [[hard-boundary-only-irreversible-harm]].

---

## 2. Session circuit breaker — Part B (`detectors.py`)

Aggregate-runaway trip that no per-command gate can see. On trip it **clamps
effectful `AUTO` decisions down to `GATE`** (queued in `pending_approval.md`) and
fires one loud alert. Escalate-not-kill: proof / recon / operator-housekeeping
keep flowing, so a real engagement is never halted. Still observe-only in Phase 1.

| Constant | Default | Trip condition (T) | Notes |
|---|---|---|---|
| `BREAKER_HIJACK_STREAK` | 2 | **T1** N consecutive *effectful* actions while target-content taint is hot (under hot taint a taint-correlated action is forced ≥GATE, so any such action counts as effectful) | the lethal-trifecta guard; the most important one |
| `BREAKER_RISK_TRIP` | 3.0 | **T2** cumulative `risk_score` ≥ this | a snowball of findings (≈ many `high` detectors) |
| `BREAKER_ESCALATION_TRIP` | 3 | **T3** cumulative `high` scope/effect-escalation findings since last clear | repeated beyond-proof / out-of-scope attempts |
| `BREAKER_COOLDOWN` | 600 s | — | idle time with no contributing event → auto-clear |

**Trip is the max-sensitivity axis; clamp is the blunt one.** If you want the
breaker to engage sooner, lower `BREAKER_HIJACK_STREAK` to 1 (trips on the *first*
effectful action under hot taint) or `BREAKER_RISK_TRIP` toward ~1.5. If a long
authorized deep-exploitation session keeps tripping T2, raise `BREAKER_RISK_TRIP`
or shorten what counts toward it (the §1 detectors).

### Clearing a tripped breaker
1. **Auto-cooldown** — `BREAKER_COOLDOWN` seconds with no new contributing event.
2. **Taint cool-down** — T1 trips relax once `taint.hot` reaches 0 (set in
   `monitor._observe_result`, decays over 3 actions).
3. **Operator override (highest authority)** — a `hints.md` `## HINT-xxx` of
   `Kind: directive` whose text matches `BREAKER_RESET_RE`
   (`reset breaker` / `clear breaker` / `解除熔断` / `重置熔断`) clears it
   immediately. This is the intended manual escape hatch — see CLAUDE.md
   "Operator Authority" and `docs/WORKFLOW.md` hints.md.

### What the clamp does / does not touch
- **Clamped**: a decision that *would* be `AUTO` with `level ≥ GATE` (an effectful
  action silently running) → forced to `GATE` / `pending_approval.md`.
- **Untouched**: `level < GATE` (proof / recon / local housekeeping) keeps `AUTO`;
  already-escalated `NOTIFY` / `GATE` / `BLOCK` are left as-is. The breaker never
  *down*grades and never pushes anything to `BLOCK` (verified by
  `verify_layers.breaker_no_overclamp`).

---

## 3. Per-run overrides

There is no per-run config file yet; to override for a single engagement, edit the
constant (it is read live each cycle) and revert after, or raise it through a code
change in `detectors.py`. A `runs/<target>/sentinel.json` override loader is a
candidate for a later phase if per-engagement tuning becomes routine.

---

## 4. Not here (enforced elsewhere)

- **Irreversible-harm hard block** — `.claude/hooks/safety_gate.py` +
  `safety_rules.json`. Never tuned for sensitivity; it is the floor.
- **Tool-layer rate / body / auth-runaway / host-backoff** —
  `tools/harness/guard.py` (`GLOBAL_MAX_RPS`, `PER_HOST_MAX_RPS`,
  `MAX_BODY_BYTES`, `AUTH_FAIL_LOCK`, `HOST_ERR_THRESHOLD`, `SESSION_WARN_COUNT`).
  These *enforce* (they can abort a tool); the §1–§2 values only *observe*.

### Part A — whole-session volume breaker (`guard.py`, enforcing)

`SessionBudget` is now a real tool-layer circuit breaker (not just soft-warn):
`probe.py` calls `check()` before each request and `record(nbytes)` after. When
the sliding-window request count OR retained-egress bytes cross a hard ceiling it
arms a cooldown; `check()` then raises `SessionTripped` (subclass of
`RateBudgetExceeded`) and the tool aborts instead of continuing the flood. This is
the GLOBAL (cross-host) counterpart to the per-host `HostHealth`/`HostBackoff`.

| Constant | Default | Trips on | Raise it if… |
|---|---|---|---|
| `SESSION_WARN_COUNT` | 200 | soft warn only (no abort) | noisy on a legit big sweep |
| `SESSION_TRIP_COUNT` | 800 | window request count → abort | a legitimately large authorized sweep |
| `SESSION_TRIP_BYTES` | 16 MB | window response bytes over the wire (pre-cap, not the 256KB-capped retained body) → abort | a data-heavy but authorized engagement |
| `SESSION_TRIP_COOLDOWN` | 300 s | armed-cooldown duration | — |
| `SESSION_WINDOW_SEC` | 600 s | sliding window for both | — |

Per-run override: raise the constant (read live), or construct
`SessionBudget(trip_count=…, trip_bytes=…)`. Self-test (isolated state, no live
pollution): `python tools/harness/guard.py`.
