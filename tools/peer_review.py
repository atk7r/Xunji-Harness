#!/usr/bin/env python3
"""异构复审模块 (peer review) —— 把"另一个模型当独立复审员"做成可接入的独立部件。

背景: review/independent-reviewer.md 把复审实现列为三种 —— 子代理 / 人开新会话 /
【另一个模型(独立性更强)】。本模块自动化第三种, 并按"谁改代码/谁是评审对象"选后端:
    Claude Code 主驾驶/修改: 满配 Codex(gpt-5.5 high, 本地 CLI agent) + arkcli 三模型 panel;
      缺 Codex 用 arkcli panel; 缺 arkcli 用 Codex; 都缺才 Claude Code 同族兜底。
    Codex-authored maintenance diff: Codex 不算独立票, 满配用 arkcli panel + Claude Code CLI 复审;
      缺 arkcli 时用 Claude Code CLI 复审。最终综合/决策权仍在 Codex。
为什么这个顺序: A2 盲区在权重里, 补盲要【正交的错误分布】。Claude 主驾满配大脑是 Codex;
arkcli panel 是外部异构补盲团; Claude 自家只减 bias 不减盲区, 故仅在 Claude 主驾时作兜底。
如果评审对象是 Codex-authored maintenance diff, 用 --driver codex:
  Codex 后端不再计为独立复审票, 矩阵切到 arkcli panel + Claude Code CLI, 但综合大脑仍为 Codex。

接入方式(其他功能 import):
    from peer_review import review
    r = review("runs/<target>")          # 自动选后端
    r.verdict      # PASS | WARN | BLOCKER | NEEDS_DRIVER | ERROR
    r.findings     # list[Finding(severity, claim, evidence, why)]
    r.backend_used # 实际用了哪个后端

铁律(单整合者): 本模块的产出是【一票/候选, 不是裁决】。driver 仍是唯一整合者, 须过
证据门: 不盲从(可驳回工具/语境误报), 不忽视(采纳真盲补)。模块绝不自动改 run。

数据出境提示: Codex 会把 run 审计内容发给 OpenAI; arkcli panel 会把冻结 review_bundle
发给 ARK 数据面模型; anthropic/openai 兼容旧后端也会发外部厂商 API。这等同"把目标发现物
发布到外部服务"。仅在操作者接受时使用 API 后端。
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
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
sys.path.insert(0, str(Path(__file__).resolve().parent))
from harness import proxy as proxymod          # noqa: E402  模型调用【绝不】走交战代理(剥代理 env + 空 opener)
from harness import codex_proxy                # noqa: E402  Codex CLI 专用代理通道
from evidence_parse import parse_evidence      # noqa: E402  Codex 裁决事实源: evidence_index, 不是散文叙事
CONFIG_PATH = ROOT / "review" / "peer_review.json"
DEFAULT_DRIVER = "claude"

# ---- 默认配置(可被 review/peer_review.json 覆盖) ----
DEFAULT_CONFIG: dict = {
    "priority": ["codex", "arkcli", "claude"],
    "panel": {
        "min_heterogeneous": "auto",
        "max_backends": 2,
        "roles": ["evidence_skeptic", "closure_skeptic", "report_consistency"],
    },
    "egress": {
        "redact_secrets": True,
        "include_artifacts": "snippets",
        "artifact_excerpt_chars": 24_000,
        "max_bundle_chars": 180_000,
    },
    "backends": {
        # cli-agent: 自己能读文件, prompt 只给路径 + rubric
        "codex": {"kind": "cli-agent", "cmd": "codex", "sandbox": "read-only",
                  "model": "gpt-5.5", "effort": "high", "heterogeneous": True},
        # arkcli 外部异构补盲团: 三模型独立审同一冻结 bundle, 聚合成候选 finding。
        "arkcli": {"kind": "arkcli-panel", "cmd": "arkcli", "heterogeneous": True,
                   "per_model_timeout": 300, "max_context_chars": 120_000,
                   "models": [
                       {"id": "kimi-k2.7-code"},
                       {"id": "minimax-m3"},
                       {"id": "glm-5.2"},
                   ]},
        # 旧 OpenAI 兼容后端: 保留给 --backend 强制/私有配置, 不在默认链路。
        "deepseek": {"kind": "openai", "base_url": "https://api.deepseek.com/v1",
                     "model": "deepseek-reasoner", "api_key_env": "DEEPSEEK_API_KEY",
                     "heterogeneous": True},
        "glm": {"kind": "openai", "base_url": "https://open.bigmodel.cn/api/paas/v4",
                "model": "glm-4-plus", "api_key_env": "GLM_API_KEY", "heterogeneous": True},
        # Claude Code CLI: 走 `claude -p`, 不直连 Anthropic Messages API。对 Claude 主驾是同族兜底;
        # 对 Codex-authored diff 是独立 reviewer。
        "claude": {"kind": "claude-code-cli", "cmd": "claude", "effort": "high",
                   "permission_mode": "dontAsk", "tools": "Read,Grep,Glob",
                   "heterogeneous": False},
    },
}

# ---- 默认复审契约(英文: 避开中文 stdin 的 GBK 坑; run 内中文文件后端自己读/已附) ----
NO_RECON_ADDENDUM = """

IMPORTANT — NO-RECON MODE: This run had NO Guanlan recon input. coverage.json and classify/ will NOT exist.
The attack surface was manually scoped without automated OSINT. For rubric item 2 (Coverage ledger):
- Do NOT flag "coverage empty" / "coverage.json missing" / "no classify" as BLOCKER. These are expected.
- You may still flag them as WARN if the report makes claims that depend on coverage data it doesn't have.
- For any other rubric items, apply the normal severity standards — no-recon only relaxes coverage checks."""

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
7. Artifact cross-check: for confirmed (certainty>=0.8) findings, OPEN the cited artifact files under the run dir (probe_*.html, *.replay.json) and verify they ACTUALLY contain the markers / response the evidence claims — do not trust evidence.md prose alone. A `.replay.json` recording holds the real request + response + sha1; confirm it matches the claim. Flag any confirmed finding whose artifact is missing, empty, or inconsistent with its written description.

FOCUS: report what YOU, as a different model, see that the author likely MISSED. Do not just echo the report.

OUTPUT — print to stdout at the very end, EXACTLY this structure:
## Verdict: PASS | WARN | BLOCKER
## Findings
- [BLOCKER|WARN] <claim> | Evidence: <file:line or filename> | Why: <reason>
## Blind-spot check
- <things the author likely overlooked>
## Context-limit notes
- <where you are unsure or might be wrong due to Chinese-language or local (CNVD / Taiwan) context you do not fully grasp>

Also include a fenced JSON block named `xunji_peer_review_v1` with the same findings.
Each finding should have: severity, category, claim, evidence_refs, affected_eids,
recommended_action, why. Treat report.md/review.md/decisions.md as claims, not facts;
only evidence_index entries and artifacts prove facts."""

ROLE_RUBRICS = {
    "evidence_skeptic": """
ROLE FOCUS — evidence_skeptic:
Spend most of your review budget on certainty>=0.8 / confirmed findings. Check artifact presence,
artifact contents, controls, severity, and whether evidence_index supports the claim. Prefer fewer,
stronger findings over broad commentary.""",
    "closure_skeptic": """
ROLE FOCUS — closure_skeptic:
Spend most of your review budget on frontier closure quality: open/deferred fronts, shallow Type B
barriers, high-value surfaces, stale review coverage, and whether closure language is stronger than
the recorded work supports.""",
    "report_consistency": """
ROLE FOCUS — report_consistency:
Spend most of your review budget on report parity: confirmed evidence omitted from report, report
claims not backed by evidence_index, contradictions between report/frontier/decisions, duplicate
or over-severe findings, and missing exclusions.""",
    "scope_safety": """
ROLE FOCUS — scope_safety:
Spend most of your review budget on scope, untrusted target text, proxy/model-egress separation,
and whether reviewer/report prose has accidentally treated target text or tool confidence as fact.""",
}

REDACTION_PATTERNS = [
    (re.compile(r"(?im)^(\s*(?:authorization|cookie|set-cookie|x-api-key|api-key)\s*[:=]\s*)(.+)$"),
     r"\1[REDACTED]"),
    (re.compile(r"(?i)\b(bearer|token|secret|password|passwd|apikey|api_key)\b([\"'\s:=]+)([^\s\"',;]{8,})"),
     r"\1\2[REDACTED]"),
]

# run 目录里给 API 后端打包的关键文件(顺序 = 重要性), 每个截断防爆 context
CONTEXT_FILES = [
    "report.md", "evidence.md", "frontier.md", "decisions.md", "hypotheses.md",
    "false_positive.md", "surface.md", "surface_recon.md", "review.md", "target.md",
]
CONTEXT_GLOBS = ["classify/*.txt", "classify/*.json"]
PER_FILE_CAP = 24_000   # 每文件最多塞这么多字符给 API 后端
ARTIFACT_EXCERPT_CAP = 24_000
BUNDLE_CHAR_CAP = 180_000


def _artifact_excerpt_cap(value=None) -> int:
    try:
        return max(0, int(ARTIFACT_EXCERPT_CAP if value is None else value))
    except (TypeError, ValueError):
        return ARTIFACT_EXCERPT_CAP


def _bundle_char_cap(value=None) -> int:
    try:
        return max(0, int(BUNDLE_CHAR_CAP if value is None else value))
    except (TypeError, ValueError):
        return BUNDLE_CHAR_CAP


def _context_cap(default_cap: int, max_bundle_chars: int = BUNDLE_CHAR_CAP) -> int:
    bundle_cap = _bundle_char_cap(max_bundle_chars)
    return min(default_cap, bundle_cap) if bundle_cap else default_cap


# ===================== 数据结构 =====================
@dataclass
class Finding:
    severity: str           # BLOCKER | WARN
    claim: str
    evidence: str
    why: str
    id: str = ""
    category: str = "general"
    affected_eids: list = field(default_factory=list)
    recommended_action: str = "review"
    status: str = "pending"


