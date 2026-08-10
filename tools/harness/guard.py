#!/usr/bin/env python3
"""Proof-only verification enforcement guard (shared by all active tools).

This is the machine-enforced floor that makes AI autonomy safe: the active
tools (probe / render / scan) MUST route through these guards. The few hard
limits from src-safety-boundary become code, not prose:

- RateLimiter      -> 禁 DoS/高频  (global + per-host token bucket)
- cap_body         -> 禁拖库/取他人数据 (truncate oversized responses)
- AuthFailCounter  -> 防死循环 (only stops a runaway/infinite auth loop; weak-
                     credential trials are allowed — the harm is SPEED, not count,
                     and RateLimiter is the actual brute-force throttle)
- UploadRegistry   -> 不留后门残留 (every test artifact is tracked for cleanup)

Pure stdlib. State persists under tools/harness/.state/ so limits hold across
separate tool invocations (each Bash call is a fresh process).
"""

from __future__ import annotations

import contextlib
import hashlib
import json
import math
import os
import re
import socket
import ssl
import time
import urllib.error
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlparse

try:
    from . import privacy as privacymod
except ImportError:  # direct execution: python tools/harness/guard.py
    import privacy as privacymod  # type: ignore

try:                       # Windows
    import msvcrt
except ImportError:
    msvcrt = None
try:                       # POSIX
    import fcntl
except ImportError:
    fcntl = None

STATE_DIR = Path(__file__).resolve().parent / ".state"
STATE_DIR.mkdir(parents=True, exist_ok=True)
_LOCK_PATH = STATE_DIR / ".lock"

# --- Hard caps (deliberately conservative; tune in one place only) -----------
GLOBAL_MAX_RPS = 2.0          # 禁高频: global requests/sec ceiling
PER_HOST_MAX_RPS = 1.0        # per-host ceiling
MAX_BODY_BYTES = 256 * 1024   # 禁拖库: refuse to retain bodies bigger than this
AUTH_FAIL_LOCK = 500         # 防死循环天花板(非禁爆破): 弱口令字典随便试, 真正的危害闸是
                             # RateLimiter 的速率(单 host 1 rps); 此值只在 probe 因 bug 陷入无限
                             # 认证循环时兜底停下。爆破可逆 -> 不按"试了几次"限, 按"多快"限。
AUTH_FAIL_PIVOT = 25          # 爆破转向阈值: 同一端点连续失败达此值 -> stderr 警告 "猜测攻击
                             # 不会产生新价值 → 转向逻辑漏洞/配置错误/未授权API"。
                             # (retrospective #4: 500+ 次猜测 0 成功, 应在 20-30 次后切方向)
# --- Self-throttle circuit breaker (防止打爆自己对目标的访问) ------------------
HOST_ERR_THRESHOLD = 3        # 连续传输错误(超时/RST/拒绝)达此值 -> 熔断该 host
HOST_BACKOFF_SEC = 120        # 熔断冷却时长(秒); 期间对该 host 的请求直接抛 HostBackoff
HOST_REQ_WARN = 30           # 单 host 累计请求软告警阈值(只提示, 不阻断)
HOST_MAX_BACKOFF_SEC = 15 * 60
HOST_HALF_OPEN_LEASE_SEC = 15
HOST_BACKOFF_JITTER_RATIO = 0.10
HOST_HEALTH_SCHEMA = "xunji.host-health.v2"
HOST_HEALTH_PROVENANCE_LIMIT = 128

# Error attribution is deliberately finite.  Only the two ``target_*`` classes
# may arm a target-host breaker.  Proxy/local failures arm a route-wide breaker;
# legacy wrappers keep a same-host, unattributed breaker so an old caller remains
# throttled without falsely blaming the target.
HOST_ERROR_POLICIES = {
    "proxy_connect": ("proxy", "route"),
    "proxy_tls": ("proxy", "route"),
    "local_dns": ("local", "route"),
    "target_tls": ("target", "target"),
    "target_reset": ("target", "target"),
    "unattributed_transport": ("unknown", "unattributed_host"),
}

_ROUTE_RE = re.compile(
    r"^(?:direct|legacy|proxy:(?:http|https|socks4|socks4a|socks5|socks5h|unknown):[0-9a-f]{16})$"
)
# --- 全局会话请求预算 (跨 host; ① 是单 host, 这个管整场总量) -------------------
SESSION_WINDOW_SEC = 600      # 滑动窗口(秒)
SESSION_WARN_COUNT = 300      # 窗口内总请求达此值 -> 软告警(整场量偏高, 考虑收敛/换出口)
# --- 全局会话硬熔断 (Part A: 软告警之上的真·工具层熔断, 整场失控时 abort) --------
SESSION_TRIP_COUNT = 2000     # 窗口内总请求达此值 -> 硬熔断(布防冷却, check() 抛 SessionTripped)
                               # (retrospective puffts: 1200 对多服务+JS-heavy 目标偏低 → 调至 2000)
SESSION_TRIP_BYTES = 48 * 1024 * 1024   # 窗口内累计响应字节(截断前线缆量, 非 cap 后保留量)-> 硬熔断(防整场拖量)
                               # (retrospective puffts: 单 chunk 可达 262KB, 62 chunk+响应 需 32MB+)
MIN_STATIC_ASSET_BYTES = 64 * 1024  # JS/CSS 排除下限: 小于此值的静态资源仍计入 bytes budget(防大量小文件绕过)
SESSION_TRIP_COOLDOWN = 300   # 熔断冷却时长(秒); 期间对任何 host 的请求直接 abort


def _now() -> float:
    return time.monotonic()


@contextlib.contextmanager
def _state_lock(max_wait: float = 15.0):
    """Cross-process exclusive lock serializing every guard state read-modify-write.

    Parallel workers each run the active tools as separate processes sharing this
    one `.state/` dir. Without a lock their `_load`->modify->`_save` sequences race
    and lose updates — the global rate ceiling would be violated by N workers at
    once (打爆目标 / 自己的访问). This lock makes the whole fan-out honour ONE global
    limit. Coarse and simple on purpose: guard mutations are sub-millisecond except
    the rate gate's intentional spacing sleep, which SHOULD serialize anyway.
    """
    f = open(_LOCK_PATH, "a+")
    deadline = time.time() + max_wait
    try:
        if msvcrt is not None:
            f.seek(0)
            while True:
                try:
                    msvcrt.locking(f.fileno(), msvcrt.LK_NBLCK, 1)
                    break
                except OSError:
                    if time.time() > deadline:
                        raise RateBudgetExceeded("guard state lock contention >15s; aborting")
                    time.sleep(0.03)
        elif fcntl is not None:
            fcntl.flock(f.fileno(), fcntl.LOCK_EX)
        yield
    finally:
        try:
            if msvcrt is not None:
                f.seek(0)
                msvcrt.locking(f.fileno(), msvcrt.LK_UNLCK, 1)
            elif fcntl is not None:
                fcntl.flock(f.fileno(), fcntl.LOCK_UN)
        finally:
            f.close()


def _load(name: str) -> dict:
    # Reads are consistent without the lock: _save replaces atomically (os.replace),
    # so a reader never sees a torn file — at worst a slightly stale one.
    p = STATE_DIR / name
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _save(name: str, data: dict) -> None:
    p = STATE_DIR / name
    tmp = p.with_name(f"{p.name}.tmp{os.getpid()}")
    tmp.write_text(json.dumps(data), encoding="utf-8")
    os.replace(tmp, p)        # atomic on the same filesystem -> no torn reads


def _update(name: str, mutate) -> None:
    """Atomic read-modify-write under the cross-process lock."""
    with _state_lock():
        data = _load(name)
        mutate(data)
        _save(name, data)


class RateBudgetExceeded(Exception):
    """Raised when a request would exceed the rate ceiling. Tools must abort,
    not sleep-and-retry in a tight loop (that would itself become a flood)."""


class SessionTripped(RateBudgetExceeded):
    """Raised when the WHOLE-session (cross-host) request count or retained-egress
    volume blows past the hard ceiling — the engagement is hammering targets at
    scale (DoS-adjacent runaway). Unlike per-host HostBackoff, this trips on GLOBAL
    volume that single-host breakers can't see. Tools abort for a cooldown instead
    of continuing the flood. Raise SESSION_TRIP_* per run for a legitimately large
    sweep. Subclasses RateBudgetExceeded so existing handlers still catch it."""


class BruteforceLock(Exception):
    """Raised only when probe's auth loop runs away (AUTH_FAIL_LOCK = a high
    anti-infinite-loop ceiling, not a brute-force ban). Weak-credential trials
    are allowed; the real harm of brute-force is SPEED, which RateLimiter caps
    (per-host 1 rps). This counter exists solely so a buggy/unbounded auth loop
    eventually stops — raise AUTH_FAIL_LOCK per run if a dictionary is longer."""


class GuardStateError(RateBudgetExceeded):
    """Guard state or caller metadata cannot be trusted.

    A corrupt/unknown HostHealth schema must never be interpreted as an empty
    breaker file.  Subclassing ``RateBudgetExceeded`` keeps old wrappers
    fail-closed through their existing abort path.
    """


