#!/usr/bin/env python3
"""Dependency-free structural validation for Xunji JSON contracts.

The repository intentionally does not require the third-party ``jsonschema``
package at runtime.  This module is therefore the single implementation of the
Draft 2020-12 subset used by ``contracts/*.schema.json``.  Producers,
consumers, and conformance selftests must call the same validator instead of
maintaining local field whitelists.
"""
from __future__ import annotations

import json
import math
import re
import sys
from datetime import datetime
from functools import lru_cache
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CONTRACTS = ROOT / "contracts"

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
    path = CONTRACTS / name
    try:
        value = json.loads(path.read_text(encoding="utf-8", errors="strict"))
    except Exception as exc:
        raise RuntimeError(f"contract schema is unavailable: {name}") from exc
    if not isinstance(value, dict):
        raise RuntimeError(f"contract schema is not an object: {name}")
    return value


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
    checks = [
        ("all published contract documents load", bool(schema_names)
         and all(isinstance(load_schema(name), dict) for name in schema_names)),
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
    if sys.argv[1:] != ["--selftest"]:
        raise SystemExit("usage: contract_schema.py --selftest")
    raise SystemExit(_selftest())
