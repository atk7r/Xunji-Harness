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
import os
import re
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
import status_style  # noqa: E402
import workers  # noqa: E402

SCHEMA = "xunji.loop_state.v1"
CONFIRMED = 0.8
PYTHON_CMD = sys.executable or "python3"
OPEN_STATUS_TOKENS = {"open", "probing", "working", "blocked_type_a"}
CLOSED_STATUS_TOKENS = {"closed", "closing", "final", "done", "complete", "completed", "blocked_type_b"}
ACTION_TEXT_CN = {
    "Resolve Agent Board conflicts before promotion or closure.": "先解决 Agent Board 冲突，再考虑提升证据或收口。",
    "Run workers.py suggest/plan and assign at least two disjoint Agent lanes.": "运行 workers.py suggest/plan，并分派至少两条不重叠 Agent 线路。",
    "Reopen or re-adjudicate fronts that are closed but unlocked by confirmed evidence.": "重开或重新裁定那些已关闭但被确认型证据重新解锁的前线。",
    "Activate deferred fronts unlocked by confirmed evidence.": "激活被确认型证据解锁的延后前线。",
    "Expand or justify low-saturation fronts before any explored-enough claim.": "在声称探索充分前，扩展低饱和前线或写明不继续的理由。",
    "Update fronts/evidence for coverage matrix empty columns or sparse rows.": "根据覆盖矩阵空列或稀疏行补 frontier/evidence。",
    "Fix unclassified front statuses before closure review.": "先修正未分类前线状态，再进入收口复核。",
    "Coda convergence: record a trajectory review, pivot/continue rationale, or review/surface Agent assignment; this is not a closure signal by itself.": "Coda 已收敛：记录轨迹复盘、换路/继续理由，或分派复审/面扩 Agent；这本身不是收口信号。",
    "Closure review candidate: run hard closure gates, replay verification, independent review, and retrospective before any pause.": "收口复核候选：暂停前必须跑硬收口闸门、replay 核实、独立复审和复盘。",
    "No open front visible, but closure blockers remain; reopen or justify missing work before closure.": "当前看不到开放前线，但仍有收口阻断项；收口前必须重开或解释缺失工作。",
    "No open front visible; run review/closure checks or reopen missing work.": "当前看不到开放前线；运行复审/收口检查，或重开缺失工作。",
    "Choose the next front from actionable/open fronts and record a Root graph pass.": "从可行动/开放前线中选择下一条，并记录 Root graph pass。",
    "Run is marked complete; do not schedule another /loop iteration.": "运行已标记完成；不要再排下一轮 /loop。",
}


def _strip_fenced_code(text: str) -> str:
    return re.sub(r"(?ms)^(```|~~~)[^\n]*\n.*?^\1[ \t]*\n?", "", text)


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


def _status_tokens(raw: object) -> set[str]:
    normalized = str(raw or "").lower().replace("-", "_")
    tokens: set[str] = set()
    for tok in re.findall(r"[a-z0-9_]+", normalized):
        if not tok:
            continue
        tokens.add(tok)
        tokens.update(part for part in tok.split("_") if part)
    return tokens


def _is_open_status(raw: object) -> bool:
    tokens = _status_tokens(raw)
    if (CLOSED_STATUS_TOKENS | {"deferred"}) & tokens:
        return False
    return bool(tokens & OPEN_STATUS_TOKENS)


def _is_deferred_status(raw: object) -> bool:
    tokens = _status_tokens(raw)
    return "deferred" in tokens and not (CLOSED_STATUS_TOKENS & tokens)


def _is_closed_status(raw: object) -> bool:
    tokens = _status_tokens(raw)
    return bool(CLOSED_STATUS_TOKENS & tokens) and "deferred" not in tokens


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


def _front_section_statuses(run_dir: Path) -> dict[str, str]:
    text = (run_dir / "frontier.md").read_text(encoding="utf-8", errors="replace") \
        if (run_dir / "frontier.md").exists() else ""
    text = _strip_fenced_code(text)
    out: dict[str, str] = {}
    for section, status in (
        ("Open Fronts", "open"),
        ("Deferred Fronts", "deferred"),
        ("Closed Fronts", "closed"),
    ):
        m = re.search(rf"(?ms)^##[ \t]+{re.escape(section)}\b(.*?)(?=^##[ \t]+|\Z)", text)
        if not m:
            continue
        for fm in re.finditer(r"(?m)^###[ \t]+(F-\d+)\b", m.group(1)):
            out[fm.group(1)] = status
    return out


