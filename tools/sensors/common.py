#!/usr/bin/env python3
"""Shared helpers for proof-oriented sensors."""
from __future__ import annotations

import http.server
import json
import re
import socketserver
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


class FastLocalHTTPServer(http.server.ThreadingHTTPServer):
    """Threading HTTP server that avoids reverse-DNS startup stalls."""

    daemon_threads = True
    allow_reuse_address = True

    def server_bind(self) -> None:
        socketserver.TCPServer.server_bind(self)
        host, port = self.server_address[:2]
        self.server_name = str(host)
        self.server_port = int(port)


def safe_slug(value: str, default: str = "sensor") -> str:
    slug = re.sub(r"[^A-Za-z0-9._-]+", "_", value.strip())[:80].strip("._-")
    return slug or default


def sensor_dir(run: str | None) -> Path:
    if run:
        run_dir = Path(run)
        if not run_dir.is_absolute():
            run_dir = ROOT / run_dir
        return run_dir / "evidence" / "sensors"
    return ROOT / "tmp" / "sensors"


def write_artifact(run: str | None, sensor: str, tag: str, data: dict) -> Path:
    out_dir = sensor_dir(run)
    out_dir.mkdir(parents=True, exist_ok=True)
    ts = time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())
    path = out_dir / f"{safe_slug(sensor)}_{ts}_{safe_slug(tag)}.json"
    payload = {
        "sensor": sensor,
        "created_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        **data,
        "artifact": str(path),
    }
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    path.chmod(0o600)
    return path


def print_json(data: dict) -> None:
    print(json.dumps(data, ensure_ascii=False, indent=2))
