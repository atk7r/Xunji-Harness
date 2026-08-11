#!/usr/bin/env python3
"""Bounded offline JS/API inventory over one saved evidence artifact.

The live command is intentionally closed::

    python3 tools/js_inventory.py inspect runs/<name> evidence/<artifact>

It performs no network I/O and writes no run state.  The source artifact is
secure-opened through :mod:`artifact_view`; output is bounded JSON containing
only target-derived candidates for Root adjudication, never evidence or findings.
"""
from __future__ import annotations

import contextlib
import hashlib
import io
import json
import re
import sys
import tempfile
from pathlib import Path
from unittest import mock
from urllib.parse import unquote, unquote_plus, urlsplit

try:
    sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
    sys.stderr.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
except Exception:
    pass

import artifact_view
from harness import privacy as privacymod


SCHEMA = "xunji.js-inventory.v2"
ERROR_SCHEMA = "xunji.js-inventory-error.v1"
AUTHORITY = (
    "read-only target-derived candidates; Root/Single Synthesizer and the "
    "evidence gate retain all promotion authority"
)
TRUST = "untrusted_target_derived_candidate"

MAX_SCAN_BYTES = 2 * 1024 * 1024
MAX_CANDIDATES = 64
MAX_OUTPUT_BYTES = 64 * 1024
MAX_RAW_CALLS = MAX_CANDIDATES * 4
MAX_URL_BYTES = 2048
MAX_ROUTE_BYTES = 1024
MAX_JSON_NODES = 4096
MAX_JSON_DEPTH = 32
MAX_QUERY_FIELDS = 48
MAX_PARAMS = 12
MAX_NEARBY_BYTES = 1500

SCAN_SUFFIXES = frozenset({".js", ".mjs", ".html", ".htm", ".json", ".txt"})
METHODS = frozenset({"GET", "POST", "PUT", "PATCH", "DELETE", "HEAD", "OPTIONS"})
_RUN_REFERENCE_RE = re.compile(r"runs/[A-Za-z0-9][A-Za-z0-9._-]{0,127}\Z")
_CONTROL_RE = re.compile(r"[\x00-\x1f\x7f]")
_SAFE_KEY_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_.-]{0,63}\Z")
_SAFE_ARTIFACT_PART_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}\Z")
_SAFE_PATH_SEGMENT_RE = re.compile(r"[A-Za-z0-9._~%-]{1,64}\Z")
_SENSITIVE_SEGMENT_RE = re.compile(
    r"(?i)(?:^|[-_.])(?:token|secret|session|password|passwd|auth|jwt|"
    r"signature|sig|api[-_]?key)(?:[-_.:=]|$)"
)
_HIGH_ENTROPY_SEGMENT_RE = re.compile(
    r"(?:[A-Fa-f0-9]{16,}|[A-Za-z0-9_-]{24,})"
)
_STRING = r"['\"]([^'\"]{1,400})['\"]"


class JSInventoryError(ValueError):
    """Stable, privacy-safe JS inventory failure."""

    def __init__(self, code: str, cause_code: str = ""):
        self.code = code
        self.cause_code = cause_code
        super().__init__(code)


def _fail(code: str, cause_code: str = "") -> None:
    raise JSInventoryError(code, cause_code)


def _validate_run_reference(value: str) -> str:
    raw = str(value or "")
    if not _RUN_REFERENCE_RE.fullmatch(raw):
        _fail("JS_INVENTORY_RUN_REFERENCE_INVALID")
    return raw


