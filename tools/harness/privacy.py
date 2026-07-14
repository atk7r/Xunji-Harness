#!/usr/bin/env python3
"""Target-facing privacy guard and evidence redaction helpers.

The live Claude driver may send arbitrary exploit *methods*, but it must not
identify the operator, this framework, a run, or an Agent in target-facing
bytes.  Proof writes use neutral, collision-resistant names.  Necessary
authentication data is allowed to the intended target, but evidence records
store redacted hashes rather than reusable secrets.

Pure stdlib.  Active request tools call :func:`validate_outbound_request`
immediately before network I/O; the PreToolUse hook calls
:func:`outbound_command_privacy_reason` for inspectable raw commands.
"""

from __future__ import annotations

import datetime as _datetime
import base64
import html
from email.header import decode_header
import getpass
import hashlib
import json
import os
import re
import secrets
import shlex
import socket
import tempfile
import unicodedata
from pathlib import Path
from urllib.parse import parse_qsl, unquote_plus, urlencode, urlsplit, urlunsplit

try:
    from .command_shape import (
        FIXTURE as COMMAND_SHAPE_FIXTURE,
        ROOT as PROJECT_ROOT,
        has_unquoted_shell_control,
        local_setup_metadata_invocation,
    )
except ImportError:  # direct ``python tools/harness/privacy.py`` selftest
    from command_shape import (  # type: ignore[no-redef]
        FIXTURE as COMMAND_SHAPE_FIXTURE,
        ROOT as PROJECT_ROOT,
        has_unquoted_shell_control,
        local_setup_metadata_invocation,
    )


class OutboundPrivacyError(ValueError):
    """Raised before I/O when target-facing bytes violate the privacy policy."""


NEUTRAL_PREFIXES = ("tmp", "diag", "proof")
NEUTRAL_MARKER_RE = re.compile(
    r"^(?:tmp|diag|proof)-\d{8}-[a-f0-9]{6,12}$", re.IGNORECASE
)
NEUTRAL_ARTIFACT_RE = re.compile(
    r"^(?:tmp|diag|proof)-\d{8}-[a-f0-9]{6,12}(?:\.[a-z0-9][a-z0-9._-]{0,31})?$",
    re.IGNORECASE,
)

_INTERNAL_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
    ("project identifier", re.compile(r"\bxunji(?:[_-][a-z0-9._-]+)?\b", re.IGNORECASE)),
    ("run directory identifier", re.compile(
        r"(?:^|[\\/])runs[\\/][a-z0-9._-]*_\d{8}(?:[_-][a-z0-9._-]+)?(?:[\\/]|$)",
        re.IGNORECASE,
    )),
    ("Claude internal path", re.compile(r"(?:^|[\\/])\.claude(?:[\\/]|$)", re.IGNORECASE)),
    ("Agent internal path", re.compile(r"(?:^|[\\/])\.agents(?:[\\/]|$)", re.IGNORECASE)),
    ("driver coordination marker", re.compile(
        r"\bXUNJI_(?:ASSIGNMENT|FRONT|ASSETS|REVIEW_RECEIPT|REVIEW_BUNDLE|COMPLETION_[A-Z_]+)\b",
        re.IGNORECASE,
    )),
)
_EMAIL_RE = re.compile(r"(?<![\w.+-])([\w.!#$%&'*+/=?^`{|}~-]+)@([a-z0-9.-]+\.[a-z]{2,})(?![\w.-])", re.IGNORECASE)
_CN_PHONE_RE = re.compile(r"(?<!\d)(?:\+?86[- ]?)?1[3-9]\d{9}(?!\d)")
_CN_ID_RE = re.compile(r"(?<!\d)\d{6}(?:19|20)\d{2}(?:0[1-9]|1[0-2])(?:0[1-9]|[12]\d|3[01])\d{3}[0-9Xx](?!\d)")
_RESERVED_EMAIL_DOMAINS = ("example.com", "example.net", "example.org", "example.invalid", "example.test")

AUTH_HEADER_NAMES = frozenset({
    "authorization", "proxy-authorization", "cookie", "x-api-key",
    "x-auth-token", "x-csrf-token", "x-xsrf-token",
})
_SENSITIVE_HEADER_NAMES = AUTH_HEADER_NAMES | frozenset({"set-cookie"})
_SENSITIVE_KEY_RE = re.compile(
    r"(?:pass(?:word|wd)?|secret|token|api[_-]?key|auth(?:orization)?|cookie|session|csrf|xsrf|"
    r"email|e-mail|phone|mobile|id[_-]?card|identity|real[_-]?name|full[_-]?name)",
    re.IGNORECASE,
)
_AUTH_BODY_SECRET_RE = re.compile(
    r"(?:^|[?&,{;\s])(?:pass(?:word|wd)?|secret)\s*[:=]",
    re.IGNORECASE,
)
_RAW_SECRET_VALUE_RE = re.compile(
    r"(?P<prefix>\b(?:pass(?:word|wd)?|secret|token|api[_-]?key|session|csrf|xsrf)\s*[:=]\s*)"
    r"(?P<value>\"[^\"]*\"|'[^']*'|[^&\s,;}]+)",
    re.IGNORECASE,
)
_REDACTION_RE = re.compile(r"<redacted:[a-z0-9_-]+:[a-f0-9]{12}>", re.IGNORECASE)
_LEGACY_ARTIFACT_RE = re.compile(
    r"\bxunji(?:_[a-z0-9]{2,24}){1,4}\.(?:txt|ini|conf|config|aspx|ashx|php|jsp|jspx|tmp|html|log)\b",
    re.IGNORECASE,
)
_DECODE_LIMIT_SENTINEL = "__outbound_privacy_nested_encoding_limit__"

