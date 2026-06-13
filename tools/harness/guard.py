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
import json
import os
import time
from pathlib import Path

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
# --- Self-throttle circuit breaker (防止打爆自己对目标的访问) ------------------
HOST_ERR_THRESHOLD = 3        # 连续传输错误(超时/RST/拒绝)达此值 -> 熔断该 host
HOST_BACKOFF_SEC = 120        # 熔断冷却时长(秒); 期间对该 host 的请求直接抛 HostBackoff
HOST_REQ_WARN = 30           # 单 host 累计请求软告警阈值(只提示, 不阻断)
# --- 全局会话请求预算 (跨 host; ① 是单 host, 这个管整场总量) -------------------
SESSION_WINDOW_SEC = 600      # 滑动窗口(秒)
SESSION_WARN_COUNT = 200      # 窗口内总请求达此值 -> 软告警(整场量偏高, 考虑收敛/换出口)
# --- 全局会话硬熔断 (Part A: 软告警之上的真·工具层熔断, 整场失控时 abort) --------
SESSION_TRIP_COUNT = 800      # 窗口内总请求达此值 -> 硬熔断(布防冷却, check() 抛 SessionTripped)
SESSION_TRIP_BYTES = 16 * 1024 * 1024   # 窗口内累计保留响应字节达此值 -> 硬熔断(防整场拖量)
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


class HostBackoff(Exception):
    """Raised when a host has refused/reset/timed out HOST_ERR_THRESHOLD times in
    a row and is in cooldown. This protects *our own access*: hammering a host
    that has started blocking us only deepens the block and produces misleading
    'all blocked' conclusions. The driver should pause that host (or switch
    egress), not keep firing."""


class HostHealth:
    """Per-host transport-error circuit breaker (state in hosthealth.json).

    A TRANSPORT error (timeout / connection reset / refused) means the host is
    failing us — record_error. An HTTP response of any status (incl. 4xx/5xx)
    means the connection is healthy — record_ok (resets the streak). After
    HOST_ERR_THRESHOLD consecutive transport errors the host enters a
    HOST_BACKOFF_SEC cooldown; check() then raises HostBackoff until it expires.
    """

    def __init__(self, threshold: int = HOST_ERR_THRESHOLD,
                 backoff: float = HOST_BACKOFF_SEC, warn_at: int = HOST_REQ_WARN):
        self.threshold = threshold
        self.backoff = backoff
        self.warn_at = warn_at

    def _state(self, host: str) -> dict:
        return _load("hosthealth.json").get(host, {"errs": 0, "total": 0, "until": 0.0})

    def check(self, host: str) -> None:
        st = self._state(host)
        remain = st.get("until", 0.0) - time.time()
        if remain > 0:
            raise HostBackoff(
                f"host '{host}' is in self-throttle backoff for {remain:.0f}s more "
                f"({self.threshold} consecutive transport failures). Pause this host "
                "or switch egress — do not keep firing (避免打爆自己 / 误判'全封')."
            )

    def record_ok(self, host: str) -> None:
        with _state_lock():
            all_st = _load("hosthealth.json")
            st = all_st.get(host, {"errs": 0, "total": 0, "until": 0.0})
            st["errs"] = 0
            st["total"] = st.get("total", 0) + 1
            st["until"] = 0.0
            all_st[host] = st
            _save("hosthealth.json", all_st)

    def record_error(self, host: str) -> None:
        with _state_lock():
            all_st = _load("hosthealth.json")
            st = all_st.get(host, {"errs": 0, "total": 0, "until": 0.0})
            st["errs"] = st.get("errs", 0) + 1
            st["total"] = st.get("total", 0) + 1
            if st["errs"] >= self.threshold:
                st["until"] = time.time() + self.backoff
            all_st[host] = st
            _save("hosthealth.json", all_st)

    def soft_warn(self, host: str) -> str | None:
        """Return a non-blocking warning string once a host crosses the request
        volume threshold (helps the driver notice it is probing one host hard)."""
        st = self._state(host)
        if st.get("total", 0) and st["total"] % self.warn_at == 0:
            return (f"[guard] 已对 {host} 发出 {st['total']} 次请求 — 注意请求量, "
                    "目标可能开始限流(放缓/换面/换出口)")
        return None


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

    def record(self, nbytes: int = 0) -> str | None:
        """Post-response: count the request + retained bytes; arm the hard breaker
        on count OR volume; return a soft/arming warning string (or None)."""
        with _state_lock():
            st = _load(self.name)
            now = time.time()
            reqs = [t for t in st.get("reqs", []) if now - t < self.window]
            reqs.append(now)
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
    capped by RateLimiter. This only stops a buggy unbounded auth loop."""

    def __init__(self, limit: int = AUTH_FAIL_LOCK):
        self.limit = limit

    def check(self, key: str) -> None:
        st = _load("authfail.json")
        if st.get(key, 0) >= self.limit:
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
        print("session-breaker selftest OK (count trip + bytes trip + cooldown clear)")
    finally:
        (STATE_DIR / fname).unlink(missing_ok=True)


if __name__ == "__main__":
    # quick smoke test
    rl = RateLimiter()
    rl.gate("example.com")
    body, trunc = cap_body(b"x" * (MAX_BODY_BYTES + 1))
    print(f"guard OK; cap truncated={trunc} len={len(body)}; "
          f"outstanding uploads={len(UploadRegistry().outstanding())}")
    _selftest_session_breaker()
