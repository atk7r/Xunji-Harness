# Review Scope

- Status: REVIEW
- Author: Codex
- Base commit: ac01b302a5b11768a657d67828484a14455b9a50
- Frozen diff: `reviewed.diff`
- Diff SHA1: `063ef455546ae4e3ebbcd3be673cf229728faadf`
- Evidence IDs: E-001, E-002, E-003, E-004

## Maintenance Assertions

- E-001 binds explicit active-run selection and both Stop hooks, including Coda,
  review, and completion hard gates.
- E-002 binds retrospective, coverage, and cookie-chain behavior.
- E-003 is the raw full-suite log, not a prose-only test claim.
- E-004 binds the seven complete component diffs to the aggregate frozen diff and
  recorded Git base. The aggregate is intentionally not duplicated into the
  external bundle, preventing total-cap truncation.

Review the frozen diff as Codex-authored Xunji framework maintenance. Focus on
false positives, missed hard blocks, fail-open boundaries, active-run identity,
closure bypasses, per-item retrospective proof, conservative coverage writes,
and cookie-chain correctness. Do not treat this report as evidence; open
`reviewed.diff` and cite specific files/hunks.
