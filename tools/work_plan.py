#!/usr/bin/env python3
"""Versioned Root work-plan and delegation-decision contract.

The plan is a derived control-plane projection.  It binds one current EXECUTE
turn to a canonical input digest and a finite set of effect-typed lanes.  It is
never evidence, operator authority, a finding, or closure proof.
"""
from __future__ import annotations

import argparse
import contextlib
import hashlib
import json
import math
import os
import re
import stat
import sys
import tempfile
import time
from pathlib import Path

try:
    import fcntl
except ImportError:  # pragma: no cover - atomic replace remains the fallback
    fcntl = None


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

import loop_journal  # noqa: E402
import run_model  # noqa: E402
from harness import capability_registry  # noqa: E402


SCHEMA = "xunji.work-plan.v1"
DECISION_SCHEMA = "xunji.delegation-decision.v1"
TRANSACTION_SCHEMA = "xunji.work-plan-transaction.v2"
LEGACY_TRANSACTION_SCHEMA = "xunji.work-plan-transaction.v1"
PLAN_FILE = "work_plan.json"
PLAN_ARCHIVE_DIR = "work_plans"
TRANSACTION_FILE = "work_plan_transaction.json"
TRANSACTION_ARCHIVE_DIR = "work_plan_transactions"
MODES = frozenset({"ROOT_DIRECT", "SERIAL_AGENT", "PARALLEL_AGENTS"})
CANONICAL_LANE_ROLES = frozenset({
    "surface", "web-auth", "web-hunter", "code-audit", "exploit", "verify",
    "review", "report",
})
STAGES = frozenset({"S1", "S2", "S3"})
EFFECTS = frozenset({
    "local_read", "local_verify", "control", "target",
    "model_egress", "repo_mutation",
})
CANONICAL_INPUTS = (
    "target.md", "surface.md", "frontier.md", "hypotheses.md",
    "evidence.md", "false_positive.md", "decisions.md", "review.md",
    "report.md", "chains.md", "hints.md", "retrospective.md", "coverage.json",
    "state/conflicts.json",
)
CONDITIONAL_CANONICAL_INPUTS = frozenset({"chains.md", "hints.md"})
_HEX64 = re.compile(r"[0-9a-f]{64}")
_LANE_ID = re.compile(r"L-[A-Za-z0-9._-]+")
_FRONT_ID = re.compile(r"F-[0-9]+")
_CAPABILITY_ID = re.compile(
    r"[a-z][a-z0-9]*(?:[.-][a-z0-9][a-z0-9-]*)*"
)


class PlanError(ValueError):
    """Stable validation failure for a work-plan transition."""


def _resolve_run(path: str | Path) -> Path:
    value = Path(path)
    return (value if value.is_absolute() else ROOT / value).resolve()


def plan_path(run_dir: str | Path) -> Path:
    return _resolve_run(run_dir) / "state" / PLAN_FILE


def plan_snapshot_path(run_dir: str | Path, plan_digest: str) -> Path:
    digest = str(plan_digest or "")
    if not _HEX64.fullmatch(digest):
        raise PlanError("WORK_PLAN_DIGEST_INVALID")
    return _resolve_run(run_dir) / "state" / PLAN_ARCHIVE_DIR / f"{digest}.json"


def plan_transaction_path(run_dir: str | Path) -> Path:
    return _resolve_run(run_dir) / "state" / TRANSACTION_FILE


def transaction_archive_path(run_dir: str | Path, receipt_hash: str) -> Path:
    digest = str(receipt_hash or "")
    if not _HEX64.fullmatch(digest):
        raise PlanError("WORK_PLAN_TRANSACTION_RECEIPT_HASH_INVALID")
    return (_resolve_run(run_dir) / "state" / TRANSACTION_ARCHIVE_DIR
            / f"{digest}.json")


def _json_bytes(value: object) -> bytes:
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
    ).encode("utf-8")


def _hash(value: object) -> str:
    return hashlib.sha256(_json_bytes(value)).hexdigest()


@contextlib.contextmanager
def _plan_lock(run_dir: Path):
    path = run_dir / "state" / ".work_plan.lock"
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a+", encoding="utf-8") as handle:
        if fcntl is not None:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
        try:
            yield
        finally:
            if fcntl is not None:
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def _flush_and_fsync_json(handle, destination: Path) -> None:
    """Make one temporary JSON body durable before it can be published."""
    del destination  # Retained as an explicit fault-injection/diagnostic binding.
    handle.flush()
    os.fsync(handle.fileno())


def _fsync_directory(path: Path) -> None:
    flags = os.O_RDONLY
    if hasattr(os, "O_DIRECTORY"):
        flags |= os.O_DIRECTORY
    directory_fd = os.open(path, flags)
    try:
        os.fsync(directory_fd)
    finally:
        os.close(directory_fd)


def _replace_json(source: str, destination: Path) -> None:
    os.replace(source, destination)


def _prepare_atomic_parent(destination: Path) -> None:
    """Persist a possibly new JSON directory before publishing into it.

    Snapshot/archive directories are created below ``state/``.  Syncing only
    the new directory after a file rename does not persist that directory's
    entry in ``state/``.  The unconditional parent barrier also repairs the
    ambiguous retry case where a prior mkdir succeeded but its barrier failed.
    """
    directory = destination.parent
    directory.mkdir(parents=True, exist_ok=True)
    _fsync_directory(directory.parent)


def _persist_replaced_entry(destination: Path) -> None:
    _fsync_directory(destination.parent)


def _ensure_existing_entry_durable(path: Path) -> None:
    """Complete an ambiguous post-replace retry before trusting the entry."""
    try:
        _persist_replaced_entry(path)
    except OSError as exc:
        raise PlanError("WORK_PLAN_DURABILITY_FAILED") from exc


def _atomic_json(path: Path, value: object) -> None:
    raw = ""
    try:
        _prepare_atomic_parent(path)
        fd, raw = tempfile.mkstemp(prefix=path.name + ".", dir=str(path.parent))
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(value, handle, ensure_ascii=False, indent=2, sort_keys=True)
            handle.write("\n")
            os.fchmod(handle.fileno(), 0o600)
            _flush_and_fsync_json(handle, path)
        _replace_json(raw, path)
        _persist_replaced_entry(path)
    except OSError as exc:
        raise PlanError("WORK_PLAN_DURABILITY_FAILED") from exc
    finally:
        try:
            if raw:
                os.unlink(raw)
        except OSError:
            pass


def _invoke_fault(fault: object | None, stage: str) -> None:
    """Invoke a selftest-only crash boundary without changing production state."""
    if fault is None:
        return
    if callable(fault):
        fault(stage)
        return
    if fault == stage:
        raise RuntimeError(f"WORK_PLAN_FAULT_INJECTED:{stage}")
    if isinstance(fault, (set, frozenset, tuple, list)) and stage in fault:
        raise RuntimeError(f"WORK_PLAN_FAULT_INJECTED:{stage}")


def _validated_journal_events(run_dir: str | Path) -> tuple[list[dict], dict]:
    """Load the journal once and turn any malformed chain into a stable hard error."""
    run = _resolve_run(run_dir)
    try:
        events = loop_journal.load_events(run)
        state = loop_journal.validate_cycle_events(events)
    except loop_journal.JournalContractError as exc:
        raise PlanError(f"WORK_PLAN_JOURNAL_INVALID:{exc.code}") from exc
    except Exception as exc:
        raise PlanError("WORK_PLAN_JOURNAL_UNREADABLE") from exc
    return events, state


def input_fingerprint(run_dir: str | Path) -> tuple[str, list[dict]]:
    """Hash semantic inputs without using mtimes or derived plan state."""
    run = _resolve_run(run_dir)
    rows: list[dict] = []
    seen: set[Path] = set()
    candidates: list[tuple[Path, str, bool]] = [
        (run / value, value, value in CONDITIONAL_CANONICAL_INPUTS)
        for value in CANONICAL_INPUTS
    ]
    candidates.extend(
        (path, path.relative_to(run).as_posix(), False)
        for path in sorted(run.glob("**/coverage.json"))
    )
    for path, logical_path, conditional in candidates:
        invalid_code = (
            "WORK_PLAN_CONDITIONAL_INPUT_INVALID"
            if conditional else "WORK_PLAN_INPUT_INVALID"
        )
        try:
            metadata = path.lstat()
        except FileNotFoundError:
            if conditional:
                rows.append({"path": logical_path, "present": False})
            continue
        except OSError as exc:
            raise PlanError(f"{invalid_code}:{logical_path}") from exc
        if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISREG(metadata.st_mode):
            raise PlanError(f"{invalid_code}:{logical_path}")
        try:
            resolved = path.resolve()
            relative = resolved.relative_to(run).as_posix()
        except (OSError, RuntimeError, ValueError) as exc:
            raise PlanError(f"{invalid_code}:{logical_path}") from exc
        if not resolved.is_file():
            raise PlanError(f"{invalid_code}:{logical_path}")
        if resolved in seen:
            continue
        seen.add(resolved)
        data = resolved.read_bytes()
        row = {
            "path": relative,
            "length": len(data),
            "sha256": hashlib.sha256(data).hexdigest(),
        }
        if conditional:
            row["present"] = True
        rows.append(row)
    rows.sort(key=lambda item: item["path"])
    return _hash(rows), rows


def _load_turn_contract(run_dir: Path) -> dict:
    path = run_dir / "state" / "turn_contract.json"
    try:
        value = json.loads(path.read_text(encoding="utf-8", errors="strict"))
    except Exception as exc:
        raise PlanError("WORK_PLAN_TURN_CONTRACT_MISSING") from exc
    if not isinstance(value, dict) or value.get("schema") != "xunji.turn_contract.v1":
        raise PlanError("WORK_PLAN_TURN_CONTRACT_INVALID")
    if value.get("mode") != "EXECUTE":
        raise PlanError("WORK_PLAN_EXECUTE_REQUIRED")
    session_id = value.get("session_id")
    prompt_sha = value.get("prompt_sha256")
    updated_at = value.get("updated_at")
    if not isinstance(session_id, str) or not session_id or len(session_id) > 1024 \
            or not isinstance(prompt_sha, str) or not _HEX64.fullmatch(prompt_sha) \
            or isinstance(updated_at, bool) \
            or not isinstance(updated_at, (int, float)) \
            or not math.isfinite(updated_at) or updated_at <= 0:
        raise PlanError("WORK_PLAN_TURN_BINDING_INVALID")
    return value


def _clean_text(value: object, *, field: str, maximum: int = 2048,
                required: bool = True) -> str:
    if not isinstance(value, str):
        raise PlanError(f"WORK_PLAN_{field.upper()}_INVALID")
    text = value.strip()
    if required and not text:
        raise PlanError(f"WORK_PLAN_{field.upper()}_REQUIRED")
    if len(text) > maximum or any(ord(char) < 32 and char not in "\t\n" for char in text):
        raise PlanError(f"WORK_PLAN_{field.upper()}_INVALID")
    return text


def normalize_lane(value: object) -> dict:
    if not isinstance(value, dict):
        raise PlanError("WORK_PLAN_LANE_OBJECT_REQUIRED")
    allowed = {
        "id", "role", "front", "effect", "assets", "dependencies",
        "expected_evidence", "expected_information_gain", "stop_condition",
        "request_cost", "request_budget", "merge_cost", "atomic",
        "capability_id",
    }
    required = allowed - {"front", "capability_id"}
    unknown = set(value) - allowed
    if unknown:
        raise PlanError("WORK_PLAN_LANE_UNKNOWN_FIELD:" + ",".join(sorted(unknown)))
    missing = required - set(value)
    if missing:
        raise PlanError("WORK_PLAN_LANE_MISSING_FIELD:" + ",".join(sorted(missing)))
    lane_id = value.get("id")
    if not isinstance(lane_id, str):
        raise PlanError("WORK_PLAN_LANE_ID_INVALID")
    lane_id = lane_id.strip()
    if not _LANE_ID.fullmatch(lane_id):
        raise PlanError("WORK_PLAN_LANE_ID_INVALID")
    effect = value.get("effect")
    if not isinstance(effect, str):
        raise PlanError("WORK_PLAN_EFFECT_INVALID")
    effect = effect.strip()
    if effect not in EFFECTS:
        raise PlanError("WORK_PLAN_EFFECT_INVALID")
    raw_capability_id = value.get("capability_id")
    capability_id = ""
    if raw_capability_id is not None:
        if not isinstance(raw_capability_id, str) \
                or raw_capability_id != raw_capability_id.strip() \
                or len(raw_capability_id) > 256 \
                or not _CAPABILITY_ID.fullmatch(raw_capability_id):
            raise PlanError("WORK_PLAN_CAPABILITY_ID_INVALID")
        capability_id = raw_capability_id
    raw_front = value.get("front", "")
    if not isinstance(raw_front, str):
        raise PlanError("WORK_PLAN_FRONT_INVALID")
    front = raw_front.strip().upper()
    if front and not _FRONT_ID.fullmatch(front):
        raise PlanError("WORK_PLAN_FRONT_INVALID")
    raw_assets = value.get("assets")
    raw_dependencies = value.get("dependencies")
    if not isinstance(raw_assets, list) or not isinstance(raw_dependencies, list):
        raise PlanError("WORK_PLAN_LANE_LIST_INVALID")
    if len(raw_assets) > 64 or len(raw_dependencies) > 16 \
            or any(not isinstance(item, str) for item in raw_assets) \
            or any(not isinstance(item, str) for item in raw_dependencies):
        raise PlanError("WORK_PLAN_LANE_LIST_INVALID")
    assets = [item.strip().lower().rstrip(".") for item in raw_assets]
    dependencies = [item.strip() for item in raw_dependencies]
    if any(not item or len(item) > 512 for item in assets) or len(set(assets)) != len(assets):
        raise PlanError("WORK_PLAN_ASSETS_INVALID")
    if any(not _LANE_ID.fullmatch(item) for item in dependencies) \
            or len(set(dependencies)) != len(dependencies) or lane_id in dependencies:
        raise PlanError("WORK_PLAN_DEPENDENCIES_INVALID")
    budget = value.get("request_budget")
    if isinstance(budget, bool) or not isinstance(budget, int) or not 0 <= budget <= 1000:
        raise PlanError("WORK_PLAN_REQUEST_BUDGET_INVALID")
    request_cost = value.get("request_cost")
    if isinstance(request_cost, bool) or not isinstance(request_cost, int) \
            or not 0 <= request_cost <= 1000 or request_cost > budget:
        raise PlanError("WORK_PLAN_REQUEST_COST_INVALID")
    information_gain = value.get("expected_information_gain")
    if not isinstance(information_gain, str):
        raise PlanError("WORK_PLAN_INFORMATION_GAIN_INVALID")
    information_gain = information_gain.strip().lower()
    if information_gain not in {"low", "medium", "high"}:
        raise PlanError("WORK_PLAN_INFORMATION_GAIN_INVALID")
    merge_cost = value.get("merge_cost")
    if isinstance(merge_cost, bool) or not isinstance(merge_cost, int) \
            or not 0 <= merge_cost <= 100:
        raise PlanError("WORK_PLAN_MERGE_COST_INVALID")
    if effect == "target" and not assets:
        raise PlanError("WORK_PLAN_TARGET_ASSET_REQUIRED")
    role = value.get("role")
    if not isinstance(role, str) or role not in CANONICAL_LANE_ROLES:
        raise PlanError("WORK_PLAN_LANE_ROLE_INVALID")
    atomic = value.get("atomic")
    if not isinstance(atomic, bool):
        raise PlanError("WORK_PLAN_ATOMIC_BOOLEAN_REQUIRED")
    return {
        "id": lane_id,
        "role": role,
        **({"front": front} if front else {}),
        "effect": effect,
        **({"capability_id": capability_id} if capability_id else {}),
        "assets": assets,
        "dependencies": dependencies,
        "expected_evidence": _clean_text(
            value.get("expected_evidence"), field="expected_evidence"),
        "expected_information_gain": information_gain,
        "stop_condition": _clean_text(
            value.get("stop_condition"), field="stop_condition"),
        "request_cost": request_cost,
        "request_budget": budget,
        "merge_cost": merge_cost,
        "atomic": atomic,
    }


def lane_by_id(plan: dict, lane_id: str) -> dict:
    """Return one exact lane from an already validated plan."""
    matches = [
        item for item in plan.get("lanes", [])
        if isinstance(item, dict) and str(item.get("id") or "") == lane_id
    ]
    if len(matches) != 1:
        raise PlanError("WORK_PLAN_LANE_NOT_UNIQUE")
    return matches[0]


def _plan_cycle_ended(run_dir: str | Path, plan: dict) -> bool:
    digest = str(plan.get("plan_digest") or "")
    if not _HEX64.fullmatch(digest):
        return False
    _, state = _validated_journal_events(run_dir)
    return digest in state.get("ended_plan_digests", [])


def lane_runtime_state(run_dir: str | Path, plan: dict, lane_id: str) -> str:
    """Project a lane's runtime state from exact plan-bound assignment attempts.

    Assignment state is derived control-plane data, not evidence.  A dependency
    becomes ready only after a matching runtime attempt has returned; prose in an
    Agent file or a hand-written ``done`` flag cannot satisfy it.
    """
    if _plan_cycle_ended(run_dir, plan):
        return "ended"
    projection = run_model.plan_cycle_projection(run_dir, plan=plan)
    matches = [
        item for item in projection.get("lane_states", [])
        if isinstance(item, dict) and item.get("lane_id") == lane_id
    ]
    if len(matches) != 1:
        return "invalid"
    state = str(matches[0].get("runtime_state") or "")
    if state == "unassigned":
        return "unassigned"
    if plan.get("execution_mode") == "ROOT_DIRECT" \
            and state in {"succeeded", "failed"}:
        # ROOT_DIRECT terminal outcomes are mechanically complete even before
        # loop_journal records the plan-bound cycle_end.  They must not fall
        # through to "assigned" and authorize the exact tool a second time.
        return "terminal"
    if state in {"returned", "failed"}:
        # A transcript-backed launch failure is a reviewable execution outcome,
        # not a hand-written success and not a permanent dependency deadlock.
        return "returned"
    if state == "running":
        return "running"
    return "assigned"


def _reviewer_dependency_current(run_dir: str | Path, plan: dict,
                                 lane_id: str) -> bool:
    """Require projection-complete Reviewer and its exact execution target.

    ``plan_cycle_projection`` is the single authenticity join over runtime,
    immutable result, Reviewer receipt, and Root disposition.  Reading the
    assignment row or merge draft directly here would reintroduce a hand-written
    shortcut and could launch the next execution before the reviewed target was
    actually disposed by Root.
    """
    if _plan_cycle_ended(run_dir, plan):
        return False
    try:
        reviewer_lane = lane_by_id(plan, lane_id)
        dependencies = [str(item) for item in reviewer_lane.get("dependencies", [])]
        if len(dependencies) != 1:
            return False
        projection = run_model.plan_cycle_projection(run_dir, plan=plan)
    except Exception:
        return False
    if projection.get("plan_digest") != plan.get("plan_digest"):
        return False
    states = {
        str(item.get("lane_id") or ""): item
        for item in projection.get("lane_states", []) if isinstance(item, dict)
    }
    reviewer_state = states.get(lane_id, {})
    target_state = states.get(dependencies[0], {})
    return bool(
        reviewer_state.get("complete") is True
        and reviewer_state.get("disposition") == "reviewed"
        and target_state.get("complete") is True
    )


def lane_dependencies_satisfied(run_dir: str | Path, plan: dict, lane: dict) -> bool:
    """Require real returns; Reviewer predecessors additionally need disposition."""
    if _plan_cycle_ended(run_dir, plan):
        return False
    for dependency in lane.get("dependencies", []):
        dep_id = str(dependency)
        if lane_runtime_state(run_dir, plan, dep_id) != "returned":
            return False
        dep_lane = lane_by_id(plan, dep_id)
        role = str(dep_lane.get("role") or "").strip().lower().replace("_", "-")
        if role in {"review", "reviewer"} \
                and not _reviewer_dependency_current(run_dir, plan, dep_id):
            return False
    return True


def _validate_dependency_dag(lanes: list[dict]) -> None:
    lane_ids = {str(lane["id"]) for lane in lanes}
    if any(str(item) not in lane_ids for lane in lanes
           for item in lane.get("dependencies", [])):
        raise PlanError("WORK_PLAN_DEPENDENCY_UNKNOWN")
    dependencies = {
        str(lane["id"]): {str(item) for item in lane.get("dependencies", [])}
        for lane in lanes
    }
    ready = sorted(key for key, values in dependencies.items() if not values)
    visited: set[str] = set()
    while ready:
        current = ready.pop(0)
        if current in visited:
            continue
        visited.add(current)
        for lane_id in sorted(dependencies):
            if current in dependencies[lane_id]:
                dependencies[lane_id].remove(current)
                if not dependencies[lane_id]:
                    ready.append(lane_id)
    if len(visited) != len(lanes):
        raise PlanError("WORK_PLAN_DEPENDENCY_CYCLE")


