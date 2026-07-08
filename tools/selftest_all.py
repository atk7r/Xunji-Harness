#!/usr/bin/env python3
"""Aggregate self-test runner — runs every tool/hook/subsystem selftest in one shot.

Why: each tool ships its own `--selftest` (and the hooks / sentinel ship their own
regression entrypoints), but they are scattered — verifying a safety-critical change
means remembering to run six-plus commands by hand, and the easy-to-forget ones rot.
This runs the whole battery and prints one green/red scorecard, so a护栏 change can be
regression-checked with a single command before the independent review.

This is a dumb, honest runner: it invokes known-safe selftests and reports their exit
codes. It is NOT the driver and does NOT score vuln-finding (that is the R-1 eval
harness, still a backlog item). The registry is explicit on purpose — never glob and
run arbitrary files.

Usage:
    python tools/selftest_all.py            # run all, print scorecard, exit 0/1
    python tools/selftest_all.py --verbose  # also dump each suite's output
    python tools/selftest_all.py --only check_run,replay
    python tools/selftest_all.py --list
"""
from __future__ import annotations

import argparse
import os
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

# Force UTF-8 everywhere: on zh Windows the default GBK stdio mangles/раises on
# Chinese output from the children (see memory windows-gbk-stdio-footgun).
try:
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
except Exception:
    pass


# Each entry: (name, argv-after-python, note). argv is relative to ROOT.
# Exit 0 == pass for every one of these. Keep this list explicit and audited.
SUITES: list[tuple[str, list[str], str]] = [
    # --- verification tools (--selftest flag) ---
    ("check_run",      ["tools/check_run.py", "--selftest"],      "evidence gate + closure"),
    ("classify_hosts", ["tools/classify_hosts.py", "--selftest"], "recon -> coverage"),
    ("scope",          ["tools/scope.py", "--selftest"],          "run scope derive/match"),
    ("peer_review",    ["tools/peer_review.py", "--selftest"],    "heterogeneous review"),
    ("probe",          ["tools/probe.py", "--selftest"],          "active HTTP sensor"),
    ("render",         ["tools/render.py", "--selftest"],         "headless browser + --eval replay"),
    ("anti_drift",     ["tools/anti_drift.py", "--selftest"],     "anti-drift anchor (rules+process re-inject)"),
    ("proxy",          ["tools/harness/proxy.py", "--selftest"],  "engagement egress proxy (渗透走/模型不走)"),
    ("codex_proxy",    ["tools/harness/codex_proxy.py", "--selftest"], "Codex review proxy hygiene"),
    ("replay",         ["tools/replay.py", "--selftest"],         "evidence replay"),
    ("setup_run",      ["tools/setup_run.py", "--selftest"],      "run scaffolding"),
    ("ingest_recon",    ["tools/ingest_recon.py", "--selftest"],   "Guanlan recon adapter"),
    ("bench",          ["tools/bench.py", "--selftest"],          "R-1 self-eval scorer"),
    ("check_knowledge", ["tools/check_knowledge.py", "--selftest"], "public knowledge grounding structure"),
    ("local_hygiene",  ["tools/check_local_hygiene.py"],          "local/publication hygiene guard"),
    ("runtime_boundary", ["tools/check_runtime_boundary.py"],         "Codex hooks absence guard"),
    ("check_templates", ["tools/check_templates.py"],             "template/reference drift guard"),
    ("knowledge_match", ["tools/knowledge_match.py", "--selftest"], "fingerprint→knowledge retrieval"),
    ("xday_match",      ["tools/xday_match.py", "--selftest"],      "fingerprint→local xday retrieval"),
    ("knowledge_seed",  ["tools/knowledge_seed.py", "--selftest"],  "fingerprint→knowledge write-back"),
    ("timestamp_gate",  ["tools/timestamp_gate.py", "--selftest"],  "web research time gate"),
    ("record_evidence", ["tools/record_evidence.py", "--selftest"], "web research -> evidence ledger"),
    ("decode_viewstate", ["tools/decode_viewstate.py", "--selftest"], "ASP.NET ViewState decoder"),
    ("input_shape",     ["tools/input_shape.py", "--selftest"],     "request shape parser"),
    ("js_inventory",    ["tools/js_inventory.py", "--selftest"],    "saved-artifact JS/API inventory sensor"),
    ("oob_listener",    ["tools/oob_listener.py", "--selftest"],    "local OOB listener"),
    ("sensor_oob",      ["tools/sensors/oob_listener.py", "--selftest"], "OOB callback artifact sensor"),
    ("sensor_mutate",   ["tools/sensors/mutate_payload.py", "--selftest"], "payload mutation artifact sensor"),
    ("sensor_blind_diff", ["tools/sensors/blind_diff.py", "--selftest"], "blind differential artifact sensor"),
    ("sensor_upload",   ["tools/sensors/upload_probe.py", "--selftest"], "harmless upload proof sensor"),
    ("sensor_client_graybox", ["tools/sensors/client_graybox.py", "--selftest"], "client graybox phenomenon sensor"),
    ("state_project",   ["tools/state_project.py", "--selftest"], "markdown-derived run state projection"),
    ("context_pack",    ["tools/context_pack.py", "--selftest"], "minimal subagent context pack"),
    # --- loop pipeline ---
    ("loop_state",       ["tools/loop_state.py", "--selftest"], "closed-loop progress and gate snapshot"),
    ("progress_ledger",  ["tools/progress_ledger.py", "--selftest"], "material-progress ledger"),
    ("run_controller",   ["tools/run_controller.py", "--selftest"], "advisory shadow run controller"),
    ("loop_bootstrap",   ["tools/loop_bootstrap.py", "--selftest"],   "autonomous loop launcher"),
    ("session_handoff",  ["tools/session_handoff.py", "--selftest"],  "session handoff tool"),
    ("deferred_queue",   ["tools/deferred_queue.py", "--selftest"],   "deferred asset retry manager"),
    ("workers",          ["tools/workers.py", "--selftest"],          "fan-out worker planning helpers"),
    ("saturation",       ["tools/saturation.py", "--selftest"],       "front saturation scoring"),
    ("coverage_matrix",  ["tools/coverage_matrix.py", "--selftest"],  "asset x vuln-family coverage matrix"),
    # --- PreToolUse / Stop hooks (--selftest flag) ---
    ("safety_gate",    [".claude/hooks/safety_gate.py", "--selftest"], "hard-boundary gate"),
    ("ip_blacklist",   [".claude/hooks/ip_blacklist.py", "--selftest"], "local IP/domain deny hook"),
    ("output_gate",    [".claude/hooks/output_gate.py", "--selftest"], "output drift Stop gate"),
    ("run_gate",       [".claude/hooks/run_gate.py", "--selftest"],    "coverage/depth Stop gate"),
    # --- live-fire safety test (drives safety_gate with real commands) ---
    ("check_hook",     ["tools/check_hook.py"],                   "safety_gate live-fire"),
    # --- sentinel regression (run the module directly) ---
    ("sentinel_replay", ["sentinel/replay.py"],                   "behavior detectors 26-case"),
    ("verify_layers",   ["sentinel/verify_layers.py"],            "safety-floor coverage"),
    # --- guard smoke test (NOTE: os.replace can flake on Windows; see --help) ---
    ("guard_smoke",    ["tools/harness/guard.py"],                "guard rate/cap/breaker smoke"),
]

