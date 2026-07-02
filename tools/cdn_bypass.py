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
import ssl
import subprocess
import sys
import urllib.request
from pathlib import Path
from typing import Optional

sys.path.insert(0, str(Path(__file__).resolve().parent))
from harness import proxy as proxymod


def _opener():
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    handlers = proxymod.urllib_proxy_handlers(ssl_context=ctx)
    return urllib.request.build_opener(*handlers)


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
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        resp = urllib.request.urlopen(req, timeout=15)
        entries = json.loads(resp.read())
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
    opener = _opener()
    for ip in ips[:5]:
        for h in test_hosts[:5]:
            try:
                req = urllib.request.Request(f"https://{ip}/",
                                             headers={"Host": h}, method="GET")
                resp = opener.open(req, timeout=10)
                body = resp.read().decode(errors="replace")
                results.append({
                    "ip": ip, "host_header": h, "status": resp.status,
                    "len": len(body),
                    "server": resp.headers.get("Server", ""),
                    "title": (re.findall(r"<title>([^<]*)</title>", body) or [""])[0][:80],
                })
            except urllib.request.HTTPError as e:
                body = e.read().decode(errors="replace")
                if e.code not in (404, 403):
                    results.append({
                        "ip": ip, "host_header": h, "status": e.code,
                        "len": len(body), "error": "http_error",
                    })
            except Exception:
                pass
    return results


def alternate_ports(host: str, ips: list[str],
                    ports: Optional[list[int]] = None) -> list[dict]:
    """6. 非标准端口 — CDN 可能只代理 443，其他端口直连源站"""
    if ports is None:
        ports = [80, 443, 8080, 8443, 10443, 12443, 4443]
    results = []
    for ip in ips[:3]:
        for port in ports:
            try:
                sock = socket.create_connection((ip, port), timeout=5)
                ctx = ssl.create_default_context()
                ctx.check_hostname = False
                ctx.verify_mode = ssl.CERT_NONE
                try:
                    with ctx.wrap_socket(sock, server_hostname=host) as ssock:
                        ssock.send(f"GET / HTTP/1.1\r\nHost: {host}\r\n\r\n".encode())
                        resp = ssock.recv(4096).decode(errors="replace")
                        status = resp.split("\r\n")[0] if resp else ""
                        results.append({
                            "ip": ip, "port": port, "status_line": status[:100],
                            "len": len(resp),
                        })
                except Exception:
                    pass
                finally:
                    try:
                        sock.close()
                    except Exception:
                        pass
            except Exception:
                pass
    return results


def proxy_egress_compare(host: str, path: str = "/") -> dict:
    """9. 代理出口对比 — 直连 vs 代理的响应差异"""
    results = {}
    # Direct
    try:
        req = urllib.request.Request(f"https://{host}{path}", method="GET")
        resp = urllib.request.urlopen(req, timeout=15)
        body = resp.read().decode(errors="replace")
        results["direct"] = {
            "status": resp.status, "len": len(body),
            "server": resp.headers.get("Server", ""),
            "sha1": _sha1(body),
        }
    except Exception as e:
        results["direct"] = {"error": str(e)[:80]}

    # Through proxy
    try:
        opener = _opener()
        req = urllib.request.Request(f"https://{host}{path}", method="GET")
        resp = opener.open(req, timeout=15)
        body = resp.read().decode(errors="replace")
        results["proxy"] = {
            "status": resp.status, "len": len(body),
            "server": resp.headers.get("Server", ""),
            "sha1": _sha1(body),
        }
    except Exception as e:
        results["proxy"] = {"error": str(e)[:80]}

    return results


def _sha1(data: str) -> str:
    import hashlib
    return hashlib.sha1(data.encode()).hexdigest()[:16]


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
    # Check proxy egress
    eg = results.get("proxy_egress_compare", {})
    if eg.get("direct", {}).get("sha1") == eg.get("proxy", {}).get("sha1"):
        reasons.append("代理出口 vs 直连响应相同 — CDN 无差异")
    else:
        reasons.append("代理出口与直连有差异 — 可能是 CDN 地域路由")

    if not reasons:
        return "Type A: CDN 可能可绕过，需进一步验证"
    return "Type B: CDN 不可绕过 — " + "; ".join(reasons[:3])


def run(host: str) -> dict:
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
    results["proxy_egress_compare"] = proxy_egress_compare(host)
    results["type_a_verdict"] = final_type_a_verdict(results)
    return results


def main() -> int:
    ap = argparse.ArgumentParser(description="CDN/WAF 绕过标准检测")
    ap.add_argument("host", help="目标主机名")
    ap.add_argument("--json", action="store_true", help="JSON 输出")
    args = ap.parse_args()

    host = args.host
    if host.startswith("http"):
        from urllib.parse import urlparse
        host = urlparse(host).hostname

    results = run(host)

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
        print(f"Alternate ports: {len(results['alternate_ports'])} open")
        for r in results["alternate_ports"][:5]:
            print(f"  {r['ip']}:{r['port']} → {r.get('status_line','')[:60]}")
        eg = results["proxy_egress_compare"]
        print(f"Direct: {eg.get('direct',{}).get('sha1','?')} Proxy: {eg.get('proxy',{}).get('sha1','?')}")
        print(f"\nVERDICT: {results['type_a_verdict']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
