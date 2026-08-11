#!/usr/bin/env python3
"""Recoverable single-writer owner for Xunji run completion.

``prepare`` freezes the canonical closure bundle and receipt identities but does
not change canonical Markdown. ``commit`` performs the only READY -> FINAL and
completion-marker writes under a manifest CAS. ``reopen`` is the only supported
inverse.  A prepared/terminal intent is made durable before either canonical
file changes, so retry can only continue the exact frozen transaction.

This owner deliberately does not decide whether a finding is true.  It binds
the facts already admitted by the run owners and rejects caller prose as a
substitute for the S3 plan, Reason, completion-review, cycle-end, check-run, or
independent-review receipts.
"""
from __future__ import annotations

import argparse
import base64
import contextlib
import hashlib
import json
import os
import re
import stat
import sys
import tempfile
import time
import uuid
from pathlib import Path
from typing import Iterable

try:
    import fcntl
except ImportError:  # pragma: no cover - supported fallback is single process
    fcntl = None

import anti_drift
import contract_schema
import loop_journal
import runtime_receipts
import turn_contract
import work_plan
from evidence_parse import current_evidence_index_hash, parse_evidence


SCHEMA = "xunji.completion-transaction.v1"
SCHEMA_FILE = "completion-transaction.v1.schema.json"
POLICY_SCHEMA = "xunji.review-policy.v1"
POLICY_SCHEMA_FILE = "review-policy.v1.schema.json"
CURRENT_REL = Path("state/completion_transaction.json")
TRANSACTIONS_REL = Path("state/completion_transactions")
POLICY_REL = Path("state/review_policy.json")
LOCK_REL = Path("state/.completion_transaction.lock")
CHECK_TOKEN_PREFIX = "XUNJI_CHECK_RUN_V1 "
CHECK_TOKEN_SCHEMA = "xunji.check-run-token.v1"
MAX_COMPLETION_FILE_BYTES = 64 * 1024 * 1024

CANONICAL_PATHS = (
    "target.md", "surface.md", "surface_recon.md", "hypotheses.md",
    "frontier.md", "evidence.md", "false_positive.md", "report.md",
    "retrospective.md", "review.md", "decisions.md", "chains.md",
    "hints.md",
)
FROZEN_STATE_PATHS = (
    "state/work_plan.json",
    "state/work_plan_transaction.json",
    "state/reason_pass_receipts.jsonl",
    "state/loop_journal.jsonl",
    "state/review_policy.json",
)
CLOSURE_INPUT_PATHS = tuple(sorted(set(
    CANONICAL_PATHS + FROZEN_STATE_PATHS + (
        "state/turn_contract.json",
        "coverage.json",
        "state/conflicts.json",
        "state/assignments.json",
        "state/loop_state.json",
        "review/review_bundle.json",
    )
)))
HEX64 = re.compile(r"^[0-9a-f]{64}$")
MARKER_RE = re.compile(
    r"(?m)^\s*(GHOST_COMPLETE|NORMAL_COMPLETE)"
    r"(?:\s+receipt=([0-9a-f]{64}))?\s*$")
REVIEW_RECEIPT_RE = re.compile(
    r"(?im)^\s*-\s*ReviewReceipt\s*[:：]\s*([0-9a-f]{64})\s*$")
STATUS_RE = re.compile(r"(?im)^(\s*-\s*Status\s*[:：]\s*)([^\r\n]*)(\r?)$")


class CompletionError(RuntimeError):
    def __init__(self, code: str, detail: str = ""):
        self.code = code
        self.detail = detail
        super().__init__(code + (f": {detail}" if detail else ""))


def default_review_policy() -> dict:
    """Return the one setup/adoption policy without sharing mutable state."""
    return {
        "schema": POLICY_SCHEMA,
        "policy_id": "live-run-review.v1",
        "slots": [
            {
                "slot_id": "independent-review",
                "role": "independent-reviewer",
                "requirement": "mandatory",
            },
            {
                "slot_id": "external-assistance",
                "role": "external-assistance",
                "requirement": "optional",
            },
        ],
    }


def _json_bytes(value: object) -> bytes:
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
    ).encode("utf-8")


def _json_hash(value: object) -> str:
    return hashlib.sha256(_json_bytes(value)).hexdigest()


def _bytes_hash(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _resolve_run(run_dir: str | Path) -> Path:
    source = Path(run_dir)
    try:
        run = source.resolve(strict=True)
    except OSError as exc:
        raise CompletionError("COMPLETION_RUN_INVALID", exc.__class__.__name__) from exc
    if not run.is_dir() or not (run / "frontier.md").is_file():
        raise CompletionError("COMPLETION_RUN_INVALID")
    if not run.name or len(run.name) > 255:
        raise CompletionError("COMPLETION_RUN_NAME_INVALID")
    return run


def _contained_path(run: Path, relative: str | Path, *, must_exist: bool) -> Path:
    raw = Path(relative)
    if raw.is_absolute() or ".." in raw.parts or not raw.parts:
        raise CompletionError("COMPLETION_PATH_INVALID", str(relative))
    current = run
    for part in raw.parts[:-1]:
        current = current / part
        if current.exists() and current.is_symlink():
            raise CompletionError("COMPLETION_PATH_SYMLINK", raw.as_posix())
    path = run / raw
    if must_exist:
        try:
            resolved = path.resolve(strict=True)
        except OSError as exc:
            raise CompletionError(
                "COMPLETION_FILE_UNAVAILABLE", raw.as_posix()) from exc
        try:
            resolved.relative_to(run)
        except ValueError as exc:
            raise CompletionError("COMPLETION_PATH_ESCAPE", raw.as_posix()) from exc
    return path


def _directory_open_flags() -> int:
    return (
        os.O_RDONLY
        | getattr(os, "O_CLOEXEC", 0)
        | getattr(os, "O_DIRECTORY", 0)
        | getattr(os, "O_NOFOLLOW", 0)
    )


def _open_directory_path(path: Path) -> int:
    """Open one resolved absolute directory without following later components."""
    resolved = path.resolve(strict=True)
    descriptor = os.open(os.path.sep, _directory_open_flags())
    try:
        for part in resolved.parts[1:]:
            child = os.open(part, _directory_open_flags(), dir_fd=descriptor)
            os.close(descriptor)
            descriptor = child
        return descriptor
    except OSError as exc:
        os.close(descriptor)
        raise CompletionError(
            "COMPLETION_PATH_OPEN_FAILED", path.as_posix()) from exc


def _open_relative_regular(run: Path, relative: Path) -> tuple[int, int, tuple[int, int]]:
    parts = relative.parts
    if not parts or any(part in {"", ".", ".."} for part in parts):
        raise CompletionError("COMPLETION_PATH_INVALID", relative.as_posix())
    try:
        anchor_before = os.stat(run, follow_symlinks=False)
        parent = _open_directory_path(run)
        anchor_fd = os.fstat(parent)
        if (anchor_before.st_dev, anchor_before.st_ino) != (
                anchor_fd.st_dev, anchor_fd.st_ino):
            raise CompletionError("COMPLETION_RUN_CHANGED_DURING_READ")
        for part in parts[:-1]:
            child = os.open(part, _directory_open_flags(), dir_fd=parent)
            os.close(parent)
            parent = child
        flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) \
            | getattr(os, "O_NOFOLLOW", 0)
        leaf = os.open(parts[-1], flags, dir_fd=parent)
        return leaf, parent, (anchor_before.st_dev, anchor_before.st_ino)
    except CompletionError:
        try:
            os.close(parent)
        except (NameError, OSError):
            pass
        raise
    except OSError as exc:
        try:
            os.close(parent)
        except (NameError, OSError):
            pass
        raise CompletionError(
            "COMPLETION_FILE_READ_FAILED", relative.as_posix()) from exc


def _file_identity(value: os.stat_result) -> tuple[int, int, int, int, int]:
    return (
        value.st_dev, value.st_ino, value.st_size,
        value.st_mtime_ns, value.st_ctime_ns,
    )


def _stable_bytes(
    run: Path,
    relative: str | Path,
    *,
    max_bytes: int = MAX_COMPLETION_FILE_BYTES,
) -> bytes:
    raw = Path(relative)
    _contained_path(run, raw, must_exist=False)
    descriptor, parent, anchor_identity = _open_relative_regular(run, raw)
    payload = bytearray()
    try:
        before = os.fstat(descriptor)
        path_before = os.stat(
            raw.parts[-1], dir_fd=parent, follow_symlinks=False)
        if not stat.S_ISREG(before.st_mode) or not stat.S_ISREG(path_before.st_mode) \
                or (before.st_dev, before.st_ino) != (
                    path_before.st_dev, path_before.st_ino):
            raise CompletionError("COMPLETION_FILE_NOT_REGULAR", raw.as_posix())
        if before.st_size > max_bytes:
            raise CompletionError("COMPLETION_FILE_TOO_LARGE", raw.as_posix())
        total = 0
        while True:
            chunk = os.read(descriptor, min(64 * 1024, max_bytes + 1 - total))
            if not chunk:
                break
            total += len(chunk)
            if total > max_bytes:
                raise CompletionError("COMPLETION_FILE_TOO_LARGE", raw.as_posix())
            payload.extend(chunk)
        after = os.fstat(descriptor)
        path_after = os.stat(
            raw.parts[-1], dir_fd=parent, follow_symlinks=False)
        if _file_identity(before) != _file_identity(after) \
                or _file_identity(before) != _file_identity(path_after) \
                or total != before.st_size:
            raise CompletionError(
                "COMPLETION_FILE_CHANGED_DURING_READ", raw.as_posix())

        fresh_leaf, fresh_parent, fresh_anchor = _open_relative_regular(run, raw)
        try:
            fresh = os.fstat(fresh_leaf)
        finally:
            os.close(fresh_leaf)
            os.close(fresh_parent)
        if fresh_anchor != anchor_identity \
                or _file_identity(fresh) != _file_identity(before):
            raise CompletionError(
                "COMPLETION_FILE_CHANGED_DURING_READ", raw.as_posix())
        return bytes(payload)
    except CompletionError:
        raise
    except OSError as exc:
        raise CompletionError(
            "COMPLETION_FILE_READ_FAILED", raw.as_posix()) from exc
    finally:
        os.close(descriptor)
        os.close(parent)


def _strict_text(value: bytes, label: str) -> str:
    try:
        return value.decode("utf-8", "strict")
    except UnicodeDecodeError as exc:
        raise CompletionError("COMPLETION_UTF8_INVALID", label) from exc


def _strict_json(value: bytes, label: str) -> dict:
    try:
        parsed = json.loads(_strict_text(value, label))
    except json.JSONDecodeError as exc:
        raise CompletionError("COMPLETION_JSON_INVALID", label) from exc
    if not isinstance(parsed, dict):
        raise CompletionError("COMPLETION_JSON_SHAPE_INVALID", label)
    return parsed


def _jsonl(value: bytes, label: str) -> list[dict]:
    rows: list[dict] = []
    for line_no, raw in enumerate(_strict_text(value, label).splitlines(), 1):
        if not raw.strip():
            continue
        try:
            row = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise CompletionError(
                "COMPLETION_JSONL_INVALID", f"{label}:{line_no}") from exc
        if not isinstance(row, dict):
            raise CompletionError(
                "COMPLETION_JSONL_SHAPE_INVALID", f"{label}:{line_no}")
        rows.append(row)
    return rows


def _fsync_directory(path: Path) -> None:
    flags = os.O_RDONLY
    if hasattr(os, "O_DIRECTORY"):
        flags |= os.O_DIRECTORY
    descriptor = os.open(path, flags)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _prepare_parent(run: Path, path: Path) -> None:
    try:
        path.relative_to(run)
    except ValueError as exc:
        raise CompletionError("COMPLETION_WRITE_PATH_ESCAPE") from exc
    relative = path.relative_to(run)
    current = run
    for part in relative.parts[:-1]:
        current = current / part
        if current.exists() and current.is_symlink():
            raise CompletionError(
                "COMPLETION_WRITE_PARENT_SYMLINK", relative.as_posix())
        if not current.exists():
            current.mkdir(mode=0o700)
            _fsync_directory(current.parent)
        elif not current.is_dir():
            raise CompletionError(
                "COMPLETION_WRITE_PARENT_INVALID", relative.as_posix())


def _atomic_bytes(run: Path, path: Path, value: bytes, *, mode: int = 0o600) -> None:
    _prepare_parent(run, path)
    raw = ""
    try:
        descriptor, raw = tempfile.mkstemp(prefix=path.name + ".", dir=path.parent)
        with os.fdopen(descriptor, "wb") as handle:
            written = handle.write(value)
            if written != len(value):
                raise OSError("short write")
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(raw, mode)
        os.replace(raw, path)
        _fsync_directory(path.parent)
    except OSError as exc:
        raise CompletionError("COMPLETION_DURABILITY_FAILED", path.name) from exc
    finally:
        try:
            if raw:
                os.unlink(raw)
        except OSError:
            pass


def _atomic_json(run: Path, path: Path, value: object) -> None:
    body = json.dumps(
        value, ensure_ascii=False, indent=2, sort_keys=True).encode("utf-8") + b"\n"
    _atomic_bytes(run, path, body)


@contextlib.contextmanager
def _completion_lock(run: Path):
    path = run / LOCK_REL
    _prepare_parent(run, path)
    flags = os.O_RDWR | os.O_CREAT | getattr(os, "O_CLOEXEC", 0) \
        | getattr(os, "O_NOFOLLOW", 0)
    try:
        descriptor = os.open(path, flags, 0o600)
    except OSError as exc:
        raise CompletionError("COMPLETION_LOCK_INVALID") from exc
    with os.fdopen(descriptor, "a+", encoding="utf-8") as handle:
        opened = os.fstat(handle.fileno())
        if not stat.S_ISREG(opened.st_mode):
            raise CompletionError("COMPLETION_LOCK_INVALID")
        if fcntl is not None:
            try:
                fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
            except OSError as exc:
                raise CompletionError("COMPLETION_LOCK_INVALID") from exc
        try:
            try:
                current = os.stat(path, follow_symlinks=False)
            except OSError as exc:
                raise CompletionError("COMPLETION_LOCK_REPLACED") from exc
            if (opened.st_dev, opened.st_ino) != (current.st_dev, current.st_ino):
                raise CompletionError("COMPLETION_LOCK_REPLACED")
            yield
        finally:
            try:
                current = os.stat(path, follow_symlinks=False)
                if (opened.st_dev, opened.st_ino) != (
                        current.st_dev, current.st_ino):
                    raise CompletionError("COMPLETION_LOCK_REPLACED")
            except OSError as exc:
                raise CompletionError("COMPLETION_LOCK_REPLACED") from exc
            if fcntl is not None:
                try:
                    fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
                except OSError as exc:
                    raise CompletionError("COMPLETION_LOCK_INVALID") from exc


