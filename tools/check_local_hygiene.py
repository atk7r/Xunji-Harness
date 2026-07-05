#!/usr/bin/env python3
"""Local-only hygiene checks for files that should never become secret sinks."""
from __future__ import annotations

import argparse
import re
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

SECRET_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    ("github-token", re.compile(r"\bgh[pousr]_[A-Za-z0-9_]{20,}\b")),
    ("ark-api-key", re.compile(r"\bark-[A-Za-z0-9_-]{20,}\b")),
    ("generic-password-assignment", re.compile(r"(?i)\b(password|passwd|token|secret|api[_-]?key)\s*=\s*[^;\s\"']{8,}")),
    ("credential-helper-inline", re.compile(r"credential\.helper=.*(password|token|secret)", re.IGNORECASE)),
]

LOCAL_FILES = [
    ROOT / ".claude" / "settings.local.json",
]


def scan_file(path: Path) -> list[str]:
    if not path.exists():
        return []
    issues: list[str] = []
    text = path.read_text(encoding="utf-8", errors="replace")
    for lineno, line in enumerate(text.splitlines(), 1):
        for category, pattern in SECRET_PATTERNS:
            if pattern.search(line):
                try:
                    rel = path.relative_to(ROOT)
                except ValueError:
                    rel = path
                issues.append(f"{rel}:{lineno}: credential-looking string ({category})")
                break
    return issues


def check(paths: list[Path] | None = None) -> list[str]:
    return [issue for path in (paths or LOCAL_FILES) for issue in scan_file(path)]


def _selftest() -> int:
    d = Path(tempfile.mkdtemp())
    clean = d / "clean.json"
    clean.write_text('{"allow":["Bash(python3 tools/check_run.py runs/x)"]}\n', encoding="utf-8")
    dirty = d / "dirty.json"
    dirty.write_text('{"allow":["credential.helper=!f(){ echo password=gho_abcdefghijklmnopqrstuvwxyz; }"]}\n',
                     encoding="utf-8")
    clean_issues = check([clean])
    dirty_issues = check([dirty])
    leaked = any("abcdefghijklmnopqrstuvwxyz" in i for i in dirty_issues)
    checks = [
        ("clean file has no issues", clean_issues == []),
        ("dirty file reports category", dirty_issues and "github-token" in dirty_issues[0]),
        ("dirty report redacts value", not leaked),
    ]
    bad = [name for name, ok in checks if not ok]
    for name, ok in checks:
        print(("ok   " if ok else "FAIL ") + name)
    print("local hygiene selftest " + ("passed" if not bad else f"FAILED ({len(bad)})"))
    return 0 if not bad else 1


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Check local config for credential-looking strings.")
    parser.add_argument("--selftest", action="store_true", help="run local regression tests")
    args = parser.parse_args(argv)
    if args.selftest:
        return _selftest()
    issues = check()
    if issues:
        print("local hygiene check failed")
        for issue in issues:
            print(f"- {issue}")
        return 1
    print("local hygiene check passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
