# Round 1 Review Disposition

Round-1 backend: arkcli panel + fresh Claude Code. Verdict was BLOCKER with six
WARN findings. Codex remains synthesizer and adjudicates against the frozen diff,
runtime artifacts, and tests.

## PR-001 — accepted (review artifact quality)

E-003 reused `verification.txt` and did not carry a canonical front ID in its
parsed Supports field. It now cites a dedicated `browser-integration.txt` and
explicitly supports the browser privacy behavior. The reviewer-generated
`affected_eids: F-001` was itself invalid because affected_eids accepts E-ids,
but that parser note does not negate the underlying artifact-quality point.

## PR-002 — accepted

Added a real loopback `probe.send` artifact containing a client Cookie and a
server Set-Cookie. The saved replay contains only hash placeholders, and an
actual `tools/replay.py --scope 127.0.0.1` run returned
`SKIPPED-PRIVACY-REDACTED`. E-004 cites both artifacts.

## PR-003 — partially dismissed, evidence expanded

The claim that percent/base64/hex tests were absent was contradicted by the full
`tools/harness/privacy.py` diff: all three already had selftests. The frozen
summary did not make that easy to see. Added case-insensitive and NFKC-normalized
variants plus explicit verification-summary coverage. Encoded values are decoded
in bounded passes before classification.

## PR-004 — accepted and fixed

The import-failure fallback duplicated an incomplete network-tool regex. It now
fails closed for every URL-bearing command when the shared privacy module is
unavailable. With the module available, URL-bearing custom Python/shell commands
must visibly invoke `validate_outbound_request` or `RequestRecorder.validate`;
known guarded framework tools retain their normal path. Selftests simulate module
absence and cover guarded/unguarded custom commands.

## PR-005 — dismissed as stated, evidence expanded

The frozen diff already included `tools/check_hook.py` cases that deny missing
raw file-backed curl uploads, and `privacy.py` reads inspectable file bytes before
allowing them. Added explicit tests proving: neutral inspectable raw upload is
allowed, the same file with private project content is denied, and missing raw
files are denied. The safer upload sensor remains the recommended path.

## PR-006 — accepted as process requirement, satisfied by rerun

Selftests are not independent review. That is why this record runs both arkcli
and fresh Claude under `--driver codex`. Round-1 review found a real fallback
defect and triggered code changes; a second review on the new frozen hash is
required before completion.

# Round 2 Review Disposition

Round-2 verdict was WARN. Arkcli had one partial parser failure; fresh Claude
returned concrete code findings. The following dispositions are against the
round-2 `peer_review.round2.md` IDs.

## Round2 PR-001/PR-004/PR-005 — accepted (evidence maturity/shape)

Self-generated summaries are now `Maturity: candidate`, `Certainty: 0.5`, and
excluded from confirmed report Evidence IDs. Load-bearing claims now use direct
artifacts: runtime privacy-redacted replay (E-004), server-observed multipart
wire bytes (E-005), and three-origin server-observed redirect headers (E-006).

## Round2 PR-002 — accepted

Added `privacy.py.txt` as a complete in-scope review artifact alongside the
aggregate diff so a sandboxed reviewer can inspect the entire enforcement module.

## Round2 PR-003 — accepted

Added actual loopback upload sensor artifacts (`upload-wire.txt` and
`upload-result.json`) proving the server received a neutral marker, filename and
boundary with no project identifier.

## Round2 PR-006 — recorded limitation

One arkcli model returned a parse error. The matrix still had a usable arkcli
vote plus a fresh Claude vote; the limitation remains explicit and no clean PASS
is inferred from the partial arkcli result.

## Round2 PR-007 — accepted and fixed

Privacy is no longer skipped merely because cleanup also matched. The command
privacy pass now permits only the exact legacy `xunji_*.<safe-ext>` artifact token
needed to remove an old leaked artifact; every other field/header/body remains
subject to hard privacy denial. Tests cover legacy cleanup ASK plus cleanup
commands carrying a local path or phone number, which remain DENY.

## Round2 PR-008 — accepted and fixed

Removed the regex-based "guard function name appears" unlock. URL-bearing custom
target scripts are denied for driver auto-execution even if a comment/string
mentions `validate_outbound_request`; Root uses guarded framework tools or
author-and-handoff.

