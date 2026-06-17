#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Stop hook: 收口闸门提醒器 —— 把"收口"从聊天里的口头宣布拉回 run 文件过闸门。

背景(hamastar run 教训): check_run 是 driver 主动跑的结构闸门; 我那次在【聊天里】宣布
"测完了/adequately probed"、却没跑 check_run, 工具链整段没启动 → 覆盖台账缺建 + 假证据
全部静默放行。根因: 闸门被动, 只在 driver 主动调用且 report 写了收口措辞时才硬审。

本 hook 在 Claude 每次停止响应时触发: 若存在【刚刚改动过的、且已写成实质终版报告的】run,
就替 driver 跑一遍 check_run; 没过就【拦一次】(decision=block), 把硬门结果怼回 driver 面前,
逼它去建覆盖台账/补真产物/派独立复审, 而不是就此收工。

与 safety_gate 的根本区别(复审重点):
  - safety_gate 拦【不可逆危害】, 必须 FAIL-CLOSED(读不到事件就拒绝)。
  - run_gate 是【流程提醒】, 不防危害、只防遗漏, 必须 FAIL-OPEN: 自身任何异常(读不到事件 /
    找不到 run / check_run 报错 / 超时)都【静默放行 exit 0】, 绝不因为一个提醒器而卡死会话。
防循环: Claude 因本 hook 续跑后, 下次 Stop 事件带 stop_hook_active=true → 此时只【提示】不再
block(最多拦一次), 避免 block→续→再 block 的死循环。这是 Claude Code 官方推荐的 Stop hook 写法。

Protocol: 读 stdin 的 Stop 事件; 仅在需要时往 stdout 写 {"decision":"block","reason":...}
(拦) 或 {"systemMessage":...}(提示)。其余 exit 0 静默。纯 stdlib。
"""
from __future__ import annotations

import json
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
RUNS = ROOT / "runs"
ACTIVE_WINDOW_SEC = 900   # 只对最近 15 分钟内改动过的 run 介入(= 当前正在做的那个)

sys.path.insert(0, str(ROOT / "tools"))
try:
    import check_run as _cr   # 复用 _report_is_final, 与 check_run 的"是否终版"判定一致
except Exception:
    _cr = None


def find_active_run(runs_root: Path, within_sec: int = ACTIVE_WINDOW_SEC) -> Path | None:
    """最近写过 report.md 的 run 目录。只看 runs/*/report.md(没 report.md = 还没开始
    收尾 = 本 hook 不该介入), 故只 glob 每 run 一个文件 —— 避免 rglob 整个 runs/ 上千个
    产物拖慢【每一次】会话停止(性能护栏)。超出时间窗 → None。"""
    if not runs_root.is_dir():
        return None
    now = time.time()
    best: Path | None = None
    best_mt = 0.0
    for rpt in runs_root.glob("*/report.md"):
        try:
            mt = rpt.stat().st_mtime
        except Exception:
            continue
        if mt > best_mt:
            best_mt, best = mt, rpt.parent
    if best is not None and (now - best_mt) <= within_sec:
        return best
    return None


def report_is_final(run_dir: Path) -> bool:
    """复用 check_run._report_is_final: report.md 引用了已确认(>=0.8)发现 = 实质终版报告。
    check_run 不可用时返回 False(fail-open: 拿不准就不介入)。"""
    if _cr is None:
        return False
    try:
        return bool(_cr._report_is_final(run_dir))
    except Exception:
        return False


def gate_skipped(run_dir: Path) -> bool:
    """操作者显式豁免: report.md 含 `run-gate: skip` 标记 = 已知此 run 不追求收尾(教学样本 /
    egress-deferred 中止), Stop hook 不再主动提醒。**只让提醒器闭嘴, 不豁免 check_run 本身**——
    手动跑 check_run 仍如实 fail, 故不构成绕过硬门的后门(防"标注一下就过闸门"的滥用)。"""
    try:
        return "run-gate: skip" in (run_dir / "report.md").read_text(encoding="utf-8", errors="replace")
    except Exception:
        return False


def run_check(run_dir: Path) -> tuple[int, str]:
    """subprocess 跑 check_run, 返回 (returncode, 合并输出)。隔离执行, 不耦合内部 API。
    check_run 是纯本地静态解析(无网络), 正常 <1s; 30s 上限足够。超时/异常 → 当作放行
    (rc=0): 提醒器绝不让会话停顿超过 30s, 也绝不因 check_run 故障而卡死(fail-open)。"""
    cmd = [sys.executable, str(ROOT / "tools" / "check_run.py"), str(run_dir)]
    try:
        r = subprocess.run(cmd, capture_output=True, encoding="utf-8",
                           errors="replace", timeout=30)
        return r.returncode, (r.stdout or "") + (r.stderr or "")
    except Exception:
        return 0, ""   # SHOULD-FIX-1: 超时/异常不阻塞会话, 按放行处理


def decide(is_final: bool, check_rc: int, stop_hook_active: bool):
    """纯决策(便于自测): 返回 'block' / 'notify' / None(放行)。
    - 非终版报告 → 放行(还没收尾, 别打扰)。
    - check_run 通过 → 放行。
    - check_run 未过: 首次 → block(拦一次); 已因本 hook 续过(stop_hook_active) → notify(防循环)。"""
    if not is_final:
        return None
    if check_rc == 0:
        return None
    return "notify" if stop_hook_active else "block"