def _validate_reviewer_topology(mode: str, lanes: list[dict]) -> None:
    """Freeze execution -> exactly-one Reviewer -> next execution ordering."""
    if mode not in MODES:
        return
    reviewers = [
        lane for lane in lanes
        if str(lane.get("role") or "").strip().lower().replace("_", "-")
        in {"review", "reviewer"}
    ]
    if any(str(lane.get("effect") or "") != "local_verify" for lane in reviewers):
        raise PlanError("WORK_PLAN_REVIEWER_EFFECT_INVALID")
    if mode == "ROOT_DIRECT":
        return
    if any(not str(lane.get("front") or "") for lane in lanes):
        raise PlanError("WORK_PLAN_AGENT_FRONT_REQUIRED")
    by_id = {str(lane["id"]): lane for lane in lanes}
    executions = [lane for lane in lanes if lane not in reviewers]
    if not executions or not reviewers:
        raise PlanError("WORK_PLAN_REVIEWER_TOPOLOGY_REQUIRED")
    reviewer_targets: dict[str, list[str]] = {}
    for reviewer in reviewers:
        dependencies = [str(item) for item in reviewer.get("dependencies", [])]
        if len(dependencies) != 1 or dependencies[0] not in by_id \
                or by_id[dependencies[0]] in reviewers:
            raise PlanError("WORK_PLAN_REVIEWER_EXACT_EXECUTION_DEPENDENCY")
        reviewer_targets.setdefault(dependencies[0], []).append(str(reviewer["id"]))
    if any(len(reviewer_targets.get(str(lane["id"]), [])) != 1 for lane in executions):
        raise PlanError("WORK_PLAN_EXECUTION_EXACT_REVIEWER_REQUIRED")
    reviewer_ids = {str(item["id"]) for item in reviewers}
    execution_successors: dict[str, list[str]] = {
        lane_id: [] for lane_id in reviewer_ids
    }
    for execution in executions:
        dependencies = [str(item) for item in execution.get("dependencies", [])]
        if dependencies and any(item not in reviewer_ids for item in dependencies):
            raise PlanError("WORK_PLAN_EXECUTION_DEPENDS_ON_REVIEWER_REQUIRED")
        for dependency in dependencies:
            execution_successors[dependency].append(str(execution["id"]))
    if mode != "SERIAL_AGENT":
        return
    initial = [lane for lane in executions if not lane.get("dependencies")]
    if len(initial) != 1:
        raise PlanError("WORK_PLAN_SERIAL_INITIAL_EXECUTION_REQUIRED")
    for execution in executions:
        if execution is initial[0]:
            continue
        if len(execution.get("dependencies", [])) != 1:
            raise PlanError("WORK_PLAN_SERIAL_EXECUTION_EXACT_REVIEWER_DEPENDENCY")
    if any(len(successors) > 1 for successors in execution_successors.values()):
        raise PlanError("WORK_PLAN_SERIAL_REVIEWER_BRANCH_FORBIDDEN")

    # Connectedness is checked explicitly even though the normal validation path
    # also performs a DAG check.  This keeps the topology contract self-contained
    # for direct callers and prevents a detached E/R component from being treated
    # as a second implicit serial workflow.
    adjacent = {lane_id: set() for lane_id in by_id}
    for lane in lanes:
        lane_id = str(lane["id"])
        for dependency in lane.get("dependencies", []):
            dep_id = str(dependency)
            if dep_id in adjacent:
                adjacent[lane_id].add(dep_id)
                adjacent[dep_id].add(lane_id)
    reachable: set[str] = set()
    pending = [str(initial[0]["id"])]
    while pending:
        lane_id = pending.pop()
        if lane_id in reachable:
            continue
        reachable.add(lane_id)
        pending.extend(sorted(adjacent[lane_id] - reachable))
    if reachable != set(by_id):
        raise PlanError("WORK_PLAN_SERIAL_TOPOLOGY_DISCONNECTED")


def _validate_stage(stage: str, run_dir: Path, *, ignore_plan_digest: str = "") -> dict:
    try:
        projection = run_model.stage_readiness(
            run_dir, ignore_plan_digest=ignore_plan_digest)
    except Exception as exc:
        raise PlanError("WORK_PLAN_STAGE_PROJECTION_INVALID") from exc
    issues = run_model.stage_declaration_issues(stage, projection)
    if issues:
        raise PlanError("WORK_PLAN_STAGE_NOT_READY:" + ",".join(issues))
    return projection


def _validate_capability_binding(mode: str, lanes: list[dict]) -> None:
    """Bind ROOT_DIRECT to one eligible exact capability; Agents bind assignments."""
    if mode != "ROOT_DIRECT":
        if any("capability_id" in lane for lane in lanes):
            raise PlanError("WORK_PLAN_AGENT_CAPABILITY_FORBIDDEN")
        return
    if len(lanes) != 1:
        return  # The structural ROOT_DIRECT error remains the primary diagnostic.
    lane = lanes[0]
    capability_id = lane.get("capability_id")
    if not isinstance(capability_id, str) or not capability_id:
        raise PlanError("WORK_PLAN_ROOT_DIRECT_CAPABILITY_REQUIRED")
    spec = capability_registry.by_id(capability_id)
    if spec is None:
        raise PlanError("WORK_PLAN_ROOT_DIRECT_CAPABILITY_UNKNOWN")
    if spec.root_direct_eligible is not True:
        raise PlanError("WORK_PLAN_ROOT_DIRECT_CAPABILITY_INELIGIBLE")
    if spec.effect != lane.get("effect"):
        raise PlanError("WORK_PLAN_ROOT_DIRECT_CAPABILITY_EFFECT_MISMATCH")


def _validate_mode(mode: str, lanes: list[dict], run_dir: Path,
                   contract: dict) -> None:
    if mode not in MODES:
        raise PlanError("WORK_PLAN_EXECUTION_MODE_INVALID")
    _validate_reviewer_topology(mode, lanes)
    if mode != "ROOT_DIRECT" and any(
        lane["effect"] in {"control", "repo_mutation"} for lane in lanes
    ):
        raise PlanError("WORK_PLAN_AGENT_EFFECT_UNASSIGNABLE")
    ready = [lane for lane in lanes if not lane["dependencies"]]
    if mode == "ROOT_DIRECT":
        lane = lanes[0] if len(lanes) == 1 else None
        if lane is None or not lane["atomic"] or lane["request_budget"] > 1:
            raise PlanError("WORK_PLAN_ROOT_DIRECT_NOT_ATOMIC")
        if lane["effect"] in {"model_egress", "repo_mutation"}:
            raise PlanError("WORK_PLAN_ROOT_DIRECT_EFFECT_FORBIDDEN")
    elif mode == "SERIAL_AGENT":
        if len(ready) != 1:
            raise PlanError("WORK_PLAN_SERIAL_REQUIRES_ONE_READY_LANE")
    else:
        if len(ready) < 2:
            raise PlanError("WORK_PLAN_PARALLEL_REQUIRES_TWO_READY_LANES")
        for lane in ready:
            if lane["effect"] in {"control", "repo_mutation"}:
                raise PlanError("WORK_PLAN_PARALLEL_SINGLE_WRITER_EFFECT")
        target_assets: set[str] = set()
        for lane in ready:
            if lane["effect"] != "target":
                continue
            overlap = target_assets & set(lane["assets"])
            if overlap:
                raise PlanError("WORK_PLAN_PARALLEL_TARGET_OVERLAP")
            target_assets.update(lane["assets"])
    _validate_capability_binding(mode, lanes)
    try:
        fanout_required = bool(run_model.summary(run_dir).get("fanout_required"))
    except Exception as exc:
        raise PlanError("WORK_PLAN_FRONTIER_INVALID") from exc
    if fanout_required and mode != "PARALLEL_AGENTS" \
            and not bool(contract.get("fanout_override")):
        raise PlanError("WORK_PLAN_MANDATORY_FANOUT")


def _plan_digest(value: dict) -> str:
    payload = dict(value)
    payload.pop("plan_digest", None)
    payload.pop("plan_id", None)
    return _hash(payload)


def validate_plan(value: object, *, run_dir: str | Path | None = None,
                  contract: dict | None = None, check_inputs: bool = False) -> dict:
    if not isinstance(value, dict) or value.get("schema") != SCHEMA:
        raise PlanError("WORK_PLAN_SCHEMA_INVALID")
    allowed = {
        "schema", "plan_id", "cycle_id", "macro_stage", "objective",
        "inputs_digest", "replan_reason", "lanes", "execution_mode",
        "merge_owner", "exit_gate", "turn_binding", "delegation_decision",
        "committed_at", "plan_digest",
    }
    if set(value) != allowed:
        raise PlanError("WORK_PLAN_FIELDS_INVALID")
    plan = dict(value)
    mode = plan.get("execution_mode")
    if not isinstance(mode, str):
        raise PlanError("WORK_PLAN_EXECUTION_MODE_INVALID")
    if mode not in MODES:
        raise PlanError("WORK_PLAN_EXECUTION_MODE_INVALID")
    stage = plan.get("macro_stage")
    if not isinstance(stage, str):
        raise PlanError("WORK_PLAN_MACRO_STAGE_INVALID")
    if stage not in STAGES:
        raise PlanError("WORK_PLAN_MACRO_STAGE_INVALID")
    lanes_raw = plan.get("lanes")
    if not isinstance(lanes_raw, list) or not 1 <= len(lanes_raw) <= 16:
        raise PlanError("WORK_PLAN_LANES_INVALID")
    lanes = [normalize_lane(item) for item in lanes_raw]
    if lanes != lanes_raw:
        raise PlanError("WORK_PLAN_LANES_NOT_CANONICAL")
    lane_ids = [lane["id"] for lane in lanes]
    if len(set(lane_ids)) != len(lane_ids):
        raise PlanError("WORK_PLAN_LANE_ID_DUPLICATE")
    if any(dep not in set(lane_ids) for lane in lanes for dep in lane["dependencies"]):
        raise PlanError("WORK_PLAN_DEPENDENCY_UNKNOWN")
    _validate_dependency_dag(lanes)
    _validate_reviewer_topology(mode, lanes)
    _validate_capability_binding(mode, lanes)
    decision = plan.get("delegation_decision")
    if not isinstance(decision, dict) or decision.get("schema") != DECISION_SCHEMA \
            or set(decision) != {"schema", "mode", "reason", "lane_ids", "committed_at"} \
            or decision.get("mode") != mode \
            or decision.get("lane_ids") != lane_ids \
            or not isinstance(decision.get("reason"), str) \
            or _clean_text(decision.get("reason"), field="delegation_reason") \
                != decision.get("reason"):
        raise PlanError("WORK_PLAN_DELEGATION_DECISION_INVALID")
    binding = plan.get("turn_binding")
    binding_time = binding.get("contract_updated_at") if isinstance(binding, dict) else None
    if not isinstance(binding, dict) \
            or set(binding) != {"session_id", "prompt_sha256", "contract_updated_at"} \
            or not isinstance(binding.get("session_id"), str) \
            or not binding.get("session_id") or len(binding.get("session_id")) > 1024 \
            or not isinstance(binding.get("prompt_sha256"), str) \
            or not _HEX64.fullmatch(binding.get("prompt_sha256")) \
            or isinstance(binding_time, bool) \
            or not isinstance(binding_time, (int, float)) \
            or not math.isfinite(binding_time) or binding_time <= 0:
        raise PlanError("WORK_PLAN_TURN_BINDING_INVALID")
    if not isinstance(plan.get("inputs_digest"), str) \
            or not _HEX64.fullmatch(plan.get("inputs_digest")):
        raise PlanError("WORK_PLAN_INPUTS_DIGEST_INVALID")
    cycle_id = plan.get("cycle_id")
    if isinstance(cycle_id, bool) or not isinstance(cycle_id, int) or cycle_id < 1:
        raise PlanError("WORK_PLAN_CYCLE_INVALID")
    committed_at = plan.get("committed_at")
    decision_time = decision.get("committed_at")
    if isinstance(committed_at, bool) or not isinstance(committed_at, (int, float)) \
            or not math.isfinite(committed_at) or committed_at <= 0 \
            or isinstance(decision_time, bool) \
            or not isinstance(decision_time, (int, float)) \
            or not math.isfinite(decision_time) or decision_time != committed_at:
        raise PlanError("WORK_PLAN_COMMIT_TIME_INVALID")
    expected_digest = _plan_digest(plan)
    if plan.get("plan_digest") != expected_digest:
        raise PlanError("WORK_PLAN_DIGEST_MISMATCH")
    expected_id = f"WP-{cycle_id}-{expected_digest[:8]}"
    if not isinstance(plan.get("plan_id"), str) or plan.get("plan_id") != expected_id:
        raise PlanError("WORK_PLAN_ID_MISMATCH")
    for field, required in (
        ("objective", True), ("replan_reason", False), ("exit_gate", True),
    ):
        if _clean_text(plan.get(field), field=field, required=required) != plan.get(field):
            raise PlanError(f"WORK_PLAN_{field.upper()}_INVALID")
    if plan.get("merge_owner") != "Root/Single Synthesizer":
        raise PlanError("WORK_PLAN_MERGE_OWNER_INVALID")
    if run_dir is not None:
        run = _resolve_run(run_dir)
        _validate_stage(stage, run, ignore_plan_digest=str(plan.get("plan_digest") or ""))
    if run_dir is not None and contract is not None:
        run = _resolve_run(run_dir)
        _validate_mode(mode, lanes, run, contract)
        current_binding = {
            "session_id": str(contract.get("session_id") or ""),
            "prompt_sha256": str(contract.get("prompt_sha256") or ""),
            "contract_updated_at": float(contract.get("updated_at") or 0.0),
        }
        if binding != current_binding:
            raise PlanError("WORK_PLAN_TURN_STALE")
        if check_inputs and input_fingerprint(run)[0] != plan["inputs_digest"]:
            raise PlanError("WORK_PLAN_INPUTS_STALE")
    plan["lanes"] = lanes
    return plan


def load_plan(run_dir: str | Path) -> dict:
    try:
        value = json.loads(plan_path(run_dir).read_text(encoding="utf-8", errors="strict"))
    except FileNotFoundError:
        return {}
    except Exception as exc:
        raise PlanError("WORK_PLAN_UNREADABLE") from exc
    return value if isinstance(value, dict) else {}


def load_plan_snapshot(run_dir: str | Path, plan_digest: str) -> dict:
    try:
        value = json.loads(plan_snapshot_path(run_dir, plan_digest).read_text(
            encoding="utf-8", errors="strict"))
    except FileNotFoundError:
        return {}
    except Exception as exc:
        raise PlanError("WORK_PLAN_SNAPSHOT_UNREADABLE") from exc
    plan = validate_plan(value)
    if plan.get("plan_digest") != plan_digest:
        raise PlanError("WORK_PLAN_SNAPSHOT_DIGEST_MISMATCH")
    return plan


def transaction_bound_plan(run_dir: str | Path) -> dict:
    """Return the current plan only through its committed v2 receipt lineage.

    Cycle closure needs the immutable current plan/transaction/archive tuple,
    while canonical inputs are expected to evolve as the plan executes. Turn and
    input freshness remain the stronger ``current_plan`` scheduler gate below.
    """
    run = _resolve_run(run_dir)
    transaction = _load_transaction(run)
    if transaction.get("status") == "prepared":
        raise PlanError("WORK_PLAN_TRANSACTION_RECOVERY_REQUIRED")
    value = load_plan(run)
    if not value:
        raise PlanError("WORK_PLAN_REQUIRED")
    if not transaction:
        raise PlanError("WORK_PLAN_TRANSACTION_REQUIRED")
    committed = _recover_transaction(run, transaction)
    plan = validate_plan(value)
    if committed != plan:
        raise PlanError("WORK_PLAN_TRANSACTION_CURRENT_PLAN_DIVERGED")
    return plan


def current_plan(run_dir: str | Path, contract: dict) -> dict:
    run = _resolve_run(run_dir)
    committed = transaction_bound_plan(run)
    plan = validate_plan(
        committed, run_dir=run, contract=contract, check_inputs=True)
    if committed != plan:
        raise PlanError("WORK_PLAN_TRANSACTION_CURRENT_PLAN_DIVERGED")
    return plan


def _next_cycle(run_dir: Path, events: list[dict] | None = None) -> tuple[int, bool]:
    rows = events if events is not None else _validated_journal_events(run_dir)[0]
    cycles = [
        item.get("cycle") for item in rows
        if isinstance(item.get("cycle"), int) and not isinstance(item.get("cycle"), bool)
        and item.get("cycle") > 0
    ]
    cycle = max(cycles, default=0)
    current_names = [
        str(item.get("event") or "") for item in rows
        if item.get("cycle") == cycle
    ]
    incomplete = bool(
        cycle and "cycle_start" in current_names and "cycle_end" not in current_names)
    if cycle <= 0 or not incomplete:
        return cycle + 1, True
    return cycle, False


def _material_plan_view(plan: dict) -> dict:
    """Fields whose change justifies a same-stage replan."""
    decision = plan.get("delegation_decision") \
        if isinstance(plan.get("delegation_decision"), dict) else {}
    return {
        "macro_stage": plan.get("macro_stage"),
        "objective": plan.get("objective"),
        "inputs_digest": plan.get("inputs_digest"),
        "lanes": plan.get("lanes"),
        "execution_mode": plan.get("execution_mode"),
        "merge_owner": plan.get("merge_owner"),
        "exit_gate": plan.get("exit_gate"),
        "delegation_reason": decision.get("reason"),
    }


_TRANSACTION_FIELDS = {
    "schema", "status", "transaction_id", "request_digest",
    "prior_transaction_receipt_hash",
    "prior_plan_digest", "prior_event_count", "prior_tail_hash",
    "prior_events_digest", "plan", "expected_events", "event_hashes",
    "prepared_at", "committed_at", "provenance",
    "migration_source_digest", "receipt_hash",
}
_LEGACY_TRANSACTION_FIELDS = {
    "schema", "status", "transaction_id", "request_digest",
    "prior_plan_digest", "prior_event_count", "prior_tail_hash",
    "prior_events_digest", "plan", "expected_events", "event_hashes",
    "prepared_at", "committed_at", "receipt_hash",
}
_EXPECTED_EVENT_PATTERNS = {
    ("stage_plan", "delegation_committed"),
    ("cycle_start", "stage_plan", "delegation_committed"),
    ("replan", "delegation_committed"),
    ("cycle_start", "replan", "delegation_committed"),
    ("cycle_start", "stage_exit", "stage_plan", "delegation_committed"),
}


def _transaction_request_digest(*, macro_stage: str, objective: str, mode: str,
                                reason: str, exit_gate: str, lanes: list[dict],
                                replan_reason: str, binding: dict,
                                inputs_digest: str, contract: dict) -> str:
    return _hash({
        "schema": "xunji.work-plan-request.v1",
        "macro_stage": macro_stage,
        "objective": objective,
        "mode": mode,
        "reason": reason,
        "exit_gate": exit_gate,
        "lanes": lanes,
        "replan_reason": replan_reason,
        "turn_binding": binding,
        "inputs_digest": inputs_digest,
        "contract_mode": contract.get("mode"),
        "fanout_override": contract.get("fanout_override") is True,
    })


def _transaction_identity(value: dict) -> str:
    plan = value.get("plan") if isinstance(value.get("plan"), dict) else {}
    return _hash({
        "request_digest": value.get("request_digest"),
        "plan_digest": plan.get("plan_digest"),
        "prior_transaction_receipt_hash": value.get(
            "prior_transaction_receipt_hash"),
        "prior_plan_digest": value.get("prior_plan_digest"),
        "prior_event_count": value.get("prior_event_count"),
        "prior_tail_hash": value.get("prior_tail_hash"),
        "prior_events_digest": value.get("prior_events_digest"),
        "expected_events": value.get("expected_events"),
        "provenance": value.get("provenance"),
        "migration_source_digest": value.get("migration_source_digest"),
    })


def _transaction_receipt_hash(value: dict) -> str:
    unsigned = dict(value)
    unsigned.pop("receipt_hash", None)
    return _hash(unsigned)


def _legacy_migration_source_digest(value: dict) -> str:
    """Bind an admitted legacy plan to its exact pre-migration source state."""
    plan = value.get("plan") if isinstance(value.get("plan"), dict) else {}
    return _hash({
        "schema": "xunji.work-plan-legacy-source.v1",
        "plan_digest": plan.get("plan_digest"),
        "prior_event_count": value.get("prior_event_count"),
        "prior_tail_hash": value.get("prior_tail_hash"),
        "prior_events_digest": value.get("prior_events_digest"),
        "event_hashes": value.get("event_hashes"),
    })


def _seal_transaction(value: dict) -> dict:
    result = dict(value)
    result["receipt_hash"] = _transaction_receipt_hash(result)
    return result


def _write_transaction(run_dir: Path, value: dict) -> dict:
    sealed = _seal_transaction(value)
    _validate_transaction(sealed)
    _atomic_json(plan_transaction_path(run_dir), sealed)
    return sealed


def _validate_expected_events(value: object) -> list[dict]:
    if not isinstance(value, list) or tuple(
            item.get("event") if isinstance(item, dict) else None for item in value
    ) not in _EXPECTED_EVENT_PATTERNS:
        raise PlanError("WORK_PLAN_TRANSACTION_EVENTS_INVALID")
    for index, item in enumerate(value):
        if not isinstance(item, dict) or set(item) != {
                "event", "note", "data", "bindings"}:
            raise PlanError("WORK_PLAN_TRANSACTION_EVENTS_INVALID")
        if not isinstance(item["note"], str) or len(item["note"]) > 4096 \
                or not isinstance(item["data"], dict) \
                or not isinstance(item["bindings"], dict):
            raise PlanError("WORK_PLAN_TRANSACTION_EVENTS_INVALID")
        for field, source_index in item["bindings"].items():
            if field != "prior_stage_exit_hash" \
                    or isinstance(source_index, bool) \
                    or not isinstance(source_index, int) \
                    or source_index < 0 or source_index >= index \
                    or value[source_index].get("event") != "stage_exit":
                raise PlanError("WORK_PLAN_TRANSACTION_EVENTS_INVALID")
    return value