## Round2 PR-009 — partially accepted and bounded

The Python wrapper cannot intercept every request generated inside sqlmap/nuclei.
It now fixes a neutral browser User-Agent for both, checks target/extra arguments,
disables sqlmap redirects, refuses custom nuclei templates/user-data, and tests
those invariants. Documentation states the external-process boundary rather than
claiming per-request inspection.

## Round2 PR-010 — accepted and fixed

Added multipart boundary/part parsing for request-record redaction. Sensitive
field names redact the complete part body; password/secret multipart fields require
the explicit auth exception before send. Tests prove `hunter2` is absent from the
record and the replay is marked redacted.

## Round2 PR-011 — accepted and fixed

E-003 now uses the canonical `Supports: F-001` value; the next bundle rebuild will
regenerate `evidence.json` and remove the stale empty parsed supports list.

## Round2 PR-012 — accepted and fixed

Audit command redaction now has a separate fail-safe. If sanitization raises, the
event is still written with `<command omitted: redaction failed>`; it neither logs
raw private bytes nor silently drops the audit decision. The hook selftest injects
a failing sanitizer and asserts this fallback.

# Round 3 Review Disposition

Round-3 verdict remained WARN and contained one evidence-grade BLOCKER plus one
new protocol gap. No HTTP-path code blocker remained after adjudication.

- PR-006 accepted: E-005 now includes a second fresh-marker upload wire/result;
  the sensor's own replication requirement is satisfied.
- PR-007/PR-011 accepted: E-006 is renamed as a loopback candidate, downgraded to
  `Certainty: 0.5`, and removed from confirmed report Evidence IDs; no raw wire
  capture or independence is claimed.
- PR-001/PR-002/PR-004/PR-005/PR-009/PR-014 accepted as scope corrections:
  the report now claims hard enforcement only for guarded framework paths;
  Agent prose, selftest summaries, browser summary, scan internals, and custom
  URL-hidden scripts are not promoted as confirmed evidence.
- PR-003 accepted: destination hostname remains scope-exempt, but a legitimate
  denied token in a target-native path/body has no silent bypass; Root uses an
  equivalent neutral proof or author-and-handoff.
- PR-008 clarified: E-004 confirms replay redaction/non-replay semantics only;
  it does not claim to satisfy fresh authenticated replication for a real
  vulnerability finding.
- PR-010 accepted as trust-boundary documentation: the engagement proxy is
  operator-controlled infrastructure. Driver bytes are checked before proxying;
  proxy-side rewriting/injection requires a separate proxy audit.
- PR-012 accepted and expanded: added URL-safe/unpadded Base64, MIME encoded-word,
  HTML entity, escaped hex/octal, zero-width, case and NFKC decoding/tests.
- PR-013 accepted and fixed: command privacy and fail-closed URL recognition now
  include `ws://` and `wss://`; `websocat`/`wscat` are recognized and tested.
- PR-015 recorded residual: both hook and active tools import the same privacy
  source intentionally to prevent policy drift. Hook import failure hard-denies
  URL actions; guard/tool import failure prevents the tool from starting. No
  claim is made that a dual-failure artifact exists.

# Final Review Disposition

The final frozen-hash review returned WARN. Four items identified concrete
recording or coverage gaps and were fixed; the remaining items were adjudicated
against the stated trust and evidence boundaries.

- PR-001 accepted and fixed: multipart replay sanitation now hashes every
  transmitted filename, sanitizes part headers, and replaces a private boundary
  in the saved body. Direct guarded multipart requests also require the filename
  to use the neutral unique proof format, even under an auth exception.
- PR-002 accepted and fixed: URL userinfo secrets require
  `allow_sensitive_auth`; the complete userinfo component is hash-redacted in
  replay URLs. Fragment auth fields are sanitized as well.
- PR-003 accepted and fixed: response headers and bounded response previews now
  pass content-aware redaction in both `probe.py` and `RequestRecorder`.
  Set-Cookie, custom token/session headers, Location query secrets, JSON/form
  secret fields, real email, phone, IDs, internal markers, and local identity
  values are not retained verbatim in the replay JSON.
