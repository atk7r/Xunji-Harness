# P1 Setup-Source Contract and Router Review

- Date: 2026-07-15
- Verdict: PASS WITH RECORDED ARKCLI BACKEND/PARSER LIMITATION
- diff_fingerprint: 115e9c7f84c48b9e
- reviewed_diff: 115e9c7f84c48b9e
- Pre-commit framework-subset fingerprint: `115e9c7f84c48b9e`.
- Full reviewed implementation SHA-256:
  `0feff6ad593367d8320d53ef4712db82cc88058a1d58c6bcbc3acca3fb91f9a8`
- Base commit: `6448592f117f92db06894632141cc2b5080846a8`
- Author/driver and final synthesis: Codex; Codex self-review is not counted as
  an independent vote.
- Scope: 21 staged P1-1/P1-2 files implementing the versioned setup-source
  contract, deterministic `/loop --source` routing, source/related-source
  provenance, setup-transaction integration, closure verification, primary-driver
  documentation, and regression wiring.

## Final behavior reviewed

The candidate adds `xunji.setup-source.v1` as a strict candidate/provenance
contract. Formal setup freezes the primary source, any material related recon
report, normalized manifest, validator receipt, and transaction identity before
publish and active-pointer compare-and-swap. Source, attachment, target, tool,
and reviewer text remain data; only the hook-bound current top-level prompt hash
may add `authority=operator`.

`tools/loop_bootstrap.py --source ... --type auto` routes a recognized existing
run to resume, parses an explicit HTTP(S) URL locally without fetch, and imports
recognized Guanlan/recon JSON without re-probe. Unsupported Markdown, HTML, PDF,
DOCX, text, and ordinary JSON fail closed with `normalizer_required`; the later
AI normalizer is not represented as implemented. Existing setup CLIs and formal
legacy runs retain their documented compatibility.

The JSON Schema is explicitly the structural layer. Mandatory cross-field
semantics remain owned by `tools/setup_source.py::validate_manifest`: resolved
source-value containment, IDNA host rules, URL/host/scheme/port consistency,
hook prompt binding for operator authority, asset URL/host consistency, and
snapshot/bundle hashes. A future non-Python validator must pass shared fixtures
and differential tests before becoming authoritative.

## Verification identity

- `python3 tools/selftest_all.py`: **64 passed, 0 failed (89.4s)**.
- Raw full-suite log SHA-256:
  `bfeb2b8ba68326866e2ece15f92187a579cd1c2b5a55ee5813ecc5fb59a5ba11`.
- Focused setup-source, setup-run, setup-transaction, loop-bootstrap, check-run,
  command-shape, privacy, turn-contract, maintenance-authority, runtime-boundary,
  template, and rule checks passed.
- JSON parsing, Python compilation, and staged diff-format checks passed.
- Final staged implementation fingerprint remained
  `0feff6ad593367d8320d53ef4712db82cc88058a1d58c6bcbc3acca3fb91f9a8`
  after the final complete suite.

These are controlled local observations, not independent reviewer votes. This
record is the review synthesis artifact and is excluded from the reviewed
implementation fingerprint by design, avoiding a self-referential hash.

## Independent review chronology

### Arkcli panel attempts

The arkcli matrix was attempted against the full/core and source-focused frozen
candidate at parent fingerprint `8ad07c3e04c148bc`.

- Kimi timed out after 300 seconds on repeated full/core and source-focused runs.
- GLM repeatedly returned content that the structured review parser could not
  parse, including a dedicated clarification retry.
- The source-focused aggregate used bundle
  `88b39bca0cf32f91e39a0ac2f8024544a7eb266c` and evidence index
  `f093d3e63f6eaeac6635400fd50e74aa986292c3`.
- Its displayed `BLOCKER` aggregate contained **zero BLOCKER findings** and only
  PR-001 WARN for the Kimi timeout. Under the evidence gate, a blocker verdict
  without a concrete blocker claim, artifact/function/path, and recommended
  action is malformed and cannot block or pass the candidate.