class HostBackoff(Exception):
    """Raised while a target- or route-scoped breaker is open."""

    def __init__(self, message: str, *, egress_route: str = "legacy",
                 host: str = "", error_class: str = "unattributed_transport",
                 attribution: str = "unknown", breaker_scope: str = "unattributed_host",
                 phase: str = "open", retry_after: float = 0.0):
        super().__init__(message)
        self.egress_route = egress_route
        self.host = host
        self.error_class = error_class
        self.attribution = attribution
        self.breaker_scope = breaker_scope
        self.phase = phase
        self.retry_after = max(float(retry_after), 0.0)

    def provenance(self) -> dict:
        return {
            "egress_route": self.egress_route,
            "host": self.host,
            "error_class": self.error_class,
            "attribution": self.attribution,
            "breaker_scope": self.breaker_scope,
            "phase": self.phase,
            "retry_after_seconds": round(self.retry_after, 3),
        }


@dataclass(frozen=True)
class HostHealthLease:
    """One cross-process half-open trial covering one or more matching breakers."""

    egress_route: str
    host: str
    token: str
    breaker_keys: tuple[str, ...]
    expires_at: float


_HOST_HEALTH_TOP_FIELDS = frozenset({"schema", "breakers", "totals", "provenance"})
_HOST_HEALTH_BREAKER_FIELDS = frozenset({
    "egress_route", "host", "error_class", "attribution", "scope",
    "consecutive", "total_errors", "opens", "phase", "until",
    "lease_token", "lease_owner", "lease_until", "updated_at",
    "backoff_seconds",
})
_HOST_HEALTH_TOTAL_FIELDS = frozenset({"egress_route", "host", "count"})
_HOST_HEALTH_PROVENANCE_FIELDS = frozenset({
    "event_id", "ts", "event", "egress_route", "host", "observed_host",
    "error_class", "attribution", "scope", "count", "consecutive",
    "until", "lease_until",
})


def _finite_number(value, field: str, *, minimum: float = 0.0) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise GuardStateError(f"host health field {field!r} must be numeric")
    out = float(value)
    if not math.isfinite(out) or out < minimum:
        raise GuardStateError(f"host health field {field!r} is out of range")
    return out


def _counter(value, field: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise GuardStateError(f"host health field {field!r} must be a non-negative integer")
    return value


def _normalize_host(host: str) -> str:
    if not isinstance(host, str) or not host or len(host) > 253:
        raise GuardStateError("host health requires a non-empty bounded host")
    if any(ord(ch) < 33 or ch.isspace() for ch in host):
        raise GuardStateError("host health host contains unsafe characters")
    value = host.strip(".").lower()
    try:
        value = value.encode("idna").decode("ascii")
    except UnicodeError as exc:
        raise GuardStateError("host health host is not valid IDNA") from exc
    if not value or len(value) > 253:
        raise GuardStateError("host health host is empty or too long")
    return value


def egress_route_id(proxy_url: str | None) -> str:
    """Return a credential-free stable route ID for direct/proxied egress.

    Proxy endpoint material is represented only by a short SHA-256 digest, so
    guard state/provenance never persists credentials or an internal proxy host.
    """
    if not proxy_url:
        return "direct"
    try:
        parsed = urlparse(proxy_url)
        scheme = (parsed.scheme or "unknown").lower()
        if scheme not in {"http", "https", "socks4", "socks4a", "socks5", "socks5h"}:
            scheme = "unknown"
        endpoint = f"{(parsed.hostname or '').lower()}:{parsed.port or 0}"
    except (TypeError, ValueError):
        scheme = "unknown"
        endpoint = "invalid"
    digest = hashlib.sha256(endpoint.encode("utf-8", errors="replace")).hexdigest()[:16]
    return f"proxy:{scheme}:{digest}"


def _normalize_route(egress_route: str | None) -> str:
    value = "legacy" if egress_route is None else egress_route
    if not isinstance(value, str) or not _ROUTE_RE.fullmatch(value):
        raise GuardStateError("unknown or unsafe egress_route; use egress_route_id()")
    return value


def host_error_policy(error_class: str) -> dict:
    try:
        attribution, scope = HOST_ERROR_POLICIES[error_class]
    except (KeyError, TypeError) as exc:
        raise GuardStateError(f"unknown host-health error_class: {error_class!r}") from exc
    policy = {"error_class": error_class, "attribution": attribution,
              "breaker_scope": scope}
    if attribution == "proxy":
        policy.update({
            "restart_policy": "operator_confirmation_required",
            "automatic_retry_stopped": True,
            "next_action": (
                "stop and wait for the operator to choose default direct or "
                "explicitly confirm proxy again"
            ),
        })
    return policy


def _exception_chain(error: BaseException) -> list[BaseException]:
    out: list[BaseException] = []
    seen: set[int] = set()
    cur: object = error
    while isinstance(cur, BaseException) and id(cur) not in seen and len(out) < 12:
        seen.add(id(cur))
        out.append(cur)
        reason = getattr(cur, "reason", None)
        if isinstance(reason, BaseException) and id(reason) not in seen:
            cur = reason
            continue
        cur = cur.__cause__ or cur.__context__
    return out


def classify_network_error(error: BaseException, *, egress_route: str) -> str:
    """Classify a transport failure without promoting ambiguity to target blame.

    For proxied traffic, an opaque connect/reset/timeout is route-attributed;
    only direct traffic or a wrapper with stronger evidence may emit target
    classes.  DNS resolution is always a local/route fault.  Legacy callers are
    deliberately kept unattributed.
    """
    route = _normalize_route(egress_route)
    chain = _exception_chain(error)
    text = " ".join(
        f"{type(item).__module__}.{type(item).__name__}: {item}" for item in chain
    ).lower()
    dns_errors = [item for item in chain if isinstance(item, socket.gaierror)]
    temporary_dns = any(getattr(item, "errno", None) == getattr(socket, "EAI_AGAIN", -3)
                        for item in dns_errors) or "temporary failure in name resolution" in text
    if temporary_dns:
        # A proxied opener resolves the proxy endpoint locally. Treat that as a
        # failed selected proxy route so the one-strike operator pause applies.
        return "proxy_connect" if route.startswith("proxy:") else "local_dns"
    ambiguous_dns = bool(dns_errors) or any(marker in text for marker in (
        "name or service not known", "nodename nor servname", "getaddrinfo failed",
        "no address associated with hostname", "err_name_not_resolved",
    ))
    if ambiguous_dns:
        # With a proxy this is resolution of the route endpoint.  Direct NXDOMAIN
        # is host-specific but not proof of a target transport failure, so keep it
        # unattributed instead of opening either a target or whole-route breaker.
        return "proxy_connect" if route.startswith("proxy:") else "unattributed_transport"
    is_tls = any(isinstance(item, ssl.SSLError) for item in chain) or any(
        marker in text for marker in ("sslerror", "tls", "ssl handshake", "certificate verify failed")
    )
    if route.startswith("proxy:"):
        return "proxy_tls" if is_tls else "proxy_connect"
    if route == "direct":
        if is_tls:
            return "target_tls"
        target_reset = any(isinstance(item, (
            ConnectionResetError, ConnectionRefusedError, ConnectionAbortedError,
        )) for item in chain) or any(marker in text for marker in (
            "connection reset by peer", "connection refused", "remote end closed",
            "err_connection_reset", "err_connection_refused",
        ))
        return "target_reset" if target_reset else "unattributed_transport"
    return "unattributed_transport"


def network_error_provenance(error: BaseException, *, egress_route: str,
                             host: str) -> dict:
    route = _normalize_route(egress_route)
    observed_host = _normalize_host(host)
    error_class = classify_network_error(error, egress_route=route)
    return {
        "egress_route": route,
        "host": observed_host,
        **host_error_policy(error_class),
    }


def _breaker_host(scope: str, observed_host: str) -> str:
    return "*" if scope == "route" else observed_host


def _breaker_key(egress_route: str, host: str, error_class: str) -> str:
    raw = json.dumps([egress_route, host, error_class], separators=(",", ":"))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _total_key(egress_route: str, host: str) -> str:
    raw = json.dumps([egress_route, host], separators=(",", ":"))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _empty_hosthealth_state() -> dict:
    return {"schema": HOST_HEALTH_SCHEMA, "breakers": {}, "totals": {}, "provenance": []}


def _new_breaker(egress_route: str, host: str, error_class: str,
                 now: float) -> dict:
    policy = host_error_policy(error_class)
    return {
        "egress_route": egress_route,
        "host": _breaker_host(policy["breaker_scope"], host),
        "error_class": error_class,
        "attribution": policy["attribution"],
        "scope": policy["breaker_scope"],
        "consecutive": 0,
        "total_errors": 0,
        "opens": 0,
        "phase": "closed",
        "until": 0.0,
        "lease_token": None,
        "lease_owner": None,
        "lease_until": 0.0,
        "updated_at": now,
        "backoff_seconds": 0.0,
    }


def _validate_hosthealth_state(data: object) -> dict:
    if not isinstance(data, dict) or set(data) != _HOST_HEALTH_TOP_FIELDS:
        raise GuardStateError("host health v2 has missing or unknown top-level fields")
    if data.get("schema") != HOST_HEALTH_SCHEMA:
        raise GuardStateError("unknown host health schema; refusing to discard breaker state")
    breakers = data.get("breakers")
    totals = data.get("totals")
    provenance = data.get("provenance")
    if not isinstance(breakers, dict) or not isinstance(totals, dict) or not isinstance(provenance, list):
        raise GuardStateError("host health collections have invalid types")
    if len(breakers) > 10000 or len(totals) > 10000 or len(provenance) > HOST_HEALTH_PROVENANCE_LIMIT:
        raise GuardStateError("host health state exceeds bounded collection limits")
    for key, item in breakers.items():
        if not isinstance(key, str) or not isinstance(item, dict) or set(item) != _HOST_HEALTH_BREAKER_FIELDS:
            raise GuardStateError("host health breaker has missing or unknown fields")
        route = _normalize_route(item.get("egress_route"))
        error_class = item.get("error_class")
        policy = host_error_policy(error_class)
        host = item.get("host")
        if host != "*":
            host = _normalize_host(host)
        if item.get("attribution") != policy["attribution"] or item.get("scope") != policy["breaker_scope"]:
            raise GuardStateError("host health breaker attribution does not match error policy")
        expected_host = "*" if policy["breaker_scope"] == "route" else host
        if host != expected_host or key != _breaker_key(route, host, error_class):
            raise GuardStateError("host health breaker key does not match its route/host/error class")
        _counter(item.get("consecutive"), "consecutive")
        _counter(item.get("total_errors"), "total_errors")
        _counter(item.get("opens"), "opens")
        phase = item.get("phase")
        if phase not in {"closed", "open", "half_open"}:
            raise GuardStateError("host health breaker has unknown phase")
        for field in ("until", "lease_until", "updated_at", "backoff_seconds"):
            _finite_number(item.get(field), field)
        token = item.get("lease_token")
        owner = item.get("lease_owner")
        if token is not None and (not isinstance(token, str) or not re.fullmatch(r"[0-9a-f]{32}", token)):
            raise GuardStateError("host health lease token is invalid")
        if owner is not None and (isinstance(owner, bool) or not isinstance(owner, int) or owner <= 0):
            raise GuardStateError("host health lease owner is invalid")
        if phase == "half_open" and (token is None or owner is None):
            raise GuardStateError("half-open breaker is missing its lease")
        if phase != "half_open" and (token is not None or owner is not None or item.get("lease_until") != 0.0):
            raise GuardStateError("non-half-open breaker carries a lease")
        if phase == "closed" and item.get("until") != 0.0:
            raise GuardStateError("closed breaker carries an open-until timestamp")
        if phase == "open" and item.get("until") <= 0.0:
            raise GuardStateError("open breaker is missing its cooldown timestamp")
        if phase == "half_open" and (item.get("until") != 0.0 or item.get("lease_until") <= 0.0):
            raise GuardStateError("half-open breaker has inconsistent cooldown/lease timestamps")
    for key, item in totals.items():
        if not isinstance(key, str) or not isinstance(item, dict) or set(item) != _HOST_HEALTH_TOTAL_FIELDS:
            raise GuardStateError("host health total has missing or unknown fields")
        route = _normalize_route(item.get("egress_route"))
        host = _normalize_host(item.get("host"))
        if key != _total_key(route, host):
            raise GuardStateError("host health total key does not match route/host")
        _counter(item.get("count"), "count")
    for item in provenance:
        if not isinstance(item, dict) or set(item) != _HOST_HEALTH_PROVENANCE_FIELDS:
            raise GuardStateError("host health provenance has missing or unknown fields")
        if not isinstance(item.get("event_id"), str) or not re.fullmatch(r"[0-9a-f]{16}", item["event_id"]):
            raise GuardStateError("host health provenance event id is invalid")
        _finite_number(item.get("ts"), "ts")
        if item.get("event") not in {
                "migrated", "error", "success", "opened", "half_open",
                "recovered", "operator_confirmed"}:
            raise GuardStateError("host health provenance event is unknown")
        _normalize_route(item.get("egress_route"))
        if item.get("host") != "*":
            _normalize_host(item.get("host"))
        _normalize_host(item.get("observed_host"))
        error_class = item.get("error_class")
        if error_class is not None:
            policy = host_error_policy(error_class)
            if item.get("attribution") != policy["attribution"] or item.get("scope") != policy["breaker_scope"]:
                raise GuardStateError("host health provenance attribution is inconsistent")
        elif item.get("attribution") != "none" or item.get("scope") != "none":
            raise GuardStateError("success provenance must use none attribution/scope")
        _counter(item.get("count"), "count")
        _counter(item.get("consecutive"), "consecutive")
        _finite_number(item.get("until"), "until")
        _finite_number(item.get("lease_until"), "lease_until")
    return data


def _append_hosthealth_event(data: dict, *, now: float, event: str,
                             egress_route: str, host: str, observed_host: str,
                             error_class: str | None, attribution: str, scope: str,
                             count: int = 0, consecutive: int = 0,
                             until: float = 0.0, lease_until: float = 0.0) -> None:
    raw = json.dumps(
        [now, event, egress_route, host, observed_host, error_class, count,
         consecutive, until, lease_until, len(data["provenance"])],
        separators=(",", ":"),
    )
    data["provenance"].append({
        "event_id": hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16],
        "ts": now,
        "event": event,
        "egress_route": egress_route,
        "host": host,
        "observed_host": observed_host,
        "error_class": error_class,
        "attribution": attribution,
        "scope": scope,
        "count": count,
        "consecutive": consecutive,
        "until": until,
        "lease_until": lease_until,
    })
    data["provenance"] = data["provenance"][-HOST_HEALTH_PROVENANCE_LIMIT:]


