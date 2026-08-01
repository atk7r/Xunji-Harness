#!/usr/bin/env python3
"""Check that workflow reference excerpts stay aligned with run templates."""
from __future__ import annotations

import argparse
import json
import re
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DRIVER_DOC_FIXTURE = (
    ROOT / "tools" / "harness" / "fixtures" / "driver-doc-conformance.json"
)

REPORT_MARKERS = [
    "- Evidence IDs:",
    "- Fingerprints captured:",
    "## Chains (组合利用",
    "## Confirmed Findings",
    "## Candidate / Phenomena",
    "## Background Evidence",
    "## False-Positive Review",
]


def _missing_markers(template_text: str, reference_text: str, markers: list[str]) -> list[str]:
    return [m for m in markers if m in template_text and m not in reference_text]


def _driver_doc_errors(
    *, root: Path = ROOT, fixture_path: Path | None = None,
    check_instruction_sources: bool = True,
) -> list[str]:
    """Validate Claude-primary owner text and copyable command shapes.

    The JSON fixture is the one data surface for required/forbidden driver claims
    and representative typed argv/prompt packages. Text markers prevent a newer
    owner from silently regressing to a legacy lifecycle; capability and runtime-
    binding checks prove that displayed examples reach the same parsers used by
    the hooks.
    """
    fixture_path = fixture_path or (
        root / "tools" / "harness" / "fixtures" / "driver-doc-conformance.json"
    )
    try:
        fixture = json.loads(fixture_path.read_text(encoding="utf-8", errors="strict"))
    except Exception as exc:
        return [f"driver doc fixture unreadable: {type(exc).__name__}"]
    if not isinstance(fixture, dict) \
            or fixture.get("schema") != "xunji.driver-doc-conformance.v1":
        return ["driver doc fixture has the wrong schema"]

    errors: list[str] = []
    documents = fixture.get("documents")
    if not isinstance(documents, list) or not documents:
        return ["driver doc fixture has no document cases"]
    texts: dict[str, str] = {}
    for case in documents:
        if not isinstance(case, dict) or set(case) != {"path", "required", "forbidden"}:
            errors.append("driver doc fixture contains a malformed document case")
            continue
        rel = case.get("path")
        required = case.get("required")
        forbidden = case.get("forbidden")
        if not isinstance(rel, str) or not rel \
                or not isinstance(required, list) or not isinstance(forbidden, list) \
                or not all(isinstance(item, str) and item for item in required + forbidden):
            errors.append("driver doc fixture document fields are invalid")
            continue
        path = root / rel
        if not path.is_file():
            errors.append(f"driver document missing: {rel}")
            continue
        text = path.read_text(encoding="utf-8", errors="replace")
        texts[rel] = text
        for marker in required:
            if marker not in text:
                errors.append(f"{rel} missing driver marker: {marker}")
        for marker in forbidden:
            if marker in text:
                errors.append(f"{rel} retains forbidden driver marker: {marker}")

    if check_instruction_sources:
        try:
            import agent_instruction_bundle  # type: ignore
            errors.extend(
                "Agent instruction composition: " + detail
                for detail in agent_instruction_bundle.selftest(root=root)
            )
            manifest = agent_instruction_bundle.load_manifest(root=root)
            for role in sorted(manifest["roles"]):
                bundle = agent_instruction_bundle.load_role_contract(role, root=root)
                text = bundle["text"]
                if "workers.py heartbeat/finish" in text or "workers.py finish" in text:
                    errors.append(f"composed role {role} retains stale lifecycle command")
                if "Root/Single Synthesizer alone promotes" not in text:
                    errors.append(f"composed role {role} misses the Root-owned promotion boundary")
                if text.count("<!-- xunji.agent-role-common.v1 -->") != 1:
                    errors.append(f"composed role {role} has an ambiguous common block")
            for role in ("report", "review"):
                text = agent_instruction_bundle.load_role_contract(
                    role, root=root)["text"]
                if "test cross-role access on state-changing operations" in text:
                    errors.append(f"composed role {role} retains target-action cross-role guidance")
        except Exception as exc:
            errors.append(
                "Agent instruction composition unavailable: " + type(exc).__name__)

    prompt_cases = fixture.get("prompt_cases")
    valid_prompt_cases: list[dict] = []
    prompt_fields = {
        "name", "document", "marker", "tool_input", "required_tokens",
        "expected", "expected_subagent_type", "expected_valid",
    }
    binding_fields = {
        "assignment", "front", "assets", "lane_id", "plan_digest",
        "result_digest", "completion_bundle_hash", "completion_review",
    }
    if not isinstance(prompt_cases, list) or not prompt_cases:
        errors.append("driver doc fixture has no prompt cases")
    else:
        for case in prompt_cases:
            if not isinstance(case, dict) or set(case) != prompt_fields:
                errors.append("driver doc fixture contains a malformed prompt case")
                continue
            name = case.get("name")
            document = case.get("document")
            marker = case.get("marker")
            tool_input = case.get("tool_input")
            prompt = tool_input.get("prompt") if isinstance(tool_input, dict) else None
            required_tokens = case.get("required_tokens")
            expected = case.get("expected")
            expected_subagent_type = case.get("expected_subagent_type")
            expected_valid = case.get("expected_valid")
            if not all(isinstance(item, str) and item for item in (
                    name, document, marker, prompt)) \
                    or not isinstance(tool_input, dict) \
                    or not set(tool_input).issubset({
                        "prompt", "subagent_type", "description",
                    }) \
                    or "prompt" not in tool_input \
                    or not isinstance(required_tokens, list) \
                    or not required_tokens \
                    or not all(isinstance(item, str) and item
                               for item in required_tokens) \
                    or not isinstance(expected, dict) \
                    or set(expected) != binding_fields \
                    or not all(isinstance(expected.get(field), str)
                               for field in binding_fields - {
                                   "assets", "completion_review",
                               }) \
                    or not isinstance(expected.get("assets"), list) \
                    or not all(isinstance(item, str)
                               for item in expected.get("assets", [])) \
                    or not isinstance(expected.get("completion_review"), bool) \
                    or expected_subagent_type not in {
                        "xunji-hunter", "xunji-reviewer",
                    } \
                    or not isinstance(expected_valid, bool):
                errors.append("driver doc fixture prompt fields are invalid")
                continue
            if marker not in texts.get(document, ""):
                errors.append(f"{name}: documented prompt marker missing")
            missing_tokens = [token for token in required_tokens if token not in prompt]
            if missing_tokens:
                errors.append(
                    f"{name}: representative prompt misses tokens: "
                    + ", ".join(missing_tokens)
                )
                continue
            valid_prompt_cases.append(case)

    order_cases = fixture.get("order_cases")
    order_fields = {"name", "document", "markers"}
    if not isinstance(order_cases, list) or not order_cases:
        errors.append("driver doc fixture has no ordering cases")
    else:
        for case in order_cases:
            if not isinstance(case, dict) or set(case) != order_fields:
                errors.append("driver doc fixture contains a malformed ordering case")
                continue
            name = case.get("name")
            document = case.get("document")
            markers = case.get("markers")
            if not isinstance(name, str) or not name \
                    or not isinstance(document, str) or not document \
                    or not isinstance(markers, list) or len(markers) < 2 \
                    or not all(isinstance(item, str) and item for item in markers):
                errors.append("driver doc fixture ordering fields are invalid")
                continue
            text = texts.get(document, "")
            positions = [text.find(marker) for marker in markers]
            if -1 in positions:
                errors.append(f"{name}: ordered driver marker missing")
            elif positions != sorted(positions) or len(set(positions)) != len(positions):
                errors.append(f"{name}: driver markers are out of order")
    try:
        sys.path.insert(0, str(ROOT / "tools"))
        import runtime_receipts  # type: ignore
    except Exception as exc:
        errors.append(
            "runtime receipt parser unavailable to template check: "
            + type(exc).__name__
        )
        return errors
    for index, case in enumerate(valid_prompt_cases):
        tool_input = case["tool_input"]
        prompt = tool_input["prompt"]
        binding = runtime_receipts._agent_invocation_binding({
            "tool_use_id": f"driver-doc-case-{index}",
            "tool_input": tool_input,
        })
        parsed = {
            "assignment": str(binding.get("assignment") or ""),
            "front": str(binding.get("front") or ""),
            "assets": binding.get("assignment_assets") or [],
            "lane_id": str(binding.get("assignment_lane") or ""),
            "plan_digest": str(binding.get("assignment_plan_digest") or ""),
            "result_digest": str(binding.get("assignment_result_digest") or ""),
            "completion_bundle_hash": str(
                binding.get("completion_bundle_hash") or ""),
            "completion_review": bool(binding.get("completion_review")),
        }
        if parsed != case["expected"]:
            errors.append(
                f"{case['name']}: runtime prompt binding differs from fixture: "
                + json.dumps(parsed, sort_keys=True)
            )
            continue
        expected_type = case["expected_subagent_type"]
        exact_prompt = False
        if case["expected"]["completion_review"]:
            run_match = re.search(r"\brun=([A-Za-z0-9._-]{1,256})\b", prompt)
            evidence_hash = runtime_receipts._evidence_hash(prompt)
            bundle_hash = runtime_receipts._completion_bundle_hash(prompt)
            if run_match and re.fullmatch(r"[0-9a-f]{40}", evidence_hash) \
                    and re.fullmatch(r"[0-9a-f]{64}", bundle_hash):
                exact_prompt = prompt == runtime_receipts.format_completion_review_prompt(
                    run_match.group(1), evidence_hash, bundle_hash)
        else:
            expected = case["expected"]
            role = "review" if expected_type == "xunji-reviewer" else "web-hunter"
            fixture_bundle = {}
            fixture_bundle_sha256 = runtime_receipts._instruction_bundle.canonical_digest(
                fixture_bundle)
            exact_prompt = prompt == runtime_receipts.assignment_launch_prompt({
                "schema": "xunji.assignment.v1",
                "agent": expected["assignment"],
                "front": expected["front"],
                "assets": expected["assets"],
                "lane_id": expected["lane_id"],
                "plan_digest": expected["plan_digest"],
                "role": role,
                "review_result_digest": expected["result_digest"],
                "instruction_bundle": fixture_bundle,
                "instruction_bundle_sha256": fixture_bundle_sha256,
            })
        observed_valid = bool(
            binding
            and exact_prompt
            and tool_input.get("subagent_type") == expected_type
            and binding.get("subagent_type") == expected_type
        )
        if observed_valid != case["expected_valid"]:
            errors.append(
                f"{case['name']}: Agent tool_input validity={observed_valid}, "
                f"expected {case['expected_valid']}"
            )

    result_cases = fixture.get("result_cases")
    result_fields = {
        "name", "document", "marker", "run", "evidence_index_hash",
        "completion_bundle_hash", "response", "expected_valid",
    }
    if not isinstance(result_cases, list) or not result_cases:
        errors.append("driver doc fixture has no completion result cases")
    else:
        for case in result_cases:
            if not isinstance(case, dict) or set(case) != result_fields \
                    or not all(isinstance(case.get(field), str)
                               and case.get(field) for field in result_fields - {
                                   "expected_valid",
                               }) \
                    or not isinstance(case.get("expected_valid"), bool):
                errors.append(
                    "driver doc fixture contains a malformed completion result case")
                continue
            if case["marker"] not in texts.get(case["document"], ""):
                errors.append(f"{case['name']}: documented result marker missing")
                continue
            expected_envelope = runtime_receipts.completion_review_result_envelope(
                case["run"], case["evidence_index_hash"],
                case["completion_bundle_hash"],
            )
            observed = runtime_receipts._completion_response_is_exact_pass(
                case["response"], expected_envelope)
            if observed != case["expected_valid"]:
                errors.append(
                    f"{case['name']}: completion result validity={observed}, "
                    f"expected {case['expected_valid']}"
                )

    capability_cases = fixture.get("capability_cases")
    if not isinstance(capability_cases, list) or not capability_cases:
        errors.append("driver doc fixture has no capability cases")
        return errors
    if root.resolve() != ROOT.resolve():
        # Exact capability identity is repository-bound and is checked in the real
        # run. Prompt/type validation above is pure and remains active in selftests.
        return errors
    try:
        from harness import capability_registry  # type: ignore
    except Exception as exc:
        errors.append(f"capability registry unavailable to template check: {type(exc).__name__}")
        return errors
    expected_fields = {
        "name", "document", "marker", "script", "argv",
        "expected_id", "expected_effect",
    }
    for case in capability_cases:
        if not isinstance(case, dict) or set(case) != expected_fields:
            errors.append("driver doc fixture contains a malformed capability case")
            continue
        name = case.get("name")
        document = case.get("document")
        marker = case.get("marker")
        script = case.get("script")
        argv = case.get("argv")
        if not all(isinstance(item, str) and item for item in (
                name, document, marker, script, case.get("expected_id"),
                case.get("expected_effect"))) \
                or not isinstance(argv, list) \
                or not all(isinstance(item, str) for item in argv):
            errors.append("driver doc fixture capability fields are invalid")
            continue
        if marker not in texts.get(document, ""):
            errors.append(f"{name}: documented command marker missing")
            continue
        spec = capability_registry.match(ROOT / script, argv)
        if spec is None:
            errors.append(f"{name}: representative documented argv is not registered")
            continue
        if spec.id != case["expected_id"] or spec.effect != case["expected_effect"]:
            errors.append(
                f"{name}: registry classified as {spec.id}/{spec.effect}, expected "
                f"{case['expected_id']}/{case['expected_effect']}"
            )
    return errors