def _validate_artifact_reference(value: str) -> str:
    raw = str(value or "")
    if not raw or len(raw.encode("utf-8", "replace")) > 1024 \
            or "\\" in raw or _CONTROL_RE.search(raw):
        _fail("JS_INVENTORY_ARTIFACT_REFERENCE_INVALID")
    parts = raw.split("/")
    if len(parts) < 2 or parts[0] != "evidence" \
            or any(
                part in {"", ".", ".."}
                or _SAFE_ARTIFACT_PART_RE.fullmatch(part) is None
                for part in parts[1:]
            ):
        _fail("JS_INVENTORY_ARTIFACT_REFERENCE_INVALID")
    suffix = Path(parts[-1]).suffix.lower()
    if suffix not in SCAN_SUFFIXES:
        _fail("JS_INVENTORY_ARTIFACT_TYPE_UNSUPPORTED")
    return "/".join(parts)


def _digest(value: str | bytes) -> str:
    raw = value if isinstance(value, bytes) else value.encode("utf-8", "replace")
    return hashlib.sha256(raw).hexdigest()


def _redacted(label: str) -> str:
    """Return a non-reversible shape marker, never a digest of secret material."""
    return f"<{label}:redacted>"


def _safe_query_key(value: str) -> str:
    source = str(value or "")[:768]
    raw = unquote_plus(source)[:256]
    safe = privacymod.sanitize_model_egress_text(raw)
    safe = _CONTROL_RE.sub("", safe).strip()
    if "%" not in source \
            and _SAFE_KEY_RE.fullmatch(safe) \
            and not _HIGH_ENTROPY_SEGMENT_RE.search(safe):
        return safe
    return _redacted("field")


def _query_keys(query: str) -> tuple[list[str], bool]:
    keys: list[str] = []
    truncated = False
    fields = str(query or "").split("&") if query else []
    if len(fields) > MAX_QUERY_FIELDS:
        fields = fields[:MAX_QUERY_FIELDS]
        truncated = True
    for field in fields:
        raw_key = field.split("=", 1)[0]
        key = _safe_query_key(raw_key)
        if key not in keys:
            keys.append(key)
        if len(keys) >= MAX_PARAMS:
            truncated = truncated or len(fields) > len(keys)
            break
    return keys, truncated


def _safe_path(path: str) -> str:
    raw = str(path or "")
    leading = raw.startswith("/")
    trailing = raw.endswith("/") and raw != "/"
    safe_parts: list[str] = []
    redact_next = False
    for part in raw.split("/"):
        if not part:
            continue
        decoded = unquote(part)[:256]
        sanitized = privacymod.sanitize_model_egress_text(decoded)
        sanitized = _CONTROL_RE.sub("", sanitized).strip()
        sensitive_key = bool(_SENSITIVE_SEGMENT_RE.search(decoded))
        if "%" in part or redact_next or not sanitized or sanitized in {".", ".."} \
                or _SAFE_PATH_SEGMENT_RE.fullmatch(sanitized) is None \
                or sensitive_key \
                or _HIGH_ENTROPY_SEGMENT_RE.search(sanitized):
            sanitized = _redacted("segment")
        safe_parts.append(sanitized)
        redact_next = sensitive_key
    value = ("/" if leading else "") + "/".join(safe_parts)
    if trailing and value and value != "/":
        value += "/"
    if not value and leading:
        value = "/"
    return value


def _safe_host(parsed) -> str:
    try:
        host = str(parsed.hostname or "").strip().lower().rstrip(".")
        port = parsed.port
    except ValueError:
        return ""
    if not host or _CONTROL_RE.search(host):
        return ""
    try:
        host = host.encode("idna").decode("ascii")
    except UnicodeError:
        return ""
    if len(host) > 253 or port is not None and not 1 <= port <= 65535:
        return ""
    if ":" in host and not host.startswith("["):
        host = f"[{host}]"
    return f"{host}:{port}" if port is not None else host