_PAYLOAD_FLAGS = frozenset({
    "-d", "--data", "--data-raw", "--data-binary", "--data-urlencode", "--json",
    "-H", "--header", "-F", "--form", "--form-string", "--marker", "--filename", "--cmd",
    "-b", "--cookie", "-u", "--user", "--oauth2-bearer",
})
_AUTH_CLI_FLAGS = frozenset({"-b", "--cookie", "-u", "--user", "--oauth2-bearer"})
_NETWORK_TOOL_RE = re.compile(
    r"(?:^|[;&|\s/])(?:curl|wget|http|xh|websocat|wscat)(?:\s|$)|"
    r"tools/(?:probe|render|scan|exploit)\.py|tools/sensors/[a-z0-9_-]+\.py",
    re.IGNORECASE,
)
_CUSTOM_NETWORK_EXEC_RE = re.compile(
    r"(?:^|[;&|\s])(?:python(?:3(?:\.\d+)?)?|node|ruby|perl|php|bash|sh|zsh|pwsh|powershell|(?:\.{1,2}/|/)[^\s]+)(?:\s|$)",
    re.IGNORECASE,
)
_URL_TEXT_RE = re.compile(r"(?:https?|wss?|ftp)://[^\s\"'<>]+", re.IGNORECASE)
_AUTH_HEADER_BLOCK_RE = re.compile(
    r"(?im)(?P<prefix>^[ \t]*(?:authorization|proxy-authorization|cookie|set-cookie|"
    r"x-api-key|x-auth-token|x-csrf-token|x-xsrf-token)[ \t]*[:=][ \t]*)"
    r"(?P<value>[^\r\n]*(?:\r?\n[ \t]+[^\r\n]*)*)"
)
_URL_SECRET_KEY_RE = re.compile(
    r"^(?:key|access[_-]?key|credential|signature|sig)$", re.IGNORECASE
)
_NETWORK_SCRIPT_NAMES = frozenset({"probe.py", "render.py", "scan.py", "exploit.py"})
_NETWORK_CLI_NAMES = frozenset({"curl", "wget", "http", "xh", "websocat", "wscat"})
_ENV_ASSIGNMENT_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_]*=.*", re.DOTALL)
_PYTHON_NAME_RE = re.compile(r"python(?:3(?:\.\d+){0,2})?", re.IGNORECASE)


def _digest(value: str | bytes) -> str:
    raw = value if isinstance(value, bytes) else value.encode("utf-8", "replace")
    return hashlib.sha256(raw).hexdigest()[:12]


def _redaction(kind: str, value: str | bytes) -> str:
    return f"<redacted:{kind}:{_digest(value)}>"


def neutral_marker(prefix: str = "proof", *, date: str | None = None,
                   nonce: str | None = None) -> str:
    """Return a neutral unique marker suitable for target-side proof data."""
    prefix = prefix.lower()
    if prefix not in NEUTRAL_PREFIXES:
        raise ValueError(f"prefix must be one of {', '.join(NEUTRAL_PREFIXES)}")
    date = date or _datetime.datetime.now(_datetime.timezone.utc).strftime("%Y%m%d")
    nonce = (nonce or secrets.token_hex(4)).lower()
    marker = f"{prefix}-{date}-{nonce}"
    if not NEUTRAL_MARKER_RE.fullmatch(marker):
        raise ValueError("neutral marker requires YYYYMMDD and 6-12 lowercase hex characters")
    return marker


def neutral_artifact_name(prefix: str = "proof", suffix: str = ".txt", **kwargs) -> str:
    """Return a neutral unique target-side artifact basename."""
    suffix = suffix or ""
    if suffix and not suffix.startswith("."):
        suffix = "." + suffix
    name = neutral_marker(prefix, **kwargs) + suffix.lower()
    validate_neutral_artifact_name(name)
    return name


def validate_neutral_marker(value: str) -> None:
    if not NEUTRAL_MARKER_RE.fullmatch(str(value or "")):
        raise OutboundPrivacyError(
            "target proof content must use tmp/diag/proof-YYYYMMDD-<6-12hex>"
        )


def validate_neutral_artifact_name(value: str) -> None:
    """Validate the transmitted basename, allowing traversal prefixes for PoCs."""
    normalized = str(value or "").replace("\\", "/").rstrip("/")
    basename = normalized.rsplit("/", 1)[-1]
    if not NEUTRAL_ARTIFACT_RE.fullmatch(basename):
        raise OutboundPrivacyError(
            "target artifact basename must use tmp/diag/proof-YYYYMMDD-<6-12hex>[.<safe-ext>]"
        )


def _configured_sensitive_values() -> list[str]:
    raw = os.environ.get("OUTBOUND_PRIVACY_DENY_VALUES", "")
    return [v.strip() for v in raw.splitlines() if len(v.strip()) >= 3]


def _local_home_values() -> list[str]:
    values = [str(Path.home()), str(os.environ.get("USERPROFILE", ""))]
    return list(dict.fromkeys(
        value.rstrip("/\\") for value in values
        if value and value not in {"/", ".", "\\"}
    ))


def _local_identity_values() -> list[str]:
    values: list[str] = _local_home_values()
    for value in (getpass.getuser(), os.environ.get("USER", ""), os.environ.get("LOGNAME", ""), socket.gethostname()):
        value = str(value or "").strip()
        if len(value) >= 3 and value.lower() not in {"root", "user", "admin", "localhost"}:
            values.append(value)
    return list(dict.fromkeys(values))


def _decoded_variants(value: str) -> list[str]:
    """Bounded common-decoding pass so percent/base64/hex is not a bypass."""
    variants = [value]
    normalized = unicodedata.normalize("NFKC", value)
    if normalized != value:
        variants.append(normalized)
    no_zero_width = re.sub(r"[\u200b-\u200f\u2060\ufeff]", "", normalized)
    if no_zero_width != normalized:
        variants.append(no_zero_width)
    entity_decoded = html.unescape(value)
    if entity_decoded != value:
        variants.append(entity_decoded)
    if re.search(r"\\(?:x[0-9a-fA-F]{2}|u[0-9a-fA-F]{4}|[0-7]{1,3})", value):
        try:
            escaped = value.encode("utf-8").decode("unicode_escape")
            if escaped != value:
                variants.append(escaped)
        except (UnicodeDecodeError, ValueError):
            pass
    if "=?" in value and "?=" in value:
        try:
            mime = "".join(
                part.decode(charset or "utf-8", "replace") if isinstance(part, bytes) else part
                for part, charset in decode_header(value)
            )
            if mime != value:
                variants.append(mime)
        except Exception:
            pass
    current = value
    for _ in range(8):
        decoded = unquote_plus(current)
        if decoded == current:
            break
        variants.append(decoded)
        current = decoded
    else:
        if unquote_plus(current) != current:
            variants.append(_DECODE_LIMIT_SENTINEL)
    stripped = value.strip()
    if stripped.startswith(("{", "[", '"')):
        try:
            variants.append(json.dumps(json.loads(stripped), ensure_ascii=False))
        except (json.JSONDecodeError, TypeError):
            pass
    tokens = re.findall(r"(?<![A-Za-z0-9+/_-])[A-Za-z0-9+/_-]{6,}={0,2}(?![A-Za-z0-9+/_-])", value)
    for token in tokens:
        try:
            raw = base64.b64decode(token, validate=True)
            decoded = raw.decode("utf-8")
            if decoded and sum(ch.isprintable() for ch in decoded) / len(decoded) >= 0.8:
                variants.append(decoded)
        except Exception:
            try:
                padded = token + "=" * (-len(token) % 4)
                raw = base64.urlsafe_b64decode(padded)
                decoded = raw.decode("utf-8")
                if decoded and sum(ch.isprintable() for ch in decoded) / len(decoded) >= 0.8:
                    variants.append(decoded)
            except Exception:
                pass
    for token in re.findall(r"(?<![0-9a-fA-F])[0-9a-fA-F]{8,}(?![0-9a-fA-F])", value):
        if len(token) % 2:
            continue
        try:
            decoded = bytes.fromhex(token).decode("utf-8")
            if decoded and sum(ch.isprintable() for ch in decoded) / len(decoded) >= 0.8:
                variants.append(decoded)
        except Exception:
            pass
    return list(dict.fromkeys(variants))


