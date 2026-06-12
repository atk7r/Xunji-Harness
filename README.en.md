# Xunji

> **English** | [中文](README.md)

Xunji is an autonomous red-team workspace for Claude Code / Codex, focused
on web 打点 (initial access). It supports AI-driven vulnerability discovery and
exploitation while keeping the process auditable, evidence-bound, and bounded by
a machine-enforced hard-rule floor.

It is not a scanner, a turnkey mass-exploit kit, or a JSON orchestrator — it gives
the AI judgment discipline, grounded recognition knowledge, run-state structure,
and a machine-enforced hard floor (see Design Philosophy below). Weaponized
exploits the driver authors are allowed (method is free); only irreversible harm
auto-executed against the target is hard-blocked.

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

## Design Philosophy（设计思路）

The whole project rests on one decision and three pillars.

### The axis: gate EFFECTS, not METHODS

What is ever restricted is the **irreversible effect an action has on the live
target, and who presses execute** — never the technique. Crafting and writing
weaponized exploitation (RCE chains, auth bypass, deserialization gadgets,
upload-to-shell, privilege escalation, C2 / reverse-shell / webshell code) is
**method, and method is free**; 0day discovery lives there. The only hard line is
an **irreversible / harm-as-purpose effect auto-executed against the target**
(destruction, 拖库, DoS, money movement) — and that line is drawn by *effect*, in
code, at runtime, never by a filename or a banned keyword.

Why this matters: a soft constraint that makes the AI timid ("don't write that
exploit", "don't name that tool") is 本末倒置 — it cripples the very capability the
operator needs, while doing nothing for safety. Safety is the hook's job, by
effect; capability is the driver's, without a method ceiling.

### Three pillars, deliberately NOT a playbook

The framework gives the AI exactly three things and refuses to be a fourth:

1. **Judgment discipline** — how to choose fronts, weigh evidence, resist false
   positives, and not stop early (`docs/cognition/`, `docs/WORKFLOW.md`).
2. **Grounding knowledge** — recognition signatures and weak-point anchors for
   real products, as *variant-analysis input*, never as turnkey payloads
   (`knowledge/`).
3. **A machine-enforced hard floor** — the deny boundary by effect
   (`.claude/hooks/`).

It is **not** a checklist / playbook / scanner-runner / JSON orchestrator. An
earlier orchestrator architecture was deliberately removed; `tools/check_rules.py`
exists to stop it from creeping back. The thesis: a capable model + discipline +
grounded recognition + a hard floor out-performs any fixed playbook, and a playbook
would only cap the model.

### One autonomous driver, author-and-handoff

A single AI reasons, chooses tools, exploits, verifies, and drafts the report.
It splits two things the operator cares about differently:

- **Author** — write complete, runnable exploitation code up to full impact and
  hand it to the operator. **No ceiling**; under-delivering exploitation code for
  an authorized target is a failure mode, symmetric to under-proving.
- **Auto-execute** — what the driver itself fires at the live target. This
  defaults to **proof-level (证明即止)**: demonstrate the vuln genuinely exists,
  then stop. Going deeper on the live target is operator-gated, normally delivered
  as code the operator runs under supervision.

### Evidence over confidence

A signal is not a conclusion; model confidence is not evidence; a single
observation is never confirmation. The run directory is the audit trail, and a
finding is reported only at the certainty its evidence supports (with a recorded
control / replication for anything ≥ 0.8). 证明即止 is operationalized as a
**harmless-verification recipe** (`docs/cognition/harmless-verification.md`): use
fake/non-production/single-shot/read-only inputs so an endpoint's *response* proves
the flaw exists without triggering its harm.

## Design Highlights（设计亮点）

What makes this more than "an AI with a prompt":

### 1. Effect × executor safety, enforced in code

A three-tier model — **autonomous (reversible/proof)** · **operator-gated
(irreversible-leaning but legitimate)** · **hard (never-justified, machine-
blocked)** — graded by *what gets touched* and *who executes*, not by technique.
The PreToolUse hook (`safety_gate.py`) enforces only the auto-execution hard
ceiling by effect; it never touches code the driver authors for the operator.

### 2. A guard layer that also protects *your own* access

All active tools route through `tools/harness/guard.py`: rate limiter (禁高频),
body cap (禁拖库), auth-fail counter (anti-runaway). Two additions close a failure
the field exposed — the driver **DoS-ing its own access** by over-probing:

- **HostHealth circuit breaker** — N consecutive transport failures on a host →
  auto-backoff (stop hammering a host that has started blocking you, and stop
  mis-reading it as "the whole site blocked my IP").
- **SessionBudget** — a global rolling-window request counter that warns when the
  whole engagement's volume is high. (The dual of "don't DoS the target": don't
  burn your own reachability.)

