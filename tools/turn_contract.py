#!/usr/bin/env python3
"""Claude Code turn-mode and PreToolUse contract for active Xunji runs.

The user's current prompt decides whether this turn executes, explains, or pauses.
Stop hooks consume the same state, so an explanation is not forced to fabricate a
Coda and a pause is not mistaken for closure.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shlex
import sys
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
RUNS = Path(os.environ.get("XUNJI_RUNS_ROOT", str(ROOT / "runs")))
sys.path.insert(0, str(ROOT / "tools"))

import run_model  # noqa: E402
import runtime_receipts  # noqa: E402
from anti_drift import find_active_run  # noqa: E402


SCHEMA = "xunji.turn_contract.v1"
EXECUTE = "EXECUTE"
EXPLAIN = "EXPLAIN_ONLY"
PAUSE = "PAUSED_BY_OPERATOR"
NORMAL = "NORMAL"
STALE_SECONDS = 6 * 60 * 60
COMPLETION_CHECKS = (
    "report_parity", "severity_artifacts", "reachable_frontier", "review_ledger",
)
CONTROL_SCRIPTS = {
    (ROOT / "tools" / name).resolve()
    for name in ("workers.py", "run_model.py", "loop_state.py")
}

EXPLAIN_RE = re.compile(
    r"告诉我(?:原因|为什么|想法)|为什么|不用修改|不要修改|无需修改|别修改|"
    r"不用做|不要做|先别做|只(?:告诉|回答|分析|解释|说明)|无需执行|"
    r"tell me why|explain only|do not (?:change|modify|act)|no changes",
    re.I,
)
PAUSE_RE = re.compile(
    r"停止\s*(?:loop|循环|渗透|运行)|渗透结束|暂停\s*(?:loop|循环|渗透|运行)|"
    r"先停(?:止|下)|stop\s+(?:the\s+)?(?:loop|run|testing)|pause\s+(?:the\s+)?(?:loop|run)",
    re.I,
)
EXECUTE_RE = re.compile(
    r"(?:^|\s)/loop\b|继续(?:执行|推进|修复|运行|渗透)?|恢复(?:执行|运行|loop)?|"
    r"修复|实现|落实|执行|修改|彻底解决|开始(?:运行|渗透)|"
    r"resume|continue|implement|fix|execute|apply",
    re.I,
)
MEMORY_APPROVAL_RE = re.compile(r"(?:明确|现在)?(?:写入|保存|更新)(?:长期)?记忆|approve memory|write (?:to )?memory", re.I)
INTERNAL_PROMPT_RE = re.compile(
    r"^\s*<(?:task-notification|system-reminder|local-command-caveat)\b",
    re.I,
)
MEMORY_PATH_RE = re.compile(
    r"(?:^|[/\\\s\"'=])\.claude(?:[/\\].*)?[/\\](?:memory|memories)(?:[/\\]|$)|"
    r"(?:^|[/\\\s\"'=])MEMORY\.md(?=[\"'\s;|&}]|$)",
    re.I,
)
BACKGROUND_REVIEW_RE = re.compile(
    r"(?s)(?:\bnohup\b.*?peer_review\.py|peer_review\.py.*?(?<![>&])&(?![>&]))",
    re.I,
)
PROTECTED_RUNTIME_RE = re.compile(
    r"(?:runtime_events\.jsonl|\.runtime_events\.lock|turn_contract\.json|run_status\.json|"
    r"assignments\.json|review[/\\]receipts[/\\][0-9a-f]{64}\.json)"
    r"(?=[\"'\s;|&}]|$)",
    re.I,
)


def _atomic_json(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, raw = tempfile.mkstemp(prefix=path.name + ".", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(value, handle, ensure_ascii=False, indent=2, sort_keys=True)
            handle.write("\n")
        os.chmod(raw, 0o600)
        os.replace(raw, path)
    finally:
        try:
            os.unlink(raw)
        except FileNotFoundError:
            pass


def contract_path(run_dir: Path) -> Path:
    return run_dir / "state" / "turn_contract.json"


def run_status_path(run_dir: Path) -> Path:
    return run_dir / "state" / "run_status.json"


def classify_prompt(prompt: str, *, active_run: bool = True) -> str:
    prompt = prompt or ""
    if not active_run:
        return NORMAL
    if PAUSE_RE.search(prompt):
        return PAUSE
    if EXPLAIN_RE.search(prompt):
        return EXPLAIN
    if EXECUTE_RE.search(prompt):
        return EXECUTE
    if re.search(r"[?？]\s*$", prompt) or re.match(r"^\s*(?:怎么|如何|是否|什么|哪|谁)", prompt):
        return EXPLAIN
    return EXPLAIN


def write_contract(run_dir: Path, event: dict) -> dict:
    prompt = str(event.get("prompt") or "")
    mode = classify_prompt(prompt, active_run=True)
    now = time.time()
    contract = {
        "schema": SCHEMA,
        "mode": mode,
        "session_id": str(event.get("session_id") or ""),
        "transcript_path": str(event.get("transcript_path") or ""),
        "prompt_sha256": hashlib.sha256(prompt.encode("utf-8", "replace")).hexdigest(),
        "prompt_excerpt": prompt[:500],
        "memory_approved": bool(MEMORY_APPROVAL_RE.search(prompt)),
        "fanout_override": bool(re.search(r"(?:明确)?允许串行|不要使用\s*(?:Agent|子代理)|serial override", prompt, re.I)),
        "updated_at": now,
    }
    _atomic_json(contract_path(run_dir), contract)
    if mode == PAUSE:
        _atomic_json(run_status_path(run_dir), {
            "schema": SCHEMA,
            "status": "paused_by_operator",
            "session_id": contract["session_id"],
            "updated_at": now,
            "reason": "operator prompt requested pause; open fronts remain open",
        })
    elif mode == EXECUTE:
        _atomic_json(run_status_path(run_dir), {
            "schema": SCHEMA,
            "status": "active",
            "session_id": contract["session_id"],
            "updated_at": now,
            "reason": "operator prompt requested execution/resume",
        })
    return contract


def load_contract(run_dir: Path, *, session_id: str = "") -> dict:
    try:
        data = json.loads(contract_path(run_dir).read_text(encoding="utf-8", errors="replace"))
    except Exception:
        return {}
    if data.get("schema") != SCHEMA:
        return {}
    if session_id and str(data.get("session_id") or "") != session_id:
        return {}
    try:
        if time.time() - float(data.get("updated_at") or 0) > STALE_SECONDS:
            return {}
    except Exception:
        return {}
    return data


def _tool_text(event: dict) -> str:
    value = event.get("tool_input") if isinstance(event.get("tool_input"), dict) else {}
    try:
        return json.dumps(value, ensure_ascii=False, sort_keys=True)
    except Exception:
        return str(value)


def _deny(reason: str) -> dict:
    return {
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": "deny",
            "permissionDecisionReason": reason,
        }
    }


def _safe_sed(tokens: list[str]) -> bool:
    scripts: list[str] = []
    index = 1
    while index < len(tokens):
        token = tokens[index]
        if token in {"-n", "--quiet", "--silent"}:
            index += 1
            continue
        if token in {"-e", "--expression"}:
            if index + 1 >= len(tokens):
                return False
            scripts.append(tokens[index + 1])
            index += 2
            continue
        if token.startswith("-"):
            return False
        if not scripts:
            scripts.append(token)
        index += 1
    return bool(scripts) and all(
        re.fullmatch(r"(?:\d+|\$)(?:,(?:\d+|\$))?p", script)
        for script in scripts
    )


def _readonly_shell(command: str) -> bool:
    """Allow a narrow shell read grammar; unknown syntax remains write-capable."""
    if not command.strip() or re.search(r">|`|\$\(|\$\{|\n|\r", command):
        return False
    allowed = {"cat", "head", "tail", "grep", "rg", "ls", "stat", "file", "wc", "find", "sed"}
    for segment in re.split(r"\s*(?:&&|\|\||;|\|)\s*", command):
        if not segment.strip():
            return False
        try:
            tokens = shlex.split(segment)
        except ValueError:
            return False
        if not tokens:
            return False
        executable = Path(tokens[0]).name
        if executable not in allowed:
            return False
        if executable == "sed" and not _safe_sed(tokens):
            return False
        if executable == "find" and any(
            token in {
                "-delete", "-exec", "-execdir", "-ok", "-okdir",
                "-fprint", "-fprint0", "-fls", "-fprintf",
            }
            for token in tokens[1:]
        ):
            return False
    return True


def _fanout_control_bash(command: str) -> bool:
    if _readonly_shell(command):
        return True
    if re.search(r"[;&|><`]|\$\(|\$\{|\n|\r", command):
        return False
    try:
        tokens = shlex.split(command)
    except ValueError:
        return False
    if len(tokens) < 2 or not re.fullmatch(
        r"python(?:3(?:\.\d+)?)?", Path(tokens[0]).name
    ):
        return False
    script = Path(tokens[1])
    if not script.is_absolute():
        script = ROOT / script
    return script.resolve() in CONTROL_SCRIPTS


def _assignment_exists(run_dir: Path, assignment: str, front: str) -> bool:
    try:
        data = json.loads((run_dir / "state" / "assignments.json").read_text(encoding="utf-8", errors="replace"))
    except Exception:
        return False
    for item in data.get("assignments", []) if isinstance(data, dict) else []:
        if not isinstance(item, dict):
            continue
        if str(item.get("agent") or "") == assignment and str(item.get("front") or "").upper() == front:
            return (run_dir / "agents" / f"{assignment}.md").exists()
    return False


def _is_target_action(event: dict) -> bool:
    tool = str(event.get("tool_name") or "")
    tool_input = event.get("tool_input") if isinstance(event.get("tool_input"), dict) else {}
    command = str(tool_input.get("command") or "")
    return tool == "WebFetch" or (tool == "Bash" and not _fanout_control_bash(command))


def _denial_is_target_action(event: dict, reason: str) -> bool:
    """Separate target-result denials from local control-plane policy denials."""
    local_policy_markers = (
        "运行时回执/回合状态只能由 hook 原子写入",
        "长期记忆写入需要操作者",
        "peer_review 不得后台运行",
    )
    return _is_target_action(event) and not any(
        marker in reason for marker in local_policy_markers)


def evaluate_pretool(run_dir: Path, event: dict, contract: dict) -> str:
    tool = str(event.get("tool_name") or "")
    text = _tool_text(event)
    mode = str(contract.get("mode") or "")
    tool_input = event.get("tool_input") if isinstance(event.get("tool_input"), dict) else {}
    command = str(tool_input.get("command") or "")

    if PROTECTED_RUNTIME_RE.search(text) and (
        tool in {"Write", "Edit", "Update", "MultiEdit", "NotebookEdit"} or tool == "Bash"
    ):
        return "运行时回执/回合状态只能由 hook 原子写入；Claude 工具不得直接修改这些控制面文件。"

    if MEMORY_PATH_RE.search(text) and not contract.get("memory_approved"):
        memory_read = tool in {"Read", "Grep", "Glob"} or (
            tool == "Bash" and _readonly_shell(command)
        )
        if not memory_read:
            return "长期记忆写入需要操作者在当前 prompt 明确批准；retrospective 不能自行升级为 memory。"
    if tool == "Bash" and BACKGROUND_REVIEW_RE.search(command):
        return "peer_review 不得后台运行并与可变 evidence 并发；请前台冻结快照后完成复审。"

    if mode == EXPLAIN:
        if tool not in {"Read", "Grep", "Glob", "WebSearch", "ListMcpResourcesTool", "ReadMcpResourceTool"}:
            return "当前回合是 EXPLAIN_ONLY：只能读取/分析，禁止修改、探测、Agent、Cron 或执行命令。"
        return ""
    if mode == PAUSE:
        if tool not in {"Read", "Grep", "Glob", "CronList", "CronDelete"}:
            return "当前回合是 PAUSED_BY_OPERATOR：只允许读取状态并执行 CronList/CronDelete；不得继续目标动作或改写前沿。"
        if tool == "CronDelete":
            job = runtime_receipts._job_id(tool_input)
            ok, note = runtime_receipts.cron_delete_allowed(
                run_dir, job,
                session_id=str(contract.get("session_id") or ""),
                since=float(contract.get("updated_at") or 0.0),
            )
            if not ok:
                return "暂停事务只可删除当前 CronList 观察到的本 run job：" + note
        return ""
    if not contract:
        if tool not in {"Read", "Grep", "Glob", "WebSearch", "CronList", "CronDelete"}:
            return "缺少当前 session 的 turn contract；先由 UserPromptSubmit 记录 EXECUTE/EXPLAIN/PAUSE 模式。"
        return ""

    if tool == "CronCreate":
        cron_ok, cron_note = runtime_receipts.cron_quiescent(
            run_dir,
            session_id=str(contract.get("session_id") or ""),
            since=float(contract.get("updated_at") or 0.0),
        )
        if not cron_ok:
            return "Cron 单实例门：创建 /loop 前必须先 CronList 证明本 run 无现存任务。" + cron_note
        if run_dir.name.lower() not in text.lower():
            return "Cron 单实例门：CronCreate prompt 必须显式包含当前 run 目录名。"
        return ""

    if tool == "CronDelete":
        job = runtime_receipts._job_id(tool_input)
        ok, note = runtime_receipts.cron_delete_allowed(
            run_dir, job,
            session_id=str(contract.get("session_id") or ""),
            since=float(contract.get("updated_at") or 0.0),
        )
        if not ok:
            return "CronDelete 只可删除当前 CronList 观察到的本 run job：" + note
        return ""

    state = run_model.summary(run_dir)
    frontier_exists = (run_dir / "frontier.md").exists()
    state_invalid = not frontier_exists or (
        not state.get("fronts") or bool(state.get("schema_errors"))
    )
    if state_invalid and (
        tool == "WebFetch" or (tool == "Bash" and not _fanout_control_bash(command))
    ):
        return (
            "canonical frontier 状态缺失或有 schema error；active run 按 fail-closed "
            "禁止目标动作，先修复 frontier.md 的 Status/Barrier class/Current depth。"
        )
    if not state.get("fanout_required") or contract.get("fanout_override"):
        return ""
    if tool == "Agent":
        raw_input = event.get("tool_input") if isinstance(event.get("tool_input"), dict) else {}
        prompt = str(raw_input.get("prompt") or raw_input.get("description") or "")
        if "XUNJI_COMPLETION_REVIEW" in prompt.upper():
            missing = [item for item in COMPLETION_CHECKS if item not in prompt.lower()]
            if not runtime_receipts._evidence_hash(prompt) or missing:
                return (
                    "Completion Agent prompt 必须包含 EVIDENCE_INDEX=<current sha1> 和 "
                    "CHECKS=report_parity,severity_artifacts,reachable_frontier,review_ledger；缺少: "
                    + ", ".join(missing or ["EVIDENCE_INDEX"]))
            return ""
        assignment, front = runtime_receipts._assignment_fields(prompt)
        if not assignment or not front:
            return "Agent Board 强制：Agent prompt 必须包含 XUNJI_ASSIGNMENT=A-... 和 XUNJI_FRONT=F-...。"
        if not _assignment_exists(run_dir, assignment, front):
            return "Agent Board 强制：Agent token 未绑定 workers.py 生成的 assignment/front。"
        return ""
    fanout = runtime_receipts.agent_fanout(
        run_dir,
        session_id=str(contract.get("session_id") or ""),
        since=float(contract.get("updated_at") or 0.0),
    )
    if fanout.get("satisfied"):
        if tool == "Bash" and _fanout_control_bash(command):
            return ""
        if tool == "WebFetch" or tool == "Bash":
            disposition = runtime_receipts.agent_disposition(
                run_dir,
                session_id=str(contract.get("session_id") or ""),
                since=float(contract.get("updated_at") or 0.0),
            )
            if not disposition.get("disposition_satisfied"):
                return (
                    "Agent receipt 已返回但尚未完成 post-return disposition；先用 workers.py "
                    "把每个 assignment 更新为带 canonical E/F/D 锚点的 merged/blocked/failed，"
                    "且更新时间必须晚于 Agent 返回。"
                )
        return ""
    if tool == "Bash":
        if not _fanout_control_bash(command):
            return (
                "Agent Board 强制：当前至少 4 个独立 active fronts"
                "（open/probing/working/type-A）；真实 Agent 回执覆盖两个不同 front 前，"
                "Root Bash 只允许只读命令和 workers/run_model/loop_state 控制面命令。"
            )
    if tool in {"WebFetch"}:
        return "Agent Board 强制：真实 Agent 回执覆盖两个不同 front 前，Root 不得继续目标 WebFetch。"
    return ""


def _context_message(contract: dict, run_dir: Path) -> str:
    mode = contract.get("mode")
    if mode == EXPLAIN:
        return "[Xunji turn mode: EXPLAIN_ONLY] 只回答操作者问题；可读文件，不修改、不探测、不派 Agent；本回合无需 Coda。"
    if mode == PAUSE:
        return "[Xunji turn mode: PAUSED_BY_OPERATOR] 保留所有 open fronts；先 CronList/CronDelete，禁止继续渗透；本回合无需 Coda，也不得写 completion marker。"
    state = run_model.summary(run_dir)
    fanout = (
        " fanout_required=true (open/probing/working/type-A 均为 active); "
        "先真实调用至少两个不同 front 的 Agent。"
        if state.get("fanout_required") else ""
    )
    return "[Xunji turn mode: EXECUTE] 按 run 状态推进，最后写唯一具体 Coda。" + fanout


def handle_event(event: dict, run_dir: Path | None = None) -> dict | None:
    run_dir = run_dir or find_active_run(RUNS, within_sec=6 * 60 * 60)
    if run_dir is None:
        if str(event.get("hook_event_name") or "") == "PreToolUse" \
                and str(event.get("tool_name") or "") == "CronCreate":
            return _deny("Xunji CronCreate 前必须先 setup/set-active 一个 run，再用当前回合 CronList 证明单实例。")
        return None
    hook = str(event.get("hook_event_name") or "")
    if hook == "UserPromptSubmit":
        prompt = str(event.get("prompt") or "")
        if INTERNAL_PROMPT_RE.search(prompt):
            contract = load_contract(
                run_dir, session_id=str(event.get("session_id") or ""))
            if not contract:
                return None
            return {
                "hookSpecificOutput": {
                    "hookEventName": "UserPromptSubmit",
                    "additionalContext": _context_message(contract, run_dir),
                }
            }
        contract = write_contract(run_dir, event)
        return {
            "hookSpecificOutput": {
                "hookEventName": "UserPromptSubmit",
                "additionalContext": _context_message(contract, run_dir),
            }
        }
    if hook == "PreToolUse":
        contract = load_contract(run_dir, session_id=str(event.get("session_id") or ""))
        reason = evaluate_pretool(run_dir, event, contract)
        if reason:
            receipt_event = dict(event)
            receipt_event.update({
                "hook_event_name": "PreToolUseDenied",
                "xunji_decision": "deny",
                "xunji_reason": reason,
                "xunji_target_action": _denial_is_target_action(event, reason),
            })
            runtime_receipts.append_hook_event(run_dir, receipt_event)
            return _deny(reason)
        return None
    if hook in {"PostToolUse", "PostToolUseFailure", "SubagentStart", "SubagentStop"}:
        tool_name = str(event.get("tool_name") or "")
        command = str((event.get("tool_input") or {}).get("command") or "") \
            if isinstance(event.get("tool_input"), dict) else ""
        target_action = _is_target_action(event)
        if hook in {"SubagentStart", "SubagentStop"} or tool_name in {
            "Agent", "CronCreate", "CronDelete", "CronList",
        } or (tool_name == "Bash" and "peer_review.py" in command) or target_action:
            receipt_event = dict(event)
            receipt_event["xunji_target_action"] = target_action
            runtime_receipts.append_hook_event(run_dir, receipt_event)
        return None
    return None


def _selftest() -> int:
    import subprocess

    root = Path(tempfile.mkdtemp())
    run = root / "run"
    (run / "state").mkdir(parents=True)
    (run / "agents").mkdir()
    (run / "frontier.md").write_text(
        "# Frontier\n## Open Fronts\n" + "".join(
            f"### F-{idx:03d}\n- Status: open\n- Barrier class: {barrier}\n- Current depth: shallow\n"
            for idx, barrier in enumerate(("app", "auth", "network", "none"), 1)
        ), encoding="utf-8")
    (run / "agents" / "A-web-001.md").write_text("# Agent\n", encoding="utf-8")
    (run / "agents" / "A-auth-001.md").write_text("# Agent\n", encoding="utf-8")
    (run / "state" / "assignments.json").write_text(json.dumps({"assignments": [
        {"agent": "A-web-001", "front": "F-001"},
        {"agent": "A-auth-001", "front": "F-002"},
    ]}), encoding="utf-8")
    explain = classify_prompt("为什么不用 Agent？只告诉我原因，不用修改")
    history_only = classify_prompt("这是这几次的历史，你来看看还有什么问题")
    ambiguous = classify_prompt("这是最新状态")
    pause = classify_prompt("停止loop，渗透结束")
    execute = classify_prompt("彻底修复所有问题")
    indirect_english = classify_prompt("Please deploy the prepared workflow")
    contract = {"mode": EXECUTE, "session_id": "s", "updated_at": time.time()}
    target_event = {"tool_name": "Bash", "tool_input": {"command": "python tools/probe.py https://example.test"}}
    encoded_target = {"tool_name": "Bash", "tool_input": {
        "command": "python3 -c 'import socket; socket.create_connection((\"example.test\",443))'"}}
    renamed_target = {"tool_name": "Bash", "tool_input": {"command": "python3 /tmp/check.py"}}
    workers_control = {"tool_name": "Bash", "tool_input": {
        "command": f"python3 {ROOT / 'tools' / 'workers.py'} list {run}"}}
    fake_workers_control = {"tool_name": "Bash", "tool_input": {
        "command": "python3 /tmp/workers.py list runs/x"}}
    safe_sed_read = {"tool_name": "Bash", "tool_input": {
        "command": "sed -n '1,10p' frontier.md"}}
    sed_in_place = {"tool_name": "Bash", "tool_input": {
        "command": "sed -n -i '1,10p' frontier.md"}}
    sed_write_command = {"tool_name": "Bash", "tool_input": {
        "command": "sed -n 'w /tmp/forged' frontier.md"}}
    find_file_output = {"tool_name": "Bash", "tool_input": {
        "command": "find . -type f -fprint /tmp/forged"}}
    agent_bad = {"tool_name": "Agent", "tool_input": {"prompt": "work F-001"}}
    agent_good = {"tool_name": "Agent", "tool_input": {
        "prompt": "XUNJI_ASSIGNMENT=A-web-001 XUNJI_FRONT=F-001",
    }}
    completion_bad = {"tool_name": "Agent", "tool_input": {
        "prompt": "XUNJI_COMPLETION_REVIEW EVIDENCE_INDEX=" + "a" * 40,
    }}
    completion_good = {"tool_name": "Agent", "tool_input": {
        "prompt": "XUNJI_COMPLETION_REVIEW EVIDENCE_INDEX=" + "a" * 40
                  + " CHECKS=report_parity,severity_artifacts,reachable_frontier,review_ledger",
    }}
    before_fanout = "真实 Agent 回执" in evaluate_pretool(run, target_event, contract)
    encoded_before_fanout = bool(evaluate_pretool(run, encoded_target, contract))
    renamed_before_fanout = bool(evaluate_pretool(run, renamed_target, contract))
    workers_allowed_before_fanout = not bool(evaluate_pretool(run, workers_control, contract))
    fake_workers_blocked_before_fanout = bool(evaluate_pretool(
        run, fake_workers_control, contract))
    safe_sed_allowed_before_fanout = not bool(evaluate_pretool(
        run, safe_sed_read, contract))
    sed_in_place_blocked = bool(evaluate_pretool(run, sed_in_place, contract))
    sed_write_blocked = bool(evaluate_pretool(run, sed_write_command, contract))
    find_file_output_blocked = bool(evaluate_pretool(run, find_file_output, contract))
    protected_write = {
        "tool_name": "Bash",
        "tool_input": {"command": "printf forged > state/runtime_events.jsonl"},
    }
    protected_reason = evaluate_pretool(run, protected_write, contract)
    protected_denial_not_target = not _denial_is_target_action(
        protected_write, protected_reason)
    transcript = root / "transcript.jsonl"
    transcript.write_text("old-agent-1\nold-agent-2\ncurrent-agent-1\ncurrent-agent-2\ncurrent-cron-list\n",
                          encoding="utf-8")

    def receipt(tool_id: str, session: str, assignment: str, front: str) -> None:
        runtime_receipts.append_hook_event(run, {
            "hook_event_name": "PostToolUse", "session_id": session,
            "transcript_path": str(transcript), "tool_name": "Agent",
            "tool_use_id": tool_id,
            "tool_input": {"prompt": f"XUNJI_ASSIGNMENT={assignment} XUNJI_FRONT={front}"},
            "tool_response": {"result": "done"},
        })

    receipt("old-agent-1", "old-session", "A-web-001", "F-001")
    receipt("old-agent-2", "old-session", "A-auth-001", "F-002")
    old_fanout_still_blocked = bool(evaluate_pretool(run, target_event, contract))
    receipt("current-agent-1", "s", "A-web-001", "F-001")
    receipt("current-agent-2", "s", "A-auth-001", "F-002")
    receipts_without_disposition_block = bool(evaluate_pretool(run, target_event, contract))
    (run / "evidence.md").write_text("# Evidence\n## E-001 - merged candidate\n", encoding="utf-8")
    assignment_state = json.loads((run / "state" / "assignments.json").read_text(encoding="utf-8"))
    for item in assignment_state["assignments"]:
        item.update({
            "status": "merged",
            "updated_at": datetime.now(timezone.utc).isoformat(),
            "last_note": f"Evidence: E-001 merged for Front: {item['front']}",
        })
    (run / "state" / "assignments.json").write_text(
        json.dumps(assignment_state), encoding="utf-8")
    current_fanout_allows = evaluate_pretool(run, target_event, contract) == ""
    missing_contract_blocks = bool(evaluate_pretool(run, target_event, {}))
    original_frontier = (run / "frontier.md").read_text(encoding="utf-8")
    (run / "frontier.md").write_text("# Frontier\n## Open Fronts\nmalformed\n", encoding="utf-8")
    malformed_frontier_blocks = "canonical frontier" in evaluate_pretool(
        run, target_event, contract)
    (run / "frontier.md").write_text(original_frontier, encoding="utf-8")
    (run / "frontier.md").unlink()
    missing_frontier_blocks = "canonical frontier" in evaluate_pretool(
        run, target_event, contract)
    (run / "frontier.md").write_text(original_frontier, encoding="utf-8")
    cron_create = {"tool_name": "CronCreate", "tool_input": {"prompt": f"/loop {run.name}"}}
    cron_before_list = bool(evaluate_pretool(run, cron_create, contract))
    runtime_receipts.append_hook_event(run, {
        "hook_event_name": "PostToolUse", "session_id": "s",
        "transcript_path": str(transcript), "tool_name": "CronList",
        "tool_use_id": "current-cron-list", "tool_input": {},
        "tool_response": {"tasks": []},
    })
    cron_after_list = evaluate_pretool(run, cron_create, contract) == ""
    empty_runs = root / "empty-runs"
    empty_runs.mkdir()
    env = dict(os.environ)
    env["XUNJI_RUNS_ROOT"] = str(empty_runs)
    no_run_cron = subprocess.run(
        [sys.executable, str(Path(__file__).resolve())],
        input=json.dumps({
            "hook_event_name": "PreToolUse", "session_id": "s",
            "tool_name": "CronCreate", "tool_input": {"prompt": "/loop future-run"},
        }),
        text=True, capture_output=True, env=env, timeout=10,
    )
    settings = json.loads((ROOT / ".claude" / "settings.json").read_text(encoding="utf-8"))
    hooks = settings.get("hooks", {})

    state_path = contract_path(run)
    state_path.write_text("{broken", encoding="utf-8")
    malformed_contract_rejected = load_contract(run, session_id="s") == {}
    _atomic_json(state_path, {
        "schema": "wrong", "mode": EXECUTE, "session_id": "s",
        "updated_at": time.time(),
    })
    wrong_schema_rejected = load_contract(run, session_id="s") == {}
    _atomic_json(state_path, {
        "schema": SCHEMA, "mode": EXECUTE, "session_id": "other",
        "updated_at": time.time(),
    })
    wrong_session_rejected = load_contract(run, session_id="s") == {}
    _atomic_json(state_path, {
        "schema": SCHEMA, "mode": EXECUTE, "session_id": "s",
        "updated_at": time.time() - STALE_SECONDS - 1,
    })
    stale_contract_rejected = load_contract(run, session_id="s") == {}
    override = write_contract(run, {
        "prompt": "继续执行，明确允许串行", "session_id": "s",
        "transcript_path": str(transcript),
    })
    operator_contract_raw = state_path.read_text(encoding="utf-8")
    operator_contract = json.loads(operator_contract_raw)
    internal_response = handle_event({
        "hook_event_name": "UserPromptSubmit",
        "session_id": "s",
        "prompt": "<task-notification><status>completed</status></task-notification>",
    }, run)
    internal_notification_preserves_contract = (
        state_path.read_text(encoding="utf-8") == operator_contract_raw
        and load_contract(run, session_id="s") == operator_contract
        and isinstance(internal_response, dict)
    )

    def wired(event_name: str) -> bool:
        return any(
            "tools/turn_contract.py" in str(hook.get("command") or "")
            for group in hooks.get(event_name, []) if isinstance(group, dict)
            for hook in group.get("hooks", []) if isinstance(hook, dict)
        )

    session_start_selftest = any(
        "tools/turn_contract.py" in str(hook.get("command") or "")
        and "--selftest" in str(hook.get("command") or "")
        for group in hooks.get("SessionStart", []) if isinstance(group, dict)
        for hook in group.get("hooks", []) if isinstance(hook, dict)
    )
    pretool_groups = hooks.get("PreToolUse", [])
    global_pretool_first = bool(
        pretool_groups
        and isinstance(pretool_groups[0], dict)
        and not pretool_groups[0].get("matcher")
        and any(
            "tools/turn_contract.py" in str(hook.get("command") or "")
            for hook in pretool_groups[0].get("hooks", []) if isinstance(hook, dict)
        )
    )
    checks = [
        ("explain overrides action words", explain == EXPLAIN),
        ("history/audit prompt without execute verb is read-only", history_only == EXPLAIN),
        ("ambiguous active-run prompt defaults read-only", ambiguous == EXPLAIN),
        ("operator stop maps to pause", pause == PAUSE),
        ("repair request maps to execute", execute == EXECUTE),
        ("unrecognized English execution wording defaults read-only", indirect_english == EXPLAIN),
        ("target action blocked before real fanout", before_fanout),
        ("encoded network command blocked before fanout", encoded_before_fanout),
        ("renamed unknown script blocked before fanout", renamed_before_fanout),
        ("workers control command allowed before fanout", workers_allowed_before_fanout),
        ("out-of-tree workers.py cannot impersonate control plane",
         fake_workers_blocked_before_fanout),
        ("narrow sed print remains read-only before fanout", safe_sed_allowed_before_fanout),
        ("sed in-place mutation blocked before fanout", sed_in_place_blocked),
        ("sed write command blocked before fanout", sed_write_blocked),
        ("find file-output action blocked before fanout", find_file_output_blocked),
        ("protected control-plane denial is not a target-result action",
         protected_denial_not_target),
        ("old-session Agent receipts do not satisfy this turn", old_fanout_still_blocked),
        ("receipts without post-return disposition remain blocked",
         receipts_without_disposition_block),
        ("current receipts plus anchored disposition unlock target action",
         current_fanout_allows),
        ("missing contract blocks target action", missing_contract_blocks),
        ("malformed frontier blocks target action", malformed_frontier_blocks),
        ("missing frontier blocks target action", missing_frontier_blocks),
        ("malformed contract is rejected", malformed_contract_rejected),
        ("wrong contract schema is rejected", wrong_schema_rejected),
        ("cross-session contract reuse is rejected", wrong_session_rejected),
        ("stale contract is rejected", stale_contract_rejected),
        ("serial override requires current operator prompt", override.get("fanout_override") is True),
        ("internal task notification cannot replace operator turn contract",
         internal_notification_preserves_contract),
        ("Agent without binding tokens blocked", "必须包含" in evaluate_pretool(run, agent_bad, contract)),
        ("bound Agent call allowed", evaluate_pretool(run, agent_good, contract) == ""),
        ("completion Agent without full checklist is blocked",
         bool(evaluate_pretool(run, completion_bad, contract))),
        ("completion Agent with evidence hash and checklist is allowed",
         evaluate_pretool(run, completion_good, contract) == ""),
        ("explain mode blocks Bash", bool(evaluate_pretool(run, target_event, {"mode": EXPLAIN}))),
        ("pause mode allows CronList", evaluate_pretool(run, {"tool_name": "CronList", "tool_input": {}}, {"mode": PAUSE}) == ""),
        ("CronCreate requires current-turn CronList", cron_before_list),
        ("CronCreate allowed after current-turn empty CronList", cron_after_list),
        ("CronCreate without an active run is blocked",
         '"permissionDecision": "deny"' in (no_run_cron.stdout or "")),
        ("settings wires UserPromptSubmit contract", wired("UserPromptSubmit")),
        ("settings wires global PreToolUse contract", wired("PreToolUse")),
        ("settings runs turn contract selftest at SessionStart", session_start_selftest),
        ("global turn contract PreToolUse hook is first", global_pretool_first),
        ("settings wires Agent/Cron PostToolUse receipts", wired("PostToolUse")),
        ("settings wires failed tool receipts", wired("PostToolUseFailure")),
        ("settings wires Subagent lifecycle receipts",
         wired("SubagentStart") and wired("SubagentStop")),
        ("CronDelete rejects job not listed for this run", bool(evaluate_pretool(
            run, {"tool_name": "CronDelete", "tool_input": {"id": "otherjob"}}, contract))),
        ("memory write needs explicit approval", bool(evaluate_pretool(
            run, {"tool_name": "Write", "tool_input": {"file_path": "/tmp/.claude/x/memory/MEMORY.md"}},
            {"mode": EXECUTE}))),
        ("relative Bash memory path needs explicit approval", bool(evaluate_pretool(
            run, {"tool_name": "Bash", "tool_input": {
                "command": "mkdir -p .claude/x/memory && printf x > .claude/x/memory/MEMORY.md"}},
            contract))),
        ("read-only Bash memory access remains allowed", not bool(evaluate_pretool(
            run, {"tool_name": "Bash", "tool_input": {
                "command": "ls -la .claude/x/memory && cat .claude/x/memory/MEMORY.md"}},
            contract))),
        ("direct memory Read remains allowed", not bool(evaluate_pretool(
            run, {"tool_name": "Read", "tool_input": {
                "file_path": "/tmp/.claude/x/memory/MEMORY.md"}}, contract))),
        ("background review is blocked", bool(evaluate_pretool(
            run, {"tool_name": "Bash", "tool_input": {
                "command": "python tools/peer_review.py runs/x > /tmp/review.log 2>&1 & echo started"}},
            contract))),
        ("foreground review redirection is allowed", not bool(evaluate_pretool(
            run, {"tool_name": "Bash", "tool_input": {
                "command": "python tools/peer_review.py runs/x > /tmp/review.log 2>&1"}},
            contract))),
        ("protected runtime receipt cannot be edited", bool(evaluate_pretool(
            run, {"tool_name": "Write", "tool_input": {"file_path": str(run / "state" / "runtime_events.jsonl")}},
            contract))),
        ("protected runtime receipt remains readable", not bool(evaluate_pretool(
            run, {"tool_name": "Read", "tool_input": {"file_path": str(run / "state" / "runtime_events.jsonl")}},
            contract))),
    ]
    bad = [name for name, ok in checks if not ok]
    for name, ok in checks:
        print(("ok   " if ok else "FAIL ") + name)
    print("turn_contract selftest " + ("passed" if not bad else f"FAILED ({len(bad)})"))
    return 0 if not bad else 1


def main() -> int:
    parser = argparse.ArgumentParser(description="Xunji Claude Code turn contract hook")
    parser.add_argument("--selftest", action="store_true")
    args = parser.parse_args()
    if args.selftest:
        return _selftest()
    try:
        event = json.loads(sys.stdin.buffer.read().decode("utf-8", "replace") or "{}")
    except Exception:
        return 0
    try:
        result = handle_event(event)
        if result:
            print(json.dumps(result, ensure_ascii=False))
    except Exception as exc:
        if str(event.get("hook_event_name") or "") == "PreToolUse":
            run_dir = find_active_run(RUNS, within_sec=6 * 60 * 60)
            if run_dir is not None:
                print(json.dumps(_deny(
                    "Xunji PreToolUse contract 内部异常，active run 按 fail-closed 阻断："
                    + type(exc).__name__), ensure_ascii=False))
        return 0
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
