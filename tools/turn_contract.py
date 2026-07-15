#!/usr/bin/env python3
"""Claude Code turn-mode and PreToolUse contract for active Xunji runs.

The user's current prompt decides whether this turn executes, explains, or pauses.
Stop hooks consume the same state, so an explanation is not forced to fabricate a
Coda and a pause is not mistaken for closure.
"""
from __future__ import annotations

import argparse
import hashlib
import ipaddress
import json
import os
import re
import shlex
import sys
import tempfile
import time
from urllib.parse import urlsplit
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
RUNS = Path(os.environ.get("XUNJI_RUNS_ROOT", str(ROOT / "runs")))
ACTIVE_RUN_POINTER = Path(os.environ.get(
    "XUNJI_ACTIVE_RUN_FILE", str(ROOT / ".claude" / "xunji_active_run")))
PENDING_DIR = Path(os.environ.get(
    "XUNJI_PENDING_TURN_DIR", str(ROOT / ".claude" / "xunji_pending_turns")))
TRANSITION_CLAIMS_DIR = Path(os.environ.get(
    "XUNJI_TRANSITION_CLAIMS_DIR",
    str(ROOT / ".claude" / "xunji_transition_claims")))
sys.path.insert(0, str(ROOT / "tools"))

import run_model  # noqa: E402
import runtime_receipts  # noqa: E402
import scope_admission  # noqa: E402
import setup_normalizer  # noqa: E402
import setup_source  # noqa: E402
from harness.command_shape import (  # noqa: E402
    has_unquoted_shell_control as _has_unquoted_shell_control,
    parse_exact_python_command,
)
from harness import maintenance_authority  # noqa: E402


SCHEMA = "xunji.turn_contract.v1"
EXECUTE = "EXECUTE"
EXPLAIN = "EXPLAIN_ONLY"
PAUSE = "PAUSED_BY_OPERATOR"
MAINTENANCE = "MAINTENANCE"
NORMAL = "NORMAL"
STALE_SECONDS = 6 * 60 * 60
PENDING_STALE_SECONDS = 15 * 60
COMPLETION_CHECKS = (
    "report_parity", "severity_artifacts", "reachable_frontier", "review_ledger",
)
CONTROL_SCRIPTS = {
    (ROOT / "tools" / name).resolve()
    for name in (
        "graph.py",
        "coverage_matrix.py",
        "ingest_recon.py",
        "loop_bootstrap.py",
        "loop_journal.py",
        "loop_state.py",
        "progress_ledger.py",
        "run_controller.py",
        "session_handoff.py",
        "setup_run.py",
        "workers.py",
        "xunji_statusline.py",
        "run_model.py",
        "scope_admission.py",
    )
}
LOCAL_VERIFICATION_SCRIPTS = {
    (ROOT / path).resolve() for path in (
        "tools/selftest_all.py",
        "tools/check_rules.py",
        "tools/check_hook.py",
        "tools/check_runtime_boundary.py",
        "tools/check_templates.py",
        "tools/harness/command_shape.py",
        "tools/harness/guard.py",
        "tools/harness/maintenance_authority.py",
        "tools/harness/privacy.py",
        "tools/setup_source.py",
        "tools/run_model.py",
        "tools/runtime_receipts.py",
        "tools/turn_contract.py",
        ".claude/hooks/ip_blacklist.py",
        ".claude/hooks/output_gate.py",
        ".claude/hooks/run_gate.py",
        ".claude/hooks/safety_gate.py",
        "sentinel/replay.py",
        "sentinel/verify_layers.py",
    )
}
TRUSTED_TARGET_ENV_KEYS = {
    "LANG", "LC_ALL", "PYTHONIOENCODING", "PYTHONUTF8",
    "XUNJI_PROXY", "XUNJI_PROXY_REQUIRED",
}
PROXY_AWARE_TARGET_TOOLS = {
    (ROOT / "tools" / name).resolve() for name in (
        "probe.py", "render.py", "scan.py", "replay.py", "rerun_deferred.py",
        "fetch_assets.py", "classify_hosts.py", "cdn_bypass.py", "exploit.py",
    )
}
RAW_NETWORK_CLIENT_RE = re.compile(
    r"(?i)(?:^|[\s;&|])(curl|wget|httpx|nuclei|sqlmap)(?:\s|$)|"
    r"\b(?:requests\.(?:get|post|request)|urllib\.request|socket\.(?:socket|create_connection))\b"
)
DIRECT_EGRESS_ENV_RE = re.compile(
    r"(?i)\bXUNJI_PROXY_REQUIRED\s*=\s*(?:0|false|no|off)\b"
)
DIRECT_EGRESS_APPROVAL_RE = re.compile(
    r"(?:明确)?(?:允许|接受|批准|同意).{0,24}(?:直连|direct[ -]?egress)|"
    r"(?:allow|approve|accept).{0,24}direct[ -]?egress",
    re.I,
)
DIRECT_EGRESS_DENIAL_RE = re.compile(
    r"(?:不|不要|不得|禁止|拒绝).{0,16}(?:允许|接受|批准|同意|直连)|"
    r"(?:do\s+not|don't|never|deny|forbid).{0,24}"
    r"(?:allow|approve|accept|direct[ -]?egress)",
    re.I,
)
NON_EGRESS_TOOLS = {
    "Agent", "AskUserQuestion", "CronCreate", "CronDelete", "CronList",
    "Edit", "Glob", "Grep", "ListMcpResourcesTool", "MultiEdit", "NotebookEdit",
    "Read", "ReadMcpResourceTool", "Skill", "TaskOutput", "TaskStop", "TodoWrite",
    "WebSearch", "Write",
}

EXPLAIN_RE = re.compile(
    r"告诉我(?:原因|为什么|想法)|为什么|不用修改|不要修改|无需修改|别修改|"
    r"不用做|不要做|先别做|只(?:告诉|回答|分析|解释|说明)|无需执行|"
    r"tell me why|explain only|do not (?:change|modify|act)|no changes",
    re.I,
)
PAUSE_RE = re.compile(
    r"停止\s*(?:loop|循环|渗透|运行)|渗透结束|暂停\s*(?:loop|循环|渗透|运行)|"
    r"先停(?:止|下)|stop\s+(?:the\s+)?(?:loop|run|testing)|pause\s+(?:the\s+)?(?:loop|run)",
    re.I,
)
EXECUTE_RE = re.compile(
    r"(?:^|\s)/loop\b|继续(?:执行|推进|修复|运行|渗透)?|恢复(?:执行|运行|loop)?|"
    r"修复|实现|落实|执行|修改|彻底解决|开始(?:运行|渗透)|"
    r"resume|continue|implement|fix|execute|apply",
    re.I,
)
MEMORY_APPROVAL_RE = re.compile(r"(?:明确|现在)?(?:写入|保存|更新)(?:长期)?记忆|approve memory|write (?:to )?memory", re.I)
INTERNAL_PROMPT_RE = re.compile(
    r"^\s*<(?:task-notification|system-reminder|local-command-caveat)\b",
    re.I,
)
MEMORY_PATH_RE = re.compile(
    r"(?:^|[/\\\s\"'=])\.claude(?:[/\\].*)?[/\\](?:memory|memories)(?:[/\\]|$)|"
    r"(?:^|[/\\\s\"'=])MEMORY\.md(?=[\"'\s;|&}]|$)",
    re.I,
)
BACKGROUND_REVIEW_RE = re.compile(
    r"(?s)(?:\bnohup\b.*?peer_review\.py|peer_review\.py.*?(?<![>&])&(?![>&]))",
    re.I,
)
PROTECTED_RUNTIME_RE = re.compile(
    r"(?:runtime_events\.jsonl|runtime_projection_error\.json|coverage\.json|"
    r"asset_ledger\.json|\.runtime_events\.lock|"
    r"turn_contract\.json|run_status\.json|setup_source\.json|setup_transaction\.json|"
    r"sources[/\\](?:normalized\.json|validator_receipt\.json|original[/\\][^\s;|&]+)|"
    r"\.xunji_(?:activation|setup|scope_admission)\.lock|\.xunji_staging|"
    r"assignments\.json|scope_admissions|xunji_active_run|xunji_pending_turns|"
    r"xunji_transition_claims|xunji_scope_admission_claims|"
    r"review[/\\]receipts[/\\][0-9a-f]{64}\.json)"
    r"(?=[.\/\\\"'\s;|&}]|$)",
    re.I,
)
CLEAR_ACTIVE_RE = re.compile(
    r"(?:清除|清空|取消|移除).{0,20}(?:active[ -]?run|运行指针)|"
    r"(?:clear|remove|unset).{0,20}active[ -]?run",
    re.I,
)
RUN_TRANSITION_RE = re.compile(
    r"(?:新建|创建|建立|重开|重新开|初始化|启动).{0,24}(?:run|运行)|"
    r"(?:new|create|setup|start).{0,24}run",
    re.I,
)
RUN_BIND_RE = re.compile(
    r"(?:/loop\s+(?:[^\n]*runs[/\\]|https?://\S+|(?:/|\.{1,2}/|[A-Za-z]:[/\\])\S+)|"
    r"(?:恢复|续接|resume|continue).{0,24}(?:run|运行)|"
    r"(?:set-active|setup_run\.py|loop_bootstrap\.py)|"
    r"(?:设置|切换|选择|绑定|set|switch|select|bind).{0,20}active[ -]?run)",
    re.I,
)


