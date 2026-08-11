#!/usr/bin/env python3
"""Local/publication hygiene checks for files that must stay local.

This is deliberately broader than a credential scanner. Xunji keeps real run
evidence, local runtime config, and tool runtimes out of the published repo even
when their contents are not classical secrets.
"""
from __future__ import annotations

import argparse
import json
import re
import stat
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

SECRET_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    ("github-token", re.compile(r"\bgh[pousr]_[A-Za-z0-9_]{20,}\b")),
    ("ark-api-key", re.compile(r"\bark-[A-Za-z0-9_-]{20,}\b")),
    ("generic-password-assignment", re.compile(r"(?i)\b(password|passwd|token|secret|api[_-]?key)\s*=\s*[^;\s\"']{8,}")),
    ("credential-helper-inline", re.compile(r"credential\.helper=.*(password|token|secret)", re.IGNORECASE)),
]

LOCAL_FILES = [
    ROOT / ".claude" / "settings.local.json",
]
PERMISSION_EXAMPLE = ROOT / ".claude" / "settings.local.example.json"
MAX_LOCAL_CONFIG_BYTES = 256 * 1024

FORBIDDEN_TRACKED_EXACT = {
    "config.ini": "local runtime config is ignored; keep only config.example.ini tracked",
    ".claude/settings.local.json": (
        "operator-local Claude permissions must stay untracked; keep only "
        "settings.local.example.json tracked"
    ),
    ".codex/hooks.json": "Codex hook runtime is not maintained; use .claude/hooks only",
    "review/review_bundle.json": "generated peer-review bundle is run/scope-local output",
}

FORBIDDEN_TRACKED_PREFIXES = {
    "runs/": "real run workbenches are local evidence, not published fixtures",
    "evidence/": "root evidence is not a canonical run; move it under runs/<run>/evidence",
    ".codex/hooks/": "Codex hook runtime is not maintained; use .claude/hooks only",
}

ROOT_RUN_DIR_RE = re.compile(
    r"^[^/]+_20\d{6}(?:_20\d{6})?/",
)
ROOT_CAPTURE_RE = re.compile(
    r"(?i)^(?:cap(?:tcha)?[^/]*|screen(?:shot)?[^/]*|scrn[^/]*|[^/]*ocr[^/]*)"
    r"\.(?:png|jpe?g|gif|webp)$"
)


def _read_local_text(path: Path) -> tuple[str | None, list[str]]:
    """Read one bounded regular local file without following a symlink."""
    try:
        info = path.lstat()
    except FileNotFoundError:
        return None, []
    except OSError as exc:
        return None, [
            f"{path.name}: local config metadata is unreadable ({type(exc).__name__})"
        ]
    if stat.S_ISLNK(info.st_mode) or not stat.S_ISREG(info.st_mode):
        return None, [f"{path.name}: local config must be a regular non-symlink file"]
    if info.st_size > MAX_LOCAL_CONFIG_BYTES:
        return None, [
            f"{path.name}: local config exceeds {MAX_LOCAL_CONFIG_BYTES} byte limit"
        ]
    try:
        return path.read_text(encoding="utf-8", errors="strict"), []
    except (OSError, UnicodeError) as exc:
        return None, [
            f"{path.name}: local config is unreadable ({type(exc).__name__})"
        ]


def _secret_issues(path: Path, text: str) -> list[str]:
    issues: list[str] = []
    for lineno, line in enumerate(text.splitlines(), 1):
        for category, pattern in SECRET_PATTERNS:
            if pattern.search(line):
                try:
                    rel = path.relative_to(ROOT)
                except ValueError:
                    rel = path
                issues.append(f"{rel}:{lineno}: credential-looking string ({category})")
                break
    return issues


def scan_file(path: Path) -> list[str]:
    text, read_issues = _read_local_text(path)
    if text is None:
        return read_issues
    return [*read_issues, *_secret_issues(path, text)]


