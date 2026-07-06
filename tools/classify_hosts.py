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
ROOT = Path(__file__).resolve().parents[1]   # 仓库根(flywheel 读端 load_knowledge_signatures 用; 之前漏定义 → 真 recon 跑必崩 NameError, selftest 没覆盖到那行)
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


_KB_ID_RE = re.compile(r"^id:\s*(\S+)\s*$", re.M)
_KB_SIG_RE = re.compile(r"^signatures:\s*(\[.*\])\s*$", re.M)


def load_knowledge_signatures(kb_dir: Path) -> "list[tuple[str, list[str]]]":
    """读 knowledge/*.md frontmatter 的 (id, signatures) —— 让 classify 识别【已入库】的产品。
    接通指纹飞轮的【读取端】(写入端 = check_run 指纹入库收口门): 上次入库的指纹, 这次遇到同栈
    直接识别。signatures 是机器可匹配的小写 substring 列表(JSON)。"""
    out: list[tuple[str, list[str]]] = []
    if not kb_dir.is_dir():
        return out
    for f in sorted(kb_dir.glob("*.md")):
        if f.name in ("README.md", "_TEMPLATE.md"):
            continue
        try:
            head = f.read_text(encoding="utf-8", errors="replace").split("---", 2)
        except Exception:
            continue
        fm = head[1] if len(head) >= 3 else ""
        idm, sigm = _KB_ID_RE.search(fm), _KB_SIG_RE.search(fm)
        if not (idm and sigm):
            continue
        try:
            sigs = [str(s).lower() for s in json.loads(sigm.group(1)) if str(s).strip()]
        except Exception:
            continue
        if sigs:
            out.append((idm.group(1).strip(), sigs))
    return out


