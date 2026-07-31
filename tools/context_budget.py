#!/usr/bin/env python3
"""Enforce measured always-loaded context budgets and owner-rule placement."""
from __future__ import annotations

import argparse
import json
import math
import tempfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CONTRACT = ROOT / "contracts" / "context-budgets.v1.json"


def check(root: Path = ROOT, contract_path: Path = CONTRACT) -> tuple[dict, list[str]]:
    contract = json.loads(contract_path.read_text(encoding="utf-8"))
    if contract.get("schema") != "xunji.context-budgets.v1":
        return {}, ["CONTEXT_BUDGET_SCHEMA_INVALID"]
    rows = {}
    texts: dict[str, str] = {}
    errors: list[str] = []
    for relative, spec in contract.get("files", {}).items():
        path = root / relative
        if not path.is_file():
            errors.append(f"CONTEXT_FILE_MISSING:{relative}")
            continue
        text = path.read_text(encoding="utf-8", errors="replace")
        texts[relative] = text
        rows[relative] = {
            "chars": len(text),
            "estimated_tokens": math.ceil(len(text) / 4),
            "max_chars": int(spec["max_chars"]),
        }
        if len(text) > int(spec["max_chars"]):
            errors.append(f"CONTEXT_BUDGET_EXCEEDED:{relative}")
        for marker in spec.get("required", []):
            if marker not in text:
                errors.append(f"CONTEXT_REQUIRED_RULE_MISSING:{relative}:{marker}")
    loop_text = texts.get("docs/templates/loop_prompt.md", "")
    for marker in contract.get("forbidden_loop_prompt_copies", []):
        if marker in loop_text:
            errors.append(f"CONTEXT_OWNER_DUPLICATED_IN_LOOP_PROMPT:{marker}")
    duplicate_limit = contract.get("duplicate_rule_limit")
    if isinstance(duplicate_limit, bool) or not isinstance(duplicate_limit, int) \
            or duplicate_limit < 1:
        errors.append("CONTEXT_DUPLICATE_RULE_LIMIT_INVALID")
    else:
        for marker in contract.get("forbidden_loop_prompt_copies", []):
            copies = sum(text.count(marker) for text in texts.values())
            if copies > duplicate_limit:
                errors.append(
                    f"CONTEXT_OWNER_RULE_DUPLICATED:{marker}:{copies}>"
                    f"{duplicate_limit}")
    return {
        "schema": contract["schema"],
        "files": rows,
        "total_chars": sum(row["chars"] for row in rows.values()),
        "total_estimated_tokens": sum(
            row["estimated_tokens"] for row in rows.values()),
    }, errors


def _selftest() -> int:
    root = Path(tempfile.mkdtemp())
    (root / "docs" / "templates").mkdir(parents=True)
    files = {
        "CLAUDE.md": "owner marker\n",
        "docs/ROUTER.md": "route marker\n",
        "docs/WORKFLOW.md": "flow marker\n",
        "docs/templates/loop_prompt.md": "cycle marker\n",
    }
    for relative, text in files.items():
        path = root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
    contract = root / "contract.json"
    contract.write_text(json.dumps({
        "schema": "xunji.context-budgets.v1",
        "files": {
            relative: {"max_chars": 100, "required": [text.split()[0]]}
            for relative, text in files.items()
        },
        "forbidden_loop_prompt_copies": ["owner marker"],
        "duplicate_rule_limit": 1,
    }), encoding="utf-8")
    summary, errors = check(root, contract)
    (root / "docs" / "templates" / "loop_prompt.md").write_text(
        "cycle marker\nowner marker\n", encoding="utf-8")
    _summary_bad, errors_bad = check(root, contract)
    checks = [
        ("measured char/token summary is deterministic",
         summary["total_chars"] == sum(len(item) for item in files.values())
         and not errors),
        ("owner rule duplication in loop prompt is rejected",
         "CONTEXT_OWNER_DUPLICATED_IN_LOOP_PROMPT:owner marker" in errors_bad
         and "CONTEXT_OWNER_RULE_DUPLICATED:owner marker:2>1" in errors_bad),
    ]
    (root / "docs" / "templates" / "loop_prompt.md").unlink()
    _summary_missing, errors_missing = check(root, contract)
    checks.append(("missing loop prompt is classified, not an exception",
                   "CONTEXT_FILE_MISSING:docs/templates/loop_prompt.md"
                   in errors_missing))
    failed = [name for name, ok in checks if not ok]
    for name, ok in checks:
        print(("ok   " if ok else "FAIL ") + name)
    print("context_budget selftest " + ("passed" if not failed else "FAILED"))
    return 0 if not failed else 1


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--selftest", action="store_true")
    args = parser.parse_args()
    if args.selftest:
        return _selftest()
    summary, errors = check()
    print(json.dumps({**summary, "errors": errors}, ensure_ascii=False, indent=2))
    return 0 if not errors else 1


if __name__ == "__main__":
    raise SystemExit(main())
