#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""knowledge_match.py — 指纹飞轮的【检索端】: 据目标内容命中 knowledge 条目, 把弱点锚吐出来。

闭合 ROADMAP R-5 的最后一步。飞轮原有两端:
  写入端  check_run 收口硬门: 识别到产品必申报 `Fingerprints captured: <产品> → knowledge/<id>.md`
  匹配端  classify_hosts: 目标活内容 match knowledge `signatures:` → 标 stack="kb:<id>"
本工具补【检索端】: 命中后【自动把该条目的 Recognition + Weak-Point Anchors(类别+机理+CVE/CNVD)
+ Verification + References 吐给 driver】, 不必再手动开 .md ——
  目标 → 指纹 → 命中条目 → 自动吐弱点锚 → driver 据此【按目标定制】下一发。

安全边界(过 R-5 的硬 gate, 攻击者非扫描器):
- 只读【公开接地层】`knowledge/*.md`(非递归 → `knowledge/weaponized/` 子目录天然不入); 显式拒读 weaponized。
- 只吐识别签名 + 弱点锚(class+mechanism+CVE), 公开层无 payload/steps(check_knowledge 已强制), 故吐出来天然安全。
- 它是【识别后查阅、按目标适配】的推理输入, 不是预载盲扫清单 —— 落在 cognition「攻击者非扫描器」Allowed 区。

用法:
  python tools/knowledge_match.py --body resp.html     # 拿保存的响应体匹配, 吐命中条目的接地内容
  python tools/knowledge_match.py --body -             # 从 stdin 读 body
  python tools/knowledge_match.py --id spring-boot-actuator   # 直接调某条目(从 kb:<id> 标签来)
  python tools/knowledge_match.py --list               # 列全部接地条目(id/产品/成熟度/签名数)
  python tools/knowledge_match.py --selftest
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
KB = ROOT / "knowledge"
WEAPONIZED = "weaponized"   # 武器化层子目录名 —— 本工具显式不碰

_FM_ID = re.compile(r"^id:\s*(.+?)\s*$", re.M)
_FM_SIG = re.compile(r"^signatures:\s*(\[.*\])\s*$", re.M)
_FM_PRODUCT = re.compile(r"^product:\s*(.+?)\s*$", re.M)
_FM_MATURITY = re.compile(r"^maturity:\s*(.+?)\s*$", re.M)


class Entry:
    __slots__ = ("id", "product", "maturity", "sigs", "path")

    def __init__(self, id, product, maturity, sigs, path):
        self.id = id
        self.product = product
        self.maturity = maturity
        self.sigs = sigs
        self.path = path


def load_entries(kb_dir: Path = KB) -> list:
    """读公开接地层 `*.md`(非递归 → 不含 weaponized/)→ [Entry]。跳过 README/_TEMPLATE。"""
    out: list = []
    if not kb_dir.is_dir():
        return out
    for f in sorted(kb_dir.glob("*.md")):          # 非递归: weaponized/ 子目录天然不入
        if f.name in ("README.md", "_TEMPLATE.md"):
            continue
        if WEAPONIZED in f.parts:                  # 防御纵深: 显式拒任何 weaponized 路径
            continue
        try:
            txt = f.read_text(encoding="utf-8", errors="replace")
        except Exception:
            continue
        parts = txt.split("---", 2)
        fm = parts[1] if len(parts) >= 3 else ""
        idm = _FM_ID.search(fm)
        if not idm:
            continue
        sigm = _FM_SIG.search(fm)
        sigs: list = []
        if sigm:
            try:
                sigs = [str(s).lower() for s in json.loads(sigm.group(1)) if str(s).strip()]
            except Exception:
                sigs = []
        prod = _FM_PRODUCT.search(fm)
        mat = _FM_MATURITY.search(fm)
        out.append(Entry(idm.group(1).strip(),
                         prod.group(1).strip() if prod else idm.group(1).strip(),
                         mat.group(1).strip() if mat else "?",
                         sigs, f))
    return out


def grounding_body(path: Path) -> str:
    """frontmatter + 起始 HTML 注释之后的正文 = 公开接地内容(公开层无 payload, check_knowledge 保证)。"""
    txt = path.read_text(encoding="utf-8", errors="replace")
    parts = txt.split("---", 2)
    body = parts[2] if len(parts) >= 3 else txt
    body = re.sub(r"^\s*<!--.*?-->\s*", "", body, flags=re.S)   # 去掉开头的 grounding 提示注释
    return body.strip()


def match_body(body_text: str, kb_dir: Path = KB) -> list:
    """目标 body → 命中条目, 按命中签名数降序。返回 [(Entry, [matched_sigs])]。子串匹配(小写)。"""
    low = body_text.lower()
    hits: list = []
    for e in load_entries(kb_dir):
        matched = [s for s in e.sigs if s in low]
        if matched:
            hits.append((e, matched))
    hits.sort(key=lambda x: -len(x[1]))
    return hits


def _print_entry(e: Entry, matched: "list | None" = None) -> None:
    print("=" * 72)
    print(f"  {e.product}  (id: {e.id} · maturity: {e.maturity})")
    if matched is not None:
        print(f"  命中签名 {len(matched)}/{len(e.sigs)}: {', '.join(matched)}")
    print("=" * 72)
    print(grounding_body(e.path))
    print()


