# Disposition — Framework Deadlock Repair

- Author/integrator: Codex
- Functional diff SHA-256: `5576d6f29e8d2acab184fd24516c23c201012607f37f4bac45dacf6ed3ac04fa`
- Final frozen review bundle: `6db994717c04b1593ca3b7a6d0f74e2033a358b0`
- Evidence index: `a8e74af0bd4e5fdb64a895b3580475f9fa9ca73d`
- reviewed_diff: 46e21b54314307f5
- Claude final record: `2026-07-27-framework-deadlock-repair-final2-claude.md`
- Arkcli final record: `2026-07-27-framework-deadlock-repair-final-arkcli.md`
- Verdict: WARN
- Driver disposition: accepted; no independent reviewer reported a source blocker.

## Review History

1. The first full matrix returned `NEEDS_DRIVER`: Claude completed, Kimi timed
   out, and GLM output did not parse. Its useful warnings found a stale
   checkpoint claim and weak review packaging.
2. The checkpoint was rewritten, certainty was reduced, legacy capped replay
   and Reviewer dependency-digest tamper received explicit fixtures, and the
   final candidate was rerun through Codex and Claude primary-driver gates.
3. The first final Claude bundle incorrectly omitted `workers.py` excerpts
   because split artifacts had no `.diff` suffix and supplied only a prose test
   summary. Those review-artifact defects were accepted and fixed.
4. The refreshed frozen bundle includes both worker diff parts and the raw
   Claude primary-driver test output. Fresh Claude returned WARN with no source
   blocker. Arkcli completed the GLM review with no source blocker; Kimi timed
   out, so the arkcli vote remains partial WARN.

## Finding Disposition

- Legacy replay compatibility: dismissed as a false premise, then protected by
  an explicit regression fixture. Baseline replay `response.len/sha1` already
  bind the full raw response; a capped saved prefix now yields
  `truncated=true`, `wire_verified=false`.
- Reviewer negative coverage: accepted and strengthened. Existing wrong-prompt,
  byte-identical replay, cancellation prohibition, and bundle-tamper checks now
  also reject a changed dependency result digest.
- Classifier TOCTOU/priority: dismissed as non-blocking by design. The
  classifier provides one terminal next action; running attempts must wait, and
  every subsequent action is reclassified. The execution owner revalidates the
  assignment, runtime journal, dependency digest, and instruction bundle under
  the assignment lock.
- Peer-review evidence drift: accepted behavior. Legitimate concurrent evidence
  change invalidates the frozen vote and requires a new bundle/review; it must
  not append a stale receipt.
- Coda migration: accepted and documented. Existing cache writes do not become
  historical semantic cycles; the next valid typed `cycle_end` establishes
  forward progress.
- Uniform certainty, empty claims/refutes, Type-B/coverage framing, and redacted
  internal identifiers: review-package/rubric limitations for a framework
  maintenance diff, not source defects. The final bundle retains 0.8 candidates,
  raw mechanical output, exact grouped diffs, and mandatory egress redaction.
- Kimi timeout: accepted reviewer-availability limitation. It is recorded and
  is not converted into a PASS vote.

## Verification

- Focused owner selftests, Python compile, rule check, and diff check: PASS.
- Codex full suite: 69 passed, 0 failed in 117.2 seconds.
- DeepSeek-backed Claude Code primary-driver session
  `61a05a61-4c92-4eca-a706-677615a93dbf`: exact
  `python3 tools/selftest_all.py`, 69 passed, 0 failed in 112.4 seconds,
  exit 0, no permission denial.
- Transcript/worktree adjudication: one Bash tool use; no Edit/Write, Agent,
  target request, active-run pointer, or candidate-external mutation.