def _manifest_entry(run: Path, relative: str, *, required: bool = False) -> dict:
    path = _contained_path(run, relative, must_exist=False)
    try:
        metadata = path.lstat()
    except FileNotFoundError:
        if required:
            raise CompletionError("COMPLETION_FILE_UNAVAILABLE", relative)
        return {"path": relative, "present": False, "sha256": "", "size": 0}
    except OSError as exc:
        raise CompletionError("COMPLETION_FILE_READ_FAILED", relative) from exc
    if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISREG(metadata.st_mode):
        raise CompletionError("COMPLETION_FILE_NOT_REGULAR", relative)
    value = _stable_bytes(run, relative)
    return {
        "path": relative,
        "present": True,
        "sha256": _bytes_hash(value),
        "size": len(value),
    }


def _closure_paths(
    run: Path,
    receipt_hashes: Iterable[str] = (),
    *,
    include_runtime: bool,
) -> list[str]:
    """Return every current input whose absence or bytes affect closure."""
    paths = set(CLOSURE_INPUT_PATHS)
    if include_runtime:
        paths.add("state/runtime_events.jsonl")
    review_text = ""
    try:
        review_text = _strict_text(_stable_bytes(run, "review.md"), "review.md")
    except CompletionError:
        if (run / "review.md").exists():
            raise
    review_hashes = set(REVIEW_RECEIPT_RE.findall(review_text))
    review_hashes.update(str(item) for item in receipt_hashes)
    for digest in review_hashes:
        if not HEX64.fullmatch(digest):
            raise CompletionError("COMPLETION_REVIEW_RECEIPT_INVALID", digest)
        paths.add(f"review/receipts/{digest}.json")

    try:
        records = parse_evidence(run)
    except Exception as exc:
        raise CompletionError(
            "COMPLETION_EVIDENCE_INDEX_INVALID", exc.__class__.__name__) from exc
    for record in records:
        manifests = record.get("artifact_manifests") \
            if isinstance(record, dict) else []
        for item in manifests if isinstance(manifests, list) else []:
            relative = str(item.get("path") or "") if isinstance(item, dict) else ""
            if relative:
                _contained_path(run, relative, must_exist=False)
                paths.add(relative)

    try:
        for candidate in run.glob("**/coverage.json"):
            relative = candidate.relative_to(run).as_posix()
            _contained_path(run, relative, must_exist=False)
            paths.add(relative)
    except OSError as exc:
        raise CompletionError("COMPLETION_COVERAGE_ENUMERATION_FAILED") from exc

    transaction_path = run / "state/work_plan_transaction.json"
    if transaction_path.exists():
        transaction = _strict_json(
            _stable_bytes(run, "state/work_plan_transaction.json"),
            "state/work_plan_transaction.json",
        )
        digest = str(transaction.get("receipt_hash") or "")
        if HEX64.fullmatch(digest):
            paths.add(f"state/work_plan_transactions/{digest}.json")
    return sorted(paths)


def _snapshot_manifest(
    run: Path,
    receipt_hashes: Iterable[str] = (),
    *,
    include_runtime: bool,
) -> list[dict]:
    required = set(CANONICAL_PATHS) - {"chains.md", "hints.md"}
    required.update(FROZEN_STATE_PATHS)
    paths = _closure_paths(
        run, receipt_hashes, include_runtime=include_runtime)
    return [
        _manifest_entry(run, item, required=item in required)
        for item in paths
    ]


def _stable_manifest(
    run: Path,
    receipt_hashes: Iterable[str] = (),
    *,
    include_runtime: bool,
) -> list[dict]:
    frozen_hashes = tuple(sorted(set(str(item) for item in receipt_hashes)))
    first = _snapshot_manifest(
        run, frozen_hashes, include_runtime=include_runtime)
    second = _snapshot_manifest(
        run, frozen_hashes, include_runtime=include_runtime)
    if first != second:
        raise CompletionError("COMPLETION_INPUT_CHANGED_DURING_SNAPSHOT")
    return second


def _manifest(run: Path, receipt_hashes: Iterable[str]) -> list[dict]:
    return _stable_manifest(
        run, receipt_hashes, include_runtime=True)


def closure_input_digest(run_dir: str | Path) -> str:
    """Hash the stable canonical/frozen closure inputs used by check_run."""
    run = _resolve_run(run_dir)
    rows = _stable_manifest(run, include_runtime=False)
    return _json_hash({
        "schema": "xunji.closure-input.v1",
        "run_name": run.name,
        "evidence_index_hash": current_evidence_index_hash(run),
        "rows": rows,
    })


def warning_code(message: str) -> str:
    digest = hashlib.sha256(str(message).encode("utf-8", "replace")).hexdigest()
    return "CHECK_WARNING_" + digest[:20].upper()


def build_check_run_token(
    run_dir: str | Path, warning_messages: Iterable[str],
) -> tuple[str, list[str]]:
    run = _resolve_run(run_dir)
    messages = [str(item) for item in warning_messages]
    codes = sorted({warning_code(item) for item in messages})
    payload = {
        "schema": CHECK_TOKEN_SCHEMA,
        "run_name": run.name,
        "closure_input_sha256": closure_input_digest(run),
        "warning_codes": codes,
        "warning_codes_sha256": _json_hash(codes),
    }
    encoded = base64.urlsafe_b64encode(_json_bytes(payload)).decode("ascii").rstrip("=")
    token_hash = _json_hash(payload)
    return f"{CHECK_TOKEN_PREFIX}{encoded}.{token_hash}", codes


def _parse_check_run_token(token: str) -> dict:
    if not token.startswith(CHECK_TOKEN_PREFIX):
        raise CompletionError("COMPLETION_CHECK_TOKEN_MISSING")
    body = token[len(CHECK_TOKEN_PREFIX):].splitlines()[0].strip()
    encoded, separator, claimed = body.rpartition(".")
    if not separator or not HEX64.fullmatch(claimed):
        raise CompletionError("COMPLETION_CHECK_TOKEN_INVALID")
    try:
        padding = "=" * (-len(encoded) % 4)
        payload = json.loads(base64.urlsafe_b64decode(
            (encoded + padding).encode("ascii")).decode("utf-8", "strict"))
    except Exception as exc:
        raise CompletionError("COMPLETION_CHECK_TOKEN_INVALID") from exc
    if not isinstance(payload, dict) or payload.get("schema") != CHECK_TOKEN_SCHEMA \
            or _json_hash(payload) != claimed:
        raise CompletionError("COMPLETION_CHECK_TOKEN_INVALID")
    codes = payload.get("warning_codes")
    if not isinstance(codes, list) or codes != sorted(set(codes)) \
            or any(not re.fullmatch(r"CHECK_WARNING_[0-9A-F]{20}", str(item))
                   for item in codes) \
            or payload.get("warning_codes_sha256") != _json_hash(codes) \
            or not HEX64.fullmatch(str(payload.get("closure_input_sha256") or "")):
        raise CompletionError("COMPLETION_CHECK_TOKEN_INVALID")
    return payload


def _response_stdout(response_excerpt: str) -> str:
    """Extract Bash stdout while requiring the token to be its first bytes."""
    value = str(response_excerpt or "")
    if value.startswith(CHECK_TOKEN_PREFIX):
        return value
    try:
        decoded = json.loads(value)
    except Exception:
        return ""
    if isinstance(decoded, dict) and isinstance(decoded.get("stdout"), str):
        return str(decoded["stdout"])
    return ""


def _manifest_map(receipt: dict) -> dict[str, dict]:
    return {str(row["path"]): row for row in receipt["manifest"]}


def _read_current(run: Path) -> dict | None:
    path = run / CURRENT_REL
    if not path.exists():
        return None
    return _validate_receipt_for_run(
        run,
        validate_receipt(_strict_json(
            _stable_bytes(run, CURRENT_REL), str(CURRENT_REL))),
    )


def _receipt_hash(receipt: dict) -> str:
    body = dict(receipt)
    body["receipt_sha256"] = ""
    return _json_hash(body)


def _binding_core(receipt: dict) -> dict:
    return {
        "schema": "xunji.completion-binding.v1",
        "run_name": receipt["run_name"],
        "mode": receipt["mode"],
        "marker": receipt["marker"],
        "manifest_sha256": receipt["manifest_sha256"],
        "basis": receipt["basis"],
        "review_policy_sha256": receipt["review_policy_sha256"],
        "review_bindings": receipt["review_bindings"],
        "report_before_sha256": receipt["report_transition"]["before_sha256"],
        "report_after_sha256": receipt["report_transition"]["after_sha256"],
        "decisions_before_sha256": receipt["decisions_transition"]["before_sha256"],
        "legacy_unbound": receipt["legacy_unbound"],
    }


def _seal(receipt: dict) -> dict:
    value = dict(receipt)
    value["completion_binding_sha256"] = _json_hash(_binding_core(value))
    value["receipt_sha256"] = ""
    value["receipt_sha256"] = _receipt_hash(value)
    return value


def _empty_basis() -> dict:
    return {
        "work_plan_digest": "",
        "work_plan_inputs_digest": "",
        "reason_receipt_sha256": "",
        "completion_review_receipt_sha256": "",
        "cycle_end_receipt_sha256": "",
        "closure_check_receipt_sha256": "",
        "closure_check_token_sha256": "",
        "closure_input_sha256": "",
        "warning_codes": [],
        "cron_disposition": "legacy_unbound",
        "cron_receipt_sha256": "",
        "warning_dispositions": [],
        "turn_contract_sha256": "",
        "runtime_tail_seq": 0,
        "runtime_tail_receipt_sha256": "",
    }


def validate_policy(value: object) -> dict:
    if not isinstance(value, dict) or value.get("schema") != POLICY_SCHEMA:
        raise CompletionError("COMPLETION_REVIEW_POLICY_INVALID")
    if contract_schema.named_schema_errors(value, POLICY_SCHEMA_FILE):
        raise CompletionError("COMPLETION_REVIEW_POLICY_INVALID")
    slots = value.get("slots")
    assert isinstance(slots, list)
    ids = [str(row.get("slot_id") or "") for row in slots if isinstance(row, dict)]
    if len(ids) != len(slots) or len(ids) != len(set(ids)):
        raise CompletionError("COMPLETION_REVIEW_POLICY_SLOT_DUPLICATE")
    mandatory = [
        row for row in slots
        if isinstance(row, dict) and row.get("requirement") == "mandatory"
    ]
    independent = [
        row for row in slots
        if isinstance(row, dict) and row.get("role") == "independent-reviewer"
    ]
    external = [
        row for row in slots
        if isinstance(row, dict) and row.get("role") == "external-assistance"
    ]
    if len(mandatory) != 1 or len(independent) != 1 \
            or mandatory[0] is not independent[0]:
        raise CompletionError("COMPLETION_REVIEW_POLICY_MANDATORY_INVALID")
    if len(external) > 1 or any(
            row.get("requirement") != "optional" for row in external):
        raise CompletionError("COMPLETION_REVIEW_POLICY_EXTERNAL_INVALID")
    return value


def validate_receipt(value: object) -> dict:
    if not isinstance(value, dict) or value.get("schema") != SCHEMA:
        raise CompletionError("COMPLETION_RECEIPT_INVALID")
    if contract_schema.named_schema_errors(value, SCHEMA_FILE):
        raise CompletionError("COMPLETION_RECEIPT_INVALID")
    receipt = dict(value)
    manifest = receipt["manifest"]
    paths = [str(row["path"]) for row in manifest]
    if paths != sorted(paths) or len(paths) != len(set(paths)):
        raise CompletionError("COMPLETION_MANIFEST_INVALID")
    if any(
        (row.get("present") is True and (
            not HEX64.fullmatch(str(row.get("sha256") or ""))
            or int(row.get("size") or 0) < 0
        ))
        or (row.get("present") is False and (
            row.get("sha256") != "" or row.get("size") != 0
        ))
        for row in manifest
    ):
        raise CompletionError("COMPLETION_MANIFEST_INVALID")
    if receipt["manifest_sha256"] != _json_hash(manifest):
        raise CompletionError("COMPLETION_MANIFEST_DIGEST_INVALID")
    if receipt["marker"] != (
            "GHOST_COMPLETE" if receipt["mode"] == "ghost" else "NORMAL_COMPLETE"):
        raise CompletionError("COMPLETION_MARKER_MODE_INVALID")
    if receipt["report_transition"]["path"] != "report.md" \
            or receipt["decisions_transition"]["path"] != "decisions.md":
        raise CompletionError("COMPLETION_TRANSITION_PATH_INVALID")
    if receipt["completion_binding_sha256"] != _json_hash(_binding_core(receipt)):
        raise CompletionError("COMPLETION_BINDING_INVALID")
    if receipt["receipt_sha256"] != _receipt_hash(receipt):
        raise CompletionError("COMPLETION_RECEIPT_DIGEST_INVALID")
    legacy = bool(receipt["legacy_unbound"])
    if legacy:
        if receipt["status"] not in {"prepared", "reopened"} \
                or receipt["review_policy"] != {} \
                or receipt["review_policy_sha256"] \
                or receipt["review_bindings"] \
                or receipt["basis"] != _empty_basis():
            raise CompletionError("COMPLETION_LEGACY_RECEIPT_INVALID")
    else:
        policy = validate_policy(receipt["review_policy"])
        if receipt["review_policy_sha256"] != _json_hash(policy):
            raise CompletionError("COMPLETION_REVIEW_POLICY_DIGEST_INVALID")
        for key in (
            "work_plan_digest", "work_plan_inputs_digest",
            "reason_receipt_sha256", "completion_review_receipt_sha256",
            "cycle_end_receipt_sha256", "closure_check_receipt_sha256",
            "closure_check_token_sha256", "closure_input_sha256",
            "turn_contract_sha256", "runtime_tail_receipt_sha256",
        ):
            if not HEX64.fullmatch(str(receipt["basis"].get(key) or "")):
                raise CompletionError("COMPLETION_BASIS_INVALID", key)
        warning_codes = receipt["basis"].get("warning_codes")
        if not isinstance(warning_codes, list) \
                or warning_codes != sorted(set(warning_codes)) \
                or any(not re.fullmatch(r"CHECK_WARNING_[0-9A-F]{20}", str(item))
                       for item in warning_codes) \
                or [row["code"] for row in receipt["basis"]["warning_dispositions"]] \
                != warning_codes:
            raise CompletionError("COMPLETION_WARNING_DISPOSITION_MISMATCH")
        if isinstance(receipt["basis"].get("runtime_tail_seq"), bool) \
                or int(receipt["basis"].get("runtime_tail_seq") or 0) < 1:
            raise CompletionError("COMPLETION_RUNTIME_TAIL_INVALID")
        slots = policy["slots"]
        bindings = receipt["review_bindings"]
        if len(slots) != len(bindings):
            raise CompletionError("COMPLETION_REVIEW_BINDINGS_INVALID")
        for slot, binding in zip(slots, bindings):
            expected = {
                "slot_id": slot["slot_id"],
                "role": slot["role"],
                "requirement": slot["requirement"],
                "provider": str(slot.get("provider") or ""),
                "backend": str(slot.get("backend") or ""),
            }
            if any(binding[key] != expected[key] for key in expected):
                raise CompletionError("COMPLETION_REVIEW_BINDINGS_INVALID")
            digest = str(binding["receipt_sha256"] or "")
            limitation = str(binding["limitation"] or "")
            if slot["requirement"] == "mandatory" and (
                    not HEX64.fullmatch(digest) or limitation):
                raise CompletionError("COMPLETION_MANDATORY_REVIEW_MISSING")
            if slot["requirement"] == "optional" \
                    and not ((HEX64.fullmatch(digest) and not limitation)
                             or (not digest and bool(limitation.strip()))):
                raise CompletionError("COMPLETION_OPTIONAL_REVIEW_UNRESOLVED")
    if receipt["status"] == "prepared" and (
            receipt["terminal_at"] != 0 or receipt["reopen_reason"]):
        raise CompletionError("COMPLETION_PREPARED_STATE_INVALID")
    if receipt["status"] == "committed" and (
            receipt["terminal_at"] <= 0 or receipt["reopen_reason"] or legacy):
        raise CompletionError("COMPLETION_COMMITTED_STATE_INVALID")
    if receipt["status"] == "reopened" and (
            receipt["terminal_at"] <= 0 or not receipt["reopen_reason"].strip()):
        raise CompletionError("COMPLETION_REOPENED_STATE_INVALID")
    return receipt


