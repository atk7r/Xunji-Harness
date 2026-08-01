"""sentinel.detectors — effect classification + the 4 deterministic Phase-1
behavioral detectors. Each returns Findings; in observe-only mode the recorded
`intent` (deny/ask/alert) is what a later inline phase WOULD do, but Phase 1
never enforces — it only logs + scores risk.
"""

from __future__ import annotations

import re

from . import classifier as C

# effect tiers
RECON = "recon"
PROOF = "proof"
DEEPER = "deeper"          # exfil / shell / bulk extraction
DESTRUCTIVE = "destructive"

_SQL_TRUNCATE_PATTERN = (
    r"(?:\btruncate\s+table\s+[`\"\[]?[A-Za-z_][\w.$-]*|"
    r"(?:^|[;&|]\s*)(?:\S*/)?(?:mysql|psql|sqlcmd|sqlite3|duckdb|mariadb)\b"
    r"[^|;\n]{0,240}\btruncate\s+(?:table\s+)?[`\"\[]?[A-Za-z_][\w.$-]*)"
)

_DESTRUCTIVE = re.compile(
    r"\brm\s+(?:-[a-z]*r[a-z]*|--recursive\b)|"
    r"\bdd\s+if=|\bmkfs\b|\bformat\s+[a-z]:|"
    r"\bdrop\s+(database|table|schema)\b|" + _SQL_TRUNCATE_PATTERN + r"|"
    r"\bdelete\s+from\b(?!.*\bwhere\b)|\b(flushall|flushdb)\b|\.drop\s*\(", re.I)
# DEEPER = effects BEYOND the proof ceiling (operator-gated by 证明即止): bulk data
# extraction (拖库), interactive/persistent shell, privesc, or retrieval of real
# secrets. NOT the proof-level payloads below — those are PROOF and run free.
_DEEPER = re.compile(
    r"--dump\b|--os-shell|--os-cmd|--os-pwn|\bmysqldump\b|\bpg_dump|\bmongodump\b|"
    r"into\s+(?:outfile|dumpfile)|--file-write|"                  # bulk extraction / file write
    r"\bnc\s+-[a-z]*e\b|/dev/tcp/|\bbash\s+-i\b|\bsh\s+-i\b|"     # interactive / reverse shell
    r"\bmsfvenom\b|meterpreter|\bgetshell\b|webshell|"            # shell / persistence tooling
    r"/etc/shadow|\bid_rsa\b|\.ssh/|\.aws/credentials|/\.git-credentials",  # secret over-reach
    re.I)
# PROOF = necessary, free, proof-level payloads — these must NOT be flagged: an
# injection differential, version/db read, single id/whoami, /etc/passwd LFI proof,
# SSTI eval, a benign XSS marker, a boolean/time probe.
_PROOF = re.compile(
    r"union\s+select|';|'\s+(and|or)\s|sleep\s*\(|\bbenchmark\s*\(|version\s*\(|database\s*\(|"
    r"/etc/passwd|<script|onerror=|\$\{|\.\./\.\.|;\s*id\b|;\s*whoami\b|\|\s*id\b|\|\s*whoami\b", re.I)


def effect_tier(action: dict) -> str:
    """Coarse tier label for lane routing + detectors. Kept CONSISTENT with
    effect_level() — same patterns, same order — so lane never disagrees with the
    autonomy decision (bug 2026-06-14: vssadmin was tier=recon but level=BLOCK)."""
    cmd = action.get("command", "")
    if _INFRA.search(cmd):
        return DEEPER
    if _BLOCK.search(cmd):
        return DESTRUCTIVE
    if _GATE.search(cmd):
        return DEEPER
    if _PROOF.search(cmd):
        return PROOF
    return RECON