def _front_summary(run_dir: Path, view: dict, projection: dict) -> dict:
    real_front_ids = {fid for fid, _ in _front_blocks_text(run_dir)}
    fronts = [
        f for f in projection.get("fronts", [])
        if str(f.get("id", "")).startswith("F-")
        and (not real_front_ids or str(f.get("id")) in real_front_ids)
    ]
    section_statuses = _front_section_statuses(run_dir)

    def front_status(f: dict) -> str:
        raw = str(f.get("status", "") or "").strip()
        if raw.lower() in {"", "unknown"}:
            raw = section_statuses.get(str(f.get("id")), raw)
        return raw

    open_fronts = [f for f in fronts if _is_open_status(front_status(f))]
    deferred_fronts = [f for f in fronts if _is_deferred_status(front_status(f))]
    closed_fronts = [f for f in fronts if _is_closed_status(front_status(f))]
    blocked_type_a = [
        f.get("id") for f in fronts
        if "blocked_type_a" in _status_tokens(front_status(f))
    ]
    blocked_type_b = [
        f.get("id") for f in fronts
        if "blocked_type_b" in _status_tokens(front_status(f))
    ]
    unclassified_status = [
        f.get("id") for f in fronts
        if (
            not _is_open_status(front_status(f))
            and not _is_deferred_status(front_status(f))
            and not _is_closed_status(front_status(f))
            and "blocked_type_b" not in _status_tokens(front_status(f))
        )
    ]
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
        "blocked_type_a": blocked_type_a,
        "blocked_type_b": blocked_type_b,
        "unclassified_status": unclassified_status,
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
    """Return the visible Router phase best inferred from canonical run files.

    Hunter is a transient action phase and is marked by loop_journal phase events;
    it is not safely inferable from static Markdown after the fact.
    """
    if fronts["open_count"]:
        return "Root Orchestrator"
    if fronts["deferred_count"] or progress["confirmed_evidence"]:
        return "Reviewer"
    if fronts["closed_count"]:
        return "Report"
    return "Setup"


def _phase_display(phase: str, *, color: bool | None = None) -> str:
    return status_style.phase_display(phase, enabled=color)


def _yes_no(value: object) -> str:
    return "是" if value else "否"


def _action_display(action: str, *, color: bool | None = None) -> str:
    cn = ACTION_TEXT_CN.get(action)
    return f"{cn} {status_style.tag(action, 'gray', enabled=color)}" if cn else action


def _pretty_block(title: str, rows: list[str], *, color: str = "cyan", enabled: bool | None = None) -> str:
    return status_style.box(title, rows, color=color, enabled=enabled)


def _gates(fronts: dict, agents: dict, progress: dict, coverage: dict) -> dict:
    fanout_required = fronts["open_count"] >= 4 and fronts["diverse_barriers"]
    needs_conflict_resolution = agents["unresolved_conflicts"] > 0
    needs_coverage_attention = bool(coverage["empty_columns"] or coverage["row_gaps"])
    needs_saturation_attention = bool(fronts["low_saturation"])
    closure_blockers: list[str] = []
    if fronts["open_count"]:
        closure_blockers.append("open_fronts_present")
    if fronts["unlocked_deferred"]:
        closure_blockers.append("unlocked_deferred_fronts")
    if fronts.get("unclassified_status"):
        closure_blockers.append("unclassified_front_status")
    if needs_conflict_resolution:
        closure_blockers.append("unresolved_agent_conflicts")
    if needs_coverage_attention:
        closure_blockers.append("coverage_attention_required")
    if needs_saturation_attention:
        closure_blockers.append("saturation_attention_required")
    completion_pause_candidate = fronts["total"] > 0 and not closure_blockers
    near_closure = completion_pause_candidate and bool(
        progress["confirmed_evidence"] or fronts["closed_count"] or fronts["deferred_count"]
    )
    return {
        "fanout_required": fanout_required,
        "fanout_reason": (
            "open fronts >= 4 and barrier classes are diverse"
            if fanout_required else ""
        ),
        "completion_pause_candidate": completion_pause_candidate,
        "needs_progress_pivot": bool(progress["coda_converged"]),
        "needs_conflict_resolution": needs_conflict_resolution,
        "needs_coverage_attention": needs_coverage_attention,
        "needs_saturation_attention": needs_saturation_attention,
        "closure_blockers": closure_blockers,
        "near_closure": near_closure,
        "closure_commands": [
            f"{PYTHON_CMD} tools/workers.py agent-check <run>",
            f"{PYTHON_CMD} tools/workers.py merge-check <run>",
            f"{PYTHON_CMD} tools/check_run.py <run>",
            f"{PYTHON_CMD} tools/check_run.py <run> --replay-verify",
            f"{PYTHON_CMD} tools/peer_review.py <run> --into-run",
        ] if near_closure else [],
    }


