#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Anti-drift anchor — re-injects binding rules + active-run process-state every turn.

Why: standing rules (system prompt / CLAUDE.md / memory) sit in EARLY context and lose attention
weight as the session grows ("Lost in the Middle"; "LLMs Get Lost in Multi-Turn Conversation").
The operator kept having to remind the driver of both GOAL and PROCESS. This runs as a
UserPromptSubmit hook so its output lands in the RECENCY zone every turn — the rules + the run's
overdue process steps are surfaced where attention is high, mechanically, not by the model
remembering and not by the operator reminding.

It is ADVISORY (injects context; never blocks — that stays the deterministic gates safety_gate /
run_gate / check_run). FAIL-OPEN: any error prints the static rules and exits 0; a context
injector must never break a turn. Process-state is DERIVED from the run files (reuse check_run),
not self-reported — a drifted self-report would just re-encode the drift.

Usage:
    python tools/anti_drift.py            # print the anchor (UserPromptSubmit hook target)
    python tools/anti_drift.py --selftest # offline regression
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8")       # type: ignore[attr-defined]
except Exception:
    pass

ROOT = Path(__file__).resolve().parents[1]
RUNS = ROOT / "runs"
CONFIG_INI = ROOT / "config.ini"
CONFIG_EXAMPLE_INI = ROOT / "config.example.ini"
ACTIVE_WINDOW_SEC = 6 * 3600   # a run that saw any file change in the last 6h = the one in flight
SESSION_STATE_STALE_SEC = 50 * 60  # session_state.json stale threshold for normal/dev mode
SESSION_STATE_STALE_GHOST_SEC = 120 * 60  # ghost mode: longer threshold

_TOOLS_PATH = str(ROOT / "tools")
if _TOOLS_PATH not in sys.path:
    sys.path.insert(0, _TOOLS_PATH)

# ---- Mode detection (Decision 3: single parse, 5s cache) ----
_mode_cache: tuple[float, str] = (0.0, "normal")


def get_mode() -> str:
    """Read local/example config [mode] once per 5s. Returns 'normal' | 'dev' | 'ghost'."""
    global _mode_cache
    now = time.time()
    if now - _mode_cache[0] < 5.0:
        return _mode_cache[1]
    try:
        import configparser
        cp = configparser.ConfigParser()
        cp.read([str(CONFIG_EXAMPLE_INI), str(CONFIG_INI)], encoding="utf-8")
        mode = cp.get("mode", "mode", fallback="normal").strip().lower()
        if mode not in ("normal", "dev", "ghost"):
            mode = "normal"
        _mode_cache = (now, mode)
        return mode
    except Exception:
        _mode_cache = (now, "normal")
        return "normal"


def is_dev_mode() -> bool:
    return get_mode() == "dev"


def is_ghost_mode() -> bool:
    return get_mode() == "ghost"


def is_normal_mode() -> bool:
    return get_mode() == "normal"

