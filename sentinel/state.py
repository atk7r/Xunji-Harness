"""sentinel.state — persistent, cross-process session state + run-ledger access.

Mirrors guard.py's locking discipline so the behavior monitor's state survives
across separate hook invocations (each hook call is a fresh process). State lives
under tools/harness/.state/sentinel/ which is already gitignored.
"""

from __future__ import annotations

import contextlib
import json
import re
import time
from pathlib import Path

try:                       # Windows
    import msvcrt
except ImportError:        # pragma: no cover
    msvcrt = None
try:                       # POSIX
    import fcntl
except ImportError:        # pragma: no cover
    fcntl = None

ROOT = Path(__file__).resolve().parents[1]
STATE_DIR = ROOT / "tools" / "harness" / ".state" / "sentinel"
RUNS_DIR = ROOT / "runs"
_LOCK_PATH = STATE_DIR / ".lock"


def _ensure() -> None:
    STATE_DIR.mkdir(parents=True, exist_ok=True)


@contextlib.contextmanager
def state_lock(max_wait: float = 10.0):
    """Cross-process exclusive lock serializing sentinel state read-modify-write.
    Best-effort: if locking is unavailable, proceed (observe-only, never blocks work)."""
    _ensure()
    fh = open(_LOCK_PATH, "a+")
    try:
        deadline = time.monotonic() + max_wait
        while True:
            try:
                if msvcrt is not None:
                    msvcrt.locking(fh.fileno(), msvcrt.LK_LOCK, 1)
                elif fcntl is not None:
                    fcntl.flock(fh.fileno(), fcntl.LOCK_EX)
                break
            except OSError:
                if time.monotonic() > deadline:
                    break                      # give up the lock, still proceed
                time.sleep(0.05)
        yield
    finally:
        try:
            if msvcrt is not None:
                fh.seek(0)
                msvcrt.locking(fh.fileno(), msvcrt.LK_UNLCK, 1)
            elif fcntl is not None:
                fcntl.flock(fh.fileno(), fcntl.LOCK_UN)
        except OSError:
            pass
        fh.close()


def load(name: str) -> dict:
    p = STATE_DIR / name
    if not p.exists():
        return {}
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return {}


def save(name: str, obj: dict) -> None:
    _ensure()
    (STATE_DIR / name).write_text(
        json.dumps(obj, ensure_ascii=False, indent=2), encoding="utf-8")


def now() -> str:
    return time.strftime("%Y-%m-%d %H:%M:%S")


# --- run-ledger access (the declared-intent baseline) ------------------------

def active_run() -> Path | None:
    """The current engagement = the runs/<dir> whose target.md was modified most
    recently. Heuristic, sufficient for observe-only Phase 1."""
    if not RUNS_DIR.exists():
        return None
    candidates = [p.parent for p in RUNS_DIR.glob("*/target.md")]
    if not candidates:
        return None
    return max(candidates, key=lambda d: (d / "target.md").stat().st_mtime)


_HOST_RE = re.compile(r"https?://([^/\s:]+)|(\b\d{1,3}(?:\.\d{1,3}){3}\b)")
# Bare domains too: a target.md that says "Target: example.com" (no http://, no IP)
# used to extract NOTHING -> empty scope -> every in-scope action looked
# out-of-scope -> false scope_drift + breaker accumulation (a real-run bug).
# label count bounded {1,16} to avoid catastrophic backtracking on a pathological
# many-dotted line (an operator-authored target.md line could otherwise stall the
# state-lock for tens of seconds).
_DOMAIN_RE = re.compile(
    r"(?:\*\.)?((?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.){1,16}[a-z]{2,})", re.I)
# suffixes that look like domains but are filenames/markup, so they are not scope.
_NON_TLD = {"md", "py", "json", "txt", "html", "htm", "css", "js", "aspx", "ashx",
            "asmx", "php", "jsp", "log", "bin", "png", "jpg", "jpeg", "gif", "svg",
            "xml", "yml", "yaml", "ini", "cfg", "sh", "ps1", "go", "exe", "zip"}
# lines that EXCLUDE hosts from scope — never harvest their domains as in-scope, or
# an `Out-of-scope: partner-bank.com` line would mute scope_drift on that host.
_EXCL_RE = re.compile(
    r"out[\s-]?of[\s-]?scope|exclu|black\s?list|deny\s?list|do not|don't|"
    r"不测|排除|禁止|黑名单|不在范围|白名单之外", re.I)


