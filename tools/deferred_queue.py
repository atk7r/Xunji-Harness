#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""deferred_queue.py —— deferred 资产重试：包装 rerun_deferred.py，读结构化结果写回。

用法:
  python tools/deferred_queue.py --run runs/<dir>              # 重试 + 写回
  python tools/deferred_queue.py --run runs/<dir> --dry-run    # 仅列队列
  python tools/deferred_queue.py --selftest                    # 自检
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass


# ---- helpers ----

def find_coverage(run_dir: Path) -> Path | None:
    """在 run 目录树中找 coverage.json。"""
    hits = sorted(run_dir.glob("**/coverage.json"))
    return hits[0] if hits else None


def _read_rerun_json(run_dir: Path) -> dict | None:
    """读 coverage_rerun.json 结构化结果。不存在或读失败返回 None。"""
    rerun_file = run_dir / "classify" / "coverage_rerun.json"
    if not rerun_file.exists():
        return None
    try:
        return json.loads(rerun_file.read_text(encoding="utf-8", errors="replace"))
    except Exception:
        return None


def _already_open_hosts(run_dir: Path) -> set[str]:
    """从前沿中提取已有 open/probing 的主机名（避免重复追加）。"""
    hosts: set[str] = set()
    frontier = run_dir / "frontier.md"
    if not frontier.exists():
        return hosts
    try:
        text = frontier.read_text(encoding="utf-8", errors="replace")
        host_matches = re.findall(r'([a-z0-9](?:[-a-z0-9]*[a-z0-9])?(?:\.[a-z0-9](?:[-a-z0-9]*[a-z0-9])?)*\.[a-z]{2,})', text, re.IGNORECASE)
        hosts.update(h for h in host_matches if '.' in h and len(h) > 5)
    except Exception:
        pass
    return hosts


def _append_frontier(run_dir: Path, new_hosts: list[str]) -> bool:
    """在 frontier.md 的 Open Fronts 段追加新前沿，列出新可达主机且不重复已有。"""
    existing = _already_open_hosts(run_dir)
    fresh = [h for h in new_hosts if h not in existing]
    if not fresh:
        return False
    frontier = run_dir / "frontier.md"
    if not frontier.exists():
        return False
    try:
        text = frontier.read_text(encoding="utf-8", errors="replace")
        fid = _next_front_id(text)
        hosts_str = ", ".join(fresh)
        stamp = time.strftime('%Y-%m-%dT%H:%M:%S')
        new_front = (
            f"### {fid}: 出口恢复——新可达资产 (deferred_queue {stamp})\n\n"
            f"- Front: 之前不可达，出口恢复后已连接 ({hosts_str})\n"
            f"- Why it matters: 新打开的攻击面——之前因网络不可达被 deferred\n"
            f"- Current depth: shallow\n"
            f"- Status: open\n"
            f"- Barrier class: none\n"
            f"- Failure budget:\n"
            f"  - Same barrier failures: 0\n"
            f"  - Same bypass family attempts: 0\n"
            f"  - Same tech-stack assets tried: 0\n"
            f"- Best current evidence: E-xxx（deferred_queue 自动重连检测——待替换为实际探测 E-id）\n"
            f"- Next autonomous move: 对每个新可达资产做初步指纹探测\n"
            f"- Stop condition: 新可达资产充分探测\n"
            f"- Linked hypotheses: (new)\n"
        )
        if "## Open Fronts" in text:
            text = text.replace("## Open Fronts\n", f"## Open Fronts\n\n{new_front}\n")
        else:
            text = f"# Frontier\n\n## Open Fronts\n\n{new_front}\n{text}"
        frontier.write_text(text, encoding="utf-8")
        return True
    except Exception as e:
        print(f"[deferred_queue] 写 frontier 失败: {e}", file=sys.stderr)
        return False


def _next_front_id(frontier_text: str) -> str:
    ids = re.findall(r'### (F-\d+)', frontier_text)
    if not ids:
        return "F-001"
    nums = [int(fid.split("-")[1]) for fid in ids]
    return f"F-{max(nums) + 1:03d}"


# ---- main ----