def _migrate_legacy_hosthealth(data: object, now: float) -> dict:
    if not isinstance(data, dict):
        raise GuardStateError("legacy host health state is not an object")
    out = _empty_hosthealth_state()
    for raw_host, raw_item in data.items():
        try:
            host = _normalize_host(raw_host)
        except GuardStateError:
            if not isinstance(raw_host, str):
                raise
            # Historical wrappers occasionally wrote a whitespace-joined host
            # list as one key.  Preserve its counters under a non-routable,
            # credential-free quarantine identity; it never matched a valid URL
            # hostname before and must not poison migration for every real host.
            digest = hashlib.sha256(raw_host.encode("utf-8", errors="replace")).hexdigest()[:16]
            host = f"legacy-invalid-{digest}.invalid"
        if not isinstance(raw_item, dict) or not set(raw_item).issubset({"errs", "total", "until"}):
            raise GuardStateError("legacy host health entry has unknown fields")
        errs = _counter(raw_item.get("errs", 0), "legacy.errs")
        total = _counter(raw_item.get("total", 0), "legacy.total")
        until = _finite_number(raw_item.get("until", 0.0), "legacy.until")
        total_key = _total_key("legacy", host)
        out["totals"][total_key] = {"egress_route": "legacy", "host": host, "count": total}
        state = _new_breaker("legacy", host, "unattributed_transport", now)
        state["consecutive"] = errs
        state["total_errors"] = errs
        if until:
            state["phase"] = "open"
            state["until"] = until
            state["opens"] = 1
            state["backoff_seconds"] = max(until - now, 0.0)
        key = _breaker_key("legacy", host, "unattributed_transport")
        out["breakers"][key] = state
        _append_hosthealth_event(
            out, now=now, event="migrated", egress_route="legacy", host=host,
            observed_host=host, error_class="unattributed_transport",
            attribution="unknown", scope="unattributed_host", count=total,
            consecutive=errs, until=until,
        )
    return _validate_hosthealth_state(out)


def _load_hosthealth_state(now: float) -> tuple[dict, bool]:
    path = STATE_DIR / "hosthealth.json"
    if not path.exists():
        return _empty_hosthealth_state(), False
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        raise GuardStateError("host health state is unreadable; refusing target traffic") from exc
    if isinstance(raw, dict) and raw.get("schema") == HOST_HEALTH_SCHEMA:
        return _validate_hosthealth_state(raw), False
    if isinstance(raw, dict) and "schema" in raw:
        raise GuardStateError("unknown host health schema; refusing target traffic")
    return _migrate_legacy_hosthealth(raw, now), True


def _save_hosthealth_state(data: dict) -> None:
    _save("hosthealth.json", _validate_hosthealth_state(data))


