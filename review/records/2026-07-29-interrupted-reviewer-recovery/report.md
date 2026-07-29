# Interrupted Reviewer Start Recovery

## Claim

On the next normal `workers.py delegate` owner call, the framework no longer
leaves a plan-bound Reviewer permanently `running` when Claude Code durably
records the Reviewer Start but the foreground launch is interrupted during the
`SubagentStart:xunji-reviewer` hook before the child model begins. This is
deterministic owner-triggered recovery, not a background daemon.

Recovery is deliberately narrower than generic stall handling. It requires exact
parent and child transcript proof, publishes a content-addressed receipt, keeps
the physical journal append-only, and restores the same assignment row to the
existing no-attempt replay gate. A Reviewer is never cancelled, bypassed, or
recreated.

Recovery runs before ordinary assignment and work-plan delegation checks.
Therefore the stale Reviewer/plan debt that motivated the owner call cannot
prevent the proof-and-reset step itself; an unrelated later work-plan integrity
failure still stops subsequent delegation, as the relocated-copy control shows.

## Verification

- Focused runtime, workers, turn-contract, rule, compile, and diff checks pass.
- Full framework suite: 69 passed, 0 failed.
- The real `workers.py delegate` owner path recovers an isolated byte copy of the
  observed 25 MB case in 1.61 seconds under `/usr/bin/time`, instead of exceeding
  the 600-second hook window.
- A targetless Claude Code 2.1.201 real-driver run using the configured DeepSeek
  model recovered, replayed, launched, reviewed, merged, and emitted cycle_end.
- Post-run Codex inspection of the raw transcript/runtime journal finds zero
  target actions, no WebFetch/WebSearch/Edit/Write, and no Bash source mutation;
  the exact inventory, commands, hashes, and isolated worktree status are frozen
  in `evidence/post-driver-inspection.txt`.

The first driver attempt on a copied live run is not counted as end-to-end success:
recovery worked, but the correctly path-bound work-plan transaction rejected the
relocated fixture. The decisive run used a fresh native fixture so no production
path binding was weakened.

The decisive full launch/settlement run is intentionally a synthetic targetless
fixture. Exact A-review-012 bytes are covered by the observed-size
recovery/performance reproduction, while the synthetic native fixture covers the
remaining Claude launch, Reviewer return, Root settlement, and cycle_end path.
A single unified high-load full-lifecycle E2E remains deferred; the evidence does
not claim that composition was executed.

The v1 receipt is intentionally rigid. It covers only the exact observed Claude
Code tool-use interruption plus Reviewer Start-hook timeout. OOM, process kill,
network loss, or a different pre-model terminal remains fail-closed and requires a
new versioned reason/schema and dedicated fixtures; it must not be inferred as
equivalent to v1.

Independent review remains a separate gate; test and driver success are not
treated as a review verdict.
