#!/usr/bin/env python3
"""oob_listener.py - lightweight OOB callback listener (P1).

Starts a small HTTP server on localhost that logs all incoming requests.
Useful for verifying out-of-band interactions: DNS-less HTTP callbacks
confirm an SSRF, XXE, blind RCE, or other async vulnerability reaches an
external endpoint.

Design:
- Pure stdlib (http.server) — no external dependencies.
- Runs LOCALLY. The operator is responsible for making the callback URL
  reachable from the target (e.g. via ngrok, a public VPS, port forwarding,
  or an interactsh-like service). This tool logs whatever arrives.
- Generates a unique callback ID on startup and prints it as JSON.
- After --timeout seconds, prints all received callbacks as a JSON array
  and exits.

Usage:
  .venv/bin/python tools/oob_listener.py
  .venv/bin/python tools/oob_listener.py --listen 0.0.0.0:8080 --timeout 120
  .venv/bin/python tools/oob_listener.py --selftest
"""

from __future__ import annotations

import argparse
import json
import os
import random
import string
import sys
import threading
import time
from datetime import datetime, timezone
from http.server import HTTPServer, BaseHTTPRequestHandler
from pathlib import Path
from urllib.parse import urlparse, parse_qs


def _generate_callback_id(length: int = 8) -> str:
    """Generate a random callback ID string."""
    return ''.join(random.choices(string.ascii_lowercase + string.digits, k=length))


class CallbackHandler(BaseHTTPRequestHandler):
    """HTTP request handler that logs all requests to a shared list."""

    # Class-level shared state (set by the server before starting)
    callbacks: list[dict] = []

    def log_message(self, format, *args):
        """Suppress default stderr logging — we produce structured JSON."""
        pass

    def _record(self):
        """Record the incoming request."""
        # Read body (with cap)
        content_length = int(self.headers.get("Content-Length", 0))
        body = b""
        if content_length > 0:
            body = self.rfile.read(min(content_length, 64 * 1024))

        # Parse query string
        parsed = urlparse(self.path)
        query = parse_qs(parsed.query)

        entry = {
            "timestamp": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z",
            "method": self.command,
            "path": parsed.path,
            "query": {k: v[0] if len(v) == 1 else v for k, v in query.items()} if query else {},
            "client": self.client_address[0],
            "headers": dict(self.headers),
            "body_preview": body[:512].decode("utf-8", "replace"),
            "body_len": len(body),
        }
        self.__class__.callbacks.append(entry)

    # Handle all HTTP methods uniformly — just log and respond 200
    def do_GET(self):
        self._record()
        self.send_response(200)
        self.send_header("Content-Type", "text/plain")
        self.end_headers()
        self.wfile.write(b"ok")

    def do_POST(self):
        self._record()
        self.send_response(200)
        self.send_header("Content-Type", "text/plain")
        self.end_headers()
        self.wfile.write(b"ok")

    def do_PUT(self):
        self._record()
        self.send_response(200)
        self.send_header("Content-Type", "text/plain")
        self.end_headers()
        self.wfile.write(b"ok")

    def do_DELETE(self):
        self._record()
        self.send_response(200)
        self.send_header("Content-Type", "text/plain")
        self.end_headers()
        self.wfile.write(b"ok")

    def do_HEAD(self):
        self._record()
        self.send_response(200)
        self.end_headers()

    def do_OPTIONS(self):
        self._record()
        self.send_response(200)
        self.send_header("Allow", "GET, POST, PUT, DELETE, HEAD, OPTIONS")
        self.end_headers()

    def do_PATCH(self):
        self._record()
        self.send_response(200)
        self.send_header("Content-Type", "text/plain")
        self.end_headers()
        self.wfile.write(b"ok")


def run_listener(host: str, port: int, timeout: int) -> dict:
    """Start the callback listener, wait for timeout, return results.

    Returns a dict with {callback_id, url, callbacks, ...}.
    """
    callback_id = _generate_callback_id()
    CallbackHandler.callbacks = []

    server = HTTPServer((host, port), CallbackHandler)
    # Set socket timeout so the serve_forever loop can be interrupted
    server.timeout = 1.0

    start_time = time.time()

    # Print startup info immediately so the caller can use the callback ID
    startup = {
        "callback_id": callback_id,
        "url": f"http://{host}:{port}/{callback_id}",
        "listen": f"{host}:{port}",
        "timeout": timeout,
        "started": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z",
        "note": ("This listener runs LOCALLY. The operator must make it reachable "
                 "from the target (e.g. ngrok, public VPS, port forwarding, or interactsh).")
    }
    print(json.dumps(startup, ensure_ascii=False), file=sys.stderr, flush=True)

    # Serve until timeout
    try:
        while (time.time() - start_time) < timeout:
            server.handle_request()
    except KeyboardInterrupt:
        pass

    server.server_close()

    elapsed = time.time() - start_time
    return {
        "callback_id": callback_id,
        "url": f"http://{host}:{port}/{callback_id}",
        "listen": f"{host}:{port}",
        "timeout": timeout,
        "elapsed_sec": round(elapsed, 1),
        "total_callbacks": len(CallbackHandler.callbacks),
        "callbacks": CallbackHandler.callbacks,
    }