- PR-004 accepted as a missing explicit proof, not as an unguarded network defect:
  `tools/exploit.py` already routes its registered ViewState HTTP operations
  through `probe.send`; it now has a registered selftest proving pre-I/O privacy
  denial. `client_graybox.py` has no network client and is explicitly documented
  and tested as passive local ingestion.
- PR-005 retained as an intentional fail-closed tradeoff: path-shaped local
  identity values can collide with target-native data. There is no silent bypass;
  equivalent neutral proof or exact author-and-handoff remains the documented
  exception workflow. This favors the operator's no-personal-data invariant.
- PR-006 retained as the declared proxy trust boundary, not promoted to an
  end-to-end proxy guarantee. Driver bytes are checked pre-proxy; independent
  proxy rewriting/injection requires a separate proxy audit.
- PR-007 dismissed as a claim/evidence category mismatch: claim 5 is the closure
  rule for a real confirmed finding. E-004 proves only redaction and the
  non-replay verdict and is not presented as a replicated vulnerability finding.
- PR-008 contradicted by the current report text: claim 1 explicitly says hard
  enforcement is limited to guarded framework paths and Agent prose alone is not
  hard enforcement.
- PR-009 retained as an explicit residual. Hook module-import failure denies all
  URL-bearing commands; an active tool/guard import failure prevents that Python
  tool from starting. The shared module deliberately avoids duplicated policy.
- PR-010 resolved as artifact description: the two raw result files remain
  immutable; `upload-replication.txt` now binds the two fresh-marker 201 wire
  captures and records that the generic repeat instruction was satisfied.

After these changes, `check_rules.py`, `git diff --check`, and all 60 registered
selftests pass. A new frozen diff and heterogeneous rereview are required before
closure.

# Final-3 Review Disposition

The final-3 heterogeneous review used the new frozen hash and returned WARN with
no BLOCKER. Two warnings drove additional hardening and evidence work.

- PR-001 retained as correctly bounded candidate evidence: E-006 is deliberately
  not a confirmed finding and is not listed in final report Evidence IDs. The
  redirect behavior is additionally covered by source and selftests, but no raw
  packet-capture claim is made.
- PR-002 accepted and fixed: generic `/home/<route>`, `/Users/<route>`, and
  `/runs/<route>` shapes no longer trigger privacy denial. The guard now matches
  the actual local home/configured identity values and run identifiers carrying
  the framework's dated run shape. Positive and false-positive tests cover both.
- PR-003 accepted as an evidence gap: E-007 adds two fresh loopback runtime replay
  artifacts with distinct response tokens/emails/custom session headers/Location
  query secrets. All raw values are absent and field-class redactions are present.
- PR-004 dismissed as a maintenance/live-run category mismatch. This scope has no
  recon assets; `surface.md` now records the single frozen repository surface so
  the absence is explicit rather than inferred.
- PR-005 retained as the documented custom-code limit. Non-framework Python code
  with a hidden destination is author-and-handoff and is not claimed as hook-
  inspectable. Registered active framework paths use per-request validators;
  `exploit.py` now has an explicit integration selftest.
- PR-006 recorded: one arkcli panel member returned a parse error, while another
  arkcli reviewer and fresh-context Claude returned substantive findings. No clean
  PASS is inferred from the partial member.

The blind-spot notes about the 32-token decoding cap and two-pass percent decoding
were also removed structurally: all discovered base64/hex tokens are inspected,
percent decoding continues for eight layers, and deeper still-changing encodings
fail closed. Tests cover a marker after 32 benign tokens and triple encoding.

Because PR-002 changed the validator and hook-facing behavior, these fixes require
one final independent review of the new frozen hash; final-3 is not reused as a
vote over changed code.

# Final-4 Review Disposition

Final-4 reviewed frozen code hash `8b3c1171f226c7152c8a011e60639e9420ebfae6`
and returned WARN with one evidence BLOCKER.

- PR-001 accepted and resolved: E-004 now has a second fresh-port loopback run
  using different client Cookie, server Set-Cookie and body values, plus a second
  independent `tools/replay.py` invocation. Both records contain distinct hash
  placeholders, neither retains reusable values, and both verdicts are
  `SKIPPED-PRIVACY-REDACTED`.
