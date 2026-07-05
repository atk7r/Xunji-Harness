#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""harness/proxy.py — 交战出口代理(opsec egress)。

铁律: **所有渗透流量**(probe / render / scan + 任何打目标的脚本)走【交战代理】XUNJI_PROXY;
**模型调用**(peer_review 的 codex / deepseek / glm / claude, 任何 LLM API)【绝不】走交战代理。

为什么用【专用】XUNJI_PROXY 而非 HTTPS_PROXY: HTTPS_PROXY 是系统级共享变量, codex CLI / urllib /
requests 都自动继承 —— 若把交战代理塞进 HTTPS_PROXY, 模型调用会跟着走代理(模型流量/密钥经目标侧
中继 = 串味 + 泄露)。所以交战代理走【专用】XUNJI_PROXY, 只有 active 工具显式读它; 模型调用另外【强制
剥代理】(model_safe_env / model_no_proxy_opener), 双保险。

fail-closed: XUNJI_PROXY_REQUIRED=1 时, active 工具没配代理就【拒绝直连】(防真实 IP 泄露), 不静默直连。

配置(优先级): `--proxy` 参数 > `XUNJI_PROXY` 环境变量 > `tools/harness/proxy.conf`(每行一个 url, # 注释)。
支持 http:// 与 socks5://; **建议 socks5h://**(代理侧解析 DNS, 防 DNS 泄露; socks4a 在 PySocks 某些失败下
会回退本地解析 = DNS 泄露, 别用)。proxy.conf 已 gitignore。

