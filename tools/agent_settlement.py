#!/usr/bin/env python3
"""Typed Agent cancellation and stale-review settlement contracts.

This module is deliberately a contract/service library, not a second driver.
``workers.py`` remains the sole assignment writer and exposes the operator-facing
command.  The turn gate imports the same predicates so a cancellation intent or
stale Reviewer decision cannot drift between assignment creation and real Claude
Code ``Agent`` execution.
"""
from __future__ import annotations

import hashlib
import json
import math
import os
import re
import stat
import tempfile
from datetime import datetime
from pathlib import Path

import run_model
import work_plan


CANCELLATION_SCHEMA = "xunji.assignment-cancellation.v2"
LEGACY_CANCELLATION_SCHEMA = "xunji.assignment-cancellation.v1"
CANCELLATION_TRANSACTION_SCHEMA = (
    "xunji.assignment-cancellation-transaction.v2"
)
LEGACY_CANCELLATION_TRANSACTION_SCHEMA = (
    "xunji.assignment-cancellation-transaction.v1"
)
CANCELLATION_STATUS = "cancelled-unlaunched"
TRANSACTION_STATUSES = frozenset({"prepared", "committed"})
_HEX64 = re.compile(r"[0-9a-f]{64}")
_ASSIGNMENT = re.compile(r"A-[A-Za-z0-9._-]+")
_LANE = re.compile(r"L-[A-Za-z0-9._-]+")

CANCELLATION_FIELDS = frozenset({
    "schema", "cancellation_id", "status", "plan_id", "plan_digest",
    "plan_inputs_digest", "observed_inputs_digest", "lane_id", "assignment",
    "assignment_attempt", "role", "front", "effect", "assets", "reason",
    "cancelled_at", "turn_binding", "assignment_row_sha256",
    "delegate_transaction_id", "delegate_receipt_digest", "agent_artifact",
    "context_artifact", "stale_basis", "plan_turn_binding",
    "observed_turn_binding", "receipt_digest",
})
LEGACY_CANCELLATION_FIELDS = frozenset({
    "schema", "cancellation_id", "status", "plan_id", "plan_digest",
    "plan_inputs_digest", "observed_inputs_digest", "lane_id", "assignment",
    "assignment_attempt", "role", "front", "effect", "assets", "reason",
    "cancelled_at", "turn_binding", "assignment_row_sha256",
    "delegate_transaction_id", "delegate_receipt_digest", "agent_artifact",
    "context_artifact", "receipt_digest",
})
TRANSACTION_FIELDS = frozenset({
    "schema", "transaction_id", "status", "plan_id", "plan_digest", "lane_id",
    "assignment", "prepared_at", "committed_at", "previous_assignments_text",
    "previous_assignments_sha256", "next_assignments_text",
    "next_assignments_sha256", "tombstone", "receipt_digest",
})
ARTIFACT_FIELDS = frozenset({"path", "resolved_path", "length", "sha256"})
TURN_BINDING_FIELDS = frozenset({
    "session_id", "prompt_sha256", "contract_updated_at", "transcript_path",
    "transcript_length", "transcript_prefix_sha256",
})
PLAN_TURN_BINDING_FIELDS = frozenset({
    "session_id", "prompt_sha256", "contract_updated_at",
})
STALE_BASES = frozenset({"turn", "inputs", "both"})


class SettlementError(RuntimeError):
    """Stable fail-closed error for cancellation/settlement state."""


def _json_bytes(value: object) -> bytes:
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


def _digest_without(value: dict, field: str) -> str:
    return hashlib.sha256(_json_bytes({
        key: item for key, item in value.items() if key != field
    })).hexdigest()


def cancellation_transaction_path(run_dir: str | Path) -> Path:
    return Path(run_dir).resolve() / "state" / "assignment_cancellation_transaction.json"


def cancellation_archive_dir(run_dir: str | Path) -> Path:
    return Path(run_dir).resolve() / "state" / "assignment_cancellations"