def _completion_markers(run_dir: Path) -> list[str]:
    path = run_dir / "decisions.md"
    if not path.exists():
        return []
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except Exception:
        return []
    markers = []
    for marker in ("GHOST_COMPLETE", "NORMAL_COMPLETE"):
        if re.search(rf"(?<![A-Z0-9_]){marker}(?![A-Z0-9_])", text):
            markers.append(marker)
    return markers


def _next_actions(fronts: dict, agents: dict, progress: dict, gates: dict) -> list[str]:
    actions: list[str] = []
    if gates.get("loop_complete"):
        return ["Run is marked complete; do not schedule another /loop iteration."]
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
    if fronts.get("unclassified_status"):
        actions.append("Fix unclassified front statuses before closure review.")
    if progress["coda_converged"]:
        actions.append("Coda convergence: record a trajectory review, pivot/continue rationale, or review/surface Agent assignment; this is not a closure signal by itself.")
    if gates["completion_pause_candidate"]:
        actions.append("Closure review candidate: run hard closure gates, replay verification, independent review, and retrospective before any pause.")
    elif not fronts["open_count"] and not fronts["unlocked_deferred"]:
        if gates.get("closure_blockers"):
            actions.append("No open front visible, but closure blockers remain; reopen or justify missing work before closure.")
        else:
            actions.append("No open front visible; run review/closure checks or reopen missing work.")
    else:
        actions.append("Choose the next front from actionable/open fronts and record a Root graph pass.")
    return actions


def _front_blocks_text(run_dir: Path) -> list[tuple[str, str]]:
    text = (run_dir / "frontier.md").read_text(encoding="utf-8", errors="replace") \
        if (run_dir / "frontier.md").exists() else ""
    text = _strip_fenced_code(text)
    out: list[tuple[str, str]] = []
    for m in re.finditer(r"(?ms)^###[ \t]+(F-\d+).*?(?=^###[ \t]+F-\d+|\Z)", text):
        out.append((m.group(1), m.group(0)))
    return out


def _field(block: str, name: str) -> str:
    m = re.search(rf"(?im)^\s*[-*]?\s*{re.escape(name)}\s*[:：]\s*([^\n]*)$", block)
    return m.group(1).strip() if m else ""


def _open_high_threat_fronts(run_dir: Path) -> list[str]:
    out: list[str] = []
    for fid, block in _front_blocks_text(run_dir):
        status = _field(block, "Status").lower()
        role = _field(block, "Threat role").lower()
        exposure = _field(block, "Threat exposure").lower()
        if _is_open_status(status) and role in {"admin-mgmt", "identity-auth", "data-pii"}:
            out.append(fid if exposure != "public-unauth" else f"{fid}(public-unauth)")
    return out


def _high_threat_deferred_without_evidence(run_dir: Path) -> list[str]:
    ev_text = (run_dir / "evidence.md").read_text(encoding="utf-8", errors="replace").lower() \
        if (run_dir / "evidence.md").exists() else ""
    out: list[str] = []
    for fid, block in _front_blocks_text(run_dir):
        status = _field(block, "Status").lower()
        role = _field(block, "Threat role").lower()
        exposure = _field(block, "Threat exposure").lower()
        if "deferred" in status and role in {"admin-mgmt", "identity-auth", "data-pii"} \
                and exposure == "public-unauth" and fid.lower() not in ev_text:
            out.append(fid)
    return out


def _open_threat_hypotheses_without_action(run_dir: Path) -> list[str]:
    path = run_dir / "hypotheses.md"
    if not path.exists():
        return []
    text = path.read_text(encoding="utf-8", errors="replace")
    out: list[str] = []
    for m in re.finditer(r"(?ms)^##[ \t]+(H-\d+).*?(?=^##[ \t]+H-\d+|\Z)", text):
        block = m.group(0)
        if not _field(block, "Threat hypothesis"):
            continue
        status = (_field(block, "Status") or "open").lower()
        if status not in {"open", "suspected", "candidate"}:
            continue
        next_action = _field(block, "Next safe verification") or _field(block, "Next action")
        linked = _field(block, "Linked IS/C/E") or _field(block, "Linked evidence")
        if not next_action.strip() and not re.search(r"\b[EC]-\d+\b|\bIS-\d+\b", linked):
            out.append(m.group(1))
    return out


