#!/usr/bin/env python3
"""Single typed registry for trusted Xunji Python capabilities.

The registry classifies an exact script + argv pair by effect and by the
mandatory services it must traverse.  It does not grant operator authority and
does not execute anything.  Callers must still enforce the active turn, run,
scope, and actor bindings before using a matched capability.
"""
from __future__ import annotations

from dataclasses import dataclass
import ipaddress
import json
from pathlib import Path
import re
import sys
from typing import Iterable
from urllib.parse import urlsplit


ROOT = Path(__file__).resolve().parents[2]

EFFECTS = frozenset({
    "local_read", "local_verify", "control", "target",
    "model_egress", "repo_mutation",
})
SCOPE_POLICIES = frozenset({"none", "active_run", "target_assets", "review_scope"})
PRIVACY_POLICIES = frozenset({"none", "target_egress", "model_egress"})
PROXY_POLICIES = frozenset({"none", "engagement"})
GUARD_POLICIES = frozenset({"none", "target"})
RECORDER_POLICIES = frozenset({
    "none", "control_journal", "target_artifact", "review_receipt",
})
TARGET_ENV = ("LANG", "LC_ALL", "PYTHONIOENCODING", "PYTHONUTF8",
              "XUNJI_PROXY", "XUNJI_PROXY_REQUIRED")


@dataclass(frozen=True)
class CapabilitySpec:
    id: str
    script: str
    effect: str
    argv_validator: str
    allowed_env: tuple[str, ...]
    scope: str
    privacy: str
    proxy: str
    guard: str
    recorder: str
    root_direct_eligible: bool = False

    def path(self, root: Path = ROOT) -> Path:
        return (root / self.script).resolve()


@dataclass(frozen=True)
class TargetReference:
    """One outbound target-bearing argv value from a validated capability."""

    value: str
    role: str = "primary"
    allow_bare: bool = False


def target_endpoint(
    reference: TargetReference,
) -> tuple[str, int | None] | None:
    """Normalize one registry-declared destination for every gate/receipt user."""
    raw = str(reference.value or "").strip()
    if not raw or len(raw.encode("utf-8")) > 8192 \
            or re.search(r"[\x00-\x20\x7f]", raw):
        return None
    has_scheme = bool(re.match(r"(?i)^https?://", raw))
    if not has_scheme and not reference.allow_bare:
        return None
    if has_scheme and re.match(
        r"(?i)^https?://(?:localhost|[a-z0-9.-]+|\[[0-9a-f:.]+\])"
        r"(?::\d{1,5})?[\u3400-\u4dbf\u4e00-\u9fff]",
        raw,
    ):
        return None
    try:
        parsed = urlsplit(raw if has_scheme else "//" + raw)
        port = parsed.port
    except ValueError:
        return None
    if parsed.username is not None or parsed.password is not None \
            or parsed.netloc.endswith(":"):
        return None
    if has_scheme and (parsed.scheme.lower() not in {"http", "https"}
                       or not parsed.netloc):
        return None
    host = str(parsed.hostname or "").strip().lower().rstrip(".")
    if not host or port is not None and not (1 <= port <= 65535):
        return None
    try:
        host = ipaddress.ip_address(host).compressed.lower()
    except ValueError:
        try:
            host = host.encode("idna").decode("ascii").lower()
        except UnicodeError:
            return None
        if len(host) > 253 or any(
                not label or len(label) > 63 or not re.fullmatch(
                    r"[a-z0-9](?:[a-z0-9-]*[a-z0-9])?", label)
                for label in host.split(".")):
            return None
    if has_scheme and port is None:
        port = 443 if parsed.scheme.lower() == "https" else 80
    return host, port


def _spec(
    capability_id: str,
    script: str,
    effect: str,
    validator: str,
    *,
    allowed_env: tuple[str, ...] = (),
    scope: str = "none",
    privacy: str = "none",
    proxy: str = "none",
    guard: str = "none",
    recorder: str = "none",
    root_direct_eligible: bool = False,
) -> CapabilitySpec:
    return CapabilitySpec(
        capability_id, script, effect, validator, allowed_env,
        scope, privacy, proxy, guard, recorder, root_direct_eligible,
    )


_SELFTEST_SCRIPTS = (
    "tools/selftest_all.py", "tools/check_rules.py", "tools/check_hook.py",
    "tools/check_runtime_boundary.py", "tools/check_templates.py",
    "tools/harness/command_shape.py", "tools/harness/guard.py",
    "tools/harness/proxy.py",
    "tools/harness/maintenance_authority.py", "tools/harness/output_layout.py",
    "tools/harness/privacy.py", "tools/harness/subagent_stop_ingress.py",
    "tools/setup_source.py", "tools/run_model.py", "tools/runtime_receipts.py",
    "tools/turn_contract.py", "tools/context_pack.py",
    "tools/work_plan.py", "tools/workers.py",
    "tools/contract_schema.py", "tools/completion_transaction.py",
    "tools/barrier_state.py", "tools/artifact_view.py",
    "tools/anti_drift.py",
    "tools/timestamp_gate.py", "tools/check_run.py",
    "tools/coverage_matrix.py", "tools/ingest_recon.py",
    "tools/loop_bootstrap.py", "tools/loop_journal.py", "tools/loop_state.py",
    "tools/progress_ledger.py", "tools/run_controller.py",
    "tools/session_handoff.py", "tools/setup_run.py",
    "tools/scope_admission.py", "tools/xunji_statusline.py",
    "tools/probe.py", "tools/render.py", "tools/scan.py", "tools/replay.py",
    "tools/classify_hosts.py", "tools/fetch_assets.py", "tools/exploit.py",
    "tools/clean_scratch.py", "tools/migrate_output_artifacts.py",
    ".claude/hooks/ip_blacklist.py", ".claude/hooks/output_gate.py",
    ".claude/hooks/run_gate.py", ".claude/hooks/safety_gate.py",
    "sentinel/replay.py", "sentinel/verify_layers.py",
)


def _verify_id(script: str) -> str:
    return "verify." + Path(script).with_suffix("").as_posix().replace(
        "/", ".").replace("_", "-")


CAPABILITIES: tuple[CapabilitySpec, ...] = (
    *tuple(_spec(
        _verify_id(script),
        script, "local_verify",
        "selftest-all" if script == "tools/selftest_all.py"
        else "no-args" if script in {
            "tools/check_rules.py", "tools/check_hook.py",
            "tools/check_runtime_boundary.py", "tools/check_templates.py",
            "tools/harness/command_shape.py", "tools/harness/guard.py",
            "tools/harness/privacy.py", "sentinel/replay.py",
            "sentinel/verify_layers.py",
        } else "selftest",
    ) for script in _SELFTEST_SCRIPTS),
    _spec("maintenance.contract-schema-prepare", "tools/contract_schema.py",
          "repo_mutation", "contract-schema-prepare"),
    _spec("maintenance.contract-schema-publish", "tools/contract_schema.py",
          "repo_mutation", "contract-schema-publish"),
    _spec("maintenance.contract-schema-discard", "tools/contract_schema.py",
          "repo_mutation", "contract-schema-discard"),
    _spec("read.contract-schema-help", "tools/contract_schema.py",
          "local_read", "contract-schema-help"),
    _spec("read.timestamp-gate", "tools/timestamp_gate.py", "local_read",
          "timestamp-gate", root_direct_eligible=True),
    _spec("read.anti-drift-semantic-status", "tools/anti_drift.py", "local_read",
          "anti-drift-semantic-status", scope="active_run",
          root_direct_eligible=True),
    _spec("control.anti-drift-reason-pass", "tools/anti_drift.py", "control",
          "anti-drift-record-reason-pass", scope="active_run",
          recorder="control_journal"),
    _spec("verify.check-run", "tools/check_run.py", "local_verify",
          "check-run-offline", scope="active_run", root_direct_eligible=True),
    _spec("target.check-run-replay", "tools/check_run.py", "target",
          "check-run-replay", allowed_env=TARGET_ENV, scope="target_assets",
          privacy="target_egress", proxy="engagement", guard="target",
          recorder="target_artifact"),
    _spec("review.check-run-auto", "tools/check_run.py", "model_egress",
          "check-run-review", scope="review_scope", privacy="model_egress",
          recorder="review_receipt"),
    _spec("read.peer-review-backends", "tools/peer_review.py", "local_read",
          "peer-review-list"),
    _spec("verify.peer-review", "tools/peer_review.py", "local_verify",
          "selftest"),
    _spec("control.peer-review-bundle", "tools/peer_review.py", "control",
          "peer-review-bundle", scope="review_scope",
          recorder="review_receipt"),
    _spec("control.peer-review-resolve", "tools/peer_review.py", "control",
          "peer-review-resolve", scope="active_run",
          recorder="review_receipt"),
    _spec("review.peer-review", "tools/peer_review.py", "model_egress",
          "peer-review-model", scope="review_scope", privacy="model_egress",
          recorder="review_receipt"),
    _spec("read.completion-transaction-status",
          "tools/completion_transaction.py", "local_read",
          "completion-transaction-status", scope="active_run"),
    _spec("control.completion-transaction-adopt-policy",
          "tools/completion_transaction.py", "control",
          "completion-transaction-adopt-policy", scope="active_run",
          recorder="control_journal"),
    _spec("control.completion-transaction-prepare",
          "tools/completion_transaction.py", "control",
          "completion-transaction-prepare", scope="active_run",
          recorder="control_journal"),
    _spec("control.completion-transaction-commit",
          "tools/completion_transaction.py", "control",
          "completion-transaction-commit", scope="active_run",
          recorder="control_journal"),
    _spec("control.completion-transaction-reopen",
          "tools/completion_transaction.py", "control",
          "completion-transaction-reopen", scope="active_run",
          recorder="control_journal"),
    _spec("read.infra-barrier-status", "tools/barrier_state.py",
          "local_read", "barrier-state-status", scope="active_run"),
    _spec("read.infra-barrier-check", "tools/barrier_state.py",
          "local_read", "barrier-state-check", scope="active_run"),
    _spec("control.infra-barrier-observe", "tools/barrier_state.py",
          "control", "barrier-state-observe", scope="active_run",
          recorder="control_journal"),
    _spec("control.infra-barrier-clear", "tools/barrier_state.py",
          "control", "barrier-state-clear", scope="active_run",
          recorder="control_journal"),
    _spec("read.artifact-view-range", "tools/artifact_view.py",
          "local_read", "artifact-view-range", scope="active_run"),
    _spec("read.artifact-view-search", "tools/artifact_view.py",
          "local_read", "artifact-view-search", scope="active_run"),
    _spec("read.artifact-view-strings", "tools/artifact_view.py",
          "local_read", "artifact-view-strings", scope="active_run"),
    _spec("read.work-plan", "tools/work_plan.py", "local_read",
          "work-plan-status", scope="active_run"),
    _spec("control.work-plan", "tools/work_plan.py", "control",
          "work-plan-commit", scope="active_run", recorder="control_journal"),
    _spec("control.work-plan-legacy-migration", "tools/work_plan.py", "control",
          "work-plan-migrate-legacy", scope="active_run",
          recorder="control_journal"),
    _spec("read.workers-help", "tools/workers.py", "local_read",
          "workers-help"),
    _spec("read.workers", "tools/workers.py", "local_read",
          "workers-read", scope="active_run"),
    _spec("control.workers-cancel-unlaunched", "tools/workers.py", "control",
          "workers-cancel-unlaunched", scope="active_run",
          recorder="control_journal"),
    _spec("control.workers-settle-stopped", "tools/workers.py", "control",
          "workers-settle-stopped", scope="active_run",
          recorder="control_journal"),
    _spec("control.workers-settle-stream-stalled", "tools/workers.py", "control",
          "workers-settle-stream-stalled", scope="active_run",
          recorder="control_journal"),
    _spec("control.workers-recover-hook-failed-stop", "tools/workers.py", "control",
          "workers-recover-hook-failed-stop", scope="active_run",
          recorder="control_journal"),
    _spec("control.workers", "tools/workers.py", "control",
          "workers-control", scope="active_run", recorder="control_journal"),
    _spec("control.graph", "tools/graph.py", "control", "one-run",
          scope="active_run", recorder="control_journal"),
    _spec("read.coverage-matrix", "tools/coverage_matrix.py", "local_read",
          "coverage-read", scope="active_run"),
    _spec("control.coverage-matrix", "tools/coverage_matrix.py", "control",
          "coverage-write", scope="active_run", recorder="control_journal"),
    _spec("read.ingest-recon", "tools/ingest_recon.py", "local_read",
          "ingest-read"),
    _spec("control.ingest-recon", "tools/ingest_recon.py", "control",
          "ingest-write", scope="active_run", recorder="control_journal"),
    _spec("read.loop-bootstrap-prepare", "tools/loop_bootstrap.py", "local_read",
          "loop-bootstrap-prepare"),
    _spec("control.loop-bootstrap", "tools/loop_bootstrap.py", "control",
          "loop-bootstrap-control", recorder="control_journal"),
    _spec("read.loop-journal", "tools/loop_journal.py", "local_read",
          "loop-journal-read", scope="active_run"),
    _spec("control.loop-journal", "tools/loop_journal.py", "control",
          "loop-journal-control", scope="active_run", recorder="control_journal"),
    _spec("read.loop-state", "tools/loop_state.py", "local_read",
          "state-read", scope="active_run"),
    _spec("control.loop-state", "tools/loop_state.py", "control",
          "loop-state-write", scope="active_run", recorder="control_journal"),
    _spec("read.progress-ledger", "tools/progress_ledger.py", "local_read",
          "state-read", scope="active_run"),
    _spec("control.progress-ledger", "tools/progress_ledger.py", "control",
          "progress-write", scope="active_run", recorder="control_journal"),
    _spec("read.run-controller", "tools/run_controller.py", "local_read",
          "state-read", scope="active_run"),
    _spec("control.run-controller", "tools/run_controller.py", "control",
          "controller-write", scope="active_run", recorder="control_journal"),
    _spec("read.session-handoff", "tools/session_handoff.py", "local_read",
          "session-pickup", scope="active_run"),
    _spec("control.session-handoff", "tools/session_handoff.py", "control",
          "session-write", scope="active_run", recorder="control_journal"),
    _spec("control.setup-run", "tools/setup_run.py", "control",
          "setup-run-control", recorder="control_journal"),
    _spec("target.setup-run-classify", "tools/setup_run.py", "target",
          "setup-run-classify", allowed_env=TARGET_ENV,
          scope="target_assets", privacy="target_egress",
          proxy="engagement", guard="target",
          recorder="target_artifact"),
    _spec("read.statusline", "tools/xunji_statusline.py", "local_read",
          "statusline-read"),
    _spec("control.statusline", "tools/xunji_statusline.py", "control",
          "statusline-control", recorder="control_journal"),
    _spec("read.run-model", "tools/run_model.py", "local_read", "one-run",
          scope="active_run", root_direct_eligible=True),
    _spec("read.runtime-receipts", "tools/runtime_receipts.py", "local_read",
          "runtime-receipts-read", scope="active_run"),
    _spec("control.runtime-receipts-reproject", "tools/runtime_receipts.py",
          "control", "runtime-receipts-reproject", scope="active_run",
          recorder="control_journal"),
    _spec("control.runtime-receipts-quarantine", "tools/runtime_receipts.py",
          "control", "runtime-receipts-quarantine", scope="active_run",
          recorder="control_journal"),
    _spec("control.scope-admission", "tools/scope_admission.py", "control",
          "scope-admission", scope="active_run", recorder="control_journal"),
    _spec("target.probe", "tools/probe.py", "target", "probe-live",
          allowed_env=TARGET_ENV, scope="target_assets",
          privacy="target_egress", proxy="engagement", guard="target",
          recorder="target_artifact"),
    _spec("target.render", "tools/render.py", "target", "render-live",
          allowed_env=TARGET_ENV, scope="target_assets",
          privacy="target_egress", proxy="engagement", guard="target",
          recorder="target_artifact"),
    _spec("target.render-eval", "tools/render.py", "target", "render-eval",
          allowed_env=TARGET_ENV, scope="target_assets",
          privacy="target_egress", proxy="engagement", guard="target",
          recorder="target_artifact"),
    _spec("target.scan", "tools/scan.py", "target", "scan-live",
          allowed_env=TARGET_ENV, scope="target_assets",
          privacy="target_egress", proxy="engagement", guard="target",
          recorder="target_artifact"),
    _spec("target.replay", "tools/replay.py", "target", "replay-live",
          allowed_env=TARGET_ENV, scope="target_assets",
          privacy="target_egress", proxy="engagement", guard="target",
          recorder="target_artifact"),
    _spec("target.replay-force", "tools/replay.py", "target", "replay-force",
          allowed_env=TARGET_ENV, scope="target_assets",
          privacy="target_egress", proxy="engagement", guard="target",
          recorder="target_artifact"),
    _spec("target.rerun-deferred", "tools/rerun_deferred.py", "target",
          "rerun-deferred", allowed_env=TARGET_ENV, scope="target_assets",
          privacy="target_egress", proxy="engagement", guard="target",
          recorder="target_artifact"),
    _spec("target.fetch-assets", "tools/fetch_assets.py", "target",
          "fetch-assets", allowed_env=TARGET_ENV, scope="target_assets",
          privacy="target_egress", proxy="engagement", guard="target",
          recorder="target_artifact"),
    _spec("target.classify-hosts", "tools/classify_hosts.py", "target",
          "classify-hosts", allowed_env=TARGET_ENV, scope="target_assets",
          privacy="target_egress", proxy="engagement", guard="target",
          recorder="target_artifact"),
    _spec("target.cdn-bypass", "tools/cdn_bypass.py", "target",
          "cdn-bypass", allowed_env=TARGET_ENV, scope="target_assets",
          privacy="target_egress", proxy="engagement", guard="target",
          recorder="target_artifact"),
    _spec("target.exploit-check", "tools/exploit.py", "target", "exploit-check",
          allowed_env=TARGET_ENV, scope="target_assets",
          privacy="target_egress", proxy="engagement", guard="target",
          recorder="target_artifact"),
    _spec("target.exploit-delivery", "tools/exploit.py", "target", "exploit-delivery",
          allowed_env=TARGET_ENV, scope="target_assets",
          privacy="target_egress", proxy="engagement", guard="target",
          recorder="target_artifact"),
)


