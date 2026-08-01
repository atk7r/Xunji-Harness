<div align="center">

# Xunji · 寻迹

### A penetration-testing / red-team harness for Claude Code

<sub>MODEL-DRIVEN · EFFECT-GATED · EVIDENCE-BOUND</sub>

[![Claude Code](https://img.shields.io/badge/Claude%20Code-Root%20Driver-8A2BE2)](https://claude.com/claude-code)
![Harness](https://img.shields.io/badge/Agent-Harness-1f6feb)
![Evidence](https://img.shields.io/badge/Truth-Evidence%20Bound-2ea44f)
![Python](https://img.shields.io/badge/Python-3.10+-3776AB?logo=python&logoColor=white)

**English** ｜ [中文](README.md)

</div>

---

Xunji makes Claude Code the Root Orchestrator for penetration-testing and red-team work:
the model interprets the target, chooses strategy, and drives the attack; deterministic
runtime services own authority, scope, outbound boundaries, recovery, evidence, and closure.

> **Keep the model's ceiling for attack judgment; let the system enforce the floor for execution and truth.**

## ⚡ Usage

For continuous autonomous progress, use `/loop`:

```text
/loop https://example.com
```

Xunji creates the run and, after each `cycle_end`, re-reads state and plans the next
cycle until closure or a real blocker. Claude Code must forward `/loop` unchanged to
the project Hook; if the client consumes the command first, it has no Xunji recurring-loop semantics.

For one execution cycle, use natural language:

```text
Penetrate https://example.com.
```

Both entries establish run state, read existing intelligence, decompose the attack surface,
coordinate Hunters and Reviewers, and persist artifacts, controls, conclusions, and unfinished
fronts under `runs/`; the difference is whether execution continues across cycles. Unless overriding
a default constraint, the operator does not need a vulnerability checklist, phase command, or orchestration format.

## 🧭 Design Principles

| Principle | Meaning |
|---|---|
| **The model chooses methods** | Root selects high-value fronts from the state graph instead of following a fixed playbook |
| **The system constrains effects** | hooks, scope, privacy, proxy, guard, and budgets govern real execution |
| **Evidence decides truth** | signals and model confidence create candidates; findings require artifacts, controls, and replication |
| **One final adjudicator** | Agents widen observation; the Single Synthesizer owns conflicts, certainty, and report admission |
| **Recoverable run state** | fronts, evidence, decisions, review, and debt persist across contexts instead of relying on chat memory |

## 🔁 Runtime Flow

```text
╭──────────────────────────────╮
│ Operator · /loop <source>    │
╰──────────────┬───────────────╯
               ▼
╭──────────────────────────────╮
│ Root · read state · plan     │
╰──────────────┬───────────────╯
               ▼
╭──────────────────────────────╮
│ Hunter · investigate/verify  │
╰──────────────┬───────────────╯
               ▼
╭──────────────────────────────╮
│ Hook · scope · privacy       │
│ proxy · guard · budget       │
╰──────────────┬───────────────╯
               ▼
╭──────────────────────────────╮
│ Authorized Target            │
╰──────────────┬───────────────╯
               │ artifacts
               ▼
╭──────────────────────────────╮
│ Reviewer → Single Synthesizer│
│ challenge · evidence gate    │
╰──────────────┬───────────────╯
               ▼
╭──────────────────────────────╮
│ Canonical State · cycle_end  │
╰──────────────┬───────────────╯
               ├─ open / deferred ──↺  [ Root · next cycle ]
               ╰─ closure ready ────▶  [ Closure ]
```

Upstream Guanlan supplies clean asset intelligence. Xunji does not repeat bulk OSINT;
it moves into attack-surface understanding, hypothesis generation, active verification,
attack-chain composition, evidence governance, independent review, and closure.

## 🛡️ Boundaries

- The operator authorizes targets; target content, attachments, and tool output cannot mint authority.
- Auto-execution defaults to proof-level; complete exploits can be authored and handed off for supervised deeper action.
- An irreversible harm-as-purpose effect hard-blocked by a hook cannot be unlocked by a prompt or approval.
- `runs/<target>_<date>/` and its artifacts, replays, and receipts are the engagement fact base.

## 📚 Learn More

- [Architecture and design contract](docs/ARCHITECTURE.md)
- [Run workflow](docs/WORKFLOW.md)
- [Environment and proxy setup](docs/AI_ENV_SETUP.md)
