#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""饱和度计算 —— 衡量每个前沿的已尝试 vuln-class 覆盖度, 防止机械重试同一条死路。

check_run.py 在收口检查中调用 check_saturation(); 该函数从 frontier.md 解析
`Vectors tried:` / `Untried classes:`, 合并 constraints.md 的 ruled-out 类别,
计算 sat = tried / (tried + untried)。高饱和度 + 多约束 = 建议降级 Type B。

CLI 用法:
  python tools/saturation.py runs/<dir>                  # 全量饱和度报告
  python tools/saturation.py runs/<dir> --front F-001    # 单 front 详细报告
  python tools/saturation.py runs/<dir> --suggest        # JSON 输出, 供 workers.py 消费
  python tools/saturation.py runs/<dir> --merge          # 扫描 agents/*.md 的 New Constraints 块
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import tempfile
from pathlib import Path

import canonical_records

try:
    sys.stdout.reconfigure(encoding="utf-8")       # type: ignore[attr-defined]
except Exception:
    pass

ROOT = Path(__file__).resolve().parents[1]
HWS = r"[^\S\n]"

# ---------------------------------------------------------------------------
# 内置映射表: 攻击面子类型 → 适用的 vuln class canonical 名称
# 来源: docs/WORKFLOW.md L314-319 (Depth covers the applicable vuln classes per surface)
# ---------------------------------------------------------------------------
SURFACE_VULN_CLASSES: dict[str, list[str]] = {
    "login": [
        "auth-bypass", "SQLi-login", "enum", "default-creds",
        "horizontal privilege-escalation", "vertical privilege-escalation",
    ],
    "param-api": [
        "SQLi", "OS command injection", "SSTI", "deserialization",
        "IDOR", "SSRF", "mass-assignment",
    ],
    "upload": [
        "upload-to-shell", "path traversal", "XXE",
    ],
    "url-fetch": [
        "SSRF", "open redirect",
    ],
    "admin": [
        "unauthenticated access", "default-creds", "debug / admin interface exposure",
    ],
    "actuator": [
        "unauthenticated access", "default-creds", "debug / admin interface exposure",
    ],
    "swagger": [
        "unauthenticated access", "default-creds", "debug / admin interface exposure",
    ],
    "sso": [
        "SSO / OAuth / SAML flaws", "open redirect",
    ],
    "oauth": [
        "SSO / OAuth / SAML flaws", "open redirect",
    ],
    "file-download": [
        "path traversal", "arbitrary file read",
    ],
    "exposure": [
        "source / sourcemap leak", "hardcoded secrets / tokens",
        "debug / admin interface exposure",
    ],
}

