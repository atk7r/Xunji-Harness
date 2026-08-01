# Evidence

## E-001 — Exact candidate diff

- Maturity: finding
- Action: Freeze the complete candidate source, schema, owner-document, workflow,
  and architecture diff.
- Result: the diff adds batched projection and a typed interrupted-Reviewer Start
  receipt/replay path without deleting or rewriting the physical runtime journal.
- Control: cancellation still reads raw lifecycle events and the ordinary
  assigned/no-attempt gate remains strict.
- Replicated: yes
- Artifacts: `evidence/reviewed.diff`
- Certainty: 1.0

## E-002 — Focused and full framework verification

- Maturity: finding
- Action: Run runtime-receipt, workers, turn-contract, rule, compile, diff, and
  full framework tests against the candidate checkout.
- Result: all focused checks pass and `selftest_all.py` reports 69 passed, 0
  failed.
- Control: negative cases reject child assistant activity, late lifecycle,
  ambiguous bindings, and non-matching recovery. A targeted concurrent-writer
  test pauses receipt publication while the runtime lock is held and proves the
  writer cannot enter the validated snapshot.
- Replicated: yes
- Artifacts: `evidence/test-results.txt`,
  `evidence/test-summary.txt`,
  `evidence/verification-summary.txt`
- Certainty: 1.0

## E-003 — Reproduction and projection performance

- Maturity: finding
- Action: Reproject an isolated copy of the observed 1008-event runtime journal
  with 68 lifecycle records and a 25 MB parent transcript.
- Result: the real `workers.py delegate` owner path completes typed recovery in
  1.61 seconds under `/usr/bin/time`, resets only A-review-012 to
  assigned/no-attempt, and writes one supersession receipt before the relocated
  work-plan path binding correctly stops further delegation.
- Control: the first real-driver attempt against a relocated copied run is
  recorded as failed after the subsequent work-plan transaction correctly
  rejected its absolute run_dir mismatch.
- Replicated: yes
- Artifacts: `evidence/reproduction.txt`,
  `evidence/performance-benchmark.txt`
- Certainty: 0.8

## E-004 — Successful real Claude Code primary-driver path

- Maturity: finding
- Action: In an isolated detached worktree, create a fresh targetless plan and
  Reviewer fixture through production APIs, append the exact interrupted Start
  through `append_hook_event`, then give Claude Code a natural-language continue
  task.
- Result: session `e459e35b-e576-4596-a689-3f1724fa0efa` writes one
  `xunji.interrupted-reviewer-start.v1` receipt, returns the same assignment to
  assigned/no-attempt, launches Reviewer agent `ae500ae8c6e829370`, records its
  real child claims and Stop, marks the Reviewer reviewed, merges the Hunter, and
  emits typed cycle_end.
- Control: the fixture has request budget zero; the transcript and runtime journal
  contain no target action, WebFetch, or WebSearch. The driver does not edit
  candidate source files.
- Replicated: yes
- Artifacts: `evidence/driver-adjudication.json`,
  `evidence/driver-runtime-events.jsonl`,
  `evidence/driver-loop-journal.jsonl`,
  `evidence/driver-assignments.json`,
  `evidence/driver-recovery-receipt.json`,
  `evidence/driver-session-transcript.jsonl`,
  `evidence/driver-reviewer-transcript.jsonl`,
  `evidence/post-driver-inspection.txt`
- Certainty: 1.0
