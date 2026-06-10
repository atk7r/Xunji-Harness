# vulnfinder

vulnfinder is an autonomous SRC workspace for Claude Code / Codex. It is built
to support AI-driven vulnerability discovery while keeping the process
auditable, evidence-bound, and safe.

The project is not a scanner, PoC library, exploit framework, or JSON
orchestrator. It provides operating rules, run-state structure, safety
boundaries, and local checks.

## Project Logic

The core idea is:

```text
single AI driver
  -> maintain written run state
  -> choose the next exploration front autonomously
  -> verify with evidence
  -> review for shallow work and false positives
  -> report only what evidence supports
```

The AI should not wait for the user to name the next vulnerability class while
safe open fronts remain. It should select a front, record why, and continue
until the front is confirmed, rejected, deferred with a blocker, or closed with
Type B reasoning.

## Authority Model

Claude Code / Codex are the project-maintenance runtimes. They may edit project
files when the user asks for project changes.

DeepSeek is a model-specific patch layer, not a project owner. DeepSeek may help
with run-level analysis, evidence review, and shallow-work auditing, but it has
no authority to modify project rules, hooks, skills, tools, or repository
structure. DeepSeek suggestions about project rules should be written into the
active run's `review.md` for Claude Code / Codex to evaluate.

## Routing

Use [docs/ROUTER.md](docs/ROUTER.md) to decide what guidance applies.

Always active:

- [CLAUDE.md](CLAUDE.md)
- [docs/WORKFLOW.md](docs/WORKFLOW.md)
- [docs/cognition/README.md](docs/cognition/README.md)
- [.claude/skills/src-safety-boundary/SKILL.md](.claude/skills/src-safety-boundary/SKILL.md)

DeepSeek patch layer:

- [docs/deepseek/README.md](docs/deepseek/README.md)
- [docs/deepseek/context_slice.md](docs/deepseek/context_slice.md)
- [docs/deepseek/driver_mode.md](docs/deepseek/driver_mode.md)
- [docs/deepseek/hunter_mode.md](docs/deepseek/hunter_mode.md)
- [docs/deepseek/reviewer_mode.md](docs/deepseek/reviewer_mode.md)

## File Map

### Core Rules

- `CLAUDE.md`: short always-loaded operating contract.
- `docs/ROUTER.md`: deterministic mode routing and authority boundary.
- `docs/WORKFLOW.md`: run-state workflow and file templates.
- `docs/cognition/README.md`: judgment discipline, false-positive resistance,
  and shallow-work smells.

### Safety Boundary

- `.claude/settings.json`: registers the PreToolUse hook for Bash.
- `.claude/hooks/safety_gate.py`: deterministic deny boundary.
- `.claude/hooks/safety_rules.json`: deny-rule configuration.
- `.claude/skills/src-safety-boundary/SKILL.md`: boundary-only skill.

### DeepSeek Patch

- `docs/deepseek/`: DeepSeek-only operating notes, prompt skeletons, context
  slicing rules, and reviewer templates.

DeepSeek patch files supplement the core rules. They do not replace them.

### Run State

Each authorized target run lives under:

```text
runs/<target_slug>_<date>/
  target.md
  surface.md
  frontier.md
  hypotheses.md
  evidence.md
  false_positive.md
  decisions.md
  review.md
  report.md
```

The run directory is the audit trail. Findings are not confirmed from chat
memory, model confidence, or single unattributed signals.

### Templates

- `docs/templates/run/`: empty run files that can be copied when starting a new
  target.

### Local Checks

- `tools/check_rules.py`: checks that legacy orchestrator surfaces, PoC files,
  live-probe scripts, and forbidden references have not been reintroduced.
- `tools/check_hook.py`: tests the local hook against blocked and allowed
  command examples.
- `tools/check_run.py`: checks that a run directory has the required autonomy
  audit files and markers.

## Safety Model

The hook blocks destructive host/file operations, permission changes, target
resource deletion, money movement, online brute force, DoS-style behavior, and
high-rate scanning patterns.

A blocked action is not unlocked by human approval. Choose a safe,
non-destructive proof instead.

Scope is not encoded in the hook. Only test targets that are authorized for the
current engagement.

## Local Checks

```powershell
.\.venv\Scripts\python.exe tools\check_rules.py
.\.venv\Scripts\python.exe tools\check_hook.py
.\.venv\Scripts\python.exe tools\check_run.py runs\cdut_20260610
```

These tools inspect local files and hook behavior only. They do not contact
targets.
