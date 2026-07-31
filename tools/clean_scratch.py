#!/usr/bin/env python3
"""Plan or explicitly apply bounded TTL cleanup for Xunji scratch directories."""
from __future__ import annotations

import argparse
import json
import os
import tempfile
import time
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRATCH_ROOTS = (".scratch", ".cache/xunji", "review/tmp")


def candidates(root: Path, *, older_than_days: int, now: float | None = None) -> list[dict]:
    if older_than_days < 1 or older_than_days > 3650:
        raise ValueError("SCRATCH_TTL_INVALID")
    base = root.resolve()
    cutoff = float(now if now is not None else time.time()) - older_than_days * 86400
    rows: list[dict] = []
    for relative in SCRATCH_ROOTS:
        scratch = (base / relative).resolve()
        try:
            scratch.relative_to(base)
        except ValueError as exc:
            raise ValueError("SCRATCH_ROOT_ESCAPE") from exc
        if not scratch.is_dir() or scratch.is_symlink():
            continue
        for path in sorted(scratch.rglob("*")):
            if path.is_symlink() or not path.is_file():
                continue
            info = path.stat()
            if info.st_mtime < cutoff:
                rows.append({
                    "path": path.relative_to(base).as_posix(),
                    "size": info.st_size,
                    "mtime": info.st_mtime,
                })
    return rows


def apply(root: Path, rows: list[dict]) -> int:
    base = root.resolve()
    removed = 0
    allowed = [(base / rel).resolve() for rel in SCRATCH_ROOTS]
    for row in rows:
        path = (base / str(row["path"])).resolve()
        if not any(path != scope and scope in path.parents for scope in allowed):
            raise ValueError("SCRATCH_DELETE_OUTSIDE_SCOPE")
        try:
            info = path.lstat()
        except FileNotFoundError:
            continue
        if path.is_symlink() or not path.is_file() \
                or info.st_size != int(row["size"]) \
                or info.st_mtime != float(row["mtime"]):
            raise ValueError("SCRATCH_DELETE_IDENTITY_CHANGED")
        path.unlink()
        removed += 1
    return removed


def _selftest() -> int:
    root = Path(tempfile.mkdtemp())
    (root / ".scratch").mkdir()
    old = root / ".scratch" / "old.log"
    old.write_text("old", encoding="utf-8")
    fresh = root / ".scratch" / "fresh.log"
    fresh.write_text("fresh", encoding="utf-8")
    now = 2_000_000_000.0
    os.utime(old, (now - 10 * 86400, now - 10 * 86400))
    os.utime(fresh, (now, now))
    rows = candidates(root, older_than_days=7, now=now)
    dry_run_preserved = old.exists()
    removed = apply(root, rows)
    checks = [
        ("TTL plan is limited to old regular files",
         [item["path"] for item in rows] == [".scratch/old.log"]),
        ("planning is dry-run and preserves bytes", dry_run_preserved),
        ("explicit apply removes only the frozen candidate",
         removed == 1 and not old.exists() and fresh.exists()),
    ]
    failed = [name for name, ok in checks if not ok]
    for name, ok in checks:
        print(("ok   " if ok else "FAIL ") + name)
    print("clean_scratch selftest " + ("passed" if not failed else "FAILED"))
    return 0 if not failed else 1


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--older-than", type=int, default=30, metavar="DAYS")
    parser.add_argument("--dry-run", action="store_true",
                        help="explicitly select the default non-deleting mode")
    parser.add_argument("--apply", action="store_true",
                        help="delete only the identity-frozen listed files")
    parser.add_argument("--selftest", action="store_true")
    args = parser.parse_args()
    if args.selftest:
        return _selftest()
    if args.dry_run and args.apply:
        parser.error("--dry-run and --apply are mutually exclusive")
    try:
        rows = candidates(ROOT, older_than_days=args.older_than)
        removed = apply(ROOT, rows) if args.apply else 0
    except ValueError as exc:
        parser.error(str(exc))
    print(json.dumps({
        "schema": "xunji.scratch-cleanup-plan.v1",
        "mode": "apply" if args.apply else "dry-run",
        "older_than_days": args.older_than,
        "roots": list(SCRATCH_ROOTS),
        "candidates": rows,
        "candidate_bytes": sum(int(row["size"]) for row in rows),
        "removed": removed,
    }, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
