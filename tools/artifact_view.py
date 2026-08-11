#!/usr/bin/env python3
"""Bounded, read-only inspection of run-owned evidence artifacts.

The tool never writes a run.  It accepts only regular non-symlink files below
``<run>/evidence/`` and exposes three bounded operations: byte range, literal
search, and printable ASCII strings.  Full-file ``Read`` is therefore not
required merely to inspect a multi-megabyte response body.
"""
from __future__ import annotations

import argparse
import contextlib
from dataclasses import dataclass
import io
import json
import os
import stat
import sys
import tempfile
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
RUNS_ROOT = ROOT / "runs"
SCHEMA = "xunji.artifact-view.v1"
AUTHORITY = "read-only local artifact view; no evidence or canonical-state authority"
READ_CHUNK = 64 * 1024
DEFAULT_SCAN_LIMIT = 8 * 1024 * 1024
MAX_SCAN_LIMIT = 64 * 1024 * 1024
MAX_RANGE_BYTES = 64 * 1024
MAX_PATTERN_BYTES = 512
MAX_MATCHES = 100
MAX_CONTEXT_BYTES = 256
MAX_STRINGS = 200
MAX_STRING_BYTES = 512


class ArtifactViewError(ValueError):
    """Stable fail-closed artifact-view diagnosis."""

    def __init__(self, code: str, detail: str = ""):
        self.code = code
        self.detail = detail
        super().__init__(f"{code}: {detail}" if detail else code)


@dataclass(frozen=True)
class BoundedArtifactRead:
    """One stable, bounded byte snapshot of a run-owned evidence artifact.

    The returned payload is never larger than ``scan_limit``.  The file and
    every parent component remain protected by the same no-follow, identity
    stable open used by the CLI views.
    """

    artifact: str
    file_size: int
    payload: bytes
    scanned_bytes: int
    scan_truncated: bool


def _fail(code: str, detail: str) -> None:
    raise ArtifactViewError(code, detail)


def _within(path: Path, parent: Path) -> bool:
    try:
        path.relative_to(parent)
        return True
    except ValueError:
        return False


def _reject_symlink_components(path: Path, anchor: Path, *, code: str) -> None:
    anchor_abs = Path(os.path.abspath(anchor))
    path_abs = Path(os.path.abspath(path))
    try:
        relative = path_abs.relative_to(anchor_abs)
    except ValueError:
        _fail(code, "path escaped its managed root")
    current = anchor_abs
    if current.is_symlink():
        _fail("ARTIFACT_VIEW_SYMLINK", "managed root must not be a symlink")
    for part in relative.parts:
        current = current / part
        if current.is_symlink():
            _fail("ARTIFACT_VIEW_SYMLINK", "artifact path must not contain symlinks")


def _resolve_run_dir(
    run_dir: str | Path,
    *,
    runs_root: str | Path = RUNS_ROOT,
) -> Path:
    root = Path(runs_root)
    raw = Path(run_dir)
    if not raw.is_absolute():
        raw = ROOT / raw
    _reject_symlink_components(raw, root, code="ARTIFACT_VIEW_RUN_OUTSIDE_ROOT")
    try:
        root_resolved = root.resolve(strict=True)
        run_resolved = raw.resolve(strict=True)
    except OSError as exc:
        _fail("ARTIFACT_VIEW_RUN_UNAVAILABLE", type(exc).__name__)
    if not root_resolved.is_dir() or not run_resolved.is_dir() \
            or not _within(run_resolved, root_resolved):
        _fail("ARTIFACT_VIEW_RUN_INVALID", "run must be a directory below runs root")
    return run_resolved


