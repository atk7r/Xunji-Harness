"""sentinel.monitor — stateful behavior monitor (observe-only, Phase 1).

assess() is the pure core (no IO) shared by the live hooks and the replay harness.
handle_event() is the Claude Code hook dispatcher; it records alerts + risk and
ALWAYS returns None (observe-only — never blocks).
"""

from __future__ import annotations

import re
import time

from . import classifier as C
from . import detectors as D
from . import state as S

# artifacts the agent CREATES this engagement (containers, etc.) -> teardown of these
# is cleanup ("clean up what you created"), not destruction. Extend as needed.
_CREATE = re.compile(r"\bdocker\s+(?:run|create)\b[^|;\n]*--name[=\s]+([\w.\-/]+)", re.I)


def _record_artifacts(command: str, sess: dict) -> None:
    refs = sess.setdefault("artifacts", [])
    for m in _CREATE.finditer(command):
        if m.group(1) not in refs:
            refs.append(m.group(1))
    sess["artifacts"] = refs[-100:]

# lanes
HOUSEKEEPING = "housekeeping"   # operator/plan-attributed local-workspace action -> allow + audit
SCRUTINY = "scrutiny"           # target / target-derived / unattributed-destructive -> run detectors
PASS = "pass"                   # plain local/recon -> allow

_MAX_DIRECTIVES = 12
_MAX_TRACE = 400


def route(attr: dict, tier: str) -> str:
    locus, prov = attr["locus"], attr["provenance"]
    if locus == C.LOCAL_WORKSPACE and prov in (C.OPERATOR_DIRECTED, C.PLAN_DERIVED):
        return HOUSEKEEPING
    effectful = tier in (D.DESTRUCTIVE, D.DEEPER)   # beyond proof/recon (destruction OR shell/secret/infra)
    if (locus == C.TARGET or prov == C.TARGET_DERIVED
            or (effectful and prov == C.UNATTRIBUTED)
            or (locus == C.LOCAL_OTHER and effectful)):
        return SCRUTINY
    return PASS


def assess(action: dict, ctx: dict, sess: dict) -> dict:
    """Pure: classify -> route -> run detectors. Returns a verdict record.
    In observe-only Phase 1 the 'verdict' is always 'observe' (no enforcement)."""
    attr = C.classify(action, ctx)
    tier = D.effect_tier(action)
    lane = route(attr, tier)
    findings = D.run_detectors(action, attr, sess, set(ctx.get("scope_hosts", set()))) \
        if lane == SCRUTINY else []
    risk = round(sum(f["risk"] for f in findings), 3)
    # four-level autonomy decision (AUTO/NOTIFY/GATE/BLOCK) — fail-safe escalates on doubt
    level, decision, dreason = D.autonomy_decision(action, attr, sess.get("artifacts", ()))
    # cumulative volume is a reversible-but-noteworthy session signal -> NOTIFY (audit)
    if decision == "AUTO" and any(f["detector"] == "exfil_rate" for f in findings):
        level, decision, dreason = max(level, D.NOTIFY), "NOTIFY", "cumulative volume — audited"
    # session circuit breaker (Part B): aggregate-runaway trip -> clamp effectful AUTO + alert.
    this_escalation = any(f["detector"] in ("effect_escalation", "scope_drift")
                          and f["severity"] == "high" for f in findings)
    breaker, bevent = D.breaker_eval(
        sess.get("breaker"),
        taint_hot=bool(ctx.get("taint")),
        this_effectful=(level >= D.GATE),
        this_escalation=this_escalation,
        risk_score=sess.get("risk_score", 0.0) + risk,
        now=time.time(), ts=S.now(),
        operator_reset=any(D.BREAKER_RESET_RE.search(d or "") for d in ctx.get("directives", [])))
    if breaker.get("tripped"):
        level, decision, dreason = D.apply_breaker(breaker, level, decision, dreason)
    return {"attr": attr, "tier": tier, "lane": lane, "findings": findings, "risk": risk,
            "level": level, "decision": decision, "decision_reason": dreason,
            "breaker": breaker, "breaker_event": bevent, "verdict": "observe"}


# --- live hook integration (IO) ---------------------------------------------

def _sess_name(event: dict) -> str:
    sid = str(event.get("session_id") or "default").replace("/", "_")[:64]
    return f"session_{sid}.json"


