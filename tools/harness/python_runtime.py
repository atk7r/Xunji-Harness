#!/usr/bin/env python3
"""Canonical Python runtime identity for the Xunji repository.

All governed project commands run through ``.venv/bin/python``. The one
documented exception is the bootstrap command that creates ``.venv``.
"""

from __future__ import annotations

import os
from pathlib import Path
import stat
import sys


ROOT = Path(__file__).resolve().parents[2]
CANONICAL_VENV = Path(".venv")
CANONICAL_PYTHON = CANONICAL_VENV / "bin" / "python"
MIN_VERSION = (3, 10)


def display_token() -> str:
    """Return the repository-relative token rendered into model-facing argv."""
    return CANONICAL_PYTHON.as_posix()


def canonical_path(root: str | Path = ROOT) -> Path:
    return Path(root) / CANONICAL_PYTHON


def _executable_identity(path: Path) -> tuple[Path, int, int] | None:
    try:
        resolved = path.resolve(strict=True)
        metadata = resolved.stat()
        if not stat.S_ISREG(metadata.st_mode) or not os.access(resolved, os.X_OK):
            return None
        return resolved, metadata.st_dev, metadata.st_ino
    except (OSError, RuntimeError, ValueError):
        return None


def token_is_canonical(
    token: str,
    *,
    root: str | Path = ROOT,
    current_executable: str | Path | None = None,
) -> bool:
    """Accept only this repository's exact ``.venv`` interpreter spelling."""
    base = Path(root)
    expected = canonical_path(base)
    lexical = Path(str(token or ""))
    if lexical.is_absolute():
        try:
            if Path(os.path.abspath(lexical)) != Path(os.path.abspath(expected)):
                return False
        except (OSError, RuntimeError, ValueError):
            return False
    elif lexical.as_posix() != display_token():
        return False
    expected_identity = _executable_identity(expected)
    if expected_identity is None or not (base / CANONICAL_VENV / "pyvenv.cfg").is_file():
        return False
    if current_executable is None:
        return True
    current = Path(current_executable)
    return current.is_absolute() and _executable_identity(current) == expected_identity


def environment_errors(
    *,
    root: str | Path = ROOT,
    executable: str | Path = sys.executable,
    prefix: str | Path = sys.prefix,
    version: tuple[int, int] = sys.version_info[:2],
) -> list[str]:
    """Return stable diagnostics for a non-canonical project interpreter."""
    base = Path(root)
    errors: list[str] = []
    if tuple(version) < MIN_VERSION:
        errors.append("PYTHON_VERSION_UNSUPPORTED")
    if Path(os.path.abspath(prefix)) != Path(os.path.abspath(base / CANONICAL_VENV)):
        errors.append("PYTHON_VENV_PREFIX_MISMATCH")
    if not token_is_canonical(
        str(canonical_path(base)), root=base, current_executable=executable
    ):
        errors.append("PYTHON_VENV_EXECUTABLE_MISMATCH")
    return errors


def require_environment(*, root: str | Path = ROOT) -> None:
    errors = environment_errors(root=root)
    if errors:
        raise RuntimeError(
            ",".join(errors) + f"; run project commands with {display_token()}"
        )
