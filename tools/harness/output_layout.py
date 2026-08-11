#!/usr/bin/env python3
"""Canonical output placement for Xunji tools.

Live engagement artifacts belong to one run.  Standalone/local invocations use
the repository ``tmp/`` tree and never inherit the caller's current directory as
an output destination.  This module resolves paths only; evidence promotion and
closure remain owned by their existing gates.
"""
from __future__ import annotations

import argparse
import os
import re
import secrets
import shutil
import tempfile
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
_SAFE_TOOL = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,63}\Z")
_SAFE_INVOCATION = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,95}\Z")


class OutputLayoutError(ValueError):
    """Raised before I/O when an output path violates the layout contract."""


def invocation_id(*, now: float | None = None, token: str | None = None) -> str:
    stamp = time.strftime("%Y%m%dT%H%M%SZ", time.gmtime(time.time() if now is None else now))
    suffix = token if token is not None else secrets.token_hex(4)
    value = f"{stamp}-{suffix}"
    if not _SAFE_INVOCATION.fullmatch(value):
        raise OutputLayoutError("invalid output invocation id")
    return value


def _tool_name(tool: str) -> str:
    if not _SAFE_TOOL.fullmatch(tool):
        raise OutputLayoutError("invalid output tool name")
    return tool


def _resolve_from_repo(path: Path, repo_root: Path) -> Path:
    return (path if path.is_absolute() else repo_root / path).resolve(strict=False)


def _reject_managed_root_symlink(path: Path, repo_root: Path, message: str) -> None:
    """Reject existing symlinks below the repository anchor in a managed root."""
    root_lexical = Path(os.path.abspath(repo_root))
    path_lexical = Path(os.path.abspath(path if path.is_absolute() else repo_root / path))
    try:
        relative = path_lexical.relative_to(root_lexical)
    except ValueError:
        raise OutputLayoutError(message) from None
    current = root_lexical
    for part in relative.parts:
        current = current / part
        if current.is_symlink():
            raise OutputLayoutError(message)


def _within(path: Path, parent: Path) -> bool:
    try:
        path.relative_to(parent)
        return True
    except ValueError:
        return False


def _require_within(path: Path, parent: Path, message: str) -> None:
    if not _within(path, parent):
        raise OutputLayoutError(message)


def _managed_tmp_root(repo_root: Path) -> Path:
    raw = repo_root / "tmp"
    _reject_managed_root_symlink(
        raw, repo_root,
        "standalone scratch root must not contain symlinks",
    )
    return _resolve_from_repo(raw, repo_root)


def scratch_dir(
    tool: str,
    *,
    invocation: str | None = None,
    repo_root: Path = ROOT,
) -> Path:
    tool = _tool_name(tool)
    _managed_tmp_root(repo_root)
    invocation = invocation or invocation_id()
    if not _SAFE_INVOCATION.fullmatch(invocation):
        raise OutputLayoutError("invalid output invocation id")
    candidate = repo_root / "tmp" / tool / invocation
    _reject_managed_root_symlink(
        candidate, repo_root,
        "standalone scratch path must not contain symlinks",
    )
    return candidate


def _normalized_name(value: str, *, default_suffix: str | None) -> str:
    if not value or value in {".", ".."} or "\x00" in value:
        raise OutputLayoutError("output filename must be non-empty")
    name = Path(value).name
    if name.endswith(".replay.json"):
        raise OutputLayoutError(
            "--save names the response body; omit the .replay.json suffix because "
            "the replay sidecar is generated automatically"
        )
    if default_suffix and "." not in name:
        name += default_suffix
    return name