- PR-002 accepted as claim calibration: report claim 2 now explicitly labels the
  loopback redirect behavior candidate and disclaims raw-wire confirmation. The
  source/test claim remains, but E-006 is not promoted or listed as confirmed.
- PR-003 recorded as an arkcli context limit, not a source-integrity defect. The
  frozen files carry complete SHA-1 identities; fresh-context Claude read the full
  1009-line privacy source, while the arkcli compact bundle excerpt was truncated.
- PR-004/PR-005 retained as evidence breadth warnings, not contradictions of the
  narrowed report: runtime evidence confirms browser body pre-I/O blocking,
  neutral upload wire bytes, request/response replay redaction, and non-replay;
  selftests and frozen source cover additional classes without promoting each to
  a standalone confirmed runtime finding.
- PR-006 recorded: one arkcli member succeeded after retry and another returned a
  parse error. Fresh-context Claude completed and independently confirmed the
  false-positive fix and removal of stale decoder limits.

No tracked code changed after final-4. The blocker resolution changes only the
review evidence ledger/artifacts and requires a fresh evidence-bundle rereview,
not another code regression run.

# Final-5 Review Disposition

Final-5 confirmed that the E-004 replication blocker was cleared and returned
WARN with no BLOCKER.

- PR-001 accepted and fixed: the upload sensor boundary now uses
  `----proof-YYYYMMDD-<8hex>`, matching the same dated neutral marker contract.
  E-005 now cites two new 201 server-observed wire/result pairs generated by the
  corrected code; older non-dated-boundary artifacts are historical only.
- PR-002 accepted and normalized without rewriting history: E-004 now cites its
  second and third fresh runs, both emitted by the current recorder schema with
  `privacy.response_redactions`; the first old-schema artifact remains uncited.
- PR-003 accepted as workflow state: D-001 remains pending only until the new
  boundary code hash is independently reviewed; D-002 is now fixed-and-reviewed.
- PR-004 dismissed as non-load-bearing in this repository-only maintenance scope;
  `target.md`, `surface.md`, and the report all state that there are no recon/live
  assets to reconcile.
- PR-005 recorded: one arkcli member returned substantive evidence findings and
  one returned a parse error; fresh-context Claude completed. No clean PASS is
  inferred from the partial arkcli member.

The boundary fix changed tracked code, so the complete 60-suite regression was
rerun (60/60) and a new frozen-hash independent review is still required.

# Final-6 Review Disposition

Final-6 independently reviewed frozen code hash
`a4ab569a2f95803511025fc833f83eed5cd2f605` with arkcli plus fresh-context
Claude and returned WARN with no BLOCKER.

- PR-001 dismissed as a date/freshness misread. `upload-wire-3.txt` and
  `upload-wire-4.txt` contain different nonce values (`387e2b16` and
  `1f5b38c5`), proving a fresh boundary per upload. The boundary uses the UTC
  date generated by `neutral_marker`; the test's explicit marker values use the
  operator-local date. Both independently satisfy `proof-YYYYMMDD-<hex>` and no
  contract requires their dates/nonces to be equal.
- PR-002 dismissed as a maintenance-evidence category mismatch. E-004/E-007
  directly confirm the framework recorder behavior under replicated controlled
  inputs; they do not claim that every possible real target response shape has
  been observed. Live targets were explicitly out of scope for this review.
- PR-003 resolved by this final-6 review itself. D-001 is now
  `final-reviewed; no-unresolved-blocker`.
- PR-004 contradicted by the ledger: E-002 is `Maturity: candidate`,
  `Reportable: no`, `Certainty: 0.5`, and is excluded from final report Evidence
  IDs. The 60/60 summary is regression context, not a confirmed target finding.
- PR-005 already matches the ledger: E-003 and E-006 remain candidate and are not
  promoted or listed as confirmed evidence.
- PR-006 recorded as a residual review limitation: one arkcli member produced
  substantive output, one had a parse error, and fresh-context Claude completed.
  The panel is accepted as WARN, never represented as clean PASS.