def privacy_reason(text: str | bytes | None, *, allow_generic_pii: bool = False) -> str:
    """Return a category-only reason; never echo the sensitive matched value."""
    if text is None:
        return ""
    value = text.decode("utf-8", "ignore") if isinstance(text, bytes) else str(text)
    if not value:
        return ""
    for candidate in _decoded_variants(value):
        if candidate == _DECODE_LIMIT_SENTINEL:
            return "nested encoding exceeds privacy inspection limit"
        for label, pattern in _INTERNAL_PATTERNS:
            if pattern.search(candidate):
                return label
        for home in _local_home_values():
            if home.casefold() in candidate.casefold():
                return "local user path"
        for item in _local_identity_values() + _configured_sensitive_values():
            if (item.casefold() in candidate.casefold() if "/" in item or "\\" in item
                    else re.search(rf"(?<![a-z0-9]){re.escape(item)}(?![a-z0-9])", candidate, re.IGNORECASE)):
                return "configured or local identity value"
        if allow_generic_pii:
            continue
        for match in _EMAIL_RE.finditer(candidate):
            domain = match.group(2).lower().rstrip(".")
            if not any(domain == d or domain.endswith("." + d) for d in _RESERVED_EMAIL_DOMAINS):
                return "email address"
        if _CN_PHONE_RE.search(candidate):
            return "phone number"
        if _CN_ID_RE.search(candidate):
            return "identity-card-shaped value"
    return ""


def _raise_if_private(value: str | bytes | None, location: str, *, allow_generic_pii: bool = False) -> None:
    reason = privacy_reason(value, allow_generic_pii=allow_generic_pii)
    if reason:
        raise OutboundPrivacyError(f"outbound privacy blocked {location}: {reason}")


def validate_outbound_request(method: str, url: str, headers: dict | None,
                              body: bytes | str | None, *,
                              allow_sensitive_auth: bool = False,
                              allow_legacy_cleanup: bool = False) -> None:
    """Fail before network I/O when generated request fields leak identity/PII.

    The destination host itself is operator-supplied scope and is not treated as
    a generated marker.  Path/query, non-auth headers, and request bodies are.
    Opaque authentication headers are allowed to the intended target, but are
    still checked for internal project/local identity markers.  A body carrying
    necessary login PII requires the explicit ``allow_sensitive_auth`` flag.
    """
    legacy_cleanup = allow_legacy_cleanup and method.upper() in {"POST", "PUT", "PATCH", "DELETE"}
    def without_legacy(value):
        if not legacy_cleanup or value is None:
            return value
        if isinstance(value, bytes):
            return _LEGACY_ARTIFACT_RE.sub("legacy-proof.txt", value.decode("utf-8", "ignore"))
        return _LEGACY_ARTIFACT_RE.sub("legacy-proof.txt", str(value))

    parsed = urlsplit(str(url or ""))
    if parsed.username is not None:
        if parsed.password is not None and not allow_sensitive_auth:
            raise OutboundPrivacyError(
                "outbound privacy blocked URL userinfo: authentication secret "
                "requires explicit auth exception"
            )
        _raise_if_private(parsed.username, "URL userinfo username",
                          allow_generic_pii=allow_sensitive_auth)
        if parsed.password is not None:
            _raise_if_private(parsed.password, "URL userinfo password",
                              allow_generic_pii=True)
    _raise_if_private(without_legacy(parsed.path), "URL path", allow_generic_pii=allow_sensitive_auth)
    for key, value in parse_qsl(parsed.query, keep_blank_values=True):
        _raise_if_private(key, "query key", allow_generic_pii=True)
        _raise_if_private(value, "query value", allow_generic_pii=allow_sensitive_auth)
    for key, value in (headers or {}).items():
        name = str(key)
        _raise_if_private(name, "header name", allow_generic_pii=True)
        auth_header = (name.lower().strip() in AUTH_HEADER_NAMES
                       or bool(_SENSITIVE_KEY_RE.search(name)))
        _raise_if_private(value, f"header {name}",
                          allow_generic_pii=auth_header or allow_sensitive_auth)
    body_text = (body.decode("utf-8", "ignore") if isinstance(body, bytes)
                 else str(body or ""))
    for head, _sep, _payload in _multipart_parts(body_text, headers or {}):
        filename = _multipart_filename(head)
        if not filename:
            continue
        validate_neutral_artifact_name(filename)
        _raise_if_private(filename, "multipart filename")
    multipart_secret = _multipart_has_auth_secret(body_text, headers or {})
    if (body_text and (_AUTH_BODY_SECRET_RE.search(unquote_plus(body_text)) or multipart_secret)
            and not allow_sensitive_auth):
        raise OutboundPrivacyError(
            "outbound privacy blocked request body: authentication secret field requires explicit auth exception"
        )
    _raise_if_private(without_legacy(body), "request body", allow_generic_pii=allow_sensitive_auth)


def _redact_text(value: str, *, kind: str = "pii") -> tuple[str, bool]:
    changed = False
    out = value
    for _label, pattern in _INTERNAL_PATTERNS:
        out, n = pattern.subn(lambda m: _redaction("internal", m.group(0)), out)
        changed = changed or bool(n)
    for home in _local_home_values():
        out, n = re.subn(re.escape(home), lambda m: _redaction("local_path", m.group(0)),
                         out, flags=re.IGNORECASE)
        changed = changed or bool(n)
    for item in _local_identity_values() + _configured_sensitive_values():
        if "/" in item or "\\" in item:
            pattern = re.compile(re.escape(item), re.IGNORECASE)
        else:
            pattern = re.compile(rf"(?<![a-z0-9]){re.escape(item)}(?![a-z0-9])", re.IGNORECASE)
        out, n = pattern.subn(lambda m: _redaction("identity", m.group(0)), out)
        changed = changed or bool(n)

    def email_repl(match: re.Match[str]) -> str:
        nonlocal changed
        domain = match.group(2).lower().rstrip(".")
        if any(domain == d or domain.endswith("." + d) for d in _RESERVED_EMAIL_DOMAINS):
            return match.group(0)
        changed = True
        return _redaction("email", match.group(0))

    out = _EMAIL_RE.sub(email_repl, out)
    out, n = _CN_PHONE_RE.subn(lambda m: _redaction("phone", m.group(0)), out)
    changed = changed or bool(n)
    out, n = _CN_ID_RE.subn(lambda m: _redaction("identity", m.group(0)), out)
    changed = changed or bool(n)
    # If a bounded decode exposed a sensitive value that was not visible in the
    # raw representation, redact the whole encoded field rather than preserve a
    # reusable encoding of private data.
    if not changed and privacy_reason(value):
        return _redaction(kind, value), True
    return out, changed


