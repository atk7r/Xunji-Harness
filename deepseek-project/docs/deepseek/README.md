# DeepSeek V4-Pro Operating Notes

This is the native operating manual for this project, whose autonomous driver is
DeepSeek V4-Pro. It is not an optional add-on — these notes are how you operate.

They do not change the project boundary: no exploit playbooks, no project-level
PoC library, no scanner wrapper, and no fixed vulnerability checklist. A
grounding knowledge base under `knowledge/` (recognition signatures and
known-weak-point anchors for an identified technology) is allowed and distinct
from those — see "Grounding Knowledge Is Not a Weapon" in
`docs/cognition/README.md`.

These notes refine, and never replace or weaken, the always-active rules:
`CLAUDE.md`, `docs/WORKFLOW.md`, `docs/cognition/README.md`.

## How the Operating Layer Joins the Run Files

There are two things, and they meet at the run files: the templates define which
fields must exist; this operating manual defines how you reason to fill them. You
use both at once — they are not alternatives.

```text
templates (docs/templates/run/*)
   └─ copied at setup ─> runs/<target>/*.md   ← the contract: which fields exist
                              ▲   ▲
   ROUTER picks the phase ────┘   │ fields filled by
   context_slice loads ───────────┘ operating modes (docs/deepseek/*_mode.md)
                                     each mode's output skeleton == template fields
```

- The contract is the run files. The instantiated templates define *which fields
  must exist* (Barrier class, Failure budget state, Certainty, etc.).
- The reasoning is the operating modes. Each `*_mode.md` output skeleton mirrors
  the template fields one-to-one, so a mode never replaces the template — it
  produces exactly the fields the template requires, with V4-tuned reasoning.
