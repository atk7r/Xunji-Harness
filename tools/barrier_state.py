#!/usr/bin/env python3
"""Derived, append-only infrastructure failure barrier.

Two consecutive distinct zero-target-byte infrastructure failure receipts for the same
``front + action fingerprint`` open a narrow
scheduling barrier.  The barrier rejects a third identical target-shaped
attempt while continuing to allow repair and local verification.  A typed clear
resets the complete action-level failure epoch. Cause and precondition remain
receipt diagnostics, but rotating them cannot evade the threshold. The tool never
writes canonical Markdown, counts a target failure, closes a front, or grants
evidence/review/report/closure authority.
"""
from __future__ import annotations

import argparse
import contextlib
import hashlib
import json
import os
import re
import stat
import sys
import tempfile
import threading
import time
from pathlib import Path
from unittest import mock

try:
    import fcntl
except ImportError:  # pragma: no cover - Unix is the supported live runtime
    fcntl = None


ROOT = Path(__file__).resolve().parents[1]
RUNS_ROOT = ROOT / "runs"
sys.path.insert(0, str(ROOT / "tools"))

import contract_schema  # noqa: E402


SCHEMA = "xunji.infra-barrier.v1"
SCHEMA_FILE = "infra-barrier.v1.schema.json"
JOURNAL = "infra_barriers.jsonl"
LOCK = ".infra_barriers.lock"
WRITER = "tools/barrier_state.py"
AUTHORITY = (
    "derived scheduling barrier only; no target, front, evidence, review, "
    "report, or closure authority"
)
MAX_JOURNAL_BYTES = 8 * 1024 * 1024
MAX_EVENTS = 16384
OPEN_THRESHOLD = 2
_HEX64 = re.compile(r"[0-9a-f]{64}\Z")
_FRONT = re.compile(r"F-[0-9]+\Z")
_CAUSE_CODE = re.compile(r"[A-Z][A-Z0-9_.-]{0,127}\Z")
_FAILURE_DOMAINS = {
    "proxy", "network_transport", "runtime", "scheduler", "tooling",
}
_CLEAR_REASONS = {
    "repair_succeeded", "target_response_observed", "failure_reclassified",
    "precondition_superseded",
}
_CLI_CLEAR_REASONS = {"repair_succeeded", "target_response_observed"}
_OPERATION_CLASSES = {"target_attempt", "repair", "local_verify"}
_INELIGIBLE_RUNTIME_FAILURE_CODES = {
    "INFRA_BARRIER_RUNTIME_FAILURE_INELIGIBLE",
    "INFRA_BARRIER_RUNTIME_FAILURE_UNTYPED",
    "INFRA_BARRIER_RUNTIME_FAILURE_UNCLASSIFIED",
    "INFRA_BARRIER_RUNTIME_FAILURE_UNBOUND_LANE",
}
_ELIGIBLE_DENIAL_CLASSES = {
    "work_plan", "iteration_plan", "delegation", "command_shape",
}


class BarrierStateError(ValueError):
    """Stable fail-closed barrier diagnosis."""

    def __init__(self, code: str, detail: str = ""):
        self.code = code
        self.detail = detail
        super().__init__(f"{code}: {detail}" if detail else code)


class BarrierDurabilityError(OSError):
    """A journal append failed its durability barrier and was rolled back."""


def _fail(code: str, detail: str) -> None:
    raise BarrierStateError(code, detail)


def _within(path: Path, parent: Path) -> bool:
    try:
        path.relative_to(parent)
        return True
    except ValueError:
        return False


def _reject_symlink_components(path: Path, anchor: Path) -> None:
    anchor_abs = Path(os.path.abspath(anchor))
    path_abs = Path(os.path.abspath(path))
    try:
        relative = path_abs.relative_to(anchor_abs)
    except ValueError:
        _fail("INFRA_BARRIER_RUN_OUTSIDE_ROOT", "run path is outside runs root")
    current = anchor_abs
    if current.is_symlink():
        _fail("INFRA_BARRIER_SYMLINK", "runs root must not be a symlink")
    for part in relative.parts:
        current = current / part
        if current.is_symlink():
            _fail("INFRA_BARRIER_SYMLINK", "run path must not contain symlinks")


def _resolve_run_dir(
    run_dir: str | Path,
    *,
    runs_root: str | Path = RUNS_ROOT,
) -> Path:
    root = Path(runs_root)
    raw = Path(run_dir)
    if not raw.is_absolute():
        raw = ROOT / raw
    _reject_symlink_components(raw, root)
    try:
        root_resolved = root.resolve(strict=True)
        run_resolved = raw.resolve(strict=True)
    except OSError as exc:
        _fail("INFRA_BARRIER_RUN_UNAVAILABLE", type(exc).__name__)
    if not root_resolved.is_dir() or not run_resolved.is_dir() \
            or not _within(run_resolved, root_resolved):
        _fail("INFRA_BARRIER_RUN_INVALID", "run must be a directory below runs root")
    return run_resolved


def _run_identity(run_dir: Path, runs_root: str | Path) -> str:
    root = Path(runs_root).resolve(strict=True)
    return run_dir.relative_to(root).as_posix()


def _journal_path(run_dir: Path) -> Path:
    state_dir = run_dir / "state"
    if state_dir.is_symlink() \
            or (state_dir.exists() and not state_dir.is_dir()):
        _fail("INFRA_BARRIER_STATE_INVALID", "state must be a regular directory")
    path = state_dir / JOURNAL
    if path.is_symlink():
        _fail("INFRA_BARRIER_JOURNAL_INVALID", "journal must not be a symlink")
    return path


def _canonical_json(value: object) -> bytes:
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
    ).encode("utf-8")


def _record_hash(record: dict) -> str:
    body = dict(record)
    body.pop("event_hash", None)
    return hashlib.sha256(_canonical_json(body)).hexdigest()


def _key_token(key: dict) -> tuple[str, str, str, str]:
    return (
        str(key.get("front") or ""),
        str(key.get("action_fingerprint") or ""),
        str(key.get("cause_code") or ""),
        str(key.get("precondition_digest") or ""),
    )


def _action_token(key: dict) -> tuple[str, str]:
    return (
        str(key.get("front") or ""),
        str(key.get("action_fingerprint") or ""),
    )


def _matching_action_states(
    states: dict[tuple[str, str, str, str], dict], key: dict,
) -> list[dict]:
    token = _action_token(key)
    return [
        item for item in states.values()
        if _action_token(item.get("barrier_key") or {}) == token
    ]


def barrier_key(
    *,
    front: str,
    action_fingerprint: str,
    cause_code: str,
    precondition_digest: str,
) -> dict:
    key = {
        "front": str(front or ""),
        "action_fingerprint": str(action_fingerprint or ""),
        "cause_code": str(cause_code or ""),
        "precondition_digest": str(precondition_digest or ""),
    }
    if not _FRONT.fullmatch(key["front"]):
        _fail("INFRA_BARRIER_KEY_INVALID", "front must match F-<digits>")
    if not _HEX64.fullmatch(key["action_fingerprint"]):
        _fail("INFRA_BARRIER_KEY_INVALID", "action_fingerprint must be lowercase sha256")
    if not _CAUSE_CODE.fullmatch(key["cause_code"]):
        _fail("INFRA_BARRIER_KEY_INVALID", "cause_code must be a bounded uppercase code")
    if not _HEX64.fullmatch(key["precondition_digest"]):
        _fail("INFRA_BARRIER_KEY_INVALID", "precondition_digest must be lowercase sha256")
    return key


def _runtime_events(run_dir: Path) -> list[dict]:
    """Load one validated runtime chain for provenance-bound barrier actions."""
    try:
        import runtime_receipts
    except ImportError as exc:
        _fail("INFRA_BARRIER_RUNTIME_UNAVAILABLE", "runtime receipt owner is unavailable")
        raise AssertionError from exc
    events, errors = runtime_receipts.validate_chain(run_dir)
    if errors:
        _fail(
            "INFRA_BARRIER_RUNTIME_INVALID",
            "runtime receipt chain is not valid: " + str(errors[0]),
        )
    return events


def _runtime_event_by_hash(
    run_dir: Path,
    receipt_sha256: str,
    *,
    events: list[dict] | None = None,
) -> dict:
    if not _HEX64.fullmatch(str(receipt_sha256 or "")):
        _fail("INFRA_BARRIER_RECEIPT_INVALID", "runtime receipt must be lowercase sha256")
    matches = [
        event for event in (events if events is not None else _runtime_events(run_dir))
        if str(event.get("receipt_hash") or "") == receipt_sha256
    ]
    if len(matches) != 1:
        _fail(
            "INFRA_BARRIER_RUNTIME_RECEIPT_UNBOUND",
            "receipt hash must identify exactly one validated runtime event",
        )
    return matches[0]


def runtime_action_fingerprint(event: dict) -> str:
    try:
        import runtime_receipts
    except ImportError as exc:
        _fail("INFRA_BARRIER_RUNTIME_UNAVAILABLE", "runtime receipt owner is unavailable")
        raise AssertionError from exc
    semantic = runtime_receipts._target_semantic_action(event)
    if semantic is not None:
        basis = {
            "schema": "xunji.infra-action-fingerprint.v1",
            "kind": "target-semantic",
            "value": list(semantic),
        }
    else:
        action_sha256 = str(event.get("action_sha256") or "")
        if not _HEX64.fullmatch(action_sha256):
            _fail(
                "INFRA_BARRIER_RUNTIME_ACTION_INVALID",
                "runtime event has no exact action digest",
            )
        basis = {
            "schema": "xunji.infra-action-fingerprint.v1",
            "kind": "runtime-action",
            "tool_name": str(event.get("tool_name") or ""),
            "action_sha256": action_sha256,
        }
    return hashlib.sha256(_canonical_json(basis)).hexdigest()