class HostHealth:
    """Route-aware transport breaker shared by every active-tool process.

    Breaker identity includes ``(egress_route, host, error_class)``.  Route
    failures use host ``*`` so one broken proxy/local resolver pauses that route
    across targets.  Only target-attributed classes use a target-host breaker.
    Target/local cooldown recovery grants one persisted half-open lease;
    concurrent workers remain blocked until that trial records success/error or
    the lease expires. Proxy-attributed route failures are different: the first
    failure pauses that proxy route until a newer operator turn explicitly
    selects proxy again. A timer alone never restarts proxy traffic.
    """

    def __init__(self, threshold: int = HOST_ERR_THRESHOLD,
                 backoff: float = HOST_BACKOFF_SEC, warn_at: int = HOST_REQ_WARN,
                 *, max_backoff: float = HOST_MAX_BACKOFF_SEC,
                 lease_seconds: float = HOST_HALF_OPEN_LEASE_SEC,
                 jitter_ratio: float = HOST_BACKOFF_JITTER_RATIO,
                 clock=None):
        if isinstance(threshold, bool) or not isinstance(threshold, int) or threshold < 1:
            raise ValueError("HostHealth threshold must be a positive integer")
        if isinstance(warn_at, bool) or not isinstance(warn_at, int) or warn_at < 1:
            raise ValueError("HostHealth warn_at must be a positive integer")
        for name, value in (("backoff", backoff), ("max_backoff", max_backoff),
                            ("lease_seconds", lease_seconds), ("jitter_ratio", jitter_ratio)):
            if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(float(value)):
                raise ValueError(f"HostHealth {name} must be finite")
        if backoff <= 0 or max_backoff < backoff or lease_seconds <= 0 or not 0 <= jitter_ratio <= 0.5:
            raise ValueError("HostHealth backoff/lease/jitter bounds are invalid")
        self.threshold = threshold
        self.backoff = float(backoff)
        self.max_backoff = float(max_backoff)
        self.lease_seconds = float(lease_seconds)
        self.jitter_ratio = float(jitter_ratio)
        self.warn_at = warn_at
        self._clock = clock or time.time

    def _now(self) -> float:
        value = float(self._clock())
        if not math.isfinite(value) or value < 0:
            raise GuardStateError("HostHealth clock returned an invalid value")
        return value

    @staticmethod
    def _matches(item: dict, route: str, host: str) -> bool:
        # Legacy state had no route dimension.  Its same-host unattributed
        # cooldown remains a conservative wildcard until a structured success
        # clears it; otherwise upgrading the wrapper would silently bypass an
        # already-open live breaker.
        if item["egress_route"] not in {route, "legacy"}:
            return False
        return item["host"] == "*" if item["scope"] == "route" else item["host"] == host

    def _backoff_delay(self, key: str, opens: int) -> float:
        exponent = min(max(opens - 1, 0), 20)
        base = min(self.max_backoff, self.backoff * (2 ** exponent))
        unit = int(hashlib.sha256(f"{key}:{opens}".encode()).hexdigest()[:8], 16) / 0xFFFFFFFF
        return min(self.max_backoff, base + base * self.jitter_ratio * unit)

    def _arm(self, item: dict, key: str, now: float) -> float:
        item["opens"] += 1
        delay = self._backoff_delay(key, item["opens"])
        item["phase"] = "open"
        item["until"] = now + delay
        item["lease_token"] = None
        item["lease_owner"] = None
        item["lease_until"] = 0.0
        item["updated_at"] = now
        item["backoff_seconds"] = delay
        return delay

    @staticmethod
    def _lease_authorized(key: str, item: dict,
                          lease: HostHealthLease | None) -> bool:
        if lease is not None:
            return item["lease_token"] == lease.token and key in lease.breaker_keys
        # Compatibility for an old same-process caller that ignored check()'s new
        # return value.  Another process can never consume this lease.
        return item["lease_owner"] == os.getpid()

    @staticmethod
    def _increment_total(data: dict, route: str, host: str, count: int) -> None:
        count = _counter(count, "request count")
        key = _total_key(route, host)
        item = data["totals"].setdefault(
            key, {"egress_route": route, "host": host, "count": 0})
        item["count"] += count

    def check(self, host: str, *, egress_route: str | None = None,
              acquire_half_open: bool = True) -> HostHealthLease | None:
        host = _normalize_host(host)
        route = _normalize_route(egress_route)
        now = self._now()
        with _state_lock():
            data, migrated = _load_hosthealth_state(now)
            matching = sorted(
                ((key, item) for key, item in data["breakers"].items()
                 if self._matches(item, route, host) and item["phase"] != "closed"),
                key=lambda pair: (0 if pair[1]["scope"] == "route" else 1, pair[0]),
            )
            for _, item in matching:
                if item["attribution"] == "proxy":
                    if migrated:
                        _save_hosthealth_state(data)
                    raise HostBackoff(
                        f"proxy route paused for route={route} host={host} "
                        f"error_class={item['error_class']}; a newer operator "
                        "turn must explicitly select proxy before one guarded retry",
                        egress_route=route, host=host,
                        error_class=item["error_class"],
                        attribution=item["attribution"],
                        breaker_scope=item["scope"],
                        phase="operator_confirmation_required",
                        retry_after=0.0,
                    )
                if item["phase"] == "open" and item["until"] > now:
                    if migrated:
                        _save_hosthealth_state(data)
                    remain = item["until"] - now
                    raise HostBackoff(
                        f"{item['scope']} breaker open for route={route} host={host} "
                        f"error_class={item['error_class']} ({remain:.0f}s remaining)",
                        egress_route=route, host=host, error_class=item["error_class"],
                        attribution=item["attribution"], breaker_scope=item["scope"],
                        phase="open", retry_after=remain,
                    )
                if item["phase"] == "half_open" and item["lease_until"] > now:
                    if migrated:
                        _save_hosthealth_state(data)
                    remain = item["lease_until"] - now
                    raise HostBackoff(
                        f"{item['scope']} breaker half-open trial already leased for "
                        f"route={route} host={host} error_class={item['error_class']} "
                        f"({remain:.0f}s remaining)",
                        egress_route=route, host=host, error_class=item["error_class"],
                        attribution=item["attribution"], breaker_scope=item["scope"],
                        phase="half_open", retry_after=remain,
                    )
            expired = [(key, item) for key, item in matching
                       if (item["phase"] == "open" and item["until"] <= now)
                       or (item["phase"] == "half_open" and item["lease_until"] <= now)]
            if not expired:
                if migrated:
                    _save_hosthealth_state(data)
                return None
            if not acquire_half_open:
                item = expired[0][1]
                if migrated:
                    _save_hosthealth_state(data)
                raise HostBackoff(
                    f"{item['scope']} breaker cooldown expired for route={route} host={host}; "
                    "recovery requires one guarded single-request probe, not a fan-out tool",
                    egress_route=route, host=host, error_class=item["error_class"],
                    attribution=item["attribution"], breaker_scope=item["scope"],
                    phase="half_open_required", retry_after=0.0,
                )
            keys = tuple(key for key, _ in expired)
            token_raw = json.dumps([route, host, now, os.getpid(), keys], separators=(",", ":"))
            token = hashlib.sha256(token_raw.encode()).hexdigest()[:32]
            lease_until = now + self.lease_seconds
            for key, item in expired:
                item["phase"] = "half_open"
                item["until"] = 0.0
                item["lease_token"] = token
                item["lease_owner"] = os.getpid()
                item["lease_until"] = lease_until
                item["updated_at"] = now
                _append_hosthealth_event(
                    data, now=now, event="half_open", egress_route=route,
                    host=item["host"], observed_host=host,
                    error_class=item["error_class"], attribution=item["attribution"],
                    scope=item["scope"], consecutive=item["consecutive"],
                    lease_until=lease_until,
                )
            _save_hosthealth_state(data)
            return HostHealthLease(route, host, token, keys, lease_until)

    def record_ok(self, host: str, *, egress_route: str | None = None,
                  count: int = 1, lease: HostHealthLease | None = None) -> None:
        host = _normalize_host(host)
        route = _normalize_route(egress_route)
        count = _counter(count, "request count")
        now = self._now()
        with _state_lock():
            data, _ = _load_hosthealth_state(now)
            matching = [(key, item) for key, item in data["breakers"].items()
                        if self._matches(item, route, host)]
            for key, item in matching:
                if item["phase"] == "half_open" and not self._lease_authorized(key, item, lease):
                    raise GuardStateError("half-open success does not own the persisted lease")
                if item["phase"] == "open":
                    raise GuardStateError("success cannot clear an open breaker without a half-open lease")
            self._increment_total(data, route, host, count)
            for _, item in matching:
                recovered = item["phase"] == "half_open" or item["consecutive"] > 0
                item["consecutive"] = 0
                item["opens"] = 0
                item["phase"] = "closed"
                item["until"] = 0.0
                item["lease_token"] = None
                item["lease_owner"] = None
                item["lease_until"] = 0.0
                item["updated_at"] = now
                item["backoff_seconds"] = 0.0
                if recovered:
                    _append_hosthealth_event(
                        data, now=now, event="recovered", egress_route=route,
                        host=item["host"], observed_host=host,
                        error_class=item["error_class"], attribution=item["attribution"],
                        scope=item["scope"], count=count,
                    )
            _append_hosthealth_event(
                data, now=now, event="success", egress_route=route, host=host,
                observed_host=host, error_class=None, attribution="none", scope="none",
                count=count,
            )
            _save_hosthealth_state(data)

    def record_error(self, host: str, *, error_class: str = "unattributed_transport",
                     egress_route: str | None = None, count: int = 1,
                     lease: HostHealthLease | None = None,
                     request_count: int | None = None) -> None:
        host = _normalize_host(host)
        route = _normalize_route(egress_route)
        policy = host_error_policy(error_class)
        count = _counter(count, "request count")
        if count < 1:
            raise GuardStateError("an error record must represent at least one real request")
        total_count = count if request_count is None else _counter(request_count, "request count")
        if total_count < count:
            raise GuardStateError("request_count cannot be smaller than attributed failures")
        now = self._now()
        with _state_lock():
            data, _ = _load_hosthealth_state(now)
            matching = [(key, item) for key, item in data["breakers"].items()
                        if self._matches(item, route, host)]
            leased: list[tuple[str, dict]] = []
            for key, item in matching:
                if item["phase"] == "half_open":
                    if not self._lease_authorized(key, item, lease):
                        raise GuardStateError("half-open failure does not own the persisted lease")
                    leased.append((key, item))
                elif item["phase"] == "open":
                    raise GuardStateError("error recorded while breaker is open; caller skipped check()")
            self._increment_total(data, route, host, total_count)
            # An unattributed/route failure interrupts a target-failure streak and
            # vice versa.  Different error classes therefore never accumulate as
            # if they were consecutive observations of one class.
            for _, item in matching:
                if item["phase"] == "closed" and item["error_class"] != error_class:
                    item["consecutive"] = 0
                    item["updated_at"] = now
            rearmed: set[str] = set()
            trip_threshold = 1 if policy["attribution"] == "proxy" else self.threshold
            for key, item in leased:
                item["consecutive"] = max(item["consecutive"], trip_threshold)
                self._arm(item, key, now)
                rearmed.add(key)
                _append_hosthealth_event(
                    data, now=now, event="opened", egress_route=route,
                    host=item["host"], observed_host=host,
                    error_class=item["error_class"], attribution=item["attribution"],
                    scope=item["scope"], consecutive=item["consecutive"], until=item["until"],
                )
            breaker_host = _breaker_host(policy["breaker_scope"], host)
            key = _breaker_key(route, breaker_host, error_class)
            item = data["breakers"].setdefault(key, _new_breaker(route, host, error_class, now))
            item["total_errors"] += count
            if key in rearmed:
                item["consecutive"] = max(item["consecutive"], trip_threshold)
            else:
                item["consecutive"] += count
                item["updated_at"] = now
                if item["consecutive"] >= trip_threshold:
                    self._arm(item, key, now)
                    _append_hosthealth_event(
                        data, now=now, event="opened", egress_route=route,
                        host=item["host"], observed_host=host,
                        error_class=error_class, attribution=policy["attribution"],
                        scope=policy["breaker_scope"], consecutive=item["consecutive"],
                        until=item["until"],
                    )
            _append_hosthealth_event(
                data, now=now, event="error", egress_route=route,
                host=breaker_host, observed_host=host, error_class=error_class,
                attribution=policy["attribution"], scope=policy["breaker_scope"],
                count=count, consecutive=item["consecutive"], until=item["until"],
            )
            _save_hosthealth_state(data)

    def soft_warn(self, host: str, *, egress_route: str | None = None) -> str | None:
        """Read-only warning; calling it never increments request counts."""
        host = _normalize_host(host)
        route = _normalize_route(egress_route)
        now = self._now()
        with _state_lock():
            data, migrated = _load_hosthealth_state(now)
            if migrated:
                _save_hosthealth_state(data)
            total = data["totals"].get(_total_key(route, host), {}).get("count", 0)
        if total and total % self.warn_at == 0:
            return (f"[guard] 已通过 {route} 对 {host} 发出 {total} 次真实请求 — "
                    "注意请求量, 目标可能开始限流(放缓/换面/换出口)")
        return None

    def snapshot(self) -> dict:
        """Validated state copy for fixtures/observability (never mutable truth)."""
        now = self._now()
        with _state_lock():
            data, migrated = _load_hosthealth_state(now)
            if migrated:
                _save_hosthealth_state(data)
            return json.loads(json.dumps(data))

    def proxy_confirmation_state(self, *, egress_route: str | None = None) -> dict:
        """Return the current manual proxy pause without exposing endpoints.

        The projection is read-only. ``latest_updated_at`` is the causal fence
        used by the turn Hook: a contract created before (or at) that failure
        cannot confirm its own retry.
        """
        selected_route = _normalize_route(egress_route) \
            if egress_route is not None else None
        if selected_route is not None and not selected_route.startswith("proxy:"):
            raise GuardStateError("proxy confirmation route must identify one proxy")
        snapshot = self.snapshot()
        pending = [
            item for item in snapshot["breakers"].values()
            if item["attribution"] == "proxy" and item["phase"] != "closed"
            and (selected_route is None or item["egress_route"] == selected_route)
        ]
        return {
            "required": bool(pending),
            "latest_updated_at": max(
                (float(item["updated_at"]) for item in pending), default=0.0),
            "routes": sorted({str(item["egress_route"]) for item in pending}),
            "error_classes": sorted({str(item["error_class"]) for item in pending}),
        }

    def acknowledge_proxy_retry(self, *, confirmed_at: float,
                                egress_route: str) -> bool:
        """Consume a newer operator proxy choice and permit one fresh attempt.

        This transition is not a health success: provenance records
        ``operator_confirmed`` and the next proxy error reopens the route on its
        first observation. The caller must supply a durable turn timestamp newer
        than the pending failure on that exact credential-free route; stale or
        racing confirmations fail closed and never clear another proxy route.
        """
        confirmed = _finite_number(confirmed_at, "confirmed_at", minimum=0.0)
        if confirmed <= 0:
            raise GuardStateError("proxy retry confirmation timestamp is invalid")
        selected_route = _normalize_route(egress_route)
        if not selected_route.startswith("proxy:"):
            raise GuardStateError("proxy retry confirmation must bind one proxy route")
        now = self._now()
        with _state_lock():
            data, _ = _load_hosthealth_state(now)
            pending = [
                (key, item) for key, item in data["breakers"].items()
                if item["attribution"] == "proxy" and item["phase"] != "closed"
                and item["egress_route"] == selected_route
            ]
            if not pending:
                return False
            latest = max(float(item["updated_at"]) for _, item in pending)
            if confirmed <= latest:
                raise GuardStateError(
                    "proxy retry requires a newer operator turn than the latest proxy failure")
            for _, item in pending:
                item["consecutive"] = 0
                item["phase"] = "closed"
                item["until"] = 0.0
                item["lease_token"] = None
                item["lease_owner"] = None
                item["lease_until"] = 0.0
                item["updated_at"] = now
                item["backoff_seconds"] = 0.0
                _append_hosthealth_event(
                    data, now=now, event="operator_confirmed",
                    egress_route=item["egress_route"], host=item["host"],
                    observed_host="operator-confirmed.local",
                    error_class=item["error_class"],
                    attribution=item["attribution"], scope=item["scope"],
                )
            _save_hosthealth_state(data)
            return True


