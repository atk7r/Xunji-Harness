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


_DENIED_ONLY_RE = re.compile(
    r"\AXUNJI_EXECUTION_STATUS=DENIED\n"
    r"未执行目标动作；不存在该动作的实测结果。\n"
    r"下一行动: (?:F-\d{3}|frontier\.md) 修复 PreToolUse 前置条件后重试同一动作\Z"
)


def _active_run_declared(pointer: Path | None = None) -> bool:
    """Conservatively detect an operator-selected run if lookup itself failed."""
    marker = pointer or Path(os.environ.get(
        "XUNJI_ACTIVE_RUN_FILE", str(ROOT / ".claude" / "xunji_active_run")))
    try:
        return marker.is_file() and bool(marker.read_text(
            encoding="utf-8", errors="replace").strip())
    except Exception:
        return marker.exists()


def _denied_result_claim_reason(
    msg: str,
    denied: list[dict],
    run_dir: Path | None = None,
) -> str:
    if not denied:
        return ""
    active = _active_protocol_fronts(run_dir) if run_dir is not None else []
    anchor = active[0] if active else "frontier.md"
    clean = _strip_invisible(msg).strip()
    if run_dir is None:
        if _DENIED_ONLY_RE.fullmatch(clean):
            return ""
    else:
        expected = (
            "XUNJI_EXECUTION_STATUS=DENIED\n"
            "未执行目标动作；不存在该动作的实测结果。\n"
            f"下一行动: {anchor} 修复 PreToolUse 前置条件后重试同一动作"
        )
        if clean == expected:
            return ""
    return (
        "[未执行动作真实性硬拦] 本回合仍有未被同工具、同执行动作成功回执消解的"
        " PreToolUse 目标动作拒绝。禁止自由文本和任何结果转述；继续完成前置条件并"
        "重试原动作，或仅输出以下三行：\n"
        "XUNJI_EXECUTION_STATUS=DENIED\n"
        "未执行目标动作；不存在该动作的实测结果。\n"
        f"下一行动: {anchor} 修复 PreToolUse 前置条件后重试同一动作"
    )


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


def _turn_coda(msg: str) -> tuple[str, str, str]:
    """Return ``(kind, detail, error)`` for one concrete final Coda line."""
    clean = _strip_invisible(msg or "").rstrip()
    matches = list(CODA_RE.finditer(clean))
    if not matches:
        return "", "", "缺少回合 Coda"
    if len(matches) != 1:
        return "", "", "只能有一个回合 Coda"
    match = matches[0]
    if match.end() != len(clean):
        return "", "", "Coda 必须是最后一个非空行"
    kind = match.group(1).upper()
    detail = match.group(2).strip()
    compact = re.sub(r"[\s`*_#<>。，、:：;；,.!?！？()（）\[\]-]", "", detail)
    if len(compact) < 4 or re.search(r"<[^>]*>|\b(?:TODO|TBD)\b", detail, re.I):
        return "", "", "Coda 内容为空、过短或仍是占位符"
    vague = re.sub(r"[\s。！!，,；;]", "", detail).lower()
    vague_only = {
        "继续", "继续分析", "继续测试", "继续验证", "继续推进", "按流程继续",
        "处理问题", "执行下一步", "等待", "等待用户", "later", "continue",
    }
    if vague in vague_only:
        return "", "", "Coda 必须写清对象和动作，不能只写泛泛的继续/处理"
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
        return "", "", "Coda 是换一种说法的泛泛继续，仍缺具体对象和动作"
    if len(set(re.findall(r"\bF-\d+\b", detail, re.I))) > 1:
        return "", "", "Coda 只能推进一个 F-id，不能把多个前沿打包"
    if kind != "BLOCKED" and not (_ACTION_RE.search(detail) or _TOOL_RE.search(detail)):
        return "", "", "下一行动必须包含明确的可执行动作"
    if _has_multiple_action_clauses(detail):
        return "", "", "Coda 只能写一个动作，不能把动作清单塞进一行"
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
    try:
        decisions = (run_dir / "decisions.md").read_text(encoding="utf-8", errors="replace")
        loop_complete = bool(re.search(
            r"(?<![A-Z0-9_])(?:GHOST_COMPLETE|NORMAL_COMPLETE)(?![A-Z0-9_])",
            decisions,
        ))
    except Exception:
        pass
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


