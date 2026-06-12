#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""ingest_recon.py — 把 recon/OSINT 报告折成 surface.md 可用的摘要。

实现 WORKFLOW.md「Ingest Existing Intelligence First」的机械部分: 读一份 recon JSON,
输出资产表 + 入口 + needs_human + **可达性矩阵**(recon 视角 vs 你出口视角), 并标注来源。
它只【结构化情报】, 不做选择/判断 —— front 选择仍是 driver 的事。

支持 osint_ai report_agent 的 schema(target/assets/entry_points/needs_human/
verification_tasks/infrastructure/stats), 未知 schema 则降级为顶层键概览。

  python tools/ingest_recon.py <recon.json>               # 打到 stdout
  python tools/ingest_recon.py <recon.json> --out runs/<t>/surface_recon.md
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


def _g(d: dict, *keys, default=""):
    for k in keys:
        if isinstance(d, dict) and d.get(k) not in (None, ""):
            return d[k]
    return default


def render(recon: dict, src: str) -> str:
    out: list[str] = []
    target = _g(recon, "target", default="(unknown)")
    org = _g(recon, "organization", "org")
    gen = _g(recon, "generated_at", "generated")
    out.append(f"# Surface — ingested from recon")
    out.append("")
    out.append(f"> Source: `{src}`" + (f" (generated_at {gen})" if gen else ""))
    out.append(f"> Target: **{target}**" + (f" — {org}" if org else ""))
    out.append("> 按 WORKFLOW「Ingest Existing Intelligence First」折叠; recon 已收集的事实"
               "(存活/IP/标题/指纹/分类)视为既有, 不重复发现。")
    out.append("")

    stats = recon.get("stats")
    if isinstance(stats, dict):
        kv = ", ".join(f"{k}={v}" for k, v in stats.items())
        out.append(f"- Stats: {kv}")
        out.append("")

    assets = recon.get("assets")
    if isinstance(assets, list) and assets:
        out.append("## Assets")
        out.append("")
        out.append("| host | category | recon-reach | verdict | tech | url |")
        out.append("|------|----------|-------------|---------|------|-----|")
        for a in assets:
            if not isinstance(a, dict):
                continue
            host = _g(a, "host", "name", default="?")
            cat = _g(a, "category")
            reach = _g(a, "reachability", "reach")
            verdict = _g(a, "verdict")
            ev = a.get("evidence") if isinstance(a.get("evidence"), dict) else {}
            tech = ev.get("tech") if isinstance(ev, dict) else None
            tech_s = ", ".join(tech) if isinstance(tech, list) else (tech or "")
            url = _g(a, "url")
            out.append(f"| {host} | {cat} | {reach} | {verdict} | {tech_s} | {url} |")
        out.append("")

    eps = recon.get("entry_points")
    if isinstance(eps, list) and eps:
        out.append("## Entry Points")
        out.append("")
        for e in eps:
            if not isinstance(e, dict):
                continue
            host = _g(e, "host", default="?")
            types = e.get("types")
            types_s = "/".join(types) if isinstance(types, list) else (types or "")
            reach = _g(e, "reachability", "reach")
            title = _g(e, "title")
            note = _g(e, "note")
            out.append(f"- **{host}** [{types_s}] reach={reach}"
                       + (f' title="{title}"' if title else "")
                       + (f" — {note}" if note else ""))
        out.append("")

    nh = recon.get("needs_human")
    if isinstance(nh, list) and nh:
        out.append("## Needs Human (recon 标记待人工终裁)")
        out.append("")
        for h in nh:
            out.append(f"- {h}")
        out.append("")

    vt = recon.get("verification_tasks")
    if isinstance(vt, list) and vt:
        out.append("## Verification Tasks (recon 建议)")
        out.append("")
        for t in vt:
            if isinstance(t, dict):
                out.append(f"- [{_g(t,'priority')}] {_g(t,'host')}: {_g(t,'action')}")
            else:
                out.append(f"- {t}")
        out.append("")

    # 可达性矩阵: recon 视角 ≠ 你出口视角(本框架核心教训之一)。
    if isinstance(assets, list) and assets:
        out.append("## Reachability Matrix")
        out.append("")
        out.append("> recon-reach 是报告生成视角; mine 由你从本出口探测后回填。两者可不同"
                   "(如境内资产对境外出口超时), 缺口即需中继/代理的信号。")
        out.append("")
        out.append("| host | recon-reach | mine (probe 后回填) |")
        out.append("|------|-------------|----------------------|")
        for a in assets:
            if isinstance(a, dict):
                out.append(f"| {_g(a,'host',default='?')} | "
                           f"{_g(a,'reachability','reach')} | ? |")
        out.append("")

    # 未知 schema 降级
    if not any(isinstance(recon.get(k), list) for k in ("assets", "entry_points")):
        out.append("## (未识别 schema — 顶层键概览)")
        out.append("")
        for k, v in recon.items():
            kind = type(v).__name__
            n = f"[{len(v)}]" if isinstance(v, (list, dict)) else ""
            out.append(f"- `{k}`: {kind}{n}")
        out.append("")

    return "\n".join(out)


def main() -> int:
    ap = argparse.ArgumentParser(description="把 recon JSON 折成 surface 摘要")
    ap.add_argument("recon", help="recon JSON 路径")
    ap.add_argument("--out", default=None, help="写入文件(默认打到 stdout)")
    args = ap.parse_args()

    p = Path(args.recon)
    try:
        recon = json.loads(p.read_text(encoding="utf-8"))
    except Exception as e:
        print(f"[ingest] 读取/解析失败: {e}", file=sys.stderr)
        return 1
    if not isinstance(recon, dict):
        print("[ingest] 顶层不是 JSON 对象, 无法折叠", file=sys.stderr)
        return 1

    md = render(recon, str(p))
    if args.out:
        op = Path(args.out)
        op.parent.mkdir(parents=True, exist_ok=True)
        op.write_text(md, encoding="utf-8")
        print(f"[ingest] 写入 {op} ({len(md)} bytes)")
    else:
        print(md)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
