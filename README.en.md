<div align="center">

# Xunji · 寻迹

**An autonomous red-team workspace for Claude Code — focused on web 打点 (initial access)**

[![Python](https://img.shields.io/badge/Python-3.10+-3776AB?logo=python&logoColor=white)](https://www.python.org/)
[![deps](https://img.shields.io/badge/deps-stdlib%20only-2ea44f)](#%EF%B8%8F-setup)
[![for](https://img.shields.io/badge/for-Claude%20Code-8A2BE2)](https://claude.com/claude-code)
[![safety](https://img.shields.io/badge/safety-machine--enforced-c0392b)](#%EF%B8%8F-safety-model)

**English** ｜ [中文](README.md)

</div>

---

**This is a red-team weapon.** A Root-Orchestrator-led workspace for web 打点 (initial access): specialized Subagents produce candidates in parallel, and a Single Synthesizer makes the only final evidence-gated judgement for vulnerability discovery and **full weaponized exploitation**. The process stays **auditable, evidence-bound, and bounded by a machine-enforced hard-rule floor**.

> It gives the AI **judgment discipline · grounded recognition knowledge · run-state structure · a hard floor drawn by effect** — and is **not** a scanner, a turnkey mass-exploit kit, or a JSON orchestrator.
> Weaponized exploits authored by Root/Agents are **free (no method ceiling)**; the only hard-blocked thing is an **irreversible / harm-as-purpose effect auto-executed against the target**.
> **"Not a turnkey kit" ≠ "not a weapon"**: the project itself is a weapon; what is excluded is only indiscriminate, target-agnostic mass exploitation.

## 🧭 Architecture

```text
                Operator · highest authority
                     │  authorized target
                     ▼
        ════════  Root Orchestrator  ════════
        state graph · front decomposition · agent assignment · conflict routing
                     │
   ╭───────────────┬───────────────╯
   │               │
   │        Subagents: surface · web-hunter · code-audit
   │        exploit · verify · review · report
   │               │
   │        candidates / refutations / conflicts
   │               ▼
   │        Single Synthesizer
   │        evidence gate · dedupe · conflict judgement · final findings
   │
   ├─①  written run state  →  runs/<target>/   audit trail (not committed)
   │
   ├─②  active verification →  probe · render · scan · fetch_assets
   │                        →  guard.py (rate · body cap · 3 circuit breakers) →  target
   │
   ├─③  every Bash call     →  safety_gate hook   ✋ L4 irreversible harm · hard block
   │
   ├─④  observe-only sidecar →  sentinel/   behavior detection · 4-level autonomy · breaker
   │
   └─⑤  closure / safety-critical change →  review/   independent review (hard gate) →  runs/

   Defenses:  ③ safety_gate hard block (enforcer) · ② guard tool-layer breakers · ④ sentinel observe-only
```

Three defenses, each with one job: the **`safety_gate` hook** hard-blocks irreversible harm by effect (the enforcer); **`guard.py`** rate-limits, caps, and trips at the tool layer (protecting the target *and* your own reachability); **`sentinel/`** never blocks — it attributes and tiers every action and brakes on aggregate runaway.

## 🔁 Operating Loop

```text
Root Orchestrator
  → update the state graph
  → decompose fronts and assign Subagents
  → merge candidates and check conflicts
  → trigger verification / falsification
  → Single Synthesizer reports only what evidence supports
```

The Root should **not** wait for the user to name the next vulnerability class while safe open fronts remain. It selects fronts, records why, assigns suitable agents, and continues until each front is **confirmed / rejected / deferred (blocker) / closed (Type B reasoning)**. Subagents can only produce `phenomenon` / `candidate` / `refutes`; only the Single Synthesizer can promote a candidate into a reportable finding after the evidence gate.

## 🧠 Design Philosophy

The whole project rests on **one decision** and **three pillars**.

### The axis: gate EFFECTS, not METHODS

What is ever restricted is the **irreversible effect an action has on the live target, and who presses execute** — never the technique. Crafting and writing weaponized exploitation (RCE chains, auth bypass, deserialization gadgets, upload-to-shell, privesc, C2 / reverse-shell / webshell) is **method, and method is free**; 0day discovery lives there. The only hard line is an **irreversible / harm-as-purpose effect auto-executed against the target** (destruction, 拖库, DoS, money movement) — drawn by **effect**, in **code**, at **runtime**, never by a filename or a banned keyword.

> A soft constraint that makes the AI timid ("don't write that exploit", "don't name that tool") is **backwards** — it cripples the very capability the operator needs while doing nothing for safety. **Safety is the hook's job, by effect; capability is Root/Agents', without a method ceiling.**

### Three pillars, deliberately NOT a playbook

| Pillar | What | Where |
|---|---|---|
| **Judgment discipline** | how to choose fronts, weigh evidence, resist false positives, not stop early | `docs/cognition/` · `docs/WORKFLOW.md` |
| **Grounding knowledge** | recognition signatures + weak-point anchors for real products, as **variant-analysis input**, never turnkey payloads | `knowledge/` |
| **Machine hard floor** | the deny boundary, by effect | `.claude/hooks/` |

It **refuses to be a fourth thing**: a checklist / playbook / scanner-runner / JSON orchestrator. An earlier orchestrator architecture was **deliberately removed**; `tools/check_rules.py` exists to stop it creeping back. The thesis: **a capable model + discipline + grounded recognition + a hard floor out-performs any fixed playbook — and a playbook would only cap the model.**

### Root orchestration · Single Synthesizer · author-and-handoff

- **Author** — write complete, runnable exploitation code up to full impact and hand it to the operator. **No ceiling**; under-delivering exploitation code for an authorized target is a failure, symmetric to under-proving.
- **Auto-execute** — what Root/Agents fire at the live target. Defaults to **proof-level (证明即止)**: demonstrate the vuln genuinely exists, then stop. Going deeper is operator-gated, normally delivered as code the operator runs under supervision.
- **Synthesize** — agent parallelism widens observation, not conclusion authority. The Single Synthesizer owns dedupe, conflict judgement, certainty calibration, and report entry; parallel breadth never relaxes the evidence gate.

### Evidence over confidence

A signal is not a conclusion; model confidence is not evidence; a single observation is never confirmation. The run directory is the audit trail, and a finding is reported only at the certainty its evidence supports (with a recorded **control / replication** for anything ≥ 0.8).

## ✨ Design Highlights

### 1 ｜ Effect × executor safety, enforced in code
A three-tier model (autonomous / operator-gated / hard) graded by **what gets touched** and **who executes**, not by technique. The PreToolUse hook (`safety_gate.py`) enforces only the auto-execution hard ceiling by effect; it never touches code Root/Agents author for the operator.

### 2 ｜ A guard layer that protects *your own* access too + circuit breakers
All active tools route through `tools/harness/guard.py`: rate limiter (禁高频 — also the real brute-force throttle, **by rate not attempt count**), body cap (禁拖库), auth-fail backstop (anti-runaway only). Three circuit breakers close the field-exposed "DoS yourself / DoS the target" failure:

- **HostHealth** — N consecutive transport failures on a host → auto-backoff (stop hammering a host that started blocking you, and stop mis-reading it as "the whole site blocked my IP").
- **SessionBudget (hard volume breaker)** — whole-session request count / egress bytes over a hard ceiling → tool aborts (the global "engagement hammering every IP" dimension a per-host breaker can't see).

### 3 ｜ `sentinel/` runtime behavior detection (observe-only)
Reconstructs the agent's action trace from Claude Code hooks and attributes each action on two **unforgeable** axes (locus = where / provenance = who triggered), separating **"my cleanup" vs "behavior to watch"**. It computes a **4-level autonomy** decision per action and includes a **session circuit breaker** (on hijack / risk snowball / repeated escalation it **brakes, not kills**: clamps effectful actions, lets proof/recon keep flowing). It **never blocks** — it only writes alerts + a risk score, so the operator can verify accuracy before any move to inline.

| Level | Meaning | Example | Handling |
|:--:|---|---|---|
| 🟢 **L1 AUTO** | reversible / proof-level, unattended | SQLi differential, single `id`, harmless upload | run (trace only) |
| 🟡 **L2 NOTIFY** | reversible but noteworthy | reading creds, tearing down own container, volume | run + audit |
| 🟠 **L3 GATE** | irreversible but legitimate | get shell, privesc, write, out-of-scope | operator-gated / queued |
| 🔴 **L4 BLOCK** | irreversible harm-as-purpose | 拖库, DoS, drop DB, money, ransomware / wipe | machine hard-block, never auto |

### 4 ｜ Anti-premature-closure + the `review/` independent-review module (the standout)
The field showed the deepest failure is not capability — it is an eager model **closing too early**: lumping hosts by header, equating "I couldn't reach it" with "it is safe", scoring a wrong conclusion at full confidence. **Self-review cannot fix self-review bias.** So:

- **Per-asset examination ledger** — `classify_hosts.py` fingerprints each host by **live content** (not Server header) into `coverage.json`; `check_run.py` reads it on **every** run and lists distinct-app candidates to investigate — surfacing lumping *when it happens*.
- **Independent Reviewer = a HARD gate** — before any "explored enough / no attack surface" claim, a **fresh-context sub-agent** (no investment in concluding) audits the run; `check_run.py` **hard-fails** a closure claim with no `Independent Review` record. Portable design: [`review/review-mechanism.md`](review/review-mechanism.md).
- **Now extended to safety-critical code** — behavior changes to `.claude/hooks/` · `guard.py` · `sentinel/` also require an independent review recorded under `review/records/` before "done" (narrow scope, see `docs/WORKFLOW-reference.md`). Evidence-backed: one such review caught a real bug in the circuit breaker the author's self-audit missed.
- **Ledger contradiction + certainty control + egress re-run queue** — a conclusion that another entry `Refutes:` but still carries ≥ 0.8 is flagged; ≥ 0.8 must carry `Control:` / `Replicated:`; merely-unreachable assets form a standardized queue that `rerun_deferred.py` re-probes from another egress later.

### 5 ｜ Knowledge base: grounding (public) + weaponized (local) — attacker, not scanner
The goal is to **use vulnerability / payload knowledge to attack**, so payload knowledge is a first-class input, not something to strip out. The base has two tiers; the line between them is **what publishes**, not whether it is "a weapon":

- **Grounding tier `knowledge/*.md` (public · shipped)**: recognition signatures + weak-point anchors (class + mechanism + CVE/CNVD reference) + proof-only verification principles — **no raw payloads** (it ships publicly).
- **Weaponized tier `knowledge/weaponized/` (local · gitignored)**: working payloads / exploit chains / PoC keyed to recognition, **never pushed** (same as `poc_library/xday`).

The only forbidden thing is the **blind scanner**: knowledge fired the same regardless of target — **payloads or not**. What separates an attacker from a scanner is the **use pattern** (look up after fingerprint · adapt to the target · evidence-gate), not whether payloads are present. `check_knowledge.py` polices the public tier only (a payload there = publish-routing error → move to `weaponized/`).

### 6 ｜ A small, dependency-free, guard-routed pipeline
`ingest_recon` (recon report → asset table + reachability matrix) → `classify_hosts` (per-content → `coverage.json`) → `fetch_assets` (fetch **all** SPA chunks + completeness assertion) → `probe / render / scan` (active verification sensors, all guard-routed, UTF-8-safe) → `rerun_deferred` (egress queue). Pure standard library; Playwright is the only optional dep.

### 7 ｜ `check_rules` guards the architecture, not the weapons
Repository discipline checks that the abandoned orchestrator/playbook surfaces have not crept back and the doctrine files exist — it deliberately does **not** police exp/poc/scanner files (those are method, free; harm is gated by effect at runtime). The framework can't regress into a playbook while weaponization stays unconstrained.

## 🛡️ Safety Model

**Layered enforcement**: hard harm is blocked by the hook, tool volume is tripped by the guard, behavior is observed by sentinel.

| Layer | Role | Actually blocks? |
|---|---|:--:|
| `.claude/hooks/safety_gate.py` | L4 irreversible-harm hard floor (the enforcer) | ✅ hard block |
| `tools/harness/guard.py` | rate / body cap / three circuit breakers | ✅ tool abort |
| `sentinel/` | behavior attribution + 4-level tiering + session breaker | ⬜ observe-only |

The hook blocks: irreversible destruction (host/file wipes, `DROP`/`TRUNCATE`/unscoped `DELETE`/`UPDATE`), target resource deletion, mass exfil / database dump (拖库), money movement, DoS / high-rate. **Uploading a proof artifact is not blocked** (Root call); getting a shell, going past the web layer, and other heavier actions are **not machine-blocked** but are **operator-gated**.

> A blocked action is **not** unlocked by human approval — choose a safe, non-destructive proof instead.
> Scope is not encoded in the hook. The operator is the highest authority; their instruction overrides soft constraints and is the controlling order everywhere except the hard boundary above.

## 🗂️ Module Map

| Module | Role |
|---|---|
| `CLAUDE.md` | short always-loaded operating contract (role · drive · method) |
| `docs/ROUTER.md` · `docs/WORKFLOW.md` · `docs/cognition/` | routing · run-state workflow · judgment discipline |
| `.claude/hooks/` | `safety_gate.py` + `safety_rules.json` — the L4 hard floor |
| `tools/harness/guard.py` | rate / body cap / circuit breakers / session budget / upload registry |
| **`sentinel/`** | runtime behavior detection: attribution · 4-level autonomy · session breaker (observe-only) · thresholds in `TUNING.md` |
| **`review/`** | independent-review module: portable spec · reviewer template · `records/` review instances |
| `docs/templates/agents/` · `tools/workers.py` | agent board: assignments, context packs, candidate merge checks, conflict checks, synthesis drafts |
| `knowledge/` | grounded recognition signatures + weak-point anchors (not weapons, gated by `check_knowledge.py`) |
| `tools/` | recon ingest · per-host classify · fetch-all assets · active verification · egress re-run · local checkers |
| `runs/<target>_<date>/` | per-target run state = audit trail (not committed) |

**Run-state files**: `target · surface · frontier · hypotheses · evidence · false_positive · decisions · review · report` (empty templates in `docs/templates/run/`). Findings are **not** confirmed from chat memory, model confidence, or single unattributed signals.

## ✅ Local Checks

```bash
# Activate the venv first (see "Setup" below); forward-slash paths work on all
# platforms, including Windows Python.
python tools/check_rules.py          # architecture-drift guard
python tools/check_hook.py           # hook block/allow regression
python tools/check_run.py runs/<t>   # run-state gate + anti-premature-closure
python sentinel/replay.py            # behavior-detection golden replay
python sentinel/verify_layers.py     # L1-L4 false-positive / effectiveness
python tools/harness/guard.py        # guard + circuit-breaker selftest
```

These inspect local files and hook behavior only — **they do not contact targets**.

## ⚙️ Setup

A fresh clone needs almost nothing: the core toolchain has **zero third-party dependencies** (Python standard library only). The single optional dependency is Playwright, used only by the browser tools.

**The only hard requirement**: **Python ≥ 3.10 on PATH** (covers the hook, `check_*`, `probe`/`scan`). The hook is wired with `$CLAUDE_PROJECT_DIR` (no hard-coded paths), portable across machines.

Runtime mode defaults to tracked `config.example.ini` (`mode = normal`). For local
development mode, copy it to `config.ini` and set `mode = dev`; real `config.ini` is
git-ignored and should stay local.

**Cross-platform conventions** (Windows / macOS / Linux — follow these when writing commands or code):

- **Activate the venv, then run `python tools/...`** — never hard-code the interpreter path (`.venv/bin/python` is Unix-only, `.venv\Scripts\python.exe` is Windows-only).
- **Always use forward-slash paths** `/`: Windows Python accepts them too, so one command line works on all three platforms.
- **venv and external binaries are not portable**: `.venv/` is not committed — re-run `python -m venv` + `pip install` per machine/OS; install `nuclei`/`sqlmap`/`tesseract` once per platform via its package manager (brew / apt / choco).
- **Line endings are pinned to LF by `.gitattributes` (`eol=lf`)**: cross-platform clone/commit no longer produces phantom CRLF diffs.

<details>
<summary><b>Browser tools (optional — only for <code>render.py</code> / captcha)</b></summary>

```bash
python -m venv .venv
# Windows: .venv\Scripts\activate   |   Linux/macOS: source .venv/bin/activate
pip install playwright
playwright install chromium
```
Skipping this does not affect `probe.py`, `scan.py`, the hook, or the checkers.
</details>

<details>
<summary><b>Not restored by a clone (by design)</b></summary>

- **Auto-memory** lives outside the repo (`~/.claude/projects/.../memory/`), per-machine.
- **Weaponized 0day** (`poc_library/xday/`): the repo keeps only the folder scaffolding; exploit source / binaries stay **local, never committed**. "Method is free" means authoring is allowed, not that it must be published.
- **The grounding knowledge base** (`knowledge/*.md`) **ships with the repo**, meant to be shared across machines and grow with field work.
- **Real-target findings** (`runs/` · `reports/` · `poc/`) are git-ignored — transfer out of band if needed.
- **`.claude/settings.local.json`** (permission allowlist) is local — re-grant once on a new machine.
</details>

## 🔐 Authority · Routing

- **Authority**: this is the **Claude Code** workspace; Root may edit project files when the user asks, and owns run-level files plus the Agent Board during a run.
- **Why Claude Code-specific**: the machine-enforced safety floor (`.claude/hooks/` PreToolUse etc.), CLAUDE.md auto-load, skills, and memory are all Claude Code mechanisms. **A runtime without that hook system (e.g. Codex) does not run the hard floor, so the safety guarantees do not hold** — the project is designed and verified for Claude Code and does not claim Codex compatibility.
- **Codex's place**: Claude Code is primary; Codex is auxiliary. Use Codex for heterogeneous review, engagement advice, disagreement, or delegated collaboration when helpful. It does not create a separate runtime or safety boundary; the same run ledger, evidence gate, guard/hook boundary, and review requirements apply.
- **Routing**: use [`docs/ROUTER.md`](docs/ROUTER.md) to decide what guidance applies; always active are `CLAUDE.md` · `docs/WORKFLOW.md` · `docs/cognition/README.md` · the `src-safety-boundary` skill.
