#!/usr/bin/env python3
"""Schema-independent first-write journal for Claude SubagentStop delivery.

This Hook intentionally imports only the Python standard library.  It runs
before ``turn_contract.py`` and preserves one bounded, content-addressed
observation even when mutable work-plan/contract validation is unavailable.
The project-level receipt has no run owner and is never lifecycle, assignment,
review, evidence, merge, or closure truth.  A later typed recovery must bind it
to one run's canonical launch and SubagentStart before it may be cited.
"""
from __future__ import annotations

import contextlib
import hashlib
import json
import os
import re
import subprocess
import sys
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path

try:
    import fcntl
except ImportError:  # pragma: no cover - macOS/Linux are the supported hosts
    fcntl = None


ROOT = Path(__file__).resolve().parents[2]
INGRESS_ROOT = ROOT / ".claude" / "xunji_subagent_stop_ingress" / "v1"
SCHEMA = "xunji.subagent-stop-ingress.v1"
ERROR_CODE = "XUNJI_E_SUBAGENT_STOP_INGRESS_FAILED"
MAX_RESULT_BYTES = 16 * 1024 * 1024
# A JSON string may require six source bytes (``\\u0000``) for one decoded
# result byte.  Keep the transport envelope separately bounded without making
# the documented 16 MiB result limit unreachable at the wrapper boundary.
MAX_EVENT_BYTES = 6 * MAX_RESULT_BYTES + 64 * 1024
MAX_PATH_BYTES = 32 * 1024
_ID_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9_-]{0,127}")
_TYPE_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}")
_FIELDS = {
    "schema", "hook_event_name", "session_id", "agent_id", "agent_type",
    "transcript_path_sha256", "result_present", "result_length",
    "result_sha256", "canonical_event_sha256", "observed_at", "receipt_hash",
}
_RUNTIME_FAILURE_LINE = re.compile(
    rb"\[XUNJI_E_RUNTIME_RECEIPT_HOOK_FAILED\] SubagentStop runtime receipt "
    rb"recording failed closed: [A-Za-z][A-Za-z0-9_.]{0,127}\n?"
)


class SubagentStopIngressError(RuntimeError):
    """Stable failure at the pre-schema durability boundary."""


def _json_bytes(value: object) -> bytes:
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
    ).encode("utf-8")


def _digest(value: object) -> str:
    return hashlib.sha256(_json_bytes(value)).hexdigest()


def _iso_now() -> str:
    return datetime.fromtimestamp(time.time(), timezone.utc).isoformat(
        timespec="milliseconds").replace("+00:00", "Z")


def _valid_timestamp(value: object) -> bool:
    if not isinstance(value, str) or not 20 <= len(value) <= 64 \
            or not re.fullmatch(
            r"[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}"
            r"(?:\.[0-9]+)?(?:Z|[+-][0-9]{2}:[0-9]{2})", value):
        return False
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except Exception:
        return False
    return parsed.tzinfo is not None and parsed.utcoffset() is not None


def _result_bytes(value: object) -> tuple[bool, bytes]:
    if value in (None, "", {}, []):
        return False, b""
    try:
        payload = value.encode("utf-8") if isinstance(value, str) \
            else _json_bytes(value)
    except Exception as exc:
        raise SubagentStopIngressError(
            "last_assistant_message is not losslessly serializable") from exc
    if len(payload) > MAX_RESULT_BYTES:
        raise SubagentStopIngressError("last_assistant_message exceeds ingress limit")
    return True, payload