def _mentor_hints(run_dir: Path, fronts: dict, agents: dict, progress: dict, gates: dict) -> list[dict]:
    hints: list[dict] = []

    def add(kind: str, reason: str, action: str, severity: str = "advisory") -> None:
        hints.append({
            "kind": kind,
            "severity": severity,
            "reason": reason,
            "suggested_action": action,
            "advisory_only": True,
        })

    if progress["no_progress_cycles"] >= 2:
        add(
            "no-progress-pivot",
            f"{progress['no_progress_cycles']} consecutive cycles produced no new evidence, certainty upgrade, or coverage cell.",
            "Pivot to a materially different mechanism, role, input shape, or control before spending more budget.",
        )

    repeated = []
    for fid, block in _front_blocks_text(run_dir):
        m = re.search(r"Same barrier failures:\s*(\d+)", block, re.I)
        if m and int(m.group(1)) >= 2:
            repeated.append(f"{fid}={m.group(1)}")
    if repeated:
        add(
            "repeated-barrier",
            "Same-barrier failures are accumulating: " + ", ".join(repeated[:6]),
            "Record an explicit continue/pivot decision and avoid retrying the same bypass family without a changed precondition.",
        )

    high_open = _open_high_threat_fronts(run_dir)
    if gates["needs_saturation_attention"] and high_open:
        add(
            "low-saturation-high-threat",
            "Low saturation overlaps open high-threat front(s): " + ", ".join(high_open[:6]),
            "Prefer mechanism-depth expansion or a documented Type B deferral over broad low-value enumeration.",
        )

    if gates["needs_conflict_resolution"]:
        add(
            "unresolved-agent-conflict",
            f"{agents['unresolved_conflicts']} Agent conflict(s) remain unresolved.",
            "Resolve through verification/control before promotion or closure.",
        )

    try:
        discipline = workers.agent_discipline_issues(run_dir)
    except Exception as exc:
        discipline = []
        add(
            "agent-discipline-audit-unavailable",
            f"Agent discipline audit failed: {type(exc).__name__}.",
            "Run tools/workers.py agent-check manually before relying on Agent completion.",
        )
    agent_artifact_issues = [
        i for i in discipline
        if i.get("kind") in {"missing-artifact-pointer", "agent-missing-control"}
    ]
    if agent_artifact_issues:
        names = sorted({str(i.get("agent")) for i in agent_artifact_issues})
        add(
            "done-agent-without-artifact-control",
            "Done Agent claim material lacks artifact/control pointers: " + ", ".join(names[:6]),
            "Downgrade candidate confidence or request artifact/control before synthesis.",
        )

    deferred = _high_threat_deferred_without_evidence(run_dir)
    if deferred:
        add(
            "high-threat-deferred-without-evidence",
            "High-threat public deferred front(s) lack E-entry support: " + ", ".join(deferred[:6]),
            "Add a representative negative E-entry or reactivate the front.",
        )

    stale_h = _open_threat_hypotheses_without_action(run_dir)
    if stale_h:
        add(
            "open-threat-hypothesis-without-action",
            "Open threat hypotheses lack action/linkage: " + ", ".join(stale_h[:8]),
            "Attach a Linked IS/C/E or one safe next verification step.",
        )
    return hints


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
    completion_markers = _completion_markers(run_dir)
    gates["completion_markers"] = completion_markers
    gates["loop_complete"] = bool(completion_markers)
    phase = _phase(fronts, progress)
    actions = _next_actions(fronts, agents, progress, gates)
    mentor_hints = _mentor_hints(run_dir, fronts, agents, progress, gates)

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
        "mentor_hints": mentor_hints,
        "next_actions": actions,
    }


