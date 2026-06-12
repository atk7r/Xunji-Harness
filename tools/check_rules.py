from __future__ import annotations

import re
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]

LEGACY_DIRS = [
    "apps",
    "schemas",
    "prompts",
    "policies",
    "examples",
    "tests",
    "artifacts",
]

WATCH_DIRS = [
    ".claude",
    "docs",
    "tools",
]

SKIP_DIRS = {
    ".venv",
    ".git",
    "__pycache__",
    ".pytest_cache",
    ".ruff_cache",
    ".state",
    "observations",
    "reports",
    "deepseek-project",
}

SKIP_FILES = {
    Path("tools/check_rules.py"),
    Path("tools/check_hook.py"),
    Path(".claude/hooks/safety_gate.py"),
    Path(".claude/hooks/safety_rules.json"),
    # Sanctioned, guard-routed active-verification tools (Active verification
    # doctrine, CLAUDE.md). These may name scanners as sensors; weaponization
    # references elsewhere in the tree are still caught.
    Path("tools/scan.py"),
    Path("tools/probe.py"),
    Path("tools/render.py"),
    Path("tools/harness/guard.py"),
    Path("tools/harness/__init__.py"),
}

FORBIDDEN_FILE_PATTERNS = [
    re.compile(r"(^|[\\/])poc([\\/]|$)", re.IGNORECASE),
    re.compile(r"(^|[\\/]).*exploit.*\.py$", re.IGNORECASE),
    re.compile(r"(^|[\\/]).*attack.*\.py$", re.IGNORECASE),
    re.compile(r"(^|[\\/]).*scanner.*\.py$", re.IGNORECASE),
]

FORBIDDEN_TEXT_PATTERNS = [
    re.compile(r"\bsqlmap\b", re.IGNORECASE),
    re.compile(r"\bhydra\b", re.IGNORECASE),
    re.compile(r"\bmasscan\b", re.IGNORECASE),
    re.compile(r"\bmetasploit\b|\bmsfconsole\b", re.IGNORECASE),
    re.compile(r"apps\.orchestrator", re.IGNORECASE),
    re.compile(r"schemas/action\.schema\.json", re.IGNORECASE),
    re.compile(r"prompts/planner\.system\.md", re.IGNORECASE),
]

REQUIRED_FILES = [
    Path("CLAUDE.md"),
    Path("docs/ROUTER.md"),
    Path("docs/WORKFLOW.md"),
    Path("docs/cognition/README.md"),
]

REQUIRED_TEXT: dict[Path, list[str]] = {}


def relative(path: Path) -> Path:
    return path.relative_to(ROOT)


def iter_text_files() -> list[Path]:
    files: list[Path] = []
    for dirname in WATCH_DIRS:
        base = ROOT / dirname
        if not base.exists():
            continue
        for path in base.rglob("*"):
            rel_parts = path.relative_to(ROOT).parts
            if any(part in SKIP_DIRS for part in rel_parts):
                continue
            if path.is_file():
                files.append(path)
    for name in ("README.md", "CLAUDE.md", "pyproject.toml", ".gitignore"):
        path = ROOT / name
        if path.exists():
            files.append(path)
    return files


def main() -> int:
    errors: list[str] = []
    warnings: list[str] = []

    for dirname in LEGACY_DIRS:
        path = ROOT / dirname
        if path.exists():
            errors.append(f"legacy directory exists: {dirname}")

    for rel in REQUIRED_FILES:
        if not (ROOT / rel).exists():
            errors.append(f"required file missing: {rel}")

    poc_dir = ROOT / "poc"
    if poc_dir.exists():
        children = [p for p in poc_dir.rglob("*") if p.is_file()]
        if children:
            errors.append("poc directory contains files")
        else:
            warnings.append("empty poc directory still exists")

    for path in ROOT.rglob("*"):
        rel_parts = path.relative_to(ROOT).parts
        if any(part in SKIP_DIRS for part in rel_parts):
            continue
        if not path.is_file():
            continue
        rel = relative(path)
        rel_text = str(rel).replace("\\", "/")
        if rel in SKIP_FILES:
            continue
        for pattern in FORBIDDEN_FILE_PATTERNS:
            if pattern.search(rel_text):
                errors.append(f"forbidden file path: {rel_text}")

    for path in iter_text_files():
        rel = relative(path)
        if rel in SKIP_FILES:
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        for pattern in FORBIDDEN_TEXT_PATTERNS:
            if pattern.search(text):
                errors.append(f"forbidden text pattern {pattern.pattern!r} in {rel}")

    for rel, required_items in REQUIRED_TEXT.items():
        path = ROOT / rel
        if not path.exists():
            continue
        text = path.read_text(encoding="utf-8", errors="replace")
        for required in required_items:
            if required not in text:
                errors.append(f"{rel} missing required text: {required}")

    if warnings:
        print("warnings")
        for warning in warnings:
            print(f"- {warning}")

    if errors:
        print("rule check failed")
        for error in errors:
            print(f"- {error}")
        return 1

    print("rule check passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