# Binding rules — split into three tiers so primacy/recency work for us, not against us.
# Tier-1 (TOP — "本轮必做"): immediate action rules. Placed first so the model sees them at the
#   highest-attention primacy position every turn.
# Tier-2 (MID — state injected dynamically by build_anchor).
# Tier-3 (BOTTOM — "约束速查"): constraints, format rules, gating. Placed last so they sit in the
#   recency zone as a final check before the model produces output.
BINDING_RULES_TIER1 = [   # TOP: 本轮必做 — placed at primacy position
    "自主驱动: safe 前沿还在就别停下问(会话长/已解决障碍/选下一类 都不是停止理由)",
    "Reason pass: 每轮先重读整个 frontier.md(所有 open+deferred 前沿)再选 — 防隧道视野",
    "回合协议: 结尾只允许「下一行动: <具体action>」或「BLOCKED: <外部依赖>」; 禁止 ? / 是否 / 继续还是",
    "漏洞检索前先跑 timestamp_gate: 每次 WebSearch/WebFetch 查 CVE/CNVD/漏洞前, 必须先 python tools/timestamp_gate.py 获取当前时间, query/URL 必须包含当前年份约束, 严禁凭模型记忆编造未验证年份的 CVE 编号",
]
BINDING_RULES_TIER3 = [   # BOTTOM: 约束速查 — placed at recency position
    "消费 Guanlan、跳过不可达; 不重做 OSINT / 不建 egress·relay·重探",
    "前沿只重排不关闭(关闭是 Reviewer 的事); BLOCKED 先判 A类(可打破) vs B类(关闭/延迟)",
    "证据门: 负面/环境结论也存盘产物; 先验证再给 ≥0.8; 单一来源/样例模板=≤0.5 · scripts≠证据(replay才有效)",
    "阶段检查点: Driver/Hunter/Reviewer 每批产出后自动触发 peer_review --into-run, codex BLOCKER 先修再继续",
    "任何代码/文档修改必须经过 codex 复审; codex 必须走专用代理(CODEX_PROXY)",
    "不过度工程(画蛇添足); 能进代码闸门的别写 prose · 中文回答",
    "引用 CVE 编号前验证其发布年份 ≤ 当前年份; 检索时 query 必须带年份(如 2026); 拿到的 CVE 用 WebFetch 验证 NVD 页面确认发布时间",
]

# Output drift patterns — driver response containing any of these = protocol violation.
# Codex review checks for these in review.md; the closure gate hard-blocks unresolved violations.
DRIFT_PATTERNS = [
    "是否继续", "要不要继续", "还是等其他条件", "请指示下一步",
    "需要我继续", "等待用户", "你决定", "需要继续吗",
    "I can continue if", "Should I continue", "wait for",
]


def _valid_ts(value, now: float) -> float:
    """Validate timestamp: must be float, non-negative, not in future (+60s skew). Returns 0.0 on failure."""
    try:
        ts = float(value)
    except Exception:
        return 0.0
    if ts < 0 or ts > now + 60:
        return 0.0
    return ts


class SessionStateManager:
    """Unified session_state.json read/write — single authority (Decision 2)."""

    @staticmethod
    def load(run_dir: Path) -> dict:
        sf = run_dir / "session_state.json"
        if not sf.exists():
            return {}
        try:
            return json.loads(sf.read_text(encoding="utf-8"))
        except Exception:
            return {}

    @staticmethod
    def save(run_dir: Path, state: dict) -> None:
        state["updated_at"] = time.time()
        sf = run_dir / "session_state.json"
        tmp = sf.with_suffix(".json.tmp")
        try:
            tmp.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
            tmp.replace(sf)
        except Exception:
            pass

    @staticmethod
    def get_drift_flags(run_dir: Path) -> list[str]:
        state = SessionStateManager.load(run_dir)
        flags = state.get("drift_flags", [])
        return flags if isinstance(flags, list) else []

    @staticmethod
    def reset_if_stale(run_dir: Path, hard_block_active: bool = False) -> dict:
        """Auto-reset stale session_state. Returns the state dict (fresh or existing)."""
        state = SessionStateManager.load(run_dir)
        if not state:
            return {}
        drift_flags = SessionStateManager.get_drift_flags(run_dir)
        if not drift_flags:
            return state
        if hard_block_active:
            return state  # never reset while hard-blocked
        updated_at = _valid_ts(state.get("updated_at"), time.time())
        stale_sec = SESSION_STATE_STALE_GHOST_SEC if is_ghost_mode() else SESSION_STATE_STALE_SEC
        if updated_at and time.time() - updated_at > stale_sec:
            state["drift_flags"] = []
            state["reread_pending"] = False
            state["drift_block_count"] = 0
            SessionStateManager.save(run_dir, state)
        return state


def find_active_run(runs_root: Path, within_sec: int = ACTIVE_WINDOW_SEC) -> Path | None:
    """Most recently touched run dir (any *.md changed within the window). Cheap: one glob."""
    if not runs_root.is_dir():
        return None
    best: Path | None = None
    best_mt = 0.0
    now = time.time()
    for md in runs_root.glob("*/*.md"):
        try:
            mt = md.stat().st_mtime
        except Exception:
            continue
        if mt > best_mt:
            best_mt, best = mt, md.parent
    if best is not None and (now - best_mt) <= within_sec:
        return best
    return None


