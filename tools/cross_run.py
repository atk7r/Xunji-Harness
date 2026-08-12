#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""跨运行知识积累 —— 扫描所有 runs/ 按 barrier / product / mechanism 聚合历史攻击结论。

每个 run 的失败和成功不是孤立的——同一个 barrier class 在 target A 上被绕过的方式,
在 target B 上可能直接复用。本工具让过去的运行经验可查询, 避免"每次遇到同一个 barrier
都从零推理"。

CLI 用法:
  .venv/bin/python tools/cross_run.py                          # 全量摘要
  .venv/bin/python tools/cross_run.py --barrier WAF-layer     # 按 barrier 查询
  .venv/bin/python tools/cross_run.py --product nginx         # 按产品查询
  .venv/bin/python tools/cross_run.py --mechanism SQLi        # 按机制查询
  .venv/bin/python tools/cross_run.py --run puffts_20260702   # 单 run 摘要
  .venv/bin/python tools/cross_run.py --suggest barrier-class
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

ROOT = Path(__file__).resolve().parents[1]
RUNS_DIR = ROOT / "runs"
HWS = r"[^\S\n]"


# ---------------------------------------------------------------------------
# 数据提取: 从单个 run 目录提取结构化信息
# ---------------------------------------------------------------------------

def _field(text: str, name: str) -> str:
    """从 markdown 块中提取 `- Name: value` 字段值(单行)。"""
    m = re.search(rf"(?im)^{HWS}*[-*]?{HWS}*{re.escape(name)}{HWS}*[:：]{HWS}*([^\n]*)", text)
    return m.group(1).strip() if m else ""


def _parse_front_blocks(text: str) -> list[dict]:
    """解析 frontier.md 中所有 ### F-XXX 块。"""
    blocks: list[dict] = []
    for m in re.finditer(r"(?ms)^###[ \t]+(F-\d+[a-z]*).*?(?=^###[ \t]+F-\d+[a-z]*|\Z)", text):
        block_text = m.group(0)
        fid = m.group(1)
        status = _field(block_text, "Status")
        barrier = _field(block_text, "Barrier class")
        vectors = _field(block_text, "Vectors tried")
        front_desc = _field(block_text, "Front")
        evidence_field = _field(block_text, "Evidence")
        evidence_refs = re.findall(r"E-\d+[a-z]*", evidence_field)

        # 提取同barrier失败次数
        same_barrier_raw = _field(block_text, "Same barrier failures")
        same_barrier = 0
        if same_barrier_raw:
            try:
                same_barrier = int(re.search(r"\d+", same_barrier_raw).group())
            except Exception:
                pass

        blocks.append({
            "id": fid,
            "status": status,
            "barrier_class": barrier if barrier else "none",
            "vectors_tried": vectors,
            "front_desc": front_desc,
            "evidence_refs": evidence_refs,
            "same_barrier_failures": same_barrier,
        })
    return blocks


def _parse_evidence_entries(text: str) -> list[dict]:
    """解析 evidence.md 中所有 E-xxx 条目。"""
    entries: list[dict] = []
    for m in re.finditer(r"(?ms)^##[ \t]+(E-\d+[a-z]*).*?(?=^##[ \t]+E-\d+[a-z]*|\Z)", text):
        block = m.group(0)
        eid = m.group(1)
        maturity = _field(block, "Maturity")
        certainty_str = _field(block, "Certainty")
        result = _field(block, "Result")
        action = _field(block, "Action")
        severity = _field(block, "Severity")

        certainty = None
        try:
            certainty = float(certainty_str)
        except Exception:
            pass

        mechanism_classes = _extract_mechanism_classes(block)

        entries.append({
            "id": eid,
            "maturity": maturity,
            "certainty": certainty,
            "result": result,
            "action": action,
            "severity": severity,
            "mechanism_classes": mechanism_classes,
        })
    return entries