def redact_headers(headers: dict | None) -> tuple[dict, list[str]]:
    out: dict = {}
    redactions: list[str] = []
    for key, value in (headers or {}).items():
        name = str(key)
        lowered = name.lower().strip()
        if lowered in _SENSITIVE_HEADER_NAMES or _SENSITIVE_KEY_RE.search(name):
            out[name] = _redaction("header", str(value))
            redactions.append(f"header:{name.lower()}")
        elif lowered in {"location", "content-location"}:
            safe, url_redactions = redact_url(str(value))
            out[name] = safe
            if url_redactions:
                redactions.append(f"header:{name.lower()}")
        else:
            safe, changed = _redact_text(str(value))
            out[name] = safe
            if changed:
                redactions.append(f"header:{name.lower()}")
    return out, redactions


def _redact_json(value, path: str, redactions: list[str]):
    if isinstance(value, dict):
        out = {}
        for key, item in value.items():
            child = f"{path}.{key}"
            if _SENSITIVE_KEY_RE.search(str(key)):
                raw = json.dumps(item, ensure_ascii=False, sort_keys=True) if not isinstance(item, str) else item
                out[key] = _redaction("field", raw)
                redactions.append(child)
            else:
                out[key] = _redact_json(item, child, redactions)
        return out
    if isinstance(value, list):
        return [_redact_json(item, f"{path}[{idx}]", redactions) for idx, item in enumerate(value)]
    if isinstance(value, str):
        safe, changed = _redact_text(value)
        if changed:
            redactions.append(path)
        return safe
    return value


def _content_type(headers: dict | None) -> str:
    for key, value in (headers or {}).items():
        if str(key).lower() == "content-type":
            return str(value)
    return ""


def _multipart_boundary(headers: dict | None) -> str:
    ctype = _content_type(headers)
    if "multipart/form-data" not in ctype.lower():
        return ""
    match = re.search(r"boundary\s*=\s*(?:\"([^\"]+)\"|([^;\s]+))", ctype, re.IGNORECASE)
    return (match.group(1) or match.group(2)) if match else ""


def _multipart_parts(text: str, headers: dict | None) -> list[tuple[str, str, str]]:
    boundary = _multipart_boundary(headers)
    if not boundary:
        return []
    out: list[tuple[str, str, str]] = []
    for raw_part in text.split("--" + boundary):
        if "\r\n\r\n" in raw_part:
            head, payload = raw_part.split("\r\n\r\n", 1)
            sep = "\r\n\r\n"
        elif "\n\n" in raw_part:
            head, payload = raw_part.split("\n\n", 1)
            sep = "\n\n"
        else:
            continue
        out.append((head, sep, payload))
    return out


def _multipart_field_name(head: str) -> str:
    match = re.search(r"\bname\s*=\s*(?:\"([^\"]*)\"|([^;\s]+))", head, re.IGNORECASE)
    return (match.group(1) or match.group(2) or "") if match else ""


def _multipart_filename(head: str) -> str:
    match = re.search(r"\bfilename\s*=\s*(?:\"([^\"]*)\"|([^;\s]+))", head, re.IGNORECASE)
    return (match.group(1) or match.group(2) or "") if match else ""


def _redact_multipart_head(head: str, redactions: list[str], field: str) -> str:
    """Sanitize part headers, always hashing the transmitted filename value."""
    def filename_repl(match: re.Match[str]) -> str:
        raw = match.group(1) if match.group(1) is not None else match.group(2)
        quote = '"' if match.group(1) is not None else ""
        redactions.append(f"body.{field or 'multipart'}.filename")
        return f"filename={quote}{_redaction('filename', raw)}{quote}"

    safe = re.sub(
        r"\bfilename\s*=\s*(?:\"([^\"]*)\"|([^;\s]+))",
        filename_repl,
        head,
        flags=re.IGNORECASE,
    )
    safe, changed = _redact_text(safe)
    if changed:
        redactions.append(f"body.{field or 'multipart'}.headers")
    return safe


def _multipart_has_auth_secret(text: str, headers: dict | None) -> bool:
    return any(
        bool(_AUTH_BODY_SECRET_RE.search(f" { _multipart_field_name(head) }="))
        for head, _sep, _payload in _multipart_parts(text, headers)
    )


def _redact_multipart(text: str, headers: dict | None) -> tuple[str, list[str]]:
    boundary = _multipart_boundary(headers)
    if not boundary:
        return text, []
    redactions: list[str] = []
    rendered: list[str] = []
    safe_boundary, boundary_changed = _redact_text(boundary)
    if boundary_changed:
        redactions.append("body.multipart.boundary")
    delimiter = "--" + boundary
    safe_delimiter = "--" + safe_boundary
    for raw_part in text.split(delimiter):
        if "\r\n\r\n" in raw_part:
            head, payload = raw_part.split("\r\n\r\n", 1)
            sep = "\r\n\r\n"
        elif "\n\n" in raw_part:
            head, payload = raw_part.split("\n\n", 1)
            sep = "\n\n"
        else:
            rendered.append(raw_part)
            continue
        field = _multipart_field_name(head)
        trailing = "\r\n" if payload.endswith("\r\n") else ("\n" if payload.endswith("\n") else "")
        content = payload[:-len(trailing)] if trailing else payload
        if field and _SENSITIVE_KEY_RE.search(field):
            content = _redaction("field", content)
            redactions.append(f"body.{field}")
        else:
            content, secret_count = _RAW_SECRET_VALUE_RE.subn(
                lambda m: m.group("prefix") + _redaction("field", m.group("value")),
                content,
            )
            if secret_count:
                redactions.append(f"body.{field or 'multipart'}.secret-field")
            safe, changed = _redact_text(content)
            content = safe
            if changed:
                redactions.append(f"body.{field or 'multipart'}")
        safe_head = _redact_multipart_head(head, redactions, field)
        rendered.append(safe_head + sep + content + trailing)
    return safe_delimiter.join(rendered), redactions


