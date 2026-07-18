#!/usr/bin/env python3
"""Fail-closed parsing for one exact local Python control command.

This module is a transitive safety dependency.  It deliberately models only the
small shell subset needed by Xunji control-plane commands; it is not a general
shell parser.  Callers must treat ``None`` as untrusted/target-capable.
"""

from __future__ import annotations

from dataclasses import dataclass
import json
import os
from pathlib import Path
import re
import shutil
import shlex
import stat
import sys
from urllib.parse import urlsplit


ROOT = Path(__file__).resolve().parents[2]
FIXTURE = Path(__file__).with_name("fixtures") / "privacy-command-shape.json"
_PYTHON_RE = re.compile(r"python(?:3(?:\.\d+){0,2})?", re.IGNORECASE)
_ENV_ASSIGNMENT_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_]*=.*", re.DOTALL)
_MAX_DIAGNOSTIC_CHAIN_BYTES = 128 * 1024
_MAX_DIAGNOSTIC_CHAIN_SEGMENTS = 64


@dataclass(frozen=True)
class PythonControlInvocation:
    script: Path
    args: tuple[str, ...]
    environment: tuple[str, ...] = ()


@dataclass(frozen=True)
class PythonControlShapeIssue:
    """Diagnostic-only description of a nearly exact control invocation.

    A shape issue never authorizes execution.  It only lets callers distinguish
    a safe-to-retry output wrapper from a source mutation or an opaque shell
    command, which must continue through the normal fail-closed path.
    """

    code: str
    category: str
    script: Path
    args: tuple[str, ...] = ()
    retryable_same_turn: bool = True


def _first_unquoted_shell_control(
    command: str, *, reject_comments: bool = True,
) -> tuple[int, str] | None:
    """Return the first shell-control offset/category, or ``None``.

    Invalid/empty input and unmatched quoting use explicit categories so
    diagnostics can remain conservative without changing the public boolean
    predicate used by existing callers.
    """
    if not isinstance(command, str) or not command.strip():
        return 0, "empty"
    quote = ""
    escaped = False
    index = 0
    token_has_content = False
    while index < len(command):
        char = command[index]
        if escaped:
            if char in "\n\r":
                return max(0, index - 1), "line-continuation"
            token_has_content = True
            escaped = False
            index += 1
            continue
        if quote == "'":
            if char == "'":
                quote = ""
            else:
                token_has_content = True
            index += 1
            continue
        if quote == '"':
            if char == "\\":
                escaped = True
            elif char == '"':
                quote = ""
            elif char in {"`", "$"}:
                return index, "quoted-expansion"
            else:
                token_has_content = True
            index += 1
            continue
        if char in {"'", '"'}:
            quote = char
        elif char == "\\":
            escaped = True
        elif char in ";&|":
            return index, "shell-chain"
        elif char in "><":
            return index, "redirection"
        elif char in "`()" or char == "$":
            return index, "expansion"
        elif char in "*?[]":
            # URL-looking words are not special to the shell.  In particular,
            # zsh applies pathname expansion to an unquoted ``?``, ``*``, or
            # bracket expression before Python receives argv.  Exempting the
            # token here would authorize a different source than the one the
            # hook inspected.  Quoting or escaping keeps the character literal.
            return index, "pathname-expansion"
        elif char in "{}":
            return index, "brace-expansion"
        elif char == "~" and not token_has_content:
            return index, "tilde-expansion"
        elif char == "=" and not token_has_content:
            # With zsh's EQUALS option, a word beginning ``=name`` expands to
            # the command path for ``name``.  Require it to be quoted/escaped
            # when it is intended as literal lifecycle data.
            return index, "equals-expansion"
        elif char in "\n\r":
            return index, "newline"
        elif char == "#" and reject_comments:
            return index, "comment"
        elif char.isspace():
            token_has_content = False
        else:
            token_has_content = True
        index += 1
    if quote:
        return len(command), "unmatched-quote"
    if escaped:
        return len(command), "trailing-escape"
    return None


