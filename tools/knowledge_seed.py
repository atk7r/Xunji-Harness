#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""knowledge_seed.py — 指纹飞轮的【写回端】脚手架: 据一次识别落一条 grounding 知识条目骨架。

背景(接线审计 2026-06-17): 飞轮的【读端】(knowledge_match/xday_match)已焊好 —— 指纹命中→检索锚点。
但反方向【写回端】一直是裸手编 knowledge/<id>.md + 只在收口、没工具。读强写弱 → 飞轮转不快:
knowledge_match --body 在一个明确指纹上 MISS, 就是飞轮盲点, 却没有顺手把它补成一条 signature 的路。
本工具就是那条路: 起一条【合规骨架】(maturity=seed), 让"补知识"从裸手编变成填空。

铁律(同 knowledge/README.md / check_knowledge):
- 只产【公开接地层】骨架(recognition + 弱点锚 + 校验原则 + 混淆项 + 引用) —— 绝不产 payload/exploit/PoC
  (那是 gitignored 的 weaponized 层)。骨架结构对齐 _TEMPLATE.md, 产出过 check_knowledge 结构门。
- 不下结论: 锚点 Reference/来源、signatures 都是【待人确认】的填空, 不是自动断言。--from-body 只是从响应
  体抽【候选】signature(title/generator/产品名), 由 driver 核对适配, 不当成事实。
- 派生不驱动: 它只建文件, 不选目标、不发包、不入库 weaponized。

用法:
  python tools/knowledge_seed.py <id> --product "Name" [--vendor V] [--category cms]
         [--aliases a,b] [--signatures s1,s2] [--from-body runs/<t>/evidence/x.html]
  python tools/knowledge_seed.py --selftest
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import date
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8")       # type: ignore[attr-defined]
except Exception:
    pass

ROOT = Path(__file__).resolve().parents[1]
KNOWLEDGE = ROOT / "knowledge"


def extract_signatures(body: str, limit: int = 6) -> list[str]:
    """从保存的响应体抽【候选】recognition signature(小写子串)。best-effort, 由人核对。
    抽: <title> 文本、generator/x-powered-by meta、'powered by X'、独特产品 token。绝不抽 payload 形状串。"""
    cands: list[str] = []
    t = re.search(r"<title[^>]*>\s*(.*?)\s*</title>", body, re.IGNORECASE | re.DOTALL)
    if t:
        cands.append(re.sub(r"\s+", " ", t.group(1)).strip())
    for m in re.finditer(r'<meta[^>]+(?:name=["\'](?:generator|application-name)["\'][^>]+content|content)=["\']([^"\']{2,60})["\']',
                         body, re.IGNORECASE):
        cands.append(m.group(1).strip())
    for m in re.finditer(r"powered[ -]by[:\s]+([A-Za-z0-9_.\- ]{2,40})", body, re.IGNORECASE):
        cands.append(m.group(1).strip())
    # 去重、小写、丢空/过长/含 payload 形状的(与 check_knowledge.PAYLOAD_SHAPE_PATTERNS 对齐,
    # 否则抽到的 signature 可能把 payload 形状串写进公开层 —— 公开层只该有识别特征, 不该有武器形状)
    seen: list[str] = []
    bad = re.compile(r"union\s+select|<script|\$\{jndi:|/etc/passwd|/dev/tcp/|<\?php|"
                     r"eval\s*\(\s*\$_|\.\./|'\s*or\s*'1'\s*=\s*'1|\bsleep\s*\(\s*\d", re.IGNORECASE)
    for c in cands:
        cl = c.lower().strip()
        if cl and len(cl) <= 60 and not bad.search(cl) and cl not in seen:
            seen.append(cl)
        if len(seen) >= limit:
            break
    # 剥尾部版本号 → 也给版本无关 signature(#5 dogfood: 'apache tomcat/9.0.58' 只认那一版, 加 'apache tomcat')
    ver = re.compile(r"[ /v.\-]*\d[\d.]*[a-z]?\s*$", re.I)
    out: list[str] = []
    for s in seen:
        if s not in out:
            out.append(s)
        s2 = ver.sub("", s).strip(" /.-")
        if s2 and s2 != s and len(s2) >= 3 and s2 not in out:
            out.append(s2)
    return out[:limit]


