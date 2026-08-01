# Driver Disposition

Review source: `peer_review.final.md` (panel: arkcli + Claude, verdict WARN,
no blocker).

## PR-001 — accepted and resolved

The review bundle did not originally include a reproducible whole-file stdout
site audit. `evidence/stdout_audit.txt` now records every `print` / stdout/stderr
write site, and the integration selftest executes the complete current `main()`
under captured stdout/stderr. Success requires both streams to be empty.

Status: accepted, resolved by E-SILENT-002 and E-SILENT-004.

## PR-002 — accepted and resolved

Failure diagnostics were visible in code but were not directly asserted. The
selftest now captures the active-pointer rejection and exception cases, requires
empty stdout, and requires `active run switch failed` on stderr. It separately
requires the real active-pointer success helper to keep both streams empty.

Status: accepted, resolved by E-SILENT-001, E-SILENT-002, and E-SILENT-004.

## PR-003 — dismissed

`loop_bootstrap.py` intentionally suppresses whitespace-only child stdout, not
only the empty string. Whitespace carries no setup result and forwarding it would
reintroduce the blank UI line this compatibility change removes. Non-whitespace
child stdout is still forwarded.

Status: dismissed by E-SILENT-001.

## PR-004 — dismissed

The integration selftest invokes the real `setup_run.main()` and real local
setup modules against a temporary filesystem. It mocks only active-pointer
selection to avoid mutating the operator's control plane and the optional
classifier subprocess to avoid live network traffic. Creating a real workspace
run or issuing target traffic is unnecessary and disproportionate for this
display-only behavior. The full local suite also passed 60/60.

Status: dismissed by E-SILENT-002.

## Additional reviewer challenges

- Suppressing classifier stdout is intentional under the operator's explicit
  “statusline is enough” requirement. Classifier progress/errors on stderr stay
  visible, and its structured outputs remain file-based rather than relying on
  setup stdout.
- The active-run helper has no external call sites beyond `setup_run.py`; the
  similarly named bootstrap helper is separate. Captured-stream tests now cover
  the real `xunji_statusline.set_active_run()` success path.
- The normal `main()` integration test is the forward-compatibility guard: any
  future print or logging output on either captured stream fails the test.
- Repository search found one downstream stdout forwarder in
  `loop_bootstrap.py`; it now forwards only non-whitespace setup output.

Independent-review limitation: reviewers could inspect only the frozen bundle,
not live repository files or commands. The final panel still included both
arkcli and Claude votes; all findings were WARN and are adjudicated above.
