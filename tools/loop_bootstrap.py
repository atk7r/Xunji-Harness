#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""loop_bootstrap.py —— 准备 Xunji loop 运行状态。

用法:
  python3 tools/loop_bootstrap.py <slug> <recon.json>       # 新目标
  python3 tools/loop_bootstrap.py --source <run|URL|file> --type auto|run|url|recon-json|file
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
import setup_normalizer  # noqa: E402
import setup_run  # noqa: E402
import setup_source  # noqa: E402
import setup_transaction  # noqa: E402
import status_style  # noqa: E402
import xunji_statusline  # noqa: E402
from anti_drift import SessionStateManager  # noqa: E402

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
    "do_not_schedule_another_loop_iteration": "运行已完成；不要再排下一轮 /loop",
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

def _validate_run(run_dir: Path) -> bool:
    """Fail closed unless the explicit path is a structurally recognizable run."""
    try:
        resolved = run_dir.resolve()
        resolved.relative_to(RUNS.resolve())
        if not resolved.is_dir():
            return False
        return (
            (resolved / "target.md").is_file()
            and (resolved / "frontier.md").is_file()
            and (resolved / "evidence").is_dir()
        )
    except Exception:
        return False


def _loop_command(run_dir: Path) -> str:
    """The explicit Claude Code entry command. The fixed template stays in docs."""
    return f"/loop {run_dir}"


def _write_initial_state(run_dir: Path) -> None:
    """写初始 state/session_state.json。失败不阻断——state 可由后续轮次重建。"""
    state = {
        "drift_flags": [],
        "updated_at": time.time(),
        "reread_pending": False,
        "drift_block_count": 0,
    }
    try:
        SessionStateManager.save(run_dir, state)
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


def _set_active_run(run_dir: Path) -> bool:
    """Resume a prepared run through the shared activation CAS primitive."""
    try:
        setup_transaction.activate_existing_run(
            run_dir,
            operation=setup_transaction.OP_LOOP_BOOTSTRAP_RESUME,
            root=ROOT,
            runs_root=RUNS,
            pointer=xunji_statusline.ACTIVE_RUN,
        )
        return True
    except Exception as e:
        print(f"[bootstrap] active run switch failed: {e}", file=sys.stderr)
        return False


# ---- commands ----

def _create_new_transaction(slug: str, recon_full: str) -> setup_transaction.TransactionResult:
    """Loop adapter: resolve source, then call the shared transaction directly."""
    request = setup_run.resolve_setup_request(
        slug, recon=recon_full, target=None, date=None, classify=False
    )
    return setup_transaction.create_and_activate(
        request["run_name"],
        source_manifest=request["source_manifest"],
        effect_profile=setup_transaction.lifecycle_effect_profile(
            setup_transaction.OP_LOOP_BOOTSTRAP_CREATE,
            request["run_name"],
            source_type="recon-json",
        ),
        build=lambda run_dir, fault: setup_run.prepare_staging_run(
            request, run_dir, fault, bootstrap=True
        ),
        validate_source=request.get("validate_source"),
        root=ROOT,
        runs_root=RUNS,
        pointer=xunji_statusline.ACTIVE_RUN,
    )