def build_entry(entry_id: str, product: str, vendor: str, category: str,
                aliases: list[str], signatures: list[str]) -> str:
    """产一条对齐 _TEMPLATE.md 的 seed 骨架 —— 过 check_knowledge 结构门; 内容是待填空, 不下结论。"""
    # 必须用 json.dumps 转义: signature 里若含 " 或 \, 手拼会产出非法 JSON —— check_knowledge 只验结构
    # 会放行, 但 knowledge_match 的 json.loads 会静默吞成 sigs=[] → 该条目永远匹配不上(飞轮白写)。
    sig_json = json.dumps(signatures, ensure_ascii=False)
    alias_json = json.dumps(aliases, ensure_ascii=False)
    sig_lines = "\n".join(f"- Signature: `{s}`  <!-- 核对: 这是否唯一识别该产品 -->" for s in signatures) \
        or "- Signature: <path / header / body marker / favicon hash / 默认行为 —— 待填>"
    today = date.today().isoformat()
    return f"""---
id: {entry_id}
product: {product}
vendor: {vendor or "TODO"}
aliases: {alias_json}
category: {category or "TODO-category"}
last_reviewed: {today}
maturity: seed
signatures: {sig_json}
---

<!--
SEED scaffold (knowledge_seed.py). PUBLIC grounding tier — ships to GitHub.
Allowed: recognition signatures, weak-point anchors (class + mechanism + reference),
proof-only verification. NO payloads / exploit chains / PoC here (那些进 gitignored
knowledge/weaponized/). 把下面的 TODO 填实再把 maturity 升 seed->verified。
-->

## Recognition (identification only)

{sig_lines}
- Distinguishing notes: <什么把它和仿冒/相似品分开; 什么会是误匹配 —— 待填>

## Weak-Point Anchors (variant-analysis input — NOT exploit steps)

- Anchor: <弱点 CLASS, 如 "敏感管理端点暴露" —— 待填>
  - Affected: <版本 / 配置条件>
  - Mechanism: <一两句: 为什么弱(概念, 非步骤)>
  - Reference: TODO-CVE/CNVD/advisory
  - source: run-observation

## Verification Principle (existence proof)

- Existence proof: <"弱点存在"在这里长什么样 —— 存在性, 非影响>
- Hard stops: <按证明边界(机密/可用/完整): 只证端点身份; 不拉数据/不提取密钥/不 RCE/不篡改/不拖库>

## False-Positive / Confounders

- <什么会冒充该识别特征: 蜜罐 / 网关桩 / 无关技术 —— 对应 cognition Attribution Checks>

## References

- <主引用, 可点 URL: NVD / CNVD / CNNVD / 厂商通告 —— 待填>
"""


def seed(entry_id: str, product: str, vendor: str, category: str, aliases: list[str],
         signatures: list[str], force: bool, out_dir: Path | None = None) -> tuple[int, str]:
    if not re.fullmatch(r"[a-z0-9][a-z0-9-]*", entry_id):
        return 2, f"id 必须 kebab-case(小写/数字/连字符): {entry_id!r}"
    target = (out_dir or KNOWLEDGE) / f"{entry_id}.md"
    if target.exists() and not force:
        return 2, f"已存在 {target.relative_to(ROOT) if target.is_relative_to(ROOT) else target} —— 要覆盖加 --force(或改用现有条目)"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(build_entry(entry_id, product, vendor, category, aliases, signatures), encoding="utf-8")
    rel = target.relative_to(ROOT) if target.is_relative_to(ROOT) else target
    return 0, str(rel)


def _validate(path: Path) -> list[str]:
    """复用 check_knowledge 的结构校验, 确认骨架过门。返回 errors(空=过)。"""
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    try:
        import check_knowledge as ck
    except Exception as e:                       # pragma: no cover
        return [f"(无法加载 check_knowledge 自校: {e})"]
    errors: list[str] = []
    ck.check_entry(path, errors, [])
    return errors