_MECHANISM_LABELS: dict[str, str] = {
    r"\bSQLi\b": "SQLi",
    r"\bNoSQLi\b": "NoSQLi",
    r"\bSSTI\b": "SSTI",
    r"\bSSRF\b": "SSRF",
    r"\bIDOR\b": "IDOR",
    r"\bXXE\b": "XXE",
    r"\bCSRF\b": "CSRF",
    r"\bXSS\b": "XSS",
    r"\bCORS\b": "CORS",
    r"auth.bypass": "auth-bypass",
    r"path.travers": "path-traversal",
    r"directory.travers": "directory-traversal",
    r"OS command injection": "OS-command-injection",
    r"command injection": "command-injection",
    r"deserialization": "deserialization",
    r"user.enum": "user-enum",
    r"brute.force": "brute-force",
    r"default.cred": "default-credentials",
    r"privilege.escalation": "privilege-escalation",
    r"\bJWT\b": "JWT",
    r"\bupload\b": "upload",
    r"open.redirect": "open-redirect",
    r"host.injection": "host-injection",
    r"request.smuggling": "request-smuggling",
    r"race.condition": "race-condition",
    r"\bTOCTOU\b": "TOCTOU",
    r"mass.assignment": "mass-assignment",
    r"\bRCE\b": "RCE",
    r"getshell": "getshell",
    r"source.leak": "source-leak",
    r"information.disclosure": "information-disclosure",
}


def _extract_mechanism_classes(text: str) -> list[str]:
    """从文本中提取机制类关键词，返回干净标签。"""
    classes = set()
    for pat, label in _MECHANISM_LABELS.items():
        if re.search(pat, text, re.I):
            classes.add(label)
    return sorted(classes)


def _parse_constraint_entries(text: str) -> list[dict]:
    """解析 constraints.md 中所有 C-xxx 条目。"""
    constraints: list[dict] = []
    for m in re.finditer(r"(?ms)^##[ \t]+(C-\d+).*?(?=^##[ \t]+C-\d+|\Z)", text):
        block = m.group(0)
        constraints.append({
            "id": m.group(1),
            "front": _field(block, "Front"),
            "mechanism_class": _field(block, "Mechanism class"),
            "why_blocked": _field(block, "Why blocked"),
            "ruled_out": _field(block, "Ruled out"),
        })
    return constraints


def _normalize_barrier(barrier: str) -> str:
    """归一化 barrier class —— 去掉括号内的细节注解, 统一为 canonical 前缀。"""
    if not barrier or barrier == "none":
        return "none"
    # 去掉 markdown 加粗/斜体标记 (*, **, ***)
    b = re.sub(r"\*+", "", barrier)
    # 去掉括号及其内容
    b = re.sub(r"\s*[(（][^)）]*[)）]", "", b).strip()
    # 去掉尾部的细节描述 (如 " + WAF-layer" 拆成两个)
    # 只取第一个 -layer 前缀作为主类
    m = re.match(r"([a-zA-Z]+-layer)", b)
    if m:
        return m.group(1).lower()
    # 中文 "未知" → none
    if b.strip() == "未知":
        return "none"
    # 常见变体映射
    aliases = {
        "auth": "auth-layer", "auth layer": "auth-layer",
        "waf": "waf-layer", "waf layer": "waf-layer",
        "app": "app-layer", "app layer": "app-layer",
        "routing": "routing-layer", "routing layer": "routing-layer",
        "network": "network-layer", "network layer": "network-layer",
        "crypto": "crypto-layer", "crypto layer": "crypto-layer",
        "credential": "credential-layer", "credential layer": "credential-layer",
        "scope": "scope-credential-layer",
        "ip": "network-layer",
    }
    key = b.lower().strip()
    for alias, canonical in aliases.items():
        if key.startswith(alias):
            return canonical
    # 宽泛匹配：包含 "-layer" 则直接返回小写
    if "-layer" in key:
        return key
    return key


