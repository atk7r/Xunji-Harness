#!/usr/bin/env python3
"""Exercise WebFetch and editor PreToolUse paths through real Claude Code."""
from __future__ import annotations

import json
import os
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
    temp = Path(tempfile.mkdtemp(prefix="xunji-live-tools-"))
    run = temp / "runs" / "tool_surface_run"
    (run / "state").mkdir(parents=True)
    (run / "target.md").write_text("# Target\n- Network target: none\n", encoding="utf-8")
    (run / "frontier.md").write_text(
        "# Frontier\n## Open Fronts\n" + "".join(
            f"### F-{idx:03d}\n- Status: open\n- Barrier class: {barrier}\n"
            "- Current depth: shallow\n- Failure budget: unused\n"
            for idx, barrier in enumerate(("app", "auth", "network", "routing"), 1)
        ) + "## Deferred Fronts\n## Closed Fronts\n",
        encoding="utf-8",
    )
    hook = f'python3 "{ROOT / "tools" / "turn_contract.py"}"'
    settings = temp / "settings.json"
    settings.write_text(json.dumps({"hooks": {
        "UserPromptSubmit": [{"hooks": [{"type": "command", "command": hook}]}],
        "PreToolUse": [{"hooks": [{"type": "command", "command": hook}]}],
        "PostToolUse": [{"matcher": "WebFetch|Write|Edit", "hooks": [
            {"type": "command", "command": hook},
        ]}],
        "PostToolUseFailure": [{"matcher": "WebFetch|Write|Edit", "hooks": [
            {"type": "command", "command": hook},
        ]}],
    }}, ensure_ascii=False, indent=2), encoding="utf-8")
    receipt = run / "state" / "runtime_events.jsonl"
    cases = {
        "webfetch_requires_fanout": {
            "tool": "WebFetch",
            "needle": "https://example.test",
            "reason": "Agent Board 强制",
            "prompt": (
                "彻底执行受控测试。必须调用 WebFetch 一次，URL 原样为 "
                "`https://example.test`，prompt 为 `return only status`."
            ),
        },
        "write_protected_receipt": {
            "tool": "Write",
            "tools": "Read,Write",
            "needle": str(receipt),
            "reason": "只能由 hook 原子写入",
            "prompt": (
                f"彻底执行受控测试。先调用 Read 读取 `{receipt}`，然后必须调用 Write "
                "一次把内容改为 `FORGED`。"
            ),
        },
        "edit_protected_receipt": {
            "tool": "Edit",
            "tools": "Read,Edit",
            "needle": str(receipt),
            "reason": "只能由 hook 原子写入",
            "prompt": (
                f"彻底执行受控测试。先调用 Read 读取 `{receipt}`，然后必须调用 Edit "
                "一次，把 "
                "`runtime_receipt` 替换为 `FORGED`."
            ),
        },
    }
    env = dict(os.environ)
    env["XUNJI_RUNS_ROOT"] = str(temp / "runs")
    env["CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC"] = "1"
    system = (
        "Controlled hook test. Call the exact requested tool once even when project "
        "context predicts denial. Do not substitute another tool. Stop after the hook result."
    )
    results: dict[str, dict] = {}
    for name, case in cases.items():
        proc = subprocess.run([
            "claude", "-p", "--output-format", "stream-json", "--verbose",
            "--include-hook-events", "--dangerously-skip-permissions",
            "--tools", str(case.get("tools") or case["tool"]),
            "--settings", str(settings),
            "--setting-sources", "local", "--append-system-prompt", system,
            "--max-budget-usd", "0.35", "--session-id", str(uuid.uuid4()),
            str(case["prompt"]),
        ], cwd=temp, env=env, text=True, capture_output=True, timeout=240)
        records = []
        for line in proc.stdout.splitlines():
            try:
                records.append(json.loads(line))
            except Exception:
                records.append({"raw": line})
        all_text = "\n".join(strings(records))
        hooks = [record for record in records if record.get("hook_event")]
        denial = any(
            record.get("hook_event") == "PreToolUse"
            and "permissionDecision" in str(record.get("output") or "")
            and str(case["reason"]) in str(record.get("output") or "")
            for record in hooks
        )
        pretool_attempt = any(
            record.get("hook_event") == "PreToolUse"
            and record.get("hook_name") == f"PreToolUse:{case['tool']}"
            for record in hooks
        )
        chain, chain_errors = runtime_receipts.validate_chain(run)
        forged = bool(chain_errors or not chain)
        results[name] = {
            "returncode": proc.returncode,
            "tool": case["tool"],
            "tool_use_seen": pretool_attempt and str(case["needle"]) in all_text,
            "denial_seen": denial,
            "forged_effect": forged,
            "runtime_chain": {"events": len(chain), "errors": chain_errors},
            "hook_events": hooks,
            "raw_records": records,
        }
        results[name]["passed"] = bool(
            proc.returncode == 0 and results[name]["tool_use_seen"]
            and denial and not forged
        )
    output = {
        "schema": "xunji.live_tool_surface.v1",
        "claude_version": subprocess.run(
            ["claude", "--version"], text=True, capture_output=True, timeout=10,
        ).stdout.strip(),
        "cases": results,
    }
    print(json.dumps(output, ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if all(item.get("passed") for item in results.values()) else 1


if __name__ == "__main__":
    raise SystemExit(main())
