#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Asset x vuln-family coverage matrix.

Markdown remains canonical. This tool derives a review view from coverage.json,
frontier.md, and constraints.md so closure can see breadth gaps that front status
alone hides: whole vuln families never touched, or an asset row with many
signal-justified blanks.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import tempfile
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8")       # type: ignore[attr-defined]
except Exception:
    pass

ROOT = Path(__file__).resolve().parents[1]
HWS = r"[^\S\n]"

sys.path.insert(0, str(Path(__file__).resolve().parent))
try:
    from saturation import _canonical, _field, _parse_constraints, _parse_list_field
except Exception:  # pragma: no cover - defensive fallback for broken imports
    def _canonical(name: str) -> str:
        return name.strip().lower()

    def _field(text: str, name: str) -> str:
        m = re.search(rf"(?im)^\s*[-*]?\s*{re.escape(name)}\s*[:：]\s*([^\n]*)", text)
        return m.group(1).strip() if m else ""

    def _parse_constraints(run_dir: Path) -> list[dict]:
        return []

    def _parse_list_field(text: str, name: str) -> list[str]:
        raw = _field(text, name)
        return [p.strip() for p in re.split(r"[;,]", raw) if p.strip()]


GROUPS: list[tuple[str, list[str]]] = [
    ("Auth", [
        "auth-bypass", "SQLi-login", "enum", "default-creds",
        "unauthenticated access", "horizontal privilege-escalation",
        "vertical privilege-escalation", "SSO / OAuth / SAML flaws",
    ]),
    ("Injection", [
        "SQLi", "NoSQLi", "OS command injection", "SSTI", "deserialization",
        "Code / expression injection", "LDAP / XPath / CRLF / HTTP-header / SMTP / ORM injection",
    ]),
    ("IDOR", ["IDOR", "mass-assignment"]),
    ("Misconfig", [
        "debug / admin interface exposure", "unauthenticated services",
        "CORS misconfiguration", "security headers / cookie / session config",
        "middleware / parsing quirks", "known component CVE",
    ]),
    ("InfoLeak", [
        "source / sourcemap leak", "VCS leak", "backup / temp files",
        "hardcoded secrets / tokens", "directory listing / error stack",
    ]),
    ("SSRF", ["SSRF", "metadata SSRF"]),
    ("PathTraversal", ["path traversal", "arbitrary file read/write/delete/download"]),
    ("XXE", ["XXE"]),
    ("Upload", ["upload-to-shell"]),
    ("Logic", ["race / TOCTOU", "flow bypass", "replay"]),
]


GROUP_CLASS_MAP: dict[str, set[str]] = {
    group: {_canonical(c) for c in classes if _canonical(c)}
    for group, classes in GROUPS
}


SURFACE_GROUPS: dict[str, set[str]] = {
    "login": {"Auth", "Injection"},
    "sso": {"Auth"},
    "oauth": {"Auth"},
    "param-api": {"Injection", "IDOR", "SSRF", "Logic"},
    "graphql": {"Injection", "IDOR", "Logic"},
    "websocket": {"Injection", "IDOR", "Logic"},
    "upload": {"Upload", "PathTraversal", "XXE"},
    "url-fetch": {"SSRF"},
    "file-download": {"PathTraversal", "InfoLeak"},
    "admin": {"Auth", "Misconfig", "InfoLeak"},
    "actuator": {"Auth", "Misconfig", "InfoLeak"},
    "swagger": {"Auth", "Misconfig", "InfoLeak", "IDOR"},
    "exposure": {"InfoLeak", "Misconfig"},
}


FLAG_SUBTYPES: dict[str, str] = {
    "LOGIN": "login",
    "SURFACE:SSO": "sso",
    "SURFACE:API": "param-api",
    "SURFACE:GRAPHQL": "graphql",
    "SURFACE:WEBSOCKET": "websocket",
    "SURFACE:UPLOAD": "upload",
    "SURFACE:URL_FETCH": "url-fetch",
    "SURFACE:FILE_DOWNLOAD": "file-download",
    "SURFACE:ADMIN": "admin",
    "SURFACE:ACTUATOR": "actuator",
    "SURFACE:SWAGGER": "swagger",
}


def _resolve_run_dir(path: str | Path) -> Path:
    p = Path(path)
    return (p if p.is_absolute() else ROOT / p).resolve()


