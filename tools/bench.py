#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""bench.py — R-1 最小自评 harness: 给【已完成的 run】对照【fixture 真值】打分。

ROADMAP R-1(最高价值缺口): 一把尺子, 让框架改动可被 A/B —— 否则所有"改进"都只是
机制听起来合理(plausible mechanism != better)。本工具是那把尺子的 v0。

铁律(同 ROADMAP R-1 guardrail):
- **度量 driver, 绝不变成 driver**。它只读 run 产物打分, 不发包、不做攻击判断。
- **fixture 是良性已知漏洞靶**(DVWA / Juice Shop / 有意可漏容器 / 录制 run 的真值标注),
  **绝非真实交战**。真实目标发现物是红线, 不进 bench/。
- 打分是近似(按 marker 子串匹配确认条目), 用于"改动前后比对"和"回归", 不是裁决。

打分维度:
- detection  : 期望发现里被【确认条目】命中的比例(检出率)。
- calibration: 命中的发现 certainty 是否达 fixture 要求的下限(防欠证/过证)。
- false-pos  : must_not_flag 陷阱(非漏洞项)被误确认的数量。
- budget     : 录像 .replay.json 计数作"已记录请求"下界(尽力, 非精确)。
- process    : expected_process 断言 —— driver 有没有在对的时刻【调用某能力】(指纹检索 /
               fetch_assets / 独立复审 …)。detection/calibration 量"结果", 这维量"行为":
               接线类改动(本身不直接改检出)只有这维量得到。纯读产物, 不发包。
               schema: expected_process:[{id, signals:[子串], in?:[文件名], must?:true}]。
               signal 是子串匹配 —— 选【稳健的能力踪迹】(工具名 tools/knowledge_match / 产物标记),
               别选易变措辞: 否则会 false-fail(真触发却没留该串)或 false-confidence(巧合命中)。
- collaboration: expected_collaboration 断言 Ultra-native Agent Board 是否按预期协作
               (高价值 front 覆盖、冲突解决、每 Agent 请求预算、首证时间、误报压制)。
               一旦 fixture 声明 expected_collaboration, 这些 checks 会进入 clean 门；
               缺少必要观测数据(如 state/events.jsonl)会显式 skipped=false-ok, 不静默通过。

用法:
  python tools/bench.py score <run_dir> <truth.json>
  python tools/bench.py score-all bench/        # 跑 bench/ 下每个 <fixture>/truth.json(各指 run)
  python tools/bench.py compare baseline.json change.json
  python tools/bench.py --selftest