def _local_permission_issues_from_text(path: Path, text: str) -> list[str]:
    """Return privacy-safe findings for Claude's local auto-allow surface.

    This intentionally does not parse shell syntax.  The project-owned minimal
    contract is mechanical: an empty auto-allow list.  Any non-empty list is a
    local hygiene HOLD, while Hooks remain the actual Xunji authority boundary.
    """
    try:
        value = json.loads(text)
    except json.JSONDecodeError as exc:
        return [
            f"{path.name}: Claude local permission config is unreadable or invalid "
            f"({type(exc).__name__})"
        ]
    if not isinstance(value, dict):
        return [f"{path.name}: Claude local permission config root must be an object"]
    permissions = value.get("permissions", {})
    if not isinstance(permissions, dict):
        return [f"{path.name}: permissions must be an object"]
    values: dict[str, list[str]] = {}
    for name in ("allow", "ask", "deny"):
        rules = permissions.get(name, [])
        if not isinstance(rules, list) or not all(
                isinstance(item, str)
                and 0 < len(item.encode("utf-8", "replace")) <= 8192
                and re.search(r"[\x00-\x1f\x7f]", item) is None
                for item in rules):
            return [f"{path.name}: permissions.{name} must be a bounded string list"]
        values[name] = rules
    if not values["allow"]:
        return []
    return [
        f"{path.name}: Claude local auto-allow is non-empty "
        f"(auto_allow_count={len(values['allow'])}); local permissions are convenience "
        "only and Xunji Hooks remain authoritative"
    ]


def local_permission_issues(path: Path) -> list[str]:
    text, read_issues = _read_local_text(path)
    if text is None:
        return read_issues
    return [*read_issues, *_local_permission_issues_from_text(path, text)]


def _permission_example_issues_from_text(path: Path, text: str) -> list[str]:
    """Validate the repository-owned minimal permission example.

    This is a drift check for a convenience template, not an authority or
    safety boundary.  The live local file is still checked separately and all
    actual tool calls remain subject to Xunji Hooks.
    """
    base_issues = _local_permission_issues_from_text(path, text)
    if base_issues:
        return base_issues
    value = json.loads(text)
    if set(value) != {"permissions"}:
        return [f"{path.name}: example root must contain only permissions"]
    permissions = value["permissions"]
    unexpected = set(permissions) - {"allow", "ask", "deny"}
    if unexpected:
        return [f"{path.name}: example permissions contains unsupported keys"]
    if "allow" not in permissions or permissions["allow"] != []:
        return [f"{path.name}: example must declare permissions.allow as empty"]
    if "ask" not in permissions or not permissions["ask"]:
        return [f"{path.name}: example must retain a non-empty permissions.ask list"]
    return []


def permission_example_issues(path: Path = PERMISSION_EXAMPLE) -> list[str]:
    text, read_issues = _read_local_text(path)
    if text is None:
        return read_issues or [f"{path.name}: repository permission example is missing"]
    return [
        *read_issues,
        *_secret_issues(path, text),
        *_permission_example_issues_from_text(path, text),
    ]


def check(paths: list[Path] | None = None) -> list[str]:
    selected = paths or LOCAL_FILES
    issues: list[str] = []
    for path in selected:
        text, read_issues = _read_local_text(path)
        issues.extend(read_issues)
        if text is None:
            continue
        issues.extend(_secret_issues(path, text))
        issues.extend(_local_permission_issues_from_text(path, text))
    if paths is None:
        issues.extend(permission_example_issues())
        issues.extend(check_publication_index())
    return issues


def _git_lines(args: list[str]) -> list[str]:
    try:
        proc = subprocess.run(
            ["git", *args],
            cwd=ROOT,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=20,
            check=False,
        )
    except Exception as e:  # noqa: BLE001 - hygiene should surface tool problems.
        return [f"__git_error__:{e!r}"]
    if proc.returncode != 0:
        msg = (proc.stderr or proc.stdout or "").strip()
        return [f"__git_error__:git {' '.join(args)} failed: {msg}"]
    return [line for line in proc.stdout.splitlines() if line.strip()]