def _validate_transaction(value: object) -> dict:
    if not isinstance(value, dict) or set(value) != _TRANSACTION_FIELDS \
            or value.get("schema") != TRANSACTION_SCHEMA \
            or value.get("status") not in {"prepared", "committed"}:
        raise PlanError("WORK_PLAN_TRANSACTION_INVALID")
    for field in (
            "transaction_id", "request_digest", "prior_events_digest", "receipt_hash"):
        if not isinstance(value.get(field), str) \
                or not _HEX64.fullmatch(value[field]):
            raise PlanError("WORK_PLAN_TRANSACTION_INVALID")
    prior_receipt = value.get("prior_transaction_receipt_hash")
    prior_digest = value.get("prior_plan_digest")
    prior_tail = value.get("prior_tail_hash")
    if not isinstance(prior_receipt, str) \
            or (prior_receipt and not _HEX64.fullmatch(prior_receipt)) \
            or not isinstance(prior_digest, str) \
            or (prior_digest and not _HEX64.fullmatch(prior_digest)) \
            or not isinstance(prior_tail, str) \
            or (prior_tail and not _HEX64.fullmatch(prior_tail)):
        raise PlanError("WORK_PLAN_TRANSACTION_INVALID")
    provenance = value.get("provenance")
    migration_source = value.get("migration_source_digest")
    if provenance not in {
            "native_commit", "legacy_migration", "native_v1_upgrade"} \
            or not isinstance(migration_source, str) \
            or (provenance == "native_commit" and migration_source) \
            or (provenance == "legacy_migration"
                and (not _HEX64.fullmatch(migration_source) or prior_receipt)) \
            or (provenance == "native_v1_upgrade"
                and (not _HEX64.fullmatch(migration_source)
                     or migration_source != prior_receipt)) \
            or (provenance == "native_commit"
                and bool(prior_digest) != bool(prior_receipt)):
        raise PlanError("WORK_PLAN_TRANSACTION_PROVENANCE_INVALID")
    prior_count = value.get("prior_event_count")
    if isinstance(prior_count, bool) or not isinstance(prior_count, int) \
            or prior_count < 0 or (prior_count == 0 and prior_tail):
        raise PlanError("WORK_PLAN_TRANSACTION_INVALID")
    plan = validate_plan(value.get("plan"))
    expected = _validate_expected_events(value.get("expected_events"))
    stage_exit_index = next(
        (index for index, item in enumerate(expected)
         if item["event"] == "stage_exit"), -1)
    for index, spec in enumerate(expected):
        required_bindings = (
            {"prior_stage_exit_hash": stage_exit_index}
            if spec["event"] == "stage_plan" and stage_exit_index >= 0 else {})
        if spec["bindings"] != required_bindings:
            raise PlanError("WORK_PLAN_TRANSACTION_EVENTS_INVALID")
        if spec["event"] == "cycle_start":
            if spec["data"]:
                raise PlanError("WORK_PLAN_TRANSACTION_EVENTS_INVALID")
            continue
        try:
            rendered = _render_expected_event(spec, ["0" * 64] * index)
            loop_journal.validate_typed_event_data(
                spec["event"], rendered["data"], cycle=plan["cycle_id"])
        except (PlanError, loop_journal.JournalContractError) as exc:
            raise PlanError("WORK_PLAN_TRANSACTION_EVENTS_INVALID") from exc
    plan_event = next(
        item for item in expected if item["event"] in {"stage_plan", "replan"})
    plan_data = plan_event["data"]
    if any(plan_data.get(field) != plan[field] for field in (
            "plan_id", "plan_digest", "inputs_digest", "macro_stage")):
        raise PlanError("WORK_PLAN_TRANSACTION_EVENTS_INVALID")
    delegation = next(
        item for item in expected if item["event"] == "delegation_committed")
    if delegation["data"] != {
            "plan_digest": plan["plan_digest"],
            "lane_ids": [lane["id"] for lane in plan["lanes"]]} \
            or delegation["note"] != plan["execution_mode"]:
        raise PlanError("WORK_PLAN_TRANSACTION_EVENTS_INVALID")
    if plan_event["event"] == "replan":
        if not value.get("prior_plan_digest") \
                or plan_data.get("prior_plan_digest") != value["prior_plan_digest"]:
            raise PlanError("WORK_PLAN_TRANSACTION_EVENTS_INVALID")
    elif stage_exit_index >= 0:
        stage_exit = expected[stage_exit_index]["data"]
        if not value.get("prior_plan_digest") \
                or stage_exit.get("from_plan_digest") != value["prior_plan_digest"] \
                or stage_exit.get("next_stage") != plan["macro_stage"] \
                or stage_exit.get("transition_reason") != plan["replan_reason"]:
            raise PlanError("WORK_PLAN_TRANSACTION_EVENTS_INVALID")
    elif value.get("prior_plan_digest"):
        raise PlanError("WORK_PLAN_TRANSACTION_EVENTS_INVALID")
    hashes = value.get("event_hashes")
    if not isinstance(hashes, list) or len(hashes) > len(expected) \
            or any(not isinstance(item, str) or not _HEX64.fullmatch(item)
                   for item in hashes) \
            or len(hashes) != len(set(hashes)):
        raise PlanError("WORK_PLAN_TRANSACTION_INVALID")
    prepared_at = value.get("prepared_at")
    committed_at = value.get("committed_at")
    if isinstance(prepared_at, bool) or not isinstance(prepared_at, (int, float)) \
            or not math.isfinite(prepared_at) or prepared_at <= 0 \
            or prepared_at != plan.get("committed_at") \
            or isinstance(committed_at, bool) \
            or not isinstance(committed_at, (int, float)) \
            or not math.isfinite(committed_at) or committed_at < 0:
        raise PlanError("WORK_PLAN_TRANSACTION_INVALID")
    if value["status"] == "prepared" and committed_at != 0 \
            or value["status"] == "committed" \
            and (committed_at < prepared_at or len(hashes) != len(expected)):
        raise PlanError("WORK_PLAN_TRANSACTION_INVALID")
    if provenance == "legacy_migration" \
            and (value["status"] != "committed" \
                 or migration_source != _legacy_migration_source_digest(value)):
        raise PlanError("WORK_PLAN_TRANSACTION_PROVENANCE_INVALID")
    if provenance == "native_v1_upgrade" and value["status"] != "committed":
        raise PlanError("WORK_PLAN_TRANSACTION_PROVENANCE_INVALID")
    if value.get("transaction_id") != _transaction_identity(value):
        raise PlanError("WORK_PLAN_TRANSACTION_ID_MISMATCH")
    if value.get("receipt_hash") != _transaction_receipt_hash(value):
        raise PlanError("WORK_PLAN_TRANSACTION_RECEIPT_HASH_MISMATCH")
    result = dict(value)
    result["plan"] = plan
    result["expected_events"] = expected
    return result


def _legacy_transaction_identity(value: dict) -> str:
    plan = value.get("plan") if isinstance(value.get("plan"), dict) else {}
    return _hash({
        "request_digest": value.get("request_digest"),
        "plan_digest": plan.get("plan_digest"),
        "prior_plan_digest": value.get("prior_plan_digest"),
        "prior_event_count": value.get("prior_event_count"),
        "prior_tail_hash": value.get("prior_tail_hash"),
        "prior_events_digest": value.get("prior_events_digest"),
        "expected_events": value.get("expected_events"),
    })


def _validate_legacy_native_transaction(value: object) -> dict:
    """Validate the one exact committed native v1 shape eligible for upgrade."""
    if not isinstance(value, dict) or set(value) != _LEGACY_TRANSACTION_FIELDS \
            or value.get("schema") != LEGACY_TRANSACTION_SCHEMA:
        raise PlanError("WORK_PLAN_LEGACY_TRANSACTION_INVALID")
    if value.get("status") != "committed":
        raise PlanError("WORK_PLAN_LEGACY_TRANSACTION_NOT_COMMITTED")
    if value.get("transaction_id") != _legacy_transaction_identity(value):
        raise PlanError("WORK_PLAN_LEGACY_TRANSACTION_ID_MISMATCH")
    if value.get("receipt_hash") != _transaction_receipt_hash(value):
        raise PlanError("WORK_PLAN_LEGACY_TRANSACTION_RECEIPT_HASH_MISMATCH")
    # Reuse every v2 semantic/event/timestamp validator.  The synthetic prior
    # receipt is validation-only and never persisted or accepted as lineage.
    translated = dict(
        value, schema=TRANSACTION_SCHEMA,
        prior_transaction_receipt_hash=(
            "0" * 64 if value.get("prior_plan_digest") else ""),
        provenance="native_commit", migration_source_digest="",
    )
    translated["transaction_id"] = _transaction_identity(translated)
    translated = _seal_transaction(translated)
    validated = _validate_transaction(translated)
    result = dict(value)
    result["plan"] = validated["plan"]
    result["expected_events"] = validated["expected_events"]
    return result


def _read_transaction(run_dir: Path) -> dict:
    path = plan_transaction_path(run_dir)
    try:
        value = json.loads(path.read_text(encoding="utf-8", errors="strict"))
    except FileNotFoundError:
        return {}
    except Exception as exc:
        raise PlanError("WORK_PLAN_TRANSACTION_UNREADABLE") from exc
    if not isinstance(value, dict):
        raise PlanError("WORK_PLAN_TRANSACTION_INVALID")
    return value


def _load_transaction(run_dir: Path) -> dict:
    value = _read_transaction(run_dir)
    if not value:
        return {}
    if value.get("schema") == LEGACY_TRANSACTION_SCHEMA:
        _validate_legacy_native_transaction(value)
        raise PlanError("WORK_PLAN_TRANSACTION_UPGRADE_REQUIRED")
    return _validate_transaction(value)


def _load_transaction_archive(run_dir: Path, receipt_hash: str) -> dict:
    path = transaction_archive_path(run_dir, receipt_hash)
    try:
        value = json.loads(path.read_text(encoding="utf-8", errors="strict"))
    except FileNotFoundError as exc:
        raise PlanError("WORK_PLAN_TRANSACTION_ARCHIVE_MISSING") from exc
    except Exception as exc:
        raise PlanError("WORK_PLAN_TRANSACTION_ARCHIVE_UNREADABLE") from exc
    if not isinstance(value, dict) or value.get("receipt_hash") != receipt_hash:
        raise PlanError("WORK_PLAN_TRANSACTION_ARCHIVE_DIVERGED")
    if value.get("schema") == LEGACY_TRANSACTION_SCHEMA:
        archived = _validate_legacy_native_transaction(value)
    else:
        archived = _validate_transaction(value)
    if archived != value:
        raise PlanError("WORK_PLAN_TRANSACTION_ARCHIVE_DIVERGED")
    return archived


def _archive_transaction(run_dir: Path, value: dict) -> Path:
    if value.get("schema") == LEGACY_TRANSACTION_SCHEMA:
        transaction = _validate_legacy_native_transaction(value)
    else:
        transaction = _validate_transaction(value)
    if transaction.get("status") != "committed":
        raise PlanError("WORK_PLAN_TRANSACTION_ARCHIVE_COMMITTED_REQUIRED")
    path = transaction_archive_path(run_dir, transaction["receipt_hash"])
    if path.exists():
        if _load_transaction_archive(
                run_dir, transaction["receipt_hash"]) != transaction:
            raise PlanError("WORK_PLAN_TRANSACTION_ARCHIVE_DIVERGED")
        # A previous replace may have succeeded while its directory fsync
        # failed.  The exact retry must finish that barrier before the archive
        # can authorize publishing the committed current receipt.
        _ensure_existing_entry_durable(path)
    else:
        _atomic_json(path, transaction)
    return path


def _verify_transaction_lineage(
    run_dir: Path, transaction: dict, *, require_current_archive: bool,
) -> None:
    current = _validate_transaction(transaction)
    if require_current_archive:
        if _load_transaction_archive(
                run_dir, current["receipt_hash"]) != current:
            raise PlanError("WORK_PLAN_TRANSACTION_ARCHIVE_DIVERGED")
    seen = {current["receipt_hash"]}
    while current.get("prior_transaction_receipt_hash"):
        prior_hash = current["prior_transaction_receipt_hash"]
        if prior_hash in seen:
            raise PlanError("WORK_PLAN_TRANSACTION_LINEAGE_CYCLE")
        seen.add(prior_hash)
        if len(seen) > 1024:
            raise PlanError("WORK_PLAN_TRANSACTION_LINEAGE_TOO_DEEP")
        prior = _load_transaction_archive(run_dir, prior_hash)
        if current["provenance"] == "native_v1_upgrade":
            if prior.get("schema") != LEGACY_TRANSACTION_SCHEMA \
                    or prior.get("plan") != current.get("plan") \
                    or prior.get("request_digest") != current.get("request_digest") \
                    or prior.get("receipt_hash") \
                    != current.get("migration_source_digest"):
                raise PlanError("WORK_PLAN_TRANSACTION_V1_UPGRADE_DIVERGED")
            return
        if current["provenance"] != "native_commit" \
                or prior.get("schema") != TRANSACTION_SCHEMA \
                or prior.get("status") != "committed" \
                or prior.get("plan", {}).get("plan_digest") \
                != current.get("prior_plan_digest"):
            raise PlanError("WORK_PLAN_TRANSACTION_LINEAGE_DIVERGED")
        current = prior


def _render_expected_event(spec: dict, event_hashes: list[str]) -> dict:
    data = json.loads(json.dumps(spec["data"], ensure_ascii=False))
    for field, source_index in spec["bindings"].items():
        try:
            data[field] = event_hashes[source_index]
        except IndexError as exc:
            raise PlanError("WORK_PLAN_TRANSACTION_EVENT_BINDING_MISSING") from exc
    return {
        "event": spec["event"],
        "note": spec["note"],
        "data": data,
    }


def _event_matches_transaction(record: dict, expected: dict, *, run: Path,
                               cycle_id: int) -> bool:
    return bool(
        record.get("schema") == loop_journal.SCHEMA
        and record.get("run_dir") == str(run)
        and record.get("cycle") == cycle_id
        and record.get("event") == expected["event"]
        and record.get("note") == expected["note"]
        and record.get("data") == expected["data"]
        and isinstance(record.get("event_hash"), str)
        and _HEX64.fullmatch(record["event_hash"])
    )


def _transaction_progress(run: Path, transaction: dict) -> tuple[list[dict], list[str]]:
    events, journal_state = _validated_journal_events(run)
    prior_count = transaction["prior_event_count"]
    if len(events) < prior_count:
        raise PlanError("WORK_PLAN_TRANSACTION_JOURNAL_DIVERGED")
    prefix = events[:prior_count]
    expected_tail = transaction["prior_tail_hash"]
    actual_tail = str(prefix[-1].get("event_hash") or "") if prefix else ""
    if _hash(prefix) != transaction["prior_events_digest"] \
            or actual_tail != expected_tail:
        raise PlanError("WORK_PLAN_TRANSACTION_PRIOR_TAIL_MISMATCH")
    suffix = events[prior_count:]
    expected_specs = transaction["expected_events"]
    if len(suffix) > len(expected_specs) and transaction["status"] != "committed":
        raise PlanError("WORK_PLAN_TRANSACTION_JOURNAL_DIVERGED")
    observed: list[str] = []
    for index, record in enumerate(suffix[:len(expected_specs)]):
        expected = _render_expected_event(expected_specs[index], observed)
        if not _event_matches_transaction(
                record, expected, run=run,
                cycle_id=transaction["plan"]["cycle_id"]):
            raise PlanError("WORK_PLAN_TRANSACTION_JOURNAL_DIVERGED")
        observed.append(record["event_hash"])
    stored = transaction["event_hashes"]
    if len(stored) > len(observed) or stored != observed[:len(stored)]:
        raise PlanError("WORK_PLAN_TRANSACTION_PROGRESS_MISMATCH")
    if transaction["status"] == "committed" and len(observed) != len(expected_specs):
        raise PlanError("WORK_PLAN_TRANSACTION_INCOMPLETE")
    if transaction["status"] == "committed" \
            and (journal_state.get("active_plan_digest")
                 != transaction["plan"]["plan_digest"]
                 or journal_state.get("pending_stage_exit_hash")):
        raise PlanError("WORK_PLAN_TRANSACTION_ACTIVE_PLAN_DIVERGED")
    return events, observed


def _exact_prior_cycle_end(run: Path, plan: dict,
                           events: list[dict] | None = None,
                           *, rederive: bool = True) -> dict:
    rows, state = _validated_journal_events(run) if events is None else (
        events, loop_journal.validate_cycle_events(events))
    digest = plan["plan_digest"]
    if digest not in state.get("ended_plan_digests", []):
        raise PlanError("WORK_PLAN_STAGE_EXIT_CYCLE_END_REQUIRED")
    matches = [
        item for item in rows
        if item.get("schema") == loop_journal.SCHEMA
        and item.get("event") == "cycle_end"
        and isinstance(item.get("data"), dict)
        and item["data"].get("plan_digest") == digest
    ]
    if len(matches) != 1:
        raise PlanError("WORK_PLAN_STAGE_EXIT_CYCLE_END_NOT_UNIQUE")
    if rederive:
        data = matches[0].get("data") \
            if isinstance(matches[0].get("data"), dict) else {}
        try:
            derived = loop_journal.derive_cycle_end_data(
                run,
                plan_digest=digest,
                next_action=str(data.get("next_action") or ""),
            )
        except loop_journal.JournalContractError as exc:
            raise PlanError(f"WORK_PLAN_STAGE_EXIT_CYCLE_END_INVALID:{exc.code}") from exc
        except Exception as exc:
            raise PlanError("WORK_PLAN_STAGE_EXIT_CYCLE_END_INVALID") from exc
        if data != derived:
            raise PlanError("WORK_PLAN_STAGE_EXIT_CYCLE_END_MISMATCH")
    return matches[0]


def _expected_plan_events(*, plan: dict, prior: dict, stage_changed: bool,
                          needs_start: bool, stage_projection: dict,
                          prior_debt: dict) -> list[dict]:
    events: list[dict] = []
    if needs_start:
        events.append({
            "event": "cycle_start", "note": f"work plan {plan['plan_id']}",
            "data": {}, "bindings": {},
        })
    stage_exit_index = -1
    if stage_changed:
        stage_exit_index = len(events)
        events.append({
            "event": "stage_exit",
            "note": f"{prior['plan_id']} -> {plan['macro_stage']}",
            "data": {
                "writer": "tools/work_plan.py",
                "plan_id": prior["plan_id"],
                "from_plan_digest": prior["plan_digest"],
                "inputs_digest": prior["inputs_digest"],
                "from_stage": prior["macro_stage"],
                "next_stage": plan["macro_stage"],
                "transition_reason": plan["replan_reason"],
                "readiness_digest": stage_projection["canonical_digest"],
                "merge_debt": prior_debt,
                "merge_debt_digest": run_model.agent_debt_digest(prior_debt),
            },
            "bindings": {},
        })
    event = "replan" if prior and not stage_changed else "stage_plan"
    plan_data = {
        "writer": "tools/work_plan.py",
        "plan_id": plan["plan_id"],
        "plan_digest": plan["plan_digest"],
        "inputs_digest": plan["inputs_digest"],
        "macro_stage": plan["macro_stage"],
        **({"prior_plan_digest": prior["plan_digest"]}
           if prior and not stage_changed else {}),
    }
    bindings = {}
    if stage_exit_index >= 0:
        bindings["prior_stage_exit_hash"] = stage_exit_index
    events.append({
        "event": event, "note": plan["plan_id"], "data": plan_data,
        "bindings": bindings,
    })
    events.append({
        "event": "delegation_committed", "note": plan["execution_mode"],
        "data": {
            "plan_digest": plan["plan_digest"],
            "lane_ids": [lane["id"] for lane in plan["lanes"]],
        },
        "bindings": {},
    })
    return _validate_expected_events(events)


def _current_plan_digest_for_transaction(run: Path) -> tuple[dict, str]:
    path = plan_path(run)
    if not path.exists():
        return {}, ""
    value = load_plan(run)
    if not value:
        raise PlanError("WORK_PLAN_TRANSACTION_CURRENT_PLAN_INVALID")
    try:
        plan = validate_plan(value)
    except PlanError as exc:
        raise PlanError("WORK_PLAN_TRANSACTION_CURRENT_PLAN_INVALID") from exc
    return plan, plan["plan_digest"]


def _recover_transaction(run: Path, transaction: dict,
                         fault: object | None = None) -> dict:
    transaction = _validate_transaction(transaction)
    transaction_file = plan_transaction_path(run)
    if not transaction_file.is_file():
        raise PlanError("WORK_PLAN_TRANSACTION_MISSING")
    # Repair an ambiguous post-replace failure before the prepared/committed
    # receipt can drive any further journal or publication effects.
    _ensure_existing_entry_durable(transaction_file)
    _verify_transaction_lineage(
        run, transaction,
        require_current_archive=transaction["status"] == "committed",
    )
    plan = transaction["plan"]
    current, current_digest = _current_plan_digest_for_transaction(run)
    allowed_current = {transaction["prior_plan_digest"], plan["plan_digest"]}
    if current_digest not in allowed_current \
            or current_digest == plan["plan_digest"] and current != plan \
            or not current_digest and transaction["prior_plan_digest"]:
        raise PlanError("WORK_PLAN_TRANSACTION_CURRENT_PLAN_DIVERGED")

    _, observed = _transaction_progress(run, transaction)
    if any(spec["event"] == "stage_exit"
           for spec in transaction["expected_events"]):
        prior = load_plan_snapshot(run, transaction["prior_plan_digest"])
        if not prior and current_digest == transaction["prior_plan_digest"]:
            prior = current
        if not prior:
            raise PlanError("WORK_PLAN_TRANSACTION_PRIOR_PLAN_MISSING")
        # The prior end was re-derived before this prepared transaction was
        # written. Recovery verifies the immutable journal prefix against the
        # transaction digest; re-entering the public producer here would reject
        # the intentionally prepared successor as a non-current transaction.
        _exact_prior_cycle_end(run, prior, rederive=False)

    snapshot = plan_snapshot_path(run, plan["plan_digest"])
    if snapshot.exists():
        frozen = load_plan_snapshot(run, plan["plan_digest"])
        if frozen != plan:
            raise PlanError("WORK_PLAN_TRANSACTION_SNAPSHOT_DIVERGED")
        _ensure_existing_entry_durable(snapshot)
    elif transaction["status"] == "committed":
        raise PlanError("WORK_PLAN_TRANSACTION_SNAPSHOT_MISSING")
    else:
        _atomic_json(snapshot, plan)
        _invoke_fault(fault, "snapshot")

    while len(observed) < len(transaction["expected_events"]):
        index = len(observed)
        expected = _render_expected_event(
            transaction["expected_events"][index], observed)
        record = loop_journal.append_event(
            run, expected["event"], note=expected["note"], data=expected["data"])
        if not _event_matches_transaction(
                record, expected, run=run, cycle_id=plan["cycle_id"]):
            raise PlanError("WORK_PLAN_TRANSACTION_EVENT_APPEND_MISMATCH")
        _invoke_fault(fault, f"event:{index}:{expected['event']}")
        transaction["event_hashes"] = [*observed, record["event_hash"]]
        transaction = _write_transaction(run, transaction)
        _, observed = _transaction_progress(run, transaction)

    if transaction["status"] == "committed":
        if current_digest != plan["plan_digest"]:
            raise PlanError("WORK_PLAN_TRANSACTION_CURRENT_PLAN_DIVERGED")
        return plan

    current, current_digest = _current_plan_digest_for_transaction(run)
    if current_digest == transaction["prior_plan_digest"]:
        _atomic_json(plan_path(run), plan)
        _invoke_fault(fault, "current_plan")
    elif current_digest != plan["plan_digest"] or current != plan:
        raise PlanError("WORK_PLAN_TRANSACTION_CURRENT_PLAN_DIVERGED")
    committed = _seal_transaction(dict(
        transaction, status="committed", event_hashes=observed,
        committed_at=transaction["prepared_at"],
    ))
    committed = _validate_transaction(committed)
    _archive_transaction(run, committed)
    _invoke_fault(fault, "archive")
    committed = _write_transaction(run, committed)
    _verify_transaction_lineage(
        run, committed, require_current_archive=True)
    _invoke_fault(fault, "committed")
    return plan


