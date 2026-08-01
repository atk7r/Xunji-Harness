#!/usr/bin/env python3
"""Exercise installed hook entrypoints against a temporary active run."""
from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path


def repository_root(source: Path) -> Path:
    for parent in source.resolve().parents:
        if (parent / "tools" / "turn_contract.py").is_file():
            return parent
    raise RuntimeError("cannot locate repository root containing tools/turn_contract.py")


ROOT = repository_root(Path(__file__))
TOOLS = ROOT / "tools"
sys.path.insert(0, str(TOOLS))

import runtime_receipts  # noqa: E402
import workers  # noqa: E402


def main() -> int:
    temp = Path(tempfile.mkdtemp(prefix="xunji-runtime-observation-"))
    runs = temp / "runs"
    run = runs / "observed_run"
    (run / "state").mkdir(parents=True)
    (run / "agents").mkdir()
    (run / "target.md").write_text("# Target\n", encoding="utf-8")
    (run / "frontier.md").write_text(
        "# Frontier\n## Open Fronts\n"
        + "".join(
            f"### F-{index:03d}\n- Status: open\n- Barrier class: {barrier}\n"
            "- Current depth: shallow\n- Failure budget: unused\n"
            for index, barrier in enumerate(("app", "auth", "network", "routing"), 1)
        )
        + "## Deferred Fronts\n## Closed Fronts\n",
        encoding="utf-8",
    )
    assignments = [
        {"agent": "A-web-001", "front": "F-001", "status": "assigned"},
        {"agent": "A-auth-001", "front": "F-002", "status": "assigned"},
    ]
    (run / "state" / "assignments.json").write_text(
        json.dumps({"schema": 1, "assignments": assignments}), encoding="utf-8")
    for item in assignments:
        (run / "agents" / f"{item['agent']}.md").write_text(
            f"# Agent\n- Role: verify\n- Assigned front: {item['front']}\n- Status: assigned\n",
            encoding="utf-8",
        )

    transcript = temp / "transcript.jsonl"
    tool_ids = [
        "agent-tool-1", "agent-tool-2", "cron-list-1", "cron-create-1",
        "cron-list-2", "cron-delete-1", "cron-list-3", "review-tool-1",
        "completion-weak-1", "completion-structured-1",
    ]
    transcript.write_text("\n".join(tool_ids) + "\n", encoding="utf-8")
    env = dict(os.environ)
    env["XUNJI_RUNS_ROOT"] = str(runs)
    settings = json.loads((ROOT / ".claude" / "settings.json").read_text(encoding="utf-8"))
    session_start_commands = [
        str(item.get("command") or "")
        for group in settings.get("hooks", {}).get("SessionStart", [])
        if isinstance(group, dict)
        for item in group.get("hooks", [])
        if isinstance(item, dict)
    ]

    def hook(event: dict) -> dict:
        event.setdefault("transcript_path", str(transcript))
        proc = subprocess.run(
            [sys.executable, str(TOOLS / "turn_contract.py")],
            input=json.dumps(event), text=True, capture_output=True, env=env, timeout=15,
        )
        if proc.returncode != 0:
            raise RuntimeError(proc.stderr or f"hook returncode={proc.returncode}")
        return json.loads(proc.stdout) if proc.stdout.strip() else {}

    def prompt(text: str, session: str) -> dict:
        return hook({"hook_event_name": "UserPromptSubmit", "session_id": session, "prompt": text})

    def pre(tool: str, tool_input: dict, session: str = "s-exec") -> dict:
        return hook({
            "hook_event_name": "PreToolUse", "session_id": session,
            "tool_name": tool, "tool_input": tool_input,
        })

    def post(tool: str, tool_id: str, tool_input: dict, response: object) -> None:
        hook({
            "hook_event_name": "PostToolUse", "session_id": "s-exec",
            "tool_name": tool, "tool_use_id": tool_id,
            "tool_input": tool_input, "tool_response": response,
        })

    observations: dict[str, object] = {}
    observations["explain_context"] = prompt("Why was Agent skipped? Explain only.", "s-explain")
    observations["explain_blocks_bash"] = pre("Bash", {"command": "echo mutate"}, "s-explain")
    observations["pause_context"] = prompt("stop the loop", "s-pause")
    observations["pause_blocks_edit"] = pre("Edit", {"file_path": str(run / "frontier.md")}, "s-pause")
    observations["execute_context"] = prompt("resume execution", "s-exec")
    target = {"command": "python3 tools/probe.py GET https://example.test"}
    contract_file = run / "state" / "turn_contract.json"
    contract_file.write_text("{broken", encoding="utf-8")
    observations["malformed_contract_blocks_target"] = pre("Bash", target)
    prompt("resume execution", "s-exec")
    contract_data = json.loads(contract_file.read_text(encoding="utf-8"))
    contract_data["schema"] = "wrong"
    contract_file.write_text(json.dumps(contract_data), encoding="utf-8")
    observations["wrong_schema_blocks_target"] = pre("Bash", target)
    prompt("resume execution", "s-exec")
    original_frontier = (run / "frontier.md").read_text(encoding="utf-8")
    (run / "frontier.md").write_text(
        "# Frontier\n## Open Fronts\nmalformed\n", encoding="utf-8")
    observations["malformed_frontier_blocks_target"] = pre("Bash", target)
    (run / "frontier.md").write_text(original_frontier, encoding="utf-8")
    observations["target_before_agents"] = pre("Bash", target)

    assignments_path = run / "state" / "assignments.json"
    original_assignments = assignments_path.read_text(encoding="utf-8")
    assignments_path.write_text("{broken", encoding="utf-8")
    observations["malformed_assignments_blocks_agent"] = pre(
        "Agent", {"prompt": "XUNJI_ASSIGNMENT=A-web-001 XUNJI_FRONT=F-001"})
    assignments_path.write_text(original_assignments, encoding="utf-8")

    for tool_id, assignment, front in (
        ("agent-tool-1", "A-web-001", "F-001"),
        ("agent-tool-2", "A-auth-001", "F-002"),
    ):
        agent_input = {"prompt": f"XUNJI_ASSIGNMENT={assignment} XUNJI_FRONT={front}"}
        observations[f"pre_{assignment}"] = pre("Agent", agent_input)
        post("Agent", tool_id, agent_input, {"result": f"candidate for {front}"})

    before_disposition = runtime_receipts.agent_disposition(run, session_id="s-exec")
    for assignment, front in (("A-web-001", "F-001"), ("A-auth-001", "F-002")):
        workers.update_agent_lifecycle(
            run, assignment, status="merged",
            note=f"Front: {front} candidate adjudicated", terminal=True,
        )
    after_disposition = runtime_receipts.agent_disposition(run, session_id="s-exec")
    observations["agent_before_disposition"] = before_disposition
    observations["agent_after_disposition"] = after_disposition
    observations["target_after_agents"] = pre("Bash", target)

    cron_input = {"prompt": f"/loop {run.name}"}
    observations["cron_create_before_list"] = pre("CronCreate", cron_input)
    post("CronList", "cron-list-1", {}, {"tasks": []})
    observations["cron_create_after_empty_list"] = pre("CronCreate", cron_input)
    post("CronCreate", "cron-create-1", cron_input, {"id": "job-observed-1"})
    observations["duplicate_create_without_relist"] = pre("CronCreate", cron_input)
    post("CronList", "cron-list-2", {}, {
        "tasks": [{"id": "job-observed-1", "prompt": f"/loop {run.name}"}],
    })
    observations["delete_unrelated_job"] = pre("CronDelete", {"id": "job-unrelated"})
    observations["delete_observed_job"] = pre("CronDelete", {"id": "job-observed-1"})
    post("CronDelete", "cron-delete-1", {"id": "job-observed-1"}, {"deleted": True})
    post("CronList", "cron-list-3", {}, {"tasks": []})
    observations["cron_quiescent"] = runtime_receipts.cron_quiescent(run, session_id="s-exec")

    generated_at = datetime.now(timezone.utc).isoformat()
    review_input = {"command": f"python3 tools/peer_review.py {run} --into-run"}
    post("Bash", "review-tool-1", review_input, {"stdout": "## Verdict: PASS"})
    observations["foreground_review_observed"] = runtime_receipts.review_invocation_valid(
        run, generated_at)

    evidence_index = run / "evidence_index.json"
    evidence_index.write_text('{"schema":"observation"}\n', encoding="utf-8")
    evidence_hash = hashlib.sha1(evidence_index.read_bytes()).hexdigest()
    weak_prompt = f"XUNJI_COMPLETION_REVIEW EVIDENCE_INDEX={evidence_hash}"
    structured_prompt = (
        f"{weak_prompt} "
        "CHECKS=report_parity,severity_artifacts,reachable_frontier,review_ledger"
    )
    observations["completion_prompt_missing_checks"] = pre(
        "Agent", {"prompt": weak_prompt})
    observations["completion_prompt_structured"] = pre(
        "Agent", {"prompt": structured_prompt})
    post("Agent", "completion-weak-1", {"prompt": structured_prompt}, {"result": "PASS"})
    observations["bare_pass_rejected"] = not runtime_receipts.completion_review_valid(
        run, evidence_hash)
    post("Agent", "completion-structured-1", {"prompt": structured_prompt}, {
        "result": (
            f"XUNJI_COMPLETION_VERDICT=PASS EVIDENCE_INDEX={evidence_hash} "
            "CHECKS=report_parity,severity_artifacts,reachable_frontier,review_ledger"
        ),
    })
    observations["structured_completion_accepted"] = runtime_receipts.completion_review_valid(
        run, evidence_hash)
    events, chain_errors = runtime_receipts.validate_chain(run)
    observations["runtime_chain"] = {"events": len(events), "errors": chain_errors}
    observations["run_status"] = json.loads((run / "state" / "run_status.json").read_text(encoding="utf-8"))

    deny = lambda value: value.get("hookSpecificOutput", {}).get("permissionDecision") == "deny"
    checks = {
        "sessionstart_contract_selftest_wired": any(
            "tools/turn_contract.py" in command and "--selftest" in command
            for command in session_start_commands),
        "explain_denies_bash": deny(observations["explain_blocks_bash"]),
        "pause_denies_edit": deny(observations["pause_blocks_edit"]),
        "pre_agent_target_denied": deny(observations["target_before_agents"]),
        "malformed_contract_denied": deny(observations["malformed_contract_blocks_target"]),
        "wrong_contract_schema_denied": deny(observations["wrong_schema_blocks_target"]),
        "malformed_frontier_denied": deny(observations["malformed_frontier_blocks_target"]),
        "malformed_assignments_denied": deny(observations["malformed_assignments_blocks_agent"]),
        "unmerged_agents_detected": bool(before_disposition.get("pending")),
        "merged_agents_accepted": after_disposition.get("disposition_satisfied") is True,
        "post_agent_target_allowed": observations["target_after_agents"] == {},
        "cron_requires_list": deny(observations["cron_create_before_list"]),
        "cron_allows_after_empty_list": observations["cron_create_after_empty_list"] == {},
        "duplicate_cron_denied": deny(observations["duplicate_create_without_relist"]),
        "unrelated_delete_denied": deny(observations["delete_unrelated_job"]),
        "listed_delete_allowed": observations["delete_observed_job"] == {},
        "cron_final_quiescent": observations["cron_quiescent"][0] is True,
        "review_invocation_time_bound": observations["foreground_review_observed"] is True,
        "completion_prompt_requires_checks": deny(observations["completion_prompt_missing_checks"]),
        "completion_prompt_with_checks_allowed": observations["completion_prompt_structured"] == {},
        "bare_completion_pass_rejected": observations["bare_pass_rejected"] is True,
        "structured_completion_accepted": observations["structured_completion_accepted"] is True,
        "receipt_chain_valid": not chain_errors and len(events) == 21,
        "execute_status_active": observations["run_status"].get("status") == "active",
    }
    print(json.dumps({
        "schema": "xunji.runtime_observation.v1",
        "checks": checks,
        "observations": observations,
        "runtime_events": events,
    }, ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if all(checks.values()) else 1


if __name__ == "__main__":
    raise SystemExit(main())