def publication_issues_for_tracked(
    tracked: list[str],
    tracked_ignored: list[str] | None = None,
) -> list[str]:
    issues: list[str] = []
    for rel in tracked_ignored or []:
        issues.append(f"{rel}: tracked file is ignored by .gitignore; remove from index")
    for rel in tracked:
        reason = FORBIDDEN_TRACKED_EXACT.get(rel)
        if reason:
            issues.append(f"{rel}: {reason}")
            continue
        for prefix, prefix_reason in FORBIDDEN_TRACKED_PREFIXES.items():
            if rel.startswith(prefix) and rel != "runs/.gitkeep":
                issues.append(f"{rel}: {prefix_reason}")
                break
        else:
            if ROOT_RUN_DIR_RE.match(rel):
                issues.append(f"{rel}: root-level real run workbench must stay local")
            elif "/" not in rel and (
                    rel.endswith(".replay.json")
                    or ROOT_CAPTURE_RE.fullmatch(rel)
                    or rel.lower().endswith((".html", ".htm"))):
                issues.append(
                    f"{rel}: root-level target artifact must stay in a run or local quarantine"
                )
    return issues


def workspace_output_warnings(untracked: list[str] | None = None) -> list[str]:
    """Report output-layout drift without opening or modifying target files."""
    paths = untracked if untracked is not None else _git_lines(
        ["ls-files", "--others", "--exclude-standard"]
    )
    git_errors = [
        value.removeprefix("__git_error__:")
        for value in paths if value.startswith("__git_error__:")
    ]
    if git_errors:
        return [f"workspace output audit unavailable: {error}" for error in git_errors]
    normalized = {Path(value).as_posix() for value in paths}
    root_replays = {
        value for value in normalized
        if "/" not in value and value.endswith(".replay.json")
    }
    root_bodies = {
        value for value in normalized
        if "/" not in value and value.lower().endswith((".html", ".htm"))
    }
    root_captures = {
        value for value in normalized
        if "/" not in value and ROOT_CAPTURE_RE.fullmatch(value)
    }
    root_evidence = {value for value in normalized if value.startswith("evidence/")}
    double_replays = {
        value for value in normalized if value.endswith(".replay.json.replay.json")
    }
    warnings: list[str] = []
    if root_bodies or root_replays or root_captures:
        warnings.append(
            "workspace output drift: "
            f"root bodies={len(root_bodies)}, replay sidecars={len(root_replays)}, "
            f"capture/OCR files={len(root_captures)}; use runs/<run>/evidence/ or "
            "the dry-run migration tool"
        )
    if root_evidence:
        warnings.append(
            f"workspace output drift: top-level evidence/ contains {len(root_evidence)} "
            "untracked files but is not a canonical run"
        )
    if double_replays:
        warnings.append(
            f"workspace output drift: {len(double_replays)} double replay sidecars; "
            "--save must name the response body, not a .replay.json file"
        )
    return warnings


def check_publication_index() -> list[str]:
    tracked = _git_lines(["ls-files"])
    tracked_ignored = _git_lines(["ls-files", "-ci", "--exclude-standard"])
    git_errors = [
        line.removeprefix("__git_error__:")
        for line in [*tracked, *tracked_ignored]
        if line.startswith("__git_error__:")
    ]
    if git_errors:
        return [f"git index hygiene unavailable: {err}" for err in git_errors]
    return publication_issues_for_tracked(tracked, tracked_ignored)


