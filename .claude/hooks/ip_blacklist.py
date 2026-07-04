#!/usr/bin/env python3
"""PreToolUse IP/domain blacklist hook — 独立黑名单闸门.

Role: 硬拒绝访问黑名单中的域名/IP/URL 模式。与 safety_gate.py 并行独立运行，
只做黑名单检查，不做其他安全判断。

黑名单配置: tools/harness/ip_blacklist.conf (gitignored, 一行一个 pattern)
内置默认: *.gov.cn (直接拒绝所有 .gov.cn 域名访问)

Protocol: reads PreToolUse JSON event on stdin, outputs hookSpecificOutput
JSON on stdout only when blocking. Pure stdlib.
"""

from __future__ import annotations

import json
import os
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CONF_PATH = ROOT / "tools" / "harness" / "ip_blacklist.conf"
AUDIT_PATH = ROOT / "tools" / "harness" / ".state" / "blacklist_audit.log"

# 内置默认黑名单 (gov.cn 及其所有变体)
DEFAULT_BLACKLIST = [r"gov\.cn"]


def load_blacklist() -> list[str]:
    """加载黑名单 patterns。conf 文件一行一个正则 pattern。不存在或损坏时回退到内置默认。"""
    if CONF_PATH.is_file():
        try:
            lines = [
                line.strip() for line in CONF_PATH.read_text(encoding="utf-8").splitlines()
                if line.strip() and not line.strip().startswith("#")
            ]
            if lines:
                return lines
        except Exception:
            pass
    return DEFAULT_BLACKLIST


# Commands that are always local meta-operations — skip blacklist check
_META_PREFIXES = [
    "git ", "echo ", "cat ", "ls ", "mkdir ", "cd ", "rm ",
    "cp ", "mv ", "find ", "grep ", "wc ", "head ", "tail ",
    "sort ", "uniq ", "python3 -c ", "python -c ",
]


def _is_meta_command(cmd: str) -> bool:
    """本地元操作命令（非网络请求），直接放行。"""
    cmd_lower = cmd.strip().lower()
    for prefix in _META_PREFIXES:
        if cmd_lower.startswith(prefix):
            return True
    return False


def extract_content(event: dict) -> str:
    """从 PreToolUse 事件中提取要检查的文本内容。

    支持: Bash(command), WebSearch(query), WebFetch(url)
    """
    tool_input = event.get("tool_input") or {}
    if not isinstance(tool_input, dict):
        return ""

    # Bash
    if "command" in tool_input and isinstance(tool_input["command"], str):
        return tool_input["command"]

    # WebSearch — 检查 query
    if "query" in tool_input and isinstance(tool_input["query"], str):
        return tool_input["query"]

    # WebFetch — 检查 url
    if "url" in tool_input and isinstance(tool_input["url"], str):
        return tool_input["url"]

    # 兜底: 拼接所有字符串值
    return " ".join(v for v in tool_input.values() if isinstance(v, str))


def check_blacklist(content: str, patterns: list[str]) -> tuple[bool, str | None]:
    """检查内容是否命中黑名单。返回 (blocked, matched_pattern)。"""
    for pat in patterns:
        try:
            if re.search(pat, content, re.IGNORECASE):
                return True, pat
        except re.error:
            continue
    return False, None


def audit(tool_name: str, pattern: str, snippet: str) -> None:
    """记录阻断事件到审计日志。Best-effort: 日志失败不影响阻断。"""
    try:
        from datetime import datetime, timezone
        AUDIT_PATH.parent.mkdir(parents=True, exist_ok=True)
        ts = datetime.now(timezone.utc).isoformat(timespec="seconds")
        with AUDIT_PATH.open("a", encoding="utf-8") as f:
            f.write(f"{ts} | BLOCK | {tool_name} | {pattern} | {snippet[:150]}\n")
    except Exception:
        pass


def deny(reason: str) -> None:
    """输出 PreToolUse 拒绝决策。"""
    out = {
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": "deny",
            "permissionDecisionReason": reason,
        }
    }
    print(json.dumps(out))
    sys.exit(0)


def main() -> int:
    if "--selftest" in sys.argv:
        return selftest()

    try:
        event = json.loads(sys.stdin.read())
    except Exception:
        return 0  # 解析失败 → 放行 (fail-open for hook input errors)

    tool_name = event.get("tool_name", "")
    content = extract_content(event)
    if not content:
        return 0  # 无可检查内容 → 放行

    # 本地元操作（git / echo / ls / ...）不检查黑名单
    if tool_name == "Bash" and _is_meta_command(content):
        return 0

    patterns = load_blacklist()
    blocked, matched = check_blacklist(content, patterns)
    if blocked:
        reason = (
            f"[IP黑名单] 目标匹配黑名单规则 '{matched}'，拒绝访问。"
            f"黑名单由 .claude/hooks/ip_blacklist.py 强制执行。"
        )
        audit(tool_name, matched, content)
        deny(reason)

    return 0  # 未命中 → 放行 (silent pass-through)