def _load_coverage(run_dir: Path) -> tuple[Path | None, dict, list[str]]:
    parse_errors: list[str] = []
    for p in [run_dir / "coverage.json", *sorted(run_dir.glob("**/coverage.json"))]:
        if not p.exists():
            continue
        try:
            data = json.loads(p.read_text(encoding="utf-8", errors="replace"))
        except Exception as e:
            parse_errors.append(f"{p.relative_to(run_dir) if p.is_relative_to(run_dir) else p}: {e}")
            continue
        if isinstance(data, dict):
            return p, data, parse_errors
    return None, {"assets": []}, parse_errors


def _asset_display(asset: dict) -> str:
    raw = str(asset.get("host") or asset.get("asset") or asset.get("url") or "").strip()
    raw = re.sub(r"^[a-z][a-z0-9+.\-]*://", "", raw, flags=re.I).split("/", 1)[0]
    port = asset.get("port")
    if port and ":" not in raw:
        raw = f"{raw}:{port}"
    return raw.strip().rstrip(".")


def _host_tokens(asset_name: str) -> set[str]:
    low = asset_name.lower()
    toks = {low}
    if low.startswith("[") and "]" in low:
        toks.add(low[1:low.index("]")])
    elif low.count(":") == 1:
        toks.add(low.split(":")[0])
    return {t for t in toks if t}


def _asset_tokens_from_value(value: str) -> set[str]:
    tokens: set[str] = set()
    for raw in re.split(r"[,;，、]+", value):
        part = raw.strip().strip("`'\"(){}<>").rstrip(".,")
        if not part or part in {"-", "n/a", "N/A"}:
            continue
        display = _asset_display({"host": part})
        if display:
            tokens.update(_host_tokens(display))
    return tokens


def _front_declared_asset_tokens(text: str) -> set[str]:
    tokens: set[str] = set()
    for name in ("Asset", "Assets", "Target", "Targets"):
        raw = _field(text, name)
        if raw:
            tokens.update(_asset_tokens_from_value(raw))
    return tokens


def _mentions_any_host(text: str, tokens: set[str]) -> bool:
    hay = text.lower()
    for tok in tokens:
        if re.search(r"(?<![\w.\-])" + re.escape(tok) + r"(?![\w.\-])", hay):
            return True
    return False


def _asset_relevant(asset: dict) -> bool:
    val = asset.get("reachable")
    return val is True or str(val).lower() == "unknown"


def _asset_subtypes(asset: dict) -> set[str]:
    flags = {str(f).upper() for f in (asset.get("flags") or [])}
    out = {subtype for flag, subtype in FLAG_SUBTYPES.items() if flag in flags}
    # Free-text titles and stack names are too noisy for applicability. Live
    # body-derived signals should already arrive as SURFACE:* flags; keyword
    # fallback is limited to inventory/category fields plus host naming.
    text = " ".join(str(asset.get(k) or "") for k in (
        "category", "category_id", "reason", "host"))
    low = text.lower()
    keyword_map = [
        ("auth", "login"), ("vpn", "login"), ("login", "login"),
        ("sso", "sso"), ("oauth", "oauth"), ("api", "param-api"),
        ("graphql", "graphql"), ("upload", "upload"), ("file", "file-download"),
        ("download", "file-download"), ("admin", "admin"), ("manage", "admin"),
        ("swagger", "swagger"), ("actuator", "actuator"), ("webhook", "url-fetch"),
        ("url fetch", "url-fetch"),
    ]
    for kw, subtype in keyword_map:
        if _keyword_present(low, kw):
            out.add(subtype)
    return out


def _keyword_present(haystack: str, keyword: str) -> bool:
    """Match surface keywords as tokens, not arbitrary substrings.

    Short words like "file" and "api" are common inside unrelated text
    ("profile", "capistrano"). Treat punctuation/underscore as separators while
    requiring alnum boundaries.
    """
    pat = r"(?<![a-z0-9])" + re.escape(keyword.lower()) + r"(?![a-z0-9])"
    return bool(re.search(pat, haystack))


def _applicable_groups(asset: dict) -> set[str]:
    groups: set[str] = set()
    for subtype in _asset_subtypes(asset):
        groups.update(SURFACE_GROUPS.get(subtype, set()))
    return groups


