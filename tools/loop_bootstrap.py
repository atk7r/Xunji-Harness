#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""loop_bootstrap.py —— 一条命令启动 Xunji 全自动渗透流水线。

用法:
  python3 tools/loop_bootstrap.py <slug> <recon.json>       # 新目标
  python3 tools/loop_bootstrap.py --resume runs/<dir>       # 续接已有 run
  python3 tools/loop_bootstrap.py --selftest                # 自检

输出: 一个可保存到文件的 loop prompt 路径，和 /loop 启动指令。
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

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass


# ---- helpers ----

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


def _read_template() -> str:
    """读 loop 模板文件。不存在时返回内置最小模板。"""
    if LOOP_TEMPLATE.exists():
        try:
            return LOOP_TEMPLATE.read_text(encoding="utf-8")
        except Exception:
            pass
    return (
        "你是 Xunji 自主 Driver，对 run={{RUN_DIR}} 执行一轮探测。\n"
        "1. Reason pass: `{{PYTHON}} tools/loop_state.py \"{{RUN_DIR}}\" --write`; "
        "`{{PYTHON}} tools/progress_ledger.py \"{{RUN_DIR}}\" --write`; "
        "`{{PYTHON}} tools/run_controller.py \"{{RUN_DIR}}\" --shadow`。\n"
        "2. 结尾: 下一行动: <action> 或 BLOCKED: <reason>。\n"
    )


def _generate_loop_prompt(run_dir: Path) -> str:
    """用实际 run 目录路径替换模板中的 {{RUN_DIR}}。"""
    template = _read_template()
    return template.replace("{{RUN_DIR}}", str(run_dir)).replace("{{PYTHON}}", PYTHON_CMD)


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
    return True


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
    if not _refresh_loop_state(run_dir):
        return 1

    # 生成 loop prompt 文件
    prompt_text = _generate_loop_prompt(run_dir)
    prompt_file = run_dir / "loop_prompt.md"
    prompt_file.write_text(prompt_text, encoding="utf-8")

    # 输出操作者指令
    _print_launch_instructions(run_dir, prompt_file)
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
    if not _refresh_loop_state(run_dir):
        return 1

    prompt_text = _generate_loop_prompt(run_dir)
    prompt_file = run_dir / "loop_prompt.md"
    prompt_file.write_text(prompt_text, encoding="utf-8")

    _print_launch_instructions(run_dir, prompt_file)
    return 0


def _print_launch_instructions(run_dir: Path, prompt_file: Path) -> None:
    """打印操作者启动和监控指令。"""
    prompt_text = prompt_file.read_text(encoding="utf-8")
    print()
    print("=" * 60)
    print("  复制以下内容，粘贴到 Claude Code 聊天中:")
    print("=" * 60)
    print()
    print(f"/loop dynamic")
    print()
    print(prompt_text)
    print()
    print("=" * 60)
    print("  监控:")
    print(f"    {PYTHON_CMD} tools/loop_state.py {run_dir} --write")
    print(f"    {PYTHON_CMD} tools/progress_ledger.py {run_dir} --write")
    print(f"    {PYTHON_CMD} tools/run_controller.py {run_dir} --shadow")
    print(f"    {PYTHON_CMD} tools/check_run.py {run_dir}")
    print(f"    tail -f {run_dir}/decisions.md")
    print(f"    cat {run_dir}/state/loop_state.md")
    print(f"    cat {run_dir}/state/controller_diff.md")
    print("=" * 60)


# ---- selftest ----

def _selftest() -> int:
    import json as _json, tempfile

    checks: list[tuple[str, bool]] = []
    p = Path(tempfile.mkdtemp())
    (p / "evidence").mkdir()
    (p / "evidence" / ".gitkeep").write_text("")
    (p / "target.md").write_text("# t", encoding="utf-8")
    (p / "frontier.md").write_text("# f\n## Open Fronts\n### F-001\n- Status: open\n", encoding="utf-8")

    checks.append(("template exists", LOOP_TEMPLATE.exists()))
    fb = _generate_loop_prompt(p)
    checks.append(("prompt non-empty", bool(fb.strip())))
    checks.append(("prompt has run path", str(p) in fb))
    checks.append(("no template var left", "{{RUN_DIR}}" not in fb))
    checks.append(("python var replaced", "{{PYTHON}}" not in fb and PYTHON_CMD in fb))
    _write_initial_state(p)
    checks.append(("session_state written", (p / "session_state.json").exists()))
    refresh_ok = _refresh_loop_state(p)
    checks.append(("loop_state refresh ok", refresh_ok and (p / "state" / "loop_state.json").exists()))
    checks.append(("progress ledger refresh ok", refresh_ok and (p / "state" / "progress_ledger.json").exists()))
    checks.append(("controller shadow refresh ok", refresh_ok and (p / "state" / "controller.shadow.json").exists()))
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
