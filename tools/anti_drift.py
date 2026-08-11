#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Anti-drift anchor — re-injects binding rules + active-run process-state every turn.

Why: standing rules (system prompt / CLAUDE.md / memory) sit in EARLY context and lose attention
weight as the session grows ("Lost in the Middle"; "LLMs Get Lost in Multi-Turn Conversation").
The operator kept having to remind the driver of both GOAL and PROCESS. This runs as a
UserPromptSubmit hook so its output lands in the RECENCY zone every turn — the rules + the run's
overdue process steps are surfaced where attention is high, mechanically, not by the model
remembering and not by the operator reminding.

It is ADVISORY (injects context; never blocks — that stays the deterministic gates safety_gate /
run_gate / check_run). FAIL-OPEN: any error prints the static rules and exits 0; a context
injector must never break a turn. Process-state is DERIVED from the run files (reuse check_run),
not self-reported — a drifted self-report would just re-encode the drift.

Reason-pass freshness is content-based: a versioned, hash-chained receipt binds the Root's
read/adjudication claim to a stable canonical digest snapshot. The receipt is derived audit state,
not proof that a model actually read the files, and never grants authority, evidence promotion, or
closure. Operational liveness is projected separately from journals/runtime/Agent receipts and is
never inferred from canonical-file mtimes.

Two modes (config.ini [mode] mode=):
  normal — full workflow: repeated drift may block and Normal-only review/completion prerequisites apply
  dev    — development observability: drift records/reminds without that block; hard safety/evidence/Coda/closure-integrity gates still run

Usage:
    python tools/anti_drift.py            # print the anchor (UserPromptSubmit hook target)
    python tools/anti_drift.py --selftest # offline regression
    python tools/anti_drift.py --semantic-status runs/<dir>
    python tools/anti_drift.py --record-reason-pass runs/<dir> \
        --chosen-front F-001 --reason "whole-graph adjudication"
