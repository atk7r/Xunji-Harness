#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""timestamp_gate.py — 漏洞检索前强制获取当前时间戳的统一闸门。

设计意图: 项目规则要求每次漏洞检索(CVE 查询 / WebSearch / knowledge_match)
必须先获取当前时间, 再据此约束搜索范围 — 防止 LLM 凭训练截止日期
幻觉出过期/不存在 CVE, 确保搜索锚定当下。

用法:
  python tools/timestamp_gate.py                 # 人类可读: 多格式时间 + 搜索提示
  python tools/timestamp_gate.py --json           # JSON 输出, 供程序/Agent 消费
  python tools/timestamp_gate.py --iso            # 仅 ISO 8601
  python tools/timestamp_gate.py --epoch          # 仅 Unix epoch
  python tools/timestamp_gate.py --year           # 仅当前年份(如 2026)
  python tools/timestamp_gate.py --search-hint    # 输出 WebSearch 应带的时间约束
  python tools/timestamp_gate.py --selftest       # 回归测试
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone


try:
    sys.stdout.reconfigure(encoding="utf-8")       # type: ignore[attr-defined]
except Exception:
    pass


def now_utc() -> datetime:
    return datetime.now(timezone.utc)


def format_iso(dt: datetime | None = None) -> str:
    dt = dt or now_utc()
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def format_date(dt: datetime | None = None) -> str:
    dt = dt or now_utc()
    return dt.strftime("%Y-%m-%d")


def format_epoch(dt: datetime | None = None) -> float:
    dt = dt or now_utc()
    return dt.timestamp()


def format_cn(dt: datetime | None = None) -> str:
    dt = dt or now_utc()
    return dt.strftime("%Y年%m月%d日 %H:%M UTC")


def build_search_hint(dt: datetime | None = None, kind: str = "vuln") -> str:
    """生成 WebSearch 应附加的时间约束字符串。

    kind='vuln' (默认, 向后兼容): 通用时间锚 + CVE 专用验证规则
    kind='generic': 仅通用时间锚 (产品版本 / 公告 / 配置 / 技术搜索)
    """
    dt = dt or now_utc()
    year = dt.year
    date = format_date(dt)
    cn = format_cn(dt)

    # Layer 1: 通用时间锚 — 所有联网搜索都必须受此约束
    general = (
        f"当前时间: {cn}。"
        f"所有联网搜索必须以 {year} 年为时间基准: "
        f"WebSearch query 必须包含 {year} 或不晚于 {date} 的明确时间约束; "
        f"引用页面须核验发布时间/更新日期不晚于 {date}; "
        f"引用任何版本号 / 安全公告 / 配置变更 / 绕过技术时, "
        f"必须确认信息发布时间不晚于 {date}; "
        f"优先搜索 {year} 年及近 3 年的资料, 旧信息须标注「可能已过期」; "
        f"严禁凭模型记忆引用未验证年份的信息。"
    )

    if kind not in ("generic", "vuln"):
        raise ValueError(
            f"unsupported kind: '{kind}' (expected 'generic' or 'vuln')"
        )

    if kind == "generic":
        return general

    # Layer 2: CVE/CNVD 专用 — 在通用基础上叠加编号验证规则
    vuln_extra = (
        f"漏洞检索附加: 优先搜索 {year} 年及近 3 年的 CVE/CNVD/安全公告; "
        f"引用 CVE 编号前必须验证其发布年份 ≤ {year} 且发布时间不晚于 {date}; "
        f"拿到的 CVE 须用 NVD 或厂商官方记录确认发布时间; "
        f"严禁凭模型记忆编造未验证年份的 CVE 编号。"
    )
    return f"{general} {vuln_extra}"


def build_output(dt: datetime | None = None, kind: str = "vuln") -> dict:
    dt = dt or now_utc()
    return {
        "iso": format_iso(dt),
        "date": format_date(dt),
        "epoch": format_epoch(dt),
        "year": dt.year,
        "month": dt.month,
        "cn": format_cn(dt),
        "search_hint": build_search_hint(dt, kind=kind),
        "kind": kind,
    }


def main() -> int:
    ap = argparse.ArgumentParser(
        description="时间戳闸门: 漏洞检索前强制获取当前时间"
    )
    ap.add_argument("--json", action="store_true", help="JSON 输出(程序消费)")
    ap.add_argument("--iso", action="store_true", help="仅 ISO 8601 格式")
    ap.add_argument("--epoch", action="store_true", help="仅 Unix epoch")
    ap.add_argument("--year", action="store_true", help="仅当前年份")
    ap.add_argument("--search-hint", action="store_true", help="输出 WebSearch 时间约束提示")
    ap.add_argument("--kind", choices=["generic", "vuln"], default="vuln",
                    help="时间约束范围: generic(通用) / vuln(通用+CVE, 默认)")
    ap.add_argument("--selftest", action="store_true", help="回归测试")
    args = ap.parse_args()

    if args.selftest:
        return _selftest()

    dt = now_utc()

    kind = args.kind

    if args.json:
        print(json.dumps(build_output(dt, kind=kind), ensure_ascii=False, indent=2))
        return 0
    if args.iso:
        print(format_iso(dt))
        return 0
    if args.epoch:
        print(str(format_epoch(dt)))
        return 0
    if args.year:
        print(str(dt.year))
        return 0
    if args.search_hint:
        print(build_search_hint(dt, kind=kind))
        return 0

    # Default: human-readable multi-format output
    out = build_output(dt, kind=kind)
    mode_label = "[通用+CVE]" if kind == "vuln" else "[仅通用]"
    print(f"=== 时间戳闸门 {mode_label} ===")
    print(f"  ISO 8601:  {out['iso']}")
    print(f"  日期:      {out['date']}")
    print(f"  年份:      {out['year']}")
    print(f"  中文:      {out['cn']}")
    print(f"  Unix:      {out['epoch']:.0f}")
    print()
    print(out["search_hint"])
    return 0