# --- four-level autonomy model (AUTO / NOTIFY / GATE / BLOCK) -------------------
# L1 AUTO   = unattended-auto: reversible proof/recon, in-scope, attributed.
# L2 NOTIFY = reversible-but-sensitive (secret read, scope-edge, cumulative volume):
#             runs, but audited (the soft reminder — appropriate ONLY because reversible).
# L3 GATE   = irreversible BUT legitimate (shell/persist/privesc/ACL/write/exploit/
#             infra-teardown / cleanup): operator-gated — ask (attended) / queue (unattended).
# L4 BLOCK  = irreversible harm-as-purpose / target destruction (拖库/DoS/money/wipe):
#             never auto. safety_gate is the enforcer; sentinel LABELS. author-and-handoff only.
# (Above L4, a non-runtime AUTHORING floor: never author ransomware/wipers/worms.)
AUTO, NOTIFY, GATE, BLOCK = 1, 2, 3, 4
LNAME = {AUTO: "AUTO", NOTIFY: "NOTIFY", GATE: "GATE", BLOCK: "BLOCK"}

# L4 — harm-as-purpose / target destruction (kept comprehensive, mirrors the
# safety_gate hard categories; safety_gate.py remains the actual enforcer).
_BLOCK = re.compile(
    r"\brm\s+(?:-[a-z]*r[a-z]*|--recursive\b)|"
    r"\bdd\s+if=|\bmkfs\b|\bformat\s+[a-z]:|>\s*/dev/sd|:\(\)\s*\{|"
    r"\b(?:shutdown|reboot|halt|poweroff)\b|"
    r"\bdrop\s+(?:database|table|schema|user|role|index|view|trigger)\b|" + _SQL_TRUNCATE_PATTERN + r"|"
    r"\bdelete\s+from\b(?!.*\bwhere\b)|\bupdate\s+\w+\s+set\b(?!.*\bwhere\b)|"
    r"\balter\s+table\b[^|;\n]*\bdrop\b|\b(?:flushall|flushdb)\b|"
    r"\b(?:dropdatabase|dropcollection)\s*\(|\.drop\s*\(\s*\)|deletemany\s*\(\s*\{\s*\}|"
    r"\bfind\b[^|;\n]*\s-delete\b|\bfind\b[^|;\n]*-exec\s+rm\b|"                       # destruction
    r"--dump\b|\bmysqldump\b|\bpg_dump|\bmongodump\b|into\s+(?:outfile|dumpfile)|"     # mass-exfil 拖库
    r"\bmasscan\b|--flood\b|--min-rate\s*[1-9]\d{3,}|\b(?:slowloris|t50|mhddos|goldeneye|loic|hoic|hulk)\b|"  # DoS
    r"\bdd\b[^|;\n]*\bof=\s*/dev/(?:sd|nvme|vd|hd|mapper|disk)|"                         # raw disk write
    r"\b(?:vssadmin|wbadmin)\b[^|;\n]*\bdelete\b|\bwmic\b[^|;\n]*shadowcopy[^|;\n]*\bdelete\b|"  # backup/shadow wipe
    r"\bshred\b|\bsdelete\b|\bcipher\s+/w|\bwipefs\b|\bblkdiscard\b|\bscrub\b|"          # secure-wipe destruction
    r"(?:-X\s*(?:POST|PUT|PATCH)|--data\b)[^|;\n]*\b(?:transfer|withdraw|remit|refund|payout|settle)\b",  # money
    re.I)
# L3 — irreversible (or high-value) but legitimate: shell / persist / privesc / ACL /
# write / exploit, plus CREDENTIAL reads (grabbing usable secrets is extraction beyond
# proof -> operator review, not silent audit).
_GATE = re.compile(
    r"\bnc\s+-[a-z]*e\b|/dev/tcp/|\bbash\s+-i\b|\bsh\s+-i\b|\bmsfvenom\b|meterpreter|"
    r"\bgetshell\b|webshell|--os-shell|--os-cmd|--os-pwn|--file-write|"
    r"\bchmod\b|\bchown\b|\bsetfacl\b|attach-user-policy|set-role|"
    r"/etc/shadow|\bid_rsa\b|\.ssh/|\.aws/credentials|/\.git-credentials", re.I)  # credential over-reach
