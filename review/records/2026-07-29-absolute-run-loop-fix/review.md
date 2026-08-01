# Review

- Required matrix: Codex-authored maintenance; arkcli panel plus fresh Claude Code
  CLI when available. Codex remains synthesizer and does not count as a vote.
- First matrix: bundle `4a9b738e478960e81e903dcd75a9d1deae31ba93`,
  verdict BLOCKER. GLM and fresh Claude completed; Kimi timed out.
- Accepted findings: separate failed/successful driver artifacts, add raw transcript
  excerpts, add explicit evidence certainty, declare maintenance/no-recon scope, and
  make scheduler interaction a first-class front.
- PR-006 disposition: the claimed scheduler bypass is refuted by E-004. The raw
  transcript shows UserPromptSubmit context before effects, no CronCreate tool use,
  and a committed `loop_bootstrap.resume` receipt. The useful part—making this
  ordering explicit—was accepted as F-003.
- PR-003 disposition: unit and live Hook code share the same turn-contract owner;
  the foreign-path negative control is deterministic and fail-closed. A targetless
  third model run would add model variance, not a different authority path.
- PR-009 disposition: rubric mismatch. This scope is software maintenance with no
  recon/target coverage; final rerun uses `--no-recon`.
- Status: first findings addressed; final exact-bundle rerun pending.

## Final Matrix

- Bundle: `815e141072a94074f8ce645889fd8762be143ee7`
- Evidence index: `d3bb8f0889dc048b670c0ac3e4b04baa145e0677`
- Backend: arkcli GLM + fresh Claude Code; Kimi timed out after 300 seconds.
- Verdict: WARN
- Source blockers: none.

Final finding disposition:

- PR-001/PR-008: accepted evidence-packaging limitation. The exact local commands,
  exit codes, full scorecard, and candidate diff were independently inspected by
  the integrator, but the external bundle contains stable summaries rather than a
  signed CI log.
- PR-002/PR-003/PR-007: accepted privacy/packaging limitation. The local raw Claude
  transcript and activation receipt were inspected directly; only a redacted,
  selected excerpt was sent to external review. The first call's denial is locally
  explicit as `XUNJI_E_LIFECYCLE_EXACT_ARGV_REQUIRED`.
- PR-004: dismissed as requiring model variance for a deterministic authority
  predicate. The foreign-path negative fixture invokes the same Hook owner and
  exact PreTool admission code as the live driver; the real driver supplies the
  positive end-to-end transition/control.
- PR-005: accepted backend-availability limitation. Kimi timeout is not a PASS vote.
- PR-006/PR-010: accepted scope qualification. The driver result proves only the
  configured Claude Code 2.1.201 + DeepSeek path; architecture text says
  "observed" and does not claim future-client universality.
- PR-009: covered by existing turn-contract fixtures that a fresh bare continue
  prompt revokes pending authority and exact retries stay same-turn bound.

Driver disposition: accept WARN. No reviewer identified a source defect that
contradicts the tested resume normalization or expands run authority.