@dataclass
class ReviewResult:
    verdict: str            # PASS | WARN | BLOCKER | NEEDS_DRIVER | ERROR
    findings: list = field(default_factory=list)
    blind_spots: list = field(default_factory=list)
    context_limits: list = field(default_factory=list)
    backend_used: str = ""
    raw: str = ""
    error: str = ""
    bundle_hash: str = ""
    evidence_index_hash: str = ""
    driver: str = ""
    brain: str = ""

    def as_dict(self) -> dict:
        return {
            "schema": "xunji.peer_review_result.v1",
            "verdict": self.verdict,
            "backend_used": self.backend_used,
            "driver": self.driver,
            "brain": self.brain,
            "bundle_hash": self.bundle_hash,
            "evidence_index_hash": self.evidence_index_hash,
            "findings": [
                {
                    "id": f.id,
                    "severity": f.severity,
                    "category": f.category,
                    "claim": f.claim,
                    "evidence": f.evidence,
                    "affected_eids": f.affected_eids,
                    "recommended_action": f.recommended_action,
                    "why": f.why,
                    "status": f.status,
                }
                for f in self.findings
            ],
            "blind_spots": self.blind_spots,
            "context_limits": self.context_limits,
            "error": self.error,
        }

    def as_markdown(self) -> str:
        lines = [f"## Verdict: {self.verdict}", "",
                 f"_backend: {self.backend_used}_  "]
        if self.brain:
            lines.append(f"_brain: {self.brain}_  ")
        if self.bundle_hash:
            lines.append(f"_bundle_hash: {self.bundle_hash}_  ")
        if self.evidence_index_hash:
            lines.append(f"_evidence_index_hash: {self.evidence_index_hash}_  ")
        lines += ["", "## Findings"]
        for f in self.findings:
            prefix = f"{f.id} " if f.id else ""
            lines.append(f"- [{f.severity}] {prefix}{f.claim} | Evidence: {f.evidence} | Why: {f.why}")
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


# ===================== 事实索引 / 复审 bundle =====================
def _sha1_bytes(data: bytes) -> str:
    return hashlib.sha1(data).hexdigest()


def _sha1_file(path: Path) -> str:
    h = hashlib.sha1()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _redact_text(text: str) -> str:
    out = text
    for pat, repl in REDACTION_PATTERNS:
        out = pat.sub(repl, out)
    return out


def _artifact_path(run_dir: Path, token: str) -> Path | None:
    root = run_dir.resolve()
    tok = token.strip().strip("`\"'").rstrip(").,;:，。）")
    cands = [tok] if tok.startswith("evidence/") else [tok, f"evidence/{tok}"]
    for rel in cands:
        try:
            p = (run_dir / rel).resolve()
        except Exception:
            continue
        if p != root and root not in p.parents:
            continue
        if p.is_file() and p.stat().st_size > 0:
            return p
    return None


def _artifact_record(run_dir: Path, token: str, *, redact: bool = False,
                     include_excerpt: bool = True,
                     excerpt_chars: int = ARTIFACT_EXCERPT_CAP) -> dict:
    p = _artifact_path(run_dir, token)
    if not p:
        return {"token": token, "exists": False}
    rel = p.relative_to(run_dir.resolve()).as_posix()
    item = {
        "token": token,
        "path": rel,
        "exists": True,
        "size": p.stat().st_size,
        "sha1": _sha1_file(p),
    }
    if include_excerpt and p.suffix.lower() in {".html", ".json", ".txt", ".log", ".xml"}:
        txt = p.read_text(encoding="utf-8", errors="replace")
        if redact:
            txt = _redact_text(txt)
        cap = _artifact_excerpt_cap(excerpt_chars)
        item["excerpt"] = txt[:cap]
        if len(txt) > cap:
            item["excerpt_truncated_chars"] = len(txt) - cap
    return item


def build_evidence_index(run_dir: Path, *, redact: bool = False,
                         include_artifacts: str = "snippets",
                         artifact_excerpt_chars: int = ARTIFACT_EXCERPT_CAP) -> dict:
    """Content-addressed fact view for reviewers. Narrative files may contain claims;
    this index is the narrow fact source Codex arbitration must cite."""
    entries = []
    for rec in parse_evidence(run_dir):
        include_excerpt = include_artifacts == "snippets"
        artifacts = sorted(
            (_artifact_record(run_dir, a, redact=redact, include_excerpt=include_excerpt,
                              excerpt_chars=artifact_excerpt_chars)
             for a in rec.get("artifacts", [])),
            key=lambda x: (str(x.get("path", "")), str(x.get("token", ""))),
        )
        entries.append({
            "id": rec.get("id"),
            "head": rec.get("head"),
            "maturity": rec.get("maturity"),
            "certainties": rec.get("certainties", []),
            "confirmed": rec.get("confirmed", False),
            "has_control": rec.get("has_control", False),
            "supports": rec.get("supports", []),
            "refutes": rec.get("refutes", []),
            "refutes_any": rec.get("refutes_any", False),
            "artifacts": artifacts,
            "artifacts_missing": rec.get("artifacts_missing", []),
        })
    entries.sort(key=lambda x: str(x.get("id", "")))
    payload = {"schema": "xunji.evidence_index.v1", "entries": entries}
    payload["sha1"] = _sha1_bytes(json.dumps(payload, ensure_ascii=False, sort_keys=True).encode("utf-8"))
    return payload


def _machine_findings(evidence_index: dict) -> list[dict]:
    findings: list[dict] = []
    for entry in evidence_index.get("entries", []):
        eid = entry.get("id") or "(unknown)"
        if entry.get("confirmed") and not entry.get("has_control"):
            findings.append({
                "severity": "WARN",
                "category": "missing_control",
                "claim": f"{eid} is confirmed but has no parsed control",
                "evidence_refs": [str(eid)],
                "recommended_action": "add_control_or_downgrade",
            })
        if entry.get("confirmed") and not any(a.get("exists") for a in entry.get("artifacts", [])):
            findings.append({
                "severity": "BLOCKER",
                "category": "missing_artifact",
                "claim": f"{eid} is confirmed but has no existing artifact in the review bundle",
                "evidence_refs": [str(eid)],
                "recommended_action": "attach_artifact_or_downgrade",
            })
        missing = entry.get("artifacts_missing") or []
        if entry.get("confirmed") and missing:
            findings.append({
                "severity": "WARN",
                "category": "artifact_reference_missing",
                "claim": f"{eid} references missing artifact token(s): {', '.join(map(str, missing))}",
                "evidence_refs": [str(eid)],
                "recommended_action": "fix_artifact_refs",
            })
    return findings


def _mark_invalid_finding_refs(result: ReviewResult, bundle: dict) -> None:
    known = {str(e.get("id")) for e in bundle.get("evidence_index", {}).get("entries", [])}
    bad_notes = []
    for f in result.findings:
        bad = [eid for eid in f.affected_eids if str(eid) not in known]
        if bad:
            note = f"{f.id or '(no-id)'} references unknown affected_eids: {', '.join(map(str, bad))}"
            bad_notes.append(note)
            f.why = (f.why + " " if f.why else "") + f"[review-output-invalid: {note}]"
    if bad_notes:
        result.context_limits.extend(bad_notes)


def build_review_bundle(run_dir: Path, *, write: bool = False,
                        redact_egress: bool = False,
                        include_artifacts: str = "snippets",
                        artifact_excerpt_chars: int = ARTIFACT_EXCERPT_CAP,
                        max_bundle_chars: int = BUNDLE_CHAR_CAP) -> dict:
    """Freeze the review input. Keep fact material separate from narrative claims so
    model-written review/report text cannot become evidence on the next pass."""
    files = {}
    for rel in CONTEXT_FILES:
        p = run_dir / rel
        if p.is_file():
            files[rel] = {"sha1": _sha1_file(p), "size": p.stat().st_size}
    claims = {rel: (run_dir / rel).read_text(encoding="utf-8", errors="replace")[:PER_FILE_CAP]
              for rel in ("report.md", "frontier.md", "decisions.md", "review.md")
              if (run_dir / rel).is_file()}
    if redact_egress:
        claims = {k: _redact_text(v) for k, v in claims.items()}
    max_chars = _bundle_char_cap(max_bundle_chars)
    requested_excerpt_chars = _artifact_excerpt_cap(artifact_excerpt_chars)
    effective_excerpt_chars = requested_excerpt_chars
    warnings: list[str] = []

    def _compose(evidence_index: dict) -> dict:
        redaction = {
            "enabled": bool(redact_egress),
            "include_artifacts": include_artifacts,
            "artifact_excerpt_chars": effective_excerpt_chars,
            "max_bundle_chars": max_chars,
        }
        if effective_excerpt_chars != requested_excerpt_chars:
            redaction["requested_artifact_excerpt_chars"] = requested_excerpt_chars
        return {
            "schema": "xunji.review_bundle.v1",
            "run": run_dir.name,
            "files": files,
            "evidence_index": evidence_index,
            "machine_findings": _machine_findings(evidence_index),
            "claims": claims,
            "egress_redaction": redaction,
            "warnings": list(warnings),
            "note": "claims are reviewer/report narrative; factual arbitration must cite evidence_index/artifact hashes",
        }

    bundle = {}
    for _ in range(6):
        evidence_index = build_evidence_index(
            run_dir,
            redact=redact_egress,
            include_artifacts=include_artifacts,
            artifact_excerpt_chars=effective_excerpt_chars,
        )
        bundle = _compose(evidence_index)
        size_probe = json.dumps(bundle, ensure_ascii=False, sort_keys=True)
        if not max_chars or len(size_probe) <= max_chars:
            break
        if include_artifacts != "snippets" or effective_excerpt_chars <= 0:
            break
        next_cap = max(0, int(effective_excerpt_chars * max_chars / len(size_probe) * 0.85))
        if next_cap >= effective_excerpt_chars:
            next_cap = effective_excerpt_chars - 1
        warnings.append(
            f"artifact_excerpt_chars reduced from {effective_excerpt_chars} to {next_cap} "
            f"to fit max_bundle_chars={max_chars}")
        effective_excerpt_chars = next_cap

    size_probe = json.dumps(bundle, ensure_ascii=False, sort_keys=True)
    if max_chars and len(size_probe) > max_chars:
        if effective_excerpt_chars == 0:
            bundle["warnings"].append(
                "review_bundle still exceeds max_bundle_chars after artifact excerpts reached 0; "
                "claims or evidence metadata dominate bundle size")
        bundle["warnings"].append(
            f"review_bundle serialized chars {len(size_probe)} exceed max_bundle_chars={max_chars}; "
            "downstream reviewer context may still be truncated")
    bundle["sha1"] = _sha1_bytes(json.dumps(bundle, ensure_ascii=False, sort_keys=True).encode("utf-8"))
    if write:
        out_dir = run_dir / "review"
        out_dir.mkdir(parents=True, exist_ok=True)
        out = out_dir / "review_bundle.json"
        out.write_text(json.dumps(bundle, ensure_ascii=False, indent=2), encoding="utf-8")
    return bundle


