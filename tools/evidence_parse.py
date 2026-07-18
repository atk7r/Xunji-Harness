#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""evidence_parse.py — 唯一权威的 evidence.md 结构化解析器(从 check_run 抽出)。

把 `evidence.md` 折成结构化记录(id/head/certainties/confirmed/artifacts/supports/…),
是收口门(check_run)、自评(bench)等的【单一解析源】—— 不要再各起一套 `##`-split + regex
(脆弱; 旧版"任一引用解析得到就放行"曾让删掉的产物静默漏过 = E-012 洞)。

放在独立模块, 让需要解析的工具直接 `from evidence_parse import parse_evidence` 引用,
而不必去 import 整个收口门(check_run)。解析逻辑是自包含的, 只依赖标准库。
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import stat
from pathlib import Path


_ART_TOKEN = re.compile(
    r"(?:evidence/[\w./-]+|render[_-][\w./-]+|[\w][\w./-]*\.(?:html|json|js|css|xml|png|jpe?g|gif|txt|log|bin|diff|patch|md))",
    re.I)


def _artifact_tokens(text: str) -> list[str]:
    """Extract concrete artifact tokens from an Artifacts field.

    The ledger sometimes uses shorthand such as `(+.replay.json)` or
    `evidence/foo_*.html` to describe adjacent replay files or large families.
    Those are useful prose, but they are not auditable file references. Keep the
    gate strict for concrete tokens while ignoring shorthand that would otherwise
    become noisy dead references.
    """
    out: list[str] = []
    for m in _ART_TOKEN.finditer(text):
        tok = m.group(0).strip().strip("`\"'").rstrip(").,;:，。）")
        prev = text[max(0, m.start() - 2):m.start()]
        next_ch = text[m.end():m.end() + 1]
        next_two = text[m.end():m.end() + 2]
        if prev == "+.":
            continue
        if tok.lower() == "replay.json" and prev.endswith("."):
            continue
        if next_two == "*.":
            continue
        if tok and tok not in out:
            out.append(tok)
    return out


def _manifest_error(relative: str, reason: str) -> dict:
    return {
        "path": relative,
        "exists": False,
        "valid": False,
        "kind": "invalid",
        "error": reason,
    }


def _regular_file_manifest(path: Path, root: Path) -> dict:
    """Read one non-symlink regular file and bind the stable bytes observed."""
    before_lstat = os.lstat(path)
    if stat.S_ISLNK(before_lstat.st_mode) \
            or not stat.S_ISREG(before_lstat.st_mode):
        raise OSError("not_regular")
    resolved = path.resolve(strict=True)
    if resolved != root and root not in resolved.parents:
        raise OSError("escape")
    flags = os.O_RDONLY
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    fd = os.open(path, flags)
    try:
        opened = os.fstat(fd)
        if not stat.S_ISREG(opened.st_mode) \
                or (opened.st_dev, opened.st_ino) \
                != (before_lstat.st_dev, before_lstat.st_ino):
            raise OSError("identity_changed")
        digest = hashlib.sha1()
        total = 0
        while True:
            chunk = os.read(fd, 1024 * 1024)
            if not chunk:
                break
            digest.update(chunk)
            total += len(chunk)
        after = os.fstat(fd)
        if (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns,
                after.st_ctime_ns) != (
                opened.st_dev, opened.st_ino, opened.st_size,
                opened.st_mtime_ns, opened.st_ctime_ns) or total != after.st_size:
            raise OSError("content_changed")
    finally:
        os.close(fd)
    return {
        "path": path.relative_to(root).as_posix(),
        "size": total,
        "sha1": digest.hexdigest(),
    }


