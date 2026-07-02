#!/usr/bin/env python3
"""Local callback listener for blind proof signals.

The listener records inbound HTTP callbacks with a nonce. It does not create a
public tunnel and does not confirm findings; it produces an artifact the driver
can cite after verifying that the callback was caused by the tested target.
"""
from __future__ import annotations

import argparse
import http.server
import json
import socket
import secrets
import sys
import threading
import time
import urllib.request
from pathlib import Path
from urllib.parse import parse_qs, urlparse

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import FastLocalHTTPServer, ROOT, print_json, safe_slug, sensor_dir  # noqa: E402

SENSITIVE_HEADERS = {"authorization", "cookie", "set-cookie", "proxy-authorization", "x-api-key", "x-auth-token"}


class CallbackStore:
    def __init__(self, path: Path, nonce: str):
        self.path = path
        self.nonce = nonce
        self.events: list[dict] = []
        self.lock = threading.Lock()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.touch(mode=0o600, exist_ok=True)
        path.chmod(0o600)

    @staticmethod
    def _headers(headers: http.client.HTTPMessage) -> dict:
        return {
            k: ("<redacted>" if k.lower() in SENSITIVE_HEADERS else v)
            for k, v in headers.items()
        }

    def record(self, handler: http.server.BaseHTTPRequestHandler) -> None:
        parsed = urlparse(handler.path)
        qs = parse_qs(parsed.query)
        length = int(handler.headers.get("Content-Length", "0") or "0")
        body = ""
        body_error = None
        if length:
            handler.connection.settimeout(2.0)
            try:
                body = handler.rfile.read(min(length, 4096)).decode("utf-8", "replace")
            except (TimeoutError, socket.timeout, OSError) as e:
                body_error = type(e).__name__
        event = {
            "sensor": "oob_listener",
            "candidate": True,
            "ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "artifact": str(self.path),
            "client": handler.client_address[0],
            "method": handler.command,
            "path": parsed.path,
            "query": qs,
            "nonce_seen": self.nonce in handler.path or self.nonce in body,
            "headers": self._headers(handler.headers),
            "body_prefix": body[:240],
            "control": "Use a unique nonce per attempted callback and verify target causality.",
            "replicated": "Run a second nonce if the callback is used for certainty >=0.8.",
        }
        if body_error:
            event["body_error"] = body_error
        with self.lock:
            self.events.append(event)
            with self.path.open("a", encoding="utf-8") as f:
                f.write(json.dumps(event, ensure_ascii=False) + "\n")


def make_handler(store: CallbackStore):
    class H(http.server.BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_GET(self):
            self._handle()

        def do_POST(self):
            self._handle()

        def _handle(self):
            store.record(self)
            self.send_response(204)
            self.send_header("Content-Length", "0")
            self.end_headers()

    return H


def artifact_path(run: str | None, nonce: str) -> Path:
    return sensor_dir(run) / f"oob_listener_{safe_slug(nonce)}.jsonl"


def _selftest() -> int:
    nonce = "testnonce"
    path = ROOT / "tmp" / "sensors" / "oob_selftest.jsonl"
    path.unlink(missing_ok=True)
    store = CallbackStore(path, nonce)
    srv = FastLocalHTTPServer(("127.0.0.1", 0), make_handler(store))
    port = srv.server_address[1]
    t = threading.Thread(target=lambda: srv.serve_forever(poll_interval=0.05), daemon=True)
    t.start()
    try:
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        req = urllib.request.Request(
            f"http://127.0.0.1:{port}/cb?nonce={nonce}",
            headers={"Cookie": "secret=1", "X-Api-Key": "key"},
        )
        opener.open(req, timeout=5).read()
        time.sleep(0.1)
    finally:
        srv.shutdown()
        srv.server_close()
        t.join(timeout=1)
    lines = path.read_text(encoding="utf-8").splitlines() if path.exists() else []
    event = json.loads(lines[0]) if lines else {}
    event_headers = {k.lower(): v for k, v in event.get("headers", {}).items()}
    checks = [
        ("event written", len(lines) == 1),
        ("nonce detected", event.get("nonce_seen") is True),
        ("method captured", event.get("method") == "GET"),
        ("sensitive headers redacted", event_headers.get("cookie") == "<redacted>"
         and event_headers.get("x-api-key") == "<redacted>"),
        ("artifact is private", (path.stat().st_mode & 0o777) == 0o600),
    ]
    bad = [n for n, ok in checks if not ok]
    for n, ok in checks:
        print(("ok   " if ok else "FAIL ") + n)
    print("oob_listener selftest " + ("passed" if not bad else f"FAILED ({len(bad)})"))
    return 0 if not bad else 1


def main() -> int:
    ap = argparse.ArgumentParser(description="Record local OOB callback evidence with a nonce.")
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=0)
    ap.add_argument("--nonce", default=None)
    ap.add_argument("--run", help="run dir; writes artifact under <run>/evidence/sensors/")
    ap.add_argument("--timeout", type=float, default=0.0, help="seconds to run; 0 means until Ctrl-C")
    ap.add_argument("--once", action="store_true", help="stop after first callback or timeout")
    ap.add_argument("--selftest", action="store_true")
    args = ap.parse_args()
    if args.selftest:
        return _selftest()
    nonce = args.nonce or secrets.token_urlsafe(12)
    path = artifact_path(args.run, nonce)
    path.unlink(missing_ok=True)
    store = CallbackStore(path, nonce)
    srv = FastLocalHTTPServer((args.host, args.port), make_handler(store))
    host, port = srv.server_address
    print_json({
        "sensor": "oob_listener",
        "candidate": True,
        "nonce": nonce,
        "listen": f"http://{host}:{port}/cb?nonce={nonce}",
        "artifact": str(path),
        "control": "Use a unique nonce per attempted callback and verify target causality.",
        "replicated": "Run a second nonce if the callback is used for certainty >=0.8.",
    })
    deadline = time.monotonic() + args.timeout if args.timeout else None
    if deadline:
        srv.timeout = min(max(args.timeout, 0.05), 0.5)
    try:
        while True:
            if deadline and time.monotonic() >= deadline:
                break
            srv.handle_request()
            if args.once and store.events:
                break
    except KeyboardInterrupt:
        pass
    finally:
        srv.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