# Suites whose smoke test is known-flaky on Windows (transient os.replace lock).
# Given one retry before being declared failed — never masks a real, repeatable fail.
FLAKY = {"guard_smoke"}


def _child_env() -> dict[str, str]:
    env = dict(os.environ)
    env["PYTHONUTF8"] = "1"
    env["PYTHONIOENCODING"] = "utf-8"
    return env


def run_suite(name: str, argv: list[str], timeout: int) -> tuple[bool, str, float]:
    """Return (passed, captured_output, seconds)."""
    cmd = [sys.executable, *[str(ROOT / a) if a.endswith(".py") else a for a in argv]]
    t0 = time.monotonic()
    try:
        proc = subprocess.run(
            cmd, cwd=ROOT, env=_child_env(),
            capture_output=True, text=True, encoding="utf-8", errors="replace",
            timeout=timeout,
        )
        out = (proc.stdout or "") + (proc.stderr or "")
        return proc.returncode == 0, out, time.monotonic() - t0
    except subprocess.TimeoutExpired as e:
        return False, f"TIMEOUT after {timeout}s\n{e.output or ''}", time.monotonic() - t0
    except Exception as e:  # noqa: BLE001 — surface any launch failure as a red suite
        return False, f"LAUNCH ERROR: {e!r}", time.monotonic() - t0


def main() -> int:
    ap = argparse.ArgumentParser(description="Run every selftest and print a scorecard.")
    ap.add_argument("--verbose", action="store_true", help="dump each suite's output, not just failures")
    ap.add_argument("--only", help="comma-separated suite names to run (default: all)")
    ap.add_argument("--timeout", type=int, default=300, help="per-suite timeout seconds (default 300)")
    ap.add_argument("--list", action="store_true", help="list suite names and exit")
    args = ap.parse_args()

    if args.list:
        for name, argv, note in SUITES:
            print(f"  {name:16} {note}")
        return 0

    suites = SUITES
    if args.only:
        want = {s.strip() for s in args.only.split(",") if s.strip()}
        unknown = want - {n for n, _, _ in SUITES}
        if unknown:
            print(f"unknown suite(s): {', '.join(sorted(unknown))}", file=sys.stderr)
            return 2
        suites = [s for s in SUITES if s[0] in want]

    print(f"running {len(suites)} selftest suite(s) with {sys.executable}\n")
    results: list[tuple[str, bool, str, float]] = []
    for name, argv, note in suites:
        ok, out, secs = run_suite(name, argv, args.timeout)
        if not ok and name in FLAKY:
            ok2, out2, secs2 = run_suite(name, argv, args.timeout)  # one retry
            if ok2:
                ok, out, secs = ok2, out2 + "\n[retried once after transient flake]", secs + secs2
        status = "PASS" if ok else "FAIL"
        print(f"  {status}  {name:16} {secs:5.1f}s  {note}")
        if (not ok or args.verbose) and out.strip():
            tail = out.strip().splitlines()
            shown = tail if args.verbose else tail[-25:]
            for line in shown:
                print(f"         | {line}")
        results.append((name, ok, out, secs))

    passed = sum(1 for _, ok, _, _ in results if ok)
    failed = len(results) - passed
    total_s = sum(s for _, _, _, s in results)
    print(f"\n{passed} passed, {failed} failed  ({total_s:.1f}s total)")
    if failed:
        print("FAILED: " + ", ".join(n for n, ok, _, _ in results if not ok), file=sys.stderr)
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
