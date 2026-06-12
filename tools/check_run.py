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
REQUIRED_FILES = [
    "target.md",
    "surface.md",
    "frontier.md",
    "hypotheses.md",
    "evidence.md",
    "false_positive.md",
    "decisions.md",
    "review.md",
    "report.md",
]

REQUIRED_MARKERS = {
    "frontier.md": [
        "# Frontier",
        "Open Fronts",
        "Deferred Fronts",
        "Closed Fronts",
        "Barrier class:",
        "Failure budget:",
    ],
    "hypotheses.md": ["# Hypotheses", "Status:", "What would confirm:", "What would reject:"],
    "evidence.md": ["# Evidence Ledger", "Certainty:", "Caused by us:", "Alternative explanation:"],
    "false_positive.md": ["# False-Positive Checks", "Could be environmental:", "Impact verified:"],
    # 只要求每次决策都有意义的字段。`Difference from previous failed attempts:`
    # 与 `Failure budget state:` 按 WORKFLOW.md 是【条件字段】(首次尝试为 n/a,
    # 仅在重复/超预算时必填),字符串匹配器无法判断前沿是否重复,故不无条件强制——
    # 该纪律由 driver 判断, 不靠这里的标记串。(P2-6: 修正 check_run 与 WORKFLOW 不一致)
    "decisions.md": [
        "# Decisions",
        "Loaded rule files this cycle:",
        "Chosen front:",
        "Why this is worth pursuing now:",
    ],
    "review.md": [
        "# Review",
        "Shallow work smells:",
        "Repeated-barrier loops:",
        "Failure-budget triggers:",
        "Next autonomous front:",
    ],
    "report.md": ["# Report", "Evidence IDs:"],
}

# Optional artifacts: validated only if present (conditional, not required every
# run). chains.md exists only when a vulnerability chain / 组合利用 is recorded.
OPTIONAL_MARKERS = {
    "chains.md": [
        "# Chains",
        "Hops",
        "Weakest hop certainty:",
        "Terminal node:",
    ],
}


def check_file(path: Path, markers: list[str]) -> list[str]:
    errors: list[str] = []
    if not path.exists():
        return [f"missing {path.name}"]
    text = path.read_text(encoding="utf-8", errors="replace")
    for marker in markers:
        if marker not in text:
            errors.append(f"{path.name} missing marker: {marker}")
    return errors


def check_evidence_certainty(run_dir: Path) -> list[str]:
    """证据门质量护栏(P0-2): certainty >= 0.8 的条目必须带 `Replicated:` 或
    `Control:` —— 复现/对照实验是把"单次观测≠确认"从口号变成可检字段。缺则 WARN
    (提示补对照或降级), 不硬失败 —— 这是质量提示, 非结构闸门。"""
    ev = run_dir / "evidence.md"
    if not ev.exists():
        return []
    text = ev.read_text(encoding="utf-8", errors="replace")
    warns: list[str] = []
    # 按 `## ` 切分条目
    blocks = re.split(r"(?=^##\s)", text, flags=re.MULTILINE)
    for b in blocks:
        head = b.splitlines()[0].strip() if b.strip() else ""
        if re.search(r"Certainty\s*[:：]\s*(0\.8|1\.0)\b", b):
            if not re.search(r"\b(Replicated|Control)\s*[:：]", b):
                warns.append(
                    f"evidence {head!r}: Certainty>=0.8 但缺 'Replicated:'/'Control:' "
                    "字段 —— 补复现/对照实验, 否则按证据门定义应降级(单次观测≠确认)")
    return warns


def check_coverage(run_dir: Path) -> list[str]:
    """前置防 lump 护栏(警告, 每次 check_run 都报, 不只收口). 读 classify_hosts.py 产出的
    结构化检视台账 coverage.json, 把【独立应用候选】(未识别栈/Spring/Vue-SPA/带 LOGIN·DYN·
    FRAMEWORK·SPA 标记 的可达资产)逐个列出 —— 这些是【不能只按服务器头 lump 带过】、必须
    逐个深挖的。lump 当下就暴露(根源: 检视状态是结构化一等台账, 藏不住), 而非收口才发现。"""
    covs = list(run_dir.glob("**/coverage.json"))
    if not covs:
        return []   # 还没跑 classify_hosts -> 由收口闸门的 'no classify.txt' 警告兜
    try:
        data = json.loads(covs[0].read_text(encoding="utf-8", errors="replace"))
    except Exception:
        return []
    total = data.get("total", 0)
    examined = data.get("examined", 0)
    reachable = data.get("reachable", 0)
    candidates = [a for a in data.get("assets", [])
                  if a.get("reachable") is True
                  and (a.get("stack") in ("?", "SpringBoot-api", "Vue-SPA") or a.get("flags"))]
    warns: list[str] = []
    if candidates:
        names = ", ".join(a["host"] for a in candidates[:15])
        warns.append(
            f"检视覆盖(防lump): 资产 {total} / 已检视内容 {examined} / 可达 {reachable}; "
            f"【独立应用候选 {len(candidates)} 个】须逐个深挖(勿按服务器头 lump): {names}"
            + (" …" if len(candidates) > 15 else ""))
    return warns


