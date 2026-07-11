#!/usr/bin/env python3
"""Rebuild frozen review artifacts from the current worktree."""
from __future__ import annotations

import json
import hashlib
import re
import shutil
import subprocess
import sys
from pathlib import Path


HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
RUNTIME = HERE / "runtime-scope"
CLOSURE = HERE / "closure-scope"
TURN = HERE / "turn-scope"
RECEIPTS = HERE / "receipts-scope"
DOCS = HERE / "docs-scope"
LIVE = HERE / "live-scope"


def run(*args: str, allow_diff: bool = False) -> str:
    proc = subprocess.run(
        args, cwd=ROOT, text=True, capture_output=True, timeout=180,
    )
    allowed = {0, 1} if allow_diff else {0}
    if proc.returncode not in allowed:
        raise RuntimeError(f"{' '.join(args)} failed: {proc.stderr}")
    return proc.stdout


def run_combined(*args: str) -> str:
    proc = subprocess.run(
        args, cwd=ROOT, text=True, capture_output=True, timeout=180,
    )
    if proc.returncode != 0:
        raise RuntimeError(f"{' '.join(args)} failed: {proc.stdout}\n{proc.stderr}")
    return proc.stdout + proc.stderr


def tracked_diff(paths: list[str]) -> str:
    return run("git", "diff", "-U0", "--", *paths)


def new_file_diff(path: str) -> str:
    return run("git", "diff", "--no-index", "-U0", "--", "/dev/null", path,
               allow_diff=True)


def write(name: str, content: str) -> None:
    (HERE / name).write_text(content, encoding="utf-8")


def split_hunks(content: str, prefix: str, *, target_bytes: int = 18_000) -> list[str]:
    lines = content.splitlines(keepends=True)
    first_hunk = next((idx for idx, line in enumerate(lines) if line.startswith("@@ ")), None)
    if first_hunk is None:
        raise RuntimeError(f"{prefix}: diff contains no hunks")
    header = lines[:first_hunk]
    starts = [idx for idx, line in enumerate(lines) if line.startswith("@@ ")]
    hunks = [lines[start:(starts[idx + 1] if idx + 1 < len(starts) else len(lines))]
             for idx, start in enumerate(starts)]
    chunks: list[str] = []
    current = list(header)
    for hunk in hunks:
        candidate = "".join(current + hunk)
        if len(candidate.encode("utf-8")) > target_bytes and len(current) > len(header):
            chunks.append("".join(current))
            current = list(header)
        current.extend(hunk)
    if len(current) > len(header):
        chunks.append("".join(current))
    for old in HERE.glob(prefix + "-*.diff"):
        old.unlink()
    names: list[str] = []
    for idx, chunk in enumerate(chunks, 1):
        name = f"{prefix}-{idx:02d}.diff"
        write(name, chunk)
        names.append(name)
    return names


def numbered_chunks(source: Path, stem: str, *, chunk_lines: int) -> list[str]:
    lines = source.read_text(encoding="utf-8", errors="replace").splitlines()
    for old in HERE.glob(stem + ".lines-*.txt"):
        old.unlink()
    names: list[str] = []
    for start in range(0, len(lines), chunk_lines):
        end = min(start + chunk_lines, len(lines))
        suffix = f"{start + 1:03d}-{'end' if end == len(lines) else f'{end:03d}'}"
        name = f"{stem}.lines-{suffix}.txt"
        body = "".join(f"{idx:6d}\t{lines[idx - 1]}\n" for idx in range(start + 1, end + 1))
        write(name, body)
        names.append(name)
    return names


