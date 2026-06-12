# Xunji

Xunji is an autonomous red-team workspace for Claude Code / Codex, focused
on web 打点 (initial access). It supports AI-driven vulnerability discovery and
exploitation while keeping the process auditable, evidence-bound, and bounded by
a machine-enforced hard-rule floor.

The project is not a scanner, PoC library, turnkey exploit kit, or JSON
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

This is the Claude Code / Codex workspace. The driver may edit project files when
the user asks for project changes, and owns the run-level files during a run.

DeepSeek is not run here. It has its own separate, independent project nested at
`deepseek-project/` with its own baseline. Do not operate across that boundary
(see Routing).

## Routing

Use [docs/ROUTER.md](docs/ROUTER.md) to decide what guidance applies.

Always active:

- [CLAUDE.md](CLAUDE.md)
- [docs/WORKFLOW.md](docs/WORKFLOW.md)
- [docs/cognition/README.md](docs/cognition/README.md)
- [.claude/skills/src-safety-boundary/SKILL.md](.claude/skills/src-safety-boundary/SKILL.md)

On request only (load when the operator explicitly says to use the SRC skill — not
auto-loaded):

- [.claude/skills/src-rules/SKILL.md](.claude/skills/src-rules/SKILL.md) — SRC /
  bug-bounty program rules (e.g. EDUSRC 无害化原则).

Nested DeepSeek project:

- `deepseek-project/` is an independent DeepSeek copy of this project. It is
  driven by DeepSeek inside its own root and is out of scope for this workspace.

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
- `.claude/skills/src-rules/SKILL.md`: SRC / bug-bounty program rules — loaded
  only on the operator's explicit request, not always active.

### Nested DeepSeek Project

- `deepseek-project/`: a separate, self-contained DeepSeek copy of this project
  with its own baseline, driven by DeepSeek. Independent of this workspace; the
  only relationship is that it is nested under it.

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

The hook blocks irreversible destruction (host/file wipes plus data destruction
— DROP/TRUNCATE/unscoped DELETE/UPDATE), target resource deletion, mass data
exfiltration / database dump (拖库), money movement, and DoS-style / high-rate
behavior. Uploading a proof artifact is not blocked
(driver's call). Getting a shell, going past the web layer, and other heavier
actions are not machine-blocked either but are operator-gated — the driver gets
the operator's consent first.

A blocked action is not unlocked by human approval. Choose a safe,
non-destructive proof instead.

Scope is not encoded in the hook. The operator is the highest authority and runs
authorized targets; their instruction overrides the soft constraints and is the
controlling order everywhere except the hard boundary above.

## Setup

A fresh clone needs almost nothing: the core toolchain has **zero third-party
dependencies** (Python standard library only). The single optional dependency is
Playwright, used only by the browser tools (`render.py`, the captcha solver).

### Requirement (the only hard one)

- **Python ≥ 3.10 on PATH.** Covers the PreToolUse hook (`safety_gate.py`), the
  `check_*` checkers, and `probe.py` / `scan.py`. The hook is wired with
  `$CLAUDE_PROJECT_DIR` (no hard-coded paths), so it is portable across machines
  with no edits.

### Browser tools (optional — only for `render.py` / captcha solving)

```bash
python -m venv .venv
# Windows: .venv\Scripts\activate   |   Linux/macOS: source .venv/bin/activate
pip install playwright
playwright install chromium
```

`render.py` and the captcha solver run under the venv python
(`.venv\Scripts\python.exe` on Windows, `.venv/bin/python` elsewhere). Skipping
this does not affect `probe.py`, `scan.py`, the hook, or the checkers.

### Directories & state

`runs/`, `knowledge/`, and `poc_library/` already exist via shipped
`.gitkeep` / `README` files. The guard's rate-limit / counter state
(`tools/harness/.state/`) is created automatically on first run; `reports/` and
`poc/` are created on demand. No manual directory setup is needed.

### Not restored by a clone (by design)

- **Auto-memory** lives outside the repo (`~/.claude/projects/.../memory/`) and
  is per-machine — a clone does not carry it.
- **Concrete PoCs / 0day entries / built binaries** (`poc_library/xday/`,
  `tools/poc_ours_upload/`) and **curated knowledge entries** (`knowledge/*.md`)
  are git-ignored and never published — transfer them out of band if needed.
- **Run findings** (`runs/<target>/`) are not committed; older runs also
  reference machine-local OSINT paths that will not exist elsewhere.
- **`.claude/settings.local.json`** (permission allowlist) is local — re-grant
  permissions once on a new machine.

## Local Checks

```powershell
.\.venv\Scripts\python.exe tools\check_rules.py
.\.venv\Scripts\python.exe tools\check_hook.py
.\.venv\Scripts\python.exe tools\check_run.py runs\<target_slug>_<date>
```

These tools inspect local files and hook behavior only. They do not contact
targets.
