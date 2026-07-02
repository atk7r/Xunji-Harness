#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""fetch_assets.py - 抓全一个 SPA 页面引用的所有 JS 资源并做【完整性断言】。

解决的实痛(某实战 实战)：只下载了 4/13 个 webpack chunk 就声称"端点已全量枚举"——
端点是从"碰巧抓到的" JS 里 grep 的, 漏的 9 个 chunk 里恰好藏着账号接管端点。

本工具：给一个页面 URL → 解析它引用的【全部】JS(<script src> + 各 JS 内部引用的 chunk
文件名)→ 核对已抓 vs 缺失 → 一键抓全(走 guard 熔断/限速/UTF-8)→ 完整性断言。
之后对 --out 目录 grep 端点, 才有"已枚举完"的底气。

  python tools/fetch_assets.py https://t/app/ --out runs/<dir>/appjs
  python tools/fetch_assets.py --html runs/<dir>/page.html --base https://t --out runs/<dir>/js
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path
from urllib.parse import urljoin, urlparse

sys.path.insert(0, str(Path(__file__).resolve().parent))
import probe  # noqa: E402  (复用 send + guard 接入 + UTF-8 stdout)
from harness.guard import HostBackoff  # noqa: E402

try:
    sys.stdout.reconfigure(encoding="utf-8")       # type: ignore[attr-defined]
except Exception:
    pass

# JS 资源引用形态：<script src>、prefetch/preload 链接、JS 内部的 chunk 文件名
JS_REF = re.compile(r'(?:src=["\']|href=["\']|["\'])'
                    r'([a-zA-Z0-9_./-]*?[a-zA-Z0-9_-]+(?:\.[a-f0-9]{6,})?\.js)\b')
CHUNK_REF = re.compile(r'([a-zA-Z0-9_-]+\.[a-f0-9]{6,}\.js|chunk-[a-zA-Z0-9_]+\.[a-f0-9]+\.js)')


def asset_paths(text: str) -> set[str]:
    out: set[str] = set()
    for m in JS_REF.findall(text):
        out.add(m)
    for m in CHUNK_REF.findall(text):
        out.add(m)
    return {p for p in out if p.endswith(".js")}


def to_url(ref: str, base: str, asset_dir_hint: str) -> str:
    if ref.startswith("http"):
        return ref
    if ref.startswith("/"):
        return base.rstrip("/") + ref
    # 裸 chunk 名(JS 内部引用, 无路径) -> 用页面里 script 的目录前缀补全
    if "/" not in ref and asset_dir_hint:
        return asset_dir_hint.rstrip("/") + "/" + ref
    return urljoin(base + "/", ref)


def main() -> int:
    ap = argparse.ArgumentParser(description="抓全 SPA 页面的 JS 资源 + 完整性断言")
    ap.add_argument("url", nargs="?", help="页面 URL")
    ap.add_argument("--html", help="改用已存的 HTML 文件(配 --base)")
    ap.add_argument("--base", help="--html 模式下的站点基址")
    ap.add_argument("--out", default=None, help="JS 输出目录")
    ap.add_argument("--timeout", type=int, default=8)
    args = ap.parse_args()

    if args.html:
        html = Path(args.html).read_text(encoding="utf-8", errors="replace")
        base = args.base or ""
    elif args.url:
        d = probe.send("GET", args.url, {}, None, None, args.timeout, retry=1)
        if "error" in d:
            print(f"[fetch_assets] 页面拉取失败: {d['error']}", file=sys.stderr)
            return 1
        # send 不返 body, 重取一次存盘读
        pr = urlparse(args.url)
        base = f"{pr.scheme}://{pr.netloc}"
        tmp = Path(args.out or "tmp") / "_page.html"
        probe.send("GET", args.url, {}, None, None, args.timeout, save=str(tmp), retry=1)
        html = tmp.read_text(encoding="utf-8", errors="replace")
    else:
        ap.error("需 url 或 --html")

    out_dir = Path(args.out) if args.out else Path("tmp") / "assets"
    out_dir.mkdir(parents=True, exist_ok=True)

    # 页面里第一个带路径的 js -> 作为裸 chunk 名的目录前缀提示
    dir_hint = ""
    mdir = re.search(r'(https?://[^"\']+/|/[^"\']+/)[a-zA-Z0-9_-]+\.[a-f0-9]{6,}\.js', html)
    if mdir:
        p = mdir.group(1)
        dir_hint = (base.rstrip("/") + p) if p.startswith("/") else p

    # 第一波：HTML 里的引用
    referenced = asset_paths(html)
    fetched: set[str] = set()
    missing_fetch: set[str] = set()

    def fetch(ref: str):
        name = ref.split("/")[-1]
        if (out_dir / name).exists():
            fetched.add(name); return
        url = to_url(ref, base, dir_hint)
        try:
            d = probe.send("GET", url, {}, None, None, args.timeout,
                           save=str(out_dir / name), retry=1)
        except HostBackoff:
            print(f"[fetch_assets] BACKOFF, 停于 {name}", file=sys.stderr); return
        if "error" not in d:
            fetched.add(name)
        else:
            missing_fetch.add(name)

    for ref in sorted(referenced):
        fetch(ref)

    # 第二波：已抓 JS 内部又引用的 chunk(惰性加载, HTML 可能没列全) -> 闭包补全
    for _ in range(3):
        more: set[str] = set()
        for f in out_dir.glob("*.js"):
            more |= asset_paths(f.read_text(encoding="utf-8", errors="replace"))
        new = {r for r in more if r.split("/")[-1] not in fetched and r.split("/")[-1] not in missing_fetch}
        if not new:
            break
        for ref in sorted(new):
            fetch(ref)

    all_names = {r.split("/")[-1] for r in (referenced)} | {f.name for f in out_dir.glob("*.js")}
    have = {f.name for f in out_dir.glob("*.js")}
    still_missing = sorted(n for n in all_names if n not in have)

    print(f"[完整性断言] 引用 JS 资源 {len(all_names)} 个 | 已抓 {len(have)} | 缺失 {len(still_missing)}")
    if still_missing:
        print("  仍缺(抓取失败):")
        for n in still_missing:
            print(f"    - {n}")
        print("  ⚠️ 资源不全 —— 此时'端点已枚举完'的结论不成立, 先抓全再 grep。")
    else:
        print(f"  ✅ 全部就位 → {out_dir}/  现在 grep 端点才有底气。")
    return 0 if not still_missing else 2


if __name__ == "__main__":
    raise SystemExit(main())
