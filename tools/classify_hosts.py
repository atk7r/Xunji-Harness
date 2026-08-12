#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""classify_hosts.py - 逐主机【按活内容】分类指纹（大规模交战用）。

ingest_recon.py 把 recon 折成资产表/可达性矩阵；本工具补它的下一步：对每个主机
实际拉全量 body，按【内容】（不是 server 头/猜测）判定技术栈与攻击面标记，输出逐资产
状态表。直接复用 probe.send（已带 HostHealth 自熔断 + RateLimiter 限速 + UTF-8 输出），
不走子进程 = 无 Windows GBK 编码坑。

它只【分类】，不做选择/判断 —— front 选择仍是 driver 的事。

  .venv/bin/python tools/classify_hosts.py <recon.json> --run runs/<t> \
    --out runs/<t>/classify --egress-recheck [--delay 1.5]
  .venv/bin/python tools/classify_hosts.py --hosts hosts.txt
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
from harness import output_layout  # noqa: E402

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
COMMON_SUBPATHS = (
    "/SCSRwd/",
    "/Identity/Account/Login",
    "/Identity/Account/Register",
    "/eServices/",
    "/Login.aspx",
    "/Default.aspx",
)
NON_ACTIONABLE_FLAGS = {"AUTH_GATE", "STUB_PAGE"}
NON_ACTIONABLE_VERDICT_NOTE = (
    "non-actionable root/auth page; still requires a recorded frontier/evidence "
    "verdict or Type A blocker before closure"
)


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


def _should_try_common_subpaths(body: str) -> bool:
    low = body.lower()
    default_markers = (
        "welcome to iis", "internet information services", "iis windows server",
        "under construction", "default web site",
    )
    if any(m in low for m in default_markers):
        return True
    compact = re.sub(r"<[^>]+>", "", body).strip()
    return 0 < len(compact) < 200


def _non_actionable_content_flags(body: str, meta: dict) -> list[str]:
    flags: list[str] = []
    try:
        status = int(meta.get("status") or 0)
    except Exception:
        status = 0
    if status in {401, 403}:
        flags.append("AUTH_GATE")
    if _should_try_common_subpaths(body) and not meta.get("discovered_path"):
        flags.append("STUB_PAGE")
    return flags


def _try_common_subpaths(base_url: str, host: str, save_dir: Path, timeout: int) -> tuple[str, dict] | None:
    for path in COMMON_SUBPATHS:
        nxt = urljoin(base_url, path)
        safe = re.sub(r"[^A-Za-z0-9._-]", "_", urlparse(nxt).path or "/")[:60]
        out = save_dir / f"{host}{safe}.html"
        d = probe.send("GET", nxt, {}, None, None, timeout, save=str(out), retry=0)
        if "error" in d:
            continue
        try:
            body = out.read_text(encoding="utf-8", errors="replace")
        except Exception:
            body = d.get("snippet", "") or ""
        stack, flags = classify_body(body)
        if stack != "?" or flags:
            d["discovered_path"] = nxt
            d["discovered_path_reason"] = "root looked like default/stub page"
            return body, d
    return None


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
            if _should_try_common_subpaths(body):
                discovered = _try_common_subpaths(url, host, save_dir, timeout)
                if discovered is not None:
                    return discovered
            return body, d
    return "", d  # last error meta