def _extract_product_hints(text: str) -> list[str]:
    """从文本中提取产品/技术栈线索。"""
    hints = set()
    patterns = [
        r"nginx/[\d.]+", r"IIS\s+[\d.]+", r"Apache/[\d.]+", r"Tomcat/[\d.]+",
        r"DedeCMS", r"WordPress", r"Drupal", r"Joomla",
        r"Shiro", r"Struts", r"Spring", r"WebLogic", r"WebSphere",
        r"fastjson", r"Log4j", r"ThinkPHP", r"Laravel", r"Django",
        r"RuoYi", r"若依", r"Nacos", r"Druid", r"Swagger",
        r"致远", r"用友", r"金蝶", r"泛微", r"通达",
        r"神州浩天", r"正方", r"强智", r"青果",
        r"ASP\.NET", r"PHP", r"Java", r"Go", r"Python",
        r"jQuery", r"React", r"Vue", r"Angular",
        r"CloudFlare", r"安全狗", r"云锁", r"D盾",
    ]
    for pat in patterns:
        found = re.findall(pat, text, re.I)
        for f in found:
            hints.add(f)
    # 按小写去重，保留最精确版本
    deduped: dict[str, str] = {}
    for h in sorted(hints):
        key = h.lower()
        if key not in deduped or len(h) > len(deduped[key]):
            deduped[key] = h
    return sorted(deduped.values())


def extract_run(run_dir: Path) -> dict | None:
    """从单个 run 目录提取结构化摘要。返回 None 如果 run 太稀疏。"""
    slug = run_dir.name

    # frontier.md
    fr = run_dir / "frontier.md"
    if not fr.exists():
        return None
    frontier_text = fr.read_text(encoding="utf-8", errors="replace")
    fronts = _parse_front_blocks(frontier_text)

    # evidence.md
    ev = run_dir / "evidence.md"
    evidence = []
    evidence_text = ""
    if ev.exists():
        evidence_text = ev.read_text(encoding="utf-8", errors="replace")
        evidence = _parse_evidence_entries(evidence_text)

    # constraints.md
    ct = run_dir / "constraints.md"
    constraints = []
    if ct.exists():
        ct_text = ct.read_text(encoding="utf-8", errors="replace")
        constraints = _parse_constraint_entries(ct_text)

    # target.md
    target = run_dir / "target.md"
    target_text = ""
    if target.exists():
        target_text = target.read_text(encoding="utf-8", errors="replace")

    # 产品指纹: 从 target.md + frontier.md 提取
    products = _extract_product_hints(target_text + "\n" + frontier_text)

    # 汇总: barrier class → fronts (归一化)
    barrier_map: dict[str, list[dict]] = {}
    for fb in fronts:
        bc_raw = fb.get("barrier_class", "none")
        bc = _normalize_barrier(bc_raw)
        fb["barrier_class_normalized"] = bc  # 存入归一化值供 build_barrier_index 使用
        barrier_map.setdefault(bc, []).append(fb)

    # 汇总: 已确认发现
    confirmed = [e for e in evidence if e.get("maturity") == "finding" and (e.get("certainty") or 0) >= 0.8]

    # 汇总: 约束中的机制类
    mechanism_classes = set()
    for c in constraints:
        mc = c.get("mechanism_class", "")
        if mc:
            mechanism_classes.add(mc)
    for e in evidence:
        for mc in e.get("mechanism_classes", []):
            mechanism_classes.add(mc)

    # 阶段
    phase = "unknown"
    if re.search(r"(?i)阶段\s*[:：]\s*Driver|Driver.*phase", target_text + frontier_text):
        phase = "Driver"
    elif re.search(r"(?i)阶段\s*[:：]\s*Hunter|Hunter.*phase", target_text + frontier_text):
        phase = "Hunter"
    elif re.search(r"(?i)阶段\s*[:：]\s*Reviewer|Reviewer.*phase|FINAL", target_text + frontier_text):
        phase = "Reviewer"

    return {
        "slug": slug,
        "phase": phase,
        "front_count": len(fronts),
        "open_fronts": len([f for f in fronts if f["status"] in ("open", "probing")]),
        "blocked_fronts": len([f for f in fronts if "blocked_type" in f.get("status", "")]),
        "deferred_fronts": len([f for f in fronts if f["status"] == "deferred"]),
        "closed_fronts": len([f for f in fronts if f["status"] == "closed"]),
        "confirmed_count": len(confirmed),
        "constraint_count": len(constraints),
        "products": products,
        "barrier_classes": list(barrier_map.keys()),
        "barrier_map": {bc: [f["id"] for f in fbs] for bc, fbs in barrier_map.items()},
        "fronts": fronts,
        "confirmed": confirmed,
        "mechanism_classes": sorted(mechanism_classes),
        "constraints": constraints,
    }