# infra / resource teardown — operator-gated. Cleanup of self-created artifacts is
# still a state-changing cleanup action and remains GATE, not NOTIFY.
_INFRA = re.compile(
    r"\bdocker\s+(?:rm|rmi|stop|kill|volume\s+rm|system\s+prune)\b|"
    r"\bterraform\s+destroy\b|\bkubectl\s+delete\b|\bhelm\s+(?:delete|uninstall)\b|"
    r"\baws\s+s3\s+rb\b|\b(?:aws|gcloud|az)\b[^|;\n]*\bdelete\b|terminate-instances|"
    r"(?:-X|--request)\s*['\"]?DELETE", re.I)
# irreversibility markers (clear state changes / writes to system paths) -> floor to GATE
_IRREVERSIBLE = re.compile(
    r"\brm\b|\bmv\s|\bchmod\b|\bchown\b|\binsert\s+into\b|\bupdate\s+\w+\s+set\b|"
    r"\bcreate\s+(?:table|user)\b|--os-shell|webshell|\bnc\s+-[a-z]*e\b|\bbash\s+-i\b|"
    r"\bdocker\s+(?:rm|stop|kill)\b|\bterraform\s+destroy\b|\bkubectl\s+delete\b|"
    r">\s*/(?:var|etc|usr|bin|lib|opt|srv|home|root)/", re.I)


# --- Phase 2: target-content taint (anti-hijack) -------------------------------
# Prompt-injection / agent-manipulation signatures that may appear in an untrusted
# TARGET response (a compromised/malicious target trying to hijack the driver).
# Deliberately matches manipulation-OF-THE-AGENT phrasing, not mere technical strings
# (so our own proof payloads echoed back — /etc/passwd, a <script> marker — don't fire).
_INJECTION = re.compile(
    r"ignore\s+(?:all\s+)?(?:the\s+)?(?:previous|above|prior)\s+(?:instructions?|prompts?|messages?)|"
    r"disregard\s+(?:all\s+)?(?:the\s+)?(?:previous|above|prior)|forget\s+(?:everything|all\s+previous)|"
    r"you\s+are\s+now\s+|\bnew\s+instructions?\s*:|\bsystem\s+prompt\b|"
    r"</?(?:system|assistant|important|instructions?)\b|"
    r"do\s+not\s+(?:tell|inform|alert|notify|report)\s+(?:the\s+)?(?:user|operator|human)|"
    r"\bas\s+an\s+ai\b[^.\n]{0,40}\byou\s+must\b|"
    r"please\s+(?:now\s+)?(?:run|execute|send|email|upload|delete|exfiltrat|curl|wget)\b",
    re.I)


def detect_injection(text: str) -> tuple[bool, str]:
    """Scan an (untrusted) target response for agent-manipulation content. Returns
    (hit, snippet)."""
    m = _INJECTION.search(text or "")
    if not m:
        return (False, "")
    s = text[max(0, m.start() - 16): m.end() + 48]
    return (True, " ".join(s.split()))


# plain file-deletion verbs — only these get the local-workspace GATE-cap; a
# ransomware/wipe/disk command (vssadmin/shred/dd...) is NEVER downgraded even if
# its switches (e.g. `/all /quiet`) get mis-parsed as repo-relative paths.
_PLAIN_DELETE = re.compile(r"\brm\b|\brmdir\b|\bdel\b", re.I)


def is_reversible(action: dict) -> bool:
    """A read/proof is reversible (no target state changed); a write/delete/exec is not.
    Reversibility is the axis that separates 'safe to NOTIFY' from 'must GATE'."""
    return not _IRREVERSIBLE.search(action.get("command", ""))


