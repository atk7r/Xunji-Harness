#!/usr/bin/env python3
"""异构复审模块 (peer review) —— 把"另一个模型当独立复审员"做成可接入的独立部件。

背景: review/independent-reviewer.md 把复审实现列为三种 —— 子代理 / 人开新会话 /
【另一个模型(独立性更强)】。本模块自动化第三种, 并按优先级选后端:
    Codex(本地 CLI agent)  >  DeepSeek / GLM(OpenAI 兼容 API)  >  Claude 自家(兜底)
为什么这个顺序: A2 盲区在权重里, 补盲要【正交的错误分布】。异构厂商(GPT/DeepSeek/GLM)
和 Claude 盲区不重叠才真补盲; Claude 自家只减 bias 不减盲区, 故仅作兜底。

接入方式(其他功能 import):
    from peer_review import review
    r = review("runs/<target>")          # 自动选后端
    r.verdict      # PASS | WARN | BLOCKER | NEEDS_DRIVER | ERROR
    r.findings     # list[Finding(severity, claim, evidence, why)]
    r.backend_used # 实际用了哪个后端

铁律(单整合者): 本模块的产出是【一票/候选, 不是裁决】。driver 仍是唯一整合者, 须过
证据门: 不盲从(可驳回工具/语境误报), 不忽视(采纳真盲补)。模块绝不自动改 run。

数据出境提示: openai/anthropic 后端会把 run 审计内容发送到外部厂商 API; Codex 发给
OpenAI。这等同"把目标发现物发布到外部服务"。仅在操作者接受时使用 API 后端。
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import urllib.request
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8")       # type: ignore[attr-defined]
except Exception:
    pass

ROOT = Path(__file__).resolve().parents[1]
CONFIG_PATH = ROOT / "review" / "peer_review.json"

# ---- 默认配置(可被 review/peer_review.json 覆盖) ----
DEFAULT_CONFIG: dict = {
    "priority": ["codex", "deepseek", "glm", "claude"],
    "backends": {
        # cli-agent: 自己能读文件, prompt 只给路径 + rubric
        "codex": {"kind": "cli-agent", "cmd": "codex", "sandbox": "read-only", "model": None,
                  "heterogeneous": True},
        # openai 兼容: 纯 API, 模块替它打包 run 内容进 prompt
        "deepseek": {"kind": "openai", "base_url": "https://api.deepseek.com/v1",
                     "model": "deepseek-reasoner", "api_key_env": "DEEPSEEK_API_KEY",
                     "heterogeneous": True},
        "glm": {"kind": "openai", "base_url": "https://open.bigmodel.cn/api/paas/v4",
                "model": "glm-4-plus", "api_key_env": "GLM_API_KEY", "heterogeneous": True},
        # 兜底: 有 ANTHROPIC_API_KEY 走 API; 否则委托 driver spawn 子代理。heterogeneous=False:
        # 同族 Claude 减 bias 不减盲区(A2), 【不满足异构独立复审门】—— auto-review/into_run 不用它
        # 满足门(dogfood 第4次逮到的 BLOCKER: 否则同族自审能蒙混"异构"门)。
        "claude": {"kind": "anthropic-or-driver", "base_url": "https://api.anthropic.com/v1",
                   "model": "claude-opus-4-8", "api_key_env": "ANTHROPIC_API_KEY",
                   "heterogeneous": False},
    },
}

# ---- 默认复审契约(英文: 避开中文 stdin 的 GBK 坑; run 内中文文件后端自己读/已附) ----
DEFAULT_RUBRIC = """You are an INDEPENDENT, HETEROGENEOUS reviewer — a DIFFERENT model from the author (the author is Claude). Your entire value is catching blind spots Claude shares with itself, so prioritize what the work likely MISSED over restating it.

CONTEXT: This is a CLOSED, authorized red-team web-pentest run. The run directory is the audit trail. Many files are in Chinese — read them as needed. Evidence discipline: certainty is graded 0.3 / 0.5 / 0.8 / 1.0, and ONLY certainty >= 0.8 may be reported as confirmed. Single observations, redirects, block pages, timeouts, and environment-provided artifacts are NEVER confirmation on their own.