def check_ledger_contradiction(run_dir: Path) -> list[str]:
    """台账矛盾护栏(警告): 若某条证据 `Refutes: E-X`, 但 E-X 自己仍 certainty>=0.8 且
    无 superseded/降级/撤回 标记 → 台账里同时挂着"被证伪"和"高置信"两个矛盾态, 会污染
    下游推理(某实战 实战: E-010 整站封锁满分置信度被 E-011 证伪却没降级)。静态可查。"""
    ev = run_dir / "evidence.md"
    if not ev.exists():
        return []
    text = ev.read_text(encoding="utf-8", errors="replace")
    blocks = re.split(r"(?=^##\s+E-)", text, flags=re.MULTILINE)
    entries: dict[str, dict] = {}
    refuted: set[str] = set()
    for b in blocks:
        hm = re.match(r"##\s+(E-\d+)", b.strip())
        if not hm:
            continue
        eid = hm.group(1)
        cm = re.search(r"Certainty\s*[:：]\s*(\d\.\d)", b)
        certainty = float(cm.group(1)) if cm else 0.0
        superseded = bool(re.search(r"superseded|降级|撤回|改判", b, re.I))
        entries[eid] = {"certainty": certainty, "superseded": superseded}
        for line in re.findall(r"Refutes\s*[:：]([^\n]*)", b):
            for rm in re.findall(r"E-\d+", line):
                refuted.add(rm)
    warns: list[str] = []
    for eid in sorted(refuted):
        e = entries.get(eid)
        if e and e["certainty"] >= 0.8 and not e["superseded"]:
            warns.append(
                f"台账矛盾: {eid} 被其它条目 Refutes(证伪), 但 {eid} 仍 certainty={e['certainty']} "
                "且无 superseded/降级标记 —— 被证伪的结论未降级会污染下游, 请降级或标 superseded。")
    return warns


def check_reason_pass(run_dir: Path) -> list[str]:
    """高频 Reason pass 护栏(警告). Reason pass 是每轮选前沿前【重读整个 frontier】的廉价
    习惯, 专治隧道视野(挖一个前沿到底、更高价值的晾着、新证据解锁了也没看)。纯文档纪律会
    在势能里被跳过 —— 正是最需要它的时候(独立复审从软警升硬门就是这个教训)。这里查:
    decisions.md 已推进多轮(>=3 条决策)却一条 `Reason:` 全图重读记录都没有 → 提示。
    存在性检查(可被糊弄, 写一行即过), 故 WARN 不硬卡; 硬门仍是收口的独立复审。"""
    dec = run_dir / "decisions.md"
    if not dec.exists():
        return []
    text = dec.read_text(encoding="utf-8", errors="replace")
    n_decisions = len(re.findall(r"^##\s+D-\d+", text, flags=re.MULTILINE))
    n_reason = len(re.findall(r"^\s*[-*]?\s*Reason\s*[:：]", text, flags=re.MULTILINE))
    if n_decisions >= 3 and n_reason == 0:
        return [
            f"Reason pass(防隧道视野): decisions.md 已 {n_decisions} 条决策却无一条 `Reason:` "
            "全图重读记录 —— 每轮选前沿前应重读【整个 frontier】(所有 open+deferred 前沿, 非只"
            "当前那个), 看有无被新证据解锁、或被忽略的高价值前沿。补 `Reason:` 行(见 WORKFLOW.md "
            "'Reason pass'); 它只重排优先级, 不收口。"]
    return []


# 强收口措辞 —— 出现这些"已穷尽/无可利用/打不动"的断言时, 触发覆盖核验(P0-1)
CLOSURE_CLAIMS = [
    "无攻击面", "无可利用", "探尽", "测尽", "都无法", "全无", "均无确认",
    "打不动", "无法突破", "无未授权", "已穷尽", "no attack surface",
    "exhausted", "nothing exploitable",
]