def _legacy_event_sequence(run: Path, plan: dict,
                           events: list[dict]) -> tuple[int, str, list[dict], list[str]]:
    """Recover one exact historical plan-commit suffix from the typed journal."""
    matches = [
        index for index, record in enumerate(events)
        if record.get("event") in {"stage_plan", "replan"}
        and record.get("cycle") == plan["cycle_id"]
        and isinstance(record.get("data"), dict)
        and record["data"].get("plan_digest") == plan["plan_digest"]
    ]
    if len(matches) != 1:
        raise PlanError("WORK_PLAN_LEGACY_PLAN_EVENT_NOT_UNIQUE")
    plan_index = matches[0]
    plan_event = events[plan_index]
    plan_data = plan_event["data"]
    if plan_event.get("note") != plan["plan_id"] \
            or any(plan_data.get(field) != plan[field] for field in (
                "plan_id", "plan_digest", "inputs_digest", "macro_stage",
            )):
        raise PlanError("WORK_PLAN_LEGACY_PLAN_EVENT_MISMATCH")
    if plan_index + 1 >= len(events):
        raise PlanError("WORK_PLAN_LEGACY_DELEGATION_EVENT_MISSING")
    delegation = events[plan_index + 1]
    if delegation.get("event") != "delegation_committed" \
            or delegation.get("cycle") != plan["cycle_id"] \
            or delegation.get("note") != plan["execution_mode"] \
            or delegation.get("data") != {
                "plan_digest": plan["plan_digest"],
                "lane_ids": [lane["id"] for lane in plan["lanes"]],
            }:
        raise PlanError("WORK_PLAN_LEGACY_DELEGATION_EVENT_MISMATCH")

    start = plan_index
    prior_digest = ""
    stage_exit_index = -1
    if plan_event["event"] == "replan":
        prior_digest = str(plan_data.get("prior_plan_digest") or "")
    elif "prior_stage_exit_hash" in plan_data:
        if plan_index == 0:
            raise PlanError("WORK_PLAN_LEGACY_STAGE_EXIT_MISSING")
        stage_exit = events[plan_index - 1]
        if stage_exit.get("event") != "stage_exit" \
                or stage_exit.get("cycle") != plan["cycle_id"] \
                or stage_exit.get("event_hash") != plan_data["prior_stage_exit_hash"]:
            raise PlanError("WORK_PLAN_LEGACY_STAGE_EXIT_MISMATCH")
        prior_digest = str(stage_exit.get("data", {}).get("from_plan_digest") or "")
        start = plan_index - 1
        stage_exit_index = 0
    if prior_digest and not _HEX64.fullmatch(prior_digest):
        raise PlanError("WORK_PLAN_LEGACY_PRIOR_PLAN_INVALID")
    if start > 0 and events[start - 1].get("event") == "cycle_start" \
            and events[start - 1].get("cycle") == plan["cycle_id"]:
        start -= 1
        if stage_exit_index >= 0:
            stage_exit_index += 1

    selected = events[start:plan_index + 2]
    expected: list[dict] = []
    for relative_index, record in enumerate(selected):
        data = json.loads(json.dumps(record.get("data"), ensure_ascii=False))
        bindings: dict[str, int] = {}
        if record.get("event") == "stage_plan" \
                and "prior_stage_exit_hash" in data:
            if stage_exit_index < 0 \
                    or data.pop("prior_stage_exit_hash") \
                    != selected[stage_exit_index].get("event_hash"):
                raise PlanError("WORK_PLAN_LEGACY_STAGE_EXIT_MISMATCH")
            bindings["prior_stage_exit_hash"] = stage_exit_index
        expected.append({
            "event": record.get("event"),
            "note": record.get("note"),
            "data": data,
            "bindings": bindings,
        })
    expected = _validate_expected_events(expected)
    hashes = [str(record.get("event_hash") or "") for record in selected]
    if any(not _HEX64.fullmatch(item) for item in hashes):
        raise PlanError("WORK_PLAN_LEGACY_EVENT_HASH_INVALID")
    return start, prior_digest, expected, hashes


def _plan_request_digest(plan: dict, contract: dict) -> str:
    decision = plan["delegation_decision"]
    return _transaction_request_digest(
        macro_stage=plan["macro_stage"], objective=plan["objective"],
        mode=plan["execution_mode"], reason=decision["reason"],
        exit_gate=plan["exit_gate"], lanes=plan["lanes"],
        replan_reason=plan["replan_reason"], binding=plan["turn_binding"],
        inputs_digest=plan["inputs_digest"], contract=contract,
    )


def _upgrade_legacy_native_transaction(
    run: Path, value: dict, contract: dict,
) -> dict:
    """Upgrade an exact, fully anchored committed native v1 receipt to v2."""
    legacy = _validate_legacy_native_transaction(value)
    plan = validate_plan(
        legacy["plan"], run_dir=run, contract=contract, check_inputs=True)
    if plan["execution_mode"] == "ROOT_DIRECT":
        raise PlanError("WORK_PLAN_LEGACY_ROOT_DIRECT_FORBIDDEN")
    current = load_plan(run)
    if not current or validate_plan(current) != plan:
        raise PlanError("WORK_PLAN_LEGACY_TRANSACTION_CURRENT_PLAN_DIVERGED")
    if legacy["request_digest"] != _plan_request_digest(plan, contract):
        raise PlanError("WORK_PLAN_LEGACY_TRANSACTION_REQUEST_DIVERGED")
    _transaction_progress(run, legacy)
    snapshot = plan_snapshot_path(run, plan["plan_digest"])
    if not snapshot.exists():
        raise PlanError("WORK_PLAN_TRANSACTION_SNAPSHOT_MISSING")
    if load_plan_snapshot(run, plan["plan_digest"]) != plan:
        raise PlanError("WORK_PLAN_TRANSACTION_SNAPSHOT_DIVERGED")
    upgraded = {
        **legacy,
        "schema": TRANSACTION_SCHEMA,
        "transaction_id": "",
        "prior_transaction_receipt_hash": legacy["receipt_hash"],
        # The exact v1 receipt is the immutable migration intention.  Reusing
        # its frozen commit time makes archive -> current retries byte-identical.
        "committed_at": legacy["committed_at"],
        "provenance": "native_v1_upgrade",
        "migration_source_digest": legacy["receipt_hash"],
        "receipt_hash": "",
    }
    upgraded["transaction_id"] = _transaction_identity(upgraded)
    upgraded = _seal_transaction(upgraded)
    upgraded = _validate_transaction(upgraded)
    _archive_transaction(run, legacy)
    _archive_transaction(run, upgraded)
    upgraded = _write_transaction(run, upgraded)
    _verify_transaction_lineage(run, upgraded, require_current_archive=True)
    return plan


def migrate_legacy_plan(
    run_dir: str | Path, *, acknowledge_unreceipted_plan: bool = False,
    contract: dict | None = None,
) -> dict:
    """Admit one pre-transaction plan through an explicit, receipt-bound path.

    Migration does not trust the self-hash in ``work_plan.json`` alone.  It
    requires the current turn/input binding and one unique, exact typed journal
    commit sequence, freezes the plan snapshot, and writes a normal committed
    transaction whose provenance remains visibly ``legacy_migration``.
    """
    if acknowledge_unreceipted_plan is not True:
        raise PlanError("WORK_PLAN_LEGACY_MIGRATION_ACK_REQUIRED")
    run = _resolve_run(run_dir)
    if not run.is_dir() or not (run / "frontier.md").is_file():
        raise PlanError("WORK_PLAN_RUN_INVALID")
    current_contract = dict(contract or _load_turn_contract(run))
    # ROOT_DIRECT is never a migration candidate.  Perform this stable check
    # before even opening the writer lock, then repeat it under the lock below.
    preflight_transaction = _read_transaction(run)
    if preflight_transaction:
        if preflight_transaction.get("schema") == LEGACY_TRANSACTION_SCHEMA:
            preflight_plan = validate_plan(
                _validate_legacy_native_transaction(
                    preflight_transaction)["plan"],
                run_dir=run, contract=current_contract, check_inputs=True)
            if preflight_plan["execution_mode"] == "ROOT_DIRECT":
                raise PlanError("WORK_PLAN_LEGACY_ROOT_DIRECT_FORBIDDEN")
        else:
            _validate_transaction(preflight_transaction)
            raise PlanError("WORK_PLAN_LEGACY_MIGRATION_ALREADY_PROVENANCED")
    else:
        preflight_value = load_plan(run)
        if not preflight_value:
            raise PlanError("WORK_PLAN_REQUIRED")
        preflight_plan = validate_plan(
            preflight_value, run_dir=run, contract=current_contract,
            check_inputs=True)
        if preflight_plan["execution_mode"] == "ROOT_DIRECT":
            raise PlanError("WORK_PLAN_LEGACY_ROOT_DIRECT_FORBIDDEN")
    with _plan_lock(run):
        raw_transaction = _read_transaction(run)
        if raw_transaction:
            if raw_transaction.get("schema") == LEGACY_TRANSACTION_SCHEMA:
                return _upgrade_legacy_native_transaction(
                    run, raw_transaction, current_contract)
            _validate_transaction(raw_transaction)
            raise PlanError("WORK_PLAN_LEGACY_MIGRATION_ALREADY_PROVENANCED")
        value = load_plan(run)
        if not value:
            raise PlanError("WORK_PLAN_REQUIRED")
        plan = validate_plan(
            value, run_dir=run, contract=current_contract, check_inputs=True)
        if plan["execution_mode"] == "ROOT_DIRECT":
            raise PlanError("WORK_PLAN_LEGACY_ROOT_DIRECT_FORBIDDEN")
        events, journal_state = _validated_journal_events(run)
        if journal_state.get("active_plan_digest") != plan["plan_digest"] \
                or journal_state.get("pending_stage_exit_hash"):
            raise PlanError("WORK_PLAN_LEGACY_PLAN_NOT_ACTIVE")
        prior_count, prior_digest, expected, hashes = _legacy_event_sequence(
            run, plan, events)
        prefix = events[:prior_count]
        request_digest = _plan_request_digest(plan, current_contract)
        snapshot = plan_snapshot_path(run, plan["plan_digest"])
        if not snapshot.exists():
            raise PlanError("WORK_PLAN_TRANSACTION_SNAPSHOT_MISSING")
        if load_plan_snapshot(run, plan["plan_digest"]) != plan:
            raise PlanError("WORK_PLAN_TRANSACTION_SNAPSHOT_DIVERGED")
        # The frozen plan/journal/snapshot tuple is the migration intention;
        # retry time must never create a second valid committed archive.
        migrated_at = plan["committed_at"]
        transaction = {
            "schema": TRANSACTION_SCHEMA,
            "status": "committed",
            "transaction_id": "",
            "request_digest": request_digest,
            "prior_transaction_receipt_hash": "",
            "prior_plan_digest": prior_digest,
            "prior_event_count": prior_count,
            "prior_tail_hash": str(prefix[-1].get("event_hash") or "")
            if prefix else "",
            "prior_events_digest": _hash(prefix),
            "plan": plan,
            "expected_events": expected,
            "event_hashes": hashes,
            "prepared_at": plan["committed_at"],
            "committed_at": migrated_at,
            "provenance": "legacy_migration",
            "migration_source_digest": "",
            "receipt_hash": "",
        }
        transaction["migration_source_digest"] = (
            _legacy_migration_source_digest(transaction))
        transaction["transaction_id"] = _transaction_identity(transaction)
        transaction = _seal_transaction(transaction)
        transaction = _validate_transaction(transaction)
        _archive_transaction(run, transaction)
        transaction = _write_transaction(run, transaction)
        return _recover_transaction(run, transaction)


def commit_plan(run_dir: str | Path, *, macro_stage: str, objective: str,
                mode: str, reason: str, exit_gate: str, lanes: list[object],
                replan_reason: str = "", contract: dict | None = None,
                fault: object | None = None) -> dict:
    run = _resolve_run(run_dir)
    if not run.is_dir() or not (run / "frontier.md").is_file():
        raise PlanError("WORK_PLAN_RUN_INVALID")
    current_contract = dict(contract or _load_turn_contract(run))
    normalized_lanes = [normalize_lane(item) for item in lanes]
    clean_objective = _clean_text(objective, field="objective")
    clean_reason = _clean_text(reason, field="delegation_reason")
    clean_exit_gate = _clean_text(exit_gate, field="exit_gate")
    clean_replan_reason = _clean_text(
        replan_reason, field="replan_reason", required=False)
    _validate_dependency_dag(normalized_lanes)
    _validate_mode(mode, normalized_lanes, run, current_contract)
    with _plan_lock(run):
        cancellation_path = (
            run / "state" / "assignment_cancellation_transaction.json")
        if cancellation_path.exists():
            try:
                import agent_settlement
                cancellation_transaction = agent_settlement.load_transaction(run)
            except Exception as exc:
                raise PlanError(
                    "WORK_PLAN_ASSIGNMENT_CANCELLATION_INVALID") from exc
            if cancellation_transaction is not None \
                    and cancellation_transaction.get("status") == "prepared":
                raise PlanError(
                    "WORK_PLAN_ASSIGNMENT_CANCELLATION_RECOVERY_REQUIRED")
        inputs_digest, _ = input_fingerprint(run)
        binding = {
            "session_id": str(current_contract.get("session_id") or ""),
            "prompt_sha256": str(current_contract.get("prompt_sha256") or ""),
            "contract_updated_at": float(current_contract.get("updated_at") or 0.0),
        }
        request_digest = _transaction_request_digest(
            macro_stage=macro_stage, objective=clean_objective, mode=mode,
            reason=clean_reason, exit_gate=clean_exit_gate,
            lanes=normalized_lanes, replan_reason=clean_replan_reason,
            binding=binding, inputs_digest=inputs_digest,
            contract=current_contract,
        )
        transaction = _load_transaction(run)
        prior_transaction_receipt_hash = ""
        if transaction:
            if transaction["status"] == "prepared":
                if transaction["request_digest"] != request_digest:
                    raise PlanError("WORK_PLAN_TRANSACTION_PENDING_MISMATCH")
                return _recover_transaction(run, transaction, fault=fault)
            committed_plan = _recover_transaction(run, transaction)
            if transaction["request_digest"] == request_digest:
                return committed_plan
            prior_transaction_receipt_hash = transaction["receipt_hash"]
        elif plan_path(run).exists():
            # A self-consistent work_plan.json is not transaction provenance.
            # Existing pre-transaction runs must pass through the explicit
            # migrate-legacy command so their exact journal source is frozen.
            raise PlanError("WORK_PLAN_TRANSACTION_REQUIRED")

        events, _ = _validated_journal_events(run)
        prior = load_plan(run)
        if prior:
            prior = validate_plan(prior)
        prior_digest = str(prior.get("plan_digest") or "") if prior else ""
        stage_projection = _validate_stage(
            macro_stage, run, ignore_plan_digest=prior_digest)
        cycle_id, needs_start = _next_cycle(run, events)
        committed_at = time.time()
        plan = {
            "schema": SCHEMA,
            "plan_id": "",
            "cycle_id": cycle_id,
            "macro_stage": macro_stage,
            "objective": clean_objective,
            "inputs_digest": inputs_digest,
            "replan_reason": clean_replan_reason,
            "lanes": normalized_lanes,
            "execution_mode": mode,
            "merge_owner": "Root/Single Synthesizer",
            "exit_gate": clean_exit_gate,
            "turn_binding": binding,
            "delegation_decision": {
                "schema": DECISION_SCHEMA,
                "mode": mode,
                "reason": clean_reason,
                "lane_ids": [lane["id"] for lane in normalized_lanes],
                "committed_at": committed_at,
            },
            "committed_at": committed_at,
            "plan_digest": "",
        }
        plan["plan_digest"] = _plan_digest(plan)
        plan["plan_id"] = f"WP-{cycle_id}-{plan['plan_digest'][:8]}"
        plan = validate_plan(
            plan, run_dir=run, contract=current_contract, check_inputs=True)
        prior_stage = str(prior.get("macro_stage") or "") if prior else ""
        stage_changed = bool(prior and prior_stage != macro_stage)
        if prior and not plan["replan_reason"]:
            raise PlanError("WORK_PLAN_REPLAN_REASON_REQUIRED")
        if prior and not stage_changed \
                and _material_plan_view(prior) == _material_plan_view(plan):
            raise PlanError("WORK_PLAN_REPLAN_NOT_MATERIAL")
        prior_projection = run_model.plan_cycle_projection(run, plan=prior) if prior else {}
        prior_debt = prior_projection.get("debt") \
            if isinstance(prior_projection.get("debt"), dict) else {}
        if stage_changed:
            if prior_debt.get("merge") or prior_debt.get("review"):
                raise PlanError("WORK_PLAN_STAGE_EXIT_AGENT_DEBT")
            _exact_prior_cycle_end(run, prior, events)
        elif prior and prior_projection.get("assigned_debt"):
            raise PlanError("WORK_PLAN_REPLAN_ASSIGNMENT_DEBT")
        expected_events = _expected_plan_events(
            plan=plan, prior=prior, stage_changed=stage_changed,
            needs_start=needs_start, stage_projection=stage_projection,
            prior_debt=prior_debt,
        )
        transaction = {
            "schema": TRANSACTION_SCHEMA,
            "status": "prepared",
            "transaction_id": "",
            "request_digest": request_digest,
            "prior_transaction_receipt_hash": prior_transaction_receipt_hash,
            "prior_plan_digest": prior_digest,
            "prior_event_count": len(events),
            "prior_tail_hash": str(events[-1].get("event_hash") or "")
            if events else "",
            "prior_events_digest": _hash(events),
            "plan": plan,
            "expected_events": expected_events,
            "event_hashes": [],
            "prepared_at": committed_at,
            "committed_at": 0.0,
            "provenance": "native_commit",
            "migration_source_digest": "",
            "receipt_hash": "",
        }
        transaction["transaction_id"] = _transaction_identity(transaction)
        transaction = _seal_transaction(transaction)
        transaction = _validate_transaction(transaction)
        # This receipt is the first side effect. Recovery never guesses a new
        # timestamp or plan digest after journal progress has started.
        transaction = _write_transaction(run, transaction)
        _invoke_fault(fault, "prepared")
        return _recover_transaction(run, transaction, fault=fault)


def _parse_lane_json(raw: str) -> dict:
    try:
        value = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise argparse.ArgumentTypeError(f"invalid lane JSON: {exc}") from exc
    if not isinstance(value, dict):
        raise argparse.ArgumentTypeError("lane JSON must be an object")
    return value


