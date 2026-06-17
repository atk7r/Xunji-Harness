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

用法:
  python tools/bench.py score <run_dir> <truth.json>
  python tools/bench.py score-all bench/        # 跑 bench/ 下每个 <fixture>/truth.json(各指 run)
  python tools/bench.py --selftest
"""
from __future__ import annotations

import argparse
import json
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

_E_BLOCK = re.compile(r"(?ms)^##\s+(E-\d+).*?(?=^##\s+E-|\Z)")


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
    budget = len(list(run_dir.glob("**/*.replay.json")))
    return {
        "fixture": truth.get("name", run_dir.name),
        "expected": n_exp, "detected": n_det,
        "detection_rate": round(n_det / n_exp, 3) if n_exp else None,
        "calibrated": n_cal, "false_positives": len(fps),
        "confirmed_total": len(blocks),
        "recorded_requests": budget,
        "budget_max": truth.get("budget", {}).get("max_requests"),
        "findings": findings, "fp_detail": fps,
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
          + (f" / {bm} max" if bm else "") + "  (lower bound: only --save'd)")
    for f in s["findings"]:
        mark = "✓" if f["detected"] else "✗"
        cal = "" if not f["detected"] else (
            f" cert={f['got_certainty']}≥{f['min_certainty']}" if f["calibrated"]
            else f" ⚠ cert={f['got_certainty']}<{f['min_certainty']} (欠证)")
        eid = f" [{f['matched_eid']}]" if f["matched_eid"] else ""
        print(f"    {mark} {f['id']}{eid}{cal}")
    for fp in s["fp_detail"]:
        print(f"    ✗ FALSE-POSITIVE: trap '{fp['trap']}' 被确认条目 {fp['flagged_eid']} 命中")


def _is_clean(s: dict) -> bool:
    """完美 = 全检出 + 全校准 + 零误报。用作退出码(回归/门)。"""
    return (s["expected"] > 0 and s["detected"] == s["expected"]
            and s["calibrated"] == s["expected"] and s["false_positives"] == 0)


def _load_truth(p: Path) -> dict:
    return json.loads(p.read_text(encoding="utf-8"))


def main() -> int:
    ap = argparse.ArgumentParser(description="R-1 自评 harness: 对 run 产物按 fixture 真值打分")
    sub = ap.add_subparsers(dest="cmd")
    sp = sub.add_parser("score", help="给单个 run 对照 truth.json 打分")
    sp.add_argument("run_dir", type=Path)
    sp.add_argument("truth", type=Path)
    sa = sub.add_parser("score-all", help="跑 bench/ 下每个 <fixture>/truth.json(truth 内 run 字段指 run)")
    sa.add_argument("bench_dir", type=Path, nargs="?", default=ROOT / "bench")
    ap.add_argument("--selftest", action="store_true")
    args = ap.parse_args()

    if args.selftest:
        return _selftest()
    if args.cmd == "score":
        rd = args.run_dir if args.run_dir.is_absolute() else Path.cwd() / args.run_dir
        s = score(rd, _load_truth(args.truth))
        _print_card(s)
        return 0 if _is_clean(s) else 1
    if args.cmd == "score-all":
        bdir = args.bench_dir
        truths = sorted(bdir.glob("*/truth.json"))
        if not truths:
            print(f"(无 fixture: {bdir}/*/truth.json)")
            return 0
        worst = 0
        for tp in truths:
            truth = _load_truth(tp)
            run_rel = truth.get("run")
            if not run_rel:
                print(f"[skip] {tp.parent.name}: truth.json 无 'run' 字段(指向待评 run 目录)")
                continue
            rd = (tp.parent / run_rel).resolve()
            s = score(rd, truth)
            _print_card(s)
            worst = max(worst, 0 if _is_clean(s) else 1)
        return worst
    ap.print_help()
    return 2


def _selftest() -> int:
    import tempfile
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
    # 欠证: 期望 1.0 但只给 0.8
    s3 = score(run2, {"name": "undercert", "expected_findings": [
        {"id": "sqli", "markers": ["sql injection"], "min_certainty": 1.0},
        {"id": "xss", "markers": ["reflected xss"], "min_certainty": 1.0}]})
    checks.append(("欠证: xss 0.9<1.0 -> detected 但非 calibrated",
                   s3["findings"][1]["detected"] and not s3["findings"][1]["calibrated"]))

    bad = [n for n, ok in checks if not ok]
    for n, ok in checks:
        print(("ok   " if ok else "FAIL ") + n)
    print("bench selftest " + ("passed" if not bad else f"FAILED ({len(bad)})"))
    return 0 if not bad else 1


if __name__ == "__main__":
    raise SystemExit(main())
