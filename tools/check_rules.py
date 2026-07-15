from __future__ import annotations

import ast
import json
import re
import sys
from pathlib import Path


# ---------------------------------------------------------------------------
# check_rules.py — repository ARCHITECTURE-DRIFT guard (not a security control).
#
# 它守的唯一东西: 仓库有没有漂回那套被废弃的 JSON 编排器 / playbook 架构,
# 以及核心纲领文件在不在。
#
# 它【不】管武器。理由是项目的核心轴 "gate EFFECTS, not METHODS":
#   - exp / poc / scanner / 利用代码 = 方法, 方法自由。它存在于仓库里、被编写
#     出来, 本身不造成任何破坏(见 poc_library/, tools/poc_ours_upload/,
#     runs/<target>/ 等正当产物区)。
#   - 唯一要管的是【在活靶上自动执行时的不可逆危害】—— 那是【效果】, 按效果、
#     在运行时由 .claude/hooks/safety_gate.py 守, 不靠静态文件名去拦。
# 因此这里不做任何 exploit/poc/scanner 文件名或工具名的"方法警察"判定 —— 那既
# 与 hook 重复, 又违背 gate-effects-not-methods。
# ---------------------------------------------------------------------------

ROOT = Path(__file__).resolve().parents[1]

# 被废弃的旧架构目录 —— 重新出现即为架构回退
LEGACY_DIRS = [
    "apps",
    "schemas",
    "prompts",
    "policies",
    "examples",
    "tests",
    "artifacts",
]

# 文本扫描范围(找旧架构引用)
WATCH_DIRS = [
    ".claude",
    "docs",
    "tools",
]

SKIP_DIRS = {
    ".venv",
    ".git",
    "__pycache__",
    ".pytest_cache",
    ".ruff_cache",
    ".state",
    "observations",
    "reports",
    "deepseek-project",
}

# 自身定义了旧架构引用字符串, 必须跳过自检
SKIP_FILES = {
    Path("tools/check_rules.py"),
    Path("tools/check_hook.py"),
    Path(".claude/hooks/safety_gate.py"),
    Path(".claude/hooks/safety_rules.json"),
}

# 仅拦【旧架构】引用 —— 这是架构完整性, 不是方法警察。
# 不再拦 sqlmap/hydra/masscan/metasploit 等工具名: 方法自由, 是否造成危害由 hook 按效果守。
FORBIDDEN_TEXT_PATTERNS = [
    re.compile(r"apps\.orchestrator", re.IGNORECASE),
    re.compile(r"schemas/action\.schema\.json", re.IGNORECASE),
    re.compile(r"prompts/planner\.system\.md", re.IGNORECASE),
]

REQUIRED_FILES = [
    Path("AGENTS.md"),
    Path("CLAUDE.md"),
    Path("docs/ARCHITECTURE.md"),
    Path("docs/ROUTER.md"),
    Path("docs/WORKFLOW.md"),
    Path("docs/WORKFLOW-reference.md"),
    Path("docs/cognition/README.md"),
    Path("tools/setup_transaction.py"),
    Path("tools/setup_normalizer.py"),
    Path("tools/setup_normalizer_bench.py"),
    Path("tools/setup_source.py"),
    Path("tools/scope_admission.py"),
    Path("contracts/setup-source.v1.schema.json"),
    Path("contracts/setup-normalizer-candidate.v1.schema.json"),
    Path("contracts/scope-admission.v1.schema.json"),
    Path("tools/harness/fixtures/setup-source.json"),
    Path("tools/harness/fixtures/setup-normalizer.json"),
    Path("tools/harness/fixtures/scope-admission.json"),
    Path("bench/setup-normalizer-pilot/cases.json"),
    Path("tools/harness/fixtures/setup-transaction.json"),
    Path("tools/harness/maintenance_authority.py"),
    Path("tools/harness/safety_critical_paths.json"),
]

