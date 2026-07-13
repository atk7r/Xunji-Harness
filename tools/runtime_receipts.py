#!/usr/bin/env python3
"""Hook-derived runtime receipts for Agent, Cron, and completion events.

Canonical findings still live in Markdown.  Runtime facts do not: an Agent spawn,
Cron deletion, or completion review is true only when a Claude Code hook observed
the tool event and the referenced tool-use id exists in the session transcript.
"""
from __future__ import annotations

import argparse
import contextlib
import hashlib
import json
import os
import re
import shlex
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path

try:
    import fcntl
except ImportError:  # pragma: no cover - Windows fallback remains atomic per write
    fcntl = None


SCHEMA = "xunji.runtime_receipt.v1"
EVENTS = "runtime_events.jsonl"
MAX_EXCERPT = 6000
PROJECTION_ERROR = "runtime_projection_error.json"
NONTERMINAL_ASSIGNMENT_STATUSES = {"assigned", "starting", "running", "working", "?", ""}
TERMINAL_ASSIGNMENT_STATUSES = {"done", "merged", "blocked", "failed", "abandoned"}


def _json_bytes(value: object) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


def _hash(value: object) -> str:
    return hashlib.sha256(_json_bytes(value)).hexdigest()


def _action_hash(tool: str, tool_input: object) -> str:
    """Hash all tool semantics while ignoring only known presentation metadata."""
    payload = dict(tool_input) if isinstance(tool_input, dict) else {}
    if tool == "Bash":
        payload.pop("description", None)
        payload.pop("timeout", None)
    return _hash(payload)


def _event_path(run_dir: Path) -> Path:
    return run_dir / "state" / EVENTS


def _lock_path(run_dir: Path) -> Path:
    return run_dir / "state" / ".runtime_events.lock"


def _projection_error_path(run_dir: Path) -> Path:
    return run_dir / "state" / PROJECTION_ERROR


@contextlib.contextmanager
def _locked(run_dir: Path):
    lock = _lock_path(run_dir)
    lock.parent.mkdir(parents=True, exist_ok=True)
    with lock.open("a+", encoding="utf-8") as handle:
        if fcntl is not None:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
        try:
            yield
        finally:
            if fcntl is not None:
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def load_events(run_dir: str | Path) -> list[dict]:
    path = _event_path(Path(run_dir))
    if not path.exists():
        return []
    out: list[dict] = []
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        try:
            item = json.loads(line)
        except Exception:
            continue
        if isinstance(item, dict):
            out.append(item)
    return out


def _excerpt(value: object) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        text = value
    else:
        try:
            text = json.dumps(value, ensure_ascii=False, sort_keys=True)
        except Exception:
            text = str(value)
    text = re.sub(r"(?i)(bearer\s+)[A-Za-z0-9._~+/=-]{12,}", r"\1[REDACTED]", text)
    return text[:MAX_EXCERPT]


def _input_text(event: dict) -> str:
    tool_input = event.get("tool_input") if isinstance(event.get("tool_input"), dict) else {}
    text = "\n".join(str(tool_input.get(key) or "") for key in (
        "prompt", "description", "command", "job_id", "id",
    ))
    if text.strip():
        return text
    return str(event.get("input_excerpt") or "")


def _mapping(value: object) -> dict:
    if isinstance(value, dict):
        return value
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
        except Exception:
            return {}
        return parsed if isinstance(parsed, dict) else {}
    return {}


def _agent_launch_fields(value: object) -> tuple[str, bool, str]:
    response = _mapping(value)
    agent_id = str(response.get("agentId") or response.get("agent_id") or "").strip()
    status = str(response.get("status") or "").strip().lower()
    is_async = bool(response.get("isAsync")) or status in {"async_launched", "running"}
    return agent_id, is_async, status


def _assignment_fields(text: str) -> tuple[str, str]:
    assignment = re.search(r"(?i)\bXUNJI_ASSIGNMENT\s*=\s*(A-[A-Za-z0-9._-]+)", text)
    front = re.search(r"(?i)\bXUNJI_FRONT\s*=\s*(F-\d+)", text)
    return (
        assignment.group(1) if assignment else "",
        front.group(1).upper() if front else "",
    )


def _assignment_assets(text: str) -> list[str]:
    match = re.search(r"(?im)\bXUNJI_ASSETS\s*=\s*([^\s]+)", text)
    if not match:
        return []
    out: list[str] = []
    for raw in match.group(1).split(","):
        value = raw.strip().strip("[]{}'\"").lower().rstrip(".")
        value = re.sub(r"^[a-z][a-z0-9+.\-]*://", "", value).split("/", 1)[0]
        if value and value not in out:
            out.append(value)
    return out


def _evidence_hash(text: str) -> str:
    match = re.search(r"(?i)\bEVIDENCE_INDEX\s*=\s*([0-9a-f]{40,64})\b", text)
    return match.group(1).lower() if match else ""


def _job_id(value: object) -> str:
    if isinstance(value, dict):
        for key in ("id", "job_id", "jobId", "task_id"):
            raw = value.get(key)
            if isinstance(raw, str) and re.fullmatch(r"[A-Za-z0-9_.:-]{6,64}", raw):
                return raw
        for child in value.values():
            found = _job_id(child)
            if found:
                return found
    if isinstance(value, list):
        for child in value:
            found = _job_id(child)
            if found:
                return found
    text = _excerpt(value)
    match = re.search(r"(?i)\b(?:job|task)?[_ -]?id\s*[:=]\s*([A-Za-z0-9_.:-]{6,64})", text)
    return match.group(1) if match else ""


def _job_ids(value: object) -> list[str]:
    found: list[str] = []
    if isinstance(value, dict):
        direct = _job_id({key: value.get(key) for key in ("id", "job_id", "jobId", "task_id")})
        if direct:
            found.append(direct)
        for child in value.values():
            found.extend(_job_ids(child))
    elif isinstance(value, list):
        for child in value:
            found.extend(_job_ids(child))
    return list(dict.fromkeys(found))


def _run_job_ids(value: object, run_name: str) -> list[str]:
    """Extract IDs only from the smallest structured task objects naming this run."""
    found: list[str] = []
    if isinstance(value, dict):
        direct = ""
        for key in ("id", "job_id", "jobId", "task_id"):
            raw = value.get(key)
            if isinstance(raw, str) and re.fullmatch(r"[A-Za-z0-9_.:-]{6,64}", raw):
                direct = raw
                break
        if direct and run_name and run_name.lower() in _excerpt(value).lower():
            found.append(direct)
        for child in value.values():
            found.extend(_run_job_ids(child, run_name))
    elif isinstance(value, list):
        for child in value:
            found.extend(_run_job_ids(child, run_name))
    return list(dict.fromkeys(found))


