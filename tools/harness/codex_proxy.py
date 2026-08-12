#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""harness/codex_proxy.py — Codex CLI 专用代理通道。

三条代理通道，互不串味:
  - 交战代理: XUNJI_PROXY (渗透流量: probe/render/scan)
  - 模型 API: 剥代理直连 (deepseek/glm/claude API, model_safe_env / model_no_proxy_opener)
  - Codex 代理: CODEX_PROXY (Codex CLI → OpenAI API, 本模块)

Codex CLI 是本地 agent 进程，本身调用 OpenAI API。它需要独立的代理通道：
既不经过交战代理(会泄露 codex 流量到目标侧中继)，也不走模型 API 的剥代理直连(可能不可达)。

Codex CLI 底层用 reqwest，遵循 HTTPS_PROXY / http_proxy 环境变量。

配置优先级: CODEX_PROXY 环境变量 > tools/harness/codex_proxy.conf (gitignored)

用法:
  程序化:
    from harness.codex_proxy import codex_env, run_codex
    env = codex_env()
    subprocess.run(["codex", "exec", ...], env=env)
    # 或一步:
    run_codex(["codex", "exec", "-s", "read-only"], input=prompt, ...)

  CLI 包装:
    .venv/bin/python tools/harness/codex_proxy.py codex exec -s read-only
    .venv/bin/python tools/harness/codex_proxy.py --status
    .venv/bin/python tools/harness/codex_proxy.py --selftest
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

_CONF = Path(__file__).resolve().parent / "codex_proxy.conf"  # gitignored: 一行一个 url


def codex_proxy_url() -> str | None:
    """Codex 专用代理 URL。只读 CODEX_PROXY 或 codex_proxy.conf。
    刻意不读 XUNJI_PROXY(交战)/HTTPS_PROXY(系统/可能被交战或模型污染)。"""
    v = (os.environ.get("CODEX_PROXY") or "").strip()
    if v:
        return v
    if _CONF.exists():
        for ln in _CONF.read_text(encoding="utf-8", errors="replace").splitlines():
            ln = ln.strip()
            if ln and not ln.startswith("#"):
                return ln
    return None


def codex_required() -> bool:
    """CODEX_PROXY_REQUIRED=1 → 强制: codex 没配代理就拒绝直连(fail-closed)。"""
    return (os.environ.get("CODEX_PROXY_REQUIRED") or "").strip().lower() in ("1", "true", "yes", "on")


def codex_env(base: dict | None = None) -> dict:
    """返回 codex 子进程用的 env dict。

    剥掉所有交战/系统代理变量 → 只设 CODEX 专用代理为 HTTPS_PROXY / http_proxy。
    CODEX_PROXY_REQUIRED=1 且无代理 → fail-closed 抛 SystemExit(拒绝直连)。
    无 codex 代理且未强制 → 直连(干净 env, 不回退到系统/交战代理)。

    与 proxy.model_safe_env() 的区别: model_safe_env 剥代理后不设任何代理(模型 API 直连);
    codex_env 剥代理后重新设为 codex 代理(codex CLI 可能需要代理才能访问 OpenAI API)。
    """
    env = dict(os.environ if base is None else base)
    # 剥掉所有可能串味的代理变量(含 NO_PROXY —— 否则 reqwest 会绕开代理直连)
    for k in ("XUNJI_PROXY", "HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "FTP_PROXY",
              "http_proxy", "https_proxy", "all_proxy", "ftp_proxy",
              "XUNJI_PROXY_REQUIRED", "CODEX_PROXY",
              "NO_PROXY", "no_proxy"):
        env.pop(k, None)

    proxy = codex_proxy_url()
    if proxy:
        env["HTTPS_PROXY"] = proxy
        env["https_proxy"] = proxy
        env["HTTP_PROXY"] = proxy
        env["http_proxy"] = proxy
    elif codex_required():
        raise SystemExit(
            "[codex_proxy] CODEX_PROXY_REQUIRED=1 但未配置 codex 代理 —— 拒绝直连。"
            " 设 CODEX_PROXY=http://host:port 或写一行进 tools/harness/codex_proxy.conf。")
    # 不设 NO_PROXY —— codex 所有流量都应走代理(如有配置)

    return env


def run_codex(args: list[str], **kwargs) -> subprocess.CompletedProcess:
    """在 codex 专用代理 env 下执行 codex 命令。

    args: codex 命令行参数，如 ["codex", "exec", "-s", "read-only"]
    kwargs: 传给 subprocess.run 的额外参数 (input, capture_output, timeout, cwd, text...)
    """
    kwargs["env"] = codex_env(kwargs.pop("env", None))
    return subprocess.run(args, **kwargs)


def status() -> dict:
    """返回 codex 代理配置状态。"""
    p = codex_proxy_url()
    src = ("CODEX_PROXY" if (os.environ.get("CODEX_PROXY") or "").strip()
           else "codex_proxy.conf" if (p and _CONF.exists()) else "none")
    return {"codex_proxy": p, "source": src, "configured": p is not None}


