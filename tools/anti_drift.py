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

import sys
import time
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8")       # type: ignore[attr-defined]
except Exception:
    pass

ROOT = Path(__file__).resolve().parents[1]
RUNS = ROOT / "runs"
ACTIVE_WINDOW_SEC = 6 * 3600   # a run that saw any file change in the last 6h = the one in flight

# Binding rules the driver has demonstrably drifted from — kept SHORT (recency-zone budget).
# These mirror the saved memories + the recurring corrections this project has needed.
BINDING_RULES = [
    "中文回答",
    "自主驱动: safe 前沿还在就别停下问(会话长/已解决障碍/选下一类 都不是停止理由)",
    "回合协议: 结尾只允许「下一行动: <具体action>」或「BLOCKED: <外部依赖>」; 禁止 ? / 是否 / 继续还是",
    "消费 Guanlan、跳过不可达; 不重做 OSINT / 不建 egress·relay·重探",
    "证据门: 负面/环境结论也要存盘产物; 先验证再给 ≥0.8; 单一来源/样例模板=≤0.5 · scripts≠证据(replay才有效)",
    "不过度工程(画蛇添足); 能进代码闸门的别写 prose",
    "阶段检查点: Driver/Hunter/Reviewer 每批产出后自动触发 peer_review --into-run, codex BLOCKER 先修再继续",
    "任何代码/文档修改必须经过 codex 复审; codex 必须走专用代理(CODEX_PROXY)",
]

# Output drift patterns — driver response containing any of these = protocol violation.
# Codex review checks for these in review.md; the closure gate hard-blocks unresolved violations.
DRIFT_PATTERNS = [
    "是否继续", "要不要继续", "还是等其他条件", "请指示下一步",
    "需要我继续", "等待用户", "你决定", "需要继续吗",
    "I can continue if", "Should I continue", "wait for",
]


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
        sys.path.insert(0, str(ROOT / "tools"))
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
        sys.path.insert(0, str(ROOT / "tools"))
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


def build_anchor() -> str:
    lines = ["[ANTI-DRIFT ANCHOR — 每回合自检, 漂移=没按下面走]"]
    lines.append("绑定规则: " + " · ".join(BINDING_RULES))
    run = find_active_run(RUNS)
    if run is not None:
        try:
            mt = max((p.stat().st_mtime for p in run.glob("*.md")), default=0)
            age = int((time.time() - mt) / 60)
        except Exception:
            age = -1
        stage = _detect_stage(run)
        lines.append(f"当前 run: {run.name} (最后改动 {age}m 前) | 阶段: {stage}")
        for f in _overdue_steps(run):
            lines.append("  · " + f)
        # Drift alerts — unresolved violations from prior turns
        drift_items = _check_drift_alert(run)
        if drift_items:
            lines.append("  ⚠ 漂移告警(未解决):")
            for d in drift_items:
                lines.append(f"    {d[:120]}")
    return "\n".join(lines)


def _selftest() -> int:
    import tempfile
    checks: list[tuple[str, bool]] = []
    a = build_anchor()
    checks.append(("anchor non-empty", bool(a.strip())))
    checks.append(("anchor carries binding rules", "绑定规则" in a))
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
        print("[ANTI-DRIFT ANCHOR]\n绑定规则: " + " · ".join(BINDING_RULES))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
