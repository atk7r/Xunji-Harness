#!/usr/bin/env python3
"""Derived progress ledger for one Xunji run cycle.

Markdown remains canonical. This helper reads `state/loop_state.json` when it is
fresh enough for the current cycle, falls back to deriving loop state, and writes
`state/progress_ledger.json` only when asked. It records whether the last cycle
produced material progress; it does not choose work, promote evidence, or close a
run.
"""
from __future__ import annotations

import argparse
import json
import sys
import tempfile
import time
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
except Exception:
    pass

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

from evidence_parse import parse_evidence  # noqa: E402
import loop_state  # noqa: E402

SCHEMA = "xunji.progress_ledger.v1"


def _resolve_run_dir(path: str | Path) -> Path:
    p = Path(path)
    return (p if p.is_absolute() else ROOT / p).resolve()


def _read_json(path: Path, default):
    try:
        data = json.loads(path.read_text(encoding="utf-8", errors="replace"))
        return data if isinstance(data, type(default)) else default
    except Exception:
        return default


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _load_loop_state(run_dir: Path) -> dict:
    cached = _read_json(run_dir / "state" / "loop_state.json", {})
    if cached.get("schema") == loop_state.SCHEMA:
        return cached
    return loop_state.derive(run_dir, write=False)


def _artifact_backing(run_dir: Path) -> dict[str, dict]:
    out: dict[str, dict] = {}
    for rec in parse_evidence(run_dir):
        eid = str(rec.get("id") or "")
        if not eid:
            continue
        out[eid] = {
            "artifacts_present": sorted(rec.get("artifacts_present", [])),
            "has_control": bool(rec.get("has_control")),
            "confirmed": bool(rec.get("confirmed")),
            "maturity": rec.get("maturity"),
        }
    return out


def derive(run_dir: Path, *, loop_data: dict | None = None) -> dict:
    run_dir = _resolve_run_dir(run_dir)
    if not run_dir.exists():
        raise FileNotFoundError(f"run directory does not exist: {run_dir}")

    state = loop_data if loop_data is not None else _load_loop_state(run_dir)
    progress = state.get("progress", {})
    evidence = _artifact_backing(run_dir)
    new_ids = [str(e) for e in progress.get("new_evidence_ids", [])]
    upgrades = progress.get("certainty_upgrades", [])
    new_cells = [str(c) for c in progress.get("coverage_new_tested_cells", [])]

    new_evidence = []
    for eid in new_ids:
        backing = evidence.get(eid, {})
        new_evidence.append({
            "id": eid,
            "artifact_backed": bool(backing.get("artifacts_present")),
            "has_control": bool(backing.get("has_control")),
            "confirmed": bool(backing.get("confirmed")),
            "maturity": backing.get("maturity"),
        })

    certainty_upgrades = []
    for item in upgrades if isinstance(upgrades, list) else []:
        if not isinstance(item, dict):
            continue
        eid = str(item.get("id") or "")
        backing = evidence.get(eid, {})
        certainty_upgrades.append({
            "id": eid,
            "from": item.get("from"),
            "to": item.get("to"),
            "artifact_backed": bool(backing.get("artifacts_present")),
            "has_control": bool(backing.get("has_control")),
            "confirmed": bool(backing.get("confirmed")),
            "maturity": backing.get("maturity"),
        })

    artifact_backed = any(i["artifact_backed"] for i in new_evidence) or any(
        i["artifact_backed"] for i in certainty_upgrades
    )
    material_progress = bool(new_ids or certainty_upgrades or new_cells)
    warnings = []
    if material_progress and new_cells and not (new_ids or certainty_upgrades):
        warnings.append("coverage-only progress; verify the row/cell change is backed by a recorded front or E-entry")
    if (new_ids or certainty_upgrades) and not artifact_backed:
        warnings.append("evidence progress lacks saved artifact backing")

    return {
        "schema": SCHEMA,
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "canonical": "Markdown run files remain source of truth; this is a derived cache.",
        "run_dir": str(run_dir),
        "loop_state_generated_at": state.get("generated_at"),
        "cycle": {
            "material_progress": material_progress,
            "artifact_backed_progress": artifact_backed,
            "new_evidence": new_evidence,
            "certainty_upgrades": certainty_upgrades,
            "coverage_new_tested_cells": new_cells,
            "no_progress_cycles": progress.get("no_progress_cycles", 0),
            "coda_converged": bool(progress.get("coda_converged")),
            "warnings": warnings,
        },
    }


