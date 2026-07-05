#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""graph.py — 把 run 的隐式因果显式化成一个【派生的、可查询的状态图】。

原理: hypotheses/frontier/evidence 早已是节点(H/F/E-xxx), 但它们之间的边——尤其
"某已确认 Fact 解锁某前沿"——散在散文里, 每轮 Reason pass 都得在脑子里重拼。本工具把这些
边解析成图, 输出派生视图(可打 / 被解锁却晾着的 deferred / 关了却被解锁的矛盾 / 悬挂 Fact /
孤儿假设 / 确认链), 让"什么被解锁了、什么找到了没跟进"从【靠脑子记】变成【一次查询】。

边的来源(复用现有字段, 只有 Unlocked-by/Unlocks 是新增的条件字段):
  - evidence  `Supports:`     E -> H/F   (确认假设 / 支撑前沿)
  - evidence  `Refutes:`      E -> E     (证伪, 已有)
  - evidence  `Unlocks:`      E -> F     (确认即解锁某前沿, 新增条件字段)
  - front     `Linked hypotheses:` F -> H (在测哪个假设, 已有)
  - front     `Unlocked-by:`  E -> F     (此前沿被某 Fact 解锁, 新增条件字段)
前沿状态由它所在的 ## Open/Deferred/Closed Fronts 区段决定。已确认 Fact = E 且 certainty>=0.8。

【护栏】图只【派生 + 建议】, 永不自主驱动或收口 —— 一旦它"决定下一步"就退化成被删过的
JSON 编排器(check_rules 盯着的那个)。选哪个前沿永远是 driver 判断; 图只是把当前状态摆出来。

  python tools/graph.py runs/<dir>     # 写 <run>/graph.json + 打印派生视图
只读本地 run 文件; 不联网、不走 guard。check_run.py 复用本模块做图一致性软警告。
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8")       # type: ignore[attr-defined]
except Exception:
    pass

ROOT = Path(__file__).resolve().parents[1]
CONFIRMED = 0.8  # certainty 门: >= 此值才算 Fact(已确认)


def _blocks(text: str, head_re: str) -> list[tuple[str, str]]:
    """按 head 正则切块, 返回 [(id, block_text)]。"""
    out: list[tuple[str, str]] = []
    for b in re.split(rf"(?=^{head_re})", text, flags=re.MULTILINE):
        m = re.match(head_re, b.strip())
        if m:
            out.append((m.group(1), b))
    return out


def _ids(block: str, field: str, kind: str) -> list[str]:
    """抽某字段那一行里的 <kind>-<num> id 列表。"""
    line = re.search(rf"{field}\s*[:：]([^\n]*)", block)
    return re.findall(rf"{kind}-\d+[a-z]*", line.group(1)) if line else []


def build_graph(run_dir: Path) -> dict:
    nodes: dict[str, dict] = {}
    edges: list[dict] = []

    hp = run_dir / "hypotheses.md"
    if hp.exists():
        for hid, b in _blocks(hp.read_text(encoding="utf-8", errors="replace"), r"##\s+(H-\d+)"):
            st = re.search(r"Status\s*[:：]\s*([^\n]+)", b)
            nodes[hid] = {"type": "hypothesis", "status": st.group(1).strip() if st else ""}

    ev = run_dir / "evidence.md"
    if ev.exists():
        for eid, b in _blocks(ev.read_text(encoding="utf-8", errors="replace"), r"##\s+(E-\d+[a-z]*)"):
            cm = re.search(r"Certainty\s*[:：]\s*(\d\.\d)", b)
            nodes[eid] = {
                "type": "evidence",
                "certainty": float(cm.group(1)) if cm else 0.0,
                "superseded": bool(re.search(r"superseded|降级|撤回|改判", b, re.I)),
            }
            for t in _ids(b, "Supports", "H") + _ids(b, "Supports", "F"):
                edges.append({"src": eid, "dst": t, "rel": "supports"})
            for f in _ids(b, "Unlocks", "F"):
                edges.append({"src": eid, "dst": f, "rel": "unlocks"})
            for e2 in _ids(b, "Refutes", "E"):
                edges.append({"src": eid, "dst": e2, "rel": "refutes"})

    fr = run_dir / "frontier.md"
    if fr.exists():
        ftext = fr.read_text(encoding="utf-8", errors="replace")
        for sec, status in (("Open Fronts", "open"),
                            ("Deferred Fronts", "deferred"),
                            ("Closed Fronts", "closed")):
            m = re.search(rf"##\s*{sec}(.*?)(?=^##\s|\Z)", ftext, re.S | re.MULTILINE)
            if not m:
                continue
            for fid, b in _blocks(m.group(1), r"###\s+(F-\d+)"):
                nodes[fid] = {"type": "front", "status": status}
                for h in _ids(b, "Linked hypotheses", "H"):
                    edges.append({"src": fid, "dst": h, "rel": "tests"})
                for e in _ids(b, "Unlocked-by", "E"):
                    edges.append({"src": e, "dst": fid, "rel": "unlocks"})

    seen: set = set()
    uniq: list[dict] = []
    for e in edges:
        k = (e["src"], e["dst"], e["rel"])
        if k not in seen:
            seen.add(k)
            uniq.append(e)
    return {"nodes": nodes, "edges": uniq}