def _url_pattern(raw_value: str) -> tuple[str, list[str], dict] | None:
    raw = str(raw_value or "").strip()
    if not raw or len(raw.encode("utf-8", "replace")) > MAX_URL_BYTES \
            or _CONTROL_RE.search(raw):
        return None
    try:
        parsed = urlsplit(raw)
    except ValueError:
        return None
    scheme = parsed.scheme.lower()
    if scheme and scheme not in {"http", "https", "ws", "wss"}:
        return None
    if scheme and not parsed.netloc:
        return None
    host = _safe_host(parsed) if parsed.netloc else ""
    if parsed.netloc and not host:
        return None
    path = _safe_path(parsed.path)
    if parsed.netloc and not path:
        path = "/"
    keys, query_truncated = _query_keys(parsed.query)
    query = "&".join(f"{key}=*" for key in keys)
    if scheme:
        pattern = f"{scheme}://{host}{path}"
    elif parsed.netloc:
        pattern = f"//{host}{path}"
    else:
        pattern = path
    if query:
        pattern += "?" + query
    if not pattern or len(pattern.encode("utf-8", "replace")) > MAX_ROUTE_BYTES:
        return None
    return pattern, keys, {
        "userinfo_removed": parsed.username is not None or parsed.password is not None,
        "fragment_removed": bool(parsed.fragment),
        "query_values_redacted": bool(parsed.query),
        "query_fields_truncated": query_truncated,
    }


def _extract_urls_from_json(text: str, *, limit: int) -> tuple[list[dict], bool]:
    try:
        data = json.loads(text)
    except (json.JSONDecodeError, RecursionError, MemoryError):
        return [], False
    out: list[dict] = []
    stack: list[tuple[object, int]] = [(data, 0)]
    nodes = 0
    truncated = False
    while stack:
        obj, depth = stack.pop()
        nodes += 1
        if nodes > MAX_JSON_NODES or depth > MAX_JSON_DEPTH:
            truncated = True
            continue
        if isinstance(obj, dict):
            url = obj.get("url") or obj.get("requestUrl") or obj.get("href")
            if isinstance(url, str) and re.search(r"/|\?", url):
                method = str(obj.get("method") or obj.get("requestMethod") or "GET").upper()
                out.append({"method": method, "url": url})
                if len(out) >= limit:
                    return out, True
            for value in reversed(list(obj.values())):
                if isinstance(value, (dict, list)):
                    stack.append((value, depth + 1))
        elif isinstance(obj, list):
            for value in reversed(obj):
                if isinstance(value, (dict, list)):
                    stack.append((value, depth + 1))
    return out, truncated


def _fetch_method(text: str, end: int) -> str:
    nearby = text[end:end + 320]
    match = re.search(
        r"\bmethod\s*:\s*['\"]([A-Za-z]{2,12})['\"]", nearby, re.I,
    )
    return match.group(1).upper() if match else "GET"


def _extract_calls(text: str, suffix: str) -> tuple[list[dict], bool]:
    calls: list[dict] = []
    truncated = False
    if suffix == ".json":
        json_calls, json_truncated = _extract_urls_from_json(
            text, limit=MAX_RAW_CALLS,
        )
        calls.extend(json_calls)
        truncated = json_truncated
        if len(calls) >= MAX_RAW_CALLS:
            return calls[:MAX_RAW_CALLS], True

    patterns = (
        (re.compile(rf"\bfetch\(\s*{_STRING}", re.I), "fetch"),
        (re.compile(rf"\baxios\.(get|delete|post|put|patch)\(\s*{_STRING}", re.I), "axios_method"),
        (re.compile(rf"\baxios\(\s*\{{[^}}]*\burl\s*:\s*{_STRING}[^}}]*\bmethod\s*:\s*{_STRING}", re.I | re.S), "axios_config"),
        (re.compile(rf"\.open\(\s*{_STRING}\s*,\s*{_STRING}", re.I), "xhr"),
        (re.compile(rf"\bnew\s+WebSocket\(\s*{_STRING}", re.I), "websocket"),
        (re.compile(rf"\burl\s*:\s*{_STRING}", re.I), "url"),
        (re.compile(rf"\baction\s*=\s*{_STRING}", re.I), "action"),
    )
    for rx, kind in patterns:
        for match in rx.finditer(text):
            groups = [value for value in match.groups() if value is not None]
            method = "GET"
            url = ""
            if kind == "fetch":
                url = groups[0]
                method = _fetch_method(text, match.end())
            elif kind == "axios_method":
                method, url = groups[0].upper(), groups[1]
            elif kind == "axios_config":
                url, method = groups[0], groups[1].upper()
            elif kind == "xhr":
                method, url = groups[0].upper(), groups[1]
            elif kind == "websocket":
                method, url = "GET", groups[0]
            elif groups:
                url = groups[-1]
            if url and re.search(
                    r"^(?:https?|wss?)://|^/|api|rest|graphql|\.do|\.json|\?",
                    url, re.I):
                calls.append({"method": method, "url": url})
                if len(calls) >= MAX_RAW_CALLS:
                    return calls, True
    return calls, truncated


