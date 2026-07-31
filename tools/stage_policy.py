#!/usr/bin/env python3
"""Mechanical S1/S2/S3 policy projection for Xunji work plans.

Root owns strategy and chooses the macro-stage.  This module only derives the
named inputs, default resource posture, exit facts, and lane-shape violations
that deterministic code can verify.  It never promotes evidence, selects an
attack, or writes canonical run state.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib
import json
import re
import tempfile
from pathlib import Path
from unittest import mock


SCHEMA = "xunji.stage-policy.v1"
STAGES = ("S1", "S2", "S3")

PROFILES = {
    "S1": {
        "goal": "information-collection",
        "ready_effect_order": ["local_read", "local_verify", "model_egress", "target"],
        "target_fanout": "deferred-until-offline-review",
        "review_breadth": "per-execution",
        "exit_requirements": [
            "scope_inventory", "source_inventory", "asset_inventory",
            "application_clusters", "technology_inventory",
            "knowledge_grounding", "coverage_ledger", "initial_fronts",
        ],
        "output_ceiling": "observation-or-candidate",
    },
    "S2": {
        "goal": "testing-and-continuous-review",
        "ready_effect_order": ["target", "local_verify", "local_read", "model_egress"],
        "target_fanout": "one-ready-lane-per-asset",
        "review_breadth": "immediate-per-execution-and-checkpoint-on-conflict",
        "exit_requirements": [
            "no_open_fronts", "no_type_a_fronts", "coverage_explained",
            "zero_merge_debt", "zero_review_debt",
        ],
        "output_ceiling": "candidate-until-synthesizer-promotion",
    },
    "S3": {
        "goal": "final-closure",
        "ready_effect_order": ["local_verify", "model_egress", "local_read", "target"],
        "target_fanout": "at-most-one-target-lane",
        "review_breadth": "independent-review-and-report-parity",
        "exit_requirements": [
            "check_run", "independent_review", "report_evidence_parity",
            "zero_agent_debt", "retrospective", "terminal_journal",
        ],
        "output_ceiling": "root-single-writer",
    },
}


def _regular_file(path: Path, run: Path) -> bool:
    try:
        return path.is_file() and not path.is_symlink() and path.resolve().is_relative_to(run)
    except (OSError, RuntimeError, ValueError):
        return False


def _digest(path: Path, run: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest() if _regular_file(path, run) else ""


def _text(path: Path, run: Path) -> str:
    return path.read_text(encoding="utf-8", errors="replace") if _regular_file(path, run) else ""


def _json(path: Path, run: Path) -> dict:
    if not _regular_file(path, run):
        return {}
    try:
        value = json.loads(path.read_text(encoding="utf-8", errors="strict"))
        return value if isinstance(value, dict) else {}
    except Exception:
        return {}


def _meaningful(text: str) -> bool:
    body = [
        line.strip() for line in text.splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    ]
    return any(
        value not in {"-", "none", "n/a", "todo", "pending", "unknown", "待补充", "待确认"}
        for value in (line.lower().lstrip("-* ").strip() for line in body)
    )


def _front_rows(text: str) -> list[dict]:
    rows: list[dict] = []
    for match in re.finditer(
        r"(?ms)^###\s+(F-\d+[A-Za-z]*)(?P<body>.*?)(?=^###\s+F-\d+[A-Za-z]*|\Z)",
        text,
    ):
        body = match.group("body")
        status_match = re.search(
            r"(?im)^\s*[-*]?\s*Status\s*[:：]\s*([^\n]+)", body
        )
        rows.append({
            "id": match.group(1),
            "status": (status_match.group(1).strip().lower() if status_match else ""),
        })
    return rows


def _knowledge_ready(run: Path) -> bool:
    # Formal setup writes knowledge_hits.md even when there are zero matches.
    # A legacy/minimal run without setup_source is not made invalid merely for
    # predating that projection.
    formal = _regular_file(run / "state" / "setup_source.json", run)
    return (
        _regular_file(run / "knowledge_hits.md", run)
        if formal else True
    )


def _lifecycle_facts(
    run: Path,
) -> tuple[dict[str, bool | None], list[str]]:
    """Project facts only from their canonical owners; unknown stays fail-closed."""
    facts: dict[str, bool | None] = {
        "zero_merge_debt": None,
        "zero_review_debt": None,
        "zero_agent_debt": None,
        "terminal_journal": None,
    }
    diagnostics: list[str] = []
    try:
        run_model = importlib.import_module("run_model")
        debt = run_model.plan_bound_agent_debt(run)
        zero_merge = not debt.get("merge")
        zero_review = not debt.get("review")
        facts.update({
            "zero_merge_debt": zero_merge,
            "zero_review_debt": zero_review,
            "zero_agent_debt": zero_merge and zero_review,
        })
    except Exception as exc:
        diagnostics.append(
            f"STAGE_POLICY_OWNER_UNAVAILABLE:run_model:{type(exc).__name__}"
        )
    try:
        loop_journal = importlib.import_module("loop_journal")
        journal = loop_journal.summarize(run)
        facts["terminal_journal"] = bool(
            journal.get("typed_contract_valid") is True
            and journal.get("incomplete_cycle") is False
            and not journal.get("open_phase")
            and "cycle_end" in journal.get("last_cycle_events", [])
        )
    except Exception as exc:
        diagnostics.append(
            f"STAGE_POLICY_OWNER_UNAVAILABLE:loop_journal:{type(exc).__name__}"
        )
    return facts, diagnostics


def project(run_dir: str | Path, stage: str, lanes: list[dict] | None = None) -> dict:
    run = Path(run_dir).resolve()
    if not run.is_dir():
        raise ValueError("STAGE_POLICY_RUN_REQUIRED")
    stage = str(stage or "").strip().upper()
    if stage not in STAGES:
        raise ValueError("STAGE_POLICY_STAGE_INVALID")

    target = _text(run / "target.md", run)
    surface = "\n".join([
        _text(run / "surface.md", run),
        _text(run / "surface_recon.md", run),
    ])
    coverage = _json(run / "coverage.json", run)
    assets = coverage.get("assets") if isinstance(coverage.get("assets"), list) else []
    asset_ledger = _json(run / "state" / "asset_ledger.json", run)
    ledger_assets = (
        asset_ledger.get("assets")
        if isinstance(asset_ledger.get("assets"), list) else []
    )
    fronts = _front_rows(_text(run / "frontier.md", run))
    open_status = {"open", "probing", "deferred", "blocked_type_a"}
    open_fronts = [row["id"] for row in fronts if row["status"] in open_status]
    type_a = [
        row["id"] for row in fronts
        if row["status"] in {"deferred", "blocked_type_a"}
    ]
    source_ready = (
        _regular_file(run / "state" / "setup_source.json", run)
        or _meaningful(target)
    )
    asset_ready = bool(assets or ledger_assets or _meaningful(surface))
    technology_ready = bool(re.search(
        r"(?i)\b(?:technology|tech(?:nology)? stack|fingerprint|framework|server|技术栈|指纹)\b",
        surface,
    ))
    lifecycle, lifecycle_diagnostics = _lifecycle_facts(run)
    facts = {
        "scope_inventory": _meaningful(target),
        "source_inventory": source_ready,
        "asset_inventory": asset_ready,
        "application_clusters": bool(fronts),
        "technology_inventory": technology_ready,
        "knowledge_grounding": _knowledge_ready(run),
        "coverage_ledger": bool(assets),
        "initial_fronts": bool(fronts),
        "no_open_fronts": not open_fronts,
        "no_type_a_fronts": not type_a,
        "coverage_explained": bool(assets),
        "zero_merge_debt": lifecycle["zero_merge_debt"],
        "zero_review_debt": lifecycle["zero_review_debt"],
        # check_run and report parity remain explicit owner dependencies.  This
        # read-only projection never substitutes a weaker duplicate predicate.
        "check_run": None,
        "independent_review": None,
        "report_evidence_parity": None,
        "zero_agent_debt": lifecycle["zero_agent_debt"],
        "retrospective": _meaningful(_text(run / "retrospective.md", run)),
        "terminal_journal": lifecycle["terminal_journal"],
    }
    requirements = list(PROFILES[stage]["exit_requirements"])
    missing = [name for name in requirements if facts.get(name) is not True]
    owner_required = [
        name for name in requirements if facts.get(name) is None
    ]
    lane_issues = validate_lane_shape(stage, lanes or [])
    input_paths = [
        "target.md", "surface.md", "surface_recon.md", "frontier.md",
        "knowledge_hits.md", "coverage.json", "state/setup_source.json",
        "state/asset_ledger.json",
    ]
    inputs = {
        name: _digest(run / name, run)
        for name in input_paths
        if _regular_file(run / name, run)
    }
    return {
        "schema": SCHEMA,
        "stage": stage,
        "profile": PROFILES[stage],
        "facts": facts,
        "missing_exit_facts": missing,
        "owner_required_exit_facts": owner_required,
        "owner_diagnostics": lifecycle_diagnostics,
        "exit_ready": False if missing else True,
        "lane_issues": lane_issues,
        "canonical_input_digests": inputs,
        "open_fronts": open_fronts,
        "type_a_fronts": type_a,
        "authority": "Root chooses stage; this projection only checks deterministic facts",
    }


def _lane(value: dict) -> dict:
    return value.get("work_plan_lane", value) if isinstance(value, dict) else {}


def _reviewer_dependencies(lanes: list[dict]) -> set[str]:
    return {
        str(dep)
        for item in lanes
        if str(item.get("role") or "") == "review"
        for dep in item.get("dependencies", [])
    }


def validate_lane_shape(
    stage: str,
    lanes: list[dict],
    *,
    require_reviewer: bool = True,
) -> list[str]:
    stage = str(stage or "").strip().upper()
    if stage not in STAGES:
        return ["STAGE_POLICY_STAGE_INVALID"]
    normalized = [_lane(item) for item in lanes]
    normalized = [item for item in normalized if isinstance(item, dict) and item]
    issues: list[str] = []
    execution = [item for item in normalized if item.get("role") != "review"]
    reviewers = _reviewer_dependencies(normalized)
    if require_reviewer:
        for item in execution:
            lane_id = str(item.get("id") or "")
            if lane_id and lane_id not in reviewers:
                issues.append(f"STAGE_POLICY_REVIEWER_REQUIRED:{lane_id}")

    ready = [item for item in execution if not item.get("dependencies")]
    if stage == "S1":
        for item in execution:
            if item.get("effect") == "target":
                issues.append(
                    f"STAGE_POLICY_S1_OFFLINE_FIRST:{item.get('id') or '(unknown)'}"
                )
    elif stage == "S2":
        seen_target_assets: set[str] = set()
        for item in ready:
            if item.get("effect") != "target":
                continue
            assets = {str(value) for value in item.get("assets", [])}
            overlap = seen_target_assets & assets
            if overlap:
                issues.append(
                    "STAGE_POLICY_S2_TARGET_OVERLAP:" + ",".join(sorted(overlap))
                )
            seen_target_assets.update(assets)
    else:
        target_lanes = [item for item in execution if item.get("effect") == "target"]
        if len(target_lanes) > 1:
            issues.append("STAGE_POLICY_S3_TARGET_FANOUT")
        forbidden_writer = [
            str(item.get("id") or "")
            for item in normalized
            if item.get("effect") in {"control", "repo_mutation"}
        ]
        if forbidden_writer:
            issues.append(
                "STAGE_POLICY_S3_SINGLE_WRITER:" + ",".join(forbidden_writer)
            )
    return issues


def _selftest() -> int:
    root = Path(tempfile.mkdtemp()) / "run"
    (root / "state").mkdir(parents=True)
    (root / "target.md").write_text(
        "# Target\n- In-scope assets: app.example\n", encoding="utf-8"
    )
    (root / "surface.md").write_text(
        "# Surface\n- Technology stack: Example/1\n", encoding="utf-8"
    )
    (root / "frontier.md").write_text(
        "# Frontier\n### F-001\n- Status: open\n", encoding="utf-8"
    )
    (root / "coverage.json").write_text(
        '{"assets":[{"host":"app.example"}]}\n', encoding="utf-8"
    )
    (root / "knowledge_hits.md").write_text(
        "# Knowledge Hits\n- none\n", encoding="utf-8"
    )
    (root / "state" / "setup_source.json").write_text(
        '{"schema":"xunji.setup-source.v1"}\n', encoding="utf-8"
    )
    (root / "state" / "asset_ledger.json").write_text(
        '{"assets":[{"host":"app.example"}]}\n', encoding="utf-8"
    )
    execution = {
        "id": "L-LOCAL", "role": "surface", "effect": "local_read",
        "assets": ["app.example"], "dependencies": [],
    }
    reviewer = {
        "id": "L-LOCAL-REVIEW", "role": "review", "effect": "local_verify",
        "assets": ["app.example"], "dependencies": ["L-LOCAL"],
    }
    s1 = project(root, "S1", [execution, reviewer])
    target_first = dict(execution, id="L-TARGET", effect="target")
    target_review = dict(
        reviewer, id="L-TARGET-REVIEW", dependencies=["L-TARGET"]
    )
    dependent_target = dict(
        target_first, id="L-TARGET-LATER", dependencies=["L-LOCAL"])
    dependent_target_review = dict(
        reviewer, id="L-TARGET-LATER-REVIEW",
        dependencies=["L-TARGET-LATER"])
    with mock.patch.object(
        importlib, "import_module", side_effect=RuntimeError("owner drift")
    ):
        owner_unavailable = project(root, "S3")
    checks = [
        ("S1 projects complete collection inputs",
         not {"scope_inventory", "source_inventory", "asset_inventory",
              "application_clusters", "technology_inventory",
              "knowledge_grounding", "coverage_ledger", "initial_fronts"}
         & set(s1["missing_exit_facts"])),
        ("S1 accepts reviewed offline-first lane",
         s1["lane_issues"] == []),
        ("S1 ROOT_DIRECT shape applies stage policy without synthetic Reviewer",
         validate_lane_shape(
             "S1", [execution], require_reviewer=False) == []),
        ("S1 ROOT_DIRECT still rejects target effect",
         "STAGE_POLICY_S1_OFFLINE_FIRST:L-TARGET"
         in validate_lane_shape(
             "S1", [target_first], require_reviewer=False)),
        ("S3 keeps closure-owner facts explicitly fail closed",
         {"check_run", "independent_review", "report_evidence_parity"}
         <= set(project(root, "S3")["owner_required_exit_facts"])),
        ("owner drift stays fail closed with stable diagnostics",
         owner_unavailable["facts"]["zero_agent_debt"] is None
         and owner_unavailable["facts"]["terminal_journal"] is None
         and owner_unavailable["owner_diagnostics"] == [
             "STAGE_POLICY_OWNER_UNAVAILABLE:run_model:RuntimeError",
             "STAGE_POLICY_OWNER_UNAVAILABLE:loop_journal:RuntimeError",
         ]),
        ("S1 rejects a ready target lane",
         "STAGE_POLICY_S1_OFFLINE_FIRST:L-TARGET"
         in validate_lane_shape("S1", [target_first, target_review])),
        ("S1 rejects a target lane hidden behind a dependency",
         "STAGE_POLICY_S1_OFFLINE_FIRST:L-TARGET-LATER"
         in validate_lane_shape(
             "S1", [execution, reviewer, dependent_target,
                    dependent_target_review])),
        ("S2 rejects ready same-asset target overlap",
         any(item.startswith("STAGE_POLICY_S2_TARGET_OVERLAP")
             for item in validate_lane_shape("S2", [
                 target_first, target_review,
                 dict(target_first, id="L-TARGET2"),
                 dict(target_review, id="L-TARGET2-REVIEW",
                      dependencies=["L-TARGET2"]),
             ]))),
        ("S3 rejects multiple ready target lanes",
         "STAGE_POLICY_S3_TARGET_FANOUT" in validate_lane_shape("S3", [
             target_first, target_review,
             dict(target_first, id="L-TARGET2", assets=["two.example"]),
             dict(target_review, id="L-TARGET2-REVIEW",
                 dependencies=["L-TARGET2"]),
         ])),
        ("S3 rejects multiple target lanes even when one is not ready",
         "STAGE_POLICY_S3_TARGET_FANOUT" in validate_lane_shape("S3", [
             target_first, target_review,
             dict(target_first, id="L-TARGET2",
                  assets=["two.example"], dependencies=["L-TARGET-REVIEW"]),
             dict(target_review, id="L-TARGET2-REVIEW",
                  dependencies=["L-TARGET2"]),
         ])),
        ("stage projection is read-only",
         not (root / "state" / "stage_policy.json").exists()),
    ]
    failed = [name for name, ok in checks if not ok]
    for name, ok in checks:
        print(("ok   " if ok else "FAIL ") + name)
    print(f"stage policy selftest {'passed' if not failed else 'FAILED'}")
    return 0 if not failed else 1


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Project deterministic S1/S2/S3 policy facts without choosing strategy"
    )
    parser.add_argument("run_dir", nargs="?")
    parser.add_argument("--stage", choices=STAGES)
    parser.add_argument("--selftest", action="store_true")
    args = parser.parse_args(argv)
    if args.selftest:
        return _selftest()
    if not args.run_dir or not args.stage:
        parser.error("run_dir and --stage are required")
    print(json.dumps(project(args.run_dir, args.stage), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
