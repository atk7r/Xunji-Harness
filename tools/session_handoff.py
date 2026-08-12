#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""session_handoff.py —— 会话交接：写 handoff 文件 / 打印续接 prompt。

用法:
  .venv/bin/python tools/session_handoff.py write runs/<dir>    # 写 session_handoff.md
  .venv/bin/python tools/session_handoff.py pickup runs/<dir>   # 打印续接 prompt
  .venv/bin/python tools/session_handoff.py --selftest          # 自检
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RUNS = ROOT / "runs"

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass


# ---- helpers ----

def _derive_counters(run_dir: Path) -> tuple[str, str, str]:
    """从 decisions / evidence 提取最后编号。FAIL-OPEN——全失败返回 'none'。"""
    last_d, last_e = "none", "none"
    for fname, prefix, target in [("decisions.md", "## D-", "last_d"),
                                   ("evidence.md", "## E-", "last_e")]:
        f = run_dir / fname
        if not f.exists():
            continue
        try:
            for line in f.read_text(encoding="utf-8", errors="replace").splitlines():
                if line.startswith(prefix):
                    if target == "last_d":
                        last_d = line.replace("## ", "").strip()
                    else:
                        last_e = line.replace("## ", "").strip()
        except Exception:
            pass
    # stage: use anti_drift if available
    stage = "Setup"
    try:
        sys.path.insert(0, str(ROOT / "tools"))
        from anti_drift import _detect_stage
        stage = _detect_stage(run_dir)
    except Exception:
        frontier = run_dir / "frontier.md"
        if frontier.exists():
            text = frontier.read_text(encoding="utf-8", errors="replace")
            if "Status: probing" in text or "Status: open" in text:
                stage = "Driver"
    return stage, last_d, last_e


def _check_pending_gates(run_dir: Path) -> list[str]:
    """检查 overdue review/check。FAIL-OPEN——异常返空列表不阻断。"""
    pending: list[str] = []
    # Intermediate gates via check_run
    try:
        sys.path.insert(0, str(ROOT / "tools"))
        import check_run as cr
        errors, warns = cr.check_intermediate_gates(run_dir)
        for e in errors[:3]:
            pending.append(f"BLOCKER: {e[:100]}")
        for w in warns[:3]:
            pending.append(f"WARN: {w[:100]}")
    except Exception:
        pass
    # Independent review check — compatible with Chinese/English markers
    try:
        review = run_dir / "review.md"
        has_review = False
        if review.exists():
            rv = review.read_text(encoding="utf-8", errors="replace")
            if re.search(r"Independent Review|独立复审|independent.review", rv, re.IGNORECASE):
                has_review = True
        if not has_review:
            pending.append("缺少独立复审")
    except Exception:
        pass
    return pending


def _read_drift_state(run_dir: Path) -> str:
    """读 drift_block.json，带 cross-run guard 和 TTL。FAIL-OPEN——读不到返 'clean'。"""
    block_file = ROOT / ".claude" / "drift_block.json"
    if not block_file.exists():
        return "clean"
    try:
        block = json.loads(block_file.read_text(encoding="utf-8"))
        if not block.get("active", False):
            return "clean"
        age = time.time() - block.get("blocked_at", 0)
        if age > 600:
            return "clean"
        # Cross-run guard: if block names a run, must match current
        block_run = block.get("run")
        if block_run and run_dir.name != block_run:
            return "clean"
        return f"active: {', '.join(block.get('drift_flags', ['unknown']))}"
    except Exception:
        return "clean"


def write_handoff(run_dir: Path) -> int:
    """写 session_handoff.md。返回 0=成功 1=失败。"""
    if not run_dir.is_dir():
        print(f"[handoff] 不是目录: {run_dir}", file=sys.stderr)
        return 1

    stage, last_d, last_e = _derive_counters(run_dir)
    pending = _check_pending_gates(run_dir)
    drift = _read_drift_state(run_dir)

    content = f"""# Session Handoff

- Run: {run_dir.name}
- Updated: {time.strftime('%Y-%m-%dT%H:%M:%S')}
- Current stage: {stage}
- Last decision: {last_d}
- Last evidence: {last_e}
- Fresh files: target.md → frontier.md → decisions.md → evidence.md → review.md
- Pending gates:
"""
    for g in pending:
        content += f"  - {g}\n"
    if not pending:
        content += "  - (none)\n"
    content += f"- Drift state: {drift}\n"
    content += f"- Next action: Read files above → Reason pass → continue from {stage}.\n"
    content += f"- Do not rely on prior chat: restart from this file + run directory.\n"

    handoff_file = run_dir / "session_handoff.md"
    try:
        handoff_file.write_text(content, encoding="utf-8")
        print(f"[handoff] written: {handoff_file}")
        return 0
    except Exception as e:
        print(f"[handoff] 写失败: {e}", file=sys.stderr)
        return 1


