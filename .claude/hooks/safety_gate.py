#!/usr/bin/env python3
"""PreToolUse safety gate for autonomous vulnerability hunting.

Role: this hook is a *boundary*, not a driver. The AI designs and executes its
own hunting approach freely; this script only deterministically BLOCKS a small
set of destructive action categories (filesystem/host destruction, permission
changes, money/transfer/refund state changes, resource deletion, online
brute-force, and DoS). It does NOT restrict scope/domain, and it never
auto-approves anything: on no match it stays silent so Claude Code's normal
permission flow applies.

Protocol: reads the PreToolUse JSON event on stdin, writes a PreToolUse
hookSpecificOutput JSON on stdout only when it decides to deny. Pure stdlib.
"""

from __future__ import annotations

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
    {"category": "permission_change", "pattern": r"\bchown\b", "reason": "ownership change (chown)"},
    {"category": "delete_resource", "pattern": r"(-X|--request)\s*['\"]?DELETE", "reason": "state-changing HTTP DELETE"},
    {"category": "bruteforce", "pattern": r"\b(hydra|medusa|patator|ncrack|crackmapexec|brutespray)\b", "reason": "online credential brute-force tool"},
    {"category": "dos", "pattern": r"\b(slowloris|loic|hoic|t50|mhddos|masscan)\b", "reason": "DoS / mass-flood tool"},
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


def main() -> None:
    try:
        event = json.loads(sys.stdin.read() or "{}")
    except Exception:
        # If we cannot parse the event, do not block (fail-open for usability);
        # the destructive-default rules only matter when a command is present.
        sys.exit(0)

    command = extract_command(event)
    if not command:
        sys.exit(0)

    for rule in load_rules():
        try:
            if re.search(rule["pattern"], command, re.IGNORECASE):
                cat = rule.get("category", "blocked")
                reason = rule.get("reason", "matched a deny rule")
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
