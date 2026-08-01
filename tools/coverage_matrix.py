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
import hashlib
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

import run_model


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
GROUP_BY_LOWER = {group.lower(): group for group, _ in GROUPS}


EVIDENCE_GROUP_PATTERNS: dict[str, list[re.Pattern]] = {
    "Auth": [
        re.compile(p, re.I) for p in (
            r"\bauth(?:entication)?[- ]?(?:gate|bypass|slip)\b", r"\bSSO\b", r"\bOAuth\b",
            r"signature bypass", r"signed-API|sign(?:ature)? verification|hardcoded .*secret",
            r"OPPO_REDIRECT_URL|Redirect-Uri", r"Basic Auth", r"token[- ]?(?:gated|issuance)",
        )
    ],
    "Injection": [
        re.compile(p, re.I) for p in (
            r"\bSQLi\b|NoSQLi|injection", r"SSTI", r"deseriali[sz]ation",
            r"CVE-2018-15133",
        )
    ],
    "IDOR": [
        re.compile(p, re.I) for p in (
            r"\bIDOR\b", r"priv[- ]?esc|cross[- ]?org",
            r"(?:org[-_ ]?ID|organizationId).{0,40}\b(?:swap|switch|tamper|control|mismatch|enumerat)",
        )
    ],
    "Misconfig": [
        re.compile(p, re.I) for p in (
            r"config(?:uration)?[- ]?leak|env\.js|micro_app\.json|app_config\.json",
            r"CORS|WAF|swagger|actuator|\.env",
        )
    ],
    "InfoLeak": [
        re.compile(p, re.I) for p in (
            r"leak|disclos", r"internal host|internal .*domain|backend API",
            r"bucket|Sentry DSN|version disclosure|APP_KEY|org[- ]?ID",
        )
    ],
    "SSRF": [re.compile(p, re.I) for p in (r"\bSSRF\b", r"url[- ]?fetch|URL fetch|metadata SSRF")],
    "PathTraversal": [re.compile(p, re.I) for p in (r"path traversal|arbitrary file|file read|file download")],
    "XXE": [re.compile(r"\bXXE\b", re.I)],
    "Upload": [re.compile(p, re.I) for p in (r"\bupload\b|file upload",)],
    "Logic": [re.compile(p, re.I) for p in (r"\breplay\b|nonce|freshness|flow bypass|method[- ]?specific|GET-slip",)],
}


EVIDENCE_TEST_FIELD_RE = re.compile(
    r"(?im)^\s*-\s*(Action|Result|Control|Replicated|Artifacts?|Status|Verdict)\s*[:：]"
)


