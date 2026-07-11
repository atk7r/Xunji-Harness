#!/usr/bin/env python3
"""Canonical parser for Xunji run control-plane state.

Markdown remains the operator-readable source of truth, but every consumer must
interpret it through this module.  Keeping status/barrier parsing here prevents
the loop controller, Agent gate, workers, and statusline from disagreeing about
the same front.
"""
from __future__ import annotations

import argparse
import re
import tempfile
from dataclasses import asdict, dataclass
from pathlib import Path


OPEN_STATUSES = {"open", "probing", "working", "blocked_type_a"}
TERMINAL_STATUSES = {
    "closed", "closing", "final", "done", "complete", "completed",
    "blocked_type_b", "deferred",
}
TRIVIAL_BARRIERS = {"", "none", "unknown", "n/a", "-"}
HWS = r"[^\S\n]"


@dataclass(frozen=True)
class Front:
    id: str
    title: str
    section: str
    status: str
    status_raw: str
    barrier: str
    depth: str
    text: str
    schema_errors: tuple[str, ...]

    @property
    def is_open(self) -> bool:
        return self.status in OPEN_STATUSES

    @property
    def is_deferred(self) -> bool:
        return self.status == "deferred"

    @property
    def is_closed(self) -> bool:
        return self.status in TERMINAL_STATUSES - {"deferred"}


def _field(block: str, name: str) -> str:
    match = re.search(
        rf"(?im)^{HWS}*[-*]?{HWS}*{re.escape(name)}{HWS}*[:：]{HWS}*([^\n]*)$",
        block,
    )
    return match.group(1).strip() if match else ""


def normalize_status(raw: object) -> str:
    """Return one canonical status from a field value or section label."""
    value = str(raw or "").strip().lower().replace("-", "_")
    tokens = set(re.findall(r"[a-z0-9_]+", value))
    if "closed_type_b" in tokens:
        tokens.add("closed")
    terminal = tokens & TERMINAL_STATUSES
    if "deferred" in terminal and terminal - {"deferred"}:
        return "unknown"
    if "blocked_type_b" in tokens:
        return "blocked_type_b"
    for preferred in ("closing", "final", "completed", "complete", "done", "closed"):
        if preferred in tokens:
            return preferred
    if "deferred" in tokens:
        return "deferred"
    if "blocked_type_a" in tokens:
        return "blocked_type_a"
    for preferred in ("probing", "working", "open"):
        if preferred in tokens:
            return preferred
    primary = re.split(r"[|,;；(（]", value, maxsplit=1)[0].strip()
    return primary or "unknown"


def _inline_component(raw: str, name: str) -> str:
    match = re.search(rf"(?i)(?:^|\|)\s*{re.escape(name)}\s*[:：]\s*([^|]+)", raw)
    return match.group(1).strip() if match else ""


def _sections(text: str) -> list[tuple[str, str]]:
    out: list[tuple[str, str]] = []
    matches = list(re.finditer(r"(?m)^##[ \t]+([^#\n]+?)[ \t]*$", text))
    if not matches:
        return [("Unknown", text)]
    prefix = text[:matches[0].start()]
    if re.search(r"(?m)^###[ \t]+F-\d+\b", prefix):
        out.append(("Unknown", prefix))
    for idx, match in enumerate(matches):
        end = matches[idx + 1].start() if idx + 1 < len(matches) else len(text)
        out.append((match.group(1).strip(), text[match.end():end]))
    return out


def parse_fronts(run_dir: str | Path) -> list[Front]:
    run = Path(run_dir)
    path = run / "frontier.md"
    if not path.exists():
        return []
    text = path.read_text(encoding="utf-8", errors="replace")
    text = re.sub(r"(?ms)^(```|~~~)[^\n]*\n.*?^\1[ \t]*\n?", "", text)
    fronts: list[Front] = []
    for section, body in _sections(text):
        blocks = list(re.finditer(r"(?ms)^###[ \t]+(F-\d+)\b([^\n]*)(.*?)(?=^###[ \t]+F-\d+\b|\Z)", body))
        for match in blocks:
            fid = match.group(1)
            title = (fid + match.group(2)).strip(" -—\t")
            block = match.group(0)
            raw_status = _field(block, "Status")
            section_status = (
                "open" if section.lower().startswith("open")
                else "deferred" if section.lower().startswith("deferred")
                else "closed" if section.lower().startswith("closed")
                else "unknown"
            )
            status = normalize_status(raw_status or section_status)
            barrier = _field(block, "Barrier class")
            depth = _field(block, "Current depth")
            errors: list[str] = []
            if not raw_status:
                errors.append("missing canonical `Status:` field")
            if raw_status and section_status != "unknown":
                section_open = section_status == "open"
                if section_open != (status in OPEN_STATUSES):
                    errors.append(
                        f"Status `{status}` conflicts with `{section}` section")
            if not barrier:
                barrier = _inline_component(raw_status, "Barrier") or "unknown"
                errors.append("missing canonical `Barrier class:` field")
            if not depth:
                depth = _inline_component(raw_status, "Depth") or "unknown"
                errors.append("missing canonical `Current depth:` field")
            if "|" in raw_status:
                errors.append("compound `Status:` line must be split into canonical fields")
            if status == "unknown":
                errors.append("unclassified Status")
            fronts.append(Front(
                id=fid,
                title=title or fid,
                section=section,
                status=status,
                status_raw=raw_status,
                barrier=barrier.strip().lower().replace(" ", "_"),
                depth=depth.strip().lower(),
                text=block,
                schema_errors=tuple(dict.fromkeys(errors)),
            ))
    return fronts


