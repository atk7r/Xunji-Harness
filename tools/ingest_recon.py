#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""ingest_recon.py — 把 recon/OSINT 报告折成 surface.md 可用的摘要。

实现 WORKFLOW.md「Ingest Existing Intelligence First」的机械部分: 读一份 recon JSON,
输出资产表 + 入口 + needs_human + **可达性矩阵**(recon 视角 vs 你出口视角), 并标注来源。
它只【结构化情报】, 不做选择/判断 —— front 选择仍是 driver 的事。

支持 osint_ai report_agent 的 schema(target/assets/entry_points/needs_human/
verification_tasks/infrastructure/stats), 未知 schema 则降级为顶层键概览。

  .venv/bin/python tools/ingest_recon.py <recon.json>     # 打到 stdout
  .venv/bin/python tools/ingest_recon.py <recon.json> --out runs/<t>/surface_recon.md
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))   # scope import(build_coverage 用)


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


# ── Guanlan → coverage 适配器(轴 B: 消费上游 OSINT 产物当台账, 零重探)─────────────────────
# Guanlan(观澜)已做: 去重(canonical_key)、通配 DNS 折叠、存活探测、归属分类、可达性分层。
# 框架【不再】用 classify_hosts 全量重探重建这些(= re-OSINT 的冤枉时间)。此适配器把 Guanlan 的
# classification.json(资产+归属+价值+类目)+ report.md(存活分层表)直接折成 coverage.json。

def _section_hosts(report_md: str | None, *keywords: str) -> set:
    """从 report.md 中【标题含任一 keyword】的段落抽 host/IP —— Guanlan 的存活分层(已确认可达/
    待验证/低质量)在 report.md 的表里。容错: 无 report 或无该段 → 空集(调用方据此降级)。"""
    if not report_md:
        return set()
    out: set = set()
    for sec in re.split(r"(?m)^#{1,6}\s+", report_md):
        head = (sec.splitlines() or [""])[0]
        if any(k in head for k in keywords):
            body = sec[len(head):].lower()
            for m in re.findall(r"(?:https?://)?\b([a-z0-9][a-z0-9.\-]*\.[a-z]{2,}|(?:\d{1,3}\.){3}\d{1,3})\b", body):
                out.add(m.strip(".").rstrip("/"))
    return out


_CATEGORY_FLAGS = {                       # Guanlan category → 深度门最小攻击面信号(grounding, 非盲标)
    "auth": ["LOGIN", "SURFACE:SSO"],
    "vpn": ["LOGIN"],
    "oa": ["SURFACE:ADMIN"],
    "admin": ["SURFACE:ADMIN"],
    "management": ["SURFACE:ADMIN"],
    "practice": ["SURFACE:ADMIN"],
}


def _asset_flags(a: dict) -> list[str]:
    """Carry recon's high-value/review/admin hints into coverage so closure gates
    can force a real E-entry instead of letting those assets disappear."""
    flags = list(_CATEGORY_FLAGS.get(str(a.get("category_id") or "").lower(), []))
    text = " ".join(str(a.get(k) or "") for k in (
        "asset", "host", "category", "category_id", "reason", "title", "note", "tags"))
    if a.get("is_high_value"):
        flags.append("HIGH_VALUE")
    if re.search(r"\[review\]", text, re.I):
        flags.append("REVIEW")
    if re.search(r"管理|后台|admin|仪器共享|实践教学", text, re.I):
        flags.append("SURFACE:ADMIN")
    if re.search(r"登录|login|auth|sso|idp", text, re.I):
        flags.append("LOGIN")
    out: list[str] = []
    for f in flags:
        if f and f not in out:
            out.append(f)
    return out


def _asset_id(host: str) -> str:
    return "ASSET-" + hashlib.sha1(host.lower().encode("utf-8")).hexdigest()[:12].upper()