REQUIRED_TEXT: dict[Path, list[str]] = {
    Path("AGENTS.md"): [
        "docs/ARCHITECTURE.md",
        "tools/harness/privacy.py",
        "tools/harness/command_shape.py",
        "tools/setup_transaction.py",
    ],
    Path("CLAUDE.md"): [
        "docs/ARCHITECTURE.md",
        "tools/harness/privacy.py",
        "tools/harness/command_shape.py",
        "tools/setup_transaction.py",
        "xunji.setup-source.v1",
        "loop_bootstrap.py --source",
        "/xunji-maintenance",
        "/xunji-scope-admit",
    ],
    Path("docs/WORKFLOW.md"): [
        "/xunji-maintenance",
        "tools/harness/maintenance_authority.py",
        "xunji.setup-source.v1",
        "sources/normalized.json",
        "setup-normalizer-candidate.v1",
        "/xunji-scope-admit",
    ],
    Path("docs/WORKFLOW-reference.md"): [
        "tools/harness/privacy.py",
        "tools/harness/command_shape.py",
        "tools/setup_transaction.py",
        "xunji.setup-source.v1",
        "sources/validator_receipt.json",
        "setup-normalizer-candidate.v1",
        "/xunji-maintenance",
        "xunji.scope_admission.v1",
    ],
    Path("docs/ARCHITECTURE.md"): [
        "## 4. 当前架构",
        "## 6. 过渡架构",
        "## 7. 目标架构",
        "## 8. 目录与 owner 地图",
        "## 10. 变更协议",
        "## 11. 当前不可破坏的不变量",
        "## 12. Maintenance Checkpoint",
        "tools/setup_transaction.py",
        "tools/setup_source.py",
        "tools/setup_normalizer.py",
        "xunji.setup-source.v1",
        "contracts/",
        "prepared_not_active",
        "commit_activation_cas()",
        "/xunji-maintenance",
        "tools/scope_admission.py",
        "xunji.scope_admission.v1",
    ],
    Path("contracts/setup-source.v1.schema.json"): [
        "structural validation layer",
        "source_ref",
        "prompt_sha256",
        "differential tests",
    ],
    Path("contracts/setup-normalizer-candidate.v1.schema.json"): [
        "setup-normalizer-candidate.v1",
        "request_sha256",
        "source_sha256",
        "target_token",
    ],
    Path("contracts/scope-admission.v1.schema.json"): [
        "xunji.scope_admission.v1",
        "projection_after_sha256",
        "zero_probe",
        "prompt_sha256",
    ],
}

CHECKPOINT_REQUIRED_FIELDS = (
    "Date",
    "Scope",
    "Architecture impact",
    "Verification",
    "Independent review",
)

ACTIVE_POINTER_OWNER = Path("tools/setup_transaction.py")
ACTIVE_POINTER_MUTATORS = {
    "write_text", "write_bytes", "unlink", "rename", "replace", "touch",
}
ACTIVE_POINTER_HELPERS = {
    "_atomic_write", "atomic_write", "os.replace", "shutil.move",
}


def _call_name(node: ast.AST) -> str:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        prefix = _call_name(node.value)
        return f"{prefix}.{node.attr}" if prefix else node.attr
    return ""


