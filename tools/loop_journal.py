#!/usr/bin/env python3
"""Append-only loop-cycle journal for interrupted Claude Code loops.

The journal is a derived audit trail at `state/loop_journal.jsonl`. Canonical run
truth remains Markdown (`frontier.md`, `decisions.md`, `evidence.md`, `review.md`).
The journal only helps a resumed session tell whether the last loop iteration
started, planned, acted, wrote results, ended, or was interrupted. It can also
record visible phase-start / phase-end markers for the human operator.
"""
from __future__ import annotations

import argparse
import contextlib
import hashlib
import json
import os
import re
import sys
import tempfile
import time
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

try:
    import fcntl
except ImportError:  # pragma: no cover
    fcntl = None

try:
    sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
except Exception:
    pass

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

import status_style  # noqa: E402
import contract_schema  # noqa: E402

SCHEMA = "xunji.loop_journal.v1"
JOURNAL = "loop_journal.jsonl"
PHASE_EVENTS = {"phase_start", "phase_end"}
TYPED_CYCLE_EVENTS = frozenset({
    "stage_plan", "replan", "stage_exit", "delegation_committed", "cycle_end",
})
_HEX64 = re.compile(r"[0-9a-f]{64}")
_PLAN_ID = re.compile(r"WP-([0-9]+)-([0-9a-f]{8})")
_LANE_ID = re.compile(r"L-[A-Za-z0-9._-]+")
_ASSIGNMENT_ID = re.compile(r"A-[A-Za-z0-9._-]+")
_CAPABILITY_ID = re.compile(r"[a-z][a-z0-9]*(?:[.-][a-z0-9][a-z0-9-]*)*")
_RECORDED_AT = re.compile(
    r"[0-9]{4}-(0[1-9]|1[0-2])-([0-2][0-9]|3[01])T"
    r"([01][0-9]|2[0-3]):[0-5][0-9]:[0-5][0-9](\.[0-9]{3})?Z")
_INVISIBLE_ACTION = re.compile(r"[\u200b\u200c\u200d\u2060\ufeff\u00a0]")
_ACTION_WORDS_ZH = (
    r"运行|执行|检查|验证|更新|记录|分派|读取|修复|重跑|测试|扫描|探测|复审|回放|"
    r"保存|写入|提交|创建|生成|删除|关闭|打开|调用|发送|汇总|同步|标记|裁定|重试|"
    r"继续|尝试|对照|分析|调查|确认|解析|抓取|请求|枚举|注入|绕过|检索|搜索|刷新|"
    r"迁移|清理|构建|审计"
)
_ACTION_WORDS_EN = (
    r"run|execute|check|verify|update|record|assign|read|fix|test|scan|review|replay|"
    r"save|write|commit|create|generate|delete|close|open|call|send|summarize|sync|mark|"
    r"adjudicate|retry|continue|try|compare|analyze|investigate|confirm|parse|fetch|request|"
    r"enumerate|inject|bypass|search|refresh|migrate|clean|build|audit"
)
_ACTION_RE = re.compile(rf"(?:{_ACTION_WORDS_ZH})|\b(?:{_ACTION_WORDS_EN})\b", re.I)
_TOOL_RE = re.compile(
    r"\b(?:check_run|peer_review|workers|coverage_matrix|probe|render|loop_state)"
    r"(?:\.py)?\b",
    re.I,
)
_CONTROL_ANCHOR_RE = re.compile(
    r"(?:check_run|classify_hosts|workers\.py|coverage_matrix\.py|frontier\.md|"
    r"evidence\.md|report\.md|decisions\.md|retrospective\.md|hints\.md|"
    r"surface\.md|conflicts?|冲突|子任务|subagent|Agent Board|分派|复审|"
    r"peer_review|收口|覆盖台账)",
    re.I,
)
_ROOT_ACTION_RECEIPT_KEYS = {
    "schema", "parent_run", "plan_id", "plan_digest", "cycle_id", "lane_id",
    "capability_id", "capability_effect", "session_id", "prompt_sha256",
    "tool_use_id", "action_sha256", "claim_event_seq", "claim_event_hash",
    "runtime_event_seq", "runtime_event_hash", "outcome", "response_sha256",
    "recorded_at", "receipt_hash",
}
_JOURNAL_ENVELOPE_KEYS = {
    "schema", "ts", "run_dir", "cycle", "event", "note", "data",
    "previous_event_hash", "canonical", "event_hash",
}
_JOURNAL_CANONICAL = "Markdown run files remain source of truth; this journal is derived."
_LOAD_ERROR_KEY = "_journal_load_error"
EVENT_CN = {
    "cycle_start": "循环开始",
    "plan": "计划确定",
    "action": "动作执行",
    "write_result": "结果写入",
    "cycle_end": "循环结束",
    "interrupt": "中断记录",
    "resume": "恢复准备",
    "phase_start": "阶段开始",
    "phase_end": "阶段结束",
    "stage_plan": "阶段计划",
    "replan": "计划刷新",
    "stage_exit": "阶段退出",
    "delegation_committed": "委派已提交",
}


class JournalContractError(ValueError):
    """Stable fail-closed error for typed cycle-event shape or ordering."""

    def __init__(self, code: str, detail: str = ""):
        self.code = code
        self.detail = detail
        super().__init__(f"{code}: {detail}" if detail else code)


class JournalDurabilityError(OSError):
    """The journal append could not be proven durable and was not admitted."""


def _contract_error(code: str, detail: str) -> None:
    raise JournalContractError(code, detail)


def _exact_keys(value: object, required: set[str], optional: set[str] | None = None,
                *, event: str) -> dict:
    if not isinstance(value, dict):
        _contract_error("CYCLE_EVENT_DATA_INVALID", f"{event} data must be an object")
    optional = optional or set()
    keys = set(value)
    missing = sorted(required - keys)
    extra = sorted(keys - required - optional)
    if missing or extra:
        _contract_error(
            "CYCLE_EVENT_DATA_INVALID",
            f"{event} keys missing={missing or 'none'} extra={extra or 'none'}",
        )
    return value


def _bounded_text(value: object, *, field: str, maximum: int = 2048,
                  allow_empty: bool = False) -> str:
    if not isinstance(value, str) or (not allow_empty and not value.strip()) \
            or len(value) > maximum:
        _contract_error("CYCLE_EVENT_DATA_INVALID", f"{field} is invalid")
    return value


def _next_action_text(value: object) -> str:
    action = _bounded_text(value, field="next_action")
    if len(action) < 4 or action != action.strip() \
            or _INVISIBLE_ACTION.search(action):
        _contract_error(
            "CYCLE_EVENT_DATA_INVALID",
            "next_action must be canonical text without outer/invisible whitespace",
        )
    return action


def _multiple_action_clauses(detail: str) -> bool:
    parts = re.split(
        r"(?:&&|\s+\+\s+|[，,；;、]|\s+/\s+|以及|并且|然后|随后|再去|接着|同时|"
        rf"和|与|及|或|并(?=(?:{_ACTION_WORDS_ZH})|\b(?:{_ACTION_WORDS_EN})\b)|"
        r"\b(?:and\s+then|and|or)\b)",
        detail,
        flags=re.I,
    )
    actionable = [part for part in parts if _ACTION_RE.search(part) or _TOOL_RE.search(part)]
    return len(actionable) > 1


def validate_next_action_semantics(
    value: object,
    *,
    active_fronts: list[str] | tuple[str, ...] | set[str] | None = None,
) -> str:
    """Return a stable Coda error code, or ``""`` for one concrete action.

    This pure validator is shared conceptually with the Stop gate.  The cycle
    producer runs it before freezing model-supplied ``next_action`` so a typed
    receipt cannot promote vague, multi-action, or wrong-front prose into trusted
    control state.
    """
    try:
        detail = _next_action_text(value)
    except JournalContractError:
        return "CODA_INVALID_DETAIL"
    compact = re.sub(r"[\s`*_#<>。，、:：;；,.!?！？()（）\[\]-]", "", detail)
    if len(compact) < 4 or re.search(r"<[^>]*>|\b(?:TODO|TBD)\b", detail, re.I):
        return "CODA_INVALID_DETAIL"
    vague = re.sub(r"[\s。！!,，;；]", "", detail).lower()
    if vague in {
        "继续", "继续分析", "继续测试", "继续验证", "继续推进", "按流程继续",
        "处理问题", "执行下一步", "等待", "等待用户", "later", "continue",
    }:
        return "CODA_VAGUE_ACTION"
    vague_phrase = re.search(
        r"(?:根据|按照)(?:前面|上述|以上|之前|当前).*(?:继续|下一步)|"
        r"继续(?:做|执行)?(?:下一步|后续工作|相关工作|剩余工作)|"
        r"按(?:既定|上述|当前)?流程继续|进一步(?:分析|处理|推进)(?:问题|工作|流程)?$",
        detail,
        re.I,
    )
    concrete_anchor = re.search(
        r"\bF-\d+\b|\b(?:python\d*|render|probe|check_run|peer_review|workers)\b|"
        r"[A-Za-z0-9_.-]+\.(?:py|md|json|html)\b",
        detail,
        re.I,
    )
    if vague_phrase and not concrete_anchor:
        return "CODA_VAGUE_ACTION"
    cited = set(re.findall(r"\bF-\d+\b", detail, re.I))
    if len(cited) > 1:
        return "CODA_MULTIPLE_FRONTS"
    if not (_ACTION_RE.search(detail) or _TOOL_RE.search(detail)):
        return "CODA_ACTION_REQUIRED"
    if _multiple_action_clauses(detail):
        return "CODA_MULTIPLE_ACTIONS"
    if active_fronts is not None:
        active = {str(item).upper() for item in active_fronts if str(item).strip()}
        cited = {item.upper() for item in cited}
        if cited and not (cited & active):
            return "CODA_WRONG_FRONT"
        if active and not cited and not _CONTROL_ANCHOR_RE.search(detail):
            return "CODA_FRONT_REQUIRED"
        if not active and cited:
            return "CODA_WRONG_FRONT"
        if not active and not cited and not _CONTROL_ANCHOR_RE.search(detail):
            return "CODA_CONTROL_OBJECT_REQUIRED"
    return ""


def _hex_digest(value: object, *, field: str, allow_empty: bool = False) -> str:
    if allow_empty and value == "":
        return ""
    if not isinstance(value, str) or not _HEX64.fullmatch(value):
        _contract_error("CYCLE_EVENT_DATA_INVALID", f"{field} must be lowercase sha256")
    return value


def _sha256_json(value: object) -> str:
    return hashlib.sha256(json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
    ).encode("utf-8")).hexdigest()