def _selftest() -> int:
    """Regression for redirect-following + AIS recognition (the lump-fix regression).
    Pure-function checks + one local-server integration (no external traffic)."""
    import http.server
    import contextlib
    import io
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
    checks.append(("common subpaths trigger on IIS default page",
                   _should_try_common_subpaths("<title>Welcome to IIS</title>") is True))
    checks.append(("common subpaths do not trigger on full app page",
                   _should_try_common_subpaths("<html>" + "x" * 3000 + "</html>") is False))
    checks.append(("stub page gets non-actionable flag",
                   "STUB_PAGE" in _non_actionable_content_flags("<title>Welcome to IIS</title>", {"status": 200})))
    checks.append(("403 gets auth-gate flag",
                   "AUTH_GATE" in _non_actionable_content_flags("Forbidden", {"status": 403})))
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

    class H2(http.server.BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def do_GET(self):
            b = (APP if self.path.startswith("/SCSRwd/") else "<title>Welcome to IIS</title>").encode()
            self.send_response(200)
            self.send_header("Content-Type", "text/html")
            self.send_header("Content-Length", str(len(b)))
            self.end_headers()
            self.wfile.write(b)

    with probe.selftest_isolation():
        srv2 = socketserver.TCPServer(("127.0.0.1", 0), H2)
        port2 = srv2.server_address[1]
        threading.Thread(target=srv2.serve_forever, daemon=True).start()
        try:
            d3 = Path(tempfile.mkdtemp())
            body2, meta2 = fetch_body(f"127.0.0.1:{port2}", d3, 5)
            stack2, flags2 = classify_body(body2)
            checks.append(("integration: IIS default page common-subpath discovers AIS",
                           stack2 == "AIS-WebForms"
                           and (meta2.get("discovered_path") or "").endswith("/SCSRwd/")))
            d4 = Path(tempfile.mkdtemp())
            cov2, _, _ = run_classify([f"127.0.0.1:{port2}"], d4, [], 0.0, 5, flush_every=1)
            checks.append(("coverage records discovered_path",
                           cov2 and cov2[0].get("discovered_path", "").endswith("/SCSRwd/")
                           and "DISCOVERED_PATH" in cov2[0].get("flags", [])))
        finally:
            srv2.shutdown()

    class H3(http.server.BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def do_GET(self):
            b = b"<title>Welcome to IIS</title>"
            self.send_response(200)
            self.send_header("Content-Type", "text/html")
            self.send_header("Content-Length", str(len(b)))
            self.end_headers()
            self.wfile.write(b)

    with probe.selftest_isolation():
        srv3 = socketserver.TCPServer(("127.0.0.1", 0), H3)
        port3 = srv3.server_address[1]
        threading.Thread(target=srv3.serve_forever, daemon=True).start()
        try:
            d5 = Path(tempfile.mkdtemp())
            cov3, _, interesting3 = run_classify([f"127.0.0.1:{port3}"], d5, [], 0.0, 5, flush_every=1)
            checks.append(("IIS default-only page is marked but not interesting",
                           cov3 and "STUB_PAGE" in cov3[0].get("flags", [])
                           and cov3[0].get("verdict_required") is True
                           and interesting3 == []))
        finally:
            srv3.shutdown()

    class H4(http.server.BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def do_GET(self):
            b = b"Forbidden"
            self.send_response(403)
            self.send_header("Content-Type", "text/plain")
            self.send_header("Content-Length", str(len(b)))
            self.end_headers()
            self.wfile.write(b)

    with probe.selftest_isolation():
        srv4 = socketserver.TCPServer(("127.0.0.1", 0), H4)
        port4 = srv4.server_address[1]
        threading.Thread(target=srv4.serve_forever, daemon=True).start()
        try:
            d6 = Path(tempfile.mkdtemp())
            cov4, _, interesting4 = run_classify([f"127.0.0.1:{port4}"], d6, [], 0.0, 5, flush_every=1)
            checks.append(("403 page is marked auth-gate but not interesting",
                           cov4 and "AUTH_GATE" in cov4[0].get("flags", [])
                           and cov4[0].get("verdict_required") is True
                           and interesting4 == []))
        finally:
            srv4.shutdown()

    # Setup egress mode is exercised through the real parser/runner while the
    # request layer is replaced.  This proves scope selection and output routing
    # without any network access or dependence on the local loopback server.
    egress_root = Path(tempfile.mkdtemp())
    egress_out = egress_root / "classify"
    egress_out.mkdir()
    egress_recon = egress_root / "recon.json"
    egress_recon.write_text(json.dumps({"assets": [
        {"host": "good.example"},
        {"host": "review.example"},
        {"host": "out.example"},
    ]}), encoding="utf-8")
    baseline_bytes = (json.dumps({
        "source": "frozen-baseline",
        "assets": [
            {"host": "good.example", "scope_status": "in", "source": "operator"},
            {"host": "review.example", "scope_status": "review", "source": "source-data"},
            {"host": "out.example", "scope_status": "out", "source": "scope-policy"},
        ],
    }, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
    (egress_out / "coverage.json").write_bytes(baseline_bytes)
    probed: list[str] = []
    original_fetch_body = globals()["fetch_body"]
    original_root = globals()["ROOT"]
    original_argv = list(sys.argv)

    def _offline_fetch(host: str, _save_dir: Path, _timeout: int) -> tuple[str, dict]:
        probed.append(host)
        return "<title>Offline</title><input type='password'>", {
            "status": 200, "len": 54,
        }

    try:
        globals()["fetch_body"] = _offline_fetch
        globals()["ROOT"] = egress_root
        sys.argv = [
            "classify_hosts.py", str(egress_recon), "--out", str(egress_out),
            "--run", str(egress_root),
            "--egress-recheck", "--delay", "0",
        ]
        with contextlib.redirect_stdout(io.StringIO()), \
                contextlib.redirect_stderr(io.StringIO()):
            egress_rc = main()
    finally:
        sys.argv = original_argv
        globals()["fetch_body"] = original_fetch_body
        globals()["ROOT"] = original_root
    egress_data = json.loads((egress_out / "egress_coverage.json").read_text(
        encoding="utf-8"))
    checks += [
        ("egress recheck probes explicit in-scope baseline assets only",
         egress_rc == 0 and probed == ["good.example"]),
        ("egress recheck leaves baseline coverage byte-identical",
         (egress_out / "coverage.json").read_bytes() == baseline_bytes),
        ("egress recheck writes a separate single-host overlay",
         [item.get("host") for item in egress_data.get("assets", [])]
         == ["good.example"]),
    ]

    bad = [n for n, ok in checks if not ok]
    for n, ok in checks:
        print(("ok   " if ok else "FAIL ") + n)
    print("classify_hosts selftest " + ("passed" if not bad else f"FAILED ({len(bad)})"))
    return 0 if not bad else 1


def run_classify(hosts: list, out_dir: Path, kb_sigs, delay: float, timeout: int,
                 flush_every: int = 10, *, coverage_name: str = "coverage.json",
                 table_name: str = "classify.txt"):
    """逐主机分类 + 【增量落盘】coverage/classify 文件(每 flush_every 台 + finally)。
    mokwon dogfood: 131 台跑到 71 静默死, coverage 全丢(只在循环末尾写一次)。现在跑到一半被杀/
    超时也留部分 coverage;单台任何异常不致命(防整跑崩)。返回 (coverage, rows, interesting)。
    抽成函数 = 可被 selftest 覆盖(ROOT/落盘那类 main-only 的 bug 不再绿着崩)。"""
    coverage: list[dict] = []
    rows: list = []
    interesting: list = []
    total = len(hosts)

    if coverage_name not in {"coverage.json", "egress_coverage.json"} \
            or table_name not in {"classify.txt", "egress_classify.txt"}:
        raise ValueError("unsupported classify output name")

    def flush() -> None:
        table = "\n".join(f"{h:30} [{st:14}] {ti:30} {fl}" for h, st, ti, fl in rows)
        (out_dir / table_name).write_text(table, encoding="utf-8")
        examined = sum(1 for c in coverage if c["examined"])
        reachable = sum(1 for c in coverage if c["reachable"] is True)
        # 原子写: 先 .tmp 再 replace(同盘原子改名), 防增量落盘中途被杀留半截损坏 JSON(Codex#2)
        tmp = out_dir / f"{coverage_name}.tmp"
        tmp.write_text(json.dumps(
            {"total": len(coverage), "examined": examined, "reachable": reachable,
             "planned": total, "partial": len(coverage) < total, "assets": coverage},
            ensure_ascii=False, indent=2), encoding="utf-8")
        tmp.replace(out_dir / coverage_name)

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
                    discovered = meta.get("discovered_path")
                    flags = [*flags, *_non_actionable_content_flags(body, meta)]
                    if redir:
                        flags = [*flags, "REDIRECT"]
                        ln = len(body)               # len of the RESOLVED page, not the stub
                    if discovered:
                        flags = [*flags, "DISCOVERED_PATH"]
                        ln = len(body)
                    rows.append((h, stack, ti, " ".join(flags)))
                    non_actionable_only = bool(flags) and all(f in NON_ACTIONABLE_FLAGS for f in flags)
                    cov = {"host": h, "reachable": True, "examined": True,
                           "stack": stack, "flags": flags, "title": ti, "len": ln}
                    if non_actionable_only:
                        cov["verdict_required"] = True
                        cov["note"] = NON_ACTIONABLE_VERDICT_NOTE
                    if redir:
                        cov["redirected_to"] = redir
                    if discovered:
                        cov["discovered_path"] = discovered
                    coverage.append(cov)
                    actionable_flags = [f for f in flags if f not in NON_ACTIONABLE_FLAGS]
                    if stack in ("SpringBoot-api", "Vue-SPA") \
                            or (stack == "?" and "STUB_PAGE" not in flags and "AUTH_GATE" not in flags) \
                            or actionable_flags:
                        interesting.append((h, stack, ti, " ".join(flags), ln))
            if i % flush_every == 0 or i == total:       # 增量落盘: 中断也留部分 coverage
                flush()
                print(f"[classify] {i}/{total} … coverage 增量落盘", file=sys.stderr)
            if do_sleep:
                time.sleep(delay)
    finally:
        flush()                                          # 收尾/中断/异常都写最终 coverage
    return coverage, rows, interesting


def _egress_hosts_from_baseline(out_dir: Path, recon_path: Path) -> list[str]:
    """Return only frozen baseline assets with explicit in-scope authority.

    Egress recheck is an overlay, not a second scope derivation.  In particular,
    review/unknown/out rows from a source file must never become probe targets
    merely because the classifier can parse them.
    """
    baseline_path = out_dir / "coverage.json"
    try:
        baseline = json.loads(baseline_path.read_text(
            encoding="utf-8", errors="strict"))
        recon_hosts = set(_hosts_from_recon(recon_path))
    except Exception as exc:
        raise ValueError("egress recheck requires readable baseline coverage and recon") from exc
    assets = baseline.get("assets") if isinstance(baseline, dict) else None
    if not isinstance(assets, list) or any(not isinstance(item, dict) for item in assets):
        raise ValueError("egress recheck baseline assets are invalid")
    hosts: list[str] = []
    seen: set[str] = set()
    for asset in assets:
        host = asset.get("host")
        if not isinstance(host, str) or not host.strip() or host != host.strip() \
                or re.search(r"[\x00-\x20\x7f/@]", host):
            raise ValueError("egress recheck baseline contains an invalid host")
        if host in seen:
            raise ValueError("egress recheck baseline contains a duplicate host")
        seen.add(host)
        if str(asset.get("scope_status") or "").strip().lower() != "in":
            continue
        if host not in recon_hosts:
            raise ValueError("in-scope baseline host is absent from frozen recon")
        hosts.append(host)
    return hosts


def main() -> int:
    ap = argparse.ArgumentParser(description="逐主机按活内容分类指纹")
    ap.add_argument("recon", nargs="?", help="recon JSON 路径")
    ap.add_argument("--hosts", help="每行一个主机的文本文件")
    ap.add_argument("--out", default=None, help="输出目录(存 body + 表)")
    ap.add_argument("--run", default=None,
                    help="run 目录；live egress recheck 输出只允许进入 <run>/classify/")
    ap.add_argument("--delay", type=float, default=1.5, help="每主机间隔秒(配合限速)")
    ap.add_argument("--timeout", type=int, default=8)
    ap.add_argument("--selftest", action="store_true", help="run regression and exit")
    ap.add_argument("--all", action="store_true",
                    help="不做 scope 过滤, 探 recon 全量(含 ownership=unrelated 的 out-of-scope)")
    ap.add_argument("--egress-recheck", action="store_true",
                    help="setup_run 专用的主动出口复核标记；不放宽 scope 或 guard")
    args = ap.parse_args()

    if args.selftest:
        return _selftest()
    if args.recon and args.hosts:
        ap.error("pass either a recon JSON path OR --hosts FILE, not both")
    if not (args.recon or args.hosts):
        ap.error("need a recon JSON path or --hosts FILE (or --selftest)")

    if args.egress_recheck and (
            args.hosts or args.all or not args.recon or not args.out or not args.run):
        ap.error("--egress-recheck requires recon + --run + --out and forbids --hosts/--all")

    # --out is a DIRECTORY (stores body + tables). Reject file-shaped values;
    # silently rewriting to a parent makes the actual destination surprising.
    if args.out and Path(args.out).suffix:
        ap.error("--out is a directory; pass its directory path, not a filename")
    try:
        out_dir = output_layout.resolve_run_bucket_dir(
            args.out,
            run=args.run,
            bucket="classify",
            tool="classify",
            invocation=output_layout.invocation_id(),
            repo_root=ROOT,
        )
    except output_layout.OutputLayoutError as exc:
        ap.error(str(exc))
    out_dir.mkdir(parents=True, exist_ok=True)

    if args.egress_recheck:
        try:
            hosts = _egress_hosts_from_baseline(out_dir, Path(args.recon))
        except ValueError as exc:
            ap.error(str(exc))
    elif args.hosts:
        hosts = [h.strip() for h in Path(args.hosts).read_text(encoding="utf-8").splitlines()
                 if h.strip() and not h.startswith("#")]
    else:
        hosts = _hosts_from_recon(Path(args.recon))

    # Legacy standalone mode derives a scope view from recon.  Setup's
    # --egress-recheck never enters this path: it uses the already frozen
    # baseline ledger above and therefore cannot fail open to recon-wide probing.
    if args.recon and not args.all and not args.egress_recheck:
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

    # 飞轮读取端: 加载已入库的 knowledge signatures, 让 classify 识别上次入库的产品。
    kb_sigs = load_knowledge_signatures(ROOT / "knowledge")

    # 逐主机分类 + 增量落盘 coverage(抽成 run_classify, 可测 + 中断留部分, 见 #9)
    coverage_name = "egress_coverage.json" if args.egress_recheck else "coverage.json"
    table_name = "egress_classify.txt" if args.egress_recheck else "classify.txt"
    coverage, rows, interesting = run_classify(
        hosts, out_dir, kb_sigs, args.delay, args.timeout,
        coverage_name=coverage_name, table_name=table_name,
    )
    table = "\n".join(f"{h:30} [{st:14}] {ti:30} {fl}" for h, st, ti, fl in rows)
    examined = sum(1 for c in coverage if c["examined"])
    reachable = sum(1 for c in coverage if c["reachable"] is True)
    print(table)
    print(f"\n[检视覆盖] 资产 {len(coverage)} | 已检视内容 {examined} | "
          f"可达 {reachable} | 写 {out_dir}/{coverage_name}")
    print("\n===== INTERESTING (未识别栈 / 独立应用 / 带 LOGIN·DYN·FRAMEWORK·SPA) =====")
    if interesting:
        for h, st, ti, fl, ln in interesting:
            print(f"  {h:30} [{st}] len={ln} {ti} {fl}")
    else:
        print("  (无 —— 全部归入已知共享栈)")
    verdict_required = [a for a in coverage if a.get("verdict_required")]
    if verdict_required:
        print("\n===== VERDICT REQUIRED (anti-lump 降噪, 但不可静默丢弃) =====")
        for a in verdict_required[:20]:
            print(f"  {str(a.get('host', '')):30} [{a.get('stack', '?')}] "
                  f"{' '.join(str(f) for f in (a.get('flags') or []))} :: {a.get('note', '')}")
        if len(verdict_required) > 20:
            print(f"  … {len(verdict_required) - 20} more")
    print(f"\n[DONE] {len(rows)} hosts -> {out_dir}/{table_name} ; {len(interesting)} interesting")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