def _front_sections(text: str) -> list[tuple[str, str]]:
    sections: list[tuple[str, str]] = []
    current = "unknown"
    buf: list[str] = []
    for line in text.splitlines():
        mh = re.match(r"^##[ \t]+(.+?)[ \t]*$", line)
        if mh:
            if buf:
                sections.append((current, "\n".join(buf)))
                buf = []
            current = mh.group(1).strip()
            continue
        buf.append(line)
    if buf:
        sections.append((current, "\n".join(buf)))
    return sections


def _parse_front_blocks(run_dir: Path) -> list[dict]:
    fr = run_dir / "frontier.md"
    if not fr.exists():
        return []
    text = fr.read_text(encoding="utf-8", errors="replace")
    blocks: list[dict] = []
    for section, body in _front_sections(text):
        sec_low = section.lower()
        if sec_low.startswith("open"):
            section_status = "open"
        elif sec_low.startswith("deferred"):
            section_status = "deferred"
        elif sec_low.startswith("closed"):
            section_status = "closed"
        else:
            section_status = "unknown"
        for m in re.finditer(r"(?ms)^###[ \t]+(F-\d+).*?(?=^###[ \t]+F-\d+|\Z)", body):
            block_text = m.group(0)
            blocks.append({
                "id": m.group(1),
                "status": (_field(block_text, "Status") or section_status).lower(),
                "section": section,
                "text": block_text,
            })
    return blocks


def _front_tried_classes(front: dict, constraints: list[dict]) -> set[str]:
    tried = {_canonical(x) for x in _parse_list_field(front["text"], "Vectors tried") if _canonical(x)}
    fid = front["id"]
    for c in constraints:
        if c.get("front") == fid:
            mc = _canonical(str(c.get("mechanism_class") or ""))
            if mc:
                tried.add(mc)
    return tried


def _class_groups(classes: set[str]) -> set[str]:
    out: set[str] = set()
    for group, members in GROUP_CLASS_MAP.items():
        if classes & members:
            out.add(group)
    return out


def derive(run_dir: Path) -> dict:
    cov_path, cov, coverage_warnings = _load_coverage(run_dir)
    assets = [a for a in cov.get("assets", []) if isinstance(a, dict) and _asset_display(a)]
    relevant = [a for a in assets if _asset_relevant(a)]
    if not relevant:
        relevant = assets

    rows = []
    for a in relevant:
        name = _asset_display(a)
        rows.append({
            "asset": name,
            "tokens": sorted(_host_tokens(name)),
            "applicable": sorted(_applicable_groups(a)),
            "tested": [],
            "fronts": [],
            "status": str(a.get("reachable", "")),
            "flags": [str(f) for f in (a.get("flags") or [])],
        })

    constraints = _parse_constraints(run_dir)
    for front in _parse_front_blocks(run_dir):
        tried_groups = _class_groups(_front_tried_classes(front, constraints))
        if not tried_groups:
            continue
        declared_tokens = _front_declared_asset_tokens(front["text"])
        for row in rows:
            row_tokens = set(row["tokens"])
            if (declared_tokens & row_tokens) or _mentions_any_host(front["text"], row_tokens):
                row["fronts"].append(front["id"])
                row["tested"] = sorted(set(row["tested"]) | tried_groups)

    group_names = [g for g, _ in GROUPS]
    matrix = []
    for row in rows:
        cells = {}
        applicable = set(row["applicable"])
        tested = set(row["tested"])
        for group in group_names:
            if group in tested:
                cells[group] = "tested"
            elif group in applicable:
                cells[group] = "untested"
            else:
                cells[group] = "not_applicable"
        row["cells"] = cells
        matrix.append(row)

    column_stats = {}
    for group in group_names:
        column_stats[group] = {
            "tested": sum(1 for r in matrix if r["cells"][group] == "tested"),
            "untested": sum(1 for r in matrix if r["cells"][group] == "untested"),
            "applicable": sum(1 for r in matrix if r["cells"][group] in {"tested", "untested"}),
        }

    row_gaps = []
    for row in matrix:
        applicable_n = sum(1 for v in row["cells"].values() if v in {"tested", "untested"})
        untested_n = sum(1 for v in row["cells"].values() if v == "untested")
        tested_n = sum(1 for v in row["cells"].values() if v == "tested")
        if applicable_n and untested_n / applicable_n >= 0.6:
            row_gaps.append({
                "asset": row["asset"],
                "tested": tested_n,
                "untested": untested_n,
                "applicable": applicable_n,
            })

    empty_columns = [
        group for group, stats in column_stats.items()
        if stats["applicable"] > 0 and stats["tested"] == 0
    ]

    return {
        "schema": "xunji.coverage_matrix.v1",
        "source": str(cov_path.relative_to(run_dir)) if cov_path and cov_path.is_relative_to(run_dir) else str(cov_path or ""),
        "groups": group_names,
        "rows": matrix,
        "column_stats": column_stats,
        "empty_columns": empty_columns,
        "row_gaps": row_gaps,
        "warnings": coverage_warnings,
        "legend": {"tested": "✓", "untested": "□", "not_applicable": "·"},
    }