# ---------------------------------------------------------------------------
# 跨运行聚合
# ---------------------------------------------------------------------------

def scan_all_runs() -> list[dict]:
    """扫描所有 runs/ 目录, 返回按时间排序的 run 摘要列表。"""
    runs: list[dict] = []
    if not RUNS_DIR.exists():
        return runs

    for d in sorted(RUNS_DIR.iterdir()):
        if not d.is_dir():
            continue
        # 跳过非 run 目录 (如 .DS_Store)
        if d.name.startswith("."):
            continue
        data = extract_run(d)
        if data:
            runs.append(data)
    return runs


def build_barrier_index(runs: list[dict]) -> dict[str, list[dict]]:
    """按 barrier class 聚合所有 run 的历史记录。"""
    idx: dict[str, list[dict]] = {}
    for r in runs:
        for bc in r["barrier_classes"]:
            entry = {
                "run": r["slug"],
                "phase": r["phase"],
                "fronts": r["barrier_map"].get(bc, []),
                "confirmed_count": r["confirmed_count"],
                "constraint_count": r["constraint_count"],
            }
            # 收集该 barrier 相关 front 的详细状态（使用归一化 barrier class）
            related_fronts = [f for f in r["fronts"]
                            if f.get("barrier_class_normalized") == bc]
            entry["blocked_count"] = len([f for f in related_fronts if "blocked_type" in f.get("status", "")])
            entry["success_count"] = len([f for f in related_fronts if f["status"] == "closed" and f.get("evidence_refs")])
            entry["total_same_barrier_failures"] = sum(f.get("same_barrier_failures", 0) for f in related_fronts)
            idx.setdefault(bc, []).append(entry)
    return idx


def build_product_index(runs: list[dict]) -> dict[str, list[dict]]:
    """按产品指纹聚合（key 归一化为小写，保留最长精确形式作为显示名）。"""
    # _display: 收集每个小写 key 的所有原始形式，取最长的作为显示名
    _display: dict[str, str] = {}
    _entries: dict[str, list[dict]] = {}
    for r in runs:
        for prod in r["products"]:
            key = prod.lower()
            _display[key] = prod if key not in _display or len(prod) > len(_display[key]) else _display[key]
            _entries.setdefault(key, []).append({
                "run": r["slug"],
                "phase": r["phase"],
                "confirmed_count": r["confirmed_count"],
                "barrier_classes": r["barrier_classes"],
            })
    return {_display[k]: v for k, v in _entries.items()}


def build_mechanism_index(runs: list[dict]) -> dict[str, list[dict]]:
    """按机制类聚合。"""
    idx: dict[str, list[dict]] = {}
    for r in runs:
        for mc in r["mechanism_classes"]:
            # 从约束和证据中提取该机制类的结果
            constraint_info = [c for c in r["constraints"] if mc.lower() in c.get("mechanism_class", "").lower()]
            confirmed_info = [e for e in r["confirmed"] if any(mc.lower() in m.lower() for m in e.get("mechanism_classes", []))]
            idx.setdefault(mc, []).append({
                "run": r["slug"],
                "phase": r["phase"],
                "constraints_for_mechanism": len(constraint_info),
                "confirmed_for_mechanism": len(confirmed_info),
                "blocked_reasons": [c.get("why_blocked", "") for c in constraint_info],
            })
    return idx


