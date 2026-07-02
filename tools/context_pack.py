#!/usr/bin/env python3
"""Minimal context pack builder for Ultra-native Xunji agents.

Markdown run files remain canonical. This tool only copies a compact slice into
`context/*.md` or stdout so a subagent starts with the smallest useful board:
target scope, assigned front, nearby coverage/evidence, barriers, and role
boundaries. It never writes findings or canonical evidence.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
HWS = r"[^\S\n]"

try:
    sys.stdout.reconfigure(encoding="utf-8")       # type: ignore[attr-defined]
except Exception:
    pass

sys.path.insert(0, str(ROOT / "tools"))
try:
    import knowledge_match as _knowledge_match
except Exception:
    _knowledge_match = None
try:
    import xday_match as _xday_match
except Exception:
    _xday_match = None


ROLE_TEMPLATES = {
    "surface": "surface.md",
    "web": "web-hunter.md",
    "web-auth": "web-hunter.md",
    "web-hunter": "web-hunter.md",
    "code": "code-audit.md",
    "code-audit": "code-audit.md",
    "zhaoxuan": "code-audit.md",
    "exploit": "exploit.md",
    "exploit-construction": "exploit.md",
    "verify": "verify.md",
    "verification": "verify.md",
    "review": "review.md",
    "independent-review": "review.md",
    "report": "report.md",
    "synthesizer": "synthesizer.md",
}


def resolve_run_dir(path: str | Path) -> Path:
    p = Path(path)
    return (p if p.is_absolute() else ROOT / p).resolve()


def _read(path: Path, limit: int | None = None) -> str:
    if not path.exists():
        return ""
    text = path.read_text(encoding="utf-8", errors="replace")
    if limit is not None and len(text) > limit:
        return text[-limit:]
    return text


def _load_json(path: Path) -> dict:
    try:
        data = json.loads(path.read_text(encoding="utf-8", errors="replace"))
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def _field(text: str, name: str) -> str:
    m = re.search(rf"(?im)^{HWS}*[-*]?{HWS}*{re.escape(name)}{HWS}*[:：]{HWS}*([^\n]*)$", text)
    return m.group(1).strip() if m else ""


def _front_block(run_dir: Path, front_id: str) -> str:
    text = _read(run_dir / "frontier.md")
    m = re.search(rf"(?ms)^###{HWS}+{re.escape(front_id)}\b.*?(?=^###{HWS}+(?:F|H)-\d+\b|\Z)", text)
    return m.group(0).strip() if m else ""


def _assignment(run_dir: Path, agent_id: str) -> dict:
    data = _load_json(run_dir / "state" / "assignments.json")
    for item in data.get("assignments", []):
        if isinstance(item, dict) and item.get("agent") == agent_id:
            return item
    path = run_dir / "agents" / f"{agent_id}.md"
    text = _read(path)
    if text:
        return {
            "agent": agent_id,
            "role": _field(text, "Role"),
            "front": _field(text, "Assigned front"),
            "scope": _field(text, "Scope"),
        }
    return {}


def _coverage_rows(run_dir: Path, front_text: str, limit: int = 6) -> list[dict]:
    candidates = [run_dir / "coverage.json", *sorted(run_dir.glob("**/coverage.json"))]
    data: dict = {}
    for p in candidates:
        data = _load_json(p)
        if isinstance(data.get("assets"), list):
            break
    low = front_text.lower()
    rows: list[dict] = []
    for asset in data.get("assets", []) if isinstance(data.get("assets"), list) else []:
        if not isinstance(asset, dict):
            continue
        host = str(asset.get("host") or asset.get("asset") or asset.get("url") or "").strip()
        if host and re.search(rf"(?<![A-Za-z0-9._-]){re.escape(host.lower())}(?![A-Za-z0-9._-])", low):
            rows.append(asset)
    return rows[:limit]


def _kb_ids(front_text: str, coverage_rows: list[dict]) -> list[str]:
    ids: list[str] = []
    for raw in re.findall(r"\bkb:([A-Za-z0-9_-]+)\b", front_text):
        if raw not in ids:
            ids.append(raw)
    for asset in coverage_rows:
        stack = str(asset.get("stack") or "")
        if stack.startswith("kb:"):
            kid = stack.split(":", 1)[1].strip()
            if kid and kid not in ids:
                ids.append(kid)
    return ids


def _rel(path: Path) -> str:
    try:
        return str(path.resolve().relative_to(ROOT))
    except Exception:
        return str(path)


def _knowledge_xday_summary(kb_ids: list[str], *, kb_dir: Path | None = None,
                            xday_dir: Path | None = None,
                            weap_dir: Path | None = None) -> list[str]:
    lines: list[str] = []
    if not kb_ids:
        return ["- (no `kb:<id>` fingerprint matched this front; run `knowledge_match.py --body <saved>` when a saved response fingerprints a product)"]
    if _knowledge_match is None:
        return ["- (knowledge_match unavailable)"]
    kb_root = kb_dir or _knowledge_match.KB
    entries = {e.id: e for e in _knowledge_match.load_entries(kb_root)}
    stores = {}
    if _xday_match is not None:
        stores = _xday_match.load_local_stores(xday_dir or _xday_match.XDAY,
                                               weap_dir or _xday_match.WEAP)
    for kid in kb_ids[:6]:
        e = entries.get(kid)
        if e:
            sigs = ", ".join(e.sigs[:4]) + (" ..." if len(e.sigs) > 4 else "")
            lines.append(f"- knowledge `{kid}`: {e.product} ({e.maturity}); path={_rel(e.path)}; signatures={sigs}")
        else:
            lines.append(f"- knowledge `{kid}`: id referenced by front/coverage but no public grounding entry found")
        local = stores.get(kid, [])
        if local:
            for store in local[:3]:
                if store.get("kind") == "poc":
                    files = ", ".join(store.get("files", [])[:6])
                    lines.append(f"  - local xday pointer: {_rel(store['path'])}/ files={files}")
                else:
                    lines.append(f"  - local weaponized note pointer: {_rel(store['path'])}")
        else:
            lines.append("  - local xday: none indexed for this knowledge id")
    return lines


def _matching_blocks(text: str, prefix: str, needle: str, limit: int = 4) -> list[str]:
    if not text:
        return []
    rx = rf"(?ms)^##{HWS}+{prefix}-\d+.*?(?=^##{HWS}+{prefix}-\d+|\Z)"
    blocks = []
    low_needle = needle.lower()
    for m in re.finditer(rx, text):
        block = m.group(0).strip()
        if low_needle and low_needle in block.lower():
            blocks.append(block)
    return blocks[:limit]


def _recent_lines(text: str, max_lines: int = 20) -> str:
    lines = [ln for ln in text.splitlines() if ln.strip()]
    return "\n".join(lines[-max_lines:])


def _role_template_path(role: str) -> Path:
    fn = ROLE_TEMPLATES.get(role, f"{role}.md")
    return ROOT / "docs" / "templates" / "agents" / fn


def _load_front_constraints(run_dir: Path, front_id: str) -> list[dict]:
    """解析 constraints.md(如果存在), 返回该 front 的约束列表。"""
    path = run_dir / "constraints.md"
    if not path.exists():
        return []
    text = path.read_text(encoding="utf-8", errors="replace")
    constraints: list[dict] = []
    for m in re.finditer(r"(?ms)^##[ \t]+(C-\d+).*?(?=^##[ \t]+C-\d+|\Z)", text):
        block = m.group(0)
        cid = m.group(1)
        c_front = _field(block, "Front")
        if c_front != front_id:
            continue
        constraints.append({
            "id": cid,
            "mechanism_class": _field(block, "Mechanism class"),
            "input_shape": _field(block, "Input shape"),
            "why_blocked": _field(block, "Why blocked"),
            "ruled_out": _field(block, "Ruled out"),
        })
    return constraints


def _load_cross_run_context(run_dir: Path, front_id: str) -> list[str]:
    """提取该 front 的 barrier class 在历史 run 中的表现, 返回 context 行列表。"""
    fr = run_dir / "frontier.md"
    if not fr.exists():
        return []
    fr_text = fr.read_text(encoding="utf-8", errors="replace")

    # 找到该 front 的 barrier class
    barrier_class = ""
    fm = re.search(rf"(?ms)^###[ \t]+{re.escape(front_id)}\b.*?(?=^###[ \t]+F-\d+|\Z)", fr_text)
    if fm:
        barrier_class = _field(fm.group(0), "Barrier class")
    if not barrier_class or barrier_class == "none":
        return []

    # 归一化后调用 cross_run.py --barrier
    import subprocess
    cross_run_script = str(ROOT / "tools" / "cross_run.py")
    try:
        result = subprocess.run(
            [sys.executable, cross_run_script, "--barrier", barrier_class],
            capture_output=True, text=True, timeout=15,
        )
        if result.returncode != 0:
            return []
        output = result.stdout.strip()
        if not output or "未找到 barrier class" in output:
            return []
        # 截取前 30 行, 避免 context 膨胀
        lines_out = output.splitlines()[:30]
        return lines_out
    except Exception:
        return []


def build_pack(run_dir: Path, *, front: str, role: str, agent: str = "",
               kb_dir: Path | None = None, xday_dir: Path | None = None,
               weap_dir: Path | None = None) -> str:
    front_text = _front_block(run_dir, front)
    cov = _coverage_rows(run_dir, front_text)
    kb_ids = _kb_ids(front_text, cov)
    target = _read(run_dir / "target.md", 5000)
    evidence_matches = _matching_blocks(_read(run_dir / "evidence.md"), "E", front)
    fp_matches = _matching_blocks(_read(run_dir / "false_positive.md"), "FP", front)
    decisions_tail = _recent_lines(_read(run_dir / "decisions.md", 6000), 18)
    role_template = _role_template_path(role)
    role_text = _read(role_template, 5000)
    generated = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())

    lines = [
        f"# Context Pack {front} / {role}",
        "",
        f"- Generated: {generated}",
        f"- Run dir: {run_dir}",
        f"- Agent: {agent or '(unassigned)'}",
        f"- Assigned front: {front}",
        f"- Role: {role}",
        "- Canonical source: markdown run files; this pack is a read-only slice.",
        "- Maturity rule: subagent output is phenomenon/candidate only; Root Synthesizer owns findings.",
        "",
        "## Scope / Target",
        target.strip() or "(target.md missing)",
        "",
        "## Assigned Front",
        front_text or f"(front {front} not found in frontier.md)",
        "",
        "## Matched Coverage",
    ]
    if cov:
        for a in cov:
            host = a.get("host") or a.get("asset") or a.get("url") or "?"
            flags = ", ".join(str(x) for x in (a.get("flags") or []))
            lines.append(f"- {host}: reachable={a.get('reachable')} stack={a.get('stack')} flags={flags}")
    else:
        lines.append("- (no coverage asset matched this front text)")

    # 约束切片: 该 front 已被尝试并排除的 mechanism class + input shape
    constraints = _load_front_constraints(run_dir, front)
    if constraints:
        lines += ["", "## Constraints (Ruled-Out Paths)"]
        lines += ["The following mechanism classes and input shapes have been tried and ruled out. "
                   "Do NOT retry these unless you have a materially different approach:"]
        for c in constraints:
            lines.append(f"- [{c['id']}] {c['mechanism_class']} on {c['input_shape']}: {c['ruled_out']}")

    # 跨运行经验: 该 front 的 barrier class 在历史 run 中的表现
    cross_run_context = _load_cross_run_context(run_dir, front)
    if cross_run_context:
        lines += ["", "## Cross-Run Experience (Historical Barrier Data)"]
        lines.append("This barrier class has been encountered in previous runs. Learn from history:")
        lines.extend(cross_run_context)

    lines += ["", "## Relevant Evidence"]
    lines.extend(evidence_matches or ["- (no E-block explicitly mentions this front id)"])
    lines += ["", "## Relevant False Positives"]
    lines.extend(fp_matches or ["- (no FP-block explicitly mentions this front id)"])
    lines += ["", "## Relevant Knowledge / Xday Pointers"]
    lines.extend(_knowledge_xday_summary(kb_ids, kb_dir=kb_dir, xday_dir=xday_dir, weap_dir=weap_dir))
    lines += ["", "## Recent Decisions / Barriers", decisions_tail or "- (decisions.md missing or empty)"]
    lines += ["", "## Role Instructions"]
    if role_text:
        lines.append(f"Source: docs/templates/agents/{role_template.name}")
        lines.append("")
        lines.append(role_text.strip())
    else:
        lines.append(f"- Missing role template for role={role}.")
    lines += [
        "",
        "## Output Contract Reminder",
        "Agent:",
        "Role:",
        "Assigned front:",
        "Scope:",
        "Budget used:",
        "Maturity: phenomenon | candidate",
        "Supports:",
        "Refutes:",
        "Artifacts:",
        "Control:",
        "Replicated:",
        "Confidence:",
        "Barrier:",
        "Conflict candidates:",
        "Recommended next action:",
        "Merge note:",
        "",
    ]
    return "\n".join(lines)


def build_from_agent(run_dir: Path, agent_id: str) -> str:
    a = _assignment(run_dir, agent_id)
    if not a:
        raise SystemExit(f"agent assignment not found: {agent_id}")
    return build_pack(run_dir, front=str(a.get("front") or ""), role=str(a.get("role") or ""), agent=agent_id)


def _atomic_write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f"{path.name}.tmp{os.getpid()}-{time.monotonic_ns()}")
    tmp.write_text(text, encoding="utf-8")
    os.replace(tmp, path)


def _selftest() -> int:
    import tempfile
    d = Path(tempfile.mkdtemp())
    kb = d / "knowledge"
    weap = kb / "weaponized"
    xday = d / "poc_library" / "xday"
    weap.mkdir(parents=True)
    xday.mkdir(parents=True)
    (kb / "foobar-cms.md").write_text(
        "---\nid: foobar-cms\nproduct: FooBar CMS\nmaturity: seed\n"
        'signatures: ["foobar-cms", "/fb/login.do"]\n---\n\n'
        "## Weak-Point Anchors\n- Anchor: auth boundary review.\n",
        encoding="utf-8")
    (weap / "foobar-cms.md").write_text("---\nid: foobar-cms\n---\nlocal note\n", encoding="utf-8")
    xp = xday / "foobar-cms"
    xp.mkdir()
    (xp / "README.md").write_text("| link | `knowledge/foobar-cms.md` |\n", encoding="utf-8")
    (xp / "poc.py").write_text("# local only\n", encoding="utf-8")
    (d / "target.md").write_text("# Target\n- In-scope assets: app.example\n", encoding="utf-8")
    (d / "frontier.md").write_text(
        "# Frontier\n\n### F-001\n- Front: app.example auth kb:foobar-cms\n- Status: open\n", encoding="utf-8")
    (d / "coverage.json").write_text(json.dumps({"assets": [
        {"host": "app.example", "reachable": True, "stack": "kb:foobar-cms", "flags": ["LOGIN"]},
        {"host": "other.example", "reachable": True},
    ]}), encoding="utf-8")
    (d / "evidence.md").write_text("# Evidence\n\n## E-001\n- Front: F-001\n- Maturity: candidate\n", encoding="utf-8")
    (d / "decisions.md").write_text("# Decisions\n\n## D-001\n- Chosen front: F-001\n", encoding="utf-8")
    pack = build_pack(d, front="F-001", role="web-auth", agent="A-web-auth-001",
                      kb_dir=kb, xday_dir=xday, weap_dir=weap)
    out = d / "context" / "F-001.web-auth.md"
    _atomic_write(out, pack)
    checks = [
        ("pack names front and role", "Context Pack F-001 / web-auth" in pack),
        ("pack includes matched coverage", "app.example" in pack and "kb:foobar-cms" in pack),
        ("pack includes knowledge pointer", "knowledge `foobar-cms`" in pack and "FooBar CMS" in pack),
        ("pack includes xday pointer without dumping note body", "local xday pointer" in pack and "local note" not in pack),
        ("pack includes evidence block", "E-001" in pack),
        ("pack includes output contract", "Maturity: phenomenon | candidate" in pack),
        ("atomic write created file", out.exists() and out.read_text(encoding="utf-8") == pack),
    ]
    bad = [n for n, ok in checks if not ok]
    for n, ok in checks:
        print(("ok   " if ok else "FAIL ") + n)
    print("context_pack selftest " + ("passed" if not bad else f"FAILED ({len(bad)})"))
    return 0 if not bad else 1


def main() -> int:
    ap = argparse.ArgumentParser(description="Build a minimal subagent context pack from a run dir.")
    ap.add_argument("run_dir", nargs="?")
    ap.add_argument("--front")
    ap.add_argument("--role")
    ap.add_argument("--agent")
    ap.add_argument("--out")
    ap.add_argument("--selftest", action="store_true")
    args = ap.parse_args()
    if args.selftest:
        return _selftest()
    if not args.run_dir:
        ap.error("run_dir is required")
    run_dir = resolve_run_dir(args.run_dir)
    if args.agent and not (args.front or args.role):
        text = build_from_agent(run_dir, args.agent)
    else:
        if not (args.front and args.role):
            ap.error("pass --front and --role, or --agent")
        text = build_pack(run_dir, front=args.front, role=args.role, agent=args.agent or "")
    if args.out:
        _atomic_write(Path(args.out), text)
        print(args.out)
    else:
        print(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
