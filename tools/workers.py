#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""workers.py — 并行 fan-out worker 的脚手架 + 合并状态台账(不是编排器)。

driver 在合适时把若干【互不阻塞、打不同资产】的 front 分给数个 fresh-context 子 agent
并行打(见 docs/templates/worker.md)。每个 worker 只写自己的 workers/W-<id>.md(候选发现),
driver 是唯一整合者: 把候选过【证据门】后并入 evidence.md。本工具只做两件事——

  --new <F-id>   在 runs/<dir>/workers/ 下开一个新的 W-<编号>.md 脚手架(分配下一个编号)
  (默认/--list)  列出所有 worker 文件: Status / 候选数 / 是否 done 但未 merge
  suggest         读取 frontier.md / coverage.json, 给出 fan-out 候选(建议, 非事实)
  plan            生成 worker 分配草案, 由 driver 确认/复制给子 agent
  merge-check     检查 worker candidates 是否缺 Control/Replicated、重复、冲突、未合并

它【不】spawn worker(那是 driver 用 Agent 工具做)、【不】自动写 canonical evidence。
就像 coverage.json 是检视台账, 这是并行工作的台账。check_run.py 复用它报"done 未 merge"。

  python tools/workers.py runs/<dir>
  python tools/workers.py runs/<dir> --new F-005
  python tools/workers.py suggest runs/<dir>
  python tools/workers.py plan runs/<dir> --limit 3
  python tools/workers.py merge-check runs/<dir>
