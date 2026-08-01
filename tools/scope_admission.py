#!/usr/bin/env python3
"""Operator-bound, zero-probe admission for setup-source candidate assets.

The command changes only the canonical coverage scope status and derived local
ledgers.  It performs no DNS lookup, socket operation, HTTP request, target
action, pointer mutation, or Cron operation.  A fresh claim written by the
``UserPromptSubmit``/``PreToolUse`` hook path is mandatory; invoking this file
directly cannot mint operator authority.
"""
from __future__ import annotations

import argparse
import hashlib
import ipaddress
import json
import math
import os
import re
import shlex
import sys
import tempfile
import time
from pathlib import Path
from urllib.parse import urlsplit

import contract_schema


ROOT = Path(__file__).resolve().parents[1]
RUNS_ROOT = ROOT / "runs"
ACTIVE_POINTER = ROOT / ".claude" / "xunji_active_run"
CLAIMS_DIR = Path(os.environ.get(
    "XUNJI_SCOPE_ADMISSION_CLAIMS_DIR",
    str(ROOT / ".claude" / "xunji_scope_admission_claims"),
))
DIRECTIVE = "/xunji-scope-admit"
CLAIM_SCHEMA = "xunji.scope_admission_claim.v1"
RECEIPT_SCHEMA = "xunji.scope_admission.v1"
CANDIDATE_SOURCE_KINDS = frozenset({"json", "markdown", "html", "pdf", "docx", "text"})
MAX_ASSETS = 128
STALE_SECONDS = 15 * 60