Final-6 blind-spot notes do not contradict closure: redacted requests are rejected
before replay method/`--force` handling, so a redacted POST cannot send a hash
placeholder; generic real-target variability and cross-process breadth remain
explicit non-claims. No tracked code changed after the final frozen review.

# Concurrent Worktree Scope Correction

After final-6, `git status` exposed a concurrently authored `TODO.md` roadmap
replacement and separate `2026-07-13-ccb-native-xunji-todo-review.md`. They were
not part of this task and were not edited or reverted. The earlier aggregate
freeze had accidentally included the tracked `TODO.md` hunk. `reviewed.diff` was
therefore rebuilt with an explicit `TODO.md` exclusion; the scoped privacy diff
hash is `315c712a0aa85a38eaa700dc258b5711a0fb696e`. Because the review subject hash
changed, a final scoped rereview is required even though privacy production code
did not change.

# Final-7 Review Disposition

Final-7 reviewed the scoped privacy-only diff and returned WARN with no BLOCKER.

- PR-001 accepted as an avoidable consistency ambiguity despite both old values
  being fresh and format-valid. The upload boundary now derives directly from
  the same per-request marker, so date and nonce match marker/content/filename.
  E-005 cites two new 201 server-observed wire pairs proving exact equality.
- PR-002 retained as claim calibration: exploit inheritance, client-graybox
  passivity and URL userinfo handling are source/selftest-backed framework claims;
  the report does not promote each as an independent runtime finding.
- PR-003 recorded as a fundamental bounded-inspection residual. The hard gate
  covers common encodings and fails closed on over-nested percent transforms;
  arbitrary bespoke transforms cannot be exhaustively decoded. Driver guidance
  explicitly forbids encoding around the policy and custom hidden network scripts
  remain author-and-handoff.
- PR-004 already matches the ledger: E-006 remains a 0.5 candidate and is not
  listed in final Evidence IDs.
- PR-005 records the same partial arkcli limitation; fresh-context Claude and one
  arkcli member completed.

The marker-derived boundary changed tracked code. Rule checks and all 60 suites
passed again (85.3s), so the scoped frozen diff requires one final hash review.

# Final-8 Review Disposition

Final-8 reviewed scoped frozen privacy diff hash
`1dd922dba8fc55c941358bebae012efdcf09322a` with the scope/safety rubric. The
arkcli plus fresh-context Claude panel returned WARN with no BLOCKER.

- PR-001 accepted as an audit-record defect: D-002 still described the obsolete
  early design where a custom script could be accepted by visible guard-function
  text. D-002 now matches the final code: URL-bearing custom scripts are denied
  for driver auto-execution even if validation names appear; hidden destinations
  remain author-and-handoff.
- PR-002 accepted as evidence wording: D-002 now cites the final frozen diff and
  final independent review. E-002 selftests remain candidate regression context,
  not confirmed evidence.
- PR-003 recorded as serialization behavior: URL query placeholders are percent-
  encoded by standard `urlencode`, so downstream URL parsers recover the same
  `<redacted:...>` token. The raw secret is absent and request replayability is
  governed separately.
- PR-004 is mitigated by the complete `privacy.py.txt` copy. Fresh-context Claude
  read all 1009 lines; arkcli's compact excerpt limitation remains recorded.
- PR-005 records the recurring partial arkcli limitation; one arkcli member and
  fresh-context Claude completed. The result is WARN, not represented as PASS.
- PR-006 retained as an integration-test breadth recommendation. Existing
  sentinel, hook, probe, replay and check_run suites exercise the layers, but no
  single artifact is promoted as a whole-pipeline target finding.
- PR-007 dismissed as a semantic misread: `privacy.replayable` describes whether
  the recorded request may be re-sent. Response redaction does not make a safe
  request unsafe; request-redacted records are rejected before method/`--force`.
- PR-008 retained as the intentional fail-closed identity tradeoff and documented
  author-and-handoff exception path.
- PR-009 is theoretical and correctly notes the target would receive the literal
  mixed encoding, not the private decoded value; no false allow was shown.
- PR-010 matches the ledger: E-002 is candidate-only and excluded from final
  report Evidence IDs.

No tracked privacy code changed after final-8. D-001 is now
`final-reviewed; no-unresolved-blocker`.
