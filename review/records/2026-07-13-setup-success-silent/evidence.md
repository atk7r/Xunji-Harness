# Evidence

## E-SILENT-001 — implementation excerpt

- Artifact: `evidence/setup_success_silent.diff`
- Claim: normal setup progress, next-step text, classifier stdout forwarding,
  and active-run success text were removed; stderr diagnostics remain. The
  bootstrap caller only forwards non-empty setup stdout.

## E-SILENT-002 — focused verification

- Artifact: `evidence/selftest.log`
- Claim: compile, setup/statusline/lifecycle focused tests, rule checks, and
  whitespace checks passed. The integration selftest requires empty stdout and
  stderr on a successful isolated setup while preserving a closed Setup journal
  cycle. It also executes explicit `--help` and an isolated `--classify` path.

## E-SILENT-003 — Claude-primary policy excerpts

- Artifact: `evidence/docs.md`
- Claim: canonical instructions now define successful mechanical Setup as
  stdout-silent, retain stderr diagnostics, and retain later Router phase
  markers.

## E-SILENT-004 — source output audit

- Artifact: `evidence/stdout_audit.txt`
- Claim: all non-selftest print/write sites remaining in `setup_run.py` target
  stderr. The active-run success and failure helper behavior is also exercised
  by captured-stream selftests.
