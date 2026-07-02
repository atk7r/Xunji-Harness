#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Stop hook: 收口闸门提醒器 —— 把"收口"从聊天里的口头宣布拉回 run 文件过闸门。

背景(hamastar run 教训): check_run 是 driver 主动跑的结构闸门; 我那次在【聊天里】宣布
"测完了/adequately probed"、却没跑 check_run, 工具链整段没启动 → 覆盖台账缺建 + 假证据
全部静默放行。根因: 闸门被动, 只在 driver 主动调用且 report 写了收口措辞时才硬审。

本 hook 在 Claude 每次停止响应时触发: 若存在【刚刚改动过的、且已写成实质终版报告的】run,
就替 driver 跑一遍 check_run; 没过就持续 decision=block, 把硬门结果怼回 driver 面前,
逼它去建覆盖台账/补真产物/派独立复审, 而不是就此收工。

Phase 架构:
  Phase 3 — 漂移提醒(D1: notify, 从 session_state 读取, 不再使用 drift_block.json)
  Phase 4 — 证据严重度闸门(block: 无数据 HIGH/CRITICAL → 要求补证据)
  Phase 2 — session 超时检测(block: 超时+漂移信号 → 要求重启会话)

与 safety_gate 的根本区别(复审重点):
  - safety_gate 拦【不可逆危害】, 必须 FAIL-CLOSED(读不到事件就拒绝)。
  - run_gate 是【流程提醒】, 不防危害、只防遗漏, 必须 FAIL-OPEN: 自身任何异常(读不到事件 /
    找不到 run / check_run 报错 / 超时)都【静默放行 exit 0】, 绝不因为一个提醒器而卡死会话。
防循环: 仅纯提醒类路径使用 systemMessage; 客观硬门(check_run / severity / replay / timeout /
Agent Board / completion review)不因 stop_hook_active 降级。cqytxy_20260702 证明“最多拦一次”
会把硬门退化成提醒, driver 会继续收口。

Protocol: 读 stdin 的 Stop 事件; 仅在需要时往 stdout 写 {"decision":"block","reason":...}
(拦) 或 {"systemMessage":...}(提示)。其余 exit 0 静默。纯 stdlib。
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
RUNS = ROOT / "runs"
ACTIVE_WINDOW_SEC = 900   # 只对最近 15 分钟内改动过的 run 介入(= 当前正在做的那个)
DRIFT_TIMEOUT_WINDOW_SEC = 6 * 60 * 60   # Phase 2 单独长窗口, 用于抓住超过 30 分钟的未解漂移
SESSION_TIMEOUT_SEC = 30 * 60   # Phase 2: 超过 30 分钟未更新 + 有漂移信号 → 阻断

sys.path.insert(0, str(ROOT / "tools"))
try:
    import check_run as _cr   # 复用 _report_is_final, 与 check_run 的"是否终版"判定一致
except Exception:
    _cr = None

try:
    from anti_drift import (
        find_active_run as _shared_find_active_run,
        is_dev_mode as _is_dev_mode,
        is_normal_mode as _is_normal_mode,
        _valid_ts,
        SessionStateManager,
    )
except Exception:
    _shared_find_active_run = None

    def _is_dev_mode() -> bool:
        return False

    def _is_normal_mode() -> bool:
        return False

    def _valid_ts(value, now: float) -> float:
        try:
            ts = float(value)
        except Exception:
            return 0.0
        if ts < 0 or ts > now + 60:
            return 0.0
        return ts

    class SessionStateManager:
        @staticmethod
        def load(run_dir):
            return {}
        @staticmethod
        def save(run_dir, state):
            pass
        @staticmethod
        def get_drift_flags(run_dir):
            return []
        @staticmethod
        def reset_if_stale(run_dir, hard_block_active=False):
            return {}


# ---- Field boundary constants (kept in sync with evidence format) ----
_RESULT_TERMINATORS = (
    "- Time:", "- Source:", "- Certainty:", "- Severity:", "- Next:",
    "- Caused", "- Alternative:", "- Supports:", "- Refutes:",
    "- Replicated:", "- Artifacts:",
)
_SUBFIELDS = ("Observed", "DataObtained", "Mechanism", "SeverityBasis")


def find_active_run(runs_root: Path, within_sec: int = ACTIVE_WINDOW_SEC) -> Path | None:
    """Return active run using the shared anti_drift implementation.
    Fallback is fail-open compatible and only used when anti_drift cannot import."""
    if _shared_find_active_run is not None:
        try:
            return _shared_find_active_run(runs_root, within_sec=within_sec)
        except Exception:
            return None
    if not runs_root.is_dir():
        return None
    now = time.time()
    best: Path | None = None
    best_mt = 0.0
    for rpt in runs_root.glob("*/*.md"):
        try:
            mt = rpt.stat().st_mtime
        except Exception:
            continue
        if mt > best_mt:
            best_mt, best = mt, rpt.parent
    if best is not None and (now - best_mt) <= within_sec:
        return best
    return None


def report_is_final(run_dir: Path) -> bool:
    """复用 check_run._report_is_final: report.md 引用了已确认(>=0.8)发现 = 实质终版报告。
    check_run 不可用时返回 False(fail-open: 拿不准就不介入)。"""
    if _cr is None:
        return False
    try:
        return bool(_cr._report_is_final(run_dir))
    except Exception:
        return False


def gate_skipped(run_dir: Path) -> bool:
    """操作者显式豁免: report.md 含 `run-gate: skip` 标记 = 已知此 run 不追求收尾(教学样本 /
    egress-deferred 中止), Stop hook 不再主动提醒。**只让提醒器闭嘴, 不豁免 check_run 本身**——
    手动跑 check_run 仍如实 fail, 故不构成绕过硬门的后门(防"标注一下就过闸门"的滥用)。"""
    try:
        return "run-gate: skip" in (run_dir / "report.md").read_text(encoding="utf-8", errors="replace")
    except Exception:
        return False


def _check_session_timeout(
    runs_root: Path,
    active_run: Path | None = None,
) -> tuple[str | None, str]:
    """Phase 2 fail-safe: check ONLY the active run's session_state.json for timeout + drift signals.
    Fixes cross-run contamination — stale session no longer blocks other runs.
    Uses drift_started_at when available so output_gate can refresh state before run_gate
    without erasing the age of an unresolved drift streak."""
    active_run = active_run or find_active_run(runs_root, within_sec=DRIFT_TIMEOUT_WINDOW_SEC)
    if active_run is None:
        return None, ""
    sf = active_run / "session_state.json"
    if not sf.exists():
        return None, ""
    now = time.time()
    try:
        sf_mtime = sf.stat().st_mtime
        state = json.loads(sf.read_text(encoding="utf-8"))
        drift_flags = state.get("drift_flags", [])
        if not isinstance(drift_flags, list) or not drift_flags:
            return None, ""
        drift_started_at = _valid_ts(state.get("drift_started_at"), now)
        updated_at = _valid_ts(state.get("updated_at"), now)
        last_touch = drift_started_at or max(updated_at, sf_mtime)
        timeout_sec = SESSION_TIMEOUT_SEC
        timeout_min = timeout_sec // 60
        if now - last_touch <= timeout_sec:
            return None, ""
        flags_str = ", ".join(str(f) for f in drift_flags)
        return "block", (
            f"[会话超时] 当前 active run runs/{active_run.name} 的 session_state.json "
            f"漂移信号({flags_str})已持续超过{timeout_min}分钟。"
            f"请写 session_handoff.md 后重启新会话。"
        )
    except Exception:
        return None, ""
    return None, ""


