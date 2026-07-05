#!/usr/bin/env python3
"""Check that workflow reference excerpts stay aligned with run templates."""
from __future__ import annotations

import argparse
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

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


def check(template: Path | None = None, reference: Path | None = None) -> list[str]:
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
    checks = [
        ("missing marker is reported", any("Fingerprints captured" in m for m in missing)),
        ("aligned markers pass", clean == []),
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