def _confirmed(nodes: dict, eid: str) -> bool:
    n = nodes.get(eid)
    return bool(n and n["type"] == "evidence"
                and n.get("certainty", 0.0) >= CONFIRMED and not n.get("superseded"))


def derive_view(g: dict, run_dir: Path | None = None) -> dict:
    nodes, edges = g["nodes"], g["edges"]
    unlocks = [(e["src"], e["dst"]) for e in edges if e["rel"] == "unlocks"]
    out_src = {e["src"] for e in edges}
    touched = {e["src"] for e in edges} | {e["dst"] for e in edges}

    unlocked_deferred: list[dict] = []
    closed_but_unlocked: list[dict] = []
    for src, dst in unlocks:
        fn = nodes.get(dst)
        if fn and fn["type"] == "front" and _confirmed(nodes, src):
            if fn["status"] == "deferred":
                unlocked_deferred.append({"front": dst, "by": src})
            elif fn["status"] == "closed":
                closed_but_unlocked.append({"front": dst, "by": src})

    dangling_facts = sorted(
        eid for eid, n in nodes.items()
        if n["type"] == "evidence" and _confirmed(nodes, eid) and eid not in out_src)

    orphan_hypotheses = sorted(
        hid for hid, n in nodes.items()
        if n["type"] == "hypothesis" and hid not in touched)

    actionable = sorted(
        {fid for fid, n in nodes.items() if n["type"] == "front" and n["status"] == "open"}
        | {u["front"] for u in unlocked_deferred})

    confirmed_chains = [{"from": s, "to": d} for s, d in unlocks if _confirmed(nodes, s)]

    # 从 coverage.json 提取事实层资产状态。调度/agent 角色建议属于 workers.py。
    high_value_idle: list[str] = []
    reachable_no_verdict: list[str] = []
    if run_dir:
        cov_path = run_dir / "classify" / "coverage.json"
        if cov_path.exists():
            import json as _json
            try:
                cov = _json.loads(cov_path.read_text(encoding="utf-8"))
                for a in cov.get("assets", []):
                    h = a.get("host", "")
                    if a.get("high_value") and not a.get("examined"):
                        high_value_idle.append(h)
                    if a.get("reachable") and a.get("verdict") is None and not a.get("examined"):
                        reachable_no_verdict.append(h)
            except Exception:
                pass

    return {
        "actionable": actionable,
        "unlocked_deferred": unlocked_deferred,
        "closed_but_unlocked": closed_but_unlocked,
        "dangling_facts": dangling_facts,
        "orphan_hypotheses": orphan_hypotheses,
        "confirmed_chains": confirmed_chains,
        "high_value_idle": high_value_idle,
        "reachable_no_verdict": reachable_no_verdict,
    }