DRIFT_HARD_FLAGS = {"protocol_violation", "option_list"}
DRIFT_BLOCK_THRESHOLD = 2
DRIFT_HANDOFF_THRESHOLD = 4


def _check_drift_session(
    active_run: Path | None = None,
) -> tuple[str | None, str]:
    """Phase 3: check fresh session drift state.

    Low-count drift remains advisory. Repeated protocol/autonomy drift becomes
    a hard gate before the older 30-minute timeout backstop.
    """
    if active_run is None:
        return None, ""
    drift_flags = SessionStateManager.get_drift_flags(active_run)
    if not drift_flags:
        return None, ""
    state = SessionStateManager.load(active_run)
    if not state:
        return None, ""
    # Only notify if session is fresh (updated within timeout window)
    now = time.time()
    updated_at = _valid_ts(state.get("updated_at"), now)
    timeout_sec = SESSION_TIMEOUT_SEC
    if updated_at and now - updated_at > timeout_sec:
        return None, ""  # stale = Phase 2 handles it
    try:
        drift_count = int(state.get("drift_block_count", 1) or 1)
    except Exception:
        drift_count = 1
    flags_str = ", ".join(str(f) for f in drift_flags)
    hard_flags = [f for f in drift_flags if f in DRIFT_HARD_FLAGS]
    if hard_flags and drift_count >= DRIFT_HANDOFF_THRESHOLD:
        return "block", (
            f"[漂移硬拦 Phase 3] 检测到连续 {drift_count} 次协议/自主性漂移({flags_str})。"
            f"请写 session_handoff.md 后重启新会话。"
        )
    if hard_flags and drift_count >= DRIFT_BLOCK_THRESHOLD:
        return "block", (
            f"[漂移硬拦 Phase 3] 检测到连续 {drift_count} 次协议/自主性漂移({flags_str})。"
            f"请 Read CLAUDE.md / WORKFLOW.md / frontier.md, 修正输出为「下一行动:」或「BLOCKED:」后继续。"
        )
    msg = (
        f"[漂移提醒 Phase 3] 检测到漂移信号({flags_str}, x{drift_count})。"
        f"请 Read CLAUDE.md / WORKFLOW.md / frontier.md 完成自检后继续。"
    )
    return "notify", msg


def _check_evidence_severity(run_dir: Path) -> tuple[str | None, str]:
    """Phase 4: 证据严重度闸门 — 结构化字段强制校验。

    要求 Result 段按 Observed / DataObtained / Mechanism / SeverityBasis 四个子字段
    输出, 禁止将推测与事实混在散文段落中。这是 E-013 事件的结构性修复:
    散文格式让推测词("若获得凭据…")隐藏在事实描述中, 无法被词表扫描拦截。

    规则(从硬到软):
    1. Result 段缺少 Observed / DataObtained / Mechanism / SeverityBasis → BLOCK
    2. Observed 含推测词 → BLOCK
    3. DataObtained:none + Severity: HIGH/CRITICAL → BLOCK
    4. SeverityBasis 引用 DataObtained:none → BLOCK

    FAIL-OPEN: 解析失败静默放行。
    """
    evidence_file = run_dir / "evidence.md"
    if not evidence_file.exists():
        return None, ""

    try:
        text = evidence_file.read_text(encoding="utf-8", errors="replace")
    except Exception:
        return None, ""

    REQUIRED_SUBFIELDS = ["Observed", "DataObtained", "Mechanism", "SeverityBasis"]
    SPECULATION_IN_OBSERVED = [
        "若获得凭据", "一旦拿到账号", "若成功利用", "可被利用", "降低攻击成本",
    ]

    warns = []   # 格式建议, 不阻塞
    blocks = []  # 严重度欺诈, 阻塞
    sections = text.split("\n## E-")
    for sec in sections:
        if not sec.strip():
            continue

        eid = sec.strip().split("\n")[0].strip() if sec.strip() else "?"
        if not eid.startswith("E-"):
            eid = "E-?" + eid[:30]

        # 检查是否有 >= 0.8 的 certainty
        has_certainty_08 = False
        for line in sec.split("\n"):
            s = line.strip()
            if s.startswith("- Certainty:") and "0.8" in s:
                has_certainty_08 = True
                break
            if s.startswith("- Certainty:") and ("0.9" in s or "1.0" in s):
                has_certainty_08 = True
                break
        if not has_certainty_08:
            continue  # only check confirmed entries

        # 提取 severity
        sev_line = _extract_field(sec, "Severity")
        sev_upper = sev_line.upper() if sev_line else ""
        is_high_crit = "HIGH" in sev_upper or "CRITICAL" in sev_upper

        # 提取 Result 段完整文本
        result_text = _extract_result_block(sec)
        if not result_text:
            if is_high_crit:
                blocks.append(f"{eid}: Result 段缺失或为空但 Severity={sev_line.strip()} — 无证据不得定 HIGH/CRITICAL")
            continue

        # === 格式检查: 缺少子字段 → 仅对 HIGH/CRITICAL 做关键词兜底检查 ===
        missing_fields = []
        for field in REQUIRED_SUBFIELDS:
            if f"- {field}:" not in result_text:
                missing_fields.append(field)
        if missing_fields:
            # 旧格式条目: 静默跳过(不产生噪音)。若为 HIGH/CRITICAL, 用关键词做兜底检查
            if is_high_crit:
                _check_old_format_severity(eid, result_text, sev_line, blocks)
            continue  # 老格式无法解析子字段, 跳过结构化深度检查

        # 提取子字段值
        observed = _extract_subfield(result_text, "Observed")
        data_obtained = _extract_subfield(result_text, "DataObtained")
        mechanism = _extract_subfield(result_text, "Mechanism")
        severity_basis = _extract_subfield(result_text, "SeverityBasis")

        # === Observed 推测词 → BLOCK (所有 >=0.8 条目) ===
        spec_in_obs = [w for w in SPECULATION_IN_OBSERVED if w in observed]
        if spec_in_obs:
            blocks.append(
                f"{eid}: Observed 含推测词({', '.join(spec_in_obs)})。"
                f"Observed 只能描述事实, 禁止推测。"
            )

        # === 严重度检查 (仅 HIGH/CRITICAL) ===
        if not is_high_crit:
            continue

        # DataObtained:none + HIGH/CRITICAL → BLOCK
        dobj_stripped = data_obtained.strip().lower()
        if dobj_stripped.startswith("none") or dobj_stripped == "none":
            blocks.append(
                f"{eid}: DataObtained=none 但 Severity={sev_line.strip()}。"
                f"零数据 → 最高 MEDIUM。"
            )

        # SeverityBasis 引用 DataObtained:none → BLOCK
        if "dataobtained:none" in severity_basis.lower() or "dataobtained: none" in severity_basis.lower():
            blocks.append(
                f"{eid}: SeverityBasis 引用了 DataObtained:none。"
                f"不得以'没有数据'作为定级依据。"
            )

        # Mechanism:none + HIGH/CRITICAL → BLOCK
        mech_stripped = mechanism.strip().lower()
        if mech_stripped.startswith("none") or mech_stripped == "none":
            blocks.append(
                f"{eid}: Mechanism=none 但 Severity={sev_line.strip()}。"
                f"无利用机制 → 最高 MEDIUM。"
            )

        # CodexReview: HIGH/CRITICAL 条目必须经过 codex 复审
        if "- CodexReview:" not in result_text:
            blocks.append(
                f"{eid}: Severity={sev_line.strip()} 但缺少 CodexReview 字段。"
                f"HIGH/CRITICAL 定级前必须经 codex agent 独立复审。"
                f"请 spawn codex agent 审查本条目, 将输出写入 CodexReview 字段。"
            )

        # CodexCriticalReview: CRITICAL 条目在 NORMAL 模式必须经过暂停前复审
        is_critical = "CRITICAL" in sev_upper
        if is_critical and _is_normal_mode() and "- CodexCriticalReview:" not in result_text:
            blocks.append(
                f"{eid}: Severity=CRITICAL 但缺少 CodexCriticalReview 字段。"
                f"NORMAL 模式暂停 #1 前必须经 codex agent 独立复审 CRITICAL 定级。"
                f"请 spawn fresh-context codex agent 审查本条目, "
                f"将其裁决写入 CodexCriticalReview 字段。"
            )

    # 组装输出: blocks 阻止, warns 仅提示
    if not blocks and not warns:
        return None, ""

    parts = []
    if blocks:
        parts.append("[证据严重度闸门] BLOCK — 以下条目严重度与证据不匹配:\n\n"
                     + "\n".join(f"  • {b}" for b in blocks))
    if warns:
        parts.append("[证据严重度闸门] WARN — 格式建议:\n\n"
                     + "\n".join(f"  • {w}" for w in warns))

    msg = "\n\n".join(parts)
    msg += ("\n\n新格式: - Result:\n"
            "    - Observed: <仅事实>\n"
            "    - DataObtained: <none | N条-TYPE>\n"
            "    - Mechanism: <利用机制 | none>\n"
            "    - SeverityBasis: <从Observed推导>")

    # 有 blocks → block; 只有 warns → 仅提示(不阻塞)
    mode = "block" if blocks else "notify"
    return mode, msg


