#!/usr/bin/env python3
"""Dependency-free structural validation for Xunji JSON contracts.

The repository intentionally does not require the third-party ``jsonschema``
package at runtime.  This module is therefore the single implementation of the
Draft 2020-12 subset used by ``contracts/*.schema.json``.  Producers,
consumers, and conformance selftests must call the same validator instead of
maintaining local field whitelists.
"""
from __future__ import annotations

import contextlib
import hashlib
import json
import math
import os
import re
import sys
import tempfile
from datetime import datetime
from functools import lru_cache
from pathlib import Path

from harness import python_runtime

try:
    import fcntl
except ImportError:  # pragma: no cover - single-workstation Unix is primary
    fcntl = None


ROOT = Path(__file__).resolve().parents[1]
CONTRACTS = ROOT / "contracts"
SCHEMA_CANDIDATES = ROOT / "tmp" / "contract_schema_candidates"
SCHEMA_CANDIDATE_META = "xunji.contract-schema-candidate.v1"
MAX_SCHEMA_BYTES = 4 * 1024 * 1024


class ContractSchemaUnavailable(RuntimeError):
    """Stable, path-redacted diagnosis for one unreadable contract source."""

    def __init__(self, name: str, code: str, cause_class: str):
        self.schema_name = name
        self.code = code
        self.cause_class = cause_class
        super().__init__(
            f"contract schema is unavailable: {name} "
            f"[{code}:{cause_class}]; run "
            f"`{python_runtime.display_token()} "
            "tools/contract_schema.py --selftest`"
        )


def _schema_unavailable(name: str, exc: BaseException) \
        -> ContractSchemaUnavailable:
    if isinstance(exc, FileNotFoundError):
        code = "SCHEMA_NOT_FOUND"
    elif isinstance(exc, UnicodeDecodeError):
        code = "SCHEMA_UTF8_INVALID"
    elif isinstance(exc, json.JSONDecodeError):
        code = "SCHEMA_JSON_INVALID"
    elif isinstance(exc, OSError):
        code = "SCHEMA_READ_FAILED"
    else:
        code = "SCHEMA_INVALID"
    return ContractSchemaUnavailable(name, code, exc.__class__.__name__)


def _load_schema_path(name: str, path: Path) -> dict:
    """Read one exact schema path and retain a stable safe cause class."""
    try:
        text = path.read_text(encoding="utf-8", errors="strict")
        value = json.loads(text)
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise _schema_unavailable(name, exc) from exc
    if not isinstance(value, dict):
        exc = TypeError("schema document root must be an object")
        raise _schema_unavailable(name, exc) from exc
    return value

_LEGACY_TURN_CONTRACT_KEYSETS = frozenset({
    frozenset({
        "schema", "mode", "session_id", "transcript_path", "prompt_sha256",
        "prompt_excerpt", "memory_approved", "fanout_override", "updated_at",
    }),
    frozenset({
        "schema", "mode", "session_id", "transcript_path", "prompt_sha256",
        "prompt_excerpt", "memory_approved", "direct_egress_approved",
        "fanout_override", "origin_run", "bound_run", "updated_at",
        "coordination_signature", "fanout_epoch_started_at", "fanout_epoch_id",
    }),
    frozenset({
        "schema", "mode", "session_id", "transcript_path", "prompt_sha256",
        "prompt_excerpt", "source_sha256s", "source_ambiguous",
        "run_name_sha256s", "run_ambiguous", "slug_sha256s", "slug_ambiguous",
        "classify_approved", "ai_external_approved", "resume_current_approved",
        "lifecycle_operation", "memory_approved", "direct_egress_approved",
        "fanout_override", "loop_requested", "loop_source_kind",
        "run_bind_requested", "run_transition_requested", "origin_run",
        "bound_run", "updated_at", "coordination_signature",
        "fanout_epoch_started_at", "fanout_epoch_id",
    }),
    frozenset({
        "schema", "mode", "session_id", "reported_session_id",
        "session_binding_kind", "transcript_path", "prompt_sha256",
        "prompt_excerpt", "source_sha256s", "source_ambiguous",
        "source_identity_version", "lifecycle_source_hint", "run_name_sha256s",
        "run_ambiguous", "slug_sha256s", "slug_ambiguous", "classify_approved",
        "ai_external_approved", "resume_current_approved", "lifecycle_operation",
        "memory_approved", "direct_egress_approved", "target_egress_denied",
        "web_tools_denied", "fanout_override", "intent_normalizations",
        "loop_requested", "loop_source_kind", "run_bind_requested",
        "run_transition_requested", "origin_run", "bound_run", "updated_at",
        "operator_intent", "coordination_signature", "fanout_epoch_started_at",
        "fanout_epoch_id",
    }),
    frozenset({
        "schema", "mode", "session_id", "reported_session_id",
        "session_binding_kind", "transcript_path", "prompt_sha256",
        "prompt_excerpt", "source_sha256s", "source_ambiguous",
        "source_identity_version", "lifecycle_source_hint", "run_name_sha256s",
        "run_ambiguous", "slug_sha256s", "slug_ambiguous", "classify_approved",
        "ai_external_approved", "resume_current_approved", "lifecycle_operation",
        "intent_resolution", "model_lifecycle_candidate_allowed", "memory_approved",
        "direct_egress_approved", "target_egress_denied", "web_tools_denied",
        "lifecycle_scope", "fanout_override", "intent_normalizations",
        "loop_requested", "loop_source_kind", "run_bind_requested",
        "run_transition_requested", "origin_run", "bound_run", "updated_at",
        "operator_intent", "coordination_signature", "fanout_epoch_started_at",
        "fanout_epoch_id",
    }),
})