YOU ARE READ-ONLY. Do not modify any file. Do not run exploitation or active probing.

REVIEW RUBRIC — for each point, cite a specific file:line or filename as evidence:
1. Evidence gate: for every finding marked confirmed (certainty >= 0.8), does the cited evidence actually support it? Anything that should be downgraded? Any single-observation / redirect / block-page / timeout treated as confirmed?
2. Coverage ledger: is the coverage/classify ledger a SUBSET of the recon assets? Any assets left unclassified or unprobed that the report silently drops?
3. False positives: any normal behavior mistaken for a vulnerability?
4. Shallow closure: were any high-value fronts (especially RCE / getshell / file upload / deserialization) closed after only shallow probing? Anything abandoned as "Type B" that deserved deeper work?
5. Claim integrity: are the report's confirmed findings, claimed depth, and captured fingerprints actually backed by evidence in the run? In particular — is EVERY evidence item with certainty >= 0.8 carried into the report's confirmed findings? Does the report contradict its own evidence ledger (e.g. an asset called "unreachable" that later evidence shows was reached and exploited)?
6. Missed surface: anything present in surface*.md / evidence that is NOT carried into the report?

FOCUS: report what YOU, as a different model, see that the author likely MISSED. Do not just echo the report.

OUTPUT — print to stdout at the very end, EXACTLY this structure:
## Verdict: PASS | WARN | BLOCKER
## Findings
- [BLOCKER|WARN] <claim> | Evidence: <file:line or filename> | Why: <reason>
## Blind-spot check
- <things the author likely overlooked>
## Context-limit notes
- <where you are unsure or might be wrong due to Chinese-language or local (CNVD / Taiwan) context you do not fully grasp>"""

# run 目录里给 API 后端打包的关键文件(顺序 = 重要性), 每个截断防爆 context
CONTEXT_FILES = [
    "report.md", "evidence.md", "frontier.md", "decisions.md", "hypotheses.md",
    "false_positive.md", "surface.md", "surface_recon.md", "review.md", "target.md",
]
CONTEXT_GLOBS = ["classify/*.txt", "classify/*.json"]
PER_FILE_CAP = 24_000   # 每文件最多塞这么多字符给 API 后端


# ===================== 数据结构 =====================
@dataclass
class Finding:
    severity: str           # BLOCKER | WARN
    claim: str
    evidence: str
    why: str


@dataclass
class ReviewResult:
    verdict: str            # PASS | WARN | BLOCKER | NEEDS_DRIVER | ERROR
    findings: list = field(default_factory=list)
    blind_spots: list = field(default_factory=list)
    context_limits: list = field(default_factory=list)
    backend_used: str = ""
    raw: str = ""
    error: str = ""

    def as_markdown(self) -> str:
        lines = [f"## Verdict: {self.verdict}", "",
                 f"_backend: {self.backend_used}_  ", "", "## Findings"]
        for f in self.findings:
            lines.append(f"- [{f.severity}] {f.claim} | Evidence: {f.evidence} | Why: {f.why}")
        if not self.findings:
            lines.append("- (none)")
        lines += ["", "## Blind-spot check"] + [f"- {b}" for b in self.blind_spots or ["(none)"]]
        lines += ["", "## Context-limit notes"] + [f"- {c}" for c in self.context_limits or ["(none)"]]
        if self.error:
            lines += ["", f"> ERROR: {self.error}"]
        return "\n".join(lines)


# ===================== 配置 =====================
def _deep_merge(base: dict, over: dict) -> dict:
    out = dict(base)
    for k, v in over.items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = _deep_merge(out[k], v)
        else:
            out[k] = v
    return out


def load_config(path: Path = CONFIG_PATH) -> dict:
    cfg = json.loads(json.dumps(DEFAULT_CONFIG))   # deep copy
    if path.is_file():
        try:
            cfg = _deep_merge(cfg, json.loads(path.read_text(encoding="utf-8")))
        except Exception as e:
            print(f"[peer_review] WARN: 配置 {path} 解析失败, 用默认: {e}", file=sys.stderr)
    return cfg


# ===================== 后端选择 =====================
def backend_available(name: str, cfg: dict) -> bool:
    b = cfg["backends"].get(name)
    if not b:
        return False
    kind = b.get("kind")
    if kind == "cli-agent":
        return shutil.which(b.get("cmd", name)) is not None
    if kind == "openai":
        return bool(os.environ.get(b.get("api_key_env", "")))
    if kind == "anthropic-or-driver":
        return True   # 永远可用: 有 key 走 API, 没 key 委托 driver 子代理(兜底)
    return False


def select_backend(cfg: dict, forced: str | None = None) -> str | None:
    if forced:
        return forced if forced in cfg["backends"] else None
    for name in cfg.get("priority", []):
        if backend_available(name, cfg):
            return name
    return None


def _is_heterogeneous(name: str, cfg: dict) -> bool:
    """异构 = 和 Claude(driver/author)盲区正交的厂商后端(codex/deepseek/glm)。claude 同族
    (heterogeneous=False): 减 bias 不减盲区(A2), 不满足异构独立复审门。"""
    return bool(cfg["backends"].get(name, {}).get("heterogeneous", False))


def list_backends(cfg: dict) -> list:
    rows = []
    for name in cfg.get("priority", []):
        b = cfg["backends"].get(name, {})
        rows.append((name, b.get("kind", "?"), backend_available(name, cfg)))
    return rows


# ===================== run 内容打包(给 API 后端) =====================
def gather_run_context(scope_dir: Path) -> str:
    chunks: list = []
    for rel in CONTEXT_FILES:
        f = scope_dir / rel
        if f.is_file():
            txt = f.read_text(encoding="utf-8", errors="replace")
            if len(txt) > PER_FILE_CAP:
                txt = txt[:PER_FILE_CAP] + f"\n…[truncated {len(txt) - PER_FILE_CAP} chars]"
            chunks.append(f"===== FILE: {rel} =====\n{txt}")
    for pat in CONTEXT_GLOBS:
        for f in sorted(scope_dir.glob(pat)):
            txt = f.read_text(encoding="utf-8", errors="replace")
            if len(txt) > PER_FILE_CAP:
                txt = txt[:PER_FILE_CAP] + f"\n…[truncated]"
            chunks.append(f"===== FILE: {f.relative_to(scope_dir).as_posix()} =====\n{txt}")
    return "\n\n".join(chunks)


# ===================== 输出解析 =====================
def parse_review_output(text: str, backend: str = "") -> ReviewResult:
    import re
    idx = text.rfind("## Verdict")
    block = text[idx:] if idx >= 0 else text
    vm = re.search(r"##\s*Verdict[:\s*]*([A-Za-z_]+)", block)
    verdict = vm.group(1).upper() if vm else "ERROR"

    findings = []
    for m in re.finditer(
            r"-\s*\[(BLOCKER|WARN)\]\s*(.+?)\s*\|\s*Evidence:\s*(.+?)\s*\|\s*Why:\s*(.+)",
            block):
        findings.append(Finding(m.group(1), m.group(2).strip(),
                                m.group(3).strip(), m.group(4).strip()))

    def _section(header: str) -> list:
        sm = re.search(rf"##\s*{re.escape(header)}[^\n]*\n(.*?)(?=\n##\s|\Z)", block, re.S)
        if not sm:
            return []
        out = []
        for ln in sm.group(1).splitlines():
            ln = ln.strip()
            if ln.startswith("-"):
                item = ln.lstrip("-").strip()
                if item and item.lower() != "(none)":
                    out.append(item)
        return out

    return ReviewResult(
        verdict=verdict, findings=findings,
        blind_spots=_section("Blind-spot check"),
        context_limits=_section("Context-limit notes"),
        backend_used=backend, raw=text,
    )


# ===================== 后端实现 =====================
def _run_codex(scope_dir: Path, rubric: str, b: dict, timeout: int) -> ReviewResult:
    rel = scope_dir.relative_to(ROOT).as_posix() if scope_dir.is_relative_to(ROOT) else str(scope_dir)
    prompt = (f"Review the CLOSED red-team run at {rel}. You may read any file under that "
              f"directory (read-only). Do not read or modify anything outside it.\n\n{rubric}")
    cmd = f'{b.get("cmd", "codex")} exec -s {b.get("sandbox", "read-only")}'
    if b.get("model"):
        cmd += f' -m {b["model"]}'
    try:
        proc = subprocess.run(cmd, shell=True, input=prompt, capture_output=True,
                              text=True, encoding="utf-8", errors="replace",
                              cwd=str(ROOT), timeout=timeout)
    except subprocess.TimeoutExpired:
        return ReviewResult(verdict="ERROR", backend_used="codex",
                            error=f"codex 超时(>{timeout}s)")
    out = proc.stdout or ""
    r = parse_review_output(out, "codex")
    if r.verdict == "ERROR" and proc.returncode != 0:
        r.error = f"codex exit {proc.returncode}; stderr tail: {(proc.stderr or '')[-400:]}"
    return r


def _run_openai(scope_dir: Path, rubric: str, b: dict, name: str, timeout: int) -> ReviewResult:
    key = os.environ.get(b.get("api_key_env", ""), "")
    if not key:
        return ReviewResult(verdict="ERROR", backend_used=name,
                            error=f"缺 {b.get('api_key_env')} 环境变量")
    context = gather_run_context(scope_dir)
    payload = {
        "model": b["model"], "temperature": 0,
        "messages": [
            {"role": "system", "content": rubric},
            {"role": "user", "content": f"Run audit trail (read-only) for {scope_dir.name}:\n\n{context}"},
        ],
    }
    req = urllib.request.Request(
        b["base_url"].rstrip("/") + "/chat/completions",
        data=json.dumps(payload).encode("utf-8"),
        headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
        method="POST")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = json.loads(resp.read().decode("utf-8", errors="replace"))
        content = data["choices"][0]["message"]["content"]
    except Exception as e:
        return ReviewResult(verdict="ERROR", backend_used=name, error=f"{name} API 失败: {e}")
    return parse_review_output(content, name)


def _run_anthropic(scope_dir: Path, rubric: str, b: dict, timeout: int) -> ReviewResult:
    key = os.environ.get(b.get("api_key_env", ""), "")
    if not key:
        # 兜底: 委托 driver 在 Claude Code 里自己 spawn fresh-context 子代理
        rel = scope_dir.relative_to(ROOT).as_posix() if scope_dir.is_relative_to(ROOT) else str(scope_dir)
        prompt = (f"[委托 driver] 无异构后端且无 ANTHROPIC_API_KEY。请 driver spawn 一个 "
                  f"general-purpose fresh-context 子代理复审 {rel}, 用以下契约。注意: 同模型只减 "
                  f"bias 不减盲区(见 review-mechanism.md / A2), 这是最弱兜底。\n\n{rubric}")
        return ReviewResult(verdict="NEEDS_DRIVER", backend_used="claude:driver-subagent",
                            raw=prompt)
    context = gather_run_context(scope_dir)
    payload = {"model": b["model"], "max_tokens": 4096, "system": rubric,
               "messages": [{"role": "user",
                             "content": f"Run audit trail (read-only) for {scope_dir.name}:\n\n{context}"}]}
    req = urllib.request.Request(
        b["base_url"].rstrip("/") + "/messages",
        data=json.dumps(payload).encode("utf-8"),
        headers={"x-api-key": key, "anthropic-version": "2023-06-01",
                 "Content-Type": "application/json"}, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = json.loads(resp.read().decode("utf-8", errors="replace"))
        content = "".join(blk.get("text", "") for blk in data.get("content", []))
    except Exception as e:
        return ReviewResult(verdict="ERROR", backend_used="claude", error=f"anthropic API 失败: {e}")
    return parse_review_output(content, "claude")


# ===================== 主入口 =====================
def review(scope_dir, *, rubric: str | None = None, backend: str | None = None,
           out_file=None, into_run: bool = False, require_heterogeneous: bool = False,
           config: dict | None = None, timeout: int = 900) -> ReviewResult:
    """对一个 run 目录做异构复审。返回 ReviewResult(候选, 非裁决 —— driver 须过证据门整合)。"""
    scope = Path(scope_dir)
    if not scope.is_absolute():
        scope = (ROOT / scope).resolve()
    if not scope.is_dir():
        return ReviewResult(verdict="ERROR", error=f"scope 目录不存在: {scope}")

    cfg = config or load_config()
    rubric = rubric or DEFAULT_RUBRIC
    chosen = select_backend(cfg, backend)
    if not chosen:
        return ReviewResult(verdict="ERROR",
                            error="无可用复审后端(codex 未装 + 无 API key)。装 codex 或配 "
                                  "DEEPSEEK_API_KEY/GLM_API_KEY/ANTHROPIC_API_KEY。")
    if require_heterogeneous and not _is_heterogeneous(chosen, cfg):
        # 同族(Claude)不满足异构独立性 —— A2: 同族减 bias 不减盲区。auto-review 不用它满足异构门,
        # 也不白跑它的 API。提示装真异构后端或 driver 自己 spawn 子代理。
        rel = scope.relative_to(ROOT).as_posix() if scope.is_relative_to(ROOT) else str(scope)
        return ReviewResult(verdict="NEEDS_DRIVER", backend_used=f"{chosen}:same-family-rejected",
            raw=f"[需真异构] 唯一可用后端 '{chosen}' 是同族(非异构), 不满足异构独立复审门。装 codex "
                f"或配 DEEPSEEK_API_KEY/GLM_API_KEY, 或 driver spawn fresh-context 子代理复审 {rel}。")
    b = cfg["backends"][chosen]
    kind = b.get("kind")
    if kind == "cli-agent":
        result = _run_codex(scope, rubric, b, timeout)
    elif kind == "openai":
        result = _run_openai(scope, rubric, b, chosen, timeout)
    elif kind == "anthropic-or-driver":
        result = _run_anthropic(scope, rubric, b, timeout)
    else:
        result = ReviewResult(verdict="ERROR", error=f"未知后端 kind: {kind}")

    # into_run 只对【异构】后端写满足门记录: 同族 Claude 即使有 key 跑了 API, 也不满足异构独立
    # 复审门(否则用同族自审蒙混"异构"门 —— dogfood 第4次 BLOCKER)。
    if (into_run and result.verdict not in ("ERROR", "NEEDS_DRIVER")
            and _is_heterogeneous(result.backend_used.split(":")[0], cfg)):
        _append_run_review(scope, result)
    if out_file:
        out = Path(out_file)
        if not out.is_absolute():
            out = ROOT / out
        out.parent.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%MZ")
        header = (f"# Peer Review — {scope.name}\n\n_backend: {result.backend_used} · {stamp}_\n"
                  f"> 候选, 非裁决。driver 须逐条过证据门: 不盲从(驳工具/语境误报), 不忽视(采纳真盲补)。\n\n")
        out.write_text(header + result.as_markdown(), encoding="utf-8")
    return result


def _append_run_review(run_dir: Path, result: ReviewResult) -> None:
    """把复审【追加】进 runs/<t>/review.md 的独立复审区块 —— 满足 check_run 的独立复审硬门
    (re.search 'Independent Review|独立复审')。追加不覆盖(review.md 可能已有别的内容)。
    NEEDS_DRIVER/ERROR 不写(没真复审就不该满足门)。"""
    rv = run_dir / "review.md"
    existing = rv.read_text(encoding="utf-8", errors="replace") if rv.exists() else "# Review\n"
    stamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%MZ")
    block = (f"## Independent Review (heterogeneous peer_review · {result.backend_used} · {stamp})\n"
             "> 异构独立复审, 候选非裁决 —— driver 逐条过证据门(不盲从工具/语境误报, 不忽视真盲补)。\n\n"
             + result.as_markdown() + "\n")
    rv.write_text(existing.rstrip() + "\n\n" + block, encoding="utf-8")


# ===================== CLI / selftest =====================
def _selftest() -> int:
    checks = []
    cfg = load_config()
    checks.append(("默认配置 priority 含 4 后端",
                   cfg["priority"] == ["codex", "deepseek", "glm", "claude"]))

    # 优先级选择: 模拟可用性
    fake = json.loads(json.dumps(DEFAULT_CONFIG))
    os.environ.pop("DEEPSEEK_API_KEY", None)
    os.environ.pop("GLM_API_KEY", None)
    os.environ.pop("ANTHROPIC_API_KEY", None)
    # claude 永远可用 -> 无 codex/无 key 时应选 claude(兜底)
    sel_fallback = select_backend(
        {"priority": ["deepseek", "glm", "claude"], "backends": fake["backends"]})
    checks.append(("无 key 时优先级落到 claude 兜底", sel_fallback == "claude"))
    # forced 强制
    checks.append(("--backend 强制存在的后端",
                   select_backend(cfg, "deepseek") == "deepseek"))
    checks.append(("--backend 不存在 -> None", select_backend(cfg, "nope") is None))
    # claude 兜底总是 available
    checks.append(("anthropic-or-driver 永远 available",
                   backend_available("claude", cfg) is True))

    # 输出解析
    sample = """blah blah process log