def resolve_artifact_file(
    value: str | None,
    *,
    run: str | Path | None,
    tool: str,
    invocation: str | None = None,
    default_suffix: str | None = None,
    repo_root: Path = ROOT,
    reject_replay_name: bool = True,
) -> Path | None:
    """Resolve one saved file into run/evidence or repository tmp.

    A basename is placed automatically.  Explicit paths remain supported only
    when they are already contained by the applicable managed root.
    """
    if value is None:
        return None
    raw_value = str(value)
    name = _normalized_name(
        raw_value,
        default_suffix=default_suffix,
    ) if reject_replay_name else Path(raw_value).name
    if not name or name in {".", ".."} or "\x00" in raw_value:
        raise OutputLayoutError("output filename must be non-empty")
    has_separator = "/" in raw_value or "\\" in raw_value
    explicit_candidate = Path(raw_value)
    if has_separator and explicit_candidate.name != name:
        explicit_candidate = explicit_candidate.with_name(name)

    if run is not None:
        run_path = Path(run)
        evidence_path = run_path / "evidence"
        _reject_managed_root_symlink(
            evidence_path, repo_root,
            "live artifact root must not contain symlinks",
        )
        allowed = _resolve_from_repo(evidence_path, repo_root)
        candidate = explicit_candidate if has_separator else evidence_path / name
        resolved = _resolve_from_repo(candidate, repo_root)
        _require_within(
            resolved,
            allowed,
            "live artifact output must stay inside <run>/evidence/",
        )
        return resolved

    managed_tmp = _managed_tmp_root(repo_root)
    if has_separator:
        candidate = explicit_candidate
        resolved = _resolve_from_repo(candidate, repo_root)
        _require_within(
            resolved,
            managed_tmp,
            "standalone output paths must stay inside repository tmp/",
        )
        return resolved
    return scratch_dir(tool, invocation=invocation, repo_root=repo_root) / name


def resolve_artifact_dir(
    value: str | None,
    *,
    run: str | Path | None,
    tool: str,
    invocation: str | None = None,
    default_leaf: str | None = None,
    unique_run_dir: bool = False,
    repo_root: Path = ROOT,
) -> Path:
    """Resolve an artifact directory into run/evidence or repository tmp."""
    invocation = invocation or invocation_id()
    if run is not None:
        run_path = Path(run)
        allowed_raw = run_path / "evidence"
        _reject_managed_root_symlink(
            allowed_raw, repo_root,
            "live artifact root must not contain symlinks",
        )
        allowed = _resolve_from_repo(allowed_raw, repo_root)
        if value:
            candidate = Path(value)
        else:
            candidate = allowed_raw
            if default_leaf:
                candidate = candidate / default_leaf
            if unique_run_dir:
                candidate = candidate / invocation
        resolved = _resolve_from_repo(candidate, repo_root)
        _require_within(
            resolved,
            allowed,
            "live artifact directory must stay inside <run>/evidence/",
        )
        return resolved

    if value:
        candidate = Path(value)
        managed_tmp = _managed_tmp_root(repo_root)
        _require_within(
            _resolve_from_repo(candidate, repo_root),
            managed_tmp,
            "standalone output directories must stay inside repository tmp/",
        )
        return _resolve_from_repo(candidate, repo_root)
    candidate = scratch_dir(tool, invocation=invocation, repo_root=repo_root)
    return candidate / default_leaf if default_leaf else candidate


def resolve_run_bucket_dir(
    value: str | None,
    *,
    run: str | Path | None,
    bucket: str,
    tool: str,
    invocation: str | None = None,
    repo_root: Path = ROOT,
) -> Path:
    """Resolve a non-evidence run bucket, with standalone fallback to tmp/."""
    bucket = _tool_name(bucket)
    if run is not None:
        run_path = Path(run)
        allowed_raw = run_path / bucket
        _reject_managed_root_symlink(
            allowed_raw, repo_root,
            f"live output root <run>/{bucket}/ must not contain symlinks",
        )
        allowed = _resolve_from_repo(allowed_raw, repo_root)
        candidate = Path(value) if value else allowed_raw
        _require_within(
            _resolve_from_repo(candidate, repo_root),
            allowed,
            f"live output directory must stay inside <run>/{bucket}/",
        )
        return _resolve_from_repo(candidate, repo_root)
    if value:
        candidate = Path(value)
        managed_tmp = _managed_tmp_root(repo_root)
        _require_within(
            _resolve_from_repo(candidate, repo_root),
            managed_tmp,
            "standalone output directories must stay inside repository tmp/",
        )
        return _resolve_from_repo(candidate, repo_root)
    return scratch_dir(tool, invocation=invocation, repo_root=repo_root)