def resolve_artifact(
    run_dir: str | Path,
    artifact: str | Path,
    *,
    runs_root: str | Path = RUNS_ROOT,
) -> tuple[Path, Path, str]:
    """Resolve one explicit artifact into the selected run's evidence root."""
    run = _resolve_run_dir(run_dir, runs_root=runs_root)
    evidence = run / "evidence"
    _reject_symlink_components(
        evidence, run, code="ARTIFACT_VIEW_EVIDENCE_OUTSIDE_RUN",
    )
    try:
        evidence_resolved = evidence.resolve(strict=True)
    except OSError as exc:
        _fail("ARTIFACT_VIEW_EVIDENCE_UNAVAILABLE", type(exc).__name__)
    if evidence.is_symlink() or not evidence_resolved.is_dir():
        _fail("ARTIFACT_VIEW_EVIDENCE_INVALID", "evidence root must be a directory")

    raw_value = str(artifact or "")
    if not raw_value or "\x00" in raw_value:
        _fail("ARTIFACT_VIEW_PATH_INVALID", "artifact path must be non-empty")
    raw = Path(raw_value)
    if raw.is_absolute():
        candidate = raw
    elif raw.parts and raw.parts[0] == "evidence":
        candidate = run / raw
    else:
        candidate = evidence / raw
    _reject_symlink_components(
        candidate, evidence, code="ARTIFACT_VIEW_OUTSIDE_EVIDENCE",
    )
    try:
        resolved = candidate.resolve(strict=True)
    except OSError as exc:
        _fail("ARTIFACT_VIEW_ARTIFACT_UNAVAILABLE", type(exc).__name__)
    if not _within(resolved, evidence_resolved):
        _fail("ARTIFACT_VIEW_OUTSIDE_EVIDENCE", "artifact escaped evidence root")
    if candidate.is_symlink() or not resolved.is_file():
        _fail("ARTIFACT_VIEW_ARTIFACT_INVALID", "artifact must be a regular file")
    relative = resolved.relative_to(run).as_posix()
    return run, resolved, relative


def _identity(value: os.stat_result) -> tuple[int, int, int, int]:
    return (value.st_dev, value.st_ino, value.st_size, value.st_mtime_ns)


def _identity_unchanged(before: os.stat_result, after: os.stat_result) -> bool:
    return _identity(before) == _identity(after)


def _directory_flags() -> int:
    return (
        os.O_RDONLY
        | getattr(os, "O_CLOEXEC", 0)
        | getattr(os, "O_DIRECTORY", 0)
        | getattr(os, "O_NOFOLLOW", 0)
    )


def _open_directory_path(path: Path) -> int:
    """Open an absolute resolved directory one no-follow component at a time."""
    resolved = path.resolve(strict=True)
    if not resolved.is_absolute():
        _fail("ARTIFACT_VIEW_OPEN_FAILED", "managed root is not absolute")
    descriptor = os.open(os.path.sep, _directory_flags())
    try:
        for part in resolved.parts[1:]:
            child = os.open(part, _directory_flags(), dir_fd=descriptor)
            os.close(descriptor)
            descriptor = child
        return descriptor
    except OSError as exc:
        os.close(descriptor)
        _fail("ARTIFACT_VIEW_OPEN_FAILED", type(exc).__name__)


def _open_relative_regular(
    anchor: Path, relative: Path,
) -> tuple[int, int, tuple[tuple[int, int], ...]]:
    """Return leaf/parent fds plus every opened directory identity."""
    parts = relative.parts
    if not parts or any(part in {"", ".", ".."} for part in parts):
        _fail("ARTIFACT_VIEW_OPEN_FAILED", "artifact path is not a safe relative path")
    parent = _open_directory_path(anchor)
    parent_stat = os.fstat(parent)
    directory_chain = [(parent_stat.st_dev, parent_stat.st_ino)]
    try:
        for part in parts[:-1]:
            child = os.open(part, _directory_flags(), dir_fd=parent)
            os.close(parent)
            parent = child
            child_stat = os.fstat(parent)
            directory_chain.append((child_stat.st_dev, child_stat.st_ino))
        flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) \
            | getattr(os, "O_NOFOLLOW", 0)
        leaf = os.open(parts[-1], flags, dir_fd=parent)
        return leaf, parent, tuple(directory_chain)
    except OSError as exc:
        os.close(parent)
        _fail("ARTIFACT_VIEW_OPEN_FAILED", type(exc).__name__)