@lru_cache(maxsize=64)
def load_schema(name: str) -> dict:
    """Load one repository-owned schema document by basename."""
    if not re.fullmatch(r"[A-Za-z0-9._-]+\.json", str(name or "")):
        raise ValueError("contract schema name is invalid")
    return _load_schema_path(name, CONTRACTS / name)


def _publish_schema_name(name: str) -> str:
    value = str(name or "")
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]*\.schema\.json", value):
        raise ValueError("SCHEMA_PUBLISH_NAME_INVALID")
    return value


def _candidate_paths(
    name: str,
    *,
    candidate_root: Path = SCHEMA_CANDIDATES,
) -> tuple[Path, Path]:
    safe = _publish_schema_name(name)
    return candidate_root / safe, candidate_root / f"{safe}.base.json"


def _sha256(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def _schema_document_issues(name: str, payload: bytes) -> list[str]:
    if not payload or len(payload) > MAX_SCHEMA_BYTES:
        return ["schema candidate is empty or exceeds the publication limit"]
    try:
        value = json.loads(payload.decode("utf-8", "strict"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        return [f"schema candidate is not strict JSON: {type(exc).__name__}"]
    if not isinstance(value, dict):
        return ["schema candidate root is not an object"]
    if value.get("$schema") != "https://json-schema.org/draft/2020-12/schema":
        return ["schema candidate has no exact Draft 2020-12 declaration"]
    identifier = value.get("$id")
    if not isinstance(identifier, str) or not identifier.strip() \
            or len(identifier.encode("utf-8")) > 2048:
        return ["schema candidate has no bounded non-empty $id"]
    return []


def _fsync_directory(path: Path) -> None:
    flags = os.O_RDONLY
    if hasattr(os, "O_DIRECTORY"):
        flags |= os.O_DIRECTORY
    descriptor = os.open(path, flags)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _atomic_replace_bytes(path: Path, payload: bytes, *, mode: int) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, raw = tempfile.mkstemp(
        prefix=path.name + ".", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(descriptor, "wb", buffering=0) as handle:
            written = handle.write(payload)
            if written != len(payload):
                raise OSError(f"short schema publication write: {written}/{len(payload)}")
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(raw, mode)
        os.replace(raw, path)
        _fsync_directory(path.parent)
    finally:
        try:
            os.unlink(raw)
        except FileNotFoundError:
            pass


@contextlib.contextmanager
def _schema_publication_lock(candidate_root: Path):
    candidate_root.mkdir(parents=True, exist_ok=True)
    if candidate_root.is_symlink() or not candidate_root.is_dir():
        raise RuntimeError("SCHEMA_CANDIDATE_ROOT_INVALID")
    lock = candidate_root / ".publish.lock"
    if lock.is_symlink() or (lock.exists() and not lock.is_file()):
        raise RuntimeError("SCHEMA_PUBLISH_LOCK_INVALID")
    with lock.open("a+", encoding="utf-8") as handle:
        if fcntl is not None:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
        try:
            yield
        finally:
            if fcntl is not None:
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def _load_candidate_meta(path: Path, *, name: str) -> dict:
    try:
        value = json.loads(path.read_text(encoding="utf-8", errors="strict"))
    except Exception as exc:
        raise RuntimeError("SCHEMA_CANDIDATE_META_UNAVAILABLE") from exc
    if not isinstance(value, dict) or set(value) != {
            "schema", "name", "base_sha256"} \
            or value.get("schema") != SCHEMA_CANDIDATE_META \
            or value.get("name") != name \
            or (str(value.get("base_sha256") or "") != "" and re.fullmatch(
                r"[0-9a-f]{64}", str(value.get("base_sha256") or "")) is None):
        raise RuntimeError("SCHEMA_CANDIDATE_META_INVALID")
    return value


def prepare_schema_candidate(
    name: str,
    *,
    contracts_dir: Path = CONTRACTS,
    candidate_root: Path = SCHEMA_CANDIDATES,
) -> dict:
    """Create or reuse one CAS-bound ignored candidate for AI editing.

    An existing malformed publication is still a valid CAS base: copy its raw
    bytes into the ignored candidate and make the repair state explicit.  This
    keeps the only writable recovery route usable for the exact failure this
    tool exists to repair, while ``publish`` still refuses to replace the
    target until the candidate is a valid schema document.
    """
    name = _publish_schema_name(name)
    target = contracts_dir / name
    candidate, meta_path = _candidate_paths(name, candidate_root=candidate_root)
    with _schema_publication_lock(candidate_root):
        if target.is_symlink() or (target.exists() and not target.is_file()):
            raise RuntimeError("SCHEMA_PUBLISH_TARGET_INVALID")
        repair_issues: list[str] = []
        if target.exists():
            try:
                current = target.read_bytes()
            except OSError as exc:
                raise RuntimeError(
                    "SCHEMA_PUBLISH_TARGET_READ_FAILED:"
                    + type(exc).__name__) from exc
            repair_issues = _schema_document_issues(name, current)
            current_hash = _sha256(current)
        else:
            current = b""
            current_hash = ""
        if candidate.exists() or meta_path.exists():
            if candidate.is_symlink() or not candidate.is_file() \
                    or meta_path.is_symlink() or not meta_path.is_file():
                raise RuntimeError("SCHEMA_CANDIDATE_PATH_INVALID")
            meta = _load_candidate_meta(meta_path, name=name)
            if str(meta.get("base_sha256") or "") != current_hash:
                raise RuntimeError(
                    "SCHEMA_CANDIDATE_STALE; preserve or discard the existing "
                    "candidate explicitly before preparing a new base")
        else:
            initial = current if target.exists() else json.dumps({
                "$schema": "https://json-schema.org/draft/2020-12/schema",
                "$id": f"https://xunji.local/contracts/{name}",
                "type": "object",
                "additionalProperties": False,
                "properties": {},
            }, ensure_ascii=False, indent=2).encode("utf-8") + b"\n"
            _atomic_replace_bytes(candidate, initial, mode=0o600)
            meta = {
                "schema": SCHEMA_CANDIDATE_META,
                "name": name,
                "base_sha256": current_hash,
            }
            _atomic_replace_bytes(
                meta_path,
                json.dumps(meta, ensure_ascii=False, indent=2,
                           sort_keys=True).encode("utf-8") + b"\n",
                mode=0o600,
            )
    relative = candidate.relative_to(ROOT).as_posix() \
        if candidate.is_relative_to(ROOT) else str(candidate)
    return {
        "status": "prepared_repair" if repair_issues else "prepared",
        "name": name,
        "candidate": relative,
        "base_sha256": current_hash,
        "repair_required": bool(repair_issues),
        "target_diagnostic": repair_issues[0] if repair_issues else "",
        "next_argv": (
            f"{python_runtime.display_token()} "
            f"tools/contract_schema.py publish {name}"
        ),
    }


def publish_schema_candidate(
    name: str,
    *,
    contracts_dir: Path = CONTRACTS,
    candidate_root: Path = SCHEMA_CANDIDATES,
) -> dict:
    """Validate, CAS, and atomically replace exactly one published schema."""
    name = _publish_schema_name(name)
    target = contracts_dir / name
    candidate, meta_path = _candidate_paths(name, candidate_root=candidate_root)
    with _schema_publication_lock(candidate_root):
        if target.is_symlink() or (target.exists() and not target.is_file()) \
                or candidate.is_symlink() or not candidate.is_file():
            raise RuntimeError("SCHEMA_PUBLISH_PATH_UNAVAILABLE")
        meta = _load_candidate_meta(meta_path, name=name)
        previous = target.read_bytes() if target.exists() else b""
        current_hash = _sha256(previous) if target.exists() else ""
        base_hash = str(meta.get("base_sha256") or "")
        if current_hash != base_hash:
            raise RuntimeError("SCHEMA_PUBLISH_CAS_MISMATCH")
        proposed = candidate.read_bytes()
        issues = _schema_document_issues(name, proposed)
        if issues:
            raise RuntimeError("SCHEMA_CANDIDATE_INVALID:" + issues[0])
        # Validate every other published document before the target changes.
        for path in sorted(contracts_dir.glob("*.schema.json")):
            if path.name != name:
                if path.is_symlink() or not path.is_file():
                    raise RuntimeError(
                        "SCHEMA_PUBLISHED_PEER_INVALID:" + path.name)
                peer_payload = path.read_bytes()
                peer_issues = _schema_document_issues(
                    path.name, peer_payload)
                if peer_issues:
                    raise RuntimeError(
                        "SCHEMA_PUBLISHED_PEER_INVALID:"
                        + path.name + ":" + peer_issues[0])
                _load_schema_path(path.name, path)
        mode = (target.stat().st_mode & 0o777) if target.exists() else 0o644
        try:
            _atomic_replace_bytes(target, proposed, mode=mode or 0o644)
            _load_schema_path(name, target)
        except Exception as exc:
            if base_hash:
                _atomic_replace_bytes(target, previous, mode=mode or 0o644)
            elif target.exists():
                target.unlink()
                _fsync_directory(target.parent)
            load_schema.cache_clear()
            raise RuntimeError("SCHEMA_PUBLISH_ROLLED_BACK") from exc
        new_hash = _sha256(proposed)
        next_meta = {
            "schema": SCHEMA_CANDIDATE_META,
            "name": name,
            "base_sha256": new_hash,
        }
        _atomic_replace_bytes(
            meta_path,
            json.dumps(next_meta, ensure_ascii=False, indent=2,
                       sort_keys=True).encode("utf-8") + b"\n",
            mode=0o600,
        )
        load_schema.cache_clear()
    return {
        "status": "published" if new_hash != current_hash else "unchanged",
        "name": name,
        "previous_sha256": current_hash,
        "published_sha256": new_hash,
        "verification_argv": (
            f"{python_runtime.display_token()} "
            "tools/contract_schema.py --selftest"
        ),
    }


def discard_schema_candidate(
    name: str,
    *,
    candidate_root: Path = SCHEMA_CANDIDATES,
) -> dict:
    """Delete only the ignored candidate pair; published contracts are untouched."""
    name = _publish_schema_name(name)
    candidate, meta_path = _candidate_paths(name, candidate_root=candidate_root)
    removed: list[str] = []
    with _schema_publication_lock(candidate_root):
        for path in (candidate, meta_path):
            if not path.exists():
                continue
            if path.is_symlink() or not path.is_file():
                raise RuntimeError("SCHEMA_CANDIDATE_PATH_INVALID")
            path.unlink()
            removed.append(path.name)
        _fsync_directory(candidate_root)
    return {"status": "discarded", "name": name, "removed": removed}


def _type_matches(value: object, expected: str) -> bool:
    if expected == "object":
        return isinstance(value, dict)
    if expected == "array":
        return isinstance(value, list)
    if expected == "string":
        return isinstance(value, str)
    if expected == "integer":
        return isinstance(value, int) and not isinstance(value, bool)
    if expected == "number":
        return (
            isinstance(value, (int, float))
            and not isinstance(value, bool)
            and math.isfinite(value)
        )
    if expected == "boolean":
        return isinstance(value, bool)
    if expected == "null":
        return value is None
    return False


def _json_equal(left: object, right: object) -> bool:
    """Compare JSON values without Python's bool/int equality leak.

    JSON Schema treats booleans and numbers as different primitive types while
    numeric 1 and 1.0 are the same mathematical value.  Recurse so composite
    const/enum values preserve those semantics too.
    """
    if isinstance(left, bool) or isinstance(right, bool):
        return isinstance(left, bool) and isinstance(right, bool) and left is right
    if isinstance(left, (int, float)) and isinstance(right, (int, float)):
        return math.isfinite(left) and math.isfinite(right) and left == right
    if isinstance(left, dict) or isinstance(right, dict):
        return (
            isinstance(left, dict) and isinstance(right, dict)
            and set(left) == set(right)
            and all(_json_equal(left[key], right[key]) for key in left)
        )
    if isinstance(left, list) or isinstance(right, list):
        return (
            isinstance(left, list) and isinstance(right, list)
            and len(left) == len(right)
            and all(_json_equal(a, b) for a, b in zip(left, right))
        )
    return type(left) is type(right) and left == right


def _valid_datetime(value: str) -> bool:
    if not re.fullmatch(
            r"[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}"
            r"(?:\.[0-9]+)?(?:Z|[+-][0-9]{2}:[0-9]{2})", value):
        return False
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return False
    return parsed.tzinfo is not None and parsed.utcoffset() is not None


def schema_errors(
    value: object,
    schema: object,
    *,
    root: dict | None = None,
    documents: dict[str, dict] | None = None,
    path: str = "$",
) -> list[str]:
    """Return structural errors for the schema subset used by this project."""
    if schema is True:
        return []
    if schema is False:
        return [f"{path}: matched false schema"]
    if not isinstance(schema, dict):
        return [f"{path}: schema is not an object"]
    root = root or schema
    documents = documents or {}
    errors: list[str] = []
    ref = schema.get("$ref")
    if isinstance(ref, str):
        document_ref, separator, fragment = ref.partition("#")
        if document_ref:
            target_root = documents.get(document_ref)
            if target_root is None:
                return [f"{path}: unresolved external ref {ref}"]
        else:
            target_root = root
        target: object = target_root
        if separator and fragment:
            if not fragment.startswith("/"):
                return [f"{path}: unresolved ref {ref}"]
            for raw in fragment[1:].split("/"):
                token = raw.replace("~1", "/").replace("~0", "~")
                if not isinstance(target, dict) or token not in target:
                    return [f"{path}: unresolved ref {ref}"]
                target = target[token]
        # Draft 2020-12 treats $ref as an applicator, not as a replacement for
        # its containing schema.  Validate the referenced schema and then keep
        # evaluating sibling keywords against the referring document's root.
        errors.extend(schema_errors(
            value, target, root=target_root, documents=documents, path=path,
        ))
    elif "$ref" in schema:
        errors.append(f"{path}: $ref is not a string")

    def matches(candidate: object) -> bool:
        return not schema_errors(
            value, candidate, root=root, documents=documents, path=path,
        )

    all_of = schema.get("allOf")
    if isinstance(all_of, list):
        for child in all_of:
            errors.extend(schema_errors(
                value, child, root=root, documents=documents, path=path,
            ))
    one_of = schema.get("oneOf")
    if isinstance(one_of, list):
        count = sum(1 for child in one_of if matches(child))
        if count != 1:
            errors.append(f"{path}: oneOf matched {count}")
    any_of = schema.get("anyOf")
    if isinstance(any_of, list) and not any(matches(child) for child in any_of):
        errors.append(f"{path}: anyOf did not match")
    if "not" in schema and matches(schema["not"]):
        errors.append(f"{path}: matched forbidden schema")
    if "if" in schema:
        branch = schema.get("then") if matches(schema["if"]) else schema.get("else")
        if isinstance(branch, (dict, bool)):
            errors.extend(schema_errors(
                value, branch, root=root, documents=documents, path=path,
            ))

    expected_type = schema.get("type")
    if isinstance(expected_type, str):
        type_ok = _type_matches(value, expected_type)
    elif isinstance(expected_type, list) and all(
            isinstance(item, str) for item in expected_type):
        type_ok = any(_type_matches(value, item) for item in expected_type)
    else:
        type_ok = expected_type is None
    if not type_ok:
        errors.append(f"{path}: expected {expected_type}")
        return errors
    if "const" in schema and not _json_equal(value, schema["const"]):
        errors.append(f"{path}: const mismatch")
    enum = schema.get("enum")
    if isinstance(enum, list) and not any(
            _json_equal(value, candidate) for candidate in enum):
        errors.append(f"{path}: enum mismatch")

    if isinstance(value, str):
        if len(value) < int(schema.get("minLength", 0)):
            errors.append(f"{path}: shorter than minLength")
        if "maxLength" in schema and len(value) > int(schema["maxLength"]):
            errors.append(f"{path}: longer than maxLength")
        if "pattern" in schema and re.search(str(schema["pattern"]), value) is None:
            errors.append(f"{path}: pattern mismatch")
        if schema.get("format") == "date-time" and not _valid_datetime(value):
            errors.append(f"{path}: invalid date-time")
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        if not math.isfinite(value):
            errors.append(f"{path}: non-finite number")
        if "minimum" in schema and value < schema["minimum"]:
            errors.append(f"{path}: below minimum")
        if "maximum" in schema and value > schema["maximum"]:
            errors.append(f"{path}: above maximum")
        if "exclusiveMinimum" in schema and value <= schema["exclusiveMinimum"]:
            errors.append(f"{path}: below exclusiveMinimum")
        if "exclusiveMaximum" in schema and value >= schema["exclusiveMaximum"]:
            errors.append(f"{path}: above exclusiveMaximum")

    if isinstance(value, list):
        if len(value) < int(schema.get("minItems", 0)):
            errors.append(f"{path}: fewer than minItems")
        if "maxItems" in schema and len(value) > int(schema["maxItems"]):
            errors.append(f"{path}: more than maxItems")
        if schema.get("uniqueItems"):
            if any(
                _json_equal(item, previous)
                for index, item in enumerate(value)
                for previous in value[:index]
            ):
                errors.append(f"{path}: duplicate array item")
        item_schema = schema.get("items")
        if isinstance(item_schema, (dict, bool)):
            for index, item in enumerate(value):
                errors.extend(schema_errors(
                    item, item_schema, root=root, documents=documents,
                    path=f"{path}[{index}]",
                ))
        contains = schema.get("contains")
        if isinstance(contains, (dict, bool)):
            count = sum(
                1 for item in value
                if not schema_errors(
                    item, contains, root=root, documents=documents, path=path,
                )
            )
            minimum = int(schema.get("minContains", 1))
            maximum = schema.get("maxContains")
            if count < minimum or maximum is not None and count > int(maximum):
                errors.append(f"{path}: contains matched {count}")

    if isinstance(value, dict):
        required = schema.get("required", [])
        for key in required if isinstance(required, list) else []:
            if key not in value:
                errors.append(f"{path}: missing {key}")
        properties = schema.get("properties") \
            if isinstance(schema.get("properties"), dict) else {}
        extra = set(value) - set(properties)
        additional = schema.get("additionalProperties", True)
        if additional is False and extra:
            errors.append(f"{path}: unknown fields {sorted(extra)}")
        elif isinstance(additional, (dict, bool)) and additional is not True:
            for key in extra:
                errors.extend(schema_errors(
                    value[key], additional, root=root, documents=documents,
                    path=f"{path}.{key}",
                ))
        names = schema.get("propertyNames")
        if isinstance(names, (dict, bool)):
            for key in value:
                errors.extend(schema_errors(
                    key, names, root=root, documents=documents,
                    path=f"{path}.<name>",
                ))
        if len(value) < int(schema.get("minProperties", 0)):
            errors.append(f"{path}: fewer than minProperties")
        if "maxProperties" in schema and len(value) > int(schema["maxProperties"]):
            errors.append(f"{path}: more than maxProperties")
        for key, child in properties.items():
            if key in value and isinstance(child, (dict, bool)):
                errors.extend(schema_errors(
                    value[key], child, root=root, documents=documents,
                    path=f"{path}.{key}",
                ))
    return errors


def named_schema_errors(
    value: object,
    name: str,
    *,
    documents: dict[str, dict] | None = None,
) -> list[str]:
    """Validate against one repository contract document."""
    schema = load_schema(name)
    resolved = dict(documents or {})

    def collect(node: object) -> None:
        if isinstance(node, dict):
            ref = node.get("$ref")
            if isinstance(ref, str):
                document, _, _ = ref.partition("#")
                if document and document not in resolved:
                    resolved[document] = load_schema(document)
                    collect(resolved[document])
            for child in node.values():
                collect(child)
        elif isinstance(node, list):
            for child in node:
                collect(child)

    collect(schema)
    return schema_errors(value, schema, documents=resolved)


def turn_contract_errors(value: object, *, allow_legacy: bool = True) -> list[str]:
    """Validate the current writer shape or one frozen historical keyset.

    Legacy compatibility is exact: every admitted historical object must match
    one observed producer keyset and is still checked against the current field
    definitions.  Unknown or half-evolved combinations never enter this path.
    """
    schema = load_schema("turn-contract.v1.schema.json")
    errors = schema_errors(value, schema)
    if not errors or not allow_legacy or not isinstance(value, dict) \
            or value.get("schema") != "xunji.turn_contract.v1":
        return errors
    keys = frozenset(value)
    if keys not in _LEGACY_TURN_CONTRACT_KEYSETS:
        return errors
    properties = schema.get("properties") \
        if isinstance(schema.get("properties"), dict) else {}
    legacy_schema = {
        "type": "object",
        "additionalProperties": False,
        "required": sorted(keys),
        "properties": {key: properties[key] for key in keys if key in properties},
    }
    if set(legacy_schema["properties"]) != set(keys):
        return errors
    if "operator_intent" in keys:
        legacy_schema["properties"]["operator_intent"] = {
            "oneOf": [
                properties["operator_intent"],
                {
                    "type": "object",
                    "additionalProperties": False,
                    "required": [
                        "schema", "operation", "source_kind", "source_sha256",
                        "run_sha256", "route", "constraints",
                    ],
                    "properties": {
                        "schema": {"const": "xunji.operator_intent.v1"},
                        "operation": {
                            "enum": ["none", "resume", "source", "setup", "loop"],
                        },
                        "source_kind": {"enum": ["none", "url", "file", "run"]},
                        "source_sha256": {
                            "type": "string", "pattern": "^$|^[0-9a-f]{64}$",
                        },
                        "run_sha256": {
                            "type": "string", "pattern": "^$|^[0-9a-f]{64}$",
                        },
                        "route": {"enum": ["offline", "direct", "proxy"]},
                        "constraints": {
                            "type": "object",
                            "additionalProperties": False,
                            "required": [
                                "target_egress_denied", "web_tools_denied",
                                "framework_mutation",
                            ],
                            "properties": {
                                "target_egress_denied": {"type": "boolean"},
                                "web_tools_denied": {"type": "boolean"},
                                "framework_mutation": {"const": "maintenance-only"},
                            },
                        },
                    },
                },
            ],
        }
    return schema_errors(value, legacy_schema, root=schema)


def run_status_errors(value: object, *, allow_legacy: bool = True) -> list[str]:
    """Validate the dedicated run-status projection with exact old-ID migration."""
    errors = named_schema_errors(value, "run-status.v1.schema.json")
    if not errors or not allow_legacy or not isinstance(value, dict) \
            or value.get("schema") != "xunji.turn_contract.v1":
        return errors
    migrated = dict(value)
    migrated["schema"] = "xunji.run-status.v1"
    return named_schema_errors(migrated, "run-status.v1.schema.json")


def transition_claim_errors(value: object, *, allow_legacy: bool = True) -> list[str]:
    """Validate the dedicated claim shape with exact old-ID migration."""
    errors = named_schema_errors(value, "transition-claim.v1.schema.json")
    if not errors or not allow_legacy or not isinstance(value, dict) \
            or value.get("schema") != "xunji.turn_contract.v1":
        return errors
    migrated = dict(value)
    migrated["schema"] = "xunji.transition-claim.v1"
    return named_schema_errors(migrated, "transition-claim.v1.schema.json")


def _selftest() -> int:
    from unittest import mock
    closed = {
        "type": "object",
        "additionalProperties": False,
        "required": ["count", "when"],
        "properties": {
            "count": {"type": "integer", "minimum": 1},
            "when": {"type": "string", "format": "date-time"},
        },
    }
    valid = {"count": 1, "when": "2026-08-01T00:00:00Z"}
    union = {
        "oneOf": [
            {"type": "object", "required": ["left"]},
            {"type": "object", "required": ["right"]},
        ],
    }
    ref_root = {
        "$defs": {
            "nonempty": {"type": "string", "minLength": 1},
        },
    }
    ref_with_sibling = {
        "$ref": "#/$defs/nonempty",
        "maxLength": 3,
        "$defs": ref_root["$defs"],
    }
    schema_names = sorted(path.name for path in CONTRACTS.glob("*.schema.json"))
    with tempfile.TemporaryDirectory(prefix="xunji-contract-schema-") as raw:
        fixture_dir = Path(raw)
        missing_error = invalid_utf8_error = invalid_json_error = root_error = None
        try:
            _load_schema_path("missing.schema.json", fixture_dir / "missing.json")
        except ContractSchemaUnavailable as exc:
            missing_error = exc
        invalid_utf8 = fixture_dir / "invalid-utf8.json"
        invalid_utf8.write_bytes(b"{\xff}")
        try:
            _load_schema_path("invalid-utf8.schema.json", invalid_utf8)
        except ContractSchemaUnavailable as exc:
            invalid_utf8_error = exc
        invalid_json = fixture_dir / "invalid-json.json"
        invalid_json.write_text("{", encoding="utf-8")
        try:
            _load_schema_path("invalid-json.schema.json", invalid_json)
        except ContractSchemaUnavailable as exc:
            invalid_json_error = exc
        non_object = fixture_dir / "non-object.json"
        non_object.write_text("[]", encoding="utf-8")
        try:
            _load_schema_path("non-object.schema.json", non_object)
        except ContractSchemaUnavailable as exc:
            root_error = exc

    with tempfile.TemporaryDirectory(prefix="xunji-schema-publish-") as raw:
        publish_root = Path(raw)
        publish_contracts = publish_root / "contracts"
        publish_candidates = publish_root / "candidates"
        publish_contracts.mkdir()
        publish_name = "fixture.v1.schema.json"
        publish_target = publish_contracts / publish_name
        base_document = {
            "$schema": "https://json-schema.org/draft/2020-12/schema",
            "$id": "https://xunji.local/contracts/fixture.v1.schema.json",
            "type": "object",
            "additionalProperties": False,
        }
        base_bytes = json.dumps(
            base_document, ensure_ascii=False, indent=2,
        ).encode("utf-8") + b"\n"
        publish_target.write_bytes(base_bytes)
        prepared = prepare_schema_candidate(
            publish_name,
            contracts_dir=publish_contracts,
            candidate_root=publish_candidates,
        )
        publish_candidate, _publish_meta = _candidate_paths(
            publish_name, candidate_root=publish_candidates)
        publish_candidate.write_text("{", encoding="utf-8")
        malformed_rejected = False
        try:
            publish_schema_candidate(
                publish_name,
                contracts_dir=publish_contracts,
                candidate_root=publish_candidates,
            )
        except RuntimeError as exc:
            malformed_rejected = "SCHEMA_CANDIDATE_INVALID" in str(exc)
        malformed_preserved = publish_target.read_bytes() == base_bytes
        next_document = dict(base_document, description="atomic candidate")
        publish_candidate.write_text(
            json.dumps(next_document, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        published = publish_schema_candidate(
            publish_name,
            contracts_dir=publish_contracts,
            candidate_root=publish_candidates,
        )
        published_bytes = publish_target.read_bytes()
        stale_document = dict(next_document, description="concurrent publisher")
        publish_target.write_text(
            json.dumps(stale_document, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        stale_rejected = False
        try:
            publish_schema_candidate(
                publish_name,
                contracts_dir=publish_contracts,
                candidate_root=publish_candidates,
            )
        except RuntimeError as exc:
            stale_rejected = "SCHEMA_PUBLISH_CAS_MISMATCH" in str(exc)
        discarded = discard_schema_candidate(
            publish_name, candidate_root=publish_candidates)
        stale_target_document = json.loads(
            publish_target.read_text(encoding="utf-8"))

        new_name = "new-fixture.v1.schema.json"
        new_prepared = prepare_schema_candidate(
            new_name,
            contracts_dir=publish_contracts,
            candidate_root=publish_candidates,
        )
        new_published = publish_schema_candidate(
            new_name,
            contracts_dir=publish_contracts,
            candidate_root=publish_candidates,
        )
        new_target = publish_contracts / new_name
        new_target_valid = bool(
            new_prepared.get("base_sha256") == ""
            and new_published.get("status") == "published"
            and not _schema_document_issues(
                new_name, new_target.read_bytes())
        )
        discard_schema_candidate(
            new_name, candidate_root=publish_candidates)

        repair_name = "broken-fixture.v1.schema.json"
        repair_target = publish_contracts / repair_name
        broken_bytes = b'{"$schema":'
        repair_target.write_bytes(broken_bytes)
        repair_prepared = prepare_schema_candidate(
            repair_name,
            contracts_dir=publish_contracts,
            candidate_root=publish_candidates,
        )
        repair_candidate, _repair_meta = _candidate_paths(
            repair_name, candidate_root=publish_candidates)
        repair_seed_preserved = repair_candidate.read_bytes() == broken_bytes
        repair_document = {
            "$schema": "https://json-schema.org/draft/2020-12/schema",
            "$id": (
                "https://xunji.local/contracts/"
                "broken-fixture.v1.schema.json"
            ),
            "type": "object",
            "additionalProperties": False,
        }
        repair_candidate.write_text(
            json.dumps(repair_document, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        repair_published = publish_schema_candidate(
            repair_name,
            contracts_dir=publish_contracts,
            candidate_root=publish_candidates,
        )
        repaired_target_valid = bool(
            repair_published.get("status") == "published"
            and json.loads(repair_target.read_text(encoding="utf-8"))
                == repair_document
        )
        discard_schema_candidate(
            repair_name, candidate_root=publish_candidates)

    with tempfile.TemporaryDirectory(prefix="xunji-schema-rollback-") as raw:
        rollback_root = Path(raw)
        rollback_contracts = rollback_root / "contracts"
        rollback_candidates = rollback_root / "candidates"
        rollback_contracts.mkdir()
        rollback_name = "rollback.v1.schema.json"
        rollback_target = rollback_contracts / rollback_name
        rollback_base = {
            "$schema": "https://json-schema.org/draft/2020-12/schema",
            "$id": "https://xunji.local/contracts/rollback.v1.schema.json",
            "type": "object",
        }
        rollback_base_bytes = json.dumps(
            rollback_base, ensure_ascii=False, indent=2,
        ).encode("utf-8") + b"\n"
        rollback_target.write_bytes(rollback_base_bytes)
        prepare_schema_candidate(
            rollback_name,
            contracts_dir=rollback_contracts,
            candidate_root=rollback_candidates,
        )
        rollback_candidate, _rollback_meta = _candidate_paths(
            rollback_name, candidate_root=rollback_candidates)
        rollback_candidate.write_text(json.dumps({
            **rollback_base,
            "description": "candidate requiring rollback",
        }, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        rollback_reported = False
        with mock.patch.object(
                sys.modules[__name__], "_load_schema_path",
                side_effect=ContractSchemaUnavailable(
                    rollback_name, "SCHEMA_READ_FAILED", "OSError")):
            try:
                publish_schema_candidate(
                    rollback_name,
                    contracts_dir=rollback_contracts,
                    candidate_root=rollback_candidates,
                )
            except RuntimeError as exc:
                rollback_reported = "SCHEMA_PUBLISH_ROLLED_BACK" in str(exc)
        rollback_restored = rollback_target.read_bytes() == rollback_base_bytes

    checks = [
        ("all published contract documents load", bool(schema_names)
         and all(isinstance(load_schema(name), dict) for name in schema_names)),
        ("missing schema reports stable safe cause and exact selftest", bool(
            missing_error
            and missing_error.code == "SCHEMA_NOT_FOUND"
            and missing_error.cause_class == "FileNotFoundError"
            and ".venv/bin/python tools/contract_schema.py --selftest"
            in str(missing_error)
        )),
        ("invalid UTF-8 and JSON remain distinguishable", bool(
            invalid_utf8_error
            and invalid_utf8_error.code == "SCHEMA_UTF8_INVALID"
            and invalid_json_error
            and invalid_json_error.code == "SCHEMA_JSON_INVALID"
        )),
        ("non-object schema has a stable invalid-root diagnosis", bool(
            root_error
            and root_error.code == "SCHEMA_INVALID"
            and root_error.cause_class == "TypeError"
        )),
        ("schema prepare emits one exact ignored-candidate publication argv", bool(
            prepared.get("status") == "prepared"
            and prepared.get("next_argv")
                == ".venv/bin/python tools/contract_schema.py "
                   "publish fixture.v1.schema.json"
        )),
        ("malformed candidate cannot change the published schema",
         malformed_rejected and malformed_preserved),
        ("validated schema publication uses the exact candidate bytes", bool(
            published.get("status") == "published"
            and json.loads(published_bytes.decode("utf-8")) == next_document
        )),
        ("schema publication rejects stale base and discards only scratch", bool(
            stale_rejected
            and discarded.get("status") == "discarded"
            and len(discarded.get("removed", [])) == 2
            and stale_target_document == stale_document
        )),
        ("schema publisher atomically admits a new contract target",
         new_target_valid),
        ("prepare exposes a CAS-bound repair route for malformed publication",
         bool(
             repair_prepared.get("status") == "prepared_repair"
             and repair_prepared.get("repair_required") is True
             and repair_prepared.get("target_diagnostic")
             and repair_seed_preserved
             and repaired_target_valid
         )),
        ("post-replace validation failure restores the prior schema bytes",
         rollback_reported and rollback_restored),
        ("closed object accepts the exact shape", not schema_errors(valid, closed)),
        ("closed object rejects unknown fields",
         bool(schema_errors(dict(valid, extra=True), closed))),
        ("JSON bool cannot masquerade as integer",
         bool(schema_errors(dict(valid, count=True), closed))),
        ("JSON const and enum do not inherit Python bool/int equality",
         bool(schema_errors(1, {"const": True}))
         and bool(schema_errors(0, {"enum": [False]}))
         and not schema_errors(1.0, {"const": 1})),
        ("uniqueItems uses JSON numeric equality without bool coercion",
         bool(schema_errors([1, 1.0], {"type": "array", "uniqueItems": True}))
         and not schema_errors([True, 1], {
             "type": "array", "uniqueItems": True,
         })),
        ("date-time format validates calendar values",
         bool(schema_errors(dict(valid, when="2026-02-30T00:00:00Z"), closed))),
        ("oneOf rejects overlapping variants",
         bool(schema_errors({"left": 1, "right": 2}, union))),
        ("named schema resolver loads external review references",
         not any("unresolved external ref" in item for item in named_schema_errors(
             {"review_receipt": None}, "merge-draft.v1.schema.json"))),
        ("Draft 2020-12 ref siblings remain active",
         not schema_errors("abc", ref_with_sibling)
         and bool(schema_errors("abcd", ref_with_sibling))),
        ("non-string refs fail closed",
         bool(schema_errors("abc", {"$ref": 1}))),
    ]
    bad = [name for name, ok in checks if not ok]
    for name, ok in checks:
        print(("ok   " if ok else "FAIL ") + name)
    print("contract_schema selftest " + (
        "passed" if not bad else f"FAILED ({len(bad)})"))
    return 0 if not bad else 1


if __name__ == "__main__":
    raw_args = sys.argv[1:]
    if raw_args in (["--help"], ["-h"]):
        print(
            "usage: contract_schema.py --selftest | "
            "{prepare|publish|discard} <name.schema.json>\n\n"
            "AI workflow:\n"
            "  1. prepare writes/reuses tmp/contract_schema_candidates/<name> "
            "and prints the exact next argv. If the published bytes are "
            "already malformed, it returns status=prepared_repair, preserves "
            "those bytes as the CAS base, and exposes the typed diagnostic.\n"
            "  2. Edit only that candidate file.\n"
            "  3. publish validates all schemas, enforces the base CAS, and "
            "atomically replaces the published file.\n"
            "  4. discard removes only the ignored candidate pair."
        )
        raise SystemExit(0)
    if raw_args == ["--selftest"]:
        raise SystemExit(_selftest())
    if len(raw_args) == 2 and raw_args[0] in {
            "prepare", "publish", "discard"}:
        action, schema_name = raw_args
        try:
            result = (
                prepare_schema_candidate(schema_name)
                if action == "prepare"
                else publish_schema_candidate(schema_name)
                if action == "publish"
                else discard_schema_candidate(schema_name)
            )
        except Exception as exc:
            print(
                f"[contract-schema {action}] ERROR {exc}", file=sys.stderr)
            raise SystemExit(1)
        print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
        raise SystemExit(0)
    raise SystemExit(
        "usage: contract_schema.py --selftest | "
        "{prepare|publish|discard} <name.schema.json>")