# Compatibility for existing internal callers/tests.  New integrations should
# use the public spelling so the same fingerprint owner is shared by plan and
# Hook preflight.
_runtime_action_fingerprint = runtime_action_fingerprint


def _runtime_precondition_digest(event: dict) -> str:
    basis = {
        "schema": "xunji.infra-precondition.v1",
        "decision_code": str(event.get("decision_code") or ""),
        "decision_class": str(event.get("decision_class") or ""),
        "shape_category": str(event.get("shape_category") or ""),
        "control_script": str(event.get("control_script") or ""),
        "capability_id": str(event.get("capability_id") or ""),
        "capability_effect": str(event.get("capability_effect") or ""),
    }
    return hashlib.sha256(_canonical_json(basis)).hexdigest()


def _runtime_plan_lane(
    run_dir: Path,
    event: dict,
    events: list[dict],
) -> tuple[dict, dict, dict]:
    """Bind one runtime receipt to its immutable claim and committed lane."""
    try:
        import runtime_receipts
        import work_plan
    except ImportError as exc:
        _fail(
            "INFRA_BARRIER_RUNTIME_UNAVAILABLE",
            "runtime/work-plan owner is unavailable",
        )
        raise AssertionError from exc
    try:
        claim = runtime_receipts.plan_bound_child_claim(
            run_dir, event, events=events)
    except RuntimeError as exc:
        _fail("INFRA_BARRIER_RUNTIME_BINDING_INVALID", str(exc))
    if not claim:
        _fail(
            "INFRA_BARRIER_RUNTIME_FAILURE_UNBOUND_LANE",
            "runtime event has no plan-bound child tool-call claim",
        )
    try:
        plan = work_plan.transaction_bound_plan(run_dir)
    except Exception as exc:
        _fail("INFRA_BARRIER_RUNTIME_PLAN_INVALID", type(exc).__name__)
    plan_digest = str(claim.get("assignment_plan_digest") or "")
    lane_id = str(claim.get("assignment_lane") or "")
    if plan_digest != str(plan.get("plan_digest") or ""):
        _fail(
            "INFRA_BARRIER_RUNTIME_PLAN_MISMATCH",
            "child claim does not bind the current committed plan",
        )
    lanes = [
        lane for lane in plan.get("lanes", [])
        if isinstance(lane, dict) and str(lane.get("id") or "") == lane_id
    ]
    if len(lanes) != 1:
        _fail(
            "INFRA_BARRIER_RUNTIME_LANE_MISMATCH",
            "child claim does not bind exactly one committed lane",
        )
    lane = lanes[0]
    if str(lane.get("front") or "") != str(claim.get("front") or ""):
        _fail(
            "INFRA_BARRIER_RUNTIME_LANE_MISMATCH",
            "claim front differs from the committed lane",
        )
    return claim, plan, lane


def runtime_failure_candidate(
    run_dir: str | Path,
    *,
    failure_receipt_sha256: str,
    runs_root: str | Path = RUNS_ROOT,
) -> dict:
    """Derive one zero-byte infrastructure failure from a trusted denial.

    Only a validated target-facing PreToolUse denial is admitted: the denied
    action never executed, so target bytes are mechanically zero.  Generic
    PostToolUse failures are intentionally excluded because they do not prove
    whether the target returned bytes.
    """
    run = _resolve_run_dir(run_dir, runs_root=runs_root)
    events = _runtime_events(run)
    event = _runtime_event_by_hash(
        run, failure_receipt_sha256, events=events)
    cause_code = str(event.get("decision_code") or "")
    front = str(event.get("front") or "")
    if event.get("hook_event_name") != "PreToolUseDenied" \
            or event.get("success") is not False \
            or event.get("decision") != "deny" \
            or event.get("target_action") is not True:
        _fail(
            "INFRA_BARRIER_RUNTIME_FAILURE_INELIGIBLE",
            "only a target PreToolUse denial proves zero target bytes",
        )
    if not _FRONT.fullmatch(front) or not _CAUSE_CODE.fullmatch(cause_code):
        _fail(
            "INFRA_BARRIER_RUNTIME_FAILURE_UNTYPED",
            "runtime denial must bind one front and stable decision code",
        )
    decision_class = str(event.get("decision_class") or "")
    if decision_class not in _ELIGIBLE_DENIAL_CLASSES:
        _fail(
            "INFRA_BARRIER_RUNTIME_FAILURE_UNCLASSIFIED",
            "runtime denial is not a recognized infrastructure class",
        )
    claim, _plan, lane = _runtime_plan_lane(run, event, events)
    if str(lane.get("effect") or "") != "target" \
            or str(claim.get("front") or "") != front:
        _fail(
            "INFRA_BARRIER_RUNTIME_FAILURE_UNBOUND_LANE",
            "runtime denial is not owned by the exact target lane/front",
        )
    if decision_class in {
        "work_plan", "iteration_plan", "delegation",
    }:
        failure_domain = "scheduler"
    elif decision_class == "command_shape":
        failure_domain = "tooling"
    else:  # closed set above
        raise AssertionError("unreachable infrastructure denial class")
    action_fingerprint = runtime_action_fingerprint(event)
    lane_binding = lane.get("infra_barrier") \
        if isinstance(lane.get("infra_barrier"), dict) else {}
    if lane_binding and (
            lane_binding.get("operation_class") != "target_attempt"
            or lane_binding.get("action_fingerprint") != action_fingerprint):
        _fail(
            "INFRA_BARRIER_RUNTIME_LANE_MISMATCH",
            "target lane barrier binding differs from the actual runtime action",
        )
    key = barrier_key(
        front=front,
        action_fingerprint=action_fingerprint,
        cause_code=cause_code,
        precondition_digest=_runtime_precondition_digest(event),
    )
    return {
        "schema": "xunji.infra-failure-candidate.v1",
        "barrier_key": key,
        "failure_receipt_sha256": failure_receipt_sha256,
        "failure_domain": failure_domain,
        "target_bytes": 0,
        "runtime_event_seq": int(event.get("seq") or 0),
        "authority": AUTHORITY,
    }


def record_runtime_failure(
    run_dir: str | Path,
    *,
    failure_receipt_sha256: str,
    runs_root: str | Path = RUNS_ROOT,
) -> dict:
    candidate = runtime_failure_candidate(
        run_dir, failure_receipt_sha256=failure_receipt_sha256,
        runs_root=runs_root,
    )
    key = candidate["barrier_key"]
    return record_failure(
        run_dir,
        front=key["front"],
        action_fingerprint=key["action_fingerprint"],
        cause_code=key["cause_code"],
        precondition_digest=key["precondition_digest"],
        failure_receipt_sha256=failure_receipt_sha256,
        failure_domain=candidate["failure_domain"],
        target_bytes=0,
        runs_root=runs_root,
    )


def observe_runtime_failure_if_eligible(
    run_dir: str | Path,
    *,
    failure_receipt_sha256: str,
    runs_root: str | Path = RUNS_ROOT,
) -> dict:
    """Hook adapter: ignore non-infra denials, fail on eligible write debt."""
    try:
        candidate = runtime_failure_candidate(
            run_dir,
            failure_receipt_sha256=failure_receipt_sha256,
            runs_root=runs_root,
        )
    except BarrierStateError as exc:
        if exc.code in _INELIGIBLE_RUNTIME_FAILURE_CODES:
            return {
                "status": "ignored",
                "code": exc.code,
                "authority": AUTHORITY,
            }
        raise
    key = candidate["barrier_key"]
    return record_failure(
        run_dir,
        front=key["front"],
        action_fingerprint=key["action_fingerprint"],
        cause_code=key["cause_code"],
        precondition_digest=key["precondition_digest"],
        failure_receipt_sha256=failure_receipt_sha256,
        failure_domain=candidate["failure_domain"],
        target_bytes=0,
        runs_root=runs_root,
    )


def _lane_barrier_key(lane: dict) -> dict:
    binding = lane.get("infra_barrier") \
        if isinstance(lane.get("infra_barrier"), dict) else {}
    if not binding:
        return {}
    return barrier_key(
        front=str(lane.get("front") or ""),
        action_fingerprint=str(binding.get("action_fingerprint") or ""),
        cause_code=str(binding.get("cause_code") or ""),
        precondition_digest=str(binding.get("precondition_digest") or ""),
    )


