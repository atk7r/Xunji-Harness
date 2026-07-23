#!/usr/bin/env python3
"""Atomic run preparation and active-pointer commit primitives.

The transaction boundary is deliberately local and deterministic.  Adapters
resolve and validate source material before calling :func:`create_and_activate`;
the transaction then prepares a hidden same-filesystem directory, freezes a
source manifest and receipt, atomically renames the complete run, and changes the
active pointer with compare-and-swap semantics.

This module is the only active-pointer writer.  setup_run, loop_bootstrap,
xunji_statusline, recovery paths, and future CCB adapters must call the same CAS
primitive instead of writing ``.claude/xunji_active_run`` themselves.
"""
from __future__ import annotations

import argparse
import ast
import contextlib
import hashlib
import json
import os
import re
import shutil
import stat
import tempfile
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Iterator, Optional, Union

import setup_source

ROOT = Path(__file__).resolve().parents[1]
RUNS_ROOT = ROOT / "runs"
ACTIVE_POINTER = ROOT / ".claude" / "xunji_active_run"
STAGING_NAME = ".xunji_staging"
SETUP_LOCK_NAME = ".xunji_setup.lock"
ACTIVATION_LOCK_NAME = ".xunji_activation.lock"
SOURCE_SCHEMA = setup_source.SCHEMA
RECEIPT_SCHEMA = "xunji.setup_transaction.v1"
TURN_CONTRACT_SCHEMA = "xunji.turn_contract.v1"
SESSION_SELECTION_SCHEMA = "xunji.session_selection.v2"
TRANSITION_EFFECT_SCHEMA = "xunji.lifecycle-effect.v1"
EFFECT_PROFILE_SCHEMA = "xunji.lifecycle-effect-profile.v1"
ACTIVATION_ATTEMPT_SCHEMA = "xunji.setup-activation-attempt.v1"
OP_SETUP_RUN_CREATE = "setup_run.create"
OP_LOOP_BOOTSTRAP_CREATE = "loop_bootstrap.create"
OP_LOOP_BOOTSTRAP_RESUME = "loop_bootstrap.resume"
OP_STATUSLINE_SET_ACTIVE = "xunji_statusline.set-active"
OP_TRANSACTION_CREATE = "setup_transaction.create"
OP_TRANSACTION_ACTIVATE = "setup_transaction.activate"
CREATE_EFFECT_OPERATIONS = frozenset({
    OP_SETUP_RUN_CREATE,
    OP_LOOP_BOOTSTRAP_CREATE,
    OP_TRANSACTION_CREATE,
})
ACTIVATE_EFFECT_OPERATIONS = frozenset({
    OP_LOOP_BOOTSTRAP_RESUME,
    OP_STATUSLINE_SET_ACTIVE,
    OP_TRANSACTION_ACTIVATE,
})
_OPERATION_OMITTED = object()
EFFECT_SOURCE_TYPES = frozenset({
    "auto", "file", "url", "recon-json", "json", "markdown",
})
SOURCE_REL = Path("state/setup_source.json")
RECEIPT_REL = Path("state/setup_transaction.json")
DEFAULT_REQUIRED = (
    "target.md",
    "surface.md",
    "frontier.md",
    "hypotheses.md",
    "evidence.md",
    "decisions.md",
    "review.md",
    "report.md",
    "retrospective.md",
    "classify/coverage.json",
    "state/asset_ledger.json",
    "state/session_state.json",
    "state/loop_state.json",
    "state/progress_ledger.json",
    "state/controller.shadow.json",
    str(SOURCE_REL),
    str(RECEIPT_REL),
    str(setup_source.NORMALIZED_REL),
    str(setup_source.VALIDATOR_REL),
)


@dataclass(frozen=True)
class PointerSnapshot:
    exists: bool
    raw: str
    sha256: str


@dataclass(frozen=True)
class TransactionResult:
    run_dir: Path
    transaction_id: str
    source_hash: str
    status: str
    recovered: bool = False


class SetupTransactionError(RuntimeError):
    """Structured fail-closed setup error used by every lifecycle adapter."""

    def __init__(
        self,
        code: str,
        message: str,
        *,
        run_dir: Path | None = None,
        transaction_id: str = "",
    ) -> None:
        super().__init__(message)
        self.code = code
        self.run_dir = run_dir
        self.transaction_id = transaction_id


class _DirectoryDurabilityError(OSError):
    """Internal marker for a required parent-directory durability failure."""


FaultInjector = Callable[[str], None]
BuildRun = Callable[[Path, Optional[FaultInjector]], None]
SourceValidator = Callable[[], None]
OwnedClearCallback = Callable[[Path, bytes, dict], Union[dict, bytes]]
ResumeBarrierCallback = Callable[[Path, dict], Union[dict, bytes]]


def _sha256(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _semantic_json_sha256(raw: str | bytes | None) -> str:
    if raw is None or raw == "" or raw == b"":
        return ""
    try:
        value = json.loads(
            raw.decode("utf-8", "strict") if isinstance(raw, bytes) else str(raw)
        )
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise ValueError("candidate JSON is invalid") from exc
    return _sha256(json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
    ).encode("utf-8"))


def lifecycle_effect_profile(
    operation: str,
    target_run: str,
    *,
    source_type: str = "",
    classify: bool = False,
    ai_mode: str = "off",
    provider: str = "",
    model: str = "",
    candidate_json: str | bytes | None = None,
) -> dict:
    """Build a redacted, closed adapter/options profile for one lifecycle effect."""
    normalized_operation = str(operation or "")
    target = str(target_run or "")
    if normalized_operation not in CREATE_EFFECT_OPERATIONS | ACTIVATE_EFFECT_OPERATIONS \
            or not re.fullmatch(r"[A-Za-z0-9_-]+", target):
        raise ValueError("invalid lifecycle operation/target")
    is_create = normalized_operation in CREATE_EFFECT_OPERATIONS
    normalized_source_type = str(source_type or "").strip().lower()
    normalized_ai = str(ai_mode or "off").strip().lower()
    normalized_provider = str(provider or "").strip()
    normalized_model = str(model or "").strip()
    if not isinstance(classify, bool):
        raise ValueError("lifecycle classify option must be boolean")
    if is_create:
        if normalized_source_type not in EFFECT_SOURCE_TYPES:
            raise ValueError("create lifecycle source type is invalid")
        if normalized_ai not in {"off", "external"}:
            raise ValueError("create lifecycle AI mode is invalid")
        if classify and normalized_operation != OP_SETUP_RUN_CREATE:
            raise ValueError("classify is only valid for setup_run create")
        if normalized_ai == "external":
            if normalized_operation != OP_LOOP_BOOTSTRAP_CREATE \
                    or not normalized_provider or not normalized_model \
                    or candidate_json in {None, "", b""}:
                raise ValueError("external create options are incomplete")
        elif normalized_provider or normalized_model or candidate_json not in {None, "", b""}:
            raise ValueError("AI-off create cannot carry external options")
    elif normalized_source_type or classify or normalized_ai != "off" \
            or normalized_provider or normalized_model \
            or candidate_json not in {None, "", b""}:
        raise ValueError("activate lifecycle profile has unexpected create options")
    for value in (normalized_provider, normalized_model):
        if value and re.search(r"[\x00-\x1f\x7f]", value):
            raise ValueError("AI identity contains control characters")
    candidate_sha = _semantic_json_sha256(candidate_json)
    profile = {
        "schema": EFFECT_PROFILE_SCHEMA,
        "operation": normalized_operation,
        "source_type": normalized_source_type,
        "classify": classify,
        "ai_mode": normalized_ai,
        "provider_sha256": _sha256(normalized_provider.encode("utf-8"))
        if normalized_provider else "",
        "model_sha256": _sha256(normalized_model.encode("utf-8"))
        if normalized_model else "",
        "candidate_sha256": candidate_sha,
    }
    profile["options_sha256"] = _sha256(json.dumps(
        profile, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
    ).encode("utf-8"))
    return profile


def validate_lifecycle_effect_profile(
    value: dict,
    *,
    expected_kind: str = "",
) -> dict:
    if not isinstance(value, dict):
        raise ValueError("lifecycle effect profile must be an object")
    keys = {
        "schema", "operation", "source_type", "classify", "ai_mode",
        "provider_sha256", "model_sha256", "candidate_sha256",
        "options_sha256",
    }
    if set(value) != keys or value.get("schema") != EFFECT_PROFILE_SCHEMA:
        raise ValueError("lifecycle effect profile schema/keys are invalid")
    operation = str(value.get("operation") or "")
    kind = "create" if operation in CREATE_EFFECT_OPERATIONS else (
        "activate" if operation in ACTIVATE_EFFECT_OPERATIONS else ""
    )
    if not kind or (expected_kind and kind != expected_kind):
        raise ValueError("lifecycle effect profile operation/kind mismatch")
    source_type = str(value.get("source_type") or "")
    ai_mode = str(value.get("ai_mode") or "")
    classify = value.get("classify")
    if not isinstance(classify, bool):
        raise ValueError("lifecycle effect profile classify is invalid")
    digests = (
        str(value.get("provider_sha256") or ""),
        str(value.get("model_sha256") or ""),
        str(value.get("candidate_sha256") or ""),
    )
    if any(item and not re.fullmatch(r"[0-9a-f]{64}", item) for item in digests):
        raise ValueError("lifecycle effect profile option digest is invalid")
    if kind == "create":
        if source_type not in EFFECT_SOURCE_TYPES or ai_mode not in {"off", "external"}:
            raise ValueError("create lifecycle effect profile options are invalid")
        if classify and operation != OP_SETUP_RUN_CREATE:
            raise ValueError("classify lifecycle effect operation is invalid")
        if ai_mode == "external":
            if operation != OP_LOOP_BOOTSTRAP_CREATE or not all(digests):
                raise ValueError("external lifecycle effect digests are incomplete")
        elif any(digests):
            raise ValueError("AI-off lifecycle effect carries external digests")
    elif source_type or classify or ai_mode != "off" or any(digests):
        raise ValueError("activate lifecycle effect carries create options")
    body = {key: value[key] for key in keys if key != "options_sha256"}
    expected_options = _sha256(json.dumps(
        body, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
    ).encode("utf-8"))
    if value.get("options_sha256") != expected_options:
        raise ValueError("lifecycle effect profile option digest mismatch")
    return dict(value)


def transition_effect(
    kind: str,
    target_run: str,
    *,
    source_reference: str = "",
    profile: dict,
) -> dict:
    """Build the canonical effect identity shared by hook and commit owner.

    Raw source references never enter claims.  A create effect is bound to the
    exact canonical manifest reference; an activation effect is bound to the
    exact target run name.
    """
    normalized_kind = str(kind or "")
    target = str(target_run or "")
    if normalized_kind not in {"create", "activate"} \
            or not re.fullmatch(r"[A-Za-z0-9_-]+", target):
        raise ValueError("invalid lifecycle effect kind/target")
    profile = validate_lifecycle_effect_profile(
        profile, expected_kind=normalized_kind)
    reference = str(source_reference or "") if normalized_kind == "create" else target
    if not reference:
        raise ValueError("create lifecycle effect requires a source reference")
    body = {
        "schema": TRANSITION_EFFECT_SCHEMA,
        "kind": normalized_kind,
        "target_run": target,
        "input_sha256": _sha256(reference.encode("utf-8", "replace")),
        "operation": profile["operation"],
        "options_sha256": profile["options_sha256"],
    }
    body["effect_sha256"] = _sha256(json.dumps(
        body, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
    ).encode("utf-8"))
    return body


def validate_transition_effect(value: dict) -> dict:
    if not isinstance(value, dict):
        raise ValueError("lifecycle effect must be an object")
    effect_keys = {
        "schema", "kind", "target_run", "input_sha256", "operation",
        "options_sha256", "effect_sha256",
    }
    if set(value) != effect_keys:
        raise ValueError("lifecycle effect schema/keys mismatch")
    operation = str(value.get("operation") or "")
    expected_kind = "create" if operation in CREATE_EFFECT_OPERATIONS else (
        "activate" if operation in ACTIVATE_EFFECT_OPERATIONS else ""
    )
    if value.get("kind") != expected_kind \
            or not re.fullmatch(r"[0-9a-f]{64}", str(value.get("options_sha256") or "")):
        raise ValueError("lifecycle effect operation/options are invalid")
    expected = None
    if value.get("kind") == "activate":
        body = {
            "schema": value.get("schema"),
            "kind": value.get("kind"),
            "target_run": value.get("target_run"),
            "input_sha256": value.get("input_sha256"),
            "operation": operation,
            "options_sha256": value.get("options_sha256"),
        }
        if body["schema"] != TRANSITION_EFFECT_SCHEMA \
                or not re.fullmatch(r"[A-Za-z0-9_-]+", str(body["target_run"] or "")) \
                or body["input_sha256"] != _sha256(
                    str(body["target_run"]).encode("utf-8", "replace")
                ):
            raise ValueError("invalid activate lifecycle effect")
        body["effect_sha256"] = _sha256(json.dumps(
            body, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
        ).encode("utf-8"))
        expected = body
    if value.get("kind") == "create":
        # The raw reference is deliberately unavailable here.  Validate the
        # closed schema and recompute only the descriptor digest.
        body = {
            "schema": value.get("schema"),
            "kind": value.get("kind"),
            "target_run": value.get("target_run"),
            "input_sha256": value.get("input_sha256"),
            "operation": operation,
            "options_sha256": value.get("options_sha256"),
        }
        if body["schema"] != TRANSITION_EFFECT_SCHEMA \
                or not re.fullmatch(r"[A-Za-z0-9_-]+", str(body["target_run"] or "")) \
                or not re.fullmatch(r"[0-9a-f]{64}", str(body["input_sha256"] or "")):
            raise ValueError("invalid create lifecycle effect")
        body["effect_sha256"] = _sha256(json.dumps(
            body, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
        ).encode("utf-8"))
        expected = body
    if value != expected:
        raise ValueError("lifecycle effect digest/schema mismatch")
    return dict(value)


def _fsync_dir(path: Path, *, required: bool = False) -> None:
    """Sync one directory, optionally making the durability barrier mandatory.

    Lock/staging cleanup keeps the historical best-effort behavior.  An
    authoritative transaction write passes ``required=True`` so an unsupported
    or failed directory sync cannot be mistaken for a durable commit.
    """
    try:
        fd = os.open(path, os.O_RDONLY)
    except (AttributeError, OSError) as exc:
        if required:
            raise _DirectoryDurabilityError(
                f"cannot open directory for durability sync: {path}"
            ) from exc
        return
    try:
        os.fsync(fd)
    except (AttributeError, OSError) as exc:
        if required:
            raise _DirectoryDurabilityError(
                f"cannot fsync directory for durability: {path}"
            ) from exc
    finally:
        os.close(fd)


