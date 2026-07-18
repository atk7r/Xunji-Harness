#!/usr/bin/env python3
"""Canonical parser for Xunji run control-plane state.

Markdown remains the operator-readable source of truth, but every consumer must
interpret it through this module.  Keeping status/barrier parsing here prevents
the loop controller, Agent gate, workers, and statusline from disagreeing about
the same front.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
import tempfile
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path


OPEN_STATUSES = {"open", "probing", "working", "blocked_type_a"}
TERMINAL_STATUSES = {
    "closed", "closing", "final", "done", "complete", "completed",
    "blocked_type_b", "deferred",
}
TRIVIAL_BARRIERS = {"", "none", "unknown", "n/a", "-"}
HWS = r"[^\S\n]"
MACRO_STAGES = ("S1", "S2", "S3")
_HEX64 = re.compile(r"[0-9a-f]{64}")
_LANE_ID = re.compile(r"L-[A-Za-z0-9._-]+")
_ASSIGNMENT_ID = re.compile(r"A-[A-Za-z0-9._-]+")
_TERMINAL_ROOT_DISPOSITIONS = {"merged", "blocked", "failed", "abandoned"}
_REVIEW_RECEIPT_FIELDS = {
    "schema", "target_assignment", "target_result_digest",
    "reviewer_assignment", "reviewer_agent_id", "reviewer_tool_use_id",
    "reviewer_result_digest", "plan_digest", "target_lane_id",
    "reviewer_lane_id", "disposition", "note", "recorded_at", "receipt_hash",
}
_REVIEW_DISPOSITIONS = {
    "accept-candidate", "needs-control", "duplicate", "refute",
    "out-of-scope", "retry", "blocked",
}
_MERGE_DRAFT_FIELDS = {
    "schema", "assignment", "role", "front", "assets", "effect", "plan_id",
    "plan_digest", "lane_id", "assignment_attempt", "runtime_attempt", "result",
    "result_digest", "outcome", "per_asset_outcomes", "review_status",
    "review_receipt", "updated_at",
}


@dataclass(frozen=True)
class Front:
    id: str
    title: str
    section: str
    status: str
    status_raw: str
    barrier: str
    depth: str
    text: str
    schema_errors: tuple[str, ...]

    @property
    def is_open(self) -> bool:
        return self.status in OPEN_STATUSES

    @property
    def is_deferred(self) -> bool:
        return self.status == "deferred"

    @property
    def is_closed(self) -> bool:
        return self.status in TERMINAL_STATUSES - {"deferred"}


def _field(block: str, name: str) -> str:
    match = re.search(
        rf"(?im)^{HWS}*[-*]?{HWS}*{re.escape(name)}{HWS}*[:：]{HWS}*([^\n]*)$",
        block,
    )
    return match.group(1).strip() if match else ""


def normalize_status(raw: object) -> str:
    """Return one canonical status from a field value or section label."""
    value = str(raw or "").strip().lower().replace("-", "_")
    tokens = set(re.findall(r"[a-z0-9_]+", value))
    if "closed_type_b" in tokens:
        tokens.add("closed")
    terminal = tokens & TERMINAL_STATUSES
    if "deferred" in terminal and terminal - {"deferred"}:
        return "unknown"
    if "blocked_type_b" in tokens:
        return "blocked_type_b"
    for preferred in ("closing", "final", "completed", "complete", "done", "closed"):
        if preferred in tokens:
            return preferred
    if "deferred" in tokens:
        return "deferred"
    if "blocked_type_a" in tokens:
        return "blocked_type_a"
    for preferred in ("probing", "working", "open"):
        if preferred in tokens:
            return preferred
    primary = re.split(r"[|,;；(（]", value, maxsplit=1)[0].strip()
    return primary or "unknown"


def _inline_component(raw: str, name: str) -> str:
    match = re.search(rf"(?i)(?:^|\|)\s*{re.escape(name)}\s*[:：]\s*([^|]+)", raw)
    return match.group(1).strip() if match else ""


def _sections(text: str) -> list[tuple[str, str]]:
    out: list[tuple[str, str]] = []
    matches = list(re.finditer(r"(?m)^##[ \t]+([^#\n]+?)[ \t]*$", text))
    if not matches:
        return [("Unknown", text)]
    prefix = text[:matches[0].start()]
    if re.search(r"(?m)^###[ \t]+F-\d+\b", prefix):
        out.append(("Unknown", prefix))
    for idx, match in enumerate(matches):
        end = matches[idx + 1].start() if idx + 1 < len(matches) else len(text)
        out.append((match.group(1).strip(), text[match.end():end]))
    return out


def parse_fronts(run_dir: str | Path) -> list[Front]:
    run = Path(run_dir)
    path = run / "frontier.md"
    if not path.exists():
        return []
    text = path.read_text(encoding="utf-8", errors="replace")
    text = re.sub(r"(?ms)^(```|~~~)[^\n]*\n.*?^\1[ \t]*\n?", "", text)
    fronts: list[Front] = []
    for section, body in _sections(text):
        blocks = list(re.finditer(r"(?ms)^###[ \t]+(F-\d+)\b([^\n]*)(.*?)(?=^###[ \t]+F-\d+\b|\Z)", body))
        for match in blocks:
            fid = match.group(1)
            title = (fid + match.group(2)).strip(" -—\t")
            block = match.group(0)
            raw_status = _field(block, "Status")
            section_status = (
                "open" if section.lower().startswith("open")
                else "deferred" if section.lower().startswith("deferred")
                else "closed" if section.lower().startswith("closed")
                else "unknown"
            )
            status = normalize_status(raw_status or section_status)
            barrier = _field(block, "Barrier class")
            depth = _field(block, "Current depth")
            errors: list[str] = []
            if not raw_status:
                errors.append("missing canonical `Status:` field")
            if raw_status and section_status != "unknown":
                section_open = section_status == "open"
                if section_open != (status in OPEN_STATUSES):
                    errors.append(
                        f"Status `{status}` conflicts with `{section}` section")
            if not barrier:
                barrier = _inline_component(raw_status, "Barrier") or "unknown"
                errors.append("missing canonical `Barrier class:` field")
            if not depth:
                depth = _inline_component(raw_status, "Depth") or "unknown"
                errors.append("missing canonical `Current depth:` field")
            if "|" in raw_status:
                errors.append("compound `Status:` line must be split into canonical fields")
            if status == "unknown":
                errors.append("unclassified Status")
            fronts.append(Front(
                id=fid,
                title=title or fid,
                section=section,
                status=status,
                status_raw=raw_status,
                barrier=barrier.strip().lower().replace(" ", "_"),
                depth=depth.strip().lower(),
                text=block,
                schema_errors=tuple(dict.fromkeys(errors)),
            ))
    return fronts


def summary(run_dir: str | Path) -> dict:
    fronts = parse_fronts(run_dir)
    opened = [front for front in fronts if front.is_open]
    barriers = sorted({front.barrier for front in opened if front.barrier not in TRIVIAL_BARRIERS})
    barrier_counts = {
        barrier: sum(1 for front in opened if front.barrier == barrier)
        for barrier in barriers
    }
    all_share_one_barrier = bool(opened) and any(
        count == len(opened) for count in barrier_counts.values()
    )
    fanout_required = len(opened) >= 4 and not all_share_one_barrier
    schema_errors = [
        f"{front.id}: {error}"
        for front in fronts
        for error in front.schema_errors
    ]
    ids = [front.id for front in fronts]
    for duplicate in sorted({fid for fid in ids if ids.count(fid) > 1}):
        schema_errors.append(f"{duplicate}: duplicate front id")
    return {
        "fronts": [asdict(front) for front in fronts],
        "open": [front.id for front in opened],
        "open_count": len(opened),
        "deferred": [front.id for front in fronts if front.is_deferred],
        "closed": [front.id for front in fronts if front.is_closed],
        "barriers": barriers,
        "diverse_barriers": not all_share_one_barrier,
        "fanout_required": fanout_required,
        "schema_errors": schema_errors,
    }


def _sha256_json(value: object) -> str:
    return hashlib.sha256(json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
    ).encode("utf-8")).hexdigest()


def _meaningful_markdown(path: Path) -> bool:
    if not path.is_file():
        return False
    text = path.read_text(encoding="utf-8", errors="replace")
    text = re.sub(r"(?s)<!--.*?-->", "", text)
    text = re.sub(r"(?m)^\s*#{1,6}\s+.*$", "", text)
    text = re.sub(r"<[^>]*>", "", text)
    return bool(re.search(r"[A-Za-z0-9\u4e00-\u9fff]", text))


def _coverage_state(run: Path) -> tuple[bool, str, str]:
    """Return (ready, detail, digest) for the canonical coverage projection."""
    candidates = [run / "coverage.json", *sorted(run.glob("**/coverage.json"))]
    seen: set[Path] = set()
    for path in candidates:
        try:
            resolved = path.resolve()
            resolved.relative_to(run)
        except (OSError, RuntimeError, ValueError):
            continue
        if resolved in seen or not resolved.is_file():
            continue
        seen.add(resolved)
        try:
            value = json.loads(resolved.read_text(encoding="utf-8", errors="strict"))
        except Exception:
            return False, f"{resolved.relative_to(run)} is unreadable", ""
        if not isinstance(value, dict) or not isinstance(value.get("assets"), list):
            return False, f"{resolved.relative_to(run)} lacks an assets list", ""
        if any(not isinstance(item, dict) for item in value["assets"]):
            return False, f"{resolved.relative_to(run)} contains a non-object asset", ""
        if not value["assets"]:
            return False, f"{resolved.relative_to(run)} has an empty assets list", ""
        return True, resolved.relative_to(run).as_posix(), _sha256_json(value)
    return False, "coverage.json is missing", ""


def _load_merge_draft(run: Path, assignment: str) -> dict:
    safe = re.sub(r"[^A-Za-z0-9._-]+", "-", assignment).strip("-")
    path = run / "state" / "merge_drafts" / f"{safe or 'invalid'}.json"
    try:
        value = json.loads(path.read_text(encoding="utf-8", errors="strict"))
    except Exception:
        return {}
    return value if isinstance(value, dict) else {}


def _normalized_role(value: object) -> str:
    role = str(value or "").strip().lower().replace("_", "-")
    return {"hunter": "web-hunter", "reviewer": "review"}.get(role, role)


def _load_assignment_rows(run: Path) -> tuple[list[dict], list[str]]:
    path = run / "state" / "assignments.json"
    if not path.exists():
        return [], []
    try:
        value = json.loads(path.read_text(encoding="utf-8", errors="strict"))
    except Exception:
        return [], ["assignments:unreadable"]
    rows = value.get("assignments") if isinstance(value, dict) else None
    if not isinstance(rows, list):
        return [], ["assignments:invalid"]
    if any(not isinstance(item, dict) for item in rows):
        return [item for item in rows if isinstance(item, dict)], ["assignment:non-object"]
    try:
        import runtime_receipts as contract_module
        contract_errors = contract_module.assignment_state_errors(
            value, parent_run=run.name)
    except Exception as exc:
        bound = any(
            any(str(item.get(field) or "") for field in (
                "plan_id", "plan_digest", "lane_id",
            ))
            for item in rows
        )
        contract_errors = [f"validator-unavailable:{exc.__class__.__name__}"] if bound else []
    return rows, ["assignments:contract-invalid:" + item for item in contract_errors]


def _load_plan_projection(run: Path, plan: dict | None = None) -> tuple[dict, list[str]]:
    if plan is None:
        try:
            value = json.loads((run / "state" / "work_plan.json").read_text(
                encoding="utf-8", errors="strict"))
        except FileNotFoundError:
            return {}, []
        except Exception:
            return {}, ["work-plan:unreadable"]
    else:
        value = plan
    if not isinstance(value, dict) or value.get("schema") != "xunji.work-plan.v1":
        return {}, ["work-plan:invalid-schema"]
    try:
        # ``work_plan`` is the current contract owner.  Resolve an already
        # running script module first to avoid loading a second copy when this
        # projection is called by ``tools/work_plan.py`` itself; standalone
        # run_model callers import it lazily so ordinary frontier parsing keeps
        # no mandatory planner dependency.
        contract_module = sys.modules.get("work_plan")
        main_module = sys.modules.get("__main__")
        if contract_module is None and main_module is not None \
                and Path(str(getattr(main_module, "__file__", ""))).resolve() \
                == Path(__file__).resolve().with_name("work_plan.py"):
            contract_module = main_module
        if contract_module is None:
            import work_plan as contract_module  # type: ignore[no-redef]
        strict_value = contract_module.validate_plan(value)
    except Exception as exc:
        detail = str(exc).splitlines()[0][:160] or exc.__class__.__name__
        return {}, ["work-plan:contract-invalid:" + detail]
    if strict_value != value:
        return {}, ["work-plan:non-canonical"]
    digest = str(value.get("plan_digest") or "")
    payload = dict(value)
    payload.pop("plan_digest", None)
    payload.pop("plan_id", None)
    if not _HEX64.fullmatch(digest) or digest != _sha256_json(payload):
        return {}, ["work-plan:digest-mismatch"]
    cycle = value.get("cycle_id")
    if isinstance(cycle, bool) or not isinstance(cycle, int) or cycle < 1 \
            or value.get("plan_id") != f"WP-{cycle}-{digest[:8]}":
        return {}, ["work-plan:id-mismatch"]
    lanes = value.get("lanes")
    if not isinstance(lanes, list) or not lanes:
        return {}, ["work-plan:lanes-invalid"]
    lane_ids = [str(item.get("id") or "") for item in lanes if isinstance(item, dict)]
    if len(lane_ids) != len(lanes) or len(set(lane_ids)) != len(lane_ids) \
            or any(not _LANE_ID.fullmatch(item) for item in lane_ids):
        return {}, ["work-plan:lane-ids-invalid"]
    return value, []


def _runtime_module():
    try:
        import runtime_receipts  # local import avoids a mandatory live-runtime dependency
    except Exception:
        return None
    return runtime_receipts


def _runtime_records(run: Path) -> tuple[list[dict], list[dict], list[str], object | None]:
    module = _runtime_module()
    if module is None:
        return [], [], ["runtime-receipts:unavailable"], None
    try:
        _, errors = module.validate_chain(run)
        if errors:
            return [], [], ["runtime-receipts:invalid-chain:" + errors[0]], module
        projection_error = run / "state" / "runtime_projection_error.json"
        if projection_error.exists():
            try:
                error_value = json.loads(projection_error.read_text(
                    encoding="utf-8", errors="strict"))
                detail = str(error_value.get("error") or "unknown projection error") \
                    if isinstance(error_value, dict) else "invalid projection error receipt"
            except Exception:
                detail = "unreadable projection error receipt"
            return [], [], ["runtime-receipts:projection-error:" + detail], module
        integrity_errors = module.agent_event_integrity_errors(run)
        if integrity_errors:
            return [], [], [
                "runtime-receipts:agent-event-integrity:" + integrity_errors[0]
            ], module
        attempts = [item for item in module.agent_attempts(run) if isinstance(item, dict)]
        failures = [
            item for item in module.failed_tool_events(run)
            if isinstance(item, dict) and item.get("tool_name") == "Agent"
        ]
    except Exception as exc:
        return [], [], [f"runtime-receipts:projection-error:{exc.__class__.__name__}"], module
    return attempts, failures, [], module


def _receipt_hash_valid(receipt: object) -> bool:
    if not isinstance(receipt, dict) or set(receipt) != _REVIEW_RECEIPT_FIELDS:
        return False
    if receipt.get("schema") != "xunji.review-disposition.v1" \
            or not _ASSIGNMENT_ID.fullmatch(str(receipt.get("target_assignment") or "")) \
            or not _ASSIGNMENT_ID.fullmatch(str(receipt.get("reviewer_assignment") or "")) \
            or receipt.get("target_assignment") == receipt.get("reviewer_assignment") \
            or not _HEX64.fullmatch(str(receipt.get("target_result_digest") or "")) \
            or not _HEX64.fullmatch(str(receipt.get("reviewer_result_digest") or "")) \
            or not _HEX64.fullmatch(str(receipt.get("plan_digest") or "")) \
            or not _LANE_ID.fullmatch(str(receipt.get("target_lane_id") or "")) \
            or not _LANE_ID.fullmatch(str(receipt.get("reviewer_lane_id") or "")) \
            or receipt.get("target_lane_id") == receipt.get("reviewer_lane_id") \
            or receipt.get("disposition") not in _REVIEW_DISPOSITIONS:
        return False
    for field, maximum in (
        ("reviewer_agent_id", 1024), ("reviewer_tool_use_id", 1024),
        ("note", 2048), ("recorded_at", 128),
    ):
        value = receipt.get(field)
        if not isinstance(value, str) or not value or len(value) > maximum \
                or any(ord(char) < 32 and char not in "\t\n" for char in value):
            return False
    try:
        if datetime.fromisoformat(
                receipt["recorded_at"].strip().replace("Z", "+00:00")).timestamp() <= 0:
            return False
    except Exception:
        return False
    claimed = str(receipt.get("receipt_hash") or "")
    unsigned = dict(receipt)
    unsigned.pop("receipt_hash", None)
    return bool(_HEX64.fullmatch(claimed) and claimed == _sha256_json(unsigned))


def _draft_result_valid(run: Path, draft: object, *, assignment: str,
                        plan_digest: str, lane_id: str, runtime_state: str,
                        runtime_record: dict) -> tuple[bool, str]:
    if not isinstance(draft, dict) or set(draft) != _MERGE_DRAFT_FIELDS \
            or draft.get("schema") != "xunji.merge-draft.v1" \
            or draft.get("assignment") != assignment \
            or draft.get("plan_digest") != plan_digest \
            or draft.get("lane_id") != lane_id:
        return False, "merge-draft-binding-invalid"
    runtime = draft.get("runtime_attempt") \
        if isinstance(draft.get("runtime_attempt"), dict) else {}
    if set(runtime) != {"agent_id", "tool_use_id", "state", "returned_at"}:
        return False, "merge-draft-runtime-attempt-invalid"
    expected_agent = str(runtime_record.get("agent_id") or "")
    expected_tool = str(runtime_record.get("tool_use_id") or "")
    expected_snapshot = runtime_record.get("result_snapshot") \
        if isinstance(runtime_record.get("result_snapshot"), dict) \
        else runtime_record.get("agent_result_snapshot") \
        if isinstance(runtime_record.get("agent_result_snapshot"), dict) else {}
    if any(
        not isinstance(runtime.get(field), str) or len(runtime.get(field)) > maximum
        for field, maximum in (
            ("agent_id", 1024), ("tool_use_id", 1024),
            ("state", 16), ("returned_at", 128),
        )
    ):
        return False, "merge-draft-runtime-attempt-invalid"
    if runtime_state not in {"returned", "failed"} \
            or draft.get("outcome") != runtime_state \
            or runtime.get("state") != runtime_state \
            or runtime.get("agent_id") != expected_agent \
            or runtime.get("tool_use_id") != expected_tool \
            or not expected_tool or not isinstance(runtime.get("returned_at"), str) \
            or not runtime.get("returned_at"):
        return False, "merge-draft-runtime-attempt-mismatch"
    if runtime_state == "returned" and not expected_agent:
        return False, "merge-draft-runtime-attempt-mismatch"
    if _iso_epoch(runtime.get("returned_at")) <= 0:
        return False, "merge-draft-runtime-attempt-mismatch"
    result = draft.get("result") if isinstance(draft.get("result"), dict) else {}
    if set(result) != {"path", "length", "sha256", "missing", "source"} \
            or not expected_snapshot \
            or any(result.get(key) != expected_snapshot.get(key) for key in result):
        return False, "merge-draft-runtime-snapshot-mismatch"
    if not isinstance(result.get("path"), str) \
            or isinstance(result.get("length"), bool) \
            or not isinstance(result.get("length"), int) \
            or result.get("length") < 0 \
            or not isinstance(result.get("sha256"), str) \
            or result.get("missing") is not False \
            or not isinstance(result.get("source"), str):
        return False, "merge-draft-runtime-snapshot-invalid"
    digest = str(draft.get("result_digest") or "")
    path = Path(str(result.get("path") or ""))
    try:
        resolved = path.resolve(strict=True)
        resolved.relative_to(run.resolve(strict=True))
        payload = resolved.read_bytes()
    except Exception:
        return False, "frozen-result-unavailable"
    actual = hashlib.sha256(payload).hexdigest()
    source = str(result.get("source") or "")
    if not _HEX64.fullmatch(digest) or actual != digest \
            or result.get("sha256") != digest \
            or result.get("length") != len(payload) \
            or result.get("missing") is not False \
            or source not in {
                "agent_tool_response", "agent_failure_response",
                "subagent_stop_response", "transcript_tool_result",
            }:
        return False, "frozen-result-digest-mismatch"
    attempt_id = str(runtime_record.get("attempt_id") or expected_agent or expected_tool)
    safe_assignment = re.sub(r"[^A-Za-z0-9._-]+", "-", assignment).strip("-")
    safe_attempt = re.sub(r"[^A-Za-z0-9._-]+", "-", attempt_id).strip("-")
    expected_path = (
        run / "state" / "merge_results" / (safe_assignment or "invalid")
        / f"{safe_attempt or 'attempt'}-{digest}.json"
    ).resolve(strict=False)
    if resolved != expected_path:
        return False, "frozen-result-path-mismatch"
    return True, ""


def _iso_epoch(value: object) -> float:
    try:
        return datetime.fromisoformat(
            str(value or "").strip().replace("Z", "+00:00")).timestamp()
    except Exception:
        return 0.0


def _auth_runtime_state(assignment: str, lane_id: str, plan_digest: str,
                        attempts: list[dict], failures: list[dict], *,
                        expected_subagent_type: str = "") -> tuple[str, dict, str]:
    candidates: list[tuple[float, str, dict]] = []
    for item in attempts:
        if item.get("assignment") == assignment and item.get("lane_id") == lane_id \
                and item.get("plan_digest") == plan_digest:
            candidates.append((float(item.get("launched_at") or 0.0),
                               str(item.get("state") or ""), item))
    for item in failures:
        if item.get("assignment") == assignment \
                and item.get("assignment_lane") == lane_id \
                and item.get("assignment_plan_digest") == plan_digest:
            candidates.append((float(item.get("ts") or 0.0), "failed", item))
    if not candidates:
        return "no-attempt", {}, ""
    if len(candidates) != 1:
        return "invalid-attempts", {}, "multiple-runtime-attempts"
    _, state, record = max(candidates, key=lambda item: item[0])
    if expected_subagent_type and str(
            record.get("subagent_type") or "") != expected_subagent_type:
        return "invalid-attempts", {}, "runtime-agent-type-mismatch"
    return (
        state if state in {"running", "returned", "failed"} else "no-attempt",
        record,
        "",
    )


def plan_cycle_projection(run_dir: str | Path, *, plan: dict | None = None) -> dict:
    """Recompute one exact plan cycle from plan lanes and immutable runtime receipts.

    No assignment projection, Agent prose, hand-written status, or caller-provided
    summary can create an attempt.  A cycle is complete only when every declared
    lane has one exact assignment, a transcript-backed runtime outcome, a frozen
    result, a content-addressed Reviewer receipt, and a Root disposition.
    """
    run = Path(run_dir).resolve()
    current, plan_errors = _load_plan_projection(run, plan)
    rows, row_errors = _load_assignment_rows(run)
    attempts, failures, runtime_errors, runtime_module = _runtime_records(run)
    merge_debt = [*plan_errors, *row_errors, *runtime_errors]
    review_debt: list[str] = []
    assigned_debt: list[str] = []
    if not current:
        bound_rows = [
            item for item in rows
            if str(item.get("plan_digest") or "") or str(item.get("lane_id") or "")
        ]
        for item in bound_rows:
            assignment = str(item.get("agent") or "(missing)")
            merge_debt.append(f"{assignment}:no-current-plan")
            review_debt.append(f"{assignment}:no-current-plan")
        return {
            "schema": "xunji.plan-cycle-projection.v1", "plan_id": "",
            "plan_digest": "", "lane_ids": [], "lane_states": [],
            "assignment_dispositions": [],
            "merge_disposition_summary": {
                "schema": "xunji.merge-disposition-summary.v1",
                "merged": [], "reviewed": [], "blocked": [], "failed": [],
                "abandoned": [], "pending": [],
            },
            "debt": {"merge": sorted(set(merge_debt)),
                     "review": sorted(set(review_debt))},
            "assigned_debt": sorted(set(assigned_debt)), "has_assignments": False,
        }

    digest = str(current["plan_digest"])
    lanes = [item for item in current["lanes"] if isinstance(item, dict)]
    lane_ids = [str(item.get("id") or "") for item in lanes]
    mode = str(current.get("execution_mode") or "")

    plan_rows = [
        item for item in rows if str(item.get("plan_digest") or "") == digest
    ]
    orphans = [
        str(item.get("agent") or "(missing)") for item in plan_rows
        if str(item.get("lane_id") or "") not in set(lane_ids)
    ]
    merge_debt.extend(f"{item}:orphan-plan-assignment" for item in orphans)
    assigned_debt.extend(f"{item}:orphan-plan-assignment" for item in orphans)
    if row_errors or runtime_errors:
        assigned_debt.extend([*row_errors, *runtime_errors])

    # ROOT_DIRECT is a separate, assignment-free execution contract.  It is
    # satisfied only by the runtime module's exact claim -> terminal projection;
    # never manufacture an Agent assignment, Reviewer receipt, or merge
    # disposition for a Root action.
    if mode == "ROOT_DIRECT":
        lane_id = lane_ids[0] if len(lane_ids) == 1 else "(invalid-root-lane)"
        root_receipt: dict = {}
        root_debt = ""
        if plan_rows:
            merge_debt.append(f"{lane_id}:root-action-unexpected-assignment")
            assigned_debt.extend(
                f"{str(item.get('agent') or lane_id)}:root-action-unexpected-assignment"
                for item in plan_rows
            )
        if not runtime_errors and runtime_module is not None \
                and hasattr(runtime_module, "root_action_receipt"):
            try:
                projected, root_debt = runtime_module.root_action_receipt(run, current)
                root_receipt = dict(projected) if isinstance(projected, dict) else {}
            except Exception as exc:
                root_debt = f"root-action-invalid:{exc.__class__.__name__}"
        elif not runtime_errors:
            root_debt = "root-action-projection-unavailable"
        if root_debt:
            merge_debt.append(f"{lane_id}:{root_debt}")
        outcome = str(root_receipt.get("outcome") or "")
        complete = bool(root_receipt and not root_debt and outcome in {"succeeded", "failed"})
        state = {
            "lane_id": lane_id,
            "role": _normalized_role(lanes[0].get("role")) if len(lanes) == 1 else "",
            "assignment": "",
            "runtime_state": outcome if complete else "pending",
            "disposition": outcome if complete else "pending",
            "result_digest": "",
            "review_receipt_hash": "",
            "complete": complete,
        }
        return {
            "schema": "xunji.plan-cycle-projection.v1",
            "plan_id": str(current.get("plan_id") or ""),
            "plan_digest": digest,
            "execution_mode": mode,
            "lane_ids": lane_ids,
            "lane_states": [state],
            "root_action_receipt": root_receipt if complete else {},
            "assignment_dispositions": [],
            "merge_disposition_summary": {
                "schema": "xunji.merge-disposition-summary.v1",
                "merged": [], "reviewed": [], "blocked": [], "failed": [],
                "abandoned": [], "pending": [],
            },
            "debt": {
                "merge": sorted(set(merge_debt)),
                "review": sorted(set(review_debt)),
            },
            "assigned_debt": sorted(set(assigned_debt)),
            "has_assignments": bool(plan_rows) or bool(row_errors),
        }

    states: dict[str, dict] = {}
    for lane in lanes:
        lane_id = str(lane.get("id") or "")
        role = _normalized_role(lane.get("role"))
        matching = [item for item in plan_rows if item.get("lane_id") == lane_id]
        state = {
            "lane_id": lane_id, "role": role, "assignment": "",
            "runtime_state": "unassigned", "disposition": "pending",
            "result_digest": "", "review_receipt_hash": "", "complete": False,
        }
        states[lane_id] = state
        if mode == "ROOT_DIRECT":
            continue
        if len(matching) != 1:
            reason = "unassigned" if not matching else "ambiguous-assignment"
            merge_debt.append(f"{lane_id}:{reason}")
            if matching:
                assigned_debt.extend(
                    str(item.get("agent") or lane_id) + ":ambiguous-assignment"
                    for item in matching
                )
            continue
        row = matching[0]
        assignment = str(row.get("agent") or "")
        state["assignment"] = assignment
        binding_ok = bool(
            _ASSIGNMENT_ID.fullmatch(assignment)
            and _normalized_role(row.get("role")) == role
            and str(row.get("front") or "").upper()
                == str(lane.get("front") or "").upper()
            and str(row.get("effect") or "") == str(lane.get("effect") or "")
            and [str(item) for item in row.get("assets", [])]
                == [str(item) for item in lane.get("assets", [])]
        )
        if not binding_ok:
            reason = f"{assignment or lane_id}:assignment-binding-invalid"
            merge_debt.append(reason)
            assigned_debt.append(reason)
            state["runtime_state"] = "invalid-binding"
            continue
        expected_subagent_type = (
            "xunji-reviewer" if role == "review" else "xunji-hunter")
        runtime_state, runtime_record, runtime_error = _auth_runtime_state(
            assignment, lane_id, digest, attempts, failures,
            expected_subagent_type=expected_subagent_type)
        state["runtime_state"] = runtime_state
        if runtime_error:
            reason = f"{assignment}:{runtime_error}"
            merge_debt.append(reason)
            assigned_debt.append(reason)
            continue
        if runtime_state in {"no-attempt", "running"}:
            reason = f"{assignment}:{runtime_state}"
            merge_debt.append(reason)
            assigned_debt.append(reason)
            continue
        draft = _load_merge_draft(run, assignment)
        draft_ok, draft_error = _draft_result_valid(
            run, draft, assignment=assignment, plan_digest=digest, lane_id=lane_id,
            runtime_state=runtime_state, runtime_record=runtime_record)
        draft_binding_ok = bool(
            draft_ok
            and _normalized_role(draft.get("role")) == role
            and str(draft.get("front") or "").upper()
                == str(lane.get("front") or "").upper()
            and [str(item) for item in draft.get("assets", [])]
                == [str(item) for item in lane.get("assets", [])]
            and str(draft.get("effect") or "") == str(lane.get("effect") or "")
            and str(draft.get("plan_id") or "") == str(current.get("plan_id") or "")
            and isinstance(draft.get("assignment_attempt"), int)
            and not isinstance(draft.get("assignment_attempt"), bool)
            and draft.get("assignment_attempt") == row.get("assignment_attempt")
            and (
                draft.get("review_status") == "not_applicable"
                if role == "review"
                else draft.get("review_status")
                in {"required", "complete", "action_required"}
            )
        )
        if not draft_binding_ok:
            reason = f"{assignment}:{draft_error or 'merge-draft-lane-binding-invalid'}"
            review_debt.append(reason)
            assigned_debt.append(reason)
        else:
            state["draft"] = draft
            state["result_digest"] = str(draft.get("result_digest") or "")
        if role == "review":
            # Reviewer completion is verified after its exact execution target,
            # but its own immutable return must already be authentic.
            state["runtime_record"] = runtime_record
            continue

    reviewers_by_target: dict[str, list[str]] = {}
    for lane in lanes:
        if _normalized_role(lane.get("role")) != "review":
            continue
        dependencies = [str(item) for item in lane.get("dependencies", [])]
        if len(dependencies) == 1:
            reviewers_by_target.setdefault(dependencies[0], []).append(str(lane.get("id") or ""))

    dispositions = {
        "merged": [], "reviewed": [], "blocked": [], "failed": [], "abandoned": [],
    }
    for lane in lanes:
        lane_id = str(lane.get("id") or "")
        role = _normalized_role(lane.get("role"))
        if role == "review":
            continue
        state = states[lane_id]
        assignment = str(state.get("assignment") or "")
        reviewer_ids = reviewers_by_target.get(lane_id, [])
        if len(reviewer_ids) != 1:
            reason = f"{lane_id}:exact-reviewer-missing"
            review_debt.append(reason)
            if assignment:
                assigned_debt.append(reason)
            continue
        reviewer_state = states.get(reviewer_ids[0], {})
        reviewer_assignment = str(reviewer_state.get("assignment") or "")
        draft = state.get("draft") if isinstance(state.get("draft"), dict) else {}
        receipt = draft.get("review_receipt") if isinstance(draft, dict) else None
        reviewer_record = reviewer_state.get("runtime_record") \
            if isinstance(reviewer_state.get("runtime_record"), dict) else {}
        reviewer_row = next((item for item in plan_rows
                             if item.get("lane_id") == reviewer_ids[0]), {})
        receipt_ok = bool(
            _receipt_hash_valid(receipt)
            and draft.get("review_status") == "complete"
            and receipt.get("target_assignment") == assignment
            and receipt.get("target_result_digest") == state.get("result_digest")
            and receipt.get("reviewer_assignment") == reviewer_assignment
            and receipt.get("reviewer_agent_id") == reviewer_record.get("agent_id")
            and receipt.get("reviewer_tool_use_id") == reviewer_record.get("tool_use_id")
            and receipt.get("reviewer_result_digest")
                == reviewer_state.get("result_digest")
            and receipt.get("plan_digest") == digest
            and receipt.get("target_lane_id") == lane_id
            and receipt.get("reviewer_lane_id") == reviewer_ids[0]
            and reviewer_state.get("runtime_state") == "returned"
            and str(reviewer_row.get("status") or "").strip().lower() == "reviewed"
            and reviewer_row.get("reviews_assignments") == [assignment]
            and reviewer_row.get("review_result_digest") == state.get("result_digest")
        )
        if not receipt_ok:
            reason = f"{assignment or lane_id}:current-review-invalid"
            review_debt.append(reason)
            if assignment:
                assigned_debt.append(reason)
            continue
        state["review_receipt_hash"] = str(receipt.get("receipt_hash") or "")
        reviewer_state["review_receipt_hash"] = state["review_receipt_hash"]
        reviewer_state["disposition"] = "reviewed"
        reviewer_state["complete"] = True
        dispositions["reviewed"].append(reviewer_assignment)

        row = next((item for item in plan_rows if item.get("lane_id") == lane_id), {})
        root_status = str(row.get("status") or "").strip().lower()
        runtime_state = str(state.get("runtime_state") or "")
        allowed = _TERMINAL_ROOT_DISPOSITIONS - ({"merged"} if runtime_state == "failed" else set())
        note_issues: list[str] = []
        if runtime_module is not None and root_status in allowed:
            try:
                note_issues = runtime_module.disposition_note_issues(
                    run, root_status, str(row.get("last_note") or ""))
            except Exception:
                note_issues = ["disposition-note-check-failed"]
        root_receipt_binding = str(
            row.get("root_disposition_review_receipt_hash") or "")
        root_disposition_at = _iso_epoch(row.get("root_disposition_at"))
        review_recorded_at = _iso_epoch(receipt.get("recorded_at"))
        if root_status not in allowed or note_issues \
                or root_receipt_binding != state["review_receipt_hash"] \
                or not root_disposition_at or root_disposition_at < review_recorded_at \
                or (root_status == "merged" and row.get("coverage_merge_satisfied") is not True):
            detail = root_status or "missing"
            if note_issues:
                detail += ":" + ",".join(note_issues)
            if root_receipt_binding != state["review_receipt_hash"]:
                detail += ":review-receipt-unbound"
            if not root_disposition_at or root_disposition_at < review_recorded_at:
                detail += ":root-before-review"
            reason = f"{assignment}:root-disposition={detail}"
            merge_debt.append(reason)
            assigned_debt.append(reason)
            continue
        state["disposition"] = root_status
        state["complete"] = True
        dispositions[root_status].append(assignment)

    lane_states = []
    assignment_dispositions = []
    for lane_id in lane_ids:
        state = dict(states[lane_id])
        state.pop("draft", None)
        state.pop("runtime_record", None)
        lane_states.append(state)
        if state.get("complete"):
            assignment_dispositions.append({
                key: state[key] for key in (
                    "lane_id", "assignment", "role", "runtime_state", "disposition",
                    "result_digest", "review_receipt_hash",
                )
            })
    pending = sorted({
        str(state.get("assignment") or state.get("lane_id") or "")
        for state in states.values() if not state.get("complete")
    } - {""})
    summary = {
        "schema": "xunji.merge-disposition-summary.v1",
        **{key: sorted(set(value)) for key, value in dispositions.items()},
        "pending": pending,
    }
    return {
        "schema": "xunji.plan-cycle-projection.v1",
        "plan_id": str(current.get("plan_id") or ""),
        "plan_digest": digest,
        "lane_ids": lane_ids,
        "lane_states": lane_states,
        "assignment_dispositions": assignment_dispositions,
        "merge_disposition_summary": summary,
        "debt": {
            "merge": sorted(set(merge_debt)),
            "review": sorted(set(review_debt)),
        },
        "assigned_debt": sorted(set(assigned_debt)),
        "has_assignments": bool(plan_rows) or bool(row_errors),
    }


def plan_bound_agent_debt(run_dir: str | Path, *, ignore_plan_digest: str = "") -> dict:
    """Derive current plan debt from its lane universe and trusted receipts."""
    projection = plan_cycle_projection(run_dir)
    if ignore_plan_digest and projection.get("plan_digest") == ignore_plan_digest:
        return {"merge": [], "review": []}
    debt = projection.get("debt") if isinstance(projection.get("debt"), dict) else {}
    return {
        "merge": [str(item) for item in debt.get("merge", [])],
        "review": [str(item) for item in debt.get("review", [])],
    }


def agent_debt_digest(debt: dict) -> str:
    """Stable digest used by stage-exit receipts and their mechanical checker."""
    return _sha256_json({
        "merge": sorted(str(item) for item in debt.get("merge", [])),
        "review": sorted(str(item) for item in debt.get("review", [])),
    })


def stage_declaration_issues(stage: str, projection: dict) -> list[str]:
    """Purely check one Root declaration against an already-derived projection."""
    stage = str(stage or "").strip().upper()
    if stage not in MACRO_STAGES:
        return ["MACRO_STAGE_INVALID"]
    readiness = projection.get("readiness") if isinstance(projection, dict) else None
    row = readiness.get(stage) if isinstance(readiness, dict) else None
    blockers = row.get("blockers") if isinstance(row, dict) else None
    if not isinstance(blockers, list):
        return ["MACRO_STAGE_PROJECTION_INVALID"]
    return [str(item) for item in blockers]


def stage_readiness(run_dir: str | Path, *, ignore_plan_digest: str = "") -> dict:
    """Derive S1/S2/S3 readiness without creating another canonical phase.

    Root remains the stage selector.  ``candidate`` is only the highest currently
    ready goal view; callers must validate Root's explicit work-plan declaration.
    """
    run = Path(run_dir).resolve()
    target = run / "target.md"
    scope_ready = _meaningful_markdown(target)
    coverage_ready, coverage_detail, coverage_digest = _coverage_state(run)
    frontier = summary(run)
    fronts = frontier.get("fronts", [])
    front_schema_ready = bool(fronts) and not frontier.get("schema_errors")
    open_fronts = sorted(str(item) for item in frontier.get("open", []))
    deferred_fronts = sorted(str(item) for item in frontier.get("deferred", []))
    type_a_fronts = sorted({
        str(item.get("id") or "") for item in fronts
        if isinstance(item, dict) and str(item.get("status") or "") == "blocked_type_a"
    } - {""})
    debt = plan_bound_agent_debt(run, ignore_plan_digest=ignore_plan_digest)

    base_blockers: list[str] = []
    if not scope_ready:
        base_blockers.append("SCOPE_NOT_READY")
    s2_blockers = list(base_blockers)
    if not coverage_ready:
        s2_blockers.append("COVERAGE_NOT_READY")
    if not front_schema_ready:
        s2_blockers.append("FRONT_SCHEMA_NOT_READY")
    s3_blockers = list(s2_blockers)
    if open_fronts:
        s3_blockers.append("OPEN_FRONTS_PRESENT")
    if type_a_fronts:
        s3_blockers.append("TYPE_A_FRONTS_PRESENT")
    if deferred_fronts:
        # Canonical Type B uses blocked_type_b/closed.  A deferred status remains
        # Type A and cannot be laundered into closure readiness by prose alone.
        s3_blockers.append("DEFERRED_TYPE_A_FRONTS_PRESENT")
    if debt["merge"]:
        s3_blockers.append("PLAN_BOUND_AGENT_MERGE_DEBT")
    if debt["review"]:
        s3_blockers.append("PLAN_BOUND_AGENT_REVIEW_DEBT")
    readiness = {
        "S1": {"ready": not base_blockers, "blockers": base_blockers},
        "S2": {"ready": not s2_blockers, "blockers": s2_blockers},
        "S3": {"ready": not s3_blockers, "blockers": s3_blockers},
    }
    candidate = next(
        (stage for stage in reversed(MACRO_STAGES) if readiness[stage]["ready"]),
        "SETUP",
    )
    facts = {
        "scope_ready": scope_ready,
        "target_digest": hashlib.sha256(target.read_bytes()).hexdigest()
        if target.is_file() else "",
        "coverage_ready": coverage_ready,
        "coverage_detail": coverage_detail,
        "coverage_digest": coverage_digest,
        "front_schema_ready": front_schema_ready,
        "front_digest": _sha256_json(fronts),
        "open_fronts": open_fronts,
        "deferred_fronts": deferred_fronts,
        "type_a_fronts": type_a_fronts,
        "agent_debt": debt,
        "agent_debt_digest": agent_debt_digest(debt),
    }
    return {
        "schema": "xunji.macro-stage-readiness.v1",
        "canonical": "Markdown/coverage/typed Agent receipts remain source of truth",
        "candidate": candidate,
        "readiness": readiness,
        "facts": facts,
        "canonical_digest": _sha256_json(facts),
    }


def _selftest() -> int:
    root = Path(tempfile.mkdtemp())
    run = root / "run"
    run.mkdir()
    (run / "frontier.md").write_text(
        "# Frontier\n\n## Open Fronts\n\n"
        "### F-001 — compound\n- Status: open | Barrier: app-layer | Depth: moderate\n\n"
        "### F-002 — canonical\n- Status: probing\n- Barrier class: auth-layer\n"
        "- Current depth: shallow\n\n"
        "### F-003\n- Status: open\n- Barrier class: network-layer\n- Current depth: shallow\n\n"
        "### F-004\n- Status: open\n- Barrier class: none\n- Current depth: shallow\n\n"
        "### F-004\n- Status: open\n- Barrier class: none\n- Current depth: shallow\n\n"
        "## Deferred Fronts\n### F-005\n- Status: deferred\n- Barrier class: auth-layer\n"
        "- Current depth: shallow\n"
        "### F-006\n- Barrier class: auth-layer\n- Current depth: shallow\n"
        "## Closed Fronts\n### F-007\n- Status: open\n"
        "- Barrier class: routing-layer\n- Current depth: shallow\n",
        encoding="utf-8",
    )
    data = summary(run)
    by_id = {front.id: front for front in parse_fronts(run)}
    checks = [
        ("compound status still counts as open", by_id["F-001"].is_open),
        ("inline barrier is recovered", by_id["F-001"].barrier == "app-layer"),
        ("compound format is flagged", bool(by_id["F-001"].schema_errors)),
        ("probing is active", "F-002" in data["open"]),
        ("deferred is not active", "F-005" not in data["open"]),
        ("four diverse fronts require fanout", data["fanout_required"] is True),
        ("duplicate front id is flagged", any("duplicate front id" in item for item in data["schema_errors"])),
        ("section fallback does not hide missing Status",
         any("F-006: missing canonical `Status:`" in item for item in data["schema_errors"])),
        ("open status inside Closed section is flagged and remains active",
         "F-007" in data["open"]
         and any("F-007: Status `open` conflicts" in item for item in data["schema_errors"])),
    ]
    stage_run = root / "stage-run"
    (stage_run / "state").mkdir(parents=True)
    (stage_run / "target.md").write_text(
        "# Target\n- Authorized scope: app.example\n", encoding="utf-8")
    (stage_run / "coverage.json").write_text(json.dumps({
        "assets": [{"host": "app.example", "examined": False}],
    }), encoding="utf-8")
    (stage_run / "frontier.md").write_text(
        "# Frontier\n\n## Open Fronts\n\n### F-010 — active\n"
        "- Status: blocked_type_a\n- Barrier class: app-layer\n"
        "- Current depth: shallow\n",
        encoding="utf-8",
    )
    open_stage = stage_readiness(stage_run)
    (stage_run / "frontier.md").write_text(
        "# Frontier\n\n## Closed Fronts\n\n### F-010 — settled\n"
        "- Status: blocked_type_b\n- Barrier class: app-layer\n"
        "- Current depth: moderate\n",
        encoding="utf-8",
    )
    closed_stage = stage_readiness(stage_run)
    (stage_run / "state" / "assignments.json").write_text(json.dumps({
        "schema": 3,
        "assignments": [{
            "agent": "A-hunter-001", "role": "hunter", "status": "done",
            "plan_digest": "a" * 64, "lane_id": "L-HUNTER",
            "attempts": [{"state": "returned", "agent_id": "child-1",
                          "tool_use_id": "tool-1"}],
        }],
    }), encoding="utf-8")
    agent_debt_stage = stage_readiness(stage_run)
    _, invalid_assignment_contract_errors = _load_assignment_rows(stage_run)
    duplicate_runtime_state = _auth_runtime_state(
        "A-hunter-001", "L-HUNTER", "a" * 64,
        [
            {"assignment": "A-hunter-001", "lane_id": "L-HUNTER",
             "plan_digest": "a" * 64, "launched_at": 1.0,
             "state": "running", "tool_use_id": "tool-one"},
            {"assignment": "A-hunter-001", "lane_id": "L-HUNTER",
             "plan_digest": "a" * 64, "launched_at": 2.0,
             "state": "returned", "tool_use_id": "tool-two"},
        ],
        [],
    )
    stale_runtime_state = _auth_runtime_state(
        "A-hunter-001", "L-HUNTER", "a" * 64,
        [
            {"assignment": "A-hunter-001", "lane_id": "L-OLD",
             "plan_digest": "b" * 64, "launched_at": 9.0,
             "state": "returned", "tool_use_id": "stale-tool"},
            {"assignment": "A-hunter-001", "lane_id": "L-HUNTER",
             "plan_digest": "a" * 64, "launched_at": 2.0,
             "state": "running", "tool_use_id": "current-tool"},
        ],
        [],
    )
    wrong_type_runtime_state = _auth_runtime_state(
        "A-hunter-001", "L-HUNTER", "a" * 64,
        [{
            "assignment": "A-hunter-001", "lane_id": "L-HUNTER",
            "plan_digest": "a" * 64, "launched_at": 2.0,
            "state": "returned", "tool_use_id": "wrong-type-tool",
            "subagent_type": "xunji-reviewer",
        }],
        [],
        expected_subagent_type="xunji-hunter",
    )
    valid_receipt = {
        "schema": "xunji.review-disposition.v1",
        "target_assignment": "A-hunter-001",
        "target_result_digest": "1" * 64,
        "reviewer_assignment": "A-review-001",
        "reviewer_agent_id": "child-review",
        "reviewer_tool_use_id": "tool-review",
        "reviewer_result_digest": "2" * 64,
        "plan_digest": "3" * 64,
        "target_lane_id": "L-HUNTER",
        "reviewer_lane_id": "L-REVIEW",
        "disposition": "accept-candidate",
        "note": "exact immutable result reviewed",
        "recorded_at": "2026-07-17T00:00:00Z",
    }
    valid_receipt["receipt_hash"] = _sha256_json(valid_receipt)
    invalid_enum_receipt = dict(valid_receipt, disposition="approve")
    invalid_enum_receipt["receipt_hash"] = _sha256_json({
        key: value for key, value in invalid_enum_receipt.items()
        if key != "receipt_hash"
    })
    extra_field_receipt = dict(valid_receipt, reviewer_prose="trusted")
    bad_time_receipt = dict(valid_receipt, recorded_at="eventually")
    bad_time_receipt["receipt_hash"] = _sha256_json({
        key: value for key, value in bad_time_receipt.items()
        if key != "receipt_hash"
    })
    committed_at = 1.0
    valid_plan = {
        "schema": "xunji.work-plan.v1",
        "plan_id": "",
        "cycle_id": 1,
        "macro_stage": "S1",
        "objective": "inspect the bounded local artifact",
        "inputs_digest": "4" * 64,
        "replan_reason": "",
        "lanes": [{
            "id": "L-LOCAL",
            "role": "web-hunter",
            "effect": "local_read",
            "capability_id": "read.timestamp-gate",
            "assets": [],
            "dependencies": [],
            "expected_evidence": "bounded artifact summary",
            "expected_information_gain": "medium",
            "stop_condition": "artifact has been inspected",
            "request_cost": 0,
            "request_budget": 0,
            "merge_cost": 1,
            "atomic": True,
        }],
        "execution_mode": "ROOT_DIRECT",
        "merge_owner": "Root/Single Synthesizer",
        "exit_gate": "bounded artifact inspection is recorded",
        "turn_binding": {
            "session_id": "session-plan",
            "prompt_sha256": "5" * 64,
            "contract_updated_at": committed_at,
        },
        "delegation_decision": {
            "schema": "xunji.delegation-decision.v1",
            "mode": "ROOT_DIRECT",
            "reason": "one bounded local read",
            "lane_ids": ["L-LOCAL"],
            "committed_at": committed_at,
        },
        "committed_at": committed_at,
        "plan_digest": "",
    }
    valid_plan["plan_digest"] = _sha256_json({
        key: value for key, value in valid_plan.items()
        if key not in {"plan_id", "plan_digest"}
    })
    valid_plan["plan_id"] = f"WP-1-{valid_plan['plan_digest'][:8]}"
    invalid_extra_plan = dict(valid_plan, reviewer_prose="trusted")
    invalid_extra_plan["plan_digest"] = _sha256_json({
        key: value for key, value in invalid_extra_plan.items()
        if key not in {"plan_id", "plan_digest"}
    })
    invalid_extra_plan["plan_id"] = f"WP-1-{invalid_extra_plan['plan_digest'][:8]}"
    invalid_lane_plan = json.loads(json.dumps(valid_plan))
    invalid_lane_plan["lanes"][0]["role"] = {"forged": "hunter"}
    invalid_lane_plan["plan_digest"] = _sha256_json({
        key: value for key, value in invalid_lane_plan.items()
        if key not in {"plan_id", "plan_digest"}
    })
    invalid_lane_plan["plan_id"] = f"WP-1-{invalid_lane_plan['plan_digest'][:8]}"
    loaded_valid_plan, valid_plan_errors = _load_plan_projection(stage_run, valid_plan)
    _, invalid_extra_errors = _load_plan_projection(stage_run, invalid_extra_plan)
    _, invalid_lane_errors = _load_plan_projection(stage_run, invalid_lane_plan)
    checks += [
        ("S2 readiness is derived from scope/coverage/front schema",
         open_stage["readiness"]["S2"]["ready"] is True),
        ("open Type-A front blocks S3",
         {"OPEN_FRONTS_PRESENT", "TYPE_A_FRONTS_PRESENT"}.issubset(
             set(open_stage["readiness"]["S3"]["blockers"]))),
        ("settled fronts make S3 a derived candidate",
         closed_stage["candidate"] == "S3"),
        ("unmerged and unreviewed plan-bound return blocks S3",
         {"PLAN_BOUND_AGENT_MERGE_DEBT", "PLAN_BOUND_AGENT_REVIEW_DEBT"}.issubset(
             set(agent_debt_stage["readiness"]["S3"]["blockers"]))),
        ("assignment loader rejects bound rows that do not conform to v1",
         any(item.startswith("assignments:contract-invalid:")
             for item in invalid_assignment_contract_errors)),
        ("runtime projection fails closed on duplicates instead of taking max",
         duplicate_runtime_state
         == ("invalid-attempts", {}, "multiple-runtime-attempts")),
        ("stale attempts from another plan/lane do not shadow the current binding",
         stale_runtime_state[0] == "running"
         and stale_runtime_state[1].get("tool_use_id") == "current-tool"
         and stale_runtime_state[2] == ""),
        ("runtime projection rejects an Agent type that contradicts the lane role",
         wrong_type_runtime_state
         == ("invalid-attempts", {}, "runtime-agent-type-mismatch")),
        ("stage declaration checker is pure over projection",
         stage_declaration_issues("S3", open_stage)
         == open_stage["readiness"]["S3"]["blockers"]),
        ("review receipt accepts only its exact typed self-hashed schema",
         _receipt_hash_valid(valid_receipt)),
        ("review receipt rejects unknown disposition even with a fresh self-hash",
         not _receipt_hash_valid(invalid_enum_receipt)),
        ("review receipt rejects extra fields and stale self-hashes",
         not _receipt_hash_valid(extra_field_receipt)
         and not _receipt_hash_valid(dict(valid_receipt, note="tampered"))),
        ("review receipt rejects non-ISO ordering timestamps",
         not _receipt_hash_valid(bad_time_receipt)),
        ("plan projection reuses the strict work-plan contract owner",
         loaded_valid_plan == valid_plan and not valid_plan_errors),
        ("self-hashed work plan with unknown fields is rejected",
         bool(invalid_extra_errors)
         and invalid_extra_errors[0].startswith("work-plan:contract-invalid:")),
        ("self-hashed work plan with a malformed lane is rejected",
         bool(invalid_lane_errors)
         and invalid_lane_errors[0].startswith("work-plan:contract-invalid:")),
    ]
    bad = [name for name, ok in checks if not ok]
    for name, ok in checks:
        print(("ok   " if ok else "FAIL ") + name)
    print("run_model selftest " + ("passed" if not bad else f"FAILED ({len(bad)})"))
    return 0 if not bad else 1


def main() -> int:
    parser = argparse.ArgumentParser(description="parse canonical Xunji run state")
    parser.add_argument("run_dir", nargs="?")
    parser.add_argument("--selftest", action="store_true")
    args = parser.parse_args()
    if args.selftest:
        return _selftest()
    if not args.run_dir:
        parser.error("run_dir is required")
    data = summary(args.run_dir)
    print(f"open={data['open_count']} fanout_required={data['fanout_required']}")
    for error in data["schema_errors"]:
        print(f"WARN {error}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