class ScopeAdmissionError(RuntimeError):
    """Structured fail-closed scope-admission error."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


def _canonical_bytes(value: object) -> bytes:
    return (json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
    ) + "\n").encode("utf-8")


def _sha256(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _atomic_bytes(path: Path, raw: bytes, *, mode: int = 0o600) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=path.name + ".", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(raw)
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(tmp, mode)
        os.replace(tmp, path)
    finally:
        try:
            os.unlink(tmp)
        except FileNotFoundError:
            pass


def _atomic_json(path: Path, value: dict) -> None:
    _atomic_bytes(path, json.dumps(
        value, ensure_ascii=False, indent=2, sort_keys=True,
    ).encode("utf-8") + b"\n")


def receipt_errors(value: object) -> list[str]:
    """Validate the formal receipt plus canonical semantic relationships."""
    errors = contract_schema.named_schema_errors(
        value, "scope-admission.v1.schema.json",
    )
    if errors or not isinstance(value, dict):
        return errors
    assets = value.get("assets") if isinstance(value.get("assets"), list) else []
    try:
        normalized = sorted(normalize_asset(str(item)) for item in assets)
    except ScopeAdmissionError:
        errors.append("$.assets: invalid canonical asset")
        normalized = []
    if assets != normalized:
        errors.append("$.assets: assets are not canonical and sorted")
    prepared_at = value.get("prepared_at")
    committed_at = value.get("committed_at")
    if not isinstance(prepared_at, (int, float)) \
            or isinstance(prepared_at, bool) or not math.isfinite(prepared_at) \
            or prepared_at <= 0:
        errors.append("$.prepared_at: invalid timestamp")
    prepared_valid = bool(
        isinstance(prepared_at, (int, float))
        and not isinstance(prepared_at, bool)
        and math.isfinite(prepared_at)
        and prepared_at > 0
    )
    if committed_at is not None and (
            not isinstance(committed_at, (int, float))
            or isinstance(committed_at, bool)
            or not math.isfinite(committed_at)
            or not prepared_valid
            or committed_at < prepared_at):
        errors.append("$.committed_at: precedes prepare or is invalid")
    return errors


def _require_receipt(value: object, *, code: str) -> dict:
    errors = receipt_errors(value)
    if errors or not isinstance(value, dict):
        raise ScopeAdmissionError(code, "; ".join(errors[:4] or ["invalid receipt"]))
    return value


def normalize_asset(value: str) -> str:
    """Return one exact host/IP scope key; URLs, ports and wildcards are invalid."""
    raw = str(value or "").strip()
    if not raw or len(raw) > 253 or any(char in raw for char in "\x00\r\n/*?[]%"):
        raise ScopeAdmissionError("invalid_asset", "asset must be one exact host or IP")
    if "://" in raw or "/" in raw or "@" in raw:
        raise ScopeAdmissionError("invalid_asset", "asset must not be a URL, path, or userinfo")
    candidate = raw.rstrip(".")
    try:
        return str(ipaddress.ip_address(candidate)).lower()
    except ValueError:
        pass
    if ":" in candidate:
        raise ScopeAdmissionError("invalid_asset", "host:port and invalid IPv6 are not accepted")
    try:
        ascii_host = candidate.encode("idna").decode("ascii").lower()
    except UnicodeError as exc:
        raise ScopeAdmissionError("invalid_asset", "asset IDNA encoding failed") from exc
    # `localhost` is the one standards-defined single-label host used by the
    # local operator fixture. Keep every other single-label name invalid so a
    # typo or search-domain-dependent intranet label cannot silently enter scope.
    if ascii_host == "localhost":
        return ascii_host
    labels = ascii_host.split(".")
    if len(ascii_host) > 253 or len(labels) < 2 or any(
        not re.fullmatch(r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?", label)
        for label in labels
    ):
        raise ScopeAdmissionError("invalid_asset", "asset hostname syntax is invalid")
    return ascii_host


def _run_from_value(
    value: str, *, root: Path = ROOT, runs_root: Path = RUNS_ROOT,
) -> tuple[Path, str]:
    raw = str(value or "").strip().replace("\\", "/")
    if not raw or "\x00" in raw or "\n" in raw or "\r" in raw:
        raise ScopeAdmissionError("invalid_run", "run path is empty or contains control bytes")
    match = re.fullmatch(r"runs/([^/]+)", raw)
    if not match or match.group(1) in {".", ".."}:
        raise ScopeAdmissionError("invalid_run", "run must use the exact runs/<name> form")
    candidate = runs_root / match.group(1)
    try:
        resolved = candidate.resolve(strict=False)
        resolved.relative_to(runs_root.resolve())
    except ValueError as exc:
        raise ScopeAdmissionError("invalid_run", "run must resolve under runs/") from exc
    if resolved.parent != runs_root.resolve() or not resolved.name:
        raise ScopeAdmissionError("invalid_run", "scope admission requires one direct runs/<name> path")
    return resolved, resolved.name


def _parse_assets(value: str) -> list[str]:
    raw_items = str(value or "").split(",")
    if not raw_items or len(raw_items) > MAX_ASSETS or any(not item.strip() for item in raw_items):
        raise ScopeAdmissionError(
            "invalid_assets", f"assets must contain 1-{MAX_ASSETS} comma-separated exact hosts/IPs",
        )
    assets: list[str] = []
    for raw in raw_items:
        asset = normalize_asset(raw)
        if asset in assets:
            raise ScopeAdmissionError("duplicate_asset", f"asset is repeated: {asset}")
        assets.append(asset)
    return sorted(assets)


NATURAL_ASSET_RE = re.compile(
    r"(?<![A-Za-z0-9_.-])(?:localhost|(?:\d{1,3}\.){3}\d{1,3}|"
    r"(?:[A-Za-z0-9](?:[A-Za-z0-9-]{0,62})\.)+"
    r"[A-Za-z](?:[A-Za-z0-9-]{0,62}))(?![A-Za-z0-9_.-])",
    re.I,
)


def _natural_scope_request(
    first: str, *, root: Path, runs_root: Path,
) -> tuple[dict | None, str]:
    """Compile a clear operator sentence into the existing typed admission."""
    patterns = (
        re.compile(
            r"^(?:请)?(?:把|将)\s*(?P<assets>.+?)\s*"
            r"(?:加入|添加到|纳入)\s*(?P<run>runs[/\\][A-Za-z0-9_-]+)"
            r"\s*(?:的|到)?\s*(?:scope|范围|作用域)",
            re.I,
        ),
        re.compile(
            r"^(?:please\s+)?add\s+(?P<assets>.+?)\s+to\s+"
            r"(?:(?:the\s+)?scope\s+(?:of|for)\s+)?"
            r"(?P<run>runs[/\\][A-Za-z0-9_-]+)(?:\s+scope)?",
            re.I,
        ),
    )
    match = None
    for candidate in patterns:
        match = candidate.search(first)
        if match is not None:
            break
    if match is None:
        attempted = bool(
            re.search(r"(?:加入|添加|纳入|\badd\b)", first, re.I)
            and re.search(r"(?:scope|范围|作用域)", first, re.I)
        )
        if attempted:
            return None, "natural scope admission intent is ambiguous"
        return None, ""
    asset_values = [
        candidate.group(0)
        for candidate in NATURAL_ASSET_RE.finditer(match.group("assets"))
    ]
    if not asset_values:
        return None, "natural scope admission names no exact host or IP"
    try:
        run_dir, run_name = _run_from_value(
            match.group("run"), root=root, runs_root=runs_root,
        )
        assets = _parse_assets(",".join(asset_values))
    except ScopeAdmissionError as exc:
        return None, str(exc)
    reason_match = re.search(
        r"(?:因为|原因(?:是|为)?|reason\s*[:=]?|because)\s*(.+)$",
        first,
        re.I,
    )
    reason = (
        str(reason_match.group(1)).strip()
        if reason_match else first.strip()
    )
    if len(reason) < 3 or len(reason) > 500:
        return None, "scope admission reason must contain 3-500 characters"
    return {
        "run_dir": str(run_dir),
        "run_name": run_name,
        "assets": assets,
        "reason": reason,
        "reason_sha256": _sha256(reason.encode("utf-8", "replace")),
        "intent_format": "natural-language",
    }, ""


def parse_operator_directive(
    prompt: str, *, root: Path = ROOT, runs_root: Path = RUNS_ROOT,
) -> tuple[dict | None, str]:
    """Parse the exact first non-empty operator line.

    ``(None, "")`` means no scope directive.  A non-empty error means the first
    line attempted this directive but was malformed and must not fall through to
    generic execute authority.
    """
    first = next((line.strip() for line in str(prompt or "").splitlines() if line.strip()), "")
    if not first.startswith(DIRECTIVE):
        return _natural_scope_request(first, root=root, runs_root=runs_root)
    if not re.match(r"^/xunji-scope-admit(?:\s|$)", first):
        return None, "scope admission directive name must match exactly"
    try:
        tokens = shlex.split(first)
    except ValueError as exc:
        return None, f"scope admission directive quoting is invalid: {exc}"
    if len(tokens) < 7 or tokens[0] != DIRECTIVE \
            or tokens[1] != "--run" or tokens[3] != "--assets" or tokens[5] != "--reason":
        return None, (
            "scope admission directive must be: /xunji-scope-admit --run "
            "runs/<name> --assets <host[,host...]> --reason <text>"
        )
    if any(token.startswith("--") for token in tokens[6:]):
        return None, "scope admission directive contains an unknown or repeated option"
    try:
        run_dir, run_name = _run_from_value(tokens[2], root=root, runs_root=runs_root)
        assets = _parse_assets(tokens[4])
    except ScopeAdmissionError as exc:
        return None, str(exc)
    reason = " ".join(tokens[6:]).strip()
    if len(reason) < 3 or len(reason) > 500:
        return None, "scope admission reason must contain 3-500 characters"
    return {
        "run_dir": str(run_dir),
        "run_name": run_name,
        "assets": assets,
        "reason": reason,
        "reason_sha256": _sha256(reason.encode("utf-8", "replace")),
    }, ""


def parse_invocation(
    args: list[str], *, root: Path = ROOT, runs_root: Path = RUNS_ROOT,
) -> dict:
    if len(args) != 3 or args[1] != "--assets":
        raise ScopeAdmissionError(
            "invalid_invocation",
            "usage: scope_admission.py runs/<name> --assets host[,host...]",
        )
    run_dir, run_name = _run_from_value(args[0], root=root, runs_root=runs_root)
    return {"run_dir": str(run_dir), "run_name": run_name, "assets": _parse_assets(args[2])}


def _claim_path(claim: dict, claims_dir: Path) -> Path:
    identity = {
        "run": claim.get("run_name"),
        "assets": claim.get("assets"),
        "session": claim.get("session_id"),
        "prompt": claim.get("prompt_sha256"),
    }
    return claims_dir / (_sha256(_canonical_bytes(identity)) + ".json")


def write_hook_claim(
    run_dir: Path, contract: dict, *, claims_dir: Path | None = None,
) -> dict:
    """Persist the hook-authorized exact admission; callers must be PreToolUse."""
    if contract_schema.turn_contract_errors(contract, allow_legacy=False):
        raise ScopeAdmissionError(
            "invalid_contract", "turn contract violates its formal contract")
    assets = [str(item) for item in (contract.get("scope_admission_assets") or [])]
    session_id = str(contract.get("session_id") or "")
    prompt_sha = str(contract.get("prompt_sha256") or "")
    reason_sha = str(contract.get("scope_admission_reason_sha256") or "")
    if contract.get("scope_admission_run") != run_dir.name or not assets \
            or not session_id or not re.fullmatch(r"[0-9a-f]{64}", prompt_sha) \
            or not re.fullmatch(r"[0-9a-f]{64}", reason_sha):
        raise ScopeAdmissionError("invalid_contract", "turn contract lacks exact scope admission authority")
    claim = {
        "schema": CLAIM_SCHEMA,
        "run_name": run_dir.name,
        "assets": assets,
        "session_id": session_id,
        "prompt_sha256": prompt_sha,
        "reason_sha256": reason_sha,
        "updated_at": time.time(),
    }
    _atomic_json(_claim_path(claim, claims_dir or CLAIMS_DIR), claim)
    return claim


def _load_json(path: Path, *, code: str) -> dict:
    try:
        value = json.loads(path.read_text(encoding="utf-8", errors="strict"))
    except Exception as exc:
        raise ScopeAdmissionError(code, f"cannot read {path.name}: {type(exc).__name__}") from exc
    if not isinstance(value, dict):
        raise ScopeAdmissionError(code, f"{path.name} must contain a JSON object")
    return value


def _consume_claim(run_dir: Path, assets: list[str], claims_dir: Path) -> tuple[dict, Path]:
    contract = _load_json(run_dir / "state" / "turn_contract.json", code="invalid_contract")
    if contract_schema.turn_contract_errors(contract, allow_legacy=False):
        raise ScopeAdmissionError(
            "invalid_contract", "turn contract violates its formal contract")
    candidates: list[tuple[Path, dict]] = []
    if claims_dir.is_dir():
        for path in claims_dir.glob("*.json"):
            try:
                claim = json.loads(path.read_text(encoding="utf-8", errors="strict"))
                age = time.time() - float(claim.get("updated_at") or 0.0)
            except Exception:
                continue
            if claim.get("schema") == CLAIM_SCHEMA and claim.get("run_name") == run_dir.name \
                    and claim.get("assets") == assets \
                    and claim.get("session_id") == contract.get("session_id") \
                    and claim.get("prompt_sha256") == contract.get("prompt_sha256") \
                    and claim.get("reason_sha256") \
                    == contract.get("scope_admission_reason_sha256") \
                    and 0 <= age <= STALE_SECONDS:
                candidates.append((path, claim))
    if len(candidates) != 1:
        raise ScopeAdmissionError(
            "claim_missing" if not candidates else "claim_ambiguous",
            "exactly one fresh hook-owned scope admission claim is required",
        )
    path, claim = candidates[0]
    if contract.get("session_id") != claim.get("session_id") \
            or contract.get("prompt_sha256") != claim.get("prompt_sha256") \
            or contract.get("scope_admission_run") != run_dir.name \
            or contract.get("scope_admission_assets") != assets \
            or contract.get("scope_admission_reason_sha256") != claim.get("reason_sha256"):
        raise ScopeAdmissionError("claim_contract_mismatch", "claim does not match the current turn contract")
    consuming = path.with_suffix(".consuming")
    try:
        os.replace(path, consuming)
    except OSError as exc:
        raise ScopeAdmissionError("claim_consume_failed", "cannot atomically consume admission claim") from exc
    return claim, consuming


def _cleanup_consumed_claims(claims_dir: Path, run_name: str, assets: list[str]) -> None:
    """Remove superseded one-use claim transports after a durable commit."""
    if not claims_dir.is_dir():
        return
    for path in claims_dir.glob("*.consuming"):
        try:
            claim = json.loads(path.read_text(encoding="utf-8", errors="strict"))
        except Exception:
            continue
        if claim.get("schema") == CLAIM_SCHEMA and claim.get("run_name") == run_name \
                and claim.get("assets") == assets:
            path.unlink(missing_ok=True)


def _row_host(row: dict) -> str:
    raw = str(row.get("host") or row.get("asset") or row.get("url") or "").strip()
    if not raw:
        return ""
    try:
        host = urlsplit(raw if "://" in raw else "//" + raw).hostname or ""
    except ValueError:
        return ""
    try:
        return normalize_asset(host)
    except ScopeAdmissionError:
        return ""


def _scope_projection(rows: list[dict], assets: list[str]) -> list[dict]:
    selected = set(assets)
    return sorted(({
        "asset": _row_host(row),
        "scope_status": str(row.get("scope_status") or ""),
        "scope_authority": str(row.get("scope_authority") or ""),
        "scope_admission_id": str(row.get("scope_admission_id") or ""),
        "scope_prompt_sha256": str(row.get("scope_prompt_sha256") or ""),
        "source": str(row.get("source") or ""),
    } for row in rows if _row_host(row) in selected), key=lambda item: item["asset"])


def _projection_hash(rows: list[dict], assets: list[str]) -> str:
    return _sha256(_canonical_bytes(_scope_projection(rows, assets)))


def _verified_candidate_assets(run_dir: Path) -> tuple[set[str], str]:
    """Derive file-candidate identity from the frozen setup bundle, not ledger labels."""
    manifest_path = run_dir / "state" / "setup_source.json"
    if not manifest_path.is_file():
        return set(), ""
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8", errors="strict"))
    except Exception:
        return set(), "setup source manifest is unreadable"
    if not isinstance(manifest, dict):
        return set(), "setup source manifest must be a JSON object"
    try:
        import setup_source  # noqa: WPS433
    except Exception:
        return set(), "setup source validator is unavailable"
    schema = str(manifest.get("schema") or "")
    if schema in setup_source.LEGACY_SCHEMAS:
        return set(), ""
    if schema != setup_source.SCHEMA:
        return set(), "setup source schema is unknown"
    try:
        setup_source.verify_bundle(run_dir, manifest)
    except Exception as exc:
        code = str(getattr(exc, "code", type(exc).__name__))
        return set(), f"setup source bundle is invalid: {code}"
    source = manifest.get("source") if isinstance(manifest.get("source"), dict) else {}
    operator = (
        manifest.get("operator_directive")
        if isinstance(manifest.get("operator_directive"), dict) else {}
    )
    if source.get("kind") not in CANDIDATE_SOURCE_KINDS \
            or operator.get("provided_target") is not False:
        return set(), ""
    assets: set[str] = set()
    for row in manifest.get("assets") or []:
        if not isinstance(row, dict):
            return set(), "setup source candidate assets are invalid"
        try:
            assets.add(normalize_asset(str(row.get("host") or "")))
        except ScopeAdmissionError:
            return set(), "setup source candidate host is invalid"
    return assets, ""


def verify_admitted_host(run_dir: Path, rows: list[dict], host: str) -> tuple[bool, str]:
    """Verify operator receipt binding for an admitted setup-source candidate host."""
    try:
        normalized = normalize_asset(host)
    except ScopeAdmissionError:
        return False, "invalid host"
    matched = [row for row in rows if _row_host(row) == normalized]
    if not matched:
        return False, "host is absent from the coverage ledger"
    frozen_candidates, source_error = _verified_candidate_assets(run_dir)
    if source_error:
        return False, source_error
    candidate_rows = [
        row for row in matched
        if str(row.get("source") or "").startswith("setup-source-candidate")
    ]
    if normalized in frozen_candidates:
        candidate_rows = matched
    if not candidate_rows:
        return True, "non-candidate scope source"
    for row in candidate_rows:
        if str(row.get("scope_status") or "") != "in" \
                or str(row.get("scope_authority") or "") != "operator":
            return False, "candidate row lacks operator scope authority"
        admission_id = str(row.get("scope_admission_id") or "")
        prompt_sha = str(row.get("scope_prompt_sha256") or "")
        if not re.fullmatch(r"[0-9a-f]{32}", admission_id) \
                or not re.fullmatch(r"[0-9a-f]{64}", prompt_sha):
            return False, "candidate row has invalid admission identity"
        receipt_path = run_dir / "state" / "scope_admissions" / f"{admission_id}.json"
        try:
            receipt = json.loads(receipt_path.read_text(encoding="utf-8", errors="strict"))
        except Exception:
            return False, "scope admission receipt is missing or unreadable"
        if receipt_errors(receipt):
            return False, "scope admission receipt violates its formal contract"
        assets = receipt.get("assets") if isinstance(receipt, dict) else None
        if not isinstance(assets, list) \
                or receipt.get("status") != "committed" or receipt.get("run_name") != run_dir.name \
                or receipt.get("admission_id") != admission_id \
                or receipt.get("prompt_sha256") != prompt_sha or normalized not in assets:
            return False, "scope admission receipt identity mismatch"
        setup_source_path = run_dir / "state" / "setup_source.json"
        try:
            current_source_sha = _sha256(setup_source_path.read_bytes())
        except OSError:
            return False, "setup source manifest is missing"
        if receipt.get("setup_source_sha256") != current_source_sha:
            return False, "scope admission setup-source hash mismatch"
        if receipt.get("projection_after_sha256") != _projection_hash(rows, assets):
            return False, "scope admission projection hash mismatch"
    return True, "operator receipt verified"


def _active_run(pointer: Path, *, root: Path, runs_root: Path) -> Path:
    try:
        raw = pointer.read_text(encoding="utf-8", errors="strict").strip()
        candidate = Path(raw)
        if not candidate.is_absolute():
            candidate = root / candidate
        resolved = candidate.resolve()
        resolved.relative_to(runs_root.resolve())
    except Exception as exc:
        raise ScopeAdmissionError("active_run_missing", "active-run pointer is missing or invalid") from exc
    return resolved


def _coverage_rows(coverage: dict) -> list[dict]:
    rows = coverage.get("assets") if isinstance(coverage, dict) else None
    if not isinstance(rows, list) or not rows or not all(isinstance(item, dict) for item in rows):
        raise ScopeAdmissionError("invalid_coverage", "candidate coverage asset rows are missing")
    return rows


def _apply_admission_locked(
    run_dir: Path,
    assets: list[str],
    *,
    root: Path = ROOT,
    runs_root: Path = RUNS_ROOT,
    pointer: Path = ACTIVE_POINTER,
    claims_dir: Path = CLAIMS_DIR,
    fault: str = "",
) -> dict:
    run_dir = run_dir.resolve()
    if _active_run(pointer, root=root, runs_root=runs_root) != run_dir:
        raise ScopeAdmissionError("inactive_run", "scope admission may update only the exact active run")
    tx = _load_json(run_dir / "state" / "setup_transaction.json", code="invalid_setup")
    if tx.get("schema") != "xunji.setup_transaction.v1" \
            or tx.get("status") not in {"committed", "recovered"}:
        raise ScopeAdmissionError("invalid_setup", "setup transaction must be committed before scope admission")
    normalized_assets = [normalize_asset(item) for item in assets]
    claim, _consuming_claim = _consume_claim(run_dir, normalized_assets, claims_dir)
    coverage_path = run_dir / "classify" / "coverage.json"
    coverage = _load_json(coverage_path, code="invalid_coverage")
    rows = _coverage_rows(coverage)
    selected_rows = [row for row in rows if _row_host(row) in set(normalized_assets)]
    counts = {asset: sum(1 for row in selected_rows if _row_host(row) == asset)
              for asset in normalized_assets}
    if any(count != 1 for count in counts.values()):
        raise ScopeAdmissionError(
            "asset_mismatch", "every admitted asset must match exactly one canonical coverage row",
        )

    statuses = {str(row.get("scope_status") or "") for row in selected_rows}
    recovery_id = {
        str(row.get("scope_admission_id") or "") for row in selected_rows
        if str(row.get("scope_admission_id") or "")
    }
    if statuses == {"in"} and len(recovery_id) == 1:
        admission_id = next(iter(recovery_id))
        receipt_path = run_dir / "state" / "scope_admissions" / f"{admission_id}.json"
        receipt = _load_json(receipt_path, code="invalid_recovery")
        _require_receipt(receipt, code="invalid_recovery")
        if receipt.get("status") != "prepared" \
                or receipt.get("admission_id") != admission_id \
                or receipt.get("run_name") != run_dir.name \
                or receipt.get("assets") != normalized_assets \
                or receipt.get("projection_after_sha256") != _projection_hash(rows, normalized_assets):
            raise ScopeAdmissionError("invalid_recovery", "prepared admission cannot be recovered safely")
        setup_source_path = run_dir / "state" / "setup_source.json"
        try:
            current_source_sha = _sha256(setup_source_path.read_bytes())
        except OSError as exc:
            raise ScopeAdmissionError(
                "invalid_recovery", "setup source manifest is missing during recovery",
            ) from exc
        if receipt.get("setup_source_sha256") != current_source_sha:
            raise ScopeAdmissionError(
                "invalid_recovery", "setup source changed after admission prepare",
            )
        for row in selected_rows:
            if str(row.get("scope_authority") or "") != "operator" \
                    or str(row.get("scope_admission_id") or "") != admission_id \
                    or str(row.get("scope_prompt_sha256") or "") \
                    != str(receipt.get("prompt_sha256") or ""):
                raise ScopeAdmissionError(
                    "invalid_recovery", "prepared coverage admission identity is invalid",
                )
        sys.path.insert(0, str(root / "tools"))
        import coverage_matrix  # noqa: WPS433
        coverage_matrix.write_outputs(run_dir)
        if fault == "recovery_after_derived":
            raise ScopeAdmissionError("fault_injected", "fault during recovery before receipt commit")
        receipt["status"] = "committed"
        receipt["recovered"] = True
        receipt["recovery_prompt_sha256"] = claim["prompt_sha256"]
        receipt["recovery_reason_sha256"] = claim["reason_sha256"]
        receipt["committed_at"] = time.time()
        _require_receipt(receipt, code="invalid_recovery")
        _atomic_json(receipt_path, receipt)
        _cleanup_consumed_claims(claims_dir, run_dir.name, normalized_assets)
        return receipt

    if statuses != {"review"} or any(
            str(row.get("source") or "") != "setup-source-candidate"
            for row in selected_rows
    ):
        raise ScopeAdmissionError(
            "status_not_review", "only setup-source-candidate rows uniformly in review may be admitted",
        )

    before_raw = coverage_path.read_bytes()
    before_projection = _projection_hash(rows, normalized_assets)
    admission_id = _sha256(_canonical_bytes({
        "claim": claim,
        "coverage_sha256": _sha256(before_raw),
        "projection": before_projection,
    }))[:32]
    admitted_at = time.time()
    for row in selected_rows:
        row.update({
            "scope_status": "in",
            "scope_authority": "operator",
            "scope_admission_id": admission_id,
            "scope_prompt_sha256": claim["prompt_sha256"],
            "scope_admitted_at": admitted_at,
        })
    after_raw = json.dumps(coverage, ensure_ascii=False, indent=2).encode("utf-8") + b"\n"
    receipt_path = run_dir / "state" / "scope_admissions" / f"{admission_id}.json"
    setup_source_path = run_dir / "state" / "setup_source.json"
    try:
        setup_source_sha = _sha256(setup_source_path.read_bytes())
    except OSError as exc:
        raise ScopeAdmissionError(
            "invalid_setup", "setup source manifest is required for candidate admission",
        ) from exc
    receipt = {
        "schema": RECEIPT_SCHEMA,
        "status": "prepared",
        "admission_id": admission_id,
        "run_name": run_dir.name,
        "assets": normalized_assets,
        "session_id": claim["session_id"],
        "prompt_sha256": claim["prompt_sha256"],
        "reason_sha256": claim["reason_sha256"],
        "coverage_path": "classify/coverage.json",
        "coverage_before_sha256": _sha256(before_raw),
        "coverage_after_sha256": _sha256(after_raw),
        "projection_before_sha256": before_projection,
        "projection_after_sha256": _projection_hash(rows, normalized_assets),
        "setup_source_sha256": setup_source_sha,
        "prepared_at": admitted_at,
        "zero_probe": True,
        "recovered": False,
    }
    _require_receipt(receipt, code="invalid_prepare")
    _atomic_json(receipt_path, receipt)
    if fault == "after_prepare":
        raise ScopeAdmissionError("fault_injected", "fault after prepared receipt")
    _atomic_bytes(coverage_path, after_raw)
    if fault == "after_coverage":
        raise ScopeAdmissionError("fault_injected", "fault after coverage publish")
    sys.path.insert(0, str(root / "tools"))
    import coverage_matrix  # noqa: WPS433
    data = coverage_matrix.write_outputs(run_dir)
    if fault == "after_derived":
        raise ScopeAdmissionError("fault_injected", "fault after derived ledger")
    receipt["status"] = "committed"
    receipt["committed_at"] = time.time()
    _require_receipt(receipt, code="invalid_commit")
    _atomic_json(receipt_path, receipt)
    derived_rows = [row for row in data.get("rows", []) if isinstance(row, dict)]
    for asset in normalized_assets:
        ok, note = verify_admitted_host(run_dir, derived_rows, asset)
        if not ok:
            raise ScopeAdmissionError("postcommit_verification_failed", note)
    _cleanup_consumed_claims(claims_dir, run_dir.name, normalized_assets)
    return receipt


def apply_admission(
    run_dir: Path,
    assets: list[str],
    *,
    root: Path = ROOT,
    runs_root: Path = RUNS_ROOT,
    pointer: Path = ACTIVE_POINTER,
    claims_dir: Path = CLAIMS_DIR,
    fault: str = "",
) -> dict:
    """Serialize canonical coverage/receipt writes under a recoverable local lock."""
    if not run_dir.resolve().is_dir():
        raise ScopeAdmissionError("invalid_run", "scope admission run directory does not exist")
    sys.path.insert(0, str(root / "tools"))
    import setup_transaction  # noqa: WPS433
    try:
        with setup_transaction.exclusive_directory_lock(
            pointer.parent / setup_transaction.ACTIVATION_LOCK_NAME,
            timeout=10.0,
            stale_after=30.0,
        ):
            with setup_transaction.exclusive_directory_lock(
                run_dir.resolve() / "state" / ".xunji_scope_admission.lock",
                timeout=10.0,
                stale_after=30.0,
            ):
                return _apply_admission_locked(
                    run_dir, assets, root=root, runs_root=runs_root, pointer=pointer,
                    claims_dir=claims_dir, fault=fault,
                )
    except setup_transaction.SetupTransactionError as exc:
        raise ScopeAdmissionError("lock_timeout", str(exc)) from exc


def _selftest() -> int:
    import shutil
    import setup_normalizer
    import setup_source
    import turn_contract

    root = Path(tempfile.mkdtemp())
    runs = root / "runs"
    run = runs / "pilot_20260715"
    (run / "state").mkdir(parents=True)
    (run / "classify").mkdir()
    pointer = root / ".claude" / "xunji_active_run"
    pointer.parent.mkdir()
    pointer.write_text(str(run), encoding="utf-8")
    (run / "state" / "setup_transaction.json").write_text(json.dumps({
        "schema": "xunji.setup_transaction.v1", "status": "committed",
    }), encoding="utf-8")
    candidate_source = root / "candidate.md"
    candidate_source.write_text(
        "Target: https://one.example.test/\nAsset: https://two.example.test/\n",
        encoding="utf-8",
    )
    source_manifest, source_bytes, _ = setup_normalizer.normalize_path(candidate_source)
    setup_source.write_bundle(run, source_manifest, source_bytes)
    (run / "state" / "setup_source.json").write_bytes(_canonical_bytes(source_manifest))
    coverage = {"assets": [
        {"host": "one.example.test", "scope_status": "review",
         "source": "setup-source-candidate", "reachable": "unknown"},
        {"host": "two.example.test", "scope_status": "review",
         "source": "setup-source-candidate", "reachable": "unknown"},
    ]}
    coverage_path = run / "classify" / "coverage.json"
    coverage_path.write_text(json.dumps(coverage), encoding="utf-8")
    directive = (
        f"{DIRECTIVE} --run runs/{run.name} --assets one.example.test "
        '--reason "operator confirmed program scope"'
    )
    parsed, parse_error = parse_operator_directive(directive, root=root, runs_root=runs)
    natural, natural_error = parse_operator_directive(
        (
            f"把 one.example.test、two.example.test 加入 runs/{run.name} "
            "的 scope，因为这是本次授权目标"
        ),
        root=root,
        runs_root=runs,
    )
    later_directive, _ = parse_operator_directive("source text\n" + directive, root=root, runs_root=runs)
    malformed, malformed_error = parse_operator_directive(
        f"{DIRECTIVE} --run runs/{run.name} --assets '*.example.test' --reason approved",
        root=root, runs_root=runs,
    )
    scoped_ipv6_rejected = False
    try:
        normalize_asset("fe80::1%en0")
    except ScopeAdmissionError:
        scoped_ipv6_rejected = True
    plain_ipv6_accepted = normalize_asset("2001:db8::1") == "2001:db8::1"
    localhost_accepted = normalize_asset("localhost") == "localhost"
    other_single_label_rejected = False
    try:
        normalize_asset("internal")
    except ScopeAdmissionError:
        other_single_label_rejected = True
    invocation = parse_invocation(
        [f"runs/{run.name}", "--assets", "one.example.test"], root=root, runs_root=runs,
    )
    alternate_run_forms_rejected = True
    for alternate in (str(run), f"runs/../runs/{run.name}", f"runs/{run.name}/"):
        try:
            parse_invocation(
                [alternate, "--assets", "one.example.test"], root=root, runs_root=runs,
            )
            alternate_run_forms_rejected = False
        except ScopeAdmissionError:
            pass
    claims = root / "claims"
    contract = turn_contract._contract_from_event({
        "session_id": "session-one",
        "transcript_path": str(root / "scope-session.jsonl"),
        "prompt": directive,
    }, run_name=run.name)
    (run / "state" / "turn_contract.json").write_text(json.dumps(contract), encoding="utf-8")
    no_claim_blocked = False
    try:
        apply_admission(run, ["one.example.test"], root=root, runs_root=runs,
                        pointer=pointer, claims_dir=claims)
    except ScopeAdmissionError as exc:
        no_claim_blocked = exc.code == "claim_missing"
    stale_contract = {**contract, "prompt_sha256": "b" * 64}
    write_hook_claim(run, stale_contract, claims_dir=claims)
    write_hook_claim(run, contract, claims_dir=claims)
    receipt = apply_admission(
        run, ["one.example.test"], root=root, runs_root=runs,
        pointer=pointer, claims_dir=claims,
    )
    promoted = json.loads(coverage_path.read_text(encoding="utf-8"))["assets"]
    sys.path.insert(0, str(root / "tools"))
    import coverage_matrix  # noqa: WPS433
    derived = coverage_matrix.derive(run)
    verified, _note = verify_admitted_host(run, derived["rows"], "one.example.test")
    forged_rows = json.loads(json.dumps(promoted))
    forged_rows[1]["scope_status"] = "in"
    forged_rows[1]["source"] = "target-derived"
    forged_candidate_verified, _ = verify_admitted_host(
        run, forged_rows, "two.example.test",
    )
    setup_source_path = run / "state" / "setup_source.json"
    setup_source_raw = setup_source_path.read_bytes()
    setup_source_path.write_text('{"mutated":true}\n', encoding="utf-8")
    source_mutation_verified, _ = verify_admitted_host(
        run, derived["rows"], "one.example.test",
    )
    setup_source_path.write_bytes(setup_source_raw)
    replay_blocked = False
    try:
        apply_admission(run, ["one.example.test"], root=root, runs_root=runs,
                        pointer=pointer, claims_dir=claims)
    except ScopeAdmissionError as exc:
        replay_blocked = exc.code == "claim_missing"

    # A crash after publishing coverage leaves a prepared receipt and remains
    # non-executable until a new hook-bound operator turn recovers it.
    crash_run = runs / "crash_20260715"
    shutil.copytree(run, crash_run)
    crash_rows = json.loads((crash_run / "classify" / "coverage.json").read_text())
    for row in crash_rows["assets"]:
        if row["host"] == "two.example.test":
            row["scope_status"] = "review"
            for key in list(row):
                if key.startswith("scope_") and key != "scope_status":
                    row.pop(key)
    (crash_run / "classify" / "coverage.json").write_text(json.dumps(crash_rows), encoding="utf-8")
    pointer.write_text(str(crash_run), encoding="utf-8")
    crash_directive = (
        f"{DIRECTIVE} --run runs/{crash_run.name} --assets two.example.test "
        '--reason "operator confirmed second asset"'
    )
    crash_contract = turn_contract._contract_from_event({
        "session_id": "session-one",
        "transcript_path": str(root / "scope-session.jsonl"),
        "prompt": crash_directive,
    }, run_name=crash_run.name)
    (crash_run / "state" / "turn_contract.json").write_text(json.dumps(crash_contract), encoding="utf-8")
    write_hook_claim(crash_run, crash_contract, claims_dir=claims)
    fault_blocked = False
    try:
        apply_admission(
            crash_run, ["two.example.test"], root=root, runs_root=runs,
            pointer=pointer, claims_dir=claims, fault="after_coverage",
        )
    except ScopeAdmissionError as exc:
        fault_blocked = exc.code == "fault_injected"
    crash_derived = coverage_matrix.derive(crash_run)
    crash_verified, _ = verify_admitted_host(
        crash_run, crash_derived["rows"], "two.example.test",
    )
    recovery_directive = (
        f"{DIRECTIVE} --run runs/{crash_run.name} --assets two.example.test "
        '--reason "operator retries interrupted admission"'
    )
    recovery_contract = turn_contract._contract_from_event({
        "session_id": "session-one",
        "transcript_path": str(root / "scope-session.jsonl"),
        "prompt": recovery_directive,
    }, run_name=crash_run.name)
    (crash_run / "state" / "turn_contract.json").write_text(
        json.dumps(recovery_contract), encoding="utf-8",
    )
    write_hook_claim(crash_run, recovery_contract, claims_dir=claims)
    recovery_fault_blocked = False
    try:
        apply_admission(
            crash_run, ["two.example.test"], root=root, runs_root=runs,
            pointer=pointer, claims_dir=claims, fault="recovery_after_derived",
        )
    except ScopeAdmissionError as exc:
        recovery_fault_blocked = exc.code == "fault_injected"
    write_hook_claim(crash_run, recovery_contract, claims_dir=claims)
    recovered_receipt = apply_admission(
        crash_run, ["two.example.test"], root=root, runs_root=runs,
        pointer=pointer, claims_dir=claims,
    )
    recovered_rows = coverage_matrix.derive(crash_run)["rows"]
    recovered_verified, _ = verify_admitted_host(
        crash_run, recovered_rows, "two.example.test",
    )
    unknown_receipt = json.loads(json.dumps(receipt))
    unknown_receipt["untrusted_extra"] = True
    missing_receipt = json.loads(json.dumps(receipt))
    missing_receipt.pop("coverage_before_sha256")
    partial_recovery_receipt = json.loads(json.dumps(recovered_receipt))
    partial_recovery_receipt.pop("recovery_reason_sha256")
    prepared_with_commit = json.loads(json.dumps(receipt))
    prepared_with_commit["status"] = "prepared"
    import setup_transaction  # noqa: WPS433
    activation_lock_serializes = False
    activation_lock = pointer.parent / setup_transaction.ACTIVATION_LOCK_NAME
    with setup_transaction.exclusive_directory_lock(activation_lock):
        try:
            with setup_transaction.exclusive_directory_lock(
                activation_lock, timeout=0.05, stale_after=3600.0,
            ):
                pass
        except setup_transaction.SetupTransactionError:
            activation_lock_serializes = True
    missing_run = runs / "missing_20260715"
    pointer.write_text(str(missing_run), encoding="utf-8")
    missing_run_side_effect_free = False
    try:
        apply_admission(
            missing_run, ["one.example.test"], root=root, runs_root=runs,
            pointer=pointer, claims_dir=claims,
        )
    except ScopeAdmissionError as exc:
        missing_run_side_effect_free = exc.code == "invalid_run" and not missing_run.exists()

    checks = [
        ("exact first-line directive parses", bool(parsed) and not parse_error),
        ("natural-language admission compiles to the same typed run/assets",
         bool(natural) and not natural_error
         and natural.get("run_name") == run.name
         and natural.get("assets")
         == ["one.example.test", "two.example.test"]
         and natural.get("intent_format") == "natural-language"),
        ("directive in later source text has no authority", later_directive is None),
        ("wildcard scope is rejected", malformed is None and bool(malformed_error)),
        ("plain IPv6 is accepted but interface-scoped IPv6 is rejected",
         plain_ipv6_accepted and scoped_ipv6_rejected),
        ("exact localhost is accepted without allowing other single-label names",
         localhost_accepted and other_single_label_rejected),
        ("tool invocation normalizes the exact run/assets", invocation["run_name"] == run.name),
        ("absolute, traversing, and trailing-slash run forms are rejected",
         alternate_run_forms_rejected),
        ("direct invocation without hook claim fails closed", no_claim_blocked),
        ("hook claim promotes only selected review row", receipt["status"] == "committed"
         and promoted[0]["scope_status"] == "in" and promoted[1]["scope_status"] == "review"),
        ("a stale prior-turn claim does not block the current exact contract",
         receipt["prompt_sha256"] == contract["prompt_sha256"]),
        ("committed admission receipt verifies", verified),
        ("frozen setup bundle defeats direct source/status ledger forgery",
         not forged_candidate_verified),
        ("setup-source mutation invalidates committed admission",
         not source_mutation_verified),
        ("consumed claim cannot replay", replay_blocked),
        ("post-coverage crash is injected", fault_blocked),
        ("prepared receipt never authorizes target execution", not crash_verified),
        ("new exact operator claim recovers interrupted admission",
         recovery_fault_blocked and recovered_receipt.get("recovered") is True
         and recovered_verified),
        ("scope receipt contract rejects unknown, missing, and half-version fields",
         not receipt_errors(receipt)
         and not receipt_errors(recovered_receipt)
         and bool(receipt_errors(unknown_receipt))
         and bool(receipt_errors(missing_receipt))
         and bool(receipt_errors(partial_recovery_receipt))
         and bool(receipt_errors(prepared_with_commit))),
        ("scope commit shares the pointer-owner activation lock",
         activation_lock_serializes),
        ("missing active-run path fails before creating state or locks",
         missing_run_side_effect_free),
    ]
    bad = [name for name, ok in checks if not ok]
    for name, ok in checks:
        print(("ok   " if ok else "FAIL ") + name)
    print("scope_admission selftest " + ("passed" if not bad else f"FAILED ({len(bad)})"))
    return 0 if not bad else 1


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if args == ["--selftest"]:
        return _selftest()
    try:
        parsed = parse_invocation(args)
        receipt = apply_admission(Path(parsed["run_dir"]), parsed["assets"])
    except ScopeAdmissionError as exc:
        print(json.dumps({"ok": False, "code": exc.code, "error": str(exc)}, ensure_ascii=False),
              file=sys.stderr)
        return 2
    print(json.dumps({
        "ok": True, "run": receipt["run_name"], "assets": receipt["assets"],
        "admission_id": receipt["admission_id"], "zero_probe": True,
    }, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