def _semantic_fields(event: dict) -> dict:
    if str(event.get("hook_event_name") or "") != "SubagentStop":
        return {}
    session_id = str(event.get("session_id") or "")
    agent_id = str(event.get("agent_id") or "")
    agent_type = str(event.get("agent_type") or "")
    transcript_path = str(event.get("transcript_path") or "")
    if not _ID_RE.fullmatch(session_id) or not _ID_RE.fullmatch(agent_id):
        raise SubagentStopIngressError("SubagentStop actor identity is invalid")
    if agent_type and not _TYPE_RE.fullmatch(agent_type):
        raise SubagentStopIngressError("SubagentStop agent type is invalid")
    try:
        transcript_bytes = transcript_path.encode("utf-8", "strict")
    except UnicodeEncodeError as exc:
        raise SubagentStopIngressError("SubagentStop transcript path is invalid") from exc
    if len(transcript_bytes) > MAX_PATH_BYTES:
        raise SubagentStopIngressError("SubagentStop transcript path exceeds ingress limit")
    result_present, result = _result_bytes(event.get("last_assistant_message"))
    return {
        "hook_event_name": "SubagentStop",
        "session_id": session_id,
        "agent_id": agent_id,
        "agent_type": agent_type,
        "transcript_path_sha256": hashlib.sha256(transcript_bytes).hexdigest()
            if transcript_path else "",
        "result_present": result_present,
        "result_length": len(result),
        "result_sha256": hashlib.sha256(result).hexdigest()
            if result_present else "",
    }


def _receipt_hash(receipt: dict) -> str:
    payload = dict(receipt)
    payload["receipt_hash"] = ""
    return _digest(payload)


def validate_receipt(receipt: object, *, filename: str = "") -> str:
    if not isinstance(receipt, dict) or set(receipt) != _FIELDS:
        return "invalid receipt shape"
    if receipt.get("schema") != SCHEMA \
            or receipt.get("hook_event_name") != "SubagentStop":
        return "invalid receipt identity"
    session_raw = receipt.get("session_id")
    agent_raw = receipt.get("agent_id")
    agent_type_raw = receipt.get("agent_type")
    if not isinstance(session_raw, str) or not isinstance(agent_raw, str) \
            or not isinstance(agent_type_raw, str):
        return "invalid receipt actor type"
    session_id = session_raw
    agent_id = agent_raw
    agent_type = agent_type_raw
    if not _ID_RE.fullmatch(session_id) or not _ID_RE.fullmatch(agent_id) \
            or (agent_type and not _TYPE_RE.fullmatch(agent_type)):
        return "invalid receipt actor"
    transcript_raw = receipt.get("transcript_path_sha256")
    if not isinstance(transcript_raw, str):
        return "invalid transcript digest type"
    transcript_digest = transcript_raw
    if transcript_digest and re.fullmatch(
            r"[0-9a-f]{64}", transcript_digest) is None:
        return "invalid transcript digest"
    present = receipt.get("result_present")
    length = receipt.get("result_length")
    result_raw = receipt.get("result_sha256")
    if not isinstance(result_raw, str):
        return "invalid result digest type"
    result_digest = result_raw
    if not isinstance(present, bool) or isinstance(length, bool) \
            or not isinstance(length, int) \
            or not 0 <= length <= MAX_RESULT_BYTES:
        return "invalid result metadata"
    if present:
        if length < 1 or re.fullmatch(r"[0-9a-f]{64}", result_digest) is None:
            return "invalid present result metadata"
    elif length != 0 or result_digest:
        return "invalid absent result metadata"
    semantic = {
        field: receipt.get(field) for field in (
            "hook_event_name", "session_id", "agent_id", "agent_type",
            "transcript_path_sha256", "result_present", "result_length",
            "result_sha256",
        )
    }
    canonical_raw = receipt.get("canonical_event_sha256")
    claimed_raw = receipt.get("receipt_hash")
    if not isinstance(canonical_raw, str) or not isinstance(claimed_raw, str):
        return "invalid receipt digest type"
    canonical = canonical_raw
    claimed = claimed_raw
    if canonical != _digest(semantic) \
            or re.fullmatch(r"[0-9a-f]{64}", claimed) is None \
            or claimed != _receipt_hash(receipt) \
            or not _valid_timestamp(receipt.get("observed_at")):
        return "invalid receipt digest or timestamp"
    if filename and filename != f"{canonical}.json":
        return "invalid receipt filename"
    return ""


