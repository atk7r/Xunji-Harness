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
import re
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
RUNS = ROOT / "runs"
SESSION_STATE_STALE_SEC = 50 * 60  # session timeout 50 min
INVISIBLE_RE = re.compile(r"[​‌‍⁠﻿ ]")
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


def _tail_has_proper_close(msg: str) -> bool:
    """Check if the tail (last 500 chars) ends with proper protocol close:
    '下一行动:' / 'BLOCKED:' (allow trailing whitespace)."""
    if not msg:
        return False
    tail = msg[-500:] if len(msg) > 500 else msg
    # Strip trailing whitespace and zero-width chars for comparison
    tail_clean = _strip_invisible(tail).rstrip()
    return bool(re.search(r'(下一行动\s*:.*|BLOCKED\s*:.*)$', tail_clean, re.IGNORECASE))


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


def main() -> None:
    if "--selftest" in sys.argv:
        sys.exit(_selftest())

    # FAIL-OPEN for parse errors: 读不到事件不是安全问题, 不阻断
    try:
        raw = sys.stdin.buffer.read()
        event = json.loads(raw.decode("utf-8", "replace") or "{}")
    except Exception:
        sys.exit(0)

    try:
        msg = event.get("last_assistant_message") or ""
        if not isinstance(msg, str) or not msg.strip():
            sys.exit(0)

        # ---- Drift detection ----
        hits = detect_drift(msg)
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
        if detect_option_list(msg):
            drift_flags.append("option_list")

        # Find active run and check frontier staleness
        run_dir = find_active_run(RUNS)

        if run_dir is not None:
            frontier = run_dir / "frontier.md"
            claude_md = ROOT / "CLAUDE.md"
            prev_state = SessionStateManager.load(run_dir)
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
    except Exception:
        # FAIL-OPEN 兜底: 本 gate 自身任何故障不卡会话
        sys.exit(0)


def _selftest() -> int:
    """Regression tests. Returns 0 if healthy."""
    import tempfile

    checks: list[tuple[str, bool]] = []

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

    bad = [n for n, ok in checks if not ok]
    for n, ok in checks:
        print(("ok   " if ok else "FAIL ") + n, file=sys.stderr)
    print("output_gate selftest " + ("passed" if not bad else f"FAILED ({len(bad)})"), file=sys.stderr)
    return 0 if not bad else 1


if __name__ == "__main__":
    main()
