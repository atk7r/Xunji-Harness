#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""xday_match.py — 飞轮的【xday 本地检索端】: 据目标指纹调出【本地存的】未公开利用。

为什么需要它(操作者思路, 记忆 payload-storage-public-vs-xday):
  公开漏洞 → 锚点 + 上网收集 + 现场造 payload(不用本地囤) → 公开端 knowledge_match 已够。
  xday    → 网上【查不到】payload(就是自己挖的) → 本地 knowledge/weaponized/ + poc_library/xday/
            是【唯一副本】。命中之前打穿过的栈, 必须能调出当初的利用链 —— 否则白挖。
本工具是公开端 knowledge_match 的【镜像对称】: 同一套 signatures 匹配, 但读【本地 xday 库】。

边界(与 knowledge_match 相反但同纪律):
- 它【就是】读本地武器化/xday 层(knowledge/weaponized/ + poc_library/xday/)—— 这两层 gitignore,
  内容【永不入库/不 push】(本工具 .py 入库, 它读的东西不入库)。surface 的是【本地副本路径+元数据】。
- match-gated: 必须 --body 命中【活目标】或显式 --id 才调; --list 只列清单不吐 payload。
  不预载整层当清单盲跑(同 cognition「攻击者非扫描器」: 命中后查、按目标适配)。
- 证明即止/外发脱敏仍归 src-safety-boundary + poc-package skill 管。

用法:
  python tools/xday_match.py --body resp.html    # 目标内容命中 → 调出对应本地 xday
  python tools/xday_match.py --id soarcloud-ais-hr # 按 knowledge id 直调(从 kb:<id> 标签来)
  python tools/xday_match.py --list              # 列本地 xday/weaponized 清单(不吐 payload)
  python tools/xday_match.py --selftest
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8")       # type: ignore[attr-defined]
except Exception:
    pass

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(Path(__file__).resolve().parent))   # tools/  (knowledge_match)
import knowledge_match   # 复用公开签名匹配(weaponized 与公开层共用同一套 signatures)

KB = ROOT / "knowledge"
WEAP = KB / "weaponized"
XDAY = ROOT / "poc_library" / "xday"

_KN_REF = re.compile(r"knowledge/([A-Za-z0-9_-]+)\.md")   # xday README 里指向公开条目的引用
_FM_ID = re.compile(r"^id:\s*(.+?)\s*$", re.M)


def load_local_stores(xday_dir: Path = XDAY, weap_dir: Path = WEAP) -> dict:
    """扫本地 xday 库 → {knowledge_id: [store, ...]}。store = {'kind','path','files'?,'readme'?}。
    poc 目录: 读其 README 里的 `knowledge/<id>.md` 引用作键; weaponized .md: frontmatter id 作键。"""
    index: dict = {}
    # ① poc_library/xday/<dir>/ —— 成品利用(源码+二进制)
    if xday_dir.is_dir():
        for d in sorted(p for p in xday_dir.iterdir() if p.is_dir()):
            readme = d / "README.md"
            kid = None
            if readme.is_file():
                m = _KN_REF.search(readme.read_text(encoding="utf-8", errors="replace"))
                kid = m.group(1) if m else None
            kid = kid or d.name                      # 兜底: 用目录名当键(至少 --id <dir> 调得到)
            files = sorted(f.name for f in d.iterdir() if f.is_file())
            index.setdefault(kid, []).append({"kind": "poc", "path": d, "files": files})
    # ② knowledge/weaponized/*.md —— 武器化笔记/payload/链(与公开层同 signatures)
    if weap_dir.is_dir():
        for f in sorted(weap_dir.glob("*.md")):
            if f.name in ("README.md", "_TEMPLATE.md"):
                continue
            txt = f.read_text(encoding="utf-8", errors="replace")
            parts = txt.split("---", 2)
            fm = parts[1] if len(parts) >= 3 else ""
            m = _FM_ID.search(fm)
            kid = m.group(1).strip() if m else f.stem
            index.setdefault(kid, []).append({"kind": "weaponized", "path": f})
    return index


def match(body_text: str, kb_dir: Path = KB, xday_dir: Path = XDAY,
          weap_dir: Path = WEAP) -> list:
    """目标 body → 公开签名命中 knowledge id → 仅返回【有本地 xday 存货】的 (id, sigs, stores)。"""
    hits = knowledge_match.match_body(body_text, kb_dir)          # [(Entry, matched_sigs)]
    stores = load_local_stores(xday_dir, weap_dir)
    out = []
    for e, sigs in hits:
        if e.id in stores:
            out.append((e.id, sigs, stores[e.id]))
    return out


def _print_stores(kid: str, stores: list, matched_sigs: "list | None" = None) -> None:
    print("=" * 72)
    head = f"  本地 xday: knowledge id `{kid}`"
    if matched_sigs is not None:
        head += f"  (命中签名 {len(matched_sigs)}: {', '.join(matched_sigs)})"
    print(head)
    print("=" * 72)
    for s in stores:
        if s["kind"] == "poc":
            rel = s["path"].relative_to(ROOT)
            print(f"  [成品利用] {rel}/")
            print(f"      文件: {', '.join(s['files'])}")
            readme = s["path"] / "README.md"
            if readme.is_file():
                for ln in readme.read_text(encoding="utf-8", errors="replace").splitlines()[:14]:
                    print(f"      | {ln}")
        else:  # weaponized .md —— 直接吐笔记/链(本地)
            rel = s["path"].relative_to(ROOT)
            print(f"  [武器化笔记] {rel}")
            print(knowledge_match.grounding_body(s["path"]))
    print("  → 本地唯一副本; 按【当前目标】适配后用, 证明即止; 外发走 poc-package(脱敏/混淆二进制)。")
    print()