def summary(run_dir: str | Path) -> dict:
    fronts = parse_fronts(run_dir)
    opened = [front for front in fronts if front.is_open]
    barriers = sorted({front.barrier for front in opened if front.barrier not in TRIVIAL_BARRIERS})
    barrier_counts = {
        barrier: sum(1 for front in opened if front.barrier == barrier)
        for barrier in barriers
    }
    all_share_one_barrier = bool(opened) and any(
        count == len(opened) for count in barrier_counts.values()
    )
    fanout_required = len(opened) >= 4 and not all_share_one_barrier
    schema_errors = [
        f"{front.id}: {error}"
        for front in fronts
        for error in front.schema_errors
    ]
    ids = [front.id for front in fronts]
    for duplicate in sorted({fid for fid in ids if ids.count(fid) > 1}):
        schema_errors.append(f"{duplicate}: duplicate front id")
    return {
        "fronts": [asdict(front) for front in fronts],
        "open": [front.id for front in opened],
        "open_count": len(opened),
        "deferred": [front.id for front in fronts if front.is_deferred],
        "closed": [front.id for front in fronts if front.is_closed],
        "barriers": barriers,
        "diverse_barriers": not all_share_one_barrier,
        "fanout_required": fanout_required,
        "schema_errors": schema_errors,
    }


def _selftest() -> int:
    root = Path(tempfile.mkdtemp())
    run = root / "run"
    run.mkdir()
    (run / "frontier.md").write_text(
        "# Frontier\n\n## Open Fronts\n\n"
        "### F-001 — compound\n- Status: open | Barrier: app-layer | Depth: moderate\n\n"
        "### F-002 — canonical\n- Status: probing\n- Barrier class: auth-layer\n"
        "- Current depth: shallow\n\n"
        "### F-003\n- Status: open\n- Barrier class: network-layer\n- Current depth: shallow\n\n"
        "### F-004\n- Status: open\n- Barrier class: none\n- Current depth: shallow\n\n"
        "### F-004\n- Status: open\n- Barrier class: none\n- Current depth: shallow\n\n"
        "## Deferred Fronts\n### F-005\n- Status: deferred\n- Barrier class: auth-layer\n"
        "- Current depth: shallow\n"
        "### F-006\n- Barrier class: auth-layer\n- Current depth: shallow\n"
        "## Closed Fronts\n### F-007\n- Status: open\n"
        "- Barrier class: routing-layer\n- Current depth: shallow\n",
        encoding="utf-8",
    )
    data = summary(run)
    by_id = {front.id: front for front in parse_fronts(run)}
    checks = [
        ("compound status still counts as open", by_id["F-001"].is_open),
        ("inline barrier is recovered", by_id["F-001"].barrier == "app-layer"),
        ("compound format is flagged", bool(by_id["F-001"].schema_errors)),
        ("probing is active", "F-002" in data["open"]),
        ("deferred is not active", "F-005" not in data["open"]),
        ("four diverse fronts require fanout", data["fanout_required"] is True),
        ("duplicate front id is flagged", any("duplicate front id" in item for item in data["schema_errors"])),
        ("section fallback does not hide missing Status",
         any("F-006: missing canonical `Status:`" in item for item in data["schema_errors"])),
        ("open status inside Closed section is flagged and remains active",
         "F-007" in data["open"]
         and any("F-007: Status `open` conflicts" in item for item in data["schema_errors"])),
    ]
    bad = [name for name, ok in checks if not ok]
    for name, ok in checks:
        print(("ok   " if ok else "FAIL ") + name)
    print("run_model selftest " + ("passed" if not bad else f"FAILED ({len(bad)})"))
    return 0 if not bad else 1


def main() -> int:
    parser = argparse.ArgumentParser(description="parse canonical Xunji run state")
    parser.add_argument("run_dir", nargs="?")
    parser.add_argument("--selftest", action="store_true")
    args = parser.parse_args()
    if args.selftest:
        return _selftest()
    if not args.run_dir:
        parser.error("run_dir is required")
    data = summary(args.run_dir)
    print(f"open={data['open_count']} fanout_required={data['fanout_required']}")
    for error in data["schema_errors"]:
        print(f"WARN {error}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
