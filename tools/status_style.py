#!/usr/bin/env python3
"""Small terminal styling helpers for Xunji operator-facing status output."""
from __future__ import annotations

import os
import sys

RESET = "\033[0m"
COLORS = {
    "gray": "\033[90m",
    "red": "\033[31m",
    "green": "\033[32m",
    "yellow": "\033[33m",
    "blue": "\033[34m",
    "purple": "\033[35m",
    "cyan": "\033[36m",
    "white": "\033[37m",
    "bold": "\033[1m",
}

PHASE_CN = {
    "Setup": "准备运行",
    "Root Orchestrator": "主驾驶调度",
    "Hunter": "验证挖掘",
    "Reviewer": "复审把关",
    "Report": "报告整理",
}
PHASE_COLOR = {
    "Setup": "blue",
    "Root Orchestrator": "cyan",
    "Hunter": "yellow",
    "Reviewer": "purple",
    "Report": "green",
}


def color_enabled() -> bool:
    if os.environ.get("NO_COLOR") or os.environ.get("XUNJI_NO_COLOR"):
        return False
    return sys.stdout.isatty() or os.environ.get("XUNJI_COLOR") == "1"


def paint(text: object, color: str, *, enabled: bool | None = None) -> str:
    s = str(text)
    if enabled is None:
        enabled = color_enabled()
    code = COLORS.get(color)
    return f"{code}{s}{RESET}" if enabled and code else s


def tag(text: object, color: str = "white", *, enabled: bool | None = None) -> str:
    return paint(f"[{text}]", color, enabled=enabled)


def field(label: object, value: object, color: str = "gray", *, enabled: bool | None = None) -> str:
    return f"{tag(label, color, enabled=enabled)} {value}"


def phase_display(phase: object, *, enabled: bool | None = None, bracket: bool = True) -> str:
    raw = str(phase or "").strip() or "未知阶段"
    cn = PHASE_CN.get(raw)
    body = f"{raw}｜{cn}" if cn else raw
    color = PHASE_COLOR.get(raw, "white")
    return tag(body, color, enabled=enabled) if bracket else paint(body, color, enabled=enabled)


def status_tag(label: str, color: str, *, enabled: bool | None = None) -> str:
    return tag(label, color, enabled=enabled)


def box(title: str, rows: list[str], *, color: str = "cyan", enabled: bool | None = None) -> str:
    line = "─" * 56
    head = f"╭─ {tag('Xunji', color, enabled=enabled)} {tag(title, color, enabled=enabled)} {line}"
    return "\n".join([head, *[f"│ {row}" for row in rows], f"╰{line}"])


def _selftest() -> int:
    plain = box("运行态快照", [field("当前阶段", phase_display("Hunter", enabled=False), "yellow", enabled=False)], enabled=False)
    colored = box("运行态快照", [field("当前阶段", phase_display("Hunter", enabled=True), "yellow", enabled=True)], enabled=True)
    checks = [
        ("plain output keeps bracket tags", "[Xunji] [运行态快照]" in plain and "[Hunter｜验证挖掘]" in plain),
        ("colored output has ansi", "\033[" in colored and "[Hunter｜验证挖掘]" in colored),
        ("NO_COLOR disables default", isinstance(color_enabled(), bool)),
    ]
    bad = [name for name, ok in checks if not ok]
    for name, ok in checks:
        print(("ok   " if ok else "FAIL ") + name)
    print("status_style selftest " + ("passed" if not bad else f"FAILED ({len(bad)})"))
    return 0 if not bad else 1


if __name__ == "__main__":
    if "--selftest" in sys.argv:
        raise SystemExit(_selftest())
    print(box("样式预览", [
        field("阶段", phase_display("Root Orchestrator"), "cyan"),
        field("可以停止", "否", "red"),
        field("下一步", "继续推进可行动开放前线", "green"),
    ]))