def _require_runtime_basis_after_active_epoch(
    run_dir: Path,
    *,
    runtime_events: list[dict],
    basis_sha256: str,
    key: dict,
    runs_root: str | Path,
) -> None:
    """Bind a successful runtime receipt to failures that precede it.

    Barrier rows carry runtime receipt hashes, so runtime-chain position is the
    causal clock.  Wall-clock timestamps are deliberately not used.
    """
    positions: dict[str, int] = {}
    for index, item in enumerate(runtime_events):
        receipt_hash = str(item.get("receipt_hash") or "")
        if receipt_hash in positions:
            _fail(
                "INFRA_BARRIER_RUNTIME_INVALID",
                "runtime receipt hash is not unique",
            )
        positions[receipt_hash] = index
    basis_position = positions.get(basis_sha256)
    if basis_position is None:
        _fail(
            "INFRA_BARRIER_RUNTIME_RECEIPT_UNBOUND",
            "successful basis is absent from the validated runtime chain",
        )
    active_failures: list[str] = []
    barrier_events = _read_events(_journal_path(run_dir))
    _validate_and_project(
        barrier_events,
        run_identity=_run_identity(run_dir, runs_root),
    )
    for record in barrier_events:
        if _key_token(record.get("barrier_key") or {}) != _key_token(key):
            continue
        if record.get("event") == "observed":
            active_failures.append(
                str((record.get("data") or {}).get(
                    "failure_receipt_sha256") or ""))
        elif record.get("event") == "cleared":
            active_failures = []
    if not active_failures:
        _fail(
            "INFRA_BARRIER_CLEAR_BASIS_MISMATCH",
            "matching barrier state has no active failure receipts",
        )
    failure_positions = [positions.get(item) for item in active_failures]
    if any(item is None for item in failure_positions):
        _fail(
            "INFRA_BARRIER_RUNTIME_RECEIPT_UNBOUND",
            "active barrier failure is absent from the validated runtime chain",
        )
    if max(int(item) for item in failure_positions) >= basis_position:
        _fail(
            "INFRA_BARRIER_CLEAR_BASIS_STALE",
            "successful basis does not follow the active failure epoch",
        )


def runtime_success_clear_candidate(
    run_dir: str | Path,
    *,
    basis_sha256: str,
    runs_root: str | Path = RUNS_ROOT,
) -> dict:
    """Derive an exact clear from one claim-bound successful child receipt.

    ``local_verify`` is intentionally not a repair signal.  A non-target
    success clears only when its own committed lane carries the exact barrier
    key with ``operation_class=repair``.  A target response clears only a
    unique partial/open epoch for the same front and actual semantic action.
    """
    run = _resolve_run_dir(run_dir, runs_root=runs_root)
    runtime_events = _runtime_events(run)
    event = _runtime_event_by_hash(
        run, basis_sha256, events=runtime_events)
    if event.get("hook_event_name") != "PostToolUse" \
            or event.get("success") is not True:
        return {
            "eligible": False,
            "note": "basis is not a successful PostToolUse receipt",
            "authority": AUTHORITY,
        }
    try:
        _claim, _plan, lane = _runtime_plan_lane(run, event, runtime_events)
    except BarrierStateError as exc:
        if exc.code == "INFRA_BARRIER_RUNTIME_FAILURE_UNBOUND_LANE":
            return {
                "eligible": False,
                "note": "success is not owned by a plan-bound child lane",
                "authority": AUTHORITY,
            }
        raise
    front = str(lane.get("front") or "")
    binding = lane.get("infra_barrier") \
        if isinstance(lane.get("infra_barrier"), dict) else {}
    projection = status_projection(run_dir, runs_root=runs_root)
    active_states = [
        item for item in projection.get("states", [])
        if isinstance(item, dict) and int(item.get("failure_count") or 0) > 0
    ]

    if event.get("target_action") is True:
        if str(lane.get("effect") or "") != "target" \
                or str(event.get("capability_effect") or "") != "target":
            _fail(
                "INFRA_BARRIER_CLEAR_BASIS_MISMATCH",
                "target response is not owned by the exact target lane/effect",
            )
        actual = runtime_action_fingerprint(event)
        if binding and (
                binding.get("operation_class") != "target_attempt"
                or binding.get("action_fingerprint") != actual):
            _fail(
                "INFRA_BARRIER_CLEAR_BASIS_MISMATCH",
                "target lane binding differs from the actual target action",
            )
        matches = [
            item for item in active_states
            if str((item.get("barrier_key") or {}).get("front") or "") == front
            and str((item.get("barrier_key") or {}).get(
                "action_fingerprint") or "") == actual
        ]
        if binding:
            exact = _lane_barrier_key(lane)
            matches = [
                item for item in matches
                if _key_token(item.get("barrier_key") or {}) == _key_token(exact)
            ]
        if not matches:
            return {
                "eligible": False,
                "note": "target response has no matching partial/open epoch",
                "authority": AUTHORITY,
            }
        if len(matches) != 1:
            _fail(
                "INFRA_BARRIER_CLEAR_BASIS_AMBIGUOUS",
                "target response matches multiple failure epochs",
            )
        _require_runtime_basis_after_active_epoch(
            run,
            runtime_events=runtime_events,
            basis_sha256=basis_sha256,
            key=matches[0]["barrier_key"],
            runs_root=runs_root,
        )
        return {
            "eligible": True,
            "reason": "target_response_observed",
            "barrier_key": dict(matches[0]["barrier_key"]),
            "basis_sha256": basis_sha256,
            "lane_id": str(lane.get("id") or ""),
            "plan_digest": str(_plan.get("plan_digest") or ""),
            "epoch_last_event_hash": str(matches[0].get(
                "last_event_hash") or ""),
            "authority": AUTHORITY,
        }

    if not binding or binding.get("operation_class") != "repair":
        return {
            "eligible": False,
            "note": "non-target success is not a typed repair lane",
            "authority": AUTHORITY,
        }
    if str(lane.get("effect") or "") not in {
            "control", "local_verify", "repo_mutation"} \
            or str(event.get("capability_effect") or "") not in {
                "control", "local_verify", "repo_mutation"}:
        _fail(
            "INFRA_BARRIER_CLEAR_BASIS_MISMATCH",
            "repair receipt effect differs from its committed repair lane",
        )
    exact = _lane_barrier_key(lane)
    matches = [
        item for item in active_states
        if _key_token(item.get("barrier_key") or {}) == _key_token(exact)
    ]
    if not matches:
        return {
            "eligible": False,
            "note": "repair lane has no exact partial/open epoch",
            "authority": AUTHORITY,
        }
    if len(matches) != 1:
        _fail(
            "INFRA_BARRIER_CLEAR_BASIS_AMBIGUOUS",
            "repair lane matches multiple failure epochs",
        )
    _require_runtime_basis_after_active_epoch(
        run,
        runtime_events=runtime_events,
        basis_sha256=basis_sha256,
        key=matches[0]["barrier_key"],
        runs_root=runs_root,
    )
    return {
        "eligible": True,
        "reason": "repair_succeeded",
        "barrier_key": exact,
        "basis_sha256": basis_sha256,
        "lane_id": str(lane.get("id") or ""),
        "plan_digest": str(_plan.get("plan_digest") or ""),
        "epoch_last_event_hash": str(matches[0].get(
            "last_event_hash") or ""),
        "authority": AUTHORITY,
    }


def record_runtime_success_clear(
    run_dir: str | Path,
    *,
    basis_sha256: str,
    runs_root: str | Path = RUNS_ROOT,
    candidate: dict | None = None,
) -> dict:
    """Hook adapter: clear an exact candidate, idempotent across hook replay."""
    derived = candidate or runtime_success_clear_candidate(
        run_dir, basis_sha256=basis_sha256, runs_root=runs_root)
    if derived.get("eligible") is not True:
        return {
            "status": "ignored",
            "note": str(derived.get("note") or "not a typed clear"),
            "authority": AUTHORITY,
        }
    key = derived["barrier_key"]
    # An old successful hook replay must never clear a newer failure epoch.
    # If this basis already owns a clear event, the automatic adapter is a
    # no-op even when later observations exist.
    prior = [
        item for item in load_events(run_dir, runs_root=runs_root)
        if item.get("event") == "cleared"
        and str((item.get("data") or {}).get("basis_sha256") or "")
        == basis_sha256
    ]
    if prior:
        if len(prior) != 1 \
                or _key_token(prior[0].get("barrier_key") or {}) \
                != _key_token(key) \
                or str((prior[0].get("data") or {}).get("reason") or "") \
                != str(derived.get("reason") or ""):
            _fail(
                "INFRA_BARRIER_CLEAR_CONFLICT",
                "runtime basis is already bound to a different clear",
            )
        return {"status": "unchanged", "cleared": prior[0]}
    return clear_barrier(
        run_dir,
        front=key["front"],
        action_fingerprint=key["action_fingerprint"],
        cause_code=key["cause_code"],
        precondition_digest=key["precondition_digest"],
        reason=str(derived["reason"]),
        basis_sha256=basis_sha256,
        expected_last_event_hash=str(
            derived.get("epoch_last_event_hash") or ""),
        runs_root=runs_root,
    )


def clear_runtime_barrier(
    run_dir: str | Path,
    *,
    front: str,
    action_fingerprint: str,
    cause_code: str,
    precondition_digest: str,
    reason: str,
    basis_sha256: str,
    runs_root: str | Path = RUNS_ROOT,
) -> dict:
    """Clear only when the successful receipt derives this exact typed key."""
    candidate = runtime_success_clear_candidate(
        run_dir, basis_sha256=basis_sha256, runs_root=runs_root)
    if candidate.get("eligible") is not True:
        _fail(
            "INFRA_BARRIER_CLEAR_BASIS_INELIGIBLE",
            str(candidate.get("note") or "successful receipt is not a typed clear"),
        )
    expected_key = barrier_key(
        front=front,
        action_fingerprint=action_fingerprint,
        cause_code=cause_code,
        precondition_digest=precondition_digest,
    )
    if candidate.get("reason") != reason \
            or _key_token(candidate.get("barrier_key") or {}) \
            != _key_token(expected_key):
        _fail(
            "INFRA_BARRIER_CLEAR_BASIS_MISMATCH",
            "successful receipt does not derive the requested lane/key/reason",
        )
    return record_runtime_success_clear(
        run_dir, basis_sha256=basis_sha256, runs_root=runs_root,
        candidate=candidate,
    )


