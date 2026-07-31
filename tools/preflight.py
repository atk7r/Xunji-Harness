#!/usr/bin/env python3
"""Read-only commit preflight: whitespace, sensitive diff, hygiene, fingerprint."""
from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
from pathlib import Path

import check_local_hygiene


ROOT = Path(__file__).resolve().parents[1]


def _git(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git", *args], cwd=ROOT, capture_output=True, text=True,
        encoding="utf-8", errors="replace", timeout=30, check=False,
    )


def sensitive_categories(text: str) -> list[str]:
    return sorted({
        category
        for category, pattern in check_local_hygiene.SECRET_PATTERNS
        if pattern.search(text)
    })


def untracked_paths(porcelain: str) -> list[str]:
    """Return exact untracked paths from NUL-delimited porcelain output."""
    return sorted({
        item[3:]
        for item in porcelain.split("\0")
        if item.startswith("?? ") and item[3:]
    })


def _diff_target(base_ref: str | None) -> tuple[str, ...]:
    # Explicit endpoints also accept Git's empty-tree object for an initial
    # push; unlike triple-dot syntax they do not require both sides to be
    # commits with a merge base.
    return (base_ref, "HEAD", "--") if base_ref else ("HEAD", "--")


def run(*, base_ref: str | None = None) -> dict:
    diff_target = _diff_target(base_ref)
    worktree_check = _git("diff", "--check", *diff_target)
    index_check = _git("diff", "--cached", "--check")
    worktree = _git("diff", "--no-ext-diff", "--binary", *diff_target)
    index = _git("diff", "--cached", "--no-ext-diff", "--binary", "HEAD", "--")
    status = _git("status", "--porcelain=v1", "-z", "--untracked-files=all")
    untracked = untracked_paths(status.stdout)
    git_ok = all(item.returncode == 0 for item in (
        worktree_check, index_check, worktree, index, status))
    diff_bytes = (
        worktree.stdout.encode("utf-8", "replace")
        + b"\0INDEX\0"
        + index.stdout.encode("utf-8", "replace")
    )
    categories = sensitive_categories(worktree.stdout + "\n" + index.stdout)
    hygiene = check_local_hygiene.check()
    return {
        "schema": "xunji.commit-preflight.v1",
        "scope": f"{base_ref}..HEAD" if base_ref else "working-tree-versus-HEAD",
        "ok": bool(
            git_ok and not worktree_check.stdout and not index_check.stdout
            and not untracked and not categories and not hygiene
        ),
        "reviewed_diff": hashlib.sha256(diff_bytes).hexdigest()[:16],
        "diff_sha256": hashlib.sha256(diff_bytes).hexdigest(),
        "checks": {
            "git_diff_check": (
                worktree_check.returncode == 0 and not worktree_check.stdout),
            "git_cached_diff_check": (
                index_check.returncode == 0 and not index_check.stdout),
            "untracked_diff_coverage": not untracked,
            "sensitive_diff": not categories,
            "local_hygiene": not hygiene,
        },
        "untracked_paths": untracked,
        "sensitive_categories": categories,
        "hygiene_issue_count": len(hygiene),
        "git_errors": [
            (item.stderr or "").strip()
            for item in (worktree_check, index_check, worktree, index, status)
            if item.returncode != 0
        ],
        "artifact_policy": (
            "CI may upload bench JSON and failure logs only; never runs/ or target artifacts"
        ),
    }


def _selftest() -> int:
    clean = "diff --git a/a b/a\n+safe = true\n"
    dirty = "".join([
        "diff --git a/a b/a\n+",
        "to", "ken", "=",
        "gh", "p", "_",
        "abcdefghijklmnopqrstuvwxyz",
        "\n",
    ])
    checks = [
        ("clean diff has no sensitive category", sensitive_categories(clean) == []),
        ("secret values are reduced to category names",
         sensitive_categories(dirty) == ["generic-password-assignment", "github-token"]
         and "abcdefghijklmnopqrstuvwxyz" not in repr(sensitive_categories(dirty))),
        ("fingerprint is stable", hashlib.sha256(clean.encode()).hexdigest()
         == hashlib.sha256(clean.encode()).hexdigest()),
        ("NUL-delimited untracked paths fail closed",
         untracked_paths("?? new.py\0 M tracked.py\0?? dir/space name.md\0")
         == ["dir/space name.md", "new.py"]),
        ("CI base ref selects the committed change range",
         _diff_target("base-sha") == ("base-sha", "HEAD", "--")),
    ]
    failed = [name for name, ok in checks if not ok]
    for name, ok in checks:
        print(("ok   " if ok else "FAIL ") + name)
    print("preflight selftest " + ("passed" if not failed else "FAILED"))
    return 0 if not failed else 1


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--selftest", action="store_true")
    parser.add_argument(
        "--base-ref",
        help="inspect committed changes between BASE and HEAD (for clean CI checkouts)",
    )
    args = parser.parse_args()
    if args.selftest:
        return _selftest()
    result = run(base_ref=args.base_ref)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