def _validate_receipt_for_run(run: Path, receipt: dict) -> dict:
    """Reject a self-consistent receipt that is incomplete for this run.

    Hashes are crash-integrity mechanisms, not identities.  The read path must
    still bind the receipt to the directory name, the complete dynamically
    derived closure manifest, the protected policy, and the exact review
    receipts that policy names.
    """
    if receipt.get("run_name") != run.name:
        raise CompletionError("COMPLETION_RUN_BINDING_INVALID")
    if receipt.get("legacy_unbound") is True:
        return receipt

    bindings = receipt.get("review_bindings") or []
    receipt_hashes = sorted({
        str(item.get("receipt_sha256") or "")
        for item in bindings if isinstance(item, dict)
        and HEX64.fullmatch(str(item.get("receipt_sha256") or ""))
    })
    expected_paths = _closure_paths(
        run, receipt_hashes, include_runtime=True)
    actual_paths = [str(item.get("path") or "") for item in receipt["manifest"]]
    if actual_paths != expected_paths:
        raise CompletionError("COMPLETION_MANIFEST_PATH_SET_INVALID")

    policy = validate_policy(_strict_json(
        _stable_bytes(run, POLICY_REL), str(POLICY_REL)))
    if policy != receipt["review_policy"] \
            or _json_hash(policy) != receipt["review_policy_sha256"]:
        raise CompletionError("COMPLETION_REVIEW_POLICY_DIVERGED")
    for slot, binding in zip(policy["slots"], bindings):
        digest = str(binding.get("receipt_sha256") or "")
        if not digest:
            continue
        relative = f"review/receipts/{digest}.json"
        value = _strict_json(_stable_bytes(run, relative), relative)
        payload = dict(value)
        claimed = str(payload.pop("receipt_id", ""))
        if claimed != digest or _json_hash(payload) != digest:
            raise CompletionError(
                "COMPLETION_REVIEW_RECEIPT_INVALID", str(slot["slot_id"]))
        _validate_review_receipt(run, value, slot)

    previous = str(receipt.get("previous_receipt_sha256") or "")
    if previous:
        previous_rel = TRANSACTIONS_REL / "receipts" / f"{previous}.json"
        previous_receipt = validate_receipt(_strict_json(
            _stable_bytes(run, previous_rel), previous_rel.as_posix()))
        if previous_receipt.get("receipt_sha256") != previous \
                or previous_receipt.get("run_name") != run.name:
            raise CompletionError("COMPLETION_PREVIOUS_RECEIPT_INVALID")

    status_value = str(receipt.get("status") or "")
    transaction_dir = TRANSACTIONS_REL / str(receipt["transaction_id"])
    if status_value == "prepared":
        prepared_rel = transaction_dir / "prepared.json"
        prepared = validate_receipt(_strict_json(
            _stable_bytes(run, prepared_rel), prepared_rel.as_posix()))
        if prepared != receipt:
            raise CompletionError("COMPLETION_PREPARED_RECEIPT_DIVERGED")
    elif status_value == "reopened":
        archive_rel = (
            TRANSACTIONS_REL / "receipts" / f"{receipt['receipt_sha256']}.json")
        reopened_rel = transaction_dir / "reopen_intent.json"
        archived = validate_receipt(_strict_json(
            _stable_bytes(run, archive_rel), archive_rel.as_posix()))
        reopened = validate_receipt(_strict_json(
            _stable_bytes(run, reopened_rel), reopened_rel.as_posix()))
        if archived != receipt or reopened != receipt:
            raise CompletionError("COMPLETION_REOPEN_RECEIPT_DIVERGED")
    return receipt


def _parse_status(report: bytes) -> tuple[str, re.Match[str]]:
    text = _strict_text(report, "report.md")
    matches = list(STATUS_RE.finditer(text))
    if len(matches) != 1:
        raise CompletionError("COMPLETION_REPORT_STATUS_AMBIGUOUS")
    return matches[0].group(2).strip().upper(), matches[0]


def _set_report_status(report: bytes, expected: set[str], target: str) -> bytes:
    text = _strict_text(report, "report.md")
    matches = list(STATUS_RE.finditer(text))
    if len(matches) != 1:
        raise CompletionError("COMPLETION_REPORT_STATUS_AMBIGUOUS")
    match = matches[0]
    if match.group(2).strip().upper() not in expected:
        raise CompletionError(
            "COMPLETION_REPORT_STATUS_INVALID", match.group(2).strip())
    replacement = match.group(1) + target + match.group(3)
    return (text[:match.start()] + replacement + text[match.end():]).encode("utf-8")


def _append_marker(decisions: bytes, marker: str, binding: str) -> bytes:
    text = _strict_text(decisions, "decisions.md")
    if MARKER_RE.search(text):
        raise CompletionError("COMPLETION_MARKER_ALREADY_PRESENT")
    newline = b"\r\n" if b"\r\n" in decisions and b"\n" not in decisions.replace(b"\r\n", b"") else b"\n"
    prefix = decisions if decisions.endswith((b"\n", b"\r")) else decisions + newline
    return prefix + f"{marker} receipt={binding}".encode("ascii") + newline


def _strip_markers(decisions: bytes) -> tuple[bytes, list[tuple[str, str]]]:
    text = _strict_text(decisions, "decisions.md")
    matches = [(item.group(1), item.group(2) or "") for item in MARKER_RE.finditer(text)]
    if not matches:
        raise CompletionError("COMPLETION_MARKER_NOT_FOUND")
    cleaned = MARKER_RE.sub("", text)
    return cleaned.encode("utf-8"), matches


def _parse_mapping(items: Iterable[str], *, label: str) -> dict[str, str]:
    result: dict[str, str] = {}
    for item in items:
        key, separator, value = str(item).partition("=")
        if not separator or not key or not value or key in result:
            raise CompletionError(f"COMPLETION_{label}_INVALID", str(item))
        result[key] = value
    return result


def _parse_warning_dispositions(items: Iterable[str]) -> list[dict]:
    rows: list[dict] = []
    seen: set[str] = set()
    for raw in items:
        code, first, tail = str(raw).partition(":")
        disposition, second, reason = tail.partition(":")
        if not first or not second or not re.fullmatch(
                r"[A-Za-z0-9][A-Za-z0-9._-]*", code) \
                or disposition not in {"accepted", "dismissed", "deferred", "fixed"} \
                or not reason.strip() or code in seen:
            raise CompletionError("COMPLETION_WARNING_DISPOSITION_INVALID", str(raw))
        seen.add(code)
        rows.append({
            "code": code, "disposition": disposition, "reason": reason.strip(),
        })
    return sorted(rows, key=lambda row: row["code"])


def _load_policy_and_bindings(
    run: Path,
    receipt_items: Iterable[str],
    limitation_items: Iterable[str],
) -> tuple[dict, list[dict], list[str]]:
    policy = validate_policy(_strict_json(
        _stable_bytes(run, POLICY_REL), str(POLICY_REL)))
    receipts = _parse_mapping(receipt_items, label="REVIEW_RECEIPT")
    limitations = _parse_mapping(limitation_items, label="REVIEW_LIMITATION")
    slots = policy["slots"]
    slot_ids = {str(slot["slot_id"]) for slot in slots}
    if (set(receipts) | set(limitations)) - slot_ids:
        raise CompletionError("COMPLETION_REVIEW_SLOT_UNKNOWN")
    review_text = _strict_text(_stable_bytes(run, "review.md"), "review.md")
    recorded = set(REVIEW_RECEIPT_RE.findall(review_text))
    bindings: list[dict] = []
    bound_hashes: list[str] = []
    for slot in slots:
        slot_id = str(slot["slot_id"])
        digest = str(receipts.get(slot_id) or "")
        limitation = str(limitations.get(slot_id) or "").strip()
        if digest:
            if not HEX64.fullmatch(digest) or digest not in recorded or limitation:
                raise CompletionError("COMPLETION_REVIEW_RECEIPT_INVALID", slot_id)
            receipt_path = f"review/receipts/{digest}.json"
            receipt = _strict_json(_stable_bytes(run, receipt_path), receipt_path)
            payload = dict(receipt)
            claimed = str(payload.pop("receipt_id", ""))
            if claimed != digest or _json_hash(payload) != digest:
                raise CompletionError("COMPLETION_REVIEW_RECEIPT_INVALID", slot_id)
            _validate_review_receipt(run, receipt, slot)
            bound_hashes.append(digest)
        if slot["requirement"] == "mandatory" and not digest:
            raise CompletionError("COMPLETION_MANDATORY_REVIEW_MISSING", slot_id)
        if slot["requirement"] == "optional" and not digest and not limitation:
            raise CompletionError("COMPLETION_OPTIONAL_REVIEW_UNRESOLVED", slot_id)
        bindings.append({
            "slot_id": slot_id,
            "role": str(slot["role"]),
            "requirement": str(slot["requirement"]),
            "provider": str(slot.get("provider") or ""),
            "backend": str(slot.get("backend") or ""),
            "receipt_sha256": digest,
            "limitation": limitation,
        })
    # One heterogeneous panel receipt may prove both the mandatory independent
    # review and the optional external-assistance slot.  Deduplicate only the
    # frozen file path; each role still has its own validated binding row.
    return policy, bindings, sorted(set(bound_hashes))


def _review_bundle_hash(run: Path) -> str:
    relative = "review/review_bundle.json"
    bundle = _strict_json(_stable_bytes(run, relative), relative)
    claimed = str(bundle.pop("sha1", ""))
    actual = hashlib.sha1(json.dumps(
        bundle, ensure_ascii=False, sort_keys=True,
    ).encode("utf-8")).hexdigest()
    if not re.fullmatch(r"[0-9a-f]{40}", claimed) or claimed != actual:
        raise CompletionError("COMPLETION_REVIEW_BUNDLE_INVALID")
    return claimed


def _validate_review_receipt(run: Path, receipt: dict, slot: dict) -> None:
    """Recompute review content, evidence, bundle, invocation, and role."""
    if receipt.get("schema") != "xunji.peer_review_receipt.v1":
        raise CompletionError(
            "COMPLETION_REVIEW_RECEIPT_SCHEMA_INVALID", str(slot["slot_id"]))
    result = receipt.get("result")
    if not isinstance(result, dict) \
            or result.get("schema") != "xunji.peer_review_result.v1" \
            or not str(result.get("backend_used") or "").strip() \
            or not str(result.get("driver") or "").strip() \
            or result.get("verdict") not in {"PASS", "WARN", "BLOCKER"}:
        raise CompletionError(
            "COMPLETION_REVIEW_RECEIPT_RESULT_INVALID", str(slot["slot_id"]))
    evidence_hash = current_evidence_index_hash(run)
    if str(result.get("evidence_index_hash") or "") != evidence_hash:
        raise CompletionError(
            "COMPLETION_REVIEW_EVIDENCE_STALE", str(slot["slot_id"]))
    bundle_hash = _review_bundle_hash(run)
    if str(result.get("bundle_hash") or "") != bundle_hash:
        raise CompletionError(
            "COMPLETION_REVIEW_BUNDLE_MISMATCH", str(slot["slot_id"]))
    receipt_id = str(receipt.get("receipt_id") or "")
    if not runtime_receipts.review_invocation_valid(
            run, str(receipt.get("generated_at") or ""),
            receipt_id=receipt_id, bundle_hash=bundle_hash):
        raise CompletionError(
            "COMPLETION_REVIEW_INVOCATION_INVALID", str(slot["slot_id"]))
    role = str(slot.get("role") or "")
    if role == "external-assistance":
        backend_used = str(result.get("backend_used") or "")
        providers = backend_used.partition(":")[2].split("+")
        # Current peer_review names the heterogeneous panel as
        # panel:<primary>+<external>.  A primary-only panel is not evidence that
        # external assistance succeeded and must be recorded as a limitation.
        if not backend_used.startswith("panel:") or len(providers) < 2:
            raise CompletionError(
                "COMPLETION_EXTERNAL_ASSISTANCE_NOT_PROVEN", str(slot["slot_id"]))
        expected = str(slot.get("provider") or slot.get("backend") or "")
        if expected and expected not in providers:
            raise CompletionError(
                "COMPLETION_EXTERNAL_ASSISTANCE_PROVIDER_MISMATCH",
                str(slot["slot_id"]),
            )


