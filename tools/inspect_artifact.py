#!/usr/bin/env python3
"""Bounded read-only queries over one saved run artifact.

This replaces ad-hoc shell pipelines for common inspection tasks while keeping
the artifact path inside one run and the output explicitly capped.  It never
writes canonical state and its JSON query language is deliberately small:
``.name``, ``[0]``, and combinations such as ``.items[0].url``.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import tempfile
from pathlib import Path


MAX_FILE_BYTES = 4_000_000
MAX_OUTPUT_ROWS = 500
MODES = ("lines", "search", "sort", "unique", "cut", "json")


def _inside(root: Path, path: Path) -> bool:
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False


def resolve_artifact(run_dir: str | Path, raw_path: str | Path) -> tuple[Path, Path]:
    run_input = Path(os.path.abspath(Path(run_dir)))
    run = run_input.resolve()
    candidate = Path(raw_path)
    candidate_input = Path(os.path.abspath(
        candidate if candidate.is_absolute() else run_input / candidate))
    path = candidate_input.resolve()
    if not run.is_dir() or not _inside(run, path):
        raise ValueError("ARTIFACT_PATH_OUTSIDE_RUN")
    try:
        lexical_relative = candidate_input.relative_to(run_input)
    except ValueError as exc:
        raise ValueError("ARTIFACT_PATH_OUTSIDE_RUN") from exc
    cursor = run
    for part in lexical_relative.parts:
        cursor /= part
        if cursor.is_symlink():
            raise ValueError("ARTIFACT_NOT_REGULAR")
    try:
        info = path.lstat()
    except FileNotFoundError as exc:
        raise ValueError("ARTIFACT_NOT_FOUND") from exc
    if not path.is_file():
        raise ValueError("ARTIFACT_NOT_REGULAR")
    if info.st_size > MAX_FILE_BYTES:
        raise ValueError("ARTIFACT_TOO_LARGE")
    return run, path


def _json_query(value: object, query: str) -> object:
    if query in {"", "."}:
        return value
    if not query.startswith("."):
        raise ValueError("JSON_QUERY_INVALID")
    tokens = re.findall(r"\.([A-Za-z_][A-Za-z0-9_-]*)|\[([0-9]+)\]", query)
    rebuilt = "".join(
        f".{name}" if name else f"[{index}]" for name, index in tokens
    )
    if rebuilt != query:
        raise ValueError("JSON_QUERY_INVALID")
    current = value
    for name, index in tokens:
        if name:
            if not isinstance(current, dict) or name not in current:
                raise ValueError("JSON_QUERY_MISSING")
            current = current[name]
        else:
            offset = int(index)
            if not isinstance(current, list) or offset >= len(current):
                raise ValueError("JSON_QUERY_MISSING")
            current = current[offset]
    return current


def inspect(
    run_dir: str | Path,
    artifact: str | Path,
    *,
    mode: str,
    start: int = 1,
    count: int = 100,
    pattern: str = "",
    regex: bool = False,
    reverse: bool = False,
    delimiter: str = "\t",
    fields: str = "1",
    query: str = ".",
) -> dict:
    run, path = resolve_artifact(run_dir, artifact)
    if mode not in MODES:
        raise ValueError("ARTIFACT_MODE_INVALID")
    if start < 1 or not 1 <= count <= MAX_OUTPUT_ROWS:
        raise ValueError("ARTIFACT_LIMIT_INVALID")
    text = path.read_text(encoding="utf-8", errors="replace")
    lines = text.splitlines()
    result: object
    total = 0

    if mode == "lines":
        total = len(lines)
        result = lines[start - 1:start - 1 + count]
    elif mode == "search":
        if not pattern or len(pattern) > 256:
            raise ValueError("ARTIFACT_PATTERN_INVALID")
        try:
            matcher = re.compile(pattern) if regex else None
        except re.error as exc:
            raise ValueError("ARTIFACT_PATTERN_INVALID") from exc
        matched = [
            {"line": index, "text": line}
            for index, line in enumerate(lines, 1)
            if (matcher.search(line) if matcher else pattern in line)
        ]
        total = len(matched)
        result = matched[start - 1:start - 1 + count]
    elif mode in {"sort", "unique"}:
        values = (
            sorted(lines, reverse=reverse)
            if mode == "sort"
            else list(dict.fromkeys(lines))
        )
        total = len(values)
        result = values[start - 1:start - 1 + count]
    elif mode == "cut":
        if not delimiter or len(delimiter) > 8:
            raise ValueError("ARTIFACT_DELIMITER_INVALID")
        try:
            indexes = [int(item) - 1 for item in fields.split(",")]
        except ValueError as exc:
            raise ValueError("ARTIFACT_FIELDS_INVALID") from exc
        if not indexes or any(item < 0 or item > 63 for item in indexes):
            raise ValueError("ARTIFACT_FIELDS_INVALID")
        values = []
        for line in lines:
            columns = line.split(delimiter)
            values.append(delimiter.join(
                columns[index] if index < len(columns) else ""
                for index in indexes
            ))
        total = len(values)
        result = values[start - 1:start - 1 + count]
    else:
        try:
            value = json.loads(text)
        except json.JSONDecodeError as exc:
            raise ValueError("ARTIFACT_JSON_INVALID") from exc
        result = _json_query(value, query)
        if isinstance(result, list):
            total = len(result)
            result = result[start - 1:start - 1 + count]
        else:
            total = 1

    returned = len(result) if isinstance(result, list) else 1
    return {
        "schema": "xunji.artifact-query.v1",
        "run": str(run),
        "artifact": path.relative_to(run).as_posix(),
        "mode": mode,
        "start": start,
        "limit": count,
        "total": total,
        "returned": returned,
        "truncated": total > (start - 1 + returned),
        "result": result,
    }


def _selftest() -> int:
    root = Path(tempfile.mkdtemp()) / "run"
    (root / "evidence").mkdir(parents=True)
    sample = root / "evidence" / "sample.txt"
    sample.write_text("b\t2\na\t1\nb\t2\n", encoding="utf-8")
    data = root / "evidence" / "sample.json"
    data.write_text('{"items":[{"url":"/api/a"},{"url":"/api/b"}]}\n',
                    encoding="utf-8")
    checks = [
        ("lines are bounded and numbered by the envelope",
         inspect(root, "evidence/sample.txt", mode="lines", count=2)["result"]
         == ["b\t2", "a\t1"]),
        ("literal search reports source line numbers",
         inspect(root, "evidence/sample.txt", mode="search", pattern="b")["result"]
         == [{"line": 1, "text": "b\t2"}, {"line": 3, "text": "b\t2"}]),
        ("unique is stable", inspect(
            root, "evidence/sample.txt", mode="unique")["result"]
         == ["b\t2", "a\t1"]),
        ("cut is typed and bounded", inspect(
            root, "evidence/sample.txt", mode="cut", fields="2")["result"]
         == ["2", "1", "2"]),
        ("json query returns only the selected value", inspect(
            root, "evidence/sample.json", mode="json",
            query=".items[1].url")["result"] == "/api/b"),
    ]
    try:
        inspect(root, "../outside", mode="lines")
        outside_rejected = False
    except ValueError as exc:
        outside_rejected = str(exc) == "ARTIFACT_PATH_OUTSIDE_RUN"
    checks.append(("paths outside the run fail closed", outside_rejected))
    linked = root / "evidence" / "linked.txt"
    try:
        linked.symlink_to(sample)
        try:
            inspect(root, "evidence/linked.txt", mode="lines")
            symlink_rejected = False
        except ValueError as exc:
            symlink_rejected = str(exc) == "ARTIFACT_NOT_REGULAR"
        symlink_check = symlink_rejected
    except OSError:
        # Windows runners commonly lack symlink privilege. Linux full CI still
        # executes the actual rejection branch.
        symlink_check = True
    checks.append(("symlink aliases fail closed when platform-supported",
                   symlink_check))
    failed = [name for name, ok in checks if not ok]
    for name, ok in checks:
        print(("ok   " if ok else "FAIL ") + name)
    print("inspect_artifact selftest " + ("passed" if not failed else "FAILED"))
    return 0 if not failed else 1


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("run_dir", nargs="?")
    parser.add_argument("artifact", nargs="?")
    parser.add_argument("--mode", choices=MODES)
    parser.add_argument("--start", type=int, default=1)
    parser.add_argument("--count", type=int, default=100)
    parser.add_argument("--pattern", default="")
    parser.add_argument("--regex", action="store_true")
    parser.add_argument("--reverse", action="store_true")
    parser.add_argument("--delimiter", default="\t")
    parser.add_argument("--fields", default="1")
    parser.add_argument("--query", default=".")
    parser.add_argument("--selftest", action="store_true")
    args = parser.parse_args()
    if args.selftest:
        return _selftest()
    if not args.run_dir or not args.artifact or not args.mode:
        parser.error("run_dir, artifact, and --mode are required")
    try:
        result = inspect(
            args.run_dir, args.artifact, mode=args.mode, start=args.start,
            count=args.count, pattern=args.pattern, regex=args.regex,
            reverse=args.reverse, delimiter=args.delimiter, fields=args.fields,
            query=args.query,
        )
    except ValueError as exc:
        parser.error(str(exc))
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