def _bounded(args: tuple[str, ...]) -> bool:
    return len(args) <= 256 and all(
        len(value.encode("utf-8", "replace")) <= 256 * 1024
        and "\x00" not in value
        for value in args
    )


def _one_run(args: tuple[str, ...]) -> bool:
    return len(args) == 1 and bool(args[0]) and not args[0].startswith("-")


def _validate_contract_schema_action(
    args: tuple[str, ...], *, action: str,
) -> bool:
    return bool(
        len(args) == 2
        and args[0] == action
        and re.fullmatch(
            r"[A-Za-z0-9][A-Za-z0-9._-]*\.schema\.json", args[1])
    )


def _options(
    args: tuple[str, ...],
    *,
    values: dict[str, set[str] | None],
    flags: set[str],
    repeatable: set[str] = frozenset(),
    positionals: int = 0,
) -> tuple[bool, dict[str, list[str]], list[str]]:
    seen: dict[str, list[str]] = {}
    raw_positionals: list[str] = []
    index = 0
    while index < len(args):
        token = args[index]
        if token in flags:
            if token in seen:
                return False, {}, []
            seen[token] = []
            index += 1
            continue
        if token in values:
            if token in seen and token not in repeatable:
                return False, {}, []
            if index + 1 >= len(args):
                return False, {}, []
            value = args[index + 1]
            choices = values[token]
            if value.startswith("-") or (choices is not None and value not in choices):
                return False, {}, []
            seen.setdefault(token, []).append(value)
            index += 2
            continue
        if token.startswith("-") or len(raw_positionals) >= positionals:
            return False, {}, []
        raw_positionals.append(token)
        index += 1
    return len(raw_positionals) == positionals, seen, raw_positionals


_PROBE_VALUE_OPTIONS: dict[str, set[str] | None] = {
    "--data": None, "--data-file": None, "--data-json-file": None,
    "--value-json": None, "--value-json-file": None,
    "--preflight-get": None, "--preflight-save": None,
    "--extract-csrf": None, "--csrf-field": None,
    "--cookie-jar": None, "-H": None, "--header": None,
    "--auth-key": None, "--timeout": None, "--tag": None,
    "--save": None, "--run": None, "--proxy": None,
    "--retry": None, "--retry-wait": None, "--range": None,
    "--chunk-size": None, "--samples": None,
}
_PROBE_FLAG_OPTIONS = {
    "--allow-sensitive-auth", "--allow-legacy-cleanup", "--headers",
    "--no-redirect", "--save-chunks",
}
_RENDER_VALUE_OPTIONS: dict[str, set[str] | None] = {
    "--eval": None, "--eval-wait": None, "--out": None,
    "--run": None, "--wait": {"load", "domcontentloaded", "networkidle"},
    "--wait-sec": None, "--timeout": None, "--proxy": None,
    "--cookie": None, "--cookies-file": None, "--save": None,
}
_RENDER_FLAG_OPTIONS = {
    "--stealth", "--allow-sensitive-auth", "--screenshot",
}
_FETCH_ASSETS_VALUE_OPTIONS: dict[str, set[str] | None] = {
    "--html": None, "--base": None, "--out": None, "--run": None,
    "--timeout": None,
}
_CDN_BYPASS_VALUE_OPTIONS: dict[str, set[str] | None] = {
    "--proxy": None,
}
_CDN_BYPASS_FLAG_OPTIONS = {"--json"}
_EXPLOIT_VALUE_OPTIONS: dict[str, set[str] | None] = {
    "--target": None, "--payload": None, "--cmd": None, "--run": None,
}
_EXPLOIT_FLAG_OPTIONS = {"--check"}


def _validate_coverage(args: tuple[str, ...], *, write: bool) -> bool:
    ok, seen, _pos = _options(
        args, values={}, flags={"--json", "--write", "--sync-coverage"},
        positionals=1,
    )
    mutating = bool({"--write", "--sync-coverage"} & set(seen))
    return ok and mutating is write


def _validate_ingest(args: tuple[str, ...], *, write: bool) -> bool:
    ok, seen, _pos = _options(
        args, values={"--out": None}, flags=set(), positionals=1,
    )
    return ok and ("--out" in seen) is write


def _validate_loop_bootstrap(args: tuple[str, ...], *, prepare: bool) -> bool:
    if args.count("--resume") == 1:
        return not prepare and len(args) == 2 and args[0] == "--resume" \
            and bool(args[1]) and not args[1].startswith("-")
    if "--source" in args:
        ok, seen, _pos = _options(
            args,
            values={
                "--source": None,
                "--type": {"auto", "run", "url", "recon-json", "file"},
                "--ai": {"off", "external"}, "--ai-provider": None,
                "--ai-model": None, "--candidate-json": None,
            },
            flags={"--prepare-normalizer"},
        )
        if not ok or "--source" not in seen \
                or ("--prepare-normalizer" in seen) is not prepare:
            return False
        ai_mode = (seen.get("--ai") or ["off"])[0]
        if ai_mode == "off":
            return not prepare and not ({
                "--ai-provider", "--ai-model", "--candidate-json",
            } & set(seen))
        return bool(
            "--ai-provider" in seen and "--ai-model" in seen
            and (("--candidate-json" in seen) != prepare)
        )
    return not prepare and len(args) == 2 and all(
        bool(value) and not value.startswith("-") for value in args)


def _validate_setup_run(args: tuple[str, ...], *, classify: bool) -> bool:
    cases = (2,) if classify else (1, 2)
    for positionals in cases:
        ok, seen, pos = _options(
            args,
            values={"--target": None, "--date": None},
            flags={"--classify"}, positionals=positionals,
        )
        if not ok or ("--classify" in seen) is not classify:
            continue
        if classify and (positionals != 2 or "--target" in seen):
            continue
        if not classify and ((positionals == 1) != ("--target" in seen)):
            continue
        if "--date" in seen and not re.fullmatch(r"\d{8}", seen["--date"][0]):
            continue
        if pos and re.fullmatch(r"[A-Za-z0-9_-]+", pos[0]):
            return True
    return False


def _validate_loop_journal(args: tuple[str, ...], *, read: bool) -> bool:
    events = {
        "start", "phase-start", "phase-end", "plan", "action",
        "write-result", "interrupt", "resume", "end", "status",
    }
    ok, seen, pos = _options(
        args,
        values={"--phase": None, "--note": None, "--next-action": None},
        flags={"--json"},
        positionals=2,
    )
    if not ok or pos[1] not in events or (pos[1] == "status") is not read:
        return False
    phase_event = pos[1] in {"phase-start", "phase-end"}
    if ("--phase" in seen) is not phase_event:
        return False
    if "--next-action" in seen and pos[1] != "end":
        return False
    if read and ("--note" in seen or "--phase" in seen
                 or "--next-action" in seen):
        return False
    return True


