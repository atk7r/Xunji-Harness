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
hookSpecificOutput JSON on stdout only when it decides to deny or ask. Pure
stdlib.
"""

from __future__ import annotations

import datetime
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))
try:
    from harness import privacy as privacymod
    _PRIVACY_IMPORT_ERROR = ""
except Exception as _privacy_error:  # fail closed for target network commands below
    privacymod = None  # type: ignore[assignment]
    _PRIVACY_IMPORT_ERROR = type(_privacy_error).__name__

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

TARGET_URL_RE = re.compile(r"(?:https?|wss?|ftp)://", re.IGNORECASE)

# Neutral target-side temporary artifacts created by this framework must use this
# shape. It gives the hook something precise to recognize without leaking project,
# run, Agent, vuln, or tool names to the target.
TARGET_TEMP_ARTIFACT_RE = re.compile(
    r"\b(?:tmp|diag|proof)-\d{8}-[a-f0-9]{6,12}(?:\.[a-z0-9._-]+)?\b"
    # Legacy escape hatch: old runs may need explicit-yes cleanup of already
    # created xunji_* artifacts. New artifacts must use the neutral shape above.
    r"|\bxunji(?:_[a-z0-9]{2,24}){1,4}\."
    r"(?:txt|ini|conf|config|aspx|ashx|php|jsp|jspx|tmp|html|log)\b",
    re.IGNORECASE,
)

TARGET_CLEANUP_EFFECT_RE = re.compile(
    r"(-X|--request)\s*['\"]?(?:DELETE|PUT|PATCH)\b|"
    r"\brm\s+-(?![a-z-]*r)[a-z-]*f[a-z-]*\b|"
    r"\bunlink\b|\bos\.remove\b|\bfs\.unlink\b|"
    r"\bRemove-Item\b|>\s*(?:/tmp/)?(?:tmp|diag|proof)-",
    re.IGNORECASE,
)

TARGET_CLEANUP_WORD_RE = re.compile(
    r"\b(cleanup|clean\s+up|remove|delete|del|unlink|overwrite|replace)\b|"
    r"清理|删除|移除|覆盖|抹除",
    re.IGNORECASE,
)

TARGET_BODY_FLAG_RE = re.compile(
    r"(?:--data(?:-raw|-binary|-urlencode)?|-d|--json|-F|--form)\s*$",
    re.IGNORECASE,
)


def _word_token(command: str, start: int, end: int) -> str:
    lefts = [command.rfind(ch, 0, start) for ch in (" ", "\t", "\n")]
    left = max(lefts) + 1
    rights = [command.find(ch, end) for ch in (" ", "\t", "\n")]
    right_candidates = [idx for idx in rights if idx >= 0]
    right = min(right_candidates) if right_candidates else len(command)
    return command[left:right]


def _quoted_segment(command: str, start: int, end: int) -> tuple[str, int] | None:
    best: tuple[str, int] | None = None
    for quote in ("'", '"', "`"):
        left = command.rfind(quote, 0, start)
        right = command.find(quote, end)
        if left >= 0 and right >= 0:
            if best is None or left > best[1]:
                best = (command[left:right + 1], left)
    return best


def _artifact_in_target_context(command: str) -> bool:
    """True only when the proof artifact is in the target request context.

    A random local note like `curl https://t/ # cleanup tmp-...` is not enough.
    The artifact must be part of the URL/quoted URL token, or part of an HTTP
    request body/form argument while the command contains a target URL.
    """
    has_url = bool(TARGET_URL_RE.search(command))
    for m in TARGET_TEMP_ARTIFACT_RE.finditer(command):
        if TARGET_URL_RE.search(_word_token(command, m.start(), m.end())):
            return True
        quoted = _quoted_segment(command, m.start(), m.end())
        if quoted:
            segment, left = quoted
            if TARGET_URL_RE.search(segment):
                return True
            if has_url and TARGET_BODY_FLAG_RE.search(command[max(0, left - 40):left]):
                return True
    return False


def _cleanup_word_near_artifact(command: str) -> bool:
    for m in TARGET_TEMP_ARTIFACT_RE.finditer(command):
        start = max(0, m.start() - 80)
        end = min(len(command), m.end() + 80)
        if TARGET_CLEANUP_WORD_RE.search(command[start:end]):
            return True
    return False


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


def _safe_audit_command(command: str) -> str:
    try:
        return (privacymod.sanitize_text_for_log(command)
                if privacymod is not None else "<command redaction unavailable>")
    except Exception:
        # Preserve the event without raw bytes if redaction itself breaks.
        return "<command omitted: redaction failed>"


def audit(category: str, reason: str, command: str, decision: str = "DENY") -> None:
    """Append a HARD_STOP hit to the audit log. Best-effort: never let logging
    break the gate (a failed write must not change the deny decision)."""
    try:
        log = Path(__file__).resolve().parents[2] / "tools" / "harness" / ".state" / "audit.log"
        log.parent.mkdir(parents=True, exist_ok=True)
        ts = datetime.datetime.now().isoformat(timespec="seconds")
        safe_command = _safe_audit_command(command)
        with log.open("a", encoding="utf-8") as fh:
            fh.write(f"{ts} | {decision} | {category} | {reason} | {safe_command[:120]}\n")
    except Exception:
        pass


def decision(permission_decision: str, reason: str) -> None:
    out = {
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": permission_decision,
            "permissionDecisionReason": reason,
        }
    }
    print(json.dumps(out))
    sys.exit(0)


def deny(reason: str) -> None:
    decision("deny", reason)


def ask(reason: str) -> None:
    decision("ask", reason)


def cleanup_requires_ask(command: str) -> str:
    """Return a reason when this looks like target-side proof-artifact cleanup.

    Generic target resource deletion remains hard-denied by the normal deny
    rules. This soft gate is intentionally narrow: it only asks for target-side
    deletion/overwrite when a URL and a recognizable proof-temp artifact name
    are both present.
    """
    if not _artifact_in_target_context(command):
        return ""
    if not (TARGET_CLEANUP_EFFECT_RE.search(command)
            or _cleanup_word_near_artifact(command)):
        return ""
    return (
        "target-side cleanup/overwrite of a proof artifact requires explicit "
        "operator yes"
    )


def outbound_privacy_reason(command: str, *, allow_legacy_cleanup: bool = False) -> str:
    """Return a category-only reason without echoing the matched private value."""
    if privacymod is not None:
        return privacymod.outbound_command_privacy_reason(
            command, allow_legacy_cleanup=allow_legacy_cleanup
        )
    # If the shared privacy module cannot load, URL-bearing Bash actions are
    # categorically uninspectable.  Fail closed instead of maintaining a second,
    # inevitably incomplete list of network tools here.
    if TARGET_URL_RE.search(command):
        return f"privacy guard unavailable ({_PRIVACY_IMPORT_ERROR or 'unknown import error'})"
    return ""


def selftest() -> int:
    """Fail-closed self-check: prove the gate still denies known-bad commands and
    stays silent on known-good ones. Returns 0 if healthy, 1 if the gate is broken.
    Wire this into session start / tools/check_hook.py so a broken gate is caught
    before any hunting begins."""
    must_block = [
        # rm is narrowed to CATASTROPHIC targets only (root / home / system dir /
        # drive root / bare * . ..); these must still hard-deny.
        '{"tool_name":"Bash","tool_input":{"command":"rm -rf /"}}',
        '{"tool_name":"Bash","tool_input":{"command":"rm -rf ~"}}',
        # ...but a destructive rm SHIPPED TO A TARGET as a QUOTED payload (injected
        # into a request) hard-denies at any path (the unquoted form is shell-
        # fragmented + inert, so it is intentionally NOT matched after the narrowing):
        '{"tool_name":"Bash","tool_input":{"command":"curl \'http://t/?c=rm -rf /app/data\'"}}',
        '{"tool_name":"Bash","tool_input":{"command":"curl \'http://t/?c=rm -r /app/data\'"}}',
        # data-dir rm the one-level catastrophic rule misses (F5 gap):
        '{"tool_name":"Bash","tool_input":{"command":"rm -rf /var/lib/mysql"}}',
        '{"tool_name":"Bash","tool_input":{"command":"sqlmap -u http://t/ --dump"}}',
        '{"tool_name":"Bash","tool_input":{"command":"mysql -e \'DROP DATABASE prod\'"}}',
        '{"tool_name":"Bash","tool_input":{"command":"curl https://t/ -d \'marker=xunji-proof\'"}}',
        '{"tool_name":"Bash","tool_input":{"command":"python tools/probe.py POST https://t/ --data \'mobile=13800138000\'"}}',
        json.dumps({"tool_name": "Bash", "tool_input": {
            "command": f"curl https://t/ -H 'X-Note: {Path.home()}/run.txt'"
        }}),
    ]
    must_pass = [
        '{"tool_name":"Bash","tool_input":{"command":"curl -s https://t/api/x"}}',
        # repo-relative cleanup is NOT catastrophic -> must fall through to the
        # native ask/allow flow, not hard-deny (this is the narrowing guarantee).
        '{"tool_name":"Bash","tool_input":{"command":"rm -rf tmp/build"}}',
        '{"tool_name":"Bash","tool_input":{"command":"rm -f runs/old/cookies.txt"}}',
        '{"tool_name":"Bash","tool_input":{"command":"curl https://t/ # cleanup tmp-20260708-a1b2c3d4.txt"}}',
        '{"tool_name":"Bash","tool_input":{"command":"XUNJI_PROXY=socks5h://127.0.0.1:1080 python tools/probe.py GET https://t/"}}',
        '{"tool_name":"Bash","tool_input":{"command":"python tools/probe.py POST https://t/login --data \'email=person@real.example.cn\' --allow-sensitive-auth"}}',
        # The operator-supplied destination may itself contain the project word;
        # it is not generated proof data and must not be rewritten.
        '{"tool_name":"Bash","tool_input":{"command":"curl https://xunji.example.test/"}}',
        '{"tool_name":"Bash","tool_input":{"command":"curl https://t/home/dashboard"}}',
        '{"tool_name":"Bash","tool_input":{"command":"curl https://t/Users/settings"}}',
        '{"tool_name":"Bash","tool_input":{"command":"curl https://t/runs/list"}}',
    ]
    must_ask = [
        '{"tool_name":"Bash","tool_input":{"command":"curl -X DELETE https://t/uploads/tmp-20260708-a1b2c3d4.txt"}}',
        '{"tool_name":"Bash","tool_input":{"command":"curl \'https://t/?cmd=rm -f /tmp/tmp-20260708-a1b2c3d4.txt\'"}}',
        '{"tool_name":"Bash","tool_input":{"command":"curl -X PUT https://t/uploads/diag-20260708-a1b2c3d4.txt --data-binary \'\'"}}',
        '{"tool_name":"Bash","tool_input":{"command":"curl -X POST https://t/cleanup -d \'path=/tmp/tmp-20260708-a1b2c3d4.txt&action=delete\'"}}',
        '{"tool_name":"Bash","tool_input":{"command":"curl -X DELETE https://t/uploads/xunji_wcfg_export.txt"}}',
    ]
    rules = load_rules()

    def classify(ev_text: str) -> str:
        cmd = extract_command(json.loads(ev_text))
        cleanup_reason = cleanup_requires_ask(cmd)
        if outbound_privacy_reason(cmd, allow_legacy_cleanup=bool(cleanup_reason)):
            return "deny"
        for r in rules:
            if not _safe_pattern(r["pattern"]):
                continue
            if re.search(r["pattern"], cmd, re.IGNORECASE):
                if cleanup_reason and r.get("category") == "delete_resource":
                    return "ask"
                return "deny"
        if cleanup_reason:
            return "ask"
        return "pass"

    ok = True
    for ev in must_block:
        if classify(ev) != "deny":
            print(f"[selftest] FAIL: should block -> {ev}", file=sys.stderr)
            ok = False
    for ev in must_ask:
        if classify(ev) != "ask":
            print(f"[selftest] FAIL: should ask -> {ev}", file=sys.stderr)
            ok = False
    for ev in must_pass:
        if classify(ev) != "pass":
            print(f"[selftest] FAIL: should allow -> {ev}", file=sys.stderr)
            ok = False
    # Simulate the shared privacy module being unavailable: every URL-bearing
    # command must fail closed, including custom/heredoc-style executors.
    global privacymod, _PRIVACY_IMPORT_ERROR
    saved_privacy, saved_error = privacymod, _PRIVACY_IMPORT_ERROR
    try:
        privacymod = None
        _PRIVACY_IMPORT_ERROR = "SelftestImportError"
        if not outbound_privacy_reason("python custom_sender.py https://t/"):
            print("[selftest] FAIL: missing privacy module did not fail closed on custom URL command",
                  file=sys.stderr)
            ok = False
        if outbound_privacy_reason("echo local-only"):
            print("[selftest] FAIL: missing privacy module blocked URL-free local command",
                  file=sys.stderr)
            ok = False
    finally:
        privacymod, _PRIVACY_IMPORT_ERROR = saved_privacy, saved_error
    if privacymod is not None:
        saved_sanitizer = privacymod.sanitize_text_for_log
        try:
            def _broken_sanitizer(_command: str) -> str:
                raise ValueError("selftest redaction failure")
            privacymod.sanitize_text_for_log = _broken_sanitizer
            if _safe_audit_command("private-value") != "<command omitted: redaction failed>":
                print("[selftest] FAIL: audit redaction failure did not preserve an omitted event",
                      file=sys.stderr)
                ok = False
        finally:
            privacymod.sanitize_text_for_log = saved_sanitizer
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
        # Read stdin as raw bytes and decode UTF-8 explicitly: the harness sends a
        # UTF-8 event, but sys.stdin.read() would decode it with the OS locale codec
        # (GBK/cp936 on a Chinese Windows), so a command containing non-ASCII (中文
        # echo / heredoc) would fail to decode and trip the fail-closed branch on a
        # perfectly benign command. Mirrors the UTF-8 reconfigure probe.py/render.py
        # already do. A genuinely malformed event still raises -> still fail-closed.
        raw = sys.stdin.buffer.read()
        event = json.loads(raw.decode("utf-8", "replace") or "{}")
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

    cleanup_reason = cleanup_requires_ask(command)
    privacy_reason = outbound_privacy_reason(
        command, allow_legacy_cleanup=bool(cleanup_reason)
    )
    if privacy_reason:
        audit("outbound_privacy", privacy_reason, "<target command redacted>")
        deny(
            f"[safety-boundary] BLOCKED (outbound_privacy): {privacy_reason}. "
            "Target-facing URL payloads, headers, bodies, multipart filenames/content, "
            "and proof writes must not contain project/run/Agent/operator identity or "
            "real personal data. Use neutral tmp/diag/proof-YYYYMMDD-<hex> values. "
            "Necessary personal data in an authentication body is allowed only through "
            "the guarded probe --allow-sensitive-auth exception; internal identity markers "
            "remain forbidden. Do not bypass or encode around this check."
        )
    for rule in load_rules():
        try:
            m = re.search(rule["pattern"], command, re.IGNORECASE)
            if m:
                cat = rule.get("category", "blocked")
                reason = rule.get("reason", "matched a deny rule")
                # Surface the exact matched substring + offset so the driver can see
                # WHAT tripped WHICH rule and reword fast (vs guessing). Most of this
                # session's stop-and-reword churn was not knowing the matched token.
                matched = m.group(0).strip()
                span = f"{m.start()}-{m.end()}"
                if cleanup_reason and cat == "delete_resource":
                    audit("cleanup_requires_yes", cleanup_reason,
                          f"[matched {matched!r}@{span}] {command}", decision="ASK")
                    ask(
                        f"[safety-boundary] ASK (cleanup_requires_yes): {cleanup_reason}. "
                        f"[matched substring {matched!r} at offset {span}] "
                        f"Cleanup is a target-side state change. STOP and ASK the operator "
                        f"for explicit yes before running this exact cleanup. If the operator "
                        f"does not answer yes, leave the artifact recorded and do not clean it."
                    )
                    # ask() exits the hook; the deny path below is unreachable for this match.
                audit(cat, reason, f"[matched {matched!r}@{span}] {command}")
                deny(
                    f"[safety-boundary] BLOCKED ({cat}): {reason}. "
                    f"[matched substring {matched!r} at offset {span}] "
                    f"This destructive action class is NEVER executed, regardless of target, "
                    f"and human authorization does NOT unlock it - authorization can only ever "
                    f"approve an equivalent SAFE proof-of-concept. STOP and ASK the user: explain "
                    f"why you think verification needs this, then propose a non-destructive "
                    f"equivalent PoC and wait for confirmation. Do not work around this hook. "
                    f"If this is a FALSE POSITIVE (the matched substring above is benign DATA — e.g. "
                    f"a payload/grep arg/echo/heredoc/commit message — not an executed command), the "
                    f"user may narrow the offending rule in .claude/hooks/safety_rules.json."
                )
        except re.error:
            continue

    if cleanup_reason:
        audit("cleanup_requires_yes", cleanup_reason, command, decision="ASK")
        ask(
            f"[safety-boundary] ASK (cleanup_requires_yes): {cleanup_reason}. "
            f"Cleanup is a target-side state change. STOP and ASK the operator for "
            f"explicit yes before running this exact cleanup. If the operator does "
            f"not answer yes, leave the artifact recorded and do not clean it."
        )

    # No match -> stay silent, let normal permission flow decide.
    sys.exit(0)


if __name__ == "__main__":
    main()