def compact_observation(value: dict, *, digest: bool = False) -> dict:
    observations = value.get("observations", {}) if isinstance(value, dict) else {}
    denials = {
        key: item.get("hookSpecificOutput", {}).get("permissionDecisionReason", "")
        for key, item in observations.items()
        if isinstance(item, dict)
        and item.get("hookSpecificOutput", {}).get("permissionDecision") == "deny"
    }
    events = []
    for event in value.get("runtime_events", []) if isinstance(value, dict) else []:
        if not isinstance(event, dict):
            continue
        keys = (
            "seq", "tool_name", "tool_use_id", "session_id", "success",
            "assignment", "front", "job_id", "completion_review",
            "evidence_index_hash", "input_sha256", "action_sha256", "response_sha256",
            "previous_hash", "receipt_hash",
            "decision", "decision_reason", "target_action",
        )
        events.append({key: event.get(key) for key in keys})
    if digest:
        encoded = json.dumps(events, ensure_ascii=False, sort_keys=True).encode("utf-8")
        return {
            "schema": "xunji.runtime_observation.replica-digest.v1",
            "checks": value.get("checks", {}),
            "denials": denials,
            "runtime_chain": observations.get("runtime_chain", {}),
            "event_count": len(events),
            "event_digest_sha256": hashlib.sha256(encoded).hexdigest(),
            "first_receipt_hash": events[0].get("receipt_hash") if events else "",
            "last_receipt_hash": events[-1].get("receipt_hash") if events else "",
            "agent_after_disposition": observations.get("agent_after_disposition", {}),
            "cron_quiescent": observations.get("cron_quiescent", []),
            "structured_completion_accepted": observations.get(
                "structured_completion_accepted"),
        }
    return {
        "schema": "xunji.runtime_observation.summary.v1",
        "checks": value.get("checks", {}),
        "denials": denials,
        "runtime_chain": observations.get("runtime_chain", {}),
        "agent_before_disposition": observations.get("agent_before_disposition", {}),
        "agent_after_disposition": observations.get("agent_after_disposition", {}),
        "cron_quiescent": observations.get("cron_quiescent", []),
        "run_status": observations.get("run_status", {}),
        "bare_pass_rejected": observations.get("bare_pass_rejected"),
        "structured_completion_accepted": observations.get("structured_completion_accepted"),
        "runtime_events": events,
    }


def compact_live_smoke(value: dict) -> dict:
    cases = {}
    for name, item in value.get("cases", {}).items():
        if not isinstance(item, dict):
            continue
        cases[name] = {key: item.get(key) for key in (
            "returncode", "record_count", "tool_use_seen", "reason_seen",
            "pretool_denial_seen", "pretool_allow_seen", "contract_mode",
            "expected_decision", "stop_truth_block_seen", "sentinel_created",
            "read_marker_seen", "blocked_effect_observed", "final_false_claim_seen",
            "denial_envelope_seen",
            "passed",
        )}
        successful_hooks = [
            event for event in item.get("hook_events", [])
            if isinstance(event, dict)
            and event.get("outcome") == "success"
            and event.get("hook_event") in {"PreToolUse", "Stop"}
        ]
        cases[name]["hook_event_count"] = len(successful_hooks)
        cases[name]["hook_decisions"] = list(dict.fromkeys(
            str(event.get("output") or "").strip()[:800]
            for event in successful_hooks if str(event.get("output") or "").strip()
        ))
    return {
        "schema": "xunji.live_claude_smoke.summary.v1",
        "claude_version": value.get("claude_version"),
        "hook_command": value.get("hook_command"),
        "output_gate_command": value.get("output_gate_command"),
        "cases": cases,
    }


def compact_live_fanout(value: dict) -> dict:
    hooks = [item for item in value.get("hook_events", []) if isinstance(item, dict)]
    successful = [item for item in hooks if item.get("outcome") == "success"]
    outputs = [str(item.get("output") or "") for item in successful]
    assignments = value.get("assignments", {}).get("assignments", [])
    return {
        "schema": "xunji.live_fanout_flow.summary.v1",
        "claude_version": value.get("claude_version"),
        "passed": value.get("passed"),
        "returncode": value.get("returncode"),
        "record_count": value.get("record_count"),
        "disposition_denial_seen": value.get("disposition_denial_seen"),
        "post_disposition_probe_allowed": value.get("post_disposition_probe_allowed"),
        "stop_hook_events": value.get("stop_hook_events"),
        "final_coda_seen": value.get("final_coda_seen"),
        "sentinel_created": value.get("sentinel_created"),
        "sentinel_value": value.get("sentinel_value"),
        "fanout": value.get("fanout"),
        "disposition": value.get("disposition"),
        "runtime_chain": value.get("runtime_chain"),
        "unresolved_target_denials": value.get("unresolved_target_denials"),
        "protected_non_target_receipts": value.get("protected_non_target_receipts"),
        "operator_contract_preserved": value.get("operator_contract_preserved"),
        "assignment_statuses": {
            str(item.get("agent") or ""): {
                "front": item.get("front"),
                "status": item.get("status"),
                "last_note": item.get("last_note"),
            }
            for item in assignments if isinstance(item, dict)
        },
        "hook_counts": {
            "agent_pretool_allowed": sum(
                1 for item in successful
                if item.get("hook_name") == "PreToolUse:Agent"
                and not str(item.get("output") or "").strip()
            ),
            "agent_posttool_recorded": sum(
                1 for item in successful if item.get("hook_name") == "PostToolUse:Agent"),
            "disposition_denials": sum(
                1 for output in outputs if "post-return disposition" in output),
            "protected_state_hook_output_records": sum(
                1 for output in outputs if "只能由 hook 原子写入" in output),
        },
    }


