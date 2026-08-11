#!/usr/bin/env python3
"""Static wiring checks for Xunji closure audits.

Run from the repository root:
    python3 .agents/skills/xunji-closure-audit/scripts/closure_audit.py
"""
from __future__ import annotations

import argparse
import ast
import re
import tempfile
from pathlib import Path


DOC_ROOTS = [
    ".claude/skills",
    ".agents/skills",
    "docs",
]
DOC_FILES = ["CLAUDE.md", "AGENTS.md"]
SELFTEST_ROOTS = [
    "tools",
    ".claude/hooks",
    "sentinel",
    ".agents/skills/xunji-closure-audit/scripts",
]
CLAUDE_PRIMARY_ONLY_SKILLS = {"web-research"}
INTENTIONAL_SHARED_MIRRORS = {
    "captcha-solve",
    "network-proxy",
    "poc-package",
    "src-rules",
    "safety-boundary",
}
CODEX_ADAPTED_COUNTERPARTS = {
    "xunji-agent-board",
    "xunji-benchmark-eval",
    "xunji-evidence-replay-gate",
    "xunji-exploit-discipline",
    "xunji-exploit-techniques",
    "xunji-knowledge-flywheel",
    "xunji-local-maintenance",
    "xunji-peer-review-panel",
    "xunji-reviewops",
    "xunji-run-lifecycle",
    "xunji-sentinel-guard-review",
    "xunji-setup-ingest",
    "xunji-web-research-sync",
}
APPROVED_CROSS_TREE_SKILLS = (
    INTENTIONAL_SHARED_MIRRORS | CODEX_ADAPTED_COUNTERPARTS
)
CODEX_PROTOCOL_REFERENCE_SKILLS = {"xunji-web-research-sync"}
CLAUDE_PRIMARY_PROTOCOL_SIGNATURES = {
    "web-research": (
        (
            "time-gate command",
            re.compile(r"\bpython3?\s+tools/timestamp_gate\.py\s+--search-hint\b"),
        ),
        (
            "knowledge-first step",
            re.compile(r"\bKnowledge(?:-| )First\b", re.IGNORECASE),
        ),
        (
            "run-ledger handoff",
            re.compile(
                r"\brecord_evidence\.py\s+--run\b|"
                r"Root/Single Synthesizer alone writes canonical|"
                r"\bevidence ledger\b",
                re.IGNORECASE,
            ),
        ),
    ),
}


def _repo_root(raw: str | None) -> Path:
    root = Path(raw or ".").resolve()
    if not (root / "AGENTS.md").is_file() or not (root / "tools").is_dir():
        raise SystemExit(f"not a Xunji repo root: {root}")
    return root


def _markdown_files(root: Path) -> list[Path]:
    files: list[Path] = []
    for rel in DOC_ROOTS:
        p = root / rel
        if p.is_dir():
            files.extend(sorted(p.rglob("*.md")))
    for rel in DOC_FILES:
        p = root / rel
        if p.is_file():
            files.append(p)
    return files


def check_python_command_refs(root: Path) -> list[str]:
    missing: list[str] = []
    pattern = re.compile(r"\bpython3?\s+([./A-Za-z0-9_-]+\.py)\b")
    total = 0
    for path in _markdown_files(root):
        text = path.read_text(encoding="utf-8", errors="replace")
        for match in pattern.finditer(text):
            rel = match.group(1)
            target = Path(rel[2:] if rel.startswith("./") else rel)
            total += 1
            if not (root / target).exists():
                missing.append(f"{target} <- {path.relative_to(root)}")
    print(f"python_command_refs total={total} missing={len(missing)}")
    return missing


def _registered_selftests(root: Path) -> set[str]:
    text = (root / "tools/selftest_all.py").read_text(encoding="utf-8", errors="replace")
    tree = ast.parse(text)
    for node in tree.body:
        target = None
        value = None
        if isinstance(node, ast.AnnAssign):
            target = node.target
            value = node.value
        elif isinstance(node, ast.Assign) and node.targets:
            target = node.targets[0]
            value = node.value
        if isinstance(target, ast.Name) and target.id == "SUITES" and value is not None:
            try:
                suites = ast.literal_eval(value)
            except (ValueError, SyntaxError) as exc:
                raise SystemExit(f"could not evaluate SUITES in tools/selftest_all.py: {exc}") from exc
            registered: set[str] = set()
            for entry in suites:
                if not (
                    isinstance(entry, tuple)
                    and len(entry) >= 2
                    and isinstance(entry[1], list)
                    and entry[1]
                    and isinstance(entry[1][0], str)
                ):
                    raise SystemExit(f"unexpected SUITES entry shape: {entry!r}")
                registered.add(entry[1][0])
            return registered
    raise SystemExit("could not parse SUITES from tools/selftest_all.py")