def check(run_dir: Path) -> tuple[list[str], list[str]]:
    data = derive(run_dir)
    warns: list[str] = []
    errors: list[str] = []
    warns.extend(f"覆盖矩阵: coverage.json 解析异常, 已尝试下一个候选 —— {w}" for w in data.get("warnings", []))
    if data["empty_columns"]:
        details = ", ".join(
            f"{g}(applicable={data['column_stats'][g]['applicable']})"
            for g in data["empty_columns"]
        )
        warns.append(
            "覆盖矩阵: 下列漏洞类别在本 run 的适用资产上整列未见测试记录 —— "
            f"{details}。这通常表示方向跑偏; 收口前应确认是无适用信号, 还是缺前沿/缺 E-entry。")
    if data["row_gaps"]:
        shown = ", ".join(
            f"{r['asset']}({r['tested']}/{r['applicable']} tested)"
            for r in data["row_gaps"][:8]
        )
        warns.append(
            "覆盖矩阵: 下列资产的适用类别大多仍为空 —— "
            f"{shown}{' …' if len(data['row_gaps']) > 8 else ''}。"
            "这说明资产可能没被测透, 或 frontier 未记录 Vectors tried。")
    return warns, errors


def render_markdown(data: dict) -> str:
    groups = data["groups"]
    labels = data["legend"]
    lines = [
        "# Coverage Matrix",
        "",
        "Legend: ✓ tested / □ applicable but untested / · no current surface signal",
        "",
        "| asset | " + " | ".join(groups) + " | fronts |",
        "|---|" + "|".join("---" for _ in groups) + "|---|",
    ]
    for row in data["rows"]:
        cells = [labels[row["cells"][g]] for g in groups]
        fronts = ", ".join(sorted(set(row["fronts"]))) or "-"
        lines.append(f"| {row['asset']} | " + " | ".join(cells) + f" | {fronts} |")
    if data["empty_columns"]:
        lines.extend(["", "## Empty Columns", ""])
        for g in data["empty_columns"]:
            st = data["column_stats"][g]
            lines.append(f"- {g}: 0/{st['applicable']} applicable assets tested")
    if data["row_gaps"]:
        lines.extend(["", "## Sparse Rows", ""])
        for r in data["row_gaps"]:
            lines.append(f"- {r['asset']}: {r['tested']}/{r['applicable']} applicable groups tested")
    return "\n".join(lines) + "\n"


def write_outputs(run_dir: Path) -> dict:
    data = derive(run_dir)
    state = run_dir / "state"
    state.mkdir(parents=True, exist_ok=True)
    (state / "coverage_matrix.json").write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (state / "coverage_matrix.md").write_text(render_markdown(data), encoding="utf-8")
    return data


