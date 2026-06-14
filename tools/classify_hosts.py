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
from urllib.parse import urljoin, urlparse

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


# JS / meta-refresh client-side redirects. A small body that is *only* a redirect
# (e.g. `<script>window.location="/app/"</script>`, len~71) is NOT a dead/noise
# page — it points at the real app. Missing this is how a real run nearly lumped
# several live app logins (hidden behind redirect stubs) as noise. Detect + follow one hop.
_REDIRECT_RES = [
    re.compile(r"""(?:window\.)?location(?:\.href|\.replace)?\s*(?:=|\()\s*['"]([^'"]+)['"]""", re.I),
    re.compile(r"""<meta[^>]+http-equiv=['"]?refresh['"]?[^>]*url=([^'">\s]+)""", re.I),
]


def detect_redirect(body: str) -> str | None:
    """If the body's dominant content is a client-side redirect, return its target.
    Conservative: only treat as a redirect when the body is small (a stub) so a
    real page that merely contains a location= string is not mis-followed."""
    if len(body) > 2000:
        return None
    for rx in _REDIRECT_RES:
        m = rx.search(body)
        if m:
            tgt = m.group(1).strip()
            if tgt and not tgt.lower().startswith(("javascript:", "#", "mailto:")):
                return tgt
    return None


def classify_body(body: str) -> tuple[str, list[str]]:
    """(stack, flags) 仅凭内容判定。"""
    low = body.lower()
    stack = "?"
    # Soar Cloud AIS HR (this product family) — recognize so it is never "?"/lumped.
    if "ais.webform.js" in low or "__logincompanyid" in low or "伺服端資訊" in low:
        stack = "AIS-WebForms"
    elif "eservices.styles.css" in low or ("identity.external" in low and "input.email" in low):
        stack = "eServices-Identity"
    elif "/system/resource" in low or "__local" in low:
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
    """https 优先, 失败回退 http; 返回 (body, meta)。复用 send(save=) 拿 guard-capped body。
    若 body 是 JS/meta 客户端跳转(同主机), 跟一跳, 返回【跳转目标】的内容(meta['redirected_to'])。"""
    for scheme in ("https", "http"):
        url = f"{scheme}://{host}/"
        out = save_dir / f"{host}.{scheme}.html"
        d = probe.send("GET", url, {}, None, None, timeout, save=str(out), retry=1)
        if "error" not in d:
            try:
                body = out.read_text(encoding="utf-8", errors="replace")
            except Exception:
                body = d.get("snippet", "") or ""
            tgt = detect_redirect(body)
            if tgt:
                nxt = urljoin(url, tgt)
                # only follow same-host hops (avoid wandering off to a 3rd party).
                # compare HOSTNAMES (host may carry a :port, urlparse.hostname does not)
                if (urlparse(nxt).hostname or "").lower() == (urlparse(url).hostname or "").lower():
                    safe = re.sub(r"[^A-Za-z0-9._-]", "_", urlparse(nxt).path or "/")[:60]
                    out2 = save_dir / f"{host}{safe}.html"
                    d2 = probe.send("GET", nxt, {}, None, None, timeout, save=str(out2), retry=1)
                    if "error" not in d2:
                        try:
                            body = out2.read_text(encoding="utf-8", errors="replace")
                        except Exception:
                            body = d2.get("snippet", "") or body
                        d2["redirected_to"] = nxt
                        return body, d2
                d.setdefault("redirected_to", nxt)   # record even if not followed
            return body, d
    return "", d  # last error meta


