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
import os
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
import loop_journal  # noqa: E402
import progress_ledger  # noqa: E402
import status_style  # noqa: E402

SCHEMA = "xunji.run_controller.shadow.v1"
STATE_CN = {
    "DRIVER_ACTIVE": "主驾驶继续推进",
    "NEEDS_REVIEW": "需要先复审/解冲突",
    "NEEDS_AGENT_FANOUT": "需要并行分派 Agent",
    "NEEDS_PIVOT": "需要轨迹复盘并换路",
    "CLOSURE_CANDIDATE": "仅是收口复核候选",
    "LOOP_COMPLETE": "运行已完成",
}
ACTION_CN = {
    "resolve_agent_or_review_conflicts_before_promotion_or_closure": "先解决 Agent/复审冲突，再考虑提升或收口",
    "assign_at_least_two_disjoint_agent_lanes_or_record_a_budget_reason": "分派至少两条不重叠 Agent 线路，或记录预算原因",
    "record_trajectory_review_then_pivot_continue_or_assign_review_surface_agent": "记录轨迹复盘，然后换机制/继续理由/分派复审或面扩 Agent",
    "update_frontier_or_evidence_for_coverage_gaps": "补 frontier/evidence 中的覆盖缺口说明",
    "expand_or_justify_low_saturation_fronts": "扩展低饱和前线，或写明为什么不继续",
    "fix_unclassified_front_statuses_before_closure_review": "修正未分类前线状态后再收口复核",
    "add_negative_evidence_or_reactivate_high_threat_deferred_front": "给高威胁延后前线补负向证据，或重新激活",
    "link_or_action_open_threat_hypotheses": "给开放威胁假设补 Linked IS/C/E 或下一步动作",
    "continue_driver_on_actionable_open_front": "继续推进可行动开放前线",
    "run_closure_gates_peer_review_and_retrospective": "跑离线收口硬门、独立复审和复盘；live replay 仅按当前显式授权路由",
    "create_or_reopen_a_front_before_claiming_closure": "先创建或重开前线，不能直接宣称结束",
    "do_not_schedule_another_loop_iteration": "不要再排下一轮 /loop",
}
REQUIRE_CN = {
    "zero open fronts or evidence-backed deferred/closed rationale": "开放前线归零，或每个延后/关闭都有证据支撑的理由",
    "offline check_run completed": "完成 lifecycle owner 所列的离线 run 结构检查",
    "independent review resolved": "独立复审已完成且问题已处理",
    "retrospective.md completed": "retrospective.md 已真实填写",
    "GHOST_COMPLETE only after hard gates pass": "只有硬门全部通过后才允许写 GHOST_COMPLETE",
}


def _resolve_run_dir(path: str | Path) -> Path:
    p = Path(path)
    return (p if p.is_absolute() else ROOT / p).resolve()


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def _pretty_block(title: str, rows: list[str], *, color: str = "purple", enabled: bool | None = None) -> str:
    return status_style.box(title, rows, color=color, enabled=enabled)


def _state_display(state: str) -> str:
    return f"{STATE_CN.get(state, state)} ({state})"


def _action_display(action: str) -> str:
    return f"{ACTION_CN.get(action, action)} ({action})"


def _stop_reason_display(reason: str) -> str:
    if reason == "completion marker present; do not schedule another /loop iteration":
        return "已写完成标记；不要再排下一轮 /loop"
    if reason == "shadow controller never grants stop; only hard closure gates plus Root adjudication can do that":
        return "影子控制面永不批准停止；只有硬收口闸门通过并由 Root 判定后才可停止"
    return reason


def _require_display(requirement: str) -> str:
    cn = REQUIRE_CN.get(requirement)
    return f"{cn} ({requirement})" if cn else requirement


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
    if gates.get("loop_complete"):
        return "LOOP_COMPLETE"
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
    if state == "LOOP_COMPLETE":
        return "do_not_schedule_another_loop_iteration"
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
        return "run_closure_gates_peer_review_and_retrospective"
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
    loop_complete = state == "LOOP_COMPLETE"
    return {
        "schema": SCHEMA,
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "canonical": "Markdown run files remain source of truth; this controller is advisory/shadow only.",
        "run_dir": str(run_dir),
        "mode": "shadow",
        "advisory_only": True,
        "state": state,
        "can_stop": loop_complete,
        "can_stop_reason": (
            "completion marker present; do not schedule another /loop iteration"
            if loop_complete
            else "shadow controller never grants stop; only hard closure gates plus Root adjudication can do that"
        ),
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
            "loop_complete": bool(loop_data.get("gates", {}).get("loop_complete")),
            "completion_markers": loop_data.get("gates", {}).get("completion_markers", []),
        },
        "stop_requires": [
            "zero open fronts or evidence-backed deferred/closed rationale",
            "offline check_run completed",
            "independent review resolved",
            "retrospective.md completed",
            "GHOST_COMPLETE only after hard gates pass",
        ],
    }