def render_markdown(data: dict, *, color: bool | None = None) -> str:
    progress = data["progress"]
    fronts = data["fronts"]
    agents = data["agents"]
    gates = data["gates"]
    blockers = gates.get("closure_blockers", [])
    blocker_color = "red" if blockers else "green"
    panel = _pretty_block("运行态快照", [
        status_style.field("当前阶段", _phase_display(data["phase"], color=color), "blue", enabled=color),
        status_style.field("前线状态", f"开放 {fronts['open_count']} / 延后 {fronts['deferred_count']} / 已关闭 {fronts['closed_count']}", "white", enabled=color),
        status_style.field("证据变化", f"总计 {progress['evidence_total']}；本轮新增 {len(progress['new_evidence_ids'])}；置信提升 {len(progress['certainty_upgrades'])}", "white", enabled=color),
        status_style.field("覆盖进展", f"已测 {progress['coverage_tested_cell_count']}；本轮新增 {len(progress['coverage_new_tested_cells'])}；未测 {progress['coverage_untested_cell_count']}", "white", enabled=color),
        status_style.field("无进展轮数", f"{progress['no_progress_cycles']}（{'需要轨迹复盘/换路' if progress['coda_converged'] else '继续推进'}）", "yellow" if progress["coda_converged"] else "green", enabled=color),
        status_style.field("Agent 状态", f"任务 {agents['assignment_count']}；未解决冲突 {agents['unresolved_conflicts']}", "purple" if agents["unresolved_conflicts"] else "white", enabled=color),
        status_style.field("需要并行分派", _yes_no(gates["fanout_required"]), "yellow" if gates["fanout_required"] else "green", enabled=color),
        status_style.field("Loop 已完成", _yes_no(gates.get("loop_complete")), "green" if gates.get("loop_complete") else "gray", enabled=color),
        status_style.field("接近收口复核", _yes_no(gates["completion_pause_candidate"]), "purple" if gates["completion_pause_candidate"] else "gray", enabled=color),
        status_style.field("收口阻断项", str(len(blockers)) + (f"（{', '.join(blockers[:4])}）" if blockers else ""), blocker_color, enabled=color),
    ], color="cyan", enabled=color)
    front_counts = f"{fronts['open_count']} / {fronts['deferred_count']} / {fronts['closed_count']}"
    evidence_line = (
        f"{progress['evidence_total']} total; 本轮新增: {len(progress['new_evidence_ids'])}; "
        f"置信提升: {len(progress['certainty_upgrades'])}"
    )
    coverage_line = (
        f"{progress['coverage_tested_cell_count']} tested cells; "
        f"本轮新增: {len(progress['coverage_new_tested_cells'])}; "
        f"未测适用单元: {progress['coverage_untested_cell_count']}"
    )
    no_progress_line = (
        f"{progress['no_progress_cycles']} "
        f"({'Coda converged / 需要换路' if progress['coda_converged'] else 'continue / 继续'})"
    )
    agents_line = f"{agents['assignment_count']} assignments; 未解决冲突: {agents['unresolved_conflicts']}"
    lines = [
        "# Xunji 运行态快照",
        "",
        panel,
        "",
        f"- {status_style.field('当前阶段', _phase_display(data['phase'], color=color), 'blue', enabled=color)}",
        f"- {status_style.field('开放/延后/关闭前线', front_counts, 'white', enabled=color)}",
        f"- {status_style.field('证据', evidence_line, 'white', enabled=color)}",
        f"- {status_style.field('覆盖', coverage_line, 'white', enabled=color)}",
        f"- {status_style.field('无进展轮数', no_progress_line, 'yellow' if progress['coda_converged'] else 'green', enabled=color)}",
        f"- {status_style.field('Agents', agents_line, 'purple' if agents['unresolved_conflicts'] else 'white', enabled=color)}",
        f"- {status_style.field('需要并行分派', _yes_no(gates['fanout_required']), 'yellow' if gates['fanout_required'] else 'green', enabled=color)}",
        f"- {status_style.field('Loop 已完成', _yes_no(gates.get('loop_complete')), 'green' if gates.get('loop_complete') else 'gray', enabled=color)}",
        f"- {status_style.field('收口复核候选', _yes_no(gates['completion_pause_candidate']), 'purple' if gates['completion_pause_candidate'] else 'gray', enabled=color)}",
        "",
        "## 下一步建议 (Next Actions)",
        "",
    ]
    lines.extend(f"- {_action_display(a, color=color)}" for a in data.get("next_actions", []))
    if data.get("mentor_hints"):
        lines.extend(["", "## 导师提示 (Mentor Hints)", ""])
        for item in data["mentor_hints"]:
            lines.append(
                f"- {item['kind']}: {item['reason']} 建议: {item['suggested_action']} (advisory only)"
            )
    if fronts.get("low_saturation"):
        lines.extend(["", "## 低饱和前线 (Low Saturation)", ""])
        for item in fronts["low_saturation"]:
            lines.append(
                f"- {item['front']}: ratio={item['ratio']} tried={item['tried']} untried={item['untried']}"
            )
    if data["coverage"].get("empty_columns"):
        lines.extend(["", "## 覆盖空列 (Coverage Empty Columns)", ""])
        lines.extend(f"- {c}" for c in data["coverage"]["empty_columns"])
    return "\n".join(lines) + "\n"


