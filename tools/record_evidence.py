#!/usr/bin/env python3
"""Append a normalized evidence entry to a Xunji run ledger.

The tool is intentionally conservative: web research and other external/source
leads are recorded as low-maturity evidence unless the caller supplies active
proof fields. It writes only local files and never performs network activity.
"""
from __future__ import annotations

import argparse
import contextlib
import io
import json
import re
import sys
import tempfile
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
    sys.stderr.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
except Exception:
    pass

ROOT = Path(__file__).resolve().parents[1]
CANONICAL_CERTAINTY = {"0.3", "0.5", "0.8", "1.0"}
MATURITY = {"phenomenon", "candidate", "finding"}
CAUSED_BY_US = {"yes", "no", "unknown"}
REPORTABLE = {"yes", "no"}


@dataclass(frozen=True)
class AppendResult:
    entry_id: str
    path: Path
    replaced_template: bool


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _one_line(value: str | None, default: str = "-") -> str:
    if value is None:
        return default
    clean = re.sub(r"\s+", " ", value.strip())
    return clean if clean else default


def _artifact_values(args: argparse.Namespace) -> list[str]:
    """Return exact artifact tokens without flattening them into prose.

    ``--artifacts`` is retained as the legacy one-value spelling.  New callers
    use repeatable ``--artifact`` so the producer emits the same per-path shape
    consumed by evidence_parse and the review gate.
    """
    values: list[str] = []
    for raw in [getattr(args, "artifacts", None), *(getattr(args, "artifact", []) or [])]:
        if raw is None:
            continue
        for line in str(raw).splitlines():
            value = line.strip()
            if value and value not in values:
                values.append(value)
    return values


def _resolve_run_dir(raw: str) -> Path:
    run_dir = Path(raw)
    if not run_dir.is_absolute():
        run_dir = (Path.cwd() / run_dir).resolve()
    else:
        run_dir = run_dir.resolve()
    if not run_dir.is_dir():
        raise ValueError(f"run directory does not exist: {run_dir}")
    ev = run_dir / "evidence.md"
    if not ev.is_file():
        raise ValueError(f"missing evidence.md in run directory: {run_dir}")
    return run_dir


def _next_id(text: str) -> str:
    nums = [int(m.group(1)) for m in re.finditer(r"(?m)^##\s+E-(\d+)\b", text)]
    if not nums:
        return "E-001"
    return f"E-{max(nums) + 1:03d}"


def _template_placeholder_span(text: str) -> tuple[int, int, str] | None:
    """Return the only stock template block span, if evidence.md is still empty."""
    blocks = list(re.finditer(r"(?ms)^##\s+(E-\d+)\b.*?(?=^##\s+E-\d+\b|\Z)", text))
    if len(blocks) != 1:
        return None
    block = blocks[0].group(0)
    required = [
        "- Maturity: phenomenon / candidate / finding",
        "- Reportable: yes / no",
        "- Time:",
        "- Action:",
        "- Source:",
        "- Result:",
        "- Certainty:",
        "- Next:",
    ]
    if all(marker in block for marker in required):
        return blocks[0].start(), blocks[0].end(), blocks[0].group(1)
    return None


def _validate_args(args: argparse.Namespace) -> None:
    certainty = str(args.certainty)
    if certainty not in CANONICAL_CERTAINTY:
        raise ValueError(
            "certainty must use the canonical scale: 0.3, 0.5, 0.8, or 1.0"
        )
    maturity = args.maturity
    if maturity not in MATURITY:
        raise ValueError("maturity must be phenomenon, candidate, or finding")
    if args.caused_by_us not in CAUSED_BY_US:
        raise ValueError("caused-by-us must be yes, no, or unknown")
    if args.reportable not in REPORTABLE:
        raise ValueError("reportable must be yes or no")
    if args.date and not re.fullmatch(r"\d{4}-\d{2}-\d{2}(?:T\d{2}:\d{2}:\d{2}Z)?", args.date):
        raise ValueError("date must be YYYY-MM-DD or YYYY-MM-DDTHH:MM:SSZ")

    confirmed = float(certainty) >= 0.8
    if confirmed and maturity != "finding":
        raise ValueError("certainty >= 0.8 requires maturity=finding")
    if maturity == "finding" and not confirmed:
        raise ValueError("maturity=finding requires certainty >= 0.8")
    if confirmed and (not _artifact_values(args) or not args.replicated_control):
        raise ValueError(
            "confirmed evidence requires --artifacts and --replicated-control"
        )
    if args.source == "web-research" and (confirmed or maturity == "finding"):
        raise ValueError(
            "web-research entries are source leads; verify with saved target "
            "artifacts before promoting to finding"
        )
    if not args.finding:
        raise ValueError("--finding is required")
    if not (args.query or args.action):
        raise ValueError("--query or --action is required")
    if not args.provenance:
        raise ValueError("--provenance is required")


