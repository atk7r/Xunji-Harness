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
- tool-friction: expected_tool_friction 显式启用后，读取 hash-chain-valid 的 typed
               AgentToolCallClaim/denial/Post 与 exact child transcript terminal，度量 denial、
               invalid argv、non-denied terminal、prepared-capability marker hit。claim 的
               success=false 只是预算预留，不是失败；identity 歧义/漂移/缺失一律 unknown。
               unknown 必须为 0，且 fixture 必须声明至少一个 threshold 才能 clean。

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
import evidence_parse   # 复用唯一权威证据解析器(独立模块, 不必拉整个收口门 check_run)
import runtime_receipts  # typed child tool-call outcomes; read-only projection

_E_BLOCK = re.compile(r"(?ms)^##\s+(E-\d+[a-z]*).*?(?=^##\s+E-|\Z)")


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
    out = {"event_requests": 0, "time_to_first_evidence_sec": None}
    if not p.exists():
        return out
    out["timeline_source"] = str(p.relative_to(run_dir))
    if p.name == "events.jsonl" and p.parent == run_dir:
        out["timeline_warning"] = "legacy root events.jsonl fallback; prefer state/events.jsonl"
    first_activity = None
    first_evidence = None
    for line in p.read_text(encoding="utf-8", errors="replace").splitlines():
        try:
            ev = json.loads(line)
            ts = float(ev.get("ts"))
        except Exception:
            continue
        typ = str(ev.get("type", "")).lower()
        if typ == "request":
            out["event_requests"] += 1
        if typ in {"request", "action"} and first_activity is None:
            first_activity = ts
        if typ == "evidence" and first_evidence is None:
            first_evidence = ts
    if first_activity is not None and first_evidence is not None and first_evidence >= first_activity:
        out["time_to_first_evidence_sec"] = round(first_evidence - first_activity, 3)
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


_TOOL_FRICTION_THRESHOLDS = {
    "min_attempted_calls": ("tool_calls_attempted", ">=", "count"),
    "max_denied_calls": ("tool_calls_denied", "<=", "count"),
    "max_denial_rate": ("tool_denial_rate", "<=", "rate"),
    "max_invalid_argv_denials": (
        "tool_invalid_argv_denials", "<=", "count"),
    "max_invalid_argv_rate": ("tool_invalid_argv_rate", "<=", "rate"),
    "max_post_failures": ("tool_post_failures", "<=", "count"),
    "min_non_denied_terminals": (
        "tool_non_denied_terminals", ">=", "count"),
    "min_non_denied_terminal_rate": (
        "tool_non_denied_terminal_rate", ">=", "rate"),
    "min_prepared_capability_hits": (
        "tool_prepared_capability_hits", ">=", "count"),
    "min_prepared_capability_hit_rate": (
        "tool_prepared_capability_hit_rate", ">=", "rate"),
}
_TOOL_FRICTION_PREPARED_THRESHOLDS = {
    "min_prepared_capability_hits", "min_prepared_capability_hit_rate",
}
_TOOL_OUTCOME_FIELDS = {
    "schema", "integrity", "attempted_calls", "outcomes",
    "invalid_argv_denials", "non_denied_terminals",
    "prepared_capability_hits", "prepared_capability_offered_calls",
    "prepared_attribution_unknown", "denial_rate", "invalid_argv_rate",
    "non_denied_terminal_rate", "prepared_capability_hit_rate",
    "unknown_reason_counts",
}
_TOOL_OUTCOME_BUCKETS = {
    "denied", "post_success", "post_failure",
    "xunji_non_denied_terminal", "unknown",
}