def build_coverage(recon: dict, report_md: str | None = None) -> dict:
    """把 Guanlan 产物折成 coverage.json(零重探)。reachable 取 Guanlan『已确认可达』(只对【真可达】
    逼裁决, 不纠缠待验证/低质量 = 轴 B『别执着不可达』); 低质量→False; 其余→unknown。flags 从 category
    取最小信号(auth/vpn→LOGIN…)供深度门; 其余攻击面在渗透实打时补。out-of-scope(ownership=unrelated/
    third_party, 由 scope 派生)滤掉。examined=0(没探, 渗透时才『检视内容』)。"""
    import scope as _scope
    sc = _scope.derive_scope(recon)
    inp, outp = sc["in"], sc["out"]
    confirmed = _section_hosts(report_md, "已确认可达", "确认可达", "confirmed")
    lowq = _section_hosts(report_md, "低质量", "低質量", "low quality", "low-quality")
    assets: list = []
    excluded_assets: list = []
    seen: set = set()
    for a in (recon.get("assets") or []):
        if not isinstance(a, dict):
            continue
        h = _scope._asset_host(a)
        sv = _scope.in_scope(h, inp, outp) if h else "out"
        if not h or h in seen:
            continue
        seen.add(h)
        if sv == "out":
            excluded_assets.append({
                "asset_id": _asset_id(h),
                "host": h,
                "scope_status": "out",
                "reason": (a.get("reason") or a.get("ownership") or "scope rule")[:120],
                "source": "guanlan",
            })
            continue
        # reachable=True 只给【严格 in-scope】(sv=="in")的: 防无 ownership 的 recon 里 unknown-scope 的
        # 无关 host 一旦出现在『已确认可达』段就被标可达 → 逼裁决/被攻击(Codex 复审 WARN#1)。
        if sv == "in":
            reach = True if h in confirmed else (False if h in lowq else "unknown")
        else:
            reach = "unknown"
        assets.append({
            "asset_id": _asset_id(h), "host": h,
            "scope_status": "in" if sv == "in" else "review",
            "reachable": reach, "examined": False, "stack": "",
            "flags": _asset_flags(a),
            "ownership": a.get("ownership"), "high_value": bool(a.get("is_high_value")),
            "category": a.get("category_id"), "reason": (a.get("reason") or "")[:120],
            "source": "guanlan",
            # P0: Guanlan baseline + egress_recheck overlay
            "source_reachability": reach,
            "current_egress_reachability": None,
            "verdict": None,
        })
    reachable_n = sum(1 for c in assets if c["reachable"] is True)
    return {"source_total": len(seen), "excluded": len(excluded_assets),
            "excluded_assets": excluded_assets,
            "total": len(assets), "examined": 0, "reachable": reachable_n,
            "planned": len(assets), "partial": False, "assets": assets,
            "source": "guanlan-adapter(no re-probe)"}