# ===================== 后端选择 =====================
def backend_available(name: str, cfg: dict) -> bool:
    b = cfg["backends"].get(name)
    if not b:
        return False
    kind = b.get("kind")
    if kind == "cli-agent":
        if shutil.which(b.get("cmd", name)) is None:
            return False
        # codex: CODEX_PROXY_REQUIRED=1 且无代理 → 标记不可用(落到下一后端)
        if name == "codex" and codex_proxy.codex_required() and not codex_proxy.codex_proxy_url():
            return False
        return True
    if kind == "arkcli-panel":
        return shutil.which(b.get("cmd", name)) is not None
    if kind == "openai":
        return bool(os.environ.get(b.get("api_key_env", "")))
    if kind == "claude-code-cli":
        return shutil.which(b.get("cmd", name)) is not None
    return False


def select_backend(cfg: dict, forced: str | None = None) -> str | None:
    if forced:
        return forced if forced in cfg["backends"] else None
    for name in cfg.get("priority", []):
        if backend_available(name, cfg):
            return name
    return None


def _normalize_driver(driver: str | None = None) -> str:
    raw = (driver or os.environ.get("XUNJI_REVIEW_DRIVER") or DEFAULT_DRIVER).strip().lower()
    aliases = {
        "claude-code": "claude",
        "claude_code": "claude",
        "claudecode": "claude",
        "anthropic": "claude",
        "codex-cli": "codex",
        "codex_cli": "codex",
        "openai": "codex",
    }
    return aliases.get(raw, raw)


def _is_heterogeneous(name: str, cfg: dict, driver: str | None = None) -> bool:
    """独立/异构是相对当前主驾驶说的。

    默认主驾驶是 Claude Code: codex/arkcli/legacy API 算异构, claude 同族不算。
    若主操作面切到 Codex: codex 变成自审, arkcli 与 Claude Code CLI 才算独立复审。
    """
    driver = _normalize_driver(driver)
    if driver == "codex":
        if name == "codex":
            return False
        if name == "claude":
            return True
    return bool(cfg["backends"].get(name, {}).get("heterogeneous", False))


def _driver_matrix_order(driver: str | None = None) -> list[str]:
    """Preferred reviewer order for the active author/review-subject mode."""
    driver = _normalize_driver(driver)
    if driver == "codex":
        # Codex-authored changes need external review: arkcli panel plus Claude Code CLI.
        return ["arkcli", "claude"]
    # Claude Code-authored/driven changes use Codex plus arkcli when available.
    return ["codex", "arkcli"]


def _available_heterogeneous_backends(cfg: dict, driver: str | None = None) -> list[str]:
    preferred = _driver_matrix_order(driver)
    priority = list(cfg.get("priority", []))
    # Keep private-config legacy backends usable and allow priority to disable a
    # backend, but never let priority invert the active driver matrix.
    order = [name for name in preferred if name in priority]
    order += [name for name in priority if name not in order]
    return [
        name for name in order
        if _is_heterogeneous(name, cfg, driver) and backend_available(name, cfg)
    ]


def _matrix_brain(cfg: dict, selected: list[str] | None = None,
                  driver: str | None = None) -> str:
    """谁做复审矩阵的主导判断/大脑。仍是候选非裁决, driver 最终过证据门。"""
    driver = _normalize_driver(driver)
    selected = selected if selected is not None else _available_heterogeneous_backends(cfg, driver)
    if driver == "codex":
        return "codex"
    if "codex" in selected:
        return "codex"
    if "arkcli" in selected:
        return "arkcli panel"
    return "claude code same-family"


def list_backends(cfg: dict) -> list:
    rows = []
    for name in cfg.get("priority", []):
        b = cfg["backends"].get(name, {})
        rows.append((name, b.get("kind", "?"), backend_available(name, cfg)))
    return rows


def build_rubric(base: str | None = None, *, role: str | None = None,
                 no_recon: bool = False) -> str:
    rubric = base or DEFAULT_RUBRIC
    if role:
        if role not in ROLE_RUBRICS:
            raise ValueError(f"unknown review role {role!r}; use one of {sorted(ROLE_RUBRICS)}")
        rubric += "\n" + ROLE_RUBRICS[role]
    if no_recon:
        rubric += NO_RECON_ADDENDUM
    return rubric


def _effective_panel_min(selected: list[str], explicit_min: int | None, configured_min) -> int:
    """Default policy matrix:
    - Claude driver: codex + arkcli require both; one missing accepts the other.
    - Codex-authored diff: arkcli + Claude Code CLI require both; no arkcli requires Claude.
    - Claude driver with neither external backend: fall back to same-family Claude."""
    if explicit_min is not None:
        return explicit_min
    if str(configured_min).strip().lower() == "auto":
        return min(2, len(selected)) if selected else 0
    return int(configured_min)


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
    def _from_json(obj: dict) -> ReviewResult | None:
        verdict = str(obj.get("verdict", "")).upper()
        if verdict not in {"PASS", "WARN", "BLOCKER"}:
            return None
        findings = []
        for i, item in enumerate(obj.get("findings", []) or [], 1):
            sev = str(item.get("severity", "")).upper()
            if sev not in {"BLOCKER", "WARN"}:
                continue
            refs = item.get("evidence_refs") or item.get("evidence") or []
            if isinstance(refs, list):
                evidence = ", ".join(str(x) for x in refs)
            else:
                evidence = str(refs)
            findings.append(Finding(
                severity=sev,
                claim=str(item.get("claim", "")).strip(),
                evidence=evidence,
                why=str(item.get("why", "")).strip(),
                id=str(item.get("id") or f"PR-{i:03d}"),
                category=str(item.get("category", "general")),
                affected_eids=item.get("affected_eids", []) or [],
                recommended_action=str(item.get("recommended_action", "review")),
            ))
        return ReviewResult(
            verdict=verdict,
            findings=findings,
            blind_spots=[str(x) for x in obj.get("blind_spots", []) or []],
            context_limits=[str(x) for x in obj.get("context_limits", []) or []],
            backend_used=backend,
            raw=text,
        )

    for m in re.finditer(r"```(?:json|xunji_peer_review_v1)?\s*(\{.*?\})\s*```", text, re.S):
        try:
            parsed = _from_json(json.loads(m.group(1)))
            if parsed:
                return parsed
        except Exception:
            continue
    try:
        parsed = _from_json(json.loads(text))
        if parsed:
            return parsed
    except Exception:
        pass

    idx = text.rfind("## Verdict")
    block = text[idx:] if idx >= 0 else text
    vm = re.search(r"##\s*Verdict[:\s*]*([A-Za-z_]+)", block)
    verdict = vm.group(1).upper() if vm else "ERROR"

    findings = []
    for i, m in enumerate(re.finditer(
            r"-\s*\[(BLOCKER|WARN)\]\s*(.+?)\s*\|\s*Evidence:\s*(.+?)\s*\|\s*Why:\s*(.+)",
            block), 1):
        claim = m.group(2).strip()
        idm = re.match(r"(PR-\d+)\s+(.+)", claim)
        fid = idm.group(1) if idm else f"PR-{i:03d}"
        if idm:
            claim = idm.group(2).strip()
        findings.append(Finding(m.group(1), claim, m.group(3).strip(), m.group(4).strip(), id=fid))

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
def _run_codex(scope_dir: Path, rubric: str, b: dict, timeout: int,
               bundle: dict | None = None,
               artifact_excerpt_chars: int = ARTIFACT_EXCERPT_CAP,
               max_bundle_chars: int = BUNDLE_CHAR_CAP) -> ReviewResult:
    # Codex reads the frozen review_bundle.json on disk; it does not rebuild or
    # inline the bundle, so excerpt sizing is controlled by review()/review_panel().
    rel = scope_dir.relative_to(ROOT).as_posix() if scope_dir.is_relative_to(ROOT) else str(scope_dir)
    prompt = (f"Review the CLOSED red-team run at {rel}. You may read any file under that "
              f"directory (read-only). Prefer {rel}/review/review_bundle.json as the frozen input. "
              f"Treat report.md/review.md/decisions.md as claims; facts must come from evidence_index "
              f"and artifact hashes. Do not read or modify anything outside it.\n\n{rubric}")
    argv = [b.get("cmd", "codex"), "exec", "-s", b.get("sandbox", "read-only")]
    if b.get("model"):
        argv.extend(["-m", b["model"]])
    if b.get("effort"):
        argv.extend(["-c", f'model_reasoning_effort={b["effort"]}'])
    try:
        proc = subprocess.run(argv, input=prompt, capture_output=True,
                              text=True, encoding="utf-8", errors="replace",
                              cwd=str(ROOT), timeout=timeout,
                              env=codex_proxy.codex_env())   # Codex CLI 走专用代理通道(与交战/模型API 隔离)
    except subprocess.TimeoutExpired:
        return ReviewResult(verdict="ERROR", backend_used="codex",
                            error=f"codex 超时(>{timeout}s)")
    out = proc.stdout or ""
    r = parse_review_output(out, "codex")
    if r.verdict == "ERROR" and proc.returncode != 0:
        r.error = f"codex exit {proc.returncode}; stderr tail: {(proc.stderr or '')[-400:]}"
    return r


