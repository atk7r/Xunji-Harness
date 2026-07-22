#!/usr/bin/env python3
"""Typed path boundary for local framework maintenance.

The personal-tool runtime trusts the top-level operator; maintenance intent is
derived by ``UserPromptSubmit`` rather than granted by a path-list ceremony.
This module still owns deterministic repository-path normalization, forbidden
runtime/control paths, and the safety-critical review manifest.
"""
from __future__ import annotations

import json
import re
import shlex
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
MANIFEST = Path(__file__).with_name("safety_critical_paths.json")
SCHEMA = "xunji.safety_critical_paths.v1"
DIRECTIVE = "/xunji-maintenance"
MAINTENANCE_ACTION_RE = re.compile(
    r"修复|修改|优化|重构|更新|精简|合并|删除|移除|实现|改进|"
    r"fix|modify|optimi[sz]e|refactor|update|simplify|merge|remove|implement",
    re.I,
)
MAINTENANCE_OBJECT_RE = re.compile(
    r"Xunji|Claude\s*Code|主驾驶|框架|harness|hook|skill|提示词|prompt|"
    r"turn[_ -]?contract|maintenance|工作流|workflow|架构|"
    r"architecture|仓库|repository|\.claude/|CLAUDE\.md|tools/harness/",
    re.I,
)
CONTINUE_ONLY_RE = re.compile(
    r"^\s*(?:继续|继续优化|继续修复|continue|resume)(?:[。.!！])?\s*$", re.I,
)

# The file-backed manifest mirrors this compiled floor. Deleting/corrupting it
# cannot remove the bootstrap boundary that protects parser and enforcement.
DEFAULT_EXACT = {
    ".claude/settings.json",
    ".claude/settings.local.json",
    "config.ini",
    "tools/agent_instruction_bundle.py",
    "tools/anti_drift.py",
    "tools/agent_settlement.py",
    "tools/cdn_bypass.py",
    "tools/check_run.py",
    "tools/check_hook.py",
    "tools/check_rules.py",
    "tools/check_runtime_boundary.py",
    "tools/check_templates.py",
    "tools/classify_hosts.py",
    "tools/context_pack.py",
    "tools/coverage_matrix.py",
    "tools/evidence_parse.py",
    "tools/exploit.py",
    "tools/fetch_assets.py",
    "tools/graph.py",
    "tools/harness/__init__.py",
    "tools/harness/capability_registry.py",
    "tools/harness/command_shape.py",
    "tools/harness/codex_proxy.py",
    "tools/harness/codex_proxy.conf",
    "tools/harness/guard.py",
    "tools/harness/maintenance_authority.py",
    "tools/harness/privacy.py",
    "tools/harness/proxy.py",
    "tools/harness/proxy.conf",
    "tools/harness/safety_critical_paths.json",
    "tools/ingest_recon.py",
    "tools/knowledge_match.py",
    "tools/loop_bootstrap.py",
    "tools/loop_journal.py",
    "tools/loop_state.py",
    "tools/peer_review.py",
    "tools/probe.py",
    "tools/progress_ledger.py",
    "tools/render.py",
    "tools/replay.py",
    "tools/rerun_deferred.py",
    "tools/run_controller.py",
    "tools/run_model.py",
    "tools/runtime_receipts.py",
    "tools/scope_admission.py",
    "tools/saturation.py",
    "tools/scan.py",
    "tools/scope.py",
    "tools/selftest_all.py",
    "tools/session_handoff.py",
    "tools/setup_run.py",
    "tools/setup_normalizer.py",
    "tools/setup_normalizer_bench.py",
    "tools/setup_source.py",
    "tools/setup_transaction.py",
    "tools/state_project.py",
    "tools/status_style.py",
    "tools/timestamp_gate.py",
    "tools/turn_contract.py",
    "tools/work_plan.py",
    "tools/workers.py",
    "tools/xunji_statusline.py",
    "tools/xday_match.py",
}
DEFAULT_PREFIXES = {
    ".claude/agents",
    ".claude/hooks",
    "contracts",
    "docs/templates/agents",
    "sentinel",
    "tools/__pycache__",
    "tools/harness/.state",
    "tools/harness/__pycache__",
}
FORBIDDEN_SCOPE_EXACT = {
    ".claude/xunji_active_run",
}
FORBIDDEN_SCOPE_PREFIXES = {
    ".git",
    ".claude/xunji_pending_turns",
    ".claude/xunji_session_selections",
    ".claude/xunji_transition_claims",
    ".claude/xunji_scope_admission_claims",
    "runs",
    "tools/__pycache__",
    "tools/harness/.state",
    "tools/harness/__pycache__",
}
PATH_KEYS = {"destination", "dest"}
PATH_KEY_RE = re.compile(
    r"(?i)(?:^|_)(?:path|paths|file|files|filepath|filepaths|filename|filenames)$"
)
WRITE_TOOLS = {"Write", "Edit", "Update", "MultiEdit", "NotebookEdit"}
_WINDOWS_ABSOLUTE = re.compile(r"^[A-Za-z]:[/\\]")
_GLOB_CHARS = re.compile(r"[*?\[\]{}]")