def main() -> int:
    ap = argparse.ArgumentParser(description="xday 本地检索: 据目标指纹调出本地存的未公开利用(本地库, 不入库)")
    ap.add_argument("--body", help="保存的响应体文件(或 - 从 stdin)做指纹匹配")
    ap.add_argument("--id", help="按 knowledge id 直调本地 xday(从 classify 的 kb:<id> 标签来)")
    ap.add_argument("--list", action="store_true", help="列本地 xday/weaponized 清单(不吐 payload)")
    ap.add_argument("--selftest", action="store_true")
    args = ap.parse_args()

    if args.selftest:
        return _selftest()

    if args.list:
        stores = load_local_stores()
        if not stores:
            print("(本地无 xday/weaponized 存货: poc_library/xday/ 与 knowledge/weaponized/ 均空)")
            return 0
        for kid, items in sorted(stores.items()):
            kinds = ", ".join(f"{s['kind']}:{s['path'].relative_to(ROOT)}" for s in items)
            print(f"  {kid:24} → {kinds}")
        print(f"\n共 {len(stores)} 个栈有本地 xday 存货。(命中后用 --id/--body 调出详情)")
        return 0

    if args.id:
        kid = args.id.replace("kb:", "")
        stores = load_local_stores()
        if kid not in stores:
            print(f"[无本地 xday] knowledge id '{kid}' 没有本地存货。`--list` 看现有。", file=sys.stderr)
            return 1
        _print_stores(kid, stores[kid])
        return 0

    if args.body:
        if args.body == "-":
            body = sys.stdin.read()
        else:
            bp = Path(args.body)
            bp = bp if bp.is_absolute() else Path.cwd() / bp
            if not bp.exists():
                print(f"[错误] body 文件不存在: {bp}", file=sys.stderr)
                return 1
            body = bp.read_text(encoding="utf-8", errors="replace")
        hits = match(body)
        if not hits:
            print("[无本地 xday 命中] 目标指纹未匹配到【有本地存货】的栈。")
            print("  (栈是公开漏洞 → 用 knowledge_match 取锚点 + 上网造; 是新 xday → 打穿后存进 poc_library/xday/ 喂飞轮)")
            return 0
        print(f"[命中 {len(hits)} 个有本地 xday 的栈]:\n")
        for kid, sigs, stores in hits:
            _print_stores(kid, stores, sigs)
        return 0

    ap.print_help()
    return 2


def _selftest() -> int:
    import tempfile
    d = Path(tempfile.mkdtemp())
    kb = d / "knowledge"
    weap = kb / "weaponized"
    xday = d / "poc_library" / "xday"
    weap.mkdir(parents=True)
    xday.mkdir(parents=True)
    # 公开条目(有 signatures, 供匹配)
    (kb / "foobar-cms.md").write_text(
        "---\nid: foobar-cms\nproduct: FooBar CMS\nmaturity: seed\n"
        'signatures: ["foobar-cms", "/fb/login.do"]\n---\n\n## Recognition\n- x\n', encoding="utf-8")
    # 公开条目(无本地 xday, 不该被 xday_match surface)
    (kb / "nostore.md").write_text(
        '---\nid: nostore\nproduct: NoStore\nsignatures: ["nostore-sig"]\n---\n\n## R\n- y\n', encoding="utf-8")
    # 本地 xday 成品(README 指向 knowledge/foobar-cms.md)
    fx = xday / "foobar-rce"
    fx.mkdir()
    (fx / "README.md").write_text("# FooBar RCE xday\n\n| 关联知识 | `knowledge/foobar-cms.md` |\n", encoding="utf-8")
    (fx / "poc.py").write_text("# exploit\n", encoding="utf-8")
    (fx / "poc_linux64").write_text("BIN", encoding="utf-8")
    # 本地武器化笔记(frontmatter id)
    (weap / "foobar-cms.md").write_text(
        "---\nid: foobar-cms\n---\n\n## Chain\n- 上传绕过 → webshell(本地笔记)\n", encoding="utf-8")
    (weap / "README.md").write_text("# weap readme\n", encoding="utf-8")

    idx = load_local_stores(xday, weap)
    body_hit = match("<html>welcome /FB/Login.do FooBar-CMS</html>", kb, xday, weap)
    body_nostore = match("<html>nostore-sig here</html>", kb, xday, weap)   # 公开命中但无本地货
    body_none = match("<html>unrelated</html>", kb, xday, weap)

    checks = [
        ("xday 成品按 README 的 knowledge/<id> 引用归键", "foobar-cms" in idx
            and any(s["kind"] == "poc" for s in idx["foobar-cms"])),
        ("weaponized .md 按 frontmatter id 归键", any(s["kind"] == "weaponized" for s in idx["foobar-cms"])),
        ("跳过 weaponized/README.md", all(s["path"].name != "README.md"
            for v in idx.values() for s in v if s["kind"] == "weaponized")),
        ("body 命中有本地货的栈 → 返回 stores", bool(body_hit) and body_hit[0][0] == "foobar-cms"),
        ("命中含成品+笔记两类", len(body_hit[0][2]) == 2),
        ("公开命中但【无本地货】→ 不 surface(nostore)", body_nostore == []),
        ("无关 body → 不命中", body_none == []),
        ("poc store 记录了文件清单(poc.py/二进制)", "poc.py" in idx["foobar-cms"][0]["files"]),
    ]
    bad = [n for n, ok in checks if not ok]
    for n, ok in checks:
        print(("ok   " if ok else "FAIL ") + n)
    print("xday_match selftest " + ("passed" if not bad else f"FAILED ({len(bad)})"))
    return 0 if not bad else 1


if __name__ == "__main__":
    raise SystemExit(main())
