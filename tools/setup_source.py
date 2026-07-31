#!/usr/bin/env python3
"""Deterministic ``xunji.setup-source.v1`` normalization and routing.

This module converts explicit URL and Guanlan/recon inputs into a provenance-rich
candidate manifest.  It never fetches a URL, executes source text, changes the
active pointer, creates Cron, or promotes source claims to operator authority.
Canonical run Markdown remains authoritative after setup; the JSON contract is a
frozen setup receipt and cross-language conformance surface.
"""
from __future__ import annotations

import hashlib
import ipaddress
import json
import mimetypes
import os
import re
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit, urlunsplit


ROOT = Path(__file__).resolve().parents[1]
RUNS_ROOT = ROOT / "runs"
SCHEMA = "xunji.setup-source.v1"
LEGACY_SCHEMAS = {"xunji.setup_source.v1"}
VALIDATION_SCHEMA = "xunji.setup-source-validation.v1"
CONTRACT_PATH = ROOT / "contracts" / "setup-source.v1.schema.json"
FIXTURE_PATH = ROOT / "tools" / "harness" / "fixtures" / "setup-source.json"
NORMALIZED_REL = Path("sources/normalized.json")
VALIDATOR_REL = Path("sources/validator_receipt.json")
NORMALIZER_REQUEST_REL = Path("sources/normalizer_request.json")
NORMALIZER_CANDIDATE_REL = Path("sources/normalizer_candidate.json")
ORIGINAL_PREFIX = Path("sources/original")
VALIDATOR_VERSION = "setup-source-validator/1"
DETERMINISTIC_VERSION = "setup-source-deterministic/1"
MAX_SOURCE_BYTES = 16 * 1024 * 1024
MAX_NORMALIZED_BYTES = 32 * 1024 * 1024
SUPPORTED_TYPES = {"auto", "run", "url", "recon-json", "file"}
SOURCE_KINDS = {
    "url", "recon-json", "json", "markdown", "html", "pdf", "docx", "text", "run",
}
RELATED_SOURCE_KINDS = {"recon-report", "attachment"}
CONFIDENCE = {"explicit", "derived", "ambiguous"}
AUTHORITIES = {"operator", "source-data", "derived"}
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_SNAPSHOT_RE = re.compile(r"^sources/original/[A-Za-z0-9._-]+$")
_BYTE_REF_RE = re.compile(r"^source:original#bytes=(\d+):(\d+)$")
_PROMPT_REF_RE = re.compile(r"^operator:prompt#sha256=([0-9a-f]{64})$")


