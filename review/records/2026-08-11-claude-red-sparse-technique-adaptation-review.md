# Claude-Red Sparse Technique Adaptation Review

## Scope

- Author: Codex.
- Claude-primary owner:
  `.claude/skills/xunji-exploit-techniques/SKILL.md`.
- Added on-demand references:
  `business-logic-state-machine.md`,
  `request-smuggling-parser-differential.md`,
  `graphql-authorization-and-cost.md`, and
  `race-toctou-state-transition.md`.
- Architecture continuity:
  `docs/ARCHITECTURE.md` Maintenance Checkpoint only; no design-body change.
- Source: selectively rewritten reasoning cues from MIT-licensed
  `SnailSploit/claude-red` commit
  `aeb41eca7088a703c3a35fbcba3086d4a6c1aa4e`, with per-reference independent
  OWASP, IETF, or primary-research grounding.

## Verification

- Isolated candidate from repository HEAD:
  - `python3 tools/check_rules.py`: PASS.
  - `python3 tools/check_templates.py`: PASS.
  - selector/reference existence and required-section checks: PASS.
  - `git diff --check`: PASS.
  - `python3 tools/selftest_all.py`: 70 passed, 0 failed (115.0s).
- DeepSeek-backed Claude primary-driver session
  `d37c91f9-3d62-4cac-8271-641d48b0b815`:
  - selected race/TOCTOU for a GraphQL mutation whose discriminating variable
    was concurrency;
  - selected business logic for a serial stale-step/quota anomaly before defect
    proof;
  - enforced candidate-only output and explicit operator approval for exact
    target-side cleanup;
  - ran the registered rule/template checks successfully;
  - made no file, target/network, run, Agent, or Cron effect.
- The same driver attempted two custom `git diff` commands that the Hook denied.
  Those denials were disclosed and were not counted as verification results.
- Driver transcript SHA-256:
  `e7dffb0ec6a60f1a34b291832b707be5aaba1ad5c3ee495a7e49f38d4f27ab90`.

## Independent Review And Disposition

External assistance was disabled by policy. No external-provider vote is
claimed. Claude Code is independent relative to this Codex-authored diff; Codex
self-review is not counted.

1. Fresh-context no-tools session
   `a4a45a84-5f7a-4edb-b9ea-50db82f608ca` returned WARN.
   - Accepted P2: the business selector said the operation `accepts` an invalid
     transition, which required proof before loading the diagnostic lens.
   - Fix: route from observed stale/replayable/client-controlled/apparently
     unenforced signals, not confirmed acceptance.
   - Accepted P3: make cleanup require explicit operator `yes`, and arbitrate
     overlapping GraphQL/business/race/smuggling selectors by the next
     discriminating variable.
2. Fresh-context no-tools session
   `aa065f4b-bcb2-4bd1-b29a-c693dc9c5a9c` returned PASS with no P0-P2 and
   suggested two clarity-only P3 refinements.
   - Accepted: a serial business-state invariant selects business logic even on
     GraphQL.
   - Accepted: request-smuggling deeper proof is confined to controlled
     fixtures/test routes and never overrides hard stops.
   - Dismissed as duplicate-owner risk: copying the global cleanup rule into
     references that do not instruct cleanup. The race reference retains the
     local reminder because it explicitly discusses cleanup.
3. Final fresh-context no-tools session
   `a0885296-2c93-42d8-af82-cf1f4e374d9d` reviewed frozen behavioral-candidate
   diff SHA-256
   `974e6dd0c270afa624b3faa6e9a4d96a3b1d5c703a0dbf2d08b9d9d5b01ad9d4`
   and returned PASS with no P0-P2.
   - Transcript SHA-256:
     `54edcdf420dc095bc9f0464919db1ef0d7ef843669416b7309e54b9241d178d7`.

## Final Disposition

PASS. The four additions remain sparse reasoning lenses, not payloads or scan
lists. They cannot create authority, widen scope, bypass guard/privacy, promote
evidence, or close a run. The post-review edits are limited to this record and
the mechanical checkpoint provenance update.

No live target/network request, run mutation, Agent/Cron action, evidence/report
promotion, Git staging, commit, or publication was performed.
