#!/usr/bin/env python3
"""Shared typed record parser for canonical Markdown/JSON run ledgers.

`run_model.py` remains the frontier/status owner and `evidence_parse.py` remains
the evidence owner.  This module supplies their common typed aggregation surface
and owns constraints, review-ledger, and immutable Agent-result parsing.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import tempfile
from pathlib import Path


MAX_BLOCK_CHARS = 200_000
MAX_FIELD_CHARS = 4096


def _visible_lines(text: str) -> list[str]:
    lines = text.splitlines()
    visible: list[str] = []
    fence = ""
    for line in lines:
        match = re.match(r"^\s*(```+|~~~+)", line)
        if match:
            marker = match.group(1)[0]
            fence = "" if fence == marker else (marker if not fence else fence)
            visible.append("")
        else:
            visible.append("" if fence else line)
    return visible


def _records(text: str, *, prefix: str, heading_level: int,
             line_offset: int = 0) -> list[dict]:
    lines = _visible_lines(text)
    heading = re.compile(
        rf"^\s*{'#' * heading_level}\s+({re.escape(prefix)}-\d+)\b(.*)$")
    starts = [
        (index, match)
        for index, line in enumerate(lines)
        if (match := heading.match(line))
    ]
    records: list[dict] = []
    seen: set[str] = set()
    for offset, (start, match) in enumerate(starts):
        end = starts[offset + 1][0] if offset + 1 < len(starts) else len(lines)
        block_lines = lines[start:end]
        block = "\n".join(block_lines)
        fields: dict[str, str] = {}
        field_names: set[str] = set()
        errors: list[str] = []
        for line in block_lines[1:]:
            field = re.match(r"^\s*[-*]\s*([^:：\n]{1,80})\s*[:：]\s*(.*)$", line)
            if not field:
                continue
            name = field.group(1).strip()
            value = field.group(2).strip()
            normalized_name = name.casefold()
            if normalized_name in field_names:
                errors.append(f"duplicate field: {name}")
                continue
            field_names.add(normalized_name)
            if len(value) > MAX_FIELD_CHARS:
                errors.append(f"field too long: {name}")
                value = value[:MAX_FIELD_CHARS]
            fields[name] = value
        record_id = match.group(1)
        if record_id in seen:
            errors.append(f"duplicate id: {record_id}")
        seen.add(record_id)
        if len(block) > MAX_BLOCK_CHARS:
            errors.append("record too long")
        records.append({
            "id": record_id,
            "title": match.group(2).strip(" \t—-:："),
            "fields": fields,
            "source_span": {
                "line_start": line_offset + start + 1,
                "line_end": line_offset + end,
            },
            "schema_errors": errors,
            "text": block[:MAX_BLOCK_CHARS],
        })
    return records


def _field_value(fields: dict[str, str], name: str, default: str = "") -> str:
    """Read historical hand-authored field spellings case-insensitively."""
    wanted = name.casefold()
    return next(
        (value for key, value in fields.items() if key.casefold() == wanted),
        default,
    )


def parse_constraints(run_dir: str | Path) -> list[dict]:
    path = Path(run_dir) / "constraints.md"
    if not path.is_file():
        return []
    records = _records(
        path.read_text(encoding="utf-8", errors="replace"),
        prefix="C", heading_level=2,
    )
    for record in records:
        fields = record["fields"]
        # The pre-typed parser accepted duplicate IDs/fields, long values, and
        # case variants. Preserve those already-written runs as bounded,
        # explicit compatibility warnings; native writers still use the
        # canonical template and fixtures reject emitting these shapes.
        compatibility_warnings = list(record["schema_errors"])
        record["schema_errors"] = []
        record.update({
            "front": _field_value(fields, "Front"),
            "mechanism_class": _field_value(fields, "Mechanism class"),
            "input_shape": _field_value(fields, "Input shape"),
            "why_blocked": _field_value(fields, "Why blocked"),
            "evidence": _field_value(fields, "Evidence"),
            "ruled_out": _field_value(fields, "Ruled out"),
            "compatibility_warnings": compatibility_warnings,
        })
        if not record["front"]:
            record["compatibility_warnings"].append("missing field: Front")
    return records


def _review_ledger_ranges(lines: list[str]) -> list[tuple[int, int]]:
    ranges: list[tuple[int, int]] = []
    for start, line in enumerate(lines):
        if not re.match(r"^\s*##\s+Review Finding Ledger\b", line, re.I):
            continue
        end = next(
            (index for index in range(start + 1, len(lines))
             if re.match(r"^\s*##\s+(?!#)", lines[index])),
            len(lines),
        )
        ranges.append((start, end))
    return ranges


def _explicit_legacy_review_heading(line: str) -> bool:
    """Return true only for the pre-ledger severity-bearing finding shape."""
    return bool(re.match(
        r"^\s*###\s+PR-\d+\b[ \t]*(?:—|-|:|：)[ \t]*(?:BLOCKER|WARN)\b",
        line,
        re.I,
    ))


def review_ledger_compatibility_warnings(run_dir: str | Path) -> list[str]:
    """Surface non-finding PR prose outside a native ledger."""
    path = Path(run_dir) / "review.md"
    if not path.is_file():
        return []
    lines = _visible_lines(path.read_text(encoding="utf-8", errors="replace"))
    ranges = _review_ledger_ranges(lines)
    if not ranges:
        return []
    return [
        f"PR heading outside Review Finding Ledger at line {index + 1}"
        for index, line in enumerate(lines)
        if re.match(r"^\s*###\s+PR-\d+\b", line, re.I)
        and not _explicit_legacy_review_heading(line)
        and not any(start < index < end for start, end in ranges)
    ]


def parse_review_ledger(run_dir: str | Path) -> list[dict]:
    path = Path(run_dir) / "review.md"
    if not path.is_file():
        return []
    lines = _visible_lines(path.read_text(encoding="utf-8", errors="replace"))
    records: list[dict] = []
    ranges = _review_ledger_ranges(lines)
    for start, end in ranges:
        records.extend(_records(
            "\n".join(lines[start:end]),
            prefix="PR", heading_level=3, line_offset=start,
        ))
    for record in _records(
        "\n".join(lines), prefix="PR", heading_level=3,
    ):
        index = int(record["source_span"]["line_start"]) - 1
        if (
            not any(start < index < end for start, end in ranges)
            and _explicit_legacy_review_heading(lines[index])
        ):
            record["compatibility_warnings"] = [
                "legacy severity finding outside Review Finding Ledger",
            ]
            records.append(record)
    for record in records:
        fields = record["fields"]
        compatibility_warnings = list(
            record.get("compatibility_warnings", [])
        ) + [
            error for error in record["schema_errors"]
            if not error.startswith("duplicate id:")
        ]
        record["schema_errors"] = [
            error for error in record["schema_errors"]
            if error.startswith("duplicate id:")
        ]
        record.update({
            "status": _field_value(fields, "Status", "pending").strip().lower(),
            "resolution": _field_value(
                fields, "DriverResolution", "pending").strip(),
            "severity": (
                "BLOCKER" if "BLOCKER" in record["title"].upper()
                else "WARN" if "WARN" in record["title"].upper()
                else ""
            ),
            "compatibility_warnings": compatibility_warnings,
        })
        if not record["severity"]:
            record["compatibility_warnings"].append("missing severity")
    return records


def parse_agent_result(path: str | Path, *, run_dir: str | Path) -> dict:
    run_input = Path(os.path.abspath(Path(run_dir)))
    run = run_input.resolve()
    raw_candidate = Path(path)
    candidate_input = Path(os.path.abspath(
        raw_candidate if raw_candidate.is_absolute()
        else run_input / raw_candidate))
    candidate = candidate_input.resolve()
    try:
        candidate.relative_to(run)
        lexical_relative = candidate_input.relative_to(run_input)
    except ValueError as exc:
        raise ValueError("AGENT_RESULT_OUTSIDE_RUN") from exc
    cursor = run
    for part in lexical_relative.parts:
        cursor /= part
        if cursor.is_symlink():
            raise ValueError("AGENT_RESULT_NOT_REGULAR")
    if not candidate.is_file():
        raise ValueError("AGENT_RESULT_NOT_REGULAR")
    if candidate.stat().st_size > 2_000_000:
        raise ValueError("AGENT_RESULT_TOO_LARGE")
    try:
        value = json.loads(candidate.read_text(encoding="utf-8", errors="strict"))
    except Exception as exc:
        raise ValueError("AGENT_RESULT_JSON_INVALID") from exc
    if not isinstance(value, dict):
        raise ValueError("AGENT_RESULT_SCHEMA_INVALID")
    return {
        "path": candidate.relative_to(run).as_posix(),
        "record": value,
        "source_span": {"line_start": 1, "line_end": 1},
        "schema_errors": (
            [] if isinstance(value.get("schema"), str)
            else ["missing string schema"]
        ),
    }


def parse_run(run_dir: str | Path) -> dict:
    run = Path(run_dir)
    import evidence_parse
    import run_model
    constraints = parse_constraints(run)
    reviews = parse_review_ledger(run)
    results = []
    result_root = run / "state" / "merge_results"
    for path in sorted(result_root.glob("**/*.json")) if result_root.is_dir() else []:
        try:
            results.append(parse_agent_result(path, run_dir=run))
        except ValueError as exc:
            results.append({
                "path": path.relative_to(run).as_posix(),
                "record": {},
                "source_span": {"line_start": 1, "line_end": 1},
                "schema_errors": [str(exc)],
            })
    return {
        "schema": "xunji.canonical-records.v1",
        "fronts": [item.__dict__ for item in run_model.parse_fronts(run)],
        "evidence": evidence_parse.parse_evidence(run),
        "constraints": constraints,
        "review_ledger": reviews,
        "agent_results": results,
        "schema_errors": [
            f"{kind}:{item.get('id') or item.get('path')}:{error}"
            for kind, rows in (
                ("constraint", constraints), ("review", reviews),
                ("agent_result", results),
            )
            for item in rows
            for error in item.get("schema_errors", [])
        ],
        "compatibility_warnings": [
            f"{kind}:{item.get('id')}:{warning}"
            for kind, rows in (
                ("constraint", constraints), ("review", reviews),
            )
            for item in rows
            for warning in item.get("compatibility_warnings", [])
        ] + [
            f"review:{warning}"
            for warning in review_ledger_compatibility_warnings(run)
        ],
    }


def _selftest() -> int:
    root = Path(tempfile.mkdtemp()) / "run"
    root.mkdir()
    (root / "constraints.md").write_text(
        "# Constraints\n"
        "```md\n## C-999\n- Front: F-999\n```\n"
        "## C-001 — canonical\n- Front：F-001\n- Mechanism class: auth\n"
        "## C-001 — duplicate\n- Front: F-002\n",
        encoding="utf-8",
    )
    (root / "review.md").write_text(
        "# Review\n### PR-999 — historical prose, not a finding ledger\n"
        "## Review Finding Ledger\n"
        "### PR-001 — WARN — docs\n"
        "- status: dismissed\n- driverresolution: Reason: duplicate\n"
        "### PR-002 — historical native title\n"
        "- Status: dismissed\n- DriverResolution: Reason: legacy\n",
        encoding="utf-8",
    )
    constraints = parse_constraints(root)
    reviews = parse_review_ledger(root)
    legacy_root = Path(tempfile.mkdtemp()) / "run"
    legacy_root.mkdir()
    (legacy_root / "review.md").write_text(
        "# Review\n"
        "### PR-777 — BLOCKER — legacy explicit finding\n"
        "- Status: pending\n- DriverResolution: pending\n",
        encoding="utf-8",
    )
    legacy_reviews = parse_review_ledger(legacy_root)
    result_root = root / "state" / "merge_results"
    result_root.mkdir(parents=True)
    real_result = result_root / "real.json"
    real_result.write_text('{"schema":"xunji.agent-result.v1"}\n', encoding="utf-8")
    linked_result = result_root / "linked.json"
    try:
        linked_result.symlink_to(real_result)
        try:
            parse_agent_result(linked_result, run_dir=root)
            symlink_rejected = False
        except ValueError as exc:
            symlink_rejected = str(exc) == "AGENT_RESULT_NOT_REGULAR"
        symlink_check = symlink_rejected
    except OSError:
        symlink_check = True
    checks = [
        ("fenced fake records are ignored", len(constraints) == 2),
        ("Chinese punctuation and source spans are preserved",
         constraints[0]["front"] == "F-001"
         and constraints[0]["source_span"]["line_start"] == 6),
        ("legacy duplicate IDs remain explicit compatibility warnings",
         "duplicate id: C-001"
         in constraints[1]["compatibility_warnings"]
         and not constraints[1]["schema_errors"]),
        ("review ledger is typed and fields are case-insensitive",
         len(reviews) == 2
         and reviews[0]["status"] == "dismissed"
         and reviews[0]["severity"] == "WARN"),
        ("missing legacy review severity is a compatibility warning",
         "missing severity" in reviews[1]["compatibility_warnings"]
         and not reviews[1]["schema_errors"]),
        ("historical PR prose outside finding ledgers stays compatible",
         all(item["id"] != "PR-999" for item in reviews)
         and review_ledger_compatibility_warnings(root)
         == ["PR heading outside Review Finding Ledger at line 2"]),
        ("legacy explicit severity finding remains typed outside native ledger",
         len(legacy_reviews) == 1
         and legacy_reviews[0]["severity"] == "BLOCKER"
         and "legacy severity finding outside Review Finding Ledger"
         in legacy_reviews[0]["compatibility_warnings"]),
        ("Agent results reject symlink aliases when platform-supported",
         symlink_check),
    ]
    failed = [name for name, ok in checks if not ok]
    for name, ok in checks:
        print(("ok   " if ok else "FAIL ") + name)
    print("canonical_records selftest " + ("passed" if not failed else "FAILED"))
    return 0 if not failed else 1


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("run_dir", nargs="?")
    parser.add_argument("--selftest", action="store_true")
    args = parser.parse_args()
    if args.selftest:
        return _selftest()
    if not args.run_dir:
        parser.error("run_dir is required")
    print(json.dumps(parse_run(args.run_dir), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