def _check_replay_quality(run_dir: Path) -> tuple[str | None, str]:
    """Phase 6: 证据回放质量门 — certainty >= 0.8 的条目必须引用真实存在的 .replay.json。

    codex 复审反复发现: driver 用 Python script 确认了行为, 但 probe.py --save 没录 replay。
    导致声称 certainty 0.8 的 confirmed finding 在 codex 审计时无法复核。

    规则: 对每条 certainty >= 0.8 的条目, 检查 Artifacts 字段是否引用了 run 目录下真实存在
    的 .replay.json 文件。缺失的条目 → 持续 block, 要求补 artifact 或降级。

    FAIL-OPEN: 解析失败/evidence.md 不存在静默放行。
    """
    try:
        from evidence_parse import parse_evidence
    except Exception:
        return None, ""

    try:
        recs = parse_evidence(run_dir)
    except Exception:
        return None, ""

    missing = []
    for rec in recs:
        if not (rec.get("confirmed") and str(rec.get("id", "")).startswith("E-")):
            continue
        present_replay = [
            a for a in rec.get("artifacts_present", [])
            if str(a).lower().endswith(".replay.json")
        ]
        if not present_replay:
            missing.append(str(rec.get("id", "E-?")))

    if not missing:
        return None, ""

    msg = (
        "[证据回放质量门] 以下 confirmed 条目缺少 .replay.json 产物:\n\n"
        + "\n".join(f"  • {e}" for e in missing)
        + "\n\n用 probe.py --save 补录 replay, 或在 evidence.md 中将 Certainty 降级到 0.5 "
          "并标注原因(codex BLOCKER: artifact 采集有时序问题)。"
    )
    return "block", msg


def _check_agent_board(run_dir: Path) -> tuple[str | None, str]:
    """Phase 5: Agent Board 强制门 — open fronts >= 4 且 barrier 多样时必须使用 Agent Board。

    如果 frontier.md 中 open fronts >= 4 且 barrier classes 不共享(无 SharedBarrier group),
    则检查 state/assignments.json 或 agents/ 目录是否存在且有内容。
    未检测到 agent 使用 → block; 存在 shared barrier 或 open < 4 → 静默放行。

    FAIL-OPEN: 解析失败静默放行。
    """
    try:
        from anti_drift import _check_agent_board_needed as _ab_needed
    except Exception:
        return None, ""

    try:
        should_remind, open_count, _bg = _ab_needed(run_dir)
    except Exception:
        return None, ""

    if not should_remind:
        return None, ""

    # Check if Agent Board has been used
    agents_dir_path = run_dir / "agents"
    assignments_path = run_dir / "state" / "assignments.json"

    has_agents = agents_dir_path.is_dir() and any(agents_dir_path.glob("A-*.md"))
    has_assignments = False
    if assignments_path.exists():
        try:
            data = json.loads(assignments_path.read_text(encoding="utf-8", errors="replace"))
            has_assignments = isinstance(data.get("assignments"), list) and len(data["assignments"]) > 0
        except Exception:
            pass

    if has_agents or has_assignments:
        return None, ""  # Agent Board used, pass

    return "block", (
        f"open fronts >= 4 且独立(无共享 barrier)，但未使用 Agent Board。"
        f"请用 workers.py assign 分配 >= 2 个 subagent。"
    )


def _extract_field(section: str, field_name: str) -> str:
    """提取 - FieldName: value 行。"""
    for line in section.split("\n"):
        s = line.strip()
        if s.startswith(f"- {field_name}:") or s.startswith(f"{field_name}:"):
            return s
    return ""


def _extract_result_block(section: str) -> str:
    """提取 Result 段到下一个顶级字段(- Xxx:)或下一个 ## 条目。"""
    lines = section.split("\n")
    result_lines = []
    in_result = False
    for line in lines:
        s = line.strip()
        if s.startswith("- Result:") or s.startswith("Result:"):
            in_result = True
            result_lines.append(line)
            continue
        if in_result:
            # 下一个顶级字段 (- Time: / - Source: / - Certainty: / - Severity: / ## E-)
            if any(s.startswith(t) for t in _RESULT_TERMINATORS):
                break
            # 子字段 (- Observed: / - DataObtained: 等) 或续行都收集
            result_lines.append(line)
    return "\n".join(result_lines)


def _check_old_format_severity(eid: str, result_text: str, sev_line: str, blocks: list) -> None:
    """旧格式条目的关键词兜底检查 — 仅对 HIGH/CRITICAL 条目执行。"""
    HARM = ["提取了", "获取了", "返回数据", "绕过了", "bypass", "执行了", "RCE", "shell", "上传了"]
    SPEC = ["若获得", "若拿到", "一旦获得", "则可", "即可", "潜在", "攻击面", "需凭据", "需认证", "需账号"]
    EXPOSURE = ["暴露", "可见", "模板", "端点名称", "端点清单", "标签", "字段名", "页面结构"]

    has_harm = any(w in result_text for w in HARM)
    has_spec = any(w in result_text for w in SPEC)
    only_exposure = any(w in result_text for w in EXPOSURE) and not has_harm

    if has_spec and not has_harm:
        blocks.append(f"{eid} [旧格式]: 含推测词({', '.join(w for w in SPEC if w in result_text)[:60]})且无危害证据 → 降级或补充证明")
    elif only_exposure:
        blocks.append(f"{eid} [旧格式]: 仅结构暴露(页面/端点/标签)但 Severity={sev_line.strip()} → 最高 MEDIUM")


