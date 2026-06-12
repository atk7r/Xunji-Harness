#!/usr/bin/env python3
"""Proof-only verification enforcement guard (shared by all active tools).

This is the machine-enforced floor that makes AI autonomy safe: the active
tools (probe / render / scan) MUST route through these guards. The few hard
limits from src-safety-boundary become code, not prose:

- RateLimiter      -> 禁 DoS/高频  (global + per-host token bucket)
- cap_body         -> 禁拖库/取他人数据 (truncate oversized responses)
- AuthFailCounter  -> 防失控 (stop probe's auth loop after N fails; a real
                     brute/spray run uses a separate, operator-gated tool)
- UploadRegistry   -> 不留后门残留 (every test artifact is tracked for cleanup)

Pure stdlib. State persists under tools/harness/.state/ so limits hold across
separate tool invocations (each Bash call is a fresh process).
"""

from __future__ import annotations

import json
import time
from pathlib import Path

STATE_DIR = Path(__file__).resolve().parent / ".state"
STATE_DIR.mkdir(parents=True, exist_ok=True)

# --- Hard caps (deliberately conservative; tune in one place only) -----------
GLOBAL_MAX_RPS = 2.0          # 禁高频: global requests/sec ceiling
PER_HOST_MAX_RPS = 1.0        # per-host ceiling
MAX_BODY_BYTES = 256 * 1024   # 禁拖库: refuse to retain bodies bigger than this
AUTH_FAIL_LOCK = 5            # anti-runaway: stop probe's auth loop after this many fails (raisable per run)


def _now() -> float:
    return time.monotonic()


def _load(name: str) -> dict:
    p = STATE_DIR / name
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _save(name: str, data: dict) -> None:
    (STATE_DIR / name).write_text(json.dumps(data), encoding="utf-8")


class RateBudgetExceeded(Exception):
    """Raised when a request would exceed the rate ceiling. Tools must abort,
    not sleep-and-retry in a tight loop (that would itself become a flood)."""


class BruteforceLock(Exception):
    """Raised when probe hits too many auth failures on one endpoint -> stop the
    automated loop. Anti-runaway throttle, NOT a policy ban: probe is a proof
    tool, not a brute-forcer. Raise/disable AUTH_FAIL_LOCK, or use a dedicated
    (operator-gated) brute/spray tool, for a real credential run."""


class RateLimiter:
    """Wall-clock spacing enforcer. Call gate(host) immediately before each
    request. It blocks the minimum time needed to honor the ceilings, and hard
    aborts if the caller is trying to burst far past budget."""

    def __init__(self, global_rps: float = GLOBAL_MAX_RPS, host_rps: float = PER_HOST_MAX_RPS):
        self.min_global = 1.0 / max(global_rps, 0.01)
        self.min_host = 1.0 / max(host_rps, 0.01)

    def gate(self, host: str, max_wait: float = 10.0) -> None:
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
    has accumulated AUTH_FAIL_LOCK failures. This makes 'try another password'
    structurally impossible past the threshold."""

    def __init__(self, limit: int = AUTH_FAIL_LOCK):
        self.limit = limit

    def check(self, key: str) -> None:
        st = _load("authfail.json")
        if st.get(key, 0) >= self.limit:
            raise BruteforceLock(
                f"endpoint '{key}' hit {self.limit} auth failures; probe stopped "
                "(anti-runaway lock; raise AUTH_FAIL_LOCK or use a dedicated brute tool)"
            )

    def record(self, key: str, ok: bool) -> None:
        st = _load("authfail.json")
        st[key] = 0 if ok else st.get(key, 0) + 1
        _save("authfail.json", st)


class UploadRegistry:
    """Tracks every artifact an upload-test puts on a target so the run can
    prove it was removed (不留后门残留). Confirming an upload vuln is only
    allowed once the artifact is registered here AND a cleanup is recorded."""

    def register(self, run: str, target: str, remote_ref: str, note: str = "") -> None:
        st = _load("uploads.json")
        st.setdefault(run, []).append(
            {"target": target, "ref": remote_ref, "note": note,
             "ts": time.strftime("%Y-%m-%d %H:%M:%S"), "cleaned": False}
        )
        _save("uploads.json", st)

    def mark_cleaned(self, run: str, remote_ref: str) -> None:
        st = _load("uploads.json")
        for item in st.get(run, []):
            if item["ref"] == remote_ref:
                item["cleaned"] = True
        _save("uploads.json", st)

    def outstanding(self, run: str | None = None) -> list[dict]:
        st = _load("uploads.json")
        runs = [run] if run else list(st)
        return [it for r in runs for it in st.get(r, []) if not it["cleaned"]]


if __name__ == "__main__":
    # quick smoke test
    rl = RateLimiter()
    rl.gate("example.com")
    body, trunc = cap_body(b"x" * (MAX_BODY_BYTES + 1))
    print(f"guard OK; cap truncated={trunc} len={len(body)}; "
          f"outstanding uploads={len(UploadRegistry().outstanding())}")
