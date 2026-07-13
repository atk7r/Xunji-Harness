#!/usr/bin/env python3
"""Claude Code statusline for Xunji.

This script is display-only during normal statusline use. It prints nothing until
Claude provides an explicit Xunji workspace and that workspace has an active run.
For an active run it renders only the current phase and run name. It never refreshes
cache files, mutates run evidence, or drives an engagement.
"""
from __future__ import annotations

import argparse
import calendar
import json
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
except Exception:
    pass

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

import status_style  # noqa: E402

ACTIVE_RUN = ROOT / ".claude" / "xunji_active_run"
PHASE_LABELS = {
    "Setup": "Setup｜准备",
    "Root Orchestrator": "Root｜调度",
    "Hunter": "Hunter｜验证",
    "Reviewer": "Reviewer｜复审",
    "Report": "Report｜报告",
    "Idle": "Idle｜空闲",
    "Paused": "Paused｜已暂停",
    "Interrupted": "Interrupted｜中断待恢复",
}
PHASE_COLOR = {
    "Setup": "blue",
    "Root Orchestrator": "cyan",
    "Hunter": "yellow",
    "Reviewer": "purple",
    "Report": "green",
    "Idle": "gray",
    "Paused": "gray",
    "Interrupted": "red",
}


def _load_json(path: Path, default):
    try:
        data = json.loads(path.read_text(encoding="utf-8", errors="replace"))
        return data if isinstance(data, type(default)) else default
    except Exception:
        return default


def _read_input() -> dict:
    try:
        raw = sys.stdin.read()
    except Exception:
        raw = ""
    if not raw.strip():
        return {}
    try:
        data = json.loads(raw)
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def _workspace_dir(payload: dict) -> Path | None:
    workspace = payload.get("workspace") if isinstance(payload.get("workspace"), dict) else {}
    raw = (
        workspace.get("current_dir")
        or workspace.get("currentDir")
    )
    if not raw:
        return None
    try:
        return Path(str(raw)).expanduser().resolve()
    except (OSError, RuntimeError, ValueError):
        return None


def _is_xunji_context(current_dir: Path) -> bool:
    try:
        current_dir.relative_to(ROOT)
    except ValueError:
        return False
    return (
        (ROOT / "CLAUDE.md").exists()
        and (ROOT / "tools" / "loop_state.py").exists()
        and (ROOT / ".claude" / "skills").is_dir()
    )


def _looks_like_run_dir(run_dir: Path) -> bool:
    markers = ("target.md", "frontier.md", "evidence.md", "decisions.md", "review.md")
    return run_dir.is_dir() and any((run_dir / marker).exists() for marker in markers)


def _run_ref(run_dir: Path) -> str:
    try:
        return str(run_dir.resolve().relative_to(ROOT))
    except ValueError:
        return str(run_dir.resolve())


def _resolve_run(raw: str) -> Path | None:
    value = raw.strip()
    if not value:
        return None
    path = Path(value).expanduser()
    run_dir = path if path.is_absolute() else ROOT / path
    run_dir = run_dir.resolve()
    try:
        run_dir.relative_to(ROOT)
    except ValueError:
        return None
    if not _looks_like_run_dir(run_dir):
        return None
    return run_dir


def set_active_run(raw: str) -> bool:
    run_dir = _resolve_run(raw)
    if run_dir is None:
        return False
    current = active_run()
    if current != run_dir:
        try:
            import turn_contract  # noqa: WPS433

            if current is None:
                # UserPromptSubmit stores a short-lived pending contract when no
                # run exists. Claim it before the first pointer is installed.
                turn_contract.claim_pending_contract(run_dir)
            else:
                # A valid current-turn contract belongs to the operator prompt,
                # not to the old pointer. Copy it before the atomic switch.
                turn_contract.transfer_contract(current, run_dir)
        except Exception:
            return False
    ACTIVE_RUN.parent.mkdir(parents=True, exist_ok=True)
    tmp_name = ""
    with tempfile.NamedTemporaryFile(
        "w",
        delete=False,
        dir=ACTIVE_RUN.parent,
        prefix=ACTIVE_RUN.name + ".",
        suffix=".tmp",
        encoding="utf-8",
    ) as f:
        tmp_name = f.name
        f.write(_run_ref(run_dir) + "\n")
    Path(tmp_name).replace(ACTIVE_RUN)
    return True