def _new_state(key: dict) -> dict:
    return {
        "barrier_key": dict(key),
        "failure_count": 0,
        "open": False,
        "open_event_hash": "",
        "last_event_hash": "",
    }


def _validate_and_project(events: list[dict], *, run_identity: str) -> dict:
    states: dict[tuple[str, str, str, str], dict] = {}
    failure_receipts: dict[str, dict] = {}
    clearance_receipts: dict[str, dict] = {}
    previous_hash = ""
    pending_open: tuple[tuple[str, str, str, str], str] | None = None

    for index, record in enumerate(events, start=1):
        errors = contract_schema.named_schema_errors(record, SCHEMA_FILE)
        if errors:
            _fail(
                "INFRA_BARRIER_EVENT_INVALID",
                f"event {index}: {errors[0]}",
            )
        if record.get("seq") != index:
            _fail("INFRA_BARRIER_SEQUENCE_INVALID", f"event {index} has wrong seq")
        if record.get("run_dir") != run_identity:
            _fail("INFRA_BARRIER_RUN_BINDING_INVALID", f"event {index} names another run")
        if record.get("previous_event_hash") != previous_hash:
            _fail("INFRA_BARRIER_CHAIN_INVALID", f"event {index} has wrong previous hash")
        actual_hash = str(record.get("event_hash") or "")
        if actual_hash != _record_hash(record):
            _fail("INFRA_BARRIER_HASH_INVALID", f"event {index} hash mismatch")

        key = record["barrier_key"]
        token = _key_token(key)
        state = states.setdefault(token, _new_state(key))
        event = record["event"]
        data = record["data"]

        if pending_open is not None:
            pending_token, trigger_hash = pending_open
            if event != "opened" or token != pending_token \
                    or data.get("trigger_observation_hash") != trigger_hash:
                _fail(
                    "INFRA_BARRIER_OPEN_EVENT_MISSING",
                    "the second observation must be followed by its mechanical open event",
                )

        if event == "observed":
            action_states = _matching_action_states(states, key)
            if any(item["open"] for item in action_states):
                _fail(
                    "INFRA_BARRIER_THIRD_OBSERVATION",
                    "an open action barrier must reject another target attempt",
                )
            receipt = data["failure_receipt_sha256"]
            if receipt in failure_receipts:
                _fail("INFRA_BARRIER_RECEIPT_DUPLICATE", "failure receipt is not unique")
            failure_receipts[receipt] = record
            state["failure_count"] += 1
            action_failure_count = sum(
                int(item["failure_count"]) for item in action_states)
            if action_failure_count > OPEN_THRESHOLD:
                _fail("INFRA_BARRIER_COUNT_INVALID", "failure count exceeded threshold")
            pending_open = (
                (token, actual_hash)
                if action_failure_count == OPEN_THRESHOLD else None
            )
        elif event == "opened":
            action_states = _matching_action_states(states, key)
            if pending_open is None \
                    or any(item["open"] for item in action_states) \
                    or sum(int(item["failure_count"])
                           for item in action_states) != OPEN_THRESHOLD \
                    or data.get("failure_count") != OPEN_THRESHOLD:
                _fail("INFRA_BARRIER_OPEN_EVENT_INVALID", "open event has no exact threshold")
            state["open"] = True
            state["open_event_hash"] = actual_hash
            pending_open = None
        elif event == "cleared":
            basis = data["basis_sha256"]
            if basis in clearance_receipts:
                _fail("INFRA_BARRIER_CLEAR_DUPLICATE", "clearance basis is not unique")
            action_states = _matching_action_states(states, key)
            open_hashes = {
                str(item["open_event_hash"])
                for item in action_states if item["open"]
            }
            expected_open_hash = next(iter(open_hashes)) if len(open_hashes) == 1 else ""
            if sum(int(item["failure_count"])
                   for item in action_states) < 1 \
                    or len(open_hashes) > 1 \
                    or data.get("prior_open_event_hash") != expected_open_hash:
                _fail(
                    "INFRA_BARRIER_CLEAR_INVALID",
                    "clear event has no exact action failure epoch",
                )
            clearance_receipts[basis] = record
            for action_state in action_states:
                action_state["failure_count"] = 0
                action_state["open"] = False
                action_state["open_event_hash"] = ""
                action_state["last_event_hash"] = actual_hash
        else:  # schema validation should make this unreachable
            _fail("INFRA_BARRIER_EVENT_INVALID", f"unknown event {event!r}")

        state["last_event_hash"] = actual_hash
        previous_hash = actual_hash

    if pending_open is not None:
        _fail(
            "INFRA_BARRIER_OPEN_EVENT_MISSING",
            "journal ended after the second observation without its open event",
        )
    return {
        "states": states,
        "failure_receipts": failure_receipts,
        "clearance_receipts": clearance_receipts,
        "tail_hash": previous_hash,
    }


def _read_events(path: Path) -> list[dict]:
    if path.is_symlink():
        _fail("INFRA_BARRIER_JOURNAL_INVALID", "journal must not be a symlink")
    if not path.exists():
        return []
    if not path.is_file():
        _fail("INFRA_BARRIER_JOURNAL_INVALID", "journal must be a regular file")
    try:
        before = path.stat(follow_symlinks=False)
    except OSError as exc:
        _fail("INFRA_BARRIER_JOURNAL_UNAVAILABLE", type(exc).__name__)
    if before.st_size > MAX_JOURNAL_BYTES:
        _fail("INFRA_BARRIER_JOURNAL_OVERSIZE", "journal exceeds read budget")
    flags = os.O_RDONLY
    if hasattr(os, "O_CLOEXEC"):
        flags |= os.O_CLOEXEC
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    try:
        descriptor = os.open(path, flags)
        try:
            opened = os.fstat(descriptor)
            if not stat.S_ISREG(opened.st_mode) \
                    or (opened.st_dev, opened.st_ino) != (before.st_dev, before.st_ino):
                _fail(
                    "INFRA_BARRIER_JOURNAL_CHANGED",
                    "journal changed before the read snapshot",
                )
            with os.fdopen(descriptor, "rb", closefd=False) as handle:
                raw = handle.read(MAX_JOURNAL_BYTES + 1)
            after = os.fstat(descriptor)
        finally:
            os.close(descriptor)
        text = raw.decode("utf-8", "strict")
    except (OSError, UnicodeDecodeError) as exc:
        _fail("INFRA_BARRIER_JOURNAL_UNAVAILABLE", type(exc).__name__)
    if len(raw) > MAX_JOURNAL_BYTES:
        _fail("INFRA_BARRIER_JOURNAL_OVERSIZE", "journal exceeds read budget")
    if _identity(before) != _identity(after):
        _fail("INFRA_BARRIER_JOURNAL_CHANGED", "journal changed during read")
    if not text:
        return []
    if not text.endswith("\n"):
        _fail("INFRA_BARRIER_JOURNAL_TRUNCATED", "journal has an incomplete tail")
    events: list[dict] = []
    for line_number, line in enumerate(text.splitlines(), start=1):
        if not line:
            _fail("INFRA_BARRIER_JOURNAL_INVALID", f"blank line {line_number}")
        try:
            value = json.loads(line)
        except json.JSONDecodeError:
            _fail("INFRA_BARRIER_JOURNAL_INVALID", f"invalid JSON at line {line_number}")
        if not isinstance(value, dict):
            _fail("INFRA_BARRIER_JOURNAL_INVALID", f"line {line_number} is not an object")
        events.append(value)
        if len(events) > MAX_EVENTS:
            _fail("INFRA_BARRIER_JOURNAL_OVERSIZE", "journal has too many events")
    return events


def load_events(
    run_dir: str | Path,
    *,
    runs_root: str | Path = RUNS_ROOT,
) -> list[dict]:
    run = _resolve_run_dir(run_dir, runs_root=runs_root)
    path = _journal_path(run)
    events = _read_events(path)
    _validate_and_project(events, run_identity=_run_identity(run, runs_root))
    return events


def _fsync_directory(path: Path) -> None:
    flags = os.O_RDONLY
    if hasattr(os, "O_DIRECTORY"):
        flags |= os.O_DIRECTORY
    descriptor = os.open(path, flags)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _fsync_file(handle) -> None:
    handle.flush()
    os.fsync(handle.fileno())


def _identity(value: os.stat_result) -> tuple[int, int, int, int]:
    return (value.st_dev, value.st_ino, value.st_size, value.st_mtime_ns)


def _ensure_state_dir(run_dir: Path) -> Path:
    state_dir = run_dir / "state"
    if state_dir.exists():
        if state_dir.is_symlink() or not state_dir.is_dir():
            _fail("INFRA_BARRIER_STATE_INVALID", "state must be a regular directory")
    else:
        try:
            state_dir.mkdir(mode=0o700)
        except OSError as exc:
            raise BarrierDurabilityError(
                f"state directory creation failed: {type(exc).__name__}"
            ) from exc
    try:
        # Repeat the parent barrier even when a prior mkdir became visible but
        # its directory fsync failed.  Exact retry can then recover safely.
        _fsync_directory(run_dir)
    except OSError as exc:
        raise BarrierDurabilityError(
            f"state directory durability failed: {type(exc).__name__}"
        ) from exc
    return state_dir


