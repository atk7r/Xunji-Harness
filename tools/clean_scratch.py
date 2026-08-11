#!/usr/bin/env python3
"""Bounded, age-based cleanup for local scratch output.

Dry-run is the default.  The cleaner never enters runs/, review/, reports/, poc/,
or artifact quarantine, never follows symlinks, and only removes files under the
explicit managed roots below.
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PROTECTED_TOP_LEVEL = {"runs", "review", "reports", "poc", "artifacts"}


def _within(path: Path, parent: Path) -> bool:
    try:
        path.relative_to(parent)
        return True
    except ValueError:
        return False


def _managed_roots(root: Path, *, include_caches: bool) -> list[tuple[str, Path]]:
    roots = [("tmp", root / "tmp")]
    if include_caches:
        roots.extend((name, root / name) for name in (".pytest_cache", ".ruff_cache"))
        excluded = PROTECTED_TOP_LEVEL | {".git", ".venv", "venv", "tmp"}
        for dirpath, dirnames, _filenames in os.walk(
                root, topdown=True, followlinks=False):
            current = Path(dirpath)
            rel = current.relative_to(root)
            if rel.parts and rel.parts[0] in excluded:
                dirnames[:] = []
                continue
            kept: list[str] = []
            for name in dirnames:
                child = current / name
                if child.is_symlink() or (current == root and name in excluded):
                    continue
                if name == "__pycache__":
                    roots.append(("python-cache", child))
                    continue
                kept.append(name)
            dirnames[:] = kept
    return roots


def inventory(
    root: Path,
    *,
    older_than_days: float,
    include_caches: bool = False,
    now: float | None = None,
) -> tuple[list[dict], list[str]]:
    if older_than_days < 0:
        raise ValueError("--older-than must be non-negative")
    now = time.time() if now is None else now
    cutoff = now - older_than_days * 86400
    root_resolved = root.resolve(strict=False)
    candidates: list[dict] = []
    warnings: list[str] = []
    seen: set[Path] = set()
    for scope, managed_root in _managed_roots(root, include_caches=include_caches):
        if not managed_root.exists():
            continue
        if managed_root.is_symlink():
            warnings.append(f"skipped symlink cleanup root: {managed_root.relative_to(root)}")
            continue
        managed_resolved = managed_root.resolve(strict=False)
        if not _within(managed_resolved, root_resolved) \
                or managed_root.name in PROTECTED_TOP_LEVEL:
            raise ValueError(f"managed cleanup root escaped repository: {managed_root}")
        for dirpath, dirnames, filenames in os.walk(managed_root, topdown=True, followlinks=False):
            current = Path(dirpath)
            kept_dirs: list[str] = []
            for name in dirnames:
                child = current / name
                if child.is_symlink():
                    warnings.append(f"skipped symlink directory: {child.relative_to(root)}")
                else:
                    kept_dirs.append(name)
            dirnames[:] = kept_dirs
            for name in filenames:
                path = current / name
                if path in seen:
                    continue
                seen.add(path)
                if path.is_symlink():
                    warnings.append(f"skipped symlink file: {path.relative_to(root)}")
                    continue
                try:
                    stat = path.stat()
                    resolved = path.resolve(strict=True)
                except OSError as exc:
                    warnings.append(
                        f"unreadable scratch entry: {path.relative_to(root)} ({exc.__class__.__name__})"
                    )
                    continue
                if not _within(resolved, managed_resolved):
                    warnings.append(f"skipped escaped entry: {path.relative_to(root)}")
                    continue
                if stat.st_mtime <= cutoff:
                    candidates.append({
                        "scope": scope,
                        "path": path.relative_to(root).as_posix(),
                        "bytes": stat.st_size,
                        "mtime": stat.st_mtime,
                    })
    candidates.sort(key=lambda item: item["path"])
    return candidates, warnings


def apply_cleanup(root: Path, candidates: list[dict]) -> tuple[int, int, list[str]]:
    root_resolved = root.resolve(strict=False)
    allowed_roots = [path.resolve(strict=False) for path in (
        root / "tmp", root / ".pytest_cache", root / ".ruff_cache",
    ) if not path.is_symlink()]
    removed_files = 0
    removed_bytes = 0
    warnings: list[str] = []
    parents: set[Path] = set()
    for item in candidates:
        rel = Path(str(item.get("path") or ""))
        path = root / rel
        try:
            resolved = path.resolve(strict=True)
        except OSError:
            continue
        if path.is_symlink() or not _within(resolved, root_resolved):
            warnings.append(f"refused non-regular cleanup entry: {rel.as_posix()}")
            continue
        in_named_root = any(_within(resolved, allowed) for allowed in allowed_roots)
        in_python_cache = "__pycache__" in rel.parts and not (
            rel.parts and rel.parts[0] in PROTECTED_TOP_LEVEL | {".git", ".venv", "venv"}
        )
        if not (in_named_root or in_python_cache) or not path.is_file():
            warnings.append(f"refused out-of-scope cleanup entry: {rel.as_posix()}")
            continue
        try:
            size = path.stat().st_size
            path.unlink()
            removed_files += 1
            removed_bytes += size
            parents.add(path.parent)
        except OSError as exc:
            warnings.append(f"failed to remove {rel.as_posix()}: {exc.__class__.__name__}")
    for parent in sorted(parents, key=lambda value: len(value.parts), reverse=True):
        current = parent
        while current != root and _within(current.resolve(strict=False), root_resolved):
            if current.name in PROTECTED_TOP_LEVEL:
                break
            try:
                current.rmdir()
            except OSError:
                break
            current = current.parent
    return removed_files, removed_bytes, warnings


def _selftest() -> int:
    root = Path(tempfile.mkdtemp())
    checks: list[tuple[str, bool]] = []
    now = 2_000_000_000.0
    try:
        old_file = root / "tmp" / "probe" / "old" / "body.html"
        new_file = root / "tmp" / "probe" / "new" / "body.html"
        protected = root / "runs" / "demo" / "evidence" / "old.html"
        cache_file = root / "tools" / "__pycache__" / "x.pyc"
        for path in (old_file, new_file, protected, cache_file):
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("x", encoding="utf-8")
        os.utime(old_file, (now - 10 * 86400, now - 10 * 86400))
        os.utime(new_file, (now - 3600, now - 3600))
        os.utime(protected, (now - 10 * 86400, now - 10 * 86400))
        os.utime(cache_file, (now - 10 * 86400, now - 10 * 86400))
        candidates, warnings = inventory(
            root, older_than_days=7, include_caches=True, now=now,
        )
        candidate_paths = {item["path"] for item in candidates}
        checks.append(("old tmp file selected", "tmp/probe/old/body.html" in candidate_paths))
        checks.append(("new tmp file retained", "tmp/probe/new/body.html" not in candidate_paths))
        checks.append(("protected run never scanned", "runs/demo/evidence/old.html" not in candidate_paths))
        checks.append(("explicit python cache selected", "tools/__pycache__/x.pyc" in candidate_paths))
        checks.append(("inventory is content-free", all("content" not in item for item in candidates)))
        checks.append(("dry-run changes nothing", old_file.exists() and not warnings))
        removed, _bytes, apply_warnings = apply_cleanup(root, candidates)
        checks.append(("apply removes only selected files", removed == 2 and not old_file.exists()
                       and not cache_file.exists() and new_file.exists() and protected.exists()))
        checks.append(("clean apply has no warnings", not apply_warnings))

        symlink_root = root / "symlink-case"
        symlink_target = symlink_root / "target"
        symlink_target.mkdir(parents=True)
        escaped_file = symlink_target / "old.html"
        escaped_file.write_text("x", encoding="utf-8")
        (symlink_root / "tmp").symlink_to(symlink_target, target_is_directory=True)
        symlink_candidates, symlink_warnings = inventory(
            symlink_root, older_than_days=0, now=now,
        )
        refused, _refused_bytes, refusal_warnings = apply_cleanup(
            symlink_root,
            [{"scope": "tmp", "path": "tmp/old.html", "bytes": 1, "mtime": 0}],
        )
        checks.append(("symlinked managed root is never traversed",
                       not symlink_candidates
                       and any("symlink cleanup root" in item for item in symlink_warnings)))
        checks.append(("apply refuses an entry injected through a symlinked root",
                       refused == 0 and escaped_file.is_file()
                       and any("out-of-scope" in item for item in refusal_warnings)))
    finally:
        shutil.rmtree(root, ignore_errors=True)
    bad = [name for name, ok in checks if not ok]
    for name, ok in checks:
        print(("ok   " if ok else "FAIL ") + name)
    print("clean scratch selftest " + ("passed" if not bad else f"FAILED ({len(bad)})"))
    return 0 if not bad else 1


def main() -> int:
    parser = argparse.ArgumentParser(description="Age-based cleanup for managed Xunji scratch.")
    parser.add_argument("--older-than", type=float, required=False,
                        help="select entries at least this many days old")
    parser.add_argument("--include-caches", action="store_true",
                        help="also select project Python/test/lint caches outside protected roots")
    parser.add_argument("--apply", action="store_true",
                        help="remove selected regular files; default is dry-run")
    parser.add_argument("--dry-run", action="store_true",
                        help="explicitly request the default no-delete mode")
    parser.add_argument("--verbose", action="store_true", help="include selected paths")
    parser.add_argument("--selftest", action="store_true")
    args = parser.parse_args()
    if args.selftest:
        return _selftest()
    if args.older_than is None:
        parser.error("--older-than is required")
    if args.apply and args.dry_run:
        parser.error("choose --apply or --dry-run, not both")
    candidates, warnings = inventory(
        ROOT,
        older_than_days=args.older_than,
        include_caches=args.include_caches,
    )
    result = {
        "schema": "xunji.scratch-cleanup.v1",
        "mode": "apply" if args.apply else "dry-run",
        "older_than_days": args.older_than,
        "selected_files": len(candidates),
        "selected_bytes": sum(int(item["bytes"]) for item in candidates),
        "warnings": warnings,
    }
    if args.verbose:
        result["entries"] = candidates
    if args.apply:
        removed, removed_bytes, apply_warnings = apply_cleanup(ROOT, candidates)
        result.update({
            "removed_files": removed,
            "removed_bytes": removed_bytes,
            "warnings": [*warnings, *apply_warnings],
        })
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