def normalize_hook_event(run_dir: str | Path, event: dict) -> dict:
    run = Path(run_dir).resolve()
    hook = str(event.get("hook_event_name") or "")
    tool = str(event.get("tool_name") or "")
    input_text = _input_text(event)
    assignment, front = _assignment_fields(input_text)
    response = event.get("tool_response")
    launched_agent_id, agent_is_async, agent_status = _agent_launch_fields(response)
    record = {
        "schema": SCHEMA,
        "ts": time.time(),
        "run_dir": str(run),
        "session_id": str(event.get("session_id") or ""),
        "transcript_path": str(event.get("transcript_path") or ""),
        "hook_event_name": hook,
        "tool_name": tool,
        "tool_use_id": str(event.get("tool_use_id") or ""),
        "success": hook in {"PostToolUse", "SubagentStart", "SubagentStop"},
        "decision": str(event.get("xunji_decision") or ""),
        "decision_reason": _excerpt(event.get("xunji_reason") or ""),
        "target_action": bool(event.get("xunji_target_action")),
        "assignment": assignment,
        "front": front,
        "assignment_assets": _assignment_assets(input_text),
        "input_excerpt": _excerpt(event.get("tool_input") or {}),
        "input_sha256": _hash(event.get("tool_input") or {}),
        "action_sha256": _action_hash(tool, event.get("tool_input") or {}),
        "response_sha256": _hash(response or {}),
        "response_excerpt": _excerpt(response),
        "agent_id": str(event.get("agent_id") or ""),
        "agent_type": str(event.get("agent_type") or ""),
        "launched_agent_id": launched_agent_id,
        "agent_is_async": agent_is_async,
        "agent_status": agent_status,
        "job_id": _job_id(response) or _job_id(event.get("tool_input") or {}),
        "job_ids": _job_ids(response) or _job_ids(event.get("tool_input") or {}),
        "listed_run_job_ids": _run_job_ids(response, run.name) if tool == "CronList" else [],
        "completion_review": "XUNJI_COMPLETION_REVIEW" in input_text.upper(),
        "evidence_index_hash": _evidence_hash(input_text),
        "run_mentioned": run.name.lower() in input_text.lower(),
    }
    return record


def _iso_timestamp(value: float) -> str:
    return datetime.fromtimestamp(value, timezone.utc).isoformat(timespec="milliseconds").replace(
        "+00:00", "Z")