def _protocol_block_reason(msg: str, run_dir: Path) -> str:
    state = _protocol_state(run_dir)
    if not state:
        return (
            "[输出协议硬拦] 无法解析 active run 状态；先修复/读取 frontier.md，"
            "并以唯一具体的 `下一行动:` 结尾。"
        )
    if state.get("loop_complete"):
        return ""
    active = list(state.get("active_fronts") or [])
    kind, detail, coda_error = _turn_coda(msg)
    if not coda_error and kind == "BLOCKED":
        coda_error = (
            "active run 尚未完成时不能用 BLOCKED 停止；应写一个能推进、"
            "转向、记录外部依赖或形成证据化裁定的下一行动"
        )
    cited_fronts = set(re.findall(r"\bF-\d+\b", detail, re.I))
    if not coda_error and active and cited_fronts and not (cited_fronts & set(active)):
        coda_error = "Coda 引用的 F-id 不属于当前 active 前沿"
    if not coda_error and not active and cited_fronts:
        coda_error = "当前没有 active 前沿，Coda 不得引用不存在的活动 F-id"
    process_anchor = re.search(
        r"(?:check_run|classify_hosts|workers\.py|coverage_matrix\.py|frontier\.md|"
        r"evidence\.md|report\.md|decisions\.md|retrospective\.md|hints\.md|"
        r"surface\.md|conflicts?|冲突|子任务|subagent|Agent Board|分派|复审|"
        r"peer_review|收口|覆盖台账)",
        detail,
        re.I,
    )
    if not coda_error and active and not cited_fronts and not process_anchor:
        coda_error = "存在 active 前沿时，Coda 必须引用一个 active F-id 或明确的控制面对象"
    if not coda_error and not active and not cited_fronts and not process_anchor:
        coda_error = "当前没有 active 前沿，Coda 必须指向明确的收口或控制面对象"
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
        protocol_exempt = turn_mode in {"EXPLAIN_ONLY", "PAUSED_BY_OPERATOR"}

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

        # Find active run and check frontier staleness
        if run_dir is not None:
            frontier = run_dir / "frontier.md"
            claude_md = ROOT / "CLAUDE.md"
            prev_state = SessionStateManager.load(run_dir)
            if _runtime_receipts is None:
                raise RuntimeError("runtime_receipts unavailable")
            unresolved = _runtime_receipts.unresolved_target_denials(
                run_dir,
                session_id=str(event.get("session_id") or ""),
                since=float(contract.get("updated_at") or 0.0),
            )
            denied_claim = _denied_result_claim_reason(
                msg, unresolved, run_dir)
            if denied_claim:
                _emit_gate_violation(denied_claim, stop_hook_active=stop_active)
                sys.exit(0)
            # Reset stale session_state (Decision B-2)
            stale_sec = SESSION_STATE_STALE_SEC
            prev_updated = _valid_ts(prev_state.get("updated_at"), now)
            if prev_updated and now - prev_updated > stale_sec:
                prev_state = {}

            # frontier_stale: frontier.md mtime > 15 min ago (30 min in normal mode)
            _frontier_alerted = 0.0
            frontier_stale_sec = 1800 if is_normal_mode() else 900
            if frontier.exists():
                frontier_mtime = frontier.stat().st_mtime
                if time.time() - frontier_mtime > frontier_stale_sec:
                    # Suppress re-trigger within 10 min of last alert to avoid infinite loop
                    last_alert = prev_state.get("frontier_alerted_at", 0)
                    if time.time() - last_alert > 600:
                        drift_flags.append("frontier_stale")
                        _frontier_alerted = time.time()
            else:
                frontier_mtime = 0.0

            protocol_block = "" if protocol_exempt else _protocol_block_reason(msg, run_dir)

            # ---- Escalation tracking: consecutive drift count ----
            drift_count = _next_drift_count(prev_state, drift_flags)
            drift_started_at = _next_drift_started_at(prev_state, drift_flags, now)

            state = {
                "frontier_mtime": frontier_mtime,
                "claude_mtime": claude_md.stat().st_mtime if claude_md.exists() else 0.0,
                "drift_flags": drift_flags,
                "drift_started_at": drift_started_at,
                "updated_at": now,
                "reread_pending": False,
                "drift_block_count": drift_count,
                "frontier_alerted_at": _frontier_alerted if _frontier_alerted > 0 else prev_state.get("frontier_alerted_at", 0),
            }
            SessionStateManager.save(run_dir, state)
            if protocol_block:
                _emit_gate_violation(protocol_block, stop_hook_active=stop_active)
                sys.exit(0)

        # ---- Drift notification: systemMessage only (no drift_block.json, Decision 2) ----
        if drift_flags:
            normal = is_normal_mode()
            threshold_handoff = 5 if normal else 3
            threshold_reread = 3 if normal else 2
            if drift_count >= threshold_handoff:
                block_msg = (
                    f"[漂移告警 x{drift_count}] 检测到: {', '.join(drift_flags)}。"
                    f"连续 {drift_count} 次违规——建议写 session_handoff.md 后重启新会话。"
                )
            elif drift_count >= threshold_reread:
                block_msg = (
                    f"[漂移告警 x{drift_count}] 检测到: {', '.join(drift_flags)}。"
                    f"重复违规——请 Read CLAUDE.md / WORKFLOW.md / frontier.md 后继续。"
                )
            else:
                block_msg = (
                    f"[漂移告警] 检测到: {', '.join(drift_flags)}。"
                    f"请 Read CLAUDE.md / WORKFLOW.md / frontier.md 后继续。"
                )
            print(json.dumps({"systemMessage": block_msg}, ensure_ascii=False))
            sys.exit(0)

        sys.exit(0)
    except Exception as exc:
        if (run_dir is not None or _active_run_declared()) and turn_mode not in {
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
    denied_receipt = [{"tool_name": "Bash", "target_action": True}]
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
    checks.append(("fixed denial-only envelope is allowed", not bool(
        _denied_result_claim_reason(
            "XUNJI_EXECUTION_STATUS=DENIED\n"
            "未执行目标动作；不存在该动作的实测结果。\n"
            "下一行动: F-001 修复 PreToolUse 前置条件后重试同一动作",
            denied_receipt))))
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
    no_front_denial = (
        "XUNJI_EXECUTION_STATUS=DENIED\n"
        "未执行目标动作；不存在该动作的实测结果。\n"
        "下一行动: frontier.md 修复 PreToolUse 前置条件后重试同一动作"
    )
    checks.append(("no-front denial envelope is accepted by truth gate",
                   not _denied_result_claim_reason(
                       no_front_denial, denied_receipt, closed_run)))
    checks.append(("no-front denial envelope is accepted by Coda gate",
                   _protocol_block_reason(no_front_denial, closed_run) == ""))
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
    (closed_run / "decisions.md").write_text("# Decisions\n\n- GHOST_COMPLETE\n", encoding="utf-8")
    checks.append(("completion marker releases output protocol",
                   _protocol_block_reason("收口检查完成。", closed_run) == ""))
    checks.append(("active front cannot use BLOCKED coda",
                   "不能用 BLOCKED" in _protocol_block_reason("BLOCKED: 等待外部凭据到位", open_run)))
    checks.append(("wrong active front id is rejected",
                   "不属于当前 active" in _protocol_block_reason(
                       "下一行动: F-999 检查另一个入口", open_run)))
    checks.append(("active run requires front id or control-plane object",
                   "必须引用一个 active F-id" in _protocol_block_reason(
                       "下一行动: 检查登录错误页响应差异", open_run)))
    checks.append(("explicit control-plane action may omit front id",
                   _protocol_block_reason("下一行动: 运行 workers.py 分派子任务", open_run) == ""))
    checks.append(("bare Agent token is not a control-plane bypass",
                   "必须引用一个 active F-id" in _protocol_block_reason(
                       "下一行动: 运行 Agent 完成工作", open_run)))
    original_loop_state = globals().get("_loop_state")
    fallback_heading_run = d / "fallback_heading_run"
    fallback_heading_run.mkdir()
    (fallback_heading_run / "frontier.md").write_text(
        "# Frontier\n\n## Front F-002 — login\n- Status: working\n",
        encoding="utf-8",
    )
    (fallback_heading_run / "decisions.md").write_text("# Decisions\n", encoding="utf-8")
    try:
        globals()["_loop_state"] = None
        fallback_state = _protocol_state(open_run)
        fallback_heading_state = _protocol_state(fallback_heading_run)
        fallback_block = _protocol_block_reason("本轮先停在这里。", open_run)
        fallback_pass = _protocol_block_reason("下一行动: F-001 检查登录错误页", open_run)
    finally:
        globals()["_loop_state"] = original_loop_state
    checks.append(("loop_state failure keeps fallback active-front Coda enforcement",
                   fallback_state.get("fallback") is True
                   and fallback_state.get("active_fronts") == ["F-001"]
                   and "输出协议硬拦" in fallback_block
                   and fallback_pass == ""))
    checks.append(("fallback parser accepts labeled F-id headings",
                   fallback_heading_state.get("active_fronts") == ["F-002"]))
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
        "session_id": "s-explain", "updated_at": time.time(),
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
