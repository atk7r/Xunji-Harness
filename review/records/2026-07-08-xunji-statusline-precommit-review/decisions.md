# Decisions

## D-001 — Use Claude Code Project Statusline, Not A Scripted Prompt Boundary

Decision: implement the always-visible status indicator through `.claude/settings.json` `statusLine`, backed by `tools/xunji_statusline.py`.

Reason: the operator wanted real-time display that does not require pasting generated prompts. Claude Code statusline is the appropriate display mechanism, while `/loop` remains explicit.

## D-002 — Keep Statusline Read-Only

Decision: normal rendering only reads the active pointer and derived run state. Mutation is limited to explicit maintenance commands `--set-active` and `--clear-active`.

Reason: statusline refreshes frequently. It must not create evidence, refresh state, choose targets, or become a hidden loop driver.

## D-003 — Restrict To This Checkout

Decision: the renderer returns an empty line when `workspace.current_dir` is outside this repository root, and it refuses active run pointers outside the root.

Reason: the operator explicitly asked for the status to be enabled only in the Xunji project.

## D-004 — Prefer Operator Terms Over Cryptic Counters

Decision: replace compact counters such as `F 6/1/3 E 4/0 B 0` with Chinese operator terms such as `待验证入口 N 个`, `子任务 ...`, `无阻断`, and `下一步 ...`.

Reason: the statusline must remain understandable even when subagents add noise or the operator glances at it mid-run.

## D-005 — Use Bootstrap And `/loop` To Keep The Pointer Current

Decision: `loop_bootstrap.py` updates the pointer for new/resume flows, and the fixed `/loop` template updates it at journal start.

Reason: statusline should follow the active run without making normal chat a loop.
