#!/usr/bin/env python3
"""scan.py - scanner-as-sensor wrapper (P3).

Runs sqlmap / nuclei as *sensors* that feed the evidence gate -- never as the
verdict. Output is at most a 0.3-0.5 certainty lead; Hunter discipline still
decides confirmed/rejected. The wrapper forces proof-only defaults and a rate cap;
the PreToolUse hook is the second line that blocks dump/os-shell/intrusive flags.

  python tools/scan.py --run runs/<dir> sqlmap "https://t/x?id=1"  # saves evidence

This wrapper exposes no scanner-native tail argv.  All proof-only flags are
fixed internally; direct scanner invocation remains outside the capability and
the safety hook still blocks it.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import socket
import subprocess
import sys
import time
from pathlib import Path
from urllib.parse import urlparse

sys.path.insert(0, str(Path(__file__).resolve().parent))
from harness.guard import RateLimiter, HostHealth, HostBackoff  # noqa: E402
from harness import guard as guardmod  # noqa: E402
from harness import privacy as privacymod  # noqa: E402
from harness import proxy as proxymod  # noqa: E402  扫描器流量走交战代理(模型调用不走)

NEUTRAL_UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
              "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36")

# defaults chosen to stay inside proof-only verification + the rate ceiling
SQLMAP_SAFE = ["--batch", "--level=1", "--risk=1",
               "--technique=BEUST",  # blind/error/union/stacked? -> drop S below
               "--threads=1", "--delay=1", "--timeout=20", "--retries=0",
               "--ignore-redirects",
               f"--user-agent={NEUTRAL_UA}", "--banner"]
# stacked queries (S) can be state-changing; keep proof-only techniques:
SQLMAP_TECH = "--technique=BEU"
NUCLEI_SAFE = ["-rate-limit", "30", "-concurrency", "5", "-timeout", "15",
               "-retries", "0",
               "-severity", "info,low,medium,high,critical",
               "-exclude-tags", "dos,intrusive,fuzz", "-header", f"User-Agent: {NEUTRAL_UA}"]

FORBIDDEN_NUCLEI_TEMPLATE_FLAGS = ("-t", "-templates", "-template", "-ud", "-user-data")
PROXY_FAILURE_MARKERS = (
    "proxyconnect", "proxy connection", "connect to proxy", "connecting to proxy",
    "proxy dialer", "proxy error", "proxy authentication", "407 proxy",
    "target or proxy", "target url or proxy", "socks connect", "socks5 connect",
)
PROXY_DEFAULT_PORTS = {
    "http": 80, "https": 443,
    "socks4": 1080, "socks4a": 1080, "socks5": 1080, "socks5h": 1080,
}


def _privacy_input_error(tool: str, target: str, extra: list[str]) -> str:
    try:
        privacymod.validate_outbound_request("GET", target, {}, None)
    except privacymod.OutboundPrivacyError as e:
        return str(e)
    extra_reason = privacymod.privacy_reason(" ".join(extra), allow_generic_pii=True)
    if extra_reason:
        return f"outbound privacy blocked scanner arguments: {extra_reason}"
    if tool == "nuclei" and any(
            token == flag or token.startswith(flag + "=")
            for token in extra for flag in FORBIDDEN_NUCLEI_TEMPLATE_FLAGS):
        return ("custom nuclei templates/user-data are not inspectable per request; "
                "use the vetted default template set or author-and-handoff")
    return ""


def _valid_target(target: str) -> bool:
    try:
        parsed = urlparse(str(target or ""))
    except ValueError:
        return False
    return bool(
        parsed.scheme in {"http", "https"} and parsed.netloc and parsed.hostname
        and not parsed.username and not parsed.password
    )


def _looks_like_proxy_failure(_stdout: str, stderr: str) -> bool:
    # Scanner stdout may contain target-controlled response text. Only the
    # tool's diagnostic channel can attribute an internal proxy failure.
    text = stderr.lower()
    return any(marker in text for marker in PROXY_FAILURE_MARKERS)


def _proxy_endpoint(proxy: str) -> tuple[str, int]:
    try:
        parsed = urlparse(proxy)
        host = parsed.hostname or ""
        port = parsed.port or PROXY_DEFAULT_PORTS.get(parsed.scheme.lower(), 0)
    except (TypeError, ValueError) as exc:
        raise ValueError("invalid proxy endpoint") from exc
    if not host or parsed.scheme.lower() not in PROXY_DEFAULT_PORTS or port <= 0:
        raise ValueError("invalid proxy endpoint")
    return host, port


def _preflight_proxy(proxy: str, timeout: float = 3.0) -> Exception | None:
    """Check only the selected proxy endpoint before a scanner can self-retry."""
    try:
        with socket.create_connection(_proxy_endpoint(proxy), timeout=timeout):
            return None
    except (OSError, ValueError) as exc:
        return exc


def _selftest() -> int:
    checks = [
        ("neutral fixed scanner UA", "xunji" not in NEUTRAL_UA.lower()),
        ("project marker in scanner URL denied",
         bool(_privacy_input_error("sqlmap", "https://target.test/?marker=xunji-proof", []))),
        ("neutral scanner target allowed",
         _privacy_input_error("sqlmap", "https://target.test/?id=1", []) == ""),
        ("scanner target must be one absolute credential-free HTTP URL",
         _valid_target("https://target.test/?id=1")
         and not _valid_target("targets.txt")
         and not _valid_target("https://user:secret@target.test/")),
        ("custom nuclei template denied",
         bool(_privacy_input_error("nuclei", "https://target.test/", ["-t", "custom.yaml"]))),
        ("project marker in extra args denied",
         bool(_privacy_input_error("sqlmap", "https://target.test/", ["--prefix=xunji-proof"]))),
        ("scanner egress route ID redacts proxy endpoint",
         guardmod.egress_route_id("socks5h://user:secret@proxy.internal:1080").startswith(
             "proxy:socks5h:")
         and "secret" not in guardmod.egress_route_id(
             "socks5h://user:secret@proxy.internal:1080")),
        ("strong scanner proxy failure is recognized",
         _looks_like_proxy_failure("", "proxyconnect tcp: connection refused")),
        ("sqlmap target-or-proxy transport diagnostic stops the route",
         _looks_like_proxy_failure(
             "", "[CRITICAL] unable to connect to the target or proxy")),
        ("target-controlled stdout cannot forge a proxy failure",
         not _looks_like_proxy_failure("proxy error: socks connect", "")),
        ("generic target failure is not blamed on proxy",
         not _looks_like_proxy_failure("", "target connection refused")),
        ("proxy endpoint parser applies scheme defaults",
         _proxy_endpoint("socks5h://proxy.example") == ("proxy.example", 1080)),
        ("scanner-native transport retries are disabled",
         "--retries=0" in SQLMAP_SAFE
         and NUCLEI_SAFE[NUCLEI_SAFE.index("-retries") + 1] == "0"),
    ]
    bad = [name for name, ok in checks if not ok]
    for name, ok in checks:
        print(("ok   " if ok else "FAIL ") + name)
    print("scan selftest " + ("passed" if not bad else f"FAILED ({len(bad)})"))
    return 0 if not bad else 1


def run(cmd: list[str], run_dir: str | None = None, name: str | None = None,
        host: str = "", tool: str = "", egress_route: str = "direct") -> int:
    print("[scan] " + " ".join(cmd), file=sys.stderr)
    start = time.time()
    try:
        result = subprocess.run(cmd, env=proxymod.scrub_proxy_env(),
                                capture_output=run_dir is not None, text=True)
        elapsed = time.time() - start
        if run_dir:
            _save_evidence(run_dir, name or f"{tool}_{host}", tool, host, cmd,
                           result.returncode, result.stdout, result.stderr, elapsed)
        if host and result.returncode == 0:
            HostHealth().record_ok(host, egress_route=egress_route)
        elif host and egress_route.startswith("proxy:") and _looks_like_proxy_failure(
                result.stdout or "", result.stderr or ""):
            HostHealth().record_error(
                host, egress_route=egress_route, error_class="proxy_connect")
            print(
                "[scan] explicit proxy failed; automatic retry is stopped. "
                "Wait for a newer operator turn to choose direct or explicitly confirm proxy.",
                file=sys.stderr,
            )
        return result.returncode
    except FileNotFoundError:
        print(f"[scan] '{cmd[0]}' not installed on this host.", file=sys.stderr)
        return 127


def _save_evidence(run_dir: str, name: str, tool: str, host: str,
                   cmd: list[str], rc: int, stdout: str, stderr: str,
                   elapsed: float) -> None:
    evdir = Path(run_dir) / "evidence"
    evdir.mkdir(parents=True, exist_ok=True)
    safe_name = name.replace("/", "_").replace(" ", "_")
    replay = {
        "tool": tool,
        "command": " ".join(cmd),
        "target": host,
        "exit_code": rc,
        "elapsed_seconds": round(elapsed, 2),
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "stdout_sha256": hashlib.sha256(stdout.encode("utf-8", errors="replace")).hexdigest(),
        "stdout_length": len(stdout),
    }
    rp_path = evdir / f"{safe_name}.scan.json"
    rp_path.write_text(json.dumps(replay, indent=2, ensure_ascii=False), encoding="utf-8")
    out_path = evdir / f"{safe_name}.scan.txt"
    out_path.write_text(stdout, encoding="utf-8", errors="replace")
    if stderr:
        err_path = evdir / f"{safe_name}.scan.err.txt"
        err_path.write_text(stderr, encoding="utf-8", errors="replace")
    print(f"[scan] evidence saved: {rp_path} + {out_path}", file=sys.stderr)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--run", default=None, dest="run_dir",
                    help="活动 run 目录如 runs/<target>；扫描输出固定落 evidence/")
    ap.add_argument("--name", default=None,
                    help="证据名称(如 E-xxx_scan); 需 --run。默认用 <tool>_<host>")
    ap.add_argument("--selftest", action="store_true")
    ap.add_argument("tool", nargs="?", choices=["sqlmap", "nuclei"])
    ap.add_argument("target", nargs="?")
    args = ap.parse_args()
    if args.selftest:
        return _selftest()
    if not args.run_dir or not args.tool or not args.target:
        ap.error("--run, tool, and target are required (or use --selftest)")
    if not _valid_target(args.target):
        ap.error("target must be one absolute credential-free http(s) URL")

    # The frozen turn route is direct by default.  Only an explicit proxy turn
    # causes resolve() to read the trusted engagement-proxy configuration;
    # model-controlled scanner-native proxy argv remains outside this capability.
    proxy = proxymod.resolve(None)
    egress_route = guardmod.egress_route_id(proxy)
    host = urlparse(args.target).hostname or args.target
    privacy_error = _privacy_input_error(args.tool, args.target, [])
    if privacy_error:
        print(f"[scan] refused: {privacy_error}", file=sys.stderr)
        return 5
    try:
        # 自熔断: 拒绝对已在退避冷却(连续失败/被目标限流)的 host 发起扫描器 —— 扫描器
        # 请求量大, 对正在封锁我的 host launch nuclei/sqlmap 只会加深封锁(本次教训)
        HostHealth().check(host, egress_route=egress_route, acquire_half_open=False)
        guardmod.SessionBudget().check()
    except guardmod.GuardStateError as e:
        print(f"[scan] refused: guard-state: {e}", file=sys.stderr)
        return 4
    except HostBackoff as e:
        print(f"[scan] refused: {e}", file=sys.stderr)
        return 4
    except guardmod.RateBudgetExceeded as e:
        print(f"[scan] refused: session/rate budget: {e}", file=sys.stderr)
        return 4
    if proxy:
        proxy_error = _preflight_proxy(proxy)
        if proxy_error is not None:
            error_class = guardmod.classify_network_error(
                proxy_error, egress_route=egress_route)
            HostHealth().record_error(
                host, egress_route=egress_route, error_class=error_class)
            print(
                "[scan] explicit proxy endpoint is unavailable; scanner launch stopped. "
                "Wait for a newer operator turn to choose direct or explicitly confirm proxy.",
                file=sys.stderr,
            )
            return 4
    RateLimiter().gate(host)  # space the launch itself

    if args.tool == "sqlmap":
        if not shutil.which("sqlmap"):
            print("[scan] sqlmap not installed. Install it, then this wrapper enforces "
                  "proof-only flags (no --dump).", file=sys.stderr)
            return 127
        cmd = ["sqlmap", "-u", args.target, *[a for a in SQLMAP_SAFE if not a.startswith("--technique")],
               SQLMAP_TECH]
        if proxy:
            cmd.append(f"--proxy={proxy}")
        return run(cmd, run_dir=args.run_dir, name=args.name, host=host, tool="sqlmap",
                   egress_route=egress_route)

    # nuclei
    if not shutil.which("nuclei"):
        print("[scan] nuclei not installed. Install it, then this wrapper enforces "
              "rate-limit + excludes dos/intrusive templates.", file=sys.stderr)
        return 127
    cmd = ["nuclei", "-u", args.target, *NUCLEI_SAFE]
    if proxy:
        cmd += ["-proxy", proxy]
    return run(cmd, run_dir=args.run_dir, name=args.name, host=host, tool="nuclei",
               egress_route=egress_route)


if __name__ == "__main__":
    raise SystemExit(main())
