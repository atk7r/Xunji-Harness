#!/usr/bin/env python3
"""probe.py - active HTTP verifier (P2).

Sends crafted requests (any method/header/body/payload) to PROVE a vulnerability
exists, then stops. This is the proof-only verification primitive the skill
explicitly permits (SQLi differential, SSTI eval echo, auth-bypass, IDOR
existence) -- bounded by the guard layer:

- RateLimiter (禁高频: 速率是爆破的真正危害闸), cap_body (禁拖库: oversized
  bodies truncated), AuthFailCounter (防死循环: 弱口令随便试, 只兜底无限认证循环).
- It never dumps: bodies are capped and only summarized (status/len/sha1/snippet).

It is a sender, not an exploiter. Proof, not extraction. Examples:
  python tools/probe.py GET  "https://t/api/x?id=1"
  python tools/probe.py GET  "https://t/api/x?id=1'"          --tag sqli-probe
  python tools/probe.py DIFF "https://t/x?id=1 and 1=1" "https://t/x?id=1 and 1=2"
  python tools/probe.py POST "https://t/login" --data '{"u":"a"}' --auth-key t/login
"""

from __future__ import annotations

import argparse
import contextlib
import hashlib
import http.client
import json
import os
import re
import shutil
import ssl
import sys
import tempfile
import time
import urllib.request
from datetime import timezone
from email.utils import parsedate_to_datetime
from http.cookies import SimpleCookie
from pathlib import Path
from urllib.parse import parse_qsl, urlencode, urlparse

try:
    import fcntl
except ImportError:  # pragma: no cover - Windows fallback uses exclusive file create
    fcntl = None

sys.path.insert(0, str(Path(__file__).resolve().parent))
from harness import guard as guardmod  # noqa: E402
from harness.guard import (RateLimiter, AuthFailCounter,  # noqa: E402
                           RateBudgetExceeded, BruteforceLock,
                           HostHealth, HostBackoff, SessionBudget, SessionTripped,
                           MIN_STATIC_ASSET_BYTES)
from harness import privacy as privacymod  # noqa: E402
from harness.privacy import OutboundPrivacyError  # noqa: E402
from harness import proxy as proxymod  # noqa: E402  渗透流量走交战代理(模型调用不走)
from harness import output_layout  # noqa: E402

# Emit UTF-8 regardless of the OS locale, so this tool's JSON (ensure_ascii=False,
# 含中文/标题) survives being captured by a parent process on Windows (default
# GBK codec would crash the reader thread). Footgun fixed at the source.
try:
    sys.stdout.reconfigure(encoding="utf-8")       # type: ignore[attr-defined]
    sys.stderr.reconfigure(encoding="utf-8")       # type: ignore[attr-defined]
except Exception:
    pass

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36")
_CTX = ssl.create_default_context()
_CTX.check_hostname = False
_CTX.verify_mode = ssl.CERT_NONE

# Content-types safe for plaintext snippets in JSON output.
# Binary types (images, audio, video, octet-stream, etc.) get base64-encoded.
_TEXT_CTYPES = frozenset({
    "text/", "application/json", "application/xml", "application/xhtml+xml",
    "application/javascript", "application/ld+json", "application/rss+xml",
    "application/atom+xml", "application/x-www-form-urlencoded",
})

STREAM_READ_BYTES = 64 * 1024
MAX_CHUNK_CAPTURE_BYTES = 8 * 1024 * 1024
MAX_CHUNK_COUNT = 128
E_RANGE_NOT_HONORED = "XUNJI_E_PROBE_RANGE_NOT_HONORED"
E_CHUNK_LIMIT = "XUNJI_E_PROBE_BODY_CHUNK_LIMIT"
E_ARTIFACT_EXISTS = "XUNJI_E_PROBE_ARTIFACT_EXISTS"
E_RESPONSE_LENGTH_MISMATCH = "XUNJI_E_PROBE_RESPONSE_LENGTH_MISMATCH"
E_RESPONSE_FRAMING_INVALID = "XUNJI_E_PROBE_RESPONSE_FRAMING_INVALID"
E_ARTIFACT_PUBLISH_FAILED = "XUNJI_E_PROBE_ARTIFACT_PUBLISH_FAILED"


class ProbeCaptureError(RuntimeError):
    def __init__(self, code: str, message: str, *, observed_bytes: int = 0):
        super().__init__(message)
        self.code = code
        self.observed_bytes = observed_bytes


def _safe_snippet(raw: bytes, ctype: str, max_len: int = 240) -> tuple[str, str | None]:
    """Return (snippet_value, encoding_or_None).
    Text types: UTF-8 decoded snippet.
    Binary types: base64-encoded snippet with encoding="base64"."""
    ctype_lower = ctype.lower().split(";")[0].strip()
    is_text = any(ctype_lower.startswith(t) for t in _TEXT_CTYPES)
    if is_text:
        return raw[:max_len].decode("utf-8", "replace"), None
    import base64 as _b64
    return _b64.b64encode(raw[:max_len]).decode("ascii"), "base64"


def _snippet_kwargs(encoding: str | None) -> dict:
    """Return {"snippet_encoding": encoding} if encoding is set, else {}."""
    return {"snippet_encoding": encoding} if encoding else {}

# 代理: 通过 --proxy 或环境变量设置。境内资产需经中继时用。
_PROXY: str | None = None


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    """不跟随 3xx 跳转: redirect_request 返回 None 使 302/301/303/307 以 HTTPError 抛出, 由 send 的
    except 捕获(status=3xx + Location + 该跳的 Set-Cookie)。认证流(登录/注册成功后 302 带
    .AspNet.ApplicationCookie 等)的会话 cookie 就设在这一跳上, 跟随跳转会丢失它。顺带: 不自动追
    跳转 -> 不会被 302 带到 scope 外的 host。"""
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


class _PrivacyRedirect(urllib.request.HTTPRedirectHandler):
    """Validate every redirect and never forward auth secrets across origins."""

    def __init__(self, *, allow_sensitive_auth: bool = False,
                 allow_legacy_cleanup: bool = False):
        super().__init__()
        self.allow_sensitive_auth = allow_sensitive_auth
        self.allow_legacy_cleanup = allow_legacy_cleanup

    @staticmethod
    def _origin(url: str) -> tuple[str, str, int | None]:
        parsed = urlparse(url)
        return parsed.scheme.lower(), (parsed.hostname or "").lower(), parsed.port

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        redirected = super().redirect_request(req, fp, code, msg, headers, newurl)
        if redirected is None:
            return None
        if self._origin(req.full_url) != self._origin(redirected.full_url):
            for mapping in (redirected.headers, redirected.unredirected_hdrs):
                for key in list(mapping):
                    if key.lower() in privacymod.AUTH_HEADER_NAMES:
                        mapping.pop(key, None)
        privacymod.validate_outbound_request(
            redirected.get_method(), redirected.full_url,
            {**redirected.unredirected_hdrs, **redirected.headers}, redirected.data,
            allow_sensitive_auth=self.allow_sensitive_auth,
            allow_legacy_cleanup=self.allow_legacy_cleanup,
        )
        return redirected


def _opener(no_redirect: bool = False, *, selected_proxy: str | None = None,
            allow_sensitive_auth: bool = False,
            allow_legacy_cleanup: bool = False) -> urllib.request.OpenerDirector:
    # urllib_proxy_handlers 返回【完整连接 handler(含带 _CTX 的 HTTPS handler)】。这里【不要】再自己加
    # HTTPSHandler —— 否则普通 HTTPSHandler 会和 socks handler 抢 https, socks 连不上时悄悄走直连泄真实 IP
    # (实测坏代理仍回 200 的坑)。selected_proxy 已由 resolve() 冻结，避免 route ID、guard 与
    # opener 在配置并发变化时指向不同出口。
    handlers: list = list(proxymod.urllib_proxy_handlers(
        selected_proxy, ssl_context=_CTX))
    if no_redirect:
        handlers.append(_NoRedirect())          # build_opener 用它替换默认 HTTPRedirectHandler
    else:
        handlers.append(_PrivacyRedirect(
            allow_sensitive_auth=allow_sensitive_auth,
            allow_legacy_cleanup=allow_legacy_cleanup,
        ))
    return urllib.request.build_opener(*handlers)


@contextlib.contextmanager
def selftest_isolation():
    """Run local HTTP selftests with isolated guard state and no engagement proxy.

    Real active tools must honor the persistent guard state and `proxy.conf`.
    Local loopback regressions, however, need deterministic fixtures: a stale
    localhost HostHealth/SessionBudget entry or a developer's gitignored
    `proxy.conf` must not make the suite red.
    """
    tmp_root = Path(tempfile.mkdtemp())
    old = (
        _PROXY,
        proxymod._CONF,
        guardmod.STATE_DIR,
        guardmod._LOCK_PATH,
        os.environ.get("XUNJI_PROXY"),
        os.environ.get("XUNJI_PROXY_REQUIRED"),
    )
    try:
        os.environ.pop("XUNJI_PROXY", None)
        os.environ["XUNJI_PROXY_REQUIRED"] = "0"
        globals()["_PROXY"] = None
        proxymod._CONF = Path("__xunji_no_proxy_conf__")
        guardmod.STATE_DIR = tmp_root / "guard_state"
        guardmod.STATE_DIR.mkdir(parents=True, exist_ok=True)
        guardmod._LOCK_PATH = guardmod.STATE_DIR / ".lock"
        yield
    finally:
        (old_proxy, old_conf, old_state_dir, old_lock_path,
         old_proxy_env, old_required_env) = old
        globals()["_PROXY"] = old_proxy
        proxymod._CONF = old_conf
        guardmod.STATE_DIR = old_state_dir
        guardmod._LOCK_PATH = old_lock_path
        if old_proxy_env is None:
            os.environ.pop("XUNJI_PROXY", None)
        else:
            os.environ["XUNJI_PROXY"] = old_proxy_env
        if old_required_env is None:
            os.environ.pop("XUNJI_PROXY_REQUIRED", None)
        else:
            os.environ["XUNJI_PROXY_REQUIRED"] = old_required_env
        shutil.rmtree(tmp_root, ignore_errors=True)


def _is_waf_block(headers: dict, body: bytes) -> bool:
    """P1: 判断 403 是否为 WAF/策略拦截(非认证失败)。"""
    body_str = body.decode("utf-8", "replace").lower()
    waf_indicators = [
        "waf", "blocked", "access denied", "request rejected",
        "cloudfront", "akamai", "cloudflare", "imperva", "f5",
        "rate limit", "too many requests", "challenge",
    ]
    server = headers.get("Server", "").lower()
    if any(w in server for w in ["cloudfront", "cloudflare", "akamai"]):
        return True
    if any(w in body_str[:500] for w in waf_indicators):
        return True
    return False

def _range_header_value(byte_range: str) -> str:
    br = byte_range.strip()
    return br if br.lower().startswith("bytes=") else f"bytes={br}"


def _compact_json_text(raw: str) -> str:
    return json.dumps(json.loads(raw), ensure_ascii=False, separators=(",", ":"))


