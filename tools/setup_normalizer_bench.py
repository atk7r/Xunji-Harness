#!/usr/bin/env python3
"""Offline A/B and hard-gate benchmark for the setup normalizer pilot.

This benchmark never calls a model or target.  ``off`` measures the deterministic
baseline.  ``reference_candidate`` is an oracle selection over IDs already exposed
by the redacted request; it proves the candidate contract can improve recall
without permitting hallucinated values.  It does not claim a live provider's
semantic quality.  Provider rollout still requires running the same cases through
that provider and comparing its candidate JSON against this report.
"""
from __future__ import annotations

import argparse
import json
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import setup_normalizer
import setup_source


ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "bench" / "setup-normalizer-pilot" / "cases.json"


def _hosts(manifest: dict) -> set[str]:
    return {
        str(item.get("host") or "")
        for item in manifest.get("assets", []) if isinstance(item, dict) and item.get("host")
    }


def _metric(expected: set[str], actual: set[str]) -> dict:
    true_positive = len(expected & actual)
    false_positive = len(actual - expected)
    missed = len(expected - actual)
    precision = true_positive / len(actual) if actual else (1.0 if not expected else 0.0)
    recall = true_positive / len(expected) if expected else 1.0
    return {
        "precision": round(precision, 6),
        "recall": round(recall, 6),
        "true_positive": true_positive,
        "false_positive": false_positive,
        "missed": missed,
        "hallucinated_assets": sorted(actual - expected),
        "missed_assets": sorted(expected - actual),
    }


def _write_case_source(case: dict, directory: Path) -> Path:
    kind = str(case.get("kind") or "")
    suffix = ".json" if kind == "json" else ".md"
    path = directory / f"{case['id']}{suffix}"
    if kind == "json":
        path.write_text(
            json.dumps(case.get("source_json"), ensure_ascii=False), encoding="utf-8"
        )
    else:
        path.write_text(str(case.get("source") or ""), encoding="utf-8")
    return path


def _oracle_candidate(request: dict, inventory: setup_normalizer.Inventory, expected: set[str]) -> dict:
    candidate = setup_normalizer.candidate_template(request)
    target = [item for item in inventory.tokens if "target" in item.roles]
    candidate["target_token"] = target[0].id if len(target) == 1 else None
    selected: list[str] = []
    for item in inventory.tokens:
        if item.kind not in {"url", "host"}:
            continue
        try:
            host = setup_source.parse_asset_value(item.value)[0]
        except setup_source.SetupSourceError:
            continue
        if host in expected:
            selected.append(item.id)
    candidate["asset_tokens"] = selected
    candidate["entry_tokens"] = [
        item.id for item in inventory.tokens
        if item.kind == "url" and setup_source.parse_asset_value(item.value)[0] in expected
    ]
    candidate["scope_refs"] = [
        item.id for item in inventory.references if "scope" in item.roles
    ]
    candidate["authorization_refs"] = [
        item.id for item in inventory.references if "authorization" in item.roles
    ]
    candidate["signal_refs"] = [
        item.id for item in inventory.references if "signal" in item.roles
    ]
    return candidate