def clear_active_run() -> None:
    try:
        ACTIVE_RUN.unlink()
    except FileNotFoundError:
        pass


def active_run() -> Path | None:
    try:
        raw = ACTIVE_RUN.read_text(encoding="utf-8", errors="replace")
    except Exception:
        return None
    return _resolve_run(raw)


def _journal_summary(run_dir: Path) -> dict:
    path = run_dir / "state" / "loop_journal.jsonl"
    if not path.exists():
        return {"open_phase": "", "interrupted": False, "last_event": None, "last_cycle_events": []}
    events: list[dict] = []
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines()[-500:]:
        if not line.strip():
            continue
        try:
            item = json.loads(line)
            if isinstance(item, dict):
                events.append(item)
        except Exception:
            continue
    last_cycle = max([int(e.get("cycle", 0) or 0) for e in events], default=0)
    current = [e for e in events if int(e.get("cycle", 0) or 0) == last_cycle]
    open_phase = ""
    for rec in current:
        event = str(rec.get("event") or "")
        phase = str((rec.get("data") or {}).get("phase") or "").strip()
        if event == "phase_start":
            open_phase = phase
        elif event == "phase_end" and phase == open_phase:
            open_phase = ""
    return {
        "open_phase": open_phase,
        "interrupted": any(str(e.get("event") or "") == "interrupt" for e in current),
        "last_event": events[-1] if events else None,
        "last_cycle_events": [str(e.get("event") or "") for e in current],
    }


def _event_age_seconds(journal: dict) -> float | None:
    event = journal.get("last_event") if isinstance(journal.get("last_event"), dict) else {}
    raw = str(event.get("ts") or "")
    try:
        return max(0.0, time.time() - calendar.timegm(time.strptime(raw, "%Y-%m-%dT%H:%M:%SZ")))
    except Exception:
        return None


def _phase(loop_data: dict, journal: dict, run_dir: Path) -> str:
    status = _load_json(run_dir / "state" / "run_status.json", {})
    if str(status.get("status") or "") == "paused_by_operator":
        return "Paused"
    open_phase = str(journal.get("open_phase") or "").strip()
    if open_phase:
        age = _event_age_seconds(journal)
        if age is None or age > 5 * 60:
            return "Interrupted"
        return open_phase
    phase = str(loop_data.get("phase") or "").strip()
    return phase or "Idle"


def _phase_tag(phase: str, *, color: bool) -> str:
    label = PHASE_LABELS.get(phase, phase or PHASE_LABELS["Idle"])
    return status_style.tag(label, PHASE_COLOR.get(phase, "white"), enabled=color)


def _state_stale(run_dir: Path) -> bool:
    try:
        latest_md = max((p.stat().st_mtime for p in run_dir.glob("*.md")), default=0.0)
    except Exception:
        return False
    if latest_md <= 0:
        return False
    try:
        derived_mtime = (run_dir / "state" / "loop_state.json").stat().st_mtime
    except Exception:
        return True
    return latest_md > derived_mtime + 0.001


def _derived_loop_state(run_dir: Path) -> tuple[dict | None, str]:
    """Read-only fallback for a missing or stale phase cache.

    Import lazily so normal cached rendering stays cheap. Controller, coverage,
    Agent, and next-action derivations are deliberately outside statusline scope.
    """
    try:
        import loop_state  # noqa: WPS433
        loop_data = loop_state.derive(run_dir, write=False)
    except Exception as exc:
        return None, exc.__class__.__name__
    return loop_data, ""


