# Codex-Authored Maintenance Diff Review Scope

## Review Object

The current uncommitted repository maintenance diff fixes the statusline setup gap:
new runs created by `tools/setup_run.py` should automatically set
`.claude/xunji_active_run`, so Claude Code statusline no longer displays
`Idle｜空闲 未选择运行目录` immediately after one-shot setup.

This is Codex-authored maintenance. Codex self-review is not an independent review.
Use `--driver codex`, where independent reviewers are arkcli panel plus Claude Code
CLI when available.

## Expected Invariants

- `setup_run.py` may update local display state after a valid run skeleton exists.
- `setup_run.py` must not enter `/loop`.
- `setup_run.py` must not choose fronts, promote evidence, or make closure decisions.
- Statusline rendering remains read-only during normal refresh.
- Pointer write failure should not break setup; it should be visible as a warning.
- Selftests must restore any pre-existing active-run pointer.

## Review Questions

- Is `_set_active_run(run_dir)` called after `scaffold(run_dir)` succeeds and before setup output continues?
- Does `_set_active_run()` reuse `xunji_statusline.set_active_run()` validation instead of duplicating pointer-write logic?
- Could the new helper leave `.claude/xunji_active_run` pointing at a temporary selftest run?
- Do docs and Claude primary-driver skills state the new setup/statusline linkage accurately?
- Is any safety or lifecycle boundary weakened by treating setup as statusline-active?

## Current Diff Under Review

The authoritative current diff is saved at `evidence/final3-diff.txt`. The
authoritative current test log is saved at `evidence/final3-test-log.txt`.

## Superseded Initial Diff (Round 0, Not Current)

```diff
diff --git a/.claude/skills/xunji-run-lifecycle/SKILL.md b/.claude/skills/xunji-run-lifecycle/SKILL.md
index b58bb86..d5a3f95 100644
--- a/.claude/skills/xunji-run-lifecycle/SKILL.md
+++ b/.claude/skills/xunji-run-lifecycle/SKILL.md
@@ -102,6 +102,10 @@ Create a new run in one shot:
 python tools/setup_run.py <slug> [recon.json]
 ```

