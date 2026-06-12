#!/usr/bin/env python3
"""render.py - controlled, read-only browser fetch (P1).

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

Run with the venv python (Playwright lives there):
  .venv/Scripts/python.exe tools/render.py <url> [--out runs/<dir>/render] [--wait networkidle]
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from urllib.parse import urlparse

sys.path.insert(0, str(Path(__file__).resolve().parent))
from harness.guard import RateLimiter, cap_body, RateBudgetExceeded  # noqa: E402

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36")

STEALTH = False  # set by --stealth: minimal anti-automation hardening (authorized access)


def render(url: str, out_dir: Path, wait: str, timeout_ms: int) -> dict:
    try:
        from playwright.sync_api import sync_playwright
    except Exception as e:  # pragma: no cover
        return {"error": f"playwright unavailable: {e}. Run with the venv python."}

    host = urlparse(url).hostname or "unknown"
    RateLimiter().gate(host)  # 禁高频: spacing enforced before navigation

    out_dir.mkdir(parents=True, exist_ok=True)
    requests: list[dict] = []
    result: dict = {"url": url, "host": host}

    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=True,
            args=["--disable-blink-features=AutomationControlled"] if STEALTH else [])
        ctx = browser.new_context(user_agent=UA, ignore_https_errors=True,
                                  locale="zh-CN")
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
    return result


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("url")
    ap.add_argument("--out", default=None, help="artifact dir (default tmp/render/<host>)")
    ap.add_argument("--wait", default="networkidle",
                    choices=["load", "domcontentloaded", "networkidle"])
    ap.add_argument("--timeout", type=int, default=30000)
    ap.add_argument("--stealth", action="store_true",
                    help="minimal anti-automation hardening for authorized access to "
                         "anti-bot-gated pages (does not forge challenge tokens)")
    args = ap.parse_args()

    global STEALTH
    STEALTH = args.stealth

    host = urlparse(args.url).hostname or "page"
    out_dir = Path(args.out) if args.out else Path("tmp") / "render" / host
    try:
        res = render(args.url, out_dir, args.wait, args.timeout)
    except RateBudgetExceeded as e:
        res = {"error": f"rate-limited: {e}"}

    print(json.dumps(res, ensure_ascii=False, indent=2))
    return 0 if "error" not in res else 1


if __name__ == "__main__":
    raise SystemExit(main())
