"""Transaction-backed work-plan fixtures for cross-module selftests only."""
from __future__ import annotations

import json
import time
from pathlib import Path


_COMPLETION_FILES = (
    "surface.md", "surface_recon.md", "hypotheses.md", "evidence.md",
    "false_positive.md", "review.md", "report.md", "chains.md", "hints.md",
)


def lane_pairs(execution_count: int = 1) -> list[dict]:
    if isinstance(execution_count, bool) or execution_count < 1:
        raise ValueError("execution_count must be a positive integer")
    lanes: list[dict] = []
    for index in range(1, execution_count + 1):
        tag = f"F{index:03d}"
        execution = {
            "id": f"L-{tag}-EXEC",
            "role": "verify",
            "front": f"F-{index:03d}",
            "effect": "local_verify",
            "assets": [],
            "dependencies": [],
            "expected_evidence": "bounded selftest result",
            "expected_information_gain": "medium",
            "stop_condition": "result returned or launch failure recorded",
            "request_cost": 0,
            "request_budget": 0,
            "merge_cost": 2,
            "atomic": False,
        }
        reviewer = {
            "id": f"L-{tag}-REVIEW",
            "role": "review",
            "front": execution["front"],
            "effect": "local_verify",
            "assets": [],
            "dependencies": [execution["id"]],
            "expected_evidence": "digest-bound selftest disposition",
            "expected_information_gain": "medium",
            "stop_condition": "candidate accepted or challenged",
            "request_cost": 0,
            "request_budget": 0,
            "merge_cost": 2,
            "atomic": False,
        }
        lanes.extend((execution, reviewer))
    return lanes


def seed_current_plan(
    run_dir: str | Path,
    *,
    stage: str = "S1",
    execution_count: int = 1,
    mode: str = "",
    fault: object | None = None,
) -> tuple[dict, dict]:
    """Create one fresh run with a native committed current plan.

    This helper deliberately calls the production ``commit_plan`` transaction;
    it never hand-writes a plan, snapshot, journal event, or trust receipt.
    """
    if stage not in {"S1", "S2", "S3"}:
        raise ValueError("stage must be S1, S2, or S3")
    if isinstance(execution_count, bool) or execution_count < 1:
        raise ValueError("execution_count must be a positive integer")
    selected_mode = mode or (
        "COMPLETION_REVIEW" if stage == "S3" else
        "SERIAL_AGENT" if execution_count == 1 else "PARALLEL_AGENTS")
    if selected_mode == "SERIAL_AGENT" and execution_count != 1:
        raise ValueError("SERIAL_AGENT selftest fixture supports one execution")

    import work_plan

    run = Path(run_dir).resolve()
    (run / "state").mkdir(parents=True, exist_ok=True)
    if (run / "state" / "work_plan_transaction.json").exists() \
            or (run / "work_plan.json").exists():
        raise ValueError("selftest plan fixture requires a fresh plan owner")
    target_path = run / "target.md"
    if not target_path.exists():
        target_path.write_text(
            "# Target\n- Authorized scope: app.example\n", encoding="utf-8")
    (run / "coverage.json").write_text(json.dumps({
        "assets": [{"host": "app.example", "examined": stage != "S1"}],
    }), encoding="utf-8")
    section = "Closed Fronts" if stage == "S3" else "Open Fronts"
    status = "blocked_type_b" if stage == "S3" else "open"
    fronts = ["# Frontier", "", f"## {section}", ""]
    for index in range(1, execution_count + 1):
        fronts.extend((
            f"### F-{index:03d} — selftest front {index}",
            f"- Status: {status}",
            "- Barrier class: authorization",
            "- Current depth: moderate",
            "",
        ))
    (run / "frontier.md").write_text("\n".join(fronts), encoding="utf-8")
    for name in _COMPLETION_FILES:
        path = run / name
        if not path.exists():
            path.write_text(f"# {name}\n", encoding="utf-8")
    conflicts_path = run / "state" / "conflicts.json"
    if not conflicts_path.exists():
        conflicts_path.write_text("{}\n", encoding="utf-8")
    contract = {
        "schema": "xunji.turn_contract.v1",
        "mode": "EXECUTE",
        "session_id": f"session-{run.name}",
        "transcript_path": str(run / "selftest-transcript.jsonl"),
        "prompt_sha256": "a" * 64,
        "prompt_excerpt": "selftest execute turn",
        "memory_approved": False,
        "updated_at": time.time(),
        "fanout_override": False,
    }
    (run / "state" / "turn_contract.json").write_text(
        json.dumps(contract, sort_keys=True), encoding="utf-8")
    plan = work_plan.commit_plan(
        run,
        macro_stage=stage,
        objective=(
            "verify closure parity" if stage == "S3"
            else "exercise transaction-bound Agent runtime"
        ),
        mode=selected_mode,
        reason="selftest uses the production work-plan transaction",
        exit_gate="selftest result is reviewed and dispositioned",
        lanes=[] if selected_mode == "COMPLETION_REVIEW" \
            else lane_pairs(execution_count),
        contract=contract,
        fault=fault,
    )
    if work_plan.transaction_bound_plan(run).get("plan_digest") \
            != plan.get("plan_digest") \
            or work_plan.current_plan(run, contract).get("plan_digest") \
            != plan.get("plan_digest"):
        raise AssertionError("selftest fixture did not create one current plan")
    return contract, plan