def _validate_state_tool(
    args: tuple[str, ...], *, write_flag: str = "",
) -> bool:
    flags = {"--json"} | ({write_flag} if write_flag else set())
    ok, seen, _pos = _options(args, values={}, flags=flags, positionals=1)
    return ok and (not write_flag or write_flag in seen)


def _validate_session(args: tuple[str, ...], *, action: str) -> bool:
    return len(args) == 2 and args[0] == action \
        and bool(args[1]) and not args[1].startswith("-")


def _validate_statusline(args: tuple[str, ...], *, control: bool) -> bool:
    if not control:
        return not args
    if args == ("--clear-active",):
        return True
    return len(args) == 2 and args[0] == "--set-active" \
        and bool(args[1]) and not args[1].startswith("-")


def _validate_scope_admission(args: tuple[str, ...]) -> bool:
    return len(args) == 3 and args[1] == "--assets" \
        and bool(args[0]) and bool(args[2]) \
        and not args[0].startswith("-") and not args[2].startswith("-")


def _validate_probe(args: tuple[str, ...]) -> bool:
    for positionals in (2, 3):
        ok, _seen, pos = _options(
            args, values=_PROBE_VALUE_OPTIONS, flags=_PROBE_FLAG_OPTIONS,
            repeatable={"-H", "--header"}, positionals=positionals,
        )
        if not ok:
            continue
        method = pos[0].upper()
        if not re.fullmatch(r"[A-Z][A-Z0-9_-]{0,31}", method):
            continue
        if (method == "DIFF") == (positionals == 3):
            return True
    return False


def _validate_render(args: tuple[str, ...], *, eval_mode: bool) -> bool:
    ok, seen, _pos = _options(
        args,
        values=_RENDER_VALUE_OPTIONS,
        flags=_RENDER_FLAG_OPTIONS,
        repeatable={"--cookie"}, positionals=1,
    )
    return ok and "--run" in seen and ("--eval" in seen) is eval_mode


def _validate_scan(args: tuple[str, ...]) -> bool:
    # Scanner argv is deliberately closed: one active run, one built-in scanner,
    # and one explicit absolute URL.  Scanner-native flags can name target files,
    # remote template URLs, output paths, resumes, and configuration profiles, so
    # none may cross this capability boundary as model-controlled tail argv.
    if len(args) not in {4, 6} or args[0] != "--run" \
            or not args[1] or args[1].startswith("-"):
        return False
    index = 2
    if len(args) == 6:
        if args[index] != "--name" \
                or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}", args[index + 1]):
            return False
        index += 2
    if args[index] not in {"sqlmap", "nuclei"}:
        return False
    target = args[index + 1]
    try:
        parsed = urlsplit(target)
    except ValueError:
        return False
    return bool(
        parsed.scheme in {"http", "https"} and parsed.netloc and parsed.hostname
        and not parsed.username and not parsed.password
    )


def _validate_replay(args: tuple[str, ...], *, force: bool) -> bool:
    ok, seen, _pos = _options(
        args, values={"--timeout": None, "--scope": None},
        flags={"--force"}, positionals=1,
    )
    return ok and ("--force" in seen) is force


def _validate_rerun(args: tuple[str, ...]) -> bool:
    ok, seen, _pos = _options(
        args,
        values={"--run": None, "--coverage": None, "--delay": None,
                "--timeout": None},
        flags=set(),
    )
    return ok and ("--run" in seen) != ("--coverage" in seen)


def _validate_fetch_assets(args: tuple[str, ...]) -> bool:
    for positionals in (0, 1):
        ok, seen, _pos = _options(
            args,
            values=_FETCH_ASSETS_VALUE_OPTIONS,
            flags=set(), positionals=positionals,
        )
        if not ok:
            continue
        if "--run" not in seen:
            continue
        if positionals == 1 and "--html" not in seen:
            return True
        if positionals == 0 and "--html" in seen and "--base" in seen:
            return True
    return False


def _validate_classify_hosts(args: tuple[str, ...]) -> bool:
    ok, seen, pos = _options(
        args,
        values={"--out": None, "--run": None, "--delay": None, "--timeout": None},
        flags={"--egress-recheck"}, positionals=1,
    )
    if not ok or "--out" not in seen or "--run" not in seen \
            or "--egress-recheck" not in seen \
            or not pos[0] or pos[0].startswith("-"):
        return False
    try:
        if "--delay" in seen and not 0 <= float(seen["--delay"][0]) <= 60:
            return False
        if "--timeout" in seen and not 1 <= int(seen["--timeout"][0]) <= 300:
            return False
    except (TypeError, ValueError):
        return False
    return True


def _validate_cdn_bypass(args: tuple[str, ...]) -> bool:
    ok, _seen, _pos = _options(
        args, values=_CDN_BYPASS_VALUE_OPTIONS,
        flags=_CDN_BYPASS_FLAG_OPTIONS, positionals=1,
    )
    return ok


def _validate_exploit(args: tuple[str, ...], *, check: bool) -> bool:
    ok, seen, _pos = _options(
        args,
        values=_EXPLOIT_VALUE_OPTIONS,
        flags=_EXPLOIT_FLAG_OPTIONS, positionals=1,
    )
    if not ok or "--target" not in seen or _pos != ["viewstate"] \
            or ("--check" in seen) is not check:
        return False
    payload_modes = int("--payload" in seen) + int("--cmd" in seen)
    return payload_modes == (0 if check else 1)


def _validate_timestamp(args: tuple[str, ...]) -> bool:
    ok, _seen, _pos = _options(
        args,
        values={"--kind": {"generic", "vuln"}},
        flags={"--json", "--iso", "--epoch", "--year", "--search-hint"},
    )
    return ok


def _validate_anti_drift(args: tuple[str, ...], *, record: bool) -> bool:
    """Accept only the two canonical semantic anti-drift command shapes."""
    if not record:
        return len(args) == 2 \
            and args[0] == "--semantic-status" \
            and bool(args[1]) and not args[1].startswith("-")
    if len(args) != 8 or args[0] != "--record-reason-pass" \
            or not args[1] or args[1].startswith("-") \
            or args[2] != "--cycle-id" \
            or not re.fullmatch(r"[1-9][0-9]*", args[3]) \
            or args[4] != "--chosen-front" \
            or not re.fullmatch(r"(?:F-[0-9]+[A-Za-z]*|NONE)", args[5]) \
            or args[6] != "--reason":
        return False
    reason = args[7]
    return bool(reason.strip()) and not reason.startswith("-") \
        and len(reason) <= 4096


def _validate_check_run(args: tuple[str, ...], mode: str) -> bool:
    if mode == "offline":
        return _one_run(args)
    if mode == "replay":
        ok, seen, _pos = _options(
            args, values={}, flags={"--replay-verify"}, positionals=1,
        )
        return ok and "--replay-verify" in seen
    ok, seen, _pos = _options(
        args,
        values={"--review-driver": {"claude", "codex"}},
        flags={"--auto-peer-review"},
        positionals=1,
    )
    return ok and "--auto-peer-review" in seen


def _validate_work_plan(args: tuple[str, ...], *, status: bool) -> bool:
    if not args:
        return False
    if args[0] == "status":
        ok, _seen, _pos = _options(
            args[1:], values={}, flags={"--json"}, positionals=1,
        )
        return status and ok
    if status or args[0] != "commit":
        return False
    ok, seen, _pos = _options(
        args[1:],
        values={
            "--stage": {"S1", "S2", "S3"},
            "--objective": None,
            "--mode": {
                "ROOT_DIRECT", "SERIAL_AGENT", "PARALLEL_AGENTS",
                "COMPLETION_REVIEW",
            },
            "--reason": None,
            "--exit-gate": None,
            "--replan-reason": None,
            "--lane": None,
        },
        flags=set(), repeatable={"--lane"}, positionals=1,
    )
    required = {"--stage", "--objective", "--mode", "--reason",
                "--exit-gate"}
    if not ok or not required.issubset(seen):
        return False
    modes = seen.get("--mode", [])
    stages = seen.get("--stage", [])
    completion = modes == ["COMPLETION_REVIEW"]
    if completion:
        if stages != ["S3"] or "--lane" in seen:
            return False
    elif "--lane" not in seen:
        return False
    try:
        return all(
            isinstance(json.loads(value), dict)
            for value in seen.get("--lane", [])
        )
    except json.JSONDecodeError:
        return False


def _validate_work_plan_legacy_migration(args: tuple[str, ...]) -> bool:
    return len(args) == 2 and args[0] == "migrate-legacy" \
        and _one_run(args[1:])


_WORKERS_COMMANDS = frozenset({
    "list", "new", "commit-plan", "commit-proposal", "delegate",
    "completion-review", "assign", "heartbeat", "finish",
    "review-disposition", "lifecycle-check", "status", "agent-check", "suggest",
    "plan", "merge-check", "conflicts", "synthesize", "merge-constraints",
    "merge-threats",
})
_WORKERS_HELP_COMMANDS = _WORKERS_COMMANDS | {
    "cancel-unlaunched", "settle-stopped", "settle-stream-stalled",
    "recover-hook-failed-stop",
}


def _validate_workers(args: tuple[str, ...], *, read: bool) -> bool:
    if not args:
        return False
    read_commands = {
        "list", "status", "agent-check", "suggest", "completion-review",
        "lifecycle-check", "merge-check",
    }
    if args[0] not in _WORKERS_COMMANDS:
        ok, seen, _pos = _options(
            args, values={"--new": None}, flags=set(), positionals=1,
        )
        return ok and (("--new" not in seen) is read)
    command = args[0]
    if (command in read_commands) is not read:
        return False
    if command == "new":
        return len(args) == 3 and not any(value.startswith("-") for value in args[1:])
    if command == "assign":
        ok, seen, _pos = _options(
            args[1:],
            values={"--role": None, "--front": None, "--scope": None,
                    "--asset": None, "--lane": None},
            flags=set(), repeatable={"--asset"}, positionals=1,
        )
        return ok and {"--role", "--front"}.issubset(seen)
    if command == "commit-plan":
        ok, seen, _pos = _options(
            args[1:],
            values={
                "--stage": {"S1", "S2", "S3"},
                "--objective": None,
                # ROOT_DIRECT is a valid public mode spelling even though the
                # generated multi-lane planner draft will reject it later with
                # a precise work-plan error. Let the owner CLI explain that
                # recoverable choice instead of hiding it as an unknown argv.
                "--mode": {
                    "ROOT_DIRECT", "SERIAL_AGENT", "PARALLEL_AGENTS",
                    "COMPLETION_REVIEW",
                },
                "--reason": None,
                "--exit-gate": None,
                "--replan-reason": None,
                "--limit": None,
            },
            flags=set(), positionals=1,
        )
        required = {
            "--stage", "--objective", "--mode", "--reason", "--exit-gate",
        }
        if not ok or not required.issubset(seen):
            return False
        if seen.get("--mode") == ["COMPLETION_REVIEW"] \
                and seen.get("--stage") != ["S3"]:
            return False
        limits = seen.get("--limit", ["2"])
        return all(
            re.fullmatch(r"[12]", raw) is not None for raw in limits
        )
    if command in {"commit-proposal", "completion-review"}:
        return len(args) == 2 and _one_run(args[1:])
    if command == "delegate":
        ok, seen, _pos = _options(
            args[1:],
            values={
                "--runtime-slots": None,
                "--request-budget": None,
                "--model-egress-budget": None,
                "--merge-capacity": None,
                "--limit": None,
                "--tool-call-limit": None,
            },
            flags=set(), positionals=1,
        )
        if not ok:
            return False
        bounds = {
            "--runtime-slots": (1, 16),
            "--request-budget": (0, 1000),
            "--model-egress-budget": (0, 1000),
            "--merge-capacity": (0, 10000),
            "--limit": (1, 16),
            "--tool-call-limit": (5, 64),
        }
        return all(
            all(re.fullmatch(r"[0-9]+", raw) is not None
                and lower <= int(raw) <= upper for raw in seen.get(flag, []))
            for flag, (lower, upper) in bounds.items()
        )
    if command in {"heartbeat", "finish"}:
        values = {"--status": None, "--note": None}
        flags = {"--amend"} if command == "finish" else set()
        ok, _seen, _pos = _options(
            args[1:], values=values, flags=flags, positionals=2,
        )
        return ok
    if command == "review-disposition":
        ok, seen, _pos = _options(
            args[1:], values={"--status": None, "--note": None},
            flags=set(), positionals=3,
        )
        return ok and {"--status", "--note"}.issubset(seen)
    flags = {"--closure"} if command == "lifecycle-check" else set()
    values = {"--limit": None} if command in {"suggest", "plan"} else {}
    ok, _seen, _pos = _options(
        args[1:], values=values, flags=flags, positionals=1,
    )
    return ok


