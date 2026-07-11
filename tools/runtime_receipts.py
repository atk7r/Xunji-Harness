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
    return "\n".join(str(tool_input.get(key) or "") for key in (
        "prompt", "description", "command", "job_id", "id",
    ))


def _assignment_fields(text: str) -> tuple[str, str]:
    assignment = re.search(r"(?i)\bXUNJI_ASSIGNMENT\s*=\s*(A-[A-Za-z0-9._-]+)", text)
    front = re.search(r"(?i)\bXUNJI_FRONT\s*=\s*(F-\d+)", text)
    return (
        assignment.group(1) if assignment else "",
        front.group(1).upper() if front else "",
    )


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
        "input_excerpt": _excerpt(event.get("tool_input") or {}),
        "input_sha256": _hash(event.get("tool_input") or {}),
        "action_sha256": _action_hash(tool, event.get("tool_input") or {}),
        "response_sha256": _hash(response or {}),
        "response_excerpt": _excerpt(response),
        "agent_id": str(event.get("agent_id") or ""),
        "agent_type": str(event.get("agent_type") or ""),
        "job_id": _job_id(response) or _job_id(event.get("tool_input") or {}),
        "job_ids": _job_ids(response) or _job_ids(event.get("tool_input") or {}),
        "listed_run_job_ids": _run_job_ids(response, run.name) if tool == "CronList" else [],
        "completion_review": "XUNJI_COMPLETION_REVIEW" in input_text.upper(),
        "evidence_index_hash": _evidence_hash(input_text),
        "run_mentioned": run.name.lower() in input_text.lower(),
    }
    return record


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


def agent_fanout(run_dir: str | Path, *, session_id: str = "", since: float = 0.0) -> dict:
    events = valid_tool_events(run_dir, "Agent", session_id=session_id, since=since)
    assignments = sorted({str(event.get("assignment")) for event in events if event.get("assignment")})
    fronts = sorted({str(event.get("front")) for event in events if event.get("front")})
    return {
        "assignments": assignments,
        "fronts": fronts,
        "count": len(assignments),
        "satisfied": len(assignments) >= 2 and len(fronts) >= 2,
    }


def agent_disposition(run_dir: str | Path, *, session_id: str = "", since: float = 0.0) -> dict:
    """Require every observed assignment to be explicitly merged or adjudicated."""
    run = Path(run_dir)
    receipts = agent_fanout(run, session_id=session_id, since=since)
    agent_events = valid_tool_events(run, "Agent", session_id=session_id, since=since)
    latest_receipt_ts: dict[str, float] = {}
    for event in agent_events:
        assignment = str(event.get("assignment") or "")
        if assignment:
            latest_receipt_ts[assignment] = max(
                latest_receipt_ts.get(assignment, 0.0), float(event.get("ts") or 0.0))
    try:
        data = json.loads((run / "state" / "assignments.json").read_text(
            encoding="utf-8", errors="replace"))
    except Exception:
        data = {}
    rows = {
        str(item.get("agent") or ""): item
        for item in data.get("assignments", []) if isinstance(item, dict)
    } if isinstance(data, dict) and isinstance(data.get("assignments"), list) else {}
    canonical = "\n".join(
        path.read_text(encoding="utf-8", errors="replace")
        for path in (run / "evidence.md", run / "frontier.md", run / "decisions.md")
        if path.exists()
    )
    pending: list[str] = []
    for assignment in receipts.get("assignments", []):
        row = rows.get(assignment, {})
        status = str(row.get("status") or "").strip().lower()
        note = str(row.get("last_note") or "").strip()
        updated_raw = str(row.get("updated_at") or row.get("finished_at") or "")
        try:
            updated_at = datetime.fromisoformat(updated_raw.replace("Z", "+00:00")).timestamp()
        except Exception:
            updated_at = 0.0
        if updated_at < latest_receipt_ts.get(assignment, 0.0):
            pending.append(f"{assignment}: disposition 早于本轮 Agent 返回")
            continue
        anchors = re.findall(r"\b[EDF]-\d+\b", note, re.I)
        anchors_exist = bool(anchors) and all(anchor.upper() in canonical.upper() for anchor in anchors)
        if status == "merged":
            if not re.search(r"(?i)\b(Evidence|Front|Decision|Refuted|Barrier)\s*[:：]", note) or not anchors_exist:
                pending.append(f"{assignment}: merged 缺 canonical E/F/D 处置锚点")
        elif status in {"blocked", "failed", "abandoned"}:
            if not re.search(r"(?i)\bReason\s*[:：]", note) or not re.search(r"\bF-\d+\b", note, re.I) or not anchors_exist:
                pending.append(f"{assignment}: {status} 缺 Reason + canonical Front 锚点")
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
    checks = [
        ("hash chain validates", not chain_errors and len(events) == 14),
        ("two real Agent receipts satisfy fanout", agent_fanout(run)["satisfied"]),
        ("done Agent remains unmerged", not disposition_before["disposition_satisfied"]),
        ("anchored merged/blocked dispositions satisfy", disposition_after["disposition_satisfied"]),
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