def check_closure_discipline(run_dir: Path) -> tuple[list[str], list[str]]:
    """过早收口护栏(P0-1). 仅当 report.md 出现【强收口断言】时触发。返回 (errors, warns):

    - **硬错(errors → check_run 失败)**: review.md 无【独立复审/Independent Review】记录。
      self-review 治不了 self-review 偏见; 把"收口必先派独立 Reviewer"从软调用变硬约束
      (某实战 实战: 建了 ④ 仍两次过早收口, 软警告拦不住 → 改硬门)。
    - **软警(warns → 仅提示)**: 无 classify.txt、Closed Front 缺证据、屏障关门无 Refutes。
      这些是质量提示, 收口是否成立属判断, 不硬卡。
    """
    report = run_dir / "report.md"
    if not report.exists():
        return [], []
    rtext = report.read_text(encoding="utf-8", errors="replace")
    if not any(c in rtext for c in CLOSURE_CLAIMS):
        return [], []  # 未声称收口 -> 不触发, 不增日常负担

    errors: list[str] = []
    warns: list[str] = []

    # 硬门: 收口前必须有独立 Reviewer 复审记录
    review = run_dir / "review.md"
    rv = review.read_text(encoding="utf-8", errors="replace") if review.exists() else ""
    if not re.search(r"Independent Review|独立复审", rv):
        errors.append(
            "收口硬门(P0-1): report 含强收口断言, 但 review.md 无【独立复审 / Independent "
            "Review】记录。自评治不了自评偏见; 收口前【必须】派独立 Reviewer 子代理(常驻授权, "
            "见 docs/templates/independent-reviewer.md)并落 review.md。撤回收口措辞或补复审后再过。")

    has_classify = any(run_dir.glob("**/classify*.txt"))
    if not has_classify:
        warns.append(
            "report 含强收口断言(如'无攻击面/探尽/打不动'), 但本 run 无逐资产按内容分类记录"
            "(classify_hosts.py 的 classify.txt) —— 资产可能只按 server 头/recon lump, "
            "未逐个看内容。收口前请跑 `python tools/classify_hosts.py`。")

    fr = run_dir / "frontier.md"
    if fr.exists():
        ftext = fr.read_text(encoding="utf-8", errors="replace")
        # 取 Closed Fronts 区段
        m = re.search(r"##\s*Closed Fronts(.*?)(?=^##\s|\Z)", ftext,
                      re.S | re.MULTILINE)
        if m:
            for block in re.split(r"(?=^###\s)", m.group(1), flags=re.MULTILINE):
                if not block.lstrip().startswith("###"):
                    continue  # 只处理 '### ' 前沿块, 跳过段首残余
                head = block.strip().splitlines()[0][:48]
                if not re.search(r"\bE-\d", block):
                    warns.append(f"frontier Closed Front {head!r}: 关门但未引用证据 ID(E-xxx)"
                                 " —— 散文关门易过早收口, 应附证据。")
                barrier = re.search(r"(WAF|限流|超时|登录门控|不可达|throttl|refused|blocked)",
                                    block, re.I)
                if barrier and not re.search(r"Refutes|证伪|reject|安全处理|参数化|int-cast", block, re.I):
                    warns.append(f"frontier Closed Front {head!r}: 以屏障({barrier.group(0)})关门却无"
                                 " Refutes/正面证据 —— '我够不着'应记 deferred 而非 closed(它安全)。")
    return errors, warns


def main() -> int:
    parser = argparse.ArgumentParser(description="Check a Xunji run directory.")
    parser.add_argument("run_dir", type=Path)
    args = parser.parse_args()

    run_dir = args.run_dir
    if not run_dir.is_absolute():
        run_dir = ROOT / run_dir
    run_dir = run_dir.resolve()

    runs_root = (ROOT / "runs").resolve()
    try:
        run_dir.relative_to(runs_root)
    except ValueError:
        print(f"run directory must be under {runs_root}")
        return 1

    errors: list[str] = []
    for name in REQUIRED_FILES:
        path = run_dir / name
        markers = REQUIRED_MARKERS.get(name, [])
        errors.extend(check_file(path, markers))

    # Optional artifacts: only checked when the file is present.
    for name, markers in OPTIONAL_MARKERS.items():
        path = run_dir / name
        if path.exists():
            errors.extend(check_file(path, markers))

    # Quality warnings (do not fail the structural gate; surface for the driver).
    warnings = check_evidence_certainty(run_dir)
    warnings.extend(check_coverage(run_dir))          # 前置防 lump: 每次都报独立应用候选
    warnings.extend(check_ledger_contradiction(run_dir))
    warnings.extend(check_reason_pass(run_dir))        # 高频 Reason pass: 防隧道视野
    # P0-1 收口硬门: 缺独立复审=硬错(并入 errors), 其余=软警
    closure_errors, closure_warns = check_closure_discipline(run_dir)
    errors.extend(closure_errors)
    warnings.extend(closure_warns)
    if warnings:
        print("warnings")
        for w in warnings:
            print(f"- {w}")

    if errors:
        print("run check failed")
        for error in errors:
            print(f"- {error}")
        return 1

    print("run check passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
