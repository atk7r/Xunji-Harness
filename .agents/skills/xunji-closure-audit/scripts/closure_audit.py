#!/usr/bin/env python3
"""Static wiring checks for Xunji closure audits.

Run from the repository root:
    python3 .agents/skills/xunji-closure-audit/scripts/closure_audit.py
"""
from __future__ import annotations

import argparse
import ast
import re
from pathlib import Path


DOC_ROOTS = [
    ".claude/skills",
    ".agents/skills",
    "docs",
]
DOC_FILES = ["CLAUDE.md", "AGENTS.md"]
SELFTEST_ROOTS = ["tools", ".claude/hooks", "sentinel"]


def _repo_root(raw: str | None) -> Path:
    root = Path(raw or ".").resolve()
    if not (root / "AGENTS.md").is_file() or not (root / "tools").is_dir():
        raise SystemExit(f"not a Xunji repo root: {root}")
    return root


def _markdown_files(root: Path) -> list[Path]:
    files: list[Path] = []
    for rel in DOC_ROOTS:
        p = root / rel
        if p.is_dir():
            files.extend(sorted(p.rglob("*.md")))
    for rel in DOC_FILES:
        p = root / rel
        if p.is_file():
            files.append(p)
    return files


def check_python_command_refs(root: Path) -> list[str]:
    missing: list[str] = []
    pattern = re.compile(r"\bpython3?\s+([./A-Za-z0-9_-]+\.py)\b")
    total = 0
    for path in _markdown_files(root):
        text = path.read_text(encoding="utf-8", errors="replace")
        for match in pattern.finditer(text):
            rel = match.group(1)
            target = Path(rel[2:] if rel.startswith("./") else rel)
            total += 1
            if not (root / target).exists():
                missing.append(f"{target} <- {path.relative_to(root)}")
    print(f"python_command_refs total={total} missing={len(missing)}")
    return missing


def _registered_selftests(root: Path) -> set[str]:
    text = (root / "tools/selftest_all.py").read_text(encoding="utf-8", errors="replace")
    tree = ast.parse(text)
    for node in tree.body:
        target = None
        value = None
        if isinstance(node, ast.AnnAssign):
            target = node.target
            value = node.value
        elif isinstance(node, ast.Assign) and node.targets:
            target = node.targets[0]
            value = node.value
        if isinstance(target, ast.Name) and target.id == "SUITES" and value is not None:
            try:
                suites = ast.literal_eval(value)
            except (ValueError, SyntaxError) as exc:
                raise SystemExit(f"could not evaluate SUITES in tools/selftest_all.py: {exc}") from exc
            registered: set[str] = set()
            for entry in suites:
                if not (
                    isinstance(entry, tuple)
                    and len(entry) >= 2
                    and isinstance(entry[1], list)
                    and entry[1]
                    and isinstance(entry[1][0], str)
                ):
                    raise SystemExit(f"unexpected SUITES entry shape: {entry!r}")
                registered.add(entry[1][0])
            return registered
    raise SystemExit("could not parse SUITES from tools/selftest_all.py")


def check_selftest_registry(root: Path) -> list[str]:
    registered = _registered_selftests(root)
    not_registered: list[str] = []
    total = 0
    for rel in SELFTEST_ROOTS:
        base = root / rel
        if not base.exists():
            continue
        for path in sorted(base.rglob("*.py")):
            repo_rel = path.relative_to(root).as_posix()
            if repo_rel == "tools/selftest_all.py":
                continue
            text = path.read_text(encoding="utf-8", errors="replace")
            if "--selftest" not in text:
                continue
            total += 1
            if repo_rel not in registered:
                not_registered.append(repo_rel)
    print(f"selftest_entrypoints total={total} not_registered={len(not_registered)}")
    return not_registered


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run Xunji static closure-audit checks.")
    parser.add_argument("--root", help="repository root; defaults to current directory")
    args = parser.parse_args(argv)

    root = _repo_root(args.root)
    failures: list[str] = []

    for item in check_python_command_refs(root):
        failures.append(f"MISSING_COMMAND {item}")
    for item in check_selftest_registry(root):
        failures.append(f"SELFTEST_NOT_REGISTERED {item}")

    if failures:
        for item in failures:
            print(item)
        print(f"closure_audit FAILED ({len(failures)} hard gap(s))")
        return 1
    print("closure_audit passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
