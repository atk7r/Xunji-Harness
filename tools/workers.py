#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Typed Agent Board ledger and compatibility worker reader.

Current plan/delegate/launch/settlement commands are documented only by the
Claude-primary ``xunji-agent-board`` references. This module validates and
projects those contracts; it never spawns Agents or writes canonical evidence.
Legacy ``--new`` and ``workers/W-*.md`` remain non-authorizing compatibility
surfaces.
"""
from __future__ import annotations

import argparse
import collections
import contextlib
import fcntl
import hashlib
import io
import json
import os
import re
import stat
import subprocess
import sys
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path

import agent_instruction_bundle as _instruction_bundle

try:
    sys.stdout.reconfigure(encoding="utf-8")       # type: ignore[attr-defined]
except Exception:
    pass

ROOT = Path(__file__).resolve().parents[1]
COMMANDS = {
    "list", "new", "suggest", "plan", "commit-plan", "commit-proposal",
    "delegate", "assign", "cancel-unlaunched",
    "status", "agent-check",
    "heartbeat", "finish", "review-disposition", "lifecycle-check",
    "merge-check", "conflicts",
    "synthesize", "merge-constraints", "merge-threats",
}
HWS = r"[^\S\n]"
NONTERMINAL_AGENT_STATUSES = {"assigned", "starting", "running", "working", "?"}
TERMINAL_AGENT_STATUSES = {
    "done", "merged", "reviewed", "blocked", "failed", "abandoned",
}
REVIEW_DISPOSITIONS = {
    "accept-candidate", "needs-control", "duplicate", "refute",
    "out-of-scope", "retry", "blocked",
}
STALE_HEARTBEAT_SECONDS = 30 * 60
PLAN_PROPOSAL_SCHEMA = "xunji.work-plan-proposal.v1"
PLAN_PROPOSAL_FILE = "work_plan_proposal.json"
PLAN_PROPOSAL_MAX_BYTES = 64 * 1024

SATURATION_SCRIPT = ROOT / "tools" / "saturation.py"

try:
    import state_project as _state_project
except Exception:
    _state_project = None
try:
    import context_pack as _context_pack
except Exception:
    _context_pack = None
try:
    import run_model as _run_model
except Exception:
    _run_model = None
try:
    import runtime_receipts as _runtime_receipts
except Exception:
    _runtime_receipts = None
try:
    import work_plan as _work_plan
except Exception:
    _work_plan = None
try:
    import agent_settlement as _agent_settlement
except Exception:
    _agent_settlement = None
try:
    import loop_journal as _loop_journal
except Exception:
    _loop_journal = None

SCAFFOLD = """# Worker {wid}

- Assigned front: {front}
- Status: working / done / merged
- Started:

## Candidate findings

### CAND-1
- Maturity: candidate
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

ROLE_ALIASES = {
    "surface-agent": "surface",
    "surface": "surface",
    "web": "web-hunter",
    "hunter": "web-hunter",
    "web-auth": "web-auth",
    "web-hunter": "web-hunter",
    "web-hunter-agent": "web-hunter",
    "code": "code-audit",
    "code-audit": "code-audit",
    "code-audit-agent": "code-audit",
    "zhaoxuan": "code-audit",
    "exploit": "exploit",
    "exploit-construction": "exploit",
    "exploit-construction-agent": "exploit",
    "verify": "verify",
    "verification": "verify",
    "verifier": "verify",
    "verification-agent": "verify",
    "review": "review",
    "reviewer": "review",
    "independent-review": "review",
    "independent-review-agent": "review",
    "report": "report",
    "report-agent": "report",
    "synthesizer": "synthesizer",
    "single-synthesizer": "synthesizer",
}
CANONICAL_AGENT_ROLES = frozenset(ROLE_ALIASES.values())
DEFAULT_AGENT_TOOL_CALL_LIMIT = 24
MIN_AGENT_TOOL_CALL_LIMIT = 5
MAX_AGENT_TOOL_CALL_LIMIT = 64

TARGET_ARTIFACT_OPSEC_RE = re.compile(
    r"\b(?:xunji|agent|worker|exploit|webshell|poc|vuln|rce|sqli|xss|idor|ssrf|lfi|"
    r"csrf|scanner|probe)[\w.-]*\.(?:txt|ini|conf|config|aspx|ashx|php|jsp|jspx|tmp|html|log)\b",
    re.IGNORECASE,
)
TARGET_CLEANUP_ARTIFACT_RE = re.compile(
    r"(?:https?|ftp)://[^\s'\"`]*(?:"
    r"\b(?:tmp|diag|proof)-\d{8}-[a-f0-9]{6,12}(?:\.[a-z0-9._-]+)?\b|"
    r"\bxunji(?:_[a-z0-9]{2,24}){1,4}\."
    r"(?:txt|ini|conf|config|aspx|ashx|php|jsp|jspx|tmp|html|log)\b"
    r")[^\s'\"`]*",
    re.IGNORECASE,
)
TARGET_CLEANUP_ACTION_RE = re.compile(
    r"\b(?:cleanup|clean\s+up|remove|delete|del|unlink|overwrite|replace|DELETE)\b|"
    r"\brm\s+-(?![a-z-]*r)[a-z-]*f[a-z-]*\b|"
    r"清理|删除|移除|覆盖|抹除",
    re.IGNORECASE,
)


def _target_cleanup_requires_yes(text: str) -> bool:
    for m in TARGET_CLEANUP_ARTIFACT_RE.finditer(text):
        start = max(0, m.start() - 120)
        end = min(len(text), m.end() + 120)
        if TARGET_CLEANUP_ACTION_RE.search(text[start:end]):
            return True
    return False

def workers_dir(run_dir: Path) -> Path:
    return run_dir / "workers"


def agents_dir(run_dir: Path) -> Path:
    return run_dir / "agents"


def context_dir(run_dir: Path) -> Path:
    return run_dir / "context"


def state_dir(run_dir: Path) -> Path:
    return run_dir / "state"


def resolve_run_dir(path: Path) -> Path:
    run_dir = path if path.is_absolute() else ROOT / path
    return run_dir.resolve()


def display_path(path: Path) -> str:
    try:
        return str(path.relative_to(ROOT))
    except ValueError:
        return str(path)


def _atomic_write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f"{path.name}.tmp{os.getpid()}-{time.monotonic_ns()}")
    tmp.write_bytes(text.encode("utf-8"))
    os.replace(tmp, path)


def _load_json(path: Path, default):
    try:
        data = json.loads(path.read_text(encoding="utf-8", errors="replace"))
        return data if isinstance(data, type(default)) else default
    except Exception:
        return default


def _role(role: str) -> str:
    return ROLE_ALIASES.get(role.strip().lower(), role.strip().lower())


def _slug(value: str) -> str:
    s = re.sub(r"[^A-Za-z0-9._-]+", "-", value.strip()).strip("-").lower()
    return s or "agent"


def _blankish(value: str | None) -> bool:
    v = (value or "").strip()
    if re.fullmatch(r"<[^>]*>", v):
        return True
    return v.lower() in {"", "-", "n/a", "na", "none", "unknown", "todo", "pending"}


def scan(run_dir: Path) -> list[dict]:
    wd = workers_dir(run_dir)
    out: list[dict] = []
    for f in sorted(wd.glob("W-*.md")) if wd.exists() else []:
        text = f.read_text(encoding="utf-8", errors="replace")
        st = re.search(rf"(?im)^{HWS}*-?{HWS}*Status{HWS}*[:：]{HWS}*([A-Za-z]+)", text)
        front = re.search(rf"(?im)^{HWS}*-?{HWS}*Assigned front{HWS}*[:：]{HWS}*([^\n]+)", text)
        cands = len(re.findall(r"^###\s+CAND-", text, re.M))
        out.append({
            "file": f.name,
            "status": (st.group(1).lower() if st else "?"),
            "front": (front.group(1).strip() if front else "?"),
            "candidates": cands,
        })
    return out


def _field(text: str, name: str) -> str:
    m = re.search(rf"(?im)^{HWS}*[-*]?{HWS}*{re.escape(name)}{HWS}*[:：]{HWS}*([^\n]*)$", text)
    return m.group(1).strip() if m else ""


def _has_field_label(text: str, name: str) -> bool:
    return bool(re.search(rf"(?im)^{HWS}*[-*]?{HWS}*{re.escape(name)}{HWS}*[:：]", text))


def _section_body(text: str, heading: str) -> str:
    m = re.search(rf"(?ims)^##{HWS}+{re.escape(heading)}{HWS}*$(.*?)(?=^##{HWS}+|\Z)", text)
    return m.group(1) if m else ""


def _int_field(text: str, name: str) -> int:
    raw = _field(text, name)
    m = re.search(r"\d+", raw)
    return int(m.group(0)) if m else 0


def _front_sections(text: str) -> list[tuple[str, str]]:
    sections: list[tuple[str, str]] = []
    current = "unknown"
    buf: list[str] = []
    for line in text.splitlines():
        mh = re.match(r"^##[ \t]+(.+?)[ \t]*$", line)
        if mh:
            if buf:
                sections.append((current, "\n".join(buf)))
                buf = []
            current = mh.group(1).strip()
            continue
        buf.append(line)
    if buf:
        sections.append((current, "\n".join(buf)))
    return sections


def parse_frontiers(run_dir: Path) -> list[dict]:
    if _run_model is not None:
        rows: list[dict] = []
        for front in _run_model.parse_fronts(run_dir):
            rows.append({
                "id": front.id,
                "section": front.section,
                "status": front.status,
                "barrier": front.barrier,
                "depth": front.depth,
                "title": front.title,
                "same_barrier_failures": _int_field(front.text, "Same barrier failures"),
                "text": front.text,
                "schema_errors": list(front.schema_errors),
            })
        return rows
    path = run_dir / "frontier.md"
    if not path.exists():
        return []
    text = path.read_text(encoding="utf-8", errors="replace")
    fronts: list[dict] = []
    for section, body in _front_sections(text):
        for m in re.finditer(r"(?ms)^###[ \t]+(F-\d+).*?(?=^###[ \t]+|\Z)", body):
            block = m.group(0)
            fid = m.group(1)
            status = (_field(block, "Status") or section).lower()
            barrier = (_field(block, "Barrier class") or "unknown").lower()
            depth = (_field(block, "Current depth") or "unknown").lower()
            title = _field(block, "Front") or block.splitlines()[0].lstrip("# ").strip()
            same_barrier = _int_field(block, "Same barrier failures")
            fronts.append({
                "id": fid,
                "section": section,
                "status": status,
                "barrier": barrier,
                "depth": depth,
                "title": title,
                "same_barrier_failures": same_barrier,
                "text": block,
            })
    return fronts


def _load_coverage(run_dir: Path) -> list[dict]:
    candidates = [run_dir / "coverage.json", *sorted(run_dir.glob("**/coverage.json"))]
    seen: set[Path] = set()
    for p in candidates:
        if p in seen or not p.exists():
            continue
        seen.add(p)
        try:
            data = json.loads(p.read_text(encoding="utf-8", errors="replace"))
        except Exception:
            continue
        assets = data.get("assets")
        if isinstance(assets, list):
            return [a for a in assets if isinstance(a, dict)]
    return []


def _asset_name(asset: dict) -> str:
    raw = str(asset.get("host") or asset.get("asset") or asset.get("url") or "").strip()
    raw = re.sub(r"^https?://", "", raw, flags=re.I).split("/", 1)[0]
    port = asset.get("port")
    if port and ":" not in raw:
        raw = f"{raw}:{port}"
    return raw


def _normalize_asset(value: str) -> str:
    raw = str(value or "").strip().lower().rstrip(".")
    raw = re.sub(r"^[a-z][a-z0-9+.\-]*://", "", raw).split("/", 1)[0]
    return raw


def _stable_asset_id(host: str) -> str:
    import hashlib
    return "ASSET-" + hashlib.sha1(_normalize_asset(host).encode("utf-8")).hexdigest()[:12].upper()


def _canonical_asset_id(asset: dict | None, host: str) -> str:
    """Keep an inventory-owned asset identity across assignment projections.

    Older coverage producers may have derived their stable ID from the hostname
    alone while newer inventories distinguish an explicit port in the display
    name.  An assignment is a projection of that inventory row, so it must copy
    the row's valid ID instead of independently minting a second identity.
    """
    value = str((asset or {}).get("asset_id") or "").strip()
    if re.fullmatch(r"ASSET-[0-9A-F]{12}", value):
        return value
    return _stable_asset_id(host)


def _resolve_assignment_assets(run_dir: Path, front: str, requested: list[str] | None,
                               role: str, *, effect: str = "") \
        -> tuple[list[str], dict[str, dict]]:
    inventory = {_normalize_asset(_asset_name(asset)): asset for asset in _load_coverage(run_dir)
                 if _normalize_asset(_asset_name(asset))}
    target_roles = {"surface", "web-auth", "web-hunter", "exploit", "verify"}
    values: list[str] = []
    for raw in requested or []:
        for part in re.split(r"[,;，、]+", raw):
            host = _normalize_asset(part)
            if host and host not in values:
                values.append(host)
    target_lane = effect == "target" or (not effect and role in target_roles)
    if inventory and target_lane and not values:
        raise ValueError(
            "target-facing assignment requires explicit --asset HOST (repeatable); "
            "do not assign only a broad F-id")
    unknown = [host for host in values if host not in inventory]
    if unknown:
        raise ValueError("asset(s) absent from coverage inventory: " + ", ".join(unknown))
    front_text = _front_text(run_dir, front).lower()
    unlinked = [host for host in values if not re.search(
        r"(?<![\w.\-])" + re.escape(host) + r"(?![\w.\-])", front_text)]
    if unlinked:
        raise ValueError(
            "asset(s) are not explicitly named in the selected frontier block: "
            + ", ".join(unlinked))
    return values, inventory


def _transaction_bound_plan_for_cancellation(run_dir: Path) -> dict:
    """Reload immutable work identity without reviving stale execution authority."""
    plan = _work_plan.transaction_bound_plan(run_dir)
    # Cancellation is permitted only after ``current_plan`` proved an exact
    # turn/input stale condition.  Re-applying current turn or stage checks here
    # would make the recovery path unreachable; structural lineage remains hard.
    validated = _work_plan.validate_plan(plan, check_inputs=False)
    if validated != plan:
        raise ValueError(
            "transaction-bound cancellation plan changed during validation")
    return plan


def _transaction_bound_plan_for_settlement(run_dir: Path) -> dict:
    """Reload a committed plan for settlement without reviving its authority."""
    plan = _work_plan.transaction_bound_plan(run_dir)
    # Intentionally omit run_dir/contract: validate_plan uses them to re-run
    # current stage/mode/turn checks. transaction_bound_plan already proves the
    # committed lineage; stale settlement needs structural identity only.
    validated = _work_plan.validate_plan(plan, check_inputs=False)
    if validated != plan:
        raise ValueError("transaction-bound settlement plan changed during validation")
    return plan


def _current_plan_lane(run_dir: Path, *, lane_id: str, role: str,
                       front: str, assets: list[str],
                       stale_settlement_plan: dict | None = None) \
        -> tuple[dict, dict]:
    """Bind an assignment to one exact current work-plan lane.

    Existing non-loop runs without a plan retain the legacy assignment surface.
    Once ``state/work_plan.json`` exists, an unreadable/stale/mismatched plan is
    never silently downgraded to legacy behavior.
    """
    plan_path = run_dir / "state" / "work_plan.json"
    if not plan_path.exists():
        return {}, {}
    if _work_plan is None:
        raise ValueError("work_plan unavailable; cannot bind assignment")
    persisted_plan = _load_json(plan_path, {})
    persisted_digest = str(persisted_plan.get("plan_digest") or "") \
        if isinstance(persisted_plan, dict) else ""
    if persisted_digest:
        _plan_cycle_is_ended(run_dir, persisted_digest)
    contract = _load_json(run_dir / "state" / "turn_contract.json", {})
    try:
        if stale_settlement_plan is None:
            plan = _work_plan.current_plan(run_dir, contract)
        else:
            # This private override is accepted only while the normal scheduler
            # fails for the one exact reason it is designed to settle.  Turn,
            # stage, transaction, snapshot, archive and lineage validation are
            # all repeated immediately before the assignment mutation.
            try:
                _work_plan.current_plan(run_dir, contract)
            except _work_plan.PlanError as exc:
                if str(exc) not in {"WORK_PLAN_INPUTS_STALE", "WORK_PLAN_TURN_STALE"} \
                        and not (_agent_settlement is not None
                                 and _agent_settlement.cancellation_barrier(
                                     run_dir, plan_digest=persisted_digest)):
                    raise
            else:
                if _agent_settlement is None \
                        or not _agent_settlement.cancellation_barrier(
                            run_dir, plan_digest=persisted_digest):
                    raise ValueError(
                        "settlement override requires stale turn/inputs or a cancellation")
            plan = _transaction_bound_plan_for_settlement(run_dir)
            if plan != stale_settlement_plan:
                raise ValueError("stale settlement plan changed before assignment")
    except Exception as exc:
        raise ValueError(f"current work plan is invalid or stale: {exc}") from exc
    if _plan_cycle_is_ended(run_dir, str(plan.get("plan_digest") or "")):
        raise ValueError("ended plan cycle is immutable; commit a new plan instead")
    if stale_settlement_plan is None and _agent_settlement is not None \
            and _agent_settlement.cancellation_barrier(
                run_dir, plan_digest=str(plan.get("plan_digest") or "")):
        raise ValueError(
            "WORK_PLAN_CANCELLED_LANE_REPLAN_REQUIRED: old plan cannot create assignments")
    if str(plan.get("execution_mode") or "") == "ROOT_DIRECT":
        raise ValueError("ROOT_DIRECT plan cannot create an Agent assignment")
    candidates = [
        item for item in plan.get("lanes", []) if isinstance(item, dict)
        and (not lane_id or str(item.get("id") or "") == lane_id)
        and _role(str(item.get("role") or "")) == role
        and str(item.get("front") or "").upper() == front.upper()
        and [_normalize_asset(value) for value in item.get("assets", [])]
        == [_normalize_asset(value) for value in assets]
    ]
    if len(candidates) != 1:
        raise ValueError(
            "assignment must match exactly one current plan lane by lane/role/front/assets")
    lane = candidates[0]
    if _agent_settlement is not None and _agent_settlement.cancellation_barrier(
            run_dir, plan_digest=str(plan.get("plan_digest") or "")) \
            and not _agent_settlement.stale_settlement_reviewer_ready(
                run_dir, plan, lane):
        raise ValueError(
            "WORK_PLAN_CANCELLED_LANE_REPLAN_REQUIRED: only authentic Reviewer settlement remains")
    if not _work_plan.lane_dependencies_satisfied(run_dir, plan, lane):
        raise ValueError("planned lane dependencies do not have matching returned attempts")
    state = _work_plan.lane_runtime_state(run_dir, plan, str(lane.get("id") or ""))
    if state != "unassigned":
        raise ValueError(
            f"planned lane already has assignment state={state}; replan for a new attempt")
    return plan, lane


def _coverage_snapshot(asset: dict) -> dict:
    return {
        "examined": bool(asset.get("examined")),
        "verdict": asset.get("verdict"),
        "tested_groups": sorted(str(item) for item in (asset.get("tested_groups") or [])),
    }


def _asset_outcomes_scaffold(
    assets: list[str], inventory: dict[str, dict] | None = None,
) -> str:
    if not assets:
        return "- No target asset package (non-target analysis lane)."
    inventory = inventory or {}
    return "\n".join(
        f"### {_canonical_asset_id(inventory.get(host), host)} — {host}\n"
        "- Action receipts:\n"
        "- Result:\n"
        "- Barrier / control:\n"
        "- Artifacts:\n"
        "- Proposed disposition: tested | barrier | unreachable | deferred"
        for host in assets
    )


def _front_assets(front: dict, assets: list[dict]) -> list[dict]:
    text = front["text"].lower()
    out: list[dict] = []
    for a in assets:
        host = _asset_name(a)
        if host and host.lower() in text:
            out.append(a)
    return out


def _asset_agent_role(asset: dict) -> str:
    cat = str(asset.get("category") or "").lower()
    flags = {str(f).lower() for f in (asset.get("flags") or [])}
    combined = " ".join([cat, *sorted(flags)])
    if any(k in combined for k in ("login", "auth", "sso", "oauth")):
        return "web-auth"
    if any(k in combined for k in ("api", "rest", "json")):
        return "web-hunter"
    if any(k in combined for k in ("upload", "file")):
        return "exploit"
    if any(k in combined for k in ("admin", "manage", "vpn", "ssl")):
        return "web-hunter"
    return "surface"


def asset_suggestions(run_dir: Path) -> list[dict]:
    """Return advisory asset-level suggestions from coverage facts."""
    items: list[dict] = []
    try:
        import coverage_matrix
        rows = coverage_matrix.derive(run_dir).get("rows", [])
    except Exception:
        rows = []
    if rows:
        for row in rows:
            if not isinstance(row, dict) or row.get("reachability") is False:
                continue
            disposition = str(row.get("disposition") or "")
            if disposition not in {"unassigned", "front-linked"}:
                continue
            host = str(row.get("asset") or "")
            source = next((asset for asset in _load_coverage(run_dir)
                           if _normalize_asset(_asset_name(asset)) == _normalize_asset(host)), {})
            reasons = [disposition]
            if source.get("high_value"):
                reasons.append("high_value")
            if row.get("reachability") is True:
                reasons.append("reachable_no_verdict")
            items.append({"asset": host, "role": _asset_agent_role(source), "reasons": reasons})
        return sorted(items, key=lambda item: (
            "high_value" in item["reasons"], "reachable_no_verdict" in item["reasons"], item["asset"]
        ), reverse=True)
    for asset in _load_coverage(run_dir):
        host = _asset_name(asset)
        if not host or asset.get("examined"):
            continue
        reasons: list[str] = []
        if asset.get("high_value"):
            reasons.append("high_value")
        if asset.get("reachable") and asset.get("verdict") is None:
            reasons.append("reachable_no_verdict")
        if not reasons:
            continue
        items.append({
            "asset": host,
            "role": _asset_agent_role(asset),
            "reasons": reasons,
        })
    return items


def suggest(run_dir: Path, limit: int | None = None) -> list[dict]:
    """Return advisory fan-out candidates. This ranks fronts; it never assigns work."""
    if _state_project is not None:
        try:
            proj = _state_project.load_or_create(run_dir)
            fronts = proj.get("fronts") or parse_frontiers(run_dir)
            cov = proj.get("coverage") if isinstance(proj.get("coverage"), dict) else {}
            assets = cov.get("assets") or _load_coverage(run_dir)
        except Exception:
            fronts = parse_frontiers(run_dir)
            assets = _load_coverage(run_dir)
    else:
        fronts = parse_frontiers(run_dir)
        assets = _load_coverage(run_dir)
    rows: list[dict] = []
    for f in fronts:
        if re.search(r"\b(closed|merged)\b", f["status"]):
            continue
        score = 0
        reasons: list[str] = []
        cautions: list[str] = []
        matched = _front_assets(f, assets)
        hosts = [_asset_name(a) for a in matched if _asset_name(a)]
        reachable = [a for a in matched if a.get("reachable") is True]
        coverage_debt = [a for a in matched if a.get("reachable") is not False
                         and not a.get("tested_groups") and not a.get("verdict")]
        flags = sorted({str(x) for a in matched for x in (a.get("flags") or [])})

        if f["status"] in {"open", "probing"}:
            score += 2
            reasons.append(f"status={f['status']}")
        elif "deferred" in f["status"] or "blocked" in f["status"]:
            score -= 1
            cautions.append(f"status={f['status']} may need driver unblock first")

        if hosts:
            score += 2
            reasons.append("front names distinct asset(s): " + ", ".join(hosts[:3]))
        else:
            cautions.append("no coverage asset matched in front text")
        if reachable:
            score += 1
            reasons.append(f"{len(reachable)} reachable matched asset(s)")
        if coverage_debt:
            score += min(4, len(coverage_debt))
            reasons.append(f"coverage debt on {len(coverage_debt)} asset(s)")
        if flags:
            score += 1
            reasons.append("surface flags: " + ", ".join(flags[:5]))
        if f["depth"] in {"shallow", "unknown"}:
            score += 1
            reasons.append(f"depth={f['depth']}")
        if f["same_barrier_failures"] >= 3:
            score -= 2
            cautions.append(f"same barrier failures={f['same_barrier_failures']}; serial metacog/pivot may be better")
        if f["barrier"] not in {"none", "unknown", ""}:
            cautions.append(f"barrier={f['barrier']}")

        rows.append({
            "front": f["id"],
            "title": f["title"],
            "status": f["status"],
            "barrier": f["barrier"],
            "depth": f["depth"],
            "assets": hosts,
            "coverage_debt": [_asset_name(a) for a in coverage_debt if _asset_name(a)],
            "score": score,
            "reasons": reasons,
            "cautions": cautions,
            "text": f["text"],
        })
    # 饱和度惩罚: 调用 saturation.py --suggest 获取每个 front 的 penalty
    front_ids = [r["front"] for r in rows]
    sat_penalties: dict[str, int] = {}
    sat_infos: dict[str, float] = {}
    if front_ids and SATURATION_SCRIPT.exists():
        try:
            result = subprocess.run(
                [sys.executable, str(SATURATION_SCRIPT), str(run_dir), "--suggest"],
                capture_output=True, text=True, timeout=15,
            )
            if result.returncode == 0:
                sat_items = json.loads(result.stdout)
                for item in sat_items:
                    fid = item.get("front", "")
                    sat_penalties[fid] = item.get("penalty", 0)
                    if item.get("saturation") is not None:
                        sat_infos[fid] = item["saturation"]
        except (json.JSONDecodeError, subprocess.TimeoutExpired, Exception):
            pass  # 饱和度不可用时优雅降级, 不影响现有逻辑

    # 应用饱和度惩罚并补充 cautions
    for r in rows:
        fid = r["front"]
        penalty = sat_penalties.get(fid, 0)
        r["score"] += penalty
        if fid in sat_infos:
            sat_pct = f"{sat_infos[fid]:.0%}"
            r["cautions"].append(f"saturation={sat_pct} penalty={penalty:+d}")
        if penalty != 0:
            r["saturation_penalty"] = penalty

    rows.sort(key=lambda r: (len(r.get("coverage_debt") or []), r["score"], bool(r["assets"]), r["front"]),
              reverse=True)
    return rows[:limit] if limit else rows


def _lane_id(front: str, suffix: str) -> str:
    """Return a deterministic work-plan lane id for one advisory front."""
    token = re.sub(r"[^A-Za-z0-9._-]+", "-", front.strip().upper()).strip("-")
    return f"L-{token or 'UNBOUND'}-{suffix}"


def _target_egress_denied_for_plan(run_dir: Path) -> bool:
    """Project the operator's negative target effect into planner output."""
    path = run_dir / "state" / "turn_contract.json"
    try:
        value = json.loads(path.read_text(encoding="utf-8", errors="strict"))
    except FileNotFoundError:
        return False
    except Exception:
        return True
    if not isinstance(value, dict) \
            or value.get("schema") != "xunji.turn_contract.v1":
        return True
    return value.get("target_egress_denied") is True


def lane_suggestions(
    run_dir: Path, limit: int | None = None, *, stage: str = "S2",
) -> list[dict]:
    """Expand ranked fronts into effect-typed Root/Hunter/Reviewer lanes.

    This remains an advisory planner: it does not commit ``work_plan.json``,
    assign an Agent, or mint a lifecycle receipt.  The returned ``work_plan_lane``
    value is the conservative generated seed placed into the non-authorizing
    proposal; Root may reshape that seed before the proposal owner validates and
    atomically commits it.
    """
    stage = str(stage or "").upper()
    if stage not in {"S1", "S2", "S3"}:
        raise ValueError("STAGE_POLICY_STAGE_INVALID")
    ranked = [row for row in suggest(run_dir) if row["score"] >= 3]
    # A fully reviewable front currently expands to six lanes.  Keep one work
    # plan within the frozen 16-lane contract; later fronts are handled by a
    # material replan after the first wave is merged.
    selected = ranked[:max(0, min(limit if limit is not None else 2, 2))]
    target_egress_denied = _target_egress_denied_for_plan(run_dir)
    planned: list[dict] = []
    for row in selected:
        front = str(row["front"])
        assets = list(dict.fromkeys(
            (row.get("coverage_debt") or row.get("assets") or [])[:4]))
        information_gain = "high" if int(row.get("score") or 0) >= 6 else "medium"
        offline_id = _lane_id(front, "OFFLINE")
        offline_review_id = _lane_id(front, "OFFLINE-REVIEW")
        target_id = _lane_id(front, "TARGET")
        target_review_id = _lane_id(front, "TARGET-REVIEW")
        verify_id = _lane_id(front, "VERIFY")
        verify_review_id = _lane_id(front, "VERIFY-REVIEW")

        def add_lane(*, lane_id: str, role: str, effect: str,
                     dependencies: list[str], expected_evidence: str,
                     request_cost: int, request_budget: int,
                     merge_cost: int, atomic: bool = False) -> None:
            lane = {
                "id": lane_id,
                "role": role,
                "front": front,
                "effect": effect,
                "assets": assets,
                "dependencies": dependencies,
                "expected_evidence": expected_evidence,
                "expected_information_gain": information_gain,
                "stop_condition": (
                    "the declared signal is observed or one attributable control refutes it"),
                "request_cost": request_cost,
                "request_budget": request_budget,
                "merge_cost": merge_cost,
                "atomic": atomic,
            }
            planned.append({
                "front_title": str(row.get("title") or front),
                "effect_class": effect,
                "overlap_key": {
                    "run": str(run_dir.resolve()),
                    "assets": assets,
                    "front": front,
                    "lane": lane_id,
                    "effect": effect,
                },
                "work_plan_lane": lane,
            })

        if stage == "S3":
            add_lane(
                lane_id=verify_id, role="verify", effect="local_verify",
                dependencies=[],
                expected_evidence=(
                    "closure-gate, report/evidence parity, and lifecycle-debt adjudication"),
                request_cost=0, request_budget=0, merge_cost=10,
            )
            add_lane(
                lane_id=verify_review_id, role="review", effect="local_verify",
                dependencies=[verify_id],
                expected_evidence=(
                    "independent disposition for the frozen S3 closure bundle"),
                request_cost=0, request_budget=0, merge_cost=5,
            )
            continue

        add_lane(
            lane_id=offline_id, role="web-hunter", effect="local_read",
            dependencies=[],
            expected_evidence="bounded source/artifact observations and explicit refutations",
            request_cost=0, request_budget=0, merge_cost=10,
        )
        add_lane(
            lane_id=offline_review_id, role="review", effect="local_verify",
            dependencies=[offline_id],
            expected_evidence="review disposition for the frozen offline merge draft",
            request_cost=0, request_budget=0, merge_cost=5,
        )
        if stage == "S1":
            continue
        predecessor = offline_review_id
        if assets and not target_egress_denied:
            add_lane(
                lane_id=target_id, role="web-hunter", effect="target",
                dependencies=[offline_review_id],
                expected_evidence="one guarded target signal plus a named baseline/control",
                request_cost=1, request_budget=3, merge_cost=20,
            )
            add_lane(
                lane_id=target_review_id, role="review", effect="local_verify",
                dependencies=[target_id],
                expected_evidence="review disposition for the frozen target merge draft",
                request_cost=0, request_budget=0, merge_cost=5,
            )
            predecessor = target_review_id
        if target_egress_denied:
            # The offline Hunter already returns a bounded preparation artifact
            # and its dependent Reviewer verifies that exact result.  With no
            # target artifact, another VERIFY -> REVIEW pair repeats the same
            # cognition work and creates avoidable plan debt.
            continue
        add_lane(
            lane_id=verify_id, role="verify", effect="local_verify",
            dependencies=[predecessor],
            expected_evidence="artifact-bound verification or a precise refutation",
            request_cost=0, request_budget=0, merge_cost=10,
        )
        add_lane(
            lane_id=verify_review_id, role="review", effect="local_verify",
            dependencies=[verify_id],
            expected_evidence="review disposition for the frozen verification merge draft",
            request_cost=0, request_budget=0, merge_cost=5,
        )
    return planned


def _plan_proposal_path(run_dir: Path) -> Path:
    return state_dir(run_dir) / PLAN_PROPOSAL_FILE


def _plan_proposal_basis(run_dir: Path) -> dict:
    """Bind a model-authored draft to the exact current turn and inputs."""
    if _work_plan is None:
        raise ValueError("work_plan unavailable; proposal fails closed")
    contract = _work_plan._load_turn_contract(run_dir)
    inputs_digest, _ = _work_plan.input_fingerprint(run_dir)
    return {
        "inputs_digest": inputs_digest,
        "turn_binding": {
            "session_id": str(contract.get("session_id") or ""),
            "prompt_sha256": str(contract.get("prompt_sha256") or ""),
            "contract_updated_at": float(contract.get("updated_at") or 0.0),
        },
    }


def write_plan_proposal(
    run_dir: Path, lanes: list[dict], *, stage: str | None = None,
) -> dict:
    """Write a replaceable, non-authorizing seed for Root strategy edits."""
    ready = [lane for lane in lanes if not lane.get("dependencies")]
    topology_mode = (
        "PARALLEL_AGENTS" if len(ready) >= 2
        and all(lanes_can_overlap(left, right)
                for index, left in enumerate(ready)
                for right in ready[index + 1:])
        else "SERIAL_AGENT"
    )
    proposal = {
        "schema": PLAN_PROPOSAL_SCHEMA,
        "basis": _plan_proposal_basis(run_dir),
        "macro_stage": stage,
        "objective": "",
        "execution_mode": topology_mode,
        "delegation_reason": "",
        "exit_gate": "",
        "replan_reason": "",
        "lanes": lanes,
    }
    path = _plan_proposal_path(run_dir)
    _atomic_write(path, json.dumps(proposal, ensure_ascii=False, indent=2) + "\n")
    return {"path": path, "proposal": proposal}


def load_plan_proposal(run_dir: Path) -> tuple[dict, str]:
    """Load one exact in-run proposal without granting it plan authority."""
    path = _plan_proposal_path(run_dir)
    try:
        info = path.lstat()
    except FileNotFoundError as exc:
        raise ValueError(
            "WORK_PLAN_PROPOSAL_MISSING: rerun workers.py plan") from exc
    if not stat.S_ISREG(info.st_mode) or path.is_symlink():
        raise ValueError("WORK_PLAN_PROPOSAL_NOT_REGULAR")
    if info.st_size <= 0 or info.st_size > PLAN_PROPOSAL_MAX_BYTES:
        raise ValueError("WORK_PLAN_PROPOSAL_SIZE_INVALID")
    try:
        raw = path.read_bytes()
        value = json.loads(raw.decode("utf-8", errors="strict"))
    except Exception as exc:
        raise ValueError("WORK_PLAN_PROPOSAL_JSON_INVALID") from exc
    expected_fields = {
        "schema", "basis", "macro_stage", "objective", "execution_mode",
        "delegation_reason", "exit_gate", "replan_reason", "lanes",
    }
    if not isinstance(value, dict) or value.get("schema") != PLAN_PROPOSAL_SCHEMA:
        raise ValueError("WORK_PLAN_PROPOSAL_SCHEMA_INVALID")
    if set(value) != expected_fields:
        raise ValueError("WORK_PLAN_PROPOSAL_FIELDS_INVALID")
    if value.get("basis") != _plan_proposal_basis(run_dir):
        raise ValueError("WORK_PLAN_PROPOSAL_STALE")
    if value.get("macro_stage") not in _work_plan.STAGES:
        raise ValueError("WORK_PLAN_PROPOSAL_STAGE_REQUIRED")
    if value.get("execution_mode") not in {"SERIAL_AGENT", "PARALLEL_AGENTS"}:
        raise ValueError("WORK_PLAN_PROPOSAL_MODE_INVALID")
    for field in ("objective", "delegation_reason", "exit_gate", "replan_reason"):
        if not isinstance(value.get(field), str):
            raise ValueError(f"WORK_PLAN_PROPOSAL_{field.upper()}_INVALID")
    lanes = value.get("lanes")
    if not isinstance(lanes, list) or not 1 <= len(lanes) <= 16 \
            or not all(isinstance(item, dict) for item in lanes):
        raise ValueError("WORK_PLAN_PROPOSAL_LANES_INVALID")
    return value, hashlib.sha256(raw).hexdigest()


def _validate_proposal_assignment_scope(run_dir: Path, lanes: list[dict]) -> None:
    """Reject a proposal that would commit debt no assignment can satisfy."""
    known_fronts = {str(item.get("id") or "") for item in parse_frontiers(run_dir)}
    for lane in lanes:
        front = str(lane.get("front") or "")
        if front not in known_fronts:
            raise ValueError(
                f"WORK_PLAN_PROPOSAL_FRONT_UNKNOWN:{front or '(empty)'}")
        _resolve_assignment_assets(
            run_dir,
            front,
            [str(item) for item in lane.get("assets", [])],
            str(lane.get("role") or ""),
            effect=str(lane.get("effect") or ""),
        )


def lanes_can_overlap(left: dict, right: dict) -> bool:
    """Apply the deterministic effect/asset overlap matrix to two planner rows."""
    a = left.get("work_plan_lane") if "work_plan_lane" in left else left
    b = right.get("work_plan_lane") if "work_plan_lane" in right else right
    if not isinstance(a, dict) or not isinstance(b, dict):
        return False
    if a.get("dependencies") or b.get("dependencies"):
        return False
    effects = {str(a.get("effect") or ""), str(b.get("effect") or "")}
    if effects & {"control", "repo_mutation"}:
        return False
    if "target" in effects:
        if effects != {"target"}:
            return True
        return not bool(set(a.get("assets") or []) & set(b.get("assets") or []))
    return effects <= {"local_read", "local_verify", "model_egress"}


def scheduler_selection(lanes: list[dict], *, runtime_slots: int,
                        request_budget: int, merge_capacity: int,
                        model_egress_budget: int = 0) -> list[dict]:
    """Return the exact ready lanes admitted by every shared capacity.

    The selected rows, rather than only their count, are the scheduling result.
    A costly earlier row may be skipped while a later independent row still
    fits; callers must never reconstruct that decision with ``lanes[:width]``.
    """
    ready = [row for row in lanes
             if not (row.get("work_plan_lane", row).get("dependencies") or [])]
    budgeted: list[dict] = []
    remaining_requests = max(0, request_budget)
    remaining_model_egress = max(0, model_egress_budget)
    remaining_merge = max(0, merge_capacity)
    for row in ready:
        if not all(lanes_can_overlap(row, other) for other in budgeted):
            continue
        lane = row.get("work_plan_lane", row)
        target_cost = 0
        model_cost = 0
        if lane.get("effect") == "target":
            target_cost = max(1, int(lane.get("request_cost") or 0))
        elif lane.get("effect") == "model_egress":
            model_cost = max(1, int(lane.get("request_cost") or 0))
        merge_cost = max(0, int(lane.get("merge_cost") or 0))
        if target_cost > remaining_requests \
                or model_cost > remaining_model_egress \
                or merge_cost > remaining_merge:
            continue
        remaining_requests -= target_cost
        remaining_model_egress -= model_cost
        remaining_merge -= merge_cost
        budgeted.append(row)
    return budgeted[:max(0, runtime_slots)]


def scheduler_width(lanes: list[dict], *, runtime_slots: int,
                    request_budget: int, merge_capacity: int,
                    model_egress_budget: int = 0) -> int:
    """Return the width of the exact capacity-bounded scheduler selection."""
    return len(scheduler_selection(
        lanes,
        runtime_slots=runtime_slots,
        request_budget=request_budget,
        merge_capacity=merge_capacity,
        model_egress_budget=model_egress_budget,
    ))


def _capacity_diagnostic(
    ready: list[dict], *, available_slots: int, request_budget: int,
    model_egress_budget: int, merge_capacity: int,
) -> str:
    """Name the exact limiting capacity for the first ready lane.

    This is an operator-facing recovery contract.  A combined generic error
    invites the driver to guess which budget to raise and can widen an unrelated
    effect boundary.
    """
    lane = ready[0].get("work_plan_lane", ready[0]) if ready else {}
    lane_id = str(lane.get("id") or "(unknown)")
    deficits: list[str] = []
    if available_slots < 1:
        deficits.append(
            f"runtime_slots required=1 available={max(0, available_slots)}")
    effect = str(lane.get("effect") or "")
    request_cost = max(1, int(lane.get("request_cost") or 0))
    if effect == "target" and request_cost > max(0, request_budget):
        deficits.append(
            f"request_budget required={request_cost} provided={max(0, request_budget)}")
    if effect == "model_egress" and request_cost > max(0, model_egress_budget):
        deficits.append(
            "model_egress_budget "
            f"required={request_cost} provided={max(0, model_egress_budget)}")
    merge_cost = max(0, int(lane.get("merge_cost") or 0))
    if merge_cost > max(0, merge_capacity):
        deficits.append(
            f"merge_capacity required={merge_cost} provided={max(0, merge_capacity)}")
    if not deficits:
        deficits.append("scheduler_selection returned no lane despite sufficient scalar capacity")
    return (
        "DELEGATE_CAPACITY_INSUFFICIENT: "
        f"lane={lane_id}; " + "; ".join(deficits)
    )


def _breadth_signals(rows: list[dict]) -> list[str]:
    """Describe candidate breadth without pretending it is a scheduler."""
    strong = [r for r in rows if r["score"] >= 3]
    distinct_assets = {a for r in strong for a in r["assets"]}
    distinct_barriers = {r["barrier"] for r in strong if r["barrier"] not in {"", "unknown"}}
    return [
        f"strong candidates={len(strong)}",
        f"distinct assets={len(distinct_assets)}",
        f"barrier classes={len(distinct_barriers) or 'mostly none/unknown'}",
    ]


def _candidate_blocks(text: str) -> list[dict]:
    blocks: list[dict] = []
    for m in re.finditer(r"(?ms)^###[ \t]+(CAND-\d+).*?(?=^###[ \t]+|\Z)", text):
        block = m.group(0)
        raw_cert = _field(block, "Proposed certainty")
        cm = re.search(r"[01]\.\d+", raw_cert)
        cert = float(cm.group(0)) if cm else None
        ctrl = _field(block, "Control / Replicated") or _field(block, "Control") or _field(block, "Replicated")
        blocks.append({
            "id": m.group(1),
            "claim": _field(block, "Claim"),
            "certainty": cert,
            "control": ctrl,
            "block": block,
        })
    return blocks


def merge_check(run_dir: Path) -> list[dict]:
    issues: list[dict] = []
    seen_claims: dict[str, tuple[str, float | None]] = {}
    for w in scan(run_dir):
        path = workers_dir(run_dir) / w["file"]
        text = path.read_text(encoding="utf-8", errors="replace")
        if w["status"] == "done":
            issues.append({"severity": "warn", "worker": w["file"], "kind": "done-but-unmerged",
                           "detail": "Status is done; driver still owes gated merge or merged mark."})
        for cand in _candidate_blocks(text):
            label = f"{w['file']}:{cand['id']}"
            claim = cand["claim"].strip()
            if not claim or claim in {"-", "TODO"}:
                issues.append({"severity": "warn", "worker": w["file"], "kind": "missing-claim",
                               "detail": f"{label} has no Claim."})
            norm = re.sub(r"\W+", " ", claim.lower()).strip() or claim.lower().strip()
            if norm:
                other = seen_claims.get(norm)
                if other:
                    other_label, other_cert = other
                    issues.append({"severity": "warn", "worker": w["file"], "kind": "duplicate-candidate",
                                   "detail": f"{label} duplicates {other_label}; driver should dedupe before E-id allocation."})
                    if cand["certainty"] is not None and other_cert is not None and cand["certainty"] != other_cert:
                        issues.append({"severity": "warn", "worker": w["file"], "kind": "conflicting-candidate",
                                       "detail": f"{label} and {other_label} propose different certainty for the same claim."})
                else:
                    seen_claims[norm] = (label, cand["certainty"])
            if cand["certainty"] is not None and cand["certainty"] >= 0.8:
                if _blankish(cand["control"]):
                    issues.append({"severity": "error", "worker": w["file"], "kind": "worker-missing-control",
                                   "detail": f"{label} proposes {cand['certainty']} without Control / Replicated."})
    return issues


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


def create_worker(run_dir: Path, front: str) -> Path:
    wd = workers_dir(run_dir)
    wd.mkdir(parents=True, exist_ok=True)
    wid = next_id(run_dir)
    path = wd / f"{wid}.md"
    path.write_text(SCAFFOLD.format(wid=wid, front=front), encoding="utf-8")
    return path


def _assignments_path(run_dir: Path) -> Path:
    return state_dir(run_dir) / "assignments.json"


DELEGATE_TRANSACTION_SCHEMA = "xunji.delegate-transaction.v1"
DELEGATE_TRANSACTION_FIELDS = frozenset({
    "schema", "transaction_id", "status", "plan_id", "plan_digest",
    "lane_ids", "prepared_at", "committed_at", "rolled_back_at",
    "rollback_reason", "previous_assignments_text",
    "previous_assignments_sha256", "agent_files_before",
    "context_files_before", "created_assignments", "created_agent_files",
    "created_context_files", "receipt_digest",
})


def _delegate_transaction_path(run_dir: Path) -> Path:
    return state_dir(run_dir) / "delegate_transaction.json"


@contextlib.contextmanager
def _assignment_mutation_lock(run_dir: Path):
    """Serialize every assignment-ledger RMW with the runtime projector."""
    if _runtime_receipts is not None \
            and hasattr(_runtime_receipts, "assignment_mutation_lock"):
        with _runtime_receipts.assignment_mutation_lock(run_dir):
            yield
        return
    lock_path = state_dir(run_dir) / ".assignments.lock"
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    with lock_path.open("a+", encoding="utf-8") as lock_file:
        fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)


def _transaction_file_snapshot(directory: Path, *, agents: bool) -> list[str]:
    if not directory.exists():
        return []
    names: list[str] = []
    for path in directory.iterdir():
        if not (path.is_file() or path.is_symlink()):
            continue
        if agents:
            if not re.fullmatch(r"A-[A-Za-z0-9._-]+\.md", path.name):
                continue
        elif path.suffix != ".md":
            continue
        names.append(path.name)
    return sorted(names)


def _delegate_transaction_digest(receipt: dict) -> str:
    payload = {key: value for key, value in receipt.items()
               if key != "receipt_digest"}
    return hashlib.sha256(json.dumps(
        payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
    ).encode("utf-8")).hexdigest()


def _write_delegate_transaction(run_dir: Path, receipt: dict) -> dict:
    saved = dict(receipt)
    saved["receipt_digest"] = _delegate_transaction_digest(saved)
    _atomic_write(
        _delegate_transaction_path(run_dir),
        json.dumps(saved, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
    )
    return saved


def _validate_delegate_transaction(receipt: object) -> dict:
    if not isinstance(receipt, dict):
        raise ValueError("delegate transaction receipt must be a JSON object")
    if set(receipt) != DELEGATE_TRANSACTION_FIELDS:
        raise ValueError("delegate transaction receipt has an unexpected shape")
    if receipt.get("schema") != DELEGATE_TRANSACTION_SCHEMA:
        raise ValueError("delegate transaction receipt has an unknown schema")
    if receipt.get("status") not in {"prepared", "committed", "rolled_back"}:
        raise ValueError("delegate transaction receipt has an invalid status")
    if not re.fullmatch(r"[0-9a-f]{64}", str(receipt.get("transaction_id") or "")):
        raise ValueError("delegate transaction receipt has an invalid transaction_id")
    if not isinstance(receipt.get("plan_id"), str) or not receipt["plan_id"]:
        raise ValueError("delegate transaction receipt has an invalid plan_id")
    if not re.fullmatch(r"[0-9a-f]{64}", str(receipt.get("plan_digest") or "")):
        raise ValueError("delegate transaction receipt has an invalid plan_digest")
    lane_ids = receipt.get("lane_ids")
    if (not isinstance(lane_ids, list) or not lane_ids
            or any(not isinstance(value, str) or not value for value in lane_ids)
            or len(set(lane_ids)) != len(lane_ids)):
        raise ValueError("delegate transaction receipt has invalid lane_ids")
    if not isinstance(receipt.get("prepared_at"), str) or not receipt["prepared_at"]:
        raise ValueError("delegate transaction receipt has an invalid prepared_at")
    status = receipt["status"]
    committed_at = receipt.get("committed_at")
    rolled_back_at = receipt.get("rolled_back_at")
    rollback_reason = receipt.get("rollback_reason")
    if status == "prepared":
        if committed_at is not None or rolled_back_at is not None or rollback_reason != "":
            raise ValueError("prepared delegate transaction has terminal fields")
    elif status == "committed":
        if (not isinstance(committed_at, str) or not committed_at
                or rolled_back_at is not None or rollback_reason != ""):
            raise ValueError("committed delegate transaction has invalid terminal fields")
    elif (not isinstance(rolled_back_at, str) or not rolled_back_at
          or committed_at is not None
          or not isinstance(rollback_reason, str) or not rollback_reason):
        raise ValueError("rolled-back delegate transaction has invalid terminal fields")
    previous = receipt.get("previous_assignments_text")
    previous_digest = receipt.get("previous_assignments_sha256")
    if previous is None:
        if previous_digest is not None:
            raise ValueError("absent prior assignments cannot have a digest")
    elif (not isinstance(previous, str)
          or not re.fullmatch(r"[0-9a-f]{64}", str(previous_digest or ""))
          or hashlib.sha256(previous.encode("utf-8")).hexdigest() != previous_digest):
        raise ValueError("delegate transaction prior assignments snapshot is invalid")
    for field, pattern in (
        ("agent_files_before", r"A-[A-Za-z0-9._-]+\.md"),
        ("context_files_before", r"[^/\\]+\.md"),
        ("created_assignments", r"A-[A-Za-z0-9._-]+"),
        ("created_agent_files", r"A-[A-Za-z0-9._-]+\.md"),
        ("created_context_files", r"[^/\\]+\.md"),
    ):
        values = receipt.get(field)
        if (not isinstance(values, list)
                or any(not isinstance(value, str) or not re.fullmatch(pattern, value)
                       for value in values)
                or len(set(values)) != len(values)):
            raise ValueError(f"delegate transaction receipt has invalid {field}")
        if field.endswith("_before") and values != sorted(values):
            raise ValueError(f"delegate transaction receipt has unsorted {field}")
    if (set(receipt["agent_files_before"]) & set(receipt["created_agent_files"])
            or set(receipt["context_files_before"])
            & set(receipt["created_context_files"])):
        raise ValueError("delegate transaction artifact intent overlaps prior files")
    digest = receipt.get("receipt_digest")
    if (not isinstance(digest, str)
            or not re.fullmatch(r"[0-9a-f]{64}", digest)
            or digest != _delegate_transaction_digest(receipt)):
        raise ValueError("delegate transaction receipt digest mismatch")
    return receipt


def _load_delegate_transaction(run_dir: Path) -> dict | None:
    path = _delegate_transaction_path(run_dir)
    if not path.exists():
        return None
    try:
        raw = json.loads(path.read_text(encoding="utf-8", errors="strict"))
    except Exception as exc:
        raise ValueError(f"delegate transaction receipt is unreadable: {exc}") from exc
    return _validate_delegate_transaction(raw)


def _remove_transaction_artifacts(
    directory: Path, before: list[str], created: list[str], *, agents: bool,
) -> None:
    if not directory.exists():
        return
    preserved = set(before)
    for name in created:
        if name in preserved:
            raise ValueError("delegate rollback refuses to remove a prior artifact")
        path = directory / name
        if not (path.is_file() or path.is_symlink()):
            continue
        if agents:
            if not re.fullmatch(r"A-[A-Za-z0-9._-]+\.md", path.name):
                continue
        elif path.suffix != ".md":
            continue
        path.unlink()


def _recover_prepared_delegate_transaction(
    run_dir: Path, *, reason: str = "recovered interrupted prepared transaction",
) -> dict | None:
    """Restore the exact pre-batch state; safe to repeat after any crash point."""
    receipt = _load_delegate_transaction(run_dir)
    if receipt is None or receipt["status"] != "prepared":
        return receipt
    assignments_path = _assignments_path(run_dir)
    previous = receipt["previous_assignments_text"]
    if previous is None:
        if assignments_path.exists():
            if assignments_path.is_dir():
                raise ValueError("cannot roll back delegate transaction over assignments directory")
            assignments_path.unlink()
    else:
        _atomic_write(assignments_path, previous)
    _remove_transaction_artifacts(
        agents_dir(run_dir), receipt["agent_files_before"],
        receipt["created_agent_files"], agents=True)
    _remove_transaction_artifacts(
        context_dir(run_dir), receipt["context_files_before"],
        receipt["created_context_files"], agents=False)
    receipt["status"] = "rolled_back"
    receipt["rolled_back_at"] = datetime.now(timezone.utc).isoformat(
        timespec="milliseconds").replace("+00:00", "Z")
    receipt["rollback_reason"] = reason
    return _write_delegate_transaction(run_dir, receipt)


def _prepare_delegate_transaction(run_dir: Path, plan: dict,
                                  lane_ids: list[str]) -> dict:
    assignments_path = _assignments_path(run_dir)
    previous = None
    if assignments_path.exists():
        previous = assignments_path.read_text(encoding="utf-8", errors="strict")
    prepared_at = datetime.now(timezone.utc).isoformat(
        timespec="milliseconds").replace("+00:00", "Z")
    transaction_seed = {
        "plan_digest": plan["plan_digest"], "lane_ids": lane_ids,
        "prepared_at": prepared_at, "pid": os.getpid(),
        "nonce": time.monotonic_ns(),
    }
    receipt = {
        "schema": DELEGATE_TRANSACTION_SCHEMA,
        "transaction_id": hashlib.sha256(json.dumps(
            transaction_seed, sort_keys=True, separators=(",", ":"),
        ).encode("utf-8")).hexdigest(),
        "status": "prepared",
        "plan_id": plan["plan_id"],
        "plan_digest": plan["plan_digest"],
        "lane_ids": lane_ids,
        "prepared_at": prepared_at,
        "committed_at": None,
        "rolled_back_at": None,
        "rollback_reason": "",
        "previous_assignments_text": previous,
        "previous_assignments_sha256": (
            hashlib.sha256(previous.encode("utf-8")).hexdigest()
            if previous is not None else None
        ),
        "agent_files_before": _transaction_file_snapshot(
            agents_dir(run_dir), agents=True),
        "context_files_before": _transaction_file_snapshot(
            context_dir(run_dir), agents=False),
        "created_assignments": [],
        "created_agent_files": [],
        "created_context_files": [],
        "receipt_digest": "",
    }
    return _write_delegate_transaction(run_dir, receipt)


def load_assignments(run_dir: Path) -> dict:
    path = _assignments_path(run_dir)
    if not path.exists():
        return {"schema": 3, "assignments": []}
    try:
        data = json.loads(path.read_text(encoding="utf-8", errors="strict"))
    except Exception as exc:
        raise ValueError("assignments.json is unreadable") from exc
    if not isinstance(data, dict) or not isinstance(data.get("assignments"), list):
        raise ValueError("assignments.json has no valid assignments list")
    if any(not isinstance(row, dict) for row in data["assignments"]):
        raise ValueError("assignments.json contains a non-object row")
    try:
        if isinstance(data.get("schema"), bool):
            raise ValueError
        schema = int(data.get("schema", 1) or 1)
    except (TypeError, ValueError):
        raise ValueError("assignments.json has an invalid ledger schema")
    if schema not in {1, 2, 3}:
        raise ValueError("assignments.json has an unsupported ledger schema")
    if schema < 2:
        for row in data["assignments"]:
            if not isinstance(row, dict):
                continue
            row.setdefault("assets", [])
            row.setdefault("attempts", [])
    if schema < 3:
        for row in data["assignments"]:
            if not isinstance(row, dict):
                continue
            row.setdefault("plan_id", "")
            row.setdefault("plan_digest", "")
            row.setdefault("lane_id", "")
            row.setdefault("effect", "")
            row.setdefault("assignment_attempt", 1)
            row.setdefault("reviews_assignments", [])
        data["schema"] = 3
    else:
        data["schema"] = schema
    _validate_assignments_data(data, parent_run=run_dir.name)
    return data


def _require_no_prepared_cancellation(run_dir: Path) -> None:
    if _agent_settlement is None:
        raise ValueError("agent_settlement unavailable; assignment mutation fails closed")
    transaction = _agent_settlement.load_transaction(run_dir)
    if transaction is not None and transaction.get("status") == "prepared":
        raise ValueError(
            "ASSIGNMENT_CANCELLATION_RECOVERY_REQUIRED: retry workers.py "
            f"cancel-unlaunched for {transaction.get('assignment')}")


@contextlib.contextmanager
def _cancellation_mutation_locks(run_dir: Path):
    """Freeze runtime append before taking the shared assignment writer lock."""
    if _runtime_receipts is None or not hasattr(_runtime_receipts, "_locked"):
        raise ValueError(
            "runtime receipt lock unavailable; cancellation fails closed")
    # runtime_receipts documents this exact lock order: event journal first,
    # assignment projection second.  Reversing it would deadlock hook recovery.
    with _runtime_receipts._locked(run_dir):
        with _assignment_mutation_lock(run_dir):
            yield


def _resolved_assignment_artifact(run_dir: Path, row: dict, field: str) -> Path:
    raw = str(row.get(field) or "")
    if not raw:
        raise ValueError(f"assignment {field} is missing")
    path = Path(raw)
    return (path if path.is_absolute() else ROOT / path).resolve(strict=False)


def _transcript_prefix_binding(contract: dict) -> dict:
    raw = str(contract.get("transcript_path") or "")
    path = Path(raw)
    if not raw or not path.is_absolute():
        raise ValueError("ASSIGNMENT_CANCELLATION_TRANSCRIPT_PATH_INVALID")
    try:
        metadata = path.lstat()
    except FileNotFoundError as exc:
        raise ValueError("ASSIGNMENT_CANCELLATION_TRANSCRIPT_MISSING") from exc
    if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISREG(metadata.st_mode):
        raise ValueError("ASSIGNMENT_CANCELLATION_TRANSCRIPT_TYPE_INVALID")
    payload = path.read_bytes()
    return {
        "session_id": str(contract.get("session_id") or ""),
        "prompt_sha256": str(contract.get("prompt_sha256") or ""),
        "contract_updated_at": float(contract.get("updated_at") or 0.0),
        "transcript_path": str(path.resolve(strict=True)),
        "transcript_length": len(payload),
        "transcript_prefix_sha256": hashlib.sha256(payload).hexdigest(),
    }


def _denied_agent_launch_ids(
    events: list[dict], *,
    assignment: str, plan_digest: str, lane_id: str,
    session_id: str = "", transcript_path: str = "",
) -> set[str]:
    """Return exact parent Agent calls that the hook proved never launched."""
    return {
        str(event.get("tool_use_id") or "")
        for event in events
        if event.get("hook_event_name") == "PreToolUseDenied"
        and event.get("tool_name") == "Agent"
        and event.get("decision") == "deny"
        and event.get("success") is False
        and str(event.get("assignment") or "") == assignment
        and str(event.get("assignment_plan_digest") or "") == plan_digest
        and str(event.get("assignment_lane") or "") == lane_id
        and (not session_id
             or str(event.get("session_id") or "") == session_id)
        and (not transcript_path
             or str(event.get("transcript_path") or "") == transcript_path)
        and str(event.get("tool_use_id") or "")
    }


def _assert_no_transcript_launch_intent(
    run_dir: Path, tombstone: dict,
) -> None:
    if _runtime_receipts is None \
            or not hasattr(_runtime_receipts, "_transcript_agent_tool_uses") \
            or not hasattr(_runtime_receipts, "_agent_invocation_binding"):
        raise ValueError(
            "runtime exact transcript parser unavailable; cancellation fails closed")
    binding = tombstone.get("turn_binding") \
        if isinstance(tombstone.get("turn_binding"), dict) else {}
    path = Path(str(binding.get("transcript_path") or ""))
    expected_length = int(binding.get("transcript_length") or 0)
    if path.is_symlink() or not path.is_file():
        raise ValueError("ASSIGNMENT_CANCELLATION_TRANSCRIPT_IDENTITY_CHANGED")
    with path.open("rb") as handle:
        prefix = handle.read(expected_length)
    if len(prefix) != expected_length \
            or hashlib.sha256(prefix).hexdigest() \
            != binding.get("transcript_prefix_sha256"):
        raise ValueError("ASSIGNMENT_CANCELLATION_TRANSCRIPT_PREFIX_CHANGED")
    try:
        candidates = _runtime_receipts._transcript_agent_tool_uses(path)
    except Exception as exc:
        raise ValueError("ASSIGNMENT_CANCELLATION_TRANSCRIPT_UNREADABLE") from exc
    events, chain_errors = _runtime_receipts.validate_chain(run_dir)
    if chain_errors:
        raise ValueError(
            "ASSIGNMENT_CANCELLATION_RUNTIME_CHAIN_INVALID:" + chain_errors[0])
    assignment = str(tombstone.get("assignment") or "")
    plan_digest = str(tombstone.get("plan_digest") or "")
    lane_id = str(tombstone.get("lane_id") or "")
    denied_tool_ids = _denied_agent_launch_ids(
        events,
        assignment=assignment,
        plan_digest=plan_digest,
        lane_id=lane_id,
        session_id=str(binding.get("session_id") or ""),
        transcript_path=str(path.resolve(strict=True)),
    )
    for candidate in candidates:
        parsed = _runtime_receipts._agent_invocation_binding(candidate)
        if parsed.get("assignment") != assignment:
            continue
        # A transcript contains the attempted Agent tool_use even when
        # PreToolUse rejects it.  Only an exact immutable deny receipt proves
        # that this particular invocation never crossed the launch boundary.
        # Any unretired or differently-bound tool_use remains launch debt.
        if str(parsed.get("tool_use_id") or "") in denied_tool_ids:
            continue
        # A malformed/incomplete prompt using the same assignment id is still
        # an in-flight launch intent; exact plan/lane equality only strengthens
        # the proof and never permits deletion.
        exact = parsed.get("assignment_plan_digest") == plan_digest \
            and parsed.get("assignment_lane") == lane_id
        detail = "exact" if exact else "conflicting"
        raise ValueError(
            f"ASSIGNMENT_CANCELLATION_TRANSCRIPT_LAUNCH_EXISTS:{detail}")


def _assert_no_assignment_runtime_records(
    run_dir: Path, assignment: str, *,
    plan_digest: str, lane_id: str,
    allow_typed_interrupted_reviewer_start: bool = False,
) -> None:
    if _runtime_receipts is None:
        raise ValueError("runtime_receipts unavailable; cancellation fails closed")
    events, chain_errors = _runtime_receipts.validate_chain(run_dir)
    if chain_errors:
        raise ValueError(
            "ASSIGNMENT_CANCELLATION_RUNTIME_CHAIN_INVALID:" + chain_errors[0])
    integrity = _runtime_receipts.agent_event_integrity_errors(run_dir)
    if integrity:
        raise ValueError(
            "ASSIGNMENT_CANCELLATION_RUNTIME_INTEGRITY_INVALID:" + integrity[0])
    runtime_events = (
        _runtime_receipts.effective_agent_events(run_dir)
        if allow_typed_interrupted_reviewer_start else events
    )
    denied_tool_ids = _denied_agent_launch_ids(
        runtime_events,
        assignment=assignment,
        plan_digest=plan_digest,
        lane_id=lane_id,
    )
    if any(
        str(event.get("assignment") or "") == assignment
        and not (
            event.get("hook_event_name") == "PreToolUseDenied"
            and event.get("tool_name") == "Agent"
            and str(event.get("tool_use_id") or "") in denied_tool_ids
        )
        for event in runtime_events
    ):
        raise ValueError("ASSIGNMENT_CANCELLATION_RUNTIME_EVENT_EXISTS")
    if any(str(item.get("assignment") or "") == assignment
           for item in _runtime_receipts.agent_attempts(run_dir)):
        raise ValueError("ASSIGNMENT_CANCELLATION_RUNTIME_ATTEMPT_EXISTS")
    if (run_dir / "state" / "runtime_projection_error.json").exists():
        raise ValueError("ASSIGNMENT_CANCELLATION_PROJECTION_ERROR_EXISTS")
    draft = _runtime_receipts.merge_draft_path(run_dir, assignment)
    if draft.exists():
        raise ValueError("ASSIGNMENT_CANCELLATION_MERGE_DRAFT_EXISTS")
    results = run_dir / "state" / "merge_results" / assignment
    if results.exists():
        if results.is_symlink() or not results.is_dir() or any(results.iterdir()):
            raise ValueError("ASSIGNMENT_CANCELLATION_RESULT_EXISTS")
    ledger = load_assignments(run_dir)
    if any(
        isinstance(item, dict) and assignment in [
            str(value) for value in item.get("reviews_assignments", [])]
        for item in ledger.get("assignments", [])
    ):
        raise ValueError("ASSIGNMENT_CANCELLATION_REVIEW_BINDING_EXISTS")


def _assert_no_assignment_runtime_activity(
    run_dir: Path, row: dict, plan: dict, lane: dict,
) -> None:
    assignment = str(row.get("agent") or "")
    if _role(str(row.get("role") or "")) == "review" \
            or _role(str(lane.get("role") or "")) == "review":
        raise ValueError("ASSIGNMENT_CANCELLATION_REVIEWER_FORBIDDEN")
    if str(row.get("status") or "").strip().lower() != "assigned" \
            or row.get("attempts") != []:
        raise ValueError("ASSIGNMENT_CANCELLATION_NOT_UNLAUNCHED")
    if any(row.get(field) not in (None, "", [], {}) for field in (
        "current_attempt", "runtime_agent_id", "review_result_digest",
        "root_disposition_at", "root_disposition_review_receipt_hash",
    )):
        raise ValueError("ASSIGNMENT_CANCELLATION_RUNTIME_STATE_EXISTS")
    _assert_no_assignment_runtime_records(
        run_dir, assignment,
        plan_digest=str(row.get("plan_digest") or ""),
        lane_id=str(row.get("lane_id") or ""),
    )
    projection = _run_model.plan_cycle_projection(run_dir, plan=plan)
    states = [
        item for item in projection.get("lane_states", [])
        if isinstance(item, dict) and item.get("lane_id") == lane.get("id")
    ]
    if len(states) != 1 or states[0].get("assignment") != assignment \
            or states[0].get("runtime_state") != "no-attempt" \
            or states[0].get("complete") is not False:
        raise ValueError("ASSIGNMENT_CANCELLATION_RUNTIME_PROJECTION_NOT_EMPTY")


def _prepared_cancellation_previous_row(transaction: dict) -> tuple[dict, dict]:
    try:
        previous = json.loads(transaction["previous_assignments_text"])
        following = json.loads(transaction["next_assignments_text"])
    except Exception as exc:
        raise ValueError("cancellation ledger snapshots are unreadable") from exc
    _validate_assignments_data(previous)
    _validate_assignments_data(following)
    assignment = str(transaction.get("assignment") or "")
    rows = [
        item for item in previous.get("assignments", [])
        if isinstance(item, dict) and item.get("agent") == assignment
    ]
    if len(rows) != 1 or any(
        isinstance(item, dict) and item.get("agent") == assignment
        for item in following.get("assignments", [])
    ):
        raise ValueError("cancellation ledger snapshots do not remove one exact row")
    if hashlib.sha256(json.dumps(
            rows[0], ensure_ascii=False, sort_keys=True,
            separators=(",", ":")).encode("utf-8")).hexdigest() \
            != transaction["tombstone"]["assignment_row_sha256"]:
        raise ValueError("cancellation frozen assignment row diverged")
    return rows[0], following


def _apply_prepared_cancellation_locked(
    run_dir: Path, transaction: dict, *, fault=None,
) -> dict:
    if transaction.get("status") == "committed":
        return transaction
    row, _following = _prepared_cancellation_previous_row(transaction)
    tombstone = transaction["tombstone"]
    plan = _work_plan.transaction_bound_plan(run_dir)
    if str(plan.get("plan_digest") or "") != transaction.get("plan_digest"):
        raise ValueError("ASSIGNMENT_CANCELLATION_PLAN_DIVERGED")
    lane = _work_plan.lane_by_id(plan, str(transaction.get("lane_id") or ""))
    current_path = _assignments_path(run_dir)
    current_text = current_path.read_text(encoding="utf-8", errors="strict")
    if current_text not in {
        transaction["previous_assignments_text"],
        transaction["next_assignments_text"],
    }:
        raise ValueError("ASSIGNMENT_CANCELLATION_LEDGER_DIVERGED")
    _assert_no_transcript_launch_intent(run_dir, tombstone)
    _assert_no_assignment_runtime_records(
        run_dir, str(transaction.get("assignment") or ""),
        plan_digest=str(transaction.get("plan_digest") or ""),
        lane_id=str(transaction.get("lane_id") or ""),
    )
    if current_text == transaction["previous_assignments_text"]:
        _assert_no_assignment_runtime_activity(run_dir, row, plan, lane)
    _agent_settlement.durable_unlink_artifact(
        run_dir, tombstone["agent_artifact"], directory="agents",
        pattern=r"A-[A-Za-z0-9._-]+\.md")
    if fault is not None:
        fault("after_agent_unlink")
    _agent_settlement.durable_unlink_artifact(
        run_dir, tombstone["context_artifact"], directory="context",
        pattern=r"[^/\\]+\.md")
    if fault is not None:
        fault("after_context_unlink")
    if current_text == transaction["previous_assignments_text"]:
        _agent_settlement.durable_atomic_text(
            current_path, transaction["next_assignments_text"])
    if fault is not None:
        fault("after_assignments_replace")
    # Only after the assignment and its launch artifacts are durably absent may
    # the immutable receipt assert the fact "cancelled-unlaunched".  Until this
    # point the prepared transaction itself is the launch/replan barrier.
    _agent_settlement.archive_cancellation(run_dir, tombstone)
    if fault is not None:
        fault("after_tombstone")
    transaction = dict(transaction)
    transaction["status"] = "committed"
    transaction["committed_at"] = datetime.now(timezone.utc).isoformat(
        timespec="milliseconds").replace("+00:00", "Z")
    transaction = _agent_settlement.save_transaction(run_dir, transaction)
    if fault is not None:
        fault("after_committed")
    return transaction


def _recover_prepared_cancellation_locked(run_dir: Path, *, fault=None) -> dict | None:
    if _agent_settlement is None:
        raise ValueError("agent_settlement unavailable; cancellation fails closed")
    transaction = _agent_settlement.load_transaction(run_dir)
    if transaction is None or transaction.get("status") != "prepared":
        return transaction
    return _apply_prepared_cancellation_locked(run_dir, transaction, fault=fault)


def cancel_unlaunched_assignment(
    run_dir: Path, assignment: str, *, reason: str, fault=None,
) -> dict:
    """Cancel one exact committed assignment that has provably never launched."""
    assignment = str(assignment or "").strip()
    reason = str(reason or "").strip()
    if not re.fullmatch(r"A-[A-Za-z0-9._-]+", assignment):
        raise ValueError("ASSIGNMENT_CANCELLATION_ASSIGNMENT_INVALID")
    if not reason or len(reason) > 4096:
        raise ValueError("ASSIGNMENT_CANCELLATION_REASON_INVALID")
    if fault is not None and not callable(fault):
        raise TypeError("cancellation fault injector must be callable")
    if _work_plan is None or _agent_settlement is None \
            or _runtime_receipts is None or _run_model is None:
        raise ValueError("cancellation contract dependencies unavailable")
    with _cancellation_mutation_locks(run_dir):
        _recover_prepared_delegate_transaction(run_dir)
        _recover_prepared_cancellation_locked(run_dir)
        existing = [
            item for item in _agent_settlement.cancellation_receipts(run_dir)
            if item.get("assignment") == assignment
        ]
        if len(existing) == 1:
            return existing[0]
        if len(existing) > 1:
            raise ValueError("ASSIGNMENT_CANCELLATION_IDENTITY_AMBIGUOUS")
        contract = _work_plan._load_turn_contract(run_dir)
        # Do not re-authorize the old plan under the current operator policy.
        # In particular, a current TARGET_EGRESS_DENIED turn must keep target
        # lanes blocked without making this local control-plane settlement
        # unreachable.  Immutable lineage is loaded below; exact input/turn
        # staleness is proven twice under the mutation locks before commit.
        plan = _transaction_bound_plan_for_cancellation(run_dir)
        data = load_assignments(run_dir)
        rows = [
            item for item in data.get("assignments", [])
            if isinstance(item, dict) and item.get("agent") == assignment
        ]
        if len(rows) != 1:
            raise ValueError("ASSIGNMENT_CANCELLATION_ASSIGNMENT_NOT_UNIQUE")
        row = rows[0]
        if str(row.get("plan_digest") or "") != str(plan.get("plan_digest") or ""):
            raise ValueError("ASSIGNMENT_CANCELLATION_PLAN_BINDING_INVALID")
        lane = _work_plan.lane_by_id(plan, str(row.get("lane_id") or ""))
        if _role(str(lane.get("role") or "")) != _role(str(row.get("role") or "")) \
                or str(lane.get("front") or "").upper() \
                != str(row.get("front") or "").upper() \
                or str(lane.get("effect") or "") != str(row.get("effect") or "") \
                or [str(item) for item in lane.get("assets", [])] \
                != [str(item) for item in row.get("assets", [])]:
            raise ValueError("ASSIGNMENT_CANCELLATION_LANE_BINDING_INVALID")
        delegate = _load_delegate_transaction(run_dir)
        if delegate is None or delegate.get("status") != "committed" \
                or delegate.get("plan_digest") != plan.get("plan_digest") \
                or assignment not in delegate.get("created_assignments", []) \
                or str(row.get("lane_id") or "") not in delegate.get("lane_ids", []):
            raise ValueError("ASSIGNMENT_CANCELLATION_DELEGATE_RECEIPT_MISSING")
        agent_path = _resolved_assignment_artifact(run_dir, row, "agent_file")
        context_path = _resolved_assignment_artifact(run_dir, row, "context")
        if agent_path.name not in delegate.get("created_agent_files", []) \
                or context_path.name not in delegate.get("created_context_files", []):
            raise ValueError("ASSIGNMENT_CANCELLATION_ARTIFACT_OWNERSHIP_INVALID")
        _assert_no_assignment_runtime_activity(run_dir, row, plan, lane)
        turn_binding = _transcript_prefix_binding(contract)
        plan_turn_binding = dict(plan.get("turn_binding") or {})
        observed_turn_binding = {
            "session_id": str(contract.get("session_id") or ""),
            "prompt_sha256": str(contract.get("prompt_sha256") or ""),
            "contract_updated_at": float(contract.get("updated_at") or 0.0),
        }
        provisional = {
            "assignment": assignment,
            "plan_digest": plan["plan_digest"],
            "lane_id": row["lane_id"],
            "turn_binding": turn_binding,
        }
        _assert_no_transcript_launch_intent(run_dir, provisional)
        observed_digest = _work_plan.input_fingerprint(run_dir)[0]
        inputs_changed = observed_digest != plan.get("inputs_digest")
        turn_changed = observed_turn_binding != plan_turn_binding
        stale_basis = (
            "both" if inputs_changed and turn_changed else
            "inputs" if inputs_changed else
            "turn" if turn_changed else ""
        )
        if not stale_basis:
            raise ValueError("ASSIGNMENT_CANCELLATION_PLAN_NO_LONGER_STALE")
        cancelled_at = datetime.now(timezone.utc).isoformat(
            timespec="milliseconds").replace("+00:00", "Z")
        row_digest = hashlib.sha256(json.dumps(
            row, ensure_ascii=False, sort_keys=True,
            separators=(",", ":")).encode("utf-8")).hexdigest()
        tombstone = _agent_settlement.build_cancellation(
            plan_id=plan["plan_id"], plan_digest=plan["plan_digest"],
            plan_inputs_digest=plan["inputs_digest"],
            observed_inputs_digest=observed_digest,
            stale_basis=stale_basis,
            plan_turn_binding=plan_turn_binding,
            observed_turn_binding=observed_turn_binding,
            lane_id=str(row["lane_id"]), assignment=assignment,
            assignment_attempt=int(row.get("assignment_attempt") or 0),
            role=str(row.get("role") or ""), front=str(row.get("front") or ""),
            effect=str(row.get("effect") or ""),
            assets=[str(item) for item in row.get("assets", [])],
            reason=reason, cancelled_at=cancelled_at, turn_binding=turn_binding,
            assignment_row_sha256=row_digest,
            delegate_transaction_id=delegate["transaction_id"],
            delegate_receipt_digest=delegate["receipt_digest"],
            agent_artifact=_agent_settlement.freeze_artifact(
                run_dir, agent_path, directory="agents",
                pattern=r"A-[A-Za-z0-9._-]+\.md"),
            context_artifact=_agent_settlement.freeze_artifact(
                run_dir, context_path, directory="context",
                pattern=r"[^/\\]+\.md"),
        )
        assignments_path = _assignments_path(run_dir)
        previous_text = assignments_path.read_text(
            encoding="utf-8", errors="strict")
        next_data = dict(data)
        next_data["assignments"] = [
            item for item in data["assignments"]
            if not (isinstance(item, dict) and item.get("agent") == assignment)
        ]
        _validate_assignments_data(next_data, parent_run=run_dir.name)
        next_text = json.dumps(
            next_data, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
        prepared_at = datetime.now(timezone.utc).isoformat(
            timespec="milliseconds").replace("+00:00", "Z")
        transaction = _agent_settlement.build_transaction(
            tombstone=tombstone,
            previous_assignments_text=previous_text,
            next_assignments_text=next_text,
            prepared_at=prepared_at,
        )
        transaction = _agent_settlement.save_transaction(run_dir, transaction)
        if fault is not None:
            fault("after_prepared")
        # The prepared receipt is now a turn-gate barrier.  Repeat both exact
        # proofs at the serialized cut before publishing the immutable tombstone.
        _assert_no_transcript_launch_intent(run_dir, tombstone)
        _assert_no_assignment_runtime_activity(run_dir, row, plan, lane)
        transaction = _apply_prepared_cancellation_locked(
            run_dir, transaction, fault=fault)
        return transaction["tombstone"]


def _validate_assignments_data(
    data: object,
    *,
    parent_run: str = "",
) -> None:
    if _runtime_receipts is None \
            or not hasattr(_runtime_receipts, "assignment_state_errors"):
        rows = data.get("assignments", []) if isinstance(data, dict) else []
        if any(
            isinstance(row, dict) and any(str(row.get(field) or "") for field in (
                "plan_id", "plan_digest", "lane_id",
            ))
            for row in rows if isinstance(rows, list)
        ):
            raise ValueError(
                "runtime_receipts unavailable; cannot validate plan-bound assignments")
        return
    errors = _runtime_receipts.assignment_state_errors(
        data, parent_run=parent_run)
    if errors:
        raise ValueError("assignments.json contract invalid: " + errors[0])


def _next_agent_id(run_dir: Path, role: str) -> str:
    prefix = f"A-{_slug(role)}-"
    n = 0
    for p in sorted(agents_dir(run_dir).glob(f"{prefix}*.md")) if agents_dir(run_dir).exists() else []:
        m = re.match(rf"{re.escape(prefix)}(\d+)\.md$", p.name)
        if m:
            n = max(n, int(m.group(1)))
    if _agent_settlement is not None:
        for assignment in _agent_settlement.cancelled_assignment_ids(run_dir):
            m = re.fullmatch(rf"{re.escape(prefix)}(\d+)", assignment)
            if m:
                n = max(n, int(m.group(1)))
    return f"{prefix}{n + 1:03d}"


def _front_title(run_dir: Path, front: str) -> str:
    for f in parse_frontiers(run_dir):
        if f.get("id") == front:
            return str(f.get("title") or front)
    return front


def _front_text(run_dir: Path, front: str) -> str:
    for f in parse_frontiers(run_dir):
        if f.get("id") == front:
            return str(f.get("text") or "")
    return ""


def _agent_rdt_profile(run_dir: Path, role: str, front: str) -> dict:
    front_text = _front_text(run_dir, front)
    if _context_pack is not None and hasattr(_context_pack, "resolve_rdt_profile"):
        return _context_pack.resolve_rdt_profile(run_dir, role=role, front_text=front_text)
    return {
        "source": "built-in defaults (context_pack unavailable)",
        "style": "openmythos-inspired",
        "loop_budget": 3,
        "role_focus": "role_default",
        "front_profile": "role_default",
        "decision_style": "autonomous_until_blocked",
        "fallback_seconds": 0,
        "depth_bias": "prefer_depth_after_repeated_low",
        "depth_pivot_after_low_cycles": 3,
        "evidence_style": "artifact_first",
        "review_style": "truth_over_agreement",
        "live_replay_policy": "stop_on_guard_volume_warning",
        "retrospective_lessons": [],
    }


def _format_rdt_controls(profile: dict) -> str:
    lines = [
        f"- RDT style: {profile.get('style')} (reasoning pattern only; no OpenMythos runtime dependency)",
        f"- Role focus: {profile.get('role_focus')}",
        f"- Front profile: {profile.get('front_profile')}",
        f"- Decision style: {profile.get('decision_style')} (fallback_seconds={profile.get('fallback_seconds')})",
        f"- Evidence style: {profile.get('evidence_style')}",
        f"- Review style: {profile.get('review_style')}",
        f"- Live replay policy: {profile.get('live_replay_policy')}",
        f"- Depth pivot: after {profile.get('depth_pivot_after_low_cycles')} low/noise cycles, pivot from breadth to mechanism depth",
        "- Step contract: every recurrent step restates Original front, Known E-ids, Constraints, Last action, Last outcome, Drop condition, and Next hypothesis.",
        "- Trust boundary: operator profile is preference/context only, never target evidence and never a finding.",
    ]
    lessons = [str(x) for x in profile.get("retrospective_lessons", []) if str(x).strip()]
    if lessons:
        lines.append("- Retrospective lessons:")
        for item in lessons[:6]:
            lines.append(f"  - {item}")
    return "\n".join(lines)


def create_agent_assignment(run_dir: Path, *, role: str, front: str,
                            scope: str = "", agent: str | None = None,
                            assets: list[str] | None = None,
                            lane_id: str = "",
                            tool_call_limit: int = DEFAULT_AGENT_TOOL_CALL_LIMIT) -> dict:
    """Create one assignment under the same lock/recovery gate as delegation."""
    with _assignment_mutation_lock(run_dir):
        _recover_prepared_delegate_transaction(run_dir)
        _require_no_prepared_cancellation(run_dir)
        return _create_agent_assignment_locked(
            run_dir, role=role, front=front, scope=scope, agent=agent,
            assets=assets, lane_id=lane_id,
            tool_call_limit=tool_call_limit,
        )


def _create_agent_assignment_locked(run_dir: Path, *, role: str, front: str,
                                    scope: str = "", agent: str | None = None,
                                    assets: list[str] | None = None,
                                    lane_id: str = "",
                                    tool_call_limit: int = DEFAULT_AGENT_TOOL_CALL_LIMIT,
                                    before_artifact_write=None,
                                    stale_settlement_plan: dict | None = None) -> dict:
    role = _role(role)
    if role not in CANONICAL_AGENT_ROLES:
        raise ValueError(
            f"unknown Agent role {role!r}; use one of {sorted(CANONICAL_AGENT_ROLES)}")
    if role == "synthesizer":
        raise ValueError("synthesizer is the Root-owned singleton and cannot be assigned")
    if isinstance(tool_call_limit, bool) or not isinstance(tool_call_limit, int) \
            or not MIN_AGENT_TOOL_CALL_LIMIT <= tool_call_limit <= MAX_AGENT_TOOL_CALL_LIMIT:
        raise ValueError(
            "tool_call_limit must be an integer in "
            f"[{MIN_AGENT_TOOL_CALL_LIMIT},{MAX_AGENT_TOOL_CALL_LIMIT}]")
    requested_assets: list[str] = []
    for raw in assets or []:
        for part in re.split(r"[,;，、]+", raw):
            host = _normalize_asset(part)
            if host and host not in requested_assets:
                requested_assets.append(host)
    plan, lane = _current_plan_lane(
        run_dir, lane_id=lane_id, role=role, front=front,
        assets=requested_assets,
        stale_settlement_plan=stale_settlement_plan,
    )
    effect = str(lane.get("effect") or "")
    if effect in {"control", "repo_mutation"}:
        raise ValueError(
            f"lane effect={effect} is Root single-writer work and cannot be assigned")
    asset_names, inventory = _resolve_assignment_assets(
        run_dir, front, requested_assets, role, effect=effect)
    data = load_assignments(run_dir)
    if lane:
        overlaps: list[str] = []
        for existing in data.get("assignments", []):
            if not isinstance(existing, dict):
                continue
            status = _normalized_agent_status(str(existing.get("status") or ""))
            if status in TERMINAL_AGENT_STATUSES:
                continue
            existing_effect = str(existing.get("effect") or "")
            shared = sorted(
                set(asset_names)
                & set(_normalize_asset(a) for a in existing.get("assets", [])))
            if effect == "target" and existing_effect == "target" and shared:
                overlaps.extend(
                    f"{host} ({existing.get('agent')})" for host in shared)
        if overlaps:
            raise ValueError(
                "asset already has a non-terminal target-effect assignment; "
                "target overlap is forbidden regardless of role: " + ", ".join(overlaps))
    elif role not in {"verify", "review"}:
        overlaps: list[str] = []
        for existing in data.get("assignments", []):
            if not isinstance(existing, dict):
                continue
            if _role(str(existing.get("role") or "")) in {"verify", "review"}:
                continue
            status = _normalized_agent_status(str(existing.get("status") or ""))
            if status in TERMINAL_AGENT_STATUSES:
                continue
            shared = sorted(set(asset_names) & set(_normalize_asset(a) for a in existing.get("assets", [])))
            if shared:
                overlaps.extend(f"{host} ({existing.get('agent')})" for host in shared)
        if overlaps:
            raise ValueError(
                "asset already has a non-terminal assignment; overlap is reserved for verify/review roles: "
                + ", ".join(overlaps))
    agent_id = agent or _next_agent_id(run_dir, role)
    prior_attempts = [
        int(item.get("assignment_attempt") or 0)
        for item in data.get("assignments", []) if isinstance(item, dict)
        and str(item.get("lane_id") or "") == str(lane.get("id") or "")
    ] if lane else []
    reviews_assignments: list[str] = []
    review_result_digest = ""
    if role == "review" and lane:
        dependencies = {str(item) for item in lane.get("dependencies", [])}
        reviews_assignments = sorted({
            str(item.get("agent") or "") for item in data.get("assignments", [])
            if isinstance(item, dict)
            and str(item.get("plan_digest") or "") == str(plan.get("plan_digest") or "")
            and str(item.get("lane_id") or "") in dependencies
            and str(item.get("agent") or "")
        })
        if len(reviews_assignments) != 1:
            raise ValueError(
                "plan-bound Reviewer lane must depend on exactly one returned assignment")
    assignment_attempt = max(prior_attempts or [0]) + 1
    asset_digest = hashlib.sha256(json.dumps(
        asset_names, ensure_ascii=False, separators=(",", ":"),
    ).encode("utf-8")).hexdigest()[:12]
    ctx_name = (
        f"{agent_id}.{front}.{asset_digest}.attempt-{assignment_attempt:03d}.md"
    )
    ctx_path = context_dir(run_dir) / ctx_name
    if _context_pack is None:
        raise ValueError(
            "context_pack unavailable; refusing to create an unbound Agent artifact")
    role_bundle = _instruction_bundle.load_role_contract(role, root=ROOT)
    role_contract = role_bundle["contract"]
    if role_contract.get("assignable") is False \
            or role_contract.get("subagent_type") not in {
                "xunji-hunter", "xunji-reviewer",
            }:
        raise ValueError("Agent role has no assignable live Claude definition")
    ctx_text = _context_pack.build_pack(
        run_dir, front=front, role=role, agent=agent_id,
        assets=asset_names, effect=effect,
        lane_id=str(lane.get("id") or ""),
        plan_digest=str(plan.get("plan_digest") or ""),
        assignment_attempt=assignment_attempt,
        tool_call_limit=tool_call_limit,
        request_budget=int(lane.get("request_budget") or 0),
        role_bundle=role_bundle,
    )
    if reviews_assignments and _runtime_receipts is not None:
        ctx_text = ctx_text.rstrip() + "\n\n## Frozen Merge Drafts\n\n"
        for target_assignment in reviews_assignments:
            draft_path = _runtime_receipts.merge_draft_path(run_dir, target_assignment)
            try:
                draft = json.loads(draft_path.read_text(
                    encoding="utf-8", errors="strict"))
            except Exception as exc:
                raise ValueError(
                    f"frozen merge draft missing for dependency {target_assignment}") from exc
            digest = str(draft.get("result_digest") or "")
            if not re.fullmatch(r"[0-9a-f]{64}", digest):
                raise ValueError(
                    f"frozen merge draft has invalid result digest for {target_assignment}")
            review_result_digest = digest
            ctx_text += (
                f"- Assignment: {target_assignment}\n"
                f"  - Draft: {display_path(draft_path)}\n"
                f"  - Result digest: {draft.get('result_digest') or '(missing)'}\n"
                f"  - Lane: {draft.get('lane_id') or '(missing)'}\n"
            )
    agent_path = agents_dir(run_dir) / f"{agent_id}.md"
    created = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    scope_text = scope or "run target scope"
    assets_text = ", ".join(asset_names) if asset_names else "none (non-target lane)"
    rdt_profile = _agent_rdt_profile(run_dir, role, front)
    context_rel = display_path(ctx_path)
    agent_rel = display_path(agent_path)
    context_descriptor = _instruction_bundle.artifact_descriptor(
        context_rel, ctx_text)
    scaffold = _instruction_bundle.load_scaffold_source(root=ROOT)
    agent_text = scaffold["text"].format(
        agent=agent_id,
        role=role,
        front=front,
        assets=assets_text,
        effect=effect or "legacy-untyped",
        lane_id=str(lane.get("id") or "legacy-unbound"),
        plan_id=str(plan.get("plan_id") or "legacy-unbound"),
        plan_digest=str(plan.get("plan_digest") or "legacy-unbound"),
        assignment_attempt=assignment_attempt,
        asset_outcomes=_asset_outcomes_scaffold(asset_names, inventory),
        scope=scope_text,
        context_rel=context_rel,
        context_sha256=context_descriptor["sha256"],
        role_contract_version=role_contract["schema"],
        role_contract_sha256=role_contract["composed_sha256"],
        subagent_type=role_contract["subagent_type"],
        live_agent_sha256=role_contract["live_agent"]["sha256"],
        created=created,
        loop_budget=rdt_profile["loop_budget"],
        profile_source=rdt_profile["source"],
        rdt_controls=_format_rdt_controls(rdt_profile),
    )
    instruction_bundle: dict = {}
    instruction_bundle_sha256 = ""
    if plan:
        instruction_bundle, instruction_bundle_sha256 = (
            _instruction_bundle.build_assignment_bundle(
                assignment=agent_id,
                plan_digest=str(plan.get("plan_digest") or ""),
                lane_id=str(lane.get("id") or ""),
                role=role,
                role_bundle=role_bundle,
                scaffold_source=scaffold["source"],
                context_path=context_rel,
                context_text=ctx_text,
                agent_path=agent_rel,
                agent_text=agent_text,
            )
        )
    if before_artifact_write is not None:
        before_artifact_write(agent_id, agent_path, ctx_path)
    written: list[Path] = []
    try:
        _atomic_write(ctx_path, ctx_text)
        written.append(ctx_path)
        _atomic_write(agent_path, agent_text)
        written.append(agent_path)
    except Exception:
        for path in reversed(written):
            path.unlink(missing_ok=True)
        raise

    rec = {
        **({"schema": "xunji.assignment.v1"} if plan else {}),
        "agent": agent_id,
        "role": role,
        "front": front,
        "front_title": _front_title(run_dir, front),
        "plan_id": str(plan.get("plan_id") or ""),
        "plan_digest": str(plan.get("plan_digest") or ""),
        "lane_id": str(lane.get("id") or ""),
        "effect": effect,
        "assignment_attempt": assignment_attempt,
        "assets": asset_names,
        "asset_ids": [
            _canonical_asset_id(inventory.get(host), host)
            for host in asset_names
        ],
        "coverage_before": {
            host: _coverage_snapshot(inventory[host]) for host in asset_names
        },
        "scope": scope_text,
        "status": "assigned",
        "reasoning_style": "personalized-rdt",
        "loop_budget": rdt_profile["loop_budget"],
        "tool_call_limit": tool_call_limit,
        "request_budget": int(lane.get("request_budget") or 0),
        "operator_profile": rdt_profile["source"],
        "context": context_rel,
        "agent_file": agent_rel,
        **({
            "instruction_bundle": instruction_bundle,
            "instruction_bundle_sha256": instruction_bundle_sha256,
        } if plan else {}),
        "created_at": created,
        "updated_at": created,
        "attempts": [],
        "reviews_assignments": reviews_assignments,
        **({"review_result_digest": review_result_digest}
           if review_result_digest else {}),
        "coverage_merge_satisfied": False,
    }
    if plan:
        try:
            _instruction_bundle.verify_assignment_bundle(
                run_dir, rec, root=ROOT)
        except Exception:
            ctx_path.unlink(missing_ok=True)
            agent_path.unlink(missing_ok=True)
            raise
    data["assignments"] = [a for a in data["assignments"] if a.get("agent") != agent_id]
    data["assignments"].append(rec)
    _validate_assignments_data(data, parent_run=run_dir.name)
    _atomic_write(_assignments_path(run_dir), json.dumps(data, ensure_ascii=False, indent=2) + "\n")
    return rec


def _agent_status_from_file(path: Path) -> str:
    text = path.read_text(encoding="utf-8", errors="replace") if path.exists() else ""
    status = (_field(text, "Status") or "?").lower()
    if _normalized_agent_status(status) in {"assigned", "working", "?"} and _has_completion_findings(text):
        return "done (findings appended)"
    return status


def _has_completion_findings(text: str) -> bool:
    m = re.search(r"(?ims)^##\s+Findings\b.*?(?=^##\s+|\Z)", text)
    if not m:
        return False
    body = re.sub(r"(?m)^##\s+Findings\b.*$", "", m.group(0)).strip()
    if not body:
        return False
    if re.search(r"(?i)\b(still investigating|pending|tbc|tbd|todo|placeholder|draft only)\b", body):
        return False
    structured = re.search(
        r"(?im)^\s*[-*]\s*(Candidate|Phenomenon|Refutes|Evidence|Control|Artifact|Result|Verdict)\s*[:：]",
        body,
    )
    plain_completion = re.search(
        r"(?i)\b(no exploitable|no findings|not exploitable|refuted|auth[- ]?gated|blocked|complete|done)\b",
        body,
    )
    return bool(structured or plain_completion)


def _normalized_agent_status(status: str) -> str:
    status_l = (status or "").strip().lower()
    if status_l.startswith(("done", "complete", "completed")):
        return "done"
    if status_l.startswith("merged"):
        return "merged"
    if status_l.startswith("reviewed"):
        return "reviewed"
    if status_l.startswith(("run", "active")):
        return "running"
    if status_l.startswith("start"):
        return "starting"
    if status_l.startswith(("fail", "error")):
        return "failed"
    if status_l.startswith(("abandon", "cancel")):
        return "abandoned"
    if status_l.startswith("block"):
        return "blocked"
    if status_l.startswith("work"):
        return "working"
    if status_l.startswith("assign"):
        return "assigned"
    return status_l or "?"


def agent_status_rows(run_dir: Path) -> list[dict]:
    with _assignment_mutation_lock(run_dir):
        return _agent_status_rows_locked(run_dir)


def _agent_status_rows_locked(run_dir: Path) -> list[dict]:
    data = load_assignments(run_dir)
    rows = []
    changed = False
    for rec in data.get("assignments", []):
        if not isinstance(rec, dict):
            continue
        ap = ROOT / rec["agent_file"] if not Path(rec.get("agent_file", "")).is_absolute() else Path(rec["agent_file"])
        row = dict(rec)
        row["file_status"] = _agent_status_from_file(ap)
        file_status_norm = _normalized_agent_status(row["file_status"])
        rec_status_norm = _normalized_agent_status(str(rec.get("status") or ""))
        plan_bound = bool(
            str(rec.get("plan_digest") or "") and str(rec.get("lane_id") or ""))
        if not plan_bound and file_status_norm == "done" \
                and rec_status_norm in {"assigned", "working", "?"}:
            rec["status"] = "done"
            rec["updated_at"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
            row["status"] = "done"
            changed = True
        if ap.exists():
            text = ap.read_text(encoding="utf-8", errors="replace")
            row["parse_error"] = not (_field(text, "Role") and _field(text, "Assigned front"))
        else:
            row["parse_error"] = True
        rows.append(row)
    if changed:
        _validate_assignments_data(data, parent_run=run_dir.name)
        _atomic_write(_assignments_path(run_dir), json.dumps(data, ensure_ascii=False, indent=2) + "\n")
    return rows


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def _parse_iso(ts: str | None) -> float | None:
    if not ts:
        return None
    try:
        return datetime.fromisoformat(ts.strip().replace("Z", "+00:00")).timestamp()
    except Exception:
        return None


def _agent_file_from_rec(rec: dict) -> Path | None:
    raw = str(rec.get("agent_file") or "")
    if not raw:
        return None
    path = Path(raw)
    return path if path.is_absolute() else ROOT / path


def _patch_agent_file_lifecycle(path: Path | None, *, status: str, note: str, stamp: str) -> None:
    if not path or not path.exists():
        return
    text = path.read_text(encoding="utf-8", errors="replace")
    if _has_field_label(text, "Status"):
        text = re.sub(r"(?im)^(\s*[-*]?\s*Status\s*[:：]).*$", rf"\1 {status}", text, count=1)
    else:
        text = text.rstrip() + f"\n- Status: {status}\n"
    note_text = note.strip() or "-"
    entry = f"- {stamp} status={status} note={note_text}\n"
    if re.search(r"(?im)^##\s+Lifecycle\b", text):
        text = re.sub(r"(?im)^##\s+Lifecycle\b", "## Lifecycle\n" + entry.rstrip(), text, count=1)
    else:
        text = text.rstrip() + "\n\n## Lifecycle\n\n" + entry
    _atomic_write(path, text if text.endswith("\n") else text + "\n")


def _validate_asset_merge(run_dir: Path, rec: dict) -> dict:
    assets = [_normalize_asset(item) for item in rec.get("assets", []) if _normalize_asset(item)]
    if not assets:
        return {"satisfied": True, "legacy_or_non_target": True, "assets": {}}
    effect = str(rec.get("effect") or "")
    plan_bound = bool(str(rec.get("plan_digest") or "") and str(rec.get("lane_id") or ""))
    if plan_bound and effect in {"local_read", "local_verify", "model_egress"}:
        return {
            "satisfied": True,
            "non_target_effect": effect,
            "assets": {
                host: {"target_actions_required": False} for host in assets
            },
        }
    if plan_bound and effect != "target":
        raise ValueError(
            f"plan-bound merge has invalid/unassignable effect={effect or '(missing)'}")
    if _runtime_receipts is None:
        raise ValueError("runtime_receipts unavailable; cannot prove per-asset Agent activity")
    attempts = [item for item in _runtime_receipts.agent_attempts(run_dir)
                if item.get("assignment") == rec.get("agent")]
    if not any(item.get("state") == "returned" for item in attempts):
        raise ValueError("merged requires a real returned Agent attempt (SubagentStop)")
    activity = _runtime_receipts.agent_asset_activity(run_dir, str(rec.get("agent") or ""))
    no_activity = [host for host in assets if int(activity.get(host, 0) or 0) < 1]
    if no_activity:
        raise ValueError(
            "per-asset settlement gate failed; no successful target-action receipt: "
            + ", ".join(no_activity))
    return {
        "satisfied": True,
        "validated_at": _now_iso(),
        "assets": {host: {"target_actions": int(activity.get(host, 0) or 0),
                           "canonical_promotion": "pending_root_synthesis"}
                   for host in assets},
    }


def _plan_cycle_is_ended(run_dir: Path, plan_digest: str) -> bool:
    if not plan_digest:
        return False
    if not re.fullmatch(r"[0-9a-f]{64}", str(plan_digest)):
        raise ValueError(
            "plan-bound lifecycle mutation refused: invalid plan digest")
    if _loop_journal is None \
            or not hasattr(_loop_journal, "validate_cycle_events"):
        raise ValueError(
            "plan-bound lifecycle mutation refused: loop journal unavailable")
    try:
        state = _loop_journal.validate_cycle_events(
            _loop_journal.load_events(run_dir))
    except Exception as exc:
        code = str(getattr(exc, "code", "") or exc.__class__.__name__)
        raise ValueError(
            "plan-bound lifecycle mutation refused: invalid loop journal "
            f"({code})"
        ) from exc
    return str(plan_digest) in {
        str(item) for item in state.get("ended_plan_digests", [])
    }


def _current_review_receipt(run_dir: Path, rec: dict) -> dict:
    if str(rec.get("role") or "") == "review":
        return {}
    if not str(rec.get("plan_digest") or "") or not str(rec.get("lane_id") or ""):
        return {"schema": "xunji.legacy-review-not-required"}
    if _runtime_receipts is None or _run_model is None:
        return {}
    try:
        if _work_plan is None:
            return {}
        plan = _work_plan.load_plan_snapshot(
            run_dir, str(rec.get("plan_digest") or ""))
        projection = _run_model.plan_cycle_projection(run_dir, plan=plan)
    except Exception:
        return {}
    state = next((
        item for item in projection.get("lane_states", [])
        if isinstance(item, dict)
        and item.get("lane_id") == rec.get("lane_id")
        and item.get("assignment") == rec.get("agent")
    ), {})
    expected_hash = str(state.get("review_receipt_hash") or "")
    if not expected_hash:
        return {}
    path = _runtime_receipts.merge_draft_path(run_dir, str(rec.get("agent") or ""))
    try:
        draft = json.loads(path.read_text(encoding="utf-8", errors="strict"))
    except Exception:
        return {}
    receipt = draft.get("review_receipt") if isinstance(draft, dict) else None
    if not (
        draft.get("schema") == "xunji.merge-draft.v1"
        and draft.get("review_status") == "complete"
        and isinstance(receipt, dict)
        and receipt.get("receipt_hash") == expected_hash
    ):
        return {}
    return receipt


def _review_receipt_complete(run_dir: Path, rec: dict) -> bool:
    return bool(_current_review_receipt(run_dir, rec))


def record_review_disposition(run_dir: Path, *, target: str, reviewer: str,
                              disposition: str, note: str) -> dict:
    with _assignment_mutation_lock(run_dir):
        return _record_review_disposition_locked(
            run_dir, target=target, reviewer=reviewer,
            disposition=disposition, note=note,
        )


_EVIDENCE_REF_RE = re.compile(
    r"(?<![A-Za-z0-9._/-])((?:runs/[A-Za-z0-9._-]+/)?evidence/"
    r"[A-Za-z0-9._/-]+)"
)


def _evidence_references(run_dir: Path, text: str) -> dict[str, Path]:
    """Return normalized run-local evidence references from one frozen result."""
    references: dict[str, Path] = {}
    prefix = f"runs/{run_dir.name}/"
    resolved_prefix = str(run_dir.resolve()).rstrip("/") + "/"
    absolute_prefix = str(run_dir.absolute()).rstrip("/") + "/"
    # Claude's Read tool reports absolute paths (and macOS may spell /tmp as
    # /private/tmp). Normalize both exact run roots before applying the bounded
    # run-local grammar; containment is still revalidated below.
    text = text.replace(resolved_prefix, prefix)
    if absolute_prefix != resolved_prefix:
        text = text.replace(absolute_prefix, prefix)
    for match in _EVIDENCE_REF_RE.finditer(text):
        raw = match.group(1).rstrip(".,);]}")
        relative = raw[len(prefix):] if raw.startswith(prefix) else raw
        if not relative.startswith("evidence/"):
            continue
        candidate = (run_dir / relative).resolve()
        try:
            candidate.relative_to(run_dir.resolve())
        except ValueError as exc:
            raise ValueError(f"evidence reference escapes run: {raw}") from exc
        references[relative] = candidate
    return references


def _frozen_result_text(draft: dict, *, label: str) -> str:
    result = draft.get("result") if isinstance(draft.get("result"), dict) else {}
    path = Path(str(result.get("path") or ""))
    try:
        return path.read_text(encoding="utf-8", errors="strict")
    except Exception as exc:
        raise ValueError(f"{label} frozen result is unavailable") from exc


def _validated_replay_body(
    run_dir: Path, replay_ref: str, replay: dict, response: dict,
    body_path: Path,
) -> dict:
    """Validate saved bytes separately from the full wire-response digest.

    Legacy replay sidecars used ``response.sha1`` for the full wire body even
    when guard capping saved only a prefix.  New v2 sidecars bind both byte
    domains.  A legacy capped body remains an honest partial artifact; an empty
    or malformed wire digest never bypasses integrity checks.
    """
    body = body_path.read_bytes()
    saved_len = len(body)
    saved_sha1 = hashlib.sha1(body).hexdigest()
    wire_len_raw = response.get("wire_len", response.get("len"))
    wire_sha1 = str(response.get("wire_sha1") or response.get("sha1") or "")
    if isinstance(wire_len_raw, bool) or not isinstance(wire_len_raw, int) \
            or wire_len_raw < 0:
        raise ValueError(f"replay sidecar has invalid wire length: {replay_ref}")
    wire_len = int(wire_len_raw)
    if not re.fullmatch(r"[0-9a-f]{40}", wire_sha1):
        raise ValueError(f"replay sidecar has missing/invalid wire hash: {replay_ref}")
    if saved_len > wire_len:
        raise ValueError(f"replay sidecar saved body exceeds wire length: {replay_ref}")

    meta = replay.get("saved_body_meta")
    if replay.get("schema") == "xunji.probe.replay.v2" and not isinstance(meta, dict):
        raise ValueError(f"v2 replay sidecar lacks saved_body_meta: {replay_ref}")
    if isinstance(meta, dict):
        meta_len = meta.get("len")
        meta_sha1 = str(meta.get("sha1") or "")
        meta_truncated = meta.get("truncated")
        if isinstance(meta_len, bool) or not isinstance(meta_len, int) \
                or meta_len < 0 \
                or not re.fullmatch(r"[0-9a-f]{40}", meta_sha1) \
                or not isinstance(meta_truncated, bool):
            raise ValueError(f"replay sidecar has invalid saved_body_meta: {replay_ref}")
        if meta_len != saved_len or meta_sha1 != saved_sha1:
            raise ValueError(f"replay sidecar saved body hash mismatch: {replay_ref}")
        if meta_truncated != (saved_len < wire_len):
            raise ValueError(f"replay sidecar truncation metadata mismatch: {replay_ref}")
        truncated = meta_truncated
    else:
        truncated = saved_len < wire_len

    wire_verified = False
    manifest_token = str(replay.get("saved_body_chunks") or "")
    if manifest_token:
        manifest_refs = _evidence_references(run_dir, manifest_token)
        if len(manifest_refs) != 1:
            raise ValueError(f"replay sidecar has invalid chunk manifest: {replay_ref}")
        _, manifest_path = next(iter(manifest_refs.items()))
        try:
            manifest = json.loads(
                manifest_path.read_text(encoding="utf-8", errors="strict"))
        except Exception as exc:
            raise ValueError(f"replay chunk manifest is unavailable: {replay_ref}") from exc
        chunks = manifest.get("chunks") if isinstance(manifest, dict) else None
        if manifest.get("schema") != "xunji.probe.body_chunks.v1" \
                or manifest.get("full_len") != wire_len \
                or str(manifest.get("full_sha1") or "") != wire_sha1 \
                or not isinstance(chunks, list) or not chunks:
            raise ValueError(f"replay chunk manifest binding mismatch: {replay_ref}")
        full_hash = hashlib.sha1()
        next_offset = 0
        total = 0
        for chunk in chunks:
            if not isinstance(chunk, dict):
                raise ValueError(f"replay chunk entry is invalid: {replay_ref}")
            refs = _evidence_references(run_dir, str(chunk.get("file") or ""))
            if len(refs) != 1:
                raise ValueError(f"replay chunk path is invalid: {replay_ref}")
            _, chunk_path = next(iter(refs.items()))
            part = chunk_path.read_bytes()
            expected_bytes = chunk.get("bytes")
            expected_offset = chunk.get("offset")
            expected_sha1 = str(chunk.get("sha1") or "")
            if isinstance(expected_bytes, bool) or not isinstance(expected_bytes, int) \
                    or isinstance(expected_offset, bool) \
                    or not isinstance(expected_offset, int) \
                    or expected_offset != next_offset \
                    or expected_bytes != len(part) \
                    or not re.fullmatch(r"[0-9a-f]{40}", expected_sha1) \
                    or hashlib.sha1(part).hexdigest() != expected_sha1:
                raise ValueError(f"replay chunk integrity mismatch: {replay_ref}")
            full_hash.update(part)
            total += len(part)
            next_offset += len(part)
        if total != wire_len or full_hash.hexdigest() != wire_sha1:
            raise ValueError(f"replay full-body chunk hash mismatch: {replay_ref}")
        wire_verified = True
    elif not truncated:
        if saved_sha1 != wire_sha1:
            raise ValueError(f"replay sidecar full body hash mismatch: {replay_ref}")
        wire_verified = True

    return {
        "wire_len": wire_len,
        "wire_sha1": wire_sha1,
        "saved_len": saved_len,
        "saved_sha1": saved_sha1,
        "truncated": truncated,
        "wire_verified": wire_verified,
    }


def _validated_review_artifacts(run_dir: Path, *, target_row: dict,
                                target_text: str, reviewer_text: str,
                                disposition: str) -> list[dict]:
    """Validate the exact artifact set before accepting a target-effect result.

    Task notifications and model summaries are transient.  The frozen target and
    Reviewer results must name the same run-local evidence set, every path must
    exist, and replay sidecars must bind a saved body whose hash still matches.
    """
    if disposition != "accept-candidate" or str(target_row.get("effect") or "") != "target":
        return []
    target_refs = _evidence_references(run_dir, target_text)
    reviewer_refs = _evidence_references(run_dir, reviewer_text)
    if not target_refs:
        raise ValueError(
            "target accept-candidate requires exact absolute or run-relative "
            "run-local evidence references in both frozen results")
    if set(reviewer_refs) != set(target_refs):
        missing = sorted(set(target_refs) - set(reviewer_refs))
        extra = sorted(set(reviewer_refs) - set(target_refs))
        detail = []
        if missing:
            detail.append("Reviewer omitted " + ", ".join(missing))
        if extra:
            detail.append("Reviewer added " + ", ".join(extra))
        raise ValueError("Reviewer evidence set mismatch: " + "; ".join(detail))
    missing_paths = sorted(ref for ref, path in target_refs.items() if not path.is_file())
    if missing_paths:
        raise ValueError("frozen result references missing evidence: " + ", ".join(missing_paths))
    receipts: list[dict] = []
    for ref in sorted(target_refs):
        path = target_refs[ref]
        entry = {
            "path": ref,
            "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
            "size": path.stat().st_size,
        }
        if ref.endswith(".replay.json"):
            try:
                replay = json.loads(path.read_text(encoding="utf-8", errors="strict"))
            except Exception as exc:
                raise ValueError(f"invalid replay sidecar: {ref}") from exc
            request = replay.get("request") if isinstance(replay.get("request"), dict) else {}
            response = replay.get("response") if isinstance(replay.get("response"), dict) else {}
            saved_body = str(replay.get("saved_body") or "")
            saved_refs = _evidence_references(run_dir, saved_body)
            if len(saved_refs) != 1:
                raise ValueError(f"replay sidecar has invalid saved_body: {ref}")
            body_ref, body_path = next(iter(saved_refs.items()))
            if body_ref not in target_refs or not body_path.is_file():
                raise ValueError(f"replay sidecar body is absent from frozen artifact set: {ref}")
            if not request.get("method") or not request.get("url") \
                    or not isinstance(response.get("status"), int):
                raise ValueError(f"replay sidecar lacks request/response binding: {ref}")
            body_binding = _validated_replay_body(
                run_dir, ref, replay, response, body_path)
            entry["request"] = {
                "method": str(request["method"]),
                "url": str(request["url"]),
            }
            entry["response"] = {
                "status": int(response["status"]),
                "len": body_binding["wire_len"],
                "sha1": body_binding["wire_sha1"],
                "saved_len": body_binding["saved_len"],
                "saved_sha1": body_binding["saved_sha1"],
                "truncated": body_binding["truncated"],
                "wire_verified": body_binding["wire_verified"],
            }
            entry["saved_body"] = body_ref
        receipts.append(entry)
    if not any(item["path"].endswith(".replay.json") for item in receipts):
        raise ValueError("target accept-candidate requires at least one replay sidecar")
    return receipts


def _record_review_disposition_locked(run_dir: Path, *, target: str, reviewer: str,
                                      disposition: str, note: str) -> dict:
    """Record one returned Reviewer lane against a frozen merge draft."""
    disposition = str(disposition or "").strip().lower()
    if disposition not in REVIEW_DISPOSITIONS:
        raise ValueError(
            "invalid review disposition; use one of " + ", ".join(sorted(REVIEW_DISPOSITIONS)))
    note = str(note or "").strip()
    if not note or len(note) > 2048 or any(ord(char) < 32 and char not in "\t\n" for char in note):
        raise ValueError("review disposition requires a bounded non-empty note")
    if _runtime_receipts is None:
        raise ValueError("runtime_receipts unavailable; cannot prove Reviewer return")
    data = load_assignments(run_dir)
    target_row = next((item for item in data.get("assignments", [])
                       if isinstance(item, dict) and item.get("agent") == target), None)
    reviewer_row = next((item for item in data.get("assignments", [])
                         if isinstance(item, dict) and item.get("agent") == reviewer), None)
    if not target_row or not reviewer_row:
        raise ValueError("target and reviewer assignments must both exist")
    plan_digest = str(target_row.get("plan_digest") or "")
    if _plan_cycle_is_ended(run_dir, plan_digest):
        raise ValueError("ended plan cycle is immutable; commit a new plan instead")
    if str(reviewer_row.get("role") or "") != "review":
        raise ValueError("reviewer assignment must use role=review")
    if target not in [str(item) for item in reviewer_row.get("reviews_assignments", [])]:
        raise ValueError("Reviewer lane is not bound to the target assignment")
    if str(target_row.get("plan_digest") or "") != str(reviewer_row.get("plan_digest") or ""):
        raise ValueError("Reviewer and target must share one exact plan digest")
    attempts = [
        item for item in _runtime_receipts.agent_attempts(run_dir)
        if item.get("assignment") == reviewer and item.get("state") == "returned"
        and item.get("lane_id") == reviewer_row.get("lane_id")
        and item.get("plan_digest") == reviewer_row.get("plan_digest")
    ]
    if len(attempts) != 1:
        raise ValueError("review disposition requires one exact returned Reviewer attempt")
    attempt = attempts[0]
    if not str(attempt.get("agent_id") or "") \
            or not str(attempt.get("tool_use_id") or ""):
        raise ValueError("review disposition requires a concrete Reviewer Agent/tool identity")
    draft_path = _runtime_receipts.merge_draft_path(run_dir, target)
    try:
        draft = json.loads(draft_path.read_text(encoding="utf-8", errors="strict"))
    except Exception as exc:
        raise ValueError("target merge draft is missing or unreadable") from exc
    if draft.get("schema") != "xunji.merge-draft.v1" \
            or draft.get("assignment") != target \
            or draft.get("plan_digest") != target_row.get("plan_digest"):
        raise ValueError("target merge draft binding mismatch")
    result = draft.get("result") if isinstance(draft.get("result"), dict) else {}
    result_path = Path(str(result.get("path") or ""))
    try:
        current_digest = hashlib.sha256(result_path.read_bytes()).hexdigest()
    except Exception as exc:
        raise ValueError("frozen Agent result is unavailable") from exc
    if not current_digest or current_digest != draft.get("result_digest"):
        raise ValueError("Agent result changed after return; re-freeze and re-review")
    if _run_model is None:
        raise ValueError("run_model unavailable; cannot validate Reviewer frozen result")
    projection = _run_model.plan_cycle_projection(run_dir)
    reviewer_state = next((
        item for item in projection.get("lane_states", [])
        if isinstance(item, dict)
        and item.get("lane_id") == reviewer_row.get("lane_id")
        and item.get("assignment") == reviewer
    ), {})
    target_state = next((
        item for item in projection.get("lane_states", [])
        if isinstance(item, dict)
        and item.get("lane_id") == target_row.get("lane_id")
        and item.get("assignment") == target
    ), {})
    reviewer_result_digest = str(reviewer_state.get("result_digest") or "")
    if reviewer_state.get("runtime_state") != "returned" \
            or not re.fullmatch(r"[0-9a-f]{64}", reviewer_result_digest) \
            or target_state.get("result_digest") != current_digest:
        raise ValueError("Reviewer/target immutable runtime result binding is invalid")
    reviewer_draft_path = _runtime_receipts.merge_draft_path(run_dir, reviewer)
    try:
        reviewer_draft = json.loads(reviewer_draft_path.read_text(
            encoding="utf-8", errors="strict"))
    except Exception as exc:
        raise ValueError("Reviewer merge draft is missing or unreadable") from exc
    artifact_validation = _validated_review_artifacts(
        run_dir,
        target_row=target_row,
        target_text=_frozen_result_text(draft, label="target"),
        reviewer_text=_frozen_result_text(reviewer_draft, label="Reviewer"),
        disposition=disposition,
    )
    stamp = _now_iso()
    receipt = {
        "schema": "xunji.review-disposition.v1",
        "target_assignment": target,
        "target_result_digest": current_digest,
        "reviewer_assignment": reviewer,
        "reviewer_agent_id": str(attempt.get("agent_id") or ""),
        "reviewer_tool_use_id": str(attempt.get("tool_use_id") or ""),
        "reviewer_result_digest": reviewer_result_digest,
        "plan_digest": str(target_row.get("plan_digest") or ""),
        "target_lane_id": str(target_row.get("lane_id") or ""),
        "reviewer_lane_id": str(reviewer_row.get("lane_id") or ""),
        "disposition": disposition,
        "note": note,
        "artifact_validation": artifact_validation,
        "recorded_at": stamp,
    }
    receipt["receipt_hash"] = hashlib.sha256(json.dumps(
        receipt, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
    ).encode("utf-8")).hexdigest()
    # Every accepted enum is a completed review of these exact frozen bytes.
    # needs-control/retry describe the evidence-supported Root disposition and
    # successor work; leaving the review itself action_required deadlocks the
    # plan because neither finish nor the dependent lane can then proceed.
    draft["review_status"] = "complete"
    draft["review_receipt"] = receipt
    draft["per_asset_outcomes"] = [
        {"asset": str(item.get("asset") or ""), "disposition": disposition}
        for item in draft.get("per_asset_outcomes", []) if isinstance(item, dict)
    ]
    draft["updated_at"] = stamp
    _atomic_write(draft_path, json.dumps(draft, ensure_ascii=False, indent=2) + "\n")
    reviewer_row["status"] = "reviewed"
    reviewer_row["updated_at"] = stamp
    reviewer_row["finished_at"] = stamp
    reviewer_row["last_note"] = (
        f"Review: {target} Disposition: {disposition} Result: {current_digest[:12]} Note: {note}"
    )
    _patch_agent_file_lifecycle(
        _agent_file_from_rec(reviewer_row), status="reviewed",
        note=reviewer_row["last_note"], stamp=stamp,
    )
    _validate_assignments_data(data, parent_run=run_dir.name)
    _atomic_write(_assignments_path(run_dir), json.dumps(data, ensure_ascii=False, indent=2) + "\n")
    return receipt


def update_agent_lifecycle(run_dir: Path, agent: str, *, status: str, note: str = "",
                           terminal: bool = False, amend: bool = False) -> dict:
    with _assignment_mutation_lock(run_dir):
        return _update_agent_lifecycle_locked(
            run_dir, agent, status=status, note=note,
            terminal=terminal, amend=amend,
        )


def _update_agent_lifecycle_locked(run_dir: Path, agent: str, *, status: str,
                                   note: str = "", terminal: bool = False,
                                   amend: bool = False) -> dict:
    data = load_assignments(run_dir)
    status_norm = _normalized_agent_status(status)
    allowed = TERMINAL_AGENT_STATUSES if terminal else NONTERMINAL_AGENT_STATUSES
    if status_norm not in allowed:
        raise ValueError(f"invalid agent status {status!r}; use one of {sorted(allowed)}")
    if terminal and status_norm not in TERMINAL_AGENT_STATUSES:
        raise ValueError(f"finish requires terminal status; use one of {sorted(TERMINAL_AGENT_STATUSES)}")
    if amend and not terminal:
        raise ValueError("disposition amendment is only valid for finish")
    stamp = _now_iso()
    for rec in data.get("assignments", []):
        if not isinstance(rec, dict):
            continue
        if str(rec.get("agent") or "") != agent:
            continue
        previous_status = _normalized_agent_status(str(rec.get("status") or ""))
        adjudicated = {"merged", "reviewed", "blocked", "failed", "abandoned"}
        plan_bound = bool(
            str(rec.get("plan_digest") or "") and str(rec.get("lane_id") or ""))
        if _plan_cycle_is_ended(run_dir, str(rec.get("plan_digest") or "")):
            if (
                terminal and not amend and status_norm == previous_status
                and note.strip() == str(rec.get("last_note") or "").strip()
            ):
                return rec
            raise ValueError("ended plan cycle is immutable; commit a new plan instead")
        if not terminal and plan_bound and status_norm in {"running", "working"}:
            attempts = rec.get("attempts") if isinstance(rec.get("attempts"), list) else []
            current_attempt = str(rec.get("current_attempt") or "")
            runtime_attempt = next((
                item for item in attempts
                if isinstance(item, dict)
                and str(item.get("attempt_id") or "") == current_attempt
                and item.get("state") == "running"
                and str(item.get("agent_id") or "")
                == str(rec.get("runtime_agent_id") or "")
            ), None)
            if runtime_attempt is None:
                raise ValueError(
                    f"plan-bound heartbeat {status_norm} requires an authentic running attempt")
        if terminal and status_norm == "reviewed":
            raise ValueError(
                "reviewed is written only by review-disposition after a returned Reviewer attempt")
        if terminal and plan_bound and str(rec.get("role") or "") == "review":
            raise ValueError(
                "plan-bound Reviewer lifecycle is written only by review-disposition")
        if terminal and plan_bound and status_norm == "done":
            raise ValueError(
                "plan-bound done is projected only from the authentic Agent return; "
                "Root must record a reviewed disposition")
        if not terminal and previous_status in TERMINAL_AGENT_STATUSES:
            raise ValueError(
                f"{agent} already has terminal status {previous_status}; "
                "heartbeat cannot reopen a returned attempt")
        if terminal and status_norm in adjudicated:
            if _runtime_receipts is None:
                raise ValueError(
                    "runtime_receipts unavailable; cannot validate terminal disposition")
            note_issues = _runtime_receipts.disposition_note_issues(run_dir, status_norm, note)
            if note_issues:
                raise ValueError("invalid disposition note; " + "; ".join(note_issues))
        if terminal and previous_status in adjudicated:
            if not amend:
                if status_norm == previous_status and note.strip() == str(rec.get("last_note") or "").strip():
                    return rec
                raise ValueError(
                    f"{agent} already has terminal disposition {previous_status}; "
                    "use finish --amend to preserve an audit trail")
            history = rec.setdefault("disposition_history", [])
            history.append({
                "status": previous_status,
                "note": str(rec.get("last_note") or ""),
                "updated_at": str(rec.get("updated_at") or ""),
                "finished_at": str(rec.get("finished_at") or ""),
                "amended_at": stamp,
            })
        elif amend:
            raise ValueError(f"{agent} has no terminal disposition to amend")
        merge_validation = None
        review_receipt: dict = {}
        if terminal and plan_bound and status_norm in {
                "merged", "blocked", "failed", "abandoned"}:
            review_receipt = _current_review_receipt(run_dir, rec)
            if not review_receipt:
                raise ValueError(
                    f"{status_norm} requires a current returned Reviewer disposition")
        if terminal and status_norm == "merged":
            if str(rec.get("plan_digest") or "") and str(rec.get("lane_id") or ""):
                draft = json.loads(_runtime_receipts.merge_draft_path(
                    run_dir, str(rec.get("agent") or ""),
                ).read_text(encoding="utf-8", errors="strict"))
                disposition = str((draft.get("review_receipt") or {}).get("disposition") or "")
                if disposition != "accept-candidate":
                    raise ValueError(
                        "merged requires reviewer disposition=accept-candidate, got "
                        f"{disposition or '(missing)'}")
            merge_validation = _validate_asset_merge(run_dir, rec)
        rec["status"] = status_norm
        rec["updated_at"] = stamp
        rec["last_seen_at"] = stamp
        if note.strip():
            rec["last_note"] = note.strip()
        rec["heartbeat_count"] = int(rec.get("heartbeat_count") or 0) + 1
        if terminal:
            rec["finished_at"] = stamp
            if review_receipt:
                rec["root_disposition_review_receipt_hash"] = str(
                    review_receipt.get("receipt_hash") or "")
                rec["root_disposition_at"] = stamp
            if status_norm == "merged":
                rec["coverage_merge_satisfied"] = True
                rec["coverage_merge"] = merge_validation
            else:
                rec["coverage_merge_satisfied"] = False
        # Plan-bound context/scaffold bytes stay immutable through Stop. Runtime
        # progress lives in assignments/receipts; mutating the displayed
        # scaffold mid-attempt would invalidate its instruction bundle.
        if not plan_bound or terminal:
            _patch_agent_file_lifecycle(
                _agent_file_from_rec(rec), status=status_norm,
                note=note, stamp=stamp)
        _validate_assignments_data(data, parent_run=run_dir.name)
        _atomic_write(_assignments_path(run_dir), json.dumps(data, ensure_ascii=False, indent=2) + "\n")
        return rec
    raise KeyError(f"agent not found in state/assignments.json: {agent}")


def agent_lifecycle_issues(run_dir: Path, *, closure: bool = False,
                           stale_after_seconds: int = STALE_HEARTBEAT_SECONDS) -> list[dict]:
    issues: list[dict] = []
    now = time.time()
    for row in agent_status_rows(run_dir):
        agent = str(row.get("agent") or "?")
        status = _normalized_agent_status(str(row.get("status") or row.get("file_status") or ""))
        last_seen = str(row.get("last_seen_at") or row.get("updated_at") or row.get("created_at") or "")
        age = None
        parsed = _parse_iso(last_seen)
        if parsed is not None:
            age = max(0, int(now - parsed))
        if status in NONTERMINAL_AGENT_STATUSES:
            plan_bound = bool(
                str(row.get("plan_digest") or "")
                and str(row.get("lane_id") or "")
            )
            if plan_bound:
                disposition_guidance = (
                    "plan-bound 状态只能由真实 launch/return 投影推进；不得由 Root "
                    "finish 为 done。等待匹配 SubagentStop 投影 done 后，执行 Reviewer "
                    "disposition 与 Root settlement；未启动且 turn/inputs stale 才走 "
                    "cancel-unlaunched。"
                )
            else:
                disposition_guidance = (
                    "收口前必须 finish 为 done/merged/blocked/failed/abandoned 并写明处置。"
                )
            issues.append({
                "severity": "error" if closure else "warn",
                "agent": agent,
                "kind": "agent-not-terminal",
                "detail": (
                    f"{agent} status={status} front={row.get('front')} last_seen={last_seen or '(missing)'} "
                    f"note={row.get('last_note') or '-'} —— {disposition_guidance}"),
            })
        if status in {"running", "working", "starting"} and age is not None and age > stale_after_seconds:
            issues.append({
                "severity": "error" if closure else "warn",
                "agent": agent,
                "kind": "agent-heartbeat-stale",
                "detail": (
                    f"{agent} status={status} 已 {age // 60} 分钟无 heartbeat —— Root 需要确认 Agent "
                    "是否仍在跑、卡住、或已有结果待合并。"),
            })
        attempts = row.get("attempts") if isinstance(row.get("attempts"), list) else []
        returned = any(
            isinstance(item, dict) and item.get("state") == "returned"
            for item in attempts
        )
        if returned and str(row.get("role") or "") != "review" \
                and str(row.get("plan_digest") or "") \
                and str(row.get("lane_id") or "") \
                and not _review_receipt_complete(run_dir, row):
            issues.append({
                "severity": "error" if closure else "warn",
                "agent": agent,
                "kind": "agent-review-pending",
                "detail": (
                    f"{agent} has a returned runtime attempt but no bound Reviewer "
                    "disposition for its frozen merge draft."),
            })
        if status == "done":
            issues.append({
                "severity": "error" if closure else "warn",
                "agent": agent,
                "kind": "agent-done-unadjudicated",
                "detail": f"{agent} returned but remains done; Root must merge/refute/block/fail it.",
            })
    return issues


def _agent_blocks(run_dir: Path) -> list[dict]:
    out = []
    for p in sorted(agents_dir(run_dir).glob("A-*.md")) if agents_dir(run_dir).exists() else []:
        text = p.read_text(encoding="utf-8", errors="replace")
        role = _field(text, "Role")
        front = _field(text, "Assigned front")
        out.append({
            "agent": p.stem,
            "role": role,
            "front": front,
            "status": (_field(text, "Status") or "?").lower(),
            "supports": _field(text, "Supports"),
            "refutes": _field(text, "Refutes"),
            "confidence": _field(text, "Confidence"),
            "control": _field(text, "Control"),
            "replicated": _field(text, "Replicated"),
            "artifacts": _field(text, "Artifacts"),
            "parse_error": not (role and front),
            "text": text,
        })
    return out


def agent_discipline_issues(run_dir: Path) -> list[dict]:
    """Check Agent Board artifacts without judging exploitability.

    This is the mechanical counterpart to the Agent templates: subagents may produce
    observations/candidates/refutations, but not canonical findings or closure; active
    candidate work must leave pointers the Synthesizer can audit and replay.
    """
    issues: list[dict] = []
    assigned = {str(a.get("agent")): a for a in load_assignments(run_dir).get("assignments", [])
                if isinstance(a, dict)}
    files = sorted(agents_dir(run_dir).glob("A-*.md")) if agents_dir(run_dir).exists() else []
    seen = set()
    for a in _agent_blocks(run_dir):
        agent = str(a["agent"])
        seen.add(agent)
        text = str(a.get("text") or "")
        role = _role(str(a.get("role") or ""))
        if a.get("parse_error"):
            issues.append({"severity": "error", "agent": agent, "kind": "parse-error",
                           "detail": f"{agent} missing Role or Assigned front."})
        rec = assigned.get(agent)
        if rec:
            if str(rec.get("front") or "").strip() != str(a.get("front") or "").strip():
                issues.append({"severity": "error", "agent": agent, "kind": "assignment-mismatch",
                               "detail": f"{agent} front differs from state/assignments.json."})
            if _role(str(rec.get("role") or "")) != role:
                issues.append({"severity": "error", "agent": agent, "kind": "role-mismatch",
                               "detail": f"{agent} role differs from state/assignments.json."})
        else:
            issues.append({"severity": "warn", "agent": agent, "kind": "unassigned-agent",
                           "detail": f"{agent} exists but is not recorded in state/assignments.json."})

        instruction_scaffold = "<!-- xunji.agent-scaffold.v1 -->" in text
        expected_sections = (
            "Frozen Lane Boundary", "Operator Profile / RDT Controls",
            "Asset Outcomes", "Final Return",
        ) if instruction_scaffold else ("Prelude", "Recurrent Loop", "Coda")
        missing_sections = [name for name in expected_sections
                            if not re.search(rf"(?im)^##\s+{re.escape(name)}\b", text)]
        if missing_sections:
            issues.append({"severity": "warn", "agent": agent, "kind": "missing-loop-section",
                           "detail": f"{agent} missing section(s): {', '.join(missing_sections)}."})
        rdt_declared = (
            re.search(r"(?im)personalized-rdt", text)
            or _has_field_label(text, "Loop budget")
            or _has_field_label(text, "Reasoning-loop budget")
            or _has_field_label(text, "Operator profile")
            or re.search(r"(?im)^##\s+Operator Profile / RDT Controls\b", text)
        )
        loop = re.search(r"(?ims)^##\s+Recurrent Loop\b.*?(?=^##\s+|\Z)", text)
        if rdt_declared and not (
                _has_field_label(text, "Loop budget")
                or _has_field_label(text, "Reasoning-loop budget")):
            issues.append({"severity": "warn", "agent": agent, "kind": "missing-loop-budget",
                           "detail": f"{agent} declares personalized RDT but has no Loop budget."})
        if rdt_declared and not (_has_field_label(text, "Operator profile")
                                 or re.search(r"(?im)^##\s+Operator Profile / RDT Controls\b", text)):
            issues.append({"severity": "warn", "agent": agent, "kind": "missing-operator-profile",
                           "detail": f"{agent} declares personalized RDT but has no operator profile/RDT control block."})
        if rdt_declared and loop:
            steps = re.findall(r"(?ims)^###\s+Step\s+\d+\b.*?(?=^###\s+Step\s+\d+\b|^##\s+|\Z)", loop.group(0))
            if not steps:
                issues.append({"severity": "warn", "agent": agent, "kind": "missing-rdt-step",
                               "detail": f"{agent} Recurrent Loop has no `### Step N` block."})
            for idx, step in enumerate(steps[:1], start=1):
                required_step_fields = [
                    "Original front",
                    "Known E-ids",
                    "Constraint / ruled-out shape",
                    "Hypothesis",
                    "Expected signal",
                    "Last action",
                    "Last outcome",
                    "Action / analysis",
                    "Observation",
                    "Control / alternative",
                    "Drop condition",
                    "Next hypothesis",
                ]
                missing_step_fields = [field for field in required_step_fields if not _has_field_label(step, field)]
                if missing_step_fields:
                    issues.append({"severity": "warn", "agent": agent, "kind": "missing-rdt-step-field",
                                   "detail": f"{agent} Step {idx} missing RDT field(s): {', '.join(missing_step_fields)}."})
        safety = re.search(
            r"(?ims)^##\s+(?:Safety / Guard[^\n]*|Frozen Lane Boundary)\n.*?"
            r"(?=^##\s+|\Z)", text)
        safety_text = safety.group(0).lower() if safety else ""
        safety_markers = (
            (("guard",), "missing-guard-reminder"),
            (("request budget", "budget"), "missing-budget-reminder"),
            (("untrusted", "target content is data"), "missing-untrusted-reminder"),
            (("outbound",), "missing-outbound-privacy-reminder"),
            (("cleanup",), "missing-cleanup-reminder"),
        )
        for alternatives, kind in safety_markers:
            token = alternatives[0]
            if not any(marker in safety_text for marker in alternatives):
                issues.append({"severity": "warn", "agent": agent, "kind": kind,
                               "detail": f"{agent} Safety / Guard section lacks `{token}`."})
        if instruction_scaffold:
            provenance = {
                "Context SHA-256": r"[0-9a-f]{64}",
                "Role contract": r"xunji\.agent-role-contract\.v1",
                "Composed role SHA-256": r"[0-9a-f]{64}",
                "Live Agent type": r"xunji-(?:hunter|reviewer)",
                "Live Agent SHA-256": r"[0-9a-f]{64}",
            }
            invalid = [
                field for field, pattern in provenance.items()
                if not re.fullmatch(pattern, _field(text, field))
            ]
            if invalid:
                issues.append({
                    "severity": "warn", "agent": agent,
                    "kind": "missing-instruction-provenance",
                    "detail": f"{agent} has invalid instruction provenance: {', '.join(invalid)}.",
                })

        bad_name = TARGET_ARTIFACT_OPSEC_RE.search(text)
        if bad_name:
            issues.append({"severity": "warn", "agent": agent, "kind": "target-artifact-opsec-name",
                           "detail": f"{agent} mentions target-side artifact name `{bad_name.group(0)}`; use neutral tmp/diag/proof-YYYYMMDD-<hex> naming, not project labels."})

        if _target_cleanup_requires_yes(text):
            issues.append({"severity": "warn", "agent": agent, "kind": "target-cleanup-requires-yes",
                           "detail": f"{agent} mentions target-side cleanup; cleanup/delete/overwrite requires explicit operator yes before execution."})

        maturity = _field(text, "Maturity").lower()
        if role != "synthesizer" and maturity == "finding":
            issues.append({"severity": "error", "agent": agent, "kind": "agent-promoted-finding",
                           "detail": f"{agent} sets Maturity: finding; only Synthesizer may promote."})
        if role != "synthesizer" and re.search(r"(?im)^\s*[-*]?\s*(Report conclusion|Closure)\s*[:：]\s*\S", text):
            issues.append({"severity": "error", "agent": agent, "kind": "agent-wrote-final-conclusion",
                           "detail": f"{agent} wrote report conclusion/closure; only Synthesizer may decide."})

        for nh in _new_threat_hypotheses(text, agent=agent, default_front=str(a.get("front") or "")):
            label = f"{agent}:{nh['nh_id']}"
            if _blankish(nh.get("asset_role_input")):
                issues.append({"severity": "warn", "agent": agent, "kind": "threat-missing-scope",
                               "detail": f"{label} has Threat hypothesis but no Asset/role/input."})
            if _blankish(nh.get("linked")) and _blankish(nh.get("next_action")):
                issues.append({"severity": "warn", "agent": agent, "kind": "threat-unanchored",
                               "detail": f"{label} has no Linked IS/C/E and no Next action for Root."})
            if role != "synthesizer" and str(nh.get("status") or "").strip().lower() in {"finding", "confirmed"}:
                issues.append({"severity": "error", "agent": agent, "kind": "agent-promoted-threat",
                               "detail": f"{label} sets threat Status={nh.get('status')}; Agents must leave it candidate/open."})

        confidence_raw = _field(text, "Confidence")
        cm = re.search(r"[01]\.\d+", confidence_raw)
        confidence = float(cm.group(0)) if cm else None
        has_claim = not (_blankish(a.get("supports")) and _blankish(a.get("refutes")))
        if a.get("status") in {"done", "merged"} and has_claim:
            if _blankish(a.get("artifacts")):
                issues.append({"severity": "warn", "agent": agent, "kind": "missing-artifact-pointer",
                               "detail": f"{agent} is done with claim material but no Artifacts pointer."})
            if confidence is not None and confidence >= 0.8:
                if _blankish(a.get("control")) and _blankish(a.get("replicated")):
                    issues.append({"severity": "error", "agent": agent, "kind": "agent-missing-control",
                                   "detail": f"{agent} proposes confidence {confidence} without Control/Replicated."})
    missing_files = sorted(set(assigned) - seen)
    for agent in missing_files:
        issues.append({"severity": "error", "agent": agent, "kind": "missing-agent-file",
                       "detail": f"{agent} exists in state/assignments.json but has no agents/A-*.md file."})
    if not files and assigned:
        issues.append({"severity": "error", "agent": "-", "kind": "missing-agents-dir",
                       "detail": "state/assignments.json has assignments but agents/A-*.md files are missing."})

    # 约束刷新检查: agent 完成时是否有未读取的新约束
    constraints_path = run_dir / "constraints.md"
    if constraints_path.exists():
        try:
            constraints_mtime = constraints_path.stat().st_mtime
        except OSError:
            constraints_mtime = None

        if constraints_mtime is not None:
            for f in sorted(agents_dir(run_dir).glob("A-*.md")) if agents_dir(run_dir).exists() else []:
                text = f.read_text(encoding="utf-8", errors="replace")
                status = (_field(text, "Status") or "?").lower()
                if status not in {"done", "merged"}:
                    continue
                try:
                    agent_mtime = f.stat().st_mtime
                except OSError:
                    continue
                # agent 的 mtime 早于 constraints.md 的 mtime → agent 完成时可能有未读取的新约束
                if agent_mtime < constraints_mtime:
                    # 检查 agent 的 Coda 中是否含 New Constraints 块（说明 agent 已刷新）
                    if not re.search(r"(?im)^##\s+New Constraints\b", text):
                        issues.append({
                            "severity": "warn",
                            "agent": f.stem,
                            "kind": "stale-constraint-state",
                            "detail": (
                                f"{f.stem} (status={status}) 完成于 constraints.md 最后修改之前, "
                                "且 Coda 中无 `## New Constraints` 块 —— agent 可能错过了新约束。"
                                "如果该 agent 负责的 front 在 constraints.md 中有新条目, 需重新评估。"
                            ),
                        })
    return issues


def _strict_json_object(pairs: list[tuple[str, object]]) -> dict:
    value: dict[str, object] = {}
    for key, item in pairs:
        if key in value:
            raise ValueError(f"CONFLICT_PROJECTION_DUPLICATE_KEY:{key}")
        value[key] = item
    return value


def _valid_conflict_timestamp(value: object) -> bool:
    if not isinstance(value, str):
        return False
    try:
        parsed = datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ")
    except ValueError:
        return False
    return parsed.strftime("%Y-%m-%dT%H:%M:%SZ") == value


def _conflict_projection_timestamp() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def _load_conflict_projection(path: Path) -> dict | None:
    try:
        metadata = path.lstat()
    except FileNotFoundError:
        return None
    except OSError as exc:
        print(
            f"[agent-board] WARN rebuilding unreadable conflicts projection: "
            f"{type(exc).__name__}",
            file=sys.stderr,
        )
        return None
    if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISREG(metadata.st_mode):
        print(
            "[agent-board] WARN rebuilding non-regular conflicts projection",
            file=sys.stderr,
        )
        return None
    try:
        value = json.loads(
            path.read_text(encoding="utf-8", errors="strict"),
            object_pairs_hook=_strict_json_object,
        )
    except Exception as exc:
        print(
            f"[agent-board] WARN rebuilding invalid conflicts projection: "
            f"{type(exc).__name__}",
            file=sys.stderr,
        )
        return None
    if not isinstance(value, dict):
        print(
            "[agent-board] WARN rebuilding non-object conflicts projection",
            file=sys.stderr,
        )
        return None
    schema = value.get("schema")
    if isinstance(schema, int) and not isinstance(schema, bool) and schema != 1:
        raise ValueError(f"CONFLICT_PROJECTION_SCHEMA_UNSUPPORTED:{schema}")
    expected = {"schema", "generated_at", "conflict_types", "conflicts"}
    extra = sorted(set(value) - expected)
    if extra:
        raise ValueError(
            "CONFLICT_PROJECTION_UNKNOWN_FIELDS:" + ",".join(extra))
    if set(value) != expected or schema != 1 or isinstance(schema, bool) \
            or not _valid_conflict_timestamp(value.get("generated_at")) \
            or not isinstance(value.get("conflict_types"), list) \
            or not all(isinstance(item, str) for item in value["conflict_types"]) \
            or not isinstance(value.get("conflicts"), list) \
            or not all(isinstance(item, dict) for item in value["conflicts"]):
        print(
            "[agent-board] WARN rebuilding malformed conflicts projection",
            file=sys.stderr,
        )
        return None
    return value


def build_conflicts(run_dir: Path) -> dict:
    """Linearly rebuild the derived conflict projection from Agent state."""
    with _assignment_mutation_lock(run_dir):
        return _build_conflicts_locked(run_dir)


def _build_conflicts_locked(run_dir: Path) -> dict:
    agents = _agent_blocks(run_dir)
    conflicts = []
    by_front: dict[str, list[dict]] = {}
    for a in agents:
        if a.get("front"):
            by_front.setdefault(str(a["front"]), []).append(a)
    for front, rows in by_front.items():
        supporters = [a for a in rows if not _blankish(a.get("supports"))]
        refuters = [a for a in rows if not _blankish(a.get("refutes"))]
        if supporters and refuters:
            conflicts.append({
                "type": "direct contradiction",
                "front": front,
                "status": "unresolved",
                "supports": [a["agent"] for a in supporters],
                "refutes": [a["agent"] for a in refuters],
                "required_agent": "verification-agent",
            })
        for polarity, field, group in (("supports", "supports", supporters), ("refutes", "refutes", refuters)):
            claims: dict[str, list[dict]] = {}
            for a in group:
                key = re.sub(r"\W+", " ", (a.get(field) or "").lower()).strip()
                if key:
                    claims.setdefault(key, []).append(a)
            for key, same in claims.items():
                certs = {a.get("confidence") for a in same if not _blankish(a.get("confidence"))}
                arts = {a.get("artifacts") for a in same if not _blankish(a.get("artifacts"))}
                if len(same) > 1:
                    conflicts.append({
                        "type": "duplicate",
                        "front": front,
                        "status": "unresolved",
                        "polarity": polarity,
                        "claim": key,
                        "agents": [a["agent"] for a in same],
                        "required_agent": "root-synthesizer",
                    })
                if len(same) > 1 and len(certs) > 1:
                    conflicts.append({
                        "type": "confidence mismatch",
                        "front": front,
                        "status": "unresolved",
                        "polarity": polarity,
                        "claim": key,
                        "agents": [a["agent"] for a in same],
                        "confidences": sorted(certs),
                        "required_agent": "verification-agent",
                    })
                if len(same) > 1 and len(arts) > 1:
                    conflicts.append({
                        "type": "artifact mismatch",
                        "front": front,
                        "status": "unresolved",
                        "polarity": polarity,
                        "claim": key,
                        "agents": [a["agent"] for a in same],
                        "required_agent": "verification-agent",
                    })
    conflict_types = [
        "direct contradiction",
        "duplicate",
        "confidence mismatch",
        "artifact mismatch",
        "scope mismatch",
    ]
    semantic = {
        "schema": 1,
        "conflict_types": conflict_types,
        "conflicts": conflicts,
    }
    path = state_dir(run_dir) / "conflicts.json"
    existing = _load_conflict_projection(path)
    if existing is not None \
            and all(existing.get(key) == value for key, value in semantic.items()):
        return existing
    data = {
        "schema": semantic["schema"],
        "generated_at": _conflict_projection_timestamp(),
        "conflict_types": semantic["conflict_types"],
        "conflicts": semantic["conflicts"],
    }
    _atomic_write(path, json.dumps(data, ensure_ascii=False, indent=2) + "\n")
    return data


def synthesize_draft(run_dir: Path) -> dict:
    assignments = load_assignments(run_dir).get("assignments", [])
    agents = _agent_blocks(run_dir)
    conflicts = build_conflicts(run_dir).get("conflicts", [])
    done = [a for a in agents if a.get("status") in {"done", "merged"}]
    candidates = [a for a in done if not _blankish(a.get("supports"))]
    needs_control = [a["agent"] for a in candidates
                     if _blankish(a.get("control")) and _blankish(a.get("replicated"))]
    draft = {
        "schema": 1,
        "generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "canonical": "markdown remains source of truth",
        "summary": {
            "assignments": len(assignments),
            "agents": len(agents),
            "done_agents": len(done),
            "candidate_supports": len(candidates),
            "unresolved_conflicts": len([c for c in conflicts if c.get("status") == "unresolved"]),
        },
        "promotion_notes": [
            "Subagent candidates are not findings.",
            "Root Synthesizer must verify control/replication and artifacts before evidence promotion.",
        ],
        "needs_control": needs_control,
        "conflicts_to_verify": [c for c in conflicts if c.get("status") == "unresolved"],
    }
    _atomic_write(state_dir(run_dir) / "synthesis.json", json.dumps(draft, ensure_ascii=False, indent=2) + "\n")
    return draft


def print_list(run_dir: Path) -> int:
    rows = scan(run_dir)
    if not rows:
        print("[workers] 无 worker 文件 —— 串行单 driver 模式。用 `workers.py suggest` 判断是否值得 fan-out。")
        return 0
    print(f"[workers] {len(rows)} 个 worker:")
    for w in rows:
        flag = "  done 未 merge -> 过证据门并入 evidence.md" if w["status"] == "done" else ""
        print(f"  {w['file']:10} front={w['front']:10} status={w['status']:8} candidates={w['candidates']}{flag}")
    um = unmerged(run_dir)
    if um:
        print(f"\n[workers] {len(um)} 个 worker 已 done 但未 merge —— driver 须逐个过【证据门】"
              "(>=0.8 要 Control/复现, 否则降级)、分配 E-id、去重、更新 frontier, 再标 merged。")
    return 0


def print_suggest(run_dir: Path, limit: int | None = None) -> int:
    rows = suggest(run_dir, limit=limit)
    if not rows:
        print("[workers suggest] 无可建议 front: 缺 frontier.md 或没有 open/probing/deferred front。")
        return 0
    notes = _breadth_signals(rows)
    planned = lane_suggestions(run_dir, limit=(limit if limit is not None else 2))
    ready = [row for row in planned if not row["work_plan_lane"]["dependencies"]]
    mode = "PARALLEL_AGENTS" if len(ready) >= 2 else "SERIAL_AGENT"
    print(f"[workers suggest] generated topology={mode} ({'; '.join(notes)})")
    print("  note: advisory only; Root must commit xunji.work-plan.v1 before assignment.")
    print("  driver still weighs live rate limits, shared auth/WAF barriers, and prior worker hit rate.")
    for r in rows:
        rs = "; ".join(r["reasons"][:3]) or "no positive signal"
        cs = (" | cautions: " + "; ".join(r["cautions"][:3])) if r["cautions"] else ""
        assets = ", ".join(r["assets"][:3]) or "?"
        print(f"  {r['front']:6} score={r['score']:>2} assets={assets:24} status={r['status']:12} "
              f"barrier={r['barrier']:18} {rs}{cs}")
    if planned:
        print("  effect-typed lane opportunities:")
        for row in planned:
            lane = row["work_plan_lane"]
            print(
                f"    {lane['id']} role={lane['role']} effect={lane['effect']} "
                f"deps={','.join(lane['dependencies']) or '-'} "
                f"request_cost={lane['request_cost']} information_gain="
                f"{lane['expected_information_gain']} merge_cost={lane['merge_cost']}"
            )
    asset_rows = asset_suggestions(run_dir)
    if asset_rows:
        print("  asset suggestions (advisory; create/front-map before assignment):")
        for item in asset_rows[:8]:
            print(f"    {item['asset']} -> role={item['role']} ({', '.join(item['reasons'])})")
    return 0


def print_plan(run_dir: Path, limit: int, *, stage: str | None = None) -> int:
    rows = [r for r in suggest(run_dir) if r["score"] >= 3]
    if not rows:
        print(
            "[workers plan] NO_STRONG_CANDIDATE: do not commit or copy a "
            "documentation example; update canonical frontier/coverage mapping, "
            "rerun the state pass, then rerun this planner."
        )
        return 1
    selected = rows[:min(limit, 2)]
    selected_stage = str(stage or "S2").upper()
    lanes = lane_suggestions(run_dir, limit=limit, stage=selected_stage)
    notes = _breadth_signals(rows)
    print(f"[workers plan] generated seed only ({'; '.join(notes)})")
    if _target_egress_denied_for_plan(run_dir):
        print(
            "[workers plan] operator effect: TARGET_EGRESS_DENIED; target lanes "
            "and target-dependent verification are omitted; the offline "
            "Hunter/Reviewer pair is the complete local suffix."
        )
    if len(selected) < len(rows):
        requested = max(0, limit)
        reason = (
            "generated-seed cap=2; the model proposal may instead express up to 16 lanes"
            if requested > 2 else f"--limit={limit}"
        )
        print(f"Selected {len(selected)} of {len(rows)} strong candidate(s) due to {reason}.")
    proposal_info = write_plan_proposal(
        run_dir, [row["work_plan_lane"] for row in lanes], stage=stage)
    print(
        f"MODEL_PROPOSAL: {display_path(proposal_info['path'])} is a derived, "
        "non-authorizing seed bound to this turn/input. Root may replace, omit, "
        "or add typed execution/Reviewer pairs (maximum 16 lanes) before "
        "workers.py commit-proposal."
    )
    missing = "objective, delegation_reason, and exit_gate"
    if stage is None:
        missing = "macro_stage, " + missing
    print(
        f"Root must fill {missing}; keep basis unchanged. Lanes are strategy, "
        "not an indivisible planner mandate."
    )
    print("Only the validated transaction commit authorizes delegation; this seed creates no facts, Agents, or receipts.\n")
    for row in lanes:
        lane = row["work_plan_lane"]
        print(f"## {lane['id']} -> {lane['front']} ({lane['role']})")
        print(f"- effect_class: {row['effect_class']}")
        print(f"- dependencies: {', '.join(lane['dependencies']) or 'none'}")
        print(f"- assets: {', '.join(lane['assets']) or 'none'}")
        print(f"- request_cost / budget: {lane['request_cost']} / {lane['request_budget']}")
        print(f"- expected_information_gain: {lane['expected_information_gain']}")
        print(f"- merge_cost: {lane['merge_cost']}")
        print()
    ready = [row for row in lanes if not row["work_plan_lane"]["dependencies"]]
    width = scheduler_width(
        lanes, runtime_slots=max(1, len(ready)), request_budget=sum(
            row["work_plan_lane"]["request_budget"] for row in ready),
        merge_capacity=sum(row["work_plan_lane"]["merge_cost"] for row in ready),
        model_egress_budget=sum(
            row["work_plan_lane"]["request_budget"] for row in ready
            if row["work_plan_lane"]["effect"] == "model_egress"),
    )
    recommended_mode = "PARALLEL_AGENTS" if width >= 2 else "SERIAL_AGENT"
    print(
        f"Topology advisory: ready={len(ready)} capacity-free_parallel_width={width} "
        f"topology_mode={recommended_mode}; actual delegate width still depends "
        "on runtime/request/egress/merge capacity."
    )
    return 0


def _remaining_replan_lanes(
    run_dir: Path, lanes: list[dict], *, replan_reason: str,
) -> tuple[list[dict], list[str]]:
    """Carry exact completed lane prefixes across the verified plan lineage.

    Canonical evidence normally changes after Root settles a lane, so a later
    generated replan must not turn the same deterministic lane id into a fresh
    assignment.  The immediate prior plan is insufficient because a replan may
    already have removed a settled prefix.  Only transcript/review/Root-complete
    lanes from the validated transaction archive chain with the same frozen work
    identity are inherited.  Their dependency-ordered descendants are inherited
    only when every predecessor was inherited too.
    """
    copied = json.loads(json.dumps(lanes))
    if not str(replan_reason or "").strip():
        return copied, []
    generated = {
        str(item.get("id") or ""): item for item in copied
        if isinstance(item, dict)
    }

    def identity(lane: dict) -> dict:
        return {
            key: lane.get(key)
            for key in (
                "id", "role", "front", "effect", "assets", "dependencies",
                "expected_evidence", "stop_condition", "request_cost",
                "request_budget", "merge_cost", "atomic",
            )
        }

    # Index only candidate ids/identities that this proposal could inherit.
    # Each projection still revalidates assignments, runtime receipts, frozen
    # result, Reviewer disposition, and Root settlement for that exact plan.
    completed_identities: dict[str, list[dict]] = {}
    for historical in _work_plan.transaction_plan_lineage(run_dir):
        relevant = [
            item for item in historical.get("lanes", [])
            if isinstance(item, dict)
            and str(item.get("id") or "") in generated
            and identity(item) == identity(
                generated[str(item.get("id") or "")])
        ]
        if not relevant:
            continue
        projection = _run_model.plan_cycle_projection(
            run_dir, plan=historical)
        states = {
            str(item.get("lane_id") or ""): item
            for item in projection.get("lane_states", [])
            if isinstance(item, dict)
        }
        for old in relevant:
            lane_id = str(old.get("id") or "")
            if states.get(lane_id, {}).get("complete") is True:
                completed_identities.setdefault(lane_id, []).append(
                    identity(old))

    inherited: set[str] = set()
    pending = [item for item in copied if isinstance(item, dict)]
    while pending:
        progressed = False
        for new in list(pending):
            lane_id = str(new.get("id") or "")
            dependencies = [str(item) for item in new.get("dependencies", [])]
            if identity(new) not in completed_identities.get(lane_id, []) \
                    or any(item not in inherited for item in dependencies):
                continue
            inherited.add(lane_id)
            pending.remove(new)
            progressed = True
        if not progressed:
            break

    remaining = [item for item in copied if str(item.get("id") or "") not in inherited]
    for lane in remaining:
        lane["dependencies"] = [
            str(item) for item in lane.get("dependencies", [])
            if str(item) not in inherited
        ]
    if inherited and not remaining:
        raise ValueError(
            "WORK_PLAN_DUPLICATE_SETTLED_WORK: every proposed lane has an "
            "identity-equal transcript/Reviewer/Root-complete predecessor in "
            "the verified transaction lineage; choose a genuinely new lane "
            "identity/mechanism/precondition, or proceed to closure assessment")
    return remaining, sorted(inherited)


def print_commit_plan(
    run_dir: Path, *, stage: str, objective: str, mode: str, reason: str,
    exit_gate: str, limit: int, replan_reason: str = "",
) -> int:
    """Compatibility path: commit the conservative generated seed directly."""
    lanes = [
        row["work_plan_lane"]
        for row in lane_suggestions(run_dir, limit=limit, stage=stage)
    ]
    if not lanes:
        print(
            "[workers commit-plan] NO_STRONG_CANDIDATE: update canonical "
            "frontier/coverage mapping and rerun the state pass.",
            file=sys.stderr,
        )
        return 1
    try:
        lanes, inherited = _remaining_replan_lanes(
            run_dir, lanes, replan_reason=replan_reason)
        plan = _work_plan.commit_plan(
            run_dir,
            macro_stage=stage,
            objective=objective,
            mode=mode,
            reason=reason,
            exit_gate=exit_gate,
            lanes=lanes,
            replan_reason=replan_reason,
        )
    except Exception as exc:
        print(f"[workers commit-plan] ERROR {exc}", file=sys.stderr)
        return 1
    _print_plan_commit_receipt(
        plan, inherited=inherited, source="generated-seed")
    return 0


def _print_plan_commit_receipt(
    plan: dict, *, inherited: list[str], source: str,
    proposal_sha256: str = "",
) -> None:
    ready = [item for item in plan.get("lanes") or []
             if isinstance(item, dict) and not item.get("dependencies")]
    topology_mode = (
        "PARALLEL_AGENTS" if len(ready) >= 2
        and all(lanes_can_overlap(left, right)
                for index, left in enumerate(ready)
                for right in ready[index + 1:])
        else "SERIAL_AGENT"
    )
    receipt = {
        "schema": "xunji.planner-commit.v2",
        "source": source,
        "plan_id": plan.get("plan_id"),
        "plan_digest": plan.get("plan_digest"),
        "macro_stage": plan.get("macro_stage"),
        "objective": plan.get("objective"),
        "execution_mode": plan.get("execution_mode"),
        "topology_mode": topology_mode,
        "ready_lane_count": len(ready),
        "mode_matches_topology": plan.get("execution_mode") == topology_mode,
        "lane_count": len(plan.get("lanes") or []),
        "lanes": [str(item.get("id") or "") for item in plan.get("lanes") or []],
        "fronts": sorted({str(item.get("front") or "")
                          for item in plan.get("lanes") or []
                          if isinstance(item, dict) and item.get("front")}),
        "inherited_completed_lanes": inherited,
        "next_action": "delegate dependency-ready lanes from this committed plan",
    }
    if proposal_sha256:
        receipt["proposal_sha256"] = proposal_sha256
    print(json.dumps(receipt, ensure_ascii=False, indent=2))


def print_commit_proposal(run_dir: Path) -> int:
    """Commit the exact current model-authored DAG through the plan owner."""
    try:
        proposal, proposal_sha256 = load_plan_proposal(run_dir)
        normalized_lanes = [
            _work_plan.normalize_lane(item) for item in proposal["lanes"]]
        _validate_proposal_assignment_scope(run_dir, normalized_lanes)
        lanes, inherited = _remaining_replan_lanes(
            run_dir,
            normalized_lanes,
            replan_reason=proposal["replan_reason"],
        )
        plan = _work_plan.commit_plan(
            run_dir,
            macro_stage=proposal["macro_stage"],
            objective=proposal["objective"],
            mode=proposal["execution_mode"],
            reason=proposal["delegation_reason"],
            exit_gate=proposal["exit_gate"],
            lanes=lanes,
            replan_reason=proposal["replan_reason"],
        )
    except Exception as exc:
        print(f"[workers commit-proposal] ERROR {exc}", file=sys.stderr)
        return 1
    _print_plan_commit_receipt(
        plan,
        inherited=inherited,
        source="model-proposal",
        proposal_sha256=proposal_sha256,
    )
    return 0


def print_assign(run_dir: Path, role: str, front: str, scope: str = "",
                 assets: list[str] | None = None, lane_id: str = "") -> int:
    try:
        rec = create_agent_assignment(
            run_dir, role=role, front=front, scope=scope, assets=assets,
            lane_id=lane_id)
    except Exception as exc:
        print(f"[agent-board assign] ERROR: {exc}", file=sys.stderr)
        return 1
    print(f"[agent-board] assigned {rec['agent']} role={rec['role']} front={rec['front']} "
          f"lane={rec.get('lane_id') or '-'} effect={rec.get('effect') or '-'} "
          f"assets={','.join(rec.get('assets') or []) or '-'} "
          f"loop_budget={rec.get('loop_budget')} "
          f"tool_call_limit={rec.get('tool_call_limit')}")
    print(f"  agent:  {rec['agent_file']}")
    print(f"  context:{rec['context']}")
    print(f"  state:  {display_path(_assignments_path(run_dir))}")
    return 0


def print_cancel_unlaunched(run_dir: Path, assignment: str, reason: str) -> int:
    try:
        receipt = cancel_unlaunched_assignment(
            run_dir, assignment, reason=reason)
    except Exception as exc:
        print(f"[workers cancel-unlaunched] ERROR {exc}", file=sys.stderr)
        return 1
    print(json.dumps(receipt, ensure_ascii=False, indent=2, sort_keys=True))
    print(
        "NEXT_OWNER_ACTION: cancellation settled assignment debt only; keep "
        f"front {receipt.get('front') or '(unknown)'} open. It is not a result, "
        "review, evidence item, refutation, completed lane/cycle, or authority "
        "to close the front. Re-read canonical status and replan only after all "
        "assignment debt is clear."
    )
    return 0


def _plan_for_delegation(run_dir: Path, contract: dict) -> tuple[dict, bool]:
    """Return a fresh plan, or the exact stale plan for settlement only."""
    try:
        plan = _work_plan.current_plan(run_dir, contract)
    except _work_plan.PlanError as exc:
        if str(exc) not in {"WORK_PLAN_INPUTS_STALE", "WORK_PLAN_TURN_STALE"}:
            raise
        plan = _transaction_bound_plan_for_settlement(run_dir)
        return plan, True
    if _agent_settlement is not None and _agent_settlement.cancellation_barrier(
            run_dir, plan_digest=str(plan.get("plan_digest") or "")):
        return plan, True
    return plan, False


def _stale_settlement_reviewer_ready(
    run_dir: Path, plan: dict, lane: dict,
) -> bool:
    """Admit only the unique Reviewer for one real returned/failed execution.

    This is deliberately narrower than normal dependency readiness.  It cannot
    launch a new execution lane, a Reviewer-of-Reviewer chain, or a second
    Reviewer for the same target after canonical inputs have made the plan
    stale.
    """
    return bool(
        _agent_settlement is not None
        and _agent_settlement.stale_settlement_reviewer_ready(
            run_dir, plan, lane)
    )


def _replayable_existing_assignment(
    run_dir: Path, plan: dict, lane: dict, *, settlement_only: bool,
) -> dict:
    """Return one durable no-attempt assignment whose launch may be replayed."""
    lane_id = str(lane.get("id") or "")
    projection = _run_model.plan_cycle_projection(run_dir, plan=plan) \
        if _run_model is not None else {}
    states = [
        item for item in projection.get("lane_states", [])
        if isinstance(item, dict) and str(item.get("lane_id") or "") == lane_id
    ]
    if len(states) != 1 \
            or str(states[0].get("runtime_state") or "") != "no-attempt":
        raise ValueError(
            f"WORK_PLAN_ASSIGNMENT_REPLAY_STATE_INVALID:{lane_id}")
    assignment = str(states[0].get("assignment") or "")
    if not re.fullmatch(r"A-[A-Za-z0-9._-]+", assignment):
        raise ValueError(
            f"WORK_PLAN_ASSIGNMENT_REPLAY_IDENTITY_INVALID:{lane_id}")
    rows = [
        item for item in load_assignments(run_dir).get("assignments", [])
        if isinstance(item, dict)
        and str(item.get("agent") or "") == assignment
        and str(item.get("plan_digest") or "") == str(plan.get("plan_digest") or "")
        and str(item.get("lane_id") or "") == lane_id
    ]
    if len(rows) != 1:
        raise ValueError(
            f"WORK_PLAN_ASSIGNMENT_REPLAY_ROW_AMBIGUOUS:{assignment}")
    row = rows[0]
    if _role(str(row.get("role") or "")) \
            != _role(str(lane.get("role") or "")) \
            or str(row.get("effect") or "") != str(lane.get("effect") or "") \
            or str(row.get("front") or "").upper() \
                != str(lane.get("front") or "").upper() \
            or [_normalize_asset(item) for item in row.get("assets", [])] \
                != [_normalize_asset(item) for item in lane.get("assets", [])] \
            or _normalized_agent_status(str(row.get("status") or "")) != "assigned" \
            or row.get("attempts") != [] \
            or any(row.get(field) not in (None, "", [], {}) for field in (
                "current_attempt", "runtime_agent_id", "root_disposition_at",
                "root_disposition_review_receipt_hash",
            )):
        raise ValueError(
            f"WORK_PLAN_ASSIGNMENT_REPLAY_ROW_INVALID:{assignment}")
    if settlement_only and not _stale_settlement_reviewer_ready(
            run_dir, plan, lane):
        raise ValueError(
            f"WORK_PLAN_ASSIGNMENT_REPLAY_STALE_ROLE_FORBIDDEN:{assignment}")

    if _role(str(lane.get("role") or "")) == "review":
        dependencies = [str(item) for item in lane.get("dependencies", [])]
        target_states = [
            item for item in projection.get("lane_states", [])
            if isinstance(item, dict)
            and str(item.get("lane_id") or "") in dependencies
            and str(item.get("runtime_state") or "") in {"returned", "failed"}
        ]
        if len(dependencies) != 1 or len(target_states) != 1 \
                or row.get("reviews_assignments") \
                    != [str(target_states[0].get("assignment") or "")] \
                or str(row.get("review_result_digest") or "") \
                    != str(target_states[0].get("result_digest") or "") \
                or not re.fullmatch(
                    r"[0-9a-f]{64}",
                    str(row.get("review_result_digest") or "")):
            raise ValueError(
                f"WORK_PLAN_ASSIGNMENT_REPLAY_REVIEW_BINDING_INVALID:{assignment}")
    elif row.get("review_result_digest"):
        raise ValueError(
            f"WORK_PLAN_ASSIGNMENT_REPLAY_EXECUTION_BINDING_INVALID:{assignment}")

    _assert_no_assignment_runtime_records(
        run_dir, assignment,
        plan_digest=str(plan.get("plan_digest") or ""),
        lane_id=lane_id,
        allow_typed_interrupted_reviewer_start=(
            _role(str(lane.get("role") or "")) == "review"),
    )
    try:
        _instruction_bundle.verify_assignment_bundle(
            run_dir, row, root=ROOT)
    except Exception as exc:
        raise ValueError(
            f"WORK_PLAN_ASSIGNMENT_REPLAY_BUNDLE_INVALID:{assignment}") from exc
    prompt = _runtime_receipts.assignment_launch_prompt(row) \
        if _runtime_receipts is not None else ""
    subagent_type = _runtime_receipts.assignment_subagent_type(row) \
        if _runtime_receipts is not None else ""
    if not prompt or not subagent_type:
        raise ValueError(
            f"WORK_PLAN_ASSIGNMENT_REPLAY_CONTRACT_INVALID:{assignment}")
    return {
        "assignment": assignment,
        "lane_id": lane_id,
        "role": str(row.get("role") or ""),
        "effect": str(row.get("effect") or ""),
        "tool_call_limit": int(row.get("tool_call_limit") or 0),
        "context": str(row.get("context") or ""),
        "subagent_type": subagent_type,
        "launch_prompt": prompt,
        "replayed_existing": True,
    }


def delegate_ready_lanes(
    run_dir: Path,
    *,
    runtime_slots: int = 2,
    request_budget: int = 10,
    model_egress_budget: int = 1,
    merge_capacity: int = 100,
    limit: int = 2,
    tool_call_limit: int = DEFAULT_AGENT_TOOL_CALL_LIMIT,
    fault=None,
) -> dict:
    """Create exact assignments for the next ready plan wave.

    The Claude primary driver still performs the actual Agent tool calls.  This
    function transactionally narrows the hand-off to plan-bound assignments,
    exact context packs, and launch prompts; the hooks then create launch/return
    receipts from the real runtime events.
    """
    if fault is not None and not callable(fault):
        raise TypeError("delegate fault injector must be callable")
    if _runtime_receipts is not None:
        # This takes the runtime lock before the assignment lock and only
        # supersedes a Reviewer Start when parent+child Claude transcripts prove
        # that the Start hook was cancelled before any model output.  The
        # ordinary exact assigned/no-attempt replay below then reuses the
        # persisted Reviewer contract.
        _runtime_receipts.recover_interrupted_reviewer_starts(run_dir)
    with _assignment_mutation_lock(run_dir):
        _recover_prepared_delegate_transaction(run_dir)
        _require_no_prepared_cancellation(run_dir)
        return _delegate_ready_lanes_locked(
            run_dir,
            runtime_slots=runtime_slots,
            request_budget=request_budget,
            model_egress_budget=model_egress_budget,
            merge_capacity=merge_capacity,
            limit=limit,
            tool_call_limit=tool_call_limit,
            fault=fault,
        )


def _delegate_ready_lanes_locked(
    run_dir: Path,
    *,
    runtime_slots: int,
    request_budget: int,
    model_egress_budget: int,
    merge_capacity: int,
    limit: int,
    tool_call_limit: int,
    fault=None,
) -> dict:
    if _work_plan is None:
        raise ValueError("work_plan unavailable; delegation fails closed")
    contract = _work_plan._load_turn_contract(run_dir)
    plan, settlement_only = _plan_for_delegation(run_dir, contract)
    mode = str(plan.get("execution_mode") or "")
    if mode == "ROOT_DIRECT":
        raise ValueError("ROOT_DIRECT plan has no Agent delegation wave")
    projection = _run_model.plan_cycle_projection(run_dir, plan=plan) \
        if _run_model is not None else {}
    projected_states = {
        str(item.get("lane_id") or ""): str(item.get("runtime_state") or "")
        for item in projection.get("lane_states", [])
        if isinstance(item, dict) and str(item.get("lane_id") or "")
    }
    ready: list[dict] = []
    for lane in plan.get("lanes", []):
        if not isinstance(lane, dict):
            continue
        if str(lane.get("effect") or "") in {"control", "repo_mutation"}:
            continue
        lane_id = str(lane.get("id") or "")
        runtime_state = _work_plan.lane_runtime_state(
            run_dir, plan, lane_id)
        if settlement_only \
                and not _stale_settlement_reviewer_ready(run_dir, plan, lane):
            continue
        existing: dict | None = None
        if projected_states.get(lane_id) == "no-attempt":
            existing = _replayable_existing_assignment(
                run_dir, plan, lane, settlement_only=settlement_only)
            if existing.get("tool_call_limit") != tool_call_limit:
                raise ValueError(
                    "WORK_PLAN_ASSIGNMENT_REPLAY_TOOL_CALL_LIMIT_MISMATCH:"
                    f"{existing.get('assignment')}")
        elif runtime_state != "unassigned":
            continue
        if not _work_plan.lane_dependencies_satisfied(run_dir, plan, lane):
            continue
        ready.append({
            "work_plan_lane": {**lane, "dependencies": []},
            **({"existing_assignment": existing} if existing else {}),
        })
    if not ready:
        if settlement_only:
            raise ValueError(
                "WORK_PLAN_STALE_SETTLEMENT_ONLY: no returned/failed execution "
                "has an unassigned unique Reviewer")
        raise ValueError("no unassigned lane has satisfied runtime dependencies")

    running = 0
    if _runtime_receipts is not None:
        running = sum(
            1 for item in _runtime_receipts.agent_attempts(run_dir)
            if item.get("state") == "running")
    available_slots = max(0, runtime_slots - running)
    if mode == "SERIAL_AGENT":
        available_slots = min(available_slots, 1)
    selected = scheduler_selection(
        ready,
        runtime_slots=min(max(0, limit), available_slots),
        request_budget=request_budget,
        model_egress_budget=model_egress_budget,
        merge_capacity=merge_capacity,
    )
    if not selected:
        raise ValueError(_capacity_diagnostic(
            ready,
            available_slots=min(max(0, limit), available_slots),
            request_budget=request_budget,
            model_egress_budget=model_egress_budget,
            merge_capacity=merge_capacity,
        ))

    replayed = [
        item["existing_assignment"] for item in selected
        if isinstance(item.get("existing_assignment"), dict)
    ]
    if replayed:
        # Never mix a durable contract replay with new assignment mutation in
        # one batch.  Replaying first is deterministic and leaves the later
        # ready suffix for the next ordinary delegate call.
        return {
            "schema": "xunji.delegate-batch.v1",
            "plan_id": plan["plan_id"],
            "plan_digest": plan["plan_digest"],
            "transaction_id": "",
            "execution_mode": mode,
            "input_freshness": (
                "stale-settlement-only" if settlement_only else "current"),
            "runtime_slots": runtime_slots,
            "running_before": running,
            "request_budget": request_budget,
            "model_egress_budget": model_egress_budget,
            "merge_capacity": merge_capacity,
            "tool_call_limit": tool_call_limit,
            "assignments": replayed,
            "replayed_existing": len(replayed),
            "next_action": (
                "Claude primary driver calls Agent once per assignment using "
                "both exact subagent_type and exact launch_prompt"),
        }

    selected_lane_ids = [
        str(item["work_plan_lane"].get("id") or "") for item in selected
    ]
    transaction = _prepare_delegate_transaction(
        run_dir, plan, selected_lane_ids)
    created: list[dict] = []
    try:
        if fault is not None:
            fault("after_prepared")
        for item in selected:
            lane = item["work_plan_lane"]

            def record_artifact_intent(agent_id: str, agent_path: Path,
                                       ctx_path: Path) -> None:
                nonlocal transaction
                agent_name = agent_path.name
                context_name = ctx_path.name
                if (agent_name in transaction["agent_files_before"]
                        or context_name in transaction["context_files_before"]):
                    raise ValueError(
                        "delegate transaction refuses to overwrite a prior artifact")
                if (agent_id in transaction["created_assignments"]
                        or agent_name in transaction["created_agent_files"]
                        or context_name in transaction["created_context_files"]):
                    raise ValueError("delegate transaction artifact intent is duplicated")
                transaction["created_assignments"].append(agent_id)
                transaction["created_agent_files"].append(agent_name)
                transaction["created_context_files"].append(context_name)
                transaction = _write_delegate_transaction(run_dir, transaction)

            rec = _create_agent_assignment_locked(
                run_dir,
                role=str(lane.get("role") or ""),
                front=str(lane.get("front") or ""),
                assets=[str(asset) for asset in lane.get("assets", [])],
                lane_id=str(lane.get("id") or ""),
                tool_call_limit=tool_call_limit,
                before_artifact_write=record_artifact_intent,
                stale_settlement_plan=plan if settlement_only else None,
            )
            if _runtime_receipts is None \
                    or not hasattr(_runtime_receipts, "assignment_launch_prompt"):
                raise ValueError(
                    "runtime exact launch-prompt builder unavailable; delegation fails closed")
            prompt = _runtime_receipts.assignment_launch_prompt(rec)
            subagent_type = _runtime_receipts.assignment_subagent_type(rec) \
                if hasattr(_runtime_receipts, "assignment_subagent_type") else ""
            if not prompt or not subagent_type:
                raise ValueError(
                    "plan-bound assignment cannot produce an exact Agent launch contract")
            created.append({
                "assignment": rec["agent"],
                "lane_id": rec["lane_id"],
                "role": rec["role"],
                "effect": rec["effect"],
                "tool_call_limit": rec["tool_call_limit"],
                "context": rec["context"],
                "subagent_type": subagent_type,
                "launch_prompt": prompt,
            })
            if fault is not None:
                fault(f"after_assignment_{len(created)}")
        refreshed_plan, refreshed_settlement_only = _plan_for_delegation(
            run_dir, _work_plan._load_turn_contract(run_dir))
        if refreshed_plan != plan \
                or refreshed_settlement_only is not settlement_only:
            raise ValueError(
                "WORK_PLAN_DELEGATE_BASIS_CHANGED_BEFORE_COMMIT")
        transaction["status"] = "committed"
        transaction["committed_at"] = datetime.now(timezone.utc).isoformat(
            timespec="milliseconds").replace("+00:00", "Z")
        transaction = _write_delegate_transaction(run_dir, transaction)
    except Exception as exc:
        try:
            _recover_prepared_delegate_transaction(
                run_dir, reason=f"delegate exception: {type(exc).__name__}")
        except Exception as rollback_exc:
            raise RuntimeError(
                "delegation failed and its prepared transaction could not roll back"
            ) from rollback_exc
        raise
    return {
        "schema": "xunji.delegate-batch.v1",
        "plan_id": plan["plan_id"],
        "plan_digest": plan["plan_digest"],
        "transaction_id": transaction["transaction_id"],
        "execution_mode": mode,
        "input_freshness": (
            "stale-settlement-only" if settlement_only else "current"),
        "runtime_slots": runtime_slots,
        "running_before": running,
        "request_budget": request_budget,
        "model_egress_budget": model_egress_budget,
        "merge_capacity": merge_capacity,
        "tool_call_limit": tool_call_limit,
        "assignments": created,
        "next_action": (
            "Claude primary driver calls Agent once per assignment using both "
            "exact subagent_type and exact launch_prompt"),
    }


def print_delegate(
    run_dir: Path,
    *, runtime_slots: int, request_budget: int,
    model_egress_budget: int, merge_capacity: int, limit: int,
    tool_call_limit: int,
) -> int:
    try:
        batch = delegate_ready_lanes(
            run_dir,
            runtime_slots=runtime_slots,
            request_budget=request_budget,
            model_egress_budget=model_egress_budget,
            merge_capacity=merge_capacity,
            limit=limit,
            tool_call_limit=tool_call_limit,
        )
    except (ValueError, _work_plan.PlanError if _work_plan is not None else ValueError) as exc:
        print(f"[workers delegate] ERROR {exc}", file=sys.stderr)
        return 1
    print(json.dumps(batch, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


def print_status(run_dir: Path, *, show_all: bool = False) -> int:
    rows = agent_status_rows(run_dir)
    if not rows:
        print("[agent-board] no assignments yet. Load xunji-agent-board, commit the current typed plan, then delegate ready lanes.")
        return 0
    counts = collections.Counter(
        str(row.get("status") or "?") for row in rows)
    active = [
        row for row in rows
        if str(row.get("status") or "?") in NONTERMINAL_AGENT_STATUSES
        or row.get("parse_error")
    ]
    if show_all:
        shown = rows
    else:
        recent_terminal = [
            row for row in rows
            if row not in active
        ][-8:]
        shown = [*active, *recent_terminal]
    count_text = ", ".join(
        f"{key}={counts[key]}" for key in sorted(counts))
    print(
        f"[agent-board] total={len(rows)} active/debt={len(active)} "
        f"states: {count_text}")
    if not show_all and len(shown) < len(rows):
        print(
            f"  bounded view: {len(rows) - len(shown)} older terminal row(s) "
            "omitted; use `workers.py status runs/<dir> --all` only for an "
            "explicit full-ledger audit.")
    for r in shown:
        warn = " parse=ERROR" if r.get("parse_error") else ""
        last = r.get("last_seen_at") or r.get("updated_at") or "-"
        print(f"  {r['agent']:22} role={r['role']:12} front={r['front']:8} "
              f"state={r.get('status','?'):9} last={last} file={r.get('file_status','?')}{warn}")
    return 0


def print_lifecycle_check(run_dir: Path, *, closure: bool = False) -> int:
    issues = agent_lifecycle_issues(run_dir, closure=closure)
    if not issues:
        print("[agent-board lifecycle] clean: all assigned Agents are terminal or no assignments exist.")
        return 0
    print(f"[agent-board lifecycle] {len(issues)} issue(s)")
    rc = 0
    for i in issues:
        sev = i["severity"].upper()
        if i["severity"] == "error":
            rc = 1
        print(f"  {sev:5} {i['kind']:24} {i['detail']}")
    return rc


def print_heartbeat(run_dir: Path, agent: str, status: str, note: str) -> int:
    try:
        rec = update_agent_lifecycle(run_dir, agent, status=status, note=note, terminal=False)
    except Exception as e:
        print(f"[agent-board heartbeat] ERROR: {e}", file=sys.stderr)
        return 1
    print(f"[agent-board heartbeat] {rec['agent']} status={rec['status']} "
          f"last_seen={rec.get('last_seen_at')} note={rec.get('last_note', '-')}")
    return 0


def _plan_continuation_notice(run_dir: Path) -> str:
    """Return one driver action when the committed plan still has lane debt."""
    if _run_model is None:
        return ""
    projection_error = run_dir / "state" / "runtime_projection_error.json"
    if projection_error.exists() and _runtime_receipts is not None:
        recovery = _runtime_receipts.foreign_lifecycle_recovery_status(run_dir)
        candidates = recovery.get("candidate_event_seqs", []) \
            if isinstance(recovery, dict) else []
        if candidates:
            seqs = ",".join(str(item) for item in candidates)
            return (
                "NEXT_OWNER_ACTION: runtime projection is blocked by proven "
                f"non-Xunji lifecycle receipts at event seq {seqs}; run exact typed "
                f"`python3 tools/runtime_receipts.py {display_path(run_dir)} "
                "--quarantine-unowned-lifecycle`, then repeat workers.py status. "
                "This appends supersession receipts and preserves runtime_events.jsonl."
            )
        return (
            "NEXT_OWNER_ACTION: runtime projection has unresolved lifecycle debt; "
            f"run exact `python3 tools/runtime_receipts.py {display_path(run_dir)} "
            "--reproject` and inspect the retained diagnostic. Do not cancel, "
            "replan, delete, or rewrite runtime receipts around an unresolved error."
        )
    try:
        projection = _run_model.plan_cycle_projection(run_dir)
    except Exception:
        return ""
    pending = [
        f"{item.get('lane_id')}:{item.get('runtime_state') or 'unassigned'}"
        for item in projection.get("lane_states", [])
        if isinstance(item, dict) and item.get("complete") is not True
        and str(item.get("lane_id") or "")
    ]
    if not pending:
        return ""
    freshness = "current"
    if _work_plan is not None:
        try:
            contract = _work_plan._load_turn_contract(run_dir)
            _work_plan.current_plan(run_dir, contract)
        except Exception as exc:
            if str(exc) in {"WORK_PLAN_INPUTS_STALE", "WORK_PLAN_TURN_STALE"}:
                freshness = "stale"
            else:
                freshness = "invalid"
    if freshness == "stale":
        if _agent_settlement is None:
            return (
                "NEXT_OWNER_ACTION: stale assignment settlement owner is "
                "unavailable; keep the front open and repair that local "
                "dependency before cancel, delegate, replan, or cycle_end."
            )
        recovery = _agent_settlement.stale_recovery_action(
            run_dir, _transaction_bound_plan_for_settlement(run_dir),
            projection=projection,
        )
        action = str(recovery.get("action") or "")
        items = recovery.get("items") \
            if isinstance(recovery.get("items"), list) else []
        first = items[0] if items and isinstance(items[0], dict) else {}
        assignment = str(first.get("assignment") or "")
        if action == _agent_settlement.RECOVERY_REPLAY_ASSIGNED_REVIEWER:
            return (
                "NEXT_OWNER_ACTION: committed plan is stale and its unique "
                f"Reviewer {assignment} is assigned with no authentic launch; "
                f"rerun `python3 tools/workers.py delegate {display_path(run_dir)} "
                "--limit 1` to replay the exact durable launch contract, then "
                "settle review and Root disposition. Do not cancel the Reviewer "
                "or rebuild its prompt."
            )
        if action == _agent_settlement.RECOVERY_CREATE_REVIEWER:
            return (
                "NEXT_OWNER_ACTION: committed plan is stale but retains exact "
                "settlement identity for a returned/failed execution; run the "
                "same documented workers.py delegate checkpoint to create only "
                "its unique digest-bound Reviewer, settle it, then replan. Do "
                "not relaunch the old execution lane."
            )
        if action == _agent_settlement.RECOVERY_CANCEL_UNLAUNCHED_EXECUTION \
                and assignment:
            return (
                "NEXT_OWNER_ACTION: committed plan is stale and non-Reviewer "
                f"assignment {assignment} has no authentic launch attempt; run "
                f"the exact typed `workers.py cancel-unlaunched "
                f"{display_path(run_dir)} {assignment} --reason "
                "\"turn or canonical inputs changed before launch\"` settlement, "
                "then replan the still-open front."
            )
        if action == _agent_settlement.RECOVERY_WAIT_RUNNING:
            return (
                "NEXT_OWNER_ACTION: committed plan retains an authentic running "
                f"attempt; repeat `python3 tools/workers.py status "
                f"{display_path(run_dir)}` after its Stop receipt. Do not cancel "
                "or replan around it."
            )
        if action == _agent_settlement.RECOVERY_HARD_INVALID:
            return (
                "NEXT_OWNER_ACTION: stale Reviewer settlement cannot be safely "
                "classified; inspect the exact owner invariant and runtime "
                "projection. Do not cancel a Reviewer, delete ledger/journal "
                "files, or replan around assignment debt."
            )
        return (
            "NEXT_OWNER_ACTION: committed plan is turn/input stale after the "
            "settled prefix and has no unsettled assignment debt; keep its "
            "front open, rerun workers.py plan, then use the model proposal's "
            "replan_reason field plus workers.py commit-proposal so the owner "
            "inherits completed lanes and rebinds only the unfinished suffix."
        )
    if freshness == "invalid":
        return (
            "NEXT_OWNER_ACTION: committed plan provenance is invalid; keep its "
            "front open and repair the reported work-plan owner error before "
            "delegation, replan, or cycle_end."
        )
    return (
        "NEXT_OWNER_ACTION: committed plan still has lane debt "
        + ", ".join(pending)
        + "; keep its front open, do not call cycle_end, and run the same "
          "documented workers.py delegate checkpoint for the next ready lane."
    )


def print_finish(run_dir: Path, agent: str, status: str, note: str, amend: bool = False) -> int:
    try:
        rec = update_agent_lifecycle(
            run_dir, agent, status=status, note=note, terminal=True, amend=amend)
    except Exception as e:
        print(f"[agent-board finish] ERROR: {e}", file=sys.stderr)
        return 1
    print(f"[agent-board finish] {rec['agent']} terminal={rec['status']} "
          f"finished_at={rec.get('finished_at')} note={rec.get('last_note', '-')}")
    continuation = _plan_continuation_notice(run_dir)
    if continuation:
        print(continuation)
    return 0


def print_review_disposition(run_dir: Path, target: str, reviewer: str,
                             disposition: str, note: str) -> int:
    try:
        receipt = record_review_disposition(
            run_dir, target=target, reviewer=reviewer,
            disposition=disposition, note=note,
        )
    except Exception as exc:
        print(f"[agent-board review] ERROR: {exc}", file=sys.stderr)
        return 1
    print(
        f"[agent-board review] target={target} reviewer={reviewer} "
        f"disposition={receipt['disposition']} receipt={receipt['receipt_hash'][:12]}"
    )
    print(
        "NEXT_OWNER_ACTION: Root/Single Synthesizer must now settle "
        f"{target} with workers.py finish using the evidence-supported terminal "
        "status; do not promote canonical state or delegate a successor first."
    )
    replay_receipts = [
        item for item in receipt.get("artifact_validation", [])
        if isinstance(item, dict) and item.get("request") and item.get("response")
    ]
    for item in replay_receipts:
        request = item["request"]
        response = item["response"]
        print(
            "  VERIFIED_ARTIFACT "
            f"{request['method']} {request['url']} -> {response['status']} "
            f"wire_len={response['len']} saved_len={response.get('saved_len', response['len'])} "
            f"truncated={str(bool(response.get('truncated'))).lower()} "
            f"wire_verified={str(bool(response.get('wire_verified'))).lower()} "
            f"body={item['saved_body']} "
            f"replay={item['path']}"
        )
    return 0


def print_conflicts(run_dir: Path) -> int:
    data = build_conflicts(run_dir)
    conflicts = data.get("conflicts", [])
    parse_errors = [a for a in _agent_blocks(run_dir) if a.get("parse_error")]
    print(f"[agent-board] conflicts={len(conflicts)} -> {display_path(state_dir(run_dir) / 'conflicts.json')}")
    for a in parse_errors:
        print(f"  WARN parse-error: {a['agent']} missing Role or Assigned front")
    for c in conflicts:
        print(f"  {c.get('type')}: front={c.get('front')} status={c.get('status')} "
              f"agents={','.join(c.get('agents') or c.get('supports') or [])}")
    return 0


def print_synthesize(run_dir: Path) -> int:
    draft = synthesize_draft(run_dir)
    print(f"[agent-board] synthesis draft -> {display_path(state_dir(run_dir) / 'synthesis.json')}")
    print(json.dumps(draft["summary"], ensure_ascii=False, indent=2))
    if draft["conflicts_to_verify"]:
        print("  unresolved conflicts require verification-agent before promotion/closure.")
    if draft["needs_control"]:
        print("  candidates needing Control/Replicated: " + ", ".join(draft["needs_control"]))
    return 0


def print_agent_check(run_dir: Path) -> int:
    issues = agent_discipline_issues(run_dir)
    if not issues:
        print("[agent-board check] clean: no Agent discipline issues found.")
        return 0
    print(f"[agent-board check] {len(issues)} issue(s)")
    rc = 0
    for i in issues:
        sev = i["severity"].upper()
        if i["severity"] == "error":
            rc = 1
        print(f"  {sev:5} {i['kind']:28} {i['detail']}")
    return rc


def print_merge_check(run_dir: Path) -> int:
    issues = merge_check(run_dir) + agent_discipline_issues(run_dir)
    if not issues:
        print("[workers merge-check] clean: no worker candidate or Agent discipline issues found.")
        return 0
    print(f"[workers merge-check] {len(issues)} issue(s)")
    rc = 0
    for i in issues:
        sev = i["severity"].upper()
        if i["severity"] == "error":
            rc = 1
        print(f"  {sev:5} {i['kind']:22} {i['detail']}")
    return rc


def _new_threat_hypotheses(text: str, *, agent: str, default_front: str = "") -> list[dict]:
    body = _section_body(text, "New Threat Hypotheses")
    if not body:
        return []
    out: list[dict] = []
    for m in re.finditer(r"(?ms)^###[ \t]+(NH-\d+).*?(?=^###[ \t]+NH-\d+|\Z)", body):
        block = m.group(0)
        threat = _field(block, "Threat hypothesis") or _field(block, "Claim")
        if _blankish(threat):
            continue
        out.append({
            "agent": agent,
            "nh_id": m.group(1),
            "front": _field(block, "Front") or default_front,
            "threat_hypothesis": threat,
            "asset_role_input": _field(block, "Asset/role/input"),
            "expected_signal": _field(block, "Expected signal"),
            "refutation_control": _field(block, "Refutation/control"),
            "linked": _field(block, "Linked IS/C/E") or _field(block, "Linked evidence"),
            "status": _field(block, "Status") or "candidate",
            "next_action": _field(block, "Next action"),
            "block": block,
        })
    return out


def _collect_agent_threats(run_dir: Path) -> list[dict]:
    out: list[dict] = []
    for f in sorted(agents_dir(run_dir).glob("A-*.md")) if agents_dir(run_dir).exists() else []:
        text = f.read_text(encoding="utf-8", errors="replace")
        out.extend(_new_threat_hypotheses(
            text,
            agent=f.stem,
            default_front=_field(text, "Assigned front"),
        ))
    return out


def _normalize_threat_key(item: dict) -> tuple[str, str, str]:
    def norm(value: str) -> str:
        return re.sub(r"\s+", " ", str(value or "").strip().lower())
    return (
        norm(item.get("front", "")),
        norm(item.get("threat_hypothesis", "")),
        norm(item.get("asset_role_input", "")),
    )


def _existing_hypothesis_keys(text: str) -> tuple[set[tuple[str, str, str]], set[str]]:
    keys: set[tuple[str, str, str]] = set()
    ids: set[str] = set()
    for m in re.finditer(r"(?ms)^##[ \t]+(H-\d+).*?(?=^##[ \t]+H-\d+|\Z)", text):
        block = m.group(0)
        ids.add(m.group(1))
        keys.add(_normalize_threat_key({
            "front": _field(block, "Front"),
            "threat_hypothesis": _field(block, "Threat hypothesis") or _field(block, "Claim"),
            "asset_role_input": _field(block, "Asset/role/input"),
        }))
    return keys, ids


def merge_threats(run_dir: Path) -> dict:
    """Merge Agent `## New Threat Hypotheses` candidates into hypotheses.md.

    This is deliberately weaker than evidence promotion: it creates falsifiable
    Root-owned hypotheses, not findings, facts, or closure decisions.
    """
    suggestions = _collect_agent_threats(run_dir)
    if not suggestions:
        return {"new": 0, "duplicate": 0, "summary": "无 agents/*.md 中的 New Threat Hypotheses 块"}

    hyp_path = run_dir / "hypotheses.md"
    if hyp_path.exists():
        text = hyp_path.read_text(encoding="utf-8", errors="replace")
    else:
        text = "# Hypotheses\n"
    existing_keys, existing_ids = _existing_hypothesis_keys(text)

    next_n = 1
    while f"H-{next_n:03d}" in existing_ids:
        next_n += 1

    new_entries: list[dict] = []
    duplicate = 0
    for s in suggestions:
        key = _normalize_threat_key(s)
        if key in existing_keys or any(_normalize_threat_key(n) == key for n in new_entries):
            duplicate += 1
            continue
        s = dict(s)
        s["hid"] = f"H-{next_n:03d}"
        next_n += 1
        new_entries.append(s)
        existing_keys.add(key)

    if not new_entries:
        return {"new": 0, "duplicate": duplicate, "summary": f"无新威胁假设（{duplicate} 条重复跳过）"}

    if not text.endswith("\n"):
        text += "\n"
    chunks = [text.rstrip(), ""]
    for s in new_entries:
        chunks.extend([
            f"## {s['hid']}",
            "",
            f"- Claim: {s['threat_hypothesis']}",
            "- Status: open",
            f"- Source / trust: agent-candidate from {s['agent']}#{s['nh_id']}; untrusted until Root verifies",
            f"- Front: {s['front']}",
            f"- Threat hypothesis: {s['threat_hypothesis']}",
            f"- Asset/role/input: {s['asset_role_input']}",
            f"- Expected signal: {s['expected_signal']}",
            f"- Refutation/control: {s['refutation_control']}",
            f"- Why plausible: suggested by {s['agent']}#{s['nh_id']}",
            f"- What would confirm: {s['expected_signal']}",
            f"- What would reject: {s['refutation_control']}",
            "- Safety boundary: use guarded proof-level checks only",
            f"- Next safe verification: {s['next_action']}",
            f"- Linked IS/C/E: {s['linked']}",
            f"- Linked evidence: {s['linked']}",
            "",
        ])
    _atomic_write(hyp_path, "\n".join(chunks).rstrip() + "\n")
    return {
        "new": len(new_entries),
        "duplicate": duplicate,
        "summary": f"新增 {len(new_entries)} 条威胁假设, {duplicate} 条重复跳过",
    }


def print_merge_threats(run_dir: Path) -> int:
    result = merge_threats(run_dir)
    print(f"[workers merge-threats] {result['summary']}")
    if result["new"] > 0:
        print(f"  威胁假设已写入 {display_path(run_dir / 'hypotheses.md')}")
    return 0


def _normalize_input_shape(shape: str) -> str:
    """归一化 input shape: 小写、去首尾空白、压缩内部连续空白。"""
    if not shape:
        return ""
    return re.sub(r"\s+", " ", shape.strip().lower())


def _normalize_mechanism_class(mc: str) -> str:
    """将 mechanism class 标准化到 canonical name（复用 saturation 的映射表）。"""
    try:
        from saturation import _canonical as _sat_canonical
        return _sat_canonical(mc)
    except Exception:
        return mc.strip()


def merge_constraints(run_dir: Path) -> dict:
    """扫描 agents/A-*.md 中的 ## New Constraints 块, 去重后合并到 constraints.md。

    返回 {"new": N, "duplicate": D, "conflict": C, "summary": str}
    """
    agents_dir = run_dir / "agents"
    if not agents_dir.exists():
        return {"new": 0, "duplicate": 0, "conflict": 0, "summary": "无 agents/ 目录"}

    # 1. 扫描 agents/*.md 的 New Constraints 块
    suggestions: list[dict] = []
    for f in sorted(agents_dir.glob("A-*.md")):
        text = f.read_text(encoding="utf-8", errors="replace")
        m = re.search(r"(?ims)^##\s+New Constraints\s*$(.*?)(?=^##\s|\Z)", text)
        if not m:
            continue
        body = m.group(1)
        for nc_m in re.finditer(r"(?ms)^###[ \t]+(NC-\d+).*?(?=^###[ \t]+NC-\d+|\Z)", body):
            nc_block = nc_m.group(0)
            nc_id = nc_m.group(1)
            front_line = re.search(rf"(?im)^{HWS}*[-*]?{HWS}*Front{HWS}*[:：]{HWS}*([^\n]*)", nc_block)
            front = front_line.group(1).strip() if front_line else ""

            # 如果 NC 块没写 Front, 用 agent 的 Assigned front
            if not front:
                front_from_agent = re.search(
                    rf"(?im)^{HWS}*[-*]?{HWS}*Assigned front{HWS}*[:：]{HWS}*([^\n]*)", text)
                front = front_from_agent.group(1).strip() if front_from_agent else ""

            suggestions.append({
                "agent": f.stem,
                "nc_id": nc_id,
                "front": front,
                "mechanism_class": _field(nc_block, "Mechanism class"),
                "input_shape": _field(nc_block, "Input shape"),
                "why_blocked": _field(nc_block, "Why blocked"),
                "evidence": _field(nc_block, "Evidence"),
                "ruled_out": _field(nc_block, "Ruled out"),
            })

    if not suggestions:
        return {"new": 0, "duplicate": 0, "conflict": 0, "summary": "无 agents/*.md 中的 New Constraints 块"}

    # 2. 解析现有 constraints.md
    constraints_path = run_dir / "constraints.md"
    existing: list[dict] = []
    existing_ids: set[str] = set()
    if constraints_path.exists():
        text = constraints_path.read_text(encoding="utf-8", errors="replace")
        for m in re.finditer(r"(?ms)^##[ \t]+(C-\d+).*?(?=^##[ \t]+C-\d+|\Z)", text):
            block = m.group(0)
            cid = m.group(1)
            existing_ids.add(cid)
            existing.append({
                "id": cid,
                "front": _field(block, "Front"),
                "mechanism_class": _normalize_mechanism_class(_field(block, "Mechanism class")),
                "input_shape": _normalize_input_shape(_field(block, "Input shape")),
            })

    # 3. 去重: 相同 front + mechanism class canonical + 归一化 input shape 的约束只保留一条
    def _dedup_key(s: dict) -> tuple:
        return (
            s.get("front", "").strip().lower(),
            _normalize_mechanism_class(s.get("mechanism_class", "")),
            _normalize_input_shape(s.get("input_shape", "")),
        )

    existing_keys = {_dedup_key(e) for e in existing}
    new_count = 0
    dup_count = 0
    conflict_count = 0

    # 确定起始 C-id
    next_n = 1
    while f"C-{next_n:03d}" in existing_ids:
        next_n += 1

    new_entries: list[dict] = []
    for s in suggestions:
        key = _dedup_key(s)
        if key in existing_keys:
            dup_count += 1
            continue
        # 检查是否与已收集的新条目重复
        if any(_dedup_key(n) == key for n in new_entries):
            dup_count += 1
            continue
        existing_keys.add(key)
        s["cid"] = f"C-{next_n:03d}"
        next_n += 1
        new_entries.append(s)
        new_count += 1

    if new_count == 0:
        summary = f"无新约束（{dup_count} 条重复跳过）"
        return {"new": 0, "duplicate": dup_count, "conflict": conflict_count, "summary": summary}

    # 4. 创建或追加 constraints.md
    if not constraints_path.exists():
        # 使用模板头部创建
        header = (
            "# Constraints Ledger\n\n"
            "> 每条约束记录一个被尝试但受阻的 mechanism class + input shape 组合。\n"
            "> Mechanism class 必须使用 `knowledge/_lexicon.md` 的 canonical name。\n"
            "> Evidence 必须指向一个存在的 E-xxx（check_run 硬门强制检查）。\n"
            "> 条件文件 —— 只在有负向结果积累时创建。\n\n"
        )
        constraints_path.write_text(header, encoding="utf-8")

    with constraints_path.open("a", encoding="utf-8") as fh:
        for s in new_entries:
            fh.write(f"\n## {s['cid']}\n\n")
            fh.write(f"- Front: {s['front']}\n")
            fh.write(f"- Mechanism class: {_normalize_mechanism_class(s['mechanism_class'])}\n")
            fh.write(f"- Input shape: {s['input_shape']}\n")
            fh.write(f"- Why blocked: {s['why_blocked']}\n")
            fh.write(f"- Evidence: {s['evidence']}\n")
            fh.write(f"- Ruled out: {s['ruled_out']}\n")

    summary = f"新增 {new_count} 条约束, {dup_count} 条重复跳过, {conflict_count} 条冲突"
    return {"new": new_count, "duplicate": dup_count, "conflict": conflict_count, "summary": summary}


def print_merge_constraints(run_dir: Path) -> int:
    result = merge_constraints(run_dir)
    print(f"[workers merge-constraints] {result['summary']}")
    if result["new"] > 0:
        print(f"  约束已写入 {display_path(run_dir / 'constraints.md')}")
    return 0


def _selftest() -> int:
    from concurrent.futures import ThreadPoolExecutor
    import threading
    from unittest import mock

    d = Path(tempfile.mkdtemp())
    artifact_review_run = d / "artifact-review"
    (artifact_review_run / "evidence").mkdir(parents=True)
    artifact_paths: list[Path] = []
    for name, body, url in (
        ("root.html", b"root\n", "http://127.0.0.1:18765/"),
        ("health.json", b'{"ok":true}\n', "http://127.0.0.1:18765/health.json"),
    ):
        body_path = artifact_review_run / "evidence" / name
        replay_path = artifact_review_run / "evidence" / f"{name}.replay.json"
        body_path.write_bytes(body)
        replay_path.write_text(json.dumps({
            "request": {"method": "GET", "url": url},
            "response": {
                "status": 200,
                "len": len(body),
                "sha1": hashlib.sha1(body).hexdigest(),
            },
            "saved_body": str(body_path.resolve()),
        }), encoding="utf-8")
        artifact_paths.extend((body_path, replay_path))
    frozen_artifact_text = "Artifacts:\n" + "".join(
        f"- {path.resolve()}\n" for path in artifact_paths
    )
    validated_artifact_receipts = _validated_review_artifacts(
        artifact_review_run,
        target_row={"effect": "target"},
        target_text=frozen_artifact_text,
        reviewer_text=frozen_artifact_text,
        disposition="accept-candidate",
    )
    partial_wire = b"prefix-" + b"x" * 64
    partial_saved = partial_wire[:16]
    partial_body = artifact_review_run / "evidence" / "partial.html"
    partial_replay = artifact_review_run / "evidence" / "partial.html.replay.json"
    partial_body.write_bytes(partial_saved)
    partial_record = {
        "schema": "xunji.probe.replay.v2",
        "request": {"method": "GET", "url": "http://127.0.0.1:18765/partial"},
        "response": {
            "status": 200,
            "len": len(partial_wire),
            "sha1": hashlib.sha1(partial_wire).hexdigest(),
            "wire_len": len(partial_wire),
            "wire_sha1": hashlib.sha1(partial_wire).hexdigest(),
        },
        "saved_body": str(partial_body.resolve()),
        "saved_body_meta": {
            "len": len(partial_saved),
            "sha1": hashlib.sha1(partial_saved).hexdigest(),
            "truncated": True,
        },
    }
    partial_replay.write_text(json.dumps(partial_record), encoding="utf-8")
    partial_text = (
        "Artifacts:\n"
        f"- {partial_body.resolve()}\n"
        f"- {partial_replay.resolve()}\n"
    )
    partial_receipts = _validated_review_artifacts(
        artifact_review_run,
        target_row={"effect": "target"},
        target_text=partial_text,
        reviewer_text=partial_text,
        disposition="accept-candidate",
    )
    partial_response = next(
        item["response"] for item in partial_receipts
        if item.get("path", "").endswith(".replay.json"))
    legacy_partial_body = artifact_review_run / "evidence" / "legacy-partial.html"
    legacy_partial_replay = (
        artifact_review_run / "evidence" / "legacy-partial.html.replay.json")
    legacy_partial_body.write_bytes(partial_saved)
    legacy_partial_replay.write_text(json.dumps({
        "request": {
            "method": "GET",
            "url": "http://127.0.0.1:18765/legacy-partial",
        },
        "response": {
            "status": 200,
            "len": len(partial_wire),
            "sha1": hashlib.sha1(partial_wire).hexdigest(),
        },
        "saved_body": str(legacy_partial_body.resolve()),
    }), encoding="utf-8")
    legacy_partial_text = (
        "Artifacts:\n"
        f"- {legacy_partial_body.resolve()}\n"
        f"- {legacy_partial_replay.resolve()}\n"
    )
    legacy_partial_receipts = _validated_review_artifacts(
        artifact_review_run,
        target_row={"effect": "target"},
        target_text=legacy_partial_text,
        reviewer_text=legacy_partial_text,
        disposition="accept-candidate",
    )
    legacy_partial_response = next(
        item["response"] for item in legacy_partial_receipts
        if item.get("path", "").endswith(".replay.json"))
    empty_wire_hash_rejected = False
    invalid_partial_record = json.loads(json.dumps(partial_record))
    invalid_partial_record["response"]["sha1"] = ""
    invalid_partial_record["response"]["wire_sha1"] = ""
    partial_replay.write_text(json.dumps(invalid_partial_record), encoding="utf-8")
    try:
        _validated_review_artifacts(
            artifact_review_run,
            target_row={"effect": "target"},
            target_text=partial_text,
            reviewer_text=partial_text,
            disposition="accept-candidate",
        )
    except ValueError as exc:
        empty_wire_hash_rejected = "wire hash" in str(exc)
    partial_replay.write_text(json.dumps(partial_record), encoding="utf-8")
    stale_reviewer_artifact_rejected = False
    try:
        _validated_review_artifacts(
            artifact_review_run,
            target_row={"effect": "target"},
            target_text=frozen_artifact_text,
            reviewer_text=(frozen_artifact_text
                           + "- evidence/stale-probe.html\n"),
            disposition="accept-candidate",
        )
    except ValueError as exc:
        stale_reviewer_artifact_rejected = "evidence set mismatch" in str(exc)
    run = d / "run"
    run.mkdir()
    (run / "state").mkdir()
    (run / "target.md").write_text(
        "# Target\n- Authorized scope: a.example b.example c.example\n",
        encoding="utf-8",
    )
    (run / "state" / "turn_contract.json").write_text(json.dumps({
        "schema": "xunji.turn_contract.v1", "mode": "EXECUTE",
        "session_id": "planner-fixture", "prompt_sha256": "a" * 64,
        "updated_at": time.time(), "fanout_override": False,
    }), encoding="utf-8")
    empty_run = d / "empty"
    empty_run.mkdir()
    legacy_assignment_run = d / "legacy-assignment"
    (legacy_assignment_run / "state").mkdir(parents=True)
    (legacy_assignment_run / "state" / "assignments.json").write_text(json.dumps({
        "schema": 1,
        "assignments": [{"agent": "A-legacy-001", "front": "F-001",
                         "status": "working"}],
    }), encoding="utf-8")
    migrated_assignments = load_assignments(legacy_assignment_run)
    unknown_schema_run = d / "unknown-assignment-schema"
    (unknown_schema_run / "state").mkdir(parents=True)
    (unknown_schema_run / "state" / "assignments.json").write_text(
        json.dumps({"schema": 999, "assignments": []}), encoding="utf-8")
    try:
        load_assignments(unknown_schema_run)
        unknown_assignment_schema_rejected = False
    except ValueError as exc:
        unknown_assignment_schema_rejected = "unsupported ledger schema" in str(exc)
    (run / "coverage.json").write_text(json.dumps({"assets": [
        {"host": "a.example", "reachable": True, "flags": ["LOGIN"]},
        {"host": "b.example", "reachable": True, "flags": ["SURFACE:API"]},
        {"host": "c.example", "reachable": True, "flags": ["SURFACE:UPLOAD"]},
        {"host": "f.example", "reachable": True, "flags": ["SURFACE:API"], "examined": True},
        {"host": "d.example", "reachable": False, "flags": []},
        {"host": "e.example", "reachable": True, "high_value": True, "examined": False,
         "verdict": None, "category": "sso", "flags": []},
    ]}), encoding="utf-8")
    (run / "frontier.md").write_text(
        "# Frontier\n## Open Fronts\n"
        "### F-001\n- Front: a.example auth boundary\n- Status: open\n- Current depth: shallow\n"
        "- Barrier class: none\n- Same barrier failures: 0\n\n"
        "### F-002\n- Front: b.example and f.example API params\n- Status: open\n- Current depth: shallow\n"
        "- Barrier class: none\n- Same barrier failures: 0\n\n"
        "### F-003\n- Front: c.example upload\n- Status: probing\n- Current depth: shallow\n"
        "- Barrier class: none\n- Same barrier failures: 1\n\n"
        "### F-004\n- Front: d.example WAF block\n- Status: deferred\n- Current depth: shallow\n"
        "- Barrier class: WAF-layer\n- Same barrier failures: 4\n\n"
        "## Closed Fronts\n### F-099\n- Status: closed\n", encoding="utf-8")
    p1 = create_worker(run, "F-001")
    p2 = create_worker(run, "F-002")
    p1.write_text(
        "# Worker W-01\n- Assigned front: F-001\n- Status: done\n\n## Candidate findings\n\n"
        "### CAND-1\n- Claim: IDOR in profile\n- Proposed certainty: 0.8\n- Control / Replicated:\n",
        encoding="utf-8")
    p2.write_text(
        "# Worker W-02\n- Assigned front: F-002\n- Status: done\n\n## Candidate findings\n\n"
        "### CAND-1\n- Claim: IDOR in profile\n- Proposed certainty: 0.5\n- Control / Replicated: baseline differs\n",
        encoding="utf-8")
    rows = suggest(run)
    planned_lanes = lane_suggestions(run, limit=1)
    s1_planned_lanes = lane_suggestions(run, limit=2, stage="S1")
    s3_planned_lanes = lane_suggestions(run, limit=2, stage="S3")
    offline_plan_run = d / "offline-plan"
    (offline_plan_run / "state").mkdir(parents=True)
    for name in ("coverage.json", "frontier.md"):
        (offline_plan_run / name).write_bytes((run / name).read_bytes())
    (offline_plan_run / "state" / "turn_contract.json").write_text(
        json.dumps({
            "schema": "xunji.turn_contract.v1",
            "mode": "EXECUTE",
            "target_egress_denied": True,
            "session_id": "offline-planner-fixture",
            "prompt_sha256": "b" * 64,
            "updated_at": time.time(),
            "fanout_override": False,
        }),
        encoding="utf-8",
    )
    offline_planned_lanes = lane_suggestions(offline_plan_run, limit=1)
    offline_plan_output = io.StringIO()
    with contextlib.redirect_stdout(offline_plan_output):
        offline_plan_exit = print_plan(offline_plan_run, 1)
    asset_rows = asset_suggestions(run)
    issues = merge_check(run)
    clean_run = d / "clean"
    clean_run.mkdir()
    no_strong = d / "no_strong"
    no_strong.mkdir()
    (no_strong / "frontier.md").write_text(
        "# Frontier\n## Deferred Fronts\n### F-001\n- Front: unmapped\n- Status: deferred\n"
        "- Barrier class: WAF-layer\n- Same barrier failures: 4\n", encoding="utf-8")
    created = create_worker(clean_run, "F-123")
    clean_rows = scan(clean_run)
    with_missing = d / "with_missing"
    with_missing.mkdir()
    (with_missing / "workers").mkdir()
    (with_missing / "workers" / "W-01.md").write_text(
        "# Worker W-01\n- Assigned front: F-001\n- Status: done\n\n## Candidate findings\n\n"
        "### CAND-1\n- Claim:\n- Proposed certainty: 0.8\n- Control / Replicated:\n",
        encoding="utf-8")
    missing_issues = merge_check(with_missing)
    plan_limited_rows = [r for r in suggest(run) if r["score"] >= 3]
    successful_plan_output = io.StringIO()
    with contextlib.redirect_stdout(successful_plan_output):
        successful_plan_exit = print_plan(run, 1)
    parallel_plan_output = io.StringIO()
    with contextlib.redirect_stdout(parallel_plan_output):
        parallel_plan_exit = print_plan(run, 2)
    planner_seed_bytes = _plan_proposal_path(run).read_bytes()
    planner_seed_proposal = json.loads(planner_seed_bytes.decode("utf-8"))
    planner_seed_digest = hashlib.sha256(planner_seed_bytes).hexdigest()
    driver_output = io.StringIO()
    with contextlib.redirect_stdout(driver_output):
        no_strong_exit = print_plan(no_strong, 3)
        clean_exit = print_merge_check(empty_run)
        legacy_list_exit = main([str(run)])
        legacy_new_exit = main([str(run), "--new", "F-777"])
        assign_cli_exit = main(["assign", str(run), "--role", "review", "--front", "F-001",
                                "--asset", "a.example"])
        status_cli_exit = main(["status", str(run)])
        empty_status_cli_exit = print_status(empty_run)
    agent_check_empty_exit = main(["agent-check", str(empty_run)])
    agent_clean = d / "agent_clean"
    agent_clean.mkdir()
    agent_clean_rec = create_agent_assignment(agent_clean, role="web-hunter", front="F-001")
    agent_clean_file = ROOT / agent_clean_rec["agent_file"] if not Path(agent_clean_rec["agent_file"]).is_absolute() else Path(agent_clean_rec["agent_file"])
    agent_clean_text = agent_clean_file.read_text(encoding="utf-8")
    agent_clean_issues = agent_discipline_issues(agent_clean)
    threat_run = d / "threat_run"
    threat_run.mkdir()
    (threat_run / "agents").mkdir()
    (threat_run / "agents" / "A-web-hunter-001.md").write_text(
        "# Agent A-web-hunter-001\n"
        "- Role: web-hunter\n- Assigned front: F-001\n- Status: done\n\n"
        "## New Threat Hypotheses\n\n"
        "### NH-1\n"
        "- Threat hypothesis: signed client param can be replayed across users\n"
        "- Asset/role/input: app.example user POST /api/order sign, uid\n"
        "- Expected signal: same signed body accepted for a different user-owned order id\n"
        "- Refutation/control: replay with owner id and tampered uid rejects equally\n"
        "- Linked IS/C/E: IS-001\n"
        "- Status: candidate\n"
        "- Next action: Root records H and runs guarded replay control\n",
        encoding="utf-8")
    threat_merge = merge_threats(threat_run)
    threat_merge_dup = merge_threats(threat_run)
    threat_hyp_text = (threat_run / "hypotheses.md").read_text(encoding="utf-8")
    threat_bad = d / "threat_bad"
    threat_bad.mkdir()
    (threat_bad / "agents").mkdir()
    (threat_bad / "state").mkdir()
    (threat_bad / "state" / "assignments.json").write_text(json.dumps({
        "assignments": [{"agent": "A-web-hunter-001", "role": "web-hunter", "front": "F-001"}]
    }), encoding="utf-8")
    (threat_bad / "agents" / "A-web-hunter-001.md").write_text(
        "# Agent A-web-hunter-001\n"
        "- Role: web-hunter\n- Assigned front: F-001\n- Status: done\n\n"
        "## Prelude\n\n## Recurrent Loop\n\n## Safety / Guard Invariants\n"
        "- guard\n- request budget\n- untrusted\n\n"
        "## Notes\n\n- Target temp file: xunji_wcfg_export.txt\n\n"
        "- Cleanup plan: cleanup of https://example.test/uploads/tmp-20260708-a1b2c3d4.txt after proof\n\n"
        "## New Threat Hypotheses\n\n"
        "### NH-1\n"
        "- Threat hypothesis: admin API hidden in JS\n"
        "- Asset/role/input:\n"
        "- Expected signal: /api/admin/users returns role-specific difference\n"
        "- Refutation/control: unauth and user replay both 403\n"
        "- Linked IS/C/E:\n"
        "- Status: confirmed\n"
        "- Next action:\n",
        encoding="utf-8")
    threat_bad_issues = agent_discipline_issues(threat_bad)
    agent_rdt_bad = d / "agent_rdt_bad"
    agent_rdt_bad.mkdir()
    rdt_bad_rec = create_agent_assignment(agent_rdt_bad, role="web-hunter", front="F-001")
    rdt_bad_file = ROOT / rdt_bad_rec["agent_file"] if not Path(rdt_bad_rec["agent_file"]).is_absolute() else Path(rdt_bad_rec["agent_file"])
    rdt_bad_file.write_text(
        re.sub(
            r"(?m)^- Context SHA-256: [0-9a-f]{64}$",
            "- Context SHA-256: invalid",
            rdt_bad_file.read_text(encoding="utf-8"),
        ),
        encoding="utf-8")
    rdt_bad_issues = agent_discipline_issues(agent_rdt_bad)
    status_sync = d / "status_sync"
    status_sync.mkdir()
    sync_rec = create_agent_assignment(status_sync, role="web-hunter", front="F-001")
    sync_file = ROOT / sync_rec["agent_file"] if not Path(sync_rec["agent_file"]).is_absolute() else Path(sync_rec["agent_file"])
    sync_file.write_text(sync_file.read_text(encoding="utf-8").replace(
        "- Status: assigned", "- Status: complete (candidate produced)"), encoding="utf-8")
    sync_rows = agent_status_rows(status_sync)
    sync_state = load_assignments(status_sync)
    status_findings = d / "status_findings"
    status_findings.mkdir()
    findings_rec = create_agent_assignment(status_findings, role="web-hunter", front="F-002")
    findings_file = ROOT / findings_rec["agent_file"] if not Path(findings_rec["agent_file"]).is_absolute() else Path(findings_rec["agent_file"])
    findings_file.write_text(findings_file.read_text(encoding="utf-8") + "\n## Findings\n\n- Candidate: done\n", encoding="utf-8")
    findings_rows = agent_status_rows(status_findings)
    findings_state = load_assignments(status_findings)
    status_blank_findings = d / "status_blank_findings"
    status_blank_findings.mkdir()
    blank_rec = create_agent_assignment(status_blank_findings, role="web-hunter", front="F-003")
    blank_file = ROOT / blank_rec["agent_file"] if not Path(blank_rec["agent_file"]).is_absolute() else Path(blank_rec["agent_file"])
    blank_file.write_text(blank_file.read_text(encoding="utf-8") + "\n## Findings\n\n", encoding="utf-8")
    blank_rows = agent_status_rows(status_blank_findings)
    blank_state = load_assignments(status_blank_findings)
    status_negative_findings = d / "status_negative_findings"
    status_negative_findings.mkdir()
    neg_rec = create_agent_assignment(status_negative_findings, role="web-hunter", front="F-004")
    neg_file = ROOT / neg_rec["agent_file"] if not Path(neg_rec["agent_file"]).is_absolute() else Path(neg_rec["agent_file"])
    neg_file.write_text(neg_file.read_text(encoding="utf-8") + "\n## Findings\n\nNo exploitable issues found.\n", encoding="utf-8")
    neg_rows = agent_status_rows(status_negative_findings)
    neg_state = load_assignments(status_negative_findings)
    status_placeholder_findings = d / "status_placeholder_findings"
    status_placeholder_findings.mkdir()
    placeholder_rec = create_agent_assignment(status_placeholder_findings, role="web-hunter", front="F-005")
    placeholder_file = ROOT / placeholder_rec["agent_file"] if not Path(placeholder_rec["agent_file"]).is_absolute() else Path(placeholder_rec["agent_file"])
    placeholder_file.write_text(
        placeholder_file.read_text(encoding="utf-8") + "\n## Findings\n\n- Candidate: still investigating\n",
        encoding="utf-8")
    placeholder_rows = agent_status_rows(status_placeholder_findings)
    placeholder_state = load_assignments(status_placeholder_findings)
    lifecycle_run = d / "lifecycle_run"
    lifecycle_run.mkdir()
    lifecycle_rec = create_agent_assignment(lifecycle_run, role="web-hunter", front="F-006")
    lifecycle_open = agent_lifecycle_issues(lifecycle_run, closure=True)
    update_agent_lifecycle(lifecycle_run, lifecycle_rec["agent"], status="running", note="started")
    lifecycle_running_state = load_assignments(lifecycle_run)
    update_agent_lifecycle(lifecycle_run, lifecycle_rec["agent"], status="done", note="returned coda", terminal=True)
    lifecycle_closed = agent_lifecycle_issues(lifecycle_run, closure=True)
    lifecycle_file = ROOT / lifecycle_rec["agent_file"] if not Path(lifecycle_rec["agent_file"]).is_absolute() else Path(lifecycle_rec["agent_file"])
    lifecycle_text = lifecycle_file.read_text(encoding="utf-8")

    explicit_assets_required = False
    try:
        create_agent_assignment(run, role="web-hunter", front="F-001")
    except ValueError as exc:
        explicit_assets_required = "explicit --asset" in str(exc)

    hunter_run = d / "hunter_role"
    hunter_run.mkdir()
    (hunter_run / "coverage.json").write_text(json.dumps({"assets": [
        {"host": "hunter.example", "reachable": True, "examined": False},
    ]}), encoding="utf-8")
    (hunter_run / "frontier.md").write_text(
        "# Frontier\n## Open Fronts\n### F-001\n"
        "- Front: hunter.example lane\n- Status: open\n"
        "- Barrier class: none\n- Current depth: shallow\n",
        encoding="utf-8")
    hunter_alias_requires_assets = False
    try:
        create_agent_assignment(hunter_run, role="hunter", front="F-001")
    except ValueError as exc:
        hunter_alias_requires_assets = "explicit --asset" in str(exc)
    unknown_role_rejected = False
    try:
        create_agent_assignment(hunter_run, role="mystery-hunter", front="F-001")
    except ValueError as exc:
        unknown_role_rejected = "unknown Agent role" in str(exc)

    disposition_run = d / "disposition_run"
    disposition_run.mkdir()
    (disposition_run / "frontier.md").write_text(
        "# Frontier\n## Open Fronts\n### F-001\n- Front: review lane\n"
        "- Status: open\n- Barrier class: none\n- Current depth: shallow\n",
        encoding="utf-8")
    (disposition_run / "decisions.md").write_text(
        "# Decisions\n## D-001\n- Result: framework barrier\n", encoding="utf-8")
    disposition_rec = create_agent_assignment(
        disposition_run, role="review", front="F-001")
    disposition_path = _assignments_path(disposition_run)
    disposition_bytes_before_invalid = disposition_path.read_bytes()
    missing_reason_rejected = False
    try:
        update_agent_lifecycle(
            disposition_run, disposition_rec["agent"], status="blocked",
            note="Front: F-001; framework barrier", terminal=True)
    except ValueError as exc:
        missing_reason_rejected = (
            str(exc) == "invalid disposition note; blocked 缺 Reason:"
        )
    missing_reason_preserves_state = (
        disposition_path.read_bytes() == disposition_bytes_before_invalid)
    missing_front_rejected = False
    try:
        update_agent_lifecycle(
            disposition_run, disposition_rec["agent"], status="blocked",
            note="Reason: framework barrier", terminal=True)
    except ValueError as exc:
        missing_front_rejected = (
            str(exc) == "invalid disposition note; blocked 缺 Front: F-xxx"
        )
    malformed_finish_preserves_state = (
        missing_reason_preserves_state
        and disposition_path.read_bytes() == disposition_bytes_before_invalid)
    invalid_disposition_rejected = False
    try:
        update_agent_lifecycle(
            disposition_run, disposition_rec["agent"], status="blocked",
            note="Reason: barrier; Front: F-001; Evidence: E-404", terminal=True)
    except ValueError as exc:
        invalid_disposition_rejected = "E-404" in str(exc)
    first_disposition = update_agent_lifecycle(
        disposition_run, disposition_rec["agent"], status="blocked",
        note="Reason: framework barrier; Front: F-001; Decision: D-001", terminal=True)
    silent_terminal_rewrite_rejected = False
    try:
        update_agent_lifecycle(
            disposition_run, disposition_rec["agent"], status="failed",
            note="Reason: revised barrier; Front: F-001; Decision: D-001", terminal=True)
    except ValueError as exc:
        silent_terminal_rewrite_rejected = "finish --amend" in str(exc)
    amended_disposition = update_agent_lifecycle(
        disposition_run, disposition_rec["agent"], status="blocked",
        note="Reason: corrected framework barrier; Front: F-001; Decision: D-001",
        terminal=True, amend=True)
    disposition_history_preserved = (
        first_disposition.get("status") == "blocked"
        and len(amended_disposition.get("disposition_history", [])) == 1
        and amended_disposition["disposition_history"][0].get("note")
        == "Reason: framework barrier; Front: F-001; Decision: D-001")
    heartbeat_cannot_set_terminal = False
    try:
        update_agent_lifecycle(
            disposition_run, disposition_rec["agent"], status="running",
            note="reopened via heartbeat", terminal=False)
    except ValueError as exc:
        heartbeat_cannot_set_terminal = "cannot reopen" in str(exc)
    done_rec = create_agent_assignment(
        disposition_run, role="review", front="F-001")
    update_agent_lifecycle(
        disposition_run, done_rec["agent"], status="done",
        note="runtime returned", terminal=True)
    done_to_adjudicated = update_agent_lifecycle(
        disposition_run, done_rec["agent"], status="blocked",
        note="Reason: no target action; Front: F-001; Decision: D-001", terminal=True)
    done_to_adjudicated_allowed = done_to_adjudicated.get("status") == "blocked"
    receipts_missing_rec = create_agent_assignment(
        disposition_run, role="review", front="F-001")
    saved_runtime_receipts = _runtime_receipts
    receipts_missing_fails_closed = False
    try:
        globals()["_runtime_receipts"] = None
        update_agent_lifecycle(
            disposition_run, receipts_missing_rec["agent"], status="blocked",
            note="Reason: no validator; Front: F-001; Decision: D-001", terminal=True)
    except ValueError as exc:
        receipts_missing_fails_closed = "runtime_receipts unavailable" in str(exc)
    finally:
        globals()["_runtime_receipts"] = saved_runtime_receipts

    def build_merge_gate_run(name: str, assets_for_agent: list[str]) -> tuple[Path, dict, Path, str]:
        gate_run = d / name
        (gate_run / "state").mkdir(parents=True)
        hosts = ", ".join(assets_for_agent)
        (gate_run / "coverage.json").write_text(json.dumps({"assets": [
            {"host": host, "reachable": True, "examined": False} for host in assets_for_agent
        ]}), encoding="utf-8")
        (gate_run / "frontier.md").write_text(
            "# Frontier\n## Open Fronts\n### F-001\n"
            f"- Front: {hosts} bounded lane\n- Status: open\n"
            "- Barrier class: none\n- Current depth: shallow\n",
            encoding="utf-8")
        rec = create_agent_assignment(
            gate_run, role="web-hunter", front="F-001", assets=assets_for_agent)
        subagent_type = "xunji-hunter"
        transcript_path = gate_run / f"{name}.jsonl"
        child_id = "child-" + name
        launch_prompt = (
            f"XUNJI_ASSIGNMENT={rec['agent']} XUNJI_FRONT=F-001 "
            f"XUNJI_ASSETS={','.join(assets_for_agent)}")
        transcript_path.write_text(json.dumps({
            "message": {"role": "assistant", "content": [{
                "type": "tool_use", "id": "launch-" + name, "name": "Agent",
                "input": {
                    "prompt": launch_prompt,
                    "subagent_type": subagent_type,
                },
            }]},
        }) + "\n", encoding="utf-8")
        child_dir = transcript_path.with_suffix("") / "subagents"
        child_dir.mkdir(parents=True)
        (child_dir / f"agent-{child_id}.jsonl").write_text(
            "\n".join(json.dumps({
                "isSidechain": True,
                "sessionId": name,
                "agentId": child_id,
                "message": {"role": "assistant", "content": [{
                    "type": "tool_use", "id": "action-" + host, "name": "Bash",
                    "input": {
                        "command": f"python3 tools/probe.py GET https://{host}"},
                }]},
            }) for host in assets_for_agent) + "\n",
            encoding="utf-8",
        )
        _runtime_receipts.append_hook_event(gate_run, {
            "hook_event_name": "PostToolUse", "session_id": name,
            "transcript_path": str(transcript_path), "tool_name": "Agent",
            "tool_use_id": "launch-" + name,
            "tool_input": {
                "prompt": launch_prompt,
                "subagent_type": subagent_type,
            },
            "tool_response": {"agentId": child_id, "isAsync": True,
                              "status": "async_launched"},
        })
        return gate_run, rec, transcript_path, child_id

    zero_run, zero_rec, zero_transcript, zero_child = build_merge_gate_run(
        "zero-activity", ["zero.example"])
    (zero_run / "evidence.md").write_text(
        "# Evidence\n## E-001\n- Action: checked zero.example\n- Result: barrier\n- Certainty: 0.5\n",
        encoding="utf-8")
    _runtime_receipts.append_hook_event(zero_run, {
        "hook_event_name": "SubagentStop", "session_id": "zero-activity",
        "transcript_path": str(zero_transcript), "agent_id": zero_child,
        "agent_type": "xunji-hunter",
        "tool_response": {"content": "zero-activity Agent returned no target action"},
    })
    zero_activity_merge_blocked = False
    try:
        update_agent_lifecycle(
            zero_run, zero_rec["agent"], status="merged",
            note="Evidence: E-001 Front: F-001", terminal=True)
    except ValueError as exc:
        zero_activity_merge_blocked = "no successful target-action receipt" in str(exc)

    partial_run, partial_rec, partial_transcript, partial_child = build_merge_gate_run(
        "partial-activity", ["one.example", "two.example"])
    (partial_run / "evidence.md").write_text(
        "# Evidence\n## E-001\n- Action: checked one.example and two.example\n"
        "- Result: per-asset controls recorded\n- Certainty: 0.5\n",
        encoding="utf-8")
    _runtime_receipts.append_hook_event(partial_run, {
        "hook_event_name": "PostToolUse", "session_id": "partial-activity",
        "transcript_path": str(partial_transcript), "tool_name": "Bash",
        "tool_use_id": "action-one.example", "agent_id": partial_child,
        "tool_input": {"command": "python3 tools/probe.py GET https://one.example"},
        "tool_response": {"stdout": "ok"}, "xunji_target_action": True,
    })
    _runtime_receipts.append_hook_event(partial_run, {
        "hook_event_name": "SubagentStop", "session_id": "partial-activity",
        "transcript_path": str(partial_transcript), "agent_id": partial_child,
        "agent_type": "xunji-hunter",
        "tool_response": {"content": "partial-activity Agent returned one asset result"},
    })
    partial_asset_merge_blocked = False
    try:
        update_agent_lifecycle(
            partial_run, partial_rec["agent"], status="merged",
            note="Evidence: E-001 Front: F-001", terminal=True)
    except ValueError as exc:
        partial_asset_merge_blocked = "two.example" in str(exc)

    full_run, full_rec, full_transcript, full_child = build_merge_gate_run(
        "full-activity", ["alpha.example", "bravo.example"])
    (full_run / "evidence.md").write_text(
        "# Evidence\n## E-001\n- Action: checked alpha.example and bravo.example\n"
        "- Result: per-asset controls recorded\n- Certainty: 0.5\n",
        encoding="utf-8")
    for host in ("alpha.example", "bravo.example"):
        _runtime_receipts.append_hook_event(full_run, {
            "hook_event_name": "PostToolUse", "session_id": "full-activity",
            "transcript_path": str(full_transcript), "tool_name": "Bash",
            "tool_use_id": "action-" + host, "agent_id": full_child,
            "tool_input": {"command": f"python3 tools/probe.py GET https://{host}"},
            "tool_response": {"stdout": "ok"}, "xunji_target_action": True,
        })
    _runtime_receipts.append_hook_event(full_run, {
        "hook_event_name": "SubagentStop", "session_id": "full-activity",
        "transcript_path": str(full_transcript), "agent_id": full_child,
        "agent_type": "xunji-hunter",
        "tool_response": {"content": "full-activity Agent returned both asset results"},
    })
    full_merge = update_agent_lifecycle(
        full_run, full_rec["agent"], status="merged",
        note="Evidence: E-001 Front: F-001", terminal=True)
    full_asset_merge_allowed = (
        full_merge.get("coverage_merge_satisfied") is True
        and set((full_merge.get("coverage_merge") or {}).get("assets", {}))
        == {"alpha.example", "bravo.example"}
    )

    # Delegate must consume the actual scheduler selection.  The first ready
    # lane is over budget while the second fits; a width-only reconstruction
    # would incorrectly assign L-EXPENSIVE.
    budget_run = d / "delegate-budget-selection"
    (budget_run / "state").mkdir(parents=True)
    (budget_run / "target.md").write_text(
        "# Target\n- Authorized scope: offline scheduler fixture\n",
        encoding="utf-8",
    )
    (budget_run / "coverage.json").write_text(json.dumps({
        "assets": [{"host": "inventory.example", "examined": False}],
    }), encoding="utf-8")
    (budget_run / "frontier.md").write_text(
        "# Frontier\n\n## Open Fronts\n\n### F-020 — expensive\n"
        "- Status: open\n- Barrier class: none\n- Current depth: shallow\n\n"
        "### F-021 — cheap\n- Status: open\n- Barrier class: none\n"
        "- Current depth: shallow\n",
        encoding="utf-8",
    )
    budget_contract = {
        "schema": "xunji.turn_contract.v1", "mode": "EXECUTE",
        "session_id": "budget-session", "prompt_sha256": "e" * 64,
        "updated_at": time.time(), "fanout_override": False,
    }
    _atomic_write(
        budget_run / "state" / "turn_contract.json",
        json.dumps(budget_contract, ensure_ascii=False, indent=2) + "\n",
    )
    budget_lanes = [{
        "id": "L-EXPENSIVE", "role": "web-hunter", "front": "F-020",
        "effect": "local_read", "assets": [], "dependencies": [],
        "expected_evidence": "bounded expensive result",
        "expected_information_gain": "medium", "stop_condition": "one result",
        "request_cost": 0, "request_budget": 0, "merge_cost": 20,
        "atomic": False,
    }, {
        "id": "L-CHEAP", "role": "web-hunter", "front": "F-021",
        "effect": "local_read", "assets": [], "dependencies": [],
        "expected_evidence": "bounded cheap result",
        "expected_information_gain": "medium", "stop_condition": "one result",
        "request_cost": 0, "request_budget": 0, "merge_cost": 5,
        "atomic": False,
    }, {
        "id": "L-EXPENSIVE-REVIEW", "role": "review", "front": "F-020",
        "effect": "local_verify", "assets": [],
        "dependencies": ["L-EXPENSIVE"],
        "expected_evidence": "digest-bound expensive result review",
        "expected_information_gain": "medium",
        "stop_condition": "exact expensive result challenged",
        "request_cost": 0, "request_budget": 0, "merge_cost": 5,
        "atomic": False,
    }, {
        "id": "L-CHEAP-REVIEW", "role": "review", "front": "F-021",
        "effect": "local_verify", "assets": [],
        "dependencies": ["L-CHEAP"],
        "expected_evidence": "digest-bound cheap result review",
        "expected_information_gain": "medium",
        "stop_condition": "exact cheap result challenged",
        "request_cost": 0, "request_budget": 0, "merge_cost": 5,
        "atomic": False,
    }]
    _work_plan.commit_plan(
        budget_run, macro_stage="S2", objective="exercise exact scheduler selection",
        mode="PARALLEL_AGENTS", reason="two independent local-read lanes",
        exit_gate="both results reviewed", contract=budget_contract,
        lanes=budget_lanes,
    )
    budget_batch = delegate_ready_lanes(
        budget_run, runtime_slots=2, request_budget=0,
        model_egress_budget=0, merge_capacity=5, limit=2,
    )
    delegate_uses_exact_budget_selection = (
        [item.get("lane_id") for item in budget_batch.get("assignments", [])]
        == ["L-CHEAP"]
    )
    exact_capacity_diagnostic = _capacity_diagnostic(
        [{"work_plan_lane": budget_lanes[0]}],
        available_slots=1,
        request_budget=0,
        model_egress_budget=0,
        merge_capacity=1,
    )
    (budget_run / "hints.md").write_text(
        "# Hints\n\n- New operator steering after the first execution assignment.\n",
        encoding="utf-8",
    )
    stale_plan_new_execution_blocked = False
    try:
        delegate_ready_lanes(
            budget_run, runtime_slots=2, request_budget=10,
            model_egress_budget=1, merge_capacity=100, limit=2,
        )
    except ValueError as exc:
        stale_plan_new_execution_blocked = (
            "WORK_PLAN_STALE_SETTLEMENT_ONLY" in str(exc))
    target_over_budget = dict(
        budget_lanes[0], id="L-TARGET-OVER", effect="target",
        assets=["inventory.example"], request_cost=2, request_budget=2,
        merge_cost=5,
    )
    model_over_budget = dict(
        budget_lanes[0], id="L-MODEL-OVER", effect="model_egress",
        request_cost=2, request_budget=2, merge_cost=5,
    )
    scheduler_skips_each_over_budget_effect = all(
        [row["work_plan_lane"]["id"] for row in scheduler_selection(
            [{"work_plan_lane": first},
             {"work_plan_lane": budget_lanes[1]}],
            runtime_slots=1, request_budget=requests,
            model_egress_budget=model_egress, merge_capacity=merge,
        )] == ["L-CHEAP"]
        for first, requests, model_egress, merge in (
            (budget_lanes[0], 0, 0, 5),
            (target_over_budget, 1, 0, 5),
            (model_over_budget, 0, 1, 5),
        )
    )

    def build_delegate_transaction_run(
        name: str, token: str, *, include_target_lane: bool = False,
    ) -> Path:
        transaction_run = d / name
        (transaction_run / "state").mkdir(parents=True)
        parent_transcript = transaction_run / "parent-transcript.jsonl"
        parent_transcript.write_text("", encoding="utf-8")
        (transaction_run / "target.md").write_text(
            "# Target\n- Authorized scope: offline transaction fixture\n",
            encoding="utf-8",
        )
        (transaction_run / "coverage.json").write_text(json.dumps({
            "assets": [{"host": "transaction.example", "examined": False}],
        }), encoding="utf-8")
        (transaction_run / "frontier.md").write_text(
            "# Frontier\n\n## Open Fronts\n\n"
            "### F-030 — first local lane\n- Status: open\n"
            "- Barrier class: none\n- Current depth: shallow\n\n"
            "### F-031 — second local lane"
            + (" for transaction.example" if include_target_lane else "")
            + "\n- Status: open\n"
            "- Barrier class: none\n- Current depth: shallow\n",
            encoding="utf-8",
        )
        contract = {
            "schema": "xunji.turn_contract.v1", "mode": "EXECUTE",
            "session_id": f"transaction-{token}",
            "prompt_sha256": token * 64,
            "updated_at": time.time(), "fanout_override": False,
            "transcript_path": str(parent_transcript.resolve()),
        }
        _atomic_write(
            transaction_run / "state" / "turn_contract.json",
            json.dumps(contract, ensure_ascii=False, indent=2) + "\n",
        )
        execution_lanes = [{
            "id": "L-FIRST", "role": "web-hunter", "front": "F-030",
            "effect": "local_read", "assets": [], "dependencies": [],
            "expected_evidence": "first bounded local result",
            "expected_information_gain": "medium",
            "stop_condition": "one attributable local result",
            "request_cost": 0, "request_budget": 0, "merge_cost": 5,
            "atomic": False,
        }, {
            "id": "L-SECOND", "role": "web-hunter", "front": "F-031",
            "effect": "target" if include_target_lane else "local_read",
            "assets": ["transaction.example"] if include_target_lane else [],
            "dependencies": [],
            "expected_evidence": "second bounded local result",
            "expected_information_gain": "medium",
            "stop_condition": "one attributable local result",
            "request_cost": 1 if include_target_lane else 0,
            "request_budget": 1 if include_target_lane else 0,
            "merge_cost": 5,
            "atomic": False,
        }]
        reviewer_lanes = [{
            "id": f"{lane['id']}-REVIEW", "role": "review",
            "front": lane["front"], "effect": "local_verify", "assets": [],
            "dependencies": [lane["id"]],
            "expected_evidence": "digest-bound result review",
            "expected_information_gain": "medium",
            "stop_condition": "the exact result is dispositioned",
            "request_cost": 0, "request_budget": 0, "merge_cost": 5,
            "atomic": False,
        } for lane in execution_lanes]
        _work_plan.commit_plan(
            transaction_run, macro_stage="S2",
            objective="exercise recoverable atomic delegation",
            mode="PARALLEL_AGENTS",
            reason="two independent local-read lanes require one batch",
            exit_gate="both exact results receive Reviewer dispositions",
            contract=contract, lanes=execution_lanes + reviewer_lanes,
        )
        return transaction_run

    transaction_run = build_delegate_transaction_run(
        "delegate-transaction-rollback", "a")
    injected_failure_seen = False

    def fail_after_first_assignment(phase: str) -> None:
        if phase == "after_assignment_1":
            raise RuntimeError("injected delegate batch failure")

    try:
        delegate_ready_lanes(
            transaction_run, runtime_slots=2, request_budget=0,
            model_egress_budget=0, merge_capacity=10, limit=2,
            fault=fail_after_first_assignment,
        )
    except RuntimeError as exc:
        injected_failure_seen = "injected delegate batch failure" in str(exc)
    rolled_back_transaction = _load_delegate_transaction(transaction_run) or {}
    failed_batch_has_zero_partial_state = (
        injected_failure_seen
        and rolled_back_transaction.get("status") == "rolled_back"
        and not _assignments_path(transaction_run).exists()
        and _transaction_file_snapshot(agents_dir(transaction_run), agents=True) == []
        and _transaction_file_snapshot(context_dir(transaction_run), agents=False) == []
    )
    transaction_retry_batch = delegate_ready_lanes(
        transaction_run, runtime_slots=2, request_budget=0,
        model_egress_budget=0, merge_capacity=10, limit=2,
    )
    committed_transaction = _load_delegate_transaction(transaction_run) or {}
    retry_commits_complete_batch = (
        [item.get("lane_id") for item in transaction_retry_batch["assignments"]]
        == ["L-FIRST", "L-SECOND"]
        and len(load_assignments(transaction_run)["assignments"]) == 2
        and len(_transaction_file_snapshot(
            agents_dir(transaction_run), agents=True)) == 2
        and len(_transaction_file_snapshot(
            context_dir(transaction_run), agents=False)) == 2
        and committed_transaction.get("status") == "committed"
        and committed_transaction.get("transaction_id")
        == transaction_retry_batch.get("transaction_id")
    )

    crash_run = build_delegate_transaction_run(
        "delegate-transaction-crash-recovery", "b")

    def crash_after_first_assignment(phase: str) -> None:
        if phase == "after_assignment_1":
            raise KeyboardInterrupt("simulated process interruption")

    simulated_crash_seen = False
    try:
        delegate_ready_lanes(
            crash_run, runtime_slots=2, request_budget=0,
            model_egress_budget=0, merge_capacity=10, limit=2,
            fault=crash_after_first_assignment,
        )
    except KeyboardInterrupt:
        simulated_crash_seen = True
    prepared_after_crash = _load_delegate_transaction(crash_run) or {}
    recovery_entry_rejected_invalid_assignment = False
    try:
        create_agent_assignment(
            crash_run, role="unknown-role", front="F-030",
            lane_id="L-FIRST",
        )
    except ValueError as exc:
        recovery_entry_rejected_invalid_assignment = "unknown Agent role" in str(exc)
    rolled_back_after_crash = _load_delegate_transaction(crash_run) or {}
    crash_recovery_is_idempotent = (
        simulated_crash_seen
        and prepared_after_crash.get("status") == "prepared"
        and recovery_entry_rejected_invalid_assignment
        and rolled_back_after_crash.get("status") == "rolled_back"
        and not _assignments_path(crash_run).exists()
        and _transaction_file_snapshot(agents_dir(crash_run), agents=True) == []
        and _transaction_file_snapshot(context_dir(crash_run), agents=False) == []
    )
    # A second entry sees an already rolled-back receipt and must remain a no-op
    # before validating the newly requested assignment.
    try:
        create_agent_assignment(
            crash_run, role="unknown-role", front="F-030",
            lane_id="L-FIRST",
        )
    except ValueError:
        pass
    crash_retry_batch = delegate_ready_lanes(
        crash_run, runtime_slots=2, request_budget=0,
        model_egress_budget=0, merge_capacity=10, limit=2,
    )
    crash_retry_is_complete = (
        [item.get("lane_id") for item in crash_retry_batch["assignments"]]
        == ["L-FIRST", "L-SECOND"]
        and len(load_assignments(crash_run)["assignments"]) == 2
        and (_load_delegate_transaction(crash_run) or {}).get("status")
        == "committed"
    )

    cancellation_run = build_delegate_transaction_run(
        "delegate-stale-unlaunched-cancellation", "c")
    cancellation_batch = delegate_ready_lanes(
        cancellation_run, runtime_slots=2, request_budget=0,
        model_egress_budget=0, merge_capacity=10, limit=2,
    )
    cancellation_old_prompts = {
        item["assignment"]: item["launch_prompt"]
        for item in cancellation_batch["assignments"]
    }
    (cancellation_run / "hints.md").write_text(
        "# Hints\n\n- Steering changed before either Agent launch.\n",
        encoding="utf-8",
    )
    cancellation_receipts = [
        cancel_unlaunched_assignment(
            cancellation_run, item["assignment"],
            reason="canonical steering changed before launch",
        )
        for item in cancellation_batch["assignments"]
    ]
    turn_stale_cancellation_run = build_delegate_transaction_run(
        "delegate-turn-stale-unlaunched-cancellation", "d")
    turn_stale_batch = delegate_ready_lanes(
        turn_stale_cancellation_run, runtime_slots=1, request_budget=0,
        model_egress_budget=0, merge_capacity=10, limit=1,
    )
    turn_stale_assignment = turn_stale_batch["assignments"][0]["assignment"]
    turn_stale_contract_path = (
        turn_stale_cancellation_run / "state" / "turn_contract.json")
    turn_stale_contract = json.loads(
        turn_stale_contract_path.read_text(encoding="utf-8"))
    turn_stale_contract["prompt_sha256"] = "e" * 64
    turn_stale_contract["updated_at"] = (
        float(turn_stale_contract["updated_at"]) + 1.0)
    _atomic_write(
        turn_stale_contract_path,
        json.dumps(turn_stale_contract, ensure_ascii=False, indent=2) + "\n",
    )
    turn_stale_receipt = cancel_unlaunched_assignment(
        turn_stale_cancellation_run,
        turn_stale_assignment,
        reason="new operator turn superseded authority before launch",
    )
    both_stale_cancellation_run = build_delegate_transaction_run(
        "delegate-turn-and-input-stale-unlaunched-cancellation", "e")
    both_stale_batch = delegate_ready_lanes(
        both_stale_cancellation_run, runtime_slots=1, request_budget=0,
        model_egress_budget=0, merge_capacity=10, limit=1,
    )
    both_stale_assignment = both_stale_batch["assignments"][0]["assignment"]
    (both_stale_cancellation_run / "hints.md").write_text(
        "# Hints\n\n- Steering and operator turn changed before Agent launch.\n",
        encoding="utf-8",
    )
    both_stale_contract_path = (
        both_stale_cancellation_run / "state" / "turn_contract.json")
    both_stale_contract = json.loads(
        both_stale_contract_path.read_text(encoding="utf-8"))
    both_stale_contract["prompt_sha256"] = "f" * 64
    both_stale_contract["updated_at"] = (
        float(both_stale_contract["updated_at"]) + 1.0)
    _atomic_write(
        both_stale_contract_path,
        json.dumps(both_stale_contract, ensure_ascii=False, indent=2) + "\n",
    )
    both_stale_receipt = cancel_unlaunched_assignment(
        both_stale_cancellation_run,
        both_stale_assignment,
        reason="canonical inputs and operator turn changed before launch",
    )
    valid_v2_cancellation_transaction = _agent_settlement.load_transaction(
        turn_stale_cancellation_run)
    v1_transaction_with_v2_tombstone = json.loads(json.dumps(
        valid_v2_cancellation_transaction))
    v1_transaction_with_v2_tombstone["schema"] = (
        _agent_settlement.LEGACY_CANCELLATION_TRANSACTION_SCHEMA)
    v1_transaction_with_v2_tombstone_rejected = False
    try:
        _agent_settlement.validate_transaction(
            v1_transaction_with_v2_tombstone)
    except _agent_settlement.SettlementError as exc:
        v1_transaction_with_v2_tombstone_rejected = (
            str(exc)
            == "ASSIGNMENT_CANCELLATION_TRANSACTION_VERSION_DIVERGED")

    legacy_tombstone = {
        key: value for key, value in turn_stale_receipt.items()
        if key in _agent_settlement.LEGACY_CANCELLATION_FIELDS
    }
    legacy_tombstone["schema"] = _agent_settlement.LEGACY_CANCELLATION_SCHEMA
    legacy_identity = {
        "plan_digest": legacy_tombstone["plan_digest"],
        "lane_id": legacy_tombstone["lane_id"],
        "assignment": legacy_tombstone["assignment"],
        "assignment_attempt": legacy_tombstone["assignment_attempt"],
        "assignment_row_sha256": legacy_tombstone[
            "assignment_row_sha256"],
        "delegate_transaction_id": legacy_tombstone[
            "delegate_transaction_id"],
        "observed_inputs_digest": legacy_tombstone[
            "observed_inputs_digest"],
        "cancelled_at": legacy_tombstone["cancelled_at"],
    }
    legacy_tombstone["cancellation_id"] = hashlib.sha256(
        _agent_settlement._json_bytes(legacy_identity)).hexdigest()
    legacy_tombstone["receipt_digest"] = (
        _agent_settlement._digest_without(
            legacy_tombstone, "receipt_digest"))
    _agent_settlement.validate_cancellation(legacy_tombstone)
    v2_transaction_with_v1_tombstone = json.loads(json.dumps(
        valid_v2_cancellation_transaction))
    v2_transaction_with_v1_tombstone["tombstone"] = legacy_tombstone
    v2_transaction_with_v1_tombstone_rejected = False
    try:
        _agent_settlement.validate_transaction(
            v2_transaction_with_v1_tombstone)
    except _agent_settlement.SettlementError as exc:
        v2_transaction_with_v1_tombstone_rejected = (
            str(exc)
            == "ASSIGNMENT_CANCELLATION_TRANSACTION_VERSION_DIVERGED")
    cancellation_cross_version_mixes_rejected = bool(
        v1_transaction_with_v2_tombstone_rejected
        and v2_transaction_with_v1_tombstone_rejected
    )
    cancellation_cli_output = io.StringIO()
    with contextlib.redirect_stdout(cancellation_cli_output):
        cancellation_cli_exit = print_cancel_unlaunched(
            turn_stale_cancellation_run,
            turn_stale_assignment,
            "new operator turn superseded authority before launch",
        )
    cancellation_cli_preserves_open_front = bool(
        cancellation_cli_exit == 0
        and "settled assignment debt only" in cancellation_cli_output.getvalue()
        and "keep front F-030 open" in cancellation_cli_output.getvalue()
        and "not a result" in cancellation_cli_output.getvalue()
        and "authority to close the front" in cancellation_cli_output.getvalue()
    )
    turn_stale_cancellation_is_typed = bool(
        turn_stale_receipt.get("schema")
            == "xunji.assignment-cancellation.v2"
        and turn_stale_receipt.get("stale_basis") == "turn"
        and turn_stale_receipt.get("plan_inputs_digest")
            == turn_stale_receipt.get("observed_inputs_digest")
        and turn_stale_receipt.get("plan_turn_binding")
            != turn_stale_receipt.get("observed_turn_binding")
        and not any(
            item.get("agent") == turn_stale_assignment
            for item in load_assignments(
                turn_stale_cancellation_run)["assignments"]
        )
    )
    both_stale_cancellation_is_typed = bool(
        both_stale_receipt.get("schema")
            == "xunji.assignment-cancellation.v2"
        and both_stale_receipt.get("stale_basis") == "both"
        and both_stale_receipt.get("plan_inputs_digest")
            != both_stale_receipt.get("observed_inputs_digest")
        and both_stale_receipt.get("plan_turn_binding")
            != both_stale_receipt.get("observed_turn_binding")
        and not any(
            item.get("agent") == both_stale_assignment
            for item in load_assignments(
                both_stale_cancellation_run)["assignments"]
        )
    )
    cancellation_projection = _run_model.plan_cycle_projection(
        cancellation_run,
        plan=_work_plan.transaction_bound_plan(cancellation_run),
    )
    cancellation_rows_after_cancel = load_assignments(
        cancellation_run)["assignments"]
    cancellation_cycle_end_blocked = False
    cancellation_cycle_end_code = ""
    try:
        _loop_journal.append_event(
            cancellation_run, "cycle_end",
            next_action="运行 check_run 验证当前计划",
        )
    except _loop_journal.JournalContractError as exc:
        cancellation_cycle_end_code = exc.code
        cancellation_cycle_end_blocked = (
            exc.code == "CYCLE_EVENT_PLAN_DEBT_OPEN")
    cancellation_schema = json.loads((
        ROOT / "contracts" / "assignment-cancellation.v2.schema.json"
    ).read_text(encoding="utf-8", errors="strict"))

    def cancellation_schema_errors(value: object) -> list[str]:
        if _runtime_receipts is None \
                or not hasattr(_runtime_receipts, "_selftest_schema_errors"):
            return ["runtime schema selftest validator unavailable"]
        return _runtime_receipts._selftest_schema_errors(
            value, cancellation_schema)

    cancellation_unknown = json.loads(json.dumps(cancellation_receipts[0]))
    cancellation_unknown["untrusted_extra"] = True
    cancellation_archive = _agent_settlement.cancellation_archive_dir(
        cancellation_run)
    cancellation_temp = cancellation_run / "state" / (
        "." + cancellation_receipts[0]["receipt_digest"]
        + ".json.active-writer.tmp")
    cancellation_temp.write_text("active writer temporary", encoding="utf-8")
    cancellation_after_temp_cleanup = _agent_settlement.cancellation_receipts(
        cancellation_run)
    durability_mkdir_target = (
        d / "cancellation-durability-mkdir" / "archive" / "receipt.json")
    original_path_mkdir = Path.mkdir

    def fail_exact_cancellation_parent_mkdir(
        path: Path, mode: int = 0o777, parents: bool = False,
        exist_ok: bool = False,
    ) -> None:
        if Path(path) == durability_mkdir_target.parent:
            raise OSError("simulated cancellation parent mkdir failure")
        original_path_mkdir(
            path, mode=mode, parents=parents, exist_ok=exist_ok)

    durability_mkdir_mapped = False
    try:
        with mock.patch.object(
                Path, "mkdir", new=fail_exact_cancellation_parent_mkdir):
            _agent_settlement.durable_atomic_text(
                durability_mkdir_target, "must not publish\n")
    except _agent_settlement.SettlementError as exc:
        durability_mkdir_mapped = str(exc) \
            == "ASSIGNMENT_CANCELLATION_DURABILITY_FAILED:OSError"

    durability_parent_target = (
        d / "cancellation-durability-parent" / "archive" / "receipt.json")
    original_settlement_fsync_for_parent = _agent_settlement._fsync_directory
    durability_parent_barrier_calls: list[Path] = []

    def fail_new_parent_barrier(path: Path) -> None:
        durability_parent_barrier_calls.append(Path(path))
        if Path(path) == durability_parent_target.parent.parent:
            raise OSError("simulated new parent entry fsync failure")
        original_settlement_fsync_for_parent(path)

    durability_parent_barrier_mapped = False
    try:
        with mock.patch.object(
                _agent_settlement, "_fsync_directory",
                side_effect=fail_new_parent_barrier):
            _agent_settlement.durable_atomic_text(
                durability_parent_target, "first attempt\n")
    except _agent_settlement.SettlementError as exc:
        durability_parent_barrier_mapped = str(exc) \
            == "ASSIGNMENT_CANCELLATION_DURABILITY_FAILED:OSError"
    _agent_settlement.durable_atomic_text(
        durability_parent_target, "durable retry\n")
    cancellation_parent_durability_failures_stable = bool(
        durability_mkdir_mapped and not durability_mkdir_target.exists()
        and durability_parent_barrier_mapped
        and durability_parent_barrier_calls
        and durability_parent_barrier_calls[0]
            == durability_parent_target.parent.parent
        and durability_parent_target.read_text(encoding="utf-8")
            == "durable retry\n"
    )
    cancellation_lanes = json.loads(json.dumps(
        _work_plan.transaction_bound_plan(cancellation_run)["lanes"]))
    cancellation_replan = _work_plan.commit_plan(
        cancellation_run, macro_stage="S2",
        objective="rebind work after typed unlaunched cancellation",
        mode="PARALLEL_AGENTS",
        reason="old assignments were never launched and are tombstoned",
        exit_gate="new exact results receive Reviewer dispositions",
        lanes=cancellation_lanes,
        replan_reason="canonical steering changed before the old Agent calls",
        contract=_work_plan._load_turn_contract(cancellation_run),
    )
    cancellation_new_batch = delegate_ready_lanes(
        cancellation_run, runtime_slots=2, request_budget=0,
        model_egress_budget=0, merge_capacity=10, limit=2,
    )
    cancellation_new_ids = {
        item["assignment"] for item in cancellation_new_batch["assignments"]
    }
    cancellation_old_ids = set(cancellation_old_prompts)

    cancellation_crash_results: list[bool] = []
    cancellation_crash_runtime_barriers: list[bool] = []
    cancellation_crash_replan_barriers: list[bool] = []
    for crash_index, (crash_stage, crash_token) in enumerate(zip((
        "after_prepared", "after_tombstone", "after_agent_unlink",
        "after_context_unlink", "after_assignments_replace", "after_committed",
    ), "345678"), start=1):
        cancellation_crash_run = build_delegate_transaction_run(
            f"cancellation-crash-{crash_index}", crash_token)
        crash_batch = delegate_ready_lanes(
            cancellation_crash_run, runtime_slots=1, request_budget=0,
            model_egress_budget=0, merge_capacity=10, limit=1,
        )
        crash_assignment = crash_batch["assignments"][0]["assignment"]
        (cancellation_crash_run / "hints.md").write_text(
            f"# Hints\n\n- Crash fixture {crash_stage}.\n", encoding="utf-8")

        def cancellation_crash(phase: str, *, selected: str = crash_stage) -> None:
            if phase == selected:
                raise RuntimeError(f"simulated cancellation crash at {phase}")

        crashed = False
        try:
            cancel_unlaunched_assignment(
                cancellation_crash_run, crash_assignment,
                reason="crash recovery fixture", fault=cancellation_crash)
        except RuntimeError as exc:
            crashed = "simulated cancellation crash" in str(exc)
        exercise_race = crash_stage in {
            "after_prepared", "after_agent_unlink", "after_assignments_replace",
        }
        if exercise_race:
            crash_plan = _work_plan.transaction_bound_plan(
                cancellation_crash_run)
            replan_blocked = False
            try:
                _work_plan.commit_plan(
                    cancellation_crash_run, macro_stage="S2",
                    objective="must not replan across prepared cancellation",
                    mode=str(crash_plan["execution_mode"]),
                    reason="recovery fixture must remain serialized",
                    exit_gate="prepared cancellation first reaches a terminal fact",
                    lanes=json.loads(json.dumps(crash_plan["lanes"])),
                    replan_reason="attempted during prepared cancellation",
                    contract=_work_plan._load_turn_contract(
                        cancellation_crash_run),
                )
            except _work_plan.PlanError as exc:
                replan_blocked = str(exc) \
                    == "WORK_PLAN_ASSIGNMENT_CANCELLATION_RECOVERY_REQUIRED"
            cancellation_crash_replan_barriers.append(replan_blocked)
            before_events = len(_runtime_receipts.validate_chain(
                cancellation_crash_run)[0])
            before_result_files = list((
                cancellation_crash_run / "state" / "merge_results"
                / crash_assignment).glob("*.json"))

            def append_late_failure() -> bool:
                try:
                    _runtime_receipts.append_hook_event(
                        cancellation_crash_run, {
                            "hook_event_name": "PostToolUseFailure",
                            "session_id": "transaction-v",
                            "transcript_path": str(Path(
                                _work_plan._load_turn_contract(
                                    cancellation_crash_run)["transcript_path"])),
                            "tool_name": "Agent",
                            "tool_use_id": f"late-{crash_stage}",
                            "tool_input": {
                                "prompt": crash_batch["assignments"][0][
                                    "launch_prompt"],
                                "subagent_type": crash_batch["assignments"][0][
                                    "subagent_type"],
                            },
                            "tool_response": {"error": "late launch failure"},
                        })
                except Exception as exc:
                    return "ASSIGNMENT_CANCELLATION_RUNTIME_BARRIER" in str(exc)
                return False

            with ThreadPoolExecutor(max_workers=2) as executor:
                late_future = executor.submit(append_late_failure)
                recovery_future = executor.submit(
                    cancel_unlaunched_assignment,
                    cancellation_crash_run, crash_assignment,
                    reason="concurrent exact retry completes frozen cancellation",
                )
                late_blocked = late_future.result()
                recovered = recovery_future.result()
            after_events = len(_runtime_receipts.validate_chain(
                cancellation_crash_run)[0])
            after_result_files = list((
                cancellation_crash_run / "state" / "merge_results"
                / crash_assignment).glob("*.json"))
            cancellation_crash_runtime_barriers.append(bool(
                late_blocked and before_events == after_events
                and before_result_files == after_result_files == []
            ))
        else:
            recovered = cancel_unlaunched_assignment(
                cancellation_crash_run, crash_assignment,
                reason="exact retry completes frozen cancellation")
        recovered_transaction = _agent_settlement.load_transaction(
            cancellation_crash_run) or {}
        cancellation_crash_results.append(bool(
            crashed
            and recovered.get("status") == "cancelled-unlaunched"
            and recovered_transaction.get("status") == "committed"
            and not load_assignments(cancellation_crash_run)["assignments"]
            and not (agents_dir(cancellation_crash_run)
                     / f"{crash_assignment}.md").exists()
            and len(_agent_settlement.cancellation_receipts(
                cancellation_crash_run)) == 1
        ))

    late_start_run = build_delegate_transaction_run(
        "cancellation-late-start-after-prepare", "2")
    late_start_batch = delegate_ready_lanes(
        late_start_run, runtime_slots=1, request_budget=0,
        model_egress_budget=0, merge_capacity=10, limit=1,
    )
    late_start_assignment = late_start_batch["assignments"][0]
    (late_start_run / "hints.md").write_text(
        "# Hints\n\n- Freeze cancellation before a late child Start.\n",
        encoding="utf-8")

    def stop_late_start_cancellation(phase: str) -> None:
        if phase == "after_prepared":
            raise RuntimeError("simulated cancellation crash before late Start")

    late_start_prepared = False
    try:
        cancel_unlaunched_assignment(
            late_start_run, late_start_assignment["assignment"],
            reason="prepare a transcript TOCTOU fixture",
            fault=stop_late_start_cancellation)
    except RuntimeError as exc:
        late_start_prepared = "before late Start" in str(exc)
    late_start_contract = _work_plan._load_turn_contract(late_start_run)
    late_start_transcript = Path(late_start_contract["transcript_path"])
    late_start_tool_id = "late-start-tool-use"
    late_start_transcript.write_text(json.dumps({
        "message": {"role": "assistant", "content": [{
            "type": "tool_use", "id": late_start_tool_id,
            "name": "Agent", "input": {
                "prompt": late_start_assignment["launch_prompt"],
                "subagent_type": late_start_assignment["subagent_type"],
            },
        }]},
    }) + "\n", encoding="utf-8")
    late_start_events_before = len(_runtime_receipts.validate_chain(
        late_start_run)[0])
    late_start_runtime_blocked = False
    try:
        _runtime_receipts.append_hook_event(late_start_run, {
            "hook_event_name": "SubagentStart",
            "session_id": late_start_contract["session_id"],
            "transcript_path": str(late_start_transcript),
            "agent_id": "late-child-after-cancellation",
            "agent_type": late_start_assignment["subagent_type"],
        })
    except Exception as exc:
        late_start_runtime_blocked = \
            "ASSIGNMENT_CANCELLATION_RUNTIME_BARRIER" in str(exc)
    late_start_recovery_blocked = False
    try:
        cancel_unlaunched_assignment(
            late_start_run, late_start_assignment["assignment"],
            reason="must retain prepared debt after transcript growth")
    except ValueError as exc:
        late_start_recovery_blocked = \
            "ASSIGNMENT_CANCELLATION_TRANSCRIPT_LAUNCH_EXISTS" in str(exc)
    late_start_transaction = _agent_settlement.load_transaction(
        late_start_run) or {}
    late_start_toctou_fail_closed = bool(
        late_start_prepared and late_start_runtime_blocked
        and late_start_recovery_blocked
        and len(_runtime_receipts.validate_chain(late_start_run)[0])
            == late_start_events_before
        and late_start_transaction.get("status") == "prepared"
        and any(
            row.get("agent") == late_start_assignment["assignment"]
            for row in load_assignments(late_start_run)["assignments"]
        )
    )

    unlink_barrier_run = build_delegate_transaction_run(
        "cancellation-unlink-barrier-retry", "9")
    unlink_batch = delegate_ready_lanes(
        unlink_barrier_run, runtime_slots=1, request_budget=0,
        model_egress_budget=0, merge_capacity=10, limit=1,
    )
    unlink_assignment = unlink_batch["assignments"][0]["assignment"]
    (unlink_barrier_run / "hints.md").write_text(
        "# Hints\n\n- Exercise unlink directory durability retry.\n",
        encoding="utf-8")
    original_settlement_fsync = _agent_settlement._fsync_directory
    unlink_barrier_failed = {"value": False}

    def fail_first_agent_unlink_barrier(path: Path) -> None:
        if Path(path).resolve() == agents_dir(unlink_barrier_run).resolve() \
                and not unlink_barrier_failed["value"]:
            unlink_barrier_failed["value"] = True
            raise OSError("simulated agent unlink parent fsync failure")
        original_settlement_fsync(path)

    try:
        with mock.patch.object(
                _agent_settlement, "_fsync_directory",
                side_effect=fail_first_agent_unlink_barrier):
            cancel_unlaunched_assignment(
                unlink_barrier_run, unlink_assignment,
                reason="unlink barrier retry fixture")
    except OSError:
        pass
    unlink_missing_before_retry = not (
        agents_dir(unlink_barrier_run) / f"{unlink_assignment}.md").exists()
    unlink_recovered = cancel_unlaunched_assignment(
        unlink_barrier_run, unlink_assignment,
        reason="retry repeats missing artifact directory barrier")
    unlink_barrier_retry_complete = bool(
        unlink_barrier_failed["value"] and unlink_missing_before_retry
        and unlink_recovered.get("status") == "cancelled-unlaunched"
        and (_agent_settlement.load_transaction(unlink_barrier_run) or {}).get(
            "status") == "committed"
    )

    transcript_launch_run = build_delegate_transaction_run(
        "cancellation-transcript-launch-intent", "0")
    transcript_launch_batch = delegate_ready_lanes(
        transcript_launch_run, runtime_slots=1, request_budget=0,
        model_egress_budget=0, merge_capacity=10, limit=1,
    )
    transcript_launch = transcript_launch_batch["assignments"][0]
    transcript_path = Path(_work_plan._load_turn_contract(
        transcript_launch_run)["transcript_path"])
    transcript_path.write_text(json.dumps({
        "message": {"role": "assistant", "content": [{
            "type": "tool_use", "id": "already-authorized-agent",
            "name": "Agent", "input": {
                "prompt": transcript_launch["launch_prompt"],
                "subagent_type": transcript_launch["subagent_type"],
            },
        }]},
    }) + "\n", encoding="utf-8")
    (transcript_launch_run / "hints.md").write_text(
        "# Hints\n\n- Too late: Agent tool_use already exists.\n",
        encoding="utf-8")
    transcript_launch_cancel_blocked = False
    try:
        cancel_unlaunched_assignment(
            transcript_launch_run, transcript_launch["assignment"],
            reason="must reject a pre-authorized Agent tool_use")
    except ValueError as exc:
        transcript_launch_cancel_blocked = (
            "TRANSCRIPT_LAUNCH_EXISTS" in str(exc))

    denied_launch_run = build_delegate_transaction_run(
        "cancellation-pretool-denied-agent", "7",
        include_target_lane=True)
    denied_launch_batch = delegate_ready_lanes(
        denied_launch_run, runtime_slots=1, request_budget=0,
        model_egress_budget=0, merge_capacity=10, limit=1,
    )
    denied_launch = denied_launch_batch["assignments"][0]
    denied_contract = _work_plan._load_turn_contract(denied_launch_run)
    denied_transcript = Path(denied_contract["transcript_path"])
    denied_tool_id = "pretool-denied-agent"
    denied_transcript.write_text(json.dumps({
        "message": {"role": "assistant", "content": [{
            "type": "tool_use", "id": denied_tool_id, "name": "Agent",
            "input": {
                "prompt": denied_launch["launch_prompt"],
                "subagent_type": denied_launch["subagent_type"],
            },
        }, {
            "type": "tool_result", "tool_use_id": denied_tool_id,
            "content": {"decision": "deny", "reason": "turn mode changed"},
        }]},
    }) + "\n", encoding="utf-8")
    denied_receipt = _runtime_receipts.append_hook_event(
        denied_launch_run, {
            "hook_event_name": "PreToolUseDenied",
            "session_id": denied_contract["session_id"],
            "transcript_path": str(denied_transcript),
            "tool_name": "Agent",
            "tool_use_id": denied_tool_id,
            "tool_input": {
                "prompt": denied_launch["launch_prompt"],
                "subagent_type": denied_launch["subagent_type"],
            },
            "tool_response": {
                "decision": "deny", "reason": "turn mode changed"},
            "xunji_decision": "deny",
        })
    denied_contract["target_egress_denied"] = True
    _atomic_write(
        denied_launch_run / "state" / "turn_contract.json",
        json.dumps(denied_contract, ensure_ascii=False, indent=2) + "\n",
    )
    (denied_launch_run / "hints.md").write_text(
        "# Hints\n\n- Denied Agent call never crossed launch boundary.\n",
        encoding="utf-8")
    denied_launch_receipt = cancel_unlaunched_assignment(
        denied_launch_run, denied_launch["assignment"],
        reason="exact PreToolUse denial proves the assignment never launched")
    denied_launch_cancellation_allowed = bool(
        denied_receipt.get("hook_event_name") == "PreToolUseDenied"
        and denied_receipt.get("decision") == "deny"
        and any(
            lane.get("effect") == "target"
            for lane in _work_plan.transaction_bound_plan(
                denied_launch_run).get("lanes", [])
        )
        and denied_launch_receipt.get("status") == "cancelled-unlaunched"
        and not load_assignments(denied_launch_run)["assignments"]
        and any(
            item.get("tool_use_id") == denied_tool_id
            for item in _runtime_receipts.validate_chain(
                denied_launch_run)[0]
        )
    )

    runtime_launch_run = build_delegate_transaction_run(
        "cancellation-runtime-event", "1")
    runtime_launch_batch = delegate_ready_lanes(
        runtime_launch_run, runtime_slots=1, request_budget=0,
        model_egress_budget=0, merge_capacity=10, limit=1,
    )
    runtime_launch = runtime_launch_batch["assignments"][0]
    runtime_transcript = Path(_work_plan._load_turn_contract(
        runtime_launch_run)["transcript_path"])
    runtime_tool_id = "runtime-failed-agent"
    runtime_transcript.write_text(json.dumps({
        "message": {"role": "assistant", "content": [{
            "type": "tool_use", "id": runtime_tool_id, "name": "Agent",
            "input": {
                "prompt": runtime_launch["launch_prompt"],
                "subagent_type": runtime_launch["subagent_type"],
            },
        }, {
            "type": "tool_result", "tool_use_id": runtime_tool_id,
            "content": {"error": "launch failed"},
        }]},
    }) + "\n", encoding="utf-8")
    _runtime_receipts.append_hook_event(runtime_launch_run, {
        "hook_event_name": "PostToolUseFailure", "session_id": "transaction-v",
        "transcript_path": str(runtime_transcript), "tool_name": "Agent",
        "tool_use_id": runtime_tool_id,
        "tool_input": {
            "prompt": runtime_launch["launch_prompt"],
            "subagent_type": runtime_launch["subagent_type"],
        },
        "tool_response": {"error": "launch failed"},
    })
    (runtime_launch_run / "hints.md").write_text(
        "# Hints\n\n- Failed execution requires Reviewer settlement.\n",
        encoding="utf-8")
    runtime_event_cancel_blocked = False
    try:
        cancel_unlaunched_assignment(
            runtime_launch_run, runtime_launch["assignment"],
            reason="must not cancel failed execution")
    except ValueError as exc:
        runtime_event_cancel_blocked = any(token in str(exc) for token in (
            "NOT_UNLAUNCHED", "RUNTIME_STATE_EXISTS", "RUNTIME_EVENT_EXISTS"))

    def exact_replay_fixture(kind: str, *, tombstone: bool) -> bool:
        replay_run = d / f"agent-exact-replay-{kind}-tombstone-{int(tombstone)}"
        (replay_run / "state").mkdir(parents=True)
        replay_run = replay_run.resolve()
        (replay_run / "agents").mkdir()
        (replay_run / "context").mkdir()
        assignment = f"A-replay-{kind}-{int(tombstone)}"
        plan_digest = hashlib.sha256(
            f"replay-plan-{kind}-{tombstone}".encode()).hexdigest()
        prompt = (
            f"XUNJI_ASSIGNMENT={assignment}\n"
            "XUNJI_FRONT=F-030\n"
        )
        subagent_type = "xunji-hunter"
        transcript = replay_run / "parent-transcript.jsonl"
        tool_id = f"tool-{kind}-{int(tombstone)}"
        transcript.write_text(json.dumps({
            "message": {"role": "assistant", "content": [{
                "type": "tool_use", "id": tool_id, "name": "Agent",
                "input": {
                    "prompt": prompt,
                    "subagent_type": subagent_type,
                },
            }]},
        }) + "\n", encoding="utf-8")
        session_id = f"replay-{kind}-{int(tombstone)}"
        agent_id = f"child-{kind}-{int(tombstone)}"
        start_event = {
            "hook_event_name": "SubagentStart", "session_id": session_id,
            "transcript_path": str(transcript), "agent_id": agent_id,
            "agent_type": subagent_type,
        }
        if kind == "start":
            target_event = start_event
        elif kind == "stop":
            _runtime_receipts.append_hook_event(replay_run, start_event)
            target_event = {
                "hook_event_name": "SubagentStop", "session_id": session_id,
                "transcript_path": str(transcript), "agent_id": agent_id,
                "agent_type": subagent_type,
                "last_assistant_message": "exact stopped result",
            }
        elif kind == "async-post":
            target_event = {
                "hook_event_name": "PostToolUse", "session_id": session_id,
                "transcript_path": str(transcript), "tool_name": "Agent",
                "tool_use_id": tool_id, "tool_input": {
                    "prompt": prompt,
                    "subagent_type": subagent_type,
                },
                "tool_response": {
                    "agentId": agent_id, "isAsync": True,
                    "status": "async_launched"},
            }
        elif kind == "sync-post":
            target_event = {
                "hook_event_name": "PostToolUse", "session_id": session_id,
                "transcript_path": str(transcript), "tool_name": "Agent",
                "tool_use_id": tool_id, "tool_input": {
                    "prompt": prompt,
                    "subagent_type": subagent_type,
                },
                "tool_response": {"content": "exact sync completion"},
            }
        else:
            target_event = {
                "hook_event_name": "PostToolUseFailure",
                "session_id": session_id, "transcript_path": str(transcript),
                "tool_name": "Agent", "tool_use_id": tool_id,
                "tool_input": {
                    "prompt": prompt,
                    "subagent_type": subagent_type,
                },
                "tool_response": {"error": "exact launch failure"},
            }
        original = _runtime_receipts.append_hook_event(
            replay_run, target_event)
        if tombstone:
            agent_file = replay_run / "agents" / f"{assignment}.md"
            context_file = replay_run / "context" / f"{assignment}.md"
            agent_file.write_text("frozen replay agent\n", encoding="utf-8")
            context_file.write_text("frozen replay context\n", encoding="utf-8")
            transcript_payload = transcript.read_bytes()
            cancelled_at = datetime.now(timezone.utc).isoformat(
                timespec="milliseconds").replace("+00:00", "Z")
            cancellation_turn = {
                "session_id": session_id,
                "prompt_sha256": "c" * 64,
                "contract_updated_at": time.time(),
            }
            receipt = _agent_settlement.build_cancellation(
                plan_id="WP-1-replay", plan_digest=plan_digest,
                plan_inputs_digest="a" * 64,
                observed_inputs_digest="b" * 64,
                stale_basis="inputs",
                plan_turn_binding=cancellation_turn,
                observed_turn_binding=cancellation_turn,
                lane_id="L-REPLAY", assignment=assignment,
                assignment_attempt=1, role="web-hunter", front="F-030",
                effect="local_read", assets=[],
                reason="exact replay precedence fixture",
                cancelled_at=cancelled_at,
                turn_binding={
                    **cancellation_turn,
                    "transcript_path": str(transcript.resolve()),
                    "transcript_length": len(transcript_payload),
                    "transcript_prefix_sha256": hashlib.sha256(
                        transcript_payload).hexdigest(),
                },
                assignment_row_sha256="d" * 64,
                delegate_transaction_id="e" * 64,
                delegate_receipt_digest="f" * 64,
                agent_artifact=_agent_settlement.freeze_artifact(
                    replay_run, agent_file, directory="agents",
                    pattern=r"A-[A-Za-z0-9._-]+\.md"),
                context_artifact=_agent_settlement.freeze_artifact(
                    replay_run, context_file, directory="context",
                    pattern=r"[^/\\]+\.md"),
            )
            _agent_settlement.archive_cancellation(replay_run, receipt)
        before_events = _runtime_receipts.validate_chain(replay_run)[0]
        before_results = sorted(str(path) for path in (
            replay_run / "state" / "merge_results").glob("**/*.json"))
        replayed = _runtime_receipts.append_hook_event(
            replay_run, json.loads(json.dumps(target_event)))
        conflict = json.loads(json.dumps(target_event))
        if kind == "start":
            conflict["agent_type"] = "changed-agent-type"
        elif kind == "stop":
            conflict["last_assistant_message"] = "different stopped result"
        elif kind == "async-post":
            conflict["tool_response"]["status"] = "different-status"
        elif kind == "sync-post":
            conflict["tool_response"]["content"] = "different completion"
        else:
            conflict["tool_response"]["error"] = "different failure"
        conflict_blocked = False
        try:
            _runtime_receipts.append_hook_event(replay_run, conflict)
        except RuntimeError as exc:
            conflict_blocked = "AGENT_EVENT_REPLAY_CONFLICT" in str(exc)
        after_events = _runtime_receipts.validate_chain(replay_run)[0]
        after_results = sorted(str(path) for path in (
            replay_run / "state" / "merge_results").glob("**/*.json"))
        return bool(
            replayed.get("receipt_hash") == original.get("receipt_hash")
            and conflict_blocked and after_events == before_events
            and after_results == before_results
        )

    exact_replay_kinds = (
        "start", "stop", "async-post", "sync-post", "failure",
    )
    exact_replay_without_tombstone = [
        exact_replay_fixture(kind, tombstone=False)
        for kind in exact_replay_kinds
    ]
    exact_replay_with_tombstone = [
        exact_replay_fixture(kind, tombstone=True)
        for kind in exact_replay_kinds
    ]

    failed_settlement_run = build_delegate_transaction_run(
        "delegate-stale-failed-settlement", "f")
    failed_execution_batch = delegate_ready_lanes(
        failed_settlement_run, runtime_slots=1, request_budget=0,
        model_egress_budget=0, merge_capacity=10, limit=1,
    )
    failed_execution = failed_execution_batch["assignments"][0]
    failed_tool_id = "stale-failed-execution-tool"
    failed_transcript = failed_settlement_run / "failed-transcript.jsonl"
    failed_transcript.write_text(json.dumps({
        "message": {"role": "assistant", "content": [{
            "type": "tool_use", "id": failed_tool_id, "name": "Agent",
            "input": {
                "prompt": failed_execution["launch_prompt"],
                "subagent_type": failed_execution["subagent_type"],
            },
        }]},
    }) + "\n", encoding="utf-8")
    _runtime_receipts.append_hook_event(failed_settlement_run, {
        "hook_event_name": "PostToolUseFailure",
        "session_id": "transaction-f",
        "transcript_path": str(failed_transcript),
        "tool_name": "Agent",
        "tool_use_id": failed_tool_id,
        "tool_input": {
            "prompt": failed_execution["launch_prompt"],
            "subagent_type": failed_execution["subagent_type"],
        },
        "tool_response": {"error": "Agent launch failed before execution"},
    })
    (failed_settlement_run / "hints.md").write_text(
        "# Hints\n\n- Replan only after the failed result is reviewed.\n",
        encoding="utf-8",
    )
    failed_reviewer_batch = delegate_ready_lanes(
        failed_settlement_run, runtime_slots=2, request_budget=0,
        model_egress_budget=0, merge_capacity=100, limit=2,
    )
    stale_failed_execution_unlocks_only_reviewer = bool(
        failed_reviewer_batch.get("input_freshness")
            == "stale-settlement-only"
        and [item.get("lane_id")
             for item in failed_reviewer_batch.get("assignments", [])]
            == ["L-FIRST-REVIEW"]
        and failed_reviewer_batch["assignments"][0].get("role") == "review"
    )

    # Planner-generated vertical closure: planner -> committed plan -> delegated
    # Hunter -> real async launch/return receipts -> delegated Reviewer -> real
    # return -> typed review disposition -> Root merge -> next execution lane.
    planned_run = d / "planned-agent-closure"
    (planned_run / "state").mkdir(parents=True)
    (planned_run / "target.md").write_text(
        "# Target\n- Authorized scope: fixture.example\n",
        encoding="utf-8",
    )
    (planned_run / "coverage.json").write_text(json.dumps({
        "assets": [{"asset_id": "ASSET-ABCDEF123456",
                    "host": "fixture.example", "reachable": True,
                    "examined": False}],
    }), encoding="utf-8")
    (planned_run / "frontier.md").write_text(
        "# Frontier\n\n## Open Fronts\n\n### F-010 — fixture.example source lane\n"
        "- Status: open\n- Barrier class: none\n- Current depth: shallow\n",
        encoding="utf-8",
    )
    (planned_run / "evidence.md").write_text(
        "# Evidence\n\n## E-900\n- Front: F-010\n"
        "- Claim: frozen offline result for fixture.example\n",
        encoding="utf-8",
    )
    planned_contract = {
        "schema": "xunji.turn_contract.v1", "mode": "EXECUTE",
        "session_id": "planned-session", "prompt_sha256": "d" * 64,
        "updated_at": time.time(), "fanout_override": False,
    }
    _atomic_write(
        planned_run / "state" / "turn_contract.json",
        json.dumps(planned_contract, ensure_ascii=False, indent=2) + "\n",
    )
    generated_plan_rows = lane_suggestions(planned_run, limit=1)
    generated_plan_lanes = [row["work_plan_lane"] for row in generated_plan_rows]
    planner_commit_output = io.StringIO()
    with contextlib.redirect_stdout(planner_commit_output):
        planner_commit_exit = main([
            "commit-plan", str(planned_run),
            "--stage", "S2",
            "--objective", "exercise serial review closure",
            "--mode", "SERIAL_AGENT",
            "--reason", "one Hunter then its dependent Reviewer",
            "--exit-gate", "review receipt precedes Root merge",
            "--limit", "1",
        ])
    planned_plan = _work_plan.load_plan(planned_run)
    planned_hunter_batch = delegate_ready_lanes(
        planned_run, runtime_slots=1, request_budget=10,
        model_egress_budget=1, merge_capacity=100, limit=1,
    )
    planned_hunter = next(
        item for item in load_assignments(planned_run)["assignments"]
        if item.get("agent") == planned_hunter_batch["assignments"][0]["assignment"])
    planned_hunter_prompt_reconstructs = (
        planned_hunter_batch["assignments"][0]["launch_prompt"]
        == _runtime_receipts.assignment_launch_prompt(planned_hunter)
    )
    assignment_preserves_inventory_asset_id = bool(
        planned_hunter.get("asset_ids") == ["ASSET-ABCDEF123456"]
        and "### ASSET-ABCDEF123456 — fixture.example"
        in (planned_run / str(planned_hunter.get("agent_file") or "")).read_text(
            encoding="utf-8", errors="strict")
    )
    reviewer_before_return_blocked = False
    try:
        before_return_batch = delegate_ready_lanes(
            planned_run, runtime_slots=1, request_budget=10,
            model_egress_budget=1, merge_capacity=100, limit=1,
        )
        reviewer_before_return_blocked = bool(
            before_return_batch.get("replayed_existing") == 1
            and before_return_batch["assignments"][0]["assignment"]
                == planned_hunter["agent"]
            and before_return_batch["assignments"][0]["role"] != "review"
        )
    except ValueError as exc:
        reviewer_before_return_blocked = "no unassigned lane" in str(exc)
    planned_hunter_path = _agent_file_from_rec(planned_hunter)
    assert planned_hunter_path is not None
    planned_transcript = planned_run / "planned-transcript.jsonl"
    planned_transcript.write_text("\n".join([
        json.dumps({"agent_id": "runtime-planned-hunter", "message": {"content": [{
            "type": "tool_result", "tool_use_id": "planned-hunter-tool",
            "content": {
                "content": "HUNTER_FULL_RESPONSE\nCandidate bound to E-900\nControl retained",
                "structured": {"front": "F-010", "outcome": "candidate"},
            },
        }]}}),
        json.dumps({"agent_id": "runtime-planned-reviewer", "message": {"content": [{
            "type": "tool_result", "tool_use_id": "planned-reviewer-tool",
            "content": {
                "content": "REVIEWER_FULL_RESPONSE\nCandidate binding verified",
                "structured": {"disposition": "accept-candidate"},
            },
        }]}}),
    ]), encoding="utf-8")
    _runtime_receipts.append_hook_event(planned_run, {
        "hook_event_name": "PostToolUse", "session_id": "planned-session",
        "transcript_path": str(planned_transcript), "tool_name": "Agent",
        "tool_use_id": "planned-hunter-tool",
        "tool_input": {
            "prompt": planned_hunter_batch["assignments"][0]["launch_prompt"],
            "subagent_type": planned_hunter_batch["assignments"][0][
                "subagent_type"],
        },
        "tool_response": {"agentId": "runtime-planned-hunter", "isAsync": True,
                          "status": "async_launched"},
    })
    planned_working_row = json.loads(json.dumps(update_agent_lifecycle(
        planned_run, planned_hunter["agent"], status="working",
        note="authentic runtime attempt made material progress",
    )))
    planned_running_issues = agent_lifecycle_issues(
        planned_run, closure=True)
    _runtime_receipts.append_hook_event(planned_run, {
        "hook_event_name": "SubagentStop", "session_id": "planned-session",
        "transcript_path": str(planned_transcript),
        "agent_id": "runtime-planned-hunter",
        "agent_type": planned_hunter_batch["assignments"][0]["subagent_type"],
        "last_assistant_message": (
            "HUNTER_FULL_RESPONSE\nCandidate bound to E-900\nControl retained"),
        "tool_response": {
            "content": "HUNTER_FULL_RESPONSE\nCandidate bound to E-900\nControl retained",
            "structured": {"front": "F-010", "outcome": "candidate"},
        },
    })
    hunter_draft_path = _runtime_receipts.merge_draft_path(
        planned_run, planned_hunter["agent"])
    hunter_draft_after_return = json.loads(
        hunter_draft_path.read_text(encoding="utf-8"))
    hunter_snapshot_path = Path(hunter_draft_after_return["result"]["path"])
    hunter_snapshot_bytes = hunter_snapshot_path.read_bytes()
    hunter_snapshot_is_full_response = (
        b"HUNTER_FULL_RESPONSE" in hunter_snapshot_bytes
        and b"Control retained" in hunter_snapshot_bytes
        and b"async_launched" not in hunter_snapshot_bytes
        and hunter_draft_after_return["result"].get("source")
            == "subagent_stop_response"
    )
    superseding_contract = dict(planned_contract)
    superseding_contract["prompt_sha256"] = "f" * 64
    superseding_contract["updated_at"] = float(planned_contract["updated_at"]) + 1.0
    (planned_run / "state" / "turn_contract.json").write_text(
        json.dumps(superseding_contract), encoding="utf-8")
    stale_turn_only_detected = False
    try:
        _work_plan.current_plan(planned_run, superseding_contract)
    except _work_plan.PlanError as exc:
        stale_turn_only_detected = bool(
            str(exc) == "WORK_PLAN_TURN_STALE"
            and _work_plan.input_fingerprint(planned_run)[0]
                == planned_plan.get("inputs_digest")
        )
    stale_direct_reviewer_assign_blocked = False
    try:
        create_agent_assignment(
            planned_run, role="review", front="F-010",
            lane_id=generated_plan_lanes[1]["id"],
        )
    except ValueError as exc:
        stale_direct_reviewer_assign_blocked = (
            "WORK_PLAN_TURN_STALE" in str(exc))
    stale_premature_replan_blocked = False
    try:
        _work_plan.commit_plan(
            planned_run, macro_stage="S2",
            objective="incorrectly skip review after steering changed",
            mode="SERIAL_AGENT",
            reason="must not supersede a returned result awaiting review",
            exit_gate="returned result is still reviewed",
            lanes=generated_plan_lanes,
            replan_reason="operator hint changed before Reviewer settlement",
            contract=planned_contract,
        )
    except _work_plan.PlanError as exc:
        stale_premature_replan_blocked = (
            str(exc) == "WORK_PLAN_REPLAN_ASSIGNMENT_DEBT")
    planned_reviewer_batch = delegate_ready_lanes(
        planned_run, runtime_slots=1, request_budget=10,
        model_egress_budget=1, merge_capacity=100, limit=1,
    )
    planned_reviewer = next(
        item for item in load_assignments(planned_run)["assignments"]
        if item.get("agent") == planned_reviewer_batch["assignments"][0]["assignment"])
    planned_reviewer_prompt_reconstructs = (
        planned_reviewer_batch["assignments"][0]["launch_prompt"]
        == _runtime_receipts.assignment_launch_prompt(planned_reviewer)
    )
    planned_reviewer_wrong_prompt = re.sub(
        r"XUNJI_RESULT_DIGEST=[0-9a-f]{64}",
        "XUNJI_RESULT_DIGEST=" + ("0" * 64),
        planned_reviewer_batch["assignments"][0]["launch_prompt"],
    )
    planned_reviewer_wrong_tool = "planned-reviewer-wrong-tool"
    with planned_transcript.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps({
            "message": {"role": "assistant", "content": [{
                "type": "tool_use", "id": planned_reviewer_wrong_tool,
                "name": "Agent", "input": {
                    "prompt": planned_reviewer_wrong_prompt,
                    "subagent_type": planned_reviewer_batch[
                        "assignments"][0]["subagent_type"],
                },
            }, {
                "type": "tool_result",
                "tool_use_id": planned_reviewer_wrong_tool,
                "content": {"decision": "deny", "reason": "digest mismatch"},
            }]},
        }) + "\n")
    planned_reviewer_wrong_denial = _runtime_receipts.append_hook_event(
        planned_run, {
            "hook_event_name": "PreToolUseDenied",
            "session_id": superseding_contract["session_id"],
            "transcript_path": str(planned_transcript),
            "tool_name": "Agent",
            "tool_use_id": planned_reviewer_wrong_tool,
            "tool_input": {
                "prompt": planned_reviewer_wrong_prompt,
                "subagent_type": planned_reviewer_batch[
                    "assignments"][0]["subagent_type"],
            },
            "tool_response": {
                "decision": "deny", "reason": "digest mismatch"},
            "xunji_decision": "deny",
        })
    planned_reviewer_assignments_before_replay = (
        planned_run / "state" / "assignments.json").read_bytes()
    planned_reviewer_replay_batch = delegate_ready_lanes(
        planned_run, runtime_slots=1, request_budget=10,
        model_egress_budget=1, merge_capacity=100, limit=1,
    )
    planned_reviewer_assignments_after_replay = (
        planned_run / "state" / "assignments.json").read_bytes()
    planned_reviewer_replay_is_idempotent = bool(
        planned_reviewer_wrong_denial.get("hook_event_name")
            == "PreToolUseDenied"
        and planned_reviewer_wrong_denial.get("decision") == "deny"
        and planned_reviewer_replay_batch.get("replayed_existing") == 1
        and planned_reviewer_replay_batch["assignments"][0]["assignment"]
            == planned_reviewer["agent"]
        and planned_reviewer_replay_batch["assignments"][0]["launch_prompt"]
            == planned_reviewer_batch["assignments"][0]["launch_prompt"]
        and planned_reviewer_replay_batch["assignments"][0].get(
            "replayed_existing") is True
        and planned_reviewer_assignments_before_replay
            == planned_reviewer_assignments_after_replay
    )
    planned_reviewer_replay_routes_without_cancel = bool(
        "replay the exact durable launch contract"
        in _plan_continuation_notice(planned_run)
    )
    interrupted_session = "planned-interrupted-reviewer"
    interrupted_agent = "planned-interrupted-reviewer-child"
    interrupted_tool = "planned-interrupted-reviewer-tool"
    interrupted_parent = planned_run / f"{interrupted_session}.jsonl"
    interrupted_parent.write_text("\n".join((
        json.dumps({
            "isSidechain": False,
            "sessionId": interrupted_session,
            "message": {"role": "assistant", "content": [{
                "type": "tool_use",
                "id": interrupted_tool,
                "name": "Agent",
                "input": {
                    "prompt": planned_reviewer_batch[
                        "assignments"][0]["launch_prompt"],
                    "subagent_type": planned_reviewer_batch[
                        "assignments"][0]["subagent_type"],
                    "run_in_background": False,
                },
            }]},
        }),
        json.dumps({
            "isSidechain": False,
            "sessionId": interrupted_session,
            "message": {"role": "user", "content": [{
                "type": "tool_result",
                "tool_use_id": interrupted_tool,
                "is_error": True,
                "content": "[Request interrupted by user for tool use]",
            }]},
        }),
    )) + "\n", encoding="utf-8")
    interrupted_child_dir = (
        interrupted_parent.with_suffix("") / "subagents")
    interrupted_child_dir.mkdir(parents=True)
    interrupted_child = (
        interrupted_child_dir / f"agent-{interrupted_agent}.jsonl")
    interrupted_child.write_text("\n".join((
        json.dumps({
            "isSidechain": True,
            "sessionId": interrupted_session,
            "agentId": interrupted_agent,
            "type": "user",
            "message": {
                "role": "user",
                "content": planned_reviewer_batch[
                    "assignments"][0]["launch_prompt"],
            },
        }),
        json.dumps({
            "isSidechain": True,
            "sessionId": interrupted_session,
            "agentId": interrupted_agent,
            "type": "attachment",
            "attachment": {
                "type": "hook_cancelled",
                "hookName": "SubagentStart:xunji-reviewer",
                "hookEvent": "SubagentStart",
                "command": (
                    'python3 "$CLAUDE_PROJECT_DIR/tools/turn_contract.py"'),
                "durationMs": 600017,
                "timeoutMs": 600000,
                "timedOut": False,
            },
        }),
        json.dumps({
            "isSidechain": True,
            "sessionId": interrupted_session,
            "agentId": interrupted_agent,
            "type": "user",
            "message": {
                "role": "user",
                "content": [{
                    "type": "text",
                    "text": "[Request interrupted by user]",
                }],
            },
        }),
    )) + "\n", encoding="utf-8")
    _runtime_receipts.append_hook_event(planned_run, {
        "hook_event_name": "SubagentStart",
        "session_id": interrupted_session,
        "transcript_path": str(interrupted_parent),
        "agent_id": interrupted_agent,
        "agent_type": "xunji-reviewer",
    })
    interrupted_running_row = next(
        item for item in load_assignments(planned_run)["assignments"]
        if item.get("agent") == planned_reviewer["agent"])
    interrupted_replay_batch = delegate_ready_lanes(
        planned_run, runtime_slots=1, request_budget=10,
        model_egress_budget=1, merge_capacity=100, limit=1,
    )
    interrupted_replayed_row = next(
        item for item in load_assignments(planned_run)["assignments"]
        if item.get("agent") == planned_reviewer["agent"])
    interrupted_reviewer_auto_replay = bool(
        interrupted_running_row.get("status") == "running"
        and interrupted_replay_batch.get("replayed_existing") == 1
        and interrupted_replay_batch["assignments"][0]["assignment"]
            == planned_reviewer["agent"]
        and interrupted_replay_batch["assignments"][0]["launch_prompt"]
            == planned_reviewer_batch["assignments"][0]["launch_prompt"]
        and interrupted_replayed_row.get("status") == "assigned"
        and interrupted_replayed_row.get("attempts") == []
        and len(_runtime_receipts._load_interrupted_reviewer_start_receipts(
            planned_run,
            _runtime_receipts.load_events(planned_run),
        )) == 1
    )
    planned_reviewer_binding_tamper_blocks_replay = False
    planned_assignment_path = planned_run / "state" / "assignments.json"
    planned_assignment_bytes = planned_assignment_path.read_bytes()
    try:
        tampered_ledger = json.loads(
            planned_assignment_bytes.decode("utf-8"))
        for item in tampered_ledger.get("assignments", []):
            if item.get("agent") == planned_reviewer["agent"]:
                item["review_result_digest"] = "0" * 64
        planned_assignment_path.write_text(
            json.dumps(tampered_ledger, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        delegate_ready_lanes(
            planned_run, runtime_slots=1, request_budget=10,
            model_egress_budget=1, merge_capacity=100, limit=1,
        )
    except ValueError as exc:
        planned_reviewer_binding_tamper_blocks_replay = (
            "WORK_PLAN_ASSIGNMENT_REPLAY_REVIEW_BINDING_INVALID" in str(exc))
    finally:
        planned_assignment_path.write_bytes(planned_assignment_bytes)
    planned_reviewer_cancel_still_forbidden = False
    try:
        cancel_unlaunched_assignment(
            planned_run, planned_reviewer["agent"],
            reason="must never cancel a mandatory Reviewer")
    except ValueError as exc:
        planned_reviewer_cancel_still_forbidden = (
            "ASSIGNMENT_CANCELLATION_REVIEWER_FORBIDDEN" in str(exc))
    planned_reviewer_context = Path(planned_reviewer["context"])
    if not planned_reviewer_context.is_absolute():
        planned_reviewer_context = ROOT / planned_reviewer_context
    planned_reviewer_context_bytes = planned_reviewer_context.read_bytes()
    planned_reviewer_bundle_tamper_blocks_replay = False
    try:
        planned_reviewer_context.write_bytes(
            planned_reviewer_context_bytes + b"\nTAMPERED\n")
        delegate_ready_lanes(
            planned_run, runtime_slots=1, request_budget=10,
            model_egress_budget=1, merge_capacity=100, limit=1,
        )
    except ValueError as exc:
        planned_reviewer_bundle_tamper_blocks_replay = (
            "WORK_PLAN_ASSIGNMENT_REPLAY_BUNDLE_INVALID" in str(exc))
    finally:
        planned_reviewer_context.write_bytes(
            planned_reviewer_context_bytes)
    _runtime_receipts.append_hook_event(planned_run, {
        "hook_event_name": "PostToolUse", "session_id": "planned-session",
        "transcript_path": str(planned_transcript), "tool_name": "Agent",
        "tool_use_id": "planned-reviewer-tool",
        "tool_input": {
            "prompt": planned_reviewer_batch["assignments"][0]["launch_prompt"],
            "subagent_type": planned_reviewer_batch["assignments"][0][
                "subagent_type"],
        },
        "tool_response": {"agentId": "runtime-planned-reviewer", "isAsync": True,
                          "status": "async_launched"},
    })
    _runtime_receipts.append_hook_event(planned_run, {
        "hook_event_name": "SubagentStop", "session_id": "planned-session",
        "transcript_path": str(planned_transcript),
        "agent_id": "runtime-planned-reviewer",
        "agent_type": planned_reviewer_batch["assignments"][0][
            "subagent_type"],
        "tool_response": {
            "content": "REVIEWER_FULL_RESPONSE\naccept-candidate after digest check",
            "structured": {"disposition": "accept-candidate"},
        },
    })
    reviewer_unreviewed_blocks_next = False
    try:
        delegate_ready_lanes(
            planned_run, runtime_slots=1, request_budget=10,
            model_egress_budget=1, merge_capacity=100, limit=1,
        )
    except ValueError as exc:
        reviewer_unreviewed_blocks_next = (
            "WORK_PLAN_STALE_SETTLEMENT_ONLY" in str(exc))
    hunter_before_mutation = planned_hunter_path.read_text(encoding="utf-8")
    planned_hunter_path.write_text(
        hunter_before_mutation + "\npost-return mutation\n", encoding="utf-8")
    hunter_snapshot_path.write_bytes(hunter_snapshot_bytes + b"\ntampered\n")
    immutable_snapshot_tamper_rejected = False
    try:
        record_review_disposition(
            planned_run, target=planned_hunter["agent"],
            reviewer=planned_reviewer["agent"], disposition="accept-candidate",
            note="frozen source candidate is attributable",
        )
    except ValueError as exc:
        immutable_snapshot_tamper_rejected = "changed after return" in str(exc)
    hunter_snapshot_path.write_bytes(hunter_snapshot_bytes)
    planned_action_receipt = record_review_disposition(
        planned_run, target=planned_hunter["agent"],
        reviewer=planned_reviewer["agent"], disposition="needs-control",
        note="frozen result needs one planned control",
    )
    planned_action_draft = json.loads(
        _runtime_receipts.merge_draft_path(
            planned_run, planned_hunter["agent"]
        ).read_text(encoding="utf-8")
    )
    planned_review_receipt = record_review_disposition(
        planned_run, target=planned_hunter["agent"],
        reviewer=planned_reviewer["agent"], disposition="accept-candidate",
        note="frozen source candidate is attributable",
    )
    scaffold_mutation_does_not_change_frozen_result = bool(planned_review_receipt)
    planned_hunter_path.write_text(hunter_before_mutation, encoding="utf-8")
    planned_merge = update_agent_lifecycle(
        planned_run, planned_hunter["agent"], status="merged",
        note="Evidence: E-900 Front: F-010", terminal=True,
    )
    planned_continuation_notice = _plan_continuation_notice(planned_run)
    planned_disposition = _runtime_receipts.agent_disposition(planned_run)
    stale_plan_next_execution_blocked = False
    try:
        delegate_ready_lanes(
            planned_run, runtime_slots=1, request_budget=10,
            model_egress_budget=1, merge_capacity=100, limit=1,
        )
    except ValueError as exc:
        stale_plan_next_execution_blocked = (
            "WORK_PLAN_STALE_SETTLEMENT_ONLY" in str(exc))
    replanned_lanes, inherited_completed_lanes = _remaining_replan_lanes(
        planned_run,
        [row["work_plan_lane"] for row in lane_suggestions(planned_run, limit=1)],
        replan_reason="operator hint changed after the prior Hunter returned",
    )
    steering_replan = _work_plan.commit_plan(
        planned_run, macro_stage="S2",
        objective="apply new steering to the remaining execution lanes",
        mode="SERIAL_AGENT",
        reason="settled old result before rebinding remaining work",
        exit_gate="newly bound execution and Reviewer chain is settled",
        lanes=replanned_lanes,
        replan_reason="operator hint changed after the prior Hunter returned",
        contract=superseding_contract,
    )
    # The current plan has intentionally omitted the settled OFFLINE prefix.
    # A second generated replan must still find that completion in the verified
    # grandparent transaction rather than creating another Hunter/Reviewer pair.
    transitive_replanned_lanes, transitive_inherited_lanes = (
        _remaining_replan_lanes(
            planned_run,
            [row["work_plan_lane"] for row in lane_suggestions(
                planned_run, limit=1)],
            replan_reason="a later cycle regenerated the conservative seed",
        )
    )
    changed_dependency_lanes = json.loads(json.dumps(generated_plan_lanes))
    changed_dependency_lanes[1]["dependencies"] = []
    dependency_changed_replanned_lanes, dependency_changed_inherited_lanes = (
        _remaining_replan_lanes(
            planned_run,
            changed_dependency_lanes,
            replan_reason="Reviewer dependency precondition changed",
        )
    )
    planned_next_batch = delegate_ready_lanes(
        planned_run, runtime_slots=1, request_budget=10,
        model_egress_budget=1, merge_capacity=100, limit=1,
    )
    planned_draft = json.loads(hunter_draft_path.read_text(encoding="utf-8"))
    synthesizer_assignment_rejected = False
    try:
        create_agent_assignment(
            planned_run, role="synthesizer", front="F-010",
            lane_id="L-OFFLINE-REVIEW",
        )
    except ValueError as exc:
        synthesizer_assignment_rejected = "Root-owned singleton" in str(exc)

    a_web = create_agent_assignment(run, role="web", front="F-002", assets=["b.example"])
    a1 = create_agent_assignment(run, role="web-auth", front="F-001", assets=["a.example"])
    a2 = create_agent_assignment(run, role="verify", front="F-001", assets=["a.example"])
    a3 = create_agent_assignment(run, role="surface", front="F-002", assets=["f.example"])
    a4 = create_agent_assignment(run, role="verify", front="F-002", assets=["b.example"])
    web_context = Path(a_web["context"]) if Path(a_web["context"]).is_absolute() else ROOT / a_web["context"]
    (run / a1["agent_file"]).write_text(
        "# Agent A\n- Role: web-auth\n- Assigned front: F-001\n- Status: done\n"
        "- Supports: IDOR in profile\n- Refutes:\n- Confidence: 0.8\n"
        "- Control:\n- Replicated:\n- Artifacts: ev1.html\n",
        encoding="utf-8")
    (run / a2["agent_file"]).write_text(
        "# Agent B\n- Role: verify\n- Assigned front: F-001\n- Status: done\n"
        "- Supports:\n- Refutes: IDOR in profile\n- Confidence: 0.3\n"
        "- Control: baseline replay\n- Replicated: no\n- Artifacts: ev2.html\n",
        encoding="utf-8")
    (run / a3["agent_file"]).write_text(
        "# Agent C\n- Role: surface\n- Assigned front: F-002\n- Status: done\n"
        "- Supports: API IDOR\n- Refutes:\n- Confidence: 0.8\n"
        "- Control: none\n- Replicated: none\n- Artifacts: ev-a.html\n",
        encoding="utf-8")
    (run / a4["agent_file"]).write_text(
        "# Agent D\n- Role: verify\n- Assigned front: F-002\n- Status: done\n"
        "- Supports: API IDOR\n- Refutes:\n- Confidence: 0.5\n"
        "- Control: baseline replay\n- Replicated: yes\n- Artifacts: ev-b.html\n",
        encoding="utf-8")
    a5 = create_agent_assignment(run, role="web-hunter", front="F-003", assets=["c.example"])
    (run / a5["agent_file"]).write_text(
        "# Agent E\n- Role: web-hunter\n- Assigned front: F-003\n- Status: done\n"
        "- Maturity: finding\n- Supports: upload shell\n- Refutes:\n- Confidence: 0.8\n"
        "- Control:\n- Replicated:\n- Artifacts:\n- Closure: confirmed\n",
        encoding="utf-8")
    conflict_doc = build_conflicts(run)
    synth_doc = synthesize_draft(run)
    agent_issues = agent_discipline_issues(run)
    context_exists = (ROOT / a1["context"]).exists() if not Path(a1["context"]).is_absolute() else Path(a1["context"]).exists()

    conflict_projection_run = d / "conflict-projection"
    (conflict_projection_run / "agents").mkdir(parents=True)
    first_conflict_projection = build_conflicts(conflict_projection_run)
    conflict_projection_path = (
        conflict_projection_run / "state" / "conflicts.json")
    first_conflict_bytes = conflict_projection_path.read_bytes()
    first_conflict_fingerprint = _work_plan.input_fingerprint(
        conflict_projection_run)[0]
    with mock.patch.object(
            sys.modules[__name__], "_conflict_projection_timestamp",
            return_value="2099-12-31T23:59:59Z"):
        repeated_conflict_projection = build_conflicts(conflict_projection_run)
    repeated_conflict_bytes = conflict_projection_path.read_bytes()
    repeated_conflict_fingerprint = _work_plan.input_fingerprint(
        conflict_projection_run)[0]
    conflict_projection_is_idempotent = bool(
        first_conflict_projection == repeated_conflict_projection
        and first_conflict_bytes == repeated_conflict_bytes
        and first_conflict_fingerprint == repeated_conflict_fingerprint
    )
    (conflict_projection_run / "agents" / "A-support.md").write_text(
        "# Agent A\n- Role: web-hunter\n- Assigned front: F-001\n"
        "- Status: done\n- Supports: candidate\n- Refutes:\n",
        encoding="utf-8",
    )
    (conflict_projection_run / "agents" / "A-refute.md").write_text(
        "# Agent B\n- Role: verify\n- Assigned front: F-001\n"
        "- Status: done\n- Supports:\n- Refutes: candidate\n",
        encoding="utf-8",
    )
    changed_conflict_projection = build_conflicts(conflict_projection_run)
    changed_conflict_fingerprint = _work_plan.input_fingerprint(
        conflict_projection_run)[0]
    semantic_conflict_change_stales_fingerprint = bool(
        any(
            item.get("type") == "direct contradiction"
            for item in changed_conflict_projection.get("conflicts", [])
        )
        and conflict_projection_path.read_bytes() != first_conflict_bytes
        and changed_conflict_fingerprint != first_conflict_fingerprint
    )

    concurrent_conflict_run = d / "concurrent-conflict-projection"
    concurrent_conflict_path = (
        concurrent_conflict_run / "state" / "conflicts.json")
    lock_attempt_count = 0
    lock_attempt_count_guard = threading.Lock()
    second_lock_attempted = threading.Event()
    first_write_started = threading.Event()
    second_write_started = threading.Event()
    release_writes = threading.Event()
    write_count_lock = threading.Lock()
    conflict_write_count = 0
    original_atomic_write = _atomic_write
    original_assignment_lock = _assignment_mutation_lock

    @contextlib.contextmanager
    def observed_assignment_lock(run_dir: Path):
        nonlocal lock_attempt_count
        with lock_attempt_count_guard:
            lock_attempt_count += 1
            if lock_attempt_count == 2:
                second_lock_attempted.set()
        with original_assignment_lock(run_dir):
            yield

    def delayed_conflict_write(path: Path, text: str) -> None:
        nonlocal conflict_write_count
        if path == concurrent_conflict_path:
            with write_count_lock:
                conflict_write_count += 1
                count = conflict_write_count
            (first_write_started if count == 1 else second_write_started).set()
            if not release_writes.wait(timeout=2.0):
                raise RuntimeError("conflict projection concurrency fixture timed out")
        original_atomic_write(path, text)

    def second_conflict_build() -> dict:
        return build_conflicts(concurrent_conflict_run)

    with mock.patch.object(
            sys.modules[__name__], "_assignment_mutation_lock",
            side_effect=observed_assignment_lock), mock.patch.object(
                sys.modules[__name__], "_atomic_write",
                side_effect=delayed_conflict_write):
        with ThreadPoolExecutor(max_workers=2) as pool:
            first_future = pool.submit(build_conflicts, concurrent_conflict_run)
            first_write_observed = first_write_started.wait(timeout=1.0)
            second_future = pool.submit(second_conflict_build)
            second_attempt_observed = second_lock_attempted.wait(timeout=1.0)
            second_reached_publish_before_release = second_write_started.wait(
                timeout=1.0)
            release_writes.set()
            concurrent_results = [
                first_future.result(timeout=2.0),
                second_future.result(timeout=2.0),
            ]
    concurrent_conflict_projection_is_linear = bool(
        first_write_observed and second_attempt_observed
        and not second_reached_publish_before_release
        and conflict_write_count == 1
        and concurrent_results[0] == concurrent_results[1]
        and concurrent_conflict_path.is_file()
    )

    duplicate_conflict_run = d / "duplicate-conflict-projection"
    duplicate_conflict_path = duplicate_conflict_run / "state" / "conflicts.json"
    duplicate_conflict_path.parent.mkdir(parents=True)
    duplicate_conflict_path.write_text(
        '{"schema":999,"schema":1,"generated_at":"2026-07-18T00:00:00Z",'
        '"conflict_types":[],"conflicts":[]}\n',
        encoding="utf-8",
    )
    duplicate_diagnostic = io.StringIO()
    with contextlib.redirect_stderr(duplicate_diagnostic):
        rebuilt_duplicate_projection = build_conflicts(duplicate_conflict_run)
    duplicate_keys_rebuild_with_diagnostic = bool(
        "WARN rebuilding invalid conflicts projection"
        in duplicate_diagnostic.getvalue()
        and rebuilt_duplicate_projection.get("schema") == 1
        and duplicate_conflict_path.read_text(
            encoding="utf-8").count('"schema"') == 1
    )

    malformed_time_run = d / "malformed-time-conflict-projection"
    malformed_time_path = malformed_time_run / "state" / "conflicts.json"
    malformed_time_path.parent.mkdir(parents=True)
    malformed_time_path.write_text(json.dumps({
        "schema": 1,
        "generated_at": "9999-99-99T99:99:99Z",
        "conflict_types": [],
        "conflicts": [],
    }), encoding="utf-8")
    malformed_time_diagnostic = io.StringIO()
    with contextlib.redirect_stderr(malformed_time_diagnostic):
        rebuilt_malformed_time = build_conflicts(malformed_time_run)
    malformed_timestamp_rebuilds_with_diagnostic = bool(
        "WARN rebuilding malformed conflicts projection"
        in malformed_time_diagnostic.getvalue()
        and _valid_conflict_timestamp(rebuilt_malformed_time.get("generated_at"))
    )

    future_conflict_run = d / "future-conflict-projection"
    future_conflict_path = future_conflict_run / "state" / "conflicts.json"
    future_conflict_path.parent.mkdir(parents=True)
    future_payload = json.dumps({
        "schema": 2,
        "generated_at": "2026-07-18T00:00:00Z",
        "conflict_types": [],
        "conflicts": [],
    })
    future_conflict_path.write_text(future_payload, encoding="utf-8")
    try:
        build_conflicts(future_conflict_run)
        future_conflict_schema_fails_closed = False
    except ValueError as exc:
        future_conflict_schema_fails_closed = bool(
            str(exc) == "CONFLICT_PROJECTION_SCHEMA_UNSUPPORTED:2"
            and future_conflict_path.read_text(encoding="utf-8") == future_payload
        )

    unknown_field_run = d / "unknown-field-conflict-projection"
    unknown_field_path = unknown_field_run / "state" / "conflicts.json"
    unknown_field_path.parent.mkdir(parents=True)
    unknown_payload = json.dumps({
        "schema": 1,
        "generated_at": "2026-07-18T00:00:00Z",
        "conflict_types": [],
        "conflicts": [],
        "future": True,
    })
    unknown_field_path.write_text(unknown_payload, encoding="utf-8")
    try:
        build_conflicts(unknown_field_run)
        unknown_conflict_field_fails_closed = False
    except ValueError as exc:
        unknown_conflict_field_fails_closed = bool(
            str(exc) == "CONFLICT_PROJECTION_UNKNOWN_FIELDS:future"
            and unknown_field_path.read_text(encoding="utf-8") == unknown_payload
        )

    symlink_conflict_run = d / "symlink-conflict-projection"
    (symlink_conflict_run / "agents").mkdir(parents=True)
    symlink_conflict_path = symlink_conflict_run / "state" / "conflicts.json"
    initial_symlink_projection = build_conflicts(symlink_conflict_run)
    outside_conflict_path = d / "outside-conflicts.json"
    outside_conflict_path.write_bytes(symlink_conflict_path.read_bytes())
    symlink_conflict_path.unlink()
    symlink_conflict_path.symlink_to(outside_conflict_path)
    symlink_diagnostic = io.StringIO()
    with contextlib.redirect_stderr(symlink_diagnostic):
        rebuilt_symlink_projection = build_conflicts(symlink_conflict_run)
    _symlink_digest, symlink_rows = _work_plan.input_fingerprint(
        symlink_conflict_run)
    conflict_symlink_rebuilt_and_bound = bool(
        "WARN rebuilding non-regular conflicts projection"
        in symlink_diagnostic.getvalue()
        and rebuilt_symlink_projection == initial_symlink_projection
        and not symlink_conflict_path.is_symlink()
        and stat.S_ISREG(symlink_conflict_path.lstat().st_mode)
        and any(
            row.get("path") == "state/conflicts.json"
            for row in symlink_rows
        )
    )

    strict_synthesize_rejects_future_projection = False
    try:
        synthesize_draft(future_conflict_run)
    except ValueError as exc:
        strict_synthesize_rejects_future_projection = (
            str(exc) == "CONFLICT_PROJECTION_SCHEMA_UNSUPPORTED:2")
    strict_synthesize_rejects_unknown_projection = False
    try:
        synthesize_draft(unknown_field_run)
    except ValueError as exc:
        strict_synthesize_rejects_unknown_projection = (
            str(exc) == "CONFLICT_PROJECTION_UNKNOWN_FIELDS:future")

    assignment_schema = json.loads((
        ROOT / "contracts" / "assignment.v1.schema.json"
    ).read_text(encoding="utf-8", errors="strict"))
    agent_receipt_schema = json.loads((
        ROOT / "contracts" / "agent-receipt.v1.schema.json"
    ).read_text(encoding="utf-8", errors="strict"))
    schema_documents = {"agent-receipt.v1.schema.json": agent_receipt_schema}

    def assignment_schema_errors(value: object) -> list[str]:
        if _runtime_receipts is None \
                or not hasattr(_runtime_receipts, "_selftest_schema_errors"):
            return ["runtime schema selftest validator unavailable"]
        return _runtime_receipts._selftest_schema_errors(
            value, assignment_schema, documents=schema_documents)

    plan_bound_assignment_rows = [
        item for item in load_assignments(planned_run).get("assignments", [])
        if isinstance(item, dict) and item.get("schema") == "xunji.assignment.v1"
    ]
    merged_schema_row = next(
        item for item in plan_bound_assignment_rows if item.get("status") == "merged")
    reviewed_schema_row = next(
        item for item in plan_bound_assignment_rows if item.get("status") == "reviewed")
    assigned_schema_row = next(
        item for item in plan_bound_assignment_rows if item.get("status") == "assigned")

    def cloned(value: object) -> object:
        return json.loads(json.dumps(value))

    assignment_unknown = cloned(assigned_schema_row)
    assignment_unknown["untrusted_extra"] = True
    assignment_missing = cloned(assigned_schema_row)
    assignment_missing.pop("plan_digest")
    assignment_bool_number = cloned(assigned_schema_row)
    assignment_bool_number["assignment_attempt"] = True
    assignment_bool_tool_limit = cloned(assigned_schema_row)
    assignment_bool_tool_limit["tool_call_limit"] = True
    assignment_small_tool_limit = cloned(assigned_schema_row)
    assignment_small_tool_limit["tool_call_limit"] = 4
    assignment_bool_request_budget = cloned(assigned_schema_row)
    assignment_bool_request_budget["request_budget"] = True
    assignment_negative_request_budget = cloned(assigned_schema_row)
    assignment_negative_request_budget["request_budget"] = -1
    assignment_bad_timestamp = cloned(assigned_schema_row)
    assignment_bad_timestamp["created_at"] = "not-a-timestamp"
    assignment_with_stale_attempt = cloned(assigned_schema_row)
    assignment_with_stale_attempt["attempts"] = cloned(merged_schema_row["attempts"])
    merged_without_review_binding = cloned(merged_schema_row)
    merged_without_review_binding.pop("root_disposition_review_receipt_hash")
    reviewer_without_result_binding = cloned(reviewed_schema_row)
    reviewer_without_result_binding.pop("review_result_digest")
    execution_with_reviewer_binding = cloned(assigned_schema_row)
    execution_with_reviewer_binding["review_result_digest"] = "5" * 64
    receipt_unknown_nested = cloned(merged_schema_row)
    receipt_unknown_nested["attempts"][0]["untrusted_extra"] = True
    receipt_bool_length_nested = cloned(merged_schema_row)
    receipt_bool_length_nested["attempts"][0]["result_snapshot"]["length"] = True
    hunter_with_reviewer_type = cloned(merged_schema_row)
    hunter_with_reviewer_type["attempts"][0]["subagent_type"] = "xunji-reviewer"
    reviewer_with_hunter_type = cloned(reviewed_schema_row)
    reviewer_with_hunter_type["attempts"][0]["subagent_type"] = "xunji-hunter"

    unlaunched_working_rejected = False
    try:
        update_agent_lifecycle(
            planned_run,
            planned_next_batch["assignments"][0]["assignment"],
            status="working", note="no runtime attempt exists",
        )
    except ValueError as exc:
        unlaunched_working_rejected = "authentic running attempt" in str(exc)

    tampered_journal_path = planned_run / "state" / "loop_journal.jsonl"
    assignments_before_journal_tamper = (
        planned_run / "state" / "assignments.json").read_bytes()
    with tampered_journal_path.open("a", encoding="utf-8") as handle:
        handle.write("{malformed journal tail\n")
    journal_tamper_assignment_rejected = False
    journal_tamper_lifecycle_rejected = False
    tampered_lane = generated_plan_lanes[-1]
    try:
        create_agent_assignment(
            planned_run,
            role=str(tampered_lane.get("role") or "review"),
            front=str(tampered_lane.get("front") or "F-010"),
            assets=[str(item) for item in tampered_lane.get("assets", [])],
            lane_id=str(tampered_lane.get("id") or ""),
        )
    except ValueError as exc:
        journal_tamper_assignment_rejected = str(exc).startswith(
            "plan-bound lifecycle mutation refused: invalid loop journal")
    try:
        update_agent_lifecycle(
            planned_run,
            planned_next_batch["assignments"][0]["assignment"],
            status="running", note="must not mutate across a corrupt journal",
        )
    except ValueError as exc:
        journal_tamper_lifecycle_rejected = str(exc).startswith(
            "plan-bound lifecycle mutation refused: invalid loop journal")
    journal_tamper_preserved_assignments = (
        planned_run / "state" / "assignments.json").read_bytes() \
        == assignments_before_journal_tamper

    def make_model_proposal_run(name: str, *, host: str, front: str) -> Path:
        proposal_run = d / name
        (proposal_run / "state").mkdir(parents=True)
        (proposal_run / "target.md").write_text(
            f"# Target\n- Authorized scope: {host}\n", encoding="utf-8")
        (proposal_run / "coverage.json").write_text(json.dumps({
            "assets": [{"asset_id": "ASSET-PROPOSAL0001", "host": host,
                        "reachable": True, "examined": False}],
        }), encoding="utf-8")
        (proposal_run / "frontier.md").write_text(
            f"# Frontier\n\n## Open Fronts\n\n### {front} — {host} adaptive lanes\n"
            "- Status: open\n- Barrier class: none\n- Current depth: shallow\n",
            encoding="utf-8",
        )
        (proposal_run / "evidence.md").write_text(
            f"# Evidence\n\n## E-901\n- Front: {front}\n"
            "- Claim: enough prior state to choose the next effect\n",
            encoding="utf-8",
        )
        _atomic_write(
            proposal_run / "state" / "turn_contract.json",
            json.dumps({
                "schema": "xunji.turn_contract.v1", "mode": "EXECUTE",
                "session_id": f"{name}-session", "prompt_sha256": "e" * 64,
                "updated_at": time.time(), "fanout_override": False,
            }, ensure_ascii=False, indent=2) + "\n",
        )
        return proposal_run

    def proposal_lane(
        lane_id: str, *, front: str, host: str, role: str = "web-hunter",
        effect: str = "local_read", dependencies: list[str] | None = None,
    ) -> dict:
        return {
            "id": lane_id, "role": role, "front": front, "effect": effect,
            "assets": [host], "dependencies": list(dependencies or []),
            "expected_evidence": "one bounded strategy-selected signal",
            "expected_information_gain": "high",
            "stop_condition": "the signal is observed or a control refutes it",
            "request_cost": 1 if effect == "target" else 0,
            "request_budget": 2 if effect == "target" else 0,
            "merge_cost": 5, "atomic": False,
        }

    adaptive_run = make_model_proposal_run(
        "adaptive-model-proposal", host="proposal.example", front="F-020")
    adaptive_lanes: list[dict] = []
    for suffix in ("SOURCE", "CVE", "CONFIG"):
        execution_id = f"L-F-020-{suffix}"
        adaptive_lanes.append(proposal_lane(
            execution_id, front="F-020", host="proposal.example"))
        adaptive_lanes.append(proposal_lane(
            f"{execution_id}-REVIEW", front="F-020", host="proposal.example",
            role="review", effect="local_verify", dependencies=[execution_id]))
    adaptive_proposal = {
        "schema": PLAN_PROPOSAL_SCHEMA,
        "basis": _plan_proposal_basis(adaptive_run),
        "macro_stage": "S2",
        "objective": "run three independent local investigations without splitting the front",
        "execution_mode": "PARALLEL_AGENTS",
        "delegation_reason": "three effect-compatible ready lanes",
        "exit_gate": "each exact result receives its bound Reviewer",
        "replan_reason": "",
        "lanes": adaptive_lanes,
    }
    _atomic_write(
        _plan_proposal_path(adaptive_run),
        json.dumps(adaptive_proposal, ensure_ascii=False, indent=2) + "\n",
    )
    adaptive_commit_output = io.StringIO()
    with contextlib.redirect_stdout(adaptive_commit_output):
        adaptive_commit_exit = print_commit_proposal(adaptive_run)
    adaptive_plan = _work_plan.load_plan(adaptive_run)
    adaptive_contract_path = adaptive_run / "state" / "turn_contract.json"
    adaptive_contract = json.loads(adaptive_contract_path.read_text(encoding="utf-8"))
    adaptive_contract["prompt_sha256"] = "f" * 64
    adaptive_contract["updated_at"] = time.time() + 1
    _atomic_write(
        adaptive_contract_path,
        json.dumps(adaptive_contract, ensure_ascii=False, indent=2) + "\n",
    )
    try:
        load_plan_proposal(adaptive_run)
        stale_model_proposal_rejected = False
    except ValueError as exc:
        stale_model_proposal_rejected = str(exc) == "WORK_PLAN_PROPOSAL_STALE"

    target_only_run = make_model_proposal_run(
        "target-only-model-proposal", host="target-only.example", front="F-021")
    target_execution = proposal_lane(
        "L-F-021-TARGET", front="F-021", host="target-only.example",
        effect="target")
    target_review = proposal_lane(
        "L-F-021-TARGET-REVIEW", front="F-021", host="target-only.example",
        role="review", effect="local_verify", dependencies=[target_execution["id"]])
    target_only_proposal = {
        "schema": PLAN_PROPOSAL_SCHEMA,
        "basis": _plan_proposal_basis(target_only_run),
        "macro_stage": "S2",
        "objective": "use existing state for one bounded target check",
        "execution_mode": "SERIAL_AGENT",
        "delegation_reason": "one target effect is ready",
        "exit_gate": "the target result receives its exact Reviewer",
        "replan_reason": "",
        "lanes": [target_execution, target_review],
    }
    _atomic_write(
        _plan_proposal_path(target_only_run),
        json.dumps(target_only_proposal, ensure_ascii=False, indent=2) + "\n",
    )
    target_only_output = io.StringIO()
    with contextlib.redirect_stdout(target_only_output):
        target_only_exit = print_commit_proposal(target_only_run)
    target_only_plan = _work_plan.load_plan(target_only_run)
    checks = [
        ("target review admission accepts four absolute frozen artifact paths",
         len(validated_artifact_receipts) == 4
         and sum(item.get("response", {}).get("status") == 200
                 for item in validated_artifact_receipts) == 2),
        ("truncated replay validates saved bytes without comparing them to the wire hash",
         partial_response.get("truncated") is True
         and partial_response.get("saved_len") == len(partial_saved)
         and partial_response.get("wire_verified") is False),
        ("legacy capped replay preserves full-wire identity without claiming full verification",
         legacy_partial_response.get("len") == len(partial_wire)
         and legacy_partial_response.get("sha1")
            == hashlib.sha1(partial_wire).hexdigest()
         and legacy_partial_response.get("saved_len") == len(partial_saved)
         and legacy_partial_response.get("truncated") is True
         and legacy_partial_response.get("wire_verified") is False),
        ("empty replay wire hash cannot bypass artifact integrity",
         empty_wire_hash_rejected),
        ("target review admission rejects stale or invented Reviewer artifacts",
         stale_reviewer_artifact_rejected),
        ("unknown future assignment ledger schema fails closed",
         unknown_assignment_schema_rejected),
        ("suggest returns open/probing before bad deferred", rows[0]["front"] in {"F-001", "F-002", "F-003"}),
        ("suggest excludes closed", all(r["front"] != "F-099" for r in rows)),
        ("breadth signals stay descriptive rather than choosing scheduler mode",
         _breadth_signals(rows[:3])[0] == "strong candidates=3"
         and not any("serial" in item or "fan-out" in item
                     for item in _breadth_signals(rows[:3]))),
        ("scan sees two done workers", len(unmerged(run)) == 2),
        ("empty run suggest returns []", suggest(empty_run) == []),
        ("asset suggestions live in workers not graph",
         any(r["asset"] == "e.example" and r["role"] == "web-auth" for r in asset_rows)),
        ("coverage asset identity preserves an explicit port",
         _asset_name({"host": "port.example", "port": 8443}) == "port.example:8443"),
        ("assignment projections preserve the inventory-owned asset id",
         assignment_preserves_inventory_asset_id),
        ("plan with no strong candidate exits 1 and forbids example fallback",
         no_strong_exit == 1
         and "NO_STRONG_CANDIDATE" in driver_output.getvalue()
         and "do not commit or copy" in driver_output.getvalue()),
        ("merge-check clean path exits 0", clean_exit == 0),
        ("created worker scans assigned front", clean_rows and clean_rows[0]["front"] == "F-123"),
        ("field parser does not cross newline on empty value", _field("- Barrier class:\n- Same barrier failures: 1", "Barrier class") == ""),
        ("empty Claim does not swallow next line", any(i["kind"] == "missing-claim" for i in missing_issues)),
        ("empty Control does not swallow following text", any(i["kind"] == "worker-missing-control" for i in missing_issues)),
        ("plan breadth signals use the full candidate pool",
         _breadth_signals(plan_limited_rows)[0]
         == f"strong candidates={len(plan_limited_rows)}"),
        ("planner names parallel mode for two dependency-free compatible fronts",
         parallel_plan_exit == 0
         and "ready=2 capacity-free_parallel_width=2 "
             "topology_mode=PARALLEL_AGENTS"
             in parallel_plan_output.getvalue()),
        ("planner writes a turn-bound non-authorizing model proposal seed",
         successful_plan_exit == 0
         and "MODEL_PROPOSAL:" in successful_plan_output.getvalue()
         and planner_seed_proposal.get("schema") == PLAN_PROPOSAL_SCHEMA
         and set(planner_seed_proposal.get("basis") or {})
            == {"inputs_digest", "turn_binding"}
         and len(planner_seed_proposal.get("lanes") or []) == 12
         and bool(re.fullmatch(r"[0-9a-f]{64}", planner_seed_digest))),
        ("S1 planner keeps target work behind the collection-stage boundary",
         [row["work_plan_lane"]["effect"] for row in s1_planned_lanes]
         == ["local_read", "local_verify", "local_read", "local_verify"]
         and sum(
             not row["work_plan_lane"]["dependencies"]
             for row in s1_planned_lanes
         ) == 2),
        ("S3 planner emits closure verification and dependent review only",
         [row["work_plan_lane"]["role"] for row in s3_planned_lanes]
         == ["verify", "review", "verify", "review"]
         and all(
             row["work_plan_lane"]["effect"] == "local_verify"
             for row in s3_planned_lanes
         )),
        ("offline operator constraint removes target lanes at planner source",
         offline_plan_exit == 0
         and [row["work_plan_lane"]["effect"] for row in offline_planned_lanes]
         == ["local_read", "local_verify"]
         and offline_planned_lanes[1]["work_plan_lane"]["dependencies"]
         == [offline_planned_lanes[0]["work_plan_lane"]["id"]]
         and "TARGET_EGRESS_DENIED; target lanes and target-dependent verification are omitted"
         in offline_plan_output.getvalue()
         and len(json.loads(_plan_proposal_path(offline_plan_run).read_text(
             encoding="utf-8")).get("lanes") or []) == 2),
        ("single-front lane plan reviews every execution lane before advancing",
         [row["work_plan_lane"]["effect"] for row in planned_lanes]
         == ["local_read", "local_verify", "target", "local_verify",
             "local_verify", "local_verify"]
         and [row["work_plan_lane"]["role"] for row in planned_lanes]
         == ["web-hunter", "review", "web-hunter", "review", "verify", "review"]),
        ("lane planner emits cost and information-gain fields",
         all({"request_cost", "expected_information_gain", "merge_cost"}
             <= set(row["work_plan_lane"]) for row in planned_lanes)),
        ("lane dependencies serialize each execution-review pair",
         planned_lanes[1]["work_plan_lane"]["dependencies"]
         == [planned_lanes[0]["work_plan_lane"]["id"]]
         and planned_lanes[2]["work_plan_lane"]["dependencies"]
         == [planned_lanes[1]["work_plan_lane"]["id"]]
         and planned_lanes[3]["work_plan_lane"]["dependencies"]
         == [planned_lanes[2]["work_plan_lane"]["id"]]
         and planned_lanes[-1]["work_plan_lane"]["dependencies"]
         == [planned_lanes[-2]["work_plan_lane"]["id"]]),
        ("model proposal can commit three ready lanes under one semantic front",
         adaptive_commit_exit == 0
         and adaptive_plan.get("execution_mode") == "PARALLEL_AGENTS"
         and len(adaptive_plan.get("lanes") or []) == 6
         and {item.get("front") for item in adaptive_plan.get("lanes") or []}
            == {"F-020"}
         and sum(not item.get("dependencies")
                 for item in adaptive_plan.get("lanes") or []) == 3
         and '"source": "model-proposal"' in adaptive_commit_output.getvalue()
         and '"ready_lane_count": 3' in adaptive_commit_output.getvalue()),
        ("model proposal may omit the generated offline prefix",
         target_only_exit == 0
         and [item.get("effect") for item in target_only_plan.get("lanes") or []]
            == ["target", "local_verify"]
         and [item.get("id") for item in target_only_plan.get("lanes") or []]
            == ["L-F-021-TARGET", "L-F-021-TARGET-REVIEW"]),
        ("model proposal is rejected after its turn binding changes",
         stale_model_proposal_rejected),
        ("scheduler width is bounded by runtime and merge capacity",
         scheduler_width(lane_suggestions(run, limit=3), runtime_slots=2,
                         request_budget=99, merge_capacity=10) == 1),
        ("delegate assigns the later lane actually selected under budget",
         delegate_uses_exact_budget_selection),
        ("stale inputs cannot launch another unassigned execution lane",
         stale_plan_new_execution_blocked),
        ("scheduler skips over-budget merge, target, and model-egress rows",
         scheduler_skips_each_over_budget_effect),
        ("delegate batch failure rolls back assignments and generated artifacts",
         failed_batch_has_zero_partial_state),
        ("delegate batch retry commits both ready execution lanes",
         retry_commits_complete_batch),
        ("prepared delegate transaction recovers idempotently through assign entry",
         crash_recovery_is_idempotent),
        ("crash-recovered delegate retry commits the complete batch",
         crash_retry_is_complete),
        ("immutable cancellation receipts satisfy the versioned JSON schema",
         len(cancellation_receipts) == 2
         and all(not cancellation_schema_errors(item)
                 for item in cancellation_receipts)
         and bool(cancellation_schema_errors(cancellation_unknown))),
        ("typed cancellation removes only unlaunched rows and keeps cycle debt open",
         cancellation_rows_after_cancel == []
         and cancellation_projection.get("assigned_debt") == []
         and all(item.get("complete") is False
                 for item in cancellation_projection.get("lane_states", []))
         and cancellation_cycle_end_blocked),
        ("turn-only stale authority can retire a provably unlaunched assignment",
         turn_stale_cancellation_is_typed),
        ("turn-and-input stale authority records the exact combined basis",
         both_stale_cancellation_is_typed),
        ("cancellation CLI keeps the front open and denies completion semantics",
         cancellation_cli_preserves_open_front),
        ("v1/v2 cancellation transaction and tombstone mixes fail closed",
         cancellation_cross_version_mixes_rejected),
        ("material replan is required and canceled Agent ids are never reused",
         cancellation_replan.get("plan_digest")
            != cancellation_receipts[0].get("plan_digest")
         and cancellation_new_ids
         and cancellation_new_ids.isdisjoint(cancellation_old_ids)),
        ("read-only archive scan never deletes a concurrent writer temp",
         cancellation_temp.exists()
         and len(cancellation_after_temp_cleanup) == 2),
        ("parent creation durability faults map stably and retry in order",
         cancellation_parent_durability_failures_stable),
        ("every cancellation crash point forward-recovers one receipt",
         all(cancellation_crash_results)
         and len(cancellation_crash_results) == 6),
        ("prepared cancellation blocks concurrent late Agent failures before snapshots",
         all(cancellation_crash_runtime_barriers)
         and len(cancellation_crash_runtime_barriers) == 3),
        ("prepared cancellation blocks material replan until forward recovery",
         all(cancellation_crash_replan_barriers)
         and len(cancellation_crash_replan_barriers) == 3),
        ("late transcript Start remains debt and cannot cross or erase cancellation",
         late_start_toctou_fail_closed),
        ("missing artifact retry repeats the unlink parent durability barrier",
         unlink_barrier_retry_complete),
        ("parent transcript Agent tool_use blocks unlaunched cancellation",
         transcript_launch_cancel_blocked),
        ("exact PreToolUse denial is negative launch proof for cancellation",
         denied_launch_cancellation_allowed),
        ("runtime failure/event cannot be relabeled as not-run cancellation",
         runtime_event_cancel_blocked),
        ("all Agent lifecycle identities replay exactly without a tombstone",
         all(exact_replay_without_tombstone)
         and len(exact_replay_without_tombstone) == 5),
        ("older Agent facts replay exactly across a later cancellation tombstone",
         all(exact_replay_with_tombstone)
         and len(exact_replay_with_tombstone) == 5),
        ("stale failed execution unlocks only its unique Reviewer",
         stale_failed_execution_unlocks_only_reviewer),
        ("same-asset target lanes cannot overlap",
         not lanes_can_overlap(
             {"effect": "target", "assets": ["a.example"], "dependencies": []},
             {"effect": "target", "assets": ["a.example"], "dependencies": []})),
        ("merge-check catches missing control", any(i["kind"] == "worker-missing-control" for i in issues)),
        ("merge-check catches duplicate candidate", any(i["kind"] == "duplicate-candidate" for i in issues)),
        ("merge-check catches conflicting candidate certainty", any(i["kind"] == "conflicting-candidate" for i in issues)),
        ("merge-check catches done-but-unmerged", any(i["kind"] == "done-but-unmerged" for i in issues)),
        ("schema-v1 assignment rows migrate explicitly to schema-v3 defaults",
         migrated_assignments.get("schema") == 3
         and migrated_assignments["assignments"][0].get("assets") == []
         and migrated_assignments["assignments"][0].get("attempts") == []
         and migrated_assignments["assignments"][0].get("lane_id") == ""),
        ("real initial, returned, reviewed, merged, and next-lane assignments conform",
         len(plan_bound_assignment_rows) >= 3
         and all(not assignment_schema_errors(item)
                 for item in plan_bound_assignment_rows)),
        ("working heartbeat preserves and conforms with the authentic running attempt",
         planned_working_row.get("status") == "working"
         and len(planned_working_row.get("attempts", [])) == 1
         and planned_working_row["attempts"][0].get("state") == "running"
         and not assignment_schema_errors(planned_working_row)
         and unlaunched_working_rejected),
        ("assignment contract rejects unknown and missing fields",
         bool(assignment_schema_errors(assignment_unknown))
         and bool(assignment_schema_errors(assignment_missing))),
        ("assignment contract rejects bool-as-integer and invalid timestamps",
         bool(assignment_schema_errors(assignment_bool_number))
         and bool(assignment_schema_errors(assignment_bad_timestamp))),
        ("new assignments materialize a bounded typed child tool-call limit",
         assigned_schema_row.get("tool_call_limit") == DEFAULT_AGENT_TOOL_CALL_LIMIT
         and bool(assignment_schema_errors(assignment_bool_tool_limit))
         and bool(assignment_schema_errors(assignment_small_tool_limit))),
        ("new assignments freeze the exact typed lane request budget",
         all(
             row.get("request_budget") == next(
                 lane["work_plan_lane"].get("request_budget")
                 for lane in generated_plan_rows
                 if lane["work_plan_lane"].get("id") == row.get("lane_id"))
             for row in plan_bound_assignment_rows
         )
         and bool(assignment_schema_errors(assignment_bool_request_budget))
         and bool(assignment_schema_errors(assignment_negative_request_budget))),
        ("assignment contract enforces assignment/review/root state fields",
         bool(assignment_schema_errors(assignment_with_stale_attempt))
         and bool(assignment_schema_errors(merged_without_review_binding))
         and bool(assignment_schema_errors(reviewer_without_result_binding))
         and bool(assignment_schema_errors(execution_with_reviewer_binding))),
        ("assignment attempts resolve exact nested receipt contract",
         bool(assignment_schema_errors(receipt_unknown_nested))
         and bool(assignment_schema_errors(receipt_bool_length_nested))),
        ("assignment role freezes the exact nested Agent type",
         bool(assignment_schema_errors(hunter_with_reviewer_type))
         and bool(assignment_schema_errors(reviewer_with_hunter_type))),
        ("corrupt loop journal fails closed before assignment/lifecycle mutation",
         journal_tamper_assignment_rejected
         and journal_tamper_lifecycle_rejected
         and journal_tamper_preserved_assignments),
        ("legacy main list exits 0", legacy_list_exit == 0),
        ("legacy main --new exits 0", legacy_new_exit == 0),
        ("assign command exits 0", assign_cli_exit == 0),
        ("target-facing assignment requires an explicit asset package",
         explicit_assets_required),
        ("hunter alias cannot create an empty target assignment",
         hunter_alias_requires_assets),
        ("unknown Agent role is rejected instead of becoming a legacy lane",
         unknown_role_rejected),
        ("invalid disposition note is rejected before state mutation",
         invalid_disposition_rejected),
        ("blocked disposition requires the literal Reason label",
         missing_reason_rejected),
        ("blocked disposition requires the literal canonical Front label",
         missing_front_rejected),
        ("malformed finish attempts preserve assignment bytes",
         malformed_finish_preserves_state),
        ("terminal disposition rewrite requires explicit amendment",
         silent_terminal_rewrite_rejected),
        ("explicit disposition amendment preserves prior audit state",
         disposition_history_preserved),
        ("heartbeat cannot write a terminal disposition",
         heartbeat_cannot_set_terminal),
        ("done assignment can advance to an adjudicated terminal state",
         done_to_adjudicated_allowed),
        ("missing disposition validator fails closed",
         receipts_missing_fails_closed),
        ("zero-tool Agent cannot be marked merged", zero_activity_merge_blocked),
        ("partial asset package cannot be marked merged", partial_asset_merge_blocked),
        ("every asset action settles before later canonical promotion",
         full_asset_merge_allowed),
        ("delegate capacity error names the exact limiting budget",
         exact_capacity_diagnostic == (
             "DELEGATE_CAPACITY_INSUFFICIENT: lane=L-EXPENSIVE; "
             "merge_capacity required=20 provided=1")),
        ("planner output is committed unchanged before delegation",
         planner_commit_exit == 0
         and generated_plan_lanes == planned_plan.get("lanes")
         and '"lane_count": 6' in planner_commit_output.getvalue()
         and '"objective": "exercise serial review closure"'
            in planner_commit_output.getvalue()
         and '"topology_mode": "SERIAL_AGENT"'
            in planner_commit_output.getvalue()
         and '"mode_matches_topology": true' in planner_commit_output.getvalue()
         and '"fronts": [' in planner_commit_output.getvalue()
         and planned_hunter_batch.get("schema") == "xunji.delegate-batch.v1"
         and planned_hunter_batch["assignments"][0].get("lane_id")
         == generated_plan_lanes[0]["id"]),
        ("Hunter and Reviewer launch prompts reconstruct from persisted assignments",
         planned_hunter_prompt_reconstructs
         and planned_reviewer_prompt_reconstructs),
        ("denied wrong Reviewer prompt replays the durable assigned contract",
         planned_reviewer_replay_is_idempotent
         and planned_reviewer_replay_routes_without_cancel
         and planned_reviewer_cancel_still_forbidden
         and planned_reviewer_bundle_tamper_blocks_replay
         and planned_reviewer_binding_tamper_blocks_replay),
        ("transcript-proven interrupted Reviewer Start auto-recovers and replays",
         interrupted_reviewer_auto_replay),
        ("plan-bound Reviewer cannot delegate before Hunter runtime return",
         reviewer_before_return_blocked),
        ("stale settlement is available only through delegate, not direct assign",
         stale_turn_only_detected
         and stale_direct_reviewer_assign_blocked
         and stale_premature_replan_blocked
         and planned_reviewer_batch.get("input_freshness")
            == "stale-settlement-only"
         and planned_reviewer_batch["assignments"][0].get("lane_id")
            == generated_plan_lanes[1]["id"]),
        ("plan-bound context path is attempt-unique and freezes exact bindings",
         ".attempt-001.md" in str(planned_hunter.get("context") or "")
         and f"Plan digest: {planned_plan['plan_digest']}" in planned_reviewer_context.read_text(
             encoding="utf-8")
         and f"Hard tool-call limit: {DEFAULT_AGENT_TOOL_CALL_LIMIT}" in planned_reviewer_context.read_text(
             encoding="utf-8")
         and planned_hunter["agent"] in planned_reviewer_context.read_text(encoding="utf-8")),
        ("Hunter return creates a plan/lane/result-bound merge draft",
         planned_draft.get("schema") == "xunji.merge-draft.v1"
         and planned_draft.get("lane_id") == generated_plan_lanes[0]["id"]
         and planned_draft.get("result_digest")),
        ("immutable result snapshot contains the full Agent response, not launch ack",
         hunter_snapshot_is_full_response),
        ("immutable result snapshot tamper invalidates Reviewer admission",
         immutable_snapshot_tamper_rejected),
        ("mutable Agent scaffold changes do not replace the frozen result",
         scaffold_mutation_does_not_change_frozen_result),
        ("Reviewer return without review disposition cannot delegate next execution",
         reviewer_unreviewed_blocks_next),
        ("returned Reviewer writes an exact review disposition receipt",
         planned_review_receipt.get("schema") == "xunji.review-disposition.v1"
         and planned_review_receipt.get("reviewer_assignment") == planned_reviewer["agent"]),
        ("needs-control completes review of frozen bytes before Root settlement",
         planned_action_receipt.get("disposition") == "needs-control"
         and planned_action_draft.get("review_status") == "complete"),
        ("non-target planner lane merges without a fabricated target receipt",
         planned_merge.get("coverage_merge_satisfied") is True
         and (planned_merge.get("coverage_merge") or {}).get("non_target_effect")
         == "local_read"
         and set((planned_merge.get("coverage_merge") or {}).get("assets", {}))
         == {"fixture.example"}
         and _runtime_receipts.agent_asset_activity(
             planned_run, planned_hunter["agent"]).get("fixture.example") == 0),
        ("Root merge follows review and unlocks the next planner execution lane",
         planned_merge.get("status") == "merged"
         and planned_disposition.get("disposition_satisfied") is True
         and stale_plan_next_execution_blocked
         and steering_replan.get("inputs_digest")
            == _work_plan.input_fingerprint(planned_run)[0]
         and planned_next_batch.get("input_freshness") == "current"
         and planned_next_batch.get("plan_digest")
            == steering_replan.get("plan_digest")
         and planned_next_batch["assignments"][0].get("lane_id")
         == generated_plan_lanes[2]["id"]
         and planned_next_batch["assignments"][0].get("effect") == "target"),
        ("Root finish keeps the front open until every committed lane settles",
         "NEXT_OWNER_ACTION" in planned_continuation_notice
         and "keep its front open" in planned_continuation_notice
         and "replan_reason" in planned_continuation_notice
         and "commit-proposal" in planned_continuation_notice
         and "inherits completed lanes" in planned_continuation_notice),
        ("generated replan inherits the exact completed lane prefix",
         inherited_completed_lanes
            == ["L-F-010-OFFLINE", "L-F-010-OFFLINE-REVIEW"]
         and [item.get("id") for item in replanned_lanes]
            == [item.get("id") for item in generated_plan_lanes[2:]]
         and replanned_lanes[0].get("dependencies") == []),
        ("later replan inherits settled prefix across transaction lineage",
         transitive_inherited_lanes
            == ["L-F-010-OFFLINE", "L-F-010-OFFLINE-REVIEW"]
         and [item.get("id") for item in transitive_replanned_lanes]
            == [item.get("id") for item in generated_plan_lanes[2:]]
         and transitive_replanned_lanes[0].get("dependencies") == []),
        ("changed dependency identity is never inherited from historical settlement",
         dependency_changed_inherited_lanes == ["L-F-010-OFFLINE"]
         and [item.get("id") for item in dependency_changed_replanned_lanes]
            == [item.get("id") for item in changed_dependency_lanes[1:]]
         and dependency_changed_replanned_lanes[0].get("dependencies") == []),
        ("replan preserves prior-plan frozen Reviewer admission",
         _review_receipt_complete(planned_run, planned_hunter)),
        ("Single Synthesizer cannot be fanned out as an Agent role",
         synthesizer_assignment_rejected),
        ("status command exits 0", status_cli_exit == 0),
        ("empty status command exits 0", empty_status_cli_exit == 0),
        ("driver-facing legacy/status output routes to typed Agent Board",
         "workers.py assign" not in driver_output.getvalue()
         and "general-purpose" not in driver_output.getvalue()
         and "commit the current typed plan" in driver_output.getvalue()
         and "legacy-only, non-authorizing" in driver_output.getvalue()),
        ("agent-check empty run exits 0", agent_check_empty_exit == 0),
        ("agent-check clean scaffold has no issues", agent_clean_issues == []),
        ("agent scaffold includes personalized RDT controls",
         "Loop budget:" in agent_clean_text
         and "Operator Profile / RDT Controls" in agent_clean_text
         and "Context SHA-256:" in agent_clean_text
         and "Composed role SHA-256:" in agent_clean_text
         and "Final Return" in agent_clean_text
         and "cleanup" in agent_clean_text.lower()
         and "outbound" in agent_clean_text.lower()
         and agent_clean_rec.get("reasoning_style") == "personalized-rdt"),
        ("agent scaffold routes launch and settlement without duplicating argv",
         "XUNJI_ASSIGNMENT=" not in agent_clean_text
         and "workers.py finish" not in agent_clean_text
         and "workers.py delegate" not in agent_clean_text
         and "Root owns launch, review, canonical adjudication" in agent_clean_text),
        ("merge-threats writes Root-owned hypothesis",
         threat_merge["new"] == 1
         and "Threat hypothesis: signed client param can be replayed across users" in threat_hyp_text
         and "Linked IS/C/E: IS-001" in threat_hyp_text),
        ("merge-threats skips duplicate suggestions", threat_merge_dup["new"] == 0),
        ("agent-check catches bad threat hypothesis fields",
         any(i["kind"] == "threat-missing-scope" for i in threat_bad_issues)
         and any(i["kind"] == "threat-unanchored" for i in threat_bad_issues)
         and any(i["kind"] == "agent-promoted-threat" for i in threat_bad_issues)),
        ("agent-check catches target artifact project label",
         any(i["kind"] == "target-artifact-opsec-name" for i in threat_bad_issues)),
        ("agent-check catches target cleanup requiring yes",
         any(i["kind"] == "target-cleanup-requires-yes" for i in threat_bad_issues)),
        ("agent-check catches invalid instruction provenance",
         any(i["kind"] == "missing-instruction-provenance"
             for i in rdt_bad_issues)),
        ("status sync: complete file flips assignment to done",
         sync_rows and sync_rows[0].get("status") == "done"
         and sync_state["assignments"][0].get("status") == "done"),
        ("status sync: Findings section flips assignment to done",
         findings_rows and findings_rows[0].get("status") == "done"
         and findings_state["assignments"][0].get("status") == "done"),
        ("status sync: empty Findings section stays assigned",
         blank_rows and blank_rows[0].get("status") == "assigned"
         and blank_state["assignments"][0].get("status") == "assigned"),
        ("status sync: negative Findings summary flips assignment to done",
         neg_rows and neg_rows[0].get("status") == "done"
         and neg_state["assignments"][0].get("status") == "done"),
        ("status sync: investigatory placeholder stays assigned",
         placeholder_rows and placeholder_rows[0].get("status") == "assigned"
         and placeholder_state["assignments"][0].get("status") == "assigned"),
        ("lifecycle: assigned agent hard-fails closure",
         any(i["kind"] == "agent-not-terminal" and i["severity"] == "error" for i in lifecycle_open)),
        ("lifecycle: heartbeat records running state",
         lifecycle_running_state["assignments"][0].get("status") == "running"
         and lifecycle_running_state["assignments"][0].get("last_note") == "started"),
        ("lifecycle: plan-bound running guidance never tells Root to write done",
         any(
             issue.get("kind") == "agent-not-terminal"
             and "不得由 Root finish 为 done" in str(issue.get("detail") or "")
             and "SubagentStop" in str(issue.get("detail") or "")
             for issue in planned_running_issues
         )),
        ("lifecycle: done remains an adjudication blocker and patches agent file",
         any(i["kind"] == "agent-done-unadjudicated" for i in lifecycle_closed)
         and "Status: done" in lifecycle_text and "returned coda" in lifecycle_text),
        ("role alias web uses web-hunter template", "Missing role template" not in web_context.read_text(encoding="utf-8")),
        ("agent assignment writes context pack", context_exists),
        ("assignments.json records agent", any(a.get("agent") == a1["agent"] for a in load_assignments(run)["assignments"])),
        ("agent-check catches missing loop/safety sections",
         any(i["kind"] == "missing-loop-section" for i in agent_issues)
         and any(i["kind"] == "missing-guard-reminder" for i in agent_issues)),
        ("agent-check catches non-synthesizer finding/closure",
         any(i["kind"] == "agent-promoted-finding" for i in agent_issues)
         and any(i["kind"] == "agent-wrote-final-conclusion" for i in agent_issues)),
        ("agent-check catches high-confidence candidate missing control/artifact",
         any(i["kind"] == "agent-missing-control" for i in agent_issues)
         and any(i["kind"] == "missing-artifact-pointer" for i in agent_issues)),
        ("conflicts detects support/refute contradiction",
         any(c.get("type") == "direct contradiction" for c in conflict_doc["conflicts"])),
        ("direct contradiction alone does not create confidence mismatch",
         not any(c.get("type") == "confidence mismatch" and c.get("front") == "F-001"
                 for c in conflict_doc["conflicts"])),
        ("conflicts detects same-polarity duplicate",
         any(c.get("type") == "duplicate" and c.get("front") == "F-002" for c in conflict_doc["conflicts"])),
        ("conflicts detects same-polarity confidence mismatch",
         any(c.get("type") == "confidence mismatch" and c.get("front") == "F-002"
             for c in conflict_doc["conflicts"])),
        ("conflicts detects same-polarity artifact mismatch",
         any(c.get("type") == "artifact mismatch" and c.get("front") == "F-002"
             for c in conflict_doc["conflicts"])),
        ("unchanged conflict projection preserves bytes and work-plan fingerprint",
         conflict_projection_is_idempotent),
        ("semantic conflict change updates the work-plan fingerprint",
         semantic_conflict_change_stales_fingerprint),
        ("concurrent conflict projection compare/write is linear",
         concurrent_conflict_projection_is_linear),
        ("duplicate conflict keys rebuild with an explicit diagnostic",
         duplicate_keys_rebuild_with_diagnostic),
        ("invalid conflict timestamps rebuild with an explicit diagnostic",
         malformed_timestamp_rebuilds_with_diagnostic),
        ("future conflict schema fails closed without downgrade",
         future_conflict_schema_fails_closed),
        ("unknown conflict fields fail closed without loss",
         unknown_conflict_field_fails_closed),
        ("conflict symlink is rebuilt in-run and bound by work-plan fingerprint",
         conflict_symlink_rebuilt_and_bound),
        ("synthesis rejects future conflict projection schema",
         strict_synthesize_rejects_future_projection),
        ("synthesis rejects unknown conflict projection fields",
         strict_synthesize_rejects_unknown_projection),
        ("synthesis draft is advisory not canonical", synth_doc.get("canonical") == "markdown remains source of truth"),
        ("synthesis treats placeholder control as missing", a3["agent"] in synth_doc["needs_control"]),
        ("synthesis carries unresolved conflicts", synth_doc["summary"]["unresolved_conflicts"] >= 1),
    ]
    bad = [n for n, ok in checks if not ok]
    for n, ok in checks:
        print(("ok   " if ok else "FAIL ") + n)
    print("workers selftest " + ("passed" if not bad else f"FAILED ({len(bad)})"))
    return 0 if not bad else 1


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if "--selftest" in argv:
        return _selftest()

    if argv and argv[0] in COMMANDS:
        cmd = argv.pop(0)
        ap = argparse.ArgumentParser(description=f"workers.py {cmd}")
        if cmd == "new":
            ap.add_argument("run_dir", type=Path)
            ap.add_argument("front")
        elif cmd == "commit-plan":
            ap.add_argument("run_dir", type=Path)
            ap.add_argument("--stage", required=True, choices=sorted(_work_plan.STAGES))
            ap.add_argument("--objective", required=True)
            ap.add_argument(
                "--mode", required=True,
                choices=["SERIAL_AGENT", "PARALLEL_AGENTS"],
            )
            ap.add_argument("--reason", required=True)
            ap.add_argument("--exit-gate", required=True)
            ap.add_argument("--replan-reason", default="")
            ap.add_argument("--limit", type=int, default=2)
        elif cmd == "commit-proposal":
            ap.add_argument("run_dir", type=Path)
        elif cmd == "delegate":
            ap.add_argument("run_dir", type=Path)
            ap.add_argument("--runtime-slots", type=int, default=2)
            ap.add_argument("--request-budget", type=int, default=10)
            ap.add_argument("--model-egress-budget", type=int, default=1)
            ap.add_argument("--merge-capacity", type=int, default=100)
            ap.add_argument("--limit", type=int, default=2)
            ap.add_argument(
                "--tool-call-limit", type=int,
                default=DEFAULT_AGENT_TOOL_CALL_LIMIT)
        elif cmd == "assign":
            ap.add_argument("run_dir", type=Path)
            ap.add_argument("--role", required=True)
            ap.add_argument("--front", required=True)
            ap.add_argument("--scope", default="")
            ap.add_argument("--asset", action="append", default=[],
                            help="exact coverage asset assigned to this Agent; repeat for a bounded asset pack")
            ap.add_argument("--lane", default="",
                            help="exact L-* lane from the current xunji.work-plan.v1")
        elif cmd == "cancel-unlaunched":
            ap.add_argument("run_dir", type=Path)
            ap.add_argument("assignment")
            ap.add_argument("--reason", required=True)
        elif cmd == "heartbeat":
            ap.add_argument("run_dir", type=Path)
            ap.add_argument("agent")
            ap.add_argument("--status", default="running",
                            choices=sorted(NONTERMINAL_AGENT_STATUSES - {"?"}))
            ap.add_argument("--note", default="")
        elif cmd == "finish":
            ap.add_argument("run_dir", type=Path)
            ap.add_argument("agent")
            ap.add_argument("--status", default="done", choices=sorted(TERMINAL_AGENT_STATUSES))
            ap.add_argument("--note", default="")
            ap.add_argument("--amend", action="store_true",
                            help="replace an existing terminal disposition and preserve its history")
        elif cmd == "review-disposition":
            ap.add_argument("run_dir", type=Path)
            ap.add_argument("target")
            ap.add_argument("reviewer")
            ap.add_argument("--status", required=True, choices=sorted(REVIEW_DISPOSITIONS))
            ap.add_argument("--note", required=True)
        elif cmd == "lifecycle-check":
            ap.add_argument("run_dir", type=Path)
            ap.add_argument("--closure", action="store_true",
                            help="treat non-terminal/stale Agents as hard errors for closure")
        elif cmd == "status":
            ap.add_argument("run_dir", type=Path)
            ap.add_argument(
                "--all", action="store_true",
                help="print the complete assignment ledger instead of the bounded active/recent view")
        else:
            ap.add_argument("run_dir", type=Path)
        if cmd in {"suggest", "plan"}:
            ap.add_argument("--limit", type=int, default=(3 if cmd == "plan" else None))
        if cmd == "plan":
            ap.add_argument(
                "--stage", choices=["S1", "S2", "S3"],
                help=(
                    "seed the selected stage profile; omitted leaves macro_stage "
                    "for Root to choose and preserves the conservative S2 lane shape"),
            )
        args = ap.parse_args(argv)
        run_dir = resolve_run_dir(args.run_dir)
        if not run_dir.exists():
            print(f"[workers] run 目录不存在: {run_dir}", file=sys.stderr)
            return 1
        if cmd == "list":
            return print_list(run_dir)
        if cmd == "new":
            path = create_worker(run_dir, args.front)
            print(f"[workers] 新建 {display_path(path)} → 指派 front {args.front}")
            return 0
        if cmd == "assign":
            return print_assign(
                run_dir, args.role, args.front, args.scope, args.asset, args.lane)
        if cmd == "commit-plan":
            return print_commit_plan(
                run_dir,
                stage=args.stage,
                objective=args.objective,
                mode=args.mode,
                reason=args.reason,
                exit_gate=args.exit_gate,
                replan_reason=args.replan_reason,
                limit=args.limit,
            )
        if cmd == "commit-proposal":
            return print_commit_proposal(run_dir)
        if cmd == "delegate":
            return print_delegate(
                run_dir,
                runtime_slots=args.runtime_slots,
                request_budget=args.request_budget,
                model_egress_budget=args.model_egress_budget,
                merge_capacity=args.merge_capacity,
                limit=args.limit,
                tool_call_limit=args.tool_call_limit,
            )
        if cmd == "cancel-unlaunched":
            return print_cancel_unlaunched(
                run_dir, args.assignment, args.reason)
        if cmd == "heartbeat":
            return print_heartbeat(run_dir, args.agent, args.status, args.note)
        if cmd == "finish":
            return print_finish(run_dir, args.agent, args.status, args.note, args.amend)
        if cmd == "review-disposition":
            return print_review_disposition(
                run_dir, args.target, args.reviewer, args.status, args.note)
        if cmd == "lifecycle-check":
            return print_lifecycle_check(run_dir, closure=args.closure)
        if cmd == "status":
            return print_status(run_dir, show_all=args.all)
        if cmd == "agent-check":
            return print_agent_check(run_dir)
        if cmd == "suggest":
            return print_suggest(run_dir, args.limit)
        if cmd == "plan":
            return print_plan(run_dir, args.limit, stage=args.stage)
        if cmd == "merge-check":
            return print_merge_check(run_dir)
        if cmd == "conflicts":
            return print_conflicts(run_dir)
        if cmd == "synthesize":
            return print_synthesize(run_dir)
        if cmd == "merge-constraints":
            return print_merge_constraints(run_dir)
        if cmd == "merge-threats":
            return print_merge_threats(run_dir)

    ap = argparse.ArgumentParser(
        description="并行 worker 脚手架 + 合并台账(不编排)",
        epilog="new commands: list, new, suggest, plan, merge-check. "
               "Legacy forms remain: workers.py RUN_DIR and workers.py RUN_DIR --new F-005.",
    )
    ap.add_argument("run_dir", type=Path)
    ap.add_argument("--new", metavar="F-ID", help="开一个新 worker 脚手架, 指派给该 front")
    args = ap.parse_args(argv)
    run_dir = resolve_run_dir(args.run_dir)
    if not run_dir.exists():
        print(f"[workers] run 目录不存在: {run_dir}", file=sys.stderr)
        return 1

    if args.new:
        path = create_worker(run_dir, args.new)
        print(f"[workers] 新建 {display_path(path)} → 指派 front {args.new}")
        print("  legacy-only, non-authorizing scaffold. Current execution must load "
              "xunji-agent-board, commit a typed plan, and delegate a ready lane; "
              "do not launch this compatibility artifact directly.")
        return 0

    return print_list(run_dir)


if __name__ == "__main__":
    raise SystemExit(main())