# ---- CLI ----
def _main() -> int:
    import argparse
    ap = argparse.ArgumentParser(
        description="Codex CLI 专用代理包装器 —— 三条通道各走各的代理，互不串味")
    ap.add_argument("--status", action="store_true", help="显示 codex 代理配置状态")
    ap.add_argument("--selftest", action="store_true")
    ap.add_argument("args", nargs=argparse.REMAINDER, help="codex 命令及参数, 如: codex exec -s read-only")
    a = ap.parse_args()

    if a.selftest:
        return _selftest()

    if a.status:
        import json
        print(json.dumps(status(), ensure_ascii=False))
        return 0

    cmd_args = a.args
    if not cmd_args:
        ap.error("需要 codex 命令参数，如: codex_proxy.py codex exec -s read-only")

    proxy = codex_proxy_url()
    if proxy:
        print(f"[codex_proxy] 通过代理: {proxy}", file=sys.stderr)
    else:
        print("[codex_proxy] 无 codex 代理配置，直连", file=sys.stderr)

    return subprocess.run(cmd_args, env=codex_env()).returncode


def _selftest() -> int:
    checks: list[tuple[str, bool]] = []

    # 暂屏蔽 codex_proxy.conf(若存在), 使"无 conf"测试不受生产配置干扰
    conf_bak = _CONF.with_suffix(".conf.bak")
    if _CONF.exists():
        _CONF.rename(conf_bak)

    # 读代理: 无 env 无 conf → None
    old = os.environ.pop("CODEX_PROXY", None)
    checks.append(("无 CODEX_PROXY+无 conf → None", codex_proxy_url() is None))

    # CODEX_PROXY env
    os.environ["CODEX_PROXY"] = "socks5h://codex-relay:1080"
    checks.append(("CODEX_PROXY env → 读到", codex_proxy_url() == "socks5h://codex-relay:1080"))

    # codex_env: 有代理时设 HTTPS_PROXY, 剥交战/系统代理(含 NO_PROXY —— 否则 reqwest 绕开代理)
    env = codex_env({"XUNJI_PROXY": "bad-engagement",
                     "HTTPS_PROXY": "bad-system",
                     "http_proxy": "bad-lower",
                     "NO_PROXY": "*",
                     "no_proxy": "api.openai.com",
                     "PATH": "/bin"})
    checks.append(("codex_env 剥 XUNJI_PROXY", "XUNJI_PROXY" not in env))
    checks.append(("codex_env 剥 NO_PROXY", "NO_PROXY" not in env))
    checks.append(("codex_env 剥 no_proxy(小写)", "no_proxy" not in env))
    checks.append(("codex_env HTTPS_PROXY=codex 代理(非系统)", env.get("HTTPS_PROXY") == "socks5h://codex-relay:1080"))
    checks.append(("codex_env http_proxy=codex 代理(非系统小写)", env.get("http_proxy") == "socks5h://codex-relay:1080"))
    checks.append(("codex_env 保留无关变量", env.get("PATH") == "/bin"))

    # codex_env: 无代理时直连(不设任何代理, 不继承系统)
    os.environ.pop("CODEX_PROXY", None)
    env2 = codex_env({"HTTPS_PROXY": "bad-system", "XUNJI_PROXY": "bad-engagement"})
    checks.append(("codex_env 无代理→不设 HTTPS_PROXY", "HTTPS_PROXY" not in env2))
    checks.append(("codex_env 无代理→不设 http_proxy", "http_proxy" not in env2))
    checks.append(("codex_env 无代理→剥 XUNJI_PROXY", "XUNJI_PROXY" not in env2))

    # fail-closed: CODEX_PROXY_REQUIRED=1 且无代理 → SystemExit
    os.environ["CODEX_PROXY_REQUIRED"] = "1"
    checks.append(("codex_required() True", codex_required() is True))
    try:
        codex_env({"PATH": "/bin"})
        fc = False
    except SystemExit:
        fc = True
    checks.append(("CODEX_PROXY_REQUIRED+无代理 → fail-closed 抛 SystemExit", fc))
    os.environ.pop("CODEX_PROXY_REQUIRED", None)
    checks.append(("codex_required() False(已清除)", codex_required() is False))

    # status
    checks.append(("status configured=False", status()["configured"] is False))
    os.environ["CODEX_PROXY"] = "http://p:3128"
    checks.append(("status configured=True", status()["configured"] is True))
    checks.append(("status source=CODEX_PROXY", status()["source"] == "CODEX_PROXY"))
    os.environ.pop("CODEX_PROXY", None)

    if old:
        os.environ["CODEX_PROXY"] = old
    # 恢复生产配置
    if conf_bak.exists():
        conf_bak.rename(_CONF)

    bad = [n for n, ok in checks if not ok]
    for n, ok in checks:
        print(f"{'ok  ' if ok else 'FAIL'} {n}")
    print(f"codex_proxy selftest {'passed' if not bad else f'FAILED ({len(bad)})'}")
    return 0 if not bad else 1


if __name__ == "__main__":
    raise SystemExit(_main())