# ---------------------------------------------------------------------------
# 类别名别名标准化字典: 将常见变体映射到 knowledge/_lexicon.md 的 canonical name
# ---------------------------------------------------------------------------
_CANONICAL_MAP: dict[str, str] = {
    # auth 家族
    "auth bypass": "auth-bypass",
    "auth-bypass": "auth-bypass",
    "authentication bypass": "auth-bypass",
    "sqli-login": "SQLi-login",
    "sqli in login": "SQLi-login",
    "login sqli": "SQLi-login",
    "enum": "enum",
    "enumeration": "enum",
    "user enumeration": "enum",
    "default creds": "default-creds",
    "default credentials": "default-creds",
    "weak credentials": "default-creds",
    "default / weak credentials": "default-creds",
    "horizontal privilege-escalation": "horizontal privilege-escalation",
    "horizontal priv esc": "horizontal privilege-escalation",
    "idor": "IDOR",
    "horizontal authz bypass": "IDOR",
    "bola": "IDOR",
    "vertical privilege-escalation": "vertical privilege-escalation",
    "vertical priv esc": "vertical privilege-escalation",
    "bfla": "vertical privilege-escalation",
    "privilege escalation": "vertical privilege-escalation",

    # injection 家族
    "sqli": "SQLi",
    "sql injection": "SQLi",
    "sql inject": "SQLi",
    "nosqli": "NoSQLi",
    "nosql injection": "NoSQLi",
    "os command injection": "OS command injection",
    "command injection": "OS command injection",
    "shell injection": "OS command injection",
    "cmd injection": "OS command injection",
    "code injection": "Code / expression injection",
    "expression injection": "Code / expression injection",
    "ssti": "SSTI",
    "template injection": "SSTI",
    "server-side template injection": "SSTI",
    "ldap injection": "LDAP / XPath / CRLF / HTTP-header / SMTP / ORM injection",
    "xpath injection": "LDAP / XPath / CRLF / HTTP-header / SMTP / ORM injection",
    "crlf injection": "LDAP / XPath / CRLF / HTTP-header / SMTP / ORM injection",
    "header injection": "LDAP / XPath / CRLF / HTTP-header / SMTP / ORM injection",

    # server-side
    "ssrf": "SSRF",
    "deserialization": "deserialization",
    "deser": "deserialization",
    "xxe": "XXE",
    "xml external entity": "XXE",
    "upload-to-shell": "upload-to-shell",
    "upload shell": "upload-to-shell",
    "file upload": "upload-to-shell",
    "file upload → shell": "upload-to-shell",
    "path traversal": "path traversal",
    "directory traversal": "path traversal",
    "lfi": "path traversal",
    "rfi": "path traversal",
    "arbitrary file read": "arbitrary file read/write/delete/download",
    "arbitrary file write": "arbitrary file read/write/delete/download",
    "arbitrary file delete": "arbitrary file read/write/delete/download",
    "arbitrary file download": "arbitrary file read/write/delete/download",
    "rce": "RCE chain / getshell",
    "rce chain": "RCE chain / getshell",
    "getshell": "RCE chain / getshell",

    # client-side
    "xss": "XSS",
    "reflected xss": "XSS",
    "stored xss": "XSS",
    "dom xss": "XSS",
    "csrf": "CSRF",
    "cors": "CORS misconfiguration",
    "cors misconfig": "CORS misconfiguration",
    "clickjacking": "clickjacking / postMessage / prototype pollution",
    "postmessage": "clickjacking / postMessage / prototype pollution",
    "open redirect": "open redirect",

    # info disclosure
    "source leak": "source / sourcemap leak",
    "sourcemap leak": "source / sourcemap leak",
    "vcs leak": "VCS leak",
    "git leak": "VCS leak",
    "backup files": "backup / temp files",
    "debug exposure": "debug / admin interface exposure",
    "admin interface exposure": "debug / admin interface exposure",
    "actuator exposure": "debug / admin interface exposure",
    "swagger exposure": "debug / admin interface exposure",
    "hardcoded secrets": "hardcoded secrets / tokens",
    "hardcoded tokens": "hardcoded secrets / tokens",
    "directory listing": "directory listing / error stack",

    # components
    "unauthenticated services": "unauthenticated services",
    "known component cve": "known component CVE",
    "cve": "known component CVE",
    "n-day": "known component CVE",
    "middleware bypass": "middleware / parsing quirks",
    "waf bypass": "middleware / parsing quirks",

    # SSO / OAuth
    "sso flaws": "SSO / OAuth / SAML flaws",
    "oauth flaws": "SSO / OAuth / SAML flaws",
    "saml flaws": "SSO / OAuth / SAML flaws",

    # business logic
    "race condition": "race / TOCTOU",
    "toctou": "race / TOCTOU",
    "flow bypass": "flow bypass",
    "replay": "replay",

    # cloud
    "metadata ssrf": "metadata SSRF",
    "imds": "metadata SSRF",
    "storage bucket exposure": "storage bucket exposure",

    # mass-assignment (not in lexicon as top-level but referenced in WORKFLOW)
    "mass-assignment": "mass-assignment",
    "mass assignment": "mass-assignment",
}

# 受控词汇: Why blocked 的合法值
_VALID_WHY_BLOCKED = {
    "WAF-signature", "app-reject", "timeout", "auth-gate",
    "rate-limit", "egress-block", "false-positive", "other",
}


