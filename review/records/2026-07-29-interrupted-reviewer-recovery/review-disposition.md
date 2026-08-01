# Independent Review Disposition

## Round 1 fresh-Claude findings

- Machine timing: accepted and fixed. `evidence/performance-benchmark.txt` now
  contains raw `/usr/bin/time -p` output for the real owner command on an isolated
  byte copy of A-review-012.
- Synthetic/full-path boundary: accepted. The report and frontier now distinguish
  exact high-load recovery from the synthetic targetless full lifecycle.
- Concurrent runtime writer: accepted and fixed. The runtime selftest pauses
  receipt publication under the runtime lock, starts a competing writer, proves it
  remains blocked, then verifies one linearized post-recovery event.

## Round 2 panel findings

### PR-001 — arkcli partial internal panel

- Status: accepted limitation
- Resolution: the outer arkcli backend completed and the final matrix contains
  both arkcli and fresh Claude. GLM returned an unparseable partial response and
  remains recorded as a WARN; it is not treated as a PASS vote.

### PR-002 — split high-load/full-lifecycle evidence

- Status: accepted limitation
- Resolution: F-004 is changed from closed to deferred. E-003 proves exact
  observed-size recovery; E-004 proves the targetless full lifecycle. No claim is
  made that these were composed into one high-load E2E. Performing that composition
  would require weakening the copied run's absolute work-plan binding or mutating
  the live run, neither of which is justified by this maintenance task.

### PR-003 — rigid v1 interruption reason

- Status: accepted design boundary
- Resolution: the Claude owner reference and architecture invariant now state
  that v1 covers only the exact observed tool-use interruption plus hook timeout.
  OOM, process kill, network loss, and other pre-model failures remain fail-closed
  until separately versioned reason/schema, migration semantics, and fault
  fixtures are introduced.

## Final2 panel findings

- Driver inspection provenance: accepted and fixed. The claim now says
  "post-run Codex inspection" and cites a separate raw command/output artifact;
  it is not described as an independent reviewer vote.
- Aggregate test line omitted by bundle excerpt: accepted and fixed.
  `evidence/test-summary.txt` is a short artifact containing the complete tail and
  exact `69 passed, 0 failed` line.
- Unified high-load lifecycle: retained as deferred, not silently qualified as
  passed.
- Performance certainty: accepted. E-003 is lowered from 1.0 to 0.8 because the
  precise 1.61-second value is one machine-timed observation, despite the
  six-hundred-second margin.
- GLM parse failure: retained after repeated round-2/final2 attempts. Kimi and
  fresh Claude remain the completed independent paths; GLM is not counted as a
  vote.
- v1 drift controls: accepted and fixed. Focused tests now reject both a
  non-Reviewer assignment and a different pre-model failure reason.

## Final gate backend

- Final3 fresh Claude completed without a source blocker, while arkcli again
  failed through Kimi timeout plus GLM parse error.
- The operator then explicitly instructed: "不用arkcli". The in-flight arkcli
  retry was interrupted and arkcli is excluded from the final gate.
- The final exact-diff record is therefore a new standalone fresh-context Claude
  review. Earlier arkcli records remain historical candidate reviews only.

## Final4 fresh-Claude findings

- Missing explicit rule/compile/diff exit-code evidence: accepted and fixed.
  `evidence/verification-summary.txt` binds the final diff SHA-256, UTC time,
  exact command classes, exit code 0 for every focused check, and the 69/69 tail.
- Large raw transcript/journal files omitted from model excerpt: accepted
  limitation. The complete raw files remain in the review record with SHA-256
  bindings; the capped model bundle uses the separately frozen inspection and
  adjudication summaries. Increasing model egress to include entire private
  transcripts is not justified for this maintenance review.