def run_benchmark() -> dict:
    fixture = json.loads(FIXTURE.read_text(encoding="utf-8"))
    directory = Path(tempfile.mkdtemp())
    rows: list[dict] = []
    hard = {
        "unreferenced_high_risk_fields": 0,
        "hallucinated_assets": 0,
        "pointer_misselection": 0,
        "source_instruction_promotions": 0,
        "adapter_contract_mismatches": 0,
        "model_egress_leaks": 0,
        "unexpected_schema_failures": 0,
    }
    off_tp = off_fp = off_expected = 0
    candidate_tp = candidate_fp = candidate_expected = 0
    recall_improvements = 0

    for case in fixture.get("cases", []):
        path = _write_case_source(case, directory)
        case_id = str(case.get("id") or path.stem)
        if case.get("prepare_only"):
            request, _inventory = setup_normalizer.prepare_request(
                path, ai_mode="external", provider="fixture-provider", model="fixture-model"
            )
            serialized = json.dumps(request, ensure_ascii=False, sort_keys=True)
            leaks = [value for value in case.get("must_not_egress", []) if value in serialized]
            hard["model_egress_leaks"] += len(leaks)
            rows.append({"id": case_id, "prepare_only": True, "leaks": leaks})
            continue

        expected_reject = str(case.get("expect_reject") or "")
        if expected_reject:
            rejected: dict[str, str] = {}
            for mode in ("off", "reference_candidate"):
                try:
                    if mode == "off":
                        setup_normalizer.normalize_path(path, ai_mode="off")
                    else:
                        request, inventory = setup_normalizer.prepare_request(
                            path, ai_mode="external", provider="fixture-provider", model="fixture-model"
                        )
                        candidate = _oracle_candidate(request, inventory, set())
                        setup_normalizer.normalize_path(
                            path, ai_mode="external", candidate_json=json.dumps(candidate),
                            provider="fixture-provider", model="fixture-model",
                        )
                    rejected[mode] = "accepted"
                    hard["pointer_misselection"] += 1
                except setup_source.SetupSourceError as exc:
                    rejected[mode] = exc.code
                    if exc.code != expected_reject:
                        hard["unexpected_schema_failures"] += 1
            rows.append({"id": case_id, "expected_reject": expected_reject, "results": rejected})
            continue

        expected = set(map(str, case.get("expected_assets", [])))
        must_not = set(map(str, case.get("must_not_promote", [])))
        off_manifest, _raw, _artifacts = setup_normalizer.normalize_path(path, ai_mode="off")
        request, inventory = setup_normalizer.prepare_request(
            path, ai_mode="external", provider="fixture-provider", model="fixture-model"
        )
        candidate = _oracle_candidate(request, inventory, expected)
        candidate_manifest, _raw2, artifacts = setup_normalizer.normalize_path(
            path, ai_mode="external", candidate_json=json.dumps(candidate),
            provider="fixture-provider", model="fixture-model",
        )
        off_actual = _hosts(off_manifest)
        candidate_actual = _hosts(candidate_manifest)
        off_metric = _metric(expected, off_actual)
        candidate_metric = _metric(expected, candidate_actual)
        if candidate_metric["recall"] > off_metric["recall"]:
            recall_improvements += 1
        off_tp += off_metric["true_positive"]
        off_fp += off_metric["false_positive"]
        off_expected += len(expected)
        candidate_tp += candidate_metric["true_positive"]
        candidate_fp += candidate_metric["false_positive"]
        candidate_expected += len(expected)
        hard["hallucinated_assets"] += candidate_metric["false_positive"]
        hard["source_instruction_promotions"] += len(candidate_actual & must_not)
        if candidate_manifest["target"]["host"] != case.get("expected_target"):
            hard["pointer_misselection"] += 1
        expected_entries = set(map(str, case.get("expected_entries", [])))
        actual_entries = {
            str(item.get("value") or "")
            for item in candidate_manifest.get("entry_points", [])
            if isinstance(item, dict) and item.get("value")
        }
        hard["adapter_contract_mismatches"] += len(expected_entries - actual_entries)
        missing_refs = sum(
            1 for name in ("assets", "scope_candidates", "authorization_claims", "entry_points", "signals")
            for item in candidate_manifest.get(name, [])
            if isinstance(item, dict) and not str(item.get("source_ref") or "")
        )
        hard["unreferenced_high_risk_fields"] += missing_refs
        if not artifacts:
            hard["unexpected_schema_failures"] += 1
        rows.append({
            "id": case_id,
            "off": off_metric,
            "reference_candidate": candidate_metric,
            "off_matches_declared_baseline": off_actual == set(case.get("off_expected_assets", [])),
            "expected_entries_present": expected_entries <= actual_entries,
        })

    aggregate = {"off": {
        "precision": round(off_tp / (off_tp + off_fp), 6) if off_tp + off_fp else 1.0,
        "recall": round(off_tp / off_expected, 6) if off_expected else 1.0,
        "true_positive": off_tp, "false_positive": off_fp,
        "missed": max(0, off_expected - off_tp), "expected": off_expected,
    }, "reference_candidate": {
        "precision": round(candidate_tp / (candidate_tp + candidate_fp), 6)
        if candidate_tp + candidate_fp else 1.0,
        "recall": round(candidate_tp / candidate_expected, 6) if candidate_expected else 1.0,
        "true_positive": candidate_tp, "false_positive": candidate_fp,
        "missed": max(0, candidate_expected - candidate_tp),
        "expected": candidate_expected,
    }}
    hard_pass = all(value == 0 for value in hard.values())
    value_gate = recall_improvements >= 1 \
        and aggregate["reference_candidate"]["recall"] > aggregate["off"]["recall"] \
        and aggregate["reference_candidate"]["precision"] >= aggregate["off"]["precision"]
    return {
        "schema": "setup-normalizer-benchmark-result.v1",
        "fixture": str(FIXTURE.relative_to(ROOT)),
        "modes": {
            "off": "deterministic baseline",
            "reference_candidate": "offline oracle over redacted request IDs; not a live model score",
        },
        "cases": rows,
        "aggregate": aggregate,
        "hard_gates": hard,
        "hard_gate_pass": hard_pass,
        "value_gate_pass": value_gate,
        "provider_rollout": "not measured; run these requests through the named provider before enabling it by default",
        "clean": hard_pass and value_gate,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Offline setup-normalizer A/B benchmark")
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--selftest", action="store_true")
    args = parser.parse_args()
    result = run_benchmark()
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
    else:
        off = result["aggregate"]["off"]
        candidate = result["aggregate"]["reference_candidate"]
        print(
            "setup-normalizer bench: "
            f"off precision={off['precision']:.3f} recall={off['recall']:.3f}; "
            f"candidate precision={candidate['precision']:.3f} recall={candidate['recall']:.3f}; "
            f"hard_gates={'PASS' if result['hard_gate_pass'] else 'FAIL'}; "
            f"value_gate={'PASS' if result['value_gate_pass'] else 'FAIL'}"
        )
        for key, value in result["hard_gates"].items():
            print(f"  {key}: {value}")
    return 0 if result["clean"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