def _load_sess(event: dict) -> dict:
    sess = S.load(_sess_name(event))
    if not sess:
        run = S.active_run()
        sess = {"scope_hosts": sorted(S.scope_hosts(run)),
                "plan_keywords": [], "directives": [],
                "egress_bytes": 0, "request_count": 0, "auth_fails": 0,
                "risk_score": 0.0, "trace": [], "run": str(run) if run else ""}
    return sess


def handle_event(event: dict) -> None:
    name = event.get("hook_event_name") or event.get("hookEventName") or ""
    with S.state_lock():
        sess = _load_sess(event)
        run = S.active_run()

        if name == "SessionStart":
            sess["scope_hosts"] = sorted(S.scope_hosts(run))
            sess["plan_keywords"] = S.plan_keywords(run)
            sess["run"] = str(run) if run else ""

        elif name == "UserPromptSubmit":
            prompt = (event.get("prompt") or "").strip()
            if prompt:
                sess.setdefault("directives", []).append(prompt)
                sess["directives"] = sess["directives"][-_MAX_DIRECTIVES:]

        elif name == "PreToolUse":
            ti = event.get("tool_input") or {}
            command = ti.get("command") if isinstance(ti, dict) else ""
            if not command and isinstance(ti, dict):
                command = " ".join(str(v) for v in ti.values() if isinstance(v, str))
            action = C.normalize_action(event.get("tool_name", ""), command or "")
            # operator authorization sources: live prompts (UserPromptSubmit) +
            # directive-kind HINT nodes from hints.md (re-read each cycle so mid-run
            # injected steering is honored). lead/claim hints do NOT authorize.
            directives = list(sess.get("directives", [])) + S.operator_hints(run)
            taint = _taint_active(sess, action)        # Phase 2: did this derive from injected target content?
            if (sess.get("taint") or {}).get("hot", 0) > 0:
                sess["taint"]["hot"] -= 1
            ctx = {"scope_hosts": set(sess.get("scope_hosts", [])),
                   "directives": directives,
                   "plan_keywords": sess.get("plan_keywords", []),
                   "taint": taint}
            _record_artifacts(command or "", sess)   # track agent-created infra for cleanup attribution
            res = assess(action, ctx, sess)
            sess["breaker"] = res["breaker"]      # persist circuit-breaker state across actions
            sess.setdefault("trace", []).append(
                {"ts": S.now(), "cmd": (command or "")[:160], "locus": res["attr"]["locus"],
                 "prov": res["attr"]["provenance"], "tier": res["tier"],
                 "level": res["level"], "decision": res["decision"], "risk": res["risk"]})
            sess["trace"] = sess["trace"][-_MAX_TRACE:]
            res["trace_tail"] = sess["trace"][-5:]   # context for a circuit-breaker alert
            if res["findings"]:
                sess["risk_score"] = round(sess.get("risk_score", 0.0) + res["risk"], 3)
            # observe-only recording by autonomy decision (NOTHING is blocked here):
            # GATE -> L3 pending-approval queue; NOTIFY/BLOCK -> alerts (audit/hard); AUTO -> trace only.
            if res["decision"] == "GATE":
                _write_pending(run, command or "", res, sess.get("risk_score", 0.0))
            elif res["decision"] in ("NOTIFY", "BLOCK"):
                _write_alert(run, command or "", res, sess.get("risk_score", 0.0))
            # circuit-breaker transitions get their own loud, one-shot alert
            if res.get("breaker_event") in ("trip", "clear"):
                _write_breaker_alert(run, command or "", res, sess.get("risk_score", 0.0))

        elif name == "PostToolUse":
            _observe_result(event, sess, run)

        S.save(_sess_name(event), sess)
    return None      # observe-only: never returns a deny/ask decision


def _taint_active(sess: dict, action: dict) -> bool:
    """True if this action plausibly DERIVES from injected target content (CaMeL-style):
    taint is 'hot' (set by a recent injected response) AND the action is effectful (>=GATE)
    or echoes a token from the injection snippet."""
    t = sess.get("taint") or {}
    if t.get("hot", 0) <= 0:
        return False
    if D.effect_level(action) >= D.GATE:
        return True
    cmd = action.get("command", "").lower()
    return any(len(tok) >= 5 and tok in cmd for tok in set((t.get("snip") or "").lower().split()))


