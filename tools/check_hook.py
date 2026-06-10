from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
HOOK = ROOT / ".claude" / "hooks" / "safety_gate.py"


BLOCKED_COMMANDS = [
    "rm -rf target_dir",
    "curl -X DELETE https://example.test/api/item/1",
    "hydra -l user -P passwords.txt example.test http-post-form",
    "masscan 10.0.0.0/8",
    "chmod -R 777 target_dir",
]

ALLOWED_COMMANDS = [
    "Get-ChildItem -Force",
    "python tools/check_rules.py",
]


def run_hook(command: str) -> tuple[int, str, str]:
    event = {"tool_input": {"command": command}}
    completed = subprocess.run(
        [sys.executable, str(HOOK)],
        input=json.dumps(event),
        text=True,
        capture_output=True,
        check=False,
    )
    return completed.returncode, completed.stdout.strip(), completed.stderr.strip()


def is_denied(stdout: str) -> bool:
    if not stdout:
        return False
    try:
        data = json.loads(stdout)
    except json.JSONDecodeError:
        return False
    output = data.get("hookSpecificOutput") or {}
    return output.get("permissionDecision") == "deny"


def main() -> int:
    if not HOOK.exists():
        print(f"missing hook: {HOOK}")
        return 1

    failures: list[str] = []
    for command in BLOCKED_COMMANDS:
        _, stdout, stderr = run_hook(command)
        if stderr or not is_denied(stdout):
            failures.append(f"expected deny for: {command}")

    for command in ALLOWED_COMMANDS:
        _, stdout, stderr = run_hook(command)
        if stderr or stdout:
            failures.append(f"expected silence for: {command}")

    if failures:
        print("hook check failed")
        for failure in failures:
            print(f"- {failure}")
        return 1

    print("hook check passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
