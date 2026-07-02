#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""setup_run.py — 一键初始化一个授权目标的 run 工作台。

机械化 WORKFLOW.md「Ingest Existing Intelligence First」+ Repository Discipline:
从 docs/templates/run/ 建齐 run 骨架 + evidence/ scripts/ 子目录, 给了 recon 就用
ingest_recon 折【全量】资产到 surface_recon.md, 并在 target.md 记录 recon 路径。

它专治 hamastar run 的根因: 当时手工誊录了 ~16 个资产进 surface.md(把 driver 的
选择偏见当成 run 的事实地面), 跳过了 ingest_recon/classify_hosts → 30+ 资产漏挖。
一键起手就杜绝"手工挑子集"的诱惑。

coverage.json 由 classify_hosts 产出, 而 classify 是【实时探测 = 主动侦察】, 不该在
setup 阶段静默自动发包 —— 默认只打印下一步命令; 加 --classify 才在授权 OK 时顺带跑。

它只【备好工作台】, 不选 front / 不做攻击判断 —— 派生不驱动, 绝非编排器。

  python tools/setup_run.py <slug> [recon.json] [--date YYYYMMDD] [--classify]
  python tools/setup_run.py --selftest
"""
from __future__ import annotations

import argparse
import datetime
import json
import re
import shutil
import subprocess
import sys
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8")       # type: ignore[attr-defined]
except Exception:
    pass

ROOT = Path(__file__).resolve().parents[1]
TPL = ROOT / "docs" / "templates" / "run"
REQUIRED = ["target.md", "surface.md", "frontier.md", "hypotheses.md", "evidence.md",
            "false_positive.md", "decisions.md", "review.md", "report.md",
            # 强制复盘: 收口硬门(check_run.check_retrospective)要求收口时填好两节真实内容。
            # 这里只铺模板占位(有 H1), 占位本身不算填 —— 收口前 driver 必须把两节写实。
            "retrospective.md"]

sys.path.insert(0, str(Path(__file__).resolve().parent))


def _today() -> str:
    return datetime.date.today().strftime("%Y%m%d")


def scaffold(run_dir: Path) -> list[str]:
    """从模板建齐必需文件 + evidence/ scripts/ 子目录(含 .gitkeep)。不覆盖已存在目录。"""
    run_dir.mkdir(parents=True, exist_ok=False)   # exist_ok=False → 已存在则 FileExistsError
    made: list[str] = []
    for name in REQUIRED:
        src = TPL / name
        dst = run_dir / name
        if src.exists():
            shutil.copyfile(src, dst)
        else:   # 模板缺失也给个带 H1 的占位, 至少满足 check_run 的 '# X' marker
            dst.write_text(f"# {name[:-3].replace('_', ' ').title()}\n", encoding="utf-8")
        made.append(name)
    for sub in ("evidence", "scripts"):
        d = run_dir / sub
        d.mkdir(exist_ok=True)
        (d / ".gitkeep").write_text("", encoding="utf-8")
    return made


def record_recon(run_dir: Path, value: str) -> None:
    """在 target.md 的『Existing intel / recon report:』字段写入 value(recon 路径或 'none')。
    用 lambda 替换避免 Windows 路径里的反斜杠被 re.sub 当成组引用(\\1 之类)。"""
    t = run_dir / "target.md"
    txt = t.read_text(encoding="utf-8", errors="replace")
    new = re.sub(r"(- Existing intel / recon report:).*",
                 lambda m: f"{m.group(1)} {value}", txt, count=1)
    t.write_text(new, encoding="utf-8")


def record_scope(run_dir: Path, recon_path: Path) -> str:
    """从 recon 的 ownership 派生默认 scope, 填进 target.md 的 Target/In-scope/Out-of-scope
    (现在这些字段 setup 留空 = scope 脊梁缺失, mokwon dogfood 实测的头号问题)。派生不驱动:
    写的是默认, driver 可改 target.md(scope.py parse_target_scope 是源)。"""
    import scope as _scope
    recon = json.loads(recon_path.read_text(encoding="utf-8"))
    sc = _scope.derive_scope(recon)
    in_line, out_line = _scope.render_scope_lines(sc)
    t = run_dir / "target.md"
    txt = t.read_text(encoding="utf-8", errors="replace")

    def setfield(s: str, name: str, val: str) -> str:           # lambda 替换避免反斜杠组引用 bug
        return re.sub(rf"(- {re.escape(name)}:).*", lambda m: f"{m.group(1)} {val}", s, count=1)

    if sc["target"]:
        txt = setfield(txt, "Target", sc["target"])
    if in_line:
        txt = setfield(txt, "In-scope assets", in_line)
    if out_line:
        txt = setfield(txt, "Out-of-scope assets", out_line)
    if sc["notes"]:
        prefix = ("⚠ scope 启发式(recon 无 ownership), 归属待裁: " if sc.get("heuristic")
                  else "scope 复核(secondary/第三方托管): ")
        note = prefix + "; ".join(f"{h}" for h, _ in sc["notes"][:6])
        txt = setfield(txt, "Notes", note)
    t.write_text(txt, encoding="utf-8")
    tag = " ⚠启发式(无 ownership, 务必复核 target.md In/Out-of-scope)" if sc.get("heuristic") else ""
    return f"scope 派生 → {len(sc['in'])} in-模式 / {len(sc['out'])} out / {len(sc['notes'])} 复核{tag}"


def ingest(recon_path: Path, run_dir: Path) -> str:
    """import ingest_recon.render 折全量资产到 surface_recon.md(纯函数, 无网络)。"""
    import ingest_recon
    recon = json.loads(recon_path.read_text(encoding="utf-8"))
    md = ingest_recon.render(recon, str(recon_path))
    (run_dir / "surface_recon.md").write_text(md, encoding="utf-8")
    n = len(recon.get("assets", [])) if isinstance(recon, dict) else 0
    return f"surface_recon.md ({n} assets)"


def adapt_coverage(recon_path: Path, run_dir: Path) -> str:
    """轴 B 适配器: Guanlan 产物 → coverage.json, 【零重探】。Guanlan 已做去重/通配折叠/存活/归属,
    框架不再 classify_hosts 全量重探重建(= re-OSINT 冤枉时间)。取 recon 同目录 report.md 的存活分层。"""
    import ingest_recon
    recon = json.loads(recon_path.read_text(encoding="utf-8"))
    rep = recon_path.parent / "report.md"
    report_md = rep.read_text(encoding="utf-8", errors="replace") if rep.exists() else None
    cov = ingest_recon.build_coverage(recon, report_md)
    out = run_dir / "classify"
    out.mkdir(parents=True, exist_ok=True)
    (out / "coverage.json").write_text(json.dumps(cov, ensure_ascii=False, indent=2), encoding="utf-8")
    src = "含 report.md 存活分层" if report_md else "无 report.md → 可达性留 unknown(渗透时定)"
    return f"coverage.json ({cov['total']} 资产 / {cov['reachable']} 已确认可达, {src})"


def _parse_frontmatter_signatures(text: str) -> list[str]:
    """纯 stdlib 从 Markdown frontmatter 中提取 signatures 列表。
    不使用 pyyaml(retrospective B1: 依赖未安装导致 knowledge_match 静默失败)。"""
    m = re.match(r"^---[ \t]*\r?\n(.*?)\r?\n---", text, re.S)
    if not m:
        return []
    fm_text = m.group(1)
    # 提取 signatures: [...] 行 — 先试单行格式(更常见), 再试多行缩进列表
    sig_line = re.search(r"(?m)^signatures\s*:\s*\[(.*?)\]", fm_text)
    if sig_line:
        return [s.strip().strip("'\"") for s in sig_line.group(1).split(",") if s.strip()]
    sig_block = re.search(r"(?m)^signatures\s*:\s*\r?\n((?:\s+-\s+[^\n]+\r?\n?)+)", fm_text)
    if sig_block:
        sigs = []
        for item in re.finditer(r"-\s+(.+?)(?:\r?\n|$)", sig_block.group(1)):
            val = item.group(1).strip().strip("'\"").rstrip(",")
            if val:
                sigs.append(val)
        return sigs
    return []


def _sig_matches(signature: str, haystack: str) -> bool:
    """检查签名是否在 haystack 中匹配。支持 glob 前缀:
    `*.suffix` → haystack 中以 .suffix 结尾; 否则 → 子串匹配。"""
    if not signature:
        return False
    if signature.startswith("*"):
        suffix = signature[1:]
        return haystack.find(suffix) >= 0
    return signature in haystack


def knowledge_match(run_dir: Path) -> str:
    """从 surface_recon.md 或 coverage.json 中提取产品指纹, 匹配 knowledge/*.md 签名,
    生成 knowledge_hits.md — 让 driver 在 Reason pass 时自然读到匹配的 knowledge 条目,
    避免跳过本地知识库直接用 WebSearch(retrospective #3/#14/#15)。
    纯 stdlib, 无外部依赖(retrospective B1: pyyaml 未安装导致静默失败)。"""
    knowledge_dir = ROOT / "knowledge"
    if not knowledge_dir.is_dir():
        return "knowledge/ 目录不存在 — 跳过签名匹配"

    # 1. 加载所有 knowledge/*.md 的 frontmatter (signatures + id)
    entries: list[dict] = []
    for kf in sorted(knowledge_dir.glob("*.md")):
        if kf.name.startswith("_") or kf.name == "README.md":
            continue
        text = kf.read_text(encoding="utf-8", errors="replace")
        fm: dict = {}
        # 提取所有 frontmatter 键值对(纯 stdlib regex, 不依赖 pyyaml)
        m = re.match(r"^---[ \t]*\r?\n(.*?)\r?\n---", text, re.S)
        if m:
            fm_text = m.group(1)
            for key in ("id", "product", "vendor", "category", "maturity"):
                kv = re.search(rf"(?m)^{key}\s*:\s*(.+?)\s*$", fm_text)
                if kv:
                    fm[key] = kv.group(1).strip().strip("'\"")
        sigs = _parse_frontmatter_signatures(text)
        if sigs:
            entries.append({
                "file": f"knowledge/{kf.name}",
                "id": fm.get("id", kf.stem),
                "product": fm.get("product", kf.stem),
                "vendor": fm.get("vendor", ""),
                "category": fm.get("category", ""),
                "maturity": fm.get("maturity", "unknown"),
                "signatures": sigs,
            })

    if not entries:
        return "knowledge/ 无可匹配条目 — 跳过签名匹配"

    # 2. 从 surface_recon.md 和 coverage.json 提取文本
    haystack = ""
    for fname in ("surface_recon.md", "surface.md"):
        p = run_dir / fname
        if p.exists():
            haystack += "\n" + p.read_text(encoding="utf-8", errors="replace")
    cov_path = run_dir / "classify" / "coverage.json"
    if cov_path.exists():
        try:
            cov = json.loads(cov_path.read_text(encoding="utf-8", errors="replace"))
            for a in cov.get("assets", []):
                haystack += "\n" + str(a.get("host", "")) + " " + str(a.get("title", ""))
                haystack += " " + str(a.get("stack", "")) + " " + " ".join(str(a.get("flags", [])))
        except Exception:
            pass

    # 3. 匹配签名(支持 glob 前缀)
    matches: list[dict] = []
    seen: set[str] = set()
    for e in entries:
        for sig in e["signatures"]:
            if _sig_matches(sig, haystack):
                if e["id"] not in seen:
                    seen.add(e["id"])
                    matches.append(e)
                break

    # 4. 生成 knowledge_hits.md
    out = run_dir / "knowledge_hits.md"
    if matches:
        lines = [
            "# Knowledge Hits (签名自动匹配)",
            "",
            f"setup_run 从 {len(entries)} 个 knowledge 条目中匹配到 {len(matches)} 个签名命中:",
            "",
        ]
        for m_item in matches:
            lines.append(f"## {m_item['id']}")
            lines.append(f"- Product: {m_item['product']}")
            if m_item['vendor']:
                lines.append(f"- Vendor: {m_item['vendor']}")
            lines.append(f"- Category: {m_item['category']} | Maturity: {m_item['maturity']}")
            matched = [s for s in m_item['signatures'] if _sig_matches(s, haystack)]
            lines.append(f"- Signatures matched: {', '.join(matched)}")
            lines.append(f"- File: `{m_item['file']}` ← Read this before WebSearch!")
            lines.append("")
        out.write_text("\n".join(lines), encoding="utf-8")
        return f"knowledge_hits.md ({len(matches)} hits: {', '.join(m['id'] for m in matches)})"
    else:
        out.write_text("# Knowledge Hits\n\n无签名命中 — 未识别到已知产品指纹。\n", encoding="utf-8")
        return "knowledge_hits.md (无命中)"


def _merge_egress_recheck(run_dir):
    """P0: 合并 Guanlan baseline coverage + classify_hosts egress recheck overlay."""
    import json as _json
    cov_path = run_dir / "classify" / "coverage.json"
    egress_path = run_dir / "classify" / "egress_coverage.json"
    if not cov_path.exists() or not egress_path.exists():
        return
    cov = _json.loads(cov_path.read_text(encoding="utf-8"))
    egress = _json.loads(egress_path.read_text(encoding="utf-8"))
    egress_map = {a["host"]: a for a in egress.get("assets", [])}
    for a in cov["assets"]:
        h = a["host"]
        if h in egress_map:
            a["current_egress_reachability"] = egress_map[h].get("reachable")
            if a["current_egress_reachability"] is True:
                a["reachable"] = True
    cov["source"] = "guanlan-baseline + egress-recheck-overlay"
    cov_path.write_text(_json.dumps(cov, ensure_ascii=False, indent=2), encoding="utf-8")


def main() -> int:
    ap = argparse.ArgumentParser(description="初始化授权目标 run 工作台(派生不驱动)")
    ap.add_argument("slug", nargs="?", help="目标短名 → run 目录 runs/<slug>_<date>")
    ap.add_argument("recon", nargs="?", help="recon JSON 路径(可选; 给了就 ingest)")
    ap.add_argument("--date", default=None, help="YYYYMMDD; 默认今天")
    ap.add_argument("--classify", action="store_true",
                    help="顺带跑 classify_hosts 建 coverage.json(实时探测=主动侦察, 需授权)")
    ap.add_argument("--selftest", action="store_true")
    args = ap.parse_args()

    if args.selftest:
        return _selftest()
    if not args.slug:
        ap.error("need <slug> (or --selftest)")

    date = args.date or _today()
    slug = re.sub(r"[^A-Za-z0-9_-]", "_", args.slug)
    run_dir = ROOT / "runs" / f"{slug}_{date}"
    if run_dir.exists():
        print(f"[!] {run_dir} 已存在 —— 不覆盖。换 slug/date 或手动处理。", file=sys.stderr)
        return 1

    made = scaffold(run_dir)
    print(f"[setup] 建 run 骨架 {run_dir}")
    print(f"        {len(made)} 个核心文件 + evidence/ + scripts/")

    recon_ok = False
    if args.recon:
        rp = Path(args.recon)
        if not rp.is_absolute():
            rp = Path.cwd() / rp
        if not rp.exists():
            print(f"[!] recon 不存在: {rp}", file=sys.stderr)
            record_recon(run_dir, "none")
        else:
            recon_ok = True
            record_recon(run_dir, str(rp))
            try:
                info = ingest(rp, run_dir)
                print(f"[setup] ingest_recon → {info}; target.md 已记录 recon 路径")
            except Exception as e:
                print(f"[!] ingest_recon 失败(已记录路径, 请手动 ingest): {e}", file=sys.stderr)
            try:
                sinfo = record_scope(run_dir, rp)
                print(f"[setup] {sinfo} → target.md(派生不驱动, 复核/可改)")
            except Exception as e:
                print(f"[!] scope 派生失败(请手填 target.md In/Out-of-scope): {e}", file=sys.stderr)
            # 轴 B: 默认【零重探】从 Guanlan 产物折 coverage.json(check_run 收口硬门要它)。
            try:
                cinfo = adapt_coverage(rp, run_dir)
                print(f"[setup] Guanlan→coverage(零重探): {cinfo}")
            except Exception as e:
                print(f"[!] coverage 适配失败(可手跑 classify_hosts 兜底): {e}", file=sys.stderr)
            try:
                kinfo = knowledge_match(run_dir)
                print(f"[setup] knowledge 签名匹配: {kinfo}")
            except Exception as e:
                print(f"[!] knowledge 匹配失败(可手查): {e}", file=sys.stderr)
    else:
        record_recon(run_dir, "none")
        print("[setup] 无 recon: 自行填 target.md 范围。")

    if recon_ok and args.classify:
        # P0: classify_hosts 作为 egress_recheck 增量层, 不覆写 Guanlan baseline
        print("[setup] --classify: 跑 classify_hosts 作 egress_recheck 增量...")
        cmd = [sys.executable, str(ROOT / "tools" / "classify_hosts.py"), str(rp),
               "--out", str(run_dir / "classify"), "--egress-recheck"]
        r = subprocess.run(cmd, capture_output=True, encoding="utf-8", errors="replace")
        sys.stdout.write(r.stdout or "")
        if r.stderr:
            sys.stderr.write(r.stderr)
        _merge_egress_recheck(run_dir)

    print(f"[下一步] 直接打可达高价值(coverage 已就位); 每轮收尾跑: python tools/check_run.py runs/{run_dir.name}")
    return 0


def _raises_exist(existing: Path) -> bool:
    try:
        scaffold(existing)
        return False
    except FileExistsError:
        return True
    except Exception:
        return False


def _selftest() -> int:
    """纯本地回归: 骨架齐全 / 子目录 / recon 记录与 ingest / 不覆盖守卫。无网络。"""
    import tempfile
    d = Path(tempfile.mkdtemp())
    rd = d / "t_20260101"
    made = scaffold(rd)
    checks = [
        ("all required files copied", all((rd / n).exists() for n in REQUIRED)),
        ("evidence/ subdir", (rd / "evidence").is_dir() and (rd / "evidence" / ".gitkeep").exists()),
        ("scripts/ subdir", (rd / "scripts").is_dir()),
        ("frontier template has depth field", "Current depth" in (rd / "frontier.md").read_text(encoding="utf-8")),
        ("no-overwrite guard raises", _raises_exist(rd)),
    ]
    recon = {"target": "t", "assets": [{"host": "a.example", "category": "c", "reachability": "confirmed", "ownership": "core"}]}
    rp = d / "recon.json"
    rp.write_text(json.dumps(recon), encoding="utf-8")
    record_recon(rd, str(rp))
    info = ingest(rp, rd)
    sinfo = record_scope(rd, rp)
    tgt = (rd / "target.md").read_text(encoding="utf-8")
    checks += [
        ("target.md records recon path", str(rp) in tgt),
        ("recon path with backslashes intact (no re.sub group bug)", "\\1" not in tgt),
        ("surface_recon.md written w/ asset", (rd / "surface_recon.md").exists()
            and "a.example" in (rd / "surface_recon.md").read_text(encoding="utf-8")),
        ("ingest reports asset count", "1 assets" in info),
        ("scope 派生填进 target.md Target", "- Target: t" in tgt),
        ("scope 派生填进 In-scope assets", "*.a.example" in tgt),
        ("record_scope 报派生计数", "in-模式" in sinfo),
    ]
    # adapt_coverage: Guanlan 产物 → coverage.json(零重探)
    adapt_coverage(rp, rd)
    cov_p = rd / "classify" / "coverage.json"
    cov_j = json.loads(cov_p.read_text(encoding="utf-8")) if cov_p.exists() else {}
    checks += [
        ("adapt_coverage 写 classify/coverage.json", cov_p.exists()),
        ("coverage 含资产 a.example", any(a.get("host") == "a.example" for a in cov_j.get("assets", []))),
        ("coverage examined=0(零重探, 没发包)", cov_j.get("examined") == 0),
        ("coverage source 标 guanlan-adapter", "guanlan" in cov_j.get("source", "")),
    ]
    # no-recon path writes 'none' (avoid template placeholder tripping _recon_cited)
    rd2 = d / "t2_20260101"
    scaffold(rd2)
    record_recon(rd2, "none")
    checks.append(("no-recon target records 'none'",
                   "recon report: none" in (rd2 / "target.md").read_text(encoding="utf-8")))

    bad = [n for n, ok in checks if not ok]
    for n, ok in checks:
        print(("ok   " if ok else "FAIL ") + n)
    print("setup_run selftest " + ("passed" if not bad else f"FAILED ({len(bad)})"))
    return 0 if not bad else 1


if __name__ == "__main__":
    raise SystemExit(main())