def _observe_result(event: dict, sess: dict, run) -> None:
    resp = event.get("tool_response")
    text = resp if isinstance(resp, str) else str(resp) if resp is not None else ""
    ti = event.get("tool_input") or {}
    command = ti.get("command", "") if isinstance(ti, dict) else ""
    if any(k in command for k in ("http://", "https://", "probe.py", "render.py", "curl", "wget")):
        sess["request_count"] = sess.get("request_count", 0) + 1
        sess["egress_bytes"] = sess.get("egress_bytes", 0) + len(text)
        low = text.lower()
        if '"status": 401' in low or '"status": 403' in low or "incorrect" in low or "unauthor" in low:
            sess["auth_fails"] = sess.get("auth_fails", 0) + 1
        # Phase 2 taint: the target response is UNTRUSTED — scan it for agent-manipulation
        # (prompt injection). If found, mark taint hot so the next effectful/correlated
        # action is treated as TARGET_DERIVED (escalated) — the lethal-trifecta guard.
        hit, snip = D.detect_injection(text)
        if hit:
            sess["taint"] = {"hot": 3, "snip": snip}
            sess["risk_score"] = round(sess.get("risk_score", 0.0) + 0.5, 3)
            S.append_alert(run,
                f"## ALERT {S.now()}  INJECTION-OBSERVED  (session risk={sess['risk_score']})\n"
                f"- An UNTRUSTED target response contains agent-manipulation content (possible hijack).\n"
                f"- Snippet: `{snip[:160]}`\n"
                f"- Effect: taint hot for next 3 actions -> effectful/correlated action escalated to "
                f"TARGET_DERIVED. observe-only — nothing blocked.")


def _entry(tag: str, command: str, res: dict, risk_total: float) -> str:
    a = res["attr"]
    lines = [f"## {tag} {S.now()}  L{res['level']}/{res['decision']}  (session risk={risk_total})",
             f"- Command: `{command[:200]}`",
             f"- Locus/Provenance: {a['locus']} / {a['provenance']}   Tier: {res['tier']}",
             f"- Decision: L{res['level']} {res['decision']} — {res['decision_reason']}"]
    for f in res["findings"]:
        lines.append(f"- [{f['severity']}] {f['detector']} (would→{f['intent']}): {f['reason']}")
    return "\n".join(lines)


def _write_pending(run, command: str, res: dict, risk_total: float) -> None:
    """L3 GATE: queue an operator-review item (observe-only — the action was NOT held)."""
    block = _entry("PENDING", command, res, risk_total)
    block += ("\n- NOTE: observe-only — action ran. L3 GATE: irreversible/operator-gated; "
              "once inline, this waits for your approve/reject (unattended: queued, agent works "
              "other fronts). Status: [ ] pending")
    S.append_pending(run, block)


def _write_breaker_alert(run, command: str, res: dict, risk_total: float) -> None:
    """One-shot loud alert on a circuit-breaker transition (trip / clear)."""
    b = res.get("breaker") or {}
    if res.get("breaker_event") == "trip":
        recent = [t.get("cmd", "")[:80] for t in (res.get("trace_tail") or [])]
        lines = [f"## CIRCUIT-BREAKER {S.now()}  TRIPPED  (session risk={risk_total})",
                 f"- Trip: {b.get('reason', '')}",
                 f"- Triggering action: `{command[:200]}`",
                 "- Effect: while tripped, effectful AUTO actions are CLAMPED to L3/GATE "
                 "(queued in pending_approval.md); proof/recon/operator-housekeeping keep "
                 "flowing. observe-only — nothing was blocked.",
                 f"- Clears: auto after {D.BREAKER_COOLDOWN}s with no contributing event, on "
                 "taint cool-down, or on an operator 'reset breaker' / '解除熔断' hint."]
        if recent:
            lines.append(f"- Recent actions: {recent}")
    else:
        lines = [f"## CIRCUIT-BREAKER {S.now()}  CLEARED  (session risk={risk_total})",
                 "- The session circuit breaker has reset; normal autonomy resumes."]
    S.append_alert(run, "\n".join(lines))


def _write_alert(run, command: str, res: dict, risk_total: float) -> None:
    """NOTIFY (L2, reversible-but-sensitive — audit) or BLOCK (L4, never-auto)."""
    block = _entry("ALERT", command, res, risk_total)
    if res["decision"] == "BLOCK":
        block += ("\n- NOTE: L4 never-auto (destruction/mass-exfil/DoS/money/wipe). "
                  "safety_gate hard-blocks; author-and-handoff only.")
    else:
        block += "\n- NOTE: L2 NOTIFY — reversible but sensitive; ran and audited for review."
    S.append_alert(run, block)