"""
from __future__ import annotations

import argparse
import contextlib
import io
import json
import re
import sys
import tempfile
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8")       # type: ignore[attr-defined]
except Exception:
    pass

ROOT = Path(__file__).resolve().parents[1]
COMMANDS = {"list", "new", "suggest", "plan", "merge-check"}
HWS = r"[^\S\n]"

try:
    import state_project as _state_project
except Exception:
    _state_project = None

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


def workers_dir(run_dir: Path) -> Path:
    return run_dir / "workers"


def resolve_run_dir(path: Path) -> Path:
    run_dir = path if path.is_absolute() else ROOT / path
    return run_dir.resolve()


def display_path(path: Path) -> str:
    try:
        return str(path.relative_to(ROOT))
    except ValueError:
        return str(path)


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
    return raw


def _front_assets(front: dict, assets: list[dict]) -> list[dict]:
    text = front["text"].lower()
    out: list[dict] = []
    for a in assets:
        host = _asset_name(a)
        if host and host.lower() in text:
            out.append(a)
    return out


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
            "score": score,
            "reasons": reasons,
            "cautions": cautions,
            "text": f["text"],
        })
    rows.sort(key=lambda r: (r["score"], bool(r["assets"]), r["front"]), reverse=True)
    return rows[:limit] if limit else rows


def _fanout_verdict(rows: list[dict]) -> tuple[str, list[str]]:
    strong = [r for r in rows if r["score"] >= 3]
    distinct_assets = {a for r in strong for a in r["assets"]}
    distinct_barriers = {r["barrier"] for r in strong if r["barrier"] not in {"", "unknown"}}
    notes = [
        f"strong candidates={len(strong)}",
        f"distinct assets={len(distinct_assets)}",
        f"barrier classes={len(distinct_barriers) or 'mostly none/unknown'}",
    ]
    if len(strong) >= 3 and len(distinct_assets) >= 3:
        return "fan-out recommended", notes
    if len(strong) >= 2 and len(distinct_assets) >= 2:
        return "fan-out optional; driver should weigh rate limit and shared barriers", notes
    return "stay serial for now", notes


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
                ctrl = cand["control"].strip().lower()
                if not ctrl or ctrl in {"-", "n/a", "na", "none", "unknown", "todo"}:
                    issues.append({"severity": "error", "worker": w["file"], "kind": "missing-control",
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
    verdict, notes = _fanout_verdict(rows)
    print(f"[workers suggest] {verdict} ({'; '.join(notes)})")
    print("  note: advisory only; driver chooses. Workers produce candidates, never canonical Facts.")
    print("  driver still weighs live rate limits, shared auth/WAF barriers, and prior worker hit rate.")
    for r in rows:
        rs = "; ".join(r["reasons"][:3]) or "no positive signal"
        cs = (" | cautions: " + "; ".join(r["cautions"][:3])) if r["cautions"] else ""
        assets = ", ".join(r["assets"][:3]) or "?"
        print(f"  {r['front']:6} score={r['score']:>2} assets={assets:24} status={r['status']:12} "
              f"barrier={r['barrier']:18} {rs}{cs}")
    return 0


def print_plan(run_dir: Path, limit: int) -> int:
    rows = [r for r in suggest(run_dir) if r["score"] >= 3]
    if not rows:
        print("[workers plan] 无 strong candidate。先串行推进或补 coverage/frontier 资产映射。")
        return 1
    selected = rows[:limit]
    verdict, notes = _fanout_verdict(rows)
    print(f"[workers plan] draft only: {verdict} ({'; '.join(notes)})")
    if len(selected) < len(rows):
        print(f"Selected {len(selected)} of {len(rows)} strong candidate(s) due to --limit={limit}.")
    print("Driver must confirm before spawning; this tool does not create facts or run agents.\n")
    start = int(next_id(run_dir).split("-", 1)[1])
    for offset, r in enumerate(selected):
        wid = f"W-{start + offset:02d}"
        print(f"## {wid} -> {r['front']}")
        print(f"- Front: {r['title']}")
        print(f"- Assets: {', '.join(r['assets']) if r['assets'] else 'not mapped; driver verify disjoint lane'}")
        print(f"- Worker file: runs/<dir>/workers/{wid}.md")
        print("- Prompt seed:")
        print(f"  You own exactly ONE front: {r['front']} ({r['title']}). "
              "Write candidates only to your worker file; do not touch canonical run files.\n")
    print("Create files with: " + " ; ".join(f"python tools/workers.py runs/<dir> --new {r['front']}" for r in selected))
    return 0


def print_merge_check(run_dir: Path) -> int:
    issues = merge_check(run_dir)
    if not issues:
        print("[workers merge-check] clean: no done-but-unmerged workers or candidate gate issues found.")
        return 0
    print(f"[workers merge-check] {len(issues)} issue(s)")
    rc = 0
    for i in issues:
        sev = i["severity"].upper()
        if i["severity"] == "error":
            rc = 1
        print(f"  {sev:5} {i['kind']:22} {i['detail']}")
    return rc


def _selftest() -> int:
    d = Path(tempfile.mkdtemp())
    run = d / "run"
    run.mkdir()
    empty_run = d / "empty"
    empty_run.mkdir()
    (run / "coverage.json").write_text(json.dumps({"assets": [
        {"host": "a.example", "reachable": True, "flags": ["LOGIN"]},
        {"host": "b.example", "reachable": True, "flags": ["SURFACE:API"]},
        {"host": "c.example", "reachable": True, "flags": ["SURFACE:UPLOAD"]},
        {"host": "d.example", "reachable": False, "flags": []},
    ]}), encoding="utf-8")
    (run / "frontier.md").write_text(
        "# Frontier\n## Open Fronts\n"
        "### F-001\n- Front: a.example auth boundary\n- Status: open\n- Current depth: shallow\n"
        "- Barrier class: none\n- Same barrier failures: 0\n\n"
        "### F-002\n- Front: b.example API params\n- Status: open\n- Current depth: shallow\n"
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
    with contextlib.redirect_stdout(io.StringIO()):
        no_strong_exit = print_plan(no_strong, 3)
        clean_exit = print_merge_check(empty_run)
        legacy_list_exit = main([str(run)])
        legacy_new_exit = main([str(run), "--new", "F-777"])
    checks = [
        ("suggest returns open/probing before bad deferred", rows[0]["front"] in {"F-001", "F-002", "F-003"}),
        ("suggest excludes closed", all(r["front"] != "F-099" for r in rows)),
        ("fanout verdict recommends with 3 mapped fronts", _fanout_verdict(rows[:3])[0] == "fan-out recommended"),
        ("scan sees two done workers", len(unmerged(run)) == 2),
        ("empty run suggest returns []", suggest(empty_run) == []),
        ("plan with no strong candidate exits 1", no_strong_exit == 1),
        ("merge-check clean path exits 0", clean_exit == 0),
        ("created worker scans assigned front", clean_rows and clean_rows[0]["front"] == "F-123"),
        ("field parser does not cross newline on empty value", _field("- Barrier class:\n- Same barrier failures: 1", "Barrier class") == ""),
        ("empty Claim does not swallow next line", any(i["kind"] == "missing-claim" for i in missing_issues)),
        ("empty Control does not swallow following text", any(i["kind"] == "missing-control" for i in missing_issues)),
        ("plan --limit uses full pool verdict source", _fanout_verdict(plan_limited_rows)[0] == "fan-out recommended"),
        ("merge-check catches missing control", any(i["kind"] == "missing-control" for i in issues)),
        ("merge-check catches duplicate candidate", any(i["kind"] == "duplicate-candidate" for i in issues)),
        ("merge-check catches conflicting candidate certainty", any(i["kind"] == "conflicting-candidate" for i in issues)),
        ("merge-check catches done-but-unmerged", any(i["kind"] == "done-but-unmerged" for i in issues)),
        ("legacy main list exits 0", legacy_list_exit == 0),
        ("legacy main --new exits 0", legacy_new_exit == 0),
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
        else:
            ap.add_argument("run_dir", type=Path)
        if cmd in {"suggest", "plan"}:
            ap.add_argument("--limit", type=int, default=(3 if cmd == "plan" else None))
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
        if cmd == "suggest":
            return print_suggest(run_dir, args.limit)
        if cmd == "plan":
            return print_plan(run_dir, args.limit)
        if cmd == "merge-check":
            return print_merge_check(run_dir)

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
        print("  driver: 用 Agent 工具 spawn 一个 general-purpose 子 agent, 喂 docs/templates/worker.md "
              "的 prompt(填 target + 该 front), 让它把候选写进这个文件。")
        return 0

    return print_list(run_dir)


if __name__ == "__main__":
    raise SystemExit(main())