def resolve_run_state_file(
    value: str | None,
    *,
    run: str | Path | None,
    tool: str,
    invocation: str | None = None,
    default_leaf: str = "http",
    repo_root: Path = ROOT,
) -> Path | None:
    """Resolve mutable local session state without mixing it with evidence.

    A live run stores basename state under ``state/<default_leaf>/``.  An
    explicit live path may select another location only inside ``state/``.
    Standalone state follows the same per-invocation tmp rule as artifacts.
    """
    if value is None:
        return None
    raw_value = str(value)
    if not raw_value or raw_value in {".", ".."} or "\x00" in raw_value:
        raise OutputLayoutError("state filename must be non-empty")
    name = Path(raw_value).name
    if not name or name in {".", ".."}:
        raise OutputLayoutError("state filename must be non-empty")
    has_separator = "/" in raw_value or "\\" in raw_value
    if run is not None:
        run_path = Path(run)
        allowed_raw = run_path / "state"
        _reject_managed_root_symlink(
            allowed_raw, repo_root,
            "live state root must not contain symlinks",
        )
        allowed = _resolve_from_repo(allowed_raw, repo_root)
        candidate = Path(raw_value) if has_separator \
            else allowed_raw / default_leaf / name
        resolved = _resolve_from_repo(candidate, repo_root)
        _require_within(
            resolved,
            allowed,
            "live mutable session state must stay inside <run>/state/",
        )
        return resolved
    if has_separator:
        candidate = Path(raw_value)
        managed_tmp = _managed_tmp_root(repo_root)
        resolved = _resolve_from_repo(candidate, repo_root)
        _require_within(
            resolved,
            managed_tmp,
            "standalone mutable session state must stay inside repository tmp/",
        )
        return resolved
    return scratch_dir(tool, invocation=invocation, repo_root=repo_root) / name