def _field(text: str, name: str) -> str:
    """从 markdown 块中提取 `- Name: value` 字段值(单行)。"""
    m = re.search(rf"(?im)^{HWS}*[-*]?{HWS}*{re.escape(name)}{HWS}*[:：]{HWS}*([^\n]*)", text)
    return m.group(1).strip() if m else ""


def _canonical(name: str) -> str:
    """将类别名标准化到 knowledge/_lexicon.md 的 canonical name。"""
    key = name.strip().lower().rstrip(".,;: ")
    if not key:
        return ""
    # 精确命中
    if key in _CANONICAL_MAP:
        return _CANONICAL_MAP[key]
    # 模糊匹配: 对长名用 in 匹配
    for alias, canon in _CANONICAL_MAP.items():
        if key == alias or (len(key) > 6 and (key in alias or alias in key)):
            return canon
    # 返回原始名(未识别, 但保留)
    return name.strip()


def _parse_list_field(text: str, name: str) -> list[str]:
    """解析 `- Name: a, b, c` 或 `- Name: a; b; c` 格式的列表字段。"""
    raw = _field(text, name)
    if not raw:
        return []
    # 按逗号或分号拆分
    parts = re.split(r"[;,]", raw)
    return [p.strip().rstrip(".,;: ") for p in parts if p.strip()]


_NA_RE = re.compile(
    r"(?i)(?:\bN/?A\b|\bnot[ -]?applicable\b|\bnot\s+relevant\b|"
    r"\bwaiv(?:e|ed|er)\b|不适用|不適用|不涉及|不需要|无需|無需|"
    r"无适用|無適用|忽略|跳过|跳過)"
)


def _strip_na_reason(item: str) -> tuple[str, str]:
    """Return (class text, waiver reason) for entries like `SQLi-login (N/A - captcha)`.

    Driver-maintained `Untried classes:` often carries a concise reason inline.
    If that inline note says N/A/not-applicable, it is a structured waiver for
    saturation math rather than an untried class.
    """
    raw = item.strip().rstrip(".,;: ")
    if not raw:
        return "", ""
    reason = ""
    for m in re.finditer(r"[\(\[][^\)\]]*[\)\]]", raw):
        chunk = m.group(0).strip("()[] ").strip()
        if _NA_RE.search(chunk):
            reason = chunk
            raw = (raw[:m.start()] + raw[m.end():]).strip()
            break
    if not reason and _NA_RE.search(raw):
        parts = re.split(r"\s+(?:--|-|—|–|:)\s+", raw, maxsplit=1)
        if len(parts) == 2:
            raw, reason = parts[0].strip(), parts[1].strip()
        else:
            reason = raw
            raw = _NA_RE.sub("", raw).strip()
    return raw.rstrip(".,;: "), reason


def _parse_class_field(text: str, name: str) -> tuple[list[str], dict[str, str]]:
    """Parse class list fields, returning active classes plus explicit N/A waivers."""
    raw = _field(text, name)
    if not raw:
        return [], {}
    classes: list[str] = []
    waivers: dict[str, str] = {}
    for part in re.split(r"[;,]", raw):
        cls_raw, reason = _strip_na_reason(part)
        cls = _canonical(cls_raw)
        if not cls:
            continue
        if reason:
            waivers[cls] = reason
        else:
            classes.append(cls)
    return classes, waivers


def _front_sections(text: str) -> list[tuple[str, str]]:
    """将 frontier.md 按 ## 标题拆分, 返回 (section_name, body) 对。"""
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