def _create_source_transaction(
    route: setup_source.SourceRoute,
    *,
    source_type: str = "auto",
    ai_mode: str = "off",
    candidate_json: str | None = None,
    provider: str = "",
    model: str = "",
) -> setup_transaction.TransactionResult:
    """Adapt one deterministic source route to the shared setup transaction."""
    if route.kind == "url":
        request = setup_run.resolve_setup_request(
            route.slug, recon=None, target=route.value, date=None, classify=False
        )
    elif route.kind == "recon-json" and route.source_path is not None:
        request = setup_run.resolve_setup_request(
            route.slug, recon=str(route.source_path), target=None, date=None, classify=False
        )
    elif route.kind in {"json", "markdown"} and route.source_path is not None:
        request = setup_run.resolve_normalized_request(
            route.source_path,
            ai_mode=ai_mode,
            candidate_json=candidate_json,
            provider=provider,
            model=model,
        )
    else:
        raise setup_source.SetupSourceError(
            "unsupported_route", f"route does not create a run: {route.kind}"
        )
    return setup_transaction.create_and_activate(
        request["run_name"],
        source_manifest=request["source_manifest"],
        effect_profile=setup_transaction.lifecycle_effect_profile(
            setup_transaction.OP_LOOP_BOOTSTRAP_CREATE,
            request["run_name"],
            source_type=source_type,
            ai_mode=ai_mode,
            provider=provider,
            model=model,
            candidate_json=candidate_json,
        ),
        build=lambda run_dir, fault: setup_run.prepare_staging_run(
            request, run_dir, fault, bootstrap=True
        ),
        validate_source=request.get("validate_source"),
        root=ROOT,
        runs_root=RUNS,
        pointer=xunji_statusline.ACTIVE_RUN,
    )


def cmd_source(
    value: str,
    source_type: str = "auto",
    *,
    ai_mode: str = "off",
    candidate_json: str | None = None,
    provider: str = "",
    model: str = "",
    prepare_normalizer: bool = False,
) -> int:
    """Route an explicit source without fetching it or starting target work."""
    try:
        route = setup_source.route_source(value, source_type=source_type, runs_root=RUNS)
    except setup_source.SetupSourceError as exc:
        print(f"[bootstrap:{exc.code}] {exc}", file=sys.stderr)
        return 1
    if route.kind == "run" and route.run_dir is not None:
        if ai_mode != "off" or candidate_json or provider or model or prepare_normalizer:
            print("[bootstrap:ai_not_applicable] existing-run resume does not accept normalizer flags", file=sys.stderr)
            return 1
        return cmd_resume(str(route.run_dir))
    if route.kind not in {"json", "markdown"} and (
        ai_mode != "off" or candidate_json or provider or model or prepare_normalizer
    ):
        print("[bootstrap:ai_not_applicable] AI flags apply only to Markdown/ordinary-JSON candidate routes", file=sys.stderr)
        return 1
    if prepare_normalizer:
        if ai_mode != "external" or candidate_json is not None:
            print("[bootstrap:invalid_normalizer_prepare] prepare requires --ai external and no candidate", file=sys.stderr)
            return 1
        try:
            request, _ = setup_normalizer.prepare_request(
                route.source_path,
                ai_mode=ai_mode,
                provider=provider,
                model=model,
            )
        except setup_source.SetupSourceError as exc:
            print(f"[bootstrap:{exc.code}] {exc}", file=sys.stderr)
            return 1
        print(_json_mod.dumps({
            "request": request,
            "candidate_template": setup_normalizer.candidate_template(request),
        }, ensure_ascii=False, sort_keys=True))
        return 0
    if ai_mode == "external" and candidate_json is None:
        print(
            "[bootstrap:ai_candidate_required] external mode requires a candidate; "
            "first rerun with --prepare-normalizer, then submit token IDs with --candidate-json",
            file=sys.stderr,
        )
        return 1
    try:
        result = _create_source_transaction(
            route,
            source_type=source_type,
            ai_mode=ai_mode,
            candidate_json=candidate_json,
            provider=provider,
            model=model,
        )
    except (setup_source.SetupSourceError, setup_transaction.SetupTransactionError) as exc:
        code = getattr(exc, "code", "source_setup_failed")
        hint = ""
        if code in {"run_exists", "prepared_not_active"}:
            hint = "；可 resume 已有 run，或用 setup_run.py 选择 date/slug"
        print(f"[bootstrap:{code}] {exc}{hint}", file=sys.stderr)
        return 1
    _print_launch_instructions(result.run_dir)
    return 0