def _tool_outcome_shape_errors(value: object) -> list[str]:
    """Validate the complete aggregate contract without exposing private data."""
    if not isinstance(value, dict):
        return ["not-object"]
    errors: list[str] = []
    if set(value) != _TOOL_OUTCOME_FIELDS:
        errors.append("top-level-fields")
    if value.get("schema") != "xunji.agent-tool-call-outcomes.v1":
        errors.append("schema")
    if value.get("integrity") not in {"valid", "unknown"}:
        errors.append("integrity")

    def count(field: str, source: dict | None = None) -> int | None:
        owner = source if source is not None else value
        raw = owner.get(field)
        if isinstance(raw, bool) or not isinstance(raw, int) or raw < 0:
            errors.append("count:" + field)
            return None
        return raw

    attempted = count("attempted_calls")
    outcomes = value.get("outcomes")
    if not isinstance(outcomes, dict) or set(outcomes) != _TOOL_OUTCOME_BUCKETS:
        errors.append("outcome-fields")
        outcomes = {}
    bucket_counts = {
        field: count(field, outcomes) for field in sorted(_TOOL_OUTCOME_BUCKETS)
    }
    invalid_argv = count("invalid_argv_denials")
    non_denied = count("non_denied_terminals")
    prepared_hits = count("prepared_capability_hits")
    prepared_offered = count("prepared_capability_offered_calls")
    prepared_unknown = count("prepared_attribution_unknown")

    complete_buckets = all(item is not None for item in bucket_counts.values())
    if attempted is not None and complete_buckets \
            and sum(int(item) for item in bucket_counts.values()) != attempted:
        errors.append("attempt-outcome-total")
    denied = bucket_counts.get("denied")
    if invalid_argv is not None and denied is not None and invalid_argv > denied:
        errors.append("invalid-argv-subset")
    expected_non_denied = None
    if all(bucket_counts.get(field) is not None for field in (
            "post_success", "post_failure", "xunji_non_denied_terminal")):
        expected_non_denied = sum(int(bucket_counts[field]) for field in (
            "post_success", "post_failure", "xunji_non_denied_terminal"))
    if non_denied is not None and expected_non_denied is not None \
            and non_denied != expected_non_denied:
        errors.append("non-denied-total")
    if prepared_hits is not None and prepared_offered is not None \
            and prepared_hits > prepared_offered:
        errors.append("prepared-hit-subset")
    if attempted is not None and prepared_offered is not None \
            and prepared_offered > attempted:
        errors.append("prepared-offered-total")
    if attempted is not None and prepared_unknown is not None \
            and prepared_unknown > attempted:
        errors.append("prepared-unknown-total")
    if attempted is not None and prepared_offered is not None \
            and prepared_unknown is not None \
            and prepared_offered + prepared_unknown > attempted:
        errors.append("prepared-attribution-total")

    def expected_rate(numerator: int | None, denominator: int | None) -> float | None:
        if numerator is None or denominator is None or denominator == 0:
            return None
        return round(numerator / denominator, 6)

    def check_rate(field: str, expected: float | None) -> None:
        raw = value.get(field)
        if expected is None:
            if raw is not None:
                errors.append("rate:" + field)
            return
        if isinstance(raw, bool) or not isinstance(raw, (int, float)) \
                or not math.isfinite(float(raw)) \
                or not math.isclose(float(raw), expected, abs_tol=1e-9):
            errors.append("rate:" + field)

    check_rate("denial_rate", expected_rate(denied, attempted))
    check_rate("invalid_argv_rate", expected_rate(invalid_argv, attempted))
    check_rate("non_denied_terminal_rate", expected_rate(non_denied, attempted))
    check_rate(
        "prepared_capability_hit_rate",
        expected_rate(prepared_hits, prepared_offered),
    )

    reasons = value.get("unknown_reason_counts")
    if not isinstance(reasons, dict):
        errors.append("unknown-reasons")
    else:
        reason_total = 0
        for name, raw in reasons.items():
            if not isinstance(name, str) \
                    or not re.fullmatch(r"[a-z][a-z0-9_-]{0,63}", name) \
                    or isinstance(raw, bool) or not isinstance(raw, int) or raw < 1:
                errors.append("unknown-reasons")
                break
            reason_total += raw
        unknown = bucket_counts.get("unknown")
        if unknown is not None and reason_total != unknown:
            errors.append("unknown-reason-total")
    return sorted(set(errors))