def _parse_front_blocks(text: str) -> list[dict]:
    """解析 frontier.md 中所有 ### F-XXX 块, 返回 dict 列表。跳过 Closed Fronts 区段。"""
    sections = _front_sections(text)
    blocks: list[dict] = []
    for section, body in sections:
        # 跳过 Closed Fronts 区段
        if section.lower().startswith("closed"):
            continue
        for m in re.finditer(r"(?ms)^###[ \t]+(F-\d+).*?(?=^###[ \t]+F-\d+|\Z)", body):
            block_text = m.group(0)
            fid = m.group(1)
            status = (_field(block_text, "Status") or section).lower()
            status_tokens = set(re.findall(r"[a-z0-9_]+", status.replace("-", "_")))
            if status_tokens & {"closed", "closing", "final", "done", "complete", "completed", "blocked_type_b"}:
                continue
            blocks.append({
                "id": fid,
                "section": section,
                "status": status,
                "text": block_text,
            })
    return blocks


def _parse_constraints(run_dir: Path) -> list[dict]:
    """Parse constraints once, then normalize the one owned mechanism field."""
    rows = canonical_records.parse_constraints(run_dir)
    for row in rows:
        row["mechanism_class"] = _canonical(row.get("mechanism_class", ""))
    return rows


def _infer_surface_subtype(front_block: str) -> str | None:
    """从 front 块推断攻击面子类型。
    优先级: 显式 Surface subtype 字段 → Front: 行关键词 → Barrier class → None
    """
    # 1. 显式字段
    subtype = _field(front_block, "Surface subtype")
    if subtype:
        return subtype.lower()

    # 2. Front: 行关键词匹配
    front_line = _field(front_block, "Front")
    combined = (front_line + " " + front_block).lower()

    keywords = [
        ("login", "login"), ("param-api", "param-api"), ("api", "param-api"),
        ("upload", "upload"), ("url-fetch", "url-fetch"), ("fetch", "url-fetch"),
        ("admin", "admin"), ("actuator", "actuator"), ("swagger", "swagger"),
        ("sso", "sso"), ("oauth", "oauth"), ("saml", "sso"),
        ("file-download", "file-download"), ("download", "file-download"),
        ("exposure", "exposure"),
    ]
    for kw, st in keywords:
        if kw in combined:
            return st

    # 3. Barrier class 推断
    barrier = _field(front_block, "Barrier class").lower()
    if "auth" in barrier:
        return "login"
    if "waf" in barrier:
        return None  # WAF 本身不推断具体子类型

    return None


def compute(front_block: str, constraints: list[dict]) -> dict:
    """计算单个 front 的饱和度。

    从 front_block 解析 Vectors tried: 和 Untried classes: 字段,
    合并 constraints 中的 mechanism classes,
    返回 {ratio, tried_count, untried_count, denominator_source, tried_list, untried_list, surface}
    """
    front_id = ""
    fm = re.match(r"###\s+(F-\d+)", front_block.strip())
    if fm:
        front_id = fm.group(1)

    # 解析 Vectors tried (已尝试的向量)
    tried_classes, tried_waivers = _parse_class_field(front_block, "Vectors tried")
    tried: set[str] = {t for t in tried_classes if t}
    waived: dict[str, str] = dict(tried_waivers)

    # 从 constraints 中提取该 front 的所有 mechanism classes
    front_constraints = [c for c in constraints if c.get("front") == front_id]
    for c in front_constraints:
        mc = _canonical(c.get("mechanism_class", ""))
        if mc:
            tried.add(mc)

    # 解析 Untried classes。显式 N/A / not-applicable 标注从分母里移除,
    # 否则 driver 写了正确解释仍会被计成低饱和。
    untried_classes, untried_waivers = _parse_class_field(front_block, "Untried classes")
    waived.update(untried_waivers)
    untried_set: set[str] = {u for u in untried_classes if u}

    surface = None
    denominator_source = "estimated"

    if untried_set:
        # Driver 显式维护了 Untried classes
        untried = untried_set - tried - set(waived)
        denominator_source = "driver" if not waived else "driver+n/a"
    else:
        # 用内置映射表兜底
        surface = _infer_surface_subtype(front_block)
        if surface and surface in SURFACE_VULN_CLASSES:
            applicable = {_canonical(c) for c in SURFACE_VULN_CLASSES[surface]}
            applicable.discard("")
            untried = applicable - tried - set(waived)
        else:
            # 无法推断 → ratio=None
            return {
                "front": front_id,
                "ratio": None,
                "tried_count": len(tried),
                "untried_count": 0,
                "denominator_source": "unknown",
                "tried_list": sorted(tried),
                "untried_list": [],
                "waived_list": sorted(waived),
                "waiver_reasons": waived,
                "surface": surface,
            }

    tried_count = len(tried)
    untried_count = len(untried)
    total = tried_count + untried_count
    ratio = tried_count / total if total > 0 else None

    return {
        "front": front_id,
        "ratio": ratio,
        "tried_count": tried_count,
        "untried_count": untried_count,
        "waived_count": len(waived),
        "denominator_source": denominator_source,
        "tried_list": sorted(tried),
        "untried_list": sorted(untried),
        "waived_list": sorted(waived),
        "waiver_reasons": waived,
        "surface": surface,
    }


