#!/usr/bin/env python3
"""Derived closed-loop state for a Xunji run.

Markdown remains canonical. This tool joins the existing derived views
(`graph.py`, `state_project.py`, `coverage_matrix.py`, `saturation.py`, and the
Agent Board state) into one compact per-cycle loop snapshot. It measures whether
the last cycle produced substance, highlights gates the Root must handle, and
writes `state/loop_state.{json,md}` when asked.

It does not choose the next front, close a front, promote evidence, or write
canonical run facts.
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
import coverage_matrix  # noqa: E402
import graph  # noqa: E402
import saturation  # noqa: E402
import state_project  # noqa: E402
import workers  # noqa: E402

SCHEMA = "xunji.loop_state.v1"
CONFIRMED = 0.8
PYTHON_CMD = sys.executable or "python3"


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


def _evidence_summary(run_dir: Path) -> dict:
    records = parse_evidence(run_dir)
    cert_by_id: dict[str, float] = {}
    confirmed: list[str] = []
    findings: list[str] = []
    for rec in records:
        certs = rec.get("certainties") or []
        cert = max(certs) if certs else 0.0
        cert_by_id[str(rec.get("id"))] = cert
        if cert >= CONFIRMED and not rec.get("superseded"):
            confirmed.append(str(rec.get("id")))
            if rec.get("maturity") == "finding":
                findings.append(str(rec.get("id")))
    return {
        "total": len(records),
        "ids": sorted(cert_by_id),
        "cert_by_id": cert_by_id,
        "confirmed": sorted(confirmed),
        "confirmed_findings": sorted(findings),
    }


def _coverage_summary(run_dir: Path, *, write: bool) -> dict:
    data = coverage_matrix.write_outputs(run_dir) if write else coverage_matrix.derive(run_dir)
    tested_cells = sorted(
        f"{row['asset']}::{group}"
        for row in data.get("rows", [])
        for group, value in row.get("cells", {}).items()
        if value == "tested"
    )
    untested_cells = sorted(
        f"{row['asset']}::{group}"
        for row in data.get("rows", [])
        for group, value in row.get("cells", {}).items()
        if value == "untested"
    )
    return {
        "source": data.get("source", ""),
        "rows": len(data.get("rows", [])),
        "tested_cells": tested_cells,
        "untested_cells": untested_cells,
        "tested_cell_count": len(tested_cells),
        "untested_cell_count": len(untested_cells),
        "empty_columns": data.get("empty_columns", []),
        "row_gaps": data.get("row_gaps", []),
        "warnings": data.get("warnings", []),
    }


def _front_summary(run_dir: Path, view: dict, projection: dict) -> dict:
    fronts = [f for f in projection.get("fronts", []) if str(f.get("id", "")).startswith("F-")]
    open_fronts = [
        f for f in fronts
        if str(f.get("status", "")).lower() in {"open", "probing", "working"}
    ]
    deferred_fronts = [f for f in fronts if "deferred" in str(f.get("status", "")).lower()]
    closed_fronts = [f for f in fronts if "closed" in str(f.get("status", "")).lower()]
    barriers = [
        str(f.get("barrier") or "unknown").strip().lower()
        for f in open_fronts
        if str(f.get("barrier") or "").strip().lower() not in {"", "unknown", "none", "-"}
    ]
    unique_barriers = sorted(set(barriers))

    low_saturation: list[dict] = []
    for result in saturation.front_saturation(run_dir):
        ratio = result.get("ratio")
        if ratio is not None and ratio < 0.6:
            low_saturation.append({
                "front": result.get("front"),
                "ratio": round(float(ratio), 3),
                "tried": result.get("tried_count"),
                "untried": result.get("untried_count"),
            })

    return {
        "total": len(fronts),
        "open": [f.get("id") for f in open_fronts],
        "deferred": [f.get("id") for f in deferred_fronts],
        "closed": [f.get("id") for f in closed_fronts],
        "open_count": len(open_fronts),
        "deferred_count": len(deferred_fronts),
        "closed_count": len(closed_fronts),
        "actionable": view.get("actionable", []),
        "unlocked_deferred": view.get("unlocked_deferred", []),
        "closed_but_unlocked": view.get("closed_but_unlocked", []),
        "dangling_facts": view.get("dangling_facts", []),
        "unique_barriers": unique_barriers,
        "diverse_barriers": len(unique_barriers) >= 2,
        "low_saturation": low_saturation,
    }


def _agent_summary(run_dir: Path, *, write: bool) -> dict:
    assignments = workers.load_assignments(run_dir).get("assignments", [])
    if write:
        conflicts = workers.build_conflicts(run_dir).get("conflicts", [])
    else:
        conflicts = _read_json(run_dir / "state" / "conflicts.json", {}).get("conflicts", [])
    unresolved = [c for c in conflicts if c.get("status") == "unresolved"]
    rows = []
    for rec in assignments:
        if isinstance(rec, dict):
            rows.append({
                "agent": rec.get("agent"),
                "role": rec.get("role"),
                "front": rec.get("front"),
                "status": rec.get("status"),
            })
    return {
        "assignments": rows,
        "assignment_count": len(rows),
        "unresolved_conflicts": len(unresolved),
        "conflict_types": sorted({str(c.get("type")) for c in unresolved}),
    }


def _progress(previous: dict, evidence: dict, coverage: dict) -> dict:
    prev_progress = previous.get("progress", {}) if previous else {}
    prev_evidence_ids = set(prev_progress.get("evidence_ids", []))
    now_evidence_ids = set(evidence["ids"])
    new_evidence = sorted(now_evidence_ids - prev_evidence_ids) if previous else []

    prev_cert = prev_progress.get("cert_by_id", {}) if previous else {}
    upgrades = []
    if previous:
        for eid, cert in evidence["cert_by_id"].items():
            old = float(prev_cert.get(eid, 0.0) or 0.0)
            if cert > old:
                upgrades.append({"id": eid, "from": old, "to": cert})

    prev_cells = set(prev_progress.get("coverage_tested_cells", []))
    now_cells = set(coverage["tested_cells"])
    new_cells = sorted(now_cells - prev_cells) if previous else []

    made_progress = bool(new_evidence or upgrades or new_cells)
    prev_no_progress = int(prev_progress.get("no_progress_cycles", 0) or 0)
    no_progress_cycles = 0 if made_progress or not previous else prev_no_progress + 1

    return {
        "evidence_total": evidence["total"],
        "evidence_ids": evidence["ids"],
        "new_evidence_ids": new_evidence,
        "cert_by_id": evidence["cert_by_id"],
        "certainty_upgrades": upgrades,
        "confirmed_evidence": evidence["confirmed"],
        "confirmed_findings": evidence["confirmed_findings"],
        "coverage_tested_cells": coverage["tested_cells"],
        "coverage_new_tested_cells": new_cells,
        "coverage_tested_cell_count": coverage["tested_cell_count"],
        "coverage_untested_cell_count": coverage["untested_cell_count"],
        "made_progress": made_progress,
        "no_progress_cycles": no_progress_cycles,
        "coda_converged": no_progress_cycles >= 2,
    }


def _phase(fronts: dict, progress: dict) -> str:
    if fronts["open_count"]:
        return "Driver"
    if fronts["deferred_count"] or progress["confirmed_evidence"]:
        return "Reviewer"
    if fronts["closed_count"]:
        return "Closure"
    return "Setup"


def _gates(fronts: dict, agents: dict, progress: dict, coverage: dict) -> dict:
    fanout_required = fronts["open_count"] >= 4 and fronts["diverse_barriers"]
    completion_pause_candidate = (
        progress["coda_converged"]
        or (fronts["open_count"] == 0 and not fronts["unlocked_deferred"])
    )
    near_closure = completion_pause_candidate or (
        fronts["open_count"] == 0 and bool(progress["confirmed_evidence"])
    )
    return {
        "fanout_required": fanout_required,
        "fanout_reason": (
            "open fronts >= 4 and barrier classes are diverse"
            if fanout_required else ""
        ),
        "completion_pause_candidate": completion_pause_candidate,
        "needs_conflict_resolution": agents["unresolved_conflicts"] > 0,
        "needs_coverage_attention": bool(coverage["empty_columns"] or coverage["row_gaps"]),
        "needs_saturation_attention": bool(fronts["low_saturation"]),
        "near_closure": near_closure,
        "closure_commands": [
            f"{PYTHON_CMD} tools/workers.py agent-check <run>",
            f"{PYTHON_CMD} tools/workers.py merge-check <run>",
            f"{PYTHON_CMD} tools/check_run.py <run>",
            f"{PYTHON_CMD} tools/check_run.py <run> --replay-verify",
            f"{PYTHON_CMD} tools/peer_review.py <run> --into-run",
        ] if near_closure else [],
    }


def _next_actions(fronts: dict, agents: dict, progress: dict, gates: dict) -> list[str]:
    actions: list[str] = []
    if gates["needs_conflict_resolution"]:
        actions.append("Resolve Agent Board conflicts before promotion or closure.")
    if gates["fanout_required"]:
        actions.append("Run workers.py suggest/plan and assign at least two disjoint Agent lanes.")
    if fronts["closed_but_unlocked"]:
        actions.append("Reopen or re-adjudicate fronts that are closed but unlocked by confirmed evidence.")
    if fronts["unlocked_deferred"]:
        actions.append("Activate deferred fronts unlocked by confirmed evidence.")
    if gates["needs_saturation_attention"]:
        actions.append("Expand or justify low-saturation fronts before any explored-enough claim.")
    if gates["needs_coverage_attention"]:
        actions.append("Update fronts/evidence for coverage matrix empty columns or sparse rows.")
    if progress["coda_converged"]:
        actions.append("Trigger completion pause: run closure gates, independent review, and retrospective.")
    elif not fronts["open_count"] and not fronts["unlocked_deferred"]:
        actions.append("No open front visible; run review/closure checks or reopen missing work.")
    else:
        actions.append("Choose the next front from actionable/open fronts and record a Root graph pass.")
    return actions


def derive(run_dir: Path, *, write: bool = False) -> dict:
    run_dir = _resolve_run_dir(run_dir)
    if not run_dir.exists():
        raise FileNotFoundError(f"run directory does not exist: {run_dir}")

    previous = _read_json(run_dir / "state" / "loop_state.json", {})
    # Refresh the standard derived projections only in write mode. They remain
    # caches; the default read path should not mutate a run directory.
    projection = state_project.write_projection(run_dir) if write else state_project.derive(run_dir)
    g = graph.build_graph(run_dir)
    view = graph.derive_view(g, run_dir)
    if write:
        _write(run_dir / "graph.json", json.dumps({**g, "view": view}, ensure_ascii=False, indent=2) + "\n")
        graph._write_checkpoint(run_dir, g)  # project-internal cache writer

    evidence = _evidence_summary(run_dir)
    coverage = _coverage_summary(run_dir, write=write)
    fronts = _front_summary(run_dir, view, projection)
    agents = _agent_summary(run_dir, write=write)
    progress = _progress(previous, evidence, coverage)
    gates = _gates(fronts, agents, progress, coverage)
    phase = _phase(fronts, progress)
    actions = _next_actions(fronts, agents, progress, gates)

    return {
        "schema": SCHEMA,
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "canonical": "Markdown run files remain source of truth; this is a derived cache.",
        "run_dir": str(run_dir),
        "phase": phase,
        "fronts": fronts,
        "agents": agents,
        "coverage": coverage,
        "progress": progress,
        "gates": gates,
        "next_actions": actions,
    }


def render_markdown(data: dict) -> str:
    progress = data["progress"]
    fronts = data["fronts"]
    agents = data["agents"]
    gates = data["gates"]
    lines = [
        "# Loop State",
        "",
        f"- Phase: {data['phase']}",
        f"- Open/deferred/closed fronts: {fronts['open_count']} / {fronts['deferred_count']} / {fronts['closed_count']}",
        f"- Evidence: {progress['evidence_total']} total; new this cycle: {len(progress['new_evidence_ids'])}; certainty upgrades: {len(progress['certainty_upgrades'])}",
        f"- Coverage: {progress['coverage_tested_cell_count']} tested cells; new this cycle: {len(progress['coverage_new_tested_cells'])}; untested applicable cells: {progress['coverage_untested_cell_count']}",
        f"- No-progress cycles: {progress['no_progress_cycles']} ({'Coda converged' if progress['coda_converged'] else 'continue'})",
        f"- Agents: {agents['assignment_count']} assignments; unresolved conflicts: {agents['unresolved_conflicts']}",
        f"- Fan-out required: {'yes' if gates['fanout_required'] else 'no'}",
        f"- Completion pause candidate: {'yes' if gates['completion_pause_candidate'] else 'no'}",
        "",
        "## Next Actions",
        "",
    ]
    lines.extend(f"- {a}" for a in data.get("next_actions", []))
    if fronts.get("low_saturation"):
        lines.extend(["", "## Low Saturation", ""])
        for item in fronts["low_saturation"]:
            lines.append(
                f"- {item['front']}: ratio={item['ratio']} tried={item['tried']} untried={item['untried']}"
            )
    if data["coverage"].get("empty_columns"):
        lines.extend(["", "## Coverage Empty Columns", ""])
        lines.extend(f"- {c}" for c in data["coverage"]["empty_columns"])
    return "\n".join(lines) + "\n"


def write_outputs(run_dir: Path) -> dict:
    data = derive(run_dir, write=True)
    state = _resolve_run_dir(run_dir) / "state"
    _write(state / "loop_state.json", json.dumps(data, ensure_ascii=False, indent=2) + "\n")
    _write(state / "loop_state.md", render_markdown(data))
    return data


def _selftest() -> int:
    d = Path(tempfile.mkdtemp())
    run = d / "run"
    run.mkdir()
    (run / "frontier.md").write_text(
        "# Frontier\n\n"
        "## Open Fronts\n\n"
        "### F-001 Login\n"
        "- Status: open\n"
        "- Barrier class: auth-gate\n"
        "- Surface subtype: login\n"
        "- Vectors tried: auth bypass\n"
        "- Untried classes: SQLi-login, enum, default-creds\n\n"
        "### F-002 API\n"
        "- Status: open\n"
        "- Barrier class: api-filter\n"
        "- Surface subtype: param-api\n"
        "- Vectors tried: SQLi\n"
        "- Untried classes: IDOR\n\n"
        "### F-003 Admin\n"
        "- Status: open\n"
        "- Barrier class: admin-login\n"
        "- Surface subtype: login\n"
        "- Vectors tried: enum\n\n"
        "### F-004 Upload\n"
        "- Status: open\n"
        "- Barrier class: upload-filter\n"
        "- Surface subtype: upload\n"
        "- Vectors tried: upload-to-shell\n",
        encoding="utf-8",
    )
    (run / "hypotheses.md").write_text("# Hypotheses\n", encoding="utf-8")
    (run / "decisions.md").write_text("# Decisions\n", encoding="utf-8")
    (run / "evidence.md").write_text(
        "# Evidence Ledger\n\n"
        "## E-001\n"
        "- Maturity: candidate\n"
        "- Certainty: 0.5\n"
        "- Supports: F-001\n",
        encoding="utf-8",
    )
    (run / "coverage.json").write_text(json.dumps({"assets": [
        {"host": "login.example", "reachable": True, "flags": ["LOGIN"]},
        {"host": "api.example", "reachable": True, "flags": ["SURFACE:API"]},
    ]}), encoding="utf-8")

    first = write_outputs(run)
    second = write_outputs(run)
    third = write_outputs(run)
    (run / "evidence.md").write_text(
        "# Evidence Ledger\n\n"
        "## E-001\n"
        "- Maturity: finding\n"
        "- Certainty: 0.8\n"
        "- Control: baseline\n"
        "- Supports: F-001\n",
        encoding="utf-8",
    )
    (run / "frontier.md").write_text(
        (run / "frontier.md").read_text(encoding="utf-8")
        .replace("- Surface subtype: param-api\n- Vectors tried: SQLi\n",
                 "- Surface subtype: param-api\n- Assets: api.example\n- Vectors tried: SQLi, IDOR\n"),
        encoding="utf-8",
    )
    fourth = write_outputs(run)

    agent_run = d / "agent_run"
    agent_run.mkdir()
    (agent_run / "frontier.md").write_text(
        "# Frontier\n\n## Open Fronts\n\n### F-001\n- Status: open\n",
        encoding="utf-8",
    )
    (agent_run / "evidence.md").write_text("# Evidence Ledger\n", encoding="utf-8")
    (agent_run / "decisions.md").write_text("# Decisions\n", encoding="utf-8")
    (agent_run / "hypotheses.md").write_text("# Hypotheses\n", encoding="utf-8")
    (agent_run / "agents").mkdir()
    (agent_run / "state").mkdir()
    (agent_run / "state" / "assignments.json").write_text(json.dumps({
        "assignments": [
            {"agent": "A-support-001", "role": "web-hunter", "front": "F-001", "status": "done"},
            {"agent": "A-refute-001", "role": "verify", "front": "F-001", "status": "done"},
        ],
    }), encoding="utf-8")
    (agent_run / "agents" / "A-support-001.md").write_text(
        "# Agent A-support-001\n"
        "- Role: web-hunter\n- Assigned front: F-001\n- Status: done\n"
        "- Supports: candidate auth bypass\n- Refutes:\n- Confidence: 0.5\n",
        encoding="utf-8",
    )
    (agent_run / "agents" / "A-refute-001.md").write_text(
        "# Agent A-refute-001\n"
        "- Role: verify\n- Assigned front: F-001\n- Status: done\n"
        "- Supports:\n- Refutes: candidate auth bypass\n- Confidence: 0.5\n",
        encoding="utf-8",
    )
    agent_state = write_outputs(agent_run)

    no_write = d / "no_write"
    no_write.mkdir()
    (no_write / "frontier.md").write_text(
        "# Frontier\n\n## Open Fronts\n\n### F-001\n- Status: open\n",
        encoding="utf-8",
    )
    (no_write / "evidence.md").write_text("# Evidence Ledger\n", encoding="utf-8")
    (no_write / "decisions.md").write_text("# Decisions\n", encoding="utf-8")
    (no_write / "hypotheses.md").write_text("# Hypotheses\n", encoding="utf-8")
    no_write_data = derive(no_write, write=False)
    checks = [
        ("writes loop state json", (run / "state" / "loop_state.json").exists()),
        ("writes loop state markdown", (run / "state" / "loop_state.md").exists()),
        ("fanout required with four diverse open fronts", first["gates"]["fanout_required"]),
        ("coverage attention is surfaced", first["gates"]["needs_coverage_attention"]),
        ("first snapshot does not count existing evidence as new", first["progress"]["new_evidence_ids"] == []),
        ("no-progress cycles increase", second["progress"]["no_progress_cycles"] == 1),
        ("coda converges after two no-progress cycles", third["progress"]["coda_converged"]),
        ("certainty upgrade resets no-progress", fourth["progress"]["certainty_upgrades"]
         and fourth["progress"]["no_progress_cycles"] == 0),
        ("coverage improvement is recorded", fourth["progress"]["coverage_new_tested_cells"]),
        ("coverage outputs written", (run / "state" / "coverage_matrix.json").exists()),
        ("graph checkpoint written", (run / "state" / "workflow_checkpoint.json").exists()),
        ("agent conflicts are surfaced", agent_state["agents"]["unresolved_conflicts"] == 1
         and agent_state["gates"]["needs_conflict_resolution"]),
        ("default derive is no-write", no_write_data["schema"] == SCHEMA
         and not (no_write / "state").exists()
         and not (no_write / "graph.json").exists()),
    ]
    bad = [name for name, ok in checks if not ok]
    for name, ok in checks:
        print(("ok   " if ok else "FAIL ") + name)
    print("loop_state selftest " + ("passed" if not bad else f"FAILED ({len(bad)})"))
    return 0 if not bad else 1


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    ap = argparse.ArgumentParser(description="derive the Xunji closed-loop state for one run")
    ap.add_argument("run_dir", nargs="?", type=Path)
    ap.add_argument("--write", action="store_true", help="write state/loop_state.{json,md} and dependent caches")
    ap.add_argument("--json", action="store_true", help="print JSON instead of Markdown")
    ap.add_argument("--selftest", action="store_true")
    args = ap.parse_args(argv)

    if args.selftest:
        return _selftest()
    if not args.run_dir:
        ap.error("run_dir is required")
    try:
        data = write_outputs(args.run_dir) if args.write else derive(args.run_dir, write=False)
    except FileNotFoundError as e:
        print(f"[loop_state] {e}", file=sys.stderr)
        return 1
    if args.json:
        print(json.dumps(data, ensure_ascii=False, indent=2))
    else:
        print(render_markdown(data), end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
