#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""输入形状记忆工具 —— 从 run 目录的 surface.md 提取已记录的输入形状, 辅助跨 front 复用。

每个 IS-xxx 记录一个已探测的请求模板(URL pattern、Content-Type、关键参数、响应形状),
供后续攻击复用。CLI 用法:

  python tools/input_shape.py list runs/<dir>          # 列出所有 IS-xxx
  python tools/input_shape.py match runs/<dir>          # 匹配给定 URL 最相似的已知输入形状
           --method POST --path /api/user/profile
  python tools/input_shape.py coverage runs/<dir>       # 计算各输入形状的 payload class 覆盖率
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8")       # type: ignore[attr-defined]
except Exception:
    pass

ROOT = Path(__file__).resolve().parents[1]
HWS = r"[^\S\n]"


def resolve_run_dir(path: str | Path) -> Path:
    p = Path(path)
    return (p if p.is_absolute() else ROOT / p).resolve()


def _field(text: str, name: str) -> str:
    """从 markdown 块中提取 `- Name: value` 字段值(单行)。"""
    m = re.search(rf"(?im)^{HWS}*[-*]?{HWS}*{re.escape(name)}{HWS}*[:：]{HWS}*([^\n]*)", text)
    return m.group(1).strip() if m else ""


def parse_input_shapes(run_dir: Path) -> list[dict]:
    """解析 surface.md 的 ## Input Shape Catalog 段, 返回所有 IS-xxx 的 dict 列表。"""
    sf = run_dir / "surface.md"
    if not sf.exists():
        return []

    text = sf.read_text(encoding="utf-8", errors="replace")
    # 找到 ## Input Shape Catalog 段
    m = re.search(r"(?ims)^##\s+Input Shape Catalog\s*$(.*?)(?=^##\s|\Z)", text)
    if not m:
        return []

    body = m.group(1)
    shapes: list[dict] = []
    for is_m in re.finditer(r"(?ms)^###[ \t]+(IS-\d+).*?(?=^###[ \t]+IS-\d+|\Z)", body):
        block = is_m.group(0)
        is_id = is_m.group(1)

        url_pattern = _field(block, "URL pattern")
        # 解析 method 和 path
        method = ""
        path = ""
        if url_pattern:
            parts = url_pattern.strip().split(None, 1)
            if parts:
                method = parts[0].upper()
            if len(parts) > 1:
                path = parts[1]

        content_type = _field(block, "Content-Type")
        key_params = _field(block, "Key params")
        auth_required = _field(block, "Auth required")
        response_shape = _field(block, "Response shape")
        seen_on = _field(block, "Seen on hosts")
        tested_classes = _field(block, "Tested payload classes")
        saturation = _field(block, "Saturation")

        shapes.append({
            "id": is_id,
            "url_pattern": url_pattern,
            "method": method,
            "path": path,
            "content_type": content_type,
            "key_params": key_params,
            "auth_required": auth_required,
            "response_shape": response_shape,
            "seen_on": seen_on,
            "tested_classes": tested_classes,
            "saturation": saturation,
        })

    return shapes


def _parse_constraints(run_dir: Path) -> list[dict]:
    """解析 constraints.md, 返回约束列表。"""
    path = run_dir / "constraints.md"
    if not path.exists():
        return []
    text = path.read_text(encoding="utf-8", errors="replace")
    constraints: list[dict] = []
    for m in re.finditer(r"(?ms)^##[ \t]+(C-\d+).*?(?=^##[ \t]+C-\d+|\Z)", text):
        block = m.group(0)
        constraints.append({
            "id": m.group(1),
            "mechanism_class": _field(block, "Mechanism class"),
            "input_shape": _field(block, "Input shape"),
        })
    return constraints


def list_shapes(run_dir: Path) -> int:
    """列出所有已记录的输入形状。"""
    shapes = parse_input_shapes(run_dir)
    if not shapes:
        print("[input_shape] surface.md 中无 Input Shape Catalog 段或该段为空")
        return 0

    print(f"[input_shape] {len(shapes)} 个输入形状:\n")
    for s in shapes:
        print(f"  {s['id']}: {s['method']} {s['path']}")
        if s['content_type']:
            print(f"    Content-Type: {s['content_type']}")
        if s['key_params']:
            print(f"    Key params: {s['key_params']}")
        if s['seen_on']:
            print(f"    Seen on: {s['seen_on']}")
        if s['tested_classes']:
            print(f"    Tested: {s['tested_classes']}")
        if s['saturation']:
            print(f"    Saturation: {s['saturation']}")
    return 0


