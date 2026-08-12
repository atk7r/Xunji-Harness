#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""rerun_deferred.py - 重跑"够不着(egress 受限)"的资产, 报哪些现在可达了。

实痛(某实战 实战): 高价值面(VPN 设备/SSO 核心/超时主机)被标 deferred(egress)散在 frontier
各处。换出口/冷却后/操作者境内跑时, 需要【一键重测所有够不着的】, 而不是翻 frontier 找。

数据源 = classify_hosts.py 产出的结构化 coverage.json(reachable!=True 的资产 = 重跑队列)。
本工具从【任何出口】都能跑: 当前出口冷却后重试、换了出口、或操作者在境内跑——
凡变可达的就重新分类、点出来。走 guard 熔断/限速; 不改原 coverage(写 *_rerun.json)。

  .venv/bin/python tools/rerun_deferred.py --run runs/<dir>  # 自动找 coverage.json
  .venv/bin/python tools/rerun_deferred.py --coverage runs/<dir>/classify/coverage.json
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import probe  # noqa: E402
import classify_hosts  # noqa: E402  (复用 classify_body)
from harness.guard import HostBackoff  # noqa: E402

try:
    sys.stdout.reconfigure(encoding="utf-8")       # type: ignore[attr-defined]
except Exception:
    pass


def find_coverage(run_dir: Path) -> Path | None:
    hits = sorted(run_dir.glob("**/coverage.json"))
    return hits[0] if hits else None


def main() -> int:
    ap = argparse.ArgumentParser(description="重跑 deferred(egress) 资产")
    ap.add_argument("--run", help="run 目录(自动找 coverage.json)")
    ap.add_argument("--coverage", help="直接给 coverage.json 路径")
    ap.add_argument("--delay", type=float, default=1.5)
    ap.add_argument("--timeout", type=int, default=8)
    args = ap.parse_args()

    cov_path = Path(args.coverage) if args.coverage else (
        find_coverage(Path(args.run)) if args.run else None)
    if not cov_path or not cov_path.exists():
        print("[rerun] 未找到 coverage.json —— 先跑 classify_hosts.py 生成检视台账。", file=sys.stderr)
        return 1
    data = json.loads(cov_path.read_text(encoding="utf-8", errors="replace"))
    queue = [a for a in data.get("assets", []) if a.get("reachable") is not True]
    print(f"[rerun] 队列(够不着的资产): {len(queue)} / 总 {data.get('total')}")
    if not queue:
        print("[rerun] 无 deferred 资产 —— 全部已可达。")
        return 0

    newly: list[dict] = []
    still: list[dict] = []
    for a in queue:
        h = a["host"]
        got = None
        for sc in ("https", "http"):
            try:
                d = probe.send("GET", f"{sc}://{h}/", {}, None, None, args.timeout, retry=1)
            except HostBackoff:
                d = {"error": "BACKOFF"}
            if "error" not in d:
                got = (sc, d)
                break
            time.sleep(0.3)
        if got:
            sc, d = got
            # 重新分类(需 body): 再取一次存内存
            sn = d.get("snippet", "") or ""
            stack, flags = classify_hosts.classify_body(sn)
            m = re.search(r"<title>(.*?)</title>", sn, re.I | re.S)
            ti = m.group(1).strip()[:30] if m else ""
            newly.append({"host": h, "scheme": sc, "status": d.get("status"),
                          "stack": stack, "flags": flags, "title": ti})
            print(f"  ✅ 现可达: {h:30} {sc} {d.get('status')} [{stack}] {ti} {flags}")
        else:
            still.append(h)
        time.sleep(args.delay)

    print(f"\n[rerun] 变可达 {len(newly)} | 仍够不着 {len(still)}")
    if newly:
        out = cov_path.with_name("coverage_rerun.json")
        out.write_text(json.dumps({"newly_reachable": newly, "still_unreachable": still},
                                  ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"  → 变可达的写入 {out}；这些是新打开的攻击面, 逐个深挖(尤其 VPN/SSO/独立栈)。")
    else:
        print("  仍全部够不着 —— 需换出口/境内中继, 或等更久冷却。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