def classify_body(body: str, kb_sigs: "list[tuple[str, list[str]]] | None" = None) -> tuple[str, list[str]]:
    """(stack, flags) 仅凭内容判定。kb_sigs = 已入库 knowledge 的 (id, signatures); 硬编码没
    认出时用它识别 —— 接通指纹飞轮读取端。"""
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

    # 飞轮读取端: 硬编码没认出 -> 用【已入库】的 knowledge signatures 认(下次同栈直接识别)。
    # 标 "kb:<id>" 以示来自知识库, driver 据此直接调该条目的弱点锚。
    if stack == "?" and kb_sigs:
        for kid, sigs in kb_sigs:
            if any(s in low for s in sigs):
                stack = f"kb:{kid}"
                break

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
    # Signal-driven attack-surface subtypes (SURFACE:X): set ONLY when the body shows a concrete
    # actionable surface (grounding, not "every page is attack surface"). The depth gate keys on
    # LOGIN or any SURFACE:* so non-login surfaces (API/upload/admin/swagger/...) can't be deferred free.
    if 'type="file"' in low or "type='file'" in low or "multipart/form-data" in low:
        flags.append("SURFACE:UPLOAD")
    # Signals are PATH/PRODUCT-shaped, not bare words (a bare 'graphql'/'oauth'/'/api/' in an SPA
    # bundle would over-tag a HARD gate — Codex calibration). Only fire on a concrete surface.
    if "swagger-ui" in low or "swagger.json" in low or "/swagger" in low or "openapi.json" in low or "api-docs" in low:
        flags.append("SURFACE:SWAGGER")
    if "/graphql" in low or "graphiql" in low or "__schema" in low:
        flags.append("SURFACE:GRAPHQL")
    if "actuator" in low:
        flags.append("SURFACE:ACTUATOR")
    if any(k in low for k in ("druid", "nacos", "eureka", "phpinfo", "h2-console", "jenkins")):
        flags.append("SURFACE:ADMIN")
    if stack == "SpringBoot-api" or ('"code":' in low and '"data":' in low) or re.search(r"/api/v\d", low):
        flags.append("SURFACE:API")
    if any(k in low for k in ("ws://", "wss://", "socket.io", "sockjs", "stomp", "signalr")):
        flags.append("SURFACE:WEBSOCKET")
    if any(k in low for k in ("/oauth", "oauth2/", "/saml", "saml2", "/openid", "/sso", "authserver", "/cas")):
        flags.append("SURFACE:SSO")
    if re.search(r"[?&](url|redirect_uri|webhook|preview|imageurl|proxy)=", low):
        flags.append("SURFACE:URL_FETCH")
    if re.search(r"[?&](file|path|download|export|filename|filepath)=", low):
        flags.append("SURFACE:FILE_DOWNLOAD")
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
    _kb = [("hamastar-cms", ["css_v4.5/"]), ("foo", ["ais.webform.js"])]
    checks.append(("classify: knowledge signature match (飞轮读取端)",
                   classify_body('<link href="/css_v4.5/x.css">', _kb)[0] == "kb:hamastar-cms"))
    checks.append(("classify: no kb match -> stays ?",
                   classify_body('<html>plain page</html>', _kb)[0] == "?"))
    checks.append(("classify: hardcoded wins over kb",
                   classify_body('<script src="/Scripts/ais.webform.js"></script>', _kb)[0] == "AIS-WebForms"))
    # SURFACE:* signal-driven subtypes (Codex calibration: path/product-shaped, not bare words —
    # so the HARD depth gate over LOGIN|SURFACE:* does not over-tag generic SPA bundles).
    def _fl(b: str) -> list:
        return classify_body(b)[1]
    checks += [
        ("SURFACE: upload form -> UPLOAD", "SURFACE:UPLOAD" in _fl('<form enctype="multipart/form-data"><input type="file"></form>')),
        ("SURFACE: swagger-ui -> SWAGGER", "SURFACE:SWAGGER" in _fl('<title>swagger-ui</title>')),
        ("SURFACE: SpringBoot JSON -> API", "SURFACE:API" in _fl('{"status":500,"timestamp":1,"path":"/api/x"}')),
        ("SURFACE: /graphql -> GRAPHQL", "SURFACE:GRAPHQL" in _fl('fetch("/graphql")')),
        ("SURFACE: plain SPA not over-tagged", not any(f.startswith("SURFACE:") for f in _fl('<div id="app">hello</div>'))),
        ("SURFACE: bare /api/ does NOT tag API (tightened)", "SURFACE:API" not in _fl('<a href="/api/config">x</a>')),
        ("SURFACE: bare word 'oauth' does NOT tag SSO (tightened)", "SURFACE:SSO" not in _fl('<p>we support oauth login soon</p>')),
    ]
    # 防回归: 真 recon 跑会调 load_knowledge_signatures(ROOT/...) —— 之前 ROOT 漏定义致 NameError,
    # 而 selftest 从不走那行, 故 16/16 绿却真跑必崩(mokwon dogfood 逮到)。覆盖 ROOT + 那行。
    checks.append(("ROOT 已定义 + load_knowledge_signatures(ROOT) 可跑(防 NameError 回归)",
                   isinstance(load_knowledge_signatures(ROOT / "knowledge"), list)))

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

    with probe.selftest_isolation():
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
            # run_classify 覆盖(#9: main 循环之前没被测 → ROOT/落盘 bug 绿着崩)。2 台 + flush_every=1
            d2 = Path(tempfile.mkdtemp())
            cov, rws, intr = run_classify([f"127.0.0.1:{port}", f"127.0.0.1:{port}"], d2, [], 0.0, 5, flush_every=1)
            cj = d2 / "coverage.json"
            cjd = json.loads(cj.read_text(encoding="utf-8")) if cj.exists() else {}
            checks.append(("run_classify 增量写 coverage.json", cj.exists()))
            checks.append(("coverage 含 2 资产 + partial 字段", cjd.get("total") == 2 and "partial" in cjd))
            checks.append(("run_classify 返回 coverage 列表", len(cov) == 2))
        finally:
            srv.shutdown()

    bad = [n for n, ok in checks if not ok]
    for n, ok in checks:
        print(("ok   " if ok else "FAIL ") + n)
    print("classify_hosts selftest " + ("passed" if not bad else f"FAILED ({len(bad)})"))
    return 0 if not bad else 1