def redact_body(body: bytes | str | None, headers: dict | None = None) -> tuple[str | None, list[str]]:
    if body is None:
        return None, []
    text = body.decode("utf-8", "replace") if isinstance(body, bytes) else str(body)
    redactions: list[str] = []
    ctype = _content_type(headers).lower()
    if "multipart/form-data" in ctype:
        return _redact_multipart(text, headers)
    if "json" in ctype or text.lstrip().startswith(("{", "[")):
        try:
            parsed = json.loads(text)
            safe = _redact_json(parsed, "body", redactions)
            return json.dumps(safe, ensure_ascii=False, separators=(",", ":")), redactions
        except (json.JSONDecodeError, TypeError):
            pass
    if "application/x-www-form-urlencoded" in ctype:
        pairs = []
        for key, value in parse_qsl(text, keep_blank_values=True):
            if _SENSITIVE_KEY_RE.search(key):
                pairs.append((key, _redaction("field", value)))
                redactions.append(f"body.{key}")
            else:
                safe, changed = _redact_text(value)
                pairs.append((key, safe))
                if changed:
                    redactions.append(f"body.{key}")
        return urlencode(pairs), redactions
    def raw_secret_repl(match: re.Match[str]) -> str:
        redactions.append("body.secret-field")
        return match.group("prefix") + _redaction("field", match.group("value"))
    text = _RAW_SECRET_VALUE_RE.sub(raw_secret_repl, text)
    safe, changed = _redact_text(text)
    if changed:
        redactions.append("body")
    return safe, redactions


def redact_url(url: str) -> tuple[str, list[str]]:
    parsed = urlsplit(str(url or ""))
    redactions: list[str] = []
    netloc = parsed.netloc
    if parsed.username is not None:
        userinfo, separator, hostport = parsed.netloc.rpartition("@")
        if separator:
            netloc = _redaction("url_auth", userinfo) + "@" + hostport
            redactions.append("url.userinfo")
    path, changed = _redact_text(parsed.path)
    if changed:
        redactions.append("url.path")
    pairs = []
    for key, value in parse_qsl(parsed.query, keep_blank_values=True):
        if _SENSITIVE_KEY_RE.search(key) or _URL_SECRET_KEY_RE.search(key):
            pairs.append((key, _redaction("query", value)))
            redactions.append(f"url.query.{key}")
        else:
            safe, changed = _redact_text(value)
            pairs.append((key, safe))
            if changed:
                redactions.append(f"url.query.{key}")
    fragment_headers = ({"Content-Type": "application/x-www-form-urlencoded"}
                        if "=" in parsed.fragment else None)
    fragment, fragment_redactions = redact_body(parsed.fragment, fragment_headers)
    fragment = fragment or ""
    if fragment_redactions:
        redactions.append("url.fragment")
    return urlunsplit((parsed.scheme, netloc, path, urlencode(pairs), fragment)), redactions


def sanitize_response_record(status: int, headers: dict | None,
                             body_preview: bytes | str | None) -> tuple[dict, list[str]]:
    """Redact replay-safe response headers and a bounded response preview."""
    safe_headers, header_redactions = redact_headers(headers)
    safe_body, body_redactions = redact_body(body_preview, headers)
    redactions = [f"response.{item}" for item in header_redactions + body_redactions]
    return {
        "status": status,
        "headers": safe_headers,
        "body_preview": safe_body,
    }, sorted(set(redactions))


def sanitize_request_record(method: str, url: str, headers: dict | None,
                            body: bytes | str | None, *,
                            auth_exception: bool = False) -> tuple[dict, dict]:
    safe_url, url_redactions = redact_url(url)
    safe_headers, header_redactions = redact_headers(headers)
    safe_body, body_redactions = redact_body(body, headers)
    redactions = sorted(set(url_redactions + header_redactions + body_redactions))
    request = {"method": method.upper(), "url": safe_url,
               "headers": safe_headers, "body": safe_body}
    privacy = {
        "schema": "outbound-privacy.v1",
        "redacted_fields": redactions,
        "replayable": not redactions,
        "auth_exception": bool(auth_exception),
    }
    return request, privacy


def contains_redaction(value) -> bool:
    if isinstance(value, dict):
        return any(contains_redaction(k) or contains_redaction(v) for k, v in value.items())
    if isinstance(value, list):
        return any(contains_redaction(v) for v in value)
    return bool(_REDACTION_RE.search(str(value)))


def sanitize_model_egress_text(value: str) -> str:
    """Hard-redact model/log egress; caller consent cannot disable this pass."""
    text = str(value or "")

    def redact_url_match(match: re.Match[str]) -> str:
        raw = match.group(0)
        # Keep common sentence punctuation outside the URL replacement.
        trimmed = raw.rstrip(".,);]}")
        suffix = raw[len(trimmed):]
        try:
            safe, _ = redact_url(trimmed)
            return safe + suffix
        except ValueError:
            return _redaction("url", trimmed) + suffix

    text = _URL_TEXT_RE.sub(redact_url_match, text)
    text = _AUTH_HEADER_BLOCK_RE.sub(
        lambda m: m.group("prefix") + _redaction("header", m.group("value")), text
    )
    text = _RAW_SECRET_VALUE_RE.sub(
        lambda m: m.group("prefix") + _redaction("field", m.group("value")), text
    )
    safe, _ = _redact_text(text)
    return safe


def sanitize_text_for_log(value: str) -> str:
    return sanitize_model_egress_text(value)


def _read_payload_file(token: str) -> tuple[str | bytes | None, str]:
    raw = token[1:] if token.startswith("@") else token
    raw = raw.split(";", 1)[0]
    path = Path(raw)
    if not path.is_file():
        return None, "file-backed payload cannot be inspected before execution"
    try:
        return path.read_bytes(), ""
    except OSError:
        return None, "file-backed payload cannot be inspected before execution"