def _detect_stage(run_dir: Path) -> str:
    """Derive current stage from run file state. Uses check_run._report_is_final()
    for closure detection — file existence alone is not enough (setup_run creates templates)."""
    try:
        if _TOOLS_PATH not in sys.path:
            sys.path.insert(0, _TOOLS_PATH)
        import check_run as cr
    except Exception:
        # Fallback: simple heuristic
        frontier = run_dir / "frontier.md"
        if frontier.exists():
            fr = frontier.read_text(encoding="utf-8", errors="replace")
            if "Status: probing" in fr or "Status: open" in fr:
                return "Driver"
        return "Setup"

    review = run_dir / "review.md"
    evidence = run_dir / "evidence.md"
    frontier = run_dir / "frontier.md"

    # Closure: check_run's canonical final-report predicate
    try:
        if cr._report_is_final(run_dir):
            rv = review.read_text(encoding="utf-8", errors="replace") if review.exists() else ""
            if "Independent Review" in rv:
                return "Closure"
            return "Closure-Missing-Review"
    except Exception:
        pass
    # Reviewer: review.md has independent review content (not just the template header)
    if review.exists() and review.stat().st_size > 500:
        rv = review.read_text(encoding="utf-8", errors="replace")
        if "Independent Review" in rv:
            return "Reviewer"
    # Hunter: evidence has confirmed entries (use evidence_parse for accuracy)
    if evidence.exists():
        try:
            recs = cr.parse_evidence(run_dir)
            n_conf = len([r for r in recs if r.get("confirmed")])
            if n_conf > 0:
                return "Hunter"
        except Exception:
            pass
    # Driver: frontier has open/probing fronts
    if frontier.exists():
        fr = frontier.read_text(encoding="utf-8", errors="replace")
        if "Status: probing" in fr or "Status: open" in fr:
            return "Driver"
    return "Setup"

def _check_drift_alert(run_dir: Path) -> list[str]:
    """Check drift_alerts.md for unresolved violations. Returns alert items."""
    alerts = run_dir / "drift_alerts.md"
    if not alerts.exists():
        return []
    try:
        lines = alerts.read_text(encoding="utf-8", errors="replace").splitlines()
        unresolved = [l for l in lines if l.startswith("- [ ]") or l.startswith("PENDING")]
        return unresolved[:5]
    except Exception:
        return []

def _overdue_steps(run_dir: Path) -> list[str]:
    """Derive process/evidence flags from the run files via check_run (no re-parsing). Advisory."""
    flags: list[str] = []
    try:
        if _TOOLS_PATH not in sys.path:
            sys.path.insert(0, _TOOLS_PATH)
        import check_run as cr
    except Exception:
        return flags
    try:
        recs = cr.parse_evidence(run_dir)
        n_ev = len([r for r in recs if r.get("id", "").startswith("E-")])
        n_conf = len([r for r in recs if r.get("id", "").startswith("E-") and r.get("confirmed")])
        # NOTE: the confirmed-without-artifact check (evidence_entries_missing_artifact) does an
        # uncapped rglob — too heavy for a per-prompt hook. It stays enforced by check_run at the
        # closure gate; the anchor only does cheap file-level checks here.
        # coverage health (lite): surface the first warning if any
        try:
            cov = cr.check_coverage_health(run_dir)
            if cov:
                flags.append("覆盖: " + cov[0][:80])
        except Exception:
            pass
        # codex checkpoint (periodic, not just at closure): any >=0.8 confirmed finding without an
        # Independent Review on record = run peer_review now (Verifier-Tax: remind here, the closure
        # gate hard-blocks). Surfaced every turn so the operator does not have to remind.
        try:
            import re as _re
            rvf = run_dir / "review.md"
            evf = run_dir / "evidence.md"
            rv0 = rvf.read_text(encoding="utf-8", errors="replace") if rvf.exists() else ""
            has_review = bool(_re.search(r"Independent Review|独立复审", rv0))
            # fires when there's a confirmed finding AND (no review yet OR evidence changed since the
            # last review) — so a NEW >=0.8 after a prior review re-triggers, not just the first one.
            ev_mt = evf.stat().st_mtime if evf.exists() else 0
            rv_mt = rvf.stat().st_mtime if rvf.exists() else 0
            if n_conf and (not has_review or ev_mt > rv_mt):
                flags.append("codex 检查点 due: ≥0.8 确认且评审未覆盖最新证据 → 跑 peer_review --into-run")
        except Exception:
            pass
        # closure readiness: report final but review/retrospective missing
        try:
            if cr._report_is_final(run_dir):
                rv = (run_dir / "review.md").read_text(encoding="utf-8", errors="replace") \
                    if (run_dir / "review.md").exists() else ""
                import re as _re
                if not _re.search(r"Independent Review|独立复审", rv):
                    flags.append("收口: report 已终版但缺独立复审 → 跑 codex/peer_review")
                retro = run_dir / "retrospective.md"
                if not retro.exists():
                    flags.append("收口: 缺 retrospective.md(强制复盘)")
        except Exception:
            pass
        flags.insert(0, f"evidence {n_ev} 条 / confirmed {n_conf}")
    except Exception:
        pass
    return flags