class SessionBudget:
    """全局(跨 host)滑窗请求 + 字节预算。HostHealth 管单 host, 这个管【整场总量】——
    实战真问题是整场请求量巨大 / 反复打爆各 IP, 单 host 熔断看不到全局。两级:
    - 软告警(SESSION_WARN_COUNT): 不阻断, 只提示(避免误伤正常批量)。
    - 硬熔断(SESSION_TRIP_COUNT / SESSION_TRIP_BYTES): 布防冷却, check() 抛
      SessionTripped, 工具 abort —— 真·DoS-临界 runaway 的工具层刹车。

    用法仿 HostHealth: 每次请求 *前* 调 check()(冷却期直接 abort); 响应 *后* 调
    record(nbytes)(计量 + 越硬阈值则布防)。"""

    def __init__(self, window: float = SESSION_WINDOW_SEC, warn_count: int = SESSION_WARN_COUNT,
                 trip_count: int = SESSION_TRIP_COUNT, trip_bytes: int = SESSION_TRIP_BYTES,
                 cooldown: float = SESSION_TRIP_COOLDOWN, name: str = "sessionbudget.json"):
        self.window = window
        self.warn_count = warn_count
        self.trip_count = trip_count
        self.trip_bytes = trip_bytes
        self.cooldown = cooldown
        self.name = name

    def check(self) -> None:
        """Pre-request: if the whole-session breaker is armed, abort (don't flood)."""
        st = _load(self.name)
        remain = st.get("until", 0.0) - time.time()
        if remain > 0:
            raise SessionTripped(
                f"whole-session volume breaker open for {remain:.0f}s more "
                f"(crossed >= {self.trip_count} reqs or >= {self.trip_bytes} bytes in "
                f"{int(self.window // 60)}min). 整场请求/外渗量过大=打爆各 IP 风险; "
                "收敛攻击面 / 换出口, 或调高 SESSION_TRIP_* 后再跑。")

    def record(self, nbytes: int = 0, count: int = 1) -> str | None:
        """Post-response: count `count` real requests + retained bytes; arm the hard
        breaker on count OR volume; return a soft/arming warning string (or None).
        `count` > 1 lets one send() that made N real attempts (retries) record all N
        — otherwise --retry would undercount the session volume (bug B1)."""
        with _state_lock():
            st = _load(self.name)
            now = time.time()
            reqs = [t for t in st.get("reqs", []) if now - t < self.window]
            reqs.extend([now] * max(int(count), 0))   # 每个真实请求(含重试)各计一次
            st["reqs"] = reqs[-5000:]   # 防无限增长
            bys = [[t, b] for (t, b) in st.get("bytes", []) if now - t < self.window]
            if nbytes:
                bys.append([now, int(nbytes)])
            st["bytes"] = bys[-5000:]
            n = len(reqs)
            total_bytes = sum(b for (_, b) in bys)
            armed = n >= self.trip_count or total_bytes >= self.trip_bytes
            if armed:
                st["until"] = now + self.cooldown   # 布防: 后续 check() 直接 abort
            _save(self.name, st)
        if armed:
            return (f"[guard] 全局会话熔断已布防: {n} 请求 / {total_bytes} 字节 "
                    f"({int(self.window // 60)}min) 超硬阈值; 后续请求将被 abort "
                    f"{int(self.cooldown)}s。收敛 / 换出口, 或调高 SESSION_TRIP_*。")
        if n >= self.warn_count and n % 50 == 0:   # 达软阈值后每 50 次提醒一次
            return (f"[guard] 全局会话 {int(self.window // 60)} 分钟内已发 {n} 请求 —— "
                    "整场请求量偏高, 易打爆目标各 IP; 考虑收敛攻击面 / 放缓 / 换出口。")
        return None