def _selftest() -> int:
    d = Path(tempfile.mkdtemp())
    clean = d / "clean.json"
    clean.write_text('{"allow":["Bash(python3 tools/check_run.py runs/x)"]}\n', encoding="utf-8")
    dirty = d / "dirty.json"
    dirty.write_text('{"allow":["credential.helper=!f(){ echo password=gho_abcdefghijklmnopqrstuvwxyz; }"]}\n',
                     encoding="utf-8")
    broad_permissions = d / "broad-permissions.json"
    broad_permissions.write_text(json.dumps({
        "permissions": {
            "allow": [
                "Bash(python3 *)",
                "Bash(python -c 'private-value')",
                "Bash(git add *)",
                "Bash(python /tmp/private-target.py)",
            ],
            "ask": [],
        },
    }), encoding="utf-8")
    exact_permissions = d / "exact-permissions.json"
    exact_permissions.write_text(json.dumps({
        "permissions": {
            "allow": ["Bash(python3 tools/check_rules.py)"],
            "ask": ["Bash(git push:*)"],
        },
    }), encoding="utf-8")
    malformed_permissions = d / "malformed-permissions.json"
    malformed_permissions.write_text('{"permissions":', encoding="utf-8")
    malformed_ask = d / "malformed-ask.json"
    malformed_ask.write_text(json.dumps({
        "permissions": {"allow": [], "ask": "Bash(git push:*)"},
    }), encoding="utf-8")
    oversized_permissions = d / "oversized-permissions.json"
    oversized_permissions.write_bytes(b"x" * (MAX_LOCAL_CONFIG_BYTES + 1))
    permission_symlink = d / "permission-symlink.json"
    permission_symlink.symlink_to(exact_permissions)
    clean_example = d / "settings.local.example.json"
    clean_example.write_text(json.dumps({
        "permissions": {
            "allow": [],
            "ask": ["Bash(git push:*)"],
        },
    }), encoding="utf-8")
    drifted_example = d / "drifted-settings.local.example.json"
    drifted_example.write_text(json.dumps({
        "permissions": {"ask": []},
    }), encoding="utf-8")
    secret_example = d / "secret-settings.local.example.json"
    secret_example.write_text(json.dumps({
        "permissions": {
            "allow": [],
            "ask": [
                "Bash(tool --token=gho_abcdefghijklmnopqrstuvwxyz:*)",
            ],
        },
    }), encoding="utf-8")
    clean_issues = check([clean])
    dirty_issues = check([dirty])
    leaked = any("abcdefghijklmnopqrstuvwxyz" in i for i in dirty_issues)
    broad_permission_issues = local_permission_issues(broad_permissions)
    exact_permission_issues = local_permission_issues(exact_permissions)
    malformed_permission_issues = local_permission_issues(malformed_permissions)
    malformed_ask_issues = local_permission_issues(malformed_ask)
    oversized_permission_issues = local_permission_issues(oversized_permissions)
    symlink_permission_issues = local_permission_issues(permission_symlink)
    clean_example_issues = permission_example_issues(clean_example)
    drifted_example_issues = permission_example_issues(drifted_example)
    secret_example_issues = permission_example_issues(secret_example)
    missing_example_issues = permission_example_issues(d / "missing-example.json")
    tracked_issues = publication_issues_for_tracked(
        [
            "README.md",
            "runs/.gitkeep",
            "runs/live_20260707/evidence.md",
            "school_20260707/evidence/body.html",
            "config.ini",
            ".claude/settings.local.json",
            ".codex/hooks/safety_gate.py",
            "review/review_bundle.json",
            "evidence/orphan.html",
            "body-without-sidecar.html",
            "loose.html",
            "loose.html.replay.json",
            "captcha-ocr.png",
            "screenshot.png",
        ],
        ["config.ini"],
    )
    workspace_warnings = workspace_output_warnings([
        "loose.html", "loose.html.replay.json",
        "body-without-sidecar.html",
        "evidence/body.replay.json", "evidence/body.replay.json.replay.json",
        "captcha-ocr.png",
    ])
    checks = [
        ("clean file has no issues", clean_issues == []),
        ("dirty file reports category", dirty_issues and "github-token" in dirty_issues[0]),
        ("dirty report redacts value", not leaked),
        ("non-empty local auto-allow is counted without parsing or disclosure",
         len(broad_permission_issues) == 1
         and "auto_allow_count=4" in broad_permission_issues[0]
         and "private-value" not in broad_permission_issues[0]
         and "private-target" not in broad_permission_issues[0]),
        ("even one exact auto-allow remains outside the minimal local template",
         len(exact_permission_issues) == 1
         and "auto_allow_count=1" in exact_permission_issues[0]
         and "check_rules.py" not in exact_permission_issues[0]),
        ("malformed local permission config fails closed without bytes",
         len(malformed_permission_issues) == 1
         and "JSONDecodeError" in malformed_permission_issues[0]
         and "permissions\":" not in malformed_permission_issues[0]),
        ("ask and deny shapes are bounded string lists",
         len(malformed_ask_issues) == 1
         and "permissions.ask" in malformed_ask_issues[0]),
        ("oversized and symlink local configs fail closed",
         len(oversized_permission_issues) == 1
         and "byte limit" in oversized_permission_issues[0]
         and len(symlink_permission_issues) == 1
         and "non-symlink" in symlink_permission_issues[0]),
        ("repository permission example keeps the minimal bounded shape",
         clean_example_issues == []
         and len(drifted_example_issues) == 1
         and "permissions.allow" in drifted_example_issues[0]),
        ("repository permission example rejects secrets without echoing them",
         len(secret_example_issues) == 1
         and "github-token" in secret_example_issues[0]
         and "abcdefghijklmnopqrstuvwxyz" not in secret_example_issues[0]),
        ("missing repository permission example fails closed",
         len(missing_example_issues) == 1
         and "missing" in missing_example_issues[0]),
        ("publication allows runs/.gitkeep", not any("runs/.gitkeep" in i for i in tracked_issues)),
        ("publication rejects ignored tracked config", any("tracked file is ignored" in i for i in tracked_issues)),
        ("publication rejects tracked local Claude permissions without global ignores",
         any(".claude/settings.local.json" in i for i in tracked_issues)),
        ("publication rejects tracked run evidence", any("runs/live_20260707" in i for i in tracked_issues)),
        ("publication rejects root run workbench", any("school_20260707" in i for i in tracked_issues)),
        ("publication rejects Codex hooks", any(".codex/hooks" in i for i in tracked_issues)),
        ("publication rejects generated review bundle",
         any("review/review_bundle.json" in i for i in tracked_issues)),
        ("publication rejects top-level evidence directory",
         any("evidence/orphan.html" in i for i in tracked_issues)),
        ("publication rejects root body/replay pairs",
         any("loose.html" in i for i in tracked_issues)),
        ("publication rejects lone root HTML body",
         any("body-without-sidecar.html" in i for i in tracked_issues)),
        ("publication rejects root capture/OCR files",
         any("captcha-ocr.png" in i for i in tracked_issues)
         and any("screenshot.png" in i for i in tracked_issues)),
        ("workspace warning counts output drift without file content",
         len(workspace_warnings) == 3
         and "root bodies=2" in workspace_warnings[0]
         and all("loose.html" not in warning for warning in workspace_warnings)),
    ]
    bad = [name for name, ok in checks if not ok]
    for name, ok in checks:
        print(("ok   " if ok else "FAIL ") + name)
    print("local hygiene selftest " + ("passed" if not bad else f"FAILED ({len(bad)})"))
    return 0 if not bad else 1


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Check local config for credential-looking strings.")
    parser.add_argument("--selftest", action="store_true", help="run local regression tests")
    args = parser.parse_args(argv)
    if args.selftest:
        return _selftest()
    issues = check()
    warnings = workspace_output_warnings()
    for warning in warnings:
        print(f"warning: {warning}")
    if issues:
        print("local hygiene check failed")
        for issue in issues:
            print(f"- {issue}")
        return 1
    print("local hygiene check passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
