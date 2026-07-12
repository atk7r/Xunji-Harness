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
    # quick smoke test
    rl = RateLimiter()
    rl.gate("example.com")
    body, trunc = cap_body(b"x" * (MAX_BODY_BYTES + 1))
    print(f"guard OK; cap truncated={trunc} len={len(body)}; "
          f"outstanding uploads={len(UploadRegistry().outstanding())}")
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