def write_outputs(run_dir: Path) -> dict:
    data = derive(run_dir, write=True)
    state = _resolve_run_dir(run_dir) / "state"
    _write(state / "loop_state.json", json.dumps(data, ensure_ascii=False, indent=2) + "\n")
    _write(state / "loop_state.md", render_markdown(data, color=False))
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
    old_color = os.environ.get("XUNJI_COLOR")
    os.environ["XUNJI_COLOR"] = "1"
    write_outputs(run)
    persisted_md = (run / "state" / "loop_state.md").read_text(encoding="utf-8", errors="replace")
    if old_color is None:
        os.environ.pop("XUNJI_COLOR", None)
    else:
        os.environ["XUNJI_COLOR"] = old_color
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

    blocked_run = d / "blocked_run"
    blocked_run.mkdir()
    (blocked_run / "frontier.md").write_text(
        "# Frontier\n\n## Open Fronts\n\n"
        "### F-001 Admin\n"
        "- Status: open, blocked_type_a\n"
        "- Threat role: admin-mgmt\n"
        "- Threat exposure: public-unauth\n"
        "- Barrier class: auth-layer\n\n"
        "### F-002 API\n"
        "- Status: working (blocked_type_a)\n"
        "- Barrier class: routing-layer\n",
        encoding="utf-8",
    )
    (blocked_run / "evidence.md").write_text("# Evidence Ledger\n", encoding="utf-8")
    (blocked_run / "decisions.md").write_text("# Decisions\n", encoding="utf-8")
    (blocked_run / "hypotheses.md").write_text("# Hypotheses\n", encoding="utf-8")
    write_outputs(blocked_run)
    write_outputs(blocked_run)
    blocked_state = write_outputs(blocked_run)

    hyphen_run = d / "hyphen_run"
    hyphen_run.mkdir()
    (hyphen_run / "frontier.md").write_text(
        "# Frontier\n\n## Open Fronts\n\n"
        "### F-001\n"
        "- Status: open (blocked-type-a: waiting)\n"
        "- Barrier class: auth-layer\n",
        encoding="utf-8",
    )
    (hyphen_run / "evidence.md").write_text("# Evidence Ledger\n", encoding="utf-8")
    (hyphen_run / "decisions.md").write_text("# Decisions\n", encoding="utf-8")
    (hyphen_run / "hypotheses.md").write_text("# Hypotheses\n", encoding="utf-8")
    hyphen_state = write_outputs(hyphen_run)

    unknown_run = d / "unknown_run"
    unknown_run.mkdir()
    (unknown_run / "frontier.md").write_text(
        "# Frontier\n\n## Open Fronts\n\n"
        "### F-001\n"
        "- Status: needs triage\n"
        "- Barrier class: app-layer\n",
        encoding="utf-8",
    )
    (unknown_run / "evidence.md").write_text("# Evidence Ledger\n", encoding="utf-8")
    (unknown_run / "decisions.md").write_text("# Decisions\n", encoding="utf-8")
    (unknown_run / "hypotheses.md").write_text("# Hypotheses\n", encoding="utf-8")
    unknown_state = write_outputs(unknown_run)

    conflicting_run = d / "conflicting_run"
    conflicting_run.mkdir()
    (conflicting_run / "frontier.md").write_text(
        "# Frontier\n\n## Open Fronts\n\n"
        "### F-001\n"
        "- Status: closed, deferred\n"
        "- Barrier class: app-layer\n",
        encoding="utf-8",
    )
    (conflicting_run / "evidence.md").write_text("# Evidence Ledger\n", encoding="utf-8")
    (conflicting_run / "decisions.md").write_text("# Decisions\n", encoding="utf-8")
    (conflicting_run / "hypotheses.md").write_text("# Hypotheses\n", encoding="utf-8")
    conflicting_state = write_outputs(conflicting_run)

    section_fallback_run = d / "section_fallback_run"
    section_fallback_run.mkdir()
    (section_fallback_run / "frontier.md").write_text(
        "# Frontier\n\n"
        "## Deferred Fronts\n\n"
        "```md\n"
        "### F-999 Example only\n"
        "- Status: deferred\n"
        "```\n\n"
        "### F-001\n"
        "- Barrier class: network-layer\n\n"
        "## Closed Fronts\n\n"
        "### F-002\n"
        "- Barrier class: none\n",
        encoding="utf-8",
    )
    (section_fallback_run / "evidence.md").write_text("# Evidence Ledger\n", encoding="utf-8")
    (section_fallback_run / "decisions.md").write_text("# Decisions\n", encoding="utf-8")
    (section_fallback_run / "hypotheses.md").write_text("# Hypotheses\n", encoding="utf-8")
    section_fallback_state = write_outputs(section_fallback_run)

    type_b_run = d / "type_b_run"
    type_b_run.mkdir()
    (type_b_run / "frontier.md").write_text(
        "# Frontier\n\n## Open Fronts\n\n"
        "### F-001\n"
        "- Status: blocked_type_b\n"
        "- Barrier class: explored-enough\n\n"
        "### F-002\n"
        "- Status: closed_type_b\n"
        "- Barrier class: explored-enough\n",
        encoding="utf-8",
    )
    (type_b_run / "evidence.md").write_text("# Evidence Ledger\n", encoding="utf-8")
    (type_b_run / "decisions.md").write_text("# Decisions\n", encoding="utf-8")
    (type_b_run / "hypotheses.md").write_text("# Hypotheses\n", encoding="utf-8")
    type_b_state = write_outputs(type_b_run)

    closing_run = d / "closing_run"
    closing_run.mkdir()
    (closing_run / "frontier.md").write_text(
        "# Frontier\n\n## Open Fronts\n\n"
        "### F-001\n"
        "- Status: open -> CLOSING (final)\n"
        "- Barrier class: explored-enough\n",
        encoding="utf-8",
    )
    (closing_run / "evidence.md").write_text("# Evidence Ledger\n", encoding="utf-8")
    (closing_run / "decisions.md").write_text("# Decisions\n", encoding="utf-8")
    (closing_run / "hypotheses.md").write_text("# Hypotheses\n", encoding="utf-8")
    closing_state = write_outputs(closing_run)

    setup_phase_run = d / "setup_phase_run"
    setup_phase_run.mkdir()
    (setup_phase_run / "frontier.md").write_text("# Frontier\n", encoding="utf-8")
    (setup_phase_run / "evidence.md").write_text("# Evidence Ledger\n", encoding="utf-8")
    (setup_phase_run / "decisions.md").write_text("# Decisions\n", encoding="utf-8")
    (setup_phase_run / "hypotheses.md").write_text("# Hypotheses\n", encoding="utf-8")
    setup_phase_state = write_outputs(setup_phase_run)

    reviewer_phase_run = d / "reviewer_phase_run"
    reviewer_phase_run.mkdir()
    (reviewer_phase_run / "frontier.md").write_text(
        "# Frontier\n\n## Deferred Fronts\n\n"
        "### F-001\n"
        "- Status: deferred\n"
        "- Barrier class: auth-layer\n",
        encoding="utf-8",
    )
    (reviewer_phase_run / "evidence.md").write_text("# Evidence Ledger\n", encoding="utf-8")
    (reviewer_phase_run / "decisions.md").write_text("# Decisions\n", encoding="utf-8")
    (reviewer_phase_run / "hypotheses.md").write_text("# Hypotheses\n", encoding="utf-8")
    reviewer_phase_state = write_outputs(reviewer_phase_run)

    report_phase_run = d / "report_phase_run"
    report_phase_run.mkdir()
    (report_phase_run / "frontier.md").write_text(
        "# Frontier\n\n## Closed Fronts\n\n"
        "### F-001\n"
        "- Status: closed\n"
        "- Barrier class: none\n",
        encoding="utf-8",
    )
    (report_phase_run / "evidence.md").write_text("# Evidence Ledger\n", encoding="utf-8")
    (report_phase_run / "decisions.md").write_text("# Decisions\n", encoding="utf-8")
    (report_phase_run / "hypotheses.md").write_text("# Hypotheses\n", encoding="utf-8")
    report_phase_state = write_outputs(report_phase_run)

    complete_run = d / "complete_run"
    complete_run.mkdir()
    (complete_run / "frontier.md").write_text(
        "# Frontier\n\n## Closed Fronts\n\n"
        "### F-001\n"
        "- Status: closed\n"
        "- Barrier class: none\n",
        encoding="utf-8",
    )
    (complete_run / "evidence.md").write_text("# Evidence Ledger\n", encoding="utf-8")
    (complete_run / "decisions.md").write_text("# Decisions\n\n- GHOST_COMPLETE\n", encoding="utf-8")
    (complete_run / "hypotheses.md").write_text("# Hypotheses\n", encoding="utf-8")
    complete_state = write_outputs(complete_run)

    checks = [
        ("writes loop state json", (run / "state" / "loop_state.json").exists()),
        ("writes loop state markdown", (run / "state" / "loop_state.md").exists()),
        ("open fronts render Root Orchestrator phase", first["phase"] == "Root Orchestrator"),
        ("empty run renders Setup phase", setup_phase_state["phase"] == "Setup"),
        ("deferred fronts render Reviewer phase", reviewer_phase_state["phase"] == "Reviewer"),
        ("closed fronts render Report phase", report_phase_state["phase"] == "Report"),
        ("markdown includes Chinese status panel", "Xunji 运行态快照" in render_markdown(first)
         and "[当前阶段] [Root Orchestrator｜主驾驶调度]" in render_markdown(first)),
        ("persisted markdown does not contain ANSI even when color forced", "\033[" not in persisted_md),
        ("fanout required with four diverse open fronts", first["gates"]["fanout_required"]),
        ("coverage attention is surfaced", first["gates"]["needs_coverage_attention"]),
        ("first snapshot does not count existing evidence as new", first["progress"]["new_evidence_ids"] == []),
        ("no-progress cycles increase", second["progress"]["no_progress_cycles"] == 1),
        ("coda converges after two no-progress cycles", third["progress"]["coda_converged"]),
        ("mentor hints include no-progress pivot",
         any(h.get("kind") == "no-progress-pivot" for h in third.get("mentor_hints", []))
         and "Mentor Hints" in render_markdown(third)),
        ("certainty upgrade resets no-progress", fourth["progress"]["certainty_upgrades"]
         and fourth["progress"]["no_progress_cycles"] == 0),
        ("coverage improvement is recorded", fourth["progress"]["coverage_new_tested_cells"]),
        ("coverage outputs written", (run / "state" / "coverage_matrix.json").exists()),
        ("graph checkpoint written", (run / "state" / "workflow_checkpoint.json").exists()),
        ("agent conflicts are surfaced", agent_state["agents"]["unresolved_conflicts"] == 1
         and agent_state["gates"]["needs_conflict_resolution"]),
        ("mentor hints include unresolved Agent conflict",
         any(h.get("kind") == "unresolved-agent-conflict" for h in agent_state.get("mentor_hints", []))),
        ("default derive is no-write", no_write_data["schema"] == SCHEMA
         and not (no_write / "state").exists()
         and not (no_write / "graph.json").exists()),
        ("type-a blocked statuses remain open",
         blocked_state["fronts"]["open_count"] == 2
         and set(blocked_state["fronts"]["blocked_type_a"]) == {"F-001", "F-002"}),
        ("coda convergence is not closure while type-a fronts are open",
         blocked_state["progress"]["coda_converged"]
         and not blocked_state["gates"]["completion_pause_candidate"]
         and "open_fronts_present" in blocked_state["gates"]["closure_blockers"]),
        ("hyphenated type-a spelling remains open",
         hyphen_state["fronts"]["open_count"] == 1
         and hyphen_state["fronts"]["blocked_type_a"] == ["F-001"]),
        ("unclassified statuses block closure review",
         unknown_state["fronts"]["unclassified_status"] == ["F-001"]
         and not unknown_state["gates"]["completion_pause_candidate"]
         and "unclassified_front_status" in unknown_state["gates"]["closure_blockers"]),
        ("conflicting terminal statuses block closure review",
         conflicting_state["fronts"]["unclassified_status"] == ["F-001"]
         and not conflicting_state["fronts"]["closed"]
         and not conflicting_state["fronts"]["deferred"]
         and "unclassified_front_status" in conflicting_state["gates"]["closure_blockers"]),
        ("section headings provide deferred/closed fallback status",
         section_fallback_state["fronts"]["deferred"] == ["F-001"]
         and section_fallback_state["fronts"]["closed"] == ["F-002"]
         and "F-999" not in section_fallback_state["fronts"]["deferred"]
         and not section_fallback_state["fronts"]["unclassified_status"]),
        ("blocked type-b is not open or unclassified",
         type_b_state["fronts"]["blocked_type_b"] == ["F-001"]
         and set(type_b_state["fronts"]["closed"]) == {"F-001", "F-002"}
         and type_b_state["fronts"]["open_count"] == 0
         and not type_b_state["fronts"]["unclassified_status"]
         and type_b_state["gates"]["completion_pause_candidate"]
         and type_b_state["gates"]["near_closure"]),
        ("mixed open-closing final status is terminal, not open",
         closing_state["fronts"]["open_count"] == 0
         and closing_state["fronts"]["closed"] == ["F-001"]
         and not closing_state["fronts"]["unclassified_status"]
         and closing_state["gates"]["completion_pause_candidate"]),
        ("completion marker sets loop_complete and stops next-loop scheduling",
         complete_state["gates"]["loop_complete"]
         and complete_state["gates"]["completion_markers"] == ["GHOST_COMPLETE"]
         and complete_state["next_actions"] == [
             "Run is marked complete; do not schedule another /loop iteration."]),
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
        print(render_markdown(data, color=status_style.color_enabled()), end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