def render_markdown(data: dict, *, color: bool | None = None) -> str:
    blockers = data.get("stop_blockers", [])
    panel = _pretty_block("控制面建议", [
        status_style.field("当前状态", _state_display(data["state"]), "yellow", enabled=color),
        status_style.field("可以停止", "是" if data["can_stop"] else "否", "green" if data["can_stop"] else "red", enabled=color),
        status_style.field("停止原因", _stop_reason_display(data["can_stop_reason"]), "red", enabled=color),
        status_style.field("下一步必须动作", _action_display(data["next_required_action"]), "green", enabled=color),
        status_style.field("停止阻断项", str(len(blockers)) + (f"（{', '.join(blockers[:4])}）" if blockers else ""), "red" if blockers else "green", enabled=color),
        status_style.field("性质", "影子控制面，只提醒，不替 Root 选洞、不提升证据、不批准收口", "gray", enabled=color),
    ], color="purple", enabled=color)
    lines = [
        "# Xunji 控制面建议",
        "",
        panel,
        "",
        f"- {status_style.field('状态', _state_display(data['state']), 'yellow', enabled=color)}",
        f"- {status_style.field('可以停止', '是' if data['can_stop'] else '否', 'green' if data['can_stop'] else 'red', enabled=color)}",
        f"- {status_style.field('停止原因', _stop_reason_display(data['can_stop_reason']), 'red', enabled=color)}",
        f"- {status_style.field('下一步必须动作', _action_display(data['next_required_action']), 'green', enabled=color)}",
    ]
    if data.get("stop_blockers"):
        lines.extend(["", "## 停止阻断项 (Stop Blockers)", ""])
        lines.extend(f"- {b}" for b in data["stop_blockers"])
    lines.extend(["", "## 停止仍需满足 (Stop Requires)", ""])
    lines.extend(f"- {_require_display(r)}" for r in data["stop_requires"])
    return "\n".join(lines) + "\n"


def write_shadow(run_dir: Path) -> dict:
    run_dir = _resolve_run_dir(run_dir)
    data = derive(run_dir)
    _write(run_dir / "state" / "controller.shadow.json", json.dumps(data, ensure_ascii=False, indent=2) + "\n")
    _write(run_dir / "state" / "controller_diff.md", render_markdown(data, color=False))
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
    loop_journal.append_event(run, "cycle_start", note="selftest cycle one")
    loop_journal.append_event(run, "cycle_end", note="selftest no-progress end one")
    loop_state.write_outputs(run)
    loop_journal.append_event(run, "cycle_start", note="selftest cycle two")
    loop_journal.append_event(run, "cycle_end", note="selftest no-progress end two")
    loop_data = loop_state.write_outputs(run)
    ledger = progress_ledger.derive(run, loop_data=loop_data)
    controller = derive(run, loop_data=loop_data, ledger_data=ledger)
    shadow = write_shadow(run)
    old_color = os.environ.get("XUNJI_COLOR")
    os.environ["XUNJI_COLOR"] = "1"
    write_shadow(run)
    persisted_diff = (run / "state" / "controller_diff.md").read_text(encoding="utf-8", errors="replace")
    if old_color is None:
        os.environ.pop("XUNJI_COLOR", None)
    else:
        os.environ["XUNJI_COLOR"] = old_color

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
    (closed / "decisions.md").write_text("# Decisions\n\n- GHOST_COMPLETE\n", encoding="utf-8")
    complete_loop = loop_state.write_outputs(closed)
    complete_ctl = derive(closed, loop_data=complete_loop, ledger_data=progress_ledger.derive(closed, loop_data=complete_loop))

    checks = [
        ("type-a open coda becomes pivot not stop",
         controller["state"] == "NEEDS_PIVOT"
         and not controller["can_stop"]
         and "open_fronts_present" in controller["stop_blockers"]),
        ("shadow files written", (run / "state" / "controller.shadow.json").exists()
         and (run / "state" / "controller_diff.md").exists()
         and shadow["schema"] == SCHEMA),
        ("persisted controller markdown does not contain ANSI when color forced",
         "\033[" not in persisted_diff),
        ("shadow controller is explicitly advisory",
         controller["advisory_only"] is True
         and controller["can_stop"] is False
         and "never grants stop" in controller["can_stop_reason"]),
        ("closed run is only closure candidate, not stop",
         closed_ctl["state"] == "CLOSURE_CANDIDATE"
         and closed_ctl["signals"]["closure_review_candidate"]
         and not closed_ctl["can_stop"]
         and all("replay" not in item.lower() for item in closed_ctl["stop_requires"])),
        ("completion marker allows loop stop without treating candidate as enough",
         complete_ctl["state"] == "LOOP_COMPLETE"
         and complete_ctl["can_stop"]
         and complete_ctl["signals"]["completion_markers"] == ["GHOST_COMPLETE"]
         and complete_ctl["next_required_action"] == "do_not_schedule_another_loop_iteration"),
        ("completion marker render tells operator not to reschedule",
         "不要再排下一轮 /loop" in render_markdown(complete_ctl)),
        ("markdown render contains Chinese stop blockers", "Xunji 控制面建议" in render_markdown(controller)
         and "Stop Blockers" in render_markdown(controller)),
        ("generic controller output never prescribes live replay or bare python",
         "--replay-verify" not in render_markdown(closed_ctl)
         and "python tools/" not in render_markdown(closed_ctl)),
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
        print(render_markdown(data, color=status_style.color_enabled()), end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
