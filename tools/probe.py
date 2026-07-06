#!/usr/bin/env python3
"""probe.py - active HTTP verifier (P2).

Sends crafted requests (any method/header/body/payload) to PROVE a vulnerability
exists, then stops. This is the proof-only verification primitive the skill
explicitly permits (SQLi differential, SSTI eval echo, auth-bypass, IDOR
existence) -- bounded by the guard layer:

- RateLimiter (禁高频: 速率是爆破的真正危害闸), cap_body (禁拖库: oversized
  bodies truncated), AuthFailCounter (防死循环: 弱口令随便试, 只兜底无限认证循环).
- It never dumps: bodies are capped and only summarized (status/len/sha1/snippet).

It is a sender, not an exploiter. Proof, not extraction. Examples:
  python tools/probe.py GET  "https://t/api/x?id=1"
  python tools/probe.py GET  "https://t/api/x?id=1'"          --tag sqli-probe
  python tools/probe.py DIFF "https://t/x?id=1 and 1=1" "https://t/x?id=1 and 1=2"
  python tools/probe.py POST "https://t/login" --data '{"u":"a"}' --auth-key t/login
"""

from __future__ import annotations

import argparse
import contextlib
import hashlib
import json
import os
import shutil
import ssl
import sys
import tempfile
import time
import urllib.request
from pathlib import Path
from urllib.parse import urlparse

sys.path.insert(0, str(Path(__file__).resolve().parent))
from harness import guard as guardmod  # noqa: E402
from harness.guard import (RateLimiter, AuthFailCounter, cap_body,  # noqa: E402
                           RateBudgetExceeded, BruteforceLock,
                           HostHealth, HostBackoff, SessionBudget, SessionTripped,
                           MIN_STATIC_ASSET_BYTES)
from harness import proxy as proxymod  # noqa: E402  渗透流量走交战代理(模型调用不走)

# Emit UTF-8 regardless of the OS locale, so this tool's JSON (ensure_ascii=False,
# 含中文/标题) survives being captured by a parent process on Windows (default
# GBK codec would crash the reader thread). Footgun fixed at the source.
try:
    sys.stdout.reconfigure(encoding="utf-8")       # type: ignore[attr-defined]
    sys.stderr.reconfigure(encoding="utf-8")       # type: ignore[attr-defined]
except Exception:
    pass

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36")
_CTX = ssl.create_default_context()
_CTX.check_hostname = False
_CTX.verify_mode = ssl.CERT_NONE

# Content-types safe for plaintext snippets in JSON output.
# Binary types (images, audio, video, octet-stream, etc.) get base64-encoded.
_TEXT_CTYPES = frozenset({
    "text/", "application/json", "application/xml", "application/xhtml+xml",
    "application/javascript", "application/ld+json", "application/rss+xml",
    "application/atom+xml", "application/x-www-form-urlencoded",
})


def _safe_snippet(raw: bytes, ctype: str, max_len: int = 240) -> tuple[str, str | None]:
    """Return (snippet_value, encoding_or_None).
    Text types: UTF-8 decoded snippet.
    Binary types: base64-encoded snippet with encoding="base64"."""
    ctype_lower = ctype.lower().split(";")[0].strip()
    is_text = any(ctype_lower.startswith(t) for t in _TEXT_CTYPES)
    if is_text:
        return raw[:max_len].decode("utf-8", "replace"), None
    import base64 as _b64
    return _b64.b64encode(raw[:max_len]).decode("ascii"), "base64"


def _snippet_kwargs(encoding: str | None) -> dict:
    """Return {"snippet_encoding": encoding} if encoding is set, else {}."""
    return {"snippet_encoding": encoding} if encoding else {}

