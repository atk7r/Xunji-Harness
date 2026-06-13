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
import hashlib
import json
import os
import ssl
import sys
import time
import urllib.request
from pathlib import Path
from urllib.parse import urlparse

sys.path.insert(0, str(Path(__file__).resolve().parent))
from harness.guard import (RateLimiter, AuthFailCounter, cap_body,  # noqa: E402
                           RateBudgetExceeded, BruteforceLock,
                           HostHealth, HostBackoff, SessionBudget, SessionTripped)

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

# 代理: 通过 --proxy 或环境变量设置。境内资产需经中继时用。
_PROXY: str | None = None


def _opener() -> urllib.request.OpenerDirector:
    handlers: list = [urllib.request.HTTPSHandler(context=_CTX)]
    if _PROXY:
        handlers.append(urllib.request.ProxyHandler({"http": _PROXY,
                                                     "https": _PROXY}))
    else:
        # 显式置空, 不继承系统代理(避免意外走错出口)
        handlers.append(urllib.request.ProxyHandler({}))
    return urllib.request.build_opener(*handlers)


def send(method: str, url: str, headers: dict, data: bytes | None,
         auth_key: str | None, timeout: int, save: str | None = None,
         retry: int = 0, retry_wait: float = 1.5,
         want_headers: bool = False) -> dict:
    host = urlparse(url).hostname or "unknown"
    afc = AuthFailCounter()
    if auth_key:
        afc.check(auth_key)            # anti-runaway: stop once locked
    hh = HostHealth()
    hh.check(host)                     # 自熔断: host 在退避冷却期则直接抛 HostBackoff
    sb = SessionBudget()
    sb.check()                         # 整场量熔断: 冷却期直接 abort(跨 host 总量/外渗)

    req = urllib.request.Request(url=url, method=method.upper(),
                                 data=data, headers={"User-Agent": UA, **headers})
    summary: dict = {"method": method.upper(), "url": url}
    opener = _opener()
    last_err: str | None = None
    raw = b""
    status = 0
    resp_headers: dict = {}
    for attempt in range(retry + 1):
        RateLimiter().gate(host)           # 禁高频(每次实际请求都计入)
        try:
            with opener.open(req, timeout=timeout) as r:
                raw = r.read()
                status = r.status
                resp_headers = dict(r.headers)
            last_err = None
            break
        except urllib.error.HTTPError as e:
            raw = e.read()
            status = e.code
            resp_headers = dict(e.headers or {})
            last_err = None
            break
        except Exception as e:
            last_err = str(e)
            if attempt < retry:
                time.sleep(retry_wait)     # 瞬时超时/RST 重试(如本次 vpn)
    if last_err is not None:
        hh.record_error(host)          # 传输错误: 累计, 达阈值即熔断该 host
        sb.record(0)                   # 失败请求也计入整场量(防多 host 错误洪水绕过会话熔断)
        out = {**summary, "error": last_err}
        if retry:
            out["attempts"] = retry + 1
        return out
    hh.record_ok(host)                 # 有 HTTP 响应(含4xx/5xx)=连接健康, 重置错误streak
    warn = hh.soft_warn(host)
    if warn:
        print(warn, file=sys.stderr)
    sb_warn = sb.record(len(raw))      # 整场请求+外渗量计量; 越硬阈值则布防熔断
    if sb_warn:
        print(sb_warn, file=sys.stderr)

    body, truncated = cap_body(raw)
    summary.update({
        "status": status,
        "len": len(raw),
        "truncated": truncated,
        "sha1": hashlib.sha1(raw).hexdigest()[:12],
        "ctype": resp_headers.get("Content-Type", ""),
        "server": resp_headers.get("Server", ""),
        "snippet": body[:240].decode("utf-8", "replace"),
    })
    if want_headers:
        # 完整响应头(Location/Set-Cookie 等), 分析跳转/会话/WAF 用
        summary["headers"] = resp_headers
    if save:
        # write the guard-capped body to a file for full-evidence inspection
        Path(save).parent.mkdir(parents=True, exist_ok=True)
        Path(save).write_bytes(body)
        summary["saved"] = save
        summary["saved_bytes"] = len(body)
    if auth_key:
        # heuristic: 401/403 or a login-ish redirect counts as an auth failure
        ok = status not in (401, 403)
        afc.record(auth_key, ok)
    return summary


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("method", help="GET/POST/PUT/... or DIFF for a two-URL comparison")
    ap.add_argument("url")
    ap.add_argument("url2", nargs="?", help="second URL for DIFF mode")
    ap.add_argument("--data", default=None)
    ap.add_argument("-H", "--header", action="append", default=[], help="k: v")
    ap.add_argument("--auth-key", default=None,
                    help="endpoint key for the brute-force lock counter")
    ap.add_argument("--timeout", type=int, default=20)
    ap.add_argument("--tag", default=None, help="label recorded with the result")
    ap.add_argument("--save", default=None,
                    help="write the guard-capped response body to this file")
    ap.add_argument("--proxy", default=None,
                    help="代理(http://h:p / socks5://h:p)；解锁境内资产经中继。"
                         "未给则读环境变量 HTTPS_PROXY/ALL_PROXY")
    ap.add_argument("--retry", type=int, default=0,
                    help="超时/RST 重试次数(瞬时不可达时用)")
    ap.add_argument("--retry-wait", type=float, default=1.5, help="重试间隔秒")
    ap.add_argument("--headers", action="store_true",
                    help="输出完整响应头(Location/Set-Cookie 等)")
    ap.add_argument("--samples", type=int, default=1,
                    help="DIFF 模式每侧采样次数；>1 时做稳定性判定(去噪)")
    args = ap.parse_args()

    global _PROXY
    _PROXY = args.proxy or os.environ.get("HTTPS_PROXY") or os.environ.get("ALL_PROXY")

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
                             args.headers) for _ in range(n)]
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
                                           args.headers)}
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
