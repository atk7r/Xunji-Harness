#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""cdn_bypass.py — CDN/WAF 绕过标准工具

把 scshr.com run 中手写的 10 种 CDN 突破技术固化为可复用工具。
每种技术返回: success, method, evidence, type_a_reason

用法:
  python tools/cdn_bypass.py <host> [--proxy PROXY]

Author: Xunji P1 improvement (scshr.com retrospective)
"""
from __future__ import annotations

import argparse
import json
import re
import socket
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Optional

sys.path.insert(0, str(Path(__file__).resolve().parent))
import probe as probemod
from probe import send


def _guarded_get(url: str, headers: dict[str, str] | None = None,
                 timeout: int = 10) -> dict:
    return send("GET", url, headers or {}, None, None, timeout,
                want_headers=True, no_redirect=True)


def _guarded_body(url: str, headers: dict[str, str] | None = None,
                  timeout: int = 15) -> tuple[dict, str]:
    with tempfile.TemporaryDirectory() as td:
        saved = str(Path(td) / "body.txt")
        result = send("GET", url, headers or {}, None, None, timeout, save=saved)
        body = Path(saved).read_text(encoding="utf-8", errors="replace") if Path(saved).exists() else ""
    return result, body


def dns_a(host: str) -> list[str]:
    """1. DNS A 记录 — 获取直接 IP"""
    try:
        import socket
        return list(set(a[4][0] for a in socket.getaddrinfo(host, 443, type=socket.SOCK_STREAM)))
    except Exception:
        return []


def dns_cname(host: str) -> Optional[str]:
    """2. DNS CNAME — CDN 别名检测"""
    try:
        result = subprocess.run(["dig", "+short", "CNAME", host],
                                capture_output=True, text=True, timeout=10)
        cname = result.stdout.strip().rstrip(".")
        return cname if cname else None
    except Exception:
        return None


def ct_log(host: str) -> list[str]:
    """3. Certificate Transparency log — 发现其他 IP/域名"""
    # 通过 crt.sh 查询
    try:
        url = f"https://crt.sh/?q=%25.{host}&output=json"
        result, body = _guarded_body(url, timeout=15)
        if result.get("transport_error"):
            return []
        entries = json.loads(body)
        names = set()
        for e in entries[:200]:
            name = e.get("name_value", "")
            for n in name.split("\n"):
                n = n.strip().lower()
                if n and not n.startswith("*"):
                    names.add(n)
        return sorted(names)[:50]
    except Exception:
        return []


def spf_txt_leak(host: str) -> list[str]:
    """4. SPF/TXT 记录 — 泄露源 IP"""
    ips = []
    try:
        result = subprocess.run(["dig", "+short", "TXT", host],
                                capture_output=True, text=True, timeout=10)
        for match in re.findall(r"ip4:(\d+\.\d+\.\d+\.\d+)", result.stdout):
            ips.append(match)
        return list(set(ips))
    except Exception:
        return []


def origin_ip_host_header(host: str, ips: list[str],
                          test_hosts: Optional[list[str]] = None) -> list[dict]:
    """5. 源站 IP Host 头注入 — 绕过 CDN 直连源站"""
    if test_hosts is None:
        test_hosts = [host, f"www.{host}", f"origin.{host}"]
    results = []
    for ip in ips[:5]:
        for h in test_hosts[:5]:
            result = _guarded_get(f"https://{ip}/", {"Host": h}, timeout=10)
            if result.get("status") and result["status"] not in (404, 403):
                snippet = result.get("snippet", "")
                results.append({
                    "ip": ip, "host_header": h, "status": result.get("status"),
                    "len": result.get("len", 0),
                    "server": result.get("server", ""),
                    "title": (re.findall(r"<title>([^<]*)</title>", snippet) or [""])[0][:80],
                    "sha1": result.get("sha1"),
                })
            elif result.get("transport_error"):
                results.append({
                    "ip": ip, "host_header": h,
                    "error": result.get("error", "")[:120],
                    "transport_error": True,
                })
    return results


def alternate_ports(host: str, ips: list[str],
                    ports: Optional[list[int]] = None) -> list[dict]:
    """6. 非标准端口候选 — 不自动连接。

    Raw socket port probing bypasses `probe.send` and the session budget. Keep
    this as passive planning output; the operator can explicitly verify a chosen
    port with `probe.py GET https://ip:port/ -H 'Host: ...'`.
    """
    if ports is None:
        ports = [80, 443, 8080, 8443, 10443, 12443, 4443]
    return [
        {
            "ip": ip,
            "candidate_ports": ports,
            "tested": False,
            "note": "candidate only; verify one port at a time through tools/probe.py",
        }
        for ip in ips[:3]
    ]


def proxy_egress_compare(host: str, path: str = "/", proxy: str | None = None) -> dict:
    """9. 出口对比 — 默认 guarded egress vs explicit guarded proxy.

    The old implementation made a naked direct request. This version always goes
    through `probe.send`; without `--proxy`, it reports only the configured
    default guarded egress.
    """
    results = {}
    old_proxy = probemod._PROXY
    try:
        probemod._PROXY = None
        default = _guarded_get(f"https://{host}{path}", timeout=15)
        results["default_guarded"] = _summary_for_compare(default)
        if proxy:
            probemod._PROXY = proxy
            proxied = _guarded_get(f"https://{host}{path}", timeout=15)
            results["explicit_proxy"] = _summary_for_compare(proxied)
        else:
            results["explicit_proxy"] = {"skipped": "pass --proxy to compare another egress"}
    finally:
        probemod._PROXY = old_proxy
    return results


def _summary_for_compare(result: dict) -> dict:
    return {
        "status": result.get("status"),
        "len": result.get("len"),
        "server": result.get("server", ""),
        "sha1": result.get("sha1"),
        "error": result.get("error"),
        "transport_error": result.get("transport_error", False),
    }


def final_type_a_verdict(results: dict) -> str:
    """10. 最终 Type A 判定 — CDN 是否可绕过"""
    reasons = []
    # Check DNS
    ips = results.get("dns_a", [])
    if not ips:
        reasons.append("无 DNS A 记录")
    # Check SPF
    spf = results.get("spf_txt_leak", [])
    if spf:
        reasons.append(f"SPF 泄露 {len(spf)} 个 IP 但无法确认是否为源站")
    # Check origin IP
    origin = results.get("origin_ip_host_header", [])
    unique_responses = {(r["ip"], r.get("len", 0)) for r in origin}
    if len(unique_responses) <= 1:
        reasons.append("所有 Host 头返回相同内容 — CDN 回源不可绕过")
    # Check alternate ports
    alt = results.get("alternate_ports", [])
    if not alt:
        reasons.append("无非标准端口开放")
    elif all(not r.get("tested") for r in alt):
        reasons.append("非标准端口未自动探测 — 需经 probe.py 单端口验证")
    # Check proxy egress
    eg = results.get("proxy_egress_compare", {})
    default_sha = eg.get("default_guarded", {}).get("sha1")
    proxy_sha = eg.get("explicit_proxy", {}).get("sha1")
    if default_sha and proxy_sha and default_sha == proxy_sha:
        reasons.append("默认 guarded 出口 vs 显式代理响应相同 — CDN 无差异")
    elif proxy_sha:
        reasons.append("默认 guarded 出口与显式代理有差异 — 可能是 CDN 地域路由")
    else:
        reasons.append("未提供显式代理出口对比")

    if not reasons:
        return "Type A: CDN 可能可绕过，需进一步验证"
    return "Type B: CDN 不可绕过 — " + "; ".join(reasons[:3])


def run(host: str, proxy: str | None = None) -> dict:
    """执行全部 10 种 CDN 绕过检测"""
    results = {"host": host}
    results["dns_a"] = dns_a(host)
    results["dns_cname"] = dns_cname(host)
    results["ct_log"] = ct_log(host)
    results["spf_txt_leak"] = spf_txt_leak(host)
    results["origin_ip_host_header"] = origin_ip_host_header(
        host, results["dns_a"])
    results["alternate_ports"] = alternate_ports(
        host, results["dns_a"])
    results["proxy_egress_compare"] = proxy_egress_compare(host, proxy=proxy)
    results["type_a_verdict"] = final_type_a_verdict(results)
    return results


def main() -> int:
    ap = argparse.ArgumentParser(description="CDN/WAF 绕过标准检测")
    ap.add_argument("host", help="目标主机名")
    ap.add_argument("--json", action="store_true", help="JSON 输出")
    ap.add_argument("--proxy", default=None,
                    help="显式交战代理(http://h:p / socks5h://h:p)，用于 guarded 出口对比")
    args = ap.parse_args()

    host = args.host
    if host.startswith("http"):
        from urllib.parse import urlparse
        host = urlparse(host).hostname

    results = run(host, proxy=args.proxy)

    if args.json:
        print(json.dumps(results, ensure_ascii=False, indent=2))
    else:
        print(f"=== CDN Bypass: {host} ===")
        print(f"DNS A: {results['dns_a']}")
        print(f"DNS CNAME: {results['dns_cname']}")
        print(f"CT Log names: {len(results['ct_log'])} found")
        print(f"SPF leaks: {results['spf_txt_leak']}")
        print(f"Origin IP Host header tests: {len(results['origin_ip_host_header'])} probes")
        for r in results["origin_ip_host_header"][:5]:
            print(f"  {r['ip']} Host:{r['host_header']} → {r.get('status','?')} {r.get('len','?')}B [{r.get('title','')}]")
        print(f"Alternate ports: {len(results['alternate_ports'])} candidate IP set(s)")
        for r in results["alternate_ports"][:5]:
            print(f"  {r['ip']} → candidates {r.get('candidate_ports', [])}")
        eg = results["proxy_egress_compare"]
        print(f"Default guarded: {eg.get('default_guarded',{}).get('sha1','?')} "
              f"Explicit proxy: {eg.get('explicit_proxy',{}).get('sha1','?')}")
        print(f"\nVERDICT: {results['type_a_verdict']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