def check_selftest_registry(root: Path) -> list[str]:
    registered = _registered_selftests(root)
    not_registered: list[str] = []
    total = 0
    for rel in SELFTEST_ROOTS:
        base = root / rel
        if not base.exists():
            continue
        for path in sorted(base.rglob("*.py")):
            repo_rel = path.relative_to(root).as_posix()
            if repo_rel == "tools/selftest_all.py":
                continue
            text = path.read_text(encoding="utf-8", errors="replace")
            if "--selftest" not in text:
                continue
            total += 1
            if repo_rel not in registered:
                not_registered.append(repo_rel)
    print(f"selftest_entrypoints total={total} not_registered={len(not_registered)}")
    return not_registered


def _frontmatter_field(text: str, field: str) -> str | None:
    if not text.startswith("---\n"):
        return None
    end = text.find("\n---\n", 4)
    if end < 0:
        return None
    pattern = re.compile(rf"^{re.escape(field)}:\s*(.+?)\s*$", re.MULTILINE)
    match = pattern.search(text[4:end])
    return match.group(1) if match else None


def check_codex_skill_ownership(root: Path) -> list[str]:
    skill_root = root / ".agents/skills"
    claude_skill_root = root / ".claude/skills"
    violations: list[str] = []
    total = 0
    codex_names: set[str] = set()
    for path in sorted(skill_root.glob("*/SKILL.md")):
        total += 1
        dirname = path.parent.name
        codex_names.add(dirname)
        text = path.read_text(encoding="utf-8", errors="replace")
        declared_name = _frontmatter_field(text, "name")
        description = _frontmatter_field(text, "description")

        if declared_name != dirname:
            violations.append(
                f"{path.relative_to(root)} declares name={declared_name!r}, "
                f"expected {dirname!r}"
            )
        if description is None or "Codex-side" not in description:
            violations.append(
                f"{path.relative_to(root)} description must declare Codex-side ownership"
            )
        if dirname in CLAUDE_PRIMARY_ONLY_SKILLS:
            violations.append(
                f"{path.relative_to(root)} is Claude-primary-only and must not "
                "exist in the Codex skill tree"
            )
        if dirname in INTENTIONAL_SHARED_MIRRORS:
            if "Codex-side" not in text or ".claude/" not in text:
                violations.append(
                    f"{path.relative_to(root)} shared mirror must state its Codex "
                    "role and Claude-runtime boundary"
                )
        if (
            (claude_skill_root / dirname / "SKILL.md").is_file()
            and dirname not in APPROVED_CROSS_TREE_SKILLS
        ):
            violations.append(
                f"{path.relative_to(root)} duplicates a Claude skill without an "
                "explicit shared-mirror or Codex-counterpart classification"
            )
        if dirname not in CODEX_PROTOCOL_REFERENCE_SKILLS:
            for owner, signatures in CLAUDE_PRIMARY_PROTOCOL_SIGNATURES.items():
                matches = [
                    label for label, signature in signatures if signature.search(text)
                ]
                if len(matches) >= 2:
                    violations.append(
                        f"{path.relative_to(root)} reproduces the Claude-primary "
                        f"{owner!r} protocol under a different Codex entry: "
                        + ", ".join(repr(item) for item in matches)
                    )

    for name in sorted(CLAUDE_PRIMARY_ONLY_SKILLS):
        if not (claude_skill_root / name / "SKILL.md").is_file():
            violations.append(
                f".claude/skills/{name}/SKILL.md canonical Claude owner is missing"
            )
    for name in sorted(APPROVED_CROSS_TREE_SKILLS):
        if not (claude_skill_root / name / "SKILL.md").is_file():
            violations.append(
                f"cross-tree classification {name!r} has no Claude skill"
            )
        if name not in codex_names:
            violations.append(
                f"cross-tree classification {name!r} has no Codex skill"
            )

    print(
        "codex_skill_ownership "
        f"total={total} violations={len(violations)}"
    )
    return violations


def _write_fixture_skill(
    root: Path,
    tree: str,
    name: str,
    *,
    description: str,
    body: str = "",
) -> None:
    path = root / tree / name / "SKILL.md"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        f"---\nname: {name}\ndescription: {description}\n---\n\n{body}\n",
        encoding="utf-8",
    )