def build_anchor(
    runs_root: Path = RUNS,
) -> str:
    lines = []

    # ---- Ghost mode: 全自动托管规则 ----
    if is_ghost_mode():
        lines.append("[GHOST MODE — 全自动托管]")
        lines.append("")
        lines.append("【Ghost 自立规则】")
        lines.append("  · 凭据自立: 默认密码→弱口令爆破→注册→用户枚举→密码喷洒, 不等待/不询问")
        lines.append("  · 网络自立: 不可达→先换路径/备选方案再判定; 不建egress·relay(保持边界内)")
        lines.append("  · 决策自立: 不问操作者任何问题, 所有选择自主做出, 记录在 decisions.md")
        lines.append("  · 不因Type B放弃: WAF/限流/超时阻挡→换方法绕过, 不关闭前沿")
        lines.append("  · 收口自立: 完成所有前沿后, 跑 check_run→peer_review→retrospective→标记 FINAL")
        lines.append("")

    lines.append("[ANTI-DRIFT ANCHOR — 每回合自检, 漂移=没按下面走]")
    lines.append("")

    # ---- Phase 1: read session_state.json and inject re-read instructions ----
    run = find_active_run(runs_root)
    drift_flags: list[str] = []
    if run is not None:
        SessionStateManager.reset_if_stale(run)
        drift_flags = SessionStateManager.get_drift_flags(run)

    # Re-read directives based on drift_flags (injected BEFORE Tier-1 for max attention)
    if drift_flags:
        lines.append("⚠ 检测到漂移信号 — 先 Read 对应约束文件后继续:")
        for flag in drift_flags:
            if flag == "frontier_stale":
                lines.append("  · 先 Read frontier.md 然后 EDIT 更新状态(读取不改变 mtime, 必须编辑!)")
            elif flag == "protocol_violation":
                lines.append("  · 先 Read CLAUDE.md — 回合协议违规")
            elif flag == "option_list":
                lines.append("  · 先 Read CLAUDE.md \"自主驱动\"段")
        lines.append("")

    # Tier-1: 本轮必做 (primacy position — highest attention weight)
    lines.append("【本轮必做】")
    for r in BINDING_RULES_TIER1:
        lines.append(f"  · {r}")
    lines.append("")
    # Tier-2: 当前状态 (dynamic — run phase + process flags)
    if run is not None:
        try:
            mt = max((p.stat().st_mtime for p in run.glob("*.md")), default=0)
            age = int((time.time() - mt) / 60)
        except Exception:
            age = -1
        stage = _detect_stage(run)
        lines.append("【当前状态】")
        lines.append(f"  run: {run.name} | 阶段: {stage} | 最后改动: {age}m 前")
        # Ghost complete detection: check decisions.md for GHOST_COMPLETE
        if is_ghost_mode():
            try:
                dc = run / "decisions.md"
                if dc.exists() and "GHOST_COMPLETE" in dc.read_text(encoding="utf-8", errors="replace"):
                    lines.append("  ✅ GHOST_COMPLETE: 所有前沿已完成, run 已自动收口")
                    lines.append("     → 停止: 无剩余工作, 等待操作者确认或关闭会话")
            except Exception:
                pass
        overdue = _overdue_steps(run)
        for f in overdue:
            lines.append(f"  · {f}")
        # 中间闸门(每回合自动跑 —— 不让 AI 忘记 check_run)
        try:
            if _TOOLS_PATH not in sys.path:
                sys.path.insert(0, _TOOLS_PATH)
            import check_run as _cr_gate
            inter_errors, inter_warns = _cr_gate.check_intermediate_gates(run)
            for e in inter_errors[:3]:
                lines.append(f"  ⛔ 中间闸门 HARD FAIL: {e[:130]}")
            for w in inter_warns[:3]:
                lines.append(f"  ⚠ 中间闸门: {w[:130]}")
        except Exception:
            pass
        drift_items = _check_drift_alert(run)
        if drift_items:
            lines.append("  ⚠ 漂移告警(未解决):")
            for d in drift_items:
                lines.append(f"    {d[:120]}")
        lines.append("")
    # Tier-3: 约束速查 (recency position — last thing model sees before producing output)
    lines.append("【约束速查】")
    for r in BINDING_RULES_TIER3:
        lines.append(f"  · {r}")

    # ---- Recency-position output self-check (fires BEFORE model produces output) ----
    if drift_flags:
        lines.append("")
        lines.append("【输出前自检 —— 生成回复前必须逐条确认】")
        if "protocol_violation" in drift_flags:
            lines.append("  □ 结尾是否【仅】为「下一行动: <action>」或「BLOCKED: <reason>」？")
            lines.append("    → 不含 ? ？吗 呢 吧 | 不含 是否/继续/你决定/等待用户/你觉得/怎么看")
        if "frontier_stale" in drift_flags:
            lines.append("  □ 已 Read frontier.md 【并 EDIT 更新】状态了吗？(只读不改 = mtime 不变 = 下轮仍提醒)")
        if "option_list" in drift_flags:
            lines.append("  □ 是否产生了编号选项列表(1.xxx / 2.xxx)把决策抛回给用户？")
            lines.append("    → 如有, 删掉选项, 自主选一个方向, 写成「下一行动:」。")

    return "\n".join(lines)