class RateLimiter:
    """Wall-clock spacing enforcer. Call gate(host) immediately before each
    request. It blocks the minimum time needed to honor the ceilings, and hard
    aborts if the caller is trying to burst far past budget."""

    def __init__(self, global_rps: float = GLOBAL_MAX_RPS, host_rps: float = PER_HOST_MAX_RPS):
        self.min_global = 1.0 / max(global_rps, 0.01)
        self.min_host = 1.0 / max(host_rps, 0.01)

    def gate(self, host: str, max_wait: float = 10.0) -> None:
        # The whole compute+spacing-sleep+write runs under the cross-process lock,
        # so N parallel workers queue through the gate and honour ONE global RPS
        # ceiling instead of each spacing independently (which would be N x rate).
        with _state_lock():
            st = _load("ratelimit.json")
            wall = time.time()
            last_global = st.get("__global__", 0.0)
            last_host = st.get(host, 0.0)
            wait = max(
                self.min_global - (wall - last_global),
                self.min_host - (wall - last_host),
                0.0,
            )
            if wait > max_wait:
                raise RateBudgetExceeded(
                    f"rate ceiling would require waiting {wait:.1f}s for {host}; "
                    "aborting instead of bursting (禁高频/DoS)"
                )
            if wait > 0:
                time.sleep(wait)
            wall = time.time()
            st["__global__"] = wall
            st[host] = wall
            _save("ratelimit.json", st)


def cap_body(data: bytes, limit: int = MAX_BODY_BYTES) -> tuple[bytes, bool]:
    """Truncate an oversized response body. Returns (body, was_truncated).
    Prevents an active tool from quietly pulling a full data dump."""
    if len(data) > limit:
        return data[:limit], True
    return data, False


class AuthFailCounter:
    """Per-endpoint authentication-failure counter. Tools call record(key, ok)
    after each auth attempt; check(key) raises BruteforceLock once the endpoint
    has accumulated AUTH_FAIL_LOCK failures. The threshold is a high anti-runaway
    ceiling, NOT a brute-force ban — weak-credential trials run freely; speed is
    capped by RateLimiter. This only stops a buggy unbounded auth loop.

    At AUTH_FAIL_PIVOT (25) consecutive failures, prints a stderr warning
    advising the driver to pivot to logic-based attacks (retrospective #4)."""

    def __init__(self, limit: int = AUTH_FAIL_LOCK, pivot: int = AUTH_FAIL_PIVOT):
        self.limit = limit
        self.pivot = pivot

    def check(self, key: str) -> None:
        st = _load("authfail.json")
        cnt = st.get(key, 0)
        if cnt == self.pivot:
            import sys as _sys
            print(f"\n[guard] BRUTE-FORCE PIVOT: endpoint '{key}' 连续 {cnt} 次认证失败 —— "
                  "猜测攻击不会产生新价值。建议: 转向逻辑漏洞/配置错误/未授权API/IDOR/路径穿越, "
                  "不要继续尝试更多密码(retrospective #4: 500+ 次猜测 0 成功)\n",
                  file=_sys.stderr)
        if cnt >= self.limit:
            raise BruteforceLock(
                f"endpoint '{key}' hit {self.limit} auth failures; probe stopped "
                "(anti-runaway ceiling — not a brute-force ban; raise AUTH_FAIL_LOCK "
                "for a longer dictionary. Speed is already capped by RateLimiter)"
            )

    def record(self, key: str, ok: bool) -> None:
        with _state_lock():
            st = _load("authfail.json")
            st[key] = 0 if ok else st.get(key, 0) + 1
            _save("authfail.json", st)

    def would_pivot(self, key: str) -> bool:
        """Probe 调用方在 record 后查: 该 endpoint 是否已达 pivot 阈值。
        返回 True 时调用方应在输出 JSON 中设 pivot_required, 提示 driver 转向。"""
        return _load("authfail.json").get(key, 0) >= self.pivot


class UploadRegistry:
    """Tracks every artifact an upload-test puts on a target so the run can
    prove it was removed (不留后门残留). Confirming an upload vuln is only
    allowed once the artifact is registered here AND a cleanup is recorded."""

    def register(self, run: str, target: str, remote_ref: str, note: str = "") -> None:
        with _state_lock():
            st = _load("uploads.json")
            st.setdefault(run, []).append(
                {"target": target, "ref": remote_ref, "note": note,
                 "ts": time.strftime("%Y-%m-%d %H:%M:%S"), "cleaned": False}
            )
            _save("uploads.json", st)

    def mark_cleaned(self, run: str, remote_ref: str) -> None:
        with _state_lock():
            st = _load("uploads.json")
            for item in st.get(run, []):
                if item["ref"] == remote_ref:
                    item["cleaned"] = True
            _save("uploads.json", st)

    def outstanding(self, run: str | None = None) -> list[dict]:
        st = _load("uploads.json")
        runs = [run] if run else list(st)
        return [it for r in runs for it in st.get(r, []) if not it["cleaned"]]


@contextlib.contextmanager
def _selftest_state_isolation():
    """Keep guard.py's executable selftest away from live shared guard state."""
    import shutil
    import tempfile

    global STATE_DIR, _LOCK_PATH
    old_state_dir, old_lock_path = STATE_DIR, _LOCK_PATH
    root = Path(tempfile.mkdtemp(prefix="xunji_guard_selftest_"))
    try:
        STATE_DIR = root / "state"
        STATE_DIR.mkdir(parents=True, exist_ok=True)
        _LOCK_PATH = STATE_DIR / ".lock"
        yield
    finally:
        STATE_DIR, _LOCK_PATH = old_state_dir, old_lock_path
        shutil.rmtree(root, ignore_errors=True)