def cancellation_archive_path(run_dir: str | Path, receipt_digest: str) -> Path:
    if not _HEX64.fullmatch(str(receipt_digest or "")):
        raise SettlementError("ASSIGNMENT_CANCELLATION_RECEIPT_DIGEST_INVALID")
    return cancellation_archive_dir(run_dir) / f"{receipt_digest}.json"


def _fsync_directory(path: Path) -> None:
    flags = os.O_RDONLY
    if hasattr(os, "O_DIRECTORY"):
        flags |= os.O_DIRECTORY
    descriptor = os.open(path, flags)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def durable_atomic_text(path: Path, text: str) -> None:
    """Publish one UTF-8 file across file and directory durability barriers."""
    parent = path.parent
    if parent.exists() and (parent.is_symlink() or not parent.is_dir()):
        raise SettlementError("ASSIGNMENT_CANCELLATION_PARENT_INVALID")
    temporary: str | None = None
    try:
        parent.mkdir(parents=True, exist_ok=True)
        # This unconditional barrier persists a newly-created parent entry and
        # also repairs a retry after mkdir succeeded but its barrier failed.
        _fsync_directory(parent.parent)
        # Keep active temp files outside immutable archive directories.  A
        # read-only archive scan must never delete or mistake a live writer temp
        # for corrupt immutable state.  The parent is on the same filesystem,
        # so ``replace`` remains atomic.
        temporary_parent = parent.parent
        descriptor, temporary = tempfile.mkstemp(
            prefix="." + path.name + ".", suffix=".tmp", dir=temporary_parent,
        )
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(temporary, 0o600)
        os.replace(temporary, path)
        _fsync_directory(parent)
    except Exception as exc:
        raise SettlementError(
            f"ASSIGNMENT_CANCELLATION_DURABILITY_FAILED:{type(exc).__name__}"
        ) from exc
    finally:
        if temporary is not None:
            try:
                os.unlink(temporary)
            except FileNotFoundError:
                pass


def durable_unlink_artifact(
    run_dir: str | Path, artifact: dict, *, directory: str, pattern: str,
) -> None:
    """Remove only the exact generated artifact frozen by a cancellation."""
    run = Path(run_dir).resolve()
    validated = _validate_artifact(artifact, directory=directory, pattern=pattern)
    relative = Path(validated["path"])
    path = run / relative
    expected_parent = run / directory
    if path.parent != expected_parent:
        raise SettlementError("ASSIGNMENT_CANCELLATION_ARTIFACT_PATH_INVALID")
    if str(path.resolve(strict=False)) != validated["resolved_path"]:
        raise SettlementError("ASSIGNMENT_CANCELLATION_ARTIFACT_IDENTITY_CHANGED")
    try:
        metadata = path.lstat()
    except FileNotFoundError:
        if expected_parent.is_symlink() or not expected_parent.is_dir():
            raise SettlementError("ASSIGNMENT_CANCELLATION_ARTIFACT_PARENT_INVALID")
        # The prior unlink may have succeeded while its parent barrier failed.
        # Repeating the barrier is part of exact forward recovery.
        _fsync_directory(expected_parent)
        return
    if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISREG(metadata.st_mode):
        raise SettlementError("ASSIGNMENT_CANCELLATION_ARTIFACT_TYPE_CHANGED")
    payload = path.read_bytes()
    if len(payload) != validated["length"] \
            or hashlib.sha256(payload).hexdigest() != validated["sha256"]:
        raise SettlementError("ASSIGNMENT_CANCELLATION_ARTIFACT_CONTENT_CHANGED")
    path.unlink()
    _fsync_directory(path.parent)


