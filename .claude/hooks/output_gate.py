#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Stop hook: output drift gate — 检测 Driver 响应中的漂移信号并写 session_state。

检测到漂移话术(是否继续/要不要继续/你决定等)、结尾问号、编号选项列表、frontier 过期 →
写 session_state.json (漂移状态)。run_gate.py 在同一 Stop 事件中读取并执行提醒(Phase 3 notify)。
anti_drift.py 在下一轮 UserPromptSubmit 注入重读指令。

漂移检测逻辑自身 FAIL-OPEN (解析失败不抛异常)。漂移状态写入 session_state，
不再使用独立 drift_block.json 文件(Decision 2)。

本 gate 负责检测+写状态; run_gate 负责 Phase 3 提醒; anti_drift 负责注入重读指令。
与 safety_gate.py 的区别: safety_gate 防不可逆危害; 本 gate 防过程漂移。

Protocol: read Stop event from stdin; detect drift → write session_state.json; exit 0.
Usage:
    python3 .claude/hooks/output_gate.py            # Stop hook target
    python3 .claude/hooks/output_gate.py --selftest  # offline regression
"""
from __future__ import annotations

import json
import os
import re
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
RUNS = Path(os.environ.get("XUNJI_RUNS_ROOT", str(ROOT / "runs")))
SESSION_STATE_STALE_SEC = 50 * 60  # session timeout 50 min
INVISIBLE_RE = re.compile(r"[​‌‍⁠﻿ ]")
CODA_RE = re.compile(
    r"(?im)^[^\S\n]*(下一行动|BLOCKED)[^\S\n]*[:：][^\S\n]*(.*?)[^\S\n]*$"
)
NORMAL_CODA = "NORMAL_CODA"
TARGET_DENIED = "TARGET_DENIED"
STOP_OUTPUT_TYPES = frozenset({NORMAL_CODA, TARGET_DENIED})
STOP_OUTPUT_SCHEMA = "xunji.stop-output.v1"
STOP_RECORD_FIELDS = {
    NORMAL_CODA: frozenset({"schema", "type", "coda_kind", "next_action"}),
    TARGET_DENIED: frozenset({
        "schema", "type", "error", "recovery", "executed", "next_action",
    }),
}

RECOVERY_SAME_TURN_RETRY = "SAME_TURN_RETRY"
RECOVERY_SAME_TURN_ALTERNATIVE = "SAME_TURN_ALTERNATIVE"
RECOVERY_NEW_OPERATOR_AUTHORITY = "NEW_OPERATOR_AUTHORITY"
RECOVERY_HARD_SAFETY_DENIAL = "HARD_SAFETY_DENIAL"
RECOVERY_TYPES = frozenset({
    RECOVERY_SAME_TURN_RETRY,
    RECOVERY_SAME_TURN_ALTERNATIVE,
    RECOVERY_NEW_OPERATOR_AUTHORITY,
    RECOVERY_HARD_SAFETY_DENIAL,
})

E_TARGET_ACTION_DENIED = "XUNJI_E_TARGET_ACTION_DENIED"
_STABLE_ERROR_RE = re.compile(r"\A[A-Z][A-Z0-9_]{2,127}\Z")
_RESERVED_STOP_MARKER_RE = re.compile(
    r"(?m)^(?:XUNJI_EXECUTION_STATUS=(?:DENIED|BLOCKED)|"
    r"XUNJI_MAINTENANCE_STATUS=BLOCKED|XUNJI_STOP_TYPE=)"
)
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
sys.path.insert(0, str(ROOT / "tools"))

try:
    from anti_drift import (
        DRIFT_PATTERNS, find_active_run, is_normal_mode,
        _valid_ts, SessionStateManager, get_mode,
        semantic_freshness, semantic_trajectory, record_reason_pass,
    )
except Exception:
    DRIFT_PATTERNS = [
        "是否继续", "要不要继续", "还是等其他条件", "请指示下一步",
        "需要我继续", "等待用户", "你决定", "需要继续吗",
        "I can continue if", "Should I continue", "wait for",
    ]

    def find_active_run(*args, **kwargs):
        return None

    def is_normal_mode() -> bool:
        return True

    def get_mode() -> str:
        return "normal"

    def semantic_freshness(run_dir) -> dict:
        return {
            "status": "invalid",
            "remind": True,
            "changed_fields": [],
            "reason": "semantic anti-drift implementation unavailable",
        }

    def semantic_trajectory(run_dir) -> dict:
        return {
            "status": "invalid",
            "no_progress_cycles": 0,
            "trajectory_review_due": False,
            "reason": "semantic anti-drift implementation unavailable",
        }

    def record_reason_pass(*args, **kwargs):
        raise RuntimeError("semantic anti-drift implementation unavailable")

    def _valid_ts(value, now: float) -> float:
        try:
            ts = float(value)
        except Exception:
            return 0.0
        if ts < 0 or ts > now + 60:
            return 0.0
        return ts

    class SessionStateManager:
        @staticmethod
        def load(run_dir):
            return {}
        @staticmethod
        def save(run_dir, state):
            pass
        @staticmethod
        def get_drift_flags(run_dir):
            return []
        @staticmethod
        def reset_if_stale(run_dir, hard_block_active=False):
            return {}

try:
    import loop_state as _loop_state
except Exception:
    _loop_state = None
try:
    import turn_contract as _turn_contract
except Exception:
    _turn_contract = None
try:
    import runtime_receipts as _runtime_receipts
except Exception:
    _runtime_receipts = None
try:
    import loop_journal as _loop_journal
except Exception:
    _loop_journal = None
try:
    import work_plan as _work_plan
except Exception:
    _work_plan = None
try:
    import completion_transaction as _completion_transaction
except Exception:
    _completion_transaction = None


def _active_run_declared(pointer: Path | None = None) -> bool:
    """Conservatively detect an operator-selected run if lookup itself failed."""
    marker = pointer or Path(os.environ.get(
        "XUNJI_ACTIVE_RUN_FILE", str(ROOT / ".claude" / "xunji_active_run")))
    try:
        return marker.is_file() and bool(marker.read_text(
            encoding="utf-8", errors="replace").strip())
    except Exception:
        return marker.exists()


def _stable_receipt_error(receipt: dict, fallback: str) -> str:
    code = str(receipt.get("decision_code") or "").strip()
    return code if _STABLE_ERROR_RE.fullmatch(code) else fallback


def _validate_stop_record(record: object) -> list[str]:
    """Stdlib semantic mirror of ``contracts/stop-output.v1.schema.json``."""
    if not isinstance(record, dict):
        return ["record must be an object"]
    kind = str(record.get("type") or "")
    required = STOP_RECORD_FIELDS.get(kind)
    if required is None:
        return ["unknown Stop output type"]
    errors: list[str] = []
    if set(record) != required:
        errors.append("record fields do not match the exclusive variant")
    if record.get("schema") != STOP_OUTPUT_SCHEMA:
        errors.append("wrong Stop output schema")
    next_action = record.get("next_action")
    if not isinstance(next_action, str) or not (4 <= len(next_action) <= 2048):
        errors.append("next_action length is invalid")
    if kind == NORMAL_CODA:
        if record.get("coda_kind") not in {"NEXT_ACTION", "BLOCKED"}:
            errors.append("unknown Coda kind")
        return errors
    if not isinstance(record.get("error"), str) or not _STABLE_ERROR_RE.fullmatch(
            str(record.get("error") or "")):
        errors.append("error code is not stable")
    if record.get("recovery") not in RECOVERY_TYPES:
        errors.append("unknown recovery semantics")
    if kind == TARGET_DENIED:
        if record.get("executed") is not False:
            errors.append("TARGET_DENIED must declare executed=false")
        return errors
    return errors


def _recovery_semantics(receipt: dict, *, maintenance_blocked: bool) -> str:
    """Map trusted receipt metadata to a finite, machine-checkable recovery class."""
    hook = str(receipt.get("hook_event_name") or "")
    decision_class = str(receipt.get("decision_class") or "").strip().lower()
    code = str(receipt.get("decision_code") or "").strip().upper()
    if hook == "PostToolUseFailure":
        return RECOVERY_SAME_TURN_RETRY
    if receipt.get("retryable_same_turn") is True or decision_class == "command_shape":
        return RECOVERY_SAME_TURN_ALTERNATIVE
    if decision_class in {"safety", "privacy", "scope"} or any(
            token in code for token in ("SAFETY", "PRIVACY", "OUT_OF_SCOPE")):
        return RECOVERY_HARD_SAFETY_DENIAL
    if decision_class == "authority" or (maintenance_blocked and hook == "PreToolUseDenied"):
        return RECOVERY_NEW_OPERATOR_AUTHORITY
    return RECOVERY_SAME_TURN_RETRY


def _target_anchor(denied: list[dict], run_dir: Path | None) -> str:
    active = _active_protocol_fronts(run_dir) if run_dir is not None else []
    if active:
        return active[0]
    latest = denied[-1] if denied else {}
    front = str(latest.get("front") or "").upper()
    return front if re.fullmatch(r"F-\d+", front) else "frontier.md"


def _target_denied_record(
    denied: list[dict],
    run_dir: Path | None = None,
) -> dict:
    latest = denied[-1] if denied else {}
    recovery = _recovery_semantics(latest, maintenance_blocked=False)
    code = _stable_receipt_error(latest, E_TARGET_ACTION_DENIED)
    anchor = _target_anchor(denied, run_dir)
    if recovery == RECOVERY_SAME_TURN_ALTERNATIVE:
        action = (
            f"{anchor} 按 XUNJI_ERROR 修正命令形状后在当前回合重试同一目标动作"
        )
    elif recovery == RECOVERY_NEW_OPERATOR_AUTHORITY:
        action = (
            f"{anchor} 在新 operator prompt 取得所需授权后重试同一目标动作"
        )
    elif recovery == RECOVERY_HARD_SAFETY_DENIAL:
        action = f"{anchor} 切换到不违反硬安全边界的替代动作"
    else:
        action = f"{anchor} 完成前置条件后在当前回合重试同一目标动作"
    record = {
        "schema": STOP_OUTPUT_SCHEMA,
        "type": TARGET_DENIED,
        "error": code,
        "recovery": recovery,
        "executed": False,
        "next_action": action,
    }
    errors = _validate_stop_record(record)
    if errors:
        raise RuntimeError("invalid TARGET_DENIED contract: " + "; ".join(errors))
    return record


def _target_denied_text(
    denied: list[dict],
    run_dir: Path | None = None,
) -> str:
    record = _target_denied_record(denied, run_dir)
    return (
        "XUNJI_EXECUTION_STATUS=DENIED\n"
        f"XUNJI_STOP_TYPE={TARGET_DENIED}\n"
        f"XUNJI_ERROR={record['error']}\n"
        f"XUNJI_RECOVERY={record['recovery']}\n"
        "未执行目标动作；不存在该动作的实测结果。\n"
        f"下一行动: {record['next_action']}"
    )


def _denied_result_claim_reason(
    msg: str,
    denied: list[dict],
    run_dir: Path | None = None,
) -> str:
    if not denied:
        return ""
    clean = _strip_invisible(msg).strip()
    expected = _target_denied_text(denied, run_dir)
    if clean == expected:
        return ""
    return (
        "[未执行动作真实性硬拦] 本回合仍有未被同工具、同执行动作成功回执消解的"
        " PreToolUse 目标动作拒绝。禁止自由文本和任何结果转述；继续完成前置条件并"
        "重试原动作，或仅输出以下 fixed envelope：\n" + expected
    )


_MAINTENANCE_SUCCESS_CLAIM_RE = re.compile(
    r"(?<!未)(?:已|已经|成功).{0,24}(?:修复|修改|还原|完成|写入|提交|通过)|"
    r"\b(?:fixed|modified|reverted|completed|succeeded|passed)\b",
    re.I,
)
_NEGATED_ENGLISH_MAINTENANCE_RE = re.compile(
    r"\b(?:not|never)\s+(?:fixed|modified|reverted|completed|succeeded|passed)\b|"
    r"\b(?:did\s+not|didn't|failed\s+to)\s+"
    r"(?:fix|modify|revert|complete|succeed|pass)\b",
    re.I,
)


def _maintenance_truth_claim_reason(msg: str, blocked: list[dict]) -> str:
    """Reject only unsupported success claims, never freeze honest progress."""
    clean = _strip_invisible(msg).strip()
    claim_text = _NEGATED_ENGLISH_MAINTENANCE_RE.sub("", clean)
    if not blocked or not _MAINTENANCE_SUCCESS_CLAIM_RE.search(claim_text):
        return ""
    latest = blocked[-1] if blocked else {}
    paths = sorted({
        str(path) for path in (latest.get("maintenance_paths") or [])
        if str(path).strip()
    })
    scope = ", ".join(paths) if paths else "the denied maintenance effect"
    return (
        "[未执行维护真实性硬拦] 尚无成功回执的维护拒绝/失败不能被描述为已修复、"
        f"已修改或已完成（effect={scope}）。请如实说明失败，或修正 typed path/argv 后"
        "在当前维护回合重试；不需要新的维护授权仪式。"
    )


def _stop_output_union(
    msg: str,
    denied: list[dict],
    blocked: list[dict],
    run_dir: Path | None = None,
) -> tuple[str, str]:
    """Return the exclusive Stop output variant and any validation error.

    Maintenance receipts only challenge unsupported success prose. Target denials
    retain the sole fixed terminal envelope.
    """
    clean = _strip_invisible(msg or "").strip()
    maintenance_error = _maintenance_truth_claim_reason(msg, blocked)
    if maintenance_error:
        return NORMAL_CODA, maintenance_error
    if denied:
        return TARGET_DENIED, _denied_result_claim_reason(msg, denied, run_dir)
    if _RESERVED_STOP_MARKER_RE.search(clean):
        return NORMAL_CODA, (
            "[STOP_ENVELOPE_UNAUTHORIZED] fixed Stop envelope requires a matching "
            "unresolved trusted runtime receipt in this prompt/session"
        )
    return NORMAL_CODA, ""


def validated_fixed_stop_kind(
    msg: str,
    run_dir: Path,
    *,
    session_id: str = "",
    since: float = 0.0,
) -> str:
    """Read-only validator shared by the later Stop hook.

    The caller may bypass ordinary process/Coda gates only when the exact fixed
    envelope is backed by an unresolved receipt in this prompt/session.
    """
    if _runtime_receipts is None:
        return ""
    try:
        blocked = _runtime_receipts.unresolved_maintenance_blockers(
            run_dir, session_id=session_id, since=since)
        denied = _runtime_receipts.unresolved_target_denials(
            run_dir, session_id=session_id, since=since)
    except Exception:
        return ""
    kind, error = _stop_output_union(msg, denied, blocked, run_dir)
    return kind if kind == TARGET_DENIED and not error else ""


def _emit_gate_violation(reason: str, *, stop_hook_active: bool) -> None:
    """Block once; Claude Code Stop retries are advisory to avoid hook churn."""
    if stop_hook_active:
        print(json.dumps({
            "systemMessage": "[Stop 重入放行，canonical run 状态仍未满足] " + reason,
        }, ensure_ascii=False))
        return
    print(json.dumps({"decision": "block", "reason": reason}, ensure_ascii=False))


def _strip_invisible(s: str) -> str:
    """Remove zero-width and invisible characters from string."""
    return INVISIBLE_RE.sub("", s)


def detect_drift(msg: str) -> list[str]:
    """Return list of drift patterns found in message."""
    if not msg or not isinstance(msg, str):
        return []
    msg = _strip_invisible(msg)
    return [p for p in DRIFT_PATTERNS if re.search(re.escape(p), msg, re.IGNORECASE)]


def _tail_has_question(msg: str) -> bool:
    """Check if the tail (last 300 chars) contains a question mark or Chinese question particle."""
    if not msg:
        return False
    tail = _strip_invisible(msg[-300:] if len(msg) > 300 else msg).rstrip()
    return bool(re.search(r'[?？]|[吗呢吧啊][\s。！,，]*$', tail))


def _coda_error(code: str, predicate: str) -> str:
    return f"[{code}] {predicate}"


def _normal_coda_record(kind: str, detail: str) -> dict:
    record = {
        "schema": STOP_OUTPUT_SCHEMA,
        "type": NORMAL_CODA,
        "coda_kind": "BLOCKED" if kind == "BLOCKED" else "NEXT_ACTION",
        "next_action": detail,
    }
    errors = _validate_stop_record(record)
    if errors:
        raise RuntimeError("invalid NORMAL_CODA contract: " + "; ".join(errors))
    return record


def _turn_coda(msg: str) -> tuple[str, str, str]:
    """Return ``(kind, detail, stable_error)`` for one concrete final Coda line."""
    clean = _strip_invisible(msg or "").rstrip()
    if _RESERVED_STOP_MARKER_RE.search(clean):
        return "", "", _coda_error(
            "STOP_ENVELOPE_UNAUTHORIZED",
            "fixed Stop envelope requires a matching current receipt",
        )
    matches = list(CODA_RE.finditer(clean))
    if not matches:
        return "", "", _coda_error(
            "CODA_MISSING", "最后一个非空行必须是唯一的 `下一行动:` Coda")
    if len(matches) != 1:
        return "", "", _coda_error(
            "CODA_MULTIPLE", "全文只能出现一个回合 Coda")
    match = matches[0]
    if match.end() != len(clean):
        trailing = clean[match.end():]
        if re.fullmatch(r"\s*`{3,}[^\n]*", trailing):
            return "", "", _coda_error(
                "CODA_TRAILING_FENCE", "Coda 后不得保留 Markdown closing fence")
        return "", "", _coda_error(
            "CODA_NOT_LAST", "Coda 必须是最后一个非空行")
    kind = match.group(1).upper()
    detail = match.group(2).strip()
    compact = re.sub(r"[\s`*_#<>。，、:：;；,.!?！？()（）\[\]-]", "", detail)
    if len(compact) < 4 or re.search(r"<[^>]*>|\b(?:TODO|TBD)\b", detail, re.I):
        return "", "", _coda_error(
            "CODA_INVALID_DETAIL", "Coda 内容不得为空、过短或含占位符")
    vague = re.sub(r"[\s。！!，,；;]", "", detail).lower()
    vague_only = {
        "继续", "继续分析", "继续测试", "继续验证", "继续推进", "按流程继续",
        "处理问题", "执行下一步", "等待", "等待用户", "later", "continue",
    }
    if vague in vague_only:
        return "", "", _coda_error(
            "CODA_VAGUE_ACTION", "Coda 必须写清一个对象和一个动作")
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
        return "", "", _coda_error(
            "CODA_VAGUE_ACTION", "泛泛继续的改写仍缺一个具体对象和动作")
    if len(set(re.findall(r"\bF-\d+\b", detail, re.I))) > 1:
        return "", "", _coda_error(
            "CODA_MULTIPLE_FRONTS", "Coda 只能推进一个 F-id")
    if kind != "BLOCKED" and not (_ACTION_RE.search(detail) or _TOOL_RE.search(detail)):
        return "", "", _coda_error(
            "CODA_ACTION_REQUIRED", "下一行动必须包含一个明确可执行动作")
    if _has_multiple_action_clauses(detail):
        return "", "", _coda_error(
            "CODA_MULTIPLE_ACTIONS", "Coda 恰好只能包含一个可执行动作谓词")
    return kind, detail, ""


def _has_multiple_action_clauses(detail: str) -> bool:
    """Distinguish multiple executable clauses from one action with many parameters."""
    parts = re.split(
        r"(?:&&|\s+\+\s+|[，,；;、]|\s+/\s+|以及|并且|然后|随后|再去|接着|同时|"
        rf"和|与|及|或|并(?=(?:{_ACTION_WORDS_ZH})|\b(?:{_ACTION_WORDS_EN})\b)|"
        r"\b(?:and\s+then|and|or)\b)",
        detail,
        flags=re.I,
    )
    actionable = [part for part in parts if _ACTION_RE.search(part) or _TOOL_RE.search(part)]
    return len(actionable) > 1


def _tail_has_proper_close(msg: str) -> bool:
    """Whether the message has exactly one concrete final Coda line."""
    return not _turn_coda(msg)[2]


def detect_option_list(msg: str) -> bool:
    """Detect >=2 numbered option lines (e.g. '1. xxx' / '2) xxx' / '3、xxx') — autonomy decay signal."""
    if not msg:
        return False
    lines = msg.splitlines()
    option_lines = [l for l in lines if re.match(r'^\d+[\.\)、]\s*', _strip_invisible(l).strip())]
    return len(option_lines) >= 2


def _next_drift_count(prev_state: dict, drift_flags: list[str]) -> int:
    """Consecutive drift counter: any drift increments; clean output resets to zero."""
    if not drift_flags:
        return 0
    try:
        prev_count = int(prev_state.get("drift_block_count", 0) or 0)
    except Exception:
        prev_count = 0
    return prev_count + 1


def _next_drift_started_at(prev_state: dict, drift_flags: list[str], now: float) -> float:
    """Timestamp when the current consecutive drift streak began; zero when clean."""
    if not drift_flags:
        return 0.0
    prev_flags = prev_state.get("drift_flags", [])
    if isinstance(prev_flags, list) and prev_flags:
        started = _valid_ts(prev_state.get("drift_started_at"), now)
        if started:
            return started
    return now


def _semantic_reason_pass_state(run_dir: Path) -> tuple[dict, dict, list[str]]:
    """Return content-bound Reason-pass status and advisory flags.

    This deliberately has no age, mtime, or read-then-edit fallback.  Semantic
    freshness comes only from the hash-chained v1 receipt contract.
    """
    freshness = semantic_freshness(run_dir)
    trajectory = semantic_trajectory(run_dir)
    if not isinstance(freshness, dict):
        freshness = {
            "status": "invalid",
            "remind": True,
            "changed_fields": [],
            "reason": "semantic_freshness returned a non-object",
        }
    if not isinstance(trajectory, dict):
        trajectory = {
            "status": "invalid",
            "no_progress_cycles": 0,
            "trajectory_review_due": False,
            "reason": "semantic_trajectory returned a non-object",
        }
    flags: list[str] = []
    # A legacy run with no baseline is migrated by anti_drift's next-prompt
    # anchor.  Stop-time drift is emitted only for a proven content transition
    # (or an invalid receipt chain), never merely because a file is old.
    if freshness.get("remind") is True and freshness.get("status") in {
            "changed_unadjudicated", "invalid"}:
        flags.append("reason_pass_due")
    if trajectory.get("trajectory_review_due") is True:
        flags.append("trajectory_review_due")
    return freshness, trajectory, flags


def _fallback_protocol_state(run_dir: Path, error: str = "") -> dict:
    """Keep the Coda gate alive when the richer loop-state projection fails."""
    active: set[str] = set()
    blocked_a: set[str] = set()
    try:
        text = (run_dir / "frontier.md").read_text(encoding="utf-8", errors="replace")
        for match in re.finditer(
            r"(?ms)^#{2,6}[ \t]+[^\n]*?\b(F-\d+)\b.*?(?=^#{2,6}[ \t]+[^\n]*?\bF-\d+\b|\Z)",
            text,
        ):
            block = match.group(0)
            status_match = re.search(r"(?im)^\s*[-*]?\s*Status\s*[:：]\s*([^\n]+)", block)
            status = status_match.group(1).lower().replace("-", "_") if status_match else ""
            primary = re.split(r"[,;；(（]", status, maxsplit=1)[0]
            tokens = set(re.findall(r"[a-z0-9_]+", primary))
            if tokens & {"open", "probing", "working", "blocked_type_a"}:
                active.add(match.group(1))
            if "blocked_type_a" in tokens:
                blocked_a.add(match.group(1))
    except Exception:
        pass
    loop_complete = False
    if _completion_transaction is not None:
        try:
            loop_complete = bool(
                _completion_transaction.is_valid_committed(run_dir))
        except Exception:
            loop_complete = False
    return {
        "active_fronts": sorted(active),
        "blocked_type_a": sorted(blocked_a),
        "loop_complete": loop_complete,
        "next_actions": [
            "Repair/read canonical frontier state, then continue the active run"
            + (f" ({error})" if error else "")
        ],
        "fallback": True,
    }


def _protocol_state(run_dir: Path) -> dict:
    """Return the read-only run state needed for output protocol enforcement.

    This is read-only. If derived state is unavailable, fall back to canonical
    Markdown parsing so the Coda contract remains enforceable without pretending
    the process hook is a safety boundary.
    """
    if _loop_state is None:
        return _fallback_protocol_state(run_dir, "loop_state import unavailable")
    try:
        data = _loop_state.derive(run_dir, write=False)
    except Exception as exc:
        return _fallback_protocol_state(run_dir, exc.__class__.__name__)
    fronts = data.get("fronts") if isinstance(data.get("fronts"), dict) else {}
    active = {str(x) for x in (fronts.get("open") or []) if str(x).strip()}
    blocked_a = {str(x) for x in (fronts.get("blocked_type_a") or []) if str(x).strip()}
    gates = data.get("gates") if isinstance(data.get("gates"), dict) else {}
    return {
        "active_fronts": sorted(active),
        "blocked_type_a": sorted(blocked_a),
        "loop_complete": bool(gates.get("loop_complete")),
        "next_actions": [str(x) for x in (data.get("next_actions") or []) if str(x).strip()],
    }


def _active_protocol_fronts(run_dir: Path) -> list[str]:
    """Cross-check derived state with canonical Markdown before choosing an anchor."""
    derived = {str(x) for x in (_protocol_state(run_dir).get("active_fronts") or [])
               if str(x).strip()}
    canonical = {str(x) for x in (
        _fallback_protocol_state(run_dir, "canonical cross-check").get("active_fronts") or [])
                 if str(x).strip()}
    return sorted(derived | canonical)


def _structured_cycle_next_action(run_dir: Path) -> tuple[str, str, bool, bool]:
    """Return the newest validated plan-bound cycle action.

    ``(action, error, present, active_unended)`` keeps an invalid structured
    receipt distinct from an absent one.  ``active_unended`` enters the normal
    Coda parser but prevents a stale completion marker from bypassing that Coda.
    """
    journal_path = run_dir / "state" / "loop_journal.jsonl"
    if _loop_journal is None:
        if journal_path.exists():
            return "", _coda_error(
                "CODA_STRUCTURED_RECEIPT_UNAVAILABLE",
                "无法验证已存在的结构化 cycle_end receipt",
            ), True, False
        return "", "", False, False
    try:
        events = _loop_journal.load_events(run_dir)
    except Exception:
        return "", _coda_error(
            "CODA_STRUCTURED_RECEIPT_UNREADABLE",
            "无法读取结构化 cycle_end receipt",
        ), True, False
    # Validate the complete typed chain before filtering for a well-shaped
    # receipt.  Filtering first would make a corrupted plan-bound cycle_end
    # (for example one missing plan_digest) look identical to genuine absence
    # and incorrectly re-enable the compatibility/free-text Coda path.
    has_cycle_contract = any(
        isinstance(item, dict) and (
            bool(item.get("_journal_load_error"))
            or str(item.get("event") or "") == "cycle_end"
            or str(item.get("event") or "").strip().lower().replace("-", "_")
            in getattr(_loop_journal, "TYPED_CYCLE_EVENTS", frozenset())
        )
        for item in events
    )
    if has_cycle_contract:
        try:
            typed_state = _loop_journal.validate_cycle_events(events)
        except Exception as exc:
            code = str(getattr(exc, "code", "") or "")
            detail = f" ({code})" if _STABLE_ERROR_RE.fullmatch(code) else ""
            return "", _coda_error(
                "CODA_STRUCTURED_RECEIPT_INVALID",
                "结构化 cycle_end journal 未通过验证" + detail,
            ), True, False
    else:
        typed_state = {}
    candidates = [
        item for item in events
        if isinstance(item, dict)
        and item.get("event") == "cycle_end"
        and isinstance(item.get("data"), dict)
        and item["data"].get("plan_id")
        and item["data"].get("plan_digest")
    ]
    active_digest = str(typed_state.get("active_plan_digest") or "")
    if not candidates and not active_digest:
        return "", "", False, False
    if _work_plan is None:
        return "", _coda_error(
            "CODA_STRUCTURED_PROVENANCE_UNAVAILABLE",
            "无法验证 structured cycle_end 的 committed v2 transaction lineage",
        ), True, False
    try:
        plan = _work_plan.transaction_bound_plan(run_dir)
    except Exception as exc:
        detail = str(exc).splitlines()[0][:160] or exc.__class__.__name__
        return "", _coda_error(
            "CODA_STRUCTURED_PROVENANCE_INVALID",
            "structured cycle_end 缺少有效 committed v2 transaction/archive/lineage"
            f" ({detail})",
        ), True, False
    plan_digest = str(plan.get("plan_digest") or "")
    if not active_digest or active_digest != plan_digest:
        return "", _coda_error(
            "CODA_STRUCTURED_PLAN_DIVERGED",
            "structured journal active plan 与 committed v2 transaction 不一致",
        ), True, False
    ended = {
        str(item) for item in typed_state.get("ended_plan_digests", [])
        if str(item)
    }
    if active_digest not in ended:
        # A prior cycle's receipt is historical.  Once a newer plan is active,
        # it must not freeze the current turn's final Coda.
        return "", "", False, True
    current = [
        item for item in candidates
        if str(item.get("data", {}).get("plan_digest") or "") == active_digest
    ]
    if len(current) != 1:
        return "", _coda_error(
            "CODA_STRUCTURED_RECEIPT_INVALID",
            "current committed plan 必须恰好对应一个 structured cycle_end",
        ), True, False
    data = current[0]["data"]
    action = data.get("next_action")
    if not isinstance(action, str) or not action.strip() or action != action.strip():
        return "", _coda_error(
            "CODA_STRUCTURED_RECEIPT_INVALID",
            "结构化 cycle_end 缺少规范 next_action",
        ), True, False
    return action, "", True, False


def _structured_projection_error(msg: str, expected: str) -> str:
    """Validate only the exact final-line projection of trusted structured data."""
    clean = (msg or "").rstrip()
    if _RESERVED_STOP_MARKER_RE.search(clean):
        return _coda_error(
            "STOP_ENVELOPE_UNAUTHORIZED",
            "fixed Stop envelope requires a matching current receipt",
        )
    matches = list(CODA_RE.finditer(clean))
    if not matches:
        return _coda_error(
            "CODA_STRUCTURED_PROJECTION_MISSING",
            "必须投影结构化 cycle_end.next_action",
        )
    if len(matches) != 1:
        return _coda_error(
            "CODA_STRUCTURED_PROJECTION_MULTIPLE",
            "结构化 next_action 只能投影一次",
        )
    match = matches[0]
    if match.end() != len(clean):
        return _coda_error(
            "CODA_STRUCTURED_PROJECTION_NOT_LAST",
            "结构化 next_action 投影必须是最后一个非空行",
        )
    if match.group(1).upper() != "下一行动":
        return _coda_error(
            "CODA_STRUCTURED_PROJECTION_KIND",
            "结构化 next_action 只能使用 `下一行动:` 投影",
        )
    actual = match.group(2).strip()
    if actual != expected:
        return _coda_error(
            "CODA_STRUCTURED_PROJECTION_MISMATCH",
            "文本 `下一行动:` 必须与最新 validated cycle_end.next_action 完全一致",
        )
    _kind, _detail, semantic_error = _turn_coda(clean)
    if semantic_error:
        return semantic_error
    return ""


def _action_context_error(detail: str, active: list[str]) -> str:
    """Apply the same active-front/control-anchor rules to any Coda source."""
    cited_fronts = {
        item.upper() for item in re.findall(r"\bF-\d+\b", detail, re.I)
    }
    active_fronts = {str(item).upper() for item in active if str(item).strip()}
    if active_fronts and cited_fronts and not (cited_fronts & active_fronts):
        return _coda_error(
            "CODA_WRONG_FRONT", "Coda 引用的 F-id 必须属于当前 active 前沿")
    if not active_fronts and cited_fronts:
        return _coda_error(
            "CODA_WRONG_FRONT", "当前没有 active 前沿，不得引用活动 F-id")
    process_anchor = re.search(
        r"(?:check_run|classify_hosts|workers\.py|coverage_matrix\.py|frontier\.md|"
        r"evidence\.md|report\.md|decisions\.md|retrospective\.md|hints\.md|"
        r"surface\.md|conflicts?|冲突|子任务|subagent|Agent Board|分派|复审|"
        r"peer_review|收口|覆盖台账)",
        detail,
        re.I,
    )
    if active_fronts and not cited_fronts and not process_anchor:
        return _coda_error(
            "CODA_FRONT_REQUIRED",
            "存在 active 前沿时必须引用一个 active F-id 或明确的控制面对象",
        )
    if not active_fronts and not cited_fronts and not process_anchor:
        return _coda_error(
            "CODA_CONTROL_OBJECT_REQUIRED",
            "当前无 active 前沿，下一行动必须指向明确的收口或控制面对象",
        )
    return ""


def _protocol_block_reason(msg: str, run_dir: Path) -> str:
    state = _protocol_state(run_dir)
    if not state:
        return (
            "[输出协议硬拦] 无法解析 active run 状态；先修复/读取 frontier.md，"
            "并以唯一具体的 `下一行动:` 结尾。"
        )
    active = list(state.get("active_fronts") or [])
    structured_action, structured_error, structured_present, structured_active = (
        _structured_cycle_next_action(run_dir)
    )
    detail = ""
    if structured_present:
        coda_error = structured_error or _structured_projection_error(
            msg, structured_action)
        if not coda_error:
            coda_error = _action_context_error(structured_action, active)
    else:
        if state.get("loop_complete") and not structured_active:
            return ""
        kind, detail, coda_error = _turn_coda(msg)
        if not coda_error:
            try:
                _normal_coda_record(kind, detail)
            except Exception:
                coda_error = _coda_error(
                    "CODA_CONTRACT_INVALID", "Coda 无法投影为 xunji.stop-output.v1")
        if not coda_error and kind == "BLOCKED":
            coda_error = _coda_error(
                "CODA_BLOCKED_INVALID",
                "active run 尚未完成时不能用 BLOCKED 停止；应写一个能推进、"
                "转向、记录外部依赖或形成证据化裁定的下一行动",
            )
        if not coda_error:
            coda_error = _action_context_error(detail, active)
    if not coda_error:
        return ""
    sample = ", ".join(active[:6])
    more = "" if len(active) <= 6 else f" 等 {len(active)} 个"
    scope = f"active 前沿({sample}{more})" if active else "尚未完成的 active run"
    return (
        f"[输出协议硬拦] 当前 {scope}；{coda_error}。"
        "本轮必须以唯一且具体的 `下一行动: <对象 + 可执行动作>` 结尾。"
        "空值、占位符、泛泛“继续分析”、多动作/多 F-id、多个 Coda、错误 F-id 或 BLOCKED 均不放行。"
    )


def main() -> None:
    if "--selftest" in sys.argv:
        sys.exit(_selftest())

    # FAIL-OPEN for parse errors: 读不到事件不是安全问题, 不阻断
    try:
        raw = sys.stdin.buffer.read()
        event = json.loads(raw.decode("utf-8", "replace") or "{}")
    except Exception:
        sys.exit(0)

    run_dir = None
    turn_mode = "EXECUTE"
    contract: dict = {}
    stop_active = bool(event.get("stop_hook_active"))
    try:
        msg = event.get("last_assistant_message") or ""
        if not isinstance(msg, str) or not msg.strip():
            sys.exit(0)

        run_dir = find_active_run(RUNS)
        if run_dir is not None and _turn_contract is not None:
            try:
                contract = _turn_contract.load_contract(
                    run_dir, session_id=str(event.get("session_id") or ""))
                turn_mode = str(contract.get("mode") or "EXECUTE")
            except Exception:
                turn_mode = "EXECUTE"
        protocol_exempt = turn_mode in {"EXPLAIN_ONLY", "PAUSED_BY_OPERATOR", "MAINTENANCE"}

        # ---- Drift detection ----
        hits = [] if protocol_exempt else detect_drift(msg)
        tail = msg[-500:] if len(msg) > 500 else msg
        tail_hits = [p for p in hits if re.search(re.escape(p), tail, re.IGNORECASE)]

        now = time.time()
        drift_flags: list[str] = []
        drift_count = 1  # initialized early: survives even when no active run found

        # protocol_violation: drift patterns in tail OR tail ends with ? (question to operator)
        # + tail missing proper close. Requires BOTH a drift signal AND missing close —
        # answering an operator question without protocol closing should NOT trigger.
        tail_has_question = _tail_has_question(msg)
        tail_missing_close = not _tail_has_proper_close(msg)
        # Only flag protocol_violation when there's a real drift signal (hesitation/question to
        # operator) AND the close is missing. Pure conversational answers (no drift patterns,
        # no trailing question directed at operator) are NOT protocol_violations even without
        # the protocol closing formula.
        if (tail_hits or tail_has_question) and tail_missing_close:
            drift_flags.append("protocol_violation")

        # option_list: >=2 numbered option lines (autonomy decay)
        if not protocol_exempt and detect_option_list(msg):
            drift_flags.append("option_list")

        # Find the active run and evaluate semantic Reason-pass freshness.  File
        # age/mtime is deliberately not evidence that the reasoning state is
        # stale: only content digests bound by a v1 receipt can establish that.
        if run_dir is not None:
            prev_state = SessionStateManager.load(run_dir)
            if _runtime_receipts is None:
                raise RuntimeError("runtime_receipts unavailable")
            unresolved_maintenance = _runtime_receipts.unresolved_maintenance_blockers(
                run_dir,
                session_id=str(event.get("session_id") or ""),
                since=float(contract.get("updated_at") or 0.0),
            )
            unresolved = _runtime_receipts.unresolved_target_denials(
                run_dir,
                session_id=str(event.get("session_id") or ""),
                since=float(contract.get("updated_at") or 0.0),
            )
            stop_kind, terminal_error = _stop_output_union(
                msg, unresolved, unresolved_maintenance, run_dir)
            if terminal_error and (
                    terminal_error.startswith("[未执行维护真实性硬拦]")
                    or stop_kind == TARGET_DENIED or not protocol_exempt):
                _emit_gate_violation(terminal_error, stop_hook_active=stop_active)
                sys.exit(0)
            if stop_kind == TARGET_DENIED:
                # Fixed terminal variants are complete Stop outputs.  They do not
                # enter drift, ordinary Coda, Agent, or closure validators.
                sys.exit(0)
            if turn_mode == "MAINTENANCE":
                # Maintenance truth was checked above. Do not apply live-run
                # Reason/Coda/Agent/closure gates to a local maintenance turn.
                sys.exit(0)
            # Reset stale session_state (Decision B-2)
            stale_sec = SESSION_STATE_STALE_SEC
            prev_updated = _valid_ts(prev_state.get("updated_at"), now)
            if prev_updated and now - prev_updated > stale_sec:
                prev_state = {}

            semantic_state, trajectory_state, semantic_flags = (
                _semantic_reason_pass_state(run_dir)
            )

            protocol_block = "" if protocol_exempt else _protocol_block_reason(msg, run_dir)

            # ---- Escalation tracking: consecutive drift count ----
            drift_count = _next_drift_count(prev_state, drift_flags)
            drift_started_at = _next_drift_started_at(prev_state, drift_flags, now)

            state = {
                "drift_flags": drift_flags,
                "drift_started_at": drift_started_at,
                "updated_at": now,
                "reread_pending": False,
                "drift_block_count": drift_count,
                "semantic_freshness": semantic_state,
                "semantic_trajectory": trajectory_state,
            }
            SessionStateManager.save(run_dir, state)
            if protocol_block:
                _emit_gate_violation(protocol_block, stop_hook_active=stop_active)
                sys.exit(0)

        # ---- Drift notification: systemMessage only (no drift_block.json, Decision 2) ----
        notification_flags = drift_flags + (
            semantic_flags if run_dir is not None else [])
        if notification_flags:
            normal = is_normal_mode()
            threshold_handoff = 5 if normal else 3
            threshold_reread = 3 if normal else 2
            if not drift_flags:
                block_msg = (
                    "[Reason-pass 提醒] 检测到: "
                    f"{', '.join(notification_flags)}。"
                    "请按 semantic status 重读/裁定 canonical 内容并记录 v1 receipt；"
                    "内容未变时只读确认，禁止为 freshness 修改文件。"
                )
            elif drift_count >= threshold_handoff:
                block_msg = (
                    f"[漂移告警 x{drift_count}] 检测到: {', '.join(notification_flags)}。"
                    f"连续 {drift_count} 次违规——建议写 session_handoff.md 后重启新会话。"
                )
            elif drift_count >= threshold_reread:
                block_msg = (
                    f"[漂移告警 x{drift_count}] 检测到: {', '.join(notification_flags)}。"
                    f"重复违规——请 Read CLAUDE.md / WORKFLOW.md / frontier.md 后继续。"
                )
            else:
                block_msg = (
                    f"[漂移告警] 检测到: {', '.join(notification_flags)}。"
                    f"请 Read CLAUDE.md / WORKFLOW.md / frontier.md 后继续。"
                )
            print(json.dumps({"systemMessage": block_msg}, ensure_ascii=False))
            sys.exit(0)

        sys.exit(0)
    except Exception as exc:
        if (run_dir is not None or _active_run_declared()) and turn_mode == "MAINTENANCE":
            _emit_gate_violation(
                "[维护输出 fail-closed] active run 的维护真实性检查内部异常："
                + type(exc).__name__ + "。不得声称维护已完成；先修复 hook/selftest。",
                stop_hook_active=stop_active,
            )
        elif (run_dir is not None or _active_run_declared()) and turn_mode not in {
            "EXPLAIN_ONLY", "PAUSED_BY_OPERATOR"
        }:
            _emit_gate_violation(
                "[输出协议 fail-closed] active run 的 output_gate 内部异常："
                + type(exc).__name__ + "。先修 hook/selftest，不得无 Coda 静默结束。",
                stop_hook_active=stop_active,
            )
        sys.exit(0)


def _selftest() -> int:
    """Regression tests. Returns 0 if healthy."""
    import os as _os
    import subprocess
    import tempfile

    checks: list[tuple[str, bool]] = []
    contract_path = ROOT / "contracts" / "stop-output.v1.schema.json"
    fixture_path = ROOT / "tools" / "harness" / "fixtures" / "stop-output.json"
    try:
        published_contract = json.loads(contract_path.read_text(encoding="utf-8"))
        fixture = json.loads(fixture_path.read_text(encoding="utf-8"))
    except Exception:
        published_contract = {}
        fixture = {}
    contract_defs = published_contract.get("$defs") \
        if isinstance(published_contract.get("$defs"), dict) else {}
    published_types = {
        str(definition.get("properties", {}).get("type", {}).get("const") or "")
        for definition in contract_defs.values()
        if isinstance(definition, dict)
    }
    published_fields = {
        str(definition.get("properties", {}).get("type", {}).get("const") or ""):
            frozenset(str(field) for field in definition.get("required", []))
        for definition in contract_defs.values()
        if isinstance(definition, dict)
    }
    published_recovery = set(
        contract_defs.get("targetDenied", {}).get("properties", {})
        .get("recovery", {}).get("enum", [])
    )
    checks.append(("published Stop contract freezes the exclusive union",
                   published_types == STOP_OUTPUT_TYPES
                   and published_fields == STOP_RECORD_FIELDS
                   and published_recovery == RECOVERY_TYPES
                   and all(definition.get("additionalProperties") is False
                           for definition in contract_defs.values()
                           if isinstance(definition, dict))
                   and len(published_contract.get("oneOf", [])) == 2))
    valid_fixture_records = [
        item.get("record") for item in fixture.get("valid_records", [])
        if isinstance(item, dict)
    ]
    invalid_fixture_records = [
        item.get("record") for item in fixture.get("invalid_records", [])
        if isinstance(item, dict)
    ]
    checks.append(("Stop data fixtures accept every declared valid record",
                   bool(valid_fixture_records)
                   and all(not _validate_stop_record(record)
                           for record in valid_fixture_records)))
    checks.append(("Stop data fixtures reject mixed/unknown terminal records",
                   bool(invalid_fixture_records)
                   and all(bool(_validate_stop_record(record))
                           for record in invalid_fixture_records)))
    fixture_coda_cases = [
        item for item in fixture.get("coda_cases", []) if isinstance(item, dict)
    ]
    checks.append(("Coda data fixtures expose stable parser error codes",
                   bool(fixture_coda_cases)
                   and all(str(item.get("expected_error") or "")
                           in _turn_coda(str(item.get("message") or ""))[2]
                           for item in fixture_coda_cases)))
    structured_projection_cases = [
        item for item in fixture.get("structured_projection_cases", [])
        if isinstance(item, dict)
    ]
    checks.append(("structured cycle action fixtures freeze exact projection",
                   bool(structured_projection_cases)
                   and all(
                       (lambda actual, expected: actual == "" if not expected
                        else expected in actual)(
                            _structured_projection_error(
                                str(item.get("message") or ""),
                                str(item.get("receipt_next_action") or ""),
                            ),
                            str(item.get("expected_error") or ""),
                       )
                       for item in structured_projection_cases)))
    envelope_shapes = fixture.get("fixed_envelope_lines") \
        if isinstance(fixture.get("fixed_envelope_lines"), dict) else {}

    def envelope_shape_matches(text: str, kind: str) -> bool:
        expected = envelope_shapes.get(kind)
        lines = text.splitlines()
        return isinstance(expected, list) and len(lines) == len(expected) \
            and all(isinstance(prefix, str) and line.startswith(prefix)
                    for line, prefix in zip(lines, expected))

    denied_receipt = [{
        "hook_event_name": "PreToolUseDenied",
        "tool_name": "Bash",
        "target_action": True,
        "decision_code": "XUNJI_E_AGENT_PREREQUISITE",
        "decision_class": "delegation",
    }]
    denied_text = _target_denied_text(denied_receipt)
    checks.append(("denied target cannot invent HTTP/TLS measurements", bool(
        _denied_result_claim_reason(
            "GET / 返回 200，Server: nginx/1.24.0，TLS 正常，延迟 12ms。",
            denied_receipt))))
    checks.append(("denied target cannot invent Agent receipt coverage", bool(
        _denied_result_claim_reason(
            "两个 front 已由真实 Agent 回执覆盖，满足 fan-out。",
            denied_receipt))))
    checks.append(("free-form honest denial is still blocked", bool(
        _denied_result_claim_reason(
            "命令被 PreToolUse 拒绝，未执行，因此没有目标结果。",
            denied_receipt))))
    checks.append(("paraphrased claim cannot bypass unresolved-denial gate", bool(
        _denied_result_claim_reason(
            "站点有回应，握手过程也很顺利。", denied_receipt))))
    checks.append(("free-form honest prose is rejected while denial is unresolved", bool(
        _denied_result_claim_reason(
            "命令被拒绝，未执行。", denied_receipt))))
    checks.append(("fixed target-denied envelope is allowed", not bool(
        _denied_result_claim_reason(denied_text, denied_receipt))))
    checks.append(("target-denied envelope exposes stable type/error/recovery",
                   "XUNJI_STOP_TYPE=TARGET_DENIED" in denied_text
                   and "XUNJI_ERROR=XUNJI_E_AGENT_PREREQUISITE" in denied_text
                   and "XUNJI_RECOVERY=SAME_TURN_RETRY" in denied_text
                   and envelope_shape_matches(denied_text, TARGET_DENIED)))
    maintenance_receipt = [{
        "hook_event_name": "PreToolUseDenied",
        "tool_name": "Edit",
        "maintenance_action": True,
        "maintenance_paths": ["tools/turn_contract.py"],
        "decision_reason": (
            "普通 /loop 不授权修改安全关键框架路径；需要操作者在新回合首条非空指令使用"
        ),
    }]
    checks.append(("maintenance denial cannot be narrated as a successful repair", bool(
        _maintenance_truth_claim_reason(
            "已修复并还原 turn_contract。", maintenance_receipt))))
    checks.append(("maintenance denial permits honest same-turn correction", not bool(
        _maintenance_truth_claim_reason(
            "Edit 路径写错，已保留拒绝回执；下一行动: 修正路径后重试。",
            maintenance_receipt))))
    checks.append(("English negated maintenance result remains honest prose", all(
        not _maintenance_truth_claim_reason(message, maintenance_receipt)
        for message in (
            "The edit was not fixed; I will retry with the correct path.",
            "I failed to modify the pointer and did not complete the edit.",
        )
    )))
    maintenance_failure = [{
        "hook_event_name": "PostToolUseFailure",
        "tool_name": "Edit",
        "maintenance_action": True,
        "maintenance_paths": ["tools/turn_contract.py"],
        "response_excerpt": '{"error":"old_string not found"}',
    }]
    checks.append(("maintenance tool failure cannot be narrated as success", bool(
        _maintenance_truth_claim_reason("Edit succeeded.", maintenance_failure))))
    checks.append(("maintenance tool failure does not require a fixed envelope", not bool(
        _maintenance_truth_claim_reason(
            "Edit failed: old_string not found。下一行动: 读取当前内容后重试。",
            maintenance_failure))))
    shape_denial = [{
        "hook_event_name": "PreToolUseDenied",
        "decision_code": "XUNJI_E_LIFECYCLE_EXACT_ARGV_REQUIRED",
        "decision_class": "command_shape",
        "retryable_same_turn": True,
    }]
    safety_denial = [{
        "hook_event_name": "PreToolUseDenied",
        "decision_code": "XUNJI_E_SAFETY_BOUNDARY",
        "decision_class": "safety",
        "maintenance_action": True,
    }]
    checks.append(("command-shape denial has same-turn alternative semantics",
                   "XUNJI_RECOVERY=SAME_TURN_ALTERNATIVE"
                   in _target_denied_text(shape_denial)))
    checks.append(("hard-safety denial has non-retry recovery semantics",
                   "XUNJI_RECOVERY=HARD_SAFETY_DENIAL"
                   in _target_denied_text(safety_denial)))
    checks.append(("hard-safety maintenance receipt still rejects a false success claim",
                   bool(_maintenance_truth_claim_reason(
                       "安全边界修改已完成。", safety_denial))))
    normal_kind, normal_error = _stop_output_union(
        "下一行动: F-001 检查登录边界", [], [])
    target_kind, target_error = _stop_output_union(
        denied_text, denied_receipt, [])
    maintenance_kind, maintenance_error = _stop_output_union(
        "下一行动: 修正 Edit 路径并重试", [], maintenance_receipt)
    checks.append(("Stop union has no sticky maintenance variant",
                   {normal_kind, target_kind, maintenance_kind} == STOP_OUTPUT_TYPES
                   and maintenance_kind == NORMAL_CODA
                   and not normal_error and not target_error and not maintenance_error))
    precedence_kind, precedence_error = _stop_output_union(
        denied_text, denied_receipt, maintenance_receipt)
    checks.append(("target denial remains the sole fixed receipt envelope",
                   precedence_kind == TARGET_DENIED and not precedence_error))
    pointer = Path(tempfile.mkdtemp()) / "active-run"
    checks.append(("missing active-run pointer is not declared", not _active_run_declared(pointer)))
    pointer.write_text("runs/example\n", encoding="utf-8")
    checks.append(("non-empty active-run pointer is fail-closed context",
                   _active_run_declared(pointer)))

    # detect_drift
    checks.append(("empty -> []", detect_drift("") == []))
    checks.append(("clean -> []", detect_drift("下一行动: F-009 WebVPN 攻击") == []))
    checks.append(("BLOCKED ok", detect_drift("BLOCKED: safe_frontier 为空") == []))
    checks.append(("是否继续 detected", "是否继续" in " ".join(detect_drift("需要我是否继续吗"))))
    checks.append(("要不要继续 detected", "要不要继续" in " ".join(detect_drift("要不要继续等一下"))))
    checks.append(("你决定 detected", "你决定" in " ".join(detect_drift("你决定吧"))))
    checks.append(("English detected", "Should I continue" in " ".join(detect_drift("Should I continue now?"))))

    # DRIFT_PATTERNS loaded (from anti_drift or inline fallback)
    checks.append(("DRIFT_PATTERNS non-empty", len(DRIFT_PATTERNS) >= 5))

    # tail check: pattern deep in context, not in tail → should not flag
    long_clean = ("a" * 600) + "\n下一行动: WebVPN 滑块破解。"
    checks.append(("deep pattern not in tail", detect_drift(long_clean) == []))

    # _tail_has_question
    checks.append(("tail ? detected", _tail_has_question("需要继续吗？请指示下一步") is True))
    checks.append(("tail ? detected (ASCII)", _tail_has_question("Should I continue?") is True))
    checks.append(("no question mark", _tail_has_question("下一行动: F-001 扫描端口") is False))
    checks.append(("empty no question", _tail_has_question("") is False))

    # _tail_has_proper_close
    checks.append(("proper close: 下一行动", _tail_has_proper_close("下一行动: F-001 扫描端口") is True))
    checks.append(("proper close: BLOCKED", _tail_has_proper_close("BLOCKED: 网络不可达") is True))
    checks.append(("proper close: trailing space", _tail_has_proper_close("BLOCKED: 外部依赖  ") is True))
    checks.append(("empty coda rejected", _tail_has_proper_close("下一行动:") is False))
    checks.append(("missing Coda exposes CODA_MISSING",
                   "CODA_MISSING" in _turn_coda("本轮先到这里。")[2]))
    checks.append(("trailing Markdown fence exposes CODA_TRAILING_FENCE",
                   "CODA_TRAILING_FENCE" in _turn_coda(
                       "```text\n下一行动: F-001 检查登录边界\n```")[2]))
    checks.append(("placeholder coda rejected", _tail_has_proper_close("下一行动: <具体 action>") is False))
    checks.append(("vague coda rejected", _tail_has_proper_close("下一行动: 继续分析") is False))
    checks.append(("paraphrased vague coda rejected",
                   _tail_has_proper_close("下一行动: 根据前面的分析继续做下一步") is False))
    checks.append(("front id without executable action is rejected",
                   _tail_has_proper_close("下一行动: F-001 登录入口") is False))
    checks.append(("prior-result wording with concrete front and tool passes syntax",
                   _tail_has_proper_close("下一行动: 根据前面的结果继续用 render 验证 F-001") is True))
    checks.append(("multiple codas rejected",
                   _tail_has_proper_close("下一行动: F-001 检查登录\n下一行动: F-002 检查接口") is False))
    checks.append(("multiple front ids rejected",
                   _tail_has_proper_close("下一行动: 检查 F-001 + F-002") is False))
    checks.append(("multiple actions rejected",
                   _tail_has_proper_close("下一行动: 运行 check_run、回放验证和独立复审") is False))
    checks.append(("multiple actions expose CODA_MULTIPLE_ACTIONS",
                   "CODA_MULTIPLE_ACTIONS" in _turn_coda(
                       "下一行动: 运行 check_run、回放验证和独立复审")[2]))
    checks.append(("two tools joined by conjunction are multiple actions",
                   _tail_has_proper_close("下一行动: 运行 check_run 与 peer_review") is False))
    checks.append(("two tools joined by 和 are multiple actions",
                   _tail_has_proper_close("下一行动: 运行 check_run 和 peer_review") is False))
    checks.append(("two English actions joined by bare and are rejected",
                   _tail_has_proper_close("下一行动: run check_run and review evidence.md") is False))
    checks.append(("two Chinese actions joined by 并 are rejected",
                   _tail_has_proper_close("下一行动: 读取 frontier.md 并更新 evidence.md") is False))
    checks.append(("save verb cannot hide a second action",
                   _tail_has_proper_close("下一行动: 运行 check_run 和保存结果") is False))
    checks.append(("two executable clauses separated by comma are rejected",
                   _tail_has_proper_close("下一行动: 读取 frontier.md，更新 evidence.md") is False))
    checks.append(("one scan action may contain multiple port parameters",
                   _tail_has_proper_close("下一行动: 扫描 F-001 的 80，443 端口") is True))
    checks.append(("single action may contain conjunction inside one front",
                   _tail_has_proper_close("下一行动: 验证 F-001 登录和会话边界") is True))
    checks.append(("single English action may contain joined objects",
                   _tail_has_proper_close("下一行动: scan F-001 headers and cookies") is True))
    checks.append(("no proper close: prose", _tail_has_proper_close("继续分析结果") is False))
    checks.append(("no proper close: question", _tail_has_proper_close("是否继续测试？") is False))
    checks.append(("no proper close: empty", _tail_has_proper_close("") is False))
    checks.append(("no proper close: mid-sentence only", _tail_has_proper_close("下一步应该测试 下一行动: xxx\nbut this is not the tail") is False))
    # detect_option_list
    checks.append(("option list detected", detect_option_list("1. scan\n2. probe\n3. report") is True))
    checks.append(("option list with paren", detect_option_list("1) foo\n2) bar") is True))
    checks.append(("option list with Chinese", detect_option_list("1、扫描\n2、探测") is True))
    checks.append(("single option only", detect_option_list("1. only one") is False))
    checks.append(("no option list", detect_option_list("just some text\nno numbers") is False))
    # Zero-width character handling
    checks.append(("proper close with zero-width", _tail_has_proper_close("下一行动: test​") is True))
    checks.append(("drift detect with zero-width",
                   "是否继续" in " ".join(detect_drift("xxx是否​继续吗"))))
    checks.append(("option list with zero-width",
                   detect_option_list("1.​ scan\n2、probe") is True))
    # _strip_invisible
    checks.append(("strip_invisible removes zwsp", _strip_invisible("a​b") == "ab"))
    checks.append(("strip_invisible no-op", _strip_invisible("abc") == "abc"))

    # session_state read/write via SessionStateManager
    d = Path(tempfile.mkdtemp())
    st = {"drift_flags": ["protocol_violation"], "updated_at": time.time()}
    SessionStateManager.save(d, st)
    loaded = SessionStateManager.load(d)
    checks.append(("session_state roundtrip", loaded.get("drift_flags") == ["protocol_violation"]))
    checks.append(("session_state missing -> {}", SessionStateManager.load(d / "nope") == {}))
    # _valid_ts (imported from anti_drift)
    now_ts = time.time()
    # consecutive count helper semantics
    checks.append(("drift count first hit -> 1", _next_drift_count({}, ["protocol_violation"]) == 1))
    checks.append(("drift count increments on drift",
                   _next_drift_count({"drift_block_count": 2}, ["option_list"]) == 3))
    checks.append(("drift count resets on clean",
                   _next_drift_count({"drift_block_count": 3}, []) == 0))
    checks.append(("drift count bad prior -> 1",
                   _next_drift_count({"drift_block_count": "bad"}, ["frontier_stale"]) == 1))
    checks.append(("drift started first hit -> now",
                   _next_drift_started_at({}, ["protocol_violation"], now_ts) == now_ts))
    checks.append(("drift started preserves streak",
                   _next_drift_started_at({"drift_flags": ["protocol_violation"],
                                           "drift_started_at": now_ts - 10},
                                          ["option_list"], now_ts) == now_ts - 10))
    checks.append(("drift started resets on clean",
                   _next_drift_started_at({"drift_flags": ["protocol_violation"],
                                           "drift_started_at": now_ts - 10}, [], now_ts) == 0.0))
    checks.append(("drift started bad prior -> now",
                   _next_drift_started_at({"drift_flags": ["protocol_violation"],
                                           "drift_started_at": "bad"},
                                          ["frontier_stale"], now_ts) == now_ts))
    checks.append(("valid_ts valid", _valid_ts(now_ts, now_ts) == now_ts))
    checks.append(("valid_ts negative -> 0", _valid_ts(-1, now_ts) == 0.0))
    checks.append(("valid_ts future -> 0", _valid_ts(now_ts + 999, now_ts) == 0.0))
    checks.append(("valid_ts zero -> 0", _valid_ts(0, now_ts) == 0.0))
    checks.append(("valid_ts non-numeric -> 0", _valid_ts("abc", now_ts) == 0.0))

    open_run = d / "open_run"
    open_run.mkdir()
    (open_run / "frontier.md").write_text(
        "# Frontier\n\n## Open Fronts\n\n### F-001\n- Status: open\n- Barrier class: auth-layer\n",
        encoding="utf-8")
    (open_run / "evidence.md").write_text("# Evidence Ledger\n", encoding="utf-8")
    (open_run / "decisions.md").write_text("# Decisions\n", encoding="utf-8")
    (open_run / "hypotheses.md").write_text("# Hypotheses\n", encoding="utf-8")
    old_semantic_mtime = time.time() - 365 * 24 * 60 * 60
    for canonical in (
            open_run / "frontier.md", open_run / "evidence.md",
            open_run / "decisions.md", open_run / "hypotheses.md"):
        _os.utime(canonical, (old_semantic_mtime, old_semantic_mtime))
    semantic_before, _, flags_before = _semantic_reason_pass_state(open_run)
    checks.append(("missing Reason-pass receipt is semantically unproven",
                   semantic_before.get("status") == "legacy_unproven"
                   and flags_before == []))
    record_reason_pass(
        open_run,
        cycle_id=1,
        chosen_front="F-001",
        reason="whole-graph adjudication selected the open auth-layer front",
    )
    semantic_fresh, _, fresh_flags = _semantic_reason_pass_state(open_run)
    checks.append(("old canonical mtimes do not forge semantic staleness",
                   semantic_fresh.get("status") == "fresh"
                   and fresh_flags == []
                   and (open_run / "frontier.md").stat().st_mtime
                       <= old_semantic_mtime + 1.0))
    (open_run / "frontier.md").write_text(
        (open_run / "frontier.md").read_text(encoding="utf-8")
        + "\n- New signal: login realm changed\n",
        encoding="utf-8",
    )
    _os.utime(open_run / "frontier.md", (old_semantic_mtime, old_semantic_mtime))
    semantic_changed, _, changed_flags = _semantic_reason_pass_state(open_run)
    checks.append(("content change with unchanged mtime requires Reason pass",
                   semantic_changed.get("status") == "changed_unadjudicated"
                   and "frontier_digest" in semantic_changed.get("changed_fields", [])
                   and changed_flags == ["reason_pass_due"]))
    closed_run = d / "closed_run"
    closed_run.mkdir()
    (closed_run / "frontier.md").write_text(
        "# Frontier\n\n## Closed Fronts\n\n### F-001\n- Status: closed\n- Barrier class: none\n",
        encoding="utf-8")
    (closed_run / "evidence.md").write_text("# Evidence Ledger\n", encoding="utf-8")
    (closed_run / "decisions.md").write_text("# Decisions\n", encoding="utf-8")
    (closed_run / "hypotheses.md").write_text("# Hypotheses\n", encoding="utf-8")
    checks.append(("protocol fronts detect open run", _active_protocol_fronts(open_run) == ["F-001"]))
    checks.append(("protocol fronts ignore closed run", _active_protocol_fronts(closed_run) == []))
    open_coda_block = _protocol_block_reason("本轮完成，继续。", open_run)
    checks.append(("open run without 下一行动 hard-blocks",
                   "输出协议硬拦" in open_coda_block))
    checks.append(("Coda correction does not inject stale strategy advice",
                   "当前控制面建议" not in open_coda_block))
    checks.append(("open run with 下一行动 passes protocol",
                   _protocol_block_reason("下一行动: F-001 尝试登录错误页对照", open_run) == ""))
    checks.append(("closed but incomplete run still requires closure action",
                   "输出协议硬拦" in _protocol_block_reason("收口检查完成。", closed_run)))
    checks.append(("closed run with concrete closure action passes",
                   _protocol_block_reason("下一行动: 运行 check_run 收口检查", closed_run) == ""))
    no_front_denial = _target_denied_text(denied_receipt, closed_run)
    checks.append(("no-front denial envelope is accepted by truth gate",
                   not _denied_result_claim_reason(
                       no_front_denial, denied_receipt, closed_run)))
    no_front_kind, no_front_error = _stop_output_union(
        no_front_denial, denied_receipt, [], closed_run)
    checks.append(("no-front denial is accepted only by terminal union branch",
                   no_front_kind == TARGET_DENIED and not no_front_error
                   and "STOP_ENVELOPE_UNAUTHORIZED" in _protocol_block_reason(
                       no_front_denial, closed_run)))
    checks.append(("frontier.md denial cannot bypass a real active F-id",
                   bool(_denied_result_claim_reason(
                       no_front_denial, denied_receipt, open_run))))
    checks.append(("closed incomplete run rejects generic action",
                   "必须指向明确的收口或控制面对象" in _protocol_block_reason(
                       "下一行动: 分析其他问题", closed_run)))
    checks.append(("closure candidate cannot use BLOCKED as a pause",
                   "不能用 BLOCKED" in _protocol_block_reason("BLOCKED: 等待操作者继续", closed_run)))
    checks.append(("closure candidate rejects arbitrary front id",
                   "当前没有 active 前沿" in _protocol_block_reason(
                       "下一行动: F-999 检查另一个入口", closed_run)))
    (closed_run / "decisions.md").write_text(
        "# Decisions\n\nGHOST_COMPLETE receipt=" + ("a" * 64) + "\n",
        encoding="utf-8",
    )
    unbound_completion_reason = _protocol_block_reason("收口检查完成。", closed_run)
    original_committed_predicate = (
        _completion_transaction.is_valid_committed
        if _completion_transaction is not None else None
    )
    try:
        if _completion_transaction is not None:
            _completion_transaction.is_valid_committed = lambda _run: True
        committed_completion_reason = _protocol_block_reason(
            "收口检查完成。", closed_run)
    finally:
        if _completion_transaction is not None and original_committed_predicate is not None:
            _completion_transaction.is_valid_committed = original_committed_predicate
    checks.append(("legacy unbound marker cannot release output protocol",
                   "输出协议硬拦" in unbound_completion_reason))
    checks.append(("valid committed transaction releases output protocol",
                   committed_completion_reason == ""))
    checks.append(("active front cannot use BLOCKED coda",
                   "不能用 BLOCKED" in _protocol_block_reason("BLOCKED: 等待外部凭据到位", open_run)))
    checks.append(("wrong active front id is rejected",
                   "CODA_WRONG_FRONT" in _protocol_block_reason(
                       "下一行动: F-999 检查另一个入口", open_run)))
    checks.append(("active run requires front id or control-plane object",
                   "必须引用一个 active F-id" in _protocol_block_reason(
                       "下一行动: 检查登录错误页响应差异", open_run)))
    checks.append(("explicit control-plane action may omit front id",
                   _protocol_block_reason("下一行动: 运行 workers.py 分派子任务", open_run) == ""))
    checks.append(("bare Agent token is not a control-plane bypass",
                   "必须引用一个 active F-id" in _protocol_block_reason(
                       "下一行动: 运行 Agent 完成工作", open_run)))
    original_loop_journal = globals().get("_loop_journal")
    original_work_plan = globals().get("_work_plan")

    class StructuredJournalFixture:
        @staticmethod
        def load_events(_run_dir):
            return [{
                "event": "cycle_end",
                "data": {
                    "plan_id": "WP-1-11111111",
                    "plan_digest": "1" * 64,
                    "next_action": "F-001 分析登录响应差异",
                },
            }]

        @staticmethod
        def validate_cycle_events(_events):
            return {
                "ended_plan_digests": ["1" * 64],
                "active_plan_digest": "1" * 64,
            }

    class StructuredWorkPlanFixture:
        @staticmethod
        def transaction_bound_plan(_run_dir):
            return {"plan_digest": "1" * 64}

    class MissingStructuredWorkPlanFixture:
        @staticmethod
        def transaction_bound_plan(_run_dir):
            raise RuntimeError("WORK_PLAN_TRANSACTION_REQUIRED")

    class NewActiveJournalFixture(StructuredJournalFixture):
        @staticmethod
        def validate_cycle_events(_events):
            return {
                "ended_plan_digests": ["1" * 64],
                "active_plan_digest": "2" * 64,
            }

    class NewActiveWorkPlanFixture:
        @staticmethod
        def transaction_bound_plan(_run_dir):
            return {"plan_digest": "2" * 64}

    class InvalidStructuredJournalFixture(StructuredJournalFixture):
        @staticmethod
        def validate_cycle_events(_events):
            error = RuntimeError("invalid structured receipt")
            error.code = "CYCLE_EVENT_HASH_CHAIN_INVALID"
            raise error

    class MalformedPlanEndJournalFixture(InvalidStructuredJournalFixture):
        TYPED_CYCLE_EVENTS = frozenset({"cycle_end", "stage_plan"})

        @staticmethod
        def load_events(_run_dir):
            return [{
                "event": "cycle_end",
                "data": {
                    "plan_id": "WP-1-11111111",
                    "next_action": "F-001 分析登录响应差异",
                },
            }]

    try:
        globals()["_loop_journal"] = StructuredJournalFixture
        globals()["_work_plan"] = StructuredWorkPlanFixture
        structured_exact = _protocol_block_reason(
            "下一行动: F-001 分析登录响应差异", open_run)
        structured_mismatch = _protocol_block_reason(
            "下一行动: F-001 检查登录错误页", open_run)
        structured_missing = _protocol_block_reason("本轮完成。", open_run)
        structured_complete_mismatch = _protocol_block_reason(
            "收口完成。", closed_run)
        globals()["_work_plan"] = MissingStructuredWorkPlanFixture
        structured_no_provenance = _protocol_block_reason(
            "下一行动: F-001 分析登录响应差异", open_run)
        globals()["_loop_journal"] = NewActiveJournalFixture
        globals()["_work_plan"] = NewActiveWorkPlanFixture
        old_end_new_active = _protocol_block_reason(
            "下一行动: F-001 检查新计划入口", open_run)
        old_end_new_active_complete = _protocol_block_reason(
            "收口完成。", closed_run)
        globals()["_loop_journal"] = InvalidStructuredJournalFixture
        globals()["_work_plan"] = StructuredWorkPlanFixture
        structured_invalid = _protocol_block_reason(
            "下一行动: F-001 分析登录响应差异", open_run)
        globals()["_loop_journal"] = MalformedPlanEndJournalFixture
        malformed_structured_end = _protocol_block_reason(
            "下一行动: F-001 分析登录响应差异", open_run)
    finally:
        globals()["_loop_journal"] = original_loop_journal
        globals()["_work_plan"] = original_work_plan
    checks.append(("validated cycle_end next_action is the exact Coda projection",
                   structured_exact == ""))
    checks.append(("structured next_action mismatch has a stable rejection code",
                   "CODA_STRUCTURED_PROJECTION_MISMATCH" in structured_mismatch))
    checks.append(("structured next_action cannot fall back to missing free text",
                   "CODA_STRUCTURED_PROJECTION_MISSING" in structured_missing))
    checks.append(("completion state does not bypass a structured action receipt",
                   "CODA_STRUCTURED_PROJECTION_MISSING"
                   in structured_complete_mismatch))
    checks.append(("invalid structured receipt fails closed without text fallback",
                   "CODA_STRUCTURED_RECEIPT_INVALID" in structured_invalid))
    checks.append(("malformed plan-bound end cannot disappear into text fallback",
                   "CODA_STRUCTURED_RECEIPT_INVALID" in malformed_structured_end))
    checks.append(("structured receipt requires committed v2 provenance",
                   "CODA_STRUCTURED_PROVENANCE_INVALID" in structured_no_provenance))
    checks.append(("old cycle action does not shadow a newer active plan",
                   old_end_new_active == ""))
    checks.append(("completion marker cannot bypass a newer active plan Coda",
                   "CODA_MISSING" in old_end_new_active_complete))
    checks.append(("structured projection reuses normal Coda semantics",
                   "CODA_VAGUE_ACTION" in _structured_projection_error(
                       "下一行动: 等待用户", "等待用户")
                   and "CODA_MULTIPLE_ACTIONS" in _structured_projection_error(
                       "下一行动: 运行 check_run 和 peer_review",
                       "运行 check_run 和 peer_review")
                   and "CODA_WRONG_FRONT" in _action_context_error(
                       "F-999 检查其他入口", ["F-001"])
                   and _action_context_error(
                       "f-001 检查登录响应差异", ["F-001"]) == ""))
    original_loop_state = globals().get("_loop_state")
    fallback_heading_run = d / "fallback_heading_run"
    fallback_heading_run.mkdir()
    (fallback_heading_run / "frontier.md").write_text(
        "# Frontier\n\n## Front F-002 — login\n- Status: working\n",
        encoding="utf-8",
    )
    (fallback_heading_run / "decisions.md").write_text("# Decisions\n", encoding="utf-8")
    fallback_predicate = (
        _completion_transaction.is_valid_committed
        if _completion_transaction is not None else None
    )
    try:
        globals()["_loop_state"] = None
        fallback_state = _protocol_state(open_run)
        fallback_heading_state = _protocol_state(fallback_heading_run)
        fallback_unbound_completion = _protocol_state(closed_run)
        if _completion_transaction is not None:
            _completion_transaction.is_valid_committed = lambda _run: True
        fallback_committed_completion = _protocol_state(closed_run)
        if _completion_transaction is not None and fallback_predicate is not None:
            _completion_transaction.is_valid_committed = fallback_predicate
        fallback_block = _protocol_block_reason("本轮先停在这里。", open_run)
        fallback_pass = _protocol_block_reason("下一行动: F-001 检查登录错误页", open_run)
    finally:
        globals()["_loop_state"] = original_loop_state
        if _completion_transaction is not None and fallback_predicate is not None:
            _completion_transaction.is_valid_committed = fallback_predicate
    checks.append(("loop_state failure keeps fallback active-front Coda enforcement",
                   fallback_state.get("fallback") is True
                   and fallback_state.get("active_fronts") == ["F-001"]
                   and "输出协议硬拦" in fallback_block
                   and fallback_pass == ""))
    checks.append(("fallback parser accepts labeled F-id headings",
                   fallback_heading_state.get("active_fronts") == ["F-002"]))
    checks.append(("fallback completion also requires a valid transaction",
                   not fallback_unbound_completion.get("loop_complete")
                   and fallback_committed_completion.get("loop_complete") is True))
    original_protocol_state = globals().get("_protocol_state")
    try:
        globals()["_protocol_state"] = lambda _run_dir: {}
        empty_state_block = _protocol_block_reason("下一行动: F-001 检查入口", open_run)
    finally:
        globals()["_protocol_state"] = original_protocol_state
    checks.append(("empty protocol state fails closed",
                   "无法解析 active run 状态" in empty_state_block))

    runs_root = d / "runs"
    live_run = runs_root / "live_run"
    live_run.mkdir(parents=True)
    (live_run / "frontier.md").write_text(
        "# Frontier\n\n## Open Fronts\n\n### F-900\n- Status: open\n- Barrier class: auth-layer\n",
        encoding="utf-8")
    (live_run / "evidence.md").write_text("# Evidence Ledger\n", encoding="utf-8")
    (live_run / "decisions.md").write_text("# Decisions\n", encoding="utf-8")
    (live_run / "hypotheses.md").write_text("# Hypotheses\n", encoding="utf-8")
    decoy_run = runs_root / "newer_but_not_active"
    decoy_run.mkdir()
    (decoy_run / "frontier.md").write_text(
        "# Frontier\n\n## Closed Fronts\n\n### F-901\n- Status: closed\n",
        encoding="utf-8")
    (decoy_run / "evidence.md").write_text("# Evidence Ledger\n", encoding="utf-8")
    pointer = d / "active_run_pointer"
    pointer.write_text(str(live_run), encoding="utf-8")
    event = {"last_assistant_message": "本轮完成，继续。"}
    env = dict(_os.environ)
    env["XUNJI_RUNS_ROOT"] = str(runs_root)
    env["XUNJI_ACTIVE_RUN_FILE"] = str(pointer)
    proc = subprocess.run(
        [sys.executable, str(Path(__file__).resolve())],
        input=json.dumps(event, ensure_ascii=False),
        text=True,
        capture_output=True,
        encoding="utf-8",
        errors="replace",
        env=env,
        timeout=10,
    )
    checks.append(("hook subprocess honors explicit active pointer and blocks open front",
                   proc.returncode == 0 and '"decision": "block"' in (proc.stdout or "")
                   and "F-900" in (proc.stdout or "")))
    retry_proc = subprocess.run(
        [sys.executable, str(Path(__file__).resolve())],
        input=json.dumps({**event, "stop_hook_active": True}, ensure_ascii=False),
        text=True, capture_output=True, encoding="utf-8", errors="replace",
        env=env, timeout=10,
    )
    checks.append(("Stop retry is advisory instead of entering another block loop",
                   retry_proc.returncode == 0
                   and '"systemMessage"' in (retry_proc.stdout or "")
                   and '"decision": "block"' not in (retry_proc.stdout or "")))
    (live_run / "state").mkdir(exist_ok=True)
    (live_run / "state" / "turn_contract.json").write_text(json.dumps({
        "schema": "xunji.turn_contract.v1", "mode": "EXPLAIN_ONLY",
        "session_id": "s-explain", "transcript_path": "",
        "prompt_sha256": "a" * 64, "prompt_excerpt": "explain fixture",
        "memory_approved": False, "fanout_override": False,
        "updated_at": time.time(),
    }), encoding="utf-8")
    explain_proc = subprocess.run(
        [sys.executable, str(Path(__file__).resolve())],
        input=json.dumps({"session_id": "s-explain", "last_assistant_message":
                          "原因是 Agent Board 过去只在 Stop 阶段检查。"}, ensure_ascii=False),
        text=True, capture_output=True, encoding="utf-8", errors="replace",
        env=env, timeout=10,
    )
    checks.append(("EXPLAIN_ONLY response is not forced to add Coda",
                   explain_proc.returncode == 0 and not (explain_proc.stdout or "").strip()))
    explain_marker_proc = subprocess.run(
        [sys.executable, str(Path(__file__).resolve())],
        input=json.dumps({
            "session_id": "s-explain",
            "last_assistant_message": (
                "固定终态示例：\nXUNJI_EXECUTION_STATUS=DENIED\n这里仅作说明。"
            ),
        }, ensure_ascii=False),
        text=True, capture_output=True, encoding="utf-8", errors="replace",
        env=env, timeout=10,
    )
    checks.append(("EXPLAIN_ONLY may quote a reserved marker without claiming terminal state",
                   explain_marker_proc.returncode == 0
                   and not (explain_marker_proc.stdout or "").strip()))

    # Full main() regression: mutually exclusive terminal variants, receipt-bound
    # bypass, same-turn resolution, and new-prompt expiry.
    terminal_run = runs_root / "terminal_run"
    terminal_run.mkdir()
    (terminal_run / "state").mkdir()
    (terminal_run / "frontier.md").write_text(
        "# Frontier\n\n## Open Fronts\n\n"
        "### F-910\n- Status: open\n- Barrier class: auth-layer\n\n"
        "### F-911\n- Status: open\n- Barrier class: tls-layer\n\n"
        "### F-912\n- Status: open\n- Barrier class: js-layer\n\n"
        "### F-913\n- Status: open\n- Barrier class: api-layer\n",
        encoding="utf-8",
    )
    (terminal_run / "evidence.md").write_text("# Evidence Ledger\n", encoding="utf-8")
    (terminal_run / "decisions.md").write_text("# Decisions\n", encoding="utf-8")
    (terminal_run / "hypotheses.md").write_text("# Hypotheses\n", encoding="utf-8")
    terminal_transcript = d / "terminal-transcript.jsonl"
    terminal_transcript.write_text(
        "target-deny target-success target-new-prompt maintenance-deny paused-target-deny\n",
        encoding="utf-8",
    )
    terminal_contract_path = terminal_run / "state" / "turn_contract.json"

    def write_terminal_contract(mode: str, updated_at: float) -> None:
        terminal_contract_path.write_text(json.dumps({
            "schema": "xunji.turn_contract.v1",
            "mode": mode,
            "session_id": "s-terminal",
            "transcript_path": str(terminal_transcript),
            "prompt_sha256": "b" * 64,
            "prompt_excerpt": f"{mode.lower()} fixture",
            "memory_approved": False,
            "fanout_override": False,
            "updated_at": updated_at,
        }), encoding="utf-8")

    def invoke_stop(script: Path, message: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [sys.executable, str(script)],
            input=json.dumps({
                "session_id": "s-terminal",
                "last_assistant_message": message,
            }, ensure_ascii=False),
            text=True,
            capture_output=True,
            encoding="utf-8",
            errors="replace",
            env=env,
            timeout=15,
        )

    pointer.write_text(str(terminal_run), encoding="utf-8")
    write_terminal_contract("EXECUTE", time.time() - 1)
    target_command = "python3 tools/probe.py GET https://example.test"
    _runtime_receipts.append_hook_event(terminal_run, {
        "hook_event_name": "PreToolUseDenied",
        "session_id": "s-terminal",
        "transcript_path": str(terminal_transcript),
        "tool_name": "Bash",
        "tool_use_id": "target-deny",
        "tool_input": {"command": target_command},
        "xunji_decision": "deny",
        "xunji_reason": "Agent prerequisite missing",
        "xunji_decision_code": "XUNJI_E_DELEGATION_REQUIRED",
        "xunji_decision_class": "delegation",
        "xunji_target_action": True,
    })
    target_pending = _runtime_receipts.unresolved_target_denials(
        terminal_run, session_id="s-terminal",
        since=json.loads(terminal_contract_path.read_text())['updated_at'])
    target_envelope = _target_denied_text(target_pending, terminal_run)
    target_output_proc = invoke_stop(Path(__file__).resolve(), target_envelope)
    target_run_proc = invoke_stop(
        ROOT / ".claude" / "hooks" / "run_gate.py", target_envelope)
    checks.append(("main: receipt-backed TARGET_DENIED bypasses ordinary Coda and run gates",
                   target_output_proc.returncode == 0
                   and not (target_output_proc.stdout or "").strip()
                   and target_run_proc.returncode == 0
                   and not (target_run_proc.stdout or "").strip()))
    target_fenced_proc = invoke_stop(
        Path(__file__).resolve(), target_envelope + "\n```")
    checks.append(("main: fixed envelope must remain exact",
                   '"decision": "block"' in (target_fenced_proc.stdout or "")))
    target_prose_proc = invoke_stop(
        Path(__file__).resolve(), "下一行动: F-910 检查登录边界")
    checks.append(("main: unresolved target denial rejects NORMAL_CODA",
                   '"decision": "block"' in (target_prose_proc.stdout or "")
                   and "TARGET_DENIED" in (target_prose_proc.stdout or "")))

    _runtime_receipts.append_hook_event(terminal_run, {
        "hook_event_name": "PostToolUse",
        "session_id": "s-terminal",
        "transcript_path": str(terminal_transcript),
        "tool_name": "Bash",
        "tool_use_id": "target-success",
        "tool_input": {"command": target_command},
        "tool_response": {"stdout": "saved artifact"},
        "xunji_target_action": True,
    })
    same_turn_proc = invoke_stop(
        Path(__file__).resolve(), "下一行动: F-910 检查登录边界")
    checks.append(("main: identical same-turn target success resolves denial",
                   same_turn_proc.returncode == 0
                   and not (same_turn_proc.stdout or "").strip()))

    _runtime_receipts.append_hook_event(terminal_run, {
        "hook_event_name": "PreToolUseDenied",
        "session_id": "s-terminal",
        "transcript_path": str(terminal_transcript),
        "tool_name": "Bash",
        "tool_use_id": "target-new-prompt",
        "tool_input": {"command": target_command + " --save"},
        "xunji_decision": "deny",
        "xunji_reason": "work plan missing",
        "xunji_decision_code": "XUNJI_E_WORK_PLAN_REQUIRED",
        "xunji_decision_class": "work_plan",
        "xunji_target_action": True,
    })
    write_terminal_contract("EXECUTE", time.time())
    expired_proc = invoke_stop(
        Path(__file__).resolve(), "下一行动: F-910 检查登录边界")
    checks.append(("main: target denial expires across a newer operator prompt",
                   expired_proc.returncode == 0
                   and not (expired_proc.stdout or "").strip()))
    forged_after_expiry = invoke_stop(
        ROOT / ".claude" / "hooks" / "run_gate.py", target_envelope)
    checks.append(("main: stale fixed envelope cannot bypass later Stop gates",
                   '"decision": "block"' in (forged_after_expiry.stdout or "")))

    write_terminal_contract("MAINTENANCE", time.time())
    _runtime_receipts.append_hook_event(terminal_run, {
        "hook_event_name": "PreToolUseDenied",
        "session_id": "s-terminal",
        "transcript_path": str(terminal_transcript),
        "tool_name": "Edit",
        "tool_use_id": "maintenance-deny",
        "tool_input": {"file_path": str(ROOT / "tools" / "turn_contract.py")},
        "xunji_decision": "deny",
        "xunji_reason": "new operator exact-path authority required",
        "xunji_decision_code": "XUNJI_E_MAINTENANCE_AUTHORITY_REQUIRED",
        "xunji_decision_class": "authority",
        "xunji_maintenance_action": True,
        "xunji_maintenance_paths": ["tools/turn_contract.py"],
    })
    maintenance_pending = _runtime_receipts.unresolved_maintenance_blockers(
        terminal_run, session_id="s-terminal",
        since=json.loads(terminal_contract_path.read_text())['updated_at'])
    maintenance_output_proc = invoke_stop(
        Path(__file__).resolve(),
        "Edit 路径错误且未执行；已保留回执，修正后在当前回合重试。",
    )
    maintenance_run_proc = invoke_stop(
        ROOT / ".claude" / "hooks" / "run_gate.py",
        "Edit 路径错误且未执行；已保留回执，修正后在当前回合重试。",
    )
    false_maintenance_success = invoke_stop(
        Path(__file__).resolve(), "turn_contract 已成功修复并完成。")
    checks.append(("main: maintenance denial allows honest correction",
                   maintenance_output_proc.returncode == 0
                   and '"decision": "block"' not in (
                       maintenance_output_proc.stdout or "")))
    checks.append(("main: maintenance turn bypasses run progression gates",
                   maintenance_run_proc.returncode == 0
                   and not (maintenance_run_proc.stdout or "").strip()))
    checks.append(("main: maintenance denial still blocks false success",
                   '"decision": "block"' in (
                       false_maintenance_success.stdout or "")))
    write_terminal_contract("MAINTENANCE", time.time())
    maintenance_expired_proc = invoke_stop(
        Path(__file__).resolve(), "维护拒绝来自上一个 prompt，当前不声称已执行。")
    checks.append(("main: maintenance blocker expires across a newer operator prompt",
                   maintenance_expired_proc.returncode == 0
                   and not (maintenance_expired_proc.stdout or "").strip()))

    write_terminal_contract("PAUSED_BY_OPERATOR", time.time() - 1)
    _runtime_receipts.append_hook_event(terminal_run, {
        "hook_event_name": "PreToolUseDenied",
        "session_id": "s-terminal",
        "transcript_path": str(terminal_transcript),
        "tool_name": "Bash",
        "tool_use_id": "paused-target-deny",
        "tool_input": {"command": target_command + " --paused"},
        "xunji_decision": "deny",
        "xunji_reason": "target action forbidden while paused",
        "xunji_decision_code": "XUNJI_E_PAUSED_TARGET_FORBIDDEN",
        "xunji_decision_class": "policy",
        "xunji_target_action": True,
    })
    paused_pending = _runtime_receipts.unresolved_target_denials(
        terminal_run, session_id="s-terminal",
        since=json.loads(terminal_contract_path.read_text())['updated_at'])
    paused_envelope = _target_denied_text(paused_pending, terminal_run)
    paused_run_proc = invoke_stop(
        ROOT / ".claude" / "hooks" / "run_gate.py", paused_envelope)
    checks.append(("main: fixed envelope never bypasses PAUSED Cron quiescence",
                   '"decision": "block"' in (paused_run_proc.stdout or "")
                   and "暂停事务" in (paused_run_proc.stdout or "")))

    closure_run = runs_root / "closure_run"
    closure_run.mkdir()
    (closure_run / "frontier.md").write_text(
        "# Frontier\n\n## Closed Fronts\n\n### F-902\n- Status: closed\n",
        encoding="utf-8")
    (closure_run / "evidence.md").write_text("# Evidence Ledger\n", encoding="utf-8")
    (closure_run / "decisions.md").write_text("# Decisions\n", encoding="utf-8")
    (closure_run / "retrospective.md").write_text(
        "# Retrospective\n\n- Verdict: FINAL\n", encoding="utf-8")
    pointer.write_text(str(closure_run), encoding="utf-8")
    proper_event = {"last_assistant_message": "下一行动: 运行 check_run 收口检查"}
    output_proc = subprocess.run(
        [sys.executable, str(Path(__file__).resolve())],
        input=json.dumps(proper_event, ensure_ascii=False), text=True, capture_output=True,
        encoding="utf-8", errors="replace", env=env, timeout=10,
    )
    run_proc = subprocess.run(
        [sys.executable, str(ROOT / ".claude" / "hooks" / "run_gate.py")],
        input=json.dumps(proper_event, ensure_ascii=False), text=True, capture_output=True,
        encoding="utf-8", errors="replace", env=env, timeout=15,
    )
    checks.append(("explicit-pointer Stop pipeline: output Coda passes then closure gate blocks",
                   not (output_proc.stdout or "").strip()
                   and '"decision": "block"' in (run_proc.stdout or "")
                   and "缺独立复审" in (run_proc.stdout or "")))
    run_retry_proc = subprocess.run(
        [sys.executable, str(ROOT / ".claude" / "hooks" / "run_gate.py")],
        input=json.dumps({**proper_event, "stop_hook_active": True}, ensure_ascii=False),
        text=True, capture_output=True, encoding="utf-8", errors="replace",
        env=env, timeout=15,
    )
    checks.append(("run gate Stop retry exits cleanly without another block",
                   run_retry_proc.returncode == 0
                   and not (run_retry_proc.stdout or "").strip()))

    bad = [n for n, ok in checks if not ok]
    for n, ok in checks:
        print(("ok   " if ok else "FAIL ") + n, file=sys.stderr)
    print("output_gate selftest " + ("passed" if not bad else f"FAILED ({len(bad)})"), file=sys.stderr)
    return 0 if not bad else 1


if __name__ == "__main__":
    main()