def compact_tool_surface(value: dict) -> dict:
    cases = {}
    for name, item in value.get("cases", {}).items():
        if not isinstance(item, dict):
            continue
        hooks = [event for event in item.get("hook_events", []) if isinstance(event, dict)]
        cases[name] = {
            key: item.get(key) for key in (
                "returncode", "tool", "tool_use_seen", "denial_seen",
                "forged_effect", "runtime_chain", "passed",
            )
        }
        cases[name]["hook_decisions"] = list(dict.fromkeys(
            str(event.get("output") or "").strip()[:800]
            for event in hooks if str(event.get("output") or "").strip()
        ))
    return {
        "schema": "xunji.live_tool_surface.summary.v1",
        "claude_version": value.get("claude_version"),
        "cases": cases,
    }


def compact_pause(value: dict) -> dict:
    def hook_decisions(section: str) -> list[str]:
        item = value.get(section, {})
        hooks = item.get("hook_events", []) if isinstance(item, dict) else []
        return list(dict.fromkeys(
            str(event.get("output") or "").strip()[:800]
            for event in hooks if isinstance(event, dict)
            and str(event.get("output") or "").strip()
        ))

    return {
        "schema": "xunji.live_pause_flow.summary.v1",
        "claude_version": value.get("claude_version"),
        "passed": value.get("passed"),
        "created_ids": value.get("created_ids"),
        "other_ids": value.get("other_ids"),
        "delete_receipts": value.get("delete_receipts"),
        "wrong_delete_denied": value.get("wrong_delete_denied"),
        "cron_quiescent": value.get("cron_quiescent"),
        "cron_note": value.get("cron_note"),
        "runtime_chain": value.get("runtime_chain"),
        "wrong_delete_hook_decisions": hook_decisions("wrong_delete"),
        "cleanup_hook_decisions": hook_decisions("cleanup"),
        "returncodes": {
            key: (value.get(key, {}) or {}).get("returncode")
            for key in ("create", "native_create", "wrong_delete", "cleanup", "native_cleanup")
        },
    }


def compact_selftest_log(content: str) -> dict:
    commands: list[dict] = []
    current: dict | None = None
    for line in content.splitlines():
        if line.startswith("$ "):
            current = {"command": line[2:], "result": "", "checks": [], "output": []}
            commands.append(current)
        elif current is not None:
            current["output"].append(line)
            if line.startswith(("ok   ", "ok  ", "FAIL ", "FAIL")):
                current["checks"].append(line.strip())
            if "selftest passed" in line or "FAILED" in line:
                current["result"] = line.strip()
    for item in commands:
        output = "\n".join(item.pop("output", []))
        item["output_sha256"] = hashlib.sha256(output.encode("utf-8")).hexdigest()
        item["check_count"] = len(item["checks"])
        item["failure_count"] = sum(
            1 for check in item["checks"] if str(check).startswith("FAIL"))
    return {
        "schema": "xunji.adversarial_selftests.summary.v1",
        "passed": bool(commands) and all(
            item.get("result") and "FAILED" not in str(item.get("result"))
            for item in commands
        ),
        "commands": commands,
        "source_sha256": hashlib.sha256(content.encode("utf-8")).hexdigest(),
    }


def file_manifest(paths: list[str]) -> dict:
    files = {}
    for relative in paths:
        path = ROOT / relative
        raw = path.read_bytes()
        files[relative] = {
            "size": len(raw),
            "sha256": hashlib.sha256(raw).hexdigest(),
            "resolved_path": str(path.resolve()),
        }
    settings = json.loads((ROOT / ".claude" / "settings.json").read_text(encoding="utf-8"))
    bindings = []
    for event_name, groups in settings.get("hooks", {}).items():
        for group in groups if isinstance(groups, list) else []:
            if not isinstance(group, dict):
                continue
            for hook in group.get("hooks", []):
                if isinstance(hook, dict):
                    bindings.append({
                        "event": event_name,
                        "matcher": str(group.get("matcher") or ""),
                        "command": str(hook.get("command") or ""),
                    })
    return {
        "schema": "xunji.installed_runtime_manifest.v1",
        "repository_root": str(ROOT.resolve()),
        "files": files,
        "hook_bindings": bindings,
        "turn_contract_hook_references": [
            binding for binding in bindings
            if "tools/turn_contract.py" in binding["command"]
        ],
    }