def check(run_dir: Path) -> tuple[list[str], list[str]]:
    """检查 run 目录下所有 Open/Deferred front 的饱和度, 返回 (warns, errors)。"""
    fr = run_dir / "frontier.md"
    if not fr.exists():
        return [], []

    text = fr.read_text(encoding="utf-8", errors="replace")
    blocks = _parse_front_blocks(text)
    constraints = _parse_constraints(run_dir)

    warns: list[str] = []
    errors: list[str] = []

    for b in blocks:
        result = compute(b["text"], constraints)
        if result["ratio"] is None:
            continue

        fid = result["front"]
        sat = result["ratio"]
        tried = result["tried_count"]
        untried = result["untried_count"]
        source = result["denominator_source"]

        # 统计该 front 的约束数量
        front_constraint_count = sum(1 for c in constraints if c.get("front") == fid)

        if sat < 0.3:
            warns.append(
                f"饱和度严重不足: {fid} sat={sat:.0%} (tried={tried}, untried={untried}, "
                f"来源={source}) —— 大量 vuln class 未尝试, 请扩展覆盖面后再考虑收口。")
        elif sat < 0.6:
            warns.append(
                f"饱和度偏低: {fid} sat={sat:.0%} (tried={tried}, untried={untried}, "
                f"来源={source}) —— 仍有多类 vuln class 未覆盖。")

        if sat >= 0.75 and front_constraint_count >= tried:
            warns.append(
                f"接近饱和: {fid} sat={sat:.0%} (tried={tried}, constraints={front_constraint_count}) "
                f"—— 大部分向量已受阻, 建议评估是否降级 Type B。")

    return warns, errors


def front_saturation(run_dir: Path) -> list[dict]:
    """Return saturation records for all open/deferred fronts in a run.

    Public helper for derived-state tools. It keeps Markdown canonical and does
    not write any files.
    """
    fr = run_dir / "frontier.md"
    if not fr.exists():
        return []
    text = fr.read_text(encoding="utf-8", errors="replace")
    constraints = _parse_constraints(run_dir)
    return [compute(block["text"], constraints) for block in _parse_front_blocks(text)]


def _scan_agent_new_constraints(run_dir: Path) -> list[dict]:
    """扫描 agents/*.md 中的 ## New Constraints 块, 提取建议的约束条目。"""
    agents_dir = run_dir / "agents"
    if not agents_dir.exists():
        return []

    suggestions: list[dict] = []
    for f in sorted(agents_dir.glob("A-*.md")):
        text = f.read_text(encoding="utf-8", errors="replace")
        # 找到 ## New Constraints 节
        m = re.search(r"(?ims)^##\s+New Constraints\s*$(.*?)(?=^##\s|\Z)", text)
        if not m:
            continue
        body = m.group(1)
        # 解析每个 ### NC-x 块
        for nc_m in re.finditer(r"(?ms)^###[ \t]+(NC-\d+).*?(?=^###[ \t]+NC-\d+|\Z)", body):
            nc_block = nc_m.group(0)
            nc_id = nc_m.group(1)
            suggestions.append({
                "agent": f.stem,
                "nc_id": nc_id,
                "mechanism_class": _field(nc_block, "Mechanism class"),
                "input_shape": _field(nc_block, "Input shape"),
                "why_blocked": _field(nc_block, "Why blocked"),
                "evidence": _field(nc_block, "Evidence"),
                "ruled_out": _field(nc_block, "Ruled out"),
            })
    return suggestions


