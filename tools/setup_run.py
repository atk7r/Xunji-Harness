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
            "false_positive.md", "decisions.md", "review.md", "report.md"]

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


def ingest(recon_path: Path, run_dir: Path) -> str:
    """import ingest_recon.render 折全量资产到 surface_recon.md(纯函数, 无网络)。"""
    import ingest_recon
    recon = json.loads(recon_path.read_text(encoding="utf-8"))
    md = ingest_recon.render(recon, str(recon_path))
    (run_dir / "surface_recon.md").write_text(md, encoding="utf-8")
    n = len(recon.get("assets", [])) if isinstance(recon, dict) else 0
    return f"surface_recon.md ({n} assets)"


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
    else:
        record_recon(run_dir, "none")
        print("[setup] 无 recon: 自行填 target.md 范围。")

    if recon_ok and args.classify:
        print("[setup] 跑 classify_hosts(实时探测建 coverage.json)...")
        cmd = [sys.executable, str(ROOT / "tools" / "classify_hosts.py"), str(rp),
               "--out", str(run_dir / "classify")]
        r = subprocess.run(cmd, capture_output=True, encoding="utf-8", errors="replace")
        sys.stdout.write(r.stdout or "")
        if r.stderr:
            sys.stderr.write(r.stderr)
    elif recon_ok:
        print("[下一步] 主动侦察建覆盖台账(check_run 收口硬门要 coverage.json):")
        print(f"         python tools/classify_hosts.py {rp} --out {run_dir / 'classify'}")

    print(f"[下一步] 每轮收尾跑: python tools/check_run.py runs/{run_dir.name}")
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
        ("9 required files copied", all((rd / n).exists() for n in REQUIRED)),
        ("evidence/ subdir", (rd / "evidence").is_dir() and (rd / "evidence" / ".gitkeep").exists()),
        ("scripts/ subdir", (rd / "scripts").is_dir()),
        ("frontier template has depth field", "Current depth" in (rd / "frontier.md").read_text(encoding="utf-8")),
        ("no-overwrite guard raises", _raises_exist(rd)),
    ]
    recon = {"target": "t", "assets": [{"host": "a.example", "category": "c", "reachability": "confirmed"}]}
    rp = d / "recon.json"
    rp.write_text(json.dumps(recon), encoding="utf-8")
    record_recon(rd, str(rp))
    info = ingest(rp, rd)
    tgt = (rd / "target.md").read_text(encoding="utf-8")
    checks += [
        ("target.md records recon path", str(rp) in tgt),
        ("recon path with backslashes intact (no re.sub group bug)", "\\1" not in tgt),
        ("surface_recon.md written w/ asset", (rd / "surface_recon.md").exists()
            and "a.example" in (rd / "surface_recon.md").read_text(encoding="utf-8")),
        ("ingest reports asset count", "1 assets" in info),
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