def _latest_basis(
    run: Path,
    *,
    cron_disposition: str,
    warning_dispositions: list[dict],
) -> dict:
    try:
        plan = work_plan.transaction_bound_plan(run)
    except Exception as exc:
        raise CompletionError(
            "COMPLETION_WORK_PLAN_TRANSACTION_INVALID", str(exc)) from exc
    if plan.get("macro_stage") != "S3" \
            or plan.get("execution_mode") != "COMPLETION_REVIEW" \
            or plan.get("lanes") != []:
        raise CompletionError("COMPLETION_S3_PLAN_INVALID")
    plan_digest = str(plan.get("plan_digest") or "")
    inputs_digest = str(plan.get("inputs_digest") or "")
    if not HEX64.fullmatch(plan_digest) or not HEX64.fullmatch(inputs_digest):
        raise CompletionError("COMPLETION_S3_PLAN_DIGEST_INVALID")

    reasons, reason_errors = anti_drift.load_reason_pass_receipts(run)
    freshness = anti_drift.semantic_freshness(run)
    if reason_errors or not reasons or freshness.get("status") != "fresh" \
            or freshness.get("latest_receipt_hash") \
            != reasons[-1].get("receipt_hash"):
        raise CompletionError(
            "COMPLETION_REASON_RECEIPT_INVALID",
            "; ".join(reason_errors[:2]) or str(freshness.get("status") or "missing"),
        )
    reason_hash = str(reasons[-1]["receipt_hash"])

    try:
        journal = loop_journal.load_events(run)
        journal_state = loop_journal.validate_cycle_events(journal)
    except Exception as exc:
        raise CompletionError("COMPLETION_LOOP_JOURNAL_INVALID", str(exc)) from exc
    ends = [
        row for row in journal
        if row.get("schema") == loop_journal.SCHEMA
        and row.get("event") == "cycle_end"
        and row.get("cycle") == plan.get("cycle_id")
        and isinstance(row.get("data"), dict)
        and row["data"].get("plan_digest") == plan_digest
        and row["data"].get("execution_mode") == "COMPLETION_REVIEW"
    ]
    if len(ends) != 1 or plan_digest not in journal_state.get(
            "ended_plan_digests", []):
        raise CompletionError("COMPLETION_CYCLE_END_RECEIPT_INVALID")
    cycle_hash = str(ends[0].get("event_hash") or "")
    if not HEX64.fullmatch(cycle_hash):
        raise CompletionError("COMPLETION_CYCLE_END_RECEIPT_INVALID")

    contract = turn_contract.load_contract(run)
    if not contract:
        raise CompletionError("COMPLETION_TURN_CONTRACT_INVALID")
    session_id = str(contract.get("session_id") or "")
    contract_hash = _bytes_hash(_stable_bytes(run, "state/turn_contract.json"))

    runtime, runtime_errors = runtime_receipts.validate_chain(run)
    if runtime_errors or not runtime:
        raise CompletionError(
            "COMPLETION_RUNTIME_CHAIN_INVALID",
            "; ".join(runtime_errors[:2]) or "empty",
        )
    evidence_hash = current_evidence_index_hash(run)
    if not runtime_receipts.completion_review_valid(run, evidence_hash):
        raise CompletionError("COMPLETION_REVIEW_CHALLENGE_INVALID")
    valid_agents = runtime_receipts.valid_tool_events(run, "Agent")
    completion_rows = [
        row for row in valid_agents
        if row.get("completion_review") is True
        and row.get("completion_plan_digest") == plan_digest
        and str(row.get("session_id") or "") == session_id
    ]
    if not completion_rows:
        raise CompletionError("COMPLETION_REVIEW_RECEIPT_RUNTIME_INVALID")
    completion_row = max(
        completion_rows, key=lambda row: int(row.get("seq") or 0))
    completion_seq = int(completion_row.get("seq") or 0)
    completion_hash = str(completion_row.get("receipt_hash") or "")
    if not HEX64.fullmatch(completion_hash):
        raise CompletionError("COMPLETION_REVIEW_RECEIPT_RUNTIME_INVALID")

    valid_bash = runtime_receipts.valid_tool_events(run, "Bash")
    checks = [
        row for row in valid_bash
        if row.get("capability_id") == "verify.check-run"
        and str(row.get("session_id") or "") == session_id
        and int(row.get("seq") or 0) > completion_seq
    ]
    if not checks:
        raise CompletionError("COMPLETION_CLOSURE_CHECK_RECEIPT_INVALID")
    check_row = max(checks, key=lambda row: int(row.get("seq") or 0))
    check_seq = int(check_row.get("seq") or 0)
    check_hash = str(check_row.get("receipt_hash") or "")
    if not HEX64.fullmatch(check_hash):
        raise CompletionError("COMPLETION_CLOSURE_CHECK_RECEIPT_INVALID")
    stdout = _response_stdout(str(check_row.get("response_excerpt") or ""))
    if not stdout.startswith(CHECK_TOKEN_PREFIX):
        raise CompletionError("COMPLETION_CHECK_TOKEN_NOT_AT_STDOUT_START")
    check_token = stdout.splitlines()[0]
    token_payload = _parse_check_run_token(check_token)
    closure_digest = closure_input_digest(run)
    if token_payload.get("run_name") != run.name \
            or token_payload.get("closure_input_sha256") != closure_digest:
        raise CompletionError("COMPLETION_CHECK_TOKEN_STALE")
    warning_codes = list(token_payload["warning_codes"])
    disposition_codes = [row["code"] for row in warning_dispositions]
    if disposition_codes != warning_codes:
        raise CompletionError("COMPLETION_WARNING_DISPOSITION_MISMATCH")

    loop_requested = contract.get("loop_requested") is True
    if loop_requested and cron_disposition != "quiescent":
        raise CompletionError("COMPLETION_CRON_DISPOSITION_REQUIRED")
    if not loop_requested and cron_disposition != "not_requested":
        raise CompletionError("COMPLETION_CRON_DISPOSITION_UNREQUESTED")
    cron_hash = ""
    if cron_disposition == "quiescent":
        controls = [
            row for row in runtime_receipts.valid_control_events(
                run, session_id=session_id,
                since=max(
                    float(contract.get("updated_at") or 0.0),
                    float(completion_row.get("ts") or 0.0),
                ),
            )
            if completion_seq < int(row.get("seq") or 0) < check_seq
            and str(row.get("tool_name") or "").startswith("Cron")
        ]
        cron_lists = [row for row in controls if row.get("tool_name") == "CronList"]
        if not cron_lists:
            raise CompletionError("COMPLETION_CRON_NOT_QUIESCENT")
        last_list = max(cron_lists, key=lambda row: int(row.get("seq") or 0))
        last_mutation = max(
            (int(row.get("seq") or 0) for row in controls
             if row.get("tool_name") in {"CronCreate", "CronDelete"}),
            default=0,
        )
        response = str(last_list.get("response_excerpt") or "").lower()
        if int(last_list.get("seq") or 0) <= last_mutation \
                or list(last_list.get("listed_run_job_ids") or []) \
                or run.name.lower() in response \
                or float(check_row.get("ts") or 0.0) \
                - float(last_list.get("ts") or 0.0) > 300:
            raise CompletionError("COMPLETION_CRON_NOT_QUIESCENT")
        cron_hash = str(last_list.get("receipt_hash") or "")
        if not HEX64.fullmatch(cron_hash):
            raise CompletionError("COMPLETION_CRON_RECEIPT_INVALID")

    tail = runtime[-1]
    tail_seq = int(tail.get("seq") or 0)
    tail_hash = str(tail.get("receipt_hash") or "")
    if tail_seq < check_seq or not HEX64.fullmatch(tail_hash):
        raise CompletionError("COMPLETION_RUNTIME_TAIL_INVALID")
    return {
        "work_plan_digest": plan_digest,
        "work_plan_inputs_digest": inputs_digest,
        "reason_receipt_sha256": reason_hash,
        "completion_review_receipt_sha256": completion_hash,
        "cycle_end_receipt_sha256": cycle_hash,
        "closure_check_receipt_sha256": check_hash,
        "closure_check_token_sha256": _json_hash(token_payload),
        "closure_input_sha256": closure_digest,
        "warning_codes": warning_codes,
        "cron_disposition": cron_disposition,
        "cron_receipt_sha256": cron_hash,
        "warning_dispositions": warning_dispositions,
        "turn_contract_sha256": contract_hash,
        "runtime_tail_seq": tail_seq,
        "runtime_tail_receipt_sha256": tail_hash,
    }


def _stage_path(run: Path, transaction_id: str) -> Path:
    return run / TRANSACTIONS_REL / transaction_id


def _write_stage(
    run: Path, receipt: dict, *,
    report_before: bytes, report_after: bytes,
    decisions_before: bytes, decisions_after: bytes,
) -> None:
    directory = _stage_path(run, receipt["transaction_id"])
    entries = {
        "report.before.md": report_before,
        "report.after.md": report_after,
        "decisions.before.md": decisions_before,
        "decisions.after.md": decisions_after,
    }
    for name, value in entries.items():
        _atomic_bytes(run, directory / name, value)
    _atomic_json(run, directory / "prepared.json", receipt)


def _load_stage_file(run: Path, receipt: dict, name: str, digest: str) -> bytes:
    relative = TRANSACTIONS_REL / receipt["transaction_id"] / name
    value = _stable_bytes(run, relative)
    if _bytes_hash(value) != digest:
        raise CompletionError("COMPLETION_STAGE_DIVERGED", name)
    return value


def _archive_receipt(run: Path, receipt: dict) -> None:
    archive = run / TRANSACTIONS_REL / "receipts" / f"{receipt['receipt_sha256']}.json"
    if archive.exists():
        existing = validate_receipt(_strict_json(
            _stable_bytes(run, archive.relative_to(run)), str(archive.relative_to(run))))
        if existing != receipt:
            raise CompletionError("COMPLETION_ARCHIVE_COLLISION")
        return
    _atomic_json(run, archive, receipt)


def _write_current(run: Path, receipt: dict) -> None:
    _atomic_json(run, run / CURRENT_REL, receipt)


def _terminal_intent(run: Path, prepared: dict, *, status: str, reason: str) -> dict:
    name = "commit_intent.json" if status == "committed" else "reopen_intent.json"
    relative = TRANSACTIONS_REL / prepared["transaction_id"] / name
    path = run / relative
    if path.exists():
        value = validate_receipt(_strict_json(_stable_bytes(run, relative), str(relative)))
        if value["transaction_id"] != prepared["transaction_id"] \
                or value["completion_binding_sha256"] != prepared["completion_binding_sha256"] \
                or value["status"] != status \
                or (status == "reopened" and value["reopen_reason"] != reason):
            raise CompletionError("COMPLETION_TERMINAL_INTENT_MISMATCH")
        return value
    value = dict(prepared)
    value["status"] = status
    value["terminal_at"] = max(time.time(), float(prepared["prepared_at"]))
    value["reopen_reason"] = reason if status == "reopened" else ""
    value = _seal(value)
    validate_receipt(value)
    _atomic_json(run, path, value)
    return value


def _manifest_cas(
    run: Path, receipt: dict, *, allow_targets: bool,
) -> tuple[str, str]:
    report_state = decisions_state = "before"
    for entry in receipt["manifest"]:
        relative = str(entry["path"])
        path = _contained_path(run, relative, must_exist=False)
        present = path.exists()
        if bool(entry.get("present")) != present:
            raise CompletionError("COMPLETION_MANIFEST_CAS_MISMATCH", relative)
        digest = _bytes_hash(_stable_bytes(run, relative)) if present else ""
        if allow_targets and relative == "report.md":
            before = receipt["report_transition"]["before_sha256"]
            after = receipt["report_transition"]["after_sha256"]
            if digest not in {before, after}:
                raise CompletionError("COMPLETION_MANIFEST_CAS_MISMATCH", relative)
            report_state = "after" if digest == after else "before"
        elif allow_targets and relative == "decisions.md":
            before = receipt["decisions_transition"]["before_sha256"]
            after = receipt["decisions_transition"]["after_sha256"]
            if digest not in {before, after}:
                raise CompletionError("COMPLETION_MANIFEST_CAS_MISMATCH", relative)
            decisions_state = "after" if digest == after else "before"
        elif relative == "state/runtime_events.jsonl" \
                and digest != entry["sha256"]:
            _runtime_tail_cas(run, receipt)
        elif digest != entry["sha256"]:
            raise CompletionError("COMPLETION_MANIFEST_CAS_MISMATCH", relative)
    return report_state, decisions_state


def _runtime_response_mentions_transaction(event: dict, transaction_id: str) -> bool:
    stdout = _response_stdout(str(event.get("response_excerpt") or ""))
    return transaction_id in stdout[:1024]


def _runtime_tail_cas(run: Path, receipt: dict) -> None:
    """Admit only semantically read-only or this transaction's owner receipts."""
    events, errors = runtime_receipts.validate_chain(run)
    if errors:
        raise CompletionError("COMPLETION_RUNTIME_CHAIN_INVALID", errors[0])
    basis = receipt["basis"]
    tail_seq = int(basis.get("runtime_tail_seq") or 0)
    tail_hash = str(basis.get("runtime_tail_receipt_sha256") or "")
    anchor = next(
        (row for row in events if int(row.get("seq") or 0) == tail_seq), None)
    if not anchor or str(anchor.get("receipt_hash") or "") != tail_hash:
        raise CompletionError("COMPLETION_RUNTIME_TAIL_DIVERGED")
    extras = [row for row in events if int(row.get("seq") or 0) > tail_seq]
    for row in extras:
        tool = str(row.get("tool_name") or "")
        capability = str(row.get("capability_id") or "")
        effect = str(row.get("capability_effect") or "")
        if row.get("target_action") is True or tool == "Agent" \
                or tool.startswith("Cron"):
            raise CompletionError("COMPLETION_RUNTIME_EFFECT_AFTER_PREPARE", tool)
        if effect in {"local_read", "local_verify"}:
            continue
        if capability in {
            "control.completion-transaction-prepare",
            "control.completion-transaction-commit",
        } and row.get("success") is True \
                and row.get("hook_event_name") == "PostToolUse" \
                and _runtime_response_mentions_transaction(
                    row, str(receipt["transaction_id"])):
            continue
        raise CompletionError(
            "COMPLETION_RUNTIME_EFFECT_AFTER_PREPARE",
            capability or tool or str(row.get("hook_event_name") or "unknown"),
        )