def _nearby(text: str, value: str) -> str:
    position = text.find(value)
    if position < 0:
        return text[:MAX_NEARBY_BYTES]
    return text[max(0, position - 500):position + 1000]


def _params(query_keys: list[str], nearby: str) -> list[str]:
    params = list(query_keys)
    for key in re.findall(
            r"['\"]([A-Za-z_][A-Za-z0-9_.-]{1,63})['\"]\s*:", nearby):
        safe = _safe_query_key(key)
        if safe not in params:
            params.append(safe)
        if len(params) >= MAX_PARAMS:
            break
    return params[:MAX_PARAMS]


def _signature_hint(text: str, pattern: str) -> list[str]:
    haystack = f"{pattern}\n{text}"
    return [
        token for token in (
            "sign", "signature", "token", "nonce", "timestamp", "hmac",
            "sha256", "md5", "encrypt",
        )
        if re.search(rf"\b{token}\b", haystack, re.I)
    ][:8]


def _role_hint(pattern: str, text: str) -> str:
    haystack = f"{pattern}\n{text[:1000]}"
    for label, regex in (
        ("admin_management", r"\b(admin|manage|manager|console|role|permission)\b"),
        ("tenant_account", r"\b(tenant|org|company|dept|account|uid|userId|owner)\b"),
        ("identity_auth", r"\b(auth|login|sso|oauth|token|session)\b"),
    ):
        if re.search(regex, haystack, re.I):
            return label
    return "unknown"


def _state_hint(method: str, pattern: str, text: str) -> str:
    if method in {"POST", "PUT", "PATCH", "DELETE"}:
        return "state_changing_method"
    haystack = f"{pattern}\n{text[:1000]}"
    for token in (
        "submit", "approve", "publish", "pay", "create", "delete", "update",
        "status", "workflow",
    ):
        if re.search(rf"\b{token}\b", haystack, re.I):
            return f"state_keyword_{token}"
    return "none_observed"


def _serialized(data: dict) -> str:
    return json.dumps(
        data, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
    )


def _fit_output(data: dict) -> dict:
    data["output_truncated"] = False
    while len((_serialized(data) + "\n").encode("utf-8")) > MAX_OUTPUT_BYTES:
        candidates = data.get("candidates")
        if not isinstance(candidates, list) or not candidates:
            _fail("JS_INVENTORY_OUTPUT_LIMIT_EXCEEDED")
        candidates.pop()
        data["returned_candidates"] = len(candidates)
        data["candidates_truncated"] = True
        data["output_truncated"] = True
        warnings = data.setdefault("warnings", [])
        if "output_limit" not in warnings:
            warnings.append("output_limit")
    return data