def freeze_artifact(
    run_dir: str | Path, path: Path, *, directory: str, pattern: str,
) -> dict:
    """Freeze lexical, resolved and content identity for one generated file."""
    run = Path(run_dir).resolve()
    expected_parent = run / directory
    if path.parent != expected_parent or not re.fullmatch(pattern, path.name):
        raise SettlementError("ASSIGNMENT_CANCELLATION_ARTIFACT_PATH_INVALID")
    try:
        metadata = path.lstat()
    except FileNotFoundError as exc:
        raise SettlementError("ASSIGNMENT_CANCELLATION_ARTIFACT_MISSING") from exc
    if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISREG(metadata.st_mode):
        raise SettlementError("ASSIGNMENT_CANCELLATION_ARTIFACT_TYPE_INVALID")
    resolved = path.resolve(strict=True)
    if resolved.parent != expected_parent.resolve(strict=True):
        raise SettlementError("ASSIGNMENT_CANCELLATION_ARTIFACT_ESCAPES_RUN")
    payload = path.read_bytes()
    return {
        "path": path.relative_to(run).as_posix(),
        "resolved_path": str(resolved),
        "length": len(payload),
        "sha256": hashlib.sha256(payload).hexdigest(),
    }


def _validate_artifact(value: object, *, directory: str = "", pattern: str = "") -> dict:
    if not isinstance(value, dict) or set(value) != ARTIFACT_FIELDS:
        raise SettlementError("ASSIGNMENT_CANCELLATION_ARTIFACT_SHAPE_INVALID")
    relative = value.get("path")
    resolved = value.get("resolved_path")
    length = value.get("length")
    digest = value.get("sha256")
    if not isinstance(relative, str) or not relative \
            or Path(relative).is_absolute() or ".." in Path(relative).parts:
        raise SettlementError("ASSIGNMENT_CANCELLATION_ARTIFACT_PATH_INVALID")
    if directory:
        parts = Path(relative).parts
        if len(parts) != 2 or parts[0] != directory \
                or not re.fullmatch(pattern, parts[1]):
            raise SettlementError("ASSIGNMENT_CANCELLATION_ARTIFACT_PATH_INVALID")
    if not isinstance(resolved, str) or not Path(resolved).is_absolute():
        raise SettlementError("ASSIGNMENT_CANCELLATION_ARTIFACT_RESOLVED_INVALID")
    if isinstance(length, bool) or not isinstance(length, int) or length < 0:
        raise SettlementError("ASSIGNMENT_CANCELLATION_ARTIFACT_LENGTH_INVALID")
    if not _HEX64.fullmatch(str(digest or "")):
        raise SettlementError("ASSIGNMENT_CANCELLATION_ARTIFACT_DIGEST_INVALID")
    return value


def _validate_plan_turn_binding(value: object, *, label: str) -> dict:
    if not isinstance(value, dict) or set(value) != PLAN_TURN_BINDING_FIELDS \
            or not isinstance(value.get("session_id"), str) \
            or not value.get("session_id") \
            or not _HEX64.fullmatch(str(value.get("prompt_sha256") or "")) \
            or isinstance(value.get("contract_updated_at"), bool) \
            or not isinstance(value.get("contract_updated_at"), (int, float)) \
            or not math.isfinite(float(value.get("contract_updated_at"))) \
            or value.get("contract_updated_at") <= 0:
        raise SettlementError(
            f"ASSIGNMENT_CANCELLATION_{label}_TURN_BINDING_INVALID")
    return value