def _selftest_legacy() -> int:
    root = Path(tempfile.mkdtemp())
    run = root / "run"
    (run / "state").mkdir(parents=True)
    (run / "target.md").write_text(
        "# Target\n- Authorized scope: app.example\n", encoding="utf-8")
    (run / "coverage.json").write_text(json.dumps({
        "assets": [{"host": "app.example", "examined": False}],
    }), encoding="utf-8")
    (run / "frontier.md").write_text(
        "# Frontier\n\n## Open Fronts\n\n### F-001 — auth\n"
        "- Status: open\n- Barrier class: auth-layer\n- Current depth: shallow\n",
        encoding="utf-8",
    )
    contract = {
        "schema": "xunji.turn_contract.v1",
        "mode": "EXECUTE",
        "session_id": "session-work-plan",
        "prompt_sha256": "a" * 64,
        "updated_at": time.time(),
        "fanout_override": False,
    }
    _atomic_json(run / "state" / "turn_contract.json", contract)
    serial_lane = {
        "id": "L-F001-HUNTER",
        "role": "web-hunter",
        "front": "F-001",
        "effect": "target",
        "assets": ["app.example"],
        "dependencies": [],
        "expected_evidence": "control-backed response artifact",
        "expected_information_gain": "high",
        "stop_condition": "candidate confirmed or refuted",
        "request_cost": 2,
        "request_budget": 3,
        "merge_cost": 20,
        "atomic": False,
    }
    s1_plan = commit_plan(
        run, macro_stage="S1", objective="inventory auth surface",
        mode="SERIAL_AGENT", reason="one complex dependent lane",
        exit_gate="hunter result reviewed", lanes=[serial_lane], contract=contract,
    )
    s2_plan = commit_plan(
        run, macro_stage="S2", objective="test auth front",
        mode="SERIAL_AGENT", reason="one complex dependent lane",
        exit_gate="hunter result reviewed", lanes=[serial_lane], contract=contract,
        replan_reason="scope and coverage inventory are ready",
    )
    (run / "frontier.md").write_text(
        "# Frontier\n\n## Closed Fronts\n\n### F-001 — auth\n"
        "- Status: blocked_type_b\n- Barrier class: auth-layer\n"
        "- Current depth: moderate\n",
        encoding="utf-8",
    )
    s3_plan = commit_plan(
        run, macro_stage="S3", objective="verify closure parity",
        mode="SERIAL_AGENT", reason="one bounded closure verification lane",
        exit_gate="closure debt remains zero", lanes=[serial_lane], contract=contract,
        replan_reason="all active fronts are settled",
    )
    events = loop_journal.load_events(run)
    stage_events = [item for item in events if item.get("event") in {
        "stage_plan", "stage_exit", "replan",
    }]
    checks: list[tuple[str, bool]] = [
        ("plan file exists", plan_path(run).is_file()),
        ("current plan validates", current_plan(run, contract)["plan_id"] == s3_plan["plan_id"]),
        ("delegation decision is bound",
         s1_plan["delegation_decision"]["mode"] == "SERIAL_AGENT"),
        ("journal records plan and decision", {
            "cycle_start", "stage_plan", "delegation_committed",
        }.issubset({item.get("event") for item in loop_journal.load_events(run)})),
        ("S1 to S2 to S3 writes exit before each new stage plan",
         [item.get("event") for item in stage_events[:5]] == [
             "stage_plan", "stage_exit", "stage_plan", "stage_exit", "stage_plan",
         ]),
        ("stage plan binds the immediately prior exit hash",
         stage_events[2].get("data", {}).get("prior_stage_exit_hash")
         == stage_events[1].get("event_hash")
         and stage_events[4].get("data", {}).get("prior_stage_exit_hash")
         == stage_events[3].get("event_hash")),
        ("stage exit binds the prior plan digest and zero merge debt",
         stage_events[1].get("data", {}).get("from_plan_digest") == s1_plan["plan_digest"]
         and stage_events[3].get("data", {}).get("from_plan_digest") == s2_plan["plan_digest"]
         and stage_events[3].get("data", {}).get("merge_debt")
         == {"merge": [], "review": []}),
    ]

    # Macro-stage is explicitly reversible.  A new active front can send S3
    # back to S2; a lost coverage prerequisite can send S2 back to S1.
    (run / "frontier.md").write_text(
        "# Frontier\n\n## Open Fronts\n\n### F-001 — reopened\n"
        "- Status: open\n- Barrier class: auth-layer\n- Current depth: moderate\n",
        encoding="utf-8",
    )
    fallback_s2 = commit_plan(
        run, macro_stage="S2", objective="re-open material auth gap",
        mode="SERIAL_AGENT", reason="one reopened front",
        exit_gate="reopened front adjudicated", lanes=[serial_lane], contract=contract,
        replan_reason="closure review reopened F-001",
    )
    (run / "coverage.json").unlink()
    fallback_s1 = commit_plan(
        run, macro_stage="S1", objective="rebuild lost coverage inventory",
        mode="SERIAL_AGENT", reason="one inventory recovery lane",
        exit_gate="coverage ledger restored", lanes=[serial_lane], contract=contract,
        replan_reason="coverage ledger became unavailable",
    )
    checks += [
        ("S3 can explicitly fall back to S2", fallback_s2["macro_stage"] == "S2"),
        ("S2 can explicitly fall back to S1", fallback_s1["macro_stage"] == "S1"),
    ]

    same_stage = commit_plan(
        run, macro_stage="S1", objective="rebuild coverage inventory and source map",
        mode="SERIAL_AGENT", reason="one inventory recovery lane",
        exit_gate="coverage ledger restored", lanes=[serial_lane], contract=contract,
        replan_reason="inventory objective materially expanded",
    )
    checks.append(("same-stage material change writes replan",
                   loop_journal.load_events(run)[-2].get("event") == "replan"
                   and same_stage["macro_stage"] == "S1"))
    nonmaterial_rejected = False
    try:
        commit_plan(
            run, macro_stage="S1", objective="rebuild coverage inventory and source map",
            mode="SERIAL_AGENT", reason="one inventory recovery lane",
            exit_gate="coverage ledger restored", lanes=[serial_lane], contract=contract,
            replan_reason="prose-only retry",
        )
    except PlanError as exc:
        nonmaterial_rejected = str(exc) == "WORK_PLAN_REPLAN_NOT_MATERIAL"
    checks.append(("prose-only same-stage replan is rejected", nonmaterial_rejected))

    (run / "evidence.md").write_text("# changed\n", encoding="utf-8")
    stale = False
    try:
        current_plan(run, contract)
    except PlanError as exc:
        stale = str(exc) == "WORK_PLAN_INPUTS_STALE"
    checks.append(("canonical change invalidates plan", stale))

    # Restore S2 prerequisites for the remaining fail-closed shape checks.
    (run / "coverage.json").write_text(json.dumps({
        "assets": [{"host": "app.example", "examined": False}],
    }), encoding="utf-8")
    direct_bad = False
    try:
        commit_plan(
            run, macro_stage="S2", objective="bad direct",
            mode="ROOT_DIRECT", reason="not atomic", exit_gate="one result",
            lanes=[serial_lane], contract=contract,
        )
    except PlanError as exc:
        direct_bad = str(exc) == "WORK_PLAN_ROOT_DIRECT_NOT_ATOMIC"
    checks.append(("complex lane cannot claim root direct", direct_bad))
    overlap_bad = False
    parallel = [dict(serial_lane, id="L-A"), dict(serial_lane, id="L-B")]
    try:
        commit_plan(
            run, macro_stage="S2", objective="bad parallel",
            mode="PARALLEL_AGENTS", reason="two lanes", exit_gate="both return",
            lanes=parallel, contract=contract,
        )
    except PlanError as exc:
        overlap_bad = str(exc) == "WORK_PLAN_PARALLEL_TARGET_OVERLAP"
    checks.append(("same-asset target lanes cannot parallelize", overlap_bad))

    open_s3_blocked = False
    try:
        commit_plan(
            run, macro_stage="S3", objective="premature closure",
            mode="SERIAL_AGENT", reason="one lane", exit_gate="close",
            lanes=[serial_lane], contract=contract, replan_reason="claim closure",
        )
    except PlanError as exc:
        open_s3_blocked = str(exc).startswith("WORK_PLAN_STAGE_NOT_READY:") \
            and "OPEN_FRONTS_PRESENT" in str(exc)
    checks.append(("open front blocks an S3 declaration", open_s3_blocked))

    (run / "frontier.md").write_text(
        "# Frontier\n\n## Closed Fronts\n\n### F-001 — settled\n"
        "- Status: blocked_type_b\n- Barrier class: auth-layer\n"
        "- Current depth: moderate\n",
        encoding="utf-8",
    )
    _atomic_json(run / "state" / "assignments.json", {
        "schema": 3, "assignments": [{
            "agent": "A-hunter-debt", "role": "hunter", "status": "done",
            "plan_digest": same_stage["plan_digest"], "lane_id": "L-F001-HUNTER",
            "attempts": [{"state": "returned", "agent_id": "child-debt",
                          "tool_use_id": "tool-debt"}],
        }],
    })
    debt_s3_blocked = False
    try:
        commit_plan(
            run, macro_stage="S3", objective="premature closure with Agent debt",
            mode="SERIAL_AGENT", reason="one lane", exit_gate="close",
            lanes=[serial_lane], contract=contract, replan_reason="claim closure",
        )
    except PlanError as exc:
        debt_s3_blocked = str(exc).startswith("WORK_PLAN_STAGE_NOT_READY:") \
            and "PLAN_BOUND_AGENT_MERGE_DEBT" in str(exc) \
            and "PLAN_BOUND_AGENT_REVIEW_DEBT" in str(exc)
    checks.append(("unmerged/unreviewed plan-bound Agent blocks S3", debt_s3_blocked))

    cyclic = [
        dict(serial_lane, id="L-CYCLE-A", dependencies=["L-CYCLE-B"]),
        dict(serial_lane, id="L-CYCLE-B", dependencies=["L-CYCLE-A"]),
    ]
    cycle_rejected = False
    try:
        commit_plan(
            run, macro_stage="S2", objective="cyclic plan",
            mode="SERIAL_AGENT", reason="bad graph", exit_gate="never",
            lanes=cyclic, contract=contract, replan_reason="graph change",
        )
    except PlanError as exc:
        cycle_rejected = str(exc) == "WORK_PLAN_DEPENDENCY_CYCLE"
    checks.append(("dependency DAG cycle is rejected", cycle_rejected))

    delegated_control = dict(
        serial_lane, id="L-CONTROL", effect="control", assets=[],
        request_cost=0, request_budget=0,
    )
    unassignable_rejected = False
    try:
        commit_plan(
            run, macro_stage="S2", objective="delegated control",
            mode="SERIAL_AGENT", reason="bad effect", exit_gate="never",
            lanes=[delegated_control], contract=contract, replan_reason="effect change",
        )
    except PlanError as exc:
        unassignable_rejected = str(exc) == "WORK_PLAN_AGENT_EFFECT_UNASSIGNABLE"
    checks.append(("Agent plans reject control/repo-mutation effects",
                   unassignable_rejected))

    # A returned Reviewer does not unlock a successor until its disposition is
    # bound to the frozen target result digest.
    dep_plan = {
        "plan_digest": "b" * 64,
        "lanes": [{"id": "L-REVIEW", "role": "review", "dependencies": []},
                  {"id": "L-NEXT", "role": "hunter",
                   "dependencies": ["L-REVIEW"]}],
    }
    reviewer_row = {
        "agent": "A-review-001", "role": "review", "status": "done",
        "plan_digest": dep_plan["plan_digest"], "lane_id": "L-REVIEW",
        "reviews_assignments": ["A-target-001"],
        "attempts": [{"state": "returned", "agent_id": "review-child",
                      "tool_use_id": "review-tool"}],
    }
    _atomic_json(run / "state" / "assignments.json", {
        "schema": 3, "assignments": [reviewer_row],
    })
    review_return_only = lane_dependencies_satisfied(
        run, dep_plan, dep_plan["lanes"][1])
    result_digest = "c" * 64
    draft_dir = run / "state" / "merge_drafts"
    draft_dir.mkdir(parents=True, exist_ok=True)
    _atomic_json(draft_dir / "A-target-001.json", {
        "schema": "xunji.merge-draft.v1", "assignment": "A-target-001",
        "plan_digest": dep_plan["plan_digest"], "result_digest": result_digest,
        "review_status": "complete", "review_receipt": {
            "schema": "xunji.review-disposition.v1",
            "reviewer_assignment": "A-review-001",
            "target_result_digest": result_digest,
            "reviewer_result_digest": "d" * 64,
            "plan_digest": dep_plan["plan_digest"],
        },
    })
    reviewer_row["status"] = "reviewed"
    _atomic_json(run / "state" / "assignments.json", {
        "schema": 3, "assignments": [reviewer_row],
    })
    reviewed_dependency = lane_dependencies_satisfied(
        run, dep_plan, dep_plan["lanes"][1])
    checks += [
        ("Reviewer return alone does not unlock its successor", not review_return_only),
        ("current Reviewer disposition unlocks its successor", reviewed_dependency),
    ]
    bad = [name for name, ok in checks if not ok]
    for name, ok in checks:
        print(("ok   " if ok else "FAIL ") + name)
    print("work_plan selftest " + ("passed" if not bad else f"FAILED ({len(bad)})"))
    return 0 if not bad else 1


