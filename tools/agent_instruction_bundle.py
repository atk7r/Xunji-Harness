#!/usr/bin/env python3
"""Compose and verify Claude-primary Agent instruction bundles.

The manifest maps canonical roles to repository-owned instruction sources. A
bundle freezes the exact source and generated artifact bytes for one assignment;
SHA-256 proves byte identity, not authorship or hidden Claude prompt attestation.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import stat
import tempfile
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
MANIFEST_REL = "contracts/agent-instruction-sources.v1.json"
MANIFEST_SCHEMA = "xunji.agent-instruction-sources.v1"
ROLE_CONTRACT_SCHEMA = "xunji.agent-role-contract.v1"
BUNDLE_SCHEMA = "xunji.agent-instruction-bundle.v1"
ROLE_PLACEHOLDER = "{{XUNJI_AGENT_ROLE_COMMON_V1}}"
MAX_SOURCE_BYTES = 512 * 1024
MAX_ARTIFACT_BYTES = 16 * 1024 * 1024
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


class InstructionBundleError(RuntimeError):
    """A stable fail-closed instruction source or artifact error."""

    def __init__(self, code: str, detail: str):
        super().__init__(detail)
        self.code = code


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _canonical_json_bytes(value: object) -> bytes:
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
    ).encode("utf-8")


def canonical_digest(value: object) -> str:
    return _sha256(_canonical_json_bytes(value))


def _relative_source_path(root: Path, raw: object) -> tuple[str, Path]:
    if not isinstance(raw, str) or not raw or "\\" in raw:
        raise InstructionBundleError("source_invalid", "instruction source path is invalid")
    rel = Path(raw)
    if rel.is_absolute() or any(part in {"", ".", ".."} for part in rel.parts):
        raise InstructionBundleError("source_invalid", "instruction source path escapes the repository")
    root_resolved = root.resolve()
    path = root / rel
    try:
        resolved = path.resolve(strict=False)
        resolved.relative_to(root_resolved)
    except (OSError, ValueError) as exc:
        raise InstructionBundleError(
            "source_invalid", "instruction source path escapes the repository",
        ) from exc
    return rel.as_posix(), path


def _read_source_bytes(root: Path, rel: Path) -> bytes:
    """Read one repository source without following any path-component symlink."""
    directory_flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) \
        | getattr(os, "O_NOFOLLOW", 0)
    file_flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
    opened: list[int] = []
    try:
        current_fd = os.open(root, directory_flags)
        opened.append(current_fd)
        for part in rel.parts[:-1]:
            current_fd = os.open(part, directory_flags, dir_fd=current_fd)
            opened.append(current_fd)
        file_fd = os.open(rel.name, file_flags, dir_fd=current_fd)
        opened.append(file_fd)
        info = os.fstat(file_fd)
        if not stat.S_ISREG(info.st_mode) or not 1 <= info.st_size <= MAX_SOURCE_BYTES:
            raise InstructionBundleError(
                "source_invalid", f"instruction source is not a bounded regular file: {rel}",
            )
        chunks: list[bytes] = []
        remaining = MAX_SOURCE_BYTES + 1
        while remaining > 0:
            chunk = os.read(file_fd, min(1024 * 1024, remaining))
            if not chunk:
                break
            chunks.append(chunk)
            remaining -= len(chunk)
        raw = b"".join(chunks)
        if len(raw) > MAX_SOURCE_BYTES:
            raise InstructionBundleError(
                "source_invalid", f"instruction source is too large: {rel}",
            )
        return raw
    except InstructionBundleError:
        raise
    except OSError as exc:
        raise InstructionBundleError(
            "source_invalid", f"instruction source cannot be opened safely: {rel}",
        ) from exc
    finally:
        for fd in reversed(opened):
            os.close(fd)


def _strict_source(root: Path, raw_path: object, *, marker: str = "") -> dict[str, Any]:
    rel, _ = _relative_source_path(root, raw_path)
    raw = _read_source_bytes(root, Path(rel))
    if not raw or len(raw) > MAX_SOURCE_BYTES or raw.startswith(b"\xef\xbb\xbf"):
        raise InstructionBundleError("source_invalid", f"instruction source bytes are invalid: {rel}")
    try:
        text = raw.decode("utf-8", errors="strict")
    except UnicodeDecodeError as exc:
        raise InstructionBundleError("source_invalid", f"instruction source is not strict UTF-8: {rel}") from exc
    if "\r" in text or not text.endswith("\n") or text.endswith("\n\n"):
        raise InstructionBundleError(
            "source_invalid", f"instruction source must use LF and one trailing newline: {rel}",
        )
    if marker and marker not in text:
        raise InstructionBundleError("source_invalid", f"instruction source marker missing: {rel}")
    return {"path": rel, "length": len(raw), "sha256": _sha256(raw), "text": text}


def _exact_object(value: object, fields: set[str], label: str) -> dict:
    if not isinstance(value, dict) or set(value) != fields:
        raise InstructionBundleError("source_invalid", f"{label} fields are invalid")
    return value


def load_manifest(*, root: Path = ROOT) -> dict:
    source = _strict_source(root, MANIFEST_REL)
    try:
        value = json.loads(source["text"])
    except Exception as exc:
        raise InstructionBundleError("source_invalid", "instruction source manifest is invalid JSON") from exc
    value = _exact_object(
        value, {"schema", "version", "common", "scaffold", "live_agents", "roles"},
        "instruction source manifest",
    )
    if value.get("schema") != MANIFEST_SCHEMA or value.get("version") != 1:
        raise InstructionBundleError("source_invalid", "instruction source manifest version is unsupported")
    source_fields = {"path", "version"}
    for label in ("common", "scaffold"):
        entry = _exact_object(value.get(label), source_fields, label)
        if not isinstance(entry.get("version"), str) or not entry["version"]:
            raise InstructionBundleError("source_invalid", f"{label} version is invalid")
    live = value.get("live_agents")
    if not isinstance(live, dict) or set(live) != {"xunji-hunter", "xunji-reviewer"}:
        raise InstructionBundleError("source_invalid", "live Agent source map is invalid")
    for agent_type, entry_value in live.items():
        entry = _exact_object(entry_value, source_fields, f"live Agent {agent_type}")
        if not isinstance(entry.get("version"), str) or not entry["version"]:
            raise InstructionBundleError("source_invalid", "live Agent version is invalid")
    roles = value.get("roles")
    expected_roles = {
        "surface", "web-auth", "web-hunter", "code-audit", "exploit",
        "verify", "review", "report", "synthesizer",
    }
    if not isinstance(roles, dict) or set(roles) != expected_roles:
        raise InstructionBundleError("source_invalid", "canonical role source map is invalid")
    role_fields = {"path", "version", "subagent_type", "assignable"}
    for role, entry_value in roles.items():
        entry = _exact_object(entry_value, role_fields, f"role {role}")
        expected_type = "xunji-reviewer" if role == "review" else "xunji-hunter"
        if role == "synthesizer":
            if entry.get("assignable") is not False or entry.get("subagent_type") is not None:
                raise InstructionBundleError("source_invalid", "synthesizer must remain non-assignable")
        elif entry.get("assignable") is not True or entry.get("subagent_type") != expected_type:
            raise InstructionBundleError("source_invalid", f"role {role} has the wrong live Agent type")
        if not isinstance(entry.get("version"), str) or not entry["version"]:
            raise InstructionBundleError("source_invalid", f"role {role} version is invalid")
    return {**value, "_source": source}


def _descriptor(source: dict, version: str) -> dict:
    return {
        "path": source["path"], "version": version,
        "length": source["length"], "sha256": source["sha256"],
    }


def load_role_contract(role: str, *, root: Path = ROOT) -> dict:
    manifest = load_manifest(root=root)
    roles = manifest["roles"]
    if role not in roles:
        raise InstructionBundleError("source_invalid", f"unknown canonical Agent role: {role}")
    common_entry = manifest["common"]
    role_entry = roles[role]
    common = _strict_source(
        root, common_entry["path"], marker="<!-- xunji.agent-role-common.v1 -->",
    )
    role_source = _strict_source(root, role_entry["path"])
    if role_source["text"].count(ROLE_PLACEHOLDER) != 1:
        raise InstructionBundleError(
            "source_invalid", f"role {role} must contain one common placeholder",
        )
    forbidden_common_markers = (
        "<!-- xunji.agent-role-common.v1 -->", "## Shared Role Method",
        "## Shared Return Delta", "## Coverage And Coda Check",
    )
    if any(marker in role_source["text"] for marker in forbidden_common_markers):
        raise InstructionBundleError("source_invalid", f"role {role} duplicates the common owner")
    composed = role_source["text"].replace(
        ROLE_PLACEHOLDER, common["text"].rstrip("\n"),
    )
    if ROLE_PLACEHOLDER in composed or composed.count(
            "<!-- xunji.agent-role-common.v1 -->") != 1:
        raise InstructionBundleError("source_invalid", f"role {role} composition is ambiguous")
    manifest_descriptor = {
        "path": MANIFEST_REL,
        "version": MANIFEST_SCHEMA,
        "length": manifest["_source"]["length"],
        "sha256": manifest["_source"]["sha256"],
    }
    subagent_type = role_entry.get("subagent_type") or ""
    live_descriptor: dict[str, Any] | None = None
    if subagent_type:
        live_entry = manifest["live_agents"][subagent_type]
        live = _strict_source(root, live_entry["path"])
        live_descriptor = _descriptor(live, live_entry["version"])
    contract = {
        "schema": ROLE_CONTRACT_SCHEMA,
        "manifest": manifest_descriptor,
        "common": _descriptor(common, common_entry["version"]),
        "role": {
            "id": role,
            **_descriptor(role_source, role_entry["version"]),
            "assignable": bool(role_entry["assignable"]),
        },
        "subagent_type": subagent_type,
        "live_agent": live_descriptor,
        "composed_length": len(composed.encode("utf-8")),
        "composed_sha256": _sha256(composed.encode("utf-8")),
    }
    return {"text": composed, "contract": contract}


def load_scaffold_source(*, root: Path = ROOT) -> dict:
    manifest = load_manifest(root=root)
    entry = manifest["scaffold"]
    source = _strict_source(
        root, entry["path"], marker="<!-- xunji.agent-scaffold.v1 -->",
    )
    return {"text": source["text"], "source": _descriptor(source, entry["version"])}


def artifact_descriptor(path: str, text: str) -> dict:
    raw = text.encode("utf-8")
    if not raw or len(raw) > MAX_ARTIFACT_BYTES:
        raise InstructionBundleError("artifact_invalid", "generated Agent artifact size is invalid")
    return {"path": path, "length": len(raw), "sha256": _sha256(raw)}


def build_assignment_bundle(
    *, assignment: str, plan_digest: str, lane_id: str, role: str,
    role_bundle: dict, scaffold_source: dict, context_path: str,
    context_text: str, agent_path: str, agent_text: str,
) -> tuple[dict, str]:
    contract = role_bundle.get("contract") if isinstance(role_bundle, dict) else None
    if not isinstance(contract, dict) or contract.get("schema") != ROLE_CONTRACT_SCHEMA:
        raise InstructionBundleError("source_invalid", "role contract is unavailable")
    bundle = {
        "schema": BUNDLE_SCHEMA,
        "assignment": assignment,
        "plan_digest": plan_digest,
        "lane_id": lane_id,
        "role": role,
        "subagent_type": str(contract.get("subagent_type") or ""),
        "role_contract": contract,
        "scaffold_source": scaffold_source,
        "context": artifact_descriptor(context_path, context_text),
        "agent_file": artifact_descriptor(agent_path, agent_text),
    }
    return bundle, canonical_digest(bundle)


def _artifact_path(
    root: Path, run_dir: Path, descriptor: object, expected_path: str,
    directory: str, assignment: str,
) -> tuple[Path, dict]:
    desc = _exact_object(descriptor, {"path", "length", "sha256"}, directory)
    if desc.get("path") != expected_path \
            or not isinstance(desc.get("length"), int) \
            or isinstance(desc.get("length"), bool) \
            or not 1 <= desc["length"] <= MAX_ARTIFACT_BYTES \
            or not isinstance(desc.get("sha256"), str) \
            or not SHA256_RE.fullmatch(desc["sha256"]):
        raise InstructionBundleError("artifact_invalid", f"{directory} descriptor is invalid")
    raw_path = Path(expected_path)
    path = raw_path if raw_path.is_absolute() else root / raw_path
    expected_directory = run_dir / directory
    try:
        directory_mode = expected_directory.lstat().st_mode
    except OSError as exc:
        raise InstructionBundleError(
            "artifact_invalid", f"{directory} artifact directory is missing",
        ) from exc
    if stat.S_ISLNK(directory_mode) or not stat.S_ISDIR(directory_mode):
        raise InstructionBundleError(
            "artifact_invalid", f"{directory} artifact directory is not a real directory",
        )
    expected_parent = expected_directory.resolve()
    try:
        if path.resolve(strict=False).parent != expected_parent:
            raise ValueError
    except (OSError, ValueError) as exc:
        raise InstructionBundleError("artifact_invalid", f"{directory} path escapes its run directory") from exc
    if directory == "agents" and path.name != f"{assignment}.md":
        raise InstructionBundleError("artifact_invalid", "Agent scaffold identity is invalid")
    try:
        mode = path.lstat().st_mode
    except OSError as exc:
        raise InstructionBundleError("artifact_invalid", f"{directory} artifact is missing") from exc
    if stat.S_ISLNK(mode) or not stat.S_ISREG(mode):
        raise InstructionBundleError("artifact_invalid", f"{directory} artifact is not a regular file")
    return path, desc


def _read_artifact_bytes(path: Path) -> bytes:
    """Read one direct child without following a swapped directory or leaf symlink."""
    directory_flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) \
        | getattr(os, "O_NOFOLLOW", 0)
    file_flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
    directory_fd = -1
    file_fd = -1
    try:
        directory_fd = os.open(path.parent, directory_flags)
        file_fd = os.open(path.name, file_flags, dir_fd=directory_fd)
        info = os.fstat(file_fd)
        if not stat.S_ISREG(info.st_mode) or not 1 <= info.st_size <= MAX_ARTIFACT_BYTES:
            raise InstructionBundleError(
                "artifact_invalid", f"instruction artifact is not a bounded regular file: {path.name}",
            )
        chunks: list[bytes] = []
        remaining = MAX_ARTIFACT_BYTES + 1
        while remaining > 0:
            chunk = os.read(file_fd, min(1024 * 1024, remaining))
            if not chunk:
                break
            chunks.append(chunk)
            remaining -= len(chunk)
        raw = b"".join(chunks)
        if len(raw) > MAX_ARTIFACT_BYTES:
            raise InstructionBundleError(
                "artifact_invalid", f"instruction artifact is too large: {path.name}",
            )
        return raw
    except InstructionBundleError:
        raise
    except OSError as exc:
        raise InstructionBundleError(
            "artifact_invalid", f"instruction artifact cannot be opened safely: {path.name}",
        ) from exc
    finally:
        if file_fd >= 0:
            os.close(file_fd)
        if directory_fd >= 0:
            os.close(directory_fd)


def verify_assignment_bundle(
    run_dir: Path, row: object, *, root: Path = ROOT,
) -> dict:
    if not isinstance(row, dict) or row.get("schema") != "xunji.assignment.v1":
        raise InstructionBundleError("source_invalid", "typed assignment row is required")
    bundle = row.get("instruction_bundle")
    digest = row.get("instruction_bundle_sha256")
    fields = {
        "schema", "assignment", "plan_digest", "lane_id", "role",
        "subagent_type", "role_contract", "scaffold_source", "context", "agent_file",
    }
    bundle = _exact_object(bundle, fields, "instruction bundle")
    if bundle.get("schema") != BUNDLE_SCHEMA \
            or not isinstance(digest, str) or not SHA256_RE.fullmatch(digest) \
            or canonical_digest(bundle) != digest:
        raise InstructionBundleError("source_invalid", "instruction bundle digest is invalid")
    expected_identity = {
        "assignment": str(row.get("agent") or ""),
        "plan_digest": str(row.get("plan_digest") or ""),
        "lane_id": str(row.get("lane_id") or ""),
        "role": str(row.get("role") or ""),
    }
    if any(bundle.get(field) != value for field, value in expected_identity.items()):
        raise InstructionBundleError("source_invalid", "instruction bundle identity does not match assignment")
    current_role = load_role_contract(expected_identity["role"], root=root)
    if bundle.get("role_contract") != current_role["contract"]:
        raise InstructionBundleError("source_stale", "instruction role or live Agent source changed")
    if bundle.get("subagent_type") != current_role["contract"].get("subagent_type"):
        raise InstructionBundleError("source_stale", "instruction live Agent type changed")
    current_scaffold = load_scaffold_source(root=root)
    if bundle.get("scaffold_source") != current_scaffold["source"]:
        raise InstructionBundleError("source_stale", "Agent scaffold source changed")
    assignment = expected_identity["assignment"]
    context_path = str(row.get("context") or "")
    agent_path = str(row.get("agent_file") or "")
    for path, desc in (
        _artifact_path(root, run_dir, bundle.get("context"), context_path, "context", assignment),
        _artifact_path(root, run_dir, bundle.get("agent_file"), agent_path, "agents", assignment),
    ):
        raw = _read_artifact_bytes(path)
        try:
            raw.decode("utf-8", errors="strict")
        except UnicodeDecodeError as exc:
            raise InstructionBundleError("artifact_invalid", f"artifact is not strict UTF-8: {path.name}") from exc
        if len(raw) != desc["length"] or _sha256(raw) != desc["sha256"]:
            raise InstructionBundleError("artifact_invalid", f"instruction artifact bytes changed: {path.name}")
    return {"bundle": bundle, "digest": digest}


def selftest(*, root: Path = ROOT) -> list[str]:
    errors: list[str] = []
    try:
        manifest = load_manifest(root=root)
        for role in sorted(manifest["roles"]):
            bundle = load_role_contract(role, root=root)
            text = bundle["text"]
            if text.count("<!-- xunji.agent-role-common.v1 -->") != 1:
                errors.append(f"{role}: common role block count is not one")
            if ROLE_PLACEHOLDER in text:
                errors.append(f"{role}: unresolved common placeholder")
            if "workers.py heartbeat/finish" in text or "workers.py finish" in text:
                errors.append(f"{role}: stale lifecycle command")
        load_scaffold_source(root=root)
    except InstructionBundleError as exc:
        errors.append(f"{exc.code}: {exc}")
        return errors

    def expect_error(code: str, label: str, action) -> None:
        try:
            action()
        except InstructionBundleError as exc:
            if exc.code != code:
                errors.append(f"{label}: expected {code}, got {exc.code}")
        except Exception as exc:  # pragma: no cover - diagnostic guard
            errors.append(f"{label}: unexpected {type(exc).__name__}: {exc}")
        else:
            errors.append(f"{label}: mutation was accepted")

    with tempfile.TemporaryDirectory() as tmp:
        fixture_root = Path(tmp)
        source_paths = {
            MANIFEST_REL,
            manifest["common"]["path"],
            manifest["scaffold"]["path"],
            *(item["path"] for item in manifest["live_agents"].values()),
            *(item["path"] for item in manifest["roles"].values()),
        }
        for rel in source_paths:
            target = fixture_root / rel
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes((root / rel).read_bytes())

        run_dir = fixture_root / "runs" / "instruction-bundle-selftest"
        context_path = run_dir / "context" / "A-bundle.md"
        agent_path = run_dir / "agents" / "A-bundle.md"
        context_path.parent.mkdir(parents=True)
        agent_path.parent.mkdir(parents=True)
        context_text = "# Frozen context\n"
        agent_text = "# Frozen Agent scaffold\n"
        context_path.write_text(context_text, encoding="utf-8")
        agent_path.write_text(agent_text, encoding="utf-8")
        role_bundle = load_role_contract("web-hunter", root=fixture_root)
        scaffold = load_scaffold_source(root=fixture_root)
        bundle, digest = build_assignment_bundle(
            assignment="A-bundle",
            plan_digest="a" * 64,
            lane_id="L-BUNDLE",
            role="web-hunter",
            role_bundle=role_bundle,
            scaffold_source=scaffold["source"],
            context_path=context_path.relative_to(fixture_root).as_posix(),
            context_text=context_text,
            agent_path=agent_path.relative_to(fixture_root).as_posix(),
            agent_text=agent_text,
        )
        row = {
            "schema": "xunji.assignment.v1",
            "agent": "A-bundle",
            "plan_digest": "a" * 64,
            "lane_id": "L-BUNDLE",
            "role": "web-hunter",
            "context": context_path.relative_to(fixture_root).as_posix(),
            "agent_file": agent_path.relative_to(fixture_root).as_posix(),
            "instruction_bundle": bundle,
            "instruction_bundle_sha256": digest,
        }
        try:
            verify_assignment_bundle(run_dir, row, root=fixture_root)
        except InstructionBundleError as exc:
            errors.append(f"valid assignment bundle: {exc.code}: {exc}")

        context_path.write_text(context_text + "tampered\n", encoding="utf-8")
        expect_error(
            "artifact_invalid", "context byte tamper",
            lambda: verify_assignment_bundle(run_dir, row, root=fixture_root),
        )
        context_path.write_text(context_text, encoding="utf-8")

        agent_path.write_text(agent_text + "tampered\n", encoding="utf-8")
        expect_error(
            "artifact_invalid", "Agent scaffold byte tamper",
            lambda: verify_assignment_bundle(run_dir, row, root=fixture_root),
        )
        agent_path.write_text(agent_text, encoding="utf-8")

        common_path = fixture_root / manifest["common"]["path"]
        common_bytes = common_path.read_bytes()
        common_path.write_bytes(common_bytes[:-1] + b" \n")
        expect_error(
            "source_stale", "common source byte drift",
            lambda: verify_assignment_bundle(run_dir, row, root=fixture_root),
        )
        common_path.write_bytes(common_bytes)

        live_path = fixture_root / manifest["live_agents"]["xunji-hunter"]["path"]
        live_bytes = live_path.read_bytes()
        live_path.write_bytes(live_bytes[:-1] + b" \n")
        expect_error(
            "source_stale", "live Agent source byte drift",
            lambda: verify_assignment_bundle(run_dir, row, root=fixture_root),
        )
        live_path.write_bytes(live_bytes)

        role_path = fixture_root / manifest["roles"]["web-hunter"]["path"]
        role_bytes = role_path.read_bytes()
        role_path.write_bytes(role_bytes[:-1] + b" \n")
        expect_error(
            "source_stale", "role source byte drift",
            lambda: verify_assignment_bundle(run_dir, row, root=fixture_root),
        )
        role_path.write_bytes(role_bytes)

        scaffold_path = fixture_root / manifest["scaffold"]["path"]
        scaffold_bytes = scaffold_path.read_bytes()
        scaffold_path.write_bytes(scaffold_bytes[:-1] + b" \n")
        expect_error(
            "source_stale", "scaffold source byte drift",
            lambda: verify_assignment_bundle(run_dir, row, root=fixture_root),
        )
        scaffold_path.write_bytes(scaffold_bytes)

        role_path.write_bytes(role_bytes.replace(
            ROLE_PLACEHOLDER.encode("utf-8"), b"common owner omitted", 1,
        ))
        expect_error(
            "source_invalid", "missing common composition placeholder",
            lambda: load_role_contract("web-hunter", root=fixture_root),
        )
        role_path.write_bytes(role_bytes)

        common_backup = common_path.with_suffix(".backup")
        common_backup.write_bytes(common_bytes)
        common_path.unlink()
        common_path.symlink_to(common_backup)
        expect_error(
            "source_invalid", "symlink instruction source",
            lambda: load_role_contract("web-hunter", root=fixture_root),
        )
        common_path.unlink()
        common_path.write_bytes(common_bytes)

        source_directory = fixture_root / "docs" / "templates" / "agents"
        real_source_directory = fixture_root / "docs" / "templates" / "agents.real"
        source_directory.rename(real_source_directory)
        source_directory.symlink_to(real_source_directory, target_is_directory=True)
        expect_error(
            "source_invalid", "symlink instruction source ancestor",
            lambda: load_role_contract("web-hunter", root=fixture_root),
        )
        source_directory.unlink()
        real_source_directory.rename(source_directory)

        agent_path.unlink()
        agent_path.symlink_to(context_path)
        expect_error(
            "artifact_invalid", "symlink generated artifact",
            lambda: verify_assignment_bundle(run_dir, row, root=fixture_root),
        )
        agent_path.unlink()
        agent_path.write_text(agent_text, encoding="utf-8")

        context_directory = context_path.parent
        real_context_directory = run_dir / "context.real"
        context_directory.rename(real_context_directory)
        outside_context_directory = fixture_root / "outside-context"
        outside_context_directory.mkdir()
        (outside_context_directory / context_path.name).write_text(
            context_text, encoding="utf-8")
        context_directory.symlink_to(outside_context_directory, target_is_directory=True)
        expect_error(
            "artifact_invalid", "symlink artifact directory escape",
            lambda: verify_assignment_bundle(run_dir, row, root=fixture_root),
        )
        context_directory.unlink()
        real_context_directory.rename(context_directory)

        identity_tamper = json.loads(json.dumps(row))
        identity_tamper["instruction_bundle"]["assignment"] = "A-other"
        identity_tamper["instruction_bundle_sha256"] = canonical_digest(
            identity_tamper["instruction_bundle"])
        expect_error(
            "source_invalid", "rehashed bundle identity tamper",
            lambda: verify_assignment_bundle(
                run_dir, identity_tamper, root=fixture_root),
        )
        digest_tamper = {**row, "instruction_bundle_sha256": "0" * 64}
        expect_error(
            "source_invalid", "bundle digest tamper",
            lambda: verify_assignment_bundle(
                run_dir, digest_tamper, root=fixture_root),
        )
        schema_tamper = json.loads(json.dumps(row))
        schema_tamper["instruction_bundle"]["schema"] = "xunji.agent-instruction-bundle.v2"
        schema_tamper["instruction_bundle_sha256"] = canonical_digest(
            schema_tamper["instruction_bundle"])
        expect_error(
            "source_invalid", "unknown instruction bundle schema",
            lambda: verify_assignment_bundle(
                run_dir, schema_tamper, root=fixture_root),
        )
        expect_error(
            "source_invalid", "unknown canonical role",
            lambda: load_role_contract("unknown", root=fixture_root),
        )

        manifest_path = fixture_root / MANIFEST_REL
        manifest_bytes = manifest_path.read_bytes()
        manifest_value = json.loads(manifest_bytes)
        manifest_value["unexpected"] = True
        manifest_path.write_text(
            json.dumps(manifest_value, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        expect_error(
            "source_invalid", "manifest extra field",
            lambda: load_manifest(root=fixture_root),
        )
        manifest_path.write_bytes(manifest_bytes)
    return errors