def _request_data_from_args(args: argparse.Namespace) -> tuple[bytes | None, bool]:
    sources = [
        args.data is not None,
        args.data_file is not None,
        args.data_json_file is not None,
        args.value_json is not None,
        args.value_json_file is not None,
    ]
    if sum(1 for x in sources if x) > 1:
        raise ValueError("choose only one of --data/--data-file/--data-json-file/--value-json/--value-json-file")
    if args.data is not None:
        return args.data.encode(), True
    if args.data_file is not None:
        return Path(args.data_file).read_bytes(), False
    if args.data_json_file is not None:
        raw = Path(args.data_json_file).read_text(encoding="utf-8")
        return _compact_json_text(raw).encode(), True
    if args.value_json is not None:
        value = _compact_json_text(args.value_json)
        return json.dumps({"Value": value}, ensure_ascii=False, separators=(",", ":")).encode(), True
    if args.value_json_file is not None:
        value = _compact_json_text(Path(args.value_json_file).read_text(encoding="utf-8"))
        return json.dumps({"Value": value}, ensure_ascii=False, separators=(",", ":")).encode(), True
    return None, False


def _fsync_directory(path: Path) -> None:
    flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0)
    fd = os.open(str(path), flags)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def _atomic_write_bytes(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=str(path.parent))
    tmp = Path(tmp_name)
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp, path)
        _fsync_directory(path.parent)
    except Exception:
        try:
            tmp.unlink()
        except OSError:
            pass
        raise


def _atomic_write_json(path: Path, value: dict) -> None:
    _atomic_write_bytes(
        path,
        (json.dumps(value, ensure_ascii=False, indent=2) + "\n").encode("utf-8"),
    )


