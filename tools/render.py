#!/usr/bin/env python3
r"""render.py - controlled, read-only browser fetch (P1).

Why it exists: curl cannot pass JS anti-bot challenges or render SPAs, leaving a
large slice of an authorized target's surface untestable. A real browser engine
(Playwright/Chromium) passes a benign "browser environment check" the same way
any user's browser does -- this is access, not a forged bypass.

Discipline:
- READ-ONLY: navigates and observes. Does not submit forms, click destructive
  controls, or run site-changing actions.
- Routed through guard.RateLimiter (禁高频) and guard.cap_body (禁拖库).
- Captures the post-challenge HTML, page title, a screenshot, and the network
  requests the page makes (XHR/fetch) -- which is how it surfaces real backend
  API endpoints for grounding.

For an authenticated page (DOM-XSS modules, post-login SPA), inject the session
you already hold -- a fresh browser context has no cookies and would be bounced to
the login page. This is symmetric to the cookie EXPORT render.py already does:
  --cookie "PHPSESSID=...; security=low"      quick header form (repeatable)
  --cookies-file runs/<dir>/cookies.json      reuse render.py's own export, or a {name:value} dict

Run with the venv python (Playwright lives there); activate the venv first
(.venv/bin/activate on Linux/macOS, .venv\Scripts\activate on Windows):
  python tools/render.py <url> [--out runs/<dir>/render] [--wait networkidle]
  python tools/render.py <url> --cookie "PHPSESSID=abc; security=low"
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from urllib.parse import urlparse

sys.path.insert(0, str(Path(__file__).resolve().parent))
from harness.guard import (RateLimiter, cap_body, RateBudgetExceeded,  # noqa: E402
                           HostHealth, HostBackoff)
from harness import proxy as proxymod  # noqa: E402  渗透流量走交战代理(模型调用不走)

try:
    sys.stdout.reconfigure(encoding="utf-8")       # type: ignore[attr-defined]
    sys.stderr.reconfigure(encoding="utf-8")       # type: ignore[attr-defined]
except Exception:
    pass

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36")

STEALTH = False  # set by --stealth: minimal anti-automation hardening (authorized access)
PROXY = None     # set by --proxy / env: 经中继访问境内资产


def build_cookies(url: str, headers: list[str], cfile: str | None) -> list[dict]:
    """Build a Playwright cookie list (name/value/domain/path) for session injection.

    Sources, both bound to the TARGET host so an IP host (e.g. 192.168.x.x) works:
    - header strings:  --cookie "PHPSESSID=abc; security=low"  (repeatable)
    - a JSON file:     render.py's own cookies.json (a Playwright cookie list) OR a
                       simple {name: value} dict.
    Only name/value/domain/path are carried -- enough to SEND the session; the
    httpOnly/secure/sameSite flags are export-only metadata and would just risk
    Playwright validation errors here, so they are dropped.
    """
    host = urlparse(url).hostname or ""
    out: list[dict] = []

    def add(name: str, value: str) -> None:
        name = (name or "").strip()
        if name:
            out.append({"name": name, "value": str(value).strip(),
                        "domain": host, "path": "/"})

    for h in headers:
        for part in h.split(";"):
            if "=" in part:
                k, v = part.split("=", 1)
                add(k, v)

    if cfile:
        data = json.loads(Path(cfile).read_text(encoding="utf-8"))
        if isinstance(data, dict):
            for k, v in data.items():
                add(k, v)
        elif isinstance(data, list):
            for c in data:               # Playwright cookie dicts (render.py export)
                if isinstance(c, dict) and c.get("name"):
                    add(c["name"], c.get("value", ""))
    return out


def render(url: str, out_dir: Path, wait: str, timeout_ms: int,
           cookies: list[dict] | None = None) -> dict:
    try:
        from playwright.sync_api import sync_playwright
    except Exception as e:  # pragma: no cover
        return {"error": f"playwright unavailable: {e}. Run with the venv python."}

    host = urlparse(url).hostname or "unknown"
    hh = HostHealth()
    hh.check(host)            # 自熔断: host 在退避冷却期则抛 HostBackoff
    RateLimiter().gate(host)  # 禁高频: spacing enforced before navigation

    out_dir.mkdir(parents=True, exist_ok=True)
    requests: list[dict] = []
    result: dict = {"url": url, "host": host}

    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=True,
            args=["--disable-blink-features=AutomationControlled"] if STEALTH else [])
        ctx_kwargs = dict(user_agent=UA, ignore_https_errors=True, locale="zh-CN")
        if PROXY:
            ctx_kwargs["proxy"] = {"server": PROXY}
        ctx = browser.new_context(**ctx_kwargs)
        if cookies:
            # inject an already-held session so authenticated pages render instead
            # of 302-ing to login (read-only: we navigate, we do not submit)
            ctx.add_cookies(cookies)
            result["injected_cookies"] = [c["name"] for c in cookies]
        if STEALTH:
            # Minimal anti-automation hardening for authorized access to anti-bot
            # gated pages: stop the engine announcing itself as automated. This
            # lets the page's own challenge JS run naturally -- it does NOT forge
            # the challenge's server-validated token.
            ctx.add_init_script(
                "Object.defineProperty(navigator,'webdriver',{get:()=>undefined});"
                "window.chrome={runtime:{}};"
                "Object.defineProperty(navigator,'languages',{get:()=>['zh-CN','zh']});"
                "Object.defineProperty(navigator,'plugins',{get:()=>[1,2,3]});"
            )
        page = ctx.new_page()

        # observe (not intercept) network -> reveals backend API endpoints
        page.on("requestfinished", lambda r: requests.append(
            {"method": r.method, "url": r.url,
             "type": r.resource_type,
             "status": (r.response().status if r.response() else None)}))

        try:
            resp = page.goto(url, wait_until=wait, timeout=timeout_ms)
            result["final_url"] = page.url
            result["status"] = resp.status if resp else None
            result["title"] = page.title()
            html = page.content().encode("utf-8", "replace")
            body, truncated = cap_body(html)
            (out_dir / "page.html").write_bytes(body)
            result["html_bytes"] = len(html)
            result["html_truncated"] = truncated
            page.screenshot(path=str(out_dir / "page.png"), full_page=False)
            # keep only app/api-ish requests (drop static asset noise) for grounding
            api = [r for r in requests
                   if r["type"] in ("xhr", "fetch")
                   or any(k in r["url"] for k in ("/api", "/rest", ".do", ".json", "/v1", "/v2"))]
            result["api_requests"] = api[:200]
            (out_dir / "network.json").write_text(
                json.dumps(requests[:500], ensure_ascii=False, indent=2), encoding="utf-8")
            # export cookies so a browser-obtained session (e.g. an anti-bot
            # client_id) can be handed to probe.py for active proof
            cookies = ctx.cookies()
            result["cookies"] = {c["name"]: c["value"] for c in cookies}
            result["cookie_header"] = "; ".join(
                f"{c['name']}={c['value']}" for c in cookies)
            (out_dir / "cookies.json").write_text(
                json.dumps(cookies, ensure_ascii=False, indent=2), encoding="utf-8")
        except Exception as e:
            result["error"] = str(e)
        finally:
            ctx.close()
            browser.close()
    # circuit breaker: a navigation that returned a status = healthy connection;
    # an exception (timeout/reset/refused) = transport failure for this host
    if result.get("error") and result.get("status") is None:
        hh.record_error(host)
    else:
        hh.record_ok(host)
    return result


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("url")
    ap.add_argument("--out", default=None, help="artifact dir (default tmp/render/<host>)")
    ap.add_argument("--run", default=None,
                    help="run 目录 runs/<dir>; 未给 --out 时产物默认落 <run>/evidence/render_<host>/"
                         "(统一布局, 防散落根目录)")
    ap.add_argument("--wait", default="networkidle",
                    choices=["load", "domcontentloaded", "networkidle"])
    ap.add_argument("--timeout", type=int, default=30000)
    ap.add_argument("--stealth", action="store_true",
                    help="minimal anti-automation hardening for authorized access to "
                         "anti-bot-gated pages (does not forge challenge tokens)")
    ap.add_argument("--proxy", default=None,
                    help="交战代理(http://h:p / socks5h://h:p)；经中继访问境内资产。"
                         "未给则走 harness.proxy(XUNJI_PROXY / proxy.conf, 不读 HTTPS_PROXY=模型那条)")
    ap.add_argument("--cookie", action="append", default=[],
                    help="注入会话 cookie(认证后页面用),形如 'PHPSESSID=abc; security=low';可重复")
    ap.add_argument("--cookies-file", default=None,
                    help="从 JSON 读 cookie:render.py 导出的 cookies.json(playwright 列表)"
                         "或 {name:value} 字典;与 --cookie 合并")
    args = ap.parse_args()

    global STEALTH, PROXY
    STEALTH = args.stealth
    PROXY = proxymod.resolve(args.proxy)   # 交战代理(XUNJI_PROXY/proxy.conf/--proxy); required 时没配 fail-closed

    host = urlparse(args.url).hostname or "page"
    if args.out:
        out_dir = Path(args.out)
    elif args.run:
        out_dir = Path(args.run) / "evidence" / f"render_{host}"   # 统一布局
    else:
        out_dir = Path("tmp") / "render" / host
    cookies = build_cookies(args.url, args.cookie, args.cookies_file)
    try:
        res = render(args.url, out_dir, args.wait, args.timeout, cookies)
    except RateBudgetExceeded as e:
        res = {"error": f"rate-limited: {e}"}
    except HostBackoff as e:
        res = {"error": f"host-backoff: {e}"}

    print(json.dumps(res, ensure_ascii=False, indent=2))
    return 0 if "error" not in res else 1


if __name__ == "__main__":
    raise SystemExit(main())