@contextlib.contextmanager
def _open_stable(path: Path, *, anchor: Path):
    """Open a file without a resolve/open gap in any artifact component."""
    try:
        anchor_resolved = anchor.resolve(strict=True)
        relative = path.relative_to(anchor_resolved)
    except (OSError, ValueError) as exc:
        _fail("ARTIFACT_VIEW_OPEN_FAILED", type(exc).__name__)
    descriptor, parent_descriptor, directory_chain = _open_relative_regular(
        anchor_resolved, relative)
    try:
        before = os.fstat(descriptor)
        try:
            path_stat = os.stat(
                relative.parts[-1], dir_fd=parent_descriptor,
                follow_symlinks=False,
            )
        except OSError as exc:
            _fail("ARTIFACT_VIEW_STAT_FAILED", type(exc).__name__)
        if not stat.S_ISREG(before.st_mode) or not stat.S_ISREG(path_stat.st_mode) \
                or (before.st_dev, before.st_ino) != (path_stat.st_dev, path_stat.st_ino):
            _fail("ARTIFACT_VIEW_ARTIFACT_CHANGED", "opened file no longer matches path")
        with os.fdopen(descriptor, "rb", closefd=False) as handle:
            yield handle, before
        after = os.fstat(descriptor)
        if not _identity_unchanged(before, after):
            _fail(
                "ARTIFACT_VIEW_ARTIFACT_CHANGED",
                "artifact changed during bounded inspection",
            )
        try:
            current_descriptor, current_parent, current_directory_chain = (
                _open_relative_regular(anchor_resolved, relative)
            )
            try:
                current_path = os.fstat(current_descriptor)
            finally:
                os.close(current_descriptor)
                os.close(current_parent)
        except (ArtifactViewError, OSError) as exc:
            _fail("ARTIFACT_VIEW_ARTIFACT_CHANGED", type(exc).__name__)
        if not _identity_unchanged(before, current_path) \
                or directory_chain != current_directory_chain:
            _fail(
                "ARTIFACT_VIEW_ARTIFACT_CHANGED",
                "artifact path or directory chain changed during bounded inspection",
            )
    finally:
        os.close(descriptor)
        os.close(parent_descriptor)


def _bounded_int(
    value: object,
    *,
    field: str,
    minimum: int,
    maximum: int,
) -> int:
    if isinstance(value, bool) or not isinstance(value, int) \
            or value < minimum or value > maximum:
        _fail(
            "ARTIFACT_VIEW_BOUND_INVALID",
            f"{field} must be between {minimum} and {maximum}",
        )
    return value


def _decode(value: bytes) -> str:
    return value.decode("utf-8", "replace")


def read_bounded_artifact(
    run_dir: str | Path,
    artifact: str | Path,
    *,
    scan_limit: int,
    runs_root: str | Path = RUNS_ROOT,
) -> BoundedArtifactRead:
    """Secure-open one explicit evidence artifact and read a bounded prefix.

    This is the public reuse surface for offline analyzers.  It deliberately
    returns bytes rather than decoded or rendered target content, and it grants
    no evidence/canonical-state authority.
    """
    scan_limit = _bounded_int(
        scan_limit, field="scan_limit", minimum=1, maximum=MAX_SCAN_LIMIT,
    )
    run, path, relative = resolve_artifact(
        run_dir, artifact, runs_root=runs_root,
    )
    with _open_stable(path, anchor=run / "evidence") as (handle, before):
        budget = min(before.st_size, scan_limit)
        payload = handle.read(budget)
        if len(payload) != budget:
            _fail(
                "ARTIFACT_VIEW_ARTIFACT_CHANGED",
                "artifact ended before its stable bounded read completed",
            )
    return BoundedArtifactRead(
        artifact=relative,
        file_size=before.st_size,
        payload=payload,
        scanned_bytes=len(payload),
        scan_truncated=len(payload) < before.st_size,
    )


