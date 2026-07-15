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


def _normalizer_candidate_shape(value: object) -> bool:
    if not isinstance(value, dict):
        return False
    if set(value) != {
        "schema", "request_sha256", "source_sha256", "redacted_sha256",
        "target_token", "asset_tokens", "entry_tokens", "scope_refs",
        "authorization_refs", "signal_refs", "unresolved",
    } or value.get("schema") != "setup-normalizer-candidate.v1":
        return False
    if any(not re.fullmatch(r"[0-9a-f]{64}", str(value.get(key) or ""))
           for key in ("request_sha256", "source_sha256", "redacted_sha256")):
        return False
    target = value.get("target_token")
    if target is not None and not re.fullmatch(r"T-[0-9]{4,6}", str(target)):
        return False
    for key, prefix in (
        ("asset_tokens", "T"), ("entry_tokens", "T"),
        ("scope_refs", "R"), ("authorization_refs", "R"), ("signal_refs", "R"),
    ):
        items = value.get(key)
        if not isinstance(items, list) or len(items) > 10000 \
                or len(set(map(str, items))) != len(items) \
                or any(not re.fullmatch(rf"{prefix}-[0-9]{{4,6}}", str(item)) for item in items):
            return False
    unresolved = value.get("unresolved")
    if not isinstance(unresolved, list) or len(unresolved) > 1000:
        return False
    return all(
        isinstance(item, dict) and set(item) == {"field", "reason", "ref_id"}
        and 1 <= len(str(item.get("field") or "")) <= 255
        and 1 <= len(str(item.get("reason") or "")) <= 1024
        and bool(re.fullmatch(r"(?:T|R)-[0-9]{4,6}", str(item.get("ref_id") or "")))
        for item in unresolved
    )


def local_setup_metadata_invocation(
    command: str,
    *,
    root: Path = ROOT,
) -> PythonControlInvocation | None:
    """Recognize exact local-only setup URL/source-normalizer argv contracts.

    ``--classify`` is intentionally excluded because it performs active egress.
    A recon positional is also excluded: this exemption exists only for the
    operator-provided URL metadata path, not arbitrary future setup behavior.
    """
    setup_script = (root / "tools" / "setup_run.py").resolve()
    loop_script = (root / "tools" / "loop_bootstrap.py").resolve()
    invocation = parse_exact_python_command(
        command, root=root, allowed_scripts={setup_script, loop_script}
    )
    if invocation is None:
        return None
    if invocation.script == loop_script:
        args = invocation.args
        source = ""
        source_type = "auto"
        type_seen = False
        ai_mode = "off"
        ai_seen = False
        provider = ""
        model = ""
        candidate_json = ""
        prepare = False
        index = 0
        while index < len(args):
            token = args[index]
            if token == "--source" and not source and index + 1 < len(args):
                source = args[index + 1]
                index += 2
                continue
            if token == "--type" and not type_seen and index + 1 < len(args):
                source_type = args[index + 1]
                type_seen = True
                index += 2
                continue
            if token == "--ai" and not ai_seen and index + 1 < len(args):
                ai_mode = args[index + 1]
                ai_seen = True
                index += 2
                continue
            if token == "--ai-provider" and not provider and index + 1 < len(args):
                provider = args[index + 1]
                index += 2
                continue
            if token == "--ai-model" and not model and index + 1 < len(args):
                model = args[index + 1]
                index += 2
                continue
            if token == "--candidate-json" and not candidate_json and index + 1 < len(args):
                candidate_json = args[index + 1]
                index += 2
                continue
            if token == "--prepare-normalizer" and not prepare:
                prepare = True
                index += 1
                continue
            return None
        if not source or source_type not in {"auto", "url", "file"}:
            return None
        if len(source.encode("utf-8")) > 8192 or re.search(r"[\x00-\x1f\x7f]", source):
            return None
        is_url = bool(re.match(r"(?i)^https?://", source))
        if ai_mode == "off":
            if provider or model or candidate_json or prepare:
                return None
        elif ai_mode == "external":
            if is_url or source_type == "url" or not provider or not model:
                return None
            if len(provider) > 255 or len(model) > 255 \
                    or re.search(r"[\x00-\x20\x7f]", provider + model):
                return None
            if prepare == bool(candidate_json):
                return None
            if candidate_json:
                if len(candidate_json.encode("utf-8")) > 256 * 1024:
                    return None
                try:
                    candidate = json.loads(candidate_json)
                except json.JSONDecodeError:
                    return None
                if not _normalizer_candidate_shape(candidate):
                    return None
        else:
            # Local AI remains unavailable until a trusted backend registry exists.
            return None
        if not is_url:
            if source_type == "url" or not source.strip():
                return None
            return invocation
        try:
            parsed = urlsplit(source)
            if parsed.scheme.lower() not in {"http", "https"} or not parsed.hostname:
                return None
            if parsed.username is not None or parsed.password is not None:
                return None
            if parsed.port is not None and not (1 <= parsed.port <= 65535):
                return None
        except ValueError:
            return None
        return invocation
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
