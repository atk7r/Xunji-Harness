#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""setup_run.py — 一键初始化一个授权目标的 run 工作台。

机械化 WORKFLOW.md「Ingest Existing Intelligence First」+ Repository Discipline:
从 docs/templates/run/ 建齐 run 骨架 + evidence/ scripts/ 子目录, 给了 recon 就用
ingest_recon 折【全量】资产到 surface_recon.md, 并在 target.md 记录 recon 路径。

它专治 hamastar run 的根因: 当时手工誊录了 ~16 个资产进 surface.md(把 driver 的
选择偏见当成 run 的事实地面), 跳过了 ingest_recon/classify_hosts → 30+ 资产漏挖。
一键起手就杜绝"手工挑子集"的诱惑。

coverage.json 默认从 Guanlan recon 产物折成零重探 baseline, 满足 check_run 的资产
台账硬门但不主动发包。加 --classify 才在授权 OK 时跑 egress_recheck 增量探测。

它只【备好工作台】, 不选 front / 不做攻击判断 —— 派生不驱动, 绝非编排器。

  python tools/setup_run.py <slug> [recon.json] [--date YYYYMMDD] [--classify]
  python tools/setup_run.py --selftest
"""
from __future__ import annotations

import argparse
import datetime
import hashlib
import json
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path
from urllib.parse import urlsplit

try:
    sys.stdout.reconfigure(encoding="utf-8")       # type: ignore[attr-defined]
except Exception:
    pass

ROOT = Path(__file__).resolve().parents[1]
TPL = ROOT / "docs" / "templates" / "run"
REQUIRED = ["target.md", "surface.md", "frontier.md", "hypotheses.md", "evidence.md",
            "false_positive.md", "decisions.md", "review.md", "report.md",
            # 强制复盘: 收口硬门(check_run.check_retrospective)要求收口时填好两节真实内容。
            # 这里只铺模板占位(有 H1), 占位本身不算填 —— 收口前 driver 必须把两节写实。
            "retrospective.md"]

sys.path.insert(0, str(Path(__file__).resolve().parent))

import loop_journal  # noqa: E402
import setup_normalizer  # noqa: E402
import setup_source  # noqa: E402
import setup_transaction  # noqa: E402


def _today() -> str:
    return datetime.date.today().strftime("%Y%m%d")


def _phase_journal(run_dir: Path, event: str, phase: str, note: str) -> None:
    """Best-effort derived phase marker. Markdown/templates remain canonical."""
    try:
        loop_journal.append_event(run_dir, event, note=note, data={"phase": phase})
    except Exception as exc:
        print(f"[setup] phase journal skipped: {exc}", file=sys.stderr)


def scaffold(run_dir: Path) -> list[str]:
    """从模板建齐必需文件 + evidence/ scripts/ 子目录(含 .gitkeep)。不覆盖已存在目录。"""
    run_dir.mkdir(parents=True, exist_ok=False)   # exist_ok=False → 已存在则 FileExistsError
    made: list[str] = []
    for name in REQUIRED:
        src = TPL / name
        dst = run_dir / name
        if src.exists():
            shutil.copyfile(src, dst)
        else:   # 模板缺失也给个带 H1 的占位, 至少满足 check_run 的 '# X' marker
            dst.write_text(f"# {name[:-3].replace('_', ' ').title()}\n", encoding="utf-8")
        made.append(name)
    for sub in ("evidence", "scripts"):
        d = run_dir / sub
        d.mkdir(exist_ok=True)
        (d / ".gitkeep").write_text("", encoding="utf-8")
    state = run_dir / "state"
    state.mkdir(exist_ok=True)
    profile_src = TPL / "operator_profile.json"
    if profile_src.exists():
        shutil.copyfile(profile_src, state / "operator_profile.json")
    return made


def record_recon(run_dir: Path, value: str) -> None:
    """在 target.md 的『Existing intel / recon report:』字段写入 value(recon 路径或 'none')。
    用 lambda 替换避免 Windows 路径里的反斜杠被 re.sub 当成组引用(\\1 之类)。"""
    t = run_dir / "target.md"
    txt = t.read_text(encoding="utf-8", errors="replace")
    new = re.sub(r"(- Existing intel / recon report:).*",
                 lambda m: f"{m.group(1)} {value}", txt, count=1)
    t.write_text(new, encoding="utf-8")


def record_target(run_dir: Path, value: str) -> None:
    """Fill target.md `Target:` from an explicit CLI target before no-recon coverage derivation."""
    t = run_dir / "target.md"
    txt = t.read_text(encoding="utf-8", errors="replace")
    new = re.sub(r"(- Target:).*", lambda m: f"{m.group(1)} {value}", txt, count=1)
    t.write_text(new, encoding="utf-8")


def record_setup_source(run_dir: Path, manifest: dict) -> None:
    """Link canonical target.md to the frozen source/validator receipts."""
    target = run_dir / "target.md"
    text = target.read_text(encoding="utf-8", errors="replace")
    marker = "## Setup Source"
    related = ", ".join(
        str(item.get("snapshot") or "")
        for item in manifest.get("related_sources", []) if isinstance(item, dict)
    ) or "none"
    block = (
        f"{marker}\n\n"
        f"- Schema: {manifest.get('schema', '')}\n"
        f"- Kind: {manifest.get('source', {}).get('kind', '')}\n"
        f"- Source SHA-256: {manifest.get('source_sha256', '')}\n"
        f"- Snapshot: {manifest.get('source', {}).get('snapshot', '')}\n"
        f"- Related snapshots: {related}\n"
        f"- Normalized candidate: {setup_source.NORMALIZED_REL.as_posix()}\n"
        f"- Validator receipt: {setup_source.VALIDATOR_REL.as_posix()}\n"
        "- Authority: target.md remains canonical; source claims are data until operator-bound.\n"
    )
    if marker in text:
        text = text.split(marker, 1)[0].rstrip() + "\n\n" + block
    else:
        text = text.rstrip() + "\n\n" + block
    target.write_text(text, encoding="utf-8")


def record_scope(run_dir: Path, recon_path: Path) -> str:
    """从 recon 的 ownership 派生默认 scope, 填进 target.md 的 Target/In-scope/Out-of-scope
    (现在这些字段 setup 留空 = scope 脊梁缺失, mokwon dogfood 实测的头号问题)。派生不驱动:
    写的是默认, driver 可改 target.md(scope.py parse_target_scope 是源)。"""
    import scope as _scope
    recon = json.loads(recon_path.read_text(encoding="utf-8"))
    sc = _scope.derive_scope(recon)
    in_line, out_line = _scope.render_scope_lines(sc)
    t = run_dir / "target.md"
    txt = t.read_text(encoding="utf-8", errors="replace")

    def setfield(s: str, name: str, val: str) -> str:           # lambda 替换避免反斜杠组引用 bug
        return re.sub(rf"(- {re.escape(name)}:).*", lambda m: f"{m.group(1)} {val}", s, count=1)

    if sc["target"]:
        txt = setfield(txt, "Target", sc["target"])
    if in_line:
        txt = setfield(txt, "In-scope assets", in_line)
    if out_line:
        txt = setfield(txt, "Out-of-scope assets", out_line)
    if sc["notes"]:
        prefix = ("⚠ scope 启发式(recon 无 ownership), 归属待裁: " if sc.get("heuristic")
                  else "scope 复核(secondary/第三方托管): ")
        note = prefix + "; ".join(f"{h}" for h, _ in sc["notes"][:6])
        txt = setfield(txt, "Notes", note)
    t.write_text(txt, encoding="utf-8")
    tag = " ⚠启发式(无 ownership, 务必复核 target.md In/Out-of-scope)" if sc.get("heuristic") else ""
    return f"scope 派生 → {len(sc['in'])} in-模式 / {len(sc['out'])} out / {len(sc['notes'])} 复核{tag}"


def ingest(recon_path: Path, run_dir: Path) -> str:
    """import ingest_recon.render 折全量资产到 surface_recon.md(纯函数, 无网络)。"""
    import ingest_recon
    recon = json.loads(recon_path.read_text(encoding="utf-8"))
    md = ingest_recon.render(recon, str(recon_path))
    (run_dir / "surface_recon.md").write_text(md, encoding="utf-8")
    n = len(recon.get("assets", [])) if isinstance(recon, dict) else 0
    return f"surface_recon.md ({n} assets)"


def adapt_coverage(recon_path: Path, run_dir: Path) -> str:
    """轴 B 适配器: Guanlan 产物 → coverage.json, 【零重探】。Guanlan 已做去重/通配折叠/存活/归属,
    框架不再 classify_hosts 全量重探重建(= re-OSINT 冤枉时间)。取 recon 同目录 report.md 的存活分层。"""
    import ingest_recon
    recon = json.loads(recon_path.read_text(encoding="utf-8"))
    rep = recon_path.parent / "report.md"
    report_md = rep.read_text(encoding="utf-8", errors="replace") if rep.exists() else None
    cov = ingest_recon.build_coverage(recon, report_md)
    out = run_dir / "classify"
    out.mkdir(parents=True, exist_ok=True)
    (out / "coverage.json").write_text(json.dumps(cov, ensure_ascii=False, indent=2), encoding="utf-8")
    src = "含 report.md 存活分层" if report_md else "无 report.md → 可达性留 unknown(渗透时定)"
    return f"coverage.json ({cov['total']} 资产 / {cov['reachable']} 已确认可达, {src})"


def _parse_frontmatter_signatures(text: str) -> list[str]:
    """纯 stdlib 从 Markdown frontmatter 中提取 signatures 列表。
    不使用 pyyaml(retrospective B1: 依赖未安装导致 knowledge_match 静默失败)。"""
    m = re.match(r"^---[ \t]*\r?\n(.*?)\r?\n---", text, re.S)
    if not m:
        return []
    fm_text = m.group(1)
    # 提取 signatures: [...] 行 — 先试单行格式(更常见), 再试多行缩进列表
    sig_line = re.search(r"(?m)^signatures\s*:\s*\[(.*?)\]", fm_text)
    if sig_line:
        return [s.strip().strip("'\"") for s in sig_line.group(1).split(",") if s.strip()]
    sig_block = re.search(r"(?m)^signatures\s*:\s*\r?\n((?:\s+-\s+[^\n]+\r?\n?)+)", fm_text)
    if sig_block:
        sigs = []
        for item in re.finditer(r"-\s+(.+?)(?:\r?\n|$)", sig_block.group(1)):
            val = item.group(1).strip().strip("'\"").rstrip(",")
            if val:
                sigs.append(val)
        return sigs
    return []


def _sig_matches(signature: str, haystack: str) -> bool:
    """检查签名是否在 haystack 中匹配。支持 glob 前缀:
    `*.suffix` → haystack 中以 .suffix 结尾; 否则 → 子串匹配。"""
    if not signature:
        return False
    if signature.startswith("*"):
        suffix = signature[1:]
        return haystack.find(suffix) >= 0
    return signature in haystack


def knowledge_match(run_dir: Path) -> str:
    """从 surface_recon.md 或 coverage.json 中提取产品指纹, 匹配 knowledge/*.md 签名,
    生成 knowledge_hits.md — 让 driver 在 Reason pass 时自然读到匹配的 knowledge 条目,
    避免跳过本地知识库直接用 WebSearch(retrospective #3/#14/#15)。
    纯 stdlib, 无外部依赖(retrospective B1: pyyaml 未安装导致静默失败)。"""
    knowledge_dir = ROOT / "knowledge"
    if not knowledge_dir.is_dir():
        return "knowledge/ 目录不存在 — 跳过签名匹配"

    # 1. 加载所有 knowledge/*.md 的 frontmatter (signatures + id)
    entries: list[dict] = []
    for kf in sorted(knowledge_dir.glob("*.md")):
        if kf.name.startswith("_") or kf.name == "README.md":
            continue
        text = kf.read_text(encoding="utf-8", errors="replace")
        fm: dict = {}
        # 提取所有 frontmatter 键值对(纯 stdlib regex, 不依赖 pyyaml)
        m = re.match(r"^---[ \t]*\r?\n(.*?)\r?\n---", text, re.S)
        if m:
            fm_text = m.group(1)
            for key in ("id", "product", "vendor", "category", "maturity"):
                kv = re.search(rf"(?m)^{key}\s*:\s*(.+?)\s*$", fm_text)
                if kv:
                    fm[key] = kv.group(1).strip().strip("'\"")
        sigs = _parse_frontmatter_signatures(text)
        if sigs:
            entries.append({
                "file": f"knowledge/{kf.name}",
                "id": fm.get("id", kf.stem),
                "product": fm.get("product", kf.stem),
                "vendor": fm.get("vendor", ""),
                "category": fm.get("category", ""),
                "maturity": fm.get("maturity", "unknown"),
                "signatures": sigs,
            })

    if not entries:
        return "knowledge/ 无可匹配条目 — 跳过签名匹配"

    # 2. 从 surface_recon.md 和 coverage.json 提取文本
    haystack = ""
    for fname in ("surface_recon.md", "surface.md"):
        p = run_dir / fname
        if p.exists():
            haystack += "\n" + p.read_text(encoding="utf-8", errors="replace")
    cov_path = run_dir / "classify" / "coverage.json"
    if cov_path.exists():
        try:
            cov = json.loads(cov_path.read_text(encoding="utf-8", errors="replace"))
            for a in cov.get("assets", []):
                haystack += "\n" + str(a.get("host", "")) + " " + str(a.get("title", ""))
                haystack += " " + str(a.get("stack", "")) + " " + " ".join(str(a.get("flags", [])))
        except Exception:
            pass

    # 3. 匹配签名(支持 glob 前缀)
    matches: list[dict] = []
    seen: set[str] = set()
    for e in entries:
        for sig in e["signatures"]:
            if _sig_matches(sig, haystack):
                if e["id"] not in seen:
                    seen.add(e["id"])
                    matches.append(e)
                break

    # 4. 生成 knowledge_hits.md
    out = run_dir / "knowledge_hits.md"
    if matches:
        lines = [
            "# Knowledge Hits (签名自动匹配)",
            "",
            f"setup_run 从 {len(entries)} 个 knowledge 条目中匹配到 {len(matches)} 个签名命中:",
            "",
        ]
        for m_item in matches:
            lines.append(f"## {m_item['id']}")
            lines.append(f"- Product: {m_item['product']}")
            if m_item['vendor']:
                lines.append(f"- Vendor: {m_item['vendor']}")
            lines.append(f"- Category: {m_item['category']} | Maturity: {m_item['maturity']}")
            matched = [s for s in m_item['signatures'] if _sig_matches(s, haystack)]
            lines.append(f"- Signatures matched: {', '.join(matched)}")
            lines.append(f"- File: `{m_item['file']}` ← Read this before WebSearch!")
            lines.append("")
        out.write_text("\n".join(lines), encoding="utf-8")
        return f"knowledge_hits.md ({len(matches)} hits: {', '.join(m['id'] for m in matches)})"
    else:
        out.write_text("# Knowledge Hits\n\n无签名命中 — 未识别到已知产品指纹。\n", encoding="utf-8")
        return "knowledge_hits.md (无命中)"


def _merge_egress_recheck(run_dir):
    """P0: 合并 Guanlan baseline coverage + classify_hosts egress recheck overlay."""
    import json as _json
    cov_path = run_dir / "classify" / "coverage.json"
    egress_path = run_dir / "classify" / "egress_coverage.json"
    if not cov_path.exists() or not egress_path.exists():
        return
    cov = _json.loads(cov_path.read_text(encoding="utf-8"))
    egress = _json.loads(egress_path.read_text(encoding="utf-8"))
    egress_map = {a["host"]: a for a in egress.get("assets", [])}
    for a in cov["assets"]:
        h = a["host"]
        if h in egress_map:
            a["current_egress_reachability"] = egress_map[h].get("reachable")
            if a["current_egress_reachability"] is True:
                a["reachable"] = True
    cov["source"] = "guanlan-baseline + egress-recheck-overlay"
    cov_path.write_text(_json.dumps(cov, ensure_ascii=False, indent=2), encoding="utf-8")


def _coverage_ready(run_dir: Path) -> bool:
    cov_path = run_dir / "classify" / "coverage.json"
    try:
        cov = json.loads(cov_path.read_text(encoding="utf-8"))
    except Exception:
        return False
    assets = cov.get("assets")
    return isinstance(assets, list) and any(isinstance(a, dict) and a.get("host") for a in assets)


def _parse_target_asset(raw: str) -> tuple[str, str, int] | None:
    """Parse target.md Target into (host, scheme, port) without accepting prose."""
    val = raw.strip()
    if not val or val.startswith("(") or re.search(r"\s", val):
        return None
    m = re.match(r"(?:(https?)://)?([^/\s#]+)(?:[/?#].*)?$", val)
    if not m:
        return None
    scheme = m.group(1) or "https"
    host = m.group(2)
    port = 443 if scheme == "https" else 80
    pm = re.match(r"^(.+):(\d+)$", host)
    if pm:
        host = pm.group(1)
        port = int(pm.group(2))
    if not host or host.startswith("(") or not re.match(r"^[A-Za-z0-9_.:-]+$", host):
        return None
    if port < 1 or port > 65535:
        return None
    return host, scheme, port


def _derive_coverage_from_target(run_dir: Path) -> str:
    """无 Guanlan recon 时, 从 target.md 的 Target 字段提取 host, 生成最小骨架
    coverage.json。资产标记为 reachable: unknown, source: target-derived。"""
    target_md = run_dir / "target.md"
    host, scheme, port = None, "https", 443
    if target_md.exists():
        for line in target_md.read_text(encoding="utf-8", errors="replace").splitlines():
            m = re.match(r"- Target:\s*(.*)$", line)
            if m:
                parsed = _parse_target_asset(m.group(1))
                if parsed is None:
                    return "target.md Target 为空或格式不适合自动推导, 跳过 coverage 推导"
                host, scheme, port = parsed
                break
    if not host:
        return "target.md 无 Target 字段, 跳过 coverage 推导"
    cov = {
        "source": "target-derived",
        "generated": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "note": "骨架 coverage — 无 Guanlan recon, 从 target.md Target 字段推导。reachable 待渗透时判定。",
        "assets": [{
            "asset_id": "ASSET-" + hashlib.sha1(host.lower().encode("utf-8")).hexdigest()[:12].upper(),
            "host": host, "port": port, "scheme": scheme,
            "scope_status": "in", "reachable": "unknown", "examined": False,
            "verdict": None,
        }],
        "total": 1, "reachable": 0, "unreachable": 0, "unknown": 1,
    }
    out = run_dir / "classify"
    out.mkdir(parents=True, exist_ok=True)
    (out / "coverage.json").write_text(json.dumps(cov, ensure_ascii=False, indent=2), encoding="utf-8")
    return f"coverage.json (骨架: {host}, reachable 待判定)"


def _derive_coverage_from_manifest(run_dir: Path, manifest: dict) -> str:
    """Build a no-probe candidate ledger from a mechanically validated source.

    File-derived assets remain ``scope_status=review``.  Source prose cannot turn
    them into in-scope authority; target.md and the next operator turn remain the
    canonical review boundary.
    """
    rows: list[dict] = []
    for asset in manifest.get("assets", []):
        if not isinstance(asset, dict) or not asset.get("host"):
            continue
        host = str(asset["host"])
        url = str(asset.get("url") or "")
        scheme = ""
        port = None
        if url:
            parsed = setup_source.parse_target_url(url)
            scheme = parsed["scheme"]
            port = parsed["port"]
        rows.append({
            "asset_id": "ASSET-" + hashlib.sha1(host.lower().encode("utf-8")).hexdigest()[:12].upper(),
            "host": host,
            "scheme": scheme,
            "port": port,
            "scope_status": "review",
            "reachable": "unknown",
            "examined": False,
            "stack": "",
            "flags": [],
            "source": "setup-source-candidate",
            "source_ref": str(asset.get("source_ref") or ""),
            "verdict": None,
        })
    coverage = {
        "source_total": len(rows),
        "excluded": 0,
        "excluded_assets": [],
        "total": len(rows),
        "examined": 0,
        "reachable": 0,
        "planned": len(rows),
        "partial": True,
        "assets": rows,
        "source": "setup-source-candidate(no re-probe; scope review required)",
    }
    out = run_dir / "classify"
    out.mkdir(parents=True, exist_ok=True)
    (out / "coverage.json").write_text(
        json.dumps(coverage, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return f"coverage.json ({len(rows)} candidate assets, zero re-probe, scope=review)"


def _render_normalized_surface(manifest: dict) -> str:
    lines = [
        "# Surface — normalized setup candidate",
        "",
        "> Values below passed source_ref validation but remain source-derived data.",
        "> Scope, authorization, reachability, findings, certainty, and severity are not promoted here.",
        "",
        "| host | url | source_ref |",
        "|---|---|---|",
    ]
    for asset in manifest.get("assets", []):
        if isinstance(asset, dict):
            lines.append(
                f"| {asset.get('host', '')} | {asset.get('url', '')} | `{asset.get('source_ref', '')}` |"
            )
    unresolved = manifest.get("unresolved") if isinstance(manifest.get("unresolved"), list) else []
    if unresolved:
        lines.extend(("", "## Unresolved source candidates", ""))
        for item in unresolved:
            if isinstance(item, dict):
                lines.append(
                    f"- {item.get('field', '')}: {item.get('reason', '')} (`{item.get('source_ref', '')}`)"
                )
    return "\n".join(lines) + "\n"


def _validated_date(raw: str | None) -> str:
    value = raw or _today()
    if not re.fullmatch(r"[0-9]{8}", value):
        raise setup_transaction.SetupTransactionError(
            "invalid_date", "date must use YYYYMMDD"
        )
    try:
        datetime.datetime.strptime(value, "%Y%m%d")
    except ValueError as exc:
        raise setup_transaction.SetupTransactionError(
            "invalid_date", f"invalid calendar date: {value}"
        ) from exc
    return value


def _validated_slug(raw: str) -> str:
    value = str(raw or "")
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]*", value):
        raise setup_transaction.SetupTransactionError(
            "invalid_slug",
            "slug must start with an alphanumeric and contain only A-Z, a-z, 0-9, _ or -",
        )
    return value


def _validated_target_url(raw: str) -> str:
    value = str(raw or "").strip()
    if not value or re.search(r"[\x00-\x20\x7f]", value):
        raise setup_transaction.SetupTransactionError(
            "invalid_target_url", "target URL is empty or contains control/whitespace"
        )
    try:
        parsed = urlsplit(value)
        _ = parsed.port
    except ValueError as exc:
        raise setup_transaction.SetupTransactionError(
            "invalid_target_url", f"target URL cannot be parsed: {exc}"
        ) from exc
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise setup_transaction.SetupTransactionError(
            "invalid_target_url", "target URL must be absolute http/https with a host"
        )
    if parsed.username is not None or parsed.password is not None:
        raise setup_transaction.SetupTransactionError(
            "invalid_target_url", "target URL must not embed userinfo credentials"
        )
    return value


def _valid_recon_assets(recon: dict) -> bool:
    assets = recon.get("assets")
    if not isinstance(assets, list) or not assets:
        return False
    for item in assets:
        if not isinstance(item, dict):
            return False
        candidate = next((
            str(item.get(key) or "").strip()
            for key in ("host", "asset", "name", "url")
            if str(item.get(key) or "").strip()
        ), "")
        if not candidate:
            return False
    return True


def resolve_setup_request(
    slug: str,
    *,
    recon: str | None,
    target: str | None,
    date: str | None,
    classify: bool,
) -> dict:
    """Resolve and validate all source material before a formal run exists."""
    safe_slug = _validated_slug(slug)
    safe_date = _validated_date(date)
    if bool(recon) == bool(target):
        raise setup_transaction.SetupTransactionError(
            "ambiguous_source", "provide exactly one source: recon JSON or --target URL"
        )
    if classify and not recon:
        raise setup_transaction.SetupTransactionError(
            "classify_requires_recon", "--classify requires a validated recon source"
        )

    request: dict = {
        "slug": safe_slug,
        "date": safe_date,
        "run_name": f"{safe_slug}_{safe_date}",
        "classify": bool(classify),
    }
    if target:
        target_url = _validated_target_url(target)
        try:
            manifest, source_bytes = setup_source.normalize_url(target_url)
        except setup_source.SetupSourceError as exc:
            raise setup_transaction.SetupTransactionError(exc.code, str(exc)) from exc
        digest = manifest["source_sha256"]
        try:
            from harness.privacy import redact_url

            display, _ = redact_url(target_url)
        except Exception:
            display = f"{urlsplit(target_url).scheme}://{urlsplit(target_url).hostname}/<redacted>"
        request.update({
            "kind": "target_url",
            "target": target_url,
            "source_sha256": digest,
            "source_manifest": manifest,
            "source_bytes": source_bytes,
            "related_source_bytes": {},
            "display": display,
            "validate_source": None,
        })
        return request

    recon_path = Path(str(recon)).expanduser()
    if recon_path.is_symlink():
        raise setup_transaction.SetupTransactionError(
            "source_symlink_forbidden", f"recon source must not be a symbolic link: {recon_path}"
        )
    if not recon_path.is_absolute():
        recon_path = (Path.cwd() / recon_path).resolve()
    try:
        recon_bytes = setup_source.read_source_bytes(recon_path)
    except (OSError, setup_source.SetupSourceError) as exc:
        code = getattr(exc, "code", "missing_recon")
        if code == "missing_source":
            code = "missing_recon"
        raise setup_transaction.SetupTransactionError(
            code, f"recon cannot be read: {recon_path}: {exc}"
        ) from exc
    try:
        recon_data = json.loads(recon_bytes.decode("utf-8"))
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise setup_transaction.SetupTransactionError(
            "invalid_recon_json", f"recon JSON is invalid: {recon_path}: {exc}"
        ) from exc
    if not isinstance(recon_data, dict) or not _valid_recon_assets(recon_data):
        raise setup_transaction.SetupTransactionError(
            "unknown_recon_schema",
            "recon must be an object with a non-empty assets list of host-bearing objects",
        )
    source_hash = hashlib.sha256(recon_bytes).hexdigest()
    report_path = recon_path.parent / "report.md"
    try:
        report_bytes = setup_source.read_source_bytes(report_path) if report_path.exists() else None
    except (OSError, setup_source.SetupSourceError) as exc:
        code = getattr(exc, "code", "invalid_recon_report")
        raise setup_transaction.SetupTransactionError(
            code, f"adjacent report cannot be read: {exc}"
        ) from exc
    report_text = report_bytes.decode("utf-8", "replace") if report_bytes is not None else None
    report_hash = hashlib.sha256(report_bytes).hexdigest() if report_bytes is not None else ""

    def validate_source() -> None:
        try:
            if hashlib.sha256(recon_path.read_bytes()).hexdigest() != source_hash:
                raise RuntimeError("recon source changed during setup")
            if report_bytes is not None:
                if not report_path.exists() or hashlib.sha256(report_path.read_bytes()).hexdigest() != report_hash:
                    raise RuntimeError("adjacent recon report changed during setup")
        except OSError as exc:
            raise RuntimeError(f"source disappeared during setup: {exc}") from exc

    try:
        manifest = setup_source.normalize_recon(recon_path, recon_bytes, recon_data)
    except setup_source.SetupSourceError as exc:
        raise setup_transaction.SetupTransactionError(exc.code, str(exc)) from exc
    related_source_bytes: dict[str, bytes] = {}
    if report_bytes is not None:
        related_snapshot = "sources/original/recon-report.md"
        setup_source.add_related_source(
            manifest,
            kind="recon-report",
            reference=str(report_path),
            snapshot=related_snapshot,
            media_type="text/markdown; charset=utf-8",
            raw=report_bytes,
        )
        related_source_bytes[related_snapshot] = report_bytes
    request.update({
        "kind": "recon_json",
        "recon_path": recon_path,
        "recon_data": recon_data,
        "report_text": report_text,
        "source_sha256": source_hash,
        "source_manifest": manifest,
        "source_bytes": recon_bytes,
        "related_source_bytes": related_source_bytes,
        "validate_source": validate_source,
    })
    return request


def resolve_normalized_request(
    source_path: str | Path,
    *,
    ai_mode: str,
    candidate_json: str | bytes | None,
    provider: str = "",
    model: str = "",
    date: str | None = None,
) -> dict:
    """Resolve a Markdown/ordinary-JSON candidate before formal run creation."""
    path = Path(source_path).expanduser()
    if not path.is_absolute():
        path = (Path.cwd() / path).resolve(strict=False)
    try:
        manifest, source_bytes, normalizer_artifacts = setup_normalizer.normalize_path(
            path,
            ai_mode=ai_mode,
            candidate_json=candidate_json,
            provider=provider,
            model=model,
        )
    except setup_source.SetupSourceError as exc:
        raise setup_transaction.SetupTransactionError(exc.code, str(exc)) from exc
    source_hash = str(manifest["source_sha256"])
    safe_date = _validated_date(date)
    slug = _validated_slug(setup_normalizer.derive_slug(manifest))

    def validate_source() -> None:
        try:
            current = setup_source.read_source_bytes(path)
        except setup_source.SetupSourceError as exc:
            raise RuntimeError(f"normalized source disappeared during setup: {exc}") from exc
        if hashlib.sha256(current).hexdigest() != source_hash:
            raise RuntimeError("normalized source changed during setup")

    target = manifest["target"]["primary_url"] or manifest["target"]["host"]
    return {
        "kind": "normalized_source",
        "slug": slug,
        "date": safe_date,
        "run_name": f"{slug}_{safe_date}",
        "classify": False,
        "source_path": path,
        "target": target,
        "source_sha256": source_hash,
        "source_manifest": manifest,
        "source_bytes": source_bytes,
        "related_source_bytes": {},
        "normalizer_artifacts": normalizer_artifacts,
        "validate_source": validate_source,
    }


def _record_scope_data(run_dir: Path, recon: dict) -> str:
    import scope as _scope

    sc = _scope.derive_scope(recon)
    in_line, out_line = _scope.render_scope_lines(sc)
    target_file = run_dir / "target.md"
    text = target_file.read_text(encoding="utf-8", errors="replace")

    def setfield(value: str, name: str, replacement: str) -> str:
        return re.sub(
            rf"(- {re.escape(name)}:).*",
            lambda match: f"{match.group(1)} {replacement}",
            value,
            count=1,
        )

    if sc["target"]:
        text = setfield(text, "Target", sc["target"])
    if in_line:
        text = setfield(text, "In-scope assets", in_line)
    if out_line:
        text = setfield(text, "Out-of-scope assets", out_line)
    if sc["notes"]:
        prefix = (
            "⚠ scope 启发式(recon 无 ownership), 归属待裁: "
            if sc.get("heuristic") else "scope 复核(secondary/第三方托管): "
        )
        text = setfield(
            text, "Notes", prefix + "; ".join(str(host) for host, _ in sc["notes"][:6])
        )
    target_file.write_text(text, encoding="utf-8")
    return "scope prepared"


def prepare_staging_run(
    request: dict,
    run_dir: Path,
    fault: setup_transaction.FaultInjector | None = None,
    *,
    bootstrap: bool = False,
) -> None:
    """Build every canonical and initial derived file inside hidden staging."""
    scaffold(run_dir)
    if fault:
        fault("journal")
    loop_journal.append_event(
        run_dir, "phase_start", note="prepare authorized run workbench",
        data={"phase": "Setup"},
    )
    setup_source.write_bundle(
        run_dir,
        request["source_manifest"],
        request["source_bytes"],
        request.get("related_source_bytes"),
        request.get("normalizer_artifacts"),
    )

    if request["kind"] == "recon_json":
        if fault:
            fault("ingest")
        import ingest_recon

        recon = request["recon_data"]
        recon_path = request["recon_path"]
        record_recon(run_dir, str(recon_path))
        (run_dir / "surface_recon.md").write_text(
            ingest_recon.render(recon, str(recon_path)), encoding="utf-8"
        )
        _record_scope_data(run_dir, recon)
        if fault:
            fault("coverage")
        coverage = ingest_recon.build_coverage(recon, request.get("report_text"))
        classify_dir = run_dir / "classify"
        classify_dir.mkdir(parents=True, exist_ok=True)
        (classify_dir / "coverage.json").write_text(
            json.dumps(coverage, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        if request.get("classify"):
            command = [
                sys.executable,
                str(ROOT / "tools" / "classify_hosts.py"),
                str(recon_path),
                "--out", str(classify_dir),
                "--egress-recheck",
            ]
            completed = subprocess.run(
                command, capture_output=True, encoding="utf-8", errors="replace"
            )
            if completed.returncode != 0:
                detail = (completed.stderr or completed.stdout or "classifier failed").strip()
                raise RuntimeError(detail)
            _merge_egress_recheck(run_dir)
        knowledge_match(run_dir)
    elif request["kind"] == "target_url":
        record_recon(run_dir, "none")
        record_target(run_dir, request["target"])
        if fault:
            fault("coverage")
        _derive_coverage_from_target(run_dir)
    else:
        record_recon(run_dir, request["source_manifest"]["source"]["snapshot"])
        record_target(run_dir, request["target"])
        (run_dir / "surface_recon.md").write_text(
            _render_normalized_surface(request["source_manifest"]), encoding="utf-8"
        )
        if fault:
            fault("coverage")
        _derive_coverage_from_manifest(run_dir, request["source_manifest"])
        knowledge_match(run_dir)

    record_setup_source(run_dir, request["source_manifest"])

    if not _coverage_ready(run_dir):
        raise RuntimeError("coverage preparation produced no valid asset")
    if fault:
        fault("asset_ledger")
    import coverage_matrix

    coverage_matrix.write_outputs(run_dir)
    if not (run_dir / "state" / "asset_ledger.json").exists():
        raise RuntimeError("asset ledger was not written")

    if bootstrap:
        loop_journal.append_event(
            run_dir, "bootstrap", note="new run prepared by shared setup transaction"
        )
    loop_journal.append_event(
        run_dir,
        "phase_end",
        note=f"run prepared; next phase=Root Orchestrator (/loop runs/{request['run_name']})",
        data={"phase": "Setup"},
    )
    state = {
        "drift_flags": [],
        "updated_at": time.time(),
        "reread_pending": False,
        "drift_block_count": 0,
    }
    (run_dir / "state" / "session_state.json").write_text(
        json.dumps(state, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    if fault:
        fault("loop_state")
    import loop_state
    import progress_ledger
    import run_controller

    loop_state.write_outputs(run_dir)
    progress_ledger.write_outputs(run_dir)
    run_controller.write_shadow(run_dir)


def create_run(
    slug: str,
    *,
    recon: str | None = None,
    target: str | None = None,
    date: str | None = None,
    classify: bool = False,
    bootstrap: bool = False,
    fault: setup_transaction.FaultInjector | None = None,
) -> setup_transaction.TransactionResult:
    request = resolve_setup_request(
        slug, recon=recon, target=target, date=date, classify=classify
    )
    return setup_transaction.create_and_activate(
        request["run_name"],
        source_manifest=request["source_manifest"],
        build=lambda run_dir, nested_fault: prepare_staging_run(
            request, run_dir, nested_fault, bootstrap=bootstrap
        ),
        validate_source=request.get("validate_source"),
        root=ROOT,
        runs_root=ROOT / "runs",
        pointer=ROOT / ".claude" / "xunji_active_run",
        fault=fault,
    )


def main() -> int:
    ap = argparse.ArgumentParser(description="初始化授权目标 run 工作台(派生不驱动)")
    ap.add_argument("slug", nargs="?", help="目标短名 → run 目录 runs/<slug>_<date>")
    ap.add_argument("recon", nargs="?", help="recon JSON 路径(可选; 给了就 ingest)")
    ap.add_argument("--target", default=None,
                    help="无 recon 时写入 target.md Target 并派生最小 coverage.json, 如 https://example.com:8443")
    ap.add_argument("--date", default=None, help="YYYYMMDD; 默认今天")
    ap.add_argument("--classify", action="store_true",
                    help="顺带跑 classify_hosts 建 coverage.json(实时探测=主动侦察, 需授权)")
    ap.add_argument("--selftest", action="store_true")
    args = ap.parse_args()

    if args.selftest:
        return _selftest()
    if not args.slug:
        ap.error("need <slug> (or --selftest)")

    try:
        create_run(
            args.slug,
            recon=args.recon,
            target=args.target,
            date=args.date,
            classify=args.classify,
        )
    except setup_transaction.SetupTransactionError as exc:
        hint = ""
        if exc.code in {"run_exists", "prepared_not_active"}:
            hint = "；可选择 resume / choose-date / choose-slug"
        print(f"[setup:{exc.code}] {exc}{hint}", file=sys.stderr)
        return 1
    return 0


def _raises_exist(existing: Path) -> bool:
    try:
        scaffold(existing)
        return False
    except FileExistsError:
        return True
    except Exception:
        return False


def _selftest() -> int:
    """纯本地回归: 骨架齐全 / 子目录 / recon 记录与 ingest / 不覆盖守卫。无网络。"""
    import contextlib
    import io
    import tempfile
    d = Path(tempfile.mkdtemp())
    rd = d / "t_20260101"
    made = scaffold(rd)
    _phase_journal(rd, "phase_start", "Setup", "selftest")
    _phase_journal(rd, "phase_end", "Setup", "selftest done")
    journal = loop_journal.summarize(rd)
    phase_events = [
        str(item.get("event") or "")
        for item in journal["last_cycle_phase_events"]
    ]
    checks = [
        ("all required files copied", all((rd / n).exists() for n in REQUIRED)),
        ("evidence/ subdir", (rd / "evidence").is_dir() and (rd / "evidence" / ".gitkeep").exists()),
        ("scripts/ subdir", (rd / "scripts").is_dir()),
        ("operator profile scaffolded", (rd / "state" / "operator_profile.json").exists()),
        ("frontier template has depth field", "Current depth" in (rd / "frontier.md").read_text(encoding="utf-8")),
        ("no-overwrite guard raises", _raises_exist(rd)),
        ("setup phase journal records start and end",
         phase_events == ["phase_start", "phase_end"] and not journal["open_phase"]),
    ]

    main_root = d / "main-root"
    (main_root / "runs").mkdir(parents=True)
    main_run = main_root / "runs" / "bannercheck_20260102"
    original_root = ROOT
    original_argv = list(sys.argv)
    captured_stdout = io.StringIO()
    captured_stderr = io.StringIO()
    try:
        globals()["ROOT"] = main_root
        sys.argv = [
            "setup_run.py", "bannercheck", "--target", "https://example.test",
            "--date", "20260102",
        ]
        with contextlib.redirect_stdout(captured_stdout), contextlib.redirect_stderr(captured_stderr):
            main_rc = main()
    finally:
        sys.argv = original_argv
        globals()["ROOT"] = original_root
    main_output = captured_stdout.getvalue()
    main_error = captured_stderr.getvalue()
    main_journal = loop_journal.summarize(main_run)
    main_phase_events = [
        str(item.get("event") or "")
        for item in main_journal["last_cycle_phase_events"]
    ]
    main_source = json.loads(
        (main_run / setup_transaction.SOURCE_REL).read_text(encoding="utf-8")
    ) if (main_run / setup_transaction.SOURCE_REL).exists() else {}
    main_receipt = json.loads(
        (main_run / setup_transaction.RECEIPT_REL).read_text(encoding="utf-8")
    ) if (main_run / setup_transaction.RECEIPT_REL).exists() else {}
    main_target = (
        (main_run / "target.md").read_text(encoding="utf-8", errors="replace")
        if (main_run / "target.md").exists() else ""
    )
    try:
        source_bundle_verified = bool(setup_source.verify_bundle(main_run, main_source))
    except setup_source.SetupSourceError:
        source_bundle_verified = False
    checks += [
        ("full setup main succeeds in isolated root", main_rc == 0),
        ("full setup main is stdout-silent on success", main_output == ""),
        ("full setup main has no stderr diagnostics on success", main_error == ""),
        ("full setup main preserves closed Setup journal cycle",
         main_phase_events == ["phase_start", "phase_end"]
         and not main_journal["open_phase"]),
        ("full setup freezes a source manifest",
         main_source.get("schema") == setup_transaction.SOURCE_SCHEMA
         and len(str(main_source.get("source_sha256") or "")) == 64),
        ("full setup freezes and verifies the separate provenance bundle",
         source_bundle_verified
         and (main_run / setup_source.NORMALIZED_REL).exists()
         and (main_run / setup_source.VALIDATOR_REL).exists()
         and (main_run / "sources" / "original" / "target-url.txt").exists()),
        ("target.md cites source hash and validator while remaining canonical",
         "## Setup Source" in main_target
         and str(main_source.get("source_sha256") or "") in main_target
         and setup_source.VALIDATOR_REL.as_posix() in main_target
         and "target.md remains canonical" in main_target),
        ("full setup commits a transaction receipt",
         main_receipt.get("schema") == setup_transaction.RECEIPT_SCHEMA
         and main_receipt.get("status") == "committed"),
        ("full setup publishes initial derived state before activation",
         all((main_run / "state" / name).exists() for name in (
             "asset_ledger.json", "session_state.json", "loop_state.json",
             "progress_ledger.json", "controller.shadow.json"))),
        ("full setup leaves no visible staging directory",
         not (main_root / "runs" / setup_transaction.STAGING_NAME).exists()),
    ]

    normalized_source = d / "normalized.md"
    normalized_source.write_text(
        "- Target: https://normalizer.example.test/login?token=private-value\n"
        "- Asset: api.normalizer.example.test\n"
        "Unlabelled mirror https://mirror.normalizer.example.test/status\n",
        encoding="utf-8",
    )
    normalizer_request, normalizer_inventory = setup_normalizer.prepare_request(
        normalized_source,
        ai_mode="external",
        provider="fixture-provider",
        model="fixture-model",
    )
    normalizer_candidate = setup_normalizer.candidate_template(normalizer_request)
    normalizer_candidate["target_token"] = next(
        item.id for item in normalizer_inventory.tokens if "target" in item.roles
    )
    normalizer_candidate["asset_tokens"] = [
        next(item.id for item in normalizer_inventory.tokens if item.value.startswith("https://mirror."))
    ]
    normalized_request = resolve_normalized_request(
        normalized_source,
        ai_mode="external",
        candidate_json=json.dumps(normalizer_candidate),
        provider="fixture-provider",
        model="fixture-model",
        date="20260103",
    )
    normalized_root = d / "normalized-root"
    normalized_runs = normalized_root / "runs"
    normalized_runs.mkdir(parents=True)
    normalized_result = setup_transaction.create_and_activate(
        normalized_request["run_name"],
        source_manifest=normalized_request["source_manifest"],
        build=lambda run_dir, fault: prepare_staging_run(
            normalized_request, run_dir, fault, bootstrap=True
        ),
        validate_source=normalized_request["validate_source"],
        root=normalized_root,
        runs_root=normalized_runs,
        pointer=normalized_root / ".claude" / "xunji_active_run",
    )
    normalized_run = normalized_result.run_dir
    normalized_manifest = json.loads(
        (normalized_run / setup_transaction.SOURCE_REL).read_text(encoding="utf-8")
    )
    normalized_coverage = json.loads(
        (normalized_run / "classify" / "coverage.json").read_text(encoding="utf-8")
    )
    normalized_target = (normalized_run / "target.md").read_text(
        encoding="utf-8", errors="replace"
    )
    try:
        normalized_verified = bool(setup_source.verify_bundle(normalized_run, normalized_manifest))
    except setup_source.SetupSourceError:
        normalized_verified = False
    stored_request = (normalized_run / setup_source.NORMALIZER_REQUEST_REL).read_text(
        encoding="utf-8", errors="strict"
    )
    checks += [
        ("external normalized source commits through the shared transaction",
         normalized_result.status == "committed" and normalized_manifest["source"]["kind"] == "markdown"),
        ("external normalizer request/candidate artifacts are frozen and verified",
         normalized_verified
         and (normalized_run / setup_source.NORMALIZER_REQUEST_REL).exists()
         and (normalized_run / setup_source.NORMALIZER_CANDIDATE_REL).exists()),
        ("stored external request contains no raw query secret or source path",
         "private-value" not in stored_request and str(normalized_source) not in stored_request),
        ("candidate inventory supplements source-backed assets without probing",
         {item["host"] for item in normalized_coverage["assets"]} >= {
             "normalizer.example.test", "api.normalizer.example.test",
             "mirror.normalizer.example.test",
         }
         and all(item["scope_status"] == "review" for item in normalized_coverage["assets"])),
        ("file-derived target is canonical but source claims remain data",
         "https://normalizer.example.test/login?token=private-value" in normalized_target
         and normalized_manifest["operator_directive"]["provided_target"] is False
         and all(item["authority"] != "operator" for item in normalized_manifest["authorization_claims"])),
    ]
    (normalized_run / setup_source.NORMALIZER_CANDIDATE_REL).write_text("{}", encoding="utf-8")
    try:
        setup_source.verify_bundle(normalized_run, normalized_manifest)
        normalizer_mutation_rejected = False
    except setup_source.SetupSourceError as exc:
        normalizer_mutation_rejected = exc.code in {
            "normalizer_artifact_mismatch", "normalizer_artifact_invalid",
        }
    checks.append(("normalizer artifact mutation blocks bundle verification", normalizer_mutation_rejected))

    mutation_source = d / "mutation.md"
    mutation_source.write_text("- Target: https://mutation.example.test/\n", encoding="utf-8")
    mutation_request = resolve_normalized_request(
        mutation_source, ai_mode="off", candidate_json=None, date="20260104"
    )
    mutation_source.write_text("- Target: https://changed.example.test/\n", encoding="utf-8")
    mutation_root = d / "mutation-root"
    mutation_runs = mutation_root / "runs"
    mutation_runs.mkdir(parents=True)
    try:
        setup_transaction.create_and_activate(
            mutation_request["run_name"],
            source_manifest=mutation_request["source_manifest"],
            build=lambda run_dir, fault: prepare_staging_run(
                mutation_request, run_dir, fault, bootstrap=True
            ),
            validate_source=mutation_request["validate_source"],
            root=mutation_root,
            runs_root=mutation_runs,
            pointer=mutation_root / ".claude" / "xunji_active_run",
        )
        normalized_mutation_rejected = False
    except setup_transaction.SetupTransactionError:
        normalized_mutation_rejected = True
    checks.append((
        "normalized source TOCTOU fails without formal run or pointer",
        normalized_mutation_rejected
        and not (mutation_runs / mutation_request["run_name"]).exists()
        and not (mutation_root / ".claude" / "xunji_active_run").exists(),
    ))

    def request_error(code: str, **kwargs) -> bool:
        try:
            resolve_setup_request("valid", date="20260101", classify=False, **kwargs)
        except setup_transaction.SetupTransactionError as exc:
            return exc.code == code
        return False

    bad_json = d / "bad-recon.json"
    bad_json.write_text("{", encoding="utf-8")
    unknown_json = d / "unknown-recon.json"
    unknown_json.write_text("{}", encoding="utf-8")
    oversized_recon = d / "oversized-recon.json"
    with oversized_recon.open("wb") as handle:
        handle.truncate(setup_source.MAX_SOURCE_BYTES + 1)
    symlink_recon = d / "symlink-recon.json"
    try:
        symlink_recon.symlink_to(unknown_json)
        symlink_request_rejected = request_error(
            "source_symlink_forbidden", recon=str(symlink_recon), target=None
        )
    except OSError:
        symlink_request_rejected = True
    checks += [
        ("missing recon fails before staging",
         request_error("missing_recon", recon=str(d / "missing.json"), target=None)),
        ("damaged recon fails before staging",
         request_error("invalid_recon_json", recon=str(bad_json), target=None)),
        ("unknown recon schema fails before staging",
         request_error("unknown_recon_schema", recon=str(unknown_json), target=None)),
        ("oversized recon fails before staging",
         request_error("source_too_large", recon=str(oversized_recon), target=None)),
        ("symlink recon fails before staging", symlink_request_rejected),
        ("invalid URL fails before staging",
         request_error("invalid_target_url", recon=None, target="not a url")),
        ("URL userinfo fails before staging",
         request_error("invalid_target_url", recon=None, target="https://user:pass@example.test/")),
    ]
    try:
        resolve_setup_request(
            "bad slug", recon=None, target="https://example.test", date="20260101",
            classify=False,
        )
        bad_slug_rejected = False
    except setup_transaction.SetupTransactionError as exc:
        bad_slug_rejected = exc.code == "invalid_slug"
    try:
        resolve_setup_request(
            "valid", recon=None, target="https://example.test", date="20260231",
            classify=False,
        )
        bad_date_rejected = False
    except setup_transaction.SetupTransactionError as exc:
        bad_date_rejected = exc.code == "invalid_date"
    checks += [
        ("invalid slug is rejected rather than silently rewritten", bad_slug_rejected),
        ("invalid calendar date is rejected", bad_date_rejected),
    ]

    help_stdout = io.StringIO()
    help_stderr = io.StringIO()
    original_argv = list(sys.argv)
    try:
        sys.argv = ["setup_run.py", "--help"]
        with contextlib.redirect_stdout(help_stdout), contextlib.redirect_stderr(help_stderr):
            try:
                main()
                help_rc = None
            except SystemExit as exc:
                help_rc = exc.code
    finally:
        sys.argv = original_argv
    checks += [
        ("explicit --help preserves argparse stdout", help_rc == 0 and "usage:" in help_stdout.getvalue()),
        ("explicit --help has no stderr diagnostics", help_stderr.getvalue() == ""),
    ]

    classify_recon = d / "classify-recon.json"
    classify_recon.write_text(json.dumps({
        "target": "classify.example",
        "assets": [{
            "host": "classify.example", "category": "web",
            "reachability": "confirmed", "ownership": "core",
        }],
    }), encoding="utf-8")
    classify_run = main_root / "runs" / "classifycheck_20260103"
    classify_calls: list[list[str]] = []
    original_root = ROOT
    original_subprocess_run = subprocess.run
    original_argv = list(sys.argv)
    classify_stdout = io.StringIO()
    classify_stderr = io.StringIO()

    def _fake_classify_run(cmd, **_kwargs):
        classify_calls.append(list(cmd))
        return subprocess.CompletedProcess(cmd, 0, stdout="classifier progress\n", stderr="")

    try:
        globals()["ROOT"] = main_root
        subprocess.run = _fake_classify_run
        sys.argv = [
            "setup_run.py", "classifycheck", str(classify_recon),
            "--classify", "--date", "20260103",
        ]
        with contextlib.redirect_stdout(classify_stdout), contextlib.redirect_stderr(classify_stderr):
            classify_rc = main()
    finally:
        sys.argv = original_argv
        subprocess.run = original_subprocess_run
        globals()["ROOT"] = original_root
    classify_journal = loop_journal.summarize(classify_run)
    checks += [
        ("--classify setup succeeds with isolated classifier", classify_rc == 0),
        ("--classify executes egress recheck",
         len(classify_calls) == 1 and "--egress-recheck" in classify_calls[0]),
        ("--classify progress stdout stays silent", classify_stdout.getvalue() == ""),
        ("--classify has no stderr diagnostics on success", classify_stderr.getvalue() == ""),
        ("--classify preserves closed Setup journal cycle",
         [str(item.get("event") or "") for item in classify_journal["last_cycle_phase_events"]]
         == ["phase_start", "phase_end"] and not classify_journal["open_phase"]),
    ]
    recon = {"target": "t", "assets": [{"host": "a.example", "category": "c", "reachability": "confirmed", "ownership": "core"}]}
    rp = d / "recon.json"
    rp.write_text(json.dumps(recon), encoding="utf-8")
    adjacent_report = d / "report.md"
    adjacent_report.write_text(
        "# Recon\n## 已确认可达资产\n| a.example | 200 | test |\n", encoding="utf-8"
    )
    frozen_request = resolve_setup_request(
        "frozen", recon=str(rp), target=None, date="20260101", classify=False
    )
    adjacent_report.write_text("# mutated report\n", encoding="utf-8")
    try:
        frozen_request["validate_source"]()
        related_mutation_rejected = False
    except RuntimeError:
        related_mutation_rejected = True
    adjacent_report.write_text(
        "# Recon\n## 已确认可达资产\n| a.example | 200 | test |\n", encoding="utf-8"
    )
    rp.write_text(json.dumps({**recon, "mutated": True}), encoding="utf-8")
    try:
        frozen_request["validate_source"]()
        source_mutation_rejected = False
    except RuntimeError:
        source_mutation_rejected = True
    rp.write_text(json.dumps(recon), encoding="utf-8")
    related_stage = d / "related-stage"
    prepare_staging_run(frozen_request, related_stage)
    related_bundle_verified = bool(setup_source.verify_bundle(
        related_stage,
        json.loads((related_stage / setup_transaction.SOURCE_REL).read_text(encoding="utf-8"))
        if (related_stage / setup_transaction.SOURCE_REL).exists()
        else frozen_request["source_manifest"],
    )) if (related_stage / setup_source.NORMALIZED_REL).exists() else False
    record_recon(rd, str(rp))
    info = ingest(rp, rd)
    sinfo = record_scope(rd, rp)
    tgt = (rd / "target.md").read_text(encoding="utf-8")
    checks += [
        ("target.md records recon path", str(rp) in tgt),
        ("recon path with backslashes intact (no re.sub group bug)", "\\1" not in tgt),
        ("surface_recon.md written w/ asset", (rd / "surface_recon.md").exists()
            and "a.example" in (rd / "surface_recon.md").read_text(encoding="utf-8")),
        ("ingest reports asset count", "1 assets" in info),
        ("scope 派生填进 target.md Target", "- Target: t" in tgt),
        ("scope 派生填进 In-scope assets", "*.a.example" in tgt),
        ("record_scope 报派生计数", "in-模式" in sinfo),
        ("recon source mutation is rejected before publish", source_mutation_rejected),
        ("adjacent report mutation is rejected before publish", related_mutation_rejected),
        ("report-derived coverage freezes its related source snapshot",
         related_bundle_verified
         and (related_stage / "sources/original/recon-report.md").read_text(encoding="utf-8")
         == adjacent_report.read_text(encoding="utf-8")
         and frozen_request["source_manifest"]["related_sources"][0]["kind"]
         == "recon-report"),
    ]
    # adapt_coverage: Guanlan 产物 → coverage.json(零重探)
    adapt_coverage(rp, rd)
    cov_p = rd / "classify" / "coverage.json"
    cov_j = json.loads(cov_p.read_text(encoding="utf-8")) if cov_p.exists() else {}
    checks += [
        ("adapt_coverage 写 classify/coverage.json", cov_p.exists()),
        ("coverage 含资产 a.example", any(a.get("host") == "a.example" for a in cov_j.get("assets", []))),
        ("coverage examined=0(零重探, 没发包)", cov_j.get("examined") == 0),
        ("coverage source 标 guanlan-adapter", "guanlan" in cov_j.get("source", "")),
    ]
    # no-recon path writes 'none' (avoid template placeholder tripping _recon_cited)
    rd2 = d / "t2_20260101"
    scaffold(rd2)
    record_recon(rd2, "none")
    no_target_info = _derive_coverage_from_target(rd2)
    bad_target = d / "bad_target_20260101"
    scaffold(bad_target)
    record_target(bad_target, "not a url")
    bad_target_info = _derive_coverage_from_target(bad_target)
    rd3 = d / "t3_20260101"
    scaffold(rd3)
    record_recon(rd3, "none")
    record_target(rd3, "http://example.org:8080/app")
    target_info = _derive_coverage_from_target(rd3)
    target_cov = json.loads((rd3 / "classify" / "coverage.json").read_text(encoding="utf-8"))
    checks += [
        ("no-recon target records 'none'",
         "recon report: none" in (rd2 / "target.md").read_text(encoding="utf-8")),
        ("no-recon without Target does not claim coverage built",
         "Target 为空" in no_target_info and not (rd2 / "classify" / "coverage.json").exists()),
        ("malformed target does not write coverage",
         "格式不适合" in bad_target_info and not (bad_target / "classify" / "coverage.json").exists()),
        ("record_target fills target.md Target",
         "- Target: http://example.org:8080/app" in (rd3 / "target.md").read_text(encoding="utf-8")),
        ("no-recon explicit target writes coverage",
         (rd3 / "classify" / "coverage.json").exists() and "example.org" in target_info),
        ("target-derived coverage parses scheme and port",
         target_cov["assets"][0]["host"] == "example.org"
         and target_cov["assets"][0]["scheme"] == "http"
         and target_cov["assets"][0]["port"] == 8080),
    ]

    bad = [n for n, ok in checks if not ok]
    for n, ok in checks:
        print(("ok   " if ok else "FAIL ") + n)
    print("setup_run selftest " + ("passed" if not bad else f"FAILED ({len(bad)})"))
    return 0 if not bad else 1


if __name__ == "__main__":
    raise SystemExit(main())
