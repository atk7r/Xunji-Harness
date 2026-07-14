#!/usr/bin/env python3
"""Fail-closed parsing for one exact local Python control command.

This module is a transitive safety dependency.  It deliberately models only the
small shell subset needed by Xunji control-plane commands; it is not a general
shell parser.  Callers must treat ``None`` as untrusted/target-capable.
"""

from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
import re
import shlex
from urllib.parse import urlsplit


ROOT = Path(__file__).resolve().parents[2]
FIXTURE = Path(__file__).with_name("fixtures") / "privacy-command-shape.json"
_PYTHON_RE = re.compile(r"python(?:3(?:\.\d+){0,2})?", re.IGNORECASE)
_ENV_ASSIGNMENT_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_]*=.*", re.DOTALL)


@dataclass(frozen=True)
class PythonControlInvocation:
    script: Path
    args: tuple[str, ...]
    environment: tuple[str, ...] = ()


def has_unquoted_shell_control(command: str, *, reject_comments: bool = True) -> bool:
    """Return True for shell syntax that prevents an exact argv interpretation.

    Quoted ``&`` and ``;`` are data.  Redirection, chaining, pipes, comments,
    subshells, command/parameter expansion, newlines, and unmatched quoting are
    rejected.  A backslash may quote a literal metacharacter outside single
    quotes, matching the narrow behavior needed by existing control commands.
    """
    if not isinstance(command, str) or not command.strip():
        return True
    quote = ""
    escaped = False
    index = 0
    while index < len(command):
        char = command[index]
        if escaped:
            escaped = False
            index += 1
            continue
        if quote == "'":
            if char == "'":
                quote = ""
            index += 1
            continue
        if quote == '"':
            if char == "\\":
                escaped = True
            elif char == '"':
                quote = ""
            elif char in {"`", "$"}:
                return True
            index += 1
            continue
        if char in {"'", '"'}:
            quote = char
        elif char == "\\":
            escaped = True
        elif char in ";&|><`()\n\r" or char == "$" or (char == "#" and reject_comments):
            return True
        index += 1
    return bool(quote or escaped)


def parse_exact_python_command(
    command: str,
    *,
    root: Path = ROOT,
    allowed_scripts: set[Path] | frozenset[Path] | None = None,
    allow_environment: bool = False,
) -> PythonControlInvocation | None:
    """Parse exactly one Python script invocation with no shell control syntax."""
    normalized = str(command or "").strip()
    if has_unquoted_shell_control(normalized):
        return None
    try:
        tokens = shlex.split(normalized, comments=False, posix=True)
    except ValueError:
        return None
    environment: list[str] = []
    if allow_environment:
        while tokens and _ENV_ASSIGNMENT_RE.fullmatch(tokens[0]):
            environment.append(tokens.pop(0))
    if len(tokens) < 2 or not _PYTHON_RE.fullmatch(Path(tokens[0]).name):
        return None
    script = Path(tokens[1])
    if not script.is_absolute():
        script = root / script
    try:
        script = script.resolve()
    except OSError:
        return None
    if allowed_scripts is not None:
        allowed = {Path(item).resolve() for item in allowed_scripts}
        if script not in allowed:
            return None
    return PythonControlInvocation(script, tuple(tokens[2:]), tuple(environment))


def _option_value(args: tuple[str, ...], index: int, name: str) -> tuple[str, int] | None:
    token = args[index]
    if token == name:
        if index + 1 >= len(args):
            return None
        return args[index + 1], index + 2
    prefix = name + "="
    if token.startswith(prefix):
        return token[len(prefix):], index + 1
    return None


def local_setup_metadata_invocation(
    command: str,
    *,
    root: Path = ROOT,
) -> PythonControlInvocation | None:
    """Recognize the local-only ``setup_run --target URL`` argv contract.

    ``--classify`` is intentionally excluded because it performs active egress.
    A recon positional is also excluded: this exemption exists only for the
    operator-provided URL metadata path, not arbitrary future setup behavior.
    """
    setup_script = (root / "tools" / "setup_run.py").resolve()
    invocation = parse_exact_python_command(
        command, root=root, allowed_scripts={setup_script}
    )
    if invocation is None:
        return None
    args = invocation.args
    positionals: list[str] = []
    target = ""
    date = ""
    index = 0
    while index < len(args):
        token = args[index]
        target_value = _option_value(args, index, "--target")
        if target_value is not None:
            if target:
                return None
            target, index = target_value
            continue
        date_value = _option_value(args, index, "--date")
        if date_value is not None:
            if date:
                return None
            date, index = date_value
            continue
        if token.startswith("-"):
            return None
        positionals.append(token)
        index += 1
    if len(positionals) != 1 or not target:
        return None
    if date and not re.fullmatch(r"\d{8}", date):
        return None
    try:
        parsed = urlsplit(target)
        if parsed.scheme.lower() not in {"http", "https"} or not parsed.hostname:
            return None
        if parsed.port is not None and not (1 <= parsed.port <= 65535):
            return None
    except ValueError:
        return None
    return invocation


def selftest() -> int:
    cases = json.loads(FIXTURE.read_text(encoding="utf-8"))["cases"]
    checks: list[tuple[str, bool]] = []
    for case in cases:
        command = str(case["command"]).replace("{ROOT}", str(ROOT))
        if "shell_control" in case:
            checks.append((
                f"{case['name']}: shell-control",
                has_unquoted_shell_control(command) is bool(case["shell_control"]),
            ))
        if "local_setup" in case:
            checks.append((
                f"{case['name']}: local-setup",
                (local_setup_metadata_invocation(command) is not None)
                is bool(case["local_setup"]),
            ))
    bad = [name for name, ok in checks if not ok]
    for name, ok in checks:
        print(("ok   " if ok else "FAIL ") + name)
    print("command_shape selftest " + ("passed" if not bad else f"FAILED ({len(bad)})"))
    return 0 if not bad else 1


if __name__ == "__main__":
    raise SystemExit(selftest())