def effect_level(action: dict) -> int:
    cmd = action.get("command", "")
    if _INFRA.search(cmd):       # check before _BLOCK so 'docker rm -f' isn't read as rm-destroy
        return GATE
    if _BLOCK.search(cmd):
        return BLOCK
    if _GATE.search(cmd):
        return GATE
    return AUTO       # NOTIFY is produced by session signals (volume) / own-artifact cleanup, not by category


def autonomy_decision(action: dict, attr: dict, own_refs=()) -> tuple[int, str, str]:
    """(effect x reversibility x locus x provenance x scope x own-artifact) -> (level, decision, reason).
    Decision: AUTO / NOTIFY (run+audit) / GATE (ask·queue) / BLOCK (never).
    FAIL-SAFE: on doubt escalate UP — never silently auto. L4 never downgrades."""
    eff = effect_level(action)
    locus, prov = attr["locus"], attr["provenance"]
    hosts = action.get("hosts")
    cmd = action.get("command", "")

    # 1) housekeeping: operator/plan-attributed local-workspace -> AUTO (your cleanup / git).
    if locus == C.LOCAL_WORKSPACE and prov in (C.OPERATOR_DIRECTED, C.PLAN_DERIVED):
        return (AUTO, "AUTO", "operator/plan-attributed local housekeeping")

    # 2) own-artifact teardown/cleanup: legitimate, but state-changing. It is not
    #    harm-as-purpose, so it is GATE instead of BLOCK, but it still needs the
    #    operator to answer yes before execution.
    if eff == GATE and _INFRA.search(cmd) and any(r and r in cmd for r in own_refs):
        return (GATE, "GATE", "teardown/cleanup of self-created engagement artifact requires operator yes")

    # 3) hijack: derived from untrusted target content -> never auto.
    if prov == C.TARGET_DERIVED:
        return (max(eff, GATE), "BLOCK" if eff == BLOCK else "GATE",
                "derived from untrusted target content (possible injection)")

    # 4) out-of-scope target -> at least GATE (scope is orthogonal to depth)。空 scope = 未知, 仍保守 GATE
    #    —— 不靠 scope_known 放行: 空 scope + 残留 plan 误判 PLAN_DERIVED 会欠标 AUTO 漏放(Codex BLOCKER)。
    #    真实的过期 scope FP 由 #10a(按当前 run 刷 scope)+ setup 自动填 scope 治, 不靠放宽这道门。
    if locus == C.TARGET and hosts and not attr["host_in_scope"]:
        return (max(eff, GATE), "BLOCK" if eff == BLOCK else "GATE", "out-of-scope / scope-undefined target")

    # 5) effect-driven
    if eff == BLOCK:
        # local-workspace destruction (repo-relative, even unattributed) is NOT
        # harm-as-purpose — it's recoverable-ish and operator-gated, cap at GATE.
        # (validation finding 2026-06-14: unattributed `rm -rf runs/x` was over-judged L4.)
        if locus == C.LOCAL_WORKSPACE and _PLAIN_DELETE.search(action.get("command", "")):
            return (GATE, "GATE", "plain file deletion on local workspace — operator review (not harm-as-purpose)")
        return (BLOCK, "BLOCK", "harm-as-purpose / target destruction (never auto)")
    if eff == GATE:
        if prov == C.OPERATOR_DIRECTED:
            return (GATE, "AUTO", "irreversible operator-gated effect, operator-authorized")
        return (GATE, "GATE", "irreversible/high-value effect beyond proof ceiling — operator review")

    # 6) eff == AUTO (proof/recon). FAIL-SAFE floors:
    if not is_reversible(action):
        return (GATE, "GATE", "irreversible state change (fail-safe escalation)")
    if prov == C.UNATTRIBUTED and locus == C.TARGET:
        return (GATE, "GATE", "unattributed target action (fail-safe escalation)")
    return (AUTO, "AUTO", "proof/recon, in-scope or attributed")


# Phase-1 cumulative thresholds (session-level). Tunable.
EGRESS_WARN = 2 * 1024 * 1024        # 2 MB cumulative response bytes retained
REQS_WARN = 300                      # cumulative requests in session
AUTHFAIL_WARN = 8                    # cumulative auth failures


