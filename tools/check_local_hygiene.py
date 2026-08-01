#!/usr/bin/env python3
"""Local/publication hygiene checks for files that must stay local.

This is deliberately broader than a credential scanner. Xunji keeps real run
evidence, local runtime config, and tool runtimes out of the published repo even
when their contents are not classical secrets.
"""
from __future__ import annotations

import argparse
import re
import subprocess
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

FORBIDDEN_TRACKED_EXACT = {
    "config.ini": "local runtime config is ignored; keep only config.example.ini tracked",
    ".codex/hooks.json": "Codex hook runtime is not maintained; use .claude/hooks only",
    "review/review_bundle.json": "generated peer-review bundle is run/scope-local output",
}

FORBIDDEN_TRACKED_PREFIXES = {
    "runs/": "real run workbenches are local evidence, not published fixtures",
    ".codex/hooks/": "Codex hook runtime is not maintained; use .claude/hooks only",
}

ROOT_RUN_DIR_RE = re.compile(
    r"^[^/]+_20\d{6}(?:_20\d{6})?/",
)


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
    issues = [issue for path in (paths or LOCAL_FILES) for issue in scan_file(path)]
    if paths is None:
        issues.extend(check_publication_index())
    return issues


def _git_lines(args: list[str]) -> list[str]:
    try:
        proc = subprocess.run(
            ["git", *args],
            cwd=ROOT,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=20,
            check=False,
        )
    except Exception as e:  # noqa: BLE001 - hygiene should surface tool problems.
        return [f"__git_error__:{e!r}"]
    if proc.returncode != 0:
        msg = (proc.stderr or proc.stdout or "").strip()
        return [f"__git_error__:git {' '.join(args)} failed: {msg}"]
    return [line for line in proc.stdout.splitlines() if line.strip()]


def publication_issues_for_tracked(
    tracked: list[str],
    tracked_ignored: list[str] | None = None,
) -> list[str]:
    issues: list[str] = []
    for rel in tracked_ignored or []:
        issues.append(f"{rel}: tracked file is ignored by .gitignore; remove from index")
    for rel in tracked:
        reason = FORBIDDEN_TRACKED_EXACT.get(rel)
        if reason:
            issues.append(f"{rel}: {reason}")
            continue
        for prefix, prefix_reason in FORBIDDEN_TRACKED_PREFIXES.items():
            if rel.startswith(prefix) and rel != "runs/.gitkeep":
                issues.append(f"{rel}: {prefix_reason}")
                break
        else:
            if ROOT_RUN_DIR_RE.match(rel):
                issues.append(f"{rel}: root-level real run workbench must stay local")
    return issues


def check_publication_index() -> list[str]:
    tracked = _git_lines(["ls-files"])
    tracked_ignored = _git_lines(["ls-files", "-ci", "--exclude-standard"])
    git_errors = [
        line.removeprefix("__git_error__:")
        for line in [*tracked, *tracked_ignored]
        if line.startswith("__git_error__:")
    ]
    if git_errors:
        return [f"git index hygiene unavailable: {err}" for err in git_errors]
    return publication_issues_for_tracked(tracked, tracked_ignored)


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
    tracked_issues = publication_issues_for_tracked(
        [
            "README.md",
            "runs/.gitkeep",
            "runs/live_20260707/evidence.md",
            "school_20260707/evidence/body.html",
            "config.ini",
            ".codex/hooks/safety_gate.py",
            "review/review_bundle.json",
        ],
        ["config.ini"],
    )
    checks = [
        ("clean file has no issues", clean_issues == []),
        ("dirty file reports category", dirty_issues and "github-token" in dirty_issues[0]),
        ("dirty report redacts value", not leaked),
        ("publication allows runs/.gitkeep", not any("runs/.gitkeep" in i for i in tracked_issues)),
        ("publication rejects ignored tracked config", any("tracked file is ignored" in i for i in tracked_issues)),
        ("publication rejects tracked run evidence", any("runs/live_20260707" in i for i in tracked_issues)),
        ("publication rejects root run workbench", any("school_20260707" in i for i in tracked_issues)),
        ("publication rejects Codex hooks", any(".codex/hooks" in i for i in tracked_issues)),
        ("publication rejects generated review bundle",
         any("review/review_bundle.json" in i for i in tracked_issues)),
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
