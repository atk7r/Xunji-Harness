# P0-3 Live Framework-Maintenance Authority Review

- Date: 2026-07-15
- Verdict: WARN WITH RECORDED REVIEW-MATRIX AND TRUST-BOUNDARY LIMITATIONS
- diff_fingerprint: cc7b654fc09be6f0
- reviewed_diff: cc7b654fc09be6f0
- Base commit: `a9772145f4d38e9a5d27abad293a7624ce66979b`
- Author/driver and final synthesis: Codex; Codex self-review is not counted as
  an independent vote.
- Scope: 14 staged P0-3 files implementing deterministic live framework
  maintenance authority, positive live Bash capabilities, exact-path writes,
  denied/failed-action receipts, output truth gating, manifest/rule coverage,
  and the matching architecture/workflow contract.

## Final verification identity

The final staged framework fingerprint is `cc7b654fc09be6f0`. No production or
documentation file changed after the full regression and final review freeze.

- `python3 tools/selftest_all.py`: **63 passed, 0 failed (89.3s)**.
- Raw full-suite log SHA-256:
  `4de0c775fbe900986e286cce3d7012940ef9e9eb0744b3afd43a6690c761de1c`.
- Focused parser, turn-contract, receipt, output-gate, rule, hook, py_compile,
  and staged diff-format checks passed.
- Full turn-contract staged diff SHA-256:
  `f38c0fcb5f1a25788934673ea9d020e06e663815c2c34d9c178694d29d6b9635`.
- Six-file architecture/workflow documentation diff SHA-256:
  `bdd5eb11310729f583f6baac368e856f4e011855bcb1e302e47b78dab54c3f5b`.

These are controlled local observations, not independent reviewer votes. The
suite log was produced after all 14 files were staged; the fingerprint above was
recomputed afterward and remained unchanged through final review.

## Independent review chronology

### Round 1 — initial hardening candidate

- Candidate fingerprint: `692472f2de1f57b6`.
- Result: WARN, no BLOCKER.
- Accepted fixes: deny maintenance Bash tool-environment overrides; require
  `--no-ext-diff --no-textconv` for Git diff/show/log; treat every other
  Git/patch shape as opaque mutation; recognize alternate path-key spellings;
  add control-byte path negatives; preserve raw regression output at controlled
  certainty.

### Round 2 — pre-capability candidate

- Candidate fingerprint: `0ea8cc4eb9654ad2`.
- Frozen bundle: `5bcc8edfb670073ec6458a2126e74c234c320721`.
- Evidence index: `0af9d22ec0c96ee9a6caa8f911fd3837a0d9fe11`.
- Result: **BLOCKER**.

The blocker showed that ordinary-loop read-only Git still accepted tool-level
`GIT_EXTERNAL_DIFF`/`GIT_PAGER`. A related WARN showed that a generic interpreter
could compute an encoded critical path without exposing it to path scanning.
Both were accepted as one authority-design defect and fixed by making all active
ordinary Bash a positive capability allowlist. Unknown shell/interpreter
programs are now denied regardless of visible path text; read/control/check and
trusted target/review capabilities have explicit environment rules. Negative
tests cover Git helper injection, base64 path decoding, and inline
`PYTHONPATH` injection.

### Round 3 — final frozen candidate

- Final fingerprint: `cc7b654fc09be6f0`.
- Bundle: `8fbd7825c80501f4d97689001a47caf12dc4d839`.
- Evidence index: `0f83646dfef26822719aae7636352e439c2a4915`.
- Panel JSON SHA-256:
  `a1b12fdd1d79603445522750fd1cef72c9d196271e6990fd29c6d2ea45a0e62d`.
- Result: **WARN, no BLOCKER**.
- Independent coverage: arkcli Kimi completed after one timeout/retry; Claude
  Code fresh-context completed and explicitly reported no BLOCKER. arkcli GLM
  returned an unparseable response and is not counted as a vote.

The frozen scope and raw panel Markdown/JSON are retained for this maintenance
session at
`/tmp/xunji-p0-live-maintenance-review-cc7b654fc09be6f0/`.

## Final finding dispositions

### PR-001 — `parse_exact_python_command` was not visible in the diff bundle

Status: **accepted as a review-context warning; no code defect demonstrated**.

