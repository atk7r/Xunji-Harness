# sentinel — runtime behavior monitor (Phase 1, observe-only)

A behavioral-detection layer for the autonomous red-team driver. Instead of
matching single commands (brittle, evadable), it reconstructs the agent's
**action trace** from Claude Code hooks and runs deterministic detectors keyed
off the run ledger. **Phase 1 is OBSERVE-ONLY: it never blocks** — it records
behavioral alerts + a risk score so the operator can judge precision before any
inline enforcement is enabled.

This is a *detection* layer, not a boundary. It complements (does not replace):
- `.claude/hooks/safety_gate.py` — static effect backstop (fail-CLOSED, a boundary).
- OS-level isolation (WSL2 bubblewrap sandbox) — the real enforcement boundary.

Sentinel itself **fails OPEN**: detection must never break the workflow.

## What it answers: "my cleanup vs behavior to detect"

Every action is attributed on two non-spoofable axes (never the agent's self-report):

- **locus** — `LOCAL_WORKSPACE` (repo/tmp/.git, or a local-repo verb like `git`) /
  `TARGET` (a host or URL) / `LOCAL_OTHER` (system/home paths) / `UNKNOWN`.
- **provenance** — `OPERATOR_DIRECTED` (matches your prompt / a `hints.md` HINT,
  keyword) / `PLAN_DERIVED` (in-scope host or matches frontier/decisions) /
  `TARGET_DERIVED` (from tainted target content — Phase 2) / `UNATTRIBUTED`.

Routing → three lanes:
- **housekeeping** = local-workspace + operator/plan attributed → allow + audit
  (your `rm -rf runs/old`, `git filter-repo` when you asked → no alert).
- **scrutiny** = target / target-derived / unattributed-destructive → run detectors.
- **pass** = plain local recon → allow.

Your own deletes run in your **own terminal** never reach the hooks at all.

## Four-level autonomy model

Every action → `(level, decision)` from six axes: **effect category × reversibility ×
locus × provenance × scope × confidence**. FAIL-SAFE: on doubt escalate UP — never
silently auto; L4 never downgrades.

| level | decision | who judges | content | recorded to |
|---|---|---|---|---|
| **L1** | `AUTO` | machine (unattended) | reversible proof/recon (injection diff, version/db, `;id`, `/etc/passwd`, blind, harmless upload), in-scope, attributed | trace only |
| **L2** | `NOTIFY` | machine + audit | **reversible** but noteworthy: cumulative volume, **teardown of self-created artifact** (own `docker rm`) | `runs/<t>/alerts.md` (audit) |
| **L3** | `GATE` | operator (red-team) | **irreversible** but legitimate: shell / persist / privesc / ACL / write / exploit / **infra teardown of unknown** / **credential read** (`/etc/shadow`,`id_rsa`,`.aws/credentials`) / out-of-scope | `runs/<t>/pending_approval.md` |
| **L4** | `BLOCK` | nobody (never auto) | irreversible harm-as-purpose: 拖库 (`--dump`/mysqldump), DoS, money, destruction (`rm -rf`/`DROP`/`TRUNCATE`/wipe/`vssadmin delete`) | `runs/<t>/alerts.md` (hard) |
| (floor) | *never author* | — | ransomware / wipers / worms / supply-chain (harm-as-purpose payloads) | — |

Key splits (why 4 not 3): **reversible-noteworthy (L2 NOTIFY, just audit) vs
irreversible (L3 GATE, must ask)** — the soft reminder belongs only at L2. And
**self-created infra teardown (L2 cleanup) vs unknown/target resource (L3/L4)** via
the artifact registry — "clean up what you created."

Orthogonal axis — **scope**: an out-of-scope target forces at least `GATE`.
Mapping to live layers: `safety_gate.py` hard-blocks L4 (the enforcer; `sentinel`
labels). **Observe-only: nothing is enforced** — decisions are recorded so you can
validate the L1/L2/L3 boundary precision before flipping high-confidence to inline.

When unattended: L1/L2 run alone (L2 audited); **L3 is queued** (`pending_approval.md`
— the agent authored it, you review async / author-and-handoff); L4 is hard-blocked.

## Detectors (Phase 1, deterministic)

| detector | fires when | would→ |
|---|---|---|
| `scope_drift` | TARGET action against a host not in engagement scope | deny |
| `effect_escalation` | deeper/destructive effect on target, not operator-authorized | ask |
| `exfil_rate` | session-cumulative egress / requests / auth-fails over threshold | alert |
| `plan_deviation` | unattributed side-effecting action (off-script / possible hijack) | alert |
| `injection_observed` (Phase 2) | an UNTRUSTED target response carries agent-manipulation content → taint hot; next effectful/correlated action becomes `TARGET_DERIVED` (escalated) | alert |

In observe-only the `would→` is recorded but **not enforced**. Findings go to
`runs/<target>/alerts.md` with a running session risk score.

## Session circuit breaker (Part B)

Per-action detectors can't see **aggregate** runaway — each command looks fine,
the *pattern* is the problem. The breaker trips on three session-level signals:

- **T1 hijack-streak** — N consecutive effectful actions while target-content
  taint is hot (the lethal-trifecta guard).
- **T2 risk-accumulation** — cumulative `risk_score` crosses a ceiling.
- **T3 escalation-streak** — repeated `high` scope/effect-escalation findings.

On trip it is **escalate-not-kill**: effectful `AUTO` decisions are clamped to
`GATE` (queued in `pending_approval.md`) and one loud `CIRCUIT-BREAKER TRIPPED`
alert fires; proof / recon / operator-housekeeping keep flowing. It clears on
cooldown, on taint cool-down, or on an operator `reset breaker` / `解除熔断`
`hints.md` directive (highest authority). Thresholds + clamp rules:
[`TUNING.md`](TUNING.md) §2.

**Axes feeding the decision**: effect category, **reversibility** (`is_reversible` —
read=reversible→may NOTIFY; write/exec=irreversible→floor GATE), **locus** + **provenance**
(incl. `hints.md` pure-directive authorization + `TARGET_DERIVED` taint), **scope**,
**own-artifact registry** (`docker run --name …` recorded → own teardown = NOTIFY cleanup).

## Files

- `classifier.py` — locus + provenance attribution (keyword-based, Phase 1)
- `detectors.py` — effect tiering + the 4 detectors
- `monitor.py` — `assess()` pure core + `handle_event()` hook dispatcher (observe-only)
- `state.py` — cross-process session state (`.state/sentinel/`) + run-ledger access
- `hook.py` — Claude Code hook entry (Pre/Post/UserPromptSubmit/SessionStart), UTF-8 stdin
- `replay.py` — golden replay regression test (`python sentinel/replay.py`)
- `verify_layers.py` — L1–L4 FP + effectiveness + breaker over-clamp guard
- `TUNING.md` — every threshold (detectors + circuit breaker), with re-test steps

Wired in `.claude/settings.json` for SessionStart / PreToolUse / PostToolUse /
UserPromptSubmit (matcher `Bash`). State + alerts are under gitignored paths.

## Run the tests

```
python sentinel/replay.py      # golden cases: 4-level decision + detectors + hints + injection + breaker
python sentinel/verify_layers.py   # FP guard + effectiveness + breaker over-clamp guard
```

## Roadmap

- **Phase 2 (done, observe-only)**: target-content taint — injection-signature detection
  on untrusted responses → `TARGET_DERIVED` escalation (anti-hijack). Still keyword-grade;
  a continuous LLM auditor sub-agent + semantic attribution remain future.
- Phase 3: behavioral anomaly vs learned baseline (TraceAegis) + probabilistic risk
  prediction (ProbGuard).
- **Flip to inline** (deny/ask·queue) for high-confidence GATE/BLOCK once real-traffic
  `alerts.md` shows L3/L4 are never misclassified as L1. Until then: observe-only.
- **Deferred (needs operator nod, touches the hard boundary)**: move infra teardown from
  `safety_gate` L4-hard to L3 native-ask. NOT done — blanket removal would un-hard-block
  TARGET-resource destruction (locus-blind). Operator tears down own infra in their own
  terminal today (ungated); sentinel already LABELS own-artifact teardown as L2 cleanup.

Grounding: AgentArmor (trace-as-program), CaMeL (control/data-flow provenance),
ProbGuard (risk-threshold monitoring), TraceAegis (behavioral anomaly).
