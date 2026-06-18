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

sys.path.insert(0, str(Path(__file__).resolve().parent))
try:
    import graph as _graph   # 派生状态图(同目录); 缺失则跳过图一致性检查
except Exception:
    _graph = None
try:
    import workers as _workers   # 并行 worker 台账(同目录)
except Exception:
    _workers = None
try:
    import replay as _replay     # 重放核实(同目录); 缺失则 --replay-verify 跳过
except Exception:
    _replay = None
from evidence_parse import parse_evidence, write_evidence_index  # 唯一权威证据解析器(已抽出到独立模块)


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
    "hints.md": [
        "# Hints",
        "Kind:",
        "Status:",
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


def evidence_entries_missing_artifact(run_dir: Path) -> list[str]:
    """P1 收口护栏: Certainty>=0.8 的证据条目必须引用一个 run 目录下【真实存在】的
    产物文件 —— 把"声称确认但没存盘"挡在收口外。返回缺产物的条目 head 列表(收口硬门→error)。"""
    return [r["head"] for r in parse_evidence(run_dir)
            if r["confirmed"] and not r["artifacts_present"]]


def check_replay_evidence(run_dir: Path) -> list[str]:
    """操作录像(软警): certainty>=0.8 的【正向确认】建议附 .replay.json 操作录像(probe --save 自动
    生成: 完整请求 + 响应 sha1) —— 让证据可被【重放核实】而非只信描述(B1: 把造假从"P 张图"抬到
    "伪造自洽请求+响应")。软警不硬卡: render/手工/negative 类未必有 probe 录像, 硬门会 FP; 先提示,
    推动"用 probe 验证就留录像", 稳定后可升硬门(同独立复审门当年软→硬的路径)。
    只对【已有产物但其中无 .replay.json】的正向确认提示(完全无产物归 P1 硬门管, 不重叠报)。"""
    warns: list[str] = []
    for r in parse_evidence(run_dir):
        if not (r["confirmed"] and r["id"].startswith("E-")):
            continue
        if r["refutes_any"] and not r["supports"]:
            continue  # 纯 negative 结论不需录像
        arts = r.get("artifacts", [])
        if arts and not any(a.lower().endswith(".replay.json") for a in arts):
            warns.append(
                f"{r['id']}: certainty>=0.8 确认但产物无 .replay.json 操作录像 —— 建议用 "
                "`probe --save` 留录像(完整请求+响应+sha1)以便重放核实, 而非只信描述。")
    return warns


def _summarize_replay(results: list[dict]) -> list[str]:
    """把 replay_run 的结果列表汇总成警告行(纯函数, 可离线单测)。DIVERGED=证据存疑升为显著
    警告(目标可能已改/已修/当时造假); 其余汇总计数。UNREACHABLE 不算失败(够不着≠假)。"""
    counts: dict = {}
    diverged: list[str] = []
    for r in results:
        v = r.get("verdict", "?")
        counts[v] = counts.get(v, 0) + 1
        if v == "DIVERGED":
            diverged.append(f"{r.get('method','?')} {r.get('url','')} "
                            f"({r.get('old_status')}→{r.get('new_status')})")
    warns: list[str] = []
    if diverged:
        warns.append("replay 核实 DIVERGED(证据存疑: 目标可能已改/已修/当时造假, driver 须核对内容是否"
                     "仍是漏洞响应): " + "; ".join(diverged[:8])
                     + (" …" if len(diverged) > 8 else ""))
    if counts:
        summary = ", ".join(f"{k}={v}" for k, v in sorted(counts.items()))
        warns.append(f"replay 核实汇总: {summary} "
                     "(IDENTICAL/CONSISTENT=现实支持; DIVERGED=存疑; UNREACHABLE=够不着≠假; "
                     "SKIPPED-*=写/破坏性/越界未自动重放, 留人工)")
    return warns


def _artifact_keys(rec: dict) -> set:
    """E- 记录引用的产物 → 候选匹配键(小写): 全名 +（直接引 .replay.json 时)去 .replay.json 的名。
    probe 的录像名是【产物全名追加 .replay.json】(sqli.html → sqli.html.replay.json, probe.py:182),
    所以【全名 sqli.html】就能绑(bare-stem 产物 shot 的全名就是 shot, 也对得上 shot.replay.json)。
    【不】再加去扩展名的键 —— 那会让 sqli.replay.json 误绑引用 sqli.json 的无关发现 = 假阴报错
    (Codex 三轮复审 false-fail); 全名匹配已覆盖 真实 / bare-stem / 直接引 三种命名。"""
    out = set()
    for a in rec.get("artifacts", []):
        base = a.replace("\\", "/").split("/")[-1].lower()
        if base:
            out.add(base)                                 # sqli.html / shot
            out.add(re.sub(r"\.replay\.json$", "", base)) # 直接引 sqli.html.replay.json → sqli.html
    out.discard("")
    return out


def _replay_unacked_findings(run_dir: Path, results: list[dict]) -> list[str]:
    """把每条 DIVERGED 录像【绑到它支撑的已确认 E- 发现】(录像 <artifact>.replay.json ↔ 该 artifact,
    全名匹配见 _artifact_keys), 列出未 re-adjudication 的 E-id。只对【承重】分歧较真: 无确认 E- 支撑的
    录像分歧不拦; 该 E- 条目自己有 `- Replay:` = 已处理(逐条目判, 非全局计数, 不会被别处/模板误清)。
    同一产物被多条确认发现引用时, 每条未自带 ack 的都报(不靠 next 只取第一条 → 防遮蔽)。"""
    recs = [r for r in parse_evidence(run_dir) if r["confirmed"]]
    unacked: list[str] = []
    for r in results:
        if r.get("verdict") != "DIVERGED":
            continue
        key = re.sub(r"\.replay\.json$", "",
                     str(r.get("file", "")).replace("\\", "/").split("/")[-1], flags=re.I).lower()
        if not key:
            continue
        for rec in recs:                      # 所有引用该产物的确认发现, 各自判 ack(防同名遮蔽)
            if key in _artifact_keys(rec) and not rec.get("has_replay_ack"):
                unacked.append(rec["id"])
    return sorted(set(unacked))


def run_replay_verify(run_dir: Path) -> tuple[list[str], list[str]]:
    """--replay-verify(断-1): 收口前自动重放核实, 把 replay 从孤岛焊进收口闭环。调 replay.replay_run
    (走 guard / target.md 授权 scope / 幂等 GET 才重放 / DELETE 永不 / 写默认 skip)。慢+默认关。
    返回 (warns, errors): DIVERGED 默认软警; 但【已终版报告 + DIVERGED + 未 re-adjudication】升硬门
    (errors), 堵'跑了重放却放过存疑证据'。仍 opt-in —— 没传 --replay-verify / 没 DIVERGED 都不触发。"""
    if _replay is None:
        return (["replay 核实跳过: 无法加载 replay 模块(同目录 tools/replay.py 缺失?)"], [])
    recs = list(run_dir.glob("**/*.replay.json"))
    if not recs:
        return (["replay 核实: 本 run 无 .replay.json 录像可重放 —— 传感器加 "
                 "`probe --save NAME --run runs/<dir>` 留录像, 高 certainty 证据才可重放核实。"], [])
    try:
        results = _replay.replay_run(run_dir)
    except Exception as e:   # 防御: replay 内部异常不该炸掉整个收口检查
        return ([f"replay 核实异常(已捕获, 不影响其余检查): {e}"], [])
    warns = _summarize_replay(results)
    errors: list[str] = []
    if _report_is_final(run_dir):
        unacked = _replay_unacked_findings(run_dir, results)
        if unacked:
            errors.append(
                "收口硬门(replay 分歧未处理): --replay-verify 对 " + ", ".join(unacked) + " 的录像得 "
                "DIVERGED 且 report 终版, 但这些 E- 条目无 `- Replay:` re-adjudication —— 跑了重放却放过"
                "存疑证据 = 静默收口。逐条处理: 降级该发现(<0.8), 或在该 E- 条目加 `- Replay:` 说明为何"
                "分歧后结论仍成立。(replay 仍 opt-in; 不强制重放、不自动否定发现)")
    return (warns, errors)


def check_dangling_citations(run_dir: Path) -> list[str]:
    """悬空引用护栏(警告): 证据条目 Artifacts: 字段里引用了 run 目录下【不存在】的产物
    —— 引用必须可复核。旧逻辑只要块内任一产物存在就放行, 删掉某个被引文件不会报(E-012:
    删 _ci_*.html 后 E-012 引用静默悬空, 靠人工才发现)。现逐条列出死引用。"""
    warns: list[str] = []
    for r in parse_evidence(run_dir):
        # 只对【显式 Artifacts: 字段】里的引用较真(artifacts_scoped)。否则散文里写的探测路径
        # (如 Action: "...GET /WEB-INF/web.xml") 会被全块兜底误抓成"死引用"(#14 mokwon dogfood FP)。
        if r["artifacts_missing"] and r.get("artifacts_scoped"):
            warns.append(
                f"evidence {r['id']}: Artifacts 字段引用了不存在的产物 {r['artifacts_missing']} —— "
                "死引用无法复核(文件被删/改名/笔误)。修正路径、补存产物、或移除该引用。")
    return warns


def check_evidence_certainty(run_dir: Path) -> list[str]:
    """证据门质量护栏(P0-2): certainty >= 0.8 的条目必须带 `Replicated:` 或
    `Control:` —— 复现/对照是把"单次观测≠确认"从口号变成可检字段。缺则 WARN。"""
    return [f"evidence {r['id']}: Certainty>=0.8 但缺 'Replicated:'/'Control:' 字段 "
            "—— 补复现/对照实验, 否则按证据门定义应降级(单次观测≠确认)"
            for r in parse_evidence(run_dir) if r["confirmed"] and not r["has_control"]]


# 布局漂移(断-2): evidence/ 放传感器证据, classify/ 放 coverage, scripts/ 放 PoC; run 根目录
# 只该有核心 .md + 自动派生的 evidence.json/coverage.json/graph.json。证据/草稿散落根目录虽仍能被
# _resolve_artifact 找到(收口门不坏), 但证据与草稿混作一团、不利审计 —— WARN 提醒归位(不硬失败,
# 历史 run 不受累)。probe/render 加 --run 后裸名/默认产物自动落 evidence/, 正确放法=省事放法。
_PROOF_SUFFIXES = {".html", ".htm", ".png", ".jpg", ".jpeg", ".gif", ".webp", ".js", ".json"}
_ROOT_OK_FILES = {"evidence.json", "coverage.json", "graph.json"}


def _loose_proof_files(run_dir: Path) -> list[str]:
    """run 根目录下散落的证据/草稿文件名(排除白名单派生 json 与子目录内文件)。纯函数, 可单测。"""
    loose = [p.name for p in run_dir.iterdir()
             if p.is_file() and p.name not in _ROOT_OK_FILES
             and p.suffix.lower() in _PROOF_SUFFIXES]
    loose.sort()
    return loose


def check_layout_drift(run_dir: Path) -> list[str]:
    # 只在【收口时】报: 主动验证中根目录有临时产物(试探截图/中间响应)属正常, 每轮唠叨=噪音;
    # 产出终版报告后还散落一地, 才是真审计问题(同 check_shallow_close 的收口节奏)。
    if not _report_is_final(run_dir):
        return []
    loose = _loose_proof_files(run_dir)
    if not loose:
        return []
    shown = ", ".join(loose[:10]) + (" …" if len(loose) > 10 else "")
    return [f"布局漂移(收口): {len(loose)} 个证据/草稿文件散落 run 根目录({shown}) —— "
            "传感器证据应落 evidence/(probe/render 加 --run 自动归位), PoC 落 scripts/, "
            "coverage 落 classify/。根目录只留核心 .md + 自动派生的 evidence/coverage/graph.json。"
            "散落仍可被收口门解析(门不坏), 但证据与草稿混作一团、不利审计。"]


def _recon_cited(run_dir: Path) -> str | None:
    """target.md 的『Existing intel / recon report:』字段若填了真实值(非空/非 N/A),
    返回该值, 否则 None —— 用于判断本 run 是否声明引用了外部 recon/OSINT 情报。"""
    t = run_dir / "target.md"
    if not t.exists():
        return None
    m = re.search(r"Existing intel\s*/\s*recon report\s*[:：]\s*(.+)",
                  t.read_text(encoding="utf-8", errors="replace"))
    if not m:
        return None
    val = m.group(1).strip().strip("`").rstrip()
    low = val.lower()
    if not val or low in ("n/a", "none", "无", "無", "—", "-", "(none)"):
        return None
    if "path or" in low:   # 未填的模板占位 '(path or "none"; …)' 不算引用了 recon
        return None
    return val


def coverage_present(run_dir: Path) -> bool:
    return bool(list(run_dir.glob("**/coverage.json")))


def _load_coverage(run_dir: Path) -> tuple:
    """覆盖三联检的共享输入, 加载一次: (recon值, recon资产数or None, coverage文件在否, coverage数据or None)。
    recon_n=None 表示 recon 路径非 JSON(如 report.md)或读不到 —— 据此跳过数量比对, 不误报。"""
    recon = _recon_cited(run_dir)
    recon_n = None
    if recon:
        try:
            assets = json.loads(Path(recon).read_text(encoding="utf-8", errors="replace")).get("assets", [])
            recon_n = len(assets) if isinstance(assets, list) else 0
        except Exception:
            recon_n = None
    covs = list(run_dir.glob("**/coverage.json"))
    cov_present = bool(covs)
    cov = None
    if covs:
        try:
            cov = json.loads(covs[0].read_text(encoding="utf-8", errors="replace"))
        except Exception:
            cov = None
    return recon, recon_n, cov_present, cov


def check_coverage_health(run_dir: Path) -> list[str]:
    """覆盖台账三联检(警告, 每轮都报, 不只收口; 输入一次加载)。三类失败各一条, 互不重叠:

    ① 防 lump: coverage.json 里的【独立应用候选】(未识别栈/Spring/Vue-SPA/带标记 的可达资产)
       逐个列出 —— 不能只按服务器头 lump, 须逐个深挖。lump 当下就暴露(结构化台账藏不住)。
    ② 台账缺建: target.md 引用了 recon 却无 coverage.json —— 资产清单疑似手工誊录子集(driver
       选择偏见=盲区), 让防 lump 失明(读不到从没建过的台账)。hamastar 根因即此。
    ③ 台账完整性: coverage 资产数 << recon 资产数 —— 子集冒充全量, 蒙混"覆盖门只查在不在"。

    收口硬门(check_closure_discipline)另有 recon&&无coverage 的【硬】失败; 此处只软警、每轮提示。"""
    recon, recon_n, cov_present, cov = _load_coverage(run_dir)
    warns: list[str] = []
    # ① 防 lump 候选(需 coverage 已建且可解析)
    if cov is not None:
        total = cov.get("total", 0)
        examined = cov.get("examined", 0)
        reachable = cov.get("reachable", 0)
        candidates = [a for a in cov.get("assets", [])
                      if a.get("reachable") is True
                      and (a.get("stack") in ("?", "SpringBoot-api", "Vue-SPA") or a.get("flags"))]
        if candidates:
            names = ", ".join(a["host"] for a in candidates[:15])
            warns.append(
                f"检视覆盖(防lump): 资产 {total} / 已检视内容 {examined} / 可达 {reachable}; "
                f"【独立应用候选 {len(candidates)} 个】须逐个深挖(勿按服务器头 lump): {names}"
                + (" …" if len(candidates) > 15 else ""))
    # ② 台账缺建(引用 recon 却无 coverage 文件 —— 用文件在否, 不看可解析性)
    if recon and not cov_present:
        warns.append(
            f"覆盖台账缺建: target.md 引用了 recon 情报({recon[:60]}) 却无 coverage.json "
            "—— 资产清单疑似手工誊录的子集(driver 选择偏见 = run 的盲区)。跑 "
            "`python tools/ingest_recon.py <recon.json>` 折全量资产 + `python tools/"
            "classify_hosts.py <recon.json> --out runs/<t>/classify` 建结构化台账; "
            "防 lump 护栏没有它就失明, 漏挖不会被发现。")
    # ③ 台账完整性(coverage 是 recon 的子集; 仅 recon 可解析为 JSON 时生效)
    if recon and cov is not None and recon_n:
        cov_n = cov.get("total", 0)
        if cov_n < recon_n * 0.8:
            warns.append(
                f"台账完整性(防子集蒙混): coverage.json 只 {cov_n} 个资产, recon 有 {recon_n} 个 —— "
                "台账疑似子集(只 classify 了一部分), 覆盖门会被【存在即过】蒙混。对全量 recon 跑 "
                "classify_hosts(别用子集台账冒充全量), 漏挖才不会藏在没 classify 的资产里。")
    return warns


def _report_is_final(run_dir: Path) -> bool:
    """report.md 是否为【实质终版报告】(而非中途存根): 其 `Evidence IDs:` 行引用了
    >=1 个 E-id, 且其中至少一个在 evidence.md 里已确认(certainty>=0.8)。

    用作【状态式收口信号】—— 把收口纪律的触发从『report 里写了"已穷尽/exhausted"这类
    忏悔措辞』改成『写出了引用确认发现的终版报告』, 堵住"在聊天里宣布完工、run 文件里
    只字不提收口"的【静默收口】漏洞(hamastar run: 行为上收口、report.md 无任何收口措辞
    → _closure_claimed 返回 False → 整个收口闸门被跳过)。闸门审的是文件不是聊天, 且原先
    只在自首时才硬审; 现在产出终版报告即触发, 自首与否都拦得住。"""
    report = run_dir / "report.md"
    if not report.exists():
        return False
    rtext = report.read_text(encoding="utf-8", errors="replace")
    m = re.search(r"Evidence IDs\s*[:：]\s*(.+)", rtext)
    if not m:
        return False
    cited = set(re.findall(r"E-\d+", m.group(1)))
    if not cited:
        return False
    confirmed = {r["id"] for r in parse_evidence(run_dir) if r["confirmed"]}
    return bool(cited & confirmed)


def check_shallow_close(run_dir: Path) -> list[str]:
    """纵深护栏(警告, 每轮). 单 front 的深度投入是 driver 判断, 但"高价值前沿浅尝即弃"是
    漏挖根因(hamastar: RCE 的多个向量各试一两下就放弃)。把【关门时的深度】变成可检信号:
    某 Closed Front 申报 `Current depth: shallow` 却没写 `Vectors tried:`(尝试过的向量类别)
    → 提示补尝试类别, 并说明为何 shallow 即足以 Type B 关闭(而非 deferred)。

    只在 front 【显式申报了 shallow】时报 → 对未申报深度的旧 run / Deferred 前沿不 FP;
    写了 Vectors tried 就不再催(深度已有交代)。只读, 不强卡(深度终究是判断)。

    评估过扩展(强制全 front 申报 depth / 高价值前沿无视深度都催 / moderate 也要 Vectors tried):
    都不做。病根一致 —— 想用更激进的静态规则测"申报深度是否属实", 但 driver 谎报 moderate 逃避
    时静态检查无法反驳(=申报即过的本质局限, 非护栏覆盖不足)。对旧 run/Deferred/异构模板还会
    FP 不可控。用 FP 噪音糊一个测不出的东西只会让护栏变钝被无视, 故保持 shallow-only。"""
    fr = run_dir / "frontier.md"
    if not fr.exists():
        return []
    text = fr.read_text(encoding="utf-8", errors="replace")
    m = re.search(r"##\s*Closed Fronts(.*?)(?=^##\s|\Z)", text, re.S | re.MULTILINE)
    if not m:
        return []
    warns: list[str] = []
    for block in re.split(r"(?=^###\s)", m.group(1), flags=re.MULTILINE):
        if not block.lstrip().startswith("###"):
            continue
        head = block.strip().splitlines()[0][:48]
        dm = re.search(r"Current depth\s*[:：]\s*(.+)", block)
        if not dm:
            continue   # 没申报深度 → 不强报(避免对旧 run / 无该字段的前沿 FP)
        val = dm.group(1).strip().lower()
        first = val.split()[0].rstrip(".,;:") if val.split() else ""
        if first == "shallow" and "moderate" not in val and "deep" not in val:
            if not re.search(r"Vectors?\s*tried\s*[:：]\s*\S", block, re.I):
                warns.append(
                    f"frontier Closed Front {head!r}: 以 depth=shallow 关闭却无 `Vectors tried:` "
                    "—— 高价值前沿浅尝即弃是漏挖根因(hamastar 的 RCE 浅尝教训)。补 `Vectors tried:` "
                    "写清尝试过的【向量类别】, 并说明为何 shallow 即足以 Type B 关闭(而非 deferred)。")
    return warns


def check_ledger_contradiction(run_dir: Path) -> list[str]:
    """台账矛盾护栏(警告): 若某条证据 `Refutes: E-X`, 但 E-X 自己仍 certainty>=0.8 且
    无 superseded/降级/撤回 标记 → 台账里同时挂着"被证伪"和"高置信"两个矛盾态, 会污染
    下游推理(某实战 实战: E-010 整站封锁满分置信度被 E-011 证伪却没降级)。静态可查。"""
    records = parse_evidence(run_dir)
    entries = {r["id"]: r for r in records if r["id"].startswith("E-")}
    refuted: set[str] = set()
    for r in records:
        refuted.update(r["refutes"])
    warns: list[str] = []
    for eid in sorted(refuted):
        e = entries.get(eid)
        if e and e["confirmed"] and not e["superseded"]:
            cmax = max(e["certainties"]) if e["certainties"] else 0.8
            warns.append(
                f"台账矛盾: {eid} 被其它条目 Refutes(证伪), 但 {eid} 仍 certainty={cmax} "
                "且无 superseded/降级标记 —— 被证伪的结论未降级会污染下游, 请降级或标 superseded。")
    return warns


def check_workers(run_dir: Path) -> list[str]:
    """并行 fan-out 护栏(警告). 若有 worker 文件标了 `Status: done` 却没被 driver merge
    (Status 未置 merged), 提示: 并行成果别静默丢, 且【证据门别跳】—— 候选必须过门(>=0.8
    要 Control/复现)才能并入 canonical evidence.md。这是 Cairn 弱点(并行写未确认 Fact 污染
    台账)的解药: 整合由单一 driver 把门。无 workers/ = 串行模式 = 不报。"""
    if _workers is None:
        return []
    try:
        um = _workers.unmerged(run_dir)
    except Exception:
        return []
    if um:
        names = ", ".join(f"{w['file']}({w['front']})" for w in um)
        return [
            f"并行 worker 未整合: {len(um)} 个 worker 已 done 却未 merge —— {names}。driver 须把每条候选"
            "过【证据门】(proposed>=0.8 必须有 Control/复现, 否则降级)、分配 E-id、去重、更新 frontier, "
            "再把该 worker 标 `Status: merged`。别让并行成果丢, 也别跳证据门。"]
    return []


def check_hints(run_dir: Path) -> list[str]:
    """操作者 Hint 护栏(警告). hints.md 把操作者的异步指引从【易丢的聊天】变成【run 目录里
    每轮重读的一等节点】。这里查: 有 `Status: pending` 的 HINT 未吸收 → 提示别让操作者指引
    在势能里烂掉(吸收后标 absorbed 即清警)。无 hints.md = 无操作者指引 = 不报。"""
    hp = run_dir / "hints.md"
    if not hp.exists():
        return []
    text = hp.read_text(encoding="utf-8", errors="replace")
    pending: list[str] = []
    for hid, b in [(m.group(1), b) for b in re.split(r"(?=^##\s+HINT-)", text, flags=re.MULTILINE)
                   for m in [re.match(r"##\s+(HINT-\d+)", b.strip())] if m]:
        if re.search(r"Status\s*[:：]\s*pending", b, re.I):
            pending.append(hid)
    if pending:
        return [
            f"操作者 Hint 未吸收: {', '.join(pending)} 仍 `pending` —— 操作者指引不是聊天里的"
            "一次性话, 是每轮该重读的一等输入。按 Kind 吸收(directive 照做 / claim 走证据门验 / "
            "constraint 当软规则守), 然后标 `Status: absorbed` 并链上 D-xxx; 或写明为何不采纳。"]
    return []


def check_graph_consistency(run_dir: Path) -> list[str]:
    """派生状态图一致性护栏(警告). 复用 graph.py 解析 H/F/E 节点与 Unlocked-by/Unlocks 边,
    只报两类【显式边与前沿状态矛盾】的高信号情形(悬挂 Fact / 孤儿假设属软提示, 留给
    graph.py 视图, 这里不报以免噪声):

    - **unlocked-but-deferred**: 某前沿被已确认 Fact(certainty>=0.8)解锁(Unlocked-by/Unlocks
      边), 却仍躺在 Deferred —— 前置已证、却没回头打(典型漏挖)。
    - **closed-but-unlocked**: 某前沿已 Closed, 却被一个已确认 Fact 解锁 —— 关门与解锁互相矛盾,
      应重开。
    """
    if _graph is None:
        return []
    try:
        view = _graph.derive_view(_graph.build_graph(run_dir))
    except Exception:
        return []
    warns: list[str] = []
    for u in view.get("unlocked_deferred", []):
        warns.append(
            f"状态图: 前沿 {u['front']} 已被已确认 Fact {u['by']} 解锁, 却仍在 Deferred —— "
            "前置已证应回头激活它, 别让它躺着(典型漏挖)。跑 `python tools/graph.py` 看全图。")
    for u in view.get("closed_but_unlocked", []):
        warns.append(
            f"状态图矛盾: 前沿 {u['front']} 已 Closed, 却被已确认 Fact {u['by']} 解锁 —— "
            "关门与解锁互斥, 应重开该前沿或撤回那条 Unlocks 边。")
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

# Negators that FLIP a closure claim into a non-claim, so an honest disclaimer like
# "非已穷尽" / "未探尽" / "not exhausted" does NOT spuriously trip the over-closure
# gate (it did on a real run: "非已穷尽" matched the substring "已穷尽").
_NEG_CJK = "非未没"
_NEG_EN = ("not ", "no ", "n't ", "never ", "without ", "isn't ", "aren't ", "wasn't ", "yet to ")


def _closure_claimed(text: str) -> bool:
    """True iff text contains a NON-negated closure assertion. Substring match (as
    before) but skips occurrences immediately preceded by a negator."""
    t = text.lower()
    for claim in CLOSURE_CLAIMS:
        c = claim.lower()
        start = 0
        while True:
            i = t.find(c, start)
            if i < 0:
                break
            prevchar = t[i - 1] if i > 0 else ""
            window = t[max(0, i - 10):i]
            if (prevchar and prevchar in _NEG_CJK) or any(window.endswith(n) for n in _NEG_EN):
                start = i + len(c)
                continue
            return True
    return False


def check_closure_discipline(run_dir: Path) -> tuple[list[str], list[str]]:
    """过早收口护栏(P0-1). 触发条件 = report.md 出现【强收口断言】(自首式) **或**
    report.md 已是【实质终版报告】(状态式 _report_is_final: 引用了已确认发现)。后者堵住
    "聊天里宣布完工、文件里不写收口措辞"的【静默收口】漏洞(hamastar run 实测: 收口闸门
    因 report 无措辞被整段跳过, 30+ 资产漏挖却"run check passed")。返回 (errors, warns):

    - **硬错(errors → check_run 失败)**:
      ① review.md 无【独立复审/Independent Review】记录(self-review 治不了 self-review 偏见);
      ② Certainty>=0.8 的证据未引用真实产物(假证据);
      ③ 引用了 recon 情报却无 coverage.json(覆盖台账缺建 = 漏挖盲区, 不能在没建全量台账时收口)。
    - **软警(warns → 仅提示)**: 无 classify.txt、Closed Front 缺证据、屏障关门无 Refutes。
    """
    report = run_dir / "report.md"
    if not report.exists():
        return [], []
    rtext = report.read_text(encoding="utf-8", errors="replace")
    if not (_closure_claimed(rtext) or _report_is_final(run_dir)):
        return [], []  # 未声称收口、也非终版报告 -> 不触发, 不增日常负担

    errors: list[str] = []
    warns: list[str] = []

    # 硬门(覆盖台账): 引用了 recon 情报却没把它折成 coverage.json, 等于资产清单只是手工
    # 誊录的子集 —— 不能在没建全量结构化台账的情况下产出终版报告/宣布收口(hamastar 根因)。
    recon = _recon_cited(run_dir)
    if recon and not coverage_present(run_dir):
        errors.append(
            "收口硬门(覆盖台账): target.md 引用了 recon 情报却无 coverage.json —— 资产清单"
            "疑似手工誊录的子集, 漏挖无法被发现。先跑 ingest_recon + classify_hosts 把【全量】"
            "资产折成结构化台账并逐个深挖独立应用候选, 再收口; 不能在台账缺建时出终版报告。")

    # 硬门(漏报一致性): evidence 里【已确认(certainty>=0.8)且非排除性、未降级】的正向发现,
    # 必须进 report 的确认发现/证据清单 —— 否则是漏报。hamastar 实测: E-017 满分 CRITICAL 越权
    # 没进 report(还反向称资产"不可达"), check_run 当时放行, 异构复审(Codex)才逮到。纯静态可查,
    # 不属"申报即过"那类测不出的(只比对 ID 在不在, 不判断申报内容真假)。
    # report_body: 先剥代码块/注释(防 ```/<!-- --> 里的 E-id 假装"已报"—— 与指纹门 S2 同类
    # bypass, Codex dogfood 复审逮到, 同一坑我在指纹门修过又在这犯), 再剥头部机械列全部 ID 的行
    # (Evidence ID/IDs/ID(s) 变体, 不依赖冒号)。残留(contrived, driver 不会自伤): 换行另起一行
    # 列 ID、正文显式写"E-x 不报"仍算引用; 模板是同行列 IDs。
    report_body = re.sub(r"```.*?```|<!--.*?-->", "", rtext, flags=re.S)
    report_body = re.sub(r"(?im)^\s*Evidence\s+IDs?.*$", "", report_body)
    cited_ids = set(re.findall(r"E-\d+", report_body))
    missing_hi = [r["id"] for r in parse_evidence(run_dir)
                  if r["id"].startswith("E-") and r["confirmed"] and not r["superseded"]
                  # 纯 negative(有 Refutes 且无 Supports)才豁免; mixed(Supports+Refutes)的确认
                  # 正向发现仍须报(WARN3, Codex 复审)。
                  and not (r["refutes_any"] and not r["supports"])
                  and r["id"] not in cited_ids]
    if missing_hi:
        errors.append(
            f"收口硬门(漏报一致性): {', '.join(sorted(missing_hi))} 在 evidence 里已确认"
            "(certainty>=0.8、非 Refutes、未降级)却没进 report 确认发现/证据清单 —— 漏报"
            "(hamastar E-017 满分 CRITICAL 越权漏报即此类)。把它们提进 report 确认发现, 或在 "
            "evidence 里降级 / 标 Refutes / 标 superseded。")

    # 硬门(指纹入库): 终版报告须申报本 run 的指纹入库情况 —— 每次渗透收口都入库喂飞轮
    # (下次同栈直接识别 + 调已知弱点锚)。缺申报=硬错; 申报"无"却有独立应用候选=软警(疑似漏入库)。
    # 剥代码块/注释再找申报, 防 ```/<!-- --> 里的字段被当真申报(复审 S2)。
    fp_scan = re.sub(r"```.*?```|<!--.*?-->", "", rtext, flags=re.S)
    fp_m = re.search(r"Fingerprints? captured\s*[:：]\s*(.*)", fp_scan, re.I)
    fp_val = fp_m.group(1).strip() if fp_m else ""
    # 实质申报的判据 = 含 `knowledge/` 入库路径(比"否定词正则"稳健: 不会把"无法测X; Y→knowledge/y.md"
    # 这种以"无/none"开头的真实申报误判为空 —— 复审 S1)。无路径 = 真没新指纹 或 识别了却没入库,
    # 两者在有独立应用候选时都该提示。
    if not fp_m:
        errors.append(
            "收口硬门(指纹入库): report 无 `Fingerprints captured:` 申报 —— 每次渗透收口都须申报"
            "识别到的产品指纹是否已入 knowledge/ grounding 库(喂飞轮: 下次同栈直接识别+调弱点锚)。"
            "写明 '<产品> → knowledge/<id>.md', 或诚实声明 '无新指纹'。")
    elif "knowledge/" not in fp_val.lower():
        covs = list(run_dir.glob("**/coverage.json"))
        cand = 0
        if covs:
            try:
                data = json.loads(covs[0].read_text(encoding="utf-8", errors="replace"))
                cand = sum(1 for a in data.get("assets", [])
                           if a.get("reachable") is True
                           and (a.get("stack") in ("?", "SpringBoot-api", "Vue-SPA") or a.get("flags")))
            except Exception:
                cand = 0
        if cand:
            warns.append(
                f"指纹入库(软警): Fingerprints captured 未给出 knowledge/ 入库路径, 但 coverage 有 "
                f"{cand} 个独立应用候选(未识别栈/带攻击面标记) —— 确认这些不是该入 knowledge/ 的"
                "新产品指纹, 别让飞轮空转。")

    # 硬门: 收口前必须有独立 Reviewer 复审记录
    review = run_dir / "review.md"
    rv = review.read_text(encoding="utf-8", errors="replace") if review.exists() else ""
    if not re.search(r"Independent Review|独立复审", rv):
        errors.append(
            "收口硬门(P0-1): report 含强收口断言, 但 review.md 无【独立复审 / Independent "
            "Review】记录。自评治不了自评偏见; 收口前【必须】派独立 Reviewer 子代理(常驻授权, "
            "见 review/independent-reviewer.md)并落 review.md。撤回收口措辞或补复审后再过。")

    # 硬门(P1): 收口时每条 Certainty>=0.8 必须引用 run 目录下真实存在的产物文件。
    # 结构闸门只查字段在不在, 查不出"声称确认却无产物"; 实战两次复审都抓到这类假证据。
    for head in evidence_entries_missing_artifact(run_dir):
        errors.append(
            f"收口硬门(P1): evidence {head!r} Certainty>=0.8 但未引用任何 run 目录下"
            "【真实存在】的产物文件 —— 确认级结论必须可复核。把 --save 的产物路径写进该条目"
            "(html/json/png/jpg/txt 或 render_* 目录), 或把 certainty 降级。")

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


def _selftest() -> int:
    """Regression for the structured evidence parser (parse_evidence + the gates that
    consume it). Mirrors check_hook's self-testing pattern. No network, no run dir."""
    import tempfile
    d = Path(tempfile.mkdtemp())
    (d / "ev_real.html").write_text("x" * 10, encoding="utf-8")
    (d / "evidence.md").write_text(
        "# Evidence Ledger\n\n"
        "## E-001 — confirmed, artifact present, has control\n"
        "- Replicated: yes\n- Artifacts: `ev_real.html`\n- Certainty: 1.0\n"
        "- Supports: H-002. Refutes: —. Next: prove later (E-002)\n\n"
        "## E-002 — split certainty; dangling citation; prose filename elsewhere\n"
        "- mentions jquery-3.6.0.min.js and ais.webform.js in prose (not citations)\n"
        "- Control: baseline vs payload\n- Artifacts: `ev_real.html`, `ev_DELETED.html`\n"
        "- Certainty (SPLIT): sub-A = **1.0**; sub-B = 0.5\n\n"
        "## E-003 — confirmed, no control, really refutes E-001\n"
        "- Artifacts: `ev_real.html`\n- Certainty: 0.8\n- Refutes: E-001\n\n"
        "## E-004 — off-doctrine certainty (0.9) must still count as confirmed\n"
        "- Replicated: yes\n- Artifacts: `ev_real.html`\n- Certainty: 0.9\n\n"
        "## E-005 — downgraded; parenthetical note mentions grid numbers (must NOT re-confirm)\n"
        "- Replicated: yes\n- Artifacts: `ev_real.html`\n"
        "- Certainty: 0.5 (降级: 原 0.8 误用, 补存可升回 1.0)\n\n"
        "## E-006 — multi-line split certainty (regression lock, N2)\n"
        "- Replicated: yes\n- Artifacts: `ev_real.html`\n"
        "- Certainty:\n  - sub-A = 1.0\n  - sub-B = 0.5\n- Supports: H-001\n\n"
        "## E-007 — value itself in parens (S1 fix: off-grid must still catch)\n"
        "- Replicated: yes\n- Artifacts: `ev_real.html`\n- Certainty: (0.8)\n",
        encoding="utf-8")
    recs = parse_evidence(d)
    byid = {r["id"]: r for r in recs}
    checks = [
        ("preamble not counted", len(recs) == 7),
        ("split certainty -> confirmed", byid["E-002"]["confirmed"] is True),
        ("off-doctrine 0.9 -> confirmed (C1)", byid["E-004"]["confirmed"] is True),
        ("downgrade w/ grid nums in note -> NOT confirmed (the 2026-06-17 fix)", byid["E-005"]["confirmed"] is False),
        ("multi-line split certainty -> confirmed (N2 regression)", byid["E-006"]["confirmed"] is True),
        ("certainty value inside parens -> confirmed (S1 fix)", byid["E-007"]["confirmed"] is True),
        ("dangling citation detected", byid["E-002"]["artifacts_missing"] == ["ev_DELETED.html"]),
        ("prose filenames not cited", not any("jquery" in a or "webform" in a
                                              for a in byid["E-002"]["artifacts"])),
        ("inline Next:(E-002) not swept into Refutes", byid["E-001"]["refutes"] == []),
        ("real refute detected", byid["E-003"]["refutes"] == ["E-001"]),
        ("dangling warns for E-002 only", [w for w in check_dangling_citations(d)
                                           if "E-002" in w] and not any(
            "E-001" in w or "E-003" in w for w in check_dangling_citations(d))),
        ("no-control entry flagged (E-003)", any("E-003" in w
                                                 for w in check_evidence_certainty(d))),
        ("control entries not flagged", not any(("E-001" in w or "E-002" in w)
                                                for w in check_evidence_certainty(d))),
        ("contradiction: refuted-but-confirmed E-001", any("E-001" in w
                                                           for w in check_ledger_contradiction(d))),
        ("no confirmed-missing-artifact FP", evidence_entries_missing_artifact(d) == []),
    ]

    # --- coverage-built + 状态式收口触发 (hamastar 修复回归) ---
    d2 = Path(tempfile.mkdtemp())
    (d2 / "ev.html").write_text("x" * 10, encoding="utf-8")
    (d2 / "evidence.md").write_text(
        "# Evidence Ledger\n\n## E-001 — confirmed\n"
        "- Replicated: yes\n- Artifacts: `ev.html`\n- Certainty: 1.0\n",
        encoding="utf-8")
    (d2 / "target.md").write_text(
        "# Target\n- Existing intel / recon report: /path/recon.json\n", encoding="utf-8")
    (d2 / "report.md").write_text("# Report\nEvidence IDs: E-001\n", encoding="utf-8")
    _built = lambda rd: [w for w in check_coverage_health(rd) if "覆盖台账缺建" in w]  # ② 缺建子警
    cov_warn_before = _built(d2)
    final_before = _report_is_final(d2)
    cerr_before, _ = check_closure_discipline(d2)
    (d2 / "coverage.json").write_text(
        '{"total":1,"examined":1,"reachable":1,"assets":[]}', encoding="utf-8")
    cov_warn_after = _built(d2)
    cerr_after, _ = check_closure_discipline(d2)
    # control: no recon cited -> no coverage gate (avoid FP on operator-given targets)
    d3 = Path(tempfile.mkdtemp())
    (d3 / "target.md").write_text("# Target\n- Existing intel / recon report: N/A\n", encoding="utf-8")
    checks += [
        ("recon cited + no coverage -> warn", bool(cov_warn_before)),
        ("real report (confirmed E-id) -> final (state-trigger)", final_before is True),
        ("final report + no coverage -> closure HARD error", any("覆盖台账" in e for e in cerr_before)),
        ("coverage built -> coverage warn clears", cov_warn_after == []),
        ("coverage built -> closure coverage error clears", not any("覆盖台账" in e for e in cerr_after)),
        ("no recon cited -> no coverage gate (no FP)", _built(d3) == [] and _recon_cited(d3) is None),
    ]

    # --- 纵深护栏 (check_shallow_close) + recon 占位排除 (P0-3) ---
    d4 = Path(tempfile.mkdtemp())
    (d4 / "frontier.md").write_text(
        "# Frontier\n## Open Fronts\n## Deferred Fronts\n## Closed Fronts\n\n"
        "### F-001 shallow no vectors\n- Current depth: shallow\n- Why closed: x\n\n"
        "### F-002 shallow with vectors\n- Current depth: shallow\n- Vectors tried: SQLi, upload, deser\n\n"
        "### F-003 deep\n- Current depth: deep\n- Why closed: proven\n",
        encoding="utf-8")
    sc = check_shallow_close(d4)
    d5 = Path(tempfile.mkdtemp())
    (d5 / "target.md").write_text(
        '# Target\n- Existing intel / recon report: (path or "none"; ingest first)\n', encoding="utf-8")
    checks += [
        ("shallow-close w/o Vectors tried -> warn (F-001)", any("F-001" in w for w in sc)),
        ("shallow-close WITH Vectors tried -> no warn (F-002)", not any("F-002" in w for w in sc)),
        ("deep-close -> no warn (F-003)", not any("F-003" in w for w in sc)),
        ("recon template placeholder -> not cited (no FP)", _recon_cited(d5) is None),
    ]

    # --- 指纹入库收口门 (任务1) ---
    d6 = Path(tempfile.mkdtemp())
    (d6 / "ev.html").write_text("x" * 10, encoding="utf-8")
    (d6 / "evidence.md").write_text(
        "# Evidence Ledger\n## E-001\n- Replicated: y\n- Artifacts: `ev.html`\n- Certainty: 1.0\n", encoding="utf-8")
    (d6 / "review.md").write_text("# Review\n## Independent Review\n- ok\n", encoding="utf-8")
    (d6 / "target.md").write_text("# Target\n- Existing intel / recon report: none\n", encoding="utf-8")
    (d6 / "report.md").write_text("# Report\nEvidence IDs: E-001\n", encoding="utf-8")
    fp_err_missing, _ = check_closure_discipline(d6)
    (d6 / "report.md").write_text(
        "# Report\nEvidence IDs: E-001\nFingerprints captured: FooCMS → knowledge/foo.md\n", encoding="utf-8")
    fp_err_ok, _ = check_closure_discipline(d6)
    (d6 / "report.md").write_text("# Report\nEvidence IDs: E-001\nFingerprints captured: 无新指纹\n", encoding="utf-8")
    (d6 / "coverage.json").write_text(
        json.dumps({"total": 1, "examined": 1, "reachable": 1,
                    "assets": [{"host": "a", "reachable": True, "stack": "?", "flags": ["LOGIN"]}]}), encoding="utf-8")
    _, fp_warn = check_closure_discipline(d6)
    (d6 / "report.md").write_text(
        "# Report\nEvidence IDs: E-001\nFingerprints captured: 无法测产品平台; 主站 WP → knowledge/wp.md\n",
        encoding="utf-8")
    _, fp_warn_s1 = check_closure_discipline(d6)
    (d6 / "report.md").write_text(
        "# Report\nEvidence IDs: E-001\n<!-- Fingerprints captured: x -->\n", encoding="utf-8")
    fp_err_s2, _ = check_closure_discipline(d6)
    checks += [
        ("missing Fingerprints captured -> hard error", any("指纹入库" in e for e in fp_err_missing)),
        ("Fingerprints captured filled -> no fp hard error", not any("收口硬门(指纹入库)" in e for e in fp_err_ok)),
        ("'无新指纹' + candidates -> soft warn", any("指纹入库(软警)" in w for w in fp_warn)),
        ("'无…' WITH knowledge path -> no soft warn (S1)", not any("指纹入库(软警)" in w for w in fp_warn_s1)),
        ("Fingerprints only in comment -> hard error (S2)", any("收口硬门(指纹入库)" in e for e in fp_err_s2)),
    ]

    # --- 台账完整性 (check_coverage_health ③ 子警, 任务8 + 任务#4 合并) ---
    _complete = lambda rd: [w for w in check_coverage_health(rd) if "台账完整性" in w]  # ③ 子集蒙混
    d7 = Path(tempfile.mkdtemp())
    recon_j = d7 / "recon.json"
    recon_j.write_text(json.dumps({"assets": [{"host": f"h{i}"} for i in range(100)]}), encoding="utf-8")
    (d7 / "target.md").write_text(
        f"# Target\n- Existing intel / recon report: {recon_j}\n", encoding="utf-8")
    (d7 / "coverage.json").write_text(json.dumps({"total": 50, "assets": []}), encoding="utf-8")
    cc_subset = _complete(d7)
    (d7 / "coverage.json").write_text(json.dumps({"total": 95, "assets": []}), encoding="utf-8")
    cc_full = _complete(d7)
    d8b = Path(tempfile.mkdtemp())
    (d8b / "target.md").write_text("# Target\n- Existing intel / recon report: /x/report.md\n", encoding="utf-8")
    (d8b / "coverage.json").write_text(json.dumps({"total": 1, "assets": []}), encoding="utf-8")
    cc_nonjson = _complete(d8b)
    checks += [
        ("coverage subset (50/100) -> warn", bool(cc_subset)),
        ("coverage full (95/100) -> no warn", cc_full == []),
        ("recon path non-JSON -> skip (no FP)", cc_nonjson == []),
    ]

    # --- 漏报一致性门 (report↔evidence 高certainty一致, Codex 暴露的缺口) ---
    d9 = Path(tempfile.mkdtemp())
    for n in ("a.html", "b.html", "c.html"):
        (d9 / n).write_text("x" * 10, encoding="utf-8")
    (d9 / "evidence.md").write_text(
        "# Evidence Ledger\n"
        "## E-200: positive missing from report\n- Certainty: 1.0\n- Supports: H-001\n"
        "- Saved artifacts: a.html\n\n"
        "## E-201: refutes-only negative (Refutes hypothesis, no Supports)\n- Certainty: 0.8\n"
        "- Refutes: H-002\n- Saved artifacts: b.html\n\n"
        "## E-202: positive but cited in report body\n- Certainty: 1.0\n- Supports: H-003\n"
        "- Saved artifacts: c.html\n\n"
        "## E-203: downgraded\n- Certainty: 0.5 (降级 2026 从 1.0)\n- Supports: H-004\n\n"
        "## E-204: positive cited only in code block (bypass)\n- Certainty: 1.0\n"
        "- Supports: H-005\n- Saved artifacts: a.html\n\n"
        "## E-205: positive cited only in HTML comment (bypass)\n- Certainty: 1.0\n"
        "- Supports: H-006\n- Saved artifacts: a.html\n\n"
        "## E-206: mixed Supports+Refutes positive\n- Certainty: 1.0\n- Supports: H-007\n"
        "- Refutes: H-008\n- Saved artifacts: a.html\n",
        encoding="utf-8")
    (d9 / "report.md").write_text(
        "# Report\nEvidence IDs: E-200, E-201, E-202, E-203, E-204, E-205, E-206\n\n"
        "## 确认发现\n### 1. finding\n- 证据: E-202\n\n"
        "```\nsample E-204 in a code block\n```\n\n<!-- E-205 in a comment -->\n",
        encoding="utf-8")
    mc_err, _ = check_closure_discipline(d9)
    mc_miss = [e for e in mc_err if "漏报一致性" in e]
    # header 变体直接测正则(不依赖冒号, 覆盖 'IDs :' 空格 / 'ID(s):')
    hv = re.sub(r"(?im)^\s*Evidence\s+IDs?.*$", "",
                "# R\nEvidence IDs : E-300\nEvidence ID(s): E-301\nbody E-302\n")
    checks += [
        ("漏报: confirmed positive 缺失 -> 含 E-200", any("E-200" in e for e in mc_miss)),
        ("漏报: refutes-only(无Supports) 豁免 E-201", not any("E-201" in e for e in mc_miss)),
        ("漏报: report 正文引用豁免 E-202", not any("E-202" in e for e in mc_miss)),
        ("漏报: 已降级豁免 E-203", not any("E-203" in e for e in mc_miss)),
        ("漏报: 代码块引用不算(bypass) E-204", any("E-204" in e for e in mc_miss)),
        ("漏报: 注释引用不算(bypass) E-205", any("E-205" in e for e in mc_miss)),
        ("漏报: mixed Supports+Refutes 不豁免 E-206", any("E-206" in e for e in mc_miss)),
        ("漏报: header 变体(空格/ID(s))被剥, E-302 正文保留",
         "E-300" not in hv and "E-301" not in hv and "E-302" in hv),
        ("漏报门触发一次", len(mc_miss) == 1),
    ]

    # --- auto-peer-review 触发/幂等逻辑(不调真实模型) ---
    d10 = Path(tempfile.mkdtemp())
    (d10 / "report.md").write_text(
        "# Report\nEvidence IDs: E-001\n## 确认发现\n- 证据: E-001\n", encoding="utf-8")
    (d10 / "review.md").write_text("# Review\n## Independent Review\n- done\n", encoding="utf-8")
    rv_before = (d10 / "review.md").read_text(encoding="utf-8")
    _maybe_auto_peer_review(d10)   # 幂等: 已有独立复审记录 -> 直接 return, 不改 review.md/不调模型
    rv_after = (d10 / "review.md").read_text(encoding="utf-8")
    d11 = Path(tempfile.mkdtemp())
    (d11 / "report.md").write_text("# Report\n草稿, 无收口断言无确认引用\n", encoding="utf-8")
    _maybe_auto_peer_review(d11)   # 未收口 -> return, 不建 review.md
    checks += [
        ("auto-review 幂等: 已有独立复审 -> review.md 不变", rv_before == rv_after),
        ("auto-review: 未收口 -> 不触发(不建 review.md)", not (d11 / "review.md").exists()),
    ]

    # --- 操作录像软警 (check_replay_evidence) ---
    d12 = Path(tempfile.mkdtemp())
    (d12 / "evidence.md").write_text(
        "# Evidence Ledger\n"
        "## E-300: confirmed, html only (无录像)\n- Certainty: 1.0\n- Supports: H-1\n"
        "- Saved artifacts: probe_x.html\n\n"
        "## E-301: confirmed, has replay\n- Certainty: 1.0\n- Supports: H-2\n"
        "- Saved artifacts: probe_y.html, probe_y.replay.json\n\n"
        "## E-302: negative refutes (无 supports)\n- Certainty: 0.8\n- Refutes: H-3\n"
        "- Saved artifacts: probe_z.html\n",
        encoding="utf-8")
    rep_w = check_replay_evidence(d12)
    checks += [
        ("录像软警: html-only confirmed -> 提示 E-300", any("E-300" in w for w in rep_w)),
        ("录像软警: 有 .replay.json 不提示 E-301", not any("E-301" in w for w in rep_w)),
        ("录像软警: negative 不提示 E-302", not any("E-302" in w for w in rep_w)),
    ]

    # 布局漂移(断-2): 检测逻辑(纯函数)+ 收口门控(只在终版报告产出后才报)
    d13 = d / "drift_20260101"
    (d13 / "evidence").mkdir(parents=True)
    (d13 / "ev_loose.html").write_text("x", encoding="utf-8")           # 散落证据
    (d13 / "shot.png").write_text("x", encoding="utf-8")                # 散落截图
    (d13 / "evidence.json").write_text("{}", encoding="utf-8")          # 派生, 白名单
    (d13 / "coverage.json").write_text("{}", encoding="utf-8")          # 白名单
    (d13 / "evidence" / "clean.html").write_text("x", encoding="utf-8")  # 已归位, 不算
    loose = _loose_proof_files(d13)
    checks += [
        ("布局漂移检测: 抓到散落 ev_loose.html/shot.png", "ev_loose.html" in loose and "shot.png" in loose),
        ("布局漂移检测: 不误报白名单 evidence.json/coverage.json", "evidence.json" not in loose and "coverage.json" not in loose),
        ("布局漂移检测: evidence/ 子目录内文件不算散落", "clean.html" not in loose),
        # 收口门控: 无终版报告 -> 静默(主动验证期不唠叨)
        ("布局漂移: 无终版报告时静默(降噪)", check_layout_drift(d13) == []),
    ]
    # 给 d13 补一个引用确认发现的终版报告 -> 此时才该报
    (d13 / "evidence.md").write_text(
        "# Evidence Ledger\n\n## E-900\n- Replicated: yes\n- Artifacts: `evidence/clean.html`\n- Certainty: 1.0\n",
        encoding="utf-8")
    (d13 / "report.md").write_text("# Report\nEvidence IDs: E-900\n", encoding="utf-8")
    drift_w = check_layout_drift(d13)
    checks.append(("布局漂移: 终版报告产出后散落 -> WARN", bool(drift_w) and "ev_loose.html" in drift_w[0]))

    # 断-3 replay 分歧门(#3): 纯决策真值表 + re-adjudication 检测(保留 opt-in, 只堵"跑了又装没看见")
    # 断-3 replay 分歧门(#3, 真·逐发现绑定 + 真实录像命名 <artifact>.replay.json —— Codex 两轮复审)
    d14 = Path(tempfile.mkdtemp())
    (d14 / "evidence").mkdir()
    (d14 / "evidence" / "sqli.html").write_text("x", encoding="utf-8")
    (d14 / "evidence" / "xss.html").write_text("x", encoding="utf-8")
    (d14 / "evidence.md").write_text(
        "# Evidence Ledger\n"
        "## E-1\n- Certainty: 1.0\n- Artifacts: `evidence/sqli.html`\n"
        "- Replay: 目标改版, 已核对仍是注入差异, 结论保留\n\n"
        "## E-2\n- Certainty: 1.0\n- Artifacts: `evidence/xss.html`\n",
        encoding="utf-8")
    (d14 / "review.md").write_text("# Review\n## R-1\n- Replay: (模板示例字段) 略\n", encoding="utf-8")
    # 真实命名(probe.py:182 追加): 产物 sqli.html 的录像是 sqli.html.replay.json
    res = [{"file": "evidence/sqli.html.replay.json", "verdict": "DIVERGED"},
           {"file": "evidence/xss.html.replay.json", "verdict": "DIVERGED"}]
    unacked = _replay_unacked_findings(d14, res)
    checks += [
        ("replay 绑定(真实命名 .html.replay.json 能绑上, 非 owner=None 漏掉): 只报 E-2", unacked == ["E-2"]),
        ("replay 绑定: E-1 自身 `- Replay:` -> 不报(别处/模板 Replay 不误清, 非全局计数)", "E-1" not in unacked),
        ("replay 绑定: 无 E- 支撑的分歧不拦(非承重)",
         _replay_unacked_findings(d14, [{"file": "evidence/orphan.html.replay.json", "verdict": "DIVERGED"}]) == []),
        ("replay 绑定: 无 DIVERGED -> 空(opt-in/目标变更不罚)",
         _replay_unacked_findings(d14, [{"file": "evidence/sqli.html.replay.json", "verdict": "IDENTICAL"}]) == []),
    ]
    # bare-stem 命名也兼容(产物 shot ↔ shot.replay.json)
    d16 = Path(tempfile.mkdtemp())
    (d16 / "evidence").mkdir()
    (d16 / "evidence" / "shot").write_text("x", encoding="utf-8")
    (d16 / "evidence.md").write_text(
        "# Evidence Ledger\n## E-9\n- Certainty: 1.0\n- Artifacts: `evidence/shot`\n", encoding="utf-8")
    checks.append(("replay 绑定: bare-stem shot ↔ shot.replay.json 也绑上",
                   _replay_unacked_findings(d16, [{"file": "evidence/shot.replay.json", "verdict": "DIVERGED"}]) == ["E-9"]))
    # 不过度匹配(防 false-fail): 录像 sqli.replay.json 对应 bare-stem 产物 sqli, 不该误绑引用 sqli.json
    # 的无关发现(那条的录像应是 sqli.json.replay.json)。Codex 三轮复审逮到的 false-fail。
    d17 = Path(tempfile.mkdtemp())
    (d17 / "evidence").mkdir()
    (d17 / "evidence" / "sqli.json").write_text("x", encoding="utf-8")
    (d17 / "evidence.md").write_text(
        "# Evidence Ledger\n## E-7\n- Certainty: 1.0\n- Artifacts: `evidence/sqli.json`\n", encoding="utf-8")
    checks.append(("replay 绑定: sqli.replay.json 不误绑 sqli.json 发现(防 false-fail)",
                   _replay_unacked_findings(d17, [{"file": "evidence/sqli.replay.json", "verdict": "DIVERGED"}]) == []))
    # 终版报告但根目录干净(证据都在 evidence/) -> 仍静默
    d14 = d / "clean_20260101"
    (d14 / "evidence").mkdir(parents=True)
    (d14 / "evidence" / "ok.html").write_text("x", encoding="utf-8")
    (d14 / "graph.json").write_text("{}", encoding="utf-8")
    (d14 / "evidence.md").write_text(
        "# Evidence Ledger\n\n## E-901\n- Replicated: yes\n- Artifacts: `evidence/ok.html`\n- Certainty: 1.0\n",
        encoding="utf-8")
    (d14 / "report.md").write_text("# Report\nEvidence IDs: E-901\n", encoding="utf-8")
    checks.append(("布局漂移: 收口且根目录干净 -> 静默", check_layout_drift(d14) == []))

    # 断-1 replay 接入: _summarize_replay 汇总逻辑(纯函数, 离线; 实网重放走 --replay-verify 不在此测)
    rv = _summarize_replay([
        {"verdict": "IDENTICAL", "method": "GET", "url": "http://x/a"},
        {"verdict": "DIVERGED", "method": "GET", "url": "http://x/b", "old_status": 200, "new_status": 404},
        {"verdict": "SKIPPED-WRITE", "method": "POST", "url": "http://x/c"},
    ])
    rv_text = "\n".join(rv)
    checks += [
        ("replay 汇总: DIVERGED 升显著警告", any("DIVERGED" in w and "http://x/b" in w for w in rv)),
        ("replay 汇总: 含计数汇总行", "IDENTICAL=1" in rv_text and "SKIPPED-WRITE=1" in rv_text),
        ("replay 汇总: 全 IDENTICAL 无 DIVERGED 警告",
         not any("证据存疑" in w for w in _summarize_replay([{"verdict": "IDENTICAL", "method": "GET", "url": "http://x/a"}]))),
        ("replay 汇总: 空结果 -> 空", _summarize_replay([]) == []),
    ]

    bad = [n for n, ok in checks if not ok]
    for n, ok in checks:
        print(("ok   " if ok else "FAIL ") + n)
    print("check_run selftest " + ("passed" if not bad else f"FAILED ({len(bad)})"))
    return 0 if not bad else 1


def _maybe_auto_peer_review(run_dir: Path) -> None:
    """--auto-peer-review: 收口时若 review.md 缺独立复审记录, 自动跑 tools/peer_review.py 异构
    复审写进 review.md(满足独立复审硬门 line 654)。慢+数据出境, 故仅显式 flag。幂等: 已有记录
    则不重跑(不重复花钱/出境)。复审是候选非裁决, driver 仍逐条过证据门。"""
    report = run_dir / "report.md"
    if not report.exists():
        return
    rtext = report.read_text(encoding="utf-8", errors="replace")
    if not (_closure_claimed(rtext) or _report_is_final(run_dir)):
        return  # 未收口 -> 不触发
    rv_path = run_dir / "review.md"
    rv = rv_path.read_text(encoding="utf-8", errors="replace") if rv_path.exists() else ""
    if re.search(r"Independent Review|独立复审", rv):
        return  # 幂等: 已有独立复审记录 -> 不重跑
    try:
        import peer_review  # 同目录(sys.path 已插入 tools/)
    except Exception as e:
        print(f"[auto-peer-review] 无法 import peer_review: {e}")
        return
    print("[auto-peer-review] 收口缺独立复审 -> 跑异构复审(peer_review, 慢/数据出境)…")
    try:
        r = peer_review.review(run_dir, into_run=True, require_heterogeneous=True)
    except Exception as e:
        print(f"[auto-peer-review] peer_review 失败: {e}")
        return
    if r.verdict == "NEEDS_DRIVER":
        print("[auto-peer-review] 落到 Claude 兜底且无 API key —— 无异构后端, 需 driver 自己 spawn "
              "fresh-context 子代理复审(独立复审门仍会拦, 这是对的)。")
        return
    print(f"[auto-peer-review] backend={r.backend_used} verdict={r.verdict}, "
          f"{len(r.findings)} findings 已写进 review.md。候选非裁决, 逐条过证据门。")


def main() -> int:
    parser = argparse.ArgumentParser(description="Check a Xunji run directory.")
    parser.add_argument("run_dir", type=Path, nargs="?")
    parser.add_argument("--selftest", action="store_true",
                        help="run the structured-evidence parser regression and exit")
    parser.add_argument("--auto-peer-review", action="store_true",
                        help="收口时若 review.md 缺独立复审记录, 自动跑 tools/peer_review.py "
                             "(异构后端 Codex>DeepSeek/GLM>Claude, 慢/数据出境)写进 review.md "
                             "满足独立复审硬门。幂等(有记录不重跑)、默认关、selftest 不触发")
    parser.add_argument("--replay-verify", action="store_true",
                        help="收口前自动重放核实: 对 .replay.json 录像跑 replay_run(走 guard / "
                             "target.md 授权 scope / 幂等 GET 才重放 / DELETE 永不 / 写操作默认 skip), "
                             "DIVERGED=证据存疑(终版报告里未 `- Replay:` 处理的承重发现→硬拦; 否则警告)。"
                             "走实网, 默认关、仅显式 flag、selftest 不触发")
    args = parser.parse_args()
    if args.selftest:
        return _selftest()
    if args.run_dir is None:
        parser.error("run_dir is required (or use --selftest)")

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

    # Derive the structured evidence sidecar once (queryable; also memoizes the parse).
    write_evidence_index(run_dir, parse_evidence(run_dir))

    # Quality warnings (do not fail the structural gate; surface for the driver).
    warnings = check_evidence_certainty(run_dir)
    warnings.extend(check_dangling_citations(run_dir))  # 死引用(E-012 洞): 逐条报
    warnings.extend(check_replay_evidence(run_dir))    # 操作录像: certainty>=0.8 确认建议附 .replay.json(可重放核实)
    warnings.extend(check_layout_drift(run_dir))       # 布局漂移: 证据/草稿散落 run 根目录(应归位 evidence/scripts/classify)
    warnings.extend(check_coverage_health(run_dir))   # 覆盖台账三联检(防 lump / 缺建 / 子集蒙混; 输入一次加载)
    warnings.extend(check_shallow_close(run_dir))     # 纵深: 高价值前沿 depth=shallow 关闭却无 Vectors tried
    warnings.extend(check_ledger_contradiction(run_dir))
    warnings.extend(check_graph_consistency(run_dir))  # 派生状态图: 解锁却 deferred / 关了却解锁
    warnings.extend(check_workers(run_dir))            # 并行 worker: done 未 merge(证据门别跳)
    warnings.extend(check_hints(run_dir))              # 操作者 Hint: pending 未吸收
    warnings.extend(check_reason_pass(run_dir))        # 高频 Reason pass: 防隧道视野
    # 自动异构复审(--auto-peer-review): 收口时若缺独立复审记录, 自动跑 peer_review 写进 review.md
    # 满足下面的独立复审硬门。慢(几分钟)+数据出境, 默认关、仅显式 flag; selftest 不走这。
    if args.auto_peer_review:
        _maybe_auto_peer_review(run_dir)
    # --replay-verify(断-1): 收口前自动重放核实 .replay.json 录像, 把 replay 焊进收口闭环。
    # 走实网(慢)+ 默认关、仅显式 flag; selftest 不走这(汇总逻辑 _summarize_replay 单独离线测)。
    if args.replay_verify:
        rv_warns, rv_errors = run_replay_verify(run_dir)
        warnings.extend(rv_warns)
        errors.extend(rv_errors)
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