def _selftest() -> int:
    """Regression for redirect-following + AIS recognition (the lump-fix regression).
    Pure-function checks + one local-server integration (no external traffic)."""
    import http.server
    import socketserver
    import tempfile
    import threading

    checks: list[tuple[str, bool]] = []
    checks.append(("redirect: js location.href",
                   detect_redirect('<script>window.location.href="/app/";</script>') == "/app/"))
    checks.append(("redirect: js location=",
                   detect_redirect('window.location="/APP/"') == "/APP/"))
    checks.append(("redirect: meta refresh",
                   detect_redirect('<meta http-equiv="refresh" content="1;url=html/x.htm">') == "html/x.htm"))
    checks.append(("redirect: location.replace", detect_redirect("location.replace('/login')") == "/login"))
    checks.append(("redirect: none on big page", detect_redirect('<a href="/x">' + "y" * 3000) is None))
    checks.append(("classify: AIS by ais.webform.js",
                   classify_body('<script src="/Scripts/ais.webform.js"></script>')[0] == "AIS-WebForms"))
    checks.append(("classify: AIS by 伺服端資訊", classify_body("伺服端資訊")[0] == "AIS-WebForms"))
    checks.append(("classify: eServices",
                   classify_body('<link href="/eServices.styles.css"><input name="Input.Email"> Identity.External')[0]
                   == "eServices-Identity"))

    STUB = '<html><script>window.location.href= "/app/";</script></html>'
    APP = ('<title>LOGIN</title><input type="password" name="FormLayout$edtPassword">'
           '<script src="/app/Scripts/ais.webform.js?v=7.3"></script>')

    class H(http.server.BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def do_GET(self):
            b = (APP if self.path.rstrip("/") == "/app" else STUB).encode()
            self.send_response(200)
            self.send_header("Content-Type", "text/html")
            self.send_header("Content-Length", str(len(b)))
            self.end_headers()
            self.wfile.write(b)

    srv = socketserver.TCPServer(("127.0.0.1", 0), H)
    port = srv.server_address[1]
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    try:
        d = Path(tempfile.mkdtemp())
        body, meta = fetch_body(f"127.0.0.1:{port}", d, 5)
        stack, _ = classify_body(body)
        checks.append(("integration: followed same-host redirect",
                       (meta.get("redirected_to", "") or "").endswith("/app/")))
        checks.append(("integration: resolved page classified AIS", stack == "AIS-WebForms"))
        checks.append(("integration: resolved body has app marker", "ais.webform.js" in body))
    finally:
        srv.shutdown()

    bad = [n for n, ok in checks if not ok]
    for n, ok in checks:
        print(("ok   " if ok else "FAIL ") + n)
    print("classify_hosts selftest " + ("passed" if not bad else f"FAILED ({len(bad)})"))
    return 0 if not bad else 1


def main() -> int:
    ap = argparse.ArgumentParser(description="逐主机按活内容分类指纹")
    ap.add_argument("recon", nargs="?", help="recon JSON 路径")
    ap.add_argument("--hosts", help="每行一个主机的文本文件")
    ap.add_argument("--out", default=None, help="输出目录(存 body + 表)")
    ap.add_argument("--delay", type=float, default=1.5, help="每主机间隔秒(配合限速)")
    ap.add_argument("--timeout", type=int, default=8)
    ap.add_argument("--selftest", action="store_true", help="run regression and exit")
    args = ap.parse_args()

    if args.selftest:
        return _selftest()
    if args.recon and args.hosts:
        ap.error("pass either a recon JSON path OR --hosts FILE, not both")
    if not (args.recon or args.hosts):
        ap.error("need a recon JSON path or --hosts FILE (or --selftest)")

    if args.hosts:
        hosts = [h.strip() for h in Path(args.hosts).read_text(encoding="utf-8").splitlines()
                 if h.strip() and not h.startswith("#")]
    else:
        hosts = _hosts_from_recon(Path(args.recon))

    # --out is a DIRECTORY (stores body + tables). Guard the common footgun of
    # passing a file path like ".../coverage.json" (which used to create a dir
    # named coverage.json/ with coverage.json inside it): use its parent instead.
    if args.out and Path(args.out).suffix:
        print(f"[!] --out '{args.out}' looks like a file; using its parent dir "
              f"'{Path(args.out).parent}' (--out is a directory).", file=sys.stderr)
        out_dir = Path(args.out).parent
    else:
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
        redir = meta.get("redirected_to")
        if redir:
            flags = [*flags, "REDIRECT"]
            ln = len(body)               # len of the RESOLVED page, not the stub
        rows.append((h, stack, ti, " ".join(flags)))
        cov = {"host": h, "reachable": True, "examined": True,
               "stack": stack, "flags": flags, "title": ti, "len": ln}
        if redir:
            cov["redirected_to"] = redir
        coverage.append(cov)
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