def _canonical_relative(
    value: str,
    *,
    root: Path = ROOT,
    allow_absolute: bool = False,
) -> str:
    raw = str(value or "").strip().replace("\\", "/")
    if not raw or "\x00" in raw or "\n" in raw or "\r" in raw:
        raise ValueError("path is empty or contains control bytes")
    is_absolute = raw.startswith("/") or bool(_WINDOWS_ABSOLUTE.match(raw))
    if raw.startswith("~") or (is_absolute and not allow_absolute):
        raise ValueError("maintenance scope must be repository-relative")
    if _GLOB_CHARS.search(raw):
        raise ValueError("maintenance scope does not accept globs")
    parts = raw.lstrip("/").split("/") if is_absolute else raw.split("/")
    if any(part in {"", ".", ".."} for part in parts):
        raise ValueError("maintenance scope must be a normalized exact path")
    candidate = (Path(raw) if is_absolute else root / Path(*parts)).resolve(strict=False)
    try:
        relative = candidate.relative_to(root.resolve())
    except ValueError as exc:
        raise ValueError("maintenance scope escapes the repository") from exc
    return relative.as_posix()


def load_critical_paths(
    *,
    root: Path = ROOT,
    manifest: Path = MANIFEST,
) -> tuple[set[str], set[str]]:
    exact = set(DEFAULT_EXACT)
    prefixes = set(DEFAULT_PREFIXES)
    try:
        value = json.loads(manifest.read_text(encoding="utf-8", errors="strict"))
        if not isinstance(value, dict) or value.get("schema") != SCHEMA:
            raise ValueError("wrong manifest schema")
        file_exact = value.get("exact")
        file_prefixes = value.get("prefixes")
        if not isinstance(file_exact, list) or not isinstance(file_prefixes, list):
            raise ValueError("manifest path lists are invalid")
        exact.update(_canonical_relative(item, root=root) for item in file_exact)
        prefixes.update(
            _canonical_relative(item, root=root).rstrip("/") for item in file_prefixes
        )
    except Exception:
        # Fail closed to the compiled boundary. A broken manifest can never make
        # the parser/guard/settings writable from an ordinary live /loop turn.
        pass
    return exact, prefixes


def is_critical_path(value: str, *, root: Path = ROOT) -> bool:
    try:
        path = _canonical_relative(value, root=root)
    except ValueError:
        return False
    exact, prefixes = load_critical_paths(root=root)
    return path in exact or any(path.startswith(prefix + "/") for prefix in prefixes)


def path_allowed(path: str) -> bool:
    """Return whether a normalized repository path is editable in maintenance."""
    if path in FORBIDDEN_SCOPE_EXACT:
        return False
    return not any(
        path == prefix or path.startswith(prefix + "/")
        for prefix in FORBIDDEN_SCOPE_PREFIXES
    )