def _default_action(args: argparse.Namespace) -> str:
    if args.action:
        return args.action
    if args.query:
        return f"Web research query: {args.query}"
    return "Record evidence lead"


def _default_next(args: argparse.Namespace) -> str:
    if args.next:
        return args.next
    if args.source == "web-research":
        return "Verify against target artifacts before promotion."
    return "Use as lead unless upgraded with control and artifacts."


def _default_trust(args: argparse.Namespace) -> str:
    if args.trust:
        return args.trust
    source = args.source.lower()
    if source == "web-research" or source.startswith("target-"):
        return "untrusted"
    return "operator-reviewed"


def _default_alternative_explanation(args: argparse.Namespace) -> str:
    if args.alternative_explanation:
        return args.alternative_explanation
    source = args.source.lower()
    if source == "web-research":
        return "External source may be stale, wrong, or not applicable until verified against current target artifacts."
    if source.startswith("target-"):
        return "Single target observation may have benign confounders unless control or replication rules them out."
    return "Recorded source may be incomplete, mis-scoped, or contradicted by later evidence."


def _format_block(entry_id: str, args: argparse.Namespace) -> str:
    title = _one_line(args.title, _one_line(args.finding)[:72]).rstrip()
    fields: list[tuple[str, str]] = [
        ("Maturity", args.maturity),
        ("Reportable", args.reportable),
        ("Time", args.date or _now_iso()),
        ("Action", _default_action(args)),
        ("Source", args.source),
        ("Trust", _default_trust(args)),
    ]
    if args.query:
        fields.append(("Query", args.query))
    fields += [
        ("Result", args.finding),
        ("Provenance", args.provenance),
        ("Caused by us", args.caused_by_us),
        ("Alternative explanation", _default_alternative_explanation(args)),
        ("Certainty", args.certainty),
    ]
    if args.replicated_control:
        fields.append(("Replicated / Control", args.replicated_control))
    fields += [
        ("Supports", args.supports),
        ("Refutes", args.refutes),
    ]
    if args.unlocks:
        fields.append(("Unlocks", args.unlocks))
    fields.append(("Next", _default_next(args)))

    lines = [f"## {entry_id} - {title}", ""]
    lines.extend(f"- {name}: {_one_line(value)}" for name, value in fields[:])
    artifacts = _artifact_values(args)
    insert_at = next(
        index for index, line in enumerate(lines)
        if line.startswith("- Supports:")
    )
    artifact_lines = ["- Artifacts:"] + [f"  - {_one_line(value)}" for value in artifacts] \
        if artifacts else ["- Artifacts: none"]
    lines[insert_at:insert_at] = artifact_lines
    return "\n".join(lines) + "\n"


def append_entry(run_dir: Path, args: argparse.Namespace) -> AppendResult:
    ev = run_dir / "evidence.md"
    text = ev.read_text(encoding="utf-8", errors="replace")
    placeholder = _template_placeholder_span(text)
    if placeholder:
        start, end, entry_id = placeholder
        new_text = text[:start].rstrip() + "\n\n" + _format_block(entry_id, args) + text[end:].lstrip("\n")
        replaced = True
    else:
        entry_id = _next_id(text)
        prefix = text.rstrip() + "\n\n" if text.strip() else ""
        new_text = prefix + _format_block(entry_id, args)
        replaced = False

    tmp = ev.with_name(f".{ev.name}.{uuid.uuid4().hex}.tmp")
    tmp.write_text(new_text, encoding="utf-8")
    tmp.replace(ev)
    return AppendResult(entry_id=entry_id, path=ev, replaced_template=replaced)