# ---------------------------------------------------------------------------
# CLI 入口
# ---------------------------------------------------------------------------
def _resolve_run_dir(path: str | Path) -> Path:
    p = Path(path)
    return (p if p.is_absolute() else ROOT / p).resolve()


def _print_full_report(run_dir: Path) -> int:
    """--default: 打印全量饱和度报告。"""
    fr = run_dir / "frontier.md"
    if not fr.exists():
        print("[saturation] frontier.md 不存在")
        return 1

    text = fr.read_text(encoding="utf-8", errors="replace")
    blocks = _parse_front_blocks(text)
    constraints = _parse_constraints(run_dir)

    if not blocks:
        print("[saturation] 无 Open/Deferred front")
        return 0

    print(f"[saturation] {len(blocks)} 个 front, {len(constraints)} 条约束\n")
    for b in blocks:
        result = compute(b["text"], constraints)
        fid = result["front"]
        sat = result["ratio"]
        if sat is None:
            print(f"  {fid}: sat= ? (无法推断表面子类型, 无法计算)")
        else:
            print(f"  {fid}: sat={sat:.0%} tried={result['tried_count']} "
                  f"untried={result['untried_count']} waived={result.get('waived_count', 0)} "
                  f"source={result['denominator_source']}")
            if result["tried_list"]:
                print(f"    tried: {', '.join(result['tried_list'][:8])}")
            if result["untried_list"]:
                print(f"    untried: {', '.join(result['untried_list'][:8])}")
            if result.get("waived_list"):
                print(f"    waived: {', '.join(result['waived_list'][:8])}")
    return 0


def _print_front_detail(run_dir: Path, front_id: str) -> int:
    """--front: 单 front 详细报告。"""
    fr = run_dir / "frontier.md"
    if not fr.exists():
        print(f"[saturation] frontier.md 不存在")
        return 1

    text = fr.read_text(encoding="utf-8", errors="replace")
    m = re.search(rf"(?ms)^###[ \t]+{re.escape(front_id)}\b.*?(?=^###[ \t]+F-\d+|\Z)", text)
    if not m:
        print(f"[saturation] front {front_id} 未找到")
        return 1

    constraints = _parse_constraints(run_dir)
    result = compute(m.group(0), constraints)

    print(f"[saturation] {front_id} 详细报告")
    print(f"  饱和度: {result['ratio']:.0%}" if result["ratio"] is not None else "  饱和度: ? (无法计算)")
    print(f"  已尝试: {result['tried_count']}")
    print(f"  未尝试: {result['untried_count']}")
    print(f"  不适用: {result.get('waived_count', 0)}")
    print(f"  分母来源: {result['denominator_source']}")
    print(f"  表面子类型: {result['surface'] or '未推断'}")

    if result["tried_list"]:
        print(f"  已尝试类别:")
        for t in result["tried_list"]:
            print(f"    - {t}")
    if result["untried_list"]:
        print(f"  未尝试类别:")
        for u in result["untried_list"]:
            print(f"    - {u}")
    if result.get("waived_list"):
        reasons = result.get("waiver_reasons") or {}
        print("  不适用类别:")
        for w in result["waived_list"]:
            reason = f" ({reasons.get(w)})" if reasons.get(w) else ""
            print(f"    - {w}{reason}")

    # 该 front 的约束
    front_constraints = [c for c in constraints if c.get("front") == front_id]
    if front_constraints:
        print(f"  约束记录 ({len(front_constraints)} 条):")
        for c in front_constraints:
            print(f"    [{c['id']}] {c['mechanism_class']} on {c['input_shape']}")
            print(f"      Why blocked: {c['why_blocked']}")
            print(f"      Ruled out: {c['ruled_out']}")
    return 0


