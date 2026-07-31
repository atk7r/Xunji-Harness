#!/usr/bin/env python3
"""One guarded WebSocket opening handshake with saved replay evidence.

The tool deliberately stops at HTTP 101.  It does not send frames, fuzz a
socket, or add a second network stack: URL/privacy/proxy/guard/recording are
inherited from ``probe.send``.
"""
from __future__ import annotations

import argparse
import base64
import hashlib
import json
import os
import re
import tempfile
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

import probe


GUID = "258EAFA5-E914-47DA-95CA-C5AB0DC85B11"
_PROXY_LOCK = threading.Lock()


def _http_url(url: str) -> str:
    parsed = urlsplit(url)
    if parsed.scheme not in {"ws", "wss"} or not parsed.netloc \
            or not parsed.hostname or parsed.username or parsed.password:
        raise ValueError("WEBSOCKET_URL_INVALID")
    return urlunsplit((
        "https" if parsed.scheme == "wss" else "http",
        parsed.netloc, parsed.path or "/", parsed.query, "",
    ))


def _save_path(run_dir: str | Path, name: str) -> Path:
    run = Path(run_dir).resolve()
    if not run.is_dir() or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}", name):
        raise ValueError("WEBSOCKET_SAVE_INVALID")
    path = (run / "evidence" / name).resolve()
    if path.parent != (run / "evidence").resolve():
        raise ValueError("WEBSOCKET_SAVE_INVALID")
    return path


def handshake(
    url: str,
    *,
    run_dir: str | Path,
    save: str,
    origin: str = "",
    protocol: str = "",
    timeout: int = 15,
    proxy: str | None = None,
    key: str | None = None,
) -> dict:
    http_url = _http_url(url)
    save_path = _save_path(run_dir, save)
    websocket_key = key or base64.b64encode(os.urandom(16)).decode("ascii")
    headers = {
        "Connection": "Upgrade",
        "Upgrade": "websocket",
        "Sec-WebSocket-Version": "13",
        "Sec-WebSocket-Key": websocket_key,
    }
    if origin:
        headers["Origin"] = origin
    if protocol:
        headers["Sec-WebSocket-Protocol"] = protocol
    # ``probe`` currently exposes process-global proxy configuration. Serialize
    # the bounded swap/send/restore transaction so concurrent callers cannot
    # borrow one another's proxy route.
    with _PROXY_LOCK:
        old_proxy = probe._PROXY
        try:
            probe._PROXY = proxy
            response = probe.send(
                "GET", http_url, headers, None, None, timeout,
                save=str(save_path), want_headers=True, no_redirect=True,
            )
        finally:
            probe._PROXY = old_proxy
    expected = base64.b64encode(
        hashlib.sha1((websocket_key + GUID).encode("ascii")).digest()
    ).decode("ascii")
    response_headers = response.get("headers") or {}
    actual = next(
        (str(value) for name, value in response_headers.items()
         if str(name).lower() == "sec-websocket-accept"),
        "",
    )
    accepted = (
        response.get("status") == 101
        and str(response_headers.get("Upgrade") or "").lower() == "websocket"
        and actual == expected
    )
    return {
        "schema": "xunji.websocket-handshake.v1",
        "url": url,
        "accepted": accepted,
        "status": response.get("status", 0),
        "expected_accept": expected,
        "actual_accept": actual,
        "saved": response.get("saved"),
        "replay": response.get("replay"),
        "attempts": response.get("attempts", 0),
        "error": response.get("error", ""),
        "boundary": "opening-handshake-only; no WebSocket frames sent",
    }


def _selftest() -> int:
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:  # noqa: N802
            key = self.headers.get("Sec-WebSocket-Key", "")
            accept = base64.b64encode(
                hashlib.sha1((key + GUID).encode("ascii")).digest()
            ).decode("ascii")
            self.send_response(101)
            self.send_header("Connection", "Upgrade")
            self.send_header("Upgrade", "websocket")
            self.send_header("Sec-WebSocket-Accept", accept)
            self.end_headers()

        def log_message(self, _format: str, *_args: object) -> None:
            return

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    root = Path(tempfile.mkdtemp()) / "run"
    root.mkdir()
    initial_proxy = probe._PROXY
    try:
        with probe.selftest_isolation():
            result = handshake(
                f"ws://127.0.0.1:{server.server_port}/socket",
                run_dir=root, save="ws-handshake.bin",
                key=base64.b64encode(b"0123456789abcdef").decode("ascii"),
            )
    finally:
        server.shutdown()
        thread.join(timeout=2)
    checks = [
        ("101 and Sec-WebSocket-Accept are both verified", result["accepted"]),
        ("handshake saves a replay-bound target artifact",
         Path(str(result["saved"])).is_file()
         and Path(str(result["replay"])).is_file()),
        ("no frame capability is exposed",
         result["boundary"] == "opening-handshake-only; no WebSocket frames sent"),
        ("process-global proxy is restored after the guarded transaction",
         probe._PROXY == initial_proxy),
    ]
    failed = [name for name, ok in checks if not ok]
    for name, ok in checks:
        print(("ok   " if ok else "FAIL ") + name)
    print("websocket_probe selftest " + ("passed" if not failed else "FAILED"))
    return 0 if not failed else 1


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("url", nargs="?")
    parser.add_argument("--run")
    parser.add_argument("--save")
    parser.add_argument("--origin", default="")
    parser.add_argument("--protocol", default="")
    parser.add_argument("--timeout", type=int, default=15)
    parser.add_argument("--proxy")
    parser.add_argument("--selftest", action="store_true")
    args = parser.parse_args()
    if args.selftest:
        return _selftest()
    if not args.url or not args.run or not args.save:
        parser.error("url, --run, and --save are required")
    try:
        result = handshake(
            args.url, run_dir=args.run, save=args.save, origin=args.origin,
            protocol=args.protocol, timeout=args.timeout, proxy=args.proxy,
        )
    except ValueError as exc:
        parser.error(str(exc))
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result["accepted"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