@contextlib.contextmanager
def _journal_lock(run_dir: Path):
    state_dir = _ensure_state_dir(run_dir)
    lock_path = state_dir / LOCK
    flags = os.O_RDWR | os.O_CREAT | getattr(os, "O_CLOEXEC", 0) \
        | getattr(os, "O_NOFOLLOW", 0)
    try:
        descriptor = os.open(lock_path, flags, 0o600)
    except OSError as exc:
        _fail("INFRA_BARRIER_LOCK_INVALID", exc.__class__.__name__)
        raise AssertionError from exc
    with os.fdopen(descriptor, "a+", encoding="utf-8") as handle:
        opened = os.fstat(handle.fileno())
        if not stat.S_ISREG(opened.st_mode):
            _fail("INFRA_BARRIER_LOCK_INVALID", "lock must be a regular file")
        try:
            os.fchmod(handle.fileno(), 0o600)
        except OSError:
            pass
        if fcntl is not None:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
        try:
            current = os.stat(lock_path, follow_symlinks=False)
            if (opened.st_dev, opened.st_ino) != (current.st_dev, current.st_ino):
                _fail("INFRA_BARRIER_LOCK_REPLACED", "lock inode changed")
            yield
        finally:
            try:
                current = os.stat(lock_path, follow_symlinks=False)
            except OSError as exc:
                _fail("INFRA_BARRIER_LOCK_REPLACED", exc.__class__.__name__)
            if (opened.st_dev, opened.st_ino) != (current.st_dev, current.st_ino):
                _fail("INFRA_BARRIER_LOCK_REPLACED", "lock inode changed")
            if fcntl is not None:
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def _append_records(path: Path, records: list[dict]) -> None:
    if not records:
        return
    if path.is_symlink() or (path.exists() and not path.is_file()):
        _fail("INFRA_BARRIER_JOURNAL_INVALID", "journal must be a regular file")
    existed_before = path.exists()
    before = path.stat(follow_symlinks=False) if existed_before else None
    original_size = before.st_size if before is not None else 0
    encoded = b"".join(
        _canonical_json(record) + b"\n" for record in records
    )
    flags = os.O_WRONLY | os.O_APPEND | os.O_CREAT
    if hasattr(os, "O_CLOEXEC"):
        flags |= os.O_CLOEXEC
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    try:
        descriptor = os.open(path, flags, 0o600)
    except OSError as exc:
        raise BarrierDurabilityError(
            f"barrier journal open failed: {type(exc).__name__}"
        ) from exc
    with os.fdopen(descriptor, "ab", buffering=0) as handle:
        try:
            opened = os.fstat(handle.fileno())
            if not stat.S_ISREG(opened.st_mode) \
                    or (before is not None and (
                        opened.st_dev, opened.st_ino
                    ) != (before.st_dev, before.st_ino)):
                raise OSError("journal changed before append")
            written = handle.write(encoded)
            if written != len(encoded):
                raise OSError(f"short append {written}/{len(encoded)}")
            try:
                os.fchmod(handle.fileno(), 0o600)
            except OSError:
                pass
            _fsync_file(handle)
            if not existed_before or original_size == 0:
                _fsync_directory(path.parent)
        except Exception as append_error:
            try:
                handle.truncate(original_size)
                handle.seek(original_size)
                _fsync_file(handle)
                if not existed_before or original_size == 0:
                    _fsync_directory(path.parent)
            except Exception as rollback_error:
                raise BarrierDurabilityError(
                    "barrier journal append failed and rollback was not durable: "
                    f"append={append_error}; rollback={rollback_error}"
                ) from append_error
            raise BarrierDurabilityError(
                "barrier journal append failed; uncommitted tail rolled back: "
                f"{append_error}"
            ) from append_error


def _event(
    *,
    event: str,
    seq: int,
    run_identity: str,
    key: dict,
    data: dict,
    previous_event_hash: str,
    recorded_at: float | None = None,
) -> dict:
    record = {
        "schema": SCHEMA,
        "event": event,
        "seq": seq,
        "run_dir": run_identity,
        "writer": WRITER,
        "recorded_at": time.time() if recorded_at is None else recorded_at,
        "barrier_key": dict(key),
        "data": data,
        "previous_event_hash": previous_event_hash,
        "authority": AUTHORITY,
    }
    record["event_hash"] = _record_hash(record)
    errors = contract_schema.named_schema_errors(record, SCHEMA_FILE)
    if errors:
        _fail("INFRA_BARRIER_EVENT_INVALID", errors[0])
    return record


def record_failure(
    run_dir: str | Path,
    *,
    front: str,
    action_fingerprint: str,
    cause_code: str,
    precondition_digest: str,
    failure_receipt_sha256: str,
    failure_domain: str,
    target_bytes: int,
    runs_root: str | Path = RUNS_ROOT,
) -> dict:
    """Record one unique zero-byte infrastructure failure.

    The second unique receipt appends ``observed`` and ``opened`` in one durable
    batch.  A replay of the same receipt is idempotent.  Once open, a new
    identical failure is rejected rather than being counted as a target result.
    """
    key = barrier_key(
        front=front,
        action_fingerprint=action_fingerprint,
        cause_code=cause_code,
        precondition_digest=precondition_digest,
    )
    if not _HEX64.fullmatch(str(failure_receipt_sha256 or "")):
        _fail("INFRA_BARRIER_RECEIPT_INVALID", "failure receipt must be lowercase sha256")
    if failure_domain not in _FAILURE_DOMAINS:
        _fail("INFRA_BARRIER_DOMAIN_INVALID", "failure domain is not infrastructure")
    if isinstance(target_bytes, bool) or target_bytes != 0:
        _fail(
            "INFRA_BARRIER_TARGET_BYTES_NONZERO",
            "only infrastructure failures with exactly zero target bytes qualify",
        )

    run = _resolve_run_dir(run_dir, runs_root=runs_root)
    run_identity = _run_identity(run, runs_root)
    with _journal_lock(run):
        path = _journal_path(run)
        events = _read_events(path)
        projection = _validate_and_project(events, run_identity=run_identity)
        existing = projection["failure_receipts"].get(failure_receipt_sha256)
        if existing is not None:
            if _key_token(existing["barrier_key"]) != _key_token(key) \
                    or existing["data"].get("failure_domain") != failure_domain:
                _fail(
                    "INFRA_BARRIER_RECEIPT_CONFLICT",
                    "failure receipt is already bound to different barrier facts",
                )
            opened = next((
                item for item in events
                if item.get("event") == "opened"
                and (item.get("data") or {}).get("trigger_observation_hash")
                == existing.get("event_hash")
            ), None)
            return {
                "status": "unchanged",
                "observed": existing,
                "opened": opened,
            }

        token = _key_token(key)
        state = projection["states"].get(token) or _new_state(key)
        action_states = _matching_action_states(projection["states"], key)
        if any(item["open"] for item in action_states):
            _fail(
                "INFRA_BARRIER_OPEN",
                "third same-action target attempt is blocked; repair, locally verify, or change the action fingerprint",
            )
        count = sum(int(item["failure_count"]) for item in action_states) + 1
        observed = _event(
            event="observed",
            seq=len(events) + 1,
            run_identity=run_identity,
            key=key,
            data={
                "failure_receipt_sha256": failure_receipt_sha256,
                "failure_domain": failure_domain,
                "target_bytes": 0,
                "target_failure_counted": False,
                "front_state_changed": False,
            },
            previous_event_hash=projection["tail_hash"],
        )
        batch = [observed]
        opened = None
        if count == OPEN_THRESHOLD:
            opened = _event(
                event="opened",
                seq=len(events) + 2,
                run_identity=run_identity,
                key=key,
                data={
                    "failure_count": OPEN_THRESHOLD,
                    "trigger_observation_hash": observed["event_hash"],
                },
                previous_event_hash=observed["event_hash"],
            )
            batch.append(opened)
        candidate = [*events, *batch]
        _validate_and_project(candidate, run_identity=run_identity)
        _append_records(path, batch)
        return {
            "status": "opened" if opened is not None else "observed",
            "observed": observed,
            "opened": opened,
        }


