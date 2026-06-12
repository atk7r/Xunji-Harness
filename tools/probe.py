#!/usr/bin/env python3
"""probe.py - active HTTP verifier (P2).

Sends crafted requests (any method/header/body/payload) to PROVE a vulnerability
exists, then stops. This is the proof-only verification primitive the skill
explicitly permits (SQLi differential, SSTI eval echo, auth-bypass, IDOR
existence) -- bounded by the guard layer:

- RateLimiter (禁高频), cap_body (禁拖库: oversized bodies truncated),
  AuthFailCounter (防失控: probe's auth loop locks after N fails).
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
import ssl
import sys
import urllib.request
from pathlib import Path
from urllib.parse import urlparse

sys.path.insert(0, str(Path(__file__).resolve().parent))
from harness.guard import (RateLimiter, AuthFailCounter, cap_body,  # noqa: E402
                           RateBudgetExceeded, BruteforceLock)

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36")
_CTX = ssl.create_default_context()
_CTX.check_hostname = False
_CTX.verify_mode = ssl.CERT_NONE


def send(method: str, url: str, headers: dict, data: bytes | None,
         auth_key: str | None, timeout: int) -> dict:
    host = urlparse(url).hostname or "unknown"
    afc = AuthFailCounter()
    if auth_key:
        afc.check(auth_key)            # anti-runaway: stop once locked
    RateLimiter().gate(host)           # 禁高频

    req = urllib.request.Request(url=url, method=method.upper(),
                                 data=data, headers={"User-Agent": UA, **headers})
    summary: dict = {"method": method.upper(), "url": url}
    try:
        with urllib.request.urlopen(req, timeout=timeout, context=_CTX) as r:
            raw = r.read()
            status = r.status
            resp_headers = dict(r.headers)
    except urllib.error.HTTPError as e:
        raw = e.read()
        status = e.code
        resp_headers = dict(e.headers or {})
    except Exception as e:
        return {**summary, "error": str(e)}

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
    args = ap.parse_args()

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
            a = send("GET", args.url, headers, None, args.auth_key, args.timeout)
            b = send("GET", args.url2, headers, None, args.auth_key, args.timeout)
            out = {"tag": args.tag, "mode": "DIFF", "a": a, "b": b,
                   "same_len": a.get("len") == b.get("len"),
                   "same_hash": a.get("sha1") == b.get("sha1"),
                   "same_status": a.get("status") == b.get("status"),
                   "note": "a controlled true/false differential that changes "
                           "len/hash/status is boolean-injection evidence; "
                           "identical responses refute it"}
        else:
            out = {"tag": args.tag, **send(args.method, args.url, headers,
                                           data, args.auth_key, args.timeout)}
    except RateBudgetExceeded as e:
        out = {"error": f"rate-limited: {e}"}
    except BruteforceLock as e:
        out = {"error": f"brute-force lock: {e}"}

    print(json.dumps(out, ensure_ascii=False, indent=2))
    return 0 if "error" not in out else 1


if __name__ == "__main__":
    raise SystemExit(main())