def _path_similarity(known_path: str, target_path: str) -> float:
    """计算路径前缀匹配相似度。越长共同前缀得分越高。"""
    if not known_path or not target_path:
        return 0.0
    kn = known_path.strip("/").lower()
    tn = target_path.strip("/").lower()
    if kn == tn:
        return 1.0
    # 按段匹配
    k_segs = kn.split("/")
    t_segs = tn.split("/")
    match = 0
    for k, t in zip(k_segs, t_segs):
        if k == t:
            match += 1
        else:
            break
    return match / max(len(k_segs), len(t_segs)) if max(len(k_segs), len(t_segs)) > 0 else 0.0


def match_shape(run_dir: Path, method: str, path: str, content_type: str = "") -> int:
    """匹配给定 URL 最相似的已知输入形状。"""
    shapes = parse_input_shapes(run_dir)
    if not shapes:
        print("[input_shape] 无已知输入形状可匹配")
        return 0

    method = method.upper().strip()
    path = path.strip()
    content_type = content_type.strip().lower()

    scored: list[tuple[float, dict]] = []
    for s in shapes:
        score = 0.0
        reasons: list[str] = []

        # method 完全匹配
        if s["method"] and s["method"].upper() == method:
            score += 0.3
            reasons.append(f"method={method}")
        elif s["method"]:
            score -= 0.1

        # path 前缀相似度
        path_sim = _path_similarity(s["path"], path)
        score += path_sim * 0.5
        if path_sim > 0:
            reasons.append(f"path_sim={path_sim:.1f}")

        # Content-Type 匹配
        if content_type and s["content_type"]:
            if s["content_type"].lower() == content_type:
                score += 0.2
                reasons.append(f"content_type={content_type}")

        scored.append((score, s, reasons))

    scored.sort(key=lambda x: x[0], reverse=True)

    print(f"[input_shape] 匹配 {method} {path}" + (f" (Content-Type: {content_type})" if content_type else ""))
    if scored[0][0] <= 0:
        print("  无相似已知输入形状")
        return 0

    # 显示 top 3
    for i, (score, s, reasons) in enumerate(scored[:3]):
        flag = " *** BEST MATCH" if i == 0 else ""
        reasons_str = "; ".join(reasons) if reasons else "no specific match reason"
        print(f"  {s['id']}: score={score:.2f} {s['method']} {s['path']}{flag}")
        print(f"    reasons: {reasons_str}")
        if s['content_type']:
            print(f"    Content-Type: {s['content_type']}")
        if s['key_params']:
            print(f"    Key params: {s['key_params']}")
        if s['tested_classes']:
            print(f"    Tested: {s['tested_classes']}")

    return 0


def compute_coverage(run_dir: Path) -> int:
    """计算各输入形状的 payload class 覆盖率。结合 constraints.md 判断 tested/total ratio。"""
    shapes = parse_input_shapes(run_dir)
    if not shapes:
        print("[input_shape] 无输入形状可计算覆盖率")
        return 0

    constraints = _parse_constraints(run_dir)

    # 尝试加载 saturation 模块获取 vuln class 映射表
    try:
        from saturation import SURFACE_VULN_CLASSES, _canonical
    except Exception:
        SURFACE_VULN_CLASSES = {}
        _canonical = lambda x: x

    print(f"[input_shape] {len(shapes)} 个输入形状的 payload class 覆盖率:\n")

    for s in shapes:
        # 从 tested_classes 字段解析已测类别
        tested_raw = s.get("tested_classes", "")
        tested_set: set[str] = set()
        if tested_raw:
            # 格式: "SQLi-login (C-004), NoSQLi (C-005)"
            for part in re.split(r"[,;]", tested_raw):
                cls_name = re.sub(r"\(C-\d+\)", "", part).strip()
                if cls_name:
                    tested_set.add(_canonical(cls_name))

        # 从 constraints 中补充: 匹配同一 URL pattern 的约束
        shape_path = s.get("path", "").strip().lower()
        shape_method = s.get("method", "").strip().upper()
        for c in constraints:
            c_input = c.get("input_shape", "").lower()
            if shape_path and shape_path in c_input:
                mc = _canonical(c.get("mechanism_class", ""))
                if mc:
                    tested_set.add(mc)

        # 推断适用的 vuln class 总数(从 surface subtype)
        # 简化: 基于 URL pattern 关键词推断
        total = 5  # 默认 5 类
        combined = (s.get("url_pattern", "") + " " + s.get("key_params", "")).lower()
        if "login" in combined:
            total = 6
        elif "api" in combined:
            total = 7
        elif "upload" in combined:
            total = 3

        tested_n = len(tested_set)
        ratio = tested_n / total if total > 0 else 0
        pct = f"{ratio:.0%}"

        print(f"  {s['id']}: {s['method']} {s['path']}")
        print(f"    Coverage: {tested_n}/{total} = {pct}")
        if tested_set:
            print(f"    Tested classes: {', '.join(sorted(tested_set)[:8])}")
        if s.get("saturation"):
            print(f"    Declared saturation: {s['saturation']}")

    return 0