def run_detectors(action: dict, attr: dict, sess: dict, scope: set) -> list[dict]:
    """Return a list of Findings. Pure: reads action/attr/sess, mutates nothing."""
    findings: list[dict] = []
    tier = effect_tier(action)

    def f(detector, severity, intent, reason, risk):
        findings.append({"detector": detector, "severity": severity,
                         "intent": intent, "reason": reason, "risk": risk,
                         "tier": tier})

    # 1) scope drift — target action against a host not in the engagement scope
    #    (空 scope 也报: 未定义=保守, 安全优先; 真实过期 scope 由 #10a 刷当前 run scope 治, 不放宽此门)
    if attr["locus"] == C.TARGET and action.get("hosts") and not attr["host_in_scope"]:
        f("scope_drift", "high", "deny",
          f"action targets out-of-scope host(s) {action['hosts']} (scope={sorted(scope)})", 0.6)

    # 2) effect escalation — deeper/destructive effect on a target, not operator-authorized
    if tier in (DEEPER, DESTRUCTIVE) and attr["locus"] == C.TARGET \
            and attr["provenance"] != C.OPERATOR_DIRECTED:
        f("effect_escalation", "high", "ask",
          f"effect tier '{tier}' against target beyond proof ceiling without operator authorization", 0.5)

    # 3) cumulative exfil / rate — session-level accumulation crossing thresholds
    if sess.get("egress_bytes", 0) > EGRESS_WARN:
        f("exfil_rate", "med", "alert",
          f"cumulative retained egress {sess['egress_bytes']} bytes > {EGRESS_WARN}", 0.3)
    if sess.get("request_count", 0) > REQS_WARN:
        f("exfil_rate", "med", "alert",
          f"cumulative requests {sess['request_count']} > {REQS_WARN}", 0.2)
    if sess.get("auth_fails", 0) > AUTHFAIL_WARN:
        f("exfil_rate", "med", "alert",
          f"cumulative auth failures {sess['auth_fails']} > {AUTHFAIL_WARN}", 0.3)

    # 4) plan deviation — unattributed action with side effects (drift / possible hijack).
    # Suppressed when a more specific high-severity detector already fired (alert hygiene),
    # or when it's teardown of a self-created artifact (cleanup is handled by the
    # GATE decision above, not by a drift detector).
    cmd = action.get("command", "")
    own_infra = bool(_INFRA.search(cmd) and any(r and r in cmd for r in sess.get("artifacts", [])))
    high_already = any(x["severity"] == "high" for x in findings)
    if not high_already and not own_infra and attr["provenance"] == C.UNATTRIBUTED \
            and (tier != RECON or attr["locus"] == C.TARGET):
        f("plan_deviation", "low", "alert",
          "action has no operator/plan/scope attribution (off-script; possible drift or hijack)", 0.2)

    return findings


# --- Part B: session circuit breaker (observe-layer aggregate trip) ------------
# Catches AGGREGATE runaway that no per-command gate can see: a hijacked agent
# (target-content taint hot + sustained effectful actions) or a risk/escalation
# snowball. On trip it CLAMPS subsequent effectful AUTO decisions down to GATE
# (operator review) and fires ONE loud alert — escalate-not-kill: proof / recon /
# operator housekeeping keep flowing so a real engagement is never killed. Still
# observe-only in Phase 1 (the clamp just routes to pending instead of trace).
BREAKER_RISK_TRIP = 3.0        # T2: cumulative session risk_score -> trip
BREAKER_ESCALATION_TRIP = 3    # T3: cumulative high scope/effect-escalation findings since clear
BREAKER_HIJACK_STREAK = 2      # T1: consecutive effectful actions while taint hot
BREAKER_COOLDOWN = 600         # seconds with no contributing event -> auto-clear
# operator is highest authority: this directive clears the breaker immediately.
BREAKER_RESET_RE = re.compile(r"reset\s+breaker|clear\s+breaker|解除熔断|重置熔断", re.I)


