#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""workers.py — 并行 fan-out worker 的脚手架 + 合并状态台账(不是编排器)。

driver 在合适时把若干【互不阻塞、打不同资产】的 front 分给数个 fresh-context 子 agent
并行打(见 docs/templates/worker.md)。每个 worker 只写自己的 workers/W-<id>.md(候选发现),
driver 是唯一整合者: 把候选过【证据门】后并入 evidence.md。本工具只做两件事——

  --new <F-id>   在 runs/<dir>/workers/ 下开一个新的 W-<编号>.md 脚手架(分配下一个编号)
  (默认/--list)  列出所有 worker 文件: Status / 候选数 / 是否 done 但未 merge

它【不】spawn worker(那是 driver 用 Agent 工具做)、【不】决定分哪个 front(driver 判断)。
就像 coverage.json 是检视台账, 这是并行工作的台账。check_run.py 复用它报"done 未 merge"。

  python tools/workers.py runs/<dir>
  python tools/workers.py runs/<dir> --new F-005
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8")       # type: ignore[attr-defined]
except Exception:
    pass

ROOT = Path(__file__).resolve().parents[1]

SCAFFOLD = """# Worker {wid}

- Assigned front: {front}
- Status: working / done / merged
- Started:

## Candidate findings

### CAND-1
- Claim:
- Action / probe:
- Result:
- Proposed certainty: 0.3 / 0.5 / 0.8 / 1.0
- Control / Replicated:
- Caused by us: yes / no / unknown
- Alternative explanation:

## Leads for the driver (outside my lane)

-

## Notes

-
"""


def workers_dir(run_dir: Path) -> Path:
    return run_dir / "workers"


def scan(run_dir: Path) -> list[dict]:
    wd = workers_dir(run_dir)
    out: list[dict] = []
    for f in sorted(wd.glob("W-*.md")) if wd.exists() else []:
        text = f.read_text(encoding="utf-8", errors="replace")
        st = re.search(r"^-?\s*Status\s*[:：]\s*([A-Za-z]+)", text, re.M)
        front = re.search(r"^-?\s*Assigned front\s*[:：]\s*([^\n]+)", text, re.M)
        cands = len(re.findall(r"^###\s+CAND-", text, re.M))
        out.append({
            "file": f.name,
            "status": (st.group(1).lower() if st else "?"),
            "front": (front.group(1).strip() if front else "?"),
            "candidates": cands,
        })
    return out


def unmerged(run_dir: Path) -> list[dict]:
    """worker 标了 done 却还没被 driver merge(Status != merged) —— 并行成果别丢、证据门别跳。"""
    return [w for w in scan(run_dir) if w["status"] == "done"]


def next_id(run_dir: Path) -> str:
    n = 0
    for w in scan(run_dir):
        m = re.match(r"W-(\d+)", w["file"])
        if m:
            n = max(n, int(m.group(1)))
    return f"W-{n + 1:02d}"


def main() -> int:
    ap = argparse.ArgumentParser(description="并行 worker 脚手架 + 合并台账(不编排)")
    ap.add_argument("run_dir", type=Path)
    ap.add_argument("--new", metavar="F-ID", help="开一个新 worker 脚手架, 指派给该 front")
    args = ap.parse_args()
    run_dir = args.run_dir if args.run_dir.is_absolute() else ROOT / args.run_dir
    run_dir = run_dir.resolve()
    if not run_dir.exists():
        print(f"[workers] run 目录不存在: {run_dir}", file=sys.stderr)
        return 1

    if args.new:
        wd = workers_dir(run_dir)
        wd.mkdir(parents=True, exist_ok=True)
        wid = next_id(run_dir)
        path = wd / f"{wid}.md"
        path.write_text(SCAFFOLD.format(wid=wid, front=args.new), encoding="utf-8")
        print(f"[workers] 新建 {path.relative_to(ROOT)} → 指派 front {args.new}")
        print("  driver: 用 Agent 工具 spawn 一个 general-purpose 子 agent, 喂 docs/templates/worker.md "
              "的 prompt(填 target + 该 front), 让它把候选写进这个文件。")
        return 0

    rows = scan(run_dir)
    if not rows:
        print("[workers] 无 worker 文件 —— 串行单 driver 模式(并行只在 >=3 个互不阻塞前沿时才值得)。")
        return 0
    print(f"[workers] {len(rows)} 个 worker:")
    for w in rows:
        flag = "  ⚠️ done 未 merge → 过证据门并入 evidence.md" if w["status"] == "done" else ""
        print(f"  {w['file']:10} front={w['front']:10} status={w['status']:8} 候选={w['candidates']}{flag}")
    um = unmerged(run_dir)
    if um:
        print(f"\n[workers] {len(um)} 个 worker 已 done 但未 merge —— driver 须逐个过【证据门】"
              "(>=0.8 要 Control/复现, 否则降级)、分配 E-id、去重、更新 frontier, 再标 merged。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