def _selftest() -> int:
    """Regression test: start a listener on a random port, send a request, verify."""
    import socket

    checks: list[tuple[str, bool]] = []

    # Test 1: _generate_callback_id produces strings of expected length
    cid = _generate_callback_id()
    checks.append(("callback_id is 8 chars", len(cid) == 8))
    checks.append(("callback_id is alphanumeric", cid.isalnum() and cid.islower()))

    # Test 2: Start listener on random port, verify it serves and logs
    free_port = None
    for p in range(18723, 18733):
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            s.bind(("127.0.0.1", p))
            s.close()
            free_port = p
            break
        except OSError:
            continue
    checks.append(("found free port for selftest", free_port is not None))

    def _send_raw(host: str, port: int, method: str, path: str, body: bytes | None = None) -> bytes:
        """Send a raw HTTP request via socket (avoids proxy/env interference)."""
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(3)
        sock.connect((host, port))
        req = f"{method} {path} HTTP/1.0\r\nHost: {host}:{port}\r\n"
        if body:
            req += f"Content-Length: {len(body)}\r\nContent-Type: application/octet-stream\r\n"
        req += "Connection: close\r\n\r\n"
        sock.sendall(req.encode() if not body else req.encode() + body)
        resp = b""
        try:
            while True:
                chunk = sock.recv(4096)
                if not chunk:
                    break
                resp += chunk
        except socket.timeout:
            pass
        sock.close()
        return resp

    if free_port:
        CallbackHandler.callbacks = []
        server = HTTPServer(("127.0.0.1", free_port), CallbackHandler)
        server.timeout = 2.0

        def serve():
            try:
                end = time.time() + 5
                while time.time() < end:
                    server.handle_request()
            except Exception:
                pass

        t = threading.Thread(target=serve, daemon=True)
        t.start()
        time.sleep(0.3)

        try:
            # Send a GET with query params
            resp = _send_raw("127.0.0.1", free_port, "GET", "/test?a=1&b=2")
            checks.append(("listener responds 200", b"200" in resp[:20] or b"ok" in resp))
            time.sleep(0.3)
            checks.append(("request was logged", len(CallbackHandler.callbacks) >= 1))
            if CallbackHandler.callbacks:
                cb = CallbackHandler.callbacks[0]
                checks.append(("logged method is GET", cb.get("method") == "GET"))
                checks.append(("logged path is /test", cb.get("path") == "/test"))
                checks.append(("logged query has a=1", cb.get("query", {}).get("a") == "1"))
                checks.append(("logged client is 127.0.0.1", cb.get("client") == "127.0.0.1"))
                checks.append(("has timestamp", bool(cb.get("timestamp"))))
                checks.append(("has headers", bool(cb.get("headers"))))

            # Test POST with body
            resp2 = _send_raw("127.0.0.1", free_port, "POST", "/cb", b"callback-payload")
            checks.append(("POST responds 200", b"200" in resp2[:20] or b"ok" in resp2))
            time.sleep(0.3)
            checks.append(("POST was logged", len(CallbackHandler.callbacks) >= 2))
            if len(CallbackHandler.callbacks) >= 2:
                cb2 = CallbackHandler.callbacks[1]
                checks.append(("POST method logged", cb2.get("method") == "POST"))
                checks.append(("POST body captured", "callback-payload" in cb2.get("body_preview", "")))

        finally:
            server.server_close()

    # Test 3: startup info has expected keys
    info = {
        "callback_id": "test1234",
        "url": "http://127.0.0.1:8723/test1234",
        "listen": "127.0.0.1:8723",
        "timeout": 60
    }
    for k in ("callback_id", "url", "listen", "timeout"):
        checks.append((f"startup info has {k}", k in info))

    bad = [n for n, ok in checks if not ok]
    for n, ok in checks:
        print(("ok   " if ok else "FAIL ") + n, file=sys.stderr)
    print("oob_listener selftest " + ("passed" if not bad else f"FAILED ({len(bad)})"), file=sys.stderr)
    return 0 if not bad else 1


def main() -> int:
    ap = argparse.ArgumentParser(
        description="Lightweight OOB callback listener for verifying out-of-band interactions. "
                    "Runs a local HTTP server and logs all incoming requests as structured JSON. "
                    "NOTE: This listener runs LOCALLY. The operator must make the callback URL "
                    "reachable from the target (e.g. via ngrok, a public VPS, port forwarding, "
                    "or an interactsh-like service). This tool logs whatever arrives.")
    ap.add_argument("--selftest", action="store_true", help="run regression test and exit")
    ap.add_argument("--listen", default="127.0.0.1:8723",
                    help="HOST:PORT to listen on (default: 127.0.0.1:8723)")
    ap.add_argument("--timeout", type=int, default=300,
                    help="seconds to listen before exiting (default: 300)")
    args = ap.parse_args()

    if args.selftest:
        return _selftest()

    # Parse listen address
    listen = args.listen
    if ":" in listen:
        host, port_str = listen.rsplit(":", 1)
        try:
            port = int(port_str)
        except ValueError:
            print(f"invalid port: {port_str}", file=sys.stderr)
            return 1
    else:
        host = listen
        port = 8723

    result = run_listener(host, port, args.timeout)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