def _print_suggest(run_dir: Path) -> int:
    """--suggest: JSON 输出, 供 workers.py suggest 消费。"""
    fr = run_dir / "frontier.md"
    if not fr.exists():
        print("[]")
        return 0

    text = fr.read_text(encoding="utf-8", errors="replace")
    blocks = _parse_front_blocks(text)
    constraints = _parse_constraints(run_dir)

    items: list[dict] = []
    for b in blocks:
        result = compute(b["text"], constraints)
        sat = result["ratio"]
        fid = result["front"]

        # 计算 penalty: 基于饱和度给一个班次分数(供 workers.py suggest 调节)
        if sat is None:
            penalty = 0
        elif sat < 0.3:
            penalty = 2  # 饱和度低 → 还有很多可试 → 加分
        elif sat < 0.6:
            penalty = 0  # 正常
        elif sat < 0.75:
            penalty = -1  # 略高 → 轻微扣分
        else:
            penalty = -2  # 接近饱和 → 扣分

        items.append({
            "front": fid,
            "saturation": round(sat, 2) if sat is not None else None,
            "penalty": penalty,
        })

    print(json.dumps(items, ensure_ascii=False, indent=2))
    return 0


def _print_merge(run_dir: Path) -> int:
    """--merge: 扫描 agents/*.md 的 New Constraints 块, 输出建议的 C-xxx。"""
    suggestions = _scan_agent_new_constraints(run_dir)
    if not suggestions:
        print("[saturation merge] 无 agents/*.md 中的 New Constraints 块")
        return 0

    # 确定起始 C-id
    existing = _parse_constraints(run_dir)
    existing_ids = {c["id"] for c in existing}
    next_n = 1
    while f"C-{next_n:03d}" in existing_ids:
        next_n += 1

    print(f"[saturation merge] 从 {len(suggestions)} 个 agent 中找到 New Constraints 建议\n")
    print("# 以下条目建议合并到 constraints.md\n")
    for i, s in enumerate(suggestions):
        cid = f"C-{next_n + i:03d}"
        print(f"## {cid}")
        print(f"- Front: (agent={s['agent']}, 需 Root 确认)")
        print(f"- Mechanism class: {_canonical(s['mechanism_class'])}")
        print(f"- Input shape: {s['input_shape']}")
        print(f"- Why blocked: {s['why_blocked']}")
        print(f"- Evidence: {s['evidence']}")
        print(f"- Ruled out: {s['ruled_out']}")
        print()

    print("# 请 Root 逐条确认后手动合并到 constraints.md")
    return 0