# ---------------------------------------------------------------------------
# 输出格式化
# ---------------------------------------------------------------------------

def _run_short(slug: str) -> str:
    """截短 run slug 用于显示。"""
    parts = slug.split("_")
    if len(parts) >= 2:
        return parts[0]
    return slug


def print_summary(runs: list[dict]) -> int:
    """全量跨运行摘要。"""
    if not runs:
        print("[cross_run] runs/ 目录为空或无有效 run")
        return 0

    barrier_idx = build_barrier_index(runs)
    product_idx = build_product_index(runs)
    mechanism_idx = build_mechanism_index(runs)

    total_confirmed = sum(r["confirmed_count"] for r in runs)
    total_constraints = sum(r["constraint_count"] for r in runs)

    print(f"[cross_run] {len(runs)} 个 run, {total_confirmed} 个 confirmed finding, "
          f"{total_constraints} 条约束, {len(barrier_idx)} 种 barrier class, "
          f"{len(product_idx)} 个产品指纹, {len(mechanism_idx)} 种机制类\n")

    # === Barrier Class 维度 ===
    print("═" * 60)
    print("Barrier Class 维度 —— 同一种障碍在不同 target 上的表现")
    print("═" * 60)
    for bc in sorted(barrier_idx.keys()):
        entries = barrier_idx[bc]
        runs_with_barrier = len(entries)
        total_failures = sum(e["total_same_barrier_failures"] for e in entries)
        blocked = sum(e["blocked_count"] for e in entries)

        # 判断历史结论
        if blocked >= runs_with_barrier and runs_with_barrier >= 2:
            verdict = "历史一致: 该 barrier 在所有 target 上都导致 Type B 降级 —— 高概率为硬障碍"
        elif blocked > 0:
            verdict = f"混合: {blocked}/{runs_with_barrier} 的 run 中导致 Type B"
        else:
            verdict = "无降级记录"

        print(f"\n## {bc} ({runs_with_barrier} runs, {total_failures} failures)")
        print(f"  结论: {verdict}")
        for e in entries:
            print(f"  - {e['run']}: {e['blocked_count']} blocked fronts, "
                  f"{e['total_same_barrier_failures']} same-barrier failures")

    # === Product 维度 ===
    print(f"\n{'═' * 60}")
    print("Product 维度 —— 同一产品在不同 target 上的发现")
    print("═" * 60)
    for prod in sorted(product_idx.keys()):
        entries = product_idx[prod]
        runs_with_product = len(entries)
        confirmed = sum(e["confirmed_count"] for e in entries)
        print(f"\n## {prod} ({runs_with_product} runs, {confirmed} confirmed)")
        for e in entries:
            barriers = ", ".join(e["barrier_classes"][:3]) if e["barrier_classes"] else "none"
            print(f"  - {e['run']}: {e['confirmed_count']} findings, barriers: {barriers}")

    # === Mechanism Class 维度 ===
    print(f"\n{'═' * 60}")
    print("Mechanism Class 维度 —— 同一漏洞类别在不同 target 上的成功率")
    print("═" * 60)
    for mc in sorted(mechanism_idx.keys()):
        entries = mechanism_idx[mc]
        runs_with_mechanism = len(entries)
        confirmed_count = sum(e["confirmed_for_mechanism"] for e in entries)
        blocked_count = sum(e["constraints_for_mechanism"] for e in entries)

        if confirmed_count > 0:
            verdict = f"有成果: {confirmed_count} 次确认发现"
        elif blocked_count > 0:
            verdict = f"仅受阻: {blocked_count} 条约束, 0 确认"
        else:
            verdict = "仅提及, 无确认/约束记录"

        print(f"\n## {mc} ({runs_with_mechanism} runs)")
        print(f"  结论: {verdict}")
        for e in entries:
            detail = f"{e['run']}: confirmed={e['confirmed_for_mechanism']}, constraints={e['constraints_for_mechanism']}"
            if e["blocked_reasons"]:
                unique_reasons = list(set(e["blocked_reasons"]))[:3]
                detail += f", blocked_by: {', '.join(unique_reasons)}"
            print(f"  - {detail}")

    return 0


