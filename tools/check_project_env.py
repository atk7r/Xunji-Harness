#!/usr/bin/env python3
"""Fail-closed preflight for the canonical Xunji ``.venv`` runtime."""

from __future__ import annotations

import argparse
import ast
import json
from pathlib import Path
import re
import shlex
import sys

from harness import python_runtime


ROOT = Path(__file__).resolve().parents[1]
_MAX_GUIDANCE_BYTES = 2 * 1024 * 1024
_BARE_PROJECT_PYTHON = re.compile(
    r"(?:"
    r"(?<![A-Za-z0-9_./-])python3?"
    r"|(?<![A-Za-z0-9_.-])/(?![^\s`'\"]*\.venv/bin/python\b)"
    r"(?:[^/\s`'\"]+/)*python3?"
    r")\s+"
    r"(?:(?:[^\s`'\"]+/)?[^\s`'\"]+\.py\b|tools/|\.claude/|/)",
)
_SETTINGS_PYTHON = "$CLAUDE_PROJECT_DIR/.venv/bin/python"
_ENV_ASSIGNMENT = re.compile(r"[A-Za-z_][A-Za-z0-9_]*=.*", re.DOTALL)
_SHELL_CONTROL = re.compile(r"(?:&&|\|\||[;|&<>`\n\r]|\$\()")


def _guidance_paths(root: Path) -> list[Path]:
    paths = [root / "CLAUDE.md", root / "AGENTS.md"]
    for directory in (root / "docs", root / ".claude" / "skills", root / ".agents" / "skills"):
        if not directory.is_dir():
            continue
        for path in directory.rglob("*.md"):
            try:
                relative = path.relative_to(root)
            except ValueError:
                continue
            if relative == Path("docs/ARCHITECTURE.md") or "review" in relative.parts:
                continue
            paths.append(path)
    return sorted(set(paths))


def _bounded_text(path: Path) -> str:
    if path.is_symlink() or not path.is_file():
        raise ValueError("PROJECT_ENV_GUIDANCE_NOT_REGULAR")
    data = path.read_bytes()
    if len(data) > _MAX_GUIDANCE_BYTES:
        raise ValueError("PROJECT_ENV_GUIDANCE_TOO_LARGE")
    try:
        return data.decode("utf-8", errors="strict")
    except UnicodeDecodeError as exc:
        raise ValueError("PROJECT_ENV_GUIDANCE_UTF8_INVALID") from exc


def command_surface_errors(*, root: str | Path = ROOT) -> list[str]:
    """Return stable drift errors for model-visible project Python commands."""
    base = Path(root)
    errors: list[str] = []
    for path in _guidance_paths(base):
        try:
            text = _bounded_text(path)
        except ValueError as exc:
            errors.append(f"{exc}:{path.relative_to(base).as_posix()}")
            continue
        if _BARE_PROJECT_PYTHON.search(text):
            errors.append(
                "PROJECT_ENV_BARE_PYTHON_COMMAND:"
                + path.relative_to(base).as_posix()
            )

    tools_dir = base / "tools"
    if tools_dir.is_dir():
        for path in sorted(tools_dir.rglob("*.py")):
            try:
                text = _bounded_text(path)
                module = ast.parse(text, filename=path.as_posix())
            except (ValueError, SyntaxError) as exc:
                errors.append(
                    f"PROJECT_ENV_SOURCE_INVALID:{path.relative_to(base).as_posix()}"
                )
                continue
            doc = ast.get_docstring(module, clean=False) or ""
            if _BARE_PROJECT_PYTHON.search(doc):
                errors.append(
                    "PROJECT_ENV_BARE_PYTHON_DOCSTRING:"
                    + path.relative_to(base).as_posix()
                )

    settings = base / ".claude" / "settings.json"
    try:
        value = json.loads(_bounded_text(settings))
    except (ValueError, json.JSONDecodeError):
        errors.append("PROJECT_ENV_SETTINGS_INVALID:.claude/settings.json")
        return sorted(set(errors))

    def command_values(item: object) -> list[str]:
        if isinstance(item, dict):
            found = [str(item["command"])] if isinstance(item.get("command"), str) else []
            return found + [value for child in item.values() for value in command_values(child)]
        if isinstance(item, list):
            return [value for child in item for value in command_values(child)]
        return []

    commands = command_values(value)
    for command in commands:
        if ".py" not in command and "/sentinel/hook.py" not in command:
            continue
        try:
            tokens = shlex.split(command, posix=True)
        except ValueError:
            errors.append("PROJECT_ENV_SETTINGS_INTERPRETER_DRIFT:.claude/settings.json")
            break
        executable_index = 0
        while executable_index < len(tokens) \
                and _ENV_ASSIGNMENT.fullmatch(tokens[executable_index]):
            executable_index += 1
        if _SHELL_CONTROL.search(command) \
                or executable_index >= len(tokens) \
                or tokens[executable_index] != _SETTINGS_PYTHON:
            errors.append("PROJECT_ENV_SETTINGS_INTERPRETER_DRIFT:.claude/settings.json")
            break
    return sorted(set(errors))


def status() -> dict:
    errors = [
        *python_runtime.environment_errors(root=ROOT),
        *command_surface_errors(root=ROOT),
    ]
    return {
        "schema": "xunji.project-python-runtime.v1",
        "ok": not errors,
        "interpreter": python_runtime.display_token(),
        "minimum_version": ".".join(map(str, python_runtime.MIN_VERSION)),
        "errors": errors,
    }


