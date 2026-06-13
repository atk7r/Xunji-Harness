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

## On Request Only

Load only when the operator explicitly tells you to use the SRC skill. Do NOT
auto-load it by guessing a target belongs to a program.

- `.claude/skills/src-rules/SKILL.md` — SRC / bug-bounty program rules (e.g.
  教育漏洞报告平台 / EDUSRC 无害化原则). Applies on top of `src-safety-boundary`
  and tightens it for platform submissions (pivot off the table, data changes need
  platform authorization).

## Capability Skills (invoke when the task fits)

These are **procedure/tooling** skills, not playbooks: they encode a recurring,
error-prone *mechanism* (how to operate something), never attack methodology or
target selection. Invoke on demand when the task matches; do not auto-load.

- `.claude/skills/poc-package/SKILL.md` — packaging an authored PoC into a clean,
  handoff-ready artifact: xday/normal home, hardened binaries, and the
  **scrub-real-targets-before-handoff** discipline. Invoke before handing off,
  committing, or submitting any PoC.
- `.claude/skills/captcha-solve/SKILL.md` — getting past a captcha barrier
  (slider / click-select / rotate / text) by driving a real browser and reusing
  the page's own verification JS, then extracting the validate token. Invoke when
  a captcha gates the endpoint you need to verify.

## Run Authority

This is the Claude Code workspace, a **red-team toolkit for web 打点
(initial access)** (see `CLAUDE.md` Project Role). It is **Claude Code-specific**:
the machine-enforced safety floor (`.claude/hooks/` PreToolUse etc.), CLAUDE.md
auto-load, skills, and memory are Claude Code mechanisms — under a runtime without
them (e.g. Codex) the hard floor does not run, so the safety guarantees do not hold. The primary surface is the web
layer: targets reached over HTTP(S) / a browser, findings are web vulnerabilities
proven to genuinely exist. Host / OS exploitation, internal-network access,
lateral movement, binary research, and multi-stage red-team work are **in scope
as operator-gated soft capabilities** — allowed with the operator's consent, not
out of scope.

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
- `runs/<target>/hints.md` (conditional — only when the operator injects steering)

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
- if a recon/OSINT report is supplied, fold it first with
  `python tools/ingest_recon.py <recon.json>` (asset table + entry points +
  reachability matrix) and cite the source in `surface.md` — do not re-discover
  what the report already carries
- ask the user only for missing authorization, target, account, or boundary data

### Driver

Use when deciding what to do next.

Load:

- `frontier.md`
- `hypotheses.md`
- latest `decisions.md`
- recent `evidence.md`

Begin each Driver cycle with a **Reason pass**: re-read the *whole* `frontier.md`
(all open + deferred fronts) and the newest evidence before choosing — catch
newly-unlocked fronts and tunnel vision early. `python tools/graph.py runs/<dir>`
makes "what just got unlocked / neglected" a query instead of a re-read. The
Reason pass re-prioritizes only; it never closes a front. See `docs/WORKFLOW.md`
"Reason pass" and "State Graph".

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

**Before any closure / "explored enough" claim, the Reviewer phase MUST include an
independent reviewer** (a fresh-context `general-purpose` sub-agent, standing-
authorized) per `review/independent-reviewer.md` — self-review does not fix
self-review bias. Its findings go under `## Independent Review` in `review.md` and
must be resolved before closing. `tools/check_run.py` enforces this at the closure gate.

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
- `python tools/check_rules.py` — repository ARCHITECTURE-drift guard (no legacy
  orchestrator/playbook dirs or refs, required doctrine files present). It does NOT
  police weapons: exp/poc/scanner code is method and is free to live in the repo
  (`poc_library/`, `runs/<target>/`, `tools/poc_*`); irreversible harm is gated
  by effect at runtime by `.claude/hooks/safety_gate.py`, not by filename here.
- `python tools/check_hook.py` — the safety hook actually denies blocked
  commands and stays silent on allowed ones.
- `python tools/check_knowledge.py` — the grounding knowledge base keeps its
  structure and stays grounding (no payload/exploit/step fields; every anchor
  carries a reference and source). Run after editing `knowledge/`.
- `python tools/ingest_recon.py <recon.json>` — fold a recon/OSINT report into a
  `surface.md`-ready asset table, entry points, and a reachability matrix
  (recon-view vs your-egress-view). Setup-phase helper; structures intel, makes
  no front choices.
- `python tools/classify_hosts.py <recon.json>` — per-host classification by live
  content (not Server header): stack fingerprint + LOGIN/DYN/FRAMEWORK/SPA flags.
  Run before claiming "explored/no surface" so assets are examined, not lumped.
- `python tools/fetch_assets.py <page-url>` — fetch ALL JS a SPA references (incl.
  webpack chunks) and assert completeness. **Run before claiming endpoint
  enumeration is complete** — grepping endpoints from a partially-fetched JS set
  is how the 某实战 run missed an account-takeover endpoint (only 4/13 chunks
  fetched). "已抓 N/M" must be N==M before "端点已枚举完".
- `python tools/rerun_deferred.py --run runs/<dir>` — re-probe the assets that were
  unreachable (egress-deferred) per `coverage.json`, from any egress (after a
  cooldown, a switched egress, or run in-country by the operator). Reports which
  became reachable + re-classifies them → the standardized "come back to the
  deferred list" path instead of hunting through `frontier.md`.
- `python tools/graph.py runs/<dir>` — derive the typed state graph from the run
  files (H/F/E nodes + `Unlocked-by`/`Supports`/`Refutes` edges) → `graph.json` +
  a view of actionable / unlocked-but-deferred / closed-but-unlocked / dangling
  Facts. **Run at the start of a Reason pass** so "what just got unlocked or
  neglected" is a query, not a re-read. Derived and advisory only — it never
  selects the next front (that stays the driver). See `docs/WORKFLOW.md` "State
  Graph".
- `python tools/workers.py runs/<dir>` — parallel fan-out bookkeeping: `--new
  <F-id>` scaffolds a worker scratch file; the bare form lists worker status and
  flags any `done`-but-unmerged worker whose candidates the driver still owes the
  evidence gate. Scaffold + ledger only — it never spawns workers or picks fronts
  (the driver does, via the Agent tool). See `docs/WORKFLOW.md` "Parallel Fan-out"
  and `docs/templates/worker.md`.

These tools verify structure and discipline only. They never replace the
evidence gate or autonomous judgement.

Active-verification tools (`probe.py` / `render.py` / `scan.py`, all guard-routed)
are sensors, not gates. `scan.py` (sqlmap/nuclei) is **opt-in when a front is
already grounded and you want cheap breadth** — its output is a ≤0.5 lead that
Hunter discipline still adjudicates, never a verdict, and never the front-selection
decision. Skipping it for a manual, controlled probe (e.g. under a noisy WAF) is a
legitimate driver choice, not a gap.

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