def print_barrier_query(runs: list[dict], barrier_class: str) -> int:
    """查询特定 barrier class 的跨运行历史。"""
    barrier_idx = build_barrier_index(runs)

    # 归一化查询参数后再做模糊匹配（索引 key 已归一化）
    query_norm = _normalize_barrier(barrier_class).lower()
    matched = {}
    for bc, entries in barrier_idx.items():
        if query_norm in bc.lower() or barrier_class.lower() in bc.lower():
            matched[bc] = entries

    if not matched:
        print(f"[cross_run] 未找到 barrier class 匹配 '{barrier_class}'")
        print(f"已知 barrier class: {', '.join(sorted(barrier_idx.keys()))}")
        return 1

    for bc, entries in matched.items():
        print(f"\n## Barrier: {bc} ({len(entries)} runs)")
        for e in entries:
            print(f"\n### {e['run']}")
            print(f"  Phase: {e['phase']}")
            print(f"  Fronts with this barrier: {', '.join(e['fronts'])}")
            print(f"  Blocked count: {e['blocked_count']}")
            print(f"  Total same-barrier failures: {e['total_same_barrier_failures']}")
            print(f"  Confirmed findings (entire run): {e['confirmed_count']}")

            # 如果有绕过成功的情况, 标注
            if e["success_count"] > 0:
                print(f"  >>> BYPASS FOUND: {e['success_count']} fronts with this barrier were successfully closed")

    return 0


def print_product_query(runs: list[dict], product: str) -> int:
    """查询特定产品的跨运行历史。"""
    product_idx = build_product_index(runs)

    matched = {}
    for prod, entries in product_idx.items():
        if product.lower() in prod.lower():
            matched[prod] = entries

    if not matched:
        print(f"[cross_run] 未找到产品匹配 '{product}'")
        return 1

    for prod, entries in matched.items():
        print(f"\n## Product: {prod} ({len(entries)} runs)")
        for e in entries:
            print(f"  - {e['run']}: phase={e['phase']}, "
                  f"confirmed={e['confirmed_count']}, "
                  f"barriers: {', '.join(e['barrier_classes'][:5])}")

    return 0


def print_mechanism_query(runs: list[dict], mechanism: str) -> int:
    """查询特定机制类的跨运行历史。"""
    mechanism_idx = build_mechanism_index(runs)

    matched = {}
    for mc, entries in mechanism_idx.items():
        if mechanism.lower() in mc.lower():
            matched[mc] = entries

    if not matched:
        print(f"[cross_run] 未找到机制类匹配 '{mechanism}'")
        return 1

    for mc, entries in matched.items():
        total_confirmed = sum(e["confirmed_for_mechanism"] for e in entries)
        total_blocked = sum(e["constraints_for_mechanism"] for e in entries)
        print(f"\n## Mechanism: {mc} ({len(entries)} runs, {total_confirmed} confirmed, {total_blocked} blocked)")
        for e in entries:
            print(f"  - {e['run']}: confirmed={e['confirmed_for_mechanism']}, constraints={e['constraints_for_mechanism']}")

    return 0


def print_run_detail(runs: list[dict], run_slug: str) -> int:
    """单 run 详细摘要。"""
    for r in runs:
        if run_slug in r["slug"]:
            print(f"## {r['slug']}")
            print(f"  Phase: {r['phase']}")
            print(f"  Fronts: {r['front_count']} total ({r['open_fronts']} open, "
                  f"{r['blocked_fronts']} blocked, {r['deferred_fronts']} deferred, "
                  f"{r['closed_fronts']} closed)")
            print(f"  Confirmed findings: {r['confirmed_count']}")
            print(f"  Constraints: {r['constraint_count']}")
            print(f"  Products: {', '.join(r['products']) if r['products'] else '(none detected)'}")
            print(f"  Barrier classes: {', '.join(r['barrier_classes']) if r['barrier_classes'] else 'none'}")
            print(f"  Mechanism classes: {', '.join(r['mechanism_classes']) if r['mechanism_classes'] else 'none'}")

            if r["confirmed"]:
                print(f"\n  Confirmed findings:")
                for c in r["confirmed"]:
                    sev = c.get("severity", "?")
                    print(f"    {c['id']}: {c.get('result', '?')[:100]} (certainty={c['certainty']}, severity={sev})")

            if r["constraints"]:
                print(f"\n  Constraints:")
                for c in r["constraints"]:
                    print(f"    {c['id']}: {c['mechanism_class']} — {c['ruled_out'][:80]}")

            return 0

    print(f"[cross_run] 未找到 run 匹配 '{run_slug}'")
    return 1


