#!/usr/bin/env python3
"""scan.py - scanner-as-sensor wrapper (P3).

Runs sqlmap / nuclei as *sensors* that feed the evidence gate -- never as the
verdict. Output is at most a 0.3-0.5 certainty lead; Hunter discipline still
decides confirmed/rejected. The wrapper forces proof-only defaults and a rate cap;
the PreToolUse hook is the second line that blocks dump/os-shell/intrusive flags.

  python tools/scan.py sqlmap "https://t/x?id=1"      # injection PROOF only (no dump)
  python tools/scan.py nuclei "https://t/"             # detection templates only
  python tools/scan.py --run runs/<dir> sqlmap "https://t/x?id=1"  # saves evidence

This wrapper never adds --dump/--os-shell (sqlmap) or dos/intrusive tags
(nuclei). If you hand it those, it refuses; if you bypass it and call the tool
directly, the safety hook still blocks them.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path
from urllib.parse import urlparse

sys.path.insert(0, str(Path(__file__).resolve().parent))
from harness.guard import RateLimiter, HostHealth, HostBackoff  # noqa: E402
from harness import proxy as proxymod  # noqa: E402  扫描器流量走交战代理(模型调用不走)

# defaults chosen to stay inside proof-only verification + the rate ceiling
SQLMAP_SAFE = ["--batch", "--level=1", "--risk=1",
               "--technique=BEUST",  # blind/error/union/stacked? -> drop S below
               "--threads=1", "--delay=1", "--timeout=20", "--banner"]
# stacked queries (S) can be state-changing; keep proof-only techniques:
SQLMAP_TECH = "--technique=BEU"
NUCLEI_SAFE = ["-rate-limit", "30", "-concurrency", "5", "-timeout", "15",
               "-severity", "info,low,medium,high,critical",
               "-exclude-tags", "dos,intrusive,fuzz"]

FORBIDDEN_SQLMAP = ("--dump", "--os-shell", "--os-pwn", "--os-cmd", "--file-write",
                    "--file-dest", "--sql-shell", "--priv-esc")
FORBIDDEN_NUCLEI_TAGS = ("dos", "intrusive", "fuzz")


def run(cmd: list[str], run_dir: str | None = None, name: str | None = None,
        host: str = "", tool: str = "") -> int:
    print("[scan] " + " ".join(cmd), file=sys.stderr)
    start = time.time()
    try:
        result = subprocess.run(cmd, env=proxymod.scrub_proxy_env(),
                                capture_output=run_dir is not None, text=True)
        elapsed = time.time() - start
        if run_dir:
            _save_evidence(run_dir, name or f"{tool}_{host}", tool, host, cmd,
                           result.returncode, result.stdout, result.stderr, elapsed)
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
    ap.add_argument("--proxy", default=None,
                    help="交战代理(http://h:p / socks5h://h:p)；经中继扫描境内资产。未给则走 harness.proxy"
                         "(XUNJI_PROXY / proxy.conf, 不读 HTTPS_PROXY=模型那条)。须置于 tool/target 之前")
    ap.add_argument("--run", default=None, dest="run_dir",
                    help="run 目录如 runs/<target>; 给则将扫描输出落 evidence/<name>.scan.json + .scan.txt")
    ap.add_argument("--name", default=None,
                    help="证据名称(如 E-xxx_scan); 需 --run。默认用 <tool>_<host>")
    ap.add_argument("tool", choices=["sqlmap", "nuclei"])
    ap.add_argument("target")
    ap.add_argument("extra", nargs=argparse.REMAINDER,
                    help="extra args incl. -flags (vetted against the forbidden list)")
    args = ap.parse_args()

    proxy = proxymod.resolve(args.proxy)   # 交战代理(XUNJI_PROXY/proxy.conf/--proxy); required 时没配 fail-closed
    host = urlparse(args.target).hostname or args.target
    try:
        # 自熔断: 拒绝对已在退避冷却(连续失败/被目标限流)的 host 发起扫描器 —— 扫描器
        # 请求量大, 对正在封锁我的 host launch nuclei/sqlmap 只会加深封锁(本次教训)
        HostHealth().check(host)
    except HostBackoff as e:
        print(f"[scan] refused: {e}", file=sys.stderr)
        return 4
    RateLimiter().gate(host)  # space the launch itself

    if args.tool == "sqlmap":
        if any(f in " ".join(args.extra) for f in FORBIDDEN_SQLMAP):
            print("[scan] refused: dump/os-shell/file-write exceed proof-only verification.",
                  file=sys.stderr)
            return 3
        if not shutil.which("sqlmap"):
            print("[scan] sqlmap not installed. Install it, then this wrapper enforces "
                  "proof-only flags (no --dump).", file=sys.stderr)
            return 127
        cmd = ["sqlmap", "-u", args.target, *[a for a in SQLMAP_SAFE if not a.startswith("--technique")],
               SQLMAP_TECH, *args.extra]
        if proxy:
            cmd.append(f"--proxy={proxy}")
        return run(cmd, run_dir=args.run_dir, name=args.name, host=host, tool="sqlmap")

    # nuclei
    if any(t in " ".join(args.extra) for t in FORBIDDEN_NUCLEI_TAGS):
        print("[scan] refused: dos/intrusive/fuzz templates exceed proof-only verification.",
              file=sys.stderr)
        return 3
    if not shutil.which("nuclei"):
        print("[scan] nuclei not installed. Install it, then this wrapper enforces "
              "rate-limit + excludes dos/intrusive templates.", file=sys.stderr)
        return 127
    cmd = ["nuclei", "-u", args.target, *NUCLEI_SAFE, *args.extra]
    if proxy:
        cmd += ["-proxy", proxy]
    return run(cmd, run_dir=args.run_dir, name=args.name, host=host, tool="nuclei")


if __name__ == "__main__":
    raise SystemExit(main())