def _run_openai(scope_dir: Path, rubric: str, b: dict, name: str, timeout: int,
                bundle: dict | None = None,
                artifact_excerpt_chars: int = ARTIFACT_EXCERPT_CAP,
                max_bundle_chars: int = BUNDLE_CHAR_CAP) -> ReviewResult:
    key = os.environ.get(b.get("api_key_env", ""), "")
    if not key:
        return ReviewResult(verdict="ERROR", backend_used=name,
                            error=f"缺 {b.get('api_key_env')} 环境变量")
    context = json.dumps(bundle or build_review_bundle(
        scope_dir,
        redact_egress=True,
        artifact_excerpt_chars=artifact_excerpt_chars,
        max_bundle_chars=max_bundle_chars),
                         ensure_ascii=False, indent=2)
    cap = _context_cap(PER_FILE_CAP * 8, max_bundle_chars)
    if len(context) > cap:
        context = context[:cap] + f"\n…[review_bundle truncated to {cap} chars]"
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
        with proxymod.model_no_proxy_opener().open(req, timeout=timeout) as resp:   # 模型 API 不走交战代理
            data = json.loads(resp.read().decode("utf-8", errors="replace"))
        content = data["choices"][0]["message"]["content"]
    except Exception as e:
        return ReviewResult(verdict="ERROR", backend_used=name, error=f"{name} API 失败: {e}")
    return parse_review_output(content, name)


def _arkcli_model_id(item) -> str:
    return item.get("id", "") if isinstance(item, dict) else str(item)


def _aggregate_arkcli_panel(results: list[tuple[str, ReviewResult]],
                            errors: list[str], backend_used: str) -> ReviewResult:
    findings: list[Finding] = []
    blind_spots: list[str] = []
    context_limits: list[str] = []
    verdict = "PASS"

    for model, result in results:
        if result.verdict == "BLOCKER":
            verdict = "BLOCKER"
        elif result.verdict == "WARN" and verdict != "BLOCKER":
            verdict = "WARN"
        blind_spots.extend(f"[{model}] {x}" for x in result.blind_spots)
        context_limits.extend(f"[{model}] {x}" for x in result.context_limits)
        for f in result.findings:
            findings.append(Finding(
                severity=f.severity,
                claim=f.claim,
                evidence=f.evidence,
                why=f"[arkcli:{model}] {f.why}",
                id=f"PR-{len(findings) + 1:03d}",
                category=f.category,
                affected_eids=f.affected_eids,
                recommended_action=f.recommended_action,
            ))

    if errors:
        context_limits.extend(errors)
        if verdict == "PASS":
            verdict = "WARN"
        findings.append(Finding(
            severity="WARN",
            claim="arkcli panel had backend errors; review is partial",
            evidence="; ".join(errors),
            why="At least one arkcli reviewer failed, so PASS only means the completed panel members found no blocker.",
            id=f"PR-{len(findings) + 1:03d}",
            category="backend_error",
            recommended_action="rerun_or_escalate",
        ))

    if not results:
        return ReviewResult(
            verdict="ERROR",
            backend_used=backend_used,
            error="arkcli panel 全部模型失败: " + ("; ".join(errors) if errors else "no results"),
            context_limits=errors,
        )

    raw = json.dumps({
        "panel": backend_used,
        "models": [m for m, _ in results],
        "errors": errors,
        "verdict": verdict,
    }, ensure_ascii=False, indent=2)
    return ReviewResult(
        verdict=verdict,
        findings=findings,
        blind_spots=blind_spots,
        context_limits=context_limits,
        backend_used=backend_used,
        raw=raw,
    )


def _run_arkcli_panel(scope_dir: Path, rubric: str, b: dict, timeout: int,
                      bundle: dict | None = None,
                      artifact_excerpt_chars: int = ARTIFACT_EXCERPT_CAP,
                      max_bundle_chars: int = BUNDLE_CHAR_CAP) -> ReviewResult:
    cmd = b.get("cmd", "arkcli")
    if shutil.which(cmd) is None:
        return ReviewResult(verdict="ERROR", backend_used="arkcli", error=f"arkcli not found: {cmd}")
    models = b.get("models") or []
    model_ids = [_arkcli_model_id(m) for m in models if _arkcli_model_id(m)]
    backend_used = "arkcli:" + "+".join(model_ids)
    context = json.dumps(bundle or build_review_bundle(
        scope_dir,
        redact_egress=True,
        artifact_excerpt_chars=artifact_excerpt_chars,
        max_bundle_chars=max_bundle_chars),
                         ensure_ascii=False, indent=2)
    cap = _context_cap(int(b.get("max_context_chars") or (PER_FILE_CAP * 5)), max_bundle_chars)
    if len(context) > cap:
        context = context[:cap] + f"\n…[review_bundle truncated to {cap} chars for arkcli panel]"
    panel_prompt = (
        "You are one independent reviewer in the Xunji external heterogeneous panel. "
        "Return ONLY a JSON object matching schema xunji.peer_review.v1. Do not use markdown. "
        "Your output is a candidate review note, not a final decision. "
        "Treat report.md/review.md/decisions.md as claims; facts must cite evidence_index entries "
        "or artifact hashes from the review_bundle.\n\n"
        f"{rubric}\n\n"
        f"Run audit trail (read-only) for {scope_dir.name}:\n\n{context}"
    )
    results: list[tuple[str, ReviewResult]] = []
    errors: list[str] = []
    per_model_timeout = min(timeout, int(b.get("per_model_timeout") or timeout))
    for item in models:
        model = _arkcli_model_id(item)
        if not model:
            continue
        argv = [
            cmd, "+chat", "--model", model, "--no-progress",
            "--temperature", "0", "--max-output-tokens", "2200",
            "--text-format", "json_object",
        ]
        thinking = item.get("thinking") if isinstance(item, dict) else None
        if thinking:
            argv.extend(["--thinking", str(thinking)])
        argv.append(panel_prompt)
        try:
            proc = subprocess.run(argv, capture_output=True, text=True,
                                  encoding="utf-8", errors="replace",
                                  cwd=str(ROOT), timeout=per_model_timeout,
                                  env=proxymod.model_safe_env())
        except subprocess.TimeoutExpired:
            errors.append(f"{model}: timeout >{per_model_timeout}s")
            continue
        if proc.returncode != 0:
            errors.append(f"{model}: arkcli exit {proc.returncode}; stderr/stdout tail: {((proc.stderr or '') + (proc.stdout or ''))[-500:]}")
            continue
        raw = proc.stdout or ""
        try:
            envelope = json.loads(raw)
            content = envelope.get("content") or envelope.get("reasoning_content") or raw
        except Exception:
            content = raw
        result = parse_review_output(str(content), f"arkcli:{model}")
        if result.verdict == "ERROR":
            errors.append(f"{model}: parse error; output tail: {str(content)[-500:]}")
            continue
        results.append((model, result))
    return _aggregate_arkcli_panel(results, errors, backend_used)


def _extract_claude_cli_result(stdout: str) -> str:
    """Claude Code `--output-format json` may print warnings before the JSON line."""
    for line in reversed((stdout or "").splitlines()):
        line = line.strip()
        if not line:
            continue
        try:
            obj = json.loads(line)
        except Exception:
            continue
        if isinstance(obj, dict):
            result = obj.get("result")
            if isinstance(result, str) and result.strip():
                return result
            content = obj.get("content")
            if isinstance(content, str) and content.strip():
                return content
    return stdout or ""


def _run_claude_cli(scope_dir: Path, rubric: str, b: dict, timeout: int,
                    bundle: dict | None = None,
                    artifact_excerpt_chars: int = ARTIFACT_EXCERPT_CAP,
                    max_bundle_chars: int = BUNDLE_CHAR_CAP) -> ReviewResult:
    cmd_name = b.get("cmd", "claude")
    if shutil.which(cmd_name) is None:
        return ReviewResult(verdict="ERROR", backend_used="claude:code-cli",
                            error=f"claude code cli not found: {cmd_name}")
    context = json.dumps(bundle or build_review_bundle(
        scope_dir,
        redact_egress=True,
        artifact_excerpt_chars=artifact_excerpt_chars,
        max_bundle_chars=max_bundle_chars),
                         ensure_ascii=False, indent=2)
    cap = _context_cap(PER_FILE_CAP * 8, max_bundle_chars)
    if len(context) > cap:
        context = context[:cap] + f"\n…[review_bundle truncated to {cap} chars]"

    rel = scope_dir.relative_to(ROOT).as_posix() if scope_dir.is_relative_to(ROOT) else str(scope_dir)
    prompt = (
        "You are running as Claude Code CLI in non-interactive fresh-context mode.\n"
        "You are a reviewer only: read-only, no edits, no active probing, no shell commands.\n"
        f"Scope directory: {rel}\n\n"
        f"{rubric}\n\n"
        f"Review bundle JSON for {scope_dir.name}:\n\n{context}"
    )
    cmd = [
        str(cmd_name),
        "-p",
        "--output-format", "json",
        "--no-session-persistence",
        "--permission-mode", str(b.get("permission_mode") or "dontAsk"),
    ]
    if b.get("effort"):
        cmd += ["--effort", str(b.get("effort"))]
    if b.get("model"):
        cmd += ["--model", str(b.get("model"))]
    if "tools" in b:
        cmd += ["--tools", str(b.get("tools") or "")]
    # If tools are enabled in private config, keep Claude scoped to the reviewed tree.
    cmd += ["--add-dir", str(scope_dir)]
    try:
        proc = subprocess.run(cmd, input=prompt, text=True, capture_output=True,
                              cwd=str(scope_dir), env=proxymod.model_safe_env(),
                              timeout=timeout)
    except Exception as e:
        return ReviewResult(verdict="ERROR", backend_used="claude:code-cli",
                            error=f"claude code cli failed: {e}")
    if proc.returncode != 0:
        tail = ((proc.stderr or "") + (proc.stdout or ""))[-1200:]
        return ReviewResult(verdict="ERROR", backend_used="claude:code-cli",
                            error=f"claude code cli exit {proc.returncode}; tail: {tail}")
    content = _extract_claude_cli_result(proc.stdout)
    result = parse_review_output(content, "claude:code-cli")
    result.raw = content or proc.stdout
    return result


