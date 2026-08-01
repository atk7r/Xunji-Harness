#!/usr/bin/env python3
"""Check that Codex does not grow a parallel hook safety runtime."""
from __future__ import annotations

import argparse
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

FORBIDDEN_CODEX_HOOK_PATHS = [
    Path(".codex/hooks"),
    Path(".codex/hooks.json"),
]


def check(root: Path = ROOT) -> list[str]:
    errors: list[str] = []
    for rel in FORBIDDEN_CODEX_HOOK_PATHS:
        if (root / rel).exists():
            errors.append(f"{rel}: Codex hook runtime is not maintained; use .claude/hooks as the only hook boundary")
    return errors


def _selftest() -> int:
    d = Path(tempfile.mkdtemp())
    clean = d / "clean"
    dirty = d / "dirty"
    clean.mkdir()
    (dirty / ".codex" / "hooks").mkdir(parents=True)
    dirty_json = d / "dirty_json"
    (dirty_json / ".codex").mkdir(parents=True)
    (dirty_json / ".codex" / "hooks.json").write_text("{}", encoding="utf-8")
    checks = [
        ("clean tree passes", check(clean) == []),
        ("codex hooks dir fails", any(".codex/hooks" in e for e in check(dirty))),
        ("codex hooks.json fails", any(".codex/hooks.json" in e for e in check(dirty_json))),
    ]
    bad = [name for name, ok in checks if not ok]
    for name, ok in checks:
        print(("ok   " if ok else "FAIL ") + name)
    print("runtime boundary selftest " + ("passed" if not bad else f"FAILED ({len(bad)})"))
    return 0 if not bad else 1


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Check Codex/Claude runtime boundary.")
    parser.add_argument("--selftest", action="store_true", help="run local regression tests")
    args = parser.parse_args(argv)
    if args.selftest:
        return _selftest()
    errors = check()
    if errors:
        print("runtime boundary check failed")
        for e in errors:
            print(f"- {e}")
        return 1
    print("runtime boundary check passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