def view_range(
    run_dir: str | Path,
    artifact: str | Path,
    *,
    offset: int,
    length: int,
    runs_root: str | Path = RUNS_ROOT,
) -> dict:
    offset = _bounded_int(
        offset, field="offset", minimum=0, maximum=(1 << 63) - 1,
    )
    length = _bounded_int(
        length, field="length", minimum=1, maximum=MAX_RANGE_BYTES,
    )
    run, path, relative = resolve_artifact(
        run_dir, artifact, runs_root=runs_root,
    )
    with _open_stable(path, anchor=run / "evidence") as (handle, before):
        if offset > before.st_size:
            _fail("ARTIFACT_VIEW_OFFSET_INVALID", "offset is beyond end of artifact")
        handle.seek(offset)
        payload = handle.read(length)
    return {
        "schema": SCHEMA,
        "operation": "range",
        "artifact": relative,
        "file_size": before.st_size,
        "offset": offset,
        "requested_bytes": length,
        "returned_bytes": len(payload),
        "end_offset": offset + len(payload),
        "eof": offset + len(payload) >= before.st_size,
        "text": _decode(payload),
        "authority": AUTHORITY,
    }


def search_literal(
    run_dir: str | Path,
    artifact: str | Path,
    *,
    pattern: str,
    scan_limit: int = DEFAULT_SCAN_LIMIT,
    max_matches: int = 20,
    context_bytes: int = 80,
    runs_root: str | Path = RUNS_ROOT,
) -> dict:
    if not isinstance(pattern, str) or not pattern:
        _fail("ARTIFACT_VIEW_PATTERN_INVALID", "literal pattern must be non-empty")
    needle = pattern.encode("utf-8")
    if len(needle) > MAX_PATTERN_BYTES:
        _fail("ARTIFACT_VIEW_PATTERN_INVALID", "literal pattern exceeds byte limit")
    scan_limit = _bounded_int(
        scan_limit, field="scan_limit", minimum=1, maximum=MAX_SCAN_LIMIT,
    )
    max_matches = _bounded_int(
        max_matches, field="max_matches", minimum=1, maximum=MAX_MATCHES,
    )
    context_bytes = _bounded_int(
        context_bytes, field="context_bytes", minimum=0,
        maximum=MAX_CONTEXT_BYTES,
    )
    run, path, relative = resolve_artifact(
        run_dir, artifact, runs_root=runs_root,
    )
    offsets: list[int] = []
    seen: set[int] = set()
    scanned = 0
    hit_limit = False
    snippets: list[dict] = []
    with _open_stable(path, anchor=run / "evidence") as (handle, before):
        budget = min(before.st_size, scan_limit)
        carry = b""
        while scanned < budget:
            chunk = handle.read(min(READ_CHUNK, budget - scanned))
            if not chunk:
                break
            combined = carry + chunk
            base = scanned - len(carry)
            cursor = 0
            while True:
                found = combined.find(needle, cursor)
                if found < 0:
                    break
                absolute = base + found
                if absolute not in seen:
                    seen.add(absolute)
                    offsets.append(absolute)
                    if len(offsets) >= max_matches:
                        hit_limit = True
                        break
                cursor = found + 1
            scanned += len(chunk)
            if hit_limit:
                break
            overlap = min(max(len(needle) - 1, 0), len(combined))
            carry = combined[-overlap:] if overlap else b""

        for absolute in offsets:
            start = max(0, absolute - context_bytes)
            end = min(
                before.st_size,
                absolute + len(needle) + context_bytes,
            )
            handle.seek(start)
            excerpt = handle.read(end - start)
            snippets.append({
                "offset": absolute,
                "excerpt_offset": start,
                "excerpt_bytes": len(excerpt),
                "text": _decode(excerpt),
            })
    return {
        "schema": SCHEMA,
        "operation": "search",
        "artifact": relative,
        "file_size": before.st_size,
        "pattern": pattern,
        "scanned_bytes": scanned,
        "scan_truncated": scanned < before.st_size,
        "matches": snippets,
        "matches_truncated": hit_limit,
        "authority": AUTHORITY,
    }