def main() -> int:
    ap = argparse.ArgumentParser(description="Deferred 资产重试管理")
    ap.add_argument("--run", default=None, help="runs/<dir> 路径")
    ap.add_argument("--dry-run", action="store_true", help="仅列队列，不实际重试")
    ap.add_argument("--selftest", action="store_true", help="自检")
    args = ap.parse_args()

    if args.selftest:
        return _selftest()
    if not args.run:
        ap.error("--run runs/<dir> is required (or --selftest)")

    run_dir = Path(args.run).resolve()
    if not run_dir.is_dir():
        print(f"[deferred_queue] 不是目录: {run_dir}", file=sys.stderr)
        return 1

    cov = find_coverage(run_dir)
    if cov:
        data = json.loads(cov.read_text(encoding="utf-8", errors="replace"))
        unreachable = [a.get("host", "") for a in data.get("assets", [])
                       if a.get("reachable") is not True and a.get("host")]
        print(f"[deferred_queue] coverage 不可达: {len(unreachable)}")
    else:
        print("[deferred_queue] 未找到 coverage.json")

    if args.dry_run:
        print("[deferred_queue] dry-run——不执行重试")
        return 0

    # 执行 rerun_deferred.py
    print("[deferred_queue] 执行 rerun_deferred.py ...")
    cmd = [sys.executable, str(ROOT / "tools" / "rerun_deferred.py"), "--run", str(run_dir)]
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
    print(r.stdout.rstrip())
    if r.returncode != 0:
        print(r.stderr, file=sys.stderr)
        print("[deferred_queue] rerun_deferred 失败", file=sys.stderr)
        return 1

    # 读结构化结果（不是解析 stdout）
    rerun = _read_rerun_json(run_dir)
    if rerun is None:
        print("[deferred_queue] 未生成 coverage_rerun.json——可能无 deferred 资产或全部仍不可达")
        return 0

    newly = rerun.get("newly_reachable", [])
    still = rerun.get("still_unreachable", [])

    if isinstance(newly, list) and newly:
        new_hosts = [item.get("host", "") for item in newly if isinstance(item, dict) and item.get("host")]
    else:
        new_hosts = []
    if isinstance(still, list):
        still_hosts = [s for s in still if isinstance(s, str)]
    else:
        still_hosts = []

    print(f"[deferred_queue] 变可达: {len(new_hosts)} | 仍不可达: {len(still_hosts)}")

    if new_hosts:
        ok = _append_frontier(run_dir, new_hosts)
        print(f"[deferred_queue] {'已追加新前沿' if ok else '新资产: ' + ', '.join(new_hosts[:5])}")
        for h in new_hosts[:5]:
            print(f"  ✅ {h}")

    return 0


# ---- selftest ----

def _selftest() -> int:
    import tempfile

    checks: list[tuple[str, bool]] = []
    d = Path(tempfile.mkdtemp())
    run = d / "test_run"
    run.mkdir()
    (run / "classify").mkdir()
    (run / "evidence").mkdir()
    (run / "evidence" / ".gitkeep").write_text("")
    (run / "target.md").write_text("# Target\n", encoding="utf-8")
    (run / "frontier.md").write_text(
        "# Frontier\n\n## Open Fronts\n\n### F-001: test\n- Status: probing\n\n"
        "## Deferred Fronts\n\n### F-002: net\n- Barrier class: network-layer\n",
        encoding="utf-8")
    (run / "classify" / "coverage.json").write_text(json.dumps({
        "total": 3, "assets": [
            {"host": "a.test.com", "reachable": True},
            {"host": "b.test.com", "reachable": False},
            {"host": "c.test.com", "reachable": False}]}), encoding="utf-8")

    checks.append(("find_coverage", find_coverage(run) is not None))
    checks.append(("next_front_id", "F-003" in _next_front_id("### F-001\n### F-002\n")))

    # _append_frontier dedup: add a.test.com first, then try again → skipped
    _append_frontier(run, ["a.test.com"])
    added2 = _append_frontier(run, ["a.test.com"])
    checks.append(("dedup skips already-open host", added2 is False))

    # _read_rerun_json missing
    checks.append(("rerun json missing -> None", _read_rerun_json(run) is None))

    # Mock rerun result
    (run / "classify" / "coverage_rerun.json").write_text(json.dumps({
        "newly_reachable": [{"host": "b.test.com", "scheme": "http", "status": 200}],
        "still_unreachable": ["c.test.com"]}), encoding="utf-8")
    rerun = _read_rerun_json(run)
    checks.append(("rerun json reads", rerun is not None))
    if rerun:
        checks.append(("newly count", len(rerun.get("newly_reachable", [])) == 1))
        checks.append(("still count", len(rerun.get("still_unreachable", [])) == 1))

    bad = [n for n, ok in checks if not ok]
    for n, ok in checks:
        print(("ok   " if ok else "FAIL ") + n, file=sys.stderr)
    print(f"deferred_queue selftest {'passed' if not bad else f'FAILED ({len(bad)})'}", file=sys.stderr)
    return 0 if not bad else 1


if __name__ == "__main__":
    raise SystemExit(main())