def _basis_semantics(value: dict) -> dict:
    result = dict(value)
    result.pop("runtime_tail_seq", None)
    result.pop("runtime_tail_receipt_sha256", None)
    return result


def _assert_committed_targets(run: Path, receipt: dict) -> None:
    report = _stable_bytes(run, "report.md")
    decisions = _stable_bytes(run, "decisions.md")
    if _bytes_hash(report) != receipt["report_transition"]["after_sha256"] \
            or _bytes_hash(decisions) != receipt["decisions_transition"]["after_sha256"]:
        raise CompletionError("COMPLETION_COMMITTED_TARGET_DIVERGED")
    marker = f"{receipt['marker']} receipt={receipt['completion_binding_sha256']}"
    lines = [line.strip() for line in _strict_text(decisions, "decisions.md").splitlines()
             if line.strip()]
    if not lines or lines[-1] != marker:
        raise CompletionError("COMPLETION_MARKER_NOT_TERMINAL")


def _assert_committed_manifest(run: Path, receipt: dict) -> None:
    report_state, decisions_state = _manifest_cas(
        run, receipt, allow_targets=True)
    if report_state != "after" or decisions_state != "after":
        raise CompletionError("COMPLETION_COMMITTED_TARGET_DIVERGED")
    _assert_committed_targets(run, receipt)


def _event_by_receipt_hash(
    events: Iterable[dict], digest: str, *, code: str,
) -> dict:
    matches = [
        row for row in events
        if str(row.get("receipt_hash") or "") == digest
    ]
    if len(matches) != 1:
        raise CompletionError(code)
    return matches[0]


def _receipt_closure_input_digest(run: Path, receipt: dict) -> str:
    rows = [
        dict(row) for row in receipt["manifest"]
        if str(row.get("path") or "") != "state/runtime_events.jsonl"
    ]
    return _json_hash({
        "schema": "xunji.closure-input.v1",
        "run_name": run.name,
        "evidence_index_hash": current_evidence_index_hash(run),
        "rows": rows,
    })


def _assert_committed_authority(run: Path, receipt: dict) -> None:
    """Revalidate every public owner basis used by a committed receipt.

    This makes the consumer predicate reject a merely self-hashed JSON object.
    It is still a trusted-workstation crash/corruption boundary, not a signing
    scheme or a second identity system.
    """
    basis = receipt["basis"]
    if _receipt_closure_input_digest(run, receipt) \
            != basis["closure_input_sha256"]:
        raise CompletionError("COMPLETION_CLOSURE_INPUT_RECEIPT_INVALID")

    try:
        plan = work_plan.transaction_bound_plan(run)
    except Exception as exc:
        raise CompletionError(
            "COMPLETION_WORK_PLAN_TRANSACTION_INVALID", str(exc)) from exc
    if str(plan.get("plan_digest") or "") != basis["work_plan_digest"] \
            or str(plan.get("inputs_digest") or "") \
            != basis["work_plan_inputs_digest"] \
            or plan.get("macro_stage") != "S3" \
            or plan.get("execution_mode") != "COMPLETION_REVIEW" \
            or plan.get("lanes") != []:
        raise CompletionError("COMPLETION_S3_PLAN_INVALID")

    reasons, reason_errors = anti_drift.load_reason_pass_receipts(run)
    if reason_errors or len([
        row for row in reasons
        if str(row.get("receipt_hash") or "")
        == basis["reason_receipt_sha256"]
    ]) != 1:
        raise CompletionError("COMPLETION_REASON_RECEIPT_INVALID")

    try:
        journal = loop_journal.load_events(run)
        journal_state = loop_journal.validate_cycle_events(journal)
    except Exception as exc:
        raise CompletionError("COMPLETION_LOOP_JOURNAL_INVALID", str(exc)) from exc
    cycle_matches = [
        row for row in journal
        if str(row.get("event_hash") or "")
        == basis["cycle_end_receipt_sha256"]
    ]
    if len(cycle_matches) != 1:
        raise CompletionError("COMPLETION_CYCLE_END_RECEIPT_INVALID")
    cycle = cycle_matches[0]
    cycle_data = cycle.get("data") if isinstance(cycle.get("data"), dict) else {}
    if cycle.get("event") != "cycle_end" \
            or cycle.get("cycle") != plan.get("cycle_id") \
            or cycle_data.get("plan_digest") != plan.get("plan_digest") \
            or cycle_data.get("execution_mode") != "COMPLETION_REVIEW" \
            or plan.get("plan_digest") not in journal_state.get(
                "ended_plan_digests", []):
        raise CompletionError("COMPLETION_CYCLE_END_RECEIPT_INVALID")

    contract = turn_contract.load_contract(run)
    if not contract or _bytes_hash(_stable_bytes(
            run, "state/turn_contract.json")) \
            != basis["turn_contract_sha256"]:
        raise CompletionError("COMPLETION_TURN_CONTRACT_INVALID")
    session_id = str(contract.get("session_id") or "")

    runtime, runtime_errors = runtime_receipts.validate_chain(run)
    if runtime_errors or not runtime:
        raise CompletionError(
            "COMPLETION_RUNTIME_CHAIN_INVALID",
            "; ".join(runtime_errors[:2]) or "empty",
        )
    tail = _event_by_receipt_hash(
        runtime, basis["runtime_tail_receipt_sha256"],
        code="COMPLETION_RUNTIME_TAIL_INVALID")
    if int(tail.get("seq") or 0) != int(basis["runtime_tail_seq"]):
        raise CompletionError("COMPLETION_RUNTIME_TAIL_INVALID")

    valid_agents = runtime_receipts.valid_tool_events(run, "Agent")
    completion = _event_by_receipt_hash(
        valid_agents, basis["completion_review_receipt_sha256"],
        code="COMPLETION_REVIEW_RECEIPT_RUNTIME_INVALID")
    if completion.get("completion_review") is not True \
            or completion.get("completion_plan_digest") \
            != plan.get("plan_digest") \
            or str(completion.get("session_id") or "") != session_id:
        raise CompletionError("COMPLETION_REVIEW_RECEIPT_RUNTIME_INVALID")
    completion_data = cycle_data.get("completion_review") \
        if isinstance(cycle_data.get("completion_review"), dict) else {}
    if completion_data != {
        "run": run.name,
        "evidence_index_hash": str(
            completion.get("evidence_index_hash") or ""),
        "completion_bundle_hash": str(
            completion.get("completion_bundle_hash") or ""),
    } or completion_data.get("evidence_index_hash") \
            != current_evidence_index_hash(run):
        raise CompletionError("COMPLETION_REVIEW_RECEIPT_RUNTIME_INVALID")

    valid_bash = runtime_receipts.valid_tool_events(run, "Bash")
    check = _event_by_receipt_hash(
        valid_bash, basis["closure_check_receipt_sha256"],
        code="COMPLETION_CLOSURE_CHECK_RECEIPT_INVALID")
    completion_seq = int(completion.get("seq") or 0)
    check_seq = int(check.get("seq") or 0)
    if check.get("capability_id") != "verify.check-run" \
            or str(check.get("session_id") or "") != session_id \
            or check_seq <= completion_seq:
        raise CompletionError("COMPLETION_CLOSURE_CHECK_RECEIPT_INVALID")
    stdout = _response_stdout(str(check.get("response_excerpt") or ""))
    if not stdout.startswith(CHECK_TOKEN_PREFIX):
        raise CompletionError("COMPLETION_CHECK_TOKEN_NOT_AT_STDOUT_START")
    token_payload = _parse_check_run_token(stdout.splitlines()[0])
    if _json_hash(token_payload) != basis["closure_check_token_sha256"] \
            or token_payload.get("run_name") != run.name \
            or token_payload.get("closure_input_sha256") \
            != basis["closure_input_sha256"] \
            or token_payload.get("warning_codes") != basis["warning_codes"]:
        raise CompletionError("COMPLETION_CHECK_TOKEN_STALE")

    loop_requested = contract.get("loop_requested") is True
    if loop_requested != (basis["cron_disposition"] == "quiescent"):
        raise CompletionError("COMPLETION_CRON_DISPOSITION_INVALID")
    if basis["cron_disposition"] == "not_requested":
        if basis["cron_receipt_sha256"]:
            raise CompletionError("COMPLETION_CRON_RECEIPT_INVALID")
    else:
        cron = _event_by_receipt_hash(
            runtime, basis["cron_receipt_sha256"],
            code="COMPLETION_CRON_RECEIPT_INVALID")
        cron_seq = int(cron.get("seq") or 0)
        response = str(cron.get("response_excerpt") or "").lower()
        later_mutation = any(
            str(row.get("session_id") or "") == session_id
            and str(row.get("tool_name") or "") in {"CronCreate", "CronDelete"}
            and cron_seq < int(row.get("seq") or 0) < check_seq
            for row in runtime
        )
        if cron.get("tool_name") != "CronList" \
                or str(cron.get("session_id") or "") != session_id \
                or not completion_seq < cron_seq < check_seq \
                or list(cron.get("listed_run_job_ids") or []) \
                or run.name.lower() in response or later_mutation \
                or float(check.get("ts") or 0.0) \
                - float(cron.get("ts") or 0.0) > 300:
            raise CompletionError("COMPLETION_CRON_NOT_QUIESCENT")

    _runtime_tail_cas(run, receipt)

    archive_rel = (
        TRANSACTIONS_REL / "receipts" / f"{receipt['receipt_sha256']}.json")
    archived = validate_receipt(_strict_json(
        _stable_bytes(run, archive_rel), archive_rel.as_posix()))
    intent_rel = (
        TRANSACTIONS_REL / receipt["transaction_id"] / "commit_intent.json")
    intent = validate_receipt(_strict_json(
        _stable_bytes(run, intent_rel), intent_rel.as_posix()))
    if archived != receipt or intent != receipt:
        raise CompletionError("COMPLETION_TERMINAL_RECEIPT_DIVERGED")
    for name, digest in (
        ("report.before.md", receipt["report_transition"]["before_sha256"]),
        ("report.after.md", receipt["report_transition"]["after_sha256"]),
        ("decisions.before.md", receipt["decisions_transition"]["before_sha256"]),
        ("decisions.after.md", receipt["decisions_transition"]["after_sha256"]),
    ):
        _load_stage_file(run, receipt, name, digest)


def prepare(
    run_dir: str | Path,
    *,
    mode: str,
    review_receipts: Iterable[str],
    review_limitations: Iterable[str],
    cron_disposition: str,
    warning_dispositions: Iterable[str] = (),
) -> dict:
    run = _resolve_run(run_dir)
    if mode not in {"ghost", "normal"}:
        raise CompletionError("COMPLETION_MODE_INVALID")
    with _completion_lock(run):
        current = _read_current(run)
        if current and current["status"] != "reopened":
            raise CompletionError(
                "COMPLETION_TRANSACTION_PENDING" if current["status"] == "prepared"
                else "COMPLETION_REOPEN_REQUIRED")
        decisions_before = _stable_bytes(run, "decisions.md")
        if MARKER_RE.search(_strict_text(decisions_before, "decisions.md")):
            raise CompletionError("COMPLETION_LEGACY_UNBOUND")
        report_before = _stable_bytes(run, "report.md")
        report_after = _set_report_status(report_before, {"READY"}, "FINAL")
        policy, bindings, receipt_hashes = _load_policy_and_bindings(
            run, review_receipts, review_limitations)
        warnings = _parse_warning_dispositions(warning_dispositions)
        basis = _latest_basis(
            run, cron_disposition=cron_disposition,
            warning_dispositions=warnings)
        manifest = _manifest(run, receipt_hashes)
        if closure_input_digest(run) != basis["closure_input_sha256"]:
            raise CompletionError("COMPLETION_INPUT_CHANGED_DURING_PREPARE")
        transaction_id = uuid.uuid4().hex
        marker = "GHOST_COMPLETE" if mode == "ghost" else "NORMAL_COMPLETE"
        receipt = {
            "schema": SCHEMA,
            "status": "prepared",
            "transaction_id": transaction_id,
            "run_name": run.name,
            "mode": mode,
            "marker": marker,
            "manifest": manifest,
            "manifest_sha256": _json_hash(manifest),
            "basis": basis,
            "review_policy": policy,
            "review_policy_sha256": _json_hash(policy),
            "review_bindings": bindings,
            "report_transition": {
                "path": "report.md",
                "before_sha256": _bytes_hash(report_before),
                "after_sha256": _bytes_hash(report_after),
            },
            "decisions_transition": {
                "path": "decisions.md",
                "before_sha256": _bytes_hash(decisions_before),
                "after_sha256": "0" * 64,
            },
            "prepared_at": time.time(),
            "terminal_at": 0,
            "previous_receipt_sha256": current["receipt_sha256"] if current else "",
            "completion_binding_sha256": "0" * 64,
            "receipt_sha256": "0" * 64,
            "legacy_unbound": False,
            "reopen_reason": "",
        }
        # The binding intentionally excludes decisions.after: the marker embeds
        # the binding, so including its own post-image digest would be cyclic.
        receipt["completion_binding_sha256"] = _json_hash(_binding_core(receipt))
        decisions_after = _append_marker(
            decisions_before, marker, receipt["completion_binding_sha256"])
        receipt["decisions_transition"]["after_sha256"] = _bytes_hash(decisions_after)
        receipt = _seal(receipt)
        validate_receipt(receipt)
        _write_stage(
            run, receipt,
            report_before=report_before, report_after=report_after,
            decisions_before=decisions_before, decisions_after=decisions_after,
        )
        _write_current(run, receipt)
        return receipt