脚本注意(铁律的"包括脚本"): PoC / runs 脚本做【直连 HTTP】必须 `import harness.proxy` 用 urllib_proxy_handlers
建 opener(或 subprocess 调 tools/probe.py)—— 否则绕过交战代理直连, 泄露真实 IP。poc_library/* 与 runs/* 里
既有的裸 urllib 脚本是【交付/归档】产物, 操作者跑时设 XUNJI_PROXY 并走 probe, 勿裸跑。
"""
from __future__ import annotations

import os
import urllib.request
from pathlib import Path

_CONF = Path(__file__).resolve().parent / "proxy.conf"   # gitignored: 一行一个 url
_SOCKS_INIT_PATCHED = False  # 防 urllib_proxy_handlers 每次调用都重新 patch SocksiPyConnectionS
# 所有需要从【模型子进程 env】里剥掉的代理变量(大小写都剥)
_PROXY_VARS = ("XUNJI_PROXY", "HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "FTP_PROXY",
               "http_proxy", "https_proxy", "all_proxy", "ftp_proxy")


def engagement_proxy(override: str | None = None) -> str | None:
    """交战代理 URL: override > XUNJI_PROXY > proxy.conf。返回 None = 直连。
    【刻意不读 HTTPS_PROXY/ALL_PROXY】—— 那是共享变量, 读它会和模型调用串味。"""
    if override and override.strip():
        return override.strip()
    v = (os.environ.get("XUNJI_PROXY") or "").strip()
    if v:
        return v
    if _CONF.exists():
        for ln in _CONF.read_text(encoding="utf-8", errors="replace").splitlines():
            ln = ln.strip()
            if ln and not ln.startswith("#"):
                return ln
    return None


def required() -> bool:
    """XUNJI_PROXY_REQUIRED=1 → 强制: active 工具没代理就拒绝直连(fail-closed)。"""
    return (os.environ.get("XUNJI_PROXY_REQUIRED") or "").strip().lower() in ("1", "true", "yes", "on")


def resolve(override: str | None = None) -> str | None:
    """active 工具用: 返回须用的交战代理。required 但没配 → fail-closed 抛 SystemExit(不许直连泄真实 IP)。"""
    p = engagement_proxy(override)
    if p is None and required():
        raise SystemExit(
            "[proxy] XUNJI_PROXY_REQUIRED=1 但未配置交战代理 —— 拒绝直连(防真实 IP 泄露)。"
            " 设 XUNJI_PROXY=socks5h://host:port 或写一行进 tools/harness/proxy.conf。")
    return p


def urllib_proxy_handlers(override: str | None = None, ssl_context=None) -> list:
    """urllib active 工具(probe + 【所有 import probe.send 的工具】: classify_hosts/fetch_assets/replay/
    rerun_deferred)用: 据【解析后的交战代理】返回【完整连接 handler 列表(含 HTTPS handler)】。
    **调用方不要再自己 append HTTPSHandler** —— 否则普通 HTTPSHandler 会和 SocksiPyHandler 抢 https_open,
    socks 连不上时悄悄走【直连】泄露真实 IP(实测坏代理仍回 200 的坑)。
    - None → [HTTPSHandler, 空 ProxyHandler](关掉 env 代理回退, 不偷用 HTTPS_PROXY=模型那条)。
    - http(s):// → [HTTPSHandler, ProxyHandler]。
    - socks5(h):// / socks4(a):// → [SocksiPyHandler] **仅此一个**(它自身即 HTTP+HTTPS handler 经 socks,
      build_opener 不会再补默认 HTTPS → 无直连旁路; ...5h/...4a = 代理侧解析 DNS 防 DNS 泄露)。
      需 PySocks; 没装 → SystemExit(绝不静默直连泄真实 IP)。
    内部 resolve() —— import probe.send 的工具不传 override 也拿到交战代理, required 时 fail-closed。"""
    https = urllib.request.HTTPSHandler(context=ssl_context)
    p = resolve(override)
    if not p:
        return [https, urllib.request.ProxyHandler({})]
    low = p.lower()
    if low.startswith(("socks5://", "socks5h://", "socks4://", "socks4a://")):
        try:
            import socks
            from sockshandler import SocksiPyHandler, SocksiPyConnectionS
            # Monkey-patch: Python 3.10+ httplib.HTTPSConnection 不再默认设 _check_hostname,
            # 但 SocksiPyConnectionS.connect() 仍访问它 → AttributeError。补上默认值 False。
            # 用模块级 flag 防每次 urllib_proxy_handlers() 调用都重新 wrap __init__。
            global _SOCKS_INIT_PATCHED
            if not _SOCKS_INIT_PATCHED:
                _orig_init = SocksiPyConnectionS.__init__
                def _patched_init(self, *a, **kw):
                    _orig_init(self, *a, **kw)
                    if not hasattr(self, '_check_hostname'):
                        self._check_hostname = False
                SocksiPyConnectionS.__init__ = _patched_init
                _SOCKS_INIT_PATCHED = True
        except ImportError:
            raise SystemExit("[proxy] socks 代理需要 PySocks: `pip install PySocks`(或改用 http:// 代理)。"
                             " 不静默直连(防真实 IP 泄露)。")
        from urllib.parse import urlparse
        u = urlparse(p)
        stype = socks.SOCKS5 if low.startswith(("socks5://", "socks5h://")) else socks.SOCKS4
        rdns = low.startswith(("socks5h://", "socks4a://"))   # h/a = 远端解析 DNS
        # SocksiPyHandler 自身覆盖 http+https(经 socks), 传 ssl_context 给底层 HTTPSConnection。
        # 【不】另加普通 HTTPSHandler —— 否则它会抢 https 走直连, socks 失败=静默直连旁路(已实测的坑)。
        # 另【显式】加空 ProxyHandler({}): 否则 build_opener 会补一个【读 env】的默认 ProxyHandler,
        # 让 socks 模式的 https 先经 ambient HTTPS_PROXY(=模型那条)= 串味(Codex round-3 WARN#4)。
        return [SocksiPyHandler(stype, u.hostname, u.port or 1080, rdns, u.username, u.password,
                                context=ssl_context),
                urllib.request.ProxyHandler({})]
    return [https, urllib.request.ProxyHandler({"http": p, "https": p})]


def model_no_proxy_opener() -> urllib.request.OpenerDirector:
    """模型 urllib API 调用用: 空 ProxyHandler → 绝不走任何代理(含 env 里的 HTTPS_PROXY)。"""
    return urllib.request.build_opener(urllib.request.ProxyHandler({}))


def model_safe_env(base: dict | None = None) -> dict:
    """模型子进程(codex CLI 等)用 env: 剥掉所有代理变量 + NO_PROXY=* —— 模型调用绝不进交战代理。"""
    env = dict(os.environ if base is None else base)
    for k in _PROXY_VARS:
        env.pop(k, None)
    env["NO_PROXY"] = "*"
    env["no_proxy"] = "*"
    return env


def scrub_proxy_env(base: dict | None = None) -> dict:
    """渗透子进程(sqlmap / nuclei 等)用 env: 剥掉所有代理变量【不设 NO_PROXY】—— 让工具【只】走显式
    传入的 --proxy(=交战代理), 不偷读 ambient HTTPS_PROXY(可能是模型那条/或残留, 走错出口)。
    没传 --proxy 时 = 直连(env 已无代理)。与 model_safe_env 区别: 不设 NO_PROXY, 以免压掉显式 --proxy。"""
    env = dict(os.environ if base is None else base)
    for k in _PROXY_VARS:
        env.pop(k, None)
    return env


def status() -> dict:
    p = engagement_proxy()
    src = ("XUNJI_PROXY" if (os.environ.get("XUNJI_PROXY") or "").strip()
           else "proxy.conf" if (p and _CONF.exists()) else "none")
    return {"engagement_proxy": p, "required": required(), "source": src}


def _selftest() -> int:
    checks = []
    old_env = {k: os.environ.get(k) for k in _PROXY_VARS + ("XUNJI_PROXY_REQUIRED",)}
    old_conf = globals()["_CONF"]
    try:
        # Ignore the developer's gitignored proxy.conf; these checks need a clean
        # "no engagement proxy configured" baseline.
        globals()["_CONF"] = Path("__xunji_no_proxy_conf__")
        for k in _PROXY_VARS:
            os.environ.pop(k, None)
        os.environ.pop("XUNJI_PROXY_REQUIRED", None)

        os.environ["XUNJI_PROXY"] = "socks5h://env:1080"
        checks.append(("override 胜过 env", engagement_proxy("http://arg:8080") == "http://arg:8080"))
        checks.append(("env XUNJI_PROXY 次之", engagement_proxy() == "socks5h://env:1080"))
        os.environ.pop("XUNJI_PROXY", None)
        os.environ["HTTPS_PROXY"] = "http://model-proxy:3128"   # 故意设, 验证交战侧不读它
        checks.append(("交战代理【不读】HTTPS_PROXY(与模型隔离)", engagement_proxy() is None))
        # urllib handlers: 没配交战代理→空 handler(不回退 HTTPS_PROXY); http→ProxyHandler; socks→SocksiPyHandler
        h0 = urllib_proxy_handlers(None)
        pn = [x for x in h0 if type(x).__name__ == "ProxyHandler"]
        checks.append(("无交战代理→空 ProxyHandler(不回退 env, 防串味)", bool(pn) and pn[0].proxies == {}))
        h1 = urllib_proxy_handlers("http://p:8080")
        p1 = [x for x in h1 if type(x).__name__ == "ProxyHandler"]
        checks.append(("http 交战代理→ProxyHandler 带代理", bool(p1) and p1[0].proxies.get("https") == "http://p:8080"))
        try:
            h2 = urllib_proxy_handlers("socks5h://relay:1080")
        except SystemExit as e:
            checks.append(("socks 可选依赖缺失 -> selftest 说明性跳过, 运行时仍 fail-closed",
                           "PySocks" in str(e)))
        else:
            names2 = [type(x).__name__ for x in h2]
            pn2 = [x for x in h2 if type(x).__name__ == "ProxyHandler"]
            checks.append(("socks→SocksiPyHandler + 空ProxyHandler, 无竞争 HTTPSHandler(防直连旁路 + 防 ambient 串味)",
                           "SocksiPyHandler" in names2 and "HTTPSHandler" not in names2
                           and bool(pn2) and pn2[0].proxies == {}))
        # model 隔离
        env = model_safe_env({"HTTPS_PROXY": "x", "XUNJI_PROXY": "y", "http_proxy": "z", "PATH": "/bin"})
        checks += [
            ("model_safe_env 剥 HTTPS_PROXY", "HTTPS_PROXY" not in env),
            ("model_safe_env 剥 XUNJI_PROXY", "XUNJI_PROXY" not in env),
            ("model_safe_env 剥小写 http_proxy", "http_proxy" not in env),
            ("model_safe_env NO_PROXY=*", env.get("NO_PROXY") == "*" and env.get("no_proxy") == "*"),
            ("model_safe_env 保留无关变量", env.get("PATH") == "/bin"),
            ("model opener 空代理", model_no_proxy_opener() is not None),
        ]
        senv = scrub_proxy_env({"HTTPS_PROXY": "x", "XUNJI_PROXY": "y", "PATH": "/bin"})
        checks += [
            ("scrub_proxy_env 剥代理变量", "HTTPS_PROXY" not in senv and "XUNJI_PROXY" not in senv),
            ("scrub_proxy_env 不设 NO_PROXY(不压显式 --proxy)", "NO_PROXY" not in senv),
            ("scrub_proxy_env 保留无关变量", senv.get("PATH") == "/bin"),
        ]
        # fail-closed
        os.environ.pop("HTTPS_PROXY", None)
        os.environ["XUNJI_PROXY_REQUIRED"] = "1"
        try:
            resolve(None)
            fc = False
        except SystemExit:
            fc = True
        checks.append(("required 但没配 → fail-closed 抛错(不直连)", fc))
        checks.append(("required 配了 override → 不抛、返回代理", resolve("http://relay:9") == "http://relay:9"))
    finally:
        globals()["_CONF"] = old_conf
        for k, v in old_env.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
    bad = [n for n, ok in checks if not ok]
    for n, ok in checks:
        print(("ok   " if ok else "FAIL ") + n)
    print("proxy selftest " + ("passed" if not bad else f"FAILED ({len(bad)})"))
    return 0 if not bad else 1


if __name__ == "__main__":
    import sys
    import argparse
    ap = argparse.ArgumentParser(description="交战出口代理(渗透走代理/模型不走)")
    ap.add_argument("--selftest", action="store_true")
    a = ap.parse_args()
    if a.selftest:
        raise SystemExit(_selftest())
    import json
    print(json.dumps(status(), ensure_ascii=False))
    sys.exit(0)