def has_unquoted_shell_control(command: str, *, reject_comments: bool = True) -> bool:
    """Return True for shell syntax that prevents an exact argv interpretation.

    Quoted ``&`` and ``;`` are data.  Redirection, chaining, pipes, comments,
    subshells, command/parameter expansion, newlines, and unmatched quoting are
    rejected.  A backslash may quote a literal metacharacter outside single
    quotes, matching the narrow behavior needed by existing control commands.
    """
    return _first_unquoted_shell_control(
        command, reject_comments=reject_comments,
    ) is not None


def split_literal_and_chain(command: str) -> tuple[str, ...] | None:
    """Split one diagnostic-only literal ``&&`` chain into exact segments.

    This helper grants no execution authority.  It recognizes only two or more
    non-empty segments separated by an unquoted literal ``&&``.  Every other
    shell control (including ``;``, ``||``, pipes, redirection, expansion,
    comments, and newlines) remains opaque so callers can preserve their normal
    fail-closed policy.
    """
    raw_command = str(command or "")
    if len(raw_command.encode("utf-8", "replace")) > _MAX_DIAGNOSTIC_CHAIN_BYTES:
        return None
    if "\n" in raw_command or "\r" in raw_command:
        return None
    remaining = raw_command.strip()
    if not remaining:
        return None
    segments: list[str] = []
    while True:
        control = _first_unquoted_shell_control(remaining)
        if control is None:
            segment = remaining.strip()
            if not segment:
                return None
            segments.append(segment)
            if len(segments) > _MAX_DIAGNOSTIC_CHAIN_SEGMENTS:
                return None
            break
        offset, category = control
        if category != "shell-chain" or remaining[offset:offset + 2] != "&&":
            return None
        segment = remaining[:offset].strip()
        if not segment:
            return None
        segments.append(segment)
        if len(segments) > _MAX_DIAGNOSTIC_CHAIN_SEGMENTS:
            return None
        remaining = remaining[offset + 2:].strip()
        if not remaining:
            return None
    return tuple(segments) if len(segments) >= 2 else None


def _resolve_script_token(
    token: str,
    *,
    root: Path,
    allowed_scripts: set[Path] | frozenset[Path] | None,
) -> Path | None:
    """Resolve one script only when its lexical and canonical paths are allowed."""
    raw_script = Path(token)
    script_path = raw_script if raw_script.is_absolute() else root / raw_script
    try:
        script_spelling = Path(os.path.abspath(script_path))
        script = script_path.resolve(strict=True)
    except (OSError, RuntimeError, ValueError):
        return None
    if allowed_scripts is None:
        return script
    allowed: set[tuple[Path, Path]] = set()
    try:
        for item in allowed_scripts:
            allowed_path = Path(item)
            if not allowed_path.is_absolute():
                allowed_path = root / allowed_path
            allowed.add((
                Path(os.path.abspath(allowed_path)),
                allowed_path.resolve(strict=True),
            ))
    except (OSError, RuntimeError, ValueError):
        return None
    return script if (script_spelling, script) in allowed else None


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
    if environment and any(item.split("=", 1)[0] == "PATH" for item in environment):
        # Even with an absolute interpreter, a command-local PATH would make
        # any helper/subprocess resolution differ from the environment this
        # exact-control boundary verified.
        return None
    if len(tokens) < 2 or not trusted_python_token(tokens[0]):
        return None
    script = _resolve_script_token(
        tokens[1], root=root, allowed_scripts=allowed_scripts,
    )
    if script is None:
        return None
    return PythonControlInvocation(script, tuple(tokens[2:]), tuple(environment))


def _executable_identity(value: str) -> tuple[Path, int, int] | None:
    """Return a stable real-file identity for one executable path."""
    try:
        path = Path(value)
        if not path.is_absolute():
            return None
        resolved = path.resolve(strict=True)
        metadata = resolved.stat()
        if not stat.S_ISREG(metadata.st_mode) or not os.access(resolved, os.X_OK):
            return None
        return resolved, metadata.st_dev, metadata.st_ino
    except (OSError, RuntimeError, ValueError):
        return None


