#!/usr/bin/env python3
"""Client/code graybox phenomenon sensor.

This is an optional profile for Electron/client artifacts. It records passive
leads only: package/config hints, ASAR presence, IPC/custom protocol strings,
and provided local-port listings. It never proves a finding by itself.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import print_json, write_artifact  # noqa: E402

MAX_FILE_BYTES = 256 * 1024
TEXT_EXTS = {".js", ".ts", ".json", ".html", ".xml", ".yml", ".yaml", ".ini", ".conf", ".config", ".txt"}
CONFIG_NAMES = {"package.json", "app.asar", "config.json", "settings.json", "electron-builder.yml"}


PATTERNS = {
    "electron": re.compile(rb"\belectron\b|BrowserWindow|ipcMain|ipcRenderer|contextBridge"),
    "ipc": re.compile(rb"ipcMain|ipcRenderer|contextBridge|preload\.js"),
    "custom_protocol": re.compile(rb"(?:protocol\.register|registerSchemesAsPrivileged|[a-zA-Z][a-zA-Z0-9+.-]{2,32}://)"),
    "url_fetch": re.compile(rb"\b(fetch|axios|XMLHttpRequest|request)\b|https?://"),
    "dangerous_setting": re.compile(rb"nodeIntegration\s*[:=]\s*true|contextIsolation\s*[:=]\s*false|webSecurity\s*[:=]\s*false"),
}


def _iter_files(paths: list[Path], limit: int) -> list[Path]:
    out: list[Path] = []
    for p in paths:
        if p.is_file():
            out.append(p)
        elif p.is_dir():
            for child in p.rglob("*"):
                if child.is_file():
                    out.append(child)
                    if len(out) >= limit:
                        return out
    return out[:limit]


def _read_prefix(path: Path) -> bytes:
    try:
        return path.read_bytes()[:MAX_FILE_BYTES]
    except Exception:
        return b""


def inspect_paths(paths: list[Path], limit: int = 500) -> list[dict]:
    findings: list[dict] = []
    for p in _iter_files(paths, limit):
        rel = str(p)
        name = p.name.lower()
        suffix = p.suffix.lower()
        data = _read_prefix(p)
        if name in CONFIG_NAMES or suffix == ".asar":
            findings.append({"kind": "client_artifact", "path": rel, "note": f"recognized {name or suffix}"})
        if suffix in TEXT_EXTS or data:
            for kind, pat in PATTERNS.items():
                if pat.search(data):
                    snippet = data[:4096].decode("utf-8", "replace")
                    findings.append({"kind": kind, "path": rel, "snippet": snippet[:240]})
    return findings


def ingest_ports(text: str) -> list[dict]:
    leads: list[dict] = []
    for line in text.splitlines():
        if re.search(r"\b(LISTEN|LISTENING)\b", line, re.I):
            leads.append({"kind": "local_listen_port", "line": line[:300]})
    return leads


def build(paths: list[Path], ports_file: Path | None = None, limit: int = 500) -> dict:
    leads = inspect_paths(paths, limit) if paths else []
    if ports_file and ports_file.exists():
        leads.extend(ingest_ports(ports_file.read_text(encoding="utf-8", errors="replace")))
    return {
        "candidate": False,
        "maturity": "phenomenon",
        "source": "client-graybox",
        "trust": "untrusted",
        "leads": leads,
        "count": len(leads),
        "control": "Passive graybox only. Active proof must be performed separately before candidate/finding.",
        "replicated": "Repeat by re-running against the same artifact snapshot or port listing.",
        "note": "Optional client-graybox profile; does not alter the web-first main loop.",
    }


def _selftest() -> int:
    import tempfile
    d = Path(tempfile.mkdtemp())
    (d / "package.json").write_text('{"main":"app.js","dependencies":{"electron":"1"}}', encoding="utf-8")
    (d / "app.js").write_text(
        "const {ipcMain, protocol} = require('electron');\n"
        "new BrowserWindow({webPreferences:{nodeIntegration:true, contextIsolation:false}});\n"
        "protocol.registerFileProtocol('sample', () => {}); fetch('https://api.example/v1');\n",
        encoding="utf-8")
    ports = d / "ports.txt"
    ports.write_text("node 123 tester 10u IPv4 TCP 127.0.0.1:4567 (LISTEN)\n", encoding="utf-8")
    data = build([d], ports)
    kinds = {x["kind"] for x in data["leads"]}
    checks = [
        ("defaults to phenomenon, not candidate", data["maturity"] == "phenomenon" and data["candidate"] is False),
        ("records electron artifact", "client_artifact" in kinds),
        ("records ipc lead", "ipc" in kinds),
        ("records custom protocol lead", "custom_protocol" in kinds),
        ("records dangerous setting as lead only", "dangerous_setting" in kinds),
        ("records local port listing", "local_listen_port" in kinds),
    ]
    bad = [n for n, ok in checks if not ok]
    for n, ok in checks:
        print(("ok   " if ok else "FAIL ") + n)
    print("client_graybox selftest " + ("passed" if not bad else f"FAILED ({len(bad)})"))
    return 0 if not bad else 1


def main() -> int:
    ap = argparse.ArgumentParser(description="Passive client/code graybox phenomenon sensor.")
    ap.add_argument("paths", nargs="*", type=Path, help="client source/package/log paths to inspect")
    ap.add_argument("--ports-file", type=Path, help="text output from lsof/netstat/ss to ingest")
    ap.add_argument("--limit", type=int, default=500)
    ap.add_argument("--run")
    ap.add_argument("--tag", default="client_graybox")
    ap.add_argument("--out", type=Path)
    ap.add_argument("--show-snippets", action="store_true", help="print code snippets to stdout; artifacts always keep full JSON")
    ap.add_argument("--selftest", action="store_true")
    args = ap.parse_args()
    if args.selftest:
        return _selftest()
    data = build(args.paths, args.ports_file, args.limit)
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        data["artifact"] = str(args.out)
        args.out.write_text(json.dumps({"sensor": "client_graybox", **data}, ensure_ascii=False, indent=2) + "\n",
                            encoding="utf-8")
        args.out.chmod(0o600)
    elif args.run:
        path = write_artifact(args.run, "client_graybox", args.tag, data)
        data["artifact"] = str(path)
    stdout_data = {"sensor": "client_graybox", **data}
    if not args.show_snippets:
        stdout_data["leads"] = [{k: v for k, v in lead.items() if k != "snippet"} for lead in data["leads"]]
        stdout_data["snippets_redacted"] = True
    print_json(stdout_data)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