def run_classify(hosts: list, out_dir: Path, kb_sigs, delay: float, timeout: int,
                 flush_every: int = 10):
    """逐主机分类 + 【增量落盘】coverage.json/classify.txt(每 flush_every 台 + finally)。
    mokwon dogfood: 131 台跑到 71 静默死, coverage 全丢(只在循环末尾写一次)。现在跑到一半被杀/
    超时也留部分 coverage;单台任何异常不致命(防整跑崩)。返回 (coverage, rows, interesting)。
    抽成函数 = 可被 selftest 覆盖(ROOT/落盘那类 main-only 的 bug 不再绿着崩)。"""
    coverage: list[dict] = []
    rows: list = []
    interesting: list = []
    total = len(hosts)

    def flush() -> None:
        table = "\n".join(f"{h:30} [{st:14}] {ti:30} {fl}" for h, st, ti, fl in rows)
        (out_dir / "classify.txt").write_text(table, encoding="utf-8")
        examined = sum(1 for c in coverage if c["examined"])
        reachable = sum(1 for c in coverage if c["reachable"] is True)
        # 原子写: 先 .tmp 再 replace(同盘原子改名), 防增量落盘中途被杀留半截损坏 JSON(Codex#2)
        tmp = out_dir / "coverage.json.tmp"
        tmp.write_text(json.dumps(
            {"total": len(coverage), "examined": examined, "reachable": reachable,
             "planned": total, "partial": len(coverage) < total, "assets": coverage},
            ensure_ascii=False, indent=2), encoding="utf-8")
        tmp.replace(out_dir / "coverage.json")

    try:
        for i, h in enumerate(hosts, 1):
            do_sleep = True
            try:
                body, meta = fetch_body(h, out_dir, timeout)
            except HostBackoff as e:
                rows.append((h, "BACKOFF", "", str(e)[:30]))
                coverage.append({"host": h, "reachable": "unknown", "examined": False,
                                 "stack": "BACKOFF", "flags": [], "note": "self-throttle"})
                do_sleep = False
            except Exception as e:                       # 单台异常不致命(网络/解析/未料)
                rows.append((h, "EXC", "", str(e)[:30]))
                coverage.append({"host": h, "reachable": "unknown", "examined": False,
                                 "stack": "EXC", "flags": [], "note": f"exc: {str(e)[:50]}"})
                do_sleep = False
            else:
                if not body and "error" in meta:
                    rows.append((h, "ERR", "", (meta.get("error", "") or "")[:24]))
                    coverage.append({"host": h, "reachable": False, "examined": False,
                                     "stack": "ERR", "flags": [], "note": (meta.get("error", "") or "")[:40]})
                else:
                    stack, flags = classify_body(body, kb_sigs)
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
                    if stack in ("?", "SpringBoot-api", "Vue-SPA") or flags:   # 有意思=未识别/带攻击面标记
                        interesting.append((h, stack, ti, " ".join(flags), ln))
            if i % flush_every == 0 or i == total:       # 增量落盘: 中断也留部分 coverage
                flush()
                print(f"[classify] {i}/{total} … coverage 增量落盘", file=sys.stderr)
            if do_sleep:
                time.sleep(delay)
    finally:
        flush()                                          # 收尾/中断/异常都写最终 coverage
    return coverage, rows, interesting


def main() -> int:
    ap = argparse.ArgumentParser(description="逐主机按活内容分类指纹")
    ap.add_argument("recon", nargs="?", help="recon JSON 路径")
    ap.add_argument("--hosts", help="每行一个主机的文本文件")
    ap.add_argument("--out", default=None, help="输出目录(存 body + 表)")
    ap.add_argument("--delay", type=float, default=1.5, help="每主机间隔秒(配合限速)")
    ap.add_argument("--timeout", type=int, default=8)
    ap.add_argument("--selftest", action="store_true", help="run regression and exit")
    ap.add_argument("--all", action="store_true",
                    help="不做 scope 过滤, 探 recon 全量(含 ownership=unrelated 的 out-of-scope)")
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

    # scope 过滤(打谁不打谁): 默认跳过 recon 标的 out-of-scope(ownership=unrelated, 如个人 NAS /
    # 外部域)—— mokwon dogfood 实测: 不过滤会把 classify 群发到个人 Synology NAS。--all 探全量;
    # --hosts 模式无 recon 上下文, 不过滤。scope 派生自 recon, 非手挑(派生不驱动)。
    if args.recon and not args.all:
        try:
            import scope as _scope
            _recon = json.loads(Path(args.recon).read_text(encoding="utf-8"))
            _sc = _scope.derive_scope(_recon)
            _skip = [h for h in hosts if _scope.in_scope(h, _sc["in"], _sc["out"]) == "out"]
            if _skip:
                hosts = [h for h in hosts if h not in set(_skip)]
                print(f"[scope] 跳过 {len(_skip)} 个 out-of-scope(recon ownership=unrelated): "
                      + ", ".join(_skip[:8]) + (" …" if len(_skip) > 8 else "")
                      + "  (--all 探全量)", file=sys.stderr)
        except Exception as e:
            print(f"[scope] 过滤跳过(派生失败, 探全量): {e}", file=sys.stderr)

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

    # 飞轮读取端: 加载已入库的 knowledge signatures, 让 classify 识别上次入库的产品。
    kb_sigs = load_knowledge_signatures(ROOT / "knowledge")

    # 逐主机分类 + 增量落盘 coverage(抽成 run_classify, 可测 + 中断留部分, 见 #9)
    coverage, rows, interesting = run_classify(hosts, out_dir, kb_sigs, args.delay, args.timeout)
    table = "\n".join(f"{h:30} [{st:14}] {ti:30} {fl}" for h, st, ti, fl in rows)
    examined = sum(1 for c in coverage if c["examined"])
    reachable = sum(1 for c in coverage if c["reachable"] is True)
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
