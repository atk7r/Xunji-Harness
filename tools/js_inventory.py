#!/usr/bin/env python3
"""Read-only JS/API inventory over saved Xunji artifacts.

This is a sensor, not a target executor. It reads files already present under a
run directory (or explicit paths inside that run), extracts likely API calls and
client-side signing/role/state hints, and prints candidate input shapes/threat
hypotheses for Root to merge manually.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import tempfile
from pathlib import Path
from urllib.parse import parse_qsl, urlparse

try:
    sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
except Exception:
    pass

ROOT = Path(__file__).resolve().parents[1]
MAX_FILE_BYTES = 2_000_000
SCAN_SUFFIXES = {".js", ".mjs", ".html", ".htm", ".json", ".txt"}


def _resolve_run_dir(path: str | Path) -> Path:
    p = Path(path)
    return (p if p.is_absolute() else ROOT / p).resolve()


def _inside(root: Path, path: Path) -> bool:
    try:
        path.resolve().relative_to(root.resolve())
        return True
    except Exception:
        return False


def _rel(root: Path, path: Path) -> str:
    try:
        return path.resolve().relative_to(root.resolve()).as_posix()
    except Exception:
        return str(path)


def _read_text(path: Path) -> str:
    if not path.exists() or not path.is_file():
        return ""
    try:
        if path.stat().st_size > MAX_FILE_BYTES:
            return path.read_text(encoding="utf-8", errors="replace")[:MAX_FILE_BYTES]
        return path.read_text(encoding="utf-8", errors="replace")
    except Exception:
        return ""


def _candidate_files(run_dir: Path, explicit: list[str] | None = None) -> list[Path]:
    if explicit:
        files: list[Path] = []
        for raw in explicit:
            p = Path(raw)
            p = p if p.is_absolute() else run_dir / p
            p = p.resolve()
            if not _inside(run_dir, p):
                raise ValueError(f"path outside run_dir is not allowed: {raw}")
            if p.is_file():
                files.append(p)
        return sorted(set(files))

    roots = [run_dir / "evidence", run_dir / "classify", run_dir]
    files = []
    seen: set[Path] = set()
    for root in roots:
        if not root.exists():
            continue
        for p in root.rglob("*"):
            if p in seen or not p.is_file():
                continue
            seen.add(p)
            if p.suffix.lower() in SCAN_SUFFIXES:
                files.append(p.resolve())
    return sorted(files)


def _extract_urls_from_json(text: str) -> list[dict]:
    try:
        data = json.loads(text)
    except Exception:
        return []
    out: list[dict] = []

    def walk(obj) -> None:
        if isinstance(obj, dict):
            url = obj.get("url") or obj.get("requestUrl") or obj.get("href")
            if isinstance(url, str) and re.search(r"/|\?", url):
                method = str(obj.get("method") or obj.get("requestMethod") or "").upper()
                out.append({"method": method or "GET", "url": url, "source": "json"})
            for value in obj.values():
                walk(value)
        elif isinstance(obj, list):
            for item in obj:
                walk(item)

    walk(data)
    return out


_STRING = r"['\"]([^'\"]{1,400})['\"]"


def _extract_calls(text: str, suffix: str) -> list[dict]:
    calls: list[dict] = []
    if suffix == ".json":
        calls.extend(_extract_urls_from_json(text))

    patterns = [
        (re.compile(rf"\bfetch\(\s*{_STRING}", re.I), "GET"),
        (re.compile(rf"\baxios\.(get|delete|post|put|patch)\(\s*{_STRING}", re.I), None),
        (re.compile(rf"\baxios\(\s*\{{[^}}]*\burl\s*:\s*{_STRING}[^}}]*\bmethod\s*:\s*{_STRING}", re.I | re.S), None),
        (re.compile(rf"\.open\(\s*{_STRING}\s*,\s*{_STRING}", re.I), None),
        (re.compile(rf"\burl\s*:\s*{_STRING}", re.I), "GET"),
        (re.compile(rf"\baction\s*=\s*{_STRING}", re.I), "GET"),
    ]
    for rx, default_method in patterns:
        for m in rx.finditer(text):
            groups = [g for g in m.groups() if g is not None]
            method = default_method or "GET"
            url = ""
            if rx.pattern.startswith("\\baxios\\."):
                method = groups[0].upper()
                url = groups[1]
            elif ".open" in rx.pattern:
                method = groups[0].upper()
                url = groups[1]
            elif "method" in rx.pattern and len(groups) >= 2:
                url = groups[0]
                method = groups[1].upper()
            elif groups:
                url = groups[-1]
            if url and re.search(r"^https?://|^/|api|rest|graphql|\\.do|\\.json|\\?", url, re.I):
                calls.append({"method": method, "url": url, "source": "text"})
    return calls


def _params(url: str, nearby: str = "") -> list[str]:
    parsed = urlparse(url)
    params = [k for k, _v in parse_qsl(parsed.query, keep_blank_values=True)]
    if nearby:
        for key in re.findall(r"['\"]([A-Za-z_][A-Za-z0-9_]{1,40})['\"]\s*:", nearby):
            if key not in params:
                params.append(key)
    return params[:12]


def _signature_hint(text: str, url: str) -> str:
    hay = f"{url}\n{text}"
    hits = []
    for token in ("sign", "signature", "token", "nonce", "timestamp", "hmac", "sha256", "md5", "encrypt"):
        if re.search(rf"\b{token}\b", hay, re.I):
            hits.append(token)
    return ", ".join(hits[:8]) if hits else "none observed"


def _role_hint(url: str, text: str) -> str:
    hay = f"{url}\n{text[:2000]}"
    for label, rx in [
        ("admin/management route", r"\b(admin|manage|manager|console|role|permission)\b"),
        ("tenant/account boundary", r"\b(tenant|org|company|dept|account|uid|userId|owner)\b"),
        ("identity/auth route", r"\b(auth|login|sso|oauth|token|session)\b"),
    ]:
        if re.search(rx, hay, re.I):
            return label
    return "unknown"


def _state_hint(method: str, url: str, text: str) -> str:
    hay = f"{method} {url}\n{text[:2000]}"
    if method.upper() in {"POST", "PUT", "PATCH", "DELETE"}:
        return "state-changing method"
    for token in ("submit", "approve", "publish", "pay", "create", "delete", "update", "status", "workflow"):
        if re.search(rf"\b{token}\b", hay, re.I):
            return f"state keyword: {token}"
    return "none observed"


def inventory(run_dir: Path, explicit_paths: list[str] | None = None) -> dict:
    run_dir = _resolve_run_dir(run_dir)
    files = _candidate_files(run_dir, explicit_paths)
    candidates: list[dict] = []
    seen: set[tuple[str, str]] = set()
    for path in files:
        text = _read_text(path)
        if not text:
            continue
        calls = _extract_calls(text, path.suffix.lower())
        for call in calls:
            method = str(call.get("method") or "GET").upper()
            url = str(call.get("url") or "").strip()
            key = (method, url)
            if not url or key in seen:
                continue
            seen.add(key)
            window = text[max(0, text.find(url) - 500): text.find(url) + 1000] if url in text else text[:1500]
            candidates.append({
                "method": method,
                "url": url,
                "source_artifact": _rel(run_dir, path),
                "params": _params(url, window),
                "signature_hint": _signature_hint(window, url),
                "role_hint": _role_hint(url, window),
                "state_hint": _state_hint(method, url, window),
            })
    return {
        "schema": "xunji.js_inventory.v1",
        "run_dir": str(run_dir),
        "note": "read-only over saved artifacts; no target network requests performed",
        "scanned_files": [_rel(run_dir, p) for p in files],
        "candidates": candidates,
    }


def render_markdown(data: dict) -> str:
    lines = [
        "# JS Inventory",
        "",
        f"- Run dir: {data['run_dir']}",
        "- Mode: read-only saved artifacts; no target network requests performed.",
        f"- Files scanned: {len(data.get('scanned_files', []))}",
        "",
        "## Candidate Input Shapes",
        "",
    ]
    candidates = data.get("candidates", [])
    if not candidates:
        lines.append("- (no API-like calls found in saved artifacts)")
    for idx, item in enumerate(candidates, start=1):
        params = ", ".join(item.get("params") or []) or "none observed"
        lines.extend([
            f"### IS-CAND-{idx:03d}",
            f"- URL pattern: {item['method']} {item['url']}",
            f"- Source JS/artifact: {item['source_artifact']}",
            f"- Client-controlled params: {params}",
            f"- Client-side signature/token/nonce logic: {item['signature_hint']}",
            f"- Role or permission hint: {item['role_hint']}",
            f"- State transition: {item['state_hint']}",
            "- Linked threat hypothesis: pending",
            "",
        ])
    lines.extend(["## Candidate Threat Hypotheses", ""])
    threat_n = 0
    for item in candidates:
        if item["role_hint"] == "unknown" and item["signature_hint"] == "none observed" \
                and item["state_hint"] == "none observed":
            continue
        threat_n += 1
        lines.extend([
            f"### TH-CAND-{threat_n:03d}",
            f"- Threat hypothesis: {item['role_hint']} or {item['state_hint']} deserves control on {item['method']} {item['url']}",
            f"- Asset/role/input: {item['url']} / {item['role_hint']} / params={', '.join(item.get('params') or []) or 'none observed'}",
            "- Expected signal: response differs by role, owner object, signature freshness, or state transition.",
            "- Refutation/control: baseline replay with unauthorized role and tampered owner/signature rejects equally.",
            f"- Linked IS/C/E: source artifact {item['source_artifact']}",
            "- Status: candidate",
            "- Next action: Root may merge to hypotheses.md, then run guarded proof-level controls.",
            "",
        ])
    if threat_n == 0:
        lines.append("- (no role/signature/state hints strong enough for a candidate hypothesis)")
    return "\n".join(lines).rstrip() + "\n"


def _selftest() -> int:
    d = Path(tempfile.mkdtemp())
    run = d / "run"
    (run / "evidence").mkdir(parents=True)
    (run / "evidence" / "app.js").write_text(
        "const nonce = Date.now();\n"
        "function makeSign(uid){ return md5(uid + nonce); }\n"
        "fetch('/api/admin/users?tenantId=1', {method: 'POST', body: JSON.stringify({uid: uid, sign: makeSign(uid)})});\n"
        "axios.get('/api/profile?userId=42');\n",
        encoding="utf-8")
    (run / "evidence" / "network.json").write_text(json.dumps([
        {"url": "https://app.example/api/order/status?id=7", "method": "GET"}
    ]), encoding="utf-8")
    data = inventory(run)
    md = render_markdown(data)
    outside = d / "outside.js"
    outside.write_text("fetch('/api/x')", encoding="utf-8")
    outside_blocked = False
    try:
        inventory(run, [str(outside)])
    except ValueError:
        outside_blocked = True
    checks = [
        ("extracts fetch endpoint", any("/api/admin/users" in c["url"] for c in data["candidates"])),
        ("extracts axios endpoint", any("/api/profile" in c["url"] for c in data["candidates"])),
        ("extracts saved network json endpoint", any("/api/order/status" in c["url"] for c in data["candidates"])),
        ("detects signature nonce logic", "sign" in md and "nonce" in md and "md5" in md),
        ("emits candidate threat hypothesis only", "Candidate Threat Hypotheses" in md and "Status: candidate" in md),
        ("blocks explicit paths outside run", outside_blocked),
    ]
    bad = [name for name, ok in checks if not ok]
    for name, ok in checks:
        print(("ok   " if ok else "FAIL ") + name)
    print("js_inventory selftest " + ("passed" if not bad else f"FAILED ({len(bad)})"))
    return 0 if not bad else 1


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="read-only JS/API inventory over saved run artifacts")
    ap.add_argument("run_dir", nargs="?", type=Path)
    ap.add_argument("--path", action="append", default=[], help="explicit file path inside run_dir; repeatable")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--selftest", action="store_true")
    args = ap.parse_args(argv)
    if args.selftest:
        return _selftest()
    if not args.run_dir:
        ap.error("run_dir is required")
    try:
        data = inventory(args.run_dir, args.path or None)
    except ValueError as e:
        print(f"[js_inventory] {e}", file=sys.stderr)
        return 2
    if args.json:
        print(json.dumps(data, ensure_ascii=False, indent=2))
    else:
        print(render_markdown(data), end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