def trusted_python_token(token: str) -> bool:
    """Bind a Python command token to the interpreter running this boundary.

    ``PATH`` lookup is used only to resolve a bare spelling; its result never
    mints trust.  The resolved file must be the same canonical executable and
    inode as ``sys.executable``.  Absolute spellings are narrower still: only
    the current spelling or its canonical real path is accepted, so an
    attacker-controlled absolute/relative alias cannot become trusted merely
    by having a Python-looking basename.
    """
    value = str(token or "")
    path = Path(value)
    if not _PYTHON_RE.fullmatch(path.name):
        return False
    current = _executable_identity(sys.executable)
    if current is None:
        return False
    try:
        if path.is_absolute():
            spelling = Path(os.path.abspath(value))
            permitted = {
                Path(os.path.abspath(sys.executable)),
                current[0],
            }
            return spelling in permitted and _executable_identity(value) == current
        if path.name != value:
            return False
        resolved = shutil.which(value)
        return bool(resolved and _executable_identity(resolved) == current)
    except (OSError, RuntimeError, ValueError):
        return False


_OBSERVATIONAL_SUFFIX_RE = re.compile(
    r"(?:"
    r"2\s*>\s*&\s*1"
    r"(?:\s*\|\s*(?:head|tail)(?:\s+(?:-\d+|-n\s+\d+))?)?"
    r"|\|\s*(?:head|tail)(?:\s+(?:-\d+|-n\s+\d+))?"
    r")\s*\Z",
    re.IGNORECASE,
)


def _diagnostic_python_control_prefix(
    command: str,
    *,
    root: Path,
    allowed_scripts: set[Path] | frozenset[Path] | None,
) -> PythonControlInvocation | None:
    """Recognize a Python-looking prefix without granting executable trust.

    This path exists only so a rejected bare/unavailable interpreter plus an
    output-only wrapper receives the stable exact-argv retry diagnostic.  It
    validates the full prefix grammar and exact script identity, but deliberately
    does not call :func:`trusted_python_token` and must never be used by an
    authority or execution decision.
    """
    normalized = str(command or "").strip()
    if has_unquoted_shell_control(normalized):
        return None
    try:
        tokens = shlex.split(normalized, comments=False, posix=True)
    except ValueError:
        return None
    if len(tokens) < 2 or not _PYTHON_RE.fullmatch(Path(tokens[0]).name):
        return None
    script = _resolve_script_token(
        tokens[1], root=root, allowed_scripts=allowed_scripts,
    )
    if script is None:
        return None
    return PythonControlInvocation(script, tuple(tokens[2:]))