def _selftest_hosthealth_route_breaker() -> None:
    fixture_path = Path(__file__).resolve().parent / "fixtures" / "guard-host-health.json"
    fixture = json.loads(fixture_path.read_text(encoding="utf-8"))
    if set(fixture) != {"schema", "breaker_cases", "classification_cases"} or (
            fixture.get("schema") != "xunji.guard-host-health-fixtures.v1"):
        raise AssertionError("guard HostHealth fixture schema/fields drifted")

    clock_value = [1000.0]

    def clock() -> float:
        return clock_value[0]

    state_path = STATE_DIR / "hosthealth.json"

    for case in fixture["breaker_cases"]:
        expected_fields = {
            "name", "route", "host", "error_class", "failures",
            "blocked_hosts", "expected_scope",
        }
        if not expected_fields.issubset(case) or not set(case).issubset(
                expected_fields | {"allowed_hosts", "allowed_routes"}):
            raise AssertionError(f"unknown/missing breaker fixture fields: {case.get('name')}")
        state_path.unlink(missing_ok=True)
        clock_value[0] = 1000.0
        hh = HostHealth(threshold=3, backoff=10, max_backoff=30,
                        lease_seconds=5, jitter_ratio=0.1, clock=clock)
        observed_failures = (
            1 if host_error_policy(case["error_class"])["attribution"] == "proxy"
            else case["failures"]
        )
        for _ in range(observed_failures):
            hh.record_error(case["host"], egress_route=case["route"],
                            error_class=case["error_class"])
        snap = hh.snapshot()
        states = [item for item in snap["breakers"].values()
                  if item["error_class"] == case["error_class"]]
        if len(states) != 1 or states[0]["scope"] != case["expected_scope"]:
            raise AssertionError(f"wrong breaker scope/key for {case['name']}")
        expected_key = _breaker_key(
            case["route"], "*" if case["expected_scope"] == "route" else case["host"],
            case["error_class"],
        )
        if expected_key not in snap["breakers"]:
            raise AssertionError(f"route/host/error_class tuple missing for {case['name']}")
        for blocked_host in case["blocked_hosts"]:
            try:
                HostHealth(clock=clock).check(blocked_host, egress_route=case["route"])
                raise AssertionError(f"breaker did not block {blocked_host}: {case['name']}")
            except HostBackoff as exc:
                if exc.error_class != case["error_class"] or exc.breaker_scope != case["expected_scope"]:
                    raise AssertionError(f"backoff provenance mismatch: {case['name']}") from exc
        for allowed_host in case.get("allowed_hosts", []):
            if HostHealth(clock=clock).check(allowed_host, egress_route=case["route"]) is not None:
                raise AssertionError(f"unrelated host received a lease: {case['name']}")
        for allowed_route in case.get("allowed_routes", []):
            if HostHealth(clock=clock).check(case["host"], egress_route=allowed_route) is not None:
                raise AssertionError(f"unrelated route received a lease: {case['name']}")

    # A shared-state cooldown grants one half-open lease.  A second worker sees
    # it and remains blocked; only the owner may close it.
    state_path.unlink(missing_ok=True)
    clock_value[0] = 2000.0
    hh1 = HostHealth(threshold=3, backoff=10, max_backoff=30,
                     lease_seconds=5, jitter_ratio=0.1, clock=clock)
    hh2 = HostHealth(threshold=3, backoff=10, max_backoff=30,
                     lease_seconds=5, jitter_ratio=0.1, clock=clock)
    hh1.record_error("shared.example", egress_route="direct",
                     error_class="target_reset", count=3)
    opened = next(iter(hh1.snapshot()["breakers"].values()))
    first_delay = opened["until"] - clock_value[0]
    if not 10 <= first_delay <= 11:
        raise AssertionError("deterministic first backoff is outside bounded jitter")
    clock_value[0] = opened["until"] + 0.001
    try:
        hh2.check("shared.example", egress_route="direct", acquire_half_open=False)
        raise AssertionError("fan-out wrapper acquired an unsafe half-open trial")
    except HostBackoff as exc:
        if exc.phase != "half_open_required":
            raise
    lease = hh1.check("shared.example", egress_route="direct")
    if not isinstance(lease, HostHealthLease):
        raise AssertionError("expired cooldown did not issue a half-open lease")
    try:
        hh2.check("shared.example", egress_route="direct")
        raise AssertionError("second worker bypassed the shared half-open lease")
    except HostBackoff as exc:
        if exc.phase != "half_open":
            raise
    wrong = HostHealthLease("direct", "shared.example", "0" * 32,
                            lease.breaker_keys, lease.expires_at)
    try:
        hh1.record_ok("shared.example", egress_route="direct", lease=wrong)
        raise AssertionError("wrong half-open token closed a breaker")
    except GuardStateError:
        pass
    hh1.record_error("shared.example", egress_route="direct",
                     error_class="target_reset", lease=lease)
    reopened = next(iter(hh1.snapshot()["breakers"].values()))
    second_delay = reopened["until"] - clock_value[0]
    if not first_delay < second_delay <= 22:
        raise AssertionError("exponential backoff is not bounded/deterministic")
    clock_value[0] = reopened["until"] + 0.001
    recovery_lease = hh2.check("shared.example", egress_route="direct")
    hh2.record_ok("shared.example", egress_route="direct", lease=recovery_lease)
    if hh1.check("shared.example", egress_route="direct") is not None:
        raise AssertionError("successful half-open trial did not close shared breaker")

    # Same state and clock produce exactly the same stable jitter.
    def deterministic_delay() -> float:
        state_path.unlink(missing_ok=True)
        clock_value[0] = 3000.0
        test = HostHealth(threshold=3, backoff=10, max_backoff=30,
                          lease_seconds=5, jitter_ratio=0.1, clock=clock)
        test.record_error("jitter.example", egress_route="direct",
                          error_class="target_reset", count=3)
        item = next(iter(test.snapshot()["breakers"].values()))
        return item["until"] - clock_value[0]

    if deterministic_delay() != deterministic_delay():
        raise AssertionError("backoff jitter is not deterministic")

    # Counts represent real attempts.  Reading a warning must never mint one.
    state_path.unlink(missing_ok=True)
    clock_value[0] = 4000.0
    counted = HostHealth(threshold=99, warn_at=4, clock=clock)
    counted.record_error("count.example", egress_route="direct",
                         error_class="target_reset", count=3)
    counted.record_ok("count.example", egress_route="direct", count=1)
    before = counted.snapshot()["totals"][_total_key("direct", "count.example")]["count"]
    if before != 4 or counted.soft_warn("count.example", egress_route="direct") is None:
        raise AssertionError("real request count/warning threshold is wrong")
    after = counted.snapshot()["totals"][_total_key("direct", "count.example")]["count"]
    if after != before:
        raise AssertionError("soft warning was counted as a request")

    # Proxy transport failure is a one-strike manual pause. Time alone never
    # restarts it; only a newer operator-turn timestamp may acknowledge one
    # fresh attempt, and that acknowledgement is not recorded as route health.
    state_path.unlink(missing_ok=True)
    clock_value[0] = 5000.0
    proxy_route = egress_route_id("socks5h://proxy.example:1080")
    proxy_health = HostHealth(threshold=3, backoff=10, max_backoff=30,
                              lease_seconds=5, jitter_ratio=0.1, clock=clock)
    proxy_health.record_error(
        "target.example", egress_route=proxy_route,
        error_class="proxy_connect")
    proxy_pause = proxy_health.proxy_confirmation_state()
    if not proxy_pause["required"] or proxy_pause["routes"] != [proxy_route]:
        raise AssertionError("first proxy failure did not open a route-wide manual pause")
    clock_value[0] = 9000.0
    try:
        proxy_health.check("another.example", egress_route=proxy_route)
        raise AssertionError("proxy route resumed from cooldown without operator confirmation")
    except HostBackoff as exc:
        if exc.phase != "operator_confirmation_required":
            raise
    try:
        proxy_health.acknowledge_proxy_retry(
            confirmed_at=proxy_pause["latest_updated_at"],
            egress_route=proxy_route)
        raise AssertionError("same-turn proxy retry confirmation was accepted")
    except GuardStateError:
        pass
    if not proxy_health.acknowledge_proxy_retry(
            confirmed_at=proxy_pause["latest_updated_at"] + 1.0,
            egress_route=proxy_route):
        raise AssertionError("newer operator proxy confirmation was not consumed")
    confirmed = proxy_health.snapshot()
    if proxy_health.check("another.example", egress_route=proxy_route) is not None:
        raise AssertionError("confirmed proxy retry did not permit one fresh attempt")
    if not any(item["event"] == "operator_confirmed"
               for item in confirmed["provenance"]):
        raise AssertionError("proxy confirmation provenance is missing")
    # One confirmation is bound to the selected proxy route. It must not clear
    # an unrelated failed proxy endpoint from the same shared state file.
    clock_value[0] = 9010.0
    other_proxy_route = egress_route_id("http://other-proxy.example:8080")
    proxy_health.record_error(
        "target.example", egress_route=proxy_route,
        error_class="proxy_connect")
    proxy_health.record_error(
        "target.example", egress_route=other_proxy_route,
        error_class="proxy_connect")
    if not proxy_health.acknowledge_proxy_retry(
            confirmed_at=clock_value[0] + 1.0,
            egress_route=proxy_route):
        raise AssertionError("selected proxy route confirmation was not consumed")
    if proxy_health.proxy_confirmation_state(
            egress_route=proxy_route)["required"]:
        raise AssertionError("selected proxy route remained paused after confirmation")
    other_pause = proxy_health.proxy_confirmation_state(
        egress_route=other_proxy_route)
    if not other_pause["required"] or other_pause["routes"] != [other_proxy_route]:
        raise AssertionError("one confirmation cleared a different proxy route")

    # Valid legacy state migrates without losing its cooldown/count.  Unknown
    # legacy/v2 fields are not silently discarded.
    state_path.write_text(json.dumps({
        "legacy.example": {"errs": 3, "total": 7, "until": clock_value[0] + 10},
    }), encoding="utf-8")
    try:
        HostHealth(clock=clock).check("legacy.example", egress_route="direct")
        raise AssertionError("legacy open breaker was lost during migration")
    except HostBackoff:
        pass
    migrated = HostHealth(clock=clock).snapshot()
    if migrated["schema"] != HOST_HEALTH_SCHEMA or (
            migrated["totals"][_total_key("legacy", "legacy.example")]["count"] != 7):
        raise AssertionError("legacy HostHealth state did not migrate losslessly")
    raw_invalid_host = "one.example two.example"
    state_path.write_text(json.dumps({
        raw_invalid_host: {"errs": 1, "total": 2, "until": 0.0},
    }), encoding="utf-8")
    quarantined = HostHealth(clock=clock).snapshot()
    quarantined_text = json.dumps(quarantined)
    if raw_invalid_host in quarantined_text or not any(
            item["host"].startswith("legacy-invalid-")
            for item in quarantined["totals"].values()):
        raise AssertionError("invalid legacy host was not safely quarantined")
    corrupt = _empty_hosthealth_state()
    corrupt["unknown"] = True
    state_path.write_text(json.dumps(corrupt), encoding="utf-8")
    try:
        HostHealth(clock=clock).snapshot()
        raise AssertionError("unknown HostHealth v2 field failed open")
    except GuardStateError:
        pass

    exception_factories = {
        "gaierror": lambda: urllib.error.URLError(socket.gaierror(
            getattr(socket, "EAI_AGAIN", -3), "temporary failure in name resolution")),
        "ssl": lambda: urllib.error.URLError(ssl.SSLError("TLS handshake failed")),
        "reset": lambda: urllib.error.URLError(ConnectionResetError("connection reset")),
    }
    for case in fixture["classification_cases"]:
        if set(case) != {"name", "exception", "route", "expect"}:
            raise AssertionError(f"classification fixture fields drifted: {case.get('name')}")
        actual = classify_network_error(exception_factories[case["exception"]](),
                                        egress_route=case["route"])
        if actual != case["expect"]:
            raise AssertionError(f"network classification mismatch for {case['name']}: {actual}")

    route = egress_route_id("socks5h://user:secret@proxy.internal:1080")
    if not _ROUTE_RE.fullmatch(route) or any(secret in route for secret in ("user", "secret", "proxy.internal")):
        raise AssertionError("egress route ID leaked proxy endpoint/credentials")
    print("host-health selftest OK (route attribution + half-open + shared counts + migration)")