def clear_barrier(
    run_dir: str | Path,
    *,
    front: str,
    action_fingerprint: str,
    cause_code: str,
    precondition_digest: str,
    reason: str,
    basis_sha256: str,
    expected_last_event_hash: str = "",
    runs_root: str | Path = RUNS_ROOT,
) -> dict:
    """Clear one exact partial/open streak after a typed recovery basis."""
    key = barrier_key(
        front=front,
        action_fingerprint=action_fingerprint,
        cause_code=cause_code,
        precondition_digest=precondition_digest,
    )
    if reason not in _CLEAR_REASONS:
        _fail("INFRA_BARRIER_CLEAR_REASON_INVALID", "clear reason is not typed")
    if not _HEX64.fullmatch(str(basis_sha256 or "")):
        _fail("INFRA_BARRIER_CLEAR_BASIS_INVALID", "clear basis must be lowercase sha256")
    if expected_last_event_hash and not _HEX64.fullmatch(
            expected_last_event_hash):
        _fail(
            "INFRA_BARRIER_CLEAR_BASIS_INVALID",
            "expected epoch event hash must be lowercase sha256",
        )

    run = _resolve_run_dir(run_dir, runs_root=runs_root)
    run_identity = _run_identity(run, runs_root)
    with _journal_lock(run):
        path = _journal_path(run)
        events = _read_events(path)
        projection = _validate_and_project(events, run_identity=run_identity)
        state = projection["states"].get(_key_token(key)) or _new_state(key)
        action_states = _matching_action_states(projection["states"], key)
        action_failure_count = sum(
            int(item["failure_count"]) for item in action_states)
        open_hashes = {
            str(item["open_event_hash"])
            for item in action_states if item["open"]
        }
        if len(open_hashes) > 1:
            _fail(
                "INFRA_BARRIER_CLEAR_BASIS_AMBIGUOUS",
                "action has multiple open barrier epochs",
            )
        action_open_hash = next(iter(open_hashes)) if open_hashes else ""
        if expected_last_event_hash \
                and state["last_event_hash"] != expected_last_event_hash:
            _fail(
                "INFRA_BARRIER_CLEAR_EPOCH_CHANGED",
                "barrier epoch changed after the runtime basis was derived",
            )
        existing = projection["clearance_receipts"].get(basis_sha256)
        if existing is not None:
            if _key_token(existing["barrier_key"]) != _key_token(key) \
                    or existing["data"].get("reason") != reason:
                _fail(
                    "INFRA_BARRIER_CLEAR_CONFLICT",
                    "clear basis is already bound to different barrier facts",
                )
            if action_failure_count > 0:
                _fail(
                    "INFRA_BARRIER_CLEAR_STALE_REPLAY",
                    "an old clear basis cannot clear a later failure epoch",
                )
            return {"status": "unchanged", "cleared": existing}
        if action_failure_count < 1:
            _fail(
                "INFRA_BARRIER_NOT_OBSERVED",
                "the action has no partial or open failure epoch",
            )
        cleared = _event(
            event="cleared",
            seq=len(events) + 1,
            run_identity=run_identity,
            key=key,
            data={
                "reason": reason,
                "basis_sha256": basis_sha256,
                "prior_open_event_hash": action_open_hash,
            },
            previous_event_hash=projection["tail_hash"],
        )
        _validate_and_project([*events, cleared], run_identity=run_identity)
        _append_records(path, [cleared])
        return {"status": "cleared", "cleared": cleared}


def preflight_decision(
    run_dir: str | Path,
    *,
    front: str,
    action_fingerprint: str,
    cause_code: str,
    precondition_digest: str,
    operation_class: str,
    runs_root: str | Path = RUNS_ROOT,
) -> dict:
    """Return the derived allow/reject decision for one action attempt.

    Cause and precondition remain part of the durable observation key, but they
    are diagnostic dimensions rather than an alternate namespace for replaying
    an action that already has an open barrier.  A target attempt is therefore
    blocked by any open state with the same front + action fingerprint.  Repair
    and local verification stay exact-key and remain available.
    """
    key = barrier_key(
        front=front,
        action_fingerprint=action_fingerprint,
        cause_code=cause_code,
        precondition_digest=precondition_digest,
    )
    if operation_class not in _OPERATION_CLASSES:
        _fail("INFRA_BARRIER_OPERATION_INVALID", "unknown operation class")
    run = _resolve_run_dir(run_dir, runs_root=runs_root)
    events = _read_events(_journal_path(run))
    projection = _validate_and_project(
        events, run_identity=_run_identity(run, runs_root),
    )
    state = projection["states"].get(_key_token(key)) or _new_state(key)
    blocking_states = []
    if operation_class == "target_attempt":
        blocking_states = sorted(
            (
                item for item in projection["states"].values()
                if item["open"]
                and str(item["barrier_key"].get("front") or "") == front
                and str(item["barrier_key"].get("action_fingerprint") or "")
                == action_fingerprint
            ),
            key=lambda item: _key_token(item["barrier_key"]),
        )
    blocked = bool(blocking_states)
    decision_state = blocking_states[0] if blocked else state
    action_failure_count = sum(
        int(item["failure_count"])
        for item in _matching_action_states(projection["states"], key)
    )
    return {
        "schema": "xunji.infra-barrier-decision.v1",
        "allowed": not blocked,
        "code": "INFRA_BARRIER_OPEN" if blocked else "ALLOW",
        "operation_class": operation_class,
        "barrier_key": dict(decision_state["barrier_key"]),
        "failure_count": (
            action_failure_count
            if operation_class == "target_attempt"
            else decision_state["failure_count"]
        ),
        "open_event_hash": decision_state["open_event_hash"],
        "authority": AUTHORITY,
    }


def status_projection(
    run_dir: str | Path,
    *,
    runs_root: str | Path = RUNS_ROOT,
) -> dict:
    run = _resolve_run_dir(run_dir, runs_root=runs_root)
    events = _read_events(_journal_path(run))
    projected = _validate_and_project(
        events, run_identity=_run_identity(run, runs_root),
    )
    states = sorted(
        (dict(value) for value in projected["states"].values()),
        key=lambda item: _key_token(item["barrier_key"]),
    )
    return {
        "schema": "xunji.infra-barrier-status.v1",
        "run_dir": _run_identity(run, runs_root),
        "event_count": len(events),
        "tail_hash": projected["tail_hash"],
        "open_barriers": [item for item in states if item["open"]],
        "states": states,
        "authority": AUTHORITY,
    }


def _expect_error(code: str, call) -> bool:
    try:
        call()
    except BarrierStateError as exc:
        return exc.code == code
    return False


