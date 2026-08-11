#!/usr/bin/env python3
"""Plan or apply migration of loose repository-root target artifacts.

The default is a read-only plan.  A file is assigned to a run only when current
canonical Markdown uniquely references its basename; ambiguous and unreferenced
files go to local non-canonical quarantine.  No run receipt or evidence claim is
created by this utility.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import tempfile
import time
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CANONICAL_MARKDOWN = (
    "target.md", "surface.md", "frontier.md", "hypotheses.md", "evidence.md",
    "false_positive.md", "decisions.md", "review.md", "report.md", "chains.md",
    "hints.md", "retrospective.md",
)
ROOT_CAPTURE_RE = re.compile(
    r"(?i)^(?:cap(?:tcha)?[^/]*|screen(?:shot)?[^/]*|scrn[^/]*|[^/]*ocr[^/]*)"
    r"\.(?:png|jpe?g|gif|webp)$"
)
SAFE_BATCH_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,95}\Z")


def _within(path: Path, parent: Path) -> bool:
    try:
        path.relative_to(parent)
        return True
    except ValueError:
        return False


def _safe_managed_path(root: Path, value: str, *, role: str) -> Path:
    """Resolve a migration path without following a managed-tree symlink."""
    relative = Path(value)
    if relative.is_absolute() or not relative.parts \
            or any(part in {"", ".", ".."} for part in relative.parts):
        raise ValueError(f"unsafe {role} path: {value}")
    root_lexical = Path(os.path.abspath(root))
    candidate = Path(os.path.abspath(root_lexical / relative))
    if not _within(candidate, root_lexical):
        raise ValueError(f"unsafe {role} path: {value}")
    current = root_lexical
    for part in relative.parts:
        current = current / part
        if current.is_symlink():
            raise ValueError(f"{role} path contains symlink: {value}")
    root_resolved = root_lexical.resolve(strict=False)
    resolved = candidate.resolve(strict=False)
    if not _within(resolved, root_resolved):
        raise ValueError(f"{role} path escapes repository: {value}")
    return candidate


def _entry_paths(root: Path, entry: dict, *, batch: str) -> tuple[Path, Path]:
    source_rel = str(entry.get("original_path") or "")
    destination_rel = str(entry.get("destination") or "")
    source_parts = Path(source_rel).parts
    if not (len(source_parts) == 1 or (
            source_parts and source_parts[0] == "evidence")):
        raise ValueError(f"source is outside loose artifact roots: {source_rel}")
    destination_parts = Path(destination_rel).parts
    matched_run = entry.get("matched_run")
    assigned_shape = (
        entry.get("status") == "assigned"
        and len(destination_parts) == 4
        and destination_parts[0] == "runs"
        and destination_parts[1] == matched_run
        and destination_parts[2] == "evidence"
    )
    quarantine_shape = (
        entry.get("status") != "assigned"
        and len(destination_parts) == 4
        and destination_parts[:3] == ("artifacts", "orphans", batch)
    )
    if not (assigned_shape or quarantine_shape):
        raise ValueError(f"destination is outside migration roots: {destination_rel}")
    return (
        _safe_managed_path(root, source_rel, role="source"),
        _safe_managed_path(root, destination_rel, role="destination"),
    )


def _destination_unavailable(root: Path, relative: Path) -> bool:
    destination = _safe_managed_path(
        root, relative.as_posix(), role="destination",
    )
    return destination.exists() or destination.is_symlink()


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while True:
            block = handle.read(1024 * 1024)
            if not block:
                break
            digest.update(block)
    return digest.hexdigest()


def _candidate_paths(root: Path) -> tuple[list[Path], list[str]]:
    candidates: list[Path] = []
    warnings: list[str] = []
    for path in root.iterdir():
        if not path.is_file():
            continue
        name = path.name
        artifact = (
            name.endswith(".replay.json")
            or name.lower().endswith((".html", ".htm"))
            or ROOT_CAPTURE_RE.fullmatch(name)
        )
        if artifact:
            if path.is_symlink():
                warnings.append(f"skipped symlink: {name}")
            else:
                candidates.append(path)
    evidence_root = root / "evidence"
    if evidence_root.exists() and not evidence_root.is_symlink():
        for path in evidence_root.rglob("*"):
            if path.is_symlink():
                warnings.append(f"skipped symlink: {path.relative_to(root).as_posix()}")
            elif path.is_file():
                candidates.append(path)
    candidates.sort(key=lambda path: path.relative_to(root).as_posix())
    return candidates, warnings


def _group_key(path: Path, candidate_names: set[str]) -> str:
    name = path.name
    if name.endswith(".replay.json.replay.json"):
        return name.removesuffix(".replay.json")
    if name.endswith(".replay.json"):
        if f"{name}.replay.json" in candidate_names:
            return name
        return name.removesuffix(".replay.json")
    return name


def _run_reference_index(root: Path, names: set[str]) -> dict[str, set[str]]:
    index: dict[str, set[str]] = defaultdict(set)
    runs_root = root / "runs"
    if not runs_root.is_dir():
        return index
    for run in sorted(runs_root.iterdir()):
        if not run.is_dir() or run.name.startswith(".") or run.is_symlink():
            continue
        text_parts: list[str] = []
        for filename in CANONICAL_MARKDOWN:
            path = run / filename
            if path.is_file() and not path.is_symlink():
                text_parts.append(path.read_text(encoding="utf-8", errors="replace"))
        haystack = "\n".join(text_parts)
        for name in names:
            token = re.compile(
                rf"(?<![A-Za-z0-9._-])evidence/"
                rf"{re.escape(name)}(?![A-Za-z0-9._/-])"
            )
            if token.search(haystack):
                index[name].add(run.name)
    return index


def plan_migration(root: Path, *, batch: str) -> dict:
    if not SAFE_BATCH_RE.fullmatch(batch):
        raise ValueError("invalid migration batch id")
    candidates, warnings = _candidate_paths(root)
    grouped: dict[str, list[Path]] = defaultdict(list)
    candidate_names = {path.name for path in candidates}
    for path in candidates:
        grouped[_group_key(path, candidate_names)].append(path)
    names = candidate_names
    refs = _run_reference_index(root, names)
    entries: list[dict] = []
    reserved: set[str] = set()
    for group, paths in sorted(grouped.items()):
        matched_runs = sorted({run for path in paths for run in refs.get(path.name, set())})
        group_status = "assigned" if len(matched_runs) == 1 else (
            "conflict" if len(matched_runs) > 1 else "orphan"
        )
        if group_status == "assigned":
            assigned_destinations = [
                (Path("runs") / matched_runs[0] / "evidence" / path.name)
                for path in paths
            ]
            if len({item.as_posix() for item in assigned_destinations}) != len(paths) \
                    or any(item.as_posix() in reserved
                           or _destination_unavailable(root, item)
                           for item in assigned_destinations):
                group_status = "conflict"
        for path in paths:
            stat = path.stat()
            source_rel = path.relative_to(root).as_posix()
            if group_status == "assigned":
                destination = Path("runs") / matched_runs[0] / "evidence" / path.name
            if group_status != "assigned":
                prefix = "root" if path.parent == root else "evidence"
                destination = Path("artifacts") / "orphans" / batch / f"{prefix}__{path.name}"
                suffix = 1
                while destination.as_posix() in reserved \
                        or _destination_unavailable(root, destination):
                    destination = (
                        Path("artifacts") / "orphans" / batch
                        / f"{prefix}__{suffix}__{path.name}"
                    )
                    suffix += 1
            reserved.add(destination.as_posix())
            entries.append({
                "original_path": source_rel,
                "sha256": _sha256(path),
                "size": stat.st_size,
                "mtime": stat.st_mtime,
                "matched_run": matched_runs[0] if len(matched_runs) == 1 else None,
                "match_basis": "unique canonical evidence-path reference" if len(matched_runs) == 1
                else ("multiple canonical evidence-path references" if matched_runs else "none"),
                "matched_runs": matched_runs,
                "destination": destination.as_posix(),
                "status": group_status,
                "group": group,
                "applied": False,
            })
    return {
        "schema": "xunji.output-migration.v1",
        "batch": batch,
        "mode": "dry-run",
        "entries": entries,
        "warnings": warnings,
    }


def _atomic_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp_name, path)
    finally:
        try:
            Path(tmp_name).unlink()
        except OSError:
            pass


def apply_migration(root: Path, plan: dict) -> dict:
    result = json.loads(json.dumps(plan))
    result["mode"] = "apply"
    warnings = list(result.get("warnings") or [])
    manifest = root / "artifacts" / "output-migrations" / result["batch"] / "manifest.json"
    result["manifest"] = manifest.relative_to(root).as_posix()
    groups: dict[str, list[dict]] = defaultdict(list)
    for entry in result.get("entries", []):
        entry["apply_state"] = "planned"
        entry["source_removed"] = False
        groups[str(entry.get("group") or entry["original_path"])].append(entry)
    result["warnings"] = warnings
    _atomic_json(manifest, result)

    for group, entries in sorted(groups.items()):
        problems: list[str] = []
        for entry in entries:
            try:
                source, destination = _entry_paths(
                    root, entry, batch=result["batch"],
                )
            except ValueError as exc:
                problems.append(str(exc))
                continue
            if not source.is_file() or source.is_symlink():
                problems.append(f"source unavailable or unsafe: {entry['original_path']}")
            elif _sha256(source) != entry["sha256"] \
                    or source.stat().st_size != entry["size"]:
                problems.append(f"source changed since plan: {entry['original_path']}")
            if destination.exists():
                problems.append(f"destination already exists: {entry['destination']}")
        if problems:
            warnings.extend(f"group {group}: {problem}" for problem in problems)
            for entry in entries:
                entry["apply_state"] = "skipped"
            result["warnings"] = warnings
            _atomic_json(manifest, result)
            continue

        staged: list[tuple[dict, Path, Path, Path]] = []
        published: list[Path] = []
        group_token = hashlib.sha256(group.encode("utf-8")).hexdigest()[:12]
        try:
            for entry in entries:
                source, destination = _entry_paths(
                    root, entry, batch=result["batch"],
                )
                destination.parent.mkdir(parents=True, exist_ok=True)
                stage = destination.with_name(
                    f".{destination.name}.xunji-migrate-{result['batch']}-{group_token}.tmp"
                )
                if stage.exists():
                    raise FileExistsError(f"staging path already exists: {stage.relative_to(root)}")
                shutil.copy2(source, stage, follow_symlinks=False)
                if _sha256(stage) != entry["sha256"] \
                        or stage.stat().st_size != entry["size"]:
                    raise OSError(f"staged copy integrity mismatch: {entry['original_path']}")
                staged.append((entry, source, destination, stage))
            for entry, _source, destination, stage in staged:
                os.replace(stage, destination)
                published.append(destination)
                entry["apply_state"] = "published"
            # Originals remain intact until every member is published.  A
            # failed unlink can leave a duplicate, but never a half-pair or data loss.
            for entry, source, destination, _stage in staged:
                try:
                    source.unlink()
                except OSError as exc:
                    warnings.append(
                        f"group {group}: published but source copy remains: "
                        f"{entry['original_path']} ({exc.__class__.__name__})"
                    )
                entry["source_removed"] = not source.exists()
                entry["applied"] = destination.is_file() \
                    and _sha256(destination) == entry["sha256"]
                entry["apply_state"] = "applied" if entry["source_removed"] \
                    else "published_with_source_copy"
        except Exception as exc:  # group rollback while originals are still intact
            if all((root / entry["original_path"]).is_file() for entry in entries):
                for destination in published:
                    try:
                        destination.unlink()
                    except OSError:
                        pass
            for _entry, _source, _destination, stage in staged:
                try:
                    stage.unlink()
                except OSError:
                    pass
            warnings.append(f"group {group}: apply failed ({exc.__class__.__name__}: {exc})")
            for entry in entries:
                entry["apply_state"] = "failed"
        result["warnings"] = warnings
        _atomic_json(manifest, result)

    _atomic_json(manifest, result)
    return result


def _summary(plan: dict) -> dict:
    counts: dict[str, int] = defaultdict(int)
    for entry in plan.get("entries", []):
        counts[str(entry.get("status") or "unknown")] += 1
    return {
        "schema": plan.get("schema"),
        "batch": plan.get("batch"),
        "mode": plan.get("mode"),
        "files": len(plan.get("entries", [])),
        "bytes": sum(int(entry.get("size") or 0) for entry in plan.get("entries", [])),
        "status_counts": dict(sorted(counts.items())),
        "applied": sum(1 for entry in plan.get("entries", []) if entry.get("applied")),
        "warnings": plan.get("warnings", []),
        **({"manifest": plan["manifest"]} if plan.get("manifest") else {}),
    }


def _selftest() -> int:
    root = Path(tempfile.mkdtemp())
    checks: list[tuple[str, bool]] = []
    try:
        run = root / "runs" / "demo_20260101"
        run.mkdir(parents=True)
        (run / "evidence.md").write_text(
            "- Artifacts:\n"
            "  - evidence/proof.html\n"
            "  - evidence/proof.html.replay.json\n"
            "  - evidence/collide.html\n"
            "  - evidence/collide.html.replay.json\n"
            "  - evidence/changed.html\n"
            "  - evidence/changed.html.replay.json\n"
            "  - evidence/render_example/nested-only.html\n",
            encoding="utf-8",
        )
        (root / "proof.html").write_text("body", encoding="utf-8")
        (root / "proof.html.replay.json").write_text("{}", encoding="utf-8")
        (root / "collide.html").write_text("body", encoding="utf-8")
        (root / "collide.html.replay.json").write_text("{}", encoding="utf-8")
        (root / "changed.html").write_text("body", encoding="utf-8")
        (root / "changed.html.replay.json").write_text("{}", encoding="utf-8")
        (root / "nested-only.html").write_text("body", encoding="utf-8")
        (run / "evidence").mkdir()
        (run / "evidence" / "collide.html").write_text("existing", encoding="utf-8")
        (root / "captcha-ocr.png").write_bytes(b"png")
        (root / "screenshot.png").write_bytes(b"png")
        loose = root / "evidence"
        loose.mkdir()
        (loose / "bad.replay.json").write_text("body", encoding="utf-8")
        (loose / "bad.replay.json.replay.json").write_text("{}", encoding="utf-8")
        plan = plan_migration(root, batch="selftest")
        by_name = {entry["original_path"]: entry for entry in plan["entries"]}
        checks.append(("uniquely cited body assigned to run",
                       by_name["proof.html"]["status"] == "assigned"
                       and by_name["proof.html"]["matched_run"] == "demo_20260101"))
        checks.append(("body and replay sidecar share assignment",
                       by_name["proof.html.replay.json"]["status"] == "assigned"))
        checks.append(("one destination collision quarantines the whole pair",
                       by_name["collide.html"]["status"] == "conflict"
                       and by_name["collide.html.replay.json"]["status"] == "conflict"))
        checks.append(("uncited capture quarantined",
                       by_name["captcha-ocr.png"]["status"] == "orphan"))
        checks.append(("common screenshot capture is included in the plan",
                       by_name["screenshot.png"]["status"] == "orphan"))
        checks.append(("nested evidence citation cannot claim a loose basename",
                       by_name["nested-only.html"]["status"] == "orphan"))
        checks.append(("double replay group quarantined without reinterpretation",
                       by_name["evidence/bad.replay.json.replay.json"]["status"] == "orphan"))
        checks.append(("dry-run moves nothing", (root / "proof.html").exists()))
        (root / "changed.html.replay.json").write_text('{"changed":true}', encoding="utf-8")
        applied = apply_migration(root, plan)
        checks.append(("apply moves assigned files under run evidence",
                       (run / "evidence" / "proof.html").is_file()
                       and (run / "evidence" / "proof.html.replay.json").is_file()))
        checks.append(("apply moves unknown files to quarantine",
                       any((root / entry["destination"]).is_file()
                           for entry in applied["entries"]
                           if entry["original_path"] == "captcha-ocr.png")))
        checks.append(("changed sidecar skips the whole body-sidecar group",
                       (root / "changed.html").is_file()
                       and (root / "changed.html.replay.json").is_file()
                       and not (run / "evidence" / "changed.html").exists()
                       and not (run / "evidence" / "changed.html.replay.json").exists()))
        checks.append(("apply writes a durable local manifest",
                       (root / applied["manifest"]).is_file()))

        rollback_root = root / "rollback-case"
        rollback_run = rollback_root / "runs" / "demo_20260101"
        rollback_run.mkdir(parents=True)
        (rollback_run / "evidence.md").write_text(
            "- evidence/rollback.html\n- evidence/rollback.html.replay.json\n",
            encoding="utf-8",
        )
        rollback_body = rollback_root / "rollback.html"
        rollback_sidecar = rollback_root / "rollback.html.replay.json"
        rollback_body.write_text("body", encoding="utf-8")
        rollback_sidecar.write_text("{}", encoding="utf-8")
        rollback_plan = plan_migration(rollback_root, batch="rollback")
        original_replace = os.replace
        publish_calls = 0

        def fail_second_publish(source, destination):
            nonlocal publish_calls
            if ".xunji-migrate-" in Path(source).name:
                publish_calls += 1
                if publish_calls == 2:
                    raise OSError("injected publish failure")
            return original_replace(source, destination)

        os.replace = fail_second_publish
        try:
            rollback_result = apply_migration(rollback_root, rollback_plan)
        finally:
            os.replace = original_replace
        rollback_entries = rollback_result["entries"]
        checks.append(("publish failure rolls back the whole body-sidecar group",
                       rollback_body.is_file() and rollback_sidecar.is_file()
                       and not (rollback_run / "evidence" / "rollback.html").exists()
                       and not (rollback_run / "evidence" / "rollback.html.replay.json").exists()
                       and not list(rollback_root.rglob("*.xunji-migrate-*.tmp"))
                       and all(entry["apply_state"] == "failed"
                               for entry in rollback_entries)))

        duplicate_root = root / "duplicate-case"
        duplicate_run = duplicate_root / "runs" / "demo_20260101"
        duplicate_run.mkdir(parents=True)
        (duplicate_run / "evidence.md").write_text(
            "- evidence/duplicate.html\n", encoding="utf-8",
        )
        duplicate_source = duplicate_root / "duplicate.html"
        duplicate_source.write_text("body", encoding="utf-8")
        duplicate_plan = plan_migration(duplicate_root, batch="duplicate")
        original_unlink = Path.unlink

        def fail_source_unlink(path, *args, **kwargs):
            if path == duplicate_source:
                raise PermissionError("injected source unlink failure")
            return original_unlink(path, *args, **kwargs)

        Path.unlink = fail_source_unlink
        try:
            duplicate_result = apply_migration(duplicate_root, duplicate_plan)
        finally:
            Path.unlink = original_unlink
        duplicate_entry = duplicate_result["entries"][0]
        checks.append(("source unlink failure keeps a verified duplicate, not data loss",
                       duplicate_source.is_file()
                       and (duplicate_run / "evidence" / "duplicate.html").is_file()
                       and duplicate_entry["applied"] is True
                       and duplicate_entry["source_removed"] is False
                       and duplicate_entry["apply_state"] == "published_with_source_copy"))

        symlink_root = root / "destination-symlink-case"
        symlink_run = symlink_root / "runs" / "demo_20260101"
        symlink_run.mkdir(parents=True)
        (symlink_run / "evidence.md").write_text(
            "- evidence/symlink.html\n", encoding="utf-8",
        )
        symlink_source = symlink_root / "symlink.html"
        symlink_source.write_text("body", encoding="utf-8")
        symlink_plan = plan_migration(symlink_root, batch="symlink")
        outside = symlink_root / "outside"
        outside.mkdir()
        (symlink_run / "evidence").symlink_to(outside, target_is_directory=True)
        symlink_result = apply_migration(symlink_root, symlink_plan)
        checks.append(("apply rejects a destination parent swapped to symlink after plan",
                       symlink_source.is_file() and not list(outside.iterdir())
                       and symlink_result["entries"][0]["apply_state"] == "skipped"
                       and any("destination path contains symlink" in warning
                               for warning in symlink_result["warnings"])))
    finally:
        shutil.rmtree(root, ignore_errors=True)
    bad = [name for name, ok in checks if not ok]
    for name, ok in checks:
        print(("ok   " if ok else "FAIL ") + name)
    print("output migration selftest " + ("passed" if not bad else f"FAILED ({len(bad)})"))
    return 0 if not bad else 1


def main() -> int:
    parser = argparse.ArgumentParser(description="Plan or apply loose artifact migration.")
    parser.add_argument("--batch", default=None,
                        help="stable local batch id (default UTC timestamp)")
    parser.add_argument("--apply", action="store_true",
                        help="move planned files and write the migration manifest")
    parser.add_argument("--verbose", action="store_true",
                        help="print per-file paths and hashes")
    parser.add_argument("--selftest", action="store_true")
    args = parser.parse_args()
    if args.selftest:
        return _selftest()
    batch = args.batch or time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())
    try:
        plan = plan_migration(ROOT, batch=batch)
    except ValueError as exc:
        parser.error(str(exc))
    result = apply_migration(ROOT, plan) if args.apply else plan
    print(json.dumps(result if args.verbose else _summary(result), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