## Verdict: BLOCKER
## Findings
- [BLOCKER] report omits E-017 | Evidence: evidence.md:283 | Why: certainty 1.0 not carried
- [WARN] stale certainty | Evidence: report.md:94 | Why: downgraded in evidence
## Blind-spot check
- later evidence superseded earlier narrative
## Context-limit notes
- chinese mojibake
"""
    r = parse_review_output(sample, "codex")
    checks.append(("解析 verdict=BLOCKER", r.verdict == "BLOCKER"))
    checks.append(("解析 2 条 findings", len(r.findings) == 2))
    checks.append(("解析 findings severity", r.findings[0].severity == "BLOCKER"))
    checks.append(("解析 evidence 字段", r.findings[0].evidence == "evidence.md:283"))
    checks.append(("解析 blind-spot 1 条", len(r.blind_spots) == 1))
    checks.append(("解析 context-limit 1 条", len(r.context_limits) == 1))
    # 取最后一个 Verdict 块(防过程日志里的假 Verdict)
    r2 = parse_review_output("## Verdict: PASS\nnoise\n" + sample, "x")
    checks.append(("取最后一个 Verdict 块", r2.verdict == "BLOCKER"))

    # (none) 不计入
    none_sample = "## Verdict: PASS\n## Findings\n- (none)\n## Blind-spot check\n- (none)\n"
    r3 = parse_review_output(none_sample)
    checks.append(("(none) 不计入 findings", len(r3.findings) == 0))
    checks.append(("(none) 不计入 blind", len(r3.blind_spots) == 0))

    # gather_run_context: 对真实 hamastar run(若在)
    sample_run = ROOT / "runs" / "hamastar_20260615"
    if sample_run.is_dir():
        ctx = gather_run_context(sample_run)
        checks.append(("gather_context 含 report.md", "FILE: report.md" in ctx))
        checks.append(("gather_context 含 evidence.md", "FILE: evidence.md" in ctx))
        checks.append(("gather_context 非空", len(ctx) > 1000))

    # as_markdown 往返
    md = r.as_markdown()
    checks.append(("as_markdown 含 Verdict", "## Verdict: BLOCKER" in md))
    checks.append(("as_markdown 含 finding", "E-017" in md))

    # into_run: 追加进 review.md 带独立复审标记(满足 check_run 门), 不覆盖已有内容
    import re as _re
    import tempfile
    d_run = Path(tempfile.mkdtemp())
    (d_run / "review.md").write_text("# Review\n## 已有内容\n- foo\n", encoding="utf-8")
    _append_run_review(d_run, ReviewResult(verdict="BLOCKER",
                       findings=[Finding("BLOCKER", "x", "e", "y")], backend_used="codex"))
    rv1 = (d_run / "review.md").read_text(encoding="utf-8")
    _append_run_review(d_run, ReviewResult(verdict="PASS", backend_used="deepseek"))
    rv2 = (d_run / "review.md").read_text(encoding="utf-8")
    checks += [
        ("into_run 写'Independent Review'标记(满足门)", bool(_re.search(r"Independent Review", rv1))),
        ("into_run 保留已有内容(追加不覆盖)", "已有内容" in rv1),
        ("into_run 写 verdict/finding", "BLOCKER" in rv1 and "x" in rv1),
        ("into_run 二次追加不覆盖(两区块)", rv2.count("Independent Review") == 2),
    ]

    # 异构性 + non-write guard (dogfood 第4次 BLOCKER 修复)
    cfg_d = load_config()
    d_err = Path(tempfile.mkdtemp())
    review(d_err, backend="nonexistent_xyz", into_run=True)   # 无此后端 -> ERROR
    d_sf = Path(tempfile.mkdtemp())
    rr_sf = review(d_sf, config={"priority": ["claude"], "backends": cfg_d["backends"]},
                   require_heterogeneous=True, into_run=True)  # 只同族 claude + require -> NEEDS_DRIVER
    checks += [
        ("heterogeneous: codex/deepseek/glm=True, claude=False",
         _is_heterogeneous("codex", cfg_d) and _is_heterogeneous("deepseek", cfg_d)
         and not _is_heterogeneous("claude", cfg_d)),
        ("into_run: ERROR verdict 不写 review.md(non-write guard)", not (d_err / "review.md").exists()),
        ("require_hetero: 唯一同族 claude -> NEEDS_DRIVER(不跑/不写)", rr_sf.verdict == "NEEDS_DRIVER"),
        ("require_hetero: 同族不写 review.md", not (d_sf / "review.md").exists()),
    ]

    bad = [n for n, ok in checks if not ok]
    for n, ok in checks:
        print(f"{'ok  ' if ok else 'FAIL'} {n}")
    if bad:
        print(f"\npeer_review selftest FAILED: {len(bad)} 项")
        return 1
    print(f"\npeer_review selftest passed ({len(checks)} checks)")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description="异构复审 (Codex > DeepSeek/GLM > Claude 兜底)")
    ap.add_argument("scope", nargs="?", help="run 目录, 如 runs/<target>")
    ap.add_argument("--backend", help="强制后端: codex|deepseek|glm|claude")
    ap.add_argument("--out", help="把复审写到该文件(如 review/records/<x>.md)")
    ap.add_argument("--into-run", action="store_true",
                    help="把复审追加进 runs/<t>/review.md 独立复审区块(满足 check_run 独立复审门)")
    ap.add_argument("--timeout", type=int, default=900)
    ap.add_argument("--list-backends", action="store_true", help="列后端可用性后退出")
    ap.add_argument("--selftest", action="store_true")
    args = ap.parse_args()

    if args.selftest:
        return _selftest()

    cfg = load_config()
    if args.list_backends:
        print("后端可用性(按优先级):")
        for name, kind, ok in list_backends(cfg):
            print(f"  {'[可用]' if ok else '[ 不可用 ]'}  {name:10} ({kind})")
        chosen = select_backend(cfg, args.backend)
        print(f"\n将选用: {chosen or '(无可用后端)'}")
        return 0

    if not args.scope:
        ap.error("需要 scope 目录(或用 --list-backends / --selftest)")
    r = review(args.scope, backend=args.backend, out_file=args.out, into_run=args.into_run,
               config=cfg, timeout=args.timeout)
    print(r.as_markdown())
    if r.verdict == "NEEDS_DRIVER":
        print("\n[!] 落到 Claude 兜底且无 API key —— 请 driver spawn fresh-context 子代理, "
              "prompt 见上(raw)。", file=sys.stderr)
        print("\n--- driver 子代理 prompt ---\n" + r.raw, file=sys.stderr)
    return 0 if r.verdict != "ERROR" else 1


if __name__ == "__main__":
    raise SystemExit(main())