def _positive_int(value: object, *, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        _contract_error("CYCLE_EVENT_DATA_INVALID", f"{field} must be a positive integer")
    return value


def _recorded_at(value: object) -> str:
    recorded = _bounded_text(value, field="root_action_receipt.recorded_at", maximum=24)
    if not _RECORDED_AT.fullmatch(recorded):
        _contract_error(
            "CYCLE_EVENT_DATA_INVALID", "root_action_receipt.recorded_at is invalid")
    try:
        parsed = datetime.fromisoformat(recorded.replace("Z", "+00:00"))
    except (TypeError, ValueError):
        _contract_error(
            "CYCLE_EVENT_DATA_INVALID", "root_action_receipt.recorded_at is invalid")
    if parsed.tzinfo is None:
        _contract_error(
            "CYCLE_EVENT_DATA_INVALID", "root_action_receipt.recorded_at needs a timezone")
    return recorded


def _plan_id(value: object, *, digest: str, cycle: int | None = None) -> str:
    if not isinstance(value, str):
        _contract_error("CYCLE_EVENT_DATA_INVALID", "plan_id is invalid")
    match = _PLAN_ID.fullmatch(value)
    if not match or match.group(2) != digest[:8] \
            or (cycle is not None and int(match.group(1)) != cycle):
        _contract_error("CYCLE_EVENT_DATA_INVALID", "plan_id does not bind cycle/digest")
    return value


def _root_action_receipt(value: object, *, plan_id: str, plan_digest: str,
                         lane_id: str, cycle: int | None) -> dict:
    receipt = _exact_keys(
        value, _ROOT_ACTION_RECEIPT_KEYS, event="cycle_end.root_action_receipt")
    if receipt["schema"] != "xunji.root-action-receipt.v1":
        _contract_error("CYCLE_EVENT_DATA_INVALID", "root action receipt schema is invalid")
    _bounded_text(receipt["parent_run"], field="root_action_receipt.parent_run", maximum=255)
    receipt_digest = _hex_digest(
        receipt["plan_digest"], field="root_action_receipt.plan_digest")
    receipt_plan_id = _plan_id(
        receipt["plan_id"], digest=receipt_digest, cycle=cycle)
    receipt_cycle = _positive_int(
        receipt["cycle_id"], field="root_action_receipt.cycle_id")
    receipt_lane = receipt["lane_id"]
    if not isinstance(receipt_lane, str) or len(receipt_lane) > 256 \
            or not _LANE_ID.fullmatch(receipt_lane):
        _contract_error("CYCLE_EVENT_DATA_INVALID", "root_action_receipt.lane_id is invalid")
    capability_id = receipt["capability_id"]
    if not isinstance(capability_id, str) or len(capability_id) > 256 \
            or not _CAPABILITY_ID.fullmatch(capability_id):
        _contract_error(
            "CYCLE_EVENT_DATA_INVALID", "root_action_receipt.capability_id is invalid")
    if receipt["capability_effect"] not in {"local_read", "local_verify"}:
        _contract_error(
            "CYCLE_EVENT_DATA_INVALID", "root_action_receipt.capability_effect is invalid")
    _bounded_text(receipt["session_id"], field="root_action_receipt.session_id", maximum=1024)
    _hex_digest(receipt["prompt_sha256"], field="root_action_receipt.prompt_sha256")
    _bounded_text(receipt["tool_use_id"], field="root_action_receipt.tool_use_id", maximum=1024)
    _hex_digest(receipt["action_sha256"], field="root_action_receipt.action_sha256")
    claim_seq = _positive_int(
        receipt["claim_event_seq"], field="root_action_receipt.claim_event_seq")
    _hex_digest(receipt["claim_event_hash"], field="root_action_receipt.claim_event_hash")
    runtime_seq = _positive_int(
        receipt["runtime_event_seq"], field="root_action_receipt.runtime_event_seq")
    _hex_digest(receipt["runtime_event_hash"], field="root_action_receipt.runtime_event_hash")
    if runtime_seq <= claim_seq:
        _contract_error(
            "CYCLE_EVENT_DATA_INVALID", "root action runtime event must follow its claim")
    if receipt["outcome"] not in {"succeeded", "failed"}:
        _contract_error("CYCLE_EVENT_DATA_INVALID", "root action receipt outcome is invalid")
    _hex_digest(receipt["response_sha256"], field="root_action_receipt.response_sha256")
    _recorded_at(receipt["recorded_at"])
    receipt_hash = _hex_digest(
        receipt["receipt_hash"], field="root_action_receipt.receipt_hash")
    expected_hash = _sha256_json({
        key: item for key, item in receipt.items() if key != "receipt_hash"
    })
    if receipt_hash != expected_hash:
        _contract_error("CYCLE_EVENT_DATA_INVALID", "root action receipt hash mismatch")
    if receipt_plan_id != plan_id or receipt_digest != plan_digest \
            or receipt_lane != lane_id or (cycle is not None and receipt_cycle != cycle):
        _contract_error(
            "CYCLE_EVENT_DATA_INVALID", "root action receipt plan/lane/cycle binding mismatch")
    return receipt


def _string_ids(value: object, *, field: str, pattern: re.Pattern[str],
                minimum: int = 0, maximum: int = 256) -> list[str]:
    if not isinstance(value, list) or isinstance(value, (str, bytes)) \
            or not minimum <= len(value) <= maximum:
        _contract_error("CYCLE_EVENT_DATA_INVALID", f"{field} is not a bounded array")
    if any(not isinstance(item, str) or not pattern.fullmatch(item) for item in value):
        _contract_error("CYCLE_EVENT_DATA_INVALID", f"{field} contains an invalid id")
    if len(value) != len(set(value)):
        _contract_error("CYCLE_EVENT_DATA_INVALID", f"{field} contains duplicate ids")
    return value


def _merge_debt(value: object) -> dict:
    debt = _exact_keys(value, {"merge", "review"}, event="stage_exit.merge_debt")
    for field in ("merge", "review"):
        rows = debt[field]
        if not isinstance(rows, list) or len(rows) > 256 \
                or any(not isinstance(item, str) or not item or len(item) > 1024
                       for item in rows) or len(rows) != len(set(rows)):
            _contract_error("CYCLE_EVENT_DATA_INVALID", f"merge_debt.{field} is invalid")
    return debt


def _merge_debt_digest(debt: dict) -> str:
    normalized = {
        "merge": sorted(str(item) for item in debt.get("merge", [])),
        "review": sorted(str(item) for item in debt.get("review", [])),
    }
    return hashlib.sha256(json.dumps(
        normalized, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
    ).encode("utf-8")).hexdigest()


def _merge_disposition_summary(value: object) -> dict:
    fields = {"schema", "merged", "reviewed", "blocked", "failed", "abandoned", "pending"}
    summary = _exact_keys(value, fields, event="cycle_end.merge_disposition_summary")
    if summary["schema"] != "xunji.merge-disposition-summary.v1":
        _contract_error("CYCLE_EVENT_DATA_INVALID", "merge summary schema is invalid")
    all_ids: list[str] = []
    for field in ("merged", "reviewed", "blocked", "failed", "abandoned", "pending"):
        rows = _string_ids(summary[field], field=f"merge_disposition_summary.{field}",
                           pattern=_ASSIGNMENT_ID)
        if field == "pending" and rows:
            _contract_error(
                "CYCLE_EVENT_DATA_INVALID",
                "plan-bound cycle_end cannot retain pending assignments",
            )
        all_ids.extend(rows)
    if len(all_ids) != len(set(all_ids)):
        _contract_error(
            "CYCLE_EVENT_DATA_INVALID",
            "merge disposition assignment ids must be disjoint",
        )
    return summary


def _assignment_dispositions(value: object, *, lane_ids: list[str], summary: dict) -> list[dict]:
    if not isinstance(value, list) or len(value) != len(lane_ids) or len(value) > 16:
        _contract_error(
            "CYCLE_EVENT_DATA_INVALID",
            "assignment_dispositions must cover every exact plan lane",
        )
    required = {
        "lane_id", "assignment", "role", "runtime_state", "disposition",
        "result_digest", "review_receipt_hash",
    }
    rows: list[dict] = []
    for item in value:
        row = _exact_keys(item, required, event="cycle_end.assignment_disposition")
        if not _LANE_ID.fullmatch(str(row["lane_id"])) \
                or not _ASSIGNMENT_ID.fullmatch(str(row["assignment"])):
            _contract_error("CYCLE_EVENT_DATA_INVALID", "assignment disposition id invalid")
        _bounded_text(row["role"], field="assignment_disposition.role", maximum=128)
        if row["runtime_state"] not in {"returned", "failed"} \
                or row["disposition"] not in {
                    "merged", "reviewed", "blocked", "failed", "abandoned",
                }:
            _contract_error("CYCLE_EVENT_DATA_INVALID", "assignment disposition state invalid")
        _hex_digest(row["result_digest"], field="assignment_disposition.result_digest")
        _hex_digest(
            row["review_receipt_hash"], field="assignment_disposition.review_receipt_hash")
        rows.append(row)
    if [str(item["lane_id"]) for item in rows] != lane_ids:
        _contract_error(
            "CYCLE_EVENT_DATA_INVALID", "assignment dispositions do not preserve plan lane order")
    assignments = [str(item["assignment"]) for item in rows]
    if len(assignments) != len(set(assignments)):
        _contract_error("CYCLE_EVENT_DATA_INVALID", "assignment dispositions are not unique")
    projected = {
        key: sorted(str(item["assignment"]) for item in rows
                    if item["disposition"] == key)
        for key in ("merged", "reviewed", "blocked", "failed", "abandoned")
    }
    if any(projected[key] != sorted(summary[key]) for key in projected) \
            or summary["pending"]:
        _contract_error(
            "CYCLE_EVENT_DATA_INVALID", "merge summary differs from exact lane dispositions")
    return rows


def validate_typed_event_data(event: str, data: object, *, cycle: int | None = None) -> dict:
    """Validate one typed event payload without granting it runtime authority."""
    if event not in TYPED_CYCLE_EVENTS:
        _contract_error("CYCLE_EVENT_NAME_INVALID", f"not a typed event: {event}")
    if event == "cycle_end":
        if data == {}:
            return {}
        if isinstance(data, dict) and (
                "execution_mode" in data or "root_action_receipt" in data):
            payload = _exact_keys(
                data, {
                    "plan_id", "plan_digest", "execution_mode", "lane_ids",
                    "root_action_receipt", "next_action",
                }, event=event,
            )
            if payload["execution_mode"] != "ROOT_DIRECT":
                _contract_error(
                    "CYCLE_EVENT_DATA_INVALID", "root cycle_end execution mode is invalid")
            digest = _hex_digest(payload["plan_digest"], field="plan_digest")
            bound_plan_id = _plan_id(payload["plan_id"], digest=digest, cycle=cycle)
            lane_ids = _string_ids(
                payload["lane_ids"], field="lane_ids", pattern=_LANE_ID,
                minimum=1, maximum=1)
            _root_action_receipt(
                payload["root_action_receipt"], plan_id=bound_plan_id,
                plan_digest=digest, lane_id=lane_ids[0], cycle=cycle)
            _next_action_text(payload["next_action"])
            return payload
        payload = _exact_keys(
            data, {
                "plan_id", "plan_digest", "lane_ids", "assignment_dispositions",
                "merge_disposition_summary", "next_action",
            },
            event=event,
        )
        digest = _hex_digest(payload["plan_digest"], field="plan_digest")
        _plan_id(payload["plan_id"], digest=digest, cycle=cycle)
        lane_ids = _string_ids(
            payload["lane_ids"], field="lane_ids", pattern=_LANE_ID,
            minimum=1, maximum=16)
        summary = _merge_disposition_summary(payload["merge_disposition_summary"])
        _assignment_dispositions(
            payload["assignment_dispositions"], lane_ids=lane_ids, summary=summary)
        _next_action_text(payload["next_action"])
        return payload
    if event == "delegation_committed":
        payload = _exact_keys(data, {"plan_digest", "lane_ids"}, event=event)
        _hex_digest(payload["plan_digest"], field="plan_digest")
        _string_ids(payload["lane_ids"], field="lane_ids", pattern=_LANE_ID,
                    minimum=1, maximum=16)
        return payload
    if event == "stage_exit":
        required = {
            "writer", "plan_id", "from_plan_digest", "inputs_digest", "from_stage",
            "next_stage", "transition_reason", "readiness_digest", "merge_debt",
            "merge_debt_digest",
        }
        payload = _exact_keys(data, required, event=event)
        if payload["writer"] != "tools/work_plan.py":
            _contract_error("CYCLE_EVENT_DATA_INVALID", "stage_exit writer is invalid")
        from_digest = _hex_digest(payload["from_plan_digest"], field="from_plan_digest")
        _plan_id(payload["plan_id"], digest=from_digest)
        _hex_digest(payload["inputs_digest"], field="inputs_digest")
        _hex_digest(payload["readiness_digest"], field="readiness_digest")
        if payload["from_stage"] not in {"S1", "S2", "S3"} \
                or payload["next_stage"] not in {"S1", "S2", "S3"} \
                or payload["from_stage"] == payload["next_stage"]:
            _contract_error("CYCLE_EVENT_DATA_INVALID", "stage_exit stage transition is invalid")
        _bounded_text(payload["transition_reason"], field="transition_reason")
        debt = _merge_debt(payload["merge_debt"])
        debt_digest = _hex_digest(payload["merge_debt_digest"], field="merge_debt_digest")
        if debt_digest != _merge_debt_digest(debt):
            _contract_error("CYCLE_EVENT_DATA_INVALID", "merge_debt_digest mismatch")
        return payload
    base_required = {"writer", "plan_id", "plan_digest", "inputs_digest", "macro_stage"}
    if event == "stage_plan":
        payload = _exact_keys(data, base_required, {"prior_stage_exit_hash"}, event=event)
    else:
        payload = _exact_keys(data, base_required | {"prior_plan_digest"}, event=event)
    if payload["writer"] != "tools/work_plan.py":
        _contract_error("CYCLE_EVENT_DATA_INVALID", f"{event} writer is invalid")
    digest = _hex_digest(payload["plan_digest"], field="plan_digest")
    _plan_id(payload["plan_id"], digest=digest, cycle=cycle)
    _hex_digest(payload["inputs_digest"], field="inputs_digest")
    if payload["macro_stage"] not in {"S1", "S2", "S3"}:
        _contract_error("CYCLE_EVENT_DATA_INVALID", "macro_stage is invalid")
    if event == "stage_plan" and "prior_stage_exit_hash" in payload:
        _hex_digest(payload["prior_stage_exit_hash"], field="prior_stage_exit_hash")
    if event == "replan":
        _hex_digest(payload["prior_plan_digest"], field="prior_plan_digest")
    return payload


def _resolve_run_dir(path: str | Path) -> Path:
    p = Path(path)
    return (p if p.is_absolute() else ROOT / p).resolve()


def _journal_path(run_dir: Path) -> Path:
    return run_dir / "state" / JOURNAL


def _flush_file(handle) -> None:
    """Flush userspace bytes before the durability barrier.

    Journal files are opened unbuffered below so rollback remains deterministic,
    but keeping the explicit flush makes the required ordering visible and
    testable if the file implementation changes later.
    """
    handle.flush()


def _fsync_file(handle) -> None:
    os.fsync(handle.fileno())


def _fsync_directory(path: Path) -> None:
    flags = os.O_RDONLY
    if hasattr(os, "O_DIRECTORY"):
        flags |= os.O_DIRECTORY
    directory_fd = os.open(path, flags)
    try:
        os.fsync(directory_fd)
    finally:
        os.close(directory_fd)


def _rollback_uncommitted_append(handle, original_size: int) -> None:
    """Remove a tail whose durability barrier failed.

    This is recovery of an uncommitted append, not mutation of an admitted
    journal event.  The unbuffered handle prevents close() from re-emitting a
    failed userspace buffer after truncation.
    """
    os.ftruncate(handle.fileno(), original_size)
    os.fsync(handle.fileno())


@contextlib.contextmanager
def _journal_lock(run_dir: Path):
    path = run_dir / "state" / ".loop_journal.lock"
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a+", encoding="utf-8") as handle:
        if fcntl is not None:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
        try:
            yield
        finally:
            if fcntl is not None:
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def _looks_like_scope_dir(run_dir: Path) -> bool:
    markers = (
        "target.md",
        "surface.md",
        "frontier.md",
        "hypotheses.md",
        "evidence.md",
        "false_positive.md",
        "decisions.md",
        "review.md",
        "report.md",
        "retrospective.md",
    )
    return any((run_dir / marker).exists() for marker in markers)


def load_events(run_dir: str | Path) -> list[dict]:
    run_dir = _resolve_run_dir(run_dir)
    path = _journal_path(run_dir)
    if not path.exists():
        return []
    out: list[dict] = []
    for line_number, line in enumerate(
            path.read_text(encoding="utf-8", errors="replace").splitlines(), start=1):
        if not line.strip():
            continue
        try:
            item = json.loads(line)
        except Exception:
            out.append({
                _LOAD_ERROR_KEY: "malformed_json",
                "line": line_number,
                "raw": line[:200],
            })
            continue
        if not isinstance(item, dict):
            out.append({
                _LOAD_ERROR_KEY: "non_object_json",
                "line": line_number,
                "raw": line[:200],
            })
            continue
        out.append(item)
    return out


def _record_event_hash(record: dict) -> str:
    payload = dict(record)
    payload.pop("event_hash", None)
    return hashlib.sha256(json.dumps(
        payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
    ).encode("utf-8")).hexdigest()


def _validate_journal_envelope(record: dict, *, previous: dict | None) -> dict:
    """Validate the exact envelope and hash link emitted by the current writer."""
    if set(record) != _JOURNAL_ENVELOPE_KEYS:
        _contract_error(
            "CYCLE_EVENT_ENVELOPE_INVALID",
            f"journal envelope keys "
            f"missing={sorted(_JOURNAL_ENVELOPE_KEYS - set(record)) or 'none'} "
            f"extra={sorted(set(record) - _JOURNAL_ENVELOPE_KEYS) or 'none'}",
        )
    if record.get("schema") != SCHEMA:
        _contract_error("CYCLE_EVENT_ENVELOPE_INVALID", "journal schema mismatch")
    event = record.get("event")
    if not isinstance(event, str) or not event or len(event) > 128 \
            or event != event.strip().lower().replace("-", "_"):
        _contract_error("CYCLE_EVENT_ENVELOPE_INVALID", "event name is invalid")
    cycle = record.get("cycle")
    if isinstance(cycle, bool) or not isinstance(cycle, int) or cycle < 1:
        _contract_error("CYCLE_EVENT_ENVELOPE_INVALID", "cycle must be a positive integer")
    for field, maximum, allow_empty in (
        ("ts", 128, False), ("run_dir", 32768, False), ("note", 4096, True),
    ):
        value = record.get(field)
        if not isinstance(value, str) or len(value) > maximum \
                or (not allow_empty and not value.strip()):
            _contract_error("CYCLE_EVENT_ENVELOPE_INVALID", f"{field} is invalid")
    if record.get("canonical") != _JOURNAL_CANONICAL:
        _contract_error("CYCLE_EVENT_ENVELOPE_INVALID", "canonical marker mismatch")
    if not isinstance(record.get("data"), dict):
        _contract_error("CYCLE_EVENT_ENVELOPE_INVALID", "data must be an object")
    previous_hash = _hex_digest(
        record.get("previous_event_hash"), field="previous_event_hash", allow_empty=True)
    expected_previous = str(previous.get("event_hash") or "") if previous else ""
    if previous_hash != expected_previous:
        _contract_error("CYCLE_EVENT_HASH_CHAIN_INVALID", "previous event hash mismatch")
    event_hash = _hex_digest(record.get("event_hash"), field="event_hash")
    if event_hash != _record_event_hash(record):
        _contract_error("CYCLE_EVENT_HASH_CHAIN_INVALID", "event hash mismatch")
    return record


def _validate_typed_envelope(record: dict) -> dict:
    event = record.get("event")
    if not isinstance(event, str) or event not in TYPED_CYCLE_EVENTS:
        _contract_error("CYCLE_EVENT_NAME_INVALID", f"invalid typed event name: {event!r}")
    cycle = record.get("cycle")
    validate_typed_event_data(event, record.get("data"), cycle=cycle)
    formal_errors = contract_schema.named_schema_errors(
        record, "cycle-event.v1.schema.json")
    if formal_errors:
        _contract_error(
            "CYCLE_EVENT_ENVELOPE_INVALID",
            "formal schema mismatch: " + "; ".join(formal_errors[:4]),
        )
    return record


def validate_cycle_events(events: list[dict]) -> dict:
    """Validate the typed subset and its plan/delegation lifecycle in journal order.

    Unknown historical events without ``schema`` remain compatible. Every event
    emitted by the current schema validates its exact envelope and immediate hash
    link. Names which normalize to one of the reserved typed events are not
    ordinary events and cannot evade the strict contract with case or hyphen
    spelling.
    """
    active: dict | None = None
    pending_exit: dict | None = None
    delegated: set[str] = set()
    cycles: dict[int, dict] = {}
    typed_count = 0
    previous_cycle = 0
    ended_plan_digests: list[str] = []
    schema_chain_started = False
    for index, record in enumerate(events):
        if not isinstance(record, dict):
            _contract_error(
                "CYCLE_EVENT_JOURNAL_INVALID", f"record {index + 1} is not an object")
        if record.get(_LOAD_ERROR_KEY):
            _contract_error(
                "CYCLE_EVENT_JOURNAL_INVALID",
                f"record {record.get('line', index + 1)} "
                f"is {record.get(_LOAD_ERROR_KEY)}",
            )
        if "schema" in record:
            if record.get("schema") != SCHEMA:
                _contract_error(
                    "CYCLE_EVENT_ENVELOPE_INVALID",
                    f"unsupported journal schema: {record.get('schema')!r}",
                )
            previous = events[index - 1] if index else None
            _validate_journal_envelope(
                record, previous=previous if isinstance(previous, dict) else None)
            schema_chain_started = True
        elif schema_chain_started:
            # Legacy rows are accepted only as an immutable prefix.  Once the
            # current writer starts a hash chain, accepting a later schema-less
            # JSON object would let the next event reset previous_event_hash to
            # the empty legacy sentinel and silently split the audit trail.
            _contract_error(
                "CYCLE_EVENT_HASH_CHAIN_INVALID",
                f"schema-less record {index + 1} appears after the v1 hash chain",
            )
        raw_event = record.get("event")
        raw_name = raw_event if isinstance(raw_event, str) else ""
        normalized = raw_name.strip().lower().replace("-", "_")
        if normalized in TYPED_CYCLE_EVENTS and raw_name != normalized:
            _contract_error(
                "CYCLE_EVENT_NAME_INVALID",
                f"reserved typed event must use canonical name: {raw_name!r}",
            )
        cycle_raw = record.get("cycle")
        cycle = cycle_raw if isinstance(cycle_raw, int) and not isinstance(cycle_raw, bool) else 0
        if raw_name == "cycle_start":
            if cycle < 1:
                # Legacy/minimal records do not become typed state merely by name.
                continue
            state = cycles.setdefault(cycle, {
                "started": False, "ended": False, "plan_bound": False,
            })
            if state["started"] or state["ended"]:
                _contract_error("CYCLE_EVENT_DUPLICATE", f"duplicate cycle_start for cycle {cycle}")
            if cycle < previous_cycle:
                _contract_error("CYCLE_EVENT_SEQUENCE_INVALID", "cycle number moved backwards")
            state["started"] = True
            previous_cycle = max(previous_cycle, cycle)
            continue
        if raw_name not in TYPED_CYCLE_EVENTS:
            continue
        if record.get("schema") != SCHEMA:
            _contract_error(
                "CYCLE_EVENT_ENVELOPE_INVALID",
                f"typed event {raw_name!r} requires journal schema {SCHEMA}",
            )
        _validate_typed_envelope(record)
        typed_count += 1
        state = cycles.setdefault(cycle, {
            "started": False, "ended": False, "plan_bound": False,
        })
        if not state["started"]:
            _contract_error(
                "CYCLE_EVENT_SEQUENCE_INVALID",
                f"{raw_name} requires cycle_start in cycle {cycle}",
            )
        if state["ended"]:
            _contract_error(
                "CYCLE_EVENT_SEQUENCE_INVALID",
                f"{raw_name} occurs after cycle_end in cycle {cycle}",
            )
        if cycle < previous_cycle:
            _contract_error("CYCLE_EVENT_SEQUENCE_INVALID", "cycle number moved backwards")
        previous_cycle = max(previous_cycle, cycle)
        data = record["data"]
        if raw_name == "stage_plan":
            if active is not None and pending_exit is None:
                _contract_error(
                    "CYCLE_EVENT_DUPLICATE",
                    "stage_plan cannot replace an active plan without stage_exit",
                )
            if pending_exit is not None:
                if data.get("prior_stage_exit_hash") != pending_exit["event_hash"]:
                    _contract_error(
                        "CYCLE_EVENT_DIGEST_STALE",
                        "stage_plan does not bind the immediately prior stage_exit",
                    )
                if data.get("macro_stage") != pending_exit["next_stage"]:
                    _contract_error(
                        "CYCLE_EVENT_SEQUENCE_INVALID",
                        "stage_plan macro_stage differs from stage_exit next_stage",
                    )
            elif "prior_stage_exit_hash" in data:
                _contract_error(
                    "CYCLE_EVENT_SEQUENCE_INVALID",
                    "prior_stage_exit_hash exists without a pending stage_exit",
                )
            active = {
                "plan_id": data["plan_id"],
                "plan_digest": data["plan_digest"],
                "macro_stage": data["macro_stage"],
                "ended_cycle": 0,
            }
            pending_exit = None
            state["plan_bound"] = True
        elif raw_name == "replan":
            if active is None or pending_exit is not None:
                _contract_error(
                    "CYCLE_EVENT_SEQUENCE_INVALID", "replan requires one active plan")
            if data["prior_plan_digest"] != active["plan_digest"]:
                _contract_error(
                    "CYCLE_EVENT_DIGEST_STALE", "replan prior_plan_digest is stale")
            if data["plan_digest"] == active["plan_digest"]:
                _contract_error(
                    "CYCLE_EVENT_DUPLICATE", "replan must commit a new plan digest")
            if data["macro_stage"] != active["macro_stage"]:
                _contract_error(
                    "CYCLE_EVENT_SEQUENCE_INVALID", "replan cannot change macro stage")
            ended_cycle = int(active.get("ended_cycle") or 0)
            if ended_cycle and cycle <= ended_cycle:
                _contract_error(
                    "CYCLE_EVENT_SEQUENCE_INVALID",
                    "a cycle-ended plan can replan only in a later cycle",
                )
            active = {
                "plan_id": data["plan_id"],
                "plan_digest": data["plan_digest"],
                "macro_stage": data["macro_stage"],
                "ended_cycle": 0,
            }
            state["plan_bound"] = True
        elif raw_name == "delegation_committed":
            if not state["plan_bound"] or active is None or pending_exit is not None:
                _contract_error(
                    "CYCLE_EVENT_SEQUENCE_INVALID",
                    "delegation_committed requires this cycle's active plan",
                )
            digest = data["plan_digest"]
            if digest != active["plan_digest"]:
                _contract_error(
                    "CYCLE_EVENT_DIGEST_STALE", "delegation plan_digest is stale")
            if digest in delegated:
                _contract_error(
                    "CYCLE_EVENT_DUPLICATE", "delegation already committed for this plan")
            delegated.add(digest)
        elif raw_name == "stage_exit":
            if active is None or pending_exit is not None:
                _contract_error(
                    "CYCLE_EVENT_SEQUENCE_INVALID", "stage_exit requires one active plan")
            if data["from_plan_digest"] != active["plan_digest"]:
                _contract_error(
                    "CYCLE_EVENT_DIGEST_STALE", "stage_exit from_plan_digest is stale")
            if data["from_stage"] != active["macro_stage"]:
                _contract_error(
                    "CYCLE_EVENT_SEQUENCE_INVALID", "stage_exit from_stage is stale")
            if data["plan_id"] != active["plan_id"]:
                _contract_error(
                    "CYCLE_EVENT_DIGEST_STALE", "stage_exit plan_id is stale")
            if active["plan_digest"] not in delegated:
                _contract_error(
                    "CYCLE_EVENT_SEQUENCE_INVALID",
                    "stage_exit requires a committed delegation decision",
                )
            ended_cycle = int(active.get("ended_cycle") or 0)
            if not ended_cycle or cycle <= ended_cycle:
                _contract_error(
                    "CYCLE_EVENT_SEQUENCE_INVALID",
                    "stage_exit requires the prior plan's typed cycle_end in an earlier cycle",
                )
            pending_exit = {
                "event_hash": record["event_hash"],
                "next_stage": data["next_stage"],
            }
            active = None
        else:  # cycle_end
            if pending_exit is not None:
                _contract_error(
                    "CYCLE_EVENT_SEQUENCE_INVALID",
                    "cycle_end cannot strand a stage_exit without the next stage_plan",
                )
            if state["plan_bound"]:
                if not data:
                    _contract_error(
                        "CYCLE_EVENT_DATA_INVALID",
                        "plan-bound cycle_end requires plan_digest and merge summary",
                    )
                if active is None or data["plan_digest"] != active["plan_digest"]:
                    _contract_error(
                        "CYCLE_EVENT_DIGEST_STALE", "cycle_end plan_digest is stale")
                if active["plan_digest"] not in delegated:
                    _contract_error(
                        "CYCLE_EVENT_SEQUENCE_INVALID",
                        "cycle_end requires the current plan's delegation decision",
                    )
                if data.get("plan_id") != active.get("plan_id"):
                    _contract_error(
                        "CYCLE_EVENT_DIGEST_STALE", "cycle_end plan_id is stale")
                active["ended_cycle"] = cycle
                ended_plan_digests.append(str(active["plan_digest"]))
            elif data:
                _contract_error(
                    "CYCLE_EVENT_SEQUENCE_INVALID",
                    "structured plan cycle_end requires a plan event in the same cycle",
                )
            state["ended"] = True
    return {
        "typed_event_count": typed_count,
        "active_plan_digest": str(active.get("plan_digest") or "") if active else "",
        "active_stage": str(active.get("macro_stage") or "") if active else "",
        "pending_stage_exit_hash": str(pending_exit.get("event_hash") or "")
        if pending_exit else "",
        "plan_bound_cycles": sorted(
            cycle for cycle, state in cycles.items() if state.get("plan_bound")),
        "ended_plan_digests": ended_plan_digests,
    }


def typed_event_errors(events: list[dict]) -> list[str]:
    """Return a stable first-error diagnostic for read-only status/check callers."""
    try:
        validate_cycle_events(events)
    except JournalContractError as exc:
        return [str(exc)]
    return []


def plan_cycle_ended(events: list[dict], plan_digest: str) -> bool:
    """Return true only for a validated typed cycle_end of the exact plan."""
    if not _HEX64.fullmatch(str(plan_digest or "")):
        return False
    try:
        state = validate_cycle_events(events)
    except JournalContractError:
        return False
    return str(plan_digest) in state.get("ended_plan_digests", [])


def derive_cycle_end_data(
    run_dir: str | Path,
    *,
    next_action: str,
    plan_digest: str = "",
) -> dict:
    """Derive an exhaustive cycle_end payload from the current plan and receipts.

    This is the only producer for plan-bound cycle_end data.  Callers may request
    ``end`` and its exact next action but cannot submit disposition arrays.
    """
    run = _resolve_run_dir(run_dir)
    try:
        import run_model
        work_plan = sys.modules.get("work_plan")
        main_module = sys.modules.get("__main__")
        if work_plan is None and main_module is not None:
            try:
                main_path = Path(str(getattr(main_module, "__file__", ""))).resolve()
            except (OSError, RuntimeError, ValueError):
                main_path = Path()
            if main_path == Path(__file__).resolve().with_name("work_plan.py"):
                work_plan = main_module
        if work_plan is None:
            import work_plan as work_plan_module
            work_plan = work_plan_module
    except Exception as exc:
        _contract_error("CYCLE_EVENT_DERIVATION_UNAVAILABLE", exc.__class__.__name__)
    action = _next_action_text(next_action)
    try:
        frontier = run_model.summary(run)
        active_fronts = [str(item) for item in frontier.get("open", [])]
    except Exception as exc:
        _contract_error("CYCLE_EVENT_NEXT_ACTION_CONTEXT_INVALID", exc.__class__.__name__)
    semantic_error = validate_next_action_semantics(
        action, active_fronts=active_fronts)
    if semantic_error:
        _contract_error(
            "CYCLE_EVENT_NEXT_ACTION_INVALID",
            semantic_error,
        )
    try:
        plan = work_plan.transaction_bound_plan(run)
    except JournalContractError:
        raise
    except Exception as exc:
        _contract_error("CYCLE_EVENT_CURRENT_PLAN_INVALID", str(exc))
    digest = str(plan.get("plan_digest") or "")
    requested_digest = str(plan_digest or "")
    if requested_digest and requested_digest != digest:
        _contract_error(
            "CYCLE_EVENT_PLAN_DIGEST_STALE",
            "requested plan differs from the current committed v2 transaction",
        )
    projection = run_model.plan_cycle_projection(run, plan=plan)
    debt = projection.get("debt") if isinstance(projection.get("debt"), dict) else {}
    summary = projection.get("merge_disposition_summary") \
        if isinstance(projection.get("merge_disposition_summary"), dict) else {}
    if debt.get("merge") or debt.get("review") or summary.get("pending"):
        detail = [
            *[str(item) for item in debt.get("merge", [])],
            *[str(item) for item in debt.get("review", [])],
            *[f"pending:{item}" for item in summary.get("pending", [])],
        ]
        _contract_error("CYCLE_EVENT_PLAN_DEBT_OPEN", "; ".join(detail[:8]))
    lane_ids = [str(item) for item in projection.get("lane_ids", [])]
    mode = str(plan.get("execution_mode") or "")
    if mode == "ROOT_DIRECT":
        receipt = projection.get("root_action_receipt")
        plan_lanes = plan.get("lanes") if isinstance(plan.get("lanes"), list) else []
        plan_lane = plan_lanes[0] if len(plan_lanes) == 1 \
            and isinstance(plan_lanes[0], dict) else {}
        expected_lane_ids = [str(plan_lane.get("id") or "")] if plan_lane else []
        turn_binding = plan.get("turn_binding") \
            if isinstance(plan.get("turn_binding"), dict) else {}
        if len(lane_ids) != 1 or lane_ids != expected_lane_ids \
                or str(projection.get("plan_id") or "") != str(plan.get("plan_id") or "") \
                or not isinstance(receipt, dict):
            _contract_error(
                "CYCLE_EVENT_PLAN_COVERAGE_INCOMPLETE",
                "ROOT_DIRECT requires one exact terminal action receipt",
            )
        if str(receipt.get("parent_run") or "") != run.name \
                or str(receipt.get("capability_id") or "") \
                != str(plan_lane.get("capability_id") or "") \
                or str(receipt.get("capability_effect") or "") \
                != str(plan_lane.get("effect") or "") \
                or str(receipt.get("session_id") or "") \
                != str(turn_binding.get("session_id") or "") \
                or str(receipt.get("prompt_sha256") or "") \
                != str(turn_binding.get("prompt_sha256") or ""):
            _contract_error(
                "CYCLE_EVENT_PLAN_COVERAGE_INCOMPLETE",
                "ROOT_DIRECT receipt differs from the exact plan/turn binding",
            )
        payload = {
            "plan_id": str(projection.get("plan_id") or ""),
            "plan_digest": digest,
            "execution_mode": "ROOT_DIRECT",
            "lane_ids": lane_ids,
            "root_action_receipt": receipt,
            "next_action": action,
        }
        validate_typed_event_data(
            "cycle_end", payload, cycle=int(plan.get("cycle_id") or 0))
        return payload
    dispositions = projection.get("assignment_dispositions")
    if not lane_ids or not isinstance(dispositions, list) \
            or len(dispositions) != len(lane_ids):
        _contract_error("CYCLE_EVENT_PLAN_COVERAGE_INCOMPLETE", "lane disposition coverage mismatch")
    return {
        "plan_id": str(projection.get("plan_id") or ""),
        "plan_digest": digest,
        "lane_ids": lane_ids,
        "assignment_dispositions": dispositions,
        "merge_disposition_summary": summary,
        "next_action": action,
    }


def _next_cycle(events: list[dict], event: str) -> int:
    cycles = [int(e.get("cycle", 0) or 0) for e in events if isinstance(e.get("cycle"), int)]
    current = max(cycles) if cycles else 0
    return current + 1 if event == "cycle_start" else max(current, 1)


def append_event(
    run_dir: str | Path,
    event: str,
    *,
    note: str = "",
    data: dict | None = None,
    next_action: str = "",
) -> dict:
    run_dir = _resolve_run_dir(run_dir)
    if not run_dir.is_dir():
        raise FileNotFoundError(f"run directory does not exist: {run_dir}")
    if not _looks_like_scope_dir(run_dir):
        raise ValueError(f"directory does not look like a Xunji run/review scope: {run_dir}")
    event = event.strip().lower().replace("-", "_")
    with _journal_lock(run_dir):
        events = load_events(run_dir)
        # Existing malformed typed state cannot be extended with a plausible
        # looking successor. Ordinary historical events remain compatible.
        typed_state = validate_cycle_events(events)
        if event == "cycle_end" and typed_state.get("active_plan_digest"):
            if data not in (None, {}):
                _contract_error(
                    "CYCLE_EVENT_CALLER_DATA_FORBIDDEN",
                    "plan-bound cycle_end is derived from current receipts",
                )
            data = derive_cycle_end_data(
                run_dir,
                next_action=next_action,
                plan_digest=str(typed_state["active_plan_digest"]),
            )
        elif event == "cycle_end" and next_action:
            _contract_error(
                "CYCLE_EVENT_NEXT_ACTION_UNBOUND",
                "next_action is accepted only for a plan-bound cycle_end",
            )
        rec = {
            "schema": SCHEMA,
            "ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "run_dir": str(run_dir),
            "cycle": _next_cycle(events, event),
            "event": event,
            "note": note,
            "data": data or {},
            "previous_event_hash": str(events[-1].get("event_hash") or "") if events else "",
            "canonical": _JOURNAL_CANONICAL,
        }
        rec["event_hash"] = _record_event_hash(rec)
        validate_cycle_events([*events, rec])
        path = _journal_path(run_dir)
        path.parent.mkdir(parents=True, exist_ok=True)
        existed_before = path.exists()
        original_size = path.stat().st_size if existed_before else 0
        encoded = (json.dumps(rec, ensure_ascii=False, sort_keys=True) + "\n").encode("utf-8")
        # Unbuffered binary append makes a failed durability barrier
        # recoverable without a buffered close re-appending the rejected tail.
        with path.open("ab", buffering=0) as f:
            try:
                written = f.write(encoded)
                if written != len(encoded):
                    raise OSError(f"short journal append: {written}/{len(encoded)} bytes")
                try:
                    os.chmod(path, 0o600)
                except OSError:
                    pass
                _flush_file(f)
                _fsync_file(f)
                # A new directory entry needs its own durability barrier.  A
                # zero-byte file may be residue from an earlier failed create,
                # so retrying it must also sync the parent directory.
                if not existed_before or original_size == 0:
                    _fsync_directory(path.parent)
            except Exception as append_error:
                try:
                    _rollback_uncommitted_append(f, original_size)
                except Exception as rollback_error:
                    raise JournalDurabilityError(
                        "journal append durability failed and rollback could not be confirmed: "
                        f"append={append_error}; rollback={rollback_error}"
                    ) from append_error
                raise JournalDurabilityError(
                    f"journal append durability failed; uncommitted tail rolled back: {append_error}"
                ) from append_error
    return rec


def summarize(run_dir: str | Path) -> dict:
    run_dir = _resolve_run_dir(run_dir)
    events = load_events(run_dir)
    last_cycle = max([int(e.get("cycle", 0) or 0) for e in events], default=0)
    current = [e for e in events if int(e.get("cycle", 0) or 0) == last_cycle]
    event_names = [str(e.get("event", "")) for e in current]
    incomplete = bool(last_cycle and "cycle_start" in event_names and "cycle_end" not in event_names)
    interrupted = "interrupt" in event_names
    open_phase = ""
    phase_events = [e for e in current if str(e.get("event", "")) in PHASE_EVENTS]
    for rec in phase_events:
        phase = str((rec.get("data") or {}).get("phase") or "").strip()
        if rec.get("event") == "phase_start":
            open_phase = phase
        elif rec.get("event") == "phase_end" and phase == open_phase:
            open_phase = ""
    typed_errors = typed_event_errors(events)
    typed_state: dict = {}
    if not typed_errors:
        typed_state = validate_cycle_events(events)
    return {
        "schema": SCHEMA,
        "run_dir": str(run_dir),
        "path": str(_journal_path(run_dir)),
        "event_count": len(events),
        "last_cycle": last_cycle,
        "last_cycle_events": event_names,
        "last_cycle_phase_events": [
            {
                "event": e.get("event"),
                "phase": (e.get("data") or {}).get("phase", ""),
                "note": e.get("note", ""),
            }
            for e in phase_events
        ],
        "open_phase": open_phase,
        "incomplete_cycle": incomplete,
        "interrupted": interrupted,
        "last_event": events[-1] if events else None,
        "typed_contract_valid": not typed_errors,
        "typed_contract_errors": typed_errors,
        "typed_cycle_state": typed_state,
    }


def phase_display(phase: str) -> str:
    raw = status_style.phase_display(phase, enabled=False, bracket=False)
    if "｜" in raw:
        name, cn = raw.split("｜", 1)
        return f"{name}（{cn}）"
    return raw


def _event_display(event: str) -> str:
    event = str(event or "").strip()
    cn = EVENT_CN.get(event)
    return f"{cn}({event})" if cn else event


def _pretty_block(title: str, rows: list[str], *, color: str = "cyan", enabled: bool | None = None) -> str:
    return status_style.box(title, rows, color=color, enabled=enabled) + "\n"


def render_phase_banner(rec: dict, *, color: bool | None = None) -> str:
    phase = str((rec.get("data") or {}).get("phase") or "unknown").strip()
    is_start = rec.get("event") == "phase_start"
    title = "阶段开始" if is_start else "阶段结束"
    marker = "XUNJI PHASE START" if is_start else "XUNJI PHASE END"
    note = str(rec.get("note") or "").strip()
    theme = status_style.PHASE_COLOR.get(phase, "green" if is_start else "yellow")
    rows = [
        status_style.field("阶段", status_style.phase_display(phase, enabled=color), theme, enabled=color),
        status_style.field("运行目录", rec.get("run_dir"), "gray", enabled=color),
        status_style.field("循环编号", rec.get("cycle"), "gray", enabled=color),
        status_style.field("机器标记", status_style.tag(marker, theme, enabled=color), "gray", enabled=color),
    ]
    if note:
        rows.append(status_style.field("说明", note, "blue", enabled=color))
    return _pretty_block(title, rows, color=theme, enabled=color)


def render_markdown(data: dict, *, color: bool | None = None) -> str:
    event_names = [_event_display(e) for e in data.get("last_cycle_events", [])]
    lines = [
        "# 循环日志状态",
        "",
        _pretty_block("循环日志", [
            status_style.field("事件总数", data["event_count"], "gray", enabled=color),
            status_style.field("最近循环", data["last_cycle"], "gray", enabled=color),
            status_style.field("循环未收尾", "是" if data["incomplete_cycle"] else "否", "yellow" if data["incomplete_cycle"] else "green", enabled=color),
            status_style.field("发生中断", "是" if data["interrupted"] else "否", "red" if data["interrupted"] else "green", enabled=color),
            status_style.field(
                "当前打开阶段",
                status_style.phase_display(data.get("open_phase"), enabled=color) if data.get("open_phase") else status_style.tag("无", "gray", enabled=color),
                "cyan",
                enabled=color,
            ),
            status_style.field("日志路径", data["path"], "gray", enabled=color),
        ], color="cyan", enabled=color).rstrip(),
    ]
    if data.get("last_cycle_events"):
        lines.append("- " + status_style.field("最近循环事件", "，".join(event_names), "blue", enabled=color))
    if data.get("last_cycle_phase_events"):
        rendered = [
            f"{_event_display(p['event'])}:{status_style.phase_display(p['phase'], enabled=color)}"
            for p in data["last_cycle_phase_events"]
        ]
        lines.append("- " + status_style.field("最近阶段事件", "，".join(rendered), "purple", enabled=color))
    if data.get("last_event"):
        lines.append("- " + status_style.field("最近事件", _event_display(data["last_event"].get("event")), "blue", enabled=color))
    return "\n".join(lines) + "\n"


def _selftest() -> int:
    d = Path(tempfile.mkdtemp())
    run = d / "run"
    run.mkdir()
    (run / "frontier.md").write_text("# Frontier\n", encoding="utf-8")
    (run / "state").mkdir()
    checks: list[tuple[str, bool]] = []
    start = append_event(run, "cycle_start", note="begin")
    append_event(run, "plan", note="F-001")
    append_event(run, "action", note="probe")
    append_event(run, "phase_start", note="choose next front", data={"phase": "Root Orchestrator"})
    phase_open = summarize(run)
    append_event(run, "phase_end", note="front chosen", data={"phase": "Root Orchestrator"})
    phase_closed = summarize(run)
    append_event(run, "write_result", note="decision updated")
    mid = summarize(run)
    append_event(run, "cycle_end", note="done")
    done = summarize(run)
    append_event(run, "cycle_start", note="next")
    append_event(run, "interrupt", note="tool failure")
    interrupted = summarize(run)
    plain_dir = d / "plain"
    plain_dir.mkdir()
    rejected_plain_dir = False
    try:
        append_event(plain_dir, "cycle_start")
    except ValueError:
        rejected_plain_dir = True
    evidence_only_dir = d / "evidence_only"
    (evidence_only_dir / "evidence").mkdir(parents=True)
    rejected_evidence_only_dir = False
    try:
        append_event(evidence_only_dir, "cycle_start")
    except ValueError:
        rejected_evidence_only_dir = True

    checks.append(("journal file exists", _journal_path(run).exists()))
    checks.append(("cycle starts at one", start["cycle"] == 1))
    checks.append(("mid cycle incomplete", mid["incomplete_cycle"] is True))
    checks.append(("phase start is visible", phase_open["open_phase"] == "Root Orchestrator"))
    checks.append(("phase end closes phase", phase_closed["open_phase"] == ""))
    checks.append(("phase banner renders Chinese", "[Xunji] [阶段开始]" in render_phase_banner({
        "event": "phase_start",
        "run_dir": str(run),
        "cycle": 1,
        "note": "test",
        "data": {"phase": "Root Orchestrator"},
    }) and "[Root Orchestrator｜主驾驶调度]" in render_phase_banner({
        "event": "phase_start",
        "run_dir": str(run),
        "cycle": 1,
        "note": "test",
        "data": {"phase": "Root Orchestrator"},
    })))
    checks.append(("phase end banner renders Chinese", "[Xunji] [阶段结束]" in render_phase_banner({
        "event": "phase_end",
        "run_dir": str(run),
        "cycle": 1,
        "note": "test",
        "data": {"phase": "Root Orchestrator"},
    })))
    checks.append(("cycle end completes", done["incomplete_cycle"] is False))
    checks.append(("interrupt visible", interrupted["interrupted"] is True and interrupted["incomplete_cycle"] is True))
    checks.append(("load events", len(load_events(run)) == 9))
    checks.append(("plain directory is rejected", rejected_plain_dir))
    checks.append(("evidence-only directory is rejected", rejected_evidence_only_dir))

    def scope(name: str) -> Path:
        item = d / name
        (item / "state").mkdir(parents=True)
        (item / "frontier.md").write_text("# Frontier\n", encoding="utf-8")
        return item

    durability = scope("durability")
    module = sys.modules[__name__]
    with patch.object(module, "_flush_file", wraps=_flush_file) as flush_spy, \
            patch.object(os, "fsync", wraps=os.fsync) as fsync_spy:
        append_event(durability, "cycle_start", note="durable")
    checks.append(("append flushes before returning success", flush_spy.call_count == 1))
    checks.append(("new journal fsyncs file and parent directory",
                   fsync_spy.call_count >= 2 and len(load_events(durability)) == 1))

    flush_failure = scope("flush_failure")
    flush_failed_closed = False
    with patch.object(module, "_flush_file", side_effect=OSError("injected flush failure")):
        try:
            append_event(flush_failure, "cycle_start", note="must not survive")
        except JournalDurabilityError:
            flush_failed_closed = True
    checks.append(("flush failure rejects and rolls back the uncommitted event",
                   flush_failed_closed
                   and _journal_path(flush_failure).read_bytes() == b""
                   and load_events(flush_failure) == []))
    flush_retry = append_event(flush_failure, "cycle_start", note="retry")
    checks.append(("flush failure retry admits exactly one first event",
                   flush_retry["cycle"] == 1
                   and len(load_events(flush_failure)) == 1
                   and load_events(flush_failure)[0]["note"] == "retry"))

    fsync_failure = scope("fsync_failure")
    seed = append_event(fsync_failure, "cycle_start", note="seed")
    seed_bytes = _journal_path(fsync_failure).read_bytes()
    fsync_failed_closed = False
    with patch.object(module, "_fsync_file", side_effect=OSError("injected fsync failure")):
        try:
            append_event(fsync_failure, "plan", note="must not survive")
        except JournalDurabilityError:
            fsync_failed_closed = True
    checks.append(("file fsync failure preserves the prior committed journal",
                   fsync_failed_closed
                   and _journal_path(fsync_failure).read_bytes() == seed_bytes
                   and load_events(fsync_failure) == [seed]))
    fsync_retry = append_event(fsync_failure, "plan", note="retry")
    checks.append(("file fsync failure retry neither duplicates nor skips the successor",
                   len(load_events(fsync_failure)) == 2
                   and fsync_retry["previous_event_hash"] == seed["event_hash"]))

    directory_failure = scope("directory_failure")
    directory_failed_closed = False
    with patch.object(module, "_fsync_directory",
                      side_effect=OSError("injected directory fsync failure")):
        try:
            append_event(directory_failure, "cycle_start", note="must not survive")
        except JournalDurabilityError:
            directory_failed_closed = True
    checks.append(("directory fsync failure rejects and rolls back the new-file event",
                   directory_failed_closed
                   and _journal_path(directory_failure).read_bytes() == b""
                   and load_events(directory_failure) == []))
    append_event(directory_failure, "cycle_start", note="retry")
    checks.append(("directory fsync failure retry admits one event",
                   len(load_events(directory_failure)) == 1
                   and load_events(directory_failure)[0]["note"] == "retry"))

    def plan_data(digest: str, stage: str, *, prior_plan: str = "",
                  prior_exit: str = "") -> dict:
        value = {
            "writer": "tools/work_plan.py",
            "plan_id": f"WP-1-{digest[:8]}",
            "plan_digest": digest,
            "inputs_digest": "a" * 64,
            "macro_stage": stage,
        }
        if prior_plan:
            value["prior_plan_digest"] = prior_plan
        if prior_exit:
            value["prior_stage_exit_hash"] = prior_exit
        return value

    def summary(*, pending: list[str] | None = None) -> dict:
        return {
            "schema": "xunji.merge-disposition-summary.v1",
            "merged": ["A-HUNTER"],
            "reviewed": ["A-REVIEWER"],
            "blocked": [],
            "failed": [],
            "abandoned": [],
            "pending": pending or [],
        }

    def root_receipt(digest: str, *, outcome: str = "succeeded",
                     lane_id: str = "L-ROOT", cycle: int = 1) -> dict:
        value = {
            "schema": "xunji.root-action-receipt.v1",
            "parent_run": "root-direct-fixture",
            "plan_id": f"WP-{cycle}-{digest[:8]}",
            "plan_digest": digest,
            "cycle_id": cycle,
            "lane_id": lane_id,
            "capability_id": "read.run-model",
            "capability_effect": "local_read",
            "session_id": "session-root-direct",
            "prompt_sha256": "4" * 64,
            "tool_use_id": "tool-root-direct",
            "action_sha256": "5" * 64,
            "claim_event_seq": 4,
            "claim_event_hash": "6" * 64,
            "runtime_event_seq": 5,
            "runtime_event_hash": "7" * 64,
            "outcome": outcome,
            "response_sha256": "8" * 64,
            "recorded_at": "2026-07-17T00:00:00Z",
        }
        value["receipt_hash"] = _sha256_json(value)
        return value

    p1, p2, p3, stale_digest = "1" * 64, "2" * 64, "3" * 64, "9" * 64
    next_action = "运行 check_run 验证当前计划"
    typed = scope("typed")
    append_event(typed, "cycle_start", note="typed begin")
    append_event(typed, "stage_plan", data=plan_data(p1, "S1"))
    append_event(typed, "delegation_committed", data={
        "plan_digest": p1, "lane_ids": ["L-HUNTER"],
    })
    empty_debt = {"merge": [], "review": []}
    append_event(typed, "replan", data=plan_data(p2, "S1", prior_plan=p1))
    append_event(typed, "delegation_committed", data={
        "plan_digest": p2, "lane_ids": ["L-HUNTER", "L-REVIEWER"],
    })
    typed_status = summarize(typed)
    checks.append(("typed stage/replan/delegation sequence validates",
                   typed_status["typed_contract_valid"] is True
                   and typed_status["typed_cycle_state"]["active_plan_digest"] == p2
                   and typed_status["typed_cycle_state"]["plan_bound_cycles"] == [1]))

    out_of_order = scope("out_of_order")
    append_event(out_of_order, "cycle_start")
    out_of_order_rejected = False
    try:
        append_event(out_of_order, "delegation_committed", data={
            "plan_digest": p1, "lane_ids": ["L-HUNTER"],
        })
    except JournalContractError as exc:
        out_of_order_rejected = exc.code == "CYCLE_EVENT_SEQUENCE_INVALID"
    checks.append(("out-of-order delegation fixture is rejected", out_of_order_rejected))

    missing = scope("missing")
    append_event(missing, "cycle_start")
    missing_rejected = False
    incomplete_plan = plan_data(p1, "S1")
    incomplete_plan.pop("inputs_digest")
    try:
        append_event(missing, "stage_plan", data=incomplete_plan)
    except JournalContractError as exc:
        missing_rejected = exc.code == "CYCLE_EVENT_DATA_INVALID"
    checks.append(("missing typed field fixture is rejected", missing_rejected))

    duplicate = scope("duplicate")
    append_event(duplicate, "cycle_start")
    append_event(duplicate, "stage_plan", data=plan_data(p1, "S1"))
    append_event(duplicate, "delegation_committed", data={
        "plan_digest": p1, "lane_ids": ["L-HUNTER"],
    })
    duplicate_rejected = False
    try:
        append_event(duplicate, "delegation_committed", data={
            "plan_digest": p1, "lane_ids": ["L-HUNTER"],
        })
    except JournalContractError as exc:
        duplicate_rejected = exc.code == "CYCLE_EVENT_DUPLICATE"
    checks.append(("duplicate delegation fixture is rejected", duplicate_rejected))

    stale = scope("stale")
    append_event(stale, "cycle_start")
    append_event(stale, "stage_plan", data=plan_data(p1, "S1"))
    append_event(stale, "delegation_committed", data={
        "plan_digest": p1, "lane_ids": ["L-HUNTER"],
    })
    stale_rejected = False
    try:
        append_event(stale, "replan", data=plan_data(
            p2, "S1", prior_plan=stale_digest))
    except JournalContractError as exc:
        stale_rejected = exc.code == "CYCLE_EVENT_DIGEST_STALE"
    checks.append(("stale prior-plan digest fixture is rejected", stale_rejected))

    exit_missing_binding = False
    bad_exit = {
        "writer": "tools/work_plan.py",
        "plan_id": f"WP-1-{p1[:8]}",
        "from_plan_digest": p1,
        "inputs_digest": "a" * 64,
        "from_stage": "S1",
        "next_stage": "S2",
        "transition_reason": "inventory is ready",
        "merge_debt": empty_debt,
        "merge_debt_digest": _merge_debt_digest(empty_debt),
    }
    try:
        append_event(stale, "stage_exit", data=bad_exit)
    except JournalContractError as exc:
        exit_missing_binding = exc.code == "CYCLE_EVENT_DATA_INVALID"
    checks.append(("stage exit requires readiness digest binding", exit_missing_binding))

    end_missing = scope("end_missing")
    append_event(end_missing, "cycle_start")
    append_event(end_missing, "stage_plan", data=plan_data(p1, "S1"))
    append_event(end_missing, "delegation_committed", data={
        "plan_digest": p1, "lane_ids": ["L-HUNTER"],
    })
    end_missing_rejected = False
    try:
        append_event(
            end_missing, "cycle_end", data={}, next_action=next_action)
    except JournalContractError as exc:
        end_missing_rejected = exc.code in {
            "CYCLE_EVENT_CURRENT_PLAN_INVALID",
            "CYCLE_EVENT_PLAN_COVERAGE_INCOMPLETE",
        }
    checks.append(("plan-bound cycle end must be mechanically derived", end_missing_rejected))

    next_action_missing_rejected = False
    try:
        append_event(end_missing, "cycle_end", data={})
    except JournalContractError as exc:
        next_action_missing_rejected = exc.code == "CYCLE_EVENT_DATA_INVALID"
    checks.append(("plan-bound end requires an exact next action",
                   next_action_missing_rejected))

    pending_end_rejected = False
    try:
        append_event(end_missing, "cycle_end", data={
            "plan_digest": p1,
            "merge_disposition_summary": summary(pending=["A-PENDING"]),
        })
    except JournalContractError as exc:
        pending_end_rejected = exc.code == "CYCLE_EVENT_CALLER_DATA_FORBIDDEN"
    checks.append(("caller cannot self-report an empty/pending cycle summary",
                   pending_end_rejected))

    stale_end_rejected = False
    try:
        append_event(end_missing, "cycle_end", data={
            "plan_digest": stale_digest,
            "merge_disposition_summary": summary(),
        })
    except JournalContractError as exc:
        stale_end_rejected = exc.code == "CYCLE_EVENT_CALLER_DATA_FORBIDDEN"
    checks.append(("caller cannot self-report a stale plan cycle end", stale_end_rejected))

    root_success_receipt = root_receipt(p1)
    root_success_payload = {
        "plan_id": f"WP-1-{p1[:8]}",
        "plan_digest": p1,
        "execution_mode": "ROOT_DIRECT",
        "lane_ids": ["L-ROOT"],
        "root_action_receipt": root_success_receipt,
        "next_action": next_action,
    }
    root_failed_receipt = root_receipt(p1, outcome="failed")
    root_failed_payload = dict(
        root_success_payload, root_action_receipt=root_failed_receipt)
    root_success_valid = root_failed_valid = False
    try:
        root_success_valid = validate_typed_event_data(
            "cycle_end", root_success_payload, cycle=1) == root_success_payload
        root_failed_valid = validate_typed_event_data(
            "cycle_end", root_failed_payload, cycle=1) == root_failed_payload
    except JournalContractError:
        pass
    checks.append(("ROOT_DIRECT succeeded receipt is a valid terminal cycle variant",
                   root_success_valid))
    checks.append(("ROOT_DIRECT failed receipt is an honest terminal cycle variant",
                   root_failed_valid))

    pending_receipt = dict(root_success_receipt, outcome="pending")
    pending_receipt["receipt_hash"] = _sha256_json({
        key: item for key, item in pending_receipt.items() if key != "receipt_hash"
    })
    pending_outcome_rejected = False
    try:
        validate_typed_event_data("cycle_end", dict(
            root_success_payload, root_action_receipt=pending_receipt), cycle=1)
    except JournalContractError as exc:
        pending_outcome_rejected = exc.code == "CYCLE_EVENT_DATA_INVALID"
    checks.append(("ROOT_DIRECT pending outcome cannot masquerade as terminal",
                   pending_outcome_rejected))

    tampered_receipt = dict(root_success_receipt, response_sha256="9" * 64)
    tampered_receipt_rejected = False
    try:
        validate_typed_event_data("cycle_end", dict(
            root_success_payload, root_action_receipt=tampered_receipt), cycle=1)
    except JournalContractError as exc:
        tampered_receipt_rejected = exc.code == "CYCLE_EVENT_DATA_INVALID"
    checks.append(("ROOT_DIRECT receipt mutation invalidates its content hash",
                   tampered_receipt_rejected))

    root_mixing_rejected = False
    try:
        validate_typed_event_data("cycle_end", dict(
            root_success_payload,
            assignment_dispositions=[],
            merge_disposition_summary=summary(),
        ), cycle=1)
    except JournalContractError as exc:
        root_mixing_rejected = exc.code == "CYCLE_EVENT_DATA_INVALID"
    checks.append(("ROOT_DIRECT variant cannot carry Agent disposition fields",
                   root_mixing_rejected))

    agent_payload = {
        "plan_id": f"WP-1-{p1[:8]}",
        "plan_digest": p1,
        "lane_ids": ["L-HUNTER", "L-REVIEWER"],
        "assignment_dispositions": [{
            "lane_id": "L-HUNTER", "assignment": "A-HUNTER", "role": "hunter",
            "runtime_state": "returned", "disposition": "merged",
            "result_digest": "a" * 64, "review_receipt_hash": "b" * 64,
        }, {
            "lane_id": "L-REVIEWER", "assignment": "A-REVIEWER", "role": "reviewer",
            "runtime_state": "returned", "disposition": "reviewed",
            "result_digest": "c" * 64, "review_receipt_hash": "d" * 64,
        }],
        "merge_disposition_summary": summary(),
        "next_action": next_action,
    }
    agent_mixing_rejected = False
    try:
        validate_typed_event_data("cycle_end", dict(
            agent_payload, root_action_receipt=root_success_receipt), cycle=1)
    except JournalContractError as exc:
        agent_mixing_rejected = exc.code == "CYCLE_EVENT_DATA_INVALID"
    checks.append(("Agent variant cannot carry a Root action receipt",
                   agent_mixing_rejected))

    missing_root_action_rejected = missing_agent_action_rejected = False
    try:
        validate_typed_event_data(
            "cycle_end",
            {key: value for key, value in root_success_payload.items()
             if key != "next_action"},
            cycle=1,
        )
    except JournalContractError as exc:
        missing_root_action_rejected = exc.code == "CYCLE_EVENT_DATA_INVALID"
    try:
        validate_typed_event_data(
            "cycle_end",
            {key: value for key, value in agent_payload.items()
             if key != "next_action"},
            cycle=1,
        )
    except JournalContractError as exc:
        missing_agent_action_rejected = exc.code == "CYCLE_EVENT_DATA_INVALID"
    checks.append(("both plan-bound cycle variants require next_action",
                   missing_root_action_rejected and missing_agent_action_rejected))
    invisible_action_rejected = False
    try:
        validate_typed_event_data(
            "cycle_end",
            dict(agent_payload, next_action=next_action + "\u200b"),
            cycle=1,
        )
    except JournalContractError as exc:
        invisible_action_rejected = exc.code == "CYCLE_EVENT_DATA_INVALID"
    checks.append(("plan-bound next_action rejects invisible text drift",
                   invisible_action_rejected))
    checks.append(("cycle producer rejects vague structured next_action",
                   validate_next_action_semantics(
                       "等待用户", active_fronts=["F-001"])
                   == "CODA_VAGUE_ACTION"))
    checks.append(("cycle producer rejects a wrong active front",
                   validate_next_action_semantics(
                       "F-999 检查其他入口", active_fronts=["F-001"])
                   == "CODA_WRONG_FRONT"))
    checks.append(("cycle producer rejects multiple executable actions",
                   validate_next_action_semantics(
                       "运行 check_run 和 peer_review", active_fronts=[])
                   == "CODA_MULTIPLE_ACTIONS"))

    root_sequence = scope("root_sequence")
    append_event(root_sequence, "cycle_start")
    append_event(root_sequence, "stage_plan", data=plan_data(p1, "S1"))
    append_event(root_sequence, "delegation_committed", data={
        "plan_digest": p1, "lane_ids": ["L-ROOT"],
    })
    with patch.object(
            sys.modules[__name__], "derive_cycle_end_data",
            return_value=root_success_payload):
        root_end = append_event(root_sequence, "cycle_end")
    checks.append(("ROOT_DIRECT cycle_end preserves the typed sequence and plan digest",
                   root_end["data"] == root_success_payload
                   and plan_cycle_ended(load_events(root_sequence), p1)))

    forged_root = scope("forged_root")
    append_event(forged_root, "cycle_start")
    append_event(forged_root, "stage_plan", data=plan_data(p1, "S1"))
    append_event(forged_root, "delegation_committed", data={
        "plan_digest": p1, "lane_ids": ["L-ROOT"],
    })
    forged_root_rejected = False
    try:
        append_event(forged_root, "cycle_end", data=root_success_payload)
    except JournalContractError as exc:
        forged_root_rejected = exc.code == "CYCLE_EVENT_CALLER_DATA_FORBIDDEN"
    checks.append(("caller cannot forge a ROOT_DIRECT cycle_end receipt",
                   forged_root_rejected))

    projected_success_receipt = dict(
        root_success_receipt, parent_run=root_sequence.name)
    projected_success_receipt["receipt_hash"] = _sha256_json({
        key: item for key, item in projected_success_receipt.items()
        if key != "receipt_hash"
    })
    projected_success_payload = dict(
        root_success_payload, root_action_receipt=projected_success_receipt)
    root_plan = {
        "execution_mode": "ROOT_DIRECT", "cycle_id": 1,
        "plan_id": f"WP-1-{p1[:8]}", "plan_digest": p1,
        "lanes": [{
            "id": "L-ROOT", "capability_id": "read.run-model",
            "effect": "local_read",
        }],
        "turn_binding": {
            "session_id": "session-root-direct", "prompt_sha256": "4" * 64,
        },
    }
    root_projection = {
        "plan_id": root_plan["plan_id"], "plan_digest": p1,
        "lane_ids": ["L-ROOT"], "debt": {"merge": [], "review": []},
        "merge_disposition_summary": {},
        "root_action_receipt": projected_success_receipt,
    }
    current_plan_calls: list[Path] = []

    def fake_current_plan(current_run: Path) -> dict:
        current_plan_calls.append(current_run)
        return root_plan

    fake_work_plan = SimpleNamespace(transaction_bound_plan=fake_current_plan)
    fake_run_model = SimpleNamespace(
        summary=lambda _run: {"open": []},
        plan_cycle_projection=lambda _run, plan: root_projection)
    with patch.dict(sys.modules, {
            "work_plan": fake_work_plan, "run_model": fake_run_model}):
        root_derived = derive_cycle_end_data(
            root_sequence, plan_digest=p1, next_action=next_action)
    checks.append(("ROOT_DIRECT cycle_end is derived only after current v2 plan validation",
                   root_derived == projected_success_payload
                   and current_plan_calls == [root_sequence.resolve()]))

    projected_failed_receipt = dict(projected_success_receipt, outcome="failed")
    projected_failed_receipt["receipt_hash"] = _sha256_json({
        key: item for key, item in projected_failed_receipt.items()
        if key != "receipt_hash"
    })
    projected_failed_payload = dict(
        root_success_payload, root_action_receipt=projected_failed_receipt)
    failed_projection = dict(
        root_projection, root_action_receipt=projected_failed_receipt)
    fake_failed_model = SimpleNamespace(
        summary=lambda _run: {"open": []},
        plan_cycle_projection=lambda _run, plan: failed_projection)
    with patch.dict(sys.modules, {
            "work_plan": fake_work_plan, "run_model": fake_failed_model}):
        failed_derived = derive_cycle_end_data(
            root_sequence, plan_digest=p1, next_action=next_action)
    checks.append(("failed ROOT_DIRECT action derives an honest failed terminal receipt",
                   failed_derived == projected_failed_payload))

    pending_projection = dict(
        root_projection,
        debt={"merge": ["L-ROOT:running"], "review": []},
        root_action_receipt=None,
    )
    fake_pending_model = SimpleNamespace(
        summary=lambda _run: {"open": []},
        plan_cycle_projection=lambda _run, plan: pending_projection)
    pending_derivation_rejected = False
    with patch.dict(sys.modules, {
            "work_plan": fake_work_plan, "run_model": fake_pending_model}):
        try:
            derive_cycle_end_data(
                root_sequence, plan_digest=p1, next_action=next_action)
        except JournalContractError as exc:
            pending_derivation_rejected = exc.code == "CYCLE_EVENT_PLAN_DEBT_OPEN"
    checks.append(("pending ROOT_DIRECT action debt blocks cycle derivation",
                   pending_derivation_rejected))

    broken_transaction_rejected = False
    broken_work_plan = SimpleNamespace(
        transaction_bound_plan=lambda _run: (_ for _ in ()).throw(
            RuntimeError("WORK_PLAN_TRANSACTION_ARCHIVE_DIVERGED")))
    with patch.dict(sys.modules, {
            "work_plan": broken_work_plan, "run_model": fake_run_model}):
        try:
            derive_cycle_end_data(
                root_sequence, plan_digest=p1, next_action=next_action)
        except JournalContractError as exc:
            broken_transaction_rejected = (
                exc.code == "CYCLE_EVENT_CURRENT_PLAN_INVALID"
                and "WORK_PLAN_TRANSACTION_ARCHIVE_DIVERGED" in exc.detail
            )
    checks.append(("broken v2 transaction/archive lineage blocks cycle derivation",
                   broken_transaction_rejected))

    planner_main_calls: list[Path] = []

    def planner_main_plan(current_run: Path) -> dict:
        planner_main_calls.append(current_run)
        return root_plan

    planner_main = SimpleNamespace(
        __file__=str(Path(__file__).resolve().with_name("work_plan.py")),
        transaction_bound_plan=planner_main_plan,
    )
    saved_work_plan = sys.modules.pop("work_plan", None)
    try:
        with patch.dict(sys.modules, {
                "__main__": planner_main, "run_model": fake_run_model}):
            main_derived = derive_cycle_end_data(
                root_sequence, plan_digest=p1, next_action=next_action)
    finally:
        if saved_work_plan is not None:
            sys.modules["work_plan"] = saved_work_plan
        else:
            sys.modules.pop("work_plan", None)
    checks.append(("cycle producer reuses work_plan running as __main__",
                   main_derived == projected_success_payload
                   and planner_main_calls == [root_sequence.resolve()]))

    legacy = scope("legacy")
    append_event(legacy, "cycle_start")
    append_event(legacy, "historical_custom_event", data={
        "free_form": "ordinary legacy data remains readable",
    })
    append_event(legacy, "cycle_end")
    masquerade_rejected = False
    try:
        validate_cycle_events([{
            "event": "stage-plan", "cycle": 1, "data": {},
        }])
    except JournalContractError as exc:
        masquerade_rejected = exc.code == "CYCLE_EVENT_NAME_INVALID"
    checks.append(("unknown ordinary historical event remains compatible",
                   summarize(legacy)["typed_contract_valid"] is True))
    checks.append(("reserved typed alias cannot masquerade as legacy", masquerade_rejected))

    legacy_prefix = scope("legacy_prefix")
    _journal_path(legacy_prefix).write_text(json.dumps({
        "cycle": 1, "event": "historical_pre_v1", "data": {"legacy": True},
    }, sort_keys=True) + "\n", encoding="utf-8")
    append_event(legacy_prefix, "cycle_start")
    checks.append(("schema-less legacy rows remain compatible only as a prefix",
                   summarize(legacy_prefix)["typed_contract_valid"] is True))

    schema_less_tail = scope("schema_less_tail")
    append_event(schema_less_tail, "cycle_start")
    with _journal_path(schema_less_tail).open("a", encoding="utf-8") as handle:
        handle.write(json.dumps({
            "cycle": 1, "event": "historical_post_v1", "data": {"legacy": True},
        }, sort_keys=True) + "\n")
    injected_tail = _journal_path(schema_less_tail).read_bytes()
    tail_rejected = False
    try:
        append_event(schema_less_tail, "action")
    except JournalContractError as exc:
        tail_rejected = exc.code == "CYCLE_EVENT_HASH_CHAIN_INVALID"
    checks.append(("schema-less JSON tail cannot split a started v1 hash chain",
                   tail_rejected
                   and _journal_path(schema_less_tail).read_bytes() == injected_tail))

    malformed_tail = scope("malformed_tail")
    append_event(malformed_tail, "cycle_start")
    with _journal_path(malformed_tail).open("a", encoding="utf-8") as handle:
        handle.write("{malformed-json\n")
    malformed_bytes = _journal_path(malformed_tail).read_bytes()
    malformed_rejected = False
    try:
        append_event(malformed_tail, "action")
    except JournalContractError as exc:
        malformed_rejected = exc.code == "CYCLE_EVENT_JOURNAL_INVALID"
    checks.append(("malformed journal tail blocks every later append",
                   malformed_rejected
                   and _journal_path(malformed_tail).read_bytes() == malformed_bytes))

    tampered_chain = scope("tampered_chain")
    append_event(tampered_chain, "cycle_start")
    append_event(tampered_chain, "historical_custom_event", data={"value": 1})
    tampered_rows = [json.loads(line) for line in _journal_path(tampered_chain).read_text(
        encoding="utf-8").splitlines()]
    tampered_rows[1]["data"]["value"] = 2
    _journal_path(tampered_chain).write_text(
        "\n".join(json.dumps(item, sort_keys=True) for item in tampered_rows) + "\n",
        encoding="utf-8")
    tampered_bytes = _journal_path(tampered_chain).read_bytes()
    tamper_rejected = False
    try:
        append_event(tampered_chain, "action")
    except JournalContractError as exc:
        tamper_rejected = exc.code == "CYCLE_EVENT_HASH_CHAIN_INVALID"
    checks.append(("ordinary v1 event mutation invalidates the journal chain",
                   tamper_rejected
                   and _journal_path(tampered_chain).read_bytes() == tampered_bytes))

    merge_schema = json.loads((ROOT / "contracts" / "merge-draft.v1.schema.json").read_text(
        encoding="utf-8"))
    review_schema = json.loads((ROOT / "contracts" / "review-disposition.v1.schema.json").read_text(
        encoding="utf-8"))
    cycle_schema = json.loads((ROOT / "contracts" / "cycle-event.v1.schema.json").read_text(
        encoding="utf-8"))
    root_receipt_schema = json.loads((
        ROOT / "contracts" / "root-action-receipt.v1.schema.json").read_text(
            encoding="utf-8"))
    expected_merge_fields = {
        "schema", "assignment", "role", "front", "assets", "effect", "plan_id",
        "plan_digest", "lane_id", "assignment_attempt", "runtime_attempt", "result",
        "result_digest", "outcome", "per_asset_outcomes", "review_status",
        "review_receipt", "updated_at",
    }
    expected_review_required_fields = {
        "schema", "target_assignment", "target_result_digest", "reviewer_assignment",
        "reviewer_agent_id", "reviewer_tool_use_id", "reviewer_result_digest",
        "plan_digest", "target_lane_id", "reviewer_lane_id", "disposition", "note",
        "recorded_at", "receipt_hash",
    }
    expected_review_fields = expected_review_required_fields | {"artifact_validation"}
    checks.append(("merge draft schema freezes exact runtime fields",
                   merge_schema.get("additionalProperties") is False
                   and set(merge_schema.get("required", [])) == expected_merge_fields
                   and set(merge_schema.get("properties", {})) == expected_merge_fields))
    checks.append(("review receipt schema freezes exact runtime fields",
                   review_schema.get("additionalProperties") is False
                   and set(review_schema.get("required", []))
                   == expected_review_required_fields
                   and set(review_schema.get("properties", {})) == expected_review_fields))
    replay_response_schema = (
        review_schema.get("properties", {})
        .get("artifact_validation", {})
        .get("items", {})
        .get("oneOf", [{}, {}])[1]
        .get("properties", {})
        .get("response", {})
    )
    legacy_response = {"status": 200, "len": 5, "sha1": "1" * 40}
    v2_response = {
        **legacy_response,
        "saved_len": 5,
        "saved_sha1": "1" * 40,
        "truncated": False,
        "wire_verified": True,
    }
    partial_response = {**legacy_response, "saved_len": 5}
    checks.append(("review response schema admits only exact legacy or complete v2",
                   not contract_schema.schema_errors(
                       legacy_response, replay_response_schema, root=review_schema)
                   and not contract_schema.schema_errors(
                       v2_response, replay_response_schema, root=review_schema)
                   and bool(contract_schema.schema_errors(
                       partial_response, replay_response_schema, root=review_schema))))
    checks.append(("typed cycle schema names only the reserved event subset",
                   cycle_schema.get("$id", "").endswith("cycle-event.v1.schema.json")
                   and set(TYPED_CYCLE_EVENTS) == {
                       "stage_plan", "replan", "stage_exit",
                       "delegation_committed", "cycle_end",
                   }))
    plan_cycle_schema = cycle_schema.get("$defs", {}).get("planCycleEndData", {})
    expected_plan_cycle_fields = {
        "plan_id", "plan_digest", "lane_ids", "assignment_dispositions",
        "merge_disposition_summary", "next_action",
    }
    checks.append(("Agent cycle schema requires the exact next-action field",
                   plan_cycle_schema.get("additionalProperties") is False
                   and set(plan_cycle_schema.get("required", []))
                   == expected_plan_cycle_fields
                   and set(plan_cycle_schema.get("properties", {}))
                   == expected_plan_cycle_fields))
    root_cycle_schema = cycle_schema.get("$defs", {}).get("rootDirectCycleEndData", {})
    expected_root_cycle_fields = {
        "plan_id", "plan_digest", "execution_mode", "lane_ids",
        "root_action_receipt", "next_action",
    }
    checks.append(("ROOT_DIRECT cycle schema is an exact independent variant",
                   root_cycle_schema.get("additionalProperties") is False
                   and set(root_cycle_schema.get("required", []))
                   == expected_root_cycle_fields
                   and set(root_cycle_schema.get("properties", {}))
                   == expected_root_cycle_fields
                   and root_cycle_schema.get("properties", {}).get(
                       "execution_mode", {}).get("const") == "ROOT_DIRECT"
                   and root_cycle_schema.get("properties", {}).get(
                       "lane_ids", {}).get("minItems") == 1
                   and root_cycle_schema.get("properties", {}).get(
                       "lane_ids", {}).get("maxItems") == 1))
    checks.append(("Root action receipt schema and semantic validator freeze the same fields",
                   root_receipt_schema.get("additionalProperties") is False
                   and set(root_receipt_schema.get("required", []))
                   == _ROOT_ACTION_RECEIPT_KEYS
                   and set(root_receipt_schema.get("properties", {}))
                   == _ROOT_ACTION_RECEIPT_KEYS))
    bad = [n for n, ok in checks if not ok]
    for n, ok in checks:
        print(("ok   " if ok else "FAIL ") + n)
    print("loop_journal selftest " + ("passed" if not bad else f"FAILED ({len(bad)})"))
    return 0 if not bad else 1


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="append/read Xunji loop interruption journal")
    ap.add_argument("run_dir", nargs="?")
    ap.add_argument("event", nargs="?", choices=[
        "start", "plan", "action", "write-result", "interrupt", "resume", "end", "status",
        "phase-start", "phase-end",
    ])
    ap.add_argument("--phase", default="", help="phase name for phase-start / phase-end")
    ap.add_argument("--note", default="")
    ap.add_argument(
        "--next-action", default="",
        help="exact final Coda action for a plan-bound end",
    )
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--selftest", action="store_true")
    args = ap.parse_args(argv)

    if args.selftest:
        return _selftest()
    if not args.run_dir or not args.event:
        ap.error("run_dir and event are required")

    event_map = {
        "start": "cycle_start",
        "write-result": "write_result",
        "end": "cycle_end",
        "phase-start": "phase_start",
        "phase-end": "phase_end",
    }
    if args.event == "status":
        data = summarize(args.run_dir)
    else:
        event = event_map.get(args.event, args.event)
        if event in PHASE_EVENTS and not args.phase.strip():
            ap.error("--phase is required for phase-start / phase-end")
        if args.next_action and event != "cycle_end":
            ap.error("--next-action is accepted only for end")
        payload = {"phase": args.phase.strip()} if event in PHASE_EVENTS else {}
        try:
            rec = append_event(
                args.run_dir,
                event,
                note=args.note,
                data=payload,
                next_action=args.next_action,
            )
        except (OSError, ValueError) as e:
            print(f"[loop_journal] {e}", file=sys.stderr)
            return 1
        data = {"appended": rec, "status": summarize(args.run_dir)}
    if args.json:
        print(json.dumps(data, ensure_ascii=False, indent=2))
    else:
        color = status_style.color_enabled()
        rec = data.get("appended") if isinstance(data, dict) else None
        if isinstance(rec, dict) and rec.get("event") in PHASE_EVENTS:
            print(render_phase_banner(rec, color=color), end="")
        print(render_markdown(data.get("status", data), color=color), end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
