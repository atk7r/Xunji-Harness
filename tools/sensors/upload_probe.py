#!/usr/bin/env python3
"""Harmless multipart upload proof sensor.

This sends a small marker file through probe.send (guard-routed). It can record
the expected remote reference in UploadRegistry so closure gates know cleanup is
owed. It does not attempt parser bypasses or webshell behavior by itself.
"""
from __future__ import annotations

import argparse
import http.server
import json
import os
import secrets
import shutil
import sys
import tempfile
import threading
from pathlib import Path

TOOLS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(TOOLS))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import probe  # noqa: E402
from common import FastLocalHTTPServer, print_json, write_artifact  # noqa: E402
from harness import guard as guardmod  # noqa: E402
from harness.guard import UploadRegistry  # noqa: E402


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


def multipart(field: str, filename: str, content: bytes, content_type: str) -> tuple[bytes, str]:
    boundary = "----xunji-proof-" + secrets.token_hex(8)
    safe_field = field.replace("\r", "_").replace("\n", "_").replace('"', "%22")
    safe_filename = filename.replace("\r", "_").replace("\n", "_").replace('"', "%22")
    safe_content_type = content_type.replace("\r", "_").replace("\n", "_")
    body = (
        f"--{boundary}\r\n"
        f'Content-Disposition: form-data; name="{safe_field}"; filename="{safe_filename}"\r\n'
        f"Content-Type: {safe_content_type}\r\n\r\n"
    ).encode() + content + f"\r\n--{boundary}--\r\n".encode()
    return body, boundary


def run_upload(url: str, field: str, filename: str, marker: str, headers: dict,
               timeout: int, proxy: str | None) -> dict:
    body, boundary = multipart(field, filename, marker.encode(), "text/plain")
    h = {"Content-Type": f"multipart/form-data; boundary={boundary}", **headers}
    old_proxy = probe._PROXY
    if proxy is not None:
        probe._PROXY = proxy
    try:
        res = probe.send("POST", url, h, body, None, timeout, want_headers=True)
    finally:
        probe._PROXY = old_proxy
    return {
        "candidate": True,
        "upload": res,
        "marker": marker,
        "filename": filename,
        "field": field,
        "control": "Marker content is harmless and unique; compare with a disallowed or safe baseline if claiming bypass.",
        "replicated": "Repeat with a fresh marker before certainty >=0.8.",
    }


def cleanup(cleanup_url: str, method: str, headers: dict, timeout: int, proxy: str | None) -> dict:
    old_proxy = probe._PROXY
    if proxy is not None:
        probe._PROXY = proxy
    try:
        return probe.send(method, cleanup_url, headers, None, None, timeout, want_headers=True)
    finally:
        probe._PROXY = old_proxy


def _selftest() -> int:
    old_state = _isolate_selftest_state()
    seen = {}
    srv = None
    t = None

    class H(http.server.BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_POST(self):
            raw = self.rfile.read(int(self.headers.get("Content-Length", "0")))
            seen["body"] = raw
            self.send_response(201)
            self.send_header("Content-Length", "2")
            self.end_headers()
            self.wfile.write(b"ok")

        def do_DELETE(self):
            seen["deleted"] = True
            self.send_response(204)
            self.send_header("Content-Length", "0")
            self.end_headers()

    try:
        srv = FastLocalHTTPServer(("127.0.0.1", 0), H)
        port = srv.server_address[1]
        t = threading.Thread(target=lambda: srv.serve_forever(poll_interval=0.05), daemon=True)
        t.start()
        data = run_upload(f"http://127.0.0.1:{port}/upload", "file", "proof.txt", "XUNJI_MARKER", {}, 5, None)
        clean = cleanup(f"http://127.0.0.1:{port}/upload/proof.txt", "DELETE", {}, 5, None)
    finally:
        if srv:
            srv.shutdown()
            srv.server_close()
        if t:
            t.join(timeout=1)
        _restore_selftest_state(old_state)
    injected, _ = multipart("fi\r\nX: y", "proof\"\r\nX: y.txt", b"x", "text/plain\r\nX: y")
    injected_headers = injected.split(b"\r\n\r\n", 1)[0]
    checks = [
        ("upload status captured", data["upload"].get("status") == 201),
        ("multipart contains marker", b"XUNJI_MARKER" in seen.get("body", b"")),
        ("cleanup status captured", clean.get("status") == 204 and seen.get("deleted") is True),
        ("multipart headers block CRLF injection", b"\r\nX:" not in injected_headers),
    ]
    bad = [n for n, ok in checks if not ok]
    for n, ok in checks:
        print(("ok   " if ok else "FAIL ") + n)
    print("upload_probe selftest " + ("passed" if not bad else f"FAILED ({len(bad)})"))
    return 0 if not bad else 1


def main() -> int:
    ap = argparse.ArgumentParser(description="Send a harmless multipart upload proof object through guard-routed probe.")
    ap.add_argument("url", nargs="?")
    ap.add_argument("--field", default="file")
    ap.add_argument("--filename", default=None)
    ap.add_argument("--marker", default=None)
    ap.add_argument("-H", "--header", action="append", default=[])
    ap.add_argument("--timeout", type=int, default=20)
    ap.add_argument("--proxy", default=None)
    ap.add_argument("--run", help="run dir; writes artifact and optionally UploadRegistry entry")
    ap.add_argument("--remote-ref", help="remote path/id expected for cleanup tracking")
    ap.add_argument("--cleanup-url", help="optional URL to request after upload")
    ap.add_argument("--cleanup-method", default="DELETE")
    ap.add_argument("--mark-cleaned", action="store_true", help="mark --remote-ref cleaned after cleanup request succeeds")
    ap.add_argument("--tag", default="upload_probe")
    ap.add_argument("--out", type=Path)
    ap.add_argument("--selftest", action="store_true")
    args = ap.parse_args()
    if args.selftest:
        return _selftest()
    if not args.url:
        ap.error("url is required")
    marker = args.marker or ("XUNJI-PROOF-" + secrets.token_hex(8))
    filename = args.filename or (marker.lower() + ".txt")
    headers = _headers(args.header)
    data = run_upload(args.url, args.field, filename, marker, headers, args.timeout, args.proxy)
    if args.run and args.remote_ref:
        UploadRegistry().register(Path(args.run).name, args.url, args.remote_ref,
                                  note=f"upload_probe marker={marker}")
        data["upload_registry"] = {"run": Path(args.run).name, "remote_ref": args.remote_ref, "registered": True}
    if args.cleanup_url:
        clean = cleanup(args.cleanup_url, args.cleanup_method.upper(), headers, args.timeout, args.proxy)
        data["cleanup"] = clean
        if args.mark_cleaned and args.run and args.remote_ref and 200 <= int(clean.get("status", 0)) < 300:
            UploadRegistry().mark_cleaned(Path(args.run).name, args.remote_ref)
            data.setdefault("upload_registry", {"run": Path(args.run).name, "remote_ref": args.remote_ref})
            data["upload_registry"]["cleaned"] = True
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        data["artifact"] = str(args.out)
        args.out.write_text(json.dumps({"sensor": "upload_probe", **data}, ensure_ascii=False, indent=2) + "\n",
                            encoding="utf-8")
        args.out.chmod(0o600)
    elif args.run:
        path = write_artifact(args.run, "upload_probe", args.tag, data)
        data["artifact"] = str(path)
    print_json({"sensor": "upload_probe", **data})
    status = int(data["upload"].get("status", 0) or 0)
    return 0 if 200 <= status < 400 else 1


if __name__ == "__main__":
    raise SystemExit(main())