def check(template: Path | None = None, reference: Path | None = None) -> list[str]:
    custom_paths = template is not None or reference is not None
    template = template or ROOT / "docs" / "templates" / "run" / "report.md"
    reference = reference or ROOT / "docs" / "WORKFLOW-reference.md"
    errors: list[str] = []
    if not template.exists():
        return [f"{template.relative_to(ROOT)} missing"]
    if not reference.exists():
        return [f"{reference.relative_to(ROOT)} missing"]
    tpl = template.read_text(encoding="utf-8", errors="replace")
    ref = reference.read_text(encoding="utf-8", errors="replace")
    for marker in _missing_markers(tpl, ref, REPORT_MARKERS):
        errors.append(f"WORKFLOW-reference.md missing report marker from template: {marker}")
    if not custom_paths:
        errors.extend(_driver_doc_errors())
    return errors


def _selftest() -> int:
    d = Path(tempfile.mkdtemp())
    tpl = d / "report.md"
    ref = d / "reference.md"
    tpl.write_text("# Report\n- Evidence IDs:\n- Fingerprints captured:\n## Confirmed Findings\n",
                   encoding="utf-8")
    ref.write_text("# Ref\n- Evidence IDs:\n", encoding="utf-8")
    missing = check(tpl, ref)
    ref.write_text("# Ref\n- Evidence IDs:\n- Fingerprints captured:\n## Confirmed Findings\n",
                   encoding="utf-8")
    clean = check(tpl, ref)
    driver_root = d / "driver-root"
    (driver_root / "docs").mkdir(parents=True)
    driver_doc = driver_root / "docs" / "driver.md"
    driver_doc.write_text(
        "CURRENT COMMAND\nCOMPLETION GUARD\nJOURNAL START\nREVIEW PROMPT\nREVIEW RESULT\n",
        encoding="utf-8",
    )
    fixture = d / "driver-doc-conformance.json"
    driver_fixture = {
        "schema": "xunji.driver-doc-conformance.v1",
        "documents": [{
            "path": "docs/driver.md",
            "required": ["CURRENT COMMAND"],
            "forbidden": ["LEGACY COMMAND"],
        }],
        "capability_cases": [{}],
        "prompt_cases": [{
            "name": "review prompt",
            "document": "docs/driver.md",
            "marker": "REVIEW PROMPT",
            "tool_input": {
                "prompt": (
                    "XUNJI_ASSIGNMENT=A-review-001 XUNJI_FRONT=F-001 "
                    "XUNJI_ASSETS=none XUNJI_LANE=L-F001-REVIEW "
                    f"XUNJI_PLAN={'a' * 64} "
                    "XUNJI_INSTRUCTION_BUNDLE="
                    "44136fa355b3678a1146ad16f7e8649e94fb4fc21fe77e8310c060f61caaff8a "
                    f"XUNJI_RESULT_DIGEST={'b' * 64} "
                    "XUNJI_COMPLETION_REVIEW"
                ),
                "subagent_type": "xunji-reviewer",
            },
            "required_tokens": [
                "XUNJI_ASSIGNMENT=", "XUNJI_FRONT=", "XUNJI_ASSETS=",
                "XUNJI_LANE=", "XUNJI_PLAN=", "XUNJI_INSTRUCTION_BUNDLE=",
                "XUNJI_RESULT_DIGEST=",
                "XUNJI_COMPLETION_REVIEW",
            ],
            "expected": {
                "assignment": "A-review-001",
                "front": "F-001",
                "assets": [],
                "lane_id": "L-F001-REVIEW",
                "plan_digest": "a" * 64,
                "result_digest": "b" * 64,
                "completion_bundle_hash": "",
                "completion_review": False,
            },
            "expected_subagent_type": "xunji-reviewer",
            "expected_valid": True,
        }],
        "result_cases": [{
            "name": "exact completion result",
            "document": "docs/driver.md",
            "marker": "REVIEW RESULT",
            "run": "demo_20260101",
            "evidence_index_hash": "c" * 40,
            "completion_bundle_hash": "d" * 64,
            "response": (
                "substantive checks complete\n"
                "XUNJI_COMPLETION_VERDICT=PASS "
                f"EVIDENCE_INDEX={'c' * 40} COMPLETION_BUNDLE={'d' * 64} "
                "run=demo_20260101 CHECKS=report_parity:PASS,"
                "severity_artifacts:PASS,reachable_frontier:PASS,review_ledger:PASS"
            ),
            "expected_valid": True,
        }],
        "order_cases": [{
            "name": "completion guard precedes start",
            "document": "docs/driver.md",
            "markers": ["COMPLETION GUARD", "JOURNAL START"],
        }],
    }
    fixture.write_text(json.dumps(driver_fixture), encoding="utf-8")
    driver_clean = _driver_doc_errors(
        root=driver_root, fixture_path=fixture,
        check_instruction_sources=False)
    driver_doc.write_text(
        "CURRENT COMMAND\nJOURNAL START\nCOMPLETION GUARD\nREVIEW PROMPT\nREVIEW RESULT\n",
        encoding="utf-8",
    )
    driver_order_drift = _driver_doc_errors(
        root=driver_root, fixture_path=fixture,
        check_instruction_sources=False)
    driver_doc.write_text(
        "CURRENT COMMAND\nCOMPLETION GUARD\nJOURNAL START\nREVIEW PROMPT\nREVIEW RESULT\n",
        encoding="utf-8",
    )
    missing_token_fixture = json.loads(json.dumps(driver_fixture))
    missing_token_fixture["prompt_cases"][0]["tool_input"]["prompt"] = \
        missing_token_fixture["prompt_cases"][0]["tool_input"]["prompt"].replace(
            "XUNJI_ASSETS=none ", "")
    fixture.write_text(json.dumps(missing_token_fixture), encoding="utf-8")
    driver_prompt_drift = _driver_doc_errors(
        root=driver_root, fixture_path=fixture,
        check_instruction_sources=False)
    wrong_type_fixture = json.loads(json.dumps(driver_fixture))
    wrong_type_fixture["prompt_cases"][0]["tool_input"]["subagent_type"] = \
        "xunji-hunter"
    fixture.write_text(json.dumps(wrong_type_fixture), encoding="utf-8")
    driver_type_drift = _driver_doc_errors(
        root=driver_root, fixture_path=fixture,
        check_instruction_sources=False)
    fixture.write_text(json.dumps(driver_fixture), encoding="utf-8")
    driver_doc.write_text("LEGACY COMMAND\n", encoding="utf-8")
    driver_drift = _driver_doc_errors(
        root=driver_root, fixture_path=fixture,
        check_instruction_sources=False)
    checks = [
        ("missing marker is reported", any("Fingerprints captured" in m for m in missing)),
        ("aligned markers pass", clean == []),
        ("data-driven driver markers pass", driver_clean == []),
        ("plan-bound Reviewer prompt requires every binding token",
         any("representative prompt misses tokens" in item
             for item in driver_prompt_drift)),
        ("plan-bound Reviewer requires the exact Agent type",
         any("Agent tool_input validity=False" in item
             for item in driver_type_drift)),
        ("completed-run guard stays before journal start",
         any("driver markers are out of order" in item
             for item in driver_order_drift)),
        ("data-driven driver drift is rejected",
         any("missing driver marker" in item for item in driver_drift)
         and any("forbidden driver marker" in item for item in driver_drift)),
    ]
    bad = [name for name, ok in checks if not ok]
    for name, ok in checks:
        print(("ok   " if ok else "FAIL ") + name)
    print("template check selftest " + ("passed" if not bad else f"FAILED ({len(bad)})"))
    return 0 if not bad else 1


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Check template/reference drift.")
    parser.add_argument("--selftest", action="store_true", help="run local regression tests")
    args = parser.parse_args(argv)
    if args.selftest:
        return _selftest()
    errors = check()
    if errors:
        print("template check failed")
        for e in errors:
            print(f"- {e}")
        return 1
    print("template check passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