def _selftest() -> int:
    """Exercise the receipt-bound plan/cycle closure, including former bypasses."""
    # Direct ``python tools/work_plan.py --selftest`` runs this module as
    # ``__main__``.  Bind the canonical import name before workers and the shared
    # settlement service load it, otherwise two module instances can project
    # different in-memory contract owners during the same fixture.
    sys.modules["work_plan"] = sys.modules[__name__]
    import runtime_receipts
    import workers
    from unittest import mock

    root = Path(tempfile.mkdtemp())

    def make_run(name: str) -> tuple[Path, dict]:
        run = root / name
        (run / "state").mkdir(parents=True)
        (run / "target.md").write_text(
            "# Target\n- Authorized scope: app.example\n", encoding="utf-8")
        (run / "coverage.json").write_text(json.dumps({
            "assets": [{"host": "app.example", "examined": False}],
        }), encoding="utf-8")
        (run / "frontier.md").write_text(
            "# Frontier\n\n## Open Fronts\n\n### F-001 — auth\n"
            "- Status: open\n- Barrier class: auth-layer\n"
            "- Current depth: shallow\n",
            encoding="utf-8",
        )
        contract = {
            "schema": "xunji.turn_contract.v1", "mode": "EXECUTE",
            "session_id": f"session-{name}", "prompt_sha256": "a" * 64,
            "updated_at": time.time(), "fanout_override": False,
        }
        _atomic_json(run / "state" / "turn_contract.json", contract)
        return run, contract

    def lane_pair(tag: str) -> list[dict]:
        execution = {
            "id": f"L-{tag}-EXEC", "role": "web-hunter", "front": "F-001",
            "effect": "local_read", "assets": [], "dependencies": [],
            "expected_evidence": "bounded structured result",
            "expected_information_gain": "medium",
            "stop_condition": "result returned or launch failure recorded",
            "request_cost": 0, "request_budget": 0, "merge_cost": 2,
            "atomic": False,
        }
        reviewer = {
            "id": f"L-{tag}-REVIEW", "role": "review", "front": "F-001",
            "effect": "local_verify", "assets": [],
            "dependencies": [execution["id"]],
            "expected_evidence": "digest-bound disposition",
            "expected_information_gain": "medium",
            "stop_condition": "target result accepted or challenged",
            "request_cost": 0, "request_budget": 0, "merge_cost": 2,
            "atomic": False,
        }
        return [execution, reviewer]

    sequence = 0

    def append_agent_tool_use(
        path: Path, tool_id: str, prompt: str, subagent_type: str,
    ) -> None:
        with path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps({
                "message": {"role": "assistant", "content": [{
                    "type": "tool_use", "id": tool_id, "name": "Agent",
                    "input": {
                        "prompt": prompt,
                        "subagent_type": subagent_type,
                    },
                }]},
            }) + "\n")

    def append_agent_tool_result(path: Path, tool_id: str, result: str) -> None:
        with path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps({
                "message": {"content": [{
                    "type": "tool_result", "tool_use_id": tool_id,
                    "content": [{"type": "text", "text": result}],
                }]},
            }) + "\n")

    def settle_plan(run: Path, plan: dict, *, failed: bool = False) -> dict:
        nonlocal sequence
        sequence += 1
        execution, reviewer_lane = plan["lanes"]
        target = workers.create_agent_assignment(
            run, role="web-hunter", front="F-001", assets=[],
            lane_id=execution["id"])
        target_tool = f"target-tool-{sequence}"
        reviewer_tool = f"review-tool-{sequence}"
        trace = root / f"transcript-{sequence}.jsonl"
        trace.write_text("", encoding="utf-8")
        target_prompt = runtime_receipts.assignment_launch_prompt(target)
        target_type = runtime_receipts.assignment_subagent_type(target)
        assert target_prompt
        assert target_type == "xunji-hunter"
        append_agent_tool_use(trace, target_tool, target_prompt, target_type)
        target_result = f"REAL TARGET RESULT {sequence}"
        if not failed:
            runtime_receipts.append_hook_event(run, {
                "hook_event_name": "SubagentStart",
                "session_id": f"runtime-{sequence}",
                "transcript_path": str(trace),
                "agent_id": f"target-child-{sequence}",
                "agent_type": target_type,
            })
            runtime_receipts.append_hook_event(run, {
                "hook_event_name": "SubagentStop",
                "session_id": f"runtime-{sequence}",
                "transcript_path": str(trace),
                "agent_id": f"target-child-{sequence}",
                "agent_type": target_type,
                "last_assistant_message": target_result,
            })
            append_agent_tool_result(trace, target_tool, target_result)
        runtime_receipts.append_hook_event(run, {
            "hook_event_name": "PostToolUseFailure" if failed else "PostToolUse",
            "session_id": f"runtime-{sequence}", "transcript_path": str(trace),
            "tool_name": "Agent", "tool_use_id": target_tool,
            "tool_input": {
                "prompt": target_prompt,
                "subagent_type": target_type,
            },
            "tool_response": (
                {"error": "Agent launch failed before execution"} if failed else
                [{"type": "text", "text": target_result}]
            ),
        })
        draft = json.loads(runtime_receipts.merge_draft_path(
            run, target["agent"]).read_text(encoding="utf-8"))
        frozen_path = Path(draft["result"]["path"])
        frozen_before = frozen_path.read_bytes()
        target_file_before_finish = Path(target["agent_file"])
        if not target_file_before_finish.is_absolute():
            target_file_before_finish = ROOT / target_file_before_finish
        scaffold_before = target_file_before_finish.read_bytes()
        assert frozen_before != scaffold_before
        assert (b"REAL TARGET RESULT" in frozen_before) is (not failed)

        reviewer = workers.create_agent_assignment(
            run, role="review", front="F-001", assets=[],
            lane_id=reviewer_lane["id"])
        reviewer_prompt = runtime_receipts.assignment_launch_prompt(reviewer)
        reviewer_type = runtime_receipts.assignment_subagent_type(reviewer)
        assert reviewer_prompt
        assert reviewer_type == "xunji-reviewer"
        reviewer_result = f"REVIEWED {reviewer['review_result_digest']}"
        append_agent_tool_use(
            trace, reviewer_tool, reviewer_prompt, reviewer_type)
        runtime_receipts.append_hook_event(run, {
            "hook_event_name": "SubagentStart",
            "session_id": f"runtime-{sequence}",
            "transcript_path": str(trace),
            "agent_id": f"review-child-{sequence}",
            "agent_type": reviewer_type,
        })
        runtime_receipts.append_hook_event(run, {
            "hook_event_name": "SubagentStop",
            "session_id": f"runtime-{sequence}",
            "transcript_path": str(trace),
            "agent_id": f"review-child-{sequence}",
            "agent_type": reviewer_type,
            "last_assistant_message": reviewer_result,
        })
        append_agent_tool_result(trace, reviewer_tool, reviewer_result)
        runtime_receipts.append_hook_event(run, {
            "hook_event_name": "PostToolUse", "session_id": f"runtime-{sequence}",
            "transcript_path": str(trace), "tool_name": "Agent",
            "tool_use_id": reviewer_tool, "tool_input": {
                "prompt": reviewer_prompt,
                "subagent_type": reviewer_type,
            },
            "tool_response": [{"type": "text", "text": reviewer_result}],
        })
        receipt = workers.record_review_disposition(
            run, target=target["agent"], reviewer=reviewer["agent"],
            disposition="blocked" if failed else "accept-candidate",
            note="exact frozen result and control disposition reviewed",
        )
        workers.update_agent_lifecycle(
            run, target["agent"], status="failed" if failed else "merged",
            note=("Reason: Agent launch failure; Front: F-001"
                  if failed else "Front: F-001"),
            terminal=True, amend=failed,
        )
        projection = run_model.plan_cycle_projection(run, plan=plan)
        assert projection["debt"] == {"merge": [], "review": []}
        assert frozen_path.read_bytes() == frozen_before
        assert target_file_before_finish.read_bytes() != scaffold_before
        return {
            "target": target, "reviewer": reviewer, "receipt": receipt,
            "frozen_path": frozen_path, "frozen_bytes": frozen_before,
            "projection": projection,
        }

    checks: list[tuple[str, bool]] = []

    # Conditional canonical inputs have an explicit absence row.  Therefore
    # missing -> present, content mutation, and present -> missing all stale an
    # already committed plan instead of disappearing from the digest input.
    absence_run, _ = make_run("conditional-absence-binding")
    absence_digest, absence_rows = input_fingerprint(absence_run)
    repeated_absence_digest, repeated_absence_rows = input_fingerprint(absence_run)
    missing_rows = {
        row.get("path"): row for row in absence_rows
        if row.get("path") in CONDITIONAL_CANONICAL_INPUTS
    }
    checks.append((
        "conditional canonical absence is explicit and deterministic",
        absence_digest == repeated_absence_digest
        and absence_rows == repeated_absence_rows
        and missing_rows == {
            "chains.md": {"path": "chains.md", "present": False},
            "hints.md": {"path": "hints.md", "present": False},
        },
    ))
    semantic_reversion_path = absence_run / "hints.md"
    semantic_reversion_path.write_text("# transient hint\n", encoding="utf-8")
    semantic_present_digest, _ = input_fingerprint(absence_run)
    semantic_reversion_path.unlink()
    semantic_reverted_digest, semantic_reverted_rows = input_fingerprint(absence_run)
    checks.append((
        "conditional digest is semantic state: exact create-delete reverts to absence",
        semantic_present_digest != absence_digest
        and semantic_reverted_digest == absence_digest
        and semantic_reverted_rows == absence_rows,
    ))
    symlink_run, _ = make_run("conditional-symlink-fail-closed")
    escaping_hint = symlink_run.parent / "outside-hints.md"
    escaping_hint.write_text("# external hint\n", encoding="utf-8")
    (symlink_run / "hints.md").symlink_to(escaping_hint)
    symlink_error = ""
    try:
        input_fingerprint(symlink_run)
    except PlanError as exc:
        symlink_error = str(exc)
    checks.append((
        "conditional symlink cannot disappear from the input digest",
        symlink_error == "WORK_PLAN_CONDITIONAL_INPUT_INVALID:hints.md",
    ))
    conflict_symlink_run, _ = make_run("conflict-symlink-fail-closed")
    escaping_conflicts = conflict_symlink_run.parent / "outside-conflicts.json"
    escaping_conflicts.write_text(
        '{"schema":1,"generated_at":"2026-07-18T00:00:00Z",'
        '"conflict_types":[],"conflicts":[]}\n',
        encoding="utf-8",
    )
    (conflict_symlink_run / "state" / "conflicts.json").symlink_to(
        escaping_conflicts)
    conflict_symlink_error = ""
    try:
        input_fingerprint(conflict_symlink_run)
    except PlanError as exc:
        conflict_symlink_error = str(exc)
    checks.append((
        "conflict projection symlink cannot escape the plan input digest",
        conflict_symlink_error
        == "WORK_PLAN_INPUT_INVALID:state/conflicts.json",
    ))
    for conditional_name in sorted(CONDITIONAL_CANONICAL_INPUTS):
        for operation in ("create", "modify", "delete"):
            conditional_run, conditional_contract = make_run(
                f"conditional-{conditional_name[:-3]}-{operation}")
            conditional_path = conditional_run / conditional_name
            if operation in {"modify", "delete"}:
                conditional_path.write_text(
                    f"# {conditional_name}\n\nbefore\n", encoding="utf-8")
            conditional_plan = commit_plan(
                conditional_run, macro_stage="S1",
                objective=f"bind {conditional_name} before {operation}",
                mode="SERIAL_AGENT", reason="execution then exact Reviewer",
                exit_gate="conditional input remains bound",
                lanes=lane_pair(
                    f"COND{conditional_name[0].upper()}{operation[0].upper()}"),
                contract=conditional_contract,
            )
            if operation == "create":
                conditional_path.write_text(
                    f"# {conditional_name}\n\ncreated\n", encoding="utf-8")
            elif operation == "modify":
                conditional_path.write_text(
                    f"# {conditional_name}\n\nafter\n", encoding="utf-8")
            else:
                conditional_path.unlink()
            stale_code = ""
            try:
                current_plan(conditional_run, conditional_contract)
            except PlanError as exc:
                stale_code = str(exc)
            changed_digest, _ = input_fingerprint(conditional_run)
            checks.append((
                f"{conditional_name} {operation} stales a committed plan",
                stale_code == "WORK_PLAN_INPUTS_STALE"
                and changed_digest != conditional_plan["inputs_digest"],
            ))

    # Every externally visible commit boundary is recoverable by the exact same
    # request. The journal suffix remains one copy of the frozen event sequence,
    # including a crash after append but before receipt progress is persisted.
    transaction_faults = (
        "prepared", "snapshot", "event:0:cycle_start",
        "event:1:stage_plan", "event:2:delegation_committed",
        "current_plan", "archive", "committed",
    )
    for fault_index, fault_stage in enumerate(transaction_faults, start=1):
        tx_run, tx_contract = make_run(f"tx-fault-{fault_index}")
        tx_lanes = lane_pair(f"TX{fault_index}")

        def crash(stage: str, *, selected: str = fault_stage) -> None:
            if stage == selected:
                raise RuntimeError(f"simulated crash at {stage}")

        crashed = False
        try:
            commit_plan(
                tx_run, macro_stage="S1", objective="transaction recovery",
                mode="SERIAL_AGENT", reason="execution then exact Reviewer",
                exit_gate="transaction committed", lanes=tx_lanes,
                contract=tx_contract, fault=crash,
            )
        except RuntimeError:
            crashed = True
        recovered = commit_plan(
            tx_run, macro_stage="S1", objective="transaction recovery",
            mode="SERIAL_AGENT", reason="execution then exact Reviewer",
            exit_gate="transaction committed", lanes=tx_lanes,
            contract=tx_contract,
        )
        first_events = loop_journal.load_events(tx_run)
        retried = commit_plan(
            tx_run, macro_stage="S1", objective="transaction recovery",
            mode="SERIAL_AGENT", reason="execution then exact Reviewer",
            exit_gate="transaction committed", lanes=tx_lanes,
            contract=tx_contract,
        )
        tx_receipt = _load_transaction(tx_run)
        checks.append((
            f"prepared transaction recovers exactly once after {fault_stage}",
            crashed
            and recovered == retried == load_plan(tx_run)
            and tx_receipt["status"] == "committed"
            and [item.get("event") for item in first_events]
                == ["cycle_start", "stage_plan", "delegation_committed"]
            and tx_receipt["event_hashes"]
                == [item.get("event_hash") for item in first_events]
            and loop_journal.load_events(tx_run) == first_events
            and load_plan_snapshot(tx_run, recovered["plan_digest"]) == recovered,
        ))

    # Every JSON publication surface uses the same flush -> file fsync ->
    # replace -> directory fsync chain.  Snapshot/archive directory creation
    # also persists the new directory entry in state/ before its first file is
    # published.
    barrier_run, barrier_contract = make_run("durability-barrier-coverage")
    module = sys.modules[__name__]
    with mock.patch.object(
            module, "_flush_and_fsync_json",
            wraps=_flush_and_fsync_json) as file_barrier_spy, \
            mock.patch.object(
                module, "_replace_json", wraps=_replace_json) as replace_spy, \
            mock.patch.object(
                module, "_persist_replaced_entry",
                wraps=_persist_replaced_entry) as entry_barrier_spy, \
            mock.patch.object(
                module, "_fsync_directory",
                wraps=_fsync_directory) as directory_barrier_spy:
        barrier_plan = commit_plan(
            barrier_run, macro_stage="S1", objective="cover durability barriers",
            mode="SERIAL_AGENT", reason="execution then exact Reviewer",
            exit_gate="all publication surfaces durable",
            lanes=lane_pair("DURABLE"), contract=barrier_contract,
        )
    barrier_transaction = _load_transaction(barrier_run)
    barrier_snapshot = plan_snapshot_path(
        barrier_run, barrier_plan["plan_digest"])
    barrier_archive = transaction_archive_path(
        barrier_run, barrier_transaction["receipt_hash"])
    publication_surfaces = {
        "transaction": plan_transaction_path(barrier_run),
        "snapshot": barrier_snapshot,
        "current": plan_path(barrier_run),
        "archive": barrier_archive,
    }

    def covered_surfaces(calls: list, destination_index: int) -> bool:
        destinations = {
            Path(call.args[destination_index]) for call in calls
            if len(call.args) > destination_index
        }
        return all(path in destinations for path in publication_surfaces.values())

    directory_calls = [Path(call.args[0]) for call in directory_barrier_spy.call_args_list]
    snapshot_dir = barrier_snapshot.parent
    archive_dir = barrier_archive.parent
    state_dir = barrier_run.resolve() / "state"

    def parent_barrier_precedes(directory: Path) -> bool:
        try:
            published_index = directory_calls.index(directory)
        except ValueError:
            return False
        return any(
            path == state_dir for path in directory_calls[:published_index])

    checks += [
        ("transaction/snapshot/current/archive flush and fsync temp JSON",
         covered_surfaces(file_barrier_spy.call_args_list, 1)),
        ("transaction/snapshot/current/archive use atomic replace",
         covered_surfaces(replace_spy.call_args_list, 1)),
        ("transaction/snapshot/current/archive fsync the replaced entry directory",
         covered_surfaces(entry_barrier_spy.call_args_list, 0)),
        ("new snapshot/archive directories persist their state-directory entries first",
         parent_barrier_precedes(snapshot_dir)
         and parent_barrier_precedes(archive_dir)),
    ]

    def publication_fault_fixture(
        label: str, helper_name: str, target: str,
    ) -> tuple[str, bool]:
        fault_run, fault_contract = make_run(f"durability-{label}")
        fault_lanes = lane_pair(f"DUR{len(checks)}")
        transaction_file = plan_transaction_path(fault_run)
        current_file = plan_path(fault_run)
        original_helper = getattr(module, helper_name)

        def matches(destination: Path) -> bool:
            destination = Path(destination)
            if target == "prepared_transaction":
                return destination == transaction_file
            if target == "snapshot":
                return destination.parent.name == PLAN_ARCHIVE_DIR
            if target == "current_plan":
                return destination == current_file
            if target == "archive":
                return destination.parent.name == TRANSACTION_ARCHIVE_DIR
            if target == "committed_transaction":
                if destination != transaction_file or not destination.is_file():
                    return False
                try:
                    value = json.loads(destination.read_text(
                        encoding="utf-8", errors="strict"))
                except Exception:
                    return False
                return value.get("status") == "committed"
            raise AssertionError(f"unknown durability target {target}")

        def fail_selected(*args):
            destination = Path(args[-1])
            if matches(destination):
                raise OSError(f"injected {label} failure")
            return original_helper(*args)

        rejected = False
        consumer_blocked = False
        visible_status = ""
        visible_archives: list[Path] = []
        with mock.patch.object(module, helper_name, side_effect=fail_selected):
            try:
                commit_plan(
                    fault_run, macro_stage="S1",
                    objective=f"recover {label}",
                    mode="SERIAL_AGENT",
                    reason="execution then exact Reviewer",
                    exit_gate="one durable committed plan",
                    lanes=fault_lanes, contract=fault_contract,
                )
            except PlanError as exc:
                rejected = str(exc) == "WORK_PLAN_DURABILITY_FAILED"
            raw_transaction = _read_transaction(fault_run)
            visible_status = str(raw_transaction.get("status") or "")
            visible_archives = sorted(
                (fault_run / "state" / TRANSACTION_ARCHIVE_DIR).glob("*.json"))
            try:
                transaction_bound_plan(fault_run)
            except PlanError:
                consumer_blocked = True

        recovered_plan = commit_plan(
            fault_run, macro_stage="S1", objective=f"recover {label}",
            mode="SERIAL_AGENT", reason="execution then exact Reviewer",
            exit_gate="one durable committed plan", lanes=fault_lanes,
            contract=fault_contract,
        )
        final_transaction = _load_transaction(fault_run)
        final_events = loop_journal.load_events(fault_run)
        temporary_residue = list((fault_run / "state").rglob("*.json.*"))
        special_state_ok = True
        if label == "archive-dir-fsync":
            special_state_ok = visible_status == "prepared" \
                and len(visible_archives) == 1
        elif label == "archive-file-fsync":
            special_state_ok = visible_status == "prepared" \
                and not visible_archives
        elif label == "committed-receipt-dir-fsync":
            # replace can be visible after its directory barrier failed, but it
            # is not admitted while that barrier remains unavailable.
            special_state_ok = visible_status == "committed"
        else:
            special_state_ok = visible_status != "committed"
        return label, bool(
            rejected and consumer_blocked and special_state_ok
            and current_plan(fault_run, fault_contract) == recovered_plan
            and final_transaction["status"] == "committed"
            and transaction_archive_path(
                fault_run, final_transaction["receipt_hash"]).is_file()
            and load_plan_snapshot(
                fault_run, recovered_plan["plan_digest"]) == recovered_plan
            and not temporary_residue
            and [item.get("event") for item in final_events]
                == ["cycle_start", "stage_plan", "delegation_committed"]
        )

    for durability_case in (
        ("prepared-receipt-file-fsync", "_flush_and_fsync_json",
         "prepared_transaction"),
        ("prepared-receipt-replace", "_replace_json",
         "prepared_transaction"),
        ("prepared-receipt-dir-fsync", "_persist_replaced_entry",
         "prepared_transaction"),
        ("snapshot-file-fsync", "_flush_and_fsync_json", "snapshot"),
        ("snapshot-replace", "_replace_json", "snapshot"),
        ("snapshot-dir-fsync", "_persist_replaced_entry", "snapshot"),
        ("current-plan-file-fsync", "_flush_and_fsync_json", "current_plan"),
        ("current-plan-replace", "_replace_json", "current_plan"),
        ("current-plan-dir-fsync", "_persist_replaced_entry", "current_plan"),
        ("archive-file-fsync", "_flush_and_fsync_json", "archive"),
        ("archive-replace", "_replace_json", "archive"),
        ("archive-dir-fsync", "_persist_replaced_entry", "archive"),
        ("committed-receipt-dir-fsync", "_persist_replaced_entry",
         "committed_transaction"),
    ):
        label, passed = publication_fault_fixture(*durability_case)
        checks.append((f"{label} fails closed and exact retry is idempotent", passed))

    # A failure while persisting the newly-created archive directory itself
    # leaves only a prepared receipt.  Retry must re-fsync state/ even though
    # mkdir now observes an existing directory, then publish one archive/current.
    mkdir_run, mkdir_contract = make_run("durability-archive-mkdir-parent")
    mkdir_lanes = lane_pair("DURMKDIR")
    resolved_mkdir_run = mkdir_run.resolve()
    mkdir_archive_dir = (
        resolved_mkdir_run / "state" / TRANSACTION_ARCHIVE_DIR)
    original_directory_fsync = _fsync_directory

    def fail_archive_parent(path: Path) -> None:
        if Path(path) == resolved_mkdir_run / "state" \
                and mkdir_archive_dir.is_dir() \
                and not any(mkdir_archive_dir.iterdir()):
            raise OSError("injected archive mkdir parent fsync failure")
        original_directory_fsync(path)

    mkdir_rejected = False
    with mock.patch.object(
            module, "_fsync_directory", side_effect=fail_archive_parent):
        try:
            commit_plan(
                mkdir_run, macro_stage="S1",
                objective="recover archive directory creation",
                mode="SERIAL_AGENT", reason="execution then exact Reviewer",
                exit_gate="archive directory and receipt durable",
                lanes=mkdir_lanes, contract=mkdir_contract,
            )
        except PlanError as exc:
            mkdir_rejected = str(exc) == "WORK_PLAN_DURABILITY_FAILED"
    mkdir_prepared = _read_transaction(mkdir_run)
    mkdir_archives_before_retry = list(mkdir_archive_dir.glob("*.json"))
    mkdir_recovered = commit_plan(
        mkdir_run, macro_stage="S1",
        objective="recover archive directory creation",
        mode="SERIAL_AGENT", reason="execution then exact Reviewer",
        exit_gate="archive directory and receipt durable",
        lanes=mkdir_lanes, contract=mkdir_contract,
    )
    mkdir_committed = _load_transaction(mkdir_run)
    checks.append((
        "archive mkdir parent-fsync failure cannot precede committed receipt",
        mkdir_rejected and mkdir_prepared.get("status") == "prepared"
        and not mkdir_archives_before_retry
        and current_plan(mkdir_run, mkdir_contract) == mkdir_recovered
        and mkdir_committed["status"] == "committed"
        and len(list(mkdir_archive_dir.glob("*.json"))) == 1,
    ))

    mismatch_run, mismatch_contract = make_run("tx-mismatch")
    mismatch_lanes = lane_pair("TXM")

    def crash_prepared(stage: str) -> None:
        if stage == "prepared":
            raise RuntimeError("simulated prepared crash")

    try:
        commit_plan(
            mismatch_run, macro_stage="S1", objective="frozen request",
            mode="SERIAL_AGENT", reason="execution then exact Reviewer",
            exit_gate="transaction committed", lanes=mismatch_lanes,
            contract=mismatch_contract, fault=crash_prepared,
        )
    except RuntimeError:
        pass
    pending_mismatch = False
    try:
        commit_plan(
            mismatch_run, macro_stage="S1", objective="different request",
            mode="SERIAL_AGENT", reason="execution then exact Reviewer",
            exit_gate="transaction committed", lanes=mismatch_lanes,
            contract=mismatch_contract,
        )
    except PlanError as exc:
        pending_mismatch = str(exc) == "WORK_PLAN_TRANSACTION_PENDING_MISMATCH"
    recovered_mismatch = commit_plan(
        mismatch_run, macro_stage="S1", objective="frozen request",
        mode="SERIAL_AGENT", reason="execution then exact Reviewer",
        exit_gate="transaction committed", lanes=mismatch_lanes,
        contract=mismatch_contract,
    )
    checks.append((
        "different request cannot replace an unresolved prepared transaction",
        pending_mismatch and _load_transaction(mismatch_run)["status"] == "committed"
        and load_plan(mismatch_run) == recovered_mismatch,
    ))

    tamper_run, tamper_contract = make_run("tx-receipt-tamper")
    commit_plan(
        tamper_run, macro_stage="S1", objective="receipt hash coverage",
        mode="SERIAL_AGENT", reason="execution then exact Reviewer",
        exit_gate="transaction committed", lanes=lane_pair("TXT"),
        contract=tamper_contract,
    )
    transaction_file = plan_transaction_path(tamper_run)
    transaction_original = json.loads(transaction_file.read_text(encoding="utf-8"))
    tamper_cases = {
        "status": dict(transaction_original, status="prepared", committed_at=0.0),
        "event_hashes": dict(
            transaction_original,
            event_hashes=["f" * 64, *transaction_original["event_hashes"][1:]],
        ),
        "committed_at": dict(
            transaction_original,
            committed_at=transaction_original["committed_at"] + 1,
        ),
    }
    transaction_tamper_blocked = True
    for tampered in tamper_cases.values():
        _atomic_json(transaction_file, tampered)
        try:
            _load_transaction(tamper_run)
            transaction_tamper_blocked = False
        except PlanError as exc:
            transaction_tamper_blocked = transaction_tamper_blocked and (
                str(exc) == "WORK_PLAN_TRANSACTION_RECEIPT_HASH_MISMATCH")
        finally:
            _atomic_json(transaction_file, transaction_original)
    checks.append((
        "transaction receipt hash covers status, progress, and commit time",
        transaction_tamper_blocked,
    ))

    provenance_run, provenance_contract = make_run("tx-provenance")
    provenance_lanes = lane_pair("TXP")
    provenance_plan = commit_plan(
        provenance_run, macro_stage="S1", objective="prove current provenance",
        mode="SERIAL_AGENT", reason="execution then exact Reviewer",
        exit_gate="transaction committed", lanes=provenance_lanes,
        contract=provenance_contract,
    )
    native_transaction = _load_transaction(provenance_run)
    native_current = current_plan(provenance_run, provenance_contract)
    checks.append((
        "normal current plan requires and validates native committed provenance",
        native_current == provenance_plan
        and native_transaction["provenance"] == "native_commit"
        and native_transaction["migration_source_digest"] == "",
    ))

    provenance_transaction_path = plan_transaction_path(provenance_run)
    provenance_transaction_path.unlink()
    missing_transaction_blocked = False
    missing_transaction_replan_blocked = False
    try:
        current_plan(provenance_run, provenance_contract)
    except PlanError as exc:
        missing_transaction_blocked = str(exc) == "WORK_PLAN_TRANSACTION_REQUIRED"
    try:
        commit_plan(
            provenance_run, macro_stage="S1",
            objective="prove current provenance",
            mode="SERIAL_AGENT", reason="execution then exact Reviewer",
            exit_gate="transaction committed", lanes=provenance_lanes,
            contract=provenance_contract,
        )
    except PlanError as exc:
        missing_transaction_replan_blocked = (
            str(exc) == "WORK_PLAN_TRANSACTION_REQUIRED")
    checks.append((
        "missing transaction blocks both current_plan and implicit replan adoption",
        missing_transaction_blocked and missing_transaction_replan_blocked,
    ))

    provenance_transaction_path.write_text("{unreadable\n", encoding="utf-8")
    unreadable_transaction_blocked = False
    try:
        current_plan(provenance_run, provenance_contract)
    except PlanError as exc:
        unreadable_transaction_blocked = (
            str(exc) == "WORK_PLAN_TRANSACTION_UNREADABLE")
    checks.append((
        "unreadable transaction blocks current_plan",
        unreadable_transaction_blocked,
    ))
    provenance_transaction_path.unlink()

    legacy_ack_blocked = False
    try:
        migrate_legacy_plan(provenance_run, contract=provenance_contract)
    except PlanError as exc:
        legacy_ack_blocked = (
            str(exc) == "WORK_PLAN_LEGACY_MIGRATION_ACK_REQUIRED")
    provenance_snapshot_path = plan_snapshot_path(
        provenance_run, provenance_plan["plan_digest"])
    provenance_snapshot_path.unlink()
    archive_before_missing = sorted(
        path.name for path in
        (provenance_run / "state" / TRANSACTION_ARCHIVE_DIR).glob("*.json"))
    missing_snapshot_blocked = False
    try:
        migrate_legacy_plan(
            provenance_run, acknowledge_unreceipted_plan=True,
            contract=provenance_contract,
        )
    except PlanError as exc:
        missing_snapshot_blocked = (
            str(exc) == "WORK_PLAN_TRANSACTION_SNAPSHOT_MISSING")
    archive_after_missing = sorted(
        path.name for path in
        (provenance_run / "state" / TRANSACTION_ARCHIVE_DIR).glob("*.json"))
    checks.append((
        "legacy migration never creates a missing immutable plan snapshot",
        missing_snapshot_blocked
        and not provenance_transaction_path.exists()
        and archive_after_missing == archive_before_missing,
    ))
    _atomic_json(provenance_snapshot_path, provenance_plan)
    migrated_plan = migrate_legacy_plan(
        provenance_run, acknowledge_unreceipted_plan=True,
        contract=provenance_contract,
    )
    migrated_transaction = _load_transaction(provenance_run)
    migrated_archive_path = transaction_archive_path(
        provenance_run, migrated_transaction["receipt_hash"])
    migrated_archive_bytes_for_gate = migrated_archive_path.read_bytes()
    migrated_archive_path.unlink()
    unarchived_cycle_plan_blocked = False
    try:
        transaction_bound_plan(provenance_run)
    except PlanError as exc:
        unarchived_cycle_plan_blocked = (
            str(exc) == "WORK_PLAN_TRANSACTION_ARCHIVE_MISSING")
    migrated_archive_path.write_bytes(migrated_archive_bytes_for_gate)
    checks.append((
        "cycle producer plan gate rejects a missing committed v2 archive",
        unarchived_cycle_plan_blocked
        and transaction_bound_plan(provenance_run) == migrated_plan,
    ))
    migration_repeat_blocked = False
    try:
        migrate_legacy_plan(
            provenance_run, acknowledge_unreceipted_plan=True,
            contract=provenance_contract,
        )
    except PlanError as exc:
        migration_repeat_blocked = (
            str(exc) == "WORK_PLAN_LEGACY_MIGRATION_ALREADY_PROVENANCED")
    checks.append((
        "explicit legacy migration freezes exact source and restores current_plan",
        legacy_ack_blocked
        and migrated_plan == provenance_plan
        and current_plan(provenance_run, provenance_contract) == provenance_plan
        and migrated_transaction["status"] == "committed"
        and migrated_transaction["provenance"] == "legacy_migration"
        and migrated_transaction["migration_source_digest"]
            == _legacy_migration_source_digest(migrated_transaction)
        and transaction_archive_path(
            provenance_run, migrated_transaction["receipt_hash"]).is_file()
        and load_plan_snapshot(
            provenance_run, provenance_plan["plan_digest"]) == provenance_plan
        and migration_repeat_blocked,
    ))
    migrated_archive = transaction_archive_path(
        provenance_run, migrated_transaction["receipt_hash"])
    migrated_archive_bytes = migrated_archive.read_bytes()
    post_migration_plan = commit_plan(
        provenance_run, macro_stage="S1",
        objective="replan without erasing admitted legacy provenance",
        mode="SERIAL_AGENT", reason="execution then exact Reviewer",
        exit_gate="transaction chain remains complete", lanes=lane_pair("TXP2"),
        replan_reason="material objective changed after migration",
        contract=provenance_contract,
    )
    post_migration_transaction = _load_transaction(provenance_run)
    checks.append((
        "migration provenance remains immutable and chained after replan",
        post_migration_plan["plan_digest"] != provenance_plan["plan_digest"]
        and post_migration_transaction["provenance"] == "native_commit"
        and post_migration_transaction["prior_transaction_receipt_hash"]
            == migrated_transaction["receipt_hash"]
        and migrated_archive.read_bytes() == migrated_archive_bytes
        and transaction_archive_path(
            provenance_run,
            post_migration_transaction["receipt_hash"],
        ).is_file()
        and not _verify_transaction_lineage(
            provenance_run, post_migration_transaction,
            require_current_archive=True),
    ))

    forged_run, forged_contract = make_run("tx-legacy-forged")
    forged_original = commit_plan(
        forged_run, macro_stage="S1", objective="journal-bound legacy source",
        mode="SERIAL_AGENT", reason="execution then exact Reviewer",
        exit_gate="transaction committed", lanes=lane_pair("TXFORGED"),
        contract=forged_contract,
    )
    plan_transaction_path(forged_run).unlink()
    forged_plan = dict(forged_original, objective="self-hashed but not journal-bound")
    forged_plan["plan_digest"] = _plan_digest(forged_plan)
    forged_plan["plan_id"] = (
        f"WP-{forged_plan['cycle_id']}-{forged_plan['plan_digest'][:8]}")
    _atomic_json(plan_path(forged_run), forged_plan)
    forged_events = loop_journal.load_events(forged_run)
    previous_hash = ""
    for record in forged_events:
        record["previous_event_hash"] = previous_hash
        if record["event"] == "cycle_start":
            record["note"] = f"work plan {forged_plan['plan_id']}"
        elif record["event"] == "stage_plan":
            record["note"] = forged_plan["plan_id"]
            record["data"]["plan_id"] = forged_plan["plan_id"]
            record["data"]["plan_digest"] = forged_plan["plan_digest"]
        elif record["event"] == "delegation_committed":
            record["data"]["plan_digest"] = forged_plan["plan_digest"]
        record["event_hash"] = loop_journal._record_event_hash(record)
        previous_hash = record["event_hash"]
    (forged_run / "state" / loop_journal.JOURNAL).write_text(
        "\n".join(json.dumps(item, ensure_ascii=False, sort_keys=True)
                  for item in forged_events) + "\n",
        encoding="utf-8",
    )
    forged_archive_before = sorted(
        path.name for path in
        (forged_run / "state" / TRANSACTION_ARCHIVE_DIR).glob("*.json"))
    forged_migration_blocked = False
    try:
        migrate_legacy_plan(
            forged_run, acknowledge_unreceipted_plan=True,
            contract=forged_contract,
        )
    except PlanError as exc:
        forged_migration_blocked = (
            str(exc) == "WORK_PLAN_TRANSACTION_SNAPSHOT_MISSING")
    forged_archive_after = sorted(
        path.name for path in
        (forged_run / "state" / TRANSACTION_ARCHIVE_DIR).glob("*.json"))
    checks.append((
        "immutable snapshot blocks a fully rehashed forged plan and journal",
        forged_migration_blocked
        and not plan_transaction_path(forged_run).exists()
        and forged_archive_after == forged_archive_before,
    ))

    direct_legacy_run, direct_legacy_contract = make_run("tx-legacy-root-direct")
    direct_legacy_lane = {
        "id": "L-LEGACY-DIRECT", "role": "verify",
        "effect": "local_read", "capability_id": "read.run-model",
        "assets": [], "dependencies": [],
        "expected_evidence": "typed local projection",
        "expected_information_gain": "low",
        "stop_condition": "one exact read returns",
        "request_cost": 0, "request_budget": 0, "merge_cost": 1,
        "atomic": True,
    }
    commit_plan(
        direct_legacy_run, macro_stage="S1", objective="one direct read",
        mode="ROOT_DIRECT", reason="one eligible atomic capability",
        exit_gate="typed action receipt", lanes=[direct_legacy_lane],
        contract=direct_legacy_contract,
    )
    plan_transaction_path(direct_legacy_run).unlink()
    direct_lock = direct_legacy_run / "state" / ".work_plan.lock"
    direct_lock_mtime = direct_lock.stat().st_mtime_ns
    direct_archives_before = sorted(
        path.name for path in
        (direct_legacy_run / "state" / TRANSACTION_ARCHIVE_DIR).glob("*.json"))
    direct_migration_blocked = False
    try:
        migrate_legacy_plan(
            direct_legacy_run, acknowledge_unreceipted_plan=True,
            contract=direct_legacy_contract,
        )
    except PlanError as exc:
        direct_migration_blocked = (
            str(exc) == "WORK_PLAN_LEGACY_ROOT_DIRECT_FORBIDDEN")
    checks.append((
        "ROOT_DIRECT migration is rejected before any writer-lock/state write",
        direct_migration_blocked
        and not plan_transaction_path(direct_legacy_run).exists()
        and direct_lock.stat().st_mtime_ns == direct_lock_mtime
        and sorted(
            path.name for path in
            (direct_legacy_run / "state" / TRANSACTION_ARCHIVE_DIR).glob("*.json"))
            == direct_archives_before,
    ))

    def as_legacy_v1(transaction: dict) -> dict:
        legacy = {
            key: json.loads(json.dumps(value, ensure_ascii=False))
            for key, value in transaction.items()
            if key not in {
                "prior_transaction_receipt_hash", "provenance",
                "migration_source_digest",
            }
        }
        legacy["schema"] = LEGACY_TRANSACTION_SCHEMA
        legacy["transaction_id"] = _legacy_transaction_identity(legacy)
        legacy["receipt_hash"] = _transaction_receipt_hash(legacy)
        return legacy

    v1_run, v1_contract = make_run("tx-native-v1-upgrade")
    v1_plan = commit_plan(
        v1_run, macro_stage="S1", objective="upgrade exact native v1",
        mode="SERIAL_AGENT", reason="execution then exact Reviewer",
        exit_gate="transaction committed", lanes=lane_pair("TXV1"),
        contract=v1_contract,
    )
    native_v1 = as_legacy_v1(_load_transaction(v1_run))
    _atomic_json(plan_transaction_path(v1_run), native_v1)
    v1_current_blocked = False
    try:
        current_plan(v1_run, v1_contract)
    except PlanError as exc:
        v1_current_blocked = (
            str(exc) == "WORK_PLAN_TRANSACTION_UPGRADE_REQUIRED")
    upgraded_v1_plan = migrate_legacy_plan(
        v1_run, acknowledge_unreceipted_plan=True, contract=v1_contract)
    upgraded_v1 = _load_transaction(v1_run)
    checks.append((
        "exact committed native v1 upgrades through archived receipt lineage",
        v1_current_blocked and upgraded_v1_plan == v1_plan
        and upgraded_v1["schema"] == TRANSACTION_SCHEMA
        and upgraded_v1["provenance"] == "native_v1_upgrade"
        and upgraded_v1["prior_transaction_receipt_hash"]
            == native_v1["receipt_hash"]
        and transaction_archive_path(
            v1_run, native_v1["receipt_hash"]).is_file()
        and transaction_archive_path(
            v1_run, upgraded_v1["receipt_hash"]).is_file()
        and current_plan(v1_run, v1_contract) == v1_plan,
    ))

    malformed_v1_run, malformed_v1_contract = make_run("tx-native-v1-malformed")
    commit_plan(
        malformed_v1_run, macro_stage="S1", objective="reject malformed v1",
        mode="SERIAL_AGENT", reason="execution then exact Reviewer",
        exit_gate="transaction committed", lanes=lane_pair("TXV1BAD"),
        contract=malformed_v1_contract,
    )
    malformed_v1 = as_legacy_v1(_load_transaction(malformed_v1_run))
    malformed_v1["request_digest"] = "f" * 64
    malformed_v1["transaction_id"] = _legacy_transaction_identity(malformed_v1)
    malformed_v1["receipt_hash"] = _transaction_receipt_hash(malformed_v1)
    _atomic_json(plan_transaction_path(malformed_v1_run), malformed_v1)
    malformed_archives_before = sorted(
        path.name for path in
        (malformed_v1_run / "state" / TRANSACTION_ARCHIVE_DIR).glob("*.json"))
    malformed_v1_blocked = False
    try:
        migrate_legacy_plan(
            malformed_v1_run, acknowledge_unreceipted_plan=True,
            contract=malformed_v1_contract,
        )
    except PlanError as exc:
        malformed_v1_blocked = (
            str(exc) == "WORK_PLAN_LEGACY_TRANSACTION_REQUEST_DIVERGED")
    checks.append((
        "rehashed but request-diverged native v1 cannot enter the upgrade path",
        malformed_v1_blocked
        and sorted(
            path.name for path in
            (malformed_v1_run / "state" / TRANSACTION_ARCHIVE_DIR).glob("*.json"))
            == malformed_archives_before,
    ))

    def archive_bytes(run_dir: Path) -> dict[str, bytes]:
        directory = run_dir / "state" / TRANSACTION_ARCHIVE_DIR
        return {
            path.name: path.read_bytes()
            for path in sorted(directory.glob("*.json"))
        }

    migration_retry_run, migration_retry_contract = make_run(
        "tx-legacy-archive-current-retry")
    migration_retry_plan = commit_plan(
        migration_retry_run, macro_stage="S1",
        objective="deterministic legacy migration retry",
        mode="SERIAL_AGENT", reason="execution then exact Reviewer",
        exit_gate="one stable migration receipt", lanes=lane_pair("TXMRETRY"),
        contract=migration_retry_contract,
    )
    plan_transaction_path(migration_retry_run).unlink()
    migration_archives_before = archive_bytes(migration_retry_run)
    migration_candidates: list[dict] = []

    def crash_migration_current_write(run_dir: Path, value: dict) -> dict:
        migration_candidates.append(json.loads(json.dumps(value)))
        raise RuntimeError("crash after migration archive before current receipt")

    migration_current_crashed = False
    with mock.patch.object(
            sys.modules[__name__], "_write_transaction",
            side_effect=crash_migration_current_write):
        try:
            migrate_legacy_plan(
                migration_retry_run, acknowledge_unreceipted_plan=True,
                contract=migration_retry_contract,
            )
        except RuntimeError:
            migration_current_crashed = True
    migration_archives_after_crash = archive_bytes(migration_retry_run)
    migration_retry_result = migrate_legacy_plan(
        migration_retry_run, acknowledge_unreceipted_plan=True,
        contract=migration_retry_contract,
    )
    migration_retry_current = _load_transaction(migration_retry_run)
    migration_archives_after_retry = archive_bytes(migration_retry_run)
    checks.append((
        "legacy archive-to-current crash retries one byte-identical receipt",
        migration_current_crashed
        and migration_retry_result == migration_retry_plan
        and len(migration_candidates) == 1
        and migration_retry_current == migration_candidates[0]
        and len(migration_archives_after_crash)
            == len(migration_archives_before) + 1
        and migration_archives_after_retry == migration_archives_after_crash
        and json.loads(transaction_archive_path(
            migration_retry_run,
            migration_retry_current["receipt_hash"],
        ).read_text(encoding="utf-8")) == migration_retry_current
        and not _verify_transaction_lineage(
            migration_retry_run, migration_retry_current,
            require_current_archive=True),
    ))

    v1_retry_run, v1_retry_contract = make_run("tx-v1-archive-current-retry")
    v1_retry_plan = commit_plan(
        v1_retry_run, macro_stage="S1",
        objective="deterministic v1 upgrade retry",
        mode="SERIAL_AGENT", reason="execution then exact Reviewer",
        exit_gate="one stable upgrade receipt", lanes=lane_pair("TXV1RETRY"),
        contract=v1_retry_contract,
    )
    v1_retry_legacy = as_legacy_v1(_load_transaction(v1_retry_run))
    _atomic_json(plan_transaction_path(v1_retry_run), v1_retry_legacy)
    v1_archives_before = archive_bytes(v1_retry_run)
    v1_candidates: list[dict] = []

    def crash_v1_current_write(run_dir: Path, value: dict) -> dict:
        v1_candidates.append(json.loads(json.dumps(value)))
        raise RuntimeError("crash after v1 archives before current receipt")

    v1_current_crashed = False
    with mock.patch.object(
            sys.modules[__name__], "_write_transaction",
            side_effect=crash_v1_current_write):
        try:
            migrate_legacy_plan(
                v1_retry_run, acknowledge_unreceipted_plan=True,
                contract=v1_retry_contract,
            )
        except RuntimeError:
            v1_current_crashed = True
    v1_archives_after_crash = archive_bytes(v1_retry_run)
    v1_retry_result = migrate_legacy_plan(
        v1_retry_run, acknowledge_unreceipted_plan=True,
        contract=v1_retry_contract,
    )
    v1_retry_current = _load_transaction(v1_retry_run)
    checks.append((
        "v1 archive-to-current crash retries one byte-identical upgrade receipt",
        v1_current_crashed and v1_retry_result == v1_retry_plan
        and len(v1_candidates) == 1
        and v1_retry_current == v1_candidates[0]
        and len(v1_archives_after_crash) == len(v1_archives_before) + 2
        and archive_bytes(v1_retry_run) == v1_archives_after_crash
        and not _verify_transaction_lineage(
            v1_retry_run, v1_retry_current, require_current_archive=True),
    ))

    for crash_archive_index in (1, 2):
        between_run, between_contract = make_run(
            f"tx-v1-between-archives-{crash_archive_index}")
        between_plan = commit_plan(
            between_run, macro_stage="S1",
            objective=f"recover after v1 archive {crash_archive_index}",
            mode="SERIAL_AGENT", reason="execution then exact Reviewer",
            exit_gate="archive chain recovered",
            lanes=lane_pair(f"TXV1A{crash_archive_index}"),
            contract=between_contract,
        )
        between_legacy = as_legacy_v1(_load_transaction(between_run))
        _atomic_json(plan_transaction_path(between_run), between_legacy)
        between_before = archive_bytes(between_run)
        archive_calls = 0
        original_archive_transaction = _archive_transaction

        def crash_between_archives(
            run_dir: Path, value: dict, *, selected: int = crash_archive_index,
        ) -> Path:
            nonlocal archive_calls
            result = original_archive_transaction(run_dir, value)
            archive_calls += 1
            if archive_calls == selected:
                raise RuntimeError(f"crash after v1 archive {selected}")
            return result

        between_crashed = False
        with mock.patch.object(
                sys.modules[__name__], "_archive_transaction",
                side_effect=crash_between_archives):
            try:
                migrate_legacy_plan(
                    between_run, acknowledge_unreceipted_plan=True,
                    contract=between_contract,
                )
            except RuntimeError:
                between_crashed = True
        between_partial = archive_bytes(between_run)
        between_result = migrate_legacy_plan(
            between_run, acknowledge_unreceipted_plan=True,
            contract=between_contract,
        )
        between_current = _load_transaction(between_run)
        between_final = archive_bytes(between_run)
        checks.append((
            f"v1 crash after archive {crash_archive_index} recovers one lineage",
            between_crashed and archive_calls == crash_archive_index
            and between_result == between_plan
            and len(between_final) == len(between_before) + 2
            and all(between_final.get(name) == data
                    for name, data in between_partial.items())
            and transaction_archive_path(
                between_run, between_current["receipt_hash"]).is_file()
            and not _verify_transaction_lineage(
                between_run, between_current, require_current_archive=True),
        ))

    prepared_run, prepared_contract = make_run("tx-current-prepared")
    prepared_lanes = lane_pair("TXPREP")

    def crash_after_current_plan(stage: str) -> None:
        if stage == "current_plan":
            raise RuntimeError("simulated crash before transaction commit")

    try:
        commit_plan(
            prepared_run, macro_stage="S1", objective="prepared provenance",
            mode="SERIAL_AGENT", reason="execution then exact Reviewer",
            exit_gate="transaction committed", lanes=prepared_lanes,
            contract=prepared_contract, fault=crash_after_current_plan,
        )
    except RuntimeError:
        pass
    prepared_current_blocked = False
    try:
        current_plan(prepared_run, prepared_contract)
    except PlanError as exc:
        prepared_current_blocked = (
            str(exc) == "WORK_PLAN_TRANSACTION_RECOVERY_REQUIRED")
    recovered_prepared = commit_plan(
        prepared_run, macro_stage="S1", objective="prepared provenance",
        mode="SERIAL_AGENT", reason="execution then exact Reviewer",
        exit_gate="transaction committed", lanes=prepared_lanes,
        contract=prepared_contract,
    )
    checks.append((
        "prepared transaction is never current until exact recovery commits it",
        prepared_current_blocked
        and current_plan(prepared_run, prepared_contract) == recovered_prepared,
    ))

    diverged_run, diverged_contract = make_run("tx-current-diverged")
    diverged_plan = commit_plan(
        diverged_run, macro_stage="S1", objective="committed provenance",
        mode="SERIAL_AGENT", reason="execution then exact Reviewer",
        exit_gate="transaction committed", lanes=lane_pair("TXDIV"),
        contract=diverged_contract,
    )
    other_run, other_contract = make_run("tx-current-other")
    other_plan = commit_plan(
        other_run, macro_stage="S1", objective="other committed provenance",
        mode="SERIAL_AGENT", reason="execution then exact Reviewer",
        exit_gate="transaction committed", lanes=lane_pair("TXOTHER"),
        contract=other_contract,
    )
    _atomic_json(plan_path(diverged_run), other_plan)
    committed_mismatch_blocked = False
    try:
        current_plan(diverged_run, diverged_contract)
    except PlanError as exc:
        committed_mismatch_blocked = (
            str(exc) == "WORK_PLAN_TRANSACTION_CURRENT_PLAN_DIVERGED")
    _atomic_json(plan_path(diverged_run), diverged_plan)
    checks.append((
        "committed transaction rejects a different self-hashed current plan",
        committed_mismatch_blocked
        and current_plan(diverged_run, diverged_contract) == diverged_plan,
    ))

    corrupt_run, corrupt_contract = make_run("tx-corrupt-journal")
    corrupt_lanes = lane_pair("TXC")
    try:
        commit_plan(
            corrupt_run, macro_stage="S1", objective="journal validation",
            mode="SERIAL_AGENT", reason="execution then exact Reviewer",
            exit_gate="transaction committed", lanes=corrupt_lanes,
            contract=corrupt_contract, fault=crash_prepared,
        )
    except RuntimeError:
        pass
    (corrupt_run / "state" / loop_journal.JOURNAL).write_text(
        "{malformed tail\n", encoding="utf-8")
    corrupt_recovery_blocked = False
    try:
        commit_plan(
            corrupt_run, macro_stage="S1", objective="journal validation",
            mode="SERIAL_AGENT", reason="execution then exact Reviewer",
            exit_gate="transaction committed", lanes=corrupt_lanes,
            contract=corrupt_contract,
        )
    except PlanError as exc:
        corrupt_recovery_blocked = str(exc).startswith(
            "WORK_PLAN_JOURNAL_INVALID:")
    checks.append((
        "prepared recovery validates the existing journal chain first",
        corrupt_recovery_blocked,
    ))

    ended_corrupt_run, ended_corrupt_contract = make_run("ended-corrupt-journal")
    ended_corrupt_plan = commit_plan(
        ended_corrupt_run, macro_stage="S1", objective="journal validation",
        mode="SERIAL_AGENT", reason="execution then exact Reviewer",
        exit_gate="transaction committed", lanes=lane_pair("TXE"),
        contract=ended_corrupt_contract,
    )
    ended_journal = ended_corrupt_run / "state" / loop_journal.JOURNAL
    ended_rows = ended_journal.read_text(encoding="utf-8").splitlines()
    ended_first = json.loads(ended_rows[0])
    ended_first["note"] = "tampered without rehash"
    ended_rows[0] = json.dumps(ended_first, ensure_ascii=False, sort_keys=True)
    ended_journal.write_text("\n".join(ended_rows) + "\n", encoding="utf-8")
    corrupt_end_state_blocked = False
    try:
        _plan_cycle_ended(ended_corrupt_run, ended_corrupt_plan)
    except PlanError as exc:
        corrupt_end_state_blocked = str(exc).startswith(
            "WORK_PLAN_JOURNAL_INVALID:")
    checks.append((
        "corrupt journal cannot be treated as an unfinished delegable plan",
        corrupt_end_state_blocked,
    ))

    run, contract = make_run("stage-flow")
    s1_plan = commit_plan(
        run, macro_stage="S1", objective="inventory auth surface",
        mode="SERIAL_AGENT", reason="execution then exact Reviewer",
        exit_gate="cycle receipt has zero debt", lanes=lane_pair("S1"),
        contract=contract,
    )
    unassigned_end_blocked = False
    try:
        loop_journal.append_event(
            run, "cycle_end", next_action="运行 check_run 验证当前计划")
    except loop_journal.JournalContractError as exc:
        unassigned_end_blocked = exc.code == "CYCLE_EVENT_PLAN_DEBT_OPEN"
    checks.append(("unassigned plan lanes cannot cycle_end", unassigned_end_blocked))

    s1_result = settle_plan(run, s1_plan)
    transition_before_end = False
    try:
        commit_plan(
            run, macro_stage="S2", objective="test auth front",
            mode="SERIAL_AGENT", reason="execution then exact Reviewer",
            exit_gate="cycle receipt has zero debt", lanes=lane_pair("S2"),
            replan_reason="inventory ready", contract=contract,
        )
    except PlanError as exc:
        transition_before_end = str(exc) == "WORK_PLAN_STAGE_EXIT_CYCLE_END_REQUIRED"
    checks.append(("stage transition requires prior typed cycle_end", transition_before_end))

    fake_summary_blocked = False
    try:
        loop_journal.append_event(run, "cycle_end", data={
            "plan_digest": s1_plan["plan_digest"],
            "merge_disposition_summary": {},
        })
    except loop_journal.JournalContractError as exc:
        fake_summary_blocked = exc.code == "CYCLE_EVENT_CALLER_DATA_FORBIDDEN"
    checks.append(("caller cannot self-report cycle_end", fake_summary_blocked))

    frozen = s1_result["frozen_path"]
    original = s1_result["frozen_bytes"]
    frozen.write_bytes(original + b"tamper")
    tamper_debt = run_model.plan_cycle_projection(run, plan=s1_plan)["debt"]["review"]
    frozen.write_bytes(original)
    checks.append(("immutable result tamper reopens review debt",
                   any("frozen-result-digest-mismatch" in item for item in tamper_debt)))

    s1_end = loop_journal.append_event(
        run,
        "cycle_end",
        note="derived end",
        next_action="运行 check_run 验证当前计划",
    )
    checks.append(("production end derives exact lane dispositions",
                   s1_end["data"]["lane_ids"] == ["L-S1-EXEC", "L-S1-REVIEW"]
                   and len(s1_end["data"]["assignment_dispositions"]) == 2
                   and not s1_end["data"]["merge_disposition_summary"]["pending"]))
    checks.append(("typed cycle_end makes every prior-plan lane non-delegable",
                   lane_runtime_state(run, s1_plan, "L-S1-EXEC") == "ended"
                   and not lane_dependencies_satisfied(
                       run, s1_plan, s1_plan["lanes"][0])))

    drifted_cycle_end = dict(s1_end["data"], next_action="different derived state")
    exact_cycle_end_blocked = False
    with mock.patch.object(
            loop_journal, "derive_cycle_end_data", return_value=drifted_cycle_end):
        try:
            commit_plan(
                run, macro_stage="S2", objective="test auth front",
                mode="SERIAL_AGENT", reason="execution then exact Reviewer",
                exit_gate="cycle receipt has zero debt", lanes=lane_pair("S2"),
                replan_reason="inventory ready", contract=contract,
            )
        except PlanError as exc:
            exact_cycle_end_blocked = (
                str(exc) == "WORK_PLAN_STAGE_EXIT_CYCLE_END_MISMATCH")
    checks.append((
        "stage exit re-derives and exactly matches the prior cycle_end",
        exact_cycle_end_blocked,
    ))

    s2_plan = commit_plan(
        run, macro_stage="S2", objective="test auth front",
        mode="SERIAL_AGENT", reason="execution then exact Reviewer",
        exit_gate="cycle receipt has zero debt", lanes=lane_pair("S2"),
        replan_reason="inventory ready", contract=contract,
    )
    events = loop_journal.load_events(run)
    boundary = [item.get("event") for item in events[-4:]]
    checks.append(("stage transition is cycle_end -> cycle_start -> stage_exit -> stage_plan",
                   boundary == ["cycle_start", "stage_exit", "stage_plan",
                                "delegation_committed"]))
    settle_plan(run, s2_plan)
    loop_journal.append_event(
        run, "cycle_end", next_action="运行 check_run 验证当前计划")
    (run / "frontier.md").write_text(
        "# Frontier\n\n## Closed Fronts\n\n### F-001 — auth\n"
        "- Status: blocked_type_b\n- Barrier class: auth-layer\n"
        "- Current depth: moderate\n",
        encoding="utf-8",
    )
    s3_plan = commit_plan(
        run, macro_stage="S3", objective="verify closure parity",
        mode="SERIAL_AGENT", reason="execution then exact Reviewer",
        exit_gate="closure gates remain zero", lanes=lane_pair("S3"),
        replan_reason="all active fronts settled", contract=contract,
    )
    checks.append(("S1/S2/S3 forward transition remains available",
                   s3_plan["macro_stage"] == "S3"))

    # Backward Macro-Stage movement uses the same real execution -> Reviewer ->
    # Root -> exact cycle_end chain; it is not a hand-written journal shortcut.
    settle_plan(run, s3_plan)
    loop_journal.append_event(
        run, "cycle_end", next_action="运行 check_run 验证当前计划")
    (run / "frontier.md").write_text(
        "# Frontier\n\n## Open Fronts\n\n### F-001 — reopened auth\n"
        "- Status: open\n- Barrier class: auth-layer\n"
        "- Current depth: moderate\n",
        encoding="utf-8",
    )
    fallback_s2 = commit_plan(
        run, macro_stage="S2", objective="re-adjudicate reopened auth front",
        mode="SERIAL_AGENT", reason="execution then exact Reviewer",
        exit_gate="reopened front reviewed", lanes=lane_pair("BACKS2"),
        replan_reason="closure review reopened F-001", contract=contract,
    )
    settle_plan(run, fallback_s2)
    loop_journal.append_event(
        run, "cycle_end", next_action="运行 check_run 验证当前计划")
    (run / "coverage.json").unlink()
    fallback_s1 = commit_plan(
        run, macro_stage="S1", objective="rebuild missing coverage inventory",
        mode="SERIAL_AGENT", reason="execution then exact Reviewer",
        exit_gate="coverage inventory restored", lanes=lane_pair("BACKS1"),
        replan_reason="coverage prerequisite became unavailable", contract=contract,
    )
    checks += [
        ("real settled S3 cycle can move backward to S2",
         fallback_s2["macro_stage"] == "S2"),
        ("real settled S2 cycle can move backward to S1",
         fallback_s1["macro_stage"] == "S1"),
    ]

    # A transcript-backed Agent launch failure is reviewable and can reach an
    # explicit failed/blocked/abandoned Root disposition without fake return state.
    failed_run, failed_contract = make_run("failed-runtime")
    failed_plan = commit_plan(
        failed_run, macro_stage="S1", objective="test failure path",
        mode="SERIAL_AGENT", reason="execution then exact Reviewer",
        exit_gate="failure reviewed", lanes=lane_pair("FAIL"),
        contract=failed_contract,
    )
    failed_result = settle_plan(failed_run, failed_plan, failed=True)
    failed_end = loop_journal.append_event(
        failed_run,
        "cycle_end",
        next_action="运行 check_run 验证当前计划",
    )
    checks.append(("failed Agent runtime unlocks Reviewer then closes as failed",
                   failed_result["projection"]["lane_states"][0]["runtime_state"] == "failed"
                   and failed_end["data"]["merge_disposition_summary"]["failed"]
                   == [failed_result["target"]["agent"]]))

    # Same-stage replans may supersede untouched lanes, but not real assignment debt.
    replan_run, replan_contract = make_run("replan")
    first = commit_plan(
        replan_run, macro_stage="S1", objective="initial inventory",
        mode="SERIAL_AGENT", reason="execution then Reviewer", exit_gate="inventory",
        lanes=lane_pair("R1"), contract=replan_contract,
    )
    second = commit_plan(
        replan_run, macro_stage="S1", objective="expanded untouched inventory",
        mode="SERIAL_AGENT", reason="execution then Reviewer", exit_gate="inventory",
        lanes=lane_pair("R2"), replan_reason="unassigned lanes superseded",
        contract=replan_contract,
    )
    checks.append(("same-stage replan may supersede wholly unassigned prior lanes",
                   first["plan_digest"] != second["plan_digest"]))
    workers.create_agent_assignment(
        replan_run, role="web-hunter", front="F-001", assets=[], lane_id="L-R2-EXEC")
    assignment_debt_blocked = False
    try:
        commit_plan(
            replan_run, macro_stage="S1", objective="illegal active replan",
            mode="SERIAL_AGENT", reason="execution then Reviewer", exit_gate="inventory",
            lanes=lane_pair("R3"), replan_reason="skip assigned lane",
            contract=replan_contract,
        )
    except PlanError as exc:
        assignment_debt_blocked = str(exc) == "WORK_PLAN_REPLAN_ASSIGNMENT_DEBT"
    checks.append(("same-stage replan cannot discard real assignment debt",
                   assignment_debt_blocked))

    topology_blocked = False
    try:
        _validate_reviewer_topology("SERIAL_AGENT", [lane_pair("BAD2")[0]])
    except PlanError as exc:
        topology_blocked = str(exc) == "WORK_PLAN_REVIEWER_TOPOLOGY_REQUIRED"
    checks.append(("Agent plan requires execution -> exactly-one Reviewer topology",
                   topology_blocked))

    serial_chain = lane_pair("CHAIN1")
    second_pair = lane_pair("CHAIN2")
    second_pair[0]["dependencies"] = [serial_chain[1]["id"]]
    valid_chain = serial_chain + second_pair
    chain_valid = True
    try:
        _validate_reviewer_topology("SERIAL_AGENT", valid_chain)
    except PlanError:
        chain_valid = False
    branched_chain = [dict(item) for item in valid_chain]
    third_pair = lane_pair("CHAIN3")
    third_pair[0]["dependencies"] = [serial_chain[1]["id"]]
    branch_blocked = False
    try:
        _validate_reviewer_topology("SERIAL_AGENT", branched_chain + third_pair)
    except PlanError as exc:
        branch_blocked = str(exc) == "WORK_PLAN_SERIAL_REVIEWER_BRANCH_FORBIDDEN"
    multiple_predecessors = [dict(item) for item in valid_chain]
    multiple_predecessors[2]["dependencies"] = [
        serial_chain[1]["id"], second_pair[1]["id"],
    ]
    multi_dependency_blocked = False
    try:
        _validate_reviewer_topology("SERIAL_AGENT", multiple_predecessors)
    except PlanError as exc:
        multi_dependency_blocked = (
            str(exc) == "WORK_PLAN_SERIAL_EXECUTION_EXACT_REVIEWER_DEPENDENCY")
    detached_cycle = lane_pair("DETACH1")
    detached_component = lane_pair("DETACH2")
    detached_component[0]["dependencies"] = [detached_component[1]["id"]]
    disconnected_blocked = False
    try:
        _validate_reviewer_topology(
            "SERIAL_AGENT", detached_cycle + detached_component)
    except PlanError as exc:
        disconnected_blocked = str(exc) == "WORK_PLAN_SERIAL_TOPOLOGY_DISCONNECTED"
    empty_front_blocked = False
    no_front = [dict(item) for item in lane_pair("NOFRONT")]
    no_front[0].pop("front", None)
    try:
        _validate_reviewer_topology("SERIAL_AGENT", no_front)
    except PlanError as exc:
        empty_front_blocked = str(exc) == "WORK_PLAN_AGENT_FRONT_REQUIRED"
    reviewer_effect_blocked = False
    bad_review_effect = [dict(item) for item in lane_pair("REVIEWFX")]
    bad_review_effect[1]["effect"] = "target"
    try:
        _validate_reviewer_topology("SERIAL_AGENT", bad_review_effect)
    except PlanError as exc:
        reviewer_effect_blocked = str(exc) == "WORK_PLAN_REVIEWER_EFFECT_INVALID"
    checks += [
        ("SERIAL_AGENT accepts one connected execution-review chain", chain_valid),
        ("SERIAL_AGENT forbids one Reviewer branching to two executions",
         branch_blocked),
        ("SERIAL_AGENT non-initial execution has exactly one Reviewer predecessor",
         multi_dependency_blocked),
        ("SERIAL_AGENT rejects a detached lane component", disconnected_blocked),
        ("Agent-mode lanes require a concrete front", empty_front_blocked),
        ("Reviewer lanes are local_verify only", reviewer_effect_blocked),
    ]

    # A completed Reviewer alone is insufficient: the exact execution it
    # reviewed must also have its projection-complete Root disposition before
    # the next execution becomes ready.
    dependency_plan = {
        "plan_digest": "e" * 64,
        "lanes": [
            {"id": "L-DEP-EXEC", "role": "hunter", "dependencies": []},
            {"id": "L-DEP-REVIEW", "role": "review",
             "dependencies": ["L-DEP-EXEC"]},
            {"id": "L-DEP-NEXT", "role": "hunter",
             "dependencies": ["L-DEP-REVIEW"]},
        ],
    }
    dependency_states = [
        {"lane_id": "L-DEP-EXEC", "runtime_state": "returned",
         "complete": False, "disposition": "pending"},
        {"lane_id": "L-DEP-REVIEW", "runtime_state": "returned",
         "complete": True, "disposition": "reviewed"},
        {"lane_id": "L-DEP-NEXT", "runtime_state": "unassigned",
         "complete": False, "disposition": "pending"},
    ]
    with mock.patch.object(run_model, "plan_cycle_projection", return_value={
            "plan_digest": dependency_plan["plan_digest"],
            "lane_states": dependency_states}):
        target_pending_blocks = not lane_dependencies_satisfied(
            root, dependency_plan, dependency_plan["lanes"][2])
    dependency_states[0] = dict(
        dependency_states[0], complete=True, disposition="merged")
    with mock.patch.object(run_model, "plan_cycle_projection", return_value={
            "plan_digest": dependency_plan["plan_digest"],
            "lane_states": dependency_states}):
        target_complete_unlocks = lane_dependencies_satisfied(
            root, dependency_plan, dependency_plan["lanes"][2])
    checks += [
        ("Reviewer complete cannot bypass incomplete reviewed execution",
         target_pending_blocks),
        ("Reviewer plus reviewed execution projection-complete unlocks successor",
         target_complete_unlocks),
    ]

    strict_bool = False
    malformed = dict(lane_pair("BOOL")[0], atomic="false")
    try:
        normalize_lane(malformed)
    except PlanError as exc:
        strict_bool = str(exc) == "WORK_PLAN_ATOMIC_BOOLEAN_REQUIRED"
    checks.append(("atomic is a strict JSON boolean", strict_bool))

    noncanonical_roles_rejected = True
    for invalid_role in ("web", "hunter", "reviewer", " web-hunter ", "WEB-HUNTER"):
        try:
            normalize_lane(dict(lane_pair("ROLE")[0], role=invalid_role))
        except PlanError as exc:
            noncanonical_roles_rejected &= str(exc) == "WORK_PLAN_LANE_ROLE_INVALID"
        else:
            noncanonical_roles_rejected = False
    checks.append((
        "work-plan lanes freeze canonical Agent roles without alias fallback",
        noncanonical_roles_rejected,
    ))

    direct_run, direct_contract = make_run("root-direct")
    direct_lane = dict(
        lane_pair("DIRECT")[0], id="L-DIRECT", atomic=True,
        request_budget=0, request_cost=0,
        capability_id="read.run-model",
    )
    direct_plan = commit_plan(
        direct_run, macro_stage="S1", objective="one atomic read",
        mode="ROOT_DIRECT", reason="mechanically atomic", exit_gate="receipt",
        lanes=[direct_lane], contract=direct_contract,
    )
    direct_blocked = False
    try:
        loop_journal.append_event(
            direct_run,
            "cycle_end",
            next_action="运行 check_run 验证当前计划",
        )
    except loop_journal.JournalContractError as exc:
        direct_blocked = exc.code == "CYCLE_EVENT_PLAN_DEBT_OPEN"
    checks.append(("ROOT_DIRECT remains fail-closed without typed action receipt",
                   direct_plan["execution_mode"] == "ROOT_DIRECT" and direct_blocked))

    def root_direct_binding_error(lane: dict) -> str:
        try:
            _validate_capability_binding("ROOT_DIRECT", [lane])
        except PlanError as exc:
            return str(exc)
        return ""

    direct_without_capability = dict(direct_lane)
    direct_without_capability.pop("capability_id")
    direct_unknown_capability = dict(
        direct_lane, capability_id="read.not-registered")
    direct_ineligible_capability = dict(
        direct_lane, capability_id="read.work-plan")
    direct_effect_mismatch = dict(direct_lane, effect="local_verify")
    agent_with_capability = [dict(item) for item in lane_pair("CAPAGENT")]
    agent_with_capability[0]["capability_id"] = "read.run-model"
    agent_capability_error = ""
    try:
        _validate_capability_binding("SERIAL_AGENT", agent_with_capability)
    except PlanError as exc:
        agent_capability_error = str(exc)
    malformed_capability_error = ""
    try:
        normalize_lane(dict(direct_lane, capability_id=" read.run-model"))
    except PlanError as exc:
        malformed_capability_error = str(exc)
    checks += [
        ("ROOT_DIRECT plan freezes one exact capability id",
         direct_plan["lanes"][0].get("capability_id") == "read.run-model"),
        ("ROOT_DIRECT requires a capability id",
         root_direct_binding_error(direct_without_capability)
         == "WORK_PLAN_ROOT_DIRECT_CAPABILITY_REQUIRED"),
        ("ROOT_DIRECT rejects an unknown capability id",
         root_direct_binding_error(direct_unknown_capability)
         == "WORK_PLAN_ROOT_DIRECT_CAPABILITY_UNKNOWN"),
        ("ROOT_DIRECT rejects a registered but ineligible capability",
         root_direct_binding_error(direct_ineligible_capability)
         == "WORK_PLAN_ROOT_DIRECT_CAPABILITY_INELIGIBLE"),
        ("ROOT_DIRECT capability effect must exactly equal the lane effect",
         root_direct_binding_error(direct_effect_mismatch)
         == "WORK_PLAN_ROOT_DIRECT_CAPABILITY_EFFECT_MISMATCH"),
        ("Agent modes cannot carry a ROOT_DIRECT capability binding",
         agent_capability_error == "WORK_PLAN_AGENT_CAPABILITY_FORBIDDEN"),
        ("capability ids reject whitespace normalization fallback",
         malformed_capability_error == "WORK_PLAN_CAPABILITY_ID_INVALID"),
    ]

    work_plan_schema = json.loads((
        ROOT / "contracts" / "work-plan.v1.schema.json"
    ).read_text(encoding="utf-8", errors="strict"))
    root_receipt_schema = json.loads((
        ROOT / "contracts" / "root-action-receipt.v1.schema.json"
    ).read_text(encoding="utf-8", errors="strict"))

    def schema_errors(value: object, schema: dict) -> list[str]:
        return runtime_receipts._selftest_schema_errors(value, schema)

    direct_schema_missing = json.loads(json.dumps(direct_plan))
    direct_schema_missing["lanes"][0].pop("capability_id")
    agent_schema_extra = json.loads(json.dumps(s3_plan))
    agent_schema_extra["lanes"][0]["capability_id"] = "read.run-model"
    root_receipt = {
        "schema": "xunji.root-action-receipt.v1",
        "parent_run": direct_run.name,
        "plan_id": direct_plan["plan_id"],
        "plan_digest": direct_plan["plan_digest"],
        "cycle_id": direct_plan["cycle_id"],
        "lane_id": "L-DIRECT",
        "capability_id": "read.run-model",
        "capability_effect": "local_read",
        "session_id": direct_contract["session_id"],
        "prompt_sha256": direct_contract["prompt_sha256"],
        "tool_use_id": "root-action-tool-1",
        "action_sha256": "b" * 64,
        "claim_event_seq": 1,
        "claim_event_hash": "c" * 64,
        "runtime_event_seq": 2,
        "runtime_event_hash": "d" * 64,
        "outcome": "succeeded",
        "response_sha256": "e" * 64,
        "recorded_at": "2026-07-17T12:00:00.000Z",
        "receipt_hash": "",
    }
    root_receipt["receipt_hash"] = _hash({
        key: value for key, value in root_receipt.items()
        if key != "receipt_hash"
    })
    receipt_unknown = dict(root_receipt, assignment="A-forged-001")
    receipt_missing = dict(root_receipt)
    receipt_missing.pop("runtime_event_hash")
    receipt_bool_seq = dict(root_receipt, runtime_event_seq=True)
    receipt_bad_outcome = dict(root_receipt, outcome="complete")
    receipt_bad_effect = dict(root_receipt, capability_effect="model_egress")
    receipt_bad_time = dict(root_receipt, recorded_at="eventually")
    checks += [
        ("ROOT_DIRECT work-plan schema requires capability_id",
         not schema_errors(direct_plan, work_plan_schema)
         and bool(schema_errors(direct_schema_missing, work_plan_schema))),
        ("Agent work-plan schema forbids capability_id",
         not schema_errors(s3_plan, work_plan_schema)
         and bool(schema_errors(agent_schema_extra, work_plan_schema))),
        ("root-action receipt positive fixture conforms to its exact schema",
         not schema_errors(root_receipt, root_receipt_schema)),
        ("root-action receipt schema rejects Agent/reviewer-style extra fields",
         bool(schema_errors(receipt_unknown, root_receipt_schema))),
        ("root-action receipt schema rejects missing runtime binding",
         bool(schema_errors(receipt_missing, root_receipt_schema))),
        ("root-action receipt schema rejects bool-as-sequence",
         bool(schema_errors(receipt_bool_seq, root_receipt_schema))),
        ("root-action receipt schema rejects unknown outcomes/effects",
         bool(schema_errors(receipt_bad_outcome, root_receipt_schema))
         and bool(schema_errors(receipt_bad_effect, root_receipt_schema))),
        ("root-action receipt schema rejects non-ISO timestamps",
         bool(schema_errors(receipt_bad_time, root_receipt_schema))),
    ]

    bad = [name for name, ok in checks if not ok]
    for name, ok in checks:
        print(("ok   " if ok else "FAIL ") + name)
    print("work_plan selftest " + ("passed" if not bad else f"FAILED ({len(bad)})"))
    return 0 if not bad else 1


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="commit/validate a Xunji work plan")
    parser.add_argument("--selftest", action="store_true")
    sub = parser.add_subparsers(dest="command")
    commit = sub.add_parser("commit")
    commit.add_argument("run_dir")
    commit.add_argument("--stage", required=True, choices=sorted(STAGES))
    commit.add_argument("--objective", required=True)
    commit.add_argument("--mode", required=True, choices=sorted(MODES))
    commit.add_argument("--reason", required=True)
    commit.add_argument("--exit-gate", required=True)
    commit.add_argument("--replan-reason", default="")
    commit.add_argument("--lane", action="append", type=_parse_lane_json, required=True)
    status = sub.add_parser("status")
    status.add_argument("run_dir")
    status.add_argument("--json", action="store_true")
    migration = sub.add_parser(
        "migrate-legacy",
        help="explicitly admit one pre-transaction plan from its typed journal",
    )
    migration.add_argument("run_dir")
    args = parser.parse_args(argv)
    if args.selftest:
        return _selftest()
    if args.command == "commit":
        try:
            plan = commit_plan(
                args.run_dir, macro_stage=args.stage, objective=args.objective,
                mode=args.mode, reason=args.reason, exit_gate=args.exit_gate,
                lanes=args.lane, replan_reason=args.replan_reason,
            )
        except PlanError as exc:
            print(f"[work-plan] ERROR {exc}", file=sys.stderr)
            return 1
        print(json.dumps(plan, ensure_ascii=False, indent=2))
        return 0
    if args.command == "status":
        try:
            contract = _load_turn_contract(_resolve_run(args.run_dir))
            plan = current_plan(args.run_dir, contract)
            value = {"current": True, "plan": plan}
        except PlanError as exc:
            value = {"current": False, "error": str(exc), "plan": load_plan(args.run_dir)}
        if args.json:
            print(json.dumps(value, ensure_ascii=False, indent=2))
        else:
            print(
                f"current={str(value['current']).lower()} "
                f"mode={(value.get('plan') or {}).get('execution_mode', '-')} "
                f"error={value.get('error', '-')}"
            )
        return 0 if value["current"] else 1
    if args.command == "migrate-legacy":
        try:
            plan = migrate_legacy_plan(
                args.run_dir, acknowledge_unreceipted_plan=True)
            transaction = _load_transaction(_resolve_run(args.run_dir))
        except PlanError as exc:
            print(f"[work-plan] ERROR {exc}", file=sys.stderr)
            return 1
        print(json.dumps({
            "migrated": True,
            "plan_id": plan["plan_id"],
            "plan_digest": plan["plan_digest"],
            "transaction_id": transaction["transaction_id"],
            "provenance": transaction["provenance"],
            "migration_source_digest": transaction["migration_source_digest"],
        }, ensure_ascii=False, indent=2))
        return 0
    parser.error("command is required")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
