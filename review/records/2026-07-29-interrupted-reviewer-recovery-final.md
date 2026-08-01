# Interrupted Reviewer Start Recovery — Final Gate

Verdict: WARN
diff_fingerprint: b2e7df9cef37e528
reviewed_diff: b2e7df9cef37e528

- Author/integrator: Codex; Codex self-review is not counted.
- Functional candidate diff SHA-256:
  `33e9a3543c92dbc55d0a11285c3044ecb57447b3435471602c0032fb16aa4af9`
- Final independent reviewer: fresh-context Claude Code CLI.
- Final review verdict: WARN, no source blocker.
- Frozen reviewed bundle:
  `review/records/2026-07-29-interrupted-reviewer-recovery/review/review_bundle.final4.json`
- Frozen bundle hash: `dba25f7c2f1d7c8b98c3148530805037b9628a6a`
- Frozen evidence index: `522de176a55dcb87fdcc2f7ac7fb793c845871c1`
- Current post-disposition bundle hash:
  `5fc664fbe286bc8c222cd865a502031b8e4d98e5`
- Operator decision: arkcli excluded from the final gate after repeated
  timeout/parse instability.

The final reviewer found no source contradiction. Its first WARN requested
explicit exit-code evidence for rule, compile, and diff checks; this was accepted
and added as `evidence/verification-summary.txt` without changing the functional
diff. Its second WARN noted that the model bundle cannot inline every raw
transcript/journal byte. That limitation is retained: complete raw files and
SHA-256 bindings are committed, while the redacted/capped review bundle uses the
inspection and adjudication summaries.

Verification:

- focused runtime-receipt, workers, turn-contract, rule, compile, and diff checks
  PASS;
- full framework scorecard: 69 passed, 0 failed in 118.4 seconds;
- isolated byte-copy A-review-012 recovery: 1.61 seconds, one typed receipt,
  assigned/no-attempt, physical runtime journal preserved;
- Claude Code 2.1.201 with the configured DeepSeek driver completed typed
  recovery, exact Reviewer replay, real Reviewer return, review disposition,
  Hunter merge, and typed cycle_end in a targetless detached worktree;
- post-run transcript/runtime inspection: target_action=0 and no
  WebFetch/WebSearch/Edit/Write or Bash source mutation.

Recorded limitations:

- the live run was not mutated;
- the original 25 MB recovery and synthetic full-lifecycle driver evidence were
  not combined into one unified E2E;
- v1 recognizes only the exact observed Claude Code interruption shape; other
  pre-model failures remain fail-closed pending a separately versioned contract;
- the 1.61-second performance number is one machine-timed observation and carries
  certainty 0.8.