# ===================== 主入口 =====================
def review(scope_dir, *, rubric: str | None = None, backend: str | None = None,
           out_file=None, into_run: bool = False, require_heterogeneous: bool = False,
           config: dict | None = None, timeout: int = 900,
           no_recon: bool = False, role: str | None = None,
           driver: str | None = None) -> ReviewResult:
    """对一个 run 目录做异构复审。返回 ReviewResult(候选, 非裁决 —— driver 须过证据门整合)。
    --no-recon: 该 run 无 Guanlan recon 输入, coverage.json 不存在属正常, 复审时覆盖检查降为 WARN。"""
    scope = Path(scope_dir)
    if not scope.is_absolute():
        scope = (ROOT / scope).resolve()
    if not scope.is_dir():
        return ReviewResult(verdict="ERROR", error=f"scope 目录不存在: {scope}")

    # #12: 复审前据当前 evidence.md 重生 evidence.json(它是 check_run 派生缓存; 若 driver 改了
    # evidence.md 却没跑 check_run, 旧 sidecar 会与源矛盾 → 误导独立复审。mokwon dogfood: Codex
    # 逮到 confirmed:[]/foo.html 的过期 evidence.json)。让复审看到真状态。
    cfg = config or load_config()
    driver = _normalize_driver(driver)
    egress_cfg = cfg.get("egress", {})
    redact_egress = bool(egress_cfg.get("redact_secrets", True))
    include_artifacts = str(egress_cfg.get("include_artifacts", "snippets"))
    artifact_excerpt_chars = _artifact_excerpt_cap(egress_cfg.get("artifact_excerpt_chars"))
    max_bundle_chars = _bundle_char_cap(egress_cfg.get("max_bundle_chars"))

    try:
        import evidence_parse as _ep
        _ep.write_evidence_index(scope, _ep.parse_evidence(scope))
    except Exception:
        pass
    bundle = build_review_bundle(scope, write=True, redact_egress=redact_egress,
                                 include_artifacts=include_artifacts,
                                 artifact_excerpt_chars=artifact_excerpt_chars,
                                 max_bundle_chars=max_bundle_chars)

    try:
        rubric = build_rubric(rubric, role=role, no_recon=no_recon)
    except ValueError as e:
        return ReviewResult(verdict="ERROR", error=str(e))
    if backend is None:
        candidates = _available_heterogeneous_backends(cfg, driver)
        chosen = candidates[0] if candidates else select_backend(cfg, None)
    else:
        chosen = select_backend(cfg, backend)
    if not chosen:
        return ReviewResult(verdict="ERROR",
                            error="无可用复审后端(codex 未装 + arkcli 不可用 + 无 Claude 兜底)。"
                                  "装 codex/arkcli/claude CLI。")
    if require_heterogeneous and not _is_heterogeneous(chosen, cfg, driver):
        # 同族(Claude)不满足异构独立性 —— A2: 同族减 bias 不减盲区。auto-review 不用它满足异构门,
        # 也不白跑同族 CLI。提示装真异构后端或 driver 自己 spawn 子代理。
        rel = scope.relative_to(ROOT).as_posix() if scope.is_relative_to(ROOT) else str(scope)
        return ReviewResult(verdict="NEEDS_DRIVER", backend_used=f"{chosen}:same-family-rejected",
            raw=f"[需真异构] 唯一可用后端 '{chosen}' 是同族(非异构), 不满足异构独立复审门。装 codex "
                f"或 arkcli, 或 driver spawn fresh-context 子代理复审 {rel}。")
    b = cfg["backends"][chosen]
    kind = b.get("kind")
    if kind == "cli-agent":
        result = _run_codex(scope, rubric, b, timeout, bundle,
                            artifact_excerpt_chars=artifact_excerpt_chars,
                            max_bundle_chars=max_bundle_chars)
    elif kind == "arkcli-panel":
        result = _run_arkcli_panel(scope, rubric, b, timeout, bundle,
                                   artifact_excerpt_chars=artifact_excerpt_chars,
                                   max_bundle_chars=max_bundle_chars)
    elif kind == "openai":
        result = _run_openai(scope, rubric, b, chosen, timeout, bundle,
                             artifact_excerpt_chars=artifact_excerpt_chars,
                             max_bundle_chars=max_bundle_chars)
    elif kind == "claude-code-cli":
        result = _run_claude_cli(scope, rubric, b, timeout, bundle,
                                 artifact_excerpt_chars=artifact_excerpt_chars,
                                 max_bundle_chars=max_bundle_chars)
    else:
        result = ReviewResult(verdict="ERROR", error=f"未知后端 kind: {kind}")
    result.bundle_hash = bundle.get("sha1", "")
    result.evidence_index_hash = bundle.get("evidence_index", {}).get("sha1", "")
    result.driver = driver
    result.brain = _matrix_brain(cfg, [chosen], driver)
    _mark_invalid_finding_refs(result, bundle)

    # into_run 只对【异构】后端写满足门记录: 同族 Claude 即使有 key 跑了 API, 也不满足异构独立
    # 复审门(否则用同族自审蒙混"异构"门 —— dogfood 第4次 BLOCKER)。
    backend_root = result.backend_used.split(":")[0]
    may_record_same_family = (
        backend_root == "claude"
        and driver == "claude"
        and not _available_heterogeneous_backends(cfg, driver)
    )
    if (into_run and result.verdict not in ("ERROR", "NEEDS_DRIVER")
            and (_is_heterogeneous(backend_root, cfg, driver) or may_record_same_family)):
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


def review_panel(scope_dir, *, backends: list[str] | None = None,
                 min_heterogeneous: int | None = None, max_backends: int | None = None,
                 roles: list[str] | None = None, into_run: bool = False,
                 out_file=None, json_out=None, config: dict | None = None,
                 timeout: int = 900, no_recon: bool = False,
                 driver: str | None = None) -> ReviewResult:
    """Run multiple heterogeneous review backends and aggregate their candidate
    findings. This is still advisory: a panel BLOCKER is a challenge for the
    driver to resolve, not a final vulnerability decision."""
    scope = Path(scope_dir)
    if not scope.is_absolute():
        scope = (ROOT / scope).resolve()
    if not scope.is_dir():
        return ReviewResult(verdict="ERROR", error=f"scope 目录不存在: {scope}")
    cfg = config or load_config()
    driver = _normalize_driver(driver)
    panel_cfg = cfg.get("panel", {})
    max_backends = int(max_backends or panel_cfg.get("max_backends") or 2)
    roles = roles or list(panel_cfg.get("roles") or [])
    if backends is None:
        backends = _available_heterogeneous_backends(cfg, driver)
    backends = [b for b in backends if b in cfg.get("backends", {})]
    selected = backends[:max_backends]
    min_heterogeneous = _effective_panel_min(
        selected, min_heterogeneous, panel_cfg.get("min_heterogeneous", "auto"))
    if not selected:
        if min_heterogeneous > 0:
            return ReviewResult(
                verdict="NEEDS_DRIVER",
                backend_used="panel:",
                error=f"panel completed 0/{min_heterogeneous} required heterogeneous backends",
                context_limits=[
                    f"panel completed 0/{min_heterogeneous} required heterogeneous backends"
                ],
                driver=driver,
                brain=_matrix_brain(cfg, selected, driver),
            )
        rr = review(scope, backend="claude", into_run=False, require_heterogeneous=False,
                    config=cfg, timeout=timeout, no_recon=no_recon,
                    role=roles[0] if roles else None, driver=driver)
        rr.backend_used = rr.backend_used or "claude:same-family-fallback"
        if rr.verdict not in {"ERROR", "NEEDS_DRIVER"}:
            rr.context_limits.append(
                "same-family fallback: no codex/arkcli available; this reduces reviewer independence")
            if into_run:
                _append_run_review(scope, rr)
        return rr

    results: list[tuple[str, ReviewResult]] = []
    errors: list[str] = []
    context_limits: list[str] = []
    for i, name in enumerate(selected):
        role = roles[i % len(roles)] if roles else None
        rr = review(scope, backend=name, into_run=False, require_heterogeneous=True,
                    config=cfg, timeout=timeout, no_recon=no_recon, role=role,
                    driver=driver)
        if rr.verdict in {"ERROR", "NEEDS_DRIVER"}:
            errors.append(f"{name}: {rr.verdict} {rr.error or rr.raw[-300:]}")
            # codex quota/rate-limit exhausted → auto-lower heterogeneous bar
            err_low = (rr.error or "").lower()
            if name == "codex" and any(kw in err_low for kw in ("quota", "usage limit")):
                min_heterogeneous = max(1, min_heterogeneous - 1)
                context_limits.append("codex quota/rate-limit exhausted; heterogeneous bar lowered to arkcli-only; manual-driver supplement required")
            continue
        results.append((name, rr))

    hetero_count = len(results)
    findings: list[Finding] = []
    blind_spots: list[str] = []
    verdict = "PASS"
    for name, rr in results:
        if rr.verdict == "BLOCKER":
            verdict = "BLOCKER"
        elif rr.verdict == "WARN" and verdict != "BLOCKER":
            verdict = "WARN"
        blind_spots.extend(f"[{name}] {x}" for x in rr.blind_spots)
        context_limits.extend(f"[{name}] {x}" for x in rr.context_limits)
        for f in rr.findings:
            findings.append(Finding(
                severity=f.severity,
                claim=f.claim,
                evidence=f.evidence,
                why=f"[panel:{name}] {f.why}",
                id=f"PR-{len(findings) + 1:03d}",
                category=f.category,
                affected_eids=f.affected_eids,
                recommended_action=f.recommended_action,
            ))

    if errors:
        context_limits.extend(errors)
        if verdict == "PASS":
            verdict = "WARN"
        findings.append(Finding(
            severity="WARN",
            claim="review panel had backend errors; aggregation is partial",
            evidence="; ".join(errors),
            why="At least one requested heterogeneous reviewer failed or was unavailable.",
            id=f"PR-{len(findings) + 1:03d}",
            category="backend_error",
            recommended_action="rerun_or_escalate",
        ))

    if hetero_count < min_heterogeneous:
        verdict = "NEEDS_DRIVER"
        context_limits.append(
            f"panel completed {hetero_count}/{min_heterogeneous} required heterogeneous backends")

    bundle = build_review_bundle(scope, write=True,
                                 redact_egress=bool(cfg.get("egress", {}).get("redact_secrets", True)),
                                 include_artifacts=str(cfg.get("egress", {}).get("include_artifacts", "snippets")),
                                 artifact_excerpt_chars=_artifact_excerpt_cap(
                                     cfg.get("egress", {}).get("artifact_excerpt_chars")),
                                 max_bundle_chars=_bundle_char_cap(
                                     cfg.get("egress", {}).get("max_bundle_chars")))
    result = ReviewResult(
        verdict=verdict,
        findings=findings,
        blind_spots=blind_spots,
        context_limits=context_limits,
        backend_used="panel:" + "+".join(name for name, _ in results),
        raw=json.dumps({
            "selected": selected,
            "driver": driver,
            "completed": [name for name, _ in results],
            "errors": errors,
            "min_heterogeneous": min_heterogeneous,
        }, ensure_ascii=False, indent=2),
        error="; ".join(errors) if verdict == "NEEDS_DRIVER" else "",
        bundle_hash=bundle.get("sha1", ""),
        evidence_index_hash=bundle.get("evidence_index", {}).get("sha1", ""),
        driver=driver,
        brain=_matrix_brain(cfg, selected, driver),
    )

    if into_run and result.verdict not in {"ERROR", "NEEDS_DRIVER"}:
        _append_run_review(scope, result)
    if out_file:
        out = Path(out_file)
        if not out.is_absolute():
            out = ROOT / out
        out.parent.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%MZ")
        header = (f"# Peer Review Panel — {scope.name}\n\n_backend: {result.backend_used} · {stamp}_\n"
                  f"> 候选, 非裁决。driver 须逐条过证据门。\n\n")
        out.write_text(header + result.as_markdown(), encoding="utf-8")
    if json_out:
        out = Path(json_out)
        if not out.is_absolute():
            out = ROOT / out
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(result.as_dict(), ensure_ascii=False, indent=2),
                       encoding="utf-8")
    return result


