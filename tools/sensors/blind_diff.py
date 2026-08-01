#!/usr/bin/env python3
"""Stable baseline-vs-mutant differential sampler.

This is a proof sensor for blind or noisy cases. It sends requests through
probe.send (guard-routed), records status/length/hash/timing, and emits a JSON
artifact. It does not interpret the vulnerability class or confirm a finding.
"""
from __future__ import annotations

import argparse
import http.server
import json
import os
import shutil
import statistics
import sys
import tempfile
import threading
import time
from pathlib import Path

TOOLS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(TOOLS))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import probe  # noqa: E402
from common import FastLocalHTTPServer, print_json, write_artifact  # noqa: E402
from harness import guard as guardmod  # noqa: E402


def _isolate_selftest_state() -> tuple:
    tmp_root = Path(tempfile.mkdtemp())
    old = (
        probe._PROXY,
        probe.proxymod._CONF,
        guardmod.STATE_DIR,
        guardmod._LOCK_PATH,
        os.environ.get("XUNJI_PROXY"),
        os.environ.get("XUNJI_PROXY_REQUIRED"),
        tmp_root,
    )
    os.environ.pop("XUNJI_PROXY", None)
    os.environ["XUNJI_PROXY_REQUIRED"] = "0"
    probe._PROXY = None
    probe.proxymod._CONF = Path("__xunji_no_proxy_conf__")
    guardmod.STATE_DIR = tmp_root / "guard_state"
    guardmod.STATE_DIR.mkdir(parents=True, exist_ok=True)
    guardmod._LOCK_PATH = guardmod.STATE_DIR / ".lock"
    return old


def _restore_selftest_state(old: tuple) -> None:
    (probe._PROXY, probe.proxymod._CONF, guardmod.STATE_DIR, guardmod._LOCK_PATH,
     old_proxy_env, old_required_env, tmp_root) = old
    if old_proxy_env is None:
        os.environ.pop("XUNJI_PROXY", None)
    else:
        os.environ["XUNJI_PROXY"] = old_proxy_env
    if old_required_env is None:
        os.environ.pop("XUNJI_PROXY_REQUIRED", None)
    else:
        os.environ["XUNJI_PROXY_REQUIRED"] = old_required_env
    shutil.rmtree(tmp_root, ignore_errors=True)


def _headers(items: list[str]) -> dict:
    out = {}
    for h in items:
        if ":" in h:
            k, v = h.split(":", 1)
            out[k.strip()] = v.strip()
    return out


def sample(url: str, headers: dict, samples: int, timeout: int, proxy: str | None) -> dict:
    runs = []
    for _ in range(max(1, samples)):
        t0 = time.monotonic()
        old_proxy = probe._PROXY
        if proxy is not None:
            probe._PROXY = proxy
        try:
            res = probe.send("GET", url, headers, None, None, timeout)
        finally:
            probe._PROXY = old_proxy
        elapsed_ms = round((time.monotonic() - t0) * 1000, 3)
        runs.append({
            "status": res.get("status"),
            "len": res.get("len"),
            "sha1": res.get("sha1"),
            "error": res.get("error"),
            "elapsed_ms": elapsed_ms,
        })
    hashes = {r.get("sha1") for r in runs}
    statuses = {r.get("status") for r in runs}
    lens = {r.get("len") for r in runs}
    times = [r["elapsed_ms"] for r in runs]
    return {
        "url": url,
        "runs": runs,
        "stable_hash": len(hashes) == 1,
        "stable_status": len(statuses) == 1,
        "stable_len": len(lens) == 1,
        "avg_ms": round(statistics.mean(times), 3),
        "median_ms": round(statistics.median(times), 3),
    }