def commit(run_dir: str | Path, *, fault: str = "") -> dict:
    run = _resolve_run(run_dir)
    with _completion_lock(run):
        receipt = _read_current(run)
        if not receipt:
            raise CompletionError("COMPLETION_PREPARED_REQUIRED")
        if receipt["status"] == "committed":
            _assert_committed_manifest(run, receipt)
            _assert_committed_authority(run, receipt)
            _archive_receipt(run, receipt)
            return receipt
        if receipt["status"] != "prepared" or receipt["legacy_unbound"]:
            raise CompletionError("COMPLETION_PREPARED_REQUIRED")
        commit_intent_path = (
            _stage_path(run, receipt["transaction_id"]) / "commit_intent.json")
        if not commit_intent_path.exists():
            latest_basis = _latest_basis(
                run,
                cron_disposition=str(receipt["basis"]["cron_disposition"]),
                warning_dispositions=list(receipt["basis"]["warning_dispositions"]),
            )
            if _basis_semantics(latest_basis) != _basis_semantics(receipt["basis"]):
                raise CompletionError("COMPLETION_BASIS_DIVERGED_AFTER_PREPARE")
        report_after = _load_stage_file(
            run, receipt, "report.after.md",
            receipt["report_transition"]["after_sha256"])
        decisions_after = _load_stage_file(
            run, receipt, "decisions.after.md",
            receipt["decisions_transition"]["after_sha256"])
        report_state, decisions_state = _manifest_cas(run, receipt, allow_targets=True)
        if decisions_state == "after" and report_state != "after":
            raise CompletionError("COMPLETION_RECOVERY_ORDER_INVALID")
        terminal = _terminal_intent(run, receipt, status="committed", reason="")
        if report_state == "before":
            _atomic_bytes(run, run / "report.md", report_after)
        if fault == "after_report":
            raise CompletionError("COMPLETION_FAULT_INJECTED", fault)
        if decisions_state == "before":
            _atomic_bytes(run, run / "decisions.md", decisions_after)
        if fault == "after_decisions":
            raise CompletionError("COMPLETION_FAULT_INJECTED", fault)
        _assert_committed_targets(run, terminal)
        _archive_receipt(run, terminal)
        if fault == "after_archive":
            raise CompletionError("COMPLETION_FAULT_INJECTED", fault)
        _write_current(run, terminal)
        return terminal


def _legacy_prepared(run: Path, reason: str) -> dict:
    report_before = _stable_bytes(run, "report.md")
    decisions_before = _stable_bytes(run, "decisions.md")
    decisions_clean, markers = _strip_markers(decisions_before)
    marker_names = {item[0] for item in markers}
    if len(markers) != 1 or len(marker_names) != 1:
        raise CompletionError("COMPLETION_LEGACY_MARKERS_AMBIGUOUS")
    mode = "ghost" if next(iter(marker_names)) == "GHOST_COMPLETE" else "normal"
    try:
        report_after = _set_report_status(report_before, {"FINAL", "READY"}, "READY")
    except CompletionError as exc:
        if exc.code != "COMPLETION_REPORT_STATUS_INVALID":
            raise
        raise CompletionError("COMPLETION_LEGACY_REPORT_STATUS_INVALID") from exc
    manifest = [_manifest_entry(run, item) for item in sorted(CANONICAL_PATHS)]
    receipt = {
        "schema": SCHEMA,
        "status": "prepared",
        "transaction_id": uuid.uuid4().hex,
        "run_name": run.name,
        "mode": mode,
        "marker": "GHOST_COMPLETE" if mode == "ghost" else "NORMAL_COMPLETE",
        "manifest": manifest,
        "manifest_sha256": _json_hash(manifest),
        "basis": _empty_basis(),
        "review_policy": {},
        "review_policy_sha256": "",
        "review_bindings": [],
        "report_transition": {
            "path": "report.md", "before_sha256": _bytes_hash(report_before),
            "after_sha256": _bytes_hash(report_after),
        },
        "decisions_transition": {
            "path": "decisions.md", "before_sha256": _bytes_hash(decisions_before),
            "after_sha256": "0" * 64,
        },
        "prepared_at": time.time(), "terminal_at": 0,
        "previous_receipt_sha256": "",
        "completion_binding_sha256": "0" * 64,
        "receipt_sha256": "0" * 64,
        "legacy_unbound": True,
        "reopen_reason": "",
    }
    receipt["completion_binding_sha256"] = _json_hash(_binding_core(receipt))
    newline = "\r\n" if "\r\n" in _strict_text(decisions_before, "decisions.md") else "\n"
    cleaned_text = _strict_text(decisions_clean, "decisions.md")
    if cleaned_text and not cleaned_text.endswith(("\n", "\r")):
        cleaned_text += newline
    cleaned_text += (
        "COMPLETION_REOPENED legacy_unbound=true "
        f"receipt={receipt['completion_binding_sha256']}\n")
    decisions_after = cleaned_text.encode("utf-8")
    receipt["decisions_transition"]["after_sha256"] = _bytes_hash(decisions_after)
    receipt = _seal(receipt)
    validate_receipt(receipt)
    _write_stage(
        run, receipt,
        report_before=report_before, report_after=report_after,
        decisions_before=decisions_before, decisions_after=decisions_after,
    )
    _write_current(run, receipt)
    return receipt


def reopen(run_dir: str | Path, *, reason: str, fault: str = "") -> dict:
    run = _resolve_run(run_dir)
    clean_reason = str(reason or "").strip()
    if not clean_reason or len(clean_reason) > 2048:
        raise CompletionError("COMPLETION_REOPEN_REASON_INVALID")
    with _completion_lock(run):
        receipt = _read_current(run)
        if receipt and receipt["status"] == "reopened":
            if receipt["reopen_reason"] != clean_reason:
                raise CompletionError("COMPLETION_REOPEN_REASON_MISMATCH")
            return receipt
        if receipt is None:
            decisions = _strict_text(_stable_bytes(run, "decisions.md"), "decisions.md")
            if not MARKER_RE.search(decisions):
                raise CompletionError("COMPLETION_COMMITTED_REQUIRED")
            receipt = _legacy_prepared(run, clean_reason)
        if receipt["status"] not in {"committed", "prepared"}:
            raise CompletionError("COMPLETION_COMMITTED_REQUIRED")

        if receipt["legacy_unbound"]:
            report_target = _load_stage_file(
                run, receipt, "report.after.md",
                receipt["report_transition"]["after_sha256"])
            decisions_target = _load_stage_file(
                run, receipt, "decisions.after.md",
                receipt["decisions_transition"]["after_sha256"])
            report_state, decisions_state = _manifest_cas(
                run, receipt, allow_targets=True)
            desired_report_state = desired_decisions_state = "after"
        else:
            report_target = _load_stage_file(
                run, receipt, "report.before.md",
                receipt["report_transition"]["before_sha256"])
            decisions_target = _load_stage_file(
                run, receipt, "decisions.before.md",
                receipt["decisions_transition"]["before_sha256"])
            if receipt["status"] == "committed":
                _assert_committed_targets(run, receipt)
                _assert_committed_authority(run, receipt)
                report_state, decisions_state = "after", "after"
            else:
                report_state, decisions_state = _manifest_cas(
                    run, receipt, allow_targets=True)
                if decisions_state == "after" and report_state != "after":
                    raise CompletionError("COMPLETION_RECOVERY_ORDER_INVALID")
            desired_report_state = desired_decisions_state = "before"

        terminal = _terminal_intent(
            run, receipt, status="reopened", reason=clean_reason)
        if report_state != desired_report_state:
            _atomic_bytes(run, run / "report.md", report_target)
        if fault == "after_report":
            raise CompletionError("COMPLETION_FAULT_INJECTED", fault)
        if decisions_state != desired_decisions_state:
            _atomic_bytes(run, run / "decisions.md", decisions_target)
        if fault == "after_decisions":
            raise CompletionError("COMPLETION_FAULT_INJECTED", fault)
        _archive_receipt(run, terminal)
        _write_current(run, terminal)
        return terminal


def status(run_dir: str | Path) -> dict:
    run = _resolve_run(run_dir)
    current = _read_current(run)
    decisions = _strict_text(_stable_bytes(run, "decisions.md"), "decisions.md")
    markers = list(MARKER_RE.finditer(decisions))
    if current is None:
        return {
            "schema": "xunji.completion-status.v1",
            "run_name": run.name,
            "status": "legacy_unbound" if markers else "open",
            "transaction_id": "",
            "completion_binding_sha256": "",
        }
    if current["status"] == "committed":
        _assert_committed_manifest(run, current)
        _assert_committed_authority(run, current)
    return {
        "schema": "xunji.completion-status.v1",
        "run_name": run.name,
        "status": current["status"],
        "transaction_id": current["transaction_id"],
        "completion_binding_sha256": current["completion_binding_sha256"],
    }


def is_valid_committed(run_dir: str | Path) -> bool:
    """Fail-closed completion predicate for derived-state consumers.

    A legacy marker is deliberately false.  ``status`` also revalidates the
    committed manifest and terminal targets, so a stale or tampered transaction
    cannot stop schedulers or make a UI claim completion.
    """
    try:
        return status(run_dir).get("status") == "committed"
    except (CompletionError, OSError, ValueError, TypeError):
        return False


def terminal_gate_state(run_dir: str | Path) -> dict:
    """Stable read-only state consumed by the terminal PreToolUse gate."""
    try:
        value = status(run_dir)
        state = str(value.get("status") or "invalid")
        transaction_id = str(value.get("transaction_id") or "")
        current = _read_current(_resolve_run(run_dir))
    except Exception as exc:
        return {
            "schema": "xunji.completion-terminal-gate.v1",
            "status": "invalid",
            "transaction_id": "",
            "prepared_at": 0,
            "terminal_at": 0,
            "allowed_capability_ids": [],
            "allowed_effects": [],
            "error": f"{exc.__class__.__name__}: {exc}",
        }
    ids: list[str] = []
    effects: list[str] = []
    if state == "prepared":
        ids = [
            "read.completion-transaction-status",
            "control.completion-transaction-commit",
            "control.completion-transaction-reopen",
        ]
        effects = ["local_read"]
    elif state == "committed":
        ids = [
            "read.completion-transaction-status",
            "control.completion-transaction-reopen",
            "verify.check-run",
        ]
        # ``verify.check-run`` is the sole post-commit verifier.  Do not expose
        # the broader local_verify effect as terminal authority.
        effects = ["local_read"]
    return {
        "schema": "xunji.completion-terminal-gate.v1",
        "status": state,
        "transaction_id": transaction_id,
        "prepared_at": float(current.get("prepared_at") or 0.0) if current else 0,
        "terminal_at": float(current.get("terminal_at") or 0.0) if current else 0,
        "allowed_capability_ids": ids,
        "allowed_effects": effects,
        "error": "",
    }


def adopt_policy(run_dir: str | Path) -> dict:
    """Adopt the default policy for a legacy run, missing-only and idempotent."""
    run = _resolve_run(run_dir)
    policy = validate_policy(default_review_policy())
    with _completion_lock(run):
        path = run / POLICY_REL
        if path.exists():
            existing = validate_policy(_strict_json(
                _stable_bytes(run, POLICY_REL), str(POLICY_REL)))
            if existing != policy:
                raise CompletionError("COMPLETION_REVIEW_POLICY_ALREADY_EXISTS")
            return {
                "schema": "xunji.review-policy-adoption.v1",
                "run_name": run.name,
                "status": "already_present",
                "policy_sha256": _json_hash(policy),
            }
        current = _read_current(run)
        if current and current.get("status") in {"prepared", "committed"}:
            raise CompletionError("COMPLETION_POLICY_ADOPTION_TRANSACTION_ACTIVE")
        if current and current.get("status") != "reopened":
            raise CompletionError("COMPLETION_POLICY_ADOPTION_STATE_INVALID")
        _atomic_json(run, path, policy)
        return {
            "schema": "xunji.review-policy-adoption.v1",
            "run_name": run.name,
            "status": "adopted",
            "policy_sha256": _json_hash(policy),
        }


