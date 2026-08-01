# Runtime Review Scope

- Status: REVIEW
- Author: Codex
- Kind: safety-critical framework maintenance
- Evidence IDs: E-001, E-002, E-003, E-004

This scope tests whether a noncompliant primary model can satisfy process gates
with prose, stale state, fabricated Agent/Cron claims, or a bare completion
`PASS`. E-001 covers turn and active-front enforcement; E-002 covers
transcript-backed receipts and post-return disposition; E-003 executes the
installed hook entrypoint across denied and allowed paths; E-004 retains the
full repository regression. There is no network target, so target-vulnerability
and HTTP replay evidence are not applicable.

The intended boundary is a lazy or instruction-noncompliant model operating
through Claude tools. A same-user process with direct filesystem access remains
outside this claim; automatic fail-open is deliberately excluded because it
would recreate the bypass this change is designed to remove.