class SetupSourceError(ValueError):
    """Structured source routing/validation failure."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


@dataclass(frozen=True)
class SourceRoute:
    kind: str
    value: str
    slug: str = ""
    run_dir: Path | None = None
    source_path: Path | None = None


def _sha256(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _canonical_bytes(value: dict) -> bytes:
    return (json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode(
        "utf-8"
    )


def _read_bounded(path: Path) -> bytes:
    if path.is_symlink():
        raise SetupSourceError(
            "source_symlink_forbidden", f"source must not be a symbolic link: {path}"
        )
    try:
        size = path.stat().st_size
    except OSError as exc:
        raise SetupSourceError("missing_source", f"source cannot be read: {path}: {exc}") from exc
    if not path.is_file():
        raise SetupSourceError("missing_source", f"source is not a regular file: {path}")
    if size > MAX_SOURCE_BYTES:
        raise SetupSourceError(
            "source_too_large", f"source exceeds {MAX_SOURCE_BYTES} byte deterministic limit"
        )
    try:
        raw = path.read_bytes()
    except OSError as exc:
        raise SetupSourceError("missing_source", f"source cannot be read: {path}: {exc}") from exc
    if len(raw) > MAX_SOURCE_BYTES:
        raise SetupSourceError(
            "source_too_large", f"source exceeds {MAX_SOURCE_BYTES} byte deterministic limit"
        )
    return raw


def read_source_bytes(path: Path) -> bytes:
    """Public bounded/no-symlink reader shared by every setup adapter."""
    return _read_bounded(path.expanduser())


def _idna_host(host: str) -> str:
    value = str(host or "").strip().rstrip(".").lower()
    if not value:
        raise SetupSourceError("invalid_host", "host is empty")
    try:
        return ipaddress.ip_address(value).compressed
    except ValueError:
        pass
    try:
        encoded = value.encode("idna").decode("ascii").lower()
    except UnicodeError as exc:
        raise SetupSourceError("invalid_host", f"host cannot be IDNA-normalized: {host}") from exc
    if len(encoded) > 253 or any(
        not label or len(label) > 63 or not re.fullmatch(r"[a-z0-9](?:[a-z0-9-]*[a-z0-9])?", label)
        for label in encoded.split(".")
    ):
        raise SetupSourceError("invalid_host", f"host is invalid: {host}")
    return encoded


def parse_target_url(value: str) -> dict:
    raw = str(value or "").strip()
    if not raw or len(raw.encode("utf-8")) > 8192 \
            or re.search(r"[\x00-\x20\x7f]", raw):
        raise SetupSourceError("invalid_url", "URL is empty or contains control/whitespace")
    # A trusted operator commonly writes ``https://host继续执行`` without a
    # separating space.  Python's IDNA codec can otherwise turn the attached
    # Chinese instruction into a different, syntactically valid hostname.  A
    # real Unicode hostname can be supplied in Unicode from its first label or
    # as explicit punycode; an ASCII hostname followed immediately by CJK is an
    # ambiguous human-language boundary and must never become a new target.
    if re.match(
        r"(?i)^https?://(?:localhost|[a-z0-9.-]+|\[[0-9a-f:.]+\])"
        r"(?::\d{1,5})?[\u3400-\u4dbf\u4e00-\u9fff]",
        raw,
    ):
        raise SetupSourceError(
            "ambiguous_url_suffix",
            "ASCII URL host is immediately followed by operator-language text",
        )
    try:
        parsed = urlsplit(raw)
        port = parsed.port
    except ValueError as exc:
        raise SetupSourceError("invalid_url", f"URL cannot be parsed: {exc}") from exc
    if parsed.scheme.lower() not in {"http", "https"} or not parsed.hostname:
        raise SetupSourceError("invalid_url", "URL must be absolute http/https with a host")
    if parsed.username is not None or parsed.password is not None:
        raise SetupSourceError("url_userinfo_forbidden", "URL userinfo credentials are forbidden")
    host = _idna_host(parsed.hostname)
    return {
        "primary_url": raw,
        "host": host,
        "scheme": parsed.scheme.lower(),
        "port": port or (443 if parsed.scheme.lower() == "https" else 80),
    }


def canonical_target_url(value: str) -> str:
    """Normalize effect-preserving URL syntax while preserving path/query bytes."""
    raw = str(value or "").strip()
    target = parse_target_url(raw)
    parsed = urlsplit(raw)
    scheme = str(target["scheme"])
    host = str(target["host"])
    host_text = f"[{host}]" if ":" in host else host
    explicit_port = parsed.port
    default_port = 443 if scheme == "https" else 80
    netloc = host_text + (
        f":{explicit_port}" if explicit_port and explicit_port != default_port else ""
    )
    return urlunsplit((
        scheme,
        netloc,
        parsed.path or "/",
        parsed.query,
        parsed.fragment,
    ))


def _bare_target_url(value: str) -> str:
    """Return a canonical HTTPS URL for an unambiguous bare host[:port]."""
    raw = str(value or "").strip()
    if not raw or any(char in raw for char in "/?#@") \
            or re.search(r"[\x00-\x20\x7f]", raw):
        return ""
    if re.match(
        r"(?i)^(?:localhost|[a-z0-9.-]+|\[[0-9a-f:.]+\])"
        r"(?::\d{1,5})?[\u3400-\u4dbf\u4e00-\u9fff]",
        raw,
    ):
        return ""
    try:
        parsed = urlsplit("//" + raw)
        host = _idna_host(parsed.hostname or "")
        port = parsed.port
    except (SetupSourceError, ValueError):
        return ""
    try:
        ipaddress.ip_address(host)
        recognizable = True
    except ValueError:
        recognizable = host == "localhost" or "." in host
    if not recognizable or parsed.path or parsed.query or parsed.fragment \
            or parsed.username is not None or parsed.password is not None:
        return ""
    host_text = f"[{host}]" if ":" in host else host
    return canonical_target_url(
        "https://" + host_text + (f":{port}" if port else "") + "/"
    )


def normalize_operator_source(value: str) -> str:
    """Compile one operator URL/bare-host spelling into its semantic identity.

    Non-target values are returned unchanged so explicit run and file routing
    stays owned by the existing deterministic router.
    """
    raw = str(value or "").strip()
    if re.match(r"(?i)^https?://", raw):
        return canonical_target_url(raw)
    return _bare_target_url(raw) or raw


def _slug(value: str) -> str:
    raw = str(value or "").strip().lower()
    candidate = re.sub(r"[^a-z0-9_-]+", "-", raw).strip("-_")
    candidate = re.sub(r"-{2,}", "-", candidate)[:48]
    if not candidate:
        raise SetupSourceError("invalid_slug", "source cannot derive a non-empty run slug")
    return candidate


def _json_pointer_token(value: str) -> str:
    return value.replace("~", "~0").replace("/", "~1")


def _json_pointer_get(value: object, pointer: str) -> object:
    if pointer == "":
        return value
    if not pointer.startswith("/"):
        raise SetupSourceError("invalid_source_ref", f"JSON pointer is invalid: {pointer}")
    current: object = value
    for raw in pointer[1:].split("/"):
        token = raw.replace("~1", "/").replace("~0", "~")
        if isinstance(current, list):
            if not token.isdigit() or int(token) >= len(current):
                raise SetupSourceError("invalid_source_ref", f"JSON pointer is out of range: {pointer}")
            current = current[int(token)]
        elif isinstance(current, dict) and token in current:
            current = current[token]
        else:
            raise SetupSourceError("invalid_source_ref", f"JSON pointer does not exist: {pointer}")
    return current


def _asset_from_value(value: object) -> tuple[str, str]:
    if isinstance(value, bytes):
        try:
            raw = value.decode("utf-8", "strict").strip()
        except UnicodeError as exc:
            raise SetupSourceError("invalid_asset", "asset source bytes are not UTF-8") from exc
    else:
        raw = str(value or "").strip()
    if not raw:
        raise SetupSourceError("invalid_asset", "asset value is empty")
    if raw.lower().startswith(("http://", "https://")):
        parsed = parse_target_url(raw)
        return str(parsed["host"]), raw
    return _idna_host(raw), ""


def parse_asset_value(value: object) -> tuple[str, str]:
    """Public canonical host/URL parser for setup-source adapters."""
    return _asset_from_value(value)


def valid_recon_data(value: object) -> bool:
    if not isinstance(value, dict) or not isinstance(value.get("assets"), list) \
            or not value.get("assets") or len(value["assets"]) > 100000:
        return False
    for item in value["assets"]:
        if not isinstance(item, dict) or not any(
            str(item.get(key) or "").strip() for key in ("host", "asset", "name", "url")
        ):
            return False
    return True


def _base_manifest(*, source: dict, provided_target: bool) -> dict:
    digest = str(source["sha256"])
    return {
        "schema": SCHEMA,
        "source_sha256": digest,
        "source": source,
        "related_sources": [],
        "operator_directive": {
            "prompt_sha256": "",
            "provided_target": bool(provided_target),
        },
        "target": {
            "primary_url": "",
            "host": "",
            "scheme": "",
            "port": None,
            "source_ref": "",
            "confidence": "ambiguous",
        },
        "assets": [],
        "scope_candidates": [],
        "authorization_claims": [],
        "entry_points": [],
        "signals": [],
        "coverage_quality": "unknown",
        "unresolved": [],
        "extractor": {
            "deterministic_version": DETERMINISTIC_VERSION,
            "ai_backend": None,
            "prompt_version": None,
            "redaction_version": None,
            "redacted_sha256": None,
            "request_schema": None,
            "request_sha256": None,
            "candidate_schema": None,
            "candidate_sha256": None,
        },
    }


def make_base_manifest(*, source: dict, provided_target: bool) -> dict:
    """Return the canonical empty v1 manifest shape for a source adapter."""
    return _base_manifest(source=source, provided_target=provided_target)


def normalize_url(value: str) -> tuple[dict, bytes]:
    parsed = parse_target_url(value)
    raw = str(value).encode("utf-8")
    digest = _sha256(raw)
    source_ref = f"source:original#bytes=0:{len(raw)}"
    manifest = _base_manifest(
        source={
            "kind": "url",
            "reference": str(value),
            "sha256": digest,
            "media_type": "text/uri-list; charset=utf-8",
            "snapshot": "sources/original/target-url.txt",
        },
        provided_target=True,
    )
    manifest["target"] = {
        **parsed,
        "source_ref": source_ref,
        "confidence": "explicit",
    }
    manifest["assets"] = [{
        "host": parsed["host"],
        "url": parsed["primary_url"],
        "source_ref": source_ref,
    }]
    manifest["entry_points"] = [{"value": parsed["primary_url"], "source_ref": source_ref}]
    manifest["coverage_quality"] = "partial"
    validate_manifest(manifest, snapshot_bytes=raw)
    return manifest, raw


def normalize_recon(path: Path, raw: bytes, data: dict) -> dict:
    if not valid_recon_data(data):
        raise SetupSourceError(
            "unknown_recon_schema",
            "recon must be an object with a non-empty host-bearing assets list",
        )
    digest = _sha256(raw)
    manifest = _base_manifest(
        source={
            "kind": "recon-json",
            "reference": str(path),
            "sha256": digest,
            "media_type": "application/json",
            "snapshot": "sources/original/recon.json",
        },
        provided_target=False,
    )
    assets: list[dict] = []
    for index, item in enumerate(data["assets"]):
        key = next(
            key for key in ("host", "asset", "name", "url")
            if str(item.get(key) or "").strip()
        )
        raw_value = item[key]
        host, url = _asset_from_value(raw_value)
        ref = f"source:json#/assets/{index}/{_json_pointer_token(key)}"
        assets.append({"host": host, "url": url, "source_ref": ref})
    manifest["assets"] = assets
    first = assets[0]
    if first["url"]:
        parsed = parse_target_url(first["url"])
        manifest["target"] = {**parsed, "source_ref": first["source_ref"], "confidence": "derived"}
    else:
        manifest["target"] = {
            "primary_url": "",
            "host": first["host"],
            "scheme": "",
            "port": None,
            "source_ref": first["source_ref"],
            "confidence": "derived",
        }
    manifest["coverage_quality"] = "full"
    for key in ("authorization", "authorization_notes"):
        if key in data and str(data.get(key) or "").strip():
            claim_value = data[key]
            if isinstance(claim_value, (dict, list)):
                claim_value = json.dumps(
                    claim_value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
                )
            manifest["authorization_claims"].append({
                "value": str(claim_value),
                "authority": "source-data",
                "source_ref": f"source:json#/{_json_pointer_token(key)}",
            })
    if "scope" in data and str(data.get("scope") or "").strip():
        scope_value = data["scope"]
        if isinstance(scope_value, list):
            for index, item in enumerate(scope_value):
                value = (
                    json.dumps(item, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
                    if isinstance(item, (dict, list)) else str(item)
                )
                if value:
                    manifest["scope_candidates"].append({
                        "value": value,
                        "source_ref": f"source:json#/scope/{index}",
                    })
        else:
            value = (
                json.dumps(scope_value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
                if isinstance(scope_value, dict) else str(scope_value)
            )
            manifest["scope_candidates"].append({
                "value": value,
                "source_ref": "source:json#/scope",
            })
    validate_manifest(manifest, snapshot_bytes=raw, snapshot_json=data)
    return manifest


def normalize_recon_path(path: Path) -> tuple[dict, bytes, dict]:
    expanded = path.expanduser()
    raw = read_source_bytes(expanded)
    resolved = expanded.resolve(strict=False)
    try:
        data = json.loads(raw.decode("utf-8", "strict"))
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise SetupSourceError("invalid_recon_json", f"recon JSON is invalid: {exc}") from exc
    if not isinstance(data, dict):
        raise SetupSourceError("unknown_recon_schema", "recon JSON root must be an object")
    return normalize_recon(resolved, raw, data), raw, data


def add_related_source(
    manifest: dict,
    *,
    kind: str,
    reference: str,
    snapshot: str,
    media_type: str,
    raw: bytes,
) -> dict:
    """Attach a frozen secondary input that materially affects setup output."""
    if manifest.get("schema") != SCHEMA:
        raise SetupSourceError("unsupported_source_schema", "related source needs canonical v1")
    descriptor = {
        "kind": kind,
        "reference": str(reference),
        "sha256": _sha256(raw),
        "media_type": str(media_type),
        "snapshot": str(snapshot),
    }
    related = manifest.get("related_sources")
    if not isinstance(related, list):
        raise SetupSourceError("invalid_source_manifest", "related_sources must be a list")
    if any(item.get("snapshot") == snapshot for item in related if isinstance(item, dict)):
        raise SetupSourceError("duplicate_related_source", f"duplicate related snapshot: {snapshot}")
    related.append(descriptor)
    return descriptor


def migrate_manifest(
    manifest: dict,
    *,
    snapshot_bytes: bytes | None = None,
    source_path: Path | None = None,
    related_snapshots: dict[str, bytes] | None = None,
) -> dict:
    """Migrate a known legacy setup identity when original bytes are available.

    Legacy manifests did not preserve enough provenance to reconstruct a v1
    bundle by themselves.  Migration therefore fails closed unless the caller
    supplies the exact bytes whose hash matches the legacy identity.
    """
    if not isinstance(manifest, dict):
        raise SetupSourceError("invalid_source_manifest", "source manifest must be an object")
    schema = str(manifest.get("schema") or "")
    if schema == SCHEMA:
        return validate_manifest(manifest, snapshot_bytes=snapshot_bytes)
    if schema not in LEGACY_SCHEMAS:
        raise SetupSourceError("unsupported_source_schema", f"unsupported setup source schema: {schema}")
    if snapshot_bytes is None:
        raise SetupSourceError(
            "migration_requires_snapshot",
            "legacy setup source cannot be migrated without its exact original bytes",
        )
    expected_hash = str(manifest.get("source_sha256") or "")
    if not _SHA256_RE.fullmatch(expected_hash) or _sha256(snapshot_bytes) != expected_hash:
        raise SetupSourceError("source_hash_mismatch", "legacy snapshot does not match source hash")
    kind = str(manifest.get("kind") or "")
    if kind == "target_url":
        try:
            target = snapshot_bytes.decode("utf-8", "strict")
        except UnicodeError as exc:
            raise SetupSourceError("migration_invalid_snapshot", "legacy URL is not UTF-8") from exc
        migrated, _ = normalize_url(target)
        return migrated
    if kind == "recon_json":
        try:
            data = json.loads(snapshot_bytes.decode("utf-8", "strict"))
        except (UnicodeError, json.JSONDecodeError) as exc:
            raise SetupSourceError("migration_invalid_snapshot", "legacy recon JSON is invalid") from exc
        if not isinstance(data, dict):
            raise SetupSourceError("unknown_recon_schema", "legacy recon root must be an object")
        path = source_path or Path(str(
            manifest.get("reference") or manifest.get("path") or "legacy-recon.json"
        ))
        migrated = normalize_recon(path, snapshot_bytes, data)
        report_hash = str(manifest.get("adjacent_report_sha256") or "")
        if report_hash:
            related_rel = "sources/original/recon-report.md"
            report_bytes = (related_snapshots or {}).get(related_rel)
            if report_bytes is None:
                raise SetupSourceError(
                    "migration_requires_related_snapshot",
                    "legacy recon report hash requires the exact adjacent report bytes",
                )
            if not _SHA256_RE.fullmatch(report_hash) or _sha256(report_bytes) != report_hash:
                raise SetupSourceError(
                    "related_source_hash_mismatch", "legacy recon report hash does not match"
                )
            add_related_source(
                migrated,
                kind="recon-report",
                reference=str(path.parent / "report.md"),
                snapshot=related_rel,
                media_type="text/markdown; charset=utf-8",
                raw=report_bytes,
            )
        return migrated
    raise SetupSourceError(
        "unsupported_legacy_source", f"legacy setup source kind is unsupported: {kind or 'missing'}"
    )


def _require_keys(value: dict, expected: set[str], *, where: str) -> None:
    extra = sorted(set(value) - expected)
    missing = sorted(expected - set(value))
    if extra or missing:
        detail = []
        if missing:
            detail.append("missing=" + ",".join(missing))
        if extra:
            detail.append("unknown=" + ",".join(extra))
        raise SetupSourceError("invalid_source_manifest", f"{where} fields invalid: {'; '.join(detail)}")


def _bounded_text(
    value: object,
    *,
    where: str,
    maximum: int,
    allow_empty: bool = False,
) -> str:
    if not isinstance(value, str):
        raise SetupSourceError("invalid_source_manifest", f"{where} must be a string")
    text = value
    if (not allow_empty and not text) or len(text) > maximum:
        raise SetupSourceError(
            "invalid_source_manifest", f"{where} must be 1..{maximum} characters"
        )
    return text


def _bounded_list(value: object, *, where: str, maximum: int) -> list:
    if not isinstance(value, list) or len(value) > maximum:
        raise SetupSourceError(
            "invalid_source_manifest", f"{where} must be a list with at most {maximum} items"
        )
    return value


def _validate_ref(
    source_ref: str,
    *,
    snapshot_bytes: bytes | None,
    snapshot_json: object | None,
    allow_empty: bool = False,
) -> object | None:
    ref = str(source_ref or "")
    if not ref and allow_empty:
        return None
    match = _BYTE_REF_RE.fullmatch(ref)
    if match:
        start, end = int(match.group(1)), int(match.group(2))
        if start > end or (snapshot_bytes is not None and end > len(snapshot_bytes)):
            raise SetupSourceError("invalid_source_ref", f"byte source_ref is out of range: {ref}")
        return snapshot_bytes[start:end] if snapshot_bytes is not None else None
    if ref.startswith("source:json#"):
        if snapshot_json is None:
            if snapshot_bytes is None:
                pointer = ref[len("source:json#"):]
                if pointer and not pointer.startswith("/"):
                    raise SetupSourceError("invalid_source_ref", f"JSON pointer is invalid: {pointer}")
                return None
            try:
                snapshot_json = json.loads(snapshot_bytes.decode("utf-8", "strict"))
            except (UnicodeError, json.JSONDecodeError) as exc:
                raise SetupSourceError("invalid_source_ref", "JSON source_ref snapshot is invalid") from exc
        return _json_pointer_get(snapshot_json, ref[len("source:json#"):])
    prompt = _PROMPT_REF_RE.fullmatch(ref)
    if prompt:
        return prompt.group(1)
    raise SetupSourceError("invalid_source_ref", f"unsupported source_ref: {ref}")


def _referenced_text(value: object) -> str:
    """Return the stable text represented by a provenance reference."""
    if isinstance(value, bytes):
        try:
            return value.decode("utf-8", "strict").strip()
        except UnicodeError as exc:
            raise SetupSourceError(
                "source_ref_mismatch", "referenced source bytes are not UTF-8 text"
            ) from exc
    if isinstance(value, (dict, list)):
        return json.dumps(
            value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
        )
    if value is None:
        return "null"
    if value is True:
        return "true"
    if value is False:
        return "false"
    return str(value).strip()


def _require_ref_contains(value: object, referenced: object | None, *, where: str) -> None:
    """Reject provenance that points somewhere unrelated to the claimed value."""
    if referenced is None:
        return
    claimed = str(value or "").strip()
    source_text = _referenced_text(referenced)
    if not claimed or claimed not in source_text:
        raise SetupSourceError(
            "source_ref_mismatch", f"{where} source_ref does not contain its value"
        )


def validate_manifest(
    manifest: dict,
    *,
    snapshot_bytes: bytes | None = None,
    snapshot_json: object | None = None,
    allow_legacy: bool = False,
) -> dict:
    if not isinstance(manifest, dict):
        raise SetupSourceError("invalid_source_manifest", "source manifest must be an object")
    schema = str(manifest.get("schema") or "")
    if schema in LEGACY_SCHEMAS and allow_legacy:
        if not _SHA256_RE.fullmatch(str(manifest.get("source_sha256") or "")):
            raise SetupSourceError("invalid_source_manifest", "legacy source hash is invalid")
        return manifest
    if schema != SCHEMA:
        raise SetupSourceError("unsupported_source_schema", f"unsupported setup source schema: {schema}")
    top_keys = {
        "schema", "source_sha256", "source", "related_sources", "operator_directive", "target", "assets",
        "scope_candidates", "authorization_claims", "entry_points", "signals",
        "coverage_quality", "unresolved", "extractor",
    }
    _require_keys(manifest, top_keys, where="manifest")
    digest = _bounded_text(
        manifest["source_sha256"], where="source_sha256", maximum=64
    )
    if not _SHA256_RE.fullmatch(digest):
        raise SetupSourceError("invalid_source_hash", "source hash must be sha256")
    source = manifest["source"]
    if not isinstance(source, dict):
        raise SetupSourceError("invalid_source_manifest", "source must be an object")
    _require_keys(source, {"kind", "reference", "sha256", "media_type", "snapshot"}, where="source")
    if not isinstance(source["kind"], str) or source["kind"] not in SOURCE_KINDS:
        raise SetupSourceError("invalid_source_manifest", "source kind/reference is invalid")
    _bounded_text(source["reference"], where="source.reference", maximum=4096)
    _bounded_text(source["sha256"], where="source.sha256", maximum=64)
    _bounded_text(source["media_type"], where="source.media_type", maximum=255)
    if source["sha256"] != digest:
        raise SetupSourceError("invalid_source_manifest", "source digest/media type is inconsistent")
    source_snapshot = _bounded_text(
        source["snapshot"], where="source.snapshot", maximum=255
    )
    if not _SNAPSHOT_RE.fullmatch(source_snapshot):
        raise SetupSourceError("snapshot_path_invalid", "snapshot must stay under sources/original")
    if snapshot_bytes is not None and _sha256(snapshot_bytes) != digest:
        raise SetupSourceError("source_hash_mismatch", "snapshot bytes do not match source hash")
    if snapshot_bytes is not None and len(snapshot_bytes) > MAX_SOURCE_BYTES:
        raise SetupSourceError("source_too_large", "snapshot exceeds deterministic source limit")

    related_sources = _bounded_list(
        manifest["related_sources"], where="related_sources", maximum=32
    )
    related_seen: set[str] = {str(source["snapshot"])}
    for index, related in enumerate(related_sources):
        if not isinstance(related, dict):
            raise SetupSourceError("invalid_source_manifest", f"related_sources[{index}] is invalid")
        _require_keys(
            related, {"kind", "reference", "sha256", "media_type", "snapshot"},
            where=f"related_sources[{index}]",
        )
        if not isinstance(related["kind"], str) \
                or related["kind"] not in RELATED_SOURCE_KINDS:
            raise SetupSourceError("invalid_source_manifest", f"related_sources[{index}] identity is invalid")
        _bounded_text(
            related["reference"], where=f"related_sources[{index}].reference", maximum=4096
        )
        _bounded_text(
            related["media_type"], where=f"related_sources[{index}].media_type", maximum=255
        )
        related_hash = _bounded_text(
            related["sha256"], where=f"related_sources[{index}].sha256", maximum=64
        )
        if not _SHA256_RE.fullmatch(related_hash):
            raise SetupSourceError("invalid_source_manifest", f"related_sources[{index}] hash/media is invalid")
        related_snapshot = _bounded_text(
            related["snapshot"], where=f"related_sources[{index}].snapshot", maximum=255
        )
        if not _SNAPSHOT_RE.fullmatch(related_snapshot):
            raise SetupSourceError("snapshot_path_invalid", f"related_sources[{index}] snapshot is invalid")
        if related_snapshot in related_seen:
            raise SetupSourceError("duplicate_related_source", f"duplicate related snapshot: {related_snapshot}")
        related_seen.add(related_snapshot)

    operator = manifest["operator_directive"]
    if not isinstance(operator, dict):
        raise SetupSourceError("invalid_source_manifest", "operator_directive must be an object")
    _require_keys(operator, {"prompt_sha256", "provided_target"}, where="operator_directive")
    prompt_hash = _bounded_text(
        operator["prompt_sha256"], where="operator_directive.prompt_sha256",
        maximum=64, allow_empty=True,
    )
    if prompt_hash and not _SHA256_RE.fullmatch(prompt_hash):
        raise SetupSourceError("invalid_operator_binding", "operator prompt hash is invalid")
    if not isinstance(operator["provided_target"], bool):
        raise SetupSourceError("invalid_operator_binding", "provided_target must be boolean")

    target = manifest["target"]
    if not isinstance(target, dict):
        raise SetupSourceError("invalid_source_manifest", "target must be an object")
    _require_keys(
        target,
        {"primary_url", "host", "scheme", "port", "source_ref", "confidence"},
        where="target",
    )
    if not isinstance(target["confidence"], str) \
            or target["confidence"] not in CONFIDENCE:
        raise SetupSourceError("invalid_target", "target confidence is invalid")
    _bounded_text(
        target["primary_url"], where="target.primary_url", maximum=8192,
        allow_empty=True,
    )
    _bounded_text(target["host"], where="target.host", maximum=253, allow_empty=True)
    _bounded_text(target["scheme"], where="target.scheme", maximum=5, allow_empty=True)
    if target["port"] is not None and (
        isinstance(target["port"], bool) or not isinstance(target["port"], int)
        or not 1 <= target["port"] <= 65535
    ):
        raise SetupSourceError("invalid_target", "target port is invalid")
    _bounded_text(
        target["source_ref"], where="target.source_ref", maximum=4096,
        allow_empty=True,
    )
    if target["primary_url"]:
        _bounded_text(target["primary_url"], where="target.primary_url", maximum=8192)
        parsed = parse_target_url(str(target["primary_url"]))
        if parsed["host"] != target["host"] or parsed["scheme"] != target["scheme"] \
                or parsed["port"] != target["port"]:
            raise SetupSourceError("invalid_target", "target URL fields are inconsistent")
    elif target["host"]:
        if _idna_host(str(target["host"])) != target["host"] or target["scheme"] != "" \
                or target["port"] is not None:
            raise SetupSourceError("invalid_target", "host-only target fields are inconsistent")
    elif target["source_ref"] or target["confidence"] != "ambiguous" \
            or target["scheme"] != "" or target["port"] is not None:
        raise SetupSourceError("invalid_target", "empty target must remain ambiguous and unreferenced")
    if target["source_ref"]:
        referenced_target = _validate_ref(
            str(target["source_ref"]), snapshot_bytes=snapshot_bytes,
            snapshot_json=snapshot_json,
        )
        if referenced_target is not None:
            target_value = target["primary_url"] or target["host"]
            _require_ref_contains(target_value, referenced_target, where="target")

    assets = manifest["assets"]
    try:
        assets = _bounded_list(assets, where="assets", maximum=100000)
    except SetupSourceError as exc:
        raise SetupSourceError("invalid_asset", str(exc)) from exc
    seen: set[str] = set()
    for index, asset in enumerate(assets):
        if not isinstance(asset, dict):
            raise SetupSourceError("invalid_asset", f"asset {index} must be an object")
        _require_keys(asset, {"host", "url", "source_ref"}, where=f"asset[{index}]")
        _bounded_text(asset["host"], where=f"asset[{index}].host", maximum=253)
        _bounded_text(
            asset["url"], where=f"asset[{index}].url", maximum=8192, allow_empty=True
        )
        _bounded_text(asset["source_ref"], where=f"asset[{index}].source_ref", maximum=4096)
        host = _idna_host(str(asset["host"]))
        if host != asset["host"]:
            raise SetupSourceError("invalid_asset", f"asset {index} host is not normalized")
        if host in seen:
            raise SetupSourceError("duplicate_asset", f"duplicate asset host: {host}")
        seen.add(host)
        if asset["url"] and parse_target_url(str(asset["url"]))["host"] != host:
            raise SetupSourceError("invalid_asset", f"asset {index} URL host mismatch")
        referenced = _validate_ref(
            str(asset["source_ref"]), snapshot_bytes=snapshot_bytes,
            snapshot_json=snapshot_json,
        )
        if referenced is not None:
            ref_host, _ = _asset_from_value(referenced)
            if ref_host != host:
                raise SetupSourceError("source_ref_mismatch", f"asset {index} source_ref mismatch")

    def candidate_list(name: str) -> list:
        maximum = 10000 if name in {"authorization_claims", "unresolved"} else 100000
        return _bounded_list(manifest[name], where=name, maximum=maximum)

    for name in ("scope_candidates", "entry_points", "signals"):
        for index, item in enumerate(candidate_list(name)):
            if not isinstance(item, dict):
                raise SetupSourceError("invalid_source_manifest", f"{name}[{index}] is invalid")
            _require_keys(item, {"value", "source_ref"}, where=f"{name}[{index}]")
            _bounded_text(item["value"], where=f"{name}[{index}].value", maximum=8192)
            _bounded_text(
                item["source_ref"], where=f"{name}[{index}].source_ref", maximum=4096
            )
            referenced = _validate_ref(
                str(item["source_ref"]), snapshot_bytes=snapshot_bytes,
                snapshot_json=snapshot_json,
            )
            _require_ref_contains(item["value"], referenced, where=f"{name}[{index}]")

    for index, claim in enumerate(candidate_list("authorization_claims")):
        if not isinstance(claim, dict):
            raise SetupSourceError("invalid_authority_claim", f"claim {index} is invalid")
        _require_keys(claim, {"value", "authority", "source_ref"}, where=f"claim[{index}]")
        _bounded_text(claim["value"], where=f"claim[{index}].value", maximum=8192)
        _bounded_text(claim["source_ref"], where=f"claim[{index}].source_ref", maximum=4096)
        if not isinstance(claim["authority"], str) \
                or claim["authority"] not in AUTHORITIES:
            raise SetupSourceError("invalid_authority_claim", f"claim {index} is invalid")
        referenced = _validate_ref(
            str(claim["source_ref"]), snapshot_bytes=snapshot_bytes,
            snapshot_json=snapshot_json,
        )
        if claim["authority"] == "operator":
            if not prompt_hash or referenced != prompt_hash:
                raise SetupSourceError(
                    "operator_authority_unbound",
                    "only a hook-bound operator prompt may mint operator authority",
                )
        elif _PROMPT_REF_RE.fullmatch(str(claim["source_ref"])):
            raise SetupSourceError("invalid_authority_claim", "non-operator claim uses prompt authority")
        else:
            _require_ref_contains(claim["value"], referenced, where=f"claim[{index}]")

    if not isinstance(manifest["coverage_quality"], str) \
            or manifest["coverage_quality"] not in {"full", "partial", "unknown"}:
        raise SetupSourceError("invalid_source_manifest", "coverage_quality is invalid")
    for index, item in enumerate(candidate_list("unresolved")):
        if not isinstance(item, dict):
            raise SetupSourceError("invalid_source_manifest", f"unresolved[{index}] is invalid")
        _require_keys(item, {"field", "reason", "source_ref"}, where=f"unresolved[{index}]")
        _bounded_text(item["field"], where=f"unresolved[{index}].field", maximum=255)
        _bounded_text(item["reason"], where=f"unresolved[{index}].reason", maximum=4096)
        _bounded_text(
            item["source_ref"], where=f"unresolved[{index}].source_ref",
            maximum=4096, allow_empty=True,
        )
        if item["source_ref"]:
            _validate_ref(
                str(item["source_ref"]), snapshot_bytes=snapshot_bytes,
                snapshot_json=snapshot_json,
            )

    extractor = manifest["extractor"]
    if not isinstance(extractor, dict):
        raise SetupSourceError("invalid_source_manifest", "extractor must be an object")
    _require_keys(
        extractor,
        {
            "deterministic_version", "ai_backend", "prompt_version",
            "redaction_version", "redacted_sha256", "request_schema",
            "request_sha256", "candidate_schema", "candidate_sha256",
        },
        where="extractor",
    )
    if not str(extractor["deterministic_version"] or ""):
        raise SetupSourceError("invalid_source_manifest", "deterministic extractor version is required")
    _bounded_text(
        extractor["deterministic_version"], where="extractor.deterministic_version", maximum=128
    )
    for key in (
        "ai_backend", "prompt_version", "redaction_version", "request_schema",
        "candidate_schema",
    ):
        if extractor[key] is not None:
            _bounded_text(extractor[key], where=f"extractor.{key}", maximum=255)
    for key in ("redacted_sha256", "request_sha256", "candidate_sha256"):
        if extractor[key] is not None:
            digest_value = _bounded_text(
                extractor[key], where=f"extractor.{key}", maximum=64
            )
            if not _SHA256_RE.fullmatch(digest_value):
                raise SetupSourceError("invalid_source_manifest", f"extractor {key} is invalid")
    ai_fields = (
        "ai_backend", "prompt_version", "redaction_version", "redacted_sha256",
        "request_schema", "request_sha256", "candidate_schema", "candidate_sha256",
    )
    populated_ai = [key for key in ai_fields if extractor[key] is not None]
    if populated_ai and len(populated_ai) != len(ai_fields):
        raise SetupSourceError("invalid_source_manifest", "AI extractor metadata must be all-or-none")
    if not populated_ai and extractor["ai_backend"] is not None:
        raise SetupSourceError("invalid_source_manifest", "AI backend metadata is incomplete")
    return manifest


def write_bundle(
    run_dir: Path,
    manifest: dict,
    snapshot_bytes: bytes,
    related_snapshots: dict[str, bytes] | None = None,
    normalizer_artifacts: dict[str, bytes] | None = None,
) -> dict:
    validate_manifest(manifest, snapshot_bytes=snapshot_bytes)
    snapshot_rel = Path(str(manifest["source"]["snapshot"]))
    snapshot = run_dir / snapshot_rel
    try:
        snapshot.resolve(strict=False).relative_to((run_dir / ORIGINAL_PREFIX).resolve(strict=False))
    except ValueError as exc:
        raise SetupSourceError("snapshot_path_invalid", "snapshot escapes sources/original") from exc
    snapshot.parent.mkdir(parents=True, exist_ok=True)
    snapshot.write_bytes(snapshot_bytes)
    normalized = run_dir / NORMALIZED_REL
    normalized.parent.mkdir(parents=True, exist_ok=True)
    normalized_bytes = _canonical_bytes(manifest)
    if len(normalized_bytes) > MAX_NORMALIZED_BYTES:
        raise SetupSourceError(
            "normalized_source_too_large", "normalized candidate exceeds deterministic limit"
        )
    normalized.write_bytes(normalized_bytes)
    extractor = manifest["extractor"]
    normalizer_receipt: dict[str, object] = {}
    normalizer_specs = (
        (NORMALIZER_REQUEST_REL, "request_schema", "request_sha256"),
        (NORMALIZER_CANDIDATE_REL, "candidate_schema", "candidate_sha256"),
    )
    if extractor["ai_backend"] is not None:
        supplied = dict(normalizer_artifacts or {})
        for rel, schema_key, hash_key in normalizer_specs:
            raw = supplied.get(rel.as_posix())
            path = run_dir / rel
            if raw is None and path.is_file():
                raw = path.read_bytes()
            if raw is None or _sha256(raw) != extractor[hash_key]:
                raise SetupSourceError(
                    "normalizer_artifact_mismatch",
                    f"normalizer artifact is missing or mismatched: {rel.as_posix()}",
                )
            try:
                value = json.loads(raw.decode("utf-8", "strict"))
            except (UnicodeError, json.JSONDecodeError) as exc:
                raise SetupSourceError(
                    "normalizer_artifact_invalid", f"normalizer artifact is invalid: {rel.as_posix()}"
                ) from exc
            if not isinstance(value, dict) or value.get("schema") != extractor[schema_key]:
                raise SetupSourceError(
                    "normalizer_artifact_mismatch", f"normalizer artifact schema mismatch: {rel.as_posix()}"
                )
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(raw)
            normalizer_receipt[rel.as_posix()] = {
                "schema": extractor[schema_key], "sha256": extractor[hash_key],
            }
    elif normalizer_artifacts:
        raise SetupSourceError(
            "unexpected_normalizer_artifact", "deterministic setup must not carry AI artifacts"
        )
    provided_related = dict(related_snapshots or {})
    related_receipts: list[dict] = []
    for descriptor in manifest["related_sources"]:
        related_rel = str(descriptor["snapshot"])
        related_path = run_dir / related_rel
        raw = provided_related.get(related_rel)
        if raw is None:
            try:
                raw = related_path.read_bytes()
            except OSError as exc:
                raise SetupSourceError(
                    "missing_related_source", f"related snapshot is unavailable: {related_rel}"
                ) from exc
        if _sha256(raw) != descriptor["sha256"]:
            raise SetupSourceError(
                "related_source_hash_mismatch", f"related snapshot hash mismatch: {related_rel}"
            )
        if len(raw) > MAX_SOURCE_BYTES:
            raise SetupSourceError(
                "source_too_large", f"related snapshot exceeds deterministic limit: {related_rel}"
            )
        related_path.parent.mkdir(parents=True, exist_ok=True)
        related_path.write_bytes(raw)
        related_receipts.append({"snapshot": related_rel, "sha256": descriptor["sha256"]})
    receipt = {
        "schema": VALIDATION_SCHEMA,
        "source_schema": SCHEMA,
        "source_sha256": manifest["source_sha256"],
        "snapshot": snapshot_rel.as_posix(),
        "snapshot_sha256": _sha256(snapshot_bytes),
        "normalized": NORMALIZED_REL.as_posix(),
        "normalized_sha256": _sha256(normalized.read_bytes()),
        "related_sources": related_receipts,
        "normalizer": normalizer_receipt,
        "validator_version": VALIDATOR_VERSION,
        "operator_bound": bool(manifest["operator_directive"]["prompt_sha256"]),
        "valid": True,
        "validated_at": time.time(),
    }
    (run_dir / VALIDATOR_REL).write_bytes(_canonical_bytes(receipt))
    return receipt


def verify_bundle(run_dir: Path, manifest: dict | None = None, *, allow_legacy: bool = False) -> dict:
    state_manifest_path = run_dir / "state" / "setup_source.json"
    if manifest is None:
        try:
            manifest = json.loads(state_manifest_path.read_text(encoding="utf-8", errors="strict"))
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            raise SetupSourceError("invalid_source_manifest", "setup source manifest is unreadable") from exc
    if str(manifest.get("schema") or "") in LEGACY_SCHEMAS and allow_legacy:
        return validate_manifest(manifest, allow_legacy=True)
    snapshot_rel = Path(str(manifest.get("source", {}).get("snapshot") or ""))
    snapshot = run_dir / snapshot_rel
    normalized = run_dir / NORMALIZED_REL
    receipt_path = run_dir / VALIDATOR_REL
    try:
        snapshot_bytes = snapshot.read_bytes()
        normalized_bytes = normalized.read_bytes()
        receipt = json.loads(receipt_path.read_text(encoding="utf-8", errors="strict"))
        normalized_manifest = json.loads(normalized_bytes.decode("utf-8", "strict"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise SetupSourceError("invalid_source_bundle", f"source bundle is unreadable: {exc}") from exc
    if normalized_manifest != manifest:
        raise SetupSourceError("source_manifest_mismatch", "state and normalized source manifests differ")
    snapshot_json = None
    if manifest.get("source", {}).get("kind") in {"recon-json", "json"}:
        try:
            snapshot_json = json.loads(snapshot_bytes.decode("utf-8", "strict"))
        except (UnicodeError, json.JSONDecodeError) as exc:
            raise SetupSourceError("invalid_source_bundle", "JSON snapshot is unreadable") from exc
    validate_manifest(
        manifest, snapshot_bytes=snapshot_bytes, snapshot_json=snapshot_json,
    )
    related_receipts: list[dict] = []
    for descriptor in manifest["related_sources"]:
        related_rel = str(descriptor["snapshot"])
        try:
            related_bytes = (run_dir / related_rel).read_bytes()
        except OSError as exc:
            raise SetupSourceError(
                "missing_related_source", f"related snapshot is unreadable: {related_rel}"
            ) from exc
        if _sha256(related_bytes) != descriptor["sha256"]:
            raise SetupSourceError(
                "related_source_hash_mismatch", f"related snapshot hash mismatch: {related_rel}"
            )
        related_receipts.append({"snapshot": related_rel, "sha256": descriptor["sha256"]})
    normalizer_receipt: dict[str, object] = {}
    extractor = manifest["extractor"]
    if extractor["ai_backend"] is not None:
        for rel, schema_key, hash_key in (
            (NORMALIZER_REQUEST_REL, "request_schema", "request_sha256"),
            (NORMALIZER_CANDIDATE_REL, "candidate_schema", "candidate_sha256"),
        ):
            try:
                raw = (run_dir / rel).read_bytes()
                value = json.loads(raw.decode("utf-8", "strict"))
            except (OSError, UnicodeError, json.JSONDecodeError) as exc:
                raise SetupSourceError(
                    "normalizer_artifact_invalid", f"normalizer artifact is unreadable: {rel.as_posix()}"
                ) from exc
            if _sha256(raw) != extractor[hash_key] or not isinstance(value, dict) \
                    or value.get("schema") != extractor[schema_key]:
                raise SetupSourceError(
                    "normalizer_artifact_mismatch", f"normalizer artifact mismatch: {rel.as_posix()}"
                )
            normalizer_receipt[rel.as_posix()] = {
                "schema": extractor[schema_key], "sha256": extractor[hash_key],
            }
    expected_receipt = {
        "schema": VALIDATION_SCHEMA,
        "source_schema": SCHEMA,
        "source_sha256": manifest["source_sha256"],
        "snapshot": snapshot_rel.as_posix(),
        "snapshot_sha256": _sha256(snapshot_bytes),
        "normalized": NORMALIZED_REL.as_posix(),
        "normalized_sha256": _sha256(normalized_bytes),
        "related_sources": related_receipts,
        "normalizer": normalizer_receipt,
        "validator_version": VALIDATOR_VERSION,
        "operator_bound": bool(manifest["operator_directive"]["prompt_sha256"]),
        "valid": True,
    }
    if not isinstance(receipt, dict) or any(receipt.get(key) != value for key, value in expected_receipt.items()):
        raise SetupSourceError("invalid_validator_receipt", "source validator receipt does not match bundle")
    return receipt


def bind_operator_prompt(run_dir: Path, contract: dict, *, source_hash: str) -> dict:
    """Bind only hook-derived prompt authority immediately before pointer commit."""
    prompt_hash = str(contract.get("prompt_sha256") or "") if isinstance(contract, dict) else ""
    if not prompt_hash:
        return {}
    if not _SHA256_RE.fullmatch(prompt_hash):
        raise SetupSourceError("invalid_operator_binding", "hook contract prompt hash is invalid")
    state_path = run_dir / "state" / "setup_source.json"
    try:
        manifest = json.loads(state_path.read_text(encoding="utf-8", errors="strict"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise SetupSourceError("invalid_source_manifest", "cannot bind unreadable source manifest") from exc
    if manifest.get("schema") != SCHEMA or manifest.get("source_sha256") != source_hash:
        raise SetupSourceError("source_manifest_mismatch", "operator binding source identity mismatch")
    manifest["operator_directive"]["prompt_sha256"] = prompt_hash
    operator_ref = f"operator:prompt#sha256={prompt_hash}"
    if manifest["operator_directive"].get("provided_target") and not any(
        claim.get("authority") == "operator"
        for claim in manifest.get("authorization_claims", []) if isinstance(claim, dict)
    ):
        manifest["authorization_claims"].append({
            "value": "operator directed setup of the explicit target source",
            "authority": "operator",
            "source_ref": operator_ref,
        })
    snapshot_rel = Path(str(manifest["source"]["snapshot"]))
    snapshot_bytes = (run_dir / snapshot_rel).read_bytes()
    snapshot_json = None
    if manifest["source"]["kind"] in {"recon-json", "json"}:
        snapshot_json = json.loads(snapshot_bytes.decode("utf-8", "strict"))
    validate_manifest(manifest, snapshot_bytes=snapshot_bytes, snapshot_json=snapshot_json)
    state_path.write_bytes(_canonical_bytes(manifest))
    write_bundle(run_dir, manifest, snapshot_bytes)
    return manifest


def _recognizable_run(path: Path, runs_root: Path) -> Path | None:
    try:
        resolved = path.expanduser().resolve(strict=True)
        relative = resolved.relative_to(runs_root.resolve(strict=True))
    except (OSError, ValueError):
        return None
    if not relative.parts:
        return None
    run_dir = runs_root.resolve() / relative.parts[0]
    if not run_dir.is_dir() or not all(
        (run_dir / name).exists() for name in ("target.md", "frontier.md", "evidence")
    ):
        return None
    return run_dir


def _sniff_file(path: Path, raw: bytes, requested_type: str) -> str:
    if requested_type == "recon-json":
        try:
            data = json.loads(raw.decode("utf-8", "strict"))
        except (UnicodeError, json.JSONDecodeError) as exc:
            raise SetupSourceError("invalid_recon_json", f"recon JSON is invalid: {exc}") from exc
        if not valid_recon_data(data):
            raise SetupSourceError("unknown_recon_schema", "JSON is not a supported recon schema")
        return "recon-json"
    if raw.startswith(b"%PDF-") or raw.startswith(b"PK\x03\x04"):
        raise SetupSourceError("normalizer_required", "PDF/DOCX input requires candidate normalization")
    stripped = raw.lstrip()
    if stripped.startswith((b"{", b"[")):
        try:
            data = json.loads(raw.decode("utf-8", "strict"))
        except (UnicodeError, json.JSONDecodeError) as exc:
            raise SetupSourceError("invalid_json", f"JSON source is invalid: {exc}") from exc
        if valid_recon_data(data):
            return "recon-json"
        return "json"
    media, _ = mimetypes.guess_type(path.name)
    if media == "text/html" or re.search(br"(?is)^\s*<!doctype\s+html|^\s*<html\b", raw[:4096]):
        raise SetupSourceError("normalizer_required", "HTML input requires selector-aware candidate normalization")
    if media == "text/markdown" or re.search(
        br"(?m)^\s*(?:#{1,6}\s+|---\s*$|[-*+]\s+(?:Target|Asset|Scope|Authorization)\s*[:\xef\xbc\x9a])",
        raw[:65536],
    ):
        return "markdown"
    if media == "text/plain" or raw:
        raise SetupSourceError("normalizer_required", "plain-text input is deferred until offset-provenance benchmarks exist")
    raise SetupSourceError("unrecognized_source", "source type cannot be identified")


def _route_file(
    candidate_path: Path,
    raw_value: str,
    requested_type: str,
) -> SourceRoute:
    """Route one already selected local path through the bounded source owner."""
    file_bytes = read_source_bytes(candidate_path)
    resolved = candidate_path.resolve(strict=False)
    kind = _sniff_file(resolved, file_bytes, requested_type)
    if kind == "recon-json":
        data = json.loads(file_bytes.decode("utf-8", "strict"))
        first = data["assets"][0]
        first_value = next(
            str(first.get(key) or "").strip()
            for key in ("host", "asset", "name", "url")
            if str(first.get(key) or "").strip()
        )
        host, _ = _asset_from_value(first_value)
        return SourceRoute(
            "recon-json", raw_value, slug=_slug(host), source_path=resolved
        )
    if kind in {"json", "markdown"}:
        return SourceRoute(kind, raw_value, source_path=resolved)
    raise SetupSourceError("unrecognized_source", "source type cannot be identified")


def route_source(
    value: str,
    *,
    source_type: str = "auto",
    runs_root: Path = RUNS_ROOT,
) -> SourceRoute:
    requested = str(source_type or "auto").strip().lower()
    if requested not in SUPPORTED_TYPES:
        raise SetupSourceError("invalid_source_type", f"unsupported source type: {requested}")
    raw_value = str(value or "").strip()
    if not raw_value:
        raise SetupSourceError("missing_source", "source is empty")
    candidate_path = Path(raw_value).expanduser()
    if not candidate_path.is_absolute():
        candidate_path = Path.cwd() / candidate_path
    if requested in {"auto", "run"}:
        run_dir = _recognizable_run(candidate_path, runs_root)
        if run_dir is not None:
            return SourceRoute("run", raw_value, run_dir=run_dir)
        if requested == "run":
            raise SetupSourceError("invalid_run", f"not a recognizable run path: {raw_value}")
    # A concrete existing path is a stronger local identity than the bare-host
    # convenience grammar.  This lets an operator pass ``report.md`` from the
    # current directory without it silently becoming ``https://report.md/``.
    # Explicit HTTP(S) input and ``--type url`` remain unambiguous URL routes.
    if requested == "auto" and (
        candidate_path.exists() or candidate_path.is_symlink()
    ):
        return _route_file(candidate_path, raw_value, requested)
    normalized_target = ""
    if requested in {"auto", "url"}:
        try:
            normalized_target = normalize_operator_source(raw_value)
        except SetupSourceError:
            # Preserve the specific URL diagnostic below for explicit URL
            # spellings instead of falling through to a misleading file error.
            if re.match(r"(?i)^https?://", raw_value):
                raise
    if normalized_target and (
            re.match(r"(?i)^https?://", raw_value)
            or normalized_target != raw_value
    ):
        parsed = parse_target_url(normalized_target)
        return SourceRoute(
            "url", normalized_target, slug=_slug(str(parsed["host"]))
        )
    if requested == "url":
        parse_target_url(raw_value)
        raise SetupSourceError("invalid_url", "URL must start with http:// or https://")
    return _route_file(candidate_path, raw_value, requested)


def _selftest() -> int:
    fixture = json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))
    contract = json.loads(CONTRACT_PATH.read_text(encoding="utf-8"))
    temp = Path(tempfile.mkdtemp())
    runs = temp / "runs"
    run = runs / "existing_20260101"
    (run / "evidence").mkdir(parents=True)
    (run / "target.md").write_text("# target\n", encoding="utf-8")
    (run / "frontier.md").write_text("# frontier\n", encoding="utf-8")
    inside = run / "target.md"
    recon = temp / "recon.data"
    recon.write_text(json.dumps({
        "assets": [
            {"host": "example.test"}, {"url": "https://api.example.test:8443/a"},
        ],
        "scope": ["*.example.test"],
        "authorization_notes": "source-provided claim only",
    }), encoding="utf-8")
    ordinary = temp / "ordinary.json"
    ordinary.write_text(json.dumps({"url": "https://example.test"}), encoding="utf-8")
    markdown = temp / "report.bin"
    markdown.write_text("# target\nhttps://example.test\n", encoding="utf-8")
    relative_markdown = temp / "driver-offline-source.md"
    relative_markdown.write_text(
        "# Authorized target\n\n- Target: `http://127.0.0.1:9`\n",
        encoding="utf-8",
    )
    oversized = temp / "oversized.bin"
    with oversized.open("wb") as handle:
        handle.truncate(MAX_SOURCE_BYTES + 1)
    symlink = temp / "linked-recon.json"
    try:
        symlink.symlink_to(recon)
        symlink_supported = True
    except OSError:
        symlink_supported = False
    input_map = {
        "run": str(run), "run-file": str(inside), "recon-json": str(recon),
        "ordinary-json": str(ordinary), "markdown": str(markdown),
        "oversized": str(oversized), "symlink": str(symlink),
        "missing": str(temp / "missing"),
    }
    checks: list[tuple[str, bool]] = [
        ("contract freezes canonical schema", contract.get("properties", {}).get("schema", {}).get("const") == SCHEMA),
        (
            "contract names mandatory cross-field semantic validation",
            all(
                marker in str(contract.get("$comment") or "")
                for marker in (
                    "source_ref", "IDNA", "primary_url", "prompt_sha256",
                    "asset URL", "bundle hashes", "differential tests",
                )
            ),
        ),
        ("fixture matches source size", fixture.get("max_source_bytes") == MAX_SOURCE_BYTES),
    ]
    for case in fixture["route_cases"]:
        value = input_map.get(case.get("input_kind"), case.get("input"))
        try:
            route = route_source(str(value), source_type=case["type"], runs_root=runs)
            ok = route.kind == case["expect"]
        except SetupSourceError:
            ok = False
        checks.append((case["name"], ok))
    for case in fixture["deny_cases"]:
        value = input_map.get(case.get("input_kind"), case.get("input"))
        try:
            route_source(str(value), source_type=case["type"], runs_root=runs)
            code = ""
        except SetupSourceError as exc:
            code = exc.code
        checks.append((case["name"], code == case["error"]))

    url_manifest, url_bytes = normalize_url("https://例子.test:8443/a?key=opaque#frag")
    bare_route = route_source(
        "Cloud.SCSHR.com:443", source_type="auto", runs_root=runs,
    )
    checks.append((
        "bare host compiles to one canonical HTTPS source",
        bare_route.kind == "url"
        and bare_route.value == "https://cloud.scshr.com/",
    ))
    prior_cwd = Path.cwd()
    try:
        os.chdir(temp)
        relative_route = route_source(
            relative_markdown.name, source_type="auto", runs_root=runs,
        )
    finally:
        os.chdir(prior_cwd)
    checks.append((
        "existing relative Markdown filename outranks bare-host convenience",
        relative_route.kind == "markdown"
        and relative_route.source_path == relative_markdown.resolve(),
    ))
    checks.append((
        "equivalent URL syntax has one semantic identity",
        canonical_target_url("HTTPS://Cloud.SCSHR.com:443")
        == canonical_target_url("https://cloud.scshr.com/")
        == "https://cloud.scshr.com/",
    ))
    try:
        route_source(
            "https://cloud.scshr.com走代理渗透",
            source_type="auto",
            runs_root=runs,
        )
        attached_intent_rejected = False
    except SetupSourceError as exc:
        attached_intent_rejected = exc.code == "ambiguous_url_suffix"
    checks.append((
        "attached operator text cannot become an IDNA target",
        attached_intent_rejected,
    ))
    checks.append((
        "JSON Schema required fields match the canonical runtime shape",
        set(contract.get("required", [])) == set(url_manifest)
        and set(
            contract.get("properties", {}).get("source", {})
            .get("properties", {}).get("kind", {}).get("enum", [])
        ) == SOURCE_KINDS,
    ))
    for case in fixture.get("authority_cases", []):
        candidate = json.loads(json.dumps(url_manifest))
        prompt_hash = str(case.get("prompt_sha256") or "")
        candidate["operator_directive"]["prompt_sha256"] = prompt_hash
        if case.get("authority") == "operator":
            source_ref = f"operator:prompt#sha256={prompt_hash or ('0' * 64)}"
            claim_value = "operator directed setup of the explicit target source"
        else:
            source_ref = candidate["target"]["source_ref"]
            claim_value = candidate["target"]["primary_url"]
        candidate["authorization_claims"] = [{
            "value": claim_value,
            "authority": case.get("authority"),
            "source_ref": source_ref,
        }]
        try:
            validate_manifest(candidate, snapshot_bytes=url_bytes)
            case_valid = True
        except SetupSourceError:
            case_valid = False
        checks.append((str(case.get("name") or "authority case"), case_valid == bool(case["valid"])))
    bundle_run = temp / "bundle"
    (bundle_run / "state").mkdir(parents=True)
    write_bundle(bundle_run, url_manifest, url_bytes)
    (bundle_run / "state" / "setup_source.json").write_bytes(_canonical_bytes(url_manifest))
    checks.append(("URL preserves local full snapshot", (bundle_run / url_manifest["source"]["snapshot"]).read_bytes() == url_bytes))
    checks.append(("URL host is IDNA normalized", url_manifest["target"]["host"].startswith("xn--")))
    checks.append(("source bundle verifies", bool(verify_bundle(bundle_run))))
    bound = bind_operator_prompt(bundle_run, {"prompt_sha256": "a" * 64}, source_hash=url_manifest["source_sha256"])
    checks.append(("only bound hook prompt mints operator claim", bool(bound) and bound["authorization_claims"][-1]["authority"] == "operator"))
    checks.append(("bound source bundle re-verifies", bool(verify_bundle(bundle_run))))

    related_manifest, related_primary = normalize_url("https://related.example/")
    related_raw = b"# Recon report\nrelated.example reachable\n"
    related_rel = "sources/original/recon-report.md"
    add_related_source(
        related_manifest,
        kind="recon-report",
        reference=str(temp / "report.md"),
        snapshot=related_rel,
        media_type="text/markdown; charset=utf-8",
        raw=related_raw,
    )
    related_run = temp / "related-bundle"
    (related_run / "state").mkdir(parents=True)
    write_bundle(
        related_run, related_manifest, related_primary, {related_rel: related_raw}
    )
    (related_run / "state" / "setup_source.json").write_bytes(
        _canonical_bytes(related_manifest)
    )
    checks.append(("related setup input is frozen and verified", bool(verify_bundle(related_run))))
    (related_run / related_rel).write_bytes(b"mutated")
    try:
        verify_bundle(related_run)
        related_mutation_rejected = False
    except SetupSourceError as exc:
        related_mutation_rejected = exc.code == "related_source_hash_mismatch"
    checks.append(("related setup input mutation fails closed", related_mutation_rejected))

    recon_manifest, recon_bytes, recon_data = normalize_recon_path(recon)
    checks.append(("recon provenance uses JSON pointers", all(a["source_ref"].startswith("source:json#/") for a in recon_manifest["assets"])))
    checks.append(("recon coverage is full without probing", recon_manifest["coverage_quality"] == "full" and len(recon_manifest["assets"]) == 2))
    checks.append((
        "recon scope and authorization stay typed source candidates",
        recon_manifest["scope_candidates"] == [{
            "value": "*.example.test", "source_ref": "source:json#/scope/0",
        }]
        and recon_manifest["authorization_claims"][0]["authority"] == "source-data",
    ))
    changed = dict(recon_manifest)
    changed["schema"] = "xunji.setup-source.v2"
    try:
        validate_manifest(changed, snapshot_bytes=recon_bytes, snapshot_json=recon_data)
        unknown_rejected = False
    except SetupSourceError as exc:
        unknown_rejected = exc.code == "unsupported_source_schema"
    checks.append(("unknown schema fails closed", unknown_rejected))
    forged = json.loads(json.dumps(recon_manifest))
    forged["authorization_claims"] = [{
        "value": "source says authorized", "authority": "operator",
        "source_ref": "source:json#/assets/0/host",
    }]
    try:
        validate_manifest(forged, snapshot_bytes=recon_bytes, snapshot_json=recon_data)
        forged_rejected = False
    except SetupSourceError as exc:
        forged_rejected = exc.code == "operator_authority_unbound"
    checks.append(("source cannot forge operator authority", forged_rejected))
    unrelated = json.loads(json.dumps(recon_manifest))
    unrelated["assets"][0]["source_ref"] = "source:json#/assets/1/url"
    try:
        validate_manifest(unrelated, snapshot_bytes=recon_bytes, snapshot_json=recon_data)
        unrelated_rejected = False
    except SetupSourceError as exc:
        unrelated_rejected = exc.code == "source_ref_mismatch"
    checks.append(("source_ref must contain the claimed value", unrelated_rejected))
    traversal = json.loads(json.dumps(recon_manifest))
    traversal["source"]["snapshot"] = "../outside.json"
    try:
        validate_manifest(traversal, snapshot_bytes=recon_bytes, snapshot_json=recon_data)
        traversal_rejected = False
    except SetupSourceError as exc:
        traversal_rejected = exc.code == "snapshot_path_invalid"
    checks.append(("snapshot traversal fails closed", traversal_rejected))
    try:
        validate_manifest(recon_manifest, snapshot_bytes=recon_bytes + b" ", snapshot_json=recon_data)
        mutation_rejected = False
    except SetupSourceError as exc:
        mutation_rejected = exc.code == "source_hash_mismatch"
    checks.append(("source mutation fails hash validation", mutation_rejected))
    if symlink_supported:
        try:
            route_source(str(symlink), source_type="auto", runs_root=runs)
            symlink_rejected = False
        except SetupSourceError as exc:
            symlink_rejected = exc.code == "source_symlink_forbidden"
        checks.append(("symlink source fails closed", symlink_rejected))
    duplicate_data = {"assets": [{"host": "dup.example"}, {"url": "https://dup.example/"}]}
    duplicate_bytes = json.dumps(duplicate_data).encode("utf-8")
    try:
        normalize_recon(temp / "duplicate.json", duplicate_bytes, duplicate_data)
        duplicate_rejected = False
    except SetupSourceError as exc:
        duplicate_rejected = exc.code == "duplicate_asset"
    checks.append(("duplicate normalized assets fail closed", duplicate_rejected))
    legacy = {
        "schema": "xunji.setup_source.v1", "kind": "target_url",
        "source_sha256": _sha256(url_bytes), "display": "https://redacted.invalid/",
    }
    migrated = migrate_manifest(legacy, snapshot_bytes=url_bytes)
    checks.append(("known legacy URL migrates with exact snapshot", migrated["schema"] == SCHEMA))
    try:
        migrate_manifest(legacy)
        snapshot_required = False
    except SetupSourceError as exc:
        snapshot_required = exc.code == "migration_requires_snapshot"
    checks.append(("legacy migration without provenance fails closed", snapshot_required))

    bad = [name for name, ok in checks if not ok]
    for name, ok in checks:
        print(("ok   " if ok else "FAIL ") + name)
    print("setup_source selftest " + ("passed" if not bad else f"FAILED ({len(bad)})"))
    return 0 if not bad else 1


if __name__ == "__main__":
    raise SystemExit(_selftest())