def _selftest() -> int:
    d = Path(tempfile.mkdtemp())
    run = d / "run"
    run.mkdir()
    (run / "coverage.json").write_text(json.dumps({"assets": [
        {"host": "a.example", "reachable": True, "flags": ["LOGIN"]},
        {"host": "b.example", "reachable": True, "flags": ["SURFACE:API"]},
        {"host": "c.example", "reachable": True, "flags": ["SURFACE:URL_FETCH"]},
        {"host": "profile.example", "reachable": True, "title": "User profile"},
        {"host": "portal.example", "reachable": True, "title": "Admin API docs"},
        {"host": "asset-field.example", "reachable": True, "flags": ["LOGIN"]},
        {"host": "url-field.example", "port": 8443, "reachable": True, "flags": ["LOGIN"]},
        {"host": "d.example", "reachable": False, "flags": ["SURFACE:UPLOAD"]},
    ]}), encoding="utf-8")
    (run / "frontier.md").write_text(
        "# Frontier\n\n"
        "## Open Fronts\n\n"
        "### F-001\n"
        "- Front: a.example login\n"
        "- Status: open\n"
        "- Vectors tried: auth bypass\n\n"
        "### F-002\n"
        "- Front: b.example API params\n"
        "- Status: probing\n"
        "- Vectors tried: SQLi, IDOR\n\n"
        "## Deferred Fronts\n\n"
        "### F-003\n"
        "- Front: c.example URL fetch\n"
        "- Status: deferred\n"
        "- Vectors tried:\n\n"
        "### F-004\n"
        "- Front: SSO flow without host token\n"
        "- Assets: asset-field.example\n"
        "- Status: probing\n"
        "- Vectors tried: auth-bypass\n\n"
        "### F-005\n"
        "- Front: URL-form target without host token\n"
        "- Targets: https://url-field.example:8443/login\n"
        "- Status: probing\n"
        "- Vectors tried: auth-bypass\n",
        encoding="utf-8",
    )
    data = derive(run)
    warns, errors = check(run)
    write_outputs(run)
    bad_cov = d / "bad_cov"
    bad_cov.mkdir()
    (bad_cov / "coverage.json").write_text("{not-json", encoding="utf-8")
    (bad_cov / "classify").mkdir()
    (bad_cov / "classify" / "coverage.json").write_text(
        json.dumps({"assets": [{"host": "nested.example", "reachable": True, "flags": ["LOGIN"]}]}),
        encoding="utf-8",
    )
    bad_cov_data = derive(bad_cov)
    bad_cov_warns, bad_cov_errors = check(bad_cov)
    by_asset = {r["asset"]: r for r in data["rows"]}
    bad_by_asset = {r["asset"]: r for r in bad_cov_data["rows"]}
    checks = [
        ("only reachable/unknown rows are included", "d.example" not in by_asset),
        ("auth vector fills Auth cell", by_asset["a.example"]["cells"]["Auth"] == "tested"),
        ("api vectors fill Injection and IDOR", by_asset["b.example"]["cells"]["Injection"] == "tested"
         and by_asset["b.example"]["cells"]["IDOR"] == "tested"),
        ("url-fetch asset exposes empty SSRF column", by_asset["c.example"]["cells"]["SSRF"] == "untested"
         and "SSRF" in data["empty_columns"]),
        ("profile does not trigger file-download keyword", all(v == "not_applicable"
         for v in by_asset["profile.example"]["cells"].values())),
        ("free-text title does not create applicability", all(v == "not_applicable"
         for v in by_asset["portal.example"]["cells"].values())),
        ("explicit Assets field attributes front to asset",
         by_asset["asset-field.example"]["cells"]["Auth"] == "tested"
         and "F-004" in by_asset["asset-field.example"]["fronts"]),
        ("explicit Targets field accepts URL host:port",
         by_asset["url-field.example:8443"]["cells"]["Auth"] == "tested"
         and "F-005" in by_asset["url-field.example:8443"]["fronts"]),
        ("corrupt primary coverage warns while using nested coverage",
         "nested.example" in bad_by_asset and bad_cov_warns and not bad_cov_errors),
        ("check reports warnings only", warns and not errors),
        ("state outputs are written", (run / "state" / "coverage_matrix.json").exists()
         and (run / "state" / "coverage_matrix.md").exists()),
    ]
    bad = [name for name, ok in checks if not ok]
    for name, ok in checks:
        print(("ok   " if ok else "FAIL ") + name)
    print("coverage_matrix selftest " + ("passed" if not bad else f"FAILED ({len(bad)})"))
    return 0 if not bad else 1


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    ap = argparse.ArgumentParser(description="derive asset x vuln-family coverage matrix")
    ap.add_argument("run_dir", nargs="?", type=Path)
    ap.add_argument("--json", action="store_true", help="print JSON instead of Markdown")
    ap.add_argument("--write", action="store_true", help="write state/coverage_matrix.{json,md}")
    ap.add_argument("--selftest", action="store_true")
    args = ap.parse_args(argv)

    if args.selftest:
        return _selftest()
    if not args.run_dir:
        ap.error("run_dir is required")
    run_dir = _resolve_run_dir(args.run_dir)
    if not run_dir.exists():
        print(f"[coverage_matrix] run 目录不存在: {run_dir}", file=sys.stderr)
        return 1
    data = write_outputs(run_dir) if args.write else derive(run_dir)
    if args.json:
        print(json.dumps(data, ensure_ascii=False, indent=2))
    else:
        print(render_markdown(data), end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