def _selftest() -> int:
    d = Path(tempfile.mkdtemp())
    empty = d / "empty"
    empty.mkdir()
    run = d / "run"
    run.mkdir()
    (run / "frontier.md").write_text(
        "# Frontier\n"
        "## Open Fronts\n"
        "### F-001\n"
        "- Front: login boundary\n"
        "- Status: open\n"
        "- Surface subtype: login\n"
        "- Vectors tried: auth bypass\n"
        "- Untried classes: SQLi-login, enum, default-creds\n\n"
        "### F-002\n"
        "- Front: api params\n"
        "- Status: open\n"
        "- Surface subtype: param-api\n"
        "- Vectors tried: SQLi, IDOR\n"
        "- Untried classes: SSRF\n\n"
        "### F-004\n"
        "- Front: captcha login\n"
        "- Status: open\n"
        "- Surface subtype: login\n"
        "- Vectors tried: auth bypass\n"
        "- Untried classes: SQLi-login (N/A - CAPTCHA blocks form submission), enum (not applicable: no username field), default-creds, SSRF (不涉及: no outbound fetch)\n\n"
        "### F-003\n"
        "- Front: terminal but misplaced\n"
        "- Status: blocked_type_b\n"
        "- Surface subtype: login\n"
        "- Vectors tried: auth bypass\n"
        "- Untried classes: enum\n\n"
        "## Closed Fronts\n"
        "### F-099\n"
        "- Front: closed login\n"
        "- Status: closed\n"
        "- Surface subtype: login\n"
        "- Vectors tried: auth bypass\n"
        "- Untried classes: enum\n",
        encoding="utf-8",
    )
    (run / "constraints.md").write_text(
        "## C-001\n"
        "- Front: F-002\n"
        "- Mechanism class: SSRF\n"
        "- Input shape: api-param\n"
        "- Why blocked: auth-gate\n"
        "- Evidence: local fixture\n"
        "- Ruled out: yes\n",
        encoding="utf-8",
    )

    blocks = _parse_front_blocks((run / "frontier.md").read_text(encoding="utf-8"))
    constraints = _parse_constraints(run)
    f1 = compute(blocks[0]["text"], constraints)
    f2 = compute(blocks[1]["text"], constraints)
    f4 = compute(blocks[2]["text"], constraints)
    derived = front_saturation(run)

    import io
    import contextlib
    with contextlib.redirect_stdout(io.StringIO()) as suggest_buf:
        suggest_exit = _print_suggest(run)
    suggest_items = json.loads(suggest_buf.getvalue())
    with contextlib.redirect_stdout(io.StringIO()):
        empty_exit = _print_full_report(empty)
        full_exit = _print_full_report(run)
        detail_exit = _print_front_detail(run, "F-001")
    warns, errors = check(run)

    checks = [
        ("empty run without frontier returns 1", empty_exit == 1),
        ("closed fronts are excluded", all(b["id"] != "F-099" for b in blocks)),
        ("terminal statuses outside Closed Fronts are excluded", all(b["id"] != "F-003" for b in blocks)),
        ("open front low saturation is computed", f1["front"] == "F-001" and round(f1["ratio"], 2) == 0.25),
        ("constraints count as tried", f2["front"] == "F-002" and f2["untried_count"] == 0),
        ("Untried classes N/A annotations are waived",
         f4["front"] == "F-004" and f4["untried_count"] == 1 and f4["waived_count"] == 3
         and round(f4["ratio"], 2) == 0.5),
        ("check emits low-saturation warning", any("F-001" in w for w in warns) and not errors),
        ("full report exits 0", full_exit == 0),
        ("front detail exits 0", detail_exit == 0),
        ("suggest exits 0", suggest_exit == 0),
        ("suggest output is stable json shape",
         suggest_items and {"front", "saturation", "penalty"} <= set(suggest_items[0])),
        ("public front_saturation helper returns records", derived and derived[0]["front"] == "F-001"),
    ]
    bad = [name for name, ok in checks if not ok]
    for name, ok in checks:
        print(("ok   " if ok else "FAIL ") + name)
    print("saturation selftest " + ("passed" if not bad else f"FAILED ({len(bad)})"))
    return 0 if not bad else 1


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)

    ap = argparse.ArgumentParser(description="饱和度计算 —— 衡量每个 front 的 vuln-class 覆盖度")
    ap.add_argument("run_dir", type=Path, nargs="?", help="run 目录路径")
    ap.add_argument("--front", metavar="F-ID", help="单 front 详细报告")
    ap.add_argument("--suggest", action="store_true", help="JSON 输出, 供 workers.py 消费")
    ap.add_argument("--merge", action="store_true", help="扫描 agents/*.md New Constraints 块")
    ap.add_argument("--selftest", action="store_true", help="run local regression tests")
    args = ap.parse_args(argv)

    if args.selftest:
        return _selftest()

    if args.run_dir is None:
        ap.error("run_dir is required")

    run_dir = _resolve_run_dir(args.run_dir)
    if not run_dir.exists():
        print(f"[saturation] run 目录不存在: {run_dir}", file=sys.stderr)
        return 1

    if args.front:
        return _print_front_detail(run_dir, args.front)
    if args.suggest:
        return _print_suggest(run_dir)
    if args.merge:
        return _print_merge(run_dir)

    return _print_full_report(run_dir)


if __name__ == "__main__":
    raise SystemExit(main())
