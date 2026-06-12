from __future__ import annotations

import argparse
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
REQUIRED_FILES = [
    "target.md",
    "surface.md",
    "frontier.md",
    "hypotheses.md",
    "evidence.md",
    "false_positive.md",
    "decisions.md",
    "review.md",
    "report.md",
]

REQUIRED_MARKERS = {
    "frontier.md": [
        "# Frontier",
        "Open Fronts",
        "Deferred Fronts",
        "Closed Fronts",
        "Barrier class:",
        "Failure budget:",
    ],
    "hypotheses.md": ["# Hypotheses", "Status:", "What would confirm:", "What would reject:"],
    "evidence.md": ["# Evidence Ledger", "Certainty:", "Caused by us:", "Alternative explanation:"],
    "false_positive.md": ["# False-Positive Checks", "Could be environmental:", "Impact verified:"],
    "decisions.md": [
        "# Decisions",
        "Loaded rule files this cycle:",
        "Chosen front:",
        "Why this is worth pursuing now:",
        "Difference from previous failed attempts:",
        "Failure budget state:",
    ],
    "review.md": [
        "# Review",
        "Shallow work smells:",
        "Repeated-barrier loops:",
        "Failure-budget triggers:",
        "Next autonomous front:",
    ],
    "report.md": ["# Report", "Evidence IDs:"],
}

# Optional artifacts: validated only if present (conditional, not required every
# run). chains.md exists only when a vulnerability chain / 组合利用 is recorded.
OPTIONAL_MARKERS = {
    "chains.md": [
        "# Chains",
        "Hops",
        "Weakest hop certainty:",
        "Terminal node:",
    ],
}


def check_file(path: Path, markers: list[str]) -> list[str]:
    errors: list[str] = []
    if not path.exists():
        return [f"missing {path.name}"]
    text = path.read_text(encoding="utf-8", errors="replace")
    for marker in markers:
        if marker not in text:
            errors.append(f"{path.name} missing marker: {marker}")
    return errors


def main() -> int:
    parser = argparse.ArgumentParser(description="Check a Xunji run directory.")
    parser.add_argument("run_dir", type=Path)
    args = parser.parse_args()

    run_dir = args.run_dir
    if not run_dir.is_absolute():
        run_dir = ROOT / run_dir
    run_dir = run_dir.resolve()

    runs_root = (ROOT / "runs").resolve()
    try:
        run_dir.relative_to(runs_root)
    except ValueError:
        print(f"run directory must be under {runs_root}")
        return 1

    errors: list[str] = []
    for name in REQUIRED_FILES:
        path = run_dir / name
        markers = REQUIRED_MARKERS.get(name, [])
        errors.extend(check_file(path, markers))

    # Optional artifacts: only checked when the file is present.
    for name, markers in OPTIONAL_MARKERS.items():
        path = run_dir / name
        if path.exists():
            errors.extend(check_file(path, markers))

    if errors:
        print("run check failed")
        for error in errors:
            print(f"- {error}")
        return 1

    print("run check passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
