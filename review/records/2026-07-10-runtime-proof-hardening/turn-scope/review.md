# Review

This Codex-authored scope requires arkcli panel plus fresh Claude review. No
completion or PASS is claimed before `peer_review.md` and `peer_review.json`
are generated from the frozen bundle. Historical round files remain on disk for
audit but are deliberately not evidence for this focused scope; no current
claim depends on their disposition prose.

## Round 4 Disposition

- PR-001: accepted as an auditability improvement. Live claims moved to
  `live-scope`; every summary now carries the raw stream SHA-256 and its source
  program is reviewed beside it.
- PR-002: accepted. Real WebFetch, Write, and Edit PreTool paths are covered by
  `live_tool_surface` with effect and hash-chain controls.
- PR-003: accepted. `installed-runtime-manifest.json` is now a direct E-001
  artifact instead of an uncited copied file.
- PR-004: retained as an arkcli limitation; minimax/glm JSON parse failures are
  not treated as PASS.
- PR-005: accepted. `live_fanout_flow` now includes both Stop hooks and proves
  the final Coda path after Agent receipt/disposition/target retry.
- PR-006: accepted. `live_pause_flow` validates same-session Cron ownership,
  wrong-owner denial, exact deletion, final List, and cleanup.
- PR-007: accepted. The non-strict semantic regex path was removed; every mode
  uses the fixed denial-only envelope while a target denial is unresolved.
- PR-008: dismissed as intended per-prompt authority. A later prompt containing
  an explicit execute verb starts a new EXECUTE turn; age does not override
  session binding or UserPromptSubmit reclassification.
- PR-009: recorded as a harness limitation. Missing requested tool use is an
  inconclusive/failed smoke, never evidence that enforcement failed or passed;
  direct installed-entrypoint observations remain the deterministic control.
- Blind spot, exception retry: accepted. `output_gate` no longer reselects a
  possibly different active run inside its exception handler.
- Blind spot, front section mismatch: accepted. `run_model --selftest` now
  proves `Status: open` under Closed is both active and a schema error.
- Live integration additionally exposed and fixed internal
  `<task-notification>` overwriting the operator contract and stale control
  suggestions in Coda-only correction messages.

## Round 5 Disposition

- PR-001 accepted and fixed: pre-fanout Python commands now resolve the script
  path and accept only the three exact repository `tools/` control scripts;
  basename aliases and symlinks resolving elsewhere are denied.
- PR-002 accepted and fixed: the read grammar restricts `sed` to numeric print
  programs and rejects find file-output actions. Regression cases cover `-i`,
  `w`, and `-fprint` while retaining safe reads.
- PR-003 retained limitation: two arkcli outputs were unparsable; Kimi and fresh
  Claude completed and no partial panel is represented as a PASS.
- PR-004 dismissed as directionally incorrect: the denial envelope is an exact
  allow form; any whitespace or wording drift fails the match and remains
  blocked. It cannot silently bypass the gate.
- PR-005 accepted: the adversarial summary now records every named check,
  per-command counts, failure counts, and output SHA-256 values.
- PR-006 accepted and fixed: if active-run resolution raises before yielding a
  run, a non-empty active-run pointer makes the output gate fail closed without
  reselecting a potentially different run.
