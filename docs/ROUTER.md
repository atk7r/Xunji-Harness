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

This is the Claude Code / Codex workspace, scoped to **web application
penetration testing only** (see `CLAUDE.md` Project Role). Every run is a
web-layer SRC run: targets reached over HTTP(S) / a browser, findings are
individual web vulnerabilities proven by harmless verification. Host / OS
exploitation, internal-network or lateral movement, binary research, and
multi-stage red-team campaigns are out of scope; if a target or task implies
them, stop and tell the user it is outside this workspace.

The driver may edit project files when the user asks for project changes. During
a target run, the run-level files are the work product:

- `runs/<target>/frontier.md`
- `runs/<target>/hypotheses.md`
- `runs/<target>/evidence.md`
- `runs/<target>/false_positive.md`
- `runs/<target>/decisions.md`
- `runs/<target>/review.md`
- `runs/<target>/report.md`
- `runs/<target>/chains.md` (conditional — only when a vulnerability chain exists)

## Project Boundary

`deepseek-project/` is a separate, self-contained DeepSeek copy of this project,
nested under it. It is an independent project with its own baseline, driven by
DeepSeek inside its own root. Do not operate inside `deepseek-project/` from here
or read across the boundary; the two share no live state.

## Phase Routing

### Setup

Use when starting a new target run.

Load:

- `docs/WORKFLOW.md`
- `docs/templates/run/`

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

Output:

- chosen front
- chosen hypothesis
- next safe verification
- updated `decisions.md`

Do not ask the user what vulnerability class to test next while safe open
fronts remain.

Commitment is evidence-gated. Stay in breadth-first reconnaissance (fingerprint,
surface, grounding observations) while a front's `certainty` is below the
confirmation threshold; commit to depth-first verification of a single front
only once an observation grounds it. Committing deep effort to one front before
the evidence supports it is a failure mode, not progress — it is the
over-digging the Reviewer failure budget exists to catch. A scan or other
recon tool is sensor input that feeds this gate; it is never the front-selection
decision itself.

### Hunter

Use when judging a signal or evidence item.

Load:

- linked hypothesis
- linked evidence
- `false_positive.md`
- relevant report section

Output:

- certainty
- confirmed / suspected / rejected / needs_more_evidence
- updated false-positive review
- report update only if evidence supports it
- if a confirmed finding's proven output state meets another finding's
  precondition, record the chain edge in `chains.md` and open it as a new front
  (组合利用); a chain is only as strong as its weakest confirmed hop

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
- `chains.md` (if present)

Output:

- report draft or update
- the atomic findings, plus any composed chain with its higher composite
  severity (when `chains.md` has a confirmed chain)
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
- `python tools/check_knowledge.py` — the grounding knowledge base keeps its
  structure and stays grounding (no payload/exploit/step fields; every anchor
  carries a reference and source). Run after editing `knowledge/`.

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