def _fresh_breaker(risk_baseline: float = 0.0) -> dict:
    # risk_baseline: the session risk_score at the moment of the last clear. T2
    # measures risk ACCRUED SINCE THEN, not lifetime — otherwise, because risk_score
    # only ever grows, the breaker would re-trip on the next finding after every
    # cooldown once 3.0 was ever crossed (a permanent clamp). See test_breaker.
    return {"tripped": False, "since": "", "until": 0.0, "reason": "",
            "hijack_streak": 0, "escalation_hits": 0, "risk_baseline": round(risk_baseline, 3)}


def breaker_eval(breaker, *, taint_hot, this_effectful, this_escalation,
                 risk_score, now, ts, operator_reset=False):
    """Session circuit-breaker state machine. Pure (no IO): reads the prior breaker
    dict + this action's signals, returns (new_breaker, event) where event is
    'trip' (just tripped), 'clear' (just reset), or None."""
    b = dict(breaker) if breaker else _fresh_breaker()

    # a clear re-baselines T2 to the current risk_score so the next trip needs a
    # fresh BREAKER_RISK_TRIP of accrued risk, not the already-counted lifetime total.
    if operator_reset and b.get("tripped"):
        return (_fresh_breaker(risk_score), "clear")

    if b.get("tripped"):
        # a still-active contributing condition refreshes the cooldown window
        if (taint_hot and this_effectful) or this_escalation:
            b["until"] = now + BREAKER_COOLDOWN
        if now >= b.get("until", 0.0):
            return (_fresh_breaker(risk_score), "clear")
        return (b, None)

    # not tripped: accumulate the trip signals
    b["hijack_streak"] = (b.get("hijack_streak", 0) + 1) if (taint_hot and this_effectful) else 0
    if this_escalation:
        b["escalation_hits"] = b.get("escalation_hits", 0) + 1
    risk_since_clear = risk_score - b.get("risk_baseline", 0.0)

    reason = ""
    if b["hijack_streak"] >= BREAKER_HIJACK_STREAK:
        reason = (f"T1 hijack-streak: {b['hijack_streak']} consecutive effectful actions while "
                  "untrusted target-content taint is hot (possible injection takeover)")
    elif risk_since_clear >= BREAKER_RISK_TRIP:
        reason = (f"T2 risk-accumulation: {round(risk_since_clear, 3)} risk accrued since last "
                  f"clear >= {BREAKER_RISK_TRIP}")
    elif b["escalation_hits"] >= BREAKER_ESCALATION_TRIP:
        reason = (f"T3 escalation-streak: {b['escalation_hits']} high scope/effect-escalation "
                  "findings this session")
    if reason:
        b.update({"tripped": True, "since": ts, "until": now + BREAKER_COOLDOWN, "reason": reason})
        return (b, "trip")
    return (b, None)


def apply_breaker(breaker, level, decision, reason):
    """While tripped, clamp an effectful AUTO decision down to GATE (operator review).
    proof/recon/housekeeping (level < GATE) and already-escalated NOTIFY/GATE/BLOCK
    decisions are left unchanged — only silently-auto effectful actions get paused."""
    if not (breaker and breaker.get("tripped")):
        return (level, decision, reason)
    # only an effectful AUTO is clamped. Bound BELOW BLOCK too: a (BLOCK,"AUTO")
    # must never be downgraded to GATE — the breaker only ever escalates. (Today
    # autonomy_decision never emits BLOCK+AUTO, so this guards a future invariant
    # break, flagged by independent review.)
    if decision == "AUTO" and GATE <= level < BLOCK:
        return (GATE, "GATE",
                f"circuit-breaker tripped ({breaker.get('reason', '')}) — effectful action "
                "clamped to operator review")
    return (level, decision, reason)