def selftest() -> int:
    """回归测试: 验证黑名单能拦截该拦的、放行该放的。"""
    patterns = load_blacklist()
    checks: list[tuple[str, bool]] = []

    # 内置默认黑名单必须包含 gov.cn
    checks.append(("default blacklist non-empty", len(patterns) >= 1))
    checks.append(("default has gov.cn", any("gov" in p and "cn" in p for p in DEFAULT_BLACKLIST)))

    # 必须拦截的 case
    must_block = [
        # Bash: 直接 curl gov.cn
        (True, "Bash", 'curl -s https://www.example.gov.cn/api'),
        (True, "Bash", 'curl -v https://sub.example.gov.cn:8443/login'),
        (True, "Bash", 'python3 tools/probe.py https://any.gov.cn/test'),
        (True, "Bash", 'wget http://xx.gx.gov.cn/file.zip'),
        # WebSearch: 搜索 gov.cn 站点
        (True, "WebSearch", "site:gov.cn 漏洞公告"),
        (True, "WebSearch", "site:example.gov.cn filetype:pdf"),
        # WebFetch: 抓取 gov.cn
        (True, "WebFetch", "https://www.mfa.gov.cn/index.html"),
        (True, "WebFetch", "http://stats.gd.gov.cn/api/data"),
    ]

    # 必须放行的 case
    must_pass = [
        (False, "Bash", 'curl -s https://example.com/api'),
        (False, "Bash", 'curl https://github.com/exploit'),
        (False, "WebSearch", "CVE-2026 最新漏洞"),
        (False, "WebFetch", "https://cve.mitre.org/cgi-bin/cvename.cgi?name=CVE-2026-12345"),
        (False, "WebFetch", "https://nvd.nist.gov/vuln/detail/CVE-2026-12345"),
        (False, "Bash", 'git clone https://github.com/user/repo.git'),
        (False, "WebSearch", "gov 域名漏洞挖掘") if "gov" not in "".join(patterns).lower() else (True, "WebSearch", "gov 域名漏洞挖掘"),
        # edge: gov 不带 .cn 不应被拦截
        (False, "Bash", 'curl https://www.usa.gov/data'),
    ]

    # Filter out the conditional case — remove the last must_pass element since it's a computed tuple
    # Actually let me just handle it differently. Let me run it inline.
    # Remove the dynamic test case — it's too fragile in a list literal
    must_pass_static = [
        (False, "Bash", 'curl -s https://example.com/api'),
        (False, "Bash", 'curl https://github.com/exploit'),
        (False, "WebSearch", "CVE-2026 最新漏洞"),
        (False, "WebFetch", "https://cve.mitre.org/cgi-bin/cvename.cgi?name=CVE-2026-12345"),
        (False, "WebFetch", "https://nvd.nist.gov/vuln/detail/CVE-2026-12345"),
        (False, "Bash", 'git clone https://github.com/user/repo.git'),
        (False, "Bash", 'curl https://www.usa.gov/data'),
    ]

    for should_block, tool_name, content in must_block:
        blocked, _ = check_blacklist(content, patterns)
        label = f"BLOCK: {tool_name} -> {content[:50]}"
        checks.append((label, blocked == should_block))

    for should_block, tool_name, content in must_pass_static:
        blocked, _ = check_blacklist(content, patterns)
        label = f"PASS:  {tool_name} -> {content[:50]}"
        checks.append((label, not blocked))

    # extract_content 函数测试
    bash_ev = {"tool_name": "Bash", "tool_input": {"command": "curl https://test.gov.cn"}}
    checks.append(("extract Bash command", extract_content(bash_ev) == "curl https://test.gov.cn"))
    ws_ev = {"tool_name": "WebSearch", "tool_input": {"query": "site:gov.cn test"}}
    checks.append(("extract WebSearch query", extract_content(ws_ev) == "site:gov.cn test"))
    wf_ev = {"tool_name": "WebFetch", "tool_input": {"url": "https://test.gov.cn/page"}}
    checks.append(("extract WebFetch url", extract_content(wf_ev) == "https://test.gov.cn/page"))
    empty_ev = {"tool_name": "Bash", "tool_input": {}}
    checks.append(("extract empty input", extract_content(empty_ev) == ""))

    # invalid pattern 不崩溃
    blocked_invalid, matched_invalid = check_blacklist("test", [r"***invalid[re"])
    checks.append(("invalid pattern does not crash", not blocked_invalid and matched_invalid is None))

    # 元操作命令不拦截（即使内容包含 gov.cn）
    checks.append(("git commit with gov.cn in message", _is_meta_command("git commit -m 'add gov.cn block'")))
    checks.append(("echo gov.cn is meta", _is_meta_command("echo gov.cn")))
    checks.append(("cat file is meta", _is_meta_command("cat /etc/hosts")))
    checks.append(("curl is NOT meta", not _is_meta_command("curl https://gov.cn")))
    checks.append(("probe is NOT meta", not _is_meta_command("python3 tools/probe.py https://gov.cn")))

    bad = [n for n, ok in checks if not ok]
    for n, ok in checks:
        print(("ok   " if ok else "FAIL ") + n)
    print(f"ip_blacklist selftest {'passed' if not bad else f'FAILED ({len(bad)})'}")
    return 0 if not bad else 1


if __name__ == "__main__":
    raise SystemExit(main())