def render_statusline(payload: dict | None = None, *, color: bool | None = None) -> str:
    payload = payload or {}
    current_dir = _workspace_dir(payload)
    if current_dir is None or not _is_xunji_context(current_dir):
        return ""
    run_dir = active_run()
    if run_dir is None:
        return ""

    stale = _state_stale(run_dir)
    loop_data = _load_json(run_dir / "state" / "loop_state.json", {})
    if stale or not loop_data:
        derived_loop, _ = _derived_loop_state(run_dir)
        if derived_loop is not None:
            loop_data = derived_loop
    journal = _journal_summary(run_dir)
    phase = _phase(loop_data, journal, run_dir)
    return (
        f"{status_style.tag('Xunji-status', 'cyan', enabled=color)} "
        f"{_phase_tag(phase, color=bool(color))} {run_dir.name}"
    )


def _selftest() -> int:
    global ACTIVE_RUN

    def fingerprint(path: Path | None) -> tuple[bool, bytes, int]:
        if path is None:
            return False, b"", 0
        try:
            return True, path.read_bytes(), path.stat().st_mtime_ns
        except FileNotFoundError:
            return False, b"", 0

    root_current = {"workspace": {"current_dir": str(ROOT)}}
    tmp_root = ROOT / "tmp"
    tmp_root.mkdir(exist_ok=True)
    temp = Path(tempfile.mkdtemp(dir=tmp_root))
    run = temp / "run"
    run.mkdir()
    (run / "target.md").write_text("# Target\n", encoding="utf-8")
    (run / "frontier.md").write_text("# Frontier\n", encoding="utf-8")
    (run / "state").mkdir()
    (run / "state" / "loop_state.json").write_text(json.dumps({
        "phase": "Root Orchestrator",
        "fronts": {"open_count": 6},
    }), encoding="utf-8")
    # Keep populated legacy summary sources beside the phase fixture. The exact
    # output assertion below proves these fields cannot leak back into statusline.
    (run / "state" / "controller.shadow.json").write_text(json.dumps({
        "next_required_action": "continue_driver_on_actionable_open_front",
        "stop_blockers": ["legacy blocker must stay hidden"],
    }), encoding="utf-8")
    (run / "state" / "assignments.json").write_text(json.dumps({
        "assignments": [{"agent": "A-001", "status": "working"}],
    }), encoding="utf-8")
    (run / "state" / "asset_ledger.json").write_text(json.dumps({
        "summary": {"total": 9, "front_linked": 4, "unassigned": 5, "disposed": 0},
    }), encoding="utf-8")
    (run / "state" / "loop_journal.jsonl").write_text(
        json.dumps({"cycle": 1, "event": "phase_start", "data": {"phase": "Hunter"}, "note": "",
                    "ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}, ensure_ascii=False) + "\n"
        + json.dumps({"cycle": 1, "event": "plan", "data": {}, "note": "目标=F-004; 原因=接口枚举",
                      "ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    real_active_pointer = ACTIVE_RUN
    real_run = active_run()
    real_contract_path = real_run / "state" / "turn_contract.json" if real_run else None
    real_pointer_before = fingerprint(real_active_pointer)
    real_contract_before = fingerprint(real_contract_path)
    ACTIVE_RUN = temp / "xunji_active_run"
    try:
        assert set_active_run(str(run))
        watched = [
            ACTIVE_RUN,
            run / "state" / "loop_state.json",
            run / "state" / "controller.shadow.json",
            run / "state" / "assignments.json",
            run / "state" / "asset_ledger.json",
            run / "state" / "loop_journal.jsonl",
        ]
        before_render = {p: p.stat().st_mtime_ns for p in watched}
        plain = render_statusline(root_current, color=False)
        colored = render_statusline(root_current, color=True)
        unspecified = render_statusline({}, color=False)
        cwd_only = render_statusline({"cwd": str(ROOT)}, color=False)
        empty_workspace = render_statusline(
            {"workspace": {"current_dir": ""}}, color=False)
        nested_workspace = render_statusline(
            {"workspace": {"current_dir": str(ROOT / "tools")}}, color=False)
        env = dict(os.environ)
        env["XUNJI_COLOR"] = "1"
        env.pop("NO_COLOR", None)
        env.pop("XUNJI_NO_COLOR", None)
        cli_program = (
            "import sys\n"
            "from pathlib import Path\n"
            f"sys.path.insert(0, {str(ROOT / 'tools')!r})\n"
            "import xunji_statusline as statusline\n"
            f"statusline.ACTIVE_RUN = Path({str(ACTIVE_RUN)!r})\n"
            "raise SystemExit(statusline.main([]))\n"
        )
        cli_proc = subprocess.run(
            [sys.executable, "-c", cli_program],
            input=json.dumps(root_current),
            text=True,
            capture_output=True,
            env=env,
            timeout=10,
        )
        cli_colored = cli_proc.stdout
        after_render = {p: p.stat().st_mtime_ns for p in watched}
        (run / "state" / "turn_contract.json").write_text(json.dumps({
            "schema": "xunji.turn_contract.v1",
            "mode": "EXECUTE",
            "session_id": "statusline-transition",
            "updated_at": time.time(),
        }), encoding="utf-8")
        (run / "state" / "run_status.json").write_text(json.dumps({
            "status": "paused_by_operator",
        }), encoding="utf-8")
        paused_plain = render_statusline(root_current, color=False)
        (run / "state" / "run_status.json").unlink()
        (run / "state" / "loop_journal.jsonl").write_text("", encoding="utf-8")
        (run / "state" / "loop_state.json").write_text(json.dumps({
            "phase": "Reviewer",
        }), encoding="utf-8")
        cached_plain = render_statusline(root_current, color=False)
        (run / "state" / "loop_state.json").write_text(json.dumps({
            "phase": "Setup",
        }), encoding="utf-8")
        setup_plain = render_statusline(root_current, color=False)
        (run / "state" / "loop_journal.jsonl").write_text(json.dumps({
            "cycle": 2,
            "event": "phase_start",
            "data": {"phase": "Hunter"},
            "note": "",
            "ts": "2000-01-01T00:00:00Z",
        }) + "\n", encoding="utf-8")
        interrupted_plain = render_statusline(root_current, color=False)
        outside_dir = Path(tempfile.mkdtemp())
        unknown_phase = _phase_tag("Unexpected Phase", color=True)
        invalid_rejected = set_active_run(str(outside_dir)) is False
        outside = render_statusline({"workspace": {"current_dir": str(outside_dir)}}, color=False)
        clear_active_run()
        no_active = render_statusline(root_current, color=False)
        assert set_active_run(str(run))
        missing_cache = temp / "missing-cache-run"
        missing_cache.mkdir()
        (missing_cache / "frontier.md").write_text(
            "# Frontier\n\n## Open Fronts\n\n### F-009 Missing cache\n- Status: open\n",
            encoding="utf-8",
        )
        (missing_cache / "evidence.md").write_text("# Evidence Ledger\n", encoding="utf-8")
        (missing_cache / "decisions.md").write_text("# Decisions\n", encoding="utf-8")
        (missing_cache / "hypotheses.md").write_text("# Hypotheses\n", encoding="utf-8")
        (missing_cache / "state").mkdir()
        (missing_cache / "state" / "loop_journal.jsonl").write_text(
            json.dumps({"cycle": 1, "event": "phase_start", "data": {"phase": "Setup"}, "note": "prepare authorized run workbench"}, ensure_ascii=False) + "\n"
            + json.dumps({"cycle": 1, "event": "phase_end", "data": {"phase": "Setup"}, "note": "run prepared; next phase=Root Orchestrator (/loop runs/missing-cache-run)"}, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
        assert set_active_run(str(missing_cache))
        inherited_contract = _load_json(
            missing_cache / "state" / "turn_contract.json", {})
        source_contract_after = _load_json(
            run / "state" / "turn_contract.json", {})
        missing_before = sorted((p.relative_to(missing_cache).as_posix() for p in missing_cache.rglob("*")))
        missing_plain = render_statusline(root_current, color=False)
        missing_after = sorted((p.relative_to(missing_cache).as_posix() for p in missing_cache.rglob("*")))
        original_derived_state = _derived_loop_state
        try:
            globals()["_derived_loop_state"] = lambda _run_dir: (None, "RuntimeError")
            failed_derive_plain = render_statusline(root_current, color=False)
        finally:
            globals()["_derived_loop_state"] = original_derived_state
    finally:
        ACTIVE_RUN = real_active_pointer
    real_pointer_after = fingerprint(real_active_pointer)
    real_contract_after = fingerprint(real_contract_path)

    checks = [
        ("plain statusline contains only status phase and run",
         plain == f"[Xunji-status] [Hunter｜验证] {run.name}"),
        ("populated legacy summary state cannot leak fields", " | " not in plain),
        ("operator pause is visible without extra fields",
         paused_plain == f"[Xunji-status] [Paused｜已暂停] {run.name}"),
        ("cached phase is rendered without extra fields",
         cached_plain == f"[Xunji-status] [Reviewer｜复审] {run.name}"),
        ("setup phase is rendered without extra fields",
         setup_plain == f"[Xunji-status] [Setup｜准备] {run.name}"),
        ("stale open phase renders interrupted without extra fields",
         interrupted_plain == f"[Xunji-status] [Interrupted｜中断待恢复] {run.name}"),
        ("colored statusline has ansi", "\033[" in colored and "[Hunter｜验证]" in colored),
        ("unknown phase fallback is styled", "\033[" in unknown_phase and "[Unexpected Phase]" in unknown_phase),
        ("normal render is read-only", before_render == after_render),
        ("unspecified workspace prints nothing", unspecified == ""),
        ("top-level cwd alone does not select a workspace", cwd_only == ""),
        ("empty workspace prints nothing", empty_workspace == ""),
        ("nested Xunji workspace renders the selected run",
         nested_workspace == f"[Xunji-status] [Hunter｜验证] {run.name}"),
        ("isolated CLI stdin-to-stdout path renders color",
         cli_proc.returncode == 0
         and "\033[" in cli_colored
         and "[Hunter｜验证]" in cli_colored
         and run.name in cli_colored),
        ("workspace without active run prints nothing", no_active == ""),
        ("missing cache still renders only phase and run",
         missing_plain.startswith("[Xunji-status] [")
         and missing_plain.endswith(f"] {missing_cache.name}")
         and " | " not in missing_plain),
        ("missing cache live derivation is read-only", missing_before == missing_after),
        ("active-run switch inherits current turn contract before pointer update",
         inherited_contract.get("session_id") == "statusline-transition"
         and inherited_contract.get("origin_run") == run.name
         and inherited_contract.get("bound_run") == missing_cache.name
         and source_contract_after.get("session_id") == "statusline-transition"),
        ("failed live derivation stays concise",
         failed_derive_plain == f"[Xunji-status] [Idle｜空闲] {missing_cache.name}"),
        ("invalid outside run pointer is rejected", invalid_rejected),
        ("outside Xunji prints nothing", outside == ""),
        ("selftest uses an isolated active-run pointer",
         ACTIVE_RUN == real_active_pointer
         and real_pointer_before == real_pointer_after
         and real_contract_before == real_contract_after),
    ]
    bad = [name for name, ok in checks if not ok]
    for name, ok in checks:
        print(("ok   " if ok else "FAIL ") + name)
    print("xunji_statusline selftest " + ("passed" if not bad else f"FAILED ({len(bad)})"))
    return 0 if not bad else 1


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="render Xunji Claude Code statusline")
    ap.add_argument("--set-active", metavar="RUN_DIR", help="set the active Xunji run pointer")
    ap.add_argument("--clear-active", action="store_true", help="clear the active Xunji run pointer")
    ap.add_argument("--selftest", action="store_true")
    args = ap.parse_args(argv)

    if args.selftest:
        return _selftest()
    if args.clear_active:
        clear_active_run()
        return 0
    if args.set_active:
        if not set_active_run(args.set_active):
            print(f"[xunji_statusline] invalid run dir: {args.set_active}", file=sys.stderr)
            return 1
        return 0

    line = render_statusline(_read_input(), color=status_style.color_enabled())
    if line:
        print(line)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
