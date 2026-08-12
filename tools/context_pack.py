#!/usr/bin/env python3
"""Minimal context pack builder for Ultra-native Xunji agents.

Markdown run files remain canonical. This tool only copies a compact slice into
`context/*.md` or stdout so a subagent starts with the smallest useful board:
target scope, assigned front, nearby coverage/evidence, barriers, and role
boundaries. It never writes findings or canonical evidence.
"""
from __future__ import annotations

import argparse
from dataclasses import dataclass
import hashlib
import json
import os
import re
import shlex
import subprocess
import sys
import time
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

import agent_instruction_bundle as _instruction_bundle
import contract_schema

ROOT = Path(__file__).resolve().parents[1]
HWS = r"[^\S\n]"

try:
    sys.stdout.reconfigure(encoding="utf-8")       # type: ignore[attr-defined]
except Exception:
    pass

sys.path.insert(0, str(ROOT / "tools"))
try:
    import knowledge_match as _knowledge_match
except Exception:
    _knowledge_match = None
try:
    import xday_match as _xday_match
except Exception:
    _xday_match = None
from harness import capability_registry as _capability_registry
from harness import python_runtime as _python_runtime


ROLE_TEMPLATES = {
    "surface": "surface",
    "web": "web-hunter",
    "web-auth": "web-auth",
    "web-hunter": "web-hunter",
    "code": "code-audit",
    "code-audit": "code-audit",
    "zhaoxuan": "code-audit",
    "exploit": "exploit",
    "exploit-construction": "exploit",
    "verify": "verify",
    "verification": "verify",
    "review": "review",
    "independent-review": "review",
    "report": "report",
    "synthesizer": "synthesizer",
}

DEFAULT_OPERATOR_PROFILE = {
    "schema": 1,
    "decision_style": "autonomous_until_blocked",
    "fallback_seconds": 600,
    "depth_bias": "prefer_depth_after_repeated_low",
    "evidence_style": "artifact_first",
    "review_style": "truth_over_agreement",
    "live_replay_policy": "stop_on_guard_volume_warning",
    "rdt": {
        "style": "openmythos-inspired",
        "default_loop_budget": 3,
        "depth_pivot_after_low_cycles": 3,
        "front_budgets": {
            "static_infoleak_config": 3,
            "auth_sso_token_signature": 6,
            "js_api_chunk_signature": 6,
            "candidate_verification": 5,
            "closure_review": 8,
        },
        "role_profiles": {
            "surface": {"loop_budget": 3, "focus": "coverage_breadth"},
            "web": {"loop_budget": 5, "focus": "mechanism_depth"},
            "web-auth": {"loop_budget": 6, "focus": "auth_boundary_depth"},
            "web-hunter": {"loop_budget": 5, "focus": "mechanism_depth"},
            "code-audit": {"loop_budget": 5, "focus": "source_to_runtime_path"},
            "exploit": {"loop_budget": 4, "focus": "proof_boundary_and_handoff"},
            "verify": {"loop_budget": 5, "focus": "control_and_falsification"},
            "review": {"loop_budget": 8, "focus": "missed_fronts_false_positive_closure"},
            "report": {"loop_budget": 3, "focus": "evidence_bound_consistency"},
            "synthesizer": {"loop_budget": 6, "focus": "conflict_resolution_and_gate"},
        },
    },
    "retrospective_lessons": [
        "check agent status and conflicts before closure",
        "read gate/source after repeated check failures",
        "when large JS exceeds body caps, pivot to range/chunk discovery",
        "after three LOW/noise cycles on the same front, pivot from breadth to mechanism depth",
        "consolidate closure blockers proactively instead of leaving orphaned agent output",
    ],
}


@dataclass(frozen=True)
class PreparedCapabilityCandidate:
    """One closed-set, derived capability view for an Agent context pack.

    Candidates are guidance only.  The registry owns the script/effect/policy
    contract and Hooks re-authorize every actual call.  Keeping only argv and a
    registry id here prevents this projection from becoming a second registry.
    """

    capability_id: str
    purpose: str
    argv: tuple[str, ...]
    env: tuple[tuple[str, str], ...] = ()
    result_hint: str = ""
    priority: int = 100


_LANE_CAPABILITY_EFFECTS = {
    "local_read": frozenset({"local_read"}),
    "local_verify": frozenset({"local_read", "local_verify"}),
    "target": frozenset({"local_read", "local_verify", "target"}),
    "model_egress": frozenset({"local_read", "local_verify", "model_egress"}),
}
_PREPARED_CAPABILITY_MARKER = "xunji.prepared-capability.v1"
_MAX_PREPARED_CAPABILITIES = 3
_LARGE_ARTIFACT_BYTES = 64 * 1024
_HTTP_URL_PATTERN = r"(?i)https?://[^\s`'\"<>，。；：！？]+"


def _turn_contract(run_dir: Path) -> dict:
    value = _load_json(run_dir / "state" / "turn_contract.json")
    if contract_schema.turn_contract_errors(value, allow_legacy=True):
        return {}
    return value

_FRONT_PROFILE_RULES: list[tuple[str, re.Pattern[str]]] = [
    ("closure_review", re.compile(r"\b(closure|review|report|merge|synthesi[sz]e)\b", re.I)),
    ("candidate_verification", re.compile(r"\b(candidate|verify|replicat|control|replay|evidence)\b", re.I)),
    ("auth_sso_token_signature", re.compile(r"\b(auth|login|sso|oauth|saml|cas|idp|token|jwt|session|signature|sign)\b", re.I)),
    ("js_api_chunk_signature", re.compile(r"\b(js|javascript|bundle|chunk|api|graphql|swagger|openapi|sign|hmac)\b", re.I)),
    ("static_infoleak_config", re.compile(r"\b(static|infoleak|exposure|config|debug|secret|source|sourcemap|backup)\b", re.I)),
]


def resolve_run_dir(path: str | Path) -> Path:
    p = Path(path)
    return (p if p.is_absolute() else ROOT / p).resolve()


def _read(path: Path, limit: int | None = None) -> str:
    if not path.exists():
        return ""
    text = path.read_text(encoding="utf-8", errors="replace")
    if limit is not None and len(text) > limit:
        return text[-limit:]
    return text


def _load_json(path: Path) -> dict:
    try:
        data = json.loads(path.read_text(encoding="utf-8", errors="replace"))
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def _deepcopy_jsonable(data: dict) -> dict:
    return json.loads(json.dumps(data, ensure_ascii=False))