def _fixture_run(
    root: Path,
    name: str = "fixture_run",
    *,
    loop_requested: bool = False,
    stale_cron: bool = False,
    warning_messages: Iterable[str] = (),
) -> tuple[Path, str]:
    """Build a closure fixture exclusively through the production owners."""
    import peer_review

    run = root / name
    (run / "state").mkdir(parents=True)
    (run / "evidence").mkdir()
    bodies = {
        "target.md": "# Target\n- Authorized scope: app.example\n",
        "surface.md": "# Surface\n- app.example\n",
        "surface_recon.md": "# Surface Recon\n- none\n",
        "hypotheses.md": "# Hypotheses\n- none open\n",
        "frontier.md": (
            "# Frontier\n\n## Open Fronts\n\n## Deferred Fronts\n\n"
            "## Closed Fronts\n\n### F-001 — complete\n"
            "- Status: blocked_type_b\n- Barrier class: authorization\n"
            "- Current depth: moderate\n"
        ),
        "evidence.md": "# Evidence Ledger\n\n- No confirmed findings.\n",
        "false_positive.md": "# False-Positive Checks\n- none\n",
        "report.md": "# Report\n\n## Summary\n\n- Status: READY\n",
        "retrospective.md": (
            "# Retrospective\n\n## Self problems\n- Fixture checked closure.\n\n"
            "## Framework problems\n- Problem: fixture only\n- Status: fixed\n"
        ),
        "review.md": "# Review\n",
        "decisions.md": "# Decisions\n\n## D-001\n- Result: ready\n",
        "chains.md": "# Chains\n- none\n",
        "hints.md": "# Hints\n- none\n",
    }
    for relative, body in bodies.items():
        (run / relative).write_text(body, encoding="utf-8")
    (run / "coverage.json").write_text(json.dumps({
        "total": 1, "examined": 1, "reachable": 1,
        "assets": [{"host": "app.example", "examined": True,
                    "reachable": True, "verdict": "closed"}],
    }) + "\n", encoding="utf-8")
    (run / "state/conflicts.json").write_text("{}\n", encoding="utf-8")
    (run / POLICY_REL).write_text(json.dumps(
        default_review_policy(), sort_keys=True) + "\n", encoding="utf-8")

    bundle = peer_review.build_review_bundle(run, write=True)
    result = peer_review.ReviewResult(
        verdict="PASS", backend_used="panel:codex", driver="claude",
        brain="fixture-independent",
        bundle_hash=str(bundle["sha1"]),
        evidence_index_hash=str(bundle["evidence_index"]["sha1"]),
    )
    review_hash = peer_review._append_run_review(run, result)

    session_id = f"session-{name}"
    transcript = run / "fixture-transcript.jsonl"
    transcript.write_text(json.dumps({
        "message": {"role": "assistant", "content": [{
            "type": "tool_use", "id": "tool-peer-review",
            "name": "Bash", "input": {"command": (
                f"python3 tools/peer_review.py {run} --into-run --driver claude"
            )},
        }]},
    }) + "\n", encoding="utf-8")
    runtime_receipts.append_hook_event(run, {
        "hook_event_name": "PostToolUse", "session_id": session_id,
        "transcript_path": str(transcript), "tool_name": "Bash",
        "tool_use_id": "tool-peer-review",
        "tool_input": {"command": (
            f"python3 tools/peer_review.py {run} --into-run --driver claude"
        )},
        "tool_response": (
            f"XUNJI_REVIEW_RECEIPT={review_hash}\n"
            f"XUNJI_REVIEW_BUNDLE={bundle['sha1']}\n"
        ),
        "xunji_capability_id": "review.peer-review",
        "xunji_capability_effect": "model_egress",
    })

    prompt = "/loop" if loop_requested else "继续执行当前授权任务"
    contract = turn_contract.write_contract(run, {
        "prompt": prompt, "session_id": session_id,
        "transcript_path": str(transcript),
    })
    plan = work_plan.commit_plan(
        run, macro_stage="S3", objective="verify closure parity",
        mode="COMPLETION_REVIEW", reason="zero open fronts",
        exit_gate="global completion challenge passes", lanes=[],
        contract=contract,
    )
    anti_drift.record_reason_pass(
        run, chosen_front="NONE", reason="all canonical closure inputs reread")

    state = runtime_receipts.completion_review_state(
        run, require_current_inputs=True)
    prompt = runtime_receipts.completion_review_prompt(run)
    result_envelope = runtime_receipts.completion_review_result_envelope(
        run.name, str(state["evidence_index_hash"]),
        str(state["completion_bundle_hash"]),
    )
    with transcript.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps({
            "message": {"role": "assistant", "content": [{
                "type": "tool_use", "id": "tool-completion-review",
                "name": "Agent", "input": {
                    "prompt": prompt, "subagent_type": "xunji-reviewer",
                },
            }]},
        }) + "\n")
    runtime_receipts.append_hook_event(run, {
        "hook_event_name": "PostToolUse", "session_id": session_id,
        "transcript_path": str(transcript), "tool_name": "Agent",
        "tool_use_id": "tool-completion-review",
        "tool_input": {"prompt": prompt, "subagent_type": "xunji-reviewer"},
        "tool_response": {"agentId": "completion-review-child",
                          "isAsync": True, "status": "async_launched"},
    })
    runtime_receipts.append_hook_event(run, {
        "hook_event_name": "SubagentStart", "session_id": session_id,
        "transcript_path": str(transcript),
        "agent_id": "completion-review-child", "agent_type": "xunji-reviewer",
    })
    runtime_receipts.append_hook_event(run, {
        "hook_event_name": "SubagentStop", "session_id": session_id,
        "transcript_path": str(transcript),
        "agent_id": "completion-review-child", "agent_type": "xunji-reviewer",
        "last_assistant_message": result_envelope,
    })
    if not runtime_receipts.completion_review_valid(
            run, current_evidence_index_hash(run)):
        raise AssertionError("fixture completion review is not valid")
    loop_journal.append_event(
        run, "cycle_end", note="completion review settled",
        next_action="run check_run.py closure verification",
    )
    if loop_requested:
        cron_event = {
            "hook_event_name": "PostToolUse", "session_id": session_id,
            "transcript_path": str(transcript), "tool_name": "CronList",
            "tool_use_id": "tool-cron-list", "tool_input": {},
            "tool_response": {"tasks": []},
        }
        if stale_cron:
            from unittest import mock
            with mock.patch.object(
                    runtime_receipts.time, "time", return_value=time.time() - 301):
                runtime_receipts.append_hook_event(run, cron_event)
        else:
            runtime_receipts.append_hook_event(run, cron_event)

    token, _codes = build_check_run_token(run, warning_messages)
    with transcript.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps({
            "message": {"role": "assistant", "content": [{
                "type": "tool_use", "id": "tool-check-run", "name": "Bash",
                "input": {"command": f"python3 tools/check_run.py {run}"},
            }]},
        }) + "\n")
    runtime_receipts.append_hook_event(run, {
        "hook_event_name": "PostToolUse", "session_id": session_id,
        "transcript_path": str(transcript), "tool_name": "Bash",
        "tool_use_id": "tool-check-run",
        "tool_input": {"command": f"python3 tools/check_run.py {run}"},
        "tool_response": token + "\nSTRUCTURAL_PASS: fixture",
        "xunji_capability_id": "verify.check-run",
        "xunji_capability_effect": "local_verify",
    })
    assert plan["plan_digest"] == work_plan.transaction_bound_plan(run)["plan_digest"]
    return run, review_hash