def _tool_friction_metrics(run_dir: Path, truth: dict) -> dict | None:
    """Evaluate explicitly requested, receipt-backed Agent tool friction.

    Old fixtures keep their scoring and exit behavior: runtime receipts are not
    loaded unless ``expected_tool_friction`` is present in truth.  JSON output is
    additive rather than byte-for-byte stable.  The public projection is
    aggregate-only and carries no commands, paths, URLs, or result bytes.
    """
    if "expected_tool_friction" not in truth:
        return None
    spec = truth.get("expected_tool_friction")
    spec_valid = isinstance(spec, dict)
    spec = spec if isinstance(spec, dict) else {}
    unknown_keys = sorted(set(spec) - set(_TOOL_FRICTION_THRESHOLDS))
    declared = [key for key in _TOOL_FRICTION_THRESHOLDS if key in spec]
    thresholds_valid = bool(declared) and spec_valid and not unknown_keys

    producer_error = False
    try:
        raw_outcome = runtime_receipts.agent_tool_call_outcomes(run_dir)
    except Exception:
        # This is a scoring boundary, so an unexpected producer failure must
        # remain a failed measurement instead of crashing an entire score-all
        # batch. Expose only a stable reason code: exception text can contain
        # private paths, commands, or imported target data.
        producer_error = True
        raw_outcome = {}
    shape_errors = _tool_outcome_shape_errors(raw_outcome)
    if producer_error:
        shape_errors = sorted({*shape_errors, "producer-error"})
    outcome = raw_outcome if isinstance(raw_outcome, dict) else {}
    raw_outcomes = outcome.get("outcomes") \
        if isinstance(outcome.get("outcomes"), dict) else {}

    def nonnegative_int(value: object, default: int = 0) -> int:
        return value if isinstance(value, int) and not isinstance(value, bool) \
            and value >= 0 else default

    attempted = nonnegative_int(outcome.get("attempted_calls"))
    denied = nonnegative_int(raw_outcomes.get("denied"))
    post_failures = nonnegative_int(raw_outcomes.get("post_failure"))
    unknown = nonnegative_int(raw_outcomes.get("unknown"), 1)
    invalid_argv = nonnegative_int(outcome.get("invalid_argv_denials"))
    non_denied = nonnegative_int(outcome.get("non_denied_terminals"))
    prepared_hits = nonnegative_int(outcome.get("prepared_capability_hits"))
    prepared_offered = nonnegative_int(
        outcome.get("prepared_capability_offered_calls"))
    prepared_unknown = nonnegative_int(
        outcome.get("prepared_attribution_unknown"), attempted or 1)

    def rate(name: str) -> float | None:
        value = outcome.get(name)
        if isinstance(value, (int, float)) and not isinstance(value, bool) \
                and 0.0 <= float(value) <= 1.0:
            return float(value)
        return None

    values: dict[str, int | float | None] = {
        "tool_calls_attempted": attempted,
        "tool_calls_denied": denied,
        "tool_denial_rate": rate("denial_rate"),
        "tool_invalid_argv_denials": invalid_argv,
        "tool_invalid_argv_rate": rate("invalid_argv_rate"),
        "tool_post_failures": post_failures,
        "tool_non_denied_terminals": non_denied,
        "tool_non_denied_terminal_rate": rate("non_denied_terminal_rate"),
        "tool_prepared_capability_hits": prepared_hits,
        "tool_prepared_capability_offered_calls": prepared_offered,
        "tool_prepared_capability_hit_rate": rate(
            "prepared_capability_hit_rate"),
        "tool_prepared_attribution_unknown": prepared_unknown,
        "tool_outcome_unknown": unknown,
    }
    checks: list[dict] = [{
        "id": "outcome-shape",
        "metric": "shape",
        "actual": ",".join(shape_errors) if shape_errors else "valid",
        "expected": "valid",
        "ok": not shape_errors,
    }, {
        "id": "outcome-integrity",
        "metric": "integrity",
        "actual": str(outcome.get("integrity") or "unknown"),
        "expected": "valid",
        "ok": outcome.get("schema") == "xunji.agent-tool-call-outcomes.v1"
        and outcome.get("integrity") == "valid",
    }, {
        "id": "unknown-zero",
        "metric": "tool_outcome_unknown",
        "actual": unknown,
        "threshold": 0,
        "op": "==",
        "ok": unknown == 0,
    }]
    if not thresholds_valid:
        checks.append({
            "id": "threshold-schema",
            "metric": "expected_tool_friction",
            "actual": (
                "unknown keys: " + ",".join(unknown_keys)
                if unknown_keys else "no valid threshold declared"),
            "ok": False,
        })

    prepared_required = any(
        key in _TOOL_FRICTION_PREPARED_THRESHOLDS for key in declared)
    if prepared_required:
        checks.append({
            "id": "prepared-attribution-known",
            "metric": "tool_prepared_attribution_unknown",
            "actual": prepared_unknown,
            "threshold": 0,
            "op": "==",
            "ok": prepared_unknown == 0,
        })

    required_metrics = {"tool_outcome_unknown"}
    if prepared_required:
        required_metrics.update({
            "tool_prepared_attribution_unknown",
            "tool_prepared_capability_offered_calls",
        })
    for name in declared:
        metric, op, kind = _TOOL_FRICTION_THRESHOLDS[name]
        required_metrics.add(metric)
        raw_threshold = spec.get(name)
        valid_threshold = (
            isinstance(raw_threshold, int) and not isinstance(raw_threshold, bool)
            and raw_threshold >= 0
            if kind == "count"
            else isinstance(raw_threshold, (int, float))
            and not isinstance(raw_threshold, bool)
            and 0.0 <= float(raw_threshold) <= 1.0
        )
        threshold = int(raw_threshold) if valid_threshold and kind == "count" \
            else float(raw_threshold) if valid_threshold else None
        actual = values.get(metric)
        ok = bool(
            valid_threshold and actual is not None
            and (float(actual) >= float(threshold) if op == ">="
                 else float(actual) <= float(threshold))
        )
        checks.append({
            "id": name.replace("_", "-"),
            "metric": metric,
            "actual": actual,
            "threshold": threshold,
            "op": op,
            "ok": ok,
        })
    return {
        "enabled": True,
        "thresholds_declared": thresholds_valid,
        "required_metrics": sorted(required_metrics),
        **values,
        "checks": checks,
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
    tool_friction = _tool_friction_metrics(run_dir, truth)
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
        "closure": closure,
        "findings": findings, "fp_detail": fps,
        "process": proc,
        "collaboration": collaboration,
        "tool_friction": tool_friction,
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
    friction = s.get("tool_friction")
    if isinstance(friction, dict):
        failed = [c for c in friction.get("checks", []) if not c.get("ok")]
        print(
            "  tool friction: "
            f"attempted={friction.get('tool_calls_attempted', 0)} "
            f"denied={friction.get('tool_calls_denied', 0)} "
            f"invalid-argv={friction.get('tool_invalid_argv_denials', 0)} "
            f"non-denied-terminal={friction.get('tool_non_denied_terminals', 0)} "
            f"prepared-hit={friction.get('tool_prepared_capability_hits', 0)}/"
            f"{friction.get('tool_prepared_capability_offered_calls', 0)} offered "
            f"unknown={friction.get('tool_outcome_unknown', 0)}"
        )
        if failed:
            print("  tool-friction checks failed: " + ", ".join(
                str(c.get("id")) for c in failed))


def _is_clean(s: dict) -> bool:
    """完美 = 全检出 + 全校准 + 零误报 + 预算内 + must 过程断言触发。"""
    proc_ok = all(p["fired"] for p in s.get("process", []) if p["must"])
    closure = s.get("closure")
    closure_ok = closure is None or closure["correct"]
    collab = s.get("collaboration") or {}
    collab_ok = all(c.get("ok") for c in collab.get("checks", []))
    friction = s.get("tool_friction")
    friction_ok = friction is None or bool(
        isinstance(friction, dict)
        and friction.get("thresholds_declared") is True
        and friction.get("tool_outcome_unknown") == 0
        and all(c.get("ok") for c in friction.get("checks", []))
    )
    detection_ok = (
        (s["expected"] > 0 and s["detected"] == s["expected"]
         and s["calibrated"] == s["expected"])
        or s["expected"] == 0
    )
    return (detection_ok and s["false_positives"] == 0 and not s.get("over_budget", False)
            and proc_ok and closure_ok and collab_ok and friction_ok)


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
    friction_scores = [
        (s, s.get("tool_friction")) for s in scores
        if isinstance(s.get("tool_friction"), dict)
    ]
    frictions = [tf for _score, tf in friction_scores]
    tool_fixture_ids = sorted(
        str(score.get("fixture") or "") for score, _tf in friction_scores)
    tool_fixture_ids_unique = bool(
        all(tool_fixture_ids)
        and len(tool_fixture_ids) == len(set(tool_fixture_ids))
    ) if tool_fixture_ids else True
    tool_attempted = sum(int(tf.get("tool_calls_attempted", 0)) for tf in frictions)
    tool_denied = sum(int(tf.get("tool_calls_denied", 0)) for tf in frictions)
    tool_invalid = sum(int(tf.get("tool_invalid_argv_denials", 0)) for tf in frictions)
    tool_non_denied = sum(int(tf.get("tool_non_denied_terminals", 0)) for tf in frictions)
    tool_prepared = sum(int(tf.get("tool_prepared_capability_hits", 0)) for tf in frictions)
    tool_prepared_offered = sum(
        int(tf.get("tool_prepared_capability_offered_calls", 0))
        for tf in frictions)
    tool_required = sorted({
        str(metric)
        for tf in frictions
        for metric in tf.get("required_metrics", [])
        if str(metric)
    })
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
        "tool_friction_fixtures": len(frictions),
        "tool_friction_fixture_ids": tool_fixture_ids,
        "tool_friction_fixture_ids_unique": tool_fixture_ids_unique,
        "tool_friction_checks_failed": sum(
            1 for tf in frictions for check in tf.get("checks", [])
            if not check.get("ok")),
        "tool_friction_required_metrics": tool_required,
        "tool_calls_attempted": tool_attempted if frictions else None,
        "tool_calls_denied": tool_denied if frictions else None,
        "tool_denial_rate": (
            round(tool_denied / tool_attempted, 6) if tool_attempted else None),
        "tool_invalid_argv_denials": tool_invalid if frictions else None,
        "tool_invalid_argv_rate": (
            round(tool_invalid / tool_attempted, 6) if tool_attempted else None),
        "tool_post_failures": sum(
            int(tf.get("tool_post_failures", 0)) for tf in frictions)
            if frictions else None,
        "tool_non_denied_terminals": tool_non_denied if frictions else None,
        "tool_non_denied_terminal_rate": (
            round(tool_non_denied / tool_attempted, 6) if tool_attempted else None),
        "tool_prepared_capability_hits": tool_prepared if frictions else None,
        "tool_prepared_capability_offered_calls": (
            tool_prepared_offered if frictions else None),
        "tool_prepared_capability_hit_rate": (
            round(tool_prepared / tool_prepared_offered, 6)
            if tool_prepared_offered else None),
        "tool_prepared_attribution_unknown": sum(
            int(tf.get("tool_prepared_attribution_unknown", 0)) for tf in frictions)
            if frictions else None,
        "tool_outcome_unknown": sum(
            int(tf.get("tool_outcome_unknown", 0)) for tf in frictions)
            if frictions else None,
        "total_expected_findings": total_expected,
        "total_detected_findings": total_detected,
        "total_calibrated_findings": total_calibrated,
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
    if a.get("tool_friction_fixtures"):
        print(
            "  tool friction: "
            f"{a['tool_friction_fixtures']} fixture(s); "
            f"attempted={a['tool_calls_attempted']} denied={a['tool_calls_denied']} "
            f"invalid-argv={a['tool_invalid_argv_denials']} "
            f"non-denied-terminal={a['tool_non_denied_terminals']} "
            f"prepared-hit={a['tool_prepared_capability_hits']}/"
            f"{a['tool_prepared_capability_offered_calls']} offered "
            f"unknown={a['tool_outcome_unknown']} "
            f"check-fail={a['tool_friction_checks_failed']}"
        )


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
        "closure_correct", "missed_high_value_fronts", "role_mismatched_fronts",
        "conflicts_unresolved", "collaboration_checks_failed", "agent_first_evidence_avg_sec",
        "false_positive_suppression_events",
        "tool_calls_attempted", "tool_calls_denied", "tool_denial_rate",
        "tool_invalid_argv_denials", "tool_invalid_argv_rate",
        "tool_post_failures", "tool_non_denied_terminals",
        "tool_non_denied_terminal_rate", "tool_prepared_capability_hits",
        "tool_prepared_capability_offered_calls",
        "tool_prepared_capability_hit_rate",
        "tool_prepared_attribution_unknown", "tool_outcome_unknown",
        "tool_friction_checks_failed",
    ]
    higher_is_better = {
        "detection_rate", "calibration_rate", "closure_correct",
        "false_positive_suppression_events",
        "tool_non_denied_terminal_rate", "tool_prepared_capability_hit_rate",
    }
    lower_is_better = {
        "false_positives", "false_positive_rate_mean", "request_budget_total",
        "request_budget_over", "time_to_first_evidence_avg_sec", "missed_high_value_fronts",
        "role_mismatched_fronts", "conflicts_unresolved", "collaboration_checks_failed",
        "agent_first_evidence_avg_sec",
        "tool_calls_denied", "tool_denial_rate", "tool_invalid_argv_denials",
        "tool_invalid_argv_rate", "tool_post_failures",
        "tool_prepared_attribution_unknown", "tool_outcome_unknown",
        "tool_friction_checks_failed",
    }
    regressed = False
    print("== bench compare ==")
    print(f"  baseline: {baseline}")
    print(f"  change  : {change}")

    def fixture_ids(source: dict) -> list[str] | None:
        raw = source.get("tool_friction_fixture_ids")
        if not isinstance(raw, list) \
                or any(not isinstance(item, str) or not item for item in raw) \
                or len(raw) != len(set(raw)):
            return None
        return sorted(raw)

    def required_metrics(source: dict) -> list[str] | None:
        raw = source.get("tool_friction_required_metrics")
        if not isinstance(raw, list) \
                or any(not isinstance(item, str) or not item for item in raw) \
                or len(raw) != len(set(raw)):
            return None
        return sorted(raw)

    friction_present = any(
        (source.get("tool_friction_fixtures") is not None
         and source.get("tool_friction_fixtures") != 0)
        or bool(source.get("tool_friction_fixture_ids"))
        or bool(source.get("tool_friction_required_metrics"))
        or (source.get("tool_friction_checks_failed") is not None
            and source.get("tool_friction_checks_failed") != 0)
        for source in (b, c)
    )
    b_ids: list[str] = []
    c_ids: list[str] = []
    b_required: list[str] = []
    c_required: list[str] = []
    if friction_present:
        populations_valid = True
        for label, source in (("baseline", b), ("change", c)):
            ids = fixture_ids(source)
            count = source.get("tool_friction_fixtures")
            unique = source.get("tool_friction_fixture_ids_unique")
            if ids is None or isinstance(count, bool) \
                    or not isinstance(count, int) or count < 0 \
                    or count != len(ids) or unique is not True:
                populations_valid = False
                regressed = True
                print(f"  tool_friction_fixture_ids: INVALID in {label}")
            elif label == "baseline":
                b_ids = ids
            else:
                c_ids = ids
        if populations_valid and b_ids != c_ids:
            regressed = True
            print("  tool_friction_fixture_ids: POPULATION_MISMATCH")

        baseline_required = required_metrics(b)
        change_required = required_metrics(c)
        if baseline_required is None or change_required is None:
            regressed = True
            print("  tool_friction_required_metrics: INVALID")
        else:
            b_required = baseline_required
            c_required = change_required
            if b_required != c_required:
                regressed = True
                print("  tool_friction_required_metrics: CONTRACT_MISMATCH")

        def change_zero(field: str) -> None:
            nonlocal regressed
            value = c.get(field)
            if isinstance(value, bool) or not isinstance(value, int) or value != 0:
                regressed = True
                print(f"  {field}: CHANGE_MUST_BE_ZERO")

        change_zero("tool_friction_checks_failed")
        change_zero("tool_outcome_unknown")
        if "tool_prepared_attribution_unknown" in c_required:
            change_zero("tool_prepared_attribution_unknown")

    required = set(b_required) | set(c_required)
    for metric in sorted(required):
        missing = [
            label for label, source in (("baseline", b), ("change", c))
            if metric not in source or source.get(metric) is None
        ]
        if missing:
            regressed = True
            print(
                f"  {metric}: MISSING_REQUIRED in " + ",".join(missing))
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
        if summary["summary"].get("tool_friction_fixture_ids_unique") is not True:
            worst = 1
        _write_json(args.json_out, summary)
        if args.json:
            print(json.dumps(summary, ensure_ascii=False, indent=2))
        else:
            _print_summary(summary)
        return worst
    if args.cmd == "compare":
        return _compare(args.baseline, args.change)
    ap.print_help()
    return 2