def build_message(run_dir: Path, check_out: str) -> str:
    tail = check_out.strip()
    if len(tail) > 1600:
        tail = tail[-1600:]
    return ("[收口闸门] 你似乎在收尾 runs/" + run_dir.name + ", 但 check_run 未通过。"
            "收口不是在聊天里宣布'测完了', 而是 run 文件过闸门。先处理下面的硬门再收尾"
            "(覆盖台账缺建→跑 ingest_recon+classify_hosts; 假证据→补真产物或降级; "
            "缺独立复审→派 fresh-context reviewer):\n\n" + tail)


def main() -> None:
    if "--selftest" in sys.argv:
        sys.exit(_selftest())
    # FAIL-OPEN 起手: 读不到/解析不了事件就放行(这是提醒器, 不是安全拦截)。
    try:
        raw = sys.stdin.buffer.read()
        event = json.loads(raw.decode("utf-8", "replace") or "{}")
    except Exception:
        sys.exit(0)
    stop_active = bool(event.get("stop_hook_active"))
    try:
        run_dir = find_active_run(RUNS)
        if run_dir is None or not report_is_final(run_dir):
            sys.exit(0)
        if gate_skipped(run_dir):
            sys.exit(0)   # 操作者已认可此 run 不收尾(教学样本/中止) → 不主动提醒
        rc, out = run_check(run_dir)
        mode = decide(True, rc, stop_active)
        if mode is None:
            sys.exit(0)
        msg = build_message(run_dir, out)
        if mode == "block":
            print(json.dumps({"decision": "block", "reason": msg}, ensure_ascii=False))
        else:
            print(json.dumps({"systemMessage": msg}, ensure_ascii=False))
        sys.exit(0)
    except Exception:
        # FAIL-OPEN 兜底: 提醒器自身的任何故障都不得卡死会话。
        sys.exit(0)


def _selftest() -> int:
    import tempfile
    checks: list[tuple[str, bool]] = []
    # decide 真值表
    checks.append(("not final -> pass", decide(False, 1, False) is None))
    checks.append(("final + check pass -> pass", decide(True, 0, False) is None))
    checks.append(("final + check fail -> block", decide(True, 1, False) == "block"))
    checks.append(("final + fail + stop_active -> notify (anti-loop)", decide(True, 1, True) == "notify"))

    d = Path(tempfile.mkdtemp())
    runs = d / "runs"
    runs.mkdir()
    r1 = runs / "a_20260101"
    r1.mkdir()
    (r1 / "report.md").write_text("# Report\n", encoding="utf-8")
    r_norpt = runs / "z_20260101"   # 无 report.md → 还没收尾 → 不该被选
    r_norpt.mkdir()
    (r_norpt / "f.md").write_text("x", encoding="utf-8")
    checks.append(("find_active_run picks run with report.md", find_active_run(runs, within_sec=900) == r1))
    checks.append(("run without report.md ignored", find_active_run(runs, within_sec=900) != r_norpt))
    checks.append(("stale run -> none", find_active_run(runs, within_sec=-1) is None))
    checks.append(("no runs dir -> none", find_active_run(d / "nope") is None))

    # report_is_final via check_run import (终版 vs 存根)
    if _cr is not None:
        rd = runs / "b_20260101"
        rd.mkdir()
        (rd / "ev.html").write_text("x" * 10, encoding="utf-8")
        (rd / "evidence.md").write_text(
            "# Evidence Ledger\n## E-001\n- Replicated: y\n- Artifacts: `ev.html`\n- Certainty: 1.0\n",
            encoding="utf-8")
        (rd / "report.md").write_text("# Report\nEvidence IDs: E-001\n", encoding="utf-8")
        rd2 = runs / "c_20260101"
        rd2.mkdir()
        (rd2 / "report.md").write_text("# Report\nEvidence IDs:\n", encoding="utf-8")
        checks.append(("report_is_final TRUE on confirmed report", report_is_final(rd) is True))
        checks.append(("report_is_final FALSE on stub", report_is_final(rd2) is False))
        rd3 = runs / "d_20260101"
        rd3.mkdir()
        (rd3 / "report.md").write_text(
            "# Report\nEvidence IDs: E-001\n<!-- run-gate: skip (teaching sample) -->\n", encoding="utf-8")
        checks.append(("gate_skipped TRUE on skip marker", gate_skipped(rd3) is True))
        checks.append(("gate_skipped FALSE without marker", gate_skipped(rd) is False))
    else:
        print("[selftest] WARN: check_run not importable; skipped report_is_final checks", file=sys.stderr)

    bad = [n for n, ok in checks if not ok]
    # 输出到 stderr(与 safety_gate 一致): SessionStart 接线时不刷 context, 手动跑仍可见。
    for n, ok in checks:
        print(("ok   " if ok else "FAIL ") + n, file=sys.stderr)
    print("run_gate selftest " + ("passed" if not bad else f"FAILED ({len(bad)})"), file=sys.stderr)
    return 0 if not bad else 1


if __name__ == "__main__":
    main()