"""
from __future__ import annotations

import argparse
import contextlib
import hashlib
import json
import os
import re
import sys
import time
from pathlib import Path

import contract_schema

try:
    import fcntl
except ImportError:  # pragma: no cover - Windows fallback remains process-local
    fcntl = None

try:
    sys.stdout.reconfigure(encoding="utf-8")       # type: ignore[attr-defined]
except Exception:
    pass

ROOT = Path(__file__).resolve().parents[1]
RUNS = ROOT / "runs"
ACTIVE_RUN_POINTER = Path(os.environ.get(
    "XUNJI_ACTIVE_RUN_FILE", str(ROOT / ".claude" / "xunji_active_run")))
CONFIG_INI = ROOT / "config.ini"
CONFIG_EXAMPLE_INI = ROOT / "config.example.ini"
ACTIVE_WINDOW_SEC = 6 * 3600   # a run that saw any file change in the last 6h = the one in flight
SESSION_STATE_STALE_SEC = 50 * 60  # session_state.json stale threshold

# Semantic anti-drift is intentionally separate from session/output liveness.
# Reason-pass receipts are derived audit claims: canonical Markdown/coverage
# remains the source of truth, and a receipt never grants authority or closure.
REASON_PASS_SCHEMA = "xunji.reason-pass.v1"
REASON_PASS_RECEIPTS = "reason_pass_receipts.jsonl"
REASON_PASS_MAX_BYTES = 8 * 1024 * 1024
REASON_PASS_MAX_RECORDS = 4096
NO_SEMANTIC_PROGRESS_THRESHOLD = 3
REASON_PASS_DIGEST_FIELDS = (
    "frontier_digest",
    "evidence_digest",
    "coverage_digest",
    "decision_digest",
    "graph_digest",
)
TRAJECTORY_DIGEST_FIELDS = (
    "frontier_digest",
    "evidence_digest",
    "coverage_digest",
    "graph_digest",
)
_REASON_PASS_FIELDS = {
    "schema",
    "run_id",
    "cycle_id",
    *REASON_PASS_DIGEST_FIELDS,
    "read_at",
    "chosen_front",
    "reason",
    "previous_receipt_hash",
    "receipt_hash",
}
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_CYCLE_FRONT_RE = re.compile(r"^(?:F-[0-9]+[A-Za-z]*|NONE)$")

_TOOLS_PATH = str(ROOT / "tools")
if _TOOLS_PATH not in sys.path:
    sys.path.insert(0, _TOOLS_PATH)

# ---- Mode detection (Decision 3: single parse, 5s cache) ----
_mode_cache: tuple[float, str] = (0.0, "normal")
SENTINEL_PENDING_SCAN_LIMIT = 1024 * 1024
SENTINEL_ALERT_TAIL_LIMIT = 256 * 1024
_SENTINEL_PENDING_RE = re.compile(
    r"Status\s*:\s*\[\s*\]\s*pending\s*$", re.IGNORECASE
)
_SENTINEL_ALERT_ACK_RE = re.compile(
    r"(?im)^\s*[-*]?\s*SentinelAlertsAck\s*[:：]\s*sha256:([0-9a-f]{64})\s*$"
)


def get_mode() -> str:
    """Read local/example config [mode] once per 5s. Returns 'normal' | 'dev'."""
    global _mode_cache
    now = time.time()
    if now - _mode_cache[0] < 5.0:
        return _mode_cache[1]
    try:
        import configparser
        cp = configparser.ConfigParser()
        cp.read([str(CONFIG_EXAMPLE_INI), str(CONFIG_INI)], encoding="utf-8")
        mode = cp.get("mode", "mode", fallback="normal").strip().lower()
        if mode not in ("normal", "dev"):
            mode = "normal"
        _mode_cache = (now, mode)
        return mode
    except Exception:
        _mode_cache = (now, "normal")
        return "normal"


def is_dev_mode() -> bool:
    return get_mode() == "dev"


def is_normal_mode() -> bool:
    return get_mode() == "normal"


def _normal_completion_committed(run: Path) -> bool:
    """Return true only for a valid NORMAL completion owner transaction."""
    try:
        import completion_transaction
        if not completion_transaction.is_valid_committed(run):
            return False
        decisions = (run / "decisions.md").read_text(
            encoding="utf-8", errors="replace")
        return bool(re.search(
            r"(?m)^\s*NORMAL_COMPLETE\s+receipt=[0-9a-f]{64}\s*$",
            decisions,
        ))
    except Exception:
        return False

# Binding rules — split into three tiers so primacy/recency work for us, not against us.
# Tier-1 (TOP — "本轮必做"): immediate action rules. Placed first so the model sees them at the
#   highest-attention primacy position every turn.
# Tier-2 (MID — state injected dynamically by build_anchor).
# Tier-3 (BOTTOM — "约束速查"): constraints, format rules, gating. Placed last so they sit in the
#   recency zone as a final check before the model produces output.
BINDING_RULES_TIER1 = [   # TOP: 本轮必做 — placed at primacy position
    "回合优先级: receipt-backed TARGET_DENIED 只输出 output_gate exact envelope; MAINTENANCE 拒绝/失败不得声称成功, 修正 typed path/argv 后可同回合重试; 否则 safe 前沿还在就自主推进, 未完成时只用唯一「下一行动」收尾(普通 BLOCKED 无效)",
    "Reason pass: 每轮重读整个 frontier.md(所有 open+deferred)并结合 evidence/coverage/graph 裁定后写 v1 receipt; 内容未变可只读确认, 禁止 freshness touch/edit",
    "联网检索走唯一 owner: 每次公共 WebSearch 前按 .claude/skills/web-research/SKILL.md 先执行已注册的 python3 tools/timestamp_gate.py --search-hint --kind vuln 并遵守输出; 非 CVE/CNVD 用 --kind generic; active run 不用 WebFetch",
    "CVE触发: live evidence 识别产品+版本/组件版本/CVE或advisory线索时, 同轮走 web-research 的 time gate → xunji-knowledge-flywheel → 公共 WebSearch → structured lead; Root 记录后再关闭或定级",
    "操作者约束持久化: 收到 directive/constraint 后先更新 hints.md(HINT-xxx, Kind=directive/constraint, Status=pending) 再继续; 每轮 Reason pass 无条件 Read hints.md —— constraint 是全 run 级原则非当前前沿上下文, 跨轮有效直到操作者显式解除",
    "Knowledge-first: 识别到产品签名后, WebSearch 前先路由 xunji-knowledge-flywheel 读取匹配接地条目; 不在 anti-drift 复制命令; 消费错误厂商 CVE 而正确 knowledge 未读 = 协议错误",
]
BINDING_RULES_TIER3 = [   # BOTTOM: 约束速查 — placed at recency position
    "消费 Guanlan、跳过不可达; 不重做 OSINT / 不建 egress·relay·重探",
    "前沿只重排不关闭(关闭是 Reviewer 的事); BLOCKED 先判 A类(可打破) vs B类(关闭/延迟)",
    "证据门: 负面/环境结论也存盘产物; 先验证再给 ≥0.8; 单一来源/样例模板=≤0.5; scripts/散文不替代产物+control/replication",
    "复审路由: 当前证据 fingerprint 触发独立复审时加载 xunji-reviewops; Agent Reviewer/手填 review.md 不替代 ReviewReceipt",
    "任何代码/文档修改必须经过 codex 复审; codex 必须走专用代理(CODEX_PROXY)",
    "不过度工程(画蛇添足); 能进代码闸门的别写 prose · 中文回答",
    "联网搜索 tripwire: WebSearch/CVE 引用输出前必须已跑 timestamp_gate 并逐条执行 search_hint; active run WebFetch 被代理门拒绝; 未跑 = 不得引用, 跳过 = 协议错误",
    "爆破预算: 同一端点连续爆破 25+ 次无果 → 强制断言 Type B, 转向逻辑漏洞/未授权API(IDOR/路径穿越/配置错误), 不要继续试更多密码(retrospective #4: 500+ 次猜测 0 成功)",
    "攻击录证: certainty≥0.8 的关键主动行为必须通过已注册 recorder/probe 留 request receipt 和产物; 不重构未注册 Python 录证片段, 不把散文当证据",
]

# Output drift patterns — driver response containing any of these = protocol violation.
# Codex review checks for these in review.md; the closure gate hard-blocks unresolved violations.
DRIFT_PATTERNS = [
    "是否继续", "要不要继续", "还是等其他条件", "请指示下一步",
    "需要我继续", "等待用户", "你决定", "需要继续吗",
    "I can continue if", "Should I continue", "wait for",
]


def _valid_ts(value, now: float) -> float:
    """Validate timestamp: must be float, non-negative, not in future (+60s skew). Returns 0.0 on failure."""
    try:
        ts = float(value)
    except Exception:
        return 0.0
    if ts < 0 or ts > now + 60:
        return 0.0
    return ts


def _json_bytes(value: object) -> bytes:
    """Stable JSON encoding used by semantic digests and receipt hashes."""
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")


def _sha256(value: object) -> str:
    return hashlib.sha256(_json_bytes(value)).hexdigest()


def _normalise_markdown(text: str) -> str:
    """Ignore transport-only newline/trailing-space churn, not semantic prose."""
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    return "\n".join(line.rstrip() for line in text.split("\n")).rstrip("\n") + "\n"


def _markdown_value(path: Path) -> dict:
    if not path.exists():
        return {"present": False, "text": ""}
    if not path.is_file():
        raise ValueError(f"canonical path is not a file: {path}")
    return {
        "present": True,
        "text": _normalise_markdown(path.read_text(encoding="utf-8", errors="replace")),
    }


def _coverage_value(run_dir: Path) -> list[dict]:
    """Return semantic coverage inputs without consuming derived state caches."""
    out: list[dict] = []
    for rel in (Path("coverage.json"), Path("classify") / "coverage.json"):
        path = run_dir / rel
        if not path.exists():
            continue
        if not path.is_file():
            raise ValueError(f"coverage path is not a file: {path}")
        raw = path.read_text(encoding="utf-8", errors="replace")
        try:
            value: object = json.loads(raw)
            out.append({"path": rel.as_posix(), "valid_json": True, "value": value})
        except Exception:
            # Malformed coverage still changes freshness deterministically.  The
            # coverage/evidence gates remain responsible for rejecting it.
            out.append({
                "path": rel.as_posix(),
                "valid_json": False,
                "text": _normalise_markdown(raw),
            })
    return out


def _graph_value(run_dir: Path) -> dict:
    """Build the graph from canonical inputs; never trust a stale graph.json cache."""
    try:
        import graph as graph_model
        value = graph_model.build_graph(run_dir)
    except Exception as exc:
        raise ValueError(f"cannot derive canonical graph: {type(exc).__name__}: {exc}") from exc
    if not isinstance(value, dict):
        raise ValueError("canonical graph builder returned a non-object")
    return value


def canonical_reason_pass_digests(run_dir: str | Path) -> dict[str, str]:
    """Compute the five versioned Reason-pass digests without writing run files."""
    run = Path(run_dir).resolve()
    if not run.is_dir():
        raise FileNotFoundError(f"run directory does not exist: {run}")
    return {
        "frontier_digest": _sha256(_markdown_value(run / "frontier.md")),
        "evidence_digest": _sha256(_markdown_value(run / "evidence.md")),
        "coverage_digest": _sha256(_coverage_value(run)),
        "decision_digest": _sha256(_markdown_value(run / "decisions.md")),
        "graph_digest": _sha256(_graph_value(run)),
    }


def _stable_reason_pass_digests(run_dir: Path) -> dict[str, str]:
    """Reject a torn snapshot if canonical inputs change while being hashed."""
    first = canonical_reason_pass_digests(run_dir)
    second = canonical_reason_pass_digests(run_dir)
    if first != second:
        changed = sorted(k for k in first if first.get(k) != second.get(k))
        raise RuntimeError(
            "canonical Reason-pass inputs changed during snapshot: " + ", ".join(changed)
        )
    return second


def _reason_pass_path(run_dir: Path) -> Path:
    return run_dir / "state" / REASON_PASS_RECEIPTS


@contextlib.contextmanager
def _reason_pass_lock(run_dir: Path):
    path = run_dir / "state" / ".reason_pass.lock"
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a+", encoding="utf-8") as handle:
        if fcntl is not None:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
        try:
            yield
        finally:
            if fcntl is not None:
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def _receipt_hash(receipt: dict) -> str:
    unsigned = dict(receipt)
    unsigned.pop("receipt_hash", None)
    return _sha256(unsigned)


def validate_reason_pass_receipt(
    receipt: object,
    *,
    run_id: str = "",
    now: float | None = None,
) -> list[str]:
    """Validate one v1 receipt structurally and cryptographically.

    Unknown schemas and fields fail closed.  This validates the receipt claim,
    not the historical truth of what the model read; current canonical equality
    is checked separately by :func:`semantic_freshness`.
    """
    if not isinstance(receipt, dict):
        return ["receipt is not an object"]
    if receipt.get("schema") != REASON_PASS_SCHEMA:
        return [f"unknown reason-pass schema: {receipt.get('schema')!r}"]
    errors: list[str] = contract_schema.named_schema_errors(
        receipt, "reason-pass-receipt.v1.schema.json")
    keys = set(receipt)
    missing = sorted(_REASON_PASS_FIELDS - keys)
    extra = sorted(keys - _REASON_PASS_FIELDS)
    if missing:
        errors.append("missing field(s): " + ", ".join(missing))
    if extra:
        errors.append("unknown field(s): " + ", ".join(extra))
    value_run_id = receipt.get("run_id")
    if not isinstance(value_run_id, str) or not value_run_id or len(value_run_id) > 255:
        errors.append("run_id must be a non-empty string <=255 chars")
    elif run_id and value_run_id != run_id:
        errors.append(f"run_id mismatch: receipt={value_run_id!r} current={run_id!r}")
    cycle = receipt.get("cycle_id")
    if isinstance(cycle, bool) or not isinstance(cycle, int) or cycle < 1:
        errors.append("cycle_id must be an integer >=1")
    for field in REASON_PASS_DIGEST_FIELDS:
        if not isinstance(receipt.get(field), str) or not _SHA256_RE.fullmatch(
            str(receipt.get(field) or "")
        ):
            errors.append(f"{field} must be lowercase SHA-256")
    read_at = receipt.get("read_at")
    valid_read_at = _valid_ts(read_at, time.time() if now is None else now)
    if not valid_read_at:
        errors.append("read_at must be a non-future positive timestamp")
    chosen = receipt.get("chosen_front")
    if not isinstance(chosen, str) or not _CYCLE_FRONT_RE.fullmatch(chosen):
        errors.append("chosen_front must be F-<number>[suffix] or NONE")
    reason = receipt.get("reason")
    if not isinstance(reason, str) or not reason.strip() or len(reason) > 4096:
        errors.append("reason must be a non-empty string <=4096 chars")
    previous = receipt.get("previous_receipt_hash")
    if not isinstance(previous, str) or (previous and not _SHA256_RE.fullmatch(previous)):
        errors.append("previous_receipt_hash must be empty or lowercase SHA-256")
    claimed_hash = receipt.get("receipt_hash")
    if not isinstance(claimed_hash, str) or not _SHA256_RE.fullmatch(claimed_hash):
        errors.append("receipt_hash must be lowercase SHA-256")
    elif claimed_hash != _receipt_hash(receipt):
        errors.append("receipt_hash mismatch")
    return errors


def load_reason_pass_receipts(run_dir: str | Path) -> tuple[list[dict], list[str]]:
    """Load and validate the bounded append-only receipt chain."""
    run = Path(run_dir).resolve()
    path = _reason_pass_path(run)
    if not path.exists():
        return [], []
    try:
        if path.stat().st_size > REASON_PASS_MAX_BYTES:
            return [], [f"reason-pass receipt file exceeds {REASON_PASS_MAX_BYTES} bytes"]
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    except Exception as exc:
        return [], [f"cannot read reason-pass receipts: {type(exc).__name__}: {exc}"]
    nonempty = [(idx, line) for idx, line in enumerate(lines, 1) if line.strip()]
    if len(nonempty) > REASON_PASS_MAX_RECORDS:
        return [], [f"reason-pass receipt count exceeds {REASON_PASS_MAX_RECORDS}"]
    receipts: list[dict] = []
    errors: list[str] = []
    previous_hash = ""
    previous_cycle = 0
    for lineno, line in nonempty:
        try:
            item = json.loads(line)
        except Exception as exc:
            errors.append(f"line {lineno}: malformed JSON ({type(exc).__name__})")
            break
        item_errors = validate_reason_pass_receipt(item, run_id=run.name)
        if item_errors:
            errors.extend(f"line {lineno}: {error}" for error in item_errors)
            break
        assert isinstance(item, dict)  # narrowed by validator
        if item.get("previous_receipt_hash") != previous_hash:
            errors.append(f"line {lineno}: previous_receipt_hash breaks the chain")
            break
        cycle = int(item["cycle_id"])
        if previous_cycle and cycle != previous_cycle + 1:
            errors.append(f"line {lineno}: cycle_id must be contiguous")
            break
        receipts.append(item)
        previous_hash = str(item["receipt_hash"])
        previous_cycle = cycle
    return (receipts if not errors else []), errors


def record_reason_pass(
    run_dir: str | Path,
    *,
    cycle_id: int | None = None,
    chosen_front: str,
    reason: str,
    read_at: float | None = None,
) -> dict:
    """Append a v1 Reason-pass receipt bound to a stable canonical snapshot."""
    run = Path(run_dir).resolve()
    if not run.is_dir():
        raise FileNotFoundError(f"run directory does not exist: {run}")
    missing_inputs = [
        name for name in ("frontier.md", "evidence.md", "decisions.md")
        if not (run / name).is_file()
    ]
    if missing_inputs:
        raise ValueError("run lacks canonical Reason-pass input(s): " + ", ".join(missing_inputs))
    chosen = str(chosen_front).strip().upper()
    reason_text = str(reason).strip()
    if chosen != "NONE":
        frontier_text = _markdown_value(run / "frontier.md")["text"]
        if not re.search(rf"(?m)^###\s+{re.escape(chosen)}(?:\s|$)", frontier_text):
            raise ValueError(f"chosen_front is not present in frontier.md: {chosen}")
    with _reason_pass_lock(run):
        receipts, errors = load_reason_pass_receipts(run)
        if errors:
            raise ValueError("invalid reason-pass receipt chain: " + "; ".join(errors[:3]))
        next_cycle_id = int(receipts[-1]["cycle_id"]) + 1 if receipts else 1
        if cycle_id is None:
            cycle_id = next_cycle_id
        if cycle_id != next_cycle_id:
            raise ValueError("cycle_id must be exactly one greater than the latest receipt cycle_id")
        digests = _stable_reason_pass_digests(run)
        recorded_at = time.time() if read_at is None else read_at
        if abs(time.time() - float(recorded_at)) > 300:
            raise ValueError("read_at for a new receipt must be within five minutes of now")
        receipt = {
            "schema": REASON_PASS_SCHEMA,
            "run_id": run.name,
            "cycle_id": cycle_id,
            **digests,
            "read_at": recorded_at,
            "chosen_front": chosen,
            "reason": reason_text,
            "previous_receipt_hash": receipts[-1]["receipt_hash"] if receipts else "",
        }
        receipt["receipt_hash"] = _receipt_hash(receipt)
        item_errors = validate_reason_pass_receipt(receipt, run_id=run.name)
        if item_errors:
            raise ValueError("invalid reason-pass receipt: " + "; ".join(item_errors))
        path = _reason_pass_path(run)
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(receipt, ensure_ascii=False, sort_keys=True) + "\n")
            handle.flush()
            os.fsync(handle.fileno())
        return receipt


def semantic_freshness(run_dir: str | Path) -> dict:
    """Assess Reason-pass freshness from content, never from mtimes.

    A legacy run without v1 receipts remains usable, but freshness is explicitly
    unproven.  Legacy session-state fields cannot forge a fresh result.
    """
    run = Path(run_dir).resolve()
    try:
        current = _stable_reason_pass_digests(run)
    except Exception as exc:
        return {
            "status": "invalid",
            "remind": True,
            "changed_fields": [],
            "reason": f"cannot compute canonical digests: {type(exc).__name__}: {exc}",
        }
    receipts, errors = load_reason_pass_receipts(run)
    if errors:
        return {
            "status": "invalid",
            "remind": True,
            "changed_fields": [],
            "reason": "invalid reason-pass receipt chain: " + "; ".join(errors[:3]),
        }
    if not receipts:
        return {
            "status": "legacy_unproven",
            "remind": True,
            "changed_fields": [],
            "reason": "no v1 Reason-pass receipt; legacy timestamps do not prove freshness",
            "current_digests": current,
        }
    latest = receipts[-1]
    changed = [field for field in REASON_PASS_DIGEST_FIELDS if latest.get(field) != current[field]]
    if changed:
        return {
            "status": "changed_unadjudicated",
            "remind": True,
            "changed_fields": changed,
            "reason": "canonical content changed after the latest Reason-pass receipt",
            "latest_cycle_id": latest["cycle_id"],
            "latest_receipt_hash": latest["receipt_hash"],
            "current_digests": current,
        }
    return {
        "status": "fresh",
        "remind": False,
        "changed_fields": [],
        "reason": "latest Reason-pass receipt covers the current canonical digests",
        "latest_cycle_id": latest["cycle_id"],
        "latest_receipt_hash": latest["receipt_hash"],
        "current_digests": current,
    }


def semantic_trajectory(run_dir: str | Path) -> dict:
    """Count consecutive receipt transitions with no semantic graph/evidence progress."""
    receipts, errors = load_reason_pass_receipts(run_dir)
    if errors:
        return {
            "status": "invalid",
            "no_progress_cycles": 0,
            "trajectory_review_due": False,
            "reason": "invalid reason-pass receipt chain: " + "; ".join(errors[:3]),
        }
    streak = 0
    for previous, current in reversed(list(zip(receipts, receipts[1:]))):
        if any(previous.get(field) != current.get(field) for field in TRAJECTORY_DIGEST_FIELDS):
            break
        streak += 1
    return {
        "status": "tracked" if receipts else "untracked",
        "no_progress_cycles": streak,
        "trajectory_review_due": streak >= NO_SEMANTIC_PROGRESS_THRESHOLD,
        "threshold": NO_SEMANTIC_PROGRESS_THRESHOLD,
        "latest_cycle_id": receipts[-1]["cycle_id"] if receipts else None,
        "reason": (
            "consecutive cycles changed only adjudication prose, not frontier/evidence/coverage/graph"
            if streak else "semantic progress is not currently stalled"
        ),
    }


def operational_liveness(run_dir: str | Path) -> dict:
    """Project explicit journal/runtime/Agent state without any freshness clocks.

    This function deliberately has no digest comparison and no mtime/age test;
    callers must not use its result as evidence of Reason-pass freshness.
    """
    run = Path(run_dir).resolve()
    journal_path = run / "state" / "loop_journal.jsonl"
    journal_events: list[dict] = []
    errors: list[str] = []
    if journal_path.exists():
        for lineno, line in enumerate(
            journal_path.read_text(encoding="utf-8", errors="replace").splitlines(), 1
        ):
            if not line.strip():
                continue
            try:
                item = json.loads(line)
            except Exception:
                errors.append(f"loop journal line {lineno}: malformed JSON")
                break
            if not isinstance(item, dict) or item.get("schema") != "xunji.loop_journal.v1":
                errors.append(f"loop journal line {lineno}: unknown schema")
                break
            journal_events.append(item)

    runtime_events: list[dict] = []
    active_agents: list[str] = []
    runtime_path = run / "state" / "runtime_events.jsonl"
    if runtime_path.exists():
        try:
            import runtime_receipts
            runtime_events, runtime_errors = runtime_receipts.validate_chain(run)
            errors.extend(f"runtime receipt: {error}" for error in runtime_errors[:3])
            if not runtime_errors:
                attempts = runtime_receipts.agent_attempts(run)
                active_agents = sorted({
                    str(item.get("agent_id") or item.get("assignment") or "")
                    for item in attempts
                    if item.get("launched_at") and not item.get("returned_at")
                } - {""})
        except Exception as exc:
            errors.append(f"runtime receipts unavailable: {type(exc).__name__}: {exc}")

    last_event = str(journal_events[-1].get("event") or "") if journal_events else ""
    open_journal = last_event in {
        "cycle_start", "plan", "action", "write_result", "resume", "phase_start"
    }
    if errors:
        status = "invalid"
    elif active_agents or open_journal:
        status = "active"
    elif journal_events or runtime_events:
        status = "quiescent"
    else:
        status = "unknown"
    return {
        "status": status,
        "active_agents": active_agents,
        "last_journal_event": last_event or None,
        "journal_event_count": len(journal_events),
        "runtime_event_count": len(runtime_events),
        "errors": errors,
        "clock_free": True,
    }


class SessionStateManager:
    """Unified session_state.json read/write — single authority (Decision 2)."""

    @staticmethod
    def path(run_dir: Path, *, for_write: bool = False) -> Path:
        state_path = run_dir / "state" / "session_state.json"
        legacy_path = run_dir / "session_state.json"
        if for_write:
            return state_path
        if state_path.exists() or not legacy_path.exists():
            return state_path
        return legacy_path

    @staticmethod
    def load(run_dir: Path) -> dict:
        sf = SessionStateManager.path(run_dir)
        if not sf.exists():
            return {}
        try:
            return json.loads(sf.read_text(encoding="utf-8"))
        except Exception:
            return {}

    @staticmethod
    def save(run_dir: Path, state: dict) -> None:
        state["updated_at"] = time.time()
        sf = SessionStateManager.path(run_dir, for_write=True)
        sf.parent.mkdir(parents=True, exist_ok=True)
        tmp = sf.with_suffix(".json.tmp")
        try:
            tmp.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
            tmp.replace(sf)
        except Exception:
            pass

    @staticmethod
    def get_drift_flags(run_dir: Path) -> list[str]:
        state = SessionStateManager.load(run_dir)
        flags = state.get("drift_flags", [])
        return flags if isinstance(flags, list) else []

    @staticmethod
    def reset_if_stale(run_dir: Path, hard_block_active: bool = False) -> dict:
        """Auto-reset stale session_state. Returns the state dict (fresh or existing)."""
        state = SessionStateManager.load(run_dir)
        if not state:
            return {}
        drift_flags = SessionStateManager.get_drift_flags(run_dir)
        if not drift_flags:
            return state
        if hard_block_active:
            return state  # never reset while hard-blocked
        updated_at = _valid_ts(state.get("updated_at"), time.time())
        stale_sec = SESSION_STATE_STALE_SEC
        if updated_at and time.time() - updated_at > stale_sec:
            state["drift_flags"] = []
            state["reread_pending"] = False
            state["drift_block_count"] = 0
            SessionStateManager.save(run_dir, state)
        return state


def _run_from_pointer(runs_root: Path, pointer: Path = ACTIVE_RUN_POINTER) -> Path | None:
    """Resolve the explicit statusline/run-lifecycle pointer inside ``runs_root``.

    The pointer is authoritative when valid. Restricting it to ``runs_root`` keeps
    temp selftests and stale/edited pointer files from selecting an arbitrary path.
    """
    try:
        raw = pointer.read_text(encoding="utf-8", errors="replace").strip()
    except Exception:
        return None
    if not raw:
        return None
    value = Path(raw).expanduser()
    candidates = [value] if value.is_absolute() else [ROOT / value, runs_root / value]
    root = runs_root.resolve()
    for candidate in candidates:
        try:
            run_dir = candidate.resolve()
            run_dir.relative_to(root)
        except (OSError, ValueError):
            continue
        if run_dir.is_dir() and any(
            (run_dir / marker).exists()
            for marker in ("target.md", "frontier.md", "evidence.md", "decisions.md", "review.md")
        ):
            return run_dir
    return None


def find_active_run(
    runs_root: Path,
    within_sec: int = ACTIVE_WINDOW_SEC,
    *,
    active_pointer: Path | None = None,
) -> Path | None:
    """Return only the explicit active run; recency is not run authority."""
    del within_sec  # retained for caller compatibility
    return _run_from_pointer(runs_root, active_pointer or ACTIVE_RUN_POINTER)


def _detect_stage(run_dir: Path) -> str:
    """Derive current stage from run file state. Uses check_run._report_is_final()
    for closure detection — file existence alone is not enough (setup_run creates templates)."""
    try:
        if _TOOLS_PATH not in sys.path:
            sys.path.insert(0, _TOOLS_PATH)
        import check_run as cr
    except Exception:
        # Fallback: simple heuristic
        frontier = run_dir / "frontier.md"
        if frontier.exists():
            fr = frontier.read_text(encoding="utf-8", errors="replace")
            if "Status: probing" in fr or "Status: open" in fr:
                return "Driver"
        return "Setup"

    review = run_dir / "review.md"
    evidence = run_dir / "evidence.md"
    frontier = run_dir / "frontier.md"

    # Closure: check_run's canonical final-report predicate
    try:
        if cr._report_is_final(run_dir):
            rv = review.read_text(encoding="utf-8", errors="replace") if review.exists() else ""
            if "Independent Review" in rv:
                return "Closure"
            return "Closure-Missing-Review"
    except Exception:
        pass
    # Reviewer: review.md has independent review content (not just the template header)
    if review.exists() and review.stat().st_size > 500:
        rv = review.read_text(encoding="utf-8", errors="replace")
        if "Independent Review" in rv:
            return "Reviewer"
    # Hunter: evidence has confirmed entries (use evidence_parse for accuracy)
    if evidence.exists():
        try:
            recs = cr.parse_evidence(run_dir)
            n_conf = len([r for r in recs if r.get("confirmed")])
            if n_conf > 0:
                return "Hunter"
        except Exception:
            pass
    # Driver: frontier has open/probing fronts
    if frontier.exists():
        fr = frontier.read_text(encoding="utf-8", errors="replace")
        if "Status: probing" in fr or "Status: open" in fr:
            return "Driver"
    return "Setup"

def _check_drift_alert(run_dir: Path) -> list[str]:
    """Check drift_alerts.md for unresolved violations. Returns alert items."""
    alerts = run_dir / "drift_alerts.md"
    if not alerts.exists():
        return []
    try:
        lines = alerts.read_text(encoding="utf-8", errors="replace").splitlines()
        unresolved = [l for l in lines if l.startswith("- [ ]") or l.startswith("PENDING")]
        return unresolved[:5]
    except Exception as exc:
        return [
            "drift_alerts.md 读取失败"
            f"({type(exc).__name__})，未解决状态未知; 先人工 Read/处置"
        ]


def _sentinel_soft_reminders(run_dir: Path) -> list[str]:
    """Project fresh observe-only sentinel debt into the recency anchor.

    Sentinel remains an audit/attribution layer: this helper never writes,
    blocks, grants authority, or treats an alert as fact.  Explicit unchecked
    pending items remain visible.  Ordinary alerts are reminded only while the
    alert ledger has no matching content-bound acknowledgement in the Root-owned
    decisions ledger, which keeps the advisory from becoming permanent context
    spam without relying on forgeable mtimes.
    """
    reminders: list[str] = []

    def _tail_bytes(path: Path, limit: int) -> bytes:
        with path.open("rb") as handle:
            size = path.stat().st_size
            if size > limit:
                handle.seek(size - limit)
            return handle.read(limit)

    def _alert_token(path: Path) -> tuple[str, str]:
        before = path.stat()
        raw = _tail_bytes(path, SENTINEL_ALERT_TAIL_LIMIT)
        after = path.stat()
        if (before.st_size, before.st_mtime_ns) != (after.st_size, after.st_mtime_ns):
            raise RuntimeError("alert ledger changed during read")
        digest = hashlib.sha256(
            str(after.st_size).encode("ascii") + b"\0" + raw
        ).hexdigest()
        return digest, raw.decode("utf-8", "replace")

    pending = run_dir / "pending_approval.md"
    if pending.is_file():
        try:
            # pending_approval.md is append-only audit state and old entries may
            # remain unresolved outside any tail.  Scan the whole file only
            # within a fixed per-prompt budget.  Above that budget, surface an
            # explicit unknown-state reminder instead of doing unbounded work or
            # falsely inferring that old authority debt is clear.
            pending_size = pending.stat().st_size
            if pending_size > SENTINEL_PENDING_SCAN_LIMIT:
                reminders.append(
                    "sentinel pending_approval.md 超出每回合扫描预算，完整状态未知; "
                    "先 Read/处置或归档压缩，且不得把 observe-only 记录当成已批准"
                )
            else:
                with pending.open("r", encoding="utf-8", errors="replace") as handle:
                    count = sum(1 for line in handle if _SENTINEL_PENDING_RE.search(line))
                if count:
                    reminders.append(
                        f"sentinel pending_approval.md 至少 {count} 条未处置; "
                        "先 Read 并交由 operator/Root 处置, 不得把 observe-only 记录当成已批准"
                    )
        except Exception as exc:
            reminders.append(
                "sentinel pending_approval.md 读取失败"
                f"({type(exc).__name__})，状态未知; 先人工 Read/处置，不得视为已批准"
            )

    alerts = run_dir / "alerts.md"
    if alerts.is_file():
        try:
            decisions = run_dir / "decisions.md"
            alert_digest, text = _alert_token(alerts)
            if not text.strip():
                return reminders
            decisions_text = (
                _tail_bytes(decisions, SENTINEL_ALERT_TAIL_LIMIT).decode("utf-8", "replace")
                if decisions.is_file() else ""
            )
            acknowledged = {
                match.group(1).lower()
                for match in _SENTINEL_ALERT_ACK_RE.finditer(decisions_text)
            }
            if alert_digest not in acknowledged:
                headings = re.findall(
                    r"(?m)^##\s+(?:ALERT|CIRCUIT-BREAKER)\b[^\n]*", text
                )
                latest = re.sub(r"\s+", " ", headings[-1]).strip() if headings else "new alert"
                reminders.append(
                    "sentinel alerts.md 有未按内容指纹确认的新观察"
                    f"(最新: {latest[:120]}); 先 Read/归因，处置后在 decisions.md 记录 "
                    f"`- SentinelAlertsAck: sha256:{alert_digest}`"
                )
        except Exception as exc:
            reminders.append(
                "sentinel alerts.md 读取失败"
                f"({type(exc).__name__})，状态未知; 先人工 Read/归因"
            )
    return reminders

def _check_agent_board_needed(run_dir: Path, _model=None) -> tuple[bool, int, dict]:
    """Check if Agent Board is mandatory: active fronts >= 4 and barriers are diverse
    (no SharedBarrierGroup). Returns (should_remind, open_count, barrier_groups)."""
    try:
        if _model is None:
            import run_model as model
        else:
            model = _model
        data = model.summary(run_dir)
    except Exception as exc:
        if (run_dir / "frontier.md").exists():
            return True, 4, {"state-parser-failure": [type(exc).__name__]}
        return False, 0, {}
    barrier_groups: dict[str, list[str]] = {}
    for front in data.get("fronts", []):
        if front.get("id") not in data.get("open", []):
            continue
        barrier = str(front.get("barrier") or "unknown")
        if barrier in {"", "none", "unknown", "n/a", "-"}:
            continue
        barrier_groups.setdefault(barrier, []).append(str(front.get("id")))
    return bool(data.get("fanout_required")), int(data.get("open_count", 0)), barrier_groups


def _overdue_steps(run_dir: Path) -> list[str]:
    """Derive process/evidence flags from the run files via check_run (no re-parsing). Advisory."""
    flags: list[str] = []
    try:
        if _TOOLS_PATH not in sys.path:
            sys.path.insert(0, _TOOLS_PATH)
        import check_run as cr
    except Exception:
        return flags
    try:
        recs = cr.parse_evidence(run_dir)
        n_ev = len([r for r in recs if r.get("id", "").startswith("E-")])
        n_conf = len([r for r in recs if r.get("id", "").startswith("E-") and r.get("confirmed")])
        # NOTE: the confirmed-without-artifact check (evidence_entries_missing_artifact) does an
        # uncapped rglob — too heavy for a per-prompt hook. It stays enforced by check_run at the
        # closure gate; the anchor only does cheap file-level checks here.
        # coverage health (lite): surface the first warning if any
        try:
            cov = cr.check_coverage_health(run_dir)
            if cov:
                flags.append("覆盖: " + cov[0][:80])
        except Exception:
            pass
        # codex checkpoint (periodic, not just at closure): any >=0.8 confirmed finding without an
        # Independent Review on record = run peer_review now (Verifier-Tax: remind here, the closure
        # gate hard-blocks). Surfaced every turn so the operator does not have to remind.
        try:
            import re as _re
            rvf = run_dir / "review.md"
            evf = run_dir / "evidence.md"
            rv0 = rvf.read_text(encoding="utf-8", errors="replace") if rvf.exists() else ""
            has_review = bool(_re.search(r"Independent Review|独立复审", rv0))
            # fires when there's a confirmed finding AND (no review yet OR evidence changed since the
            # last review) — so a NEW >=0.8 after a prior review re-triggers, not just the first one.
            ev_mt = evf.stat().st_mtime if evf.exists() else 0
            rv_mt = rvf.stat().st_mtime if rvf.exists() else 0
            if n_conf and (not has_review or ev_mt > rv_mt):
                flags.append("独立复审 due: ≥0.8 确认且评审未覆盖最新证据 → 加载 xunji-reviewops 并刷新 fingerprint-bound ReviewReceipt")
        except Exception:
            pass
        # closure readiness: report final but review/retrospective missing
        try:
            if cr._report_is_final(run_dir):
                rv = (run_dir / "review.md").read_text(encoding="utf-8", errors="replace") \
                    if (run_dir / "review.md").exists() else ""
                import re as _re
                if not _re.search(r"Independent Review|独立复审", rv):
                    flags.append("收口: report 已终版但缺独立复审 → 加载 xunji-reviewops；Agent Reviewer/手填 review.md 不满足")
                retro = run_dir / "retrospective.md"
                if not retro.exists():
                    flags.append("收口: 缺 retrospective.md(强制复盘)")
        except Exception:
            pass
        flags.insert(0, f"evidence {n_ev} 条 / confirmed {n_conf}")
    except Exception:
        pass
    return flags




def build_anchor(
    runs_root: Path = RUNS,
    *,
    active_pointer: Path | None = None,
) -> str:
    lines = []

    # ---- Runtime mode: keep the effective config visible every turn. ----
    runtime_mode = get_mode()
    if runtime_mode == "normal":
        lines.append("[NORMAL MODE — 全量执行]")
        lines.append("  · 漂移路径: output_gate 记录/软提醒; run_gate Phase 3 对重复协议/自主性漂移阻断")
        lines.append("")
        lines.append("【Normal 自立规则】")
        lines.append("  · 凭据自立: 默认密码→弱口令爆破→注册→用户枚举→密码喷洒, 不等待/不询问")
        lines.append("  · 网络自立: 不可达→先换路径/备选方案再判定; 不建egress·relay(保持边界内)")
        lines.append("  · 决策自立: 不问操作者任何问题, 所有选择自主做出, 记录在 decisions.md")
        lines.append("  · 不因Type B放弃: WAF/限流/超时阻挡→换方法绕过, 不关闭前沿")
        lines.append("  · 收口自立: 完成所有前沿后, 按 lifecycle/reviewops owner 跑离线硬门、独立复审、复盘，再按 typed completion contract 收口")
        lines.append("")
    else:
        lines.append("[DEV MODE — 开发观察]")
        lines.append("  · 漂移路径: output_gate 仍记录/软提醒; run_gate 跳过 repeated-drift 阻断")
        lines.append("  · 跳过 Normal-only 额外复审/完成前置")
        lines.append("  · authority/safety/privacy/evidence/Coda/closure integrity 硬门不降级")
        lines.append("")

    lines.append("[ANTI-DRIFT ANCHOR — 每回合自检, 漂移=没按下面走]")
    lines.append("")

    # ---- Phase 1: read session_state.json and inject re-read instructions ----
    run = find_active_run(runs_root, active_pointer=active_pointer)
    drift_flags: list[str] = []
    semantic_state: dict = {}
    trajectory_state: dict = {}
    if run is not None:
        SessionStateManager.reset_if_stale(run)
        # ``frontier_stale`` is a legacy mtime claim.  It may still be present
        # until output_gate is migrated, but it cannot mint semantic staleness.
        drift_flags = [
            flag for flag in SessionStateManager.get_drift_flags(run)
            if flag != "frontier_stale"
        ]
        semantic_state = semantic_freshness(run)
        trajectory_state = semantic_trajectory(run)

    if semantic_state.get("remind"):
        lines.append("⚠ Reason-pass 语义新鲜度待处理:")
        if semantic_state.get("status") == "changed_unadjudicated":
            changed = ", ".join(semantic_state.get("changed_fields", []))
            lines.append(f"  · canonical 内容已变化({changed}); 本轮重读全图并记录 v1 receipt")
        elif semantic_state.get("status") == "legacy_unproven":
            lines.append("  · 旧 run 尚无 v1 receipt; 做一次全图 Reason pass 建立语义基线(不得 touch canonical 文件)")
        else:
            lines.append(f"  · receipt/digest 无法验证: {str(semantic_state.get('reason') or '')[:160]}")
        lines.append("  · 内容未变时只读确认即可; freshness 不要求 Edit frontier.md")
        lines.append("")
    if trajectory_state.get("trajectory_review_due"):
        lines.append("⚠ Trajectory review due:")
        lines.append(
            "  · 连续 " + str(trajectory_state.get("no_progress_cycles", 0))
            + " 个周期无 frontier/evidence/coverage/graph 语义增量; 复盘盲点并 pivot/分派 review 或 surface Agent"
        )
        lines.append("  · 这是轨迹收敛信号, 不是 Completion/收口授权")
        lines.append("")

    # Re-read directives based on drift_flags (injected BEFORE Tier-1 for max attention)
    if drift_flags:
        lines.append("⚠ 检测到漂移信号 — 先 Read 对应约束文件后继续:")
        for flag in drift_flags:
            if flag == "protocol_violation":
                lines.append("  · 先 Read CLAUDE.md — 回合协议违规")
            elif flag == "option_list":
                lines.append("  · 先 Read CLAUDE.md \"自主驱动\"段")
        lines.append("")

    # Tier-1: 本轮必做 (primacy position — highest attention weight)
    lines.append("【本轮必做】")
    for r in BINDING_RULES_TIER1:
        lines.append(f"  · {r}")
    # Agent Board 强制检查: active fronts >= 4 且无共享 barrier -> 必须并行
    if run is not None:
        agent_needed, n_open, _bg = _check_agent_board_needed(run)
        if agent_needed:
            lines.append("  · Agent Board 强制: 无 fixed Stop debt 且 active(open/probing/working/type-A) fronts ≥ 4、无共享 barrier → 加载 xunji-agent-board，提交 ≥2 条 ready disjoint lanes 并 delegate；按 owner 的 exact contract 分消息错峰真实 launch，禁止 Root 全串行。")
        # 操作者约束持久化检查: hints.md 有 pending constraint → 提示吸收
        hp = run / "hints.md"
        if hp.exists():
            try:
                import re as _re_hints
                htext = hp.read_text(encoding="utf-8", errors="replace")
                pending = [m.group(1) for m in _re_hints.finditer(
                    r"##\s+(HINT-\d+)\n(?:(?!##\s).)*?Kind\s*[:：]\s*constraint"
                    r"(?:(?!##\s).)*?Status\s*[:：]\s*pending",
                    htext, _re_hints.I | _re_hints.S)]
                if pending:
                    lines.append(f"  ⚠ 操作者约束待吸收: {', '.join(pending)} — 先 Read hints.md 并按 Kind 吸收再动作(constraint 是全 run 级原则)")
            except Exception:
                pass
    lines.append("")
    # Tier-2: 当前状态 (dynamic — run phase + process flags)
    if run is not None:
        try:
            mt = max((p.stat().st_mtime for p in run.glob("*.md")), default=0)
            age = int((time.time() - mt) / 60)
        except Exception:
            age = -1
        stage = _detect_stage(run)
        lines.append("【当前状态】")
        lines.append(f"  run: {run.name} | 阶段: {stage} | 最后改动: {age}m 前")
        if is_normal_mode() and _normal_completion_committed(run):
            lines.append("  ✅ NORMAL_COMPLETE: 所有前沿已完成, run 已自动收口")
            lines.append("     → 停止: 无剩余工作, 等待操作者确认或关闭会话")
        overdue = _overdue_steps(run)
        for f in overdue:
            lines.append(f"  · {f}")
        for reminder in _sentinel_soft_reminders(run):
            lines.append(f"  ⚠ 安全护栏软提醒: {reminder}")
        # 中间闸门(每回合自动跑 —— 不让 AI 忘记 check_run)
        try:
            if _TOOLS_PATH not in sys.path:
                sys.path.insert(0, _TOOLS_PATH)
            import check_run as _cr_gate
            inter_errors, inter_warns = _cr_gate.check_intermediate_gates(run)
            for e in inter_errors[:3]:
                lines.append(f"  ⛔ 中间闸门 HARD FAIL: {e[:130]}")
            for w in inter_warns[:3]:
                lines.append(f"  ⚠ 中间闸门: {w[:130]}")
        except Exception as exc:
            lines.append(
                "  ⚠ 中间闸门读取失败"
                f"({type(exc).__name__})，状态未知; 不得据此推断可收口"
            )
        drift_items = _check_drift_alert(run)
        if drift_items:
            lines.append("  ⚠ 漂移告警(未解决):")
            for d in drift_items:
                lines.append(f"    {d[:120]}")
        lines.append("")
    # Tier-3: 约束速查 (recency position — last thing model sees before producing output)
    lines.append("【约束速查】")
    for r in BINDING_RULES_TIER3:
        lines.append(f"  · {r}")

    # ---- Recency-position output self-check (fires BEFORE model produces output) ----
    if drift_flags:
        lines.append("")
        lines.append("【输出前自检 —— 生成回复前必须逐条确认】")
        if "protocol_violation" in drift_flags:
            lines.append("  □ 最后一个非空行是否【唯一】的「下一行动: <对象+具体动作>」？")
            lines.append("    → 无 receipt-backed fixed Stop debt 时，不含空值/占位/泛泛继续/多动作/多F-id/错误F-id；未完成 run 的普通 Coda 不得用 BLOCKED 逃避")
        if "option_list" in drift_flags:
            lines.append("  □ 是否产生了编号选项列表(1.xxx / 2.xxx)把决策抛回给用户？")
            lines.append("    → 如有, 删掉选项, 自主选一个方向, 写成「下一行动:」。")

    if semantic_state.get("remind"):
        lines.append("")
        lines.append("【Reason-pass 回执前自检】")
        lines.append("  □ 是否重读/裁定了当前 digest 对应的全图, 并记录 v1 receipt？")
        lines.append("  □ 若 canonical 内容未变, 是否避免了无语义 touch/edit？")

    return "\n".join(lines)


def _selftest() -> int:
    import tempfile

    checks: list[tuple[str, bool]] = []
    d = Path(tempfile.mkdtemp())
    empty_runs = d / "empty-runs"
    empty_runs.mkdir()

    # Prove both config.ini modes are connected without touching the operator's
    # ignored local config.  Local config overrides the tracked example; invalid
    # values fail closed to normal.
    global CONFIG_INI, CONFIG_EXAMPLE_INI, _mode_cache
    mode_dir = d / "mode-config"
    mode_dir.mkdir()

    @contextlib.contextmanager
    def _isolated_mode_paths():
        global CONFIG_INI, CONFIG_EXAMPLE_INI, _mode_cache
        original = (CONFIG_INI, CONFIG_EXAMPLE_INI, _mode_cache)
        try:
            CONFIG_EXAMPLE_INI = mode_dir / "config.example.ini"
            CONFIG_INI = mode_dir / "config.ini"
            CONFIG_EXAMPLE_INI.write_text("[mode]\nmode = normal\n", encoding="utf-8")
            CONFIG_INI.write_text("[mode]\nmode = dev\n", encoding="utf-8")
            _mode_cache = (0.0, "normal")
            yield
        finally:
            CONFIG_INI, CONFIG_EXAMPLE_INI, _mode_cache = original

    with _isolated_mode_paths():
        dev_mode = get_mode()
        dev_anchor = build_anchor(
            runs_root=empty_runs, active_pointer=d / "missing-dev-pointer"
        )
        checks.append(("config local dev overrides example normal",
                       dev_mode == "dev" and "[DEV MODE" in dev_anchor))
        CONFIG_INI.write_text("[mode]\nmode = unknown\n", encoding="utf-8")
        _mode_cache = (0.0, "dev")
        checks.append(("invalid config mode fails closed to normal",
                       get_mode() == "normal"))

    a = build_anchor(runs_root=empty_runs, active_pointer=d / "missing-pointer")
    checks.append(("anchor non-empty", bool(a.strip())))
    checks.append(("anchor carries binding rules", "本轮必做" in a and "约束速查" in a))
    checks.append(("anchor is compact (<3KB)", len(a) < 3072))
    checks.append(("anchor routes owners without stale executable protocols",
                   "workers.py assign" not in a
                   and "peer_review --into-run" not in a
                   and "replay才有效" not in a
                   and "from harness.guard import RequestRecorder" not in a))
    checks.append(("target Stop debt precedes autonomy while maintenance stays retryable",
                   "receipt-backed TARGET_DENIED" in a
                   and "修正 typed path/argv 后可同回合重试" in a
                   and "BLOCKED都会被" not in a))
    completion_probe = d / "completion-probe"
    completion_probe.mkdir()
    (completion_probe / "decisions.md").write_text(
        "# Decisions\n\nNORMAL_COMPLETE receipt=" + ("a" * 64) + "\n",
        encoding="utf-8",
    )
    import completion_transaction as _completion_transaction
    checks.append(("legacy normal marker cannot claim completion",
                   not _normal_completion_committed(completion_probe)))
    original_committed_predicate = _completion_transaction.is_valid_committed
    try:
        _completion_transaction.is_valid_committed = lambda _run: True
        committed_probe = _normal_completion_committed(completion_probe)
    finally:
        _completion_transaction.is_valid_committed = original_committed_predicate
    checks.append(("valid completion transaction enables normal status",
                   committed_probe))
    # drift patterns list
    checks.append(("drift patterns non-empty", len(DRIFT_PATTERNS) >= 5))
    # find_active_run: explicit pointer is the only run authority.
    checks.append(("stage Detection exists", _detect_stage(d) == "Setup"))
    runs = d / "runs"
    (runs / "a_x").mkdir(parents=True)
    (runs / "a_x" / "report.md").write_text("# r", encoding="utf-8")
    checks.append(("missing pointer never guesses a recent run", find_active_run(runs) is None))
    checks.append(("recency window cannot authorize a run", find_active_run(runs, within_sec=9999) is None))
    checks.append(("no runs dir -> none", find_active_run(d / "nope") is None))
    pointed = runs / "pointed"
    pointed.mkdir()
    (pointed / "frontier.md").write_text("# Frontier\n", encoding="utf-8")
    pointer = d / "active_run"
    pointer.write_text(str(pointed), encoding="utf-8")
    checks.append(("explicit pointer wins over newer run",
                   find_active_run(runs, active_pointer=pointer) == pointed.resolve()))
    outside = d / "outside"
    outside.mkdir()
    (outside / "frontier.md").write_text("# Frontier\n", encoding="utf-8")
    pointer.write_text(str(outside), encoding="utf-8")
    checks.append(("outside pointer is ignored",
                   find_active_run(runs, active_pointer=pointer) is None))

    # SessionStateManager tests
    rd = runs / "test_session"
    rd.mkdir(parents=True)
    # missing file -> {}
    checks.append(("session_state missing -> {}", SessionStateManager.load(rd) == {}))
    # valid JSON
    (rd / "session_state.json").write_text(
        json.dumps({"drift_flags": ["frontier_stale"], "updated_at": time.time()}), encoding="utf-8")
    st = SessionStateManager.load(rd)
    checks.append(("session_state reads drift_flags", st.get("drift_flags") == ["frontier_stale"]))
    # corrupt JSON -> {}
    (rd / "session_state.json").write_text("not json{{{", encoding="utf-8")
    checks.append(("session_state corrupt -> {}", SessionStateManager.load(rd) == {}))
    # get_drift_flags
    (rd / "session_state.json").write_text(
        json.dumps({"drift_flags": ["protocol_violation"], "updated_at": time.time()}), encoding="utf-8")
    checks.append(("get_drift_flags returns list",
                   SessionStateManager.get_drift_flags(rd) == ["protocol_violation"]))
    SessionStateManager.save(rd, {"drift_flags": ["frontier_stale"]})
    checks.append(("session_state save writes state/ path",
                   (rd / "state" / "session_state.json").exists()))

    # build_anchor with drift_flags — uses temp locations, NOT real project files
    import tempfile as _tm
    _td = Path(_tm.mkdtemp())
    _tmp_runs = _td / "runs"
    _tmp_runs.mkdir()
    test_run = _tmp_runs / "_selftest_drift_test"
    test_run.mkdir(parents=True)
    (test_run / "evidence.md").write_text("# test", encoding="utf-8")
    (test_run / "session_state.json").write_text(
        json.dumps({"drift_flags": ["protocol_violation", "frontier_stale"], "frontier_mtime": 0.0,
                     "claude_mtime": 0.0, "updated_at": time.time()}), encoding="utf-8")
    test_pointer = _td / "active-run"
    test_pointer.write_text(str(test_run), encoding="utf-8")
    anchor_with_drift = build_anchor(runs_root=_tmp_runs, active_pointer=test_pointer)
    checks.append(("anchor injects protocol_violation warning",
                   "先 Read CLAUDE.md — 回合协议违规" in anchor_with_drift))
    legacy_ritual = "先 Read frontier.md 然后 " + "EDIT 更新状态"
    legacy_mtime_claim = "只读不改 = " + "mtime"
    checks.append(("legacy frontier mtime cannot mint ritual edit",
                   legacy_ritual not in anchor_with_drift
                   and legacy_mtime_claim not in anchor_with_drift))
    checks.append(("anchor still has Tier-1 rules", "本轮必做" in anchor_with_drift))
    # self-check section present when drift
    checks.append(("anchor has self-check section when drift",
                   "输出前自检" in anchor_with_drift))
    # The retired drift_block.json file must not be presented as authority; the
    # mode banner above names the current output_gate/run_gate ownership.
    checks.append(("anchor names current drift owners, not retired drift_block file",
                   "drift_block" not in anchor_with_drift.lower()))

    # Sentinel is observe-only, but new/unresolved audit debt must be visible in
    # the next-prompt recency anchor instead of depending on model memory.
    sentinel_run = _tmp_runs / "sentinel_soft_reminder"
    sentinel_run.mkdir()
    (sentinel_run / "evidence.md").write_text("# Evidence\n", encoding="utf-8")
    (sentinel_run / "decisions.md").write_text("# Decisions\n", encoding="utf-8")
    (sentinel_run / "alerts.md").write_text(
        "# Behavioral Alerts\n\n## ALERT 2026-08-02 L2/NOTIFY\n- new\n",
        encoding="utf-8",
    )
    (sentinel_run / "pending_approval.md").write_text(
        "# Pending\n\n## PENDING 2026-08-02 L3/GATE\nStatus: [ ] pending\n",
        encoding="utf-8",
    )
    sentinel_reminders = _sentinel_soft_reminders(sentinel_run)
    checks.append(("sentinel pending and fresh alerts become soft reminders",
                   len(sentinel_reminders) == 2
                   and any("pending_approval.md" in item for item in sentinel_reminders)
                   and any("alerts.md" in item for item in sentinel_reminders)))
    alert_reminder = next(item for item in sentinel_reminders if "alerts.md" in item)
    alert_ack = re.search(r"sha256:([0-9a-f]{64})", alert_reminder)
    (sentinel_run / "decisions.md").write_text(
        "# Decisions\n\n- SentinelAlertsAck: sha256:"
        + (alert_ack.group(1) if alert_ack else "missing") + "\n",
        encoding="utf-8",
    )
    disposed_reminders = _sentinel_soft_reminders(sentinel_run)
    checks.append(("content-bound decisions ack silences ordinary alert reminder only",
                   len(disposed_reminders) == 1
                   and "pending_approval.md" in disposed_reminders[0]))
    empty_alert_run = _tmp_runs / "sentinel_empty_alert"
    empty_alert_run.mkdir()
    (empty_alert_run / "alerts.md").write_text("  \n", encoding="utf-8")
    checks.append(("empty alerts ledger does not create a phantom soft reminder",
                   _sentinel_soft_reminders(empty_alert_run) == []))
    (sentinel_run / "pending_approval.md").write_text(
        "Status: [ ] pending\n" + ("x" * (300 * 1024)) +
        "\nStatus: [x] resolved\n",
        encoding="utf-8",
    )
    checks.append(("old pending outside alert tail cap remains visible",
                   any("至少 1 条" in item
                       for item in _sentinel_soft_reminders(sentinel_run))))
    (sentinel_run / "pending_approval.md").write_text(
        "Status: [ ] pending\n" + ("x" * SENTINEL_PENDING_SCAN_LIMIT),
        encoding="utf-8",
    )
    checks.append(("oversize pending ledger is bounded but never inferred clear",
                   any("超出每回合扫描预算" in item
                       for item in _sentinel_soft_reminders(sentinel_run))))
    test_pointer.write_text(str(sentinel_run), encoding="utf-8")
    sentinel_anchor = build_anchor(runs_root=_tmp_runs, active_pointer=test_pointer)
    checks.append(("anchor exposes safety soft reminder without granting authority",
                   "安全护栏软提醒" in sentinel_anchor
                   and "不得把 observe-only 记录当成已批准" in sentinel_anchor))
    drift_read_error_run = _tmp_runs / "drift_alert_read_error"
    drift_read_error_run.mkdir()
    (drift_read_error_run / "drift_alerts.md").mkdir()
    checks.append(("drift alert read failure is visible, not silently clear",
                   any("读取失败" in item
                       for item in _check_drift_alert(drift_read_error_run))))

    # Stale session_state auto-reset
    fresh_run = _tmp_runs / "fresh_session"
    fresh_run.mkdir()
    (fresh_run / "evidence.md").write_text("# fresh", encoding="utf-8")
    old_stale = time.time() - SESSION_STATE_STALE_SEC - 120
    (fresh_run / "session_state.json").write_text(
        json.dumps({"drift_flags": ["protocol_violation"], "updated_at": old_stale}), encoding="utf-8")
    test_pointer.write_text(str(fresh_run), encoding="utf-8")
    anchor_fresh = build_anchor(runs_root=_tmp_runs, active_pointer=test_pointer)
    checks.append(("stale session_state auto-reset",
                   "先 Read CLAUDE.md — 回合协议违规" not in anchor_fresh))

    # Semantic freshness / Reason-pass receipt fixtures.
    def _semantic_run(name: str) -> Path:
        run = _tmp_runs / name
        run.mkdir()
        (run / "frontier.md").write_text(
            "# Frontier\n\n## Open Fronts\n\n"
            "### F-001 Login\n- Status: open\n- Barrier class: auth-layer\n",
            encoding="utf-8",
        )
        (run / "hypotheses.md").write_text(
            "# Hypotheses\n\n## H-001\n- Status: open\n", encoding="utf-8"
        )
        (run / "evidence.md").write_text("# Evidence Ledger\n", encoding="utf-8")
        (run / "decisions.md").write_text("# Decisions\n", encoding="utf-8")
        (run / "classify").mkdir()
        (run / "classify" / "coverage.json").write_text(
            json.dumps({"assets": [{"host": "example.test", "reachable": True}]}),
            encoding="utf-8",
        )
        return run

    semantic_run = _semantic_run("semantic_freshness")
    forged = canonical_reason_pass_digests(semantic_run)
    SessionStateManager.save(semantic_run, {
        "drift_flags": [],
        "frontier_mtime": time.time(),
        **forged,
    })
    legacy = semantic_freshness(semantic_run)
    checks.append(("legacy timestamps/digests cannot forge freshness",
                   legacy.get("status") == "legacy_unproven" and legacy.get("remind") is True))

    canonical_paths = [
        semantic_run / "frontier.md",
        semantic_run / "hypotheses.md",
        semantic_run / "evidence.md",
        semantic_run / "decisions.md",
        semantic_run / "classify" / "coverage.json",
    ]
    canonical_mtimes = {path: path.stat().st_mtime_ns for path in canonical_paths}
    first_receipt = record_reason_pass(
        semantic_run,
        chosen_front="F-001",
        reason="whole-graph read; F-001 has the strongest unresolved auth signal",
    )
    checks.append(("receipt binds all required semantic digests",
                   first_receipt.get("schema") == REASON_PASS_SCHEMA
                   and first_receipt.get("cycle_id") == 1
                   and all(_SHA256_RE.fullmatch(str(first_receipt.get(field) or ""))
                           for field in REASON_PASS_DIGEST_FIELDS)))
    auto_receipt_run = _semantic_run("auto_reason_pass_sequence")
    auto_first = record_reason_pass(
        auto_receipt_run, chosen_front="F-001", reason="first automatic receipt")
    auto_second = record_reason_pass(
        auto_receipt_run, chosen_front="F-001", reason="second automatic receipt")
    checks.append(("omitted receipt sequence advances atomically",
                   auto_first.get("cycle_id") == 1
                   and auto_second.get("cycle_id") == 2
                   and auto_second.get("previous_receipt_hash")
                   == auto_first.get("receipt_hash")))
    checks.append(("recording receipt never touches canonical files",
                   canonical_mtimes == {path: path.stat().st_mtime_ns for path in canonical_paths}))
    fresh = semantic_freshness(semantic_run)
    before_readonly = {
        path: path.stat().st_mtime_ns
        for path in semantic_run.rglob("*") if path.is_file()
    }
    fresh_again = semantic_freshness(semantic_run)
    semantic_trajectory(semantic_run)
    after_readonly = {
        path: path.stat().st_mtime_ns
        for path in semantic_run.rglob("*") if path.is_file()
    }
    checks.append(("matching digest is fresh without reminder",
                   fresh.get("status") == "fresh" and fresh.get("remind") is False))
    checks.append(("content-unchanged semantic checks are read-only",
                   fresh_again.get("status") == "fresh" and before_readonly == after_readonly))
    test_pointer.write_text(str(semantic_run), encoding="utf-8")
    anchor_semantic_fresh = build_anchor(runs_root=_tmp_runs, active_pointer=test_pointer)
    checks.append(("fresh anchor has no semantic-stale reminder",
                   "Reason-pass 语义新鲜度待处理" not in anchor_semantic_fresh))

    (semantic_run / "evidence.md").write_text(
        "# Evidence Ledger\n\n## E-001\n- Maturity: candidate\n"
        "- Certainty: 0.5\n- Supports: F-001\n",
        encoding="utf-8",
    )
    changed = semantic_freshness(semantic_run)
    checks.append(("canonical digest change without reread reminds",
                   changed.get("status") == "changed_unadjudicated"
                   and "evidence_digest" in changed.get("changed_fields", [])))
    changed_mtime = (semantic_run / "evidence.md").stat().st_mtime_ns
    changed_again = semantic_freshness(semantic_run)
    checks.append(("changed-digest assessment does not ritual-edit",
                   changed_again.get("remind") is True
                   and (semantic_run / "evidence.md").stat().st_mtime_ns == changed_mtime))
    anchor_semantic_changed = build_anchor(runs_root=_tmp_runs, active_pointer=test_pointer)
    checks.append(("anchor names changed canonical digest",
                   "canonical 内容已变化" in anchor_semantic_changed
                   and "freshness 不要求 Edit frontier.md" in anchor_semantic_changed))

    # Three decision-only transitions do not count as semantic trajectory progress.
    trajectory_run = _semantic_run("semantic_trajectory")
    record_reason_pass(
        trajectory_run, cycle_id=1, chosen_front="F-001", reason="baseline whole-graph pass"
    )
    for cycle in range(2, 5):
        with (trajectory_run / "decisions.md").open("a", encoding="utf-8") as handle:
            handle.write(f"\n## D-{cycle:03d}\n- Chosen front: F-001\n- Result: no new signal\n")
        record_reason_pass(
            trajectory_run,
            cycle_id=cycle,
            chosen_front="F-001",
            reason=f"cycle {cycle}: same precondition and no new signal",
        )
    stalled = semantic_trajectory(trajectory_run)
    checks.append(("consecutive no-semantic-progress cycles trigger trajectory review",
                   stalled.get("no_progress_cycles") == 3
                   and stalled.get("trajectory_review_due") is True))
    (trajectory_run / "evidence.md").write_text(
        "# Evidence Ledger\n\n## E-001\n- Maturity: candidate\n- Certainty: 0.5\n",
        encoding="utf-8",
    )
    record_reason_pass(
        trajectory_run, cycle_id=5, chosen_front="F-001", reason="new E-001 resets trajectory"
    )
    progressed = semantic_trajectory(trajectory_run)
    checks.append(("evidence/graph progress resets trajectory streak",
                   progressed.get("no_progress_cycles") == 0
                   and progressed.get("trajectory_review_due") is False))
    try:
        record_reason_pass(
            trajectory_run, cycle_id=7, chosen_front="F-001", reason="attempt to skip cycle 6"
        )
        skipped_cycle_rejected = False
    except ValueError:
        skipped_cycle_rejected = True
    checks.append(("receipt cycles cannot skip and hide a no-progress interval",
                   skipped_cycle_rejected))

    tampered_run = _semantic_run("tampered_receipt")
    record_reason_pass(
        tampered_run, cycle_id=1, chosen_front="F-001", reason="baseline before tamper"
    )
    tampered_path = _reason_pass_path(tampered_run)
    tampered_item = json.loads(tampered_path.read_text(encoding="utf-8"))
    tampered_item["evidence_digest"] = "0" * 64
    tampered_path.write_text(json.dumps(tampered_item) + "\n", encoding="utf-8")
    tampered_state = semantic_freshness(tampered_run)
    checks.append(("tampered receipt hash fails closed",
                   tampered_state.get("status") == "invalid"
                   and tampered_state.get("remind") is True))

    unknown_run = _semantic_run("unknown_receipt")
    unknown_receipt = record_reason_pass(
        unknown_run, cycle_id=1, chosen_front="F-001", reason="baseline before schema mutation"
    )
    unknown_receipt["schema"] = "xunji.reason-pass.v999"
    unknown_receipt["receipt_hash"] = _receipt_hash(unknown_receipt)
    _reason_pass_path(unknown_run).write_text(
        json.dumps(unknown_receipt) + "\n", encoding="utf-8"
    )
    unknown_state = semantic_freshness(unknown_run)
    checks.append(("unknown receipt schema fails closed",
                   unknown_state.get("status") == "invalid"
                   and "unknown reason-pass schema" in unknown_state.get("reason", "")))

    # Operational liveness is event/state based and deliberately clock-free.
    liveness_run = _semantic_run("operational_liveness")
    unknown_liveness = operational_liveness(liveness_run)
    journal = liveness_run / "state" / "loop_journal.jsonl"
    journal.parent.mkdir(exist_ok=True)
    start_event = {
        "schema": "xunji.loop_journal.v1",
        "cycle": 1,
        "event": "cycle_start",
        "ts": "2000-01-01T00:00:00Z",
    }
    journal.write_text(json.dumps(start_event) + "\n", encoding="utf-8")
    os.utime(journal, (1, 1))
    active_liveness = operational_liveness(liveness_run)
    with journal.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps({
            "schema": "xunji.loop_journal.v1",
            "cycle": 1,
            "event": "cycle_end",
            "ts": "2000-01-01T00:00:01Z",
        }) + "\n")
    quiescent_liveness = operational_liveness(liveness_run)
    checks.append(("operational liveness is separate and clock-free",
                   unknown_liveness.get("status") == "unknown"
                   and active_liveness.get("status") == "active"
                   and active_liveness.get("clock_free") is True
                   and quiescent_liveness.get("status") == "quiescent"))

    schema_path = ROOT / "contracts" / "reason-pass-receipt.v1.schema.json"
    try:
        schema = json.loads(schema_path.read_text(encoding="utf-8"))
    except Exception:
        schema = {}
    checks.append(("published reason-pass schema matches runtime contract",
                   schema.get("properties", {}).get("schema", {}).get("const") == REASON_PASS_SCHEMA
                   and set(schema.get("required", [])) == _REASON_PASS_FIELDS
                   and schema.get("additionalProperties") is False))

    # Agent Board 强制门 selftest
    ab_dir = _tmp_runs / "_selftest_agent_board"
    ab_dir.mkdir(parents=True)
    (ab_dir / "evidence.md").write_text("# test", encoding="utf-8")

    # Case 1: < 4 open fronts -> should NOT remind
    (ab_dir / "frontier.md").write_text(
        "# Frontier\n## Open\n"
        "### F-001\n- Status: open\n- Barrier class: none\n\n"
        "### F-002\n- Status: open\n- Barrier class: none\n\n"
        "### F-003\n- Status: probing\n- Barrier class: WAF\n",
        encoding="utf-8")
    needed_lt4, n_lt4, _ = _check_agent_board_needed(ab_dir)
    checks.append(("agent board: <4 active fronts -> not needed", not needed_lt4 and n_lt4 == 3))

    # Case 2: >= 4 open fronts with shared barrier (SharedBarrierGroup exists) -> should NOT remind
    (ab_dir / "frontier.md").write_text(
        "# Frontier\n## Open\n"
        "### F-001\n- Status: open\n- Barrier class: WAF-rate-limit\n\n"
        "### F-002\n- Status: open\n- Barrier class: WAF-rate-limit\n\n"
        "### F-003\n- Status: open\n- Barrier class: WAF-rate-limit\n\n"
        "### F-004\n- Status: open\n- Barrier class: WAF-rate-limit\n",
        encoding="utf-8")
    needed_shared, n_shared, bg_shared = _check_agent_board_needed(ab_dir)
    checks.append(("agent board: shared barrier -> not needed", not needed_shared and n_shared == 4))
    checks.append(("agent board: shared barrier group detected", len(bg_shared.get("waf-rate-limit", [])) == 4))

    # Case 3: >= 4 open fronts with diverse barriers (no SharedBarrierGroup) -> MUST remind
    (ab_dir / "frontier.md").write_text(
        "# Frontier\n## Open\n"
        "### F-001\n- Status: open\n- Barrier class: SQL-injection\n\n"
        "### F-002\n- Status: open\n- Barrier class: XSS-filter\n\n"
        "### F-003\n- Status: open\n- Barrier class: auth-bypass\n\n"
        "### F-004\n- Status: open\n- Barrier class: file-upload\n",
        encoding="utf-8")
    needed_div, n_div, bg_div = _check_agent_board_needed(ab_dir)
    checks.append(("agent board: diverse barriers -> needed", needed_div and n_div == 4))
    checks.append(("agent board: no shared group in diverse", all(len(v) < 2 for v in bg_div.values())))

    # Case 4: >= 4 open with all barriers none/unknown -> diverse (remind)
    (ab_dir / "frontier.md").write_text(
        "# Frontier\n## Open\n"
        "### F-001\n- Status: open\n- Barrier class: none\n\n"
        "### F-002\n- Status: open\n- Barrier class: unknown\n\n"
        "### F-003\n- Status: open\n- Barrier class: none\n\n"
        "### F-004\n- Status: open\n- Barrier class: \n",
        encoding="utf-8")
    needed_none, n_none, bg_none = _check_agent_board_needed(ab_dir)
    checks.append(("agent board: all none/unknown -> needed", needed_none and n_none == 4))
    checks.append(("agent board: none/unknown not grouped", len(bg_none) == 0))

    class _BrokenRunModel:
        @staticmethod
        def summary(_run):
            raise RuntimeError("parser unavailable")

    parser_fail = _check_agent_board_needed(ab_dir, _model=_BrokenRunModel())
    checks.append(("agent board: parser failure with frontier -> fail closed",
                   parser_fail[0] and parser_fail[1] >= 4
                   and "state-parser-failure" in parser_fail[2]))

    # Case 5: verify build_anchor injects the reminder
    test_pointer.write_text(str(ab_dir), encoding="utf-8")
    anchor_ab = build_anchor(runs_root=_tmp_runs, active_pointer=test_pointer)
    checks.append(("agent board: anchor injects typed owner reminder",
                   "Agent Board 强制" in anchor_ab
                   and "xunji-agent-board" in anchor_ab
                   and "workers.py assign" not in anchor_ab))

    # Case 6: missing frontier.md -> not needed
    no_frontier = _tmp_runs / "no_frontier_run"
    no_frontier.mkdir()
    (no_frontier / "evidence.md").write_text("# test", encoding="utf-8")
    needed_nf, n_nf, _ = _check_agent_board_needed(no_frontier)
    checks.append(("agent board: no frontier.md -> not needed", not needed_nf and n_nf == 0))

    bad = [n for n, ok in checks if not ok]
    for n, ok in checks:
        print(("ok   " if ok else "FAIL ") + n, file=sys.stderr)
    print("anti_drift selftest " + ("passed" if not bad else f"FAILED ({len(bad)})"), file=sys.stderr)
    return 0 if not bad else 1


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Xunji semantic anti-drift anchor")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--selftest", action="store_true", help="run offline regression fixtures")
    mode.add_argument(
        "--record-reason-pass", metavar="RUN_DIR",
        help="append a v1 Reason-pass receipt for a stable canonical snapshot",
    )
    mode.add_argument(
        "--semantic-status", metavar="RUN_DIR",
        help="print semantic freshness, trajectory, and separate operational liveness",
    )
    parser.add_argument(
        "--cycle-id", type=int,
        help="optional explicit receipt sequence; omitted means the next valid value",
    )
    parser.add_argument("--chosen-front", help="chosen F-<number> or NONE")
    parser.add_argument("--reason", help="bounded whole-graph adjudication rationale")
    args = parser.parse_args(argv)

    if args.selftest:
        return _selftest()
    if args.record_reason_pass:
        missing = [
            flag for flag, value in (
                ("--chosen-front", args.chosen_front),
                ("--reason", args.reason),
            )
            if value is None
        ]
        if missing:
            parser.error("--record-reason-pass requires " + ", ".join(missing))
        try:
            receipt = record_reason_pass(
                args.record_reason_pass,
                cycle_id=args.cycle_id,
                chosen_front=args.chosen_front,
                reason=args.reason,
            )
        except Exception as exc:
            print(f"[anti_drift] reason-pass receipt rejected: {exc}", file=sys.stderr)
            return 2
        print(json.dumps(receipt, ensure_ascii=False, sort_keys=True))
        return 0
    if args.semantic_status:
        run = Path(args.semantic_status).resolve()
        result = {
            "semantic_freshness": semantic_freshness(run),
            "semantic_trajectory": semantic_trajectory(run),
            "operational_liveness": operational_liveness(run),
        }
        print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
        return 1 if result["semantic_freshness"].get("status") == "invalid" else 0
    try:
        print(build_anchor())
    except Exception:
        # FAIL-OPEN: still anchor the static rules; never break a turn.
        print("[ANTI-DRIFT ANCHOR]\n绑定规则: " + " · ".join(BINDING_RULES_TIER1 + BINDING_RULES_TIER3))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
