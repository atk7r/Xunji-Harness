#!/usr/bin/env python3
"""PreToolUse safety gate for autonomous vulnerability hunting.

Role: this hook is a *boundary*, not a driver. The AI designs and executes its
own hunting approach freely; this script only deterministically BLOCKS a small
set of irreversible / destructive action categories (filesystem & host
destruction incl. 删库, mass data dump / 拖库, resource deletion, money
movement, and DoS). It does NOT restrict scope/domain, and it never
auto-approves anything: on no match it stays silent so Claude Code's normal
permission flow applies.

Protocol: reads the PreToolUse JSON event on stdin, writes a PreToolUse
hookSpecificOutput JSON on stdout only when it decides to deny. Pure stdlib.
"""

from __future__ import annotations

import datetime
import json
import re
import sys
from pathlib import Path

RULES_PATH = Path(__file__).with_name("safety_rules.json")

# Built-in fallback used if safety_rules.json is missing or unreadable, so the
# boundary still holds even when the config file is deleted.
DEFAULT_RULES = [
    {"category": "destructive", "pattern": r"\brm\s+-[a-z]*[rf]", "reason": "recursive/forced file deletion (rm -rf)"},
    {"category": "destructive", "pattern": r"\bmkfs\b", "reason": "filesystem format"},
    {"category": "destructive", "pattern": r"\bdd\s+if=", "reason": "raw disk write (dd if=)"},
    {"category": "destructive", "pattern": r"\b(shutdown|reboot|halt|poweroff)\b", "reason": "host shutdown/reboot"},
    {"category": "destructive", "pattern": r"\bdrop\s+(database|table|schema)\b", "reason": "database/table destruction (删库)"},
    {"category": "data_exfil", "pattern": r"\bsqlmap\b[^|;\n]*--dump", "reason": "sqlmap data dump (拖库)"},
    {"category": "delete_resource", "pattern": r"(-X|--request)\s*['\"]?DELETE", "reason": "state-changing HTTP DELETE"},
    {"category": "dos", "pattern": r"\b(slowloris|loic|hoic|t50|mhddos|masscan)\b", "reason": "DoS / mass-flood tool"},
    {"category": "payment_transfer", "pattern": r"(-X\s*(POST|PUT|PATCH)|--data|\s-d\s)[^|;\n]*\b(transfer|withdraw|refund|payout)\b", "reason": "money-movement request"},
]


def load_rules() -> list[dict]:
    try:
        data = json.loads(RULES_PATH.read_text(encoding="utf-8"))
        rules = data.get("rules") if isinstance(data, dict) else None
        compiled = []
        for r in rules or []:
            if "pattern" in r:
                compiled.append(r)
        return compiled or DEFAULT_RULES
    except Exception:
        return DEFAULT_RULES


def extract_command(event: dict) -> str:
    """Pull the inspectable command/payload text out of the tool input."""
    tool_input = event.get("tool_input") or {}
    if not isinstance(tool_input, dict):
        return ""
    # Bash -> command; other tools -> best-effort concatenation of string values.
    if "command" in tool_input and isinstance(tool_input["command"], str):
        return tool_input["command"]
    parts = [v for v in tool_input.values() if isinstance(v, str)]
    return " \n ".join(parts)


def audit(category: str, reason: str, command: str) -> None:
    """Append a HARD_STOP hit to the audit log. Best-effort: never let logging
    break the gate (a failed write must not change the deny decision)."""
    try:
        log = Path(__file__).resolve().parents[2] / "tools" / "harness" / ".state" / "audit.log"
        log.parent.mkdir(parents=True, exist_ok=True)
        ts = datetime.datetime.now().isoformat(timespec="seconds")
        with log.open("a", encoding="utf-8") as fh:
            fh.write(f"{ts} | DENY | {category} | {reason} | {command[:120]}\n")
    except Exception:
        pass


def deny(reason: str) -> None:
    out = {
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": "deny",
            "permissionDecisionReason": reason,
        }
    }
    print(json.dumps(out))
    sys.exit(0)


def selftest() -> int:
    """Fail-closed self-check: prove the gate still denies known-bad commands and
    stays silent on known-good ones. Returns 0 if healthy, 1 if the gate is broken.
    Wire this into session start / tools/check_hook.py so a broken gate is caught
    before any hunting begins."""
    must_block = [
        '{"tool_name":"Bash","tool_input":{"command":"rm -rf /tmp/x"}}',
        '{"tool_name":"Bash","tool_input":{"command":"sqlmap -u http://t/ --dump"}}',
        '{"tool_name":"Bash","tool_input":{"command":"mysql -e \'DROP DATABASE prod\'"}}',
    ]
    must_pass = [
        '{"tool_name":"Bash","tool_input":{"command":"curl -s https://t/api/x"}}',
    ]
    rules = load_rules()

    def blocks(ev_text: str) -> bool:
        cmd = extract_command(json.loads(ev_text))
        return any(
            re.search(r["pattern"], cmd, re.IGNORECASE) for r in rules
            if _safe_pattern(r["pattern"])
        )

    ok = True
    for ev in must_block:
        if not blocks(ev):
            print(f"[selftest] FAIL: should block -> {ev}", file=sys.stderr)
            ok = False
    for ev in must_pass:
        if blocks(ev):
            print(f"[selftest] FAIL: should allow -> {ev}", file=sys.stderr)
            ok = False
    print("[selftest] safety gate healthy" if ok else "[selftest] safety gate BROKEN",
          file=sys.stderr)
    return 0 if ok else 1


def _safe_pattern(pattern: str) -> bool:
    try:
        re.compile(pattern)
        return True
    except re.error:
        return False


def main() -> None:
    if "--selftest" in sys.argv:
        sys.exit(selftest())

    try:
        event = json.loads(sys.stdin.read() or "{}")
    except Exception:
        # FAIL-CLOSED: a malformed event means we cannot vet this action, so we
        # refuse it rather than let it through unchecked.
        deny(
            "[safety-boundary] BLOCKED (fail-closed): the safety gate could not parse "
            "the tool event, so it cannot vet this action against the deny rules. This is a "
            "fail-closed stop. Retry; if it persists, inspect .claude/hooks/safety_gate.py."
        )

    command = extract_command(event)
    if not command:
        sys.exit(0)

    for rule in load_rules():
        try:
            if re.search(rule["pattern"], command, re.IGNORECASE):
                cat = rule.get("category", "blocked")
                reason = rule.get("reason", "matched a deny rule")
                audit(cat, reason, command)
                deny(
                    f"[safety-boundary] BLOCKED ({cat}): {reason}. "
                    f"This destructive action class is NEVER executed, regardless of target, "
                    f"and human authorization does NOT unlock it - authorization can only ever "
                    f"approve an equivalent SAFE proof-of-concept. STOP and ASK the user: explain "
                    f"why you think verification needs this, then propose a non-destructive "
                    f"equivalent PoC and wait for confirmation. Do not work around this hook. "
                    f"Only if this is a genuine false positive (a benign command wrongly matched) "
                    f"should the user adjust .claude/hooks/safety_rules.json."
                )
        except re.error:
            continue

    # No match -> stay silent, let normal permission flow decide.
    sys.exit(0)


if __name__ == "__main__":
    main()