def _selftest() -> int:
    current = status()
    synthetic = python_runtime.environment_errors(
        root=ROOT,
        executable="/usr/bin/python3",
        prefix="/usr",
        version=(3, 9),
    )
    import tempfile

    with tempfile.TemporaryDirectory(prefix="xunji-project-env-") as tmp:
        fixture = Path(tmp)
        (fixture / "docs").mkdir()
        (fixture / "tools").mkdir()
        (fixture / ".claude" / "skills" / "demo").mkdir(parents=True)
        (fixture / ".agents" / "skills" / "demo").mkdir(parents=True)
        (fixture / "CLAUDE.md").write_text(
            ".venv/bin/python tools/check_run.py\n", encoding="utf-8")
        (fixture / "AGENTS.md").write_text("# rules\n", encoding="utf-8")
        (fixture / "docs" / "guide.md").write_text("safe\n", encoding="utf-8")
        (fixture / ".claude" / "settings.json").parent.mkdir(exist_ok=True)
        (fixture / ".claude" / "settings.json").write_text(json.dumps({
            "hooks": {"SessionStart": [{"hooks": [{
                "type": "command",
                "command": '"$CLAUDE_PROJECT_DIR/.venv/bin/python" '
                           '"$CLAUDE_PROJECT_DIR/tools/check_project_env.py"',
            }]}]},
        }), encoding="utf-8")
        surface_clean = command_surface_errors(root=fixture) == []
        (fixture / "docs" / "guide.md").write_text(
            "`python3 tools/check_run.py`\n", encoding="utf-8")
        bare_rejected = any(
            item.startswith("PROJECT_ENV_BARE_PYTHON_COMMAND:")
            for item in command_surface_errors(root=fixture)
        )
        (fixture / "docs" / "guide.md").write_text(
            "`/usr/bin/python3 tools/check_run.py`\n", encoding="utf-8")
        absolute_bare_rejected = any(
            item.startswith("PROJECT_ENV_BARE_PYTHON_COMMAND:")
            for item in command_surface_errors(root=fixture)
        )
        (fixture / "docs" / "guide.md").write_text("safe\n", encoding="utf-8")
        (fixture / "tools" / "demo.py").write_text(
            '"""Run: python3 tools/demo.py"""\n', encoding="utf-8")
        bare_docstring_rejected = any(
            item.startswith("PROJECT_ENV_BARE_PYTHON_DOCSTRING:")
            for item in command_surface_errors(root=fixture)
        )
        (fixture / "tools" / "demo.py").write_text(
            '"""Run with the project environment."""\n', encoding="utf-8")
        (fixture / ".claude" / "settings.json").write_text(json.dumps({
            "hooks": {"SessionStart": [{"hooks": [{
                "type": "command",
                "command": '"$CLAUDE_PROJECT_DIR/.venv/bin/python" '
                           '"$CLAUDE_PROJECT_DIR/tools/check_project_env.py" '
                           '&& python3 tools/demo.py',
            }]}]},
        }), encoding="utf-8")
        embedded_bare_rejected = (
            "PROJECT_ENV_SETTINGS_INTERPRETER_DRIFT:.claude/settings.json"
            in command_surface_errors(root=fixture)
        )
        (fixture / ".claude" / "settings.json").write_text(json.dumps({
            "statusLine": {
                "type": "command",
                "command": 'XUNJI_COLOR=1 '
                           '$CLAUDE_PROJECT_DIR/.venv/bin/python '
                           '$CLAUDE_PROJECT_DIR/tools/demo.py',
            },
        }), encoding="utf-8")
        unquoted_canonical_accepted = command_surface_errors(root=fixture) == []

    checks = [
        ("current test process uses canonical .venv", current["ok"]),
        ("wrong prefix is rejected", "PYTHON_VENV_PREFIX_MISMATCH" in synthetic),
        ("wrong executable is rejected", "PYTHON_VENV_EXECUTABLE_MISMATCH" in synthetic),
        ("old Python is rejected", "PYTHON_VERSION_UNSUPPORTED" in synthetic),
        ("model-facing token is stable", current["interpreter"] == ".venv/bin/python"),
        ("canonical model-facing command surface passes", surface_clean),
        ("bare model-facing Python command is rejected", bare_rejected),
        ("absolute bare model-facing Python is rejected", absolute_bare_rejected),
        ("bare project tool docstring command is rejected", bare_docstring_rejected),
        ("embedded second interpreter in settings is rejected", embedded_bare_rejected),
        ("unquoted canonical settings interpreter is accepted", unquoted_canonical_accepted),
    ]
    bad = [name for name, ok in checks if not ok]
    for name, ok in checks:
        print(("ok   " if ok else "FAIL ") + name)
    print("project_env selftest " + ("passed" if not bad else f"FAILED ({len(bad)})"))
    return 0 if not bad else 1


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--selftest", action="store_true")
    args = parser.parse_args(argv)
    if args.selftest:
        return _selftest()
    value = status()
    if args.json:
        print(json.dumps(value, sort_keys=True))
    elif value["ok"]:
        print(f"project Python runtime OK: {value['interpreter']}")
    else:
        print(
            "project Python runtime invalid: " + ",".join(value["errors"])
            + f"; use {value['interpreter']}",
            file=sys.stderr,
        )
    return 0 if value["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
