===== CLAUDE.md =====
- `docs/ROUTER.md` decides which mode guidance to load; deterministic (runtime +
  phase + run state → files).
- The five Router phases are `Setup`, `Root Orchestrator`, `Hunter`, `Reviewer`,
  and `Report`. Whenever one of these phases is entered or left, print an
  obvious Chinese, box-style operator marker with bracket tags (for example
  `[Xunji] [阶段开始] [Hunter｜验证挖掘]`) and ANSI color when the terminal supports it.
  Once a run directory exists, record the same transition with
  `tools/loop_journal.py phase-start|phase-end --phase ...`.
  Mechanical Setup inside `setup_run.py` is the one display exception: record its
  start/end in the journal but do not print separate box banners, because the
  tool's progress output and selected-run statusline already expose that state.
  Do not invent markers for lifecycle mechanics such as resume, handoff, drift
  recovery, `/loop`, or closure gates. Operator-facing lifecycle/status output
  should be Chinese, keep bracket tags as no-color fallback, and summarize the
  current phase, run dir, blockers, and next required action before any raw
  details.
- Claude Code statusline is a read-only indicator for this project. It prints
  nothing without an explicit Xunji workspace and active run; otherwise it shows
  only `[Xunji-status] [<phase>] <run>`. Detailed progress and health remain in
  visible phase banners and `loop_journal.py` phase-start/phase-end records.
- **Target-facing privacy boundary:** Root and every Agent must keep generated
  project/run/Agent/operator identity and real personal data out of outbound URL
  paths/queries, headers, bodies, multipart names/content, and target writes. Use
===== docs/WORKFLOW.md =====
阶段进入/退出必须对操作者可见。When a run enters or leaves one of the Router
phases (`Setup`, `Root Orchestrator`, `Hunter`, `Reviewer`, `Report`), print a
clear Chinese phase marker and, once a run directory exists, record it in the
loop journal:

```bash
python tools/loop_journal.py runs/<dir> phase-start --phase "Root Orchestrator" --note "why this phase starts"
python tools/loop_journal.py runs/<dir> phase-end --phase "Root Orchestrator" --note "result and next phase"
```

`setup_run.py` 的机械 Setup 是显示例外：仍写入 Setup 的 `phase_start` / `phase_end`
journal 事件，但不额外打印 box banner，避免与工具进度及选中 run 的 statusline
重复。其他实际进入的 Router 阶段继续显示 start/end marker。

Only mark phases actually entered. `Resume`, `/loop`, handoff, and closure gates
are lifecycle mechanics, not extra Router phases.

Operator-facing lifecycle output should be Chinese, box-style, and `[标签]`
based when possible, with ANSI color as presentation only. Show current phase,
open/deferred/closed fronts, evidence delta, coverage delta, Agent conflicts,
stop blockers, and next required action before detailed raw state.

The point is to make "what just got unlocked / neglected / contradicted / unassigned"
a query, not a full re-read of every block. Ask:

1. Did new evidence **confirm, refute, or unlock** any front?
===== docs/ROUTER.md =====
### Phase Start / End Visibility

The Router phases are exactly: `Setup`, `Root Orchestrator`, `Hunter`,
`Reviewer`, and `Report`. Each phase that is actually entered must produce a
Chinese, box-style visible start marker and a matching visible end marker. Use
bracket tags as the no-color fallback and ANSI color when the terminal supports
it:

```text
╭─ [Xunji] [阶段开始] [Hunter｜验证挖掘] ...
...
╭─ [Xunji] [阶段结束] [Hunter｜验证挖掘] ...
```

When a run directory exists, record the same transition in
`state/loop_journal.jsonl`:

```bash
python tools/loop_journal.py runs/<dir> phase-start --phase "<Phase>" --note "<why>"
python tools/loop_journal.py runs/<dir> phase-end --phase "<Phase>" --note "<result; next phase>"
```

Mechanical Setup performed inside `setup_run.py` is the display exception: keep
its journal start/end events, but do not print separate box banners. The setup
tool's normal progress output and selected-run statusline already make that state
visible. Other Router phases retain their visible start/end markers.

Do not fake markers for phases skipped by the current turn. `Resume`, `/loop`,
handoff, drift recovery, and closure gates are lifecycle mechanics, not extra
Router phases.

Operator-facing lifecycle/status prints should be Chinese first. Prefer compact
`[标签]` panels that show current phase, run directory, front counts, evidence
delta, stop blockers, and next required action before raw JSON or file paths.

===== .claude/skills/xunji-run-lifecycle/SKILL.md =====
being drafted or finalized. `Resume`, handoff, drift recovery, and closure gates
are lifecycle mechanics, not extra phases.

Operator-facing lifecycle output should be Chinese first and bracket-tagged.
Detailed phase banners may summarize front counts, evidence/coverage delta, stop
blockers, and next actions before raw state paths or JSON; the persistent
statusline is intentionally narrower.
`setup_run.py` keeps Setup start/end in the loop journal but deliberately omits
its own box banners so setup progress and statusline do not duplicate the phase.

Claude Code's project statusline is enabled for Xunji through
`.claude/settings.json` and `tools/xunji_statusline.py`. It should stay concise:
`[Xunji-status] [Hunter｜验证] <run>`. It prints nothing until Claude supplies an
explicit Xunji workspace and that workspace has an active run. Treat it as
read-only display. It does not replace phase markers, `loop_journal.py`, or
PreToolUse enforcement.

## Setup

Create a new run in one shot:
