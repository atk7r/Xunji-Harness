#!/usr/bin/env python3
"""Exercise a real Claude Code Cron create -> pause/delete/list transaction."""
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


def strings(value: object):
    if isinstance(value, str):
        yield value
    elif isinstance(value, dict):
        for child in value.values():
            yield from strings(child)
    elif isinstance(value, list):
        for child in value:
            yield from strings(child)


def main() -> int:
    temp = Path(tempfile.mkdtemp(prefix="xunji-live-pause-"))
    run = temp / "runs" / "pause_run"
    (run / "state").mkdir(parents=True)
    (run / "target.md").write_text("# Target\n- Network target: none\n", encoding="utf-8")
    (run / "frontier.md").write_text(
        "# Frontier\n## Open Fronts\n### F-001\n- Status: open\n"
        "- Barrier class: local scheduler\n- Current depth: shallow\n"
        "- Failure budget: unused\n## Deferred Fronts\n## Closed Fronts\n",
        encoding="utf-8",
    )
    hook = f'python3 "{ROOT / "tools" / "turn_contract.py"}"'
    settings = temp / "settings.json"
    settings.write_text(json.dumps({"hooks": {
        "UserPromptSubmit": [{"hooks": [{"type": "command", "command": hook}]}],
        "PreToolUse": [{"hooks": [{"type": "command", "command": hook}]}],
        "PostToolUse": [{"matcher": "CronList|CronCreate|CronDelete", "hooks": [
            {"type": "command", "command": hook},
        ]}],
        "PostToolUseFailure": [{"matcher": "CronList|CronCreate|CronDelete", "hooks": [
            {"type": "command", "command": hook},
        ]}],
    }}, ensure_ascii=False, indent=2), encoding="utf-8")
    env = dict(os.environ)
    env["XUNJI_RUNS_ROOT"] = str(temp / "runs")
    env["CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC"] = "1"
    session_id = str(uuid.uuid4())

    def invoke(prompt: str, tools: str, *, resume: bool = False) -> dict:
        command = [
            "claude", "-p", "--output-format", "stream-json", "--verbose",
            "--include-hook-events", "--dangerously-skip-permissions",
            "--tools", tools, "--settings", str(settings),
            "--setting-sources", "local", "--max-budget-usd", "0.50",
        ]
        if resume:
            command.extend(["--resume", session_id])
        else:
            command.extend(["--session-id", session_id])
        command.append(prompt)
        proc = subprocess.run(
            command, cwd=temp, env=env, text=True, capture_output=True, timeout=300)
        records = []
        for line in proc.stdout.splitlines():
            try:
                records.append(json.loads(line))
            except Exception:
                records.append({"raw": line})
        return {
            "returncode": proc.returncode,
            "stderr": proc.stderr[-2000:],
            "records": records,
            "hook_events": [item for item in records if item.get("hook_event")],
        }

    create = invoke(
        "Controlled local scheduler test. Continue execution. First call CronList. Then call "
        "CronCreate exactly once to create an hourly recurring task whose prompt is exactly "
        "`/loop pause_run`. Report the created task id.",
        "CronList,CronCreate",
    )
    created = runtime_receipts.valid_tool_events(
        run, "CronCreate", session_id=session_id)
    created_ids = [
        str(job) for event in created for job in event.get("job_ids", []) if job
    ]
    cleanup_settings = temp / "cleanup-settings.json"
    cleanup_settings.write_text("{}\n", encoding="utf-8")

    def invoke_native(prompt: str, tools: str) -> dict:
        proc = subprocess.run([
            "claude", "-p", "--output-format", "stream-json", "--verbose",
            "--dangerously-skip-permissions", "--tools", tools,
            "--settings", str(cleanup_settings), "--setting-sources", "local",
            "--max-budget-usd", "0.25", "--resume", session_id, prompt,
        ], cwd=temp, env=env, text=True, capture_output=True, timeout=240)
        records = []
        for line in proc.stdout.splitlines():
            try:
                records.append(json.loads(line))
            except Exception:
                records.append({"raw": line})
        return {"returncode": proc.returncode, "stderr": proc.stderr[-2000:], "records": records}

    native_create = invoke_native(
        "Controlled ownership fixture. Call CronCreate exactly once for an hourly task "
        "whose prompt is exactly `/loop other_run`, then report its id.",
        "CronCreate",
    )
    native_text = "\n".join(
        str(record.get("result") or "")
        for record in native_create["records"]
        if isinstance(record, dict) and record.get("type") == "result"
    )
    other_ids = [
        item for item in dict.fromkeys(re.findall(
            r"\b[0-9a-f]{8}\b", native_text, flags=re.I))
        if item not in created_ids
    ]

    wrong = invoke(
        "停止loop，暂停运行。先调用 CronList，然后故意调用 CronDelete 删除有效但属于 "
        f"other_run 的 id `{other_ids[0] if other_ids else 'missing-other-id'}` 一次；"
        "看到 hook 拒绝后立即停止，不要删除 pause_run 任务。",
        "CronList,CronDelete", resume=True,
    )
    wrong_denial = any(
        event.get("hook_event_name") == "PreToolUseDenied"
        and any(job in str(event.get("decision_reason") or "") for job in other_ids)
        for event in runtime_receipts.denied_tool_events(run, session_id=session_id)
    )

    cleanup_prompt = (
        "停止loop，暂停运行。调用 CronList，找到 prompt 恰好为 `/loop pause_run` 的任务，"
        "用 CronDelete 删除它的精确 id，然后再次调用 CronList 确认该任务不存在。"
    )
    cleanup = invoke(cleanup_prompt, "CronList,CronDelete", resume=True)
    quiescent, quiescent_note = runtime_receipts.cron_quiescent(
        run, session_id=session_id)
    if not quiescent and created_ids:
        cleanup = invoke(cleanup_prompt, "CronList,CronDelete", resume=True)
        quiescent, quiescent_note = runtime_receipts.cron_quiescent(
            run, session_id=session_id)

    deleted = runtime_receipts.valid_tool_events(
        run, "CronDelete", session_id=session_id)
    native_cleanup = {"returncode": 0, "stderr": "", "records": []}
    if other_ids:
        native_cleanup = invoke_native(
            f"Controlled cleanup. Call CronDelete for id `{other_ids[0]}`, then CronList "
            "and confirm that exact id is absent.", "CronList,CronDelete")
    chain, chain_errors = runtime_receipts.validate_chain(run)
    output = {
        "schema": "xunji.live_pause_flow.v1",
        "claude_version": subprocess.run(
            ["claude", "--version"], text=True, capture_output=True, timeout=10,
        ).stdout.strip(),
        "session_id": session_id,
        "create": create,
        "native_create": native_create,
        "wrong_delete": wrong,
        "cleanup": cleanup,
        "native_cleanup": native_cleanup,
        "created_ids": created_ids,
        "other_ids": other_ids,
        "delete_receipts": [event.get("job_id") for event in deleted],
        "wrong_delete_denied": wrong_denial,
        "cron_quiescent": quiescent,
        "cron_note": quiescent_note,
        "runtime_chain": {"events": len(chain), "errors": chain_errors},
    }
    output["passed"] = bool(
        create["returncode"] == 0 and native_create["returncode"] == 0
        and wrong["returncode"] == 0
        and cleanup["returncode"] == 0 and native_cleanup["returncode"] == 0
        and created_ids and other_ids and wrong_denial
        and deleted and quiescent and not chain_errors
    )
    print(json.dumps(output, ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if output["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