def _atomic_json(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, raw = tempfile.mkstemp(prefix=path.name + ".", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(value, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
        os.replace(raw, path)
    finally:
        try:
            os.unlink(raw)
        except FileNotFoundError:
            pass


def _project_agent_lifecycle(run_dir: Path, record: dict) -> None:
    """Project trusted hook lifecycle into assignment attempts.

    Agent PostToolUse is a launch acknowledgement when Claude returns
    ``status=async_launched``.  It must never be projected as completion.  The
    matching SubagentStop is the return boundary.
    """
    path = run_dir / "state" / "assignments.json"
    if not path.exists():
        return
    try:
        data = json.loads(path.read_text(encoding="utf-8", errors="replace"))
    except Exception as exc:
        raise RuntimeError("cannot parse assignments.json for runtime projection") from exc
    rows = data.get("assignments") if isinstance(data, dict) else None
    if not isinstance(rows, list):
        raise RuntimeError("assignments.json has no valid assignments list")

    hook = str(record.get("hook_event_name") or "")
    changed = False
    stamp = _iso_timestamp(float(record.get("ts") or time.time()))
    if hook == "PostToolUse" and record.get("tool_name") == "Agent" \
            and record.get("success") is True:
        assignment = str(record.get("assignment") or "")
        front = str(record.get("front") or "")
        launched_id = str(record.get("launched_agent_id") or "")
        attempt_id = launched_id or str(record.get("tool_use_id") or "")
        if not assignment or not front or not attempt_id:
            return
        derived = next((item for item in agent_attempts(run_dir)
                        if str(item.get("tool_use_id") or "")
                        == str(record.get("tool_use_id") or "")), {})
        derived_returned_at = float(derived.get("returned_at") or 0.0)
        projected_state = (
            "returned" if derived_returned_at or not record.get("agent_is_async") else "running"
        )
        for row in rows:
            if not isinstance(row, dict) or str(row.get("agent") or "") != assignment:
                continue
            if str(row.get("front") or "").upper() != front.upper():
                raise RuntimeError(
                    f"assignment/front mismatch for {assignment}: "
                    f"receipt={front} state={row.get('front') or '(missing)'}"
                )
            expected_assets = _assignment_assets(
                "XUNJI_ASSETS=" + ",".join(str(item) for item in row.get("assets", [])))
            receipt_assets = [str(item) for item in record.get("assignment_assets", [])]
            if receipt_assets != expected_assets:
                raise RuntimeError(
                    f"assignment asset mismatch for {assignment}: "
                    f"receipt={receipt_assets} state={expected_assets}"
                )
            attempts = row.setdefault("attempts", [])
            if not isinstance(attempts, list):
                attempts = []
                row["attempts"] = attempts
            if not any(str(item.get("attempt_id") or "") == attempt_id
                       for item in attempts if isinstance(item, dict)):
                attempt = {
                    "attempt_id": attempt_id,
                    "agent_id": launched_id,
                    "tool_use_id": str(record.get("tool_use_id") or ""),
                    "session_id": str(record.get("session_id") or ""),
                    "launched_at": stamp,
                    "state": projected_state,
                }
                if projected_state == "returned":
                    attempt["returned_at"] = _iso_timestamp(derived_returned_at) \
                        if derived_returned_at else stamp
                attempts.append(attempt)
            row["current_attempt"] = attempt_id
            row["runtime_agent_id"] = launched_id
            row["updated_at"] = stamp
            current = str(row.get("status") or "").strip().lower()
            if current in NONTERMINAL_ASSIGNMENT_STATUSES:
                row["status"] = "running" if projected_state == "running" else "done"
                row["last_note"] = (
                    f"runtime launch: attempt={attempt_id}"
                    if projected_state == "running"
                    else f"runtime return: attempt={attempt_id}; disposition pending"
                )
            changed = True
            break
    elif hook == "SubagentStop":
        stopped_id = str(record.get("agent_id") or "")
        if not stopped_id:
            return
        for row in rows:
            if not isinstance(row, dict):
                continue
            attempts = row.get("attempts")
            if not isinstance(attempts, list):
                continue
            matched = False
            for attempt in attempts:
                if not isinstance(attempt, dict) or str(attempt.get("agent_id") or "") != stopped_id:
                    continue
                if str(attempt.get("state") or "") != "returned":
                    attempt["state"] = "returned"
                    attempt["returned_at"] = stamp
                    matched = True
            if not matched:
                continue
            row["updated_at"] = stamp
            row["last_seen_at"] = stamp
            current = str(row.get("status") or "").strip().lower()
            if current in NONTERMINAL_ASSIGNMENT_STATUSES:
                row["status"] = "done"
                row["last_note"] = f"runtime return: attempt={stopped_id}; disposition pending"
            changed = True
    if changed:
        _atomic_json(path, data)


def append_hook_event(run_dir: str | Path, event: dict) -> dict:
    run = Path(run_dir).resolve()
    record = normalize_hook_event(run, event)
    with _locked(run):
        events = load_events(run)
        record["seq"] = len(events) + 1
        record["previous_hash"] = str(events[-1].get("receipt_hash") or "") if events else ""
        unsigned = dict(record)
        record["receipt_hash"] = _hash(unsigned)
        path = _event_path(run)
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n")
        try:
            os.chmod(path, 0o600)
        except OSError:
            pass
    needs_projection = (
        (record.get("hook_event_name") == "PostToolUse" and record.get("tool_name") == "Agent")
        or record.get("hook_event_name") == "SubagentStop"
    )
    if needs_projection:
        try:
            with _locked(run):
                _project_agent_lifecycle(run, record)
                _projection_error_path(run).unlink(missing_ok=True)
        except Exception as exc:
            # The immutable receipt remains authoritative. Persist projection
            # drift explicitly so status/check tools and reviewers can diagnose it.
            with _locked(run):
                _atomic_json(_projection_error_path(run), {
                    "schema": "xunji.runtime_projection_error.v1",
                    "recorded_at": _iso_timestamp(time.time()),
                    "event_seq": int(record.get("seq") or 0),
                    "event_hash": str(record.get("receipt_hash") or ""),
                    "error": f"{exc.__class__.__name__}: {exc}",
                })
    return record


def validate_chain(run_dir: str | Path) -> tuple[list[dict], list[str]]:
    events = load_events(run_dir)
    errors: list[str] = []
    previous = ""
    for index, record in enumerate(events, 1):
        claimed = str(record.get("receipt_hash") or "")
        unsigned = dict(record)
        unsigned.pop("receipt_hash", None)
        if record.get("schema") != SCHEMA:
            errors.append(f"event {index}: wrong schema")
        if int(record.get("seq", 0) or 0) != index:
            errors.append(f"event {index}: non-contiguous seq")
        if str(record.get("previous_hash") or "") != previous:
            errors.append(f"event {index}: previous_hash mismatch")
        if claimed != _hash(unsigned):
            errors.append(f"event {index}: receipt_hash mismatch")
        previous = claimed
    return events, errors


def _transcript_has(record: dict) -> bool:
    tool_use_id = str(record.get("tool_use_id") or "")
    transcript = Path(str(record.get("transcript_path") or ""))
    if not tool_use_id or not transcript.is_file():
        return False
    try:
        return tool_use_id in transcript.read_text(encoding="utf-8", errors="replace")
    except Exception:
        return False


def valid_tool_events(
    run_dir: str | Path,
    tool_name: str | None = None,
    *,
    session_id: str = "",
    since: float = 0.0,
) -> list[dict]:
    events, errors = validate_chain(run_dir)
    if errors:
        return []
    return [
        event for event in events
        if event.get("success") is True
        and event.get("hook_event_name") == "PostToolUse"
        and (tool_name is None or event.get("tool_name") == tool_name)
        and (not session_id or str(event.get("session_id") or "") == session_id)
        and (not since or float(event.get("ts") or 0.0) >= since)
        and _transcript_has(event)
    ]


def valid_lifecycle_events(
    run_dir: str | Path,
    *,
    session_id: str = "",
    since: float = 0.0,
) -> list[dict]:
    """Return transcript-backed SubagentStart/SubagentStop hook receipts."""
    events, errors = validate_chain(run_dir)
    if errors:
        return []
    transcript_cache: dict[str, str] = {}
    out: list[dict] = []
    for event in events:
        if event.get("hook_event_name") not in {"SubagentStart", "SubagentStop"}:
            continue
        if session_id and str(event.get("session_id") or "") != session_id:
            continue
        if since and float(event.get("ts") or 0.0) < since:
            continue
        agent_id = str(event.get("agent_id") or "")
        transcript_path = str(event.get("transcript_path") or "")
        if not agent_id or not transcript_path:
            continue
        if transcript_path not in transcript_cache:
            try:
                transcript_cache[transcript_path] = Path(transcript_path).read_text(
                    encoding="utf-8", errors="replace")
            except Exception:
                transcript_cache[transcript_path] = ""
        if agent_id in transcript_cache[transcript_path]:
            out.append(event)
    return out


def denied_tool_events(
    run_dir: str | Path,
    *,
    session_id: str = "",
    since: float = 0.0,
    target_only: bool = False,
) -> list[dict]:
    """Return transcript-backed denials emitted by the trusted PreToolUse hook."""
    events, errors = validate_chain(run_dir)
    if errors:
        return []
    return [
        event for event in events
        if event.get("hook_event_name") == "PreToolUseDenied"
        and event.get("decision") == "deny"
        and (not target_only or event.get("target_action") is True)
        and (not session_id or str(event.get("session_id") or "") == session_id)
        and (not since or float(event.get("ts") or 0.0) >= since)
        and _transcript_has(event)
    ]


def unresolved_target_denials(
    run_dir: str | Path,
    *,
    session_id: str = "",
    since: float = 0.0,
) -> list[dict]:
    """Return target denials without a later successful identical tool input."""
    denied = denied_tool_events(
        run_dir, session_id=session_id, since=since, target_only=True)
    successful = [
        event for event in valid_tool_events(
            run_dir, session_id=session_id, since=since)
        if event.get("target_action") is True
    ]
    unresolved: list[dict] = []
    for denial in denied:
        denial_ts = float(denial.get("ts") or 0.0)
        resolved = any(
            float(event.get("ts") or 0.0) > denial_ts
            and event.get("tool_name") == denial.get("tool_name")
            and event.get("action_sha256") == denial.get("action_sha256")
            for event in successful
        )
        if not resolved:
            unresolved.append(denial)
    return unresolved


def _launch_from_record(event: dict) -> tuple[str, bool, str]:
    launched = str(event.get("launched_agent_id") or "")
    is_async = bool(event.get("agent_is_async"))
    status = str(event.get("agent_status") or "")
    if launched or is_async or status:
        return launched, is_async, status
    return _agent_launch_fields(event.get("response_excerpt") or "")


def agent_attempts(
    run_dir: str | Path,
    *,
    session_id: str = "",
    since: float = 0.0,
) -> list[dict]:
    """Build assignment attempts from launch acknowledgements and SubagentStop."""
    launches = valid_tool_events(run_dir, "Agent", session_id=session_id, since=since)
    lifecycle = valid_lifecycle_events(run_dir, session_id=session_id, since=since)
    stops: dict[str, list[float]] = {}
    starts: dict[str, list[float]] = {}
    for event in lifecycle:
        agent_id = str(event.get("agent_id") or "")
        if not agent_id:
            continue
        if event.get("hook_event_name") == "SubagentStop":
            stops.setdefault(agent_id, []).append(float(event.get("ts") or 0.0))
        elif event.get("hook_event_name") == "SubagentStart":
            starts.setdefault(agent_id, []).append(float(event.get("ts") or 0.0))
    attempts: list[dict] = []
    for event in launches:
        assignment = str(event.get("assignment") or "")
        front = str(event.get("front") or "")
        kind = "assignment"
        if event.get("completion_review"):
            assignment = "XUNJI-COMPLETION"
            front = "REVIEW"
            kind = "completion_review"
        if not assignment or not front:
            continue
        launched_id, is_async, status = _launch_from_record(event)
        attempt_id = launched_id or str(event.get("tool_use_id") or "")
        launched_at = float(event.get("ts") or 0.0)
        returned_at = 0.0
        started_at = 0.0
        if is_async:
            # Agent ids are unique attempt identities. The closest matching
            # Start is causal even when queueing or hook delivery exceeds an
            # arbitrary wall-clock window.
            matching_starts = starts.get(launched_id, [])
            if matching_starts:
                started_at = min(matching_starts, key=lambda ts: abs(ts - launched_at))
            lifecycle_floor = started_at or launched_at
            later_stops = [ts for ts in stops.get(launched_id, []) if ts >= lifecycle_floor]
            returned_at = min(later_stops) if later_stops else 0.0
        else:
            returned_at = launched_at
        attempts.append({
            "attempt_id": attempt_id,
            "assignment": assignment,
            "front": front,
            "agent_id": launched_id,
            "actor_agent_id": str(event.get("agent_id") or ""),
            "session_id": str(event.get("session_id") or ""),
            "tool_use_id": str(event.get("tool_use_id") or ""),
            "launched_at": launched_at,
            "started_at": started_at,
            "returned_at": returned_at,
            "state": "returned" if returned_at else "running",
            "is_async": is_async,
            "launch_status": status,
            "kind": kind,
        })
    return attempts


def agent_actor(run_dir: str | Path, agent_id: str, *, since: float = 0.0) -> dict:
    """Resolve a Claude subagent id to its exact assignment attempt."""
    if not agent_id:
        return {}
    matches = [a for a in agent_attempts(run_dir, since=since) if a.get("agent_id") == agent_id]
    if not matches:
        return {}
    return max(matches, key=lambda item: float(item.get("launched_at") or 0.0))


def agent_asset_activity(run_dir: str | Path, assignment: str) -> dict[str, int]:
    """Count successful target actions by the assignment's concrete assets."""
    run = Path(run_dir)
    try:
        data = json.loads((run / "state" / "assignments.json").read_text(
            encoding="utf-8", errors="replace"))
    except Exception:
        return {}
    row = next((item for item in data.get("assignments", [])
                if isinstance(item, dict) and str(item.get("agent") or "") == assignment), {})
    assets = [str(item).strip().lower() for item in row.get("assets", []) if str(item).strip()]
    if not assets:
        return {}
    attempts = [a for a in agent_attempts(run) if a.get("assignment") == assignment]
    actor_ids = {str(a.get("agent_id") or "") for a in attempts if a.get("agent_id")}
    if not actor_ids:
        return {asset: 0 for asset in assets}
    first_launch = min(float(a.get("launched_at") or 0.0) for a in attempts)
    events = [event for event in valid_tool_events(run, since=first_launch)
              if event.get("target_action") is True
              and str(event.get("agent_id") or "") in actor_ids]
    counts = {asset: 0 for asset in assets}
    for event in events:
        text = _input_text(event).lower()
        for asset in assets:
            host = re.sub(r"^[a-z][a-z0-9+.\-]*://", "", asset).split("/", 1)[0]
            if host and re.search(r"(?<![\w.\-])" + re.escape(host) + r"(?![\w.\-])", text):
                counts[asset] += 1
    return counts


def agent_fanout(run_dir: str | Path, *, session_id: str = "", since: float = 0.0) -> dict:
    attempts = [item for item in agent_attempts(
        run_dir, session_id=session_id, since=since)
                if item.get("kind") == "assignment"]
    assignments = sorted({str(item.get("assignment")) for item in attempts if item.get("assignment")})
    fronts = sorted({str(item.get("front")) for item in attempts if item.get("front")})
    return {
        "assignments": assignments,
        "fronts": fronts,
        "attempts": attempts,
        "running": sorted({str(item.get("assignment")) for item in attempts
                           if item.get("state") == "running"}),
        "returned": sorted({str(item.get("assignment")) for item in attempts
                            if item.get("state") == "returned"}),
        "count": len(assignments),
        "satisfied": len(assignments) >= 2 and len(fronts) >= 2,
    }


def disposition_note_issues(run_dir: str | Path, status: str, note: str) -> list[str]:
    """Validate one terminal disposition against canonical run anchors."""
    run = Path(run_dir)
    status = str(status or "").strip().lower()
    note = str(note or "").strip()
    canonical = "\n".join(
        path.read_text(encoding="utf-8", errors="replace")
        for path in (run / "evidence.md", run / "frontier.md", run / "decisions.md")
        if path.exists()
    )
    anchors = [anchor.upper() for anchor in re.findall(r"\b[EDF]-\d+\b", note, re.I)]
    canonical_anchors = {
        anchor.upper() for anchor in re.findall(r"\b[EDF]-\d+\b", canonical, re.I)
    }
    missing = [anchor for anchor in anchors if anchor not in canonical_anchors]
    issues: list[str] = []
    if status == "merged":
        if not re.search(r"(?i)\b(Evidence|Front|Decision|Refuted|Barrier)\s*[:：]", note):
            issues.append("merged 缺 Evidence/Front/Decision/Refuted/Barrier 标签")
        if not anchors:
            issues.append("merged 缺 canonical E/F/D 锚点")
    elif status in {"blocked", "failed", "abandoned"}:
        if not re.search(r"(?i)\bReason\s*[:：]", note):
            issues.append(f"{status} 缺 Reason:")
        if not re.search(r"(?i)\bFront\s*[:：]\s*F-\d+\b", note):
            issues.append(f"{status} 缺 Front: F-xxx")
    if missing:
        issues.append("canonical 锚点不存在: " + ", ".join(dict.fromkeys(missing)))
    return issues


def agent_disposition(run_dir: str | Path, *, session_id: str = "", since: float = 0.0) -> dict:
    """Require only returned attempts to be explicitly merged or adjudicated."""
    run = Path(run_dir)
    receipts = agent_fanout(run, session_id=session_id, since=since)
    latest_return_ts: dict[str, float] = {}
    for attempt in receipts.get("attempts", []):
        assignment = str(attempt.get("assignment") or "")
        returned_at = float(attempt.get("returned_at") or 0.0)
        if assignment and returned_at:
            latest_return_ts[assignment] = max(latest_return_ts.get(assignment, 0.0), returned_at)
    try:
        data = json.loads((run / "state" / "assignments.json").read_text(
            encoding="utf-8", errors="replace"))
    except Exception:
        data = {}
    rows = {
        str(item.get("agent") or ""): item
        for item in data.get("assignments", []) if isinstance(item, dict)
    } if isinstance(data, dict) and isinstance(data.get("assignments"), list) else {}
    pending: list[str] = []
    for assignment in sorted(latest_return_ts):
        row = rows.get(assignment, {})
        status = str(row.get("status") or "").strip().lower()
        note = str(row.get("last_note") or "").strip()
        updated_raw = str(row.get("updated_at") or row.get("finished_at") or "")
        try:
            updated_at = datetime.fromisoformat(updated_raw.replace("Z", "+00:00")).timestamp()
        except Exception:
            updated_at = 0.0
        if updated_at < latest_return_ts.get(assignment, 0.0):
            pending.append(f"{assignment}: disposition 早于真实 SubagentStop 返回")
            continue
        note_issues = disposition_note_issues(run, status, note)
        if status == "merged":
            pending.extend(f"{assignment}: {issue}" for issue in note_issues)
            if row.get("assets") and row.get("coverage_merge_satisfied") is not True:
                pending.append(f"{assignment}: merged 未通过逐资产动作 + canonical E-entry 验收")
        elif status in {"blocked", "failed", "abandoned"}:
            pending.extend(f"{assignment}: {issue}" for issue in note_issues)
        else:
            pending.append(f"{assignment}: status={status or '(missing)'} 尚未 merge/adjudicate")
    return {
        **receipts,
        "pending": pending,
        "disposition_satisfied": bool(receipts.get("satisfied")) and not pending,
    }


def completion_review_valid(run_dir: str | Path, evidence_index_hash: str) -> bool:
    for event in reversed(valid_tool_events(run_dir, "Agent")):
        if not event.get("completion_review"):
            continue
        if str(event.get("evidence_index_hash") or "") != evidence_index_hash:
            continue
        response = str(event.get("response_excerpt") or "")
        required_checks = (
            "report_parity", "severity_artifacts", "reachable_frontier", "review_ledger",
        )
        if (
            re.search(r"(?i)\bXUNJI_COMPLETION_VERDICT\s*=\s*PASS\b", response)
            and re.search(
                rf"(?i)\bEVIDENCE_INDEX\s*=\s*{re.escape(evidence_index_hash)}\b",
                response,
            )
            and all(check in response.lower() for check in required_checks)
        ):
            return True
    return False


def _peer_review_command_matches(command: str, run_dir: Path) -> bool:
    """Accept only a direct foreground peer_review invocation for this run."""
    if re.search(r"[;&|`$<>\n\r]", command):
        return False
    try:
        argv = shlex.split(command, posix=True)
    except ValueError:
        return False
    if len(argv) < 4 or not re.fullmatch(r"(?:python|python3)(?:\.\d+)?", Path(argv[0]).name):
        return False
    script = Path(argv[1])
    if not script.is_absolute():
        script = Path(__file__).resolve().parents[1] / script
    script = script.resolve()
    expected = (Path(__file__).resolve().parents[1] / "tools" / "peer_review.py").resolve()
    if script != expected:
        return False
    if "--into-run" not in argv or any(
        flag in argv for flag in ("--bundle-only", "--resolve", "--selftest")
    ):
        return False
    for raw in argv[2:]:
        if raw.startswith("-"):
            continue
        candidate = Path(raw)
        if not candidate.is_absolute():
            candidate = Path(__file__).resolve().parents[1] / candidate
        candidate = candidate.resolve()
        if candidate == run_dir.resolve():
            return True
    return False


def review_invocation_valid(
    run_dir: str | Path,
    generated_at: str,
    *,
    receipt_id: str = "",
    bundle_hash: str = "",
) -> bool:
    """Bind a review receipt to the exact foreground command and its output."""
    try:
        parsed = datetime.fromisoformat(generated_at.replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        generated_ts = parsed.timestamp()
    except Exception:
        generated_ts = 0.0
    run = Path(run_dir).resolve()
    receipt_marker = f"XUNJI_REVIEW_RECEIPT={receipt_id}" if receipt_id else ""
    bundle_marker = f"XUNJI_REVIEW_BUNDLE={bundle_hash}" if bundle_hash else ""
    for event in reversed(valid_tool_events(run, "Bash")):
        try:
            tool_input = json.loads(str(event.get("input_excerpt") or "{}"))
        except Exception:
            tool_input = {}
        command = str(tool_input.get("command") or "") if isinstance(tool_input, dict) else ""
        if not _peer_review_command_matches(command, run):
            continue
        response = str(event.get("response_excerpt") or "")
        if receipt_marker and receipt_marker not in response:
            continue
        if bundle_marker and bundle_marker not in response:
            continue
        event_ts = float(event.get("ts") or 0)
        if generated_ts and generated_ts - 5 <= event_ts <= generated_ts + 120:
            return True
    return False


def cron_quiescent(
    run_dir: str | Path,
    *,
    session_id: str = "",
    since: float = 0.0,
) -> tuple[bool, str]:
    events = valid_tool_events(run_dir, session_id=session_id, since=since)
    cron = [event for event in events if str(event.get("tool_name") or "").startswith("Cron")]
    listed = [event for event in cron if event.get("tool_name") == "CronList"]
    if not listed:
        return False, "missing successful CronList receipt"
    latest_list = listed[-1]
    last_mutation = max(
        (int(event.get("seq", 0) or 0) for event in cron if event.get("tool_name") in {"CronCreate", "CronDelete"}),
        default=0,
    )
    if int(latest_list.get("seq", 0) or 0) < last_mutation:
        return False, "CronList receipt predates latest CronCreate/CronDelete"

    active: dict[str, dict] = {}
    for event in cron:
        tool = event.get("tool_name")
        job = str(event.get("job_id") or "")
        if tool == "CronCreate" and event.get("run_mentioned") and job:
            active[job] = event
        elif tool == "CronDelete" and job:
            active.pop(job, None)
    response = str(latest_list.get("response_excerpt") or "").lower()
    run_name = Path(run_dir).name.lower()
    if active:
        return False, "active run Cron job receipt(s): " + ", ".join(sorted(active))
    listed_run_jobs = [str(job) for job in latest_list.get("listed_run_job_ids", []) if job]
    if listed_run_jobs:
        return False, "latest CronList contains active run job(s): " + ", ".join(listed_run_jobs)
    if run_name and run_name in response:
        return False, "latest CronList still mentions the active run"
    return True, "latest successful CronList proves no active run job"


def cron_delete_allowed(
    run_dir: str | Path,
    job_id: str,
    *,
    session_id: str = "",
    since: float = 0.0,
) -> tuple[bool, str]:
    """Bind CronDelete to a run job observed by a current CronList/Create receipt."""
    if not job_id:
        return False, "CronDelete has no parseable job id"
    events = valid_tool_events(run_dir, session_id=session_id, since=since)
    cron = [event for event in events if str(event.get("tool_name") or "").startswith("Cron")]
    listed = [event for event in cron if event.get("tool_name") == "CronList"]
    if not listed:
        return False, "missing successful current-turn CronList receipt"
    latest = listed[-1]
    observed = {str(item) for item in latest.get("listed_run_job_ids", []) if item}
    for event in cron:
        if event.get("tool_name") == "CronCreate" and event.get("run_mentioned"):
            observed.update(str(item) for item in event.get("job_ids", []) if item)
    if job_id not in observed:
        return False, f"job {job_id} was not observed as a task for run {Path(run_dir).name}"
    return True, "CronDelete is bound to an observed current-run job"


def _write_transcript(path: Path, *tool_ids: str) -> None:
    path.write_text("\n".join(json.dumps({"tool_use_id": item}) for item in tool_ids), encoding="utf-8")


def _selftest() -> int:
    from unittest import mock

    run = Path(tempfile.mkdtemp()) / "run"
    (run / "state").mkdir(parents=True)
    transcript = run.parent / "transcript.jsonl"
    ids = (
        "tool-agent-1", "tool-agent-2", "tool-list-1", "tool-create-1",
        "tool-list-active", "tool-delete-1", "tool-list-2", "tool-review-1",
        "tool-completion-bad", "tool-completion-good", "tool-target-denied",
        "tool-target-failed", "tool-target-other", "tool-target-success",
    )
    _write_transcript(transcript, *ids)

    def event(tool: str, tool_id: str, tool_input: dict, response: object) -> dict:
        return {
            "hook_event_name": "PostToolUse", "session_id": "s1",
            "transcript_path": str(transcript), "tool_name": tool,
            "tool_use_id": tool_id, "tool_input": tool_input,
            "tool_response": response,
        }

    append_hook_event(run, event("Agent", ids[0], {
        "prompt": "XUNJI_ASSIGNMENT=A-web-001 XUNJI_FRONT=F-001",
    }, {"result": "candidate done"}))
    append_hook_event(run, event("Agent", ids[1], {
        "prompt": "XUNJI_ASSIGNMENT=A-auth-001 XUNJI_FRONT=F-002",
    }, {"result": "candidate done"}))
    (run / "frontier.md").write_text("# Frontier\n## Open Fronts\n### F-001\n- Status: open\n### F-002\n- Status: open\n",
                                      encoding="utf-8")
    (run / "evidence.md").write_text("# Evidence\n## E-001\n", encoding="utf-8")
    (run / "state" / "assignments.json").write_text(json.dumps({"assignments": [
        {"agent": "A-web-001", "front": "F-001", "status": "merged",
         "updated_at": datetime.now(timezone.utc).isoformat(),
         "last_note": "Evidence: E-001 merged for Front: F-001"},
        {"agent": "A-auth-001", "front": "F-002", "status": "done",
         "updated_at": datetime.now(timezone.utc).isoformat(),
         "last_note": "candidate returned"},
    ]}), encoding="utf-8")
    disposition_before = agent_disposition(run)
    data = json.loads((run / "state" / "assignments.json").read_text(encoding="utf-8"))
    data["assignments"][1].update({
        "status": "blocked", "last_note": "Reason: no credential; Front: F-002 remains open",
        "updated_at": datetime.now(timezone.utc).isoformat(),
    })
    (run / "state" / "assignments.json").write_text(json.dumps(data), encoding="utf-8")
    disposition_after = agent_disposition(run)
    missing_anchor_issues = disposition_note_issues(
        run, "blocked", "Reason: no credential; Front: F-002; Evidence: E-404")
    append_hook_event(run, event("CronList", ids[2], {}, {"tasks": []}))
    before, _ = cron_quiescent(run)
    append_hook_event(run, event("CronCreate", ids[3], {"prompt": f"/loop {run.name}"}, {"id": "deadbeef"}))
    active, _ = cron_quiescent(run)
    append_hook_event(run, event("CronList", ids[4], {}, {
        "tasks": [{"id": "deadbeef", "prompt": f"/loop {run.name}"}],
    }))
    delete_ok, _ = cron_delete_allowed(run, "deadbeef")
    prefix_delete, _ = cron_delete_allowed(run, "deadbe")
    wrong_delete, _ = cron_delete_allowed(run, "otherjob")
    append_hook_event(run, event("CronDelete", ids[5], {"id": "deadbeef"}, {"deleted": True}))
    stale, _ = cron_quiescent(run)
    append_hook_event(run, event("CronList", ids[6], {}, {"tasks": []}))
    after, _ = cron_quiescent(run)
    current_turn, _ = cron_quiescent(run, session_id="different-session", since=time.time() - 30)
    review_generated = datetime.now(timezone.utc).isoformat()
    review_receipt = "c" * 64
    review_bundle = "d" * 40
    append_hook_event(run, event("Bash", ids[7], {
        "command": f"python3 tools/peer_review.py {run} --into-run",
    }, {"stdout": (
        f"XUNJI_REVIEW_RECEIPT={review_receipt}\n"
        f"XUNJI_REVIEW_BUNDLE={review_bundle}\n## Verdict: PASS"
    )}))
    review_ok = review_invocation_valid(
        run, review_generated, receipt_id=review_receipt, bundle_hash=review_bundle)
    wrong_marker_review = review_invocation_valid(
        run, review_generated, receipt_id="e" * 64, bundle_hash=review_bundle)
    stale_review = review_invocation_valid(
        run, "2000-01-01T00:00:00+00:00",
        receipt_id=review_receipt, bundle_hash=review_bundle)
    completion_hash = "b" * 40
    completion_prompt = (
        f"XUNJI_COMPLETION_REVIEW EVIDENCE_INDEX={completion_hash} "
        "CHECKS=report_parity,severity_artifacts,reachable_frontier,review_ledger")
    append_hook_event(run, event("Agent", ids[8], {"prompt": completion_prompt}, {
        "result": "PASS",
    }))
    weak_completion = completion_review_valid(run, completion_hash)
    append_hook_event(run, event("Agent", ids[9], {"prompt": completion_prompt}, {
        "result": f"XUNJI_COMPLETION_VERDICT=PASS EVIDENCE_INDEX={completion_hash} "
                  "CHECKS=report_parity,severity_artifacts,reachable_frontier,review_ledger",
    }))
    structured_completion = completion_review_valid(run, completion_hash)
    append_hook_event(run, {
        "hook_event_name": "PreToolUseDenied", "session_id": "s1",
        "transcript_path": str(transcript), "tool_name": "Bash",
        "tool_use_id": ids[10],
        "tool_input": {"command": "python3 tools/probe.py GET https://example.test"},
        "xunji_decision": "deny", "xunji_reason": "Agent Board required",
        "xunji_target_action": True,
    })
    denied_target = denied_tool_events(run, session_id="s1", target_only=True)
    unresolved_before = unresolved_target_denials(run, session_id="s1")
    failed_target = event("Bash", ids[11], {
        "command": "python3 tools/probe.py GET https://example.test",
        "description": "first retry with changed metadata",
    }, {"error": "controlled failure"})
    failed_target["hook_event_name"] = "PostToolUseFailure"
    failed_target["xunji_target_action"] = True
    append_hook_event(run, failed_target)
    unresolved_after_failure = unresolved_target_denials(run, session_id="s1")
    other_target = event("Bash", ids[12], {
        "command": "python3 tools/probe.py GET https://other.example.test",
    }, {"stdout": "different command success"})
    other_target["xunji_target_action"] = True
    append_hook_event(run, other_target)
    unresolved_after_other = unresolved_target_denials(run, session_id="s1")
    successful_target = event("Bash", ids[13], {
        "command": "python3 tools/probe.py GET https://example.test",
        "description": "successful retry with different metadata",
    }, {"stdout": "controlled success"})
    successful_target["xunji_target_action"] = True
    append_hook_event(run, successful_target)
    unresolved_after_success = unresolved_target_denials(run, session_id="s1")
    events, chain_errors = validate_chain(run)
    tampered = run.parent / "tampered"
    (tampered / "state").mkdir(parents=True)
    tampered_lines = _event_path(run).read_text(encoding="utf-8").splitlines()
    tampered_first = json.loads(tampered_lines[0])
    tampered_first["response_excerpt"] = "forged candidate"
    tampered_lines[0] = json.dumps(tampered_first, ensure_ascii=False, sort_keys=True)
    _event_path(tampered).write_text("\n".join(tampered_lines) + "\n", encoding="utf-8")
    tampered_fanout = agent_fanout(tampered)

    async_run = run.parent / "async-run"
    (async_run / "state").mkdir(parents=True)
    async_transcript = run.parent / "async-transcript.jsonl"
    _write_transcript(async_transcript, "async-launch-1", "async-launch-2", "child-action-1",
                      "child-agent-1", "child-agent-2")
    (async_run / "frontier.md").write_text(
        "# Frontier\n## Open Fronts\n### F-001\n- Status: open\n"
        "### F-002\n- Status: open\n", encoding="utf-8")
    (async_run / "evidence.md").write_text("# Evidence\n", encoding="utf-8")
    (async_run / "state" / "assignments.json").write_text(json.dumps({"assignments": [
        {"agent": "A-async-001", "front": "F-001", "status": "assigned",
         "assets": ["a.example"]},
        {"agent": "A-async-002", "front": "F-002", "status": "assigned",
         "assets": ["b.example"]},
    ]}), encoding="utf-8")

    def async_launch(tool_id: str, assignment: str, front: str, asset: str,
                     child_id: str) -> None:
        append_hook_event(async_run, {
            "hook_event_name": "PostToolUse", "session_id": "async-session",
            "transcript_path": str(async_transcript), "tool_name": "Agent",
            "tool_use_id": tool_id,
            "tool_input": {"prompt": (
                f"XUNJI_ASSIGNMENT={assignment} XUNJI_FRONT={front} XUNJI_ASSETS={asset}"
            )},
            "tool_response": {"agentId": child_id, "isAsync": True,
                              "status": "async_launched"},
        })

    async_launch("async-launch-1", "A-async-001", "F-001", "a.example", "child-agent-1")
    async_launch("async-launch-2", "A-async-002", "F-002", "b.example", "child-agent-2")
    async_running_fanout = agent_fanout(async_run)
    async_running_disposition = agent_disposition(async_run)
    async_state = json.loads((async_run / "state" / "assignments.json").read_text(encoding="utf-8"))
    append_hook_event(async_run, {
        "hook_event_name": "PostToolUse", "session_id": "async-session",
        "transcript_path": str(async_transcript), "tool_name": "Bash",
        "tool_use_id": "child-action-1", "agent_id": "child-agent-1",
        "tool_input": {"command": "python3 tools/probe.py GET https://a.example"},
        "tool_response": {"stdout": "ok"}, "xunji_target_action": True,
    })
    async_activity = agent_asset_activity(async_run, "A-async-001")
    append_hook_event(async_run, {
        "hook_event_name": "SubagentStop", "session_id": "async-session",
        "transcript_path": str(async_transcript), "agent_id": "child-agent-1",
        "agent_type": "general-purpose",
    })
    async_after_stop = agent_disposition(async_run)
    async_state_after_stop = json.loads(
        (async_run / "state" / "assignments.json").read_text(encoding="utf-8"))
    async_state_after_stop["assignments"][0].update({
        "status": "blocked", "last_note": "Reason: auth barrier; Front: F-001",
        "updated_at": datetime.now(timezone.utc).isoformat(),
    })
    (async_run / "state" / "assignments.json").write_text(
        json.dumps(async_state_after_stop), encoding="utf-8")
    async_one_return_disposed = agent_disposition(async_run)

    race_run = run.parent / "stop-before-launch-run"
    (race_run / "state").mkdir(parents=True)
    race_transcript = run.parent / "stop-before-launch-transcript.jsonl"
    _write_transcript(race_transcript, "race-launch", "race-child")
    (race_run / "state" / "assignments.json").write_text(json.dumps({"assignments": [
        {"agent": "A-race-001", "front": "F-001", "status": "assigned"},
    ]}), encoding="utf-8")
    for hook in ("SubagentStart", "SubagentStop"):
        append_hook_event(race_run, {
            "hook_event_name": hook, "session_id": "race-session",
            "transcript_path": str(race_transcript), "agent_id": "race-child",
            "agent_type": "general-purpose",
        })
    append_hook_event(race_run, {
        "hook_event_name": "PostToolUse", "session_id": "race-session",
        "transcript_path": str(race_transcript), "tool_name": "Agent",
        "tool_use_id": "race-launch",
        "tool_input": {"prompt": "XUNJI_ASSIGNMENT=A-race-001 XUNJI_FRONT=F-001"},
        "tool_response": {"agentId": "race-child", "isAsync": True,
                          "status": "async_launched"},
    })
    race_attempts = agent_attempts(race_run)
    race_state = json.loads(
        (race_run / "state" / "assignments.json").read_text(encoding="utf-8"))

    delayed_run = run.parent / "delayed-stop-before-launch-run"
    (delayed_run / "state").mkdir(parents=True)
    delayed_transcript = run.parent / "delayed-stop-before-launch-transcript.jsonl"
    _write_transcript(delayed_transcript, "delayed-launch", "delayed-child")
    (delayed_run / "state" / "assignments.json").write_text(json.dumps({"assignments": [
        {"agent": "A-delayed-001", "front": "F-001", "status": "assigned"},
    ]}), encoding="utf-8")
    with mock.patch.object(time, "time", side_effect=[100.0, 105.0, 140.0]):
        for hook in ("SubagentStart", "SubagentStop"):
            append_hook_event(delayed_run, {
                "hook_event_name": hook, "session_id": "delayed-session",
                "transcript_path": str(delayed_transcript), "agent_id": "delayed-child",
                "agent_type": "general-purpose",
            })
        append_hook_event(delayed_run, {
            "hook_event_name": "PostToolUse", "session_id": "delayed-session",
            "transcript_path": str(delayed_transcript), "tool_name": "Agent",
            "tool_use_id": "delayed-launch",
            "tool_input": {
                "prompt": "XUNJI_ASSIGNMENT=A-delayed-001 XUNJI_FRONT=F-001"},
            "tool_response": {"agentId": "delayed-child", "isAsync": True,
                              "status": "async_launched"},
        })
    delayed_attempts = agent_attempts(delayed_run)

    projection_error_run = run.parent / "projection-error-run"
    (projection_error_run / "state").mkdir(parents=True)
    projection_error_transcript = run.parent / "projection-error-transcript.jsonl"
    _write_transcript(projection_error_transcript, "projection-error-launch")
    (projection_error_run / "state" / "assignments.json").write_text(
        "{broken", encoding="utf-8")
    append_hook_event(projection_error_run, {
        "hook_event_name": "PostToolUse", "session_id": "projection-error-session",
        "transcript_path": str(projection_error_transcript), "tool_name": "Agent",
        "tool_use_id": "projection-error-launch",
        "tool_input": {"prompt": "XUNJI_ASSIGNMENT=A-error-001 XUNJI_FRONT=F-001"},
        "tool_response": {"agentId": "projection-error-child", "isAsync": True,
                          "status": "async_launched"},
    })
    projection_error = json.loads(
        _projection_error_path(projection_error_run).read_text(encoding="utf-8"))
    asset_error_run = run.parent / "projection-asset-error-run"
    (asset_error_run / "state").mkdir(parents=True)
    asset_error_transcript = run.parent / "projection-asset-error-transcript.jsonl"
    _write_transcript(asset_error_transcript, "projection-asset-error-launch")
    (asset_error_run / "state" / "assignments.json").write_text(json.dumps({
        "schema": 2,
        "assignments": [{"agent": "A-asset-error-001", "front": "F-001",
                         "status": "assigned", "assets": ["a.example"]}],
    }), encoding="utf-8")
    append_hook_event(asset_error_run, {
        "hook_event_name": "PostToolUse", "session_id": "projection-asset-error-session",
        "transcript_path": str(asset_error_transcript), "tool_name": "Agent",
        "tool_use_id": "projection-asset-error-launch",
        "tool_input": {"prompt": (
            "XUNJI_ASSIGNMENT=A-asset-error-001 XUNJI_FRONT=F-001 "
            "XUNJI_ASSETS=b.example")},
        "tool_response": {"agentId": "projection-asset-error-child", "isAsync": True,
                          "status": "async_launched"},
    })
    asset_projection_error = json.loads(
        _projection_error_path(asset_error_run).read_text(encoding="utf-8"))
    checks = [
        ("hash chain validates", not chain_errors and len(events) == 14),
        ("two real Agent receipts satisfy fanout", agent_fanout(run)["satisfied"]),
        ("done Agent remains unmerged", not disposition_before["disposition_satisfied"]),
        ("anchored merged/blocked dispositions satisfy", disposition_after["disposition_satisfied"]),
        ("missing canonical anchor is reported precisely",
         missing_anchor_issues == ["canonical 锚点不存在: E-404"]),
        ("CronList with no jobs is quiescent", before),
        ("created run job is active", not active),
        ("CronDelete binds to listed run job", delete_ok),
        ("CronDelete rejects response-substring job prefix", not prefix_delete),
        ("CronDelete rejects unlisted job", not wrong_delete),
        ("post-delete CronList is still required", not stale),
        ("post-delete CronList proves quiescence", after),
        ("old-session CronList cannot satisfy current turn", not current_turn),
        ("foreground review receipt is time-bound", review_ok),
        ("review receipt requires exact output marker", not wrong_marker_review),
        ("shell-decorated review command is rejected", not _peer_review_command_matches(
            f"echo fake; python3 tools/peer_review.py {run} --into-run", run)),
        ("unrelated later invocation cannot validate stale review", not stale_review),
        ("bare PASS cannot satisfy completion review", not weak_completion),
        ("structured evidence-bound completion receipt passes", structured_completion),
        ("tampered receipt chain cannot satisfy Agent fanout", not tampered_fanout["satisfied"]),
        ("async launch receipts satisfy fanout without pretending return",
         async_running_fanout["satisfied"]
         and set(async_running_fanout["running"]) == {"A-async-001", "A-async-002"}
         and async_running_fanout["returned"] == []),
        ("running async Agents do not create post-return disposition deadlock",
         async_running_disposition["disposition_satisfied"]),
        ("async launch projects assignments to running attempts",
         all(item.get("status") == "running" and item.get("attempts")
             for item in async_state["assignments"])),
        ("child target receipt is attributed to its assigned asset",
         async_activity.get("a.example") == 1),
        ("SubagentStop alone creates a disposition obligation",
         not async_after_stop["disposition_satisfied"]
         and any("A-async-001" in item for item in async_after_stop["pending"])),
        ("returned assignment may be adjudicated while peer Agent is still running",
         async_one_return_disposed["disposition_satisfied"]
         and async_one_return_disposed["running"] == ["A-async-002"]),
        ("SubagentStop recorded before launch acknowledgement still closes the attempt",
         race_attempts and race_attempts[0]["state"] == "returned"
         and race_state["assignments"][0]["status"] == "done"),
        ("delayed reverse lifecycle events match by unique agent id without time window",
         delayed_attempts and delayed_attempts[0]["state"] == "returned"),
        ("runtime projection failure is persisted instead of swallowed",
         projection_error.get("event_seq") == 1
         and "cannot parse assignments.json" in projection_error.get("error", "")),
        ("runtime projection revalidates the exact assignment asset package",
         "assignment asset mismatch" in asset_projection_error.get("error", "")),
        ("target denial is transcript-backed", len(denied_target) == 1),
        ("target denial remains unresolved without a retry", len(unresolved_before) == 1),
        ("failed identical retry does not resolve denial", len(unresolved_after_failure) == 1),
        ("different successful command does not resolve denial", len(unresolved_after_other) == 1),
        ("successful same command resolves despite description drift", not unresolved_after_success),
        ("Bash environment participates in action hash", _action_hash(
            "Bash", {"command": "probe", "env": {"TOKEN": "one"}}) != _action_hash(
            "Bash", {"command": "probe", "env": {"TOKEN": "two"}})),
        ("WebFetch extended parameters participate in action hash", _action_hash(
            "WebFetch", {"url": "https://example.test", "prompt": "inspect", "headers": {"X": "1"}})
            != _action_hash(
                "WebFetch", {"url": "https://example.test", "prompt": "inspect", "headers": {"X": "2"}})),
    ]
    bad = [name for name, ok in checks if not ok]
    for name, ok in checks:
        print(("ok   " if ok else "FAIL ") + name)
    print("runtime_receipts selftest " + ("passed" if not bad else f"FAILED ({len(bad)})"))
    return 0 if not bad else 1


def main() -> int:
    parser = argparse.ArgumentParser(description="validate Xunji hook-derived runtime receipts")
    parser.add_argument("run_dir", nargs="?")
    parser.add_argument("--selftest", action="store_true")
    args = parser.parse_args()
    if args.selftest:
        return _selftest()
    if not args.run_dir:
        parser.error("run_dir is required")
    _, errors = validate_chain(args.run_dir)
    fanout = agent_fanout(args.run_dir)
    cron_ok, cron_note = cron_quiescent(args.run_dir)
    print(json.dumps({"errors": errors, "fanout": fanout, "cron_quiescent": cron_ok,
                      "cron_note": cron_note}, ensure_ascii=False, indent=2))
    return 1 if errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