def _parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(description="Record a normalized Xunji evidence entry.")
    ap.add_argument("--run", required=False, help="run directory containing evidence.md")
    ap.add_argument("--source", default="web-research", help="evidence source label")
    ap.add_argument("--trust", help="provenance trust label; defaults from --source")
    ap.add_argument("--query", help="research query or searched phrase")
    ap.add_argument("--date", help="entry timestamp, preferably tools/timestamp_gate.py --iso")
    ap.add_argument("--finding", help="what was found")
    ap.add_argument("--provenance", help="URL, source name, or local source pointer")
    ap.add_argument("--title", help="optional heading title")
    ap.add_argument("--maturity", default="phenomenon", choices=sorted(MATURITY))
    ap.add_argument("--certainty", default="0.3", choices=sorted(CANONICAL_CERTAINTY))
    ap.add_argument("--reportable", default="no", choices=sorted(REPORTABLE))
    ap.add_argument("--action", help="explicit action field; defaults from --query")
    ap.add_argument("--caused-by-us", default="no", choices=sorted(CAUSED_BY_US))
    ap.add_argument(
        "--alternative-explanation",
        help="benign/confounding explanation to preserve in the evidence entry",
    )
    ap.add_argument("--replicated-control", help="required for confirmed evidence")
    ap.add_argument(
        "--artifacts",
        help="legacy single saved artifact value (repeatable --artifact is preferred)",
    )
    ap.add_argument(
        "--artifact", action="append", default=[],
        help="one exact saved artifact path; repeat for every body and replay sidecar",
    )
    ap.add_argument("--supports", default="-", help="IDs this entry supports")
    ap.add_argument("--refutes", default="-", help="IDs this entry refutes")
    ap.add_argument("--unlocks", help="optional F-id unlocked by this confirmed fact")
    ap.add_argument("--next", help="next action")
    ap.add_argument("--dry-run", action="store_true", help="print the block without writing")
    ap.add_argument("--json", action="store_true", help="print machine-readable result")
    ap.add_argument("--selftest", action="store_true", help="run local regression tests")
    return ap


def main(argv: list[str] | None = None) -> int:
    ap = _parser()
    args = ap.parse_args(argv)
    if args.selftest:
        return _selftest()
    if not args.run:
        ap.error("--run is required unless --selftest is used")
    try:
        _validate_args(args)
        run_dir = _resolve_run_dir(args.run)
        if args.dry_run:
            text = (run_dir / "evidence.md").read_text(encoding="utf-8", errors="replace")
            placeholder = _template_placeholder_span(text)
            entry_id = placeholder[2] if placeholder else _next_id(text)
            print(_format_block(entry_id, args), end="")
            return 0
        result = append_entry(run_dir, args)
    except ValueError as exc:
        print(f"record_evidence: {exc}", file=sys.stderr)
        return 2

    if args.json:
        print(json.dumps({
            "id": result.entry_id,
            "path": str(result.path),
            "replaced_template": result.replaced_template,
        }, ensure_ascii=False))
    else:
        print(f"{result.entry_id} {result.path}")
    return 0


def _template_text() -> str:
    return """# Evidence Ledger

## E-001

- Maturity: phenomenon / candidate / finding
- Reportable: yes / no (confirmed vuln->report; coverage/verdict->summary)
- Time:
- Action:
- Source:
- Result:
- Caused by us: yes / no / unknown
- Alternative explanation:
- Certainty:
- Replicated / Control: (conditional)
- Replay: (conditional adjudication prose; not an artifact path list)
- Artifacts: (conditional; list each concrete path separately, including both a probe body and its .replay.json)
- Supports:
- Refutes:
- Unlocks: (conditional)
- Next:
"""