def cmd_new(slug: str, recon_path: str) -> int:
    """New-run adapter; the shared transaction is the sole commit owner."""
    recon_full = str(Path(recon_path).resolve())
    if not Path(recon_full).exists():
        print(f"[bootstrap] recon 文件不存在: {recon_full}", file=sys.stderr)
        return 1

    print(f"[bootstrap] 目标: {slug} | recon: {recon_full}")
    try:
        result = _create_new_transaction(slug, recon_full)
    except setup_transaction.SetupTransactionError as exc:
        print(f"[bootstrap:{exc.code}] {exc}", file=sys.stderr)
        return 1
    run_dir = result.run_dir
    print(f"[bootstrap] run 目录: {run_dir}")

    _print_launch_instructions(run_dir)
    return 0


def cmd_resume(run_path: str) -> int:
    """续接已有 run。"""
    run_dir = Path(run_path).resolve()
    if not _validate_run(run_dir):
        print(f"[bootstrap] 不是合法的 run 目录: {run_dir}", file=sys.stderr)
        return 1

    print(f"[bootstrap] 续接 run: {run_dir}")

    # 写 handoff
    subprocess.run([PYTHON_CMD, str(ROOT / "tools" / "session_handoff.py"),
                    "write", str(run_dir)], timeout=30)
    _journal(run_dir, "resume_prepare", "resume state prepared; loop not started until explicit /loop")
    if not _refresh_loop_state(run_dir):
        return 1
    if not _set_active_run(run_dir):
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
    global _create_new_transaction, _create_source_transaction
    global _print_launch_instructions, _refresh_loop_state, _set_active_run

    import contextlib, io, json as _json, tempfile

    checks: list[tuple[str, bool]] = []
    tmp_root = RUNS
    tmp_root.mkdir(exist_ok=True)
    p = Path(tempfile.mkdtemp(dir=tmp_root))
    (p / "evidence").mkdir()
    (p / "evidence" / ".gitkeep").write_text("")
    (p / "target.md").write_text("# t", encoding="utf-8")
    (p / "frontier.md").write_text("# f\n## Open Fronts\n### F-001\n- Status: open\n", encoding="utf-8")

    checks.append(("template exists", LOOP_TEMPLATE.exists()))
    checks.append(("loop command names run", _loop_command(p) == f"/loop {p}"))
    checks.append(("no per-run prompt before refresh", not (p / "loop_prompt.md").exists()))
    original_active_pointer = xunji_statusline.ACTIVE_RUN
    isolated_active_pointer = p / ".active-run"
    xunji_statusline.ACTIVE_RUN = isolated_active_pointer
    try:
        setup_transaction.activate_existing_run(
            p,
            operation=setup_transaction.OP_TRANSACTION_ACTIVATE,
            root=ROOT,
            runs_root=RUNS,
            pointer=isolated_active_pointer,
            pending_dir=p / ".pending",
            claims_dir=p / ".claims",
        )
        checks.append(("active run helper accepts run", xunji_statusline.set_active_run(str(p)) is True))
    finally:
        xunji_statusline.ACTIVE_RUN = original_active_pointer

    recon = p / "recon.json"
    recon.write_text(_json.dumps({
        "assets": [{"host": "selftest.example", "ownership": "core"}],
    }), encoding="utf-8")
    unsupported_root = Path(tempfile.mkdtemp())
    unsupported_source = unsupported_root / "ordinary.json"
    unsupported_source.write_text(
        _json.dumps({"target": "https://example.test/"}), encoding="utf-8"
    )
    shared_calls: list[str] = []
    shared_profiles: list[dict] = []
    original_shared_create = setup_transaction.create_and_activate

    def fake_shared_create(run_name: str, **kwargs):
        shared_calls.append(run_name)
        shared_profiles.append(dict(kwargs.get("effect_profile") or {}))
        return setup_transaction.TransactionResult(
            p.resolve(), "e" * 32, "f" * 64, "committed"
        )

    try:
        setup_transaction.create_and_activate = fake_shared_create
        real_adapter_result = _create_new_transaction("adaptercheck", str(recon))
    finally:
        setup_transaction.create_and_activate = original_shared_create
    checks.append((
        "legacy new-run adapter returns the shared transaction result",
        real_adapter_result.status == "committed"
        and len(shared_calls) == 1
        and shared_calls[0].startswith("adaptercheck_")
        and shared_calls[0][-8:].isdigit()
        and shared_profiles[0].get("operation")
        == setup_transaction.OP_LOOP_BOOTSTRAP_CREATE
        and shared_profiles[0].get("source_type") == "recon-json"
    ))
    active_hook_calls: list[Path] = []
    transaction_calls: list[tuple[str, str]] = []
    source_transaction_calls: list[str] = []
    source_transaction_options: list[dict] = []
    orig_set_active = _set_active_run
    orig_create_transaction = _create_new_transaction
    orig_create_source_transaction = _create_source_transaction
    orig_refresh = _refresh_loop_state
    orig_print_launch = _print_launch_instructions
    orig_subprocess_run = subprocess.run

    class _FakeCompleted:
        returncode = 0
        stdout = ""
        stderr = ""

    def fake_set_active(run_dir: Path) -> bool:
        active_hook_calls.append(Path(run_dir).resolve())
        return True

    def fake_create_transaction(slug: str, recon_path: str):
        transaction_calls.append((slug, recon_path))
        return setup_transaction.TransactionResult(
            p.resolve(), "a" * 32, "b" * 64, "committed"
        )

    def fake_create_source_transaction(route: setup_source.SourceRoute, **kwargs):
        source_transaction_calls.append(route.kind)
        source_transaction_options.append(dict(kwargs))
        return setup_transaction.TransactionResult(
            p.resolve(), "c" * 32, "d" * 64, "committed"
        )

    def fake_run(*_args, **_kwargs) -> _FakeCompleted:
        return _FakeCompleted()

    try:
        _set_active_run = fake_set_active
        _create_new_transaction = fake_create_transaction
        _create_source_transaction = fake_create_source_transaction
        _refresh_loop_state = lambda _run_dir: True
        _print_launch_instructions = lambda _run_dir: None
        subprocess.run = fake_run
        rc_new = cmd_new("selftest", str(recon))
        rc_source = cmd_source("https://example.test/path?key=opaque", "auto")
        rc_normalized_off = cmd_source(str(unsupported_source), "auto")
        calls_before_prepare = list(source_transaction_calls)
        prepare_out = io.StringIO()
        with contextlib.redirect_stdout(prepare_out):
            rc_prepare = cmd_source(
                str(unsupported_source), "auto", ai_mode="external",
                provider="claude-code", model="fixture-model",
                prepare_normalizer=True,
            )
        rc_missing_candidate = cmd_source(
            str(unsupported_source), "auto", ai_mode="external",
            provider="claude-code", model="fixture-model",
        )
        rc_resume = cmd_resume(str(p))
    finally:
        _set_active_run = orig_set_active
        _create_new_transaction = orig_create_transaction
        _create_source_transaction = orig_create_source_transaction
        _refresh_loop_state = orig_refresh
        _print_launch_instructions = orig_print_launch
        subprocess.run = orig_subprocess_run

    checks.append(("cmd_new delegates to shared setup transaction",
                   rc_new == 0 and transaction_calls == [("selftest", str(recon.resolve()))]))
    checks.append(("--source URL delegates to deterministic router and shared transaction",
                   rc_source == 0 and source_transaction_calls[:1] == ["url"]))
    checks.append(("ordinary JSON --ai off delegates through the shared transaction",
                   rc_normalized_off == 0 and source_transaction_calls == ["url", "json"]))
    checks.append(("source adapter preserves the validated source type for effect binding",
                   [item.get("source_type") for item in source_transaction_options]
                   == ["auto", "auto"]))
    checks.append(("external prepare emits only a redacted request without transaction work",
                   rc_prepare == 0
                   and 'setup-normalizer-request.v1' in prepare_out.getvalue()
                   and calls_before_prepare == source_transaction_calls))
    checks.append(("external mode without candidate fails before transaction work",
                   rc_missing_candidate == 1 and calls_before_prepare == source_transaction_calls))
    checks.append(("cmd_new does not perform a second active-pointer commit",
                   active_hook_calls.count(p.resolve()) == 1))
    checks.append(("cmd_resume invokes shared active CAS",
                   rc_resume == 0 and p.resolve() in active_hook_calls))

    xunji_statusline.ACTIVE_RUN = isolated_active_pointer
    try:
        rc_resume_real = cmd_resume(str(p))
        import turn_contract  # noqa: WPS433
        resume_session = "loop-bootstrap-statusline-session"
        resume_transcript = str(p / "loop-bootstrap-statusline.jsonl")
        turn_contract.write_contract(p, {
            "session_id": resume_session,
            "transcript_path": resume_transcript,
            "prompt": f"/loop runs/{p.name}",
        })
        rendered_resume = xunji_statusline.render_statusline({
            "session_id": resume_session,
            "transcript_path": resume_transcript,
            "workspace": {"current_dir": str(ROOT)},
        }, color=False)
    finally:
        xunji_statusline.ACTIVE_RUN = original_active_pointer
    checks.append(("cmd_resume real set-active renders selected run", rc_resume_real == 0 and p.name in rendered_resume))
    _write_initial_state(p)
    checks.append(("session_state written", (p / "state" / "session_state.json").exists()))
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
    import shutil
    shutil.rmtree(p, ignore_errors=True)
    shutil.rmtree(unsupported_root, ignore_errors=True)
    return 0 if not bad else 1


