# Runtime Receipt Review Scope

- Status: REVIEW
- Author: Codex
- Kind: safety-critical framework maintenance
- Evidence IDs: E-001

This static/control scope asks whether prose, stale/manual files, forged chain content,
unmerged Agent output, loose Cron identifiers, or a bare reviewer PASS can
substitute for observed runtime work. E-001 covers implementation invariants
and named adversarial controls, including the full `selftest_all.log`. Real
Claude Agent/Cron/tool integration is intentionally reviewed in `live-scope`
without duplicating its source and summaries here. The full repository regression
is included as a control artifact, not presented as a separate finding. It does
not claim that synthetic transcript fixtures are live-session evidence. The
installed settings snapshot, its manifest hash, raw focused selftest output, and
derived summary are all included for direct cross-checking.