def _selftest_session_breaker() -> None:
    """Verify the whole-session hard breaker on an ISOLATED state file (never the
    live sessionbudget.json). Trips on count, then on bytes; check() must abort
    while armed and pass after cooldown."""
    fname = "sessionbudget_selftest.json"
    (STATE_DIR / fname).unlink(missing_ok=True)
    try:
        # count trip: 3 reqs with trip_count=3 -> armed -> check() raises
        sb = SessionBudget(trip_count=3, trip_bytes=10**9, cooldown=300, name=fname)
        for _ in range(3):
            sb.record(0)
        try:
            sb.check()
            raise AssertionError("session breaker did NOT trip on count")
        except SessionTripped:
            pass
        # bytes trip on a fresh file
        (STATE_DIR / fname).unlink(missing_ok=True)
        sb2 = SessionBudget(trip_count=10**9, trip_bytes=1024, cooldown=300, name=fname)
        sb2.record(2048)
        try:
            sb2.check()
            raise AssertionError("session breaker did NOT trip on bytes")
        except SessionTripped:
            pass
        # after cooldown expiry, check() passes again
        st = _load(fname); st["until"] = time.time() - 1; _save(fname, st)
        SessionBudget(name=fname).check()      # must not raise
        # B1 regression: one record(count=N) must count N real requests (retries),
        # not 1 — else --retry undercounts the session volume breaker.
        (STATE_DIR / fname).unlink(missing_ok=True)
        sbN = SessionBudget(trip_count=3, trip_bytes=10**9, cooldown=300, name=fname)
        sbN.record(0, count=3)                 # one send() that made 3 real attempts
        try:
            sbN.check()
            raise AssertionError("record(count=3) did not aggregate retries (B1)")
        except SessionTripped:
            pass
        print("session-breaker selftest OK (count trip + bytes trip + cooldown clear + retry-count)")
    finally:
        (STATE_DIR / fname).unlink(missing_ok=True)


class RequestRecorder:
    """统一 HTTP 请求录制器 — 所有攻击请求（probe.py / render.py / 裸 Python script）
    都应通过此层记录，自动生成 .replay.json 证据产物。解决 retrospective #11:
    driver 的 script 攻击和 probe.py 证据采集是两条分离路径，导致 codex 复审时
    无法复核关键攻击行为。

    使用方式（driver 侧；validate 必须在网络 I/O 前调用）:
        rec = RequestRecorder(run_dir)
        rec.validate(method="POST", url="https://target/login",
                     request_body="user=test@example.com")
        rec.record(
            method="POST", url="https://target/login", request_body="user=test@example.com",
            response_status=200, response_body="登录失败", response_headers={"Content-Type": "text/html"},
            artifact_name="login_attempt_1"
        )

    probe.py 内部已通过 --save 自动生成 .replay.json; 此层是给操作者执行的
    author-and-handoff script / framework integration 的桥接。Claude driver 不因
    代码里出现 validate 名字就获得自定义网络脚本 auto-execution 权限。
    record() 对每个 artifact_name 递增编号，避免覆盖。"""

    def __init__(self, run_dir: str | Path):
        self.run_dir = Path(run_dir)
        self.evidence_dir = self.run_dir / "evidence"
        self.evidence_dir.mkdir(parents=True, exist_ok=True)
        self._counter: dict[str, int] = {}

    @staticmethod
    def validate(method: str, url: str, request_body: str = "",
                 request_headers: dict | None = None, *,
                 allow_sensitive_auth: bool = False) -> None:
        """Pre-I/O privacy check for custom scripts using this recorder."""
        privacymod.validate_outbound_request(
            method, url, request_headers or {}, request_body,
            allow_sensitive_auth=allow_sensitive_auth,
        )

    def record(
        self,
        method: str,
        url: str,
        request_body: str = "",
        request_headers: dict | None = None,
        response_status: int = 0,
        response_body: str = "",
        response_headers: dict | None = None,
        artifact_name: str = "script_request",
        note: str = "",
    ) -> Path:
        """记录一次 HTTP 请求-响应对，写入 .replay.json 到 evidence/ 目录。
        文件名: <artifact_name>.replay.json (首次); 若文件已存在, 自动递增为 _2, _3 …。
        跨调用安全: 每次调用扫描 evidence/ 目录已有文件, 避免覆盖之前的录像(W5)。
        不做名称 strip —— 原样保留 artifact_name 中的数字(如 port_8080)(W3)。"""
        import hashlib
        base = artifact_name.replace(".replay.json", "")
        # W5: scan filesystem for existing files to avoid cross-invocation overwrites
        # Match: <base>.replay.json, <base>_2.replay.json, <base>_3.replay.json ...
        existing = [p for p in self.evidence_dir.glob(f"{base}*.replay.json")
                    if p.name.replace(".replay.json", "") == base
                    or p.name.replace(".replay.json", "").startswith(f"{base}_")]
        idx = len(existing) + 1
        # Also consider in-memory counter for dedup within this instance
        in_mem = self._counter.get(base, 0)
        idx = max(idx, in_mem + 1)
        self._counter[base] = idx
        filename = f"{base}.replay.json" if idx == 1 else f"{base}_{idx}.replay.json"

        body_hash = hashlib.sha256(response_body.encode("utf-8", errors="replace")).hexdigest()[:16]
        safe_request, request_privacy = privacymod.sanitize_request_record(
            method, url, request_headers or {}, request_body,
        )
        safe_response, response_redactions = privacymod.sanitize_response_record(
            response_status, response_headers, response_body[:500],
        )
        record = {
            "method": safe_request["method"],
            "url": safe_request["url"],
            "request_body": safe_request["body"],
            "request_headers": safe_request["headers"],
            "response_status": response_status,
            "response_body_sha256": body_hash,
            "response_body_preview": safe_response["body_preview"],
            "response_headers": safe_response["headers"],
            "privacy": {
                **request_privacy,
                "response_redactions": response_redactions,
            },
            "note": privacymod.sanitize_text_for_log(note),
            "recorded_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        }
        out = self.evidence_dir / filename
        out.write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8")
        return out


if __name__ == "__main__":
    # Quick smoke tests run in an isolated state root.  Executing the test suite
    # must not consume the live engagement's rate/request/breaker budget.
    with _selftest_state_isolation():
        rl = RateLimiter()
        rl.gate("example.com")
        body, trunc = cap_body(b"x" * (MAX_BODY_BYTES + 1))
        print(f"guard OK; cap truncated={trunc} len={len(body)}; "
              f"outstanding uploads={len(UploadRegistry().outstanding())}")
        _selftest_hosthealth_route_breaker()
        _selftest_session_breaker()
    # smoke-test RequestRecorder
    import tempfile
    d = Path(tempfile.mkdtemp())
    rr = RequestRecorder(d)
    p = rr.record(
        method="POST", url="https://x/login", response_status=200,
        response_body='{"token":"response-secret","email":"person@real.example.cn"}',
        response_headers={"Content-Type": "application/json"},
        artifact_name="test_login",
    )
    assert p.exists(), "recorder output missing"
    assert "test_login.replay.json" in str(p)
    recorded = p.read_text(encoding="utf-8")
    assert "response-secret" not in recorded, "response secret persisted in replay preview"
    assert "person@real.example.cn" not in recorded, "response PII persisted in replay preview"
    print("RequestRecorder smoke-test OK")
