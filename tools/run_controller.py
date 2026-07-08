#!/usr/bin/env python3
"""Shadow controller for Xunji run lifecycle decisions.

This is intentionally advisory. It consumes derived state (`loop_state` and
`progress_ledger`) and writes a shadow recommendation when asked. It does not
edit canonical Markdown, pick the next exploit front, promote evidence, or close
a run.
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

import loop_state  # noqa: E402
import progress_ledger  # noqa: E402

SCHEMA = "xunji.run_controller.shadow.v1"


def _resolve_run_dir(path: str | Path) -> Path:
    p = Path(path)
    return (p if p.is_absolute() else ROOT / p).resolve()


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _mentor_stop_blockers(loop_data: dict) -> list[str]:
    blocking_kinds = {
        "high-threat-deferred-without-evidence",
        "open-threat-hypothesis-without-action",
        "done-agent-without-artifact-control",
        "unresolved-agent-conflict",
    }
    out = []
    for item in loop_data.get("mentor_hints", []):
        if item.get("kind") in blocking_kinds:
            out.append(str(item.get("kind")))
    return sorted(set(out))


def _state_name(loop_data: dict, ledger: dict, blockers: list[str]) -> str:
    gates = loop_data.get("gates", {})
    progress = loop_data.get("progress", {})
    fronts = loop_data.get("fronts", {})
    cycle = ledger.get("cycle", {})
    if gates.get("needs_conflict_resolution") or "unresolved-agent-conflict" in blockers:
        return "NEEDS_REVIEW"
    if gates.get("fanout_required"):
        return "NEEDS_AGENT_FANOUT"
    if progress.get("coda_converged") and fronts.get("open_count", 0):
        return "NEEDS_PIVOT"
    if progress.get("coda_converged") and not cycle.get("material_progress"):
        return "NEEDS_PIVOT"
    if blockers:
        return "DRIVER_ACTIVE"
    if gates.get("completion_pause_candidate"):
        return "CLOSURE_CANDIDATE"
    return "DRIVER_ACTIVE"


def _next_required_action(state: str, loop_data: dict, blockers: list[str]) -> str:
    gates = loop_data.get("gates", {})
    fronts = loop_data.get("fronts", {})
    progress = loop_data.get("progress", {})
    if state == "NEEDS_REVIEW":
        return "resolve_agent_or_review_conflicts_before_promotion_or_closure"
    if state == "NEEDS_AGENT_FANOUT":
        return "assign_at_least_two_disjoint_agent_lanes_or_record_a_budget_reason"
    if state == "NEEDS_PIVOT":
        return "record_trajectory_review_then_pivot_continue_or_assign_review_surface_agent"
    if gates.get("needs_coverage_attention"):
        return "update_frontier_or_evidence_for_coverage_gaps"
    if gates.get("needs_saturation_attention"):
        return "expand_or_justify_low_saturation_fronts"
    if "unclassified_front_status" in blockers:
        return "fix_unclassified_front_statuses_before_closure_review"
    if "high-threat-deferred-without-evidence" in blockers:
        return "add_negative_evidence_or_reactivate_high_threat_deferred_front"
    if "open-threat-hypothesis-without-action" in blockers:
        return "link_or_action_open_threat_hypotheses"
    if fronts.get("open_count", 0):
        return "continue_driver_on_actionable_open_front"
    if progress.get("confirmed_evidence") or state == "CLOSURE_CANDIDATE":
        return "run_closure_gates_replay_peer_review_and_retrospective"
    return "create_or_reopen_a_front_before_claiming_closure"


def derive(run_dir: Path, *, loop_data: dict | None = None, ledger_data: dict | None = None) -> dict:
    run_dir = _resolve_run_dir(run_dir)
    if not run_dir.exists():
        raise FileNotFoundError(f"run directory does not exist: {run_dir}")
    loop_data = loop_data if loop_data is not None else loop_state.derive(run_dir, write=False)
    ledger_data = ledger_data if ledger_data is not None else progress_ledger.derive(run_dir, loop_data=loop_data)
    gate_blockers = list(loop_data.get("gates", {}).get("closure_blockers", []))
    mentor_blockers = _mentor_stop_blockers(loop_data)
    blockers = sorted(set(gate_blockers + mentor_blockers))
    state = _state_name(loop_data, ledger_data, blockers)
    next_action = _next_required_action(state, loop_data, blockers)
    return {
        "schema": SCHEMA,
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "canonical": "Markdown run files remain source of truth; this controller is advisory/shadow only.",
        "run_dir": str(run_dir),
        "mode": "shadow",
        "advisory_only": True,
        "state": state,
        "can_stop": False,
        "can_stop_reason": "shadow controller never grants stop; only hard closure gates plus Root adjudication can do that",
        "stop_blockers": blockers,
        "next_required_action": next_action,
        "signals": {
            "open_fronts": loop_data.get("fronts", {}).get("open", []),
            "blocked_type_a": loop_data.get("fronts", {}).get("blocked_type_a", []),
            "coda_converged": bool(loop_data.get("progress", {}).get("coda_converged")),
            "material_progress": bool(ledger_data.get("cycle", {}).get("material_progress")),
            "artifact_backed_progress": bool(ledger_data.get("cycle", {}).get("artifact_backed_progress")),
            "fanout_required": bool(loop_data.get("gates", {}).get("fanout_required")),
            "closure_review_candidate": bool(loop_data.get("gates", {}).get("completion_pause_candidate")),
        },
        "stop_requires": [
            "zero open fronts or evidence-backed deferred/closed rationale",
            "python tools/check_run.py <run>",
            "python tools/check_run.py <run> --replay-verify",
            "independent review resolved",
            "retrospective.md completed",
            "GHOST_COMPLETE only after hard gates pass",
        ],
    }


def render_markdown(data: dict) -> str:
    lines = [
        "# Run Controller Shadow",
        "",
        f"- State: {data['state']}",
        f"- Can stop: {'yes' if data['can_stop'] else 'no'}",
        f"- Can stop reason: {data['can_stop_reason']}",
        f"- Next required action: {data['next_required_action']}",
    ]
    if data.get("stop_blockers"):
        lines.extend(["", "## Stop Blockers", ""])
        lines.extend(f"- {b}" for b in data["stop_blockers"])
    lines.extend(["", "## Stop Requires", ""])
    lines.extend(f"- {r}" for r in data["stop_requires"])
    return "\n".join(lines) + "\n"


def write_shadow(run_dir: Path) -> dict:
    run_dir = _resolve_run_dir(run_dir)
    data = derive(run_dir)
    _write(run_dir / "state" / "controller.shadow.json", json.dumps(data, ensure_ascii=False, indent=2) + "\n")
    _write(run_dir / "state" / "controller_diff.md", render_markdown(data))
    return data


def _selftest() -> int:
    d = Path(tempfile.mkdtemp())
    run = d / "run"
    run.mkdir()
    (run / "frontier.md").write_text(
        "# Frontier\n\n## Open Fronts\n\n"
        "### F-001 Admin\n"
        "- Status: open, blocked_type_a\n"
        "- Barrier class: auth-layer\n"
        "- Vectors tried: enum\n"
        "- Untried classes: default-creds\n",
        encoding="utf-8",
    )
    (run / "evidence.md").write_text("# Evidence Ledger\n", encoding="utf-8")
    (run / "decisions.md").write_text("# Decisions\n", encoding="utf-8")
    (run / "hypotheses.md").write_text("# Hypotheses\n", encoding="utf-8")
    loop_state.write_outputs(run)
    loop_state.write_outputs(run)
    loop_data = loop_state.write_outputs(run)
    ledger = progress_ledger.derive(run, loop_data=loop_data)
    controller = derive(run, loop_data=loop_data, ledger_data=ledger)
    shadow = write_shadow(run)

    closed = d / "closed"
    closed.mkdir()
    (closed / "frontier.md").write_text(
        "# Frontier\n\n## Closed Fronts\n\n"
        "### F-001\n"
        "- Status: closed\n"
        "- Barrier class: none\n",
        encoding="utf-8",
    )
    (closed / "evidence").mkdir()
    (closed / "evidence" / "ok.html").write_text("ok", encoding="utf-8")
    (closed / "evidence.md").write_text(
        "# Evidence Ledger\n\n"
        "## E-001\n"
        "- Maturity: finding\n"
        "- Control: baseline\n"
        "- Artifacts: evidence/ok.html\n"
        "- Certainty: 0.8\n"
        "- Supports: F-001\n",
        encoding="utf-8",
    )
    (closed / "decisions.md").write_text("# Decisions\n", encoding="utf-8")
    (closed / "hypotheses.md").write_text("# Hypotheses\n", encoding="utf-8")
    closed_loop = loop_state.write_outputs(closed)
    closed_ctl = derive(closed, loop_data=closed_loop, ledger_data=progress_ledger.derive(closed, loop_data=closed_loop))

    checks = [
        ("type-a open coda becomes pivot not stop",
         controller["state"] == "NEEDS_PIVOT"
         and not controller["can_stop"]
         and "open_fronts_present" in controller["stop_blockers"]),
        ("shadow files written", (run / "state" / "controller.shadow.json").exists()
         and (run / "state" / "controller_diff.md").exists()
         and shadow["schema"] == SCHEMA),
        ("shadow controller is explicitly advisory",
         controller["advisory_only"] is True
         and controller["can_stop"] is False
         and "never grants stop" in controller["can_stop_reason"]),
        ("closed run is only closure candidate, not stop",
         closed_ctl["state"] == "CLOSURE_CANDIDATE"
         and closed_ctl["signals"]["closure_review_candidate"]
         and not closed_ctl["can_stop"]),
        ("markdown render contains stop blockers", "Stop Blockers" in render_markdown(controller)),
    ]
    bad = [name for name, ok in checks if not ok]
    for name, ok in checks:
        print(("ok   " if ok else "FAIL ") + name)
    print("run_controller selftest " + ("passed" if not bad else f"FAILED ({len(bad)})"))
    return 0 if not bad else 1


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    ap = argparse.ArgumentParser(description="derive an advisory shadow controller decision for one Xunji run")
    ap.add_argument("run_dir", nargs="?", type=Path)
    ap.add_argument("--shadow", action="store_true", help="write state/controller.shadow.json and controller_diff.md")
    ap.add_argument("--json", action="store_true", help="print JSON instead of Markdown")
    ap.add_argument("--selftest", action="store_true")
    args = ap.parse_args(argv)

    if args.selftest:
        return _selftest()
    if not args.run_dir:
        ap.error("run_dir is required")
    try:
        data = write_shadow(args.run_dir) if args.shadow else derive(args.run_dir)
    except FileNotFoundError as e:
        print(f"[run_controller] {e}", file=sys.stderr)
        return 1
    if args.json:
        print(json.dumps(data, ensure_ascii=False, indent=2))
    else:
        print(render_markdown(data), end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