def extract_strings(
    run_dir: str | Path,
    artifact: str | Path,
    *,
    min_length: int = 4,
    scan_limit: int = DEFAULT_SCAN_LIMIT,
    max_strings: int = 50,
    max_string_bytes: int = 256,
    runs_root: str | Path = RUNS_ROOT,
) -> dict:
    min_length = _bounded_int(
        min_length, field="min_length", minimum=1, maximum=128,
    )
    scan_limit = _bounded_int(
        scan_limit, field="scan_limit", minimum=1, maximum=MAX_SCAN_LIMIT,
    )
    max_strings = _bounded_int(
        max_strings, field="max_strings", minimum=1, maximum=MAX_STRINGS,
    )
    max_string_bytes = _bounded_int(
        max_string_bytes, field="max_string_bytes", minimum=min_length,
        maximum=MAX_STRING_BYTES,
    )
    run, path, relative = resolve_artifact(
        run_dir, artifact, runs_root=runs_root,
    )
    results: list[dict] = []
    current = bytearray()
    current_start = 0
    current_length = 0
    preview_truncated = False
    scanned = 0
    hit_limit = False

    def finish_current() -> None:
        nonlocal current, current_length, preview_truncated, hit_limit
        if current_length >= min_length and len(results) < max_strings:
            results.append({
                "offset": current_start,
                "byte_length": current_length,
                "preview_truncated": preview_truncated,
                "text": current.decode("ascii", "strict"),
            })
            if len(results) >= max_strings:
                hit_limit = True
        current = bytearray()
        current_length = 0
        preview_truncated = False

    with _open_stable(path, anchor=run / "evidence") as (handle, before):
        budget = min(before.st_size, scan_limit)
        while scanned < budget and not hit_limit:
            chunk = handle.read(min(READ_CHUNK, budget - scanned))
            if not chunk:
                break
            consumed = 0
            for index, byte in enumerate(chunk):
                consumed = index + 1
                absolute = scanned + index
                if 32 <= byte <= 126:
                    if current_length == 0:
                        current_start = absolute
                    current_length += 1
                    if len(current) < max_string_bytes:
                        current.append(byte)
                    else:
                        preview_truncated = True
                else:
                    finish_current()
                    if hit_limit:
                        break
            scanned += consumed
        if not hit_limit:
            finish_current()
    return {
        "schema": SCHEMA,
        "operation": "strings",
        "artifact": relative,
        "file_size": before.st_size,
        "scanned_bytes": scanned,
        "scan_truncated": scanned < before.st_size,
        "strings": results,
        "strings_truncated": hit_limit or any(
            item["preview_truncated"] for item in results
        ),
        "authority": AUTHORITY,
    }


def _expect_error(code: str, call) -> bool:
    try:
        call()
    except ArtifactViewError as exc:
        return exc.code == code
    return False


