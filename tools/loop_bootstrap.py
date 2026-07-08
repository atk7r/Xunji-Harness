#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""loop_bootstrap.py —— 准备 Xunji loop 运行状态。

用法:
  python3 tools/loop_bootstrap.py <slug> <recon.json>       # 新目标
  python3 tools/loop_bootstrap.py --resume runs/<dir>       # 续接已有 run
  python3 tools/loop_bootstrap.py --selftest                # 自检

输出: 状态准备结果和 Claude Code `/loop runs/<dir>` 启动指令。
固定 loop 协议在 docs/templates/loop_prompt.md；不生成 per-run prompt。
"""

from __future__ import annotations

import argparse
import json as _json_mod
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RUNS = ROOT / "runs"
LOOP_TEMPLATE = ROOT / "docs" / "templates" / "loop_prompt.md"
PYTHON_CMD = sys.executable or "python3"
sys.path.insert(0, str(ROOT / "tools"))

import loop_journal  # noqa: E402
import status_style  # noqa: E402
import xunji_statusline  # noqa: E402

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

STATE_CN = {
    "DRIVER_ACTIVE": "主驾驶继续推进",
    "NEEDS_REVIEW": "需要先复审/解冲突",
    "NEEDS_AGENT_FANOUT": "需要并行分派 Agent",
    "NEEDS_PIVOT": "需要轨迹复盘并换路",
    "CLOSURE_CANDIDATE": "仅是收口复核候选",
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
    "run_closure_gates_replay_peer_review_and_retrospective": "跑收口硬门、replay、独立复审和复盘",
    "create_or_reopen_a_front_before_claiming_closure": "先创建或重开前线，不能直接宣称结束",
}


# ---- helpers ----

def _pretty_block(title: str, rows: list[str]) -> str:
    return status_style.box(title, rows, color="cyan", enabled=status_style.color_enabled())


def _read_json(path: Path) -> dict:
    try:
        data = _json_mod.loads(path.read_text(encoding="utf-8", errors="replace"))
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def _state_display(state: str) -> str:
    return f"{STATE_CN.get(state, state)} ({state})" if state else "未知"


def _action_display(action: str) -> str:
    return f"{ACTION_CN.get(action, action)} ({action})" if action else "未知"

def _find_run_by_slug(slug: str) -> Path | None:
    """按 slug 前缀找最近创建的 run 目录。"""
    candidates = sorted(RUNS.glob(f"{slug}_*"), key=lambda p: p.stat().st_mtime, reverse=True)
    return candidates[0] if candidates else None


def _validate_run(run_dir: Path) -> bool:
    """验证目录像合法 run：有 target.md 或有 evidence/ 子目录。FAIL-OPEN——拿不准不拦。"""
    try:
        if not run_dir.is_dir():
            return False
        has_target = (run_dir / "target.md").exists()
        has_evidence = (run_dir / "evidence").is_dir()
        return has_target or has_evidence
    except Exception:
        return True  # fail-open


def _loop_command(run_dir: Path) -> str:
    """The explicit Claude Code entry command. The fixed template stays in docs."""
    return f"/loop {run_dir}"


def _write_initial_state(run_dir: Path) -> None:
    """写初始 session_state.json。失败不阻断——state 可由后续轮次重建。"""
    state = {
        "drift_flags": [],
        "updated_at": time.time(),
        "reread_pending": False,
        "drift_block_count": 0,
    }
    sf = run_dir / "session_state.json"
    try:
        sf.write_text(_json_mod.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception:
        print(f"[bootstrap] 注意: 写 session_state.json 失败（后续轮次会重建）", file=sys.stderr)


def _refresh_loop_state(run_dir: Path) -> bool:
    """Refresh derived loop caches. These are advisory caches; Markdown stays canonical."""
    commands = [
        ("loop_state", [PYTHON_CMD, str(ROOT / "tools" / "loop_state.py"), str(run_dir), "--write"]),
        ("progress_ledger", [PYTHON_CMD, str(ROOT / "tools" / "progress_ledger.py"), str(run_dir), "--write"]),
        ("run_controller", [PYTHON_CMD, str(ROOT / "tools" / "run_controller.py"), str(run_dir), "--shadow"]),
    ]
    for name, cmd in commands:
        try:
            r = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
        except Exception as e:
            print(f"[bootstrap] {name} 刷新失败: {e}", file=sys.stderr)
            return False
        if r.stdout.strip():
            print(r.stdout.rstrip())
        if r.returncode != 0:
            if r.stderr.strip():
                print(r.stderr.rstrip(), file=sys.stderr)
            print(f"[bootstrap] {name} 刷新失败", file=sys.stderr)
            return False
    print(f"[bootstrap] loop state: {run_dir / 'state' / 'loop_state.json'}")
    print(f"[bootstrap] progress ledger: {run_dir / 'state' / 'progress_ledger.json'}")
    print(f"[bootstrap] controller shadow: {run_dir / 'state' / 'controller.shadow.json'}")
    _journal(run_dir, "state_refresh", "loop/progress/controller advisory caches refreshed")
    return True


def _print_status_summary(run_dir: Path) -> None:
    color = status_style.color_enabled()
    loop_data = _read_json(run_dir / "state" / "loop_state.json")
    controller = _read_json(run_dir / "state" / "controller.shadow.json")
    journal = loop_journal.summarize(run_dir)
    fronts = loop_data.get("fronts", {})
    progress = loop_data.get("progress", {})
    gates = loop_data.get("gates", {})
    rows = [
        status_style.field("运行目录", run_dir, "gray", enabled=color),
        status_style.field("推断阶段", status_style.phase_display(str(loop_data.get("phase") or "未知"), enabled=color), "blue", enabled=color),
        status_style.field(
            "当前打开阶段",
            status_style.phase_display(journal.get("open_phase"), enabled=color) if journal.get("open_phase") else status_style.tag("无", "gray", enabled=color),
            "cyan",
            enabled=color,
        ),
        status_style.field("前线", f"开放 {fronts.get('open_count', 0)} / 延后 {fronts.get('deferred_count', 0)} / 已关闭 {fronts.get('closed_count', 0)}", "white", enabled=color),
        status_style.field("证据", f"总计 {progress.get('evidence_total', 0)}；本轮新增 {len(progress.get('new_evidence_ids', []))}；置信提升 {len(progress.get('certainty_upgrades', []))}", "white", enabled=color),
        status_style.field("覆盖", f"已测 {progress.get('coverage_tested_cell_count', 0)}；未测 {progress.get('coverage_untested_cell_count', 0)}", "white", enabled=color),
        status_style.field("需要并行分派", "是" if gates.get("fanout_required") else "否", "yellow" if gates.get("fanout_required") else "green", enabled=color),
        status_style.field("收口复核候选", "是" if gates.get("completion_pause_candidate") else "否", "purple" if gates.get("completion_pause_candidate") else "gray", enabled=color),
        status_style.field("控制面状态", _state_display(str(controller.get("state") or "")), "yellow", enabled=color),
        status_style.field("下一步必须动作", _action_display(str(controller.get("next_required_action") or "")), "green", enabled=color),
    ]
    blockers = controller.get("stop_blockers") if isinstance(controller.get("stop_blockers"), list) else []
    if blockers:
        rows.append(status_style.field("停止阻断项", "，".join(str(b) for b in blockers[:6]), "red", enabled=color))
    print(_pretty_block("Xunji 当前状态总览", rows))


def _journal(run_dir: Path, event: str, note: str) -> None:
    """Best-effort derived journal write; failure must not block setup/resume."""
    if not run_dir.is_dir():
        return
    try:
        loop_journal.append_event(run_dir, event, note=note)
    except Exception as e:
        print(f"[bootstrap] journal write skipped: {e}", file=sys.stderr)


def _set_active_run(run_dir: Path) -> None:
    """Best-effort statusline pointer update. It is local display state only."""
    try:
        if not xunji_statusline.set_active_run(str(run_dir)):
            print(f"[bootstrap] active run pointer skipped: {run_dir}", file=sys.stderr)
    except Exception as e:
        print(f"[bootstrap] active run pointer skipped: {e}", file=sys.stderr)


# ---- commands ----

def cmd_new(slug: str, recon_path: str) -> int:
    """新 run：setup_run → 写初始状态 → 输出启动指令。"""
    recon_full = str(Path(recon_path).resolve())
    if not Path(recon_full).exists():
        print(f"[bootstrap] recon 文件不存在: {recon_full}", file=sys.stderr)
        return 1

    print(f"[bootstrap] 目标: {slug} | recon: {recon_full}")
    cmd = [sys.executable, str(ROOT / "tools" / "setup_run.py"), slug, recon_full]
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
    print(r.stdout.rstrip())
    if r.returncode != 0:
        print(r.stderr, file=sys.stderr)
        print("[bootstrap] setup_run 失败", file=sys.stderr)
        return 1

    run_dir = _find_run_by_slug(slug)
    if run_dir is None:
        print("[bootstrap] 未找到创建的 run 目录", file=sys.stderr)
        return 1
    print(f"[bootstrap] run 目录: {run_dir}")

    _write_initial_state(run_dir)
    _set_active_run(run_dir)
    _journal(run_dir, "bootstrap", f"new run prepared from recon {recon_full}")
    if not _refresh_loop_state(run_dir):
        return 1

    _print_launch_instructions(run_dir)
    return 0


def cmd_resume(run_path: str) -> int:
    """续接已有 run。"""
    run_dir = Path(run_path).resolve()
    if not _validate_run(run_dir):
        print(f"[bootstrap] 不是合法的 run 目录: {run_dir}", file=sys.stderr)
        return 1

    print(f"[bootstrap] 续接 run: {run_dir}")
    _set_active_run(run_dir)

    # 写 handoff
    subprocess.run([PYTHON_CMD, str(ROOT / "tools" / "session_handoff.py"),
                    "write", str(run_dir)], timeout=30)
    _journal(run_dir, "resume_prepare", "resume state prepared; loop not started until explicit /loop")
    if not _refresh_loop_state(run_dir):
        return 1

    _print_launch_instructions(run_dir)
    return 0


def _print_launch_instructions(run_dir: Path) -> None:
    """打印操作者启动和监控指令。"""
    _print_status_summary(run_dir)
    print()
    print(_pretty_block("Claude Code 启动入口", [
        status_style.field("启动命令", _loop_command(run_dir), "green", enabled=status_style.color_enabled()),
        status_style.field("固定协议", LOOP_TEMPLATE, "gray", enabled=status_style.color_enabled()),
        status_style.field("提示", "不生成 per-run loop_prompt.md；Claude Code 在 /loop 中读取固定协议和 run 文件。", "blue", enabled=status_style.color_enabled()),
    ]))
    print(_pretty_block("常用监控命令", [
        status_style.field("日志", f"{PYTHON_CMD} tools/loop_journal.py {run_dir} status", "cyan", enabled=status_style.color_enabled()),
        status_style.field("运行态", f"{PYTHON_CMD} tools/loop_state.py {run_dir} --write", "cyan", enabled=status_style.color_enabled()),
        status_style.field("进展账本", f"{PYTHON_CMD} tools/progress_ledger.py {run_dir} --write", "cyan", enabled=status_style.color_enabled()),
        status_style.field("控制面", f"{PYTHON_CMD} tools/run_controller.py {run_dir} --shadow", "cyan", enabled=status_style.color_enabled()),
        status_style.field("结构检查", f"{PYTHON_CMD} tools/check_run.py {run_dir}", "cyan", enabled=status_style.color_enabled()),
        status_style.field("决策流", f"tail -f {run_dir}/decisions.md", "gray", enabled=status_style.color_enabled()),
        status_style.field("运行态文件", f"cat {run_dir}/state/loop_state.md", "gray", enabled=status_style.color_enabled()),
        status_style.field("控制面文件", f"cat {run_dir}/state/controller_diff.md", "gray", enabled=status_style.color_enabled()),
    ]))


# ---- selftest ----

def _selftest() -> int:
    global _find_run_by_slug, _print_launch_instructions, _refresh_loop_state, _set_active_run

    import json as _json, tempfile

    checks: list[tuple[str, bool]] = []
    tmp_root = ROOT / "tmp"
    tmp_root.mkdir(exist_ok=True)
    p = Path(tempfile.mkdtemp(dir=tmp_root))
    (p / "evidence").mkdir()
    (p / "evidence" / ".gitkeep").write_text("")
    (p / "target.md").write_text("# t", encoding="utf-8")
    (p / "frontier.md").write_text("# f\n## Open Fronts\n### F-001\n- Status: open\n", encoding="utf-8")

    checks.append(("template exists", LOOP_TEMPLATE.exists()))
    checks.append(("loop command names run", _loop_command(p) == f"/loop {p}"))
    checks.append(("no per-run prompt before refresh", not (p / "loop_prompt.md").exists()))
    old_active = xunji_statusline.ACTIVE_RUN.read_text(encoding="utf-8", errors="replace") \
        if xunji_statusline.ACTIVE_RUN.exists() else None
    try:
        checks.append(("active run helper accepts run", xunji_statusline.set_active_run(str(p)) is True))
    finally:
        if old_active is None:
            xunji_statusline.clear_active_run()
        else:
            xunji_statusline.ACTIVE_RUN.write_text(old_active, encoding="utf-8")

    recon = p / "recon.json"
    recon.write_text("{}", encoding="utf-8")
    active_hook_calls: list[Path] = []
    orig_set_active = _set_active_run
    orig_find_run = _find_run_by_slug
    orig_refresh = _refresh_loop_state
    orig_print_launch = _print_launch_instructions
    orig_subprocess_run = subprocess.run

    class _FakeCompleted:
        returncode = 0
        stdout = ""
        stderr = ""

    def fake_set_active(run_dir: Path) -> None:
        active_hook_calls.append(Path(run_dir).resolve())

    def fake_run(*_args, **_kwargs) -> _FakeCompleted:
        return _FakeCompleted()

    try:
        _set_active_run = fake_set_active
        _find_run_by_slug = lambda _slug: p
        _refresh_loop_state = lambda _run_dir: True
        _print_launch_instructions = lambda _run_dir: None
        subprocess.run = fake_run
        rc_new = cmd_new("selftest", str(recon))
        rc_resume = cmd_resume(str(p))
    finally:
        _set_active_run = orig_set_active
        _find_run_by_slug = orig_find_run
        _refresh_loop_state = orig_refresh
        _print_launch_instructions = orig_print_launch
        subprocess.run = orig_subprocess_run

    checks.append(("cmd_new invokes active-run hook", rc_new == 0 and p.resolve() in active_hook_calls))
    checks.append(("cmd_resume invokes active-run hook", rc_resume == 0 and active_hook_calls.count(p.resolve()) >= 2))

    old_active_resume = xunji_statusline.ACTIVE_RUN.read_text(encoding="utf-8", errors="replace") \
        if xunji_statusline.ACTIVE_RUN.exists() else None
    try:
        rc_resume_real = cmd_resume(str(p))
        rendered_resume = xunji_statusline.render_statusline({"workspace": {"current_dir": str(ROOT)}}, color=False)
    finally:
        if old_active_resume is None:
            xunji_statusline.clear_active_run()
        else:
            xunji_statusline.ACTIVE_RUN.write_text(old_active_resume, encoding="utf-8")
    checks.append(("cmd_resume real set-active renders selected run", rc_resume_real == 0 and p.name in rendered_resume))
    _write_initial_state(p)
    checks.append(("session_state written", (p / "session_state.json").exists()))
    refresh_ok = _refresh_loop_state(p)
    checks.append(("loop_state refresh ok", refresh_ok and (p / "state" / "loop_state.json").exists()))
    checks.append(("progress ledger refresh ok", refresh_ok and (p / "state" / "progress_ledger.json").exists()))
    checks.append(("controller shadow refresh ok", refresh_ok and (p / "state" / "controller.shadow.json").exists()))
    checks.append(("loop journal written", (p / "state" / "loop_journal.jsonl").exists()))
    checks.append(("status summary reads refreshed state", _read_json(p / "state" / "loop_state.json").get("phase") == "Root Orchestrator"))
    checks.append(("refresh does not create per-run prompt", not (p / "loop_prompt.md").exists()))
    checks.append(("loop_state refresh fails closed", _refresh_loop_state(p / "missing-run") is False))
    checks.append(("validate run ok", _validate_run(p) is True))
    checks.append(("validate non-run fails", _validate_run(Path("/nonexistent")) is False))

    bad = [n for n, ok in checks if not ok]
    for n, ok in checks:
        print(("ok   " if ok else "FAIL ") + n, file=sys.stderr)
    print(f"loop_bootstrap selftest {'passed' if not bad else f'FAILED ({len(bad)})'}", file=sys.stderr)
    return 0 if not bad else 1


def main() -> int:
    ap = argparse.ArgumentParser(description="Xunji 全自动流水线启动器")
    ap.add_argument("slug_or_resume", nargs="?", help="<slug> 或 --resume 的路径")
    ap.add_argument("recon", nargs="?", help="recon.json 路径（新 run 时必填）")
    ap.add_argument("--resume", dest="resume", action="store_true",
                    help="续接已有 run（slug_or_resume 为 runs/<dir> 路径）")
    ap.add_argument("--selftest", action="store_true", help="自检")
    args = ap.parse_args()

    if args.selftest:
        return _selftest()
    if args.resume:
        if not args.slug_or_resume:
            ap.error("--resume 需要 runs/<dir> 路径")
        return cmd_resume(args.slug_or_resume)
    if not args.slug_or_resume or not args.recon:
        ap.error("新 run: <slug> <recon.json>；续接: --resume runs/<dir>")
    return cmd_new(args.slug_or_resume, args.recon)


if __name__ == "__main__":
    raise SystemExit(main())