def _deep_merge(base: dict, override: dict) -> dict:
    merged = _deepcopy_jsonable(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = _deep_merge(merged[key], value)
        else:
            merged[key] = value
    return merged


def _as_int(value, default: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _profile_rel(path: Path) -> str:
    try:
        return str(path.relative_to(ROOT))
    except ValueError:
        return str(path)


def load_operator_profile(run_dir: Path) -> tuple[dict, str]:
    """Load per-run operator preferences without treating them as evidence."""
    path = run_dir / "state" / "operator_profile.json"
    data = _load_json(path)
    if data:
        return _deep_merge(DEFAULT_OPERATOR_PROFILE, data), _profile_rel(path)
    return _deepcopy_jsonable(DEFAULT_OPERATOR_PROFILE), "built-in defaults (state/operator_profile.json missing)"


def _role_profile(profile: dict, role: str) -> dict:
    rdt = profile.get("rdt") if isinstance(profile.get("rdt"), dict) else {}
    profiles = rdt.get("role_profiles") if isinstance(rdt.get("role_profiles"), dict) else {}
    role_l = role.strip().lower()
    if isinstance(profiles.get(role_l), dict):
        return dict(profiles[role_l])
    if role_l == "web" and isinstance(profiles.get("web-hunter"), dict):
        return dict(profiles["web-hunter"])
    return {}


def _front_profile(front_text: str, role: str) -> str:
    combined = f"{role}\n{front_text}"
    if role in {"verify", "verification"}:
        return "candidate_verification"
    if role in {"review", "report", "synthesizer", "independent-review"}:
        return "closure_review"
    for name, rx in _FRONT_PROFILE_RULES:
        if rx.search(combined):
            return name
    return "role_default"


def resolve_rdt_profile(run_dir: Path, *, role: str, front_text: str = "") -> dict:
    profile, source = load_operator_profile(run_dir)
    rdt = profile.get("rdt") if isinstance(profile.get("rdt"), dict) else {}
    role_cfg = _role_profile(profile, role)
    default_budget = _as_int(
        rdt.get("default_loop_budget"),
        int(DEFAULT_OPERATOR_PROFILE["rdt"]["default_loop_budget"]),
    )
    role_budget = _as_int(role_cfg.get("loop_budget"), default_budget)
    front_key = _front_profile(front_text, role)
    front_budgets = rdt.get("front_budgets") if isinstance(rdt.get("front_budgets"), dict) else {}
    front_budget = _as_int(front_budgets.get(front_key), 0)
    lessons = profile.get("retrospective_lessons") if isinstance(profile.get("retrospective_lessons"), list) else []
    return {
        "source": source,
        "style": str(rdt.get("style") or "openmythos-inspired"),
        "loop_budget": max(role_budget, front_budget, 1),
        "role_focus": str(role_cfg.get("focus") or "role_default"),
        "front_profile": front_key,
        "decision_style": str(profile.get("decision_style") or "autonomous_until_blocked"),
        "fallback_seconds": _as_int(profile.get("fallback_seconds"), int(DEFAULT_OPERATOR_PROFILE["fallback_seconds"])),
        "depth_bias": str(profile.get("depth_bias") or "prefer_depth_after_repeated_low"),
        "depth_pivot_after_low_cycles": _as_int(rdt.get("depth_pivot_after_low_cycles"), 3),
        "evidence_style": str(profile.get("evidence_style") or "artifact_first"),
        "review_style": str(profile.get("review_style") or "truth_over_agreement"),
        "live_replay_policy": str(profile.get("live_replay_policy") or "stop_on_guard_volume_warning"),
        "retrospective_lessons": [str(x) for x in lessons[:6]],
    }


def render_operator_profile_lines(run_dir: Path, *, role: str, front_text: str = "",
                                  include_heading: bool = True) -> list[str]:
    rdt = resolve_rdt_profile(run_dir, role=role, front_text=front_text)
    lines: list[str] = []
    if include_heading:
        lines += ["## Operator Profile / Personalized RDT"]
    lines += [
        f"- Source: {rdt['source']}",
        f"- RDT style: {rdt['style']} (reasoning pattern only; no OpenMythos runtime dependency)",
        f"- Recommended reasoning-loop budget: {rdt['loop_budget']} recurrent step(s); "
        "this does not authorize additional tool calls",
        f"- Role focus: {rdt['role_focus']}",
        f"- Front profile: {rdt['front_profile']}",
        f"- Decision style: {rdt['decision_style']} (fallback_seconds={rdt['fallback_seconds']})",
        f"- Evidence style: {rdt['evidence_style']}",
        f"- Review style: {rdt['review_style']}",
        f"- Live replay policy: {rdt['live_replay_policy']}",
        f"- Depth pivot: after {rdt['depth_pivot_after_low_cycles']} low/noise cycles, pivot from breadth to mechanism depth",
        "- Step contract: every recurrent step restates Original front, Known E-ids, Constraints, Last action, Last outcome, Drop condition, and Next hypothesis.",
        "- Trust boundary: operator profile is preference/context only, never target evidence and never a finding.",
    ]
    lessons = rdt.get("retrospective_lessons") or []
    if lessons:
        lines.append("- Retrospective lessons:")
        for item in lessons:
            lines.append(f"  - {item}")
    return lines


def _field(text: str, name: str) -> str:
    values = _field_values(text, name)
    return values[0] if values else ""


def _field_values(text: str, name: str) -> list[str]:
    return [
        value.strip() for value in re.findall(
            rf"(?im)^{HWS}*[-*]?{HWS}*{re.escape(name)}{HWS}*[:：]{HWS}*([^\n]*)$",
            text,
        )
    ]


def _front_block(run_dir: Path, front_id: str) -> str:
    text = _read(run_dir / "frontier.md")
    m = re.search(rf"(?ms)^###{HWS}+{re.escape(front_id)}\b.*?(?=^###{HWS}+(?:F|H)-\d+\b|\Z)", text)
    return m.group(0).strip() if m else ""


def _egress_route(contract: dict) -> str:
    operator_intent = contract.get("operator_intent") \
        if isinstance(contract.get("operator_intent"), dict) else {}
    route = str(operator_intent.get("route") or "")
    if route in {"offline", "direct", "proxy"}:
        return route
    # Historical false meant proxy-by-default, not an affirmative operator
    # choice. Do not revive it; a fresh top-level turn must freeze a route.
    return "direct" if contract.get("direct_egress_approved") is True else "offline"


def _json_sha256(value: object) -> str:
    encoded = json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _prepared_action_sha256(command: str) -> str:
    """Mirror runtime_receipts' Bash action hash without importing its writer."""
    return _json_sha256({"command": command})


def _candidate_command(
    candidate: PreparedCapabilityCandidate,
    spec: _capability_registry.CapabilitySpec,
) -> str:
    env = " ".join(
        f"{key}={shlex.quote(value)}" for key, value in candidate.env
    )
    invocation = shlex.join((_python_runtime.display_token(), spec.script, *candidate.argv))
    return f"{env} {invocation}" if env else invocation


def _assignment_asset_endpoints(assets: list[str]) -> set[tuple[str, int | None]]:
    endpoints: set[tuple[str, int | None]] = set()
    for asset in assets:
        endpoint = _capability_registry.target_endpoint(
            _capability_registry.TargetReference(
                asset, role="assignment", allow_bare=True,
            )
        )
        if endpoint is not None:
            endpoints.add(endpoint)
    return endpoints


def _exact_http_urls(text: str) -> list[str] | None:
    """Return exact distinct HTTP(S) spellings after ambiguity normalization.

    The canonical form is used only as an ambiguity key.  The emitted argv
    retains the exact frozen spelling (apart from Markdown tail punctuation),
    because semantic URL normalization belongs to the runtime/barrier owner.
    """
    by_key: dict[str, str] = {}
    for raw in re.findall(_HTTP_URL_PATTERN, text):
        value = raw.rstrip(".,);]}")
        try:
            parsed = urlsplit(value)
            host = parsed.hostname or ""
            port = parsed.port
        except ValueError:
            return None
        scheme = parsed.scheme.lower()
        if scheme not in {"http", "https"} or not host \
                or parsed.username is not None or parsed.password is not None:
            return None
        canonical_host = host.lower()
        if ":" in canonical_host:
            canonical_host = f"[{canonical_host}]"
        default_port = 443 if scheme == "https" else 80
        netloc = canonical_host + (f":{port}" if port and port != default_port else "")
        key = urlunsplit((scheme, netloc, parsed.path, parsed.query, parsed.fragment))
        prior = by_key.get(key)
        if prior is not None and prior != value:
            return None
        by_key[key] = value
    return sorted(set(by_key.values()))


def _direct_action_has_condition_suffix(next_move: str) -> bool:
    """Detect an explicit condition clause after the direct action object.

    The action object is the exact HTTP URL or evidence artifact selected by
    the frozen front.  Starting the search after that object keeps ``if`` and
    ``when`` inside URL queries or artifact names inert.  A condition must
    begin the remaining tail or a punctuation-delimited tail clause, so normal
    noun phrases such as ``for if-statement tokens`` are not conditions.
    """
    object_spans: list[tuple[int, int]] = []
    for match in re.finditer(_HTTP_URL_PATTERN, next_move):
        object_spans.append(match.span())
    for match in re.finditer(r"`(evidence/[^`\r\n]+)`", next_move):
        object_spans.append(match.span())
    for match in re.finditer(
        r"(?<![A-Za-z0-9._/-])evidence/"
        r"[A-Za-z0-9][A-Za-z0-9._/@%+=:,~\/-]*",
        next_move,
    ):
        object_spans.append(match.span())
    if not object_spans:
        return False

    # The first direct object owns the action tail.  Later URLs/artifacts make
    # projection ambiguous elsewhere; they must not move this boundary past an
    # already-visible condition clause.
    _object_start, object_end = min(
        object_spans, key=lambda span: (span[0], -span[1]),
    )
    tail = next_move[object_end:]
    clauses = [tail]
    clauses.extend(
        tail[match.end():]
        for match in re.finditer(r"[,;:，；：。!?！？]|(?:\s+[—–]\s+)", tail)
    )
    for raw_clause in clauses:
        clause = raw_clause.strip()
        if not clause:
            continue
        if re.match(
            r"(?is)^(?:if|when|provided\s+that|as\s+long\s+as)\b\s+\S",
            clause,
        ):
            return True
        if re.match(r"^(?:如果|前提是|只要)\s*\S", clause):
            return True
        if re.match(r"^若(?!干)\s*\S", clause):
            return True
        if re.match(r"^当(?:\s+\S|\S.*(?:时|[,，]))", clause):
            return True
        if re.match(r"^在\s*\S.+时\s*[。！？.!?]?\s*$", clause):
            return True
    return False


def _front_is_explicit_affirmative(next_move: str) -> bool:
    """Reject negated, completed, exception, and conditional-only intent."""
    if _direct_action_has_condition_suffix(next_move):
        return False
    if re.search(
        r"(?i)\b(?:do\s+not|don't|must\s+not|never|skip|already\s+"
        r"(?:complete|completed|done|ran|tested)|do\s+not\s+repeat|"
        r"if\s+(?:needed|necessary|required)|only\s+if|when\s+needed|"
        r"in\s+case|unless|except|excluding|without|rather\s+than|"
        r"instead\s+of|other\s+than|all\s+but|forego|eschew|"
        r"avoid(?:ing|ed)?|refrain(?:ing)?(?:\s+from)?|omit(?:ting|ted)?)\b|"
        r"(?:禁止|不要|不得|无需|不必|勿|已完成|已执行|已探活|不再|不重复|"
        r"跳过|如有需要|如果需要|仅当|除.+以外|除外|排除|避免|而不是|"
        r"不做|舍弃|而非|不含|改为)",
        next_move,
    ):
        return False
    return True


def _front_selects_get_liveness(next_move: str) -> bool:
    """Recognize a GET-liveness capability as the sentence's direct action."""
    if not _front_is_explicit_affirmative(next_move):
        return False
    if not (
        re.match(
            r"(?i)^\s*(?:(?:execute|run|perform|send|issue)\s+"
            r"(?:(?:an?|the|one)\s+)?(?:(?:http\s+)?get\b|"
            r"probe(?:\.py)?\s+get\b)|use\s+probe(?:\.py)?\s+get\b)",
            next_move,
        )
        or re.match(
            r"^\s*(?:(?:执行|发送|运行|进行)\s*(?:一次|该|此)?\s*"
            r"(?:(?:HTTP\s*)?GET\b|probe(?:\.py)?\s+GET\b)|"
            r"使用\s*probe(?:\.py)?\s+GET\b)",
            next_move,
        )
    ):
        return False
    return bool(
        re.search(r"(?i)\b(?:http\s+)?get\b.*\b(?:probe|liveness|reachab)", next_move)
        or re.search(r"(?i)\bprobe(?:\.py)?\s+get\b", next_move)
        or (re.search(r"(?i)\bget\b", next_move)
            and re.search(r"(?:探活|可达|连通)", next_move))
    )


def _front_selects_local_inspection(
    next_move: str, *, artifact_reference: str,
) -> bool:
    """Require the selected artifact to be the direct local-inspection object."""
    if not _front_is_explicit_affirmative(next_move) or re.search(
            r"(?i)\b(?:may|might|could)\b|(?:可考虑)", next_move):
        return False
    escaped = re.escape(artifact_reference)
    artifact = rf"(?:`{escaped}`|{escaped})(?=\s|[,.;:，。；：]|$)"
    return any(re.match(pattern + artifact, next_move) for pattern in (
        r"(?i)^\s*(?:search|find|inspect|read|analy[sz]e|scan)\s+"
        r"(?:(?:the|one|selected|saved)\s+)?",
        r"(?i)^\s*extract\s+(?:printable\s+)?strings\s+(?:from\s+)?",
        r"(?i)^\s*(?:inspect|read)\s+(?:(?:an?|the)\s+)?"
        r"(?:byte\s+)?(?:range|slice|chunk)s?\s+(?:from|in|of)\s+",
        r"^\s*(?:检索|搜索|查找|检查|读取|分析|扫描)\s*",
        r"^\s*提取\s*(?:可打印)?字符串\s*(?:自|从)?\s*",
        r"^\s*(?:检查|读取)\s*(?:字节)?(?:范围|分块|切片)\s*(?:自|从|于)?\s*",
    ))


def _bounded_range_from_intent(
    next_move: str, *, artifact_size: int,
) -> tuple[int, int] | None:
    """Resolve a narrow explicit byte range, or a safe first-chunk default."""
    offset_marked = bool(re.search(r"(?i)\boffset\b|(?:偏移(?:量)?)", next_move))
    length_marked = bool(re.search(r"(?i)\blength\b|(?:长度)", next_move))
    offset_values = {
        int(token) for groups in re.findall(
            r"(?i)\boffset\s*(?:=|:)?\s*(0|[1-9][0-9]*)|"
            r"(?:偏移(?:量)?)\s*(?:=|:|为)?\s*(0|[1-9][0-9]*)",
            next_move,
        ) for token in groups if token
    }
    length_values = {
        int(token) for groups in re.findall(
            r"(?i)\blength\s*(?:=|:)?\s*(0|[1-9][0-9]*)|"
            r"(?:长度)\s*(?:=|:|为)?\s*(0|[1-9][0-9]*)",
            next_move,
        ) for token in groups if token
    }
    if (offset_marked and len(offset_values) != 1) \
            or (length_marked and len(length_values) != 1):
        return None
    offset = next(iter(offset_values)) if offset_values else 0
    length = next(iter(length_values)) if length_values else 4096
    if artifact_size <= 0 or not 0 <= offset < artifact_size \
            or not 1 <= length <= 64 * 1024 \
            or offset > (1 << 63) - 1:
        return None
    return offset, length


def _candidate_is_valid(
    candidate: PreparedCapabilityCandidate,
    *,
    run_dir: Path,
    lane_effect: str,
    assets: list[str],
    route: str,
    lane: dict | None = None,
) -> tuple[_capability_registry.CapabilitySpec, str] | None:
    """Reverse-validate one derived candidate against the sole registry.

    Failure returns no projection.  It never falls back to an approximate
    command, a script inventory, or an effect-wide list.
    """
    spec = _capability_registry.by_id(candidate.capability_id)
    allowed = _LANE_CAPABILITY_EFFECTS.get(lane_effect, frozenset())
    if spec is None or spec.effect not in allowed:
        return None
    if _capability_registry.match(spec.path(), candidate.argv) != spec:
        return None
    if _capability_registry.run_reference(spec, candidate.argv) != _profile_rel(run_dir):
        return None
    if any(
        not key or key not in spec.allowed_env
        or not value or re.search(r"[\x00-\x1f\x7f]", value)
        for key, value in candidate.env
    ) or len({key for key, _value in candidate.env}) != len(candidate.env):
        return None
    if any(
        not value or len(value.encode("utf-8", "replace")) > 256 * 1024
        or re.search(r"[\x00-\x1f\x7f]", value)
        or "```" in value or "`" in value
        for value in candidate.argv
    ):
        return None
    if spec.effect == "target":
        required = "1" if route == "proxy" else "0" if route == "direct" else ""
        if not required or candidate.env != (("XUNJI_PROXY_REQUIRED", required),):
            return None
        assignment_endpoints = _assignment_asset_endpoints(assets)
        if not assignment_endpoints:
            return None
        try:
            references = _capability_registry.target_references(spec, candidate.argv)
        except ValueError:
            return None
        if not references:
            return None
        for reference in references:
            endpoint = _capability_registry.target_endpoint(reference)
            if endpoint is None:
                return None
            host, port = endpoint
            if not any(
                asset_host == host and (asset_port is None or asset_port == port)
                for asset_host, asset_port in assignment_endpoints
            ):
                return None
    elif candidate.env:
        return None
    command = _candidate_command(candidate, spec)
    if "\n" in command or "\r" in command or "```" in command:
        return None
    binding = lane.get("infra_barrier") \
        if isinstance(lane, dict) and isinstance(lane.get("infra_barrier"), dict) \
        else {}
    if spec.effect == "target" and binding.get("operation_class") == "target_attempt":
        try:
            import barrier_state as _barrier_state
            actual_fingerprint = _barrier_state.runtime_action_fingerprint({
                "tool_name": "Bash",
                "tool_input": {"command": command},
                "action_sha256": _prepared_action_sha256(command),
            })
        except Exception:
            return None
        if actual_fingerprint != str(binding.get("action_fingerprint") or ""):
            return None
    return spec, command


def _target_probe_candidate(
    run_dir: Path,
    *,
    effect: str,
    front_text: str,
    request_budget: int,
    route: str,
    lane_id: str,
    assignment_attempt: int,
) -> PreparedCapabilityCandidate | None:
    if effect != "target" or request_budget < 1 or route == "offline":
        return None
    next_moves = _field_values(front_text, "Next autonomous move")
    if len(next_moves) != 1 or not next_moves[0]:
        return None
    next_move = next_moves[0]
    if not _front_selects_get_liveness(next_move):
        return None
    urls = _exact_http_urls(next_move)
    if urls is None or len(urls) != 1:
        return None
    if not re.fullmatch(r"L-[A-Za-z0-9._-]+", lane_id) \
            or isinstance(assignment_attempt, bool) \
            or not isinstance(assignment_attempt, int) \
            or not 1 <= assignment_attempt <= 999999:
        return None
    url = urls[0]
    lane_token = re.sub(r"[^a-z0-9]+", "-", lane_id.lower()).strip("-")[:36]
    lane_digest = hashlib.sha256(lane_id.encode("utf-8")).hexdigest()[:12]
    save_name = (
        f"liveness-{lane_token}-{lane_digest}-attempt-{assignment_attempt:03d}"
    )
    evidence_root = run_dir / "evidence"
    try:
        if evidence_root.is_symlink() or not evidence_root.is_dir():
            return None
    except OSError:
        return None
    body = evidence_root / f"{save_name}.html"
    if any(path.exists() or path.is_symlink() for path in (
            body, Path(str(body) + ".replay.json"))):
        return None
    return PreparedCapabilityCandidate(
        capability_id="target.probe",
        purpose="HTTP GET liveness selected by the frozen front",
        argv=(
            "GET", url, "--save", save_name, "--run", _profile_rel(run_dir),
            "--no-redirect", "--headers",
        ),
        env=(("XUNJI_PROXY_REQUIRED", "1" if route == "proxy" else "0"),),
        result_hint="JSON stdout plus a recorder-bound response artifact",
        priority=10,
    )


def _evidence_artifact_reference(
    run_dir: Path, front_text: str,
) -> tuple[str, Path, str] | None:
    """Resolve exactly one Root-frozen evidence path without following symlinks."""
    next_moves = _field_values(front_text, "Next autonomous move")
    explicit_values = _field_values(front_text, "Artifact")
    if len(next_moves) != 1 or not next_moves[0] or len(explicit_values) > 1:
        return None
    next_move = next_moves[0]
    explicit = explicit_values[0] if explicit_values else ""
    source = "\n".join(value for value in (next_move, explicit) if value)
    refs = {
        value.strip().rstrip(".,);]}")
        for value in re.findall(
            r"(?<![A-Za-z0-9._/-])(evidence/[A-Za-z0-9][A-Za-z0-9._/@%+=:,~\/-]*)",
            source,
        )
    }
    refs.update(
        value.strip() for value in re.findall(r"`(evidence/[^`\r\n]+)`", source)
    )
    refs = {value for value in refs if value.startswith("evidence/")}
    if len(refs) != 1:
        return None
    rel = next(iter(refs)).removeprefix("evidence/")
    if not rel or any(part in {"", ".", ".."} for part in Path(rel).parts):
        return None
    evidence_root = run_dir / "evidence"
    path = evidence_root / rel
    try:
        cursor = evidence_root
        if evidence_root.is_symlink() or not evidence_root.is_dir():
            return None
        for part in Path(rel).parts:
            cursor = cursor / part
            if cursor.is_symlink():
                return None
        resolved_root = evidence_root.resolve(strict=True)
        resolved = path.resolve(strict=True)
        if resolved.parent != resolved_root and resolved_root not in resolved.parents:
            return None
        if not path.is_file():
            return None
    except (OSError, RuntimeError, ValueError):
        return None
    return rel, path, next_move


def _artifact_candidates(
    run_dir: Path, *, effect: str, front_text: str,
) -> list[PreparedCapabilityCandidate]:
    if effect not in _LANE_CAPABILITY_EFFECTS:
        return []
    artifact = _evidence_artifact_reference(run_dir, front_text)
    if artifact is None:
        return []
    rel, path, next_move = artifact
    if not _front_selects_local_inspection(
            next_move, artifact_reference=f"evidence/{rel}"):
        return []
    run_ref = _profile_rel(run_dir)
    candidates: list[PreparedCapabilityCandidate] = []
    if Path(rel).suffix.lower() in {".js", ".mjs", ".html", ".htm", ".json", ".txt"} \
            and re.search(
                r"(?i)\b(?:javascript|js\s+bundle|api\s+(?:inventory|route|endpoint)|"
                r"client[- ]side\s+(?:route|endpoint))\b|"
                r"(?:JS\s*包|接口清单|接口路由|客户端路由)",
                next_move,
            ):
        candidates.append(PreparedCapabilityCandidate(
            capability_id="read.js-inventory",
            purpose="bounded offline JS/API inventory selected for one frozen artifact",
            argv=("inspect", run_ref, f"evidence/{rel}"),
            result_hint="bounded noncanonical JSON candidates with URL secrets redacted",
            priority=15,
        ))
    literal = _field(front_text, "Search literal") or _field(
        front_text, "Literal pattern",
    )
    if not literal:
        match = re.search(
            r"(?i)(?:literal|search(?:\s+for)?|find)\s+`([^`\r\n]+)`",
            next_move,
        )
        literal = match.group(1).strip() if match else ""
    if literal and len(literal.encode("utf-8", "replace")) <= 512 \
            and re.search(r"(?i)\b(?:literal|search|find)\b|(?:检索|搜索|查找)", next_move):
        candidates.append(PreparedCapabilityCandidate(
            capability_id="read.artifact-view-search",
            purpose="literal search selected for one frozen evidence artifact",
            argv=("search", run_ref, rel, literal),
            result_hint="bounded JSON match offsets and contexts",
            priority=20,
        ))
    try:
        size = path.stat().st_size
    except OSError:
        return []
    range_intent = bool(re.search(
        r"(?i)\b(?:range|offset|slice|chunk|inspect|read)\b|(?:字节|分块|切片|读取|分析)",
        next_move,
    ))
    selected_range = _bounded_range_from_intent(next_move, artifact_size=size)
    if range_intent and selected_range is not None and (
            size > _LARGE_ARTIFACT_BYTES or re.search(
                r"(?i)\b(?:range|offset|slice|chunk)\b|(?:字节|分块|切片)",
                next_move,
            )):
        offset, length = selected_range
        candidates.append(PreparedCapabilityCandidate(
            capability_id="read.artifact-view-range",
            purpose="bounded first-range inspection of one frozen evidence artifact",
            argv=("range", run_ref, rel, "--offset", str(offset),
                  "--length", str(length)),
            result_hint="bounded JSON byte range without whole-file loading",
            priority=30,
        ))
    if re.search(
        r"(?i)\b(?:strings|binary|javascript|js\s+bundle|unknown\s+encoding)\b|"
        r"(?:字符串|二进制|大型\s*JS|未知编码)",
        next_move,
    ):
        candidates.append(PreparedCapabilityCandidate(
            capability_id="read.artifact-view-strings",
            purpose="bounded string extraction selected for one frozen evidence artifact",
            argv=("strings", run_ref, rel, "--scan-limit", str(8 * 1024 * 1024),
                  "--max-strings", "50", "--max-string-bytes", "256"),
            result_hint="bounded JSON strings with scan and output caps",
            priority=40,
        ))
    return candidates


def _prepared_capabilities(
    run_dir: Path,
    *,
    effect: str,
    target: str,
    front_text: str,
    assets: list[str],
    request_budget: int,
    lane_id: str = "",
    assignment_attempt: int = 0,
    lane: dict | None = None,
    route: str | None = None,
) -> list[tuple[PreparedCapabilityCandidate, _capability_registry.CapabilitySpec, str]]:
    selected_route = route if route in {"offline", "direct", "proxy"} \
        else _egress_route(_turn_contract(run_dir))
    candidates: list[PreparedCapabilityCandidate] = []
    target_candidate = _target_probe_candidate(
        run_dir,
        effect=effect,
        front_text=front_text,
        request_budget=request_budget,
        route=selected_route,
        lane_id=lane_id,
        assignment_attempt=assignment_attempt,
    )
    if target_candidate is not None:
        candidates.append(target_candidate)
    candidates.extend(_artifact_candidates(
        run_dir, effect=effect, front_text=front_text,
    ))
    selected: list[
        tuple[PreparedCapabilityCandidate, _capability_registry.CapabilitySpec, str]
    ] = []
    seen: set[tuple[str, str]] = set()
    for candidate in sorted(
            candidates, key=lambda item: (item.priority, item.capability_id, item.argv)):
        validated = _candidate_is_valid(
            candidate,
            run_dir=run_dir,
            lane_effect=effect,
            assets=assets,
            route=selected_route,
            lane=lane or {},
        )
        if validated is None:
            continue
        spec, command = validated
        identity = (spec.id, _prepared_action_sha256(command))
        if identity in seen:
            continue
        seen.add(identity)
        selected.append((candidate, spec, command))
        if len(selected) == _MAX_PREPARED_CAPABILITIES:
            break
    return selected


def _prepared_capability_lines(
    run_dir: Path,
    *,
    effect: str,
    target: str,
    front_text: str,
    assets: list[str],
    request_budget: int,
    lane_id: str = "",
    assignment_attempt: int = 0,
    lane: dict | None = None,
    route: str | None = None,
) -> list[str]:
    selected = _prepared_capabilities(
        run_dir,
        effect=effect,
        target=target,
        front_text=front_text,
        assets=assets,
        request_budget=request_budget,
        lane_id=lane_id,
        assignment_attempt=assignment_attempt,
        lane=lane,
        route=route,
    )
    lines = [
        "## Prepared Registered Capabilities",
        "Derived guidance only. This block grants no authority; Hooks revalidate the",
        "turn, assignment, effect, assets, budgets, route, command shape, and registry match.",
    ]
    if not selected:
        return [
            *lines,
            "",
            "- None. No complete registry-backed argv can be derived from this frozen lane.",
            "  This empty projection does not reduce assignment authority or tool availability.",
            "  Continue with assignment-authorized built-ins and public capability contracts;",
            "  do not guess argv or inspect private framework source merely to discover syntax.",
        ]
    for index, (candidate, spec, command) in enumerate(selected, 1):
        marker = {
            "action_sha256": _prepared_action_sha256(command),
            "capability_id": spec.id,
            "effect": spec.effect,
        }
        lines += [
            "",
            f"### {index}. {spec.id}",
            f"<!-- {_PREPARED_CAPABILITY_MARKER} "
            + json.dumps(marker, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
            + " -->",
            f"- Effect: {spec.effect}",
            f"- Purpose: {candidate.purpose}",
            f"- Result: {candidate.result_hint or 'typed capability result'}",
            "- Exact argv:",
            "",
            "```bash",
            command,
            "```",
        ]
    lines += [
        "",
        "A denial is an attributable outcome: follow its public retry text once, then",
        "return the supported result or barrier without reading Hook/guard/tool source.",
    ]
    return lines


def _egress_contract_lines(
    run_dir: Path, *, effect: str, contract: dict | None = None,
) -> list[str]:
    """Expose the frozen route choice without minting authority."""
    if effect != "target":
        return []
    frozen_contract = contract if isinstance(contract, dict) \
        else _turn_contract(run_dir)
    route = _egress_route(frozen_contract)
    if route == "direct":
        return [
            "## Frozen Egress Route",
            "This turn uses the default direct route. Prefix every registered target",
            "capability argv with exact `XUNJI_PROXY_REQUIRED=0`; Hooks still revalidate",
            "scope, privacy, request budget, guard, command shape, and recording.",
        ]
    if route == "offline":
        return [
            "## Frozen Egress Route",
            "This turn is offline. Do not invoke a target capability.",
        ]
    return [
        "## Frozen Egress Route",
        "The operator explicitly selected the engagement proxy for this turn. Prefix every",
        "registered target argv with exact `XUNJI_PROXY_REQUIRED=1`. If the proxy fails,",
        "return the blocker and stop; only a newer operator turn may restart target traffic.",
    ]


def _assignment(run_dir: Path, agent_id: str) -> dict:
    data = _load_json(run_dir / "state" / "assignments.json")
    for item in data.get("assignments", []):
        if isinstance(item, dict) and item.get("agent") == agent_id:
            return item
    path = run_dir / "agents" / f"{agent_id}.md"
    text = _read(path)
    if text:
        return {
            "agent": agent_id,
            "role": _field(text, "Role"),
            "front": _field(text, "Assigned front"),
            "scope": _field(text, "Scope"),
        }
    return {}


def _normalized_asset(value: object) -> str:
    raw = str(value or "").strip().lower().rstrip(".")
    raw = re.sub(r"^[a-z][a-z0-9+.\-]*://", "", raw).split("/", 1)[0]
    return raw


def _coverage_rows(run_dir: Path, front_text: str, limit: int = 6,
                   exact_assets: list[str] | None = None) -> list[dict]:
    candidates = [run_dir / "coverage.json", *sorted(run_dir.glob("**/coverage.json"))]
    data: dict = {}
    for p in candidates:
        data = _load_json(p)
        if isinstance(data.get("assets"), list):
            break
    low = front_text.lower()
    selected = {_normalized_asset(item) for item in (exact_assets or [])
                if _normalized_asset(item)}
    rows: list[dict] = []
    for asset in data.get("assets", []) if isinstance(data.get("assets"), list) else []:
        if not isinstance(asset, dict):
            continue
        host = str(asset.get("host") or asset.get("asset") or asset.get("url") or "").strip()
        normalized = _normalized_asset(host)
        if selected and normalized in selected:
            rows.append(asset)
        elif not selected and host and re.search(
                rf"(?<![A-Za-z0-9._-]){re.escape(host.lower())}(?![A-Za-z0-9._-])", low):
            rows.append(asset)
    return rows[:limit]


def _kb_ids(front_text: str, coverage_rows: list[dict]) -> list[str]:
    ids: list[str] = []
    for raw in re.findall(r"\bkb:([A-Za-z0-9_-]+)\b", front_text):
        if raw not in ids:
            ids.append(raw)
    for asset in coverage_rows:
        stack = str(asset.get("stack") or "")
        if stack.startswith("kb:"):
            kid = stack.split(":", 1)[1].strip()
            if kid and kid not in ids:
                ids.append(kid)
    return ids


def _rel(path: Path) -> str:
    try:
        return str(path.resolve().relative_to(ROOT))
    except Exception:
        return str(path)


def _knowledge_xday_summary(kb_ids: list[str], *, kb_dir: Path | None = None,
                            xday_dir: Path | None = None,
                            weap_dir: Path | None = None) -> list[str]:
    lines: list[str] = []
    fallback = (
        "use built-in Read against exact saved-artifact and knowledge paths "
        "already supplied by the context; return an explicit knowledge gap when no grounded "
        "match exists; writeback is a separate maintenance turn"
    )
    if not kb_ids:
        return [f"- (no `kb:<id>` hint matched this front; {fallback}.)"]
    if _knowledge_match is None:
        return [f"- (offline matcher module unavailable; {fallback}.)"]
    kb_root = kb_dir or _knowledge_match.KB
    entries = {e.id: e for e in _knowledge_match.load_entries(kb_root)}
    stores = {}
    if _xday_match is not None:
        stores = _xday_match.load_local_stores(xday_dir or _xday_match.XDAY,
                                               weap_dir or _xday_match.WEAP)
    for kid in kb_ids[:6]:
        e = entries.get(kid)
        if e:
            sigs = ", ".join(e.sigs[:4]) + (" ..." if len(e.sigs) > 4 else "")
            lines.append(f"- knowledge `{kid}`: {e.product} ({e.maturity}); path={_rel(e.path)}; signatures={sigs}")
        else:
            lines.append(f"- knowledge `{kid}`: id referenced by front/coverage but no public grounding entry found")
        local = stores.get(kid, []) if e else []
        if local:
            for store in local[:3]:
                if store.get("kind") == "poc":
                    files = ", ".join(store.get("files", [])[:6])
                    lines.append(f"  - local xday pointer: {_rel(store['path'])}/ files={files}")
                else:
                    lines.append(f"  - local weaponized note pointer: {_rel(store['path'])}")
        elif e:
            lines.append("  - local xday: none indexed for this knowledge id")
        else:
            lines.append("  - local xday: withheld until a public grounding entry matches")
    return lines


def _matching_blocks(text: str, prefix: str, needle: str, limit: int = 4) -> list[str]:
    if not text:
        return []
    rx = rf"(?ms)^##{HWS}+{prefix}-\d+.*?(?=^##{HWS}+{prefix}-\d+|\Z)"
    blocks = []
    low_needle = needle.lower()
    for m in re.finditer(rx, text):
        block = m.group(0).strip()
        if low_needle and low_needle in block.lower():
            blocks.append(block)
    return blocks[:limit]


def _recent_lines(text: str, max_lines: int = 20) -> str:
    lines = [ln for ln in text.splitlines() if ln.strip()]
    return "\n".join(lines[-max_lines:])


def _canonical_role(role: str) -> str:
    canonical = ROLE_TEMPLATES.get(str(role or "").strip().lower())
    if not canonical:
        raise _instruction_bundle.InstructionBundleError(
            "source_invalid", f"unknown Agent role: {role}",
        )
    return canonical


def _role_template_path(role: str) -> Path:
    canonical = _canonical_role(role)
    manifest = _instruction_bundle.load_manifest(root=ROOT)
    return ROOT / str(manifest["roles"][canonical]["path"])


def _load_front_constraints(run_dir: Path, front_id: str) -> list[dict]:
    """解析 constraints.md(如果存在), 返回该 front 的约束列表。"""
    path = run_dir / "constraints.md"
    if not path.exists():
        return []
    text = path.read_text(encoding="utf-8", errors="replace")
    constraints: list[dict] = []
    for m in re.finditer(r"(?ms)^##[ \t]+(C-\d+).*?(?=^##[ \t]+C-\d+|\Z)", text):
        block = m.group(0)
        cid = m.group(1)
        c_front = _field(block, "Front")
        if c_front != front_id:
            continue
        constraints.append({
            "id": cid,
            "mechanism_class": _field(block, "Mechanism class"),
            "input_shape": _field(block, "Input shape"),
            "why_blocked": _field(block, "Why blocked"),
            "ruled_out": _field(block, "Ruled out"),
        })
    return constraints


def _load_front_hypotheses(run_dir: Path, front_id: str, limit: int = 4) -> list[str]:
    """Return H-blocks tied to this front, especially threat hypotheses."""
    path = run_dir / "hypotheses.md"
    if not path.exists():
        return []
    text = path.read_text(encoding="utf-8", errors="replace")
    out: list[str] = []
    for m in re.finditer(r"(?ms)^##[ \t]+H-\d+.*?(?=^##[ \t]+H-\d+|\Z)", text):
        block = m.group(0).strip()
        if re.search(rf"(?<![A-Za-z0-9_-]){re.escape(front_id)}(?![A-Za-z0-9_-])", block):
            out.append(block)
    return out[:limit]


def _load_cross_run_context(run_dir: Path, front_id: str) -> list[str]:
    """提取该 front 的 barrier class 在历史 run 中的表现, 返回 context 行列表。"""
    fr = run_dir / "frontier.md"
    if not fr.exists():
        return []
    fr_text = fr.read_text(encoding="utf-8", errors="replace")

    # 找到该 front 的 barrier class
    barrier_class = ""
    fm = re.search(rf"(?ms)^###[ \t]+{re.escape(front_id)}\b.*?(?=^###[ \t]+F-\d+|\Z)", fr_text)
    if fm:
        barrier_class = _field(fm.group(0), "Barrier class")
    if not barrier_class or barrier_class == "none":
        return []

    # 调用 cross_run.py --barrier 查询该 barrier class 的历史
    cross_run_script = str(ROOT / "tools" / "cross_run.py")
    try:
        result = subprocess.run(
            [sys.executable, cross_run_script, "--barrier", barrier_class],
            capture_output=True, text=True, timeout=15,
        )
        if result.returncode != 0:
            return []
        output = result.stdout.strip()
        if not output or "未找到 barrier class" in output:
            return []
        # 截取前 30 行, 避免 context 膨胀
        lines_out = output.splitlines()[:30]
        return lines_out
    except Exception:
        return []


def build_pack(run_dir: Path, *, front: str, role: str, agent: str = "",
               assets: list[str] | None = None, effect: str = "",
               lane_id: str = "", plan_digest: str = "",
               assignment_attempt: int = 0,
               tool_call_limit: int = 0,
               request_budget: int = 0,
               lane: dict | None = None,
               kb_dir: Path | None = None, xday_dir: Path | None = None,
               weap_dir: Path | None = None,
               role_bundle: dict | None = None) -> str:
    front_text = _front_block(run_dir, front)
    normalized_assets = [_normalized_asset(item) for item in (assets or [])
                         if _normalized_asset(item)]
    cov = _coverage_rows(run_dir, front_text, exact_assets=normalized_assets)
    kb_ids = _kb_ids(front_text, cov)
    target = _read(run_dir / "target.md", 5000)
    evidence_matches = _matching_blocks(_read(run_dir / "evidence.md"), "E", front)
    fp_matches = _matching_blocks(_read(run_dir / "false_positive.md"), "FP", front)
    decisions_tail = _recent_lines(_read(run_dir / "decisions.md", 6000), 18)
    canonical_role = _canonical_role(role)
    role_bundle = role_bundle or _instruction_bundle.load_role_contract(
        canonical_role, root=ROOT)
    contract = role_bundle.get("contract") \
        if isinstance(role_bundle, dict) else None
    if not isinstance(contract, dict) \
            or contract.get("schema") != _instruction_bundle.ROLE_CONTRACT_SCHEMA \
            or (contract.get("role") or {}).get("id") != canonical_role:
        raise _instruction_bundle.InstructionBundleError(
            "source_invalid", "context pack role contract is invalid",
        )
    role_text = str(role_bundle.get("text") or "")
    if not role_text:
        raise _instruction_bundle.InstructionBundleError(
            "source_invalid", "context pack role text is empty",
        )
    generated = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    lane_snapshot = json.loads(json.dumps(lane, ensure_ascii=False)) \
        if isinstance(lane, dict) else {}
    if lane_snapshot:
        try:
            lane_budget = lane_snapshot.get("request_budget")
            lane_assets = [
                _normalized_asset(item) for item in lane_snapshot.get("assets", [])
                if _normalized_asset(item)
            ] if isinstance(lane_snapshot.get("assets"), list) else None
        except (TypeError, ValueError):
            lane_budget = None
            lane_assets = None
        if (
                str(lane_snapshot.get("id") or "") != lane_id
                or str(lane_snapshot.get("front") or "").upper() != front.upper()
                or _canonical_role(str(lane_snapshot.get("role") or ""))
                != canonical_role
                or str(lane_snapshot.get("effect") or "") != effect
                or lane_budget != request_budget
                or lane_assets != normalized_assets):
            raise _instruction_bundle.InstructionBundleError(
                "source_invalid",
                "context pack lane snapshot differs from assignment binding",
            )
    expected_evidence = str(lane_snapshot.get("expected_evidence") or "")
    stop_condition = str(lane_snapshot.get("stop_condition") or "")
    if lane_snapshot and any(
        not value or len(value.encode("utf-8", "replace")) > 4096
        or re.search(r"[\x00-\x1f\x7f]", value)
        for value in (expected_evidence, stop_condition)
    ):
        raise _instruction_bundle.InstructionBundleError(
            "source_invalid",
            "context pack lane evidence and stop fields must be bounded single lines",
        )
    turn_contract_snapshot = _turn_contract(run_dir)
    route_snapshot = _egress_route(turn_contract_snapshot)

    lines = [
        f"# Context Pack {front} / {role}",
        "",
        f"- Generated: {generated}",
        f"- Run dir: {run_dir}",
        f"- Agent: {agent or '(unassigned)'}",
        f"- Assignment attempt: {assignment_attempt or '(unbound)'}",
        f"- Assigned front: {front}",
        f"- Assigned assets: {','.join(normalized_assets) if normalized_assets else 'none'}",
        f"- Effect: {effect or '(unbound)'}",
        f"- Lane: {lane_id or '(unbound)'}",
        f"- Plan digest: {plan_digest or '(unbound)'}",
        f"- Hard tool-call limit: {tool_call_limit if tool_call_limit > 0 else '(unbound)'}"
        " total attempted child calls; PreToolUse enforces it and denials count.",
        f"- Target request budget: {request_budget} attempted target call(s); "
        "PreToolUse denies the first call above this lane budget.",
        f"- Expected evidence: {expected_evidence or '(unbound)'}",
        f"- Stop condition: {stop_condition or '(unbound)'}",
        f"- Role: {role}",
        "- Canonical source: markdown run files; this pack is a read-only slice.",
        "- Maturity rule: subagent output is phenomenon/candidate only; Root Synthesizer owns findings.",
        "",
        "## Scope / Target",
        target.strip() or "(target.md missing)",
        "",
        "## Assigned Front",
        front_text or f"(front {front} not found in frontier.md)",
    ]
    egress_contract = _egress_contract_lines(
        run_dir, effect=effect, contract=turn_contract_snapshot,
    )
    if egress_contract:
        lines += ["", *egress_contract]
    lines += ["", *_prepared_capability_lines(
        run_dir,
        effect=effect,
        target=target,
        front_text=front_text,
        assets=normalized_assets,
        request_budget=request_budget,
        lane_id=lane_id,
        assignment_attempt=assignment_attempt,
        lane=lane_snapshot,
        route=route_snapshot,
    )]
    lines += ["", "## Matched Coverage"]
    if cov:
        for a in cov:
            host = a.get("host") or a.get("asset") or a.get("url") or "?"
            flags = ", ".join(str(x) for x in (a.get("flags") or []))
            lines.append(f"- {host}: reachable={a.get('reachable')} stack={a.get('stack')} flags={flags}")
    else:
        lines.append("- (no coverage asset matched this front text)")

    hypotheses = _load_front_hypotheses(run_dir, front)
    if hypotheses:
        lines += ["", "## Relevant Hypotheses / Threat Hypotheses"]
        lines += [
            "Use these as falsifiable queues only. They are not findings until Root promotes evidence."
        ]
        lines.extend(hypotheses)

    # 约束切片: 该 front 已被尝试并排除的 mechanism class + input shape
    constraints = _load_front_constraints(run_dir, front)
    if constraints:
        lines += ["", "## Constraints (Ruled-Out Paths)"]
        lines += ["The following mechanism classes and input shapes have been tried and ruled out. "
                   "Do NOT retry these unless you have a materially different approach:"]
        for c in constraints:
            lines.append(f"- [{c['id']}] {c['mechanism_class']} on {c['input_shape']}: {c['ruled_out']}")

    # 跨运行经验: 该 front 的 barrier class 在历史 run 中的表现
    cross_run_context = _load_cross_run_context(run_dir, front)
    if cross_run_context:
        lines += ["", "## Cross-Run Experience (Historical Barrier Data)"]
        lines.append("This barrier class has been encountered in previous runs. Learn from history:")
        lines.extend(cross_run_context)

    lines += ["", "## Relevant Evidence"]
    lines.extend(evidence_matches or ["- (no E-block explicitly mentions this front id)"])
    lines += ["", "## Relevant False Positives"]
    lines.extend(fp_matches or ["- (no FP-block explicitly mentions this front id)"])
    lines += ["", "## Relevant Knowledge / Xday Pointers"]
    lines.extend(_knowledge_xday_summary(kb_ids, kb_dir=kb_dir, xday_dir=xday_dir, weap_dir=weap_dir))
    lines += ["", "## Recent Decisions / Barriers", decisions_tail or "- (decisions.md missing or empty)"]
    lines += ["", *render_operator_profile_lines(run_dir, role=role, front_text=front_text)]
    lines += ["", "## Validated Role Receipt And Instructions"]
    common_source = contract["common"]
    role_source = contract["role"]
    live_source = contract.get("live_agent") or {}
    lines += [
        f"- Contract: {contract['schema']}",
        "- Admission: the bundle builder and Hook already verified these hashes; "
        "consume the embedded role text and do not reread or hash framework sources.",
        f"- Manifest SHA-256: {contract['manifest']['sha256']}",
        f"- Common: version={common_source['version']} sha256={common_source['sha256']}",
        f"- Role: role={canonical_role} version={role_source['version']} "
        f"sha256={role_source['sha256']}",
        f"- Composed role SHA-256: {contract['composed_sha256']}",
        f"- Live Agent: {contract.get('subagent_type') or '(Root-only)'}"
        + (f" sha256={live_source.get('sha256')}"
           if live_source else ""),
        "",
        role_text.strip(),
    ]
    lines += [
        "",
        "## Output Contract Reminder",
        "Use the generated Agent scaffold's `Final Return` fields.",
        "Maturity remains phenomenon/candidate; add only the role-authorized",
        "constraint, threat-hypothesis, or coverage deltas defined above.",
        "",
    ]
    return "\n".join(lines)


def build_from_agent(run_dir: Path, agent_id: str) -> str:
    a = _assignment(run_dir, agent_id)
    if not a:
        raise SystemExit(f"agent assignment not found: {agent_id}")
    if isinstance(a.get("instruction_bundle"), dict):
        try:
            verified = _instruction_bundle.verify_assignment_bundle_for_context_replay(
                run_dir, a, root=ROOT,
            )
            return verified["context_text"]
        except (OSError, UnicodeDecodeError,
                _instruction_bundle.InstructionBundleError) as exc:
            raise SystemExit(f"frozen agent context is invalid: {exc}") from exc
    plan_digest = str(a.get("plan_digest") or "")
    lane_id = str(a.get("lane_id") or "")
    if plan_digest or lane_id:
        raise SystemExit(
            "plan-bound assignment has no verifiable frozen instruction bundle"
        )
    plan = _load_json(run_dir / "state" / "work_plan.json")
    if str(plan.get("plan_digest") or "") != plan_digest and plan_digest:
        plan = _load_json(run_dir / "state" / "work_plans" / f"{plan_digest}.json")
    lanes = [
        item for item in plan.get("lanes", [])
        if isinstance(item, dict) and str(item.get("id") or "") == lane_id
    ]
    lane = lanes[0] if len(lanes) == 1 else None
    return build_pack(
        run_dir,
        front=str(a.get("front") or ""),
        role=str(a.get("role") or ""),
        agent=agent_id,
        assets=[str(item) for item in a.get("assets", []) if str(item).strip()],
        effect=str(a.get("effect") or ""),
        lane_id=lane_id,
        plan_digest=plan_digest,
        assignment_attempt=int(a.get("assignment_attempt") or 0),
        tool_call_limit=int(a.get("tool_call_limit") or 0),
        request_budget=int(a.get("request_budget") or 0),
        lane=lane,
    )


def _atomic_write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f"{path.name}.tmp{os.getpid()}-{time.monotonic_ns()}")
    tmp.write_text(text, encoding="utf-8")
    os.replace(tmp, path)


def _selftest() -> int:
    import tempfile
    d = Path(tempfile.mkdtemp())
    kb = d / "knowledge"
    weap = kb / "weaponized"
    xday = d / "poc_library" / "xday"
    weap.mkdir(parents=True)
    xday.mkdir(parents=True)
    (kb / "foobar-cms.md").write_text(
        "---\nid: foobar-cms\nproduct: FooBar CMS\nmaturity: seed\n"
        'signatures: ["foobar-cms", "/fb/login.do"]\n---\n\n'
        "## Weak-Point Anchors\n- Anchor: auth boundary review.\n",
        encoding="utf-8")
    (weap / "foobar-cms.md").write_text("---\nid: foobar-cms\n---\nlocal note\n", encoding="utf-8")
    (weap / "missing-public.md").write_text(
        "---\nid: missing-public\n---\nmust stay hidden without public grounding\n",
        encoding="utf-8")
    xp = xday / "foobar-cms"
    xp.mkdir()
    (xp / "README.md").write_text("| link | `knowledge/foobar-cms.md` |\n", encoding="utf-8")
    (xp / "poc.py").write_text("# local only\n", encoding="utf-8")
    (d / "target.md").write_text("# Target\n- In-scope assets: app.example\n", encoding="utf-8")
    (d / "frontier.md").write_text(
        "# Frontier\n\n### F-001\n- Front: app.example auth kb:foobar-cms\n- Status: open\n", encoding="utf-8")
    (d / "hypotheses.md").write_text(
        "# Hypotheses\n\n"
        "## H-001\n\n"
        "- Claim: app.example hidden admin API may expose cross-role data\n"
        "- Status: open\n"
        "- Front: F-001\n"
        "- Threat hypothesis: hidden admin API may expose cross-role data\n"
        "- Asset/role/input: app.example user GET /api/admin/users\n"
        "- Expected signal: role-specific response difference\n"
        "- Refutation/control: unauth and user both 403\n"
        "- Linked IS/C/E: IS-001\n",
        encoding="utf-8")
    (d / "coverage.json").write_text(json.dumps({"assets": [
        {"host": "app.example", "reachable": True, "stack": "kb:foobar-cms", "flags": ["LOGIN"]},
        {"host": "other.example", "reachable": True},
    ]}), encoding="utf-8")
    (d / "evidence.md").write_text("# Evidence\n\n## E-001\n- Front: F-001\n- Maturity: candidate\n", encoding="utf-8")
    (d / "decisions.md").write_text("# Decisions\n\n## D-001\n- Chosen front: F-001\n", encoding="utf-8")
    evidence_dir = d / "evidence"
    evidence_dir.mkdir()
    (evidence_dir / "large.js").write_bytes(
        (b"const route='/api/admin';\n" * 4096) + b"binary-tail\x00value\n"
    )
    (evidence_dir / "other.js").write_text("const other = true;\n", encoding="utf-8")
    (evidence_dir / "binary.bin").write_bytes(b"prefix\x00printable-secret\x00suffix")
    outside_artifact = d / "outside.bin"
    outside_artifact.write_bytes(b"outside")
    (evidence_dir / "escape.bin").symlink_to(outside_artifact)
    (d / "state").mkdir()
    (d / "state" / "operator_profile.json").write_text(json.dumps({
        "schema": 1,
        "decision_style": "autonomous_until_review",
        "rdt": {
            "role_profiles": {
                "web-auth": {"loop_budget": 7, "focus": "custom_auth_depth"}
            }
        },
        "retrospective_lessons": ["custom lesson"]
    }), encoding="utf-8")
    now = time.time()
    (d / "state" / "turn_contract.json").write_text(json.dumps({
        "schema": "xunji.turn_contract.v1",
        "mode": "EXECUTE",
        "session_id": "context-pack-session",
        "transcript_path": str(d / "context-pack-transcript.jsonl"),
        "prompt_sha256": "a" * 64,
        "prompt_excerpt": "operator continued with the default direct route",
        "memory_approved": False,
        "direct_egress_approved": True,
        "fanout_override": False,
        "origin_run": d.name,
        "bound_run": d.name,
        "updated_at": now,
        "coordination_signature": "b" * 64,
        "fanout_epoch_started_at": now,
        "fanout_epoch_id": "c" * 16,
    }), encoding="utf-8")
    pack = build_pack(d, front="F-001", role="web-auth", agent="A-web-auth-001",
                      kb_dir=kb, xday_dir=xday, weap_dir=weap)
    out = d / "context" / "F-001.web-auth.md"
    _atomic_write(out, pack)
    malformed = d / "malformed_profile"
    malformed.mkdir()
    (malformed / "frontier.md").write_text(
        "# Frontier\n\n### F-001\n- Front: app.example auth token\n- Status: open\n", encoding="utf-8")
    (malformed / "state").mkdir()
    (malformed / "state" / "operator_profile.json").write_text(json.dumps({
        "fallback_seconds": "later",
        "rdt": {
            "default_loop_budget": "many",
            "depth_pivot_after_low_cycles": "soon",
            "role_profiles": {
                "web-auth": {"loop_budget": "high", "focus": "custom_auth_depth"}
            }
        }
    }), encoding="utf-8")
    malformed_rdt = resolve_rdt_profile(
        malformed, role="web-auth",
        front_text=(malformed / "frontier.md").read_text(encoding="utf-8"))
    no_kb_summary = "\n".join(_knowledge_xday_summary([]))
    missing_public_summary = "\n".join(_knowledge_xday_summary(
        ["missing-public"], kb_dir=kb, xday_dir=xday, weap_dir=weap))
    global _knowledge_match
    saved_knowledge_match = _knowledge_match
    try:
        _knowledge_match = None
        matcher_unavailable_summary = "\n".join(_knowledge_xday_summary(
            ["foobar-cms"], kb_dir=kb, xday_dir=xday, weap_dir=weap))
    finally:
        _knowledge_match = saved_knowledge_match
    complete_role_bundle = _instruction_bundle.load_role_contract(
        "web-auth", root=ROOT)
    complete_role_template = complete_role_bundle["text"].strip()
    target_front = (
        "### F-001\n"
        "- Next autonomous move: Execute HTTP GET probe against "
        "http://127.0.0.1:18765 to confirm reachability\n"
    )
    prepared_probe = "\n".join(_prepared_capability_lines(
        d,
        effect="target",
        target="# Target\n- Target: http://127.0.0.1:18765\n",
        front_text=target_front,
        assets=["127.0.0.1:18765"],
        request_budget=1,
        lane_id="L-target-001",
        assignment_attempt=1,
    ))
    prepared_probe_zh = "\n".join(_prepared_capability_lines(
        d,
        effect="target",
        target="# Target\n- Target: http://127.0.0.1:18765\n",
        front_text=(
            "### F-001\n"
            "- Next autonomous move: 使用 probe.py GET http://127.0.0.1:18765 "
            "确认可达性并收集响应指纹\n"
        ),
        assets=["127.0.0.1:18765"],
        request_budget=1,
        lane_id="L-target-001",
        assignment_attempt=2,
    ))
    zero_budget_probe = "\n".join(_prepared_capability_lines(
        d, effect="target",
        target="# Target\n- Target: http://127.0.0.1:18765\n",
        front_text=target_front, assets=["127.0.0.1:18765"], request_budget=0,
        lane_id="L-target-001", assignment_attempt=3,
    ))
    wrong_asset_probe = "\n".join(_prepared_capability_lines(
        d, effect="target",
        target="# Target\n- Target: http://127.0.0.1:18765\n",
        front_text=target_front, assets=["other.example"], request_budget=1,
        lane_id="L-target-001", assignment_attempt=4,
    ))
    ambiguous_url_probe = "\n".join(_prepared_capability_lines(
        d, effect="target",
        target=("# Target\n- Target: http://127.0.0.1:18765\n"
                "- Target: http://127.0.0.1:18766\n"),
        front_text=(
            "### F-001\n- Next autonomous move: Execute HTTP GET probe against "
            "http://127.0.0.1:18765 and http://127.0.0.1:18766 for liveness\n"
        ),
        assets=["127.0.0.1:18765", "127.0.0.1:18766"], request_budget=1,
        lane_id="L-target-001", assignment_attempt=5,
    ))
    ambiguous_fallback_probe = "\n".join(_prepared_capability_lines(
        d, effect="target",
        target=("# Target\n- Target: http://127.0.0.1:18765\n"
                "- Target: http://127.0.0.1:18766\n"),
        front_text=(
            "### F-001\n- Next autonomous move: Execute HTTP GET probe for liveness\n"
        ),
        assets=["127.0.0.1:18765", "127.0.0.1:18766"], request_budget=1,
        lane_id="L-target-001", assignment_attempt=6,
    ))
    negative_target_probes = ["\n".join(_prepared_capability_lines(
        d, effect="target", target="# Target\n- Target: http://127.0.0.1:18765\n",
        front_text=f"### F-negative\n- Next autonomous move: {move}\n",
        assets=["127.0.0.1:18765"], request_budget=1,
        lane_id="L-target-negative", assignment_attempt=index,
    )) for index, move in enumerate((
        "Do not execute HTTP GET probe against http://127.0.0.1:18765; use saved evidence",
        "The GET liveness probe against http://127.0.0.1:18765 is already complete; do not repeat it",
        "禁止对 http://127.0.0.1:18765 进行 GET 探活，改读本地证据",
        "Use saved evidence rather than execute HTTP GET liveness probe against http://127.0.0.1:18765",
        "Execute local checks without sending an HTTP GET liveness probe to http://127.0.0.1:18765",
        "Execute all checks except the HTTP GET liveness probe against http://127.0.0.1:18765",
        "Execute local checks while avoiding the HTTP GET liveness probe against http://127.0.0.1:18765",
        "Execute all checks excluding the HTTP GET liveness probe against http://127.0.0.1:18765",
        "Run the local replay instead of the HTTP GET liveness probe against http://127.0.0.1:18765",
        "Execute all work other than the HTTP GET liveness probe against http://127.0.0.1:18765",
        "Execute local replay and forego the HTTP GET liveness probe against http://127.0.0.1:18765",
        "Execute local replay and eschew the HTTP GET liveness probe against http://127.0.0.1:18765",
        "If needed, execute HTTP GET liveness probe against http://127.0.0.1:18765",
        "Run HTTP GET liveness probe against http://127.0.0.1:18765 if credentials become available",
        "Run HTTP GET liveness probe against http://127.0.0.1:18765 when approval arrives",
        "Run HTTP GET liveness probe against http://127.0.0.1:18765 provided that the budget remains",
        "Run HTTP GET liveness probe against http://127.0.0.1:18765 as long as the window stays open",
        "执行 HTTP GET http://127.0.0.1:18765 探活，如果授权生效",
        "执行 HTTP GET http://127.0.0.1:18765 探活，若凭据可用",
        "执行 HTTP GET http://127.0.0.1:18765 探活，前提是预算仍然可用",
        "执行 HTTP GET http://127.0.0.1:18765 探活，只要维护窗口开放",
        "执行本地检查，除 http://127.0.0.1:18765 的 GET 探活以外",
        "执行本地检查，避免对 http://127.0.0.1:18765 进行 GET 探活",
        "执行本地回放，不做 http://127.0.0.1:18765 的 HTTP GET 探活",
        "执行本地检查，舍弃 http://127.0.0.1:18765 的 GET 探活",
    ), 10)]
    exact_url_probe = "\n".join(_prepared_capability_lines(
        d, effect="target", target="# Target\n- Target: 127.0.0.1:18765\n",
        front_text=("### F-exact\n- Next autonomous move: Execute HTTP GET liveness "
                    "probe against HTTP://127.0.0.1:18765/Exact?A=B\n"),
        assets=["127.0.0.1:18765"], request_budget=1,
        lane_id="L-target-exact", assignment_attempt=20,
    ))
    query_word_probe = "\n".join(_prepared_capability_lines(
        d, effect="target", target="# Target\n- Target: 127.0.0.1:18765\n",
        front_text=("### F-query-words\n- Next autonomous move: Run HTTP GET liveness "
                    "probe against http://127.0.0.1:18765/?if=ready&when=now\n"),
        assets=["127.0.0.1:18765"], request_budget=1,
        lane_id="L-target-query-words", assignment_attempt=23,
    ))
    tight_zh_condition_probe = "\n".join(_prepared_capability_lines(
        d, effect="target", target="# Target\n- Target: example.test\n",
        front_text=("### F-tight-zh-condition\n- Next autonomous move: "
                    "执行 HTTP GET 探活 https://example.test/，如果服务不可达\n"),
        assets=["example.test"], request_budget=1,
        lane_id="L-target-tight-zh-condition", assignment_attempt=24,
    ))
    long_lane_prefix = "L-" + "same-prefix-" * 8
    long_lane_candidates = [
        _target_probe_candidate(
            d, effect="target", front_text=target_front, request_budget=1,
            route="direct", lane_id=long_lane_prefix + suffix,
            assignment_attempt=20,
        )
        for suffix in ("alpha", "beta")
    ]
    barrier_mismatch_probe = "\n".join(_prepared_capability_lines(
        d, effect="target", target="# Target\n- Target: http://127.0.0.1:18765\n",
        front_text=target_front, assets=["127.0.0.1:18765"], request_budget=1,
        lane_id="L-target-barrier", assignment_attempt=21,
        lane={"infra_barrier": {
            "operation_class": "target_attempt",
            "action_fingerprint": "f" * 64,
        }},
    ))
    collision_lane = "L-target-collision"
    collision_lane_digest = hashlib.sha256(
        collision_lane.encode("utf-8")).hexdigest()[:12]
    collision_body = evidence_dir / (
        f"liveness-l-target-collision-{collision_lane_digest}-attempt-022.html"
    )
    collision_body.write_text("existing", encoding="utf-8")
    collision_probe = "\n".join(_prepared_capability_lines(
        d, effect="target", target="# Target\n- Target: http://127.0.0.1:18765\n",
        front_text=target_front, assets=["127.0.0.1:18765"], request_budget=1,
        lane_id=collision_lane, assignment_attempt=22,
    ))
    collision_body.unlink()
    def prepared_local(front_text: str) -> str:
        """Exercise active-run-only validators without creating a runs/ fixture."""
        saved_profile_rel = globals()["_profile_rel"]
        try:
            globals()["_profile_rel"] = lambda path: f"runs/{path.name}"
            return "\n".join(_prepared_capability_lines(
                d, effect="local_read", target="", front_text=front_text,
                assets=[], request_budget=0,
            ))
        finally:
            globals()["_profile_rel"] = saved_profile_rel

    artifact_front = (
        "### F-002\n"
        "- Next autonomous move: Inspect `evidence/large.js` as a large JavaScript "
        "bundle; search the literal, read a byte range, and extract strings\n"
        "- Search literal: /api/admin\n"
    )
    prepared_artifacts = prepared_local(artifact_front)
    explicit_range = prepared_local(
        "### F-range\n- Next autonomous move: Read `evidence/large.js` byte range "
        "with offset=65536 length=1024\n"
    )
    prepared_binary_strings = prepared_local(
        "### F-binary\n- Next autonomous move: Extract strings from "
        "`evidence/binary.bin` as a binary artifact\n"
    )
    negative_artifacts = [prepared_local(
        f"### F-local-negative\n- Next autonomous move: {move}\n"
    ) for move in (
        "Do not inspect `evidence/large.js`; the analysis is already complete",
        "不要分析 `evidence/large.js`，已经完成",
        "If needed, inspect `evidence/large.js` as a JavaScript bundle",
        "Read saved notes rather than inspect `evidence/large.js` as a JavaScript bundle",
        "Inspect all saved artifacts except `evidence/large.js` as a JavaScript bundle",
        "Read `evidence/large.js` without analyzing its JavaScript routes",
        "Read saved notes while avoiding analysis of `evidence/large.js` as a JavaScript bundle",
        "Inspect the report instead of `evidence/large.js` as a JavaScript bundle",
        "Inspect the report other than `evidence/large.js` as a JavaScript bundle",
        "Inspect the report and forego `evidence/large.js` JavaScript analysis",
        "Inspect the report and eschew `evidence/large.js` JavaScript analysis",
        "Inspect `evidence/large.js` if credentials become available",
        "Inspect `evidence/large.js` when approval arrives",
        "Inspect `evidence/large.js` provided that the budget remains",
        "Inspect `evidence/large.js` as long as the review window stays open",
        "检查 `evidence/large.js`，如果授权生效",
        "检查 `evidence/large.js`，若凭据可用",
        "检查 `evidence/large.js`，当维护窗口开启时",
        "检查 `evidence/large.js`，在授权生效时",
        "检查 `evidence/large.js`，前提是预算仍然可用",
        "检查 `evidence/large.js`，只要审查窗口开放",
        "读取本地说明，除 `evidence/large.js` 的 JS 分析以外",
        "读取本地说明，避免分析 `evidence/large.js` 的 JS 路由",
        "检查报告而非 `evidence/large.js` 这个 JavaScript 包",
        "读取报告，不含 `evidence/large.js` 的 JavaScript 分析",
    )]
    conditional_suffix_examples = (
        "Run HTTP GET liveness probe against http://127.0.0.1:18765 if credentials become available",
        "Run HTTP GET liveness probe against http://127.0.0.1:18765 when approval arrives",
        "Run HTTP GET liveness probe against http://127.0.0.1:18765 provided that the budget remains",
        "Run HTTP GET liveness probe against http://127.0.0.1:18765 as long as the window stays open",
        "Run HTTP GET https://example.test/ if stale; inspect evidence/a.js",
        "执行 HTTP GET 探活 https://example.test/，如果服务不可达",
        "检查 `evidence/large.js`，如果授权生效",
        "检查 `evidence/large.js`，若凭据可用",
        "检查 `evidence/large.js`，当维护窗口开启时",
        "检查 `evidence/large.js`，在授权生效时",
        "检查 `evidence/large.js`，前提是预算仍然可用",
        "检查 `evidence/large.js`，只要审查窗口开放",
    )
    nonconditional_object_examples = (
        "Run HTTP GET liveness probe against http://127.0.0.1:18765/?if=now&when=later",
        "Inspect evidence/if-when.js",
        "Inspect evidence/large.js for if-statement and when-handler nouns",
        "Inspect evidence/large.js to record the normal noun when",
        "检查 evidence/large.js 当前版本接口",
        "检查 evidence/large.js 若干普通路由",
        "Inspect evidence/large.js as a JavaScript bundle",
    )
    duplicate_next_move = prepared_local(
        "### F-duplicate\n"
        "- Next autonomous move: Inspect `evidence/large.js` as a JavaScript bundle\n"
        "- Next autonomous move: Do not inspect `evidence/large.js`\n"
    )
    duplicate_artifact_field = prepared_local(
        "### F-duplicate-artifact\n"
        "- Next autonomous move: Inspect the selected JavaScript bundle\n"
        "- Artifact: evidence/large.js\n"
        "- Artifact: evidence/other.js\n"
    )
    ambiguous_artifacts = prepared_local(
        "### F-003\n- Next autonomous move: Inspect byte ranges in "
        "`evidence/large.js` and `evidence/other.js`\n"
    )
    symlink_artifact = prepared_local(
        "### F-004\n- Next autonomous move: Inspect byte range in "
        "`evidence/escape.bin`\n"
    )
    keyword_only = "\n".join(_prepared_capability_lines(
        d, effect="target", target="# Target\n- Target: http://127.0.0.1:18765\n",
        front_text="### F-005\n- Next autonomous move: scan render exploit the target\n",
        assets=["127.0.0.1:18765"], request_budget=3,
    ))
    invalid_candidate = PreparedCapabilityCandidate(
        capability_id="read.artifact-view-search",
        purpose="invalid fixture",
        argv=("search", _profile_rel(d), "large.js", "bad`literal"),
    )
    unknown_candidate = PreparedCapabilityCandidate(
        capability_id="read.unknown",
        purpose="unknown fixture",
        argv=("status", _profile_rel(d)),
    )
    contract_path = d / "state" / "turn_contract.json"
    direct_contract = json.loads(contract_path.read_text(encoding="utf-8"))
    proxy_contract = dict(direct_contract)
    proxy_contract["direct_egress_approved"] = False
    proxy_contract["operator_intent"] = {"route": "proxy"}
    saved_turn_contract = globals()["_turn_contract"]
    try:
        # This unit exercises projection only. The normal loader independently
        # rejects partial contracts; supplying the typed projection here avoids
        # minting a fake historical keyset merely for a renderer fixture.
        globals()["_turn_contract"] = lambda _run_dir: {
            "operator_intent": {"route": "offline"},
        }
        prepared_offline_probe = "\n".join(_prepared_capability_lines(
            d, effect="target",
            target="# Target\n- Target: http://127.0.0.1:18765\n",
            front_text=target_front, assets=["127.0.0.1:18765"],
            request_budget=1,
            lane_id="L-target-001", assignment_attempt=30,
        ))
        globals()["_turn_contract"] = lambda _run_dir: proxy_contract
        prepared_proxy_probe = "\n".join(_prepared_capability_lines(
            d,
            effect="target",
            target="# Target\n- Target: http://127.0.0.1:18765\n",
            front_text=target_front,
            assets=["127.0.0.1:18765"],
            request_budget=1,
            lane_id="L-target-001", assignment_attempt=31,
        ))
        proxy_route_lines = "\n".join(_egress_contract_lines(d, effect="target"))
    finally:
        globals()["_turn_contract"] = saved_turn_contract
    contract_path.write_text(json.dumps(direct_contract), encoding="utf-8")
    lane_snapshot = {
        "id": "L-read-001",
        "front": "F-001",
        "role": "web-auth",
        "effect": "local_read",
        "assets": [],
        "request_budget": 0,
        "expected_evidence": "bounded artifact observations",
        "stop_condition": "one supported result or explicit barrier",
    }
    lane_pack = build_pack(
        d, front="F-001", role="web-auth", agent="A-web-auth-001",
        effect="local_read", lane_id="L-read-001", plan_digest="d" * 64,
        request_budget=0, lane=lane_snapshot,
        kb_dir=kb, xday_dir=xday, weap_dir=weap,
    )
    lane_mismatch_rejected = False
    try:
        build_pack(
            d, front="F-001", role="web-auth", effect="local_read",
            lane_id="L-other", request_budget=0, lane=lane_snapshot,
            kb_dir=kb, xday_dir=xday, weap_dir=weap,
        )
    except _instruction_bundle.InstructionBundleError:
        lane_mismatch_rejected = True
    frozen_context_path = d / "context" / "A-frozen-001.context.md"
    frozen_agent_path = d / "agents" / "A-frozen-001.md"
    frozen_agent_path.parent.mkdir()
    frozen_context_text = "# Frozen context\n\nexact recorded bytes\n"
    frozen_agent_text = "# Agent A-frozen-001\n"
    frozen_context_path.write_text(frozen_context_text, encoding="utf-8")
    frozen_agent_path.write_text(frozen_agent_text, encoding="utf-8")
    frozen_bundle, frozen_digest = _instruction_bundle.build_assignment_bundle(
        assignment="A-frozen-001", plan_digest="e" * 64,
        lane_id="L-frozen-001", role="web-auth",
        role_bundle=complete_role_bundle,
        scaffold_source=_instruction_bundle.load_scaffold_source(root=ROOT)["source"],
        context_path=str(frozen_context_path), context_text=frozen_context_text,
        agent_path=str(frozen_agent_path), agent_text=frozen_agent_text,
    )
    frozen_row = {
        "schema": "xunji.assignment.v1",
        "agent": "A-frozen-001", "plan_digest": "e" * 64,
        "lane_id": "L-frozen-001", "role": "web-auth",
        "context": str(frozen_context_path),
        "agent_file": str(frozen_agent_path),
        "instruction_bundle": frozen_bundle,
        "instruction_bundle_sha256": frozen_digest,
    }
    assignments_path = d / "state" / "assignments.json"

    def write_frozen_row(row: dict) -> None:
        assignments_path.write_text(
            json.dumps({"assignments": [row]}), encoding="utf-8",
        )

    def frozen_row_rejected(row: dict) -> bool:
        write_frozen_row(row)
        try:
            build_from_agent(d, "A-frozen-001")
        except SystemExit:
            return True
        return False

    write_frozen_row(frozen_row)
    frozen_replay = build_from_agent(d, "A-frozen-001")
    frozen_agent_path.write_text(
        frozen_agent_text + "\n## Lifecycle\n- Status: done\n",
        encoding="utf-8",
    )
    lifecycle_replay = build_from_agent(d, "A-frozen-001")
    frozen_context_path.write_text("tampered\n", encoding="utf-8")
    frozen_tamper_rejected = frozen_row_rejected(frozen_row)
    frozen_context_path.write_text(frozen_context_text, encoding="utf-8")
    path_tamper_row = json.loads(json.dumps(frozen_row))
    path_tamper_row["agent_file"] = str(frozen_context_path)
    frozen_path_tamper_rejected = frozen_row_rejected(path_tamper_row)
    descriptor_tamper_row = json.loads(json.dumps(frozen_row))
    descriptor_tamper_row["instruction_bundle"]["context"]["length"] += 1
    descriptor_tamper_row["instruction_bundle_sha256"] = (
        _instruction_bundle.canonical_digest(
            descriptor_tamper_row["instruction_bundle"],
        )
    )
    frozen_descriptor_tamper_rejected = frozen_row_rejected(
        descriptor_tamper_row,
    )
    bundle_tamper_row = json.loads(json.dumps(frozen_row))
    bundle_tamper_row["instruction_bundle"]["lane_id"] = "L-tampered"
    frozen_bundle_tamper_rejected = frozen_row_rejected(bundle_tamper_row)
    write_frozen_row(frozen_row)
    checks = [
        ("pack names front and role", "Context Pack F-001 / web-auth" in pack),
        ("pack includes matched coverage", "app.example" in pack and "kb:foobar-cms" in pack),
        ("pack includes knowledge pointer", "knowledge `foobar-cms`" in pack and "FooBar CMS" in pack),
        ("no-kb route uses built-in live lookup and defers writeback",
         "Read against exact" in no_kb_summary
         and "separate maintenance turn" in no_kb_summary
         and "knowledge_match.py" not in no_kb_summary),
        ("local xday pointer requires a matching public grounding entry",
         "withheld until a public grounding entry matches" in missing_public_summary
         and "local xday pointer" not in missing_public_summary
         and "missing-public.md" not in missing_public_summary),
        ("matcher import failure keeps the built-in live fallback",
         "offline matcher module unavailable" in matcher_unavailable_summary
         and "Read against exact" in matcher_unavailable_summary
         and "separate maintenance turn" in matcher_unavailable_summary),
        ("pack includes xday pointer without dumping note body", "local xday pointer" in pack and "local note" not in pack),
        ("pack includes evidence block", "E-001" in pack),
        ("target pack exposes the frozen direct-egress argv prefix",
         "This turn uses the default direct route" in "\n".join(
             _egress_contract_lines(d, effect="target"))
         and prepared_probe.count("XUNJI_PROXY_REQUIRED=0") == 1),
        ("explicit proxy route freezes proxy opt-in and stop-on-failure guidance",
         prepared_proxy_probe.count("XUNJI_PROXY_REQUIRED=1") == 1
         and "only a newer operator turn may restart" in proxy_route_lines),
        ("route-less historical proxy-default projection stays offline",
         _egress_route({"direct_egress_approved": False}) == "offline"),
        ("offline zero-budget mismatched-asset and ambiguous URL lanes expose zero target argv",
         all("target.probe" not in value and "XUNJI_PROXY_REQUIRED=" not in value
             for value in (
                 prepared_offline_probe, zero_budget_probe, wrong_asset_probe,
                 ambiguous_url_probe, ambiguous_fallback_probe,
             ))
         and all("No complete registry-backed argv" in value
                 for value in (
                     prepared_offline_probe, zero_budget_probe, wrong_asset_probe,
                     ambiguous_url_probe, ambiguous_fallback_probe,
                 ))),
        ("pack includes relevant threat hypothesis", "Relevant Hypotheses / Threat Hypotheses" in pack
         and "hidden admin API may expose cross-role data" in pack
         and "Linked IS/C/E: IS-001" in pack),
        ("pack includes personalized operator profile", "Operator Profile / Personalized RDT" in pack
         and "Recommended reasoning-loop budget: 7" in pack and "custom_auth_depth" in pack
         and "custom lesson" in pack),
        ("pack embeds the complete role template without front truncation",
         complete_role_template and complete_role_template in pack),
        ("pack records deterministic role provenance",
         complete_role_bundle["contract"]["composed_sha256"] in pack
         and complete_role_bundle["contract"]["manifest"]["sha256"] in pack
         and pack.count("<!-- xunji.agent-role-common.v1 -->") == 1),
        ("embedded role template cannot reintroduce Agent lifecycle commands",
         "workers.py heartbeat/finish" not in complete_role_template
         and "workers.py finish" not in complete_role_template
         and "Root/Single Synthesizer alone promotes" in complete_role_template
         and "workers.py heartbeat/finish" not in pack),
        ("malformed numeric profile values fall back safely",
         malformed_rdt["loop_budget"] == 6
         and malformed_rdt["fallback_seconds"] == DEFAULT_OPERATOR_PROFILE["fallback_seconds"]
         and malformed_rdt["depth_pivot_after_low_cycles"] == 3),
        ("pack includes output contract",
         "Maturity remains phenomenon/candidate" in pack
         and "generated Agent scaffold's `Final Return`" in pack),
        ("frozen lane evidence and stop condition are projected without changing authority",
         "Expected evidence: bounded artifact observations" in lane_pack
         and "Stop condition: one supported result or explicit barrier" in lane_pack
         and lane_mismatch_rejected),
        ("plan-bound lookup replays exact context across lifecycle status mutation",
         frozen_replay == frozen_context_text
         and lifecycle_replay == frozen_context_text),
        ("plan-bound replay rejects context path descriptor and bundle tamper",
         frozen_tamper_rejected
         and frozen_path_tamper_rejected
         and frozen_descriptor_tamper_rejected
         and frozen_bundle_tamper_rejected),
        ("target GET lane receives one registry-validated exact public argv",
         "## Prepared Registered Capabilities" in prepared_probe
         and "### 1. target.probe" in prepared_probe
         and "XUNJI_PROXY_REQUIRED=0 .venv/bin/python tools/probe.py GET "
         "http://127.0.0.1:18765" in prepared_probe
         and "GET - Target:" not in prepared_probe
         and "--run " in prepared_probe
         and "--no-redirect" in prepared_probe
         and "--headers" in prepared_probe
         and re.search(
             r"--save liveness-l-target-001-[0-9a-f]{12}-attempt-001\b",
             prepared_probe,
         ) is not None
         and _PREPARED_CAPABILITY_MARKER in prepared_probe),
        ("Chinese driver GET intent receives the same prepared probe argv",
         ".venv/bin/python tools/probe.py GET http://127.0.0.1:18765"
         in prepared_probe_zh),
        ("one explicit large artifact produces a stable maximum-three projection",
         prepared_artifacts.count(_PREPARED_CAPABILITY_MARKER) == 3
         and prepared_artifacts.index("read.js-inventory")
         < prepared_artifacts.index("read.artifact-view-search")
         < prepared_artifacts.index("read.artifact-view-range")
         and "read.artifact-view-strings" not in prepared_artifacts
         and "/api/admin" in prepared_artifacts),
        ("explicit range intent is preserved and binary strings remain separately discoverable",
         "--offset 65536 --length 1024" in explicit_range
         and "read.artifact-view-strings" in prepared_binary_strings),
        ("direct-object suffix predicate distinguishes conditions from object text and nouns",
         all(_direct_action_has_condition_suffix(value)
             for value in conditional_suffix_examples)
         and not any(_direct_action_has_condition_suffix(value)
                     for value in nonconditional_object_examples)),
        ("negative completed and conditional-only prose exposes no prepared capability",
         all("No complete registry-backed argv" in value
             and _PREPARED_CAPABILITY_MARKER not in value
             for value in (*negative_target_probes, *negative_artifacts))),
        ("duplicate intent or artifact fields are ambiguous and expose nothing",
         all("No complete registry-backed argv" in value
             and _PREPARED_CAPABILITY_MARKER not in value
             for value in (duplicate_next_move, duplicate_artifact_field))),
        ("target projection preserves the exact frozen URL spelling",
         "HTTP://127.0.0.1:18765/Exact?A=B" in exact_url_probe),
        ("URL query words remain data while tight Chinese conditional tails expose nothing",
         "http://127.0.0.1:18765/?if=ready&when=now" in query_word_probe
         and _PREPARED_CAPABILITY_MARKER in query_word_probe
         and "No complete registry-backed argv" in tight_zh_condition_probe
         and _PREPARED_CAPABILITY_MARKER not in tight_zh_condition_probe
         and _exact_http_urls(
             "执行 HTTP GET 探活 https://example.test/，如果服务不可达",
         ) == ["https://example.test/"]),
        ("long lane ids cannot collide after filename shortening",
         all(candidate is not None for candidate in long_lane_candidates)
         and long_lane_candidates[0].argv != long_lane_candidates[1].argv),
        ("existing artifact groups and mismatched target barriers fail closed",
         "No complete registry-backed argv" in collision_probe
         and "No complete registry-backed argv" in barrier_mismatch_probe),
        ("ambiguous or symlink artifacts and target keywords do not guess argv",
         all("No complete registry-backed argv" in value
             for value in (ambiguous_artifacts, symlink_artifact, keyword_only))
         and "target.scan" not in keyword_only
         and "target.render" not in keyword_only
         and "target.exploit" not in keyword_only),
        ("unknown/effect-invalid/unsafe candidate values fail closed",
         _candidate_is_valid(
             invalid_candidate, run_dir=d, lane_effect="local_read",
             assets=[], route="direct",
         ) is None
         and _candidate_is_valid(
             unknown_candidate, run_dir=d, lane_effect="local_read",
             assets=[], route="direct",
         ) is None
         and _candidate_is_valid(
             PreparedCapabilityCandidate(
                 capability_id="read.artifact-view-range", purpose="effect fixture",
                 argv=("range", _profile_rel(d), "large.js", "--offset", "0"),
             ),
             run_dir=d, lane_effect="", assets=[], route="direct",
         ) is None),
        ("projection never emits proxy values or authorization-like flags",
         "XUNJI_PROXY=" not in prepared_probe
         and "enabled=true" not in prepared_probe
         and "authorized=true" not in prepared_probe),
        ("atomic write created file", out.exists() and out.read_text(encoding="utf-8") == pack),
    ]
    bad = [n for n, ok in checks if not ok]
    for n, ok in checks:
        print(("ok   " if ok else "FAIL ") + n)
    print("context_pack selftest " + ("passed" if not bad else f"FAILED ({len(bad)})"))
    return 0 if not bad else 1


def main() -> int:
    ap = argparse.ArgumentParser(description="Build a minimal subagent context pack from a run dir.")
    ap.add_argument("run_dir", nargs="?")
    ap.add_argument("--front")
    ap.add_argument("--role")
    ap.add_argument("--agent")
    ap.add_argument("--out")
    ap.add_argument("--selftest", action="store_true")
    args = ap.parse_args()
    if args.selftest:
        return _selftest()
    if not args.run_dir:
        ap.error("run_dir is required")
    run_dir = resolve_run_dir(args.run_dir)
    if args.agent and not (args.front or args.role):
        text = build_from_agent(run_dir, args.agent)
    else:
        if not (args.front and args.role):
            ap.error("pass --front and --role, or --agent")
        text = build_pack(run_dir, front=args.front, role=args.role, agent=args.agent or "")
    if args.out:
        _atomic_write(Path(args.out), text)
        print(args.out)
    else:
        print(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