def pickup_prompt(run_dir: Path) -> str:
    """生成新会话续接 prompt。"""
    if not run_dir.is_dir():
        return f"# Error: {run_dir} 不是目录"

    stage, _, _ = _derive_counters(run_dir)
    return (
        f"Pickup Xunji run {run_dir} — 当前阶段: {stage}\n"
        f"先读 {run_dir}/session_handoff.md，然后按顺序:\n"
        f"  target.md → frontier.md → decisions.md → evidence.md → review.md\n"
        f"聊天上下文为空——所有状态在 run 目录文件中。\n"
        f"执行一轮自主探测: Reason pass → 选前沿 → 探测 → 更新状态。\n"
        f"结尾: 下一行动: <action> 或 BLOCKED: <reason>\n"
    )


# ---- selftest ----

def _selftest() -> int:
    import tempfile

    checks: list[tuple[str, bool]] = []
    d = Path(tempfile.mkdtemp())
    run = d / "test_run"
    run.mkdir()
    (run / "evidence").mkdir()
    (run / "evidence" / ".gitkeep").write_text("")
    (run / "frontier.md").write_text(
        "# Frontier\n\n## Open Fronts\n\n### F-001: test\n- Status: probing\n\n"
        "### F-002: closed\n- Status: closed\n\n"
        "### F-003: also open\n- Status: open\n",
        encoding="utf-8")
    (run / "decisions.md").write_text("## D-001\n- Result: test\n", encoding="utf-8")
    (run / "evidence.md").write_text("## E-001\n- Certainty: 0.5\n", encoding="utf-8")
    (run / "target.md").write_text("# Target\n- Target: test\n", encoding="utf-8")
    (run / "review.md").write_text("# Review\n独立复审 completed\n", encoding="utf-8")

    # write_handoff
    rc = write_handoff(run)
    checks.append(("write_handoff returns 0", rc == 0))
    checks.append(("handoff file exists", (run / "session_handoff.md").exists()))
    if (run / "session_handoff.md").exists():
        ho = (run / "session_handoff.md").read_text(encoding="utf-8")
        checks.append(("handoff has stage", "Current stage:" in ho))
        checks.append(("handoff has D-001", "D-001" in ho))
        checks.append(("handoff has E-001", "E-001" in ho))
        # Should NOT have "缺少独立复审" since review.md has 独立复审
        checks.append(("no spurious review warning", "缺少独立复审" not in ho))

    # pickup
    pp = pickup_prompt(run)
    checks.append(("pickup non-empty", bool(pp.strip())))
    checks.append(("pickup mentions run", str(run) in pp))

    # write to bad path
    rc_bad = write_handoff(Path("/nonexistent/path"))
    checks.append(("bad path returns non-zero", rc_bad != 0))

    bad = [n for n, ok in checks if not ok]
    for n, ok in checks:
        print(("ok   " if ok else "FAIL ") + n, file=sys.stderr)
    print(f"session_handoff selftest {'passed' if not bad else f'FAILED ({len(bad)})'}", file=sys.stderr)
    return 0 if not bad else 1


def main() -> int:
    ap = argparse.ArgumentParser(description="Xunji 会话交接工具")
    ap.add_argument("action", nargs="?", choices=["write", "pickup"], help="write|pickup")
    ap.add_argument("run_dir", nargs="?", help="runs/<dir> 路径")
    ap.add_argument("--selftest", action="store_true", help="自检")
    args = ap.parse_args()

    if args.selftest:
        return _selftest()
    if not args.action or not args.run_dir:
        ap.error("需要 action(write|pickup) 和 run_dir")

    run_dir = Path(args.run_dir).resolve()
    if args.action == "write":
        return write_handoff(run_dir)
    else:
        print(pickup_prompt(run_dir))
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