def _validate_workers_cancel_unlaunched(args: tuple[str, ...]) -> bool:
    if len(args) != 5 or args[0] != "cancel-unlaunched" \
            or not _one_run(args[1:2]) \
            or not re.fullmatch(r"A-[A-Za-z0-9._-]+", args[2]) \
            or args[3] != "--reason":
        return False
    reason = args[4]
    return bool(reason.strip()) and not reason.startswith("-") \
        and len(reason) <= 4096


def _validate_workers_settle_stopped(args: tuple[str, ...]) -> bool:
    return bool(
        len(args) == 3
        and args[0] == "settle-stopped"
        and _one_run(args[1:2])
        and re.fullmatch(r"A-[A-Za-z0-9._-]+", args[2])
    )


def _validate_workers_settle_stream_stalled(args: tuple[str, ...]) -> bool:
    return bool(
        len(args) == 3
        and args[0] == "settle-stream-stalled"
        and _one_run(args[1:2])
        and re.fullmatch(r"A-[A-Za-z0-9._-]+", args[2])
    )


def _validate_workers_recover_hook_failed_stop(args: tuple[str, ...]) -> bool:
    return bool(
        len(args) == 3
        and args[0] == "recover-hook-failed-stop"
        and _one_run(args[1:2])
        and re.fullmatch(r"A-[A-Za-z0-9._-]+", args[2])
    )


def _validate_peer_review(args: tuple[str, ...], mode: str) -> bool:
    if mode == "list":
        return args == ("--list-backends",)
    common_values = {
        "--out": None, "--json-out": None, "--timeout": None,
    }
    if mode == "bundle":
        ok, seen, _pos = _options(
            args, values=common_values, flags={"--bundle-only", "--no-recon"},
            positionals=1,
        )
        return ok and "--bundle-only" in seen
    if mode == "resolve":
        ok, seen, _pos = _options(
            args,
            values={"--resolve": None,
                    "--status": {"accepted", "dismissed", "superseded", "escalated"},
                    "--resolution": None},
            flags=set(), positionals=1,
        )
        return ok and {"--resolve", "--status", "--resolution"}.issubset(seen)
    ok, seen, _pos = _options(
        args,
        values={
            **common_values,
            "--backend": None, "--driver": {"claude", "codex"},
            "--role": None, "--panel-backends": None,
            "--min-heterogeneous": None, "--max-backends": None,
        },
        flags={"--into-run", "--panel", "--no-recon"}, positionals=1,
    )
    return ok and not ({"--bundle-only", "--resolve", "--list-backends"} & set(seen))


def _mapping_items(
    values: list[str], *, digest: bool, maximum_value_bytes: int = 2048,
) -> bool:
    keys: set[str] = set()
    for raw in values:
        key, separator, value = raw.partition("=")
        if not separator or not re.fullmatch(
                r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}", key) \
                or key in keys or not value.strip():
            return False
        if digest:
            if not re.fullmatch(r"[0-9a-f]{64}", value):
                return False
        elif len(value.encode("utf-8", "replace")) > maximum_value_bytes:
            return False
        keys.add(key)
    return True


def _validate_completion_transaction(
    args: tuple[str, ...], *, action: str,
) -> bool:
    if not args or args[0] != action:
        return False
    if action in {"status", "commit", "adopt-policy"}:
        return len(args) == 2 and _one_run(args[1:])
    if action == "reopen":
        ok, seen, _pos = _options(
            args[1:], values={"--reason": None}, flags=set(), positionals=1,
        )
        reason = (seen.get("--reason") or [""])[0]
        return bool(
            ok and "--reason" in seen and reason.strip()
            and len(reason.encode("utf-8", "replace")) <= 2048
        )
    if action != "prepare":
        return False
    ok, seen, _pos = _options(
        args[1:],
        values={
            "--mode": {"ghost", "normal"},
            "--review-receipt": None,
            "--review-limitation": None,
            "--cron-disposition": {"quiescent", "not_requested"},
            "--warning-disposition": None,
        },
        flags=set(),
        repeatable={
            "--review-receipt", "--review-limitation",
            "--warning-disposition",
        },
        positionals=1,
    )
    if not ok or not {"--mode", "--cron-disposition"}.issubset(seen):
        return False
    if not _mapping_items(seen.get("--review-receipt", []), digest=True) \
            or not _mapping_items(
                seen.get("--review-limitation", []), digest=False,
            ):
        return False
    warning_codes: set[str] = set()
    for raw in seen.get("--warning-disposition", []):
        code, separator, tail = raw.partition(":")
        disposition, second, reason = tail.partition(":")
        if not separator or not second \
                or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]*", code) \
                or disposition not in {
                    "accepted", "dismissed", "deferred", "fixed",
                } \
                or not reason.strip() or code in warning_codes \
                or len(reason.encode("utf-8", "replace")) > 2048:
            return False
        warning_codes.add(code)
    return True


def _barrier_key_valid(seen: dict[str, list[str]]) -> bool:
    required = {
        "--front", "--action-fingerprint", "--cause-code",
        "--precondition-digest",
    }
    return bool(
        required.issubset(seen)
        and re.fullmatch(r"F-[0-9]+", seen["--front"][0])
        and re.fullmatch(r"[0-9a-f]{64}", seen["--action-fingerprint"][0])
        and re.fullmatch(
            r"[A-Z][A-Z0-9_.-]{0,127}", seen["--cause-code"][0],
        )
        and re.fullmatch(r"[0-9a-f]{64}", seen["--precondition-digest"][0])
    )


def _validate_barrier_state(args: tuple[str, ...], *, action: str) -> bool:
    if not args or args[0] != action:
        return False
    if action == "status":
        return len(args) == 2 and _one_run(args[1:])
    common = {
        "--front": None,
        "--action-fingerprint": None,
        "--cause-code": None,
        "--precondition-digest": None,
    }
    if action == "check":
        values = {
            **common,
            "--operation-class": {
                "target_attempt", "repair", "local_verify",
            },
        }
        required = {"--operation-class"}
    elif action == "observe":
        values = {
            "--failure-receipt-sha256": None,
        }
        required = {"--failure-receipt-sha256"}
    elif action == "clear":
        values = {
            **common,
            "--reason": {
                "repair_succeeded", "target_response_observed",
            },
            "--basis-sha256": None,
        }
        required = {"--reason", "--basis-sha256"}
    else:
        return False
    ok, seen, _pos = _options(
        args[1:], values=values, flags=set(), positionals=1,
    )
    if not ok or not required.issubset(seen):
        return False
    if action == "observe":
        return bool(re.fullmatch(
            r"[0-9a-f]{64}", seen["--failure-receipt-sha256"][0],
        ))
    if not _barrier_key_valid(seen):
        return False
    if action == "clear":
        return bool(re.fullmatch(r"[0-9a-f]{64}", seen["--basis-sha256"][0]))
    return True


def _bounded_decimal(raw: str, *, minimum: int, maximum: int) -> bool:
    if not re.fullmatch(r"0|[1-9][0-9]*", raw):
        return False
    try:
        value = int(raw)
    except ValueError:
        return False
    return minimum <= value <= maximum


def _validate_artifact_view(args: tuple[str, ...], *, action: str) -> bool:
    if not args or args[0] != action:
        return False
    if action == "range":
        ok, seen, pos = _options(
            args[1:],
            values={"--offset": None, "--length": None},
            flags=set(), positionals=2,
        )
        if not ok or "--offset" not in seen:
            return False
        return bool(
            pos[1]
            and _bounded_decimal(
                seen["--offset"][0], minimum=0, maximum=(1 << 63) - 1,
            )
            and ("--length" not in seen or _bounded_decimal(
                seen["--length"][0], minimum=1, maximum=64 * 1024,
            ))
        )
    if action == "search":
        ok, seen, pos = _options(
            args[1:],
            values={
                "--scan-limit": None, "--max-matches": None,
                "--context-bytes": None,
            },
            flags=set(), positionals=3,
        )
        if not ok or not pos[1] or not pos[2] \
                or len(pos[2].encode("utf-8", "replace")) > 512:
            return False
        bounds = {
            "--scan-limit": (1, 64 * 1024 * 1024),
            "--max-matches": (1, 100),
            "--context-bytes": (0, 256),
        }
    elif action == "strings":
        ok, seen, pos = _options(
            args[1:],
            values={
                "--min-length": None, "--scan-limit": None,
                "--max-strings": None, "--max-string-bytes": None,
            },
            flags=set(), positionals=2,
        )
        if not ok or not pos[1]:
            return False
        bounds = {
            "--min-length": (1, 128),
            "--scan-limit": (1, 64 * 1024 * 1024),
            "--max-strings": (1, 200),
            "--max-string-bytes": (1, 512),
        }
    else:
        return False
    if any(
        name in seen and not _bounded_decimal(
            seen[name][0], minimum=limits[0], maximum=limits[1],
        )
        for name, limits in bounds.items()
    ):
        return False
    if action == "strings":
        minimum = int((seen.get("--min-length") or ["4"])[0])
        maximum = int((seen.get("--max-string-bytes") or ["256"])[0])
        if maximum < minimum:
            return False
    return True


def argv_matches(validator: str, args: Iterable[str]) -> bool:
    values = tuple(str(value) for value in args)
    if not _bounded(values):
        return False
    if validator == "contract-schema-prepare":
        return _validate_contract_schema_action(values, action="prepare")
    if validator == "contract-schema-publish":
        return _validate_contract_schema_action(values, action="publish")
    if validator == "contract-schema-discard":
        return _validate_contract_schema_action(values, action="discard")
    if validator == "contract-schema-help":
        return values in {("--help",), ("-h",)}
    if validator == "workers-help":
        return bool(
            values in {("--help",), ("-h",)}
            or len(values) == 2
            and values[0] in _WORKERS_HELP_COMMANDS
            and values[1] in {"--help", "-h"}
        )
    if validator == "selftest":
        return values == ("--selftest",)
    if validator == "no-args":
        return not values
    if validator == "selftest-all":
        ok, _seen, _pos = _options(
            values,
            values={"--only": None, "--timeout": None},
            flags={"--verbose", "--list"},
        )
        return ok
    if validator == "timestamp-gate":
        return _validate_timestamp(values)
    if validator == "anti-drift-semantic-status":
        return _validate_anti_drift(values, record=False)
    if validator == "anti-drift-record-reason-pass":
        return _validate_anti_drift(values, record=True)
    if validator == "one-run":
        return _one_run(values)
    if validator == "runtime-receipts-read":
        return _one_run(values)
    if validator == "runtime-receipts-reproject":
        return len(values) == 2 and _one_run(values[:1]) \
            and values[1] == "--reproject"
    if validator == "runtime-receipts-quarantine":
        return len(values) == 2 and _one_run(values[:1]) \
            and values[1] == "--quarantine-unowned-lifecycle"
    if validator == "coverage-read":
        return _validate_coverage(values, write=False)
    if validator == "coverage-write":
        return _validate_coverage(values, write=True)
    if validator == "ingest-read":
        return _validate_ingest(values, write=False)
    if validator == "ingest-write":
        return _validate_ingest(values, write=True)
    if validator == "loop-bootstrap-prepare":
        return _validate_loop_bootstrap(values, prepare=True)
    if validator == "loop-bootstrap-control":
        return _validate_loop_bootstrap(values, prepare=False)
    if validator == "loop-journal-read":
        return _validate_loop_journal(values, read=True)
    if validator == "loop-journal-control":
        return _validate_loop_journal(values, read=False)
    if validator == "state-read":
        return _validate_state_tool(values)
    if validator == "loop-state-write":
        return _validate_state_tool(values, write_flag="--write")
    if validator == "progress-write":
        return _validate_state_tool(values, write_flag="--write")
    if validator == "controller-write":
        return _validate_state_tool(values, write_flag="--shadow")
    if validator == "session-pickup":
        return _validate_session(values, action="pickup")
    if validator == "session-write":
        return _validate_session(values, action="write")
    if validator == "setup-run-control":
        return _validate_setup_run(values, classify=False)
    if validator == "setup-run-classify":
        return _validate_setup_run(values, classify=True)
    if validator == "statusline-read":
        return _validate_statusline(values, control=False)
    if validator == "statusline-control":
        return _validate_statusline(values, control=True)
    if validator == "scope-admission":
        return _validate_scope_admission(values)
    if validator == "probe-live":
        return _validate_probe(values)
    if validator == "render-live":
        return _validate_render(values, eval_mode=False)
    if validator == "render-eval":
        return _validate_render(values, eval_mode=True)
    if validator == "scan-live":
        return _validate_scan(values)
    if validator == "replay-live":
        return _validate_replay(values, force=False)
    if validator == "replay-force":
        return _validate_replay(values, force=True)
    if validator == "rerun-deferred":
        return _validate_rerun(values)
    if validator == "fetch-assets":
        return _validate_fetch_assets(values)
    if validator == "classify-hosts":
        return _validate_classify_hosts(values)
    if validator == "cdn-bypass":
        return _validate_cdn_bypass(values)
    if validator == "exploit-check":
        return _validate_exploit(values, check=True)
    if validator == "exploit-delivery":
        return _validate_exploit(values, check=False)
    if validator == "check-run-offline":
        return _validate_check_run(values, "offline")
    if validator == "check-run-replay":
        return _validate_check_run(values, "replay")
    if validator == "check-run-review":
        return _validate_check_run(values, "review")
    if validator == "work-plan-status":
        return _validate_work_plan(values, status=True)
    if validator == "work-plan-commit":
        return _validate_work_plan(values, status=False)
    if validator == "work-plan-migrate-legacy":
        return _validate_work_plan_legacy_migration(values)
    if validator == "workers-read":
        return _validate_workers(values, read=True)
    if validator == "workers-cancel-unlaunched":
        return _validate_workers_cancel_unlaunched(values)
    if validator == "workers-settle-stopped":
        return _validate_workers_settle_stopped(values)
    if validator == "workers-settle-stream-stalled":
        return _validate_workers_settle_stream_stalled(values)
    if validator == "workers-recover-hook-failed-stop":
        return _validate_workers_recover_hook_failed_stop(values)
    if validator == "workers-control":
        return _validate_workers(values, read=False)
    if validator == "peer-review-list":
        return _validate_peer_review(values, "list")
    if validator == "peer-review-bundle":
        return _validate_peer_review(values, "bundle")
    if validator == "peer-review-resolve":
        return _validate_peer_review(values, "resolve")
    if validator == "peer-review-model":
        return _validate_peer_review(values, "model")
    if validator.startswith("completion-transaction-"):
        return _validate_completion_transaction(
            values, action=validator.removeprefix("completion-transaction-"),
        )
    if validator.startswith("barrier-state-"):
        return _validate_barrier_state(
            values, action=validator.removeprefix("barrier-state-"),
        )
    if validator.startswith("artifact-view-"):
        return _validate_artifact_view(
            values, action=validator.removeprefix("artifact-view-"),
        )
    return False


