# Turn Enforcement Review Scope

- Status: REVIEW
- Author: Codex
- Kind: safety-critical framework maintenance
- Evidence IDs: E-001

## Claim

This scope asks whether a lazy or instruction-noncompliant Claude model can turn
an explanation into actions, relabel active work to avoid Agent fan-out, reuse
stale state, or proceed when control files are malformed. No external target was
engaged.

## Enforcement

E-001 binds the settings diff and complete reviewed source excerpts to the turn,
output, Stop, and canonical-front contracts. Installed runtime hashes and live
activation are reviewed in `live-scope`. Its named adversarial log covers missing, malformed,
wrong-schema, stale, and cross-session contracts; missing/malformed frontier;
manual or old Agent proof; background review; direct receipt mutation; and Coda
bypasses. The full repository regression remains in the parent maintenance
record and is not presented as a separate finding in this focused scope.

## Live Activation

Real Claude lifecycle behavior is reviewed in the separate `live-scope`, which
contains the mode/fabrication smoke, full Agent-to-Stop flow, WebFetch/editor
surface, and Cron pause transaction. This scope intentionally reviews the static
enforcement implementation without duplicating those runtime artifacts.

## Boundary

Same-user direct filesystem tampering remains outside the threat claim.
Automatic fail-open is intentionally excluded because it would restore the
process bypass this work removes. Read-only memory inspection remains allowed;
unknown or mutating shell grammar requires current-prompt approval.