def _selftest() -> int:
    import tempfile

    # Isolate from real config.ini — selftest always runs in normal mode.
    _orig_is_dev_mode = globals()["is_dev_mode"]
    globals()["is_dev_mode"] = lambda: False
    _orig_is_ghost_mode = globals()["is_ghost_mode"]
    globals()["is_ghost_mode"] = lambda: False

    checks: list[tuple[str, bool]] = []
    a = build_anchor()
    checks.append(("anchor non-empty", bool(a.strip())))
    checks.append(("anchor carries binding rules", "本轮必做" in a and "约束速查" in a))
    checks.append(("anchor is compact (<3KB)", len(a) < 3072))
    # drift patterns list
    checks.append(("drift patterns non-empty", len(DRIFT_PATTERNS) >= 5))
    # find_active_run: picks the most-recent run within window, ignores stale
    d = Path(tempfile.mkdtemp())
    checks.append(("stage Detection exists", _detect_stage(d) == "Setup"))
    runs = d / "runs"
    (runs / "a_x").mkdir(parents=True)
    (runs / "a_x" / "report.md").write_text("# r", encoding="utf-8")
    checks.append(("find_active_run picks recent", find_active_run(runs) == runs / "a_x"))
    checks.append(("stale window -> none", find_active_run(runs, within_sec=-1) is None))
    checks.append(("no runs dir -> none", find_active_run(d / "nope") is None))

    # SessionStateManager tests
    time.sleep(1.1)  # ensure mtime is later than a_x/report.md created above
    rd = runs / "test_session"
    rd.mkdir(parents=True)
    # missing file -> {}
    checks.append(("session_state missing -> {}", SessionStateManager.load(rd) == {}))
    # valid JSON
    (rd / "session_state.json").write_text(
        json.dumps({"drift_flags": ["frontier_stale"], "updated_at": time.time()}), encoding="utf-8")
    st = SessionStateManager.load(rd)
    checks.append(("session_state reads drift_flags", st.get("drift_flags") == ["frontier_stale"]))
    # corrupt JSON -> {}
    (rd / "session_state.json").write_text("not json{{{", encoding="utf-8")
    checks.append(("session_state corrupt -> {}", SessionStateManager.load(rd) == {}))
    # get_drift_flags
    (rd / "session_state.json").write_text(
        json.dumps({"drift_flags": ["protocol_violation"], "updated_at": time.time()}), encoding="utf-8")
    checks.append(("get_drift_flags returns list",
                   SessionStateManager.get_drift_flags(rd) == ["protocol_violation"]))

    # build_anchor with drift_flags — uses temp locations, NOT real project files
    import tempfile as _tm
    _td = Path(_tm.mkdtemp())
    _tmp_runs = _td / "runs"
    _tmp_runs.mkdir()
    test_run = _tmp_runs / "_selftest_drift_test"
    test_run.mkdir(parents=True)
    time.sleep(1.1)  # ensure mtime is fresh
    (test_run / "evidence.md").write_text("# test", encoding="utf-8")
    (test_run / "session_state.json").write_text(
        json.dumps({"drift_flags": ["protocol_violation", "frontier_stale"], "frontier_mtime": 0.0,
                     "claude_mtime": 0.0, "updated_at": time.time()}), encoding="utf-8")
    anchor_with_drift = build_anchor(runs_root=_tmp_runs)
    checks.append(("anchor injects protocol_violation warning",
                   "先 Read CLAUDE.md — 回合协议违规" in anchor_with_drift))
    checks.append(("anchor injects frontier_stale warning",
                   "先 Read frontier.md 然后 EDIT 更新状态" in anchor_with_drift))
    checks.append(("anchor still has Tier-1 rules", "本轮必做" in anchor_with_drift))
    # self-check section present when drift
    checks.append(("anchor has self-check section when drift",
                   "输出前自检" in anchor_with_drift))
    # No drift_block.json referenced in anchor output
    checks.append(("anchor no drift_block reference",
                   "drift_block" not in anchor_with_drift.lower()))

    # Stale session_state auto-reset
    fresh_run = _tmp_runs / "fresh_session"
    fresh_run.mkdir()
    (fresh_run / "evidence.md").write_text("# fresh", encoding="utf-8")
    old_stale = time.time() - SESSION_STATE_STALE_SEC - 120
    (fresh_run / "session_state.json").write_text(
        json.dumps({"drift_flags": ["protocol_violation"], "updated_at": old_stale}), encoding="utf-8")
    anchor_fresh = build_anchor(runs_root=_tmp_runs)
    checks.append(("stale session_state auto-reset",
                   "先 Read CLAUDE.md — 回合协议违规" not in anchor_fresh))

    # Restore original is_dev_mode and is_ghost_mode after selftest
    globals()["is_dev_mode"] = _orig_is_dev_mode
    globals()["is_ghost_mode"] = _orig_is_ghost_mode

    bad = [n for n, ok in checks if not ok]
    for n, ok in checks:
        print(("ok   " if ok else "FAIL ") + n, file=sys.stderr)
    print("anti_drift selftest " + ("passed" if not bad else f"FAILED ({len(bad)})"), file=sys.stderr)
    return 0 if not bad else 1


def main() -> int:
    if "--selftest" in sys.argv:
        return _selftest()
    try:
        print(build_anchor())
    except Exception:
        # FAIL-OPEN: still anchor the static rules; never break a turn.
        print("[ANTI-DRIFT ANCHOR]\n绑定规则: " + " · ".join(BINDING_RULES_TIER1 + BINDING_RULES_TIER3))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