- The GLM-only clarification ended `ERROR` with no findings after two parse
  errors. It is retained as a backend/parser limitation, not converted into a
  reviewer vote.

Arkcli therefore did not produce a valid independent code verdict. The attempts
and their failure modes satisfy neither PASS nor BLOCKER and remain disclosed.

### Claude full-candidate review

Claude Code ran fresh-context, with no tools and only the frozen hard-redacted
bundle. The strict result for parent fingerprint `8ad07c3e04c148bc` was PASS with
one WARN and no BLOCKER.

- Bundle: `6863019881f50b456fcddb6709f286a107c4b8b5`.
- Evidence index: `be105019ce73c9b61be91eafc123749c6617146f`.
- Stored review SHA-256:
  `c9b18356d571c91266e3b22659baa317a57c15039fd304f219a60d99e29e43e9`.
- WARN PR-001: the language-neutral JSON Schema did not explicitly document
  semantic invariants enforced by the Python validator, so a future consumer
  using the structural schema alone could accept an invalid manifest.

The finding was accepted. The contract now names every cited semantic invariant
and its current owner, architecture/workflow docs state the replacement-runtime
condition, and selftest/rule checks pin the contract text against drift. No
production authority, routing, transaction, privacy, or closure logic changed
in this reviewer-driven delta.

### Claude final-delta review

The exact warning-resolution delta and final fingerprint were reviewed again by
Claude Code fresh-context.

- Final fingerprint:
  `0feff6ad593367d8320d53ef4712db82cc88058a1d58c6bcbc3acca3fb91f9a8`.
- Bundle: `96d8b743e1aed5fc7cee71390f66d021f15166d7`.
- Evidence index: `38207b5ecc6f538ee85dba1440a988a32e24fc08`.
- Stored review SHA-256:
  `7b9147eae136b678a0f924607aa2c93ab9ec2645eb3ff5eee826a61f974b5b33`.
- Result: **PASS, zero findings**.

The reviewer confirmed that the delta resolves the parent WARN, keeps the Python
validator authoritative today, describes TypeScript/differential testing only as
a future migration condition, and does not alter production behavior.

## Finding dispositions

### PR-001 — JSON Schema did not name semantic validator requirements

Status: **accepted and fixed**.

The structural/semantic split, exact invariants, owner, and migration gate are
now explicit in the schema comment, architecture, and workflow reference. The
setup-source selftest verifies the required semantic markers and `check_rules.py`
prevents their silent removal. The final fresh-context review returned PASS with
no remaining finding.

### Arkcli aggregate `BLOCKER` without a blocker finding

Status: **dismissed as a malformed aggregate, with backend limitation retained**.

The only structured finding was a WARN about Kimi timeout. No code claim,
evidence reference, affected evidence ID, or recommended code action accompanied
the aggregate label. Treating the label alone as evidence would violate the same
review evidence gate this maintenance work is required to preserve.

## Residual limitations

- Arkcli did not complete a valid panel vote: Kimi timed out and GLM output failed
  parsing. This missing coverage is explicit and is not called PASS.
- Claude review used artifact excerpts and did not execute the repository. The
  full local suite is supporting evidence, not a substitute independent vote.
- No alternative-runtime validator or differential harness exists yet. The
  contract now makes this a prerequisite for future authority rather than a
  claim about current implementation.
- The Markdown/HTML/PDF/DOCX/text/ordinary-JSON AI normalizer remains the next
  milestone and correctly fails closed here.

## Final synthesis

There is no unresolved evidence-backed BLOCKER. The only concrete independent
code finding was accepted, fixed, mechanically pinned, and re-reviewed PASS on
the final fingerprint. Arkcli failures are recorded rather than hidden or
promoted. The complete regression is green, the architecture checkpoint names
the correct owners and transitional boundary, and the Codex-authored P1-1/P1-2
candidate may proceed to commit.