# arkcli panel 是外部异构补盲团; 聚合结果仍是候选非裁决。Codex + evidence gate + run 才做最终裁决。
def _strip_template_review_placeholders(text: str) -> str:
    """Remove the old docs/templates/run/review.md fake PR block if a run inherited it.

    The real ledger is generated by peer_review.py. A blank `PR-001 — BLOCKER —
    category` template looks exactly like a pending finding to check_run, so it
    must not survive into an appended review.
    """
    return re.sub(
        r"(?ms)^###\s+PR-001\s+—\s+BLOCKER\s+—\s+category\s*\n"
        r"\s*-\s*Status\s*:\s*pending\s*\n"
        r"\s*-\s*Claim\s*:\s*\n"
        r"\s*-\s*EvidenceRefs\s*:\s*\n"
        r"\s*-\s*AffectedEIDs\s*:\s*\n"
        r"\s*-\s*RecommendedAction\s*:\s*\n"
        r"\s*-\s*Why\s*:\s*\n"
        r"\s*-\s*DriverResolution\s*:\s*pending\s*\n?",
        "",
        text,
    )


def _append_run_review(run_dir: Path, result: ReviewResult) -> None:
    """把复审【追加】进 runs/<t>/review.md 的独立复审区块 —— 满足 check_run 的独立复审硬门
    (re.search 'Independent Review|独立复审')。追加不覆盖(review.md 可能已有别的内容)。
    NEEDS_DRIVER/ERROR 不写(没真复审就不该满足门)。"""
    rv = run_dir / "review.md"
    existing = rv.read_text(encoding="utf-8", errors="replace") if rv.exists() else "# Review\n"
    existing = _strip_template_review_placeholders(existing)
    stamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%MZ")
    backend_root = (result.backend_used or "").split(":")[0]
    driver = _normalize_driver(result.driver)
    same_family_fallback = backend_root == "claude" and driver == "claude"
    review_kind = "same-family peer_review fallback" if same_family_fallback else "heterogeneous peer_review"
    if same_family_fallback:
        review_note = "同族 Claude 兜底复审, 独立性弱于 Codex/arkcli; 仍是候选非裁决。"
    elif backend_root == "claude" and driver == "codex":
        review_note = "Claude Code CLI 相对 Codex-authored diff 是独立复审; 候选非裁决。"
    else:
        review_note = "异构独立复审, 候选非裁决。"
    ledger = ["## Review Finding Ledger",
              f"- BundleHash: {result.bundle_hash or '(missing)'}",
              f"- EvidenceIndexHash: {result.evidence_index_hash or '(missing)'}"]
    if result.findings:
        for i, f in enumerate(result.findings, 1):
            if not f.id:
                f.id = f"PR-{i:03d}"
            ledger += [
                f"### {f.id} — {f.severity} — {f.category}",
                f"- Status: pending",
                f"- Claim: {f.claim}",
                f"- EvidenceRefs: {f.evidence}",
                f"- AffectedEIDs: {', '.join(f.affected_eids) if f.affected_eids else '(none)'}",
                f"- RecommendedAction: {f.recommended_action}",
                f"- Why: {f.why}",
                "- DriverResolution: pending",
            ]
    else:
        ledger.append("- (none)")
    block = (f"## Independent Review ({review_kind} · {result.backend_used} · {stamp})\n"
             f"> {review_note}矩阵大脑: {result.brain or '(unknown)'}。事实只来自 evidence_index/artifact hash; "
             "report/review/decisions 只是 claim。driver 必须逐条处理 PR-xxx。\n\n"
             + result.as_markdown() + "\n\n" + "\n".join(ledger) + "\n")
    rv.write_text(existing.rstrip() + "\n\n" + block, encoding="utf-8")


ALLOWED_RESOLUTION_STATUSES = {"accepted", "dismissed", "superseded", "escalated"}


def resolve_finding(run_dir: Path, pr_id: str, status: str, resolution: str) -> None:
    """Resolve a PR-xxx review finding on the record. This is intentionally narrow:
    it edits only Status / DriverResolution inside that PR block."""
    status_l = status.strip().lower()
    if status_l not in ALLOWED_RESOLUTION_STATUSES:
        raise ValueError(f"invalid status {status!r}; use one of {sorted(ALLOWED_RESOLUTION_STATUSES)}")
    if not resolution.strip():
        raise ValueError("resolution is required")
    rv = run_dir / "review.md"
    if not rv.exists():
        raise FileNotFoundError(f"review.md not found: {rv}")
    text = rv.read_text(encoding="utf-8", errors="replace")
    pat = re.compile(rf"(?ms)(^###\s+{re.escape(pr_id)}\s+—\s+(?:BLOCKER|WARN)\b)(.*?)(?=^###\s+PR-\d+\s+—|^##\s|\Z)")
    m = pat.search(text)
    if not m:
        raise ValueError(f"{pr_id} not found in Review Finding Ledger")
    block = m.group(2)
    if re.search(r"(?im)^\s*-\s*Status\s*[:：]", block):
        block = re.sub(r"(?im)^\s*-\s*Status\s*[:：].*$", f"- Status: {status_l}", block, count=1)
    else:
        block = "\n- Status: " + status_l + block
    if re.search(r"(?im)^\s*-\s*DriverResolution\s*[:：]", block):
        block = re.sub(r"(?im)^\s*-\s*DriverResolution\s*[:：].*$",
                       f"- DriverResolution: {resolution.strip()}", block, count=1)
    else:
        block = block.rstrip() + f"\n- DriverResolution: {resolution.strip()}\n"
    text = text[:m.start(2)] + block + text[m.end(2):]
    rv.write_text(text, encoding="utf-8")