"""
from __future__ import annotations

import argparse
import json
import math
import re
import sys
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8")       # type: ignore[attr-defined]
except Exception:
    pass

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(Path(__file__).resolve().parent))   # tools/  (evidence_parse)
import evidence_parse  # noqa: E402  # tools/ is the standalone script import root.

_E_BLOCK = re.compile(r"(?ms)^##\s+(E-\d+[a-z]*).*?(?=^##\s+E-|\Z)")
_ATTRIBUTABLE_METRIC_EVENTS = {
    "request", "action", "evidence", "delegation", "assignment",
    "agent_start", "agent_stop", "agent_result", "review", "merge", "model",
}


def _confirmed_blocks(run_dir: Path) -> tuple[dict, dict, set]:
    """返回 ({确认 E-id: 块原文}, {E-id: 最大 certainty}, {正向确认 id})。确认性沿用
    evidence_parse.parse_evidence(certainty>=0.8); 块原文用于 marker 匹配。正向集 = 排除【纯负向
    (Refutes 且无 Supports)】—— 这类是 driver 正确地"没声称漏洞", 不能当成误报(同漏报门豁免)。"""
    recs = evidence_parse.parse_evidence(run_dir)
    confirmed = {r["id"] for r in recs if r["confirmed"] and r["id"].startswith("E-")}
    positive = {r["id"] for r in recs if r["id"] in confirmed
                and not (r["refutes_any"] and not r["supports"])}
    cert = {r["id"]: (max(r["certainties"]) if r["certainties"] else 0.0) for r in recs}
    ev = run_dir / "evidence.md"
    blocks: dict = {}
    if ev.exists():
        text = ev.read_text(encoding="utf-8", errors="replace")
        for m in _E_BLOCK.finditer(text):
            blocks[m.group(1)] = m.group(0)
    return {eid: blocks.get(eid, "") for eid in confirmed}, cert, positive


def _match(markers: list, blocks: dict) -> "str | None":
    """返回第一个【块文本含全部 marker(子串、大小写不敏感)】的确认 E-id, 否则 None。"""
    mks = [str(m).lower() for m in markers if str(m).strip()]
    if not mks:
        return None
    for eid, btext in blocks.items():
        bl = btext.lower()
        if all(mk in bl for mk in mks):
            return eid
    return None


_PROC_DEFAULT_FILES = ["decisions.md", "evidence.md", "review.md", "frontier.md", "report.md"]


def _process_check(run_dir: Path, asserts: list) -> list:
    """过程断言: 量"driver 有没有在对的时刻【调用某能力】"。bench 原本只量结果(检出/校准),
    接线类改动(把死功能接进触发)不直接改检出, 只能这维量得到 —— 否则"接线有没有真生效"不可见。
    每条断言 = 在指定 run 文件(默认核心 .md)里找全部 signals(子串, 大小写不敏感); 全中 = 该能力
    留下了踪迹。must=True(默认)未命中 → 计入回归门(_is_clean)。只读产物, 绝不发包。"""
    out = []
    for a in asserts:
        files = a.get("in") or _PROC_DEFAULT_FILES
        hay = ""
        for fn in files:
            p = run_dir / fn
            if p.exists():
                hay += "\n" + p.read_text(encoding="utf-8", errors="replace").lower()
        sigs = [str(s).lower() for s in a.get("signals", []) if str(s).strip()]
        out.append({"id": a.get("id"), "fired": bool(sigs) and all(s in hay for s in sigs),
                    "must": bool(a.get("must", True)), "signals": a.get("signals", [])})
    return out


def _timeline_metrics(run_dir: Path) -> dict:
    """Optional recorded timeline metrics.

    If a fixture includes events.jsonl, each line may be:
      {"ts": 1.0, "type": "request"|"action"|"evidence", ...}
    This stays artifact-only: no wall clock probing, no target traffic.
    """
    p = run_dir / "state" / "events.jsonl"
    if not p.exists():
        p = run_dir / "events.jsonl"
    out = {
        "event_requests": 0,
        "time_to_first_delegation_sec": None,
        "time_to_first_evidence_sec": None,
        "duplicate_target_requests": 0,
        "information_gain_total": 0.0,
        "token_budget_spent": 0,
        "closure_reopen_events": 0,
    }
    if not p.exists():
        return out
    out["timeline_source"] = str(p.relative_to(run_dir))
    if p.name == "events.jsonl" and p.parent == run_dir:
        out["timeline_warning"] = "legacy root events.jsonl fallback; prefer state/events.jsonl"
    first_activity = None
    first_delegation = None
    first_evidence = None
    request_shapes: set[tuple[str, str, str]] = set()
    for line in p.read_text(encoding="utf-8", errors="replace").splitlines():
        try:
            ev = json.loads(line)
            ts = float(ev.get("ts"))
        except Exception:
            continue
        typ = str(ev.get("type", "")).lower()
        if typ == "request":
            out["event_requests"] += 1
            shape = (
                str(ev.get("method") or "").upper(),
                str(ev.get("asset") or ev.get("host") or ""),
                str(ev.get("url") or ev.get("path") or ""),
            )
            if shape[1] or shape[2]:
                if shape in request_shapes:
                    # Count repeated occurrences beyond the first, not the
                    # number of distinct repeated shapes.
                    out["duplicate_target_requests"] += 1
                request_shapes.add(shape)
        if typ in {"delegation", "agent_start", "assignment"} \
                and first_delegation is None:
            first_delegation = ts
        if typ in _ATTRIBUTABLE_METRIC_EVENTS:
            try:
                out["information_gain_total"] += float(
                    ev.get("information_gain") or 0)
                out["token_budget_spent"] += int(ev.get("tokens") or 0)
            except (TypeError, ValueError):
                pass
        if typ in {"stage_transition", "stage-transition"} \
                and str(ev.get("from") or "").upper() == "S3" \
                and str(ev.get("to") or "").upper() == "S2":
            out["closure_reopen_events"] += 1
        if typ in {"request", "action"} and first_activity is None:
            first_activity = ts
        if typ == "evidence" and first_evidence is None:
            first_evidence = ts
    if first_activity is not None and first_evidence is not None and first_evidence >= first_activity:
        out["time_to_first_evidence_sec"] = round(first_evidence - first_activity, 3)
    if first_activity is not None and first_delegation is not None \
            and first_delegation >= first_activity:
        out["time_to_first_delegation_sec"] = round(
            first_delegation - first_activity, 3)
    out["information_gain_total"] = round(out["information_gain_total"], 3)
    return out


def _load_json(path: Path) -> dict:
    try:
        data = json.loads(path.read_text(encoding="utf-8", errors="replace"))
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def _field(text: str, name: str) -> str:
    m = re.search(rf"(?im)^\s*[-*]?\s*{re.escape(name)}\s*[:：]\s*([^\n]*)$", text)
    return m.group(1).strip() if m else ""


def _front_blocks(run_dir: Path) -> list[dict]:
    text = (run_dir / "frontier.md").read_text(encoding="utf-8", errors="replace") \
        if (run_dir / "frontier.md").exists() else ""
    out = []
    for m in re.finditer(r"(?ms)^###\s+(F-\d+).*?(?=^###\s+F-\d+|\Z)", text):
        block = m.group(0)
        threat_role = _field(block, "Threat role")
        severity = _field(block, "Severity")
        out.append({
            "id": m.group(1),
            "text": block,
            "status": _field(block, "Status").lower(),
            "threat_role": threat_role,
            "threat_exposure": _field(block, "Threat exposure"),
            "severity": severity,
            "high_value": severity.upper() in {"HIGH", "CRITICAL"}
            or threat_role.lower() in {"admin-mgmt", "identity-auth"},
        })
    return out


def _agent_blocks(run_dir: Path) -> list[dict]:
    out = []
    ad = run_dir / "agents"
    for p in sorted(ad.glob("A-*.md")) if ad.exists() else []:
        text = p.read_text(encoding="utf-8", errors="replace")
        out.append({
            "agent": p.stem,
            "role": _field(text, "Role"),
            "front": _field(text, "Assigned front"),
            "status": _field(text, "Status").lower(),
            "maturity": _field(text, "Maturity").lower(),
            "supports": _field(text, "Supports"),
            "refutes": _field(text, "Refutes"),
            "confidence": _field(text, "Confidence"),
        })
    return out


def _collaboration_metrics(run_dir: Path, truth: dict) -> dict:
    """Artifact-only Ultra-native coordination metrics.

    This does not judge exploitability. It checks whether the agent board behaved
    like a coordinated search: high-value fronts assigned, candidates gated,
    conflicts resolved, and request budget not multiplied by agent count.
    """
    assignments = _load_json(run_dir / "state" / "assignments.json").get("assignments", [])
    assignments = [a for a in assignments if isinstance(a, dict)]
    plan_lanes = _load_json(
        run_dir / "state" / "work_plan.json").get("lanes", [])
    plan_lanes = plan_lanes if isinstance(plan_lanes, list) else []
    plan_lane_ids = {
        str(lane.get("id") or lane.get("lane_id") or "").strip()
        for lane in plan_lanes
        if isinstance(lane, dict)
    } - {""}
    assigned_lane_ids = {
        str(item.get("lane_id") or "").strip()
        for item in assignments
    } - {""}
    lane_capture_rate = (
        round(len(assigned_lane_ids & plan_lane_ids) / len(plan_lane_ids), 3)
        if plan_lane_ids else None
    )
    agents = _agent_blocks(run_dir)
    fronts = _front_blocks(run_dir)
    conflicts = _load_json(run_dir / "state" / "conflicts.json").get("conflicts", [])
    conflicts = [c for c in conflicts if isinstance(c, dict)]
    unresolved = [c for c in conflicts if str(c.get("status", "")).lower() in {"", "open", "unresolved"}]
    assigned_fronts = {str(a.get("front")) for a in assignments if a.get("front")}
    high_fronts = {f["id"] for f in fronts if f["high_value"]}
    missed_high = sorted(high_fronts - assigned_fronts)
    agent_roles = {a["agent"]: a.get("role", "") for a in agents}
    assignment_roles: dict[str, set[str]] = {}
    for a in assignments:
        front = str(a.get("front") or "").strip()
        if not front:
            continue
        role = str(a.get("role") or agent_roles.get(str(a.get("agent") or ""), "")).strip().lower()
        assignment_roles.setdefault(front, set())
        if role:
            assignment_roles[front].add(role)

    candidate_agents = [
        a for a in agents
        if a.get("maturity") == "candidate" or a.get("supports") or a.get("refutes")
    ]
    finding_ids = [r["id"] for r in evidence_parse.parse_evidence(run_dir)
                   if r["confirmed"] and r.get("maturity") == "finding"]
    conversion = (round(len(finding_ids) / len(candidate_agents), 3) if candidate_agents else None)

    # Events may optionally include agent and type=request/evidence. Without such
    # data, report empty maps rather than guessing.
    event_path = run_dir / "state" / "events.jsonl"
    req_by_agent: dict[str, int] = {}
    first_by_mode: dict[str, float] = {}
    start_by_mode: dict[str, float] = {}
    if event_path.exists():
        for line in event_path.read_text(encoding="utf-8", errors="replace").splitlines():
            try:
                ev = json.loads(line)
                ts = float(ev.get("ts"))
            except Exception:
                continue
            agent = str(ev.get("agent") or ev.get("mode") or "").strip()
            typ = str(ev.get("type", "")).lower()
            if agent and typ == "request":
                req_by_agent[agent] = req_by_agent.get(agent, 0) + 1
                start_by_mode.setdefault(agent, ts)
            if agent and typ == "evidence":
                first_by_mode.setdefault(agent, ts)
    ttfe_by_mode = {m: round(first_by_mode[m] - start_by_mode[m], 3)
                    for m in first_by_mode if m in start_by_mode and first_by_mode[m] >= start_by_mode[m]}

    fp_suppressed = sum(1 for r in evidence_parse.parse_evidence(run_dir)
                        if r.get("refutes_any") and not r.get("supports") and r.get("confirmed"))
    spec = truth.get("expected_collaboration", {})
    checks = []
    role_misses = []
    if spec:
        front_roles = spec.get("front_roles", {})
        if isinstance(front_roles, dict):
            for front, roles in front_roles.items():
                wanted = {str(r).strip().lower() for r in roles if str(r).strip()}
                got = assignment_roles.get(str(front), set())
                if wanted and not (wanted & got):
                    role_misses.append({"front": front, "expected_roles": sorted(wanted), "got_roles": sorted(got)})
        if "min_agent_coverage" in spec:
            denom = max(len(high_fronts), 1)
            covered = len(high_fronts) - len(missed_high) - len(
                [m for m in role_misses if str(m.get("front")) in high_fronts])
            checks.append({"id": "agent-coverage", "ok": covered / denom
                           >= float(spec["min_agent_coverage"])})
        if spec.get("require_conflicts_resolved"):
            checks.append({"id": "conflicts-resolved", "ok": not unresolved})
        if "max_requests_per_agent" in spec and req_by_agent:
            cap = int(spec["max_requests_per_agent"])
            checks.append({"id": "request-budget-by-agent", "ok": all(v <= cap for v in req_by_agent.values())})
        elif "max_requests_per_agent" in spec:
            reason = "state/events.jsonl missing" if not event_path.exists() else "no agent request events"
            checks.append({"id": "request-budget-by-agent", "ok": False, "skipped": True,
                           "reason": reason})
        if spec.get("require_no_missed_high_value"):
            checks.append({"id": "missed-high-value-front", "ok": not missed_high})
    return {
        "assignments": len(assignments),
        "agents": len(agents),
        "high_value_fronts": len(high_fronts),
        "assigned_high_value_fronts": len(high_fronts) - len(missed_high),
        "missed_high_value_fronts": missed_high,
        "role_mismatched_fronts": role_misses,
        "candidate_agents": len(candidate_agents),
        "confirmed_findings": len(finding_ids),
        "candidate_to_finding_conversion": conversion,
        "conflicts_total": len(conflicts),
        "conflicts_unresolved": len(unresolved),
        "conflict_resolution_correct": not unresolved if conflicts else None,
        "request_budget_by_agent": req_by_agent,
        "time_to_first_evidence_by_mode_sec": ttfe_by_mode,
        "front_coverage_rate": round(
            sum(1 for front in fronts if front["status"] in {
                "closed", "blocked_type_b", "deferred", "done", "complete",
            }) / len(fronts), 3,
        ) if fronts else None,
        "effective_lane_capture_rate": lane_capture_rate,
        "agent_useful_yield": round(
            sum(1 for item in assignments if str(
                item.get("root_disposition") or item.get("status") or "").lower()
                in {"merged", "blocked", "failed"}) / len(assignments), 3,
        ) if assignments else None,
        "merge_debt": sum(
            1 for item in assignments
            if str(item.get("status") or "").lower() in {"done", "returned"}
            and not item.get("root_disposition")
        ),
        "false_positive_suppression_events": fp_suppressed,
        "checks": checks,
    }


def _closure_check(run_dir: Path, truth: dict) -> dict | None:
    """Check a recorded closure fixture without treating 'no finding' as failure."""
    spec = truth.get("expected_closure")
    if not spec:
        return None
    hay = ""
    for fn in spec.get("in") or ["decisions.md", "review.md", "report.md"]:
        p = run_dir / fn
        if p.exists():
            hay += "\n" + p.read_text(encoding="utf-8", errors="replace").lower()
    markers = [str(m).lower() for m in spec.get("markers", []) if str(m).strip()]
    markers_ok = all(m in hay for m in markers)
    review_ok = True
    if spec.get("requires_independent_review", False):
        rp = run_dir / "review.md"
        review_ok = rp.exists() and "independent review" in rp.read_text(
            encoding="utf-8", errors="replace").lower()
    no_positive = True
    if spec.get("requires_no_positive_findings", True):
        blocks, _cert, positive = _confirmed_blocks(run_dir)
        no_positive = not any(eid in positive for eid in blocks)
    return {
        "expected": True,
        "correct": bool(markers_ok and review_ok and no_positive),
        "markers_ok": markers_ok,
        "review_ok": review_ok,
        "no_positive_findings": no_positive,
    }


def score(run_dir: Path, truth: dict) -> dict:
    blocks, cert, positive = _confirmed_blocks(run_dir)
    findings = []
    for exp in truth.get("expected_findings", []):
        hit = _match(exp.get("markers", []), blocks)
        minc = float(exp.get("min_certainty", 0.8))
        got = cert.get(hit) if hit else None
        findings.append({
            "id": exp.get("id"), "detected": hit is not None, "matched_eid": hit,
            "min_certainty": minc, "got_certainty": got,
            "calibrated": bool(hit is not None and got is not None and got >= minc),
        })
    # 误报只针对【正向确认发现】: 纯负向条目(driver 正确地"没声称漏洞")不算误报。
    pos_blocks = {eid: bt for eid, bt in blocks.items() if eid in positive}
    fps = []
    for trap in truth.get("must_not_flag", []):
        hit = _match(trap.get("markers", []), pos_blocks)
        if hit:
            fps.append({"trap": trap.get("id"), "flagged_eid": hit})
    n_exp = len(findings)
    n_det = sum(1 for f in findings if f["detected"])
    n_cal = sum(1 for f in findings if f["calibrated"])
    timeline = _timeline_metrics(run_dir)
    replay_budget = len(list(run_dir.glob("**/*.replay.json")))
    budget = max(replay_budget, timeline["event_requests"])
    proc = _process_check(run_dir, truth.get("expected_process", []))
    budget_max = truth.get("budget", {}).get("max_requests")
    closure = _closure_check(run_dir, truth)
    collaboration = _collaboration_metrics(run_dir, truth)
    return {
        "fixture": truth.get("name", run_dir.name),
        "expected": n_exp, "detected": n_det,
        "detection_rate": round(n_det / n_exp, 3) if n_exp else None,
        "calibrated": n_cal,
        "calibration_rate": round(n_cal / n_det, 3) if n_det else (1.0 if n_exp == 0 else 0.0),
        "false_positives": len(fps),
        "false_positive_rate": round(len(fps) / len(truth.get("must_not_flag", [])), 3)
        if truth.get("must_not_flag") else 0.0,
        "confirmed_total": len(blocks),
        "recorded_requests": budget,
        "budget_max": budget_max,
        "over_budget": bool(budget_max is not None and budget > int(budget_max)),
        "time_to_first_evidence_sec": timeline["time_to_first_evidence_sec"],
        "time_to_first_delegation_sec": timeline["time_to_first_delegation_sec"],
        "duplicate_target_requests": timeline["duplicate_target_requests"],
        "information_gain_total": timeline["information_gain_total"],
        "token_budget_spent": timeline["token_budget_spent"],
        "closure_reopen_events": timeline["closure_reopen_events"],
        "closure": closure,
        "findings": findings, "fp_detail": fps,
        "process": proc,
        "collaboration": collaboration,
    }


def _print_card(s: dict) -> None:
    dr = s["detection_rate"]
    print(f"== bench: {s['fixture']} ==")
    print(f"  detection : {s['detected']}/{s['expected']}"
          + (f" ({dr:.0%})" if dr is not None else "")
          + f"   calibrated {s['calibrated']}/{s['expected']}")
    print(f"  false-pos : {s['false_positives']}   (confirmed entries total: {s['confirmed_total']})")
    bm = s["budget_max"]
    print(f"  budget    : {s['recorded_requests']} recorded requests"
          + (f" / {bm} max" if bm else "")
          + ("  OVER" if s.get("over_budget") else "")
          + "  (lower bound: saved replay or recorded events)")
    if s.get("time_to_first_evidence_sec") is not None:
        print(f"  first-evidence: {s['time_to_first_evidence_sec']}s")
    if s.get("closure"):
        c = s["closure"]
        mark = "✓" if c["correct"] else "✗"
        print(f"  closure   : {mark} markers={c['markers_ok']} review={c['review_ok']} "
              f"no_positive={c['no_positive_findings']}")
    for f in s["findings"]:
        mark = "✓" if f["detected"] else "✗"
        cal = "" if not f["detected"] else (
            f" cert={f['got_certainty']}≥{f['min_certainty']}" if f["calibrated"]
            else f" ⚠ cert={f['got_certainty']}<{f['min_certainty']} (欠证)")
        eid = f" [{f['matched_eid']}]" if f["matched_eid"] else ""
        print(f"    {mark} {f['id']}{eid}{cal}")
    for fp in s["fp_detail"]:
        print(f"    ✗ FALSE-POSITIVE: trap '{fp['trap']}' 被确认条目 {fp['flagged_eid']} 命中")
    proc = s.get("process", [])
    if proc:
        n_fired = sum(1 for p in proc if p["fired"])
        print(f"  process   : {n_fired}/{len(proc)} 能力在对的时刻触发了")
        for p in proc:
            mark = "✓" if p["fired"] else ("✗" if p["must"] else "○")
            opt = "" if p["must"] else " (optional)"
            miss = "" if p["fired"] else f"  signals={p['signals']} 未见踪迹"
            print(f"    {mark} {p['id']}{opt}{miss}")
    collab = s.get("collaboration", {})
    if collab and (collab.get("assignments") or collab.get("agents") or collab.get("checks")):
        failed = [c for c in collab.get("checks", []) if not c.get("ok")]
        print(f"  agents    : {collab.get('agents', 0)} agents / {collab.get('assignments', 0)} assignments; "
              f"high fronts {collab.get('assigned_high_value_fronts', 0)}/"
              f"{collab.get('high_value_fronts', 0)} assigned")
        conv = collab.get("candidate_to_finding_conversion")
        if conv is not None:
            print(f"  conversion: {collab.get('confirmed_findings', 0)}/"
                  f"{collab.get('candidate_agents', 0)} candidate/refutation agents -> findings ({conv:.0%})")
        if collab.get("conflicts_total"):
            print(f"  conflicts : {collab.get('conflicts_total', 0)} total; "
                  f"{collab.get('conflicts_unresolved', 0)} unresolved")
        if collab.get("request_budget_by_agent"):
            print(f"  agent budget: {collab['request_budget_by_agent']}")
        if collab.get("time_to_first_evidence_by_mode_sec"):
            print(f"  agent first-evidence: {collab['time_to_first_evidence_by_mode_sec']}")
        if failed:
            print("  collaboration checks failed: " + ", ".join(
                str(c.get("id")) + (f" ({c.get('reason')})" if c.get("skipped") else "")
                for c in failed))


def _is_clean(s: dict) -> bool:
    """完美 = 全检出 + 全校准 + 零误报 + 预算内 + must 过程断言触发。"""
    proc_ok = all(p["fired"] for p in s.get("process", []) if p["must"])
    closure = s.get("closure")
    closure_ok = closure is None or closure["correct"]
    collab = s.get("collaboration") or {}
    collab_ok = all(c.get("ok") for c in collab.get("checks", []))
    detection_ok = (
        (s["expected"] > 0 and s["detected"] == s["expected"]
         and s["calibrated"] == s["expected"])
        or s["expected"] == 0
    )
    return (detection_ok and s["false_positives"] == 0 and not s.get("over_budget", False)
            and proc_ok and closure_ok and collab_ok)


def _load_truth(p: Path) -> dict:
    return json.loads(p.read_text(encoding="utf-8"))


def _aggregate(scores: list[dict]) -> dict:
    total_expected = sum(s["expected"] for s in scores)
    total_detected = sum(s["detected"] for s in scores)
    total_calibrated = sum(s["calibrated"] for s in scores)
    ttfe = [s["time_to_first_evidence_sec"] for s in scores
            if s.get("time_to_first_evidence_sec") is not None]
    clean = sum(1 for s in scores if _is_clean(s))
    closures = [s for s in scores if s.get("closure")]
    collaborations = [s.get("collaboration") or {} for s in scores]
    collab_checks = [c for co in collaborations for c in co.get("checks", [])]
    collab_ttfe = [v for co in collaborations for v in co.get("time_to_first_evidence_by_mode_sec", {}).values()]
    return {
        "fixtures": len(scores),
        "clean": clean,
        "detection_rate": round(total_detected / total_expected, 3) if total_expected else None,
        "calibration_rate": round(total_calibrated / total_detected, 3) if total_detected else 1.0,
        "false_positives": sum(s["false_positives"] for s in scores),
        "false_positive_rate_mean": round(
            sum(s["false_positive_rate"] for s in scores) / len(scores), 3) if scores else None,
        "request_budget_over": sum(1 for s in scores if s.get("over_budget")),
        "request_budget_total": sum(s["recorded_requests"] for s in scores),
        "time_to_first_evidence_avg_sec": round(sum(ttfe) / len(ttfe), 3) if ttfe else None,
        "time_to_first_delegation_avg_sec": (
            round(sum(values) / len(values), 3) if (
                values := [s["time_to_first_delegation_sec"] for s in scores
                           if s.get("time_to_first_delegation_sec") is not None]
            ) else None
        ),
        "duplicate_target_requests": sum(
            int(s.get("duplicate_target_requests", 0)) for s in scores),
        "information_gain_total": round(sum(
            float(s.get("information_gain_total", 0)) for s in scores), 3),
        "token_budget_spent": sum(
            int(s.get("token_budget_spent", 0)) for s in scores),
        "closure_reopen_events": sum(
            int(s.get("closure_reopen_events", 0)) for s in scores),
        "closure_correct": sum(1 for s in closures if s["closure"]["correct"]),
        "closure_expected": len(closures),
        "agent_assignments": sum(int(co.get("assignments", 0)) for co in collaborations),
        "agent_count": sum(int(co.get("agents", 0)) for co in collaborations),
        "missed_high_value_fronts": sum(len(co.get("missed_high_value_fronts", [])) for co in collaborations),
        "role_mismatched_fronts": sum(len(co.get("role_mismatched_fronts", [])) for co in collaborations),
        "conflicts_unresolved": sum(int(co.get("conflicts_unresolved", 0)) for co in collaborations),
        "collaboration_checks_failed": sum(1 for c in collab_checks if not c.get("ok")),
        "false_positive_suppression_events": sum(
            int(co.get("false_positive_suppression_events", 0)) for co in collaborations),
        "agent_first_evidence_avg_sec": round(sum(collab_ttfe) / len(collab_ttfe), 3) if collab_ttfe else None,
        "total_expected_findings": total_expected,
        "total_detected_findings": total_detected,
        "total_calibrated_findings": total_calibrated,
    }


def scheduler_ab_decision(value: dict) -> dict:
    """Adjudicate a recorded Root/serial/parallel comparison.

    A hard parallel gate is admitted only when parallel has no quality loss,
    improves elapsed time or coverage, and its merge/request/token overhead stays
    within the fixture's declared caps.  Otherwise the scheduler remains a soft,
    capacity-bounded recommendation.
    """
    modes = value.get("modes") if isinstance(value, dict) else None
    required = {"root_direct", "serial_agent", "parallel_agent"}
    if not isinstance(modes, dict) or set(modes) != required:
        raise ValueError("SCHEDULER_AB_MODES_INVALID")
    metric_names = (
        "quality", "elapsed_sec", "coverage", "merge_cost", "requests", "tokens",
    )
    normalized_modes: dict[str, dict[str, float]] = {}
    for name, row in modes.items():
        if not isinstance(row, dict) or not {
            *metric_names,
        }.issubset(row):
            raise ValueError(f"SCHEDULER_AB_ROW_INVALID:{name}")
        try:
            normalized = {
                metric: float(row[metric])
                for metric in metric_names
                if not isinstance(row[metric], bool)
            }
        except (TypeError, ValueError, OverflowError) as exc:
            raise ValueError(f"SCHEDULER_AB_ROW_INVALID:{name}") from exc
        if len(normalized) != len(metric_names) or any(
            not math.isfinite(number) or number < 0
            for number in normalized.values()
        ) or any(normalized[metric] > 1 for metric in ("quality", "coverage")):
            raise ValueError(f"SCHEDULER_AB_ROW_INVALID:{name}")
        normalized_modes[name] = normalized
    parallel = normalized_modes["parallel_agent"]
    baselines = [
        normalized_modes["root_direct"], normalized_modes["serial_agent"],
    ]
    caps = value.get("caps")
    cap_names = {"merge_cost", "requests", "tokens"}
    if not isinstance(caps, dict) or set(caps) != cap_names:
        raise ValueError("SCHEDULER_AB_CAPS_INVALID")
    try:
        cap_values = {
            name: float(caps[name])
            for name in cap_names
            if not isinstance(caps[name], bool)
        }
    except (TypeError, ValueError, OverflowError) as exc:
        raise ValueError("SCHEDULER_AB_CAPS_INVALID") from exc
    if len(cap_values) != len(cap_names) or any(
        not math.isfinite(number) or number < 0
        for number in cap_values.values()
    ):
        raise ValueError("SCHEDULER_AB_CAPS_INVALID")
    quality_ok = all(parallel["quality"] >= row["quality"]
                     for row in baselines)
    benefit = (
        parallel["elapsed_sec"] < min(row["elapsed_sec"] for row in baselines)
        or parallel["coverage"] > max(row["coverage"] for row in baselines)
    )
    overhead_ok = (
        parallel["merge_cost"] <= cap_values["merge_cost"]
        and parallel["requests"] <= cap_values["requests"]
        and parallel["tokens"] <= cap_values["tokens"]
    )
    promote = bool(quality_ok and benefit and overhead_ok)
    decision = (
        "hard-gate-eligible" if promote else "soft-recommendation-only"
    )
    expected = value.get("expected_decision")
    if expected is not None and expected != decision:
        raise ValueError("SCHEDULER_AB_EXPECTED_MISMATCH")
    return {
        "schema": "xunji.scheduler-ab-decision.v1",
        "promote_parallel_hard_gate": promote,
        "decision": decision,
        "checks": {
            "no_quality_regression": quality_ok,
            "speed_or_coverage_benefit": benefit,
            "overhead_within_caps": overhead_ok,
        },
    }


def _summary(scores: list[dict]) -> dict:
    return {"summary": _aggregate(scores), "scores": scores}


def _print_summary(summary: dict) -> None:
    a = summary["summary"]
    print("== bench summary ==")
    print(f"  fixtures  : {a['clean']}/{a['fixtures']} clean")
    if a["detection_rate"] is not None:
        print(f"  detection : {a['total_detected_findings']}/{a['total_expected_findings']} "
              f"({a['detection_rate']:.0%})")
    print(f"  calibration: {a['total_calibrated_findings']}/{a['total_detected_findings']} "
          f"({a['calibration_rate']:.0%})")
    print(f"  false-pos : {a['false_positives']} "
          f"(mean trap rate {a['false_positive_rate_mean']:.0%})")
    print(f"  budget    : {a['request_budget_total']} recorded; "
          f"{a['request_budget_over']} fixture(s) over max")
    if a["time_to_first_evidence_avg_sec"] is not None:
        print(f"  first-evidence avg: {a['time_to_first_evidence_avg_sec']}s")
    if a["closure_expected"]:
        print(f"  closure   : {a['closure_correct']}/{a['closure_expected']} correct")
    if a["agent_count"] or a["agent_assignments"] or a["collaboration_checks_failed"]:
        print(f"  agents    : {a['agent_count']} agents / {a['agent_assignments']} assignments; "
              f"missed-high={a['missed_high_value_fronts']} role-mismatch={a['role_mismatched_fronts']}")
        print(f"  conflicts : {a['conflicts_unresolved']} unresolved; "
              f"collab-check-fail={a['collaboration_checks_failed']}")
        print(f"  fp-suppression: {a['false_positive_suppression_events']} negative confirmed events")
        if a["agent_first_evidence_avg_sec"] is not None:
            print(f"  agent first-evidence avg: {a['agent_first_evidence_avg_sec']}s")


def _write_json(path: Path | None, obj: dict) -> None:
    if not path:
        return
    path.write_text(json.dumps(obj, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _load_score_or_summary(path: Path) -> dict:
    obj = json.loads(path.read_text(encoding="utf-8"))
    if "summary" in obj:
        return obj["summary"]
    if "scores" in obj:
        return _aggregate(obj["scores"])
    return _aggregate([obj])


def _compare(baseline: Path, change: Path) -> int:
    b = _load_score_or_summary(baseline)
    c = _load_score_or_summary(change)
    keys = [
        "detection_rate", "calibration_rate", "false_positives", "false_positive_rate_mean",
        "request_budget_total", "request_budget_over", "time_to_first_evidence_avg_sec",
        "time_to_first_delegation_avg_sec", "duplicate_target_requests",
        "information_gain_total", "token_budget_spent", "closure_reopen_events",
        "closure_correct", "missed_high_value_fronts", "role_mismatched_fronts",
        "conflicts_unresolved", "collaboration_checks_failed", "agent_first_evidence_avg_sec",
        "false_positive_suppression_events",
    ]
    higher_is_better = {
        "detection_rate", "calibration_rate", "closure_correct",
        "false_positive_suppression_events", "information_gain_total",
    }
    lower_is_better = {
        "false_positives", "false_positive_rate_mean", "request_budget_total",
        "request_budget_over", "time_to_first_evidence_avg_sec", "missed_high_value_fronts",
        "time_to_first_delegation_avg_sec", "duplicate_target_requests",
        "token_budget_spent",
        "role_mismatched_fronts", "conflicts_unresolved", "collaboration_checks_failed",
        "agent_first_evidence_avg_sec", "closure_reopen_events",
    }
    regressed = False
    print("== bench compare ==")
    print(f"  baseline: {baseline}")
    print(f"  change  : {change}")
    for k in keys:
        bv, cv = b.get(k), c.get(k)
        if bv is None and cv is None:
            continue
        delta = None if bv is None or cv is None else round(cv - bv, 3)
        sign = "+" if delta is not None and delta > 0 else ""
        if delta is not None:
            if k in higher_is_better and delta < 0:
                regressed = True
            if k in lower_is_better and delta > 0:
                regressed = True
        print(f"  {k}: {bv} -> {cv}" + ("" if delta is None else f" ({sign}{delta})"))
    return 1 if regressed else 0


def main() -> int:
    ap = argparse.ArgumentParser(description="R-1 自评 harness: 对 run 产物按 fixture 真值打分")
    sub = ap.add_subparsers(dest="cmd")
    sp = sub.add_parser("score", help="给单个 run 对照 truth.json 打分")
    sp.add_argument("run_dir", type=Path)
    sp.add_argument("truth", type=Path)
    sp.add_argument("--json", action="store_true", help="print JSON instead of a text card")
    sp.add_argument("--json-out", type=Path, help="write score JSON to this path")
    sa = sub.add_parser("score-all", help="跑 bench/ 下每个 <fixture>/truth.json(truth 内 run 字段指 run)")
    sa.add_argument("bench_dir", type=Path, nargs="?", default=ROOT / "bench")
    sa.add_argument("--json", action="store_true", help="print summary JSON instead of cards")
    sa.add_argument("--json-out", type=Path, help="write summary JSON to this path")
    cp = sub.add_parser("compare", help="compare two score/summary JSON files")
    cp.add_argument("baseline", type=Path)
    cp.add_argument("change", type=Path)
    ab = sub.add_parser(
        "scheduler-ab",
        help="adjudicate a recorded root-direct/serial/parallel fixture",
    )
    ab.add_argument("fixture", type=Path)
    ap.add_argument("--selftest", action="store_true")
    args = ap.parse_args()

    if args.selftest:
        return _selftest()
    if args.cmd == "score":
        rd = args.run_dir if args.run_dir.is_absolute() else Path.cwd() / args.run_dir
        s = score(rd, _load_truth(args.truth))
        _write_json(args.json_out, s)
        if args.json:
            print(json.dumps(s, ensure_ascii=False, indent=2))
        else:
            _print_card(s)
        return 0 if _is_clean(s) else 1
    if args.cmd == "score-all":
        bdir = args.bench_dir
        truths = sorted(bdir.glob("*/truth.json"))
        if not truths:
            print(f"(无 fixture: {bdir}/*/truth.json)")
            return 0
        worst = 0
        scores = []
        for tp in truths:
            truth = _load_truth(tp)
            run_rel = truth.get("run")
            if not run_rel:
                print(f"[skip] {tp.parent.name}: truth.json 无 'run' 字段(指向待评 run 目录)")
                continue
            rd = (tp.parent / run_rel).resolve()
            s = score(rd, truth)
            scores.append(s)
            if not args.json:
                _print_card(s)
            worst = max(worst, 0 if _is_clean(s) else 1)
        summary = _summary(scores)
        _write_json(args.json_out, summary)
        if args.json:
            print(json.dumps(summary, ensure_ascii=False, indent=2))
        else:
            _print_summary(summary)
        return worst
    if args.cmd == "compare":
        return _compare(args.baseline, args.change)
    if args.cmd == "scheduler-ab":
        try:
            decision = scheduler_ab_decision(_load_truth(args.fixture))
        except (OSError, ValueError, json.JSONDecodeError) as exc:
            print(f"scheduler A/B invalid: {exc}", file=sys.stderr)
            return 2
        print(json.dumps(decision, ensure_ascii=False, indent=2))
        return 0
    ap.print_help()
    return 2


def _selftest() -> int:
    import contextlib
    import io
    import tempfile
    d = Path(tempfile.mkdtemp())
    run = d / "fix_20260101"
    run.mkdir()
    (run / "evidence.md").write_text(
        "# Evidence Ledger\n\n"
        "## E-001: SQL injection in id param (union-based)\n"
        "- Certainty: 1.0\n- Replicated: yes\n- Artifacts: `evidence/sqli.html`\n"
        "- Supports: H-001\n\n"
        "## E-002: login page present (environment)\n"
        "- Certainty: 0.8\n- Replicated: yes\n- Refutes: H-009\n\n"
        "## E-003: reflected XSS in search param\n"
        "- Certainty: 0.5\n- Note: suspected, not yet controlled\n",
        encoding="utf-8")
    truth = {
        "name": "selftest-fixture",
        "expected_findings": [
            {"id": "sqli", "markers": ["sql injection", "union"], "min_certainty": 0.8},
            {"id": "xss", "markers": ["reflected xss"], "min_certainty": 0.8},
        ],
        "must_not_flag": [
            {"id": "login-page-is-not-a-vuln", "markers": ["login page present"]},
        ],
    }
    s = score(run, truth)
    checks = [
        ("检出: sqli(确认1.0 含 markers) 命中", s["findings"][0]["detected"] and s["findings"][0]["matched_eid"] == "E-001"),
        ("校准: sqli cert 1.0>=0.8 calibrated", s["findings"][0]["calibrated"]),
        ("漏检: xss 只 0.5 未确认 -> 不算检出", not s["findings"][1]["detected"]),
        ("检出率 1/2", s["detection_rate"] == 0.5),
        ("误报: 'login page present' 在 E-002 但 E-002 是纯 Refutes negative -> 不算确认正向, 不应误报",
         s["false_positives"] == 0),
        ("_is_clean: 有漏检 -> 非 clean(退出码1)", not _is_clean(s)),
    ]
    # 全检出 + 校准 + 零误报 -> clean
    run2 = d / "perfect_20260101"
    run2.mkdir()
    (run2 / "evidence.md").write_text(
        "# Evidence Ledger\n\n## E-001: SQL injection union-based\n- Certainty: 1.0\n- Replicated: yes\n"
        "- Artifacts: `evidence/a.html`\n\n## E-002: reflected XSS in q\n- Certainty: 0.9\n- Control: baseline\n"
        "- Artifacts: `evidence/b.html`\n", encoding="utf-8")
    s2 = score(run2, {"name": "perfect", "expected_findings": [
        {"id": "sqli", "markers": ["sql injection"], "min_certainty": 0.8},
        {"id": "xss", "markers": ["reflected xss"], "min_certainty": 0.8}]})
    checks.append(("全检出+校准+零误报 -> clean(退出码0)", _is_clean(s2)))
    # 欠证: 期望 1.0 但只给 0.8
    s3 = score(run2, {"name": "undercert", "expected_findings": [
        {"id": "sqli", "markers": ["sql injection"], "min_certainty": 1.0},
        {"id": "xss", "markers": ["reflected xss"], "min_certainty": 1.0}]})
    checks.append(("欠证: xss 0.9<1.0 -> detected 但非 calibrated",
                   s3["findings"][1]["detected"] and not s3["findings"][1]["calibrated"]))

    # 过程断言: run3 的 decisions.md 留下 knowledge_match 踪迹, 但没 fetch_assets
    run3 = d / "proc_20260101"
    run3.mkdir()
    (run3 / "evidence.md").write_text(
        "# Evidence Ledger\n\n## E-001: SQL injection union-based\n- Certainty: 1.0\n- Replicated: yes\n"
        "- Artifacts: `evidence/a.html`\n", encoding="utf-8")
    (run3 / "decisions.md").write_text(
        "# Decisions\n## D-001\n- Reason: 指纹命中, 跑了 tools/knowledge_match.py --body 取锚点\n",
        encoding="utf-8")
    tp = {"name": "proc", "expected_findings": [{"id": "sqli", "markers": ["sql injection"], "min_certainty": 0.8}],
          "expected_process": [{"id": "consulted-knowledge", "signals": ["knowledge_match"], "must": True},
                               {"id": "ran-fetch-assets", "signals": ["fetch_assets"], "must": True}]}
    sp = score(run3, tp)
    checks.append(("过程: knowledge_match 留痕 -> fired", sp["process"][0]["fired"]))
    checks.append(("过程: fetch_assets 无痕 -> not fired", not sp["process"][1]["fired"]))
    checks.append(("过程门: must 断言未全触发 -> 非 clean(尽管全检出)", not _is_clean(sp)))
    tp2 = {"name": "proc-opt", "expected_findings": [{"id": "sqli", "markers": ["sql injection"], "min_certainty": 0.8}],
           "expected_process": [{"id": "ran-fetch-assets", "signals": ["fetch_assets"], "must": False}]}
    checks.append(("过程门: optional 未触发不破 clean", _is_clean(score(run3, tp2))))

    # pure-negative fixture: no expected findings, just traps that must not be positive-confirmed.
    spn = score(run3, {"name": "pure-negative", "expected_findings": [],
                       "must_not_flag": [{"id": "not-sqli", "markers": ["not present"]}]})
    checks.append(("纯负向 fixture: 无 expected_findings 且零误报 -> clean", _is_clean(spn)))

    # timeline + recorded closure fixture
    run4 = d / "closure_20260101"
    run4.mkdir()
    (run4 / "evidence.md").write_text(
        "# Evidence Ledger\n\n## E-001: Static-only fixture\n- Certainty: 0.8\n"
        "- Replicated: yes\n- Refutes: H-001\n", encoding="utf-8")
    (run4 / "review.md").write_text(
        "# Review\n\n## Independent Review\n\nclosure supported; no confirmed findings.\n",
        encoding="utf-8")
    (run4 / "report.md").write_text(
        "# Report\n\n## Closure\n\nstatic-only fixture; no confirmed findings.\n",
        encoding="utf-8")
    (run4 / "events.jsonl").write_text(
        '{"ts": 2.0, "type": "request"}\n{"ts": 5.5, "type": "evidence"}\n',
        encoding="utf-8")
    sc = score(run4, {"name": "closure", "expected_findings": [],
                      "expected_closure": {"markers": ["closure", "static-only fixture"],
                                           "requires_independent_review": True},
                      "budget": {"max_requests": 3}})
    checks.append(("时间线: time-to-first-evidence 从 events.jsonl 计算", sc["time_to_first_evidence_sec"] == 3.5))
    run4_state = d / "closure_state_20260101"
    run4_state.mkdir()
    (run4_state / "state").mkdir()
    (run4_state / "evidence.md").write_text("# Evidence Ledger\n", encoding="utf-8")
    (run4_state / "state" / "events.jsonl").write_text(
        '{"ts": 1.0, "type": "request", "method":"GET", "url":"/a", "tokens":10}\n'
        '{"ts": 1.5, "type": "delegation"}\n'
        '{"ts": 2.0, "type": "request", "method":"GET", "url":"/a", "tokens":5, "information_gain":0.25}\n'
        '{"ts": 4.0, "type": "evidence"}\n'
        '{"ts": 4.5, "type": "untrusted_noise", "tokens":999, "information_gain":99}\n'
        '{"ts": 5.0, "type": "stage_transition", "from":"S3", "to":"S2"}\n',
        encoding="utf-8")
    timeline_state = _timeline_metrics(run4_state)
    checks.append(("时间线: state/events.jsonl 优先",
                   timeline_state["time_to_first_evidence_sec"] == 3.0))
    checks.append(("协作度量: delegation/duplicate/gain/token/reopen 可观测",
                   timeline_state["time_to_first_delegation_sec"] == 0.5
                   and timeline_state["duplicate_target_requests"] == 1
                   and timeline_state["information_gain_total"] == 0.25
                   and timeline_state["token_budget_spent"] == 15
                   and timeline_state["closure_reopen_events"] == 1))
    checks.append(("时间线: legacy events.jsonl 标记 fallback",
                   _timeline_metrics(run4).get("timeline_warning") is not None))
    checks.append(("收口: 无正向发现 + Independent Review + markers -> clean", _is_clean(sc)))
    summ = _summary([s2, sc])["summary"]
    checks.append(("汇总: 2 fixture clean 且 closure 计数正确",
                   summ["clean"] == 2 and summ["closure_correct"] == 1))

    # Ultra-native collaboration metrics: assignments, roles, conflicts, agent budgets,
    # time-to-first-evidence, and false-positive suppression are all artifact-only.
    run5 = d / "collab_20260101"
    (run5 / "state").mkdir(parents=True)
    (run5 / "agents").mkdir()
    (run5 / "frontier.md").write_text(
        "# Frontier\n\n"
        "### F-001 identity-auth profile idor\n"
        "- Status: active\n- Threat role: identity-auth\n- Severity: HIGH\n\n"
        "### F-002 marketing page\n"
        "- Status: active\n- Threat role: static-content\n- Severity: LOW\n",
        encoding="utf-8")
    (run5 / "state" / "assignments.json").write_text(json.dumps({
        "schema": 1,
        "assignments": [
            {"agent": "A-web-auth-001", "role": "web-auth", "front": "F-001"},
            {"agent": "A-verify-001", "role": "verify", "front": "F-001"},
        ],
    }, ensure_ascii=False, indent=2), encoding="utf-8")
    (run5 / "agents" / "A-web-auth-001.md").write_text(
        "# Agent A-web-auth-001\n"
        "- Role: web-auth\n- Assigned front: F-001\n- Status: done\n"
        "- Maturity: candidate\n- Supports: H-001\n- Confidence: 0.8\n",
        encoding="utf-8")
    (run5 / "agents" / "A-verify-001.md").write_text(
        "# Agent A-verify-001\n"
        "- Role: verify\n- Assigned front: F-001\n- Status: done\n"
        "- Maturity: phenomenon\n- Refutes: H-009\n- Confidence: 0.8\n",
        encoding="utf-8")
    (run5 / "state" / "conflicts.json").write_text(json.dumps({
        "schema": 1,
        "conflicts": [
            {"id": "C-001", "type": "confidence mismatch", "status": "resolved",
             "resolution": "verification replay supports E-001"},
        ],
    }, ensure_ascii=False, indent=2), encoding="utf-8")
    (run5 / "state" / "events.jsonl").write_text(
        '{"ts": 1.0, "type": "request", "agent": "A-web-auth-001"}\n'
        '{"ts": 2.0, "type": "request", "agent": "A-web-auth-001"}\n'
        '{"ts": 3.5, "type": "evidence", "agent": "A-web-auth-001"}\n'
        '{"ts": 4.0, "type": "request", "agent": "A-verify-001"}\n'
        '{"ts": 5.0, "type": "evidence", "agent": "A-verify-001"}\n',
        encoding="utf-8")
    (run5 / "evidence.md").write_text(
        "# Evidence Ledger\n\n"
        "## E-001: Profile IDOR confirms identity-auth exposure\n"
        "- Certainty: 0.8\n- Maturity: finding\n- Supports: F-001\n"
        "- Replicated: yes\n\n"
        "## E-002: Admin takeover claim refuted by replay\n"
        "- Certainty: 0.8\n- Maturity: candidate\n- Refutes: H-009\n"
        "- Replicated: yes\n",
        encoding="utf-8")
    collab_truth = {
        "name": "collab",
        "expected_findings": [
            {"id": "idor", "markers": ["profile idor", "identity-auth"], "min_certainty": 0.8},
        ],
        "expected_collaboration": {
            "min_agent_coverage": 1.0,
            "front_roles": {"F-001": ["web-auth", "verify"]},
            "require_conflicts_resolved": True,
            "max_requests_per_agent": 2,
            "require_no_missed_high_value": True,
        },
    }
    sco = score(run5, collab_truth)
    checks.append(("协作: high-value front 被合适 role 覆盖", sco["collaboration"]["checks"][0]["ok"]))
    checks.append(("协作: candidate/refutation-to-finding conversion 记录",
                   sco["collaboration"]["candidate_to_finding_conversion"] == 0.5))
    checks.append(("协作: resolved conflict 不破门",
                   sco["collaboration"]["conflicts_total"] == 1
                   and sco["collaboration"]["conflicts_unresolved"] == 0))
    checks.append(("协作: request budget by agent 记录且未超 cap",
                   sco["collaboration"]["request_budget_by_agent"].get("A-web-auth-001") == 2
                   and all(c["ok"] for c in sco["collaboration"]["checks"])))
    checks.append(("协作: time-to-first-evidence by mode 记录",
                   sco["collaboration"]["time_to_first_evidence_by_mode_sec"].get("A-web-auth-001") == 2.5))
    checks.append(("协作: false-positive suppression 记录 pure negative confirmed event",
                   sco["collaboration"]["false_positive_suppression_events"] == 1))
    checks.append(("协作: 无 canonical plan 时 lane capture 不猜测分母",
                   sco["collaboration"]["effective_lane_capture_rate"] is None))
    checks.append(("协作门: checks 全绿 -> clean", _is_clean(sco)))

    run6 = d / "collab_bad_20260101"
    (run6 / "state").mkdir(parents=True)
    (run6 / "agents").mkdir()
    (run6 / "frontier.md").write_text((run5 / "frontier.md").read_text(encoding="utf-8"), encoding="utf-8")
    (run6 / "state" / "assignments.json").write_text(json.dumps({
        "schema": 1,
        "assignments": [{"agent": "A-surface-001", "role": "surface", "front": "F-002"}],
    }, ensure_ascii=False, indent=2), encoding="utf-8")
    (run6 / "agents" / "A-surface-001.md").write_text(
        "# Agent A-surface-001\n- Role: surface\n- Assigned front: F-002\n- Status: done\n"
        "- Maturity: phenomenon\n- Confidence: 0.5\n",
        encoding="utf-8")
    (run6 / "state" / "conflicts.json").write_text(json.dumps({
        "schema": 1,
        "conflicts": [{"id": "C-001", "type": "direct contradiction", "status": "open"}],
    }, ensure_ascii=False, indent=2), encoding="utf-8")
    (run6 / "state" / "events.jsonl").write_text(
        '{"ts": 1.0, "type": "request", "agent": "A-surface-001"}\n'
        '{"ts": 2.0, "type": "request", "agent": "A-surface-001"}\n'
        '{"ts": 3.0, "type": "request", "agent": "A-surface-001"}\n',
        encoding="utf-8")
    (run6 / "evidence.md").write_text(
        "# Evidence Ledger\n\n## E-001: Profile IDOR confirms identity-auth exposure\n"
        "- Certainty: 0.8\n- Maturity: finding\n- Supports: F-001\n- Replicated: yes\n",
        encoding="utf-8")
    sbad = score(run6, collab_truth)
    checks.append(("协作门: high-value miss / unresolved conflict / over cap -> 非 clean",
                   not _is_clean(sbad)
                   and sbad["collaboration"]["missed_high_value_fronts"] == ["F-001"]
                   and sbad["collaboration"]["conflicts_unresolved"] == 1
                   and sbad["collaboration"]["request_budget_by_agent"].get("A-surface-001") == 3))
    run7 = d / "collab_no_events_20260101"
    (run7 / "state").mkdir(parents=True)
    (run7 / "agents").mkdir()
    (run7 / "frontier.md").write_text((run5 / "frontier.md").read_text(encoding="utf-8"), encoding="utf-8")
    (run7 / "state" / "assignments.json").write_text((run5 / "state" / "assignments.json").read_text(
        encoding="utf-8"), encoding="utf-8")
    (run7 / "state" / "conflicts.json").write_text((run5 / "state" / "conflicts.json").read_text(
        encoding="utf-8"), encoding="utf-8")
    (run7 / "agents" / "A-web-auth-001.md").write_text((run5 / "agents" / "A-web-auth-001.md").read_text(
        encoding="utf-8"), encoding="utf-8")
    (run7 / "evidence.md").write_text((run5 / "evidence.md").read_text(encoding="utf-8"), encoding="utf-8")
    snoevents = score(run7, collab_truth)
    budget_check = [c for c in snoevents["collaboration"]["checks"] if c["id"] == "request-budget-by-agent"][0]
    checks.append(("协作门: 要求 per-agent budget 但缺 events -> skipped 且非 clean",
                   not _is_clean(snoevents) and budget_check.get("skipped")
                   and budget_check.get("reason") == "state/events.jsonl missing"))
    lane_run = d / "lane_capture_20260101"
    (lane_run / "state").mkdir(parents=True)
    (lane_run / "state" / "work_plan.json").write_text(json.dumps({
        "lanes": [{"id": "L-001"}],
    }), encoding="utf-8")
    (lane_run / "state" / "assignments.json").write_text(json.dumps({
        "assignments": [
            {"lane_id": "L-001"}, {"lane_id": "L-stale"},
        ],
    }), encoding="utf-8")
    lane_metrics = _collaboration_metrics(lane_run, {})
    checks.append(("协作: lane capture 只计算当前 plan 交集且不超过 1",
                   lane_metrics["effective_lane_capture_rate"] == 1.0))
    summ2 = _summary([sco, sbad])["summary"]
    checks.append(("协作汇总: failed checks / missed high / unresolved conflict 可见",
                   summ2["collaboration_checks_failed"] >= 3
                   and summ2["missed_high_value_fronts"] == 1
                   and summ2["conflicts_unresolved"] == 1))

    # compare is a real regression gate, not just display.
    base = d / "base.json"
    change_ok = d / "change-ok.json"
    change_bad = d / "change-bad.json"
    base.write_text(json.dumps({"summary": {"detection_rate": 1.0, "calibration_rate": 1.0,
                                            "false_positives": 0, "false_positive_rate_mean": 0.0,
                                            "request_budget_total": 10, "request_budget_over": 0,
                                            "time_to_first_evidence_avg_sec": 2.0,
                                            "closure_reopen_events": 0,
                                            "closure_correct": 1,
                                            "missed_high_value_fronts": 0,
                                            "role_mismatched_fronts": 0,
                                            "conflicts_unresolved": 0,
                                            "collaboration_checks_failed": 0,
                                            "agent_first_evidence_avg_sec": 2.0,
                                            "false_positive_suppression_events": 1}}, ensure_ascii=False), encoding="utf-8")
    change_ok.write_text(json.dumps({"summary": {"detection_rate": 1.0, "calibration_rate": 1.0,
                                                 "false_positives": 0, "false_positive_rate_mean": 0.0,
                                                 "request_budget_total": 10, "request_budget_over": 0,
                                                 "time_to_first_evidence_avg_sec": 2.0,
                                                 "closure_reopen_events": 0,
                                                 "closure_correct": 1,
                                                 "missed_high_value_fronts": 0,
                                                 "role_mismatched_fronts": 0,
                                                 "conflicts_unresolved": 0,
                                                 "collaboration_checks_failed": 0,
                                                 "agent_first_evidence_avg_sec": 2.0,
                                                 "false_positive_suppression_events": 1}}, ensure_ascii=False), encoding="utf-8")
    change_bad.write_text(json.dumps({"summary": {"detection_rate": 0.5, "calibration_rate": 1.0,
                                                  "false_positives": 1, "false_positive_rate_mean": 0.5,
                                                  "request_budget_total": 12, "request_budget_over": 1,
                                                  "time_to_first_evidence_avg_sec": 3.0,
                                                  "closure_reopen_events": 1,
                                                  "closure_correct": 1,
                                                  "missed_high_value_fronts": 1,
                                                  "role_mismatched_fronts": 1,
                                                  "conflicts_unresolved": 1,
                                                  "collaboration_checks_failed": 2,
                                                  "agent_first_evidence_avg_sec": 4.0,
                                                  "false_positive_suppression_events": 0}}, ensure_ascii=False), encoding="utf-8")
    with contextlib.redirect_stdout(io.StringIO()):
        cmp_ok = _compare(base, change_ok)
        cmp_bad = _compare(base, change_bad)
    checks.append(("compare: unchanged metrics exit 0", cmp_ok == 0))
    checks.append(("compare: worse metrics exit 1", cmp_bad == 1))
    ab_soft = scheduler_ab_decision({
        "modes": {
            "root_direct": {"quality": 0.8, "elapsed_sec": 10, "coverage": 0.5,
                            "merge_cost": 0, "requests": 2, "tokens": 100},
            "serial_agent": {"quality": 0.9, "elapsed_sec": 8, "coverage": 0.7,
                             "merge_cost": 1, "requests": 2, "tokens": 150},
            "parallel_agent": {"quality": 0.9, "elapsed_sec": 5, "coverage": 0.8,
                               "merge_cost": 4, "requests": 2, "tokens": 220},
        },
        "caps": {"merge_cost": 2, "requests": 3, "tokens": 300},
    })
    checks.append(("scheduler A/B keeps parallel soft when merge overhead loses",
                   ab_soft["decision"] == "soft-recommendation-only"
                   and not ab_soft["checks"]["overhead_within_caps"]))
    try:
        scheduler_ab_decision({
            "modes": {
                name: {
                    "quality": 1, "elapsed_sec": 1, "coverage": 1,
                    "merge_cost": 0, "requests": 0, "tokens": 0,
                }
                for name in ("root_direct", "serial_agent", "parallel_agent")
            },
        })
        missing_caps_closed = False
    except ValueError as exc:
        missing_caps_closed = str(exc) == "SCHEDULER_AB_CAPS_INVALID"
    checks.append(("scheduler A/B requires explicit finite caps",
                   missing_caps_closed))
    malformed_ab = {
        "modes": {
            name: {
                "quality": 1, "elapsed_sec": 1, "coverage": 1,
                "merge_cost": 0, "requests": 0, "tokens": 0,
            }
            for name in ("root_direct", "serial_agent", "parallel_agent")
        },
        "caps": {"merge_cost": 1, "requests": 1, "tokens": 1},
    }
    malformed_ab["modes"]["parallel_agent"]["quality"] = "NaN"
    try:
        scheduler_ab_decision(malformed_ab)
        malformed_row_closed = False
    except ValueError as exc:
        malformed_row_closed = (
            str(exc) == "SCHEDULER_AB_ROW_INVALID:parallel_agent"
        )
    checks.append(("scheduler A/B rejects non-finite row metrics stably",
                   malformed_row_closed))
    expected_mismatch = dict(malformed_ab)
    expected_mismatch["modes"] = {
        name: {
            "quality": 1, "elapsed_sec": 1, "coverage": 1,
            "merge_cost": 0, "requests": 0, "tokens": 0,
        }
        for name in ("root_direct", "serial_agent", "parallel_agent")
    }
    expected_mismatch["expected_decision"] = "hard-gate-eligible"
    try:
        scheduler_ab_decision(expected_mismatch)
        expected_mismatch_closed = False
    except ValueError as exc:
        expected_mismatch_closed = (
            str(exc) == "SCHEDULER_AB_EXPECTED_MISMATCH"
        )
    checks.append(("scheduler A/B binds the recorded expected decision",
                   expected_mismatch_closed))

    # Keep the checked-in Ultra-native collaboration fixture from drifting.
    fixture_truth = ROOT / "bench" / "ultra-agent-collab" / "truth.json"
    if fixture_truth.exists():
        fixture_run = fixture_truth.parent / "sample_run"
        sfix = score(fixture_run, _load_truth(fixture_truth))
        checks.append(("checked-in ultra-agent-collab fixture stays clean",
                       _is_clean(sfix) and sfix["collaboration"]["checks"]
                       and sfix["collaboration"]["conflicts_unresolved"] == 0))

    bad = [n for n, ok in checks if not ok]
    for n, ok in checks:
        print(("ok   " if ok else "FAIL ") + n)
    print("bench selftest " + ("passed" if not bad else f"FAILED ({len(bad)})"))
    return 0 if not bad else 1


if __name__ == "__main__":
    raise SystemExit(main())