# 代理: 通过 --proxy 或环境变量设置。境内资产需经中继时用。
_PROXY: str | None = None


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    """不跟随 3xx 跳转: redirect_request 返回 None 使 302/301/303/307 以 HTTPError 抛出, 由 send 的
    except 捕获(status=3xx + Location + 该跳的 Set-Cookie)。认证流(登录/注册成功后 302 带
    .AspNet.ApplicationCookie 等)的会话 cookie 就设在这一跳上, 跟随跳转会丢失它。顺带: 不自动追
    跳转 -> 不会被 302 带到 scope 外的 host。"""
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def _opener(no_redirect: bool = False) -> urllib.request.OpenerDirector:
    # urllib_proxy_handlers 返回【完整连接 handler(含带 _CTX 的 HTTPS handler)】。这里【不要】再自己加
    # HTTPSHandler —— 否则普通 HTTPSHandler 会和 socks handler 抢 https, socks 连不上时悄悄走直连泄真实 IP
    # (实测坏代理仍回 200 的坑)。_PROXY 仅是 --proxy 覆盖; 内部 resolve() 让 import probe.send 的工具
    # (classify_hosts/fetch_assets/replay/rerun_deferred)也走交战代理 + required 时 fail-closed。
    handlers: list = list(proxymod.urllib_proxy_handlers(_PROXY, ssl_context=_CTX))
    if no_redirect:
        handlers.append(_NoRedirect())          # build_opener 用它替换默认 HTTPRedirectHandler
    return urllib.request.build_opener(*handlers)


@contextlib.contextmanager
def selftest_isolation():
    """Run local HTTP selftests with isolated guard state and no engagement proxy.

    Real active tools must honor the persistent guard state and `proxy.conf`.
    Local loopback regressions, however, need deterministic fixtures: a stale
    localhost HostHealth/SessionBudget entry or a developer's gitignored
    `proxy.conf` must not make the suite red.
    """
    tmp_root = Path(tempfile.mkdtemp())
    old = (
        _PROXY,
        proxymod._CONF,
        guardmod.STATE_DIR,
        guardmod._LOCK_PATH,
        os.environ.get("XUNJI_PROXY"),
        os.environ.get("XUNJI_PROXY_REQUIRED"),
    )
    try:
        os.environ.pop("XUNJI_PROXY", None)
        os.environ.pop("XUNJI_PROXY_REQUIRED", None)
        globals()["_PROXY"] = None
        proxymod._CONF = Path("__xunji_no_proxy_conf__")
        guardmod.STATE_DIR = tmp_root / "guard_state"
        guardmod.STATE_DIR.mkdir(parents=True, exist_ok=True)
        guardmod._LOCK_PATH = guardmod.STATE_DIR / ".lock"
        yield
    finally:
        (old_proxy, old_conf, old_state_dir, old_lock_path,
         old_proxy_env, old_required_env) = old
        globals()["_PROXY"] = old_proxy
        proxymod._CONF = old_conf
        guardmod.STATE_DIR = old_state_dir
        guardmod._LOCK_PATH = old_lock_path
        if old_proxy_env is None:
            os.environ.pop("XUNJI_PROXY", None)
        else:
            os.environ["XUNJI_PROXY"] = old_proxy_env
        if old_required_env is None:
            os.environ.pop("XUNJI_PROXY_REQUIRED", None)
        else:
            os.environ["XUNJI_PROXY_REQUIRED"] = old_required_env
        shutil.rmtree(tmp_root, ignore_errors=True)


def _is_waf_block(headers: dict, body: bytes) -> bool:
    """P1: 判断 403 是否为 WAF/策略拦截(非认证失败)。"""
    body_str = body.decode("utf-8", "replace").lower()
    waf_indicators = [
        "waf", "blocked", "access denied", "request rejected",
        "cloudfront", "akamai", "cloudflare", "imperva", "f5",
        "rate limit", "too many requests", "challenge",
    ]
    server = headers.get("Server", "").lower()
    if any(w in server for w in ["cloudfront", "cloudflare", "akamai"]):
        return True
    if any(w in body_str[:500] for w in waf_indicators):
        return True
    return False

