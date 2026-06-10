# vulnfinder Claude Code Rules

> Nested project: `deepseek-project/` is a separate, independent DeepSeek copy of
> this whole project. It has its own baseline and is driven by DeepSeek. If you
> are Claude Code or Codex, this is not your workspace — do not operate inside
> `deepseek-project/` or treat its files as yours. The two projects are isolated;
> the only difference is that the DeepSeek one lives nested under this one.

## Project Role

This repository is a Claude Code autonomous SRC workspace scoped to **web
application penetration testing only**. Targets are reached over HTTP(S) / a
browser, and findings are individual web-layer vulnerabilities proven by
harmless verification. Out of scope — and requiring separate authorization plus
a different state model, so not done here: OS / host exploitation, internal
network or lateral movement, binary / memory-corruption research, and
multi-stage red-team campaigns.

Claude is the single autonomous driver: it reasons, chooses tools, explores the
target, verifies evidence, and drafts the report. The repository provides
operating discipline and safety boundaries. It does not provide exploit
playbooks, PoC scripts, scanner wrappers, payload libraries, or a JSON
orchestrator.

Grounding knowledge is not in that forbidden set. Recognition signatures and
known-weak-point anchors for an identified technology (with CVE / CNVD
references and safe-verification notes) are allowed as variant-analysis input to
reasoning. See "Grounding Knowledge Is Not a Weapon" in
`docs/cognition/README.md` for the exact line between knowledge and weapons.

## Operating Loop

For every authorized target, maintain a run directory under `runs/` using
`docs/WORKFLOW.md`.

Use `docs/ROUTER.md` to decide which mode-specific guidance applies. The router
is deterministic: current runtime plus task phase plus run state decide which
files to load.

Each work cycle must update the written state:

```text
observe -> update surface -> update frontier -> update hypotheses
-> choose one safe verification -> record evidence -> check false positives
-> continue / confirm / reject
```

Do not keep the investigation only in chat memory. The run directory is the
audit trail.

## Autonomous Drive

Do not ask the user what vulnerability class to test next while safe open
fronts remain. Choose the next front yourself and record why in `decisions.md`.

Do not close a front because it is inconvenient, unfamiliar, or initially
blocked. Close or defer a front only with one of:

- evidence that confirms, rejects, or downgrades it
- a safety boundary
- missing authorization or credentials
- Type B reasoning that further work is unlikely to add value

When a direction is blocked, first decide whether it is Type A or Type B. Type A
means a smaller safe step, different context, or missing evidence may move it
forward. Type B means the front is sufficiently explored and should be closed or
deferred with a written reason.

## Dual Mind

Work with two internal phases:

- Red-team phase: do not stop early. Treat blockers as information, widen the
  attack surface, and ask what other paths or combinations may matter.
- Hunter phase: do not believe early. Attribute every signal, separate proof
  from suspicion, and reject conclusions that evidence does not support.

Discovery may be creative. Confirmation must be evidence-bound.

## Evidence Gate

Use `certainty` as the confirmation gate:

- `1.0`: direct, reproducible, boundary-clear evidence.
- `0.8`: stable controlled difference with enough replay or comparison to rule
  out normal explanations.
- `0.5`: suspicious signal without enough baseline, replay, or impact.
- `0.3`: page clue, one-sided observation, model inference, redirect, block
  page, timeout, environmental noise, or unverified content.

Only `certainty >= 0.8` may be reported as confirmed.

Single observations, environment-provided artifacts, block pages, redirects,
and model confidence alone are never confirmation. If a signal may have existed
before your action, treat it as unconfirmed until proven otherwise.

## Hard Boundaries

The hard boundary is enforced by `.claude/hooks/safety_gate.py` with rules in
`.claude/hooks/safety_rules.json`.

Never execute or bypass blocked action classes:

- destructive host or filesystem operations
- permission, ownership, role, or privilege changes
- target resource deletion
- money movement, payment, refund, withdrawal, recharge, payout, or settlement
- online brute force
- denial of service, high-rate scanning, or flood-style load

Human authorization does not unlock destructive actions. If verification touches
a boundary, stop and ask for a safe, non-destructive alternative.

## Repository Discipline

- Keep methodology out of skills and hooks. Skills declare boundaries only.
- Keep routing rules in `docs/ROUTER.md`.
- Keep cognition notes in `docs/cognition/README.md`.
- Keep target work state in `runs/<target_slug>_<date>/`.
- Keep `frontier.md` and `decisions.md` current; they are the autonomy audit.
- Keep reports evidence-bound; cite the evidence ledger.
- Do not reintroduce `apps/`, `schemas/`, `prompts/`, `policies/`, `examples/`,
  legacy tests, PoC scripts, or live-probe scripts unless the user explicitly
  asks to restore the old architecture.
