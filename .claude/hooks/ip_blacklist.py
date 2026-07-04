#!/usr/bin/env python3
"""PreToolUse IP/domain blacklist hook.

Blocks Bash/WebSearch/WebFetch input when it matches a blacklist regex.

No built-in defaults — all rules come from the config file.  If the config
file is missing or empty, the hook is a no-op (nothing is blocked).

Config path:
  tools/harness/ip_blacklist.conf

Format:
  - one Python regex per line
  - blank lines and lines starting with # are ignored
  - see tools/harness/ip_blacklist.conf.example
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CONF_PATH = ROOT / "tools" / "harness" / "ip_blacklist.conf"
INPUT_FIELDS = ("command", "query", "url")


def load_patterns() -> list[str]:
    try:
        lines = CONF_PATH.read_text(encoding="utf-8").splitlines()
    except (FileNotFoundError, OSError):
        return []

    patterns: list[str] = []
    for raw in lines:
        line = raw.strip()
        if line and not line.startswith("#") and line not in patterns:
            patterns.append(line)
    return patterns


def event_text(event: dict) -> str:
    tool_input = event.get("tool_input") or {}
    if not isinstance(tool_input, dict):
        return ""

    return " ".join(
        value
        for key in INPUT_FIELDS
        if isinstance((value := tool_input.get(key)), str)
    )


def first_match(text: str, patterns: list[str]) -> str | None:
    for pattern in patterns:
        try:
            if re.search(pattern, text, re.IGNORECASE):
                return pattern
        except re.error:
            continue
    return None


def deny(pattern: str) -> None:
    out = {
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": "deny",
            "permissionDecisionReason": (
                f"[IP黑名单] 目标匹配黑名单规则 '{pattern}'，拒绝访问。"
            ),
        }
    }
    print(json.dumps(out, ensure_ascii=False))


def main() -> int:
    if "--selftest" in sys.argv:
        return selftest()

    patterns = load_patterns()
    if not patterns:
        return 0  # 无黑名单规则 → 放行

    try:
        event = json.loads(sys.stdin.read() or "{}")
    except json.JSONDecodeError:
        return 0

    text = event_text(event)
    if not text:
        return 0

    match = first_match(text, patterns)
    if match:
        deny(match)

    return 0


def selftest() -> int:
    loaded = load_patterns()
    invalid = []
    for pattern in loaded:
        try:
            re.compile(pattern)
        except re.error as exc:
            invalid.append(f"{pattern}: {exc}")

    # selftest uses its own test patterns, independent of the conf file
    test_patterns = [r"gov\.cn", r"192\.0\.2\.\d+", r"malware\.example\.com"]

    checks = [
        ("config patterns compile", not invalid),
        ("block gov.cn URL", first_match("curl https://www.example.gov.cn/api", test_patterns) == r"gov\.cn"),
        ("block gov.cn search", first_match("site:gov.cn 漏洞公告", test_patterns) == r"gov\.cn"),
        ("block IP range", first_match("curl https://192.0.2.10/admin", test_patterns) == r"192\.0\.2\.\d+"),
        ("block malware domain", first_match("wget https://malware.example.com/payload", test_patterns) == r"malware\.example\.com"),
        ("pass normal URL", first_match("curl https://example.com/api", test_patterns) is None),
        ("pass usa.gov", first_match("curl https://www.usa.gov/data", test_patterns) is None),
        (
            "extract command/query/url",
            event_text({"tool_input": {"command": "curl https://test.gov.cn"}})
            == "curl https://test.gov.cn"
            and event_text({"tool_input": {"query": "site:gov.cn test"}})
            == "site:gov.cn test"
            and event_text({"tool_input": {"url": "https://test.gov.cn/page"}})
            == "https://test.gov.cn/page",
        ),
        ("empty patterns = no match", first_match("curl https://gov.cn", []) is None),
        ("invalid regex ignored at match time", first_match("test", [r"***invalid[re"]) is None),
    ]

    for item in invalid:
        print(f"FAIL invalid pattern in {CONF_PATH}: {item}")

    failed = [name for name, ok in checks if not ok]
    for name, ok in checks:
        print(("ok   " if ok else "FAIL ") + name)

    print(f"ip_blacklist selftest {'passed' if not failed and not invalid else 'FAILED'}")
    return 0 if not failed and not invalid else 1


if __name__ == "__main__":
    raise SystemExit(main())