def operator_intent(
    prompt: str,
    *,
    previous_mode: str = "",
    lifecycle_intent: bool = False,
) -> bool:
    """Recognize ordinary operator wording as local framework maintenance.

    Only the first non-empty instruction is considered.  Quoted target/tool
    output later in the prompt cannot mint the mode.  A terse ``继续`` inherits
    an immediately preceding maintenance mode because this is a single-user
    conversational tool, not a cross-user authorization boundary.
    """
    first = next((line.strip() for line in str(prompt or "").splitlines() if line.strip()), "")
    if not first:
        return False
    if re.match(r"^/xunji-maintenance(?:\s|$)", first):
        return True
    # A top-level lifecycle instruction is the primary effect.  Framework words
    # in a trailing recovery clause (for example "if a Hook denies it, repair
    # and retry") must not turn an operator /loop into repository maintenance.
    if lifecycle_intent or re.match(r"^/loop(?:\s|$)", first, re.I):
        return False
    if previous_mode == "MAINTENANCE" and (
            CONTINUE_ONLY_RE.fullmatch(first)
            or re.match(r"^(?:继续|continue|resume).{0,40}(?:修复|修改|优化|fix|modify|optimi[sz]e)", first, re.I)
    ):
        return True
    return bool(MAINTENANCE_ACTION_RE.search(first) and MAINTENANCE_OBJECT_RE.search(first))


def _path_key(value: object) -> bool:
    raw = str(value or "").strip().replace("-", "_")
    # Claude tool schemas use both snake_case and camelCase spellings. Normalize
    # the latter before matching the final semantic component so nested fields
    # such as ``edits[].sourcePaths`` cannot disappear from the effect set.
    normalized = re.sub(r"(?<!^)(?=[A-Z])", "_", raw).lower()
    return normalized in PATH_KEYS or bool(PATH_KEY_RE.search(normalized))


def structured_path_values(value: object) -> tuple[list[str], list[str]]:
    """Return every raw path member plus deterministic invalid-member markers.

    A path-like field may contain one string or nested lists of strings. Other
    values, including an empty list, are invalid but are not silently discarded.
    Dict/list containers outside a path field are traversed so edit collections
    such as ``edits[].file_path`` remain part of the same direct mutation.
    """
    paths: list[str] = []
    invalid: list[str] = []

    def invalid_marker(node: object) -> str:
        if isinstance(node, str):
            return node
        try:
            return json.dumps(node, ensure_ascii=False, sort_keys=True)
        except Exception:
            return f"<{type(node).__name__}>"

    def visit(
        node: object,
        *,
        path_member: bool = False,
        nested_path_list: bool = False,
    ) -> None:
        if path_member:
            if isinstance(node, str):
                paths.append(node)
                return
            if isinstance(node, list):
                # One list level is the supported list-valued path shape. A
                # nested container is retained and traversed for auditability,
                # but remains invalid so a malformed member cannot fail open.
                if nested_path_list or not node:
                    invalid.append(invalid_marker(node))
                for child in node:
                    visit(
                        child, path_member=True, nested_path_list=True)
                return
            invalid.append(invalid_marker(node))
            # Preserve the invalid container while still discovering any nested
            # explicitly named path members for the canonical receipt set.
            if isinstance(node, dict):
                visit(node)
            return
        if isinstance(node, dict):
            for child_key, child in node.items():
                if _path_key(child_key):
                    visit(child, path_member=True)
                elif isinstance(child, (dict, list)):
                    visit(child)
        elif isinstance(node, list):
            for child in node:
                visit(child)

    visit(value)
    return paths, invalid


def event_path_values(event: dict) -> tuple[list[str], list[str]]:
    """Return raw structured path members and non-string/container errors."""
    tool_input = event.get("tool_input")
    if not isinstance(tool_input, dict):
        return [], [f"<{type(tool_input).__name__}>"]
    return structured_path_values(tool_input)


def event_paths(event: dict, *, root: Path = ROOT) -> tuple[list[str], list[str]]:
    """Return normalized direct tool paths and invalid path values."""
    raw_paths, invalid = event_path_values(event)
    paths: list[str] = []
    for raw in raw_paths:
        try:
            path = _canonical_relative(raw, root=root, allow_absolute=True)
        except ValueError:
            invalid.append(str(raw))
            continue
        if path not in paths:
            paths.append(path)
    return paths, invalid