def _selftest() -> int:
    sys.path.insert(0, str(ROOT / "tools"))
    from evidence_parse import parse_evidence  # pylint: disable=import-error

    def run_cli(argv: list[str]) -> int:
        with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
            return main(argv)

    checks: list[tuple[str, bool]] = []
    d = Path(tempfile.mkdtemp())
    (d / "evidence.md").write_text(_template_text(), encoding="utf-8")

    base = [
        "--run", str(d),
        "--query", "Sample Product CVE 2026",
        "--date", "2026-07-07T00:00:00Z",
        "--finding", "Vendor advisory describes a fixed auth bypass.",
        "--provenance", "https://vendor.example/advisory.html",
    ]
    rc = run_cli(base + ["--json"])
    text = (d / "evidence.md").read_text(encoding="utf-8")
    recs = parse_evidence(d)
    checks.append(("first write replaces template E-001", rc == 0 and "phenomenon / candidate / finding" not in text))
    checks.append(("parser sees one low-maturity record", len(recs) == 1 and recs[0]["id"] == "E-001" and not recs[0]["confirmed"]))
    checks.append(("web research default trust is untrusted", recs[0]["trust"] == "untrusted"))
    checks.append(("Artifacts field scopes URL away from artifact parser", recs[0]["artifacts"] == [] and recs[0]["artifacts_scoped"]))

    rc2 = run_cli(base + [
        "--finding", "Independent docs mention the same product behavior.",
        "--provenance", "https://docs.example/product",
        "--certainty", "0.5",
        "--maturity", "candidate",
    ])
    recs2 = parse_evidence(d)
    checks.append(("second write appends E-002", rc2 == 0 and [r["id"] for r in recs2] == ["E-001", "E-002"]))
    checks.append(("canonical 0.5 stays unconfirmed candidate", recs2[1]["maturity"] == "candidate" and not recs2[1]["confirmed"]))

    bad = Path(tempfile.mkdtemp())
    (bad / "evidence.md").write_text("# Evidence Ledger\n", encoding="utf-8")
    rc3 = run_cli(base + ["--run", str(bad), "--certainty", "0.8", "--maturity", "finding"])
    checks.append(("web research cannot be promoted directly", rc3 == 2))

    proof = Path(tempfile.mkdtemp())
    (proof / "evidence.md").write_text("# Evidence Ledger\n", encoding="utf-8")
    (proof / "evidence").mkdir()
    (proof / "evidence" / "proof.html").write_text("proof", encoding="utf-8")
    (proof / "evidence" / "proof.html.replay.json").write_text(
        "{}", encoding="utf-8")
    rc4 = run_cli([
        "--run", str(proof),
        "--source", "target-session-artifact",
        "--action", "probe saved response",
        "--finding", "Saved response demonstrates the behavior.",
        "--provenance", "evidence/proof.html",
        "--certainty", "0.8",
        "--maturity", "finding",
        "--reportable", "yes",
        "--replicated-control", "baseline and mutant differ stably",
        "--artifact", "evidence/proof.html",
        "--artifact", "evidence/proof.html.replay.json",
    ])
    proof_rec = parse_evidence(proof)[0]
    checks.append(("target artifact default trust is untrusted", proof_rec["trust"] == "untrusted"))
    checks.append(("non-web confirmed entry can be recorded with proof fields", rc4 == 0))
    checks.append(("repeatable artifact producer preserves exact body/sidecar paths",
                   proof_rec["artifacts"] == [
                       "evidence/proof.html",
                       "evidence/proof.html.replay.json",
                   ]))

    rc5 = run_cli(base + ["--date", "yesterday"])
    checks.append(("malformed date is rejected", rc5 == 2))

    bad_names = [name for name, ok in checks if not ok]
    for name, ok in checks:
        print(("ok   " if ok else "FAIL ") + name)
    print("record_evidence selftest " + ("passed" if not bad_names else f"FAILED ({len(bad_names)})"))
    return 0 if not bad_names else 1


if __name__ == "__main__":
    raise SystemExit(main())
