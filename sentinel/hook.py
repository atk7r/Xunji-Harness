#!/usr/bin/env python3
"""sentinel hook entry — Claude Code Pre/PostToolUse, UserPromptSubmit, SessionStart.

OBSERVE-ONLY: this hook NEVER denies. It reads the event, updates the behavior
monitor, records alerts, and exits 0 silently. Unlike the static safety_gate
(fail-CLOSED, a boundary), this detection layer fails OPEN — it must never break
the agent's workflow. Register for all four events in .claude/settings.json.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

# Run as a standalone script: make the repo root importable so `sentinel` resolves.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def main() -> int:
    try:
        raw = sys.stdin.buffer.read()                       # UTF-8 bytes (GBK-safe)
        event = json.loads(raw.decode("utf-8", "replace") or "{}")
    except Exception:
        return 0                                            # observe-only: no-op on parse error
    try:
        from sentinel import monitor
        monitor.handle_event(event)
    except Exception:
        pass                                                # detection must never break work
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