def active_pointer_mutations(path: Path, text: str) -> list[int]:
    """Return non-test direct writes to the canonical active-run pointer.

    ``tools/setup_transaction.py`` is the one writer.  Other modules may read
    the pointer or pass it to the shared transaction API, but may not mutate it
    directly.  This AST tripwire covers Path mutations, write-mode ``open()``,
    common atomic-write helpers, and shell strings.  Selftest functions may
    construct deliberately forbidden calls to verify the runtime guard.
    """
    if path == ACTIVE_POINTER_OWNER:
        return []
    try:
        tree = ast.parse(text, filename=str(path))
    except SyntaxError:
        return []

    pointer_names: set[str] = set()

    def mentions_pointer(node: ast.AST | None) -> bool:
        if node is None:
            return False
        if isinstance(node, ast.Name) and node.id in pointer_names:
            return True
        return any(
            isinstance(child, ast.Constant)
            and isinstance(child.value, str)
            and "xunji_active_run" in child.value
            for child in ast.walk(node)
        )

    # Resolve the simple module/function aliases used by the repository.
    changed = True
    while changed:
        changed = False
        for node in ast.walk(tree):
            if not isinstance(node, (ast.Assign, ast.AnnAssign)):
                continue
            value = node.value
            if not mentions_pointer(value):
                continue
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            for target in targets:
                if isinstance(target, ast.Name) and target.id not in pointer_names:
                    pointer_names.add(target.id)
                    changed = True

    errors: list[int] = []

    class MutationVisitor(ast.NodeVisitor):
        def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
            if node.name == "_selftest" or node.name.startswith("test_"):
                return
            self.generic_visit(node)

        visit_AsyncFunctionDef = visit_FunctionDef

        def visit_Call(self, node: ast.Call) -> None:
            name = _call_name(node.func)
            if isinstance(node.func, ast.Attribute):
                if node.func.attr in ACTIVE_POINTER_MUTATORS and mentions_pointer(node.func.value):
                    errors.append(node.lineno)
            if name == "open" and node.args and mentions_pointer(node.args[0]):
                mode = "r"
                if len(node.args) > 1 and isinstance(node.args[1], ast.Constant):
                    mode = str(node.args[1].value)
                for keyword in node.keywords:
                    if keyword.arg == "mode" and isinstance(keyword.value, ast.Constant):
                        mode = str(keyword.value.value)
                if any(flag in mode for flag in "wax+"):
                    errors.append(node.lineno)
            if name in ACTIVE_POINTER_HELPERS and node.args:
                destination = node.args[1] if name in {"os.replace", "shutil.move"} \
                    and len(node.args) > 1 else node.args[0]
                if mentions_pointer(destination):
                    errors.append(node.lineno)
            self.generic_visit(node)

        def visit_Constant(self, node: ast.Constant) -> None:
            if not isinstance(node.value, str) or "xunji_active_run" not in node.value:
                return
            if re.search(r"(?:^|[;&|\n])\s*(?:rm|unlink|tee)\b|>{1,2}\s*[^\n]*xunji_active_run", node.value):
                errors.append(node.lineno)

    MutationVisitor().visit(tree)
    return sorted(set(errors))


def check_maintenance_checkpoint(text: str) -> list[str]:
    """Check checkpoint shape, not VCS freshness.

    Freshness depends on the review/commit range and remains a fingerprint-review
    responsibility. This tripwire prevents a missing, blank, or placeholder-only
    checkpoint from passing merely because its heading survived.
    """
    errors: list[str] = []
    match = re.search(
        r"(?ms)^## 12\. Maintenance Checkpoint[ \t]*$\n(.*?)(?=^##[ \t]|\Z)",
        text,
    )
    if not match:
        return ["docs/ARCHITECTURE.md missing Maintenance Checkpoint body"]
    body = match.group(1)
    for field in CHECKPOINT_REQUIRED_FIELDS:
        field_match = re.search(rf"(?m)^- {re.escape(field)}:[ \t]*(\S.*)$", body)
        if not field_match:
            errors.append(f"docs/ARCHITECTURE.md checkpoint missing non-empty field: {field}")
            continue
        value = field_match.group(1).strip()
        if value.lower() in {"none", "n/a", "na", "pending", "tbd", "todo", "—", "-"} or "<" in value:
            errors.append(f"docs/ARCHITECTURE.md checkpoint has placeholder field: {field}")
    return errors


def check_safety_critical_manifest(root: Path = ROOT) -> list[str]:
    """Keep the file manifest synchronized with the compiled fail-closed floor."""
    try:
        sys.path.insert(0, str(root / "tools"))
        from harness import maintenance_authority  # type: ignore
        import turn_contract  # type: ignore
        manifest = json.loads((
            root / "tools/harness/safety_critical_paths.json"
        ).read_text(encoding="utf-8", errors="strict"))
    except Exception as exc:
        return [f"safety-critical manifest cannot be validated: {type(exc).__name__}"]
    if not isinstance(manifest, dict) or manifest.get("schema") != maintenance_authority.SCHEMA:
        return ["safety-critical manifest has the wrong schema"]
    exact = manifest.get("exact")
    prefixes = manifest.get("prefixes")
    if not isinstance(exact, list) or not all(isinstance(item, str) for item in exact):
        return ["safety-critical manifest exact list is invalid"]
    if not isinstance(prefixes, list) or not all(isinstance(item, str) for item in prefixes):
        return ["safety-critical manifest prefixes list is invalid"]
    errors: list[str] = []
    if len(exact) != len(set(exact)) or len(prefixes) != len(set(prefixes)):
        errors.append("safety-critical manifest contains duplicate paths")
    if set(exact) != set(maintenance_authority.DEFAULT_EXACT):
        errors.append("safety-critical manifest exact paths drift from compiled fail-closed floor")
    if set(prefixes) != set(maintenance_authority.DEFAULT_PREFIXES):
        errors.append("safety-critical manifest prefixes drift from compiled fail-closed floor")
    critical_exact = set(exact)
    critical_prefixes = set(prefixes)
    trusted_entrypoints = (
        set(turn_contract.CONTROL_SCRIPTS)
        | set(turn_contract.LOCAL_VERIFICATION_SCRIPTS)
        | set(turn_contract.PROXY_AWARE_TARGET_TOOLS)
        | {(root / "tools/peer_review.py").resolve()}
    )
    missing_trusted: list[str] = []
    for entrypoint in trusted_entrypoints:
        try:
            relative = entrypoint.resolve().relative_to(root.resolve()).as_posix()
        except ValueError:
            missing_trusted.append(str(entrypoint))
            continue
        if relative not in critical_exact and not any(
                relative.startswith(prefix + "/") for prefix in critical_prefixes):
            missing_trusted.append(relative)
    if missing_trusted:
        errors.append(
            "trusted executable paths are absent from safety-critical manifest: "
            + ", ".join(sorted(missing_trusted))
        )
    return errors