def _selftest() -> int:
    """build_coverage 适配器回归(纯本地, 无网络): 存活分层映射 / scope 滤 / category flags / 零重探。"""
    recon = {"target": "ex.edu.cn", "assets": [
        {"asset": "auth.ex.edu.cn", "ownership": "core", "category_id": "auth", "is_high_value": True},
        {"asset": "www.ex.edu.cn", "ownership": "core", "category_id": "portal"},
        {"asset": "dead.ex.edu.cn", "ownership": "core", "category_id": "portal"},
        {"asset": "ies.ex.edu.cn", "ownership": "core", "category_id": "portal",
         "reason": "[review] 大型仪器共享管理平台", "is_high_value": True},
        {"asset": "spam.unrelated.com", "ownership": "unrelated"},
        {"asset": "0.vpn.ex.edu.cn", "ownership": "core", "category_id": "vpn"},
    ]}
    report = ("# R\n## 3. 已确认可达资产\n| auth.ex.edu.cn | 200 | t |\n| www.ex.edu.cn | 200 | t |\n"
              "| ies.ex.edu.cn | 200 | t |\n"
              "## 5. 低质量\n| dead.ex.edu.cn | 404 | |\n")
    cov = build_coverage(recon, report)
    h = {a["host"]: a for a in cov["assets"]}
    checks = [
        ("unrelated 滤出(不入 coverage)", "spam.unrelated.com" not in h),
        ("out-of-scope 资产仍在排除台账中可审计",
         cov["source_total"] == 6 and cov["excluded"] == 1
         and cov["excluded_assets"][0]["host"] == "spam.unrelated.com"),
        ("in-scope 资产有稳定 asset_id",
         all(re.fullmatch(r"ASSET-[0-9A-F]{12}", a.get("asset_id", "")) for a in cov["assets"])),
        ("已确认可达 → reachable True", h["auth.ex.edu.cn"]["reachable"] is True),
        ("低质量 → reachable False", h["dead.ex.edu.cn"]["reachable"] is False),
        ("待验证(不在 report)→ unknown(轴B: 不纠缠)", h["0.vpn.ex.edu.cn"]["reachable"] == "unknown"),
        ("auth category → LOGIN flag(供深度门)", "LOGIN" in h["auth.ex.edu.cn"]["flags"]),
        ("vpn category → LOGIN flag", "LOGIN" in h["0.vpn.ex.edu.cn"]["flags"]),
        ("[review]/高价值管理面 → REVIEW/HIGH_VALUE/SURFACE:ADMIN flags",
         all(f in h["ies.ex.edu.cn"]["flags"] for f in ("REVIEW", "HIGH_VALUE", "SURFACE:ADMIN"))),
        ("portal 无 flag", h["www.ex.edu.cn"]["flags"] == []),
        ("examined=0 全 False(零重探, 渗透时才检视)", cov["examined"] == 0 and all(a["examined"] is False for a in cov["assets"])),
        ("high_value 透传", h["auth.ex.edu.cn"]["high_value"] is True),
        ("source 标 guanlan-adapter", "guanlan" in cov["source"]),
        ("reachable 计数 = 已确认可达数(3)", cov["reachable"] == 3),
        ("无 report → 全 unknown(降级不崩)", all(a["reachable"] == "unknown" for a in build_coverage(recon, None)["assets"])),
    ]
    # Codex 复审 WARN#1: 无 ownership 的 recon, unknown-scope 无关 host 即便列在『已确认可达』也不标 reachable True
    recon2 = {"target": "ex.edu.cn", "assets": [
        {"asset": "ex.edu.cn", "category_id": "portal"},            # target 域族 → heuristic in
        {"asset": "evil.attacker.com", "category_id": "portal"}]}   # 无关 → heuristic unknown-scope
    rep2 = "# R\n## 已确认可达\n| ex.edu.cn | 200 | |\n| evil.attacker.com | 200 | |\n"
    h2 = {a["host"]: a for a in build_coverage(recon2, rep2)["assets"]}
    checks.append(("WARN#1: unknown-scope 无关 host 不标 reachable True(即便在已确认可达段)",
                   h2.get("evil.attacker.com", {}).get("reachable") is not True))
    bad = [n for n, ok in checks if not ok]
    for n, ok in checks:
        print(("ok   " if ok else "FAIL ") + n)
    print("ingest_recon selftest " + ("passed" if not bad else f"FAILED ({len(bad)})"))
    return 0 if not bad else 1


def main() -> int:
    ap = argparse.ArgumentParser(description="把 recon JSON 折成 surface 摘要")
    ap.add_argument("recon", nargs="?", help="recon JSON 路径")
    ap.add_argument("--out", default=None, help="写入文件(默认打到 stdout)")
    ap.add_argument("--selftest", action="store_true", help="run regression and exit")
    args = ap.parse_args()

    if args.selftest:
        return _selftest()
    if not args.recon:
        ap.error("need a recon JSON path (or --selftest)")

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