def main() -> int:
    ap = argparse.ArgumentParser(description="Xunji 全自动流水线启动器")
    ap.add_argument("slug_or_resume", nargs="?", help="<slug> 或 --resume 的路径")
    ap.add_argument("recon", nargs="?", help="recon.json 路径（新 run 时必填）")
    ap.add_argument("--resume", dest="resume", action="store_true",
                    help="续接已有 run（slug_or_resume 为 runs/<dir> 路径）")
    ap.add_argument("--source", help="统一输入: existing run、http/https URL 或本地文件")
    ap.add_argument("--type", dest="source_type", default=None,
                    choices=sorted(setup_source.SUPPORTED_TYPES),
                    help="source 路由类型；auto 按 run → URL → 内容识别")
    ap.add_argument("--ai", choices=sorted(setup_normalizer.AI_MODES), default="off",
                    help="candidate normalizer: off(默认) / local(需登记) / external(硬脱敏)")
    ap.add_argument("--ai-provider", default="", help="external normalizer provider identity")
    ap.add_argument("--ai-model", default="", help="external normalizer model identity")
    ap.add_argument("--candidate-json", default=None,
                    help="reference-only setup-normalizer-candidate.v1 JSON")
    ap.add_argument("--prepare-normalizer", action="store_true",
                    help="输出硬脱敏 request + candidate template，不创建 run/切 pointer")
    ap.add_argument("--selftest", action="store_true", help="自检")
    args = ap.parse_args()

    if args.selftest:
        return _selftest()
    if args.source:
        if args.resume or args.slug_or_resume or args.recon:
            ap.error("--source 不能与 legacy positional 或 --resume 混用")
        return cmd_source(
            args.source,
            args.source_type or "auto",
            ai_mode=args.ai,
            candidate_json=args.candidate_json,
            provider=args.ai_provider,
            model=args.ai_model,
            prepare_normalizer=args.prepare_normalizer,
        )
    if args.source_type is not None:
        ap.error("--type 只能与 --source 一起使用")
    if args.ai != "off" or args.ai_provider or args.ai_model or args.candidate_json \
            or args.prepare_normalizer:
        ap.error("normalizer flags 只能与 --source 一起使用")
    if args.resume:
        if not args.slug_or_resume:
            ap.error("--resume 需要 runs/<dir> 路径")
        return cmd_resume(args.slug_or_resume)
    if not args.slug_or_resume or not args.recon:
        ap.error("新 run: <slug> <recon.json>；续接: --resume runs/<dir>")
    return cmd_new(args.slug_or_resume, args.recon)


if __name__ == "__main__":
    raise SystemExit(main())