def inventory(
    run_dir: str | Path,
    artifact: str,
    *,
    runs_root: str | Path = artifact_view.RUNS_ROOT,
) -> dict:
    artifact_reference = _validate_artifact_reference(artifact)
    try:
        snapshot = artifact_view.read_bounded_artifact(
            run_dir, artifact_reference,
            scan_limit=MAX_SCAN_BYTES, runs_root=runs_root,
        )
    except artifact_view.ArtifactViewError as exc:
        _fail("JS_INVENTORY_ARTIFACT_REJECTED", exc.code)

    text = snapshot.payload.decode("utf-8", "replace")
    raw_calls, parser_truncated = _extract_calls(
        text, Path(snapshot.artifact).suffix.lower(),
    )
    candidates: list[dict] = []
    seen: set[tuple[str, str]] = set()
    candidate_truncated = parser_truncated
    for call in raw_calls:
        method = str(call.get("method") or "GET").upper()
        if method not in METHODS:
            continue
        raw_url = str(call.get("url") or "")
        normalized = _url_pattern(raw_url)
        if normalized is None:
            continue
        pattern, query_keys, redaction_meta = normalized
        key = (method, pattern)
        if key in seen:
            continue
        seen.add(key)
        nearby = _nearby(text, raw_url)
        candidate_id = "JS-CAND-" + _digest(
            json.dumps([method, pattern], ensure_ascii=False, separators=(",", ":"))
        )[:12]
        candidates.append({
            "candidate_id": candidate_id,
            "method": method,
            "route_pattern": pattern,
            "params": _params(query_keys, nearby),
            "signature_hints": _signature_hint(nearby, pattern),
            "role_hint": _role_hint(pattern, nearby),
            "state_hint": _state_hint(method, pattern, nearby),
            **redaction_meta,
        })
        if len(candidates) >= MAX_CANDIDATES:
            candidate_truncated = candidate_truncated or len(raw_calls) > len(seen)
            break

    warnings: list[str] = []
    if snapshot.scan_truncated:
        warnings.append("scan_limit")
    if parser_truncated:
        warnings.append("parser_limit")
    if candidate_truncated:
        warnings.append("candidate_limit")
    data = {
        "schema": SCHEMA,
        "operation": "inspect",
        "run": "active_run",
        "artifact": {
            "id": "selected-evidence-artifact",
            "type": Path(snapshot.artifact).suffix.lower(),
        },
        "trust": TRUST,
        "authority": AUTHORITY,
        "file_size": snapshot.file_size,
        "scanned_bytes": snapshot.scanned_bytes,
        "scan_truncated": snapshot.scan_truncated,
        "returned_candidates": len(candidates),
        "candidates_truncated": candidate_truncated,
        "warnings": warnings,
        "candidates": candidates,
    }
    return _fit_output(data)


def _error_document(exc: JSInventoryError) -> dict:
    result = {
        "schema": ERROR_SCHEMA,
        "ok": False,
        "error_code": exc.code,
    }
    if exc.cause_code:
        result["cause_code"] = exc.cause_code
    return result


def _expect_error(code: str, call) -> bool:
    try:
        call()
    except JSInventoryError as exc:
        return exc.code == code
    return False


def _run_inspect_cli(values: list[str], *, runs_root: str | Path) -> int:
    """Run the closed inspect CLI against one explicit runs root.

    ``runs_root`` is injected only so the hermetic selftest can exercise the
    same validation, secure-open, and serialization path without touching the
    repository's real ``runs/`` tree.
    """
    try:
        if len(values) != 3 or values[0] != "inspect":
            _fail("JS_INVENTORY_COMMAND_INVALID")
        run_reference = _validate_run_reference(values[1])
        artifact_reference = _validate_artifact_reference(values[2])
        run_path = Path(runs_root) / Path(run_reference).name
        result = inventory(
            run_path, artifact_reference, runs_root=runs_root,
        )
    except JSInventoryError as exc:
        print(_serialized(_error_document(exc)))
        return 2
    print(_serialized(result))
    return 0