def print_suggest(runs: list[dict], dimension: str) -> int:
    """输出建议列表, 供 context_pack.py 或 Root 消费。"""
    if dimension == "barrier-class":
        barrier_idx = build_barrier_index(runs)
        for bc in sorted(barrier_idx.keys()):
            entries = barrier_idx[bc]
            print(f"{bc}: {len(entries)} runs, {sum(e['total_same_barrier_failures'] for e in entries)} failures")
    elif dimension == "product":
        product_idx = build_product_index(runs)
        for prod in sorted(product_idx.keys()):
            entries = product_idx[prod]
            print(f"{prod}: {len(entries)} runs, {sum(e['confirmed_count'] for e in entries)} confirmed")
    elif dimension == "mechanism":
        mechanism_idx = build_mechanism_index(runs)
        for mc in sorted(mechanism_idx.keys()):
            entries = mechanism_idx[mc]
            confirmed = sum(e["confirmed_for_mechanism"] for e in entries)
            blocked = sum(e["constraints_for_mechanism"] for e in entries)
            print(f"{mc}: {len(entries)} runs, {confirmed} confirmed, {blocked} blocked")
    else:
        print(f"[cross_run] 未知维度 '{dimension}', 可用: barrier-class, product, mechanism")
        return 1
    return 0


# ---------------------------------------------------------------------------
# CLI 入口
# ---------------------------------------------------------------------------

def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)

    ap = argparse.ArgumentParser(description="跨运行知识积累 —— 按 barrier/product/mechanism 聚合历史攻击结论")
    ap.add_argument("--barrier", metavar="CLASS", help="按 barrier class 查询")
    ap.add_argument("--product", metavar="NAME", help="按产品指纹查询")
    ap.add_argument("--mechanism", metavar="CLASS", help="按机制类查询")
    ap.add_argument("--run", metavar="SLUG", help="单 run 详细摘要")
    ap.add_argument("--suggest", metavar="DIMENSION", help="列出维度下所有已知值 (barrier-class/product/mechanism)")
    ap.add_argument("--json", action="store_true", help="输出 JSON 而非文本（供其他工具消费）")
    args = ap.parse_args(argv)

    runs = scan_all_runs()

    # --json: 返回结构化数据供 context_pack / graph 等工具消费
    if args.json:
        import json as _json
        barrier_idx = build_barrier_index(runs)
        product_idx = build_product_index(runs)
        mechanism_idx = build_mechanism_index(runs)
        result = {
            "total_runs": len(runs),
            "barrier_index": {bc: entries for bc, entries in barrier_idx.items() if bc != "none"},
            "product_index": {p: entries for p, entries in product_idx.items()},
            "mechanism_index": {m: entries for m, entries in mechanism_idx.items()},
        }
        print(_json.dumps(result, ensure_ascii=False, indent=2))
        return 0

    if args.barrier:
        return print_barrier_query(runs, args.barrier)
    if args.product:
        return print_product_query(runs, args.product)
    if args.mechanism:
        return print_mechanism_query(runs, args.mechanism)
    if args.run:
        return print_run_detail(runs, args.run)
    if args.suggest:
        return print_suggest(runs, args.suggest)

    return print_summary(runs)


if __name__ == "__main__":
    raise SystemExit(main())