SURFACE_GROUPS: dict[str, set[str]] = {
    "login": {"Auth", "Injection"},
    "sso": {"Auth"},
    "oauth": {"Auth"},
    "param-api": {"Injection", "IDOR", "Logic"},
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


def _asset_id(name: str) -> str:
    return "ASSET-" + hashlib.sha1(name.lower().encode("utf-8")).hexdigest()[:12].upper()


def _load_assignments(run_dir: Path) -> list[dict]:
    try:
        data = json.loads((run_dir / "state" / "assignments.json").read_text(
            encoding="utf-8", errors="replace"))
    except Exception:
        return []
    rows = data.get("assignments") if isinstance(data, dict) else None
    return [item for item in rows if isinstance(item, dict)] if isinstance(rows, list) else []


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
    return [{
        "id": front.id,
        "status": front.status,
        "section": front.section,
        "text": front.text,
    } for front in run_model.parse_fronts(run_dir)]


def _coverage_status_token(value: str) -> str:
    value = value.lower().replace("-", "_")
    toks = set(re.findall(r"[a-z0-9_]+", value))
    if toks & {"confirmed", "finding", "vulnerable"}:
        return "confirmed"
    if toks & {"rejected", "refuted", "closed", "blocked_type_b", "closed_type_b"}:
        return "closed"
    if toks & {"deferred", "blocked_type_a"}:
        return "deferred"
    return ""


def _parse_evidence_blocks(run_dir: Path) -> dict[str, dict]:
    ev = run_dir / "evidence.md"
    if not ev.exists():
        return {}
    text = ev.read_text(encoding="utf-8", errors="replace")
    out: dict[str, dict] = {}
    for b in re.split(r"(?=^##\s)", text, flags=re.MULTILINE):
        if not b.lstrip().startswith("##"):
            continue
        head = b.splitlines()[0].strip()
        m = re.search(r"\b(E-\d+[a-z]*)\b", head)
        if not m:
            continue
        eid = m.group(1)
        out[eid] = {
            "id": eid,
            "text": b,
            "front_refs": sorted(set(re.findall(r"\bF-\d+\b", b))),
            "groups": _evidence_groups(b),
        }
    return out


def _parse_coverage_waivers(run_dir: Path) -> tuple[list[dict], list[str]]:
    """Parse structured coverage waivers from canonical markdown.

    Format, one line:
      - Coverage waiver: asset=host.example; groups=Upload,XXE; reason=no upload surface; evidence=E-001

    Waivers are only for matrix breadth accounting. They do not prove a finding
    and do not close a front by themselves.
    """
    waivers: list[dict] = []
    warnings: list[str] = []
    for rel in ("frontier.md", "constraints.md", "decisions.md"):
        path = run_dir / rel
        if not path.exists():
            continue
        text = path.read_text(encoding="utf-8", errors="replace")
        for lineno, line in enumerate(text.splitlines(), 1):
            if "Coverage waiver:" not in line:
                continue
            raw = line.split("Coverage waiver:", 1)[1].strip()
            fields = {
                k.strip().lower(): v.strip()
                for k, v in re.findall(r"([A-Za-z_ -]+)\s*=\s*([^;]+)", raw)
            }
            asset_raw = fields.get("asset") or fields.get("assets") or ""
            groups_raw = fields.get("group") or fields.get("groups") or ""
            reason = fields.get("reason") or ""
            if not asset_raw or not groups_raw or not reason:
                warnings.append(
                    f"{rel}:{lineno}: Coverage waiver 缺 asset/groups/reason 字段, 已忽略")
                continue
            groups: set[str] = set()
            for part in re.split(r"[,|/，、]+", groups_raw):
                key = part.strip().lower()
                if not key:
                    continue
                if key not in GROUP_BY_LOWER:
                    warnings.append(
                        f"{rel}:{lineno}: Coverage waiver group={part.strip()} 不在矩阵组名中, 已忽略该组")
                    continue
                groups.add(GROUP_BY_LOWER[key])
            if not groups:
                continue
            wildcard = asset_raw.strip() in {"*", "all", "ALL"}
            waivers.append({
                "source": f"{rel}:{lineno}",
                "asset": asset_raw,
                "asset_tokens": sorted(_asset_tokens_from_value(asset_raw)),
                "wildcard": wildcard,
                "groups": sorted(groups),
                "reason": reason,
                "evidence": fields.get("evidence") or fields.get("evidenceid") or "",
            })
    return waivers, warnings


def _evidence_groups(text: str) -> set[str]:
    if not EVIDENCE_TEST_FIELD_RE.search(text):
        return set()
    if _evidence_certainty(text) < 0.5:
        return set()
    signal = _evidence_signal_text(text)
    groups: set[str] = set()
    for group, pats in EVIDENCE_GROUP_PATTERNS.items():
        if any(p.search(signal) for p in pats):
            groups.add(group)
    return groups


def _evidence_signal_text(text: str) -> str:
    """Keep coverage inference on tested/proven fields, not caveats or next leads."""
    keep = []
    for line in text.splitlines():
        if re.match(
            r"(?i)^\s*-\s*(Action|Result|Control|Replicated|Status|Verdict)\s*[:：]",
            line,
        ):
            keep.append(line)
    return "\n".join(keep)


def _evidence_certainty(text: str) -> float:
    vals = []
    for m in re.finditer(r"(?im)^\s*-\s*Certainty[^\n:：]*[:：]\s*[\(（]?\s*(\d(?:\.\d+)?)", text):
        try:
            vals.append(float(m.group(1)))
        except ValueError:
            pass
    return max(vals) if vals else 0.0


def _front_tried_classes(front: dict, constraints: list[dict]) -> set[str]:
    tried = {_canonical(x) for x in _parse_list_field(front["text"], "Vectors tried") if _canonical(x)}
    fid = front["id"]
    for c in constraints:
        if c.get("front") == fid:
            mc = _canonical(str(c.get("mechanism_class") or ""))
            if mc:
                tried.add(mc)
    return tried


def _front_evidence_groups(front: dict, evidence: dict[str, dict]) -> set[str]:
    groups: set[str] = set()
    for eid in sorted(set(re.findall(r"\bE-\d+[a-z]*\b", front["text"]))):
        groups.update(evidence.get(eid, {}).get("groups", set()))
    return groups


def _class_groups(classes: set[str]) -> set[str]:
    out: set[str] = set()
    for group, members in GROUP_CLASS_MAP.items():
        if classes & members:
            out.add(group)
    return out


def _waiver_applies(row: dict, group: str, waivers: list[dict]) -> bool:
    row_tokens = set(row.get("tokens") or [])
    for waiver in waivers:
        if group not in set(waiver.get("groups") or []):
            continue
        if waiver.get("wildcard"):
            return True
        if row_tokens & set(waiver.get("asset_tokens") or []):
            return True
    return False


def derive(run_dir: Path) -> dict:
    cov_path, cov, coverage_warnings = _load_coverage(run_dir)
    waivers, waiver_warnings = _parse_coverage_waivers(run_dir)
    coverage_warnings.extend(waiver_warnings)
    assets = [a for a in cov.get("assets", []) if isinstance(a, dict) and _asset_display(a)]

    rows = []
    for a in assets:
        name = _asset_display(a)
        reachability = a.get("reachable")
        raw_scope_status = str(a.get("scope_status") or "").strip().lower()
        scope_status = raw_scope_status if raw_scope_status in {
            "in", "out", "review", "unknown",
        } else "legacy"
        rows.append({
            "asset_id": str(a.get("asset_id") or _asset_id(name)),
            "asset": name,
            "tokens": sorted(_host_tokens(name)),
            "scope_status": scope_status,
            "scope_authority": str(a.get("scope_authority") or ""),
            "scope_admission_id": str(a.get("scope_admission_id") or ""),
            "scope_prompt_sha256": str(a.get("scope_prompt_sha256") or ""),
            "source": str(a.get("source") or cov.get("source") or ""),
            "applicable": sorted(_applicable_groups(a)) if reachability is not False else [],
            "tested": [],
            "fronts": [],
            "assignments": [],
            "assignment_statuses": [],
            "reachability": reachability,
            "status": str(reachability),
            "examined": bool(a.get("examined")),
            "inventory_verdict": str(a.get("verdict") or ""),
            "flags": [str(f) for f in (a.get("flags") or [])],
        })

    constraints = _parse_constraints(run_dir)
    evidence = _parse_evidence_blocks(run_dir)
    fronts = _parse_front_blocks(run_dir)
    front_status = {front["id"]: _coverage_status_token(str(front.get("status") or ""))
                    for front in fronts}
    for front in fronts:
        tried_groups = _class_groups(_front_tried_classes(front, constraints)) | _front_evidence_groups(front, evidence)
        declared_tokens = _front_declared_asset_tokens(front["text"])
        matched_rows: list[dict] = []
        for row in rows:
            row_tokens = set(row["tokens"])
            if (declared_tokens & row_tokens) or _mentions_any_host(front["text"], row_tokens):
                row["fronts"].append(front["id"])
                matched_rows.append(row)
        if tried_groups and matched_rows:
            coverage_warnings.append(
                f"{front['id']}: front-level Vectors tried 不直接计入 {len(matched_rows)} 个资产的 tested cell；"
                "每个资产必须由点名该 host 的 E-entry 证明测试覆盖")

    for eid, ev in evidence.items():
        ev_groups = set(ev.get("groups", set()))
        if not ev_groups:
            continue
        for row in rows:
            row_tokens = set(row["tokens"])
            if _mentions_any_host(ev["text"], row_tokens):
                row["fronts"] = sorted(set(row["fronts"]) | set(ev.get("front_refs", [])))
                row["tested"] = sorted(set(row["tested"]) | ev_groups)

    assignment_rows = _load_assignments(run_dir)
    for assignment in assignment_rows:
        assigned_assets = set(_asset_tokens_from_value(
            ",".join(str(item) for item in (assignment.get("assets") or []))))
        if not assigned_assets:
            continue
        for row in rows:
            if set(row["tokens"]) & assigned_assets:
                row["assignments"].append(str(assignment.get("agent") or ""))
                row["assignment_statuses"].append(str(assignment.get("status") or ""))

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
                cells[group] = "waived" if _waiver_applies(row, group, waivers) else "untested"
            else:
                cells[group] = "not_applicable"
        row["cells"] = cells
        row["fronts"] = sorted(set(row["fronts"]))
        row["assignments"] = sorted(set(item for item in row["assignments"] if item))
        row["assignment_statuses"] = sorted(set(
            item.strip().lower() for item in row["assignment_statuses"] if item.strip()))
        terminal_fronts = {front_status.get(fid, "") for fid in row["fronts"]}
        terminal_fronts.discard("")
        inventory_verdict = _coverage_status_token(row["inventory_verdict"])
        active_assignment = any(status in {"assigned", "starting", "running", "working", "?", ""}
                                for status in row["assignment_statuses"])
        if row["reachability"] is False:
            disposition = "unreachable-baseline"
        elif inventory_verdict:
            disposition = inventory_verdict
        elif "confirmed" in terminal_fronts:
            disposition = "confirmed"
        elif "closed" in terminal_fronts:
            disposition = "closed"
        elif "deferred" in terminal_fronts:
            disposition = "deferred"
        elif row["tested"]:
            disposition = (
                "tested" if not any(value == "untested" for value in cells.values())
                else "tested-partial"
            )
        elif active_assignment:
            disposition = "assigned"
        elif row["fronts"]:
            disposition = "front-linked"
        else:
            disposition = "unassigned"
        row["disposition"] = disposition
        row["accounted"] = disposition not in {"unassigned"}
        row["closure_ready"] = disposition in {
            "unreachable-baseline", "confirmed", "closed", "deferred", "tested"
        }
        matrix.append(row)

    column_stats = {}
    for group in group_names:
        column_stats[group] = {
            "tested": sum(1 for r in matrix if r["cells"][group] == "tested"),
            "untested": sum(1 for r in matrix if r["cells"][group] == "untested"),
            "waived": sum(1 for r in matrix if r["cells"][group] == "waived"),
            "applicable": sum(1 for r in matrix if r["cells"][group] in {"tested", "untested", "waived"}),
            "actionable": sum(1 for r in matrix if r["cells"][group] in {"tested", "untested"}),
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
        if stats["actionable"] > 0 and stats["tested"] == 0
    ]

    accounting_gaps = [
        {"asset_id": row["asset_id"], "asset": row["asset"],
         "reachability": row["reachability"], "disposition": row["disposition"]}
        for row in matrix
        if row["reachability"] is not False and row["disposition"] == "unassigned"
    ]
    closure_gaps = [
        {"asset_id": row["asset_id"], "asset": row["asset"],
         "reachability": row["reachability"], "disposition": row["disposition"]}
        for row in matrix
        if row["reachability"] is not False and not row["closure_ready"]
    ]
    summary = {
        "total": len(matrix),
        "reachable": sum(1 for row in matrix if row["reachability"] is True),
        "unknown": sum(1 for row in matrix if str(row["reachability"]).lower() == "unknown"),
        "unreachable": sum(1 for row in matrix if row["reachability"] is False),
        "front_linked": sum(1 for row in matrix if row["fronts"]),
        "unassigned": len(accounting_gaps),
        "assigned": sum(1 for row in matrix if row["disposition"] == "assigned"),
        "disposed": sum(1 for row in matrix if row["closure_ready"]),
        "closure_debt": len(closure_gaps),
    }

    return {
        "schema": "xunji.coverage_matrix.v1",
        "source": str(cov_path.relative_to(run_dir)) if cov_path and cov_path.is_relative_to(run_dir) else str(cov_path or ""),
        "groups": group_names,
        "rows": matrix,
        "column_stats": column_stats,
        "empty_columns": empty_columns,
        "row_gaps": row_gaps,
        "accounting_gaps": accounting_gaps,
        "closure_gaps": closure_gaps,
        "summary": summary,
        "waivers": waivers,
        "warnings": coverage_warnings,
        "legend": {"tested": "✓", "untested": "□", "waived": "~", "not_applicable": "·"},
    }


def check(run_dir: Path, *, closure: bool = False) -> tuple[list[str], list[str]]:
    data = derive(run_dir)
    warns: list[str] = []
    errors: list[str] = []
    warns.extend(f"覆盖矩阵: {w}" for w in data.get("warnings", []))
    if data.get("accounting_gaps"):
        gaps = data["accounting_gaps"]
        shown = ", ".join(item["asset"] for item in gaps[:10])
        msg = (
            f"资产账本: {len(gaps)}/{data['summary']['total']} 个范围内 reachable/unknown 资产"
            "没有 front 或 assignment，仍处于 unassigned: "
            f"{shown}{' …' if len(gaps) > 10 else ''}。先显式映射资产，不能让宽泛 F-id 掩盖遗漏。")
        (errors if closure else warns).append(("收口硬门(" + msg + ")") if closure else msg)
    if closure and data.get("closure_gaps"):
        gaps = data["closure_gaps"]
        shown = ", ".join(
            f"{item['asset']}[{item['disposition']}]" for item in gaps[:10])
        errors.append(
            f"收口硬门(资产未完成): {len(gaps)}/{data['summary']['total']} 个 reachable/unknown 资产"
            "尚未达到 tested/confirmed/closed/deferred 终态: "
            f"{shown}{' …' if len(gaps) > 10 else ''}。")
    if data["empty_columns"]:
        details = ", ".join(
            f"{g}(applicable={data['column_stats'][g]['applicable']})"
            for g in data["empty_columns"]
        )
        msg = (
            "覆盖矩阵: 下列漏洞类别在本 run 的适用资产上整列未见测试记录 —— "
            f"{details}。这通常表示方向跑偏; 收口前应确认是无适用信号, 还是缺前沿/缺 E-entry。")
        (errors if closure else warns).append(("收口硬门(" + msg + ")") if closure else msg)
    if data["row_gaps"]:
        shown = ", ".join(
            f"{r['asset']}({r['tested']}/{r['applicable']} tested)"
            for r in data["row_gaps"][:8]
        )
        msg = (
            "覆盖矩阵: 下列资产的适用类别大多仍为空 —— "
            f"{shown}{' …' if len(data['row_gaps']) > 8 else ''}。"
            "这说明资产可能没被测透, 或 frontier 未记录 Vectors tried。")
        (errors if closure else warns).append(("收口硬门(" + msg + ")") if closure else msg)
    return warns, errors


def render_markdown(data: dict) -> str:
    groups = data["groups"]
    labels = data["legend"]
    lines = [
        "# Coverage Matrix",
        "",
        "Legend: ✓ tested / □ applicable but untested / ~ structured waiver / · no current surface signal",
        ("Assets: total={total} reachable={reachable} unknown={unknown} unreachable={unreachable} "
         "front-linked={front_linked} unassigned={unassigned} assigned={assigned} "
         "disposed={disposed} closure-debt={closure_debt}").format(**data["summary"]),
        "",
        "| asset | reachability | disposition | " + " | ".join(groups) + " | fronts | assignments |",
        "|---|---|---|" + "|".join("---" for _ in groups) + "|---|---|",
    ]
    for row in data["rows"]:
        cells = [labels[row["cells"][g]] for g in groups]
        fronts = ", ".join(sorted(set(row["fronts"]))) or "-"
        assignments = ", ".join(row.get("assignments") or []) or "-"
        lines.append(
            f"| {row['asset']} | {row['status']} | {row['disposition']} | "
            + " | ".join(cells) + f" | {fronts} | {assignments} |")
    if data.get("accounting_gaps"):
        lines.extend(["", "## Unassigned Assets", ""])
        for row in data["accounting_gaps"]:
            lines.append(
                f"- {row['asset_id']} {row['asset']}: reachability={row['reachability']}; disposition=unassigned")
    if data["empty_columns"]:
        lines.extend(["", "## Empty Columns", ""])
        for g in data["empty_columns"]:
            st = data["column_stats"][g]
            lines.append(f"- {g}: 0/{st['applicable']} applicable assets tested")
    if data["row_gaps"]:
        lines.extend(["", "## Sparse Rows", ""])
        for r in data["row_gaps"]:
            lines.append(f"- {r['asset']}: {r['tested']}/{r['applicable']} applicable groups tested")
    if data.get("waivers"):
        lines.extend(["", "## Structured Waivers", ""])
        for w in data["waivers"]:
            ev = f"; evidence={w.get('evidence')}" if w.get("evidence") else ""
            lines.append(
                f"- {w.get('source')}: asset={w.get('asset')}; groups={', '.join(w.get('groups') or [])}; "
                f"reason={w.get('reason')}{ev}")
    return "\n".join(lines) + "\n"


def write_outputs(run_dir: Path) -> dict:
    data = derive(run_dir)
    state = run_dir / "state"
    state.mkdir(parents=True, exist_ok=True)
    (state / "coverage_matrix.json").write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (state / "coverage_matrix.md").write_text(render_markdown(data), encoding="utf-8")
    ledger = {
        "schema": "xunji.asset_ledger.v1",
        "source": data.get("source"),
        "summary": data.get("summary"),
        "assets": [{
            key: row.get(key) for key in (
                "asset_id", "asset", "scope_status", "scope_authority",
                "scope_admission_id", "scope_prompt_sha256", "source",
                "reachability", "examined", "flags", "fronts",
                "assignments", "assignment_statuses", "tested", "inventory_verdict",
                "disposition", "accounted", "closure_ready",
            )
        } for row in data.get("rows", [])],
    }
    (state / "asset_ledger.json").write_text(
        json.dumps(ledger, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return data


def sync_coverage_json(run_dir: Path) -> dict:
    """Conservatively write Markdown-derived touch/verdict state into coverage.json.

    `coverage.json` starts as the recon/classification baseline. During an attack
    cycle the canonical records are still frontier/evidence/report, but leaving
    coverage at examined=0 makes reviewers think assets were never touched. This
    sync marks an asset examined only when its host is explicitly mentioned in a
    canonical run file. It writes a verdict only from a terminal front status;
    evidence/report mentions alone are touch signals, not dispositions.
    """
    cov_path, cov, warnings = _load_coverage(run_dir)
    if cov_path is None or not isinstance(cov, dict):
        return {"path": "", "changed": 0, "warnings": warnings}
    assets = [a for a in cov.get("assets", []) if isinstance(a, dict)]
    if not assets:
        return {"path": str(cov_path), "changed": 0, "warnings": warnings}

    data = derive(run_dir)
    rows = {str(r.get("asset") or ""): r for r in data.get("rows", []) if isinstance(r, dict)}
    front_status = {f["id"]: _coverage_status_token(str(f.get("status") or ""))
                    for f in _parse_front_blocks(run_dir)}
    ev_text = (run_dir / "evidence.md").read_text(encoding="utf-8", errors="replace") \
        if (run_dir / "evidence.md").exists() else ""
    report_text = (run_dir / "report.md").read_text(encoding="utf-8", errors="replace") \
        if (run_dir / "report.md").exists() else ""

    changed = 0
    for asset in assets:
        name = _asset_display(asset)
        if not name:
            continue
        row = rows.get(name)
        row_touched = bool(row and (row.get("fronts") or row.get("tested")))
        token_set = _host_tokens(name)
        evidence_touched = _mentions_any_host(ev_text, token_set)
        report_touched = _mentions_any_host(report_text, token_set)
        touched = row_touched or evidence_touched or report_touched
        if touched and asset.get("examined") is not True:
            asset["examined"] = True
            changed += 1

        verdict = ""
        if row:
            statuses = {_coverage_status_token(front_status.get(fid, "")) for fid in row.get("fronts", [])}
            statuses.discard("")
            if "confirmed" in statuses:
                verdict = "confirmed"
            elif "closed" in statuses:
                verdict = "closed"
            elif "deferred" in statuses:
                verdict = "deferred"
        current_verdict = str(asset.get("verdict") or "").strip()
        verdict_source = str(asset.get("verdict_source") or "").strip()
        # ac01b30 briefly emitted these mention-only pseudo-verdicts. They were
        # never part of the coverage schema and suppress workers that correctly
        # look for reachable assets with verdict=None, so migrate them away.
        if current_verdict in {"evidence-recorded", "reported"}:
            asset["verdict"] = None
            asset.pop("verdict_source", None)
            current_verdict = ""
            verdict_source = ""
            changed += 1
            warnings.append(
                f"{name}: removed legacy mention-only verdict; terminal frontier disposition still required")
        if verdict and (not current_verdict or verdict_source == "coverage_matrix_sync"):
            if current_verdict != verdict or verdict_source != "coverage_matrix_sync":
                asset["verdict"] = verdict
                asset["verdict_source"] = "coverage_matrix_sync"
                changed += 1
        elif not verdict and verdict_source == "coverage_matrix_sync":
            asset["verdict"] = None
            asset.pop("verdict_source", None)
            changed += 1

        tested_groups = sorted(row.get("tested") or []) if row else []
        tested_source = str(asset.get("tested_groups_source") or "").strip()
        if tested_groups:
            if asset.get("tested_groups") != tested_groups or tested_source != "coverage_matrix_sync":
                asset["tested_groups"] = tested_groups
                asset["tested_groups_source"] = "coverage_matrix_sync"
                changed += 1
        elif tested_source == "coverage_matrix_sync":
            asset.pop("tested_groups", None)
            asset.pop("tested_groups_source", None)
            changed += 1

    if changed:
        cov["total"] = len(assets)
        cov["examined"] = sum(1 for a in assets if a.get("examined") is True)
        cov["reachable"] = sum(1 for a in assets if a.get("reachable") is True)
        tmp = cov_path.with_name(cov_path.name + ".tmp")
        tmp.write_text(json.dumps(cov, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        tmp.replace(cov_path)
    return {
        "path": str(cov_path),
        "changed": changed,
        "examined": cov.get("examined", 0),
        "total": cov.get("total", len(assets)),
        "warnings": warnings,
    }


def _selftest() -> int:
    d = Path(tempfile.mkdtemp())
    run = d / "run"
    run.mkdir()
    (run / "coverage.json").write_text(json.dumps({"assets": [
        {"host": "a.example", "scope_status": "in", "reachable": True, "flags": ["LOGIN"]},
        {"host": "b.example", "scope_status": "review", "scope_authority": "",
         "scope_admission_id": "", "scope_prompt_sha256": "",
         "source": "setup-source-candidate", "reachable": True, "flags": ["SURFACE:API"]},
        {"host": "c.example", "reachable": True, "flags": ["SURFACE:URL_FETCH"]},
        {"host": "profile.example", "reachable": True, "title": "User profile"},
        {"host": "portal.example", "reachable": True, "title": "Admin API docs"},
        {"host": "asset-field.example", "reachable": True, "flags": ["LOGIN"]},
        {"host": "url-field.example", "port": 8443, "reachable": True, "flags": ["LOGIN"]},
        {"host": "evidence-only.example", "reachable": True, "flags": ["LOGIN"]},
        {"host": "status-only.example", "reachable": True, "flags": ["LOGIN"]},
        {"host": "low-cert.example", "reachable": True, "flags": ["LOGIN"]},
        {"host": "confounder.example", "reachable": True, "flags": ["SURFACE:API"]},
        {"host": "multi-a.example", "reachable": True, "flags": ["SURFACE:API"]},
        {"host": "multi-b.example", "reachable": True, "flags": ["SURFACE:API"]},
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
        "- Vectors tried: auth-bypass\n\n"
        "### F-006\n"
        "- Front: broad API batch\n"
        "- Assets: multi-a.example, multi-b.example\n"
        "- Status: probing\n"
        "- Vectors tried: SQLi, IDOR\n",
        encoding="utf-8",
    )
    (run / "evidence.md").write_text(
        "# Evidence Ledger\n\n"
        "## E-001\n"
        "- Action: checked evidence-only.example login boundary\n"
        "- Result: SSO auth-gate observed; 401 on unauth API\n"
        "- Certainty: 0.5\n"
        "- Supports: F-006\n\n"
        "## E-002\n"
        "- Action: checked status-only.example public page\n"
        "- Result: returned HTTP 401 text without boundary mechanism evidence\n"
        "- Certainty: 0.3\n\n"
        "## E-003\n"
        "- Action: checked low-cert.example login boundary\n"
        "- Result: SSO auth-gate clue from one redirect only\n"
        "- Certainty: 0.3\n\n"
        "## E-004\n"
        "- Action: checked confounder.example parameter handling\n"
        "- Result: normal validation response, no parameter anomaly\n"
        "- Note: false-positive confounder mentioned SQLi as an alternate hypothesis only\n"
        "- Certainty: 0.5\n\n"
        "## E-005\n"
        "- Action: tested a.example authentication boundary\n"
        "- Result: auth-gate bypass control rejected\n"
        "- Certainty: 0.5\n\n"
        "## E-006\n"
        "- Action: tested b.example API parameter controls\n"
        "- Result: SQLi injection control and IDOR swap both rejected\n"
        "- Certainty: 0.5\n\n"
        "## E-007\n"
        "- Action: tested asset-field.example authentication boundary\n"
        "- Result: auth-gate bypass control rejected\n"
        "- Certainty: 0.5\n\n"
        "## E-008\n"
        "- Action: tested url-field.example:8443 authentication boundary\n"
        "- Result: auth-gate bypass control rejected\n"
        "- Certainty: 0.5\n",
        encoding="utf-8")
    data = derive(run)
    warns, errors = check(run)
    closure_warns, closure_errors = check(run, closure=True)
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
    waiver_run = d / "waiver"
    waiver_run.mkdir()
    (waiver_run / "coverage.json").write_text(json.dumps({"assets": [
        {"host": "waived.example", "reachable": True, "flags": ["SURFACE:URL_FETCH"]},
    ]}), encoding="utf-8")
    (waiver_run / "frontier.md").write_text(
        "# Frontier\n\n"
        "## Deferred Fronts\n\n"
        "### F-001\n"
        "- Status: deferred\n"
        "- Coverage waiver: asset=waived.example; groups=SSRF; reason=URL fetch sink absent in saved body; evidence=E-001\n",
        encoding="utf-8")
    waiver_data = derive(waiver_run)
    waiver_warns, waiver_errors = check(waiver_run, closure=True)
    sync_run = d / "sync"
    sync_run.mkdir()
    (sync_run / "coverage.json").write_text(json.dumps({"assets": [
        {"host": "open.example", "reachable": True, "examined": False, "flags": ["LOGIN"], "verdict": None},
        {"host": "done.example", "reachable": True, "examined": False, "flags": ["LOGIN"], "verdict": None},
        {"host": "typeb.example", "reachable": True, "examined": False, "flags": ["LOGIN"], "verdict": None},
        {"host": "evidence-touch.example", "reachable": True, "examined": False, "flags": ["LOGIN"], "verdict": None},
        {"host": "report-touch.example", "reachable": True, "examined": False, "flags": ["LOGIN"], "verdict": None},
        {"host": "legacy-touch.example", "reachable": True, "examined": True, "flags": ["LOGIN"], "verdict": "reported"},
        {"host": "quiet.example", "reachable": True, "examined": False, "flags": ["LOGIN"], "verdict": None},
    ]}), encoding="utf-8")
    (sync_run / "frontier.md").write_text(
        "# Frontier\n\n"
        "## Open Fronts\n\n"
        "### F-001\n"
        "- Front: open.example login\n"
        "- Status: open\n"
        "- Vectors tried: auth-bypass\n\n"
        "## Deferred Fronts\n\n"
        "### F-002\n"
        "- Front: done.example login\n"
        "- Status: deferred\n"
        "- Vectors tried: auth-bypass\n\n"
        "## Closed Fronts\n\n"
        "### F-003\n"
        "- Front: typeb.example login\n"
        "- Status: closed_type_b\n"
        "- Vectors tried: auth-bypass\n",
        encoding="utf-8")
    (sync_run / "evidence.md").write_text(
        "# Evidence Ledger\n\n## E-001\n- Action: fetched evidence-touch.example landing page\n"
        "- Result: generic page only\n- Certainty: 0.3\n",
        encoding="utf-8")
    (sync_run / "report.md").write_text(
        "# Report\n\nInventory note: report-touch.example was seen but has no terminal disposition.\n",
        encoding="utf-8")
    sync_info = sync_coverage_json(sync_run)
    sync_cov = json.loads((sync_run / "coverage.json").read_text(encoding="utf-8"))
    sync_by_host = {a["host"]: a for a in sync_cov["assets"]}
    by_asset = {r["asset"]: r for r in data["rows"]}
    bad_by_asset = {r["asset"]: r for r in bad_cov_data["rows"]}
    waiver_by_asset = {r["asset"]: r for r in waiver_data["rows"]}
    checks = [
        ("scope admission status survives canonical coverage derivation",
         by_asset["a.example"]["scope_status"] == "in"
         and by_asset["b.example"]["scope_status"] == "review"),
        ("scope authority and source metadata survive canonical derivation",
         by_asset["b.example"]["source"] == "setup-source-candidate"
         and "scope_admission_id" in by_asset["b.example"]
         and "scope_prompt_sha256" in by_asset["b.example"]),
        ("all in-scope assets stay in ledger with unreachable explicitly accounted",
         by_asset["d.example"]["disposition"] == "unreachable-baseline"
         and all(v == "not_applicable" for v in by_asset["d.example"]["cells"].values())),
        ("exact-host auth evidence fills Auth cell", by_asset["a.example"]["cells"]["Auth"] == "tested"),
        ("exact-host API evidence fills Injection and IDOR", by_asset["b.example"]["cells"]["Injection"] == "tested"
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
        ("evidence-derived auth test fills matrix without Vectors tried",
         by_asset["evidence-only.example"]["cells"]["Auth"] == "tested"),
        ("bare HTTP status text does not fill Auth coverage",
         by_asset["status-only.example"]["cells"]["Auth"] == "untested"),
        ("low-certainty evidence does not fill Auth coverage",
         by_asset["low-cert.example"]["cells"]["Auth"] == "untested"),
        ("confounder note does not fill Injection coverage",
         by_asset["confounder.example"]["cells"]["Injection"] == "untested"),
        ("multi-asset front vectors never copy one probe across the whole asset batch",
         by_asset["multi-a.example"]["cells"]["Injection"] == "untested"
         and by_asset["multi-b.example"]["cells"]["IDOR"] == "untested"
         and any("front-level Vectors tried" in warning for warning in data["warnings"])),
        ("partial per-asset group coverage remains closure debt",
         by_asset["evidence-only.example"]["disposition"] == "tested-partial"
         and not by_asset["evidence-only.example"]["closure_ready"]),
        ("corrupt primary coverage warns while using nested coverage",
         "nested.example" in bad_by_asset and bad_cov_warns and not bad_cov_errors),
        ("structured coverage waiver marks cell waived",
         waiver_by_asset["waived.example"]["cells"]["SSRF"] == "waived"
         and waiver_data["empty_columns"] == []
         and waiver_warns == [] and waiver_errors == []),
        ("structured coverage waiver renders reason",
         "Coverage waiver" not in "\n".join(waiver_data.get("warnings", []))
         and "Structured Waivers" in render_markdown(waiver_data)
         and "URL fetch sink absent" in render_markdown(waiver_data)),
        ("check reports warnings only", warns and not errors),
        ("closure check upgrades matrix gaps to errors", bool(closure_errors)),
        ("state outputs and full asset ledger are written",
         (run / "state" / "coverage_matrix.json").exists()
         and (run / "state" / "coverage_matrix.md").exists()
         and (run / "state" / "asset_ledger.json").exists()),
        ("sync coverage marks touched assets examined",
         sync_info["changed"] >= 2
         and sync_by_host["open.example"]["examined"] is True
         and sync_by_host["done.example"]["examined"] is True
         and sync_by_host["typeb.example"]["examined"] is True
         and sync_by_host["quiet.example"]["examined"] is False),
        ("sync coverage only writes terminal verdicts",
         sync_by_host["open.example"].get("verdict") is None
         and sync_by_host["done.example"].get("verdict") == "deferred"
         and sync_by_host["typeb.example"].get("verdict") == "closed"
         and sync_by_host["done.example"].get("verdict_source") == "coverage_matrix_sync"),
        ("evidence/report mentions mark examined but never invent verdicts",
         sync_by_host["evidence-touch.example"]["examined"] is True
         and sync_by_host["evidence-touch.example"].get("verdict") is None
         and sync_by_host["report-touch.example"]["examined"] is True
         and sync_by_host["report-touch.example"].get("verdict") is None),
        ("legacy mention-only pseudo-verdict is migrated away",
         sync_by_host["legacy-touch.example"].get("verdict") is None
         and any("legacy mention-only verdict" in w for w in sync_info["warnings"])),
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
    ap.add_argument("--sync-coverage", action="store_true",
                    help="conservatively sync Markdown-derived examined/verdict fields into coverage.json")
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
    if args.sync_coverage:
        data["coverage_sync"] = sync_coverage_json(run_dir)
    if args.json:
        print(json.dumps(data, ensure_ascii=False, indent=2))
    else:
        print(render_markdown(data), end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