def validate_cancellation(value: object) -> dict:
    if not isinstance(value, dict):
        raise SettlementError("ASSIGNMENT_CANCELLATION_SHAPE_INVALID")
    schema = value.get("schema")
    legacy = schema == LEGACY_CANCELLATION_SCHEMA
    expected_fields = LEGACY_CANCELLATION_FIELDS if legacy \
        else CANCELLATION_FIELDS
    if set(value) != expected_fields:
        raise SettlementError("ASSIGNMENT_CANCELLATION_SHAPE_INVALID")
    if schema not in {CANCELLATION_SCHEMA, LEGACY_CANCELLATION_SCHEMA} \
            or value.get("status") != CANCELLATION_STATUS:
        raise SettlementError("ASSIGNMENT_CANCELLATION_SCHEMA_INVALID")
    for field in (
        "cancellation_id", "plan_digest", "plan_inputs_digest",
        "observed_inputs_digest", "assignment_row_sha256",
        "delegate_transaction_id", "delegate_receipt_digest", "receipt_digest",
    ):
        if not _HEX64.fullmatch(str(value.get(field) or "")):
            raise SettlementError(f"ASSIGNMENT_CANCELLATION_{field.upper()}_INVALID")
    if not isinstance(value.get("plan_id"), str) or not value["plan_id"]:
        raise SettlementError("ASSIGNMENT_CANCELLATION_PLAN_ID_INVALID")
    if not _LANE.fullmatch(str(value.get("lane_id") or "")) \
            or not _ASSIGNMENT.fullmatch(str(value.get("assignment") or "")):
        raise SettlementError("ASSIGNMENT_CANCELLATION_BINDING_INVALID")
    attempt = value.get("assignment_attempt")
    if isinstance(attempt, bool) or not isinstance(attempt, int) or attempt < 1:
        raise SettlementError("ASSIGNMENT_CANCELLATION_ATTEMPT_INVALID")
    for field in ("role", "front", "effect", "reason", "cancelled_at"):
        if not isinstance(value.get(field), str) or not value[field].strip():
            raise SettlementError(f"ASSIGNMENT_CANCELLATION_{field.upper()}_INVALID")
    if len(value["reason"]) > 4096:
        raise SettlementError("ASSIGNMENT_CANCELLATION_REASON_INVALID")
    assets = value.get("assets")
    if not isinstance(assets, list) or any(
        not isinstance(item, str) or not item for item in assets
    ) or len(set(assets)) != len(assets):
        raise SettlementError("ASSIGNMENT_CANCELLATION_ASSETS_INVALID")
    binding = value.get("turn_binding")
    if not isinstance(binding, dict) or set(binding) != TURN_BINDING_FIELDS \
            or not isinstance(binding.get("session_id"), str) \
            or not binding.get("session_id") \
            or not _HEX64.fullmatch(str(binding.get("prompt_sha256") or "")) \
            or isinstance(binding.get("contract_updated_at"), bool) \
            or not isinstance(binding.get("contract_updated_at"), (int, float)) \
            or not math.isfinite(float(binding.get("contract_updated_at"))) \
            or binding.get("contract_updated_at") <= 0 \
            or not isinstance(binding.get("transcript_path"), str) \
            or not Path(binding.get("transcript_path") or "").is_absolute() \
            or isinstance(binding.get("transcript_length"), bool) \
            or not isinstance(binding.get("transcript_length"), int) \
            or binding.get("transcript_length") < 0 \
            or not _HEX64.fullmatch(str(
                binding.get("transcript_prefix_sha256") or "")):
        raise SettlementError("ASSIGNMENT_CANCELLATION_TURN_BINDING_INVALID")
    try:
        cancelled_time = datetime.fromisoformat(
            value["cancelled_at"].replace("Z", "+00:00"))
    except ValueError as exc:
        raise SettlementError("ASSIGNMENT_CANCELLATION_CANCELLED_AT_INVALID") from exc
    if cancelled_time.tzinfo is None or cancelled_time.utcoffset() is None:
        raise SettlementError("ASSIGNMENT_CANCELLATION_CANCELLED_AT_INVALID")
    _validate_artifact(
        value.get("agent_artifact"), directory="agents",
        pattern=r"A-[A-Za-z0-9._-]+\.md",
    )
    _validate_artifact(
        value.get("context_artifact"), directory="context",
        pattern=r"[^/\\]+\.md",
    )
    if value["receipt_digest"] != _digest_without(value, "receipt_digest"):
        raise SettlementError("ASSIGNMENT_CANCELLATION_RECEIPT_DIGEST_MISMATCH")
    identity = {
        "plan_digest": value["plan_digest"],
        "lane_id": value["lane_id"],
        "assignment": value["assignment"],
        "assignment_attempt": value["assignment_attempt"],
        "assignment_row_sha256": value["assignment_row_sha256"],
        "delegate_transaction_id": value["delegate_transaction_id"],
        "observed_inputs_digest": value["observed_inputs_digest"],
        "cancelled_at": value["cancelled_at"],
    }
    if not legacy:
        stale_basis = str(value.get("stale_basis") or "")
        if stale_basis not in STALE_BASES:
            raise SettlementError(
                "ASSIGNMENT_CANCELLATION_STALE_BASIS_INVALID")
        plan_binding = _validate_plan_turn_binding(
            value.get("plan_turn_binding"), label="PLAN")
        observed_binding = _validate_plan_turn_binding(
            value.get("observed_turn_binding"), label="OBSERVED")
        turn_changed = plan_binding != observed_binding
        inputs_changed = (
            value["plan_inputs_digest"] != value["observed_inputs_digest"])
        expected_basis = (
            "both" if turn_changed and inputs_changed else
            "turn" if turn_changed else
            "inputs" if inputs_changed else ""
        )
        if stale_basis != expected_basis:
            raise SettlementError(
                "ASSIGNMENT_CANCELLATION_STALE_BASIS_MISMATCH")
        if any(
            value["turn_binding"].get(field) != observed_binding.get(field)
            for field in PLAN_TURN_BINDING_FIELDS
        ):
            raise SettlementError(
                "ASSIGNMENT_CANCELLATION_OBSERVED_TURN_BINDING_DIVERGED")
        identity.update({
            "stale_basis": stale_basis,
            "plan_turn_binding": plan_binding,
            "observed_turn_binding": observed_binding,
        })
    expected_id = hashlib.sha256(_json_bytes(identity)).hexdigest()
    if value["cancellation_id"] != expected_id:
        raise SettlementError("ASSIGNMENT_CANCELLATION_ID_MISMATCH")
    return value