def critical_paths_for_event(event: dict, *, root: Path = ROOT) -> list[str]:
    """Find explicit critical paths touched/referenced by a tool request."""
    exact, prefixes = load_critical_paths(root=root)
    paths, _ = event_paths(event, root=root)
    found = {
        path for path in paths
        if path in exact or any(path.startswith(prefix + "/") for prefix in prefixes)
    }
    if str(event.get("tool_name") or "") == "Bash":
        tool_input = event.get("tool_input") if isinstance(event.get("tool_input"), dict) else {}
        command = str(tool_input.get("command") or "").replace("\\", "/")
        for path in sorted(exact):
            if path in command:
                found.add(path)
        for prefix in sorted(prefixes):
            match = re.search(re.escape(prefix) + r"/[^\s'\";&|]+", command)
            if match:
                try:
                    found.add(_canonical_relative(match.group(0), root=root))
                except ValueError:
                    pass
        basenames: dict[str, list[str]] = {}
        for path in exact:
            basenames.setdefault(Path(path).name, []).append(path)
        try:
            tokens = shlex.split(command)
        except ValueError:
            tokens = []
        for token in tokens:
            name = Path(token.strip("'\"[](),;")).name
            if name in basenames and len(basenames[name]) == 1:
                found.add(basenames[name][0])
    return sorted(found)


