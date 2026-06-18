#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""scope.py — run 的 scope(打谁 / 不打谁)单一权威。

问题(mokwon dogfood 实测): setup 把 134 资产折进 surface, 却把 target.md 的
In-scope/Out-of-scope 留空 → classify/probe 默认会群发 recon 里的【个人 NAS / 外部域】
(非目标资产)。本模块从 recon 的 `ownership` 派生默认 scope 写进 target.md(派生不驱动,
driver 可改), 并给工具一个 in_scope(host) 判定, 把"别打非目标"从手工变成框架内置。

- derive_scope(recon): ownership unrelated→out, core/secondary→in; 压成紧凑模式
  (`*.<registrable>` + IP /24)。secondary(第三方托管)进 notes 提示。
- parse_target_scope(md): 从 target.md 的 In/Out 行折回模式(target.md 是源, 像
  evidence_parse; 不存第二份 json 免漂移)。
- in_scope(host, in_pats, out_pats) -> 'in'|'out'|'unknown'(out 优先)。

边界定位: 这是【打谁】的目标卫生, 不是【授权门】(授权是操作者的事, 无需框架判),
也不是不可逆危害硬地板(那是 safety_gate)。纯 stdlib。
"""
from __future__ import annotations

import argparse
import ipaddress
import json
import re
import sys
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8")       # type: ignore[attr-defined]
except Exception:
    pass

_IP_RE = re.compile(r"^\d{1,3}(\.\d{1,3}){3}$")
# 韩国/常见二级 cc 后缀: registrable = 末3标签; 其余末2标签。无 PSL 的稳健近似。
_SLD = ("ac.kr", "co.kr", "or.kr", "go.kr", "ne.kr", "re.kr", "pe.kr", "hs.kr", "ms.kr", "es.kr")


def _is_ip(h: str) -> bool:
    return bool(_IP_RE.match(h or ""))


def registrable(host: str) -> str:
    """host → 可注册域近似(mokwon.ac.kr / mu.ac.kr / edutrack.co.kr)。无 PSL, 按二级 cc 后缀。"""
    host = (host or "").strip().lower().rstrip(".")
    labels = host.split(".")
    for sld in _SLD:
        s = sld.split(".")
        if len(labels) > len(s) and labels[-len(s):] == s:
            return ".".join(labels[-(len(s) + 1):])
    return ".".join(labels[-2:]) if len(labels) >= 2 else host


def _cidr24(ip: str) -> str:
    o = ip.split(".")
    return f"{o[0]}.{o[1]}.{o[2]}.0/24"


def derive_scope(recon: dict) -> dict:
    """从 recon 派生默认 scope。键: target/in/out/out_detail/notes/heuristic。
    osint_ai schema 有 `ownership`(unrelated→out, core/secondary→in)。**无 ownership 字段的 recon
    源走启发式兜底**: 只把【target 域族】判 in-scope, 其余(别的域/裸 IP)进 needs_human 待人工裁定,
    绝不静默把所有资产判 in-scope(原 bug: 换源后过滤失效)。heuristic=True 时 setup/CLI 会显著告警。"""
    assets = recon.get("assets") or []
    target = (recon.get("target") or "").strip().lower()
    target_reg = registrable(target) if target else ""
    heuristic = not any(isinstance(a, dict) and a.get("ownership") for a in assets)
    in_doms: set[str] = set()
    in_ips: list[str] = []
    out_detail: list[tuple[str, str]] = []
    notes: list[tuple[str, str]] = []
    for a in assets:
        if not isinstance(a, dict):
            continue
        h = (a.get("host") or "").strip().lower()
        if not h:
            continue
        reason = a.get("reason") or ""
        if heuristic:
            # 无 ownership: 只 target 域族 in-scope; 别的域/裸 IP 进 needs_human(不自动 in/out,
            # 因无信号分不清别名 vs 第三方)。不静默全判 in-scope。
            if not _is_ip(h) and target_reg and registrable(h) == target_reg:
                in_doms.add(target_reg)
            else:
                notes.append((h, reason or "无 ownership: 归属待人工裁定"))
            continue
        own = (a.get("ownership") or "core").lower()
        if own == "unrelated":
            out_detail.append((h, reason))
            continue
        # core / secondary → in
        if _is_ip(h):
            in_ips.append(h)
        else:
            in_doms.add(registrable(h))
        if own == "secondary":
            notes.append((h, reason))      # 第三方托管/待裁: in-scope 但低值, 提示复核
    by24: dict[str, list[str]] = {}
    for ip in in_ips:
        by24.setdefault(_cidr24(ip), []).append(ip)
    in_cidrs: list[str] = []
    for c, ips in sorted(by24.items()):
        in_cidrs.append(c if len(set(ips)) >= 2 else ips[0])   # ≥2 同段压 /24, 否则单点
    in_pats = sorted(f"*.{d}" for d in in_doms) + sorted(set(in_cidrs))
    out_pats = sorted(set(h for h, _ in out_detail))
    return {"target": recon.get("target", ""), "in": in_pats, "out": out_pats,
            "out_detail": out_detail, "notes": notes, "heuristic": heuristic}


def _match_one(host: str, pat: str) -> bool:
    host = (host or "").strip().lower()
    pat = (pat or "").strip().lower()
    if not host or not pat:
        return False
    if "/" in pat and _is_ip(host):
        try:
            return ipaddress.ip_address(host) in ipaddress.ip_network(pat, strict=False)
        except Exception:
            return False
    if pat.startswith("*."):
        suf = pat[2:]
        return host == suf or host.endswith("." + suf)
    return host == pat


def in_scope(host: str, in_pats: list[str], out_pats: list[str]) -> str:
    """'out'(命中 out 模式, 优先) | 'in'(命中 in 模式) | 'unknown'(都不命中, 警告不拦)。"""
    if any(_match_one(host, p) for p in out_pats):
        return "out"
    if any(_match_one(host, p) for p in in_pats):
        return "in"
    return "unknown"


_TOK = re.compile(r"[^\s,;]+")


def _patterns_from_line(text: str) -> list[str]:
    text = re.sub(r"[（(][^）)]*[）)]", "", text)          # 丢括号说明
    return [t for t in _TOK.findall(text) if t and t.lower() != "none"]


def parse_target_scope(md: str) -> tuple[list[str], list[str]]:
    """从 target.md 文本折回 (in_pats, out_pats)。target.md 是源(像 evidence_parse)。"""
    def field(name: str) -> list[str]:
        m = re.search(rf"(?im)^\s*-\s*{re.escape(name)}\s*[:：](.*)$", md)
        return _patterns_from_line(m.group(1)) if m else []
    return field("In-scope assets"), field("Out-of-scope assets")


def render_scope_lines(sc: dict) -> tuple[str, str]:
    """→ (in_line, out_line) 写进 target.md(带派生来源说明)。"""
    if sc.get("heuristic"):
        note = "  (⚠ recon 无 ownership: 仅 target 域族启发式; 其余资产见 Notes 待裁 —— 务必复核/补全)"
        in_line = (", ".join(sc["in"]) + note) if sc["in"] else \
                  "⚠ recon 无 ownership 且无 target 域 —— scope 未派生, 手填 In-scope 再 classify"
        return in_line, ""     # 启发式不自动定 out(无信号分不清别名 vs 第三方)
    in_line = (", ".join(sc["in"]) + "  (recon ownership 派生; 复核/可改)") if sc["in"] else ""
    out_line = (", ".join(sc["out"]) + "  (recon ownership=unrelated, 非目标)") if sc["out"] else ""
    return in_line, out_line


def _selftest() -> int:
    recon = {"target": "mokwon.ac.kr", "assets": [
        {"host": "www.mokwon.ac.kr", "ownership": "core"},
        {"host": "lms.mokwon.ac.kr", "ownership": "core"},
        {"host": "mu.ac.kr", "ownership": "core"},
        {"host": "xn--vk1b78lx0k.kr", "ownership": "core"},
        {"host": "cal.mokwon.ac.kr", "ownership": "secondary", "reason": "Google前置"},
        {"host": "lizking215.synology.me", "ownership": "unrelated", "reason": "个人NAS"},
        {"host": "eli.edutrack.co.kr", "ownership": "unrelated", "reason": "外部域"},
        {"host": "203.230.137.174", "ownership": "core"},
        {"host": "203.230.137.52", "ownership": "core"},
        {"host": "175.126.99.61", "ownership": "core"},
    ]}
    sc = derive_scope(recon)
    ip, op = sc["in"], sc["out"]
    checks = [
        ("域压成 *.mokwon.ac.kr", "*.mokwon.ac.kr" in ip),
        ("别名根域 *.mu.ac.kr 在 in", "*.mu.ac.kr" in ip),
        ("IDN *.xn--vk1b78lx0k.kr 在 in(不再误删)", "*.xn--vk1b78lx0k.kr" in ip),
        ("同段 IP 压 /24", "203.230.137.0/24" in ip),
        ("单点 IP 保留", "175.126.99.61" in ip),
        ("unrelated 个人NAS 进 out", "lizking215.synology.me" in op),
        ("unrelated 外部域 进 out", "eli.edutrack.co.kr" in op),
        ("secondary 进 notes(in-scope 但提示)", any(h == "cal.mokwon.ac.kr" for h, _ in sc["notes"])),
        ("secondary cal 仍 in(域匹配)", in_scope("cal.mokwon.ac.kr", ip, op) == "in"),
    ]
    # in_scope 判定
    checks += [
        ("子域 in", in_scope("ucm.mokwon.ac.kr", ip, op) == "in"),
        ("apex in", in_scope("mokwon.ac.kr", ip, op) == "in"),
        ("段内 IP in", in_scope("203.230.137.99", ip, op) == "in"),
        ("out 优先于 in", in_scope("lizking215.synology.me", ip, op) == "out"),
        ("陌生 host unknown", in_scope("evil.example.com", ip, op) == "unknown"),
    ]
    # target.md 往返
    in_line, out_line = render_scope_lines(sc)
    md = f"# Target\n- In-scope assets: {in_line}\n- Out-of-scope assets: {out_line}\n"
    pin, pout = parse_target_scope(md)
    checks += [
        ("target.md 往返: in 模式可解析回", "*.mokwon.ac.kr" in pin),
        ("target.md 往返: out 模式可解析回", "lizking215.synology.me" in pout),
        ("往返后判定一致", in_scope("ucm.mokwon.ac.kr", pin, pout) == "in"
                          and in_scope("lizking215.synology.me", pin, pout) == "out"),
    ]
    # 启发式兜底: recon 无 ownership 不静默全判 in-scope, 只 target 域族 in, 其余 needs_human
    rec_no_own = {"target": "ex.com", "assets": [
        {"host": "a.ex.com"}, {"host": "b.ex.com"}, {"host": "evil.other.org"}, {"host": "9.9.9.9"}]}
    sc2 = derive_scope(rec_no_own)
    checks += [
        ("无 ownership → heuristic=True", sc2.get("heuristic") is True),
        ("启发式: target 域族 *.ex.com in", "*.ex.com" in sc2["in"]),
        ("启发式: 别的域不自动 in(防静默全 in)", in_scope("evil.other.org", sc2["in"], sc2["out"]) != "in"),
        ("启发式: 裸 IP 不自动 in", in_scope("9.9.9.9", sc2["in"], sc2["out"]) != "in"),
        ("启发式: 别的域/IP 进 notes 待裁",
         any(h == "evil.other.org" for h, _ in sc2["notes"]) and any(h == "9.9.9.9" for h, _ in sc2["notes"])),
        ("有 ownership → heuristic=False", derive_scope(recon).get("heuristic") is False),
    ]
    bad = [n for n, ok in checks if not ok]
    for n, ok in checks:
        print(("ok   " if ok else "FAIL ") + n)
    print("scope selftest " + ("passed" if not bad else f"FAILED ({len(bad)})"))
    return 0 if not bad else 1


def main() -> int:
    ap = argparse.ArgumentParser(description="run scope 派生/判定(打谁不打谁)")
    ap.add_argument("recon", nargs="?", help="recon JSON → 打印派生 scope")
    ap.add_argument("--selftest", action="store_true")
    args = ap.parse_args()
    if args.selftest:
        return _selftest()
    if not args.recon:
        ap.error("need recon.json (or --selftest)")
    recon = json.loads(Path(args.recon).read_text(encoding="utf-8"))
    sc = derive_scope(recon)
    if sc.get("heuristic"):
        print("[⚠ scope 启发式] recon 无 ownership 字段 → 仅按 target 域族派生 in-scope, "
              f"{len(sc['notes'])} 个资产归属待人工裁定。复核 target.md In/Out-of-scope 再 classify。",
              file=sys.stderr)
    in_line, out_line = render_scope_lines(sc)
    print(f"target: {sc['target']}")
    print(f"In-scope:  {in_line}")
    print(f"Out-of-scope: {out_line}")
    if sc["notes"]:
        print("notes (secondary/第三方托管, in-scope 但复核):")
        for h, r in sc["notes"]:
            print(f"  - {h}  {r[:50]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