def _selftest() -> int:
    import tempfile

    d = Path(tempfile.mkdtemp())
    (d / "surface.md").write_text(
        "# Surface\n\n"
        "## Entry Points\n- /\n\n"
        "## Input Shape Catalog\n\n"
        "### IS-001\n"
        "- URL pattern: POST /authService/authUser/v2/login/phone\n"
        "- Content-Type: application/x-www-form-urlencoded\n"
        "- Key params: phone (numeric, 11-digit), password (string)\n"
        "- Auth required: none\n"
        "- Response shape: JSON {code: int, msg: string, data: object|null}\n"
        "- Seen on hosts: app.example.com\n"
        "- Tested payload classes: SQLi-login (C-004), NoSQLi (C-005)\n"
        "- Saturation: 2/5 (SQLi, NoSQLi, type-confusion, SSTI, auth-bypass)\n\n"
        "### IS-002\n"
        "- URL pattern: GET /api/user/profile\n"
        "- Content-Type: application/json\n"
        "- Key params: userId (int)\n"
        "- Auth required: Bearer token\n"
        "- Response shape: JSON {id: int, name: string, role: string}\n"
        "- Seen on hosts: api.example.com\n"
        "- Tested payload classes: IDOR (C-007)\n"
        "- Saturation: 1/5 (IDOR, SQLi, NoSQLi, mass-assignment, SSRF)\n",
        encoding="utf-8")

    shapes = parse_input_shapes(d)
    checks = [
        ("parse 2 shapes", len(shapes) == 2),
        ("IS-001 method", shapes[0]["method"] == "POST"),
        ("IS-001 path", "/authService/authUser/v2/login/phone" in shapes[0]["path"]),
        ("IS-001 content-type", "x-www-form-urlencoded" in shapes[0]["content_type"]),
        ("IS-002 method", shapes[1]["method"] == "GET"),
        ("IS-002 path", "/api/user/profile" in shapes[1]["path"]),
        ("empty surface.md returns []", parse_input_shapes(Path(tempfile.mkdtemp())) == []),
        ("path similarity exact", _path_similarity("/api/user/profile", "/api/user/profile") == 1.0),
        ("path similarity partial", _path_similarity("/api/user", "/api/user/profile") > 0.5),
        ("path similarity none", _path_similarity("/auth/login", "/api/user") == 0.0),
        ("path similarity empty", _path_similarity("", "/api") == 0.0),
    ]

    bad = [n for n, ok in checks if not ok]
    for n, ok in checks:
        print(("ok   " if ok else "FAIL ") + n)
    print("input_shape selftest " + ("passed" if not bad else f"FAILED ({len(bad)})"))
    return 0 if not bad else 1


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)

    if "--selftest" in argv:
        return _selftest()

    ap = argparse.ArgumentParser(description="输入形状记忆工具 —— 提取、匹配、计算覆盖率")
    sub = ap.add_subparsers(dest="cmd")

    p_list = sub.add_parser("list", help="列出所有 IS-xxx")
    p_list.add_argument("run_dir", type=Path)

    p_match = sub.add_parser("match", help="匹配给定 URL 最相似的已知输入形状")
    p_match.add_argument("run_dir", type=Path)
    p_match.add_argument("--method", required=True, help="HTTP method (GET/POST/...)")
    p_match.add_argument("--path", required=True, help="URL path")
    p_match.add_argument("--content-type", default="", help="Content-Type header")

    p_cov = sub.add_parser("coverage", help="计算各输入形状的 payload class 覆盖率")
    p_cov.add_argument("run_dir", type=Path)

    args = ap.parse_args(argv)
    if not args.cmd:
        ap.print_help()
        return 1

    run_dir = resolve_run_dir(args.run_dir)
    if not run_dir.exists():
        print(f"[input_shape] run 目录不存在: {run_dir}", file=sys.stderr)
        return 1

    if args.cmd == "list":
        return list_shapes(run_dir)
    elif args.cmd == "match":
        return match_shape(run_dir, args.method, args.path, args.content_type)
    elif args.cmd == "coverage":
        return compute_coverage(run_dir)

    return 1


if __name__ == "__main__":
    raise SystemExit(main())