# ===================== CLI / selftest =====================
def _selftest() -> int:
    checks = []
    cfg = load_config()
    checks.append(("默认配置 priority = codex > arkcli > claude",
                   cfg["priority"] == ["codex", "arkcli", "claude"]))
    checks.append(("默认 panel min_heterogeneous=auto",
                   cfg["panel"]["min_heterogeneous"] == "auto"))
    checks.append(("默认 arkcli panel 模型顺序",
                   [_arkcli_model_id(x) for x in cfg["backends"]["arkcli"]["models"]]
                   == ["kimi-k2.7-code", "minimax-m3", "glm-5.2"]))
    checks.append(("默认 arkcli panel 不禁用 thinking",
                   all(not (isinstance(x, dict) and x.get("thinking") == "disabled")
                       for x in cfg["backends"]["arkcli"]["models"])))
    checks.append(("默认 artifact excerpt cap 覆盖旧 1200 字截断",
                   cfg["egress"].get("artifact_excerpt_chars") == ARTIFACT_EXCERPT_CAP))
    checks.append(("默认 max_bundle_chars 有效",
                   cfg["egress"].get("max_bundle_chars") == BUNDLE_CHAR_CAP))
    checks += [
        ("driver matrix order: claude -> codex,arkcli",
         _driver_matrix_order("claude") == ["codex", "arkcli"]),
        ("driver matrix order: codex -> arkcli,claude",
         _driver_matrix_order("codex") == ["arkcli", "claude"]),
        ("panel auto min: codex+arkcli -> 2",
         _effective_panel_min(["codex", "arkcli"], None, "auto") == 2),
        ("panel auto min: codex-driver arkcli+claude -> 2",
         _effective_panel_min(["arkcli", "claude"], None, "auto") == 2),
        ("panel auto min: only arkcli -> 1",
         _effective_panel_min(["arkcli"], None, "auto") == 1),
        ("panel auto min: only codex -> 1",
         _effective_panel_min(["codex"], None, "auto") == 1),
        ("panel auto min: no hetero -> 0",
         _effective_panel_min([], None, "auto") == 0),
        ("panel explicit min overrides auto",
         _effective_panel_min(["arkcli"], 2, "auto") == 2),
    ]
    checks.append(("driver aliases normalize",
                   _normalize_driver("claude-code") == "claude"
                   and _normalize_driver("codex-cli") == "codex"))
    checks += [
        ("matrix brain: full claude driver -> codex",
         _matrix_brain(cfg, ["codex", "arkcli"], "claude") == "codex"),
        ("matrix brain: no codex -> arkcli panel",
         _matrix_brain(cfg, ["arkcli"], "claude") == "arkcli panel"),
        ("matrix brain: no arkcli -> codex",
         _matrix_brain(cfg, ["codex"], "claude") == "codex"),
        ("matrix brain: no hetero -> claude code same-family",
         _matrix_brain(cfg, [], "claude") == "claude code same-family"),
        ("matrix brain: codex driver full -> codex",
         _matrix_brain(cfg, ["arkcli", "claude"], "codex") == "codex"),
    ]
    fake_all = json.loads(json.dumps(DEFAULT_CONFIG))
    fake_all["priority"] = ["claude", "arkcli", "codex"]  # private config cannot invert the matrix
    for n in ("codex", "arkcli", "claude"):
        fake_all["backends"][n]["kind"] = "claude-code-cli"
        fake_all["backends"][n]["cmd"] = sys.executable
    checks += [
        ("matrix selection ignores inverted priority for claude driver",
         _available_heterogeneous_backends(fake_all, "claude")[:2] == ["codex", "arkcli"]),
        ("matrix selection for codex driver is arkcli+claude",
         _available_heterogeneous_backends(fake_all, "codex")[:2] == ["arkcli", "claude"]),
    ]

    # 优先级选择: 模拟可用性
    fake = json.loads(json.dumps(DEFAULT_CONFIG))
    os.environ.pop("DEEPSEEK_API_KEY", None)
    os.environ.pop("GLM_API_KEY", None)
    fake["backends"]["arkcli"]["cmd"] = "__missing_arkcli__"
    fake["backends"]["claude"]["cmd"] = sys.executable
    # claude CLI 可用 -> 无 codex/无 arkcli 时应选 claude(兜底)
    sel_fallback = select_backend(
        {"priority": ["arkcli", "claude"], "backends": fake["backends"]})
    checks.append(("无 arkcli 时优先级落到 claude 兜底", sel_fallback == "claude"))
    # forced 强制
    checks.append(("--backend 强制存在的后端",
                   select_backend(cfg, "arkcli") == "arkcli"))
    checks.append(("--backend 不存在 -> None", select_backend(cfg, "nope") is None))
    checks.append(("claude-code-cli cmd 存在时 available 或可被本地环境决定",
                   backend_available("claude", cfg) == (shutil.which(cfg["backends"]["claude"]["cmd"]) is not None)))
    checks.append(("arkcli-panel cmd 存在时 available 或可被本地环境决定",
                   backend_available("arkcli", cfg) == (shutil.which(cfg["backends"]["arkcli"]["cmd"]) is not None)))

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
    json_sample = """```json
{"schema":"xunji.peer_review.v1","verdict":"BLOCKER","findings":[{"severity":"BLOCKER","category":"weak_evidence","claim":"missing control","evidence_refs":["E-001","evidence/x.html"],"affected_eids":["E-001"],"recommended_action":"add_control","why":"no baseline"}],"blind_spots":["control gap"],"context_limits":[]}
```"""
    r_json = parse_review_output(json_sample, "glm")
    checks.append(("解析 JSON verdict=BLOCKER", r_json.verdict == "BLOCKER"))
    checks.append(("解析 JSON finding category/action/eid",
                   r_json.findings[0].category == "weak_evidence"
                   and r_json.findings[0].recommended_action == "add_control"
                   and r_json.findings[0].affected_eids == ["E-001"]))
    checks.append(("as_dict emits schema/findings",
                   r_json.as_dict()["schema"] == "xunji.peer_review_result.v1"
                   and r_json.as_dict()["findings"][0]["affected_eids"] == ["E-001"]
                   and "brain" in r_json.as_dict()))
    checks.append(("role rubric appends focus",
                   "ROLE FOCUS — evidence_skeptic" in build_rubric(role="evidence_skeptic")))
    try:
        build_rubric(role="not-a-role")
        role_bad = False
    except ValueError:
        role_bad = True
    checks.append(("unknown role rejected", role_bad))
    panel = _aggregate_arkcli_panel(
        [("glm-5.2", ReviewResult(verdict="PASS", backend_used="arkcli:glm-5.2")),
         ("kimi-k2.7-code", ReviewResult(
             verdict="WARN",
             findings=[Finding("WARN", "possible shallow closure", "F-001", "needs one more control",
                               category="shallow_closure", affected_eids=["E-001"])],
             backend_used="arkcli:kimi-k2.7-code"))],
        ["minimax-m3: timeout >1s"],
        "arkcli:glm-5.2+kimi-k2.7-code+minimax-m3")
    checks.append(("arkcli panel 聚合 WARN + backend_error", panel.verdict == "WARN" and len(panel.findings) == 2))
    checks.append(("arkcli panel PR id 唯一化", [f.id for f in panel.findings] == ["PR-001", "PR-002"]))
    panel_matrix = ReviewResult(verdict="PASS", backend_used="panel:codex+arkcli", brain="codex")
    checks.append(("as_markdown emits brain",
                   "_brain: codex_" in panel_matrix.as_markdown()))

    # (none) 不计入
    none_sample = "## Verdict: PASS\n## Findings\n- (none)\n## Blind-spot check\n- (none)\n"
    r3 = parse_review_output(none_sample)
    checks.append(("(none) 不计入 findings", len(r3.findings) == 0))
    checks.append(("(none) 不计入 blind", len(r3.blind_spots) == 0))
    cli_json = 'warning\n{"type":"result","result":"## Verdict: PASS\\n## Findings\\n- (none)"}\n'
    checks.append(("Claude CLI JSON result parser ignores warning",
                   _extract_claude_cli_result(cli_json).startswith("## Verdict: PASS")))

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
    (d_run / "evidence.md").write_text(
        "# Evidence Ledger\n\n## E-001 — x\n- Certainty: 0.8\n- Control: yes\n- Artifacts: `a.html`\n",
        encoding="utf-8")
    (d_run / "a.html").write_text("ok", encoding="utf-8")
    b_run = build_review_bundle(d_run, write=True)
    (d_run / "secret.txt").write_text("Authorization: Bearer abcdefghijk123456\n", encoding="utf-8")
    (d_run / "evidence.md").write_text(
        "# Evidence Ledger\n\n## E-001 — x\n- Certainty: 0.8\n- Control: yes\n"
        "- Artifacts: `secret.txt`\n",
        encoding="utf-8")
    b_redacted = build_review_bundle(d_run, redact_egress=True)
    b_unredacted = build_review_bundle(d_run, redact_egress=False)
    redacted_blob = json.dumps(b_redacted, ensure_ascii=False)
    unredacted_blob = json.dumps(b_unredacted, ensure_ascii=False)
    (d_run / "long.txt").write_text("A" * 1300 + "KEEP_TAIL", encoding="utf-8")
    (d_run / "evidence.md").write_text(
        "# Evidence Ledger\n\n## E-001 — x\n- Certainty: 0.8\n- Control: yes\n"
        "- Artifacts: `long.txt`\n",
        encoding="utf-8")
    b_long = build_review_bundle(d_run)
    b_long_small = build_review_bundle(d_run, artifact_excerpt_chars=100)
    b_tiny_bundle_cap = build_review_bundle(d_run, max_bundle_chars=100)
    long_art = b_long["evidence_index"]["entries"][0]["artifacts"][0]
    long_small_art = b_long_small["evidence_index"]["entries"][0]["artifacts"][0]
    (d_run / "evidence.md").write_text(
        "# Evidence Ledger\n\n## E-001 — x\n- Certainty: 0.8\n- Control: yes\n- Artifacts: `a.html`\n",
        encoding="utf-8")
    rr_block = ReviewResult(verdict="BLOCKER",
                            findings=[Finding("BLOCKER", "x", "E-001", "y")],
                            backend_used="codex",
                            bundle_hash=b_run["sha1"],
                            evidence_index_hash=b_run["evidence_index"]["sha1"])
    _append_run_review(d_run, rr_block)
    rv1 = (d_run / "review.md").read_text(encoding="utf-8")
    resolve_finding(d_run, "PR-001", "dismissed", "Evidence: E-001 artifact a.html supports dismissal")
    rv_resolved = (d_run / "review.md").read_text(encoding="utf-8")
    _append_run_review(d_run, ReviewResult(verdict="PASS", backend_used="arkcli:glm-5.2+kimi-k2.7-code+minimax-m3"))
    rv2 = (d_run / "review.md").read_text(encoding="utf-8")
    d_tpl = Path(tempfile.mkdtemp())
    (d_tpl / "review.md").write_text(
        "# Review\n\n## Review Finding Ledger\n\n"
        "### PR-001 — BLOCKER — category\n\n"
        "- Status: pending\n- Claim:\n- EvidenceRefs:\n- AffectedEIDs:\n"
        "- RecommendedAction:\n- Why:\n- DriverResolution: pending\n",
        encoding="utf-8")
    _append_run_review(d_tpl, rr_block)
    rv_tpl = (d_tpl / "review.md").read_text(encoding="utf-8")
    checks += [
        ("into_run 写'Independent Review'标记(满足门)", bool(_re.search(r"Independent Review", rv1))),
        ("into_run 保留已有内容(追加不覆盖)", "已有内容" in rv1),
        ("into_run 写 verdict/finding", "BLOCKER" in rv1 and "x" in rv1),
        ("into_run 写 PR pending ledger", "Review Finding Ledger" in rv1 and "Status: pending" in rv1),
        ("into_run strips old blank PR template before appending",
         rv_tpl.count("### PR-001") == 1 and "— category" not in rv_tpl),
        ("resolve_finding 更新 status/resolution",
         "Status: dismissed" in rv_resolved and "Evidence: E-001 artifact a.html" in rv_resolved),
        ("bundle 写入 review/review_bundle.json", (d_run / "review" / "review_bundle.json").exists()),
        ("bundle redacts obvious bearer token",
         "abcdefghijk123456" not in redacted_blob and "abcdefghijk123456" in unredacted_blob),
        ("bundle artifact excerpt keeps evidence after old 1200 char cap",
         "KEEP_TAIL" in long_art.get("excerpt", "")),
        ("bundle artifact excerpt cap remains configurable",
         long_small_art.get("excerpt_truncated_chars", 0) > 0
         and "KEEP_TAIL" not in long_small_art.get("excerpt", "")),
        ("bundle max_bundle_chars emits warning when exceeded",
         b_tiny_bundle_cap.get("warnings")
         and any("exceed max_bundle_chars=100" in w for w in b_tiny_bundle_cap["warnings"])
         and any("artifact excerpts reached 0" in w for w in b_tiny_bundle_cap["warnings"])
         and b_tiny_bundle_cap["egress_redaction"]["artifact_excerpt_chars"] < ARTIFACT_EXCERPT_CAP),
        ("into_run 二次追加不覆盖(两区块)", rv2.count("Independent Review") == 2),
    ]
    d_machine = Path(tempfile.mkdtemp())
    (d_machine / "evidence.md").write_text(
        "# Evidence Ledger\n\n## E-777 — no artifact\n- Maturity: finding\n- Certainty: 0.8\n- Control: yes\n",
        encoding="utf-8")
    b_machine = build_review_bundle(d_machine)
    checks.append(("bundle machine_findings includes missing artifact blocker",
                   any(x.get("category") == "missing_artifact"
                       for x in b_machine.get("machine_findings", []))))
    p_need = review_panel(d_machine, backends=[], min_heterogeneous=1)
    checks.append(("review_panel with no backends needs driver", p_need.verdict == "NEEDS_DRIVER"))
    rr_bad = ReviewResult(
        verdict="WARN",
        findings=[Finding("WARN", "bad eid", "E-404", "why", id="PR-009", affected_eids=["E-404"])],
        backend_used="codex")
    _mark_invalid_finding_refs(rr_bad, b_run)
    checks.append(("invalid affected_eids annotated, not silent",
                   rr_bad.context_limits and "E-404" in rr_bad.findings[0].why))

    # 异构性 + non-write guard (dogfood 第4次 BLOCKER 修复)
    cfg_d = load_config()
    d_err = Path(tempfile.mkdtemp())
    review(d_err, backend="nonexistent_xyz", into_run=True)   # 无此后端 -> ERROR
    d_sf = Path(tempfile.mkdtemp())
    rr_sf = review(d_sf, config={"priority": ["claude"], "backends": cfg_d["backends"]},
                   require_heterogeneous=True, into_run=True)  # 只同族 claude + require -> NEEDS_DRIVER
    checks += [
        ("heterogeneous: codex/arkcli=True, claude=False",
         _is_heterogeneous("codex", cfg_d) and _is_heterogeneous("arkcli", cfg_d)
         and not _is_heterogeneous("claude", cfg_d)),
        ("codex driver: codex=self, arkcli/claude=independent",
         not _is_heterogeneous("codex", cfg_d, "codex")
         and _is_heterogeneous("arkcli", cfg_d, "codex")
         and _is_heterogeneous("claude", cfg_d, "codex")),
        ("into_run: ERROR verdict 不写 review.md(non-write guard)", not (d_err / "review.md").exists()),
        ("require_hetero: 唯一同族 claude -> NEEDS_DRIVER(不跑/不写)", rr_sf.verdict == "NEEDS_DRIVER"),
        ("require_hetero: 同族不写 review.md", not (d_sf / "review.md").exists()),
    ]
    _append_run_review(d_run, ReviewResult(verdict="PASS", backend_used="claude",
                                           driver="codex"))
    rv_codex_driver = (d_run / "review.md").read_text(encoding="utf-8")
    checks.append(("codex driver 下 Claude 记录为独立复审",
                   "Claude Code CLI 相对 Codex-authored diff 是独立复审" in rv_codex_driver
                   and "same-family peer_review fallback · claude" not in rv_codex_driver.split("Claude Code CLI 相对 Codex-authored diff 是独立复审")[-1]))

    bad = [n for n, ok in checks if not ok]
    for n, ok in checks:
        print(f"{'ok  ' if ok else 'FAIL'} {n}")
    if bad:
        print(f"\npeer_review selftest FAILED: {len(bad)} 项")
        return 1
    print(f"\npeer_review selftest passed ({len(checks)} checks)")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description="异构复审矩阵 (Claude-authored: Codex+arkcli; Codex-authored: arkcli+Claude)")
    ap.add_argument("scope", nargs="?", help="run 目录, 如 runs/<target>")
    ap.add_argument("--backend", help="强制单后端: codex|arkcli|claude (legacy: deepseek|glm)。不指定则按矩阵跑 panel。")
    ap.add_argument("--driver", choices=["claude", "codex"], default=None,
                    help="作者/评审对象模式(默认 claude; 可用 XUNJI_REVIEW_DRIVER 覆盖)。claude-authored: Codex+arkcli; codex-authored: arkcli+Claude, 排除 Codex 自审票。")
    ap.add_argument("--out", help="把复审写到该文件(如 review/records/<x>.md)")
    ap.add_argument("--json-out", help="把结构化复审结果写到 JSON 文件")
    ap.add_argument("--into-run", action="store_true",
                    help="把复审追加进 runs/<t>/review.md 独立复审区块(满足 check_run 独立复审门)")
    ap.add_argument("--role", choices=sorted(ROLE_RUBRICS),
                    help="角色化复审: evidence_skeptic|closure_skeptic|report_consistency|scope_safety")
    ap.add_argument("--panel", action="store_true",
                    help="跑多后端矩阵 panel, 聚合候选 findings。不指定 --backend 时这是默认行为。")
    ap.add_argument("--panel-backends",
                    help="配合 --panel: 逗号分隔后端列表, 如 codex,arkcli")
    ap.add_argument("--min-heterogeneous", type=int, default=None,
                    help="配合 --panel: 最少成功异构后端数(默认 auto: 满配2, 缺一边1)")
    ap.add_argument("--max-backends", type=int, default=None,
                    help="配合 --panel: 最多尝试后端数(默认读配置, 通常 2)")
    ap.add_argument("--no-recon", action="store_true",
                    help="无 Guanlan recon 输入: 覆盖检查降为 WARN, 不因 coverage.json 缺失报 BLOCKER")
    ap.add_argument("--bundle-only", action="store_true",
                    help="只生成 runs/<t>/review/review_bundle.json 并打印 bundle/evidence hash, 不调用模型")
    ap.add_argument("--resolve", metavar="PR-XXX",
                    help="只更新 review.md 中某条 PR-xxx 的处理状态, 不调用模型")
    ap.add_argument("--status", choices=sorted(ALLOWED_RESOLUTION_STATUSES),
                    help="配合 --resolve: accepted|dismissed|superseded|escalated")
    ap.add_argument("--resolution", help="配合 --resolve: 证据化 DriverResolution 文本")
    ap.add_argument("--timeout", type=int, default=900)
    ap.add_argument("--list-backends", action="store_true", help="列后端可用性后退出")
    ap.add_argument("--selftest", action="store_true")
    args = ap.parse_args()

    if args.selftest:
        return _selftest()

    cfg = load_config()
    if args.list_backends:
        driver = _normalize_driver(args.driver)
        print("后端可用性(按优先级):")
        for name, kind, ok in list_backends(cfg):
            indep = _is_heterogeneous(name, cfg, driver)
            print(f"  {'[可用]' if ok else '[ 不可用 ]'}  {name:10} ({kind}, {'independent' if indep else 'same/self'})")
        if args.backend:
            chosen = select_backend(cfg, args.backend)
            print(f"\n单后端: {chosen or '(无可用后端)'}")
        else:
            selected = _available_heterogeneous_backends(cfg, driver)
            print(f"\n矩阵复审: {', '.join(selected) if selected else 'claude'}")
            print(f"大脑: {_matrix_brain(cfg, selected, driver)}")
        return 0

    if not args.scope:
        ap.error("需要 scope 目录(或用 --list-backends / --selftest)")
    if args.resolve:
        if not args.status or not args.resolution:
            ap.error("--resolve 需要同时提供 --status 和 --resolution")
        scope = Path(args.scope)
        if not scope.is_absolute():
            scope = (ROOT / scope).resolve()
        resolve_finding(scope, args.resolve, args.status, args.resolution)
        print(json.dumps({"resolved": args.resolve, "status": args.status,
                          "review": (scope / "review.md").as_posix()},
                         ensure_ascii=False, indent=2))
        return 0
    if args.bundle_only:
        scope = Path(args.scope)
        if not scope.is_absolute():
            scope = (ROOT / scope).resolve()
        egress_cfg = cfg.get("egress", {})
        bundle = build_review_bundle(
            scope,
            write=True,
            redact_egress=bool(egress_cfg.get("redact_secrets", True)),
            include_artifacts=str(egress_cfg.get("include_artifacts", "snippets")),
            artifact_excerpt_chars=_artifact_excerpt_cap(egress_cfg.get("artifact_excerpt_chars")),
            max_bundle_chars=_bundle_char_cap(egress_cfg.get("max_bundle_chars")),
        )
        print(json.dumps({"bundle_hash": bundle["sha1"],
                          "evidence_index_hash": bundle["evidence_index"]["sha1"],
                          "path": (scope / "review" / "review_bundle.json").as_posix()},
                         ensure_ascii=False, indent=2))
        return 0
    use_panel = args.panel or args.backend is None
    if use_panel:
        panel_backends = [x.strip() for x in args.panel_backends.split(",") if x.strip()] \
            if args.panel_backends else None
        r = review_panel(
            args.scope,
            backends=panel_backends,
            min_heterogeneous=args.min_heterogeneous,
            max_backends=args.max_backends,
            roles=[args.role] if args.role else None,
            into_run=args.into_run,
            out_file=args.out,
            json_out=args.json_out,
            config=cfg,
            timeout=args.timeout,
            no_recon=args.no_recon,
            driver=args.driver,
        )
    else:
        r = review(args.scope, backend=args.backend, out_file=args.out, into_run=args.into_run,
                   config=cfg, timeout=args.timeout, no_recon=args.no_recon, role=args.role,
                   driver=args.driver)
        if args.json_out:
            out = Path(args.json_out)
            if not out.is_absolute():
                out = ROOT / out
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_text(json.dumps(r.as_dict(), ensure_ascii=False, indent=2),
                           encoding="utf-8")
    print(r.as_markdown())
    if r.verdict == "NEEDS_DRIVER":
        print("\n[!] 未完成所需独立复审矩阵 —— 请 driver spawn fresh-context 子代理或补齐可用后端, "
              "prompt 见上(raw)。", file=sys.stderr)
        print("\n--- driver 子代理 prompt ---\n" + r.raw, file=sys.stderr)
    return 0 if r.verdict != "ERROR" else 1


if __name__ == "__main__":
    raise SystemExit(main())