def selftest() -> int:
    root = Path(tempfile.mkdtemp())
    run = root / "runs" / "demo_20260101"
    checks: list[tuple[str, bool]] = []
    try:
        checks.append((
            "run basename lands in evidence",
            resolve_artifact_file(
                "proof", run=run, tool="probe", invocation="case-1",
                default_suffix=".html", repo_root=root,
            ) == (run / "evidence" / "proof.html").resolve(strict=False),
        ))
        checks.append((
            "standalone basename lands in invocation scratch",
            resolve_artifact_file(
                "proof.html", run=None, tool="probe", invocation="case-2",
                repo_root=root,
            ) == root / "tmp" / "probe" / "case-2" / "proof.html",
        ))
        checks.append((
            "run cookie state is separate from evidence",
            resolve_run_state_file(
                "cookies.json", run=run, tool="probe", invocation="case-2",
                repo_root=root,
            ) == (run / "state" / "http" / "cookies.json").resolve(strict=False),
        ))
        explicit = root / "runs" / "demo_20260101" / "evidence" / "nested" / "proof.json"
        checks.append((
            "explicit run evidence path is preserved",
            resolve_artifact_file(
                str(explicit), run=run, tool="probe", invocation="case-3",
                repo_root=root,
            ) == explicit.resolve(strict=False),
        ))
        for label, value, kwargs in (
            ("run root output rejected", str(run / "loose.html"), {"run": run}),
            ("standalone cwd output rejected", "outside/proof.html", {"run": None}),
            ("replay-as-body rejected", "proof.replay.json", {"run": run}),
            ("run traversal rejected", str(run / "evidence" / ".." / "escape.html"), {"run": run}),
        ):
            rejected = False
            try:
                resolve_artifact_file(
                    value, tool="probe", invocation="case-4", repo_root=root,
                    **kwargs,
                )
            except OutputLayoutError:
                rejected = True
            checks.append((label, rejected))
        outside = root / "outside"
        outside.mkdir()
        (run / "evidence").parent.mkdir(parents=True, exist_ok=True)
        try:
            (run / "evidence").symlink_to(outside, target_is_directory=True)
            symlink_rejected = False
            try:
                resolve_artifact_file(
                    "symlink.html", run=run, tool="probe", invocation="case-5",
                    repo_root=root,
                )
            except OutputLayoutError:
                symlink_rejected = True
            checks.append(("existing evidence symlink escape rejected", symlink_rejected))
        finally:
            try:
                (run / "evidence").unlink()
            except OSError:
                pass
        (run / "evidence").mkdir(parents=True, exist_ok=True)
        (run / "evidence" / "nested").symlink_to(outside, target_is_directory=True)
        nested_symlink_rejected = False
        try:
            resolve_artifact_file(
                str(run / "evidence" / "nested" / "escape.html"),
                run=run, tool="probe", invocation="case-5b", repo_root=root,
            )
        except OutputLayoutError:
            nested_symlink_rejected = True
        checks.append(("intermediate evidence symlink escape rejected", nested_symlink_rejected))
        (run / "evidence" / "nested").unlink()
        try:
            (root / "tmp").symlink_to(outside, target_is_directory=True)
            standalone_symlink_cases = (
                ("default file", lambda: resolve_artifact_file(
                    "scratch.html", run=None, tool="probe", invocation="case-6",
                    repo_root=root,
                )),
                ("explicit file", lambda: resolve_artifact_file(
                    "tmp/probe/manual.html", run=None, tool="probe",
                    invocation="case-6", repo_root=root,
                )),
                ("explicit artifact dir", lambda: resolve_artifact_dir(
                    "tmp/render/manual", run=None, tool="render",
                    invocation="case-6", repo_root=root,
                )),
                ("explicit bucket dir", lambda: resolve_run_bucket_dir(
                    "tmp/classify/manual", run=None, bucket="classify",
                    tool="classify", invocation="case-6", repo_root=root,
                )),
                ("explicit state file", lambda: resolve_run_state_file(
                    "tmp/probe/cookies.json", run=None, tool="probe",
                    invocation="case-6", repo_root=root,
                )),
            )
            for case_name, resolver in standalone_symlink_cases:
                rejected = False
                try:
                    resolver()
                except OutputLayoutError:
                    rejected = True
                checks.append((
                    f"existing tmp symlink rejects standalone {case_name}",
                    rejected,
                ))
        finally:
            try:
                (root / "tmp").unlink()
            except OSError:
                pass
        (root / "tmp").mkdir()
        implicit_symlink_cases = (
            ("file", "probe", lambda: resolve_artifact_file(
                "scratch.html", run=None, tool="probe", invocation="case-7",
                repo_root=root,
            )),
            ("artifact dir", "render", lambda: resolve_artifact_dir(
                None, run=None, tool="render", invocation="case-7",
                repo_root=root,
            )),
            ("bucket dir", "classify", lambda: resolve_run_bucket_dir(
                None, run=None, bucket="classify", tool="classify",
                invocation="case-7", repo_root=root,
            )),
            ("state file", "state-probe", lambda: resolve_run_state_file(
                "cookies.json", run=None, tool="state-probe", invocation="case-7",
                repo_root=root,
            )),
        )
        for case_name, tool_dir, resolver in implicit_symlink_cases:
            link = root / "tmp" / tool_dir
            link.symlink_to(outside, target_is_directory=True)
            rejected = False
            try:
                resolver()
            except OutputLayoutError:
                rejected = True
            checks.append((
                f"implicit standalone {case_name} rejects tool-directory symlink",
                rejected,
            ))
            link.unlink()
        first = resolve_artifact_dir(
            None, run=run, tool="render", invocation="attempt-a",
            default_leaf="render_example.test", unique_run_dir=True,
            repo_root=root,
        )
        second = resolve_artifact_dir(
            None, run=run, tool="render", invocation="attempt-b",
            default_leaf="render_example.test", unique_run_dir=True,
            repo_root=root,
        )
        checks.append((
            "run render attempts use distinct directories",
            first != second
            and first == (run / "evidence" / "render_example.test" / "attempt-a").resolve(strict=False),
        ))
        checks.append((
            "classify output stays in its canonical run bucket",
            resolve_run_bucket_dir(
                None, run=run, bucket="classify", tool="classify",
                invocation="case-5", repo_root=root,
            ) == (run / "classify").resolve(strict=False),
        ))
    finally:
        shutil.rmtree(root, ignore_errors=True)
    bad = [name for name, ok in checks if not ok]
    for name, ok in checks:
        print(("ok   " if ok else "FAIL ") + name)
    print("output layout selftest " + ("passed" if not bad else f"FAILED ({len(bad)})"))
    return 0 if not bad else 1


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate Xunji output layout helpers.")
    parser.add_argument("--selftest", action="store_true")
    args = parser.parse_args()
    if args.selftest:
        return selftest()
    parser.error("use --selftest")


if __name__ == "__main__":
    raise SystemExit(main())