def save_cancellation(value: dict) -> dict:
    saved = dict(value)
    saved["receipt_digest"] = _digest_without(saved, "receipt_digest")
    return validate_cancellation(saved)


def build_cancellation(**values: object) -> dict:
    """Build one exact immutable cancellation receipt from frozen inputs."""
    saved = {"schema": CANCELLATION_SCHEMA, "status": CANCELLATION_STATUS, **values}
    saved["cancellation_id"] = hashlib.sha256(_json_bytes({
        "plan_digest": saved.get("plan_digest"),
        "lane_id": saved.get("lane_id"),
        "assignment": saved.get("assignment"),
        "assignment_attempt": saved.get("assignment_attempt"),
        "assignment_row_sha256": saved.get("assignment_row_sha256"),
        "delegate_transaction_id": saved.get("delegate_transaction_id"),
        "observed_inputs_digest": saved.get("observed_inputs_digest"),
        "cancelled_at": saved.get("cancelled_at"),
        "stale_basis": saved.get("stale_basis"),
        "plan_turn_binding": saved.get("plan_turn_binding"),
        "observed_turn_binding": saved.get("observed_turn_binding"),
    })).hexdigest()
    saved["receipt_digest"] = ""
    return save_cancellation(saved)


def validate_transaction(value: object) -> dict:
    if not isinstance(value, dict) or set(value) != TRANSACTION_FIELDS:
        raise SettlementError("ASSIGNMENT_CANCELLATION_TRANSACTION_SHAPE_INVALID")
    transaction_schema = value.get("schema")
    if transaction_schema not in {
            CANCELLATION_TRANSACTION_SCHEMA,
            LEGACY_CANCELLATION_TRANSACTION_SCHEMA,
    } \
            or value.get("status") not in TRANSACTION_STATUSES:
        raise SettlementError("ASSIGNMENT_CANCELLATION_TRANSACTION_SCHEMA_INVALID")
    for field in ("transaction_id", "plan_digest", "receipt_digest"):
        if not _HEX64.fullmatch(str(value.get(field) or "")):
            raise SettlementError(
                f"ASSIGNMENT_CANCELLATION_TRANSACTION_{field.upper()}_INVALID")
    if not isinstance(value.get("plan_id"), str) or not value["plan_id"] \
            or not _LANE.fullmatch(str(value.get("lane_id") or "")) \
            or not _ASSIGNMENT.fullmatch(str(value.get("assignment") or "")):
        raise SettlementError("ASSIGNMENT_CANCELLATION_TRANSACTION_BINDING_INVALID")
    if not isinstance(value.get("prepared_at"), str) or not value["prepared_at"]:
        raise SettlementError("ASSIGNMENT_CANCELLATION_TRANSACTION_TIME_INVALID")
    if value["status"] == "prepared" and value.get("committed_at") is not None:
        raise SettlementError("ASSIGNMENT_CANCELLATION_TRANSACTION_TERMINAL_INVALID")
    if value["status"] == "committed" \
            and (not isinstance(value.get("committed_at"), str)
                 or not value["committed_at"]):
        raise SettlementError("ASSIGNMENT_CANCELLATION_TRANSACTION_TERMINAL_INVALID")
    for text_field, digest_field in (
        ("previous_assignments_text", "previous_assignments_sha256"),
        ("next_assignments_text", "next_assignments_sha256"),
    ):
        text = value.get(text_field)
        digest = value.get(digest_field)
        if not isinstance(text, str) or not _HEX64.fullmatch(str(digest or "")) \
                or hashlib.sha256(text.encode("utf-8")).hexdigest() != digest:
            raise SettlementError(
                "ASSIGNMENT_CANCELLATION_TRANSACTION_LEDGER_SNAPSHOT_INVALID")
    tombstone = validate_cancellation(value.get("tombstone"))
    expected_transaction_schema = (
        LEGACY_CANCELLATION_TRANSACTION_SCHEMA
        if tombstone.get("schema") == LEGACY_CANCELLATION_SCHEMA
        else CANCELLATION_TRANSACTION_SCHEMA
    )
    if transaction_schema != expected_transaction_schema:
        raise SettlementError(
            "ASSIGNMENT_CANCELLATION_TRANSACTION_VERSION_DIVERGED")
    if tombstone["plan_id"] != value["plan_id"] \
            or tombstone["plan_digest"] != value["plan_digest"] \
            or tombstone["lane_id"] != value["lane_id"] \
            or tombstone["assignment"] != value["assignment"]:
        raise SettlementError("ASSIGNMENT_CANCELLATION_TRANSACTION_TOMBSTONE_DIVERGED")
    expected_id = hashlib.sha256(_json_bytes({
        "tombstone": tombstone["receipt_digest"],
        "previous_assignments_sha256": value["previous_assignments_sha256"],
        "next_assignments_sha256": value["next_assignments_sha256"],
        "prepared_at": value["prepared_at"],
    })).hexdigest()
    if value["transaction_id"] != expected_id \
            or value["receipt_digest"] != _digest_without(value, "receipt_digest"):
        raise SettlementError("ASSIGNMENT_CANCELLATION_TRANSACTION_DIGEST_MISMATCH")
    return value


