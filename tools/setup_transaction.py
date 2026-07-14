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
import contextlib
import hashlib
import json
import os
import re
import shutil
import tempfile
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Iterator, Optional

ROOT = Path(__file__).resolve().parents[1]
RUNS_ROOT = ROOT / "runs"
ACTIVE_POINTER = ROOT / ".claude" / "xunji_active_run"
STAGING_NAME = ".xunji_staging"
SETUP_LOCK_NAME = ".xunji_setup.lock"
ACTIVATION_LOCK_NAME = ".xunji_activation.lock"
SOURCE_SCHEMA = "xunji.setup_source.v1"
RECEIPT_SCHEMA = "xunji.setup_transaction.v1"
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


FaultInjector = Callable[[str], None]
BuildRun = Callable[[Path, Optional[FaultInjector]], None]
SourceValidator = Callable[[], None]


def _sha256(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _fsync_dir(path: Path) -> None:
    """Best-effort directory durability without changing transaction outcome."""
    try:
        fd = os.open(path, os.O_RDONLY)
    except (AttributeError, OSError):
        return
    try:
        os.fsync(fd)
    except OSError:
        pass
    finally:
        os.close(fd)


def _atomic_write(path: Path, raw: bytes, *, mode: int = 0o600) -> None:
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
        _fsync_dir(path.parent)
    finally:
        try:
            os.unlink(tmp_name)
        except FileNotFoundError:
            pass


def _atomic_json(path: Path, value: dict) -> None:
    _atomic_write(
        path,
        (json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode(
            "utf-8"
        ),
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
def _exclusive_directory_lock(
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
    if source.get("schema") != SOURCE_SCHEMA \
            or str(source.get("source_sha256") or "") != source_hash:
        raise SetupTransactionError(
            "transaction_identity_mismatch",
            "setup source manifest does not match transaction receipt",
            run_dir=run_dir,
            transaction_id=transaction_id,
        )


def _write_receipt(run_dir: Path, receipt: dict) -> None:
    value = dict(receipt)
    value["schema"] = RECEIPT_SCHEMA
    value["updated_at"] = time.time()
    _atomic_json(_receipt_path(run_dir), value)


def _validate_prepared_run(run_dir: Path, required_files: tuple[str, ...]) -> None:
    missing = [name for name in required_files if not (run_dir / name).exists()]
    if missing:
        raise SetupTransactionError(
            "incomplete_staging",
            "prepared run missing required files: " + ", ".join(missing),
            run_dir=run_dir,
        )
    source = _read_json(run_dir / SOURCE_REL)
    receipt = _read_receipt(run_dir)
    if source.get("schema") != SOURCE_SCHEMA or not source.get("source_sha256"):
        raise SetupTransactionError(
            "invalid_source_manifest", "prepared source manifest is invalid", run_dir=run_dir
        )
    if not receipt.get("transaction_id") or receipt.get("status") != "prepared":
        raise SetupTransactionError(
            "invalid_prepared_receipt", "prepared transaction receipt is invalid", run_dir=run_dir
        )
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


def _claim_or_transfer_contract(
    current: Path | None,
    target: Path,
    *,
    transaction_id: str,
    source_hash: str,
    pending_dir: Path | None,
    claims_dir: Path | None,
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
    if current is None:
        expected_run = target.name if transaction_id and source_hash else ""
        return turn_contract.claim_pending_contract(
            target,
            pending_dir=pending_dir,
            claims_dir=claims_dir,
            transaction_id=transaction_id,
            source_hash=source_hash,
            expected_run=expected_run,
        )
    return turn_contract.transfer_contract(
        current,
        target,
        transaction_id=transaction_id,
        source_hash=source_hash,
        expected_run=target.name if transaction_id and source_hash else "",
    )


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
    pending_dir: Path | None = None,
    claims_dir: Path | None = None,
    fault: FaultInjector | None = None,
) -> TransactionResult:
    """Atomically select ``run_dir`` iff the pointer still matches ``expected``."""
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
    lock = pointer.parent / ACTIVATION_LOCK_NAME
    with _exclusive_directory_lock(lock):
        current_snapshot = pointer_snapshot(pointer)
        current_target = _pointer_target(
            current_snapshot, root=root, runs_root=runs_root
        )
        if current_target == target:
            receipt_status = str(receipt.get("status") or "")
            needs_recovery = receipt_status in {"prepared", "prepared_not_active"}
            if needs_recovery:
                _invoke_fault(fault, "before_recovered_receipt")
                _finalize_receipt(target, recovered=True, pointer=pointer)
            return TransactionResult(
                target, transaction_id, source_hash,
                "recovered" if receipt_status == "recovered" or needs_recovery else "committed",
                recovered=needs_recovery,
            )
        if not _same_snapshot(current_snapshot, expected):
            if receipt:
                receipt.update({
                    "status": "prepared_not_active",
                    "last_error": "active pointer compare-and-swap mismatch",
                    "observed_pointer_sha256": current_snapshot.sha256,
                })
                _write_receipt(target, receipt)
            raise SetupTransactionError(
                "pointer_cas_mismatch",
                "active pointer changed during setup; prepared run was not activated",
                run_dir=target,
                transaction_id=transaction_id,
            )

        contract = _claim_or_transfer_contract(
            current_target,
            target,
            transaction_id=transaction_id,
            source_hash=source_hash,
            pending_dir=pending_dir,
            claims_dir=claims_dir,
        )
        if receipt and contract:
            receipt["contract_binding"] = {
                "session_id": str(contract.get("session_id") or ""),
                "prompt_sha256": str(contract.get("prompt_sha256") or ""),
                "source_sha256": source_hash,
                "transaction_id": transaction_id,
                "expected_run": target.name,
            }
            _write_receipt(target, receipt)

        _invoke_fault(fault, "before_pointer_replace")
        _atomic_write(pointer, (_pointer_ref(target, root) + "\n").encode("utf-8"))
        _invoke_fault(fault, "after_pointer_before_receipt")
        _finalize_receipt(target, recovered=False, pointer=pointer)
        return TransactionResult(target, transaction_id, source_hash, "committed")


def activate_existing_run(
    run_dir: Path,
    *,
    root: Path = ROOT,
    runs_root: Path = RUNS_ROOT,
    pointer: Path = ACTIVE_POINTER,
    pending_dir: Path | None = None,
    claims_dir: Path | None = None,
    fault: FaultInjector | None = None,
) -> TransactionResult:
    """Resume/set-active path through the same pointer CAS and receipt recovery."""
    receipt = _read_receipt(run_dir)
    return commit_activation_cas(
        run_dir,
        expected=pointer_snapshot(pointer),
        root=root,
        runs_root=runs_root,
        pointer=pointer,
        transaction_id=str(receipt.get("transaction_id") or ""),
        source_hash=str(receipt.get("source_sha256") or ""),
        allow_legacy=not bool(receipt),
        pending_dir=pending_dir,
        claims_dir=claims_dir,
        fault=fault,
    )


def clear_activation_cas(
    *,
    expected: PointerSnapshot,
    pointer: Path = ACTIVE_POINTER,
) -> bool:
    """Clear the pointer under the same activation lock; never clear then restore."""
    with _exclusive_directory_lock(pointer.parent / ACTIVATION_LOCK_NAME):
        current = pointer_snapshot(pointer)
        if not _same_snapshot(current, expected):
            raise SetupTransactionError(
                "pointer_cas_mismatch", "active pointer changed before clear"
            )
        if not current.exists:
            return False
        pointer.unlink()
        _fsync_dir(pointer.parent)
        return True


def _recover_existing(
    final_dir: Path,
    *,
    source_hash: str,
    root: Path,
    runs_root: Path,
    pointer: Path,
) -> TransactionResult | None:
    receipt = _read_receipt(final_dir)
    if not receipt or receipt.get("source_sha256") != source_hash:
        return None
    # Lock order is always setup -> activation.  Recovery must not inspect the
    # canonical pointer under only the setup lock while set-active/resume can
    # concurrently commit under the activation lock.
    with _exclusive_directory_lock(pointer.parent / ACTIVATION_LOCK_NAME):
        current = pointer_snapshot(pointer)
        if _pointer_target(
            current, root=root, runs_root=runs_root
        ) != final_dir.resolve():
            return None
        if receipt.get("status") in {"prepared", "prepared_not_active"}:
            _finalize_receipt(final_dir, recovered=True, pointer=pointer)
            return TransactionResult(
                final_dir,
                str(receipt.get("transaction_id") or ""),
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
    _validate_run_name(run_name)
    source = dict(source_manifest)
    if source.get("schema") != SOURCE_SCHEMA:
        raise SetupTransactionError("invalid_source_manifest", "unsupported source schema")
    source_hash = str(source.get("source_sha256") or "")
    if not re.fullmatch(r"[0-9a-f]{64}", source_hash):
        raise SetupTransactionError("invalid_source_hash", "source hash must be sha256")
    requested_txid = transaction_id or ""
    txid = requested_txid or uuid.uuid4().hex
    if not re.fullmatch(r"[0-9a-f]{32}", txid):
        raise SetupTransactionError("invalid_transaction_id", "transaction id is invalid")

    runs_root.mkdir(parents=True, exist_ok=True)
    final_dir = _inside(runs_root / run_name, runs_root)
    initial_pointer = pointer_snapshot(pointer)
    setup_lock = runs_root / SETUP_LOCK_NAME
    staging_parent = runs_root / STAGING_NAME
    staging_dir = staging_parent / f"{run_name}.{txid}"
    renamed = False

    with _exclusive_directory_lock(setup_lock):
        if final_dir.exists():
            recovered = _recover_existing(
                final_dir,
                source_hash=source_hash,
                root=root,
                runs_root=runs_root,
                pointer=pointer,
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
                "status": "prepared",
                "prepared_at": time.time(),
                "expected_pointer": {
                    "exists": initial_pointer.exists,
                    "sha256": initial_pointer.sha256,
                },
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
            _fsync_dir(runs_root)
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
        str(SOURCE_REL), str(RECEIPT_REL),
    )
    source_hash = _sha256(b"fixture-source")
    source = {
        "schema": SOURCE_SCHEMA,
        "kind": "target_url",
        "source_sha256": source_hash,
        "display": "https://example.test/",
    }
    checks: list[tuple[str, bool]] = []
    try:
        owner_failure_lock = root / ".owner-failure.lock"
        original_atomic_json = globals()["_atomic_json"]

        def fail_owner_json(path: Path, value: dict) -> None:
            if path.name == "owner.json":
                raise OSError("injected owner metadata failure")
            original_atomic_json(path, value)

        try:
            globals()["_atomic_json"] = fail_owner_json
            try:
                with _exclusive_directory_lock(owner_failure_lock):
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
            result.run_dir, root=root, runs_root=runs, pointer=pointer
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
                corrupt_run, root=root, runs_root=runs, pointer=pointer
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
            "schema": SOURCE_SCHEMA,
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
                mismatch_run, root=root, runs_root=runs, pointer=pointer
            )
            source_mismatch_rejected = False
        except SetupTransactionError as exc:
            source_mismatch_rejected = exc.code == "transaction_identity_mismatch"
        checks.append((
            "source manifest mismatch blocks formal activation",
            source_mismatch_rejected
            and _same_snapshot(pointer_snapshot(pointer), before_mismatch),
        ))

        # A malformed/dangling pointer is not a source of turn authority.  The
        # pending hook claim must still be consumed and transaction-bound.
        import sys
        sys.path.insert(0, str(ROOT / "tools"))
        import turn_contract

        _atomic_write(pointer, b"runs/missing_20260101\n")
        pending_dir = root / "pending"
        claims_dir = root / "claims"
        pending = turn_contract.write_pending_contract({
            "session_id": "setup-transaction-selftest",
            "prompt": "创建一个新 run claim_20260101",
        }, pending_dir=pending_dir)
        turn_contract.write_transition_claim(
            "claim_20260101", pending, claims_dir=claims_dir
        )
        claimed = create_and_activate(
            "claim_20260101", source_manifest=source, build=_minimal_builder,
            root=root, runs_root=runs, pointer=pointer, required_files=required,
            pending_dir=pending_dir, claims_dir=claims_dir,
        )
        claimed_receipt = _read_receipt(claimed.run_dir)
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
             == "setup-transaction-selftest"),
            ("consumed transition claim is not replayable",
             turn_contract.claim_pending_contract(
                 claimed.run_dir, pending_dir=pending_dir, claims_dir=claims_dir
             ) == {}),
        ])

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
                    final, root=root, runs_root=runs, pointer=pointer
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
            cas_dir, root=root, runs_root=runs, pointer=pointer
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
                root=root,
                runs_root=runs,
                pointer=pointer,
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
