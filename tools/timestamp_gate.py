#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""timestamp_gate.py — 漏洞检索前强制获取当前时间戳的统一闸门。

设计意图: 项目规则要求每次漏洞检索(CVE 查询 / WebSearch / knowledge_match /
WebFetch 漏洞数据)必须先获取当前时间, 再据此约束搜索范围 — 防止 LLM 凭训练截止日期
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


def build_search_hint(dt: datetime | None = None) -> str:
    """生成 WebSearch 应附加的时间约束字符串。"""
    dt = dt or now_utc()
    year = dt.year
    return (
        f"当前时间: {format_cn(dt)}。"
        f"漏洞检索必须以 {year} 年为基准: "
        f"优先搜索 {year} 年及近 3 年的 CVE/CNVD/安全公告; "
        f"引用 CVE 时必须验证其发布时间不晚于 {format_date(dt)}; "
        f"严禁凭模型记忆引用未验证年份的 CVE 编号。"
    )


def build_output(dt: datetime | None = None) -> dict:
    dt = dt or now_utc()
    return {
        "iso": format_iso(dt),
        "date": format_date(dt),
        "epoch": format_epoch(dt),
        "year": dt.year,
        "month": dt.month,
        "cn": format_cn(dt),
        "search_hint": build_search_hint(dt),
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
    ap.add_argument("--selftest", action="store_true", help="回归测试")
    args = ap.parse_args()

    if args.selftest:
        return _selftest()

    dt = now_utc()

    if args.json:
        print(json.dumps(build_output(dt), ensure_ascii=False, indent=2))
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
        print(build_search_hint(dt))
        return 0

    # Default: human-readable multi-format output
    out = build_output(dt)
    print("=== 时间戳闸门 ===")
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
    out = build_output(dt)
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

    # Search hint contains year
    checks.append(("search_hint has year", str(dt.year) in out["search_hint"]))
    checks.append(("search_hint has CVE mention", "CVE" in out["search_hint"]))
    checks.append(("search_hint has CNVD mention", "CNVD" in out["search_hint"]))

    # JSON roundtrip
    raw = json.dumps(out, ensure_ascii=False)
    loaded = json.loads(raw)
    checks.append(("JSON roundtrip iso", loaded["iso"] == out["iso"]))
    checks.append(("JSON roundtrip year", loaded["year"] == out["year"]))

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
    finally:
        sys.stdout = old_stdout

    bad = [n for n, ok in checks if not ok]
    for n, ok in checks:
        print(("ok   " if ok else "FAIL ") + n)
    print("timestamp_gate selftest " + ("passed" if not bad else f"FAILED ({len(bad)})"))
    return 0 if not bad else 1


if __name__ == "__main__":
    raise SystemExit(main())
