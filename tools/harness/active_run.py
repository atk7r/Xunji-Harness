"""Strict read-only resolver for Xunji's authoritative active-run pointer."""

from __future__ import annotations

import argparse
from pathlib import Path
import re
import tempfile


ROOT = Path(__file__).resolve().parents[2]
RUNS = ROOT / "runs"
POINTER = ROOT / ".claude" / "xunji_active_run"
_RUN_NAME = re.compile(r"[A-Za-z0-9._-]{1,256}")


class ActiveRunError(ValueError):
    pass


def resolve(
    *,
    root: str | Path = ROOT,
    runs_root: str | Path | None = None,
    pointer: str | Path | None = None,
) -> Path:
    """Resolve only the explicit pointer; never guess the newest run."""
    base = Path(root).resolve()
    runs = Path(runs_root).resolve() if runs_root is not None else base / "runs"
    marker = Path(pointer) if pointer is not None else base / ".claude" / "xunji_active_run"
    try:
        raw = marker.read_text(encoding="utf-8", errors="strict")
    except Exception as exc:
        raise ActiveRunError("ACTIVE_RUN_POINTER_MISSING") from exc
    if len(raw.encode("utf-8")) > 4096 or raw != raw.strip() + "\n" \
            or "\n" in raw.strip() or "\r" in raw:
        raise ActiveRunError("ACTIVE_RUN_POINTER_SHAPE_INVALID")
    value = raw.strip()
    candidate = Path(value)
    if not candidate.is_absolute():
        candidate = base / candidate
    try:
        resolved = candidate.resolve(strict=True)
        relative = resolved.relative_to(runs.resolve(strict=True))
    except Exception as exc:
        raise ActiveRunError("ACTIVE_RUN_POINTER_OUTSIDE_RUNS") from exc
    if len(relative.parts) != 1 or not _RUN_NAME.fullmatch(relative.name) \
            or not resolved.is_dir():
        raise ActiveRunError("ACTIVE_RUN_POINTER_TARGET_INVALID")
    if not any((resolved / name).is_file() for name in (
        "target.md", "frontier.md", "evidence.md", "decisions.md", "review.md",
    )):
        raise ActiveRunError("ACTIVE_RUN_POINTER_NOT_A_RUN")
    return resolved


def _selftest() -> int:
    with tempfile.TemporaryDirectory(prefix="xunji-active-run-") as tmp:
        root = Path(tmp)
        runs = root / "runs"
        run = runs / "demo_20260101"
        run.mkdir(parents=True)
        (run / "frontier.md").write_text("# Frontier\n", encoding="utf-8")
        marker = root / ".claude" / "xunji_active_run"
        marker.parent.mkdir()
        marker.write_text("runs/demo_20260101\n", encoding="utf-8")
        valid = resolve(root=root) == run.resolve()

        marker.write_text("runs/demo_20260101\nextra\n", encoding="utf-8")
        malformed_rejected = False
        try:
            resolve(root=root)
        except ActiveRunError as exc:
            malformed_rejected = str(exc) == "ACTIVE_RUN_POINTER_SHAPE_INVALID"

        outside = root / "outside"
        outside.mkdir()
        (outside / "frontier.md").write_text("# Outside\n", encoding="utf-8")
        marker.write_text(str(outside) + "\n", encoding="utf-8")
        outside_rejected = False
        try:
            resolve(root=root)
        except ActiveRunError as exc:
            outside_rejected = str(exc) == "ACTIVE_RUN_POINTER_OUTSIDE_RUNS"

        marker.unlink()
        missing_rejected = False
        try:
            resolve(root=root)
        except ActiveRunError as exc:
            missing_rejected = str(exc) == "ACTIVE_RUN_POINTER_MISSING"

    checks = [
        ("exact relative pointer resolves", valid),
        ("multi-line pointer is rejected", malformed_rejected),
        ("outside absolute pointer is rejected", outside_rejected),
        ("missing pointer never guesses a run", missing_rejected),
    ]
    bad = [name for name, ok in checks if not ok]
    for name, ok in checks:
        print(("ok   " if ok else "FAIL ") + name)
    print("active_run selftest " + ("passed" if not bad else f"FAILED ({len(bad)})"))
    return 0 if not bad else 1


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--selftest", action="store_true", required=True)
    parser.parse_args(argv)
    return _selftest()


if __name__ == "__main__":
    raise SystemExit(main())