def _selftest() -> int:
    import contextlib
    import io
    import tempfile
    from unittest import mock
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
    with mock.patch.object(
            runtime_receipts, "agent_tool_call_outcomes",
            side_effect=AssertionError("legacy fixture loaded runtime receipts")):
        legacy_score = score(run2, {
            "name": "legacy-no-tool-friction",
            "expected_findings": [
                {"id": "sqli", "markers": ["sql injection"], "min_certainty": 0.8},
                {"id": "xss", "markers": ["reflected xss"], "min_certainty": 0.8},
            ],
        })
    checks.append(("旧 fixture 未声明 expected_tool_friction 时不加载 runtime receipts",
                   legacy_score.get("tool_friction") is None and _is_clean(legacy_score)))

    clean_tool_outcomes = {
        "schema": "xunji.agent-tool-call-outcomes.v1",
        "integrity": "valid",
        "attempted_calls": 4,
        "outcomes": {
            "denied": 1,
            "post_success": 2,
            "post_failure": 0,
            "xunji_non_denied_terminal": 1,
            "unknown": 0,
        },
        "invalid_argv_denials": 0,
        "non_denied_terminals": 3,
        "prepared_capability_hits": 3,
        "prepared_capability_offered_calls": 4,
        "prepared_attribution_unknown": 0,
        "denial_rate": 0.25,
        "invalid_argv_rate": 0.0,
        "non_denied_terminal_rate": 0.75,
        "prepared_capability_hit_rate": 0.75,
        "unknown_reason_counts": {},
    }
    tool_truth = {
        "name": "tool-friction",
        "expected_findings": [
            {"id": "sqli", "markers": ["sql injection"], "min_certainty": 0.8},
            {"id": "xss", "markers": ["reflected xss"], "min_certainty": 0.8},
        ],
        "expected_tool_friction": {
            "min_attempted_calls": 4,
            "max_denial_rate": 0.25,
            "max_invalid_argv_denials": 0,
            "max_post_failures": 0,
            "min_non_denied_terminal_rate": 0.75,
            "min_prepared_capability_hit_rate": 0.75,
        },
    }
    with mock.patch.object(
            runtime_receipts, "agent_tool_call_outcomes",
            return_value=clean_tool_outcomes):
        tool_score = score(run2, tool_truth)
        no_threshold_score = score(run2, {
            **tool_truth, "expected_tool_friction": {},
        })
        typo_threshold_score = score(run2, {
            **tool_truth,
            "expected_tool_friction": {"max_denail_rate": 0.25},
        })
    checks.append(("工具摩擦: 声明 thresholds、unknown=0 且 prepared marker 命中 -> clean",
                   _is_clean(tool_score)
                   and tool_score["tool_friction"]["tool_calls_attempted"] == 4
                   and tool_score["tool_friction"]["tool_prepared_capability_hits"] == 3))
    checks.append(("工具摩擦: 空 thresholds 与拼错字段都 fail closed",
                   not _is_clean(no_threshold_score)
                   and not _is_clean(typo_threshold_score)))
    unknown_tool_outcomes = json.loads(json.dumps(clean_tool_outcomes))
    unknown_tool_outcomes["outcomes"]["unknown"] = 1
    unknown_tool_outcomes["outcomes"]["post_success"] = 1
    unknown_tool_outcomes["non_denied_terminals"] = 2
    unknown_tool_outcomes["non_denied_terminal_rate"] = 0.5
    with mock.patch.object(
            runtime_receipts, "agent_tool_call_outcomes",
            return_value=unknown_tool_outcomes):
        unknown_tool_score = score(run2, tool_truth)
    checks.append(("工具摩擦: 即使其它阈值可调，任何 outcome unknown 都非 clean",
                   not _is_clean(unknown_tool_score)
                   and unknown_tool_score["tool_friction"]["tool_outcome_unknown"] == 1))
    prepared_unknown_outcomes = json.loads(json.dumps(clean_tool_outcomes))
    prepared_unknown_outcomes["prepared_attribution_unknown"] = 1
    with mock.patch.object(
            runtime_receipts, "agent_tool_call_outcomes",
            return_value=prepared_unknown_outcomes):
        prepared_unknown_score = score(run2, tool_truth)
    checks.append(("工具摩擦: prepared threshold 要求完整 context descriptor 归因",
                   not _is_clean(prepared_unknown_score)))
    malformed_tool_outcomes = json.loads(json.dumps(clean_tool_outcomes))
    malformed_tool_outcomes["non_denied_terminals"] = 4
    with mock.patch.object(
            runtime_receipts, "agent_tool_call_outcomes",
            return_value=malformed_tool_outcomes):
        malformed_tool_score = score(run2, tool_truth)
    malformed_shape = next(
        check for check in malformed_tool_score["tool_friction"]["checks"]
        if check["id"] == "outcome-shape")
    checks.append(("工具摩擦: producer count/rate invariant 畸形时 fail closed",
                   not _is_clean(malformed_tool_score)
                   and not malformed_shape["ok"]
                   and "non-denied-total" in malformed_shape["actual"]))
    producer_private_error = "private-path private-command imported-bytes"
    with mock.patch.object(
            runtime_receipts, "agent_tool_call_outcomes",
            side_effect=RuntimeError(producer_private_error)):
        producer_error_score = score(run2, tool_truth)
    producer_error_shape = next(
        check for check in producer_error_score["tool_friction"]["checks"]
        if check["id"] == "outcome-shape")
    producer_error_json = json.dumps(
        producer_error_score, ensure_ascii=False, sort_keys=True)
    checks.append(("工具摩擦: producer 异常脱敏、可观测并 fail closed",
                   not _is_clean(producer_error_score)
                   and "producer-error" in producer_error_shape["actual"]
                   and producer_private_error not in producer_error_json))
    duplicate_tool_fixture_summary = _summary([tool_score, tool_score])[
        "summary"]
    checks.append(("工具摩擦: score 批次拒绝重复 truth.name fixture ID",
                   duplicate_tool_fixture_summary[
                       "tool_friction_fixture_ids_unique"] is False))
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
        '{"ts": 1.0, "type": "request"}\n{"ts": 4.0, "type": "evidence"}\n',
        encoding="utf-8")
    checks.append(("时间线: state/events.jsonl 优先",
                   _timeline_metrics(run4_state)["time_to_first_evidence_sec"] == 3.0))
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

    friction_base = d / "friction-base.json"
    friction_change_ok = d / "friction-change-ok.json"
    friction_change_missing = d / "friction-change-missing.json"
    friction_both_unknown = d / "friction-both-unknown.json"
    friction_threshold_bad = d / "friction-threshold-bad.json"
    friction_population_base = d / "friction-population-base.json"
    friction_population_drop = d / "friction-population-drop.json"
    friction_baseline_failed = d / "friction-baseline-failed.json"
    friction_prepared_unknown = d / "friction-prepared-unknown.json"
    friction_contract = {
        "tool_friction_fixtures": 1,
        "tool_friction_fixture_ids": ["tool-friction"],
        "tool_friction_fixture_ids_unique": True,
        "tool_friction_required_metrics": [
            "tool_denial_rate", "tool_outcome_unknown"],
        "tool_friction_checks_failed": 0,
    }
    friction_base.write_text(json.dumps({"summary": {
        **friction_contract,
        "tool_denial_rate": 0.25,
        "tool_outcome_unknown": 0,
    }}), encoding="utf-8")
    friction_change_ok.write_text(json.dumps({"summary": {
        **friction_contract,
        "tool_denial_rate": 0.0,
        "tool_outcome_unknown": 0,
    }}), encoding="utf-8")
    friction_change_missing.write_text(json.dumps({"summary": {
        **friction_contract,
        "tool_outcome_unknown": 0,
    }}), encoding="utf-8")
    friction_both_unknown.write_text(json.dumps({"summary": {
        **friction_contract,
        "tool_denial_rate": 0.25,
        "tool_outcome_unknown": 1,
        "tool_friction_checks_failed": 1,
    }}), encoding="utf-8")
    friction_threshold_bad.write_text(json.dumps({"summary": {
        **friction_contract,
        "tool_denial_rate": 0.0,
        "tool_outcome_unknown": 0,
        "tool_friction_checks_failed": 1,
    }}), encoding="utf-8")
    friction_population_base.write_text(json.dumps({"summary": {
        **friction_contract,
        "tool_friction_fixtures": 2,
        "tool_friction_fixture_ids": ["tool-friction", "tool-friction-hard"],
        "tool_denial_rate": 0.25,
        "tool_outcome_unknown": 0,
    }}), encoding="utf-8")
    friction_population_drop.write_text(json.dumps({"summary": {
        **friction_contract,
        "tool_denial_rate": 0.0,
        "tool_outcome_unknown": 0,
    }}), encoding="utf-8")
    friction_baseline_failed.write_text(json.dumps({"summary": {
        **friction_contract,
        "tool_denial_rate": 0.25,
        "tool_outcome_unknown": 1,
        "tool_friction_checks_failed": 1,
    }}), encoding="utf-8")
    friction_prepared_unknown.write_text(json.dumps({"summary": {
        **friction_contract,
        "tool_friction_required_metrics": [
            "tool_outcome_unknown", "tool_prepared_attribution_unknown",
            "tool_prepared_capability_hit_rate",
            "tool_prepared_capability_offered_calls",
        ],
        "tool_denial_rate": 0.0,
        "tool_outcome_unknown": 0,
        "tool_prepared_attribution_unknown": 1,
        "tool_prepared_capability_hit_rate": 0.5,
        "tool_prepared_capability_offered_calls": 4,
    }}), encoding="utf-8")
    with contextlib.redirect_stdout(io.StringIO()):
        friction_cmp_ok = _compare(friction_base, friction_change_ok)
        friction_cmp_missing = _compare(
            friction_base, friction_change_missing)
        friction_cmp_both_unknown = _compare(
            friction_both_unknown, friction_both_unknown)
        friction_cmp_threshold_bad = _compare(
            friction_base, friction_threshold_bad)
        friction_cmp_population_drop = _compare(
            friction_population_base, friction_population_drop)
        friction_cmp_improved_from_failed = _compare(
            friction_baseline_failed, friction_change_ok)
        friction_cmp_prepared_unknown = _compare(
            friction_prepared_unknown, friction_prepared_unknown)
    checks.append(("compare: tool friction required metrics 完整且改善 -> exit 0",
                   friction_cmp_ok == 0))
    checks.append(("compare: tool friction required metric 缺失 -> fail closed",
                   friction_cmp_missing == 1))
    checks.append(("compare: 双方 outcome unknown 不因相等而通过",
                   friction_cmp_both_unknown == 1))
    checks.append(("compare: change threshold/check 失败时绝对拒绝",
                   friction_cmp_threshold_bad == 1))
    checks.append(("compare: 删除 tool-friction 难例不能改善汇总",
                   friction_cmp_population_drop == 1))
    checks.append(("compare: baseline 可失败，change 修复全部绝对门后可证明改善",
                   friction_cmp_improved_from_failed == 0))
    checks.append(("compare: prepared-required attribution unknown 必须绝对为零",
                   friction_cmp_prepared_unknown == 1))

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