def outbound_command_privacy_reason(command: str, *,
                                    allow_legacy_cleanup: bool = False) -> str:
    """Inspect target-facing CLI fields without treating local control args as egress."""
    if allow_legacy_cleanup:
        command = _LEGACY_ARTIFACT_RE.sub("legacy-proof.txt", command)
    if not re.search(r"(?:https?|wss?|ftp)://", command, re.IGNORECASE):
        return ""
    if has_unquoted_shell_control(command, reject_comments=False):
        return "URL-bearing command contains shell control, expansion, comment, or redirection and cannot be inspected as one exact argv"
    if local_setup_metadata_invocation(command, root=PROJECT_ROOT) is not None:
        return ""
    try:
        tokens = shlex.split(command, comments=False, posix=True)
    except ValueError:
        return "target command cannot be parsed for outbound privacy"
    executable_index = 0
    while (executable_index < len(tokens)
           and _ENV_ASSIGNMENT_RE.fullmatch(tokens[executable_index])):
        executable_index += 1
    executable = Path(tokens[executable_index]).name.lower() \
        if executable_index < len(tokens) else ""
    network_marker = bool(_NETWORK_TOOL_RE.search(command))
    known_network_tool = network_marker and executable in _NETWORK_CLI_NAMES
    if _PYTHON_NAME_RE.fullmatch(executable) and executable_index + 1 < len(tokens):
        raw_script = Path(tokens[executable_index + 1])
        script = raw_script if raw_script.is_absolute() else PROJECT_ROOT / raw_script
        try:
            script = script.resolve()
            sensors = (PROJECT_ROOT / "tools" / "sensors").resolve()
            known_network_tool = network_marker and ((
                script.parent == (PROJECT_ROOT / "tools").resolve()
                and script.name in _NETWORK_SCRIPT_NAMES
            ) or (
                script.parent == sensors
                and bool(re.fullmatch(r"[a-z0-9_-]+\.py", script.name, re.IGNORECASE))
            ))
        except OSError:
            known_network_tool = False
    if not known_network_tool and _CUSTOM_NETWORK_EXEC_RE.search(command):
        return "custom target-facing scripts are not an enforceable egress boundary; use guarded probe/render/scan/sensors or author-and-handoff"
    guarded_auth_exception = (
        any(("tools/probe.py" in token or "tools/render.py" in token) for token in tokens)
        and "--allow-sensitive-auth" in tokens
    )
    raw_curl = any(Path(token).name == "curl" for token in tokens)
    follows_redirects = any(token in {"-L", "--location", "--location-trusted"} for token in tokens)
    has_raw_auth = any(token in _AUTH_CLI_FLAGS for token in tokens)
    for idx, token in enumerate(tokens[:-1]):
        if token in {"-H", "--header"} and ":" in tokens[idx + 1]:
            if tokens[idx + 1].split(":", 1)[0].strip().lower() in AUTH_HEADER_NAMES:
                has_raw_auth = True
    if raw_curl and follows_redirects and has_raw_auth:
        return "raw redirect-following command may forward authentication across origins; use guarded probe/render"
    for token in tokens:
        if re.match(r"(?:https?|wss?|ftp)://", token, re.IGNORECASE):
            try:
                parsed = urlsplit(token)
                if parsed.username is not None:
                    return "URL userinfo requires a guarded explicit authentication path"
                reason = privacy_reason(parsed.path, allow_generic_pii=guarded_auth_exception)
                if reason:
                    return f"URL path contains {reason}"
                for key, value in parse_qsl(parsed.query, keep_blank_values=True):
                    if (_SENSITIVE_KEY_RE.search(key) or _URL_SECRET_KEY_RE.search(key)) \
                            and not guarded_auth_exception:
                        return "query contains an authentication or sensitive field that requires guarded explicit auth exception"
                    reason = privacy_reason(value, allow_generic_pii=guarded_auth_exception)
                    if reason:
                        return f"query value contains {reason}"
            except ValueError:
                return "target URL cannot be inspected for outbound privacy"
    idx = 0
    while idx < len(tokens):
        token = tokens[idx]
        flag = token
        value: str | None = None
        if token in _PAYLOAD_FLAGS and idx + 1 < len(tokens):
            value = tokens[idx + 1]
            idx += 2
        else:
            for candidate in _PAYLOAD_FLAGS:
                prefix = candidate + "="
                if token.startswith(prefix):
                    flag = candidate
                    value = token[len(prefix):]
                    break
            idx += 1
        if value is None:
            continue
        allow_pii = guarded_auth_exception or flag in _AUTH_CLI_FLAGS
        secret_candidate: str | bytes = value
        if flag in {"-H", "--header"} and ":" in value:
            header_name, header_value = value.split(":", 1)
            allow_pii = allow_pii or header_name.strip().lower() in AUTH_HEADER_NAMES
            value = header_value
        if flag in {"-F", "--form"} and "=@" in value:
            file_token = "@" + value.split("=@", 1)[1]
            form_parts = file_token[1:].split(";")
            transmitted_name = Path(form_parts[0]).name
            for part in form_parts[1:]:
                if part.lower().startswith("filename="):
                    transmitted_name = part.split("=", 1)[1].strip('"\'')
            try:
                validate_neutral_artifact_name(transmitted_name)
            except OutboundPrivacyError:
                return "multipart filename is not a neutral unique proof artifact name"
            reason = privacy_reason(transmitted_name, allow_generic_pii=False)
            if reason:
                return f"multipart filename contains {reason}"
            payload, error = _read_payload_file(file_token)
            if error:
                return error
            reason = privacy_reason(payload, allow_generic_pii=allow_pii)
            secret_candidate = payload or b""
        elif value.startswith("@") and flag in {"-d", "--data", "--data-raw", "--data-binary", "--data-urlencode"}:
            payload, error = _read_payload_file(value)
            if error:
                return error
            reason = privacy_reason(payload, allow_generic_pii=allow_pii)
            secret_candidate = payload or b""
        elif flag == "--data-urlencode" and "@" in value and "=" not in value:
            return "--data-urlencode file-backed field is not inspectable as target bytes; use guarded probe"
        else:
            reason = privacy_reason(value, allow_generic_pii=allow_pii)
        secret_text = (secret_candidate.decode("utf-8", "ignore")
                       if isinstance(secret_candidate, bytes) else secret_candidate)
        if (flag in {"-d", "--data", "--data-raw", "--data-binary", "--data-urlencode", "--json",
                     "-F", "--form", "--form-string"}
                and _AUTH_BODY_SECRET_RE.search(unquote_plus(secret_text))
                and not guarded_auth_exception):
            return f"{flag} authentication secret field requires guarded explicit auth exception"
        if reason:
            return f"{flag} payload contains {reason}"
    return ""