def save_transaction(run_dir: str | Path, value: dict) -> dict:
    saved = dict(value)
    saved["receipt_digest"] = _digest_without(saved, "receipt_digest")
    validated = validate_transaction(saved)
    durable_atomic_text(
        cancellation_transaction_path(run_dir),
        json.dumps(
            validated, ensure_ascii=False, indent=2, sort_keys=True,
            allow_nan=False) + "\n",
    )
    return validated


def build_transaction(
    *, tombstone: dict, previous_assignments_text: str,
    next_assignments_text: str, prepared_at: str,
) -> dict:
    receipt = validate_cancellation(tombstone)
    previous_digest = hashlib.sha256(
        previous_assignments_text.encode("utf-8")).hexdigest()
    next_digest = hashlib.sha256(next_assignments_text.encode("utf-8")).hexdigest()
    transaction_id = hashlib.sha256(_json_bytes({
        "tombstone": receipt["receipt_digest"],
        "previous_assignments_sha256": previous_digest,
        "next_assignments_sha256": next_digest,
        "prepared_at": prepared_at,
    })).hexdigest()
    value = {
        "schema": CANCELLATION_TRANSACTION_SCHEMA,
        "transaction_id": transaction_id,
        "status": "prepared",
        "plan_id": receipt["plan_id"],
        "plan_digest": receipt["plan_digest"],
        "lane_id": receipt["lane_id"],
        "assignment": receipt["assignment"],
        "prepared_at": prepared_at,
        "committed_at": None,
        "previous_assignments_text": previous_assignments_text,
        "previous_assignments_sha256": previous_digest,
        "next_assignments_text": next_assignments_text,
        "next_assignments_sha256": next_digest,
        "tombstone": receipt,
        "receipt_digest": "",
    }
    value["receipt_digest"] = _digest_without(value, "receipt_digest")
    return validate_transaction(value)


