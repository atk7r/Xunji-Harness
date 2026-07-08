# Evidence Ledger

## E-001

- Maturity: candidate
- Reportable: no
- Time: 2026-07-08T00:00:00+08:00
- Action: Implemented a Claude Code project statusline renderer.
- Source: repository diff
- Result: `tools/xunji_statusline.py` renders a concise Chinese statusline from `.claude/xunji_active_run`, derived `state/*.json`, and `state/loop_journal.jsonl`; normal rendering is read-only.
- Control: `tools/xunji_statusline.py --selftest` verifies project-outside silence, invalid pointer rejection, read-only render mtimes, ANSI output, and next-action extraction.
- Caused by us: yes
- Alternative explanation: The renderer may become stale if upstream Claude Code statusline JSON fields change.
- Certainty: 0.8
- Artifacts: evidence/patches/tools__xunji_statusline_py.patch.txt
- Supports: F-001, F-002, F-004
- Next: Independent review should verify the renderer does not mutate run state during normal statusline execution.

## E-002

- Maturity: candidate
- Reportable: no
- Time: 2026-07-08T00:00:00+08:00
- Action: Wired the renderer into Claude Code project settings.
- Source: repository diff
- Result: `.claude/settings.json` adds `statusLine` command with a 2 second refresh interval and project-local script path.
- Control: statusline selftest invokes the script through its normal command path with `XUNJI_COLOR=1` and verifies ANSI output.
- Caused by us: yes
- Alternative explanation: Local Claude Code versions without `statusLine` support may ignore or reject the setting.
- Certainty: 0.8
- Artifacts: evidence/patches/_claude__settings_json.patch.txt
- Supports: F-001, F-002
- Next: Independent review should check the settings key/shape and project-only activation boundary.

## E-003

- Maturity: candidate
- Reportable: no
- Time: 2026-07-08T00:00:00+08:00
- Action: Integrated active-run pointer updates into bootstrap and fixed `/loop` protocol.
- Source: repository diff
- Result: `loop_bootstrap.py` sets the pointer on new/resume and `docs/templates/loop_prompt.md` sets it at explicit `/loop` start; pointer state is ignored by Git.
- Control: `tools/loop_bootstrap.py --selftest` verifies the active-run helper accepts a project-local run and restores the prior pointer.
- Caused by us: yes
- Alternative explanation: If a run directory is outside the repository root, the statusline intentionally refuses to track it.
- Certainty: 0.8
- Artifacts: evidence/patches/tools__loop_bootstrap_py.patch.txt, evidence/patches/docs__templates__loop_prompt_md.patch.txt, evidence/patches/_gitignore.patch.txt
- Supports: F-002, F-003
- Next: Independent review should check normal chat remains unaffected and `/loop` remains explicit.

## E-004

- Maturity: candidate
- Reportable: no
- Time: 2026-07-08T00:00:00+08:00
- Action: Documented statusline boundary in Claude primary-driver instructions and workflow docs.
- Source: repository diff
- Result: `CLAUDE.md`, `.claude/skills/xunji-run-lifecycle/SKILL.md`, and `docs/WORKFLOW.md` state the statusline is read-only and does not replace phase markers, journal records, or hook enforcement.
- Control: independent review receives the documentation diff plus the implementation diff in the same frozen bundle.
- Caused by us: yes
- Alternative explanation: Documentation can drift if implementation changes without updating the selftest.
- Certainty: 0.8
- Artifacts: evidence/patches/CLAUDE_md.patch.txt, evidence/patches/_claude__skills__xunji-run-lifecycle__SKILL_md.patch.txt, evidence/patches/docs__WORKFLOW_md.patch.txt
- Supports: F-001, F-003
- Next: Independent review should check the boundary is stated in Claude primary-driver files, not only Codex-side `.agents/skills`.

## E-005

- Maturity: candidate
- Reportable: no
- Time: 2026-07-08T00:00:00+08:00
- Action: Ran focused regression tests.
- Source: local command output
- Result: Syntax checks, JSON validation, statusline selftest, bootstrap selftest, selected `selftest_all.py` suite, rules, templates, and whitespace diff check passed.
- Control: the selected `selftest_all.py` run includes `xunji_statusline`, and its wiring diff is included as a patch artifact.
- Caused by us: yes
- Alternative explanation: Focused tests do not fully emulate Claude Code's proprietary statusline runtime.
- Certainty: 0.8
- Artifacts: evidence/patches/tools__selftest_all_py.patch.txt, evidence/test-log.txt
- Supports: F-004
- Next: Commit should record the remaining limitation that local tests cannot fully invoke Claude Code's internal statusline renderer.

## E-006

- Maturity: candidate
- Reportable: no
- Time: 2026-07-08T00:00:00+08:00
- Action: Checked Claude Code statusline/settings schema against official documentation.
- Source: official documentation
- Result: Claude Code documents `statusLine` as the settings key for a command-backed statusline, including `command`, `refreshInterval`, `padding`, and stdin JSON with workspace current directory context.
- Control: Local `.claude/settings.json` was validated as JSON and the command target was exercised by `tools/xunji_statusline.py --selftest`.
- Caused by us: yes
- Alternative explanation: Documentation may change in a future Claude Code release; the local test cannot fully emulate Claude Code's proprietary renderer.
- Certainty: 0.8
- Artifacts: evidence/official-docs/claude-code-statusline-excerpt.txt, evidence/official-docs/claude-code-settings-excerpt.txt
- Supports: F-001, F-002
- Next: If Claude Code changes the settings schema, update `.claude/settings.json` and this review record.