def _atomic_json(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, raw = tempfile.mkstemp(prefix=path.name + ".", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(value, handle, ensure_ascii=False, indent=2, sort_keys=True)
            handle.write("\n")
        os.chmod(raw, 0o600)
        os.replace(raw, path)
    finally:
        try:
            os.unlink(raw)
        except FileNotFoundError:
            pass


def contract_path(run_dir: Path) -> Path:
    return run_dir / "state" / "turn_contract.json"


def run_status_path(run_dir: Path) -> Path:
    return run_dir / "state" / "run_status.json"


def explicit_active_run(
    runs_root: Path | None = None,
    pointer: Path | None = None,
) -> Path | None:
    """Resolve only the authoritative pointer; contracts must never guess a run."""
    root = (runs_root or RUNS).resolve()
    marker = pointer or ACTIVE_RUN_POINTER
    try:
        raw = marker.read_text(encoding="utf-8", errors="replace").strip()
        if not raw:
            return None
        candidate = Path(raw).expanduser()
        if not candidate.is_absolute():
            candidate = ROOT / candidate
        candidate = candidate.resolve()
        candidate.relative_to(root)
    except Exception:
        return None
    if not candidate.is_dir():
        return None
    if not any((candidate / name).exists() for name in (
            "target.md", "frontier.md", "evidence.md", "decisions.md", "review.md")):
        return None
    return candidate


def classify_prompt(prompt: str, *, active_run: bool = True) -> str:
    prompt = prompt or ""
    if not active_run:
        return NORMAL
    if PAUSE_RE.search(prompt):
        return PAUSE
    if EXPLAIN_RE.search(prompt):
        return EXPLAIN
    if RUN_TRANSITION_RE.search(prompt) or RUN_BIND_RE.search(prompt):
        return EXECUTE
    if EXECUTE_RE.search(prompt):
        return EXECUTE
    if re.search(r"[?？]\s*$", prompt) or re.match(r"^\s*(?:怎么|如何|是否|什么|哪|谁)", prompt):
        return EXPLAIN
    return EXPLAIN


def _contract_from_event(event: dict, *, run_name: str = "") -> dict:
    prompt = str(event.get("prompt") or "")
    maintenance, maintenance_error = maintenance_authority.parse_directive(prompt)
    scope_request, scope_error = scope_admission.parse_operator_directive(prompt)
    if maintenance and not str(event.get("session_id") or ""):
        maintenance = None
        maintenance_error = "maintenance authority requires a non-empty hook session id"
    if scope_request and not str(event.get("session_id") or ""):
        scope_request = None
        scope_error = "scope admission authority requires a non-empty hook session id"
    if maintenance and scope_request:
        scope_request = None
        scope_error = "maintenance and scope admission directives cannot share one turn"
    mode = MAINTENANCE if maintenance else (
        EXECUTE if scope_request else classify_prompt(prompt, active_run=True)
    )
    if maintenance_error:
        # A malformed top-level maintenance command never falls through into a
        # broad EXECUTE turn merely because the prompt also contains "fix".
        mode = EXPLAIN
    if scope_error:
        mode = EXPLAIN
    now = time.time()
    contract = {
        "schema": SCHEMA,
        "mode": mode,
        "session_id": str(event.get("session_id") or ""),
        "transcript_path": str(event.get("transcript_path") or ""),
        "prompt_sha256": hashlib.sha256(prompt.encode("utf-8", "replace")).hexdigest(),
        "prompt_excerpt": prompt[:500],
        "memory_approved": bool(MEMORY_APPROVAL_RE.search(prompt)),
        "direct_egress_approved": bool(
            DIRECT_EGRESS_APPROVAL_RE.search(prompt)
            and not DIRECT_EGRESS_DENIAL_RE.search(prompt)
        ),
        "fanout_override": bool(re.search(r"(?:明确)?允许串行|不要使用\s*(?:Agent|子代理)|serial override", prompt, re.I)),
        "origin_run": run_name,
        "bound_run": run_name,
        "updated_at": now,
    }
    if maintenance:
        contract["maintenance_authorized_paths"] = list(
            maintenance.get("authorized_paths") or [])
        contract["maintenance_critical_paths"] = list(
            maintenance.get("critical_paths") or [])
        contract["maintenance_reason"] = str(maintenance.get("reason") or "")
        contract["maintenance_reason_sha256"] = str(
            maintenance.get("reason_sha256") or "")
    if maintenance_error:
        contract["maintenance_parse_error"] = maintenance_error
    if scope_request:
        contract["scope_admission_run"] = str(scope_request.get("run_name") or "")
        contract["scope_admission_assets"] = list(scope_request.get("assets") or [])
        contract["scope_admission_reason_sha256"] = str(
            scope_request.get("reason_sha256") or "")
    if scope_error:
        contract["scope_admission_parse_error"] = scope_error
    return contract


def _safe_run_summary(run_dir: Path) -> tuple[dict, str]:
    """Keep hook execution deterministic when canonical state parsing fails."""
    try:
        state = run_model.summary(run_dir)
    except Exception as exc:
        note = f"{exc.__class__.__name__}: run_model.summary failed"
        return {"fronts": [], "open": [], "schema_errors": [note]}, note
    return (state if isinstance(state, dict) else {
        "fronts": [], "open": [], "schema_errors": ["invalid run_model summary"],
    }), ""


def _coordination_signature(run_dir: Path) -> str:
    """Hash only topology and coverage debt that should start a new fan-out epoch."""
    state, summary_error = _safe_run_summary(run_dir)
    fronts = sorted(
        (str(item.get("id") or ""), str(item.get("status") or ""), str(item.get("barrier") or ""))
        for item in state.get("fronts", [])
        if isinstance(item, dict) and str(item.get("id") or "") in set(state.get("open", []))
    )
    assets: list[tuple] = []
    coverage_paths = [run_dir / "coverage.json", *sorted(run_dir.glob("**/coverage.json"))]
    for path in coverage_paths:
        if not path.exists():
            continue
        try:
            coverage = json.loads(path.read_text(encoding="utf-8", errors="replace"))
        except Exception:
            continue
        for asset in coverage.get("assets", []) if isinstance(coverage, dict) else []:
            if not isinstance(asset, dict) or asset.get("reachable") is False:
                continue
            host = str(asset.get("host") or asset.get("asset") or asset.get("url") or "").lower()
            if not host:
                continue
            assets.append((
                host,
                str(asset.get("reachable")),
                bool(asset.get("examined")),
                str(asset.get("verdict") or ""),
                tuple(sorted(str(item) for item in (asset.get("tested_groups") or []))),
            ))
        break
    try:
        import coverage_matrix  # noqa: WPS433
        matrix = coverage_matrix.derive(run_dir)
        assets = sorted(
            (str(row.get("asset") or ""), str(row.get("reachability")),
             str(row.get("disposition") or ""), tuple(sorted(row.get("fronts") or [])),
             tuple(sorted(row.get("tested") or [])))
            for row in matrix.get("rows", [])
            if isinstance(row, dict) and row.get("reachability") is not False
        )
    except Exception:
        pass
    return hashlib.sha256(json.dumps(
        {"fronts": fronts, "coverage_debt": sorted(assets),
         "summary_error": summary_error},
        ensure_ascii=False, sort_keys=True, separators=(",", ":"),
    ).encode("utf-8")).hexdigest()


def _previous_contract(run_dir: Path) -> dict:
    try:
        data = json.loads(contract_path(run_dir).read_text(encoding="utf-8", errors="replace"))
    except Exception:
        return {}
    return data if isinstance(data, dict) and data.get("schema") == SCHEMA else {}


def write_contract(run_dir: Path, event: dict) -> dict:
    previous = _previous_contract(run_dir)
    contract = _contract_from_event(event, run_name=run_dir.name)
    requested_scope_run = str(contract.get("scope_admission_run") or "")
    if requested_scope_run and requested_scope_run != run_dir.name:
        contract.pop("scope_admission_run", None)
        contract.pop("scope_admission_assets", None)
        contract.pop("scope_admission_reason_sha256", None)
        contract["scope_admission_parse_error"] = (
            "scope admission run must equal the exact active run"
        )
        contract["mode"] = EXPLAIN
    signature = _coordination_signature(run_dir)
    previous_since = float(previous.get("fanout_epoch_started_at") or 0.0)
    if previous.get("coordination_signature") == signature and previous_since > 0:
        contract["fanout_epoch_started_at"] = previous_since
        contract["fanout_epoch_id"] = str(previous.get("fanout_epoch_id") or "")
    else:
        contract["fanout_epoch_started_at"] = float(contract["updated_at"])
        contract["fanout_epoch_id"] = hashlib.sha256(
            f"{run_dir.resolve()}:{signature}:{contract['updated_at']}".encode("utf-8")
        ).hexdigest()[:16]
    contract["coordination_signature"] = signature
    _atomic_json(contract_path(run_dir), contract)
    _write_run_status(run_dir, contract)
    return contract


def _pending_path(session_id: str, pending_dir: Path | None = None) -> Path:
    digest = hashlib.sha256(session_id.encode("utf-8", "replace")).hexdigest()
    return (pending_dir or PENDING_DIR) / f"{digest}.json"


def write_pending_contract(event: dict, *, pending_dir: Path | None = None) -> dict:
    """Persist a short-lived operator contract while no run exists yet."""
    session_id = str(event.get("session_id") or "")
    if not session_id:
        return {}
    contract = _contract_from_event(event)
    prompt = str(contract.get("prompt_excerpt") or "")
    maintenance_attempt = contract.get("mode") == MAINTENANCE \
        or bool(contract.get("maintenance_parse_error"))
    if not maintenance_attempt and (
            contract.get("mode") != EXECUTE or not (
                RUN_TRANSITION_RE.search(prompt) or RUN_BIND_RE.search(prompt))):
        return {}
    _atomic_json(_pending_path(session_id, pending_dir), contract)
    return contract


def load_pending_contract(session_id: str, *, pending_dir: Path | None = None) -> dict:
    if not session_id:
        return {}
    try:
        data = json.loads(_pending_path(session_id, pending_dir).read_text(
            encoding="utf-8", errors="replace"))
        age = time.time() - float(data.get("updated_at") or 0.0)
    except Exception:
        return {}
    valid_mode = data.get("mode") in {EXECUTE, MAINTENANCE} or (
        data.get("mode") == EXPLAIN and bool(data.get("maintenance_parse_error"))
    )
    if data.get("schema") != SCHEMA or not valid_mode:
        return {}
    if not str(data.get("session_id") or "") or age < 0 or age > PENDING_STALE_SECONDS:
        return {}
    return data


def _transition_claim_path(
    target_name: str,
    session_id: str,
    claims_dir: Path | None = None,
) -> Path:
    target_digest = hashlib.sha256(
        target_name.encode("utf-8", "replace")).hexdigest()
    session_digest = hashlib.sha256(
        session_id.encode("utf-8", "replace")).hexdigest()
    return (claims_dir or TRANSITION_CLAIMS_DIR) / f"{target_digest}-{session_digest}.json"


def _transition_claim_glob(target_name: str) -> str:
    digest = hashlib.sha256(target_name.encode("utf-8", "replace")).hexdigest()
    return f"{digest}-*.json"


def write_transition_claim(
    target_name: str,
    contract: dict,
    *,
    claims_dir: Path | None = None,
) -> dict:
    """Bind a no-run lifecycle PreToolUse event to one exact target run name."""
    session_id = str(contract.get("session_id") or "")
    prompt_sha = str(contract.get("prompt_sha256") or "")
    if not target_name or not session_id or not prompt_sha:
        raise ValueError("transition claim requires target/session/prompt hash")
    claim = {
        "schema": SCHEMA,
        "target_run": target_name,
        "session_id": session_id,
        "prompt_sha256": prompt_sha,
        "updated_at": time.time(),
    }
    _atomic_json(_transition_claim_path(target_name, session_id, claims_dir), claim)
    return claim


def _lifecycle_target_name(invocation: tuple[Path, list[str]]) -> str:
    script, args = invocation
    if script.name == "xunji_statusline.py" and "--set-active" in args:
        try:
            return Path(args[args.index("--set-active") + 1]).name
        except (ValueError, IndexError):
            return ""
    if script.name == "loop_bootstrap.py" and "--resume" in args:
        try:
            return Path(args[args.index("--resume") + 1]).name
        except (ValueError, IndexError):
            return ""
    if script.name == "loop_bootstrap.py" and "--source" in args:
        try:
            source_value = args[args.index("--source") + 1]
            source_type = args[args.index("--type") + 1] if "--type" in args else "auto"
            route = setup_source.route_source(
                source_value, source_type=source_type, runs_root=ROOT / "runs"
            )
        except (ValueError, IndexError, setup_source.SetupSourceError):
            return ""
        if route.kind == "run" and route.run_dir is not None:
            return route.run_dir.name
        if route.kind in {"json", "markdown"} and route.source_path is not None:
            if "--prepare-normalizer" in args:
                return ""
            try:
                ai_mode = args[args.index("--ai") + 1] if "--ai" in args else "off"
                provider = args[args.index("--ai-provider") + 1] \
                    if "--ai-provider" in args else ""
                model = args[args.index("--ai-model") + 1] \
                    if "--ai-model" in args else ""
                candidate_json = args[args.index("--candidate-json") + 1] \
                    if "--candidate-json" in args else None
                manifest, _raw, _artifacts = setup_normalizer.normalize_path(
                    route.source_path,
                    ai_mode=ai_mode,
                    candidate_json=candidate_json,
                    provider=provider,
                    model=model,
                )
                slug = setup_normalizer.derive_slug(manifest)
            except (ValueError, IndexError, setup_source.SetupSourceError):
                return ""
            return f"{slug}_{datetime.now().strftime('%Y%m%d')}"
        return f"{route.slug}_{datetime.now().strftime('%Y%m%d')}" if route.slug else ""
    if script.name not in {"setup_run.py", "loop_bootstrap.py"}:
        return ""
    value_options = {"--date", "--target"}
    flag_options = {"--classify"}
    positionals: list[str] = []
    date_value = datetime.now().strftime("%Y%m%d")
    index = 0
    while index < len(args):
        token = args[index]
        if token in value_options:
            if index + 1 >= len(args):
                return ""
            if token == "--date":
                date_value = args[index + 1]
            index += 2
            continue
        if token in flag_options:
            index += 1
            continue
        if token.startswith("-"):
            # Fail closed when setup/loop_bootstrap gains a new option. An
            # unknown value must never be mistaken for the run slug.
            return ""
        positionals.append(token)
        index += 1
    if not positionals:
        return ""
    slug = re.sub(r"[^A-Za-z0-9_-]", "_", positionals[0])
    return f"{slug}_{date_value}"


def claim_pending_contract(
    target_run: Path,
    *,
    pending_dir: Path | None = None,
    claims_dir: Path | None = None,
    transaction_id: str = "",
    source_hash: str = "",
    expected_run: str = "",
) -> dict:
    """Consume the exact hook claim and bind it to one setup transaction.

    Claim contents still come only from PreToolUse.  Transaction callers may
    supply the mechanically derived transaction/source identity, but cannot
    supply a session, prompt hash, authority bit, or claim path.
    """
    if expected_run and expected_run != target_run.name:
        raise RuntimeError("transition claim expected run mismatch")
    identity_values = (transaction_id, source_hash, expected_run)
    if any(identity_values) and not all(identity_values):
        raise RuntimeError("transition claim transaction identity is incomplete")
    if transaction_id and not re.fullmatch(r"[0-9a-f]{32}", transaction_id):
        raise RuntimeError("transition claim transaction id is invalid")
    if source_hash and not re.fullmatch(r"[0-9a-f]{64}", source_hash):
        raise RuntimeError("transition claim source hash is invalid")
    directory = pending_dir or PENDING_DIR
    if not directory.is_dir():
        return {}
    claim_directory = claims_dir or TRANSITION_CLAIMS_DIR
    claim_paths = list(claim_directory.glob(_transition_claim_glob(target_run.name))) \
        if claim_directory.is_dir() else []
    valid_claims: list[tuple[Path, dict]] = []
    for candidate in claim_paths:
        try:
            item = json.loads(candidate.read_text(encoding="utf-8", errors="replace"))
            item_age = time.time() - float(item.get("updated_at") or 0.0)
        except Exception:
            continue
        if item.get("schema") == SCHEMA and item.get("target_run") == target_run.name \
                and str(item.get("session_id") or "") \
                and 0 <= item_age <= PENDING_STALE_SECONDS:
            valid_claims.append((candidate, item))
    if len(valid_claims) > 1:
        raise RuntimeError("multiple session claims for one target run")
    try:
        claim_path, claim = valid_claims[0]
        claim_age = time.time() - float(claim.get("updated_at") or 0.0)
    except IndexError:
        # A normal shell/operator set-active outside Claude has no pending files.
        fresh_pending = False
        for path in directory.glob("*.json"):
            try:
                data = json.loads(path.read_text(encoding="utf-8", errors="replace"))
                age = time.time() - float(data.get("updated_at") or 0.0)
                fresh_pending = fresh_pending or bool(
                    data.get("schema") == SCHEMA
                    and data.get("mode") == EXECUTE
                    and str(data.get("session_id") or "")
                    and 0 <= age <= PENDING_STALE_SECONDS
                )
            except Exception:
                continue
        if not fresh_pending:
            return {}
        raise RuntimeError("pending contract exists without a target claim")
    if claim.get("schema") != SCHEMA or claim.get("target_run") != target_run.name \
            or claim_age < 0 or claim_age > PENDING_STALE_SECONDS:
        raise RuntimeError("stale or mismatched transition claim")
    session_id = str(claim.get("session_id") or "")
    contract = load_pending_contract(session_id, pending_dir=directory)
    if not contract:
        raise RuntimeError("transition claim has no matching pending contract")
    if str(contract.get("prompt_sha256") or "") != str(claim.get("prompt_sha256") or ""):
        raise RuntimeError("transition claim prompt hash mismatch")
    if not session_id:
        return {}
    contract = dict(contract)
    contract["bound_run"] = target_run.name
    contract["transitioned_from"] = "pending:no-active-run"
    if transaction_id:
        contract["transition_transaction"] = {
            "transaction_id": transaction_id,
            "source_sha256": source_hash,
            "expected_run": expected_run,
        }
    _atomic_json(contract_path(target_run), contract)
    _write_run_status(target_run, contract)
    try:
        _pending_path(session_id, directory).unlink()
    except FileNotFoundError:
        pass
    try:
        claim_path.unlink()
    except FileNotFoundError:
        pass
    return contract


def _write_run_status(run_dir: Path, contract: dict) -> None:
    """Project a transferred/operator contract into the target run status."""
    mode = str(contract.get("mode") or "")
    now = float(contract.get("updated_at") or time.time())
    if mode == PAUSE:
        _atomic_json(run_status_path(run_dir), {
            "schema": SCHEMA,
            "status": "paused_by_operator",
            "session_id": contract["session_id"],
            "updated_at": now,
            "reason": "operator prompt requested pause; open fronts remain open",
        })
    elif mode == EXECUTE:
        _atomic_json(run_status_path(run_dir), {
            "schema": SCHEMA,
            "status": "active",
            "session_id": contract["session_id"],
            "updated_at": now,
            "reason": "operator prompt requested execution/resume",
        })
    elif mode == MAINTENANCE:
        _atomic_json(run_status_path(run_dir), {
            "schema": SCHEMA,
            "status": "maintenance",
            "session_id": contract["session_id"],
            "updated_at": now,
            "reason": "operator authorized exact-path framework maintenance; live run is frozen",
        })


def load_contract(run_dir: Path, *, session_id: str = "") -> dict:
    try:
        data = json.loads(contract_path(run_dir).read_text(encoding="utf-8", errors="replace"))
    except Exception:
        return {}
    if data.get("schema") != SCHEMA:
        return {}
    if session_id and str(data.get("session_id") or "") != session_id:
        return {}
    try:
        if time.time() - float(data.get("updated_at") or 0) > STALE_SECONDS:
            return {}
    except Exception:
        return {}
    return data


def transfer_contract(
    source_run: Path,
    target_run: Path,
    *,
    transaction_id: str = "",
    source_hash: str = "",
    expected_run: str = "",
) -> dict:
    """Copy and transaction-bind the contract before a pointer switch."""
    source_run = source_run.resolve()
    target_run = target_run.resolve()
    identity_values = (transaction_id, source_hash, expected_run)
    if any(identity_values) and not all(identity_values):
        raise RuntimeError("contract transfer transaction identity is incomplete")
    if expected_run and expected_run != target_run.name:
        raise RuntimeError("contract transfer expected run mismatch")
    if transaction_id and not re.fullmatch(r"[0-9a-f]{32}", transaction_id):
        raise RuntimeError("contract transfer transaction id is invalid")
    if source_hash and not re.fullmatch(r"[0-9a-f]{64}", source_hash):
        raise RuntimeError("contract transfer source hash is invalid")
    if source_run == target_run:
        return load_contract(source_run)
    source_contract = load_contract(source_run)
    if not source_contract:
        return {}
    contract = dict(source_contract)
    contract.setdefault("origin_run", source_run.name)
    contract["bound_run"] = target_run.name
    contract["transitioned_from"] = source_run.name
    if transaction_id:
        contract["transition_transaction"] = {
            "transaction_id": transaction_id,
            "source_sha256": source_hash,
            "expected_run": expected_run,
        }
    _atomic_json(contract_path(target_run), contract)
    _write_run_status(target_run, contract)
    return contract


def _tool_text(event: dict) -> str:
    value = event.get("tool_input") if isinstance(event.get("tool_input"), dict) else {}
    try:
        return json.dumps(value, ensure_ascii=False, sort_keys=True)
    except Exception:
        return str(value)


def _deny(reason: str) -> dict:
    return {
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": "deny",
            "permissionDecisionReason": reason,
        }
    }


def _protected_control_reason(event: dict) -> str:
    tool = str(event.get("tool_name") or "")
    if tool not in {"Write", "Edit", "Update", "MultiEdit", "NotebookEdit", "Bash"}:
        return ""
    if PROTECTED_RUNTIME_RE.search(_tool_text(event)):
        return (
            "active-run 指针、pending contract、运行时回执、资产账本和回合状态只能由"
            "受控工具/hook 原子写入；Claude 不得直接修改这些控制面文件。"
        )
    return ""


def _local_pycompile_bash(command: str) -> bool:
    """Accept direct ``python -m py_compile`` for repository-local Python files."""
    if _has_unquoted_shell_control(command):
        return False
    try:
        tokens = shlex.split(command, posix=True)
    except ValueError:
        return False
    if len(tokens) < 4 or not re.fullmatch(
            r"(?:python|python3)(?:\.\d+(?:\.\d+)?)?", Path(tokens[0]).name):
        return False
    if tokens[1:3] != ["-m", "py_compile"]:
        return False
    for raw in tokens[3:]:
        if raw.startswith("-"):
            return False
        candidate = Path(raw)
        if not candidate.is_absolute():
            candidate = ROOT / candidate
        try:
            candidate.resolve(strict=False).relative_to(ROOT.resolve())
        except ValueError:
            return False
        if candidate.suffix != ".py":
            return False
    return True


def _local_verification_bash(command: str) -> bool:
    """Allow one exact audited local regression command, never a shell wrapper."""
    if _local_pycompile_bash(command):
        return True
    invocation = parse_exact_python_command(
        command, root=ROOT, allowed_scripts=LOCAL_VERIFICATION_SCRIPTS
    )
    if invocation is None:
        return False
    script = invocation.script
    args = list(invocation.args)
    name = script.name
    if name == "selftest_all.py":
        allowed_flags = {"--verbose", "--list", "--only", "--timeout"}
        index = 0
        while index < len(args):
            flag = args[index]
            if flag not in allowed_flags:
                return False
            index += 1
            if flag in {"--only", "--timeout"}:
                if index >= len(args) or args[index].startswith("-"):
                    return False
                index += 1
        return True
    if name in {
        "check_rules.py", "check_hook.py", "check_runtime_boundary.py",
        "check_templates.py", "command_shape.py", "guard.py", "privacy.py",
        "replay.py", "verify_layers.py",
    }:
        return not args
    return args == ["--selftest"]


def _trusted_critical_execution_bash(
    command: str,
    *,
    tool_env: dict | None = None,
) -> bool:
    """Distinguish running an audited project entrypoint from modifying its source."""
    explicit_env = tool_env or {}
    if any(str(key) not in TRUSTED_TARGET_ENV_KEYS for key in explicit_env):
        return False
    if (_local_verification_bash(command) or _control_invocation(command) is not None) \
            and not explicit_env:
        return True
    candidate = command.strip()
    review_redirect = re.fullmatch(r"(.+?)\s+>\s+(/[^\s]+)\s+2>&1", candidate)
    if review_redirect and "peer_review.py" in review_redirect.group(1):
        candidate = review_redirect.group(1)
    allowed = set(PROXY_AWARE_TARGET_TOOLS) | {
        (ROOT / "tools" / "peer_review.py").resolve(),
    }
    invocation = parse_exact_python_command(candidate, root=ROOT, allowed_scripts=allowed)
    if invocation is not None:
        return invocation.script in PROXY_AWARE_TARGET_TOOLS or not explicit_env
    if _has_unquoted_shell_control(candidate):
        return False
    try:
        tokens = shlex.split(candidate, posix=True)
    except ValueError:
        return False
    inline_env: set[str] = set()
    while tokens and re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*=.*", tokens[0]):
        inline_env.add(tokens.pop(0).split("=", 1)[0])
    if not inline_env <= TRUSTED_TARGET_ENV_KEYS:
        return False
    invocation = parse_exact_python_command(
        shlex.join(tokens), root=ROOT, allowed_scripts=allowed
    ) if tokens else None
    if invocation is None:
        return False
    if invocation.script == (ROOT / "tools/peer_review.py").resolve() and inline_env:
        return False
    return invocation.script in PROXY_AWARE_TARGET_TOOLS


def _audited_bash_execution(event: dict) -> bool:
    """Allow only explicit Bash capabilities; unknown local shell is write-capable."""
    tool_input = event.get("tool_input") if isinstance(event.get("tool_input"), dict) else {}
    command = str(tool_input.get("command") or "")
    tool_env = tool_input.get("env") if isinstance(tool_input.get("env"), dict) else {}
    if not tool_env and _readonly_shell(command):
        return True
    return _trusted_critical_execution_bash(command, tool_env=tool_env)


def _maintenance_pretool_reason(event: dict, contract: dict) -> str:
    """Enforce exact mutation scope and a local-only maintenance turn."""
    tool = str(event.get("tool_name") or "")
    tool_input = event.get("tool_input") if isinstance(event.get("tool_input"), dict) else {}
    command = str(tool_input.get("command") or "")
    parse_error = str(contract.get("maintenance_parse_error") or "")
    readonly_tools = {"Read", "Grep", "Glob"}
    if parse_error:
        if tool in readonly_tools:
            return ""
        return "框架维护授权格式无效：" + parse_error
    authorized = {
        str(path) for path in (contract.get("maintenance_authorized_paths") or [])
        if str(path).strip()
    }
    if not authorized:
        return "框架维护授权缺少 exact maintenance_authorized_paths；拒绝 fail-open。"
    if tool in readonly_tools:
        return ""
    if tool in {"CronCreate", "CronDelete", "CronList", "Agent", "WebFetch", "WebSearch"}:
        return "框架维护回合禁止 target/network action、Agent 与 Cron；本回合只做本地精确路径维护。"
    if tool != "Bash" and _is_target_action(event):
        return "框架维护回合禁止 target/network action、Agent 与 Cron；本回合只做本地精确路径维护。"
    if tool in maintenance_authority.WRITE_TOOLS:
        paths, invalid = maintenance_authority.event_paths(event)
        if invalid or not paths:
            return "框架维护写工具必须提供可规范化的 repository-local exact file path。"
        outside = sorted(set(paths) - authorized)
        if outside:
            return (
                "框架维护授权仅覆盖当前回合 exact paths；未授权: "
                + ", ".join(outside)
            )
        return ""
    if tool == "Bash":
        tool_env = tool_input.get("env") if isinstance(tool_input.get("env"), dict) else {}
        if tool_env:
            return (
                "框架维护 Bash 禁止工具级环境覆盖；PYTHONPATH/Git 外部 helper 等变量会"
                "破坏本地只读/验证命令的确定性。"
            )
        if _readonly_shell(command) or _local_verification_bash(command):
            return ""
        if _event_destinations(event):
            return "框架维护回合禁止 target/network action、Agent 与 Cron；本回合只做本地精确路径维护。"
        critical = maintenance_authority.critical_paths_for_event(event)
        if critical:
            return (
                "框架维护禁止用 Bash 直接改安全关键文件；请用 Edit/Write 且路径必须与授权完全一致: "
                + ", ".join(critical)
            )
        return "框架维护 Bash 仅允许只读命令或审计过的单一 selftest/check 命令；禁止目标动作和任意 shell 写入。"
    return f"框架维护回合不允许工具 {tool or '(unknown)'}；只允许读取、精确 Edit/Write 和本地验证。"


def _maintenance_event_paths(event: dict) -> list[str]:
    tool = str(event.get("tool_name") or "")
    if tool in maintenance_authority.WRITE_TOOLS:
        paths, _ = maintenance_authority.event_paths(event)
        return paths
    return maintenance_authority.critical_paths_for_event(event)


def _maintenance_receipt_paths(event: dict, contract: dict | None = None) -> list[str]:
    paths = list(_maintenance_event_paths(event))
    if contract and contract.get("mode") == MAINTENANCE:
        paths.extend(str(path) for path in (
            contract.get("maintenance_critical_paths") or []))
    return sorted({path for path in paths if path})


def _opaque_repo_mutation_bash(command: str) -> bool:
    """Treat every non-readonly Git/patch invocation as opaque repository mutation."""
    if _readonly_shell(command):
        return False
    try:
        tokens = shlex.split(command, posix=True)
    except ValueError:
        tokens = re.split(r"\s+", command.strip())
    for index, token in enumerate(tokens):
        name = Path(token.strip("'\"()[]{};,|&")).name.lower()
        if name == "patch":
            return True
        if name == "git":
            return True
    # Quoted `sh -c 'git ...'` is one argv token after outer parsing. Because
    # the complete outer command was not accepted by `_readonly_shell`, any
    # nested Git is mutation-capable and must fail closed.
    raw = command.replace("\\\n", " ")
    return bool(re.search(
        r"(?i)(?:^|[\s;&|('\"`])(?:[^\s;&|('\"`]+/)?git(?:\s|$)|"
        r"(?:^|[\s;&|('\"`])(?:[^\s;&|('\"`]+/)?patch(?:\s|$)",
        raw,
    ))


def _critical_maintenance_reason(event: dict) -> str:
    """Require the top-level maintenance entry before critical source writes."""
    tool = str(event.get("tool_name") or "")
    tool_input = event.get("tool_input") if isinstance(event.get("tool_input"), dict) else {}
    command = str(tool_input.get("command") or "")
    if tool not in maintenance_authority.WRITE_TOOLS | {"Bash"}:
        return ""
    if tool == "Bash" and _opaque_repo_mutation_bash(command):
        return (
            "普通 /loop 不授权使用不透明的仓库变更命令修改或暂存框架；"
            "先保留当前 diff/错误并停止 run 状态推进。需要操作者在新回合首条非空"
            "指令使用: " + maintenance_authority.required_directive([])
        )
    critical = maintenance_authority.critical_paths_for_event(event)
    if not critical:
        return ""
    tool_env = tool_input.get("env") if isinstance(tool_input.get("env"), dict) else {}
    if tool == "Bash" and (
            (not tool_env and _readonly_shell(command))
            or _trusted_critical_execution_bash(command, tool_env=tool_env)):
        return ""
    return (
        "普通 /loop 不授权修改安全关键框架路径；保留本次拒绝并停止 run 状态推进。"
        "需要操作者在新回合首条非空指令使用: "
        + maintenance_authority.required_directive(critical)
    )


def _is_maintenance_denial(reason: str) -> bool:
    return any(marker in reason for marker in (
        "框架维护", "maintenance_authorized_paths", "/xunji-maintenance",
    ))


def _maintenance_action(event: dict, *, contract: dict | None = None) -> bool:
    tool = str(event.get("tool_name") or "")
    if contract and contract.get("mode") == MAINTENANCE \
            and tool not in {"Read", "Grep", "Glob"}:
        return True
    if tool in maintenance_authority.WRITE_TOOLS:
        return bool(maintenance_authority.critical_paths_for_event(event))
    if tool == "Bash" and maintenance_authority.critical_paths_for_event(event):
        command = str((event.get("tool_input") or {}).get("command") or "") \
            if isinstance(event.get("tool_input"), dict) else ""
        return not (_readonly_shell(command) or _local_verification_bash(command))
    return False


def _record_maintenance_denial(
    run_dir: Path,
    event: dict,
    contract: dict,
    reason: str,
) -> None:
    """Keep a turn-scoped stop marker; raw/category text stays in receipts."""
    if not contract:
        return
    value = dict(contract)
    value["maintenance_blocked"] = {
        "updated_at": time.time(),
        "tool_name": str(event.get("tool_name") or ""),
        "paths": _maintenance_receipt_paths(event, contract),
        "reason_sha256": hashlib.sha256(
            reason.encode("utf-8", "replace")).hexdigest(),
    }
    _atomic_json(contract_path(run_dir), value)


def _safe_sed(tokens: list[str]) -> bool:
    scripts: list[str] = []
    index = 1
    while index < len(tokens):
        token = tokens[index]
        if token in {"-n", "--quiet", "--silent"}:
            index += 1
            continue
        if token in {"-e", "--expression"}:
            if index + 1 >= len(tokens):
                return False
            scripts.append(tokens[index + 1])
            index += 2
            continue
        if token.startswith("-"):
            return False
        if not scripts:
            scripts.append(token)
        index += 1
    return bool(scripts) and all(
        re.fullmatch(r"(?:\d+|\$)(?:,(?:\d+|\$))?p", script)
        for script in scripts
    )


def _safe_git_read(tokens: list[str]) -> bool:
    """Allow repository inspection but no index/worktree/ref mutation."""
    if len(tokens) < 2:
        return False
    if tokens[1] not in {
        "diff", "status", "show", "log", "rev-parse", "ls-files",
    }:
        return False
    if any(
        token in {"--ext-diff", "--textconv"}
        or token.startswith("--output")
        for token in tokens[2:]
    ):
        return False
    if tokens[1] in {"diff", "show", "log"}:
        return "--no-ext-diff" in tokens[2:] and "--no-textconv" in tokens[2:]
    return True


def _readonly_shell(command: str) -> bool:
    """Allow a narrow shell read grammar; unknown syntax remains write-capable."""
    if not command.strip() or re.search(r">|`|\$\(|\$\{|\n|\r", command):
        return False
    allowed = {
        "cat", "head", "tail", "grep", "rg", "ls", "stat", "file", "wc",
        "find", "sed", "git",
    }
    for segment in re.split(r"\s*(?:&&|\|\||;|\|)\s*", command):
        if not segment.strip():
            return False
        try:
            tokens = shlex.split(segment)
        except ValueError:
            return False
        if not tokens:
            return False
        executable = Path(tokens[0]).name
        if executable not in allowed:
            return False
        if executable == "sed" and not _safe_sed(tokens):
            return False
        if executable == "git" and not _safe_git_read(tokens):
            return False
        if executable == "find" and any(
            token in {
                "-delete", "-exec", "-execdir", "-ok", "-okdir",
                "-fprint", "-fprint0", "-fls", "-fprintf",
            }
            for token in tokens[1:]
        ):
            return False
    return True


def _control_invocation(command: str) -> tuple[Path, list[str]] | None:
    """Parse one exact in-repo Python control command."""
    invocation = parse_exact_python_command(
        command, root=ROOT, allowed_scripts=CONTROL_SCRIPTS
    )
    if invocation is None:
        return None
    return invocation.script, list(invocation.args)


def _fanout_control_bash(command: str, *, tool_env: dict | None = None) -> bool:
    if tool_env:
        return False
    if _readonly_shell(command) or _local_verification_bash(command):
        return True
    return _control_invocation(command) is not None


def _assignment_record(run_dir: Path, assignment: str, front: str = "") -> dict:
    try:
        data = json.loads((run_dir / "state" / "assignments.json").read_text(encoding="utf-8", errors="replace"))
    except Exception:
        return {}
    for item in data.get("assignments", []) if isinstance(data, dict) else []:
        if not isinstance(item, dict):
            continue
        if str(item.get("agent") or "") != assignment:
            continue
        if front and str(item.get("front") or "").upper() != front.upper():
            continue
        if not (run_dir / "agents" / f"{assignment}.md").exists():
            return {}
        return item
    return {}


def _assignment_exists(run_dir: Path, assignment: str, front: str) -> bool:
    return bool(_assignment_record(run_dir, assignment, front))


def _normalized_assets(values: object) -> list[str]:
    out: list[str] = []
    for raw in values if isinstance(values, list) else []:
        value = str(raw).strip().lower().rstrip(".")
        value = re.sub(r"^[a-z][a-z0-9+.\-]*://", "", value).split("/", 1)[0]
        if value and value not in out:
            out.append(value)
    return out


def _coverage_rows(run_dir: Path) -> tuple[list[dict], str]:
    coverage_paths = [run_dir / "coverage.json", *sorted(run_dir.glob("**/coverage.json"))]
    existing = [path for path in coverage_paths if path.exists()]
    if not existing:
        return [], ""
    try:
        import coverage_matrix  # noqa: WPS433
        data = coverage_matrix.derive(run_dir)
    except Exception as exc:
        return [], f"{exc.__class__.__name__}: coverage derivation failed"
    rows = [row for row in data.get("rows", []) if isinstance(row, dict)]
    if not rows:
        return [], "coverage file exists but no valid asset rows were derived"
    return rows, ""


def _event_known_hosts(run_dir: Path, event: dict) -> tuple[set[str], str]:
    text = _tool_text(event).lower()
    found: set[str] = set()
    rows, error = _coverage_rows(run_dir)
    if error:
        return set(), error
    for row in rows:
        host = _normalized_assets([row.get("asset")])
        if host and re.search(r"(?<![\w.\-])" + re.escape(host[0]) + r"(?![\w.\-])", text):
            found.add(host[0])
    return found, ""


def _coverage_hostnames(rows: list[dict]) -> set[str]:
    """Return host-only scope keys for URL/IP destination comparison."""
    hosts: set[str] = set()
    for row in rows:
        for asset in _normalized_assets([row.get("asset")]):
            try:
                host = urlsplit("//" + asset).hostname or ""
            except ValueError:
                host = ""
            host = host.strip().lower().rstrip(".")
            if host:
                hosts.add(host)
    return hosts


def _unapproved_scope_destinations(
    run_dir: Path, rows: list[dict], destinations: set[str],
) -> dict[str, list[str]]:
    """Return ledger-known destinations that are not admitted for target effects.

    ``legacy`` preserves old ledgers that predate an explicit scope-status field.
    New setup-source candidates deliberately use ``review`` and must remain
    non-executable until a hook-bound operator admission updates the ledger.
    Conflicting duplicate rows fail closed.
    """
    status_by_host: dict[str, set[str]] = {}
    candidate_receipt_errors: set[str] = set()
    for row in rows:
        status = str(row.get("scope_status") or "legacy").strip().lower()
        for asset in _normalized_assets([row.get("asset")]):
            try:
                host = urlsplit("//" + asset).hostname or ""
            except ValueError:
                host = ""
            host = host.strip().lower().rstrip(".")
            if host:
                status_by_host.setdefault(host, set()).add(status)
                if status == "in":
                    valid, _note = scope_admission.verify_admitted_host(
                        run_dir, rows, host,
                    )
                    if not valid:
                        candidate_receipt_errors.add(host)
    return {
        host: sorted(statuses | ({"invalid-admission-receipt"}
                                 if host in candidate_receipt_errors else set()))
        for host in sorted(destinations)
        if (statuses := status_by_host.get(host))
        and (statuses != {"in"} or host in candidate_receipt_errors)
        and statuses != {"legacy"}
    }


def _event_destinations(event: dict) -> set[str]:
    """Extract explicit network destinations without treating artifact paths as hosts."""
    text = _tool_text(event)
    destinations: set[str] = set()
    for raw_url in re.findall(r"(?i)\b(?:https?|wss?)://[^\s\"'<>]+", text):
        try:
            host = urlsplit(raw_url.rstrip(",);]}")).hostname or ""
        except ValueError:
            host = ""
        host = host.strip().lower().rstrip(".")
        if host:
            destinations.add(host)

    command = str((event.get("tool_input") or {}).get("command") or "") \
        if isinstance(event.get("tool_input"), dict) else ""
    try:
        tokens = shlex.split(command)
    except ValueError:
        tokens = []
    file_suffixes = {
        ".diff", ".gif", ".html", ".json", ".jsonl", ".log", ".md",
        ".png", ".py", ".replay", ".txt", ".yaml", ".yml",
    }
    bare_host = re.compile(
        r"(?i)^(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+"
        r"[a-z]{2,63}(?::\d+)?(?:/.*)?$"
    )
    for token in tokens:
        candidate = token.strip("[](),;\"'")
        if not candidate or "://" in candidate or "/" in candidate:
            continue
        host_candidate = candidate.rsplit(":", 1)[0] if candidate.count(":") == 1 else candidate
        try:
            destinations.add(str(ipaddress.ip_address(host_candidate)).lower())
            continue
        except ValueError:
            pass
        if Path(host_candidate).suffix.lower() in file_suffixes or not bare_host.fullmatch(candidate):
            continue
        try:
            host = urlsplit("//" + candidate).hostname or ""
        except ValueError:
            host = ""
        if host:
            destinations.add(host.lower().rstrip("."))
    return destinations


def _unassigned_assets(run_dir: Path) -> tuple[list[str], str]:
    try:
        import coverage_matrix  # noqa: WPS433
        data = coverage_matrix.derive(run_dir)
    except Exception as exc:
        return [], f"{exc.__class__.__name__}: coverage derivation failed"
    if any(run_dir.glob("**/coverage.json")) and not data.get("rows"):
        return [], "coverage file exists but no valid asset rows were derived"
    return ([str(item.get("asset") or "") for item in data.get("accounting_gaps", [])
             if str(item.get("asset") or "")], "")


def _proxy_egress_reason(run_dir: Path, event: dict) -> str:
    """Deny target egress paths that cannot prove use of the engagement proxy."""
    tool = str(event.get("tool_name") or "")
    tool_input = event.get("tool_input") if isinstance(event.get("tool_input"), dict) else {}
    command = str(tool_input.get("command") or "")
    if tool == "Bash" and RAW_NETWORK_CLIENT_RE.search(command):
        return (
            "交战代理硬门：active run 禁止使用裸 curl/wget/httpx/nuclei/sqlmap/requests/urllib/socket；"
            "请走项目的 proxy-aware guarded tools。"
        )
    touched, coverage_error = _event_known_hosts(run_dir, event)
    if coverage_error:
        return "资产覆盖硬门：无法派生目标资产账本，拒绝在未知 scope/代理状态下执行：" + coverage_error
    if tool == "WebFetch":
        return (
            "交战代理硬门：active run 中 WebFetch 无法证明经过 XUNJI_PROXY，且未知目标会"
            "绕过资产账本；目标请求必须改用 tools/probe.py/render.py/scan.py，公共资料研究"
            "使用 WebSearch/知识工具。"
        )
    if tool != "Bash":
        if touched or _event_destinations(event):
            return (
                "交战代理硬门：该非 Bash 网络工具无法证明经过 XUNJI_PROXY；"
                "目标请求必须改用 proxy-aware project tools。"
            )
        return ""
    try:
        tokens = shlex.split(command)
    except ValueError:
        return "交战代理硬门：无法解析目标命令，拒绝可能的直连出口。"
    approved = False
    for token in tokens:
        if not token.endswith(".py"):
            continue
        path = Path(token)
        if not path.is_absolute():
            path = ROOT / path
        try:
            approved = path.resolve() in PROXY_AWARE_TARGET_TOOLS
        except Exception:
            approved = False
        if approved:
            break
    if approved:
        rows, inventory_error = _coverage_rows(run_dir)
        if inventory_error:
            return "资产覆盖硬门：无法派生目标资产账本：" + inventory_error
        if not rows:
            return "资产覆盖硬门：proxy-aware 目标工具执行前必须先建立 coverage/asset ledger。"
        destinations = _event_destinations(event)
        unapproved = _unapproved_scope_destinations(run_dir, rows, destinations)
        if unapproved:
            detail = ", ".join(
                f"{host}={'/'.join(statuses)}"
                for host, statuses in unapproved.items()
            )
            return (
                "资产 scope 准入硬门：coverage ledger 中的 review/out/unknown 只是候选，"
                "不能由 source、AI、front 或工具输出提升为 operator authority；"
                "先取得当前操作者的零探测精确准入并由受控工具更新账本。待准入: "
                + detail
            )
        unknown = sorted(destinations - _coverage_hostnames(rows))
        if unknown:
            return (
                "资产覆盖硬门：proxy-aware 目标工具只能访问 coverage ledger 已声明的 host/IP；"
                "未知目标: " + ", ".join(unknown)
            )
    if not approved:
        if not touched:
            return ""
        return (
            "交战代理硬门：该目标命令未绑定项目的 proxy-aware 工具，无法证明出口代理；"
            "改用 tools/probe.py、render.py 或 scan.py。"
        )
    return ""


def _is_target_action(event: dict) -> bool:
    tool = str(event.get("tool_name") or "")
    tool_input = event.get("tool_input") if isinstance(event.get("tool_input"), dict) else {}
    command = str(tool_input.get("command") or "")
    tool_env = tool_input.get("env") if isinstance(tool_input.get("env"), dict) else {}
    if tool == "Bash" and _fanout_control_bash(command, tool_env=tool_env):
        return False
    # Every other Bash command remains target-capable. Do not let a future
    # NON_EGRESS_TOOLS entry silently weaken the fail-closed shell boundary.
    if tool == "WebFetch" or tool == "Bash":
        return True
    if tool in NON_EGRESS_TOOLS:
        return False
    return bool(_event_destinations(event))


def _denial_is_target_action(event: dict, reason: str) -> bool:
    """Separate target-result denials from local control-plane policy denials."""
    local_policy_markers = (
        "active-run 指针",
        "清除 active-run 指针必须由当前操作者 prompt 明确授权",
        "长期记忆写入需要操作者",
        "peer_review 不得后台运行",
        "setup transaction",
        "框架维护",
        "/xunji-maintenance",
    )
    return _is_target_action(event) and not any(
        marker in reason for marker in local_policy_markers)


def _setup_transaction_reason(run_dir: Path) -> str:
    """Block work while a published setup transaction is not committed."""
    path = run_dir / "state" / "setup_transaction.json"
    if not path.exists():
        return ""  # legacy run
    try:
        receipt = json.loads(path.read_text(encoding="utf-8", errors="strict"))
    except Exception:
        return "setup transaction receipt is unreadable; only read/recovery lifecycle actions are allowed."
    if not isinstance(receipt, dict) or receipt.get("schema") != "xunji.setup_transaction.v1":
        return "setup transaction receipt schema is invalid; only read/recovery lifecycle actions are allowed."
    status = str(receipt.get("status") or "")
    if status not in {"committed", "recovered"}:
        return (
            f"setup transaction is {status or 'unknown'}, not committed; "
            "only read/recovery lifecycle actions are allowed and CronCreate remains blocked."
        )
    return ""


def _scope_admission_invocation(
    invocation: tuple[Path, list[str]] | None,
) -> dict | None:
    if not invocation or invocation[0].name != "scope_admission.py":
        return None
    try:
        return scope_admission.parse_invocation(invocation[1])
    except scope_admission.ScopeAdmissionError:
        return None


def _scope_admission_pretool_reason(
    run_dir: Path, event: dict, contract: dict,
) -> str:
    """Make the admission turn local-only and bind one exact controlled write."""
    tool = str(event.get("tool_name") or "")
    tool_input = event.get("tool_input") if isinstance(event.get("tool_input"), dict) else {}
    command = str(tool_input.get("command") or "")
    tool_env = tool_input.get("env") if isinstance(tool_input.get("env"), dict) else {}
    parse_error = str(contract.get("scope_admission_parse_error") or "")
    if parse_error:
        if tool in {"Read", "Grep", "Glob"}:
            return ""
        return "资产 scope 准入授权格式无效：" + parse_error
    if not contract.get("scope_admission_run"):
        return ""
    if tool in {"Read", "Grep", "Glob"}:
        return ""
    invocation = _control_invocation(command) if tool == "Bash" and not tool_env else None
    parsed = _scope_admission_invocation(invocation)
    expected_assets = list(contract.get("scope_admission_assets") or [])
    if parsed and parsed.get("run_name") == run_dir.name \
            and parsed.get("run_name") == contract.get("scope_admission_run") \
            and parsed.get("assets") == expected_assets:
        return ""
    return (
        "资产 scope 准入回合是 zero-probe local transition：只允许读取和一次与当前"
        " operator 首行完全匹配的 scope_admission.py；禁止 target/network、Agent、Cron、"
        "其他控制面写入或资产集合扩张。"
    )


def evaluate_pretool(run_dir: Path, event: dict, contract: dict) -> str:
    tool = str(event.get("tool_name") or "")
    text = _tool_text(event)
    mode = str(contract.get("mode") or "")
    tool_input = event.get("tool_input") if isinstance(event.get("tool_input"), dict) else {}
    command = str(tool_input.get("command") or "")
    tool_env = tool_input.get("env") if isinstance(tool_input.get("env"), dict) else {}
    direct_env_opt_out = str(tool_env.get("XUNJI_PROXY_REQUIRED") or "").strip().lower() \
        in {"0", "false", "no", "off"}

    protected_reason = _protected_control_reason(event)
    if protected_reason:
        return protected_reason

    if mode == MAINTENANCE or contract.get("maintenance_parse_error"):
        return _maintenance_pretool_reason(event, contract)

    if contract.get("scope_admission_run") or contract.get("scope_admission_parse_error"):
        return _scope_admission_pretool_reason(run_dir, event, contract)

    critical_reason = _critical_maintenance_reason(event)
    if critical_reason:
        return critical_reason

    invocation = _control_invocation(command) if tool == "Bash" else None
    prompt_excerpt = str(contract.get("prompt_excerpt") or "")
    resume_allowed = False
    source_allowed = False
    if invocation and invocation[0].name == "loop_bootstrap.py" \
            and "--resume" in invocation[1]:
        try:
            resume_arg = invocation[1][invocation[1].index("--resume") + 1]
        except (ValueError, IndexError):
            resume_arg = ""
        resume_allowed = bool(
            re.search(r"(?:继续|恢复|续接|resume|continue)", prompt_excerpt, re.I)
            or (resume_arg and (
                resume_arg.lower() in prompt_excerpt.lower()
                or Path(resume_arg).name.lower() in prompt_excerpt.lower()
            )))
    if invocation and invocation[0].name == "loop_bootstrap.py" \
            and "--source" in invocation[1]:
        try:
            source_arg = invocation[1][invocation[1].index("--source") + 1]
        except (ValueError, IndexError):
            source_arg = ""
        # Unlike resume, first-source setup may create a new canonical run.  A
        # basename collision is therefore not authority for a different path.
        source_allowed = bool(
            source_arg and source_arg.lower() in prompt_excerpt.lower()
        )
        if "--ai" in invocation[1]:
            try:
                requested_ai = invocation[1][invocation[1].index("--ai") + 1]
            except (ValueError, IndexError):
                requested_ai = ""
            if requested_ai == "external" and not re.search(
                r"--ai(?:\s+|=)external(?:\s|$)", prompt_excerpt, re.I
            ):
                return "external normalizer 必须由当前操作者 prompt 显式写出 --ai external；source/模型不能自行开启模型出境。"
    if invocation and invocation[0].name in {"setup_run.py", "loop_bootstrap.py"} \
            and not ({"--selftest", "--help", "-h"} & set(invocation[1])) \
            and not RUN_TRANSITION_RE.search(prompt_excerpt) \
            and not resume_allowed and not source_allowed:
        return "setup/resume run 转换必须由当前操作者 prompt 明确要求；不得借切换 run 规避当前回合约束。"
    if invocation and invocation[0].name == "xunji_statusline.py" \
            and "--set-active" in invocation[1]:
        try:
            target_arg = invocation[1][invocation[1].index("--set-active") + 1]
        except (ValueError, IndexError):
            return "--set-active 缺少 run 路径。"
        target_name = Path(target_arg).name.lower()
        if target_name not in prompt_excerpt.lower() and target_arg.lower() not in prompt_excerpt.lower():
            return "--set-active 目标必须由当前操作者 prompt 明确点名；不得切换到无关 run。"
    if invocation and invocation[0].name == "xunji_statusline.py" \
            and "--clear-active" in invocation[1] \
            and not CLEAR_ACTIVE_RE.search(str(contract.get("prompt_excerpt") or "")):
        return "清除 active-run 指针必须由当前操作者 prompt 明确授权；切换 run 请使用受控 --set-active/setup/resume。"

    setup_transaction_reason = _setup_transaction_reason(run_dir)
    lifecycle_recovery = bool(invocation and invocation[0].name in {
        "setup_run.py", "loop_bootstrap.py", "xunji_statusline.py",
    })
    if setup_transaction_reason and tool not in {
            "Read", "Grep", "Glob", "CronList"} and not lifecycle_recovery:
        return setup_transaction_reason

    if MEMORY_PATH_RE.search(text) and not contract.get("memory_approved"):
        memory_read = tool in {"Read", "Grep", "Glob"} or (
            tool == "Bash" and not tool_env and _readonly_shell(command)
        )
        if not memory_read:
            return "长期记忆写入需要操作者在当前 prompt 明确批准；retrospective 不能自行升级为 memory。"
    if tool == "Bash" and BACKGROUND_REVIEW_RE.search(command):
        return "peer_review 不得后台运行并与可变 evidence 并发；请前台冻结快照后完成复审。"
    if tool == "Bash" and (DIRECT_EGRESS_ENV_RE.search(text) or direct_env_opt_out) \
            and not contract.get("direct_egress_approved"):
        return (
            "交战代理硬门：XUNJI_PROXY_REQUIRED=0 只能由当前操作者 prompt 明确批准直连；"
            "模型或历史环境变量不能自行关闭 fail-closed。"
        )

    if mode == EXPLAIN:
        if tool not in {"Read", "Grep", "Glob", "WebSearch", "ListMcpResourcesTool", "ReadMcpResourceTool"}:
            return "当前回合是 EXPLAIN_ONLY：只能读取/分析，禁止修改、探测、Agent、Cron 或执行命令。"
        return ""
    if mode == PAUSE:
        if tool not in {"Read", "Grep", "Glob", "CronList", "CronDelete"}:
            return "当前回合是 PAUSED_BY_OPERATOR：只允许读取状态并执行 CronList/CronDelete；不得继续目标动作或改写前沿。"
        if tool == "CronDelete":
            job = runtime_receipts._job_id(tool_input)
            ok, note = runtime_receipts.cron_delete_allowed(
                run_dir, job,
                session_id=str(contract.get("session_id") or ""),
                since=float(contract.get("updated_at") or 0.0),
            )
            if not ok:
                return "暂停事务只可删除当前 CronList 观察到的本 run job：" + note
        return ""
    if not contract:
        if tool not in {"Read", "Grep", "Glob", "WebSearch", "CronList", "CronDelete"}:
            return "缺少当前 session 的 turn contract；先由 UserPromptSubmit 记录 EXECUTE/EXPLAIN/PAUSE 模式。"
        return ""

    if tool == "CronCreate":
        if RUN_TRANSITION_RE.search(prompt_excerpt) \
                and str(contract.get("bound_run") or run_dir.name) == str(
                    contract.get("origin_run") or run_dir.name):
            return "Cron 单实例门：当前 prompt 要求创建新 run；先完成 setup 并切换 contract，再对新 run 执行 CronList/CronCreate。"
        cron_ok, cron_note = runtime_receipts.cron_quiescent(
            run_dir,
            session_id=str(contract.get("session_id") or ""),
            since=float(contract.get("updated_at") or 0.0),
        )
        if not cron_ok:
            return "Cron 单实例门：创建 /loop 前必须先 CronList 证明本 run 无现存任务。" + cron_note
        if run_dir.name.lower() not in text.lower():
            return "Cron 单实例门：CronCreate prompt 必须显式包含当前 run 目录名。"
        return ""

    if tool == "CronDelete":
        job = runtime_receipts._job_id(tool_input)
        ok, note = runtime_receipts.cron_delete_allowed(
            run_dir, job,
            session_id=str(contract.get("session_id") or ""),
            since=float(contract.get("updated_at") or 0.0),
        )
        if not ok:
            return "CronDelete 只可删除当前 CronList 观察到的本 run job：" + note
        return ""

    state, _ = _safe_run_summary(run_dir)
    frontier_exists = (run_dir / "frontier.md").exists()
    state_invalid = not frontier_exists or (
        not state.get("fronts") or bool(state.get("schema_errors"))
    )
    if state_invalid and (
        tool == "WebFetch" or (tool == "Bash" and not _fanout_control_bash(
            command, tool_env=tool_env))
    ):
        return (
            "canonical frontier 状态缺失或有 schema error；active run 按 fail-closed "
            "禁止目标动作，先修复 frontier.md 的 Status/Barrier class/Current depth。"
        )
    if _is_target_action(event):
        proxy_reason = _proxy_egress_reason(run_dir, event)
        if proxy_reason:
            return proxy_reason
        unassigned_assets, coverage_error = _unassigned_assets(run_dir)
        touched_hosts, host_error = _event_known_hosts(run_dir, event)
        if coverage_error or host_error:
            return "资产覆盖硬门：账本派生失败，拒绝 fail-open：" + (coverage_error or host_error)
        if touched_hosts and unassigned_assets:
            shown = ", ".join(unassigned_assets[:8])
            return (
                f"资产覆盖硬门：仍有 {len(unassigned_assets)} 个 reachable/unknown 范围内资产未映射到"
                f"任何 front/assignment（{shown}{' …' if len(unassigned_assets) > 8 else ''}）。"
                "先在 frontier.md 逐资产点名；宽泛 F-id 不能代替资产账本。"
            )
    if tool == "Bash" and not _audited_bash_execution(event):
        return (
            "普通 /loop 的 Bash 只能执行无环境覆盖的只读 grammar、受控 lifecycle/verification，"
            "或受信 target/review capability；未知 shell/interpreter 可能改写安全关键框架，"
            "按 fail-closed 拒绝。框架编辑必须由新回合 /xunji-maintenance exact-path 授权。"
        )
    actor_agent_id = str(event.get("agent_id") or "").strip()
    if actor_agent_id:
        if tool == "Agent":
            return "Agent Board 强制：只有 Root 可派 Agent；子 Agent 不得嵌套派生新 Agent。"
        actor = runtime_receipts.agent_actor(run_dir, actor_agent_id)
        if not actor:
            return "Agent Board 强制：当前子 Agent 没有 transcript-backed assignment attempt，拒绝执行。"
        if actor.get("state") != "running":
            return "Agent Board 强制：该子 Agent attempt 已返回，不能在 SubagentStop 后继续执行。"
        if actor.get("kind") == "completion_review":
            if tool in {"Read", "Grep", "Glob"} or (
                    tool == "Bash" and not tool_env and _readonly_shell(command)):
                return ""
            return "Completion review Agent 只允许读取冻结的 run 状态；不得修改、探测或再派 Agent。"
        rec = _assignment_record(
            run_dir, str(actor.get("assignment") or ""), str(actor.get("front") or ""))
        if not rec:
            return "Agent Board 强制：子 Agent attempt 对应的 assignment/front 已失效。"
        assigned_assets = set(_normalized_assets(rec.get("assets")))
        if _is_target_action(event) and not assigned_assets:
            return (
                "Agent Board 资产边界：legacy/空资产 assignment 不具备目标执行权限；"
                "Root 必须创建带显式 asset package 的新 assignment。"
            )
        if _is_target_action(event):
            touched, coverage_error = _event_known_hosts(run_dir, event)
            if coverage_error:
                return "Agent Board 资产边界：无法派生资产账本，拒绝 fail-open：" + coverage_error
            outside = sorted(touched - assigned_assets)
            if outside:
                return (
                    "Agent Board 资产边界：子 Agent 只能操作 assignment 的显式资产包；越界资产: "
                    + ", ".join(outside)
                )
        # Child Agents run their own assigned lane. Global Root fan-out and
        # post-return disposition must never block their probe/control actions.
        return ""
    if tool == "Agent":
        raw_input = event.get("tool_input") if isinstance(event.get("tool_input"), dict) else {}
        prompt = str(raw_input.get("prompt") or raw_input.get("description") or "")
        if "XUNJI_COMPLETION_REVIEW" in prompt.upper():
            missing = [item for item in COMPLETION_CHECKS if item not in prompt.lower()]
            if not runtime_receipts._evidence_hash(prompt) or missing:
                return (
                    "Completion Agent prompt 必须包含 EVIDENCE_INDEX=<current sha1> 和 "
                    "CHECKS=report_parity,severity_artifacts,reachable_frontier,review_ledger；缺少: "
                    + ", ".join(missing or ["EVIDENCE_INDEX"]))
            return ""
        assignment, front = runtime_receipts._assignment_fields(prompt)
        if not assignment or not front:
            return "Agent Board 强制：Agent prompt 必须包含 XUNJI_ASSIGNMENT=A-... 和 XUNJI_FRONT=F-...。"
        rec = _assignment_record(run_dir, assignment, front)
        if not rec:
            return "Agent Board 强制：Agent token 未绑定 workers.py 生成的 assignment/front。"
        status = str(rec.get("status") or "").strip().lower()
        if status not in {"assigned", "starting"}:
            return (
                f"Agent Board attempt 唯一性：{assignment} status={status or '(missing)'}，"
                "只有 assigned/starting assignment 可启动；重试或续派必须创建新 assignment。"
            )
        expected_assets = _normalized_assets(rec.get("assets"))
        prompt_assets = runtime_receipts._assignment_assets(prompt)
        if expected_assets and prompt_assets != expected_assets:
            return (
                "Agent Board 资产绑定：prompt 必须包含与 assignment 完全一致的 "
                f"XUNJI_ASSETS={','.join(expected_assets)}。"
            )
        return ""
    if not state.get("fanout_required") or contract.get("fanout_override"):
        return ""
    epoch_since = float(contract.get("fanout_epoch_started_at")
                        or contract.get("updated_at") or 0.0)
    fanout = runtime_receipts.agent_fanout(
        run_dir,
        since=epoch_since,
    )
    if fanout.get("satisfied"):
        if tool == "Bash" and _fanout_control_bash(command, tool_env=tool_env):
            return ""
        if tool == "WebFetch" or tool == "Bash":
            disposition = runtime_receipts.agent_disposition(
                run_dir,
                since=epoch_since,
            )
            if not disposition.get("disposition_satisfied"):
                pending = [str(item) for item in disposition.get("pending", []) if str(item).strip()]
                detail = ("；待处理：" + "；".join(pending[:4])) if pending else ""
                return (
                    "真实 SubagentStop 已返回但尚未完成 post-return disposition；先用 workers.py "
                    "把每个 assignment 更新为带 canonical E/F/D 锚点的 merged/blocked/failed，"
                    "且更新时间必须晚于 Agent 返回。" + detail
                )
        return ""
    if tool == "Bash":
        if not _fanout_control_bash(command, tool_env=tool_env):
            return (
                "Agent Board 强制：当前至少 4 个独立 active fronts"
                "（open/probing/working/type-A）；真实 Agent 回执覆盖两个不同 front 前，"
                "Root Bash 只允许只读命令和 workers/run_model/loop_state 控制面命令。"
            )
    if tool in {"WebFetch"}:
        return "Agent Board 强制：真实 Agent 回执覆盖两个不同 front 前，Root 不得继续目标 WebFetch。"
    return ""


def _context_message(contract: dict, run_dir: Path) -> str:
    mode = contract.get("mode")
    if contract.get("scope_admission_parse_error"):
        return (
            "[Xunji scope admission: INVALID] 未授予任何资产准入权限；"
            + str(contract.get("scope_admission_parse_error") or "")
        )
    if contract.get("scope_admission_run"):
        assets = ", ".join(str(item) for item in (
            contract.get("scope_admission_assets") or []))
        return (
            "[Xunji scope admission: ZERO_PROBE] 当前 operator 首行只授权 active run 的"
            f" exact assets: {assets}。调用受控 scope_admission.py 完成本地 receipt/ledger "
            "transition；本回合禁止 target/network、Agent、Cron，后续新 /loop 回合才可探测。"
        )
    if contract.get("maintenance_parse_error"):
        return (
            "[Xunji maintenance authority: INVALID] 未授予任何维护权限；"
            + str(contract.get("maintenance_parse_error") or "")
        )
    if mode == MAINTENANCE:
        paths = ", ".join(str(path) for path in (
            contract.get("maintenance_authorized_paths") or []))
        return (
            "[Xunji turn mode: MAINTENANCE] 仅可修改当前 operator prompt 绑定的 exact paths: "
            f"{paths}。禁止 target/network action、Agent、Cron 和 Bash 直接写文件；"
            "run_status/frontier/evidence 不得因本维护回合推进。本回合无需 live-run Coda。"
        )
    if mode == EXPLAIN:
        return "[Xunji turn mode: EXPLAIN_ONLY] 只回答操作者问题；可读文件，不修改、不探测、不派 Agent；本回合无需 Coda。"
    if mode == PAUSE:
        return "[Xunji turn mode: PAUSED_BY_OPERATOR] 保留所有 open fronts；先 CronList/CronDelete，禁止继续渗透；本回合无需 Coda，也不得写 completion marker。"
    state, _ = _safe_run_summary(run_dir)
    fanout = (
        " fanout_required=true (open/probing/working/type-A 均为 active); "
        "先真实调用至少两个不同 front 的 Agent。"
        if state.get("fanout_required") else ""
    )
    return "[Xunji turn mode: EXECUTE] 按 run 状态推进，最后写唯一具体 Coda。" + fanout


def handle_event(event: dict, run_dir: Path | None = None) -> dict | None:
    run_dir = run_dir or explicit_active_run()
    hook = str(event.get("hook_event_name") or "")
    if run_dir is None:
        if hook == "UserPromptSubmit" and not INTERNAL_PROMPT_RE.search(
                str(event.get("prompt") or "")):
            contract = write_pending_contract(event)
            if contract:
                if contract.get("mode") == MAINTENANCE \
                        or contract.get("maintenance_parse_error"):
                    context = _context_message(contract, ROOT)
                else:
                    context = (
                        "[Xunji bootstrap turn] 当前没有 active run；若操作者要求新建/"
                        "恢复 run，先执行受控 setup/resume。成功 set-active 会原子继承本回合契约。"
                    )
                return {
                    "hookSpecificOutput": {
                        "hookEventName": "UserPromptSubmit",
                        "additionalContext": context,
                    }
                }
        if hook == "PreToolUse":
            protected_reason = _protected_control_reason(event)
            if protected_reason:
                return _deny(protected_reason)
            tool = str(event.get("tool_name") or "")
            if tool == "CronCreate":
                return _deny("Xunji CronCreate 前必须先 setup/set-active 一个 run，再用当前回合 CronList 证明单实例。")
            pending = load_pending_contract(str(event.get("session_id") or ""))
            if pending and (
                    pending.get("mode") == MAINTENANCE
                    or pending.get("maintenance_parse_error")):
                reason = _maintenance_pretool_reason(event, pending)
                return _deny(reason) if reason else None
            command = str((event.get("tool_input") or {}).get("command") or "") \
                if isinstance(event.get("tool_input"), dict) else ""
            invocation = _control_invocation(command) if tool == "Bash" else None
            args = invocation[1] if invocation else []
            script_name = invocation[0].name if invocation else ""
            if script_name == "scope_admission.py":
                return _deny(
                    "scope admission requires the exact active run and a current hook-bound operator directive."
                )
            normalizer_prepare = bool(
                invocation
                and script_name == "loop_bootstrap.py"
                and "--prepare-normalizer" in args
            )
            inspection_only = bool(
                invocation
                and ({"--selftest", "--help", "-h"} & set(args)
                     or (script_name == "xunji_statusline.py"
                         and not ({"--set-active", "--clear-active"} & set(args))))
            )
            lifecycle = bool(invocation and (
                script_name in {"setup_run.py", "loop_bootstrap.py"}
                or (script_name == "xunji_statusline.py"
                    and bool({"--set-active", "--clear-active"} & set(args)))
            ) and not inspection_only)
            if inspection_only:
                return None
            if normalizer_prepare:
                if not pending:
                    return _deny(
                        "无 active run 的 external normalizer prepare 必须绑定当前 session 的"
                        " operator bootstrap contract；source 必须由当前 prompt 精确点名并显式写出"
                        " --ai external。")
                reason = evaluate_pretool(ROOT, event, pending)
                return _deny(reason) if reason else None
            if lifecycle:
                if not pending:
                    return _deny(
                        "无 active run 的 setup/resume/set-active 必须绑定当前 session 的"
                        " operator bootstrap contract；先由 UserPromptSubmit 明确新建/恢复目标。")
                reason = evaluate_pretool(ROOT, event, pending)
                if reason:
                    return _deny(reason)
                target_name = _lifecycle_target_name(invocation)
                if not target_name:
                    return _deny("无法从 lifecycle 命令确定唯一目标 run；拒绝创建 transition claim。")
                try:
                    write_transition_claim(target_name, pending)
                except Exception:
                    return _deny("无法原子写入当前 session/目标 run 的 transition claim。")
                return None
            if pending and tool not in {
                    "Read", "Grep", "Glob", "WebSearch", "ListMcpResourcesTool",
                    "ReadMcpResourceTool", "CronList"}:
                return _deny(
                    "当前 session 正在 bootstrap run；绑定 active run 前只允许只读动作和"
                    "受控 setup/resume/set-active，不得先执行目标或任意写操作。")
        return None
    if hook == "UserPromptSubmit":
        prompt = str(event.get("prompt") or "")
        if INTERNAL_PROMPT_RE.search(prompt):
            contract = load_contract(
                run_dir, session_id=str(event.get("session_id") or ""))
            if not contract:
                return None
            return {
                "hookSpecificOutput": {
                    "hookEventName": "UserPromptSubmit",
                    "additionalContext": _context_message(contract, run_dir),
                }
            }
        contract = write_contract(run_dir, event)
        return {
            "hookSpecificOutput": {
                "hookEventName": "UserPromptSubmit",
                "additionalContext": _context_message(contract, run_dir),
            }
        }
    if hook == "PreToolUse":
        session_id = str(event.get("session_id") or "")
        contract = load_contract(run_dir, session_id=session_id) if session_id else {}
        reason = evaluate_pretool(run_dir, event, contract)
        if reason:
            maintenance_action = _maintenance_action(event, contract=contract) \
                or _is_maintenance_denial(reason)
            receipt_event = dict(event)
            receipt_event.update({
                "hook_event_name": "PreToolUseDenied",
                "xunji_decision": "deny",
                "xunji_reason": reason,
                "xunji_target_action": _denial_is_target_action(event, reason),
                "xunji_maintenance_action": maintenance_action,
                "xunji_maintenance_paths": _maintenance_receipt_paths(event, contract)
                if maintenance_action else [],
            })
            runtime_receipts.append_hook_event(run_dir, receipt_event)
            if maintenance_action:
                _record_maintenance_denial(run_dir, event, contract, reason)
            return _deny(reason)
        command = str((event.get("tool_input") or {}).get("command") or "") \
            if isinstance(event.get("tool_input"), dict) else ""
        invocation = _control_invocation(command) \
            if str(event.get("tool_name") or "") == "Bash" else None
        if _scope_admission_invocation(invocation):
            try:
                scope_admission.write_hook_claim(run_dir, contract)
            except scope_admission.ScopeAdmissionError:
                return _deny(
                    "无法原子写入当前 session 的 exact scope admission claim；拒绝 fail-open。"
                )
        return None
    if hook in {"PostToolUse", "PostToolUseFailure", "SubagentStart", "SubagentStop"}:
        tool_name = str(event.get("tool_name") or "")
        command = str((event.get("tool_input") or {}).get("command") or "") \
            if isinstance(event.get("tool_input"), dict) else ""
        target_action = _is_target_action(event)
        session_id = str(event.get("session_id") or "")
        contract = load_contract(run_dir, session_id=session_id) if session_id else {}
        maintenance_action = _maintenance_action(event, contract=contract)
        invocation = _control_invocation(command) if tool_name == "Bash" else None
        scope_admission_action = bool(_scope_admission_invocation(invocation))
        if hook in {"SubagentStart", "SubagentStop"} or tool_name in {
            "Agent", "CronCreate", "CronDelete", "CronList",
        } or (tool_name == "Bash" and "peer_review.py" in command) \
                or target_action or maintenance_action or scope_admission_action:
            receipt_event = dict(event)
            receipt_event["xunji_target_action"] = target_action
            receipt_event["xunji_maintenance_action"] = maintenance_action
            receipt_event["xunji_scope_admission_action"] = scope_admission_action
            receipt_event["xunji_maintenance_paths"] = (
                _maintenance_receipt_paths(event, contract) if maintenance_action else [])
            runtime_receipts.append_hook_event(run_dir, receipt_event)
        return None
    return None


def _selftest() -> int:
    import subprocess
    from unittest import mock

    root = Path(tempfile.mkdtemp())
    run = root / "run"
    (run / "state").mkdir(parents=True)
    (run / "agents").mkdir()
    front_specs = (
        ("app", "example.test public app"),
        ("auth", "auth.example.test login"),
        ("network", "network review"),
        ("none", "workflow review"),
    )
    (run / "frontier.md").write_text(
        "# Frontier\n## Open Fronts\n" + "".join(
            f"### F-{idx:03d}\n- Front: {label}\n- Status: open\n"
            f"- Barrier class: {barrier}\n- Current depth: shallow\n"
            for idx, (barrier, label) in enumerate(front_specs, 1)
        ), encoding="utf-8")
    (run / "coverage.json").write_text(json.dumps({"assets": [
        {"host": "example.test", "reachable": True, "examined": False},
        {"host": "auth.example.test", "reachable": True, "examined": False},
    ]}), encoding="utf-8")
    (run / "agents" / "A-web-001.md").write_text("# Agent\n", encoding="utf-8")
    (run / "agents" / "A-auth-001.md").write_text("# Agent\n", encoding="utf-8")
    (run / "state" / "assignments.json").write_text(json.dumps({"assignments": [
        {"agent": "A-web-001", "front": "F-001", "status": "assigned",
         "assets": ["example.test"]},
        {"agent": "A-auth-001", "front": "F-002", "status": "assigned",
         "assets": ["auth.example.test"]},
    ]}), encoding="utf-8")
    explain = classify_prompt("为什么不用 Agent？只告诉我原因，不用修改")
    history_only = classify_prompt("这是这几次的历史，你来看看还有什么问题")
    ambiguous = classify_prompt("这是最新状态")
    pause = classify_prompt("停止loop，渗透结束")
    execute = classify_prompt("彻底修复所有问题")
    indirect_english = classify_prompt("Please deploy the prepared workflow")
    no_run_question = classify_prompt("what runs exist?", active_run=False)
    active_run_question = classify_prompt("active run 是什么？")
    active_run_switch = classify_prompt("switch active run to runs/other_20260101")
    negated_direct_cn = _contract_from_event({"prompt": "不要允许直连，继续使用代理"})
    negated_direct_en = _contract_from_event({"prompt": "do not allow direct egress"})
    explicit_direct = _contract_from_event({"prompt": "明确允许本回合直连"})
    scope_prompt = (
        "/xunji-scope-admit --run runs/pilot_20260715 "
        "--assets one.example.test,two.example.test --reason operator-confirmed-scope"
    )
    scope_contract = _contract_from_event({
        "prompt": scope_prompt, "session_id": "scope-session",
    })
    malformed_scope_contract = _contract_from_event({
        "prompt": "/xunji-scope-admit --run runs/pilot_20260715 --assets '*' --reason bad",
        "session_id": "scope-session",
    })
    contract = {
        "mode": EXECUTE,
        "session_id": "s",
        "prompt_excerpt": "/loop 重新开一个新 run",
        "origin_run": run.name,
        "bound_run": run.name,
        "updated_at": time.time(),
    }
    target_event = {"tool_name": "Bash", "tool_input": {"command": "python tools/probe.py https://example.test"}}
    scope_turn_target_blocked = "zero-probe local transition" in evaluate_pretool(
        run, target_event, scope_contract)
    malformed_scope_write_blocked = bool(evaluate_pretool(
        run, {"tool_name": "Write", "tool_input": {"file_path": str(run / "frontier.md")}},
        malformed_scope_contract,
    ))
    with mock.patch.object(run_model, "summary", side_effect=RuntimeError("broken state")):
        summary_failure_signature = _coordination_signature(run)
        summary_failure_reason = evaluate_pretool(run, target_event, contract)
    encoded_target = {"tool_name": "Bash", "tool_input": {
        "command": "python3 -c 'import socket; socket.create_connection((\"example.test\",443))'"}}
    renamed_target = {"tool_name": "Bash", "tool_input": {"command": "python3 /tmp/check.py"}}
    workers_control = {"tool_name": "Bash", "tool_input": {
        "command": f"python3 {ROOT / 'tools' / 'workers.py'} list {run}"}}
    workers_asset_control = {"tool_name": "Bash", "tool_input": {
        "command": (
            f"python3 {ROOT / 'tools' / 'workers.py'} assign {run} "
            "--role web-hunter --front F-001 --asset example.test"
        )}}
    workers_quoted_note_control = {"tool_name": "Bash", "tool_input": {
        "command": (
            f"python3 {ROOT / 'tools' / 'workers.py'} finish {run} A-web-001 "
            '--status blocked --note "Reason: shared barrier; Front: F-001"'
        )}}
    workers_quoted_punctuation_control = {"tool_name": "Bash", "tool_input": {
        "command": (
            f"python3 {ROOT / 'tools' / 'workers.py'} finish {run} A-web-001 "
            '--status blocked --note "Reason: auth; pipe | amp & gt > lt <; Front: F-001"'
        )}}
    workers_single_quoted_literal_control = {"tool_name": "Bash", "tool_input": {
        "command": (
            f"python3 {ROOT / 'tools' / 'workers.py'} finish {run} A-web-001 "
            "--status blocked --note 'Reason: literal $(id) ${HOME} `id`; Front: F-001'"
        )}}
    workers_escaped_substitution_literal = {"tool_name": "Bash", "tool_input": {
        "command": (
            f"python3 {ROOT / 'tools' / 'workers.py'} finish {run} A-web-001 "
            '--status blocked --note "Reason: literal \\$(id); Front: F-001"'
        )}}
    workers_ansi_c_literal_control = {"tool_name": "Bash", "tool_input": {
        "command": (
            f"python3 {ROOT / 'tools' / 'workers.py'} finish {run} A-web-001 "
            "--status blocked --note $'Reason: literal $(id); Front: F-001'"
        )}}
    workers_trailing_comment_control = {"tool_name": "Bash", "tool_input": {
        "command": f"python3 {ROOT / 'tools' / 'workers.py'} list {run} # ignored"}}
    workers_shell_chain = (
        f"python3 {ROOT / 'tools' / 'workers.py'} list {run}; echo unsafe")
    adversarial_control_commands = [
        f"python3 {ROOT / 'tools' / 'workers.py'} list {run} | cat",
        f"python3 {ROOT / 'tools' / 'workers.py'} list {run} && echo unsafe",
        f"python3 {ROOT / 'tools' / 'workers.py'} list {run} > /tmp/forged",
        f"python3 {ROOT / 'tools' / 'workers.py'} list {run} 2>&1",
        (f"python3 {ROOT / 'tools' / 'workers.py'} finish {run} A-web-001 "
         '--status blocked --note "Reason: $(id); Front: F-001"'),
        (f"python3 {ROOT / 'tools' / 'workers.py'} finish {run} A-web-001 "
         '--status blocked --note "Reason: ${HOME}; Front: F-001"'),
        (f"python3 {ROOT / 'tools' / 'workers.py'} finish {run} A-web-001 "
         '--status blocked --note "Reason: `id`; Front: F-001"'),
        (f"python3 {ROOT / 'tools' / 'workers.py'} finish {run} A-web-001 "
         '--status blocked --note "Reason: \\\\$(id); Front: F-001"'),
        (f"python3 {ROOT / 'tools' / 'workers.py'} finish {run} A-web-001 "
         "--status blocked --note <(id)"),
        (f"python3 {ROOT / 'tools' / 'workers.py'} finish {run} A-web-001 "
         "--status blocked --note >(id)"),
        f"python3 {ROOT / 'tools' / 'workers.py'} list {run} # ignored $(id)",
        f"python3 {ROOT / 'tools' / 'workers.py'} list '{run}",
        f"python3 {ROOT / 'tools' / 'workers.py'} list {run} \\",
    ]
    setup_control = {"tool_name": "Bash", "tool_input": {
        "command": f"python3 {ROOT / 'tools' / 'setup_run.py'} next {root / 'recon.json'}"}}
    source_url = "https://new-source.example/path?key=opaque"
    source_control = {"tool_name": "Bash", "tool_input": {
        "command": (
            f"python3 {ROOT / 'tools' / 'loop_bootstrap.py'} "
            f"--source '{source_url}' --type auto"
        )}}
    journal_control = {"tool_name": "Bash", "tool_input": {
        "command": f"python3 {ROOT / 'tools' / 'loop_journal.py'} {run} start --note begin"}}
    clear_active = {"tool_name": "Bash", "tool_input": {
        "command": f"python3 {ROOT / 'tools' / 'xunji_statusline.py'} --clear-active"}}
    set_active = {"tool_name": "Bash", "tool_input": {
        "command": f"python3 {ROOT / 'tools' / 'xunji_statusline.py'} --set-active runs/other_20260101"}}
    resume_control = {"tool_name": "Bash", "tool_input": {
        "command": f"python3 {ROOT / 'tools' / 'loop_bootstrap.py'} --resume runs/other_20260101"}}
    prepared_receipt_path = run / "state" / "setup_transaction.json"
    prepared_receipt_path.write_text(json.dumps({
        "schema": "xunji.setup_transaction.v1",
        "transaction_id": "a" * 32,
        "source_sha256": "b" * 64,
        "status": "prepared_not_active",
    }), encoding="utf-8")
    prepared_target_blocked = "setup transaction" in evaluate_pretool(
        run, target_event, contract)
    prepared_cron_blocked = "setup transaction" in evaluate_pretool(
        run, {"tool_name": "CronCreate", "tool_input": {
            "prompt": f"/loop {run.name}"}}, contract)
    prepared_read_allowed = evaluate_pretool(
        run, {"tool_name": "Read", "tool_input": {
            "file_path": str(prepared_receipt_path)}}, contract) == ""
    prepared_recovery_event = {"tool_name": "Bash", "tool_input": {
        "command": f"python3 {ROOT / 'tools' / 'loop_bootstrap.py'} --resume {run}"}}
    prepared_recovery_contract = {
        **contract,
        "prompt_excerpt": f"resume run {run}",
    }
    prepared_recovery_allowed = evaluate_pretool(
        run, prepared_recovery_event, prepared_recovery_contract) == ""
    prepared_receipt_path.unlink()
    fake_workers_control = {"tool_name": "Bash", "tool_input": {
        "command": "python3 /tmp/workers.py list runs/x"}}
    safe_sed_read = {"tool_name": "Bash", "tool_input": {
        "command": "sed -n '1,10p' frontier.md"}}
    sed_in_place = {"tool_name": "Bash", "tool_input": {
        "command": "sed -n -i '1,10p' frontier.md"}}
    sed_write_command = {"tool_name": "Bash", "tool_input": {
        "command": "sed -n 'w /tmp/forged' frontier.md"}}
    find_file_output = {"tool_name": "Bash", "tool_input": {
        "command": "find . -type f -fprint /tmp/forged"}}
    agent_bad = {"tool_name": "Agent", "tool_input": {"prompt": "work F-001"}}
    agent_good = {"tool_name": "Agent", "tool_input": {
        "prompt": "XUNJI_ASSIGNMENT=A-web-001 XUNJI_FRONT=F-001 XUNJI_ASSETS=example.test",
    }}
    completion_bad = {"tool_name": "Agent", "tool_input": {
        "prompt": "XUNJI_COMPLETION_REVIEW EVIDENCE_INDEX=" + "a" * 40,
    }}
    completion_good = {"tool_name": "Agent", "tool_input": {
        "prompt": "XUNJI_COMPLETION_REVIEW EVIDENCE_INDEX=" + "a" * 40
                  + " CHECKS=report_parity,severity_artifacts,reachable_frontier,review_ledger",
    }}
    agent_bad_blocked = "必须包含" in evaluate_pretool(run, agent_bad, contract)
    agent_good_allowed = evaluate_pretool(run, agent_good, contract) == ""
    before_fanout = "真实 Agent 回执" in evaluate_pretool(run, target_event, contract)
    encoded_before_fanout = bool(evaluate_pretool(run, encoded_target, contract))
    renamed_before_fanout = bool(evaluate_pretool(run, renamed_target, contract))
    workers_allowed_before_fanout = not bool(evaluate_pretool(run, workers_control, contract))
    workers_asset_control_allowed = (
        evaluate_pretool(run, workers_asset_control, contract) == ""
        and not _is_target_action(workers_asset_control))
    workers_quoted_note_allowed = (
        evaluate_pretool(run, workers_quoted_note_control, contract) == ""
        and _control_invocation(workers_quoted_note_control["tool_input"]["command"]) is not None)
    quoted_punctuation_allowed = (
        evaluate_pretool(run, workers_quoted_punctuation_control, contract) == ""
        and _control_invocation(
            workers_quoted_punctuation_control["tool_input"]["command"]) is not None)
    single_quoted_literals_allowed = (
        evaluate_pretool(run, workers_single_quoted_literal_control, contract) == ""
        and _control_invocation(
            workers_single_quoted_literal_control["tool_input"]["command"]) is not None)
    escaped_substitution_literal_allowed = (
        evaluate_pretool(run, workers_escaped_substitution_literal, contract) == ""
        and _control_invocation(
            workers_escaped_substitution_literal["tool_input"]["command"]) is not None)
    ansi_c_literal_rejected = (
        _control_invocation(
            workers_ansi_c_literal_control["tool_input"]["command"]) is None)
    trailing_comment_control_rejected = (
        _control_invocation(
            workers_trailing_comment_control["tool_input"]["command"]) is None)
    workers_shell_chain_rejected = _control_invocation(workers_shell_chain) is None
    adversarial_controls_fail_closed = all(
        _control_invocation(command) is None
        and bool(evaluate_pretool(
            run, {"tool_name": "Bash", "tool_input": {"command": command}}, contract))
        for command in adversarial_control_commands)
    bare_python_control_allowed = _control_invocation(
        f"python {ROOT / 'tools' / 'loop_state.py'} {run}") is not None
    micro_python_control_allowed = _control_invocation(
        f"python3.14.2 {ROOT / 'tools' / 'loop_state.py'} {run}") is not None
    setup_allowed_before_fanout = not bool(evaluate_pretool(run, setup_control, contract))
    source_setup_allowed = not bool(evaluate_pretool(run, source_control, {
        **contract, "prompt_excerpt": f"/loop {source_url}",
    }))
    unrelated_source_setup_blocked = bool(evaluate_pretool(run, source_control, {
        **contract, "prompt_excerpt": "/loop https://unrelated.example/",
    }))
    basename_collision_source_blocked = bool(evaluate_pretool(run, source_control, {
        **contract, "prompt_excerpt": "/loop /tmp/path?key=opaque",
    }))
    setup_without_operator_blocked = bool(evaluate_pretool(run, setup_control, {
        **contract, "prompt_excerpt": "继续当前 run 的 F-001",
    }))
    journal_allowed_before_fanout = not bool(evaluate_pretool(run, journal_control, contract))
    clear_without_operator_blocked = bool(evaluate_pretool(run, clear_active, contract))
    clear_with_operator_allowed = not bool(evaluate_pretool(run, clear_active, {
        **contract, "prompt_excerpt": "清除 active run 指针",
    }))
    clear_with_english_operator_allowed = not bool(evaluate_pretool(run, clear_active, {
        **contract, "prompt_excerpt": "clear the active run pointer",
    }))
    unrelated_set_active_blocked = bool(evaluate_pretool(run, set_active, contract))
    named_set_active_allowed = not bool(evaluate_pretool(run, set_active, {
        **contract, "prompt_excerpt": "/loop runs/other_20260101",
    }))
    named_resume_allowed = not bool(evaluate_pretool(run, resume_control, {
        **contract, "prompt_excerpt": "/loop runs/other_20260101",
    }))
    classify_setup_target = _lifecycle_target_name((
        ROOT / "tools" / "setup_run.py",
        ["--classify", "classified", str(root / "recon.json"), "--date", "20260101"],
    ))
    url_setup_target = _lifecycle_target_name((
        ROOT / "tools" / "setup_run.py",
        ["url-target", "--target", "https://example.test:8443", "--date", "20260101"],
    ))
    routed_url_target = _lifecycle_target_name((
        ROOT / "tools" / "loop_bootstrap.py",
        ["--source", source_url, "--type", "auto"],
    ))
    unknown_option_target = _lifecycle_target_name((
        ROOT / "tools" / "setup_run.py",
        ["--future-option", "wrong-slug", "real-slug", "--date", "20260101"],
    ))
    direct_resume_target = _lifecycle_target_name((
        ROOT / "tools" / "loop_bootstrap.py",
        ["--resume", "runs/resume_20260101"],
    ))
    direct_set_active_target = _lifecycle_target_name((
        ROOT / "tools" / "xunji_statusline.py",
        ["--set-active", "runs/selected_20260101"],
    ))
    fake_workers_blocked_before_fanout = bool(evaluate_pretool(
        run, fake_workers_control, contract))
    safe_sed_allowed_before_fanout = not bool(evaluate_pretool(
        run, safe_sed_read, contract))
    sed_in_place_blocked = bool(evaluate_pretool(run, sed_in_place, contract))
    sed_write_blocked = bool(evaluate_pretool(run, sed_write_command, contract))
    find_file_output_blocked = bool(evaluate_pretool(run, find_file_output, contract))
    protected_write = {
        "tool_name": "Bash",
        "tool_input": {"command": "printf forged > state/runtime_events.jsonl"},
    }
    protected_reason = evaluate_pretool(run, protected_write, contract)
    protected_denial_not_target = not _denial_is_target_action(
        protected_write, protected_reason)
    pointer_write = {
        "tool_name": "Write",
        "tool_input": {"file_path": str(ROOT / ".claude" / "xunji_active_run"),
                       "content": "runs/other\n"},
    }
    pointer_shell = {
        "tool_name": "Bash",
        "tool_input": {"command": "rm .claude/xunji_active_run"},
    }
    pointer_write_blocked = bool(evaluate_pretool(run, pointer_write, contract))
    coverage_write = {
        "tool_name": "Write",
        "tool_input": {"file_path": str(run / "coverage.json"), "content": "{}"},
    }
    coverage_write_blocked = "资产账本" in evaluate_pretool(
        run, coverage_write, contract)
    coverage_sync_control = {
        "tool_name": "Bash",
        "tool_input": {"command": (
            f"python3 {ROOT / 'tools' / 'coverage_matrix.py'} {run} --sync"
        )},
    }
    coverage_sync_control_allowed = evaluate_pretool(
        run, coverage_sync_control, contract) == ""
    pointer_shell_reason = evaluate_pretool(run, pointer_shell, contract)
    pointer_shell_is_local = not _denial_is_target_action(pointer_shell, pointer_shell_reason)
    transcript = root / "transcript.jsonl"
    transcript.write_text("old-agent-1\nold-agent-2\ncurrent-agent-1\ncurrent-agent-2\ncurrent-cron-list\n",
                          encoding="utf-8")

    def receipt(tool_id: str, session: str, assignment: str, front: str,
                assets: str) -> None:
        runtime_receipts.append_hook_event(run, {
            "hook_event_name": "PostToolUse", "session_id": session,
            "transcript_path": str(transcript), "tool_name": "Agent",
            "tool_use_id": tool_id,
            "tool_input": {"prompt": (
                f"XUNJI_ASSIGNMENT={assignment} XUNJI_FRONT={front} XUNJI_ASSETS={assets}"
            )},
            "tool_response": {"result": "done"},
        })

    receipt("old-agent-1", "old-session", "A-web-001", "F-001", "example.test")
    receipt("old-agent-2", "old-session", "A-auth-001", "F-002", "auth.example.test")
    old_fanout_still_blocked = bool(evaluate_pretool(run, target_event, contract))
    receipt("current-agent-1", "s", "A-web-001", "F-001", "example.test")
    receipt("current-agent-2", "s", "A-auth-001", "F-002", "auth.example.test")
    receipts_without_disposition_block = bool(evaluate_pretool(run, target_event, contract))
    (run / "evidence.md").write_text("# Evidence\n## E-001 - merged candidate\n", encoding="utf-8")
    assignment_state = json.loads((run / "state" / "assignments.json").read_text(encoding="utf-8"))
    for item in assignment_state["assignments"]:
        item.update({
            "status": "merged",
            "updated_at": datetime.now(timezone.utc).isoformat(),
            "last_note": f"Evidence: E-001 merged for Front: {item['front']}",
            "coverage_merge_satisfied": True,
        })
    (run / "state" / "assignments.json").write_text(
        json.dumps(assignment_state), encoding="utf-8")
    current_fanout_allows = evaluate_pretool(run, target_event, contract) == ""
    missing_contract_blocks = bool(evaluate_pretool(run, target_event, {}))
    original_frontier = (run / "frontier.md").read_text(encoding="utf-8")
    (run / "frontier.md").write_text("# Frontier\n## Open Fronts\nmalformed\n", encoding="utf-8")
    malformed_frontier_blocks = "canonical frontier" in evaluate_pretool(
        run, target_event, contract)
    (run / "frontier.md").write_text(original_frontier, encoding="utf-8")
    (run / "frontier.md").unlink()
    missing_frontier_blocks = "canonical frontier" in evaluate_pretool(
        run, target_event, contract)
    (run / "frontier.md").write_text(original_frontier, encoding="utf-8")
    cron_create = {"tool_name": "CronCreate", "tool_input": {"prompt": f"/loop {run.name}"}}
    cron_contract = {**contract, "prompt_excerpt": f"/loop {run.name}"}
    cron_before_list = bool(evaluate_pretool(run, cron_create, cron_contract))
    runtime_receipts.append_hook_event(run, {
        "hook_event_name": "PostToolUse", "session_id": "s",
        "transcript_path": str(transcript), "tool_name": "CronList",
        "tool_use_id": "current-cron-list", "tool_input": {},
        "tool_response": {"tasks": []},
    })
    cron_after_list = evaluate_pretool(run, cron_create, cron_contract) == ""
    new_run_cron_blocked_until_transition = "先完成 setup" in evaluate_pretool(
        run, cron_create, contract)
    empty_runs = root / "empty-runs"
    empty_runs.mkdir()
    env = dict(os.environ)
    env["XUNJI_RUNS_ROOT"] = str(empty_runs)
    pending_dir = root / "xunji_pending_turns"
    claims_dir = root / "xunji_transition_claims"
    env["XUNJI_PENDING_TURN_DIR"] = str(pending_dir)
    env["XUNJI_TRANSITION_CLAIMS_DIR"] = str(claims_dir)
    no_run_prompt = subprocess.run(
        [sys.executable, str(Path(__file__).resolve())],
        input=json.dumps({
            "hook_event_name": "UserPromptSubmit", "session_id": "s-bootstrap",
            "prompt": "/loop 重新开一个新 run",
        }),
        text=True, capture_output=True, env=env, timeout=10,
    )
    pending_written = (
        no_run_prompt.returncode == 0
        and "Xunji bootstrap turn" in (no_run_prompt.stdout or "")
        and any(pending_dir.glob("*.json"))
    )
    normalizer_source = root / "operator-normalizer.md"
    normalizer_source.write_text(
        "- Target: https://normalizer.example.test/\n", encoding="utf-8")
    prepare_pending_dir = root / "normalizer-pending"
    prepare_claims_dir = root / "normalizer-claims"
    prepare_env = dict(env)
    prepare_env["XUNJI_PENDING_TURN_DIR"] = str(prepare_pending_dir)
    prepare_env["XUNJI_TRANSITION_CLAIMS_DIR"] = str(prepare_claims_dir)
    normalizer_prepare_command = (
        f"python3 {shlex.quote(str(ROOT / 'tools' / 'loop_bootstrap.py'))} "
        f"--source {shlex.quote(str(normalizer_source))} --type file "
        "--ai external --ai-provider fixture-provider --ai-model fixture-model "
        "--prepare-normalizer"
    )

    def no_run_hook(event: dict, *, hook_env: dict[str, str] = prepare_env) \
            -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [sys.executable, str(Path(__file__).resolve())],
            input=json.dumps(event), text=True, capture_output=True,
            env=hook_env, timeout=10,
        )

    unbound_prepare = no_run_hook({
        "hook_event_name": "PreToolUse", "session_id": "prepare-unbound",
        "tool_name": "Bash", "tool_input": {"command": normalizer_prepare_command},
    })
    unbound_normalizer_prepare_blocked = (
        '"permissionDecision": "deny"' in (unbound_prepare.stdout or "")
        and "operator bootstrap contract" in (unbound_prepare.stdout or "")
    )
    no_external_submit = no_run_hook({
        "hook_event_name": "UserPromptSubmit", "session_id": "prepare-no-external",
        "prompt": f"/loop {normalizer_source}",
    })
    no_external_prepare = no_run_hook({
        "hook_event_name": "PreToolUse", "session_id": "prepare-no-external",
        "tool_name": "Bash", "tool_input": {"command": normalizer_prepare_command},
    })
    implicit_external_prepare_blocked = (
        no_external_submit.returncode == 0
        and '"permissionDecision": "deny"' in (no_external_prepare.stdout or "")
        and "--ai external" in (no_external_prepare.stdout or "")
    )
    explicit_external_submit = no_run_hook({
        "hook_event_name": "UserPromptSubmit", "session_id": "prepare-external",
        "prompt": f"/loop {normalizer_source} --ai external",
    })
    claims_before_prepare = list(prepare_claims_dir.glob("*.json")) \
        if prepare_claims_dir.exists() else []
    explicit_external_prepare = no_run_hook({
        "hook_event_name": "PreToolUse", "session_id": "prepare-external",
        "tool_name": "Bash", "tool_input": {"command": normalizer_prepare_command},
    })
    claims_after_prepare = list(prepare_claims_dir.glob("*.json")) \
        if prepare_claims_dir.exists() else []
    explicit_external_prepare_allowed_without_claim = (
        explicit_external_submit.returncode == 0
        and not (explicit_external_prepare.stdout or "").strip()
        and claims_before_prepare == claims_after_prepare == []
    )
    no_run_setup = subprocess.run(
        [sys.executable, str(Path(__file__).resolve())],
        input=json.dumps({
            "hook_event_name": "PreToolUse", "session_id": "s-bootstrap",
            "tool_name": "Bash", "tool_input": {
                "command": f"python3 {ROOT / 'tools' / 'setup_run.py'} bootstrap {root / 'recon.json'} --date 20260101"},
        }),
        text=True, capture_output=True, env=env, timeout=10,
    )
    pending_setup_allowed = (
        no_run_setup.returncode == 0 and not (no_run_setup.stdout or "").strip()
        and any(claims_dir.glob("*.json")))
    no_run_probe = subprocess.run(
        [sys.executable, str(Path(__file__).resolve())],
        input=json.dumps({
            "hook_event_name": "PreToolUse", "session_id": "s-bootstrap",
            "tool_name": "Bash", "tool_input": {
                "command": "python3 tools/probe.py https://example.test"},
        }),
        text=True, capture_output=True, env=env, timeout=10,
    )
    pending_target_action_blocked = (
        '"permissionDecision": "deny"' in (no_run_probe.stdout or "")
        and "bootstrap run" in (no_run_probe.stdout or ""))
    no_run_write = subprocess.run(
        [sys.executable, str(Path(__file__).resolve())],
        input=json.dumps({
            "hook_event_name": "PreToolUse", "session_id": "s-bootstrap",
            "tool_name": "Write", "tool_input": {
                "file_path": str(root / "target.txt"), "content": "blocked"},
        }),
        text=True, capture_output=True, env=env, timeout=10,
    )
    pending_arbitrary_write_blocked = (
        '"permissionDecision": "deny"' in (no_run_write.stdout or "")
        and "bootstrap run" in (no_run_write.stdout or ""))
    no_run_unbound_set = subprocess.run(
        [sys.executable, str(Path(__file__).resolve())],
        input=json.dumps({
            "hook_event_name": "PreToolUse", "session_id": "s-no-contract",
            "tool_name": "Bash", "tool_input": {
                "command": f"python3 {ROOT / 'tools' / 'xunji_statusline.py'} --set-active runs/ghost_20260101"},
        }),
        text=True, capture_output=True, env=env, timeout=10,
    )
    unbound_set_active_blocked = (
        '"permissionDecision": "deny"' in (no_run_unbound_set.stdout or "")
        and "bootstrap contract" in (no_run_unbound_set.stdout or ""))
    pending_target = root / "bootstrap_20260101"
    (pending_target / "state").mkdir(parents=True)
    claimed_pending = claim_pending_contract(
        pending_target, pending_dir=pending_dir, claims_dir=claims_dir)
    pending_claimed_into_run = (
        claimed_pending.get("session_id") == "s-bootstrap"
        and load_contract(pending_target, session_id="s-bootstrap").get("bound_run")
        == pending_target.name
        and not any(pending_dir.glob("*.json"))
    )
    ambiguous_dir = root / "ambiguous-pending"
    write_pending_contract({
        "session_id": "ambiguous-a", "prompt": "创建一个新 run alpha",
    }, pending_dir=ambiguous_dir)
    write_pending_contract({
        "session_id": "ambiguous-b", "prompt": "创建一个新 run beta",
    }, pending_dir=ambiguous_dir)
    ambiguous_target = root / "neutral_20260101"
    (ambiguous_target / "state").mkdir(parents=True)
    try:
        claim_pending_contract(
            ambiguous_target, pending_dir=ambiguous_dir,
            claims_dir=root / "ambiguous-claims")
        ambiguous_pending_rejected = False
    except RuntimeError:
        ambiguous_pending_rejected = True
    exact_dir = root / "exact-pending"
    exact_claims = root / "exact-claims"
    exact_a = write_pending_contract({
        "session_id": "exact-a", "prompt": "创建一个新 run",
    }, pending_dir=exact_dir)
    write_pending_contract({
        "session_id": "exact-b", "prompt": "创建另一个新 run",
    }, pending_dir=exact_dir)
    exact_target = root / "exact_20260101"
    (exact_target / "state").mkdir(parents=True)
    write_transition_claim(exact_target.name, exact_a, claims_dir=exact_claims)
    exact_txid = "a" * 32
    exact_source_hash = "b" * 64
    exact_claimed = claim_pending_contract(
        exact_target, pending_dir=exact_dir, claims_dir=exact_claims,
        transaction_id=exact_txid, source_hash=exact_source_hash,
        expected_run=exact_target.name)
    exact_session_claimed = (
        exact_claimed.get("session_id") == "exact-a"
        and load_pending_contract("exact-b", pending_dir=exact_dir).get("session_id") == "exact-b"
    )
    exact_transaction_bound = exact_claimed.get("transition_transaction") == {
        "transaction_id": exact_txid,
        "source_sha256": exact_source_hash,
        "expected_run": exact_target.name,
    }
    race_dir = root / "race-pending"
    race_claims = root / "race-claims"
    race_a = write_pending_contract({
        "session_id": "race-a", "prompt": "创建一个新 run race",
    }, pending_dir=race_dir)
    race_b = write_pending_contract({
        "session_id": "race-b", "prompt": "创建一个新 run race",
    }, pending_dir=race_dir)
    race_target = root / "race_20260101"
    (race_target / "state").mkdir(parents=True)
    write_transition_claim(race_target.name, race_a, claims_dir=race_claims)
    write_transition_claim(race_target.name, race_b, claims_dir=race_claims)
    try:
        claim_pending_contract(
            race_target, pending_dir=race_dir, claims_dir=race_claims)
        same_target_race_rejected = False
    except RuntimeError:
        same_target_race_rejected = True
    unrelated_no_run_prompt = subprocess.run(
        [sys.executable, str(Path(__file__).resolve())],
        input=json.dumps({
            "hook_event_name": "UserPromptSubmit", "session_id": "s-unrelated",
            "prompt": "修复这段本地代码",
        }),
        text=True, capture_output=True, env=env, timeout=10,
    )
    unrelated_prompt_not_persisted = (
        unrelated_no_run_prompt.returncode == 0
        and not (unrelated_no_run_prompt.stdout or "").strip()
        and not any(pending_dir.glob("*.json"))
    )
    explicit_runs = root / "explicit-runs"
    explicit_candidate = explicit_runs / "recent_20260101"
    explicit_candidate.mkdir(parents=True)
    (explicit_candidate / "target.md").write_text("# Target\n", encoding="utf-8")
    explicit_pointer = root / "active-pointer"
    no_pointer_does_not_guess = explicit_active_run(
        explicit_runs, explicit_pointer) is None
    explicit_pointer.write_text(str(explicit_candidate), encoding="utf-8")
    explicit_pointer_selected = explicit_active_run(
        explicit_runs, explicit_pointer) == explicit_candidate.resolve()
    no_run_cron = subprocess.run(
        [sys.executable, str(Path(__file__).resolve())],
        input=json.dumps({
            "hook_event_name": "PreToolUse", "session_id": "s",
            "tool_name": "CronCreate", "tool_input": {"prompt": "/loop future-run"},
        }),
        text=True, capture_output=True, env=env, timeout=10,
    )
    no_run_pointer_write = subprocess.run(
        [sys.executable, str(Path(__file__).resolve())],
        input=json.dumps({
            "hook_event_name": "PreToolUse", "session_id": "s",
            "tool_name": "Write",
            "tool_input": {"file_path": str(ROOT / ".claude" / "xunji_active_run"),
                           "content": "runs/forged\n"},
        }),
        text=True, capture_output=True, env=env, timeout=10,
    )
    no_run_pending_write = subprocess.run(
        [sys.executable, str(Path(__file__).resolve())],
        input=json.dumps({
            "hook_event_name": "PreToolUse", "session_id": "s",
            "tool_name": "Write",
            "tool_input": {"file_path": str(pending_dir / "forged.json"),
                           "content": "{}\n"},
        }),
        text=True, capture_output=True, env=env, timeout=10,
    )
    settings = json.loads((ROOT / ".claude" / "settings.json").read_text(encoding="utf-8"))
    hooks = settings.get("hooks", {})

    state_path = contract_path(run)
    state_path.write_text("{broken", encoding="utf-8")
    malformed_contract_rejected = load_contract(run, session_id="s") == {}
    _atomic_json(state_path, {
        "schema": "wrong", "mode": EXECUTE, "session_id": "s",
        "updated_at": time.time(),
    })
    wrong_schema_rejected = load_contract(run, session_id="s") == {}
    _atomic_json(state_path, {
        "schema": SCHEMA, "mode": EXECUTE, "session_id": "other",
        "updated_at": time.time(),
    })
    wrong_session_rejected = load_contract(run, session_id="s") == {}
    _atomic_json(state_path, {
        "schema": SCHEMA, "mode": EXECUTE, "session_id": "s",
        "updated_at": time.time() - STALE_SECONDS - 1,
    })
    stale_contract_rejected = load_contract(run, session_id="s") == {}
    source_run = root / "source-run"
    target_run = root / "target-run"
    (source_run / "state").mkdir(parents=True)
    (target_run / "state").mkdir(parents=True)
    transferred_source = write_contract(source_run, {
        "prompt": "/loop 重新开一个新 run", "session_id": "s-transition",
        "transcript_path": str(transcript),
    })
    transfer_txid = "c" * 32
    transfer_source_hash = "d" * 64
    transferred = transfer_contract(
        source_run,
        target_run,
        transaction_id=transfer_txid,
        source_hash=transfer_source_hash,
        expected_run=target_run.name,
    )
    transfer_preserves_contract = (
        transferred.get("prompt_sha256") == transferred_source.get("prompt_sha256")
        and transferred.get("session_id") == transferred_source.get("session_id")
        and transferred.get("origin_run") == source_run.name
        and transferred.get("bound_run") == target_run.name
        and transferred.get("transition_transaction") == {
            "transaction_id": transfer_txid,
            "source_sha256": transfer_source_hash,
            "expected_run": target_run.name,
        }
        and load_contract(target_run, session_id="s-transition") == transferred
        and json.loads(run_status_path(target_run).read_text(encoding="utf-8"))["status"] == "active"
    )
    override = write_contract(run, {
        "prompt": "继续执行，明确允许串行", "session_id": "s",
        "transcript_path": str(transcript),
    })
    operator_contract_raw = state_path.read_text(encoding="utf-8")
    operator_contract = json.loads(operator_contract_raw)
    internal_response = handle_event({
        "hook_event_name": "UserPromptSubmit",
        "session_id": "s",
        "prompt": "<task-notification><status>completed</status></task-notification>",
    }, run)
    internal_notification_preserves_contract = (
        state_path.read_text(encoding="utf-8") == operator_contract_raw
        and load_contract(run, session_id="s") == operator_contract
        and isinstance(internal_response, dict)
    )

    proxy_run = root / "proxy-run"
    (proxy_run / "state").mkdir(parents=True)
    (proxy_run / "frontier.md").write_text(
        "# Frontier\n## Open Fronts\n### F-001\n- Front: a.example public app\n"
        "- Status: open\n- Barrier class: none\n- Current depth: shallow\n",
        encoding="utf-8")
    (proxy_run / "coverage.json").write_text(json.dumps({"assets": [
        {"host": "a.example", "reachable": True, "examined": False},
    ]}), encoding="utf-8")
    proxy_contract = {
        "mode": EXECUTE, "session_id": "proxy-session", "prompt_excerpt": "继续执行",
        "fanout_override": True, "updated_at": time.time(),
    }
    raw_curl = {"tool_name": "Bash", "tool_input": {
        "command": "curl https://a.example/"}}
    raw_requests = {"tool_name": "Bash", "tool_input": {
        "command": "python3 -c 'import requests; requests.get(\"https://a.example\")'"}}
    target_webfetch = {"tool_name": "WebFetch", "tool_input": {"url": "https://a.example/"}}
    unknown_webfetch = {"tool_name": "WebFetch", "tool_input": {
        "url": "https://unknown.example/"}}
    guarded_probe = {"tool_name": "Bash", "tool_input": {
        "command": f"python3 {ROOT / 'tools' / 'probe.py'} GET https://a.example/"}}
    unknown_guarded_probe = {"tool_name": "Bash", "tool_input": {
        "command": f"python3 {ROOT / 'tools' / 'probe.py'} GET https://unknown.example/"}}
    direct_guarded_probe = {"tool_name": "Bash", "tool_input": {
        "command": (
            f"XUNJI_PROXY_REQUIRED=0 python3 {ROOT / 'tools' / 'probe.py'} "
            "GET https://a.example/"
        )}}
    direct_env_probe = {"tool_name": "Bash", "tool_input": {
        "command": f"python3 {ROOT / 'tools' / 'probe.py'} GET https://a.example/",
        "env": {"XUNJI_PROXY_REQUIRED": "0"},
    }}
    browser_target = {"tool_name": "mcp__browser__navigate", "tool_input": {
        "url": "https://a.example/"}}
    raw_curl_blocked = "交战代理硬门" in evaluate_pretool(proxy_run, raw_curl, proxy_contract)
    raw_requests_blocked = "交战代理硬门" in evaluate_pretool(
        proxy_run, raw_requests, proxy_contract)
    target_webfetch_blocked = "交战代理硬门" in evaluate_pretool(
        proxy_run, target_webfetch, proxy_contract)
    unknown_webfetch_blocked = "交战代理硬门" in evaluate_pretool(
        proxy_run, unknown_webfetch, proxy_contract)
    guarded_probe_allowed = evaluate_pretool(proxy_run, guarded_probe, proxy_contract) == ""
    scoped_proxy_coverage = json.loads(
        (proxy_run / "coverage.json").read_text(encoding="utf-8"))
    scoped_proxy_coverage["assets"][0]["scope_status"] = "review"
    (proxy_run / "coverage.json").write_text(
        json.dumps(scoped_proxy_coverage), encoding="utf-8")
    review_scope_target_blocked = "scope 准入硬门" in evaluate_pretool(
        proxy_run, guarded_probe, proxy_contract)
    scoped_proxy_coverage["assets"][0]["scope_status"] = "out"
    (proxy_run / "coverage.json").write_text(
        json.dumps(scoped_proxy_coverage), encoding="utf-8")
    out_scope_target_blocked = "scope 准入硬门" in evaluate_pretool(
        proxy_run, guarded_probe, proxy_contract)
    scoped_proxy_coverage["assets"][0]["scope_status"] = "in"
    scoped_proxy_coverage["assets"][0]["source"] = "setup-source-candidate"
    (proxy_run / "coverage.json").write_text(
        json.dumps(scoped_proxy_coverage), encoding="utf-8")
    forged_candidate_in_scope_blocked = "invalid-admission-receipt" in evaluate_pretool(
        proxy_run, guarded_probe, proxy_contract)
    scoped_proxy_coverage["assets"][0].pop("source", None)
    (proxy_run / "coverage.json").write_text(
        json.dumps(scoped_proxy_coverage), encoding="utf-8")
    explicit_in_scope_target_allowed = evaluate_pretool(
        proxy_run, guarded_probe, proxy_contract) == ""
    unknown_guarded_probe_blocked = "未知目标: unknown.example" in evaluate_pretool(
        proxy_run, unknown_guarded_probe, proxy_contract)
    direct_without_operator_blocked = "当前操作者 prompt" in evaluate_pretool(
        proxy_run, direct_guarded_probe, proxy_contract)
    direct_env_without_operator_blocked = "当前操作者 prompt" in evaluate_pretool(
        proxy_run, direct_env_probe, proxy_contract)
    direct_with_operator_allowed = evaluate_pretool(
        proxy_run, direct_guarded_probe,
        {**proxy_contract, "direct_egress_approved": True}) == ""
    nonbash_target_tool_blocked = "非 Bash 网络工具" in evaluate_pretool(
        proxy_run, browser_target, proxy_contract)
    (proxy_run / "frontier.md").write_text(
        "# Frontier\n## Open Fronts\n### F-001\n- Front: unmapped app\n"
        "- Status: open\n- Barrier class: none\n- Current depth: shallow\n",
        encoding="utf-8")
    unassigned_asset_blocked = "资产覆盖硬门" in evaluate_pretool(
        proxy_run, guarded_probe, proxy_contract)
    (proxy_run / "frontier.md").write_text(
        "# Frontier\n## Open Fronts\n### F-001\n- Front: a.example public app\n"
        "- Status: open\n- Barrier class: none\n- Current depth: shallow\n",
        encoding="utf-8")

    corrupt_run = root / "corrupt-coverage-run"
    corrupt_run.mkdir()
    (corrupt_run / "frontier.md").write_text(
        "# Frontier\n## Open Fronts\n### F-001\n- Front: unknown target\n"
        "- Status: open\n- Barrier class: none\n- Current depth: shallow\n",
        encoding="utf-8")
    (corrupt_run / "coverage.json").write_text("{broken", encoding="utf-8")
    corrupt_reason = evaluate_pretool(
        corrupt_run, {"tool_name": "Bash", "tool_input": {
            "command": f"python3 {ROOT / 'tools' / 'probe.py'} GET https://unknown.example/"}},
        proxy_contract)
    corrupt_coverage_fails_closed = (
        "资产覆盖硬门" in corrupt_reason and "coverage" in corrupt_reason)
    nested_run = root / "nested-coverage-run"
    (nested_run / "classify").mkdir(parents=True)
    (nested_run / "frontier.md").write_text(
        "# Frontier\n## Open Fronts\n### F-001\n- Front: nested.example app\n"
        "- Status: open\n- Barrier class: none\n- Current depth: shallow\n",
        encoding="utf-8")
    (nested_run / "coverage.json").write_text("{broken", encoding="utf-8")
    (nested_run / "classify" / "coverage.json").write_text(json.dumps({"assets": [
        {"host": "nested.example", "reachable": True},
    ]}), encoding="utf-8")
    nested_fallback_host_is_enforced = "交战代理硬门" in evaluate_pretool(
        nested_run, {"tool_name": "Bash", "tool_input": {
            "command": "curl https://nested.example/"}}, proxy_contract)

    epoch_first = write_contract(proxy_run, {
        "prompt": "继续执行", "session_id": "epoch-one", "transcript_path": str(transcript)})
    epoch_second = write_contract(proxy_run, {
        "prompt": "继续执行", "session_id": "epoch-two", "transcript_path": str(transcript)})
    proxy_cov = json.loads((proxy_run / "coverage.json").read_text(encoding="utf-8"))
    proxy_cov["assets"][0]["verdict"] = "closed"
    (proxy_run / "coverage.json").write_text(json.dumps(proxy_cov), encoding="utf-8")
    epoch_third = write_contract(proxy_run, {
        "prompt": "继续执行", "session_id": "epoch-three", "transcript_path": str(transcript)})
    fanout_epoch_persists = (
        epoch_first["fanout_epoch_started_at"] == epoch_second["fanout_epoch_started_at"]
        and epoch_first["fanout_epoch_id"] == epoch_second["fanout_epoch_id"])
    material_debt_change_resets_epoch = (
        epoch_third["fanout_epoch_id"] != epoch_second["fanout_epoch_id"]
        and epoch_third["fanout_epoch_started_at"] >= epoch_second["updated_at"])

    actor_run = root / "actor-run"
    (actor_run / "state").mkdir(parents=True)
    (actor_run / "agents").mkdir()
    (actor_run / "frontier.md").write_text(
        "# Frontier\n## Open Fronts\n"
        "### F-001\n- Front: a.example lane\n- Status: open\n- Barrier class: app\n- Current depth: shallow\n"
        "### F-002\n- Front: b.example lane\n- Status: open\n- Barrier class: auth\n- Current depth: shallow\n"
        "### F-003\n- Front: local code lane\n- Status: open\n- Barrier class: code\n- Current depth: shallow\n"
        "### F-004\n- Front: synthesis lane\n- Status: open\n- Barrier class: none\n- Current depth: shallow\n",
        encoding="utf-8")
    (actor_run / "coverage.json").write_text(json.dumps({"assets": [
        {"host": "a.example", "reachable": True},
        {"host": "b.example", "reachable": True},
    ]}), encoding="utf-8")
    (actor_run / "agents" / "A-one.md").write_text("# Agent\n", encoding="utf-8")
    (actor_run / "agents" / "A-two.md").write_text("# Agent\n", encoding="utf-8")
    (actor_run / "state" / "assignments.json").write_text(json.dumps({"assignments": [
        {"agent": "A-one", "front": "F-001", "status": "assigned", "assets": ["a.example"]},
        {"agent": "A-two", "front": "F-002", "status": "assigned", "assets": ["b.example"]},
    ]}), encoding="utf-8")
    actor_contract = {
        "mode": EXECUTE, "session_id": "actor-session", "prompt_excerpt": "继续执行",
        "updated_at": time.time(), "fanout_epoch_started_at": time.time() - 1,
    }
    actor_good_prompt = {"tool_name": "Agent", "tool_input": {"prompt":
        "XUNJI_ASSIGNMENT=A-one XUNJI_FRONT=F-001 XUNJI_ASSETS=a.example"}}
    actor_bad_assets_prompt = {"tool_name": "Agent", "tool_input": {"prompt":
        "XUNJI_ASSIGNMENT=A-one XUNJI_FRONT=F-001 XUNJI_ASSETS=b.example"}}
    asset_bound_prompt_allowed = evaluate_pretool(
        actor_run, actor_good_prompt, actor_contract) == ""
    mismatched_asset_prompt_blocked = "XUNJI_ASSETS=a.example" in evaluate_pretool(
        actor_run, actor_bad_assets_prompt, actor_contract)
    actor_transcript = root / "actor-transcript.jsonl"
    actor_transcript.write_text(
        "launch-one\nlaunch-two\nchild-one\nchild-two\nchild-one-action\nchild-two-action\n",
        encoding="utf-8")

    def actor_launch(tool_id: str, assignment: str, front: str, asset: str, child: str) -> None:
        runtime_receipts.append_hook_event(actor_run, {
            "hook_event_name": "PostToolUse", "session_id": "actor-session",
            "transcript_path": str(actor_transcript), "tool_name": "Agent",
            "tool_use_id": tool_id,
            "tool_input": {"prompt": (
                f"XUNJI_ASSIGNMENT={assignment} XUNJI_FRONT={front} XUNJI_ASSETS={asset}")},
            "tool_response": {"agentId": child, "isAsync": True, "status": "async_launched"},
        })

    actor_launch("launch-one", "A-one", "F-001", "a.example", "child-one")
    actor_launch("launch-two", "A-two", "F-002", "b.example", "child-two")
    child_own_action = {"tool_name": "Bash", "agent_id": "child-one", "tool_input": {
        "command": f"python3 {ROOT / 'tools' / 'probe.py'} GET https://a.example/"}}
    child_outside_action = {"tool_name": "Bash", "agent_id": "child-one", "tool_input": {
        "command": f"python3 {ROOT / 'tools' / 'probe.py'} GET https://b.example/"}}
    child_nested_agent = {"tool_name": "Agent", "agent_id": "child-one", "tool_input": {
        "prompt": "XUNJI_ASSIGNMENT=A-two XUNJI_FRONT=F-002 XUNJI_ASSETS=b.example"}}
    child_lane_allowed = evaluate_pretool(actor_run, child_own_action, actor_contract) == ""
    child_asset_escape_blocked = "越界资产" in evaluate_pretool(
        actor_run, child_outside_action, actor_contract)
    nested_agent_blocked = "只有 Root 可派 Agent" in evaluate_pretool(
        actor_run, child_nested_agent, actor_contract)
    root_allowed_while_agents_running = evaluate_pretool(
        actor_run, {**guarded_probe}, actor_contract) == ""
    runtime_receipts.append_hook_event(actor_run, {
        "hook_event_name": "SubagentStop", "session_id": "actor-session",
        "transcript_path": str(actor_transcript), "agent_id": "child-one",
        "agent_type": "general-purpose",
    })
    root_blocked_after_real_return = "SubagentStop" in evaluate_pretool(
        actor_run, {**guarded_probe}, actor_contract)
    child_two_action = {"tool_name": "Bash", "agent_id": "child-two", "tool_input": {
        "command": f"python3 {ROOT / 'tools' / 'probe.py'} GET https://b.example/"}}
    running_peer_not_blocked_by_returned_peer = evaluate_pretool(
        actor_run, child_two_action, actor_contract) == ""
    actor_assignments = json.loads(
        (actor_run / "state" / "assignments.json").read_text(encoding="utf-8"))
    for row in actor_assignments["assignments"]:
        if row.get("agent") == "A-two":
            row["assets"] = []
    (actor_run / "state" / "assignments.json").write_text(
        json.dumps(actor_assignments), encoding="utf-8")
    legacy_empty_asset_child_blocked = "空资产 assignment" in evaluate_pretool(
        actor_run, child_two_action, actor_contract)
    with actor_transcript.open("a", encoding="utf-8") as handle:
        handle.write("completion-launch\ncompletion-child\n")
    runtime_receipts.append_hook_event(actor_run, {
        "hook_event_name": "PostToolUse", "session_id": "actor-session",
        "transcript_path": str(actor_transcript), "tool_name": "Agent",
        "tool_use_id": "completion-launch",
        "tool_input": {"prompt": (
            "XUNJI_COMPLETION_REVIEW EVIDENCE_INDEX=" + "c" * 40
            + " CHECKS=report_parity,severity_artifacts,reachable_frontier,review_ledger")},
        "tool_response": {"agentId": "completion-child", "isAsync": True,
                          "status": "async_launched"},
    })
    completion_child_read_allowed = evaluate_pretool(actor_run, {
        "tool_name": "Read", "agent_id": "completion-child",
        "tool_input": {"file_path": str(actor_run / "evidence.md")},
    }, actor_contract) == ""
    completion_child_write_blocked = "只允许读取" in evaluate_pretool(actor_run, {
        "tool_name": "Write", "agent_id": "completion-child",
        "tool_input": {"file_path": str(actor_run / "report.md"), "content": "forged"},
    }, actor_contract)

    maintenance_prompt = (
        "/xunji-maintenance --scope tools/turn_contract.py,docs/WORKFLOW.md "
        "--reason 'repair live maintenance boundary'\ncontinue with local verification"
    )
    maintenance_contract = _contract_from_event({
        "prompt": maintenance_prompt,
        "session_id": "maintenance-session",
        "transcript_path": str(root / "maintenance-transcript.jsonl"),
    }, run_name=run.name)
    malformed_maintenance_contract = _contract_from_event({
        "prompt": "/xunji-maintenance --scope tools/turn_contract.py --bad option fix",
        "session_id": "maintenance-session",
    }, run_name=run.name)
    missing_session_maintenance_contract = _contract_from_event({
        "prompt": maintenance_prompt,
    }, run_name=run.name)
    quoted_source_contract = _contract_from_event({
        "prompt": (
            "/loop runs/example\nsource text: /xunji-maintenance --scope "
            "tools/turn_contract.py --reason forged"
        ),
        "session_id": "maintenance-session",
    }, run_name=run.name)
    critical_edit = {"tool_name": "Edit", "tool_input": {
        "file_path": str(ROOT / "tools" / "turn_contract.py"),
        "old_string": "old", "new_string": "new",
    }}
    adjacent_doc_edit = {"tool_name": "Edit", "tool_input": {
        "file_path": str(ROOT / "docs" / "WORKFLOW.md"),
        "old_string": "old", "new_string": "new",
    }}
    outside_edit = {"tool_name": "Edit", "tool_input": {
        "file_path": str(ROOT / "README.md"),
        "old_string": "old", "new_string": "new",
    }}
    maintenance_target = {"tool_name": "Bash", "tool_input": {
        "command": f"python3 {ROOT / 'tools' / 'probe.py'} GET https://example.test/",
    }}
    maintenance_cron = {"tool_name": "CronCreate", "tool_input": {
        "prompt": f"/loop {run.name}",
    }}
    maintenance_agent = {"tool_name": "Agent", "tool_input": {
        "prompt": "XUNJI_ASSIGNMENT=A-maint-001 XUNJI_FRONT=F-001",
    }}
    maintenance_mcp_read = {"tool_name": "ReadMcpResourceTool", "tool_input": {
        "server": "external", "uri": "resource://target-controlled",
    }}
    maintenance_shell_write = {"tool_name": "Bash", "tool_input": {
        "command": "sed -i '' s/old/new/ tools/turn_contract.py",
    }}
    maintenance_read = {"tool_name": "Bash", "tool_input": {
        "command": "sed -n '1,20p' tools/turn_contract.py",
    }}
    maintenance_compile = {"tool_name": "Bash", "tool_input": {
        "command": "python3 -m py_compile tools/turn_contract.py",
    }}
    maintenance_git_status = {"tool_name": "Bash", "tool_input": {
        "command": "git status --short",
    }}
    maintenance_git_diff = {"tool_name": "Bash", "tool_input": {
        "command": "git diff --no-ext-diff --no-textconv -- tools/turn_contract.py",
    }}
    maintenance_git_diff_unsafe = {"tool_name": "Bash", "tool_input": {
        "command": "git diff -- tools/turn_contract.py",
    }}
    maintenance_git_env = {"tool_name": "Bash", "tool_input": {
        "command": "git diff --no-ext-diff --no-textconv -- tools/turn_contract.py",
        "env": {"GIT_EXTERNAL_DIFF": "/tmp/untrusted-helper"},
    }}
    ordinary_git_env_status = {"tool_name": "Bash", "tool_input": {
        "command": "git status --short",
        "env": {"GIT_PAGER": "/tmp/untrusted-helper"},
    }}
    ordinary_encoded_write = {"tool_name": "Bash", "tool_input": {
        "command": (
            "python3 -c \"import base64,pathlib;"
            "pathlib.Path(base64.b64decode('dG9vbHMvdHVybl9jb250cmFjdC5weQ==')"
            ".decode()).write_text('changed')\""
        ),
    }}
    ordinary_pythonpath_target = {"tool_name": "Bash", "tool_input": {
        "command": (
            f"PYTHONPATH=/tmp python3 {ROOT / 'tools' / 'probe.py'} "
            "GET https://a.example/"
        ),
    }}
    maintenance_git_add = {"tool_name": "Bash", "tool_input": {
        "command": "git add -- tools/turn_contract.py",
    }}
    opaque_git_apply = {"tool_name": "Bash", "tool_input": {
        "command": "git apply /tmp/uninspected.patch",
    }}
    opaque_git_wrapped = [
        {"tool_name": "Bash", "tool_input": {
            "command": "env GIT_CONFIG_NOSYSTEM=1 /usr/bin/git apply /tmp/uninspected.patch",
        }},
        {"tool_name": "Bash", "tool_input": {
            "command": "sh -c 'git checkout -- tools/turn_contract.py'",
        }},
        {"tool_name": "Bash", "tool_input": {
            "command": "cd /tmp && patch -p1 < change.diff",
        }},
        {"tool_name": "Bash", "tool_input": {
            "command": "git pull --ff-only",
        }},
        {"tool_name": "Bash", "tool_input": {
            "command": "git clone https://example.test/repo.git /tmp/repo-copy",
        }},
    ]
    ordinary_critical_edit_blocked = "/xunji-maintenance" in evaluate_pretool(
        run, critical_edit, contract)
    authorized_critical_edit_allowed = evaluate_pretool(
        run, critical_edit, maintenance_contract) == ""
    authorized_adjacent_doc_allowed = evaluate_pretool(
        run, adjacent_doc_edit, maintenance_contract) == ""
    maintenance_outside_edit_blocked = "未授权" in evaluate_pretool(
        run, outside_edit, maintenance_contract)
    maintenance_target_blocked = "禁止 target/network" in evaluate_pretool(
        run, maintenance_target, maintenance_contract)
    maintenance_cron_blocked = "禁止 target/network" in evaluate_pretool(
        run, maintenance_cron, maintenance_contract)
    maintenance_agent_blocked = "禁止 target/network" in evaluate_pretool(
        run, maintenance_agent, maintenance_contract)
    maintenance_mcp_blocked = "不允许工具" in evaluate_pretool(
        run, maintenance_mcp_read, maintenance_contract)
    maintenance_shell_write_blocked = "禁止用 Bash" in evaluate_pretool(
        run, maintenance_shell_write, maintenance_contract)
    maintenance_read_allowed = evaluate_pretool(
        run, maintenance_read, maintenance_contract) == ""
    maintenance_compile_allowed = evaluate_pretool(
        run, maintenance_compile, maintenance_contract) == ""
    maintenance_git_read_allowed = evaluate_pretool(
        run, maintenance_git_status, maintenance_contract) == ""
    maintenance_git_diff_allowed = evaluate_pretool(
        run, maintenance_git_diff, maintenance_contract) == ""
    maintenance_git_diff_unsafe_blocked = bool(evaluate_pretool(
        run, maintenance_git_diff_unsafe, maintenance_contract))
    maintenance_git_env_blocked = "环境覆盖" in evaluate_pretool(
        run, maintenance_git_env, maintenance_contract)
    ordinary_git_env_blocked = "/xunji-maintenance" in evaluate_pretool(
        run, ordinary_git_env_status, contract)
    ordinary_encoded_write_blocked = "Bash 只能执行" in evaluate_pretool(
        run, ordinary_encoded_write, contract)
    ordinary_pythonpath_target_blocked = "/xunji-maintenance" in evaluate_pretool(
        run, ordinary_pythonpath_target, contract)
    maintenance_git_add_blocked = bool(evaluate_pretool(
        run, maintenance_git_add, maintenance_contract))
    ordinary_opaque_git_mutation_blocked = "/xunji-maintenance" in evaluate_pretool(
        run, opaque_git_apply, contract)
    ordinary_wrapped_repo_mutation_blocked = all(
        "/xunji-maintenance" in evaluate_pretool(run, event, contract)
        for event in opaque_git_wrapped
    )
    malformed_maintenance_write_blocked = "授权格式无效" in evaluate_pretool(
        run, critical_edit, malformed_maintenance_contract)
    maintenance_run = root / "maintenance-run"
    (maintenance_run / "state").mkdir(parents=True)
    for name in ("target.md", "frontier.md", "evidence.md", "decisions.md", "review.md"):
        (maintenance_run / name).write_text(f"# {name}\n", encoding="utf-8")
    written_maintenance_contract = write_contract(maintenance_run, {
        "prompt": maintenance_prompt,
        "session_id": "maintenance-session",
        "transcript_path": str(root / "maintenance-transcript.jsonl"),
    })
    maintenance_run_status = json.loads(
        run_status_path(maintenance_run).read_text(encoding="utf-8"))
    pending_maintenance_dir = root / "pending-maintenance"
    pending_maintenance = write_pending_contract({
        "prompt": maintenance_prompt,
        "session_id": "pending-maintenance-session",
    }, pending_dir=pending_maintenance_dir)
    pending_maintenance_loaded = load_pending_contract(
        "pending-maintenance-session", pending_dir=pending_maintenance_dir)

    live_runs = root / "live-maintenance-runs"
    live_run = live_runs / "live_maintenance_20260101"
    (live_run / "state").mkdir(parents=True)
    for name in ("target.md", "frontier.md", "evidence.md", "decisions.md", "review.md"):
        (live_run / name).write_text(f"# {name}\n", encoding="utf-8")
    live_pointer = root / "live-maintenance-pointer"
    live_pointer.write_text(str(live_run.resolve()) + "\n", encoding="utf-8")
    live_transcript = root / "live-maintenance-transcript.jsonl"
    live_transcript.write_text(
        "live-authorized-edit\nlive-outside-edit\nlive-critical-deny\n",
        encoding="utf-8",
    )
    live_env = dict(os.environ)
    live_env.update({
        "XUNJI_RUNS_ROOT": str(live_runs),
        "XUNJI_ACTIVE_RUN_FILE": str(live_pointer),
        "XUNJI_PENDING_TURN_DIR": str(root / "live-pending"),
        "XUNJI_TRANSITION_CLAIMS_DIR": str(root / "live-claims"),
    })

    def live_hook(event: dict) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [sys.executable, str(Path(__file__).resolve())],
            input=json.dumps(event), text=True, capture_output=True,
            env=live_env, timeout=10,
        )

    live_submit = live_hook({
        "hook_event_name": "UserPromptSubmit",
        "session_id": "live-maintenance-session",
        "transcript_path": str(live_transcript),
        "prompt": maintenance_prompt,
    })
    live_authorized_edit = live_hook({
        "hook_event_name": "PreToolUse",
        "session_id": "live-maintenance-session",
        "transcript_path": str(live_transcript),
        "tool_name": "Edit", "tool_use_id": "live-authorized-edit",
        "tool_input": {
            "file_path": str(ROOT / "tools" / "turn_contract.py"),
            "old_string": "old", "new_string": "new",
        },
    })
    live_outside_edit = live_hook({
        "hook_event_name": "PreToolUse",
        "session_id": "live-maintenance-session",
        "transcript_path": str(live_transcript),
        "tool_name": "Edit", "tool_use_id": "live-outside-edit",
        "tool_input": {
            "file_path": str(ROOT / "README.md"),
            "old_string": "old", "new_string": "new",
        },
    })
    live_execute_submit = live_hook({
        "hook_event_name": "UserPromptSubmit",
        "session_id": "live-maintenance-session",
        "transcript_path": str(live_transcript),
        "prompt": f"/loop {live_run}",
    })
    live_critical_denial = live_hook({
        "hook_event_name": "PreToolUse",
        "session_id": "live-maintenance-session",
        "transcript_path": str(live_transcript),
        "tool_name": "Edit", "tool_use_id": "live-critical-deny",
        "tool_input": {
            "file_path": str(ROOT / "tools" / "turn_contract.py"),
            "old_string": "old", "new_string": "new",
        },
    })
    live_execute_contract = load_contract(
        live_run, session_id="live-maintenance-session")
    live_denials = runtime_receipts.unresolved_maintenance_blockers(
        live_run, session_id="live-maintenance-session",
        since=float(live_execute_contract.get("updated_at") or 0.0),
    )

    def wired(event_name: str) -> bool:
        return any(
            "tools/turn_contract.py" in str(hook.get("command") or "")
            for group in hooks.get(event_name, []) if isinstance(group, dict)
            for hook in group.get("hooks", []) if isinstance(hook, dict)
        )

    session_start_selftest = any(
        "tools/turn_contract.py" in str(hook.get("command") or "")
        and "--selftest" in str(hook.get("command") or "")
        for group in hooks.get("SessionStart", []) if isinstance(group, dict)
        for hook in group.get("hooks", []) if isinstance(hook, dict)
    )
    pretool_groups = hooks.get("PreToolUse", [])
    global_pretool_first = bool(
        pretool_groups
        and isinstance(pretool_groups[0], dict)
        and not pretool_groups[0].get("matcher")
        and any(
            "tools/turn_contract.py" in str(hook.get("command") or "")
            for hook in pretool_groups[0].get("hooks", []) if isinstance(hook, dict)
        )
    )
    def receipt_matcher_tools(event_name: str) -> set[str]:
        found: set[str] = set()
        for group in hooks.get(event_name, []):
            if not isinstance(group, dict):
                continue
            if not any(
                    "tools/turn_contract.py" in str(hook.get("command") or "")
                    for hook in group.get("hooks", []) if isinstance(hook, dict)):
                continue
            found.update(
                token for token in str(group.get("matcher") or "").split("|") if token)
        return found
    maintenance_receipt_tools = {
        "Write", "Edit", "Update", "MultiEdit", "NotebookEdit",
    }
    checks = [
        ("explain overrides action words", explain == EXPLAIN),
        ("history/audit prompt without execute verb is read-only", history_only == EXPLAIN),
        ("ambiguous active-run prompt defaults read-only", ambiguous == EXPLAIN),
        ("operator stop maps to pause", pause == PAUSE),
        ("repair request maps to execute", execute == EXECUTE),
        ("unrecognized English execution wording defaults read-only", indirect_english == EXPLAIN),
        ("no-active-run ordinary question stays outside run execution", no_run_question == NORMAL),
        ("active-run informational question stays read-only", active_run_question == EXPLAIN),
        ("explicit active-run switch remains executable", active_run_switch == EXECUTE),
        ("maintenance directive is a distinct exact-path turn mode",
         maintenance_contract.get("mode") == MAINTENANCE
         and maintenance_contract.get("maintenance_authorized_paths") == [
             "tools/turn_contract.py", "docs/WORKFLOW.md"]
         and maintenance_contract.get("maintenance_critical_paths") == [
             "tools/turn_contract.py"]
         and len(str(maintenance_contract.get("prompt_sha256") or "")) == 64),
        ("source text after the first operator instruction cannot mint maintenance authority",
         quoted_source_contract.get("mode") == EXECUTE
         and not quoted_source_contract.get("maintenance_authorized_paths")),
        ("malformed maintenance command fails closed instead of becoming execute",
         malformed_maintenance_contract.get("mode") == EXPLAIN
         and bool(malformed_maintenance_contract.get("maintenance_parse_error"))),
        ("maintenance authority fails closed without hook session identity",
         missing_session_maintenance_contract.get("mode") == EXPLAIN
         and "session id" in str(
             missing_session_maintenance_contract.get("maintenance_parse_error") or "")),
        ("ordinary live loop cannot edit a safety-critical path",
         ordinary_critical_edit_blocked),
        ("maintenance exact scope allows the authorized critical path",
         authorized_critical_edit_allowed),
        ("maintenance exact scope allows its adjacent documentation path",
         authorized_adjacent_doc_allowed),
        ("maintenance exact scope rejects an unlisted repository path",
         maintenance_outside_edit_blocked),
        ("maintenance turn blocks target actions and Cron",
         maintenance_target_blocked and maintenance_cron_blocked
         and maintenance_agent_blocked and maintenance_mcp_blocked),
        ("maintenance turn forbids Bash source mutation",
         maintenance_shell_write_blocked),
        ("maintenance turn allows read-only Bash and direct py_compile",
         maintenance_read_allowed and maintenance_compile_allowed
         and maintenance_git_read_allowed and maintenance_git_diff_allowed
         and maintenance_git_diff_unsafe_blocked and maintenance_git_env_blocked),
        ("maintenance turn denies git index/worktree mutation",
         maintenance_git_add_blocked),
        ("ordinary live loop denies opaque git patch mutation",
         ordinary_opaque_git_mutation_blocked
         and ordinary_wrapped_repo_mutation_blocked),
        ("ordinary live loop denies env-injected reads and unknown interpreters",
         ordinary_git_env_blocked and ordinary_encoded_write_blocked
         and ordinary_pythonpath_target_blocked),
        ("malformed maintenance authority permits reads but denies writes",
         malformed_maintenance_write_blocked
         and evaluate_pretool(run, {"tool_name": "Read", "tool_input": {
             "file_path": str(ROOT / "tools" / "turn_contract.py")}},
             malformed_maintenance_contract) == ""),
        ("maintenance contract freezes the live run in derived run status",
         written_maintenance_contract.get("mode") == MAINTENANCE
         and maintenance_run_status.get("status") == "maintenance"),
        ("no-active-run maintenance authority stays session-bound and short-lived",
         pending_maintenance.get("mode") == MAINTENANCE
         and pending_maintenance_loaded.get("session_id") == "pending-maintenance-session"),
        ("live hook pipeline binds maintenance mode and exact authorized Edit",
         live_submit.returncode == 0
         and "MAINTENANCE" in (live_submit.stdout or "")
         and live_authorized_edit.returncode == 0
         and not (live_authorized_edit.stdout or "").strip()),
        ("live hook pipeline denies an out-of-scope maintenance Edit",
         '"permissionDecision": "deny"' in (live_outside_edit.stdout or "")
         and "未授权" in (live_outside_edit.stdout or "")),
        ("new execute turn revokes maintenance scope and records critical denial",
         live_execute_submit.returncode == 0
         and '"permissionDecision": "deny"' in (live_critical_denial.stdout or "")
         and len(live_denials) == 1
         and live_denials[0].get("maintenance_paths") == ["tools/turn_contract.py"]),
        ("negated direct-egress phrases never grant approval",
         not negated_direct_cn["direct_egress_approved"]
         and not negated_direct_en["direct_egress_approved"]),
        ("explicit direct-egress phrase grants current-turn approval",
         explicit_direct["direct_egress_approved"]),
        ("exact scope directive binds run/assets and execute mode",
         scope_contract.get("mode") == EXECUTE
         and scope_contract.get("scope_admission_run") == "pilot_20260715"
         and scope_contract.get("scope_admission_assets")
         == ["one.example.test", "two.example.test"]),
        ("scope admission turn is zero-probe and blocks target actions",
         scope_turn_target_blocked),
        ("malformed scope directive permits no write authority",
         malformed_scope_contract.get("mode") == EXPLAIN
         and malformed_scope_write_blocked),
        ("target action blocked before real fanout", before_fanout),
        ("run-model failure produces a deterministic fail-closed contract state",
         bool(summary_failure_signature)
         and "canonical frontier" in summary_failure_reason),
        ("raw target curl is denied by proxy egress gate", raw_curl_blocked),
        ("raw target requests code is denied by proxy egress gate", raw_requests_blocked),
        ("target WebFetch is denied because it cannot attest engagement proxy",
         target_webfetch_blocked),
        ("unknown-host WebFetch cannot bypass the engagement proxy gate",
         unknown_webfetch_blocked),
        ("proxy-aware guarded target tool is allowed", guarded_probe_allowed),
        ("source/AI review-scope asset cannot become a target capability",
         review_scope_target_blocked),
        ("explicit out-of-scope asset stays blocked", out_scope_target_blocked),
        ("candidate in-scope hand edit without committed operator receipt stays blocked",
         forged_candidate_in_scope_blocked),
        ("explicit in-scope ledger asset remains executable",
         explicit_in_scope_target_allowed),
        ("proxy-aware tool rejects destinations absent from the asset ledger",
         unknown_guarded_probe_blocked),
        ("direct-egress opt-out requires current operator approval",
         direct_without_operator_blocked and direct_env_without_operator_blocked),
        ("current operator may explicitly approve direct egress",
         direct_with_operator_allowed),
        ("non-Bash target network tool cannot bypass proxy attestation",
         nonbash_target_tool_blocked),
        ("unassigned coverage asset blocks target action", unassigned_asset_blocked),
        ("corrupt coverage fails closed instead of disabling the asset gate",
         corrupt_coverage_fails_closed),
        ("valid nested coverage still enforces hosts when root coverage is corrupt",
         nested_fallback_host_is_enforced),
        ("continue prompts preserve a material fanout epoch across sessions",
         fanout_epoch_persists),
        ("material coverage-debt change resets fanout epoch",
         material_debt_change_resets_epoch),
        ("asset-bound Agent prompt is accepted", asset_bound_prompt_allowed),
        ("Agent prompt with mismatched asset package is denied",
         mismatched_asset_prompt_blocked),
        ("bound child Agent may execute its own target lane", child_lane_allowed),
        ("child Agent cannot escape its assigned asset package", child_asset_escape_blocked),
        ("child Agent cannot create nested Agent fanout", nested_agent_blocked),
        ("Root is not deadlocked while async Agents are still running",
         root_allowed_while_agents_running),
        ("Root disposition gate starts only after real SubagentStop",
         root_blocked_after_real_return),
        ("running child is not blocked by a returned peer's disposition debt",
         running_peer_not_blocked_by_returned_peer),
        ("legacy empty-asset child cannot execute target actions",
         legacy_empty_asset_child_blocked),
        ("completion-review child can read frozen run state",
         completion_child_read_allowed),
        ("completion-review child cannot mutate run state",
         completion_child_write_blocked),
        ("encoded network command blocked before fanout", encoded_before_fanout),
        ("renamed unknown script blocked before fanout", renamed_before_fanout),
        ("workers control command allowed before fanout", workers_allowed_before_fanout),
        ("workers --asset control is not misclassified as target egress",
         workers_asset_control_allowed),
        ("quoted disposition punctuation remains valid control data",
         workers_quoted_note_allowed),
        ("all quoted shell punctuation remains inert control data",
         quoted_punctuation_allowed),
        ("single-quoted substitutions remain literal control data",
         single_quoted_literals_allowed),
        ("backslash-escaped substitution remains literal control data",
         escaped_substitution_literal_allowed),
        ("ANSI-C shell expansion is not accepted as exact control argv",
         ansi_c_literal_rejected),
        ("trailing shell comments are not accepted as exact control argv",
         trailing_comment_control_rejected),
        ("unquoted shell chaining cannot impersonate a control command",
         workers_shell_chain_rejected),
        ("adversarial shell syntax fails closed through evaluate_pretool",
         adversarial_controls_fail_closed),
        ("bare python control command is recognized", bare_python_control_allowed),
        ("micro-version Python control command is recognized",
         micro_python_control_allowed),
        ("new-run setup command is lifecycle control before old-run fanout",
         setup_allowed_before_fanout),
        ("prompt-named --source URL is local lifecycle control",
         source_setup_allowed and not _is_target_action(source_control)),
        ("--source URL absent from the operator prompt is blocked",
         unrelated_source_setup_blocked),
        ("--source basename collision is not operator authority",
         basename_collision_source_blocked),
        ("prepared setup transaction blocks target work", prepared_target_blocked),
        ("prepared setup transaction blocks CronCreate", prepared_cron_blocked),
        ("prepared setup transaction remains readable", prepared_read_allowed),
        ("prepared setup transaction permits explicit recovery lifecycle",
         prepared_recovery_allowed),
        ("setup cannot be used without current operator run-transition intent",
         setup_without_operator_blocked),
        ("documented loop journal command is control before fanout",
         journal_allowed_before_fanout),
        ("clear-active needs current operator authorization", clear_without_operator_blocked),
        ("operator-authorized clear-active is allowed", clear_with_operator_allowed),
        ("English operator-authorized clear-active is allowed",
         clear_with_english_operator_allowed),
        ("set-active cannot switch to a run absent from the operator prompt",
         unrelated_set_active_blocked),
        ("prompt-named set-active is allowed", named_set_active_allowed),
        ("prompt-named resume is allowed across runs", named_resume_allowed),
        ("setup --classify keeps the following slug positional",
         classify_setup_target == "classified_20260101"),
        ("setup --target URL is consumed without replacing the run slug",
         url_setup_target == "url-target_20260101"),
        ("loop bootstrap --source URL derives the exact target run",
         routed_url_target == f"new-source-example_{datetime.now().strftime('%Y%m%d')}"),
        ("unknown lifecycle options fail closed instead of rebinding the slug",
         unknown_option_target == ""),
        ("loop bootstrap resume extracts the exact target run",
         direct_resume_target == "resume_20260101"),
        ("statusline set-active extracts the exact target run",
         direct_set_active_target == "selected_20260101"),
        ("out-of-tree workers.py cannot impersonate control plane",
         fake_workers_blocked_before_fanout),
        ("narrow sed print remains read-only before fanout", safe_sed_allowed_before_fanout),
        ("sed in-place mutation blocked before fanout", sed_in_place_blocked),
        ("sed write command blocked before fanout", sed_write_blocked),
        ("find file-output action blocked before fanout", find_file_output_blocked),
        ("protected control-plane denial is not a target-result action",
         protected_denial_not_target),
        ("direct active-run pointer Write is blocked", pointer_write_blocked),
        ("direct coverage ledger Write is blocked", coverage_write_blocked),
        ("controlled coverage sync remains allowed", coverage_sync_control_allowed),
        ("active-run pointer shell denial is local, not a target result",
         pointer_shell_is_local),
        ("old-session Agent receipts do not satisfy this turn", old_fanout_still_blocked),
        ("receipts without post-return disposition remain blocked",
         receipts_without_disposition_block),
        ("current receipts plus anchored disposition unlock target action",
         current_fanout_allows),
        ("missing contract blocks target action", missing_contract_blocks),
        ("malformed frontier blocks target action", malformed_frontier_blocks),
        ("missing frontier blocks target action", missing_frontier_blocks),
        ("malformed contract is rejected", malformed_contract_rejected),
        ("wrong contract schema is rejected", wrong_schema_rejected),
        ("cross-session contract reuse is rejected", wrong_session_rejected),
        ("stale contract is rejected", stale_contract_rejected),
        ("active-run transition preserves the current contract and run status",
         transfer_preserves_contract),
        ("serial override requires current operator prompt", override.get("fanout_override") is True),
        ("internal task notification cannot replace operator turn contract",
         internal_notification_preserves_contract),
        ("Agent without binding tokens blocked", agent_bad_blocked),
        ("bound Agent call allowed", agent_good_allowed),
        ("completion Agent without full checklist is blocked",
         bool(evaluate_pretool(run, completion_bad, contract))),
        ("completion Agent with evidence hash and checklist is allowed",
         evaluate_pretool(run, completion_good, contract) == ""),
        ("explain mode blocks Bash", bool(evaluate_pretool(run, target_event, {"mode": EXPLAIN}))),
        ("pause mode allows CronList", evaluate_pretool(run, {"tool_name": "CronList", "tool_input": {}}, {"mode": PAUSE}) == ""),
        ("CronCreate requires current-turn CronList", cron_before_list),
        ("CronCreate allowed after current-turn empty CronList", cron_after_list),
        ("new-run /loop cannot schedule the origin run before transition",
         new_run_cron_blocked_until_transition),
        ("CronCreate without an active run is blocked",
         '"permissionDecision": "deny"' in (no_run_cron.stdout or "")),
        ("root control files stay protected with no active run",
         '"permissionDecision": "deny"' in (no_run_pointer_write.stdout or "")
         and "active-run" in (no_run_pointer_write.stdout or "")
         and '"permissionDecision": "deny"' in (no_run_pending_write.stdout or "")),
        ("no-active-run UserPromptSubmit stores a bootstrap contract", pending_written),
        ("no-active-run normalizer prepare needs a current bootstrap contract",
         unbound_normalizer_prepare_blocked),
        ("no-active-run normalizer prepare cannot self-authorize external egress",
         implicit_external_prepare_blocked),
        ("operator-bound external prepare is read-only and creates no transition claim",
         explicit_external_prepare_allowed_without_claim),
        ("pending bootstrap allows its authorized setup command",
         pending_setup_allowed),
        ("pending bootstrap blocks target execution before run binding",
         pending_target_action_blocked),
        ("pending bootstrap blocks arbitrary writes before run binding",
         pending_arbitrary_write_blocked),
        ("set-active without a current-session bootstrap contract is blocked",
         unbound_set_active_blocked),
        ("first active run consumes and binds the bootstrap contract",
         pending_claimed_into_run),
        ("ambiguous pending contracts fail closed instead of crossing sessions",
         ambiguous_pending_rejected),
        ("target claim selects the exact session among concurrent pending contracts",
         exact_session_claimed),
        ("consumed target claim binds source, transaction, and expected run",
         exact_transaction_bound),
        ("same-target concurrent session claims fail closed",
         same_target_race_rejected),
        ("no-run non-lifecycle prompt does not leave a pending contract",
         unrelated_prompt_not_persisted),
        ("turn contracts do not guess a recent run without a pointer",
         no_pointer_does_not_guess),
        ("turn contracts bind the explicit active pointer", explicit_pointer_selected),
        ("settings wires UserPromptSubmit contract", wired("UserPromptSubmit")),
        ("settings wires global PreToolUse contract", wired("PreToolUse")),
        ("settings runs turn contract selftest at SessionStart", session_start_selftest),
        ("global turn contract PreToolUse hook is first", global_pretool_first),
        ("settings wires Agent/Cron PostToolUse receipts", wired("PostToolUse")),
        ("settings wires failed tool receipts", wired("PostToolUseFailure")),
        ("settings wires maintenance write success and failure receipts",
         maintenance_receipt_tools <= receipt_matcher_tools("PostToolUse")
         and maintenance_receipt_tools <= receipt_matcher_tools("PostToolUseFailure")),
        ("settings wires Subagent lifecycle receipts",
         wired("SubagentStart") and wired("SubagentStop")),
        ("CronDelete rejects job not listed for this run", bool(evaluate_pretool(
            run, {"tool_name": "CronDelete", "tool_input": {"id": "otherjob"}}, contract))),
        ("memory write needs explicit approval", bool(evaluate_pretool(
            run, {"tool_name": "Write", "tool_input": {"file_path": "/tmp/.claude/x/memory/MEMORY.md"}},
            {"mode": EXECUTE}))),
        ("relative Bash memory path needs explicit approval", bool(evaluate_pretool(
            run, {"tool_name": "Bash", "tool_input": {
                "command": "mkdir -p .claude/x/memory && printf x > .claude/x/memory/MEMORY.md"}},
            contract))),
        ("read-only Bash memory access remains allowed", not bool(evaluate_pretool(
            run, {"tool_name": "Bash", "tool_input": {
                "command": "ls -la .claude/x/memory && cat .claude/x/memory/MEMORY.md"}},
            contract))),
        ("direct memory Read remains allowed", not bool(evaluate_pretool(
            run, {"tool_name": "Read", "tool_input": {
                "file_path": "/tmp/.claude/x/memory/MEMORY.md"}}, contract))),
        ("background review is blocked", bool(evaluate_pretool(
            run, {"tool_name": "Bash", "tool_input": {
                "command": "python tools/peer_review.py runs/x > /tmp/review.log 2>&1 & echo started"}},
            contract))),
        ("foreground review redirection is allowed", not bool(evaluate_pretool(
            run, {"tool_name": "Bash", "tool_input": {
                "command": "python tools/peer_review.py runs/x > /tmp/review.log 2>&1"}},
            contract))),
        ("protected runtime receipt cannot be edited", bool(evaluate_pretool(
            run, {"tool_name": "Write", "tool_input": {"file_path": str(run / "state" / "runtime_events.jsonl")}},
            contract))),
        ("protected runtime receipt remains readable", not bool(evaluate_pretool(
            run, {"tool_name": "Read", "tool_input": {"file_path": str(run / "state" / "runtime_events.jsonl")}},
            contract))),
    ]
    bad = [name for name, ok in checks if not ok]
    for name, ok in checks:
        print(("ok   " if ok else "FAIL ") + name)
    print("turn_contract selftest " + ("passed" if not bad else f"FAILED ({len(bad)})"))
    return 0 if not bad else 1


def main() -> int:
    parser = argparse.ArgumentParser(description="Xunji Claude Code turn contract hook")
    parser.add_argument("--selftest", action="store_true")
    args = parser.parse_args()
    if args.selftest:
        return _selftest()
    try:
        event = json.loads(sys.stdin.buffer.read().decode("utf-8", "replace") or "{}")
    except Exception:
        return 0
    try:
        result = handle_event(event)
        if result:
            print(json.dumps(result, ensure_ascii=False))
    except Exception as exc:
        if str(event.get("hook_event_name") or "") == "PreToolUse":
            run_dir = explicit_active_run()
            if run_dir is not None:
                print(json.dumps(_deny(
                    "Xunji PreToolUse contract 内部异常，active run 按 fail-closed 阻断："
                    + type(exc).__name__), ensure_ascii=False))
        return 0
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
