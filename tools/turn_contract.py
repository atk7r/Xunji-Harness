#!/usr/bin/env python3
"""Claude Code turn-mode and PreToolUse contract for active Xunji runs.

The user's current prompt decides whether this turn executes, explains, or pauses.
Stop hooks consume the same state, so an explanation is not forced to fabricate a
Coda and a pause is not mistaken for closure.
"""
from __future__ import annotations

import argparse
import hashlib
import ipaddress
import json
import os
import re
import shlex
import sys
import tempfile
import time
from urllib.parse import urlsplit
from datetime import datetime, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
RUNS = Path(os.environ.get("XUNJI_RUNS_ROOT", str(ROOT / "runs")))
ACTIVE_RUN_POINTER = Path(os.environ.get(
    "XUNJI_ACTIVE_RUN_FILE", str(ROOT / ".claude" / "xunji_active_run")))
PENDING_DIR = Path(os.environ.get(
    "XUNJI_PENDING_TURN_DIR", str(ROOT / ".claude" / "xunji_pending_turns")))
TRANSITION_CLAIMS_DIR = Path(os.environ.get(
    "XUNJI_TRANSITION_CLAIMS_DIR",
    str(ROOT / ".claude" / "xunji_transition_claims")))
SESSION_SELECTION_DIR = Path(os.environ.get(
    "XUNJI_SESSION_SELECTION_DIR",
    str(ROOT / ".claude" / "xunji_session_selections")))
sys.path.insert(0, str(ROOT / "tools"))

import run_model  # noqa: E402
import runtime_receipts  # noqa: E402
import scope_admission  # noqa: E402
import setup_normalizer  # noqa: E402
import setup_source  # noqa: E402
import setup_transaction  # noqa: E402
import work_plan  # noqa: E402
import agent_settlement  # noqa: E402
import agent_instruction_bundle  # noqa: E402
from evidence_parse import current_evidence_index_hash  # noqa: E402
from harness import capability_registry  # noqa: E402
from harness.command_shape import (  # noqa: E402
    PythonControlInvocation,
    PythonControlShapeIssue,
    diagnose_python_control_shape,
    has_unquoted_shell_control as _has_unquoted_shell_control,
    local_setup_metadata_invocation,
    normalize_local_setup_command,
    parse_exact_python_command,
    split_literal_and_chain,
    trusted_python_token,
)
from harness import maintenance_authority, privacy  # noqa: E402


SCHEMA = "xunji.turn_contract.v1"
EXECUTE = "EXECUTE"
EXPLAIN = "EXPLAIN_ONLY"
PAUSE = "PAUSED_BY_OPERATOR"
MAINTENANCE = "MAINTENANCE"
NORMAL = "NORMAL"
STALE_SECONDS = 6 * 60 * 60
PENDING_STALE_SECONDS = 15 * 60
SESSION_END_REASONS = frozenset({
    "clear", "resume", "logout", "prompt_input_exit",
    "bypass_permissions_disabled", "other",
})
SESSION_START_SOURCES = frozenset({"startup", "resume", "clear", "compact"})
AUTHORITY_SESSION_ENDED = "session_ended"
AUTHORITY_RESUME_BARRIER = "resume_barrier"
COMPLETION_CHECKS = runtime_receipts.GLOBAL_COMPLETION_CHECKS
CONTROL_SCRIPTS = set(capability_registry.registered_scripts(
    root=ROOT, effects={"local_read", "control"},
))
LIFECYCLE_SCRIPTS = {
    (ROOT / "tools" / "loop_bootstrap.py").resolve(),
    (ROOT / "tools" / "setup_run.py").resolve(),
    (ROOT / "tools" / "xunji_statusline.py").resolve(),
}
LOCAL_VERIFICATION_SCRIPTS = set(capability_registry.registered_scripts(
    root=ROOT, effects={"local_verify"},
))
TRUSTED_TARGET_ENV_KEYS = set(capability_registry.TARGET_ENV)
PROXY_AWARE_TARGET_TOOLS = set(capability_registry.registered_scripts(
    root=ROOT, effects={"target"},
))
REGISTERED_CAPABILITY_SCRIPTS = set(
    capability_registry.registered_scripts(root=ROOT)
)
RAW_NETWORK_CLIENT_RE = re.compile(
    r"(?i)(?:^|[\s;&|])(curl|wget|httpx|nuclei|sqlmap)(?:\s|$)|"
    r"\b(?:requests\.(?:get|post|request)|urllib\.request|socket\.(?:socket|create_connection))\b"
)
DIRECT_EGRESS_ENV_RE = re.compile(
    r"(?i)\bXUNJI_PROXY_REQUIRED\s*=\s*(?:0|false|no|off)\b"
)
DIRECT_EGRESS_APPROVAL_RE = re.compile(
    r"(?:明确)?(?:允许|接受|批准|同意).{0,24}(?:直连|direct[ -]?egress)|"
    r"(?:allow|approve|accept).{0,24}direct[ -]?egress",
    re.I,
)
DIRECT_EGRESS_DENIAL_RE = re.compile(
    r"(?:不|不要|不得|禁止|拒绝).{0,16}(?:允许|接受|批准|同意|直连)|"
    r"(?:do\s+not|don't|never|deny|forbid).{0,24}"
    r"(?:allow|approve|accept|direct[ -]?egress)",
    re.I,
)
ALL_NETWORK_DENIAL_RE = re.compile(
    r"(?:禁止|不要|不得|不允许|无需).{0,24}"
    r"(?:任何|所有|一切)?\s*(?:网络请求|网络访问|联网|出站)|"
    r"(?:完全|仅)?\s*离线(?:测试|运行|执行)?|"
    r"(?:do\s+not|don't|must\s+not|no)\s+(?:make\s+|send\s+|use\s+)?"
    r"(?:any\s+|all\s+)?(?:network\s+(?:requests?|access)|egress)|"
    r"(?:offline[- ]only|run\s+offline)",
    re.I,
)
TARGET_EGRESS_DENIAL_RE = re.compile(
    r"(?:禁止|不要|不得|不允许|无需).{0,32}"
    r"(?:向|对)?\s*(?:目标).{0,16}(?:网络|请求|访问|出站|探测|扫描)|"
    r"(?:禁止|不要|不得|不允许|无需).{0,24}(?:探测|扫描)|"
    r"(?:do\s+not|don't|must\s+not|no)\s+(?:send\s+|make\s+|perform\s+)?"
    r"(?:target\s+)?(?:network\s+requests?|target\s+(?:egress|requests?|probing|scanning)|"
    r"probes?|scans?)",
    re.I,
)
WEB_TOOL_DENIAL_RE = re.compile(
    r"(?:禁止|不要|不得|不允许|无需).{0,32}(?:WebFetch|WebSearch|浏览器)|"
    r"(?:do\s+not|don't|must\s+not|no)\s+(?:use\s+)?"
    r"(?:WebFetch|WebSearch|(?:the\s+)?browser|web\s+(?:fetch|search))",
    re.I,
)
NON_EGRESS_TOOLS = {
    "Agent", "AskUserQuestion", "CronCreate", "CronDelete", "CronList",
    "Edit", "Glob", "Grep", "ListMcpResourcesTool", "MultiEdit", "NotebookEdit",
    "Read", "ReadMcpResourceTool", "ScheduleWakeup", "Skill", "TaskCreate",
    "TaskOutput", "TaskStop", "TaskUpdate", "TodoWrite",
    "WebSearch", "Write",
}

E_NEW_RUN_SETUP_REQUIRED = "XUNJI_E_NEW_RUN_SETUP_REQUIRED"
E_LIFECYCLE_EXACT_ARGV_REQUIRED = "XUNJI_E_LIFECYCLE_EXACT_ARGV_REQUIRED"
E_RUN_TRANSITION_AUTHORITY_MISSING = "XUNJI_E_RUN_TRANSITION_AUTHORITY_MISSING"
E_CLEAR_ACTIVE_FORBIDDEN = "XUNJI_E_CLEAR_ACTIVE_FORBIDDEN"
E_CRON_LIST_REQUIRED = "XUNJI_E_CRON_LIST_REQUIRED"
E_CRON_RUN_MISMATCH = "XUNJI_E_CRON_RUN_MISMATCH"
E_CRON_CREATE_REQUIRED = "XUNJI_E_CRON_CREATE_REQUIRED"
E_ITERATION_PLAN_REQUIRED = "XUNJI_E_ITERATION_PLAN_REQUIRED"
E_WORK_PLAN_REQUIRED = "XUNJI_E_WORK_PLAN_REQUIRED"
E_WORK_PLAN_STALE = "XUNJI_E_WORK_PLAN_STALE"
E_DELEGATION_REQUIRED = "XUNJI_E_DELEGATION_REQUIRED"
E_ROOT_COORDINATOR_ONLY = "XUNJI_E_ROOT_COORDINATOR_ONLY"
E_CAPABILITY_POLICY = "XUNJI_E_CAPABILITY_POLICY"
E_AGENT_TOOL_CALL_LIMIT_EXCEEDED = "XUNJI_E_AGENT_TOOL_CALL_LIMIT_EXCEEDED"
E_AGENT_TOOL_CALL_IDENTITY_CONFLICT = "XUNJI_E_AGENT_TOOL_CALL_IDENTITY_CONFLICT"
E_AGENT_TOOL_CALL_BUDGET_INVALID = "XUNJI_E_AGENT_TOOL_CALL_BUDGET_INVALID"
E_AGENT_REQUEST_BUDGET_EXCEEDED = "XUNJI_E_AGENT_REQUEST_BUDGET_EXCEEDED"
E_AGENT_INSTRUCTION_SOURCE_STALE = "XUNJI_E_AGENT_INSTRUCTION_SOURCE_STALE"
E_AGENT_ARTIFACT_INTEGRITY = "XUNJI_E_AGENT_ARTIFACT_INTEGRITY"
E_LIFECYCLE_PRIVATE_API = "XUNJI_E_LIFECYCLE_PRIVATE_API"
E_RUNTIME_RECEIPT_HOOK_FAILED = "XUNJI_E_RUNTIME_RECEIPT_HOOK_FAILED"
E_ROOT_SETTLEMENT_REQUIRED = "XUNJI_E_ROOT_SETTLEMENT_REQUIRED"
ERROR_CODE_RE = re.compile(r"^\[([A-Z0-9_]+)\]")
ENV_ASSIGNMENT_TOKEN_RE = re.compile(
    r"[A-Za-z_][A-Za-z0-9_]*=.*", re.DOTALL)

EXPLAIN_RE = re.compile(
    r"告诉我(?:原因|为什么|想法)|为什么|"
    r"分析(?:上面|以下|这段)(?:的)?(?:代码|文本|内容)|"
    r"不用修改|不要修改|无需修改|别修改|"
    r"不用做|不要做|先别做|不要执行|不得执行|别执行|只(?:告诉|回答|分析|解释|说明)|无需执行|"
    r"tell me why|explain only|can you (?:explain|describe|tell me)|"
    r"do not (?:change|modify|act|execute|run|apply|start)|no changes",
    re.I,
)
LOOP_EXPLAIN_OVERRIDE_RE = re.compile(
    r"告诉我(?:原因|为什么|想法)|为什么|"
    r"分析(?:上面|以下|这段)(?:的)?(?:代码|文本|内容)|"
    r"只(?:告诉|回答|分析|解释|说明)|"
    r"不用做|不要做|先别做|不要执行|不得执行|别执行|无需执行|"
    r"tell me why|explain only|can you (?:explain|describe|tell me)|"
    r"do not (?:act|execute|run|apply|start)",
    re.I,
)
PAUSE_RE = re.compile(
    r"停止\s*(?:loop|循环|渗透|运行)|渗透结束|暂停\s*(?:loop|循环|渗透|运行)|"
    r"先停(?:止|下)|stop\s+(?:the\s+)?(?:loop|run|testing)|pause\s+(?:the\s+)?(?:loop|run)",
    re.I,
)
EXECUTE_RE = re.compile(
    r"继续(?:执行|推进|修复|运行|渗透)?|恢复(?:执行|运行|loop)?|"
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
    r"(?:runtime_events\.jsonl|runtime_projection_error\.json|"
    r"runtime_projection_cursor\.json|coverage\.json|"
    r"asset_ledger\.json|\.runtime_events\.lock|"
    r"loop_journal\.jsonl|\.loop_journal\.lock|"
    r"reason_pass_receipts\.jsonl|\.reason_pass\.lock|"
    r"turn_contract\.json|run_status\.json|work_plan\.json|"
    r"work_plan_transaction\.json|\.work_plan\.lock|"
    r"work_plans[/\\][0-9a-f]{64}\.json|"
    r"work_plan_transactions[/\\][0-9a-f]{64}\.json|"
    r"setup_source\.json|setup_transaction\.json|"
    r"sources[/\\](?:normalized\.json|validator_receipt\.json|original[/\\][^\s;|&]+)|"
    r"\.xunji_(?:activation|setup|scope_admission)\.lock|\.xunji_staging|"
    r"assignments\.json|delegate_transaction\.json|\.assignments\.lock|"
    r"assignment_cancellation_transaction\.json|"
    r"assignment_cancellations[/\\][0-9a-f]{64}\.json|"
    r"merge_drafts[/\\][A-Za-z0-9._-]+\.json|"
    r"merge_results[/\\][A-Za-z0-9._-]+[/\\][A-Za-z0-9._-]+\.json|"
    r"scope_admissions|xunji_active_run|xunji_pending_turns|"
    r"xunji_session_selections|"
    r"xunji_transition_claims|xunji_scope_admission_claims|"
    r"review[/\\]receipts[/\\][0-9a-f]{64}\.json)"
    r"(?=[.\/\\\"'\s;|&}]|$)",
    re.I,
)
RUN_TRANSITION_RE = re.compile(
    r"(?:新建|创建|建立|重开|重新开|初始化|启动).{0,24}(?:run|运行)|"
    r"(?:new|create|setup|start).{0,24}run",
    re.I,
)
RUN_BIND_RE = re.compile(
    r"(?:/loop\s+(?:[^\n]*runs[/\\]|https?://\S+|(?:/|\.{1,2}/|[A-Za-z]:[/\\])\S+)|"
    r"(?:恢复|续接|resume|continue).{0,24}(?:run|运行)|"
    r"(?:set-active|setup_run\.py|loop_bootstrap\.py)|"
    r"(?:设置|切换|选择|绑定|set|switch|select|bind).{0,20}active[ -]?run)",
    re.I,
)
PROMPT_URL_RE = re.compile(r"(?i)https?://[^\s\"'<>]+")
QUESTION_RE = re.compile(
    r"^\s*(?:怎么|如何|是否|要不要|能否|可否|什么|哪|谁)|"
    r"^\s*(?:can|could|would|should|may|might|is|are|do|does|did|"
    r"what|which|who|why|how)\b|"
    r"(?:吗|么|呢)\s*[?？。.!！]*\s*$|[?？]\s*$",
    re.I,
)
LIFECYCLE_DENIAL_RE = re.compile(
    r"(?:不(?:要|得|应|用|再|允许)?|禁止|无需|别|取消).{0,32}"
    r"(?:创建|新建|建立|启动|恢复|续接|切换|设置|"
    r"\b(?:setup|create|start|resume|continue|switch|set)\b)"
    r".{0,24}(?:\brun\b|运行)|"
    r"(?:do\s+not|don't|never|no\s+need\s+to|should\s+not|must\s+not).{0,32}"
    r"\b(?:create|start|setup|resume|continue|switch|set)\b.{0,24}\brun\b",
    re.I,
)
CLASSIFY_DENIAL_RE = re.compile(
    r"(?:不(?:要|得|应|用|允许)?|禁止|无需|别|without|do\s+not|don't|never|\bno\b)"
    r".{0,24}--classify|--classify.{0,24}(?:不要|不得|禁止|without|disabled)",
    re.I,
)
AI_EXTERNAL_DENIAL_RE = re.compile(
    r"(?:不(?:要|得|应|用|允许)?|禁止|无需|别|without|do\s+not|don't|never|\bno\b)"
    r".{0,24}--ai(?:\s+|=)external|"
    r"--ai(?:\s+|=)external.{0,24}(?:不要|不得|禁止|without|disabled)",
    re.I,
)
INLINE_DATA_RE = re.compile(
    r"`[^`\n]*`|\"[^\"\n]*\"|“[^”\n]*”|‘[^’\n]*’|"
    r"(?<![A-Za-z0-9_])'[^'\n]*'(?![A-Za-z0-9_])"
)
NATURAL_RUN_TRANSITION_RE = re.compile(
    r"^[ \t]{0,3}(?:(?:请(?:帮我)?|帮我|现在|立即|马上)\s*)*"
    r"(?:从\s+\S+\s+)?"
    r"(?:创建|新建|建立|重开|重新开|初始化|启动)[^\r\n]{0,24}"
    r"(?:run(?![A-Za-z0-9_-])|运行)|"
    r"^[ \t]{0,3}(?:(?:please|now)\s+)*"
    r"(?:create|start|setup|set\s+up|initialize)\b[^\r\n]{0,24}\brun\b",
    re.I | re.M,
)
NATURAL_RUN_BIND_RE = re.compile(
    r"^[ \t]{0,3}(?:(?:请(?:帮我)?|帮我|现在|立即|马上)\s*)*"
    r"(?:(?:继续|恢复|续接)[^\r\n]{0,24}(?:run(?![A-Za-z0-9_-])|运行|runs[/\\])|"
    r"(?:设置|切换|选择|绑定)[^\r\n]{0,20}(?:active[ -]?run|运行指针))|"
    r"^[ \t]{0,3}(?:(?:please|now)\s+)*"
    r"(?:(?:resume|continue)\b[^\r\n]{0,24}(?:\brun\b|runs[/\\])|"
    r"(?:set|switch|select|bind)\b[^\r\n]{0,20}\bactive[ -]?run\b)",
    re.I | re.M,
)


def _first_operator_line(prompt: str) -> str:
    for line in str(prompt or "").splitlines():
        if line.strip():
            # Preserve the original bytes for prompt hashing and data-container
            # detection.  Directive normalization is a separate, auditable step.
            return line.rstrip()
    return ""


DIRECTIVE_LEADING_WHITESPACE = "\ufeff \t\u00a0\u2007\u202f\u3000"
DIRECTIVE_DATA_PREFIX_RE = re.compile(r"^(?:>|```|~~~|[-*+]\s)")


def _operator_directive_line(prompt: str) -> tuple[str, list[str]]:
    """Return one human directive after effect-preserving presentation cleanup.

    Leading horizontal whitespace is a common terminal/paste artifact in this
    personal tool and does not change the requested effect.  Explicit Markdown
    data containers remain data: blockquotes, fenced code, and list items are not
    silently converted into operator directives.
    """
    raw = _first_operator_line(prompt)
    if not raw:
        return "", []
    line = raw.lstrip(DIRECTIVE_LEADING_WHITESPACE).rstrip()
    if not line or DIRECTIVE_DATA_PREFIX_RE.match(line):
        return "", []
    normalizations: list[str] = []
    if line != raw:
        normalizations.append("leading_horizontal_whitespace")
    return line, normalizations


def _operator_intent_text(prompt: str) -> str:
    """Remove fenced/quoted data before natural-language authority matching."""
    kept: list[str] = []
    fence = ""
    for raw_line in str(prompt or "").splitlines():
        line = raw_line.strip()
        marker = re.match(r"^(```+|~~~+)", line)
        if marker:
            token = marker.group(1)[0]
            if not fence:
                fence = token
            elif fence == token:
                fence = ""
            continue
        if fence or line.startswith(">") \
                or raw_line.startswith("    ") or raw_line.startswith("\t"):
            continue
        kept.append(INLINE_DATA_RE.sub(" ", raw_line))
    return "\n".join(kept)


def _operator_effect_constraints(prompt: str) -> tuple[bool, bool]:
    """Freeze explicit negative network intent without treating it as an ACL."""
    intent = _operator_intent_text(prompt)
    clauses = [
        item.strip() for item in re.split(r"[\n。！？!?；;，,]+", intent)
        if item.strip()
    ]
    all_network = any(ALL_NETWORK_DENIAL_RE.search(item) for item in clauses)
    return (
        all_network or any(
            TARGET_EGRESS_DENIAL_RE.search(item) for item in clauses),
        all_network or any(WEB_TOOL_DENIAL_RE.search(item) for item in clauses),
    )


def _natural_lifecycle_intent(intent: str) -> tuple[bool, bool]:
    """Return explicit top-level (new-run, bind-run) operation intent.

    Broad lifecycle words remain useful for legacy contract compatibility, but
    current authority requires an imperative-looking top-level line.  This
    keeps explanatory prose such as "这是创建新 run 的说明" from minting an
    executable run transition.
    """
    return (
        bool(NATURAL_RUN_TRANSITION_RE.search(intent)),
        bool(NATURAL_RUN_BIND_RE.search(intent)),
    )


def _prompt_has_loop_directive(prompt: str) -> bool:
    line, _normalizations = _operator_directive_line(prompt)
    return bool(re.match(r"^/loop(?:\s|$)", line, re.I))


def _prompt_loop_source(prompt: str) -> str:
    line, _normalizations = _operator_directive_line(prompt)
    loop = re.match(r"^/loop\s+(.+)$", line, re.I)
    if not loop:
        return ""
    try:
        tokens = shlex.split(loop.group(1), comments=False, posix=True)
    except ValueError:
        return ""
    # Keep the exact parsed token.  Characters such as ')' and ']' are legal in
    # URL paths and file names; silently trimming them would authorize a
    # different source.  Ambiguous prose punctuation must fail closed.
    return tokens[0] if tokens else ""


def _prompt_source_authority(prompt: str) -> tuple[list[str], bool]:
    """Return source hashes plus ambiguity without persisting raw URL secrets.

    An explicit ``/loop`` owns its first parsed source token.  Natural language
    may name one unique URL, but multiple URLs are data until the operator makes
    the lifecycle source unambiguous; guessing among them would mint authority.
    """
    text = str(prompt or "")
    if _prompt_has_loop_directive(text):
        value = _prompt_loop_source(text)
        values = [value] if value else []
        ambiguous = False
    else:
        text = _operator_intent_text(text)
        values = []
        for match in PROMPT_URL_RE.finditer(text):
            value = match.group(0)
            if value and value not in values:
                values.append(value)
        ambiguous = len(values) > 1 or any(
            value.endswith(tuple(".,，。);；]}>")) for value in values
        )
        if ambiguous:
            values = []
    return ([
        hashlib.sha256(value.encode("utf-8", "replace")).hexdigest()
        for value in values[:1]
    ], ambiguous)


def _prompt_run_authority(prompt: str) -> tuple[list[str], bool]:
    """Hash one prompt-named run basename without treating URL paths as runs."""
    text = str(prompt or "")
    loop_source = _prompt_loop_source(text) if _prompt_has_loop_directive(text) else ""
    if loop_source:
        tokens = [loop_source]
    else:
        text = _operator_intent_text(text)
        try:
            tokens = shlex.split(text, comments=False, posix=True)
        except ValueError:
            tokens = text.split()
    names: list[str] = []
    for raw in tokens:
        token = str(raw)
        name = _run_name_from_path(token)
        if name and name not in names:
            names.append(name)
    ambiguous = len(names) > 1
    if ambiguous:
        names = []
    return ([
        hashlib.sha256(name.encode("utf-8", "replace")).hexdigest()
        for name in names[:1]
    ], ambiguous)


def _prompt_slug_authority(prompt: str) -> tuple[list[str], bool]:
    """Hash an explicitly named setup slug outside quoted/fenced data."""
    text = _operator_intent_text(prompt)
    names: list[str] = []
    patterns = (
        re.compile(
            r"(?:\bslug\b|短名|命名为|名为)\s*[:=：]?\s*"
            r"([A-Za-z0-9_-]+)(?![A-Za-z0-9_-])",
            re.I,
        ),
        re.compile(
            r"setup_run\.py\s+([A-Za-z0-9_-]+)(?![A-Za-z0-9_-])",
            re.I,
        ),
    )
    for pattern in patterns:
        for match in pattern.finditer(text):
            name = str(match.group(1) or "")
            if name and name not in names:
                names.append(name)
    ambiguous = len(names) > 1
    if ambiguous:
        names = []
    return ([
        hashlib.sha256(name.encode("utf-8", "replace")).hexdigest()
        for name in names[:1]
    ], ambiguous)


def _operator_flag_approved(
    prompt: str,
    *,
    positive: re.Pattern[str],
    denial: re.Pattern[str],
) -> bool:
    """Derive an opt-in from the full operator text, never the log excerpt."""
    intent = _operator_intent_text(prompt)
    return bool(positive.search(intent) and not denial.search(intent))


class TransitionDurabilityError(RuntimeError):
    """An authority write/delete could not cross its durability barrier."""


def _fsync_directory(path: Path) -> None:
    try:
        fd = os.open(path, os.O_RDONLY)
    except (AttributeError, OSError) as exc:
        raise TransitionDurabilityError(
            f"cannot open authority directory for fsync: {path}"
        ) from exc
    try:
        os.fsync(fd)
    except (AttributeError, OSError) as exc:
        raise TransitionDurabilityError(
            f"cannot fsync authority directory: {path}"
        ) from exc
    finally:
        os.close(fd)


def _confirm_directory_durable(path: Path) -> None:
    if not path.is_dir():
        raise TransitionDurabilityError(
            f"authority directory is unavailable for durability confirmation: {path}"
        )
    _fsync_directory(path)


def _confirm_authority_directory_chain(directory: Path) -> None:
    """Confirm one authority directory and exactly one ownership ancestor.

    The fixed two-level barrier covers ``state -> run`` and
    ``pending/claims -> .claude`` without recursively syncing unrelated
    ancestors.  It runs on every retry; visible directory existence is never
    treated as proof that an earlier ancestor barrier succeeded.
    """
    _confirm_directory_durable(directory)
    owner_directory = directory.parent
    if owner_directory != directory:
        _confirm_directory_durable(owner_directory)


def _durable_unlink(path: Path, *, require_directory: bool) -> bool:
    """Delete one authority artifact and durably confirm presence or absence."""
    directory = path.parent
    if not directory.is_dir():
        if require_directory:
            raise TransitionDurabilityError(
                f"authority directory is unavailable for durable deletion: {directory}"
            )
        return False
    existed = path.exists()
    try:
        path.unlink(missing_ok=True)
    except OSError as exc:
        raise TransitionDurabilityError(
            f"cannot delete authority artifact: {path}"
        ) from exc
    _confirm_authority_directory_chain(directory)
    return existed


def _atomic_json(path: Path, value: dict, *, durable: bool = False) -> None:
    raw = ""
    fd: int | None = None
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        fd, raw = tempfile.mkstemp(
            prefix=path.name + ".", suffix=".tmp", dir=path.parent)
        handle = os.fdopen(fd, "w", encoding="utf-8")
        fd = None
        with handle:
            json.dump(value, handle, ensure_ascii=False, indent=2, sort_keys=True)
            handle.write("\n")
            if durable:
                handle.flush()
                os.fsync(handle.fileno())
        os.chmod(raw, 0o600)
        os.replace(raw, path)
        if durable:
            _confirm_authority_directory_chain(path.parent)
    except TransitionDurabilityError:
        raise
    except (AttributeError, OSError) as exc:
        if durable:
            raise TransitionDurabilityError(
                f"cannot durably replace authority artifact: {path}"
            ) from exc
        raise
    finally:
        if fd is not None:
            try:
                os.close(fd)
            except OSError:
                pass
        if raw:
            try:
                os.unlink(raw)
            except FileNotFoundError:
                pass


def contract_path(run_dir: Path) -> Path:
    return run_dir / "state" / "turn_contract.json"


def run_status_path(run_dir: Path) -> Path:
    return run_dir / "state" / "run_status.json"


def explicit_active_run(
    runs_root: Path | None = None,
    pointer: Path | None = None,
    project_root: Path | None = None,
) -> Path | None:
    """Resolve only the authoritative pointer; contracts must never guess a run."""
    root = (runs_root or RUNS).resolve()
    project = (project_root or ROOT).resolve()
    marker = pointer or ACTIVE_RUN_POINTER
    try:
        raw = marker.read_text(encoding="utf-8", errors="replace").strip()
        if not raw:
            return None
        candidate = Path(raw).expanduser()
        if not candidate.is_absolute():
            candidate = project / candidate
        candidate = candidate.resolve()
        candidate.relative_to(root)
    except Exception:
        return None
    if not candidate.is_dir():
        return None
    if not any((candidate / name).exists() for name in (
            "target.md", "frontier.md", "evidence.md", "decisions.md", "review.md")):
        return None
    return candidate


def classify_prompt(prompt: str, *, active_run: bool = True) -> str:
    prompt = prompt or ""
    if not active_run:
        return NORMAL
    intent = _operator_intent_text(prompt)
    if PAUSE_RE.search(intent):
        return PAUSE
    if LIFECYCLE_DENIAL_RE.search(intent) or QUESTION_RE.search(intent):
        return EXPLAIN
    if _prompt_has_loop_directive(prompt):
        # An exact lifecycle request may also contain narrow safety/effect
        # constraints such as "do not modify framework source".  Those clauses
        # reduce the allowed effect; they do not negate the requested run.
        if LOOP_EXPLAIN_OVERRIDE_RE.search(intent):
            return EXPLAIN
        return EXECUTE
    if EXPLAIN_RE.search(intent):
        return EXPLAIN
    natural_transition, natural_bind = _natural_lifecycle_intent(intent)
    if natural_transition or natural_bind:
        return EXECUTE
    if EXECUTE_RE.search(intent):
        return EXECUTE
    return EXPLAIN


def _contract_from_event(
    event: dict,
    *,
    run_name: str = "",
    previous_mode: str = "",
) -> dict:
    prompt = str(event.get("prompt") or "")
    session_binding, session_binding_kind = _event_session_binding(event)
    _directive_line, intent_normalizations = _operator_directive_line(prompt)
    intent_text = _operator_intent_text(prompt)
    source_sha256s, source_ambiguous = _prompt_source_authority(prompt)
    run_name_sha256s, run_ambiguous = _prompt_run_authority(prompt)
    slug_sha256s, slug_ambiguous = _prompt_slug_authority(prompt)
    natural_transition, natural_bind = _natural_lifecycle_intent(intent_text)
    loop_requested = _prompt_has_loop_directive(prompt)
    target_egress_denied, web_tools_denied = _operator_effect_constraints(prompt)
    maintenance = maintenance_authority.operator_intent(
        prompt,
        previous_mode=previous_mode,
        lifecycle_intent=bool(
            loop_requested or natural_transition or natural_bind),
    )
    scope_request, scope_error = scope_admission.parse_operator_directive(prompt)
    if maintenance and scope_request:
        maintenance = False
    mode = EXECUTE if scope_request else (
        MAINTENANCE if maintenance else classify_prompt(prompt, active_run=True)
    )
    if scope_error:
        mode = EXPLAIN
    now = time.time()
    loop_source = _prompt_loop_source(prompt) if loop_requested else ""
    if re.match(r"(?i)^https?://", loop_source):
        loop_source_kind = "url"
    elif _run_name_from_path(loop_source):
        loop_source_kind = "run"
    elif loop_source:
        loop_source_kind = "file"
    else:
        loop_source_kind = "none"
    derived_transition = bool(
        mode == EXECUTE and natural_transition
        and not LIFECYCLE_DENIAL_RE.search(intent_text)
    )
    if mode == EXECUTE and loop_source_kind in {"url", "file"}:
        derived_transition = True
    elif mode == EXECUTE and loop_source_kind == "run":
        derived_transition = not run_name or _run_name_from_path(loop_source) != run_name
    if mode != EXECUTE:
        lifecycle_operation = "none"
    elif loop_requested:
        lifecycle_operation = (
            "resume" if loop_source_kind == "run" else
            "source" if loop_source_kind in {"url", "file"} else
            "loop"
        )
    elif natural_bind:
        lifecycle_operation = "resume"
    elif natural_transition:
        lifecycle_operation = "source" \
            if source_sha256s or source_ambiguous else "setup"
    else:
        lifecycle_operation = "none"
    contract = {
        "schema": SCHEMA,
        "mode": mode,
        "session_id": session_binding,
        "reported_session_id": str(event.get("session_id") or ""),
        "session_binding_kind": session_binding_kind,
        "transcript_path": str(event.get("transcript_path") or ""),
        "prompt_sha256": hashlib.sha256(prompt.encode("utf-8", "replace")).hexdigest(),
        "prompt_excerpt": privacy.sanitize_text_for_log(prompt[:500]),
        "source_sha256s": source_sha256s,
        "source_ambiguous": source_ambiguous,
        "run_name_sha256s": run_name_sha256s,
        "run_ambiguous": run_ambiguous,
        "slug_sha256s": slug_sha256s,
        "slug_ambiguous": slug_ambiguous,
        "classify_approved": _operator_flag_approved(
            prompt,
            positive=re.compile(r"(?:^|\s)--classify(?:\s|$)", re.I),
            denial=CLASSIFY_DENIAL_RE,
        ),
        "ai_external_approved": _operator_flag_approved(
            prompt,
            positive=re.compile(
                r"(?:^|\s)--ai(?:\s+|=)external(?:\s|$)", re.I),
            denial=AI_EXTERNAL_DENIAL_RE,
        ),
        "resume_current_approved": bool(
            lifecycle_operation == "resume"
            and not run_name_sha256s
            and not run_ambiguous
        ),
        "lifecycle_operation": lifecycle_operation,
        "memory_approved": bool(MEMORY_APPROVAL_RE.search(prompt)),
        "direct_egress_approved": bool(
            DIRECT_EGRESS_APPROVAL_RE.search(prompt)
            and not DIRECT_EGRESS_DENIAL_RE.search(prompt)
        ),
        "target_egress_denied": target_egress_denied,
        "web_tools_denied": web_tools_denied,
        "fanout_override": bool(re.search(r"(?:明确)?允许串行|不要使用\s*(?:Agent|子代理)|serial override", prompt, re.I)),
        "intent_normalizations": intent_normalizations,
        "loop_requested": loop_requested,
        "loop_source_kind": loop_source_kind,
        "run_bind_requested": natural_bind,
        "run_transition_requested": derived_transition,
        "origin_run": run_name,
        "bound_run": run_name,
        "updated_at": now,
    }
    if maintenance:
        contract["maintenance_intent"] = "operator_prompt"
    if scope_request:
        contract["scope_admission_run"] = str(scope_request.get("run_name") or "")
        contract["scope_admission_assets"] = list(scope_request.get("assets") or [])
        contract["scope_admission_reason_sha256"] = str(
            scope_request.get("reason_sha256") or "")
    if scope_error:
        contract["scope_admission_parse_error"] = scope_error
    return contract


def _safe_run_summary(run_dir: Path) -> tuple[dict, str]:
    """Keep hook execution deterministic when canonical state parsing fails."""
    try:
        state = run_model.summary(run_dir)
    except Exception as exc:
        note = f"{exc.__class__.__name__}: run_model.summary failed"
        return {"fronts": [], "open": [], "schema_errors": [note]}, note
    return (state if isinstance(state, dict) else {
        "fronts": [], "open": [], "schema_errors": ["invalid run_model summary"],
    }), ""


def _coordination_signature(run_dir: Path) -> str:
    """Hash only topology and coverage debt that should start a new fan-out epoch."""
    state, summary_error = _safe_run_summary(run_dir)
    fronts = sorted(
        (str(item.get("id") or ""), str(item.get("status") or ""), str(item.get("barrier") or ""))
        for item in state.get("fronts", [])
        if isinstance(item, dict) and str(item.get("id") or "") in set(state.get("open", []))
    )
    assets: list[tuple] = []
    coverage_paths = [run_dir / "coverage.json", *sorted(run_dir.glob("**/coverage.json"))]
    for path in coverage_paths:
        if not path.exists():
            continue
        try:
            coverage = json.loads(path.read_text(encoding="utf-8", errors="replace"))
        except Exception:
            continue
        for asset in coverage.get("assets", []) if isinstance(coverage, dict) else []:
            if not isinstance(asset, dict) or asset.get("reachable") is False:
                continue
            host = str(asset.get("host") or asset.get("asset") or asset.get("url") or "").lower()
            if not host:
                continue
            assets.append((
                host,
                str(asset.get("reachable")),
                bool(asset.get("examined")),
                str(asset.get("verdict") or ""),
                tuple(sorted(str(item) for item in (asset.get("tested_groups") or []))),
            ))
        break
    # Do not include coverage_matrix's derived assignment ``disposition`` here.
    # Agent launch/return/merge changes that cache and would invalidate the very
    # epoch whose receipts are meant to prove the lifecycle.  Canonical coverage
    # fields above still reset the epoch for reachability, verdict, examined, or
    # tested-group changes.
    return hashlib.sha256(json.dumps(
        {"fronts": fronts, "coverage_debt": sorted(assets),
         "summary_error": summary_error},
        ensure_ascii=False, sort_keys=True, separators=(",", ":"),
    ).encode("utf-8")).hexdigest()


def coordination_epoch(run_dir: Path, contract: dict) -> dict:
    """Validate and return the one fan-out epoch shared by PreToolUse and Stop.

    Session ids deliberately do not participate: a bare continue prompt may
    replace the Claude session/turn while the material front and coverage
    topology remains unchanged.  A missing or forged signature/start pair is
    fail-closed, and a material topology change requires ``write_contract`` to
    mint a new epoch before old Agent receipts can satisfy coordination.
    """
    live_signature = _coordination_signature(run_dir)
    stored_signature = str(contract.get("coordination_signature") or "")
    try:
        started_at = float(contract.get("fanout_epoch_started_at") or 0.0)
        contract_updated_at = float(contract.get("updated_at") or 0.0)
    except (TypeError, ValueError):
        started_at = 0.0
        contract_updated_at = 0.0
    epoch_id = str(contract.get("fanout_epoch_id") or "")
    valid = bool(
        re.fullmatch(r"[0-9a-f]{64}", stored_signature)
        and stored_signature == live_signature
        and started_at > 0
        and contract_updated_at >= started_at
        and re.fullmatch(r"[0-9a-f]{16}", epoch_id)
    )
    return {
        "valid": valid,
        "since": started_at if valid else 0.0,
        "coordination_signature": live_signature,
        "fanout_epoch_id": epoch_id if valid else "",
        "error": "" if valid else "XUNJI_E_COORDINATION_EPOCH_STALE",
    }


def _previous_contract(run_dir: Path) -> dict:
    try:
        data = json.loads(contract_path(run_dir).read_text(encoding="utf-8", errors="replace"))
    except Exception:
        return {}
    return data if isinstance(data, dict) and data.get("schema") == SCHEMA else {}


def write_contract(run_dir: Path, event: dict) -> dict:
    previous = _previous_contract(run_dir)
    contract = _contract_from_event(
        event,
        run_name=run_dir.name,
        previous_mode=str(previous.get("mode") or ""),
    )
    requested_scope_run = str(contract.get("scope_admission_run") or "")
    if requested_scope_run and requested_scope_run != run_dir.name:
        contract.pop("scope_admission_run", None)
        contract.pop("scope_admission_assets", None)
        contract.pop("scope_admission_reason_sha256", None)
        contract["scope_admission_parse_error"] = (
            "scope admission run must equal the exact active run"
        )
        contract["mode"] = EXPLAIN
    signature = _coordination_signature(run_dir)
    previous_since = float(previous.get("fanout_epoch_started_at") or 0.0)
    if previous.get("coordination_signature") == signature and previous_since > 0:
        contract["fanout_epoch_started_at"] = previous_since
        contract["fanout_epoch_id"] = str(previous.get("fanout_epoch_id") or "")
    else:
        contract["fanout_epoch_started_at"] = float(contract["updated_at"])
        contract["fanout_epoch_id"] = hashlib.sha256(
            f"{run_dir.resolve()}:{signature}:{contract['updated_at']}".encode("utf-8")
        ).hexdigest()[:16]
    contract["coordination_signature"] = signature
    _atomic_json(contract_path(run_dir), contract, durable=True)
    _write_run_status(run_dir, contract)
    return contract


def _write_session_barrier(
    run_dir: Path,
    *,
    session_id: str,
    transcript_path: str,
    authority_state: str,
    ended_from_contract_sha256: str,
    session_end_reason: str = "",
    resume_selection_sha256: str = "",
) -> dict:
    """Persist a non-executable boundary contract for end/resume lifecycle.

    The barrier intentionally reconstructs a blank-prompt EXPLAIN contract
    instead of copying the previous turn.  Session selection may survive, but
    prompt, transition, maintenance, scope, and target authority never do.
    """
    if authority_state not in {
            AUTHORITY_SESSION_ENDED, AUTHORITY_RESUME_BARRIER}:
        raise ValueError("unknown session authority barrier")
    transcript_sha256 = hashlib.sha256(
        transcript_path.encode("utf-8", "replace")).hexdigest()
    previous = _previous_contract(run_dir)
    barrier = _contract_from_event({
        "session_id": session_id,
        "transcript_path": transcript_path,
        "prompt": "",
    }, run_name=run_dir.name)
    for key in (
            "coordination_signature", "fanout_epoch_started_at",
            "fanout_epoch_id"):
        if key in previous:
            barrier[key] = previous[key]
    barrier.update({
        "authority_state": authority_state,
        "resume_requires_prompt": True,
        "transcript_sha256": transcript_sha256,
        "ended_from_contract_sha256": ended_from_contract_sha256,
    })
    if authority_state == AUTHORITY_SESSION_ENDED:
        barrier["session_end_reason"] = session_end_reason
        barrier["session_ended_at"] = time.time()
    else:
        barrier["session_start_source"] = "resume"
        barrier["resume_selection_sha256"] = resume_selection_sha256
        barrier["session_resumed_at"] = time.time()
    _atomic_json(contract_path(run_dir), barrier, durable=True)
    return barrier


def _pending_path(session_id: str, pending_dir: Path | None = None) -> Path:
    digest = hashlib.sha256(session_id.encode("utf-8", "replace")).hexdigest()
    return (pending_dir or PENDING_DIR) / f"{digest}.json"


SINGLE_OPERATOR_SESSION_BINDING = "xunji:single-operator"


def _transcript_session_binding(transcript_path: str) -> str:
    value = str(transcript_path or "").strip()
    if not value:
        return ""
    digest = hashlib.sha256(value.encode("utf-8", "replace")).hexdigest()
    return f"xunji:transcript:{digest}"


def _event_session_binding(event: dict) -> tuple[str, str]:
    """Return a causal turn binding, not a multi-user authorization identity."""
    session_id = str(event.get("session_id") or "").strip()
    if session_id:
        return session_id, "session_id"
    transcript_binding = _transcript_session_binding(
        str(event.get("transcript_path") or ""))
    if transcript_binding:
        return transcript_binding, "transcript_path"
    return SINGLE_OPERATOR_SESSION_BINDING, "single_operator"


def _event_session_candidates(event: dict) -> list[str]:
    values: list[str] = []
    reported = str(event.get("session_id") or "").strip()
    transcript = _transcript_session_binding(
        str(event.get("transcript_path") or ""))
    # Use the strongest available correlation key.  The personal singleton is
    # a last-resort recovery only when Claude omitted both metadata fields; it
    # must never let a named session consume another session's pending intent.
    candidates = (reported, transcript) if (reported or transcript) else (
        SINGLE_OPERATOR_SESSION_BINDING,)
    for value in candidates:
        if value and value not in values:
            values.append(value)
    return values


def _revoke_transition_claims_unlocked(
    session_id: str,
    *,
    claims_dir: Path | None = None,
) -> None:
    """Tombstone one session's transition claims under activation lock."""
    if not session_id:
        return
    directory = claims_dir or TRANSITION_CLAIMS_DIR
    if directory.is_dir():
        for path in directory.glob("*.json"):
            try:
                claim = json.loads(path.read_text(
                    encoding="utf-8", errors="replace"))
            except Exception:
                continue
            if str(claim.get("session_id") or "") != session_id:
                continue
            try:
                setup_transaction.validate_transition_effect(
                    claim.get("effect"))
            except ValueError as exc:
                raise RuntimeError(
                    "matching transition claim cannot be durably revoked"
                ) from exc
            if claim.get("schema") != SCHEMA \
                    or str(claim.get("status") or "") not in {
                        "active", "claimed", "revoked",
                    }:
                raise RuntimeError(
                    "matching transition claim has an invalid revocation state")
            claim.update({
                "schema": SCHEMA,
                "session_id": session_id,
                "status": "revoked",
                "revoked_at": float(
                    claim.get("revoked_at") or time.time()),
                "updated_at": time.time(),
            })
            _atomic_json(path, claim, durable=True)


def _revoke_pending_session_unlocked(
    session_id: str,
    *,
    pending_dir: Path | None = None,
    claims_dir: Path | None = None,
) -> None:
    """Revoke one pending session while the caller holds activation lock."""
    if not session_id:
        return
    _revoke_transition_claims_unlocked(session_id, claims_dir=claims_dir)
    _durable_unlink(
        _pending_path(session_id, pending_dir), require_directory=False)


def _revoke_pending_session(
    session_id: str,
    *,
    pending_dir: Path | None = None,
    claims_dir: Path | None = None,
    pointer: Path | None = None,
    lock_timeout: float = 10.0,
) -> None:
    """Linearizably tombstone prior authority before a top-level prompt."""
    lock = (pointer or ACTIVE_RUN_POINTER).parent \
        / setup_transaction.ACTIVATION_LOCK_NAME
    with setup_transaction.exclusive_directory_lock(lock, timeout=lock_timeout):
        _revoke_pending_session_unlocked(
            session_id, pending_dir=pending_dir, claims_dir=claims_dir)


def cleanup_session_end(
    event: dict,
    *,
    root: Path = ROOT,
    runs_root: Path = RUNS,
    pointer: Path = ACTIVE_RUN_POINTER,
    pending_dir: Path = PENDING_DIR,
    claims_dir: Path = TRANSITION_CLAIMS_DIR,
    selection_dir: Path = SESSION_SELECTION_DIR,
    lock_timeout: float = 1.0,
) -> bool:
    """Clear only the selection still owned by the ending Claude session.

    SessionEnd cannot block exit, so every uncertainty leaves the pointer in
    place.  The pointer snapshot and exact turn-contract digest are rechecked
    together by the transaction owner under the activation lock.  This prevents
    session A from clearing a same-run selection after session B has submitted a
    newer prompt and replaced the canonical contract.
    """
    session_id = str(event.get("session_id") or "")
    transcript_path = str(event.get("transcript_path") or "")
    reason = str(event.get("reason") or "")
    if event.get("hook_event_name") != "SessionEnd" \
            or not session_id or not transcript_path:
        return False
    transcript_sha256 = hashlib.sha256(
        transcript_path.encode("utf-8", "replace")).hexdigest()

    cleared = False
    authority_retired = False

    def retire_authority() -> None:
        nonlocal authority_retired
        _revoke_pending_session_unlocked(
            session_id, pending_dir=pending_dir, claims_dir=claims_dir)
        authority_retired = True

    def end_owned_contract(target: Path, raw: bytes, contract: dict) -> dict | bytes:
        if contract.get("authority_state") == AUTHORITY_SESSION_ENDED:
            return raw
        return _write_session_barrier(
            target,
            session_id=session_id,
            transcript_path=transcript_path,
            authority_state=AUTHORITY_SESSION_ENDED,
            ended_from_contract_sha256=hashlib.sha256(raw).hexdigest(),
            session_end_reason=reason,
        )

    try:
        snapshot = setup_transaction.pointer_snapshot(pointer)
        run_dir = explicit_active_run(
            runs_root, pointer, project_root=root) if snapshot.exists else None
    except (OSError, UnicodeError):
        snapshot = setup_transaction.PointerSnapshot(False, "", "")
        run_dir = None
    if reason in SESSION_END_REASONS and run_dir is not None:
        try:
            raw_contract = contract_path(run_dir).read_bytes()
            contract = json.loads(raw_contract.decode("utf-8", "strict"))
            owned = bool(
                isinstance(contract, dict)
                and contract.get("schema") == SCHEMA
                and str(contract.get("session_id") or "") == session_id
                and str(contract.get("transcript_path") or "") == transcript_path
                and str(contract.get("bound_run") or "") == run_dir.name
                and str(contract.get("authority_state") or "") in {
                    "", AUTHORITY_SESSION_ENDED, AUTHORITY_RESUME_BARRIER,
                }
                and re.fullmatch(
                    r"[0-9a-f]{64}",
                    str(contract.get("prompt_sha256") or ""),
                )
            )
            if owned:
                cleared = setup_transaction.clear_activation_cas(
                    expected=snapshot,
                    pointer=pointer,
                    root=root,
                    runs_root=runs_root,
                    session_id=session_id,
                    transcript_sha256=transcript_sha256,
                    contract_sha256=hashlib.sha256(raw_contract).hexdigest(),
                    selection_dir=selection_dir,
                    on_owned_clear=end_owned_contract,
                    session_cleanup=retire_authority,
                    lock_timeout=lock_timeout,
                )
        except (OSError, UnicodeError, json.JSONDecodeError,
                setup_transaction.SetupTransactionError):
            cleared = False

    # Ending a session also retires its unconsumed bootstrap/transition
    # authority.  Failure is deliberately non-destructive: SessionEnd has no
    # decision control and must not delay or block Claude Code shutdown.
    if not authority_retired:
        try:
            _revoke_pending_session(
                session_id,
                pending_dir=pending_dir,
                claims_dir=claims_dir,
                pointer=pointer,
                lock_timeout=lock_timeout,
            )
        except setup_transaction.SetupTransactionError:
            pass
    return cleared


def restore_session_start(
    event: dict,
    *,
    root: Path = ROOT,
    runs_root: Path = RUNS,
    pointer: Path = ACTIVE_RUN_POINTER,
    selection_dir: Path = SESSION_SELECTION_DIR,
    lock_timeout: float = 1.0,
) -> bool:
    """Restore only the exact selection named by Claude's resume event.

    ``startup``, ``clear`` and ``compact`` never consult selection receipts.
    The restored pointer is installed behind an EXPLAIN-only barrier; the next
    real UserPromptSubmit must mint all fresh turn authority.
    """
    source = str(event.get("source") or "")
    if event.get("hook_event_name") != "SessionStart" \
            or source not in SESSION_START_SOURCES or source != "resume":
        return False
    session_id = str(event.get("session_id") or "")
    transcript_path = str(event.get("transcript_path") or "")
    if not session_id or not transcript_path:
        return False
    transcript_sha256 = hashlib.sha256(
        transcript_path.encode("utf-8", "replace")).hexdigest()

    def write_resume_barrier(target: Path, selection: dict) -> dict:
        return _write_session_barrier(
            target,
            session_id=session_id,
            transcript_path=transcript_path,
            authority_state=AUTHORITY_RESUME_BARRIER,
            ended_from_contract_sha256=str(
                selection.get("active_contract_sha256") or ""),
            resume_selection_sha256=str(
                selection.get("receipt_sha256") or ""),
        )

    try:
        return setup_transaction.restore_session_activation_cas(
            session_id=session_id,
            transcript_sha256=transcript_sha256,
            selection_dir=selection_dir,
            on_resume_barrier=write_resume_barrier,
            pointer=pointer,
            root=root,
            runs_root=runs_root,
            lock_timeout=lock_timeout,
        )
    except (OSError, UnicodeError, setup_transaction.SetupTransactionError):
        return False


def _write_pending_contract_unlocked(
    event: dict,
    *,
    pending_dir: Path | None = None,
) -> dict:
    """Persist a pending contract while the caller holds activation lock."""
    contract = _contract_from_event(event)
    session_id = str(contract.get("session_id") or "")
    if not session_id:
        return {}
    maintenance_attempt = contract.get("mode") == MAINTENANCE
    if not maintenance_attempt and (
            contract.get("mode") != EXECUTE or not bool(
                contract.get("run_transition_requested")
                or contract.get("run_bind_requested")
                or (
                    contract.get("loop_requested")
                    and contract.get("loop_source_kind") != "none"
                )
            )):
        return {}
    _atomic_json(
        _pending_path(session_id, pending_dir), contract, durable=True)
    return contract


def write_pending_contract(
    event: dict,
    *,
    pending_dir: Path | None = None,
    claims_dir: Path | None = None,
) -> dict:
    """Persist a short-lived operator contract while no run exists yet."""
    session_id, _binding_kind = _event_session_binding(event)
    if not session_id:
        return {}
    lock = ACTIVE_RUN_POINTER.parent / setup_transaction.ACTIVATION_LOCK_NAME
    with setup_transaction.exclusive_directory_lock(lock):
        _revoke_pending_session_unlocked(
            session_id, pending_dir=pending_dir, claims_dir=claims_dir)
        return _write_pending_contract_unlocked(event, pending_dir=pending_dir)


def load_pending_contract(session_id: str, *, pending_dir: Path | None = None) -> dict:
    if not session_id:
        return {}
    try:
        data = json.loads(_pending_path(session_id, pending_dir).read_text(
            encoding="utf-8", errors="replace"))
        age = time.time() - float(data.get("updated_at") or 0.0)
    except Exception:
        return {}
    valid_mode = data.get("mode") in {EXECUTE, MAINTENANCE}
    if data.get("schema") != SCHEMA or not valid_mode:
        return {}
    if not str(data.get("session_id") or "") or age < 0 or age > PENDING_STALE_SECONDS:
        return {}
    return data


def load_pending_contract_for_event(
    event: dict,
    *,
    pending_dir: Path | None = None,
) -> dict:
    """Load the current turn even when Claude omits session_id on one hook.

    Exact session identity remains the first correlation key.  A matching
    transcript or the personal-tool singleton is a recovery key, not a new
    authority source; the persisted top-level human prompt still owns the effect.
    """
    directory = pending_dir or PENDING_DIR
    for candidate in _event_session_candidates(event):
        contract = load_pending_contract(candidate, pending_dir=directory)
        if contract:
            return contract
    transcript_path = str(event.get("transcript_path") or "").strip()
    if not transcript_path or not directory.is_dir():
        return {}
    matching: list[dict] = []
    for path in directory.glob("*.json"):
        try:
            raw = json.loads(path.read_text(encoding="utf-8", errors="strict"))
        except Exception:
            continue
        session_id = str(raw.get("session_id") or "")
        contract = load_pending_contract(session_id, pending_dir=directory)
        if contract and str(contract.get("transcript_path") or "") == transcript_path:
            matching.append(contract)
    return matching[0] if len(matching) == 1 else {}


def _transition_claim_path(
    target_name: str,
    session_id: str,
    effect: dict,
    prompt_sha256: str,
    claims_dir: Path | None = None,
) -> Path:
    effect = setup_transaction.validate_transition_effect(effect)
    target_digest = hashlib.sha256(
        target_name.encode("utf-8", "replace")).hexdigest()[:32]
    session_digest = hashlib.sha256(
        session_id.encode("utf-8", "replace")).hexdigest()[:32]
    prompt_digest = hashlib.sha256(
        prompt_sha256.encode("utf-8", "replace")).hexdigest()[:32]
    effect_digest = str(effect["effect_sha256"])[:32]
    return (claims_dir or TRANSITION_CLAIMS_DIR) / (
        f"{target_digest}-{effect_digest}-{prompt_digest}-{session_digest}.json"
    )


def _transition_claim_glob(target_name: str, effect: dict | None = None) -> str:
    digest = hashlib.sha256(
        target_name.encode("utf-8", "replace")).hexdigest()[:32]
    if effect is None:
        return f"{digest}-*.json"
    validated = setup_transaction.validate_transition_effect(effect)
    return f"{digest}-{str(validated['effect_sha256'])[:32]}-*.json"


def write_transition_claim(
    target_name: str,
    contract: dict,
    *,
    claims_dir: Path | None = None,
    origin_run: str = "",
    effect: dict,
) -> dict:
    """Bind lifecycle PreToolUse to one exact redacted transition effect."""
    session_id = str(contract.get("session_id") or "")
    prompt_sha = str(contract.get("prompt_sha256") or "")
    if not target_name or not session_id or not prompt_sha:
        raise ValueError("transition claim requires target/session/prompt hash")
    effect = setup_transaction.validate_transition_effect(effect)
    if effect.get("target_run") != target_name:
        raise ValueError("transition claim effect target mismatch")
    claim = {
        "schema": SCHEMA,
        "target_run": target_name,
        "session_id": session_id,
        "prompt_sha256": prompt_sha,
        "origin_run": origin_run,
        "effect": effect,
        "status": "active",
        "updated_at": time.time(),
    }
    path = _transition_claim_path(
        target_name, session_id, effect, prompt_sha, claims_dir)
    if path.exists():
        try:
            existing = json.loads(path.read_text(
                encoding="utf-8", errors="strict"))
            existing_effect = setup_transaction.validate_transition_effect(
                existing.get("effect"))
        except Exception as exc:
            raise RuntimeError(
                "existing transition claim is unreadable or invalid"
            ) from exc
        exact_identity = bool(
            existing.get("schema") == SCHEMA
            and existing.get("target_run") == target_name
            and existing.get("session_id") == session_id
            and existing.get("prompt_sha256") == prompt_sha
            and str(existing.get("origin_run") or "") == origin_run
            and existing_effect == effect
        )
        if not exact_identity:
            raise RuntimeError(
                "existing transition claim identity cannot be overwritten")
        status = str(existing.get("status") or "")
        if status == "claimed":
            binding = existing.get("claim_binding")
            if not isinstance(binding, dict) \
                    or binding.get("target_run") != target_name \
                    or str(binding.get("origin_run") or "") != origin_run \
                    or binding.get("session_id") != session_id \
                    or binding.get("prompt_sha256") != prompt_sha \
                    or binding.get("expected_run") != target_name \
                    or binding.get("effect") != effect:
                raise RuntimeError(
                    "claimed transition identity is incomplete or inconsistent")
            # A repeated PreToolUse for the same prompt must never replace a
            # claimed record with active.  Re-run only the failed directory
            # barrier and preserve the frozen transaction binding byte-for-byte.
            _confirm_authority_directory_chain(path.parent)
            return existing
        if status == "revoked":
            raise RuntimeError(
                "transition claim was revoked by a newer operator prompt")
        if status != "active" or "claim_binding" in existing:
            raise RuntimeError("existing transition claim state is invalid")
        claim["updated_at"] = max(
            float(existing.get("updated_at") or 0.0), time.time())
    _atomic_json(path, claim, durable=True)
    return claim


def write_hook_transition_claim(
    target_name: str,
    contract: dict,
    *,
    origin_run: Path | None = None,
    pending_dir: Path | None = None,
    claims_dir: Path | None = None,
    invocation: tuple[Path, list[str]] | None = None,
) -> dict:
    """Write a claim only while its exact hook contract is still current."""
    session_id = str(contract.get("session_id") or "")
    prompt_sha = str(contract.get("prompt_sha256") or "")
    if not session_id or not prompt_sha:
        raise RuntimeError("hook transition claim lacks session/prompt identity")
    effect = _lifecycle_transition_effect(invocation, target_name) if invocation else None
    if not effect:
        raise RuntimeError("hook transition claim lacks an exact lifecycle effect")
    lock = ACTIVE_RUN_POINTER.parent / setup_transaction.ACTIVATION_LOCK_NAME
    with setup_transaction.exclusive_directory_lock(lock):
        if origin_run is None:
            if explicit_active_run() is not None:
                raise RuntimeError("active pointer appeared before no-run transition claim")
            current = load_pending_contract(session_id, pending_dir=pending_dir)
        else:
            selected = explicit_active_run()
            if selected is None or selected.resolve() != origin_run.resolve():
                raise RuntimeError("active pointer changed before transition claim")
            current = load_contract(origin_run, session_id=session_id)
        if str(current.get("prompt_sha256") or "") != prompt_sha:
            raise RuntimeError("operator contract changed before transition claim")
        return write_transition_claim(
            target_name,
            current,
            claims_dir=claims_dir,
            origin_run=origin_run.name if origin_run is not None else "",
            effect=effect,
        )


def _lifecycle_target_name(invocation: tuple[Path, list[str]]) -> str:
    script, args = invocation
    if script.name == "xunji_statusline.py" and "--set-active" in args:
        try:
            return Path(args[args.index("--set-active") + 1]).name
        except (ValueError, IndexError):
            return ""
    if script.name == "loop_bootstrap.py" and "--resume" in args:
        try:
            return Path(args[args.index("--resume") + 1]).name
        except (ValueError, IndexError):
            return ""
    if script.name == "loop_bootstrap.py" and "--source" in args:
        try:
            source_value = args[args.index("--source") + 1]
            source_type = args[args.index("--type") + 1] if "--type" in args else "auto"
            route = setup_source.route_source(
                source_value, source_type=source_type, runs_root=ROOT / "runs"
            )
        except (ValueError, IndexError, setup_source.SetupSourceError):
            return ""
        if route.kind == "run" and route.run_dir is not None:
            return route.run_dir.name
        if route.kind in {"json", "markdown"} and route.source_path is not None:
            if "--prepare-normalizer" in args:
                return ""
            try:
                ai_mode = args[args.index("--ai") + 1] if "--ai" in args else "off"
                provider = args[args.index("--ai-provider") + 1] \
                    if "--ai-provider" in args else ""
                model = args[args.index("--ai-model") + 1] \
                    if "--ai-model" in args else ""
                candidate_json = args[args.index("--candidate-json") + 1] \
                    if "--candidate-json" in args else None
                manifest, _raw, _artifacts = setup_normalizer.normalize_path(
                    route.source_path,
                    ai_mode=ai_mode,
                    candidate_json=candidate_json,
                    provider=provider,
                    model=model,
                )
                slug = setup_normalizer.derive_slug(manifest)
            except (ValueError, IndexError, setup_source.SetupSourceError):
                return ""
            return f"{slug}_{datetime.now().strftime('%Y%m%d')}"
        return f"{route.slug}_{datetime.now().strftime('%Y%m%d')}" if route.slug else ""
    if script.name not in {"setup_run.py", "loop_bootstrap.py"}:
        return ""
    value_options = {"--date", "--target"}
    flag_options = {"--classify"}
    positionals: list[str] = []
    date_value = datetime.now().strftime("%Y%m%d")
    index = 0
    while index < len(args):
        token = args[index]
        if token in value_options:
            if index + 1 >= len(args):
                return ""
            if token == "--date":
                date_value = args[index + 1]
            index += 2
            continue
        if token in flag_options:
            index += 1
            continue
        if token.startswith("-"):
            # Fail closed when setup/loop_bootstrap gains a new option. An
            # unknown value must never be mistaken for the run slug.
            return ""
        positionals.append(token)
        index += 1
    if not positionals:
        return ""
    slug = re.sub(r"[^A-Za-z0-9_-]", "_", positionals[0])
    return f"{slug}_{date_value}"


def _source_authority_matches(value: str, contract: dict) -> bool:
    if not value:
        return False
    digest = hashlib.sha256(value.encode("utf-8", "replace")).hexdigest()
    if "source_sha256s" in contract:
        return digest in {
            str(item) for item in (contract.get("source_sha256s") or [])
        }
    # Compatibility applies only to truly legacy contracts.  New contracts
    # always carry the field and therefore never fall back to display text.
    prompt = str(contract.get("prompt_excerpt") or "")
    loop_source = _prompt_loop_source(prompt)
    if loop_source:
        return value == loop_source
    try:
        tokens = shlex.split(prompt, comments=False, posix=True)
    except ValueError:
        tokens = prompt.split()
    return value in {str(token) for token in tokens}


def _run_name_from_path(value: str) -> str:
    text = str(value or "").strip()
    if not text or re.match(r"(?i)^[a-z][a-z0-9+.-]*://", text):
        return ""
    normalized = text.replace("\\", "/")
    if normalized.startswith("./"):
        normalized = normalized[2:]
    runs_root = RUNS.resolve()
    if normalized.startswith("runs/"):
        candidate = runs_root / normalized[len("runs/"):]
    else:
        raw = Path(text).expanduser()
        if not raw.is_absolute():
            return ""
        candidate = raw
    try:
        relative = candidate.resolve().relative_to(runs_root)
    except (OSError, ValueError):
        return ""
    if not relative.parts or not re.fullmatch(r"[A-Za-z0-9_-]+", relative.parts[0]):
        return ""
    return relative.parts[0]


def _contract_lifecycle_operation(contract: dict) -> str:
    value = str(contract.get("lifecycle_operation") or "")
    if value in {"none", "loop", "source", "resume", "setup"}:
        return value
    prompt = str(contract.get("prompt_excerpt") or "")
    loop_source = _prompt_loop_source(prompt)
    if loop_source:
        if _run_name_from_path(loop_source):
            return "resume"
        return "source"
    if re.search(r"(?:继续|恢复|续接|resume|continue)", prompt, re.I) \
            and RUN_BIND_RE.search(prompt):
        return "resume"
    return "setup" if RUN_TRANSITION_RE.search(prompt) else "none"


def _prompt_names_identifier(value: str, contract: dict) -> bool:
    if not value:
        return False
    return bool(re.search(
        rf"(?<![A-Za-z0-9_-]){re.escape(value)}(?![A-Za-z0-9_-])",
        str(contract.get("prompt_excerpt") or ""),
        re.I,
    ))


def _run_authority_matches(value: str, contract: dict, run_dir: Path) -> bool:
    target_name = _run_name_from_path(value)
    if not target_name or contract.get("run_ambiguous"):
        return False
    digest = hashlib.sha256(target_name.encode("utf-8", "replace")).hexdigest()
    if "run_name_sha256s" in contract:
        named = {
            str(item) for item in (contract.get("run_name_sha256s") or [])
        }
        if named:
            return digest in named
        return bool(
            contract.get("resume_current_approved")
            and target_name == run_dir.name
            and str(contract.get("bound_run") or "") == run_dir.name
        )
    if _prompt_names_identifier(target_name, contract):
        return True
    return bool(
        target_name == run_dir.name
        and str(contract.get("bound_run") or "") == run_dir.name
        and re.search(
            r"(?:继续|恢复|续接|resume|continue)",
            str(contract.get("prompt_excerpt") or ""), re.I,
        )
    )


def _deterministic_source_slug(value: str) -> str:
    try:
        route = setup_source.route_source(
            value, source_type="auto", runs_root=ROOT / "runs")
    except setup_source.SetupSourceError:
        return ""
    return str(route.slug or "")


def _prompt_authorizes_slug(slug: str, contract: dict) -> bool:
    if not slug:
        return False
    digest = hashlib.sha256(slug.encode("utf-8", "replace")).hexdigest()
    if "slug_sha256s" in contract:
        return bool(
            not contract.get("slug_ambiguous")
            and digest in {
                str(item) for item in (contract.get("slug_sha256s") or [])
            }
        )
    # Compatibility applies only to contracts written before slug hashes were
    # added.  New contracts never authorize from their display excerpt.
    prompt = str(contract.get("prompt_excerpt") or "")
    return bool(re.search(
        rf"(?:\bslug\b|短名|命名为|名为)\s*[:=：]?\s*{re.escape(slug)}"
        rf"(?![A-Za-z0-9_-])|setup_run\.py\s+{re.escape(slug)}"
        rf"(?![A-Za-z0-9_-])",
        prompt, re.I,
    ))


def _slug_authorized(slug: str, source: str, contract: dict) -> bool:
    if not slug:
        return False
    if "slug_sha256s" in contract and (
            contract.get("slug_ambiguous") or contract.get("slug_sha256s")):
        return _prompt_authorizes_slug(slug, contract)
    return bool(source and slug == _deterministic_source_slug(source))


def _parse_loop_source_args(args: list[str]) -> dict | None:
    value_options = {
        "--source", "--type", "--ai", "--ai-provider", "--ai-model",
        "--candidate-json",
    }
    flag_options = {"--prepare-normalizer"}
    values: dict[str, str] = {}
    flags: set[str] = set()
    index = 0
    while index < len(args):
        token = args[index]
        if token in value_options:
            if token in values or index + 1 >= len(args):
                return None
            values[token] = args[index + 1]
            index += 2
            continue
        if token in flag_options:
            if token in flags:
                return None
            flags.add(token)
            index += 1
            continue
        return None
    source = values.get("--source", "")
    source_type = values.get("--type", "auto")
    ai_mode = values.get("--ai", "off")
    provider = values.get("--ai-provider", "")
    model = values.get("--ai-model", "")
    candidate = values.get("--candidate-json", "")
    prepare = "--prepare-normalizer" in flags
    if not source or source_type not in setup_source.SUPPORTED_TYPES \
            or ai_mode not in setup_normalizer.AI_MODES:
        return None
    if ai_mode == "off":
        if provider or model or candidate or prepare:
            return None
    elif ai_mode == "external":
        if not provider or not model or prepare == bool(candidate) \
                or re.match(r"(?i)^https?://", source) or source_type == "url" \
                or re.search(r"[\x00-\x20\x7f]", provider + model):
            return None
        if candidate:
            try:
                setup_normalizer.parse_candidate(candidate)
            except setup_source.SetupSourceError:
                return None
    else:
        # No trusted local model registry exists yet.
        return None
    return {"source": source, "values": values, "flags": flags}


def _parse_setup_run_args(args: list[str]) -> dict | None:
    value_options = {"--target", "--date"}
    flag_options = {"--classify"}
    values: dict[str, str] = {}
    flags: set[str] = set()
    positionals: list[str] = []
    index = 0
    while index < len(args):
        token = args[index]
        if token in value_options:
            if token in values or index + 1 >= len(args):
                return None
            values[token] = args[index + 1]
            index += 2
            continue
        if token in flag_options:
            if token in flags:
                return None
            flags.add(token)
            index += 1
            continue
        if token.startswith("-"):
            return None
        positionals.append(token)
        index += 1
    if not 1 <= len(positionals) <= 2:
        return None
    if values.get("--date"):
        if not re.fullmatch(r"\d{8}", values["--date"]):
            return None
        try:
            datetime.strptime(values["--date"], "%Y%m%d")
        except ValueError:
            return None
    if values.get("--target") and len(positionals) != 1:
        return None
    if not values.get("--target") and len(positionals) != 2:
        return None
    return {
        "slug": positionals[0],
        "recon": positionals[1] if len(positionals) == 2 else "",
        "target": values.get("--target", ""),
        "classify": "--classify" in flags,
    }


def _canonical_effect_source(value: str, *, source_type: str = "auto") -> tuple[str, str]:
    """Return effect kind/reference using the same source router as adapters."""
    try:
        route = setup_source.route_source(
            value, source_type=source_type, runs_root=ROOT / "runs")
    except setup_source.SetupSourceError:
        return "", ""
    if route.kind == "run" and route.run_dir is not None:
        return "activate", route.run_dir.name
    if route.kind == "url":
        return "create", route.value
    if route.source_path is not None:
        return "create", str(route.source_path)
    return "", ""


def _lifecycle_transition_effect(
    invocation: tuple[Path, list[str]] | None,
    target_name: str,
) -> dict | None:
    """Project an exact accepted argv into the commit owner's effect schema."""
    if not invocation or not target_name:
        return None
    script, args = invocation
    kind = ""
    reference = ""
    profile: dict | None = None
    if script.name == "xunji_statusline.py" and len(args) == 2 \
            and args[0] == "--set-active":
        kind, reference = "activate", target_name
        profile = setup_transaction.lifecycle_effect_profile(
            setup_transaction.OP_STATUSLINE_SET_ACTIVE, target_name)
    elif script.name == "loop_bootstrap.py" and len(args) == 2 \
            and args[0] == "--resume":
        kind, reference = "activate", target_name
        profile = setup_transaction.lifecycle_effect_profile(
            setup_transaction.OP_LOOP_BOOTSTRAP_RESUME, target_name)
    elif script.name == "loop_bootstrap.py" and "--source" in args:
        parsed = _parse_loop_source_args(args)
        if parsed:
            values = parsed["values"]
            source_type = str(values.get("--type", "auto"))
            kind, reference = _canonical_effect_source(
                str(parsed["source"]),
                source_type=source_type,
            )
            if kind == "activate":
                profile = setup_transaction.lifecycle_effect_profile(
                    setup_transaction.OP_LOOP_BOOTSTRAP_RESUME, target_name)
            elif kind == "create":
                profile = setup_transaction.lifecycle_effect_profile(
                    setup_transaction.OP_LOOP_BOOTSTRAP_CREATE,
                    target_name,
                    source_type=source_type,
                    ai_mode=str(values.get("--ai", "off")),
                    provider=str(values.get("--ai-provider", "")),
                    model=str(values.get("--ai-model", "")),
                    candidate_json=values.get("--candidate-json"),
                )
    elif script.name == "loop_bootstrap.py" and len(args) == 2 \
            and not any(token.startswith("-") for token in args):
        kind, reference = _canonical_effect_source(args[1])
        if kind == "create":
            profile = setup_transaction.lifecycle_effect_profile(
                setup_transaction.OP_LOOP_BOOTSTRAP_CREATE,
                target_name,
                source_type="recon-json",
            )
    elif script.name == "setup_run.py":
        parsed = _parse_setup_run_args(args)
        if parsed:
            source = str(parsed["target"] or parsed["recon"])
            kind, reference = _canonical_effect_source(source) if source else ("", "")
            if kind == "create":
                profile = setup_transaction.lifecycle_effect_profile(
                    setup_transaction.OP_SETUP_RUN_CREATE,
                    target_name,
                    source_type="url" if parsed["target"] else "recon-json",
                    classify=bool(parsed["classify"]),
                )
    if kind == "activate" and profile:
        return setup_transaction.transition_effect(
            "activate", target_name, profile=profile)
    if kind == "create" and reference and profile:
        return setup_transaction.transition_effect(
            "create", target_name, source_reference=reference, profile=profile)
    return None


def _lifecycle_authority_reason(
    run_dir: Path,
    invocation: tuple[Path, list[str]],
    contract: dict,
) -> str:
    script, args = invocation
    if script.name not in {"setup_run.py", "loop_bootstrap.py"} \
            or ({"--selftest", "--help", "-h"} & set(args)):
        return ""
    operation = _contract_lifecycle_operation(contract)
    prefix = f"[{E_RUN_TRANSITION_AUTHORITY_MISSING}] "

    if script.name == "loop_bootstrap.py" and "--source" in args:
        parsed = _parse_loop_source_args(args)
        if not parsed:
            return prefix + "loop_bootstrap --source 必须使用唯一、受支持的精确 argv。"
        source = str(parsed["source"])
        if operation not in {"source", "resume"}:
            return prefix + "当前 prompt 未授权 source/resume lifecycle 操作。"
        if contract.get("source_ambiguous"):
            return prefix + (
                "当前 operator prompt 含多个 URL，不能猜测 lifecycle source；"
                "请用 `/loop <source>` 显式选择唯一 source。"
            )
        if not _source_authority_matches(source, contract):
            return prefix + (
                "loop_bootstrap --source 必须与当前 operator prompt 选定 source 的"
                " SHA-256 完全一致；相同 basename、不同 query 或上一回合 source 均无效。"
            )
        if operation == "resume" and not _run_authority_matches(
                source, contract, run_dir):
            return prefix + "resume source 必须绑定当前 prompt 唯一点名的 runs/<name>。"
        requested_ai = str(parsed["values"].get("--ai", "off"))
        if "ai_external_approved" in contract:
            external_approved = bool(contract.get("ai_external_approved"))
        else:
            prompt_excerpt = str(contract.get("prompt_excerpt") or "")
            external_approved = bool(
                re.search(
                    r"(?:^|\s)--ai(?:\s+|=)external(?:\s|$)",
                    prompt_excerpt, re.I)
                and not AI_EXTERNAL_DENIAL_RE.search(prompt_excerpt)
            )
        if requested_ai == "external" and not external_approved:
            return (
                "external normalizer 必须由当前操作者 prompt 显式写出 --ai external；"
                "source/模型不能自行开启模型出境。"
            )
        return ""

    if script.name == "loop_bootstrap.py" and "--resume" in args:
        if len(args) != 2 or args[0] != "--resume" or not args[1] \
                or args[1].startswith("-"):
            return prefix + "loop_bootstrap --resume 必须是唯一目标的精确 argv。"
        if operation != "resume":
            return prefix + "source/setup turn 不能改写为 resume 操作。"
        if not _run_authority_matches(args[1], contract, run_dir):
            return prefix + "resume 目标必须是当前 prompt 唯一点名的 run。"
        return ""

    if script.name == "loop_bootstrap.py":
        if len(args) != 2 or any(token.startswith("-") for token in args):
            return prefix + "legacy loop bootstrap 必须是精确的 <slug> <recon> argv。"
        slug, recon = args
        if operation not in {"source", "setup"}:
            return prefix + "resume/loop turn 不能改写为 legacy new-run 操作。"
        if contract.get("source_ambiguous") or not _source_authority_matches(
                recon, contract):
            return prefix + "legacy recon 必须与当前 prompt 选定 source 完全一致。"
        if not _slug_authorized(slug, recon, contract):
            return prefix + "legacy run slug 必须由 source 确定或由当前 prompt 点名。"
        return ""

    parsed_setup = _parse_setup_run_args(args)
    if not parsed_setup:
        return prefix + "setup_run 必须使用唯一、受支持的精确 argv。"
    if "classify_approved" in contract:
        classify_approved = bool(contract.get("classify_approved"))
    else:
        prompt_excerpt = str(contract.get("prompt_excerpt") or "")
        classify_approved = bool(
            re.search(r"(?:^|\s)--classify(?:\s|$)", prompt_excerpt, re.I)
            and not CLASSIFY_DENIAL_RE.search(prompt_excerpt)
        )
    if parsed_setup["classify"] and not classify_approved:
        return prefix + (
            "主动 classify 必须由当前 operator prompt 肯定且显式写出 --classify；"
            "否定文本不构成 opt-in。"
        )
    slug = str(parsed_setup["slug"])
    source = str(parsed_setup["target"] or parsed_setup["recon"])
    if source:
        if operation not in {"source", "setup"}:
            return prefix + "resume/loop turn 不能改写为 new-run setup 操作。"
        if contract.get("source_ambiguous") or not _source_authority_matches(
                source, contract):
            return prefix + "setup source/target 必须与当前 prompt 选定 source 完全一致。"
        if not _slug_authorized(slug, source, contract):
            return prefix + "setup run slug 必须由 source 确定或由当前 prompt 点名。"
        return ""
    if operation != "setup" or not _prompt_authorizes_slug(slug, contract):
        return prefix + "无 source 的 setup 必须由当前 prompt 同时点名 new run 与 slug。"
    return ""


def claim_transition_contract(
    target_run: Path,
    *,
    current_run: Path | None = None,
    pending_dir: Path | None = None,
    claims_dir: Path | None = None,
    transaction_id: str = "",
    source_hash: str = "",
    expected_run: str = "",
    effect: dict | None = None,
) -> dict:
    """Consume one exact active/no-active hook claim and bind the transaction.

    Claim contents still come only from PreToolUse.  Transaction callers may
    supply the mechanically derived transaction/source identity, but cannot
    supply a session, prompt hash, authority bit, or claim path.
    """
    if expected_run and expected_run != target_run.name:
        raise RuntimeError("transition claim expected run mismatch")
    if bool(transaction_id) != bool(source_hash):
        raise RuntimeError("transition claim transaction identity is incomplete")
    expected_run = expected_run or target_run.name
    if transaction_id and not re.fullmatch(r"[0-9a-f]{32}", transaction_id):
        raise RuntimeError("transition claim transaction id is invalid")
    if source_hash and not re.fullmatch(r"[0-9a-f]{64}", source_hash):
        raise RuntimeError("transition claim source hash is invalid")
    try:
        requested_effect = setup_transaction.validate_transition_effect(effect) \
            if effect is not None else None
    except ValueError as exc:
        raise RuntimeError("transition claim effect identity is invalid") from exc
    if requested_effect and requested_effect.get("target_run") != target_run.name:
        raise RuntimeError("transition claim effect target mismatch")
    directory = pending_dir or PENDING_DIR
    claim_directory = claims_dir or TRANSITION_CLAIMS_DIR
    claim_paths: list[Path] = []
    if claim_directory.is_dir():
        patterns = [_transition_claim_glob(target_run.name, requested_effect)]
        legacy_target_digest = hashlib.sha256(
            target_run.name.encode("utf-8", "replace")).hexdigest()
        patterns.append(f"{legacy_target_digest}-*.json")
        for pattern in patterns:
            for path in claim_directory.glob(pattern):
                if path not in claim_paths:
                    claim_paths.append(path)
    valid_claims: list[tuple[Path, dict]] = []
    for candidate in claim_paths:
        try:
            item = json.loads(candidate.read_text(encoding="utf-8", errors="replace"))
            item_age = time.time() - float(item.get("updated_at") or 0.0)
            item_effect = setup_transaction.validate_transition_effect(item.get("effect"))
        except Exception as exc:
            raise RuntimeError(
                "matching transition claim artifact is unreadable or invalid"
            ) from exc
        if item.get("schema") != SCHEMA \
                or item.get("target_run") != target_run.name \
                or not str(item.get("session_id") or "") \
                or item_age < 0 or item_age > PENDING_STALE_SECONDS \
                or (requested_effect is not None and item_effect != requested_effect):
            raise RuntimeError("matching transition claim artifact is stale or mismatched")
        valid_claims.append((candidate, item))
    live_claims = [
        pair for pair in valid_claims
        if str(pair[1].get("status") or "active") in {"active", "claimed"}
    ]
    revoked_claims = [
        pair for pair in valid_claims
        if str(pair[1].get("status") or "") == "revoked"
    ]
    if len(live_claims) == 1:
        valid_claims = live_claims
    elif not live_claims and revoked_claims:
        raise RuntimeError("transition claim was revoked by a newer operator prompt")
    elif valid_claims and len(live_claims) != 1:
        raise RuntimeError("multiple or invalid claims for one transition effect")
    if len(valid_claims) > 1:
        raise RuntimeError("multiple session claims for one transition effect")
    if not valid_claims:
        # A target mismatch must not turn a hook-originated command into an
        # apparently direct shell invocation.  Any fresh claim/tombstone in the
        # shared directory proves that a hook transition is still in flight.
        fresh_other_claim = False
        if claim_directory.is_dir():
            for path in claim_directory.glob("*.json"):
                try:
                    data = json.loads(path.read_text(
                        encoding="utf-8", errors="replace"))
                    age = time.time() - float(data.get("updated_at") or 0.0)
                    fresh_other_claim = fresh_other_claim or bool(
                        data.get("schema") == SCHEMA
                        and str(data.get("session_id") or "")
                        and 0 <= age <= PENDING_STALE_SECONDS
                    )
                except Exception:
                    continue
        if fresh_other_claim:
            raise RuntimeError("fresh transition claim targets a different run")
        # A normal shell/operator invocation outside Claude has neither a claim
        # nor a fresh pending contract and remains a supported local CLI path.
        fresh_pending = False
        for path in (directory.glob("*.json") if directory.is_dir() else []):
            try:
                data = json.loads(path.read_text(encoding="utf-8", errors="replace"))
                age = time.time() - float(data.get("updated_at") or 0.0)
                fresh_pending = fresh_pending or bool(
                    data.get("schema") == SCHEMA
                    and data.get("mode") == EXECUTE
                    and str(data.get("session_id") or "")
                    and 0 <= age <= PENDING_STALE_SECONDS
                )
            except Exception:
                continue
        if not fresh_pending:
            return {}
        raise RuntimeError("pending contract exists without a target claim")
    claim_path, claim = valid_claims[0]
    status = str(claim.get("status") or "active")
    if status == "revoked":
        raise RuntimeError("transition claim was revoked by a newer operator prompt")
    if status not in {"active", "claimed"} \
            or claim.get("target_run") != target_run.name:
        raise RuntimeError("invalid or mismatched transition claim")
    session_id = str(claim.get("session_id") or "")
    origin_name = str(claim.get("origin_run") or "")
    claim_effect = setup_transaction.validate_transition_effect(claim.get("effect"))
    if requested_effect is not None and claim_effect != requested_effect:
        raise RuntimeError("transition claim exact effect mismatch")
    if current_run is None:
        if origin_name:
            raise RuntimeError("no-active transition claim unexpectedly names an origin run")
        contract = load_pending_contract(session_id, pending_dir=directory)
    else:
        if origin_name != current_run.name:
            raise RuntimeError("active transition claim origin run mismatch")
        contract = load_contract(current_run, session_id=session_id)
    if not contract:
        raise RuntimeError("transition claim has no matching current contract")
    if str(contract.get("prompt_sha256") or "") != str(claim.get("prompt_sha256") or ""):
        raise RuntimeError("transition claim prompt hash mismatch")
    if not session_id:
        return {}
    claim_binding = {
        "target_run": target_run.name,
        "origin_run": origin_name,
        "session_id": session_id,
        "prompt_sha256": str(claim.get("prompt_sha256") or ""),
        "transaction_id": transaction_id,
        "source_sha256": source_hash,
        "expected_run": expected_run,
        "effect": claim_effect,
    }
    if status == "claimed":
        if claim.get("claim_binding") != claim_binding:
            raise RuntimeError("claimed transition identity cannot be changed or replayed")
        _confirm_authority_directory_chain(claim_path.parent)
    else:
        claim.update({
            "status": "claimed",
            "claim_binding": claim_binding,
            "claimed_at": time.time(),
            "updated_at": time.time(),
        })
        _atomic_json(claim_path, claim, durable=True)
    contract = dict(contract)
    contract["bound_run"] = target_run.name
    contract["transitioned_from"] = (
        current_run.name if current_run is not None else "pending:no-active-run"
    )
    if transaction_id:
        contract["transition_transaction"] = {
            "transaction_id": transaction_id,
            "source_sha256": source_hash,
            "expected_run": expected_run,
        }
    contract["transition_claim"] = claim_binding
    _atomic_json(contract_path(target_run), contract, durable=True)
    _write_run_status(target_run, contract)
    return contract


def finalize_transition_claim(
    target_run: Path,
    contract: dict,
    *,
    pending_dir: Path | None = None,
    claims_dir: Path | None = None,
) -> bool:
    """Retire one claimed/tombstoned authority after pointer commit.

    The durable target contract supplies the exact binding.  A newer prompt may
    have changed a claimed record to ``revoked`` after a post-pointer fault; the
    already-committed pointer still permits exact cleanup, never a new effect.
    """
    binding = contract.get("transition_claim")
    if not isinstance(binding, dict):
        return False
    target_name = str(binding.get("target_run") or "")
    expected_run = str(binding.get("expected_run") or "")
    session_id = str(binding.get("session_id") or "")
    prompt_sha = str(binding.get("prompt_sha256") or "")
    try:
        effect = setup_transaction.validate_transition_effect(binding.get("effect"))
    except ValueError as exc:
        raise RuntimeError("committed transition effect binding is invalid") from exc
    if target_name != target_run.name or expected_run != target_run.name \
            or not session_id or not prompt_sha:
        raise RuntimeError("committed transition claim binding is invalid")
    path = _transition_claim_path(
        target_name, session_id, effect, prompt_sha, claims_dir)
    claim_found = path.exists()
    if claim_found:
        try:
            claim = json.loads(path.read_text(
                encoding="utf-8", errors="strict"))
        except Exception as exc:
            raise RuntimeError("committed transition claim is unreadable") from exc
        if claim.get("schema") != SCHEMA \
                or str(claim.get("target_run") or "") != target_name \
                or str(claim.get("session_id") or "") != session_id \
                or str(claim.get("prompt_sha256") or "") != prompt_sha \
                or claim.get("effect") != effect \
                or claim.get("claim_binding") != binding \
                or str(claim.get("status") or "") not in {"claimed", "revoked"}:
            raise RuntimeError(
                "committed transition claim does not match its binding")
    # Even an already-missing path needs a directory fsync: the preceding
    # process may have unlinked it and failed only the deletion barrier.
    _durable_unlink(path, require_directory=True)

    pending_path = _pending_path(session_id, pending_dir)
    origin_run = str(binding.get("origin_run") or "")
    pending_directory_required = not origin_run
    if pending_path.parent.is_dir():
        if pending_path.exists():
            try:
                pending = json.loads(pending_path.read_text(
                    encoding="utf-8", errors="strict"))
            except Exception as exc:
                raise RuntimeError(
                    "matching pending transition contract is unreadable"
                ) from exc
            if str(pending.get("prompt_sha256") or "") == prompt_sha:
                _durable_unlink(pending_path, require_directory=True)
            else:
                # A newer prompt for the same session owns this path.  Preserve
                # it while confirming that the old deletion cannot resurrect.
                _confirm_authority_directory_chain(pending_path.parent)
        else:
            _durable_unlink(
                pending_path, require_directory=pending_directory_required)
    elif pending_directory_required:
        raise TransitionDurabilityError(
            "pending authority directory disappeared before durable retirement")
    return claim_found


def claim_pending_contract(
    target_run: Path,
    *,
    pending_dir: Path | None = None,
    claims_dir: Path | None = None,
    transaction_id: str = "",
    source_hash: str = "",
    expected_run: str = "",
    effect: dict | None = None,
) -> dict:
    """Compatibility wrapper for no-active-run claim consumers."""
    return claim_transition_contract(
        target_run,
        pending_dir=pending_dir,
        claims_dir=claims_dir,
        transaction_id=transaction_id,
        source_hash=source_hash,
        expected_run=expected_run,
        effect=effect,
    )


def _write_run_status(run_dir: Path, contract: dict) -> None:
    """Project a transferred/operator contract into the target run status."""
    mode = str(contract.get("mode") or "")
    now = float(contract.get("updated_at") or time.time())
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
    elif mode == MAINTENANCE:
        _atomic_json(run_status_path(run_dir), {
            "schema": SCHEMA,
            "status": "maintenance",
            "session_id": contract["session_id"],
            "updated_at": now,
            "reason": "operator requested local framework maintenance; live run is frozen",
        })


def load_contract(run_dir: Path, *, session_id: str = "") -> dict:
    try:
        data = json.loads(contract_path(run_dir).read_text(encoding="utf-8", errors="replace"))
    except Exception:
        return {}
    if data.get("schema") != SCHEMA:
        return {}
    if data.get("authority_state") == AUTHORITY_SESSION_ENDED:
        return {}
    if session_id and str(data.get("session_id") or "") != session_id:
        return {}
    try:
        if time.time() - float(data.get("updated_at") or 0) > STALE_SECONDS:
            return {}
    except Exception:
        return {}
    return data


def load_contract_for_event(run_dir: Path, event: dict) -> dict:
    """Correlate one active contract without treating session ID as a user ACL."""
    contract = load_contract(run_dir)
    if not contract:
        return {}
    contract_session = str(contract.get("session_id") or "")
    if contract_session in _event_session_candidates(event):
        return contract
    event_transcript = str(event.get("transcript_path") or "").strip()
    if event_transcript and str(contract.get("transcript_path") or "") == event_transcript:
        return contract
    if not str(event.get("session_id") or "").strip() and not event_transcript:
        # Personal-tool recovery: the only active pointer and fresh canonical
        # contract remain the causal truth when a Claude hook omits both fields.
        return contract
    return {}


def transfer_contract(
    source_run: Path,
    target_run: Path,
    *,
    transaction_id: str = "",
    source_hash: str = "",
    expected_run: str = "",
) -> dict:
    """Copy and transaction-bind the contract before a pointer switch."""
    source_run = source_run.resolve()
    target_run = target_run.resolve()
    identity_values = (transaction_id, source_hash, expected_run)
    if any(identity_values) and not all(identity_values):
        raise RuntimeError("contract transfer transaction identity is incomplete")
    if expected_run and expected_run != target_run.name:
        raise RuntimeError("contract transfer expected run mismatch")
    if transaction_id and not re.fullmatch(r"[0-9a-f]{32}", transaction_id):
        raise RuntimeError("contract transfer transaction id is invalid")
    if source_hash and not re.fullmatch(r"[0-9a-f]{64}", source_hash):
        raise RuntimeError("contract transfer source hash is invalid")
    if source_run == target_run:
        return load_contract(source_run)
    source_contract = load_contract(source_run)
    if not source_contract:
        return {}
    contract = dict(source_contract)
    contract.setdefault("origin_run", source_run.name)
    contract["bound_run"] = target_run.name
    contract["transitioned_from"] = source_run.name
    # A consumed claim belongs to the old pointer transition. Direct local
    # activation may carry the current turn contract forward, but it cannot
    # reuse that one-shot claim or its old transaction identity.
    contract.pop("transition_claim", None)
    contract.pop("transition_transaction", None)
    if transaction_id:
        contract["transition_transaction"] = {
            "transaction_id": transaction_id,
            "source_sha256": source_hash,
            "expected_run": expected_run,
        }
    _atomic_json(contract_path(target_run), contract, durable=True)
    _write_run_status(target_run, contract)
    return contract


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


def _pretool_context(message: str) -> dict:
    return {
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "additionalContext": message,
        }
    }


_EDIT_EFFECT_TOOLS = {"Write", "Edit", "Update", "MultiEdit", "NotebookEdit"}
_RUN_PROTECTED_STATE_FILES = {
    "runtime_events.jsonl", "runtime_projection_error.json",
    "runtime_projection_cursor.json", "coverage.json",
    "asset_ledger.json", ".runtime_events.lock", "loop_journal.jsonl",
    ".loop_journal.lock", "reason_pass_receipts.jsonl", ".reason_pass.lock",
    "turn_contract.json", "run_status.json", "work_plan.json",
    "work_plan_transaction.json", ".work_plan.lock", "setup_source.json",
    "setup_transaction.json", "assignments.json", "delegate_transaction.json",
    "assignment_cancellation_transaction.json",
    ".assignments.lock",
}
_RUN_PROTECTED_STATE_DIRS = {
    "work_plans", "work_plan_transactions", "assignment_cancellations",
    "merge_drafts", "merge_results",
    "scope_admissions",
}
_WORKSPACE_PROTECTED_CLAUDE_NAMES = {
    "xunji_active_run", "xunji_pending_turns", "xunji_session_selections",
    "xunji_transition_claims", "xunji_scope_admission_claims",
}


def _structured_edit_path_values(
    value: object,
    run_dir: Path | None = None,
) -> tuple[list[str], bool]:
    paths, invalid = maintenance_authority.structured_path_values(value)
    # Every direct edit tool must name at least one exact path. Empty strings,
    # empty lists, non-string members and malformed aliases stay invalid instead
    # of disappearing before the protected-path check.
    normalization_error = False
    normalized_members = 0
    for raw in paths:
        accepted = False
        roots = [ROOT]
        if run_dir is not None and run_dir.resolve(strict=False) != ROOT.resolve():
            roots.append(run_dir)
        for normalization_root in roots:
            normalized, member_errors = maintenance_authority.event_paths({
                "tool_input": {"file_path": raw},
            }, root=normalization_root)
            if normalized and not member_errors:
                accepted = True
                break
        if accepted:
            normalized_members += 1
        else:
            normalization_error = True
    return paths, bool(
        invalid or normalization_error or normalized_members != len(paths)
        or not paths
    )


def _path_views(raw: str, run_dir: Path | None) -> tuple[list[Path], bool]:
    """Return lexical and symlink-resolved views for workspace/run-relative input."""
    try:
        portable = str(raw).replace("\\", os.sep)
        path = Path(portable).expanduser()
        bases = [None] if path.is_absolute() else [ROOT]
        if not path.is_absolute() and run_dir is not None:
            bases.append(run_dir)
        views: list[Path] = []
        for base in bases:
            candidate = path if base is None else base / path
            lexical = Path(os.path.abspath(os.path.normpath(str(candidate))))
            resolved = candidate.resolve(strict=False)
            for view in (lexical, resolved):
                if view not in views:
                    views.append(view)
        return views, False
    except (OSError, RuntimeError, ValueError):
        return [], True


def _relative_if_within(path: Path, parent: Path) -> Path | None:
    try:
        return path.relative_to(parent)
    except ValueError:
        return None


def _protected_run_relative(rel: Path) -> bool:
    parts = [part.lower() for part in rel.parts if part not in {"", "."}]
    if not parts:
        return False
    if parts[-1] == "coverage.json":
        return True
    if ".xunji_staging" in parts or "scope_admissions" in parts:
        return True
    # setup_source.py owns the complete frozen bundle at run-root/sources/*.
    # Direct Edit/Write must not mutate normalized input, validator receipts,
    # model-normalizer request/candidate records, or original snapshots.
    if parts[0] == "sources":
        return True
    if any(re.fullmatch(r"\.xunji_(?:activation|setup|scope_admission)\.lock", part)
           for part in parts):
        return True
    if parts[0] != "state" or len(parts) < 2:
        return False
    state_rel = parts[1:]
    if state_rel[0] in _RUN_PROTECTED_STATE_FILES \
            or state_rel[0] in _RUN_PROTECTED_STATE_DIRS:
        return True
    if state_rel[0] == "sources" and len(state_rel) >= 2:
        return state_rel[1] in {"normalized.json", "validator_receipt.json", "original"}
    return False


def _structured_path_is_protected(raw: str, run_dir: Path | None) -> tuple[bool, bool]:
    views, invalid = _path_views(raw, run_dir)
    if invalid:
        return False, True
    configured_exact: set[Path] = set()
    configured_trees: set[Path] = set()
    for configured in (ACTIVE_RUN_POINTER,):
        configured_views, configured_invalid = _path_views(str(configured), None)
        if configured_invalid:
            return False, True
        configured_exact.update(configured_views)
    for configured in (
            PENDING_DIR, TRANSITION_CLAIMS_DIR, SESSION_SELECTION_DIR,
            scope_admission.CLAIMS_DIR):
        configured_views, configured_invalid = _path_views(str(configured), None)
        if configured_invalid:
            return False, True
        configured_trees.update(configured_views)
    workspace_views = {ROOT.resolve(strict=False), Path(os.path.abspath(str(ROOT)))}
    run_views: set[Path] = set()
    if run_dir is not None:
        run_views.update({
            run_dir.resolve(strict=False), Path(os.path.abspath(str(run_dir))),
        })
    runs_views = {RUNS.resolve(strict=False), Path(os.path.abspath(str(RUNS)))}
    for view in views:
        if view in configured_exact:
            return True, False
        if any(_relative_if_within(view, parent) is not None
               for parent in configured_trees):
            return True, False
        for current_run in run_views:
            rel = _relative_if_within(view, current_run)
            if rel is not None and _protected_run_relative(rel):
                return True, False
        for runs_root in runs_views:
            rel = _relative_if_within(view, runs_root)
            if rel is not None and len(rel.parts) >= 2 \
                    and _protected_run_relative(Path(*rel.parts[1:])):
                return True, False
        for workspace in workspace_views:
            rel = _relative_if_within(view, workspace)
            if rel is None:
                continue
            parts = [part.lower() for part in rel.parts]
            if len(parts) >= 2 and parts[0] == ".claude" \
                    and parts[1] in _WORKSPACE_PROTECTED_CLAUDE_NAMES:
                return True, False
            if len(parts) >= 2 and parts[0] == "review" and parts[1] == "receipts":
                return True, False
            if ".xunji_staging" in parts:
                return True, False
    return False, False


def _protected_control_reason(event: dict, run_dir: Path | None = None) -> str:
    tool = str(event.get("tool_name") or "")
    if tool not in {*_EDIT_EFFECT_TOOLS, "Bash"}:
        return ""
    if tool == "Bash":
        # Bash is classified later by the parsed capability/command-shape
        # boundary. Preserve the established exact deny surface here; do not
        # infer filesystem effects by recursively regex-scanning shell text.
        protected = bool(PROTECTED_RUNTIME_RE.search(_tool_text(event)))
        invalid = False
    else:
        tool_input = event.get("tool_input") \
            if isinstance(event.get("tool_input"), dict) else {}
        path_values, invalid = _structured_edit_path_values(tool_input, run_dir)
        protected = False
        for raw in path_values:
            matched, path_invalid = _structured_path_is_protected(raw, run_dir)
            protected = protected or matched
            invalid = invalid or path_invalid
    if protected:
        return (
            "active-run 指针、pending contract、运行时回执、资产账本和回合状态只能由"
            "受控工具/hook 原子写入；Claude 不得直接修改这些控制面文件。"
        )
    if invalid:
        return "编辑工具 path 参数无法安全归一化；控制面路径检查按 fail-closed 拒绝。"
    return ""


PRIVATE_LIFECYCLE_API_RE = re.compile(
    r"\bsetup_transaction\s*\.\s*"
    r"(?:create_and_activate|commit_activation_cas|restore_session_activation_cas|"
    r"clear_activation_cas)\s*\(",
    re.I,
)


def _private_lifecycle_api_reason(event: dict) -> str:
    """Keep Claude on public lifecycle adapters after a recoverable denial."""
    if str(event.get("tool_name") or "") != "Bash":
        return ""
    tool_input = event.get("tool_input") \
        if isinstance(event.get("tool_input"), dict) else {}
    command = str(tool_input.get("command") or "")
    if not PRIVATE_LIFECYCLE_API_RE.search(command):
        return ""
    return (
        f"[{E_LIFECYCLE_PRIVATE_API}] Claude 主驾驶不得用 python -c/stdin/import "
        "直接调用 setup_transaction 私有事务 API。该 API 是状态一致性 owner，不是"
        "拒绝后的备用入口；请修正并精确重试 loop_bootstrap.py、setup_run.py 或"
        "其他 lifecycle owner 文档公开的 typed adapter。"
    )


def _local_pycompile_bash(command: str) -> bool:
    """Accept direct trusted-interpreter py_compile for repository-local files."""
    if _has_unquoted_shell_control(command):
        return False
    try:
        tokens = shlex.split(command, posix=True)
    except ValueError:
        return False
    if len(tokens) < 4 or not trusted_python_token(tokens[0]):
        return False
    if tokens[1:3] != ["-m", "py_compile"]:
        return False
    for raw in tokens[3:]:
        if raw.startswith("-"):
            return False
        candidate = Path(raw)
        if not candidate.is_absolute():
            candidate = ROOT / candidate
        try:
            candidate.resolve(strict=False).relative_to(ROOT.resolve())
        except ValueError:
            return False
        if candidate.suffix != ".py":
            return False
    return True


def _registered_capability_invocation(
    command: str,
    *,
    tool_env: dict | None = None,
) -> tuple[
    capability_registry.CapabilitySpec, Path, list[str], dict[str, str]
] | None:
    """Resolve one exact Python argv through the typed capability registry."""
    explicit_env = {
        str(key): str(value) for key, value in (tool_env or {}).items()
    }
    raw_candidate = str(command or "").strip()
    candidate = normalize_local_setup_command(raw_candidate)
    if candidate != raw_candidate \
            and local_setup_metadata_invocation(candidate, root=ROOT) is None:
        candidate = raw_candidate
    # Shell redirects are never part of a typed capability.  In particular,
    # peer_review already has --out/--json-out; stripping a redirect before
    # parsing would hide shell metacharacters and an unbound write target.
    if _has_unquoted_shell_control(candidate):
        return None
    invocation = parse_exact_python_command(
        candidate, root=ROOT,
        allowed_scripts=REGISTERED_CAPABILITY_SCRIPTS,
        allow_environment=True,
    )
    if invocation is None:
        return None
    inline_env: dict[str, str] = {}
    for assignment in invocation.environment:
        key, value = assignment.split("=", 1)
        if key in inline_env:
            return None
        inline_env[key] = value
    if explicit_env and inline_env:
        return None
    spec = capability_registry.match(
        invocation.script, invocation.args, root=ROOT,
    )
    if spec is None:
        return None
    supplied_env = explicit_env or inline_env
    if not set(supplied_env) <= set(spec.allowed_env):
        return None
    if any(
        "\x00" in value or "\n" in value or "\r" in value
        or len(value.encode("utf-8", "replace")) > 8192
        for value in supplied_env.values()
    ):
        return None
    return spec, invocation.script, list(invocation.args), supplied_env


def _diagnostic_registered_environment_allowed(
    invocation: PythonControlInvocation,
) -> bool:
    """Keep known-script argv mistakes out of the maintenance classifier.

    Matching a typed capability still requires valid argv.  This helper grants
    no capability; it only recognizes that inline environment assignments use
    keys declared by some capability for the exact registered script, so an
    argv typo can receive a retryable shape diagnostic instead of being
    mislabeled as a source-code mutation.
    """
    supplied: dict[str, str] = {}
    for assignment in invocation.environment:
        if "=" not in assignment:
            return False
        key, value = assignment.split("=", 1)
        if key in supplied or "\x00" in value or "\n" in value or "\r" in value \
                or len(value.encode("utf-8", "replace")) > 8192:
            return False
        supplied[key] = value
    if not supplied:
        return True
    allowed: set[str] = set()
    try:
        resolved = invocation.script.resolve(strict=True)
    except (OSError, RuntimeError, ValueError):
        return False
    for spec in capability_registry.CAPABILITIES:
        try:
            if spec.path(ROOT) == resolved:
                allowed.update(spec.allowed_env)
        except (OSError, RuntimeError, ValueError):
            continue
    return bool(allowed) and set(supplied) <= allowed


def _capability_data_critical_paths(
    capability: tuple[
        capability_registry.CapabilitySpec, Path, list[str], dict[str, str]
    ],
) -> list[str]:
    """Return protected paths named by capability data, excluding its executable."""
    _spec, _script, args, _env = capability
    return _argv_data_critical_paths(args)


def _argv_data_critical_paths(args: list[str] | tuple[str, ...]) -> list[str]:
    """Return protected paths named by argv data, excluding the executable."""
    return maintenance_authority.critical_paths_for_event({
        "tool_name": "Bash",
        "tool_input": {"command": shlex.join(args)},
    })


def _capability_path(value: str) -> Path | None:
    raw = str(value or "").strip()
    if not raw or re.match(r"(?i)^[a-z][a-z0-9+.-]*://", raw):
        return None
    candidate = Path(raw)
    if not candidate.is_absolute():
        candidate = ROOT / candidate
    try:
        return candidate.resolve(strict=False)
    except (OSError, RuntimeError, ValueError):
        return None


def _path_within(path: Path, parent: Path) -> bool:
    try:
        path.resolve(strict=False).relative_to(parent.resolve(strict=False))
        return True
    except (OSError, RuntimeError, ValueError):
        return False


def _capability_policy_reason(
    run_dir: Path,
    capability: tuple[
        capability_registry.CapabilitySpec, Path, list[str], dict[str, str]
    ] | None,
) -> str:
    """Enforce declared scope/service policies against normalized resources."""
    if capability is None:
        return ""
    spec, _script, args, _env = capability
    if spec.effect == "target" and (
        spec.scope != "target_assets" or spec.privacy != "target_egress"
        or spec.proxy != "engagement" or spec.guard != "target"
        or spec.recorder != "target_artifact"
    ):
        return f"[{E_CAPABILITY_POLICY}] target capability policy bundle is incomplete."
    if spec.effect == "model_egress" and (
        spec.scope != "review_scope" or spec.privacy != "model_egress"
        or spec.recorder != "review_receipt"
    ):
        return f"[{E_CAPABILITY_POLICY}] model-egress capability policy bundle is incomplete."
    if spec.effect == "control" and spec.recorder == "none":
        return f"[{E_CAPABILITY_POLICY}] control capability lacks a recorder policy."

    run_ref = capability_registry.run_reference(spec, args)
    resolved_run_ref = _capability_path(run_ref) if run_ref else None
    if spec.scope in {"active_run", "review_scope"}:
        output_bound_only = spec.argv_validator == "ingest-write"
        if not output_bound_only and (
                resolved_run_ref is None
                or resolved_run_ref != run_dir.resolve(strict=False)):
            return (
                f"[{E_CAPABILITY_POLICY}] capability {spec.id} must bind the exact "
                f"active run {run_dir.name}."
            )
    elif spec.scope == "target_assets" and resolved_run_ref is not None \
            and resolved_run_ref != run_dir.resolve(strict=False):
        return (
            f"[{E_CAPABILITY_POLICY}] target capability {spec.id} names a different run."
        )

    if spec.argv_validator in {"replay-live", "replay-force"} and args:
        replay_path = _capability_path(args[0])
        if replay_path is None or not _path_within(replay_path, run_dir):
            return (
                f"[{E_CAPABILITY_POLICY}] replay input must be the active run or one "
                "of its recorded replay artifacts."
            )
    outputs = capability_registry.output_references(spec, args)
    for raw in outputs:
        output = _capability_path(raw)
        bare_under_run = bool(
            run_ref and resolved_run_ref == run_dir.resolve(strict=False)
            and "/" not in raw and "\\" not in raw
            and spec.argv_validator in {
                "probe-live", "render-live", "render-eval",
            }
        )
        if not bare_under_run and (
                output is None or not _path_within(output, run_dir)):
            return (
                f"[{E_CAPABILITY_POLICY}] capability {spec.id} output must stay "
                "inside the active run."
            )
    if spec.argv_validator == "rerun-deferred" and "--coverage" in args:
        try:
            coverage = _capability_path(args[args.index("--coverage") + 1])
        except (ValueError, IndexError):
            coverage = None
        if coverage is None or not _path_within(coverage, run_dir):
            return (
                f"[{E_CAPABILITY_POLICY}] deferred coverage mutation must stay "
                "inside the active run."
            )
    return ""


def _local_verification_bash(command: str) -> bool:
    """Allow one exact audited local regression command, never a shell wrapper."""
    if _local_pycompile_bash(command):
        return True
    invocation = _registered_capability_invocation(command)
    return bool(invocation and invocation[0].effect == "local_verify")


def _trusted_critical_execution_bash(
    command: str,
    *,
    tool_env: dict | None = None,
) -> bool:
    """Distinguish running an audited project entrypoint from modifying its source."""
    capability = _registered_capability_invocation(
        command, tool_env=tool_env)
    return bool(capability and not _capability_data_critical_paths(capability))


def _audited_bash_execution(event: dict) -> bool:
    """Allow only explicit Bash capabilities; unknown local shell is write-capable."""
    tool_input = event.get("tool_input") if isinstance(event.get("tool_input"), dict) else {}
    command = str(tool_input.get("command") or "")
    tool_env = tool_input.get("env") if isinstance(tool_input.get("env"), dict) else {}
    if not tool_env and _readonly_shell(command):
        return True
    return _trusted_critical_execution_bash(command, tool_env=tool_env)


def _maintenance_pretool_reason(event: dict, contract: dict) -> str:
    """Keep an intent-derived maintenance turn local and auditable."""
    tool = str(event.get("tool_name") or "")
    tool_input = event.get("tool_input") if isinstance(event.get("tool_input"), dict) else {}
    command = str(tool_input.get("command") or "")
    readonly_tools = {"Read", "Grep", "Glob"}
    if tool in readonly_tools:
        return ""
    if tool in {"CronCreate", "CronDelete", "CronList", "Agent", "WebFetch", "WebSearch"}:
        return "框架维护回合禁止 target/network action、Agent 与 Cron；本回合只做本地精确路径维护。"
    if tool != "Bash" and _is_target_action(event):
        return "框架维护回合禁止 target/network action、Agent 与 Cron；本回合只做本地精确路径维护。"
    if tool in maintenance_authority.WRITE_TOOLS:
        paths, invalid = maintenance_authority.event_paths(event)
        if invalid or not paths:
            return "框架维护写工具必须提供可规范化的 repository-local exact file path。"
        forbidden = sorted(
            path for path in paths if not maintenance_authority.path_allowed(path)
        )
        if forbidden:
            return (
                "框架维护不得直接写 live-run、Git 或控制状态路径: "
                + ", ".join(forbidden)
            )
        return ""
    if tool == "Bash":
        tool_env = tool_input.get("env") if isinstance(tool_input.get("env"), dict) else {}
        if tool_env:
            return (
                "框架维护 Bash 禁止工具级环境覆盖；PYTHONPATH/Git 外部 helper 等变量会"
                "破坏本地只读/验证命令的确定性。"
            )
        if _readonly_shell(command) or _local_verification_bash(command):
            return ""
        if _event_destinations(event):
            return "框架维护回合禁止 target/network action、Agent 与 Cron；本回合只做本地精确路径维护。"
        critical = maintenance_authority.critical_paths_for_event(event)
        if critical:
            return (
                "框架维护禁止用 Bash 直接改安全关键文件；请用可审计的 Edit/Write: "
                + ", ".join(critical)
            )
        return "框架维护 Bash 仅允许只读命令或审计过的单一 selftest/check 命令；禁止目标动作和任意 shell 写入。"
    return f"框架维护回合不允许工具 {tool or '(unknown)'}；只允许读取、精确 Edit/Write 和本地验证。"


def _maintenance_event_paths(event: dict) -> list[str]:
    tool = str(event.get("tool_name") or "")
    if tool in maintenance_authority.WRITE_TOOLS:
        paths, _ = maintenance_authority.event_paths(event)
        return paths
    return maintenance_authority.critical_paths_for_event(event)


def _maintenance_receipt_paths(event: dict, contract: dict | None = None) -> list[str]:
    # Bind only the canonical paths extracted from this exact effect. Contract
    # scope is authority, not evidence that every authorized file was touched.
    # The same helper is used by authorization, PreToolUseDenied, PostToolUse and
    # PostToolUseFailure so outcome cannot change the receipt path set.
    return sorted({path for path in _maintenance_event_paths(event) if path})


_ROOT_CANONICAL_MUTATION_FILES = {
    "chains.md", "decisions.md", "evidence.md", "false_positive.md",
    "findings.md", "frontier.md", "report.md", "review.md",
}


def _root_canonical_mutation_paths(run_dir: Path, event: dict) -> list[str]:
    """Return canonical run files directly targeted by a Root edit tool."""
    if str(event.get("tool_name") or "") not in maintenance_authority.WRITE_TOOLS:
        return []
    found: set[str] = set()
    for base in (ROOT, run_dir):
        paths, invalid = maintenance_authority.event_paths(event, root=base)
        if invalid:
            continue
        for path in paths:
            normalized = str(path).replace("\\", "/")
            if normalized in _ROOT_CANONICAL_MUTATION_FILES:
                found.add(normalized)
                continue
            prefix = f"runs/{run_dir.name}/"
            if normalized.startswith(prefix):
                relative = normalized[len(prefix):]
                if relative in _ROOT_CANONICAL_MUTATION_FILES:
                    found.add(relative)
    return sorted(found)


def _reviewed_unsettled_assignments(run_dir: Path) -> tuple[list[str], str]:
    """Find execution results reviewed but not yet disposed by Root."""
    path = run_dir / "state" / "assignments.json"
    if not path.exists():
        return [], ""
    try:
        data = json.loads(path.read_text(encoding="utf-8", errors="strict"))
        rows = data.get("assignments") if isinstance(data, dict) else None
        if not isinstance(rows, list):
            raise ValueError("assignments is not a list")
    except Exception as exc:
        return [], f"assignment state unreadable: {type(exc).__name__}"
    reviewed_targets = {
        str(target)
        for row in rows if isinstance(row, dict)
        and str(row.get("role") or "") == "review"
        and str(row.get("status") or "").strip().lower() == "reviewed"
        for target in row.get("reviews_assignments", [])
        if str(target)
    }
    pending = sorted({
        str(row.get("agent") or "")
        for row in rows if isinstance(row, dict)
        and str(row.get("agent") or "") in reviewed_targets
        and str(row.get("role") or "") != "review"
        and str(row.get("status") or "").strip().lower() == "done"
    } - {""})
    return pending, ""


def _root_settlement_reason(run_dir: Path, event: dict) -> str:
    """Keep review -> Root disposition -> canonical promotion in one order."""
    if str(event.get("agent_id") or "").strip():
        return ""
    paths = _root_canonical_mutation_paths(run_dir, event)
    if not paths:
        return ""
    pending, error = _reviewed_unsettled_assignments(run_dir)
    if error:
        return f"[{E_ROOT_SETTLEMENT_REQUIRED}] {error}; canonical mutation denied."
    if not pending:
        return ""
    return (
        f"[{E_ROOT_SETTLEMENT_REQUIRED}] review-disposition 已冻结，先对 "
        f"{', '.join(pending)} 执行 workers.py finish（按证据选择 merged/blocked/"
        f"failed/abandoned），再修改 {', '.join(paths)}；Reviewer 接受候选不等于 finding。"
    )


def _shell_command_names(command: str, *, _depth: int = 0) -> list[str]:
    """Return executable basenames from actual shell command positions only."""
    if _depth > 2:
        return []
    try:
        lexer = shlex.shlex(command, posix=True, punctuation_chars=";&|<>")
        lexer.whitespace_split = True
        lexer.commenters = ""
        tokens = list(lexer)
    except ValueError:
        return []

    separators = {";", "&&", "||", "|", "&"}
    segments: list[list[str]] = []
    current: list[str] = []
    for token in tokens:
        if token in separators:
            if current:
                segments.append(current)
                current = []
            continue
        current.append(token)
    if current:
        segments.append(current)

    names: list[str] = []
    for segment in segments:
        # Redirection operators and their operands are data for effect
        # classification, never command positions.
        command_tokens: list[str] = []
        skip_redirection_target = False
        for token in segment:
            if skip_redirection_target:
                skip_redirection_target = False
                continue
            if token in {"<", ">", ">>", "<<", "<<<", "<>"}:
                skip_redirection_target = True
                continue
            if re.fullmatch(r"[0-9]*(?:<|>|>>|<<|<<<|<>)", token):
                skip_redirection_target = True
                continue
            command_tokens.append(token)
        if not command_tokens:
            continue

        index = 0
        while index < len(command_tokens) and ENV_ASSIGNMENT_TOKEN_RE.fullmatch(
                command_tokens[index]):
            index += 1
        if index >= len(command_tokens):
            continue
        name = Path(command_tokens[index]).name.lower()
        if name == "env":
            index += 1
            while index < len(command_tokens):
                token = command_tokens[index]
                if token == "--":
                    index += 1
                    break
                if token in {"-u", "--unset", "-C", "--chdir"}:
                    index += 2
                    continue
                if token.startswith(("--unset=", "--chdir=")) \
                        or token.startswith("-") \
                        or ENV_ASSIGNMENT_TOKEN_RE.fullmatch(token):
                    index += 1
                    continue
                break
            if index >= len(command_tokens):
                continue
            name = Path(command_tokens[index]).name.lower()
        wrapper_only = False
        while name in {"command", "exec"}:
            wrapper = name
            names.append(wrapper)
            index += 1
            while index < len(command_tokens):
                token = command_tokens[index]
                if token == "--":
                    index += 1
                    break
                if wrapper == "command" and token in {"-v", "-V"}:
                    wrapper_only = True
                    break
                if wrapper == "exec" and token == "-a":
                    index += 2
                    continue
                if token.startswith("-"):
                    index += 1
                    continue
                break
            if wrapper_only or index >= len(command_tokens):
                break
            name = Path(command_tokens[index]).name.lower()
        if wrapper_only or index >= len(command_tokens):
            continue
        names.append(name)
        if name in {"sh", "bash", "zsh", "dash", "ksh"}:
            shell_args = command_tokens[index + 1:]
            for arg_index, token in enumerate(shell_args[:-1]):
                if token in {"-c", "-lc", "-cl"}:
                    names.extend(_shell_command_names(
                        shell_args[arg_index + 1], _depth=_depth + 1))
                    break
    return names


def _opaque_repo_mutation_bash(command: str) -> bool:
    """Treat an executed non-readonly Git/patch command as repository mutation."""
    if _readonly_shell(command):
        return False
    return bool({"git", "patch"} & set(_shell_command_names(command)))


def _critical_maintenance_reason(event: dict) -> str:
    """Keep framework mutation out of a live execution turn."""
    tool = str(event.get("tool_name") or "")
    tool_input = event.get("tool_input") if isinstance(event.get("tool_input"), dict) else {}
    command = str(tool_input.get("command") or "")
    if tool not in maintenance_authority.WRITE_TOOLS | {"Bash"}:
        return ""
    if tool == "Bash" and _opaque_repo_mutation_bash(command):
        return (
            "live run 回合不允许用不透明仓库命令修改或暂存框架；"
            "请在新的顶层 prompt 直接说明要修复/修改的 Xunji 框架问题。"
        )
    critical = maintenance_authority.critical_paths_for_event(event)
    if not critical:
        return ""
    tool_env = tool_input.get("env") if isinstance(tool_input.get("env"), dict) else {}
    if tool == "Bash" and (
            (not tool_env and _readonly_shell(command))
            or _trusted_critical_execution_bash(command, tool_env=tool_env)):
        return ""
    return (
        "live run 回合不修改安全关键框架路径；请在新的顶层 prompt 直接说明"
        "要修复/修改的 Xunji 框架问题。涉及: " + ", ".join(critical)
    )


def _maintenance_action(event: dict, *, contract: dict | None = None) -> bool:
    """Classify maintenance from typed effect/paths, never denial prose."""
    tool = str(event.get("tool_name") or "")
    if contract and contract.get("mode") == MAINTENANCE \
            and tool not in {"Read", "Grep", "Glob"}:
        return True
    if tool in maintenance_authority.WRITE_TOOLS:
        return bool(maintenance_authority.critical_paths_for_event(event))
    if tool == "Bash":
        command = str((event.get("tool_input") or {}).get("command") or "") \
            if isinstance(event.get("tool_input"), dict) else ""
        tool_input = event.get("tool_input") \
            if isinstance(event.get("tool_input"), dict) else {}
        tool_env = tool_input.get("env") \
            if isinstance(tool_input.get("env"), dict) else {}
        # Git/patch mutation is a typed repository-maintenance effect even when
        # its command omits an explicit critical path.  Other unknown shell is
        # still denied by evaluate_pretool, but denial guidance mentioning
        # /xunji-maintenance cannot itself mint maintenance truth.
        command_names = set(_shell_command_names(command))
        if ({"git", "patch"} & command_names) and (
                tool_env or _opaque_repo_mutation_bash(command)):
            return True
        if not maintenance_authority.critical_paths_for_event(event):
            return False
        capability = _registered_capability_invocation(
            command, tool_env=tool_env)
        if capability is not None \
                and capability[0].effect != "repo_mutation" \
                and not _capability_data_critical_paths(capability):
            return False
        return not (_readonly_shell(command) or _local_verification_bash(command))
    return False


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


def _safe_git_read(tokens: list[str]) -> bool:
    """Allow repository inspection but no index/worktree/ref mutation."""
    if len(tokens) < 2:
        return False
    if tokens[1] not in {
        "diff", "status", "show", "log", "rev-parse", "ls-files",
    }:
        return False
    if any(
        token in {"--ext-diff", "--textconv"}
        or token.startswith("--output")
        for token in tokens[2:]
    ):
        return False
    if tokens[1] in {"diff", "show", "log"}:
        return "--no-ext-diff" in tokens[2:] and "--no-textconv" in tokens[2:]
    return True


def _safe_rg_read(tokens: list[str]) -> bool:
    """Reject ripgrep options that can launch preprocess/decompression commands."""
    return not any(
        token in {"--pre", "--pre-glob"}
        or token.startswith("--pre=")
        or token.startswith("--pre-glob=")
        or token == "--hostname-bin"
        or token.startswith("--hostname-bin=")
        or token == "--search-zip"
        or bool(re.fullmatch(r"-[^-]*z[^-]*", token))
        for token in tokens[1:]
    )


def _safe_shasum_read(tokens: list[str]) -> bool:
    """Allow only the macOS SHA-256 file-read form used for local diagnostics."""
    return (
        len(tokens) >= 4
        and tokens[1:3] == ["-a", "256"]
        and all(token and not token.startswith("-") for token in tokens[3:])
    )


def _readonly_shell(command: str) -> bool:
    """Allow a narrow shell read grammar without splitting quoted punctuation."""
    if not command.strip() or re.search(r"`|\$\(|\$\{|\n|\r|\x00", command):
        return False
    try:
        lexer = shlex.shlex(
            command, posix=True, punctuation_chars="<>|&;",
        )
        lexer.whitespace_split = True
        lexer.commenters = ""
        raw_tokens = list(lexer)
    except ValueError:
        return False
    segments: list[list[str]] = []
    current: list[str] = []
    index = 0
    while index < len(raw_tokens):
        if raw_tokens[index:index + 3] == ["2", ">", "/dev/null"]:
            index += 3
            continue
        token = raw_tokens[index]
        if token in {"&&", "||", ";", "|"}:
            if not current:
                return False
            segments.append(current)
            current = []
            index += 1
            continue
        if token and all(char in "<>|&;" for char in token):
            return False
        current.append(token)
        index += 1
    if not current:
        return False
    segments.append(current)
    allowed = {
        "cat", "head", "tail", "grep", "rg", "ls", "stat", "file", "wc",
        "find", "sed", "sort", "git", "shasum", "echo",
    }
    for tokens in segments:
        if not tokens:
            return False
        # The launcher may resolve a trusted bare helper from PATH, but a path
        # spelling would let `/tmp/cat` or `./git` impersonate the allowlist by
        # basename before the shell executes an unrelated file.
        executable = tokens[0]
        if executable not in allowed:
            return False
        if executable == "rg" and not _safe_rg_read(tokens):
            return False
        if executable == "sed" and not _safe_sed(tokens):
            return False
        if executable == "git" and not _safe_git_read(tokens):
            return False
        if executable == "shasum" and not _safe_shasum_read(tokens):
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


def _control_invocation(command: str) -> tuple[Path, list[str]] | None:
    """Parse one exact in-repo Python control command."""
    invocation = _registered_capability_invocation(command)
    if invocation is None or invocation[0].effect not in {"local_read", "control"}:
        return None
    return invocation[1], invocation[2]


def _lifecycle_invocation(
    command: str, *, tool_env: dict | None = None,
) -> tuple[Path, list[str]] | None:
    """Return exact lifecycle argv even when that mode has target effect."""
    capability = _registered_capability_invocation(
        command, tool_env=tool_env)
    if capability is None or capability[1] not in LIFECYCLE_SCRIPTS:
        return None
    return capability[1], capability[2]


def _python_control_hint(script: Path, args: list[str]) -> str:
    """Render a copy-safe trusted-interpreter argv hint without executing it."""
    interpreter = Path(sys.executable).resolve()
    return " ".join(shlex.quote(str(token)) for token in (
        interpreter, script.resolve(), *args,
    ))


def _clear_active_reason(invocation: tuple[Path, list[str]] | None) -> str:
    """Deny pointer clearing as an unowned lifecycle escape hatch."""
    if invocation and invocation[0].name == "xunji_statusline.py" \
            and "--clear-active" in invocation[1]:
        return (
            f"[{E_CLEAR_ACTIVE_FORBIDDEN}] active-run 指针不得由 Claude Code "
            "hook 回合清空；请使用受控 setup/resume/set-active 完成事务化 run 转换。"
        )
    return ""


def _registered_capability_shape_issue(
    event: dict,
) -> PythonControlShapeIssue | None:
    """Diagnose a registered-script shape without converting it to authority.

    The stable error code predates the typed capability registry and retains its
    lifecycle name for receipt compatibility.  The diagnostic boundary covers
    every registered Python script in two non-authorizing cases:

    * a literal ``&&`` chain whose executable segments are exact registered
      capabilities (with optional display-only ``echo`` segments), excluding
      repository mutation and safety-critical data paths;
    * an observational ``2>&1``/``head``/``tail`` wrapper; and
    * one clean exact invocation whose argv matches no registered capability.

    In both cases PreToolUse still denies execution.  The distinction only keeps
    a retryable command-shape error from becoming a false framework-maintenance
    claim merely because the audited entrypoint itself is safety-critical.
    """
    if str(event.get("tool_name") or "") != "Bash":
        return None
    tool_input = event.get("tool_input") if isinstance(event.get("tool_input"), dict) else {}
    command = str(tool_input.get("command") or "")
    if _registered_capability_invocation(command) is not None:
        return None
    chain = _registered_capability_chain(event)
    if chain is not None:
        first_invocation = chain[0][1]
        segments = split_literal_and_chain(command) or ()
        has_passive_segment = any(
            _diagnostic_passive_chain_segment(
                shlex.split(segment, comments=False, posix=True))
            for segment in segments
        )
        return PythonControlShapeIssue(
            code=E_LIFECYCLE_EXACT_ARGV_REQUIRED,
            category=("registered-chain-passive" if has_passive_segment
                      else "registered-chain"),
            script=first_invocation.script,
            args=first_invocation.args,
        )
    invalid_chain = _registered_capability_chain_details(
        event, allow_invalid=True)
    if invalid_chain is not None and invalid_chain[1]:
        capabilities, invalid_invocations = invalid_chain
        first_invocation = (
            capabilities[0][1] if capabilities else invalid_invocations[0])
        return PythonControlShapeIssue(
            code=E_LIFECYCLE_EXACT_ARGV_REQUIRED,
            category="registered-chain-invalid-argv",
            script=first_invocation.script,
            args=first_invocation.args,
        )
    issue = diagnose_python_control_shape(
        command,
        root=ROOT,
        allowed_scripts=REGISTERED_CAPABILITY_SCRIPTS,
    )
    if issue is not None:
        if capability_registry.match(issue.script, issue.args, root=ROOT) is not None:
            return issue
        return PythonControlShapeIssue(
            code=E_LIFECYCLE_EXACT_ARGV_REQUIRED,
            category="invalid-argv-" + issue.category,
            script=issue.script,
            args=issue.args,
        )

    invocation = parse_exact_python_command(
        command,
        root=ROOT,
        allowed_scripts=REGISTERED_CAPABILITY_SCRIPTS,
        allow_environment=True,
    )
    if invocation is None \
            or not _diagnostic_registered_environment_allowed(invocation):
        return None
    if capability_registry.match(
            invocation.script, invocation.args, root=ROOT) is not None:
        return None
    return PythonControlShapeIssue(
        code=E_LIFECYCLE_EXACT_ARGV_REQUIRED,
        category="invalid-argv",
        script=invocation.script,
        args=invocation.args,
    )


def _registered_capability_chain(
    event: dict,
) -> tuple[tuple[
    capability_registry.CapabilitySpec, PythonControlInvocation, str,
], ...] | None:
    """Resolve a diagnostic-only chain without granting any segment authority."""
    details = _registered_capability_chain_details(event, allow_invalid=False)
    return details[0] if details is not None else None


def _registered_capability_chain_details(
    event: dict, *, allow_invalid: bool,
) -> tuple[
    tuple[tuple[
        capability_registry.CapabilitySpec, PythonControlInvocation, str,
    ], ...],
    tuple[PythonControlInvocation, ...],
] | None:
    """Parse known-script chain segments for non-authorizing diagnostics."""
    if str(event.get("tool_name") or "") != "Bash":
        return None
    tool_input = event.get("tool_input") \
        if isinstance(event.get("tool_input"), dict) else {}
    raw_env = tool_input.get("env") if "env" in tool_input else None
    if raw_env is not None and raw_env != {}:
        return None
    segments = split_literal_and_chain(str(tool_input.get("command") or ""))
    if segments is None:
        return None
    capabilities: list[tuple[
        capability_registry.CapabilitySpec, PythonControlInvocation, str,
    ]] = []
    invalid_invocations: list[PythonControlInvocation] = []
    for segment in segments:
        try:
            display_tokens = shlex.split(segment, comments=False, posix=True)
        except ValueError:
            return None
        if _diagnostic_passive_chain_segment(display_tokens):
            continue
        invocation = parse_exact_python_command(
            segment,
            root=ROOT,
            allowed_scripts=REGISTERED_CAPABILITY_SCRIPTS,
            allow_environment=True,
        )
        if invocation is None \
                or not _diagnostic_registered_environment_allowed(invocation):
            return None
        if _argv_data_critical_paths(invocation.args):
            return None
        spec = capability_registry.match(
            invocation.script, invocation.args, root=ROOT)
        if spec is None:
            if not allow_invalid:
                return None
            invalid_invocations.append(invocation)
            continue
        if spec.effect == "repo_mutation":
            return None
        capabilities.append((spec, invocation, segment))
    if not capabilities and not invalid_invocations:
        return None
    return tuple(capabilities), tuple(invalid_invocations)


def _diagnostic_passive_chain_segment(tokens: list[str]) -> bool:
    """Recognize harmless shell-only segments for denial classification only."""
    if tokens and tokens[0] == "echo":
        return True
    if len(tokens) == 2 and tokens[0] == "sleep" \
            and re.fullmatch(r"(?:0|[1-5]?\d)(?:\.\d+)?", tokens[1]):
        try:
            return float(tokens[1]) <= 60.0
        except ValueError:
            return False
    return False


def _lifecycle_shape_reason(event: dict) -> str:
    issue = _registered_capability_shape_issue(event)
    if issue is None:
        return ""
    if issue.category in {"registered-chain", "registered-chain-passive"}:
        prefix = (
            "等待/展示 segment 与已注册 capability 被合并成"
            if issue.category == "registered-chain-passive"
            else "多个已注册 capability 被合并成"
        )
        return (
            f"[{E_LIFECYCLE_EXACT_ARGV_REQUIRED}] {prefix}"
            "一个 compound Bash。PreToolUse 已拒绝整条命令且未执行任何 segment，也未"
            "授予 capability authority，也未把 executable path 记为 maintenance。保持原"
            "顺序，把每个 registered Python "
            "argv 分别作为一次 Bash tool call 原样重试；不要使用 &&、;、||、pipe、"
            "redirection、换行或 separator echo。此拒绝属于 command-shape，可在同一 "
            "operator 回合修正。"
        )
    if issue.category == "registered-chain-invalid-argv":
        return (
            f"[{E_LIFECYCLE_EXACT_ARGV_REQUIRED}] 多个已登记 Python 入口被合并成"
            "一个 compound Bash，且至少一个 segment 的 argv 未匹配 typed capability。"
            "PreToolUse 已拒绝整条命令、未执行任何 segment，也未把 executable path 记为"
            "maintenance。回到各脚本 owner 文档补齐 invalid argv，再把每个完整 registered "
            "Python argv 分别作为一次 Bash tool call；不要使用 shell chain/wrapper。"
            "此拒绝可在同一 operator 回合修正。"
        )
    if issue.category.startswith("invalid-argv"):
        retry_args = ["<按对应 owner 文档填写完整参数>"]
        if issue.script.name == "probe.py":
            retry_args = [
                "GET", "<url>", "--save", "<name>",
                "--run", "runs/<run>",
            ]
        retry_hint = _python_control_hint(issue.script, retry_args)
        wrapper_note = ""
        if issue.category != "invalid-argv":
            wrapper_note = " 同时删除 2>&1/head/tail/pipe 等观察包装。"
        return (
            f"[{E_LIFECYCLE_EXACT_ARGV_REQUIRED}] 已登记 Xunji 脚本的当前 argv 未匹配"
            "任何 typed capability；PreToolUse 已拒绝且未执行，也未授予 control/target/"
            "maintenance authority。请回到该脚本的 owner 文档，按 "
            f"`{retry_hint}` 的形状补齐并原样重试。{wrapper_note}"
            "读取源码或 manifest 只用 Read/Grep/Glob；不要用 python -c、重定向或不透明 shell "
            "猜测参数。此拒绝属于 command-shape，可在同一 operator 回合修正。"
        )
    retry_hint = _python_control_hint(issue.script, ["<原参数>"])
    return (
        f"[{E_LIFECYCLE_EXACT_ARGV_REQUIRED}] 已注册 Xunji capability 命令必须是单一、精确的 "
        "Python argv；检测到仅用于观察输出的 shell 包装。请在当前 operator 回合使用"
        f"当前解释器绝对路径并按 `{retry_hint}` 的形状删除 "
        "2>&1/head/tail/pipe 包装、原样重试精确参数。此拒绝属于 command-shape，"
        "不是框架维护授权错误，也不会继承到新的“继续”回合。"
    )


def _decision_metadata(reason: str, event: dict) -> dict:
    """Build additive, non-secret receipt fields for a deterministic denial."""
    match = ERROR_CODE_RE.match(str(reason or ""))
    code = match.group(1) if match else ""
    classes = {
        E_LIFECYCLE_EXACT_ARGV_REQUIRED: "command_shape",
        E_NEW_RUN_SETUP_REQUIRED: "lifecycle",
        E_RUN_TRANSITION_AUTHORITY_MISSING: "authority",
        E_CLEAR_ACTIVE_FORBIDDEN: "lifecycle",
        E_CRON_LIST_REQUIRED: "cron",
        E_CRON_RUN_MISMATCH: "cron",
        E_CRON_CREATE_REQUIRED: "cron",
        E_ITERATION_PLAN_REQUIRED: "iteration_plan",
        E_WORK_PLAN_REQUIRED: "work_plan",
        E_WORK_PLAN_STALE: "work_plan",
        E_DELEGATION_REQUIRED: "delegation",
        E_ROOT_COORDINATOR_ONLY: "delegation",
        E_CAPABILITY_POLICY: "capability_policy",
        E_AGENT_TOOL_CALL_LIMIT_EXCEEDED: "agent_tool_budget",
        E_AGENT_TOOL_CALL_IDENTITY_CONFLICT: "agent_tool_budget",
        E_AGENT_TOOL_CALL_BUDGET_INVALID: "agent_tool_budget",
        E_AGENT_REQUEST_BUDGET_EXCEEDED: "agent_request_budget",
    }
    metadata = {
        "xunji_decision_code": code,
        "xunji_decision_class": classes.get(code, "policy" if code else ""),
    }
    issue = _registered_capability_shape_issue(event) \
        if code == E_LIFECYCLE_EXACT_ARGV_REQUIRED else None
    if issue is not None:
        try:
            script = issue.script.relative_to(ROOT).as_posix()
        except ValueError:
            script = issue.script.name
        metadata.update({
            "xunji_shape_category": issue.category,
            "xunji_control_script": script,
            "xunji_retryable_same_turn": issue.retryable_same_turn,
        })
        if issue.category.startswith("registered-chain"):
            details = _registered_capability_chain_details(
                event, allow_invalid=True)
            chain = details[0] if details is not None else ()
            effect_order = (
                "target", "model_egress", "control",
                "local_verify", "local_read",
            )
            effects = {spec.effect for spec, _invocation, _segment in chain}
            ordered_effects = [effect for effect in effect_order if effect in effects]
            if ordered_effects:
                metadata["xunji_capability_effect"] = ordered_effects[0]
                metadata["xunji_capability_effects"] = ordered_effects
            metadata["xunji_target_retry_action_sha256s"] = [
                runtime_receipts._action_hash("Bash", {"command": segment})
                for spec, _invocation, segment in chain
                if spec.effect == "target"
            ]
    return metadata


def _new_run_transition_pending(contract: dict, run_dir: Path) -> bool:
    transition = bool(contract.get("run_transition_requested")) or bool(
        RUN_TRANSITION_RE.search(str(contract.get("prompt_excerpt") or "")))
    if not transition:
        return False
    origin = str(contract.get("origin_run") or "")
    bound = str(contract.get("bound_run") or "")
    # Before an active-run transition, origin and bound both name the current
    # run.  Before a no-active-run transition, both are empty.  Once the setup
    # transaction has claimed the hook authority, ``bound_run`` names the
    # target while an empty origin remains a meaningful no-active sentinel;
    # never replace that sentinel with ``run_dir.name``.
    if not bound or bound != run_dir.name:
        return True
    return bool(origin and bound == origin)


def _event_effect(event: dict) -> str:
    tool = str(event.get("tool_name") or "")
    if tool == "Bash":
        tool_input = event.get("tool_input") \
            if isinstance(event.get("tool_input"), dict) else {}
        command = str(tool_input.get("command") or "")
        tool_env = tool_input.get("env") \
            if isinstance(tool_input.get("env"), dict) else {}
        capability = _registered_capability_invocation(
            command, tool_env=tool_env)
        if capability is not None:
            return capability[0].effect
    return "target" if _is_target_action(event) else ""


def _transition_commit_reason(run_dir: Path, contract: dict) -> str:
    """Verify a source-backed setup transaction before post-bind work."""
    transaction = contract.get("transition_transaction")
    if not isinstance(transaction, dict) or not transaction:
        return ""  # Explicit resume/set-active may bind a legacy run.
    try:
        receipt = json.loads(
            (run_dir / "state" / "setup_transaction.json").read_text(
                encoding="utf-8", errors="strict",
            )
        )
    except Exception:
        receipt = {}
    binding = receipt.get("contract_binding") if isinstance(receipt, dict) else {}
    expected = {
        "transaction_id": str(transaction.get("transaction_id") or ""),
        "source_sha256": str(transaction.get("source_sha256") or ""),
        "expected_run": str(transaction.get("expected_run") or ""),
        "session_id": str(contract.get("session_id") or ""),
        "prompt_sha256": str(contract.get("prompt_sha256") or ""),
    }
    valid = bool(
        receipt.get("schema") == "xunji.setup_transaction.v1"
        and receipt.get("status") in {"committed", "recovered"}
        and receipt.get("transaction_id") == expected["transaction_id"]
        and receipt.get("source_sha256") == expected["source_sha256"]
        and expected["expected_run"] == run_dir.name
        and isinstance(binding, dict)
        and all(str(binding.get(key) or "") == value for key, value in expected.items())
    )
    if valid:
        return ""
    return (
        f"[{E_NEW_RUN_SETUP_REQUIRED}] 新 run 的 setup transaction 尚未形成与当前 "
        "session/prompt/source/transaction/expected-run 一致的 committed/recovered 回执；"
        "拒绝把指针或模型叙述当作 setup 完成。"
    )


def _loop_iteration_gate_reason(run_dir: Path, event: dict, contract: dict) -> str:
    """Derive the explicit-/loop setup -> Cron -> plan execution boundary."""
    if not contract.get("loop_requested"):
        return ""
    tool = str(event.get("tool_name") or "")
    tool_input = event.get("tool_input") \
        if isinstance(event.get("tool_input"), dict) else {}
    command = str(tool_input.get("command") or "")
    tool_env = tool_input.get("env") \
        if isinstance(tool_input.get("env"), dict) else {}
    capability = _registered_capability_invocation(
        command, tool_env=tool_env) if tool == "Bash" else None
    root_direct_candidate = False
    if capability is not None and work_plan.plan_path(run_dir).exists():
        # A committed ROOT_DIRECT plan makes its exact capability an execution
        # action even when the effect is local_read/local_verify.  Also route a
        # same-effect registered capability through the gate so it cannot
        # impersonate the capability id frozen by the plan.
        try:
            raw_plan = work_plan.validate_plan(work_plan.load_plan(run_dir))
            raw_lanes = raw_plan.get("lanes") \
                if isinstance(raw_plan.get("lanes"), list) else []
            root_direct_candidate = bool(
                raw_plan.get("execution_mode") == "ROOT_DIRECT"
                and len(raw_lanes) == 1
                and (
                    capability[0].root_direct_eligible is True
                    or capability[0].effect == str(raw_lanes[0].get("effect") or "")
                )
            )
        except Exception:
            # An eligible Root action must not bypass an unreadable/stale plan.
            root_direct_candidate = capability[0].root_direct_eligible is True
    task_plan_tool = tool in {"TaskCreate", "TaskUpdate", "TodoWrite"}
    execution_tool = tool == "Agent" or _event_effect(event) in {
        "target", "model_egress",
    } or root_direct_candidate
    if not task_plan_tool and not execution_tool:
        return ""
    if _new_run_transition_pending(contract, run_dir):
        return (
            f"[{E_NEW_RUN_SETUP_REQUIRED}] 当前显式 /loop 要求创建新 run；先用当前 "
            "operator 回合的精确 lifecycle argv 完成 setup/activation，再绑定新 run。"
        )
    session_id = str(contract.get("session_id") or "")
    since = float(contract.get("updated_at") or 0.0)
    transitioned = bool(
        contract.get("run_transition_requested")
        and not _new_run_transition_pending(contract, run_dir)
        and (
            isinstance(contract.get("transition_transaction"), dict)
            or bool(str(contract.get("transitioned_from") or ""))
        )
    )
    if transitioned:
        transition_reason = _transition_commit_reason(run_dir, contract)
        if transition_reason:
            return transition_reason
        cron_ok, cron_note = runtime_receipts.cron_create_observed(
            run_dir, session_id=session_id, since=since,
        )
        if not cron_ok:
            return (
                f"[{E_CRON_CREATE_REQUIRED}] 新 run 已绑定，但尚无当前回合、显式命名该 run "
                f"的成功 CronCreate 回执；先执行 fresh CronList/CronCreate。{cron_note}"
            )
    if task_plan_tool:
        return ""
    plan_ok, plan_note = runtime_receipts.iteration_plan_observed(
        run_dir,
        session_id=session_id,
        since=since,
        after_latest_cron_create=transitioned,
    )
    if not plan_ok:
        return (
            f"[{E_ITERATION_PLAN_REQUIRED}] 显式 /loop 在 Agent/目标动作前必须有当前回合"
            "成功的 TaskCreate/TaskUpdate（兼容 TodoWrite）任务清单回执。该硬门只证明"
            "存在与时序；Root 仍须按工作流覆盖资产、向量、Agent lanes、证据写入与 gates。"
            f"{plan_note}"
        )
    return _work_plan_gate_reason(run_dir, event, contract)


def _stale_reviewer_agent_ready(run_dir: Path, event: dict, plan: dict) -> bool:
    """Admit one exact Reviewer without making a stale plan executable again."""
    if str(event.get("tool_name") or "") != "Agent":
        return False
    tool_input = event.get("tool_input") \
        if isinstance(event.get("tool_input"), dict) else {}
    prompt = str(tool_input.get("prompt") or "")
    if str(tool_input.get("subagent_type") or "") != "xunji-reviewer":
        return False
    assignment, front = runtime_receipts._assignment_fields(prompt)
    assets = runtime_receipts._assignment_assets(prompt)
    lane_match = re.search(
        r"(?i)\bXUNJI_LANE\s*=\s*(L-[A-Za-z0-9._-]+)", prompt)
    lane_id = lane_match.group(1) if lane_match else ""
    plan_digest = runtime_receipts._assignment_plan(prompt)
    result_digest = runtime_receipts._assignment_result_digest(prompt)
    if not runtime_receipts.has_completion_review_marker(prompt) \
            or not assignment or not front or not lane_id \
            or plan_digest != str(plan.get("plan_digest") or ""):
        return False
    lanes = [
        item for item in plan.get("lanes", []) if isinstance(item, dict)
        and str(item.get("id") or "") == lane_id
        and str(item.get("front") or "").upper() == front.upper()
        and _normalized_assets(item.get("assets")) == assets
    ]
    if len(lanes) != 1 or not agent_settlement.stale_settlement_reviewer_ready(
            run_dir, plan, lanes[0]):
        return False
    dependencies = [str(item) for item in lanes[0].get("dependencies", [])]
    if len(dependencies) != 1:
        return False
    try:
        projection = run_model.plan_cycle_projection(run_dir, plan=plan)
    except Exception:
        return False
    target_states = [
        item for item in projection.get("lane_states", [])
        if isinstance(item, dict)
        and str(item.get("lane_id") or "") == dependencies[0]
        and str(item.get("runtime_state") or "") in {"returned", "failed"}
    ]
    if len(target_states) != 1:
        return False
    target_assignment = str(target_states[0].get("assignment") or "")
    target_result_digest = str(target_states[0].get("result_digest") or "")
    target_record = _assignment_record(run_dir, target_assignment)
    if not re.fullmatch(r"A-[A-Za-z0-9._-]+", target_assignment) \
            or not re.fullmatch(r"[0-9a-f]{64}", target_result_digest) \
            or not target_record \
            or str(target_record.get("plan_digest") or "") != plan_digest \
            or str(target_record.get("lane_id") or "") != dependencies[0]:
        return False
    rec = _assignment_record(run_dir, assignment, front)
    if not rec or str(rec.get("plan_digest") or "") != plan_digest \
            or str(rec.get("lane_id") or "") != lane_id \
            or str(rec.get("role") or "").strip().lower() != "review" \
            or str(rec.get("effect") or "") != "local_verify" \
            or str(rec.get("status") or "").strip().lower() != "assigned" \
            or rec.get("attempts") != [] \
            or _normalized_assets(rec.get("assets")) != assets \
            or not re.fullmatch(r"[0-9a-f]{64}", result_digest) \
            or str(rec.get("review_result_digest") or "") != result_digest \
            or result_digest != target_result_digest \
            or rec.get("reviews_assignments") != [target_assignment] \
            or prompt != runtime_receipts.assignment_launch_prompt(rec):
        return False
    try:
        return not agent_settlement.cancellation_barrier(
            run_dir, plan_digest=plan_digest, assignment=assignment)
    except Exception:
        return False


def _work_plan_gate_reason(run_dir: Path, event: dict, contract: dict) -> str:
    """Require one current plan/delegation decision before /loop effects.

    TaskCreate proves only that the model made a task list.  This gate binds the
    actual execution mode and effect-typed lanes to the current turn and current
    canonical digest.  Child Agents remain free to execute their assigned lane;
    the later actor/asset gate still enforces their exact runtime assignment.
    """
    if not contract.get("loop_requested"):
        return ""
    tool = str(event.get("tool_name") or "")
    event_effect = _event_effect(event)
    if tool != "Agent" and event_effect not in {"target", "model_egress"}:
        tool_input = event.get("tool_input") \
            if isinstance(event.get("tool_input"), dict) else {}
        command = str(tool_input.get("command") or "")
        tool_env = tool_input.get("env") \
            if isinstance(tool_input.get("env"), dict) else {}
        local_capability = _registered_capability_invocation(
            command, tool_env=tool_env) if tool == "Bash" else None
        try:
            raw_plan = work_plan.validate_plan(work_plan.load_plan(run_dir))
            raw_lanes = raw_plan.get("lanes") \
                if isinstance(raw_plan.get("lanes"), list) else []
        except Exception:
            raw_plan, raw_lanes = {}, []
        if not (
            local_capability is not None
            and raw_plan.get("execution_mode") == "ROOT_DIRECT"
            and len(raw_lanes) == 1
            and (
                local_capability[0].root_direct_eligible is True
                or local_capability[0].effect
                == str(raw_lanes[0].get("effect") or "")
            )
        ):
            return ""
    stale_settlement = False
    try:
        plan = work_plan.current_plan(run_dir, contract)
    except work_plan.PlanError as exc:
        detail = str(exc)
        plan = {}
        if detail == "WORK_PLAN_INPUTS_STALE" and tool == "Agent":
            try:
                candidate = work_plan.transaction_bound_plan(run_dir)
                validated = work_plan.validate_plan(
                    candidate, run_dir=run_dir, contract=contract,
                    check_inputs=False)
                if candidate == validated \
                        and _stale_reviewer_agent_ready(
                            run_dir, event, candidate):
                    plan = candidate
                    stale_settlement = True
            except Exception:
                plan = {}
        if plan:
            detail = ""
        else:
            code = E_WORK_PLAN_STALE if detail in {
                "WORK_PLAN_TURN_STALE", "WORK_PLAN_INPUTS_STALE",
                "WORK_PLAN_DIGEST_MISMATCH", "WORK_PLAN_ID_MISMATCH",
            } else E_WORK_PLAN_REQUIRED
            return (
                f"[{code}] 当前 /loop 在 Agent/目标动作前必须提交与本 turn 和 canonical "
                "输入 digest 一致的 xunji.work-plan.v1，并先选择 ROOT_DIRECT / "
                f"SERIAL_AGENT / PARALLEL_AGENTS。当前状态：{detail}。"
                "完整读取 `.claude/skills/xunji-agent-board/SKILL.md`，再从唯一公共入口 "
                f"`python3 tools/workers.py plan runs/{run_dir.name} --limit 2` 继续；"
                "不要读取 tools 源码或猜测 schema/argv。"
            )
    try:
        cancellation_barrier = agent_settlement.cancellation_barrier(
            run_dir, plan_digest=str(plan.get("plan_digest") or ""))
    except Exception as exc:
        return (
            f"[{E_WORK_PLAN_STALE}] assignment cancellation receipt 无法安全验证："
            f"{type(exc).__name__}；拒绝启动 Agent/目标动作。"
        )
    if cancellation_barrier and not stale_settlement:
        if tool == "Agent" and _stale_reviewer_agent_ready(run_dir, event, plan):
            stale_settlement = True
        else:
            return (
                f"[{E_WORK_PLAN_STALE}] 当前 plan 含 cancelled-unlaunched lane；"
                "只允许 authentic returned/failed execution 的唯一 Reviewer 结清，"
                "其余执行必须先 material replan。"
            )
    mode = str(plan.get("execution_mode") or "")
    actor_agent_id = str(event.get("agent_id") or "").strip()
    if actor_agent_id:
        if mode == "ROOT_DIRECT":
            return (
                f"[{E_DELEGATION_REQUIRED}] 当前计划声明 ROOT_DIRECT，不能由子 Agent "
                "执行；canonical 输入或策略改变后先 replan。"
            )
        return ""
    if tool != "Agent":
        if mode != "ROOT_DIRECT":
            return (
                f"[{E_ROOT_COORDINATOR_ONLY}] 当前 delegation={mode}；Root 只负责 "
                "plan/assign/message/review/merge/control，不得代替 Hunter 执行目标动作。"
            )
        lanes = [item for item in plan.get("lanes", []) if isinstance(item, dict)]
        tool_input = event.get("tool_input") \
            if isinstance(event.get("tool_input"), dict) else {}
        command = str(tool_input.get("command") or "")
        tool_env = tool_input.get("env") \
            if isinstance(tool_input.get("env"), dict) else {}
        capability = _registered_capability_invocation(
            command, tool_env=tool_env) if tool == "Bash" else None
        expected_capability = str(lanes[0].get("capability_id") or "") \
            if len(lanes) == 1 else ""
        actual_capability = capability[0].id if capability is not None else ""
        if len(lanes) != 1 \
                or str(lanes[0].get("effect") or "") != event_effect \
                or not expected_capability \
                or actual_capability != expected_capability \
                or capability is None \
                or capability[0].root_direct_eligible is not True:
            return (
                f"[{E_DELEGATION_REQUIRED}] ROOT_DIRECT 动作 capability="
                f"{actual_capability or 'unregistered'} / effect={event_effect or 'unknown'} "
                "必须与当前唯一 atomic lane 的 capability_id/effect 精确一致且 registry "
                "明确标记为 root_direct_eligible；先 replan。"
            )
        direct_lane_state = work_plan.lane_runtime_state(
            run_dir, plan, str(lanes[0].get("id") or ""))
        direct_receipt, direct_debt = runtime_receipts.root_action_receipt(
            run_dir, plan)
        if direct_lane_state in {"terminal", "ended"} or direct_receipt:
            return (
                f"[{E_DELEGATION_REQUIRED}] 当前 ROOT_DIRECT plan 已有 exact terminal "
                "receipt 或 typed cycle_end；不得在同一 cycle 上重新授权工具执行。"
            )
        if direct_debt not in {
                "root-action-pending:no-claim",
                "root-action-pending:no-terminal",
        }:
            return (
                f"[{E_DELEGATION_REQUIRED}] 当前 ROOT_DIRECT runtime chain 无法安全投影："
                f"{direct_debt or 'unknown projection state'}；先修复 receipt/chain，"
                "不得重跑动作。"
            )
        if event_effect == "target":
            expected_assets = set(_normalized_assets(lanes[0].get("assets")))
            touched_assets, coverage_error = _event_known_hosts(run_dir, event)
            if coverage_error or not touched_assets or touched_assets != expected_assets:
                return (
                    f"[{E_DELEGATION_REQUIRED}] ROOT_DIRECT target 动作必须与唯一 lane 的"
                    "非空 asset package 精确一致；资产派生失败或集合不等均拒绝。"
                )
        return ""
    if mode == "ROOT_DIRECT":
        return (
            f"[{E_DELEGATION_REQUIRED}] 当前计划声明 ROOT_DIRECT；不得同时启动 Agent。"
        )
    raw_input = event.get("tool_input") if isinstance(event.get("tool_input"), dict) else {}
    prompt = str(raw_input.get("prompt") or "")
    completion_reason = _global_completion_gate_reason(run_dir, raw_input)
    if completion_reason is not None:
        if completion_reason:
            return completion_reason
        if plan.get("macro_stage") != "S3":
            return (
                f"[{E_DELEGATION_REQUIRED}] completion review Agent 只允许绑定 S3 "
                "work plan。"
            )
        return ""
    assignment, front = runtime_receipts._assignment_fields(prompt)
    prompt_assets = runtime_receipts._assignment_assets(prompt)
    lane_match = re.search(
        r"(?i)\bXUNJI_LANE\s*=\s*(L-[A-Za-z0-9._-]+)", prompt)
    lane_id = lane_match.group(1) if lane_match else ""
    plan_digest = runtime_receipts._assignment_plan(prompt)
    lanes = [item for item in plan.get("lanes", []) if isinstance(item, dict)]
    candidates = [
        item for item in lanes
        if (not front or str(item.get("front") or "").upper() == front.upper())
        and (not prompt_assets or _normalized_assets(item.get("assets")) == prompt_assets)
    ]
    if lane_id:
        candidates = [item for item in candidates if item.get("id") == lane_id]
    if not assignment or not front or not lane_id or not plan_digest \
            or plan_digest != str(plan.get("plan_digest") or "") \
            or len(candidates) != 1:
        return (
            f"[{E_DELEGATION_REQUIRED}] Agent prompt 必须唯一绑定当前 work plan lane；"
            "包含 XUNJI_ASSIGNMENT、XUNJI_FRONT、XUNJI_ASSETS、XUNJI_LANE=L-... "
            "和 XUNJI_PLAN=<current plan digest>。"
        )
    lane = candidates[0]
    if not work_plan.lane_dependencies_satisfied(run_dir, plan, lane):
        return (
            f"[{E_DELEGATION_REQUIRED}] Agent lane 仍有未返回的 dependencies，不能启动。"
        )
    rec = _assignment_record(run_dir, assignment, front)
    if not rec or str(rec.get("plan_digest") or "") != plan_digest \
            or str(rec.get("lane_id") or "") != lane_id \
            or str(rec.get("role") or "") \
            != runtime_receipts.canonical_assignment_role(lane.get("role")) \
            or str(rec.get("effect") or "") != str(lane.get("effect") or "") \
            or _normalized_assets(rec.get("assets")) != prompt_assets:
        return (
            f"[{E_DELEGATION_REQUIRED}] Agent prompt 与 workers.py 生成的 exact "
            "assignment/plan/lane/effect/assets binding 不一致。"
        )
    integrity_reason = _instruction_integrity_reason(run_dir, rec)
    if integrity_reason:
        return integrity_reason
    expected_agent_type = runtime_receipts.assignment_subagent_type(rec)
    if not expected_agent_type \
            or str(raw_input.get("subagent_type") or "") != expected_agent_type:
        return (
            f"[{E_DELEGATION_REQUIRED}] Agent subagent_type 必须与 assignment role "
            f"精确一致：expected={expected_agent_type or '(invalid role)'}。"
        )
    expected_prompt = runtime_receipts.assignment_launch_prompt(rec)
    if not expected_prompt or prompt != expected_prompt:
        return (
            f"[{E_DELEGATION_REQUIRED}] Agent tool_input.prompt 必须与 workers.py "
            "生成值逐字节一致；禁止前后缀、附加上下文、重排、空白变化或手写重建。"
        )
    return ""


def _fanout_control_bash(command: str, *, tool_env: dict | None = None) -> bool:
    if not tool_env and _readonly_shell(command):
        return True
    capability = _registered_capability_invocation(
        command, tool_env=tool_env,
    )
    return bool(
        capability
        and capability[0].effect in {
            "local_read", "local_verify", "control", "model_egress",
        }
    )


def _global_completion_gate_reason(
    run_dir: Path,
    raw_input: dict,
) -> str | None:
    """Validate one assignment-free completion Reviewer launch envelope."""
    prompt = str(raw_input.get("prompt") or "")
    if not runtime_receipts.has_completion_review_marker(prompt):
        return None
    assignment, _front = runtime_receipts._assignment_fields(prompt)
    if assignment:
        return None
    if not runtime_receipts.is_global_completion_envelope(prompt):
        return (
            f"[{E_DELEGATION_REQUIRED}] global completion envelope 不得混入 "
            "XUNJI_ASSIGNMENT/FRONT/ASSETS/LANE/PLAN/RESULT_DIGEST；"
            "plan-bound Reviewer 必须提供完整 assignment package。"
        )
    if str(raw_input.get("subagent_type") or "") != "xunji-reviewer":
        return (
            f"[{E_DELEGATION_REQUIRED}] completion review 必须使用 exact "
            "xunji-reviewer Agent type。"
        )
    expected = runtime_receipts.completion_review_prompt(
        run_dir, current_evidence_index_hash(run_dir))
    if not expected or prompt != expected:
        return (
            f"[{E_DELEGATION_REQUIRED}] global completion prompt 必须与当前 "
            "current S3 plan、evidence index、completion bundle、run 名和固定 checks "
            "的 canonical envelope 逐字节一致；missing/stale/prepared/corrupt plan "
            "均不得启动。"
        )
    return ""


def _assignment_record(run_dir: Path, assignment: str, front: str = "") -> dict:
    try:
        data = json.loads((run_dir / "state" / "assignments.json").read_text(encoding="utf-8", errors="replace"))
    except Exception:
        return {}
    if runtime_receipts.assignment_state_errors(
            data, parent_run=run_dir.name):
        return {}
    matches = [
        item for item in data.get("assignments", [])
        if isinstance(item, dict)
        and str(item.get("agent") or "") == assignment
        and (not front or str(item.get("front") or "").upper() == front.upper())
    ] if isinstance(data, dict) else []
    if len(matches) != 1 \
            or not (run_dir / "agents" / f"{assignment}.md").exists():
        return {}
    return matches[0]


def _assignment_exists(run_dir: Path, assignment: str, front: str) -> bool:
    return bool(_assignment_record(run_dir, assignment, front))


def _instruction_integrity_reason(
    run_dir: Path,
    rec: dict,
    *,
    frozen_launch_prompt_sha256: str = "",
) -> str:
    try:
        agent_instruction_bundle.verify_assignment_bundle(
            run_dir, rec, root=ROOT)
    except agent_instruction_bundle.InstructionBundleError as exc:
        if exc.code == "artifact_invalid":
            return (
                f"[{E_AGENT_ARTIFACT_INTEGRITY}] assignment 的 frozen context/Agent "
                f"artifact 完整性校验失败：{exc}。拒绝执行并重新 material replan/delegate。"
            )
        return (
            f"[{E_AGENT_INSTRUCTION_SOURCE_STALE}] assignment 的 role/common/scaffold/"
            f"live Agent 指令来源无效或已漂移：{exc}。拒绝执行并重新 material replan/delegate。"
        )
    if frozen_launch_prompt_sha256:
        current = runtime_receipts.assignment_launch_prompt_sha256(rec)
        if not current or current != frozen_launch_prompt_sha256:
            return (
                f"[{E_AGENT_INSTRUCTION_SOURCE_STALE}] child attempt 冻结的 launch/bundle "
                "digest 与当前 assignment 不一致；拒绝从可变状态补信任。"
            )
    return ""


def _claim_plan_bound_child_tool_call(run_dir: Path, event: dict) -> str:
    """Reserve a live plan-bound child's attempted call before all policy gates."""
    agent_id = str(event.get("agent_id") or "").strip()
    if not agent_id:
        return ""
    session_id = str(event.get("session_id") or "").strip()
    actor = runtime_receipts.agent_actor(
        run_dir, agent_id, session_id=session_id)
    if not actor or actor.get("kind") != "assignment" \
            or actor.get("state") != "running" \
            or not str(actor.get("lane_id") or "") \
            or not str(actor.get("plan_digest") or ""):
        # Existing gates own unbound, completion-review, and post-Stop actors.
        return ""
    event["xunji_agent_request_action"] = _is_target_action(event)
    try:
        claim = runtime_receipts.claim_agent_tool_call(run_dir, event)
    except Exception as exc:
        detail = str(exc)
        code = E_AGENT_TOOL_CALL_IDENTITY_CONFLICT \
            if "IDENTITY_CONFLICT" in detail \
            else E_AGENT_TOOL_CALL_BUDGET_INVALID
        return (
            f"[{code}] plan-bound 子 Agent 的 PreToolUse 调用预算无法原子绑定："
            f"{detail.split(':', 1)[0]}。本次工具未执行；返回 blocker，不得绕过或重试新形状。"
        )
    ordinal = int(claim.get("agent_tool_call_ordinal") or 0)
    limit = int(claim.get("agent_tool_call_limit") or 0)
    event["_xunji_agent_tool_call_claim"] = {
        "ordinal": ordinal,
        "limit": limit,
        "admitted": bool(claim.get("agent_tool_call_admitted")),
        "receipt_hash": str(claim.get("receipt_hash") or ""),
        "request_action": bool(claim.get("agent_request_action")),
        "request_ordinal": int(claim.get("agent_request_ordinal") or 0),
        "request_budget": int(claim.get("assignment_request_budget") or 0),
        "request_admitted": bool(claim.get("agent_request_admitted")),
    }
    if claim.get("agent_tool_call_admitted") is not True:
        return (
            f"[{E_AGENT_TOOL_CALL_LIMIT_EXCEEDED}] plan-bound 子 Agent 第 "
            f"{ordinal} 次工具调用超过 assignment 冻结上限 {limit}；claim 已耐久记录，"
            "工具未执行。立即用已有材料返回 candidate/refutation/blocker；不得继续调用工具。"
        )
    if claim.get("agent_request_action") is True \
            and claim.get("agent_request_admitted") is not True:
        request_ordinal = int(claim.get("agent_request_ordinal") or 0)
        request_budget = int(claim.get("assignment_request_budget") or 0)
        return (
            f"[{E_AGENT_REQUEST_BUDGET_EXCEEDED}] plan-bound 子 Agent 第 "
            f"{request_ordinal} 次 target 请求超过 lane 冻结上限 {request_budget}；"
            "request claim 已耐久记录且工具未执行。立即用已有响应与 artifact 返回，"
            "不得换 method/path/argv 继续探测。"
        )
    return ""


def _plan_bound_child_budget_context(event: dict) -> dict | None:
    claim = event.get("_xunji_agent_tool_call_claim") \
        if isinstance(event.get("_xunji_agent_tool_call_claim"), dict) else {}
    ordinal = int(claim.get("ordinal") or 0)
    limit = int(claim.get("limit") or 0)
    messages: list[str] = []
    if ordinal and limit and claim.get("admitted") is True \
            and ordinal >= limit - 1:
        remaining = max(0, limit - ordinal)
        if remaining == 1:
            messages.append(
            f"[Xunji Agent budget {ordinal}/{limit}] 当前调用完成后只剩 1 次额度；"
            "不要再探测。读取本次结果后直接返回已有证据支持的 candidate/refutation/blocker。"
            )
        else:
            messages.append(
            f"[Xunji Agent budget {ordinal}/{limit}] 这是最后一次允许的工具调用；"
            "读取结果后必须直接给出 final response，下一次调用将被硬门拒绝。"
            )
    if claim.get("request_action") is True and claim.get("request_admitted") is True:
        request_ordinal = int(claim.get("request_ordinal") or 0)
        request_budget = int(claim.get("request_budget") or 0)
        if request_ordinal >= request_budget:
            messages.append(
                f"[Xunji request budget {request_ordinal}/{request_budget}] "
                "本次 target 请求耗尽当前 lane 预算；读取结果后立即返回，禁止追加 method/path。"
            )
    return _pretool_context("\n".join(messages)) if messages else None


def _normalized_assets(values: object) -> list[str]:
    out: list[str] = []
    for raw in values if isinstance(values, list) else []:
        value = str(raw).strip().lower().rstrip(".")
        value = re.sub(r"^[a-z][a-z0-9+.\-]*://", "", value).split("/", 1)[0]
        if value and value not in out:
            out.append(value)
    return out


def _coverage_rows(run_dir: Path) -> tuple[list[dict], str]:
    coverage_paths = [run_dir / "coverage.json", *sorted(run_dir.glob("**/coverage.json"))]
    existing = [path for path in coverage_paths if path.exists()]
    if not existing:
        return [], ""
    try:
        import coverage_matrix  # noqa: WPS433
        data = coverage_matrix.derive(run_dir)
    except Exception as exc:
        return [], f"{exc.__class__.__name__}: coverage derivation failed"
    rows = [row for row in data.get("rows", []) if isinstance(row, dict)]
    if not rows:
        return [], "coverage file exists but no valid asset rows were derived"
    return rows, ""


def _event_known_hosts(run_dir: Path, event: dict) -> tuple[set[str], str]:
    text = _tool_text(event).lower()
    found: set[str] = set()
    rows, error = _coverage_rows(run_dir)
    if error:
        return set(), error
    for row in rows:
        host = _normalized_assets([row.get("asset")])
        if host and re.search(r"(?<![\w.\-])" + re.escape(host[0]) + r"(?![\w.\-])", text):
            found.add(host[0])
    return found, ""


def _coverage_hostnames(rows: list[dict]) -> set[str]:
    """Return host-only scope keys for URL/IP destination comparison."""
    hosts: set[str] = set()
    for row in rows:
        for asset in _normalized_assets([row.get("asset")]):
            try:
                host = urlsplit("//" + asset).hostname or ""
            except ValueError:
                host = ""
            host = host.strip().lower().rstrip(".")
            if host:
                hosts.add(host)
    return hosts


def _unapproved_scope_destinations(
    run_dir: Path, rows: list[dict], destinations: set[str],
) -> dict[str, list[str]]:
    """Return ledger-known destinations that are not admitted for target effects.

    ``legacy`` preserves old ledgers that predate an explicit scope-status field.
    New setup-source candidates deliberately use ``review`` and must remain
    non-executable until a hook-bound operator admission updates the ledger.
    Conflicting duplicate rows fail closed.
    """
    status_by_host: dict[str, set[str]] = {}
    candidate_receipt_errors: set[str] = set()
    for row in rows:
        status = str(row.get("scope_status") or "legacy").strip().lower()
        for asset in _normalized_assets([row.get("asset")]):
            try:
                host = urlsplit("//" + asset).hostname or ""
            except ValueError:
                host = ""
            host = host.strip().lower().rstrip(".")
            if host:
                status_by_host.setdefault(host, set()).add(status)
                if status == "in":
                    valid, _note = scope_admission.verify_admitted_host(
                        run_dir, rows, host,
                    )
                    if not valid:
                        candidate_receipt_errors.add(host)
    return {
        host: sorted(statuses | ({"invalid-admission-receipt"}
                                 if host in candidate_receipt_errors else set()))
        for host in sorted(destinations)
        if (statuses := status_by_host.get(host))
        and (statuses != {"in"} or host in candidate_receipt_errors)
        and statuses != {"legacy"}
    }


def _event_destinations(event: dict) -> set[str]:
    """Extract explicit network destinations without treating artifact paths as hosts."""
    text = _tool_text(event)
    destinations: set[str] = set()
    for raw_url in re.findall(r"(?i)\b(?:https?|wss?)://[^\s\"'<>]+", text):
        try:
            host = urlsplit(raw_url.rstrip(",);]}")).hostname or ""
        except ValueError:
            host = ""
        host = host.strip().lower().rstrip(".")
        if host:
            destinations.add(host)

    command = str((event.get("tool_input") or {}).get("command") or "") \
        if isinstance(event.get("tool_input"), dict) else ""
    try:
        tokens = shlex.split(command)
    except ValueError:
        tokens = []
    file_suffixes = {
        ".diff", ".gif", ".html", ".json", ".jsonl", ".log", ".md",
        ".png", ".py", ".replay", ".txt", ".yaml", ".yml",
    }
    bare_host = re.compile(
        r"(?i)^(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+"
        r"[a-z]{2,63}(?::\d+)?(?:/.*)?$"
    )
    for token in tokens:
        candidate = token.strip("[](),;\"'")
        if not candidate or "://" in candidate or "/" in candidate:
            continue
        host_candidate = candidate.rsplit(":", 1)[0] if candidate.count(":") == 1 else candidate
        try:
            destinations.add(str(ipaddress.ip_address(host_candidate)).lower())
            continue
        except ValueError:
            pass
        if Path(host_candidate).suffix.lower() in file_suffixes or not bare_host.fullmatch(candidate):
            continue
        try:
            host = urlsplit("//" + candidate).hostname or ""
        except ValueError:
            host = ""
        if host:
            destinations.add(host.lower().rstrip("."))
    return destinations


def _unassigned_assets(run_dir: Path) -> tuple[list[str], str]:
    try:
        import coverage_matrix  # noqa: WPS433
        data = coverage_matrix.derive(run_dir)
    except Exception as exc:
        return [], f"{exc.__class__.__name__}: coverage derivation failed"
    if any(run_dir.glob("**/coverage.json")) and not data.get("rows"):
        return [], "coverage file exists but no valid asset rows were derived"
    return ([str(item.get("asset") or "") for item in data.get("accounting_gaps", [])
             if str(item.get("asset") or "")], "")


def _proxy_egress_reason(run_dir: Path, event: dict) -> str:
    """Deny target egress paths that cannot prove use of the engagement proxy."""
    tool = str(event.get("tool_name") or "")
    tool_input = event.get("tool_input") if isinstance(event.get("tool_input"), dict) else {}
    command = str(tool_input.get("command") or "")
    if tool == "Bash" and RAW_NETWORK_CLIENT_RE.search(command):
        return (
            "交战代理硬门：active run 禁止使用裸 curl/wget/httpx/nuclei/sqlmap/requests/urllib/socket；"
            "请走项目的 proxy-aware guarded tools。"
        )
    touched, coverage_error = _event_known_hosts(run_dir, event)
    if coverage_error:
        return "资产覆盖硬门：无法派生目标资产账本，拒绝在未知 scope/代理状态下执行：" + coverage_error
    if tool == "WebFetch":
        return (
            "交战代理硬门：active run 中 WebFetch 无法证明经过 XUNJI_PROXY，且未知目标会"
            "绕过资产账本；目标请求必须改用 tools/probe.py/render.py/scan.py，公共资料研究"
            "使用 WebSearch/知识工具。"
        )
    if tool != "Bash":
        if touched or _event_destinations(event):
            return (
                "交战代理硬门：该非 Bash 网络工具无法证明经过 XUNJI_PROXY；"
                "目标请求必须改用 proxy-aware project tools。"
            )
        return ""
    try:
        tokens = shlex.split(command)
    except ValueError:
        return "交战代理硬门：无法解析目标命令，拒绝可能的直连出口。"
    approved = False
    for token in tokens:
        if not token.endswith(".py"):
            continue
        path = Path(token)
        if not path.is_absolute():
            path = ROOT / path
        try:
            approved = path.resolve() in PROXY_AWARE_TARGET_TOOLS
        except Exception:
            approved = False
        if approved:
            break
    if approved:
        rows, inventory_error = _coverage_rows(run_dir)
        if inventory_error:
            return "资产覆盖硬门：无法派生目标资产账本：" + inventory_error
        if not rows:
            return "资产覆盖硬门：proxy-aware 目标工具执行前必须先建立 coverage/asset ledger。"
        destinations = _event_destinations(event)
        unapproved = _unapproved_scope_destinations(run_dir, rows, destinations)
        if unapproved:
            detail = ", ".join(
                f"{host}={'/'.join(statuses)}"
                for host, statuses in unapproved.items()
            )
            return (
                "资产 scope 准入硬门：coverage ledger 中的 review/out/unknown 只是候选，"
                "不能由 source、AI、front 或工具输出提升为 operator authority；"
                "先取得当前操作者的零探测精确准入并由受控工具更新账本。待准入: "
                + detail
            )
        unknown = sorted(destinations - _coverage_hostnames(rows))
        if unknown:
            return (
                "资产覆盖硬门：proxy-aware 目标工具只能访问 coverage ledger 已声明的 host/IP；"
                "未知目标: " + ", ".join(unknown)
            )
    if not approved:
        if not touched:
            return ""
        return (
            "交战代理硬门：该目标命令未绑定项目的 proxy-aware 工具，无法证明出口代理；"
            "改用 tools/probe.py、render.py 或 scan.py。"
        )
    return ""


def _is_target_action(event: dict) -> bool:
    tool = str(event.get("tool_name") or "")
    tool_input = event.get("tool_input") if isinstance(event.get("tool_input"), dict) else {}
    command = str(tool_input.get("command") or "")
    tool_env = tool_input.get("env") if isinstance(tool_input.get("env"), dict) else {}
    if tool == "Bash":
        if not tool_env and _readonly_shell(command):
            return False
        capability = _registered_capability_invocation(
            command, tool_env=tool_env,
        )
        if capability is not None:
            return capability[0].effect == "target"
        # Unknown shell remains target-capable.  It may also mutate locally,
        # but it never gains a lower effect merely because no URL was visible.
        return True
    # WebFetch remains target-capable. Do not let a future NON_EGRESS_TOOLS
    # entry silently weaken the fail-closed network boundary.
    if tool == "WebFetch":
        return True
    if tool in NON_EGRESS_TOOLS:
        return False
    return bool(_event_destinations(event))


def _denial_is_target_action(event: dict, reason: str) -> bool:
    """Separate target-result denials from local control-plane policy denials."""
    if E_LIFECYCLE_EXACT_ARGV_REQUIRED in reason:
        details = _registered_capability_chain_details(
            event, allow_invalid=True)
        if details is not None:
            chain = details[0]
            return any(
                spec.effect == "target"
                for spec, _invocation, _segment in chain
            )
    local_policy_markers = (
        "active-run 指针",
        "清除 active-run 指针必须由当前操作者 prompt 明确授权",
        "长期记忆写入需要操作者",
        "peer_review 不得后台运行",
        "setup transaction",
        "框架维护",
        "/xunji-maintenance",
        E_LIFECYCLE_EXACT_ARGV_REQUIRED,
    )
    if any(marker in reason for marker in local_policy_markers):
        return False
    tool = str(event.get("tool_name") or "")
    if tool != "Bash":
        return _is_target_action(event)
    tool_input = event.get("tool_input") \
        if isinstance(event.get("tool_input"), dict) else {}
    command = str(tool_input.get("command") or "")
    tool_env = tool_input.get("env") \
        if isinstance(tool_input.get("env"), dict) else {}
    if not tool_env and _readonly_shell(command):
        return False
    capability = _registered_capability_invocation(
        command, tool_env=tool_env,
    )
    if capability is not None:
        return capability[0].effect == "target"
    # Execution authorization intentionally keeps unknown Bash target-capable.
    # A denial receipt is narrower: destination-free local shell must not mint
    # permanent target-result debt merely because its command shape was denied.
    return bool(_event_destinations(event))


def _setup_transaction_reason(run_dir: Path) -> str:
    """Block work while a published setup transaction is not committed."""
    path = run_dir / "state" / "setup_transaction.json"
    if not path.exists():
        return ""  # legacy run
    try:
        receipt = json.loads(path.read_text(encoding="utf-8", errors="strict"))
    except Exception:
        return "setup transaction receipt is unreadable; only read/recovery lifecycle actions are allowed."
    if not isinstance(receipt, dict) or receipt.get("schema") != "xunji.setup_transaction.v1":
        return "setup transaction receipt schema is invalid; only read/recovery lifecycle actions are allowed."
    status = str(receipt.get("status") or "")
    if status not in {"committed", "recovered"}:
        return (
            f"setup transaction is {status or 'unknown'}, not committed; "
            "only read/recovery lifecycle actions are allowed and CronCreate remains blocked."
        )
    return ""


def _scope_admission_invocation(
    invocation: tuple[Path, list[str]] | None,
) -> dict | None:
    if not invocation or invocation[0].name != "scope_admission.py":
        return None
    try:
        return scope_admission.parse_invocation(invocation[1])
    except scope_admission.ScopeAdmissionError:
        return None


def _scope_admission_pretool_reason(
    run_dir: Path, event: dict, contract: dict,
) -> str:
    """Make the admission turn local-only and bind one exact controlled write."""
    tool = str(event.get("tool_name") or "")
    tool_input = event.get("tool_input") if isinstance(event.get("tool_input"), dict) else {}
    command = str(tool_input.get("command") or "")
    tool_env = tool_input.get("env") if isinstance(tool_input.get("env"), dict) else {}
    parse_error = str(contract.get("scope_admission_parse_error") or "")
    if parse_error:
        if tool in {"Read", "Grep", "Glob"}:
            return ""
        return "资产 scope 准入授权格式无效：" + parse_error
    if not contract.get("scope_admission_run"):
        return ""
    if tool in {"Read", "Grep", "Glob"}:
        return ""
    invocation = _control_invocation(command) if tool == "Bash" and not tool_env else None
    parsed = _scope_admission_invocation(invocation)
    expected_assets = list(contract.get("scope_admission_assets") or [])
    if parsed and parsed.get("run_name") == run_dir.name \
            and parsed.get("run_name") == contract.get("scope_admission_run") \
            and parsed.get("assets") == expected_assets:
        return ""
    return (
        "资产 scope 准入回合是 zero-probe local transition：只允许读取和一次与当前"
        " operator 首行完全匹配的 scope_admission.py；禁止 target/network、Agent、Cron、"
        "其他控制面写入或资产集合扩张。"
    )


def evaluate_pretool(run_dir: Path, event: dict, contract: dict) -> str:
    tool = str(event.get("tool_name") or "")
    text = _tool_text(event)
    mode = str(contract.get("mode") or "")
    tool_input = event.get("tool_input") if isinstance(event.get("tool_input"), dict) else {}
    command = str(tool_input.get("command") or "")
    tool_env = tool_input.get("env") if isinstance(tool_input.get("env"), dict) else {}
    registered_capability = _registered_capability_invocation(
        command, tool_env=tool_env) if tool == "Bash" else None
    normalized_capability_env = (
        registered_capability[3] if registered_capability is not None else {}
    )
    direct_env_opt_out = str(
        normalized_capability_env.get(
            "XUNJI_PROXY_REQUIRED",
            tool_env.get("XUNJI_PROXY_REQUIRED", ""),
        )
    ).strip().lower() in {"0", "false", "no", "off"}

    # Exact registered capabilities already passed script identity and typed argv
    # validation.  Do not rescan their quoted data (for example a disposition
    # note naming ``assignments.json``) as if it were an opaque shell write.
    # Unknown or invalid commands still take the fail-closed text heuristic.
    protected_reason = "" if registered_capability is not None \
        else _protected_control_reason(event, run_dir)
    if protected_reason:
        return protected_reason

    if mode == MAINTENANCE:
        return _maintenance_pretool_reason(event, contract)

    if contract.get("scope_admission_run") or contract.get("scope_admission_parse_error"):
        return _scope_admission_pretool_reason(run_dir, event, contract)

    shape_reason = _lifecycle_shape_reason(event)
    if shape_reason:
        return shape_reason

    critical_reason = _critical_maintenance_reason(event)
    if critical_reason:
        return critical_reason

    capability_reason = _capability_policy_reason(
        run_dir, registered_capability)
    if capability_reason:
        return capability_reason

    control_invocation = _control_invocation(command) if tool == "Bash" else None
    invocation = _lifecycle_invocation(
        command, tool_env=tool_env) if tool == "Bash" else None
    invocation = invocation or control_invocation
    if invocation and invocation[0].name in {
            "setup_run.py", "loop_bootstrap.py", "xunji_statusline.py"} \
            and tool_env:
        return (
            "lifecycle control 禁止 tool_input.env 覆盖；解释器、PATH 与 setup 输入必须"
            "保持 hook/commit 可复现。"
        )
    clear_active_reason = _clear_active_reason(invocation)
    if clear_active_reason:
        return clear_active_reason
    if invocation:
        lifecycle_reason = _lifecycle_authority_reason(
            run_dir, invocation, contract)
        if lifecycle_reason:
            return lifecycle_reason
    if invocation and invocation[0].name == "xunji_statusline.py" \
            and "--set-active" in invocation[1]:
        try:
            target_arg = invocation[1][invocation[1].index("--set-active") + 1]
        except (ValueError, IndexError):
            return "--set-active 缺少 run 路径。"
        if _contract_lifecycle_operation(contract) != "resume" \
                or not _run_authority_matches(target_arg, contract, run_dir):
            return (
                "--set-active 目标必须由当前操作者 prompt 以唯一 runs/<name> 明确点名；"
                "source/setup turn 或 URL/path 子串不得切换到无关 run。"
            )
    setup_transaction_reason = _setup_transaction_reason(run_dir)
    lifecycle_recovery = bool(invocation and invocation[0].name in {
        "setup_run.py", "loop_bootstrap.py", "xunji_statusline.py",
    })
    if setup_transaction_reason and tool not in {
            "Read", "Grep", "Glob", "CronList"} and not lifecycle_recovery:
        return setup_transaction_reason

    if MEMORY_PATH_RE.search(text) and not contract.get("memory_approved"):
        memory_read = tool in {"Read", "Grep", "Glob"} or (
            tool == "Bash" and not tool_env and _readonly_shell(command)
        )
        if not memory_read:
            return "长期记忆写入需要操作者在当前 prompt 明确批准；retrospective 不能自行升级为 memory。"
    if tool == "Bash" and BACKGROUND_REVIEW_RE.search(command):
        return "peer_review 不得后台运行并与可变 evidence 并发；请前台冻结快照后完成复审。"
    if tool == "Bash" and (DIRECT_EGRESS_ENV_RE.search(text) or direct_env_opt_out) \
            and not contract.get("direct_egress_approved"):
        return (
            "交战代理硬门：XUNJI_PROXY_REQUIRED=0 只能由当前操作者 prompt 明确批准直连；"
            "模型或历史环境变量不能自行关闭 fail-closed。"
        )

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

    if contract.get("web_tools_denied") and (
            tool in {"WebFetch", "WebSearch"}
            or "browser" in tool.lower()):
        return (
            "[XUNJI_E_OPERATOR_EFFECT_DENIED] 当前顶层操作者明确禁止 "
            "WebFetch/WebSearch/浏览器；本回合只能继续本地离线工作。"
        )
    if contract.get("target_egress_denied"):
        if _is_target_action(event):
            return (
                "[XUNJI_E_OPERATOR_EFFECT_DENIED] 当前顶层操作者明确禁止"
                "目标出站/探测/扫描；保留本地读取、验证、Reviewer 和"
                "无网络 Agent lane。"
            )
        if tool == "Agent":
            agent_prompt = str(tool_input.get("prompt") or "")
            assignment, front = runtime_receipts._assignment_fields(agent_prompt)
            assignment_record = _assignment_record(run_dir, assignment, front) \
                if assignment else {}
            if str((assignment_record or {}).get("effect") or "") == "target":
                return (
                    "[XUNJI_E_OPERATOR_EFFECT_DENIED] 当前顶层操作者明确禁止"
                    "目标出站；不得启动 effect=target 的 Agent assignment。"
                )

    if tool == "CronCreate":
        if _new_run_transition_pending(contract, run_dir):
            return (
                f"[{E_NEW_RUN_SETUP_REQUIRED}] Cron 单实例门：当前 prompt 要求创建新 run；"
                "先完成 setup 并切换 contract，再对新 run 执行 CronList/CronCreate。"
            )
        cron_ok, cron_note = runtime_receipts.cron_quiescent(
            run_dir,
            session_id=str(contract.get("session_id") or ""),
            since=float(contract.get("updated_at") or 0.0),
        )
        if not cron_ok:
            return (
                f"[{E_CRON_LIST_REQUIRED}] Cron 单实例门：创建 /loop 前必须先 CronList "
                "证明本 run 无现存任务。" + cron_note
            )
        if run_dir.name.lower() not in text.lower():
            return (
                f"[{E_CRON_RUN_MISMATCH}] Cron 单实例门：CronCreate prompt 必须显式"
                "包含当前 run 目录名。"
            )
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

    settlement_reason = _root_settlement_reason(run_dir, event)
    if settlement_reason:
        return settlement_reason

    iteration_gate_reason = _loop_iteration_gate_reason(run_dir, event, contract)
    if iteration_gate_reason:
        return iteration_gate_reason

    state, _ = _safe_run_summary(run_dir)
    frontier_exists = (run_dir / "frontier.md").exists()
    state_invalid = not frontier_exists or (
        not state.get("fronts") or bool(state.get("schema_errors"))
    )
    if state_invalid and (
        tool == "WebFetch" or (tool == "Bash" and not _fanout_control_bash(
            command, tool_env=tool_env))
    ):
        return (
            "canonical frontier 状态缺失或有 schema error；active run 按 fail-closed "
            "禁止目标动作，先修复 frontier.md 的 Status/Barrier class/Current depth。"
        )
    if _is_target_action(event):
        proxy_reason = _proxy_egress_reason(run_dir, event)
        if proxy_reason:
            return proxy_reason
        unassigned_assets, coverage_error = _unassigned_assets(run_dir)
        touched_hosts, host_error = _event_known_hosts(run_dir, event)
        if coverage_error or host_error:
            return "资产覆盖硬门：账本派生失败，拒绝 fail-open：" + (coverage_error or host_error)
        if touched_hosts and unassigned_assets:
            shown = ", ".join(unassigned_assets[:8])
            return (
                f"资产覆盖硬门：仍有 {len(unassigned_assets)} 个 reachable/unknown 范围内资产未映射到"
                f"任何 front/assignment（{shown}{' …' if len(unassigned_assets) > 8 else ''}）。"
                "先在 frontier.md 逐资产点名；宽泛 F-id 不能代替资产账本。"
            )
    if tool == "Bash" and not _audited_bash_execution(event):
        return (
            "普通 /loop 的 Bash 只能执行无环境覆盖的只读 grammar、受控 lifecycle/verification，"
            "或受信 target/review capability；未知 shell/interpreter 可能改写安全关键框架，"
            "按 fail-closed 拒绝。请在新顶层 prompt 直接说明要修复的 Xunji 框架问题。"
        )
    actor_agent_id = str(event.get("agent_id") or "").strip()
    if actor_agent_id:
        if tool == "Agent":
            return "Agent Board 强制：只有 Root 可派 Agent；子 Agent 不得嵌套派生新 Agent。"
        actor = runtime_receipts.agent_actor(run_dir, actor_agent_id)
        if not actor:
            return "Agent Board 强制：当前子 Agent 没有 transcript-backed assignment attempt，拒绝执行。"
        if actor.get("state") != "running":
            return "Agent Board 强制：该子 Agent attempt 已返回，不能在 SubagentStop 后继续执行。"
        if actor.get("kind") == "completion_review":
            if tool in {"Read", "Grep", "Glob"} or (
                    tool == "Bash" and not tool_env and _readonly_shell(command)):
                return ""
            return "Completion review Agent 只允许读取冻结的 run 状态；不得修改、探测或再派 Agent。"
        rec = _assignment_record(
            run_dir, str(actor.get("assignment") or ""), str(actor.get("front") or ""))
        if not rec:
            return "Agent Board 强制：子 Agent attempt 对应的 assignment/front 已失效。"
        if rec.get("schema") == "xunji.assignment.v1":
            integrity_reason = _instruction_integrity_reason(
                run_dir, rec,
                frozen_launch_prompt_sha256=str(
                    actor.get("launch_prompt_sha256") or ""),
            )
            if integrity_reason:
                return integrity_reason
        if str(rec.get("lane_id") or "") and str(actor.get("lane_id") or "") \
                != str(rec.get("lane_id") or ""):
            return "Agent Board 强制：子 Agent runtime attempt 与 assignment lane 不一致。"
        if str(rec.get("plan_digest") or "") and str(actor.get("plan_digest") or "") \
                != str(rec.get("plan_digest") or ""):
            return "Agent Board 强制：子 Agent runtime attempt 与 assignment plan 不一致。"
        lane_effect = str(rec.get("effect") or "")
        effective = _event_effect(event)
        allowed_effects = {
            "local_read": {"local_read"},
            "local_verify": {"local_read", "local_verify"},
            "target": {"local_read", "local_verify", "target"},
            "model_egress": {"local_read", "local_verify", "model_egress"},
        }.get(lane_effect, set())
        if effective and lane_effect and effective not in allowed_effects:
            return (
                "Agent Board effect 边界：子 Agent capability effect="
                f"{effective} 超出 assignment lane effect={lane_effect}。"
            )
        assigned_assets = set(_normalized_assets(rec.get("assets")))
        if _is_target_action(event) and not assigned_assets:
            return (
                "Agent Board 资产边界：legacy/空资产 assignment 不具备目标执行权限；"
                "Root 必须创建带显式 asset package 的新 assignment。"
            )
        if _is_target_action(event):
            touched, coverage_error = _event_known_hosts(run_dir, event)
            if coverage_error:
                return "Agent Board 资产边界：无法派生资产账本，拒绝 fail-open：" + coverage_error
            outside = sorted(touched - assigned_assets)
            if outside:
                return (
                    "Agent Board 资产边界：子 Agent 只能操作 assignment 的显式资产包；越界资产: "
                    + ", ".join(outside)
                )
        # Child Agents run their own assigned lane. Global Root fan-out and
        # post-return disposition must never block their probe/control actions.
        return ""
    if tool == "Agent":
        raw_input = event.get("tool_input") if isinstance(event.get("tool_input"), dict) else {}
        prompt = str(raw_input.get("prompt") or "")
        completion_reason = _global_completion_gate_reason(run_dir, raw_input)
        if completion_reason is not None:
            return completion_reason
        assignment, front = runtime_receipts._assignment_fields(prompt)
        if not assignment or not front:
            return (
                f"[{E_DELEGATION_REQUIRED}] Agent Board 强制：Agent prompt 必须包含 "
                "XUNJI_ASSIGNMENT=A-... 和 XUNJI_FRONT=F-...。"
            )
        rec = _assignment_record(run_dir, assignment, front)
        if not rec:
            return (
                f"[{E_DELEGATION_REQUIRED}] Agent Board 强制：Agent token 未绑定 "
                "workers.py 生成的 assignment/front。"
            )
        if rec.get("schema") == "xunji.assignment.v1":
            integrity_reason = _instruction_integrity_reason(run_dir, rec)
            if integrity_reason:
                return integrity_reason
        status = str(rec.get("status") or "").strip().lower()
        if status not in {"assigned", "starting"}:
            return (
                f"[{E_DELEGATION_REQUIRED}] Agent Board attempt 唯一性：{assignment} "
                f"status={status or '(missing)'}，"
                "只有 assigned/starting assignment 可启动；重试或续派必须创建新 assignment。"
            )
        expected_assets = _normalized_assets(rec.get("assets"))
        prompt_assets = runtime_receipts._assignment_assets(prompt)
        if prompt_assets != expected_assets:
            return (
                f"[{E_DELEGATION_REQUIRED}] Agent Board 资产绑定：prompt 必须包含与 "
                "assignment 完全一致的 "
                f"XUNJI_ASSETS={','.join(expected_assets) if expected_assets else 'none'}。"
            )
        expected_lane = str(rec.get("lane_id") or "")
        expected_plan = str(rec.get("plan_digest") or "")
        expected_result = str(rec.get("review_result_digest") or "")
        if rec.get("schema") == "xunji.assignment.v1":
            expected_agent_type = runtime_receipts.assignment_subagent_type(rec)
            if not expected_agent_type or str(
                    raw_input.get("subagent_type") or "") != expected_agent_type:
                return (
                    f"[{E_DELEGATION_REQUIRED}] Agent Board Agent-type 绑定："
                    "subagent_type 必须与 assignment "
                    f"role 精确一致，expected={expected_agent_type or '(invalid role)'}。")
        if expected_lane and runtime_receipts._assignment_lane(prompt) != expected_lane:
            return (
                f"[{E_DELEGATION_REQUIRED}] Agent Board lane 绑定：prompt 的 "
                "XUNJI_LANE 必须与 assignment 完全一致。"
            )
        if expected_plan and runtime_receipts._assignment_plan(prompt) != expected_plan:
            return (
                f"[{E_DELEGATION_REQUIRED}] Agent Board plan 绑定：prompt 的 "
                "XUNJI_PLAN 必须与 assignment 完全一致。"
            )
        if expected_result and runtime_receipts._assignment_result_digest(prompt) != expected_result:
            return (
                f"[{E_DELEGATION_REQUIRED}] Agent Board Reviewer 绑定：prompt 的 "
                "XUNJI_RESULT_DIGEST 必须与冻结 "
                "merge draft 完全一致。")
        expected_prompt = runtime_receipts.assignment_launch_prompt(rec)
        if (expected_lane or expected_plan) and (
                not expected_prompt or prompt != expected_prompt):
            return (
                f"[{E_DELEGATION_REQUIRED}] Agent Board 完整 prompt 绑定："
                "tool_input.prompt 必须与 workers.py "
                "生成值逐字节一致；任何前后缀、附加上下文、重排或空白变化都拒绝。")
        return ""
    if not state.get("fanout_required") or contract.get("fanout_override"):
        return ""
    epoch = coordination_epoch(run_dir, contract)
    if not epoch.get("valid"):
        if tool == "Bash" and _fanout_control_bash(command, tool_env=tool_env):
            return ""
        if tool not in {"Bash", "WebFetch"}:
            return ""
        return (
            "Agent Board coordination epoch 缺失、伪造或已因 front/coverage material change "
            "失效；先提交新的 execute turn/work plan，使 coordination_signature 与 "
            "fanout_epoch_started_at 成对刷新。"
        )
    epoch_since = float(epoch["since"])
    fanout = runtime_receipts.agent_fanout(
        run_dir,
        since=epoch_since,
    )
    if fanout.get("satisfied"):
        if tool == "Bash" and _fanout_control_bash(command, tool_env=tool_env):
            return ""
        if tool == "WebFetch" or tool == "Bash":
            disposition = runtime_receipts.agent_disposition(
                run_dir,
                since=epoch_since,
            )
            if not disposition.get("disposition_satisfied"):
                pending = [str(item) for item in disposition.get("pending", []) if str(item).strip()]
                detail = ("；待处理：" + "；".join(pending[:4])) if pending else ""
                return (
                    "真实 SubagentStop 已返回但尚未完成 post-return disposition；先用 workers.py "
                    "把每个 assignment 更新为带 canonical E/F/D 锚点的 merged/blocked/failed，"
                    "且更新时间必须晚于 Agent 返回。" + detail
                )
        return ""
    if tool == "Bash":
        if not _fanout_control_bash(command, tool_env=tool_env):
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
    normalizations = {
        str(item) for item in (contract.get("intent_normalizations") or [])
        if str(item)
    }
    intent_note = (
        "[Xunji operator intent: NORMALIZED] 已忽略首行无语义水平空白；"
        "原始 prompt hash 与 exact source/effect 绑定保持不变。"
        if "leading_horizontal_whitespace" in normalizations else ""
    )
    effect_note = ""
    if contract.get("target_egress_denied"):
        effect_note += (
            "[Xunji operator effect: TARGET_EGRESS_DENIED] 本回合不得规划、"
            "派发或执行 target lane；只允许本地离线 Hunter/Reviewer/Root 工作。"
        )
    if contract.get("web_tools_denied"):
        effect_note += (
            "[Xunji operator effect: WEB_TOOLS_DENIED] 本回合不得使用 "
            "WebFetch/WebSearch/浏览器。"
        )
    if contract.get("scope_admission_parse_error"):
        return (
            "[Xunji scope admission: INVALID] 未授予任何资产准入权限；"
            + str(contract.get("scope_admission_parse_error") or "")
        )
    if contract.get("scope_admission_run"):
        assets = ", ".join(str(item) for item in (
            contract.get("scope_admission_assets") or []))
        return (
            "[Xunji scope admission: ZERO_PROBE] 当前 operator 首行只授权 active run 的"
            f" exact assets: {assets}。调用受控 scope_admission.py 完成本地 receipt/ledger "
            "transition；本回合禁止 target/network、Agent、Cron，后续新 /loop 回合才可探测。"
        )
    if mode == MAINTENANCE:
        return (
            "[Xunji turn mode: MAINTENANCE] 已从顶层 operator 意图识别本地框架维护。"
            "可用 typed Edit/Write 修改 repository-local 源码、测试和文档；禁止直接写"
            " live-run/Git/control state，禁止 target/network action、Agent、Cron 和 Bash"
            " 直接写文件。run_status/frontier/evidence 不得推进；完成后需自测、复审、提交。"
        )
    if mode == EXPLAIN:
        return "[Xunji turn mode: EXPLAIN_ONLY] 只回答操作者问题；可读文件，不修改、不探测、不派 Agent；本回合无需 Coda。"
    if mode == PAUSE:
        return "[Xunji turn mode: PAUSED_BY_OPERATOR] 保留所有 open fronts；先 CronList/CronDelete，禁止继续渗透；本回合无需 Coda，也不得写 completion marker。"
    if mode == EXECUTE and contract.get("loop_requested"):
        if _new_run_transition_pending(contract, run_dir):
            retry_hint = _python_control_hint(
                ROOT / "tools" / "loop_bootstrap.py",
                ["--source", "<source>", "--type", "auto"],
            )
            return effect_note + intent_note + (
                "[Xunji lifecycle: SETUP_REQUIRED] 当前显式 /loop 要求创建新 run。先在"
                "同一顶层 operator 回合执行 prompt 对应的精确 "
                f"`{retry_hint}`；命令后不得"
                "附加 2>&1、pipe、head/tail 或其他 shell wrapper。setup/activation 成功后，"
                "对新 run 依次 fresh CronList、CronCreate、TaskCreate/TaskUpdate，再做图谱/"
                "front 拆解并真实派发 Agent。形状拒绝应同回合精确重试，不能等裸“继续”。"
            )
        if contract.get("run_transition_requested"):
            return effect_note + intent_note + (
                "[Xunji lifecycle: RUN_BOUND] 新 run 已绑定；按 fresh CronList -> CronCreate"
                "（prompt 精确命名当前 run）-> TaskCreate/TaskUpdate -> graph/fronts -> real "
                "Agent launches -> adjudication/synthesis 推进。Agent/目标动作会在缺少当前"
                "回合回执时 fail closed。"
            )
        return effect_note + intent_note + (
            "[Xunji lifecycle: ITERATION_PLAN_REQUIRED] 当前是显式 /loop；在 Agent/目标"
            "动作前先创建或更新本回合 TaskCreate/TaskUpdate（兼容 TodoWrite）清单，再按"
            "图谱、front、真实 Agent 回执和单一综合者流程推进。"
        )
    state, _ = _safe_run_summary(run_dir)
    fanout = (
        " fanout_required=true (open/probing/working/type-A 均为 active); "
        "先真实调用至少两个不同 front 的 Agent。"
        if state.get("fanout_required") else ""
    )
    return effect_note + "[Xunji turn mode: EXECUTE] 按 run 状态推进，最后写唯一具体 Coda。" + fanout


def _explicit_pointer_rebind(contract: dict, run_dir: Path) -> bool:
    """Require current-prompt operator authority before adopting a stale pointer."""
    if contract.get("mode") != EXECUTE:
        return False
    requested_scope_run = str(contract.get("scope_admission_run") or "")
    if requested_scope_run:
        return requested_scope_run == run_dir.name
    operation = _contract_lifecycle_operation(contract)
    if operation in {"source", "setup"}:
        return bool(
            contract.get("run_transition_requested")
            and not contract.get("source_ambiguous")
            and not contract.get("run_ambiguous")
        )
    if operation == "resume":
        return _run_authority_matches(
            f"runs/{run_dir.name}", contract, run_dir)
    return False


def handle_event(event: dict, run_dir: Path | None = None) -> dict | None:
    supplied_run_dir = run_dir
    hook = str(event.get("hook_event_name") or "")
    if hook in {"SessionStart", "SessionEnd"}:
        # The active pointer is a persistent personal selection, not a
        # session-owned lease. Session lifecycle events never clear/restore it.
        return None
    prompt = str(event.get("prompt") or "") if hook == "UserPromptSubmit" else ""
    if hook == "UserPromptSubmit" and not INTERNAL_PROMPT_RE.search(prompt):
        # Revoke -> pointer resolve -> replacement contract is one prompt
        # transaction under the same lock used by setup commit.
        lock = ACTIVE_RUN_POINTER.parent / setup_transaction.ACTIVATION_LOCK_NAME
        with setup_transaction.exclusive_directory_lock(lock):
            incoming_session, _binding_kind = _event_session_binding(event)
            _revoke_pending_session_unlocked(incoming_session)
            run_dir = supplied_run_dir or explicit_active_run()
            if run_dir is None:
                contract = _write_pending_contract_unlocked(event)
            else:
                previous_session = str(
                    _previous_contract(run_dir).get("session_id") or "")
                if previous_session and previous_session != incoming_session:
                    # The active run has one canonical turn contract.  Replacing
                    # it invalidates claims derived from that exact old contract,
                    # even when another Claude session supplied the new prompt.
                    # Unrelated no-active pending sessions remain isolated.
                    _revoke_transition_claims_unlocked(previous_session)
                contract = write_contract(run_dir, event)
        if run_dir is None:
            if not contract:
                return None
            if contract.get("mode") == MAINTENANCE \
                    or contract.get("loop_requested"):
                context = _context_message(contract, ROOT)
            else:
                context = (
                    "[Xunji bootstrap turn] 当前没有 active run；若操作者要求新建/"
                    "恢复 run，先执行受控 setup/resume。成功 set-active 会原子继承本回合契约。"
                )
            return {
                "hookSpecificOutput": {
                    "hookEventName": "UserPromptSubmit",
                    "additionalContext": context,
                }
            }
        return {
            "hookSpecificOutput": {
                "hookEventName": "UserPromptSubmit",
                "additionalContext": _context_message(contract, run_dir),
            }
        }
    else:
        run_dir = supplied_run_dir or explicit_active_run()
    if run_dir is None:
        if hook == "UserPromptSubmit" and not INTERNAL_PROMPT_RE.search(prompt):
            contract = write_pending_contract(event)
            if contract:
                if contract.get("mode") == MAINTENANCE:
                    context = _context_message(contract, ROOT)
                elif contract.get("loop_requested"):
                    context = _context_message(contract, ROOT)
                else:
                    context = (
                        "[Xunji bootstrap turn] 当前没有 active run；若操作者要求新建/"
                        "恢复 run，先执行受控 setup/resume。成功 set-active 会原子继承本回合契约。"
                    )
                return {
                    "hookSpecificOutput": {
                        "hookEventName": "UserPromptSubmit",
                        "additionalContext": context,
                    }
                }
        if hook == "PreToolUse":
            private_api_reason = _private_lifecycle_api_reason(event)
            if private_api_reason:
                return _deny(private_api_reason)
            protected_reason = _protected_control_reason(event, None)
            if protected_reason:
                return _deny(protected_reason)
            tool = str(event.get("tool_name") or "")
            if tool == "CronCreate":
                return _deny(
                    f"[{E_NEW_RUN_SETUP_REQUIRED}] Xunji CronCreate 前必须先 "
                    "setup/set-active 一个 run，再用当前回合 CronList 证明单实例。"
                )
            pending = load_pending_contract_for_event(event)
            if pending and pending.get("mode") == MAINTENANCE:
                reason = _maintenance_pretool_reason(event, pending)
                return _deny(reason) if reason else None
            shape_reason = _lifecycle_shape_reason(event)
            if shape_reason:
                return _deny(shape_reason)
            command = str((event.get("tool_input") or {}).get("command") or "") \
                if isinstance(event.get("tool_input"), dict) else ""
            invocation = _lifecycle_invocation(command) if tool == "Bash" else None
            args = invocation[1] if invocation else []
            script_name = invocation[0].name if invocation else ""
            clear_active_reason = _clear_active_reason(invocation)
            if clear_active_reason:
                return _deny(clear_active_reason)
            if script_name == "scope_admission.py":
                return _deny(
                    "scope admission requires the exact active run and a current hook-bound operator directive."
                )
            normalizer_prepare = bool(
                invocation
                and script_name == "loop_bootstrap.py"
                and "--prepare-normalizer" in args
            )
            inspection_only = bool(
                invocation
                and ({"--selftest", "--help", "-h"} & set(args)
                     or (script_name == "xunji_statusline.py"
                         and not ({"--set-active", "--clear-active"} & set(args))))
            )
            lifecycle = bool(invocation and (
                script_name in {"setup_run.py", "loop_bootstrap.py"}
                or (script_name == "xunji_statusline.py"
                    and bool({"--set-active", "--clear-active"} & set(args)))
            ) and not inspection_only)
            if inspection_only:
                return None
            if normalizer_prepare:
                if not pending:
                    return _deny(
                        "无 active run 的 external normalizer prepare 必须绑定当前 operator"
                        " bootstrap contract；source 必须由当前 prompt 精确点名并显式写出"
                        " --ai external。")
                reason = evaluate_pretool(ROOT, event, pending)
                return _deny(reason) if reason else None
            if lifecycle:
                if not pending:
                    return _deny(
                        f"[{E_RUN_TRANSITION_AUTHORITY_MISSING}] 无 active run 的 setup/resume/"
                        "set-active 没有匹配当前顶层 human prompt 的 operator intent；先由"
                        " UserPromptSubmit 明确唯一 source/run。空白等无害格式会自动归一化，"
                        "不要调用 setup_transaction 私有 API 绕过。")
                reason = evaluate_pretool(ROOT, event, pending)
                if reason:
                    return _deny(reason)
                target_name = _lifecycle_target_name(invocation)
                if not target_name:
                    return _deny("无法从 lifecycle 命令确定唯一目标 run；拒绝创建 transition claim。")
                try:
                    write_hook_transition_claim(
                        target_name, pending, invocation=invocation)
                except Exception:
                    return _deny("无法原子写入当前 session/目标 run 的 transition claim。")
                return None
            if pending and tool not in {
                    "Read", "Grep", "Glob", "WebSearch", "ListMcpResourcesTool",
                    "ReadMcpResourceTool", "CronList"}:
                return _deny(
                    "当前 session 正在 bootstrap run；绑定 active run 前只允许只读动作和"
                    "受控 setup/resume/set-active，不得先执行目标或任意写操作。")
        return None
    if hook == "UserPromptSubmit":
        if INTERNAL_PROMPT_RE.search(prompt):
            contract = load_contract_for_event(run_dir, event)
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
        private_api_reason = _private_lifecycle_api_reason(event)
        contract = load_contract_for_event(run_dir, event)
        budget_reason = _claim_plan_bound_child_tool_call(run_dir, event)
        reason = private_api_reason or budget_reason \
            or evaluate_pretool(run_dir, event, contract)
        if reason:
            decision_metadata = _decision_metadata(reason, event)
            shape_denial = decision_metadata.get("xunji_decision_code") \
                == E_LIFECYCLE_EXACT_ARGV_REQUIRED
            maintenance_action = False if shape_denial else _maintenance_action(
                event, contract=contract)
            receipt_event = dict(event)
            receipt_event.update({
                "hook_event_name": "PreToolUseDenied",
                "xunji_decision": "deny",
                "xunji_reason": reason,
                "xunji_target_action": _denial_is_target_action(event, reason),
                "xunji_maintenance_action": maintenance_action,
                "xunji_maintenance_paths": _maintenance_receipt_paths(event, contract)
                if maintenance_action else [],
            })
            receipt_event.update(decision_metadata)
            runtime_receipts.append_hook_event(run_dir, receipt_event)
            return _deny(reason)
        command = str((event.get("tool_input") or {}).get("command") or "") \
            if isinstance(event.get("tool_input"), dict) else ""
        control_invocation = _control_invocation(command) \
            if str(event.get("tool_name") or "") == "Bash" else None
        lifecycle_invocation = _lifecycle_invocation(command) \
            if str(event.get("tool_name") or "") == "Bash" else None
        if _scope_admission_invocation(control_invocation):
            try:
                scope_admission.write_hook_claim(run_dir, contract)
            except scope_admission.ScopeAdmissionError:
                return _deny(
                    "无法原子写入当前 session 的 exact scope admission claim；拒绝 fail-open。"
                )
        if lifecycle_invocation and lifecycle_invocation[0].name in {
                "setup_run.py", "loop_bootstrap.py", "xunji_statusline.py"} \
                and not ({"--selftest", "--help", "-h", "--prepare-normalizer"}
                         & set(lifecycle_invocation[1])):
            target_name = _lifecycle_target_name(lifecycle_invocation)
            if target_name and target_name != run_dir.name:
                try:
                    write_hook_transition_claim(
                        target_name, contract, origin_run=run_dir,
                        invocation=lifecycle_invocation)
                except Exception:
                    return _deny(
                        "当前 active-run lifecycle claim 无法绑定 exact session/prompt/"
                        "origin/target；拒绝 fail-open。"
                    )
        if contract.get("loop_requested") and str(event.get("tool_name") or "") == "Bash":
            tool_input = event.get("tool_input") \
                if isinstance(event.get("tool_input"), dict) else {}
            root_capability = _registered_capability_invocation(
                str(tool_input.get("command") or ""),
                tool_env=tool_input.get("env")
                if isinstance(tool_input.get("env"), dict) else {},
            )
            if root_capability is not None:
                try:
                    plan = work_plan.current_plan(run_dir, contract)
                except work_plan.PlanError:
                    plan = {}
                lanes = plan.get("lanes") if isinstance(plan.get("lanes"), list) else []
                if plan.get("execution_mode") == "ROOT_DIRECT" and len(lanes) == 1 \
                        and str(lanes[0].get("capability_id") or "") \
                        == root_capability[0].id:
                    claim_event = dict(event)
                    claim_event["xunji_capability_id"] = root_capability[0].id
                    claim_event["xunji_capability_effect"] = root_capability[0].effect
                    claim_event["xunji_capability_recorder"] = root_capability[0].recorder
                    binding = {
                        "plan_id": str(plan.get("plan_id") or ""),
                        "plan_digest": str(plan.get("plan_digest") or ""),
                        "cycle_id": int(plan.get("cycle_id") or 0),
                        "lane_id": str(lanes[0].get("id") or ""),
                        "capability_id": root_capability[0].id,
                        "effect": root_capability[0].effect,
                        "session_id": str(contract.get("session_id") or ""),
                        "prompt_sha256": str(contract.get("prompt_sha256") or ""),
                    }
                    try:
                        runtime_receipts.claim_root_action(
                            run_dir, claim_event, binding)
                    except Exception as exc:
                        return _deny(
                            f"[{E_DELEGATION_REQUIRED}] ROOT_DIRECT claim 无法原子冻结或"
                            f"与既有动作冲突：{exc}"
                        )
        return _plan_bound_child_budget_context(event)
    if hook in {"PostToolUse", "PostToolUseFailure", "SubagentStart", "SubagentStop"}:
        tool_name = str(event.get("tool_name") or "")
        command = str((event.get("tool_input") or {}).get("command") or "") \
            if isinstance(event.get("tool_input"), dict) else ""
        tool_input = event.get("tool_input") \
            if isinstance(event.get("tool_input"), dict) else {}
        tool_env = tool_input.get("env") \
            if isinstance(tool_input.get("env"), dict) else {}
        capability = _registered_capability_invocation(
            command, tool_env=tool_env) if tool_name == "Bash" else None
        target_action = _is_target_action(event)
        contract = load_contract_for_event(run_dir, event)
        maintenance_action = _maintenance_action(event, contract=contract)
        invocation = _control_invocation(command) if tool_name == "Bash" else None
        scope_admission_action = bool(_scope_admission_invocation(invocation))
        if hook in {"SubagentStart", "SubagentStop"} or tool_name in {
            "Agent", "CronCreate", "CronDelete", "CronList",
            "TaskCreate", "TaskUpdate", "TodoWrite",
        } or target_action or maintenance_action or scope_admission_action \
                or bool(capability and (
                    capability[0].recorder != "none"
                    or capability[0].root_direct_eligible is True
                )):
            receipt_event = dict(event)
            receipt_event["xunji_target_action"] = target_action
            receipt_event["xunji_maintenance_action"] = maintenance_action
            receipt_event["xunji_scope_admission_action"] = scope_admission_action
            receipt_event["xunji_capability_id"] = (
                capability[0].id if capability else "")
            receipt_event["xunji_capability_effect"] = (
                capability[0].effect if capability else "")
            receipt_event["xunji_capability_recorder"] = (
                capability[0].recorder if capability else "")
            receipt_event["xunji_maintenance_paths"] = (
                _maintenance_receipt_paths(event, contract) if maintenance_action else [])
            runtime_receipts.append_hook_event(run_dir, receipt_event)
        return None
    return None


def _selftest() -> int:
    import subprocess
    import workers
    from harness.selftest_plan import seed_current_plan
    from unittest import mock

    def seed_activate_effect(target_name: str) -> dict:
        profile = setup_transaction.lifecycle_effect_profile(
            setup_transaction.OP_STATUSLINE_SET_ACTIVE, target_name)
        return setup_transaction.transition_effect(
            "activate", target_name, profile=profile)

    root = Path(tempfile.mkdtemp())
    (root / "recon.json").write_text(json.dumps({
        "assets": [{"host": "bootstrap.example"}],
    }), encoding="utf-8")
    effect_source = root / "effect-source.md"
    effect_source.write_text(
        "- Target: https://effect.example.test/\n", encoding="utf-8")
    run = root / "run"
    (run / "state").mkdir(parents=True)
    (run / "agents").mkdir()
    front_specs = (
        ("app", "example.test public app"),
        ("auth", "auth.example.test login"),
        ("network", "network review"),
        ("none", "workflow review"),
    )
    (run / "frontier.md").write_text(
        "# Frontier\n## Open Fronts\n" + "".join(
            f"### F-{idx:03d}\n- Front: {label}\n- Status: open\n"
            f"- Barrier class: {barrier}\n- Current depth: shallow\n"
            for idx, (barrier, label) in enumerate(front_specs, 1)
        ), encoding="utf-8")
    (run / "coverage.json").write_text(json.dumps({"assets": [
        {"host": "example.test", "reachable": True, "examined": False},
        {"host": "auth.example.test", "reachable": True, "examined": False},
    ]}), encoding="utf-8")
    (run / "agents" / "A-web-001.md").write_text("# Agent\n", encoding="utf-8")
    (run / "agents" / "A-auth-001.md").write_text("# Agent\n", encoding="utf-8")
    (run / "state" / "assignments.json").write_text(json.dumps({"assignments": [
        {"agent": "A-web-001", "front": "F-001", "status": "assigned",
         "assets": ["example.test"]},
        {"agent": "A-auth-001", "front": "F-002", "status": "assigned",
         "assets": ["auth.example.test"]},
    ]}), encoding="utf-8")
    explain = classify_prompt("为什么不用 Agent？只告诉我原因，不用修改")
    history_only = classify_prompt("这是这几次的历史，你来看看还有什么问题")
    ambiguous = classify_prompt("这是最新状态")
    pause = classify_prompt("停止loop，渗透结束")
    execute = classify_prompt("彻底修复所有问题")
    indirect_english = classify_prompt("Please deploy the prepared workflow")
    no_run_question = classify_prompt("what runs exist?", active_run=False)
    active_run_question = classify_prompt("active run 是什么？")
    active_run_switch = classify_prompt("switch active run to runs/other_20260101")
    restricted_loop_contract = _contract_from_event({
        "prompt": (
            f"/loop runs/{run.name}\n"
            "Repository source and settings remain read-only. "
            "Do not Edit/Write settings and do not create evidence IDs. "
            "不要修改 Xunji 框架源码。"
        ),
        "session_id": "restricted-loop-session",
    }, run_name=run.name)
    denied_loop_contract = _contract_from_event({
        "prompt": f"/loop runs/{run.name}\nDo not resume run runs/{run.name}.",
        "session_id": "denied-loop-session",
    }, run_name=run.name)
    negated_direct_cn = _contract_from_event({"prompt": "不要允许直连，继续使用代理"})
    negated_direct_en = _contract_from_event({"prompt": "do not allow direct egress"})
    explicit_direct = _contract_from_event({"prompt": "明确允许本回合直连"})
    scope_prompt = (
        "/xunji-scope-admit --run runs/pilot_20260715 "
        "--assets one.example.test,two.example.test --reason operator-confirmed-scope"
    )
    scope_contract = _contract_from_event({
        "prompt": scope_prompt, "session_id": "scope-session",
    })
    malformed_scope_contract = _contract_from_event({
        "prompt": "/xunji-scope-admit --run runs/pilot_20260715 --assets '*' --reason bad",
        "session_id": "scope-session",
    })
    contract = {
        "mode": EXECUTE,
        "session_id": "s",
        "prompt_excerpt": "/loop 重新开一个新 run",
        "origin_run": run.name,
        "bound_run": run.name,
        "updated_at": time.time(),
        "coordination_signature": _coordination_signature(run),
        "fanout_epoch_started_at": time.time() - 1,
        "fanout_epoch_id": "0123456789abcdef",
    }
    target_event = {"tool_name": "Bash", "tool_input": {
        "command": "python3 tools/probe.py GET https://example.test"}}
    scope_turn_target_blocked = "zero-probe local transition" in evaluate_pretool(
        run, target_event, scope_contract)
    malformed_scope_write_blocked = bool(evaluate_pretool(
        run, {"tool_name": "Write", "tool_input": {"file_path": str(run / "frontier.md")}},
        malformed_scope_contract,
    ))
    with mock.patch.object(run_model, "summary", side_effect=RuntimeError("broken state")):
        summary_failure_signature = _coordination_signature(run)
        summary_failure_reason = evaluate_pretool(run, target_event, contract)
    encoded_target = {"tool_name": "Bash", "tool_input": {
        "command": "python3 -c 'import socket; socket.create_connection((\"example.test\",443))'"}}
    renamed_target = {"tool_name": "Bash", "tool_input": {"command": "python3 /tmp/check.py"}}
    workers_control = {"tool_name": "Bash", "tool_input": {
        "command": f"python3 {ROOT / 'tools' / 'workers.py'} list {run}"}}
    workers_asset_control = {"tool_name": "Bash", "tool_input": {
        "command": (
            f"python3 {ROOT / 'tools' / 'workers.py'} assign {run} "
            "--role web-hunter --front F-001 --asset example.test"
        )}}
    workers_quoted_note_control = {"tool_name": "Bash", "tool_input": {
        "command": (
            f"python3 {ROOT / 'tools' / 'workers.py'} finish {run} A-web-001 "
            '--status blocked --note "Reason: shared barrier; Front: F-001"'
        )}}
    workers_protected_name_note_control = {"tool_name": "Bash", "tool_input": {
        "command": (
            f"python3 {ROOT / 'tools' / 'workers.py'} review-disposition {run} "
            "A-web-001 A-review-001 --status accept-candidate "
            '--note "Reviewed assignments.json and runtime_events.jsonl bindings"'
        )}}
    workers_quoted_punctuation_control = {"tool_name": "Bash", "tool_input": {
        "command": (
            f"python3 {ROOT / 'tools' / 'workers.py'} finish {run} A-web-001 "
            '--status blocked --note "Reason: auth; pipe | amp & gt > lt <; Front: F-001"'
        )}}
    workers_single_quoted_literal_control = {"tool_name": "Bash", "tool_input": {
        "command": (
            f"python3 {ROOT / 'tools' / 'workers.py'} finish {run} A-web-001 "
            "--status blocked --note 'Reason: literal $(id) ${HOME} `id`; Front: F-001'"
        )}}
    workers_escaped_substitution_literal = {"tool_name": "Bash", "tool_input": {
        "command": (
            f"python3 {ROOT / 'tools' / 'workers.py'} finish {run} A-web-001 "
            '--status blocked --note "Reason: literal \\$(id); Front: F-001"'
        )}}
    workers_ansi_c_literal_control = {"tool_name": "Bash", "tool_input": {
        "command": (
            f"python3 {ROOT / 'tools' / 'workers.py'} finish {run} A-web-001 "
            "--status blocked --note $'Reason: literal $(id); Front: F-001'"
        )}}
    workers_trailing_comment_control = {"tool_name": "Bash", "tool_input": {
        "command": f"python3 {ROOT / 'tools' / 'workers.py'} list {run} # ignored"}}
    workers_shell_chain = (
        f"python3 {ROOT / 'tools' / 'workers.py'} list {run}; echo unsafe")
    adversarial_control_commands = [
        f"python3 {ROOT / 'tools' / 'workers.py'} list {run} | cat",
        f"python3 {ROOT / 'tools' / 'workers.py'} list {run} && echo unsafe",
        f"python3 {ROOT / 'tools' / 'workers.py'} list {run} > /tmp/forged",
        f"python3 {ROOT / 'tools' / 'workers.py'} list {run} 2>&1",
        (f"python3 {ROOT / 'tools' / 'workers.py'} finish {run} A-web-001 "
         '--status blocked --note "Reason: $(id); Front: F-001"'),
        (f"python3 {ROOT / 'tools' / 'workers.py'} finish {run} A-web-001 "
         '--status blocked --note "Reason: ${HOME}; Front: F-001"'),
        (f"python3 {ROOT / 'tools' / 'workers.py'} finish {run} A-web-001 "
         '--status blocked --note "Reason: `id`; Front: F-001"'),
        (f"python3 {ROOT / 'tools' / 'workers.py'} finish {run} A-web-001 "
         '--status blocked --note "Reason: \\\\$(id); Front: F-001"'),
        (f"python3 {ROOT / 'tools' / 'workers.py'} finish {run} A-web-001 "
         "--status blocked --note <(id)"),
        (f"python3 {ROOT / 'tools' / 'workers.py'} finish {run} A-web-001 "
         "--status blocked --note >(id)"),
        f"python3 {ROOT / 'tools' / 'workers.py'} list {run} # ignored $(id)",
        f"python3 {ROOT / 'tools' / 'workers.py'} list '{run}",
        f"python3 {ROOT / 'tools' / 'workers.py'} list {run} \\",
    ]
    setup_control = {"tool_name": "Bash", "tool_input": {
        "command": f"python3 {ROOT / 'tools' / 'setup_run.py'} next {root / 'recon.json'}"}}
    setup_operator_contract = _contract_from_event({
        "prompt": f"/loop {root / 'recon.json'} 创建新 run，slug next",
        "session_id": "setup-session",
    }, run_name=run.name)
    setup_classify_control = {"tool_name": "Bash", "tool_input": {
        "command": (
            f"python3 {ROOT / 'tools' / 'setup_run.py'} "
            f"next {root / 'recon.json'} --classify"
        )}}
    setup_classify_contract = _contract_from_event({
        "prompt": (
            f"/loop {root / 'recon.json'} 创建新 run，slug next --classify"
        ),
        "session_id": "setup-classify-session",
    }, run_name=run.name)
    setup_classify_denied_contract = _contract_from_event({
        "prompt": (
            f"/loop {root / 'recon.json'} 创建新 run，slug next；"
            "不要使用 --classify"
        ),
        "session_id": "setup-classify-denied-session",
    }, run_name=run.name)
    long_prompt_padding = "背景说明" * 160
    setup_classify_late_opt_in_contract = _contract_from_event({
        "prompt": (
            f"/loop {root / 'recon.json'} 创建新 run，slug next "
            f"{long_prompt_padding} --classify"
        ),
        "session_id": "setup-classify-late-opt-in-session",
    }, run_name=run.name)
    setup_classify_late_denial_contract = _contract_from_event({
        "prompt": (
            f"/loop {root / 'recon.json'} 创建新 run，slug next --classify "
            f"{long_prompt_padding} 不要使用 --classify"
        ),
        "session_id": "setup-classify-late-denial-session",
    }, run_name=run.name)
    setup_classify_quoted_opt_in_contract = _contract_from_event({
        "prompt": (
            f"/loop {root / 'recon.json'} 创建新 run，slug next\n"
            "> --classify"
        ),
        "session_id": "setup-classify-quoted-opt-in-session",
    }, run_name=run.name)
    setup_late_slug_contract = _contract_from_event({
        "prompt": (
            f"/loop {root / 'recon.json'} 创建新 run "
            f"{long_prompt_padding} slug next"
        ),
        "session_id": "setup-late-slug-session",
    }, run_name=run.name)
    setup_quoted_slug_contract = _contract_from_event({
        "prompt": (
            f"/loop {root / 'recon.json'} 创建新 run\n"
            "> slug next"
        ),
        "session_id": "setup-quoted-slug-session",
    }, run_name=run.name)
    source_url = "https://new-source.example/path?key=opaque-secret"
    source_control = {"tool_name": "Bash", "tool_input": {
        "command": (
            f"python3 {ROOT / 'tools' / 'loop_bootstrap.py'} "
            f"--source '{source_url}' --type auto"
        )}}
    source_operator_contract = _contract_from_event({
        "prompt": f"/loop {source_url} 创建新 run",
        "session_id": "shape-session",
    }, run_name=run.name)
    punctuated_source_url = "https://punct.example/path)"
    punctuated_source_control = {"tool_name": "Bash", "tool_input": {
        "command": (
            f"python3 {ROOT / 'tools' / 'loop_bootstrap.py'} "
            f"--source '{punctuated_source_url}' --type auto"
        ),
    }}
    trimmed_punctuated_source_control = {"tool_name": "Bash", "tool_input": {
        "command": (
            f"python3 {ROOT / 'tools' / 'loop_bootstrap.py'} "
            "--source 'https://punct.example/path' --type auto"
        ),
    }}
    punctuated_source_contract = _contract_from_event({
        "prompt": f"/loop '{punctuated_source_url}' 创建新 run",
        "session_id": "punctuated-source-session",
    }, run_name=run.name)
    implicit_source_contract = _contract_from_event({
        "prompt": f"/loop {source_url}",
        "session_id": "implicit-source-session",
    }, run_name=run.name)
    normalized_source_contract = _contract_from_event({
        "prompt": f"\u3000  /loop {source_url} 创建新 run",
        "session_id": "normalized-source-session",
    }, run_name=run.name)
    multi_url_contract = _contract_from_event({
        "prompt": (
            f"/loop {source_url} 创建新 run；不要使用 "
            "https://unselected.example/other"
        ),
        "session_id": "multi-url-session",
    }, run_name=run.name)
    natural_single_url_contract = _contract_from_event({
        "prompt": f"从 {source_url} 创建新 run",
        "session_id": "natural-single-url-session",
    }, run_name=run.name)
    natural_multi_url_contract = _contract_from_event({
        "prompt": (
            f"从 {source_url} 创建新 run；参考资料是 "
            "https://unselected.example/other"
        ),
        "session_id": "natural-multi-url-session",
    }, run_name=run.name)
    negated_source_contract = _contract_from_event({
        "prompt": f"不要创建新 run：{source_url}",
        "session_id": "negated-source-session",
    }, run_name=run.name)
    english_negated_source_contract = _contract_from_event({
        "prompt": f"do not create run from {source_url}",
        "session_id": "english-negated-source-session",
    }, run_name=run.name)
    question_source_contract = _contract_from_event({
        "prompt": f"如何从 {source_url} 创建新 run？",
        "session_id": "question-source-session",
    }, run_name=run.name)
    modal_question_source_contract = _contract_from_event({
        "prompt": f"Can you create a new run from {source_url}",
        "session_id": "modal-question-source-session",
    }, run_name=run.name)
    lifecycle_description_contract = _contract_from_event({
        "prompt": f"这是创建新 run 的说明：{source_url}",
        "session_id": "lifecycle-description-session",
    }, run_name=run.name)
    quoted_log_contract = _contract_from_event({
        "prompt": (
            "日志内容如下：\n```\n"
            f"/loop {source_url}\n"
            "```\n帮我看看"
        ),
        "session_id": "quoted-log-session",
    }, run_name=run.name)
    indented_code_contract = _contract_from_event({
        "prompt": f"    /loop {source_url} 创建新 run\n分析上面的代码",
        "session_id": "indented-code-session",
    }, run_name=run.name)
    english_imperative_source_contract = _contract_from_event({
        "prompt": f"Create a new run from {source_url}",
        "session_id": "english-imperative-source-session",
    }, run_name=run.name)
    natural_punctuated_contract = _contract_from_event({
        "prompt": "从 https://natural.example/path。 创建新 run",
        "session_id": "natural-punctuated-session",
    }, run_name=run.name)
    natural_clean_source = {"tool_name": "Bash", "tool_input": {
        "command": (
            f"python3 {ROOT / 'tools' / 'loop_bootstrap.py'} "
            "--source 'https://natural.example/path' --type auto"
        ),
    }}
    negated_resume_contract = _contract_from_event({
        "prompt": "不要恢复 run runs/other_20260101",
        "session_id": "negated-resume-session",
    }, run_name=run.name)
    run_file_loop_contract = _contract_from_event({
        "prompt": f"/loop runs/{run.name}/target.md",
        "session_id": "run-file-loop-session",
    }, run_name=run.name)
    wrapped_source_control = {"tool_name": "Bash", "tool_input": {
        "command": source_control["tool_input"]["command"] + " 2>&1",
    }}
    source_write_redirect = {"tool_name": "Bash", "tool_input": {
        "command": source_control["tool_input"]["command"] + " > setup.log",
    }}
    wrong_query_source = {"tool_name": "Bash", "tool_input": {
        "command": (
            f"python3 {ROOT / 'tools' / 'loop_bootstrap.py'} "
            "--source 'https://new-source.example/path?key=different-secret' --type auto"
        ),
    }}
    unselected_source = {"tool_name": "Bash", "tool_input": {
        "command": (
            f"python3 {ROOT / 'tools' / 'loop_bootstrap.py'} "
            "--source 'https://unselected.example/other' --type auto"
        ),
    }}
    arbitrary_url = "https://arbitrary.example/third"
    setup_selected_target = {"tool_name": "Bash", "tool_input": {
        "command": (
            f"python3 {ROOT / 'tools' / 'setup_run.py'} "
            f"{_deterministic_source_slug(source_url)} --target '{source_url}'"
        ),
    }}
    setup_unselected_target = {"tool_name": "Bash", "tool_input": {
        "command": (
            f"python3 {ROOT / 'tools' / 'setup_run.py'} "
            f"{_deterministic_source_slug('https://unselected.example/other')} "
            "--target 'https://unselected.example/other'"
        ),
    }}
    setup_arbitrary_target = {"tool_name": "Bash", "tool_input": {
        "command": (
            f"python3 {ROOT / 'tools' / 'setup_run.py'} "
            f"{_deterministic_source_slug(arbitrary_url)} --target '{arbitrary_url}'"
        ),
    }}
    unrelated_legacy_recon = {"tool_name": "Bash", "tool_input": {
        "command": (
            f"python3 {ROOT / 'tools' / 'loop_bootstrap.py'} "
            f"unrelated {root / 'unrelated-recon.json'}"
        ),
    }}
    journal_control = {"tool_name": "Bash", "tool_input": {
        "command": f"python3 {ROOT / 'tools' / 'loop_journal.py'} {run} start --note begin"}}
    clear_active = {"tool_name": "Bash", "tool_input": {
        "command": f"python3 {ROOT / 'tools' / 'xunji_statusline.py'} --clear-active"}}
    wrapped_clear_active = {"tool_name": "Bash", "tool_input": {
        "command": clear_active["tool_input"]["command"] + " 2>&1"}}
    set_active = {"tool_name": "Bash", "tool_input": {
        "command": f"python3 {ROOT / 'tools' / 'xunji_statusline.py'} --set-active runs/other_20260101"}}
    resume_control = {"tool_name": "Bash", "tool_input": {
        "command": f"python3 {ROOT / 'tools' / 'loop_bootstrap.py'} --resume runs/other_20260101"}}
    unrelated_resume_control = {"tool_name": "Bash", "tool_input": {
        "command": (
            f"python3 {ROOT / 'tools' / 'loop_bootstrap.py'} "
            "--resume runs/unrelated_20260101"
        ),
    }}
    resume_operator_contract = _contract_from_event({
        "prompt": "/loop runs/other_20260101",
        "session_id": "resume-session",
    }, run_name=run.name)
    set_active_operator_contract = _contract_from_event({
        "prompt": "switch active run to runs/other_20260101",
        "session_id": "set-active-session",
    }, run_name=run.name)
    set_active_prefix_contract = _contract_from_event({
        "prompt": "switch active run to runs/other_202601010",
        "session_id": "set-active-prefix-session",
    }, run_name=run.name)
    set_active_url_collision_contract = _contract_from_event({
        "prompt": (
            "/loop https://source.example/runs/other_20260101 创建新 run"
        ),
        "session_id": "set-active-url-collision-session",
    }, run_name=run.name)
    prepared_receipt_path = run / "state" / "setup_transaction.json"
    prepared_receipt_path.write_text(json.dumps({
        "schema": "xunji.setup_transaction.v1",
        "transaction_id": "a" * 32,
        "source_sha256": "b" * 64,
        "status": "prepared_not_active",
    }), encoding="utf-8")
    prepared_target_blocked = "setup transaction" in evaluate_pretool(
        run, target_event, contract)
    prepared_cron_blocked = "setup transaction" in evaluate_pretool(
        run, {"tool_name": "CronCreate", "tool_input": {
            "prompt": f"/loop {run.name}"}}, contract)
    prepared_read_allowed = evaluate_pretool(
        run, {"tool_name": "Read", "tool_input": {
            "file_path": str(prepared_receipt_path)}}, contract) == ""
    prepared_recovery_event = {"tool_name": "Bash", "tool_input": {
        "command": (
            f"python3 {ROOT / 'tools' / 'loop_bootstrap.py'} "
            f"--resume runs/{run.name}"
        )}}
    prepared_recovery_contract = _contract_from_event({
        "prompt": f"resume run runs/{run.name}",
        "session_id": "prepared-recovery-session",
    }, run_name=run.name)
    prepared_recovery_allowed = evaluate_pretool(
        run, prepared_recovery_event, prepared_recovery_contract) == ""
    prepared_receipt_path.unlink()

    def registered_event(script: str, *args: str) -> dict:
        command = shlex.join((
            str(Path(sys.executable).resolve()),
            str((ROOT / script).resolve()),
            *args,
        ))
        return {"tool_name": "Bash", "tool_input": {"command": command}}

    registry_probe = registered_event(
        "tools/probe.py", "GET", "https://example.test/")
    registry_workers = registered_event(
        "tools/workers.py", "list", str(run))
    registry_owner_reads = [
        registered_event("tools/workers.py", "status", str(run)),
        registered_event("tools/workers.py", "lifecycle-check", str(run)),
        registered_event("tools/run_model.py", str(run)),
        registered_event("tools/runtime_receipts.py", str(run)),
        registered_event("tools/loop_journal.py", str(run), "status"),
    ]
    wrapped_owner_reads = [{
        "tool_name": "Bash",
        "tool_input": {
            "command": str(event["tool_input"]["command"]) + " 2>&1",
        },
    } for event in registry_owner_reads]
    wrapped_owner_output_filter = {
        "tool_name": "Bash",
        "tool_input": {
            "command": str(registry_owner_reads[0]["tool_input"]["command"])
            + " 2>&1 | head -20",
        },
    }
    wrapped_unknown_owner_argv = {
        "tool_name": "Bash",
        "tool_input": {
            "command": str(registry_owner_reads[0]["tool_input"]["command"])
            + " --future 2>&1",
        },
    }
    owner_file_redirect = {
        "tool_name": "Bash",
        "tool_input": {
            "command": str(registry_owner_reads[0]["tool_input"]["command"])
            + " > /tmp/xunji-owner-status.txt",
        },
    }
    registry_review = registered_event(
        "tools/peer_review.py", str(run), "--backend", "claude")
    registry_check_offline = registered_event(
        "tools/check_run.py", str(run))
    registry_check_replay = registered_event(
        "tools/check_run.py", str(run), "--replay-verify")
    registry_check_model = registered_event(
        "tools/check_run.py", str(run), "--auto-peer-review",
        "--review-driver", "codex")

    def compound_event(*commands: str) -> dict:
        return {
            "tool_name": "Bash",
            "tool_input": {"command": " && ".join(commands)},
        }

    registered_chain_events = [
        compound_event(*(
            registered_event("tools/workers.py", action, str(run))[
                "tool_input"]["command"]
            for action in ("merge-check", "conflicts", "synthesize")
        ), registered_event(
            "tools/work_plan.py", "status", str(run),
        )["tool_input"]["command"]),
        compound_event(*(
            registered_event(script, str(run), option)["tool_input"]["command"]
            for script, option in (
                ("tools/loop_state.py", "--write"),
                ("tools/progress_ledger.py", "--write"),
                ("tools/run_controller.py", "--shadow"),
            )
        )),
        compound_event(
            registered_event(
                "tools/workers.py", "status", str(run),
            )["tool_input"]["command"],
            "echo '---'",
            registered_event(
                "tools/workers.py", "agent-check", str(run),
            )["tool_input"]["command"],
        ),
        compound_event(
            "sleep 5",
            registered_event(
                "tools/workers.py", "status", str(run),
            )["tool_input"]["command"],
        ),
    ]
    registered_chain_prefix = str(
        registry_owner_reads[0]["tool_input"]["command"])
    registered_chain_suffix = str(
        registry_owner_reads[1]["tool_input"]["command"])
    effectful_registered_chain_events = [
        compound_event(
            str(registry_probe["tool_input"]["command"]),
            registered_chain_suffix,
        ),
        compound_event(
            str(registry_check_model["tool_input"]["command"]),
            registered_chain_suffix,
        ),
        compound_event(
            str(registry_probe["tool_input"]["command"]),
            str(registry_check_model["tool_input"]["command"]),
        ),
    ]
    reverse_duplicate_effect_chain = compound_event(
        str(registry_check_model["tool_input"]["command"]),
        str(registry_probe["tool_input"]["command"]),
        str(registry_probe["tool_input"]["command"]),
    )
    invalid_registered_chain_events = [
        compound_event(
            registered_chain_prefix + " --future",
            registered_chain_suffix,
        ),
        compound_event(
            str(registry_probe["tool_input"]["command"]),
            registered_chain_prefix + " --future",
        ),
    ]
    critical_data_invalid_chain = compound_event(
        registered_chain_prefix + " --future tools/turn_contract.py",
        registered_chain_suffix,
    )
    unsafe_registered_chains = [
        critical_data_invalid_chain,
        compound_event(
            registered_chain_prefix,
            "git add tools/turn_contract.py",
        ),
        compound_event(
            registered_chain_prefix,
            "sed -i '' tools/turn_contract.py",
        ),
        compound_event(
            registered_chain_prefix,
            f"{shlex.quote(str(Path(sys.executable).resolve()))} -c 'print(1)' "
            "tools/turn_contract.py",
        ),
        {"tool_name": "Bash", "tool_input": {
            "command": registered_chain_prefix + " > tools/turn_contract.py",
        }},
        compound_event(
            "LANG=C " + registered_chain_prefix,
            registered_chain_suffix,
        ),
        {"tool_name": "Bash", "tool_input": {
            "command": registered_chain_prefix + " && " + registered_chain_suffix,
            "env": {"LANG": "C"},
        }},
        *(
            {"tool_name": "Bash", "tool_input": {
                "command": registered_chain_prefix + " && " + registered_chain_suffix,
                "env": malformed_env,
            }}
            for malformed_env in ("LANG=C", ["LANG=C"], 1)
        ),
    ]
    registry_anti_status = registered_event(
        "tools/anti_drift.py", "--semantic-status", str(run))
    registry_reason_pass = registered_event(
        "tools/anti_drift.py", "--record-reason-pass", str(run),
        "--cycle-id", "1", "--chosen-front", "NONE",
        "--reason", "whole graph adjudicated")
    registry_reason_pass_extra = registered_event(
        "tools/anti_drift.py", "--record-reason-pass", str(run),
        "--cycle-id", "1", "--chosen-front", "NONE",
        "--reason", "whole graph adjudicated", "--future")
    registry_runtime_reproject = registered_event(
        "tools/runtime_receipts.py", str(run), "--reproject")
    registry_runtime_reproject_wrong_order = registered_event(
        "tools/runtime_receipts.py", "--reproject", str(run))
    registry_invalid_plan = registered_event(
        "tools/work_plan.py", "--future")
    registry_incomplete_plan = registered_event(
        "tools/work_plan.py", "commit", str(run),
        "--stage", "S2", "--mode", "PARALLEL_AGENTS",
        "--reason", "E2E primary-driver validation cycle",
    )
    registry_incomplete_plan_wrapped = {
        "tool_name": "Bash",
        "tool_input": {
            "command": registry_incomplete_plan["tool_input"]["command"]
            + " 2>&1 | head -60",
        },
    }
    manifest_python_read = {
        "tool_name": "Bash",
        "tool_input": {"command": shlex.join((
            str(Path(sys.executable).resolve()),
            "-c",
            "open('tools/harness/safety_critical_paths.json').read()",
        ))},
    }
    generic_read_chain = {
        "tool_name": "Bash",
        "tool_input": {
            "command": f"ls -la {shlex.quote(str(root / 'runs'))} "
            "2>/dev/null || echo NO_RUNS_DIR",
        },
    }
    wrong_policy_run = root / "wrong-policy-run"
    wrong_policy_run.mkdir()
    wrong_run_workers = registered_event(
        "tools/workers.py", "list", str(wrong_policy_run))
    wrong_run_review = registered_event(
        "tools/peer_review.py", str(wrong_policy_run), "--backend", "claude")
    wrong_run_anti_status = registered_event(
        "tools/anti_drift.py", "--semantic-status", str(wrong_policy_run))
    wrong_run_runtime_receipts = registered_event(
        "tools/runtime_receipts.py", str(wrong_policy_run))
    outside_ingest = registered_event(
        "tools/ingest_recon.py", str(root / "recon.json"),
        "--out", str(root / "outside-surface.md"))
    outside_probe_output = registered_event(
        "tools/probe.py", "GET", "https://example.test/",
        "--save", str(root / "outside-probe.html"))
    capability_scope_and_output_bindings_fail_closed = all(
        E_CAPABILITY_POLICY in _capability_policy_reason(
            run,
            _registered_capability_invocation(event["tool_input"]["command"]),
        )
        for event in (
            wrong_run_workers, wrong_run_review,
            wrong_run_anti_status, wrong_run_runtime_receipts,
            outside_ingest, outside_probe_output,
        )
    )
    semantic_capability = _registered_capability_invocation(
        registry_anti_status["tool_input"]["command"])
    reason_capability = _registered_capability_invocation(
        registry_reason_pass["tool_input"]["command"])
    runtime_reproject_capability = _registered_capability_invocation(
        registry_runtime_reproject["tool_input"]["command"])
    typed_local_capability_shapes_are_exact = bool(
        semantic_capability
        and semantic_capability[0].effect == "local_read"
        and semantic_capability[0].scope == "active_run"
        and capability_registry.run_reference(
            semantic_capability[0], semantic_capability[2]) == str(run)
        and reason_capability
        and reason_capability[0].effect == "control"
        and reason_capability[0].scope == "active_run"
        and reason_capability[0].recorder == "control_journal"
        and capability_registry.run_reference(
            reason_capability[0], reason_capability[2]) == str(run)
        and _registered_capability_invocation(
            registry_reason_pass_extra["tool_input"]["command"]) is None
        and runtime_reproject_capability
        and runtime_reproject_capability[0].id
        == "control.runtime-receipts-reproject"
        and runtime_reproject_capability[0].effect == "control"
        and runtime_reproject_capability[0].scope == "active_run"
        and runtime_reproject_capability[0].recorder == "control_journal"
        and capability_registry.run_reference(
            runtime_reproject_capability[0], runtime_reproject_capability[2])
        == str(run)
        and _registered_capability_invocation(
            registry_runtime_reproject_wrong_order["tool_input"]["command"])
        is None
    )
    capability_effect_classification_is_exact = bool(
        _is_target_action(registry_probe)
        and not _maintenance_action(registry_probe)
        and not _is_target_action(registry_workers)
        and not _maintenance_action(registry_workers)
        and not _is_target_action(registry_review)
        and not _maintenance_action(registry_review)
        and not _is_target_action(registry_check_offline)
        and not _maintenance_action(registry_check_offline)
        and _is_target_action(registry_check_replay)
        and not _maintenance_action(registry_check_replay)
        and not _is_target_action(registry_check_model)
        and not _maintenance_action(registry_check_model)
    )
    invalid_registered_argv_fails_closed = bool(
        _registered_capability_invocation(
            registry_invalid_plan["tool_input"]["command"]) is None
        and _control_invocation(
            registry_invalid_plan["tool_input"]["command"]) is None
        and _is_target_action(registry_invalid_plan)
    )
    incomplete_plan_reason = evaluate_pretool(
        run, registry_incomplete_plan, contract)
    incomplete_plan_metadata = _decision_metadata(
        incomplete_plan_reason, registry_incomplete_plan)
    wrapped_incomplete_plan_reason = evaluate_pretool(
        run, registry_incomplete_plan_wrapped, contract)
    clean_invalid_registered_argv_is_retryable_shape = bool(
        E_LIFECYCLE_EXACT_ARGV_REQUIRED in incomplete_plan_reason
        and incomplete_plan_metadata.get("xunji_decision_class")
        == "command_shape"
        and incomplete_plan_metadata.get("xunji_shape_category")
        == "invalid-argv"
        and incomplete_plan_metadata.get("xunji_control_script")
        == "tools/work_plan.py"
        and incomplete_plan_metadata.get("xunji_retryable_same_turn") is True
        and "/xunji-maintenance" not in incomplete_plan_reason
        and not _denial_is_target_action(
            registry_incomplete_plan, incomplete_plan_reason)
        and E_LIFECYCLE_EXACT_ARGV_REQUIRED in wrapped_incomplete_plan_reason
        and _decision_metadata(
            wrapped_incomplete_plan_reason,
            registry_incomplete_plan_wrapped,
        ).get("xunji_shape_category") == "invalid-argv-output-filter"
    )
    invalid_probe_with_allowed_env = {
        "tool_name": "Bash",
        "tool_input": {"command": (
            f"XUNJI_PROXY_REQUIRED=0 {shlex.quote(sys.executable)} "
            f"{shlex.quote(str(ROOT / 'tools' / 'probe.py'))} "
            "--method GET --url https://example.test/ --save "
            f"--run-dir {shlex.quote(str(run))}"
        )},
    }
    invalid_probe_env_reason = evaluate_pretool(
        run, invalid_probe_with_allowed_env, contract)
    invalid_probe_env_metadata = _decision_metadata(
        invalid_probe_env_reason, invalid_probe_with_allowed_env)
    invalid_probe_env_is_retryable_shape = bool(
        E_LIFECYCLE_EXACT_ARGV_REQUIRED in invalid_probe_env_reason
        and invalid_probe_env_metadata.get("xunji_decision_class")
        == "command_shape"
        and invalid_probe_env_metadata.get("xunji_shape_category")
        == "invalid-argv"
        and invalid_probe_env_metadata.get("xunji_control_script")
        == "tools/probe.py"
        and invalid_probe_env_metadata.get("xunji_retryable_same_turn") is True
        and "GET" in invalid_probe_env_reason
        and "--run" in invalid_probe_env_reason
        and "/xunji-maintenance" not in invalid_probe_env_reason
    )
    opaque_python_manifest_read_stays_maintenance = bool(
        _registered_capability_shape_issue(manifest_python_read) is None
        and bool(evaluate_pretool(run, manifest_python_read, contract))
        and _maintenance_action(manifest_python_read, contract=contract)
    )
    fake_workers_control = {"tool_name": "Bash", "tool_input": {
        "command": "python3 /tmp/workers.py list runs/x"}}
    safe_sed_read = {"tool_name": "Bash", "tool_input": {
        "command": "sed -n '1,10p' frontier.md"}}
    readonly_helper_path_spoofs_rejected = all(not _readonly_shell(command) for command in (
        "/tmp/cat frontier.md",
        "./git status",
        "tools/rg pattern .",
    ))
    rg_preprocessors_rejected = all(not _readonly_shell(command) for command in (
        "rg --pre cat pattern .",
        "rg --pre=cat pattern .",
        "rg --pre-glob '*.md' pattern .",
        "rg --pre-glob=*.md pattern .",
        "rg --hostname-bin /tmp/pwn --json pattern .",
        "rg --hostname-bin=/tmp/pwn --json pattern .",
        "rg --search-zip pattern .",
        "rg -z pattern .",
    ))
    plain_rg_remains_read_only = _readonly_shell("rg pattern .")
    quoted_punctuation_and_devnull_remain_read_only = all(_readonly_shell(command) for command in (
        'grep -n "ROOT_DIRECT|SERIAL_AGENT" tools/workers.py',
        'grep -n "mode" tools/work_plan.py 2>/dev/null | head -50',
        'ls runs 2>/dev/null || echo "No runs directory"',
        'find runs/example -type f | sort',
    )) and all(not _readonly_shell(command) for command in (
        'grep mode tools/workers.py > /tmp/copied',
        'grep mode tools/workers.py 2> /tmp/errors',
        'grep mode tools/workers.py & echo background',
    ))
    readonly_hash_event = {"tool_name": "Bash", "tool_input": {
        "command": (
            "shasum -a 256 contracts/agent-instruction-sources.v1.json "
            "docs/templates/agents/common.v1.md "
            ".claude/agents/xunji-reviewer.md"
        )}}
    exact_shasum_is_read_only_not_maintenance = bool(
        _readonly_shell(readonly_hash_event["tool_input"]["command"])
        and not _maintenance_action(readonly_hash_event, contract=contract)
        and all(not _readonly_shell(command) for command in (
            "shasum -a 1 docs/templates/agents/common.v1.md",
            "shasum -c checksums.txt",
            "/usr/bin/shasum -a 256 docs/templates/agents/common.v1.md",
        ))
    )
    sed_in_place = {"tool_name": "Bash", "tool_input": {
        "command": "sed -n -i '1,10p' frontier.md"}}
    sed_write_command = {"tool_name": "Bash", "tool_input": {
        "command": "sed -n 'w /tmp/forged' frontier.md"}}
    find_file_output = {"tool_name": "Bash", "tool_input": {
        "command": "find . -type f -fprint /tmp/forged"}}
    agent_bad = {"tool_name": "Agent", "tool_input": {"prompt": "work F-001"}}
    agent_good = {"tool_name": "Agent", "tool_input": {
        "prompt": "XUNJI_ASSIGNMENT=A-web-001 XUNJI_FRONT=F-001 XUNJI_ASSETS=example.test",
        "subagent_type": "xunji-hunter",
    }}
    completion_gate_run = root / "completion-gate-run"
    completion_gate_contract, _ = seed_current_plan(
        completion_gate_run, stage="S3")
    exact_completion_prompt = runtime_receipts.completion_review_prompt(
        completion_gate_run)
    completion_bad = {"tool_name": "Agent", "tool_input": {
        "prompt": re.sub(r"\s+CHECKS=.*$", "", exact_completion_prompt),
        "subagent_type": "xunji-reviewer",
    }}
    completion_good = {"tool_name": "Agent", "tool_input": {
        "prompt": exact_completion_prompt,
        "subagent_type": "xunji-reviewer",
    }}
    completion_wrong_types = [
        {"tool_name": "Agent", "tool_input": {
            "prompt": exact_completion_prompt,
            "subagent_type": wrong_type,
        }}
        for wrong_type in (
            None, "", " ", "general-purpose", "xunji-hunter",
            "xunji-reviewer ")
    ]
    completion_mixed = {"tool_name": "Agent", "tool_input": {
        "prompt": exact_completion_prompt + " XUNJI_FRONT=F-001",
        "subagent_type": "xunji-reviewer",
    }}
    completion_stale_hash = {"tool_name": "Agent", "tool_input": {
        "prompt": re.sub(
            r"EVIDENCE_INDEX=[0-9a-f]{40}", "EVIDENCE_INDEX=" + "0" * 40,
            exact_completion_prompt),
        "subagent_type": "xunji-reviewer",
    }}
    completion_marker_impostors = [
        {"tool_name": "Agent", "tool_input": {
            "prompt": marker,
            "subagent_type": "xunji-reviewer",
        }}
        for marker in (
            "NOT_XUNJI_COMPLETION_REVIEW",
            "XUNJI_COMPLETION_REVIEWED",
        )
    ]
    completion_bad_blocked = bool(evaluate_pretool(
        completion_gate_run, completion_bad, completion_gate_contract))
    completion_good_allowed = evaluate_pretool(
        completion_gate_run, completion_good, completion_gate_contract) == ""
    completion_wrong_types_blocked = all(
        bool(evaluate_pretool(
            completion_gate_run, item, completion_gate_contract))
        for item in completion_wrong_types)
    completion_stale_and_mixed_blocked = bool(
        evaluate_pretool(
            completion_gate_run, completion_stale_hash,
            completion_gate_contract)) and bool(evaluate_pretool(
                completion_gate_run, completion_mixed,
                completion_gate_contract))
    completion_impostors_blocked = all(
        bool(evaluate_pretool(
            completion_gate_run, item, completion_gate_contract))
        for item in completion_marker_impostors)

    def unavailable_completion_event(candidate_run: Path) -> dict:
        return {"tool_name": "Agent", "tool_input": {
            "prompt": runtime_receipts.format_completion_review_prompt(
                candidate_run.name,
                current_evidence_index_hash(candidate_run),
                "b" * 64,
            ),
            "subagent_type": "xunji-reviewer",
        }}

    completion_no_plan_run = root / "completion-no-plan-run"
    (completion_no_plan_run / "state").mkdir(parents=True)
    (completion_no_plan_run / "evidence.md").write_text(
        "# Evidence Ledger\n", encoding="utf-8")
    completion_no_plan_contract = {
        **completion_gate_contract,
        "session_id": "completion-no-plan-session",
    }
    completion_s1_run = root / "completion-s1-run"
    completion_s1_contract, _ = seed_current_plan(
        completion_s1_run, stage="S1")
    completion_s2_run = root / "completion-s2-run"
    completion_s2_contract, _ = seed_current_plan(
        completion_s2_run, stage="S2")
    completion_stale_run = root / "completion-stale-run"
    completion_stale_contract, _ = seed_current_plan(
        completion_stale_run, stage="S3")
    completion_stale_prompt = runtime_receipts.completion_review_prompt(
        completion_stale_run)
    with (completion_stale_run / "report.md").open("a", encoding="utf-8") as handle:
        handle.write("material closure change\n")
    completion_prepared_run = root / "completion-prepared-run"

    def stop_after_prepared(stage: str) -> None:
        if stage == "prepared":
            raise RuntimeError("intentional prepared work-plan fixture")

    try:
        seed_current_plan(
            completion_prepared_run, stage="S3", fault=stop_after_prepared)
    except RuntimeError as exc:
        if str(exc) != "intentional prepared work-plan fixture":
            raise
    completion_prepared_contract = json.loads(
        (completion_prepared_run / "state" / "turn_contract.json").read_text(
            encoding="utf-8"))
    completion_corrupt_run = root / "completion-corrupt-run"
    completion_corrupt_contract, _ = seed_current_plan(
        completion_corrupt_run, stage="S3")
    (completion_corrupt_run / "state" / "work_plan_transaction.json").write_text(
        "{corrupt", encoding="utf-8")
    unavailable_completion_cases = [
        (completion_no_plan_run, completion_no_plan_contract,
         unavailable_completion_event(completion_no_plan_run)),
        (completion_s1_run, completion_s1_contract,
         unavailable_completion_event(completion_s1_run)),
        (completion_s2_run, completion_s2_contract,
         unavailable_completion_event(completion_s2_run)),
        (completion_stale_run, completion_stale_contract, {
            "tool_name": "Agent", "tool_input": {
                "prompt": completion_stale_prompt,
                "subagent_type": "xunji-reviewer",
            },
        }),
        (completion_prepared_run, completion_prepared_contract,
         unavailable_completion_event(completion_prepared_run)),
        (completion_corrupt_run, completion_corrupt_contract,
         unavailable_completion_event(completion_corrupt_run)),
    ]
    unavailable_completion_prompts_are_empty = all(
        runtime_receipts.completion_review_prompt(candidate_run) == ""
        for candidate_run, _candidate_contract, _event in unavailable_completion_cases)
    unavailable_completion_attempts_blocked = all(
        bool(evaluate_pretool(candidate_run, event, candidate_contract))
        for candidate_run, candidate_contract, event in unavailable_completion_cases)
    unavailable_completion_pretool_is_read_only = all(
        runtime_receipts.load_events(candidate_run) == []
        for candidate_run, _candidate_contract, _event in unavailable_completion_cases)
    agent_bad_blocked = "必须包含" in evaluate_pretool(run, agent_bad, contract)
    agent_good_allowed = evaluate_pretool(run, agent_good, contract) == ""
    before_fanout = "真实 Agent 回执" in evaluate_pretool(run, target_event, contract)
    encoded_before_fanout = bool(evaluate_pretool(run, encoded_target, contract))
    renamed_before_fanout = bool(evaluate_pretool(run, renamed_target, contract))
    workers_allowed_before_fanout = not bool(evaluate_pretool(run, workers_control, contract))
    workers_asset_control_allowed = (
        evaluate_pretool(run, workers_asset_control, contract) == ""
        and not _is_target_action(workers_asset_control))
    workers_quoted_note_allowed = (
        evaluate_pretool(run, workers_quoted_note_control, contract) == ""
        and _control_invocation(workers_quoted_note_control["tool_input"]["command"]) is not None)
    workers_protected_name_note_allowed = (
        evaluate_pretool(run, workers_protected_name_note_control, contract) == ""
        and _control_invocation(
            workers_protected_name_note_control["tool_input"]["command"]) is not None)
    quoted_punctuation_allowed = (
        evaluate_pretool(run, workers_quoted_punctuation_control, contract) == ""
        and _control_invocation(
            workers_quoted_punctuation_control["tool_input"]["command"]) is not None)
    single_quoted_literals_allowed = (
        evaluate_pretool(run, workers_single_quoted_literal_control, contract) == ""
        and _control_invocation(
            workers_single_quoted_literal_control["tool_input"]["command"]) is not None)
    escaped_substitution_literal_allowed = (
        evaluate_pretool(run, workers_escaped_substitution_literal, contract) == ""
        and _control_invocation(
            workers_escaped_substitution_literal["tool_input"]["command"]) is not None)
    ansi_c_literal_rejected = (
        _control_invocation(
            workers_ansi_c_literal_control["tool_input"]["command"]) is None)
    trailing_comment_control_rejected = (
        _control_invocation(
            workers_trailing_comment_control["tool_input"]["command"]) is None)
    workers_shell_chain_rejected = _control_invocation(workers_shell_chain) is None
    adversarial_controls_fail_closed = all(
        _control_invocation(command) is None
        and bool(evaluate_pretool(
            run, {"tool_name": "Bash", "tool_input": {"command": command}}, contract))
        for command in adversarial_control_commands)
    python_alias_command = f"python {ROOT / 'tools' / 'loop_state.py'} {run}"
    python3_alias_command = f"python3 {ROOT / 'tools' / 'loop_state.py'} {run}"
    documented_python3_is_trusted_across_hook_path = (
        _control_invocation(python3_alias_command) is not None
        and _control_invocation(python_alias_command) is None
        and trusted_python_token("python3")
        and not trusted_python_token("python")
    )
    unavailable_micro_python_rejected = _control_invocation(
        f"python3.14.2 {ROOT / 'tools' / 'loop_state.py'} {run}") is None
    setup_invocation = _control_invocation(setup_control["tool_input"]["command"])
    setup_allowed_before_fanout = not bool(evaluate_pretool(
        run, setup_control, setup_operator_contract))
    benign_setup_direct_egress_prefixes_normalize = all(
        _lifecycle_invocation(command) is not None
        and _registered_capability_invocation(command)[0].id
        == "control.loop-bootstrap"
        for command in (
            f"XUNJI_PROXY_REQUIRED=0 python3 {ROOT / 'tools' / 'loop_bootstrap.py'} "
            "--source 'http://127.0.0.1:18765' --type auto",
            f"export XUNJI_PROXY_REQUIRED=0 && python3 "
            f"{ROOT / 'tools' / 'loop_bootstrap.py'} "
            "--source 'http://127.0.0.1:18765' --type auto",
        )
    )
    setup_classify_invocation = _lifecycle_invocation(
        setup_classify_control["tool_input"]["command"])
    classify_requires_explicit_opt_in = bool(
        setup_classify_invocation
        and "--classify" in _lifecycle_authority_reason(
            run, setup_classify_invocation, setup_operator_contract)
        and _lifecycle_authority_reason(
            run, setup_classify_invocation, setup_classify_contract) == ""
        and "opt-in" in _lifecycle_authority_reason(
            run, setup_classify_invocation, setup_classify_denied_contract)
    )
    full_prompt_classify_authority = bool(
        setup_classify_invocation
        and _lifecycle_authority_reason(
            run, setup_classify_invocation,
            setup_classify_late_opt_in_contract) == ""
        and "opt-in" in _lifecycle_authority_reason(
            run, setup_classify_invocation,
            setup_classify_late_denial_contract)
        and "opt-in" in _lifecycle_authority_reason(
            run, setup_classify_invocation,
            setup_classify_quoted_opt_in_contract)
    )
    structured_slug_authority = bool(
        setup_invocation
        and _lifecycle_authority_reason(
            run, setup_invocation, setup_late_slug_contract) == ""
        and "slug" in _lifecycle_authority_reason(
            run, setup_invocation, setup_quoted_slug_contract)
    )
    invalid_lifecycle_args_fail_closed = all(item is None for item in (
        _parse_loop_source_args([
            "--source", source_url, "--ai", "off", "--ai-provider", "unexpected",
        ]),
        _parse_loop_source_args([
            "--source", str(root / "recon.json"), "--ai", "local",
        ]),
        _parse_loop_source_args([
            "--source", str(root / "recon.json"), "--ai", "external",
            "--ai-provider", "fixture", "--ai-model", "fixture",
        ]),
        _parse_setup_run_args(["empty-source"]),
        _parse_setup_run_args([
            "dated", str(root / "recon.json"), "--date", "20261340",
        ]),
    ))
    source_control_with_env = {
        **source_control,
        "tool_input": {
            **source_control["tool_input"],
            "env": {"PATH": "/private/tmp/untrusted"},
        },
    }
    lifecycle_env_override_reason = evaluate_pretool(
        run, source_control_with_env, source_operator_contract)
    lifecycle_env_override_blocked = bool(lifecycle_env_override_reason)
    source_setup_allowed = not bool(evaluate_pretool(run, source_control, {
        **contract, "prompt_excerpt": f"/loop {source_url}",
    }))
    hashed_source_setup_allowed = evaluate_pretool(
        run, source_control, source_operator_contract) == ""
    punctuated_source_preserved_exactly = bool(
        len(punctuated_source_contract.get("source_sha256s") or []) == 1
        and evaluate_pretool(
            run, punctuated_source_control, punctuated_source_contract) == ""
        and E_RUN_TRANSITION_AUTHORITY_MISSING in evaluate_pretool(
            run, trimmed_punctuated_source_control, punctuated_source_contract)
    )
    wrapped_source_reason = evaluate_pretool(
        run, wrapped_source_control, source_operator_contract)
    source_write_redirect_reason = evaluate_pretool(
        run, source_write_redirect, source_operator_contract)
    wrong_query_source_blocked = E_RUN_TRANSITION_AUTHORITY_MISSING in evaluate_pretool(
        run, wrong_query_source, source_operator_contract)
    unselected_prompt_url_blocked = bool(
        len(multi_url_contract.get("source_sha256s") or []) == 1
        and E_RUN_TRANSITION_AUTHORITY_MISSING in evaluate_pretool(
            run, unselected_source, multi_url_contract)
    )
    natural_single_url_authorized = bool(
        len(natural_single_url_contract.get("source_sha256s") or []) == 1
        and not natural_single_url_contract.get("source_ambiguous")
        and evaluate_pretool(run, source_control, natural_single_url_contract) == ""
    )
    natural_multi_url_reason = evaluate_pretool(
        run, unselected_source, natural_multi_url_contract)
    natural_multi_url_fails_closed = bool(
        natural_multi_url_contract.get("source_ambiguous")
        and not natural_multi_url_contract.get("source_sha256s")
        and E_RUN_TRANSITION_AUTHORITY_MISSING in natural_multi_url_reason
        and "多个 URL" in natural_multi_url_reason
    )
    denied_and_question_intents_are_read_only = all(
        item.get("mode") == EXPLAIN
        and item.get("lifecycle_operation") == "none"
        and E_RUN_TRANSITION_AUTHORITY_MISSING in evaluate_pretool(
            run, source_control, item)
        for item in (
            negated_source_contract,
            english_negated_source_contract,
            question_source_contract,
            modal_question_source_contract,
            lifecycle_description_contract,
        )
    )
    negated_resume_is_read_only = bool(
        negated_resume_contract.get("mode") == EXPLAIN
        and negated_resume_contract.get("lifecycle_operation") == "none"
        and E_RUN_TRANSITION_AUTHORITY_MISSING in evaluate_pretool(
            run, resume_control, negated_resume_contract)
    )
    quoted_loop_data_cannot_mint_authority = bool(
        not quoted_log_contract.get("loop_requested")
        and quoted_log_contract.get("mode") == EXPLAIN
        and quoted_log_contract.get("lifecycle_operation") == "none"
        and E_RUN_TRANSITION_AUTHORITY_MISSING in evaluate_pretool(
            run, source_control, quoted_log_contract)
    )
    indented_analysis_remains_read_only = bool(
        indented_code_contract.get("mode") == EXPLAIN
        and indented_code_contract.get("lifecycle_operation") == "none"
        and E_RUN_TRANSITION_AUTHORITY_MISSING in evaluate_pretool(
            run, source_control, indented_code_contract)
    )
    leading_whitespace_operator_intent_normalized = bool(
        normalized_source_contract.get("mode") == EXECUTE
        and normalized_source_contract.get("loop_requested")
        and normalized_source_contract.get("lifecycle_operation") == "source"
        and normalized_source_contract.get("intent_normalizations")
        == ["leading_horizontal_whitespace"]
        and normalized_source_contract.get("source_sha256s")
        == implicit_source_contract.get("source_sha256s")
        and normalized_source_contract.get("prompt_sha256")
        != implicit_source_contract.get("prompt_sha256")
    )
    english_imperative_source_authorized = bool(
        english_imperative_source_contract.get("mode") == EXECUTE
        and english_imperative_source_contract.get("lifecycle_operation") == "source"
        and evaluate_pretool(
            run, source_control, english_imperative_source_contract) == ""
    )
    natural_trailing_punctuation_fails_closed = bool(
        natural_punctuated_contract.get("source_ambiguous")
        and not natural_punctuated_contract.get("source_sha256s")
        and E_RUN_TRANSITION_AUTHORITY_MISSING in evaluate_pretool(
            run, natural_clean_source, natural_punctuated_contract)
    )
    run_file_source_resumes_current_run = bool(
        run_file_loop_contract.get("loop_source_kind") == "run"
        and run_file_loop_contract.get("lifecycle_operation") == "resume"
        and not run_file_loop_contract.get("run_transition_requested")
    )
    setup_selected_target_allowed = evaluate_pretool(
        run, setup_selected_target, source_operator_contract) == ""
    setup_unselected_target_blocked = E_RUN_TRANSITION_AUTHORITY_MISSING \
        in evaluate_pretool(run, setup_unselected_target, source_operator_contract)
    natural_single_setup_target_allowed = evaluate_pretool(
        run, setup_selected_target, natural_single_url_contract) == ""
    natural_multi_setup_targets_blocked = all(
        E_RUN_TRANSITION_AUTHORITY_MISSING in evaluate_pretool(
            run, event, natural_multi_url_contract)
        for event in (
            setup_selected_target, setup_unselected_target, setup_arbitrary_target,
        )
    )
    unrelated_legacy_recon_blocked = E_RUN_TRANSITION_AUTHORITY_MISSING \
        in evaluate_pretool(run, unrelated_legacy_recon, source_operator_contract)
    source_turn_resume_blocked = E_RUN_TRANSITION_AUTHORITY_MISSING \
        in evaluate_pretool(run, unrelated_resume_control, source_operator_contract)
    exact_resume_operation_allowed = evaluate_pretool(
        run, resume_control, resume_operator_contract) == ""
    unrelated_resume_operation_blocked = E_RUN_TRANSITION_AUTHORITY_MISSING \
        in evaluate_pretool(run, unrelated_resume_control, resume_operator_contract)
    source_contract_redacted = bool(
        source_operator_contract.get("source_sha256s")
        and "opaque-secret" not in str(source_operator_contract)
        and "redacted%3Aquery" in str(source_operator_contract.get("prompt_excerpt") or "")
    )
    loop_url_derives_transition = bool(
        implicit_source_contract.get("loop_requested")
        and implicit_source_contract.get("loop_source_kind") == "url"
        and implicit_source_contract.get("run_transition_requested")
        and _new_run_transition_pending(implicit_source_contract, run)
    )
    owner_read_clean_allowed = all(
        (lambda capability: bool(
            capability
            and capability[0].effect == "local_read"
            and not _critical_maintenance_reason(event)
            and evaluate_pretool(run, event, contract) == ""
        ))(_registered_capability_invocation(event["tool_input"]["command"]))
        for event in registry_owner_reads
    )
    owner_wrapper_reasons = [
        evaluate_pretool(run, event, contract) for event in wrapped_owner_reads
    ]
    owner_wrappers_are_retryable_shape_denials = all(
        E_LIFECYCLE_EXACT_ARGV_REQUIRED in reason
        and _decision_metadata(reason, event).get("xunji_decision_class")
        == "command_shape"
        and _decision_metadata(reason, event).get("xunji_retryable_same_turn")
        is True
        and "/xunji-maintenance" not in reason
        and not _denial_is_target_action(event, reason)
        for event, reason in zip(wrapped_owner_reads, owner_wrapper_reasons)
    )
    owner_output_filter_reason = evaluate_pretool(
        run, wrapped_owner_output_filter, contract)
    owner_output_filter_is_shape_denial = bool(
        E_LIFECYCLE_EXACT_ARGV_REQUIRED in owner_output_filter_reason
        and _decision_metadata(
            owner_output_filter_reason, wrapped_owner_output_filter,
        ).get("xunji_shape_category") == "output-filter"
    )
    registered_chain_reasons = [
        evaluate_pretool(run, event, contract)
        for event in registered_chain_events
    ]
    registered_chains_are_retryable_nonmaintenance_denials = all(
        E_LIFECYCLE_EXACT_ARGV_REQUIRED in reason
        and _decision_metadata(reason, event).get("xunji_decision_class")
        == "command_shape"
        and str(_decision_metadata(
            reason, event).get("xunji_shape_category") or "").startswith(
                "registered-chain")
        and _decision_metadata(reason, event).get("xunji_retryable_same_turn")
        is True
        and "/xunji-maintenance" not in reason
        and not _denial_is_target_action(event, reason)
        for event, reason in zip(registered_chain_events, registered_chain_reasons)
    )
    registered_chain_segments_retry_individually = all(
        evaluate_pretool(
            run,
            {"tool_name": "Bash", "tool_input": {"command": segment}},
            contract,
        ) == ""
        for event in registered_chain_events
        for segment in (split_literal_and_chain(
            str(event["tool_input"]["command"])) or ())
        if not _diagnostic_passive_chain_segment(
            shlex.split(segment, comments=False, posix=True))
    )
    effectful_registered_chain_reasons = [
        evaluate_pretool(run, event, contract)
        for event in effectful_registered_chain_events
    ]
    effectful_registered_chains_keep_typed_denial = bool(
        len(effectful_registered_chain_reasons) == 3
        and all(
            E_LIFECYCLE_EXACT_ARGV_REQUIRED in reason
            and _decision_metadata(reason, event).get("xunji_shape_category")
            == "registered-chain"
            and "/xunji-maintenance" not in reason
            for event, reason in zip(
                effectful_registered_chain_events,
                effectful_registered_chain_reasons,
            )
        )
        and _decision_metadata(
            effectful_registered_chain_reasons[0],
            effectful_registered_chain_events[0],
        ).get("xunji_capability_effect") == "target"
        and _denial_is_target_action(
            effectful_registered_chain_events[0],
            effectful_registered_chain_reasons[0],
        )
        and _decision_metadata(
            effectful_registered_chain_reasons[1],
            effectful_registered_chain_events[1],
        ).get("xunji_capability_effect") == "model_egress"
        and not _denial_is_target_action(
            effectful_registered_chain_events[1],
            effectful_registered_chain_reasons[1],
        )
        and _decision_metadata(
            effectful_registered_chain_reasons[2],
            effectful_registered_chain_events[2],
        ).get("xunji_capability_effects") == ["target", "model_egress"]
        and _denial_is_target_action(
            effectful_registered_chain_events[2],
            effectful_registered_chain_reasons[2],
        )
    )
    reverse_duplicate_effect_reason = evaluate_pretool(
        run, reverse_duplicate_effect_chain, contract)
    reverse_duplicate_effect_metadata = _decision_metadata(
        reverse_duplicate_effect_reason, reverse_duplicate_effect_chain)
    effect_set_is_stable_and_target_segments_are_distinct = bool(
        reverse_duplicate_effect_metadata.get("xunji_capability_effect")
        == "target"
        and reverse_duplicate_effect_metadata.get("xunji_capability_effects")
        == ["target", "model_egress"]
        and len(reverse_duplicate_effect_metadata.get(
            "xunji_target_retry_action_sha256s") or []) == 2
        and len(set(reverse_duplicate_effect_metadata.get(
            "xunji_target_retry_action_sha256s") or [])) == 1
    )
    invalid_registered_chain_reasons = [
        evaluate_pretool(run, event, contract)
        for event in invalid_registered_chain_events
    ]
    invalid_registered_chains_are_nonmaintenance_shape = bool(
        len(invalid_registered_chain_reasons) == 2
        and all(
            E_LIFECYCLE_EXACT_ARGV_REQUIRED in reason
            and _decision_metadata(reason, event).get("xunji_shape_category")
            == "registered-chain-invalid-argv"
            and "/xunji-maintenance" not in reason
            for event, reason in zip(
                invalid_registered_chain_events,
                invalid_registered_chain_reasons,
            )
        )
        and not _denial_is_target_action(
            invalid_registered_chain_events[0],
            invalid_registered_chain_reasons[0],
        )
        and _denial_is_target_action(
            invalid_registered_chain_events[1],
            invalid_registered_chain_reasons[1],
        )
    )
    unsafe_registered_chain_reasons = [
        evaluate_pretool(run, event, contract)
        for event in unsafe_registered_chains
    ]
    opaque_or_mutating_chains_stay_fail_closed = all(
        E_LIFECYCLE_EXACT_ARGV_REQUIRED not in reason
        and _registered_capability_shape_issue(event) is None
        and bool(reason)
        for event, reason in zip(
            unsafe_registered_chains, unsafe_registered_chain_reasons)
    )
    unknown_owner_wrapper_reason = evaluate_pretool(
        run, wrapped_unknown_owner_argv, contract)
    owner_file_redirect_reason = evaluate_pretool(
        run, owner_file_redirect, contract)
    unknown_and_write_wrappers_stay_fail_closed = bool(
        E_LIFECYCLE_EXACT_ARGV_REQUIRED in unknown_owner_wrapper_reason
        and _decision_metadata(
            unknown_owner_wrapper_reason,
            wrapped_unknown_owner_argv,
        ).get("xunji_shape_category") == "invalid-argv-stderr-merge"
        and "/xunji-maintenance" not in unknown_owner_wrapper_reason
        and E_LIFECYCLE_EXACT_ARGV_REQUIRED not in owner_file_redirect_reason
        and bool(owner_file_redirect_reason)
    )
    shape_metadata = _decision_metadata(wrapped_source_reason, wrapped_source_control)
    shape_denial_classified = bool(
        E_LIFECYCLE_EXACT_ARGV_REQUIRED in wrapped_source_reason
        and shape_metadata.get("xunji_decision_class") == "command_shape"
        and shape_metadata.get("xunji_control_script") == "tools/loop_bootstrap.py"
        and shape_metadata.get("xunji_retryable_same_turn") is True
        and not _denial_is_target_action(wrapped_source_control, wrapped_source_reason)
        and "/xunji-maintenance" not in wrapped_source_reason
    )
    true_redirect_stays_maintenance = bool(
        source_write_redirect_reason
        and E_LIFECYCLE_EXACT_ARGV_REQUIRED not in source_write_redirect_reason
    )
    shape_receipt_run = root / "shape-receipt-run"
    (shape_receipt_run / "state").mkdir(parents=True)
    shape_receipt_contract = {
        **source_operator_contract,
        "origin_run": shape_receipt_run.name,
        "bound_run": shape_receipt_run.name,
        "updated_at": time.time(),
    }
    _atomic_json(contract_path(shape_receipt_run), shape_receipt_contract)
    shape_hook_result = handle_event({
        "hook_event_name": "PreToolUse", "session_id": "shape-session",
        "transcript_path": str(root / "shape-transcript.jsonl"),
        "tool_name": "Bash", "tool_use_id": "shape-denial-1",
        "tool_input": wrapped_source_control["tool_input"],
    }, shape_receipt_run)
    shape_receipts = runtime_receipts.load_events(shape_receipt_run)
    shape_receipt = shape_receipts[-1] if shape_receipts else {}
    shape_receipt_is_nonmaintenance = bool(
        shape_hook_result
        and shape_receipt.get("decision_code") == E_LIFECYCLE_EXACT_ARGV_REQUIRED
        and shape_receipt.get("decision_class") == "command_shape"
        and shape_receipt.get("maintenance_action") is False
        and shape_receipt.get("target_action") is False
        and shape_receipt.get("retryable_same_turn") is True
        and "opaque-secret" not in str(shape_receipt)
        and not load_contract(shape_receipt_run).get("maintenance_blocked")
    )
    owner_shape_hook_result = handle_event({
        "hook_event_name": "PreToolUse", "session_id": "shape-session",
        "transcript_path": str(root / "shape-transcript.jsonl"),
        "tool_name": "Bash", "tool_use_id": "owner-shape-denial-1",
        "tool_input": wrapped_owner_reads[0]["tool_input"],
    }, shape_receipt_run)
    owner_shape_receipts = runtime_receipts.load_events(shape_receipt_run)
    owner_shape_receipt = owner_shape_receipts[-1] \
        if owner_shape_receipts else {}
    owner_shape_receipt_is_nonmaintenance = bool(
        owner_shape_hook_result
        and owner_shape_receipt.get("decision_code")
        == E_LIFECYCLE_EXACT_ARGV_REQUIRED
        and owner_shape_receipt.get("decision_class") == "command_shape"
        and owner_shape_receipt.get("control_script") == "tools/workers.py"
        and owner_shape_receipt.get("maintenance_action") is False
        and owner_shape_receipt.get("target_action") is False
        and owner_shape_receipt.get("retryable_same_turn") is True
        and not load_contract(shape_receipt_run).get("maintenance_blocked")
    )
    chain_receipt_run = root / "registered-chain-receipt-run"
    (chain_receipt_run / "state").mkdir(parents=True)
    chain_receipt_transcript = root / "registered-chain-transcript.jsonl"
    chain_receipt_transcript.write_text(
        "\n".join(
            f"registered-chain-denial-{index}"
            for index in range(1, len(registered_chain_events) + 1)
        ) + "\n" + "\n".join(
            f"effectful-chain-denial-{index}"
            for index in range(1, len(effectful_registered_chain_events) + 1)
        ) + "\n" + "\n".join(
            f"invalid-chain-denial-{index}"
            for index in range(1, len(invalid_registered_chain_events) + 1)
        ) + "\neffectful-chain-target-retry\n",
        encoding="utf-8",
    )
    chain_receipt_contract = {
        **contract,
        "origin_run": chain_receipt_run.name,
        "bound_run": chain_receipt_run.name,
        "session_id": "registered-chain-session",
        "updated_at": time.time(),
    }
    _atomic_json(contract_path(chain_receipt_run), chain_receipt_contract)
    chain_hook_results = [
        handle_event({
            "hook_event_name": "PreToolUse",
            "session_id": "registered-chain-session",
            "transcript_path": str(chain_receipt_transcript),
            "tool_name": "Bash",
            "tool_use_id": f"registered-chain-denial-{index}",
            "tool_input": event["tool_input"],
        }, chain_receipt_run)
        for index, event in enumerate(registered_chain_events, start=1)
    ]
    chain_receipts = [
        receipt for receipt in runtime_receipts.load_events(chain_receipt_run)
        if str(receipt.get("tool_use_id") or "").startswith(
            "registered-chain-denial-")
    ]
    registered_chain_receipts_do_not_mint_debt = bool(
        all(chain_hook_results)
        and len(chain_receipts) == len(registered_chain_events)
        and all(
            receipt.get("decision_code") == E_LIFECYCLE_EXACT_ARGV_REQUIRED
            and receipt.get("decision_class") == "command_shape"
            and str(receipt.get("shape_category") or "").startswith(
                "registered-chain")
            and receipt.get("maintenance_action") is False
            and receipt.get("maintenance_paths") == []
            and receipt.get("target_action") is False
            and receipt.get("retryable_same_turn") is True
            for receipt in chain_receipts
        )
        and not load_contract(chain_receipt_run).get("maintenance_blocked")
        and not runtime_receipts.unresolved_maintenance_blockers(
            chain_receipt_run)
    )
    effectful_chain_hook_results = [
        handle_event({
            "hook_event_name": "PreToolUse",
            "session_id": "registered-chain-session",
            "transcript_path": str(chain_receipt_transcript),
            "tool_name": "Bash",
            "tool_use_id": f"effectful-chain-denial-{index}",
            "tool_input": event["tool_input"],
        }, chain_receipt_run)
        for index, event in enumerate(
            effectful_registered_chain_events, start=1)
    ]
    effectful_chain_receipts = [
        receipt for receipt in runtime_receipts.load_events(chain_receipt_run)
        if str(receipt.get("tool_use_id") or "").startswith(
            "effectful-chain-denial-")
    ]
    effectful_chain_receipts_preserve_effect_without_maintenance = bool(
        all(effectful_chain_hook_results)
        and len(effectful_chain_receipts) == 3
        and [
            receipt.get("capability_effect")
            for receipt in effectful_chain_receipts
        ] == ["target", "model_egress", "target"]
        and [
            receipt.get("target_action")
            for receipt in effectful_chain_receipts
        ] == [True, False, True]
        and effectful_chain_receipts[2].get("capability_effects")
        == ["target", "model_egress"]
        and all(
            len(receipt.get("target_retry_action_sha256s") or []) == 1
            for receipt in (
                effectful_chain_receipts[0], effectful_chain_receipts[2],
            )
        )
        and effectful_chain_receipts[1].get(
            "target_retry_action_sha256s") == []
        and all(
            receipt.get("decision_code") == E_LIFECYCLE_EXACT_ARGV_REQUIRED
            and receipt.get("shape_category") == "registered-chain"
            and receipt.get("maintenance_action") is False
            and receipt.get("maintenance_paths") == []
            for receipt in effectful_chain_receipts
        )
        and not load_contract(chain_receipt_run).get("maintenance_blocked")
        and not runtime_receipts.unresolved_maintenance_blockers(
            chain_receipt_run)
    )
    invalid_chain_hook_results = [
        handle_event({
            "hook_event_name": "PreToolUse",
            "session_id": "registered-chain-session",
            "transcript_path": str(chain_receipt_transcript),
            "tool_name": "Bash",
            "tool_use_id": f"invalid-chain-denial-{index}",
            "tool_input": event["tool_input"],
        }, chain_receipt_run)
        for index, event in enumerate(
            invalid_registered_chain_events, start=1)
    ]
    invalid_chain_receipts = [
        receipt for receipt in runtime_receipts.load_events(chain_receipt_run)
        if str(receipt.get("tool_use_id") or "").startswith(
            "invalid-chain-denial-")
    ]
    invalid_chain_receipts_are_nonmaintenance = bool(
        all(invalid_chain_hook_results)
        and len(invalid_chain_receipts) == 2
        and [
            receipt.get("target_action")
            for receipt in invalid_chain_receipts
        ] == [False, True]
        and [
            len(receipt.get("target_retry_action_sha256s") or [])
            for receipt in invalid_chain_receipts
        ] == [0, 1]
        and all(
            receipt.get("shape_category")
            == "registered-chain-invalid-argv"
            and receipt.get("maintenance_action") is False
            and receipt.get("maintenance_paths") == []
            for receipt in invalid_chain_receipts
        )
        and not runtime_receipts.unresolved_maintenance_blockers(
            chain_receipt_run)
    )
    unsafe_chain_receipt_classifications: list[bool] = []
    for index, event in enumerate(unsafe_registered_chains, start=1):
        unsafe_run = root / f"unsafe-chain-receipt-{index}"
        (unsafe_run / "state").mkdir(parents=True)
        unsafe_session = f"unsafe-chain-session-{index}"
        unsafe_contract = {
            **contract,
            "origin_run": unsafe_run.name,
            "bound_run": unsafe_run.name,
            "session_id": unsafe_session,
            "updated_at": time.time(),
        }
        _atomic_json(contract_path(unsafe_run), unsafe_contract)
        unsafe_transcript = root / f"unsafe-chain-transcript-{index}.jsonl"
        unsafe_tool_id = f"unsafe-chain-denial-{index}"
        unsafe_transcript.write_text(unsafe_tool_id + "\n", encoding="utf-8")
        unsafe_hook_result = handle_event({
            "hook_event_name": "PreToolUse",
            "session_id": unsafe_session,
            "transcript_path": str(unsafe_transcript),
            "tool_name": "Bash",
            "tool_use_id": unsafe_tool_id,
            "tool_input": event["tool_input"],
        }, unsafe_run)
        unsafe_events = runtime_receipts.load_events(unsafe_run)
        unsafe_receipt = unsafe_events[-1] if unsafe_events else {}
        unsafe_chain_receipt_classifications.append(bool(
            unsafe_hook_result
            and unsafe_receipt.get("decision_code")
            != E_LIFECYCLE_EXACT_ARGV_REQUIRED
            and unsafe_receipt.get("maintenance_action") is True
            and unsafe_receipt.get("target_action") is False
            and runtime_receipts.unresolved_maintenance_blockers(unsafe_run)
        ))
    unsafe_chain_receipts_preserve_conservative_maintenance = bool(
        unsafe_chain_receipt_classifications
        and all(unsafe_chain_receipt_classifications)
    )
    unresolved_effectful_chain_before_retry = (
        runtime_receipts.unresolved_target_denials(
            chain_receipt_run,
            session_id="registered-chain-session",
        )
    )
    target_retry_command = str(registry_probe["tool_input"]["command"])
    runtime_receipts.append_hook_event(chain_receipt_run, {
        "hook_event_name": "PostToolUse",
        "session_id": "registered-chain-session",
        "transcript_path": str(chain_receipt_transcript),
        "tool_name": "Bash",
        "tool_use_id": "effectful-chain-target-retry",
        "tool_input": {
            "command": target_retry_command,
            "description": "presentation-only retry metadata",
        },
        "tool_response": {"stdout": "controlled target retry success"},
        "xunji_target_action": True,
        "xunji_capability_effect": "target",
    })
    unresolved_effectful_chain_after_retry = (
        runtime_receipts.unresolved_target_denials(
            chain_receipt_run,
            session_id="registered-chain-session",
        )
    )
    effectful_chain_target_debt_resolves_by_exact_segment = bool(
        len(unresolved_effectful_chain_before_retry) == 3
        and not unresolved_effectful_chain_after_retry
    )
    invalid_argv_receipt_run = root / "invalid-argv-receipt-run"
    (invalid_argv_receipt_run / "state").mkdir(parents=True)
    invalid_argv_contract = _contract_from_event({
        "prompt": "继续当前 run 并按 owner 文档生成完整 work plan",
        "session_id": "invalid-argv-session",
    }, run_name=invalid_argv_receipt_run.name)
    invalid_argv_contract.update({
        "origin_run": invalid_argv_receipt_run.name,
        "bound_run": invalid_argv_receipt_run.name,
        "updated_at": time.time(),
    })
    _atomic_json(contract_path(invalid_argv_receipt_run), invalid_argv_contract)
    e2e_incomplete_plan = registered_event(
        "tools/work_plan.py", "commit", str(invalid_argv_receipt_run),
        "--stage", "S2", "--mode", "PARALLEL_AGENTS",
        "--reason", "E2E primary-driver validation cycle",
    )
    invalid_argv_hook_result = handle_event({
        "hook_event_name": "PreToolUse",
        "session_id": "invalid-argv-session",
        "transcript_path": str(root / "invalid-argv-transcript.jsonl"),
        "tool_name": "Bash",
        "tool_use_id": "invalid-argv-denial-1",
        "tool_input": e2e_incomplete_plan["tool_input"],
    }, invalid_argv_receipt_run)
    incomplete_lane = json.dumps({"id": "L-schema-invalid"}, separators=(",", ":"))
    registry_valid_failed_plan = registered_event(
        "tools/work_plan.py", "commit", str(invalid_argv_receipt_run),
        "--stage", "S2", "--objective", "review one bounded front",
        "--mode", "SERIAL_AGENT", "--reason", "one dependency chain",
        "--exit-gate", "frozen result reviewed and Root-disposed",
        "--lane", incomplete_lane,
    )
    valid_failed_capability = _registered_capability_invocation(
        registry_valid_failed_plan["tool_input"]["command"])
    handle_event({
        "hook_event_name": "PostToolUseFailure",
        "session_id": "invalid-argv-session",
        "transcript_path": str(root / "invalid-argv-transcript.jsonl"),
        "tool_name": "Bash",
        "tool_use_id": "valid-control-failure-1",
        "tool_input": registry_valid_failed_plan["tool_input"],
        "tool_response": {"error": "lane missing required semantic fields"},
    }, invalid_argv_receipt_run)
    invalid_argv_receipts = {
        str(item.get("tool_use_id") or ""): item
        for item in runtime_receipts.load_events(invalid_argv_receipt_run)
    }
    invalid_argv_denial_receipt = invalid_argv_receipts.get(
        "invalid-argv-denial-1", {})
    valid_control_failure_receipt = invalid_argv_receipts.get(
        "valid-control-failure-1", {})
    invalid_argv_and_control_failure_receipts_are_nonmaintenance = bool(
        invalid_argv_hook_result
        and invalid_argv_denial_receipt.get("decision_code")
        == E_LIFECYCLE_EXACT_ARGV_REQUIRED
        and invalid_argv_denial_receipt.get("decision_class") == "command_shape"
        and invalid_argv_denial_receipt.get("shape_category") == "invalid-argv"
        and invalid_argv_denial_receipt.get("maintenance_action") is False
        and invalid_argv_denial_receipt.get("target_action") is False
        and valid_failed_capability
        and valid_failed_capability[0].id == "control.work-plan"
        and valid_control_failure_receipt.get("capability_id")
        == "control.work-plan"
        and valid_control_failure_receipt.get("capability_effect") == "control"
        and valid_control_failure_receipt.get("maintenance_action") is False
        and valid_control_failure_receipt.get("success") is False
        and not runtime_receipts.unresolved_maintenance_blockers(
            invalid_argv_receipt_run,
            session_id="invalid-argv-session",
            since=float(invalid_argv_contract.get("updated_at") or 0.0),
        )
        and not load_contract(invalid_argv_receipt_run).get("maintenance_blocked")
        and not (invalid_argv_receipt_run / "state" / "work_plan.json").exists()
        and not (invalid_argv_receipt_run / "state" / "loop_journal.jsonl").exists()
    )
    generic_shell_run = root / "generic-shell-denial-run"
    (generic_shell_run / "state").mkdir(parents=True)
    (generic_shell_run / "frontier.md").write_text(
        """# Frontier
## Open Fronts
### F-001
- Front: local read-shape validation
- Assets: fixture.invalid
- Why it matters: exercise a destination-free local shell denial
- Current depth: shallow
- Status: open
- Barrier class: none
- Failure budget:
  - Same barrier failures: 0
  - Same bypass family attempts: 0
  - Same tech-stack assets tried: 0
- Vectors tried: none
- Untried classes: local read grammar
- Best current evidence: none
- Next autonomous move: use a registered read
- Stop condition: one attributable local result
- Unruled out: target behavior intentionally untested
- Linked hypotheses: none
## Deferred Fronts
## Closed Fronts
""",
        encoding="utf-8",
    )
    (generic_shell_run / "coverage.json").write_text(
        json.dumps({"assets": [{
            "host": "fixture.invalid",
            "reachable": True,
            "examined": True,
            "scope_status": "in",
        }]}), encoding="utf-8")
    generic_shell_contract = _contract_from_event({
        "prompt": "继续执行当前本地 run 的命令边界验证",
        "session_id": "generic-shell-session",
    }, run_name=generic_shell_run.name)
    generic_shell_contract.update({
        "origin_run": generic_shell_run.name,
        "bound_run": generic_shell_run.name,
        "updated_at": time.time(),
        "coordination_signature": _coordination_signature(generic_shell_run),
    })
    _atomic_json(contract_path(generic_shell_run), generic_shell_contract)
    generic_shell_reason = evaluate_pretool(
        generic_shell_run, generic_read_chain, generic_shell_contract)
    generic_shell_hook_result = handle_event({
        "hook_event_name": "PreToolUse",
        "session_id": "generic-shell-session",
        "transcript_path": str(root / "generic-shell-transcript.jsonl"),
        "tool_name": "Bash",
        "tool_use_id": "generic-shell-denial-1",
        "tool_input": generic_read_chain["tool_input"],
    }, generic_shell_run)
    generic_shell_receipts = runtime_receipts.load_events(generic_shell_run)
    generic_shell_receipt = generic_shell_receipts[-1] \
        if generic_shell_receipts else {}
    generic_read_chain_is_allowed_without_maintenance = bool(
        generic_shell_hook_result is None
        and generic_shell_reason == ""
        and not _maintenance_action(
            generic_read_chain, contract=generic_shell_contract)
        and generic_shell_receipt == {}
        and not runtime_receipts.unresolved_maintenance_blockers(
            generic_shell_run,
            session_id="generic-shell-session",
            since=float(generic_shell_contract.get("updated_at") or 0.0),
        )
        and not load_contract(generic_shell_run).get("maintenance_blocked")
    )
    unrelated_source_setup_blocked = bool(evaluate_pretool(run, source_control, {
        **contract, "prompt_excerpt": "/loop https://unrelated.example/",
    }))
    basename_collision_source_blocked = bool(evaluate_pretool(run, source_control, {
        **contract, "prompt_excerpt": "/loop /tmp/path?key=opaque",
    }))
    setup_without_operator_blocked = bool(evaluate_pretool(run, setup_control, {
        **contract, "prompt_excerpt": "继续当前 run 的 F-001",
    }))
    journal_allowed_before_fanout = not bool(evaluate_pretool(run, journal_control, contract))
    clear_without_operator_blocked = bool(evaluate_pretool(run, clear_active, contract))
    clear_with_operator_blocked = E_CLEAR_ACTIVE_FORBIDDEN in evaluate_pretool(
        run, clear_active, {
        **contract, "prompt_excerpt": "清除 active run 指针",
    })
    clear_with_english_operator_blocked = E_CLEAR_ACTIVE_FORBIDDEN in evaluate_pretool(
        run, clear_active, {
        **contract, "prompt_excerpt": "clear the active run pointer",
    })
    wrapped_clear_active_blocked = E_LIFECYCLE_EXACT_ARGV_REQUIRED in evaluate_pretool(
        run, wrapped_clear_active, contract)
    unrelated_set_active_blocked = bool(evaluate_pretool(run, set_active, contract))
    named_set_active_allowed = not bool(evaluate_pretool(run, set_active, {
        **contract, "prompt_excerpt": "/loop runs/other_20260101",
    }))
    exact_set_active_authority = evaluate_pretool(
        run, set_active, set_active_operator_contract) == ""
    set_active_prefix_collision_blocked = bool(evaluate_pretool(
        run, set_active, set_active_prefix_contract))
    set_active_url_path_collision_blocked = bool(evaluate_pretool(
        run, set_active, set_active_url_collision_contract))
    named_resume_allowed = not bool(evaluate_pretool(run, resume_control, {
        **contract, "prompt_excerpt": "/loop runs/other_20260101",
    }))
    classify_setup_target = _lifecycle_target_name((
        ROOT / "tools" / "setup_run.py",
        ["--classify", "classified", str(root / "recon.json"), "--date", "20260101"],
    ))
    url_setup_target = _lifecycle_target_name((
        ROOT / "tools" / "setup_run.py",
        ["url-target", "--target", "https://example.test:8443", "--date", "20260101"],
    ))
    routed_url_target = _lifecycle_target_name((
        ROOT / "tools" / "loop_bootstrap.py",
        ["--source", source_url, "--type", "auto"],
    ))
    unknown_option_target = _lifecycle_target_name((
        ROOT / "tools" / "setup_run.py",
        ["--future-option", "wrong-slug", "real-slug", "--date", "20260101"],
    ))
    direct_resume_target = _lifecycle_target_name((
        ROOT / "tools" / "loop_bootstrap.py",
        ["--resume", "runs/resume_20260101"],
    ))
    direct_set_active_target = _lifecycle_target_name((
        ROOT / "tools" / "xunji_statusline.py",
        ["--set-active", "runs/selected_20260101"],
    ))
    effect_target = "effect_20260101"
    setup_plain_effect = _lifecycle_transition_effect((
        ROOT / "tools" / "setup_run.py",
        ["effect", str(root / "recon.json"), "--date", "20260101"],
    ), effect_target)
    setup_classify_effect = _lifecycle_transition_effect((
        ROOT / "tools" / "setup_run.py",
        ["effect", str(root / "recon.json"), "--date", "20260101", "--classify"],
    ), effect_target)
    statusline_activate_effect = _lifecycle_transition_effect((
        ROOT / "tools" / "xunji_statusline.py",
        ["--set-active", f"runs/{effect_target}"],
    ), effect_target)
    bootstrap_resume_effect = _lifecycle_transition_effect((
        ROOT / "tools" / "loop_bootstrap.py",
        ["--resume", f"runs/{effect_target}"],
    ), effect_target)
    external_candidate = json.dumps({
        "schema": setup_normalizer.CANDIDATE_SCHEMA,
        "request_sha256": "a" * 64,
        "source_sha256": "b" * 64,
        "redacted_sha256": "c" * 64,
        "target_token": None,
        "asset_tokens": [],
        "entry_tokens": [],
        "scope_refs": [],
        "authorization_refs": [],
        "signal_refs": [],
        "unresolved": [],
    })
    external_effect_a = _lifecycle_transition_effect((
        ROOT / "tools" / "loop_bootstrap.py",
        [
            "--source", str(effect_source), "--type", "file",
            "--ai", "external", "--ai-provider", "fixture-provider",
            "--ai-model", "fixture-model-a", "--candidate-json", external_candidate,
        ],
    ), effect_target)
    external_effect_b = _lifecycle_transition_effect((
        ROOT / "tools" / "loop_bootstrap.py",
        [
            "--source", str(effect_source), "--type", "file",
            "--ai", "external", "--ai-provider", "fixture-provider",
            "--ai-model", "fixture-model-b", "--candidate-json", external_candidate,
        ],
    ), effect_target)
    lifecycle_effect_options_are_exact = bool(
        setup_plain_effect and setup_classify_effect
        and setup_plain_effect["operation"] == setup_transaction.OP_SETUP_RUN_CREATE
        and setup_plain_effect["options_sha256"]
        != setup_classify_effect["options_sha256"]
        and statusline_activate_effect and bootstrap_resume_effect
        and statusline_activate_effect["operation"]
        == setup_transaction.OP_STATUSLINE_SET_ACTIVE
        and bootstrap_resume_effect["operation"]
        == setup_transaction.OP_LOOP_BOOTSTRAP_RESUME
        and statusline_activate_effect["effect_sha256"]
        != bootstrap_resume_effect["effect_sha256"]
        and external_effect_a and external_effect_b
        and external_effect_a["options_sha256"] != external_effect_b["options_sha256"]
        and "fixture-model" not in str(external_effect_a)
    )
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
    coordinator_denial_reason = (
        f"[{E_ROOT_COORDINATOR_ONLY}] Root coordinator cannot execute this lane")
    denied_local_compound = {
        "tool_name": "Bash", "tool_input": {"command": (
            f"ls {run} && echo local 2>/dev/null || echo missing")},
    }
    denied_local_python = {
        "tool_name": "Bash", "tool_input": {"command": (
            "python3 -c 'import glob; print(glob.glob(\"state/*\"))'")},
    }
    denied_raw_target = {
        "tool_name": "Bash", "tool_input": {
            "command": "curl https://example.test/health"},
    }
    denied_webfetch = {
        "tool_name": "WebFetch", "tool_input": {
            "url": "https://example.test/health"},
    }
    denied_schedule_wakeup = {
        "tool_name": "ScheduleWakeup", "tool_input": {
            "prompt": "continue offline review for https://example.test/health"},
    }
    readonly_url_argument = {
        "tool_name": "Bash", "tool_input": {
            "command": "cat https://example.test/not-a-network-read"},
    }
    denial_receipt_effects_are_narrow = bool(
        not _is_target_action(denied_local_compound)
        and _is_target_action(denied_local_python)
        and not _denial_is_target_action(
            denied_local_compound, coordinator_denial_reason)
        and not _denial_is_target_action(
            denied_local_python, coordinator_denial_reason)
        and _denial_is_target_action(
            denied_raw_target, coordinator_denial_reason)
        and _denial_is_target_action(
            registry_probe, coordinator_denial_reason)
        and _denial_is_target_action(
            denied_webfetch, coordinator_denial_reason)
        and not _is_target_action(denied_schedule_wakeup)
        and not _denial_is_target_action(
            denied_schedule_wakeup, coordinator_denial_reason)
        and not _is_target_action(readonly_url_argument)
        and not _denial_is_target_action(
            readonly_url_argument, coordinator_denial_reason)
    )
    settlement_order_run = root / "settlement-order"
    (settlement_order_run / "state").mkdir(parents=True)
    (settlement_order_run / "frontier.md").write_text(
        "# Frontier\n## Open Fronts\n### F-001\n- Status: open\n"
        "- Barrier class: none\n- Current depth: shallow\n",
        encoding="utf-8",
    )
    settlement_rows = {
        "assignments": [{
            "agent": "A-hunter-001", "role": "web-hunter", "status": "done",
        }, {
            "agent": "A-review-001", "role": "review", "status": "reviewed",
            "reviews_assignments": ["A-hunter-001"],
        }],
    }
    (settlement_order_run / "state" / "assignments.json").write_text(
        json.dumps(settlement_rows), encoding="utf-8")
    canonical_edit = {
        "tool_name": "Edit",
        "tool_input": {
            "file_path": str(settlement_order_run / "evidence.md"),
            "old_string": "old", "new_string": "new",
        },
    }
    settlement_contract = {
        "schema": SCHEMA, "mode": EXECUTE, "session_id": "settlement-session",
        "prompt_sha256": "f" * 64, "updated_at": time.time(),
    }
    canonical_before_finish_blocked = (
        E_ROOT_SETTLEMENT_REQUIRED in evaluate_pretool(
            settlement_order_run, canonical_edit, settlement_contract)
    )
    settlement_rows["assignments"][0]["status"] = "blocked"
    (settlement_order_run / "state" / "assignments.json").write_text(
        json.dumps(settlement_rows), encoding="utf-8")
    canonical_after_finish_unblocked = (
        E_ROOT_SETTLEMENT_REQUIRED not in evaluate_pretool(
            settlement_order_run, canonical_edit, settlement_contract)
    )
    pointer_write = {
        "tool_name": "Write",
        "tool_input": {"file_path": str(ROOT / ".claude" / "xunji_active_run"),
                       "content": "runs/other\n"},
    }
    pointer_shell = {
        "tool_name": "Bash",
        "tool_input": {"command": "rm .claude/xunji_active_run"},
    }
    pointer_write_blocked = bool(evaluate_pretool(run, pointer_write, contract))
    coverage_write = {
        "tool_name": "Write",
        "tool_input": {"file_path": str(run / "coverage.json"), "content": "{}"},
    }
    coverage_write_blocked = "资产账本" in evaluate_pretool(
        run, coverage_write, contract)
    coverage_sync_control = {
        "tool_name": "Bash",
        "tool_input": {"command": (
            f"python3 {ROOT / 'tools' / 'coverage_matrix.py'} {run} --sync-coverage"
        )},
    }
    coverage_sync_control_allowed = evaluate_pretool(
        run, coverage_sync_control, contract) == ""
    pointer_shell_reason = evaluate_pretool(run, pointer_shell, contract)
    pointer_shell_is_local = not _denial_is_target_action(pointer_shell, pointer_shell_reason)
    transcript = root / "transcript.jsonl"
    transcript.write_text("", encoding="utf-8")
    old_transcript = root / "old-transcript.jsonl"
    old_transcript.write_text("", encoding="utf-8")

    def receipt(tool_id: str, session: str, assignment: str, front: str,
                assets: str) -> None:
        prompt = (
            f"XUNJI_ASSIGNMENT={assignment} XUNJI_FRONT={front} "
            f"XUNJI_ASSETS={assets}"
        )
        child_id = f"child-{tool_id}"
        event_transcript = old_transcript if session == "old-session" else transcript
        with event_transcript.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps({
                "message": {"role": "assistant", "content": [{
                    "type": "tool_use", "id": tool_id, "name": "Agent",
                    "input": {
                        "prompt": prompt,
                        "subagent_type": "xunji-hunter",
                    },
                }]},
            }) + "\n")
        runtime_receipts.append_hook_event(run, {
            "hook_event_name": "SubagentStart", "session_id": session,
            "transcript_path": str(event_transcript),
            "agent_id": child_id, "agent_type": "xunji-hunter",
        })
        runtime_receipts.append_hook_event(run, {
            "hook_event_name": "SubagentStop", "session_id": session,
            "transcript_path": str(event_transcript),
            "agent_id": child_id, "agent_type": "xunji-hunter",
            "last_assistant_message": "done",
        })
        with event_transcript.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps({
                "message": {"content": [{
                    "type": "tool_result", "tool_use_id": tool_id,
                    "content": [{"type": "text", "text": "done"}],
                }]},
            }) + "\n")
        runtime_receipts.append_hook_event(run, {
            "hook_event_name": "PostToolUse", "session_id": session,
            "transcript_path": str(event_transcript), "tool_name": "Agent",
            "tool_use_id": tool_id,
            "tool_input": {
                "prompt": prompt,
                "subagent_type": "xunji-hunter",
            },
            "tool_response": [{"type": "text", "text": "done"}],
        })

    receipt("old-agent-1", "old-session", "A-web-001", "F-001", "example.test")
    receipt("old-agent-2", "old-session", "A-auth-001", "F-002", "auth.example.test")
    old_fanout_still_blocked = bool(evaluate_pretool(run, target_event, contract))
    receipt("current-agent-1", "s", "A-web-001", "F-001", "example.test")
    receipt("current-agent-2", "s", "A-auth-001", "F-002", "auth.example.test")
    receipts_without_disposition_block = bool(evaluate_pretool(run, target_event, contract))
    (run / "evidence.md").write_text("# Evidence\n## E-001 - merged candidate\n", encoding="utf-8")
    assignment_state = json.loads((run / "state" / "assignments.json").read_text(encoding="utf-8"))
    for item in assignment_state["assignments"]:
        item.update({
            "status": "merged",
            "updated_at": datetime.now(timezone.utc).isoformat(),
            "last_note": f"Evidence: E-001 merged for Front: {item['front']}",
            "coverage_merge_satisfied": True,
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
    cron_contract = {**contract, "prompt_excerpt": f"/loop {run.name}"}
    cron_before_list = bool(evaluate_pretool(run, cron_create, cron_contract))
    with transcript.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps({
            "message": {"role": "assistant", "content": [{
                "type": "tool_use", "id": "current-cron-list",
                "name": "CronList", "input": {},
            }]},
        }) + "\n")
        handle.write(json.dumps({
            "message": {"content": [{
                "type": "tool_result", "tool_use_id": "current-cron-list",
                "content": [{"type": "text", "text": '{"tasks": []}'}],
            }]},
        }) + "\n")
    runtime_receipts.append_hook_event(run, {
        "hook_event_name": "PostToolUse", "session_id": "s",
        "transcript_path": str(transcript), "tool_name": "CronList",
        "tool_use_id": "current-cron-list", "tool_input": {},
        "tool_response": {"tasks": []},
    })
    cron_after_list = evaluate_pretool(run, cron_create, cron_contract) == ""
    new_run_cron_blocked_until_transition = "先完成 setup" in evaluate_pretool(
        run, cron_create, contract)
    lifecycle_task = {"tool_name": "TaskCreate", "tool_input": {
        "subject": "decompose assets and Agent lanes",
        "description": "review https://bound.example.test/?key=plan-secret",
    }}
    pending_loop_contract = {
        **source_operator_contract,
        "origin_run": run.name,
        "bound_run": run.name,
        "updated_at": time.time(),
    }
    pending_plan_requires_setup = E_NEW_RUN_SETUP_REQUIRED in evaluate_pretool(
        run, lifecycle_task, pending_loop_contract)
    pending_agent_requires_setup = E_NEW_RUN_SETUP_REQUIRED in evaluate_pretool(
        run, agent_bad, pending_loop_contract)

    lifecycle_run = root / "bound_20260716"
    (lifecycle_run / "state").mkdir(parents=True)
    (lifecycle_run / "agents").mkdir()
    (lifecycle_run / "frontier.md").write_text(
        "# Frontier\n\n## Open Fronts\n\n### F-001 — app.example serial lifecycle\n"
        "- Status: open\n- Barrier class: auth-layer\n- Current depth: shallow\n",
        encoding="utf-8",
    )
    (lifecycle_run / "target.md").write_text(
        "# Target\n- Authorized scope: bound.example.test\n",
        encoding="utf-8",
    )
    (lifecycle_run / "coverage.json").write_text(
        json.dumps({"assets": [{
            "host": "app.example", "reachable": True, "examined": False,
        }]}), encoding="utf-8")
    (lifecycle_run / "state" / "assignments.json").write_text(
        json.dumps({"assignments": []}), encoding="utf-8")
    lifecycle_txid = "7" * 32
    lifecycle_source_hash = "8" * 64
    lifecycle_contract = {
        **source_operator_contract,
        "origin_run": run.name,
        "bound_run": lifecycle_run.name,
        "updated_at": time.time() - 0.01,
        "transition_transaction": {
            "transaction_id": lifecycle_txid,
            "source_sha256": lifecycle_source_hash,
            "expected_run": lifecycle_run.name,
        },
    }
    uncommitted_transition_blocked = E_NEW_RUN_SETUP_REQUIRED in evaluate_pretool(
        lifecycle_run, lifecycle_task, lifecycle_contract)
    (lifecycle_run / "state" / "setup_transaction.json").write_text(json.dumps({
        "schema": "xunji.setup_transaction.v1",
        "status": "committed",
        "transaction_id": lifecycle_txid,
        "source_sha256": lifecycle_source_hash,
        "contract_binding": {
            "transaction_id": lifecycle_txid,
            "source_sha256": lifecycle_source_hash,
            "expected_run": lifecycle_run.name,
            "session_id": str(lifecycle_contract.get("session_id") or ""),
            "prompt_sha256": str(lifecycle_contract.get("prompt_sha256") or ""),
        },
    }), encoding="utf-8")
    plan_before_cron_blocked = E_CRON_CREATE_REQUIRED in evaluate_pretool(
        lifecycle_run, lifecycle_task, lifecycle_contract)
    lifecycle_agent = {"tool_name": "Agent", "tool_input": {"prompt": "work F-001"}}
    agent_before_cron_blocked = E_CRON_CREATE_REQUIRED in evaluate_pretool(
        lifecycle_run, lifecycle_agent, lifecycle_contract)
    no_active_lifecycle_contract = {
        **lifecycle_contract,
        "origin_run": "",
        "bound_run": lifecycle_run.name,
        "transitioned_from": "pending:no-active-run",
    }
    no_active_transition_reaches_cron_gate = bool(
        not _new_run_transition_pending(no_active_lifecycle_contract, lifecycle_run)
        and E_CRON_CREATE_REQUIRED in evaluate_pretool(
            lifecycle_run, lifecycle_task, no_active_lifecycle_contract)
        and "RUN_BOUND" in _context_message(
            no_active_lifecycle_contract, lifecycle_run)
    )
    lifecycle_transcript = root / "lifecycle-transcript.jsonl"
    lifecycle_transcript.write_text(
        "bound-cron\nbound-task\n", encoding="utf-8")
    runtime_receipts.append_hook_event(lifecycle_run, {
        "hook_event_name": "PostToolUse",
        "session_id": str(lifecycle_contract.get("session_id") or ""),
        "transcript_path": str(lifecycle_transcript),
        "tool_name": "CronCreate", "tool_use_id": "bound-cron",
        "tool_input": {"prompt": f"/loop {lifecycle_run.name}"},
        "tool_response": {"id": "bound-cron-job"},
    })
    agent_before_plan_blocked = E_ITERATION_PLAN_REQUIRED in evaluate_pretool(
        lifecycle_run, lifecycle_agent, lifecycle_contract)
    plan_allowed_after_cron = evaluate_pretool(
        lifecycle_run, lifecycle_task, lifecycle_contract) == ""
    runtime_receipts.append_hook_event(lifecycle_run, {
        "hook_event_name": "PostToolUse",
        "session_id": str(lifecycle_contract.get("session_id") or ""),
        "transcript_path": str(lifecycle_transcript),
        "tool_name": "TaskCreate", "tool_use_id": "bound-task",
        "tool_input": lifecycle_task["tool_input"],
        "tool_response": {"taskId": "bound-task-id"},
    })
    post_plan_agent_reason = evaluate_pretool(
        lifecycle_run, lifecycle_agent, lifecycle_contract)
    work_plan_missing_after_task = E_WORK_PLAN_REQUIRED in post_plan_agent_reason
    work_plan_route_is_explicit = (
        ".claude/skills/xunji-agent-board/SKILL.md" in post_plan_agent_reason
        and f"python3 tools/workers.py plan runs/{lifecycle_run.name} --limit 2"
        in post_plan_agent_reason
        and "不要读取 tools 源码" in post_plan_agent_reason
    )
    lifecycle_model_review = registered_event(
        "tools/peer_review.py", str(lifecycle_run), "--backend", "claude")
    model_egress_work_plan_missing = E_WORK_PLAN_REQUIRED in evaluate_pretool(
        lifecycle_run, lifecycle_model_review, lifecycle_contract)
    serial_plan = work_plan.commit_plan(
        lifecycle_run,
        macro_stage="S2",
        objective="exercise one bounded serial Hunter lane",
        mode="SERIAL_AGENT",
        reason="one complex lane with a shared dependency",
        exit_gate="Hunter return receives Reviewer disposition",
        lanes=[{
            "id": "L-F001-HUNTER",
            "role": "web-hunter",
            "front": "F-001",
            "effect": "local_read",
            "assets": ["app.example"],
            "dependencies": [],
            "expected_evidence": "attributed candidate or refutation",
            "expected_information_gain": "medium",
            "stop_condition": "candidate settled or a concrete blocker recorded",
            "request_cost": 0,
            "request_budget": 0,
            "merge_cost": 10,
            "atomic": False,
        }, {
            "id": "L-F001-REVIEW",
            "role": "review",
            "front": "F-001",
            "effect": "local_verify",
            "assets": ["app.example"],
            "dependencies": ["L-F001-HUNTER"],
            "expected_evidence": "digest-bound challenge of the Hunter return",
            "expected_information_gain": "medium",
            "stop_condition": "exact frozen result receives a disposition",
            "request_cost": 0,
            "request_budget": 0,
            "merge_cost": 10,
            "atomic": False,
        }],
        contract=lifecycle_contract,
    )
    lifecycle_assignment = "A-work-plan-001"
    (lifecycle_run / "state" / "turn_contract.json").write_text(
        json.dumps(lifecycle_contract), encoding="utf-8")
    workers.create_agent_assignment(
        lifecycle_run,
        role="web-hunter",
        front="F-001",
        scope="exercise one bounded serial Hunter lane",
        agent=lifecycle_assignment,
        assets=["app.example"],
        lane_id="L-F001-HUNTER",
    )
    planned_prompt = runtime_receipts.assignment_launch_prompt(
        _assignment_record(lifecycle_run, lifecycle_assignment, "F-001"))
    planned_type = "xunji-hunter"
    planned_agent = {
        "tool_name": "Agent", "tool_input": {
            "prompt": planned_prompt,
            "subagent_type": planned_type,
        }}
    planned_agent_allowed = evaluate_pretool(
        lifecycle_run, planned_agent, lifecycle_contract) == ""
    wrong_plan_agent = {"tool_name": "Agent", "tool_input": {
        "prompt": (
            f"XUNJI_ASSIGNMENT={lifecycle_assignment} XUNJI_FRONT=F-001 "
            "XUNJI_ASSETS=app.example XUNJI_LANE=L-F001-HUNTER "
            f"XUNJI_PLAN={'0' * 64}"
        ),
        "subagent_type": planned_type,
    }}
    mismatched_plan_agent_blocked = E_DELEGATION_REQUIRED in evaluate_pretool(
        lifecycle_run, wrong_plan_agent, lifecycle_contract)
    altered_plan_prompts = (
        planned_prompt + "\nAdditional hand-written context",
        "Read context first. " + planned_prompt,
        planned_prompt.replace(" XUNJI_FRONT", "  XUNJI_FRONT", 1),
        " ".join(reversed(planned_prompt.split())),
    )
    altered_plan_prompts_blocked = all(
        E_DELEGATION_REQUIRED in evaluate_pretool(
            lifecycle_run,
            {"tool_name": "Agent", "tool_input": {
                "prompt": candidate,
                "subagent_type": planned_type,
            }},
            lifecycle_contract,
        )
        for candidate in altered_plan_prompts
    )
    canary_receipt_run = root / "canary-delegation-receipt-run"
    (canary_receipt_run / "state").mkdir(parents=True)
    (canary_receipt_run / "agents").mkdir()
    (canary_receipt_run / "context").mkdir()
    for name in ("target.md", "frontier.md"):
        (canary_receipt_run / name).write_text(
            (lifecycle_run / name).read_text(encoding="utf-8"),
            encoding="utf-8",
        )
    canary_row = json.loads(json.dumps(
        json.loads((lifecycle_run / "state" / "assignments.json").read_text(
            encoding="utf-8"))["assignments"][0]
    ))
    canary_context_path = canary_receipt_run / "context" / f"{lifecycle_assignment}.md"
    canary_agent_path = canary_receipt_run / "agents" / f"{lifecycle_assignment}.md"
    canary_context_text = "# Frozen context\n"
    canary_agent_text = "# Agent\n"
    canary_row["context"] = str(canary_context_path)
    canary_row["agent_file"] = str(canary_agent_path)
    canary_context_path.write_bytes(canary_context_text.encode("utf-8"))
    canary_agent_path.write_bytes(canary_agent_text.encode("utf-8"))
    canary_role_bundle = agent_instruction_bundle.load_role_contract(
        "web-hunter", root=ROOT)
    canary_scaffold = agent_instruction_bundle.load_scaffold_source(root=ROOT)
    canary_bundle, canary_bundle_digest = (
        agent_instruction_bundle.build_assignment_bundle(
            assignment=lifecycle_assignment,
            plan_digest=str(canary_row["plan_digest"]),
            lane_id=str(canary_row["lane_id"]),
            role="web-hunter",
            role_bundle=canary_role_bundle,
            scaffold_source=canary_scaffold["source"],
            context_path=str(canary_context_path),
            context_text=canary_context_text,
            agent_path=str(canary_agent_path),
            agent_text=canary_agent_text,
        )
    )
    canary_row["instruction_bundle"] = canary_bundle
    canary_row["instruction_bundle_sha256"] = canary_bundle_digest
    (canary_receipt_run / "state" / "assignments.json").write_text(
        json.dumps({"schema": 3, "assignments": [canary_row]}),
        encoding="utf-8",
    )
    canary_transcript = root / "canary-delegation-transcript.jsonl"
    canary_transcript.write_text("canary-delegation\n", encoding="utf-8")
    write_contract(canary_receipt_run, {
        "prompt": f"继续执行 runs/{canary_receipt_run.name}",
        "session_id": "canary-delegation-session",
        "transcript_path": str(canary_transcript),
    })
    canary_prompt = runtime_receipts.assignment_launch_prompt(canary_row)
    canary_denial = handle_event({
        "hook_event_name": "PreToolUse",
        "session_id": "canary-delegation-session",
        "transcript_path": str(canary_transcript),
        "tool_name": "Agent",
        "tool_use_id": "canary-appended-prompt",
        "tool_input": {
            "prompt": canary_prompt + " XUNJI_CANARY_APPEND=1",
            "subagent_type": planned_type,
        },
    }, canary_receipt_run)
    canary_receipts = runtime_receipts.load_events(canary_receipt_run)
    canary_receipt = canary_receipts[-1] if canary_receipts else {}
    canary_denial_persists_delegation_code = bool(
        canary_denial
        and canary_receipt.get("hook_event_name") == "PreToolUseDenied"
        and canary_receipt.get("decision_code") == E_DELEGATION_REQUIRED
        and canary_receipt.get("decision_class") == "delegation"
        and canary_receipt.get("maintenance_action") is False
    )
    description_only_plan_prompt_blocked = E_DELEGATION_REQUIRED in evaluate_pretool(
        lifecycle_run,
        {"tool_name": "Agent", "tool_input": {
            "prompt": "", "description": planned_prompt,
            "subagent_type": planned_type,
        }},
        lifecycle_contract,
    )
    lifecycle_transcript.write_text(
        lifecycle_transcript.read_text(encoding="utf-8") + "planned-agent-tool\n",
        encoding="utf-8",
    )
    runtime_receipts.append_hook_event(lifecycle_run, {
        "hook_event_name": "PostToolUse",
        "session_id": str(lifecycle_contract.get("session_id") or ""),
        "transcript_path": str(lifecycle_transcript),
        "tool_name": "Agent", "tool_use_id": "planned-agent-tool",
        "tool_input": planned_agent["tool_input"],
        "tool_response": {
            "agentId": "runtime-planned-child", "status": "async_launched",
            "isAsync": True,
        },
    })
    planned_child_read_allowed = evaluate_pretool(
        lifecycle_run,
        {"tool_name": "Read", "agent_id": "runtime-planned-child",
         "tool_input": {"file_path": str(lifecycle_run / "frontier.md")}},
        lifecycle_contract,
    ) == ""
    planned_child_verify = registered_event("tools/work_plan.py", "--selftest")
    planned_child_verify["agent_id"] = "runtime-planned-child"
    planned_child_effect_escape_blocked = "effect 边界" in evaluate_pretool(
        lifecycle_run, planned_child_verify, lifecycle_contract)

    def seed_instruction_tamper_run(name: str, agent: str) -> tuple[Path, dict, dict, str]:
        candidate_run = root / name
        candidate_contract, _candidate_plan = seed_current_plan(
            candidate_run, stage="S1")
        candidate_row = workers.create_agent_assignment(
            candidate_run,
            role="verify",
            front="F-001",
            scope="exercise instruction bundle tamper boundary",
            agent=agent,
            assets=[],
            lane_id="L-F001-EXEC",
        )
        candidate_prompt = runtime_receipts.assignment_launch_prompt(candidate_row)
        if not candidate_prompt:
            raise AssertionError("tamper fixture lacks a canonical launch prompt")
        return candidate_run, candidate_contract, candidate_row, candidate_prompt

    def row_artifact_path(row: dict, field: str) -> Path:
        path = Path(str(row.get(field) or ""))
        return path if path.is_absolute() else ROOT / path

    def write_parent_tool_use(
        path: Path, tool_use_id: str, prompt: str, *, append: bool = False,
    ) -> None:
        line = json.dumps({
            "message": {"role": "assistant", "content": [{
                "type": "tool_use", "id": tool_use_id, "name": "Agent",
                "input": {
                    "prompt": prompt, "subagent_type": "xunji-hunter",
                },
            }]},
        }, sort_keys=True) + "\n"
        with path.open("a" if append else "w", encoding="utf-8") as handle:
            handle.write(line)

    parent_tamper_run, parent_tamper_contract, parent_tamper_row, parent_tamper_prompt = (
        seed_instruction_tamper_run(
            "instruction-parent-tamper", "A-parent-tamper"))
    parent_tamper_transcript = root / "instruction-parent-tamper.jsonl"
    write_parent_tool_use(
        parent_tamper_transcript, "parent-tamper-tool", parent_tamper_prompt)
    parent_context_path = row_artifact_path(parent_tamper_row, "context")
    parent_context_bytes = parent_context_path.read_bytes()
    parent_context_path.write_bytes(parent_context_bytes + b"tampered-before-launch\n")
    parent_tamper_denial = handle_event({
        "hook_event_name": "PreToolUse",
        "session_id": str(parent_tamper_contract["session_id"]),
        "transcript_path": str(parent_tamper_transcript.resolve()),
        "tool_name": "Agent", "tool_use_id": "parent-tamper-tool",
        "tool_input": {
            "prompt": parent_tamper_prompt,
            "subagent_type": "xunji-hunter",
        },
    }, parent_tamper_run)
    parent_tamper_events = runtime_receipts.load_events(parent_tamper_run)
    parent_tamper_receipt = parent_tamper_events[-1] if parent_tamper_events else {}
    parent_context_path.write_bytes(parent_context_bytes)
    parent_tamper_original_restored = evaluate_pretool(
        parent_tamper_run,
        {"tool_name": "Agent", "tool_input": {
            "prompt": parent_tamper_prompt,
            "subagent_type": "xunji-hunter",
        }},
        parent_tamper_contract,
    ) == ""
    parent_artifact_tamper_fails_before_launch = bool(
        parent_tamper_denial
        and parent_tamper_receipt.get("hook_event_name") == "PreToolUseDenied"
        and parent_tamper_receipt.get("decision_code")
        == E_AGENT_ARTIFACT_INTEGRITY
        and not any(item.get("hook_event_name") in {
            "PostToolUse", "SubagentStart", "SubagentStop",
        } for item in parent_tamper_events)
        and runtime_receipts.agent_attempts(parent_tamper_run) == []
        and parent_tamper_original_restored
    )

    start_race_run, start_race_contract, start_race_row, start_race_prompt = (
        seed_instruction_tamper_run(
            "instruction-start-race", "A-start-race"))
    start_race_transcript = root / "instruction-start-race.jsonl"
    write_parent_tool_use(
        start_race_transcript, "start-race-tool", start_race_prompt)
    runtime_receipts.append_hook_event(start_race_run, {
        "hook_event_name": "PostToolUse",
        "session_id": str(start_race_contract["session_id"]),
        "transcript_path": str(start_race_transcript.resolve()),
        "tool_name": "Agent", "tool_use_id": "start-race-tool",
        "tool_input": {
            "prompt": start_race_prompt,
            "subagent_type": "xunji-hunter",
        },
        "tool_response": {
            "agentId": "start-race-child", "status": "async_launched",
            "isAsync": True,
        },
    })
    start_race_context = row_artifact_path(start_race_row, "context")
    start_race_context_bytes = start_race_context.read_bytes()
    start_race_context.write_bytes(start_race_context_bytes + b"tampered-before-start\n")
    start_race_events_before = runtime_receipts.load_events(start_race_run)
    start_race_assignments_before = (
        start_race_run / "state" / "assignments.json").read_bytes()
    start_race_attempts_before = runtime_receipts.agent_attempts(start_race_run)
    start_race_error = ""
    try:
        runtime_receipts.append_hook_event(start_race_run, {
            "hook_event_name": "SubagentStart",
            "session_id": str(start_race_contract["session_id"]),
            "transcript_path": str(start_race_transcript.resolve()),
            "agent_id": "start-race-child", "agent_type": "xunji-hunter",
        })
    except RuntimeError as exc:
        start_race_error = str(exc)
    start_race_rejected_without_mutation = bool(
        E_AGENT_ARTIFACT_INTEGRITY in start_race_error
        and runtime_receipts.load_events(start_race_run) == start_race_events_before
        and (start_race_run / "state" / "assignments.json").read_bytes()
        == start_race_assignments_before
        and runtime_receipts.agent_attempts(start_race_run)
        == start_race_attempts_before
    )
    start_race_context.write_bytes(start_race_context_bytes)
    runtime_receipts.append_hook_event(start_race_run, {
        "hook_event_name": "SubagentStart",
        "session_id": str(start_race_contract["session_id"]),
        "transcript_path": str(start_race_transcript.resolve()),
        "agent_id": "start-race-child", "agent_type": "xunji-hunter",
    })
    start_race_recovers_after_exact_restore = bool(
        runtime_receipts.agent_actor(
            start_race_run, "start-race-child",
            session_id=str(start_race_contract["session_id"]),
        )
    )

    child_rebind_run, child_rebind_contract, child_rebind_row, child_rebind_prompt = (
        seed_instruction_tamper_run(
            "instruction-child-rebind", "A-child-rebind"))
    child_rebind_transcript = root / (
        str(child_rebind_contract["session_id"]) + ".jsonl")
    write_parent_tool_use(
        child_rebind_transcript, "child-rebind-parent", child_rebind_prompt)
    runtime_receipts.append_hook_event(child_rebind_run, {
        "hook_event_name": "PostToolUse",
        "session_id": str(child_rebind_contract["session_id"]),
        "transcript_path": str(child_rebind_transcript.resolve()),
        "tool_name": "Agent", "tool_use_id": "child-rebind-parent",
        "tool_input": {
            "prompt": child_rebind_prompt,
            "subagent_type": "xunji-hunter",
        },
        "tool_response": {
            "agentId": "child-rebind-agent", "status": "async_launched",
            "isAsync": True,
        },
    })
    runtime_receipts.append_hook_event(child_rebind_run, {
        "hook_event_name": "SubagentStart",
        "session_id": str(child_rebind_contract["session_id"]),
        "transcript_path": str(child_rebind_transcript.resolve()),
        "agent_id": "child-rebind-agent", "agent_type": "xunji-hunter",
    })
    child_rebind_ledger_path = child_rebind_run / "state" / "assignments.json"
    child_rebind_ledger = json.loads(
        child_rebind_ledger_path.read_text(encoding="utf-8"))
    child_rebind_current = next(
        item for item in child_rebind_ledger["assignments"]
        if item.get("agent") == "A-child-rebind")
    child_rebind_context = row_artifact_path(child_rebind_current, "context")
    child_rebind_agent_file = row_artifact_path(child_rebind_current, "agent_file")
    child_rebind_context.write_bytes(
        child_rebind_context.read_bytes() + b"coordinated-rebind\n")
    child_rebind_role = agent_instruction_bundle.load_role_contract(
        "verify", root=ROOT)
    child_rebind_scaffold = agent_instruction_bundle.load_scaffold_source(root=ROOT)
    child_rebind_bundle, child_rebind_digest = (
        agent_instruction_bundle.build_assignment_bundle(
            assignment="A-child-rebind",
            plan_digest=str(child_rebind_current["plan_digest"]),
            lane_id=str(child_rebind_current["lane_id"]),
            role="verify",
            role_bundle=child_rebind_role,
            scaffold_source=child_rebind_scaffold["source"],
            context_path=str(child_rebind_current["context"]),
            context_text=child_rebind_context.read_text(
                encoding="utf-8", errors="strict"),
            agent_path=str(child_rebind_current["agent_file"]),
            agent_text=child_rebind_agent_file.read_text(
                encoding="utf-8", errors="strict"),
        )
    )
    child_rebind_current["instruction_bundle"] = child_rebind_bundle
    child_rebind_current["instruction_bundle_sha256"] = child_rebind_digest
    child_rebind_ledger_path.write_text(
        json.dumps(child_rebind_ledger, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    child_rebind_bundle_is_internally_valid = True
    try:
        agent_instruction_bundle.verify_assignment_bundle(
            child_rebind_run, child_rebind_current, root=ROOT)
    except agent_instruction_bundle.InstructionBundleError:
        child_rebind_bundle_is_internally_valid = False
    child_read_input = {"file_path": str(child_rebind_run / "frontier.md")}
    child_rebind_sidechain = (
        child_rebind_transcript.with_suffix("") / "subagents"
        / "agent-child-rebind-agent.jsonl")
    child_rebind_sidechain.parent.mkdir(parents=True)
    child_rebind_sidechain.write_text(json.dumps({
        "isSidechain": True,
        "sessionId": str(child_rebind_contract["session_id"]),
        "agentId": "child-rebind-agent",
        "message": {"role": "assistant", "content": [{
            "type": "tool_use", "id": "child-rebind-read",
            "name": "Read", "input": child_read_input,
        }]},
    }, sort_keys=True) + "\n", encoding="utf-8")
    child_rebind_denial = handle_event({
        "hook_event_name": "PreToolUse",
        "session_id": str(child_rebind_contract["session_id"]),
        "transcript_path": str(child_rebind_transcript.resolve()),
        "agent_id": "child-rebind-agent",
        "tool_name": "Read", "tool_use_id": "child-rebind-read",
        "tool_input": child_read_input,
    }, child_rebind_run)
    child_rebind_events = runtime_receipts.load_events(child_rebind_run)
    child_rebind_claims = [
        item for item in child_rebind_events
        if item.get("hook_event_name")
        == runtime_receipts.AGENT_TOOL_CALL_CLAIM_EVENT
        and item.get("tool_use_id") == "child-rebind-read"
    ]
    child_rebind_denials = [
        item for item in child_rebind_events
        if item.get("hook_event_name") == "PreToolUseDenied"
        and item.get("tool_use_id") == "child-rebind-read"
    ]
    child_rebind_start_hash_blocks_mutable_rebind = bool(
        child_rebind_bundle_is_internally_valid
        and child_rebind_denial
        and len(child_rebind_claims) == 1
        and child_rebind_claims[0].get("agent_tool_call_admitted") is True
        and len(child_rebind_denials) == 1
        and child_rebind_denials[0].get("decision_code")
        == E_AGENT_INSTRUCTION_SOURCE_STALE
        and int(child_rebind_claims[0].get("seq") or 0)
        < int(child_rebind_denials[0].get("seq") or 0)
        and not any(
            item.get("hook_event_name") == "PostToolUse"
            and item.get("tool_use_id") == "child-rebind-read"
            for item in child_rebind_events
        )
    )
    serial_root_target_blocked = E_ROOT_COORDINATOR_ONLY in evaluate_pretool(
        lifecycle_run, target_event, lifecycle_contract)
    serial_root_model_egress_blocked = E_ROOT_COORDINATOR_ONLY in evaluate_pretool(
        lifecycle_run, lifecycle_model_review, lifecycle_contract)

    # A canonical-input change after a real Hunter return must not deadlock the
    # unique Reviewer at the real PreToolUse boundary.  This fixture traverses
    # workers delegate -> runtime receipts -> workers stale settlement ->
    # evaluate_pretool instead of calling the shared predicate in isolation.
    stale_review_run = root / "stale-review-pretool"
    (stale_review_run / "state").mkdir(parents=True)
    (stale_review_run / "target.md").write_text(
        "# Target\n- Authorized scope: offline fixture\n", encoding="utf-8")
    (stale_review_run / "coverage.json").write_text(
        json.dumps({"assets": [{
            "host": "offline-review.example", "examined": False,
        }]}), encoding="utf-8")
    (stale_review_run / "frontier.md").write_text(
        "# Frontier\n\n## Open Fronts\n\n### F-001 — offline review\n"
        "- Status: open\n- Barrier class: local-state\n- Current depth: shallow\n",
        encoding="utf-8")
    stale_review_transcript = root / "stale-review-transcript.jsonl"
    stale_review_transcript.write_text("stale-review-task\n", encoding="utf-8")
    stale_review_contract = {
        "schema": SCHEMA, "mode": EXECUTE,
        "session_id": "stale-review-session", "prompt_sha256": "a" * 64,
        "prompt_excerpt": "continue the explicit loop",
        "updated_at": time.time() - 0.01, "loop_requested": True,
        "origin_run": stale_review_run.name,
        "bound_run": stale_review_run.name,
        "transcript_path": str(stale_review_transcript.resolve()),
        "fanout_override": False,
    }
    _atomic_json(contract_path(stale_review_run), stale_review_contract)
    runtime_receipts.append_hook_event(stale_review_run, {
        "hook_event_name": "PostToolUse",
        "session_id": stale_review_contract["session_id"],
        "transcript_path": str(stale_review_transcript),
        "tool_name": "TaskCreate", "tool_use_id": "stale-review-task",
        "tool_input": {"subject": "Hunter then exact Reviewer"},
        "tool_response": {"taskId": "stale-review-task-id"},
    })
    stale_review_plan = work_plan.commit_plan(
        stale_review_run, macro_stage="S2",
        objective="exercise stale returned-result settlement",
        mode="PARALLEL_AGENTS",
        reason="two local Hunters create an equal-digest ambiguity challenge",
        exit_gate="exact returned result receives Reviewer disposition",
        lanes=[{
            "id": "L-STALE-HUNTER", "role": "web-hunter", "front": "F-001",
            "effect": "local_read", "assets": [], "dependencies": [],
            "expected_evidence": "one frozen local result",
            "expected_information_gain": "medium",
            "stop_condition": "one attributable result returns",
            "request_cost": 0, "request_budget": 0, "merge_cost": 5,
            "atomic": False,
        }, {
            "id": "L-STALE-DECOY", "role": "web-hunter", "front": "F-001",
            "effect": "local_read", "assets": [], "dependencies": [],
            "expected_evidence": "one equal-content but separately bound result",
            "expected_information_gain": "medium",
            "stop_condition": "one separately attributable result returns",
            "request_cost": 0, "request_budget": 0, "merge_cost": 5,
            "atomic": False,
        }, {
            "id": "L-STALE-REVIEW", "role": "review", "front": "F-001",
            "effect": "local_verify", "assets": [],
            "dependencies": ["L-STALE-HUNTER"],
            "expected_evidence": "digest-bound result challenge",
            "expected_information_gain": "medium",
            "stop_condition": "exact result receives disposition",
            "request_cost": 0, "request_budget": 0, "merge_cost": 5,
            "atomic": False,
        }, {
            "id": "L-STALE-DECOY-REVIEW", "role": "review", "front": "F-001",
            "effect": "local_verify", "assets": [],
            "dependencies": ["L-STALE-DECOY"],
            "expected_evidence": "digest-bound decoy result challenge",
            "expected_information_gain": "medium",
            "stop_condition": "decoy result receives its own disposition",
            "request_cost": 0, "request_budget": 0, "merge_cost": 5,
            "atomic": False,
        }], contract=stale_review_contract,
    )
    stale_hunter_batch = workers.delegate_ready_lanes(
        stale_review_run, runtime_slots=2, request_budget=0,
        model_egress_budget=0, merge_capacity=10, limit=2)
    stale_hunter_prompt = stale_hunter_batch["assignments"][0]["launch_prompt"]
    for stale_index, stale_hunter in enumerate(
            stale_hunter_batch["assignments"], start=1):
        stale_tool = f"stale-hunter-tool-{stale_index}"
        stale_child = f"stale-hunter-child-{stale_index}"
        stale_prompt = stale_hunter["launch_prompt"]
        stale_type = stale_hunter["subagent_type"]
        with stale_review_transcript.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps({
                "message": {"role": "assistant", "content": [{
                    "type": "tool_use", "id": stale_tool, "name": "Agent",
                    "input": {
                        "prompt": stale_prompt,
                        "subagent_type": stale_type,
                    },
                }]},
            }) + "\n")
        runtime_receipts.append_hook_event(stale_review_run, {
            "hook_event_name": "SubagentStart",
            "session_id": stale_review_contract["session_id"],
            "transcript_path": str(stale_review_transcript),
            "agent_id": stale_child, "agent_type": stale_type,
        })
        runtime_receipts.append_hook_event(stale_review_run, {
            "hook_event_name": "SubagentStop",
            "session_id": stale_review_contract["session_id"],
            "transcript_path": str(stale_review_transcript),
            "agent_id": stale_child, "agent_type": stale_type,
            "last_assistant_message": "STALE HUNTER FULL RESULT",
        })
        with stale_review_transcript.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps({
                "message": {"content": [{
                    "type": "tool_result", "tool_use_id": stale_tool,
                    "content": [{
                        "type": "text", "text": "STALE HUNTER FULL RESULT"}],
                }]},
            }) + "\n")
        runtime_receipts.append_hook_event(stale_review_run, {
            "hook_event_name": "PostToolUse",
            "session_id": stale_review_contract["session_id"],
            "transcript_path": str(stale_review_transcript),
            "tool_name": "Agent", "tool_use_id": stale_tool,
            "tool_input": {
                "prompt": stale_prompt,
                "subagent_type": stale_type,
            },
            "tool_response": [{
                "type": "text", "text": "STALE HUNTER FULL RESULT"}],
        })
    (stale_review_run / "hints.md").write_text(
        "# Hints\n\n- New steering applies only after this result is reviewed.\n",
        encoding="utf-8")
    stale_reviewer_batch = workers.delegate_ready_lanes(
        stale_review_run, runtime_slots=1, request_budget=0,
        model_egress_budget=0, merge_capacity=10, limit=1)
    stale_reviewer_prompt = stale_reviewer_batch["assignments"][0]["launch_prompt"]
    stale_reviewer_type = stale_reviewer_batch["assignments"][0]["subagent_type"]
    stale_hunter_type = stale_hunter_batch["assignments"][0]["subagent_type"]
    stale_reviewer_pretool_allowed = evaluate_pretool(
        stale_review_run,
        {"tool_name": "Agent", "tool_input": {
            "prompt": stale_reviewer_prompt,
            "subagent_type": stale_reviewer_type,
        }},
        stale_review_contract,
    ) == ""
    stale_old_execution_pretool_blocked = E_WORK_PLAN_STALE in evaluate_pretool(
        stale_review_run,
        {"tool_name": "Agent", "tool_input": {
            "prompt": stale_hunter_prompt,
            "subagent_type": stale_hunter_type,
        }},
        stale_review_contract,
    )
    stale_reviewer_without_digest_blocked = bool(evaluate_pretool(
        stale_review_run,
        {"tool_name": "Agent", "tool_input": {
            "prompt": re.sub(
                r"\s+XUNJI_RESULT_DIGEST=[0-9a-f]{64}", "",
                stale_reviewer_prompt),
            "subagent_type": stale_reviewer_type,
        }},
        stale_review_contract,
    ))
    stale_reviewer_without_marker_blocked = bool(evaluate_pretool(
        stale_review_run,
        {"tool_name": "Agent", "tool_input": {
            "prompt": re.sub(
                r"\s+XUNJI_COMPLETION_REVIEW\b", "", stale_reviewer_prompt),
            "subagent_type": stale_reviewer_type,
        }},
        stale_review_contract,
    ))
    stale_reviewer_appended_context_blocked = bool(evaluate_pretool(
        stale_review_run,
        {"tool_name": "Agent", "tool_input": {
            "prompt": stale_reviewer_prompt + "\nAdditional reviewer context",
            "subagent_type": stale_reviewer_type,
        }},
        stale_review_contract,
    ))
    stale_projection = run_model.plan_cycle_projection(
        stale_review_run, plan=stale_review_plan)
    stale_returned_states = [
        item for item in stale_projection.get("lane_states", [])
        if isinstance(item, dict)
        and item.get("lane_id") in {"L-STALE-HUNTER", "L-STALE-DECOY"}
        and item.get("runtime_state") == "returned"
    ]
    stale_equal_digest_decoy_exists = bool(
        len(stale_returned_states) == 2
        and len({str(item.get("assignment") or "")
                 for item in stale_returned_states}) == 2
        and len({str(item.get("result_digest") or "")
                 for item in stale_returned_states}) == 1
        and re.fullmatch(
            r"[0-9a-f]{64}",
            str(stale_returned_states[0].get("result_digest") or ""))
    )
    stale_assignment_path = stale_review_run / "state" / "assignments.json"
    stale_assignments_before_confusion = json.loads(
        stale_assignment_path.read_text(encoding="utf-8", errors="strict"))
    stale_assignments_confused = json.loads(json.dumps(
        stale_assignments_before_confusion))
    stale_reviewer_assignment = stale_reviewer_batch["assignments"][0][
        "assignment"]
    stale_target_assignment = stale_hunter_batch["assignments"][0]["assignment"]
    stale_decoy_assignment = stale_hunter_batch["assignments"][1]["assignment"]
    for stale_row in stale_assignments_confused.get("assignments", []):
        if isinstance(stale_row, dict) \
                and stale_row.get("agent") == stale_reviewer_assignment:
            stale_row["reviews_assignments"] = [stale_decoy_assignment]
    _atomic_json(stale_assignment_path, stale_assignments_confused)
    stale_reviewer_wrong_equal_digest_assignment_blocked = bool(
        evaluate_pretool(
            stale_review_run,
            {"tool_name": "Agent", "tool_input": {
                "prompt": stale_reviewer_prompt,
                "subagent_type": stale_reviewer_type,
            }},
            stale_review_contract,
        )
    )
    _atomic_json(stale_assignment_path, stale_assignments_before_confusion)
    stale_reviewer_exact_target_frozen = bool(
        stale_target_assignment != stale_decoy_assignment
        and any(
            isinstance(item, dict)
            and item.get("agent") == stale_reviewer_assignment
            and item.get("reviews_assignments") == [stale_target_assignment]
            for item in stale_assignments_before_confusion.get(
                "assignments", [])
        )
    )

    # ROOT_DIRECT is an exact hook-owned claim, not a prose shortcut.  Exercise
    # the real PreToolUse -> runtime claim -> PostToolUse -> typed cycle_end
    # path, including same-effect capability substitution, hook replay, and a
    # second-action attempt.
    direct_run = root / "root_direct_cycle"
    (direct_run / "state").mkdir(parents=True)
    (direct_run / "agents").mkdir()
    (direct_run / "target.md").write_text(
        "# Target\n- Authorized scope: direct.example.test\n", encoding="utf-8")
    (direct_run / "coverage.json").write_text(json.dumps({
        "assets": [{
            "host": "direct.example.test", "reachable": True, "examined": False,
        }],
    }), encoding="utf-8")
    (direct_run / "frontier.md").write_text(
        "# Frontier\n\n## Open Fronts\n\n### F-001 — local verification\n"
        "- Status: open\n- Barrier class: local-state\n- Current depth: shallow\n",
        encoding="utf-8",
    )
    (direct_run / "state" / "assignments.json").write_text(
        json.dumps({"schema": 3, "assignments": []}), encoding="utf-8")
    direct_contract = {
        "schema": SCHEMA,
        "mode": EXECUTE,
        "session_id": "root-direct-session",
        "prompt_sha256": "d" * 64,
        "prompt_excerpt": "continue the existing explicit loop",
        "updated_at": time.time() - 0.01,
        "loop_requested": True,
        "origin_run": direct_run.name,
        "bound_run": direct_run.name,
    }
    _atomic_json(contract_path(direct_run), direct_contract)
    direct_transcript = root / "root-direct-transcript.jsonl"
    direct_transcript.write_text(
        "root-direct-task\nroot-direct-action-1\nroot-direct-action-2\n",
        encoding="utf-8",
    )
    runtime_receipts.append_hook_event(direct_run, {
        "hook_event_name": "PostToolUse",
        "session_id": direct_contract["session_id"],
        "transcript_path": str(direct_transcript),
        "tool_name": "TaskCreate",
        "tool_use_id": "root-direct-task",
        "tool_input": {"subject": "one exact Root capability"},
        "tool_response": {"taskId": "root-direct-task-id"},
    })
    direct_plan = work_plan.commit_plan(
        direct_run,
        macro_stage="S1",
        objective="perform one bounded timestamp verification",
        mode="ROOT_DIRECT",
        reason="one cheap deterministic local read",
        exit_gate="exact Root action receipt reaches typed cycle_end",
        lanes=[{
            "id": "L-DIRECT-VERIFY",
            "role": "verify",
            "front": "F-001",
            "effect": "local_read",
            "capability_id": "read.timestamp-gate",
            "assets": [],
            "dependencies": [],
            "expected_evidence": "mechanical timestamp output only",
            "expected_information_gain": "low",
            "stop_condition": "one terminal tool receipt exists",
            "request_cost": 0,
            "request_budget": 0,
            "merge_cost": 1,
            "atomic": True,
        }],
        contract=direct_contract,
    )
    wrong_direct = registered_event("tools/run_model.py", str(direct_run))
    wrong_direct.update({
        "hook_event_name": "PreToolUse",
        "session_id": direct_contract["session_id"],
        "transcript_path": str(direct_transcript),
        "tool_use_id": "root-direct-wrong",
    })
    wrong_direct_reason = evaluate_pretool(
        direct_run, wrong_direct, direct_contract)
    wrong_direct_result = handle_event(wrong_direct, direct_run)
    wrong_direct_blocked = bool(
        E_DELEGATION_REQUIRED in wrong_direct_reason
        and "capability" in wrong_direct_reason
        and isinstance(wrong_direct_result, dict)
    )
    direct_pre = registered_event("tools/timestamp_gate.py", "--year")
    direct_pre.update({
        "hook_event_name": "PreToolUse",
        "session_id": direct_contract["session_id"],
        "transcript_path": str(direct_transcript),
        "tool_use_id": "root-direct-action-1",
    })
    direct_pre_allowed = handle_event(direct_pre, direct_run) is None
    direct_pre_replay_idempotent = handle_event(direct_pre, direct_run) is None
    direct_post = {
        **direct_pre,
        "hook_event_name": "PostToolUse",
        "tool_response": {"stdout": "2026", "exit_code": 0},
    }
    direct_post_recorded = handle_event(direct_post, direct_run) is None
    direct_post_replay_idempotent = handle_event(direct_post, direct_run) is None
    direct_receipt, direct_receipt_debt = runtime_receipts.root_action_receipt(
        direct_run, direct_plan)
    direct_projection = run_model.plan_cycle_projection(direct_run, plan=direct_plan)
    direct_exact_after_terminal = handle_event(direct_pre, direct_run)
    direct_exact_after_terminal_blocked = bool(
        isinstance(direct_exact_after_terminal, dict)
        and E_DELEGATION_REQUIRED in json.dumps(direct_exact_after_terminal)
        and "terminal" in json.dumps(direct_exact_after_terminal))
    direct_second = dict(direct_pre)
    direct_second["tool_use_id"] = "root-direct-action-2"
    direct_second_result = handle_event(direct_second, direct_run)
    direct_second_blocked = bool(
        isinstance(direct_second_result, dict)
        and E_DELEGATION_REQUIRED in json.dumps(direct_second_result)
        and "terminal" in json.dumps(direct_second_result)
    )
    import loop_journal as _loop_journal
    direct_cycle_end = _loop_journal.append_event(
        direct_run, "cycle_end", note="exact Root action settled",
        next_action="验证 F-001 的本地时间戳结果")
    direct_cycle_end_valid = bool(
        direct_cycle_end.get("data", {}).get("execution_mode") == "ROOT_DIRECT"
        and direct_cycle_end.get("data", {}).get("root_action_receipt")
        == direct_receipt
        and _loop_journal.plan_cycle_ended(
            _loop_journal.load_events(direct_run), direct_plan["plan_digest"])
    )
    lifecycle_codes = {
        E_NEW_RUN_SETUP_REQUIRED, E_CRON_CREATE_REQUIRED, E_ITERATION_PLAN_REQUIRED,
    }
    plan_unlocks_lifecycle_gate = not any(
        code in post_plan_agent_reason for code in lifecycle_codes)
    task_url_is_control_only = not _is_target_action(lifecycle_task)
    lifecycle_events = runtime_receipts.load_events(lifecycle_run)
    task_event_receipt = next(
        (item for item in lifecycle_events
         if item.get("tool_use_id") == "bound-task"),
        {},
    )
    task_receipt_redacted = bool(
        task_event_receipt
        and "plan-secret" not in str(task_event_receipt)
        and "redacted%3Aquery" in str(task_event_receipt.get("input_excerpt") or "")
    )
    empty_runs = root / "empty-runs"
    empty_runs.mkdir()
    env = dict(os.environ)
    env["XUNJI_RUNS_ROOT"] = str(empty_runs)
    pending_dir = root / "xunji_pending_turns"
    claims_dir = root / "xunji_transition_claims"
    env["XUNJI_PENDING_TURN_DIR"] = str(pending_dir)
    env["XUNJI_TRANSITION_CLAIMS_DIR"] = str(claims_dir)
    no_run_prompt = subprocess.run(
        [sys.executable, str(Path(__file__).resolve())],
        input=json.dumps({
            "hook_event_name": "UserPromptSubmit", "session_id": "s-bootstrap",
            "prompt": f"/loop {root / 'recon.json'} 创建新 run，slug bootstrap",
        }),
        text=True, capture_output=True, env=env, timeout=10,
    )
    pending_written = (
        no_run_prompt.returncode == 0
        and "Xunji lifecycle: SETUP_REQUIRED" in (no_run_prompt.stdout or "")
        and str(Path(sys.executable).resolve()) in (no_run_prompt.stdout or "")
        and str((ROOT / "tools" / "loop_bootstrap.py").resolve())
        in (no_run_prompt.stdout or "")
        and any(pending_dir.glob("*.json"))
    )
    normalizer_source = root / "operator-normalizer.md"
    normalizer_source.write_text(
        "- Target: https://normalizer.example.test/\n", encoding="utf-8")
    prepare_pending_dir = root / "normalizer-pending"
    prepare_claims_dir = root / "normalizer-claims"
    prepare_env = dict(env)
    prepare_env["XUNJI_PENDING_TURN_DIR"] = str(prepare_pending_dir)
    prepare_env["XUNJI_TRANSITION_CLAIMS_DIR"] = str(prepare_claims_dir)
    normalizer_prepare_command = (
        f"python3 {shlex.quote(str(ROOT / 'tools' / 'loop_bootstrap.py'))} "
        f"--source {shlex.quote(str(normalizer_source))} --type file "
        "--ai external --ai-provider fixture-provider --ai-model fixture-model "
        "--prepare-normalizer"
    )
    normalizer_prepare_invocation = _control_invocation(normalizer_prepare_command)
    late_external_opt_in_contract = _contract_from_event({
        "session_id": "late-external-opt-in",
        "prompt": (
            f"/loop {normalizer_source} {long_prompt_padding} --ai external"
        ),
    }, run_name=run.name)
    late_external_denial_contract = _contract_from_event({
        "session_id": "late-external-denial",
        "prompt": (
            f"/loop {normalizer_source} --ai external {long_prompt_padding} "
            "不要使用 --ai external"
        ),
    }, run_name=run.name)
    quoted_external_opt_in_contract = _contract_from_event({
        "session_id": "quoted-external-opt-in",
        "prompt": f"/loop {normalizer_source}\n> --ai external",
    }, run_name=run.name)
    full_prompt_external_authority = bool(
        normalizer_prepare_invocation
        and _lifecycle_authority_reason(
            run, normalizer_prepare_invocation,
            late_external_opt_in_contract) == ""
        and "--ai external" in _lifecycle_authority_reason(
            run, normalizer_prepare_invocation,
            late_external_denial_contract)
        and "--ai external" in _lifecycle_authority_reason(
            run, normalizer_prepare_invocation,
            quoted_external_opt_in_contract)
    )

    def no_run_hook(event: dict, *, hook_env: dict[str, str] = prepare_env) \
            -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [sys.executable, str(Path(__file__).resolve())],
            input=json.dumps(event), text=True, capture_output=True,
            env=hook_env, timeout=10,
        )

    no_active_clear = no_run_hook({
        "hook_event_name": "PreToolUse", "session_id": "clear-no-active",
        "tool_name": "Bash", "tool_input": clear_active["tool_input"],
    })
    no_active_clear_fail_closed = bool(
        E_CLEAR_ACTIVE_FORBIDDEN in (no_active_clear.stdout or "")
        and '"permissionDecision": "deny"' in (no_active_clear.stdout or "")
    )
    no_active_wrapped_clear = no_run_hook({
        "hook_event_name": "PreToolUse", "session_id": "clear-no-active-wrapped",
        "tool_name": "Bash", "tool_input": wrapped_clear_active["tool_input"],
    })
    no_active_wrapped_clear_fail_closed = bool(
        E_LIFECYCLE_EXACT_ARGV_REQUIRED
        in (no_active_wrapped_clear.stdout or "")
        and '"permissionDecision": "deny"'
        in (no_active_wrapped_clear.stdout or "")
    )

    shape_pending_dir = root / "shape-pending"
    shape_claims_dir = root / "shape-claims"
    shape_env = dict(env)
    shape_env["XUNJI_PENDING_TURN_DIR"] = str(shape_pending_dir)
    shape_env["XUNJI_TRANSITION_CLAIMS_DIR"] = str(shape_claims_dir)
    shape_submit = no_run_hook({
        "hook_event_name": "UserPromptSubmit", "session_id": "shape-no-active",
        "prompt": f"/loop {source_url} 创建新 run",
    }, hook_env=shape_env)
    no_active_wrapped = no_run_hook({
        "hook_event_name": "PreToolUse", "session_id": "shape-no-active",
        "tool_name": "Bash", "tool_input": wrapped_source_control["tool_input"],
    }, hook_env=shape_env)
    no_active_shape_denied_without_claim = bool(
        shape_submit.returncode == 0
        and E_LIFECYCLE_EXACT_ARGV_REQUIRED in (no_active_wrapped.stdout or "")
        and str(Path(sys.executable).resolve()) in (no_active_wrapped.stdout or "")
        and not list(shape_claims_dir.glob("*.json"))
    )
    no_active_clean = no_run_hook({
        "hook_event_name": "PreToolUse", "session_id": "shape-no-active",
        "tool_name": "Bash", "tool_input": source_control["tool_input"],
    }, hook_env=shape_env)
    same_turn_clean_retry_claims = bool(
        not (no_active_clean.stdout or "").strip()
        and list(shape_claims_dir.glob("*.json"))
    )
    missing_metadata_pending_dir = root / "missing-metadata-pending"
    missing_metadata_claims_dir = root / "missing-metadata-claims"
    missing_metadata_env = dict(env)
    missing_metadata_env["XUNJI_PENDING_TURN_DIR"] = str(
        missing_metadata_pending_dir)
    missing_metadata_env["XUNJI_TRANSITION_CLAIMS_DIR"] = str(
        missing_metadata_claims_dir)
    missing_metadata_transcript = str(
        root / "missing-metadata-transcript.jsonl")
    missing_metadata_submit = no_run_hook({
        "hook_event_name": "UserPromptSubmit",
        "transcript_path": missing_metadata_transcript,
        "prompt": f"  /loop {source_url} 创建新 run",
    }, hook_env=missing_metadata_env)
    missing_metadata_pretool = no_run_hook({
        "hook_event_name": "PreToolUse",
        "transcript_path": missing_metadata_transcript,
        "tool_name": "Bash",
        "tool_input": source_control["tool_input"],
    }, hook_env=missing_metadata_env)
    missing_metadata_pending = [
        json.loads(path.read_text(encoding="utf-8"))
        for path in missing_metadata_pending_dir.glob("*.json")
    ] if missing_metadata_pending_dir.is_dir() else []
    missing_metadata_claims = list(
        missing_metadata_claims_dir.glob("*.json")) \
        if missing_metadata_claims_dir.is_dir() else []
    missing_session_hook_pipeline_recovers_intent = bool(
        missing_metadata_submit.returncode == 0
        and "operator intent: NORMALIZED" in (
            missing_metadata_submit.stdout or "")
        and len(missing_metadata_pending) == 1
        and missing_metadata_pending[0].get("session_binding_kind")
        == "transcript_path"
        and not (missing_metadata_pretool.stdout or "").strip()
        and len(missing_metadata_claims) == 1
    )
    singleton_pending_dir = root / "singleton-metadata-pending"
    singleton_claims_dir = root / "singleton-metadata-claims"
    singleton_env = dict(env)
    singleton_env["XUNJI_PENDING_TURN_DIR"] = str(singleton_pending_dir)
    singleton_env["XUNJI_TRANSITION_CLAIMS_DIR"] = str(singleton_claims_dir)
    singleton_submit = no_run_hook({
        "hook_event_name": "UserPromptSubmit",
        "prompt": f"/loop {source_url} 创建新 run",
    }, hook_env=singleton_env)
    singleton_pretool = no_run_hook({
        "hook_event_name": "PreToolUse",
        "tool_name": "Bash",
        "tool_use_id": "singleton-metadata-bootstrap",
        "tool_input": source_control["tool_input"],
    }, hook_env=singleton_env)
    singleton_pending = [
        json.loads(path.read_text(encoding="utf-8"))
        for path in singleton_pending_dir.glob("*.json")
    ] if singleton_pending_dir.is_dir() else []
    singleton_claims = [
        json.loads(path.read_text(encoding="utf-8"))
        for path in singleton_claims_dir.glob("*.json")
    ] if singleton_claims_dir.is_dir() else []
    missing_all_metadata_hook_pipeline_recovers_intent = bool(
        singleton_submit.returncode == 0
        and len(singleton_pending) == 1
        and singleton_pending[0].get("session_id")
        == SINGLE_OPERATOR_SESSION_BINDING
        and singleton_pending[0].get("session_binding_kind")
        == "single_operator"
        and not (singleton_pretool.stdout or "").strip()
        and len(singleton_claims) == 1
        and singleton_claims[0].get("session_id")
        == SINGLE_OPERATOR_SESSION_BINDING
        and singleton_claims[0].get("status") == "active"
    )
    private_api_attempt = no_run_hook({
        "hook_event_name": "PreToolUse",
        "tool_name": "Bash",
        "tool_input": {
            "command": (
                "python3 -c \"import setup_transaction; "
                "setup_transaction.create_and_activate('forged')\""
            ),
        },
    }, hook_env=missing_metadata_env)
    no_active_private_lifecycle_api_blocked = bool(
        E_LIFECYCLE_PRIVATE_API in (private_api_attempt.stdout or "")
        and '"permissionDecision": "deny"' in (
            private_api_attempt.stdout or "")
        and len(missing_metadata_claims) == 1
    )
    continue_submit = no_run_hook({
        "hook_event_name": "UserPromptSubmit", "session_id": "shape-no-active",
        "prompt": "继续",
    }, hook_env=shape_env)
    after_continue_retry = no_run_hook({
        "hook_event_name": "PreToolUse", "session_id": "shape-no-active",
        "tool_name": "Bash", "tool_input": source_control["tool_input"],
    }, hook_env=shape_env)
    shape_tombstones = [
        json.loads(path.read_text(encoding="utf-8"))
        for path in shape_claims_dir.glob("*.json")
    ] if shape_claims_dir.is_dir() else []
    bare_continue_revokes_transition_authority = bool(
        continue_submit.returncode == 0
        and not list(shape_pending_dir.glob("*.json"))
        and len(shape_tombstones) == 1
        and shape_tombstones[0].get("status") == "revoked"
        and '"permissionDecision": "deny"' in (after_continue_retry.stdout or "")
        and E_RUN_TRANSITION_AUTHORITY_MISSING in (
            after_continue_retry.stdout or "")
    )

    interleave_pending_dir = root / "interleave-pending"
    interleave_claims_dir = root / "interleave-claims"
    interleave_session = "active-pointer-interleave"
    interleave_contract = write_pending_contract({
        "session_id": interleave_session,
        "prompt": f"/loop {source_url} 创建新 run",
    }, pending_dir=interleave_pending_dir, claims_dir=interleave_claims_dir)
    write_transition_claim(
        "stale_interleave_20260101", interleave_contract,
        claims_dir=interleave_claims_dir,
        effect=seed_activate_effect("stale_interleave_20260101"))
    interleave_active = empty_runs / "interleave_active_20260101"
    interleave_active.mkdir()
    (interleave_active / "target.md").write_text(
        "# Interleaved active run\n", encoding="utf-8")
    interleave_pointer = root / "interleave-active-pointer"
    interleave_pointer.write_text(
        str(interleave_active.resolve()), encoding="utf-8")
    interleave_env = dict(env)
    interleave_env["XUNJI_ACTIVE_RUN_FILE"] = str(interleave_pointer)
    interleave_env["XUNJI_PENDING_TURN_DIR"] = str(interleave_pending_dir)
    interleave_env["XUNJI_TRANSITION_CLAIMS_DIR"] = str(interleave_claims_dir)
    interleave_submit = subprocess.run(
        [sys.executable, str(Path(__file__).resolve())],
        input=json.dumps({
            "hook_event_name": "UserPromptSubmit",
            "session_id": interleave_session,
            "prompt": "当前 active run 状态是什么？",
        }),
        text=True, capture_output=True, env=interleave_env, timeout=10,
    )
    try:
        claim_pending_contract(
            root / "stale_interleave_20260101",
            pending_dir=interleave_pending_dir,
            claims_dir=interleave_claims_dir,
        )
        interleaved_old_claim_unclaimable = False
    except RuntimeError as exc:
        interleaved_old_claim_unclaimable = "revoked" in str(exc)
    interleave_tombstones = [
        json.loads(path.read_text(encoding="utf-8"))
        for path in interleave_claims_dir.glob("*.json")
    ] if interleave_claims_dir.is_dir() else []
    persistent_pointer_captures_new_prompt = bool(
        interleave_submit.returncode == 0
        and not list(interleave_pending_dir.glob("*.json"))
        and len(interleave_tombstones) == 1
        and interleave_tombstones[0].get("status") == "revoked"
        and interleaved_old_claim_unclaimable
        and load_contract(
            interleave_active, session_id=interleave_session
        ).get("mode") == EXPLAIN
        and "NOT_BOUND" not in (interleave_submit.stdout or "")
    )

    foreign_active = empty_runs / "foreign_session_active_20260101"
    (foreign_active / "state").mkdir(parents=True)
    (foreign_active / "target.md").write_text(
        "# Foreign session run\n", encoding="utf-8")
    foreign_owner = "foreign-pointer-owner"
    foreign_contract = write_contract(foreign_active, {
        "session_id": foreign_owner,
        "transcript_path": str(root / "foreign-owner.jsonl"),
        "prompt": f"/loop runs/{foreign_active.name}",
    })
    foreign_pointer = root / "foreign-active-pointer"
    foreign_pointer.write_text(
        str(foreign_active.resolve()) + "\n", encoding="utf-8")
    foreign_env = dict(env)
    foreign_env["XUNJI_ACTIVE_RUN_FILE"] = str(foreign_pointer)
    foreign_env["XUNJI_PENDING_TURN_DIR"] = str(root / "foreign-pending")
    foreign_env["XUNJI_TRANSITION_CLAIMS_DIR"] = str(root / "foreign-claims")
    foreign_before = contract_path(foreign_active).read_bytes()
    foreign_ordinary = subprocess.run(
        [sys.executable, str(Path(__file__).resolve())],
        input=json.dumps({
            "hook_event_name": "UserPromptSubmit",
            "session_id": "ordinary-startup-session",
            "transcript_path": str(root / "ordinary-startup.jsonl"),
            "prompt": "继续修复 Xunji 本地代码",
        }),
        text=True, capture_output=True, env=foreign_env, timeout=10,
    )
    foreign_pointer_is_personal_global_selection = bool(
        foreign_ordinary.returncode == 0
        and "NOT_BOUND" not in (foreign_ordinary.stdout or "")
        and contract_path(foreign_active).read_bytes() != foreign_before
        and load_contract(
            foreign_active, session_id="ordinary-startup-session"
        ).get("mode") == MAINTENANCE
    )
    foreign_explicit = subprocess.run(
        [sys.executable, str(Path(__file__).resolve())],
        input=json.dumps({
            "hook_event_name": "UserPromptSubmit",
            "session_id": "explicit-rebind-session",
            "transcript_path": str(root / "explicit-rebind.jsonl"),
            "prompt": f"/loop runs/{foreign_active.name}",
        }),
        text=True, capture_output=True, env=foreign_env, timeout=10,
    )
    explicit_prompt_can_rebind_foreign_pointer = bool(
        foreign_explicit.returncode == 0
        and load_contract(
            foreign_active, session_id="explicit-rebind-session"
        ).get("mode") == EXECUTE
    )

    isolation_pending_dir = root / "authority-isolation-pending"
    isolation_claims_dir = root / "authority-isolation-claims"
    isolation_a = write_pending_contract({
        "session_id": "isolation-a",
        "prompt": f"/loop {source_url} 创建新 run isolation-a",
    }, pending_dir=isolation_pending_dir, claims_dir=isolation_claims_dir)
    isolation_b = write_pending_contract({
        "session_id": "isolation-b",
        "prompt": f"/loop {source_url} 创建新 run isolation-b",
    }, pending_dir=isolation_pending_dir, claims_dir=isolation_claims_dir)
    write_transition_claim(
        "isolation_a_20260101", isolation_a, claims_dir=isolation_claims_dir,
        effect=seed_activate_effect("isolation_a_20260101"))
    write_transition_claim(
        "isolation_b_20260101", isolation_b, claims_dir=isolation_claims_dir,
        effect=seed_activate_effect("isolation_b_20260101"))
    isolation_env = dict(env)
    isolation_env["XUNJI_PENDING_TURN_DIR"] = str(isolation_pending_dir)
    isolation_env["XUNJI_TRANSITION_CLAIMS_DIR"] = str(isolation_claims_dir)
    internal_isolation_submit = no_run_hook({
        "hook_event_name": "UserPromptSubmit",
        "session_id": "isolation-a",
        "prompt": "<task-notification id=\"done\">internal</task-notification>",
    }, hook_env=isolation_env)
    internal_prompt_preserves_pending_authority = bool(
        internal_isolation_submit.returncode == 0
        and _pending_path("isolation-a", isolation_pending_dir).exists()
        and _transition_claim_path(
            "isolation_a_20260101", "isolation-a",
            seed_activate_effect("isolation_a_20260101"),
            str(isolation_a.get("prompt_sha256") or ""), isolation_claims_dir).exists()
        and _pending_path("isolation-b", isolation_pending_dir).exists()
        and _transition_claim_path(
            "isolation_b_20260101", "isolation-b",
            seed_activate_effect("isolation_b_20260101"),
            str(isolation_b.get("prompt_sha256") or ""), isolation_claims_dir).exists()
    )
    session_a_replacement = no_run_hook({
        "hook_event_name": "UserPromptSubmit",
        "session_id": "isolation-a",
        "prompt": "当前状态是什么？",
    }, hook_env=isolation_env)
    prompt_revocation_is_session_scoped = bool(
        session_a_replacement.returncode == 0
        and not _pending_path("isolation-a", isolation_pending_dir).exists()
        and json.loads(_transition_claim_path(
            "isolation_a_20260101", "isolation-a",
            seed_activate_effect("isolation_a_20260101"),
            str(isolation_a.get("prompt_sha256") or ""), isolation_claims_dir
        ).read_text(encoding="utf-8")).get("status") == "revoked"
        and _pending_path("isolation-b", isolation_pending_dir).exists()
        and json.loads(_transition_claim_path(
            "isolation_b_20260101", "isolation-b",
            seed_activate_effect("isolation_b_20260101"),
            str(isolation_b.get("prompt_sha256") or ""), isolation_claims_dir
        ).read_text(encoding="utf-8")).get("status") == "active"
    )

    overwrite_run = root / "active-contract-overwrite"
    (overwrite_run / "state").mkdir(parents=True)
    (overwrite_run / "target.md").write_text(
        "# Active contract overwrite\n", encoding="utf-8")
    overwrite_pending = root / "overwrite-pending"
    overwrite_claims = root / "overwrite-claims"
    old_active_contract = write_contract(overwrite_run, {
        "session_id": "old-active-session",
        "prompt": f"/loop {source_url} 创建新 run",
    })
    old_active_target = "old_active_target_20260101"
    old_active_effect = seed_activate_effect(old_active_target)
    write_transition_claim(
        old_active_target, old_active_contract,
        claims_dir=overwrite_claims, origin_run=overwrite_run.name,
        effect=old_active_effect)
    unrelated_pending_contract = write_pending_contract({
        "session_id": "unrelated-pending-session",
        "prompt": "创建一个新 run unrelated",
    }, pending_dir=overwrite_pending, claims_dir=overwrite_claims)
    unrelated_pending_target = "unrelated_pending_20260101"
    unrelated_pending_effect = seed_activate_effect(unrelated_pending_target)
    write_transition_claim(
        unrelated_pending_target, unrelated_pending_contract,
        claims_dir=overwrite_claims, effect=unrelated_pending_effect)
    overwrite_pointer = root / "overwrite-active-pointer"
    overwrite_pointer.write_text(str(overwrite_run), encoding="utf-8")
    with mock.patch.object(sys.modules[__name__], "ACTIVE_RUN_POINTER", overwrite_pointer), \
            mock.patch.object(sys.modules[__name__], "PENDING_DIR", overwrite_pending), \
            mock.patch.object(
                sys.modules[__name__], "TRANSITION_CLAIMS_DIR", overwrite_claims):
        handle_event({
            "hook_event_name": "UserPromptSubmit",
            "session_id": "new-active-session",
            "prompt": "当前 active run 状态是什么？",
        }, run_dir=overwrite_run)
    old_active_claim_path = _transition_claim_path(
        old_active_target, "old-active-session", old_active_effect,
        str(old_active_contract.get("prompt_sha256") or ""), overwrite_claims)
    unrelated_pending_claim_path = _transition_claim_path(
        unrelated_pending_target, "unrelated-pending-session",
        unrelated_pending_effect,
        str(unrelated_pending_contract.get("prompt_sha256") or ""),
        overwrite_claims)
    active_contract_overwrite_revokes_old_session_claims = bool(
        json.loads(old_active_claim_path.read_text(
            encoding="utf-8")).get("status") == "revoked"
        and json.loads(unrelated_pending_claim_path.read_text(
            encoding="utf-8")).get("status") == "active"
        and _pending_path(
            "unrelated-pending-session", overwrite_pending).exists()
        and load_contract(
            overwrite_run, session_id="new-active-session").get("mode") == EXPLAIN
    )

    missing_session_run = root / "missing-session-overwrite"
    (missing_session_run / "state").mkdir(parents=True)
    (missing_session_run / "target.md").write_text(
        "# Missing session overwrite\n", encoding="utf-8")
    missing_session_claims = root / "missing-session-claims"
    missing_session_contract = write_contract(missing_session_run, {
        "session_id": "displaced-by-missing-session",
        "prompt": f"/loop {source_url} 创建新 run",
    })
    missing_session_target = "missing_session_target_20260101"
    missing_session_effect = seed_activate_effect(missing_session_target)
    write_transition_claim(
        missing_session_target, missing_session_contract,
        claims_dir=missing_session_claims, origin_run=missing_session_run.name,
        effect=missing_session_effect)
    missing_session_pointer = root / "missing-session-active-pointer"
    missing_session_pointer.write_text(str(missing_session_run), encoding="utf-8")
    with mock.patch.object(
            sys.modules[__name__], "ACTIVE_RUN_POINTER", missing_session_pointer), \
            mock.patch.object(
                sys.modules[__name__], "TRANSITION_CLAIMS_DIR", missing_session_claims):
        handle_event({
            "hook_event_name": "UserPromptSubmit",
            "session_id": "",
            "prompt": "当前 active run 状态是什么？",
        }, run_dir=missing_session_run)
    missing_session_claim_path = _transition_claim_path(
        missing_session_target, "displaced-by-missing-session",
        missing_session_effect,
        str(missing_session_contract.get("prompt_sha256") or ""),
        missing_session_claims)
    missing_session_overwrite_revokes_old_claim = bool(
        json.loads(missing_session_claim_path.read_text(
            encoding="utf-8")).get("status") == "revoked"
        and load_contract(missing_session_run).get("mode") == EXPLAIN
    )

    unbound_prepare = no_run_hook({
        "hook_event_name": "PreToolUse", "session_id": "prepare-unbound",
        "tool_name": "Bash", "tool_input": {"command": normalizer_prepare_command},
    })
    unbound_normalizer_prepare_blocked = (
        '"permissionDecision": "deny"' in (unbound_prepare.stdout or "")
        and "operator bootstrap contract" in (unbound_prepare.stdout or "")
    )
    no_external_submit = no_run_hook({
        "hook_event_name": "UserPromptSubmit", "session_id": "prepare-no-external",
        "prompt": f"/loop {normalizer_source}",
    })
    no_external_prepare = no_run_hook({
        "hook_event_name": "PreToolUse", "session_id": "prepare-no-external",
        "tool_name": "Bash", "tool_input": {"command": normalizer_prepare_command},
    })
    implicit_external_prepare_blocked = (
        no_external_submit.returncode == 0
        and '"permissionDecision": "deny"' in (no_external_prepare.stdout or "")
        and "--ai external" in (no_external_prepare.stdout or "")
    )
    explicit_external_submit = no_run_hook({
        "hook_event_name": "UserPromptSubmit", "session_id": "prepare-external",
        "prompt": f"/loop {normalizer_source} --ai external",
    })
    claims_before_prepare = list(prepare_claims_dir.glob("*.json")) \
        if prepare_claims_dir.exists() else []
    explicit_external_prepare = no_run_hook({
        "hook_event_name": "PreToolUse", "session_id": "prepare-external",
        "tool_name": "Bash", "tool_input": {"command": normalizer_prepare_command},
    })
    claims_after_prepare = list(prepare_claims_dir.glob("*.json")) \
        if prepare_claims_dir.exists() else []
    explicit_external_prepare_allowed_without_claim = (
        explicit_external_submit.returncode == 0
        and not (explicit_external_prepare.stdout or "").strip()
        and claims_before_prepare == claims_after_prepare == []
    )
    exact_setup_command = (
        f"{shlex.quote(str(Path(sys.executable).resolve()))} "
        f"{shlex.quote(str((ROOT / 'tools' / 'setup_run.py').resolve()))} "
        f"bootstrap {shlex.quote(str(root / 'recon.json'))} "
        "--date 20260101"
    )
    exact_setup_invocation = _control_invocation(exact_setup_command)
    expected_setup_effect = _lifecycle_transition_effect(
        exact_setup_invocation, "bootstrap_20260101")
    no_run_setup = subprocess.run(
        [sys.executable, str(Path(__file__).resolve())],
        input=json.dumps({
            "hook_event_name": "PreToolUse", "session_id": "s-bootstrap",
            "tool_name": "Bash", "tool_input": {
                "command": exact_setup_command},
        }),
        text=True, capture_output=True, env=env, timeout=10,
    )
    setup_claim_paths = sorted(claims_dir.glob("*.json"))
    setup_claim = json.loads(setup_claim_paths[0].read_text(
        encoding="utf-8")) if len(setup_claim_paths) == 1 else {}
    setup_pending = load_pending_contract(
        "s-bootstrap", pending_dir=pending_dir)
    pending_setup_allowed = (
        no_run_setup.returncode == 0 and not (no_run_setup.stdout or "").strip()
        and len(setup_claim_paths) == 1
        and setup_claim.get("status") == "active"
        and setup_claim.get("session_id") == "s-bootstrap"
        and setup_claim.get("target_run") == "bootstrap_20260101"
        and setup_claim.get("origin_run") == ""
        and setup_claim.get("prompt_sha256")
        == setup_pending.get("prompt_sha256")
        and setup_claim.get("effect") == expected_setup_effect
        and str(root / "recon.json") not in json.dumps(
            setup_claim, ensure_ascii=False)
        and _pending_path("s-bootstrap", pending_dir).exists()
    )

    bare_pending_dir = root / "bare-python-pending"
    bare_claims_dir = root / "bare-python-claims"
    bare_session = "bare-python-bootstrap"
    bare_command = (
        f"python3 {shlex.quote(str((ROOT / 'tools' / 'setup_run.py').resolve()))} "
        f"bare-python {shlex.quote(str(root / 'recon.json'))} --date 20260101"
    )
    fake_python_dir = root / "fake-python-path"
    fake_python_dir.mkdir()
    fake_python = fake_python_dir / "python3"
    fake_python.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    fake_python.chmod(0o755)
    bare_env = dict(env)
    bare_env["XUNJI_PENDING_TURN_DIR"] = str(bare_pending_dir)
    bare_env["XUNJI_TRANSITION_CLAIMS_DIR"] = str(bare_claims_dir)
    bare_env["PATH"] = str(fake_python_dir)
    bare_submit = no_run_hook({
        "hook_event_name": "UserPromptSubmit", "session_id": bare_session,
        "prompt": f"/loop {root / 'recon.json'} 创建新 run，slug bare-python",
    }, hook_env=bare_env)
    bare_before = load_pending_contract(
        bare_session, pending_dir=bare_pending_dir)
    unrecognized_bare_command = bare_command.replace("python3 ", "python3.99 ", 1)
    bare_mismatch = no_run_hook({
        "hook_event_name": "PreToolUse", "session_id": bare_session,
        "tool_name": "Bash", "tool_input": {"command": unrecognized_bare_command},
    }, hook_env=bare_env)
    bare_after_mismatch = load_pending_contract(
        bare_session, pending_dir=bare_pending_dir)
    unrecognized_bare_python_fails_closed = bool(
        bare_submit.returncode == 0
        and bare_before.get("prompt_sha256")
        and bare_after_mismatch.get("prompt_sha256")
        == bare_before.get("prompt_sha256")
        and '"permissionDecision": "deny"' in (bare_mismatch.stdout or "")
        and not list(bare_claims_dir.glob("*.json"))
    )
    alias_python_dir = root / "trusted-python-path"
    alias_python_dir.mkdir()
    (alias_python_dir / "python3").symlink_to(Path(sys.executable).resolve())
    bare_alias_env = dict(bare_env)
    bare_alias_env["PATH"] = str(alias_python_dir)
    bare_alias = no_run_hook({
        "hook_event_name": "PreToolUse", "session_id": bare_session,
        "tool_name": "Bash", "tool_input": {"command": bare_command},
    }, hook_env=bare_alias_env)
    bare_alias_claims = sorted(bare_claims_dir.glob("*.json"))
    documented_bare_python_claims_across_path_difference = bool(
        bare_alias.returncode == 0
        and not (bare_alias.stdout or "").strip()
        and len(bare_alias_claims) == 1
        and json.loads(bare_alias_claims[0].read_text(
            encoding="utf-8")).get("status") == "active"
    )
    no_run_probe = subprocess.run(
        [sys.executable, str(Path(__file__).resolve())],
        input=json.dumps({
            "hook_event_name": "PreToolUse", "session_id": "s-bootstrap",
            "tool_name": "Bash", "tool_input": {
                "command": "python3 tools/probe.py GET https://example.test"},
        }),
        text=True, capture_output=True, env=env, timeout=10,
    )
    pending_target_action_blocked = (
        '"permissionDecision": "deny"' in (no_run_probe.stdout or "")
        and "bootstrap run" in (no_run_probe.stdout or ""))
    no_run_write = subprocess.run(
        [sys.executable, str(Path(__file__).resolve())],
        input=json.dumps({
            "hook_event_name": "PreToolUse", "session_id": "s-bootstrap",
            "tool_name": "Write", "tool_input": {
                "file_path": str(ROOT / "README.md"), "content": "blocked"},
        }),
        text=True, capture_output=True, env=env, timeout=10,
    )
    pending_arbitrary_write_blocked = (
        '"permissionDecision": "deny"' in (no_run_write.stdout or "")
        and "bootstrap run" in (no_run_write.stdout or ""))

    # Authority persistence must expose one stable durability error even when
    # failure happens before a temporary file exists.  These are deliberately
    # direct fault fixtures for the initialization and file/directory barriers.
    authority_fault_root = root / "authority-write-faults"
    authority_fault_path = authority_fault_root / "claim.json"
    with mock.patch.object(
            Path, "mkdir", side_effect=OSError("injected authority mkdir")):
        try:
            _atomic_json(authority_fault_path, {"state": "active"}, durable=True)
            authority_mkdir_fault_mapped = False
        except TransitionDurabilityError:
            authority_mkdir_fault_mapped = True
    authority_fault_root.mkdir()
    with mock.patch.object(
            tempfile, "mkstemp",
            side_effect=OSError("injected authority mkstemp")):
        try:
            _atomic_json(authority_fault_path, {"state": "active"}, durable=True)
            authority_mkstemp_fault_mapped = False
        except TransitionDurabilityError:
            authority_mkstemp_fault_mapped = True
    with mock.patch.object(
            os, "fsync", side_effect=OSError("injected authority file fsync")):
        try:
            _atomic_json(authority_fault_path, {"state": "active"}, durable=True)
            authority_file_fsync_fault_mapped = False
        except TransitionDurabilityError:
            authority_file_fsync_fault_mapped = True
    with mock.patch.object(
            sys.modules[__name__], "_fsync_directory",
            side_effect=TransitionDurabilityError(
                "injected authority directory fsync")):
        try:
            _atomic_json(authority_fault_path, {"state": "active"}, durable=True)
            authority_dir_fsync_fault_mapped = False
        except TransitionDurabilityError:
            authority_dir_fsync_fault_mapped = authority_fault_path.exists()

    no_run_unbound_set = subprocess.run(
        [sys.executable, str(Path(__file__).resolve())],
        input=json.dumps({
            "hook_event_name": "PreToolUse", "session_id": "s-no-contract",
            "tool_name": "Bash", "tool_input": {
                "command": f"python3 {ROOT / 'tools' / 'xunji_statusline.py'} --set-active runs/ghost_20260101"},
        }),
        text=True, capture_output=True, env=env, timeout=10,
    )
    unbound_set_active_blocked = (
        '"permissionDecision": "deny"' in (no_run_unbound_set.stdout or "")
        and E_RUN_TRANSITION_AUTHORITY_MISSING in (
            no_run_unbound_set.stdout or ""))
    pending_target = root / "bootstrap_20260101"
    (pending_target / "state").mkdir(parents=True)
    claimed_pending = claim_pending_contract(
        pending_target, pending_dir=pending_dir, claims_dir=claims_dir)
    claimed_pending_path = next(claims_dir.glob("*.json"))
    claimed_pending_raw = claimed_pending_path.read_bytes()
    real_claim_replay_fsync = _fsync_directory
    claimed_replay_child_barriers = 0
    claimed_replay_owner_barriers = 0

    def fail_claimed_replay_owner_once(path: Path) -> None:
        nonlocal claimed_replay_child_barriers, claimed_replay_owner_barriers
        if path.resolve() == claims_dir.resolve():
            claimed_replay_child_barriers += 1
            real_claim_replay_fsync(path)
            return
        if path.resolve() == claims_dir.parent.resolve():
            claimed_replay_owner_barriers += 1
            if claimed_replay_owner_barriers == 1:
                raise TransitionDurabilityError(
                    "injected claimed-replay owner directory fsync")
        real_claim_replay_fsync(path)

    with mock.patch.object(
            sys.modules[__name__], "_fsync_directory",
            fail_claimed_replay_owner_once):
        try:
            write_transition_claim(
                pending_target.name,
                setup_pending,
                claims_dir=claims_dir,
                effect=expected_setup_effect,
            )
            claimed_replay_owner_faulted = False
        except TransitionDurabilityError:
            claimed_replay_owner_faulted = True
        replayed_claim = write_transition_claim(
            pending_target.name,
            setup_pending,
            claims_dir=claims_dir,
            effect=expected_setup_effect,
        )
    claimed_replay_is_byte_stable = bool(
        claimed_replay_owner_faulted
        and claimed_replay_child_barriers == 2
        and claimed_replay_owner_barriers == 2
        and replayed_claim.get("status") == "claimed"
        and replayed_claim.get("claim_binding")
        == claimed_pending.get("transition_claim")
        and claimed_pending_path.read_bytes() == claimed_pending_raw
    )
    pending_claim_status = replayed_claim.get("status")
    pending_claim_finalized = finalize_transition_claim(
        pending_target, claimed_pending,
        pending_dir=pending_dir, claims_dir=claims_dir)
    pending_claimed_into_run = (
        claimed_pending.get("session_id") == "s-bootstrap"
        and load_contract(pending_target, session_id="s-bootstrap").get("bound_run")
        == pending_target.name
        and pending_claim_status == "claimed"
        and pending_claim_finalized
        and not any(pending_dir.glob("*.json"))
        and not any(claims_dir.glob("*.json"))
    )
    ambiguous_dir = root / "ambiguous-pending"
    write_pending_contract({
        "session_id": "ambiguous-a", "prompt": "创建一个新 run alpha",
    }, pending_dir=ambiguous_dir)
    write_pending_contract({
        "session_id": "ambiguous-b", "prompt": "创建一个新 run beta",
    }, pending_dir=ambiguous_dir)
    ambiguous_target = root / "neutral_20260101"
    (ambiguous_target / "state").mkdir(parents=True)
    try:
        claim_pending_contract(
            ambiguous_target, pending_dir=ambiguous_dir,
            claims_dir=root / "ambiguous-claims")
        ambiguous_pending_rejected = False
    except RuntimeError:
        ambiguous_pending_rejected = True
    exact_dir = root / "exact-pending"
    exact_claims = root / "exact-claims"
    exact_a = write_pending_contract({
        "session_id": "exact-a", "prompt": "创建一个新 run",
    }, pending_dir=exact_dir)
    write_pending_contract({
        "session_id": "exact-b", "prompt": "创建另一个新 run",
    }, pending_dir=exact_dir)
    exact_target = root / "exact_20260101"
    (exact_target / "state").mkdir(parents=True)
    write_transition_claim(
        exact_target.name, exact_a, claims_dir=exact_claims,
        effect=seed_activate_effect(exact_target.name))
    exact_txid = "a" * 32
    exact_source_hash = "b" * 64
    exact_claimed = claim_pending_contract(
        exact_target, pending_dir=exact_dir, claims_dir=exact_claims,
        transaction_id=exact_txid, source_hash=exact_source_hash,
        expected_run=exact_target.name)
    exact_session_claimed = (
        exact_claimed.get("session_id") == "exact-a"
        and load_pending_contract("exact-b", pending_dir=exact_dir).get("session_id") == "exact-b"
    )
    exact_transaction_bound = exact_claimed.get("transition_transaction") == {
        "transaction_id": exact_txid,
        "source_sha256": exact_source_hash,
        "expected_run": exact_target.name,
    }
    exact_claim_finalized = finalize_transition_claim(
        exact_target, exact_claimed,
        pending_dir=exact_dir, claims_dir=exact_claims)
    exact_transaction_bound = bool(
        exact_transaction_bound
        and exact_claim_finalized
        and not _pending_path("exact-a", exact_dir).exists()
        and _pending_path("exact-b", exact_dir).exists()
        and not list(exact_claims.glob("*.json"))
    )

    durable_cleanup_pending = root / "durable-cleanup-pending"
    durable_cleanup_claims = root / "durable-cleanup-claims"
    durable_cleanup_contract = write_pending_contract({
        "session_id": "durable-cleanup",
        "prompt": "创建一个新 run durable_cleanup_20260101",
    }, pending_dir=durable_cleanup_pending)
    durable_cleanup_target = root / "durable_cleanup_20260101"
    (durable_cleanup_target / "state").mkdir(parents=True)
    durable_cleanup_effect = seed_activate_effect(
        durable_cleanup_target.name)
    write_transition_claim(
        durable_cleanup_target.name,
        durable_cleanup_contract,
        claims_dir=durable_cleanup_claims,
        effect=durable_cleanup_effect,
    )
    durable_cleanup_bound = claim_pending_contract(
        durable_cleanup_target,
        pending_dir=durable_cleanup_pending,
        claims_dir=durable_cleanup_claims,
        effect=durable_cleanup_effect,
    )
    real_fsync_directory = _fsync_directory
    cleanup_fsync_calls = 0

    def fail_pending_cleanup_barrier(path: Path) -> None:
        nonlocal cleanup_fsync_calls
        cleanup_fsync_calls += 1
        if cleanup_fsync_calls == 2:
            raise TransitionDurabilityError(
                "injected pending deletion directory fsync")
        real_fsync_directory(path)

    with mock.patch.object(
            sys.modules[__name__], "_fsync_directory",
            fail_pending_cleanup_barrier):
        try:
            finalize_transition_claim(
                durable_cleanup_target,
                durable_cleanup_bound,
                pending_dir=durable_cleanup_pending,
                claims_dir=durable_cleanup_claims,
            )
            durable_cleanup_faulted = False
        except TransitionDurabilityError:
            durable_cleanup_faulted = True
    durable_cleanup_retry = finalize_transition_claim(
        durable_cleanup_target,
        durable_cleanup_bound,
        pending_dir=durable_cleanup_pending,
        claims_dir=durable_cleanup_claims,
    )
    durable_missing_cleanup_converges = bool(
        durable_cleanup_faulted
        and durable_cleanup_retry is False
        and not list(durable_cleanup_pending.glob("*.json"))
        and not list(durable_cleanup_claims.glob("*.json"))
    )
    race_dir = root / "race-pending"
    race_claims = root / "race-claims"
    race_a = write_pending_contract({
        "session_id": "race-a", "prompt": "创建一个新 run race",
    }, pending_dir=race_dir)
    race_b = write_pending_contract({
        "session_id": "race-b", "prompt": "创建一个新 run race",
    }, pending_dir=race_dir)
    race_target = root / "race_20260101"
    (race_target / "state").mkdir(parents=True)
    race_effect = seed_activate_effect(race_target.name)
    write_transition_claim(
        race_target.name, race_a, claims_dir=race_claims, effect=race_effect)
    write_transition_claim(
        race_target.name, race_b, claims_dir=race_claims, effect=race_effect)
    try:
        claim_pending_contract(
            race_target, pending_dir=race_dir, claims_dir=race_claims)
        same_target_race_rejected = False
    except RuntimeError:
        same_target_race_rejected = True
    unrelated_no_run_prompt = subprocess.run(
        [sys.executable, str(Path(__file__).resolve())],
        input=json.dumps({
            "hook_event_name": "UserPromptSubmit", "session_id": "s-unrelated",
            "prompt": "修复 Xunji 这段本地代码",
        }),
        text=True, capture_output=True, env=env, timeout=10,
    )
    no_run_maintenance_prompt_persisted = (
        unrelated_no_run_prompt.returncode == 0
        and "MAINTENANCE" in (unrelated_no_run_prompt.stdout or "")
        and any(pending_dir.glob("*.json"))
    )
    explicit_runs = root / "explicit-runs"
    explicit_candidate = explicit_runs / "recent_20260101"
    explicit_candidate.mkdir(parents=True)
    (explicit_candidate / "target.md").write_text("# Target\n", encoding="utf-8")
    explicit_pointer = root / "active-pointer"
    no_pointer_does_not_guess = explicit_active_run(
        explicit_runs, explicit_pointer) is None
    explicit_pointer.write_text(str(explicit_candidate), encoding="utf-8")
    explicit_pointer_selected = explicit_active_run(
        explicit_runs, explicit_pointer) == explicit_candidate.resolve()

    session_project = root / "session-end-project"
    session_runs = session_project / "runs"
    session_run = session_runs / "session_end_20260101"
    (session_run / "state").mkdir(parents=True)
    (session_run / "target.md").write_text(
        "# Session end run\n", encoding="utf-8")
    session_pointer = session_project / ".claude" / "xunji_active_run"
    session_pointer.parent.mkdir(parents=True)
    session_pending = session_project / ".claude" / "pending"
    session_claims = session_project / ".claude" / "claims"
    session_selections = session_project / ".claude" / "selections"
    owner_a = "session-end-owner-a"
    owner_b = "session-end-owner-b"

    def session_transcript(session_id: str) -> str:
        return str(session_project / f"{session_id}.jsonl")

    def select_for_session(session_id: str) -> dict:
        session_pointer.write_text(
            f"runs/{session_run.name}\n", encoding="utf-8")
        return write_contract(session_run, {
            "session_id": session_id,
            "transcript_path": session_transcript(session_id),
            "prompt": f"/loop runs/{session_run.name}",
        })

    owner_a_contract = select_for_session(owner_a)
    pending_owner_a = dict(owner_a_contract)
    _atomic_json(_pending_path(owner_a, session_pending), pending_owner_a)
    owner_a_target = "session_end_target_20260101"
    owner_a_effect = seed_activate_effect(owner_a_target)
    write_transition_claim(
        owner_a_target,
        pending_owner_a,
        claims_dir=session_claims,
        origin_run=session_run.name,
        effect=owner_a_effect,
    )
    owner_a_claim_path = _transition_claim_path(
        owner_a_target,
        owner_a,
        owner_a_effect,
        str(owner_a_contract.get("prompt_sha256") or ""),
        session_claims,
    )
    owner_cleanup = cleanup_session_end({
        "hook_event_name": "SessionEnd",
        "session_id": owner_a,
        "transcript_path": session_transcript(owner_a),
        "reason": "prompt_input_exit",
    }, root=session_project, runs_root=session_runs, pointer=session_pointer,
       pending_dir=session_pending, claims_dir=session_claims,
       selection_dir=session_selections)
    owner_selection_path = setup_transaction.session_selection_path(
        session_selections, owner_a)
    session_end_clears_owned_selection = bool(
        owner_cleanup
        and not session_pointer.exists()
        and owner_selection_path.exists()
        and load_contract(session_run, session_id=owner_a) == {}
        and not _pending_path(owner_a, session_pending).exists()
        and json.loads(owner_a_claim_path.read_text(
            encoding="utf-8")).get("status") == "revoked"
    )

    non_resume_sources_do_not_restore = all(
        not restore_session_start({
            "hook_event_name": "SessionStart",
            "source": source,
            "session_id": owner_a,
            "transcript_path": session_transcript(owner_a),
        }, root=session_project, runs_root=session_runs,
           pointer=session_pointer, selection_dir=session_selections)
        for source in ("startup", "clear", "compact")
    ) and not session_pointer.exists() and owner_selection_path.exists()
    wrong_transcript_resume = restore_session_start({
        "hook_event_name": "SessionStart",
        "source": "resume",
        "session_id": owner_a,
        "transcript_path": session_transcript(owner_a) + ".fork",
    }, root=session_project, runs_root=session_runs,
       pointer=session_pointer, selection_dir=session_selections)
    fork_session_resume = restore_session_start({
        "hook_event_name": "SessionStart",
        "source": "resume",
        "session_id": owner_b,
        "transcript_path": session_transcript(owner_a),
    }, root=session_project, runs_root=session_runs,
       pointer=session_pointer, selection_dir=session_selections)
    wrong_resume_identity_fails_closed = bool(
        not wrong_transcript_resume and not fork_session_resume
        and not session_pointer.exists() and owner_selection_path.exists()
    )
    exact_session_resume = restore_session_start({
        "hook_event_name": "SessionStart",
        "source": "resume",
        "session_id": owner_a,
        "transcript_path": session_transcript(owner_a),
    }, root=session_project, runs_root=session_runs,
       pointer=session_pointer, selection_dir=session_selections)
    resume_barrier = load_contract(session_run, session_id=owner_a)
    resume_restores_selection_not_authority = bool(
        exact_session_resume
        and explicit_active_run(
            session_runs, session_pointer, project_root=session_project)
        == session_run.resolve()
        and not owner_selection_path.exists()
        and resume_barrier.get("mode") == EXPLAIN
        and resume_barrier.get("authority_state") == AUTHORITY_RESUME_BARRIER
        and resume_barrier.get("resume_requires_prompt") is True
        and bool(evaluate_pretool(session_run, {
            "tool_name": "Write",
            "tool_input": {"file_path": str(session_run / "evidence.md")},
        }, resume_barrier))
    )
    fresh_resume_prompt = write_contract(session_run, {
        "session_id": owner_a,
        "transcript_path": session_transcript(owner_a),
        "prompt": "继续修复",
    })
    first_prompt_after_resume_mints_fresh_contract = bool(
        fresh_resume_prompt.get("mode") == EXECUTE
        and not fresh_resume_prompt.get("authority_state")
        and not fresh_resume_prompt.get("resume_requires_prompt")
    )

    select_for_session(owner_a)
    wrong_owner_cleanup = cleanup_session_end({
        "hook_event_name": "SessionEnd",
        "session_id": owner_b,
        "transcript_path": session_transcript(owner_b),
        "reason": "other",
    }, root=session_project, runs_root=session_runs, pointer=session_pointer,
       pending_dir=session_pending, claims_dir=session_claims,
       selection_dir=session_selections)
    session_end_preserves_other_owner = bool(
        not wrong_owner_cleanup and session_pointer.exists()
        and load_contract(session_run, session_id=owner_a)
    )
    unknown_owner_contract = load_contract(session_run, session_id=owner_a)
    _atomic_json(
        _pending_path(owner_a, session_pending),
        unknown_owner_contract,
    )
    unknown_owner_target = "session_end_unknown_target_20260101"
    unknown_owner_effect = seed_activate_effect(unknown_owner_target)
    write_transition_claim(
        unknown_owner_target,
        unknown_owner_contract,
        claims_dir=session_claims,
        origin_run=session_run.name,
        effect=unknown_owner_effect,
    )
    unknown_owner_claim_path = _transition_claim_path(
        unknown_owner_target,
        owner_a,
        unknown_owner_effect,
        str(unknown_owner_contract.get("prompt_sha256") or ""),
        session_claims,
    )
    unknown_reason_cleanup = cleanup_session_end({
        "hook_event_name": "SessionEnd",
        "session_id": owner_a,
        "transcript_path": session_transcript(owner_a),
        "reason": "unknown-future-reason",
    }, root=session_project, runs_root=session_runs, pointer=session_pointer,
       pending_dir=session_pending, claims_dir=session_claims,
       selection_dir=session_selections)
    session_end_unknown_reason_fails_closed = bool(
        not unknown_reason_cleanup
        and session_pointer.exists()
        and not _pending_path(owner_a, session_pending).exists()
        and json.loads(unknown_owner_claim_path.read_text(
            encoding="utf-8")).get("status") == "revoked"
    )

    # Simulate session B replacing the contract on the same run after session A
    # observes it but before the transaction owner acquires the pointer lock.
    select_for_session(owner_a)
    original_clear_activation = setup_transaction.clear_activation_cas

    def replace_owner_before_clear(**kwargs):
        write_contract(session_run, {
            "session_id": owner_b,
            "transcript_path": session_transcript(owner_b),
            "prompt": f"/loop runs/{session_run.name}",
        })
        return original_clear_activation(**kwargs)

    with mock.patch.object(
            setup_transaction, "clear_activation_cas", replace_owner_before_clear):
        stale_owner_cleanup = cleanup_session_end({
            "hook_event_name": "SessionEnd",
            "session_id": owner_a,
            "transcript_path": session_transcript(owner_a),
            "reason": "resume",
        }, root=session_project, runs_root=session_runs, pointer=session_pointer,
           pending_dir=session_pending, claims_dir=session_claims,
           selection_dir=session_selections)
    same_run_owner_cas_preserves_new_session = bool(
        not stale_owner_cleanup
        and session_pointer.exists()
        and load_contract(session_run, session_id=owner_b)
    )
    new_owner_cleanup = cleanup_session_end({
        "hook_event_name": "SessionEnd",
        "session_id": owner_b,
        "transcript_path": session_transcript(owner_b),
        "reason": "logout",
    }, root=session_project, runs_root=session_runs, pointer=session_pointer,
       pending_dir=session_pending, claims_dir=session_claims,
       selection_dir=session_selections)
    new_owner_can_clear_after_race = bool(
        new_owner_cleanup and not session_pointer.exists())

    reason_results: list[bool] = []
    for end_reason in sorted(SESSION_END_REASONS):
        reason_owner = "session-end-reason-" + end_reason
        select_for_session(reason_owner)
        reason_results.append(bool(cleanup_session_end({
            "hook_event_name": "SessionEnd",
            "session_id": reason_owner,
            "transcript_path": session_transcript(reason_owner),
            "reason": end_reason,
        }, root=session_project, runs_root=session_runs,
           pointer=session_pointer, pending_dir=session_pending,
           claims_dir=session_claims, selection_dir=session_selections)
           and not session_pointer.exists()))
    all_official_session_end_reasons_clear = all(reason_results)

    select_for_session(owner_a)
    missing_session_cleanup = cleanup_session_end({
        "hook_event_name": "SessionEnd",
        "session_id": "",
        "transcript_path": session_transcript(owner_a),
        "reason": "other",
    }, root=session_project, runs_root=session_runs, pointer=session_pointer,
       pending_dir=session_pending, claims_dir=session_claims,
       selection_dir=session_selections)
    missing_session_preserves_pointer = bool(
        not missing_session_cleanup and session_pointer.exists())

    missing_transcript_owner = "session-end-missing-transcript"
    select_for_session(missing_transcript_owner)
    missing_transcript_cleanup = cleanup_session_end({
        "hook_event_name": "SessionEnd",
        "session_id": missing_transcript_owner,
        "reason": "other",
    }, root=session_project, runs_root=session_runs, pointer=session_pointer,
       pending_dir=session_pending, claims_dir=session_claims,
       selection_dir=session_selections)
    missing_transcript_preserves_pointer = bool(
        not missing_transcript_cleanup and session_pointer.exists())

    invalid_contract_results: list[bool] = []

    def invalid_contract_case(mutator) -> None:
        select_for_session(owner_a)
        mutator(contract_path(session_run))
        result = cleanup_session_end({
            "hook_event_name": "SessionEnd",
            "session_id": owner_a,
            "transcript_path": session_transcript(owner_a),
            "reason": "other",
        }, root=session_project, runs_root=session_runs,
           pointer=session_pointer, pending_dir=session_pending,
           claims_dir=session_claims, selection_dir=session_selections,
           lock_timeout=0.05)
        invalid_contract_results.append(bool(
            not result and session_pointer.exists()))

    invalid_contract_case(lambda path: path.unlink())
    invalid_contract_case(lambda path: path.write_text(
        "{broken", encoding="utf-8"))

    def wrong_contract_schema(path: Path) -> None:
        value = load_contract(session_run, session_id=owner_a)
        if not value:
            value = select_for_session(owner_a)
        value["schema"] = "wrong"
        _atomic_json(path, value)

    def wrong_contract_bound_run(path: Path) -> None:
        value = load_contract(session_run, session_id=owner_a)
        if not value:
            value = select_for_session(owner_a)
        value["bound_run"] = "other_20260101"
        _atomic_json(path, value)

    def invalid_contract_prompt_hash(path: Path) -> None:
        value = load_contract(session_run, session_id=owner_a)
        if not value:
            value = select_for_session(owner_a)
        value["prompt_sha256"] = "not-a-sha256"
        _atomic_json(path, value)

    invalid_contract_case(wrong_contract_schema)
    invalid_contract_case(wrong_contract_bound_run)
    invalid_contract_case(invalid_contract_prompt_hash)
    invalid_session_contracts_preserve_pointer = all(invalid_contract_results)

    session_run_b = session_runs / "session_end_b_20260101"
    (session_run_b / "state").mkdir(parents=True)
    (session_run_b / "target.md").write_text(
        "# Session B run\n", encoding="utf-8")
    write_contract(session_run_b, {
        "session_id": owner_b,
        "transcript_path": session_transcript(owner_b),
        "prompt": f"/loop runs/{session_run_b.name}",
    })
    select_for_session(owner_a)

    def replace_pointer_before_clear(**kwargs):
        session_pointer.write_text(
            str(session_run_b.resolve()) + "\n", encoding="utf-8")
        return original_clear_activation(**kwargs)

    with mock.patch.object(
            setup_transaction, "clear_activation_cas", replace_pointer_before_clear):
        changed_pointer_cleanup = cleanup_session_end({
            "hook_event_name": "SessionEnd",
            "session_id": owner_a,
            "transcript_path": session_transcript(owner_a),
            "reason": "clear",
        }, root=session_project, runs_root=session_runs,
           pointer=session_pointer, pending_dir=session_pending,
           claims_dir=session_claims, selection_dir=session_selections,
           lock_timeout=0.05)
    changed_pointer_cas_preserves_new_run = bool(
        not changed_pointer_cleanup
        and explicit_active_run(
            session_runs, session_pointer, project_root=session_project)
        == session_run_b.resolve()
    )

    process_owner = "session-end-process-owner"
    select_for_session(process_owner)
    session_pointer.write_text(
        str(session_run.resolve()) + "\n", encoding="utf-8")
    session_env = dict(os.environ)
    session_env.update({
        "XUNJI_RUNS_ROOT": str(session_runs),
        "XUNJI_ACTIVE_RUN_FILE": str(session_pointer),
        "XUNJI_PENDING_TURN_DIR": str(session_pending),
        "XUNJI_TRANSITION_CLAIMS_DIR": str(session_claims),
        "XUNJI_SESSION_SELECTION_DIR": str(session_selections),
    })
    session_end_process = subprocess.run(
        [sys.executable, str(Path(__file__).resolve())],
        input=json.dumps({
            "hook_event_name": "SessionEnd",
            "session_id": process_owner,
            "transcript_path": session_transcript(process_owner),
            "reason": "prompt_input_exit",
        }),
        text=True,
        capture_output=True,
        env=session_env,
        timeout=5,
    )
    session_end_hook_exits_cleanly = bool(
        session_end_process.returncode == 0
        and not session_end_process.stdout.strip()
        and session_pointer.exists()
    )

    lock_owner = "session-end-lock-owner"
    select_for_session(lock_owner)
    cleanup_lock = session_pointer.parent \
        / setup_transaction.ACTIVATION_LOCK_NAME
    lock_started = time.monotonic()
    with setup_transaction.exclusive_directory_lock(cleanup_lock):
        lock_busy_cleanup = cleanup_session_end({
            "hook_event_name": "SessionEnd",
            "session_id": lock_owner,
            "transcript_path": session_transcript(lock_owner),
            "reason": "other",
        }, root=session_project, runs_root=session_runs,
           pointer=session_pointer, pending_dir=session_pending,
           claims_dir=session_claims, selection_dir=session_selections,
           lock_timeout=0.05)
    lock_elapsed = time.monotonic() - lock_started
    session_end_lock_timeout_is_bounded = bool(
        not lock_busy_cleanup
        and session_pointer.exists()
        and lock_elapsed < 0.4
    )
    post_lock_cleanup = cleanup_session_end({
        "hook_event_name": "SessionEnd",
        "session_id": lock_owner,
        "transcript_path": session_transcript(lock_owner),
        "reason": "other",
    }, root=session_project, runs_root=session_runs, pointer=session_pointer,
       pending_dir=session_pending, claims_dir=session_claims,
       selection_dir=session_selections)
    session_end_can_retry_after_lock_release = bool(
        post_lock_cleanup and not session_pointer.exists())

    select_for_session(owner_a)
    before_invalid_attestation = setup_transaction.pointer_snapshot(session_pointer)
    try:
        setup_transaction.clear_activation_cas(
            expected=before_invalid_attestation,
            pointer=session_pointer,
            root=session_project,
            runs_root=session_runs,
            session_id=owner_a,
        )
        partial_clear_attestation_rejected = False
    except setup_transaction.SetupTransactionError as exc:
        partial_clear_attestation_rejected = bool(
            exc.code == "invalid_clear_attestation"
            and session_pointer.exists())
    no_run_cron = subprocess.run(
        [sys.executable, str(Path(__file__).resolve())],
        input=json.dumps({
            "hook_event_name": "PreToolUse", "session_id": "s",
            "tool_name": "CronCreate", "tool_input": {"prompt": "/loop future-run"},
        }),
        text=True, capture_output=True, env=env, timeout=10,
    )
    no_run_pointer_write = subprocess.run(
        [sys.executable, str(Path(__file__).resolve())],
        input=json.dumps({
            "hook_event_name": "PreToolUse", "session_id": "s",
            "tool_name": "Write",
            "tool_input": {"file_path": str(ROOT / ".claude" / "xunji_active_run"),
                           "content": "runs/forged\n"},
        }),
        text=True, capture_output=True, env=env, timeout=10,
    )
    no_run_pending_write = subprocess.run(
        [sys.executable, str(Path(__file__).resolve())],
        input=json.dumps({
            "hook_event_name": "PreToolUse", "session_id": "s",
            "tool_name": "Write",
            "tool_input": {"file_path": str(pending_dir / "forged.json"),
                           "content": "{}\n"},
        }),
        text=True, capture_output=True, env=env, timeout=10,
    )
    no_run_selection_write = subprocess.run(
        [sys.executable, str(Path(__file__).resolve())],
        input=json.dumps({
            "hook_event_name": "PreToolUse", "session_id": "s",
            "tool_name": "Write",
            "tool_input": {
                "file_path": str(ROOT / ".claude" / "xunji_session_selections"
                                 / ("a" * 64 + ".json")),
                "content": "{}\n",
            },
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
    source_run = root / "source-run"
    target_run = root / "target-run"
    (source_run / "state").mkdir(parents=True)
    (target_run / "state").mkdir(parents=True)
    transferred_source = write_contract(source_run, {
        "prompt": "/loop 重新开一个新 run", "session_id": "s-transition",
        "transcript_path": str(transcript),
    })
    transfer_txid = "c" * 32
    transfer_source_hash = "d" * 64
    transferred = transfer_contract(
        source_run,
        target_run,
        transaction_id=transfer_txid,
        source_hash=transfer_source_hash,
        expected_run=target_run.name,
    )
    transfer_preserves_contract = (
        transferred.get("prompt_sha256") == transferred_source.get("prompt_sha256")
        and transferred.get("session_id") == transferred_source.get("session_id")
        and transferred.get("origin_run") == source_run.name
        and transferred.get("bound_run") == target_run.name
        and transferred.get("transition_transaction") == {
            "transaction_id": transfer_txid,
            "source_sha256": transfer_source_hash,
            "expected_run": target_run.name,
        }
        and load_contract(target_run, session_id="s-transition") == transferred
        and json.loads(run_status_path(target_run).read_text(encoding="utf-8"))["status"] == "active"
    )
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

    proxy_run = root / "proxy-run"
    (proxy_run / "state").mkdir(parents=True)
    (proxy_run / "frontier.md").write_text(
        "# Frontier\n## Open Fronts\n### F-001\n- Front: a.example public app\n"
        "- Status: open\n- Barrier class: none\n- Current depth: shallow\n",
        encoding="utf-8")
    (proxy_run / "coverage.json").write_text(json.dumps({"assets": [
        {"host": "a.example", "reachable": True, "examined": False},
    ]}), encoding="utf-8")
    proxy_contract = {
        "mode": EXECUTE, "session_id": "proxy-session", "prompt_excerpt": "继续执行",
        "fanout_override": True, "updated_at": time.time(),
    }
    raw_curl = {"tool_name": "Bash", "tool_input": {
        "command": "curl https://a.example/"}}
    raw_requests = {"tool_name": "Bash", "tool_input": {
        "command": "python3 -c 'import requests; requests.get(\"https://a.example\")'"}}
    target_webfetch = {"tool_name": "WebFetch", "tool_input": {"url": "https://a.example/"}}
    unknown_webfetch = {"tool_name": "WebFetch", "tool_input": {
        "url": "https://unknown.example/"}}
    guarded_probe = {"tool_name": "Bash", "tool_input": {
        "command": f"python3 {ROOT / 'tools' / 'probe.py'} GET https://a.example/"}}
    unknown_guarded_probe = {"tool_name": "Bash", "tool_input": {
        "command": f"python3 {ROOT / 'tools' / 'probe.py'} GET https://unknown.example/"}}
    direct_guarded_probe = {"tool_name": "Bash", "tool_input": {
        "command": (
            f"XUNJI_PROXY_REQUIRED=0 python3 {ROOT / 'tools' / 'probe.py'} "
            "GET https://a.example/"
        )}}
    direct_env_probe = {"tool_name": "Bash", "tool_input": {
        "command": f"python3 {ROOT / 'tools' / 'probe.py'} GET https://a.example/",
        "env": {"XUNJI_PROXY_REQUIRED": "0"},
    }}
    quoted_direct_probe = {"tool_name": "Bash", "tool_input": {
        "command": (
            f"XUNJI_PROXY_REQUIRED=o''ff python3 {ROOT / 'tools' / 'probe.py'} "
            "GET https://a.example/"
        )}}
    browser_target = {"tool_name": "mcp__browser__navigate", "tool_input": {
        "url": "https://a.example/"}}
    raw_curl_blocked = "交战代理硬门" in evaluate_pretool(proxy_run, raw_curl, proxy_contract)
    raw_requests_blocked = "交战代理硬门" in evaluate_pretool(
        proxy_run, raw_requests, proxy_contract)
    target_webfetch_blocked = "交战代理硬门" in evaluate_pretool(
        proxy_run, target_webfetch, proxy_contract)
    unknown_webfetch_blocked = "交战代理硬门" in evaluate_pretool(
        proxy_run, unknown_webfetch, proxy_contract)
    guarded_probe_allowed = evaluate_pretool(proxy_run, guarded_probe, proxy_contract) == ""
    scoped_proxy_coverage = json.loads(
        (proxy_run / "coverage.json").read_text(encoding="utf-8"))
    scoped_proxy_coverage["assets"][0]["scope_status"] = "review"
    (proxy_run / "coverage.json").write_text(
        json.dumps(scoped_proxy_coverage), encoding="utf-8")
    review_scope_target_blocked = "scope 准入硬门" in evaluate_pretool(
        proxy_run, guarded_probe, proxy_contract)
    scoped_proxy_coverage["assets"][0]["scope_status"] = "out"
    (proxy_run / "coverage.json").write_text(
        json.dumps(scoped_proxy_coverage), encoding="utf-8")
    out_scope_target_blocked = "scope 准入硬门" in evaluate_pretool(
        proxy_run, guarded_probe, proxy_contract)
    scoped_proxy_coverage["assets"][0]["scope_status"] = "in"
    scoped_proxy_coverage["assets"][0]["source"] = "setup-source-candidate"
    (proxy_run / "coverage.json").write_text(
        json.dumps(scoped_proxy_coverage), encoding="utf-8")
    forged_candidate_in_scope_blocked = "invalid-admission-receipt" in evaluate_pretool(
        proxy_run, guarded_probe, proxy_contract)
    scoped_proxy_coverage["assets"][0].pop("source", None)
    (proxy_run / "coverage.json").write_text(
        json.dumps(scoped_proxy_coverage), encoding="utf-8")
    explicit_in_scope_target_allowed = evaluate_pretool(
        proxy_run, guarded_probe, proxy_contract) == ""
    unknown_guarded_probe_blocked = "未知目标: unknown.example" in evaluate_pretool(
        proxy_run, unknown_guarded_probe, proxy_contract)
    direct_without_operator_blocked = "当前操作者 prompt" in evaluate_pretool(
        proxy_run, direct_guarded_probe, proxy_contract)
    direct_env_without_operator_blocked = "当前操作者 prompt" in evaluate_pretool(
        proxy_run, direct_env_probe, proxy_contract)
    quoted_direct_without_operator_blocked = "当前操作者 prompt" in evaluate_pretool(
        proxy_run, quoted_direct_probe, proxy_contract)
    direct_with_operator_allowed = evaluate_pretool(
        proxy_run, direct_guarded_probe,
        {**proxy_contract, "direct_egress_approved": True}) == ""
    quoted_direct_with_operator_allowed = evaluate_pretool(
        proxy_run, quoted_direct_probe,
        {**proxy_contract, "direct_egress_approved": True}) == ""
    nonbash_target_tool_blocked = "非 Bash 网络工具" in evaluate_pretool(
        proxy_run, browser_target, proxy_contract)
    (proxy_run / "frontier.md").write_text(
        "# Frontier\n## Open Fronts\n### F-001\n- Front: unmapped app\n"
        "- Status: open\n- Barrier class: none\n- Current depth: shallow\n",
        encoding="utf-8")
    unassigned_asset_blocked = "资产覆盖硬门" in evaluate_pretool(
        proxy_run, guarded_probe, proxy_contract)
    (proxy_run / "frontier.md").write_text(
        "# Frontier\n## Open Fronts\n### F-001\n- Front: a.example public app\n"
        "- Status: open\n- Barrier class: none\n- Current depth: shallow\n",
        encoding="utf-8")

    corrupt_run = root / "corrupt-coverage-run"
    corrupt_run.mkdir()
    (corrupt_run / "frontier.md").write_text(
        "# Frontier\n## Open Fronts\n### F-001\n- Front: unknown target\n"
        "- Status: open\n- Barrier class: none\n- Current depth: shallow\n",
        encoding="utf-8")
    (corrupt_run / "coverage.json").write_text("{broken", encoding="utf-8")
    corrupt_reason = evaluate_pretool(
        corrupt_run, {"tool_name": "Bash", "tool_input": {
            "command": f"python3 {ROOT / 'tools' / 'probe.py'} GET https://unknown.example/"}},
        proxy_contract)
    corrupt_coverage_fails_closed = (
        "资产覆盖硬门" in corrupt_reason and "coverage" in corrupt_reason)
    nested_run = root / "nested-coverage-run"
    (nested_run / "classify").mkdir(parents=True)
    (nested_run / "frontier.md").write_text(
        "# Frontier\n## Open Fronts\n### F-001\n- Front: nested.example app\n"
        "- Status: open\n- Barrier class: none\n- Current depth: shallow\n",
        encoding="utf-8")
    (nested_run / "coverage.json").write_text("{broken", encoding="utf-8")
    (nested_run / "classify" / "coverage.json").write_text(json.dumps({"assets": [
        {"host": "nested.example", "reachable": True},
    ]}), encoding="utf-8")
    nested_fallback_host_is_enforced = "交战代理硬门" in evaluate_pretool(
        nested_run, {"tool_name": "Bash", "tool_input": {
            "command": "curl https://nested.example/"}}, proxy_contract)

    epoch_first = write_contract(proxy_run, {
        "prompt": "继续执行", "session_id": "epoch-one", "transcript_path": str(transcript)})
    epoch_second = write_contract(proxy_run, {
        "prompt": "继续执行", "session_id": "epoch-two", "transcript_path": str(transcript)})
    proxy_cov = json.loads((proxy_run / "coverage.json").read_text(encoding="utf-8"))
    proxy_cov["assets"][0]["verdict"] = "closed"
    (proxy_run / "coverage.json").write_text(json.dumps(proxy_cov), encoding="utf-8")
    changed_signature_invalidates_pair = not coordination_epoch(
        proxy_run, epoch_second).get("valid")
    epoch_third = write_contract(proxy_run, {
        "prompt": "继续执行", "session_id": "epoch-three", "transcript_path": str(transcript)})
    fanout_epoch_persists = (
        epoch_first["fanout_epoch_started_at"] == epoch_second["fanout_epoch_started_at"]
        and epoch_first["fanout_epoch_id"] == epoch_second["fanout_epoch_id"])
    material_debt_change_resets_epoch = (
        epoch_third["fanout_epoch_id"] != epoch_second["fanout_epoch_id"]
        and epoch_third["fanout_epoch_started_at"] >= epoch_second["updated_at"])

    actor_run = root / "actor-run"
    (actor_run / "state").mkdir(parents=True)
    (actor_run / "agents").mkdir()
    (actor_run / "frontier.md").write_text(
        "# Frontier\n## Open Fronts\n"
        "### F-001\n- Front: a.example lane\n- Status: open\n- Barrier class: app\n- Current depth: shallow\n"
        "### F-002\n- Front: b.example lane\n- Status: open\n- Barrier class: auth\n- Current depth: shallow\n"
        "### F-003\n- Front: local code lane\n- Status: open\n- Barrier class: code\n- Current depth: shallow\n"
        "### F-004\n- Front: synthesis lane\n- Status: open\n- Barrier class: none\n- Current depth: shallow\n",
        encoding="utf-8")
    (actor_run / "coverage.json").write_text(json.dumps({"assets": [
        {"host": "a.example", "reachable": True},
        {"host": "b.example", "reachable": True},
    ]}), encoding="utf-8")
    (actor_run / "agents" / "A-one.md").write_text("# Agent\n", encoding="utf-8")
    (actor_run / "agents" / "A-two.md").write_text("# Agent\n", encoding="utf-8")
    (actor_run / "state" / "assignments.json").write_text(json.dumps({"assignments": [
        {"agent": "A-one", "front": "F-001", "status": "assigned", "assets": ["a.example"]},
        {"agent": "A-two", "front": "F-002", "status": "assigned", "assets": ["b.example"]},
    ]}), encoding="utf-8")
    actor_contract = {
        "mode": EXECUTE, "session_id": "actor-session", "prompt_excerpt": "继续执行",
        "updated_at": time.time(), "fanout_epoch_started_at": time.time() - 1,
        "coordination_signature": _coordination_signature(actor_run),
        "fanout_epoch_id": "fedcba9876543210",
    }
    actor_good_prompt = {"tool_name": "Agent", "tool_input": {
        "prompt": "XUNJI_ASSIGNMENT=A-one XUNJI_FRONT=F-001 "
                  "XUNJI_ASSETS=a.example",
        "subagent_type": "xunji-hunter",
    }}
    actor_bad_assets_prompt = {"tool_name": "Agent", "tool_input": {
        "prompt": "XUNJI_ASSIGNMENT=A-one XUNJI_FRONT=F-001 "
                  "XUNJI_ASSETS=b.example",
        "subagent_type": "xunji-hunter",
    }}
    asset_bound_prompt_allowed = evaluate_pretool(
        actor_run, actor_good_prompt, actor_contract) == ""
    mismatched_asset_prompt_blocked = "XUNJI_ASSETS=a.example" in evaluate_pretool(
        actor_run, actor_bad_assets_prompt, actor_contract)
    actor_transcript = root / "actor-transcript.jsonl"
    actor_transcript.write_text(
        "\n".join(json.dumps({
            "type": "user",
            "message": {"content": [{
                "type": "tool_result",
                "tool_use_id": tool_use_id,
                "content": {"content": content},
            }]},
        }, sort_keys=True) for tool_use_id, content in (
            ("launch-one", "child-one returned its bounded lane result"),
            ("launch-two", "child-two returned its bounded lane result"),
        )) + "\n",
        encoding="utf-8")

    def actor_launch(tool_id: str, assignment: str, front: str, asset: str, child: str) -> None:
        runtime_receipts.append_hook_event(actor_run, {
            "hook_event_name": "PostToolUse", "session_id": "actor-session",
            "transcript_path": str(actor_transcript), "tool_name": "Agent",
            "tool_use_id": tool_id,
            "tool_input": {
                "prompt": (
                    f"XUNJI_ASSIGNMENT={assignment} XUNJI_FRONT={front} "
                    f"XUNJI_ASSETS={asset}"),
                "subagent_type": "xunji-hunter",
            },
            "tool_response": {"agentId": child, "isAsync": True, "status": "async_launched"},
        })

    actor_launch("launch-one", "A-one", "F-001", "a.example", "child-one")
    actor_launch("launch-two", "A-two", "F-002", "b.example", "child-two")
    child_own_action = {"tool_name": "Bash", "agent_id": "child-one", "tool_input": {
        "command": f"python3 {ROOT / 'tools' / 'probe.py'} GET https://a.example/"}}
    child_outside_action = {"tool_name": "Bash", "agent_id": "child-one", "tool_input": {
        "command": f"python3 {ROOT / 'tools' / 'probe.py'} GET https://b.example/"}}
    child_nested_agent = {"tool_name": "Agent", "agent_id": "child-one", "tool_input": {
        "prompt": "XUNJI_ASSIGNMENT=A-two XUNJI_FRONT=F-002 XUNJI_ASSETS=b.example"}}
    child_lane_allowed = evaluate_pretool(actor_run, child_own_action, actor_contract) == ""
    child_asset_escape_blocked = "越界资产" in evaluate_pretool(
        actor_run, child_outside_action, actor_contract)
    nested_agent_blocked = "只有 Root 可派 Agent" in evaluate_pretool(
        actor_run, child_nested_agent, actor_contract)
    root_allowed_while_agents_running = evaluate_pretool(
        actor_run, {**guarded_probe}, actor_contract) == ""
    runtime_receipts.append_hook_event(actor_run, {
        "hook_event_name": "SubagentStop", "session_id": "actor-session",
        "transcript_path": str(actor_transcript), "agent_id": "child-one",
        "agent_type": "xunji-hunter",
        "tool_response": {"content": "child-one returned its bounded lane result"},
    })
    root_blocked_after_real_return = "SubagentStop" in evaluate_pretool(
        actor_run, {**guarded_probe}, actor_contract)
    child_two_action = {"tool_name": "Bash", "agent_id": "child-two", "tool_input": {
        "command": f"python3 {ROOT / 'tools' / 'probe.py'} GET https://b.example/"}}
    running_peer_not_blocked_by_returned_peer = evaluate_pretool(
        actor_run, child_two_action, actor_contract) == ""
    actor_assignments = json.loads(
        (actor_run / "state" / "assignments.json").read_text(encoding="utf-8"))
    for row in actor_assignments["assignments"]:
        if row.get("agent") == "A-two":
            row["assets"] = []
    (actor_run / "state" / "assignments.json").write_text(
        json.dumps(actor_assignments), encoding="utf-8")
    legacy_empty_asset_child_blocked = "空资产 assignment" in evaluate_pretool(
        actor_run, child_two_action, actor_contract)
    for row in actor_assignments["assignments"]:
        if row.get("agent") == "A-two":
            row["assets"] = ["b.example"]
    (actor_run / "state" / "assignments.json").write_text(
        json.dumps(actor_assignments), encoding="utf-8")
    completion_actor_run = root / "completion-actor-run"
    completion_actor_contract, _ = seed_current_plan(
        completion_actor_run, stage="S3")
    completion_actor_transcript = root / "completion-actor-transcript.jsonl"
    actor_completion_prompt = runtime_receipts.completion_review_prompt(
        completion_actor_run)
    completion_actor_transcript.write_text(json.dumps({
        "message": {"role": "assistant", "content": [{
            "type": "tool_use", "id": "completion-launch",
            "name": "Agent", "input": {
                "prompt": actor_completion_prompt,
                "subagent_type": "xunji-reviewer",
            },
        }]},
    }, sort_keys=True) + "\n", encoding="utf-8")
    runtime_receipts.append_hook_event(completion_actor_run, {
        "hook_event_name": "PostToolUse", "session_id": "completion-actor-session",
        "transcript_path": str(completion_actor_transcript), "tool_name": "Agent",
        "tool_use_id": "completion-launch",
        "tool_input": {"prompt": actor_completion_prompt,
            "subagent_type": "xunji-reviewer",
        },
        "tool_response": {"agentId": "completion-child", "isAsync": True,
                          "status": "async_launched"},
    })
    runtime_receipts.append_hook_event(completion_actor_run, {
        "hook_event_name": "SubagentStart",
        "session_id": "completion-actor-session",
        "transcript_path": str(completion_actor_transcript),
        "agent_id": "completion-child",
        "agent_type": "xunji-reviewer",
    })
    completion_child_read_allowed = evaluate_pretool(completion_actor_run, {
        "tool_name": "Read", "agent_id": "completion-child",
        "tool_input": {"file_path": str(completion_actor_run / "evidence.md")},
    }, completion_actor_contract) == ""
    completion_child_write_blocked = "只允许读取" in evaluate_pretool(
        completion_actor_run, {
        "tool_name": "Write", "agent_id": "completion-child",
        "tool_input": {
            "file_path": str(completion_actor_run / "report.md"),
            "content": "forged",
        },
    }, completion_actor_contract)

    sync_actor_run = root / "sync-actor-run"
    (sync_actor_run / "state").mkdir(parents=True)
    (sync_actor_run / "agents").mkdir()
    (sync_actor_run / "frontier.md").write_text(
        "# Frontier\n## Open Fronts\n### F-001\n- Status: open\n"
        "- Barrier class: code\n- Current depth: shallow\n",
        encoding="utf-8",
    )
    (sync_actor_run / "agents" / "A-sync.md").write_text(
        "# Agent\n", encoding="utf-8")
    (sync_actor_run / "state" / "assignments.json").write_text(json.dumps({
        "schema": 3,
        "assignments": [{
            "agent": "A-sync", "front": "F-001", "status": "assigned",
            "assets": [], "effect": "local_read", "attempts": [],
        }],
    }), encoding="utf-8")
    sync_actor_prompt = (
        "XUNJI_ASSIGNMENT=A-sync XUNJI_FRONT=F-001 XUNJI_ASSETS=none")
    sync_actor_transcript = root / "sync-actor-transcript.jsonl"
    sync_actor_transcript.write_text(json.dumps({
        "message": {"role": "assistant", "content": [{
            "type": "tool_use", "id": "sync-actor-tool", "name": "Agent",
            "input": {
                "prompt": sync_actor_prompt,
                "subagent_type": "xunji-hunter",
            },
        }]},
    }) + "\n", encoding="utf-8")
    runtime_receipts.append_hook_event(sync_actor_run, {
        "hook_event_name": "SubagentStart", "session_id": "sync-actor-session",
        "transcript_path": str(sync_actor_transcript),
        "agent_id": "sync-actor-child", "agent_type": "xunji-hunter",
    })
    sync_actor_contract = {
        "mode": EXECUTE, "session_id": "sync-actor-session",
        "prompt_excerpt": "continue", "updated_at": time.time(),
    }
    sync_child_read = {
        "tool_name": "Read", "agent_id": "sync-actor-child",
        "tool_input": {"file_path": str(sync_actor_run / "frontier.md")},
    }
    synchronous_child_allowed_before_parent_post = evaluate_pretool(
        sync_actor_run, sync_child_read, sync_actor_contract) == ""
    runtime_receipts.append_hook_event(sync_actor_run, {
        "hook_event_name": "SubagentStop", "session_id": "sync-actor-session",
        "transcript_path": str(sync_actor_transcript),
        "agent_id": "sync-actor-child", "agent_type": "xunji-hunter",
        "last_assistant_message": "SYNC-ACTOR-FINAL",
    })
    synchronous_child_blocked_after_stop = "已返回" in evaluate_pretool(
        sync_actor_run, sync_child_read, sync_actor_contract)
    with sync_actor_transcript.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps({
            "message": {"content": [{
                "type": "tool_result", "tool_use_id": "sync-actor-tool",
                "content": [{"type": "text", "text": "SYNC-ACTOR-FINAL"}],
            }]},
        }) + "\n")
    runtime_receipts.append_hook_event(sync_actor_run, {
        "hook_event_name": "PostToolUse", "session_id": "sync-actor-session",
        "transcript_path": str(sync_actor_transcript), "tool_name": "Agent",
        "tool_use_id": "sync-actor-tool",
        "tool_input": {
            "prompt": sync_actor_prompt,
            "subagent_type": "xunji-hunter",
        },
        "tool_response": [{"type": "text", "text": "SYNC-ACTOR-FINAL"}],
    })
    sync_actor_attempts = runtime_receipts.agent_attempts(sync_actor_run)

    maintenance_prompt = (
        "修复 Xunji turn contract 的维护边界，并同步 WORKFLOW 文档\n"
        "continue with local verification"
    )
    maintenance_contract = _contract_from_event({
        "prompt": maintenance_prompt,
        "session_id": "maintenance-session",
        "transcript_path": str(root / "maintenance-transcript.jsonl"),
    }, run_name=run.name)
    malformed_maintenance_contract = _contract_from_event({
        "prompt": "/xunji-maintenance 修复 turn contract",
        "session_id": "maintenance-session",
    }, run_name=run.name)
    missing_session_maintenance_contract = _contract_from_event({
        "prompt": maintenance_prompt,
    }, run_name=run.name)
    operator_e2e_loop_contract = _contract_from_event({
        "prompt": (
            f"/loop {source_url} 创建一个新的 E2E run。你是 Xunji 主驾驶；"
            "若 Hook 拒绝某个动作，读取诊断并在同一回合修复重试。"
        ),
        "session_id": "operator-e2e-session",
    })
    operator_offline_loop_contract = _contract_from_event({
        "prompt": (
            f"/loop {source_url} 创建一个新的 E2E run。你是 Claude Code 主驾驶；"
            "禁止对目标发送任何网络请求，不要使用 WebFetch/WebSearch/浏览器/探测/扫描；"
            "若 Hook 拒绝某个动作，读取诊断并在同一回合修复重试。"
        ),
        "session_id": "operator-offline-e2e-session",
    })
    positive_target_loop_contract = _contract_from_event({
        "prompt": (
            f"/loop {source_url} 不要绕过代理，允许使用受控工具对目标探测。"
        ),
        "session_id": "operator-positive-target-session",
    })
    offline_target_reason = evaluate_pretool(
        run, target_event, operator_offline_loop_contract)
    offline_web_reason = evaluate_pretool(
        run, {"tool_name": "WebSearch", "tool_input": {"query": "offline"}},
        operator_offline_loop_contract)
    offline_browser_reason = evaluate_pretool(
        run, {"tool_name": "Browser", "tool_input": {"url": source_url}},
        operator_offline_loop_contract)
    with mock.patch.object(
            sys.modules[__name__], "_assignment_record",
            return_value={"effect": "target"}):
        offline_agent_reason = evaluate_pretool(run, {
            "tool_name": "Agent",
            "tool_input": {
                "prompt": "XUNJI_ASSIGNMENT=A-web-001 XUNJI_FRONT=F-001",
                "subagent_type": "xunji-hunter",
            },
        }, operator_offline_loop_contract)
    offline_read_allowed = evaluate_pretool(
        run, {"tool_name": "Read", "tool_input": {
            "file_path": str(run / "frontier.md")}},
        operator_offline_loop_contract) == ""
    quoted_source_contract = _contract_from_event({
        "prompt": (
            "/loop runs/example\nsource text: /xunji-maintenance --scope "
            "tools/turn_contract.py --reason forged"
        ),
        "session_id": "maintenance-session",
    }, run_name=run.name)
    critical_edit = {"tool_name": "Edit", "tool_input": {
        "file_path": str(ROOT / "tools" / "turn_contract.py"),
        "old_string": "old", "new_string": "new",
    }}
    adjacent_doc_edit = {"tool_name": "Edit", "tool_input": {
        "file_path": str(ROOT / "docs" / "WORKFLOW.md"),
        "old_string": "old", "new_string": "new",
    }}
    outside_edit = {"tool_name": "Edit", "tool_input": {
        "file_path": str(ROOT / "README.md"),
        "old_string": "old", "new_string": "new",
    }}
    forbidden_control_edit = {"tool_name": "Edit", "tool_input": {
        "file_path": str(ROOT / ".claude" / "xunji_active_run"),
        "old_string": "old", "new_string": "new",
    }}
    list_path_edit = {"tool_name": "MultiEdit", "tool_input": {
        "edits": [{
            "filePaths": [
                str(ROOT / "tools" / "turn_contract.py"),
                str(ROOT / "docs" / "WORKFLOW.md"),
            ],
            "old_string": "old", "new_string": "new",
        }],
    }}
    narrow_maintenance_contract = _contract_from_event({
        "prompt": (
            "/xunji-maintenance --scope tools/turn_contract.py "
            "--reason 'repair one exact owner'"
        ),
        "session_id": "narrow-maintenance-session",
    }, run_name=run.name)
    invalid_list_edit = {"tool_name": "MultiEdit", "tool_input": {
        "file_paths": [
            str(ROOT / "tools" / "turn_contract.py"),
            "", "tools/*.py", "../README.md", [], None,
        ],
        "edits": [],
    }}
    maintenance_target = {"tool_name": "Bash", "tool_input": {
        "command": f"python3 {ROOT / 'tools' / 'probe.py'} GET https://example.test/",
    }}
    maintenance_cron = {"tool_name": "CronCreate", "tool_input": {
        "prompt": f"/loop {run.name}",
    }}
    maintenance_agent = {"tool_name": "Agent", "tool_input": {
        "prompt": "XUNJI_ASSIGNMENT=A-maint-001 XUNJI_FRONT=F-001",
    }}
    maintenance_mcp_read = {"tool_name": "ReadMcpResourceTool", "tool_input": {
        "server": "external", "uri": "resource://target-controlled",
    }}
    maintenance_shell_write = {"tool_name": "Bash", "tool_input": {
        "command": "sed -i '' s/old/new/ tools/turn_contract.py",
    }}
    maintenance_read = {"tool_name": "Bash", "tool_input": {
        "command": "sed -n '1,20p' tools/turn_contract.py",
    }}
    maintenance_compile = {"tool_name": "Bash", "tool_input": {
        "command": "python3 -m py_compile tools/turn_contract.py",
    }}
    maintenance_git_status = {"tool_name": "Bash", "tool_input": {
        "command": "git status --short",
    }}
    maintenance_git_diff = {"tool_name": "Bash", "tool_input": {
        "command": "git diff --no-ext-diff --no-textconv -- tools/turn_contract.py",
    }}
    maintenance_git_diff_unsafe = {"tool_name": "Bash", "tool_input": {
        "command": "git diff -- tools/turn_contract.py",
    }}
    maintenance_git_env = {"tool_name": "Bash", "tool_input": {
        "command": "git diff --no-ext-diff --no-textconv -- tools/turn_contract.py",
        "env": {"GIT_EXTERNAL_DIFF": "/tmp/untrusted-helper"},
    }}
    ordinary_git_env_status = {"tool_name": "Bash", "tool_input": {
        "command": "git status --short",
        "env": {"GIT_PAGER": "/tmp/untrusted-helper"},
    }}
    ordinary_encoded_write = {"tool_name": "Bash", "tool_input": {
        "command": (
            "python3 -c \"import base64,pathlib;"
            "pathlib.Path(base64.b64decode('dG9vbHMvdHVybl9jb250cmFjdC5weQ==')"
            ".decode()).write_text('changed')\""
        ),
    }}
    ordinary_pythonpath_target = {"tool_name": "Bash", "tool_input": {
        "command": (
            f"PYTHONPATH=/tmp python3 {ROOT / 'tools' / 'probe.py'} "
            "GET https://a.example/"
        ),
    }}
    maintenance_git_add = {"tool_name": "Bash", "tool_input": {
        "command": "git add -- tools/turn_contract.py",
    }}
    opaque_git_apply = {"tool_name": "Bash", "tool_input": {
        "command": "git apply /tmp/uninspected.patch",
    }}
    opaque_git_wrapped = [
        {"tool_name": "Bash", "tool_input": {
            "command": "env GIT_CONFIG_NOSYSTEM=1 /usr/bin/git apply /tmp/uninspected.patch",
        }},
        {"tool_name": "Bash", "tool_input": {
            "command": "sh -c 'git checkout -- tools/turn_contract.py'",
        }},
        {"tool_name": "Bash", "tool_input": {
            "command": "command -p git commit --amend --no-edit",
        }},
        {"tool_name": "Bash", "tool_input": {
            "command": "exec /usr/bin/git checkout -- tools/turn_contract.py",
        }},
        {"tool_name": "Bash", "tool_input": {
            "command": "cd /tmp && patch -p1 < change.diff",
        }},
        {"tool_name": "Bash", "tool_input": {
            "command": "git pull --ff-only",
        }},
        {"tool_name": "Bash", "tool_input": {
            "command": "git clone https://example.test/repo.git /tmp/repo-copy",
        }},
    ]
    git_env_read = {"tool_name": "Bash", "tool_input": {
        "command": "git status --short",
        "env": {"GIT_PAGER": "/tmp/untrusted-helper"},
    }}
    repo_words_as_data = [
        {"tool_name": "Bash", "tool_input": {
            "command": "echo 'git status --short'"}},
        {"tool_name": "Bash", "tool_input": {
            "command": "echo 'NO git available'"}},
        {"tool_name": "Bash", "tool_input": {
            "command": "printf '%s' 'patch notes only'"}},
        {"tool_name": "Bash", "tool_input": {
            "command": "python3 -c \"print('git apply')\""}},
    ]
    ordinary_critical_edit_blocked = bool(evaluate_pretool(
        run, critical_edit, contract))
    authorized_critical_edit_allowed = evaluate_pretool(
        run, critical_edit, maintenance_contract) == ""
    authorized_adjacent_doc_allowed = evaluate_pretool(
        run, adjacent_doc_edit, maintenance_contract) == ""
    maintenance_outside_edit_allowed = evaluate_pretool(
        run, outside_edit, maintenance_contract) == ""
    maintenance_list_paths_allowed = evaluate_pretool(
        run, list_path_edit, maintenance_contract) == ""
    maintenance_mixed_list_allowed = evaluate_pretool(
        run, list_path_edit, narrow_maintenance_contract) == ""
    maintenance_invalid_list_blocked = "path 参数" in evaluate_pretool(
        run, invalid_list_edit, maintenance_contract)
    maintenance_target_blocked = "禁止 target/network" in evaluate_pretool(
        run, maintenance_target, maintenance_contract)
    maintenance_cron_blocked = "禁止 target/network" in evaluate_pretool(
        run, maintenance_cron, maintenance_contract)
    maintenance_agent_blocked = "禁止 target/network" in evaluate_pretool(
        run, maintenance_agent, maintenance_contract)
    maintenance_mcp_blocked = "不允许工具" in evaluate_pretool(
        run, maintenance_mcp_read, maintenance_contract)
    maintenance_shell_write_blocked = "禁止用 Bash" in evaluate_pretool(
        run, maintenance_shell_write, maintenance_contract)
    maintenance_read_allowed = evaluate_pretool(
        run, maintenance_read, maintenance_contract) == ""
    maintenance_compile_allowed = evaluate_pretool(
        run, maintenance_compile, maintenance_contract) == ""
    maintenance_git_read_allowed = evaluate_pretool(
        run, maintenance_git_status, maintenance_contract) == ""
    maintenance_git_diff_allowed = evaluate_pretool(
        run, maintenance_git_diff, maintenance_contract) == ""
    maintenance_git_diff_unsafe_blocked = bool(evaluate_pretool(
        run, maintenance_git_diff_unsafe, maintenance_contract))
    maintenance_git_env_blocked = "环境覆盖" in evaluate_pretool(
        run, maintenance_git_env, maintenance_contract)
    ordinary_git_env_blocked = bool(evaluate_pretool(
        run, ordinary_git_env_status, contract))
    ordinary_encoded_write_blocked = "Bash 只能执行" in evaluate_pretool(
        run, ordinary_encoded_write, contract)
    ordinary_pythonpath_target_blocked = bool(evaluate_pretool(
        run, ordinary_pythonpath_target, contract))
    maintenance_git_add_blocked = bool(evaluate_pretool(
        run, maintenance_git_add, maintenance_contract))
    ordinary_opaque_git_mutation_blocked = bool(evaluate_pretool(
        run, opaque_git_apply, contract)) and _maintenance_action(
            opaque_git_apply, contract=contract)
    ordinary_wrapped_repo_mutation_blocked = all(
        bool(evaluate_pretool(run, event, contract))
        and _maintenance_action(event, contract=contract)
        for event in opaque_git_wrapped
    )
    git_env_read_is_typed_repo_mutation = _maintenance_action(
        git_env_read, contract=contract)
    repo_words_in_data_do_not_mint_maintenance = all(
        not _maintenance_action(event, contract=contract)
        and not _opaque_repo_mutation_bash(event["tool_input"]["command"])
        for event in repo_words_as_data
    )
    safe_git_reads_are_not_maintenance = all(
        not _maintenance_action(event, contract=contract)
        for event in (maintenance_git_status, maintenance_git_diff)
    )
    malformed_maintenance_attempt_is_typed = bool(
        malformed_maintenance_contract.get("mode") == MAINTENANCE
        and _maintenance_action(
            outside_edit, contract=malformed_maintenance_contract)
        and not _maintenance_action({
            "tool_name": "Read",
            "tool_input": {"file_path": str(ROOT / "README.md")},
        }, contract=malformed_maintenance_contract)
    )
    malformed_maintenance_write_allowed = evaluate_pretool(
        run, critical_edit, malformed_maintenance_contract) == ""
    maintenance_run = root / "maintenance-run"
    (maintenance_run / "state").mkdir(parents=True)
    for name in ("target.md", "frontier.md", "evidence.md", "decisions.md", "review.md"):
        (maintenance_run / name).write_text(f"# {name}\n", encoding="utf-8")
    written_maintenance_contract = write_contract(maintenance_run, {
        "prompt": maintenance_prompt,
        "session_id": "maintenance-session",
        "transcript_path": str(root / "maintenance-transcript.jsonl"),
    })
    maintenance_run_status = json.loads(
        run_status_path(maintenance_run).read_text(encoding="utf-8"))
    receipt_paths_expected = ["docs/WORKFLOW.md", "tools/turn_contract.py"]
    receipt_base = {
        "session_id": "maintenance-session",
        "transcript_path": str(root / "maintenance-transcript.jsonl"),
        "tool_name": "MultiEdit",
        "tool_input": list_path_edit["tool_input"],
    }
    handle_event({
        **receipt_base,
        "hook_event_name": "PostToolUse",
        "tool_use_id": "maintenance-path-success",
        "tool_response": {"status": "ok"},
    }, maintenance_run)
    handle_event({
        **receipt_base,
        "hook_event_name": "PostToolUseFailure",
        "tool_use_id": "maintenance-path-failure",
        "tool_response": {"status": "failed"},
    }, maintenance_run)
    denial_receipt_run = root / "maintenance-denial-receipt-run"
    (denial_receipt_run / "state").mkdir(parents=True)
    for name in ("target.md", "frontier.md", "evidence.md", "decisions.md", "review.md"):
        (denial_receipt_run / name).write_text(
            f"# {name}\n", encoding="utf-8")
    write_contract(denial_receipt_run, {
        "prompt": "修复 Xunji turn contract",
        "session_id": "narrow-maintenance-session",
        "transcript_path": str(root / "narrow-maintenance-transcript.jsonl"),
    })
    receipt_denial = handle_event({
        **receipt_base,
        "hook_event_name": "PreToolUse",
        "session_id": "narrow-maintenance-session",
        "transcript_path": str(root / "narrow-maintenance-transcript.jsonl"),
        "tool_use_id": "maintenance-path-denial",
        "tool_input": forbidden_control_edit["tool_input"],
        "tool_name": "Edit",
    }, denial_receipt_run)
    malformed_receipt_run = root / "malformed-maintenance-receipt-run"
    (malformed_receipt_run / "state").mkdir(parents=True)
    for name in ("target.md", "frontier.md", "evidence.md", "decisions.md", "review.md"):
        (malformed_receipt_run / name).write_text(
            f"# {name}\n", encoding="utf-8")
    write_contract(malformed_receipt_run, {
        "prompt": "/xunji-maintenance 修复 turn contract",
        "session_id": "malformed-maintenance-session",
        "transcript_path": str(root / "malformed-maintenance-transcript.jsonl"),
    })
    malformed_receipt_result = handle_event({
        "hook_event_name": "PreToolUse",
        "session_id": "malformed-maintenance-session",
        "transcript_path": str(root / "malformed-maintenance-transcript.jsonl"),
        "tool_name": "Edit",
        "tool_use_id": "malformed-maintenance-denial",
        "tool_input": outside_edit["tool_input"],
    }, malformed_receipt_run)
    malformed_receipts = runtime_receipts.load_events(malformed_receipt_run)
    malformed_receipt = malformed_receipts[-1] if malformed_receipts else {}
    malformed_maintenance_receipt_is_typed = bool(
        malformed_receipt_result
        and malformed_receipt.get("maintenance_action") is True
        and malformed_receipt.get("maintenance_paths") == ["README.md"]
        and malformed_receipt.get("target_action") is False
        and load_contract(malformed_receipt_run).get("maintenance_blocked", {}).get(
            "paths") == ["README.md"]
    )
    receipt_records = {
        str(item.get("tool_use_id") or ""): item
        for receipt_run in (maintenance_run, denial_receipt_run)
        for item in runtime_receipts.load_events(receipt_run)
    }
    receipt_success_failure_paths_identical = all(
        receipt_records.get(tool_use_id, {}).get("maintenance_paths")
        == receipt_paths_expected
        for tool_use_id in (
            "maintenance-path-success", "maintenance-path-failure",
        )
    )
    receipt_denial_path_exact = (
        receipt_records.get("maintenance-path-denial", {}).get("maintenance_paths")
        == [".claude/xunji_active_run"]
    )
    pending_maintenance_dir = root / "pending-maintenance"
    pending_maintenance = write_pending_contract({
        "prompt": maintenance_prompt,
        "session_id": "pending-maintenance-session",
    }, pending_dir=pending_maintenance_dir)
    pending_maintenance_loaded = load_pending_contract(
        "pending-maintenance-session", pending_dir=pending_maintenance_dir)

    live_runs = root / "live-maintenance-runs"
    live_run = live_runs / "live_maintenance_20260101"
    (live_run / "state").mkdir(parents=True)
    for name in ("target.md", "frontier.md", "evidence.md", "decisions.md", "review.md"):
        (live_run / name).write_text(f"# {name}\n", encoding="utf-8")
    live_pointer = root / "live-maintenance-pointer"
    live_pointer.write_text(str(live_run.resolve()) + "\n", encoding="utf-8")
    live_transcript = root / "live-maintenance-transcript.jsonl"
    live_transcript.write_text(
        "live-authorized-edit\nlive-outside-edit\n",
        encoding="utf-8",
    )
    write_contract(live_run, {
        "session_id": "live-maintenance-session",
        "transcript_path": str(live_transcript),
        "prompt": f"/loop runs/{live_run.name}",
    })
    live_env = dict(os.environ)
    live_env.update({
        "XUNJI_RUNS_ROOT": str(live_runs),
        "XUNJI_ACTIVE_RUN_FILE": str(live_pointer),
        "XUNJI_PENDING_TURN_DIR": str(root / "live-pending"),
        "XUNJI_TRANSITION_CLAIMS_DIR": str(root / "live-claims"),
    })

    def live_hook(event: dict) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [sys.executable, str(Path(__file__).resolve())],
            input=json.dumps(event), text=True, capture_output=True,
            env=live_env, timeout=10,
        )

    live_submit = live_hook({
        "hook_event_name": "UserPromptSubmit",
        "session_id": "live-maintenance-session",
        "transcript_path": str(live_transcript),
        "prompt": maintenance_prompt,
    })
    live_authorized_edit = live_hook({
        "hook_event_name": "PreToolUse",
        "session_id": "live-maintenance-session",
        "transcript_path": str(live_transcript),
        "tool_name": "Edit", "tool_use_id": "live-authorized-edit",
        "tool_input": {
            "file_path": str(ROOT / "tools" / "turn_contract.py"),
            "old_string": "old", "new_string": "new",
        },
    })
    live_outside_edit = live_hook({
        "hook_event_name": "PreToolUse",
        "session_id": "live-maintenance-session",
        "transcript_path": str(live_transcript),
        "tool_name": "Edit", "tool_use_id": "live-outside-edit",
        "tool_input": {
            "file_path": str(ROOT / ".claude" / "xunji_active_run"),
            "old_string": "old", "new_string": "new",
        },
    })
    live_execute_submit = live_hook({
        "hook_event_name": "UserPromptSubmit",
        "session_id": "live-maintenance-session",
        "transcript_path": str(live_transcript),
        "prompt": f"/loop {live_run}",
    })
    live_critical_denial = live_hook({
        "hook_event_name": "PreToolUse",
        "session_id": "live-maintenance-session",
        "transcript_path": str(live_transcript),
        "tool_name": "Edit", "tool_use_id": "live-critical-deny",
        "tool_input": {
            "file_path": str(ROOT / "tools" / "turn_contract.py"),
            "old_string": "old", "new_string": "new",
        },
    })
    live_execute_contract = load_contract(
        live_run, session_id="live-maintenance-session")
    live_denials = runtime_receipts.unresolved_maintenance_blockers(
        live_run, session_id="live-maintenance-session",
        since=float(live_execute_contract.get("updated_at") or 0.0),
    )
    live_durable_denials = (
        runtime_receipts.unresolved_durable_maintenance_blockers(
            live_run, session_id="live-maintenance-session",
            since=float(live_execute_contract.get("updated_at") or 0.0),
        )
    )
    live_read_after_blocker = live_hook({
        "hook_event_name": "PreToolUse",
        "session_id": "live-maintenance-session",
        "transcript_path": str(live_transcript),
        "tool_name": "Read", "tool_use_id": "live-blocked-read",
        "tool_input": {"file_path": str(live_run / "frontier.md")},
    })
    live_task_update_after_blocker = live_hook({
        "hook_event_name": "PreToolUse",
        "session_id": "live-maintenance-session",
        "transcript_path": str(live_transcript),
        "tool_name": "TaskUpdate", "tool_use_id": "live-blocked-task-update",
        "tool_input": {"taskId": "1", "status": "completed"},
    })
    live_control_after_blocker = live_hook({
        "hook_event_name": "PreToolUse",
        "session_id": "live-maintenance-session",
        "transcript_path": str(live_transcript),
        "tool_name": "Bash", "tool_use_id": "live-blocked-control",
        "tool_input": {
            "command": (
                f"{sys.executable} {ROOT / 'tools' / 'workers.py'} "
                f"status {live_run}"
            ),
        },
    })
    live_agent_after_blocker = live_hook({
        "hook_event_name": "PreToolUse",
        "session_id": "live-maintenance-session",
        "transcript_path": str(live_transcript),
        "tool_name": "Agent", "tool_use_id": "live-blocked-agent",
        "tool_input": {
            "prompt": "XUNJI_ASSIGNMENT=A-fake XUNJI_FRONT=F-001",
            "subagent_type": "xunji-hunter",
        },
    })

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
    session_resume_restore_wired = any(
        str(group.get("matcher") or "") == "resume"
        and any(
            "tools/turn_contract.py" in str(hook.get("command") or "")
            and "--selftest" not in str(hook.get("command") or "")
            and float(hook.get("timeout") or 0) == 3.0
            for hook in group.get("hooks", []) if isinstance(hook, dict)
        )
        for group in hooks.get("SessionStart", []) if isinstance(group, dict)
    )
    session_end_cleanup_wired = any(
        "tools/turn_contract.py" in str(hook.get("command") or "")
        and float(hook.get("timeout") or 0) == 3.0
        for group in hooks.get("SessionEnd", []) if isinstance(group, dict)
        and not group.get("matcher")
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
    def receipt_matcher_tools(event_name: str) -> set[str]:
        found: set[str] = set()
        for group in hooks.get(event_name, []):
            if not isinstance(group, dict):
                continue
            if not any(
                    "tools/turn_contract.py" in str(hook.get("command") or "")
                    for hook in group.get("hooks", []) if isinstance(hook, dict)):
                continue
            found.update(
                token for token in str(group.get("matcher") or "").split("|") if token)
        return found
    maintenance_receipt_tools = {
        "Write", "Edit", "Update", "MultiEdit", "NotebookEdit",
    }
    iteration_plan_receipt_tools = {"TaskCreate", "TaskUpdate", "TodoWrite"}
    review_command = shlex.join((
        str(Path(sys.executable).resolve()),
        str((ROOT / "tools" / "peer_review.py").resolve()),
        str(run), "--backend", "claude",
    ))
    safe_review_event = {"tool_name": "Bash", "tool_input": {
        "command": review_command + " --out "
        + shlex.quote(str(run / "review-safe.md")),
    }}
    injected_review_redirect = {"tool_name": "Bash", "tool_input": {
        "command": review_command + " > /tmp/review$(id) 2>&1",
    }}
    critical_review_output = {"tool_name": "Bash", "tool_input": {
        "command": review_command + " --out "
        + shlex.quote(str(ROOT / "tools" / "turn_contract.py")),
    }}
    critical_review_reason = evaluate_pretool(
        run, critical_review_output, contract)
    archive_digest = "a" * 64
    transaction_aliases = [
        f"{run}/state/work_plan_transactions//{archive_digest}.json",
        f"{run}/state/work_plan_transactions/./{archive_digest}.json",
        f"{run}/state/work_plan_transactions/x/../{archive_digest}.json",
    ]
    run_relative_transaction = {
        "tool_name": "Write", "tool_input": {
            "file_path": f"state/work_plan_transactions/{archive_digest}.json",
            "content": "forged",
        },
    }
    structured_protected_events = [
        {"tool_name": "Write", "tool_input": {
            "file_path": transaction_aliases[0], "content": "forged"}},
        {"tool_name": "Edit", "tool_input": {
            "file_path": transaction_aliases[1],
            "old_string": "old", "new_string": "new"}},
        {"tool_name": "Update", "tool_input": {
            "target_path": transaction_aliases[2], "value": "forged"}},
        {"tool_name": "MultiEdit", "tool_input": {"edits": [{
            "file_path": str(
                run / "state" / "work_plans" / f"{archive_digest}.json"),
            "old_string": "old", "new_string": "new",
        }]}},
        {"tool_name": "NotebookEdit", "tool_input": {
            "notebook_path": str(
                run / "state" / "merge_drafts" / "A-hunter-001.json"),
            "new_source": "forged"}},
        {"tool_name": "Edit", "tool_input": {
            "destination_path": str(
                run / "state" / "merge_results" / "A-hunter-001"
                / "attempt.json"),
            "old_string": "old", "new_string": "new"}},
        {"tool_name": "Write", "tool_input": {
            "file_path": str(
                run / "state" / "assignment_cancellation_transaction.json"),
            "content": "forged"}},
        {"tool_name": "Edit", "tool_input": {
            "file_path": str(
                run / "state" / "assignment_cancellations"
                / f"{archive_digest}.json"),
            "old_string": "old", "new_string": "new"}},
    ]
    setup_source_protected_events = [
        {"tool_name": "Write", "tool_input": {
            "file_path": str(run / "sources" / "normalized.json"),
            "content": "forged"}},
        {"tool_name": "Edit", "tool_input": {
            "file_path": "sources/validator_receipt.json",
            "old_string": "old", "new_string": "new"}},
        {"tool_name": "MultiEdit", "tool_input": {"edits": [{
            "source_path": str(run / "sources" / "original" / "input.json"),
            "old_string": "old", "new_string": "new",
        }]}},
        {"tool_name": "NotebookEdit", "tool_input": {
            "notebook_path": str(
                run / "sources" / "normalizer_candidate.json"),
            "new_source": "forged"}},
        {"tool_name": "MultiEdit", "tool_input": {
            "file_paths": [
                str(run / "sources" / "nested" / "missing.json"),
                str(run / "ordinary" / "missing.md"),
            ],
            "edits": []}},
    ]
    (run / "state" / "work_plans").mkdir(parents=True, exist_ok=True)
    symlink_alias = root / "protected-plan-alias"
    symlink_alias.symlink_to(run / "state" / "work_plans", target_is_directory=True)
    safe_escape = root / "safe-escape-target"
    safe_escape.mkdir()
    protected_escape = run / "state" / "work_plans" / "escape"
    protected_escape.symlink_to(safe_escape, target_is_directory=True)
    symlink_alias_events = [
        {"tool_name": "Write", "tool_input": {
            "file_path": str(symlink_alias / f"{archive_digest}.json"),
            "content": "forged",
        }},
        {"tool_name": "Write", "tool_input": {
            "file_path": str(protected_escape / "ordinary.json"),
            "content": "forged",
        }},
    ]
    lifecycle_failure_code, lifecycle_failure_diagnostic = (
        _runtime_hook_failure_diagnostic(
            {"hook_event_name": "SubagentStop"}, RuntimeError("opaque")))
    ordinary_failure_code, ordinary_failure_diagnostic = (
        _runtime_hook_failure_diagnostic(
            {"hook_event_name": "UserPromptSubmit"}, RuntimeError("opaque")))
    budget_actor_fixture = {
        "kind": "assignment",
        "state": "running",
        "lane_id": "L-BUDGET",
        "plan_digest": "b" * 64,
    }

    def budget_event_fixture(tool_id: str) -> dict:
        return {
            "hook_event_name": "PreToolUse",
            "session_id": "budget-session",
            "transcript_path": str(root / "budget-session.jsonl"),
            "agent_id": "budget-child",
            "tool_name": "Read",
            "tool_use_id": tool_id,
            "tool_input": {"file_path": "/tmp/budget-fixture"},
        }

    budget_near_event = budget_event_fixture("budget-near")
    # Nested Agent is guaranteed to hit a later policy denial; its attempted
    # call still consumes the already-frozen plan-bound budget.
    budget_near_event["tool_name"] = "Agent"
    budget_near_event["tool_input"] = {"prompt": "not-authorizing"}
    with mock.patch.object(
            runtime_receipts, "agent_actor",
            return_value=budget_actor_fixture), \
            mock.patch.object(
                runtime_receipts, "claim_agent_tool_call",
                return_value={
                    "agent_tool_call_ordinal": 5,
                    "agent_tool_call_limit": 6,
                    "agent_tool_call_admitted": True,
                    "receipt_hash": "a" * 64,
                }) as near_claim:
        budget_near_reason = _claim_plan_bound_child_tool_call(
            run, budget_near_event)
        budget_near_context = _plan_bound_child_budget_context(
            budget_near_event)
        # This later policy denial cannot refund the already-completed claim.
        budget_later_policy_denial = evaluate_pretool(
            run, budget_near_event, {})
        budget_policy_denial_still_counted = bool(
            near_claim.call_count == 1
            and budget_near_event.get("_xunji_agent_tool_call_claim", {}).get(
                "ordinal") == 5
            and budget_later_policy_denial)

    budget_last_event = budget_event_fixture("budget-last")
    with mock.patch.object(
            runtime_receipts, "agent_actor",
            return_value=budget_actor_fixture), \
            mock.patch.object(
                runtime_receipts, "claim_agent_tool_call",
                return_value={
                    "agent_tool_call_ordinal": 6,
                    "agent_tool_call_limit": 6,
                    "agent_tool_call_admitted": True,
                    "receipt_hash": "b" * 64,
                }):
        budget_last_reason = _claim_plan_bound_child_tool_call(
            run, budget_last_event)
        budget_last_context = _plan_bound_child_budget_context(
            budget_last_event)

    budget_over_event = budget_event_fixture("budget-over")
    with mock.patch.object(
            runtime_receipts, "agent_actor",
            return_value=budget_actor_fixture), \
            mock.patch.object(
                runtime_receipts, "claim_agent_tool_call",
                return_value={
                    "agent_tool_call_ordinal": 7,
                    "agent_tool_call_limit": 6,
                    "agent_tool_call_admitted": False,
                    "receipt_hash": "c" * 64,
                }):
        budget_over_reason = _claim_plan_bound_child_tool_call(
            run, budget_over_event)

    budget_conflict_event = budget_event_fixture("budget-conflict")
    with mock.patch.object(
            runtime_receipts, "agent_actor",
            return_value=budget_actor_fixture), \
            mock.patch.object(
                runtime_receipts, "claim_agent_tool_call",
                side_effect=RuntimeError("AGENT_TOOL_CALL_IDENTITY_CONFLICT")):
        budget_conflict_reason = _claim_plan_bound_child_tool_call(
            run, budget_conflict_event)

    request_last_event = budget_event_fixture("request-last")
    request_last_event.update({
        "tool_name": "WebFetch",
        "tool_input": {"url": "http://127.0.0.1:18765/", "prompt": "GET"},
    })
    with mock.patch.object(
            runtime_receipts, "agent_actor",
            return_value=budget_actor_fixture), \
            mock.patch.object(
                runtime_receipts, "claim_agent_tool_call",
                return_value={
                    "agent_tool_call_ordinal": 3,
                    "agent_tool_call_limit": 6,
                    "agent_tool_call_admitted": True,
                    "agent_request_action": True,
                    "agent_request_ordinal": 2,
                    "assignment_request_budget": 2,
                    "agent_request_admitted": True,
                    "receipt_hash": "d" * 64,
                }):
        request_last_reason = _claim_plan_bound_child_tool_call(
            run, request_last_event)
        request_last_context = _plan_bound_child_budget_context(
            request_last_event)

    request_over_event = budget_event_fixture("request-over")
    request_over_event.update({
        "tool_name": "WebFetch",
        "tool_input": {"url": "http://127.0.0.1:18765/health", "prompt": "GET"},
    })
    with mock.patch.object(
            runtime_receipts, "agent_actor",
            return_value=budget_actor_fixture), \
            mock.patch.object(
                runtime_receipts, "claim_agent_tool_call",
                return_value={
                    "agent_tool_call_ordinal": 4,
                    "agent_tool_call_limit": 6,
                    "agent_tool_call_admitted": True,
                    "agent_request_action": True,
                    "agent_request_ordinal": 3,
                    "assignment_request_budget": 2,
                    "agent_request_admitted": False,
                    "receipt_hash": "e" * 64,
                }):
        request_over_reason = _claim_plan_bound_child_tool_call(
            run, request_over_event)

    checks = [
        ("plan-bound child attempts are claimed before a later policy denial",
         budget_near_reason == "" and budget_policy_denial_still_counted),
        ("near-cap and final-call PreToolUse context instruct an immediate return",
         isinstance(budget_near_context, dict)
         and "只剩 1 次额度" in json.dumps(budget_near_context, ensure_ascii=False)
         and budget_last_reason == ""
         and isinstance(budget_last_context, dict)
         and "最后一次允许" in json.dumps(budget_last_context, ensure_ascii=False)),
        ("the seventh child call has one stable hard-limit denial code",
         E_AGENT_TOOL_CALL_LIMIT_EXCEEDED in budget_over_reason
         and _decision_metadata(budget_over_reason, budget_over_event).get(
             "xunji_decision_class") == "agent_tool_budget"),
        ("child tool-use identity conflicts fail closed with a stable code",
         E_AGENT_TOOL_CALL_IDENTITY_CONFLICT in budget_conflict_reason),
        ("target request budget exhausts with context and denies the next call",
         request_last_reason == ""
         and request_last_event.get("xunji_agent_request_action") is True
         and isinstance(request_last_context, dict)
         and "耗尽当前 lane 预算" in json.dumps(
             request_last_context, ensure_ascii=False)
         and E_AGENT_REQUEST_BUDGET_EXCEEDED in request_over_reason
         and _decision_metadata(request_over_reason, request_over_event).get(
             "xunji_decision_class") == "agent_request_budget"),
        ("explain overrides action words", explain == EXPLAIN),
        ("history/audit prompt without execute verb is read-only", history_only == EXPLAIN),
        ("ambiguous active-run prompt defaults read-only", ambiguous == EXPLAIN),
        ("operator stop maps to pause", pause == PAUSE),
        ("repair request maps to execute", execute == EXECUTE),
        ("unrecognized English execution wording defaults read-only", indirect_english == EXPLAIN),
        ("no-active-run ordinary question stays outside run execution", no_run_question == NORMAL),
        ("active-run informational question stays read-only", active_run_question == EXPLAIN),
        ("explicit active-run switch remains executable", active_run_switch == EXECUTE),
        ("scoped safety restrictions do not revoke an exact loop directive",
         restricted_loop_contract.get("mode") == EXECUTE
         and restricted_loop_contract.get("lifecycle_operation") == "resume"
         and _explicit_pointer_rebind(restricted_loop_contract, run)),
        ("an explicit lifecycle denial still revokes a conflicting loop directive",
         denied_loop_contract.get("mode") == EXPLAIN
         and denied_loop_contract.get("lifecycle_operation") == "none"),
        ("runtime lifecycle hook exceptions surface a stable fail-closed diagnostic",
         lifecycle_failure_code == 2
         and lifecycle_failure_diagnostic.startswith(
             f"[{E_RUNTIME_RECEIPT_HOOK_FAILED}] SubagentStop")
         and "opaque" not in lifecycle_failure_diagnostic
         and ordinary_failure_code == 0
         and ordinary_failure_diagnostic == ""),
        ("ordinary operator wording derives a distinct maintenance turn mode",
         maintenance_contract.get("mode") == MAINTENANCE
         and maintenance_contract.get("maintenance_intent") == "operator_prompt"
         and len(str(maintenance_contract.get("prompt_sha256") or "")) == 64),
        ("source text after the first operator instruction cannot mint maintenance authority",
         quoted_source_contract.get("mode") == EXECUTE
         and not quoted_source_contract.get("maintenance_authorized_paths")),
        ("legacy maintenance alias needs no scope or reason ceremony",
         malformed_maintenance_contract.get("mode") == MAINTENANCE
         and not malformed_maintenance_contract.get("maintenance_parse_error")),
        ("trusted single-operator maintenance uses a local correlation fallback",
         missing_session_maintenance_contract.get("mode") == MAINTENANCE
         and missing_session_maintenance_contract.get("session_id")
         == SINGLE_OPERATOR_SESSION_BINDING
         and missing_session_maintenance_contract.get("session_binding_kind")
         == "single_operator"),
        ("explicit loop intent outranks a framework recovery clause",
         operator_e2e_loop_contract.get("mode") == EXECUTE
         and operator_e2e_loop_contract.get("loop_requested") is True
         and operator_e2e_loop_contract.get("lifecycle_operation") == "source"
         and not operator_e2e_loop_contract.get("maintenance_intent")),
        ("operator offline intent freezes target and named web-tool constraints",
         operator_offline_loop_contract.get("mode") == EXECUTE
         and operator_offline_loop_contract.get("target_egress_denied") is True
         and operator_offline_loop_contract.get("web_tools_denied") is True
         and "XUNJI_E_OPERATOR_EFFECT_DENIED" in offline_target_reason
         and "XUNJI_E_OPERATOR_EFFECT_DENIED" in offline_web_reason
         and "XUNJI_E_OPERATOR_EFFECT_DENIED" in offline_browser_reason
         and "XUNJI_E_OPERATOR_EFFECT_DENIED" in offline_agent_reason
         and offline_read_allowed),
        ("proxy discipline plus positive target intent does not mint an offline denial",
         positive_target_loop_contract.get("target_egress_denied") is False
         and positive_target_loop_contract.get("web_tools_denied") is False),
        ("ordinary live loop cannot edit a safety-critical path",
         ordinary_critical_edit_blocked),
        ("maintenance intent allows a typed critical-path edit",
         authorized_critical_edit_allowed),
        ("maintenance intent allows an adjacent documentation edit",
         authorized_adjacent_doc_allowed),
        ("maintenance intent allows repository-local paths without predeclaration",
         maintenance_outside_edit_allowed),
        ("list-valued nested paths are authorized as one complete set",
         maintenance_list_paths_allowed),
        ("one typed edit may cover multiple repository-local paths",
         maintenance_mixed_list_allowed),
        ("empty, glob, escaping, and non-string path members fail closed",
         maintenance_invalid_list_blocked),
        ("maintenance receipts bind the exact typed effect paths",
         bool(receipt_denial)
         and receipt_success_failure_paths_identical
         and receipt_denial_path_exact
         and receipt_records.get(
             "maintenance-path-success", {}).get("success") is True
         and receipt_records.get(
             "maintenance-path-failure", {}).get("success") is False
         and receipt_records.get(
             "maintenance-path-denial", {}).get("decision") == "deny"),
        ("authorized scope is never reported as an untouched receipt path",
         _maintenance_receipt_paths(
             adjacent_doc_edit, maintenance_contract) == ["docs/WORKFLOW.md"]),
        ("maintenance turn blocks target actions and Cron",
         maintenance_target_blocked and maintenance_cron_blocked
         and maintenance_agent_blocked and maintenance_mcp_blocked),
        ("maintenance turn forbids Bash source mutation",
         maintenance_shell_write_blocked),
        ("maintenance turn allows read-only Bash and direct py_compile",
         maintenance_read_allowed and maintenance_compile_allowed
         and maintenance_git_read_allowed and maintenance_git_diff_allowed
         and maintenance_git_diff_unsafe_blocked and maintenance_git_env_blocked),
        ("maintenance turn denies git index/worktree mutation",
         maintenance_git_add_blocked),
        ("ordinary live loop denies opaque git patch mutation",
         ordinary_opaque_git_mutation_blocked
         and ordinary_wrapped_repo_mutation_blocked),
        ("Git env helpers remain typed repo mutation while Git words in data do not",
         git_env_read_is_typed_repo_mutation
         and repo_words_in_data_do_not_mint_maintenance
         and safe_git_reads_are_not_maintenance),
        ("ordinary live loop denies env-injected reads and unknown interpreters",
         ordinary_git_env_blocked and ordinary_encoded_write_blocked
         and ordinary_pythonpath_target_blocked),
        ("legacy maintenance alias permits typed local writes without options",
         malformed_maintenance_write_allowed
         and malformed_maintenance_attempt_is_typed
         and evaluate_pretool(run, {"tool_name": "Read", "tool_input": {
             "file_path": str(ROOT / "tools" / "turn_contract.py")}},
             malformed_maintenance_contract) == ""),
        ("maintenance contract freezes the live run in derived run status",
         written_maintenance_contract.get("mode") == MAINTENANCE
         and maintenance_run_status.get("status") == "maintenance"),
        ("no-active-run maintenance authority stays session-bound and short-lived",
         pending_maintenance.get("mode") == MAINTENANCE
         and pending_maintenance_loaded.get("session_id") == "pending-maintenance-session"),
        ("live hook pipeline binds maintenance mode and typed local Edit",
         live_submit.returncode == 0
         and "MAINTENANCE" in (live_submit.stdout or "")
         and live_authorized_edit.returncode == 0
         and not (live_authorized_edit.stdout or "").strip()),
        ("live hook pipeline denies direct control-state Edit",
         '"permissionDecision": "deny"' in (live_outside_edit.stdout or "")
         and "active-run" in (live_outside_edit.stdout or "")),
        ("new execute turn revokes maintenance scope and records critical denial",
         live_execute_submit.returncode == 0
         and '"permissionDecision": "deny"' in (live_critical_denial.stdout or "")
         and not live_denials
         and len(live_durable_denials) == 1
         and live_durable_denials[0].get("maintenance_paths")
         == ["tools/turn_contract.py"]),
        ("current-turn maintenance blocker allows deterministic inspection only",
         live_read_after_blocker.returncode == 0
         and not (live_read_after_blocker.stdout or "").strip()
         and live_task_update_after_blocker.returncode == 0
         and not (live_task_update_after_blocker.stdout or "").strip()),
        ("a benign maintenance denial does not sticky-freeze the operator turn",
         "XUNJI_E_MAINTENANCE_BLOCKED" not in (live_control_after_blocker.stdout or "")
         and "XUNJI_E_MAINTENANCE_BLOCKED" not in (live_agent_after_blocker.stdout or "")
         and not live_denials
         and len(live_durable_denials) == 1),
        ("negated direct-egress phrases never grant approval",
         not negated_direct_cn["direct_egress_approved"]
         and not negated_direct_en["direct_egress_approved"]),
        ("explicit direct-egress phrase grants current-turn approval",
         explicit_direct["direct_egress_approved"]),
        ("exact scope directive binds run/assets and execute mode",
         scope_contract.get("mode") == EXECUTE
         and scope_contract.get("scope_admission_run") == "pilot_20260715"
         and scope_contract.get("scope_admission_assets")
         == ["one.example.test", "two.example.test"]),
        ("scope admission turn is zero-probe and blocks target actions",
         scope_turn_target_blocked),
        ("malformed scope directive permits no write authority",
         malformed_scope_contract.get("mode") == EXPLAIN
         and malformed_scope_write_blocked),
        ("target action blocked before real fanout", before_fanout),
        ("run-model failure produces a deterministic fail-closed contract state",
         bool(summary_failure_signature)
         and "canonical frontier" in summary_failure_reason),
        ("raw target curl is denied by proxy egress gate", raw_curl_blocked),
        ("raw target requests code is denied by proxy egress gate", raw_requests_blocked),
        ("target WebFetch is denied because it cannot attest engagement proxy",
         target_webfetch_blocked),
        ("unknown-host WebFetch cannot bypass the engagement proxy gate",
         unknown_webfetch_blocked),
        ("proxy-aware guarded target tool is allowed", guarded_probe_allowed),
        ("source/AI review-scope asset cannot become a target capability",
         review_scope_target_blocked),
        ("explicit out-of-scope asset stays blocked", out_scope_target_blocked),
        ("candidate in-scope hand edit without committed operator receipt stays blocked",
         forged_candidate_in_scope_blocked),
        ("explicit in-scope ledger asset remains executable",
         explicit_in_scope_target_allowed),
        ("proxy-aware tool rejects destinations absent from the asset ledger",
         unknown_guarded_probe_blocked),
        ("direct-egress opt-out requires current operator approval",
         direct_without_operator_blocked and direct_env_without_operator_blocked
         and quoted_direct_without_operator_blocked),
        ("current operator may explicitly approve direct egress",
         direct_with_operator_allowed and quoted_direct_with_operator_allowed),
        ("non-Bash target network tool cannot bypass proxy attestation",
         nonbash_target_tool_blocked),
        ("unassigned coverage asset blocks target action", unassigned_asset_blocked),
        ("corrupt coverage fails closed instead of disabling the asset gate",
         corrupt_coverage_fails_closed),
        ("valid nested coverage still enforces hosts when root coverage is corrupt",
         nested_fallback_host_is_enforced),
        ("continue prompts preserve a material fanout epoch across sessions",
         fanout_epoch_persists),
        ("material coverage-debt change resets fanout epoch",
         material_debt_change_resets_epoch and changed_signature_invalidates_pair),
        ("asset-bound Agent prompt is accepted", asset_bound_prompt_allowed),
        ("Agent prompt with mismatched asset package is denied",
         mismatched_asset_prompt_blocked),
        ("bound child Agent may execute its own target lane", child_lane_allowed),
        ("child Agent cannot escape its assigned asset package", child_asset_escape_blocked),
        ("child Agent cannot create nested Agent fanout", nested_agent_blocked),
        ("Root is not deadlocked while async Agents are still running",
         root_allowed_while_agents_running),
        ("Root disposition gate starts only after real SubagentStop",
         root_blocked_after_real_return),
        ("running child is not blocked by a returned peer's disposition debt",
         running_peer_not_blocked_by_returned_peer),
        ("legacy empty-asset child cannot execute target actions",
         legacy_empty_asset_child_blocked),
        ("completion-review child can read frozen run state",
         completion_child_read_allowed),
        ("completion-review child cannot mutate run state",
         completion_child_write_blocked),
        ("synchronous child is authorized from transcript-bound SubagentStart",
         synchronous_child_allowed_before_parent_post),
        ("synchronous child loses authority at SubagentStop before parent PostToolUse",
         synchronous_child_blocked_after_stop),
        ("Start -> Stop -> synchronous Post projects one causal returned attempt",
         len(sync_actor_attempts) == 1
         and sync_actor_attempts[0].get("state") == "returned"
         and sync_actor_attempts[0].get("agent_id") == "sync-actor-child"),
        ("encoded network command blocked before fanout", encoded_before_fanout),
        ("renamed unknown script blocked before fanout", renamed_before_fanout),
        ("workers control command allowed before fanout", workers_allowed_before_fanout),
        ("workers --asset control is not misclassified as target egress",
         workers_asset_control_allowed),
        ("quoted disposition punctuation remains valid control data",
         workers_quoted_note_allowed),
        ("registered owner notes may name protected records as inert data",
         workers_protected_name_note_allowed),
        ("all quoted shell punctuation remains inert control data",
         quoted_punctuation_allowed),
        ("single-quoted substitutions remain literal control data",
         single_quoted_literals_allowed),
        ("backslash-escaped substitution remains literal control data",
         escaped_substitution_literal_allowed),
        ("ANSI-C shell expansion is not accepted as exact control argv",
         ansi_c_literal_rejected),
        ("trailing shell comments are not accepted as exact control argv",
         trailing_comment_control_rejected),
        ("unquoted shell chaining cannot impersonate a control command",
         workers_shell_chain_rejected),
        ("adversarial shell syntax fails closed through evaluate_pretool",
         adversarial_controls_fail_closed),
        ("documented bare python3 survives hook and Bash PATH differences",
         documented_python3_is_trusted_across_hook_path),
        ("unresolved micro-version Python token cannot impersonate control",
         unavailable_micro_python_rejected),
        ("new-run setup command is lifecycle control before old-run fanout",
         setup_allowed_before_fanout),
        ("benign direct-egress reminders normalize into local bootstrap control",
         benign_setup_direct_egress_prefixes_normalize),
        ("setup --classify requires a current explicit non-negated opt-in",
         classify_requires_explicit_opt_in),
        ("classify opt-in uses the full unquoted prompt rather than its log excerpt",
         full_prompt_classify_authority),
        ("explicit setup slug authority is hashed from full unquoted prompt text",
         structured_slug_authority),
        ("prompt-named --source URL is local lifecycle control",
         source_setup_allowed and not _is_target_action(source_control)),
        ("source authority persists only as a hash with a redacted prompt display",
         source_contract_redacted),
        ("explicit /loop URL derives a new-run transition without extra wording",
         loop_url_derives_transition),
        ("hashed current-prompt source authority permits the exact clean argv",
         hashed_source_setup_allowed),
        ("same basename with a different query cannot reuse source authority",
         wrong_query_source_blocked),
        ("explicit /loop binds only its source token, not other mentioned URLs",
         unselected_prompt_url_blocked),
        ("natural-language setup authorizes one unique URL source",
         natural_single_url_authorized),
        ("natural-language setup with multiple URLs fails closed as ambiguous",
         natural_multi_url_fails_closed),
        ("negated and interrogative create intents remain read-only",
         denied_and_question_intents_are_read_only),
        ("negated resume intent remains read-only", negated_resume_is_read_only),
        ("quoted/code-fenced /loop text cannot mint lifecycle authority",
         quoted_loop_data_cannot_mint_authority),
        ("indented /loop plus explicit analysis remains read-only",
         indented_analysis_remains_read_only),
        ("leading whitespace is normalized without changing source authority",
         leading_whitespace_operator_intent_normalized),
        ("top-level English imperative still authorizes its unique source",
         english_imperative_source_authorized),
        ("natural-language trailing URL punctuation fails closed",
         natural_trailing_punctuation_fails_closed),
        ("a file inside the current run routes as resume without new-run transition",
         run_file_source_resumes_current_run),
        ("setup_run --target accepts only the selected source",
         setup_selected_target_allowed and setup_unselected_target_blocked),
        ("natural-language unique URL permits its deterministic setup target",
         natural_single_setup_target_allowed),
        ("natural-language multi-URL authority blocks selected, mentioned, and arbitrary setup targets",
         natural_multi_setup_targets_blocked),
        ("source turn cannot substitute an unrelated legacy recon",
         unrelated_legacy_recon_blocked),
        ("source turn cannot substitute a resume operation",
         source_turn_resume_blocked),
        ("resume turn binds the exact named run operation",
         exact_resume_operation_allowed and unrelated_resume_operation_blocked),
        ("output-only lifecycle wrappers return a stable non-maintenance shape denial",
         shape_denial_classified),
        ("shape denial receipt is structured, redacted, and non-maintenance",
         shape_receipt_is_nonmaintenance),
        ("clean exact owner status commands remain registered local reads",
         owner_read_clean_allowed),
        ("owner status output wrappers are retryable command-shape denials",
         owner_wrappers_are_retryable_shape_denials
         and owner_output_filter_is_shape_denial),
        ("owner status shape receipt is structured and non-maintenance",
         owner_shape_receipt_is_nonmaintenance),
        ("registered capability chains are denied without maintenance truth",
         registered_chains_are_retryable_nonmaintenance_denials),
        ("every denied registered-chain segment remains an exact individual retry",
         registered_chain_segments_retry_individually),
        ("target and model registered chains retain typed non-maintenance denials",
         effectful_registered_chains_keep_typed_denial),
        ("chain effect set is risk ordered while duplicate target identities remain",
         effect_set_is_stable_and_target_segments_are_distinct),
        ("invalid-argv registered chains are retryable nonmaintenance shape denials",
         invalid_registered_chains_are_nonmaintenance_shape),
        ("registered chain denial receipts create no maintenance blocker",
         registered_chain_receipts_do_not_mint_debt),
        ("effectful registered-chain receipts preserve effect without maintenance",
         effectful_chain_receipts_preserve_effect_without_maintenance),
        ("invalid registered-chain receipts cannot mint maintenance debt",
         invalid_chain_receipts_are_nonmaintenance),
        ("env, critical-data, and repository chains retain maintenance debt",
         unsafe_chain_receipts_preserve_conservative_maintenance),
        ("exact target segment retry resolves registered-chain target debt",
         effectful_chain_target_debt_resolves_by_exact_segment),
        ("opaque or mutating chain segments retain the normal fail-closed path",
         opaque_or_mutating_chains_stay_fail_closed),
        ("invalid owner argv is retryable while true file redirects stay maintenance-class",
         unknown_and_write_wrappers_stay_fail_closed),
        ("real incomplete work-plan argv and valid control failure receipts stay non-maintenance",
         invalid_argv_and_control_failure_receipts_are_nonmaintenance),
        ("common read chains execute without maintenance or target debt",
         generic_read_chain_is_allowed_without_maintenance),
        ("true lifecycle output writes remain maintenance-class mutations",
         true_redirect_stays_maintenance),
        ("--source URL absent from the operator prompt is blocked",
         unrelated_source_setup_blocked),
        ("--source basename collision is not operator authority",
         basename_collision_source_blocked),
        ("prepared setup transaction blocks target work", prepared_target_blocked),
        ("prepared setup transaction blocks CronCreate", prepared_cron_blocked),
        ("prepared setup transaction remains readable", prepared_read_allowed),
        ("prepared setup transaction permits explicit recovery lifecycle",
         prepared_recovery_allowed),
        ("setup cannot be used without current operator run-transition intent",
         setup_without_operator_blocked),
        ("documented loop journal command is control before fanout",
         journal_allowed_before_fanout),
        ("clear-active is denied without operator wording", clear_without_operator_blocked),
        ("operator text cannot authorize active-pointer clearing",
         clear_with_operator_blocked),
        ("English operator text cannot authorize active-pointer clearing",
         clear_with_english_operator_blocked),
        ("wrapped clear-active remains a fail-closed lifecycle command",
         wrapped_clear_active_blocked),
        ("set-active cannot switch to a run absent from the operator prompt",
         unrelated_set_active_blocked),
        ("prompt-named set-active is allowed", named_set_active_allowed),
        ("set-active binds an exact hashed run name without prefix or URL-path authority",
         exact_set_active_authority
         and set_active_prefix_collision_blocked
         and set_active_url_path_collision_blocked),
        ("prompt-named resume is allowed across runs", named_resume_allowed),
        ("setup --classify keeps the following slug positional",
         classify_setup_target == "classified_20260101"),
        ("invalid normalizer flags, empty setup source, and invalid dates fail closed",
         invalid_lifecycle_args_fail_closed),
        ("lifecycle commands reject tool-level PATH/environment overrides",
         lifecycle_env_override_blocked),
        ("setup --target URL is consumed without replacing the run slug",
         url_setup_target == "url-target_20260101"),
        ("loop bootstrap --source URL derives the exact target run",
         routed_url_target == f"new-source-example_{datetime.now().strftime('%Y%m%d')}"),
        ("unknown lifecycle options fail closed instead of rebinding the slug",
         unknown_option_target == ""),
        ("loop bootstrap resume extracts the exact target run",
         direct_resume_target == "resume_20260101"),
        ("statusline set-active extracts the exact target run",
         direct_set_active_target == "selected_20260101"),
        ("lifecycle claims distinguish adapter and semantic option effects",
         lifecycle_effect_options_are_exact),
        ("typed capability effects separate target, control, local verify, and model egress",
         capability_effect_classification_is_exact),
        ("anti-drift and runtime-receipt capabilities bind exact argv and active run",
         typed_local_capability_shapes_are_exact),
        ("capability scope and output resources bind to the active run",
         capability_scope_and_output_bindings_fail_closed),
        ("unknown argv for a registered script remains target-capable and non-control",
         invalid_registered_argv_fails_closed),
        ("clean invalid registered argv is a non-authorizing retryable shape denial",
         clean_invalid_registered_argv_is_retryable_shape),
        ("allowed probe env plus invalid argv remains a retryable shape denial",
         invalid_probe_env_is_retryable_shape),
        ("arbitrary python-c access to a critical manifest remains maintenance-class",
         opaque_python_manifest_read_stays_maintenance),
        ("out-of-tree workers.py cannot impersonate control plane",
         fake_workers_blocked_before_fanout),
        ("read-only helper allowlist rejects path-spelled impersonators",
         readonly_helper_path_spoofs_rejected),
        ("ripgrep read helper rejects external preprocessor options",
         rg_preprocessors_rejected and plain_rg_remains_read_only),
        ("quoted punctuation and stderr-to-devnull stay read-only",
         quoted_punctuation_and_devnull_remain_read_only),
        ("exact shasum file reads never mint framework maintenance debt",
         exact_shasum_is_read_only_not_maintenance),
        ("narrow sed print remains read-only before fanout", safe_sed_allowed_before_fanout),
        ("sed in-place mutation blocked before fanout", sed_in_place_blocked),
        ("sed write command blocked before fanout", sed_write_blocked),
        ("find file-output action blocked before fanout", find_file_output_blocked),
        ("protected control-plane denial is not a target-result action",
         protected_denial_not_target),
        ("destination-free local shell denials do not mint target-result debt",
         denial_receipt_effects_are_narrow),
        ("Root canonical promotion waits for reviewed assignment settlement",
         canonical_before_finish_blocked and canonical_after_finish_unblocked),
        ("direct active-run pointer Write is blocked", pointer_write_blocked),
        ("direct coverage ledger Write is blocked", coverage_write_blocked),
        ("controlled coverage sync remains allowed", coverage_sync_control_allowed),
        ("active-run pointer shell denial is local, not a target result",
         pointer_shell_is_local),
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
        ("active-run transition preserves the current contract and run status",
         transfer_preserves_contract),
        ("serial override requires current operator prompt", override.get("fanout_override") is True),
        ("internal task notification cannot replace operator turn contract",
         internal_notification_preserves_contract),
        ("Agent without binding tokens blocked", agent_bad_blocked),
        ("bound Agent call allowed", agent_good_allowed),
        ("completion Agent without full checklist is blocked",
         completion_bad_blocked),
        ("completion Agent with evidence hash and checklist is allowed",
         completion_good_allowed),
        ("completion Agent rejects missing, legacy, whitespace, and role-swapped types",
         completion_wrong_types_blocked),
        ("completion Agent rejects stale hash and mixed assignment envelopes",
         completion_stale_and_mixed_blocked),
        ("completion marker matching is token-exact rather than substring-based",
         completion_impostors_blocked),
        ("completion prompt requires current committed S3 plan provenance",
         unavailable_completion_prompts_are_empty),
        ("missing, S1, S2, stale, prepared, and corrupt plans block completion launch",
         unavailable_completion_attempts_blocked),
        ("blocked completion PreToolUse attempts append no runtime facts",
         unavailable_completion_pretool_is_read_only),
        ("explain mode blocks Bash", bool(evaluate_pretool(run, target_event, {"mode": EXPLAIN}))),
        ("pause mode allows CronList", evaluate_pretool(run, {"tool_name": "CronList", "tool_input": {}}, {"mode": PAUSE}) == ""),
        ("CronCreate requires current-turn CronList", cron_before_list),
        ("CronCreate allowed after current-turn empty CronList", cron_after_list),
        ("new-run /loop cannot schedule the origin run before transition",
         new_run_cron_blocked_until_transition),
        ("pending new-run /loop blocks task planning on the origin run",
         pending_plan_requires_setup),
        ("pending new-run /loop blocks Agent launch on the origin run",
         pending_agent_requires_setup),
        ("post-bind work requires a committed transaction/contract binding",
         uncommitted_transition_blocked),
        ("new-run task planning waits for current-turn CronCreate",
         plan_before_cron_blocked),
        ("new-run Agent launch waits for current-turn CronCreate",
         agent_before_cron_blocked),
        ("a committed no-active-run transition reaches the bound-run Cron gate",
         no_active_transition_reaches_cron_gate),
        ("Agent launch waits for a post-Cron iteration plan receipt",
         agent_before_plan_blocked),
        ("TaskCreate is allowed after the bound run Cron receipt",
         plan_allowed_after_cron),
        ("post-Cron task receipt unlocks the lifecycle gate",
         plan_unlocks_lifecycle_gate),
        ("Task receipt alone does not replace xunji.work-plan.v1",
         work_plan_missing_after_task and model_egress_work_plan_missing
         and work_plan_route_is_explicit),
        ("serial work plan permits its uniquely bound Agent",
         planned_agent_allowed),
        ("plan-bound Agent prompt rejects suffix, prefix, whitespace, and reorder drift",
         altered_plan_prompts_blocked),
        ("appended-prompt canary persists the stable delegation denial code",
         canary_denial_persists_delegation_code),
        ("Agent description cannot replace an exact tool_input.prompt",
         description_only_plan_prompt_blocked),
        ("plan-bound Agent rejects a mismatched plan digest",
         mismatched_plan_agent_blocked),
        ("real PreToolUse admits only the unique stale-result Reviewer",
         stale_reviewer_pretool_allowed
         and stale_old_execution_pretool_blocked
         and stale_reviewer_without_digest_blocked
         and stale_reviewer_without_marker_blocked
         and stale_reviewer_appended_context_blocked
         and stale_equal_digest_decoy_exists
         and stale_reviewer_wrong_equal_digest_assignment_blocked
         and stale_reviewer_exact_target_frozen
         and stale_reviewer_batch.get("input_freshness")
            == "stale-settlement-only"
         and stale_review_plan.get("plan_digest")
            == stale_reviewer_batch.get("plan_digest")),
        ("plan-bound child may read its lane context but cannot escape its effect",
         planned_child_read_allowed and planned_child_effect_escape_blocked),
        ("context tamper before parent launch is denied without a fake Agent attempt",
         parent_artifact_tamper_fails_before_launch),
        ("artifact drift between parent Post and SubagentStart appends no Start",
         start_race_rejected_without_mutation
         and start_race_recovers_after_exact_restore),
        ("Start-frozen prompt hash rejects a coordinated mutable child rebind",
         child_rebind_start_hash_blocks_mutable_rebind),
        ("serial Agent mode keeps Root coordinator-only for target and model effects",
         serial_root_target_blocked and serial_root_model_egress_blocked),
        ("ROOT_DIRECT rejects a same-effect capability id substitution",
         wrong_direct_blocked),
        ("ROOT_DIRECT PreToolUse freezes one exact claim and exact replay is idempotent",
         direct_pre_allowed and direct_pre_replay_idempotent),
        ("ROOT_DIRECT PostToolUse replay preserves one exact terminal receipt",
         direct_post_recorded and direct_post_replay_idempotent
         and not direct_receipt_debt
         and direct_receipt.get("outcome") == "succeeded"),
        ("ROOT_DIRECT projection completes without Agent or Reviewer fiction",
         direct_projection.get("root_action_receipt") == direct_receipt
         and direct_projection.get("assignment_dispositions") == []
         and not direct_projection.get("debt", {}).get("merge")
         and direct_projection.get("lane_states", [{}])[0].get("complete") is True),
        ("ROOT_DIRECT terminal blocks exact replay and a second tool use before cycle_end",
         direct_exact_after_terminal_blocked and direct_second_blocked),
        ("ROOT_DIRECT exact receipt derives the typed cycle_end",
         direct_cycle_end_valid),
        ("TaskCreate with a URL remains control-plane only",
         task_url_is_control_only),
        ("task-plan runtime receipt redacts sensitive URL query values",
         task_receipt_redacted),
        ("CronCreate without an active run is blocked",
         '"permissionDecision": "deny"' in (no_run_cron.stdout or "")),
        ("root control files stay protected with no active run",
         '"permissionDecision": "deny"' in (no_run_pointer_write.stdout or "")
         and "active-run" in (no_run_pointer_write.stdout or "")
         and '"permissionDecision": "deny"' in (no_run_pending_write.stdout or "")
         and '"permissionDecision": "deny"' in (no_run_selection_write.stdout or "")),
        ("clear-active fails closed even without an active run",
         no_active_clear_fail_closed and no_active_wrapped_clear_fail_closed),
        ("no-active-run UserPromptSubmit stores a bootstrap contract", pending_written),
        ("no-active lifecycle wrapper returns shape denial without a claim",
         no_active_shape_denied_without_claim),
        ("no-active clean exact retry succeeds in the same operator turn",
         same_turn_clean_retry_claims),
        ("missing session metadata preserves normalized operator intent across hooks",
         missing_session_hook_pipeline_recovers_intent),
        ("missing all Claude metadata uses the personal singleton across hooks",
         missing_all_metadata_hook_pipeline_recovers_intent),
        ("private setup transaction APIs cannot bypass the public lifecycle adapter",
         no_active_private_lifecycle_api_blocked),
        ("a new bare continue prompt revokes pending transition authority",
         bare_continue_revokes_transition_authority),
        ("the persistent personal pointer captures a new prompt",
         persistent_pointer_captures_new_prompt),
        ("a pointer selected by another session remains the personal global selection",
         foreign_pointer_is_personal_global_selection),
        ("an exact explicit prompt may rebind a foreign-session pointer",
         explicit_prompt_can_rebind_foreign_pointer),
        ("internal prompt notifications preserve pending authority",
         internal_prompt_preserves_pending_authority),
        ("no-active prompt revocation preserves unrelated session authority",
         prompt_revocation_is_session_scoped),
        ("active canonical contract overwrite revokes the old session claims",
         active_contract_overwrite_revokes_old_session_claims),
        ("missing-session active overwrite still revokes the displaced claim",
         missing_session_overwrite_revokes_old_claim),
        ("no-active-run normalizer prepare needs a current bootstrap contract",
         unbound_normalizer_prepare_blocked),
        ("no-active-run normalizer prepare cannot self-authorize external egress",
         implicit_external_prepare_blocked),
        ("external-model opt-in uses full unquoted prompt with late denial precedence",
         full_prompt_external_authority),
        ("operator-bound external prepare is read-only and creates no transition claim",
         explicit_external_prepare_allowed_without_claim),
        ("pending bootstrap allows its authorized setup command",
         pending_setup_allowed),
        ("pending bootstrap rejects an unrecognized bare Python without consuming authority",
         unrecognized_bare_python_fails_closed),
        ("documented bare python3 claims across hook and Bash PATH differences",
         documented_bare_python_claims_across_path_difference),
        ("pending bootstrap blocks target execution before run binding",
         pending_target_action_blocked),
        ("pending bootstrap blocks arbitrary writes before run binding",
         pending_arbitrary_write_blocked),
        ("authority mkdir and mkstemp failures map to the durability boundary",
         authority_mkdir_fault_mapped and authority_mkstemp_fault_mapped),
        ("authority file and directory fsync failures map to the durability boundary",
         authority_file_fsync_fault_mapped and authority_dir_fsync_fault_mapped),
        ("set-active without a current-session bootstrap contract is blocked",
         unbound_set_active_blocked),
        ("first active run consumes and binds the bootstrap contract",
         pending_claimed_into_run),
        ("claimed exact replay retries the owner-directory durability barrier",
         claimed_replay_is_byte_stable),
        ("ambiguous pending contracts fail closed instead of crossing sessions",
         ambiguous_pending_rejected),
        ("target claim selects the exact session among concurrent pending contracts",
         exact_session_claimed),
        ("consumed target claim binds source, transaction, and expected run",
         exact_transaction_bound),
        ("missing claim and pending artifacts converge after deletion fsync retry",
         durable_missing_cleanup_converges),
        ("same-target concurrent session claims fail closed",
         same_target_race_rejected),
        ("no-run maintenance intent leaves a short-lived local contract",
         no_run_maintenance_prompt_persisted),
        ("turn contracts do not guess a recent run without a pointer",
         no_pointer_does_not_guess),
        ("turn contracts bind the explicit active pointer", explicit_pointer_selected),
        ("SessionEnd clears the exact session-owned statusline selection",
         session_end_clears_owned_selection),
        ("startup clear and compact never restore a saved selection",
         non_resume_sources_do_not_restore),
        ("wrong transcript and fork session cannot consume a selection",
         wrong_resume_identity_fails_closed),
        ("resume restores selection behind a non-executable barrier",
         resume_restores_selection_not_authority),
        ("the first prompt after resume mints a fresh turn contract",
         first_prompt_after_resume_mints_fresh_contract),
        ("SessionEnd cannot clear another session's selection",
         session_end_preserves_other_owner),
        ("unknown SessionEnd reason leaves the pointer intact",
         session_end_unknown_reason_fails_closed),
        ("all official SessionEnd reasons clear an owned selection",
         all_official_session_end_reasons_clear),
        ("SessionEnd without a session id preserves the pointer",
         missing_session_preserves_pointer),
        ("SessionEnd without a transcript preserves the pointer",
         missing_transcript_preserves_pointer),
        ("missing or corrupt SessionEnd ownership contracts fail closed",
         invalid_session_contracts_preserve_pointer),
        ("same-run session replacement wins the contract-and-pointer CAS",
         same_run_owner_cas_preserves_new_session),
        ("different-run pointer replacement wins the SessionEnd CAS",
         changed_pointer_cas_preserves_new_run),
        ("the replacement session can clear its own selection",
         new_owner_can_clear_after_race),
        ("session clear rejects a partial ownership attestation",
         partial_clear_attestation_rejected),
        ("SessionEnd hook exits silently and preserves the personal pointer",
         session_end_hook_exits_cleanly),
        ("SessionEnd lock contention stays within the hook budget",
         session_end_lock_timeout_is_bounded),
        ("SessionEnd cleanup succeeds after the lock is released",
         session_end_can_retry_after_lock_release),
        ("settings wires UserPromptSubmit contract", wired("UserPromptSubmit")),
        ("settings does not wire session-owned pointer cleanup",
         not session_end_cleanup_wired),
        ("settings wires global PreToolUse contract", wired("PreToolUse")),
        ("settings runs turn contract selftest at SessionStart", session_start_selftest),
        ("settings does not wire session-owned pointer restoration",
         not session_resume_restore_wired),
        ("global turn contract PreToolUse hook is first", global_pretool_first),
        ("settings wires Agent/Cron PostToolUse receipts", wired("PostToolUse")),
        ("settings wires iteration-plan success/failure receipts",
         iteration_plan_receipt_tools <= receipt_matcher_tools("PostToolUse")
         and iteration_plan_receipt_tools <= receipt_matcher_tools("PostToolUseFailure")),
        ("settings wires failed tool receipts", wired("PostToolUseFailure")),
        ("settings wires maintenance write success and failure receipts",
         maintenance_receipt_tools <= receipt_matcher_tools("PostToolUse")
         and maintenance_receipt_tools <= receipt_matcher_tools("PostToolUseFailure")),
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
                "command": "python3 tools/peer_review.py runs/x > /tmp/review.log 2>&1 & echo started"}},
            contract))),
        ("foreground review uses typed --out instead of shell redirection",
         not bool(evaluate_pretool(run, safe_review_event, contract))),
        ("peer review redirect metacharacters cannot enter the capability registry",
         _registered_capability_invocation(
             injected_review_redirect["tool_input"]["command"]) is None
         and bool(evaluate_pretool(run, injected_review_redirect, contract))),
        ("registered review cannot overwrite a safety-critical data path",
         bool(critical_review_reason)
         and _maintenance_action(critical_review_output)),
        ("protected runtime receipt cannot be edited", bool(evaluate_pretool(
            run, {"tool_name": "Write", "tool_input": {"file_path": str(run / "state" / "runtime_events.jsonl")}},
            contract))),
        ("structured edit paths reject duplicate-slash, dot, and parent aliases",
         all(_protected_control_reason(event, run)
             for event in structured_protected_events[:3])),
        ("active-run-relative structured paths remain protected",
         bool(_protected_control_reason(run_relative_transaction, run))),
        ("every edit-tool path field protects plan and merge archives",
         all(_protected_control_reason(event, run)
             for event in structured_protected_events)),
        ("every structured edit tool protects the run-root setup source bundle",
         all(_protected_control_reason(event, run)
             for event in setup_source_protected_events)),
        ("symlink aliases and protected-namespace escapes remain protected",
         all(_protected_control_reason(event, run)
             for event in symlink_alias_events)),
        ("nonexistent ordinary edit path remains unprotected",
         not _protected_control_reason(
             {"tool_name": "Write", "tool_input": {
                 "file_path": str(run / "ordinary" / "new.md"),
                 "content": "ordinary",
             }}, run)),
        ("reason-pass receipt and lock cannot be edited directly", all(
            bool(evaluate_pretool(
                run, {"tool_name": "Write", "tool_input": {"file_path": str(path)}},
                contract,
            ))
            for path in (
                run / "state" / "reason_pass_receipts.jsonl",
                run / "state" / ".reason_pass.lock",
            )
        )),
        ("journals, plan/delegate transactions, and immutable snapshots cannot be edited directly", all(
            bool(evaluate_pretool(
                run, {"tool_name": "Write", "tool_input": {"file_path": str(path)}},
                contract,
            ))
            for path in (
                run / "state" / "loop_journal.jsonl",
                run / "state" / ".loop_journal.lock",
                run / "state" / "runtime_projection_cursor.json",
                run / "state" / "work_plans" / ("a" * 64 + ".json"),
                run / "state" / "work_plan_transactions"
                / ("c" * 64 + ".json"),
                run / "state" / "work_plan_transaction.json",
                run / "state" / "delegate_transaction.json",
                run / "state" / "assignment_cancellation_transaction.json",
                run / "state" / "assignment_cancellations"
                / ("d" * 64 + ".json"),
                run / "state" / "merge_results" / "A-hunter-001"
                / ("attempt-001-" + "b" * 64 + ".json"),
                run / "state" / ".work_plan.lock",
                run / "state" / ".assignments.lock",
            )
        )),
        ("protected runtime receipt remains readable", not bool(evaluate_pretool(
            run, {"tool_name": "Read", "tool_input": {"file_path": str(run / "state" / "runtime_events.jsonl")}},
            contract))),
        ("runtime projection cursor remains readable", not bool(evaluate_pretool(
            run, {"tool_name": "Read", "tool_input": {"file_path": str(
                run / "state" / "runtime_projection_cursor.json")}}, contract))),
        ("normalized and symlinked protected paths remain readable",
         all(not _protected_control_reason(
             {"tool_name": "Read", "tool_input": {"file_path": path}}, run)
             for path in [*transaction_aliases, str(symlink_alias / "snapshot.json")])),
        ("reason-pass receipt remains readable", not bool(evaluate_pretool(
            run, {"tool_name": "Read", "tool_input": {
                "file_path": str(run / "state" / "reason_pass_receipts.jsonl")}},
            contract))),
        ("content-addressed plan/transaction and Agent-result snapshots remain readable", all(
            not bool(evaluate_pretool(
                run, {"tool_name": "Read", "tool_input": {"file_path": str(path)}},
                contract,
            ))
            for path in (
                run / "state" / "work_plans" / ("a" * 64 + ".json"),
                run / "state" / "work_plan_transactions"
                / ("c" * 64 + ".json"),
                run / "state" / "assignment_cancellations"
                / ("d" * 64 + ".json"),
                run / "state" / "assignment_cancellation_transaction.json",
                run / "state" / "merge_results" / "A-hunter-001"
                / ("attempt-001-" + "b" * 64 + ".json"),
            )
        )),
    ]
    bad = [name for name, ok in checks if not ok]
    for name, ok in checks:
        print(("ok   " if ok else "FAIL ") + name)
    print("turn_contract selftest " + ("passed" if not bad else f"FAILED ({len(bad)})"))
    return 0 if not bad else 1


def _runtime_hook_failure_diagnostic(event: dict, exc: Exception) -> tuple[int, str]:
    hook = str(event.get("hook_event_name") or "")
    if hook not in {
            "PostToolUse", "PostToolUseFailure",
            "SubagentStart", "SubagentStop"}:
        return 0, ""
    return 2, (
        f"[{E_RUNTIME_RECEIPT_HOOK_FAILED}] {hook} runtime receipt "
        f"recording failed closed: {type(exc).__name__}"
    )


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
        hook = str(event.get("hook_event_name") or "")
        if hook == "PreToolUse":
            run_dir = explicit_active_run()
            state = "active run" if run_dir is not None else "no active run"
            print(json.dumps(_deny(
                f"Xunji PreToolUse contract 内部异常，{state} 按 fail-closed 阻断："
                + type(exc).__name__), ensure_ascii=False))
            return 0
        exit_code, diagnostic = _runtime_hook_failure_diagnostic(event, exc)
        if diagnostic:
            print(diagnostic, file=sys.stderr)
        if exit_code:
            return exit_code
        return 0
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