def load_transaction(run_dir: str | Path) -> dict | None:
    path = cancellation_transaction_path(run_dir)
    if not path.exists():
        return None
    if path.is_symlink() or not path.is_file():
        raise SettlementError("ASSIGNMENT_CANCELLATION_TRANSACTION_PATH_INVALID")
    try:
        value = json.loads(path.read_text(encoding="utf-8", errors="strict"))
    except Exception as exc:
        raise SettlementError("ASSIGNMENT_CANCELLATION_TRANSACTION_UNREADABLE") from exc
    return validate_transaction(value)


def archive_cancellation(run_dir: str | Path, value: dict) -> Path:
    receipt = validate_cancellation(value)
    path = cancellation_archive_path(run_dir, receipt["receipt_digest"])
    encoded = json.dumps(
        receipt, ensure_ascii=False, indent=2, sort_keys=True,
        allow_nan=False) + "\n"
    if path.exists():
        if path.is_symlink() or not path.is_file() \
                or path.read_text(encoding="utf-8", errors="strict") != encoded:
            raise SettlementError("ASSIGNMENT_CANCELLATION_ARCHIVE_COLLISION")
        _fsync_directory(path.parent)
        return path
    durable_atomic_text(path, encoded)
    return path


def cancellation_receipts(run_dir: str | Path) -> list[dict]:
    directory = cancellation_archive_dir(run_dir)
    if not directory.exists():
        return []
    if directory.is_symlink() or not directory.is_dir():
        raise SettlementError("ASSIGNMENT_CANCELLATION_ARCHIVE_PATH_INVALID")
    receipts: list[dict] = []
    for path in sorted(directory.iterdir()):
        if path.is_symlink() or not path.is_file() \
                or not re.fullmatch(r"[0-9a-f]{64}\.json", path.name):
            raise SettlementError("ASSIGNMENT_CANCELLATION_ARCHIVE_ENTRY_INVALID")
        try:
            receipt = validate_cancellation(json.loads(path.read_text(
                encoding="utf-8", errors="strict")))
        except SettlementError:
            raise
        except Exception as exc:
            raise SettlementError("ASSIGNMENT_CANCELLATION_ARCHIVE_UNREADABLE") from exc
        if path.stem != receipt["receipt_digest"]:
            raise SettlementError("ASSIGNMENT_CANCELLATION_ARCHIVE_NAME_MISMATCH")
        receipts.append(receipt)
    return receipts


def cancellation_barrier(
    run_dir: str | Path, *, plan_digest: str = "", assignment: str = "",
) -> bool:
    """True when a prepared intent or immutable tombstone blocks launch/reuse."""
    candidates = cancellation_receipts(run_dir)
    transaction = load_transaction(run_dir)
    if transaction is not None:
        candidates.append(transaction["tombstone"])
    return any(
        (not plan_digest or item["plan_digest"] == plan_digest)
        and (not assignment or item["assignment"] == assignment)
        for item in candidates
    )


def cancelled_assignment_ids(run_dir: str | Path) -> set[str]:
    values = {item["assignment"] for item in cancellation_receipts(run_dir)}
    transaction = load_transaction(run_dir)
    if transaction is not None:
        values.add(transaction["assignment"])
    return values