def content_path_manifest(run_dir: Path, relative: str) -> dict:
    """Return a symlink-free content manifest for one run-relative file/dir.

    Missing paths are valid, explicit state. Existing directories bind every
    regular file by relative path, size, and digest; symlinks, escapes, and
    special files fail closed instead of becoming an un-hashed directory shell.
    """
    try:
        root = Path(run_dir).resolve(strict=True)
    except Exception:
        return _manifest_error(str(relative), "run_unavailable")
    rel = Path(str(relative))
    normalized = rel.as_posix()
    if rel.is_absolute() or not normalized or normalized == "." \
            or any(part in {"", ".", ".."} for part in rel.parts):
        return _manifest_error(normalized, "relative_path_invalid")
    path = root
    try:
        for index, part in enumerate(rel.parts):
            path = path / part
            try:
                metadata = os.lstat(path)
            except FileNotFoundError:
                return {
                    "path": normalized,
                    "exists": False,
                    "valid": True,
                    "kind": "missing",
                }
            if stat.S_ISLNK(metadata.st_mode):
                return _manifest_error(normalized, "symlink_forbidden")
            if index < len(rel.parts) - 1 and not stat.S_ISDIR(metadata.st_mode):
                return _manifest_error(normalized, "ancestor_not_directory")
        resolved = path.resolve(strict=True)
        if resolved != root and root not in resolved.parents:
            return _manifest_error(normalized, "path_escape")
        top = os.lstat(path)
        if stat.S_ISREG(top.st_mode):
            item = _regular_file_manifest(path, root)
            return {
                "path": normalized,
                "exists": item["size"] > 0,
                "valid": True,
                "kind": "file" if item["size"] > 0 else "empty_file",
                "size": item["size"],
                "sha1": item["sha1"],
            }
        if not stat.S_ISDIR(top.st_mode):
            return _manifest_error(normalized, "special_file_forbidden")
        files: list[dict] = []

        def visit(directory: Path) -> None:
            with os.scandir(directory) as entries:
                ordered = sorted(entries, key=lambda item: item.name)
            observed_entries: list[tuple[str, int, int, int, int, int, int]] = []
            for entry in ordered:
                child = Path(entry.path)
                metadata = entry.stat(follow_symlinks=False)
                observed_entries.append((
                    entry.name, metadata.st_dev, metadata.st_ino,
                    stat.S_IFMT(metadata.st_mode),
                    metadata.st_size, metadata.st_mtime_ns,
                    metadata.st_ctime_ns,
                ))
                if stat.S_ISLNK(metadata.st_mode):
                    raise OSError("nested_symlink")
                if stat.S_ISDIR(metadata.st_mode):
                    child_resolved = child.resolve(strict=True)
                    if root not in child_resolved.parents:
                        raise OSError("nested_escape")
                    visit(child)
                elif stat.S_ISREG(metadata.st_mode):
                    files.append(_regular_file_manifest(child, root))
                else:
                    raise OSError("nested_special_file")
            with os.scandir(directory) as current_entries:
                current_snapshot = []
                for entry in current_entries:
                    metadata = entry.stat(follow_symlinks=False)
                    current_snapshot.append((
                        entry.name, metadata.st_dev, metadata.st_ino,
                        stat.S_IFMT(metadata.st_mode),
                        metadata.st_size, metadata.st_mtime_ns,
                        metadata.st_ctime_ns,
                    ))
                current_snapshot.sort()
            if observed_entries != current_snapshot:
                raise OSError("directory_membership_changed")

        visit(path)
        files.sort(key=lambda item: item["path"])
        total_size = sum(int(item["size"]) for item in files)
        directory_sha1 = hashlib.sha1(json.dumps(
            files, ensure_ascii=False, sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")).hexdigest()
        return {
            "path": normalized,
            "exists": any(int(item["size"]) > 0 for item in files),
            "valid": True,
            "kind": "directory",
            "size": total_size,
            "sha1": directory_sha1,
            "files": files,
        }
    except (OSError, RuntimeError, ValueError):
        return _manifest_error(normalized, "content_manifest_unstable")


def _evidence_artifact_manifest(run_dir: Path, token: str) -> dict:
    normalized = token.strip().strip("`\"'").rstrip(").,;:，。）")
    candidates = [normalized] if normalized.startswith("evidence/") else [
        normalized, f"evidence/{normalized}",
    ]
    invalid: list[dict] = []
    for relative in candidates:
        item = content_path_manifest(run_dir, relative)
        if item.get("valid") and item.get("exists"):
            return {"token": token, **item}
        if not item.get("valid"):
            invalid.append(item)
    if invalid:
        return {"token": token, **invalid[0]}
    return {"token": token, "exists": False, "valid": True, "kind": "missing"}


def evidence_artifact_manifest(run_dir: Path, token: str) -> dict:
    """Public canonical artifact view shared by review and closure consumers."""
    return _evidence_artifact_manifest(run_dir, token)


def _resolve_artifact(tok: str, run_dir: Path) -> Path | None:
    """Resolve only a safe, non-empty, content-bound artifact."""
    item = _evidence_artifact_manifest(run_dir, tok)
    if not item.get("valid") or not item.get("exists"):
        return None
    try:
        return Path(run_dir).resolve(strict=True) / str(item["path"])
    except Exception:
        return None


# Artifacts are cited in an explicit `Artifacts:` field (one or more lines until the
# next `- Field:` bullet / blank / next entry). Scoping citation-checks to this field
# (not the whole block) keeps prose filename mentions (e.g. "jquery-3.6.0.min.js",
# "ais.webform.js") from being mis-read as dead evidence citations.
_ARTIFACT_FIELD_RE = re.compile(
    r"(?:[Ss]aved\s+)?[Aa]rtifacts?(?:\s*\([^)\n]*\))?\s*[:：]\s*(.+?)(?=\n\s*[-*]\s*[A-Z][\w /()-]*[:：]|\n\s*\n|\n##|\Z)",
    re.S)
# Certainty 字段的【值区域】: 从 `Certainty…:` 到下一个 `- Field:` / 空行 / 块尾。
# 用来把 certainty 取值限定在【字段值内】(而非旧逻辑"从关键词扫到块尾"), 再配合 _PAREN_RE
# 剥掉括号说明 —— 否则降级时括号里写的解释数字(如"原 0.8 / 升回 1.0")会被误当成 certainty
# 值, 使降级无效(2026-06-17 实测)。剥括号后仍含【同字段内】的 split-certainty 多值。
_CERT_FIELD_RE = re.compile(
    r"Certainty[^\n:：]*[:：](.+?)(?=\n\s*[-*]\s+\w[\w /()（）-]*[:：]|\n\s*\n|\n##|\Z)",
    re.S | re.I)
_PAREN_RE = re.compile(r"[\(（][^\)）]*[\)）]")
_CERT_NUMBER_RE = re.compile(r"\b[01]\.\d+\b")
# inline field labels — used to bound a field's value when several share one line
# (e.g. "- Supports: H-002. Refutes: —. Next: prove X (E-005)." — the (E-005) belongs
# to Next:, not Refutes:; cutting at the next label stops that misattribution).
_INLINE_FIELDS = (r"Supports|Refutes|Next|Certainty|Maturity|Severity|Cleanup|Note|Replicated|"
                  r"Control|Alternative|Source|Action|Result|Caused by us")
_INLINE_CUT_RE = re.compile(r"\b(?:" + _INLINE_FIELDS + r")\s*[:：]")
_MATURITY_FIELD_RE = re.compile(
    r"(?im)^\s*[-*]?\s*Maturity\s*[:：]\s*([A-Za-z_-]+|现象|候选|发现|确认)")
_ROLE_FIELD_RE = re.compile(
    r"(?im)^\s*[-*]?\s*Role\s*[:：]\s*(coverage[a-z_-]*)")
_FIELD_RE = re.compile(
    r"(?im)^\s*[-*]?\s*(Source|Trust)\s*[:：]\s*(.+?)(?=\n\s*[-*]\s*[A-Z][\w /()-]*[:：]|\n\s*\n|\n##|\Z)",
    re.S)

def _strip_certainty_notes(text: str) -> str:
    """Drop explanatory parentheticals from a Certainty field while preserving
    a value that is itself parenthesized, e.g. `Certainty: (0.8)`."""
    def repl(m: re.Match) -> str:
        inner = m.group(0)[1:-1].strip()
        return inner if re.fullmatch(r"[01]\.\d+", inner) else ""
    return _PAREN_RE.sub(repl, text)


def _field_ids(block: str, name: str, idpat: str) -> list[str]:
    """IDs (E-/H-/F-) in a `Name:` field's value, bounded to the next inline field
    label so a co-line `Next:`/prose mention is not swept in."""
    out: list[str] = []
    for m in re.finditer(name + r"\s*[:：]\s*(.*)", block):
        seg = m.group(1)
        cut = _INLINE_CUT_RE.search(seg)
        if cut:
            seg = seg[:cut.start()]
        out += re.findall(idpat, seg)
    return out


def _maturity(block: str, confirmed: bool) -> tuple[str, bool, str | None]:
    m = _MATURITY_FIELD_RE.search(block)
    if not m:
        return ("finding" if confirmed else "candidate"), False, None
    val = m.group(1).strip().lower().replace("_", "-")
    if val in {"phenomenon", "observed", "observation", "static", "source", "client", "recon", "现象"}:
        return "phenomenon", True, None
    if val in {"candidate", "proposed", "unconfirmed", "候选"}:
        return "candidate", True, None
    if val in {"finding", "confirmed", "confirmed-finding", "发现", "确认"}:
        return "finding", True, None
    return "candidate", True, val


def _provenance(block: str) -> dict:
    fields: dict[str, str] = {}
    for m in _FIELD_RE.finditer(block):
        fields[m.group(1).lower()] = m.group(2).strip().splitlines()[0].strip()
    src = fields.get("source", "evidence-ledger")
    trust = fields.get("trust")
    src_l = src.lower()
    if trust is None:
        target_sources = {
            "target", "target-content", "target-network-observation", "target-session-artifact",
            "target-error", "target-page", "target-js", "target-pdf", "target-readme",
        }
        trust = "untrusted" if src_l in target_sources or src_l.startswith("target-") else "operator-reviewed"
    return {"source": src, "trust": trust}


def parse_evidence(run_dir: Path) -> list[dict]:
    """Single canonical parser: evidence.md -> structured records. Replaces the
    per-check ad-hoc `##`-split + regex (fragile, and the artifact gate used to pass
    a block if ANY one citation resolved, so a deleted file was silent — E-012).
    Artifact presence is re-read on every call so directory/file changes cannot
    remain hidden behind an evidence.md-only mtime cache."""
    ev = run_dir / "evidence.md"
    if not ev.exists():
        return []
    text = ev.read_text(encoding="utf-8", errors="replace")
    records: list[dict] = []
    for b in re.split(r"(?=^##\s)", text, flags=re.MULTILINE):
        if not b.lstrip().startswith("##"):
            continue  # skip the file preamble (the `# Evidence Ledger` header block)
        head = b.splitlines()[0].strip()
        idm = re.search(r"\bE-\d+[a-z]*\b", head)
        eid = idm.group(0) if idm else head.lstrip("# ").strip()[:48]
        # certainty: 取 `Certainty:` 字段的【值区域】并【剥掉括号说明】, 而非旧逻辑"从关键词
        # 扫到块尾"—— 后者会把降级时括号里写的解释数字(如"原 0.8 / 升回 1.0")误当成 certainty
        # 值, 使降级无效(2026-06-17 实测踩到)。剥括号后仍含同字段内的 split-certainty 多值。
        cm = _CERT_FIELD_RE.search(b)
        region = _strip_certainty_notes(cm.group(1)) if cm else ""
        certs = [float(x) for x in _CERT_NUMBER_RE.findall(region)]
        # also read explicit "Certainty: 0.NN" values so an OFF-DOCTRINE certainty
        # (0.9/0.85/0.7…, off the {1.0,0.8,0.5,0.3} grid) cannot silently slip the
        # hard artifact gate by failing to match the canonical-literal regex above.
        # off-grid 兜底: 抓 `Certainty:` 后紧跟的值(含 0.9 这类非网格)。允许一层可选括号
        # `[\(（]?`, 这样值本身被写进括号(`Certainty: (0.8)`)也能抓到 —— 否则 _PAREN_RE 会把
        # 它连括号一起剥掉致漏判(复审 S1)。降级写法 `0.5 (原 0.8…)` 仍只抓紧跟的 0.5(不进括号)。
        certs += [float(x) for x in re.findall(r"certainty\s*[:：]\s*\**\s*[\(（]?\s*(\d\.\d+)", b, re.I)]
        # Stable de-duplication: split fields and the explicit fallback can both
        # see the first value. Keep ordering so diagnostics remain predictable.
        seen_certs = set()
        certs = [c for c in certs if not (c in seen_certs or seen_certs.add(c))]
        # artifacts: scoped to the explicit Artifacts: field (fallback: whole block,
        # for legacy entries with no such field).
        fm = _ARTIFACT_FIELD_RE.search(b)
        scope_txt, scoped = (fm.group(1), True) if fm else (b, False)
        arts: list[str] = []
        arts = _artifact_tokens(scope_txt)
        artifact_manifests = [
            _evidence_artifact_manifest(run_dir, item) for item in arts]
        present = [
            item for item, manifest in zip(arts, artifact_manifests)
            if manifest.get("valid") and manifest.get("exists")
        ]
        missing = [
            item for item, manifest in zip(arts, artifact_manifests)
            if not manifest.get("valid") or not manifest.get("exists")
        ]
        refutes = _field_ids(b, "Refutes", r"E-\d+[a-z]*")
        supports = _field_ids(b, "Supports", r"[EHF]-\d+")
        confirmed = any(c >= 0.8 for c in certs)
        maturity, maturity_explicit, maturity_raw = _maturity(b, confirmed)
        role_m = _ROLE_FIELD_RE.search(b)
        role = role_m.group(1) if role_m else ""
        prov = _provenance(b)
        records.append({
            "id": eid, "head": head,
            "certainties": certs, "confirmed": confirmed,
            "maturity": maturity, "maturity_explicit": maturity_explicit,
            "maturity_raw": maturity_raw, "maturity_unknown": maturity_raw is not None,
            "role": role,
            "source": prov["source"], "trust": prov["trust"], "provenance": prov,
            "has_control": bool(re.search(r"\b(Replicated|Control)\s*[:：]", b)),
            # 该条目自己有 `- Replay:` 字段 = 对 replay 分歧做过 re-adjudication(check_run 断-3 绑定用,
            # 逐条目判而非全局计数, 避免别处/模板的 Replay 误清这条)。
            "has_replay_ack": bool(re.search(r"(?im)^\s*[-*]\s*Replay\s*[:：]", b)),
            "artifacts": arts, "artifacts_scoped": scoped,
            "artifact_manifests": artifact_manifests,
            "artifacts_present": present, "artifacts_missing": missing,
            "supports": sorted(set(supports)), "refutes": sorted(set(refutes)),
            # refutes_any: block 是否含 Refutes 字段(不论 refute 的是 E/H/F)。漏报一致性门用它
            # 区分"排除性/negative 结论"(Refutes hypothesis, 如'未发现漏洞')—— 这类不该强制进
            # report 确认发现; r["refutes"] 只抓 E-\d+ 会漏掉 Refutes H-xxx 的 negative 结论(FP)。
            "refutes_any": bool(re.search(r"(?im)^\s*[-*]?\s*Refutes\s*[:：]\s*\S", b)),
            "superseded": bool(re.search(r"superseded|降级|撤回|改判", b, re.I)),
        })
    return records


def write_evidence_index(run_dir: Path, records: list[dict]) -> None:
    """Derived sidecar (like graph.json / coverage.json): structured, queryable view
    of the evidence ledger so tooling/operator need not regex the markdown."""
    if not records:
        return
    confirmed = [r["id"] for r in records if r["confirmed"]]
    confirmed_findings = [r["id"] for r in records if r["confirmed"] and r.get("maturity") == "finding"]
    out = {"total": len(records), "confirmed": confirmed,
           "confirmed_findings": confirmed_findings,
           "dangling_citations": {r["id"]: r["artifacts_missing"]
                                  for r in records if r["artifacts_missing"]},
           "entries": records}
    try:
        (run_dir / "evidence.json").write_text(
            json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception:
        pass


def _evidence_artifact_hash(run_dir: Path, token: str) -> dict:
    return _evidence_artifact_manifest(run_dir, token)


def canonical_evidence_index(run_dir: Path) -> dict:
    """Build the one content-addressed fact view used by review and closure."""
    entries = []
    for record in parse_evidence(run_dir):
        manifests = record.get("artifact_manifests")
        if not isinstance(manifests, list) \
                or len(manifests) != len(record.get("artifacts", [])):
            manifests = [
                _evidence_artifact_hash(run_dir, item)
                for item in record.get("artifacts", [])
            ]
        entries.append({
            "id": record.get("id"),
            "head": record.get("head"),
            "maturity": record.get("maturity"),
            "certainties": record.get("certainties", []),
            "confirmed": record.get("confirmed", False),
            "has_control": record.get("has_control", False),
            "supports": record.get("supports", []),
            "refutes": record.get("refutes", []),
            "refutes_any": record.get("refutes_any", False),
            "artifacts": sorted(
                (dict(item) for item in manifests if isinstance(item, dict)),
                key=lambda item: (
                    str(item.get("path", "")), str(item.get("token", ""))),
            ),
            "artifacts_missing": record.get("artifacts_missing", []),
        })
    entries.sort(key=lambda item: str(item.get("id", "")))
    return {
        "schema": "xunji.evidence_index.v1",
        "evidence_manifest": content_path_manifest(run_dir, "evidence.md"),
        "entries": entries,
    }


def evidence_index_hash(payload: dict) -> str:
    """Hash a canonical index while ignoring reviewer-only presentation bytes."""
    value = json.loads(json.dumps(payload, ensure_ascii=False))
    value.pop("sha1", None)
    for entry in value.get("entries", []):
        for artifact in entry.get("artifacts", []):
            for key in ("excerpt", "excerpt_truncated_chars", "diff_summary"):
                artifact.pop(key, None)
    return hashlib.sha1(json.dumps(
        value, ensure_ascii=False, sort_keys=True).encode("utf-8")).hexdigest()


def current_evidence_index_hash(run_dir: Path) -> str:
    """Hash the canonical evidence projection used by review and closure gates."""
    return evidence_index_hash(canonical_evidence_index(run_dir))
