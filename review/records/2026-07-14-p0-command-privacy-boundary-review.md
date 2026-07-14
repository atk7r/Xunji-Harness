# P0 Command And Privacy Boundary Review

- Verdict: PASS WITH RECORDED BACKEND LIMITATION
- diff_fingerprint: c6a0a0ce982d3360
- reviewed_diff: c6a0a0ce982d3360
- Author and final synthesis: Codex
- Scope: the staged P0-1 framework diff for exact local-control parsing,
  URL-bearing compound-command rejection, outbound privacy enforcement, and
  mandatory model-egress redaction.

## Independent review matrix

The frozen final diff was reviewed under the Codex-authored maintenance matrix.

- arkcli panel, final diff fingerprint `c6a0a0ce982d3360`, bundle
  `c71c9992e8e6e6612ce2d7d39a71ccfc30f01f81`: one independent model completed
  with verdict `WARN`; the second model returned a parse error. Its candidate
  findings were about review-context truncation, aggregate verification detail,
  and the intentionally pending repository review record, not a demonstrated
  implementation bypass.
- arkcli focused rerun, bundle
  `b3456bb5c327f12950a1aed577987a1713b8b028`: three full focused diff artifacts
  were added so the relevant hunks were directly inspectable. The rerun did not
  produce an independent vote because one model timed out after 240 seconds and
  the second again returned a parse error. This is a recorded backend limitation;
  it is not converted into a PASS.
- Claude Code fresh-context, final focused bundle
  `b3456bb5c327f12950a1aed577987a1713b8b028`: verdict `WARN`, findings none. The
  first attempt timed out and the isolated retry completed. Claude had no tools,
  no repository working directory, and received only the hard-redacted frozen
  bundle.

The review scope and raw independent outputs are retained outside the repository
at `/tmp/xunji-p0-command-privacy-review/` for this local maintenance session.

## Driver dispositions

1. arkcli context-truncation findings: accepted as a review-package quality gap,
   then resolved by adding full `privacy-focus.diff`, `command-focus.diff`, and
   `peer-review-focus.diff` artifacts. No production code changed after the final
   fingerprint was frozen.
2. arkcli aggregate-test-evidence warning: partially accepted. The final project
   regression is recorded below, and the frozen focused diffs contain the
   data-driven fixtures and selftests that exercise the claimed boundaries.
3. arkcli missing-review-record warning: resolved by this record. The earlier
   `Independent review pending` text described the review while it was in
   progress; it was not treated as closure evidence.
4. arkcli quantified whitelist/model-redaction warnings: dismissed as
   context-limit findings after the focused artifacts exposed the complete
   `turn_contract.py`, `privacy.py`, and `peer_review.py` hunks. The focused
   rerun's backend failure is retained above rather than hidden.
5. Claude blind spot about broad `$` rejection: accepted as intentional
   fail-closed behavior. A bare `$` must remain rejected because it covers
   variable, command, parameter, and ANSI-C-style shell expansion families.
6. Claude observations about absolute-path matching, duplicate `--target`, and
   folded authorization headers: verified as safe failure behavior. The fixture
   rejects absolute and parent-relative custom senders; the exact setup parser
   rejects duplicate target flags; folded header continuation lines are redacted.
7. Pre-freeze review blind spots found two real gaps: absolute/parent-relative
   custom executables and folded authorization continuation lines. Both were
   fixed, fixture-tested, restaged, and are included in the final fingerprint.

## Verification

- `python3 tools/selftest_all.py`: PASS, 61 passed and 0 failed in 88.2 seconds.
- `python3 tools/harness/command_shape.py`: PASS.
- `python3 tools/harness/privacy.py`: PASS.
- `python3 .claude/hooks/safety_gate.py --selftest`: PASS.
- `python3 tools/check_hook.py`: PASS.
- `python3 tools/peer_review.py --selftest`: PASS, 76 checks.
- `python3 tools/check_rules.py`: PASS.
- `git diff --cached --check`: PASS before this review record was staged.

## Synthesis

The final diff preserves the unknown-target guard and narrows only the local
metadata channel to one exact `setup_run.py` invocation shape. URL-bearing shell
control, redirection, expansion, custom network senders, secrets, userinfo, and
sensitive query data fail closed. Model-review redaction cannot be disabled by
configuration. No unresolved independent-review finding demonstrates a bypass in
the frozen implementation. The incomplete arkcli focused rerun remains an
explicit availability/context limitation.