def main() -> int:
    ap = argparse.ArgumentParser(description="派生 run 的类型化状态图(只建议, 不驱动)")
    ap.add_argument("run_dir", type=Path)
    args = ap.parse_args()
    run_dir = args.run_dir if args.run_dir.is_absolute() else ROOT / args.run_dir
    run_dir = run_dir.resolve()
    if not run_dir.exists():
        print(f"[graph] run 目录不存在: {run_dir}", file=sys.stderr)
        return 1

    g = build_graph(run_dir)
    view = derive_view(g, run_dir)
    out = run_dir / "graph.json"
    out.write_text(json.dumps({**g, "view": view}, ensure_ascii=False, indent=2),
                   encoding="utf-8")

    n_front = sum(1 for n in g["nodes"].values() if n["type"] == "front")
    n_ev = sum(1 for n in g["nodes"].values() if n["type"] == "evidence")
    n_hyp = sum(1 for n in g["nodes"].values() if n["type"] == "hypothesis")
    print(f"[graph] 节点: {n_front} 前沿 / {n_ev} 证据 / {n_hyp} 假设; 边 {len(g['edges'])} 条 → {out.name}")
    print(f"[graph] 可打前沿: {', '.join(view['actionable']) or '(无)'}")
    if view["unlocked_deferred"]:
        s = ", ".join(f"{u['front']}←{u['by']}" for u in view["unlocked_deferred"])
        print(f"  ⚠️ 被已确认 Fact 解锁却仍 deferred(该激活!): {s}")
    if view["closed_but_unlocked"]:
        s = ", ".join(f"{u['front']}←{u['by']}" for u in view["closed_but_unlocked"])
        print(f"  ⚠️ 已 Closed 却被已确认 Fact 解锁(矛盾, 该重开): {s}")
    if view["dangling_facts"]:
        print(f"  • 悬挂 Fact(确认了却不支撑/解锁/证伪任何东西, 找到没跟进?): {', '.join(view['dangling_facts'])}")
    if view["orphan_hypotheses"]:
        print(f"  • 孤儿假设(无任何边, 既没在测也没证据): {', '.join(view['orphan_hypotheses'])}")
    if view["confirmed_chains"]:
        s = ", ".join(f"{c['from']}→{c['to']}" for c in view["confirmed_chains"])
        print(f"  • 确认链(组合利用候选, 记进 chains.md): {s}")
    if view.get("high_value_idle"):
        print(f"  🔴 高价值资产未检视: {', '.join(view['high_value_idle'][:8])}")
    if view.get("reachable_no_verdict"):
        print(f"  🟡 可达但无裁决资产: {', '.join(view['reachable_no_verdict'][:8])}")
    print("[graph] 仅为派生事实视图; 调度建议由 workers.py suggest 生成, driver 仍负责判断。")

    # 写入轻量 workflow checkpoint —— 会话恢复和阶段追踪
    _write_checkpoint(run_dir, g)
    return 0


def _write_checkpoint(run_dir: Path, g: dict) -> None:
    """写入 state/workflow_checkpoint.json —— 轻量运行状态快照。
    不依赖外部框架, 约 15 行 JSON。Root graph pass 每次调用自动更新。"""
    import time as _time
    state_dir = run_dir / "state"
    state_dir.mkdir(parents=True, exist_ok=True)

    # 收集当前状态 —— 节点 type: front/evidence/hypothesis
    nodes = g.get("nodes", {})
    open_fronts = [nid for nid, nd in nodes.items()
                   if nd.get("type") == "front" and nd.get("status") in ("open", "probing")]
    deferred_fronts = [nid for nid, nd in nodes.items()
                       if nd.get("type") == "front" and nd.get("status") == "deferred"]
    blocked_fronts = [nid for nid, nd in nodes.items()
                      if nd.get("type") == "front" and "blocked_type" in str(nd.get("status", ""))]
    closed_fronts = [nid for nid, nd in nodes.items()
                     if nd.get("type") == "front" and nd.get("status") == "closed"]
    confirmed = [nid for nid, nd in nodes.items()
                 if nd.get("type") == "evidence" and (nd.get("certainty") or 0) >= 0.8]
    total_fronts = sum(1 for nd in nodes.values() if nd.get("type") == "front")

    # 推断当前阶段
    phase = "Driver"
    if not open_fronts and deferred_fronts:
        phase = "Reviewer"
    elif blocked_fronts and not open_fronts:
        phase = "Reviewer"
    elif confirmed and not open_fronts:
        phase = "Reviewer"

    checkpoint = {
        "updated_at": _time.strftime("%Y-%m-%dT%H:%M:%SZ", _time.gmtime()),
        "phase": phase,
        "open_fronts": open_fronts,
        "deferred_fronts": deferred_fronts,
        "blocked_fronts": blocked_fronts,
        "closed_fronts": closed_fronts,
        "confirmed_evidence": confirmed,
        "total_fronts": total_fronts,
        "last_graph_pass": _time.strftime("%Y-%m-%dT%H:%M:%SZ", _time.gmtime()),
    }

    path = state_dir / "workflow_checkpoint.json"
    path.write_text(json.dumps(checkpoint, ensure_ascii=False, indent=2), encoding="utf-8")


if __name__ == "__main__":
    raise SystemExit(main())