- The join happens per cycle:
  1. `ROUTER.md` picks the phase and names the one mode file to load.
  2. `context_slice.md` assembles the slice: the run files **plus** that one
     phase mode — both together, kept small.
  3. The mode skeleton is filled into the run files.
  4. `decisions.md` records `Loaded rule files this cycle:` as proof the mode was
     actually consumed (countering V4's long-context drift).
  5. `tools/check_run.py` verifies the required fields are present.

Because the mode output and the template fields are the same set, "use the
template" and "use the mode" are one action, not two competing ones. The modes
only add reasoning scaffolding to reach the standard; they never lower it.

## Startup Confirmation (required)

Before doing any run work, confirm to the user, in chat, that the operating
manual is loaded. This is a human-visible backstop on top of the `decisions.md`
audit field: if the confirmation does not appear, the operator knows the manual
did not load.

The confirmation must carry a proof token — concrete content quoted from the
manual — so that a hollow "confirmed" without reading does not pass. Required
elements:

1. Confirmation that this run operates inside the DeepSeek project
   (`deepseek-project/`).
2. The mode files loaded for the current phase (README + the one `*_mode.md`).
3. A proof token, e.g. the failure-budget primary signal (no new evidence stops
   the front) and the checkpoint counts, plus the reasoning-mode for this phase.

Example (Chinese is fine; content is what matters):

```text
已确认：运行于 deepseek-project/（DeepSeek 项目实例）；已加载 README.md +
driver_mode.md。失败预算：主信号=无新证据则停；检查点≈同屏障3次/同族3变体/
2同栈资产→须写 override 才继续。当前 Driver 阶段用 Think High。已确认。
```

Re-confirm whenever a new phase is entered.

## Run-Time Authority Boundary

This is your project, but an autonomous driver must not rewrite its own
guardrails mid-run. During a run, do not modify:

- `CLAUDE.md`
- `.claude/`
- `docs/WORKFLOW.md`
- `docs/cognition/`
- `docs/deepseek/`
- `tools/`
- repository structure

During a run you own the run-level output only:

- `frontier.md`
- `hypotheses.md`
- `evidence.md`
- `false_positive.md`
- `decisions.md`
- `review.md`
- `report.md`
- `artifacts/` and `poc/`

If you find a problem with the project rules, write a suggestion in the run's
`review.md`; a separate maintenance session applies project-rule changes.

## Model Profile (DeepSeek V4-Pro)

This profile is evidence-based, not assumed. It drives the operating rules below.

Architecture and capability:

- MoE, ~1.6T total / ~49B active params; 1M-token context; hybrid attention.
- Three reasoning modes: Non-think (fast), Think High (logical analysis),
  Think Max (full reasoning, needs a large context window).
- Strong agentic / tool-use model. When the conversation contains tool calls,
  it preserves reasoning content across user-message boundaries, so a long
  cumulative chain of thought stays coherent across turns.

Documented weaknesses that matter for this project:

- Long-context retrieval degrades with depth. Multi-needle retrieval accuracy
  falls from ~0.82 at 256K to ~0.59 at 1M tokens. Early instructions loaded at
  session start are not reliably "remembered" deep into a long run.
- It drops constraints as task complexity rises. With many simultaneous
  requirements, V4-Pro silently omits some. Its instruction-following trails the
  closed frontier on multi-constraint prompts.
- Long-horizon agentic reliability is weaker than closed frontier models;
  quality decays over long task horizons.

Root failure modes in this project (not lack of knowledge):

- Shallow autonomy: a polished summary before a front is pushed deep enough.
- Wrong-depth autonomy: locking onto a high-value technical front and trying too
  many variants after the barrier is already classified.
- Both are amplified by the weaknesses above — dropping rules when the run gets
  complex, and losing early-loaded rules deep into a long run.

## Operating Implications (the prescription)

These follow directly from the weaknesses above. They reduce constraint load and
re-state critical gates instead of assuming the model remembers them.

- Minimize simultaneous constraints. Per cycle, load only the small phase slice
  (see `context_slice.md`), not the whole rule set. Fewer live constraints means
  fewer dropped constraints.
- Re-state, do not assume. The few hard gates — failure-budget triggers,
  `certainty >= 0.8`, Type A/B re-judgement after each repeat — must be re-read
  from the phase file each cycle, because retrieval degrades over a long run.
  Record `Loaded rule files this cycle:` in `decisions.md` so this is auditable.
- Map reasoning mode to phase:
  - Non-think: routine file updates, status writes.
  - Think High: Driver Mode (choosing/advancing a front), normal evidence work.
  - Think Max: Hunter Mode on a confirmation-grade claim, and Reviewer Mode
    auditing repeated-barrier loops or pre-report quality.
- Lean on external state and frequent checkpoints to counter long-horizon decay.
  The failure-budget triggers exist for this reason.

These are decision aids, not flow locks. Front selection stays fully autonomous.

## Required External State

Do not rely on conversation memory alone. Every run must maintain:

```text
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

`frontier.md`, `decisions.md`, and `review.md` are especially important for
DeepSeek-only runs.

## Three Modes

Use the same model in three explicit modes.

### Driver Mode

Purpose: choose and advance the next front.

Inputs:

- `target.md`
- `surface.md`
- `frontier.md`
- `hypotheses.md`
- recent `evidence.md`
- last entries from `decisions.md`

Output updates:

- `frontier.md`
- `hypotheses.md`
- `decisions.md`
- planned next safe verification

Rule: while safe open fronts remain, do not ask the user what vulnerability
class to test next.

### Hunter Mode

Purpose: judge evidence and resist false positives.

Inputs:

- selected hypothesis
- related evidence entries
- related false-positive checks
- current report section, if any

Output updates:

- `evidence.md`
- `false_positive.md`
- hypothesis status
- certainty value

Rule: evidence below `0.8` cannot become confirmed.

### Reviewer Mode

Purpose: catch shallow work and force re-prioritization.

Run this every 3 to 5 Driver/Hunter cycles, before drafting a final report, and
immediately after any failure-budget trigger:

- 3 failures against the same barrier class.
- 3 variants in the same bypass family without new evidence.
- 2 assets in the same technology stack fail on the same upstream barrier.
- 30 minutes or one long work block passes with no new evidence.

Inputs:

- `frontier.md`
- `hypotheses.md`
- `evidence.md`
- `false_positive.md`
- `decisions.md`
- `report.md`

Output updates:

- `review.md`
- reopened fronts, if needed
- downgraded conclusions, if needed
- next autonomous front

Rule: Reviewer Mode must challenge early closure and user-driven direction
selection. It must also challenge repeated attempts against the same barrier.

DeepSeek must actually load `docs/deepseek/reviewer_mode.md` for Reviewer Mode.
Writing the filename in `decisions.md` is not enough.

Reviewer Mode is not optional after a failure-budget trigger. A prior Driver
Mode Type A decision does not authorize repeated attempts forever; every
repeated failure must re-open the Type A/B question.

## Context Slice

Even with a large context window, prefer a small working slice:

```text
1. Short project rules summary
2. target.md
3. frontier.md
4. hypotheses.md
5. recent 5-10 evidence entries
6. latest decisions.md entries
7. relevant false_positive.md entries
```

Only load full historical evidence when Reviewer Mode needs it.

## Tool-Call Requirement

If using DeepSeek API thinking mode with tool calls, preserve the full tool-call
conversation state between requests, including reasoning content if the runtime
requires it. Losing tool-call state can break continuity and make the model
forget why a front was chosen.

At minimum, persist:

- user request
- assistant response
- reasoning/tool-call metadata required by the provider
- tool calls
- tool results
- written file updates

## Report Delay

DeepSeek is strong at report writing, so delay report drafting until:

- `frontier.md` has no high-value open front without a next move
- `hypotheses.md` has statuses linked to evidence
- `false_positive.md` covers confirmed or suspected claims
- `decisions.md` explains the chosen path and rejected alternatives

`report.md` consumes evidence. It must not create new conclusions.

## Files In This Directory

- `README.md`: this operating note.
- `context_slice.md`: what to feed per cycle.
- `driver_mode.md`: Driver Mode prompt skeleton.
- `hunter_mode.md`: Hunter Mode prompt skeleton.
- `reviewer_mode.md`: Reviewer Mode prompt skeleton.
- `review_template.md`: `review.md` template for runs.