def selftest() -> int:
    checks: list[tuple[str, bool]] = []
    marker = neutral_marker("proof", date="20260713", nonce="a1b2c3d4")
    shape_cases = json.loads(COMMAND_SHAPE_FIXTURE.read_text(encoding="utf-8"))["cases"]
    for case in shape_cases:
        if "privacy" not in case:
            continue
        command = str(case["command"]).replace("{ROOT}", str(PROJECT_ROOT))
        reason = outbound_command_privacy_reason(command)
        checks.append((
            f"privacy-command-shape fixture: {case['name']}",
            (reason == "") if case["privacy"] == "allow" else bool(reason),
        ))
    artifact = neutral_artifact_name("proof", ".txt", date="20260713", nonce="a1b2c3d4")
    checks.extend([
        ("neutral marker", marker == "proof-20260713-a1b2c3d4"),
        ("neutral artifact", artifact == "proof-20260713-a1b2c3d4.txt"),
        ("reserved example email allowed", privacy_reason("test@example.com") == ""),
        ("real email blocked", privacy_reason("person@real.example.cn") == "email address"),
        ("phone blocked", privacy_reason("13800138000") == "phone number"),
        ("project marker blocked", privacy_reason("XUNJI-PROOF-abc") == "project identifier"),
        ("percent-encoded project marker blocked", privacy_reason("x%75nji-proof") == "project identifier"),
        ("triple-percent-encoded project marker blocked",
         privacy_reason("%252578unji-proof") == "project identifier"),
        ("base64 project marker blocked", privacy_reason("eHVuamk=") == "project identifier"),
        ("URL-safe/unpadded base64 project marker blocked", privacy_reason("eHVuamk") == "project identifier"),
        ("URL-safe underscore base64 project marker blocked", privacy_reason("eHVuamk_") == "project identifier"),
        ("base64 marker after 32 benign tokens blocked",
         privacy_reason(" ".join(["QUFBQUFB"] * 33 + ["eHVuamk="])) == "project identifier"),
        ("hex project marker blocked", privacy_reason("78756e6a69") == "project identifier"),
        ("case-insensitive project marker blocked", privacy_reason("XuNjI-proof") == "project identifier"),
        ("NFKC project marker blocked", privacy_reason("ｘｕｎｊｉ-proof") == "project identifier"),
        ("zero-width project marker blocked", privacy_reason("x\u200bunji-proof") == "project identifier"),
        ("HTML-entity project marker blocked", privacy_reason("&#120;unji-proof") == "project identifier"),
        ("escaped-hex project marker blocked", privacy_reason(r"\x78unji-proof") == "project identifier"),
        ("escaped-octal project marker blocked", privacy_reason(r"\170unji-proof") == "project identifier"),
        ("MIME project marker blocked", privacy_reason("=?utf-8?B?eHVuamk=?=") == "project identifier"),
        ("actual local home path blocked",
         privacy_reason(str(Path.home() / "proof.txt")) == "local user path"),
        ("target-native /Users route not false-blocked",
         privacy_reason("/Users/settings") == ""),
        ("target-native /home route not false-blocked",
         privacy_reason("/home/dashboard") == ""),
        ("target-native /runs route not false-blocked",
         privacy_reason("/runs/list") == ""),
        ("dated framework run identifier blocked",
         privacy_reason("/runs/sample_20260713/evidence") == "run directory identifier"),
    ])
    old_deny_values = os.environ.get("OUTBOUND_PRIVACY_DENY_VALUES")
    try:
        os.environ["OUTBOUND_PRIVACY_DENY_VALUES"] = "Acme Operator"
        try:
            validate_outbound_request("GET", "https://acme-operator.example.test/", {}, None)
            checks.append(("configured identity does not block destination host", True))
        except OutboundPrivacyError:
            checks.append(("configured identity does not block destination host", False))
        try:
            validate_outbound_request("POST", "https://target.test/", {}, "owner=Acme Operator")
            checks.append(("configured identity blocks generated body", False))
        except OutboundPrivacyError:
            checks.append(("configured identity blocks generated body", True))
    finally:
        if old_deny_values is None:
            os.environ.pop("OUTBOUND_PRIVACY_DENY_VALUES", None)
        else:
            os.environ["OUTBOUND_PRIVACY_DENY_VALUES"] = old_deny_values
    try:
        validate_outbound_request("POST", "https://target.test/upload", {}, b"proof-20260713-a1b2c3d4")
        checks.append(("neutral request allowed", True))
    except OutboundPrivacyError:
        checks.append(("neutral request allowed", False))
    for label, body in (("project request denied", b"marker=xunji-proof"),
                        ("PII request denied", b"mobile=13800138000"),
                        ("auth secret request denied without exception", b"password=hunter2")):
        try:
            validate_outbound_request("POST", "https://target.test/api", {}, body)
            checks.append((label, False))
        except OutboundPrivacyError:
            checks.append((label, True))
    try:
        validate_outbound_request("POST", "https://target.test/login", {}, b"email=person@real.example.cn",
                                  allow_sensitive_auth=True)
        checks.append(("explicit auth exception", True))
    except OutboundPrivacyError:
        checks.append(("explicit auth exception", False))
    try:
        validate_outbound_request("POST", "https://target.test/login", {}, b"password=hunter2",
                                  allow_sensitive_auth=True)
        checks.append(("explicit auth secret exception", True))
    except OutboundPrivacyError:
        checks.append(("explicit auth secret exception", False))
    try:
        validate_outbound_request("GET", "https://tester:hunter2@target.test/", {}, None)
        checks.append(("URL userinfo secret requires explicit exception", False))
    except OutboundPrivacyError:
        checks.append(("URL userinfo secret requires explicit exception", True))
    try:
        validate_outbound_request(
            "GET", "https://tester:hunter2@target.test/", {}, None,
            allow_sensitive_auth=True,
        )
        checks.append(("URL userinfo explicit auth exception", True))
    except OutboundPrivacyError:
        checks.append(("URL userinfo explicit auth exception", False))
    safe_userinfo_url, userinfo_redactions = redact_url(
        "https://tester:hunter2@target.test/path"
    )
    checks.append(("URL userinfo redacted from record",
                   "tester" not in safe_userinfo_url
                   and "hunter2" not in safe_userinfo_url
                   and "url.userinfo" in userinfo_redactions))
    safe_fragment_url, fragment_redactions = redact_url(
        "https://target.test/callback#access_token=fragment-secret"
    )
    checks.append(("URL fragment secret redacted from record",
                   "fragment-secret" not in safe_fragment_url
                   and "url.fragment" in fragment_redactions))
    req, meta = sanitize_request_record(
        "POST", "https://target.test/login?email=person@real.example.cn",
        {"Authorization": "Bearer secret", "Content-Type": "application/x-www-form-urlencoded"},
        "password=hunter2&note=ok",
    )
    checks.extend([
        ("record secrets redacted", contains_redaction(req)),
        ("redacted record not replayable", meta["replayable"] is False),
        ("raw secret absent", "hunter2" not in json.dumps(req)),
        ("raw untyped secret field redacted",
         "hunter2" not in (redact_body("password=hunter2&note=ok")[0] or "")),
        ("local env marker not treated as payload",
         outbound_command_privacy_reason(
             "XUNJI_PROXY=socks5h://127.0.0.1:1080 python tools/probe.py GET https://target.test/"
         ) == ""),
        ("raw payload project marker denied",
         bool(outbound_command_privacy_reason("curl https://target.test/ -d marker=xunji-proof"))),
        ("raw cross-origin auth redirect denied",
         bool(outbound_command_privacy_reason(
             "curl -L https://target.test/ -H 'Authorization: Bearer secret'"
         ))),
        ("raw multipart auth secret denied",
         bool(outbound_command_privacy_reason(
             "curl -F password=hunter2 https://target.test/login"
         ))),
        ("WebSocket target payload project marker denied",
         bool(outbound_command_privacy_reason(
             "websocat 'wss://target.test/socket?marker=xunji-proof'"
         ))),
        ("urlencode file-backed field denied",
         bool(outbound_command_privacy_reason(
             "curl --data-urlencode password@secret.txt https://target.test/login"
         ))),
        ("unguarded custom target script denied",
         bool(outbound_command_privacy_reason(
             "python custom_sender.py https://target.test/"
         ))),
        ("unguarded Node target script denied",
         bool(outbound_command_privacy_reason(
             "node custom_sender.js https://target.test/"
         ))),
        ("unguarded Ruby target script denied",
         bool(outbound_command_privacy_reason(
             "ruby custom_sender.rb https://target.test/"
         ))),
        ("absolute custom target executable denied",
         bool(outbound_command_privacy_reason(
             "/tmp/custom_sender https://target.test/"
         ))),
        ("parent-relative custom target executable denied",
         bool(outbound_command_privacy_reason(
             "../custom_sender https://target.test/"
         ))),
        ("absolute Python interpreter custom sender denied",
         bool(outbound_command_privacy_reason(
             "/usr/bin/python3 custom_sender.py https://target.test/"
         ))),
        ("inline custom target script still denied despite guard-name text",
         bool(outbound_command_privacy_reason(
             "python -c \"RequestRecorder.validate('GET','https://target.test/')\""
         ))),
        ("guarded auth exception accepted",
         outbound_command_privacy_reason(
             "python tools/probe.py POST https://target.test/login --data email=person@real.example.cn --allow-sensitive-auth"
         ) == ""),
        ("raw URL userinfo denied",
         bool(outbound_command_privacy_reason(
             "curl https://operator:hunter2@target.test/private"
         ))),
        ("raw sensitive query denied",
         bool(outbound_command_privacy_reason(
             "curl 'https://target.test/private?token=hunter2'"
         ))),
    ])
    safe_log = sanitize_model_egress_text(
        "Authorization: Bearer hunter2\n"
        "python tools/setup_run.py alpha --target "
        "'https://operator:hunter2@target.test/path?key=opaque&note=ok'"
    )
    checks.append((
        "model/log egress hard-redacts headers, userinfo, and sensitive query",
        "hunter2" not in safe_log and "opaque" not in safe_log
        and "operator" not in safe_log and "note=ok" in safe_log,
    ))
    folded_log = sanitize_model_egress_text(
        "Authorization: Bearer first-line\n\tcontinuation-secret\nX-Note: keep"
    )
    checks.append((
        "model/log egress redacts folded authentication header continuations",
        "first-line" not in folded_log and "continuation-secret" not in folded_log
        and "X-Note: keep" in folded_log,
    ))
    with tempfile.TemporaryDirectory() as td:
        safe_file = Path(td) / "proof-20260713-a1b2c3d4.txt"
        safe_file.write_text("proof-20260713-a1b2c3d4", encoding="utf-8")
        safe_upload = f"curl -F 'file=@{safe_file};filename=proof-20260713-a1b2c3d4.txt' https://target.test/upload"
        checks.append(("inspectable neutral raw upload allowed",
                       outbound_command_privacy_reason(safe_upload) == ""))
        safe_file.write_text("marker=xunji-proof", encoding="utf-8")
        checks.append(("inspectable raw upload private content denied",
                       bool(outbound_command_privacy_reason(safe_upload))))
    multipart_headers = {"Content-Type": "multipart/form-data; boundary=proof-boundary"}
    multipart_body = (
        '--proof-boundary\r\nContent-Disposition: form-data; name="password"\r\n\r\n'
        'hunter2\r\n--proof-boundary--\r\n'
    )
    try:
        validate_outbound_request("POST", "https://target.test/login", multipart_headers, multipart_body)
        checks.append(("multipart auth secret requires explicit exception", False))
    except OutboundPrivacyError:
        checks.append(("multipart auth secret requires explicit exception", True))
    safe_multipart, multipart_redactions = redact_body(multipart_body, multipart_headers)
    checks.append(("multipart auth secret redacted from replay",
                   "hunter2" not in (safe_multipart or "")
                   and "body.password" in multipart_redactions))
    upload_body = (
        '--proof-boundary\r\nContent-Disposition: form-data; name="file"; '
        'filename="private-document.txt"\r\nContent-Type: text/plain\r\n\r\n'
        'proof-20260713-a1b2c3d4\r\n--proof-boundary--\r\n'
    )
    try:
        validate_outbound_request(
            "POST", "https://target.test/upload", multipart_headers, upload_body,
            allow_sensitive_auth=True,
        )
        checks.append(("multipart non-neutral filename denied", False))
    except OutboundPrivacyError:
        checks.append(("multipart non-neutral filename denied", True))
    safe_upload_body, upload_redactions = redact_body(upload_body, multipart_headers)
    checks.append(("multipart filename redacted from replay",
                   "private-document.txt" not in (safe_upload_body or "")
                   and "body.file.filename" in upload_redactions))
    private_boundary_headers = {
        "Content-Type": "multipart/form-data; boundary=xunji-private-boundary"
    }
    private_boundary_body = (
        '--xunji-private-boundary\r\nContent-Disposition: form-data; name="note"\r\n\r\n'
        'ok\r\n--xunji-private-boundary--\r\n'
    )
    safe_boundary_body, boundary_redactions = redact_body(
        private_boundary_body, private_boundary_headers,
    )
    checks.append(("multipart boundary redacted from replay body",
                   "xunji-private-boundary" not in (safe_boundary_body or "")
                   and "body.multipart.boundary" in boundary_redactions))
    safe_response, response_redactions = sanitize_response_record(
        200,
        {
            "Content-Type": "application/json",
            "Set-Cookie": "sid=secret123",
            "X-Session-ID": "response-session",
            "Location": "/callback?access_token=response-location-secret",
        },
        '{"token":"secret123","email":"person@real.example.cn"}',
    )
    serialized_response = json.dumps(safe_response, ensure_ascii=False)
    checks.append(("response preview secrets redacted",
                   "secret123" not in serialized_response
                   and "person@real.example.cn" not in serialized_response
                   and "response-session" not in serialized_response
                   and "response-location-secret" not in serialized_response
                   and any(item.startswith("response.body") for item in response_redactions)))
    bad = [name for name, ok in checks if not ok]
    for name, ok in checks:
        print(("ok   " if ok else "FAIL ") + name)
    print("privacy selftest " + ("passed" if not bad else f"FAILED ({len(bad)})"))
    return 0 if not bad else 1


if __name__ == "__main__":
    raise SystemExit(selftest())