def diagnose_python_control_shape(
    command: str,
    *,
    root: Path = ROOT,
    allowed_scripts: set[Path] | frozenset[Path] | None = None,
) -> PythonControlShapeIssue | None:
    """Diagnose a prefix-anchored control command with an output-only wrapper.

    Only stderr-to-stdout merging and a terminal ``head``/``tail`` filter are
    classified as same-turn retryable.  The command is still rejected: callers
    must ask for the exact argv-only invocation.  File redirection, ``tee``,
    substitutions, comments, command chains, leading pipes, and arbitrary
    filters deliberately return ``None`` so mutation/maintenance policy retains
    precedence.
    """
    normalized = str(command or "").strip()
    control = _first_unquoted_shell_control(normalized)
    if control is None:
        return None
    offset, category = control
    suffix_offset = offset
    if category == "redirection" and offset > 0 and normalized[offset - 1] == "2" \
            and (offset == 1 or normalized[offset - 2].isspace()):
        suffix_offset = offset - 1
    prefix = normalized[:suffix_offset].rstrip()
    suffix = normalized[suffix_offset:].strip()
    if not prefix or not _OBSERVATIONAL_SUFFIX_RE.fullmatch(suffix):
        return None
    invocation = parse_exact_python_command(
        prefix, root=root, allowed_scripts=allowed_scripts,
    ) or _diagnostic_python_control_prefix(
        prefix, root=root, allowed_scripts=allowed_scripts,
    )
    if invocation is None:
        return None
    category = "stderr-merge" if suffix.lstrip().startswith("2") else "output-filter"
    if "|" in suffix:
        category = "output-filter"
    return PythonControlShapeIssue(
        code="XUNJI_E_LIFECYCLE_EXACT_ARGV_REQUIRED",
        category=category,
        script=invocation.script,
        args=invocation.args,
    )


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
    import tempfile
    from unittest import mock

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
        if "shape_issue" in case:
            issue = diagnose_python_control_shape(
                command,
                allowed_scripts={
                    (ROOT / "tools" / "setup_run.py").resolve(),
                    (ROOT / "tools" / "loop_bootstrap.py").resolve(),
                },
            )
            checks.append((
                f"{case['name']}: shape-issue",
                (issue.category if issue else "") == str(case["shape_issue"]),
            ))
    checks.extend((
        ("cancel-unlaunched exact Python argv parses as one control invocation",
         (lambda invocation: bool(
             invocation
             and invocation.args == (
                 "cancel-unlaunched", "runs/demo_20260101",
                 "A-web-hunter-001", "--reason", "inputs changed",
             )
         ))(parse_exact_python_command(
             f"{shlex.quote(sys.executable)} "
             f"{shlex.quote(str(ROOT / 'tools' / 'workers.py'))} "
             "cancel-unlaunched runs/demo_20260101 A-web-hunter-001 "
             "--reason 'inputs changed'",
             root=ROOT,
             allowed_scripts={(ROOT / "tools" / "workers.py").resolve()},
         ))),
        ("cancel-unlaunched shell chaining never parses as control",
         parse_exact_python_command(
             f"{shlex.quote(sys.executable)} "
             f"{shlex.quote(str(ROOT / 'tools' / 'workers.py'))} "
             "cancel-unlaunched runs/demo_20260101 A-web-hunter-001 "
             "--reason ok; echo forged",
             root=ROOT,
             allowed_scripts={(ROOT / "tools" / "workers.py").resolve()},
         ) is None),
        ("literal && chain splits only for diagnostic classification",
         (lambda first, second: split_literal_and_chain(
             f"{first} && {second}"
         ) == (first, second))(
             f"{shlex.quote(sys.executable)} "
             f"{shlex.quote(str(ROOT / 'tools' / 'workers.py'))} "
             "list runs/demo_20260101",
             f"{shlex.quote(sys.executable)} "
             f"{shlex.quote(str(ROOT / 'tools' / 'workers.py'))} "
             "status runs/demo_20260101",
         )),
        ("literal && diagnostic permits a static echo segment",
         (lambda first, second: split_literal_and_chain(
             f"{first} && echo '---' && {second}"
         ) == (first, "echo '---'", second))(
             f"{shlex.quote(sys.executable)} "
             f"{shlex.quote(str(ROOT / 'tools' / 'workers.py'))} "
             "list runs/demo_20260101",
             f"{shlex.quote(sys.executable)} "
             f"{shlex.quote(str(ROOT / 'tools' / 'workers.py'))} "
             "status runs/demo_20260101",
         )),
        ("non-literal or effectful shell chains stay opaque",
         (lambda command: all(split_literal_and_chain(candidate) is None for candidate in (
             command,
             command + " &&",
             command + " ; echo unsafe",
             command + " || echo unsafe",
             command + " | head -1",
             command + " > /tmp/forged",
             command + " && echo $(id)",
             command + " &&\necho unsafe",
         )))(
             f"{shlex.quote(sys.executable)} "
             f"{shlex.quote(str(ROOT / 'tools' / 'workers.py'))} "
             "list runs/demo_20260101"
         )),
        ("diagnostic chain count and byte budgets fail closed",
         (lambda command: bool(
             split_literal_and_chain(
                 " && ".join([command] * (_MAX_DIAGNOSTIC_CHAIN_SEGMENTS + 1))
             ) is None
             and split_literal_and_chain(
                 command + " && echo " + "x" * _MAX_DIAGNOSTIC_CHAIN_BYTES
             ) is None
         ))(
             f"{shlex.quote(sys.executable)} "
             f"{shlex.quote(str(ROOT / 'tools' / 'workers.py'))} "
             "list runs/demo_20260101"
         )),
        ("current absolute Python identity is trusted",
         trusted_python_token(sys.executable)),
        ("current canonical Python identity is trusted",
         trusted_python_token(str(Path(sys.executable).resolve(strict=True)))),
    ))
    with tempfile.TemporaryDirectory() as tmp:
        fake_python = Path(tmp) / "python3"
        fake_python.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
        fake_python.chmod(0o755)
        with mock.patch.dict(os.environ, {"PATH": str(Path(tmp))}):
            checks.append((
                "PATH-resolved bare Python cannot mint interpreter trust",
                not trusted_python_token("python3"),
            ))
        with mock.patch.object(shutil, "which", return_value=None):
            unavailable_clean = (
                f"python {ROOT / 'tools' / 'loop_bootstrap.py'} "
                "--source 'https://example.test/path?key=opaque' --type auto"
            )
            unavailable_wrapped = unavailable_clean + " 2>&1"
            checks.append((
                "unavailable bare Python alias is rejected",
                not trusted_python_token("python3.99"),
            ))
            checks.append((
                "clean unavailable bare Python cannot authorize lifecycle control",
                parse_exact_python_command(
                    unavailable_clean,
                    root=ROOT,
                    allowed_scripts={(ROOT / "tools" / "loop_bootstrap.py").resolve()},
                ) is None
                and local_setup_metadata_invocation(unavailable_clean) is None,
            ))
            issue = diagnose_python_control_shape(
                unavailable_wrapped,
                root=ROOT,
                allowed_scripts={(ROOT / "tools" / "loop_bootstrap.py").resolve()},
            )
            checks.append((
                "unavailable bare Python output wrapper remains diagnostic-only",
                issue is not None
                and issue.code == "XUNJI_E_LIFECYCLE_EXACT_ARGV_REQUIRED"
                and issue.category == "stderr-merge",
            ))
        alias_dir = Path(tmp) / "aliases"
        alias_dir.mkdir()
        interpreter_alias = alias_dir / "python3"
        interpreter_alias.symlink_to(sys.executable)
        documented_setup = (
            f"python3 {shlex.quote(str(ROOT / 'tools' / 'setup_run.py'))} "
            "alpha --target https://example.test/ --date 20260714"
        )
        with mock.patch.dict(os.environ, {"PATH": str(alias_dir)}):
            checks.extend((
                (
                    "documented bare python3 resolves to the running interpreter",
                    trusted_python_token("python3"),
                ),
                (
                    "documented setup argv reaches the exact Hook parser",
                    parse_exact_python_command(
                        documented_setup,
                        root=ROOT,
                        allowed_scripts={
                            (ROOT / "tools" / "setup_run.py").resolve(),
                        },
                    ) is not None
                    and local_setup_metadata_invocation(documented_setup) is not None,
                ),
            ))
        checks.append((
            "attacker-controlled absolute interpreter alias is rejected",
            not trusted_python_token(str(interpreter_alias)),
        ))
        script_alias = alias_dir / "setup_run.py"
        script_alias.symlink_to(ROOT / "tools" / "setup_run.py")
        checks.append((
            "attacker-controlled script alias cannot impersonate an allowed script",
            parse_exact_python_command(
                f"{shlex.quote(sys.executable)} {shlex.quote(str(script_alias))} "
                "alpha --target https://example.test/",
                root=ROOT,
                allowed_scripts={(ROOT / "tools" / "setup_run.py").resolve()},
            ) is None,
        ))
        checks.append((
            "inline PATH cannot alter an exact Python control environment",
            parse_exact_python_command(
                f"PATH={tmp} {shlex.quote(sys.executable)} "
                f"{ROOT / 'tools' / 'setup_run.py'} "
                "alpha --target https://example.test/",
                root=ROOT,
                allowed_scripts={(ROOT / "tools" / "setup_run.py").resolve()},
                allow_environment=True,
            ) is None,
        ))
    bad = [name for name, ok in checks if not ok]
    for name, ok in checks:
        print(("ok   " if ok else "FAIL ") + name)
    print("command_shape selftest " + ("passed" if not bad else f"FAILED ({len(bad)})"))
    return 0 if not bad else 1


if __name__ == "__main__":
    raise SystemExit(selftest())