def main() -> int:
    if "--selftest" in sys.argv:
        return _selftest()
    ap = argparse.ArgumentParser(description="指纹飞轮写回端: 起一条 grounding 知识条目 seed 骨架(派生不驱动)")
    ap.add_argument("id", help="kebab-case 条目 id(= 文件名 knowledge/<id>.md)")
    ap.add_argument("--product", required=True, help="产品名")
    ap.add_argument("--vendor", default="", help="厂商")
    ap.add_argument("--category", default="", help="cms | framework-management-endpoint | device …")
    ap.add_argument("--aliases", default="", help="逗号分隔别名")
    ap.add_argument("--signatures", default="", help="逗号分隔 recognition signature(小写子串); 留空用 --from-body 抽候选")
    ap.add_argument("--from-body", default=None, help="保存的响应体文件 —— 抽候选 signature(供核对)")
    ap.add_argument("--force", action="store_true", help="覆盖已存在条目")
    args = ap.parse_args()

    aliases = [a.strip() for a in args.aliases.split(",") if a.strip()]
    sigs = [s.strip().lower() for s in args.signatures.split(",") if s.strip()]
    if args.from_body and not sigs:
        body = Path(args.from_body).read_text(encoding="utf-8", errors="replace")
        sigs = extract_signatures(body)
        if sigs:
            print(f"[从 {args.from_body} 抽到候选 signature(待你核对): {sigs}]", file=sys.stderr)
        else:
            print(f"[--from-body 没抽到候选 —— 手填 signatures]", file=sys.stderr)

    rc, msg = seed(args.id, args.product, args.vendor, args.category, aliases, sigs, args.force)
    if rc != 0:
        print(msg, file=sys.stderr)
        return rc
    print(f"已起 seed 骨架: {msg}")
    errs = _validate(ROOT / msg)
    if errs:
        print("  ⚠ 结构自校未过(填 TODO 后复跑 check_knowledge):", file=sys.stderr)
        for e in errs:
            print(f"    - {e}", file=sys.stderr)
    else:
        print("  结构自校: 过 check_knowledge 门。把 TODO 填实、确认 signatures, 再升 maturity->verified。")
    return 0


def _selftest() -> int:
    import tempfile
    checks: list[tuple[str, bool]] = []
    # 1) 抽 signature
    body = '<html><head><title>Chaoxing 学习通</title><meta name="generator" content="MyCMS 2.1"></head>powered by FooFramework</html>'
    sigs = extract_signatures(body)
    checks.append(("from-body 抽到 title", any("学习通" in s or "chaoxing" in s for s in sigs)))
    checks.append(("from-body 抽到 generator", any("mycms" in s for s in sigs)))
    checks.append(("from-body 不抽 payload 形状", not any("<script" in s for s in extract_signatures('<title><script>x</script></title>'))))
    # 2) 产骨架对齐 check_knowledge 必需项(直接验字符串, 不写进真 knowledge/, 无副作用)
    text = build_entry("test-seed-product", "Test Product", "TestVendor", "cms",
                       ["tp", "testprod"], ["test product", "x-powered-by: testprod"])
    for sec in ["## Recognition", "## Weak-Point Anchors", "## Verification Principle",
                "## False-Positive / Confounders", "## References"]:
        checks.append((f"骨架含 {sec}", sec in text))
    checks.append(("frontmatter maturity: seed", "maturity: seed" in text))
    checks.append(("锚点有 Reference + source(过 check_knowledge 锚点门)",
                   bool(re.search(r"reference\s*:", text, re.IGNORECASE)) and bool(re.search(r"source\s*:", text, re.IGNORECASE))))
    checks.append(("公开层无 payload/exploit 标题(发布路由对)",
                   "## payload" not in text.lower() and "## exploit" not in text.lower() and "## poc" not in text.lower()))
    # 3) seed() 写盘(临时目录) + id 校验 + 防覆盖
    d = Path(tempfile.mkdtemp())
    rc, _ = seed("test-seed-product", "Test Product", "", "", [], ["test product"], force=False, out_dir=d)
    checks.append(("seed 写盘 rc=0 + 文件落地", rc == 0 and (d / "test-seed-product.md").exists()))
    rc2, _ = seed("Bad_ID", "P", "", "", [], [], force=False, out_dir=d)
    checks.append(("非 kebab id 被拒", rc2 == 2))
    rc3, _ = seed("test-seed-product", "P", "", "", [], [], force=False, out_dir=d)
    checks.append(("已存在不覆盖(无 --force)被拒", rc3 == 2))
    rc4, _ = seed("test-seed-product", "P", "", "", [], [], force=True, out_dir=d)
    checks.append(("--force 可覆盖", rc4 == 0))

    bad = [n for n, ok in checks if not ok]
    for n, ok in checks:
        print(("ok   " if ok else "FAIL ") + n)
    print("knowledge_seed selftest " + ("passed" if not bad else f"FAILED ({len(bad)})"))
    return 0 if not bad else 1


if __name__ == "__main__":
    raise SystemExit(main())