def render_markdown(data: dict) -> str:
    cycle = data["cycle"]
    lines = [
        "# Progress Ledger",
        "",
        f"- Material progress: {'yes' if cycle['material_progress'] else 'no'}",
        f"- Artifact-backed progress: {'yes' if cycle['artifact_backed_progress'] else 'no'}",
        f"- New evidence: {len(cycle['new_evidence'])}",
        f"- Certainty upgrades: {len(cycle['certainty_upgrades'])}",
        f"- Coverage cells: {len(cycle['coverage_new_tested_cells'])}",
        f"- No-progress cycles: {cycle['no_progress_cycles']}",
    ]
    if cycle.get("warnings"):
        lines.extend(["", "## Warnings", ""])
        lines.extend(f"- {w}" for w in cycle["warnings"])
    return "\n".join(lines) + "\n"


def write_outputs(run_dir: Path) -> dict:
    run_dir = _resolve_run_dir(run_dir)
    data = derive(run_dir)
    path = run_dir / "state" / "progress_ledger.json"
    old = _read_json(path, {})
    cycles = list(old.get("cycles", [])) if isinstance(old.get("cycles"), list) else []
    cycles.append(data["cycle"] | {"generated_at": data["generated_at"]})
    # Keep this cache bounded. Canonical history remains in Markdown decisions and
    # evidence; this ledger is only a recent-cycle control-plane aid.
    data["cycles"] = cycles[-50:]
    _write(path, json.dumps(data, ensure_ascii=False, indent=2) + "\n")
    _write(run_dir / "state" / "progress_ledger.md", render_markdown(data))
    return data


def _selftest() -> int:
    d = Path(tempfile.mkdtemp())
    run = d / "run"
    run.mkdir()
    (run / "frontier.md").write_text(
        "# Frontier\n\n## Open Fronts\n\n### F-001\n- Status: open\n",
        encoding="utf-8",
    )
    (run / "hypotheses.md").write_text("# Hypotheses\n", encoding="utf-8")
    (run / "decisions.md").write_text("# Decisions\n", encoding="utf-8")
    (run / "evidence.md").write_text("# Evidence Ledger\n", encoding="utf-8")
    first_loop = loop_state.write_outputs(run)
    first = write_outputs(run)

    (run / "evidence").mkdir()
    (run / "evidence" / "proof.html").write_text("proof", encoding="utf-8")
    (run / "evidence.md").write_text(
        "# Evidence Ledger\n\n"
        "## E-001\n"
        "- Maturity: finding\n"
        "- Control: baseline\n"
        "- Artifacts: evidence/proof.html\n"
        "- Certainty: 0.8\n"
        "- Supports: F-001\n",
        encoding="utf-8",
    )
    second_loop = loop_state.write_outputs(run)
    second = write_outputs(run)
    checks = [
        ("first cycle has no material progress", first_loop["progress"]["new_evidence_ids"] == []
         and not first["cycle"]["material_progress"]),
        ("new artifact-backed evidence is material progress",
         second_loop["progress"]["new_evidence_ids"] == ["E-001"]
         and second["cycle"]["material_progress"]
         and second["cycle"]["artifact_backed_progress"]),
        ("ledger json written with history", (run / "state" / "progress_ledger.json").exists()
         and len(_read_json(run / "state" / "progress_ledger.json", {}).get("cycles", [])) == 2),
        ("markdown render mentions material progress", "Material progress: yes" in render_markdown(second)),
    ]
    bad = [name for name, ok in checks if not ok]
    for name, ok in checks:
        print(("ok   " if ok else "FAIL ") + name)
    print("progress_ledger selftest " + ("passed" if not bad else f"FAILED ({len(bad)})"))
    return 0 if not bad else 1


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    ap = argparse.ArgumentParser(description="derive the Xunji material-progress ledger for one run")
    ap.add_argument("run_dir", nargs="?", type=Path)
    ap.add_argument("--write", action="store_true", help="write state/progress_ledger.{json,md}")
    ap.add_argument("--json", action="store_true", help="print JSON instead of Markdown")
    ap.add_argument("--selftest", action="store_true")
    args = ap.parse_args(argv)

    if args.selftest:
        return _selftest()
    if not args.run_dir:
        ap.error("run_dir is required")
    try:
        data = write_outputs(args.run_dir) if args.write else derive(args.run_dir)
    except FileNotFoundError as e:
        print(f"[progress_ledger] {e}", file=sys.stderr)
        return 1
    if args.json:
        print(json.dumps(data, ensure_ascii=False, indent=2))
    else:
        print(render_markdown(data), end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