def _selftest() -> int:
    """Regression tests — uses real clock (deterministic-enough for format checks)."""
    dt = now_utc()
    out = build_output(dt, kind="vuln")
    out_generic = build_output(dt, kind="generic")
    checks: list[tuple[str, bool]] = []

    # ISO format: YYYY-MM-DDTHH:MM:SSZ
    checks.append(("ISO has T and Z", "T" in out["iso"] and out["iso"].endswith("Z")))
    checks.append(("ISO starts with year", out["iso"].startswith(str(dt.year))))

    # Date format: YYYY-MM-DD
    checks.append(("date is YYYY-MM-DD", len(out["date"]) == 10 and out["date"][4] == "-"))

    # Epoch is positive float
    checks.append(("epoch > 1.7e9", out["epoch"] > 1.7e9))

    # Year is current
    checks.append(("year is current", out["year"] == dt.year))
    checks.append(("month in 1..12", 1 <= out["month"] <= 12))

    # Search hint (vuln kind): contains both general and CVE parts
    checks.append(("vuln hint has year", str(dt.year) in out["search_hint"]))
    checks.append(("vuln hint has 'WebSearch query'", "WebSearch query 必须包含" in out["search_hint"]))
    checks.append(("vuln hint requires page-date verification", "引用页面须核验" in out["search_hint"]))
    checks.append(("vuln hint has CVE mention", "CVE" in out["search_hint"]))
    checks.append(("vuln hint has CNVD mention", "CNVD" in out["search_hint"]))
    checks.append(("vuln hint has generic time anchor", "所有联网搜索" in out["search_hint"]))
    checks.append(("vuln hint has '可能已过期'", "可能已过期" in out["search_hint"]))
    checks.append(("vuln hint requires official CVE date source",
                   "NVD 或厂商官方记录确认发布时间" in out["search_hint"]))
    checks.append(("vuln hint does not require WebFetch", "WebFetch" not in out["search_hint"]))

    # Search hint (generic kind): has time anchor but NO CVE/CNVD
    checks.append(("generic hint has year", str(dt.year) in out_generic["search_hint"]))
    checks.append(("generic hint has 'WebSearch query'", "WebSearch query 必须包含" in out_generic["search_hint"]))
    checks.append(("generic hint has generic time anchor", "所有联网搜索" in out_generic["search_hint"]))
    checks.append(("generic hint has '可能已过期'", "可能已过期" in out_generic["search_hint"]))
    checks.append(("generic hint does not require WebFetch", "WebFetch" not in out_generic["search_hint"]))
    checks.append(("generic hint NO CVE mention", "CVE" not in out_generic["search_hint"]))
    checks.append(("generic hint NO CNVD mention", "CNVD" not in out_generic["search_hint"]))

    # kind validation: invalid kind raises ValueError
    try:
        build_search_hint(dt, kind="invalid")
        checks.append(("invalid kind raises ValueError", False))
    except ValueError:
        checks.append(("invalid kind raises ValueError", True))

    # JSON roundtrip
    raw = json.dumps(out, ensure_ascii=False)
    loaded = json.loads(raw)
    checks.append(("JSON roundtrip iso", loaded["iso"] == out["iso"]))
    checks.append(("JSON roundtrip year", loaded["year"] == out["year"]))
    checks.append(("JSON roundtrip kind", loaded["kind"] == "vuln"))

    # CLI flag outputs (capture via main with monkey-patched argv)
    import io
    old_stdout = sys.stdout
    try:
        # --iso
        buf = io.StringIO()
        sys.stdout = buf
        sys.argv = ["timestamp_gate.py", "--iso"]
        try:
            main()
        except SystemExit:
            pass
        sys.stdout = old_stdout
        iso_out = buf.getvalue().strip()
        checks.append(("--iso flag output matches", iso_out == out["iso"]))

        # --year
        buf = io.StringIO()
        sys.stdout = buf
        sys.argv = ["timestamp_gate.py", "--year"]
        try:
            main()
        except SystemExit:
            pass
        sys.stdout = old_stdout
        year_out = buf.getvalue().strip()
        checks.append(("--year flag output matches", year_out == str(dt.year)))

        # --json
        buf = io.StringIO()
        sys.stdout = buf
        sys.argv = ["timestamp_gate.py", "--json"]
        try:
            main()
        except SystemExit:
            pass
        sys.stdout = old_stdout
        json_out = buf.getvalue().strip()
        checks.append(("--json flag valid JSON", json_out.startswith("{")))

        # --search-hint --kind generic
        buf = io.StringIO()
        sys.stdout = buf
        sys.argv = ["timestamp_gate.py", "--search-hint", "--kind", "generic"]
        try:
            main()
        except SystemExit:
            pass
        sys.stdout = old_stdout
        generic_hint_out = buf.getvalue().strip()
        checks.append(("--search-hint --kind generic has no CVE", "CVE" not in generic_hint_out))
        checks.append(("--search-hint --kind generic has time anchor", "所有联网搜索" in generic_hint_out))
    finally:
        sys.stdout = old_stdout

    bad = [n for n, ok in checks if not ok]
    for n, ok in checks:
        print(("ok   " if ok else "FAIL ") + n)
    print("timestamp_gate selftest " + ("passed" if not bad else f"FAILED ({len(bad)})"))
    return 0 if not bad else 1


if __name__ == "__main__":
    raise SystemExit(main())