def _selftest() -> int:
    checks: list[tuple[str, bool]] = []
    with tempfile.TemporaryDirectory(prefix="xunji-js-inventory-") as raw:
        fixture = Path(raw)
        runs_root = fixture / "runs"
        run = runs_root / "fixture_20260101"
        evidence = run / "evidence"
        state = run / "state"
        evidence.mkdir(parents=True)
        state.mkdir()

        app = evidence / "app.js"
        app.write_text(
            "const nonce = Date.now();\n"
            "function makeSign(uid){ return md5(uid + nonce); }\n"
            "fetch('/api/admin/users?tenantId=1&token=raw-query-secret#raw-fragment-secret', "
            "{method: 'POST', body: JSON.stringify({uid: uid, sign: makeSign(uid)})});\n"
            "axios.get('/api/profile?userId=42');\n"
            "fetch('/reset/token/hunter2?ABCDEFGHIJKLMNOPQRSTUVWXYZabcdef=raw-value');\n"
            "fetch('/api/upload/%68%75%6e%74%65%72%32?"
            "%68%75%6e%74%65%72%32=raw-encoded-key-value');\n"
            "fetch('/api/double/%2568%2575%256e%2574%2565%2572%2532?"
            "%2568%2575%256e%2574%2565%2572%2532=raw-double-encoded-value');\n"
            "new WebSocket('wss://operator:raw-userinfo-secret@socket.example/"
            "session-0123456789abcdef0123456789abcdef?session=raw-ws-secret#raw-ws-fragment');\n",
            encoding="utf-8",
        )
        (state / "control.json").write_text(json.dumps({
            "url": "https://state.invalid/private?token=sibling-state-secret",
        }), encoding="utf-8")
        before_stat = app.stat()
        before_entries = sorted(
            item.relative_to(run).as_posix() for item in run.rglob("*")
        )
        data = inventory(
            run, "evidence/app.js", runs_root=runs_root,
        )
        encoded = _serialized(data)
        reparsed = json.loads(encoded)
        after_stat = app.stat()
        after_entries = sorted(
            item.relative_to(run).as_posix() for item in run.rglob("*")
        )
        routes = [item["route_pattern"] for item in data["candidates"]]
        low_entropy_secret = b"hunter2"
        secret_artifact = evidence / "note.txt"
        secret_artifact.write_bytes(low_entropy_secret)
        secret_encoded = _serialized(inventory(
            run, "evidence/note.txt", runs_root=runs_root,
        ))
        secret_digest = hashlib.sha256(low_entropy_secret).hexdigest()
        checks.extend([
            ("single saved artifact produces bounded structured candidates",
             reparsed["schema"] == SCHEMA
             and reparsed["artifact"]["type"] == ".js"
             and reparsed["artifact"]["id"] == "selected-evidence-artifact"
             and reparsed["run"] == "active_run"
             and reparsed["returned_candidates"] >= 3),
            ("fetch method and endpoint candidates remain useful",
             any(item["method"] == "POST" and "/api/admin/users" in item["route_pattern"]
                 for item in data["candidates"])
             and any("/api/profile" in route for route in routes)
             and any(route.startswith("wss://socket.example/") for route in routes)),
            ("query values, userinfo, fragments and high-entropy path secrets never render",
             all(secret not in encoded for secret in (
                 "raw-query-secret", "raw-fragment-secret", "operator",
                 "raw-userinfo-secret", "raw-ws-secret", "raw-ws-fragment",
                 "0123456789abcdef0123456789abcdef", "hunter2",
                 "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdef", "%68%75%6e%74%65%72%32",
                 "raw-encoded-key-value",
             ))
             and "tenantId=*" in encoded and "session=*" in encoded
             and "/api/upload/<segment:redacted>" in encoded
             and "<field:redacted>=*" in encoded),
            ("single and double percent-encoded path or query names never render",
             all(secret not in encoded for secret in (
                 "%68%75%6e%74%65%72%32",
                 "%2568%2575%256e%2574%2565%2572%2532",
                 "raw-encoded-key-value", "raw-double-encoded-value",
             ))
             and "/api/upload/<segment:redacted>" in encoded
             and "/api/double/<segment:redacted>" in encoded
             and encoded.count("<field:redacted>=*") >= 2),
            ("absolute local paths and sibling state content never render",
             str(fixture) not in encoded
             and "fixture_20260101" not in encoded
             and "evidence/app.js" not in encoded
             and "state.invalid" not in encoded
             and "sibling-state-secret" not in encoded),
            ("low-entropy artifact content and its enumerable digest never render",
             "hunter2" not in secret_encoded
             and secret_digest not in secret_encoded
             and "scanned_sha256" not in secret_encoded
             and "content_sha256" not in secret_encoded),
            ("output is pure bounded JSON without Markdown instructions",
             len((encoded + "\n").encode("utf-8")) <= MAX_OUTPUT_BYTES
             and "# JS Inventory" not in encoded
             and "Next action" not in encoded
             and data["trust"] == TRUST),
            ("inspection is read-only",
             before_entries == after_entries
             and artifact_view._identity(before_stat) == artifact_view._identity(after_stat)),
        ])

        outside = fixture / "outside.js"
        outside.write_text("fetch('/api/outside?token=outside-secret')", encoding="utf-8")
        if hasattr(outside, "symlink_to"):
            link = evidence / "link.js"
            link.symlink_to(outside)
            checks.append((
                "evidence symlink escape is rejected",
                _expect_error(
                    "JS_INVENTORY_ARTIFACT_REJECTED",
                    lambda: inventory(run, "evidence/link.js", runs_root=runs_root),
                ),
            ))
            nested = evidence / "nested"
            nested.mkdir()
            nested_app = nested / "inside.js"
            nested_app.write_text("fetch('/api/inside')", encoding="utf-8")
            linked_parent = evidence / "linked-parent"
            linked_parent.symlink_to(nested, target_is_directory=True)
            checks.append((
                "intermediate symlink is rejected",
                _expect_error(
                    "JS_INVENTORY_ARTIFACT_REJECTED",
                    lambda: inventory(
                        run, "evidence/linked-parent/inside.js", runs_root=runs_root,
                    ),
                ),
            ))

        large = evidence / "large.js"
        late_marker = "late-endpoint-secret"
        large.write_bytes(
            b"A" * MAX_SCAN_BYTES
            + f"fetch('/api/{late_marker}')".encode("utf-8")
        )
        large_data = inventory(run, "evidence/large.js", runs_root=runs_root)
        large_encoded = _serialized(large_data)
        checks.append((
            "large files read only the fixed prefix and disclose truncation",
            large_data["scanned_bytes"] == MAX_SCAN_BYTES
            and large_data["scan_truncated"] is True
            and late_marker not in large_encoded,
        ))

        many = evidence / "many.js"
        many.write_text("\n".join(
            f"fetch('/api/item-{index}?token=secret-value-{index}')"
            for index in range(MAX_CANDIDATES * 3)
        ), encoding="utf-8")
        many_data = inventory(run, "evidence/many.js", runs_root=runs_root)
        many_encoded = _serialized(many_data)
        checks.append((
            "candidate and serialized output limits are hard",
            len(many_data["candidates"]) <= MAX_CANDIDATES
            and many_data["candidates_truncated"] is True
            and len((many_encoded + "\n").encode("utf-8")) <= MAX_OUTPUT_BYTES
            and "secret-value-" not in many_encoded,
        ))

        with mock.patch("artifact_view._identity_unchanged", return_value=False):
            checks.append((
                "read-time artifact mutation fails closed",
                _expect_error(
                    "JS_INVENTORY_ARTIFACT_REJECTED",
                    lambda: inventory(run, "evidence/app.js", runs_root=runs_root),
                ),
            ))

        stdout = io.StringIO()
        with contextlib.redirect_stdout(stdout):
            cli_success_status = _run_inspect_cli(
                ["inspect", "runs/fixture_20260101", "evidence/app.js"],
                runs_root=runs_root,
            )
        cli_success = json.loads(stdout.getvalue())
        checks.append((
            "CLI success is one compact JSON document through the secure-open path",
            cli_success_status == 0
            and cli_success.get("schema") == SCHEMA
            and cli_success.get("operation") == "inspect"
            and str(fixture) not in stdout.getvalue(),
        ))

        stdout = io.StringIO()
        with contextlib.redirect_stdout(stdout):
            missing_status = _run_inspect_cli(
                ["inspect", "runs/fixture_20260101", "evidence/missing.js"],
                runs_root=runs_root,
            )
        missing_error = json.loads(stdout.getvalue())
        checks.append((
            "CLI missing artifact is a path-free JSON error without a traceback",
            missing_status == 2
            and missing_error.get("schema") == ERROR_SCHEMA
            and missing_error.get("error_code") == "JS_INVENTORY_ARTIFACT_REJECTED"
            and missing_error.get("cause_code")
            == "ARTIFACT_VIEW_ARTIFACT_UNAVAILABLE"
            and str(fixture) not in stdout.getvalue()
            and "Traceback" not in stdout.getvalue(),
        ))

        stdout = io.StringIO()
        with contextlib.redirect_stdout(stdout):
            missing_run_status = _run_inspect_cli(
                ["inspect", "runs/missing_20260101", "evidence/app.js"],
                runs_root=runs_root,
            )
        missing_run_error = json.loads(stdout.getvalue())
        checks.append((
            "CLI missing run is a path-free JSON error without a traceback",
            missing_run_status == 2
            and missing_run_error.get("schema") == ERROR_SCHEMA
            and missing_run_error.get("error_code")
            == "JS_INVENTORY_ARTIFACT_REJECTED"
            and missing_run_error.get("cause_code")
            == "ARTIFACT_VIEW_RUN_UNAVAILABLE"
            and str(fixture) not in stdout.getvalue()
            and "Traceback" not in stdout.getvalue(),
        ))

        stdout = io.StringIO()
        with contextlib.redirect_stdout(stdout):
            legacy_status = main([str(run)])
        legacy_error = json.loads(stdout.getvalue())
        checks.append((
            "legacy whole-run CLI is rejected with a JSON error",
            legacy_status == 2
            and legacy_error.get("error_code") == "JS_INVENTORY_COMMAND_INVALID"
            and str(run) not in stdout.getvalue(),
        ))
        checks.extend([
            ("CLI run reference must be repository-relative",
             _expect_error(
                 "JS_INVENTORY_RUN_REFERENCE_INVALID",
                 lambda: _validate_run_reference(str(run)),
             )),
            ("CLI artifact must be one evidence-relative supported file",
             _expect_error(
                 "JS_INVENTORY_ARTIFACT_REFERENCE_INVALID",
                 lambda: _validate_artifact_reference("state/control.json"),
             )
             and _expect_error(
                 "JS_INVENTORY_ARTIFACT_REFERENCE_INVALID",
                 lambda: _validate_artifact_reference("evidence/../state/control.json"),
             )
             and _expect_error(
                 "JS_INVENTORY_ARTIFACT_TYPE_UNSUPPORTED",
                 lambda: _validate_artifact_reference("evidence/raw.bin"),
             )
             and _expect_error(
                 "JS_INVENTORY_ARTIFACT_REFERENCE_INVALID",
                 lambda: _validate_artifact_reference(
                     "evidence/operator:pw@host#frag?token=secret.js"
                 ),
             )),
        ])

    bad = [name for name, ok in checks if not ok]
    for name, ok in checks:
        print(("ok   " if ok else "FAIL ") + name)
    print("js_inventory selftest " + (
        "passed" if not bad else f"FAILED ({len(bad)})"
    ))
    return 0 if not bad else 1


def main(argv: list[str] | None = None) -> int:
    values = list(sys.argv[1:] if argv is None else argv)
    if values == ["--selftest"]:
        return _selftest()
    return _run_inspect_cli(values, runs_root=artifact_view.RUNS_ROOT)


if __name__ == "__main__":
    raise SystemExit(main())