def registered_scripts(
    *, root: Path = ROOT, effects: set[str] | frozenset[str] | None = None,
) -> frozenset[Path]:
    return frozenset(
        spec.path(root) for spec in CAPABILITIES
        if effects is None or spec.effect in effects
    )


def by_id(capability_id: str) -> CapabilitySpec | None:
    """Return one exact registry entry without case or whitespace fallback."""
    if not isinstance(capability_id, str) or not capability_id:
        return None
    matches = [spec for spec in CAPABILITIES if spec.id == capability_id]
    return matches[0] if len(matches) == 1 else None


def match(
    script: Path, args: Iterable[str], *, root: Path = ROOT,
) -> CapabilitySpec | None:
    try:
        resolved = script.resolve(strict=True)
    except (OSError, RuntimeError, ValueError):
        return None
    for spec in CAPABILITIES:
        try:
            same = spec.path(root) == resolved
        except (OSError, RuntimeError, ValueError):
            same = False
        if same and argv_matches(spec.argv_validator, args):
            return spec
    return None


def _flag_values(args: Iterable[str], names: set[str]) -> dict[str, list[str]]:
    values = tuple(str(value) for value in args)
    found: dict[str, list[str]] = {}
    index = 0
    while index < len(values):
        token = values[index]
        if token in names and index + 1 < len(values):
            found.setdefault(token, []).append(values[index + 1])
            index += 2
            continue
        index += 1
    return found


def run_reference(spec: CapabilitySpec, args: Iterable[str]) -> str:
    """Project the run resource named by a validated capability argv."""
    values = tuple(str(value) for value in args)
    validator = spec.argv_validator
    if validator.startswith("check-run-"):
        return values[0] if values else ""
    if validator.startswith("peer-review-") and validator not in {
            "peer-review-list"}:
        value_flags = {
            "--out", "--json-out", "--timeout", "--backend", "--driver",
            "--role", "--panel-backends", "--min-heterogeneous",
            "--max-backends", "--resolve", "--status", "--resolution",
        }
        index = 0
        while index < len(values):
            if values[index] in value_flags:
                index += 2
            elif values[index].startswith("-"):
                index += 1
            else:
                return values[index]
        return ""
    if validator.startswith("work-plan-"):
        return values[1] if len(values) > 1 else ""
    if validator.startswith((
            "completion-transaction-", "barrier-state-", "artifact-view-",
    )):
        return values[1] if len(values) > 1 else ""
    if validator in {
        "anti-drift-semantic-status", "anti-drift-record-reason-pass",
    }:
        return values[1] if len(values) > 1 else ""
    if validator.startswith("workers-"):
        commands = {
            "list", "new", "suggest", "plan", "commit-plan", "commit-proposal",
            "delegate", "completion-review", "assign",
            "cancel-unlaunched", "settle-stopped", "settle-stream-stalled",
            "recover-hook-failed-stop",
            "status",
            "agent-check", "heartbeat", "finish", "review-disposition",
            "lifecycle-check",
            "merge-check", "conflicts", "synthesize", "merge-constraints",
            "merge-threats",
        }
        return values[1] if values and values[0] in commands and len(values) > 1 \
            else (values[0] if values else "")
    if validator in {
        "one-run", "runtime-receipts-read", "runtime-receipts-reproject",
        "runtime-receipts-quarantine",
        "coverage-read", "coverage-write", "loop-journal-read",
        "loop-journal-control", "state-read", "loop-state-write",
        "progress-write", "controller-write", "scope-admission",
    }:
        return values[0] if values else ""
    if validator in {"session-pickup", "session-write"}:
        return values[1] if len(values) > 1 else ""
    flags = _flag_values(values, {"--run"})
    return (flags.get("--run") or [""])[0]


def output_references(spec: CapabilitySpec, args: Iterable[str]) -> tuple[str, ...]:
    """Project explicit filesystem outputs from an already validated argv."""
    names_by_validator = {
        "ingest-write": {"--out"},
        "peer-review-bundle": {"--out", "--json-out"},
        "peer-review-model": {"--out", "--json-out"},
        "probe-live": {"--save", "--preflight-save", "--cookie-jar"},
        "render-live": {"--out", "--save"},
        "render-eval": {"--out", "--save"},
        "fetch-assets": {"--out"},
        "classify-hosts": {"--out"},
    }
    names = names_by_validator.get(spec.argv_validator, set())
    found = _flag_values(args, names)
    return tuple(value for name in sorted(found) for value in found[name])


_EXPLICIT_TARGET_REFERENCE_VALIDATORS = frozenset({
    "probe-live", "render-live", "render-eval", "scan-live",
    "fetch-assets", "cdn-bypass", "exploit-check", "exploit-delivery",
})
_INDIRECT_TARGET_REFERENCE_VALIDATORS = frozenset({
    "check-run-replay", "setup-run-classify", "replay-live", "replay-force",
    "rerun-deferred", "classify-hosts",
})


def target_reference_policy(spec: CapabilitySpec) -> str:
    """Classify how a registered target capability obtains its destinations."""
    if spec.effect != "target":
        return "none"
    if spec.argv_validator in _EXPLICIT_TARGET_REFERENCE_VALIDATORS:
        return "explicit"
    if spec.argv_validator in _INDIRECT_TARGET_REFERENCE_VALIDATORS:
        return "indirect"
    return "missing"


def _strict_target_options(
    args: tuple[str, ...], *,
    values: dict[str, set[str] | None],
    flags: set[str],
    positional_counts: tuple[int, ...],
    repeatable: set[str] = frozenset(),
) -> tuple[dict[str, list[str]], list[str]]:
    """Reparse target argv with the validator-owned, closed option schema."""
    for positional_count in positional_counts:
        ok, seen, positionals = _options(
            args,
            values=values,
            flags=flags,
            repeatable=repeatable,
            positionals=positional_count,
        )
        if ok:
            return seen, positionals
    raise ValueError("validated target argv cannot be projected by its option schema")


def target_references(
    spec: CapabilitySpec, args: Iterable[str],
) -> tuple[TargetReference, ...]:
    """Project only outbound destination argv from one exact target capability.

    Callers use this shared contract for pre-execution coverage authorization and
    post-execution asset attribution.  Output paths, payloads, headers, proxy
    selectors, and arbitrary URL-shaped data are excluded by construction.
    """
    values = tuple(str(value) for value in args)
    policy = target_reference_policy(spec)
    if policy == "none":
        return ()
    if policy == "missing":
        raise ValueError(
            f"target capability {spec.id} has no destination reference contract")
    if not argv_matches(spec.argv_validator, values):
        raise ValueError(
            f"target capability {spec.id} argv no longer matches its registry contract")
    if policy == "indirect":
        return ()

    references: list[TargetReference] = []
    if spec.argv_validator == "probe-live":
        seen, positionals = _strict_target_options(
            values,
            values=_PROBE_VALUE_OPTIONS,
            flags=_PROBE_FLAG_OPTIONS,
            repeatable={"-H", "--header"},
            positional_counts=(2, 3),
        )
        references.extend(
            TargetReference(value) for value in positionals[1:])
        preflight = (seen.get("--preflight-get") or [""])[0]
        if preflight:
            references.append(TargetReference(preflight, role="supporting"))
    elif spec.argv_validator in {"render-live", "render-eval"}:
        _seen, positionals = _strict_target_options(
            values,
            values=_RENDER_VALUE_OPTIONS,
            flags=_RENDER_FLAG_OPTIONS,
            repeatable={"--cookie"},
            positional_counts=(1,),
        )
        references.append(TargetReference(positionals[0]))
    elif spec.argv_validator == "scan-live" and values:
        references.append(TargetReference(values[-1]))
    elif spec.argv_validator == "fetch-assets":
        seen, positionals = _strict_target_options(
            values,
            values=_FETCH_ASSETS_VALUE_OPTIONS,
            flags=set(),
            positional_counts=(0, 1),
        )
        value = positionals[0] if positionals else (seen.get("--base") or [""])[0]
        if value:
            references.append(TargetReference(value))
    elif spec.argv_validator == "cdn-bypass":
        _seen, positionals = _strict_target_options(
            values,
            values=_CDN_BYPASS_VALUE_OPTIONS,
            flags=_CDN_BYPASS_FLAG_OPTIONS,
            positional_counts=(1,),
        )
        references.append(TargetReference(positionals[0], allow_bare=True))
    elif spec.argv_validator in {"exploit-check", "exploit-delivery"}:
        seen, _positionals = _strict_target_options(
            values,
            values=_EXPLOIT_VALUE_OPTIONS,
            flags=_EXPLOIT_FLAG_OPTIONS,
            positional_counts=(1,),
        )
        value = (seen.get("--target") or [""])[0]
        if value:
            references.append(TargetReference(value))

    if not references:
        raise ValueError(
            f"explicit target capability {spec.id} produced no destination references")
    return tuple(references)