def _extract_subfield(result_block: str, field_name: str) -> str:
    """从 Result 段提取 - FieldName: value。跨行收集直到下一个子字段或结束。"""
    lines = result_block.split("\n")
    value_parts = []
    in_field = False
    prefix = f"- {field_name}:"
    for line in lines:
        s = line.strip()
        if s.startswith(prefix):
            in_field = True
            # 取冒号后的值
            val = s[len(prefix):].strip()
            value_parts.append(val)
            continue
        if in_field:
            # 遇到下一个子字段则停止
            if any(s.strip().startswith(f"- {sf}:") for sf in _SUBFIELDS):
                break
            # 遇到顶级字段则停止
            if any(s.startswith(t) for t in _RESULT_TERMINATORS):
                break
            if s:
                value_parts.append(line)
    return " ".join(value_parts).strip()


def run_check(run_dir: Path) -> tuple[int, str]:
    """subprocess 跑 check_run, 返回 (returncode, 合并输出)。隔离执行, 不耦合内部 API。
    check_run 是纯本地静态解析(无网络), 正常 <1s; 30s 上限足够。超时/异常 → 当作放行
    (rc=0): 提醒器绝不让会话停顿超过 30s, 也绝不因 check_run 故障而卡死(fail-open)。"""
    cmd = [sys.executable, str(ROOT / "tools" / "check_run.py"), str(run_dir)]
    try:
        r = subprocess.run(cmd, capture_output=True, encoding="utf-8",
                           errors="replace", timeout=30)
        return r.returncode, (r.stdout or "") + (r.stderr or "")
    except Exception:
        return 0, ""   # SHOULD-FIX-1: 超时/异常不阻塞会话, 按放行处理


def decide(is_final: bool, check_rc: int, stop_hook_active: bool):
    """纯决策(便于自测): 返回 'block' / 'notify' / None(放行)。
    - 非终版报告 → 放行(还没收尾, 别打扰)。
    - check_run 通过 → 放行。
    - check_run 未过 → 始终 block(强制修复, 不降级)。提醒是无效的——本 run 实测:
      driver 在 stop_hook_active 降级为 notify 后宣布 FINAL, 而 check_run 仍有 4 硬门。
      去掉降级: 修复前永不收口。"""
    if not is_final:
        return None
    if check_rc == 0:
        return None
    return "block"


def _count_open_fronts(run_dir: Path) -> int:
    """Count fronts in frontier.md with Status: open (not probing/blocked_type_b/deferred/closed).
    Returns 0 if frontier.md is missing or unparseable."""
    fr = run_dir / "frontier.md"
    if not fr.exists():
        return 0
    try:
        text = fr.read_text(encoding="utf-8", errors="replace")
    except Exception:
        return 0
    import re as _re_of
    count = 0
    for block in _re_of.split(r"(?=^###\s+F-\d+)", text, flags=_re_of.MULTILINE):
        if not _re_of.match(r"^###\s+F-\d+", block.lstrip()):
            continue
        sm = _re_of.search(r"(?im)^\s*-?\s*Status\s*[:：]\s*(.+)$", block)
        status = sm.group(1).strip().lower() if sm else ""
        if status == "open":
            count += 1
    return count


def build_message(run_dir: Path, check_out: str) -> str:
    tail = check_out.strip()
    if len(tail) > 1600:
        tail = tail[-1600:]
    return ("[收口闸门] 你似乎在收尾 runs/" + run_dir.name + ", 但 check_run 未通过。"
            "收口不是在聊天里宣布'测完了', 而是 run 文件过闸门。先处理下面的硬门再收尾"
            "(覆盖台账缺建→跑 ingest_recon+classify_hosts; 假证据→补真产物或降级; "
            "缺独立复审→派 fresh-context reviewer):\n\n" + tail)


def main() -> None:
    if "--selftest" in sys.argv:
        sys.exit(_selftest())
    # FAIL-OPEN 起手: 读不到/解析不了事件就放行(这是提醒器, 不是安全拦截)。
    try:
        raw = sys.stdin.buffer.read()
        event = json.loads(raw.decode("utf-8", "replace") or "{}")
    except Exception:
        sys.exit(0)
    stop_active = bool(event.get("stop_hook_active"))
    try:
        # ---- Phase 3: drift session check (soft first, hard on repeated protocol drift) ----
        active_run = find_active_run(RUNS)
        # Dev mode: skip Phase 3 notification (drift detection still runs in output_gate)
        if not _is_dev_mode():
            drift_mode, drift_msg = _check_drift_session(active_run)
            if drift_mode is not None:
                if drift_mode == "block":
                    print(json.dumps({"decision": "block", "reason": drift_msg}, ensure_ascii=False))
                    sys.exit(0)
                print(json.dumps({"systemMessage": drift_msg}, ensure_ascii=False))
                # Fall through — allow other checks to run

        # ---- Phase 4 (NEW): evidence severity gate — 防无数据支撑的 HIGH/CRITICAL 定级 ----
        if active_run is not None:
            sev_mode, sev_msg = _check_evidence_severity(active_run)
            if sev_mode is not None:
                if sev_mode == "block":
                    print(json.dumps({"decision": "block", "reason": sev_msg}, ensure_ascii=False))
                    sys.exit(0)
                else:
                    print(json.dumps({"systemMessage": sev_msg}, ensure_ascii=False))
                    # fall through — notify only, don't block further checks

        # ---- Phase 2: session timeout check ----
        timeout_mode, timeout_msg = _check_session_timeout(RUNS, active_run)
        if timeout_mode is not None:
            if timeout_mode == "block":
                print(json.dumps({"decision": "block", "reason": timeout_msg}, ensure_ascii=False))
                sys.exit(0)
            else:
                print(json.dumps({"systemMessage": timeout_msg}, ensure_ascii=False))
                # fall through — don't exit; allow existing gate checks to also run

        # ---- Phase 6 (NEW): 证据回放质量门 — certainty>=0.8 必须引用 .replay.json 产物 ----
        if active_run is not None:
            rq_mode, rq_msg = _check_replay_quality(active_run)
            if rq_mode is not None:
                if rq_mode == "block":
                    print(json.dumps({"decision": "block", "reason": rq_msg}, ensure_ascii=False))
                    sys.exit(0)
                else:
                    print(json.dumps({"systemMessage": rq_msg}, ensure_ascii=False))

        # ---- Phase 5 (NEW): Agent Board 强制门 — open fronts >= 4 且 barrier 多样时禁止全串行 ----
        if active_run is not None:
            ab_mode, ab_msg = _check_agent_board(active_run)
            if ab_mode is not None:
                if ab_mode == "block":
                    print(json.dumps({"decision": "block", "reason": ab_msg}, ensure_ascii=False))
                    sys.exit(0)
                else:
                    print(json.dumps({"systemMessage": ab_msg}, ensure_ascii=False))
                    # fall through

        # ---- Existing closure gate ----
        run_dir = active_run
        if run_dir is None or not report_is_final(run_dir):
            sys.exit(0)
        # NORMAL mode closure: 独立复审 + CodexCompletionReview
        if _is_normal_mode() and not gate_skipped(run_dir):
            try:
                import re as _re
                rv = (run_dir / "review.md").read_text(encoding="utf-8", errors="replace") \
                    if (run_dir / "review.md").exists() else ""
                dc = run_dir / "decisions.md"
                dc_text = dc.read_text(encoding="utf-8", errors="replace") if dc.exists() else ""

                # Check 1: independent review
                if not _re.search(r"Independent Review|独立复审", rv):
                    closure_msg = (
                        "[Normal 收口] report 已终版但缺独立复审。"
                        "请 spawn codex reviewer 完成独立复审 → "
                        "写 retrospective.md → 在 decisions.md 末尾写入 NORMAL_COMPLETE。"
                    )
                    print(json.dumps({"systemMessage": closure_msg}, ensure_ascii=False))
                    sys.exit(0)

                # Check 2: CodexCompletionReview
                if "CodexCompletionReview" not in dc_text:
                    cc_msg = (
                        "[Normal 收口] report 已终版但 decisions.md 缺少 CodexCompletionReview。"
                        "NORMAL 模式暂停 #2 前必须经 codex agent 复审完整 run。"
                        "请 spawn fresh-context codex agent 审查完整 run, "
                        "将其裁决写入 decisions.md 的 CodexCompletionReview 字段。"
                    )
                    print(json.dumps({"decision": "block", "reason": cc_msg}, ensure_ascii=False))
                    sys.exit(0)
            except Exception:
                pass  # FAIL-OPEN: decisions.md / review.md 读失败放行
        if gate_skipped(run_dir):
            sys.exit(0)   # 操作者已认可此 run 不收尾(教学样本/中止) → 不主动提醒
        rc, out = run_check(run_dir)
        # P5: When 0 open fronts remain (all Type B/Closed/Deferred), the driver has
        # genuinely exhausted all attack vectors. Downgrade structural check_run failures
        # (e.g. "coverage empty" without Guanlan recon) from BLOCK to WARN — do not
        # indefinitely block closure when nothing more can be done.
        open_fronts = _count_open_fronts(run_dir)
        if open_fronts == 0 and rc != 0:
            mode = "notify"
            msg = (
                f"[收口闸门 · 无开放前沿] 全部前沿已裁决 (Type B/Closed/Deferred), "
                f"但 check_run 仍有提示。确认已穷尽攻击面后即可收口:\n\n"
            ) + (out.strip()[-1200:] if len(out.strip()) > 1200 else out.strip())
        else:
            mode = decide(True, rc, stop_active)
            if mode is None:
                sys.exit(0)
            msg = build_message(run_dir, out)
        if mode == "block":
            print(json.dumps({"decision": "block", "reason": msg}, ensure_ascii=False))
        else:
            print(json.dumps({"systemMessage": msg}, ensure_ascii=False))
        sys.exit(0)
    except Exception:
        # FAIL-OPEN 兜底: 提醒器自身的任何故障都不得卡死会话。
        sys.exit(0)