def _selftest() -> int:
    sys.modules["barrier_state"] = sys.modules[__name__]
    import runtime_receipts as runtime_receipts_module

    checks: list[tuple[str, bool]] = []
    with tempfile.TemporaryDirectory(prefix="xunji-barrier-state-") as raw:
        fixture = Path(raw)
        runs_root = fixture / "runs"
        run = runs_root / "fixture-run"
        (run / "state").mkdir(parents=True)
        key = {
            "front": "F-001",
            "action_fingerprint": "a" * 64,
            "cause_code": "PROXY_CONNECT_FAILED",
            "precondition_digest": "b" * 64,
        }

        runtime_run = runs_root / "runtime-bound"
        (runtime_run / "state").mkdir(parents=True)
        denied_event = {
            "seq": 1,
            "receipt_hash": "d" * 64,
            "hook_event_name": "PreToolUseDenied",
            "success": False,
            "decision": "deny",
            "decision_code": "XUNJI_E_WORK_PLAN_STALE",
            "decision_class": "work_plan",
            "target_action": True,
            "front": "F-001",
            "tool_name": "Bash",
            "action_sha256": "e" * 64,
            "shape_category": "",
            "control_script": "",
            "capability_id": "target.probe",
            "capability_effect": "target",
        }
        semantic_action = ("probe", "GET", "https://app.example/")
        target_lane = {
            "id": "L-F001-TARGET", "front": "F-001", "effect": "target",
        }
        claim = {
            "front": "F-001", "assignment_lane": "L-F001-TARGET",
            "assignment_plan_digest": "9" * 64,
        }
        plan = {"plan_digest": "9" * 64, "lanes": [target_lane]}
        with mock.patch.object(
                runtime_receipts_module, "validate_chain",
                return_value=([denied_event], [])), mock.patch.object(
                runtime_receipts_module, "_target_semantic_action",
                return_value=semantic_action), mock.patch.object(
                sys.modules[__name__], "_runtime_plan_lane",
                return_value=(claim, plan, target_lane)):
            candidate = runtime_failure_candidate(
                runtime_run, failure_receipt_sha256="d" * 64,
                runs_root=runs_root,
            )
            runtime_observed = record_runtime_failure(
                runtime_run, failure_receipt_sha256="d" * 64,
                runs_root=runs_root,
            )
            unbound_runtime_rejected = _expect_error(
                "INFRA_BARRIER_RUNTIME_RECEIPT_UNBOUND",
                lambda: record_runtime_failure(
                    runtime_run, failure_receipt_sha256="f" * 64,
                    runs_root=runs_root,
                ),
            )
        ineligible_event = dict(
            denied_event,
            receipt_hash="f" * 64,
            hook_event_name="PostToolUseFailure",
            decision="",
        )
        with mock.patch.object(
                runtime_receipts_module, "validate_chain",
                return_value=([ineligible_event], [])):
            ineligible_runtime_rejected = _expect_error(
                "INFRA_BARRIER_RUNTIME_FAILURE_INELIGIBLE",
                lambda: record_runtime_failure(
                    runtime_run, failure_receipt_sha256="f" * 64,
                    runs_root=runs_root,
                ),
            )
        candidate_key = candidate["barrier_key"]
        successful_event = dict(
            denied_event,
            seq=2,
            receipt_hash="c" * 64,
            hook_event_name="PostToolUse",
            success=True,
            decision="",
        )
        with mock.patch.object(
                runtime_receipts_module, "validate_chain",
                return_value=([denied_event, successful_event], [])), mock.patch.object(
                runtime_receipts_module, "_target_semantic_action",
                return_value=semantic_action), mock.patch.object(
                sys.modules[__name__], "_runtime_plan_lane",
                return_value=(claim, plan, target_lane)):
            runtime_cleared = clear_runtime_barrier(
                runtime_run, **candidate_key,
                reason="target_response_observed", basis_sha256="c" * 64,
                runs_root=runs_root,
            )

        stale_run = runs_root / "runtime-stale-success"
        (stale_run / "state").mkdir(parents=True)
        stale_success = dict(successful_event, seq=1, receipt_hash="3" * 64)
        stale_failure = dict(denied_event, seq=2, receipt_hash="4" * 64)
        record_failure(
            stale_run, **candidate_key,
            failure_receipt_sha256="4" * 64,
            failure_domain="scheduler", target_bytes=0,
            runs_root=runs_root,
        )
        with mock.patch.object(
                runtime_receipts_module, "validate_chain",
                return_value=([stale_success, stale_failure], [])), mock.patch.object(
                runtime_receipts_module, "_target_semantic_action",
                return_value=semantic_action), mock.patch.object(
                sys.modules[__name__], "_runtime_plan_lane",
                return_value=(claim, plan, target_lane)):
            stale_success_rejected = _expect_error(
                "INFRA_BARRIER_CLEAR_BASIS_STALE",
                lambda: runtime_success_clear_candidate(
                    stale_run, basis_sha256="3" * 64,
                    runs_root=runs_root,
                ),
            )

        race_run = runs_root / "runtime-clear-race"
        (race_run / "state").mkdir(parents=True)
        first_race_failure = dict(denied_event, seq=1, receipt_hash="5" * 64)
        race_success = dict(successful_event, seq=2, receipt_hash="6" * 64)
        second_race_failure = dict(denied_event, seq=3, receipt_hash="7" * 64)
        record_failure(
            race_run, **candidate_key,
            failure_receipt_sha256="5" * 64,
            failure_domain="scheduler", target_bytes=0,
            runs_root=runs_root,
        )
        with mock.patch.object(
                runtime_receipts_module, "validate_chain",
                return_value=([first_race_failure, race_success,
                               second_race_failure], [])), mock.patch.object(
                runtime_receipts_module, "_target_semantic_action",
                return_value=semantic_action), mock.patch.object(
                sys.modules[__name__], "_runtime_plan_lane",
                return_value=(claim, plan, target_lane)):
            stale_epoch_candidate = runtime_success_clear_candidate(
                race_run, basis_sha256="6" * 64,
                runs_root=runs_root,
            )
        record_failure(
            race_run, **candidate_key,
            failure_receipt_sha256="7" * 64,
            failure_domain="scheduler", target_bytes=0,
            runs_root=runs_root,
        )
        clear_race_rejected = _expect_error(
            "INFRA_BARRIER_CLEAR_EPOCH_CHANGED",
            lambda: record_runtime_success_clear(
                race_run, basis_sha256="6" * 64,
                runs_root=runs_root, candidate=stale_epoch_candidate,
            ),
        )
        checks.extend([
            ("runtime observe derives its key from one validated zero-byte denial",
             candidate["failure_domain"] == "scheduler"
             and candidate["target_bytes"] == 0
             and runtime_observed["status"] == "observed"),
            ("runtime observe rejects a hash absent from the validated chain",
             unbound_runtime_rejected),
            ("generic post-tool failures cannot claim zero target bytes",
             ineligible_runtime_rejected),
            ("runtime clear binds an exact successful target response",
             runtime_cleared["status"] == "cleared"),
            ("success predating an active failure epoch cannot clear it",
             stale_success_rejected),
            ("clear candidate cannot erase a failure appended after derivation",
             clear_race_rejected),
        ])

        repair_run = runs_root / "runtime-repair-bound"
        (repair_run / "state").mkdir(parents=True)
        repair_key = {
            "front": "F-001",
            "action_fingerprint": "7" * 64,
            "cause_code": "XUNJI_E_WORK_PLAN_STALE",
            "precondition_digest": "8" * 64,
        }
        record_failure(
            repair_run, **repair_key,
            failure_receipt_sha256="1" * 64,
            failure_domain="scheduler", target_bytes=0,
            runs_root=runs_root,
        )
        repair_success = dict(
            successful_event,
            receipt_hash="2" * 64,
            target_action=False,
            capability_effect="local_verify",
        )
        repair_failure = dict(
            denied_event,
            receipt_hash="1" * 64,
        )
        local_verify_lane = {
            "id": "L-F001-REPAIR", "front": "F-001",
            "effect": "local_verify",
            "infra_barrier": {
                "schema": "xunji.infra-barrier-binding.v1",
                **{key: value for key, value in repair_key.items()
                   if key != "front"},
                "operation_class": "local_verify",
            },
        }
        repair_lane = dict(local_verify_lane)
        repair_lane["infra_barrier"] = {
            **local_verify_lane["infra_barrier"],
            "operation_class": "repair",
        }
        repair_plan = {"plan_digest": "6" * 64, "lanes": [repair_lane]}
        repair_claim = {
            "front": "F-001", "assignment_lane": "L-F001-REPAIR",
            "assignment_plan_digest": "6" * 64,
        }
        with mock.patch.object(
                runtime_receipts_module, "validate_chain",
                return_value=([repair_failure, repair_success], [])), mock.patch.object(
                sys.modules[__name__], "_runtime_plan_lane",
                return_value=(repair_claim, repair_plan, local_verify_lane)):
            unrelated_local_verify = runtime_success_clear_candidate(
                repair_run, basis_sha256="2" * 64,
                runs_root=runs_root,
            )
        with mock.patch.object(
                runtime_receipts_module, "validate_chain",
                return_value=([repair_failure, repair_success], [])), mock.patch.object(
                sys.modules[__name__], "_runtime_plan_lane",
                return_value=(repair_claim, repair_plan, repair_lane)):
            exact_repair_clear = record_runtime_success_clear(
                repair_run, basis_sha256="2" * 64,
                runs_root=runs_root,
            )
        checks.extend([
            ("unrelated local_verify success cannot clear a barrier",
             unrelated_local_verify.get("eligible") is False),
            ("only exact operation_class=repair lane success clears",
             exact_repair_clear.get("status") == "cleared"),
        ])

        initial = preflight_decision(
            run, **key, operation_class="target_attempt", runs_root=runs_root,
        )
        first = record_failure(
            run, **key, failure_receipt_sha256="1" * 64,
            failure_domain="proxy", target_bytes=0, runs_root=runs_root,
        )
        after_first = preflight_decision(
            run, **key, operation_class="target_attempt", runs_root=runs_root,
        )
        second = record_failure(
            run, **key, failure_receipt_sha256="2" * 64,
            failure_domain="proxy", target_bytes=0, runs_root=runs_root,
        )
        blocked = preflight_decision(
            run, **key, operation_class="target_attempt", runs_root=runs_root,
        )
        repair = preflight_decision(
            run, **key, operation_class="repair", runs_root=runs_root,
        )
        local_verify = preflight_decision(
            run, **key, operation_class="local_verify", runs_root=runs_root,
        )
        changed_diagnostics = preflight_decision(
            run, **dict(key, precondition_digest="c" * 64),
            operation_class="target_attempt", runs_root=runs_root,
        )
        event_count = status_projection(run, runs_root=runs_root)["event_count"]
        replay = record_failure(
            run, **key, failure_receipt_sha256="2" * 64,
            failure_domain="proxy", target_bytes=0, runs_root=runs_root,
        )
        event_count_after_replay = status_projection(
            run, runs_root=runs_root,
        )["event_count"]

        checks.extend([
            ("empty journal allows target attempt", initial["allowed"]),
            ("first zero-byte infrastructure failure stays below threshold",
             first["status"] == "observed" and after_first["allowed"]
             and after_first["failure_count"] == 1),
            ("second failure atomically opens the barrier",
             second["status"] == "opened" and second["opened"] is not None
             and event_count == 3),
            ("third identical target shape is blocked", not blocked["allowed"]
             and blocked["code"] == "INFRA_BARRIER_OPEN"),
            ("repair and local verification remain allowed",
             repair["allowed"] and local_verify["allowed"]),
            ("changed precondition cannot bypass the same open action",
             not changed_diagnostics["allowed"]
             and changed_diagnostics["code"] == "INFRA_BARRIER_OPEN"
             and changed_diagnostics["barrier_key"] == key
             and changed_diagnostics["failure_count"] == 2),
            ("failure receipt replay is idempotent",
             replay["status"] == "unchanged"
             and event_count_after_replay == event_count),
            ("writer refuses to append a third identical observation",
             _expect_error(
                 "INFRA_BARRIER_OPEN",
                 lambda: record_failure(
                     run, **key, failure_receipt_sha256="9" * 64,
                     failure_domain="proxy", target_bytes=0,
                     runs_root=runs_root,
                 ),
             )),
        ])

        clear = clear_barrier(
            run, **key, reason="repair_succeeded", basis_sha256="3" * 64,
            runs_root=runs_root,
        )
        clear_replay = clear_barrier(
            run, **key, reason="repair_succeeded", basis_sha256="3" * 64,
            runs_root=runs_root,
        )
        after_clear = preflight_decision(
            run, **key, operation_class="target_attempt", runs_root=runs_root,
        )
        checks.extend([
            ("typed repair basis clears only the exact open barrier",
             clear["status"] == "cleared" and after_clear["allowed"]
             and after_clear["failure_count"] == 0),
            ("clear replay is idempotent", clear_replay["status"] == "unchanged"),
            ("non-zero target bytes cannot become infrastructure failures",
             _expect_error(
                 "INFRA_BARRIER_TARGET_BYTES_NONZERO",
                 lambda: record_failure(
                     run, **key, failure_receipt_sha256="4" * 64,
                     failure_domain="proxy", target_bytes=1,
                     runs_root=runs_root,
                 ),
             )),
        ])

        rotated_run = runs_root / "diagnostic-rotation"
        (rotated_run / "state").mkdir(parents=True)
        rotated_key = {
            **key,
            "cause_code": "NETWORK_TRANSPORT_FAILED",
            "precondition_digest": "c" * 64,
        }
        record_failure(
            rotated_run, **key, failure_receipt_sha256="4" * 64,
            failure_domain="proxy", target_bytes=0, runs_root=runs_root,
        )
        rotated_second = record_failure(
            rotated_run, **rotated_key, failure_receipt_sha256="5" * 64,
            failure_domain="network_transport", target_bytes=0,
            runs_root=runs_root,
        )
        rotated_blocked = preflight_decision(
            rotated_run,
            **dict(rotated_key, precondition_digest="d" * 64),
            operation_class="target_attempt", runs_root=runs_root,
        )
        clear_barrier(
            rotated_run, **rotated_key, reason="repair_succeeded",
            basis_sha256="6" * 64, runs_root=runs_root,
        )
        rotated_states = status_projection(
            rotated_run, runs_root=runs_root)["states"]
        checks.append((
            "diagnostic rotation cannot prevent the same action reaching threshold",
            rotated_second["status"] == "opened"
            and not rotated_blocked["allowed"]
            and rotated_blocked["failure_count"] == 2
            and all(item["failure_count"] == 0 for item in rotated_states),
        ))

        concurrent_run = runs_root / "concurrent-diagnostic-rotation"
        (concurrent_run / "state").mkdir(parents=True)
        concurrent_results: list[dict] = []
        concurrent_errors: list[BaseException] = []

        def concurrent_failure(item_key: dict, receipt_hash: str) -> None:
            try:
                concurrent_results.append(record_failure(
                    concurrent_run, **item_key,
                    failure_receipt_sha256=receipt_hash,
                    failure_domain="network_transport", target_bytes=0,
                    runs_root=runs_root,
                ))
            except BaseException as exc:  # pragma: no cover - asserted below
                concurrent_errors.append(exc)

        concurrent_threads = [
            threading.Thread(target=concurrent_failure, args=(key, "d" * 64)),
            threading.Thread(
                target=concurrent_failure, args=(rotated_key, "e" * 64)),
        ]
        for thread in concurrent_threads:
            thread.start()
        for thread in concurrent_threads:
            thread.join()
        concurrent_projection = status_projection(
            concurrent_run, runs_root=runs_root)
        checks.append((
            "concurrent diagnostic failures serialize into one open action epoch",
            not concurrent_errors
            and sorted(item["status"] for item in concurrent_results)
            == ["observed", "opened"]
            and concurrent_projection["event_count"] == 3
            and sum(
                item["failure_count"]
                for item in concurrent_projection["states"]
            ) == 2
            and sum(
                1 for item in concurrent_projection["states"] if item["open"]
            ) == 1,
        ))

        record_failure(
            run, **key, failure_receipt_sha256="7" * 64,
            failure_domain="proxy", target_bytes=0, runs_root=runs_root,
        )
        record_failure(
            run, **key, failure_receipt_sha256="8" * 64,
            failure_domain="proxy", target_bytes=0, runs_root=runs_root,
        )
        checks.append((
            "a prior clear receipt cannot clear a later barrier epoch",
            _expect_error(
                "INFRA_BARRIER_CLEAR_STALE_REPLAY",
                lambda: clear_barrier(
                    run, **key, reason="repair_succeeded",
                    basis_sha256="3" * 64, runs_root=runs_root,
                ),
            ),
        ))

        partial_run = runs_root / "partial-streak"
        (partial_run / "state").mkdir(parents=True)
        record_failure(
            partial_run, **key, failure_receipt_sha256="a" * 64,
            failure_domain="network_transport", target_bytes=0,
            runs_root=runs_root,
        )
        partial_clear = clear_barrier(
            partial_run, **key, reason="target_response_observed",
            basis_sha256="b" * 64, runs_root=runs_root,
        )
        record_failure(
            partial_run, **key, failure_receipt_sha256="c" * 64,
            failure_domain="network_transport", target_bytes=0,
            runs_root=runs_root,
        )
        partial_status = preflight_decision(
            partial_run, **key, operation_class="target_attempt",
            runs_root=runs_root,
        )
        checks.append((
            "a successful response clears a one-failure streak so failures are consecutive",
            partial_clear["status"] == "cleared"
            and partial_status["allowed"]
            and partial_status["failure_count"] == 1,
        ))

        durable_run = runs_root / "durability"
        (durable_run / "state").mkdir(parents=True)
        with mock.patch(__name__ + "._fsync_file", side_effect=OSError("fixture")):
            try:
                record_failure(
                    durable_run, **key, failure_receipt_sha256="5" * 64,
                    failure_domain="runtime", target_bytes=0,
                    runs_root=runs_root,
                )
            except BarrierDurabilityError:
                durability_failed = True
            else:
                durability_failed = False
        durable_path = _journal_path(durable_run)
        checks.append((
            "failed durability barrier rolls back the uncommitted append",
            durability_failed
            and (not durable_path.exists() or durable_path.stat().st_size == 0),
        ))

        tamper_run = runs_root / "tamper"
        (tamper_run / "state").mkdir(parents=True)
        record_failure(
            tamper_run, **key, failure_receipt_sha256="6" * 64,
            failure_domain="tooling", target_bytes=0, runs_root=runs_root,
        )
        tamper_path = _journal_path(tamper_run)
        tampered = json.loads(tamper_path.read_text(encoding="utf-8"))
        tampered["data"]["failure_domain"] = "scheduler"
        tamper_path.write_text(
            json.dumps(tampered, sort_keys=True) + "\n", encoding="utf-8",
        )
        checks.append((
            "hash-chain tampering fails closed",
            _expect_error(
                "INFRA_BARRIER_HASH_INVALID",
                lambda: status_projection(tamper_run, runs_root=runs_root),
            ),
        ))

        outside = fixture / "outside"
        outside.mkdir()
        checks.append((
            "run path outside the configured runs root is rejected",
            _expect_error(
                "INFRA_BARRIER_RUN_OUTSIDE_ROOT",
                lambda: status_projection(outside, runs_root=runs_root),
            ),
        ))
        if hasattr(os, "symlink"):
            symlink_run = runs_root / "symlink-run"
            symlink_run.symlink_to(outside, target_is_directory=True)
            checks.append((
                "run symlinks are rejected",
                _expect_error(
                    "INFRA_BARRIER_SYMLINK",
                    lambda: status_projection(symlink_run, runs_root=runs_root),
                ),
            ))

    bad = [name for name, ok in checks if not ok]
    for name, ok in checks:
        print(("ok   " if ok else "FAIL ") + name)
    print("barrier_state selftest " + (
        "passed" if not bad else f"FAILED ({len(bad)})"
    ))
    return 0 if not bad else 1


