from __future__ import annotations

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
]

REQUIRED_TEXT: dict[Path, list[str]] = {
    Path("AGENTS.md"): [
        "docs/ARCHITECTURE.md",
        "tools/harness/privacy.py",
        "tools/harness/command_shape.py",
    ],
    Path("CLAUDE.md"): [
        "docs/ARCHITECTURE.md",
        "tools/harness/privacy.py",
        "tools/harness/command_shape.py",
    ],
    Path("docs/WORKFLOW-reference.md"): [
        "tools/harness/privacy.py",
        "tools/harness/command_shape.py",
    ],
    Path("docs/ARCHITECTURE.md"): [
        "## 4. 当前架构",
        "## 6. 过渡架构",
        "## 7. 目标架构",
        "## 8. 目录与 owner 地图",
        "## 10. 变更协议",
        "## 11. 当前不可破坏的不变量",
        "## 12. Maintenance Checkpoint",
    ],
}

CHECKPOINT_REQUIRED_FIELDS = (
    "Date",
    "Scope",
    "Architecture impact",
    "Verification",
    "Independent review",
)


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

    if errors:
        print("rule check failed")
        for error in errors:
            print(f"- {error}")
        return 1

    print("rule check passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
