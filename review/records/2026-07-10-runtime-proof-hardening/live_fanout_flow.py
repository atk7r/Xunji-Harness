#!/usr/bin/env python3
"""Exercise Agent receipt -> disposition -> Root release in real Claude Code."""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys
import tempfile
import uuid
from pathlib import Path


def repository_root(source: Path) -> Path:
    for parent in source.resolve().parents:
        if (parent / "tools" / "turn_contract.py").is_file():
            return parent
    raise RuntimeError("cannot locate Xunji repository root")


ROOT = repository_root(Path(__file__))
sys.path.insert(0, str(ROOT / "tools"))

import runtime_receipts  # noqa: E402


def main() -> int:
    temp = Path(tempfile.mkdtemp(prefix="xunji-live-fanout-"))
    run = temp / "runs" / "fanout_run"
    (run / "state").mkdir(parents=True)
    (run / "agents").mkdir()
    (temp / "tools").mkdir()
    sentinel = temp / "FANOUT_RELEASED"
    (temp / "tools" / "probe.py").write_text(
        "from pathlib import Path\nPath('FANOUT_RELEASED').write_text('released')\n",
        encoding="utf-8",
    )
    (run / "target.md").write_text("# Target\n- Network target: none\n", encoding="utf-8")
    (run / "frontier.md").write_text(
        "# Frontier\n## Open Fronts\n" + "".join(
            f"### F-{idx:03d}\n- Status: open\n- Barrier class: {barrier}\n"
            "- Current depth: shallow\n- Failure budget: unused\n"
            for idx, barrier in enumerate(("app", "auth", "network", "routing"), 1)
        ) + "## Deferred Fronts\n## Closed Fronts\n",
        encoding="utf-8",
    )
    (run / "evidence.md").write_text(
        "# Evidence\n## E-900 - controlled Agent candidate\n", encoding="utf-8")
    assignments = [
        {"agent": "A-web-001", "front": "F-001", "status": "assigned"},
        {"agent": "A-auth-001", "front": "F-002", "status": "assigned"},
    ]
    (run / "state" / "assignments.json").write_text(json.dumps({
        "schema": 1, "assignments": assignments,
    }), encoding="utf-8")
    for item in assignments:
        (run / "agents" / f"{item['agent']}.md").write_text(
            f"# Agent\n- Role: verify\n- Assigned front: {item['front']}\n- Status: assigned\n",
            encoding="utf-8",
        )

    hook = f'python3 "{ROOT / "tools" / "turn_contract.py"}"'
    output_gate = f'python3 "{ROOT / ".claude" / "hooks" / "output_gate.py"}"'
    run_gate = f'python3 "{ROOT / ".claude" / "hooks" / "run_gate.py"}"'
    settings = temp / "settings.json"
    settings.write_text(json.dumps({"hooks": {
        "UserPromptSubmit": [{"hooks": [{"type": "command", "command": hook}]}],
        "PreToolUse": [{"hooks": [{"type": "command", "command": hook}]}],
        "PostToolUse": [{"matcher": "Agent|Bash", "hooks": [
            {"type": "command", "command": hook},
        ]}],
        "PostToolUseFailure": [{"matcher": "Agent|Bash", "hooks": [
            {"type": "command", "command": hook},
        ]}],
        "SubagentStart": [{"hooks": [{"type": "command", "command": hook}]}],
        "SubagentStop": [{"hooks": [{"type": "command", "command": hook}]}],
        "Stop": [{"hooks": [
            {"type": "command", "command": output_gate},
            {"type": "command", "command": run_gate},
        ]}],
    }}, ensure_ascii=False, indent=2), encoding="utf-8")

    probe = "python3 tools/probe.py GET https://example.test"
    finish_web = (
        f"python3 {ROOT / 'tools' / 'workers.py'} finish {run} A-web-001 "
        "--status merged --note 'Evidence: E-900 merged for Front: F-001'"
    )
    finish_auth = (
        f"python3 {ROOT / 'tools' / 'workers.py'} finish {run} A-auth-001 "
        "--status merged --note 'Evidence: E-900 merged for Front: F-002'"
    )
    prompt = f"""Controlled local workflow test. Perform exactly this sequence and do not stop after an expected denial:
1. Call Agent once with prompt `XUNJI_ASSIGNMENT=A-web-001 XUNJI_FRONT=F-001 Return candidate for F-001.`
2. Call Agent once with prompt `XUNJI_ASSIGNMENT=A-auth-001 XUNJI_FRONT=F-002 Return candidate for F-002.`
3. Call Bash exactly `{probe}`. It must be denied because disposition is still pending.
4. Call Bash exactly `{finish_web}`.
5. Call Bash exactly `{finish_auth}`.
6. Call Bash exactly `{probe}` again. It must now execute the local sentinel probe.
Do not invent target results. After step 6, report only whether the sentinel command executed,
then end with exactly `下一行动: 读取 F-001 证据索引`."""
    env = dict(os.environ)
    env["XUNJI_RUNS_ROOT"] = str(temp / "runs")
    env["CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC"] = "1"
    proc = subprocess.run([
        "claude", "-p", "--output-format", "stream-json", "--verbose",
        "--include-hook-events", "--dangerously-skip-permissions",
        "--tools", "Agent,Bash", "--settings", str(settings),
        "--setting-sources", "local", "--max-budget-usd", "1.00",
        "--session-id", str(uuid.uuid4()), prompt,
    ], cwd=temp, env=env, text=True, capture_output=True, timeout=360)
    records = []
    for line in proc.stdout.splitlines():
        try:
            records.append(json.loads(line))
        except Exception:
            records.append({"raw": line})
    hook_events = [record for record in records if record.get("hook_event")]
    result_records = [
        record for record in records
        if isinstance(record, dict) and record.get("type") == "result"
    ]
    final_result_text = str(result_records[-1].get("result") or "") \
        if result_records else ""
    stop_hook_events = [
        record for record in hook_events
        if record.get("hook_event") == "Stop" and record.get("outcome") == "success"
    ]
    coda_matches = re.findall(
        r"(?im)^\s*下一行动\s*[:：]\s*(.*?)\s*$", final_result_text)
    final_coda_seen = bool(
        len(coda_matches) == 1
        and final_result_text.rstrip().splitlines()[-1].lstrip().startswith("下一行动")
        and len(set(re.findall(r"\bF-\d+\b", coda_matches[0], re.I))) == 1
        and next(iter(set(re.findall(r"\bF-\d+\b", coda_matches[0], re.I))), "")
        in {"F-001", "F-002", "F-003", "F-004"}
    )
    disposition_denial = any(
        record.get("hook_event") == "PreToolUse"
        and "post-return disposition" in str(record.get("output") or "")
        for record in hook_events
    )
    probe_allowed = any(
        record.get("hook_event") == "PreToolUse"
        and record.get("outcome") == "success"
        and not str(record.get("output") or "").strip()
        for record in hook_events
    ) and sentinel.exists()
    chain, chain_errors = runtime_receipts.validate_chain(run)
    fanout = runtime_receipts.agent_fanout(run)
    disposition = runtime_receipts.agent_disposition(run)
    unresolved_target_denials = runtime_receipts.unresolved_target_denials(run)
    all_denials = runtime_receipts.denied_tool_events(run)
    protected_non_target_denials = [
        event for event in all_denials
        if "只能由 hook 原子写入" in str(event.get("decision_reason") or "")
        and event.get("target_action") is False
    ]
    final_contract = json.loads((run / "state" / "turn_contract.json").read_text(
        encoding="utf-8"))
    operator_contract_preserved = (
        final_contract.get("session_id")
        and str(final_contract.get("prompt_excerpt") or "").startswith(
            "Controlled local workflow test.")
    )
    result = {
        "schema": "xunji.live_fanout_flow.v1",
        "claude_version": subprocess.run(
            ["claude", "--version"], text=True, capture_output=True, timeout=10,
        ).stdout.strip(),
        "returncode": proc.returncode,
        "stderr": proc.stderr[-2000:],
        "record_count": len(records),
        "disposition_denial_seen": disposition_denial,
        "post_disposition_probe_allowed": probe_allowed,
        "stop_hook_events": len(stop_hook_events),
        "final_coda_seen": final_coda_seen,
        "sentinel_created": sentinel.exists(),
        "sentinel_value": sentinel.read_text(encoding="utf-8") if sentinel.exists() else "",
        "fanout": fanout,
        "disposition": disposition,
        "runtime_chain": {"events": len(chain), "errors": chain_errors},
        "unresolved_target_denials": unresolved_target_denials,
        "protected_non_target_receipts": len(protected_non_target_denials),
        "operator_contract_preserved": operator_contract_preserved,
        "assignments": json.loads((run / "state" / "assignments.json").read_text(
            encoding="utf-8")),
        "hook_events": hook_events,
        "raw_records": records,
    }
    result["passed"] = bool(
        proc.returncode == 0 and disposition_denial and probe_allowed
        and fanout.get("satisfied") and disposition.get("disposition_satisfied")
        and len(stop_hook_events) >= 2 and final_coda_seen and operator_contract_preserved
        and not chain_errors and not unresolved_target_denials and sentinel.exists()
    )
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if result["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