def stale_reference_audit() -> dict:
    """Inventory Claude-facing Markdown and reject known historical shortcuts."""
    roots = [
        ROOT / "CLAUDE.md",
        ROOT / "docs",
        ROOT / ".claude" / "skills",
        ROOT / ".agents" / "skills",
        ROOT / "review" / "independent-reviewer.md",
    ]
    patterns = {
        "heading_alone_is_review_gate": r"marker is what `?tools/check_run\.py`? looks for",
        "manual_fresh_context_template": r"Reviewer prompt \(copy, fill",
        "assignment_proves_agent_use": r"assignment(?: file)? (?:counts as|proves) Agent",
        "heartbeat_proves_execution": r"heartbeat (?:counts as|proves) (?:Agent )?execution",
        "pipe_delimited_front_status": r"Status:\s*open\s*\|\s*Barrier",
        "pause_forces_coda": r"PAUSED_BY_OPERATOR.{0,120}(?:requires|must write).{0,30}Coda",
    }
    files: dict[str, dict] = {}
    matches: list[dict] = []
    candidates: list[Path] = []
    for root in roots:
        if root.is_file():
            candidates.append(root)
        elif root.is_dir():
            candidates.extend(sorted(root.rglob("*.md")))
    for path in sorted(set(candidates)):
        raw = path.read_bytes()
        text = raw.decode("utf-8", errors="replace")
        relative = path.relative_to(ROOT).as_posix()
        files[relative] = {"size": len(raw), "sha256": hashlib.sha256(raw).hexdigest()}
        for name, expression in patterns.items():
            regex = re.compile(expression, re.I | re.S)
            for match in regex.finditer(text):
                matches.append({
                    "pattern": name,
                    "path": relative,
                    "line": text.count("\n", 0, match.start()) + 1,
                    "excerpt": " ".join(match.group(0).split())[:240],
                })
    return {
        "schema": "xunji.stale_reference_audit.v1",
        "files_scanned": len(files),
        "patterns": patterns,
        "forbidden_matches": matches,
        "passed": not matches,
        "files": files,
    }


def copy_set(names: list[str], destination: Path) -> None:
    destination.mkdir(parents=True, exist_ok=True)
    for name in names:
        shutil.copy2(HERE / name, destination / name)


def clean_generated(destination: Path, patterns: tuple[str, ...]) -> None:
    for pattern in patterns:
        for path in destination.glob(pattern):
            if path.is_file():
                path.unlink()