def _selftest() -> int:
    import tempfile

    root = Path(tempfile.mkdtemp())
    for path in DEFAULT_EXACT:
        target = root / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text("# fixture\n", encoding="utf-8")
    for prefix in DEFAULT_PREFIXES:
        (root / prefix).mkdir(parents=True, exist_ok=True)
    manifest = root / "tools/harness/safety_critical_paths.json"
    manifest.write_text(json.dumps({
        "schema": SCHEMA,
        "exact": sorted(DEFAULT_EXACT),
        "prefixes": sorted(DEFAULT_PREFIXES),
    }), encoding="utf-8")

    checks: list[tuple[str, bool]] = []
    checks.append(("ordinary operator wording derives maintenance intent",
                   operator_intent("修复 Xunji turn contract，并更新文档")))
    checks.append(("legacy maintenance alias is optional and argument-free",
                   operator_intent("/xunji-maintenance 修复 hook")))
    checks.append(("terse continuation inherits only a prior maintenance turn",
                   operator_intent("继续", previous_mode="MAINTENANCE")
                   and operator_intent(
                       "继续修复本地代码", previous_mode="MAINTENANCE")
                   and not operator_intent("继续", previous_mode="EXECUTE")))
    checks.append(("generic target bug wording does not imply framework maintenance",
                   not operator_intent("修复目标代码中的 bug 和登录问题")
                   and not operator_intent("fix the target code bug")
                   and not operator_intent("修复目标 session 超时问题")
                   and not operator_intent("fix the target pointer bug")))
    checks.append(("lifecycle primary intent outranks a maintenance recovery clause",
                   not operator_intent(
                       "/loop https://operator-e2e.invalid 创建 run；"
                       "若 Xunji Hook 拒绝则修复并重试")
                   and not operator_intent(
                       "创建新 run；若 Xunji Hook 拒绝则修复并重试",
                       lifecycle_intent=True)))
    adjacent = root / "docs/maintenance-note.md"
    adjacent.parent.mkdir(parents=True, exist_ok=True)
    adjacent.write_text("# note\n", encoding="utf-8")
    checks.append(("later source text cannot mint maintenance intent",
                   not operator_intent(
                       "/loop runs/example\nquoted target: /xunji-maintenance 修复 hook")))
    checks.append(("live-run and control-state paths remain forbidden",
                   not path_allowed("runs/example/frontier.md")
                   and not path_allowed(".claude/xunji_active_run")
                   and not path_allowed(".git/index")
                   and path_allowed("tools/turn_contract.py")
                   and path_allowed("docs/maintenance-note.md")))
    edit = {"tool_name": "Edit", "tool_input": {
        "file_path": str(root / "tools/turn_contract.py"), "old_string": "a", "new_string": "b",
    }}
    checks.append(("absolute tool path normalizes inside root",
                   event_paths(edit, root=root)[0] == ["tools/turn_contract.py"]))
    alternate_path_key = {"tool_name": "Edit", "tool_input": {
        "file_path": str(root / "tools/turn_contract.py"),
        "source_path": str(root / "docs/maintenance-note.md"),
    }}
    checks.append(("path-key variants cannot hide an additional file",
                   event_paths(alternate_path_key, root=root)[0] == [
                       "tools/turn_contract.py", "docs/maintenance-note.md",
                   ]))
    list_paths = {"tool_name": "MultiEdit", "tool_input": {
        "edits": [{
            "filePaths": [
                str(root / "tools/turn_contract.py"),
                str(root / "docs/maintenance-note.md"),
            ],
        }],
    }}
    checks.append(("nested list-valued path fields are complete",
                   event_paths(list_paths, root=root) == ([
                       "tools/turn_contract.py", "docs/maintenance-note.md",
                   ], [])))
    invalid_members = {"tool_name": "MultiEdit", "tool_input": {
        "file_paths": [
            str(root / "tools/turn_contract.py"), "", "tools/*.py",
            "../escape.py", [], None,
        ],
    }}
    invalid_paths, invalid_values = event_paths(invalid_members, root=root)
    checks.append(("invalid list members are preserved beside valid paths",
                   invalid_paths == ["tools/turn_contract.py"]
                   and {"", "tools/*.py", "../escape.py", "[]", "null"}
                   <= set(invalid_values)))
    internal_alias = root / "docs-alias"
    internal_alias.symlink_to(root / "docs", target_is_directory=True)
    alias_event = {"tool_name": "Write", "tool_input": {
        "file_path": str(internal_alias / "missing" / "new.md"),
    }}
    checks.append(("symlink aliases with nonexistent tails canonicalize once",
                   event_paths(alias_event, root=root) == (
                       ["docs/missing/new.md"], [])))
    external = root.parent / f"{root.name}-outside"
    external.mkdir()
    escaping_alias = root / "escaping-alias"
    escaping_alias.symlink_to(external, target_is_directory=True)
    escaping_event = {"tool_name": "Write", "tool_input": {
        "file_path": str(escaping_alias / "missing.md"),
    }}
    escaped_paths, escaped_values = event_paths(escaping_event, root=root)
    checks.append(("symlink escape with nonexistent tail fails closed",
                   not escaped_paths and escaped_values == [
                       str(escaping_alias / "missing.md")]))
    checks.append(("critical Edit path detected",
                   critical_paths_for_event(edit, root=root) == ["tools/turn_contract.py"]))
    bash = {"tool_name": "Bash", "tool_input": {
        "command": "sed -i '' s/a/b/ tools/turn_contract.py",
    }}
    checks.append(("critical Bash path detected",
                   "tools/turn_contract.py" in critical_paths_for_event(bash, root=root)))
    control_paths_rejected = True
    for candidate in ("tools/bad\x00.py", "tools/bad\n.py", "tools/bad\r.py"):
        try:
            _canonical_relative(candidate, root=root)
        except ValueError:
            continue
        control_paths_rejected = False
    checks.append(("path control bytes fail closed", control_paths_rejected))
    manifest.write_text("{broken", encoding="utf-8")
    exact, prefixes = load_critical_paths(root=root, manifest=manifest)
    checks.append(("broken manifest preserves compiled boundary",
                   "tools/turn_contract.py" in exact and "sentinel" in prefixes))

    bad = [name for name, ok in checks if not ok]
    for name, ok in checks:
        print(("ok   " if ok else "FAIL ") + name)
    print("maintenance_authority selftest " + ("passed" if not bad else f"FAILED ({len(bad)})"))
    return 0 if not bad else 1


if __name__ == "__main__":
    raise SystemExit(_selftest() if "--selftest" in sys.argv or len(sys.argv) == 1 else 2)