def _selftest() -> int:
    root = Path(tempfile.mkdtemp(prefix="xunji-completion-transaction-"))
    checks: list[tuple[str, bool]] = []
    try:
        run, review_hash = _fixture_run(root)
        receipt = prepare(
            run, mode="ghost",
            review_receipts=[f"independent-review={review_hash}"],
            review_limitations=["external-assistance=provider unavailable"],
            cron_disposition="not_requested")
        checks.append(("prepare is noncanonical and schema-valid",
                       receipt["status"] == "prepared"
                       and _parse_status((run / "report.md").read_bytes())[0] == "READY"
                       and not MARKER_RE.search((run / "decisions.md").read_text())
                       and validate_receipt(receipt) == receipt))

        original_surface = (run / "surface.md").read_bytes()
        (run / "surface.md").write_bytes(original_surface + b"drift\n")
        cas_blocked = False
        try:
            commit(run)
        except CompletionError as exc:
            cas_blocked = exc.code.startswith("COMPLETION_")
        (run / "surface.md").write_bytes(original_surface)
        checks.append(("manifest CAS rejects canonical drift", cas_blocked))

        crash_seen = False
        try:
            commit(run, fault="after_report")
        except CompletionError as exc:
            crash_seen = exc.code == "COMPLETION_FAULT_INJECTED"
        committed = commit(run)
        marker_line = [line for line in (run / "decisions.md").read_text().splitlines()
                       if line.strip()][-1]
        checks.append(("commit recovers forward after report publication",
                       crash_seen and committed["status"] == "committed"
                       and _parse_status((run / "report.md").read_bytes())[0] == "FINAL"
                       and marker_line == (
                           "GHOST_COMPLETE receipt="
                           + committed["completion_binding_sha256"])))
        checks.append(("commit retry is idempotent", commit(run) == committed))
        checks.append(("public committed predicate validates the transaction",
                       is_valid_committed(run)))
        current_bytes = (run / CURRENT_REL).read_bytes()
        forged_current = json.loads(current_bytes)
        forged_current["manifest"] = forged_current["manifest"][:9]
        forged_current["manifest_sha256"] = _json_hash(
            forged_current["manifest"])
        forged_current = _seal(forged_current)
        _atomic_json(run, run / CURRENT_REL, forged_current)
        incomplete_self_hashed_rejected = not is_valid_committed(run)
        _atomic_bytes(run, run / CURRENT_REL, current_bytes)
        checks.append((
            "self-hashed receipt cannot omit dynamically required manifest paths",
            incomplete_self_hashed_rejected,
        ))
        committed_gate = terminal_gate_state(run)
        checks.append(("terminal API grants only the exact post-commit verifier",
                       committed_gate["status"] == "committed"
                       and "verify.check-run"
                       in committed_gate["allowed_capability_ids"]
                       and "local_verify" not in committed_gate["allowed_effects"]))

        frozen_evidence = (run / "evidence.md").read_bytes()
        (run / "evidence.md").write_bytes(frozen_evidence + b"new evidence\n")
        stale_completion = False
        try:
            status(run)
        except CompletionError as exc:
            stale_completion = exc.code in {
                "COMPLETION_MANIFEST_CAS_MISMATCH",
                "COMPLETION_MANIFEST_PATH_SET_INVALID",
                "COMPLETION_REVIEW_EVIDENCE_STALE",
                "COMPLETION_CLOSURE_INPUT_RECEIPT_INVALID",
            }
        stale_completion = stale_completion and not is_valid_committed(run)
        (run / "evidence.md").write_bytes(frozen_evidence)
        checks.append(("post-commit canonical drift invalidates completion",
                       stale_completion))

        reopened = reopen(run, reason="new evidence arrived")
        checks.append(("reopen restores exact prepared canonical preimages",
                       reopened["status"] == "reopened"
                       and _parse_status((run / "report.md").read_bytes())[0] == "READY"
                       and not MARKER_RE.search((run / "decisions.md").read_text())))
        checks.append(("reopen retry is idempotent",
                       reopen(run, reason="new evidence arrived") == reopened))

        mandatory_run, mandatory_hash = _fixture_run(root, "mandatory_missing")
        mandatory_blocked = False
        try:
            prepare(
                mandatory_run, mode="normal", review_receipts=[],
                review_limitations=["external-assistance=unavailable"],
                cron_disposition="not_requested")
        except CompletionError as exc:
            mandatory_blocked = exc.code == "COMPLETION_MANDATORY_REVIEW_MISSING"
        checks.append(("mandatory review cannot downgrade to limitation", mandatory_blocked))

        optional_run, optional_hash = _fixture_run(root, "optional_unresolved")
        optional_blocked = False
        try:
            prepare(
                optional_run, mode="normal",
                review_receipts=[f"independent-review={optional_hash}"],
                review_limitations=[], cron_disposition="not_requested")
        except CompletionError as exc:
            optional_blocked = exc.code == "COMPLETION_OPTIONAL_REVIEW_UNRESOLVED"
        checks.append(("optional unavailable slot records a limitation", optional_blocked))

        draft_run, draft_hash = _fixture_run(root, "draft_report")
        (draft_run / "report.md").write_text(
            "# Report\n\n## Summary\n\n- Status: DRAFT\n", encoding="utf-8")
        draft_blocked = False
        try:
            prepare(
                draft_run, mode="normal",
                review_receipts=[f"independent-review={draft_hash}"],
                review_limitations=["external-assistance=unavailable"],
                cron_disposition="not_requested")
        except CompletionError as exc:
            draft_blocked = exc.code == "COMPLETION_REPORT_STATUS_INVALID"
        checks.append(("only READY report can enter completion prepare", draft_blocked))

        transaction_run, transaction_hash = _fixture_run(root, "plan_tx_tamper")
        plan_transaction_path = transaction_run / "state/work_plan_transaction.json"
        plan_transaction = json.loads(plan_transaction_path.read_text(encoding="utf-8"))
        plan_transaction["plan"]["objective"] = "tampered after commit"
        plan_transaction_path.write_text(
            json.dumps(plan_transaction) + "\n", encoding="utf-8")
        transaction_blocked = False
        try:
            prepare(
                transaction_run, mode="normal",
                review_receipts=[f"independent-review={transaction_hash}"],
                review_limitations=["external-assistance=unavailable"],
                cron_disposition="not_requested")
        except CompletionError as exc:
            transaction_blocked = (
                exc.code == "COMPLETION_WORK_PLAN_TRANSACTION_INVALID")
        checks.append(("S3 plan must match its committed transaction receipt",
                       transaction_blocked))

        cancel_run, cancel_hash = _fixture_run(root, "cancel_prepared")
        prepare(
            cancel_run, mode="normal",
            review_receipts=[f"independent-review={cancel_hash}"],
            review_limitations=["external-assistance=unavailable"],
            cron_disposition="not_requested")
        cancelled = reopen(cancel_run, reason="closure basis changed before commit")
        checks.append(("explicit reopen cancels a prepared transaction safely",
                       cancelled["status"] == "reopened"
                       and _parse_status((cancel_run / "report.md").read_bytes())[0]
                       == "READY"
                       and not MARKER_RE.search(
                           (cancel_run / "decisions.md").read_text())))

        external_run, external_hash = _fixture_run(root, "external_claim")
        external_not_proven = False
        try:
            prepare(
                external_run, mode="normal",
                review_receipts=[
                    f"independent-review={external_hash}",
                    f"external-assistance={external_hash}",
                ],
                review_limitations=[], cron_disposition="not_requested")
        except CompletionError as exc:
            external_not_proven = (
                exc.code == "COMPLETION_EXTERNAL_ASSISTANCE_NOT_PROVEN")
        checks.append(("external assistance is derived from receipt backend",
                       external_not_proven))

        status_run, _ = _fixture_run(root, "legacy")
        (status_run / "report.md").write_text(
            "# Report\n\n## Summary\n\n- Status: FINAL\n", encoding="utf-8")
        (status_run / "decisions.md").write_text(
            "# Decisions\n\nGHOST_COMPLETE\n", encoding="utf-8")
        checks.append(("unbound old marker is classified, not trusted",
                       status(status_run)["status"] == "legacy_unbound"
                       and not is_valid_committed(status_run)))
        legacy_prepare_blocked = False
        try:
            prepare(
                status_run, mode="ghost", review_receipts=[], review_limitations=[],
                cron_disposition="not_requested")
        except CompletionError as exc:
            legacy_prepare_blocked = exc.code == "COMPLETION_LEGACY_UNBOUND"
        legacy = reopen(status_run, reason="adopt transaction owner")
        checks.append(("legacy marker requires explicit typed reopen",
                       legacy_prepare_blocked and legacy["status"] == "reopened"
                       and legacy["legacy_unbound"]
                       and _parse_status((status_run / "report.md").read_bytes())[0] == "READY"
                       and "GHOST_COMPLETE" not in (status_run / "decisions.md").read_text()))

        unknown = dict(committed)
        unknown["unknown"] = True
        checks.append(("closed schema rejects unknown receipt fields",
                       bool(contract_schema.named_schema_errors(unknown, SCHEMA_FILE))))
        bad_policy = {
            "schema": POLICY_SCHEMA, "policy_id": "p", "slots": [{
                "slot_id": "x", "role": "fresh", "requirement": "mandatory",
                "command": "untrusted",
            }],
        }
        checks.append(("closed policy cannot inject backend commands",
                       bool(contract_schema.named_schema_errors(
                           bad_policy, POLICY_SCHEMA_FILE))))

        symlink_run, symlink_hash = _fixture_run(root, "symlink")
        target = symlink_run / "real-surface.md"
        target.write_text("# Surface\n", encoding="utf-8")
        (symlink_run / "surface.md").unlink()
        (symlink_run / "surface.md").symlink_to(target.name)
        symlink_blocked = False
        try:
            prepare(
                symlink_run, mode="normal",
                review_receipts=[f"independent-review={symlink_hash}"],
                review_limitations=["external-assistance=unavailable"],
                cron_disposition="not_requested")
        except CompletionError as exc:
            symlink_blocked = exc.code.startswith("COMPLETION_")
        checks.append(("manifest rejects symlinked canonical files", symlink_blocked))

        (symlink_run / "evidence" / "real").mkdir(parents=True)
        (symlink_run / "evidence" / "real" / "nested.txt").write_text(
            "proof", encoding="utf-8")
        (symlink_run / "evidence" / "linked").symlink_to(
            symlink_run / "evidence" / "real", target_is_directory=True)
        intermediate_blocked = False
        try:
            _stable_bytes(symlink_run, "evidence/linked/nested.txt")
        except CompletionError as exc:
            intermediate_blocked = exc.code in {
                "COMPLETION_PATH_SYMLINK", "COMPLETION_FILE_READ_FAILED",
            }
        checks.append(("secure open rejects intermediate symlink components",
                       intermediate_blocked))

        bounded = symlink_run / "bounded.txt"
        bounded.write_bytes(b"12345")
        oversize_blocked = False
        try:
            _stable_bytes(symlink_run, "bounded.txt", max_bytes=4)
        except CompletionError as exc:
            oversize_blocked = exc.code == "COMPLETION_FILE_TOO_LARGE"
        checks.append(("completion file reads enforce a hard byte limit",
                       oversize_blocked))

        forged_chain_run, forged_chain_hash = _fixture_run(root, "forged_chain")
        with (forged_chain_run / "state/runtime_events.jsonl").open(
                "a", encoding="utf-8") as handle:
            handle.write('{"schema":"xunji.runtime_receipt.v1","forged":true}\n')
        forged_chain_blocked = False
        try:
            prepare(
                forged_chain_run, mode="normal",
                review_receipts=[f"independent-review={forged_chain_hash}"],
                review_limitations=["external-assistance=unavailable"],
                cron_disposition="not_requested")
        except CompletionError as exc:
            forged_chain_blocked = exc.code in {
                "COMPLETION_REVIEW_INVOCATION_INVALID",
                "COMPLETION_RUNTIME_CHAIN_INVALID",
            }
        checks.append(("forged runtime hash chain cannot satisfy closure",
                       forged_chain_blocked))

        prose_run, prose_hash = _fixture_run(root, "forged_structural_pass")
        runtime_path = prose_run / "state/runtime_events.jsonl"
        runtime_lines = runtime_path.read_text(encoding="utf-8").splitlines()
        runtime_path.write_text("\n".join(runtime_lines[:-1]) + "\n", encoding="utf-8")
        runtime_receipts.append_hook_event(prose_run, {
            "hook_event_name": "PostToolUse",
            "session_id": f"session-{prose_run.name}",
            "transcript_path": str(prose_run / "fixture-transcript.jsonl"),
            "tool_name": "Bash", "tool_use_id": "tool-forged-check",
            "tool_input": {"command": f"python3 tools/check_run.py {prose_run}"},
            "tool_response": "STRUCTURAL_PASS: forged prose",
            "xunji_capability_id": "verify.check-run",
            "xunji_capability_effect": "local_verify",
        })
        prose_blocked = False
        try:
            prepare(
                prose_run, mode="normal",
                review_receipts=[f"independent-review={prose_hash}"],
                review_limitations=["external-assistance=unavailable"],
                cron_disposition="not_requested")
        except CompletionError as exc:
            prose_blocked = exc.code == "COMPLETION_CLOSURE_CHECK_RECEIPT_INVALID"
        checks.append(("forged STRUCTURAL_PASS prose is not a check receipt",
                       prose_blocked))

        drift_run, drift_hash = _fixture_run(root, "drift_after_check")
        (drift_run / "surface.md").write_text(
            "# Surface\n- app.example\n- drift after check\n", encoding="utf-8")
        drift_blocked = False
        try:
            prepare(
                drift_run, mode="normal",
                review_receipts=[f"independent-review={drift_hash}"],
                review_limitations=["external-assistance=unavailable"],
                cron_disposition="not_requested")
        except CompletionError as exc:
            drift_blocked = exc.code.startswith("COMPLETION_")
        checks.append(("canonical drift after check invalidates its token",
                       drift_blocked))

        warning_message = "fixture closure warning"
        warning_run, warning_hash = _fixture_run(
            root, "warning_mismatch", warning_messages=[warning_message])
        warning_mismatch = False
        try:
            prepare(
                warning_run, mode="normal",
                review_receipts=[f"independent-review={warning_hash}"],
                review_limitations=["external-assistance=unavailable"],
                cron_disposition="not_requested")
        except CompletionError as exc:
            warning_mismatch = exc.code == "COMPLETION_WARNING_DISPOSITION_MISMATCH"
        exact_warning_run, exact_warning_hash = _fixture_run(
            root, "warning_exact", warning_messages=[warning_message])
        exact_warning = prepare(
            exact_warning_run, mode="normal",
            review_receipts=[f"independent-review={exact_warning_hash}"],
            review_limitations=["external-assistance=unavailable"],
            cron_disposition="not_requested",
            warning_dispositions=[
                f"{warning_code(warning_message)}:accepted:operator reviewed"
            ],
        )
        checks.append(("warning dispositions exactly cover check warning IDs",
                       warning_mismatch and exact_warning["status"] == "prepared"))

        loop_run, loop_hash = _fixture_run(
            root, "loop_wrong_disposition", loop_requested=True)
        wrong_cron = False
        try:
            prepare(
                loop_run, mode="normal",
                review_receipts=[f"independent-review={loop_hash}"],
                review_limitations=["external-assistance=unavailable"],
                cron_disposition="not_requested")
        except CompletionError as exc:
            wrong_cron = exc.code == "COMPLETION_CRON_DISPOSITION_REQUIRED"
        stale_loop_run, stale_loop_hash = _fixture_run(
            root, "loop_stale_cron", loop_requested=True, stale_cron=True)
        stale_cron_blocked = False
        try:
            prepare(
                stale_loop_run, mode="normal",
                review_receipts=[f"independent-review={stale_loop_hash}"],
                review_limitations=["external-assistance=unavailable"],
                cron_disposition="quiescent")
        except CompletionError as exc:
            stale_cron_blocked = exc.code in {
                "COMPLETION_CRON_NOT_QUIESCENT",
                "COMPLETION_RUNTIME_CHAIN_INVALID",
            }
        checks.append(("loop contract rejects wrong or stale Cron disposition",
                       wrong_cron and stale_cron_blocked))

        review_run, review_hash_bad = _fixture_run(root, "invalid_review_receipt")
        receipt_path = review_run / f"review/receipts/{review_hash_bad}.json"
        bad_receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
        bad_receipt["result"]["brain"] = "tampered"
        receipt_path.write_text(json.dumps(bad_receipt) + "\n", encoding="utf-8")
        invalid_receipt_blocked = False
        try:
            prepare(
                review_run, mode="normal",
                review_receipts=[f"independent-review={review_hash_bad}"],
                review_limitations=["external-assistance=unavailable"],
                cron_disposition="not_requested")
        except CompletionError as exc:
            invalid_receipt_blocked = exc.code == "COMPLETION_REVIEW_RECEIPT_INVALID"

        bundle_run, bundle_receipt = _fixture_run(root, "invalid_review_bundle")
        bundle_path = bundle_run / "review/review_bundle.json"
        bad_bundle = json.loads(bundle_path.read_text(encoding="utf-8"))
        bad_bundle["note"] = "tampered"
        bundle_path.write_text(json.dumps(bad_bundle) + "\n", encoding="utf-8")
        invalid_bundle_blocked = False
        try:
            prepare(
                bundle_run, mode="normal",
                review_receipts=[f"independent-review={bundle_receipt}"],
                review_limitations=["external-assistance=unavailable"],
                cron_disposition="not_requested")
        except CompletionError as exc:
            invalid_bundle_blocked = exc.code == "COMPLETION_REVIEW_BUNDLE_INVALID"

        invocation_run, invocation_receipt = _fixture_run(
            root, "invalid_review_invocation")
        transcript_path = invocation_run / "fixture-transcript.jsonl"
        transcript_path.write_text(
            transcript_path.read_text(encoding="utf-8").replace(
                "tool-peer-review", "missing-peer-tool"),
            encoding="utf-8",
        )
        invalid_invocation_blocked = False
        try:
            prepare(
                invocation_run, mode="normal",
                review_receipts=[f"independent-review={invocation_receipt}"],
                review_limitations=["external-assistance=unavailable"],
                cron_disposition="not_requested")
        except CompletionError as exc:
            invalid_invocation_blocked = (
                exc.code == "COMPLETION_REVIEW_INVOCATION_INVALID")
        checks.append(("invalid review id, bundle, or invocation is rejected",
                       invalid_receipt_blocked and invalid_bundle_blocked
                       and invalid_invocation_blocked))

        effect_run, effect_hash = _fixture_run(root, "effect_after_prepare")
        prepare(
            effect_run, mode="normal",
            review_receipts=[f"independent-review={effect_hash}"],
            review_limitations=["external-assistance=unavailable"],
            cron_disposition="not_requested")
        runtime_receipts.append_hook_event(effect_run, {
            "hook_event_name": "PostToolUse",
            "session_id": f"session-{effect_run.name}",
            "transcript_path": str(effect_run / "fixture-transcript.jsonl"),
            "tool_name": "CronList", "tool_use_id": "tool-late-cron",
            "tool_input": {}, "tool_response": {"tasks": []},
        })
        late_effect_blocked = False
        try:
            commit(effect_run)
        except CompletionError as exc:
            late_effect_blocked = (
                exc.code == "COMPLETION_RUNTIME_EFFECT_AFTER_PREPARE")
        checks.append(("target/Agent/Cron receipts after prepare block commit",
                       late_effect_blocked))

        adopt_run, adopt_hash = _fixture_run(root, "legacy_adopt")
        (adopt_run / POLICY_REL).unlink()
        adopted = adopt_policy(adopt_run)
        new_token, _ = build_check_run_token(adopt_run, [])
        adopt_transcript = adopt_run / "fixture-transcript.jsonl"
        with adopt_transcript.open("a", encoding="utf-8") as handle:
            handle.write("tool-check-after-adopt\n")
        runtime_receipts.append_hook_event(adopt_run, {
            "hook_event_name": "PostToolUse",
            "session_id": f"session-{adopt_run.name}",
            "transcript_path": str(adopt_transcript), "tool_name": "Bash",
            "tool_use_id": "tool-check-after-adopt",
            "tool_input": {"command": f"python3 tools/check_run.py {adopt_run}"},
            "tool_response": new_token + "\nSTRUCTURAL_PASS: recertified",
            "xunji_capability_id": "verify.check-run",
            "xunji_capability_effect": "local_verify",
        })
        adopted_prepared = prepare(
            adopt_run, mode="normal",
            review_receipts=[f"independent-review={adopt_hash}"],
            review_limitations=["external-assistance=unavailable"],
            cron_disposition="not_requested")
        adopted_committed = commit(adopt_run)
        post_token, _ = build_check_run_token(adopt_run, [])
        with adopt_transcript.open("a", encoding="utf-8") as handle:
            handle.write("tool-check-post-commit\n")
        runtime_receipts.append_hook_event(adopt_run, {
            "hook_event_name": "PostToolUse",
            "session_id": f"session-{adopt_run.name}",
            "transcript_path": str(adopt_transcript), "tool_name": "Bash",
            "tool_use_id": "tool-check-post-commit",
            "tool_input": {"command": f"python3 tools/check_run.py {adopt_run}"},
            "tool_response": post_token + "\nSTRUCTURAL_PASS: post commit",
            "xunji_capability_id": "verify.check-run",
            "xunji_capability_effect": "local_verify",
        })
        checks.append(("legacy policy adoption enables recertification and post-commit check",
                       adopted["status"] == "adopted"
                       and adopted_prepared["status"] == "prepared"
                       and adopted_committed["status"] == "committed"
                       and status(adopt_run)["status"] == "committed"))
    finally:
        # Selftest temp data contains no engagement material; leave cleanup to
        # TemporaryDirectory semantics would hide fault artifacts, so remove it.
        import shutil
        shutil.rmtree(root, ignore_errors=True)

    failed = [name for name, ok in checks if not ok]
    for name, ok in checks:
        print(f"[completion_transaction selftest] {'PASS' if ok else 'FAIL'} {name}")
    if failed:
        print(json.dumps({"failed": failed}, ensure_ascii=False), file=sys.stderr)
        return 1
    print(f"[completion_transaction selftest] PASS ({len(checks)} checks)")
    return 0


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--selftest", action="store_true")
    sub = parser.add_subparsers(dest="command")
    status_parser = sub.add_parser("status")
    status_parser.add_argument("run")
    adopt_parser = sub.add_parser("adopt-policy")
    adopt_parser.add_argument("run")
    prepare_parser = sub.add_parser("prepare")
    prepare_parser.add_argument("run")
    prepare_parser.add_argument("--mode", choices=("ghost", "normal"), required=True)
    prepare_parser.add_argument("--review-receipt", action="append", default=[],
                                metavar="SLOT=SHA256")
    prepare_parser.add_argument("--review-limitation", action="append", default=[],
                                metavar="SLOT=REASON")
    prepare_parser.add_argument("--cron-disposition",
                                choices=("quiescent", "not_requested"), required=True)
    prepare_parser.add_argument("--warning-disposition", action="append", default=[],
                                metavar="CODE:DISPOSITION:REASON")
    commit_parser = sub.add_parser("commit")
    commit_parser.add_argument("run")
    reopen_parser = sub.add_parser("reopen")
    reopen_parser.add_argument("run")
    reopen_parser.add_argument("--reason", required=True)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    if args.selftest:
        return _selftest()
    try:
        if args.command == "status":
            value = status(args.run)
        elif args.command == "adopt-policy":
            value = adopt_policy(args.run)
        elif args.command == "prepare":
            value = prepare(
                args.run, mode=args.mode,
                review_receipts=args.review_receipt,
                review_limitations=args.review_limitation,
                cron_disposition=args.cron_disposition,
                warning_dispositions=args.warning_disposition,
            )
        elif args.command == "commit":
            value = commit(args.run)
        elif args.command == "reopen":
            value = reopen(args.run, reason=args.reason)
        else:
            _parser().print_help(sys.stderr)
            return 2
    except (CompletionError, contract_schema.ContractSchemaUnavailable) as exc:
        print(str(exc), file=sys.stderr)
        return 1
    if args.command in {"prepare", "commit", "reopen"}:
        print(
            "XUNJI_COMPLETION_"
            + args.command.upper().replace("-", "_")
            + "=" + str(value.get("transaction_id") or "")
        )
    print(json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