The parser is an unchanged transitive dependency, so it has no staged diff to
include. It is protected by both the compiled/JSON critical-path floor and the
manifest parity rule. Direct source inspection confirms that it:

- rejects unquoted `;`, `&&`, pipes, redirects, comments, substitutions,
  newlines, unmatched quotes, and expansion syntax before `shlex` parsing;
- parses exactly one Python argv and resolves the proposed script;
- allows it only when the resolved path equals a member of `allowed_scripts`.

Existing command-shape fixtures cover chaining, pipe, subshell, command and
backtick substitution, redirection, and custom scripts. A final direct control
check returned DENY for `python -c`, `python -m`, shell chaining, and a
parent-relative untrusted script. A normalized `tools/../tools/probe.py` alias
resolved to the exact registered `probe.py` capability and was allowed; this is
path normalization to the trusted script, not an escape. The staged turn-contract
tests separately exercise an encoded `python -c` write and unknown live Bash.

### PR-002 — claimed heavy artifact excerpt truncation

Status: **dismissed as factually contradicted by the frozen bundle**.

`review_bundle.json` has `warnings: []`, retains the requested per-artifact
excerpt cap of 24,000 characters, and records no `excerpt_truncated_chars` for
any E-001 through E-007 artifact. Each referenced code diff is smaller than the
per-artifact cap and is present in full after required egress redaction. The WARN
mistook a per-file maximum for evidence that every file was truncated. The six
documentation files are intentionally disclosed as fingerprint-bound but outside
the narrow model bundle; they cannot introduce an executable bypass, and their
contract parity is covered by rule checks and the full suite.

### PR-003 — selftest observation is not itself fingerprint proof

Status: **accepted as an evidence limitation and correctly calibrated**.

E-007 already uses certainty 0.8 and calls the suite a controlled observation,
not an independent vote. This record binds the unchanged final fingerprint, raw
log SHA-256, full diff hashes, and review bundle. It does not promote local tests
into independent confirmation.

### PR-004 — first-line operator provenance

Status: **accepted residual trust boundary**.

Only Claude Code's top-level `UserPromptSubmit.prompt` first non-empty line may
mint authority. Attachments and later source/tool/target/reviewer text do not.
If an operator or upstream UI copies attacker-controlled bytes into that exact
operator authority position, the hook cannot recover their semantic provenance.
This limitation is disclosed in architecture/workflow docs and is not described
as technically solved.

### PR-005 — partial arkcli panel

Status: **accepted backend limitation**.

Kimi and Claude fresh-context completed; GLM parsing failed. The missing GLM vote
is not converted into PASS. The final verdict therefore remains WARN even though
neither completed independent reviewer found a blocker.

## Blind-spot synthesis

- Claude Code's current direct write tool names are the five names wired into
  settings and `WRITE_TOOLS`. Hypothetical future `ApplyPatch` or
  `NotebookCreate` tools are not current Claude Code capabilities; adding one
  must update hook matchers, receipts, and rules in the same maintenance change.
- Trusted target environment keys are data passed to fixed registered scripts,
  not shell names. Direct-egress opt-out remains bound to current operator
  approval by the existing proxy boundary. Value-sensitive behavior remains a
  trusted target-entrypoint concern, not authority for an unknown program.
- Read-only Git may expose committed repository content to the local model. That
  is expected local read authority, not target/model egress; external review
  still passes through the redaction bundle.
- Treating unknown Git/patch commands as mutation may reject harmless commands
  such as `git --version`; this is intentional fail-closed friction.
- The Claude-noted maintenance-action classification mismatch is over-inclusive
  receipt tracking, not an execution allow bypass.
- OS-level races, a process with pre-existing arbitrary filesystem authority,
  and first-line UI provenance remain outside complete hook mediation. Current
  critical paths are ASCII enumerated paths, so the Unicode-normalization blind
  spot does not identify a concrete critical-path bypass.

## Final synthesis

The original ordinary-loop bypass was repaired at the capability boundary, not
with more path-string heuristics. The final fingerprint passed focused and full
regression and received the required arkcli plus Claude fresh-context review.
There is no unresolved independent-review BLOCKER. Residual provenance,
OS-mediation, local-test, and backend-availability limitations are explicit, so
this Codex-authored safety-critical maintenance diff may proceed with verdict
WARN rather than being mislabeled PASS.