def build_diff(url_a: str, url_b: str, headers: dict, samples: int, timeout: int,
               proxy: str | None = None) -> dict:
    a = sample(url_a, headers, samples, timeout, proxy)
    b = sample(url_b, headers, samples, timeout, proxy)
    a_sig = _stable_signature(a["runs"])
    b_sig = _stable_signature(b["runs"])
    a0, b0 = a["runs"][0], b["runs"][0]
    timing_delta_ms = round(b["median_ms"] - a["median_ms"], 3)
    reliable = bool(
        a_sig and b_sig
        and not a_sig[3] and not b_sig[3]
        and a_sig[:3] != b_sig[:3]
    )
    return {
        "candidate": True,
        "mode": "blind_diff",
        "samples": max(1, samples),
        "a": a,
        "b": b,
        "same_status": a0.get("status") == b0.get("status"),
        "same_len": a0.get("len") == b0.get("len"),
        "same_hash": a0.get("sha1") == b0.get("sha1"),
        "timing_delta_ms": timing_delta_ms,
        "reliable_differential": reliable,
        "control": "URL A is baseline/control; URL B is mutant. Treat only stable differences as evidence.",
        "replicated": f"{max(1, samples)} sample(s) per side.",
    }


def _stable_signature(runs: list[dict]) -> tuple | None:
    signatures = {
        (r.get("status"), r.get("len"), r.get("sha1"), r.get("error"))
        for r in runs
    }
    if len(signatures) != 1:
        return None
    return next(iter(signatures))


def _selftest() -> int:
    old_state = _isolate_selftest_state()
    srv = None
    t = None

    class H(http.server.BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_GET(self):
            body = b"mutant" if "mutant" in self.path else b"base"
            self.send_response(200)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

    try:
        srv = FastLocalHTTPServer(("127.0.0.1", 0), H)
        port = srv.server_address[1]
        t = threading.Thread(target=lambda: srv.serve_forever(poll_interval=0.05), daemon=True)
        t.start()
        data = build_diff(f"http://127.0.0.1:{port}/base",
                          f"http://127.0.0.1:{port}/mutant", {}, 1, 5)
    finally:
        if srv:
            srv.shutdown()
            srv.server_close()
        if t:
            t.join(timeout=1)
        _restore_selftest_state(old_state)
    checks = [
        ("reliable differential", data["reliable_differential"] is True),
        ("same status", data["same_status"] is True),
        ("different hash", data["same_hash"] is False),
        ("timing recorded", isinstance(data["timing_delta_ms"], float)),
    ]
    bad = [n for n, ok in checks if not ok]
    for n, ok in checks:
        print(("ok   " if ok else "FAIL ") + n)
    print("blind_diff selftest " + ("passed" if not bad else f"FAILED ({len(bad)})"))
    return 0 if not bad else 1


def main() -> int:
    ap = argparse.ArgumentParser(description="Sample baseline vs mutant URLs through guard-routed probe.send.")
    ap.add_argument("url_a", nargs="?")
    ap.add_argument("url_b", nargs="?")
    ap.add_argument("--samples", type=int, default=3)
    ap.add_argument("--timeout", type=int, default=20)
    ap.add_argument("-H", "--header", action="append", default=[])
    ap.add_argument("--proxy", default=None)
    ap.add_argument("--run")
    ap.add_argument("--tag", default="blind_diff")
    ap.add_argument("--out", type=Path)
    ap.add_argument("--selftest", action="store_true")
    args = ap.parse_args()
    if args.selftest:
        return _selftest()
    if not args.url_a or not args.url_b:
        ap.error("url_a and url_b are required")
    data = build_diff(args.url_a, args.url_b, _headers(args.header), args.samples, args.timeout, args.proxy)
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        data["artifact"] = str(args.out)
        args.out.write_text(json.dumps({"sensor": "blind_diff", **data}, ensure_ascii=False, indent=2) + "\n",
                            encoding="utf-8")
        args.out.chmod(0o600)
    elif args.run:
        path = write_artifact(args.run, "blind_diff", args.tag, data)
        data["artifact"] = str(path)
    print_json({"sensor": "blind_diff", **data})
    return 0 if data["reliable_differential"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