def _range_header_value(byte_range: str) -> str:
    br = byte_range.strip()
    return br if br.lower().startswith("bytes=") else f"bytes={br}"


def _header_value(headers: dict, name: str) -> str | None:
    name_l = name.lower()
    for k, v in headers.items():
        if k.lower() == name_l:
            return v
    return None


def send(method: str, url: str, headers: dict, data: bytes | None,
         auth_key: str | None, timeout: int, save: str | None = None,
         retry: int = 0, retry_wait: float = 1.5,
         want_headers: bool = False, no_redirect: bool = False,
         byte_range: str | None = None) -> dict:
    host = urlparse(url).hostname or "unknown"
    afc = AuthFailCounter()
    if auth_key:
        afc.check(auth_key)            # anti-runaway: stop once locked
    hh = HostHealth()
    hh.check(host)                     # 自熔断: host 在退避冷却期则直接抛 HostBackoff
    sb = SessionBudget()
    sb.check()                         # 整场量熔断: 冷却期直接 abort(跨 host 总量/外渗)

    req_headers = {"User-Agent": UA, **headers}
    if byte_range and not any(k.lower() == "range" for k in req_headers):
        req_headers["Range"] = _range_header_value(byte_range)
    req = urllib.request.Request(url=url, method=method.upper(),
                                 data=data, headers=req_headers)
    summary: dict = {"method": method.upper(), "url": url}
    if byte_range:
        summary["range"] = _header_value(req_headers, "Range")
    opener = _opener(no_redirect)
    last_err: str | None = None
    raw = b""
    status = 0
    resp_headers: dict = {}
    cookie_list: list[str] = []            # ALL Set-Cookie values (dict() would drop dups)
    attempts = 0                           # 真实发出的请求数(含重试), 供整场量精确计数
    for attempt in range(retry + 1):
        attempts += 1
        RateLimiter().gate(host)           # 禁高频(每次实际请求都计入)
        try:
            with opener.open(req, timeout=timeout) as r:
                raw = r.read()
                status = r.status
                resp_headers = dict(r.headers)
                cookie_list = r.headers.get_all("Set-Cookie") or []
            last_err = None
            break
        except urllib.error.HTTPError as e:
            raw = e.read()
            status = e.code
            resp_headers = dict(e.headers or {})
            cookie_list = (e.headers.get_all("Set-Cookie") if e.headers else None) or []
            last_err = None
            break
        except Exception as e:
            last_err = str(e)
            if attempt < retry:
                time.sleep(retry_wait)     # 瞬时超时/RST 重试(如本次 vpn)
    if last_err is not None:
        hh.record_error(host)
        # P1: classify transport error
        err_lower = last_err.lower()
        if 'ssl' in err_lower or 'tls' in err_lower or 'handshake' in err_lower:
            transport_type = "cdn_tls_reject" if 'eof' in err_lower else "transport_error"
        elif 'timeout' in err_lower or 'reset' in err_lower or 'refused' in err_lower or 'unreachable' in err_lower:
            transport_type = "transport_error"
        else:
            transport_type = "transport_error"          # 传输错误: 累计, 达阈值即熔断该 host
        sb.record(0, count=attempts)   # 失败请求(含每次重试)都计入整场量, 防错误洪水绕过会话熔断
        out = {**summary, "error": last_err, "transport_error": True, "error_type": transport_type}
        if retry:
            out["attempts"] = retry + 1
        return out
    hh.record_ok(host)                 # 有 HTTP 响应(含4xx/5xx)=连接健康, 重置错误streak
    warn = hh.soft_warn(host)
    if warn:
        print(warn, file=sys.stderr)
    # JS/CSS 静态资源 >MIN_STATIC_ASSET_BYTES 不计入 bytes budget(防 JS-heavy SPA 的 chunk 下载触发假熔断);
    # 仍计入 count budget。小于阈值的仍正常计(防大量小文件绕过)。
    content_type = (resp_headers.get("Content-Type") or "").lower()
    record_bytes = len(raw)
    if len(raw) >= MIN_STATIC_ASSET_BYTES and any(t in content_type for t in ("javascript", "css")):
        record_bytes = 0
    sb_warn = sb.record(record_bytes, count=attempts)   # 整场请求(含重试)+外渗量计量; 越硬阈值则布防熔断
    if sb_warn:
        print(sb_warn, file=sys.stderr)

    body, truncated = cap_body(raw)
    _full_sha1 = hashlib.sha1(raw).hexdigest()
    _snippet_val, _snippet_enc = _safe_snippet(body, resp_headers.get("Content-Type", ""))
    summary.update({
        "status": status,
        "len": len(raw),
        "truncated": truncated,
        "sha1": _full_sha1[:12],
        "sha1_full": _full_sha1,            # 全 sha1: replay 比对整完整性(不削成 48-bit)
        "ctype": resp_headers.get("Content-Type", ""),
        "server": resp_headers.get("Server", ""),
        "snippet": _snippet_val,
        **_snippet_kwargs(_snippet_enc),
        # P1: 错误分类
        "transport_error": False,
        "application_error": False,
        "auth_failure": False,
        "blocked_by_policy": False,
        "cdn_tls_reject": False,
    })
    # P1: 分类 HTTP 响应
    if status in (401,):
        summary["auth_failure"] = True
    if status in (403,):
        if _is_waf_block(resp_headers, body):
            summary["blocked_by_policy"] = True
        else:
            summary["auth_failure"] = True
    if status in (429, 503):
        summary["blocked_by_policy"] = True
    if status >= 400 and not summary["auth_failure"] and not summary["blocked_by_policy"]:
        summary["application_error"] = True
    if want_headers:
        # 完整响应头(Location/Set-Cookie 等), 分析跳转/会话/WAF 用。
        # dict(r.headers) 对重复 Set-Cookie 只留一个 -> 多 cookie(antiforgery+session)会丢;
        # 用 get_all 把全部 Set-Cookie 合并回 headers, 并单列 set_cookies 列表供会话流程解析。
        if cookie_list:
            resp_headers["Set-Cookie"] = "\n".join(cookie_list)
        summary["headers"] = resp_headers
        summary["set_cookies"] = cookie_list
    if save:
        # write the guard-capped body to a file for full-evidence inspection
        Path(save).parent.mkdir(parents=True, exist_ok=True)
        Path(save).write_bytes(body)
        summary["saved"] = save
        summary["saved_bytes"] = len(body)
        # snippet 覆盖率: 当 body 远超 240-char snippet 时, driver 可能仅依赖 snippet
        # 而遗漏关键内容(codex review 实战教训: 3 次因 body 空/snippet 短导致错误分析)。
        # 此字段告诉 driver "snippet 只涵盖了 X% 的响应, 需要读 saved 文件"。
        snippet_len = min(240, len(body))
        summary["snippet_pct"] = round(snippet_len / max(len(body), 1) * 100, 1)
        if len(body) > 500:
            print(f"[probe] saved {len(body)} bytes → {save}  (snippet covers {summary['snippet_pct']}% only — read the saved file for full content)",
                  file=sys.stderr)
        # 操作录像(.replay.json): 完整请求 + 响应摘要, 让 certainty>=0.8 的证据可被【重放核实】而非
        # 只信描述(B1: 把造假从"P 张图"抬到"伪造自洽的请求+响应+sha1")。响应只存摘要(status/全
        # sha1/len/headers/snippet) —— 全 body 已在 saved 文件, 不重复 dump(守模块"never dumps"原则)。
        replay = {
            "ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "request": {"method": method.upper(), "url": url,
                        "headers": dict(headers),   # 存完整(含 Cookie/Authorization): 重放认证请求需原值;
                        "body": data.decode("utf-8", "replace") if data else None},  # 目标非机密(能上云=不机密), 不脱敏
            "response": {"status": status, "len": len(raw),
                         "sha1": hashlib.sha1(raw).hexdigest(),
                         "ctype": resp_headers.get("Content-Type", ""),
                         "headers": resp_headers,   # 完整响应头(含 Set-Cookie), 供重放/核对
                         "snippet": _snippet_val,
                         **_snippet_kwargs(_snippet_enc)},
            "saved_body": save,
        }
        # 文件名【追加】.replay.json(不用 with_suffix: 它替换最后扩展名 -> a.html/a.txt 都成
        # a.replay.json 互相覆盖、x.tar.gz 丢 .gz —— dogfood 第5次 WARN)。追加保证唯一对应。
        replay_path = save + ".replay.json"
        Path(replay_path).write_text(json.dumps(replay, ensure_ascii=False, indent=2),
                                     encoding="utf-8")
        summary["replay"] = replay_path
    if auth_key:
        # heuristic: 401/403 or a login-ish redirect counts as an auth failure
        ok = status not in (401, 403)
        afc.record(auth_key, ok)
        if afc.would_pivot(auth_key):
            summary["pivot_required"] = True
            summary["pivot_reason"] = (
                f"同一端点 {afc.pivot}+ 次认证失败 — 猜测攻击不会产生新价值。"
                "转向逻辑漏洞/配置错误/未授权API/IDOR/路径穿越。"
            )
    return summary


