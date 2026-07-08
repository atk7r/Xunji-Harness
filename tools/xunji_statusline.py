#!/usr/bin/env python3
"""Claude Code statusline for Xunji.

This script is display-only during normal statusline use. It reads the active run
pointer plus derived state files and prints one concise, operator-facing line.
It never refreshes loop state, mutates run evidence, or drives an engagement.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
except Exception:
    pass

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

import status_style  # noqa: E402

ACTIVE_RUN = ROOT / ".claude" / "xunji_active_run"
PHASE_LABELS = {
    "Setup": "Setup｜准备",
    "Root Orchestrator": "Root｜调度",
    "Hunter": "Hunter｜验证",
    "Reviewer": "Reviewer｜复审",
    "Report": "Report｜报告",
    "Idle": "Idle｜空闲",
}
PHASE_COLOR = {
    "Setup": "blue",
    "Root Orchestrator": "cyan",
    "Hunter": "yellow",
    "Reviewer": "purple",
    "Report": "green",
    "Idle": "gray",
}
ACTION_LABELS = {
    "resolve_agent_or_review_conflicts_before_promotion_or_closure": "处理证据/子任务冲突",
    "assign_at_least_two_disjoint_agent_lanes_or_record_a_budget_reason": "分派子任务",
    "record_trajectory_review_then_pivot_continue_or_assign_review_surface_agent": "复盘换路",
    "update_frontier_or_evidence_for_coverage_gaps": "补齐覆盖记录",
    "expand_or_justify_low_saturation_fronts": "扩展验证入口",
    "fix_unclassified_front_statuses_before_closure_review": "修正入口状态",
    "add_negative_evidence_or_reactivate_high_threat_deferred_front": "补负向证据或重开高威胁入口",
    "link_or_action_open_threat_hypotheses": "处理开放威胁假设",
    "continue_driver_on_actionable_open_front": "继续验证可行动入口",
    "run_closure_gates_replay_peer_review_and_retrospective": "跑收口检查",
    "create_or_reopen_a_front_before_claiming_closure": "创建或重开验证入口",
}


def _load_json(path: Path, default):
    try:
        data = json.loads(path.read_text(encoding="utf-8", errors="replace"))
        return data if isinstance(data, type(default)) else default
    except Exception:
        return default


def _read_input() -> dict:
    try:
        raw = sys.stdin.read()
    except Exception:
        raw = ""
    if not raw.strip():
        return {}
    try:
        data = json.loads(raw)
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def _workspace_dir(payload: dict) -> Path:
    workspace = payload.get("workspace") if isinstance(payload.get("workspace"), dict) else {}
    raw = (
        workspace.get("current_dir")
        or workspace.get("currentDir")
        or payload.get("cwd")
        or os.environ.get("PWD")
        or os.getcwd()
    )
    return Path(str(raw)).expanduser().resolve()


def _is_xunji_context(current_dir: Path) -> bool:
    try:
        current_dir.relative_to(ROOT)
    except ValueError:
        return False
    return (
        (ROOT / "CLAUDE.md").exists()
        and (ROOT / "tools" / "loop_state.py").exists()
        and (ROOT / ".claude" / "skills").is_dir()
    )


def _looks_like_run_dir(run_dir: Path) -> bool:
    markers = ("target.md", "frontier.md", "evidence.md", "decisions.md", "review.md")
    return run_dir.is_dir() and any((run_dir / marker).exists() for marker in markers)


def _run_ref(run_dir: Path) -> str:
    try:
        return str(run_dir.resolve().relative_to(ROOT))
    except ValueError:
        return str(run_dir.resolve())


def _resolve_run(raw: str) -> Path | None:
    value = raw.strip()
    if not value:
        return None
    path = Path(value).expanduser()
    run_dir = path if path.is_absolute() else ROOT / path
    run_dir = run_dir.resolve()
    try:
        run_dir.relative_to(ROOT)
    except ValueError:
        return None
    if not _looks_like_run_dir(run_dir):
        return None
    return run_dir


def set_active_run(raw: str) -> bool:
    run_dir = _resolve_run(raw)
    if run_dir is None:
        return False
    ACTIVE_RUN.parent.mkdir(parents=True, exist_ok=True)
    tmp_name = ""
    with tempfile.NamedTemporaryFile(
        "w",
        delete=False,
        dir=ACTIVE_RUN.parent,
        prefix=ACTIVE_RUN.name + ".",
        suffix=".tmp",
        encoding="utf-8",
    ) as f:
        tmp_name = f.name
        f.write(_run_ref(run_dir) + "\n")
    Path(tmp_name).replace(ACTIVE_RUN)
    return True


def clear_active_run() -> None:
    try:
        ACTIVE_RUN.unlink()
    except FileNotFoundError:
        pass


def active_run() -> Path | None:
    try:
        raw = ACTIVE_RUN.read_text(encoding="utf-8", errors="replace")
    except Exception:
        return None
    return _resolve_run(raw)


def _journal_summary(run_dir: Path) -> dict:
    path = run_dir / "state" / "loop_journal.jsonl"
    if not path.exists():
        return {"open_phase": "", "interrupted": False, "last_event": None, "last_cycle_events": []}
    events: list[dict] = []
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines()[-500:]:
        if not line.strip():
            continue
        try:
            item = json.loads(line)
            if isinstance(item, dict):
                events.append(item)
        except Exception:
            continue
    last_cycle = max([int(e.get("cycle", 0) or 0) for e in events], default=0)
    current = [e for e in events if int(e.get("cycle", 0) or 0) == last_cycle]
    open_phase = ""
    for rec in current:
        event = str(rec.get("event") or "")
        phase = str((rec.get("data") or {}).get("phase") or "").strip()
        if event == "phase_start":
            open_phase = phase
        elif event == "phase_end" and phase == open_phase:
            open_phase = ""
    return {
        "open_phase": open_phase,
        "interrupted": any(str(e.get("event") or "") == "interrupt" for e in current),
        "last_event": events[-1] if events else None,
        "last_cycle_events": [str(e.get("event") or "") for e in current],
    }


def _agent_summary(run_dir: Path) -> str:
    assignments = _load_json(run_dir / "state" / "assignments.json", {}).get("assignments", [])
    if not isinstance(assignments, list) or not assignments:
        return "无子任务"
    statuses = [str(a.get("status") or "").strip().lower() for a in assignments if isinstance(a, dict)]
    conflicts = _load_json(run_dir / "state" / "conflicts.json", {}).get("conflicts", [])
    unresolved = [
        c for c in conflicts
        if isinstance(c, dict) and str(c.get("status") or "").strip().lower() == "unresolved"
    ] if isinstance(conflicts, list) else []
    if unresolved:
        return f"子任务 {len(unresolved)} 个冲突"
    active = [s for s in statuses if s.startswith(("assign", "work")) or s in {"?", ""}]
    done = [s for s in statuses if s.startswith(("done", "complete", "completed"))]
    if active:
        return f"子任务 {len(active)} 个进行中"
    if done:
        return f"子任务 {len(done)} 个完成待合并"
    return f"子任务 {len(statuses)} 个已记录"


def _front_summary(loop_data: dict) -> str:
    fronts = loop_data.get("fronts") if isinstance(loop_data.get("fronts"), dict) else {}
    open_count = int(fronts.get("open_count", 0) or 0)
    return f"待验证入口 {open_count} 个"


def _phase(loop_data: dict, journal: dict) -> str:
    open_phase = str(journal.get("open_phase") or "").strip()
    if open_phase:
        return open_phase
    phase = str(loop_data.get("phase") or "").strip()
    return phase or "Idle"


def _phase_tag(phase: str, *, color: bool) -> str:
    label = PHASE_LABELS.get(phase, phase or PHASE_LABELS["Idle"])
    return status_style.tag(label, PHASE_COLOR.get(phase, "white"), enabled=color)


def _blocker_summary(controller: dict) -> tuple[str, int]:
    blockers = controller.get("stop_blockers")
    count = len(blockers) if isinstance(blockers, list) else 0
    return ("无阻断" if count == 0 else f"阻断 {count} 个", count)


def _last_plan_note(journal: dict) -> str:
    last = journal.get("last_event") if isinstance(journal.get("last_event"), dict) else {}
    note = str(last.get("note") or "").strip()
    event = str(last.get("event") or "").strip()
    if event not in {"plan", "action", "write_result", "phase_start", "phase_end"}:
        return ""
    target = ""
    reason = ""
    mt = re.search(r"目标=([^;；]+)", note)
    mr = re.search(r"原因=([^;；]+)", note)
    if mt:
        target = mt.group(1).strip()
    if mr:
        reason = mr.group(1).strip()
    if target and reason:
        return f"{target} {reason}"
    if target:
        return target
    cleaned = re.sub(r"^(即将执行|结果已写入运行文件|已选择目标=)", "", note).strip()
    return cleaned


def _next_action(controller: dict, journal: dict) -> str:
    note = _last_plan_note(journal)
    if note:
        return note
    action = str(controller.get("next_required_action") or "").strip()
    return ACTION_LABELS.get(action, action or "等待下一步")


def _clip(text: str, limit: int = 42) -> str:
    text = " ".join(str(text).split())
    return text if len(text) <= limit else text[: limit - 1] + "…"


def render_statusline(payload: dict | None = None, *, color: bool | None = None) -> str:
    payload = payload or {}
    current_dir = _workspace_dir(payload)
    if not _is_xunji_context(current_dir):
        return ""
    run_dir = active_run()
    if run_dir is None:
        return f"{status_style.tag('Xunji-status', 'cyan', enabled=color)} {_phase_tag('Idle', color=bool(color))} 未选择运行目录"

    loop_data = _load_json(run_dir / "state" / "loop_state.json", {})
    controller = _load_json(run_dir / "state" / "controller.shadow.json", {})
    journal = _journal_summary(run_dir)
    phase = _phase(loop_data, journal)
    blocker_text, blocker_count = _blocker_summary(controller)
    interrupt = " | 中断待续" if journal.get("interrupted") else ""
    line = " | ".join([
        f"{status_style.tag('Xunji-status', 'cyan', enabled=color)} {_phase_tag(phase, color=bool(color))} {run_dir.name}{interrupt}",
        _front_summary(loop_data),
        _agent_summary(run_dir),
        status_style.paint(blocker_text, "red" if blocker_count else "green", enabled=color),
        "下一步 " + _clip(_next_action(controller, journal)),
    ])
    return line


def _selftest() -> int:
    root_current = {"workspace": {"current_dir": str(ROOT)}}
    tmp_root = ROOT / "tmp"
    tmp_root.mkdir(exist_ok=True)
    temp = Path(tempfile.mkdtemp(dir=tmp_root))
    run = temp / "run"
    run.mkdir()
    (run / "target.md").write_text("# Target\n", encoding="utf-8")
    (run / "frontier.md").write_text("# Frontier\n", encoding="utf-8")
    (run / "state").mkdir()
    (run / "state" / "loop_state.json").write_text(json.dumps({
        "phase": "Root Orchestrator",
        "fronts": {"open_count": 6},
    }), encoding="utf-8")
    (run / "state" / "controller.shadow.json").write_text(json.dumps({
        "next_required_action": "continue_driver_on_actionable_open_front",
        "stop_blockers": [],
    }), encoding="utf-8")
    (run / "state" / "assignments.json").write_text(json.dumps({
        "assignments": [
            {"agent": "A-001", "status": "working"},
            {"agent": "A-002", "status": "assigned"},
        ],
    }), encoding="utf-8")
    (run / "state" / "loop_journal.jsonl").write_text(
        json.dumps({"cycle": 1, "event": "phase_start", "data": {"phase": "Hunter"}, "note": ""}, ensure_ascii=False) + "\n"
        + json.dumps({"cycle": 1, "event": "plan", "data": {}, "note": "目标=F-004; 原因=接口枚举"}, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    old_pointer = ACTIVE_RUN.read_text(encoding="utf-8", errors="replace") if ACTIVE_RUN.exists() else None
    try:
        assert set_active_run(str(run))
        watched = [
            ACTIVE_RUN,
            run / "state" / "loop_state.json",
            run / "state" / "controller.shadow.json",
            run / "state" / "assignments.json",
            run / "state" / "loop_journal.jsonl",
        ]
        before_render = {p: p.stat().st_mtime_ns for p in watched}
        plain = render_statusline(root_current, color=False)
        colored = render_statusline(root_current, color=True)
        outside_dir = Path(tempfile.mkdtemp())
        env = dict(os.environ)
        env["XUNJI_COLOR"] = "1"
        env.pop("NO_COLOR", None)
        env.pop("XUNJI_NO_COLOR", None)
        proc = subprocess.run(
            [sys.executable, str(Path(__file__).resolve())],
            input=json.dumps(root_current),
            text=True,
            capture_output=True,
            env=env,
            timeout=10,
        )
        env_colored = proc.stdout
        unknown_phase = _phase_tag("Unexpected Phase", color=True)
        invalid_rejected = set_active_run(str(outside_dir)) is False
        outside = render_statusline({"workspace": {"current_dir": str(outside_dir)}}, color=False)
        after_render = {p: p.stat().st_mtime_ns for p in watched}
    finally:
        if old_pointer is None:
            clear_active_run()
        else:
            ACTIVE_RUN.write_text(old_pointer, encoding="utf-8")

    checks = [
        ("plain statusline is human-readable", "[Xunji-status] [Hunter｜验证]" in plain),
        ("open fronts use pentest wording", "待验证入口 6 个" in plain and "F 6/1/3" not in plain),
        ("subagents are aggregated", "子任务 2 个进行中" in plain),
        ("next action uses plan note", "下一步 F-004 接口枚举" in plain),
        ("colored statusline has ansi", "\033[" in colored and "[Hunter｜验证]" in colored),
        ("XUNJI_COLOR command path has ansi", proc.returncode == 0 and "\033[" in env_colored and "[Hunter｜验证]" in env_colored),
        ("unknown phase fallback is styled", "\033[" in unknown_phase and "[Unexpected Phase]" in unknown_phase),
        ("normal render is read-only", before_render == after_render),
        ("invalid outside run pointer is rejected", invalid_rejected),
        ("outside Xunji prints nothing", outside == ""),
    ]
    bad = [name for name, ok in checks if not ok]
    for name, ok in checks:
        print(("ok   " if ok else "FAIL ") + name)
    print("xunji_statusline selftest " + ("passed" if not bad else f"FAILED ({len(bad)})"))
    return 0 if not bad else 1


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="render Xunji Claude Code statusline")
    ap.add_argument("--set-active", metavar="RUN_DIR", help="set the active Xunji run pointer")
    ap.add_argument("--clear-active", action="store_true", help="clear the active Xunji run pointer")
    ap.add_argument("--selftest", action="store_true")
    args = ap.parse_args(argv)

    if args.selftest:
        return _selftest()
    if args.clear_active:
        clear_active_run()
        return 0
    if args.set_active:
        if not set_active_run(args.set_active):
            print(f"[xunji_statusline] invalid run dir: {args.set_active}", file=sys.stderr)
            return 1
        return 0

    line = render_statusline(_read_input(), color=status_style.color_enabled())
    if line:
        print(line)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