### 3. The anti-premature-closure system (the standout)

The most distinctive part. The field showed the deepest failure is not capability
— it is an eager model **closing too early**: lumping N hosts by header without
looking, calling "I couldn't reach it" → "it is safe", or scoring a wrong
conclusion at full confidence. **Self-review cannot fix self-review bias.** So:

- **Per-asset examination ledger** — `classify_hosts.py` fingerprints each host by
  *live content* (not Server header) into a structured `coverage.json`;
  `check_run.py` reads it on **every** run and lists the distinct-app candidates
  that must be investigated, so lumping is surfaced *when it happens*, not at the end.
- **Independent Reviewer, as a HARD gate** — before any "explored enough / no
  attack surface" claim, a **fresh-context sub-agent** audits the run with no
  investment in concluding (`docs/templates/independent-reviewer.md`).
  `check_run.py` **hard-fails** a closure claim with no `Independent Review` record.
  This turns review from self-administered (gameable) into independent (enforced) —
  the portable design is written up in `docs/review-mechanism.md`.
- **Ledger contradiction + certainty control** — a conclusion that another entry
  `Refutes:` but that still carries ≥ 0.8 is flagged (no polluting the ledger); any
  ≥ 0.8 entry must carry a `Control:` / `Replicated:` field.
- **Egress re-run queue** — assets that were merely unreachable (`reachable=false`
  in `coverage.json`) are a standardized queue; `rerun_deferred.py` re-probes them
  from any egress later. "Can't reach now" stays a live to-do, not a silent close.

### 4. Grounding knowledge, never a weapon

`knowledge/*.md` carry recognition signatures + weak-point anchors (weakness class
+ mechanism + CVE/CNVD reference + source), and explicitly **no payloads, steps, or
turnkey kits** — `check_knowledge.py` enforces the contract. The base is meant to
**grow with what you actually meet in the field** (a closure-time discipline adds
the entry for any newly fingerprinted stack).

### 5. A small, dependency-free, guard-routed tool pipeline

`ingest_recon` (fold a recon report → asset table + reachability matrix) →
`classify_hosts` (per-content classification → `coverage.json`) → `fetch_assets`
(fetch *all* SPA chunks + completeness assertion, so endpoint enumeration is
actually complete) → `probe` / `render` / `scan` (active verification sensors, all
guard-routed, UTF-8-safe) → `rerun_deferred` (egress queue). Pure standard library;
Playwright is the only optional dep (browser tools).

### 6. `check_rules` guards the architecture, not the weapons

Repository discipline checks that the abandoned orchestrator/playbook surfaces have
not crept back and the doctrine files exist — it deliberately does **not** police
exp/poc/scanner files (those are method, free; harm is gated by effect at runtime).
This keeps the framework from regressing into a playbook while leaving weaponization
unconstrained.

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

- `tools/check_rules.py`: architecture-drift guard — checks that the abandoned
  JSON-orchestrator/playbook surfaces (legacy dirs + refs) have not been
  reintroduced and that the doctrine files exist. It does not police weapons:
  exp/poc/scanner code is method (free); irreversible harm is gated by effect at
  runtime by the hook, not by filename.
- `tools/check_hook.py`: tests the local hook against blocked and allowed
  command examples.
- `tools/check_run.py`: run-state gate — required audit files/markers, plus the
  anti-premature-closure guards (closure HARD-fails without an Independent Review
  record; advisory warnings for un-examined assets, ledger contradictions, and
  ≥0.8 certainty without a control).
- `tools/check_knowledge.py`: keeps `knowledge/` grounding (no payload/exploit/step
  fields; every anchor carries a reference + source).

### Active-verification & engagement tools

All route through `tools/harness/guard.py` (rate limit, body cap, circuit breaker,
session budget) and emit UTF-8.

- `tools/ingest_recon.py`: fold a recon/OSINT report into a `surface.md`-ready
  asset table, entry points, and a reachability matrix.
- `tools/classify_hosts.py`: per-host classification by live content → structured
  `coverage.json` (the anti-lump examination ledger).
- `tools/fetch_assets.py`: fetch ALL JS a SPA references (incl. webpack chunks) and
  assert completeness before claiming endpoint enumeration is done.
- `tools/rerun_deferred.py`: re-probe egress-deferred (unreachable) assets later,
  from any egress.
- `tools/probe.py` · `tools/render.py` · `tools/scan.py`: active verification
  sensors (HTTP prober / headless browser / scanner-as-sensor wrapper).

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