def _selftest() -> int:
    checks: list[tuple[str, bool]] = []
    with tempfile.TemporaryDirectory(prefix="xunji-artifact-view-") as raw:
        fixture = Path(raw)
        runs_root = fixture / "runs"
        run = runs_root / "fixture-run"
        evidence = run / "evidence"
        evidence.mkdir(parents=True)
        boundary_prefix = b"A" * (READ_CHUNK - 3)
        payload = (
            b"header\x00HELLO_WORLD\x00" + boundary_prefix
            + b"NEEDLE-CROSS-CHUNK\x00tail-printable\x00"
        )
        artifact = evidence / "large.bin"
        artifact.write_bytes(payload)
        before_stat = artifact.stat()
        before_entries = sorted(
            item.relative_to(run).as_posix() for item in run.rglob("*")
        )

        ranged = view_range(
            run, "large.bin", offset=7, length=11, runs_root=runs_root,
        )
        searched = search_literal(
            run, "evidence/large.bin", pattern="NEEDLE-CROSS-CHUNK",
            scan_limit=len(payload), max_matches=5, context_bytes=8,
            runs_root=runs_root,
        )
        strings = extract_strings(
            run, "large.bin", min_length=5, scan_limit=len(payload),
            max_strings=10, max_string_bytes=32, runs_root=runs_root,
        )
        bounded = read_bounded_artifact(
            run, "large.bin", scan_limit=16, runs_root=runs_root,
        )
        limited = search_literal(
            run, "large.bin", pattern="tail-printable", scan_limit=32,
            runs_root=runs_root,
        )
        after_stat = artifact.stat()
        after_entries = sorted(
            item.relative_to(run).as_posix() for item in run.rglob("*")
        )
        checks.extend([
            ("range returns only the requested bounded bytes",
             ranged["text"] == "HELLO_WORLD" and ranged["returned_bytes"] == 11),
            ("literal search finds a match spanning reader chunks",
             len(searched["matches"]) == 1
             and searched["matches"][0]["offset"]
             == payload.index(b"NEEDLE-CROSS-CHUNK")),
            ("strings extraction preserves offsets and bounded previews",
             any(item["text"] == "HELLO_WORLD" for item in strings["strings"])
             and all(len(item["text"]) <= 32 for item in strings["strings"])),
            ("public stable read returns only its bounded prefix",
             bounded.payload == payload[:16]
             and bounded.scanned_bytes == 16
             and bounded.file_size == len(payload)
             and bounded.scan_truncated is True
             and bounded.artifact == "evidence/large.bin"),
            ("scan limit is explicit and cannot imply absence",
             limited["scan_truncated"] and not limited["matches"]),
            ("all operations are read-only",
             before_entries == after_entries
             and _identity(before_stat) == _identity(after_stat)),
            ("range hard cap rejects oversized output",
             _expect_error(
                 "ARTIFACT_VIEW_BOUND_INVALID",
                 lambda: view_range(
                     run, "large.bin", offset=0, length=MAX_RANGE_BYTES + 1,
                     runs_root=runs_root,
                 ),
             )),
        ])

        outside = run / "target.md"
        outside.write_text("canonical", encoding="utf-8")
        checks.append((
            "canonical files outside evidence are not readable as artifacts",
            _expect_error(
                "ARTIFACT_VIEW_OUTSIDE_EVIDENCE",
                lambda: view_range(
                    run, outside, offset=0, length=4, runs_root=runs_root,
                ),
            ),
        ))
        escaped = fixture / "outside.bin"
        escaped.write_bytes(b"outside")
        checks.append((
            "path traversal and absolute escape are rejected",
            _expect_error(
                "ARTIFACT_VIEW_OUTSIDE_EVIDENCE",
                lambda: search_literal(
                    run, escaped, pattern="outside", runs_root=runs_root,
                ),
            ),
        ))
        if hasattr(os, "symlink"):
            link = evidence / "link.bin"
            link.symlink_to(escaped)
            checks.append((
                "artifact symlinks are rejected",
                _expect_error(
                    "ARTIFACT_VIEW_SYMLINK",
                    lambda: extract_strings(
                        run, "link.bin", runs_root=runs_root,
                    ),
                ),
            ))
            nested = evidence / "nested"
            nested.mkdir()
            nested_artifact = nested / "inside.bin"
            nested_artifact.write_bytes(b"inside")
            linked_parent = evidence / "linked-parent"
            linked_parent.symlink_to(nested, target_is_directory=True)

            def open_linked_parent() -> None:
                with _open_stable(
                    linked_parent / "inside.bin", anchor=evidence,
                ) as (handle, _before):
                    handle.read(1)

            checks.append((
                "secure open rejects an intermediate symlink without a resolve/open gap",
                _expect_error("ARTIFACT_VIEW_OPEN_FAILED", open_linked_parent),
            ))

            moving = evidence / "moving"
            moving.mkdir()
            moving_artifact = moving / "inside.bin"
            moving_artifact.write_bytes(b"stable-old-bytes")
            moving_artifact_resolved = moving_artifact.resolve()

            def replace_intermediate_during_read() -> None:
                moved = evidence / "moving-old"
                with _open_stable(
                    moving_artifact_resolved, anchor=evidence,
                ) as (handle, _before):
                    handle.read(6)
                    moving.rename(moved)
                    moving.mkdir()
                    (moving / "inside.bin").write_bytes(b"replacement")

            checks.append((
                "intermediate directory replacement during read fails the final fence",
                _expect_error(
                    "ARTIFACT_VIEW_ARTIFACT_CHANGED",
                    replace_intermediate_during_read,
                ),
            ))

        with mock.patch(__name__ + "._identity_unchanged", return_value=False):
            checks.append((
                "read-time mutation fails closed",
                _expect_error(
                    "ARTIFACT_VIEW_ARTIFACT_CHANGED",
                    lambda: view_range(
                        run, "large.bin", offset=0, length=4,
                        runs_root=runs_root,
                    ),
                ),
            ))

        stderr = io.StringIO()
        with contextlib.redirect_stderr(stderr):
            cli_error = main([
                "range", str(run), str(outside), "--offset", "0", "--length", "1",
            ])
        checks.append((
            "CLI artifact errors return status 2 instead of raising NameError",
            cli_error == 2 and "ARTIFACT_VIEW_" in stderr.getvalue(),
        ))

    bad = [name for name, ok in checks if not ok]
    for name, ok in checks:
        print(("ok   " if ok else "FAIL ") + name)
    print("artifact_view selftest " + (
        "passed" if not bad else f"FAILED ({len(bad)})"
    ))
    return 0 if not bad else 1


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Bounded read-only inspection of one run evidence artifact.",
    )
    parser.add_argument("--selftest", action="store_true")
    subparsers = parser.add_subparsers(dest="command")

    range_parser = subparsers.add_parser("range")
    range_parser.add_argument("run")
    range_parser.add_argument("artifact")
    range_parser.add_argument("--offset", type=int, required=True)
    range_parser.add_argument("--length", type=int, default=4096)

    search_parser = subparsers.add_parser("search")
    search_parser.add_argument("run")
    search_parser.add_argument("artifact")
    search_parser.add_argument("pattern")
    search_parser.add_argument("--scan-limit", type=int, default=DEFAULT_SCAN_LIMIT)
    search_parser.add_argument("--max-matches", type=int, default=20)
    search_parser.add_argument("--context-bytes", type=int, default=80)

    strings_parser = subparsers.add_parser("strings")
    strings_parser.add_argument("run")
    strings_parser.add_argument("artifact")
    strings_parser.add_argument("--min-length", type=int, default=4)
    strings_parser.add_argument("--scan-limit", type=int, default=DEFAULT_SCAN_LIMIT)
    strings_parser.add_argument("--max-strings", type=int, default=50)
    strings_parser.add_argument("--max-string-bytes", type=int, default=256)

    args = parser.parse_args(argv)
    if args.selftest:
        if args.command:
            parser.error("--selftest cannot be combined with a command")
        return _selftest()
    if not args.command:
        parser.error("a command is required")
    try:
        if args.command == "range":
            result = view_range(
                args.run, args.artifact, offset=args.offset, length=args.length,
            )
        elif args.command == "search":
            result = search_literal(
                args.run, args.artifact, pattern=args.pattern,
                scan_limit=args.scan_limit, max_matches=args.max_matches,
                context_bytes=args.context_bytes,
            )
        else:
            result = extract_strings(
                args.run, args.artifact, min_length=args.min_length,
                scan_limit=args.scan_limit, max_strings=args.max_strings,
                max_string_bytes=args.max_string_bytes,
            )
    except ArtifactViewError as exc:
        print(str(exc), file=sys.stderr)
        return 2
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