def _selftest() -> int:
    import tempfile
    checks: list[tuple[str, bool]] = []
    # decide 真值表
    checks.append(("not final -> pass", decide(False, 1, False) is None))
    checks.append(("final + check pass -> pass", decide(True, 0, False) is None))
    checks.append(("final + check fail -> block", decide(True, 1, False) == "block"))
    checks.append(("final + fail + stop_active -> block (强制, 不降级)", decide(True, 1, True) == "block"))

    d = Path(tempfile.mkdtemp())
    runs = d / "runs"
    runs.mkdir()
    r1 = runs / "a_20260101"
    r1.mkdir()
    (r1 / "report.md").write_text("# Report\n", encoding="utf-8")
    r_norpt = runs / "z_20260101"   # 无 report.md → 还没收尾 → 不该被选
    r_norpt.mkdir()
    (r_norpt / "f.md").write_text("x", encoding="utf-8")
    # find_active_run now delegates to anti_drift: scans all *.md, picks most recent
    time.sleep(1.1)
    (r1 / "touch.md").write_text("fresh", encoding="utf-8")  # make r1 more recent than r_norpt
    checks.append(("find_active_run picks most-recent run with *.md", find_active_run(runs, within_sec=900) == r1))
    checks.append(("find_active_run picks runs even without report.md", find_active_run(runs, within_sec=900) is not None))
    checks.append(("stale run -> none", find_active_run(runs, within_sec=-1) is None))
    checks.append(("no runs dir -> none", find_active_run(d / "nope") is None))

    # report_is_final via check_run import (终版 vs 存根)
    if _cr is not None:
        rd = runs / "b_20260101"
        rd.mkdir()
        (rd / "ev.html").write_text("x" * 10, encoding="utf-8")
        (rd / "evidence.md").write_text(
            "# Evidence Ledger\n## E-001\n- Replicated: y\n- Artifacts: `ev.html`\n- Certainty: 1.0\n",
            encoding="utf-8")
        (rd / "report.md").write_text("# Report\nEvidence IDs: E-001\n", encoding="utf-8")
        rd2 = runs / "c_20260101"
        rd2.mkdir()
        (rd2 / "report.md").write_text("# Report\nEvidence IDs:\n", encoding="utf-8")
        checks.append(("report_is_final TRUE on confirmed report", report_is_final(rd) is True))
        checks.append(("report_is_final FALSE on stub", report_is_final(rd2) is False))
        rd3 = runs / "d_20260101"
        rd3.mkdir()
        (rd3 / "report.md").write_text(
            "# Report\nEvidence IDs: E-001\n<!-- run-gate: skip (teaching sample) -->\n", encoding="utf-8")
        checks.append(("gate_skipped TRUE on skip marker", gate_skipped(rd3) is True))
        checks.append(("gate_skipped FALSE without marker", gate_skipped(rd) is False))
    else:
        print("[selftest] WARN: check_run not importable; skipped report_is_final checks", file=sys.stderr)

    # Phase 2: session timeout detection
    sdir = runs / "session_test"
    sdir.mkdir()
    # no session_state.json -> pass
    mode_none, _ = _check_session_timeout(runs)
    checks.append(("session timeout: no file -> pass", mode_none is None))
    # fresh session_state.json with drift -> pass (within timeout window)
    (sdir / "session_state.json").write_text(
        json.dumps({"drift_flags": ["protocol_violation"], "updated_at": time.time()}), encoding="utf-8")
    mode_fresh, _ = _check_session_timeout(runs)
    checks.append(("session timeout: fresh file -> pass", mode_fresh is None))
    # stale session_state.json with empty drift_flags -> pass
    old_time = time.time() - SESSION_TIMEOUT_SEC - 60
    os.utime(str(sdir / "session_state.json"), (old_time, old_time))
    (sdir / "session_state.json").write_text(
        json.dumps({"drift_flags": [], "updated_at": old_time}), encoding="utf-8")
    mode_empty, _ = _check_session_timeout(runs)
    checks.append(("session timeout: stale but no drift -> pass", mode_empty is None))
    # stale session_state.json with non-empty drift_flags -> block (new API: needs active_run)
    (sdir / "session_state.json").write_text(
        json.dumps({"drift_flags": ["frontier_stale"], "updated_at": old_time}), encoding="utf-8")
    os.utime(str(sdir / "session_state.json"), (old_time, old_time))
    mode_block, msg_block = _check_session_timeout(runs, active_run=sdir)
    checks.append(("session timeout: stale + drift -> block", mode_block == "block"))
    checks.append(("session timeout: message mentions run", "session_test" in msg_block))
    # corrupt session_state.json -> pass (fail-open)
    (sdir / "session_state.json").write_text("not json{{{", encoding="utf-8")
    os.utime(str(sdir / "session_state.json"), (old_time, old_time))
    mode_corrupt, _ = _check_session_timeout(runs)
    checks.append(("session timeout: corrupt file -> pass", mode_corrupt is None))
    # drift_flags is not a list -> pass
    (sdir / "session_state.json").write_text(
        json.dumps({"drift_flags": "not_a_list", "updated_at": old_time}), encoding="utf-8")
    os.utime(str(sdir / "session_state.json"), (old_time, old_time))
    mode_badtype, _ = _check_session_timeout(runs)
    checks.append(("session timeout: drift_flags not list -> pass", mode_badtype is None))
    # Phase 2 uses a longer candidate window than ordinary active-run gates.
    timeout_runs = d / "timeout_runs"
    timeout_runs.mkdir()
    timeout_candidate = timeout_runs / "timeout_candidate"
    timeout_candidate.mkdir()
    old_timeout_touch = time.time() - SESSION_TIMEOUT_SEC - 60
    (timeout_candidate / "frontier.md").write_text("# Frontier\n", encoding="utf-8")
    (timeout_candidate / "session_state.json").write_text(
        json.dumps({"drift_flags": ["protocol_violation"],
                    "drift_started_at": old_timeout_touch,
                    "updated_at": old_timeout_touch}), encoding="utf-8")
    os.utime(str(timeout_candidate / "frontier.md"), (old_timeout_touch, old_timeout_touch))
    os.utime(str(timeout_candidate / "session_state.json"), (old_timeout_touch, old_timeout_touch))
    mode_long_window, _ = _check_session_timeout(timeout_runs)
    checks.append(("session timeout: >15m drift candidate still blocks", mode_long_window == "block"))

    # Phase 3: drift session check (notify first, then hard block repeated protocol drift)
    import tempfile as _tempfile_mod
    test_ds_dir = Path(_tempfile_mod.mkdtemp())
    # No active_run → pass
    d3_mode_none, _ = _check_drift_session(active_run=None)
    checks.append(("drift session: no active_run -> pass", d3_mode_none is None))
    # Active run with no session_state.json → pass
    ds_run = test_ds_dir / "ds_run"
    ds_run.mkdir()
    d3_mode_nostate, _ = _check_drift_session(active_run=ds_run)
    checks.append(("drift session: no session_state -> pass", d3_mode_nostate is None))
    # Fresh session_state with drift_flags → notify
    (ds_run / "session_state.json").write_text(
        json.dumps({"drift_flags": ["protocol_violation"], "drift_block_count": 1,
                     "updated_at": time.time()}), encoding="utf-8")
    d3_mode_notify, d3_msg = _check_drift_session(active_run=ds_run)
    checks.append(("drift session: drift flags -> notify", d3_mode_notify == "notify"))
    checks.append(("drift session: message mentions drift", "漂移提醒" in (d3_msg or "")))
    # Repeated protocol/autonomy drift -> hard block
    (ds_run / "session_state.json").write_text(
        json.dumps({"drift_flags": ["protocol_violation"], "drift_block_count": 2,
                    "updated_at": time.time()}), encoding="utf-8")
    d3_mode_block, d3_msg_block = _check_drift_session(active_run=ds_run)
    checks.append(("drift session: protocol count 2 -> block", d3_mode_block == "block"))
    checks.append(("drift session: block asks reread", "Read CLAUDE.md" in (d3_msg_block or "")))
    (ds_run / "session_state.json").write_text(
        json.dumps({"drift_flags": ["option_list"], "drift_block_count": 4,
                    "updated_at": time.time()}), encoding="utf-8")
    d3_mode_handoff, d3_msg_handoff = _check_drift_session(active_run=ds_run)
    checks.append(("drift session: option count 4 -> block", d3_mode_handoff == "block"))
    checks.append(("drift session: handoff message", "session_handoff.md" in (d3_msg_handoff or "")))
    (ds_run / "session_state.json").write_text(
        json.dumps({"drift_flags": ["frontier_stale"], "drift_block_count": 4,
                    "updated_at": time.time()}), encoding="utf-8")
    d3_mode_frontier, _ = _check_drift_session(active_run=ds_run)
    checks.append(("drift session: frontier-only count 4 stays notify", d3_mode_frontier == "notify"))
    # Stale session_state with drift_flags → pass (Phase 2 handles stale)
    old_drift = time.time() - SESSION_TIMEOUT_SEC - 120
    (ds_run / "session_state.json").write_text(
        json.dumps({"drift_flags": ["frontier_stale"], "drift_block_count": 1,
                     "updated_at": old_drift}), encoding="utf-8")
    os.utime(str(ds_run / "session_state.json"), (old_drift, old_drift))
    d3_mode_stale, _ = _check_drift_session(active_run=ds_run)
    checks.append(("drift session: stale drift -> pass", d3_mode_stale is None))
    # Empty drift_flags → pass
    (ds_run / "session_state.json").write_text(
        json.dumps({"drift_flags": [], "updated_at": time.time()}), encoding="utf-8")
    d3_mode_empty, _ = _check_drift_session(active_run=ds_run)
    checks.append(("drift session: empty flags -> pass", d3_mode_empty is None))

    # Phase 2: session timeout with active_run binding + updated_at
    sdir2 = Path(_tempfile_mod.mkdtemp())
    # No active_run → pass
    mode_none2, _ = _check_session_timeout(sdir2)
    checks.append(("session timeout: no active_run -> pass", mode_none2 is None))
    # Stale session_state on non-active run → not checked (only checks active_run)
    stale_run = sdir2 / "stale_run"
    stale_run.mkdir()
    old2 = time.time() - SESSION_TIMEOUT_SEC - 120
    (stale_run / "session_state.json").write_text(
        json.dumps({"drift_flags": ["protocol_violation"], "updated_at": old2}), encoding="utf-8")
    os.utime(str(stale_run / "session_state.json"), (old2, old2))
    mode_stale_inactive, _ = _check_session_timeout(sdir2, active_run=stale_run)
    checks.append(("session timeout: stale active -> block", mode_stale_inactive == "block"))
    # updated_at fresh but file mtime stale → pass (anti_drift touched JSON)
    half_stale = sdir2 / "half_stale"
    half_stale.mkdir()
    sf_path = half_stale / "session_state.json"
    sf_path.write_text(
        json.dumps({"drift_flags": ["protocol_violation"], "updated_at": time.time()}), encoding="utf-8")
    old_mtime = time.time() - SESSION_TIMEOUT_SEC - 120
    os.utime(str(sf_path), (old_mtime, old_mtime))
    mode_fresh_json, _ = _check_session_timeout(sdir2, active_run=half_stale)
    checks.append(("session timeout: fresh updated_at + stale mtime -> pass", mode_fresh_json is None))
    # Both stale → block
    both_stale = sdir2 / "both_stale"
    both_stale.mkdir()
    sf2 = both_stale / "session_state.json"
    sf2.write_text(
        json.dumps({"drift_flags": ["protocol_violation"], "updated_at": old2}), encoding="utf-8")
    os.utime(str(sf2), (old2, old2))
    mode_both, _ = _check_session_timeout(sdir2, active_run=both_stale)
    checks.append(("session timeout: both stale -> block", mode_both == "block"))
    # Fresh file writes from output_gate must not erase an old unresolved drift streak.
    old_started = time.time() - SESSION_TIMEOUT_SEC - 120
    fresh_file_old_drift = sdir2 / "fresh_file_old_drift"
    fresh_file_old_drift.mkdir()
    (fresh_file_old_drift / "session_state.json").write_text(
        json.dumps({"drift_flags": ["protocol_violation"],
                    "drift_started_at": old_started,
                    "updated_at": time.time()}), encoding="utf-8")
    mode_old_drift, msg_old_drift = _check_session_timeout(sdir2, active_run=fresh_file_old_drift)
    checks.append(("session timeout: old drift_started_at despite fresh file -> block", mode_old_drift == "block"))
    checks.append(("session timeout: old drift message mentions 持续", "持续" in (msg_old_drift or "")))

    # SPECULATION_IN_OBSERVED precision tests (Decision 4)
    import tempfile as _tm_spec
    spec_dir = Path(_tm_spec.mkdtemp())
    # True positive: "若获得凭据" in Observed → should block
    (spec_dir / "evidence.md").write_text("""# Evidence
## E-001
- Certainty: 0.8
- Severity: HIGH
- Result:
    - Observed: 若获得凭据即可访问管理后台
    - DataObtained: 1条-页面响应
    - Mechanism: 凭证填充攻击
    - SeverityBasis: 若获得凭据可导致未授权访问
    - CodexReview: confirmed HIGH
""", encoding="utf-8")
    sev_spec1, sev_spec_msg1 = _check_evidence_severity(spec_dir)
    checks.append(("spec word: 若获得凭据 detected", sev_spec1 == "block"))
    checks.append(("spec word: block mentions Observed 含推测词", "Observed 含推测词" in (sev_spec_msg1 or "")))
    # False positive: "若服务器返回200" in Observed → should NOT block (not in spec list)
    spec_dir2 = Path(_tm_spec.mkdtemp())
    (spec_dir2 / "evidence.md").write_text("""# Evidence
## E-001
- Certainty: 0.8
- Severity: HIGH
- Result:
    - Observed: 若服务器返回200状态码且响应体含admin字段
    - DataObtained: 2条-HTTP响应
    - Mechanism: 路径枚举发现管理端点
    - SeverityBasis: 未授权访问管理界面
    - CodexReview: confirmed HIGH
""", encoding="utf-8")
    sev_spec2, _ = _check_evidence_severity(spec_dir2)
    checks.append(("spec word: 若服务器返回200 NOT blocked", sev_spec2 is None))
    # False positive: "若" alone in Observed → should NOT block (removed from list)
    spec_dir3 = Path(_tm_spec.mkdtemp())
    (spec_dir3 / "evidence.md").write_text("""# Evidence
## E-001
- Certainty: 0.8
- Severity: HIGH
- Result:
    - Observed: 若输入特殊字符服务器返回错误页面
    - DataObtained: 1条-错误页面HTML
    - Mechanism: 反射型XSS
    - SeverityBasis: 未过滤用户输入导致脚本执行
    - CodexReview: confirmed HIGH
""", encoding="utf-8")
    sev_spec3, _ = _check_evidence_severity(spec_dir3)
    checks.append(("spec word: 若 alone NOT blocked", sev_spec3 is None))

    # Phase 6: replay quality gate requires a real replay artifact in Artifacts:
    import tempfile as _tm_replay
    replay_missing = Path(_tm_replay.mkdtemp())
    (replay_missing / "evidence.md").write_text("""# Evidence
## E-001
- Certainty: 0.8
- Artifacts: proof.html
""", encoding="utf-8")
    rq_missing, rq_missing_msg = _check_replay_quality(replay_missing)
    checks.append(("replay quality: confirmed without replay -> block", rq_missing == "block"))
    checks.append(("replay quality: message names E-001", "E-001" in (rq_missing_msg or "")))

    replay_ok = Path(_tm_replay.mkdtemp())
    (replay_ok / "proof.html.replay.json").write_text("{}", encoding="utf-8")
    (replay_ok / "evidence.md").write_text("""# Evidence
## E-001
- Certainty: 0.8
- Artifacts: proof.html.replay.json
""", encoding="utf-8")
    rq_ok, _ = _check_replay_quality(replay_ok)
    checks.append(("replay quality: existing replay artifact -> pass", rq_ok is None))

    replay_prose = Path(_tm_replay.mkdtemp())
    (replay_prose / "proof.html").write_text("x", encoding="utf-8")
    (replay_prose / "evidence.md").write_text("""# Evidence
## E-001
- Certainty: 0.8
- Artifacts: proof.html
- Note: should add proof.html.replay.json later
""", encoding="utf-8")
    rq_prose, _ = _check_replay_quality(replay_prose)
    checks.append(("replay quality: prose mention is not enough", rq_prose == "block"))

    replay_missing_file = Path(_tm_replay.mkdtemp())
    (replay_missing_file / "evidence.md").write_text("""# Evidence
## E-001
- Certainty: 0.8
- Artifacts: proof.html.replay.json
""", encoding="utf-8")
    rq_missing_file, _ = _check_replay_quality(replay_missing_file)
    checks.append(("replay quality: missing replay file -> block", rq_missing_file == "block"))

    replay_low_cert = Path(_tm_replay.mkdtemp())
    (replay_low_cert / "evidence.md").write_text("""# Evidence
## E-001
- Certainty: 0.5
- Artifacts: proof.html
""", encoding="utf-8")
    rq_low_cert, _ = _check_replay_quality(replay_low_cert)
    checks.append(("replay quality: low certainty without replay -> pass", rq_low_cert is None))

    # Phase 4: CodexCriticalReview — NORMAL 模式 CRITICAL 定级必须经暂停前复审
    _orig_normal_mode = globals().get("_is_normal_mode")
    # Temporarily force NORMAL mode for these tests
    globals()["_is_normal_mode"] = lambda: True
    try:
        import tempfile as _tm4
        # Test 1: CRITICAL with CodexReview but missing CodexCriticalReview → block
        ev1 = Path(_tm4.mkdtemp())
        (ev1 / "evidence.md").write_text("""# Evidence
## E-001
- Certainty: 0.8
- Severity: CRITICAL
- Result:
    - Observed: 未授权访问数据库
    - DataObtained: 5条-用户表记录
    - Mechanism: SQL注入绕过认证
    - SeverityBasis: 获取了数据库内容可导致数据泄露
    - CodexReview: confirmed CRITICAL
""", encoding="utf-8")
        sev_mode1, sev_msg1 = _check_evidence_severity(ev1)
        checks.append(("CodexCriticalReview: CRITICAL missing field -> block", sev_mode1 == "block"))
        checks.append(("CodexCriticalReview: block message mentions field", "CodexCriticalReview" in (sev_msg1 or "")))

        # Test 2: CRITICAL with both CodexReview and CodexCriticalReview → pass
        ev2 = Path(_tm4.mkdtemp())
        (ev2 / "evidence.md").write_text("""# Evidence
## E-001
- Certainty: 0.8
- Severity: CRITICAL
- Result:
    - Observed: 未授权访问数据库
    - DataObtained: 5条-用户表记录
    - Mechanism: SQL注入绕过认证
    - SeverityBasis: 获取了数据库内容可导致数据泄露
    - CodexReview: confirmed CRITICAL
    - CodexCriticalReview: confirmed CRITICAL for pause gate
""", encoding="utf-8")
        sev_mode2, sev_msg2 = _check_evidence_severity(ev2)
        checks.append(("CodexCriticalReview: CRITICAL with field -> pass", sev_mode2 is None))

        # Test 3: HIGH with CodexReview, no CodexCriticalReview needed → pass
        ev3 = Path(_tm4.mkdtemp())
        (ev3 / "evidence.md").write_text("""# Evidence
## E-001
- Certainty: 0.8
- Severity: HIGH
- Result:
    - Observed: 反射型XSS
    - DataObtained: 1条-弹窗回显
    - Mechanism: 未过滤用户输入
    - SeverityBasis: 可执行脚本导致会话劫持
    - CodexReview: confirmed HIGH
""", encoding="utf-8")
        sev_mode3, _ = _check_evidence_severity(ev3)
        checks.append(("CodexCriticalReview: HIGH without field -> pass", sev_mode3 is None))

        # Test 4: CRITICAL without certainty 0.8 → not checked (below gate threshold)
        ev4 = Path(_tm4.mkdtemp())
        (ev4 / "evidence.md").write_text("""# Evidence
## E-001
- Certainty: 0.5
- Severity: CRITICAL
- Result:
    - Observed: 可能的注入点
    - DataObtained: none
    - Mechanism: none
    - SeverityBasis: 推测
""", encoding="utf-8")
        sev_mode4, _ = _check_evidence_severity(ev4)
        checks.append(("CodexCriticalReview: <0.8 certainty -> not checked", sev_mode4 is None))
    finally:
        if _orig_normal_mode is not None:
            globals()["_is_normal_mode"] = _orig_normal_mode
        else:
            globals().pop("_is_normal_mode", None)

    # NORMAL mode closure: CodexCompletionReview in decisions.md
    globals()["_is_normal_mode"] = lambda: True
    try:
        ev5 = Path(_tm4.mkdtemp())
        (ev5 / "report.md").write_text("# Report\nEvidence IDs: E-001\n", encoding="utf-8")
        (ev5 / "evidence.md").write_text("""# Evidence
## E-001
- Certainty: 0.8
- Severity: HIGH
- Result:
    - Observed: XSS
    - DataObtained: 1条-alert
    - Mechanism: 反射型XSS
    - SeverityBasis: 脚本执行
    - CodexReview: confirmed HIGH
""", encoding="utf-8")
        # decisions.md 缺 CodexCompletionReview → 应阻断
        (ev5 / "decisions.md").write_text("# Decisions\n- chose F-001 first\n", encoding="utf-8")
        dc_text = (ev5 / "decisions.md").read_text(encoding="utf-8", errors="replace")
        checks.append(("CodexCompletionReview: missing -> detected",
                       "CodexCompletionReview" not in dc_text))

        # decisions.md 含 CodexCompletionReview → 应放行
        (ev5 / "decisions.md").write_text(
            "# Decisions\n- chose F-001 first\n- CodexCompletionReview: confirmed complete\n",
            encoding="utf-8")
        dc_text2 = (ev5 / "decisions.md").read_text(encoding="utf-8", errors="replace")
        checks.append(("CodexCompletionReview: present -> detected",
                       "CodexCompletionReview" in dc_text2))
    finally:
        globals().pop("_is_normal_mode", None)

    # Phase 5: Agent Board 强制门 selftest
    import tempfile as _tm_ab
    ab_test = Path(_tm_ab.mkdtemp())

    # Case 1: no frontier.md -> pass (silent)
    ab_run1 = ab_test / "no_frontier"
    ab_run1.mkdir()
    mode1, _ = _check_agent_board(ab_run1)
    checks.append(("agent board gate: no frontier.md -> pass", mode1 is None))

    # Case 2: < 4 open fronts (probing not counted) -> pass
    ab_run2 = ab_test / "few_fronts"
    ab_run2.mkdir()
    (ab_run2 / "frontier.md").write_text(
        "# Frontier\n## Open\n"
        "### F-001\n- Status: open\n- Barrier class: none\n\n"
        "### F-002\n- Status: open\n- Barrier class: none\n\n"
        "### F-003\n- Status: probing\n- Barrier class: WAF\n",
        encoding="utf-8")
    mode2, _ = _check_agent_board(ab_run2)
    checks.append(("agent board gate: <4 open fronts (probing excluded) -> pass", mode2 is None))

    # Case 3: >= 4 open fronts with shared barrier -> pass
    ab_run3 = ab_test / "shared_barrier"
    ab_run3.mkdir()
    (ab_run3 / "frontier.md").write_text(
        "# Frontier\n## Open\n"
        "### F-001\n- Status: open\n- Barrier class: WAF-rate-limit\n\n"
        "### F-002\n- Status: open\n- Barrier class: WAF-rate-limit\n\n"
        "### F-003\n- Status: open\n- Barrier class: WAF-rate-limit\n\n"
        "### F-004\n- Status: probing\n- Barrier class: WAF-rate-limit\n",
        encoding="utf-8")
    mode3, _ = _check_agent_board(ab_run3)
    checks.append(("agent board gate: shared barrier -> pass", mode3 is None))

    # Case 4: >= 4 open fronts diverse, no agents -> block
    ab_run4 = ab_test / "diverse_no_agents"
    ab_run4.mkdir()
    (ab_run4 / "frontier.md").write_text(
        "# Frontier\n## Open\n"
        "### F-001\n- Status: open\n- Barrier class: SQL-injection\n\n"
        "### F-002\n- Status: open\n- Barrier class: XSS-filter\n\n"
        "### F-003\n- Status: open\n- Barrier class: auth-bypass\n\n"
        "### F-004\n- Status: open\n- Barrier class: file-upload\n",
        encoding="utf-8")
    mode4, msg4 = _check_agent_board(ab_run4)
    checks.append(("agent board gate: diverse no agents -> block", mode4 == "block"))
    checks.append(("agent board gate: block message readable", "Agent Board" in (msg4 or "")))

    # Case 5: >= 4 open fronts diverse, has agents/ dir -> pass
    ab_run5 = ab_test / "diverse_with_agents"
    ab_run5.mkdir()
    (ab_run5 / "frontier.md").write_text(
        "# Frontier\n## Open\n"
        "### F-001\n- Status: open\n- Barrier class: SQL-injection\n\n"
        "### F-002\n- Status: open\n- Barrier class: XSS-filter\n\n"
        "### F-003\n- Status: open\n- Barrier class: auth-bypass\n\n"
        "### F-004\n- Status: open\n- Barrier class: file-upload\n",
        encoding="utf-8")
    (ab_run5 / "agents").mkdir()
    (ab_run5 / "agents" / "A-web-hunter-001.md").write_text("# Agent\n", encoding="utf-8")
    mode5, _ = _check_agent_board(ab_run5)
    checks.append(("agent board gate: diverse with agents -> pass", mode5 is None))

    # Case 6: >= 4 open fronts diverse, has assignments.json -> pass
    ab_run6 = ab_test / "diverse_with_assignments"
    ab_run6.mkdir()
    (ab_run6 / "frontier.md").write_text(
        "# Frontier\n## Open\n"
        "### F-001\n- Status: open\n- Barrier class: SQL-injection\n\n"
        "### F-002\n- Status: open\n- Barrier class: XSS-filter\n\n"
        "### F-003\n- Status: open\n- Barrier class: auth-bypass\n\n"
        "### F-004\n- Status: open\n- Barrier class: file-upload\n",
        encoding="utf-8")
    (ab_run6 / "state").mkdir(parents=True)
    (ab_run6 / "state" / "assignments.json").write_text(
        json.dumps({"schema": 1, "assignments": [{"agent": "A-web-hunter-001", "status": "assigned"}]}),
        encoding="utf-8")
    mode6, _ = _check_agent_board(ab_run6)
    checks.append(("agent board gate: diverse with assignments.json -> pass", mode6 is None))

    bad = [n for n, ok in checks if not ok]
    # 输出到 stderr(与 safety_gate 一致): SessionStart 接线时不刷 context, 手动跑仍可见。
    for n, ok in checks:
        print(("ok   " if ok else "FAIL ") + n, file=sys.stderr)
    print("run_gate selftest " + ("passed" if not bad else f"FAILED ({len(bad)})"), file=sys.stderr)
    return 0 if not bad else 1


if __name__ == "__main__":
    main()
