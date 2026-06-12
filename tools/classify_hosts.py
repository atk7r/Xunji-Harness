#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""classify_hosts.py - 逐主机【按活内容】分类指纹（大规模交战用）。

ingest_recon.py 把 recon 折成资产表/可达性矩阵；本工具补它的下一步：对每个主机
实际拉全量 body，按【内容】（不是 server 头/猜测）判定技术栈与攻击面标记，输出逐资产
状态表。直接复用 probe.send（已带 HostHealth 自熔断 + RateLimiter 限速 + UTF-8 输出），
不走子进程 = 无 Windows GBK 编码坑。

它只【分类】，不做选择/判断 —— front 选择仍是 driver 的事。

  python tools/classify_hosts.py <recon.json> [--out runs/<t>/classify] [--delay 1.5]
  python tools/classify_hosts.py --hosts hosts.txt --out runs/<t>/classify
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import probe  # noqa: E402  (复用 send + 其 guard 接入 + UTF-8 stdout)
from harness.guard import HostBackoff  # noqa: E402

try:
    sys.stdout.reconfigure(encoding="utf-8")       # type: ignore[attr-defined]
except Exception:
    pass


def _hosts_from_recon(path: Path) -> list[str]:
    d = json.loads(path.read_text(encoding="utf-8"))
    out = []
    for a in d.get("assets", []):
        if isinstance(a, dict) and a.get("host"):
            out.append(a["host"])
    return out


def classify_body(body: str) -> tuple[str, list[str]]:
    """(stack, flags) 仅凭内容判定。"""
    low = body.lower()
    stack = "?"
    if "/system/resource" in low or "__local" in low:
        stack = "VSB-CMS"
    elif "/iam/auth" in low or "starttunnel" in low or "tunnelconnect" in low:
        stack = "zerotrust-IAM"
    elif "/authserver/" in low or "统一身份认证" in low:
        stack = "CAS-login"
    elif "subacct" in low or "应用账号登录" in low:
        stack = "card-subAcct"
    elif "loginedshow" in low or "账号延期" in low:
        stack = "acctext-Vue"
    elif "id=app" in low and ("chunk-" in low or "vue" in low):
        stack = "Vue-SPA"
    elif '"status":' in low and '"timestamp":' in low and '"path":' in low:
        stack = "SpringBoot-api"

    flags = []
    if 'type="password"' in low or "type='password'" in low:
        flags.append("LOGIN")
    if re.search(r"\.(jsp|do|action|php|aspx?)\b", low) or re.search(r"\?[a-z_]+=\d", low):
        flags.append("DYN")
    if any(k in low for k in ("swagger", "druid", "actuator", "ruoyi", "若依",
                              "nacos", "thinkphp", "jeecg", "eureka")):
        flags.append("FRAMEWORK")
    if "id=app" in low or 'id="app"' in low:
        flags.append("SPA")
    return stack, flags


def fetch_body(host: str, save_dir: Path, timeout: int) -> tuple[str, dict]:
    """https 优先, 失败回退 http; 返回 (body, meta)。复用 send(save=) 拿 guard-capped body。"""
    for scheme in ("https", "http"):
        out = save_dir / f"{host}.{scheme}.html"
        d = probe.send("GET", f"{scheme}://{host}/", {}, None, None, timeout,
                       save=str(out), retry=1)
        if "error" not in d:
            try:
                body = out.read_text(encoding="utf-8", errors="replace")
            except Exception:
                body = d.get("snippet", "") or ""
            return body, d
    return "", d  # last error meta


def main() -> int:
    ap = argparse.ArgumentParser(description="逐主机按活内容分类指纹")
    src = ap.add_mutually_exclusive_group(required=True)
    src.add_argument("recon", nargs="?", help="recon JSON 路径")
    src.add_argument("--hosts", help="每行一个主机的文本文件")
    ap.add_argument("--out", default=None, help="输出目录(存 body + 表)")
    ap.add_argument("--delay", type=float, default=1.5, help="每主机间隔秒(配合限速)")
    ap.add_argument("--timeout", type=int, default=8)
    args = ap.parse_args()

    if args.hosts:
        hosts = [h.strip() for h in Path(args.hosts).read_text(encoding="utf-8").splitlines()
                 if h.strip() and not h.startswith("#")]
    else:
        hosts = _hosts_from_recon(Path(args.recon))

    out_dir = Path(args.out) if args.out else Path("tmp") / "classify"
    out_dir.mkdir(parents=True, exist_ok=True)

    # 结构化检视台账(coverage): 每个资产 reachable/examined/stack —— 让 lump 藏不住。
    coverage: list[dict] = []
    rows = []
    interesting = []
    for h in hosts:
        try:
            body, meta = fetch_body(h, out_dir, args.timeout)
        except HostBackoff as e:
            rows.append((h, "BACKOFF", "", str(e)[:30]))
            coverage.append({"host": h, "reachable": "unknown", "examined": False,
                             "stack": "BACKOFF", "flags": [], "note": "self-throttle"})
            continue
        if not body and "error" in meta:
            rows.append((h, "ERR", "", (meta.get("error", "") or "")[:24]))
            coverage.append({"host": h, "reachable": False, "examined": False,
                             "stack": "ERR", "flags": [], "note": (meta.get("error", "") or "")[:40]})
            time.sleep(args.delay)
            continue
        stack, flags = classify_body(body)
        m = re.search(r"<title>(.*?)</title>", body, re.I | re.S)
        ti = (m.group(1).strip()[:30] if m else "")
        ln = meta.get("len", len(body))
        rows.append((h, stack, ti, " ".join(flags)))
        coverage.append({"host": h, "reachable": True, "examined": True,
                         "stack": stack, "flags": flags, "title": ti, "len": ln})
        # "有意思"= 未识别栈 或 带攻击面标记(独立应用/登录/动态/框架)
        if stack in ("?", "SpringBoot-api", "Vue-SPA") or flags:
            interesting.append((h, stack, ti, " ".join(flags), ln))
        time.sleep(args.delay)

    table = "\n".join(f"{h:30} [{st:14}] {ti:30} {fl}" for h, st, ti, fl in rows)
    (out_dir / "classify.txt").write_text(table, encoding="utf-8")
    # coverage.json: check_run 读它做"已检视 vs 可达未检视"的结构化比对(根源防 lump)
    examined = sum(1 for c in coverage if c["examined"])
    reachable = sum(1 for c in coverage if c["reachable"] is True)
    (out_dir / "coverage.json").write_text(json.dumps(
        {"total": len(coverage), "examined": examined, "reachable": reachable,
         "assets": coverage}, ensure_ascii=False, indent=2), encoding="utf-8")
    print(table)
    print(f"\n[检视覆盖] 资产 {len(coverage)} | 已检视内容 {examined} | "
          f"可达 {reachable} | 写 {out_dir}/coverage.json")
    print("\n===== INTERESTING (未识别栈 / 独立应用 / 带 LOGIN·DYN·FRAMEWORK·SPA) =====")
    if interesting:
        for h, st, ti, fl, ln in interesting:
            print(f"  {h:30} [{st}] len={ln} {ti} {fl}")
    else:
        print("  (无 —— 全部归入已知共享栈)")
    print(f"\n[DONE] {len(rows)} hosts -> {out_dir}/classify.txt ; {len(interesting)} interesting")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