def selftest() -> int:
    ids = [spec.id for spec in CAPABILITIES]
    demo_run = "runs/demo_20260101"
    sha_a = "a" * 64
    sha_b = "b" * 64
    barrier_key_args = [
        "--front", "F-001",
        "--action-fingerprint", sha_a,
        "--cause-code", "NETWORK_TIMEOUT",
        "--precondition-digest", sha_b,
    ]
    root_direct_ids = {
        spec.id for spec in CAPABILITIES if spec.root_direct_eligible
    }
    expected_root_direct_ids = {
        "read.timestamp-gate",
        "read.anti-drift-semantic-status",
        "verify.check-run",
        "read.run-model",
    }
    target_specs = [spec for spec in CAPABILITIES if spec.effect == "target"]

    def projected_targets(script: str, args: list[str]) -> tuple[TargetReference, ...]:
        spec = match(ROOT / script, args)
        if spec is None:
            return ()
        try:
            return target_references(spec, args)
        except ValueError:
            return ()

    noisy_probe_args = [
        "POST", "https://actual.example/app.js",
        "--data", "next=https://payload.example/callback",
        "--header", "Referer: https://header.example/source",
        "--preflight-get", "https://preflight.example/form",
        "--save", "f003-cms-8090-app-js.js",
        "--run", demo_run,
    ]
    noisy_probe_targets = projected_targets("tools/probe.py", noisy_probe_args)
    bare_cdn_targets = projected_targets(
        "tools/cdn_bypass.py", ["cdn.example", "--json"])
    shared_endpoint_normalization = (
        target_endpoint(TargetReference("https://Port.Example/path"))
        == ("port.example", 443)
        and target_endpoint(TargetReference(
            "https://port.example:8443/path"))
        == ("port.example", 8443)
        and target_endpoint(TargetReference("https://例子.测试/path"))
        == ("xn--fsqu00a.xn--0zwm56d", 443)
        and target_endpoint(TargetReference(
            "[2001:db8::1]:8443", allow_bare=True))
        == ("2001:db8::1", 8443)
        and target_endpoint(TargetReference(
            "https://user@port.example/")) is None
        and target_endpoint(TargetReference(
            "https://port.example:/")) is None
        and target_endpoint(TargetReference("port.example")) is None
    )
    missing_target_policy_rejected = False
    try:
        target_references(
            _spec(
                "target.future", "tools/probe.py", "target",
                "future-target-validator",
            ),
            ["https://future.example/"],
        )
    except ValueError as exc:
        missing_target_policy_rejected = (
            "no destination reference contract" in str(exc))
    unknown_target_option_rejected = False
    try:
        _strict_target_options(
            (
                "GET", "https://actual.example/", "--future-target",
                "https://must-not-be-promoted.example/",
            ),
            values=_PROBE_VALUE_OPTIONS,
            flags=_PROBE_FLAG_OPTIONS,
            repeatable={"-H", "--header"},
            positional_counts=(2, 3),
        )
    except ValueError:
        unknown_target_option_rejected = True
    checks: list[tuple[str, bool]] = [
        ("capability ids are unique", len(ids) == len(set(ids))),
        ("all registered scripts exist", all(spec.path().is_file() for spec in CAPABILITIES)),
        ("effects are finite", all(spec.effect in EFFECTS for spec in CAPABILITIES)),
        ("scope policies are finite", all(spec.scope in SCOPE_POLICIES for spec in CAPABILITIES)),
        ("privacy policies are finite", all(spec.privacy in PRIVACY_POLICIES for spec in CAPABILITIES)),
        ("proxy policies are finite", all(spec.proxy in PROXY_POLICIES for spec in CAPABILITIES)),
        ("guard policies are finite", all(spec.guard in GUARD_POLICIES for spec in CAPABILITIES)),
        ("recorder policies are finite", all(spec.recorder in RECORDER_POLICIES for spec in CAPABILITIES)),
        ("root-direct eligibility is a strict boolean", all(
            isinstance(spec.root_direct_eligible, bool) for spec in CAPABILITIES)),
        ("root-direct eligibility is an explicit narrow local allowlist",
         root_direct_ids == expected_root_direct_ids),
        ("root-direct eligible capabilities have no target or control effect", all(
            spec.effect in {"local_read", "local_verify"}
            and spec.privacy == "none" and spec.proxy == "none"
            and spec.guard == "none" and spec.recorder == "none"
            for spec in CAPABILITIES if spec.root_direct_eligible)),
        ("every target capability declares an explicit or indirect destination policy",
         bool(target_specs) and all(
             target_reference_policy(spec) in {"explicit", "indirect"}
             for spec in target_specs)),
        ("a new target capability without a destination policy fails closed",
         missing_target_policy_rejected),
        ("unknown target options cannot promote their values to destinations",
         unknown_target_option_rejected),
        ("probe target projection excludes payload header and dotted save names",
         noisy_probe_targets == (
             TargetReference("https://actual.example/app.js"),
             TargetReference(
                 "https://preflight.example/form", role="supporting"),
         )
         and output_references(
             match(ROOT / "tools/probe.py", noisy_probe_args)
             or _spec("", "", "", ""), noisy_probe_args)
         == ("f003-cms-8090-app-js.js",)),
        ("bare target references require an explicit capability-owned opt-in",
         bare_cdn_targets == (
             TargetReference("cdn.example", allow_bare=True),
         )),
        ("every consumer shares one strict host port and IDNA normalizer",
         shared_endpoint_normalization),
        ("indirect target capabilities cannot invent argv destinations",
         (lambda spec: bool(
             spec and target_reference_policy(spec) == "indirect"
             and target_references(spec, [demo_run, "--replay-verify"]) == ()
         ))(match(ROOT / "tools/check_run.py", [
             demo_run, "--replay-verify",
         ]))),
        ("contract schema maintenance has three exact discoverable argv", bool(
            (match(ROOT / "tools/contract_schema.py", [
                "prepare", "work-plan.v1.schema.json",
            ]) or _spec("", "", "", "")).id
                == "maintenance.contract-schema-prepare"
            and (match(ROOT / "tools/contract_schema.py", [
                "publish", "work-plan.v1.schema.json",
            ]) or _spec("", "", "", "")).id
                == "maintenance.contract-schema-publish"
            and (match(ROOT / "tools/contract_schema.py", [
                "discard", "work-plan.v1.schema.json",
            ]) or _spec("", "", "", "")).id
                == "maintenance.contract-schema-discard"
            and all((match(ROOT / "tools/contract_schema.py", argv)
                     or _spec("", "", "", "")).effect == "repo_mutation"
                    for argv in (
                        ["prepare", "work-plan.v1.schema.json"],
                        ["publish", "work-plan.v1.schema.json"],
                        ["discard", "work-plan.v1.schema.json"],
                    ))
            and match(ROOT / "tools/contract_schema.py", [
                "publish", "../work-plan.v1.schema.json",
            ]) is None
            and (match(ROOT / "tools/contract_schema.py", ["--help"])
                 or _spec("", "", "", "")).id
                == "read.contract-schema-help"
        )),
        ("workers top-level help is an exact local-read capability", bool(
            (match(ROOT / "tools/workers.py", ["--help"])
             or _spec("", "", "", "")).id == "read.workers-help"
            and (match(ROOT / "tools/workers.py", ["-h"])
                 or _spec("", "", "", "")).effect == "local_read"
            and (match(ROOT / "tools/workers.py", [
                "recover-hook-failed-stop", "--help",
            ]) or _spec("", "", "", "")).id == "read.workers-help"
            and match(ROOT / "tools/workers.py", ["--help", "extra"]) is None
        )),
        ("root-direct eligibility defaults closed",
         _spec("fixture.closed", "tools/run_model.py", "local_read", "one-run")
         .root_direct_eligible is False),
        ("capability id lookup is exact and closed on unknown spelling", bool(
            by_id("read.run-model")
            and by_id("read.run-model").id == "read.run-model"
            and by_id("READ.RUN-MODEL") is None
            and by_id(" read.run-model") is None
            and by_id("unknown.capability") is None)),
        ("no registered capability uses a script-wide native argv fallback",
         all(spec.argv_validator != "native-cli" for spec in CAPABILITIES)),
        ("target policies are a complete mandatory bundle", all(
            spec.scope == "target_assets" and spec.privacy == "target_egress"
            and spec.proxy == "engagement" and spec.guard == "target"
            and spec.recorder == "target_artifact"
            for spec in CAPABILITIES if spec.effect == "target")),
        ("model egress policies are a complete mandatory bundle", all(
            spec.scope == "review_scope" and spec.privacy == "model_egress"
            and spec.recorder == "review_receipt"
            for spec in CAPABILITIES if spec.effect == "model_egress")),
        ("control capabilities always declare a recorder", all(
            spec.recorder != "none"
            for spec in CAPABILITIES if spec.effect == "control")),
        ("new tool selftests are local verification only", all(
            (match(ROOT / script, ["--selftest"])
             or _spec("", "", "", "")).effect == "local_verify"
            for script in (
                "tools/completion_transaction.py", "tools/barrier_state.py",
                "tools/artifact_view.py",
            )
        )),
        ("completion transaction actions have distinct exact effects", bool(
            (match(ROOT / "tools/completion_transaction.py", [
                "status", demo_run,
            ]) or _spec("", "", "", "")).id
            == "read.completion-transaction-status"
            and (match(ROOT / "tools/completion_transaction.py", [
                "adopt-policy", demo_run,
            ]) or _spec("", "", "", "")).id
            == "control.completion-transaction-adopt-policy"
            and (match(ROOT / "tools/completion_transaction.py", [
                "prepare", demo_run,
                "--mode", "normal",
                "--review-receipt", f"independent-review={sha_a}",
                "--review-limitation", "external-assistance=not configured",
                "--cron-disposition", "not_requested",
                "--warning-disposition", "CHECK_WARN:accepted:reviewed locally",
            ]) or _spec("", "", "", "")).id
            == "control.completion-transaction-prepare"
            and (match(ROOT / "tools/completion_transaction.py", [
                "commit", demo_run,
            ]) or _spec("", "", "", "")).id
            == "control.completion-transaction-commit"
            and (match(ROOT / "tools/completion_transaction.py", [
                "reopen", demo_run, "--reason", "new canonical evidence",
            ]) or _spec("", "", "", "")).id
            == "control.completion-transaction-reopen"
            and all(
                (match(ROOT / "tools/completion_transaction.py", argv)
                 or _spec("", "", "", "")).recorder == "control_journal"
                for argv in (
                    ["adopt-policy", demo_run],
                    ["prepare", demo_run, "--mode", "ghost",
                     "--cron-disposition", "quiescent"],
                    ["commit", demo_run],
                    ["reopen", demo_run, "--reason", "basis changed"],
                )
            )
            and run_reference(
                match(ROOT / "tools/completion_transaction.py", [
                    "commit", demo_run,
                ]) or _spec("", "", "", ""),
                ["commit", demo_run],
            ) == demo_run
        )),
        ("completion transaction argv fail closed on malformed extensions", bool(
            match(ROOT / "tools/completion_transaction.py", [
                "prepare", demo_run, "--mode", "normal",
                "--cron-disposition", "not_requested", "--future", "x",
            ]) is None
            and match(ROOT / "tools/completion_transaction.py", [
                "prepare", demo_run, "--mode", "normal",
                "--review-receipt", "independent-review=not-a-digest",
                "--cron-disposition", "not_requested",
            ]) is None
            and match(ROOT / "tools/completion_transaction.py", [
                "prepare", demo_run, "--mode", "normal", "--mode", "ghost",
                "--cron-disposition", "not_requested",
            ]) is None
            and match(ROOT / "tools/completion_transaction.py", [
                "reopen", demo_run,
            ]) is None
            and match(ROOT / "tools/completion_transaction.py", [
                "commit", demo_run, "--future",
            ]) is None
            and match(ROOT / "tools/completion_transaction.py", [
                "adopt-policy", demo_run, "extra",
            ]) is None
        )),
        ("infrastructure barrier separates reads from derived-state controls", bool(
            (match(ROOT / "tools/barrier_state.py", [
                "status", demo_run,
            ]) or _spec("", "", "", "")).id == "read.infra-barrier-status"
            and (match(ROOT / "tools/barrier_state.py", [
                "check", demo_run, *barrier_key_args,
                "--operation-class", "target_attempt",
            ]) or _spec("", "", "", "")).id == "read.infra-barrier-check"
            and (match(ROOT / "tools/barrier_state.py", [
                "observe", demo_run,
                "--failure-receipt-sha256", sha_a,
            ]) or _spec("", "", "", "")).id
            == "control.infra-barrier-observe"
            and (match(ROOT / "tools/barrier_state.py", [
                "clear", demo_run, *barrier_key_args,
                "--reason", "repair_succeeded", "--basis-sha256", sha_b,
            ]) or _spec("", "", "", "")).id
            == "control.infra-barrier-clear"
            and all(
                (match(ROOT / "tools/barrier_state.py", argv)
                 or _spec("", "", "", "")).recorder == "control_journal"
                for argv in (
                    ["observe", demo_run,
                     "--failure-receipt-sha256", sha_a],
                    ["clear", demo_run, *barrier_key_args,
                     "--reason", "repair_succeeded", "--basis-sha256", sha_b],
                )
            )
            and run_reference(
                match(ROOT / "tools/barrier_state.py", [
                    "status", demo_run,
                ]) or _spec("", "", "", ""),
                ["status", demo_run],
            ) == demo_run
        )),
        ("infrastructure barrier observe accepts only a runtime receipt reference", bool(
            match(ROOT / "tools/barrier_state.py", [
                "observe", demo_run,
                "--failure-receipt-sha256", "not-a-digest",
            ]) is None
            and match(ROOT / "tools/barrier_state.py", [
                "observe", demo_run,
                "--failure-receipt-sha256", sha_a,
                "--failure-domain", "runtime",
            ]) is None
            and match(ROOT / "tools/barrier_state.py", [
                "clear", demo_run, *barrier_key_args,
                "--reason", "failure_reclassified", "--basis-sha256", sha_b,
            ]) is None
            and match(ROOT / "tools/barrier_state.py", [
                "check", demo_run, *barrier_key_args,
                "--operation-class", "future",
            ]) is None
            and match(ROOT / "tools/barrier_state.py", [
                "status", demo_run, "--future",
            ]) is None
        )),
        ("artifact view exposes only bounded active-run reads", bool(
            (match(ROOT / "tools/artifact_view.py", [
                "range", demo_run, "responses/large.bin",
                "--offset", "0", "--length", "65536",
            ]) or _spec("", "", "", "")).id == "read.artifact-view-range"
            and (match(ROOT / "tools/artifact_view.py", [
                "search", demo_run, "responses/large.bin", "literal",
                "--scan-limit", str(64 * 1024 * 1024),
                "--max-matches", "100", "--context-bytes", "256",
            ]) or _spec("", "", "", "")).id == "read.artifact-view-search"
            and (match(ROOT / "tools/artifact_view.py", [
                "strings", demo_run, "responses/large.bin",
                "--min-length", "4", "--scan-limit", "1024",
                "--max-strings", "20", "--max-string-bytes", "256",
            ]) or _spec("", "", "", "")).id == "read.artifact-view-strings"
            and all(
                (match(ROOT / "tools/artifact_view.py", argv)
                 or _spec("", "", "", "")).scope == "active_run"
                for argv in (
                    ["range", demo_run, "large.bin", "--offset", "0"],
                    ["search", demo_run, "large.bin", "needle"],
                    ["strings", demo_run, "large.bin"],
                )
            )
            and run_reference(
                match(ROOT / "tools/artifact_view.py", [
                    "range", demo_run, "large.bin", "--offset", "0",
                ]) or _spec("", "", "", ""),
                ["range", demo_run, "large.bin", "--offset", "0"],
            ) == demo_run
        )),
        ("artifact view bounds and unknown argv fail closed", bool(
            match(ROOT / "tools/artifact_view.py", [
                "range", demo_run, "large.bin", "--offset", "-1",
            ]) is None
            and match(ROOT / "tools/artifact_view.py", [
                "range", demo_run, "large.bin", "--offset", "0",
                "--length", "65537",
            ]) is None
            and match(ROOT / "tools/artifact_view.py", [
                "search", demo_run, "large.bin", "needle",
                "--scan-limit", str(64 * 1024 * 1024 + 1),
            ]) is None
            and match(ROOT / "tools/artifact_view.py", [
                "strings", demo_run, "large.bin",
                "--min-length", "128", "--max-string-bytes", "127",
            ]) is None
            and match(ROOT / "tools/artifact_view.py", [
                "strings", demo_run, "large.bin", "--future", "1",
            ]) is None
        )),
        ("offline check_run is local verification", (match(
            ROOT / "tools/check_run.py", ["runs/demo_20260101"]
        ) or _spec("", "", "repo_mutation", "")).effect == "local_verify"),
        ("replay check_run is a target effect", (match(
            ROOT / "tools/check_run.py", ["runs/demo_20260101", "--replay-verify"]
        ) or _spec("", "", "repo_mutation", "")).effect == "target"),
        ("auto review is model egress", (match(
            ROOT / "tools/check_run.py",
            ["runs/demo_20260101", "--auto-peer-review", "--review-driver", "codex"],
        ) or _spec("", "", "repo_mutation", "")).effect == "model_egress"),
        ("timestamp gate accepts only typed read flags", bool(match(
            ROOT / "tools/timestamp_gate.py", ["--json", "--kind", "vuln"]
        )) and match(ROOT / "tools/timestamp_gate.py", ["--future"]) is None),
        ("anti-drift semantic status is an exact active-run read", bool(
            (match(ROOT / "tools/anti_drift.py", [
                "--semantic-status", "runs/demo_20260101",
            ]) or _spec("", "", "", "")).effect == "local_read"
            and (match(ROOT / "tools/anti_drift.py", [
                "--semantic-status", "runs/demo_20260101",
            ]) or _spec("", "", "", "")).scope == "active_run"
            and match(ROOT / "tools/anti_drift.py", [
                "--semantic-status", "runs/demo_20260101", "--future",
            ]) is None
        )),
        ("anti-drift reason pass is exact recorded active-run control", bool(
            (match(ROOT / "tools/anti_drift.py", [
                "--record-reason-pass", "runs/demo_20260101",
                "--cycle-id", "1", "--chosen-front", "F-001",
                "--reason", "whole graph adjudicated",
            ]) or _spec("", "", "", "")).effect == "control"
            and (match(ROOT / "tools/anti_drift.py", [
                "--record-reason-pass", "runs/demo_20260101",
                "--cycle-id", "1", "--chosen-front", "NONE",
                "--reason", "whole graph adjudicated",
            ]) or _spec("", "", "", "")).recorder == "control_journal"
            and match(ROOT / "tools/anti_drift.py", [
                "--record-reason-pass", "runs/demo_20260101",
                "--cycle-id", "0", "--chosen-front", "F-001",
                "--reason", "whole graph adjudicated",
            ]) is None
            and match(ROOT / "tools/anti_drift.py", [
                "--record-reason-pass", "runs/demo_20260101",
                "--cycle-id", "1", "--chosen-front", "F-001",
                "--reason", "whole graph adjudicated", "--future",
            ]) is None
        )),
        ("work plan rejects unknown argv", match(
            ROOT / "tools/work_plan.py", ["--future"]
        ) is None),
        ("workers assignment is control", (match(
            ROOT / "tools/workers.py",
            ["assign", "runs/demo_20260101", "--role", "web-hunter",
             "--front", "F-001", "--asset", "app.example"],
        ) or _spec("", "", "repo_mutation", "")).effect == "control"),
        ("workers planner commit is one exact control argv", bool(
            (lambda matched: bool(
                matched
                and matched.effect == "control"
                and run_reference(matched, [
                    "commit-plan", "runs/demo_20260101",
                    "--stage", "S2", "--objective", "probe the selected front",
                    "--mode", "SERIAL_AGENT", "--reason", "one dependent chain",
                    "--exit-gate", "reviewed target evidence", "--limit", "1",
                ]) == "runs/demo_20260101"
            ))(match(ROOT / "tools/workers.py", [
                "commit-plan", "runs/demo_20260101",
                "--stage", "S2", "--objective", "probe the selected front",
                "--mode", "SERIAL_AGENT", "--reason", "one dependent chain",
                "--exit-gate", "reviewed target evidence", "--limit", "1",
            ]))
            and (match(ROOT / "tools/workers.py", [
                "commit-plan", "runs/demo_20260101",
                "--stage", "S1", "--objective", "probe once",
                "--mode", "ROOT_DIRECT", "--reason", "one atomic action",
                "--exit-gate", "saved response", "--limit", "1",
            ]) or _spec("", "", "", "")).effect == "control"
            and match(ROOT / "tools/workers.py", [
                "commit-plan", "runs/demo_20260101",
                "--stage", "S2", "--objective", "probe the selected front",
                "--mode", "SERIAL_AGENT", "--reason", "one dependent chain",
                "--exit-gate", "reviewed target evidence", "--limit", "0",
            ]) is None
            and match(ROOT / "tools/workers.py", [
                "commit-plan", "runs/demo_20260101",
                "--stage", "S2", "--objective", "probe the selected front",
                "--mode", "SERIAL_AGENT", "--reason", "one dependent chain",
                "--exit-gate", "reviewed target evidence", "--future", "x",
            ]) is None
        )),
        ("workers model proposal write and commit are exact control capabilities", bool(
            (match(ROOT / "tools/workers.py", [
                "plan", "runs/demo_20260101", "--limit", "2",
            ]) or _spec("", "", "", "")).effect == "control"
            and (lambda matched: bool(
                matched
                and matched.effect == "control"
                and run_reference(matched, [
                    "commit-proposal", "runs/demo_20260101",
                ]) == "runs/demo_20260101"
            ))(match(ROOT / "tools/workers.py", [
                "commit-proposal", "runs/demo_20260101",
            ]))
            and match(ROOT / "tools/workers.py", [
                "commit-proposal", "runs/demo_20260101", "--future",
            ]) is None
        )),
        ("completion plan and launch formatter have exact distinct effects", bool(
            (lambda matched: bool(
                matched and matched.effect == "control"
            ))(match(ROOT / "tools/workers.py", [
                "commit-plan", "runs/demo_20260101",
                "--stage", "S3", "--objective", "review closure bundle",
                "--mode", "COMPLETION_REVIEW", "--reason", "zero open fronts",
                "--exit-gate", "exact completion receipt",
            ]))
            and match(ROOT / "tools/workers.py", [
                "commit-plan", "runs/demo_20260101",
                "--stage", "S2", "--objective", "review closure bundle",
                "--mode", "COMPLETION_REVIEW", "--reason", "zero open fronts",
                "--exit-gate", "exact completion receipt",
            ]) is None
            and match(ROOT / "tools/workers.py", [
                "commit-plan", "runs/demo_20260101",
                "--stage", "S3", "--objective", "review closure bundle",
                "--mode", "COMPLETION_REVIEW", "--reason", "zero open fronts",
                "--exit-gate", "exact completion receipt",
                "--lane", "{}",
            ]) is None
            and (lambda matched: bool(
                matched
                and matched.effect == "local_read"
                and run_reference(matched, [
                    "completion-review", "runs/demo_20260101",
                ]) == "runs/demo_20260101"
            ))(match(ROOT / "tools/workers.py", [
                "completion-review", "runs/demo_20260101",
            ]))
            and match(ROOT / "tools/workers.py", [
                "completion-review", "runs/demo_20260101", "--future",
            ]) is None
            and (lambda matched: bool(
                matched and matched.effect == "control"
            ))(match(ROOT / "tools/work_plan.py", [
                "commit", "runs/demo_20260101",
                "--stage", "S3", "--objective", "review closure bundle",
                "--mode", "COMPLETION_REVIEW", "--reason", "zero open fronts",
                "--exit-gate", "exact completion receipt",
            ]))
            and match(ROOT / "tools/work_plan.py", [
                "commit", "runs/demo_20260101",
                "--stage", "S2", "--objective", "review closure bundle",
                "--mode", "COMPLETION_REVIEW", "--reason", "zero open fronts",
                "--exit-gate", "exact completion receipt",
            ]) is None
        )),
        ("workers delegate has exact bounded scheduler argv", bool(
            match(ROOT / "tools/workers.py", [
                "delegate", "runs/demo_20260101", "--runtime-slots", "2",
                "--request-budget", "10", "--model-egress-budget", "1",
                "--merge-capacity", "100", "--limit", "2",
                "--tool-call-limit", "6",
            ])
            and match(ROOT / "tools/workers.py", [
                "delegate", "runs/demo_20260101", "--runtime-slots", "0",
            ]) is None
            and match(ROOT / "tools/workers.py", [
                "delegate", "runs/demo_20260101", "--tool-call-limit", "0",
            ]) is None
            and match(ROOT / "tools/workers.py", [
                "delegate", "runs/demo_20260101", "--future", "1",
            ]) is None)),
        ("workers unlaunched cancellation is a distinct exact control capability", bool(
            (match(ROOT / "tools/workers.py", [
                "cancel-unlaunched", "runs/demo_20260101", "A-web-hunter-001",
                "--reason", "turn or canonical inputs changed before launch",
            ]) or _spec("", "", "", "")).id
            == "control.workers-cancel-unlaunched"
            and (match(ROOT / "tools/workers.py", [
                "cancel-unlaunched", "runs/demo_20260101", "A-web-hunter-001",
                "--reason", "turn or canonical inputs changed before launch",
            ]) or _spec("", "", "", "")).recorder == "control_journal"
            and match(ROOT / "tools/workers.py", [
                "cancel-unlaunched", "runs/demo_20260101", "A-web-hunter-001",
            ]) is None
            and match(ROOT / "tools/workers.py", [
                "cancel-unlaunched", "runs/demo_20260101", "A-web-hunter-001",
                "--reason", "ok", "--future",
            ]) is None)),
        ("workers external-stop settlement is a distinct exact control capability", bool(
            (match(ROOT / "tools/workers.py", [
                "settle-stopped", "runs/demo_20260101", "A-web-hunter-001",
            ]) or _spec("", "", "", "")).id
            == "control.workers-settle-stopped"
            and (match(ROOT / "tools/workers.py", [
                "settle-stopped", "runs/demo_20260101", "A-web-hunter-001",
            ]) or _spec("", "", "", "")).recorder == "control_journal"
            and match(ROOT / "tools/workers.py", [
                "settle-stopped", "runs/demo_20260101",
            ]) is None
            and match(ROOT / "tools/workers.py", [
                "settle-stopped", "runs/demo_20260101", "A-web-hunter-001",
                "--future",
            ]) is None)),
        ("workers stream-stall settlement is a distinct exact control capability", bool(
            (match(ROOT / "tools/workers.py", [
                "settle-stream-stalled", "runs/demo_20260101",
                "A-web-hunter-001",
            ]) or _spec("", "", "", "")).id
            == "control.workers-settle-stream-stalled"
            and (match(ROOT / "tools/workers.py", [
                "settle-stream-stalled", "runs/demo_20260101",
                "A-web-hunter-001",
            ]) or _spec("", "", "", "")).recorder == "control_journal"
            and match(ROOT / "tools/workers.py", [
                "settle-stream-stalled", "runs/demo_20260101",
            ]) is None
            and match(ROOT / "tools/workers.py", [
                "settle-stream-stalled", "runs/demo_20260101",
                "A-web-hunter-001", "--future",
            ]) is None)),
        ("workers hook-failed Stop recovery is a distinct exact control capability", bool(
            (match(ROOT / "tools/workers.py", [
                "recover-hook-failed-stop", "runs/demo_20260101",
                "A-review-001",
            ]) or _spec("", "", "", "")).id
            == "control.workers-recover-hook-failed-stop"
            and (match(ROOT / "tools/workers.py", [
                "recover-hook-failed-stop", "runs/demo_20260101",
                "A-review-001",
            ]) or _spec("", "", "", "")).recorder == "control_journal"
            and match(ROOT / "tools/workers.py", [
                "recover-hook-failed-stop", "runs/demo_20260101",
            ]) is None
            and match(ROOT / "tools/workers.py", [
                "recover-hook-failed-stop", "runs/demo_20260101",
                "A-review-001", "--future",
            ]) is None)),
        ("workers status is read while assignment is control", (match(
            ROOT / "tools/workers.py", ["status", "runs/demo_20260101"]
        ) or _spec("", "", "repo_mutation", "")).effect == "local_read"),
        ("work-plan status is read while commit is control", (match(
            ROOT / "tools/work_plan.py", ["status", "runs/demo_20260101"]
        ) or _spec("", "", "repo_mutation", "")).effect == "local_read"),
        ("runtime receipt read/reproject/quarantine have exact distinct effects", bool(
            (match(ROOT / "tools/runtime_receipts.py", [
                "runs/demo_20260101",
            ]) or _spec("", "", "", "")).id == "read.runtime-receipts"
            and (match(ROOT / "tools/runtime_receipts.py", [
                "runs/demo_20260101", "--reproject",
            ]) or _spec("", "", "", "")).id
            == "control.runtime-receipts-reproject"
            and (match(ROOT / "tools/runtime_receipts.py", [
                "runs/demo_20260101", "--reproject",
            ]) or _spec("", "", "", "")).recorder == "control_journal"
            and run_reference(
                match(ROOT / "tools/runtime_receipts.py", [
                    "runs/demo_20260101", "--reproject",
                ]) or _spec("", "", "", ""),
                ["runs/demo_20260101", "--reproject"],
            ) == "runs/demo_20260101"
            and match(ROOT / "tools/runtime_receipts.py", [
                "--reproject", "runs/demo_20260101",
            ]) is None
            and match(ROOT / "tools/runtime_receipts.py", [
                "runs/demo_20260101", "--future",
            ]) is None
            and (match(ROOT / "tools/runtime_receipts.py", [
                "runs/demo_20260101", "--quarantine-unowned-lifecycle",
            ]) or _spec("", "", "", "")).id
            == "control.runtime-receipts-quarantine"
            and (match(ROOT / "tools/runtime_receipts.py", [
                "runs/demo_20260101", "--quarantine-unowned-lifecycle",
            ]) or _spec("", "", "", "")).recorder == "control_journal"
            and match(ROOT / "tools/runtime_receipts.py", [
                "--quarantine-unowned-lifecycle", "runs/demo_20260101",
            ]) is None
        )),
        ("legacy work-plan migration is exact recorded active-run control", bool(
            (match(ROOT / "tools/work_plan.py", [
                "migrate-legacy", "runs/demo_20260101",
            ]) or _spec("", "", "", "")).id
            == "control.work-plan-legacy-migration"
            and (match(ROOT / "tools/work_plan.py", [
                "migrate-legacy", "runs/demo_20260101",
            ]) or _spec("", "", "", "")).effect == "control"
            and (match(ROOT / "tools/work_plan.py", [
                "migrate-legacy", "runs/demo_20260101",
            ]) or _spec("", "", "", "")).scope == "active_run"
            and run_reference(
                match(ROOT / "tools/work_plan.py", [
                    "migrate-legacy", "runs/demo_20260101",
                ]) or _spec("", "", "", ""),
                ["migrate-legacy", "runs/demo_20260101"],
            ) == "runs/demo_20260101"
            and (match(ROOT / "tools/work_plan.py", [
                "migrate-legacy", "runs/demo_20260101",
            ]) or _spec("", "", "", "")).recorder == "control_journal"
            and not (match(ROOT / "tools/work_plan.py", [
                "migrate-legacy", "runs/demo_20260101",
            ]) or _spec("", "", "", "")).root_direct_eligible
            and match(ROOT / "tools/work_plan.py", [
                "migrate-legacy", "runs/demo_20260101", "--future",
            ]) is None
            and match(ROOT / "tools/work_plan.py", ["migrate-legacy"]) is None
            and match(ROOT / "tools/work_plan.py", [
                "migrate-legacy", "runs/demo_20260101", "runs/other_20260101",
            ]) is None
        )),
        ("setup requires one exact source and splits classify as target", bool(
            match(ROOT / "tools/setup_run.py", [
                "demo", "recon.json", "--classify",
            ])
            and (match(ROOT / "tools/setup_run.py", [
                "demo", "recon.json", "--classify",
            ]) or _spec("", "", "repo_mutation", "")).effect == "target"
            and match(ROOT / "tools/setup_run.py", ["demo"]) is None
            and match(ROOT / "tools/setup_run.py", ["demo", "--classify"]) is None
        )),
        ("loop bootstrap accepts every supported typed source route", all(
            match(ROOT / "tools/loop_bootstrap.py", [
                "--source", "runs/demo_20260101", "--type", source_type,
            ]) is not None for source_type in ("auto", "run", "recon-json", "file")
        )),
        ("loop bootstrap resume first-matches the control capability", bool(
            (match(ROOT / "tools/loop_bootstrap.py", [
                "--resume", "runs/demo_20260101",
            ]) or _spec("", "", "repo_mutation", "")).id
            == "control.loop-bootstrap"
            and (match(ROOT / "tools/loop_bootstrap.py", [
                "--resume", "runs/demo_20260101",
            ]) or _spec("", "", "repo_mutation", "")).effect == "control"
        )),
        ("journal argv binds status/phase/end option ownership exactly", bool(
            (match(ROOT / "tools/loop_journal.py", [
                "runs/demo_20260101", "status",
            ]) or _spec("", "", "repo_mutation", "")).effect == "local_read"
            and match(ROOT / "tools/loop_journal.py", [
                "runs/demo_20260101", "phase-start",
            ]) is None
            and (match(ROOT / "tools/loop_journal.py", [
                "runs/demo_20260101", "end", "--next-action",
                "运行 check_run 验证当前计划",
            ]) or _spec("", "", "repo_mutation", "")).effect == "control"
            # Whether end is plan-bound is canonical run state, not argv. Keep
            # legacy end admissible here; loop_journal enforces the runtime
            # requirement after validating the typed journal.
            and (match(ROOT / "tools/loop_journal.py", [
                "runs/demo_20260101", "end",
            ]) or _spec("", "", "repo_mutation", "")).effect == "control"
            and match(ROOT / "tools/loop_journal.py", [
                "runs/demo_20260101", "start", "--next-action",
                "运行 check_run 验证当前计划",
            ]) is None
            and match(ROOT / "tools/loop_journal.py", [
                "runs/demo_20260101", "status", "--next-action",
                "运行 check_run 验证当前计划",
            ]) is None
        )),
        ("target selftests remain local verification", all(
            (match(ROOT / script, ["--selftest"])
             or _spec("", "", "repo_mutation", "")).effect == "local_verify"
            for script in ("tools/probe.py", "tools/render.py", "tools/replay.py")
        )),
        ("live probe requires method and URL", bool(
            match(ROOT / "tools/probe.py", ["GET", "https://example.test/"])
            and match(ROOT / "tools/probe.py", ["https://example.test/"]) is None
        )),
        ("scan capability binds one run and one absolute URL with no hidden argv", bool(
            match(ROOT / "tools/scan.py", [
                "--run", "runs/demo_20260101", "nuclei", "https://example.test/",
            ])
            and match(ROOT / "tools/scan.py", [
                "--run", "runs/demo_20260101", "--name", "E-001-scan",
                "sqlmap", "https://example.test/?id=1",
            ])
            and match(ROOT / "tools/scan.py", [
                "--run", "runs/demo_20260101", "nuclei", "https://example.test/",
                "-l", "/tmp/hidden-targets", "-o", "/tmp/hidden-output",
            ]) is None
            and match(ROOT / "tools/scan.py", [
                "--proxy", "http://untrusted-proxy:8080", "--run",
                "runs/demo_20260101", "nuclei", "https://example.test/",
            ]) is None
            and match(ROOT / "tools/scan.py", [
                "nuclei", "targets.txt",
            ]) is None
        )),
        ("classify capability is baseline-bound egress recheck only", bool(
            match(ROOT / "tools/classify_hosts.py", [
                "recon.json", "--out", "runs/demo_20260101/classify",
                "--run", "runs/demo_20260101",
                "--egress-recheck",
            ])
            and match(ROOT / "tools/classify_hosts.py", [
                "--hosts", "/tmp/hidden-targets", "--out",
                "runs/demo_20260101/classify", "--run", "runs/demo_20260101",
                "--egress-recheck",
            ]) is None
            and match(ROOT / "tools/classify_hosts.py", [
                "recon.json", "--out", "runs/demo_20260101/classify",
                "--run", "runs/demo_20260101", "--all",
            ]) is None
            and match(ROOT / "tools/classify_hosts.py", [
                "recon.json", "--out", "runs/demo_20260101/classify",
                "--run", "runs/demo_20260101",
            ]) is None
        )),
        ("render and fetch-assets require an explicit run binding", bool(
            match(ROOT / "tools/render.py", [
                "https://example.test/", "--run", "runs/demo_20260101",
            ])
            and match(ROOT / "tools/render.py", [
                "https://example.test/",
            ]) is None
            and match(ROOT / "tools/fetch_assets.py", [
                "https://example.test/", "--run", "runs/demo_20260101",
            ])
            and match(ROOT / "tools/fetch_assets.py", [
                "https://example.test/",
            ]) is None
        )),
        ("render eval and forced replay receive explicit capability ids", bool(
            (match(ROOT / "tools/render.py", [
                "https://example.test/", "--eval", "proof.js",
                "--run", "runs/demo_20260101",
            ]) or _spec("", "", "", "")).id == "target.render-eval"
            and (match(ROOT / "tools/replay.py", [
                "runs/demo_20260101", "--force",
            ]) or _spec("", "", "", "")).id == "target.replay-force"
        )),
        ("exploit modes reject unknown plugins and ambiguous delivery", bool(
            match(ROOT / "tools/exploit.py", [
                "viewstate", "--target", "https://example.test/", "--check",
            ])
            and match(ROOT / "tools/exploit.py", [
                "future", "--target", "https://example.test/", "--check",
            ]) is None
            and match(ROOT / "tools/exploit.py", [
                "viewstate", "--target", "https://example.test/",
                "--payload", "x", "--cmd", "id",
            ]) is None
        )),
    ]
    bad = [name for name, ok in checks if not ok]
    for name, ok in checks:
        print(("ok   " if ok else "FAIL ") + name)
    print("capability_registry selftest " + (
        "passed" if not bad else f"FAILED ({len(bad)})"))
    return 0 if not bad else 1


if __name__ == "__main__":
    raise SystemExit(selftest())