def main() -> int:
    for obsolete in (
        "rules_docs.diff", "skills_templates.diff",
        "root_workflow.diff", "agent_templates.diff",
    ):
        (HERE / obsolete).unlink(missing_ok=True)
    write("output_gate.diff", tracked_diff([".claude/hooks/output_gate.py"]))
    write("settings.diff", tracked_diff([".claude/settings.json"]))
    write("run_model.diff", new_file_diff("tools/run_model.py"))
    write("workers.diff", tracked_diff(["tools/anti_drift.py", "tools/workers.py"]))
    run_gate = split_hunks(
        tracked_diff([".claude/hooks/run_gate.py"]), "run_gate.hunks", target_bytes=10_000)
    check_run = split_hunks(
        tracked_diff(["tools/check_run.py"]), "check_run.hunks", target_bytes=8_000)
    write("peer_review.diff", tracked_diff(["tools/peer_review.py"]))
    write("canonical_consumers.diff", tracked_diff([
        "tools/coverage_matrix.py", "tools/graph.py", "tools/loop_state.py",
        "tools/state_project.py",
    ]))
    write("status_journal.diff", tracked_diff([
        "tools/loop_journal.py", "tools/xunji_statusline.py",
    ]))
    write("test_registry.diff", tracked_diff(["tools/selftest_all.py"]))
    write("root_rules.diff", tracked_diff([
        "CLAUDE.md", "docs/ROUTER.md", "docs/ROADMAP.md",
        "review/independent-reviewer.md",
    ]))
    write("workflow_core.diff", tracked_diff([
        "docs/WORKFLOW.md",
    ]))
    write("workflow_reference.diff", tracked_diff([
        "docs/WORKFLOW-reference.md",
    ]))
    write("primary_skills.diff", tracked_diff([
        ".claude/skills/xunji-agent-board/SKILL.md",
        ".claude/skills/xunji-peer-review-panel/SKILL.md",
        ".claude/skills/xunji-reviewops/SKILL.md",
        ".claude/skills/xunji-run-lifecycle/SKILL.md",
        ".agents/skills/xunji-peer-review-panel/SKILL.md",
    ]))
    write("agent_role_templates.diff", tracked_diff([
        "docs/templates/agents/code-audit.md", "docs/templates/agents/exploit.md",
        "docs/templates/agents/report.md", "docs/templates/agents/review.md",
        "docs/templates/agents/surface.md", "docs/templates/agents/synthesizer.md",
        "docs/templates/agents/verify.md", "docs/templates/agents/web-hunter.md",
    ]))
    write("lifecycle_templates.diff", tracked_diff([
        "docs/templates/loop_prompt.md", "docs/templates/run/review.md",
        "docs/templates/worker.md",
    ]))
    turn = numbered_chunks(ROOT / "tools/turn_contract.py", "turn_contract", chunk_lines=170)
    receipts = numbered_chunks(
        ROOT / "tools/runtime_receipts.py", "runtime_receipts", chunk_lines=150)

    observation = run(sys.executable, str(HERE / "runtime_observation.py"))
    replica = run(sys.executable, str(HERE / "runtime_observation.py"))
    parsed = json.loads(observation)
    replica_parsed = json.loads(replica)
    for label, item in (("primary", parsed), ("replica", replica_parsed)):
        if not item.get("checks") or not all(item["checks"].values()):
            raise RuntimeError(f"{label} runtime observation contains a failed assertion")
    write("runtime_observation.json", json.dumps(parsed, ensure_ascii=False, indent=2,
                                                  sort_keys=True) + "\n")
    write("runtime_observation.replica.json", json.dumps(
        replica_parsed, ensure_ascii=False, indent=2, sort_keys=True) + "\n")
    write("runtime_observation.summary.json", json.dumps(
        compact_observation(parsed), ensure_ascii=False, indent=2, sort_keys=True) + "\n")
    write("runtime_observation.replica.summary.json", json.dumps(
        compact_observation(replica_parsed, digest=True), ensure_ascii=False, indent=2,
        sort_keys=True) + "\n")
    source_lines = (HERE / "runtime_observation.py").read_text(
        encoding="utf-8", errors="replace").splitlines()
    write("runtime_observation.source.txt", "".join(
        f"{idx:6d}\t{line}\n" for idx, line in enumerate(source_lines, 1)))
    live_raw_path = HERE / "live_claude_smoke.json"
    live_raw = json.loads(live_raw_path.read_text(encoding="utf-8"))
    live_summary = compact_live_smoke(live_raw)
    live_summary["raw_sha256"] = hashlib.sha256(live_raw_path.read_bytes()).hexdigest()
    write("live_claude_smoke.summary.json", json.dumps(
        live_summary, ensure_ascii=False, indent=2, sort_keys=True) + "\n")
    live_source = (HERE / "live_claude_smoke.py").read_text(
        encoding="utf-8", errors="replace").splitlines()
    write("live_claude_smoke.source.txt", "".join(
        f"{idx:6d}\t{line}\n" for idx, line in enumerate(live_source, 1)))
    fanout_raw_path = HERE / "live_fanout_flow.json"
    fanout_raw = json.loads(fanout_raw_path.read_text(encoding="utf-8"))
    if not fanout_raw.get("passed"):
        raise RuntimeError("live fan-out flow did not pass")
    fanout_summary = compact_live_fanout(fanout_raw)
    fanout_summary["raw_sha256"] = hashlib.sha256(fanout_raw_path.read_bytes()).hexdigest()
    write("live_fanout_flow.summary.json", json.dumps(
        fanout_summary, ensure_ascii=False, indent=2, sort_keys=True) + "\n")
    fanout_source = (HERE / "live_fanout_flow.py").read_text(
        encoding="utf-8", errors="replace").splitlines()
    write("live_fanout_flow.source.txt", "".join(
        f"{idx:6d}\t{line}\n" for idx, line in enumerate(fanout_source, 1)))
    tool_raw_path = HERE / "live_tool_surface.json"
    tool_raw = json.loads(tool_raw_path.read_text(encoding="utf-8"))
    if not all(item.get("passed") for item in tool_raw.get("cases", {}).values()):
        raise RuntimeError("live tool-surface flow did not pass")
    tool_summary = compact_tool_surface(tool_raw)
    tool_summary["raw_sha256"] = hashlib.sha256(tool_raw_path.read_bytes()).hexdigest()
    write("live_tool_surface.summary.json", json.dumps(
        tool_summary, ensure_ascii=False, indent=2, sort_keys=True) + "\n")
    tool_source = (HERE / "live_tool_surface.py").read_text(
        encoding="utf-8", errors="replace").splitlines()
    write("live_tool_surface.source.txt", "".join(
        f"{idx:6d}\t{line}\n" for idx, line in enumerate(tool_source, 1)))
    pause_raw_path = HERE / "live_pause_flow.json"
    pause_raw = json.loads(pause_raw_path.read_text(encoding="utf-8"))
    if not pause_raw.get("passed"):
        raise RuntimeError("live pause flow did not pass")
    pause_summary = compact_pause(pause_raw)
    pause_summary["raw_sha256"] = hashlib.sha256(pause_raw_path.read_bytes()).hexdigest()
    write("live_pause_flow.summary.json", json.dumps(
        pause_summary, ensure_ascii=False, indent=2, sort_keys=True) + "\n")
    pause_source = (HERE / "live_pause_flow.py").read_text(
        encoding="utf-8", errors="replace").splitlines()
    write("live_pause_flow.source.txt", "".join(
        f"{idx:6d}\t{line}\n" for idx, line in enumerate(pause_source, 1)))
    write("installed-runtime-manifest.json", json.dumps(file_manifest([
        ".claude/settings.json", ".claude/hooks/output_gate.py",
        ".claude/hooks/run_gate.py", "tools/turn_contract.py",
        "tools/runtime_receipts.py", "tools/run_model.py", "tools/anti_drift.py",
        "tools/workers.py",
    ]), ensure_ascii=False, indent=2, sort_keys=True) + "\n")
    write("closure-source-manifest.json", json.dumps(file_manifest([
        "tools/check_run.py", "tools/peer_review.py", "tools/selftest_all.py",
        "tools/coverage_matrix.py", "tools/graph.py", "tools/loop_state.py",
        "tools/state_project.py", "tools/loop_journal.py",
        "tools/xunji_statusline.py",
    ]), ensure_ascii=False, indent=2, sort_keys=True) + "\n")
    stale_audit = stale_reference_audit()
    if not stale_audit["passed"]:
        raise RuntimeError(f"stale Claude-facing references remain: {stale_audit['forbidden_matches']}")
    write("stale_reference_audit.json", json.dumps(
        stale_audit, ensure_ascii=False, indent=2, sort_keys=True) + "\n")
    adversarial_commands = (
        [sys.executable, "tools/run_model.py", "--selftest"],
        [sys.executable, "tools/turn_contract.py", "--selftest"],
        [sys.executable, "tools/runtime_receipts.py", "--selftest"],
        [sys.executable, "tools/anti_drift.py", "--selftest"],
        [sys.executable, ".claude/hooks/output_gate.py", "--selftest"],
        [sys.executable, ".claude/hooks/run_gate.py", "--selftest"],
    )
    adversarial_log = ""
    for command in adversarial_commands:
        adversarial_log += "$ " + " ".join(command) + "\n"
        adversarial_log += run_combined(*command) + "\n"
    write("adversarial_selftests.log", adversarial_log)
    adversarial_chunks = numbered_chunks(
        HERE / "adversarial_selftests.log", "adversarial_selftests", chunk_lines=170)
    write("adversarial_selftests.summary.json", json.dumps(
        compact_selftest_log(adversarial_log), ensure_ascii=False, indent=2,
        sort_keys=True) + "\n")
    closure_commands = (
        [sys.executable, "tools/check_run.py", "--selftest"],
        [sys.executable, "tools/peer_review.py", "--selftest"],
        [sys.executable, "tools/state_project.py", "--selftest"],
        [sys.executable, "tools/loop_state.py", "--selftest"],
        [sys.executable, "tools/xunji_statusline.py", "--selftest"],
    )
    closure_log = ""
    for command in closure_commands:
        closure_log += "$ " + " ".join(command) + "\n"
        closure_log += run_combined(*command) + "\n"
    write("closure_selftests.summary.json", json.dumps(
        compact_selftest_log(closure_log), ensure_ascii=False, indent=2,
        sort_keys=True) + "\n")
    observation_chunks = numbered_chunks(
        HERE / "runtime_observation.json", "runtime_observation", chunk_lines=190)
    replica_chunks = numbered_chunks(
        HERE / "runtime_observation.replica.json", "runtime_observation.replica",
        chunk_lines=190)
    shutil.copy2(ROOT / ".claude/settings.json", HERE / "installed-settings.json")

    runtime_names = [
        "output_gate.diff", "settings.diff", "run_model.diff", "workers.diff",
        "installed-settings.json", "runtime_observation.py",
        "runtime_observation.source.txt", "runtime_observation.summary.json",
        "runtime_observation.replica.summary.json", "selftest_all.log",
        *run_gate, *turn, *receipts,
    ]
    closure_names = [
        *check_run, "peer_review.diff", "canonical_consumers.diff",
        "status_journal.diff", "test_registry.diff", "selftest_all.log",
        "installed-runtime-manifest.json", "closure-source-manifest.json",
        "closure_selftests.summary.json",
    ]
    docs_names = [
        "root_rules.diff", "workflow_core.diff", "workflow_reference.diff",
        "primary_skills.diff", "agent_role_templates.diff",
        "lifecycle_templates.diff", "selftest_all.log",
        "historical_failures.md", "stale_reference_audit.json",
        "installed-runtime-manifest.json", "peer_review.diff",
    ]
    live_names = [
        "installed-runtime-manifest.json",
        "live_claude_smoke.source.txt", "live_claude_smoke.summary.json",
        "live_fanout_flow.source.txt", "live_fanout_flow.summary.json",
        "live_tool_surface.source.txt", "live_tool_surface.summary.json",
        "live_pause_flow.source.txt", "live_pause_flow.summary.json",
    ]
    turn_names = [
        "output_gate.diff", "settings.diff", *adversarial_chunks, *run_gate, *turn,
    ]
    receipt_names = [
        "settings.diff", "installed-settings.json", "workers.diff",
        "installed-runtime-manifest.json", "adversarial_selftests.log",
        "adversarial_selftests.summary.json",
        "selftest_all.log", *receipts,
    ]
    clean_generated(RUNTIME, (
        "run_gate.hunks-*.diff", "turn_contract.lines-*.txt",
        "runtime_receipts.lines-*.txt", "runtime_observation.lines-*.txt",
        "runtime_observation.replica.lines-*.txt", "runtime_observation*.summary.json",
        "runtime_observation.source.txt",
    ))
    clean_generated(CLOSURE, (
        "check_run.hunks-*.diff", "rules_docs.diff", "skills_templates.diff",
        "root_workflow.diff", "agent_templates.diff", "peer_review.md",
        "peer_review.json"))
    clean_generated(TURN, (
        "run_gate.hunks-*.diff", "turn_contract.lines-*.txt",
        "live_claude_smoke.*", "live_fanout_flow.*", "selftest_all.log",
        "adversarial_selftests.summary.json", "adversarial_selftests.log",
        "adversarial_selftests.lines-*.txt",
        "run_model.diff", "installed-runtime-manifest.json",
    ))
    clean_generated(RECEIPTS, (
        "runtime_receipts.lines-*.txt", "runtime_observation*",
        "live_fanout_flow.*", "adversarial_selftests.log",
    ))
    DOCS.mkdir(parents=True, exist_ok=True)
    LIVE.mkdir(parents=True, exist_ok=True)
    copy_set(runtime_names, RUNTIME)
    copy_set(closure_names, CLOSURE)
    copy_set(turn_names, TURN)
    copy_set(receipt_names, RECEIPTS)
    copy_set(docs_names, DOCS)
    copy_set(live_names, LIVE)
    print(json.dumps({
        "runtime": runtime_names,
        "closure": closure_names,
        "turn": turn_names,
        "receipts": receipt_names,
        "docs": docs_names,
        "live": live_names,
        "runtime_checks": len(parsed["checks"]),
        "runtime_events": len(parsed.get("runtime_events", [])),
        "replica_checks": len(replica_parsed["checks"]),
        "replica_events": len(replica_parsed.get("runtime_events", [])),
    }, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