def _ownership_fixture(root: Path) -> None:
    _write_fixture_skill(
        root,
        ".claude/skills",
        "web-research",
        description="Canonical Claude-primary public research protocol.",
        body=(
            "python3 tools/timestamp_gate.py --search-hint --kind generic\n"
            "## Knowledge First\n"
            "Root/Single Synthesizer alone writes canonical evidence.md."
        ),
    )
    for name in sorted(APPROVED_CROSS_TREE_SKILLS):
        _write_fixture_skill(
            root,
            ".claude/skills",
            name,
            description="Canonical Claude-primary skill.",
        )
        boundary = (
            f"Codex-side mirror; canonical runtime remains "
            f"`.claude/skills/{name}/SKILL.md`."
            if name in INTENTIONAL_SHARED_MIRRORS
            else "Codex-side adapted counterpart."
        )
        _write_fixture_skill(
            root,
            ".agents/skills",
            name,
            description="Codex-side auxiliary skill.",
            body=boundary,
        )
    _write_fixture_skill(
        root,
        ".agents/skills",
        "xunji-closure-audit",
        description="Codex-side repository closure audit.",
    )


def _selftest() -> int:
    checks: list[tuple[str, bool]] = []

    with tempfile.TemporaryDirectory(prefix="xunji-ownership-good-") as raw:
        root = Path(raw)
        _ownership_fixture(root)
        checks.append(
            ("classified fixture passes", not check_codex_skill_ownership(root))
        )

    with tempfile.TemporaryDirectory(prefix="xunji-ownership-desc-") as raw:
        root = Path(raw)
        _ownership_fixture(root)
        _write_fixture_skill(
            root,
            ".agents/skills",
            "missing-owner",
            description="Generic helper without an owner declaration.",
        )
        failures = check_codex_skill_ownership(root)
        checks.append(
            (
                "missing Codex-side declaration rejected",
                any("must declare Codex-side" in item for item in failures),
            )
        )

    with tempfile.TemporaryDirectory(prefix="xunji-ownership-primary-") as raw:
        root = Path(raw)
        _ownership_fixture(root)
        _write_fixture_skill(
            root,
            ".agents/skills",
            "web-research",
            description="Codex-side renamed copy of a live protocol.",
        )
        failures = check_codex_skill_ownership(root)
        checks.append(
            (
                "Claude-primary-only entry rejected",
                any("Claude-primary-only" in item for item in failures),
            )
        )

    with tempfile.TemporaryDirectory(prefix="xunji-ownership-collision-") as raw:
        root = Path(raw)
        _ownership_fixture(root)
        _write_fixture_skill(
            root,
            ".claude/skills",
            "new-shared",
            description="Canonical Claude-primary skill.",
        )
        _write_fixture_skill(
            root,
            ".agents/skills",
            "new-shared",
            description="Codex-side unclassified counterpart.",
        )
        failures = check_codex_skill_ownership(root)
        checks.append(
            (
                "unclassified cross-tree collision rejected",
                any("without an explicit" in item for item in failures),
            )
        )

    with tempfile.TemporaryDirectory(prefix="xunji-ownership-renamed-") as raw:
        root = Path(raw)
        _ownership_fixture(root)
        _write_fixture_skill(
            root,
            ".agents/skills",
            "vulnerability-intel",
            description="Codex-side generic vulnerability intelligence helper.",
            body=(
                "python tools/timestamp_gate.py --search-hint --kind generic\n"
                "## Knowledge-First Check\n"
                "python tools/record_evidence.py --run runs/example"
            ),
        )
        failures = check_codex_skill_ownership(root)
        checks.append(
            (
                "renamed Claude protocol rejected",
                any("reproduces the Claude-primary" in item for item in failures),
            )
        )

    failed = [name for name, passed in checks if not passed]
    for name, passed in checks:
        print(f"{'ok' if passed else 'FAIL'} {name}")
    if failed:
        print(f"closure_audit selftest FAILED ({len(failed)} check(s))")
        return 1
    print(f"closure_audit selftest passed ({len(checks)} checks)")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run Xunji static closure-audit checks.")
    parser.add_argument("--root", help="repository root; defaults to current directory")
    parser.add_argument(
        "--selftest",
        action="store_true",
        help="run deterministic Codex skill ownership regression fixtures",
    )
    args = parser.parse_args(argv)

    if args.selftest:
        return _selftest()

    root = _repo_root(args.root)
    failures: list[str] = []

    for item in check_python_command_refs(root):
        failures.append(f"MISSING_COMMAND {item}")
    for item in check_selftest_registry(root):
        failures.append(f"SELFTEST_NOT_REGISTERED {item}")
    for item in check_codex_skill_ownership(root):
        failures.append(f"CODEX_SKILL_OWNERSHIP {item}")

    if failures:
        for item in failures:
            print(item)
        print(f"closure_audit FAILED ({len(failures)} hard gap(s))")
        return 1
    print("closure_audit passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