def _publish_bytes_noclobber(path: Path, data: bytes) -> None:
    """Durably publish one new file without ever replacing a competing path."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=str(path.parent))
    tmp = Path(tmp_name)
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.link(tmp, path)
        _fsync_directory(path.parent)
    finally:
        try:
            tmp.unlink()
        except OSError:
            pass


@contextlib.contextmanager
def _artifact_output_reservation(save: str | None):
    """Reserve one save group across target I/O without creating partial evidence."""
    if not save:
        yield
        return
    lock_root = Path(tempfile.gettempdir()) / "xunji-probe-reservations"
    lock_root.mkdir(mode=0o700, parents=True, exist_ok=True)
    lock_name = hashlib.sha256(
        str(Path(save).absolute()).encode("utf-8")).hexdigest() + ".lock"
    lock_path = lock_root / lock_name
    descriptor: int | None = None
    exclusive_path = False
    try:
        if fcntl is not None:
            descriptor = os.open(lock_path, os.O_RDWR | os.O_CREAT, 0o600)
            try:
                fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except OSError as exc:
                raise FileExistsError(
                    "artifact output is reserved by another probe invocation") from exc
        else:  # pragma: no cover - exercised only where advisory file locks lack
            descriptor = os.open(
                lock_path, os.O_RDWR | os.O_CREAT | os.O_EXCL, 0o600)
            exclusive_path = True
        yield
    finally:
        if descriptor is not None:
            if fcntl is not None:
                try:
                    fcntl.flock(descriptor, fcntl.LOCK_UN)
                except OSError:
                    pass
            os.close(descriptor)
        if exclusive_path:
            try:
                lock_path.unlink()
            except OSError:
                pass


def _read_response_stream(
    stream,
    *,
    save_chunks: bool,
    chunk_size: int,
) -> tuple[bytes, int, str, str, bytes | None]:
    """Read a wire response once while retaining only bounded local bytes."""
    if chunk_size <= 0:
        raise ValueError("chunk_size must be positive")
    if save_chunks and chunk_size > MAX_CHUNK_CAPTURE_BYTES:
        raise ValueError(
            f"chunk_size exceeds hard capture limit {MAX_CHUNK_CAPTURE_BYTES}")
    body = bytearray()
    full_parts: list[bytes] | None = [] if save_chunks else None
    sha1 = hashlib.sha1()
    sha256 = hashlib.sha256()
    wire_len = 0
    while True:
        part = stream.read(STREAM_READ_BYTES)
        if not part:
            break
        wire_len += len(part)
        sha1.update(part)
        sha256.update(part)
        remaining = guardmod.MAX_BODY_BYTES - len(body)
        if remaining > 0:
            body.extend(part[:remaining])
        if full_parts is not None:
            if wire_len > MAX_CHUNK_CAPTURE_BYTES:
                raise ProbeCaptureError(
                    E_CHUNK_LIMIT,
                    "response exceeds explicit chunk capture byte limit",
                    observed_bytes=wire_len,
                )
            required_chunks = max(1, (wire_len + chunk_size - 1) // chunk_size)
            if required_chunks > MAX_CHUNK_COUNT:
                raise ProbeCaptureError(
                    E_CHUNK_LIMIT,
                    "response exceeds explicit chunk capture count limit",
                    observed_bytes=wire_len,
                )
            full_parts.append(part)
    return (
        bytes(body), wire_len, sha1.hexdigest(), sha256.hexdigest(),
        b"".join(full_parts) if full_parts is not None else None,
    )


def _range_response_error(
    requested: str | None,
    *,
    status: int,
    headers: dict,
    body_len: int | None = None,
) -> str:
    if not requested:
        return ""
    request_match = re.fullmatch(
        r"bytes=(\d+)-(\d+)", requested.strip(), re.I)
    if not request_match:
        return "only one explicit bytes=start-end range is supported"
    req_start, req_end = (int(request_match.group(1)), int(request_match.group(2)))
    if req_end < req_start:
        return "range end precedes range start"
    if status != 206:
        return f"server ignored Range and returned status {status}"
    value = _header_value(headers, "Content-Range") or ""
    response_match = re.fullmatch(
        r"bytes\s+(\d+)-(\d+)/(\d+|\*)", value.strip(), re.I)
    if not response_match:
        return "missing or malformed Content-Range"
    got_start, got_end = int(response_match.group(1)), int(response_match.group(2))
    total = response_match.group(3)
    clipped_at_eof = (
        total != "*"
        and got_start == req_start
        and got_end < req_end
        and got_end == int(total) - 1
        and req_start < int(total)
    )
    if got_start != req_start or (got_end != req_end and not clipped_at_eof):
        return "Content-Range does not match requested byte interval"
    if total != "*" and (int(total) <= got_end):
        return "Content-Range total is inconsistent"
    if body_len is not None and body_len != got_end - got_start + 1:
        return "Content-Range length differs from received bytes"
    return ""


def _content_length_error(
    headers: dict,
    *,
    body_len: int,
    method: str,
    status: int,
) -> str:
    """Detect incomplete or ambiguous HTTP message framing.

    Content-Length describes the framed response body, not the origin resource.
    It is therefore checked only where a body is permitted and transfer-encoding
    has not replaced it.
    """
    declared = (_header_value(headers, "Content-Length") or "").strip()
    transfer = (_header_value(headers, "Transfer-Encoding") or "").strip()
    if declared and transfer:
        return "response contains both Content-Length and Transfer-Encoding"
    if not declared or transfer or method.upper() == "HEAD" \
            or status in {204, 304} or 100 <= status < 200:
        return ""
    if not re.fullmatch(r"\d+", declared):
        return "malformed Content-Length"
    if int(declared) != body_len:
        return "Content-Length differs from received response bytes"
    return ""


def _duplicate_content_length_error(headers) -> str:
    values = headers.get_all("Content-Length") \
        if hasattr(headers, "get_all") else None
    if values is not None and len(values) > 1:
        return "response contains multiple Content-Length headers"
    return ""


def _write_body_chunks(save: str, raw: bytes, *, chunk_size: int,
                       wire_sha1: str, wire_sha256: str) -> dict:
    if chunk_size <= 0:
        raise ValueError("chunk_size must be positive")
    if len(raw) > MAX_CHUNK_CAPTURE_BYTES:
        raise ProbeCaptureError(
            E_CHUNK_LIMIT, "response exceeds explicit chunk capture byte limit",
            observed_bytes=len(raw))
    required_chunks = max(1, (len(raw) + chunk_size - 1) // chunk_size)
    if required_chunks > MAX_CHUNK_COUNT:
        raise ProbeCaptureError(
            E_CHUNK_LIMIT, "response exceeds explicit chunk capture count limit",
            observed_bytes=len(raw))
    base = Path(save)
    chunk_dir = base.with_name(base.name + ".chunks")
    manifest_path = base.with_name(base.name + ".chunks.json")
    if chunk_dir.exists() or manifest_path.exists():
        raise FileExistsError("chunk output already exists; choose a fresh --save path")
    base.parent.mkdir(parents=True, exist_ok=True)
    stage_root = Path(tempfile.mkdtemp(
        prefix=f".{base.name}.chunks-stage-", dir=str(base.parent)))
    stage_chunks = stage_root / chunk_dir.name
    stage_chunks.mkdir()
    chunks: list[dict] = []
    try:
        offsets = list(range(0, len(raw), chunk_size)) or [0]
        for idx, offset in enumerate(offsets):
            part = raw[offset:offset + chunk_size]
            name = f"part-{idx:04d}.bin"
            part_path = stage_chunks / name
            _atomic_write_bytes(part_path, part)
            chunks.append({
                "path": f"{chunk_dir.name}/{name}",
                "offset": offset,
                "bytes": len(part),
                "sha256": hashlib.sha256(part).hexdigest(),
            })
        manifest = {
            "schema": "xunji.probe.body_chunks.v2",
            "saved_body": base.name,
            "chunk_dir": chunk_dir.name,
            "chunk_size": chunk_size,
            "wire_len": len(raw),
            "wire_sha1": wire_sha1,
            "wire_sha256": wire_sha256,
            "chunks": chunks,
        }
        chunk_dir.mkdir()
        for item in chunks:
            name = Path(str(item["path"])).name
            os.link(stage_chunks / name, chunk_dir / name)
        _fsync_directory(chunk_dir)
        _fsync_directory(base.parent)
    except Exception:
        if chunk_dir.exists() and not manifest_path.exists():
            shutil.rmtree(chunk_dir, ignore_errors=True)
        raise
    finally:
        shutil.rmtree(stage_root, ignore_errors=True)
    return {
        "manifest": str(manifest_path),
        "manifest_reference": manifest_path.name,
        "chunk_dir": str(chunk_dir),
        "chunks": len(chunks),
        "full_len": len(raw),
        "full_sha1": wire_sha1,
        "full_sha256": wire_sha256,
        "manifest_data": manifest,
    }


def _header_value(headers: dict, name: str) -> str | None:
    name_l = name.lower()
    for k, v in headers.items():
        if k.lower() == name_l:
            return v
    return None


def _set_header(headers: dict, name: str, value: str) -> None:
    for k in list(headers):
        if k.lower() == name.lower():
            headers[k] = value
            return
    headers[name] = value


def _cookie_dict_from_header(value: str | None) -> dict[str, str]:
    out: dict[str, str] = {}
    if not value:
        return out
    for part in value.split(";"):
        if "=" not in part:
            continue
        k, v = part.split("=", 1)
        k = k.strip()
        if k:
            out[k] = v.strip()
    return out


def _cookie_expired(expires: str, *, now: float | None = None) -> bool:
    """Interpret timezone-less legacy dates as UTC, matching HTTP-date semantics."""
    try:
        expires_at = parsedate_to_datetime(expires)
        if expires_at.tzinfo is None:
            expires_at = expires_at.replace(tzinfo=timezone.utc)
        return expires_at.timestamp() <= (time.time() if now is None else now)
    except (TypeError, ValueError, OverflowError):
        return False


def _cookie_dict_from_set_cookies(values: list[str]) -> dict[str, str | None]:
    """Parse Set-Cookie updates; ``None`` means the server deleted the cookie."""
    out: dict[str, str | None] = {}
    for raw in values:
        c = SimpleCookie()
        try:
            c.load(raw)
        except Exception:
            continue
        for name, morsel in c.items():
            expired = False
            expires = str(morsel["expires"] or "").strip()
            if expires:
                expired = _cookie_expired(expires)
            deleted = (
                not morsel.value
                or str(morsel["max-age"] or "").strip() == "0"
                or expired
            )
            out[name] = None if deleted else morsel.value
    return out


def _cookie_header(cookies: dict[str, str]) -> str:
    return "; ".join(f"{k}={v}" for k, v in sorted(cookies.items()))


def _load_cookie_jar(path: str | None) -> dict[str, str]:
    if not path or not Path(path).exists():
        return {}
    data = json.loads(Path(path).read_text(encoding="utf-8", errors="replace"))
    if not isinstance(data, dict):
        raise ValueError(f"cookie jar must be a JSON object: {path}")
    return {
        str(k): str(v)
        for k, v in data.items()
        if str(k).strip() and v is not None and str(v)
    }


def _save_cookie_jar(path: str | None, cookies: dict[str, str]) -> None:
    if not path:
        return
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    tmp_name = ""
    with tempfile.NamedTemporaryFile(
        "w", delete=False, dir=p.parent, prefix=p.name + ".", suffix=".tmp", encoding="utf-8"
    ) as f:
        tmp_name = f.name
        f.write(json.dumps(cookies, ensure_ascii=False, indent=2) + "\n")
    os.chmod(tmp_name, 0o600)
    Path(tmp_name).replace(p)


def _merge_cookies_into_headers(
    headers: dict,
    cookies: dict[str, str],
    *,
    prefer_cookies: bool = False,
) -> dict:
    explicit = _cookie_dict_from_header(_header_value(headers, "Cookie"))
    merged = dict(explicit) if prefer_cookies else dict(cookies)
    merged.update(cookies if prefer_cookies else explicit)
    if merged:
        _set_header(headers, "Cookie", _cookie_header(merged))
    return headers


def _extract_csrf_token(body: bytes, pattern: str) -> str:
    text = body.decode("utf-8", "replace")
    m = re.search(pattern, text, flags=re.S)
    if not m:
        raise ValueError("--extract-csrf pattern did not match preflight body")
    if "value" in m.groupdict():
        return m.group("value")
    if m.groups():
        return m.group(1)
    return m.group(0)


def _inject_csrf(data: bytes | None, *, json_body: bool, field: str, token: str) -> tuple[bytes, bool]:
    if json_body:
        obj = json.loads((data or b"{}").decode("utf-8"))
        if not isinstance(obj, dict):
            raise ValueError("JSON CSRF injection requires a JSON object body")
        obj[field] = token
        return json.dumps(obj, ensure_ascii=False, separators=(",", ":")).encode("utf-8"), True
    pairs = parse_qsl((data or b"").decode("utf-8", "replace"), keep_blank_values=True)
    replaced = False
    for idx, (k, _v) in enumerate(pairs):
        if k == field:
            pairs[idx] = (k, token)
            replaced = True
    if not replaced:
        pairs.append((field, token))
    return urlencode(pairs).encode("utf-8"), False


def _apply_preflight(args, headers: dict, data: bytes | None, json_body: bool) -> tuple[dict, bytes | None, bool, dict]:
    """GET a form/bootstrap page, merge cookies, and inject an extracted CSRF token."""
    meta: dict = {}
    jar = _load_cookie_jar(getattr(args, "cookie_jar", None))
    original_explicit_cookies = _cookie_dict_from_header(_header_value(headers, "Cookie"))
    _merge_cookies_into_headers(headers, jar)
    preflight_url = getattr(args, "preflight_get", None)
    if not preflight_url:
        return headers, data, json_body, meta

    tmp_save = None
    preflight_save = getattr(args, "preflight_save", None)
    if getattr(args, "extract_csrf", None) and not preflight_save:
        tmp_save = str(Path(tempfile.mkdtemp()) / "preflight.html")
        preflight_save = tmp_save
    try:
        pre = send(
            "GET", preflight_url, headers.copy(), None, None, args.timeout,
            save=preflight_save, retry=args.retry, retry_wait=args.retry_wait,
            want_headers=True, no_redirect=args.no_redirect,
        )
        cookie_updates = _cookie_dict_from_set_cookies(pre.get("set_cookies", []))
        if cookie_updates:
            for name, value in cookie_updates.items():
                if value is None:
                    jar.pop(name, None)
                else:
                    jar[name] = value
            _save_cookie_jar(getattr(args, "cookie_jar", None), jar)
            # A fresh Set-Cookie is the browser-equivalent update and therefore
            # wins over a same-name Cookie supplied for the initial GET. Build
            # from the original explicit header so deleted jar cookies cannot
            # survive through the already-merged preflight request header.
            post_cookies = dict(jar)
            post_cookies.update(original_explicit_cookies)
            for name, value in cookie_updates.items():
                if value is None:
                    post_cookies.pop(name, None)
                else:
                    post_cookies[name] = value
            _set_header(headers, "Cookie", _cookie_header(post_cookies))
        meta = {
            "url": preflight_url,
            "status": pre.get("status"),
            "cookies": sorted(cookie_updates),
        }
        if getattr(args, "extract_csrf", None):
            if not preflight_save or not Path(preflight_save).exists():
                raise ValueError("--extract-csrf requires a readable preflight body")
            token = _extract_csrf_token(Path(preflight_save).read_bytes(), args.extract_csrf)
            field = args.csrf_field or "__RequestVerificationToken"
            data, json_body = _inject_csrf(data, json_body=json_body, field=field, token=token)
            if not json_body and not _header_value(headers, "Content-Type"):
                _set_header(headers, "Content-Type", "application/x-www-form-urlencoded")
            meta.update({"csrf_field": field, "csrf_extracted": True})
        return headers, data, json_body, meta
    finally:
        if tmp_save:
            for p in (Path(tmp_save), Path(tmp_save + ".replay.json")):
                try:
                    p.unlink()
                except OSError:
                    pass


def _send_impl(method: str, url: str, headers: dict, data: bytes | None,
               auth_key: str | None, timeout: int, save: str | None = None,
               retry: int = 0, retry_wait: float = 1.5,
               want_headers: bool = False, no_redirect: bool = False,
               byte_range: str | None = None, save_chunks: bool = False,
               chunk_size: int = guardmod.MAX_BODY_BYTES,
               allow_sensitive_auth: bool = False,
               allow_legacy_cleanup: bool = False) -> dict:
    req_headers = {"User-Agent": UA, **headers}
    if byte_range and not any(k.lower() == "range" for k in req_headers):
        req_headers["Range"] = _range_header_value(byte_range)
    requested_range = _header_value(req_headers, "Range")
    if requested_range and not re.fullmatch(
            r"bytes=\d+-\d+", requested_range.strip(), re.I):
        return {
            "method": method.upper(), "url": url,
            "error": "only one explicit bytes=start-end range is supported",
            "error_code": E_RANGE_NOT_HONORED,
        }
    if save_chunks and (
            chunk_size <= 0 or chunk_size > MAX_CHUNK_CAPTURE_BYTES):
        return {
            "method": method.upper(), "url": url,
            "error": "chunk_size is outside the bounded capture contract",
            "error_code": E_CHUNK_LIMIT,
        }
    if save:
        save_path = Path(save)
        output_paths = [save_path, Path(save + ".replay.json")]
        if save_chunks:
            output_paths.extend([
                save_path.with_name(save_path.name + ".chunks"),
                save_path.with_name(save_path.name + ".chunks.json"),
            ])
        if any(path.exists() or path.is_symlink() for path in output_paths):
            return {
                "method": method.upper(), "url": url,
                "error": "artifact output already exists; choose a fresh --save path",
                "error_code": E_ARTIFACT_EXISTS,
            }
    # Privacy is a pre-I/O boundary.  Reject generated project/operator identity
    # and real PII before rate state mutates or an opener can touch the target.
    privacymod.validate_outbound_request(
        method, url, req_headers, data,
        allow_sensitive_auth=allow_sensitive_auth,
        allow_legacy_cleanup=allow_legacy_cleanup,
    )
    host = urlparse(url).hostname or "unknown"
    selected_proxy = proxymod.resolve(_PROXY)
    egress_route = guardmod.egress_route_id(selected_proxy)
    afc = AuthFailCounter()
    if auth_key:
        afc.check(auth_key)            # anti-runaway: stop once locked
    hh = HostHealth()
    sb = SessionBudget()

    req = urllib.request.Request(url=url, method=method.upper(),
                                 data=data, headers=req_headers)
    summary: dict = {"method": method.upper(), "url": url,
                     "egress_route": egress_route}
    if requested_range:
        summary["range"] = requested_range
    opener = _opener(
        no_redirect,
        selected_proxy=selected_proxy,
        allow_sensitive_auth=allow_sensitive_auth,
        allow_legacy_cleanup=allow_legacy_cleanup,
    )
    last_err: str | None = None
    body = b""
    wire_len = 0
    wire_sha1 = hashlib.sha1(b"").hexdigest()
    wire_sha256 = hashlib.sha256(b"").hexdigest()
    chunk_raw: bytes | None = None
    capture_error: ProbeCaptureError | None = None
    status = 0
    resp_headers: dict = {}
    cookie_list: list[str] = []            # ALL Set-Cookie values (dict() would drop dups)
    attempts = 0                           # 真实发出的请求数(含重试), 供整场量精确计数
    attempt_error_classes: list[str] = []
    for attempt in range(retry + 1):
        # Every real attempt re-checks shared route/host and whole-session state.
        # This prevents one --retry call from overrunning a breaker that armed on
        # an earlier attempt, and gives a cooled breaker exactly one half-open I/O.
        lease = hh.check(host, egress_route=egress_route)
        sb.check()
        attempts += 1
        RateLimiter().gate(host)           # 禁高频(每次实际请求都计入)
        try:
            with opener.open(req, timeout=timeout) as r:
                status = r.status
                framing_error = _duplicate_content_length_error(r.headers)
                if framing_error:
                    raise ProbeCaptureError(
                        E_RESPONSE_FRAMING_INVALID, framing_error)
                resp_headers = dict(r.headers)
                cookie_list = r.headers.get_all("Set-Cookie") or []
                range_error = _range_response_error(
                    requested_range, status=status, headers=resp_headers)
                if range_error:
                    raise ProbeCaptureError(E_RANGE_NOT_HONORED, range_error)
                body, wire_len, wire_sha1, wire_sha256, chunk_raw = (
                    _read_response_stream(
                        r, save_chunks=save_chunks, chunk_size=chunk_size))
                length_error = _content_length_error(
                    resp_headers, body_len=wire_len, method=method,
                    status=status)
                if length_error:
                    raise ProbeCaptureError(
                        E_RESPONSE_LENGTH_MISMATCH, length_error,
                        observed_bytes=wire_len)
                range_error = _range_response_error(
                    requested_range, status=status, headers=resp_headers,
                    body_len=wire_len)
                if range_error:
                    raise ProbeCaptureError(
                        E_RANGE_NOT_HONORED, range_error,
                        observed_bytes=wire_len)
            last_err = None
            break
        except urllib.error.HTTPError as e:
            status = e.code
            framing_error = _duplicate_content_length_error(e.headers)
            if framing_error:
                capture_error = ProbeCaptureError(
                    E_RESPONSE_FRAMING_INVALID, framing_error)
                last_err = None
                break
            resp_headers = dict(e.headers or {})
            cookie_list = (e.headers.get_all("Set-Cookie") if e.headers else None) or []
            range_error = _range_response_error(
                requested_range, status=status, headers=resp_headers)
            if range_error:
                capture_error = ProbeCaptureError(
                    E_RANGE_NOT_HONORED, range_error)
                last_err = None
                break
            try:
                body, wire_len, wire_sha1, wire_sha256, chunk_raw = (
                    _read_response_stream(
                        e, save_chunks=save_chunks, chunk_size=chunk_size))
                length_error = _content_length_error(
                    resp_headers, body_len=wire_len, method=method,
                    status=status)
                if length_error:
                    raise ProbeCaptureError(
                        E_RESPONSE_LENGTH_MISMATCH, length_error,
                        observed_bytes=wire_len)
                range_error = _range_response_error(
                    requested_range, status=status, headers=resp_headers,
                    body_len=wire_len)
                if range_error:
                    raise ProbeCaptureError(
                        E_RANGE_NOT_HONORED, range_error,
                        observed_bytes=wire_len)
            except ProbeCaptureError as exc:
                capture_error = exc
            last_err = None
            break
        except ProbeCaptureError as exc:
            capture_error = exc
            last_err = None
            break
        except http.client.IncompleteRead as exc:
            capture_error = ProbeCaptureError(
                E_RESPONSE_LENGTH_MISMATCH,
                "response ended before its declared Content-Length",
                observed_bytes=len(exc.partial or b""),
            )
            last_err = None
            break
        except http.client.HTTPException as exc:
            capture_error = ProbeCaptureError(
                E_RESPONSE_FRAMING_INVALID,
                f"invalid HTTP response framing: {exc.__class__.__name__}",
            )
            last_err = None
            break
        except OutboundPrivacyError:
            raise
        except Exception as e:
            last_err = str(e)
            error_class = guardmod.classify_network_error(e, egress_route=egress_route)
            attempt_error_classes.append(error_class)
            sb_warn = sb.record(0, count=1)
            if sb_warn:
                print(sb_warn, file=sys.stderr)
            hh.record_error(host, egress_route=egress_route,
                            error_class=error_class, lease=lease)
            if guardmod.host_error_policy(error_class)["attribution"] == "proxy":
                # A broken explicit proxy is not a transient target retry. The
                # first route-attributed failure opens a manual pause; return now
                # even when --retry was supplied and wait for a newer operator turn.
                break
            if attempt < retry:
                time.sleep(retry_wait)     # 瞬时超时/RST 重试(如本次 vpn)
    if last_err is not None:
        error_class = attempt_error_classes[-1]
        policy = guardmod.host_error_policy(error_class)
        transport_type = "cdn_tls_reject" if error_class == "target_tls" else "transport_error"
        out = {
            **summary,
            "error": last_err,
            "transport_error": True,
            "error_type": transport_type,
            **policy,
            "attempt_error_classes": attempt_error_classes,
            "attempts": attempts,
        }
        if policy["attribution"] == "proxy":
            out.update({
                "restart_policy": "operator_confirmation_required",
                "automatic_retry_stopped": True,
                "next_action": (
                    "stop and wait for the operator to choose default direct or "
                    "explicitly confirm proxy again"
                ),
            })
        return out
    if capture_error is not None:
        observed = max(wire_len, capture_error.observed_bytes)
        sb_warn = sb.record(observed, count=1)
        if sb_warn:
            print(sb_warn, file=sys.stderr)
        hh.record_ok(host, egress_route=egress_route, lease=lease)
        return {
            **summary,
            "status": status,
            "error": str(capture_error),
            "error_code": capture_error.code,
            "observed_bytes": observed,
            "transport_error": False,
            "application_error": status >= 400,
            "auth_failure": status in {401, 403},
            "blocked_by_policy": False,
            "capture_error": True,
            "attempts": attempts,
        }
    # JS/CSS 静态资源 >MIN_STATIC_ASSET_BYTES 不计入 bytes budget(防 JS-heavy SPA 的 chunk 下载触发假熔断);
    # 仍计入 count budget。小于阈值的仍正常计(防大量小文件绕过)。
    response_content_type = _header_value(resp_headers, "Content-Type") or ""
    content_type = response_content_type.lower()
    record_bytes = wire_len
    if wire_len >= MIN_STATIC_ASSET_BYTES and any(t in content_type for t in ("javascript", "css")):
        record_bytes = 0
    # Failed attempts were recorded at failure time; this records the one HTTP
    # response and its wire bytes, so retries cannot be double-counted.
    sb_warn = sb.record(record_bytes, count=1)
    if sb_warn:
        print(sb_warn, file=sys.stderr)
    hh.record_ok(host, egress_route=egress_route, lease=lease)  # HTTP response = route/target healthy
    warn = hh.soft_warn(host, egress_route=egress_route)
    if warn:
        print(warn, file=sys.stderr)

    truncated = wire_len > len(body)
    _full_sha1 = wire_sha1
    _snippet_val, _snippet_enc = _safe_snippet(body, response_content_type)
    summary.update({
        "status": status,
        "len": wire_len,
        "truncated": truncated,
        "sha1": _full_sha1[:12],
        "sha1_full": _full_sha1,            # 全 sha1: replay 比对整完整性(不削成 48-bit)
        "ctype": response_content_type,
        "server": resp_headers.get("Server", ""),
        "snippet": _snippet_val,
        **_snippet_kwargs(_snippet_enc),
        # P1: 错误分类
        "transport_error": False,
        "application_error": False,
        "auth_failure": False,
        "blocked_by_policy": False,
        "cdn_tls_reject": False,
    })
    # P1: 分类 HTTP 响应
    if status in (401,):
        summary["auth_failure"] = True
    if status in (403,):
        if _is_waf_block(resp_headers, body):
            summary["blocked_by_policy"] = True
        else:
            summary["auth_failure"] = True
    if status in (429, 503):
        summary["blocked_by_policy"] = True
    if status >= 400 and not summary["auth_failure"] and not summary["blocked_by_policy"]:
        summary["application_error"] = True
    if want_headers:
        # 完整响应头(Location/Set-Cookie 等), 分析跳转/会话/WAF 用。
        # dict(r.headers) 对重复 Set-Cookie 只留一个 -> 多 cookie(antiforgery+session)会丢;
        # 用 get_all 把全部 Set-Cookie 合并回 headers, 并单列 set_cookies 列表供会话流程解析。
        if cookie_list:
            resp_headers["Set-Cookie"] = "\n".join(cookie_list)
        summary["headers"] = resp_headers
        summary["set_cookies"] = cookie_list
    if save:
        # Publish body/chunks/replay from temporary files.  The v2 manifest is
        # written last and is therefore the group commit marker.
        Path(save).parent.mkdir(parents=True, exist_ok=True)
        chunk_info = None
        published_paths: list[Path] = []
        try:
            if save_chunks:
                if chunk_raw is None:
                    raise ProbeCaptureError(
                        E_CHUNK_LIMIT, "chunk capture bytes were not retained")
                chunk_info = _write_body_chunks(
                    save, chunk_raw, chunk_size=chunk_size,
                    wire_sha1=wire_sha1, wire_sha256=wire_sha256)
                published_paths.append(Path(chunk_info["chunk_dir"]))
                summary["chunk_manifest"] = chunk_info["manifest"]
                summary["chunk_count"] = chunk_info["chunks"]
                summary["chunk_full_len"] = chunk_info["full_len"]
                summary["chunk_full_sha1"] = chunk_info["full_sha1"]
                summary["chunk_full_sha256"] = chunk_info["full_sha256"]

            _publish_bytes_noclobber(Path(save), body)
            published_paths.append(Path(save))
            summary["saved"] = save
            summary["saved_bytes"] = len(body)

            # snippet 覆盖率提醒 driver 使用 bounded artifact_view，而不是让
            # Agent 一次 Read 整个大型静态资源。
            snippet_len = min(240, len(body))
            summary["snippet_pct"] = round(
                snippet_len / max(len(body), 1) * 100, 1)
            if len(body) > 500:
                print(
                    f"[probe] saved {len(body)} bytes → {save}  "
                    f"(snippet covers {summary['snippet_pct']}% only — "
                    "use bounded artifact view for inspection)",
                    file=sys.stderr,
                )

            safe_request, request_privacy = privacymod.sanitize_request_record(
                method, url, req_headers, data,
                auth_exception=allow_sensitive_auth,
            )
            safe_response, response_redactions = privacymod.sanitize_response_record(
                status, resp_headers, _snippet_val,
            )
            safe_snippet_encoding = _snippet_enc if not any(
                item.startswith("response.body") for item in response_redactions
            ) else None
            replay = {
                "schema": "xunji.probe.replay.v2",
                "ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                "request": safe_request,
                "response": {
                    "status": status,
                    "len": wire_len,
                    "sha1": wire_sha1,
                    "wire_len": wire_len,
                    "wire_sha1": wire_sha1,
                    "wire_sha256": wire_sha256,
                    "ctype": response_content_type,
                    "headers": safe_response["headers"],
                    "snippet": safe_response["body_preview"],
                    **_snippet_kwargs(safe_snippet_encoding),
                },
                "privacy": {
                    **request_privacy,
                    "response_redactions": response_redactions,
                },
                "saved_body": save,
                "saved_body_meta": {
                    "len": len(body),
                    "sha1": hashlib.sha1(body).hexdigest(),
                    "truncated": bool(truncated),
                },
            }
            if chunk_info:
                replay["saved_body_chunks"] = chunk_info["manifest_reference"]
            replay_path = save + ".replay.json"
            _publish_bytes_noclobber(
                Path(replay_path),
                (json.dumps(replay, ensure_ascii=False, indent=2) + "\n").encode(
                    "utf-8"),
            )
            published_paths.append(Path(replay_path))
            summary["replay"] = replay_path

            if chunk_info:
                _publish_bytes_noclobber(
                    Path(chunk_info["manifest"]),
                    (json.dumps(
                        chunk_info["manifest_data"], ensure_ascii=False,
                        indent=2,
                    ) + "\n").encode("utf-8"),
                )
                published_paths.append(Path(chunk_info["manifest"]))
        except BaseException:
            for path in reversed(published_paths):
                try:
                    if path.is_dir() and not path.is_symlink():
                        shutil.rmtree(path)
                    else:
                        path.unlink()
                except OSError:
                    pass
            raise
    if auth_key:
        # heuristic: 401/403 or a login-ish redirect counts as an auth failure
        ok = status not in (401, 403)
        afc.record(auth_key, ok)
        if afc.would_pivot(auth_key):
            summary["pivot_required"] = True
            summary["pivot_reason"] = (
                f"同一端点 {afc.pivot}+ 次认证失败 — 猜测攻击不会产生新价值。"
                "转向逻辑漏洞/配置错误/未授权API/IDOR/路径穿越。"
            )
    return summary


def send(method: str, url: str, headers: dict, data: bytes | None,
         auth_key: str | None, timeout: int, save: str | None = None,
         retry: int = 0, retry_wait: float = 1.5,
         want_headers: bool = False, no_redirect: bool = False,
         byte_range: str | None = None, save_chunks: bool = False,
         chunk_size: int = guardmod.MAX_BODY_BYTES,
         allow_sensitive_auth: bool = False,
         allow_legacy_cleanup: bool = False) -> dict:
    """Reserve a save group before network I/O, then publish it no-clobber."""
    try:
        with _artifact_output_reservation(save):
            return _send_impl(
                method, url, headers, data, auth_key, timeout, save, retry,
                retry_wait, want_headers, no_redirect, byte_range, save_chunks,
                chunk_size, allow_sensitive_auth, allow_legacy_cleanup,
            )
    except FileExistsError as exc:
        return {
            "method": method.upper(), "url": url,
            "error": str(exc), "error_code": E_ARTIFACT_EXISTS,
        }
    except OSError as exc:
        return {
            "method": method.upper(), "url": url,
            "error": f"artifact publication failed: {exc.__class__.__name__}",
            "error_code": E_ARTIFACT_PUBLISH_FAILED,
            "capture_error": True,
            "blocked_by_policy": False,
        }


def _selftest() -> int:
    """Regression for full Set-Cookie capture (dict() used to drop duplicate
    Set-Cookie -> the ASP.NET Core antiforgery flow broke) + --save. Local-only."""
    import http.server
    import io
    import re as _re
    import socketserver
    import tempfile
    import threading
    from unittest import mock

    checks: list[tuple[str, bool]] = []
    redirect = _PrivacyRedirect()
    original = urllib.request.Request(
        "https://a.example.test/start",
        headers={"Cookie": "session=secret", "Authorization": "Bearer secret", "X-Test": "ok"},
    )
    cross = redirect.redirect_request(
        original, None, 302, "Found", {}, "https://b.example.test/next"
    )
    cross_headers = {**cross.unredirected_hdrs, **cross.headers} if cross else {}
    checks.append(("cross-origin redirect strips Cookie/Authorization",
                   cross is not None
                   and not any(k.lower() in privacymod.AUTH_HEADER_NAMES for k in cross_headers)
                   and cross_headers.get("X-test") == "ok"))
    same = redirect.redirect_request(
        original, None, 302, "Found", {}, "https://a.example.test/next"
    )
    same_headers = {**same.unredirected_hdrs, **same.headers} if same else {}
    checks.append(("same-origin redirect preserves required auth",
                   same is not None
                   and any(k.lower() == "cookie" for k in same_headers)
                   and any(k.lower() == "authorization" for k in same_headers)))
    second_cross = redirect.redirect_request(
        cross, None, 302, "Found", {}, "https://c.example.test/final"
    ) if cross else None
    second_headers = ({**second_cross.unredirected_hdrs, **second_cross.headers}
                      if second_cross else {})
    checks.append(("multi-hop redirects cannot regain stripped auth",
                   second_cross is not None
                   and not any(k.lower() in privacymod.AUTH_HEADER_NAMES for k in second_headers)))
    try:
        redirect.redirect_request(
            original, None, 302, "Found", {}, "https://b.example.test/?marker=xunji-proof"
        )
        checks.append(("redirect target privacy is revalidated", False))
    except OutboundPrivacyError:
        checks.append(("redirect target privacy is revalidated", True))
    with selftest_isolation():
        class H(http.server.BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def do_GET(self):
                if self.path.startswith("/csrf"):
                    b = (b'<form><input type="hidden" name="__RequestVerificationToken" '
                         b'value="TOKEN123"></form>')
                    self.send_response(200)
                    self.send_header("Content-Type", "text/html")
                    self.send_header("Set-Cookie", "csrf_session=ABC; path=/; httponly")
                    self.send_header("Set-Cookie", "stale_session=; max-age=0; path=/")
                    self.send_header(
                        "Set-Cookie",
                        "expired_session=STALE; expires=Thu, 01 Jan 1970 00:00:00 GMT; path=/",
                    )
                    self.send_header("Content-Length", str(len(b)))
                    self.end_headers()
                    self.wfile.write(b)
                    return
                if self.path.startswith("/large"):
                    b = b"L" * (guardmod.MAX_BODY_BYTES + 17)
                    self.send_response(200)
                    self.send_header("Content-Type", "text/plain")
                    self.send_header("Content-Length", str(len(b)))
                    self.end_headers()
                    self.wfile.write(b)
                    return
                if self.path.startswith("/length-short"):
                    b = b"short"
                    self.send_response(200)
                    self.send_header("Content-Type", "text/plain")
                    self.send_header("Content-Length", "10")
                    self.end_headers()
                    self.wfile.write(b)
                    self.close_connection = True
                    return
                if self.path.startswith("/length-duplicate"):
                    b = b"hello"
                    self.send_response(200)
                    self.send_header("Content-Type", "text/plain")
                    self.send_header("Content-Length", str(len(b)))
                    self.send_header("Content-Length", str(len(b)))
                    self.end_headers()
                    self.wfile.write(b)
                    return
                if self.path.startswith("/range-ignored"):
                    b = b"0123456789"
                    self.send_response(200)
                    self.send_header("Content-Type", "text/plain")
                    self.send_header("Content-Length", str(len(b)))
                    self.end_headers()
                    self.wfile.write(b)
                    return
                if self.path.startswith("/range-wrong"):
                    b = b"1234"
                    self.send_response(206)
                    self.send_header("Content-Type", "text/plain")
                    self.send_header("Content-Range", "bytes 1-4/10")
                    self.send_header("Content-Length", str(len(b)))
                    self.end_headers()
                    self.wfile.write(b)
                    return
                if self.path.startswith("/range-short"):
                    b = b"234"
                    self.send_response(206)
                    self.send_header("Content-Type", "text/plain")
                    self.send_header("Content-Range", "bytes 2-4/10")
                    self.send_header("Content-Length", str(len(b)))
                    self.end_headers()
                    self.wfile.write(b)
                    return
                if self.path.startswith("/range-clipped"):
                    b = b"0123456789"
                    if self.headers.get("Range") == "bytes=2-99":
                        part = b[2:]
                        self.send_response(206)
                        self.send_header("Content-Type", "text/plain")
                        self.send_header("Content-Range", "bytes 2-9/10")
                        self.send_header("Content-Length", str(len(part)))
                        self.end_headers()
                        self.wfile.write(part)
                        return
                if self.path.startswith("/range"):
                    b = b"0123456789"
                    if self.headers.get("Range") == "bytes=2-5":
                        part = b[2:6]
                        self.send_response(206)
                        self.send_header("Content-Type", "text/plain")
                        self.send_header("Content-Range", "bytes 2-5/10")
                        self.send_header("Content-Length", str(len(part)))
                        self.end_headers()
                        self.wfile.write(part)
                        return
                    self.send_response(200)
                    self.send_header("Content-Type", "text/plain")
                    self.send_header("Content-Length", str(len(b)))
                    self.end_headers()
                    self.wfile.write(b)
                    return
                if self.path.startswith("/redir"):
                    # 模拟登录成功: 302 跳转, 会话 cookie 设在【这一跳】上(跟随跳转会丢失它)
                    self.send_response(302)
                    self.send_header("Location", "/")
                    self.send_header("Set-Cookie", ".AspNet.ApplicationCookie=AUTH_TOKEN_XYZ; path=/; httponly")
                    self.send_header("Content-Length", "0")
                    self.end_headers()
                    return
                if self.path.startswith("/privacy-response"):
                    b = b'{"token":"response-secret","email":"person@real.example.cn"}'
                    self.send_response(200)
                    self.send_header("Content-Type", "application/json")
                    self.send_header("Content-Length", str(len(b)))
                    self.end_headers()
                    self.wfile.write(b)
                    return
                b = b"ok-body"
                self.send_response(200)
                self.send_header("Content-Type", "text/html")
                # two distinct Set-Cookie headers, like ASP.NET Core (cleared external + antiforgery)
                self.send_header("Set-Cookie", "Identity.External=; expires=Thu, 01 Jan 1970 00:00:00 GMT; path=/; httponly")
                self.send_header("Set-Cookie", ".AspNetCore.Antiforgery.abc=CfDJ8_TOKEN; path=/; samesite=strict; httponly")
                self.send_header("Content-Length", str(len(b)))
                self.end_headers()
                self.wfile.write(b)

            def do_POST(self):
                length = int(self.headers.get("Content-Length") or 0)
                body = self.rfile.read(length).decode("utf-8", "replace")
                cookie = self.headers.get("Cookie") or ""
                ok = "__RequestVerificationToken=TOKEN123" in body and "csrf_session=ABC" in cookie
                self.send_response(200 if ok else 403)
                self.send_header("Content-Type", "text/plain")
                self.end_headers()
                self.wfile.write(b"csrf-ok" if ok else b"csrf-bad")

        srv = socketserver.TCPServer(("127.0.0.1", 0), H)
        port = srv.server_address[1]
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        try:
            tmp = Path(tempfile.mkdtemp()) / "body.html"
            d = send("GET", f"http://127.0.0.1:{port}/", {"Cookie": "sess=secret123"}, None, None, 5,
                     save=str(tmp), want_headers=True)
            sc = d.get("headers", {}).get("Set-Cookie", "")
            cl = d.get("set_cookies", [])
            checks.append(("status 200", d.get("status") == 200))
            checks.append(("both Set-Cookie captured (set_cookies list)", len(cl) == 2))
            checks.append(("Identity.External present in headers", "Identity.External" in sc))
            checks.append(("antiforgery cookie regex-extractable",
                           bool(_re.search(r"\.AspNetCore\.Antiforgery\.[^=]+=[^;]+", sc))))
            checks.append(("--save wrote the body", tmp.is_file() and tmp.read_bytes() == b"ok-body"))
            checks.append(("len/sha1 summarized", d.get("len") == 7 and bool(d.get("sha1"))))
            checks.append(("Content-Type lookup is case-insensitive",
                           d.get("ctype") == "text/html"))
            checks.append(("text response keeps a readable snippet",
                           d.get("snippet") == "ok-body"
                           and "snippet_encoding" not in d))
            checks.append(("probe exposes credential-free egress route",
                           d.get("egress_route") == "direct"))
            # 操作录像: --save 同时写 <file>.replay.json(追加扩展名, 非 with_suffix)
            rp = Path(str(tmp) + ".replay.json")
            checks.append(("--save 写了 <file>.replay.json(追加不替换扩展名)", rp.is_file()))
            checks.append(("文件名是 body.html.replay.json(非 body.replay.json, 防同 stem 覆盖)",
                           rp.name == "body.html.replay.json"))
            if rp.is_file():
                rj = json.loads(rp.read_text(encoding="utf-8"))
                hreq = json.dumps(rj["request"]["headers"])
                hresp = json.dumps(rj["response"]["headers"])
                checks.append(("replay 含请求 method/url",
                               rj["request"]["method"] == "GET" and rj["request"]["url"].startswith("http")))
                checks.append(("replay 含响应 status/全sha1",
                               rj["response"]["status"] == 200 and len(rj["response"]["sha1"]) >= 40))
                checks.append(("replay v2 separates wire and saved-body integrity",
                               rj.get("schema") == "xunji.probe.replay.v2"
                               and rj["response"].get("wire_len") == 7
                               and rj["response"].get("wire_sha1")
                                   == hashlib.sha1(b"ok-body").hexdigest()
                               and rj.get("saved_body_meta") == {
                                   "len": 7,
                                   "sha1": hashlib.sha1(b"ok-body").hexdigest(),
                                   "truncated": False,
                               }))
                checks.append(("replay preserves case-insensitive Content-Type",
                               rj["response"].get("ctype") == "text/html"))
                checks.append(("summary.sha1 == replay.sha1 前缀(截断一致)",
                               d.get("sha1") == rj["response"]["sha1"][:12]))
                checks.append(("replay 请求 Cookie 已脱敏且原值不落盘",
                               "<redacted:header:" in hreq and "sess=secret123" not in hreq))
                checks.append(("replay 响应 Set-Cookie 已脱敏",
                               "<redacted:header:" in hresp and "Identity.External=" not in hresp))
                checks.append(("含认证脱敏的 replay 标为不可重放",
                               rj.get("privacy", {}).get("replayable") is False))
                checks.append(("summary 引用 replay 路径", bool(d.get("replay"))))
            private_response = Path(tempfile.mkdtemp()) / "response.json"
            send("GET", f"http://127.0.0.1:{port}/privacy-response", {}, None, None, 5,
                 save=str(private_response))
            private_replay = Path(str(private_response) + ".replay.json")
            if private_replay.is_file():
                private_record = private_replay.read_text(encoding="utf-8")
                checks.append(("replay response snippet redacts returned secret and PII",
                               "response-secret" not in private_record
                               and "person@real.example.cn" not in private_record
                               and "response.body" in private_record))
            else:
                checks.append(("replay response snippet redacts returned secret and PII", False))
            diff_base = Path(tempfile.mkdtemp()) / "boolean.html"
            diff_b = Path(_diff_side_save(str(diff_base), "b"))
            da = send("GET", f"http://127.0.0.1:{port}/?v=true", {}, None, None, 5,
                      save=_diff_side_save(str(diff_base), "a"))
            db = send("GET", f"http://127.0.0.1:{port}/?v=false", {}, None, None, 5,
                      save=str(diff_b))
            checks.append(("DIFF save naming preserves A base and writes distinct B body",
                           diff_base.is_file() and diff_b.is_file()
                           and diff_b.name == "boolean.b.html"))
            checks.append(("DIFF saves replay for both comparison sides",
                           Path(str(diff_base) + ".replay.json").is_file()
                           and Path(str(diff_b) + ".replay.json").is_file()
                           and da.get("replay") and db.get("replay")))
            no_suffix_base = Path(tempfile.mkdtemp()) / "boolean"
            no_suffix_b = Path(_diff_side_save(str(no_suffix_base), "b"))
            send("GET", f"http://127.0.0.1:{port}/?plain=a", {}, None, None, 5,
                 save=str(no_suffix_base))
            send("GET", f"http://127.0.0.1:{port}/?plain=b", {}, None, None, 5,
                 save=str(no_suffix_b))
            checks.append(("DIFF explicit no-suffix paths keep distinct A/B replay files",
                           no_suffix_b.name == "boolean.b"
                           and Path(str(no_suffix_base) + ".replay.json").is_file()
                           and Path(str(no_suffix_b) + ".replay.json").is_file()
                           and str(no_suffix_base) != str(no_suffix_b)))
            large = Path(tempfile.mkdtemp()) / "large.txt"
            dl = send("GET", f"http://127.0.0.1:{port}/large", {}, None, None, 5,
                      save=str(large), save_chunks=True)
            manifest = Path(str(large) + ".chunks.json")
            manifest_data = json.loads(manifest.read_text(encoding="utf-8")) if manifest.exists() else {}
            checks.append(("--save-chunks keeps normal saved body capped",
                           large.is_file() and large.stat().st_size == guardmod.MAX_BODY_BYTES
                           and dl.get("truncated") is True))
            checks.append(("--save-chunks writes manifest with full body metadata",
                           manifest.exists()
                           and manifest_data.get("schema") == "xunji.probe.body_chunks.v2"
                           and manifest_data.get("wire_len") == guardmod.MAX_BODY_BYTES + 17
                           and manifest_data.get("wire_sha1") == hashlib.sha1(
                               b"L" * (guardmod.MAX_BODY_BYTES + 17)).hexdigest()
                           and manifest_data.get("wire_sha256") == hashlib.sha256(
                               b"L" * (guardmod.MAX_BODY_BYTES + 17)).hexdigest()
                           and manifest_data.get("saved_body") == large.name
                           and all(not Path(item.get("path", "")).is_absolute()
                                   and len(item.get("sha256", "")) == 64
                                   for item in manifest_data.get("chunks", []))
                           and dl.get("chunk_manifest") == str(manifest)))
            large_replay = json.loads(
                Path(str(large) + ".replay.json").read_text(encoding="utf-8"))
            checks.append(("large replay binds capped saved bytes separately from wire bytes",
                           large_replay.get("saved_body_meta", {}).get("len")
                               == guardmod.MAX_BODY_BYTES
                           and large_replay.get("saved_body_meta", {}).get("truncated") is True
                           and large_replay.get("saved_body_meta", {}).get("sha1")
                               == hashlib.sha1(
                                   b"L" * guardmod.MAX_BODY_BYTES).hexdigest()
                           and large_replay.get("response", {}).get("wire_len")
                               == guardmod.MAX_BODY_BYTES + 17))
            # 认证流: --no-redirect 不跟随 302, 捕获【跳转那一跳】的 Set-Cookie(会话 cookie)
            nr = send("GET", f"http://127.0.0.1:{port}/redir", {}, None, None, 5,
                      want_headers=True, no_redirect=True)
            nr_sc = "\n".join(nr.get("set_cookies", []))
            checks.append(("--no-redirect 拿到 302(不跟随)", nr.get("status") == 302))
            checks.append(("--no-redirect 捕获跳转上的会话 cookie",
                           ".AspNet.ApplicationCookie=AUTH_TOKEN_XYZ" in nr_sc))
            checks.append(("--no-redirect 响应头含 Location", nr.get("headers", {}).get("Location", "") == "/"))
            # 对照: 默认跟随到 200, 会话 cookie 丢失(证明 --no-redirect 对认证流是必要的)
            fr = send("GET", f"http://127.0.0.1:{port}/redir", {}, None, None, 5, want_headers=True)
            checks.append(("默认跟随 -> 200 且会话 cookie 丢(故认证流需 --no-redirect)",
                           fr.get("status") == 200 and "ApplicationCookie" not in "\n".join(fr.get("set_cookies", []))))
            rr = send("GET", f"http://127.0.0.1:{port}/range", {}, None, None, 5,
                      want_headers=True, byte_range="2-5")
            checks.append(("--range sends Range header and receives partial body",
                           rr.get("status") == 206 and rr.get("snippet") == "2345"
                           and rr.get("headers", {}).get("Content-Range") == "bytes 2-5/10"
                           and rr.get("range") == "bytes=2-5"))
            rr2 = send("GET", f"http://127.0.0.1:{port}/range", {"range": "bytes=2-5"},
                       None, None, 5, want_headers=True, byte_range="0-1")
            checks.append(("--range respects caller-supplied Range header casing",
                           rr2.get("status") == 206 and rr2.get("snippet") == "2345"
                           and rr2.get("range") == "bytes=2-5"))
            range_ignored = send(
                "GET", f"http://127.0.0.1:{port}/range-ignored", {}, None,
                None, 5, byte_range="2-5")
            checks.append(("ignored Range fails with a typed error before body capture",
                           range_ignored.get("error_code") == E_RANGE_NOT_HONORED
                           and range_ignored.get("status") == 200))
            range_wrong = send(
                "GET", f"http://127.0.0.1:{port}/range-wrong", {}, None,
                None, 5, byte_range="2-5")
            checks.append(("mismatched Content-Range fails with the same typed error",
                           range_wrong.get("error_code") == E_RANGE_NOT_HONORED
                           and range_wrong.get("status") == 206))
            range_short = send(
                "GET", f"http://127.0.0.1:{port}/range-short", {}, None,
                None, 5, byte_range="2-5")
            checks.append(("shorter-than-requested Content-Range fails closed",
                           range_short.get("error_code") == E_RANGE_NOT_HONORED
                           and range_short.get("status") == 206))
            range_clipped = send(
                "GET", f"http://127.0.0.1:{port}/range-clipped", {}, None,
                None, 5, byte_range="2-99")
            checks.append(("RFC-valid final range clipping at EOF is accepted",
                           range_clipped.get("status") == 206
                           and range_clipped.get("len") == 8
                           and range_clipped.get("snippet") == "23456789"))
            checks.append(("capture contract errors are not target policy blocks",
                           range_ignored.get("capture_error") is True
                           and range_ignored.get("blocked_by_policy") is False))
            checks.append(("declared response length mismatch is typed",
                           bool(_content_length_error(
                               {"Content-Length": "10"}, body_len=5,
                               method="GET", status=200))
                           and not _content_length_error(
                               {"Content-Length": "10"}, body_len=0,
                               method="HEAD", status=200)))
            early_eof = send(
                "GET", f"http://127.0.0.1:{port}/length-short", {}, None,
                None, 5)
            checks.append(("early EOF is a typed capture error, not target blocking",
                           early_eof.get("error_code")
                           == E_RESPONSE_LENGTH_MISMATCH
                           and early_eof.get("capture_error") is True
                           and early_eof.get("blocked_by_policy") is False))
            duplicate_length = send(
                "GET", f"http://127.0.0.1:{port}/length-duplicate", {}, None,
                None, 5)
            checks.append(("duplicate Content-Length fails with typed framing error",
                           duplicate_length.get("error_code")
                           == E_RESPONSE_FRAMING_INVALID
                           and duplicate_length.get("capture_error") is True
                           and duplicate_length.get("blocked_by_policy") is False))
            bounded_stream = _read_response_stream(
                io.BytesIO(b"B" * (guardmod.MAX_BODY_BYTES + 9)),
                save_chunks=False, chunk_size=guardmod.MAX_BODY_BYTES)
            checks.append(("streaming keeps only the normal 256KiB body cap",
                           len(bounded_stream[0]) == guardmod.MAX_BODY_BYTES
                           and bounded_stream[1] == guardmod.MAX_BODY_BYTES + 9
                           and bounded_stream[4] is None))
            try:
                _read_response_stream(
                    io.BytesIO(b"C" * (MAX_CHUNK_CAPTURE_BYTES + 1)),
                    save_chunks=True, chunk_size=guardmod.MAX_BODY_BYTES)
                chunk_limit_typed = False
            except ProbeCaptureError as exc:
                chunk_limit_typed = exc.code == E_CHUNK_LIMIT
            checks.append(("explicit chunk capture has a typed total-byte hard limit",
                           chunk_limit_typed))
            competing = Path(tempfile.mkdtemp()) / "competing.bin"
            competing.write_bytes(b"competitor")
            try:
                _publish_bytes_noclobber(competing, b"probe")
                no_clobber = False
            except FileExistsError:
                no_clobber = competing.read_bytes() == b"competitor"
            checks.append(("artifact publication never replaces a competing file",
                           no_clobber))
            interrupted_save = Path(tempfile.mkdtemp()) / "interrupted.html"
            original_publish = _publish_bytes_noclobber
            publish_calls = 0

            def interrupt_second_publish(path: Path, data: bytes) -> None:
                nonlocal publish_calls
                publish_calls += 1
                if publish_calls == 2:
                    raise KeyboardInterrupt
                original_publish(path, data)

            interrupted = False
            try:
                with mock.patch(
                        __name__ + "._publish_bytes_noclobber",
                        side_effect=interrupt_second_publish):
                    send(
                        "GET", f"http://127.0.0.1:{port}/", {}, None,
                        None, 5, save=str(interrupted_save))
            except KeyboardInterrupt:
                interrupted = True
            checks.append(("KeyboardInterrupt cleans a partially published save group",
                           interrupted and not interrupted_save.exists()
                           and not Path(
                               str(interrupted_save) + ".replay.json").exists()))
            reserved = Path(tempfile.mkdtemp()) / "reserved.bin"
            with _artifact_output_reservation(str(reserved)):
                try:
                    with _artifact_output_reservation(str(reserved)):
                        pass
                    reservation_exclusive = False
                except FileExistsError:
                    reservation_exclusive = True
            checks.append(("save group is reserved before target I/O",
                           reservation_exclusive))
            with mock.patch(__name__ + ".send", return_value={"sha1": "a"}) as mocked:
                _diff_samples(
                    "https://example.test/a", str(reserved), samples=1,
                    headers={}, auth_key=None, timeout=5, retry=0,
                    retry_wait=0.0, want_headers=False, no_redirect=True,
                    byte_range="0-3", save_chunks=True, chunk_size=4096,
                    allow_sensitive_auth=False, allow_legacy_cleanup=True,
                )
            diff_args = mocked.call_args.args if mocked.call_args else ()
            checks.append(("DIFF forwards chunk/range/redirect flags to each side",
                           len(diff_args) >= 16
                           and diff_args[10] is True
                           and diff_args[11] == "0-3"
                           and diff_args[12] is True
                           and diff_args[13] == 4096
                           and diff_args[15] is True))
            jar = Path(tempfile.mkdtemp()) / "cookies.json"
            _save_cookie_jar(str(jar), {
                "csrf_session": "JAR_OLD",
                "stale_session": "OLD",
                "expired_session": "OLD",
            })
            chain_args = argparse.Namespace(
                preflight_get=f"http://127.0.0.1:{port}/csrf",
                preflight_save=None,
                extract_csrf=r'name="__RequestVerificationToken"\s+value="([^"]+)"',
                csrf_field="__RequestVerificationToken",
                cookie_jar=str(jar),
                timeout=5,
                retry=0,
                retry_wait=1.5,
                no_redirect=False,
            )
            ch_headers, ch_data, ch_json, ch_meta = _apply_preflight(
                chain_args,
                {"Cookie": "csrf_session=EXPLICIT_OLD; explicit_only=KEEP"},
                b"u=a",
                False,
            )
            csrf_post = send("POST", f"http://127.0.0.1:{port}/submit",
                             ch_headers, ch_data, None, 5)
            jar_data = json.loads(jar.read_text(encoding="utf-8")) if jar.exists() else {}
            checks.append(("--preflight-get extracts csrf token",
                           ch_data is not None and b"__RequestVerificationToken=TOKEN123" in ch_data
                           and ch_meta.get("csrf_extracted") is True and ch_json is False))
            checks.append(("--preflight-get merges Set-Cookie into final request",
                           "csrf_session=ABC" in ch_headers.get("Cookie", "")
                           and "explicit_only=KEEP" in ch_headers.get("Cookie", "")
                           and "stale_session=" not in ch_headers.get("Cookie", "")
                           and "expired_session=" not in ch_headers.get("Cookie", "")
                           and jar_data.get("csrf_session") == "ABC"
                           and "stale_session" not in jar_data
                           and "expired_session" not in jar_data))
            checks.append(("cookie jar is owner-only",
                           jar.exists() and (jar.stat().st_mode & 0o077) == 0))
            checks.append(("preflight chained POST succeeds", csrf_post.get("status") == 200))

            # Exhausted retries must be attributed structurally and counted as
            # three real attempts (not one wrapper call, and not four warnings).
            import socket as _socket
            unused = _socket.socket()
            unused.bind(("127.0.0.1", 0))
            unused_port = unused.getsockname()[1]
            unused.close()
            totals_before = HostHealth().snapshot()["totals"].get(
                guardmod._total_key("direct", "127.0.0.1"), {}).get("count", 0)
            failed = send("GET", f"http://127.0.0.1:{unused_port}/", {}, None, None, 1,
                          retry=2, retry_wait=0)
            totals_after = HostHealth().snapshot()["totals"][
                guardmod._total_key("direct", "127.0.0.1")]["count"]
            checks.append(("transport failure exposes route/error attribution",
                           failed.get("egress_route") == "direct"
                           and failed.get("error_class") == "target_reset"
                           and failed.get("attribution") == "target"
                           and failed.get("breaker_scope") == "target"))
            checks.append(("retry wrapper records exact real request count",
                           failed.get("attempts") == 3 and totals_after - totals_before == 3))
            globals()["_PROXY"] = f"http://127.0.0.1:{unused_port}"
            proxy_failed = send(
                "GET", f"http://127.0.0.1:{port}/", {}, None, None, 1,
                retry=2, retry_wait=0)
            globals()["_PROXY"] = None
            checks.append(("proxy failure stops automatic retry pending operator confirmation",
                           proxy_failed.get("egress_route", "").startswith("proxy:http:")
                           and proxy_failed.get("attribution") == "proxy"
                           and proxy_failed.get("attempts") == 1
                           and proxy_failed.get("automatic_retry_stopped") is True
                           and proxy_failed.get("restart_policy")
                           == "operator_confirmation_required"))
        finally:
            srv.shutdown()
    # Output layout: live artifacts stay in run/evidence; standalone saves use
    # one managed invocation directory under repository tmp/.
    ps_bare = _place_save("ev_x.html", "runs/t_20260101", invocation="selftest-a")
    checks.append(("--run + 裸名 -> <run>/evidence/",
                   Path(ps_bare) == output_layout.ROOT / "runs/t_20260101/evidence/ev_x.html"))
    checks.append(("--run + evidence 内显式路径 -> 原样尊重",
                   _place_save("runs/t/evidence/sub/ev.html", "runs/t", invocation="selftest-b")
                   == str(output_layout.ROOT / "runs/t/evidence/sub/ev.html")))
    checks.append(("无 --run -> invocation scratch",
                   _place_save("ev.html", None, invocation="selftest-c")
                   == str(output_layout.ROOT / "tmp" / "probe" / "selftest-c" / "ev.html")))
    outside_rejected = False
    replay_name_rejected = False
    try:
        _place_save("sub/ev.html", "runs/t", invocation="selftest-d")
    except output_layout.OutputLayoutError:
        outside_rejected = True
    try:
        _place_save("ev.replay.json", "runs/t", invocation="selftest-e")
    except output_layout.OutputLayoutError:
        replay_name_rejected = True
    checks.append(("run output outside evidence rejected", outside_rejected))
    checks.append(("replay sidecar name rejected as response body", replay_name_rejected))
    checks.append(("run cookie jar uses state/http rather than evidence",
                   _place_cookie_jar("cookies.json", "runs/t", invocation="selftest-cookie")
                   == str(output_layout.ROOT / "runs/t/state/http/cookies.json")))
    cookie_outside_rejected = False
    try:
        _place_cookie_jar(".state/cookies.json", "runs/t", invocation="selftest-cookie-bad")
    except output_layout.OutputLayoutError:
        cookie_outside_rejected = True
    checks.append(("run cookie jar outside state is rejected", cookie_outside_rejected))
    cookie_headers = {"Cookie": "same=explicit; explicit_only=1"}
    _merge_cookies_into_headers(cookie_headers, {"same": "jar", "jar_only": "1"})
    checks.append(("explicit Cookie overrides loaded jar before preflight",
                   "same=explicit" in cookie_headers["Cookie"]
                   and "jar_only=1" in cookie_headers["Cookie"]))
    malformed_jar = Path(tempfile.mkdtemp()) / "cookies.json"
    malformed_jar.write_text('{"drop": null, "keep": "v"}', encoding="utf-8")
    checks.append(("cookie jar ignores JSON null deletion markers",
                   _load_cookie_jar(str(malformed_jar)) == {"keep": "v"}))
    checks.append(("timezone-less Expires values are interpreted as UTC",
                   not _cookie_expired("Thu, 01 Jan 1970 01:00:00", now=0)
                   and _cookie_expired("Wed, 31 Dec 1969 23:00:00", now=0)))
    # #3: 无扩展名裸名补 .html(dogfood: --save tomcat9 存成裸名, driver 以为 .html 报错)
    checks.append(("--run + 无扩展名裸名 -> 补 .html 落 evidence/",
                   Path(_place_save("tomcat9", "runs/t", invocation="selftest-f"))
                   == output_layout.ROOT / "runs/t/evidence/tomcat9.html"))
    checks.append(("无 --run + 无扩展名 -> scratch + .html",
                   _place_save("foo", None, invocation="selftest-g")
                   == str(output_layout.ROOT / "tmp" / "probe" / "selftest-g" / "foo.html")))
    checks.append(("已带扩展名不重复补",
                   _place_save("a.json", None, invocation="selftest-h")
                   == str(output_layout.ROOT / "tmp" / "probe" / "selftest-h" / "a.json")))
    raw_body_file = Path(tempfile.mkdtemp()) / "body.bin"
    raw_body_file.write_bytes(b"raw=1")
    json_body_file = Path(tempfile.mkdtemp()) / "body.json"
    json_body_file.write_text('{"b": 2, "a": [1, true]}', encoding="utf-8")
    value_body, value_is_json = _request_data_from_args(argparse.Namespace(
        data=None, data_file=None, data_json_file=None,
        value_json='{"FileName":"web.config","Depth":1}', value_json_file=None))
    full_body, full_is_json = _request_data_from_args(argparse.Namespace(
        data=None, data_file=None, data_json_file=str(json_body_file),
        value_json=None, value_json_file=None))
    raw_body, raw_is_json = _request_data_from_args(argparse.Namespace(
        data=None, data_file=str(raw_body_file), data_json_file=None,
        value_json=None, value_json_file=None))
    value_obj = json.loads(value_body.decode("utf-8")) if value_body else {}
    checks.append(("--data-json-file compacts complete JSON body",
                   full_is_json and full_body == b'{"b":2,"a":[1,true]}'))
    checks.append(("--data-file preserves raw bytes and content-type flag",
                   raw_body == b"raw=1" and raw_is_json is False))
    checks.append(("--value-json wraps inner JSON as Value string",
                   value_is_json and isinstance(value_obj.get("Value"), str)
                   and json.loads(value_obj["Value"])["FileName"] == "web.config"))
    try:
        _request_data_from_args(argparse.Namespace(
            data="{}", data_file=None, data_json_file=str(json_body_file),
            value_json=None, value_json_file=None))
        conflict_raised = False
    except ValueError:
        conflict_raised = True
    checks.append(("request body sources are mutually exclusive", conflict_raised))
    try:
        _request_data_from_args(argparse.Namespace(
            data=None, data_file=None, data_json_file=None,
            value_json="{bad-json", value_json_file=None))
        invalid_json_raised = False
    except json.JSONDecodeError:
        invalid_json_raised = True
    checks.append(("invalid --value-json raises JSONDecodeError", invalid_json_raised))
    bad = [n for n, ok in checks if not ok]
    for n, ok in checks:
        print(("ok   " if ok else "FAIL ") + n)
    print("probe selftest " + ("passed" if not bad else f"FAILED ({len(bad)})"))
    return 0 if not bad else 1


def _place_save(
    save: str | None,
    run: str | None,
    *,
    invocation: str | None = None,
) -> str | None:
    """Resolve a response body path without ever falling back to the CWD."""
    path = output_layout.resolve_artifact_file(
        save,
        run=run,
        tool="probe",
        invocation=invocation,
        default_suffix=".html",
    )
    return str(path) if path is not None else None


def _place_cookie_jar(
    value: str | None,
    run: str | None,
    *,
    invocation: str | None = None,
) -> str | None:
    path = output_layout.resolve_run_state_file(
        value,
        run=run,
        tool="probe",
        invocation=invocation,
        default_leaf="http",
    )
    return str(path) if path is not None else None


def _diff_side_save(base: str | None, side: str) -> str | None:
    if not base or side == "a":
        return base
    path = Path(base)
    if path.suffix:
        return str(path.with_name(path.stem + f".{side}" + path.suffix))
    return str(path.with_name(path.name + f".{side}"))


def _diff_samples(
    url: str,
    save: str | None,
    *,
    samples: int,
    headers: dict,
    auth_key: str | None,
    timeout: int,
    retry: int,
    retry_wait: float,
    want_headers: bool,
    no_redirect: bool,
    byte_range: str | None,
    save_chunks: bool,
    chunk_size: int,
    allow_sensitive_auth: bool,
    allow_legacy_cleanup: bool,
) -> tuple[dict, bool, list]:
    runs = [send(
        "GET", url, headers, None, auth_key, timeout,
        save if index == 0 else None,
        retry, retry_wait, want_headers, no_redirect, byte_range, save_chunks,
        chunk_size, allow_sensitive_auth, allow_legacy_cleanup,
    ) for index in range(samples)]
    hashes = sorted({row.get("sha1") for row in runs})
    return runs[0], len(hashes) == 1, hashes


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("method", nargs="?", help="GET/POST/PUT/... or DIFF for a two-URL comparison")
    ap.add_argument("url", nargs="?")
    ap.add_argument("url2", nargs="?", help="second URL for DIFF mode")
    ap.add_argument("--selftest", action="store_true", help="run regression and exit")
    ap.add_argument("--data", default=None)
    ap.add_argument("--data-file", default=None,
                    help="raw request body from file; does not auto-set Content-Type")
    ap.add_argument("--data-json-file", default=None,
                    help="read a complete JSON request body from file and compact it before sending")
    ap.add_argument("--value-json", default=None,
                    help="wrap JSON as an escaped string Value field: {\"Value\":\"<compact-json>\"}")
    ap.add_argument("--value-json-file", default=None,
                    help="like --value-json, but read the inner JSON from a file")
    ap.add_argument("--preflight-get", default=None,
                    help="GET this page first, then merge Set-Cookie values into the final request")
    ap.add_argument("--preflight-save", default=None,
                    help="save the preflight response body and replay for evidence/token inspection")
    ap.add_argument("--extract-csrf", default=None,
                    help="regex applied to the preflight body; group 1 or named group 'value' is injected")
    ap.add_argument("--csrf-field", default="__RequestVerificationToken",
                    help="form/JSON field name for --extract-csrf")
    ap.add_argument("--cookie-jar", default=None,
                    help="JSON cookie jar to load/update; basename -> <run>/state/http/ "
                         "or standalone tmp/<tool>/<invocation>/")
    ap.add_argument("-H", "--header", action="append", default=[], help="k: v")
    ap.add_argument("--auth-key", default=None,
                    help="endpoint key for the brute-force lock counter")
    ap.add_argument("--allow-sensitive-auth", action="store_true",
                    help="explicit exception for personal data required in an authentication body; "
                         "internal project/local identity markers remain blocked and replay evidence is redacted")
    ap.add_argument("--allow-legacy-cleanup", action="store_true",
                    help="allow only a legacy xunji_* proof-artifact reference during an operator-approved cleanup; "
                         "the safety hook still requires explicit yes")
    ap.add_argument("--timeout", type=int, default=20)
    ap.add_argument("--tag", default=None, help="label recorded with the result")
    ap.add_argument("--save", default=None,
                    help="write the guard-capped response body to this file")
    ap.add_argument("--run", default=None,
                    help="run 目录 runs/<dir>; 给了它且 --save 是裸文件名时, 产物落到 "
                         "<run>/evidence/(统一布局, 防散落根目录; 录像 .replay.json 一并跟随)")
    ap.add_argument("--proxy", default=None,
                    help="显式交战代理(http://h:p / socks5h://h:p)；未给时默认直连。"
                         "只有 XUNJI_PROXY_REQUIRED=1 才读取 XUNJI_PROXY / proxy.conf；"
                         "不读 HTTPS_PROXY=模型通道")
    ap.add_argument("--retry", type=int, default=0,
                    help="超时/RST 重试次数(瞬时不可达时用)")
    ap.add_argument("--retry-wait", type=float, default=1.5, help="重试间隔秒")
    ap.add_argument("--headers", action="store_true",
                    help="输出完整响应头(Location/Set-Cookie 等)")
    ap.add_argument("--no-redirect", action="store_true",
                    help="不跟随 3xx 跳转 —— 直接拿 302 那一跳(认证流会话 cookie 设在跳转上, 跟随会丢; "
                         "也防被跳转带到 scope 外)")
    ap.add_argument("--range", dest="byte_range", default=None,
                    help="HTTP byte range helper, e.g. 0-262143 or bytes=0-262143. "
                         "Adds a Range header unless one was supplied explicitly.")
    ap.add_argument("--save-chunks", action="store_true",
                    help="with --save, also write a bounded response stream into <save>.chunks/ "
                         "plus a v2 relative-path/SHA-256 manifest (hard cap: 8 MiB and 128 "
                         "parts). The normal saved body remains guard-capped at 256 KiB.")
    ap.add_argument("--chunk-size", type=int, default=guardmod.MAX_BODY_BYTES,
                    help="bytes per --save-chunks part (default: guard cap size)")
    ap.add_argument("--samples", type=int, default=1,
                    help="DIFF 模式每侧采样次数；>1 时做稳定性判定(去噪)")
    args = ap.parse_args()

    if args.selftest:
        return _selftest()
    if not args.method or not args.url:
        ap.error("method and url are required (or use --selftest)")

    artifact_invocation = output_layout.invocation_id()
    try:
        args.save = _place_save(
            args.save, args.run, invocation=artifact_invocation)
        args.preflight_save = _place_save(
            args.preflight_save, args.run, invocation=artifact_invocation)
        args.cookie_jar = _place_cookie_jar(
            args.cookie_jar, args.run, invocation=artifact_invocation)
    except output_layout.OutputLayoutError as exc:
        ap.error(str(exc))

    global _PROXY
    _PROXY = args.proxy   # --proxy 显式选代理；否则 proxy.resolve 按 required=0/1 冻结 direct/proxy

    headers = {}
    for h in args.header:
        if ":" in h:
            k, v = h.split(":", 1)
            headers[k.strip()] = v.strip()
    try:
        data, json_body = _request_data_from_args(args)
    except json.JSONDecodeError as e:
        ap.error(f"invalid JSON request body: {e.msg} at line {e.lineno} column {e.colno}")
    except (OSError, ValueError) as e:
        ap.error(str(e))
    if data and json_body and "Content-Type" not in headers:
        headers["Content-Type"] = "application/json"
    try:
        headers, data, json_body, preflight_meta = _apply_preflight(args, headers, data, json_body)
    except json.JSONDecodeError as e:
        ap.error(f"invalid JSON request body after CSRF injection: {e.msg} at line {e.lineno} column {e.colno}")
    except (OSError, ValueError) as e:
        ap.error(str(e))

    try:
        if args.method.upper() == "DIFF":
            if not args.url2:
                print("DIFF needs two URLs", file=sys.stderr)
                return 2
            n = max(1, args.samples)

            def sample(url: str, save: str | None) -> tuple[dict, bool, list]:
                return _diff_samples(
                    url, save, samples=n, headers=headers,
                    auth_key=args.auth_key, timeout=args.timeout,
                    retry=args.retry, retry_wait=args.retry_wait,
                    want_headers=args.headers, no_redirect=args.no_redirect,
                    byte_range=args.byte_range, save_chunks=args.save_chunks,
                    chunk_size=args.chunk_size,
                    allow_sensitive_auth=args.allow_sensitive_auth,
                    allow_legacy_cleanup=args.allow_legacy_cleanup,
                )

            a, a_stable, a_h = sample(args.url, _diff_side_save(args.save, "a"))
            b, b_stable, b_h = sample(args.url2, _diff_side_save(args.save, "b"))
            same_hash = a.get("sha1") == b.get("sha1")
            out = {"tag": args.tag, "mode": "DIFF", "samples": n,
                   "a": a, "b": b,
                   "a_stable": a_stable, "b_stable": b_stable,
                   "same_len": a.get("len") == b.get("len"),
                   "same_hash": same_hash,
                   "same_status": a.get("status") == b.get("status"),
                   # 仅当两侧各自稳定且彼此不同, 才是可信的布尔差异(去噪后)
                   "reliable_differential": bool(a_stable and b_stable
                                                 and not same_hash),
                   "note": "reliable_differential=true(两侧各自稳定且不同)才是"
                           "布尔注入证据；某侧 *_stable=false 说明该响应本身在波动"
                           "(动态内容/多IP负载均衡)，差异不可信，先排噪"}
            if args.save:
                out["artifacts"] = {
                    "a": {"body": a.get("saved"), "replay": a.get("replay")},
                    "b": {"body": b.get("saved"), "replay": b.get("replay")},
                }
            if not a_stable:
                out["a_hashes"] = a_h
            if not b_stable:
                out["b_hashes"] = b_h
        else:
            out = {"tag": args.tag, **send(args.method, args.url, headers,
                                           data, args.auth_key, args.timeout,
                                           args.save, args.retry, args.retry_wait,
                                           args.headers, args.no_redirect,
                                           args.byte_range, args.save_chunks,
                                           args.chunk_size,
                                           args.allow_sensitive_auth,
                                           args.allow_legacy_cleanup)}
            if preflight_meta:
                out["preflight"] = preflight_meta
    except guardmod.GuardStateError as e:
        out = {"error": f"guard-state: {e}", "error_class": "guard_state"}
    except SessionTripped as e:
        out = {"error": f"session-volume-breaker: {e}"}
    except RateBudgetExceeded as e:
        out = {"error": f"rate-limited: {e}"}
    except BruteforceLock as e:
        out = {"error": f"brute-force lock: {e}"}
    except HostBackoff as e:
        out = {"error": f"host-backoff: {e}", **e.provenance()}
    except OutboundPrivacyError as e:
        out = {"error": f"outbound-privacy: {e}"}

    print(json.dumps(out, ensure_ascii=False, indent=2))
    return 0 if "error" not in out else 1


if __name__ == "__main__":
    raise SystemExit(main())