def _fsync_directory(path: Path) -> None:
    flags = os.O_RDONLY
    if hasattr(os, "O_DIRECTORY"):
        flags |= os.O_DIRECTORY
    descriptor = os.open(path, flags)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _ensure_directory(path: Path) -> None:
    missing: list[Path] = []
    cursor = path
    while not cursor.exists():
        missing.append(cursor)
        cursor = cursor.parent
    if not cursor.is_dir() or cursor.is_symlink():
        raise SubagentStopIngressError("ingress owner directory is not regular")
    for directory in reversed(missing):
        created = False
        try:
            directory.mkdir(mode=0o700)
            created = True
        except FileExistsError:
            # Another wrapper process may be publishing the same first Stop.
            # Accept only the exact regular directory it won; symlinks and
            # non-directories remain fail-closed.
            pass
        if directory.is_symlink() or not directory.is_dir():
            raise SubagentStopIngressError(
                "ingress owner directory is not regular")
        if created:
            _fsync_directory(directory)
            _fsync_directory(directory.parent)
    if path.is_symlink() or not path.is_dir():
        raise SubagentStopIngressError("ingress directory is not regular")


def _atomic_receipt(path: Path, payload: bytes) -> None:
    _ensure_directory(path.parent)
    if path.is_symlink():
        raise SubagentStopIngressError("ingress receipt is not regular")
    if path.exists():
        if path.is_symlink() or not path.is_file() or path.read_bytes() != payload:
            raise SubagentStopIngressError("ingress receipt identity conflict")
        with path.open("rb", buffering=0) as handle:
            os.fsync(handle.fileno())
        _fsync_directory(path.parent)
        return
    descriptor, raw = tempfile.mkstemp(
        prefix=path.name + ".", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(descriptor, "wb", buffering=0) as handle:
            written = handle.write(payload)
            if written != len(payload):
                raise OSError(f"short ingress write: {written}/{len(payload)}")
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(raw, 0o600)
        os.replace(raw, path)
        _fsync_directory(path.parent)
    finally:
        try:
            os.unlink(raw)
        except FileNotFoundError:
            pass


@contextlib.contextmanager
def _capture_lock(ingress_root: Path):
    _ensure_directory(ingress_root)
    lock = ingress_root / ".capture.lock"
    if lock.is_symlink() or (lock.exists() and not lock.is_file()):
        raise SubagentStopIngressError("ingress lock is not regular")
    created = not lock.exists()
    with lock.open("a+", encoding="utf-8") as handle:
        try:
            os.chmod(lock, 0o600)
        except OSError:
            pass
        if created:
            handle.flush()
            os.fsync(handle.fileno())
            _fsync_directory(ingress_root)
        if fcntl is not None:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
        try:
            yield
        finally:
            if fcntl is not None:
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def capture(event: dict, *, ingress_root: Path | None = None) -> dict:
    ingress_root = Path(ingress_root or INGRESS_ROOT)
    semantic = _semantic_fields(event)
    if not semantic:
        return {}
    canonical = _digest(semantic)
    path = ingress_root / f"{canonical}.json"
    with _capture_lock(ingress_root):
        if path.exists():
            try:
                existing = json.loads(path.read_text(
                    encoding="utf-8", errors="strict"))
            except Exception as exc:
                raise SubagentStopIngressError(
                    "existing ingress receipt is unreadable") from exc
            error = validate_receipt(existing, filename=path.name)
            if error:
                raise SubagentStopIngressError(error)
            return existing
        receipt = {
            "schema": SCHEMA,
            **semantic,
            "canonical_event_sha256": canonical,
            "observed_at": _iso_now(),
            "receipt_hash": "",
        }
        receipt["receipt_hash"] = _receipt_hash(receipt)
        payload = json.dumps(
            receipt, ensure_ascii=False, indent=2, sort_keys=True,
        ).encode("utf-8") + b"\n"
        _atomic_receipt(path, payload)
        actual = json.loads(path.read_text(encoding="utf-8", errors="strict"))
        error = validate_receipt(actual, filename=path.name)
        if error:
            raise SubagentStopIngressError(error)
        return actual


def load_receipts(*, ingress_root: Path | None = None) -> list[dict]:
    ingress_root = Path(ingress_root or INGRESS_ROOT)
    if not ingress_root.exists():
        return []
    if ingress_root.is_symlink() or not ingress_root.is_dir():
        raise SubagentStopIngressError("ingress directory is not regular")
    receipts: list[dict] = []
    for path in sorted(ingress_root.glob("*.json")):
        if path.is_symlink() or not path.is_file():
            raise SubagentStopIngressError(
                f"ingress receipt is not regular: {path.name}")
        try:
            receipt = json.loads(path.read_text(
                encoding="utf-8", errors="strict"))
        except Exception as exc:
            raise SubagentStopIngressError(
                f"ingress receipt is unreadable: {path.name}") from exc
        error = validate_receipt(receipt, filename=path.name)
        if error:
            raise SubagentStopIngressError(
                f"ingress receipt {path.name} invalid: {error}")
        receipts.append(receipt)
    return receipts


def matching_receipt(
    start: dict,
    result: object,
    *,
    ingress_root: Path | None = None,
) -> dict:
    """Select ingress only after a run-owned Start supplies the exact identity."""
    result_present, payload = _result_bytes(result)
    transcript_path = str(start.get("transcript_path") or "")
    transcript_digest = hashlib.sha256(
        transcript_path.encode("utf-8", "strict")).hexdigest() \
        if transcript_path else ""
    result_digest = hashlib.sha256(payload).hexdigest() if result_present else ""
    matches: list[dict] = []
    for receipt in load_receipts(ingress_root=ingress_root):
        if str(receipt.get("session_id") or "") \
                != str(start.get("session_id") or "") \
                or str(receipt.get("agent_id") or "") \
                != str(start.get("agent_id") or ""):
            continue
        ingress_type = str(receipt.get("agent_type") or "")
        if ingress_type and ingress_type != str(start.get("agent_type") or ""):
            continue
        ingress_transcript = str(receipt.get("transcript_path_sha256") or "")
        if ingress_transcript and ingress_transcript != transcript_digest:
            continue
        if receipt.get("result_present") is True and (
                not result_present
                or int(receipt.get("result_length") or 0) != len(payload)
                or str(receipt.get("result_sha256") or "") != result_digest):
            continue
        matches.append(receipt)
    if len(matches) > 1:
        raise SubagentStopIngressError(
            "multiple ingress receipts match one run-owned SubagentStop")
    return matches[0] if matches else {}


def _delegate_turn_contract(raw: bytes) -> tuple[int, bytes, bytes]:
    """Run the mutable owner after ingress and normalize only failed startup.

    Successful delegation and an owner's already-typed failure preserve exact
    stdout/stderr bytes.  Import/startup/exec failures cannot supply that typed
    line, so the wrapper replaces their unbounded traceback with one stable
    recovery-compatible cause token.
    """
    try:
        completed = subprocess.run(
            [sys.executable, str(ROOT / "tools" / "turn_contract.py")],
            input=raw,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
        )
    except Exception as exc:
        diagnostic = (
            "[XUNJI_E_RUNTIME_RECEIPT_HOOK_FAILED] SubagentStop runtime "
            "receipt recording failed closed: "
            f"SchemaIndependentWrapperDelegateError.{type(exc).__name__}\n"
        ).encode("ascii")
        return 2, b"", diagnostic
    code = int(completed.returncode)
    stdout = bytes(completed.stdout or b"")
    stderr = bytes(completed.stderr or b"")
    if code != 0 and _RUNTIME_FAILURE_LINE.fullmatch(stderr) is None:
        safe_code = code if 1 <= code <= 255 else 2
        diagnostic = (
            "[XUNJI_E_RUNTIME_RECEIPT_HOOK_FAILED] SubagentStop runtime "
            "receipt recording failed closed: "
            f"SchemaIndependentWrapperDelegateExit.{safe_code}\n"
        ).encode("ascii")
        return safe_code, b"", diagnostic
    return code, stdout, stderr


def _selftest() -> int:
    from concurrent.futures import ThreadPoolExecutor
    from unittest import mock

    tools_path = str(ROOT / "tools")
    inserted_tools_path = tools_path not in sys.path
    if inserted_tools_path:
        sys.path.insert(0, tools_path)
    import contract_schema

    with tempfile.TemporaryDirectory(prefix="xunji-stop-ingress-") as raw:
        root = Path(raw) / "ingress"
        base = {
            "hook_event_name": "SubagentStop",
            "session_id": "session-001",
            "agent_id": "agent-001",
            "agent_type": "xunji-reviewer",
            "transcript_path": "/private/transcripts/session-001.jsonl",
            "last_assistant_message": "exact result",
        }
        first = capture(base, ingress_root=root)
        replay = capture(base, ingress_root=root)
        absent = capture({**base, "agent_id": "agent-002",
                          "last_assistant_message": ""}, ingress_root=root)
        selected = matching_receipt({
            "session_id": "session-001",
            "agent_id": "agent-001",
            "agent_type": "xunji-reviewer",
            "transcript_path": "/private/transcripts/session-001.jsonl",
        }, "exact result", ingress_root=root)
        missing_result_selected = matching_receipt({
            "session_id": "session-001",
            "agent_id": "agent-002",
            "agent_type": "xunji-reviewer",
            "transcript_path": "/private/transcripts/session-001.jsonl",
        }, "transcript-derived result", ingress_root=root)
        tamper_path = root / f"{first['canonical_event_sha256']}.json"
        exact = tamper_path.read_bytes()
        tampered = dict(first)
        tampered["agent_type"] = "xunji-hunter"
        tamper_path.write_text(
            json.dumps(tampered, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        tamper_detected = False
        try:
            load_receipts(ingress_root=root)
        except SubagentStopIngressError:
            tamper_detected = True
        tamper_path.write_bytes(exact)
        formal_valid = not contract_schema.named_schema_errors(
            first, "subagent-stop-ingress.v1.schema.json")
        unknown = dict(first, unexpected=True)
        absent_drift = dict(absent, result_sha256="a" * 64)
        actor_type_drift = dict(first, session_id=1)
        timestamp_drift = dict(first)
        timestamp_drift["observed_at"] = str(
            timestamp_drift["observed_at"]).replace("T", " ", 1)
        timestamp_drift["receipt_hash"] = _receipt_hash(timestamp_drift)
        validators_reject_drift = bool(
            validate_receipt(unknown)
            and contract_schema.named_schema_errors(
                unknown, "subagent-stop-ingress.v1.schema.json")
            and validate_receipt(absent_drift)
            and contract_schema.named_schema_errors(
                absent_drift, "subagent-stop-ingress.v1.schema.json")
            and validate_receipt(timestamp_drift)
            and contract_schema.named_schema_errors(
                timestamp_drift, "subagent-stop-ingress.v1.schema.json")
            and validate_receipt(actor_type_drift)
            and contract_schema.named_schema_errors(
                actor_type_drift, "subagent-stop-ingress.v1.schema.json")
        )

        concurrent_root = Path(raw) / "concurrent"
        with ThreadPoolExecutor(max_workers=8) as pool:
            concurrent = list(pool.map(
                lambda _index: capture(base, ingress_root=concurrent_root),
                range(16),
            ))
        concurrent_linearized = bool(
            len({item.get("receipt_hash") for item in concurrent}) == 1
            and len(load_receipts(ingress_root=concurrent_root)) == 1
        )

        symlink_root = Path(raw) / "symlink-receipt"
        _ensure_directory(symlink_root)
        symlink_semantic = _semantic_fields({
            **base, "agent_id": "agent-symlink",
        })
        symlink_path = symlink_root / f"{_digest(symlink_semantic)}.json"
        symlink_path.symlink_to(Path(raw) / "missing-victim")
        receipt_symlink_rejected = False
        try:
            capture({**base, "agent_id": "agent-symlink"},
                    ingress_root=symlink_root)
        except (OSError, SubagentStopIngressError):
            receipt_symlink_rejected = symlink_path.is_symlink()

        replace_root = Path(raw) / "replace-failure"
        replace_failed_closed = False
        with mock.patch.object(os, "replace",
                               side_effect=OSError("selftest replace")):
            try:
                capture({**base, "agent_id": "agent-replace"},
                        ingress_root=replace_root)
            except (OSError, SubagentStopIngressError):
                replace_failed_closed = not list(
                    replace_root.glob("*.json"))

        fsync_root = Path(raw) / "fsync-failure"
        fsync_failed_closed = False
        with mock.patch.object(os, "fsync",
                               side_effect=OSError("selftest fsync")):
            try:
                capture({**base, "agent_id": "agent-fsync"},
                        ingress_root=fsync_root)
            except (OSError, SubagentStopIngressError):
                fsync_failed_closed = not list(fsync_root.glob("*.json")) \
                    if fsync_root.exists() else True

        oversized_rejected = False
        exact_limit_admitted = False
        with mock.patch.object(sys.modules[__name__], "MAX_RESULT_BYTES", 8):
            exact_limit = capture({
                **base,
                "agent_id": "agent-exact-limit",
                "last_assistant_message": "12345678",
            }, ingress_root=Path(raw) / "exact-limit")
            exact_limit_admitted = exact_limit.get("result_length") == 8
            try:
                capture({
                    **base,
                    "agent_id": "agent-oversized",
                    "last_assistant_message": "123456789",
                }, ingress_root=Path(raw) / "oversized")
            except SubagentStopIngressError:
                oversized_rejected = True

        exact_failure = (
            b"[XUNJI_E_RUNTIME_RECEIPT_HOOK_FAILED] SubagentStop runtime "
            b"receipt recording failed closed: RuntimeError\n"
        )
        with mock.patch.object(subprocess, "run", return_value=(
                subprocess.CompletedProcess(
                    args=[], returncode=0, stdout=b"exact stdout",
                    stderr=b"exact stderr"))):
            delegated_success = _delegate_turn_contract(b"{}")
        with mock.patch.object(subprocess, "run", return_value=(
                subprocess.CompletedProcess(
                    args=[], returncode=2, stdout=b"", stderr=exact_failure))):
            delegated_typed_failure = _delegate_turn_contract(b"{}")
        with mock.patch.object(subprocess, "run", return_value=(
                subprocess.CompletedProcess(
                    args=[], returncode=1, stdout=b"partial",
                    stderr=b"Traceback: import failed\n"))):
            delegated_startup_failure = _delegate_turn_contract(b"{}")
        with mock.patch.object(
                subprocess, "run", side_effect=FileNotFoundError("selftest")):
            delegated_exec_failure = _delegate_turn_contract(b"{}")

        tail_drifts = [
            dict(first, **{field: str(first[field]) + suffix})
            for field in (
                "session_id", "agent_id", "agent_type",
                "transcript_path_sha256", "result_sha256",
                "canonical_event_sha256", "receipt_hash",
            )
            for suffix in ("\n", "\r")
        ]
        tail_drift_rejected = all(
            validate_receipt(item)
            and contract_schema.named_schema_errors(
                item, "subagent-stop-ingress.v1.schema.json")
            for item in tail_drifts
        )
        checks = [
            ("exact Stop ingress is content-addressed and replay-idempotent",
             first == replay and bool(first.get("receipt_hash"))),
            ("missing result still preserves a non-authoritative observation",
             absent.get("result_present") is False
             and absent.get("result_length") == 0),
            ("run-owned identity and present result select one exact ingress",
             selected.get("receipt_hash") == first.get("receipt_hash")),
            ("absent ingress result defers result truth to typed recovery",
             missing_result_selected.get("receipt_hash")
                == absent.get("receipt_hash")),
            ("ingress tamper fails closed", tamper_detected),
            ("emitter output satisfies both formal and stdlib validators",
             formal_valid),
            ("formal and stdlib validators reject shape/conditional drift",
             validators_reject_drift),
            ("concurrent identical ingress linearizes to one receipt",
             concurrent_linearized),
            ("receipt symlink cannot redirect ingress publication",
             receipt_symlink_rejected),
            ("replace and fsync failures leave no admitted ingress receipt",
             replace_failed_closed and fsync_failed_closed),
            ("oversized Agent result fails before ingress publication",
             exact_limit_admitted and oversized_rejected),
            ("formal and stdlib validators both reject CR/LF tail drift",
             tail_drift_rejected),
            ("delegate preserves success and owner-typed failure bytes",
             delegated_success == (0, b"exact stdout", b"exact stderr")
             and delegated_typed_failure == (2, b"", exact_failure)),
            ("delegate startup and exec failures normalize to recoverable tokens",
             delegated_startup_failure[0] == 1
             and delegated_startup_failure[1] == b""
             and delegated_startup_failure[2].endswith(
                 b"SchemaIndependentWrapperDelegateExit.1\n")
             and delegated_exec_failure[0] == 2
             and delegated_exec_failure[2].endswith(
                 b"SchemaIndependentWrapperDelegateError.FileNotFoundError\n")),
        ]
    if inserted_tools_path:
        sys.path.remove(tools_path)
    bad = [name for name, ok in checks if not ok]
    for name, ok in checks:
        print(("ok   " if ok else "FAIL ") + name)
    print("subagent_stop_ingress selftest " + (
        "passed" if not bad else f"FAILED ({len(bad)})"))
    return 0 if not bad else 1


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if args == ["--selftest"]:
        return _selftest()
    if args:
        raise SystemExit("usage: subagent_stop_ingress.py [--selftest]")
    raw = sys.stdin.buffer.read(MAX_EVENT_BYTES + 1)
    if len(raw) > MAX_EVENT_BYTES:
        print(f"[{ERROR_CODE}] hook payload exceeds ingress limit", file=sys.stderr)
        return 2
    try:
        event = json.loads(raw.decode("utf-8", "strict") or "{}")
        if not isinstance(event, dict):
            raise SubagentStopIngressError("hook payload is not an object")
        capture(event)
    except Exception as exc:
        print(f"[{ERROR_CODE}] {type(exc).__name__}", file=sys.stderr)
        return 2
    # One wrapper owns ordering: the observation is durable before any import or
    # schema lookup in turn_contract.py can begin.  Preserve the child's exact
    # stdout, stderr, and exit status so Claude Code retains normal Hook
    # semantics and the recovery proof can distinguish this cutover from the
    # legacy direct-turn_contract era.
    return_code, delegate_stdout, delegate_stderr = _delegate_turn_contract(raw)
    if delegate_stdout:
        sys.stdout.buffer.write(delegate_stdout)
        sys.stdout.buffer.flush()
    if delegate_stderr:
        sys.stderr.buffer.write(delegate_stderr)
        sys.stderr.buffer.flush()
    return return_code


if __name__ == "__main__":
    raise SystemExit(main())
