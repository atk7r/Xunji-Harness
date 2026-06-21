#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Stop hook: output drift gate — detects delegation patterns in Driver response.

When the Driver ends a turn with "是否继续" / "要不要继续" / "还是等其他条件" etc.,
this hook prints a systemMessage warning. MVP: fail-open, advisory only — never blocks.

Distinct from run_gate.py (closure structural gate) and safety_gate.py (damage prevention).
This gate checks conversation text for protocol violations, independently of run file state.

Protocol: read Stop event from stdin; on drift match, print systemMessage; exit 0 always.
FAIL-OPEN: any error → silent exit 0 (a reminder must never stall a session).

Usage:
    python3 .claude/hooks/output_gate.py            # Stop hook target
    python3 .claude/hooks/output_gate.py --selftest  # offline regression
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))

try:
    from anti_drift import DRIFT_PATTERNS
except Exception:
    DRIFT_PATTERNS = [
        "是否继续", "要不要继续", "还是等其他条件", "请指示下一步",
        "需要我继续", "等待用户", "你决定", "需要继续吗",
        "I can continue if", "Should I continue", "wait for",
    ]


def detect_drift(msg: str) -> list[str]:
    """Return list of drift patterns found in message."""
    if not msg or not isinstance(msg, str):
        return []
    return [p for p in DRIFT_PATTERNS if re.search(re.escape(p), msg, re.IGNORECASE)]


def main() -> None:
    if "--selftest" in sys.argv:
        sys.exit(_selftest())

    # FAIL-OPEN: any error reading/parsing → silent pass
    try:
        raw = sys.stdin.buffer.read()
        event = json.loads(raw.decode("utf-8", "replace") or "{}")
    except Exception:
        sys.exit(0)

    try:
        msg = event.get("last_assistant_message") or ""
        if not isinstance(msg, str) or not msg.strip():
            sys.exit(0)

        hits = detect_drift(msg)
        if not hits:
            sys.exit(0)

        # Check if drift is at the END of the response (last 500 chars)
        # A drift pattern in the middle of a long technical explanation is less concerning
        tail = msg[-500:] if len(msg) > 500 else msg
        tail_hits = [p for p in hits if re.search(re.escape(p), tail, re.IGNORECASE)]
        if not tail_hits:
            # Pattern found only in earlier context, not in the conclusion
            sys.exit(0)

        warning = (
            f"[output-gate] 检测到回合末尾漂移话术: {', '.join(tail_hits[:3])}。"
            f"违反回合协议(结尾应为下一行动或BLOCKED)。"
            f"此为 fail-open 警告——当前未阻塞回合，后续应重写。"
        )
        print(json.dumps({"systemMessage": warning}, ensure_ascii=False))
    except Exception:
        pass
    sys.exit(0)


def _selftest() -> int:
    """Regression tests. Returns 0 if healthy."""
    checks: list[tuple[str, bool]] = []

    # detect_drift
    checks.append(("empty -> []", detect_drift("") == []))
    checks.append(("clean -> []", detect_drift("下一行动: F-009 WebVPN 攻击") == []))
    checks.append(("BLOCKED ok", detect_drift("BLOCKED: safe_frontier 为空") == []))
    checks.append(("是否继续 detected", "是否继续" in " ".join(detect_drift("需要我是否继续吗"))))
    checks.append(("要不要继续 detected", "要不要继续" in " ".join(detect_drift("要不要继续等一下"))))
    checks.append(("你决定 detected", "你决定" in " ".join(detect_drift("你决定吧"))))
    checks.append(("English detected", "Should I continue" in " ".join(detect_drift("Should I continue now?"))))

    # DRIFT_PATTERNS loaded (from anti_drift or inline fallback)
    checks.append(("DRIFT_PATTERNS non-empty", len(DRIFT_PATTERNS) >= 5))

    # tail check: pattern deep in context, not in tail → should not flag
    long_clean = ("a" * 600) + "\n下一行动: WebVPN 滑块破解。"
    checks.append(("deep pattern not in tail", detect_drift(long_clean) == []))

    bad = [n for n, ok in checks if not ok]
    for n, ok in checks:
        print(("ok   " if ok else "FAIL ") + n, file=sys.stderr)
    print("output_gate selftest " + ("passed" if not bad else f"FAILED ({len(bad)})"), file=sys.stderr)
    return 0 if not bad else 1


if __name__ == "__main__":
    main()