def main() -> int:
    ap = argparse.ArgumentParser(description="指纹飞轮检索端: 据目标命中 knowledge 条目并吐弱点锚(只读公开接地层)")
    ap.add_argument("--body", help="保存的响应体文件路径(或 - 从 stdin 读)做指纹匹配")
    ap.add_argument("--id", help="直接调某条目的接地内容(从 classify 的 kb:<id> 标签来)")
    ap.add_argument("--list", action="store_true", help="列全部接地条目")
    ap.add_argument("--kb", default=None, help="knowledge 目录(默认仓库 knowledge/; 仅测试用)")
    ap.add_argument("--selftest", action="store_true")
    args = ap.parse_args()

    if args.selftest:
        return _selftest()
    kb_dir = Path(args.kb) if args.kb else KB

    if args.list:
        ents = load_entries(kb_dir)
        if not ents:
            print(f"(无接地条目: {kb_dir}/*.md)")
            return 0
        for e in ents:
            print(f"  {e.id:28} {e.maturity:9} sigs={len(e.sigs):<2} {e.product}")
        print(f"\n共 {len(ents)} 条接地条目。")
        return 0

    if args.id:
        ents = {e.id: e for e in load_entries(kb_dir)}
        e = ents.get(args.id) or ents.get(args.id.replace("kb:", ""))   # 容忍 kb:<id> 写法
        if not e:
            print(f"[未命中] knowledge 无 id '{args.id}'。`--list` 看现有条目。", file=sys.stderr)
            return 1
        _print_entry(e)
        return 0

    if args.body:
        if args.body == "-":
            body = sys.stdin.read()
        else:
            bp = Path(args.body)
            if not bp.is_absolute():
                bp = Path.cwd() / bp
            if not bp.exists():
                print(f"[错误] body 文件不存在: {bp}", file=sys.stderr)
                return 1
            body = bp.read_text(encoding="utf-8", errors="replace")
        hits = match_body(body, kb_dir)
        if not hits:
            print("[无命中] 目标内容未匹配任何【已入库】指纹。")
            print("         识别出新产品? 顺手写回飞轮(别等收口): "
                  "python tools/knowledge_seed.py <id> --product <名> --from-body <本响应体>")
            print("         收口时在 report 申报 Fingerprints captured, 飞轮下次自动认。")
            return 0
        print(f"[命中 {len(hits)} 条] 据目标指纹检索到以下接地条目(按目标定制利用, 勿盲跑):\n")
        for e, matched in hits:
            _print_entry(e, matched)
        return 0

    ap.print_help()
    return 2


def _selftest() -> int:
    import tempfile
    d = Path(tempfile.mkdtemp())
    kb = d / "knowledge"
    (kb / WEAPONIZED).mkdir(parents=True)
    # 公开接地条目
    (kb / "foobar-cms.md").write_text(
        "---\nid: foobar-cms\nproduct: FooBar CMS\nmaturity: seed\n"
        'signatures: ["foobar-cms", "/fb/login.do", "powered by foobar"]\n---\n\n'
        "<!-- grounding, not a weapon -->\n\n"
        "## Recognition (identification only)\n- Signature: `/fb/login.do` present.\n\n"
        "## Weak-Point Anchors (variant-analysis input — NOT exploit steps)\n"
        "- Anchor: unauth info disclosure (class) via /fb/api — CVE-2099-0001.\n\n"
        "## References\n- CVE-2099-0001\n", encoding="utf-8")
    # 武器化层(必须被排除)
    (kb / WEAPONIZED / "foobar-exploit.md").write_text(
        "---\nid: foobar-weap\nsignatures: [\"foobar-cms\"]\n---\nPAYLOAD: nope\n", encoding="utf-8")
    # README/TEMPLATE(必须跳过)
    (kb / "README.md").write_text("# readme\n", encoding="utf-8")
    (kb / "_TEMPLATE.md").write_text("---\nid: tpl\nsignatures: [\"x\"]\n---\n", encoding="utf-8")

    ents = load_entries(kb)
    ids = {e.id for e in ents}
    hits = match_body("<html>welcome, Powered by FooBar, go /FB/Login.do</html>", kb)
    nohit = match_body("<html>totally unrelated page</html>", kb)
    body = grounding_body(kb / "foobar-cms.md")

    checks = [
        ("加载公开条目 foobar-cms", "foobar-cms" in ids),
        ("排除 weaponized/ 子目录条目", "foobar-weap" not in ids),
        ("跳过 README/_TEMPLATE", "tpl" not in ids and len(ents) == 1),
        ("body 命中(大小写不敏感, 多签名)", bool(hits) and hits[0][0].id == "foobar-cms"),
        ("命中报告匹配到的签名(>=2)", len(hits[0][1]) >= 2),
        ("无关 body 不命中", nohit == []),
        ("grounding_body 去掉 frontmatter", "signatures:" not in body and "id: foobar" not in body),
        ("grounding_body 去掉起始 HTML 注释", "grounding, not a weapon" not in body),
        ("grounding_body 保留 Recognition + Anchors + CVE", "Weak-Point Anchors" in body and "CVE-2099-0001" in body),
    ]
    bad = [n for n, ok in checks if not ok]
    for n, ok in checks:
        print(("ok   " if ok else "FAIL ") + n)
    print("knowledge_match selftest " + ("passed" if not bad else f"FAILED ({len(bad)})"))
    return 0 if not bad else 1


if __name__ == "__main__":
    raise SystemExit(main())