def _atomic_write(
    path: Path,
    raw: bytes,
    *,
    mode: int = 0o600,
    durable_parent: bool = False,
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(
        prefix=path.name + ".", suffix=".tmp", dir=path.parent
    )
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(raw)
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(tmp_name, mode)
        os.replace(tmp_name, path)
        _fsync_dir(path.parent, required=durable_parent)
    finally:
        try:
            os.unlink(tmp_name)
        except FileNotFoundError:
            pass


def _pointer_durability_failed(
    *,
    run_dir: Path,
    transaction_id: str,
) -> SetupTransactionError:
    return SetupTransactionError(
        "pointer_durability_failed",
        "active pointer directory durability failed; the pointer may already be "
        "visible, but activation remains non-terminal and must be retried",
        run_dir=run_dir,
        transaction_id=transaction_id,
    )


def _write_active_pointer(
    pointer: Path,
    raw: bytes,
    *,
    run_dir: Path,
    transaction_id: str,
) -> None:
    """Replace the authoritative pointer and require its directory barrier."""
    try:
        _atomic_write(pointer, raw, durable_parent=True)
    except _DirectoryDurabilityError as exc:
        raise _pointer_durability_failed(
            run_dir=run_dir,
            transaction_id=transaction_id,
        ) from exc


def _confirm_active_pointer_durable(
    pointer: Path,
    *,
    run_dir: Path,
    transaction_id: str,
) -> None:
    """Re-run the pointer barrier before recovering a non-terminal receipt."""
    try:
        _fsync_dir(pointer.parent, required=True)
    except _DirectoryDurabilityError as exc:
        raise _pointer_durability_failed(
            run_dir=run_dir,
            transaction_id=transaction_id,
        ) from exc


def _confirm_receipt_durable(
    run_dir: Path,
    *,
    transaction_id: str,
) -> None:
    """Make an already-visible formal receipt durable before recovery succeeds."""
    if not _receipt_path(run_dir).exists():
        return
    try:
        _fsync_dir(_receipt_path(run_dir).parent, required=True)
    except _DirectoryDurabilityError as exc:
        raise SetupTransactionError(
            "receipt_durability_failed",
            "setup transaction receipt directory durability failed; recovery "
            "cannot terminalize the transaction",
            run_dir=run_dir,
            transaction_id=transaction_id,
        ) from exc


def _confirm_run_publish_durable(
    runs_root: Path,
    *,
    run_dir: Path,
    transaction_id: str,
) -> None:
    """Require the formal run-directory rename to be durable before activation."""
    try:
        _fsync_dir(runs_root, required=True)
    except _DirectoryDurabilityError as exc:
        raise SetupTransactionError(
            "run_publish_durability_failed",
            "formal run directory durability failed; the run remains prepared "
            "and cannot be activated until the exact transaction is retried",
            run_dir=run_dir,
            transaction_id=transaction_id,
        ) from exc


def _session_selection_durability_failed(
    *,
    run_dir: Path,
    transaction_id: str,
) -> SetupTransactionError:
    return SetupTransactionError(
        "session_selection_durability_failed",
        "session resume selection deletion is not durably confirmed; the "
        "already-safe resume barrier must be retried before success",
        run_dir=run_dir,
        transaction_id=transaction_id,
    )


def _consume_session_selection_durable(
    selection_path: Path,
    *,
    run_dir: Path,
    transaction_id: str,
) -> None:
    """Delete one resume receipt and require the deletion directory barrier."""
    try:
        selection_path.unlink(missing_ok=True)
        _fsync_dir(selection_path.parent, required=True)
    except (OSError, _DirectoryDurabilityError) as exc:
        raise _session_selection_durability_failed(
            run_dir=run_dir,
            transaction_id=transaction_id,
        ) from exc


def _confirm_session_selection_absence_durable(
    selection_path: Path,
    *,
    run_dir: Path,
    transaction_id: str,
) -> None:
    """Confirm a prior resume-receipt unlink after its barrier-only failure."""
    try:
        _fsync_dir(selection_path.parent, required=True)
    except _DirectoryDurabilityError as exc:
        raise _session_selection_durability_failed(
            run_dir=run_dir,
            transaction_id=transaction_id,
        ) from exc


def _atomic_json(
    path: Path,
    value: dict,
    *,
    durable_parent: bool = False,
) -> None:
    _atomic_write(
        path,
        (json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode(
            "utf-8"
        ),
        durable_parent=durable_parent,
    )


def pointer_snapshot(pointer: Path = ACTIVE_POINTER) -> PointerSnapshot:
    try:
        raw_bytes = pointer.read_bytes()
    except FileNotFoundError:
        return PointerSnapshot(False, "", _sha256(b""))
    return PointerSnapshot(True, raw_bytes.decode("utf-8", "replace"), _sha256(raw_bytes))


def _same_snapshot(left: PointerSnapshot, right: PointerSnapshot) -> bool:
    return left.exists == right.exists and left.sha256 == right.sha256 and left.raw == right.raw


def _invoke_fault(fault: FaultInjector | None, stage: str) -> None:
    if fault is not None:
        fault(stage)


@contextlib.contextmanager
def exclusive_directory_lock(
    path: Path,
    *,
    timeout: float = 10.0,
    stale_after: float = 10.0,
) -> Iterator[None]:
    """Portable lock based on atomic mkdir, with bounded stale-lock recovery."""
    deadline = time.monotonic() + timeout
    path.parent.mkdir(parents=True, exist_ok=True)
    while True:
        try:
            path.mkdir(mode=0o700)
        except FileExistsError:
            try:
                age = time.time() - path.stat().st_mtime
            except FileNotFoundError:
                continue
            owner = _read_json(path / "owner.json")
            owner_pid = int(owner.get("pid") or 0)
            owner_alive = False
            if owner_pid > 0:
                try:
                    os.kill(owner_pid, 0)
                    owner_alive = True
                except ProcessLookupError:
                    owner_alive = False
                except (PermissionError, OSError):
                    # Unknown is treated as live; never steal an ambiguous lock.
                    owner_alive = True
            if age > stale_after and not owner_alive:
                stale = path.with_name(path.name + f".stale.{uuid.uuid4().hex}")
                try:
                    path.rename(stale)
                    shutil.rmtree(stale, ignore_errors=True)
                    continue
                except (FileNotFoundError, OSError):
                    pass
            if time.monotonic() >= deadline:
                raise SetupTransactionError(
                    "lock_timeout", f"transaction lock busy: {path}"
                )
            time.sleep(0.05)
        else:
            try:
                _atomic_json(path / "owner.json", {
                    "pid": os.getpid(),
                    "created_at": time.time(),
                })
            except Exception:
                # A created lock without owner metadata must not linger until a
                # stale timeout if local metadata persistence itself failed.
                shutil.rmtree(path, ignore_errors=True)
                _fsync_dir(path.parent)
                raise
            break
    try:
        yield
    finally:
        shutil.rmtree(path, ignore_errors=True)
        _fsync_dir(path.parent)


def _validate_run_name(run_name: str) -> None:
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]*_[0-9]{8}", run_name):
        raise SetupTransactionError("invalid_run_name", f"invalid run name: {run_name!r}")


def _inside(path: Path, parent: Path) -> Path:
    resolved = path.resolve()
    try:
        resolved.relative_to(parent.resolve())
    except ValueError as exc:
        raise SetupTransactionError(
            "run_outside_root", f"run is outside transaction root: {resolved}"
        ) from exc
    return resolved


def _pointer_ref(run_dir: Path, root: Path) -> str:
    try:
        return str(run_dir.resolve().relative_to(root.resolve()))
    except ValueError:
        return str(run_dir.resolve())


def _pointer_target(
    snapshot: PointerSnapshot,
    *,
    root: Path,
    runs_root: Path,
) -> Path | None:
    if not snapshot.exists or not snapshot.raw.strip():
        return None
    candidate = Path(snapshot.raw.strip()).expanduser()
    if not candidate.is_absolute():
        candidate = root / candidate
    try:
        candidate = candidate.resolve()
        candidate.relative_to(runs_root.resolve())
    except (OSError, ValueError):
        return None
    return candidate if candidate.is_dir() else None


def _materialized_dangling_create_pointer(
    target: Path,
    receipt: dict,
    snapshot: PointerSnapshot,
    *,
    root: Path,
    runs_root: Path,
) -> bool:
    """Detect unchanged pointer bytes whose missing referent was just published.

    A pathname can change meaning without a pointer write: before atomic rename it
    is dangling, afterwards it resolves to the newly published target.  That is
    not evidence of a prior pointer commit and must not enter post-commit recovery.
    New receipts freeze the pre-publication semantic origin to distinguish this
    case from a real crash after pointer replacement.
    """
    expected = receipt.get("expected_pointer") \
        if isinstance(receipt.get("expected_pointer"), dict) else {}
    return bool(
        receipt.get("status") in {"prepared", "prepared_not_active"}
        and receipt.get("expected_origin_valid") is False
        and str(receipt.get("expected_origin_run") or "") == ""
        and expected.get("exists") is snapshot.exists
        and expected.get("sha256") == snapshot.sha256
        and _pointer_target(snapshot, root=root, runs_root=runs_root) == target
        and receipt.get("contract_binding") is None
        and receipt.get("transition_claim") is None
    )


def _read_json(path: Path) -> dict:
    try:
        value = json.loads(path.read_text(encoding="utf-8", errors="strict"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return {}
    return value if isinstance(value, dict) else {}


def _receipt_path(run_dir: Path) -> Path:
    return run_dir / RECEIPT_REL


def _read_receipt(run_dir: Path) -> dict:
    value = _read_json(_receipt_path(run_dir))
    return value if value.get("schema") == RECEIPT_SCHEMA else {}


def _valid_sha256(value: object) -> bool:
    return bool(re.fullmatch(r"[0-9a-f]{64}", str(value or "")))


def _valid_timestamp(value: object, *, allow_zero: bool = False) -> bool:
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        return False
    numeric = float(value)
    return (allow_zero and numeric == 0.0) or 0.0 < numeric < float("inf")


def session_selection_path(selection_dir: Path, session_id: str) -> Path:
    """Return the only selection-receipt path valid for one Claude session."""
    if not session_id:
        raise SetupTransactionError(
            "invalid_session_selection", "session selection requires a session id"
        )
    digest = _sha256(session_id.encode("utf-8", "replace"))
    return selection_dir / f"{digest}.json"


def _selection_dir_inside_pointer(selection_dir: Path, pointer: Path) -> Path:
    try:
        parent = pointer.parent.resolve()
        resolved = selection_dir.resolve()
        resolved.relative_to(parent)
    except (OSError, ValueError) as exc:
        raise SetupTransactionError(
            "invalid_session_selection",
            "session selection directory must stay inside the pointer state directory",
        ) from exc
    if resolved == parent:
        raise SetupTransactionError(
            "invalid_session_selection",
            "session selection receipts require a dedicated subdirectory",
        )
    return resolved


def _selection_digest(value: dict) -> str:
    body = {key: value[key] for key in value if key != "receipt_sha256"}
    return _sha256(json.dumps(
        body, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
    ).encode("utf-8"))


def _run_identity(run_dir: Path, *, root: Path) -> dict:
    receipt = _read_receipt(run_dir)
    _validate_activation_receipt(run_dir, receipt)
    transaction_id = str(receipt.get("transaction_id") or "")
    source_hash = str(receipt.get("source_sha256") or "")
    legacy = not bool(receipt)
    try:
        stat_result = run_dir.stat()
    except OSError as exc:
        raise SetupTransactionError(
            "invalid_session_selection",
            "session selection run identity is unavailable",
            run_dir=run_dir,
        ) from exc
    identity = {
        "run_name": run_dir.name,
        "run_ref": _pointer_ref(run_dir, root),
        "run_path_sha256": _sha256(
            str(run_dir.resolve()).encode("utf-8", "replace")
        ),
        "transaction_id": transaction_id,
        "source_sha256": source_hash,
        "legacy": legacy,
        # Formal runs already have a transaction/source identity.  Legacy runs
        # need filesystem object identity as well as a pathname so deleting and
        # recreating the same path cannot inherit a resume capability.
        "st_dev": int(stat_result.st_dev) if legacy else 0,
        "st_ino": int(stat_result.st_ino) if legacy else 0,
    }
    identity["run_identity_sha256"] = _sha256(json.dumps(
        identity, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
    ).encode("utf-8"))
    return identity


def _build_session_selection(
    *,
    session_id: str,
    transcript_sha256: str,
    target: Path,
    root: Path,
    pointer_snapshot_value: PointerSnapshot,
    active_contract_sha256: str,
    ended_contract_sha256: str,
) -> dict:
    identity = _run_identity(target, root=root)
    value = {
        "schema": SESSION_SELECTION_SCHEMA,
        "status": "prepared",
        "session_id_sha256": _sha256(
            session_id.encode("utf-8", "replace")),
        "transcript_sha256": transcript_sha256,
        **identity,
        "pointer_sha256": pointer_snapshot_value.sha256,
        "active_contract_sha256": active_contract_sha256,
        "ended_contract_sha256": ended_contract_sha256,
        "prepared_at": time.time(),
        "cleared_at": 0.0,
    }
    value["receipt_sha256"] = _selection_digest(value)
    return value


def validate_session_selection(value: dict) -> dict:
    keys = {
        "schema", "status", "session_id_sha256", "transcript_sha256",
        "run_name", "run_ref", "run_path_sha256", "transaction_id",
        "source_sha256", "legacy", "st_dev", "st_ino",
        "run_identity_sha256", "pointer_sha256", "active_contract_sha256",
        "ended_contract_sha256", "prepared_at", "cleared_at",
        "receipt_sha256",
    }
    if not isinstance(value, dict) or set(value) != keys \
            or value.get("schema") != SESSION_SELECTION_SCHEMA:
        raise SetupTransactionError(
            "invalid_session_selection", "session selection schema/keys are invalid"
        )
    if value.get("status") not in {"prepared", "cleared"}:
        raise SetupTransactionError(
            "invalid_session_selection", "session selection status is invalid"
        )
    if not re.fullmatch(r"[A-Za-z0-9_-]+", str(value.get("run_name") or "")):
        raise SetupTransactionError(
            "invalid_session_selection", "session selection run name is invalid"
        )
    run_ref = str(value.get("run_ref") or "")
    if not run_ref or re.search(r"[\x00-\x1f\x7f]", run_ref):
        raise SetupTransactionError(
            "invalid_session_selection", "session selection run reference is invalid"
        )
    digests = (
        value.get("session_id_sha256"), value.get("transcript_sha256"),
        value.get("run_path_sha256"), value.get("run_identity_sha256"),
        value.get("pointer_sha256"), value.get("active_contract_sha256"),
        value.get("ended_contract_sha256"), value.get("receipt_sha256"),
    )
    if not all(_valid_sha256(item) for item in digests):
        raise SetupTransactionError(
            "invalid_session_selection", "session selection digest is invalid"
        )
    if not isinstance(value.get("legacy"), bool):
        raise SetupTransactionError(
            "invalid_session_selection", "session selection legacy flag is invalid"
        )
    st_dev = value.get("st_dev")
    st_ino = value.get("st_ino")
    valid_stat_types = bool(
        isinstance(st_dev, int) and not isinstance(st_dev, bool)
        and isinstance(st_ino, int) and not isinstance(st_ino, bool)
    )
    transaction_id = str(value.get("transaction_id") or "")
    source_hash = str(value.get("source_sha256") or "")
    if value["legacy"]:
        valid_identity = bool(
            not transaction_id and not source_hash and valid_stat_types
            and st_dev >= 0 and st_ino > 0
        )
    else:
        valid_identity = bool(
            re.fullmatch(r"[0-9a-f]{32}", transaction_id)
            and _valid_sha256(source_hash)
            and valid_stat_types and st_dev == 0 and st_ino == 0
        )
    if not valid_identity:
        raise SetupTransactionError(
            "invalid_session_selection", "session selection run identity is invalid"
        )
    if not _valid_timestamp(value.get("prepared_at")):
        raise SetupTransactionError(
            "invalid_session_selection", "session selection prepared timestamp is invalid"
        )
    cleared_at = value.get("cleared_at")
    if value["status"] == "prepared":
        valid_cleared_at = _valid_timestamp(cleared_at, allow_zero=True) \
            and float(cleared_at) == 0.0
    else:
        valid_cleared_at = _valid_timestamp(cleared_at)
    if not valid_cleared_at:
        raise SetupTransactionError(
            "invalid_session_selection", "session selection cleared timestamp is invalid"
        )
    identity = {
        "run_name": value["run_name"],
        "run_ref": value["run_ref"],
        "run_path_sha256": value["run_path_sha256"],
        "transaction_id": transaction_id,
        "source_sha256": source_hash,
        "legacy": value["legacy"],
        "st_dev": st_dev,
        "st_ino": st_ino,
    }
    expected_identity = _sha256(json.dumps(
        identity, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
    ).encode("utf-8"))
    if value.get("run_identity_sha256") != expected_identity \
            or value.get("receipt_sha256") != _selection_digest(value):
        raise SetupTransactionError(
            "invalid_session_selection", "session selection identity/digest mismatch"
        )
    return dict(value)


def _write_selection_status(path: Path, value: dict, status: str) -> dict:
    result = dict(validate_session_selection(value))
    if status != "cleared":
        raise SetupTransactionError(
            "invalid_session_selection", "unsupported session selection status"
        )
    result["status"] = "cleared"
    result["cleared_at"] = time.time()
    result["receipt_sha256"] = _selection_digest(result)
    _atomic_json(path, result)
    return result


def _same_selection_binding(left: dict, right: dict) -> bool:
    """Compare immutable receipt identity while ignoring status/timestamps."""
    keys = (
        "session_id_sha256", "transcript_sha256", "run_name", "run_ref",
        "run_path_sha256", "transaction_id", "source_sha256", "legacy",
        "st_dev", "st_ino", "run_identity_sha256", "pointer_sha256",
        "active_contract_sha256", "ended_contract_sha256",
    )
    return all(left.get(key) == right.get(key) for key in keys)


def _callback_contract(
    target: Path,
    callback_result: dict | bytes,
) -> tuple[bytes, dict]:
    path = target / "state" / "turn_contract.json"
    try:
        raw = path.read_bytes()
        contract = json.loads(raw.decode("utf-8", "strict"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise SetupTransactionError(
            "invalid_resume_barrier",
            "session contract callback did not persist valid JSON",
            run_dir=target,
        ) from exc
    if not isinstance(contract, dict):
        raise SetupTransactionError(
            "invalid_resume_barrier", "session contract callback returned a non-object",
            run_dir=target,
        )
    if isinstance(callback_result, bytes):
        matches = callback_result == raw
    elif isinstance(callback_result, dict):
        matches = callback_result == contract
    else:
        matches = False
    if not matches:
        raise SetupTransactionError(
            "invalid_resume_barrier",
            "session contract callback result does not match persisted state",
            run_dir=target,
        )
    return raw, contract


def _validate_safe_session_contract(
    contract: dict,
    *,
    session_id: str,
    transcript_sha256: str,
    target: Path,
    authority_state: str,
    active_contract_sha256: str = "",
    selection_sha256: str = "",
) -> None:
    if contract.get("schema") != TURN_CONTRACT_SCHEMA \
            or contract.get("mode") != "EXPLAIN_ONLY" \
            or str(contract.get("session_id") or "") != session_id \
            or str(contract.get("bound_run") or "") != target.name \
            or contract.get("authority_state") != authority_state \
            or contract.get("resume_requires_prompt") is not True \
            or str(contract.get("transcript_sha256") or "") != transcript_sha256 \
            or not _valid_sha256(contract.get("prompt_sha256")):
        raise SetupTransactionError(
            "invalid_resume_barrier",
            "session callback did not persist the required fail-closed contract",
            run_dir=target,
        )
    if any(bool(contract.get(key)) for key in (
            "run_transition_requested", "run_bind_requested", "loop_requested",
            "resume_current_approved", "classify_approved",
            "ai_external_approved", "memory_approved", "direct_egress_approved",
            "fanout_override", "transition_claim", "source_sha256s",
            "run_name_sha256s", "slug_sha256s")) \
            or str(contract.get("lifecycle_operation") or "none") != "none" \
            or any(str(key).startswith(("maintenance_", "scope_admission_"))
                   for key in contract):
        raise SetupTransactionError(
            "invalid_resume_barrier",
            "session callback contract carries executable authority",
            run_dir=target,
        )
    ended_from = str(contract.get("ended_from_contract_sha256") or "")
    if not _valid_sha256(ended_from):
        raise SetupTransactionError(
            "invalid_resume_barrier",
            "session callback contract lacks the ended authority digest",
            run_dir=target,
        )
    if active_contract_sha256 and ended_from != active_contract_sha256:
        raise SetupTransactionError(
            "invalid_resume_barrier",
            "session callback contract changed the ended authority identity",
            run_dir=target,
        )
    if authority_state == "session_ended":
        if contract.get("session_start_source") not in {None, ""}:
            raise SetupTransactionError(
                "invalid_resume_barrier",
                "ended-session contract cannot claim a SessionStart source",
                run_dir=target,
            )
    elif authority_state == "resume_barrier":
        if not _valid_sha256(selection_sha256) \
                or contract.get("session_start_source") != "resume" \
                or str(contract.get("resume_selection_sha256") or "") \
                != selection_sha256:
            raise SetupTransactionError(
                "invalid_resume_barrier",
                "resume barrier is not bound to the exact resume selection",
                run_dir=target,
            )


def _selection_target(
    selection: dict,
    *,
    root: Path,
    runs_root: Path,
) -> Path:
    value = validate_session_selection(selection)
    candidate = Path(str(value["run_ref"])).expanduser()
    if not candidate.is_absolute():
        candidate = root / candidate
    try:
        target = candidate.resolve()
        target.relative_to(runs_root.resolve())
    except (OSError, ValueError) as exc:
        raise SetupTransactionError(
            "invalid_session_selection", "session selection target is outside runs",
        ) from exc
    if not target.is_dir() or target.name != value["run_name"] \
            or _pointer_ref(target, root) != value["run_ref"] \
            or _sha256(str(target).encode("utf-8", "replace")) \
            != value["run_path_sha256"]:
        raise SetupTransactionError(
            "invalid_session_selection", "session selection target identity changed",
            run_dir=target,
        )
    current_identity = _run_identity(target, root=root)
    for key in (
            "run_name", "run_ref", "run_path_sha256", "transaction_id",
            "source_sha256", "legacy", "st_dev", "st_ino",
            "run_identity_sha256"):
        if value[key] != current_identity[key]:
            raise SetupTransactionError(
                "invalid_session_selection",
                "session selection no longer matches the run identity",
                run_dir=target,
            )
    return target


def _validate_create_effect_profile(
    run_dir: Path | None,
    source: dict,
    profile_value: object,
) -> dict:
    try:
        profile = validate_lifecycle_effect_profile(
            profile_value, expected_kind="create")
    except ValueError as exc:
        raise SetupTransactionError(
            "invalid_effect_profile",
            f"current-schema setup effect profile is invalid: {exc}",
            run_dir=run_dir,
        ) from exc
    source_kind = str(source.get("source", {}).get("kind") or "")
    source_type = str(profile.get("source_type") or "")
    operation = str(profile.get("operation") or "")
    compatible = source_type == source_kind
    if operation == OP_LOOP_BOOTSTRAP_CREATE:
        compatible = bool(
            source_type == "auto"
            or source_type == source_kind
            or source_type == "file" and source_kind in {
                "recon-json", "json", "markdown",
            }
        )
    if not compatible:
        raise SetupTransactionError(
            "effect_profile_source_mismatch",
            "setup effect source type does not match the frozen source manifest",
            run_dir=run_dir,
        )
    extractor = source.get("extractor") \
        if isinstance(source.get("extractor"), dict) else {}
    actual_ai = "external" if extractor.get("ai_backend") is not None else "off"
    if profile.get("ai_mode") != actual_ai:
        raise SetupTransactionError(
            "effect_profile_ai_mismatch",
            "setup effect AI mode does not match the frozen source manifest",
            run_dir=run_dir,
        )
    if actual_ai == "external" and run_dir is not None:
        request = _read_json(run_dir / setup_source.NORMALIZER_REQUEST_REL)
        ai = request.get("ai") if isinstance(request.get("ai"), dict) else {}
        try:
            candidate_raw = (run_dir / setup_source.NORMALIZER_CANDIDATE_REL).read_bytes()
            candidate_sha = _semantic_json_sha256(candidate_raw)
        except (OSError, ValueError) as exc:
            raise SetupTransactionError(
                "invalid_effect_profile",
                f"external effect option artifacts are unavailable: {exc}",
                run_dir=run_dir,
            ) from exc
        expected_digests = {
            "provider_sha256": _sha256(str(ai.get("provider") or "").encode("utf-8")),
            "model_sha256": _sha256(str(ai.get("model") or "").encode("utf-8")),
            "candidate_sha256": candidate_sha,
        }
        if any(profile.get(key) != digest for key, digest in expected_digests.items()):
            raise SetupTransactionError(
                "effect_profile_ai_mismatch",
                "setup effect AI option digest does not match the frozen artifacts",
                run_dir=run_dir,
            )
    return profile


def _validate_activation_receipt(run_dir: Path, receipt: dict) -> None:
    """Distinguish a legacy missing receipt from a corrupt formal receipt."""
    receipt_path = _receipt_path(run_dir)
    if not receipt_path.exists():
        return
    if not receipt:
        raise SetupTransactionError(
            "invalid_transaction_receipt",
            "existing setup transaction receipt is unreadable or has the wrong schema",
            run_dir=run_dir,
        )
    transaction_id = str(receipt.get("transaction_id") or "")
    source_hash = str(receipt.get("source_sha256") or "")
    if not re.fullmatch(r"[0-9a-f]{32}", transaction_id):
        raise SetupTransactionError(
            "invalid_transaction_receipt", "receipt transaction id is invalid", run_dir=run_dir
        )
    if not re.fullmatch(r"[0-9a-f]{64}", source_hash):
        raise SetupTransactionError(
            "invalid_transaction_receipt", "receipt source hash is invalid", run_dir=run_dir
        )
    if str(receipt.get("run_name") or "") != run_dir.name:
        raise SetupTransactionError(
            "invalid_transaction_receipt", "receipt run name does not match directory", run_dir=run_dir
        )
    if str(receipt.get("status") or "") not in {
        "prepared", "prepared_not_active", "committed", "recovered",
    }:
        raise SetupTransactionError(
            "invalid_transaction_receipt", "receipt status is invalid", run_dir=run_dir
        )
    source = _read_json(run_dir / SOURCE_REL)
    try:
        setup_source.validate_manifest(source, allow_legacy=True)
        if source.get("schema") == SOURCE_SCHEMA:
            setup_source.verify_bundle(run_dir, source)
    except setup_source.SetupSourceError as exc:
        raise SetupTransactionError(
            exc.code, f"setup source manifest/bundle is invalid: {exc}",
            run_dir=run_dir, transaction_id=transaction_id,
        ) from exc
    if str(source.get("source_sha256") or "") != source_hash:
        raise SetupTransactionError(
            "transaction_identity_mismatch",
            "setup source manifest does not match transaction receipt",
            run_dir=run_dir,
            transaction_id=transaction_id,
        )
    if source.get("schema") == SOURCE_SCHEMA:
        _validate_create_effect_profile(
            run_dir, source, receipt.get("effect_profile"))
        _validate_create_claim_binding(
            run_dir, receipt, source_hash=source_hash)
    activation_attempt = receipt.get("activation_attempt")
    if activation_attempt is not None:
        _validate_activation_attempt(run_dir, receipt, activation_attempt)


def _write_receipt(run_dir: Path, receipt: dict) -> None:
    value = dict(receipt)
    value["schema"] = RECEIPT_SCHEMA
    value["updated_at"] = time.time()
    try:
        _atomic_json(
            _receipt_path(run_dir), value, durable_parent=True)
    except _DirectoryDurabilityError as exc:
        raise SetupTransactionError(
            "receipt_durability_failed",
            "setup transaction receipt directory durability failed; activation "
            "cannot advance until the exact transaction is retried",
            run_dir=run_dir,
            transaction_id=str(value.get("transaction_id") or ""),
        ) from exc


def _validate_setup_bundle(run_dir: Path, required_files: tuple[str, ...]) -> None:
    """Validate the complete current-schema setup bundle and run skeleton."""
    missing = [name for name in required_files if not (run_dir / name).exists()]
    if missing:
        raise SetupTransactionError(
            "incomplete_staging",
            "prepared run missing required files: " + ", ".join(missing),
            run_dir=run_dir,
        )
    source = _read_json(run_dir / SOURCE_REL)
    try:
        setup_source.validate_manifest(source)
        setup_source.verify_bundle(run_dir, source)
    except setup_source.SetupSourceError as exc:
        raise SetupTransactionError(
            exc.code, f"prepared source manifest/bundle is invalid: {exc}", run_dir=run_dir
        ) from exc
    receipt = _read_receipt(run_dir)
    _validate_create_effect_profile(
        run_dir, source, receipt.get("effect_profile"))
    coverage_path = run_dir / "classify" / "coverage.json"
    if coverage_path.exists():
        coverage = _read_json(coverage_path)
        assets = coverage.get("assets")
        if not isinstance(assets, list) or not any(
            isinstance(item, dict) and str(item.get("host") or "").strip()
            for item in assets
        ):
            raise SetupTransactionError(
                "invalid_coverage", "coverage contains no valid asset", run_dir=run_dir
            )


def _validate_prepared_run(run_dir: Path, required_files: tuple[str, ...]) -> None:
    _validate_setup_bundle(run_dir, required_files)
    receipt = _read_receipt(run_dir)
    if not receipt.get("transaction_id") or receipt.get("status") != "prepared":
        raise SetupTransactionError(
            "invalid_prepared_receipt", "prepared transaction receipt is invalid", run_dir=run_dir
        )


def _valid_receipt_timestamp(value: object) -> bool:
    return (
        isinstance(value, (int, float))
        and not isinstance(value, bool)
        and 0 < float(value) < float("inf")
    )


def _validate_exact_claim_binding(
    run_dir: Path,
    *,
    transaction_id: str,
    source_hash: str,
    contract_binding: object,
    transition_binding: object,
    expected_effect: dict,
    code: str,
    label: str,
) -> dict | None:
    """Validate one closed hook binding without consulting mutable claim state."""
    if contract_binding is None and transition_binding is None:
        return None
    if not isinstance(contract_binding, dict) \
            or not isinstance(transition_binding, dict):
        raise SetupTransactionError(
            code,
            f"{label} has an incomplete hook claim binding",
            run_dir=run_dir,
            transaction_id=transaction_id,
        )
    session_id = str(transition_binding.get("session_id") or "")
    prompt_sha = str(transition_binding.get("prompt_sha256") or "")
    origin_run = str(transition_binding.get("origin_run") or "")
    if not session_id or not re.fullmatch(r"[0-9a-f]{64}", prompt_sha) \
            or (origin_run and not re.fullmatch(r"[A-Za-z0-9_-]+", origin_run)):
        raise SetupTransactionError(
            code,
            f"{label} session/prompt/origin identity is invalid",
            run_dir=run_dir,
            transaction_id=transaction_id,
        )
    expected_contract_binding = {
        "session_id": session_id,
        "prompt_sha256": prompt_sha,
        "source_sha256": source_hash,
        "transaction_id": transaction_id,
        "expected_run": run_dir.name,
    }
    expected_transition_binding = {
        "target_run": run_dir.name,
        "origin_run": origin_run,
        "session_id": session_id,
        "prompt_sha256": prompt_sha,
        "transaction_id": transaction_id,
        "source_sha256": source_hash,
        "expected_run": run_dir.name,
        "effect": expected_effect,
    }
    if contract_binding != expected_contract_binding \
            or transition_binding != expected_transition_binding:
        raise SetupTransactionError(
            code,
            f"{label} transaction/source/run/claim binding is inconsistent",
            run_dir=run_dir,
            transaction_id=transaction_id,
        )
    return dict(transition_binding)


def _validate_create_claim_binding(
    run_dir: Path,
    receipt: dict,
    *,
    source_hash: str,
) -> dict | None:
    """Keep the receipt's top-level claim identity create-only and immutable."""
    transaction_id = str(receipt.get("transaction_id") or "")
    source = _read_json(run_dir / SOURCE_REL)
    source_section = source.get("source") \
        if isinstance(source.get("source"), dict) else {}
    try:
        effect_profile = validate_lifecycle_effect_profile(
            receipt.get("effect_profile"), expected_kind="create")
        expected_effect = transition_effect(
            "create",
            run_dir.name,
            source_reference=str(source_section.get("reference") or ""),
            profile=effect_profile,
        )
    except ValueError as exc:
        raise SetupTransactionError(
            "transaction_identity_mismatch",
            f"create lifecycle identity cannot be derived: {exc}",
            run_dir=run_dir,
            transaction_id=transaction_id,
        ) from exc
    return _validate_exact_claim_binding(
        run_dir,
        transaction_id=transaction_id,
        source_hash=source_hash,
        contract_binding=receipt.get("contract_binding"),
        transition_binding=receipt.get("transition_claim"),
        expected_effect=expected_effect,
        code="transaction_identity_mismatch",
        label="create receipt",
    )


def _activation_attempt_digest(value: dict) -> str:
    body = {key: item for key, item in value.items() if key != "attempt_sha256"}
    return _sha256(json.dumps(
        body, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
    ).encode("utf-8"))


def _validate_activation_attempt(
    run_dir: Path,
    receipt: dict,
    value: object,
    *,
    requested_effect: dict | None = None,
) -> dict:
    """Validate the self-contained activation identity nested below create state."""
    transaction_id = str(receipt.get("transaction_id") or "")
    source_hash = str(receipt.get("source_sha256") or "")
    if not isinstance(value, dict):
        raise SetupTransactionError(
            "invalid_activation_attempt",
            "activation attempt must be an object",
            run_dir=run_dir,
            transaction_id=transaction_id,
        )
    status = str(value.get("status") or "")
    base_keys = {
        "schema", "status", "transaction_id", "source_sha256", "target_run",
        "effect_profile", "effect", "expected_pointer", "contract_binding",
        "transition_claim", "started_at", "attempt_sha256",
    }
    expected_keys = set(base_keys)
    if status in {"committed", "recovered"}:
        expected_keys.add("committed_at")
    if status == "recovered":
        expected_keys.add("recovered_at")
    if status not in {"pending", "committed", "recovered"} \
            or set(value) != expected_keys \
            or value.get("schema") != ACTIVATION_ATTEMPT_SCHEMA:
        raise SetupTransactionError(
            "invalid_activation_attempt",
            "activation attempt schema/status/keys are invalid",
            run_dir=run_dir,
            transaction_id=transaction_id,
        )
    if value.get("transaction_id") != transaction_id \
            or value.get("source_sha256") != source_hash \
            or value.get("target_run") != run_dir.name:
        raise SetupTransactionError(
            "invalid_activation_attempt",
            "activation attempt does not match its create transaction",
            run_dir=run_dir,
            transaction_id=transaction_id,
        )
    expected_pointer = value.get("expected_pointer")
    if not isinstance(expected_pointer, dict) \
            or set(expected_pointer) != {"exists", "sha256"} \
            or not isinstance(expected_pointer.get("exists"), bool) \
            or not re.fullmatch(
                r"[0-9a-f]{64}", str(expected_pointer.get("sha256") or "")
            ) \
            or not _valid_receipt_timestamp(value.get("started_at")):
        raise SetupTransactionError(
            "invalid_activation_attempt",
            "activation attempt pointer/time identity is invalid",
            run_dir=run_dir,
            transaction_id=transaction_id,
        )
    if status in {"committed", "recovered"} \
            and not _valid_receipt_timestamp(value.get("committed_at")):
        raise SetupTransactionError(
            "invalid_activation_attempt",
            "terminal activation attempt lacks a commit timestamp",
            run_dir=run_dir,
            transaction_id=transaction_id,
        )
    if status == "recovered" \
            and not _valid_receipt_timestamp(value.get("recovered_at")):
        raise SetupTransactionError(
            "invalid_activation_attempt",
            "recovered activation attempt lacks a recovery timestamp",
            run_dir=run_dir,
            transaction_id=transaction_id,
        )
    try:
        profile = validate_lifecycle_effect_profile(
            value.get("effect_profile"), expected_kind="activate")
        effect = validate_transition_effect(value.get("effect"))
        expected_effect = transition_effect(
            "activate", run_dir.name, profile=profile)
    except ValueError as exc:
        raise SetupTransactionError(
            "invalid_activation_attempt",
            f"activation attempt effect is invalid: {exc}",
            run_dir=run_dir,
            transaction_id=transaction_id,
        ) from exc
    if effect != expected_effect:
        raise SetupTransactionError(
            "invalid_activation_attempt",
            "activation attempt profile/effect binding is inconsistent",
            run_dir=run_dir,
            transaction_id=transaction_id,
        )
    if requested_effect is not None and effect != requested_effect:
        raise SetupTransactionError(
            "activation_attempt_mismatch",
            "retry operation does not match the pending activation attempt",
            run_dir=run_dir,
            transaction_id=transaction_id,
        )
    _validate_exact_claim_binding(
        run_dir,
        transaction_id=transaction_id,
        source_hash=source_hash,
        contract_binding=value.get("contract_binding"),
        transition_binding=value.get("transition_claim"),
        expected_effect=effect,
        code="invalid_activation_attempt",
        label="activation attempt",
    )
    try:
        expected_digest = _activation_attempt_digest(value)
    except (TypeError, ValueError) as exc:
        raise SetupTransactionError(
            "invalid_activation_attempt",
            f"activation attempt is not canonical JSON: {exc}",
            run_dir=run_dir,
            transaction_id=transaction_id,
        ) from exc
    if value.get("attempt_sha256") != expected_digest:
        raise SetupTransactionError(
            "invalid_activation_attempt",
            "activation attempt digest mismatch",
            run_dir=run_dir,
            transaction_id=transaction_id,
        )
    return dict(value)


def _build_activation_attempt(
    run_dir: Path,
    receipt: dict,
    *,
    profile: dict,
    effect: dict,
    expected: PointerSnapshot,
    contract: dict,
) -> dict:
    transaction_id = str(receipt.get("transaction_id") or "")
    source_hash = str(receipt.get("source_sha256") or "")
    contract_binding = None
    transition_binding = contract.get("transition_claim") if contract else None
    if isinstance(transition_binding, dict):
        contract_binding = {
            "session_id": str(contract.get("session_id") or ""),
            "prompt_sha256": str(contract.get("prompt_sha256") or ""),
            "source_sha256": source_hash,
            "transaction_id": transaction_id,
            "expected_run": run_dir.name,
        }
    attempt = {
        "schema": ACTIVATION_ATTEMPT_SCHEMA,
        "status": "pending",
        "transaction_id": transaction_id,
        "source_sha256": source_hash,
        "target_run": run_dir.name,
        "effect_profile": profile,
        "effect": effect,
        "expected_pointer": {
            "exists": expected.exists,
            "sha256": expected.sha256,
        },
        "contract_binding": contract_binding,
        "transition_claim": transition_binding,
        "started_at": time.time(),
    }
    attempt["attempt_sha256"] = _activation_attempt_digest(attempt)
    return _validate_activation_attempt(
        run_dir, receipt, attempt, requested_effect=effect)


def _activation_attempt_matches_snapshot(
    attempt: dict,
    snapshot: PointerSnapshot,
) -> bool:
    expected = attempt.get("expected_pointer") \
        if isinstance(attempt.get("expected_pointer"), dict) else {}
    return bool(
        expected.get("exists") is snapshot.exists
        and expected.get("sha256") == snapshot.sha256
    )


def _activation_contract_matches_attempt(
    run_dir: Path,
    receipt: dict,
    attempt: dict,
    contract: dict,
) -> bool:
    expected = _build_activation_attempt(
        run_dir,
        receipt,
        profile=dict(attempt["effect_profile"]),
        effect=dict(attempt["effect"]),
        expected=PointerSnapshot(
            bool(attempt["expected_pointer"]["exists"]),
            "",
            str(attempt["expected_pointer"]["sha256"]),
        ),
        contract=contract,
    )
    frozen_keys = {
        "transaction_id", "source_sha256", "target_run", "effect_profile",
        "effect", "expected_pointer", "contract_binding", "transition_claim",
    }
    return all(expected[key] == attempt[key] for key in frozen_keys)


def _finalize_activation_attempt(
    run_dir: Path,
    *,
    recovered: bool,
    pointer: Path,
) -> dict:
    receipt = _read_receipt(run_dir)
    attempt = _validate_activation_attempt(
        run_dir, receipt, receipt.get("activation_attempt"))
    if attempt.get("status") in {"committed", "recovered"}:
        return receipt
    now = time.time()
    attempt["status"] = "recovered" if recovered else "committed"
    attempt["committed_at"] = now
    if recovered:
        attempt["recovered_at"] = now
    attempt["attempt_sha256"] = _activation_attempt_digest(attempt)
    receipt["activation_attempt"] = attempt
    if receipt.get("status") in {"prepared", "prepared_not_active"}:
        receipt.update({
            "status": "recovered" if recovered else "committed",
            "active_pointer": str(pointer),
            "committed_at": now,
        })
        if recovered:
            receipt["recovered_at"] = now
        receipt.pop("last_error", None)
    _write_receipt(run_dir, receipt)
    return receipt


def _validate_create_recovery_receipt(
    run_dir: Path,
    receipt: dict,
    *,
    source_hash: str,
    requested_transaction_id: str,
) -> dict | None:
    """Validate immutable create publish/claim identity for pointer recovery."""
    transaction_id = str(receipt.get("transaction_id") or "")
    if requested_transaction_id and transaction_id != requested_transaction_id:
        raise SetupTransactionError(
            "transaction_identity_mismatch",
            "recovery transaction id does not match the requested transaction",
            run_dir=run_dir,
            transaction_id=transaction_id,
        )
    expected_pointer = receipt.get("expected_pointer")
    if not _valid_receipt_timestamp(receipt.get("prepared_at")) \
            or not isinstance(expected_pointer, dict) \
            or not isinstance(expected_pointer.get("exists"), bool) \
            or not re.fullmatch(
                r"[0-9a-f]{64}", str(expected_pointer.get("sha256") or "")
            ):
        raise SetupTransactionError(
            "invalid_transaction_receipt",
            "recovery receipt is missing immutable preparation identity",
            run_dir=run_dir,
            transaction_id=transaction_id,
        )
    if receipt.get("status") == "prepared_not_active" \
            and not _valid_receipt_timestamp(receipt.get("publish_intent_at")):
        raise SetupTransactionError(
            "invalid_transaction_receipt",
            "prepared_not_active receipt lacks a valid publish intent",
            run_dir=run_dir,
            transaction_id=transaction_id,
        )

    return _validate_create_claim_binding(
        run_dir, receipt, source_hash=source_hash)


def _claim_or_transfer_contract(
    current: Path | None,
    target: Path,
    *,
    transaction_id: str,
    source_hash: str,
    pending_dir: Path | None,
    claims_dir: Path | None,
    effect: dict,
) -> dict:
    """Use hook-owned claim material; callers cannot provide claim contents."""
    try:
        import turn_contract  # local import avoids a lifecycle import cycle
    except ImportError as exc:
        raise SetupTransactionError(
            "contract_boundary_unavailable",
            "turn-contract boundary is unavailable; activation is denied",
            run_dir=target,
            transaction_id=transaction_id,
        ) from exc
    expected_run = target.name if transaction_id and source_hash else ""
    try:
        contract = turn_contract.claim_transition_contract(
            target,
            current_run=current,
            pending_dir=pending_dir,
            claims_dir=claims_dir,
            transaction_id=transaction_id,
            source_hash=source_hash,
            expected_run=expected_run,
            effect=effect,
        )
        if contract or current is None or current.resolve() == target.resolve() \
                or str(effect.get("kind") or "") != "activate":
            return contract
        # A direct local CLI invocation has no hook claim by design, but an
        # already selected run may still carry the current turn contract.  Move
        # that contract to the target before the pointer CAS; never let the
        # pointer switch strand it on the old run.  ``transfer_contract`` only
        # copies an existing valid contract and cannot mint operator authority.
        return turn_contract.transfer_contract(
            current,
            target,
            transaction_id=transaction_id,
            source_hash=source_hash,
            expected_run=expected_run,
        )
    except turn_contract.TransitionDurabilityError as exc:
        raise SetupTransactionError(
            "contract_claim_durability_failed",
            f"transition claim durability barrier failed: {exc}",
            run_dir=target,
            transaction_id=transaction_id,
        ) from exc
    except RuntimeError as exc:
        raise SetupTransactionError(
            "contract_claim_invalid",
            f"transition claim/contract binding failed: {exc}",
            run_dir=target,
            transaction_id=transaction_id,
        ) from exc


def _finalize_hook_transition_claim(
    target: Path,
    binding: dict | None,
    *,
    transaction_id: str,
    pending_dir: Path | None,
    claims_dir: Path | None,
) -> bool:
    """Retire hook authority only after the active pointer is committed."""
    if not isinstance(binding, dict):
        return False
    try:
        import turn_contract  # local import avoids a lifecycle import cycle
        return turn_contract.finalize_transition_claim(
            target,
            {"transition_claim": binding},
            pending_dir=pending_dir,
            claims_dir=claims_dir,
        )
    except (ImportError, RuntimeError) as exc:
        raise SetupTransactionError(
            "contract_claim_finalize_failed",
            f"committed transition claim cleanup failed: {exc}",
            run_dir=target,
            transaction_id=transaction_id,
        ) from exc


def _historical_transition_bindings(
    receipt: dict,
    *,
    include_create: bool = True,
    include_activation: bool = True,
) -> list[dict]:
    """Return immutable create/activation bindings in deterministic order."""
    candidates: list[object] = []
    if include_create:
        candidates.append(receipt.get("transition_claim"))
    attempt = receipt.get("activation_attempt")
    if include_activation and isinstance(attempt, dict):
        candidates.append(attempt.get("transition_claim"))
    bindings: list[dict] = []
    seen: set[str] = set()
    for candidate in candidates:
        if not isinstance(candidate, dict):
            continue
        try:
            digest = _sha256(json.dumps(
                candidate,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8"))
        except (TypeError, ValueError) as exc:
            raise SetupTransactionError(
                "invalid_transaction_receipt",
                f"historical transition binding is not canonical JSON: {exc}",
            ) from exc
        if digest not in seen:
            seen.add(digest)
            bindings.append(dict(candidate))
    return bindings


def _retire_historical_transition_claims(
    target: Path,
    receipt: dict,
    *,
    transaction_id: str,
    pending_dir: Path | None,
    claims_dir: Path | None,
    include_create: bool = True,
    include_activation: bool = True,
) -> bool:
    """Durably retire receipt-bound authority before selecting a fresh claim."""
    retired = False
    for binding in _historical_transition_bindings(
        receipt,
        include_create=include_create,
        include_activation=include_activation,
    ):
        retired = _finalize_hook_transition_claim(
            target,
            binding,
            transaction_id=transaction_id,
            pending_dir=pending_dir,
            claims_dir=claims_dir,
        ) or retired
    return retired


def _consume_exact_recovery_followup(
    target: Path,
    *,
    transaction_id: str,
    source_hash: str,
    effect: dict,
    pending_dir: Path | None,
    claims_dir: Path | None,
    pointer: Path,
    activation_profile: dict | None = None,
    expected: PointerSnapshot | None = None,
) -> bool:
    """Settle a fresh exact claim that arrived while an older effect recovered.

    A post-pointer activation crash may be followed by a new Claude prompt before
    the old nested attempt is terminalized.  Recovering only the old attempt would
    return success for the new command while leaving its claim live.  Claim the
    follow-up only after the old binding has been retired and only through the
    exact requested effect.  Activation follow-ups get their own recoverable
    nested attempt; an exact create follow-up is an idempotent reconciliation of
    the already-active transaction/source/profile identity.
    """
    contract = _claim_or_transfer_contract(
        target,
        target,
        transaction_id=transaction_id,
        source_hash=source_hash,
        pending_dir=pending_dir,
        claims_dir=claims_dir,
        effect=effect,
    )
    if not contract:
        return False

    if activation_profile is not None:
        if expected is None:
            raise SetupTransactionError(
                "invalid_activation_attempt",
                "activation follow-up recovery lacks a pointer snapshot",
                run_dir=target,
                transaction_id=transaction_id,
            )
        receipt = _read_receipt(target)
        _validate_activation_receipt(target, receipt)
        receipt["activation_attempt"] = _build_activation_attempt(
            target,
            receipt,
            profile=activation_profile,
            effect=effect,
            expected=expected,
            contract=contract,
        )
        _write_receipt(target, receipt)

    _finalize_hook_transition_claim(
        target,
        contract.get("transition_claim"),
        transaction_id=transaction_id,
        pending_dir=pending_dir,
        claims_dir=claims_dir,
    )
    if activation_profile is not None:
        _finalize_activation_attempt(
            target, recovered=False, pointer=pointer)
    return True


def _receipt_matches(
    receipt: dict,
    *,
    transaction_id: str,
    source_hash: str,
    allow_legacy: bool,
) -> bool:
    if not receipt:
        return allow_legacy and not transaction_id and not source_hash
    return (
        bool(transaction_id and source_hash)
        and receipt.get("transaction_id") == transaction_id
        and receipt.get("source_sha256") == source_hash
    )


def _finalize_receipt(
    run_dir: Path,
    *,
    recovered: bool,
    pointer: Path,
) -> dict:
    receipt = _read_receipt(run_dir)
    if not receipt:
        return {}
    receipt.update({
        "status": "recovered" if recovered else "committed",
        "active_pointer": str(pointer),
        "committed_at": time.time(),
    })
    if recovered:
        receipt["recovered_at"] = time.time()
    receipt.pop("last_error", None)
    _write_receipt(run_dir, receipt)
    return receipt


def commit_activation_cas(
    run_dir: Path,
    *,
    expected: PointerSnapshot,
    root: Path = ROOT,
    runs_root: Path = RUNS_ROOT,
    pointer: Path = ACTIVE_POINTER,
    transaction_id: str = "",
    source_hash: str = "",
    allow_legacy: bool = False,
    effect_profile: dict,
    required_files: tuple[str, ...] = DEFAULT_REQUIRED,
    pending_dir: Path | None = None,
    claims_dir: Path | None = None,
    fault: FaultInjector | None = None,
) -> TransactionResult:
    """Atomically select ``run_dir`` iff the pointer still matches ``expected``."""
    # Transition authority belongs to the selected repository root.  Falling
    # back to turn_contract's import-time global directories would let a fresh
    # pending turn in the real checkout contaminate an isolated clone, test
    # root, or temporary worktree that passed its own pointer/runs_root.
    if pending_dir is None:
        pending_dir = root / ".claude" / "xunji_pending_turns"
    if claims_dir is None:
        claims_dir = root / ".claude" / "xunji_transition_claims"
    target = _inside(run_dir, runs_root)
    if not target.is_dir():
        raise SetupTransactionError("missing_run", f"run does not exist: {target}")
    receipt = _read_receipt(target)
    _validate_activation_receipt(target, receipt)
    if not _receipt_matches(
        receipt,
        transaction_id=transaction_id,
        source_hash=source_hash,
        allow_legacy=allow_legacy,
    ):
        raise SetupTransactionError(
            "transaction_identity_mismatch",
            "prepared receipt does not match transaction/source identity",
            run_dir=target,
            transaction_id=transaction_id,
        )
    transaction_id = transaction_id or str(receipt.get("transaction_id") or "")
    source_hash = source_hash or str(receipt.get("source_sha256") or "")
    try:
        profile = validate_lifecycle_effect_profile(effect_profile)
    except ValueError as exc:
        raise SetupTransactionError(
            "invalid_effect_profile",
            f"lifecycle effect profile is invalid: {exc}",
            run_dir=target,
            transaction_id=transaction_id,
        ) from exc
    effect_kind = (
        "create" if profile["operation"] in CREATE_EFFECT_OPERATIONS else "activate"
    )
    if effect_kind == "create":
        if not receipt or receipt.get("effect_profile") != profile:
            raise SetupTransactionError(
                "effect_profile_mismatch",
                "create effect profile does not match the frozen setup receipt",
                run_dir=target,
                transaction_id=transaction_id,
            )
        source_manifest = _read_json(target / SOURCE_REL)
        source_section = source_manifest.get("source") \
            if isinstance(source_manifest.get("source"), dict) else {}
        source_reference = str(source_section.get("reference") or "")
    else:
        source_reference = ""
    try:
        effect = transition_effect(
            effect_kind,
            target.name,
            source_reference=source_reference,
            profile=profile,
        )
    except ValueError as exc:
        raise SetupTransactionError(
            "invalid_transition_effect",
            f"cannot derive exact lifecycle effect: {exc}",
            run_dir=target,
            transaction_id=transaction_id,
        ) from exc
    lock = pointer.parent / ACTIVATION_LOCK_NAME
    with exclusive_directory_lock(lock):
        # Activation receipts are mutable only through this lock.  Re-read the
        # current value after lock acquisition so a concurrent terminalization
        # cannot be overwritten by a stale pre-lock copy.
        receipt = _read_receipt(target)
        _validate_activation_receipt(target, receipt)
        if not _receipt_matches(
            receipt,
            transaction_id=transaction_id,
            source_hash=source_hash,
            allow_legacy=allow_legacy,
        ):
            raise SetupTransactionError(
                "transaction_identity_mismatch",
                "prepared receipt changed before activation lock acquisition",
                run_dir=target,
                transaction_id=transaction_id,
            )
        if effect_kind == "create" \
                and (not receipt or receipt.get("effect_profile") != profile):
            raise SetupTransactionError(
                "effect_profile_mismatch",
                "create effect profile changed before activation lock acquisition",
                run_dir=target,
                transaction_id=transaction_id,
            )
        _confirm_run_publish_durable(
            runs_root,
            run_dir=target,
            transaction_id=transaction_id,
        )
        current_snapshot = pointer_snapshot(pointer)
        current_target = _pointer_target(
            current_snapshot, root=root, runs_root=runs_root
        )
        receipt_status = str(receipt.get("status") or "")
        materialized_dangling_pointer = bool(
            effect_kind == "create"
            and _materialized_dangling_create_pointer(
                target, receipt, current_snapshot,
                root=root, runs_root=runs_root,
            )
        )
        pointer_already_committed = bool(
            current_target == target and not materialized_dangling_pointer)
        authority_origin = None if materialized_dangling_pointer else current_target
        needs_create_terminalization = receipt_status in {
            "prepared", "prepared_not_active",
        }
        has_immutable_create_binding = bool(
            receipt.get("contract_binding") is not None
            or receipt.get("transition_claim") is not None
        )
        # Receipt terminalization and authority retirement are distinct.  The
        # terminal receipt replace may be visible even when its directory fsync
        # failed before the historical create claim could be retired.  Only an
        # exact create retry may use that immutable top-level binding; a later
        # activation must leave historical create identity untouched.
        needs_create_binding_retirement = bool(
            pointer_already_committed
            and (
                needs_create_terminalization
                or (effect_kind == "create" and has_immutable_create_binding)
            )
        )
        pending_attempt = None
        attempt_value = receipt.get("activation_attempt") \
            if isinstance(receipt, dict) else None
        if isinstance(attempt_value, dict) \
                and attempt_value.get("status") == "pending":
            if effect_kind != "activate":
                raise SetupTransactionError(
                    "activation_attempt_mismatch",
                    "a create operation cannot replace a pending activation attempt",
                    run_dir=target,
                    transaction_id=transaction_id,
                )
            pending_attempt = _validate_activation_attempt(
                target, receipt, attempt_value, requested_effect=effect)
        if needs_create_terminalization \
                or needs_create_binding_retirement \
                or pending_attempt is not None:
            # A published prepared run can be mutated after its initial staging
            # validation.  A pending activation is equally unable to weaken
            # that frozen bundle, even when the outer create status is already
            # committed.
            _validate_setup_bundle(target, required_files)

        # A prior process may have completed ``replace`` but failed the parent
        # directory fsync before it could terminalize the receipt.  Seeing the
        # target bytes is not enough: recovery must execute the durability
        # barrier again before retiring authority or recording success.
        if pointer_already_committed:
            _confirm_active_pointer_durable(
                pointer,
                run_dir=target,
                transaction_id=transaction_id,
            )
            _confirm_receipt_durable(
                target,
                transaction_id=transaction_id,
            )
            if needs_create_binding_retirement:
                # Fully validate the immutable prepared-create identity before
                # deleting any receipt-bound authority.  A malformed recovery
                # receipt must not be able to retire a still-live claim.
                _validate_create_recovery_receipt(
                    target,
                    receipt,
                    source_hash=source_hash,
                    requested_transaction_id=transaction_id,
                )
            _retire_historical_transition_claims(
                target,
                receipt,
                transaction_id=transaction_id,
                pending_dir=pending_dir,
                claims_dir=claims_dir,
                include_create=needs_create_binding_retirement,
                include_activation=pending_attempt is not None,
            )

        if pending_attempt is not None:
            if pointer_already_committed:
                _invoke_fault(fault, "before_recovered_receipt")
                receipt = _finalize_activation_attempt(
                    target, recovered=True, pointer=pointer)
                _consume_exact_recovery_followup(
                    target,
                    transaction_id=transaction_id,
                    source_hash=source_hash,
                    effect=effect,
                    pending_dir=pending_dir,
                    claims_dir=claims_dir,
                    pointer=pointer,
                    activation_profile=profile,
                    expected=current_snapshot,
                )
                return TransactionResult(
                    target,
                    transaction_id,
                    source_hash,
                    "recovered",
                    recovered=True,
                )
            if not _activation_attempt_matches_snapshot(
                pending_attempt, current_snapshot
            ):
                raise SetupTransactionError(
                    "pointer_cas_mismatch",
                    "pointer no longer matches the pending activation attempt",
                    run_dir=target,
                    transaction_id=transaction_id,
                )
            if not _same_snapshot(current_snapshot, expected):
                raise SetupTransactionError(
                    "pointer_cas_mismatch",
                    "active pointer changed before activation retry",
                    run_dir=target,
                    transaction_id=transaction_id,
                )
            retry_contract = _claim_or_transfer_contract(
                current_target,
                target,
                transaction_id=transaction_id,
                source_hash=source_hash,
                pending_dir=pending_dir,
                claims_dir=claims_dir,
                effect=effect,
            )
            if not _activation_contract_matches_attempt(
                target, receipt, pending_attempt, retry_contract
            ):
                raise SetupTransactionError(
                    "activation_attempt_mismatch",
                    "retry hook binding does not match the pending activation attempt",
                    run_dir=target,
                    transaction_id=transaction_id,
                )
            _invoke_fault(fault, "before_pointer_replace")
            _write_active_pointer(
                pointer,
                (_pointer_ref(target, root) + "\n").encode("utf-8"),
                run_dir=target,
                transaction_id=transaction_id,
            )
            _invoke_fault(fault, "after_pointer_before_receipt")
            _finalize_hook_transition_claim(
                target,
                pending_attempt.get("transition_claim"),
                transaction_id=transaction_id,
                pending_dir=pending_dir,
                claims_dir=claims_dir,
            )
            _finalize_activation_attempt(
                target, recovered=True, pointer=pointer)
            return TransactionResult(
                target,
                transaction_id,
                source_hash,
                "recovered",
                recovered=True,
            )

        if pointer_already_committed:
            recovered_create = needs_create_binding_retirement
            if needs_create_terminalization:
                _invoke_fault(fault, "before_recovered_receipt")
                receipt = _finalize_receipt(target, recovered=True, pointer=pointer)
            if effect_kind == "create" and needs_create_binding_retirement:
                _consume_exact_recovery_followup(
                    target,
                    transaction_id=transaction_id,
                    source_hash=source_hash,
                    effect=effect,
                    pending_dir=pending_dir,
                    claims_dir=claims_dir,
                    pointer=pointer,
                )
                return TransactionResult(
                    target,
                    transaction_id,
                    source_hash,
                    "recovered",
                    recovered=True,
                )

            # An explicit selection of the already selected run is still a
            # new hook effect.  Consume and retire its exact claim, but store an
            # activation binding only below activation_attempt; the top-level
            # create identity is historical and never rewritten.
            same_target_contract = _claim_or_transfer_contract(
                current_target,
                target,
                transaction_id=transaction_id,
                source_hash=source_hash,
                pending_dir=pending_dir,
                claims_dir=claims_dir,
                effect=effect,
            )
            if receipt and same_target_contract and effect_kind == "activate":
                same_target_attempt = _build_activation_attempt(
                    target,
                    receipt,
                    profile=profile,
                    effect=effect,
                    expected=current_snapshot,
                    contract=same_target_contract,
                )
                receipt["activation_attempt"] = same_target_attempt
                _write_receipt(target, receipt)
            _finalize_hook_transition_claim(
                target,
                same_target_contract.get("transition_claim")
                if same_target_contract else None,
                transaction_id=transaction_id,
                pending_dir=pending_dir,
                claims_dir=claims_dir,
            )
            if receipt and same_target_contract and effect_kind == "activate":
                _finalize_activation_attempt(
                    target, recovered=False, pointer=pointer)
            return TransactionResult(
                target, transaction_id, source_hash,
                "recovered" if recovered_create else "committed",
                recovered=recovered_create,
            )
        if not _same_snapshot(current_snapshot, expected):
            if receipt:
                if receipt.get("status") in {"prepared", "prepared_not_active"}:
                    receipt["status"] = "prepared_not_active"
                receipt["last_error"] = \
                    "active pointer compare-and-swap mismatch"
                receipt["observed_pointer_sha256"] = current_snapshot.sha256
                _write_receipt(target, receipt)
            raise SetupTransactionError(
                "pointer_cas_mismatch",
                "active pointer changed during setup; prepared run was not activated",
                run_dir=target,
                transaction_id=transaction_id,
            )

        contract = _claim_or_transfer_contract(
            authority_origin,
            target,
            transaction_id=transaction_id,
            source_hash=source_hash,
            pending_dir=pending_dir,
            claims_dir=claims_dir,
            effect=effect,
        )
        if receipt and effect_kind == "create" and contract:
            source = _read_json(target / SOURCE_REL)
            if source.get("schema") == SOURCE_SCHEMA:
                try:
                    setup_source.bind_operator_prompt(
                        target, contract, source_hash=source_hash
                    )
                except setup_source.SetupSourceError as exc:
                    raise SetupTransactionError(
                        exc.code,
                        f"operator source binding failed: {exc}",
                        run_dir=target,
                        transaction_id=transaction_id,
                    ) from exc
            receipt["contract_binding"] = {
                "session_id": str(contract.get("session_id") or ""),
                "prompt_sha256": str(contract.get("prompt_sha256") or ""),
                "source_sha256": source_hash,
                "transaction_id": transaction_id,
                "expected_run": target.name,
            }
            receipt["transition_claim"] = contract.get("transition_claim")
            _write_receipt(target, receipt)
        elif receipt and effect_kind == "activate":
            receipt["activation_attempt"] = _build_activation_attempt(
                target,
                receipt,
                profile=profile,
                effect=effect,
                expected=current_snapshot,
                contract=contract,
            )
            _write_receipt(target, receipt)

        _invoke_fault(fault, "before_pointer_replace")
        _write_active_pointer(
            pointer,
            (_pointer_ref(target, root) + "\n").encode("utf-8"),
            run_dir=target,
            transaction_id=transaction_id,
        )
        _invoke_fault(fault, "after_pointer_before_receipt")
        if effect_kind == "create":
            _finalize_receipt(target, recovered=False, pointer=pointer)
            _finalize_hook_transition_claim(
                target,
                contract.get("transition_claim") if contract else None,
                transaction_id=transaction_id,
                pending_dir=pending_dir,
                claims_dir=claims_dir,
            )
        else:
            _finalize_hook_transition_claim(
                target,
                contract.get("transition_claim") if contract else None,
                transaction_id=transaction_id,
                pending_dir=pending_dir,
                claims_dir=claims_dir,
            )
            if receipt:
                _finalize_activation_attempt(
                    target, recovered=False, pointer=pointer)
        return TransactionResult(target, transaction_id, source_hash, "committed")


def activate_existing_run(
    run_dir: Path,
    *,
    operation: object = _OPERATION_OMITTED,
    root: Path = ROOT,
    runs_root: Path = RUNS_ROOT,
    pointer: Path = ACTIVE_POINTER,
    required_files: tuple[str, ...] = DEFAULT_REQUIRED,
    pending_dir: Path | None = None,
    claims_dir: Path | None = None,
    fault: FaultInjector | None = None,
) -> TransactionResult:
    """Resume/set-active path through the same pointer CAS and receipt recovery.

    Only a truly omitted argument preserves the committed
    ``xunji_statusline.py`` adapter.  Explicit ``None``/empty/unknown values are
    invalid rather than silently inheriting statusline authority.  New adapters
    and transaction-internal callers must pass their exact operation explicitly.
    """
    if pending_dir is None:
        pending_dir = root / ".claude" / "xunji_pending_turns"
    if claims_dir is None:
        claims_dir = root / ".claude" / "xunji_transition_claims"
    receipt = _read_receipt(run_dir)
    if operation is _OPERATION_OMITTED:
        normalized_operation = OP_STATUSLINE_SET_ACTIVE
    elif not isinstance(operation, str) or not operation:
        raise SetupTransactionError(
            "invalid_effect_profile",
            "activation adapter operation must be a non-empty explicit string",
            run_dir=run_dir,
        )
    else:
        normalized_operation = operation
    try:
        effect_profile = lifecycle_effect_profile(
            normalized_operation, run_dir.name)
    except ValueError as exc:
        raise SetupTransactionError(
            "invalid_effect_profile",
            f"activation adapter operation is invalid: {exc}",
            run_dir=run_dir,
        ) from exc
    return commit_activation_cas(
        run_dir,
        expected=pointer_snapshot(pointer),
        root=root,
        runs_root=runs_root,
        pointer=pointer,
        transaction_id=str(receipt.get("transaction_id") or ""),
        source_hash=str(receipt.get("source_sha256") or ""),
        allow_legacy=not bool(receipt),
        effect_profile=effect_profile,
        required_files=required_files,
        pending_dir=pending_dir,
        claims_dir=claims_dir,
        fault=fault,
    )


def clear_activation_cas(
    *,
    expected: PointerSnapshot,
    pointer: Path = ACTIVE_POINTER,
    root: Path = ROOT,
    runs_root: Path = RUNS_ROOT,
    session_id: str = "",
    transcript_sha256: str = "",
    contract_sha256: str = "",
    selection_dir: Path | None = None,
    on_owned_clear: OwnedClearCallback | None = None,
    session_cleanup: Callable[[], None] | None = None,
    lock_timeout: float = 10.0,
    fault: FaultInjector | None = None,
) -> bool:
    """Clear the pointer under the activation lock with optional session receipt.

    SessionEnd cleanup supplies both ``session_id`` and the exact active turn-
    contract digest observed before entering the lock.  The transaction owner
    rechecks pointer + contract together before invoking ``on_owned_clear``.
    That callback must replace executable authority with a mechanically safe
    ``session_ended`` EXPLAIN contract.  Only then is a session-selection receipt
    written and the pointer removed.  Callers cannot supply receipt contents.
    """
    session_parts = (
        contract_sha256, transcript_sha256, selection_dir,
        on_owned_clear, session_cleanup,
    )
    if session_id and (
            not _valid_sha256(contract_sha256)
            or not _valid_sha256(transcript_sha256)
            or selection_dir is None
            or on_owned_clear is None
            or session_cleanup is None) \
            or not session_id and any(part is not None and part != ""
                                      for part in session_parts):
        raise SetupTransactionError(
            "invalid_clear_attestation",
            "session-bound clear requires session/transcript/contract identity, "
            "a selection directory, and both ownership callbacks",
        )
    selection_root = _selection_dir_inside_pointer(
        selection_dir, pointer) if selection_dir is not None else None
    with exclusive_directory_lock(
            pointer.parent / ACTIVATION_LOCK_NAME, timeout=lock_timeout):
        current = pointer_snapshot(pointer)
        if not _same_snapshot(current, expected):
            raise SetupTransactionError(
                "pointer_cas_mismatch", "active pointer changed before clear"
            )
        if not current.exists:
            return False
        if session_id:
            target = _pointer_target(current, root=root, runs_root=runs_root)
            if target is None:
                raise SetupTransactionError(
                    "session_owner_mismatch",
                    "active pointer has no valid session-owned run",
                )
            contract_path = target / "state" / "turn_contract.json"
            try:
                raw_contract = contract_path.read_bytes()
                contract = json.loads(raw_contract.decode("utf-8", "strict"))
            except (OSError, UnicodeError, json.JSONDecodeError) as exc:
                raise SetupTransactionError(
                    "session_owner_mismatch",
                    "active run contract is unavailable for session-bound clear",
                    run_dir=target,
                ) from exc
            contract_transcript = str(contract.get("transcript_path") or "") \
                if isinstance(contract, dict) else ""
            if _sha256(raw_contract) != contract_sha256 \
                    or not isinstance(contract, dict) \
                    or contract.get("schema") != TURN_CONTRACT_SCHEMA \
                    or str(contract.get("session_id") or "") != session_id \
                    or str(contract.get("bound_run") or "") != target.name \
                    or not contract_transcript \
                    or _sha256(contract_transcript.encode("utf-8", "replace")) \
                    != transcript_sha256 \
                    or not re.fullmatch(
                        r"[0-9a-f]{64}",
                        str(contract.get("prompt_sha256") or ""),
                    ):
                raise SetupTransactionError(
                    "session_owner_mismatch",
                    "active run contract changed or belongs to another session",
                    run_dir=target,
                )
            prior_state = str(contract.get("authority_state") or "")
            if prior_state == "session_ended":
                active_contract_sha = str(
                    contract.get("ended_from_contract_sha256") or "")
                if not _valid_sha256(active_contract_sha):
                    raise SetupTransactionError(
                        "session_owner_mismatch",
                        "ended session contract lost its prior authority identity",
                        run_dir=target,
                    )
            else:
                active_contract_sha = contract_sha256
            selection_path = session_selection_path(
                selection_root, session_id)  # type: ignore[arg-type]
            prior_selection: dict | None = None
            prior_selection_raw = b""
            if selection_path.exists():
                try:
                    prior_selection_raw = selection_path.read_bytes()
                    prior_value = json.loads(
                        prior_selection_raw.decode("utf-8", "strict"))
                except (OSError, UnicodeError, json.JSONDecodeError) as exc:
                    raise SetupTransactionError(
                        "session_selection_mismatch",
                        "existing session selection receipt is unreadable",
                        run_dir=target,
                    ) from exc
                prior_selection = validate_session_selection(
                    prior_value if isinstance(prior_value, dict) else {})
                current_identity = _run_identity(target, root=root)
                preflight = {
                    "session_id_sha256": _sha256(
                        session_id.encode("utf-8", "replace")),
                    "transcript_sha256": transcript_sha256,
                    **current_identity,
                    "pointer_sha256": current.sha256,
                    "active_contract_sha256": active_contract_sha,
                }
                preflight_keys = tuple(preflight)
                if prior_selection.get("status") != "prepared" or any(
                        prior_selection.get(key) != preflight[key]
                        for key in preflight_keys):
                    raise SetupTransactionError(
                        "session_selection_mismatch",
                        "existing session selection belongs to another clear",
                        run_dir=target,
                    )
            callback_result = on_owned_clear(target, raw_contract, contract)
            ended_raw, ended_contract = _callback_contract(
                target, callback_result)
            _validate_safe_session_contract(
                ended_contract,
                session_id=session_id,
                transcript_sha256=transcript_sha256,
                target=target,
                authority_state="session_ended",
                active_contract_sha256=active_contract_sha,
            )
            if not _same_snapshot(pointer_snapshot(pointer), current):
                raise SetupTransactionError(
                    "pointer_cas_mismatch",
                    "active pointer changed during owned SessionEnd callback",
                    run_dir=target,
                )
            _invoke_fault(fault, "after_owned_clear")
            selection = _build_session_selection(
                session_id=session_id,
                transcript_sha256=transcript_sha256,
                target=target,
                root=root,
                pointer_snapshot_value=current,
                active_contract_sha256=active_contract_sha,
                ended_contract_sha256=_sha256(ended_raw),
            )
            if prior_selection is not None:
                try:
                    prior_unchanged = selection_path.read_bytes() \
                        == prior_selection_raw
                except OSError:
                    prior_unchanged = False
                if not prior_unchanged \
                        or not _same_selection_binding(
                            prior_selection, selection):
                    raise SetupTransactionError(
                        "session_selection_mismatch",
                        "existing session selection changed or has another binding",
                        run_dir=target,
                    )
                selection = prior_selection
                selection_raw = prior_selection_raw
            else:
                _atomic_json(selection_path, selection)
                selection_raw = selection_path.read_bytes()
            _invoke_fault(fault, "after_session_selection")
            session_cleanup()
            if not _same_snapshot(pointer_snapshot(pointer), current):
                selection_path.unlink(missing_ok=True)
                _fsync_dir(selection_path.parent)
                raise SetupTransactionError(
                    "pointer_cas_mismatch",
                    "active pointer changed during SessionEnd authority cleanup",
                    run_dir=target,
                )
            try:
                selection_unchanged = selection_path.read_bytes() == selection_raw
            except OSError:
                selection_unchanged = False
            if not selection_unchanged:
                raise SetupTransactionError(
                    "session_selection_mismatch",
                    "session selection changed during authority cleanup",
                    run_dir=target,
                )
            try:
                ended_contract_unchanged = contract_path.read_bytes() == ended_raw
            except OSError:
                ended_contract_unchanged = False
            if not ended_contract_unchanged:
                selection_path.unlink(missing_ok=True)
                _fsync_dir(selection_path.parent)
                raise SetupTransactionError(
                    "invalid_resume_barrier",
                    "ended-session contract changed during authority cleanup",
                    run_dir=target,
                )
            _invoke_fault(fault, "after_session_cleanup")
        pointer.unlink()
        _fsync_dir(pointer.parent)
        _invoke_fault(fault, "after_session_pointer_clear")
        if session_id:
            _write_selection_status(selection_path, selection, "cleared")
            _invoke_fault(fault, "after_session_selection_cleared")
        return True


def restore_session_activation_cas(
    *,
    session_id: str,
    transcript_sha256: str,
    selection_dir: Path,
    on_resume_barrier: ResumeBarrierCallback,
    pointer: Path = ACTIVE_POINTER,
    root: Path = ROOT,
    runs_root: Path = RUNS_ROOT,
    lock_timeout: float = 10.0,
    fault: FaultInjector | None = None,
) -> bool:
    """Restore one exact session selection without reviving old turn authority.

    The run comes only from the content-addressed session receipt; this function
    never scans ``runs/``.  A caller-provided callback must first persist an
    EXPLAIN-only ``resume_barrier`` contract bound to this receipt.  The pointer
    is written only after that barrier is re-read and mechanically validated.
    """
    if not session_id or not _valid_sha256(transcript_sha256) \
            or not callable(on_resume_barrier):
        raise SetupTransactionError(
            "invalid_session_resume",
            "session resume requires exact session/transcript identity and a barrier callback",
        )
    selection_root = _selection_dir_inside_pointer(selection_dir, pointer)
    selection_path = session_selection_path(selection_root, session_id)
    with exclusive_directory_lock(
            pointer.parent / ACTIVATION_LOCK_NAME, timeout=lock_timeout):
        current = pointer_snapshot(pointer)
        if not selection_path.exists():
            # A successful prior attempt consumes its receipt.  A repeated hook
            # may acknowledge the already-installed safe barrier, but cannot
            # select or overwrite anything without a receipt.
            current_target = _pointer_target(
                current, root=root, runs_root=runs_root)
            if current_target is None:
                raise SetupTransactionError(
                    "session_selection_missing",
                    "no resumable selection exists for this session",
                )
            try:
                raw_barrier = (
                    current_target / "state" / "turn_contract.json").read_bytes()
                barrier = json.loads(raw_barrier.decode("utf-8", "strict"))
            except (OSError, UnicodeError, json.JSONDecodeError) as exc:
                raise SetupTransactionError(
                    "session_selection_missing",
                    "existing pointer has no valid consumed resume barrier",
                    run_dir=current_target,
                ) from exc
            barrier_selection = str(
                barrier.get("resume_selection_sha256") or "") \
                if isinstance(barrier, dict) else ""
            _validate_safe_session_contract(
                barrier if isinstance(barrier, dict) else {},
                session_id=session_id,
                transcript_sha256=transcript_sha256,
                target=current_target,
                authority_state="resume_barrier",
                selection_sha256=barrier_selection,
            )
            _confirm_session_selection_absence_durable(
                selection_path,
                run_dir=current_target,
                transaction_id="",
            )
            return True

        try:
            selection_raw = selection_path.read_bytes()
            selection_value = json.loads(selection_raw.decode("utf-8", "strict"))
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            raise SetupTransactionError(
                "invalid_session_selection",
                "session selection receipt is unreadable",
            ) from exc
        selection = validate_session_selection(
            selection_value if isinstance(selection_value, dict) else {})
        if selection["session_id_sha256"] != _sha256(
                session_id.encode("utf-8", "replace")) \
                or selection["transcript_sha256"] != transcript_sha256:
            raise SetupTransactionError(
                "session_selection_mismatch",
                "session resume does not own this selection receipt",
            )
        target = _selection_target(
            selection, root=root, runs_root=runs_root)
        current_target = _pointer_target(
            current, root=root, runs_root=runs_root)
        if current.exists and current_target != target:
            raise SetupTransactionError(
                "pointer_cas_mismatch",
                "another active pointer wins over automatic session resume",
                run_dir=target,
            )
        if current.exists and current_target == target:
            allowed_pointer_hashes = {
                str(selection["pointer_sha256"]),
                _sha256((str(selection["run_ref"]) + "\n").encode("utf-8")),
            }
            if current.sha256 not in allowed_pointer_hashes:
                raise SetupTransactionError(
                    "pointer_cas_mismatch",
                    "same-run pointer bytes do not match this selection",
                    run_dir=target,
                )

        contract_path = target / "state" / "turn_contract.json"
        try:
            before_raw = contract_path.read_bytes()
            before_contract = json.loads(before_raw.decode("utf-8", "strict"))
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            raise SetupTransactionError(
                "invalid_resume_barrier",
                "selected run has no valid ended-session contract",
                run_dir=target,
            ) from exc
        if not isinstance(before_contract, dict):
            raise SetupTransactionError(
                "invalid_resume_barrier",
                "selected run contract is not an object",
                run_dir=target,
            )
        before_state = str(before_contract.get("authority_state") or "")
        if before_state == "session_ended":
            if _sha256(before_raw) != selection["ended_contract_sha256"]:
                raise SetupTransactionError(
                    "session_selection_mismatch",
                    "ended contract changed after session selection",
                    run_dir=target,
                )
            _validate_safe_session_contract(
                before_contract,
                session_id=session_id,
                transcript_sha256=transcript_sha256,
                target=target,
                authority_state="session_ended",
                active_contract_sha256=str(
                    selection["active_contract_sha256"]),
            )
            callback_result = on_resume_barrier(target, selection)
            _barrier_raw, barrier_contract = _callback_contract(
                target, callback_result)
            _validate_safe_session_contract(
                barrier_contract,
                session_id=session_id,
                transcript_sha256=transcript_sha256,
                target=target,
                authority_state="resume_barrier",
                active_contract_sha256=str(
                    selection["active_contract_sha256"]),
                selection_sha256=str(selection["receipt_sha256"]),
            )
        elif before_state == "resume_barrier":
            barrier_contract = before_contract
            _validate_safe_session_contract(
                barrier_contract,
                session_id=session_id,
                transcript_sha256=transcript_sha256,
                target=target,
                authority_state="resume_barrier",
                active_contract_sha256=str(
                    selection["active_contract_sha256"]),
                selection_sha256=str(selection["receipt_sha256"]),
            )
        else:
            raise SetupTransactionError(
                "invalid_resume_barrier",
                "automatic resume cannot reuse an executable turn contract",
                run_dir=target,
            )
        if not _same_snapshot(pointer_snapshot(pointer), current):
            raise SetupTransactionError(
                "pointer_cas_mismatch",
                "active pointer changed during resume barrier callback",
                run_dir=target,
            )
        try:
            selection_unchanged = selection_path.read_bytes() == selection_raw
        except OSError:
            selection_unchanged = False
        if not selection_unchanged:
            raise SetupTransactionError(
                "session_selection_mismatch",
                "session selection changed during resume barrier callback",
                run_dir=target,
            )
        _invoke_fault(fault, "after_resume_barrier")
        if not current.exists:
            _write_active_pointer(
                pointer,
                (str(selection["run_ref"]) + "\n").encode("utf-8"),
                run_dir=target,
                transaction_id=str(selection.get("transaction_id") or ""),
            )
        else:
            # A prior restore may have replaced the pointer and failed only its
            # directory barrier.  Keep the selection receipt until a retry
            # confirms that barrier instead of consuming recovery authority.
            _confirm_active_pointer_durable(
                pointer,
                run_dir=target,
                transaction_id=str(selection.get("transaction_id") or ""),
            )
        _invoke_fault(fault, "after_resume_pointer")
        _consume_session_selection_durable(
            selection_path,
            run_dir=target,
            transaction_id=str(selection.get("transaction_id") or ""),
        )
        _invoke_fault(fault, "after_resume_selection_consume")
        return True


def _recover_existing(
    final_dir: Path,
    *,
    source_hash: str,
    effect_profile: dict,
    requested_transaction_id: str,
    required_files: tuple[str, ...],
    root: Path,
    runs_root: Path,
    pointer: Path,
    pending_dir: Path | None,
    claims_dir: Path | None,
) -> TransactionResult | None:
    # Lock order is always setup -> activation.  Recovery must not inspect the
    # canonical pointer under only the setup lock while set-active/resume can
    # concurrently commit under the activation lock.
    with exclusive_directory_lock(pointer.parent / ACTIVATION_LOCK_NAME):
        receipt = _read_receipt(final_dir)
        _validate_activation_receipt(final_dir, receipt)
        if not receipt or receipt.get("source_sha256") != source_hash:
            return None
        if receipt.get("effect_profile") != effect_profile:
            raise SetupTransactionError(
                "effect_profile_mismatch",
                "recovery adapter/options do not match the frozen create effect",
                run_dir=final_dir,
                transaction_id=str(receipt.get("transaction_id") or ""),
            )
        receipt_txid = str(receipt.get("transaction_id") or "")
        if requested_transaction_id and requested_transaction_id != receipt_txid:
            raise SetupTransactionError(
                "transaction_identity_mismatch",
                "recovery transaction id does not match the requested transaction",
                run_dir=final_dir,
                transaction_id=receipt_txid,
            )
        current = pointer_snapshot(pointer)
        if _pointer_target(
            current, root=root, runs_root=runs_root
        ) != final_dir.resolve():
            return None
        if _materialized_dangling_create_pointer(
            final_dir.resolve(), receipt, current,
            root=root, runs_root=runs_root,
        ):
            # The unchanged pointer only became resolvable because this run was
            # published.  No pointer commit or contract transfer has happened;
            # let commit_activation_cas bind the frozen no-origin claim first.
            return None
        _confirm_active_pointer_durable(
            pointer,
            run_dir=final_dir,
            transaction_id=receipt_txid,
        )
        _confirm_receipt_durable(
            final_dir,
            transaction_id=receipt_txid,
        )
        _validate_setup_bundle(final_dir, required_files)
        activation_attempt = receipt.get("activation_attempt")
        if isinstance(activation_attempt, dict) \
                and activation_attempt.get("status") == "pending":
            activation_attempt = _validate_activation_attempt(
                final_dir, receipt, activation_attempt)
        if receipt.get("status") in {"prepared", "prepared_not_active"}:
            _validate_create_recovery_receipt(
                final_dir,
                receipt,
                source_hash=source_hash,
                requested_transaction_id=requested_transaction_id,
            )

        # Historical create and nested-activation bindings are immutable receipt
        # identity.  Retire every such claim before looking for a fresh command;
        # otherwise a new claim can be mistaken for the old effect's origin.
        _retire_historical_transition_claims(
            final_dir,
            receipt,
            transaction_id=receipt_txid,
            pending_dir=pending_dir,
            claims_dir=claims_dir,
        )

        if isinstance(activation_attempt, dict) \
                and activation_attempt.get("status") == "pending":
            receipt = _finalize_activation_attempt(
                final_dir, recovered=True, pointer=pointer)

        # A create command can arrive after a prior activation wrote the pointer
        # but before that activation receipt was terminalized.  Once the old
        # attempt is recovered, settle only a fresh claim for this exact create
        # adapter/source/profile.  The same path also makes a crash after claiming
        # that follow-up retryable without accepting a different operation.
        if receipt.get("status") in {"prepared", "prepared_not_active"}:
            receipt = _finalize_receipt(final_dir, recovered=True, pointer=pointer)

        source_manifest = _read_json(final_dir / SOURCE_REL)
        source_section = source_manifest.get("source") \
            if isinstance(source_manifest.get("source"), dict) else {}
        try:
            create_effect = transition_effect(
                "create",
                final_dir.name,
                source_reference=str(source_section.get("reference") or ""),
                profile=effect_profile,
            )
        except ValueError as exc:
            raise SetupTransactionError(
                "invalid_transition_effect",
                f"cannot derive exact create recovery effect: {exc}",
                run_dir=final_dir,
                transaction_id=receipt_txid,
            ) from exc
        _consume_exact_recovery_followup(
            final_dir,
            transaction_id=receipt_txid,
            source_hash=source_hash,
            effect=create_effect,
            pending_dir=pending_dir,
            claims_dir=claims_dir,
            pointer=pointer,
        )
        return TransactionResult(
            final_dir,
            receipt_txid,
            source_hash,
            "recovered",
            recovered=True,
        )
    return None


def create_and_activate(
    run_name: str,
    *,
    source_manifest: dict,
    build: BuildRun,
    effect_profile: dict | None = None,
    validate_source: SourceValidator | None = None,
    root: Path = ROOT,
    runs_root: Path = RUNS_ROOT,
    pointer: Path = ACTIVE_POINTER,
    required_files: tuple[str, ...] = DEFAULT_REQUIRED,
    transaction_id: str | None = None,
    pending_dir: Path | None = None,
    claims_dir: Path | None = None,
    fault: FaultInjector | None = None,
) -> TransactionResult:
    """Prepare, publish, and activate one run as a recoverable transaction."""
    if pending_dir is None:
        pending_dir = root / ".claude" / "xunji_pending_turns"
    if claims_dir is None:
        claims_dir = root / ".claude" / "xunji_transition_claims"
    _validate_run_name(run_name)
    source = dict(source_manifest)
    try:
        setup_source.validate_manifest(source)
    except setup_source.SetupSourceError as exc:
        raise SetupTransactionError(exc.code, str(exc)) from exc
    source_hash = str(source.get("source_sha256") or "")
    if not re.fullmatch(r"[0-9a-f]{64}", source_hash):
        raise SetupTransactionError("invalid_source_hash", "source hash must be sha256")
    try:
        profile = validate_lifecycle_effect_profile(
            effect_profile, expected_kind="create")
    except ValueError as exc:
        raise SetupTransactionError(
            "invalid_effect_profile",
            f"current-schema create requires a valid effect profile: {exc}",
        ) from exc
    _validate_create_effect_profile(None, source, profile)
    requested_txid = transaction_id or ""
    txid = requested_txid or uuid.uuid4().hex
    if not re.fullmatch(r"[0-9a-f]{32}", txid):
        raise SetupTransactionError("invalid_transaction_id", "transaction id is invalid")

    runs_root.mkdir(parents=True, exist_ok=True)
    final_dir = _inside(runs_root / run_name, runs_root)
    initial_pointer = pointer_snapshot(pointer)
    initial_origin = _pointer_target(
        initial_pointer, root=root, runs_root=runs_root)
    setup_lock = runs_root / SETUP_LOCK_NAME
    staging_parent = runs_root / STAGING_NAME
    staging_dir = staging_parent / f"{run_name}.{txid}"
    renamed = False

    with exclusive_directory_lock(setup_lock):
        if final_dir.exists():
            recovered = _recover_existing(
                final_dir,
                source_hash=source_hash,
                effect_profile=profile,
                requested_transaction_id=requested_txid,
                required_files=required_files,
                root=root,
                runs_root=runs_root,
                pointer=pointer,
                pending_dir=pending_dir,
                claims_dir=claims_dir,
            )
            if recovered is not None:
                return recovered
            receipt = _read_receipt(final_dir)
            if receipt.get("status") in {"prepared", "prepared_not_active"} \
                    and receipt.get("source_sha256") == source_hash:
                receipt_txid = str(receipt.get("transaction_id") or "")
                if requested_txid and requested_txid == receipt_txid:
                    return commit_activation_cas(
                        final_dir,
                        expected=pointer_snapshot(pointer),
                        root=root,
                        runs_root=runs_root,
                        pointer=pointer,
                        transaction_id=receipt_txid,
                        source_hash=source_hash,
                        effect_profile=profile,
                        required_files=required_files,
                        pending_dir=pending_dir,
                        claims_dir=claims_dir,
                        fault=fault,
                    )
                raise SetupTransactionError(
                    "prepared_not_active",
                    "matching run is fully prepared but not active; explicitly resume it "
                    "or retry with its transaction id",
                    run_dir=final_dir,
                    transaction_id=str(receipt.get("transaction_id") or ""),
                )
            raise SetupTransactionError(
                "run_exists",
                "run already exists; resume it, choose another date, or choose another slug",
                run_dir=final_dir,
            )
        if staging_dir.exists():
            shutil.rmtree(staging_dir)
        staging_parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        try:
            _invoke_fault(fault, "before_build")
            build(staging_dir, fault)
            if validate_source is not None:
                validate_source()
            _invoke_fault(fault, "source_manifest")
            _atomic_json(staging_dir / SOURCE_REL, source)
            receipt = {
                "schema": RECEIPT_SCHEMA,
                "transaction_id": txid,
                "run_name": run_name,
                "source_sha256": source_hash,
                "effect_profile": profile,
                "activation_attempt": None,
                "status": "prepared",
                "prepared_at": time.time(),
                "expected_pointer": {
                    "exists": initial_pointer.exists,
                    "sha256": initial_pointer.sha256,
                },
                "expected_origin_valid": initial_origin is not None,
                "expected_origin_run": initial_origin.name
                if initial_origin is not None else "",
            }
            _invoke_fault(fault, "prepared_receipt")
            _write_receipt(staging_dir, receipt)
            _validate_prepared_run(staging_dir, required_files)
            # Publish intent is recorded while the directory is still hidden.
            # Therefore the first instant the atomic rename makes it visible,
            # its receipt is already explainable as prepared_not_active; there
            # is no published `prepared` crash window.
            receipt.update({
                "status": "prepared_not_active",
                "publish_intent_at": time.time(),
            })
            _write_receipt(staging_dir, receipt)
            _invoke_fault(fault, "before_atomic_rename")
            _invoke_fault(fault, "atomic_rename")
            staging_dir.rename(final_dir)
            renamed = True
            _confirm_run_publish_durable(
                runs_root,
                run_dir=final_dir,
                transaction_id=txid,
            )
            _invoke_fault(fault, "after_atomic_rename")
            _invoke_fault(fault, "before_pointer_cas")
            return commit_activation_cas(
                final_dir,
                expected=initial_pointer,
                root=root,
                runs_root=runs_root,
                pointer=pointer,
                transaction_id=txid,
                source_hash=source_hash,
                effect_profile=profile,
                required_files=required_files,
                pending_dir=pending_dir,
                claims_dir=claims_dir,
                fault=fault,
            )
        except SetupTransactionError:
            raise
        except Exception as exc:
            location = final_dir if renamed else staging_dir
            raise SetupTransactionError(
                "transaction_failed",
                f"setup transaction failed: {exc.__class__.__name__}: {exc}",
                run_dir=location,
                transaction_id=txid,
            ) from exc
        finally:
            if not renamed:
                shutil.rmtree(staging_dir, ignore_errors=True)
            try:
                staging_parent.rmdir()
            except OSError:
                pass


def _minimal_builder(run_dir: Path, fault: FaultInjector | None) -> None:
    for stage in ("ingest", "coverage", "asset_ledger", "journal", "loop_state"):
        _invoke_fault(fault, stage)
    (run_dir / "classify").mkdir(parents=True)
    (run_dir / "state").mkdir(parents=True)
    (run_dir / "target.md").write_text("# Target\n", encoding="utf-8")
    (run_dir / "classify" / "coverage.json").write_text(
        json.dumps({"assets": [{"host": "example.test"}]}), encoding="utf-8"
    )
    for name in (
        "asset_ledger.json", "session_state.json", "loop_state.json",
        "progress_ledger.json", "controller.shadow.json",
    ):
        (run_dir / "state" / name).write_text("{}\n", encoding="utf-8")
    source, source_bytes = setup_source.normalize_url("https://example.test/")
    setup_source.write_bundle(run_dir, source, source_bytes)


def _selftest() -> int:
    fixture = ROOT / "tools" / "harness" / "fixtures" / "setup-transaction.json"
    spec = json.loads(fixture.read_text(encoding="utf-8"))
    temp = Path(tempfile.mkdtemp(prefix="xunji-setup-transaction-"))
    root = temp / "project"
    runs = root / "runs"
    pointer = root / ".claude" / "xunji_active_run"
    required = (
        "target.md", "classify/coverage.json", "state/asset_ledger.json",
        "state/session_state.json", "state/loop_state.json",
        "state/progress_ledger.json", "state/controller.shadow.json",
        str(SOURCE_REL), str(RECEIPT_REL), str(setup_source.NORMALIZED_REL),
        str(setup_source.VALIDATOR_REL),
    )
    source, source_bytes = setup_source.normalize_url("https://example.test/")
    alternate_source, alternate_source_bytes = setup_source.normalize_url(
        "https://alternate.example.test/"
    )
    source_hash = str(source["source_sha256"])

    def test_create_profile(run_name: str, manifest: dict = source) -> dict:
        return lifecycle_effect_profile(
            OP_TRANSACTION_CREATE,
            run_name,
            source_type=str(manifest["source"]["kind"]),
        )

    real_create_and_activate = globals()["create_and_activate"]

    def create_and_activate(run_name: str, **kwargs) -> TransactionResult:
        """Selftest adapter supplies the same explicit profile as real adapters."""
        manifest = kwargs.get("source_manifest")
        kwargs.setdefault("effect_profile", test_create_profile(run_name, manifest))
        return real_create_and_activate(run_name, **kwargs)

    def test_create_effect(run_name: str, manifest: dict = source) -> dict:
        return transition_effect(
            "create",
            run_name,
            source_reference=str(manifest["source"]["reference"]),
            profile=test_create_profile(run_name, manifest),
        )

    def test_activate_effect(
        run_name: str,
        operation: str = OP_TRANSACTION_ACTIVATE,
    ) -> dict:
        return transition_effect(
            "activate",
            run_name,
            profile=lifecycle_effect_profile(operation, run_name),
        )

    def builder_for(manifest: dict, raw: bytes) -> BuildRun:
        def build(run_dir: Path, fault: FaultInjector | None) -> None:
            _minimal_builder(run_dir, fault)
            setup_source.write_bundle(run_dir, manifest, raw)
        return build

    def seed_published_recovery(run_name: str) -> tuple[Path, dict]:
        """Create a post-rename/post-pointer candidate without invoking recovery."""
        run_dir = runs / run_name
        builder_for(source, source_bytes)(run_dir, None)
        _atomic_json(run_dir / SOURCE_REL, source)
        previous = pointer_snapshot(pointer)
        receipt = {
            "schema": RECEIPT_SCHEMA,
            "transaction_id": uuid.uuid4().hex,
            "run_name": run_name,
            "source_sha256": source_hash,
            "effect_profile": test_create_profile(run_name),
            "status": "prepared_not_active",
            "prepared_at": time.time(),
            "publish_intent_at": time.time(),
            "expected_pointer": {
                "exists": previous.exists,
                "sha256": previous.sha256,
            },
        }
        _write_receipt(run_dir, receipt)
        _atomic_write(pointer, (_pointer_ref(run_dir, root) + "\n").encode("utf-8"))
        return run_dir, _read_receipt(run_dir)

    def seed_formal_run(
        run_name: str,
        *,
        status: str,
        expected_pointer: PointerSnapshot | None = None,
    ) -> tuple[Path, dict]:
        """Seed a complete formal run without changing the active pointer."""
        run_dir = runs / run_name
        builder_for(source, source_bytes)(run_dir, None)
        _atomic_json(run_dir / SOURCE_REL, source)
        previous = expected_pointer or pointer_snapshot(pointer)
        receipt = {
            "schema": RECEIPT_SCHEMA,
            "transaction_id": uuid.uuid4().hex,
            "run_name": run_name,
            "source_sha256": source_hash,
            "effect_profile": test_create_profile(run_name),
            "activation_attempt": None,
            "status": status,
            "prepared_at": time.time(),
            "expected_pointer": {
                "exists": previous.exists,
                "sha256": previous.sha256,
            },
        }
        if status == "prepared_not_active":
            receipt["publish_intent_at"] = time.time()
        elif status in {"committed", "recovered"}:
            receipt["active_pointer"] = str(pointer)
            receipt["committed_at"] = time.time()
            if status == "recovered":
                receipt["recovered_at"] = time.time()
        _write_receipt(run_dir, receipt)
        return run_dir, _read_receipt(run_dir)

    def frozen_create_identity(run_dir: Path) -> dict:
        receipt = _read_receipt(run_dir)
        return {
            "effect_profile": receipt.get("effect_profile"),
            "contract_binding": receipt.get("contract_binding"),
            "transition_claim": receipt.get("transition_claim"),
            "setup_source_sha256": _sha256((run_dir / SOURCE_REL).read_bytes()),
        }

    def production_omitted_activation_callers() -> list[dict[str, str]]:
        found: list[dict[str, str]] = []

        class Visitor(ast.NodeVisitor):
            def __init__(self, relative_path: str) -> None:
                self.relative_path = relative_path
                self.functions: list[str] = []

            def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
                if node.name == "_selftest":
                    return
                self.functions.append(node.name)
                self.generic_visit(node)
                self.functions.pop()

            def visit_AsyncFunctionDef(
                self, node: ast.AsyncFunctionDef,
            ) -> None:
                if node.name == "_selftest":
                    return
                self.functions.append(node.name)
                self.generic_visit(node)
                self.functions.pop()

            def visit_Call(self, node: ast.Call) -> None:
                called = node.func.id if isinstance(node.func, ast.Name) else (
                    node.func.attr if isinstance(node.func, ast.Attribute) else ""
                )
                if called == "activate_existing_run" \
                        and not any(
                            keyword.arg == "operation" for keyword in node.keywords
                        ):
                    found.append({
                        "path": self.relative_path,
                        "function": self.functions[-1]
                        if self.functions else "<module>",
                    })
                self.generic_visit(node)

        for path in sorted((ROOT / "tools").rglob("*.py")):
            relative = path.relative_to(ROOT).as_posix()
            try:
                tree = ast.parse(path.read_text(encoding="utf-8"), filename=relative)
            except (OSError, UnicodeError, SyntaxError):
                continue
            Visitor(relative).visit(tree)
        return found

    def recovery_integrity_denied(
        run_name: str,
        mutate: Callable[[Path, dict], None],
        expected_codes: set[str],
    ) -> bool:
        run_dir, receipt = seed_published_recovery(run_name)
        mutate(run_dir, receipt)
        _write_receipt(run_dir, receipt)
        before = pointer_snapshot(pointer)
        try:
            create_and_activate(
                run_name,
                source_manifest=source,
                build=builder_for(source, source_bytes),
                root=root,
                runs_root=runs,
                pointer=pointer,
                required_files=required,
            )
            denied = False
        except SetupTransactionError as exc:
            denied = exc.code in expected_codes
        return bool(
            denied
            and _same_snapshot(pointer_snapshot(pointer), before)
            and _read_receipt(run_dir).get("status") == "prepared_not_active"
        )

    def active_recovery_integrity_denied(
        run_name: str,
        mutate: Callable[[Path, dict], None],
        expected_codes: set[str],
    ) -> bool:
        """Exercise the direct resume/set-active path for an active prepared run."""
        run_dir, receipt = seed_published_recovery(run_name)
        mutate(run_dir, receipt)
        _write_receipt(run_dir, receipt)
        before = pointer_snapshot(pointer)
        try:
            activate_existing_run(
                run_dir,
                operation=OP_TRANSACTION_ACTIVATE,
                root=root,
                runs_root=runs,
                pointer=pointer,
                required_files=required,
            )
            denied = False
        except SetupTransactionError as exc:
            denied = exc.code in expected_codes
        return bool(
            denied
            and _same_snapshot(pointer_snapshot(pointer), before)
            and _read_receipt(run_dir).get("status") == "prepared_not_active"
        )

    checks: list[tuple[str, bool]] = []
    try:
        option_target = "effect_options_20260101"
        option_reference = "/private/recon/path.json?token=opaque"
        setup_plain_profile = lifecycle_effect_profile(
            OP_SETUP_RUN_CREATE,
            option_target,
            source_type="recon-json",
            classify=False,
        )
        setup_classify_profile = lifecycle_effect_profile(
            OP_SETUP_RUN_CREATE,
            option_target,
            source_type="recon-json",
            classify=True,
        )
        loop_profile = lifecycle_effect_profile(
            OP_LOOP_BOOTSTRAP_CREATE,
            option_target,
            source_type="recon-json",
        )
        setup_plain_effect = transition_effect(
            "create", option_target,
            source_reference=option_reference,
            profile=setup_plain_profile,
        )
        setup_classify_effect = transition_effect(
            "create", option_target,
            source_reference=option_reference,
            profile=setup_classify_profile,
        )
        loop_effect = transition_effect(
            "create", option_target,
            source_reference=option_reference,
            profile=loop_profile,
        )
        resume_effect = transition_effect(
            "activate",
            option_target,
            profile=lifecycle_effect_profile(
                OP_LOOP_BOOTSTRAP_RESUME, option_target),
        )
        set_active_effect = transition_effect(
            "activate",
            option_target,
            profile=lifecycle_effect_profile(
                OP_STATUSLINE_SET_ACTIVE, option_target),
        )
        checks.extend([
            (
                "classify and no-classify produce different lifecycle effects",
                setup_plain_effect["effect_sha256"]
                != setup_classify_effect["effect_sha256"],
            ),
            (
                "setup_run and loop_bootstrap substitution changes the effect",
                setup_plain_effect["effect_sha256"] != loop_effect["effect_sha256"],
            ),
            (
                "resume and set-active operations produce different effects",
                resume_effect["effect_sha256"]
                != set_active_effect["effect_sha256"],
            ),
            (
                "effect/profile persist no raw source reference",
                option_reference not in json.dumps({
                    "effect": setup_plain_effect,
                    "profile": setup_plain_profile,
                }, sort_keys=True),
            ),
        ])
        owner_failure_lock = root / ".owner-failure.lock"
        original_atomic_json = globals()["_atomic_json"]

        def fail_owner_json(path: Path, value: dict) -> None:
            if path.name == "owner.json":
                raise OSError("injected owner metadata failure")
            original_atomic_json(path, value)

        try:
            globals()["_atomic_json"] = fail_owner_json
            try:
                with exclusive_directory_lock(owner_failure_lock):
                    pass
                owner_failure_reported = False
            except OSError:
                owner_failure_reported = True
        finally:
            globals()["_atomic_json"] = original_atomic_json
        checks.append((
            "owner metadata failure removes the unowned lock",
            owner_failure_reported and not owner_failure_lock.exists(),
        ))

        old = runs / "old_20260101"
        old.mkdir(parents=True)
        (old / "target.md").write_text("# old\n", encoding="utf-8")
        non_run = root / "docs"
        non_run.mkdir()
        _atomic_write(pointer, b"docs\n")
        checks.append((
            "in-repository path outside runs is not pointer authority",
            _pointer_target(
                pointer_snapshot(pointer), root=root, runs_root=runs
            ) is None,
        ))
        _atomic_write(pointer, b"runs/old_20260101\n")
        result = create_and_activate(
            "ok_20260101", source_manifest=source, build=_minimal_builder,
            root=root, runs_root=runs, pointer=pointer, required_files=required,
        )
        checks.extend([
            ("successful transaction commits", result.status == "committed"),
            ("successful transaction selects exact run",
             _pointer_target(
                 pointer_snapshot(pointer), root=root, runs_root=runs
             ) == result.run_dir),
            ("committed receipt persisted",
             _read_receipt(result.run_dir).get("status") == "committed"),
            ("staging directory removed", not (runs / STAGING_NAME).exists()),
        ])
        try:
            commit_activation_cas(
                old,
                expected=pointer_snapshot(pointer),
                root=root,
                runs_root=runs,
                pointer=pointer,
                effect_profile=lifecycle_effect_profile(
                    OP_TRANSACTION_ACTIVATE, old.name),
            )
            implicit_legacy_rejected = False
        except SetupTransactionError as exc:
            implicit_legacy_rejected = exc.code == "transaction_identity_mismatch"
        checks.append((
            "activation CAS rejects implicit legacy identity bypass",
            implicit_legacy_rejected,
        ))
        try:
            commit_activation_cas(
                old,
                root=root,
                runs_root=runs,
                pointer=pointer,
                effect_profile=lifecycle_effect_profile(
                    OP_TRANSACTION_ACTIVATE, old.name),
            )
            required_compare_snapshot = False
        except TypeError:
            required_compare_snapshot = True
        checks.append((
            "activation CAS requires an explicit compare snapshot",
            required_compare_snapshot,
        ))
        committed_receipt_before = _read_receipt(result.run_dir)
        selected_again = activate_existing_run(
            result.run_dir, operation=OP_TRANSACTION_ACTIVATE,
            root=root, runs_root=runs, pointer=pointer
        )
        checks.extend([
            ("selecting the committed active run is idempotent",
             selected_again.status == "committed" and not selected_again.recovered),
            ("idempotent selection does not relabel committed receipt",
             _read_receipt(result.run_dir) == committed_receipt_before),
        ])
        before_identity_reject = pointer_snapshot(pointer)
        try:
            commit_activation_cas(
                result.run_dir,
                expected=before_identity_reject,
                root=root,
                runs_root=runs,
                pointer=pointer,
                effect_profile=lifecycle_effect_profile(
                    OP_TRANSACTION_ACTIVATE, result.run_dir.name),
            )
            missing_identity_rejected = False
        except SetupTransactionError as exc:
            missing_identity_rejected = exc.code == "transaction_identity_mismatch"
        checks.append((
            "formal receipt activation requires explicit transaction identity",
            missing_identity_rejected
            and _same_snapshot(pointer_snapshot(pointer), before_identity_reject),
        ))

        corrupt_run = runs / "corrupt_20260101"
        (corrupt_run / "state").mkdir(parents=True)
        (corrupt_run / RECEIPT_REL).write_text("{broken", encoding="utf-8")
        before_corrupt = pointer_snapshot(pointer)
        try:
            activate_existing_run(
                corrupt_run, operation=OP_TRANSACTION_ACTIVATE,
                root=root, runs_root=runs, pointer=pointer
            )
            corrupt_receipt_rejected = False
        except SetupTransactionError as exc:
            corrupt_receipt_rejected = exc.code == "invalid_transaction_receipt"
        checks.append((
            "corrupt formal receipt cannot impersonate a legacy run",
            corrupt_receipt_rejected
            and _same_snapshot(pointer_snapshot(pointer), before_corrupt),
        ))

        mismatch_run = runs / "mismatch_20260101"
        (mismatch_run / "state").mkdir(parents=True)
        mismatch_source_hash = "2" * 64
        _atomic_json(mismatch_run / SOURCE_REL, {
            "schema": "xunji.setup_source.v1",
            "source_sha256": mismatch_source_hash,
        })
        _write_receipt(mismatch_run, {
            "transaction_id": "3" * 32,
            "run_name": mismatch_run.name,
            "source_sha256": "4" * 64,
            "status": "prepared_not_active",
        })
        before_mismatch = pointer_snapshot(pointer)
        try:
            activate_existing_run(
                mismatch_run, operation=OP_TRANSACTION_ACTIVATE,
                root=root, runs_root=runs, pointer=pointer
            )
            source_mismatch_rejected = False
        except SetupTransactionError as exc:
            source_mismatch_rejected = exc.code == "transaction_identity_mismatch"
        checks.append((
            "source manifest mismatch blocks formal activation",
            source_mismatch_rejected
            and _same_snapshot(pointer_snapshot(pointer), before_mismatch),
        ))

        def corrupt_recovery_txid(_run_dir: Path, receipt: dict) -> None:
            receipt["transaction_id"] = "not-a-valid-transaction"

        def corrupt_recovery_run_name(_run_dir: Path, receipt: dict) -> None:
            receipt["run_name"] = "different_20260101"

        def remove_recovery_validator(run_dir: Path, _receipt: dict) -> None:
            (run_dir / setup_source.VALIDATOR_REL).unlink()

        def remove_recovery_required_file(run_dir: Path, _receipt: dict) -> None:
            (run_dir / "target.md").unlink()

        def forge_recovery_status(_run_dir: Path, receipt: dict) -> None:
            receipt.pop("publish_intent_at", None)

        checks.extend([
            (
                "post-pointer recovery rejects an invalid transaction id",
                recovery_integrity_denied(
                    "recover_bad_txid_20260101",
                    corrupt_recovery_txid,
                    {"invalid_transaction_receipt"},
                ),
            ),
            (
                "post-pointer recovery rejects a receipt for another run",
                recovery_integrity_denied(
                    "recover_bad_name_20260101",
                    corrupt_recovery_run_name,
                    {"invalid_transaction_receipt"},
                ),
            ),
            (
                "post-pointer recovery rejects a missing setup source bundle",
                recovery_integrity_denied(
                    "recover_missing_bundle_20260101",
                    remove_recovery_validator,
                    {"invalid_source_bundle", "invalid_validator_receipt"},
                ),
            ),
            (
                "post-pointer recovery rejects an incomplete run skeleton",
                recovery_integrity_denied(
                    "recover_incomplete_20260101",
                    remove_recovery_required_file,
                    {"incomplete_staging"},
                ),
            ),
            (
                "direct active-run recovery rejects an incomplete run skeleton",
                active_recovery_integrity_denied(
                    "active_recover_incomplete_20260101",
                    remove_recovery_required_file,
                    {"incomplete_staging"},
                ),
            ),
            (
                "post-pointer recovery rejects a forged prepared_not_active receipt",
                recovery_integrity_denied(
                    "recover_forged_status_20260101",
                    forge_recovery_status,
                    {"invalid_transaction_receipt"},
                ),
            ),
        ])

        substituted_profile_run, _ = seed_published_recovery(
            "recover_substituted_profile_20260101")
        substituted_before = pointer_snapshot(pointer)
        try:
            create_and_activate(
                substituted_profile_run.name,
                source_manifest=source,
                build=builder_for(source, source_bytes),
                effect_profile=lifecycle_effect_profile(
                    OP_SETUP_RUN_CREATE,
                    substituted_profile_run.name,
                    source_type="url",
                ),
                root=root,
                runs_root=runs,
                pointer=pointer,
                required_files=required,
            )
            substituted_profile_denied = False
        except SetupTransactionError as exc:
            substituted_profile_denied = exc.code == "effect_profile_mismatch"
        checks.append((
            "post-pointer recovery rejects adapter profile substitution",
            substituted_profile_denied
            and _same_snapshot(pointer_snapshot(pointer), substituted_before)
            and _read_receipt(substituted_profile_run).get("status")
            == "prepared_not_active",
        ))

        missing_profile_run, missing_profile_receipt = seed_published_recovery(
            "recover_missing_profile_20260101")
        missing_profile_receipt.pop("effect_profile", None)
        _write_receipt(missing_profile_run, missing_profile_receipt)
        before_missing_profile = pointer_snapshot(pointer)
        try:
            activate_existing_run(
                missing_profile_run,
                operation=OP_TRANSACTION_ACTIVATE,
                root=root,
                runs_root=runs,
                pointer=pointer,
            )
            missing_current_profile_rejected = False
        except SetupTransactionError as exc:
            missing_current_profile_rejected = exc.code == "invalid_effect_profile"
        checks.append((
            "current-schema formal run without an effect profile fails closed",
            missing_current_profile_rejected
            and _same_snapshot(pointer_snapshot(pointer), before_missing_profile),
        ))

        true_legacy = runs / "true_legacy_20260101"
        true_legacy.mkdir()
        (true_legacy / "target.md").write_text("# legacy\n", encoding="utf-8")
        true_legacy_result = activate_existing_run(
            true_legacy,
            operation=OP_TRANSACTION_ACTIVATE,
            root=root,
            runs_root=runs,
            pointer=pointer,
            pending_dir=root / "true-legacy-pending",
            claims_dir=root / "true-legacy-claims",
        )
        checks.append((
            "receipt-free legacy run remains explicitly activatable",
            true_legacy_result.status == "committed"
            and _pointer_target(
                pointer_snapshot(pointer), root=root, runs_root=runs
            ) == true_legacy.resolve(),
        ))

        import sys
        sys.path.insert(0, str(ROOT / "tools"))
        import turn_contract

        direct_target = runs / "direct_transfer_20260101"
        direct_target.mkdir()
        (direct_target / "target.md").write_text(
            "# direct transfer target\n", encoding="utf-8")
        (true_legacy / "state").mkdir(exist_ok=True)
        direct_source_contract = turn_contract._contract_from_event({
            "session_id": "direct-local-transition",
            "prompt": f"/loop runs/{direct_target.name}",
        }, run_name=true_legacy.name)
        turn_contract._atomic_json(
            turn_contract.contract_path(true_legacy), direct_source_contract)
        direct_transfer_result = activate_existing_run(
            direct_target,
            operation=OP_TRANSACTION_ACTIVATE,
            root=root,
            runs_root=runs,
            pointer=pointer,
            pending_dir=root / "direct-transfer-pending",
            claims_dir=root / "direct-transfer-claims",
        )
        direct_target_contract = turn_contract.load_contract(
            direct_target, session_id="direct-local-transition")
        direct_source_after = turn_contract.load_contract(
            true_legacy, session_id="direct-local-transition")
        checks.append((
            "direct local activation transfers an existing turn contract before pointer CAS",
            direct_transfer_result.status == "committed"
            and direct_target_contract.get("origin_run") == true_legacy.name
            and direct_target_contract.get("bound_run") == direct_target.name
            and direct_target_contract.get("prompt_sha256")
            == direct_source_contract.get("prompt_sha256")
            and direct_source_after == direct_source_contract
            and _pointer_target(
                pointer_snapshot(pointer), root=root, runs_root=runs
            ) == direct_target.resolve(),
        ))

        # A malformed/dangling pointer is not a source of turn authority.  The
        # pending hook claim must still be consumed and transaction-bound.
        def seed_activate_claim(
            origin: Path,
            target: Path,
            *,
            session_id: str,
            operation: str,
            claims_root: Path,
        ) -> dict:
            (origin / "state").mkdir(parents=True, exist_ok=True)
            contract = turn_contract._contract_from_event({
                "session_id": session_id,
                "prompt": f"/loop runs/{target.name}",
            }, run_name=origin.name)
            turn_contract._atomic_json(
                turn_contract.contract_path(origin), contract)
            turn_contract.write_transition_claim(
                target.name,
                contract,
                origin_run=origin.name,
                claims_dir=claims_root,
                effect=test_activate_effect(target.name, operation),
            )
            return contract

        _atomic_write(pointer, b"runs/missing_20260101\n")
        pending_dir = root / "pending"
        claims_dir = root / "claims"
        pending = turn_contract.write_pending_contract({
            "session_id": "setup-transaction-selftest",
            "prompt": "/loop https://claim.example 创建一个新 run",
        }, pending_dir=pending_dir)
        turn_contract.write_transition_claim(
            "claim_20260101", pending, claims_dir=claims_dir,
            effect=test_create_effect("claim_20260101"),
        )
        claimed = create_and_activate(
            "claim_20260101", source_manifest=source, build=_minimal_builder,
            root=root, runs_root=runs, pointer=pointer, required_files=required,
            pending_dir=pending_dir, claims_dir=claims_dir,
        )
        claimed_receipt = _read_receipt(claimed.run_dir)
        claimed_source = _read_json(claimed.run_dir / SOURCE_REL)
        claimed_contract = turn_contract.load_contract(
            claimed.run_dir, session_id="setup-transaction-selftest"
        )
        checks.extend([
            ("dangling pointer cannot bypass pending claim consumption",
             claimed_contract.get("bound_run") == "claim_20260101"
             and not any(claims_dir.glob("*.json"))),
            ("consumed claim binds source transaction and expected run",
             claimed_contract.get("transition_transaction") == {
                 "transaction_id": claimed.transaction_id,
                 "source_sha256": source_hash,
                 "expected_run": "claim_20260101",
             }),
            ("transaction receipt records hook-owned contract binding",
             claimed_receipt.get("contract_binding", {}).get("session_id")
             == "setup-transaction-selftest"
             and claimed_receipt.get("transition_claim", {}).get("effect")
             == test_create_effect("claim_20260101")),
            ("hook prompt and exact source effect bind operator authority",
             claimed_source.get("operator_directive", {}).get("prompt_sha256")
             == pending.get("prompt_sha256")
             and any(
                 item.get("authority") == "operator"
                 and item.get("source_ref")
                 == f"operator:prompt#sha256={pending.get('prompt_sha256')}"
                 for item in claimed_source.get("authorization_claims", [])
                 if isinstance(item, dict)
             )
             and bool(setup_source.verify_bundle(claimed.run_dir, claimed_source))),
            ("claim artifacts retire only after the pointer commits",
             _pointer_target(
                 pointer_snapshot(pointer), root=root, runs_root=runs
             ) == claimed.run_dir
             and not any(claims_dir.glob("*.json"))
             and not any(pending_dir.glob("*.json"))),
        ])

        # Exact incident regression: the pointer bytes already name the run,
        # but the run does not exist until atomic publish.  Publishing must not
        # reinterpret those unchanged bytes as a completed pointer commit.
        same_dangling_name = "same_dangling_20260101"
        _atomic_write(
            pointer, f"runs/{same_dangling_name}\n".encode("utf-8"))
        same_dangling_before = pointer_snapshot(pointer)
        same_dangling_pending = root / "same-dangling-pending"
        same_dangling_claims = root / "same-dangling-claims"
        same_pending = turn_contract.write_pending_contract({
            "session_id": "same-dangling-session",
            "prompt": f"为 {source['source']['reference']} 创建一个新 run",
        }, pending_dir=same_dangling_pending)
        turn_contract.write_transition_claim(
            same_dangling_name,
            same_pending,
            claims_dir=same_dangling_claims,
            effect=test_create_effect(same_dangling_name),
        )
        same_dangling_result = create_and_activate(
            same_dangling_name,
            source_manifest=source,
            build=_minimal_builder,
            root=root,
            runs_root=runs,
            pointer=pointer,
            required_files=required,
            pending_dir=same_dangling_pending,
            claims_dir=same_dangling_claims,
        )
        same_dangling_receipt = _read_receipt(
            same_dangling_result.run_dir)
        same_dangling_contract = turn_contract.load_contract(
            same_dangling_result.run_dir,
            session_id="same-dangling-session",
        )
        checks.append((
            "same-target dangling pointer binds no-origin claim before commit",
            same_dangling_result.status == "committed"
            and not same_dangling_result.recovered
            and same_dangling_receipt.get("status") == "committed"
            and same_dangling_receipt.get("expected_origin_valid") is False
            and same_dangling_receipt.get("expected_pointer", {}).get("sha256")
                == same_dangling_before.sha256
            and same_dangling_contract.get("transition_claim", {}).get(
                "origin_run") == ""
            and not any(same_dangling_pending.glob("*.json"))
            and not any(same_dangling_claims.glob("*.json")),
        ))

        import builtins
        original_import = builtins.__import__

        def deny_turn_contract_import(name, *args, **kwargs):
            if name == "turn_contract":
                raise ImportError("injected missing turn-contract boundary")
            return original_import(name, *args, **kwargs)

        try:
            builtins.__import__ = deny_turn_contract_import
            try:
                _claim_or_transfer_contract(
                    None,
                    claimed.run_dir,
                    transaction_id="e" * 32,
                    source_hash="f" * 64,
                    pending_dir=pending_dir,
                    claims_dir=claims_dir,
                    effect=test_create_effect(claimed.run_dir.name),
                )
                missing_contract_boundary_blocked = False
            except SetupTransactionError as exc:
                missing_contract_boundary_blocked = (
                    exc.code == "contract_boundary_unavailable"
                )
        finally:
            builtins.__import__ = original_import
        checks.append((
            "missing turn-contract boundary fails closed",
            missing_contract_boundary_blocked,
        ))

        def seed_create_claim(
            target_name: str,
            session_id: str,
            *,
            pending_root: Path,
            claims_root: Path,
            manifest: dict = source,
        ) -> tuple[dict, dict]:
            pending_contract = turn_contract.write_pending_contract({
                "session_id": session_id,
                "prompt": (
                    f"创建新 run {target_name}，source "
                    f"{manifest['source']['reference']}"
                ),
            }, pending_dir=pending_root, claims_dir=claims_root)
            effect_value = test_create_effect(target_name, manifest)
            turn_contract.write_transition_claim(
                target_name, pending_contract,
                claims_dir=claims_root, effect=effect_value,
            )
            return pending_contract, effect_value

        # The claim authorizes one exact source effect, not merely a prompt hash
        # or a coincidentally identical target directory name.
        _atomic_write(pointer, b"runs/missing_effect_origin_20260101\n")
        mismatch_pending = root / "effect-mismatch-pending"
        mismatch_claims = root / "effect-mismatch-claims"
        seed_create_claim(
            "effect_mismatch_20260101", "effect-mismatch",
            pending_root=mismatch_pending, claims_root=mismatch_claims,
        )
        mismatch_before = pointer_snapshot(pointer)
        try:
            create_and_activate(
                "effect_mismatch_20260101",
                source_manifest=alternate_source,
                build=builder_for(alternate_source, alternate_source_bytes),
                root=root, runs_root=runs, pointer=pointer,
                required_files=required,
                pending_dir=mismatch_pending, claims_dir=mismatch_claims,
            )
            mismatched_effect_rejected = False
        except SetupTransactionError as exc:
            mismatched_effect_rejected = exc.code == "contract_claim_invalid"
        checks.append((
            "same target cannot consume a claim for a different source effect",
            mismatched_effect_rejected
            and _same_snapshot(pointer_snapshot(pointer), mismatch_before)
            and bool(list(mismatch_claims.glob("*.json"))),
        ))

        def expect_artifact_denial(
            target_name: str,
            session_id: str,
            mutate: Callable[[Path, dict], None],
        ) -> bool:
            _atomic_write(pointer, b"runs/missing_artifact_origin_20260101\n")
            artifact_pending = root / f"{target_name}-pending"
            artifact_claims = root / f"{target_name}-claims"
            pending_contract, _effect = seed_create_claim(
                target_name, session_id,
                pending_root=artifact_pending, claims_root=artifact_claims,
            )
            claim_path = next(artifact_claims.glob("*.json"))
            mutate(claim_path, pending_contract)
            before = pointer_snapshot(pointer)
            try:
                create_and_activate(
                    target_name, source_manifest=source,
                    build=builder_for(source, source_bytes),
                    root=root, runs_root=runs, pointer=pointer,
                    required_files=required,
                    pending_dir=artifact_pending, claims_dir=artifact_claims,
                )
                denied = False
            except SetupTransactionError as exc:
                denied = exc.code == "contract_claim_invalid"
            return denied and _same_snapshot(pointer_snapshot(pointer), before)

        def stale_claim(path: Path, _contract: dict) -> None:
            value = json.loads(path.read_text(encoding="utf-8"))
            value["updated_at"] = time.time() - (16 * 60)
            _atomic_json(path, value)

        def corrupt_claim(path: Path, _contract: dict) -> None:
            path.write_text("{broken", encoding="utf-8")

        def revoke_claim(_path: Path, contract_value: dict) -> None:
            turn_contract.write_pending_contract({
                "session_id": str(contract_value.get("session_id") or ""),
                "prompt": "只查看当前状态，不创建 run",
            }, pending_dir=root / "revoked_artifact_20260101-pending",
               claims_dir=root / "revoked_artifact_20260101-claims")

        checks.extend([
            ("stale matching claim cannot downgrade to direct-shell activation",
             expect_artifact_denial(
                 "stale_artifact_20260101", "stale-artifact", stale_claim)),
            ("corrupt matching claim cannot downgrade to direct-shell activation",
             expect_artifact_denial(
                 "corrupt_artifact_20260101", "corrupt-artifact", corrupt_claim)),
            ("revoked matching claim cannot downgrade to direct-shell activation",
             expect_artifact_denial(
                 "revoked_artifact_20260101", "revoked-artifact", revoke_claim)),
        ])

        # A failure before pointer replacement leaves an exact claimed record.
        # The same transaction/effect may recover; a newer prompt tombstones it.
        retry_pending = root / "claimed-retry-pending"
        retry_claims = root / "claimed-retry-claims"
        retry_name = "claimed_retry_20260101"
        seed_create_claim(
            retry_name, "claimed-retry",
            pending_root=retry_pending, claims_root=retry_claims,
        )
        _atomic_write(pointer, b"runs/missing_retry_origin_20260101\n")
        retry_txid = "9" * 32

        def fail_before_pointer(stage: str) -> None:
            if stage == "before_pointer_replace":
                raise RuntimeError("injected before-pointer failure")

        try:
            create_and_activate(
                retry_name, source_manifest=source,
                build=builder_for(source, source_bytes),
                root=root, runs_root=runs, pointer=pointer,
                required_files=required, transaction_id=retry_txid,
                pending_dir=retry_pending, claims_dir=retry_claims,
                fault=fail_before_pointer,
            )
            before_pointer_fault_reported = False
        except SetupTransactionError:
            before_pointer_fault_reported = True
        retry_claim_value = json.loads(next(
            retry_claims.glob("*.json")).read_text(encoding="utf-8"))
        retry_result = create_and_activate(
            retry_name, source_manifest=source,
            build=builder_for(source, source_bytes),
            root=root, runs_root=runs, pointer=pointer,
            required_files=required, transaction_id=retry_txid,
            pending_dir=retry_pending, claims_dir=retry_claims,
        )
        checks.append((
            "same transaction/effect retries a claimed pre-pointer failure",
            before_pointer_fault_reported
            and retry_claim_value.get("status") == "claimed"
            and retry_result.status == "committed"
            and not list(retry_claims.glob("*.json"))
            and not list(retry_pending.glob("*.json")),
        ))

        revoked_retry_pending = root / "claimed-revoked-pending"
        revoked_retry_claims = root / "claimed-revoked-claims"
        revoked_retry_name = "claimed_revoked_20260101"
        seed_create_claim(
            revoked_retry_name, "claimed-revoked",
            pending_root=revoked_retry_pending,
            claims_root=revoked_retry_claims,
        )
        _atomic_write(pointer, b"runs/missing_revoked_origin_20260101\n")
        revoked_txid = "8" * 32
        try:
            create_and_activate(
                revoked_retry_name, source_manifest=source,
                build=builder_for(source, source_bytes),
                root=root, runs_root=runs, pointer=pointer,
                required_files=required, transaction_id=revoked_txid,
                pending_dir=revoked_retry_pending,
                claims_dir=revoked_retry_claims,
                fault=fail_before_pointer,
            )
        except SetupTransactionError:
            pass
        turn_contract.write_pending_contract({
            "session_id": "claimed-revoked",
            "prompt": "只解释状态，不再创建 run",
        }, pending_dir=revoked_retry_pending, claims_dir=revoked_retry_claims)
        revoked_before = pointer_snapshot(pointer)
        try:
            create_and_activate(
                revoked_retry_name, source_manifest=source,
                build=builder_for(source, source_bytes),
                root=root, runs_root=runs, pointer=pointer,
                required_files=required, transaction_id=revoked_txid,
                pending_dir=revoked_retry_pending,
                claims_dir=revoked_retry_claims,
            )
            claimed_revocation_denied = False
        except SetupTransactionError as exc:
            claimed_revocation_denied = exc.code == "contract_claim_invalid"
        checks.append((
            "new prompt tombstone blocks retry of a claimed pre-pointer command",
            claimed_revocation_denied
            and _same_snapshot(pointer_snapshot(pointer), revoked_before),
        ))

        def fail_after_pointer(stage: str) -> None:
            if stage == "after_pointer_before_receipt":
                raise RuntimeError("injected post-pointer failure")

        tampered_pointer_pending = root / "tampered-pointer-claim-pending"
        tampered_pointer_claims = root / "tampered-pointer-claim-claims"
        tampered_pointer_name = "tampered_pointer_claim_20260101"
        seed_create_claim(
            tampered_pointer_name, "tampered-pointer-claim",
            pending_root=tampered_pointer_pending,
            claims_root=tampered_pointer_claims,
        )
        _atomic_write(pointer, b"runs/missing_tampered_pointer_origin_20260101\n")
        tampered_pointer_txid = "6" * 32
        try:
            create_and_activate(
                tampered_pointer_name, source_manifest=source,
                build=builder_for(source, source_bytes),
                root=root, runs_root=runs, pointer=pointer,
                required_files=required, transaction_id=tampered_pointer_txid,
                pending_dir=tampered_pointer_pending,
                claims_dir=tampered_pointer_claims,
                fault=fail_after_pointer,
            )
        except SetupTransactionError:
            pass
        tampered_pointer_dir = runs / tampered_pointer_name
        tampered_pointer_receipt = _read_receipt(tampered_pointer_dir)
        tampered_pointer_receipt["transition_claim"]["transaction_id"] = "5" * 32
        _write_receipt(tampered_pointer_dir, tampered_pointer_receipt)
        tampered_pointer_before = pointer_snapshot(pointer)
        try:
            create_and_activate(
                tampered_pointer_name, source_manifest=source,
                build=builder_for(source, source_bytes),
                root=root, runs_root=runs, pointer=pointer,
                required_files=required,
                pending_dir=tampered_pointer_pending,
                claims_dir=tampered_pointer_claims,
            )
            tampered_pointer_denied = False
        except SetupTransactionError as exc:
            tampered_pointer_denied = exc.code == "transaction_identity_mismatch"
        checks.append((
            "post-pointer recovery rejects a mutated exact claim binding",
            tampered_pointer_denied
            and _same_snapshot(pointer_snapshot(pointer), tampered_pointer_before)
            and _read_receipt(tampered_pointer_dir).get("status")
            == "prepared_not_active"
            and bool(list(tampered_pointer_claims.glob("*.json"))),
        ))

        post_pointer_pending = root / "post-pointer-claim-pending"
        post_pointer_claims = root / "post-pointer-claim-claims"
        post_pointer_name = "post_pointer_claim_20260101"
        seed_create_claim(
            post_pointer_name, "post-pointer-claim",
            pending_root=post_pointer_pending,
            claims_root=post_pointer_claims,
        )
        _atomic_write(pointer, b"runs/missing_post_pointer_origin_20260101\n")
        post_pointer_txid = "7" * 32

        try:
            create_and_activate(
                post_pointer_name, source_manifest=source,
                build=builder_for(source, source_bytes),
                root=root, runs_root=runs, pointer=pointer,
                required_files=required, transaction_id=post_pointer_txid,
                pending_dir=post_pointer_pending,
                claims_dir=post_pointer_claims,
                fault=fail_after_pointer,
            )
            post_pointer_fault_reported = False
        except SetupTransactionError:
            post_pointer_fault_reported = True
        post_pointer_receipt_before = _read_receipt(
            runs / post_pointer_name)
        recovered_claim = create_and_activate(
            post_pointer_name, source_manifest=source,
            build=builder_for(source, source_bytes),
            root=root, runs_root=runs, pointer=pointer,
            required_files=required,
            pending_dir=post_pointer_pending, claims_dir=post_pointer_claims,
        )
        post_pointer_receipt_after = _read_receipt(recovered_claim.run_dir)
        checks.append((
            "post-pointer recovery finalizes the exact hook claim",
            post_pointer_fault_reported and recovered_claim.recovered
            and post_pointer_receipt_after.get("status") == "recovered"
            and post_pointer_receipt_after.get("transition_claim")
            == post_pointer_receipt_before.get("transition_claim")
            and post_pointer_receipt_after.get("contract_binding")
            == post_pointer_receipt_before.get("contract_binding")
            and not list(post_pointer_claims.glob("*.json"))
            and not list(post_pointer_pending.glob("*.json")),
        ))

        # Active-run transitions use the same exact claim boundary.
        active_origin = runs / "active_origin_20260101"
        active_target = runs / "active_target_20260101"
        (active_origin / "state").mkdir(parents=True)
        active_target.mkdir()
        active_contract = turn_contract._contract_from_event({
            "session_id": "active-transition",
            "prompt": f"/loop runs/{active_target.name}",
        }, run_name=active_origin.name)
        turn_contract._atomic_json(
            turn_contract.contract_path(active_origin), active_contract)
        active_effect = test_activate_effect(active_target.name)
        active_claims = root / "active-transition-claims"
        turn_contract.write_transition_claim(
            active_target.name, active_contract,
            origin_run=active_origin.name,
            claims_dir=active_claims, effect=active_effect,
        )
        _atomic_write(pointer, b"runs/active_origin_20260101\n")
        active_result = activate_existing_run(
            active_target, operation=OP_TRANSACTION_ACTIVATE,
            root=root, runs_root=runs, pointer=pointer,
            pending_dir=root / "active-transition-pending",
            claims_dir=active_claims,
        )
        active_bound = turn_contract.load_contract(
            active_target, session_id="active-transition")
        checks.append((
            "active-run activation consumes the exact origin/target/effect claim",
            active_result.status == "committed"
            and active_bound.get("bound_run") == active_target.name
            and not list(active_claims.glob("*.json")),
        ))

        # The committed statusline adapter predates the explicit operation
        # parameter.  Its omitted argument must map to the statusline effect,
        # while an explicitly different adapter operation remains unable to
        # consume that exact hook claim.
        status_origin = runs / "status_origin_20260101"
        (status_origin / "state").mkdir(parents=True)
        status_target, _ = seed_formal_run(
            "status_target_20260101", status="committed")
        status_create_identity = frozen_create_identity(status_target)
        status_contract = turn_contract._contract_from_event({
            "session_id": "status-transition",
            "prompt": f"/loop runs/{status_target.name}",
        }, run_name=status_origin.name)
        turn_contract._atomic_json(
            turn_contract.contract_path(status_origin), status_contract)
        status_claims = root / "status-transition-claims"
        turn_contract.write_transition_claim(
            status_target.name, status_contract,
            origin_run=status_origin.name,
            claims_dir=status_claims,
            effect=test_activate_effect(
                status_target.name, OP_STATUSLINE_SET_ACTIVE),
        )
        _atomic_write(pointer, b"runs/status_origin_20260101\n")
        status_result = activate_existing_run(
            status_target, root=root, runs_root=runs, pointer=pointer,
            pending_dir=root / "status-transition-pending",
            claims_dir=status_claims,
        )
        status_bound = turn_contract.load_contract(
            status_target, session_id="status-transition")
        status_receipt = _read_receipt(status_target)
        checks.append((
            "legacy statusline omission consumes only the statusline effect claim",
            status_result.status == "committed"
            and status_bound.get("transition_claim", {}).get("effect", {}).get(
                "operation") == OP_STATUSLINE_SET_ACTIVE
            and status_receipt.get("activation_attempt", {}).get("status")
            == "committed"
            and status_receipt.get("activation_attempt", {}).get(
                "effect", {}).get("operation") == OP_STATUSLINE_SET_ACTIVE
            and frozen_create_identity(status_target) == status_create_identity
            and not list(status_claims.glob("*.json")),
        ))

        same_target_contract = turn_contract._contract_from_event({
            "session_id": "status-same-target",
            "prompt": f"/loop runs/{status_target.name}",
        }, run_name=status_target.name)
        turn_contract._atomic_json(
            turn_contract.contract_path(status_target), same_target_contract)
        same_target_claims = root / "status-same-target-claims"
        turn_contract.write_transition_claim(
            status_target.name, same_target_contract,
            origin_run=status_target.name,
            claims_dir=same_target_claims,
            effect=test_activate_effect(
                status_target.name, OP_STATUSLINE_SET_ACTIVE),
        )
        same_target_before = pointer_snapshot(pointer)
        same_target_result = activate_existing_run(
            status_target, root=root, runs_root=runs, pointer=pointer,
            pending_dir=root / "status-same-target-pending",
            claims_dir=same_target_claims,
        )
        same_target_bound = turn_contract.load_contract(
            status_target, session_id="status-same-target")
        same_target_receipt = _read_receipt(status_target)
        checks.append((
            "same-target statusline selection retires its fresh exact claim",
            same_target_result.status == "committed"
            and _same_snapshot(pointer_snapshot(pointer), same_target_before)
            and same_target_bound.get("bound_run") == status_target.name
            and same_target_receipt.get("activation_attempt", {}).get("status")
            == "committed"
            and frozen_create_identity(status_target) == status_create_identity
            and not list(same_target_claims.glob("*.json")),
        ))

        invalid_operation_before = pointer_snapshot(pointer)
        invalid_operation_codes: list[str] = []
        for invalid_operation in (None, ""):
            try:
                activate_existing_run(
                    status_target,
                    operation=invalid_operation,
                    root=root,
                    runs_root=runs,
                    pointer=pointer,
                )
            except SetupTransactionError as exc:
                invalid_operation_codes.append(exc.code)
        checks.append((
            "explicit None/empty operations never inherit statusline identity",
            invalid_operation_codes
            == ["invalid_effect_profile", "invalid_effect_profile"]
            and _same_snapshot(pointer_snapshot(pointer), invalid_operation_before),
        ))

        checks.append((
            "production omissions stay inside the statusline compatibility allowlist",
            all(
                caller in spec.get("allowed_production_omitted_callers", [])
                for caller in production_omitted_activation_callers()
            ),
        ))

        receipt_durability_case = next((
            case for case in spec.get("receipt_durability_cases", [])
            if isinstance(case, dict) and case.get("failure") == "fsync"
        ), {})
        receipt_durability_run_name = "receipt_durability_20260101"
        receipt_durability_before = pointer_snapshot(pointer)
        original_receipt_os_fsync = os.fsync

        def fail_directory_fsync_for_receipt(fd: int) -> None:
            if stat.S_ISDIR(os.fstat(fd).st_mode):
                raise OSError("injected setup-receipt directory fsync failure")
            original_receipt_os_fsync(fd)

        try:
            os.fsync = fail_directory_fsync_for_receipt
            try:
                create_and_activate(
                    receipt_durability_run_name,
                    source_manifest=source,
                    build=_minimal_builder,
                    root=root,
                    runs_root=runs,
                    pointer=pointer,
                    required_files=required,
                )
                receipt_durability_code = ""
            except SetupTransactionError as exc:
                receipt_durability_code = exc.code
        finally:
            os.fsync = original_receipt_os_fsync
        checks.append((
            "receipt directory fsync failure cannot publish or move the pointer",
            receipt_durability_case.get("error")
            == receipt_durability_code == "receipt_durability_failed"
            and receipt_durability_case.get("formal_run") == "absent"
            and not (runs / receipt_durability_run_name).exists()
            and receipt_durability_case.get("pointer") == "unchanged"
            and _same_snapshot(
                pointer_snapshot(pointer), receipt_durability_before),
        ))

        terminal_receipt_case = next((
            case for case in spec.get("receipt_durability_cases", [])
            if isinstance(case, dict)
            and case.get("failure") == "post_pointer_terminal_fsync"
        ), {})

        def seed_terminal_receipt_fsync_failure(
            run_name: str,
            session_id: str,
        ) -> tuple[str, Path, Path, Path, dict, dict]:
            pending_root = root / f"{session_id}-pending"
            claims_root = root / f"{session_id}-claims"
            seed_create_claim(
                run_name,
                session_id,
                pending_root=pending_root,
                claims_root=claims_root,
            )
            _atomic_write(
                pointer,
                f"runs/missing_{session_id}_origin_20260101\n".encode("utf-8"),
            )
            armed = False
            failed_once = False
            original_fsync = os.fsync

            def arm_terminal_receipt_fsync(stage: str) -> None:
                nonlocal armed
                if stage == "after_pointer_before_receipt":
                    armed = True

            def fail_terminal_receipt_directory_fsync(fd: int) -> None:
                nonlocal failed_once
                if armed and not failed_once \
                        and stat.S_ISDIR(os.fstat(fd).st_mode):
                    failed_once = True
                    raise OSError(
                        "injected terminal receipt directory fsync failure")
                original_fsync(fd)

            try:
                os.fsync = fail_terminal_receipt_directory_fsync
                try:
                    create_and_activate(
                        run_name,
                        source_manifest=source,
                        build=_minimal_builder,
                        root=root,
                        runs_root=runs,
                        pointer=pointer,
                        required_files=required,
                        pending_dir=pending_root,
                        claims_dir=claims_root,
                        fault=arm_terminal_receipt_fsync,
                    )
                    error_code = ""
                except SetupTransactionError as exc:
                    error_code = exc.code
            finally:
                os.fsync = original_fsync
            run_dir = runs / run_name
            visible_receipt = _read_receipt(run_dir)
            visible_claim = json.loads(next(
                claims_root.glob("*.json")).read_text(encoding="utf-8"))
            return (
                error_code,
                run_dir,
                pending_root,
                claims_root,
                visible_receipt,
                visible_claim,
            )

        terminal_receipt_name = "terminal_receipt_durability_20260101"
        terminal_receipt_code, terminal_receipt_run, \
            terminal_receipt_pending, terminal_receipt_claims, \
            terminal_receipt_visible, terminal_claim_visible = \
            seed_terminal_receipt_fsync_failure(
                terminal_receipt_name, "terminal-receipt")
        terminal_receipt_retry = create_and_activate(
            terminal_receipt_name,
            source_manifest=source,
            build=_minimal_builder,
            root=root,
            runs_root=runs,
            pointer=pointer,
            required_files=required,
            pending_dir=terminal_receipt_pending,
            claims_dir=terminal_receipt_claims,
        )
        checks.append((
            "terminal receipt fsync failure recovers without origin relabeling",
            terminal_receipt_case.get("error")
            == terminal_receipt_code == "receipt_durability_failed"
            and terminal_receipt_case.get("receipt")
            == terminal_receipt_visible.get("status") == "committed"
            and terminal_receipt_case.get("claim")
            == terminal_claim_visible.get("status") == "claimed"
            and terminal_receipt_case.get("retry") == "recovered"
            and terminal_receipt_retry.recovered
            and not list(terminal_receipt_pending.glob("*.json"))
            and not list(terminal_receipt_claims.glob("*.json")),
        ))

        direct_terminal_name = "direct_terminal_receipt_20260101"
        direct_terminal_code, direct_terminal_run, direct_terminal_pending, \
            direct_terminal_claims, direct_terminal_visible, \
            direct_terminal_claim_visible = seed_terminal_receipt_fsync_failure(
                direct_terminal_name, "direct-terminal-receipt")
        direct_terminal_retry = commit_activation_cas(
            direct_terminal_run,
            expected=pointer_snapshot(pointer),
            root=root,
            runs_root=runs,
            pointer=pointer,
            transaction_id=str(
                direct_terminal_visible.get("transaction_id") or ""),
            source_hash=str(
                direct_terminal_visible.get("source_sha256") or ""),
            effect_profile=direct_terminal_visible.get("effect_profile"),
            required_files=required,
            pending_dir=direct_terminal_pending,
            claims_dir=direct_terminal_claims,
        )
        checks.append((
            "direct create CAS retires a terminal receipt's historical binding",
            terminal_receipt_case.get("direct_retry") == "recovered"
            and direct_terminal_code == "receipt_durability_failed"
            and direct_terminal_visible.get("status") == "committed"
            and direct_terminal_claim_visible.get("status") == "claimed"
            and direct_terminal_retry.recovered
            and direct_terminal_retry.status == "recovered"
            and not list(direct_terminal_pending.glob("*.json"))
            and not list(direct_terminal_claims.glob("*.json")),
        ))

        publish_durability_case = next((
            case for case in spec.get("run_publish_durability_cases", [])
            if isinstance(case, dict) and case.get("failure") == "fsync"
        ), {})
        publish_run_name = "publish_durability_20260101"
        publish_before = pointer_snapshot(pointer)
        original_publish_os_fsync = os.fsync
        runs_root_stat = runs.stat()

        def fail_runs_root_fsync(fd: int) -> None:
            descriptor_stat = os.fstat(fd)
            if (descriptor_stat.st_dev, descriptor_stat.st_ino) == (
                runs_root_stat.st_dev,
                runs_root_stat.st_ino,
            ):
                raise OSError("injected formal-run directory fsync failure")
            original_publish_os_fsync(fd)

        try:
            os.fsync = fail_runs_root_fsync
            try:
                create_and_activate(
                    publish_run_name,
                    source_manifest=source,
                    build=_minimal_builder,
                    root=root,
                    runs_root=runs,
                    pointer=pointer,
                    required_files=required,
                )
                publish_durability_code = ""
                publish_transaction_id = ""
            except SetupTransactionError as exc:
                publish_durability_code = exc.code
                publish_transaction_id = exc.transaction_id
        finally:
            os.fsync = original_publish_os_fsync
        publish_run = runs / publish_run_name
        publish_pending = _read_receipt(publish_run)
        publish_after_failure = pointer_snapshot(pointer)
        original_publish_fsync_dir = globals()["_fsync_dir"]
        publish_retry_barriers = 0

        def count_publish_retry_barrier(
            path: Path, *, required: bool = False,
        ) -> None:
            nonlocal publish_retry_barriers
            if required and path.resolve() == runs.resolve():
                publish_retry_barriers += 1
            original_publish_fsync_dir(path, required=required)

        try:
            globals()["_fsync_dir"] = count_publish_retry_barrier
            publish_retry = create_and_activate(
                publish_run_name,
                source_manifest=source,
                build=_minimal_builder,
                root=root,
                runs_root=runs,
                pointer=pointer,
                required_files=required,
                transaction_id=publish_transaction_id,
            )
        finally:
            globals()["_fsync_dir"] = original_publish_fsync_dir
        checks.extend([
            (
                "run publish fsync failure leaves a prepared visible run",
                publish_durability_case.get("error")
                == publish_durability_code == "run_publish_durability_failed"
                and publish_durability_case.get("formal_run")
                == publish_pending.get("status") == "prepared_not_active"
                and publish_run.is_dir()
                and publish_durability_case.get("pointer") == "unchanged"
                and _same_snapshot(publish_after_failure, publish_before),
            ),
            (
                "exact publish retry repeats the run-directory barrier",
                publish_durability_case.get("retry") == "committed"
                and publish_retry.status == "committed"
                and publish_retry_barriers >= 1
                and _read_receipt(publish_run).get("status") == "committed",
            ),
        ])

        durability_cases = {
            str(case.get("failure") or ""): case
            for case in spec.get("directory_durability_cases", [])
            if isinstance(case, dict)
        }

        def retry_with_barrier_count(
            callback: Callable[[], TransactionResult],
        ) -> tuple[TransactionResult, int]:
            original_fsync_dir = globals()["_fsync_dir"]
            required_calls = 0

            def counting_fsync_dir(
                path: Path, *, required: bool = False,
            ) -> None:
                nonlocal required_calls
                if required and path.resolve() == pointer.parent.resolve():
                    required_calls += 1
                original_fsync_dir(path, required=required)

            try:
                globals()["_fsync_dir"] = counting_fsync_dir
                result = callback()
            finally:
                globals()["_fsync_dir"] = original_fsync_dir
            return result, required_calls

        # A directory-open failure happens after the pointer replace, but the
        # create receipt must remain recoverable and non-terminal.  The exact
        # create retry must run a fresh directory barrier before recovery.
        open_run_name = "durability_open_20260101"
        original_os_open = os.open

        def fail_pointer_directory_open(
            path: str | bytes | os.PathLike[str] | os.PathLike[bytes],
            flags: int,
            *args: object,
            **kwargs: object,
        ) -> int:
            if Path(os.fsdecode(path)).resolve() == pointer.parent.resolve():
                raise OSError("injected active-pointer directory open failure")
            return original_os_open(path, flags, *args, **kwargs)

        try:
            os.open = fail_pointer_directory_open
            try:
                create_and_activate(
                    open_run_name,
                    source_manifest=source,
                    build=_minimal_builder,
                    root=root,
                    runs_root=runs,
                    pointer=pointer,
                    required_files=required,
                )
                open_durability_code = ""
            except SetupTransactionError as exc:
                open_durability_code = exc.code
        finally:
            os.open = original_os_open
        open_run = runs / open_run_name
        open_pending = _read_receipt(open_run)
        open_retry, open_retry_barriers = retry_with_barrier_count(
            lambda: create_and_activate(
                open_run_name,
                source_manifest=source,
                build=_minimal_builder,
                root=root,
                runs_root=runs,
                pointer=pointer,
                required_files=required,
            )
        )
        open_after = _read_receipt(open_run)
        open_case = durability_cases.get("open", {})
        checks.extend([
            (
                "pointer directory open failure is explicit and non-terminal",
                open_case.get("error") == "pointer_durability_failed"
                and open_durability_code == "pointer_durability_failed"
                and open_pending.get("status")
                == open_case.get("receipt") == "prepared_not_active"
                and _pointer_target(
                    pointer_snapshot(pointer), root=root, runs_root=runs
                ) == open_run.resolve(),
            ),
            (
                "create retry repeats the pointer durability barrier",
                open_case.get("retry") == "recovered"
                and open_retry.recovered
                and open_retry_barriers >= 1
                and open_after.get("status") == "recovered",
            ),
        ])

        # A real directory-fsync failure on an activation attempt likewise
        # leaves the exact attempt/claim pending.  A different operation cannot
        # consume it, while the same operation retries the barrier and recovers.
        fsync_origin = runs / "durability_fsync_origin_20260101"
        (fsync_origin / "state").mkdir(parents=True)
        _atomic_write(
            pointer,
            (_pointer_ref(fsync_origin, root) + "\n").encode("utf-8"),
        )
        fsync_target, _ = seed_formal_run(
            "durability_fsync_target_20260101",
            status="prepared_not_active",
        )
        fsync_claims = root / "durability-fsync-claims"
        seed_activate_claim(
            fsync_origin,
            fsync_target,
            session_id="durability-fsync",
            operation=OP_STATUSLINE_SET_ACTIVE,
            claims_root=fsync_claims,
        )
        original_os_fsync = os.fsync
        pointer_parent_stat = pointer.parent.stat()

        def fail_pointer_directory_fsync(fd: int) -> None:
            descriptor_stat = os.fstat(fd)
            if (descriptor_stat.st_dev, descriptor_stat.st_ino) == (
                pointer_parent_stat.st_dev,
                pointer_parent_stat.st_ino,
            ):
                raise OSError("injected active-pointer directory fsync failure")
            original_os_fsync(fd)

        try:
            os.fsync = fail_pointer_directory_fsync
            try:
                activate_existing_run(
                    fsync_target,
                    root=root,
                    runs_root=runs,
                    pointer=pointer,
                    required_files=required,
                    claims_dir=fsync_claims,
                    pending_dir=root / "durability-fsync-pending",
                )
                fsync_durability_code = ""
            except SetupTransactionError as exc:
                fsync_durability_code = exc.code
        finally:
            os.fsync = original_os_fsync
        fsync_pending = _read_receipt(fsync_target)
        fsync_claim_pending = bool(list(fsync_claims.glob("*.json")))
        try:
            activate_existing_run(
                fsync_target,
                operation=OP_TRANSACTION_ACTIVATE,
                root=root,
                runs_root=runs,
                pointer=pointer,
                required_files=required,
                claims_dir=fsync_claims,
                pending_dir=root / "durability-fsync-pending",
            )
            fsync_cross_operation_code = ""
        except SetupTransactionError as exc:
            fsync_cross_operation_code = exc.code
        fsync_retry, fsync_retry_barriers = retry_with_barrier_count(
            lambda: activate_existing_run(
                fsync_target,
                root=root,
                runs_root=runs,
                pointer=pointer,
                required_files=required,
                claims_dir=fsync_claims,
                pending_dir=root / "durability-fsync-pending",
            )
        )
        fsync_after = _read_receipt(fsync_target)
        fsync_case = durability_cases.get("fsync", {})
        checks.extend([
            (
                "pointer directory fsync failure preserves pending authority",
                fsync_case.get("error") == "pointer_durability_failed"
                and fsync_durability_code == "pointer_durability_failed"
                and fsync_case.get("attempt") == "pending"
                and fsync_pending.get("activation_attempt", {}).get("status")
                == "pending"
                and _pointer_target(
                    pointer_snapshot(pointer), root=root, runs_root=runs
                ) == fsync_target.resolve()
                and fsync_claim_pending,
            ),
            (
                "durability retry rejects cross-operation relabeling",
                fsync_cross_operation_code == "activation_attempt_mismatch",
            ),
            (
                "same activation retry repeats the durability barrier",
                fsync_case.get("retry") == "recovered"
                and fsync_retry.recovered
                and fsync_retry_barriers >= 1
                and fsync_after.get("activation_attempt", {}).get("status")
                == "recovered"
                and not list(fsync_claims.glob("*.json")),
            ),
        ])

        activation_cases = {
            str(case.get("stage") or ""): case
            for case in spec.get("activation_attempt_cases", [])
            if isinstance(case, dict)
        }

        # A prepared formal run records the statusline activation separately.
        # A pre-pointer fault can be retried only with that exact operation and
        # never relabels the frozen create identity.
        prepared_activation_origin = runs / "prepared_activation_origin_20260101"
        (prepared_activation_origin / "state").mkdir(parents=True)
        _atomic_write(
            pointer,
            (_pointer_ref(prepared_activation_origin, root) + "\n").encode(
                "utf-8"),
        )
        prepared_activation_target, _ = seed_formal_run(
            "prepared_activation_target_20260101",
            status="prepared_not_active",
        )
        prepared_create_identity = frozen_create_identity(
            prepared_activation_target)
        prepared_activation_claims = root / "prepared-activation-claims"
        seed_activate_claim(
            prepared_activation_origin,
            prepared_activation_target,
            session_id="prepared-activation",
            operation=OP_STATUSLINE_SET_ACTIVE,
            claims_root=prepared_activation_claims,
        )

        def fail_activation_before_pointer(stage: str) -> None:
            if stage == "before_pointer_replace":
                raise RuntimeError("injected activation pre-pointer fault")

        def fail_activation_after_pointer(stage: str) -> None:
            if stage == "after_pointer_before_receipt":
                raise RuntimeError("injected activation post-pointer fault")

        prepared_create_name = "prepared_create_followup_20260101"
        prepared_create_pending = root / "prepared-create-followup-pending"
        prepared_create_claims = root / "prepared-create-followup-claims"
        prepared_create_session = "prepared-create-followup"
        seed_create_claim(
            prepared_create_name,
            prepared_create_session,
            pending_root=prepared_create_pending,
            claims_root=prepared_create_claims,
        )
        _atomic_write(pointer, b"runs/missing_prepared_create_origin_20260101\n")
        try:
            create_and_activate(
                prepared_create_name,
                source_manifest=source,
                build=_minimal_builder,
                root=root,
                runs_root=runs,
                pointer=pointer,
                required_files=required,
                pending_dir=prepared_create_pending,
                claims_dir=prepared_create_claims,
                fault=fail_activation_after_pointer,
            )
        except RuntimeError:
            prepared_create_faulted = True
        else:
            prepared_create_faulted = False
        turn_contract._revoke_pending_session(
            prepared_create_session,
            pending_dir=prepared_create_pending,
            claims_dir=prepared_create_claims,
            pointer=pointer,
        )
        fresh_prepared_contract = turn_contract._contract_from_event({
            "session_id": prepared_create_session,
            "prompt": (
                f"创建另一个新 run {prepared_create_name}，source "
                f"{source['source']['reference']}"
            ),
        }, run_name=prepared_create_name)
        turn_contract._atomic_json(
            turn_contract.contract_path(runs / prepared_create_name),
            fresh_prepared_contract,
            durable=True,
        )
        turn_contract.write_transition_claim(
            prepared_create_name,
            fresh_prepared_contract,
            claims_dir=prepared_create_claims,
            origin_run=prepared_create_name,
            effect=test_create_effect(prepared_create_name),
        )
        prepared_create_recovered = create_and_activate(
            prepared_create_name,
            source_manifest=source,
            build=_minimal_builder,
            root=root,
            runs_root=runs,
            pointer=pointer,
            required_files=required,
            pending_dir=prepared_create_pending,
            claims_dir=prepared_create_claims,
        )
        prepared_create_case = activation_cases.get(
            "prepared_create_after_pointer_new_prompt_same_effect", {})
        checks.append((
            "prepared create recovery retires old binding before fresh same-effect claim",
            prepared_create_faulted
            and prepared_create_case.get("old_claim") == "retired"
            and prepared_create_case.get("fresh_claim") == "consumed"
            and prepared_create_case.get("retry") == "recovered"
            and prepared_create_recovered.recovered
            and _read_receipt(
                runs / prepared_create_name).get("status") == "recovered"
            and not list(prepared_create_pending.glob("*.json"))
            and not list(prepared_create_claims.glob("*.json")),
        ))
        _atomic_write(
            pointer,
            (_pointer_ref(prepared_activation_origin, root) + "\n").encode(
                "utf-8"),
        )

        prepared_before = pointer_snapshot(pointer)
        try:
            activate_existing_run(
                prepared_activation_target,
                root=root,
                runs_root=runs,
                pointer=pointer,
                required_files=required,
                claims_dir=prepared_activation_claims,
                pending_dir=root / "prepared-activation-pending",
                fault=fail_activation_before_pointer,
            )
            prepared_activation_faulted = False
        except RuntimeError:
            prepared_activation_faulted = True
        prepared_after_fault_snapshot = pointer_snapshot(pointer)
        prepared_pending = _read_receipt(prepared_activation_target)
        prepared_pending_attempt = prepared_pending.get("activation_attempt", {})
        try:
            activate_existing_run(
                prepared_activation_target,
                operation=OP_TRANSACTION_ACTIVATE,
                root=root,
                runs_root=runs,
                pointer=pointer,
                required_files=required,
                claims_dir=prepared_activation_claims,
                pending_dir=root / "prepared-activation-pending",
            )
            prepared_cross_operation_rejected = False
        except SetupTransactionError as exc:
            prepared_cross_operation_rejected = \
                exc.code == "activation_attempt_mismatch"
        prepared_after_cross_snapshot = pointer_snapshot(pointer)
        prepared_recovered = activate_existing_run(
            prepared_activation_target,
            root=root,
            runs_root=runs,
            pointer=pointer,
            required_files=required,
            claims_dir=prepared_activation_claims,
            pending_dir=root / "prepared-activation-pending",
        )
        prepared_after = _read_receipt(prepared_activation_target)
        checks.extend([
            (
                "pre-pointer activation fault persists a frozen pending attempt",
                activation_cases.get("before_pointer_replace", {}).get(
                    "attempt") == "pending"
                and prepared_activation_faulted
                and prepared_pending_attempt.get("status") == "pending"
                and prepared_pending_attempt.get("effect", {}).get("operation")
                == OP_STATUSLINE_SET_ACTIVE
                and _same_snapshot(
                    prepared_after_fault_snapshot, prepared_before)
                and frozen_create_identity(prepared_activation_target)
                == prepared_create_identity,
            ),
            (
                "pending activation rejects a cross-operation retry",
                prepared_cross_operation_rejected
                and _same_snapshot(
                    prepared_after_cross_snapshot, prepared_before),
            ),
            (
                "same-operation retry commits the prepared activation",
                prepared_recovered.recovered
                and prepared_after.get("status") == "recovered"
                and prepared_after.get("activation_attempt", {}).get("status")
                == "recovered"
                and frozen_create_identity(prepared_activation_target)
                == prepared_create_identity
                and not list(prepared_activation_claims.glob("*.json")),
            ),
        ])

        prepared_post_origin = runs / "prepared_post_origin_20260101"
        (prepared_post_origin / "state").mkdir(parents=True)
        _atomic_write(
            pointer,
            (_pointer_ref(prepared_post_origin, root) + "\n").encode("utf-8"),
        )
        prepared_post_target, _ = seed_formal_run(
            "prepared_post_target_20260101",
            status="prepared_not_active",
        )
        prepared_post_identity = frozen_create_identity(prepared_post_target)
        prepared_post_claims = root / "prepared-post-claims"
        seed_activate_claim(
            prepared_post_origin,
            prepared_post_target,
            session_id="prepared-post",
            operation=OP_STATUSLINE_SET_ACTIVE,
            claims_root=prepared_post_claims,
        )
        try:
            activate_existing_run(
                prepared_post_target,
                root=root,
                runs_root=runs,
                pointer=pointer,
                required_files=required,
                claims_dir=prepared_post_claims,
                pending_dir=root / "prepared-post-pending",
                fault=fail_activation_after_pointer,
            )
            prepared_post_faulted = False
        except RuntimeError:
            prepared_post_faulted = True
        prepared_post_pending = _read_receipt(prepared_post_target)
        prepared_post_pointer = pointer_snapshot(pointer)
        prepared_post_recovered = activate_existing_run(
            prepared_post_target,
            root=root,
            runs_root=runs,
            pointer=pointer,
            required_files=required,
            claims_dir=prepared_post_claims,
            pending_dir=root / "prepared-post-pending",
        )
        prepared_post_after = _read_receipt(prepared_post_target)
        checks.append((
            "formal prepared activation recovers after pointer-before-receipt crash",
            prepared_post_faulted
            and _pointer_target(
                prepared_post_pointer, root=root, runs_root=runs
            ) == prepared_post_target.resolve()
            and prepared_post_pending.get("status") == "prepared_not_active"
            and prepared_post_pending.get("activation_attempt", {}).get("status")
            == "pending"
            and prepared_post_recovered.recovered
            and prepared_post_after.get("status") == "recovered"
            and prepared_post_after.get("activation_attempt", {}).get("status")
            == "recovered"
            and frozen_create_identity(prepared_post_target)
            == prepared_post_identity
            and not list(prepared_post_claims.glob("*.json")),
        ))

        # The same post-pointer crash must recover when the outer create receipt
        # was already committed, including a non-empty historical create claim.
        committed_activation_origin = runs / "committed_activation_origin_20260101"
        (committed_activation_origin / "state").mkdir(parents=True)
        _atomic_write(
            pointer,
            (_pointer_ref(committed_activation_origin, root) + "\n").encode(
                "utf-8"),
        )
        committed_create_identity = frozen_create_identity(claimed.run_dir)
        committed_activation_claims = root / "committed-activation-claims"
        seed_activate_claim(
            committed_activation_origin,
            claimed.run_dir,
            session_id="committed-activation",
            operation=OP_STATUSLINE_SET_ACTIVE,
            claims_root=committed_activation_claims,
        )

        try:
            activate_existing_run(
                claimed.run_dir,
                root=root,
                runs_root=runs,
                pointer=pointer,
                required_files=required,
                claims_dir=committed_activation_claims,
                pending_dir=root / "committed-activation-pending",
                fault=fail_activation_after_pointer,
            )
            committed_activation_faulted = False
        except RuntimeError:
            committed_activation_faulted = True
        committed_pending = _read_receipt(claimed.run_dir)
        committed_activation_recovered = activate_existing_run(
            claimed.run_dir,
            root=root,
            runs_root=runs,
            pointer=pointer,
            required_files=required,
            claims_dir=committed_activation_claims,
            pending_dir=root / "committed-activation-pending",
        )
        committed_after = _read_receipt(claimed.run_dir)
        checks.append((
            "post-pointer activation recovers independently of outer create status",
            activation_cases.get("after_pointer_before_receipt", {}).get(
                "pointer") == "target"
            and committed_activation_faulted
            and committed_pending.get("status") == "committed"
            and committed_pending.get("activation_attempt", {}).get("status")
            == "pending"
            and committed_activation_recovered.recovered
            and committed_after.get("status") == "committed"
            and committed_after.get("activation_attempt", {}).get("status")
            == "recovered"
            and frozen_create_identity(claimed.run_dir)
            == committed_create_identity
            and not list(committed_activation_claims.glob("*.json")),
        ))

        def seed_post_pointer_pending_activation(
            prefix: str,
            *,
            session_id: str,
        ) -> tuple[Path, Path, Path, dict]:
            origin = runs / f"{prefix}_origin_20260101"
            (origin / "state").mkdir(parents=True)
            _atomic_write(
                pointer,
                (_pointer_ref(origin, root) + "\n").encode("utf-8"),
            )
            target, _ = seed_formal_run(
                f"{prefix}_target_20260101", status="committed")
            claims_root = root / f"{prefix}-claims"
            pending_root = root / f"{prefix}-pending"
            seed_activate_claim(
                origin,
                target,
                session_id=session_id,
                operation=OP_STATUSLINE_SET_ACTIVE,
                claims_root=claims_root,
            )
            try:
                activate_existing_run(
                    target,
                    root=root,
                    runs_root=runs,
                    pointer=pointer,
                    required_files=required,
                    claims_dir=claims_root,
                    pending_dir=pending_root,
                    fault=fail_activation_after_pointer,
                )
            except RuntimeError:
                pass
            else:
                raise AssertionError("post-pointer activation fault did not fire")
            return target, claims_root, pending_root, frozen_create_identity(target)

        def replace_active_prompt_claim(
            target: Path,
            claims_root: Path,
            *,
            session_id: str,
            prompt: str,
            effect: dict,
        ) -> dict:
            turn_contract._revoke_transition_claims_unlocked(
                session_id, claims_dir=claims_root)
            contract = turn_contract._contract_from_event({
                "session_id": session_id,
                "prompt": prompt,
            }, run_name=target.name)
            turn_contract._atomic_json(
                turn_contract.contract_path(target), contract)
            turn_contract.write_transition_claim(
                target.name,
                contract,
                origin_run=target.name,
                claims_dir=claims_root,
                effect=effect,
            )
            return contract

        # A new same-operation prompt must not be reported successful while its
        # own claim remains live behind the recovered post-pointer attempt.
        followup_target, followup_claims, followup_pending, followup_identity = \
            seed_post_pointer_pending_activation(
                "activation_followup", session_id="activation-followup")
        followup_contract = replace_active_prompt_claim(
            followup_target,
            followup_claims,
            session_id="activation-followup",
            prompt=f"再次恢复 run runs/{followup_target.name}",
            effect=test_activate_effect(
                followup_target.name, OP_STATUSLINE_SET_ACTIVE),
        )
        followup_result = activate_existing_run(
            followup_target,
            root=root,
            runs_root=runs,
            pointer=pointer,
            required_files=required,
            claims_dir=followup_claims,
            pending_dir=followup_pending,
        )
        followup_receipt = _read_receipt(followup_target)
        checks.append((
            "post-pointer recovery consumes a new same-operation prompt claim",
            activation_cases.get(
                "after_pointer_new_prompt_same_operation", {}
            ).get("fresh_claim") == "consumed"
            and followup_result.recovered
            and followup_receipt.get("activation_attempt", {}).get("status")
            == "committed"
            and followup_receipt.get("activation_attempt", {}).get(
                "contract_binding", {}).get("prompt_sha256")
            == followup_contract.get("prompt_sha256")
            and frozen_create_identity(followup_target) == followup_identity
            and not list(followup_claims.glob("*.json")),
        ))

        # The create adapter has a different exact effect.  If it is the current
        # fresh prompt, the already-active identical transaction is reconciled
        # idempotently and that create claim is retired as well.
        create_followup_target, create_followup_claims, \
            create_followup_pending, create_followup_identity = \
            seed_post_pointer_pending_activation(
                "create_followup", session_id="create-followup")
        create_followup_contract = replace_active_prompt_claim(
            create_followup_target,
            create_followup_claims,
            session_id="create-followup",
            prompt=(
                f"创建新 run {create_followup_target.name}，source "
                f"{source['source']['reference']}"
            ),
            effect=test_create_effect(create_followup_target.name),
        )
        create_followup_result = create_and_activate(
            create_followup_target.name,
            source_manifest=source,
            build=builder_for(source, source_bytes),
            root=root,
            runs_root=runs,
            pointer=pointer,
            required_files=required,
            pending_dir=create_followup_pending,
            claims_dir=create_followup_claims,
        )
        create_followup_bound = turn_contract.load_contract(
            create_followup_target, session_id="create-followup")
        checks.append((
            "create recovery consumes only its fresh exact create claim",
            activation_cases.get(
                "after_pointer_new_prompt_create", {}
            ).get("fresh_claim") == "consumed"
            and create_followup_result.recovered
            and create_followup_bound.get("prompt_sha256")
            == create_followup_contract.get("prompt_sha256")
            and create_followup_bound.get("transition_claim", {}).get("effect")
            == test_create_effect(create_followup_target.name)
            and frozen_create_identity(create_followup_target)
            == create_followup_identity
            and not list(create_followup_claims.glob("*.json")),
        ))

        # A fresh claim for a different activation operation cannot be swept up
        # merely because an older same-target attempt is now recoverable.
        cross_target, cross_claims, cross_pending, _ = \
            seed_post_pointer_pending_activation(
                "cross_followup", session_id="cross-followup")
        replace_active_prompt_claim(
            cross_target,
            cross_claims,
            session_id="cross-followup",
            prompt=f"以 transaction adapter 恢复 run runs/{cross_target.name}",
            effect=test_activate_effect(
                cross_target.name, OP_TRANSACTION_ACTIVATE),
        )
        cross_before = pointer_snapshot(pointer)
        try:
            activate_existing_run(
                cross_target,
                root=root,
                runs_root=runs,
                pointer=pointer,
                required_files=required,
                claims_dir=cross_claims,
                pending_dir=cross_pending,
            )
            cross_rejected = False
        except SetupTransactionError as exc:
            cross_rejected = exc.code == "contract_claim_invalid"
        cross_claim_values = [
            json.loads(path.read_text(encoding="utf-8"))
            for path in cross_claims.glob("*.json")
        ]
        checks.append((
            "recovery never consumes a fresh cross-operation claim",
            activation_cases.get(
                "after_pointer_new_prompt_cross_operation", {}
            ).get("fresh_claim") == "preserved"
            and cross_rejected
            and _same_snapshot(pointer_snapshot(pointer), cross_before)
            and any(
                item.get("status") == "active"
                and item.get("effect") == test_activate_effect(
                    cross_target.name, OP_TRANSACTION_ACTIVATE)
                for item in cross_claim_values
            ),
        ))

        semantic_target, semantic_claims, semantic_pending, _ = \
            seed_post_pointer_pending_activation(
                "semantic_tamper", session_id="semantic-tamper")
        semantic_receipt = _read_receipt(semantic_target)
        semantic_receipt["activation_attempt"]["effect"] = \
            test_activate_effect(
                semantic_target.name, OP_TRANSACTION_ACTIVATE)
        semantic_receipt["activation_attempt"]["attempt_sha256"] = \
            _activation_attempt_digest(
                semantic_receipt["activation_attempt"])
        _write_receipt(semantic_target, semantic_receipt)
        semantic_before = pointer_snapshot(pointer)
        try:
            activate_existing_run(
                semantic_target,
                root=root,
                runs_root=runs,
                pointer=pointer,
                required_files=required,
                claims_dir=semantic_claims,
                pending_dir=semantic_pending,
            )
            semantic_rejected = False
        except SetupTransactionError as exc:
            semantic_rejected = exc.code == "invalid_activation_attempt"
        checks.append((
            "semantic activation tamper fails despite a recomputed self-hash",
            activation_cases.get("semantic_attempt_tamper", {}).get("result")
            == "denied"
            and semantic_rejected
            and _same_snapshot(pointer_snapshot(pointer), semantic_before)
            and bool(list(semantic_claims.glob("*.json"))),
        ))

        # A nested self-hash mismatch is a receipt-integrity failure, not a
        # reason to discard the activation identity or downgrade to direct shell.
        tampered_activation_origin = runs / "tampered_activation_origin_20260101"
        (tampered_activation_origin / "state").mkdir(parents=True)
        _atomic_write(
            pointer,
            (_pointer_ref(tampered_activation_origin, root) + "\n").encode(
                "utf-8"),
        )
        tampered_activation_target, _ = seed_formal_run(
            "tampered_activation_target_20260101",
            status="prepared_not_active",
        )
        tampered_activation_claims = root / "tampered-activation-claims"
        seed_activate_claim(
            tampered_activation_origin,
            tampered_activation_target,
            session_id="tampered-activation",
            operation=OP_STATUSLINE_SET_ACTIVE,
            claims_root=tampered_activation_claims,
        )
        try:
            activate_existing_run(
                tampered_activation_target,
                root=root,
                runs_root=runs,
                pointer=pointer,
                required_files=required,
                claims_dir=tampered_activation_claims,
                pending_dir=root / "tampered-activation-pending",
                fault=fail_activation_before_pointer,
            )
        except RuntimeError:
            pass
        tampered_receipt = _read_receipt(tampered_activation_target)
        tampered_receipt["activation_attempt"]["attempt_sha256"] = "0" * 64
        _write_receipt(tampered_activation_target, tampered_receipt)
        tampered_before = pointer_snapshot(pointer)
        try:
            activate_existing_run(
                tampered_activation_target,
                root=root,
                runs_root=runs,
                pointer=pointer,
                required_files=required,
                claims_dir=tampered_activation_claims,
                pending_dir=root / "tampered-activation-pending",
            )
            tampered_activation_rejected = False
        except SetupTransactionError as exc:
            tampered_activation_rejected = \
                exc.code == "invalid_activation_attempt"
        checks.append((
            "tampered activation attempt fails closed without moving the pointer",
            tampered_activation_rejected
            and _same_snapshot(pointer_snapshot(pointer), tampered_before)
            and bool(list(tampered_activation_claims.glob("*.json"))),
        ))

        wrong_status_origin = runs / "wrong_status_origin_20260101"
        wrong_status_target = runs / "wrong_status_target_20260101"
        (wrong_status_origin / "state").mkdir(parents=True)
        wrong_status_target.mkdir()
        wrong_status_contract = turn_contract._contract_from_event({
            "session_id": "wrong-status-transition",
            "prompt": f"/loop runs/{wrong_status_target.name}",
        }, run_name=wrong_status_origin.name)
        turn_contract._atomic_json(
            turn_contract.contract_path(wrong_status_origin),
            wrong_status_contract,
        )
        wrong_status_claims = root / "wrong-status-transition-claims"
        turn_contract.write_transition_claim(
            wrong_status_target.name, wrong_status_contract,
            origin_run=wrong_status_origin.name,
            claims_dir=wrong_status_claims,
            effect=test_activate_effect(
                wrong_status_target.name, OP_STATUSLINE_SET_ACTIVE),
        )
        _atomic_write(pointer, b"runs/wrong_status_origin_20260101\n")
        wrong_status_before = pointer_snapshot(pointer)
        try:
            activate_existing_run(
                wrong_status_target,
                operation=OP_TRANSACTION_ACTIVATE,
                root=root, runs_root=runs, pointer=pointer,
                pending_dir=root / "wrong-status-transition-pending",
                claims_dir=wrong_status_claims,
            )
            wrong_status_operation_rejected = False
        except SetupTransactionError as exc:
            wrong_status_operation_rejected = exc.code == "contract_claim_invalid"
        checks.append((
            "explicit generic activation cannot consume a statusline effect claim",
            wrong_status_operation_rejected
            and _same_snapshot(pointer_snapshot(pointer), wrong_status_before)
            and bool(list(wrong_status_claims.glob("*.json"))),
        ))

        overwritten_origin = runs / "overwritten_origin_20260101"
        overwritten_target = runs / "overwritten_target_20260101"
        (overwritten_origin / "state").mkdir(parents=True)
        overwritten_target.mkdir()
        overwritten_a = turn_contract._contract_from_event({
            "session_id": "overwritten-a",
            "prompt": f"/loop runs/{overwritten_target.name}",
        }, run_name=overwritten_origin.name)
        turn_contract._atomic_json(
            turn_contract.contract_path(overwritten_origin), overwritten_a)
        overwritten_claims = root / "overwritten-claims"
        turn_contract.write_transition_claim(
            overwritten_target.name, overwritten_a,
            origin_run=overwritten_origin.name,
            claims_dir=overwritten_claims,
            effect=test_activate_effect(overwritten_target.name),
        )
        overwritten_b = turn_contract._contract_from_event({
            "session_id": "overwritten-b", "prompt": "只查看状态",
        }, run_name=overwritten_origin.name)
        turn_contract._atomic_json(
            turn_contract.contract_path(overwritten_origin), overwritten_b)
        _atomic_write(pointer, b"runs/overwritten_origin_20260101\n")
        overwritten_before = pointer_snapshot(pointer)
        try:
            activate_existing_run(
                overwritten_target, operation=OP_TRANSACTION_ACTIVATE,
                root=root, runs_root=runs, pointer=pointer,
                pending_dir=root / "overwritten-pending",
                claims_dir=overwritten_claims,
            )
            overwritten_contract_denied = False
        except SetupTransactionError as exc:
            overwritten_contract_denied = exc.code == "contract_claim_invalid"
        checks.append((
            "active contract overwrite cannot rebind an in-flight claim",
            overwritten_contract_denied
            and _same_snapshot(pointer_snapshot(pointer), overwritten_before),
        ))

        for index, case in enumerate(spec.get("failure_cases", []), 1):
            stage = str(case["stage"])
            run_name = f"failure{index}_20260101"
            before = pointer_snapshot(pointer)

            def fail_at(observed: str, wanted: str = stage) -> None:
                if observed == wanted:
                    raise RuntimeError("injected " + wanted)

            try:
                create_and_activate(
                    run_name, source_manifest=source, build=_minimal_builder,
                    root=root, runs_root=runs, pointer=pointer,
                    required_files=required, fault=fail_at,
                )
                failed = False
            except SetupTransactionError:
                failed = True
            final = runs / run_name
            formal_state = str(case.get("formal_run") or "absent")
            published = formal_state != "absent"
            pointer_expectation = str(case.get("pointer") or "unchanged")
            checks.append((f"fault {stage} returns nonzero", failed))
            if pointer_expectation == "target":
                checks.append((
                    f"fault {stage} leaves the committed target pointer explainable",
                    _pointer_target(
                        pointer_snapshot(pointer), root=root, runs_root=runs
                    ) == final.resolve(),
                ))
            else:
                checks.append((f"fault {stage} preserves old pointer",
                               _same_snapshot(pointer_snapshot(pointer), before)))
            checks.append((f"fault {stage} has no false formal run",
                           final.exists() == published))
            if published:
                checks.append((
                    f"fault {stage} has expected formal receipt state",
                    _read_receipt(final).get("status") == formal_state,
                ))
            if pointer_expectation == "target":
                recovered_after_fault = activate_existing_run(
                    final, operation=OP_TRANSACTION_ACTIVATE,
                    root=root, runs_root=runs, pointer=pointer,
                    required_files=required,
                )
                checks.append((
                    f"fault {stage} is idempotently recoverable",
                    recovered_after_fault.recovered
                    and _read_receipt(final).get("status") == "recovered",
                ))

        same_tx_run = "same_tx_20260101"
        same_txid = "1" * 32

        def stop_before_pointer(stage: str) -> None:
            if stage == "before_pointer_replace":
                raise RuntimeError("stop before pointer")

        try:
            create_and_activate(
                same_tx_run,
                source_manifest=source,
                build=_minimal_builder,
                root=root,
                runs_root=runs,
                pointer=pointer,
                required_files=required,
                transaction_id=same_txid,
                fault=stop_before_pointer,
            )
            same_tx_prepared = False
        except SetupTransactionError:
            same_tx_prepared = True
        try:
            create_and_activate(
                same_tx_run,
                source_manifest=source,
                build=_minimal_builder,
                root=root,
                runs_root=runs,
                pointer=pointer,
                required_files=required,
            )
            new_tx_rejected = False
        except SetupTransactionError as exc:
            new_tx_rejected = exc.code == "prepared_not_active"
        same_tx_retry = create_and_activate(
            same_tx_run,
            source_manifest=source,
            build=_minimal_builder,
            root=root,
            runs_root=runs,
            pointer=pointer,
            required_files=required,
            transaction_id=same_txid,
        )
        checks.extend([
            ("published prepared run rejects a new transaction id",
             same_tx_prepared and new_tx_rejected),
            ("same transaction id can retry activation",
             same_tx_retry.status == "committed"
             and same_tx_retry.transaction_id == same_txid),
        ])

        cas_run = "cas_20260101"
        before_cas = pointer_snapshot(pointer)

        def change_pointer(stage: str) -> None:
            if stage == "before_pointer_cas":
                _atomic_write(pointer, b"runs/old_20260101\n")

        try:
            create_and_activate(
                cas_run, source_manifest=source, build=_minimal_builder,
                root=root, runs_root=runs, pointer=pointer,
                required_files=required, fault=change_pointer,
            )
            cas_failed = False
        except SetupTransactionError as exc:
            cas_failed = exc.code == "pointer_cas_mismatch"
        cas_dir = runs / cas_run
        checks.extend([
            ("pointer CAS mismatch fails", cas_failed),
            ("pointer CAS mismatch keeps concurrent value",
             pointer_snapshot(pointer).raw == "runs/old_20260101\n"),
            ("pointer CAS mismatch publishes explainable prepared run",
             _read_receipt(cas_dir).get("status") == "prepared_not_active"),
        ])
        recovered = activate_existing_run(
            cas_dir, operation=OP_TRANSACTION_ACTIVATE,
            root=root, runs_root=runs, pointer=pointer,
            required_files=required,
        )
        checks.extend([
            ("explicit resume activates prepared run", recovered.status == "committed"),
            ("prepared receipt becomes committed",
             _read_receipt(cas_dir).get("status") == "committed"),
        ])

        receipt_run = "receipt_20260101"

        def fail_receipt(stage: str) -> None:
            if stage == "after_pointer_before_receipt":
                raise RuntimeError("receipt write interrupted")

        try:
            create_and_activate(
                receipt_run, source_manifest=source, build=_minimal_builder,
                root=root, runs_root=runs, pointer=pointer,
                required_files=required, fault=fail_receipt,
            )
            receipt_failed = False
        except SetupTransactionError:
            receipt_failed = True
        receipt_dir = runs / receipt_run
        before_recovery_fault = pointer_snapshot(pointer)

        def fail_recovered_receipt(stage: str) -> None:
            if stage == "before_recovered_receipt":
                raise RuntimeError("recovered receipt interrupted")

        try:
            activate_existing_run(
                receipt_dir,
                operation=OP_TRANSACTION_ACTIVATE,
                root=root,
                runs_root=runs,
                pointer=pointer,
                required_files=required,
                fault=fail_recovered_receipt,
            )
            recovered_receipt_faulted = False
        except RuntimeError:
            recovered_receipt_faulted = True
        recovery_case_declared = any(
            str(item.get("stage") or "") == "before_recovered_receipt"
            for item in spec.get("recovery_failure_cases", [])
            if isinstance(item, dict)
        )
        retry = create_and_activate(
            receipt_run, source_manifest=source, build=_minimal_builder,
            root=root, runs_root=runs, pointer=pointer, required_files=required,
        )
        checks.extend([
            ("pointer-after-receipt fault reports failure", receipt_failed),
            ("recovered-receipt fault is declared and reports failure",
             recovery_case_declared and recovered_receipt_faulted),
            ("recovered-receipt fault preserves pointer and prepared receipt",
             _same_snapshot(pointer_snapshot(pointer), before_recovery_fault)
             and retry.recovered),
            ("pointer-after-receipt fault leaves prepared receipt",
             retry.recovered and _read_receipt(receipt_dir).get("status") == "recovered"),
            ("same source retry recovers without duplicate run",
             retry.run_dir.resolve() == receipt_dir.resolve()),
        ])

        # Session selection is a separate, hook-owned recovery capability.  It
        # records only an exact session/transcript/run identity after ownership
        # CAS, and can restore the pointer only behind an EXPLAIN-only barrier.
        session_root = root / "session-selection-project"
        session_runs = session_root / "runs"
        session_run = session_runs / "session_resume_20260101"
        (session_run / "state").mkdir(parents=True)
        (session_run / "target.md").write_text(
            "# session resume\n", encoding="utf-8")
        session_pointer = session_root / ".claude" / "xunji_active_run"
        session_pointer.parent.mkdir(parents=True)
        session_selections = session_pointer.parent / "session-selections"
        session_id = "session-resume-owner"
        transcript_path = str(session_root / "transcripts" / "session.jsonl")
        transcript_sha = _sha256(
            transcript_path.encode("utf-8", "replace"))
        session_prompt_sha = _sha256(b"resume protected run")
        callback_order: list[str] = []

        def select_session_run() -> tuple[PointerSnapshot, bytes, dict]:
            active_contract = {
                "schema": TURN_CONTRACT_SCHEMA,
                "mode": "EXECUTE",
                "session_id": session_id,
                "transcript_path": transcript_path,
                "prompt_sha256": session_prompt_sha,
                "bound_run": session_run.name,
                "authority_state": "active",
                "run_transition_requested": False,
                "run_bind_requested": False,
                "loop_requested": True,
                "lifecycle_operation": "loop",
                "updated_at": time.time(),
            }
            _atomic_json(
                session_run / "state" / "turn_contract.json",
                active_contract,
            )
            _atomic_write(
                session_pointer,
                (_pointer_ref(session_run, session_root) + "\n").encode("utf-8"),
            )
            raw = (session_run / "state" / "turn_contract.json").read_bytes()
            return pointer_snapshot(session_pointer), raw, active_contract

        def write_ended_contract(
            target: Path,
            raw_contract: bytes,
            contract: dict,
        ) -> dict:
            callback_order.append("owned-clear")
            if contract.get("authority_state") == "session_ended":
                return contract
            prior = str(contract.get("ended_from_contract_sha256") or "") \
                if contract.get("authority_state") == "session_ended" \
                else _sha256(raw_contract)
            value = {
                "schema": TURN_CONTRACT_SCHEMA,
                "mode": "EXPLAIN_ONLY",
                "session_id": session_id,
                "transcript_path": transcript_path,
                "transcript_sha256": transcript_sha,
                "prompt_sha256": session_prompt_sha,
                "bound_run": target.name,
                "authority_state": "session_ended",
                "resume_requires_prompt": True,
                "ended_from_contract_sha256": prior,
                "run_transition_requested": False,
                "run_bind_requested": False,
                "loop_requested": False,
                "lifecycle_operation": "none",
                "updated_at": time.time(),
            }
            _atomic_json(target / "state" / "turn_contract.json", value)
            return value

        def write_resume_barrier(target: Path, selection: dict) -> dict:
            callback_order.append("resume-barrier")
            value = {
                "schema": TURN_CONTRACT_SCHEMA,
                "mode": "EXPLAIN_ONLY",
                "session_id": session_id,
                "transcript_path": transcript_path,
                "transcript_sha256": transcript_sha,
                "prompt_sha256": session_prompt_sha,
                "bound_run": target.name,
                "authority_state": "resume_barrier",
                "resume_requires_prompt": True,
                "session_start_source": "resume",
                "resume_selection_sha256": selection["receipt_sha256"],
                "ended_from_contract_sha256": selection[
                    "active_contract_sha256"],
                "run_transition_requested": False,
                "run_bind_requested": False,
                "loop_requested": False,
                "lifecycle_operation": "none",
                "updated_at": time.time(),
            }
            _atomic_json(target / "state" / "turn_contract.json", value)
            return value

        def clean_session_authority() -> None:
            callback_order.append("cleanup")

        session_before, session_contract_raw, _session_contract = select_session_run()
        session_cleared = clear_activation_cas(
            expected=session_before,
            pointer=session_pointer,
            root=session_root,
            runs_root=session_runs,
            session_id=session_id,
            transcript_sha256=transcript_sha,
            contract_sha256=_sha256(session_contract_raw),
            selection_dir=session_selections,
            on_owned_clear=write_ended_contract,
            session_cleanup=clean_session_authority,
        )
        selection_path = session_selection_path(
            session_selections, session_id)
        selection_value = validate_session_selection(_read_json(selection_path))
        ended_contract = _read_json(
            session_run / "state" / "turn_contract.json")
        checks.extend([
            ("session clear writes selection only after owned contract callback",
             session_cleared and callback_order[:2] == ["owned-clear", "cleanup"]),
            ("session clear removes pointer and leaves a cleared exact receipt",
             not session_pointer.exists()
             and selection_value.get("status") == "cleared"
             and selection_value.get("session_id_sha256")
             == _sha256(session_id.encode("utf-8"))
            and selection_value.get("transcript_sha256") == transcript_sha
             and selection_value.get("run_name") == session_run.name
             and selection_value.get("legacy") is True
             and selection_value.get("st_dev")
             == int(session_run.stat().st_dev)
             and selection_value.get("st_ino")
             == int(session_run.stat().st_ino)),
            ("session clear retires executable authority before pointer removal",
             ended_contract.get("mode") == "EXPLAIN_ONLY"
             and ended_contract.get("authority_state") == "session_ended"
             and ended_contract.get("resume_requires_prompt") is True),
        ])

        callback_order.clear()
        session_restored = restore_session_activation_cas(
            session_id=session_id,
            transcript_sha256=transcript_sha,
            selection_dir=session_selections,
            on_resume_barrier=write_resume_barrier,
            pointer=session_pointer,
            root=session_root,
            runs_root=session_runs,
        )
        resumed_contract = _read_json(
            session_run / "state" / "turn_contract.json")
        checks.extend([
            ("same-session resume restores the exact run and consumes its receipt",
             session_restored
             and _pointer_target(
                 pointer_snapshot(session_pointer), root=session_root,
                 runs_root=session_runs) == session_run.resolve()
             and not selection_path.exists()),
            ("resume installs EXPLAIN-only prompt barrier before pointer write",
             callback_order == ["resume-barrier"]
             and resumed_contract.get("mode") == "EXPLAIN_ONLY"
             and resumed_contract.get("authority_state") == "resume_barrier"
             and resumed_contract.get("resume_requires_prompt") is True
             and resumed_contract.get("session_start_source") == "resume"),
            ("duplicate resume is idempotent after receipt consumption",
             restore_session_activation_cas(
                 session_id=session_id,
                 transcript_sha256=transcript_sha,
                 selection_dir=session_selections,
                 on_resume_barrier=write_resume_barrier,
                 pointer=session_pointer,
                 root=session_root,
                 runs_root=session_runs)),
        ])

        # A failed callback or mismatched ownership cannot mint a selection.
        callback_order.clear()
        bad_before, bad_raw, _bad_contract = select_session_run()
        wrong_contract_digest = "f" * 64
        try:
            clear_activation_cas(
                expected=bad_before,
                pointer=session_pointer,
                root=session_root,
                runs_root=session_runs,
                session_id=session_id,
                transcript_sha256=transcript_sha,
                contract_sha256=wrong_contract_digest,
                selection_dir=session_selections,
                on_owned_clear=write_ended_contract,
                session_cleanup=clean_session_authority,
            )
            wrong_owner_rejected = False
        except SetupTransactionError as exc:
            wrong_owner_rejected = exc.code == "session_owner_mismatch"
        checks.append((
            "failed contract CAS cannot invoke callback or write a selection",
            wrong_owner_rejected and callback_order == []
            and session_pointer.exists() and not selection_path.exists(),
        ))

        def unsafe_owned_clear(
            target: Path,
            _raw_contract: bytes,
            contract: dict,
        ) -> dict:
            value = dict(contract)
            value["mode"] = "EXECUTE"
            value["authority_state"] = "session_ended"
            value["transcript_sha256"] = transcript_sha
            value["resume_requires_prompt"] = True
            value["ended_from_contract_sha256"] = _sha256(bad_raw)
            _atomic_json(target / "state" / "turn_contract.json", value)
            return value

        try:
            clear_activation_cas(
                expected=bad_before,
                pointer=session_pointer,
                root=session_root,
                runs_root=session_runs,
                session_id=session_id,
                transcript_sha256=transcript_sha,
                contract_sha256=_sha256(bad_raw),
                selection_dir=session_selections,
                on_owned_clear=unsafe_owned_clear,
                session_cleanup=clean_session_authority,
            )
            unsafe_callback_rejected = False
        except SetupTransactionError as exc:
            unsafe_callback_rejected = exc.code == "invalid_resume_barrier"
        checks.append((
            "unsafe SessionEnd callback cannot clear pointer or mint receipt",
            unsafe_callback_rejected and session_pointer.exists()
            and not selection_path.exists(),
        ))

        # A per-session receipt is immutable authority.  A stale/different
        # mapping must fail before the callback can retire the current owner.
        existing_before, existing_raw, _ = select_session_run()
        conflicting_selection = _build_session_selection(
            session_id=session_id,
            transcript_sha256="b" * 64,
            target=session_run,
            root=session_root,
            pointer_snapshot_value=existing_before,
            active_contract_sha256=_sha256(existing_raw),
            ended_contract_sha256="c" * 64,
        )
        _atomic_json(selection_path, conflicting_selection)
        callback_order.clear()
        try:
            clear_activation_cas(
                expected=existing_before,
                pointer=session_pointer,
                root=session_root,
                runs_root=session_runs,
                session_id=session_id,
                transcript_sha256=transcript_sha,
                contract_sha256=_sha256(existing_raw),
                selection_dir=session_selections,
                on_owned_clear=write_ended_contract,
                session_cleanup=clean_session_authority,
            )
            conflicting_selection_rejected = False
        except SetupTransactionError as exc:
            conflicting_selection_rejected = \
                exc.code == "session_selection_mismatch"
        checks.append((
            "SessionEnd cannot overwrite another same-session selection",
            conflicting_selection_rejected and callback_order == []
            and session_pointer.exists()
            and _read_json(selection_path) == conflicting_selection,
        ))
        selection_path.unlink()

        # Cleanup remains inside the transaction boundary: it cannot swap the
        # validated ended barrier back to executable authority before unlink.
        cleanup_before, cleanup_raw, cleanup_contract = select_session_run()

        def revive_during_cleanup() -> None:
            revived = dict(cleanup_contract)
            revived["mode"] = "EXECUTE"
            revived["authority_state"] = "active"
            _atomic_json(
                session_run / "state" / "turn_contract.json", revived)

        try:
            clear_activation_cas(
                expected=cleanup_before,
                pointer=session_pointer,
                root=session_root,
                runs_root=session_runs,
                session_id=session_id,
                transcript_sha256=transcript_sha,
                contract_sha256=_sha256(cleanup_raw),
                selection_dir=session_selections,
                on_owned_clear=write_ended_contract,
                session_cleanup=revive_during_cleanup,
            )
            cleanup_revival_rejected = False
        except SetupTransactionError as exc:
            cleanup_revival_rejected = exc.code == "invalid_resume_barrier"
        checks.append((
            "SessionEnd cleanup cannot revive authority before pointer clear",
            cleanup_revival_rejected and session_pointer.exists()
            and not selection_path.exists(),
        ))

        # Re-seed after the intentionally unsafe callback changed the contract.
        retry_before, retry_raw, _retry_contract = select_session_run()

        def fail_after_selection(stage: str) -> None:
            if stage == "after_session_selection":
                raise RuntimeError("injected session selection fault")

        try:
            clear_activation_cas(
                expected=retry_before,
                pointer=session_pointer,
                root=session_root,
                runs_root=session_runs,
                session_id=session_id,
                transcript_sha256=transcript_sha,
                contract_sha256=_sha256(retry_raw),
                selection_dir=session_selections,
                on_owned_clear=write_ended_contract,
                session_cleanup=clean_session_authority,
                fault=fail_after_selection,
            )
            selection_faulted = False
        except RuntimeError:
            selection_faulted = True
        ended_retry_raw = (
            session_run / "state" / "turn_contract.json").read_bytes()
        retry_after_selection = clear_activation_cas(
            expected=pointer_snapshot(session_pointer),
            pointer=session_pointer,
            root=session_root,
            runs_root=session_runs,
            session_id=session_id,
            transcript_sha256=transcript_sha,
            contract_sha256=_sha256(ended_retry_raw),
            selection_dir=session_selections,
            on_owned_clear=write_ended_contract,
            session_cleanup=clean_session_authority,
        )
        checks.append((
            "SessionEnd receipt fault is safely retryable without old authority",
            selection_faulted and retry_after_selection
            and not session_pointer.exists()
            and _read_json(session_run / "state" / "turn_contract.json").get(
                "authority_state") == "session_ended",
        ))

        def fail_after_resume_barrier(stage: str) -> None:
            if stage == "after_resume_barrier":
                raise RuntimeError("injected resume barrier fault")

        try:
            restore_session_activation_cas(
                session_id=session_id,
                transcript_sha256=transcript_sha,
                selection_dir=session_selections,
                on_resume_barrier=write_resume_barrier,
                pointer=session_pointer,
                root=session_root,
                runs_root=session_runs,
                fault=fail_after_resume_barrier,
            )
            resume_barrier_faulted = False
        except RuntimeError:
            resume_barrier_faulted = True
        pointer_after_barrier_fault = pointer_snapshot(session_pointer)
        resume_barrier_retry = restore_session_activation_cas(
            session_id=session_id,
            transcript_sha256=transcript_sha,
            selection_dir=session_selections,
            on_resume_barrier=write_resume_barrier,
            pointer=session_pointer,
            root=session_root,
            runs_root=session_runs,
        )
        checks.append((
            "resume barrier fault keeps pointer absent and retries idempotently",
            resume_barrier_faulted and not pointer_after_barrier_fault.exists
            and resume_barrier_retry and session_pointer.exists()
            and not selection_path.exists(),
        ))

        # A post-pointer fault leaves a safe barrier plus receipt; retry consumes
        # the receipt without rewriting or replacing the same-run pointer.
        post_pointer_before, post_pointer_raw, _ = select_session_run()
        clear_activation_cas(
            expected=post_pointer_before,
            pointer=session_pointer,
            root=session_root,
            runs_root=session_runs,
            session_id=session_id,
            transcript_sha256=transcript_sha,
            contract_sha256=_sha256(post_pointer_raw),
            selection_dir=session_selections,
            on_owned_clear=write_ended_contract,
            session_cleanup=clean_session_authority,
        )

        def fail_after_resume_pointer(stage: str) -> None:
            if stage == "after_resume_pointer":
                raise RuntimeError("injected post-resume-pointer fault")

        try:
            restore_session_activation_cas(
                session_id=session_id,
                transcript_sha256=transcript_sha,
                selection_dir=session_selections,
                on_resume_barrier=write_resume_barrier,
                pointer=session_pointer,
                root=session_root,
                runs_root=session_runs,
                fault=fail_after_resume_pointer,
            )
            resume_pointer_faulted = False
        except RuntimeError:
            resume_pointer_faulted = True
        pointer_after_resume_fault = pointer_snapshot(session_pointer)
        resume_pointer_retry = restore_session_activation_cas(
            session_id=session_id,
            transcript_sha256=transcript_sha,
            selection_dir=session_selections,
            on_resume_barrier=write_resume_barrier,
            pointer=session_pointer,
            root=session_root,
            runs_root=session_runs,
        )
        checks.append((
            "post-pointer resume fault consumes exact receipt on retry",
            resume_pointer_faulted and pointer_after_resume_fault.exists
            and selection_path.exists() is False
            and resume_pointer_retry,
        ))

        resume_selection_case = next((
            case for case in spec.get("session_resume_durability_cases", [])
            if isinstance(case, dict)
            and case.get("failure") == "selection_delete_fsync"
        ), {})
        selection_durable_before, selection_durable_raw, _ = select_session_run()
        clear_activation_cas(
            expected=selection_durable_before,
            pointer=session_pointer,
            root=session_root,
            runs_root=session_runs,
            session_id=session_id,
            transcript_sha256=transcript_sha,
            contract_sha256=_sha256(selection_durable_raw),
            selection_dir=session_selections,
            on_owned_clear=write_ended_contract,
            session_cleanup=clean_session_authority,
        )
        original_selection_fsync_dir = globals()["_fsync_dir"]
        selection_barrier_failed = False

        def fail_selection_delete_barrier(
            path: Path, *, required: bool = False,
        ) -> None:
            nonlocal selection_barrier_failed
            if required and path.resolve() == session_selections.resolve() \
                    and not selection_barrier_failed:
                selection_barrier_failed = True
                raise _DirectoryDurabilityError(
                    "injected session selection deletion fsync")
            original_selection_fsync_dir(path, required=required)

        try:
            globals()["_fsync_dir"] = fail_selection_delete_barrier
            try:
                restore_session_activation_cas(
                    session_id=session_id,
                    transcript_sha256=transcript_sha,
                    selection_dir=session_selections,
                    on_resume_barrier=write_resume_barrier,
                    pointer=session_pointer,
                    root=session_root,
                    runs_root=session_runs,
                )
                selection_durability_code = ""
            except SetupTransactionError as exc:
                selection_durability_code = exc.code
        finally:
            globals()["_fsync_dir"] = original_selection_fsync_dir
        selection_durability_retry = restore_session_activation_cas(
            session_id=session_id,
            transcript_sha256=transcript_sha,
            selection_dir=session_selections,
            on_resume_barrier=write_resume_barrier,
            pointer=session_pointer,
            root=session_root,
            runs_root=session_runs,
        )
        checks.append((
            "SessionStart selection deletion fsync failure converges on retry",
            resume_selection_case.get("error")
            == selection_durability_code
            == "session_selection_durability_failed"
            and resume_selection_case.get("pointer") == "target"
            and session_pointer.exists()
            and resume_selection_case.get("selection") == "absent"
            and not selection_path.exists()
            and resume_selection_case.get("retry") == "recovered"
            and selection_durability_retry,
        ))

        # Prepare one more selection, then prove wrong transcript/session and a
        # competing pointer cannot consume or overwrite it.
        mismatch_before, mismatch_raw, _ = select_session_run()
        clear_activation_cas(
            expected=mismatch_before,
            pointer=session_pointer,
            root=session_root,
            runs_root=session_runs,
            session_id=session_id,
            transcript_sha256=transcript_sha,
            contract_sha256=_sha256(mismatch_raw),
            selection_dir=session_selections,
            on_owned_clear=write_ended_contract,
            session_cleanup=clean_session_authority,
        )
        try:
            restore_session_activation_cas(
                session_id=session_id,
                transcript_sha256="a" * 64,
                selection_dir=session_selections,
                on_resume_barrier=write_resume_barrier,
                pointer=session_pointer,
                root=session_root,
                runs_root=session_runs,
            )
            wrong_transcript_rejected = False
        except SetupTransactionError as exc:
            wrong_transcript_rejected = exc.code == "session_selection_mismatch"
        try:
            restore_session_activation_cas(
                session_id="different-session",
                transcript_sha256=transcript_sha,
                selection_dir=session_selections,
                on_resume_barrier=write_resume_barrier,
                pointer=session_pointer,
                root=session_root,
                runs_root=session_runs,
            )
            wrong_session_rejected = False
        except SetupTransactionError as exc:
            wrong_session_rejected = exc.code == "session_selection_missing"
        other_run = session_runs / "other_session_20260101"
        other_run.mkdir()
        _atomic_write(
            session_pointer,
            (_pointer_ref(other_run, session_root) + "\n").encode("utf-8"),
        )
        competing_before = pointer_snapshot(session_pointer)
        try:
            restore_session_activation_cas(
                session_id=session_id,
                transcript_sha256=transcript_sha,
                selection_dir=session_selections,
                on_resume_barrier=write_resume_barrier,
                pointer=session_pointer,
                root=session_root,
                runs_root=session_runs,
            )
            competing_pointer_rejected = False
        except SetupTransactionError as exc:
            competing_pointer_rejected = exc.code == "pointer_cas_mismatch"
        checks.extend([
            ("wrong transcript/session cannot consume a selection",
             wrong_transcript_rejected and wrong_session_rejected
             and selection_path.exists()),
            ("automatic resume never overwrites another active pointer",
             competing_pointer_rejected
             and _same_snapshot(
                 pointer_snapshot(session_pointer), competing_before)
             and selection_path.exists()),
        ])

        # A pathname is not an immutable legacy identity.  Replace the exact
        # directory while keeping its old inode alive under another name, then
        # prove the receipt cannot activate the newly-created object.
        session_pointer.unlink()
        displaced_run = session_runs / "displaced_session_20260101"
        session_run.rename(displaced_run)
        displaced_identity = (
            int(displaced_run.stat().st_dev), int(displaced_run.stat().st_ino))
        (session_run / "state").mkdir(parents=True)
        (session_run / "target.md").write_text(
            "# replacement legacy run\n", encoding="utf-8")
        replacement_identity = (
            int(session_run.stat().st_dev), int(session_run.stat().st_ino))
        shutil.rmtree(displaced_run)
        try:
            restore_session_activation_cas(
                session_id=session_id,
                transcript_sha256=transcript_sha,
                selection_dir=session_selections,
                on_resume_barrier=write_resume_barrier,
                pointer=session_pointer,
                root=session_root,
                runs_root=session_runs,
            )
            recreated_legacy_rejected = False
        except SetupTransactionError as exc:
            recreated_legacy_rejected = \
                exc.code == "invalid_session_selection"
        checks.append((
            "legacy selection rejects same-path run replacement",
            recreated_legacy_rejected and not session_pointer.exists()
            and selection_path.exists()
            and replacement_identity != displaced_identity,
        ))

        checks.append(("fixture schema", spec.get("schema") == "xunji.setup-transaction-fixture.v1"))
    finally:
        shutil.rmtree(temp, ignore_errors=True)

    bad = [name for name, ok in checks if not ok]
    for name, ok in checks:
        print(("ok   " if ok else "FAIL ") + name)
    print("setup_transaction selftest " + ("passed" if not bad else f"FAILED ({len(bad)})"))
    return 0 if not bad else 1


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Xunji setup transaction primitives")
    parser.add_argument("--selftest", action="store_true")
    args = parser.parse_args(argv)
    if args.selftest:
        return _selftest()
    parser.error("this module is an adapter API; use setup_run.py or loop_bootstrap.py")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