+`setup_run.py` sets `.claude/xunji_active_run` to the newly created run as local
+statusline display state. This does not enter `/loop`, choose a front, or make any
+evidence/closure decision.
+
 Use `--classify` only for an authorized current egress recheck:

 ```bash
diff --git a/.claude/skills/xunji-setup-ingest/SKILL.md b/.claude/skills/xunji-setup-ingest/SKILL.md
index 0646b9d..674f1c6 100644
--- a/.claude/skills/xunji-setup-ingest/SKILL.md
+++ b/.claude/skills/xunji-setup-ingest/SKILL.md
@@ -36,7 +36,9 @@ With recon, setup should:
 - write `knowledge_hits.md` when local signatures match.

 `setup_run.py` prepares the workbench. It does not pick fronts, decide findings,
-or attack the target.
+or attack the target. After the run skeleton exists, it also sets
+`.claude/xunji_active_run` so the Claude Code statusline points at the new run;
+that pointer is local display state only.

 ## Scope And Coverage

diff --git a/docs/WORKFLOW.md b/docs/WORKFLOW.md
index f661ebe..fd01092 100644
--- a/docs/WORKFLOW.md
+++ b/docs/WORKFLOW.md
@@ -96,8 +96,8 @@ current Router phase, run name, pending verification entries, aggregated Agent
 state, blockers, and the next action in Chinese. It reads `.claude/xunji_active_run`
 plus derived `state/*.json` / `state/loop_journal.jsonl` only; it does not refresh
 state, choose work, write evidence, or enforce phase discipline. The active-run
-pointer is local runtime state and is updated by `loop_bootstrap.py` and the fixed
-`/loop runs/<dir>` protocol.
+pointer is local runtime state and is updated by `setup_run.py`, `loop_bootstrap.py`,
+and the fixed `/loop runs/<dir>` protocol.

 阶段进入/退出必须对操作者可见。When a run enters or leaves one of the Router
 phases (`Setup`, `Root Orchestrator`, `Hunter`, `Reviewer`, `Report`), print a
diff --git a/tools/setup_run.py b/tools/setup_run.py
index b1eb21e..ff2f45a 100644
--- a/tools/setup_run.py
+++ b/tools/setup_run.py
@@ -45,6 +45,7 @@ REQUIRED = ["target.md", "surface.md", "frontier.md", "hypotheses.md", "evidence
 sys.path.insert(0, str(Path(__file__).resolve().parent))

 import loop_journal  # noqa: E402
+import xunji_statusline  # noqa: E402


 def _today() -> str:
@@ -70,6 +71,17 @@ def _phase_journal(run_dir: Path, event: str, phase: str, note: str) -> None:
         print(f"[setup] phase journal skipped: {exc}", file=sys.stderr)


+def _set_active_run(run_dir: Path) -> None:
+    """Best-effort statusline pointer update. It is display state, not evidence."""
+    try:
+        if xunji_statusline.set_active_run(str(run_dir)):
+            print(f"[setup] statusline active run: runs/{run_dir.name}")
+        else:
+            print(f"[setup] statusline active run skipped: {run_dir}", file=sys.stderr)
+    except Exception as exc:
+        print(f"[setup] statusline active run skipped: {exc}", file=sys.stderr)
+
+
 def scaffold(run_dir: Path) -> list[str]:
     """从模板建齐必需文件 + evidence/ scripts/ 子目录(含 .gitkeep)。不覆盖已存在目录。"""
     run_dir.mkdir(parents=True, exist_ok=False)   # exist_ok=False -> 已存在则 FileExistsError
@@ -400,6 +412,7 @@ def main() -> int:
     made = scaffold(run_dir)
     print(_phase_banner("start", "Setup", run_dir=run_dir, note="prepare authorized run workbench"))
     _phase_journal(run_dir, "phase_start", "Setup", "prepare authorized run workbench")
+    _set_active_run(run_dir)
     print(f"[setup] 建 run 骨架 {run_dir}")
     print(f"        {len(made)} 个核心文件 + evidence/ + scripts/")
     coverage_ready = False
@@ -562,6 +575,24 @@ def _selftest() -> int:
          and target_cov["assets"][0]["port"] == 8080),
     ]

+    tmp_root = ROOT / "tmp"
+    tmp_root.mkdir(exist_ok=True)
+    active_rd = Path(tempfile.mkdtemp(dir=tmp_root)) / "run"
+    scaffold(active_rd)
+    old_active = xunji_statusline.ACTIVE_RUN.read_text(encoding="utf-8", errors="replace") \
+        if xunji_statusline.ACTIVE_RUN.exists() else None
+    try:
+        _set_active_run(active_rd)
+        active = xunji_statusline.active_run()
+    finally:
+        if old_active is None:
+            xunji_statusline.clear_active_run()
+        else:
+            xunji_statusline.ACTIVE_RUN.write_text(old_active, encoding="utf-8")
+    checks += [
+        ("setup writes statusline active run pointer", active == active_rd.resolve()),
+    ]
+
     bad = [n for n, ok in checks if not ok]
     for n, ok in checks:
         print(("ok   " if ok else "FAIL ") + n)
```

## Superseded Initial Verification Log (Round 0, Not Current)

The authoritative current test log is `evidence/final3-test-log.txt`. The log
below is retained only as round history.

```text
[setup] statusline active run: runs/run
ok   all required files copied
ok   evidence/ subdir
ok   scripts/ subdir
ok   operator profile scaffolded
ok   frontier template has depth field
ok   no-overwrite guard raises
ok   setup phase banner is visible
ok   setup phase journal closes
ok   target.md records recon path
ok   recon path with backslashes intact (no re.sub group bug)
ok   surface_recon.md written w/ asset
ok   ingest reports asset count
ok   scope 派生填进 target.md Target
ok   scope 派生填进 In-scope assets
ok   record_scope 报派生计数
ok   adapt_coverage 写 classify/coverage.json
ok   coverage 含资产 a.example
ok   coverage examined=0(零重探, 没发包)
ok   coverage source 标 guanlan-adapter
ok   no-recon target records 'none'
ok   no-recon without Target does not claim coverage built
ok   malformed target does not write coverage
ok   record_target fills target.md Target
ok   no-recon explicit target writes coverage
ok   target-derived coverage parses scheme and port
ok   setup writes statusline active run pointer
setup_run selftest passed
ok   plain statusline is human-readable
ok   open fronts use pentest wording
ok   subagents are aggregated
ok   next action uses plan note
ok   colored statusline has ansi
ok   XUNJI_COLOR command path has ansi
ok   unknown phase fallback is styled
ok   normal render is read-only
ok   invalid outside run pointer is rejected
ok   outside Xunji prints nothing
xunji_statusline selftest passed
rule check passed
running 2 selftest suite(s) with /opt/homebrew/opt/python@3.14/bin/python3.14

  PASS  setup_run          0.1s  run scaffolding
  PASS  xunji_statusline   0.1s  Claude Code Xunji statusline

2 passed, 0 failed  (0.2s total)
```

## Round 1 Follow-Up

The first independent review returned WARN and identified that the selftest
mutated the real `.claude/xunji_active_run` pointer and leaked temp directories.
The current diff fixes that by monkeypatching `xunji_statusline.ACTIVE_RUN` to an
isolated temp pointer during the test and removing the temp parent directory in
`finally`.

The final full diff is saved at `evidence/final2-diff.txt`; the final rerun test
log is saved at `evidence/final2-test-log.txt`.

## Round 2 Follow-Up

The second independent review returned WARN because several evidence entries and
the primary report section still pointed at the superseded initial diff. This
record now treats `evidence/final3-diff.txt` and `evidence/final3-test-log.txt` as
the current authoritative artifacts. The current code also asserts module pointer
restoration, asserts the real active-run pointer file remains untouched, cleans
the temp directory, and clarifies that `setup_run.py --classify` is a new-run
setup option rather than an existing-run refresh mode.

## Round 3 Follow-Up

The third independent review returned WARN, with no BLOCKER. It found one stale
artifact reference (E-004 still pointed to the Round-1 follow-up) and one untested
best-effort failure path. This final record updates all confirmed evidence entries
to the current `final2` artifacts and adds branch tests for `set_active_run()`
returning `False` and raising an exception. The remaining limitation is deliberate:
the automated selftest does not run a production CLI invocation that mutates the
real `.claude/xunji_active_run`, because preserving the operator's active pointer
is the safer test invariant.

## Round 4 Follow-Up

The fourth panel run returned `NEEDS_DRIVER` because arkcli failed across all
three models, but Claude Code CLI completed. A standalone Claude Code CLI final
review found no blocker and flagged lazy-import/call-site-documentation issues.
The current final3 diff addresses both: the `xunji_statusline` import moved into
`_set_active_run()` and the unconditional setup call site now documents that it is
for new-run creation, not future existing-run modes.

## Scope Note

`docs/ROUTER.md` entered scope during review because Round 2 identified ambiguity
around `setup_run.py --classify`. The ROUTER change is documentation-only and
clarifies that `--classify` remains a one-shot new-run setup option, not an
existing-run refresh mode.