def relative(path: Path) -> Path:
    return path.relative_to(ROOT)


def iter_text_files() -> list[Path]:
    files: list[Path] = []
    for dirname in WATCH_DIRS:
        base = ROOT / dirname
        if not base.exists():
            continue
        for path in base.rglob("*"):
            rel_parts = path.relative_to(ROOT).parts
            if any(part in SKIP_DIRS for part in rel_parts):
                continue
            if path.is_file():
                files.append(path)
    for name in ("README.md", "AGENTS.md", "CLAUDE.md", "pyproject.toml", ".gitignore"):
        path = ROOT / name
        if path.exists():
            files.append(path)
    return files


def main() -> int:
    errors: list[str] = []

    scanner_probe = Path("tools/_active_pointer_probe.py")
    bad_probe = 'ACTIVE_RUN = Path(".claude/xunji_active_run")\nACTIVE_RUN.write_text("x")\n'
    good_probe = 'ACTIVE_RUN = Path(".claude/xunji_active_run")\nACTIVE_RUN.read_text()\n'
    if not active_pointer_mutations(scanner_probe, bad_probe):
        errors.append("active-pointer mutation tripwire failed to detect a direct writer")
    if active_pointer_mutations(scanner_probe, good_probe):
        errors.append("active-pointer mutation tripwire rejected a read-only consumer")

    # 1. 架构回退: 旧目录重现
    for dirname in LEGACY_DIRS:
        path = ROOT / dirname
        if path.exists():
            errors.append(f"legacy directory exists: {dirname}")

    # 2. 纲领文件存在
    for rel in REQUIRED_FILES:
        if not (ROOT / rel).exists():
            errors.append(f"required file missing: {rel}")

    # 3. 旧架构文本引用
    for path in iter_text_files():
        rel = relative(path)
        if rel in SKIP_FILES:
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        for pattern in FORBIDDEN_TEXT_PATTERNS:
            if pattern.search(text):
                errors.append(f"forbidden text pattern {pattern.pattern!r} in {rel}")
        if path.suffix == ".py":
            for line in active_pointer_mutations(rel, text):
                errors.append(
                    f"direct active-pointer mutation outside {ACTIVE_POINTER_OWNER}: "
                    f"{rel}:{line}"
                )

    # 4. 必含文本(当前为空)
    for rel, required_items in REQUIRED_TEXT.items():
        path = ROOT / rel
        if not path.exists():
            continue
        text = path.read_text(encoding="utf-8", errors="replace")
        for required in required_items:
            if required not in text:
                errors.append(f"{rel} missing required text: {required}")

    architecture_doc = ROOT / "docs/ARCHITECTURE.md"
    if architecture_doc.exists():
        errors.extend(check_maintenance_checkpoint(
            architecture_doc.read_text(encoding="utf-8", errors="replace")))
    errors.extend(check_safety_critical_manifest())

    if errors:
        print("rule check failed")
        for error in errors:
            print(f"- {error}")
        return 1

    print("rule check passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