def _selftest() -> int:
    """Regression for full Set-Cookie capture (dict() used to drop duplicate
    Set-Cookie -> the ASP.NET Core antiforgery flow broke) + --save. Local-only."""
    import http.server
    import re as _re
    import socketserver
    import tempfile
    import threading

    checks: list[tuple[str, bool]] = []
    with selftest_isolation():
        class H(http.server.BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def do_GET(self):
                if self.path.startswith("/range"):
                    b = b"0123456789"
                    if self.headers.get("Range") == "bytes=2-5":
                        part = b[2:6]
                        self.send_response(206)
                        self.send_header("Content-Type", "text/plain")
                        self.send_header("Content-Range", "bytes 2-5/10")
                        self.send_header("Content-Length", str(len(part)))
                        self.end_headers()
                        self.wfile.write(part)
                        return
                    self.send_response(200)
                    self.send_header("Content-Type", "text/plain")
                    self.send_header("Content-Length", str(len(b)))
                    self.end_headers()
                    self.wfile.write(b)
                    return
                if self.path.startswith("/redir"):
                    # 模拟登录成功: 302 跳转, 会话 cookie 设在【这一跳】上(跟随跳转会丢失它)
                    self.send_response(302)
                    self.send_header("Location", "/")
                    self.send_header("Set-Cookie", ".AspNet.ApplicationCookie=AUTH_TOKEN_XYZ; path=/; httponly")
                    self.send_header("Content-Length", "0")
                    self.end_headers()
                    return
                b = b"ok-body"
                self.send_response(200)
                self.send_header("Content-Type", "text/html")
                # two distinct Set-Cookie headers, like ASP.NET Core (cleared external + antiforgery)
                self.send_header("Set-Cookie", "Identity.External=; expires=Thu, 01 Jan 1970 00:00:00 GMT; path=/; httponly")
                self.send_header("Set-Cookie", ".AspNetCore.Antiforgery.abc=CfDJ8_TOKEN; path=/; samesite=strict; httponly")
                self.send_header("Content-Length", str(len(b)))
                self.end_headers()
                self.wfile.write(b)

        srv = socketserver.TCPServer(("127.0.0.1", 0), H)
        port = srv.server_address[1]
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        try:
            tmp = Path(tempfile.mkdtemp()) / "body.html"
            d = send("GET", f"http://127.0.0.1:{port}/", {"Cookie": "sess=secret123"}, None, None, 5,
                     save=str(tmp), want_headers=True)
            sc = d.get("headers", {}).get("Set-Cookie", "")
            cl = d.get("set_cookies", [])
            checks.append(("status 200", d.get("status") == 200))
            checks.append(("both Set-Cookie captured (set_cookies list)", len(cl) == 2))
            checks.append(("Identity.External present in headers", "Identity.External" in sc))
            checks.append(("antiforgery cookie regex-extractable",
                           bool(_re.search(r"\.AspNetCore\.Antiforgery\.[^=]+=[^;]+", sc))))
            checks.append(("--save wrote the body", tmp.is_file() and tmp.read_bytes() == b"ok-body"))
            checks.append(("len/sha1 summarized", d.get("len") == 7 and bool(d.get("sha1"))))
            # 操作录像: --save 同时写 <file>.replay.json(追加扩展名, 非 with_suffix)
            rp = Path(str(tmp) + ".replay.json")
            checks.append(("--save 写了 <file>.replay.json(追加不替换扩展名)", rp.is_file()))
            checks.append(("文件名是 body.html.replay.json(非 body.replay.json, 防同 stem 覆盖)",
                           rp.name == "body.html.replay.json"))
            if rp.is_file():
                rj = json.loads(rp.read_text(encoding="utf-8"))
                hreq = json.dumps(rj["request"]["headers"])
                hresp = json.dumps(rj["response"]["headers"])
                checks.append(("replay 含请求 method/url",
                               rj["request"]["method"] == "GET" and rj["request"]["url"].startswith("http")))
                checks.append(("replay 含响应 status/全sha1",
                               rj["response"]["status"] == 200 and len(rj["response"]["sha1"]) >= 40))
                checks.append(("summary.sha1 == replay.sha1 前缀(截断一致)",
                               d.get("sha1") == rj["response"]["sha1"][:12]))
                checks.append(("请求头完整存(Cookie 原值在, 供重放认证请求)", "sess=secret123" in hreq))
                checks.append(("响应头完整存(Set-Cookie 原值在, 不脱敏)", "Identity.External=" in hresp))
                checks.append(("summary 引用 replay 路径", bool(d.get("replay"))))
            # 认证流: --no-redirect 不跟随 302, 捕获【跳转那一跳】的 Set-Cookie(会话 cookie)
            nr = send("GET", f"http://127.0.0.1:{port}/redir", {}, None, None, 5,
                      want_headers=True, no_redirect=True)
            nr_sc = "\n".join(nr.get("set_cookies", []))
            checks.append(("--no-redirect 拿到 302(不跟随)", nr.get("status") == 302))
            checks.append(("--no-redirect 捕获跳转上的会话 cookie",
                           ".AspNet.ApplicationCookie=AUTH_TOKEN_XYZ" in nr_sc))
            checks.append(("--no-redirect 响应头含 Location", nr.get("headers", {}).get("Location", "") == "/"))
            # 对照: 默认跟随到 200, 会话 cookie 丢失(证明 --no-redirect 对认证流是必要的)
            fr = send("GET", f"http://127.0.0.1:{port}/redir", {}, None, None, 5, want_headers=True)
            checks.append(("默认跟随 -> 200 且会话 cookie 丢(故认证流需 --no-redirect)",
                           fr.get("status") == 200 and "ApplicationCookie" not in "\n".join(fr.get("set_cookies", []))))
            rr = send("GET", f"http://127.0.0.1:{port}/range", {}, None, None, 5,
                      want_headers=True, byte_range="2-5")
            checks.append(("--range sends Range header and receives partial body",
                           rr.get("status") == 206 and rr.get("snippet") == "2345"
                           and rr.get("headers", {}).get("Content-Range") == "bytes 2-5/10"
                           and rr.get("range") == "bytes=2-5"))
            rr2 = send("GET", f"http://127.0.0.1:{port}/range", {"range": "bytes=2-5"},
                       None, None, 5, want_headers=True, byte_range="0-1")
            checks.append(("--range respects caller-supplied Range header casing",
                           rr2.get("status") == 206 and rr2.get("snippet") == "2345"
                           and rr2.get("range") == "bytes=2-5"))
        finally:
            srv.shutdown()
    # 统一布局 _place_save: 裸文件名 + --run -> <run>/evidence/; 显式路径/无 --run 原样
    ps_bare = _place_save("ev_x.html", "runs/t_20260101")
    checks.append(("--run + 裸名 -> <run>/evidence/", Path(ps_bare) == Path("runs/t_20260101/evidence/ev_x.html")))
    checks.append(("--run + 显式路径 -> 原样尊重", _place_save("sub/ev.html", "runs/t") == "sub/ev.html"))
    checks.append(("无 --run -> 原样", _place_save("ev.html", None) == "ev.html"))
    # #3: 无扩展名裸名补 .html(dogfood: --save tomcat9 存成裸名, driver 以为 .html 报错)
    checks.append(("--run + 无扩展名裸名 -> 补 .html 落 evidence/",
                   Path(_place_save("tomcat9", "runs/t")) == Path("runs/t/evidence/tomcat9.html")))
    checks.append(("无 --run + 无扩展名 -> 补 .html", _place_save("foo", None) == "foo.html"))
    checks.append(("已带扩展名不重复补", _place_save("a.json", None) == "a.json"))
    checks.append(("显式路径(含分隔符)无扩展名也不补/不改(Codex#7)", _place_save("sub/tomcat9", "runs/t") == "sub/tomcat9"))
    bad = [n for n, ok in checks if not ok]
    for n, ok in checks:
        print(("ok   " if ok else "FAIL ") + n)
    print("probe selftest " + ("passed" if not bad else f"FAILED ({len(bad)})"))
    return 0 if not bad else 1


def _place_save(save: str | None, run: str | None) -> str | None:
    """统一布局: --run 给定且 --save 是【裸文件名】(无路径分隔)时, 产物落到 <run>/evidence/
    —— 录像 .replay.json 写在 save 旁, 自动一并跟随。--save 已带路径分隔则原样尊重
    (显式路径优先, 向后兼容)。专治证据散落 run 根目录、与草稿混作一团(断-2)。"""
    if not save:
        return save
    if ("/" in save) or ("\\" in save):
        return save                       # 显式路径: 原样尊重(向后兼容), 不补扩展名/不改(Codex#7)
    if "." not in Path(save).name:        # 裸名无扩展名 → 补 .html(#3: --save tomcat9 存成裸名报错;
        save = save + ".html"             # 录像 .replay.json 自动跟随)
    if not run:
        return save
    return str(Path(run) / "evidence" / save)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("method", nargs="?", help="GET/POST/PUT/... or DIFF for a two-URL comparison")
    ap.add_argument("url", nargs="?")
    ap.add_argument("url2", nargs="?", help="second URL for DIFF mode")
    ap.add_argument("--selftest", action="store_true", help="run regression and exit")
    ap.add_argument("--data", default=None)
    ap.add_argument("-H", "--header", action="append", default=[], help="k: v")
    ap.add_argument("--auth-key", default=None,
                    help="endpoint key for the brute-force lock counter")
    ap.add_argument("--timeout", type=int, default=20)
    ap.add_argument("--tag", default=None, help="label recorded with the result")
    ap.add_argument("--save", default=None,
                    help="write the guard-capped response body to this file")
    ap.add_argument("--run", default=None,
                    help="run 目录 runs/<dir>; 给了它且 --save 是裸文件名时, 产物落到 "
                         "<run>/evidence/(统一布局, 防散落根目录; 录像 .replay.json 一并跟随)")
    ap.add_argument("--proxy", default=None,
                    help="交战代理(http://h:p / socks5h://h:p)；解锁境内资产经中继。"
                         "未给则走 harness.proxy 解析(XUNJI_PROXY / proxy.conf, 不读 HTTPS_PROXY=模型那条)")
    ap.add_argument("--retry", type=int, default=0,
                    help="超时/RST 重试次数(瞬时不可达时用)")
    ap.add_argument("--retry-wait", type=float, default=1.5, help="重试间隔秒")
    ap.add_argument("--headers", action="store_true",
                    help="输出完整响应头(Location/Set-Cookie 等)")
    ap.add_argument("--no-redirect", action="store_true",
                    help="不跟随 3xx 跳转 —— 直接拿 302 那一跳(认证流会话 cookie 设在跳转上, 跟随会丢; "
                         "也防被跳转带到 scope 外)")
    ap.add_argument("--range", dest="byte_range", default=None,
                    help="HTTP byte range helper, e.g. 0-262143 or bytes=0-262143. "
                         "Adds a Range header unless one was supplied explicitly.")
    ap.add_argument("--samples", type=int, default=1,
                    help="DIFF 模式每侧采样次数；>1 时做稳定性判定(去噪)")
    args = ap.parse_args()

    if args.selftest:
        return _selftest()
    if not args.method or not args.url:
        ap.error("method and url are required (or use --selftest)")

    args.save = _place_save(args.save, args.run)   # 统一布局: --run 时裸文件名 -> <run>/evidence/

    global _PROXY
    _PROXY = args.proxy   # 仅存 --proxy 覆盖; 真正解析在 _opener(urllib_proxy_handlers), 直跑与 import 都走交战代理

    headers = {}
    for h in args.header:
        if ":" in h:
            k, v = h.split(":", 1)
            headers[k.strip()] = v.strip()
    data = args.data.encode() if args.data else None
    if data and "Content-Type" not in headers:
        headers["Content-Type"] = "application/json"

    try:
        if args.method.upper() == "DIFF":
            if not args.url2:
                print("DIFF needs two URLs", file=sys.stderr)
                return 2
            n = max(1, args.samples)

            def sample(url: str) -> tuple[dict, bool, list]:
                runs = [send("GET", url, headers, None, args.auth_key,
                             args.timeout, None, args.retry, args.retry_wait,
                             args.headers, byte_range=args.byte_range) for _ in range(n)]
                hs = sorted({r.get("sha1") for r in runs})
                return runs[0], len(hs) == 1, hs

            a, a_stable, a_h = sample(args.url)
            b, b_stable, b_h = sample(args.url2)
            same_hash = a.get("sha1") == b.get("sha1")
            out = {"tag": args.tag, "mode": "DIFF", "samples": n,
                   "a": a, "b": b,
                   "a_stable": a_stable, "b_stable": b_stable,
                   "same_len": a.get("len") == b.get("len"),
                   "same_hash": same_hash,
                   "same_status": a.get("status") == b.get("status"),
                   # 仅当两侧各自稳定且彼此不同, 才是可信的布尔差异(去噪后)
                   "reliable_differential": bool(a_stable and b_stable
                                                 and not same_hash),
                   "note": "reliable_differential=true(两侧各自稳定且不同)才是"
                           "布尔注入证据；某侧 *_stable=false 说明该响应本身在波动"
                           "(动态内容/多IP负载均衡)，差异不可信，先排噪"}
            if not a_stable:
                out["a_hashes"] = a_h
            if not b_stable:
                out["b_hashes"] = b_h
        else:
            out = {"tag": args.tag, **send(args.method, args.url, headers,
                                           data, args.auth_key, args.timeout,
                                           args.save, args.retry, args.retry_wait,
                                           args.headers, args.no_redirect,
                                           args.byte_range)}
    except SessionTripped as e:
        out = {"error": f"session-volume-breaker: {e}"}
    except RateBudgetExceeded as e:
        out = {"error": f"rate-limited: {e}"}
    except BruteforceLock as e:
        out = {"error": f"brute-force lock: {e}"}
    except HostBackoff as e:
        out = {"error": f"host-backoff: {e}"}

    print(json.dumps(out, ensure_ascii=False, indent=2))
    return 0 if "error" not in out else 1


if __name__ == "__main__":
    raise SystemExit(main())
