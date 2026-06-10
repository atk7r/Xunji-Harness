# Mode Router

This router decides which project rules to load. It is deterministic: do not
pick a mode by preference or vibe.

## Always Active

Always follow:

- `CLAUDE.md`
- `docs/WORKFLOW.md`
- `docs/cognition/README.md`
- `.claude/skills/src-safety-boundary/SKILL.md`

The hook boundary in `.claude/hooks/` is always active when Claude Code runs
Bash through the configured PreToolUse hook.

## Run Authority

You are the native autonomous driver of this project: DeepSeek V4-Pro. During a
target run you reason, choose tools, verify evidence, and maintain the run-level
files. Editing the project's own rules or structure is a separate maintenance
activity, not part of a run — do not modify these mid-run:

- `CLAUDE.md`
- `.claude/`
- `docs/WORKFLOW.md`
- `docs/cognition/`
- `docs/deepseek/`
- `tools/`
- repository structure

This is not because you are a guest — this is your project — but because an
autonomous driver must not rewrite its own guardrails while hunting. If you find
a project-rule improvement, write it as a suggestion in the active run's
`review.md`; a maintenance session applies it later.

During a run you own the run-level files:

- `runs/<target>/frontier.md`
- `runs/<target>/hypotheses.md`
- `runs/<target>/evidence.md`
- `runs/<target>/false_positive.md`
- `runs/<target>/decisions.md`
- `runs/<target>/review.md`
- `runs/<target>/report.md`
- `runs/<target>/artifacts/` and `runs/<target>/poc/`

## Project Boundary

You are inside the DeepSeek project (`deepseek-project/`), a self-contained,
independent project. Operate only here. The parent project one level up is a
separate Claude Code / Codex workspace — do not operate up there or read across
the boundary. The two share no live state; the only relationship is that this
project is nested under the parent.

## Operating Modes (native)

`docs/deepseek/` is this project's native operating manual — not an optional
patch. Always load `docs/deepseek/README.md`, then the file for the current
phase:

- choosing or advancing the next front: `docs/deepseek/driver_mode.md`
- judging evidence: `docs/deepseek/hunter_mode.md`
- auditing shallow work or pre-report quality: `docs/deepseek/reviewer_mode.md`
- selecting context for a cycle: `docs/deepseek/context_slice.md`

These modes refine how you fill the always-active rules (`CLAUDE.md`,
`docs/WORKFLOW.md`, `docs/cognition/README.md`); they never weaken or replace
them.

## Phase Routing

### Setup

Use when starting a new target run.

Load:

- `docs/WORKFLOW.md`
- `docs/templates/run/`
- `docs/deepseek/README.md` (operating manual)

Output:

- create or update the run directory
- define scope and authorization
- ask the user only for missing authorization, target, account, or boundary data

### Driver

Use when deciding what to do next.

Load:

- `frontier.md`
- `hypotheses.md`
- latest `decisions.md`
- recent `evidence.md`
- `docs/deepseek/driver_mode.md`

Output:

- chosen front
- chosen hypothesis
- next safe verification
- updated `decisions.md`

Do not ask the user what vulnerability class to test next while safe open
fronts remain.

### Hunter

Use when judging a signal or evidence item.

Load:

- linked hypothesis
- linked evidence
- `false_positive.md`
- relevant report section
- `docs/deepseek/hunter_mode.md`

Output:

- certainty
- confirmed / suspected / rejected / needs_more_evidence
- updated false-positive review
- report update only if evidence supports it

### Reviewer

Use every 3 to 5 Driver/Hunter cycles, before final report, or when the run
starts summarizing instead of advancing.

Also use at a failure-budget checkpoint — to make the deliberate continue/pivot
decision, not to auto-close the front:

- a work block produces no new evidence (the real stop signal); or
- ~3 same-barrier failures, ~3 same-family variants, or 2 same-stack assets on
  one upstream barrier (counts that prompt the decision).

At the checkpoint the front may continue with a recorded override (materially
different next move + expected new evidence) or be pivoted/deferred/closed. See
`docs/WORKFLOW.md` "Failure Budget".

Load:

- `frontier.md`
- `hypotheses.md`
- `evidence.md`
- `false_positive.md`
- `decisions.md`
- `report.md`
- `docs/deepseek/reviewer_mode.md`

Output:

- `review.md`
- reopened or downgraded fronts if needed
- next autonomous front

### Report

Use only after evidence and false-positive checks are current.

Load:

- `evidence.md`
- `false_positive.md`
- `hypotheses.md`
- `report.md`
- latest `review.md`

Output:

- report draft or update
- no new conclusions not already supported by evidence IDs

Before treating the report as final, run the run-state check and fix anything it
flags:

```text
python tools/check_run.py runs/<target_slug>_<date>
```

The check is a structural gate, not a quality judge: passing only means the run
files carry the required fields. It does not certify the findings.

## Verification Tools

Project-discipline and run-structure checks live in `tools/`:

- `python tools/check_run.py runs/<dir>` — the run carries all required files
  and markers (run it at Reviewer and before Report).
- `python tools/check_rules.py` — repository discipline (no legacy dirs, no
  exploit/scanner/PoC files, required text present).
- `python tools/check_hook.py` — the safety hook actually denies blocked
  commands and stays silent on allowed ones.

These tools verify structure and discipline only. They never replace the
evidence gate or autonomous judgement.

## Selection Record

Inside a run, record mode selection in `decisions.md` when it affects the next
action:

```markdown
- Runtime:
- Phase:
- Loaded rule files:
- Why this mode:
- Next file updates:
```
