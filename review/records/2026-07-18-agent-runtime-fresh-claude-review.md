# Fresh-context Claude maintenance review

- Date: 2026-07-18
- Reviewer: Claude Code 2.1.201 through the locally configured DeepSeek API
- Model / effort: `deepseek-v4-pro[1m]` / `max`
- Session: `31f2b0c4-2455-4568-96a3-e48dd958d7bf`
- Author under review: Codex
- Review backend: Claude Code only; arkcli was explicitly not used
- Frozen commit: `6d9b667dc2996075098afd7d3d8fb658c8fe4c68`
- Frozen tree: `92120979887a5ad80a9b03d5a08daada58ceaaa9`
- Parent/base: `1a2170eb6e1a6d7a31d37d8ef8310db9ba7b4bbb`
- Claude transcript SHA-256:
  `42daa6b36b18c19b61f6e85edb6c67d43057e5c9ebe55958494dd06c3cb10250`
- Disposition: **PASS**
- Findings: **P0=0, P1=0, P2=0, P3=0**

The reviewer received a fresh, read-only prompt and a detached worktree whose
content was created from the exact staged index. The worktree was clean at the
end of review. The prompt expressly excluded CCB/TypeScript migration and the
unstaged `tools/xunji_statusline.py` candidate. It instructed the reviewer to
cross-check implementation, contracts, fixtures, owner documentation, and the
Claude primary-driver E2E record rather than accept their PASS language.

## Review coverage

Claude examined the complete parent-to-candidate diff and reported review of 63
files. Its focused analysis covered:

- exact registered capability/argv/effect classification and invalid-argv
  recovery without maintenance/target truth;
- Stop output union, fixed envelopes, Coda, target/maintenance receipt sourcing,
  and run-gate consumption;
- work-plan v2 transaction/archive lineage, forward recovery, lane topology,
  ROOT_DIRECT, delegation, cancellation, and cycle ordering;
- exact role/type/prompt binding, causal Parent/Start/Stop projection, immutable
  results, digest-bound Reviewer disposition, and Root finish gates;
- setup activation single-writer/CAS, durability checks, and pending-contract
  fail-closed behavior;
- driver-doc conformance, TODO completion claims, and the E2E F-001
  `needs-control` recovery path.

The reviewer independently ran:

- `python3 tools/selftest_all.py` — 69 passed, 0 failed;
- `python3 tools/bench.py score-all bench/` — 18/18 clean, zero false positives;
- `python3 tools/turn_contract.py --selftest` — passed;
- `python3 tools/work_plan.py --selftest` — passed;
- `python3 .claude/hooks/run_gate.py --selftest` — passed, 33 checks;
- `python3 .claude/hooks/output_gate.py --selftest` — passed, 27 checks;
- `python3 tools/probe.py --selftest` — passed against local loopback;
- `python3 tools/check_rules.py` and `python3 tools/check_templates.py` — passed;
- focused static inspection of shell-shape detection, capability effects, Stop
  exclusivity, review disposition flow, and activation CAS/TOCTOU boundaries.

## Reviewer conclusions

Claude found no actionable defect. In particular, it confirmed that invalid
registered argv remains denied while explicitly avoiding maintenance debt; Stop
families are exclusive and receipt-backed; Reviewer `needs-control` leaves
`action_required`; `accept-candidate` is required before the reviewed candidate
can reach a complete review status; and setup activation re-reads and validates
state under its exclusive lock before pointer publication.

It also verified that the E2E record did not hide the F-001 disagreement: the
initial Reviewer disposition remained recorded, Root re-read the frozen
artifacts and corrected the field-attribution description, and the local-only
Hunter ended `blocked` rather than being promoted to target evidence or a
finding.

## Residual risks and disposition

1. `turn_contract.py` intentionally fails closed when a pending contract exists
   without its target claim. The reviewer could not prove a normal bootstrap
   route that creates that malformed state. Disposition: bounded investigation
   backlog; no authorization bypass and no commit blocker. TODO wording is
   changed from a presumed regression to a production-path audit.
2. Trusted Python identity relies on the canonical local interpreter resolved at
   validation time. Replacing that binary between hook validation and execution
   is a local platform TOCTOU premise. Disposition: accepted platform boundary,
   not a target or remote bypass introduced by this diff.
3. Durability claims do not cover the complete builder directory tree,
   SessionEnd selection creation, or pointer clear. Disposition: accepted and
   already stated in the Architecture Checkpoint; projection gaps remain
   fail-closed/reprojectable.

No residual item changes the review verdict or authorizes marking the broader
W2 scheduler A/B benefit, stage-default strategy, or CCB/TypeScript work as
complete.