def scope_hosts(run: Path | None) -> set[str]:
    """Parse In-scope hosts from target.md (the engagement scope). Extracts URLs,
    bare IPv4, AND bare domains (so a plain `Target: example.com` defines scope)."""
    if run is None:
        return set()
    tgt = run / "target.md"
    if not tgt.exists():
        return set()
    text = tgt.read_text(encoding="utf-8", errors="replace")
    hosts: set[str] = set()
    for line in text.splitlines():
        low = line.lower()
        if _EXCL_RE.search(low):
            continue                       # exclusion line: do not harvest as in-scope
        if "in-scope" in low or "target:" in low or "scope" in low:
            for m in _HOST_RE.finditer(line):
                h = (m.group(1) or m.group(2) or "").lower()
                if h:
                    hosts.add(h)
            for m in _DOMAIN_RE.finditer(line):
                dom = m.group(1).lower()
                if dom.rsplit(".", 1)[-1] not in _NON_TLD:
                    hosts.add(dom)
    return {h for h in hosts if h}


def plan_keywords(run: Path | None) -> list[str]:
    """Coarse keyword set from the declared plan (frontier/decisions) for the
    plan-deviation detector. Phase 1: scope hosts + front/decision tokens."""
    kws: set[str] = set(scope_hosts(run))
    if run is None:
        return list(kws)
    for name in ("frontier.md", "decisions.md", "hypotheses.md"):
        p = run / name
        if not p.exists():
            continue
        text = p.read_text(encoding="utf-8", errors="replace").lower()
        for tok in re.findall(r"[a-z_]{4,}", text):
            kws.add(tok)
    return list(kws)


def parse_hint_directives(text: str) -> list[str]:
    """Pure: from hints.md text, return the Hint texts of HINT nodes that AUTHORIZE
    an action — Kind is a **pure directive** (do/skip/prioritize/open/close).

    Excluded on purpose (WORKFLOW-reference.md hints.md 'Absorb by Kind'):
    - lead / claim  -> <=0.5 intel to verify, never authorization.
    - constraint    -> a scope/boundary rule (handled by scope_hosts), not action
      authorization; e.g. '只测 host X' must NOT auto-authorize --dump against X.
    So a Kind tagged both 'constraint' and 'directive' is treated as a constraint
    (conservative: it does not grant action authorization)."""
    out: list[str] = []
    for block in re.split(r"(?=^##\s+HINT-)", text, flags=re.MULTILINE):
        if not block.lstrip().startswith("## HINT-"):
            continue
        km = re.search(r"^-\s*Kind:\s*(.+)$", block, re.MULTILINE)
        if not km:
            continue
        kind = km.group(1).lower()
        if "directive" not in kind or any(k in kind for k in ("constraint", "lead", "claim")):
            continue
        hm = re.search(r"^-\s*Hint:\s*(.+?)(?=^-\s|\Z)", block, re.MULTILINE | re.DOTALL)
        if hm:
            out.append(" ".join(hm.group(1).split()))
    return out


def operator_hints(run: Path | None) -> list[str]:
    """Directive-kind HINT texts from runs/<target>/hints.md (operator authorization
    source). Re-read each cycle so mid-run injected steering is honored."""
    if run is None:
        return []
    p = run / "hints.md"
    if not p.exists():
        return []
    return parse_hint_directives(p.read_text(encoding="utf-8", errors="replace"))


def append_alert(run: Path | None, block: str) -> None:
    """Append a behavioral alert to runs/<target>/alerts.md (observe-only output)."""
    if run is None:
        run = STATE_DIR        # fall back to state dir if no active run
    p = run / "alerts.md"
    header = "" if p.exists() else "# Behavioral Alerts (sentinel, observe-only)\n\n"
    with p.open("a", encoding="utf-8") as fh:
        fh.write(header + block.rstrip() + "\n\n")


def append_pending(run: Path | None, block: str) -> None:
    """Append an L2 operator-review item to runs/<target>/pending_approval.md
    (the red-team-mode queue: agent authored the action; operator approves/rejects)."""
    if run is None:
        run = STATE_DIR
    p = run / "pending_approval.md"
    header = "" if p.exists() else (
        "# Pending Approval — L2 (sentinel, observe-only)\n\n"
        "Operator-review queue for level-2 (red-team) actions. observe-only: these\n"
        "actions were NOT held; once inline enforcement is on, L2 waits here for your\n"
        "approve/reject. L1 runs unattended; L3 is hard-blocked (see alerts.md).\n\n")
    with p.open("a", encoding="utf-8") as fh:
        fh.write(header + block.rstrip() + "\n\n")