def require_runtime_event_not_cancelled(
    run_dir: str | Path, runtime_record: dict,
) -> None:
    """Reject a new Agent lifecycle fact after cancellation intent is durable.

    ``runtime_receipts.append_hook_event`` calls this before mutable-ledger
    validation for a raw new delivery, then repeats it after resolving the
    frozen lifecycle binding.  The caller excludes immutable journal replay
    identities.  The assignment id is globally tombstoned: a conflicting
    lane/plan is attempted identity reuse, not an unrelated event that may
    cross the barrier.
    """
    if not isinstance(runtime_record, dict):
        raise SettlementError("ASSIGNMENT_CANCELLATION_RUNTIME_EVENT_INVALID")
    hook = str(runtime_record.get("hook_event_name") or "")
    tool = str(runtime_record.get("tool_name") or "")
    if not (
        hook in {"SubagentStart", "SubagentStop"}
        or tool == "Agent" and hook in {"PostToolUse", "PostToolUseFailure"}
    ):
        return

    # Parse every cancellation surface before deciding that this event is
    # unrelated.  A malformed prepared transaction cannot safely identify the
    # assignment it intended to fence and therefore fails closed globally.
    candidates = cancellation_receipts(run_dir)
    transaction = load_transaction(run_dir)
    if transaction is not None:
        candidates.append(transaction["tombstone"])
    assignment = str(runtime_record.get("assignment") or "")
    if not assignment:
        return
    matching = [
        item for item in candidates if item["assignment"] == assignment
    ]
    if not matching:
        return
    event_plan = str(runtime_record.get("assignment_plan_digest") or "")
    event_lane = str(runtime_record.get("assignment_lane") or "")
    for tombstone in matching:
        if event_plan and event_plan != tombstone["plan_digest"]:
            raise SettlementError(
                "ASSIGNMENT_CANCELLATION_RUNTIME_IDENTITY_REUSE")
        if event_lane and event_lane != tombstone["lane_id"]:
            raise SettlementError(
                "ASSIGNMENT_CANCELLATION_RUNTIME_IDENTITY_REUSE")
    raise SettlementError(
        f"ASSIGNMENT_CANCELLATION_RUNTIME_BARRIER:{assignment}")


def stale_settlement_reviewer_ready(
    run_dir: str | Path, plan: dict, lane: dict,
) -> bool:
    """Shared unique-Reviewer predicate for workers and the real turn gate."""
    if str(lane.get("role") or "").strip().lower() not in {
        "review", "reviewer", "independent-review", "independent-review-agent",
    } or str(lane.get("effect") or "") != "local_verify":
        return False
    dependencies = [str(item) for item in lane.get("dependencies", [])]
    if len(dependencies) != 1:
        return False
    dependency_id = dependencies[0]
    try:
        dependency_lane = work_plan.lane_by_id(plan, dependency_id)
    except Exception:
        return False
    if str(dependency_lane.get("role") or "").strip().lower() in {
        "review", "reviewer", "independent-review", "independent-review-agent",
    }:
        return False
    reviewers = [
        item for item in plan.get("lanes", []) if isinstance(item, dict)
        and str(item.get("role") or "").strip().lower() in {
            "review", "reviewer", "independent-review", "independent-review-agent",
        }
        and [str(value) for value in item.get("dependencies", [])]
            == [dependency_id]
    ]
    if len(reviewers) != 1 or reviewers[0].get("id") != lane.get("id"):
        return False
    try:
        projection = run_model.plan_cycle_projection(run_dir, plan=plan)
    except Exception:
        return False
    dependency_states = [
        item for item in projection.get("lane_states", [])
        if isinstance(item, dict) and item.get("lane_id") == dependency_id
    ]
    return bool(
        projection.get("plan_digest") == plan.get("plan_digest")
        and len(dependency_states) == 1
        and dependency_states[0].get("runtime_state") in {"returned", "failed"}
        and work_plan.lane_dependencies_satisfied(run_dir, plan, lane)
    )