def _add_key_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--front", required=True)
    parser.add_argument("--action-fingerprint", required=True)
    parser.add_argument("--cause-code", required=True)
    parser.add_argument("--precondition-digest", required=True)


def _key_args(args: argparse.Namespace) -> dict:
    return {
        "front": args.front,
        "action_fingerprint": args.action_fingerprint,
        "cause_code": args.cause_code,
        "precondition_digest": args.precondition_digest,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Record and inspect the derived repeated-infrastructure-failure barrier.",
    )
    parser.add_argument("--selftest", action="store_true")
    subparsers = parser.add_subparsers(dest="command")

    observe = subparsers.add_parser("observe")
    observe.add_argument("run")
    observe.add_argument("--failure-receipt-sha256", required=True)

    clear = subparsers.add_parser("clear")
    clear.add_argument("run")
    _add_key_args(clear)
    clear.add_argument("--reason", choices=sorted(_CLI_CLEAR_REASONS), required=True)
    clear.add_argument("--basis-sha256", required=True)

    check = subparsers.add_parser("check")
    check.add_argument("run")
    _add_key_args(check)
    check.add_argument("--operation-class", choices=sorted(_OPERATION_CLASSES), required=True)

    status = subparsers.add_parser("status")
    status.add_argument("run")

    args = parser.parse_args(argv)
    if args.selftest:
        if args.command:
            parser.error("--selftest cannot be combined with a command")
        return _selftest()
    if not args.command:
        parser.error("a command is required")

    try:
        if args.command == "observe":
            result = record_runtime_failure(
                args.run,
                failure_receipt_sha256=args.failure_receipt_sha256,
            )
        elif args.command == "clear":
            result = clear_runtime_barrier(
                args.run, **_key_args(args), reason=args.reason,
                basis_sha256=args.basis_sha256,
            )
        elif args.command == "check":
            result = preflight_decision(
                args.run, **_key_args(args), operation_class=args.operation_class,
            )
        else:
            result = status_projection(args.run)
    except (BarrierStateError, BarrierDurabilityError) as exc:
        print(str(exc), file=sys.stderr)
        return 2
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
    if args.command == "check" and not result["allowed"]:
        return 3
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
