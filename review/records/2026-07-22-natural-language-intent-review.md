# Natural-language lifecycle intent review

Verdict: PASS
diff_fingerprint: fff0e5e39255d3a7
reviewed_diff: fff0e5e39255d3a7

- Date: 2026-07-22
- Author and synthesis: Codex
- Independent reviewer: DeepSeek-backed Claude Code, fresh-context CLI
- Final review session: `69844dd2-b2ba-450a-9d66-239e3f6e5c1b`
- Exact reviewed patch SHA-256:
  `c89b95e7ac2b9f9d14525a40859b4ac2cbcd65028592839e70fac188db9f4d01`
- Method: the complete 10-file patch was sent to a no-tools, no-edit review
  context at high effort. No arkcli or Codex self-vote was used.

## Verification supplied and independently checked

- Focused `setup_source.py`、`scope_admission.py`、`turn_contract.py` selftests
  and `py_compile`: PASS.
- Full `python3 tools/selftest_all.py`: PASS 69/69.
- `python3 tools/check_rules.py` and `git diff --check`: PASS.
- Claude Code primary-driver session
  `f558c0d0-09ba-473f-aad9-2f5ebd0ea708` received a no-space natural-language
  loopback setup request, executed the injected exact bootstrap argv, created
  and activated `runs/127-0-0-1_20260722` in an isolated clone, and recorded
  `success=true`、`target_action=false` with zero Agent/Cron and no framework
  mutation.

## Reviewer verdict

The final reviewer returned PASS across natural-language compilation, semantic
URL identity, attached Chinese prose separation, primary-action precedence,
sensitive source handling, scope admission, unchanged hard boundaries,
documentation consistency, and regression coverage. Its exact final line was:

`INDEPENDENT_REVIEW_VERDICT=PASS PATCH_SHA256=c89b95e7ac2b9f9d14525a40859b4ac2cbcd65028592839e70fac188db9f4d01`

## Challenge and driver dispositions

An earlier fresh review session `73d8f900-e2a4-4f46-bee6-0cef0627bda0`
returned PASS with several challenges. They were handled before the final vote:

1. Accepted: the broad BMP CJK range included Yijing symbols. The range was
   narrowed to Extension A plus Unified Ideographs and retested.
2. Accepted as documentation clarification: natural permission questions stay
   read-only, while a literal top-level `/loop` is already an execute command
   and only an actual denial cancels it. Owner docs now match `classify_prompt`.
3. Dismissed with code evidence: the reviewer claimed the scope execution hint
   lacked `--run` and `--reason`. `scope_admission.parse_invocation()` defines
   the executable contract as positional `runs/<name> --assets <hosts>`; the
   operator alias owns `--run/--reason`, and the hook claim already hash-binds
   the reason. A selftest now freezes the correct executable hint and rejects
   accidental alias-shaped argv.
4. Dismissed with regex and test evidence: the mixed Chinese approval plus
   English denial case is already rejected by `DIRECT_ROUTE_HARD_DENIAL_RE`.
   A dedicated mixed-language regression case now proves denial precedence.

## Non-blocking blind spots

- Unusual natural-language word order may not match the bounded v1 scope parser;
  the concise alias remains available and ambiguity fails closed.
- Novel attached-language prefixes outside the recognized Chinese/English set
  may require whitespace; the URL parser still rejects ASCII-host plus common
  CJK attachment rather than authorizing a different IDN target.
- Broader fuzz/property testing of URL/prose combinations would be useful later,
  but is not required for this bug fix and does not weaken current hard gates.

Codex accepts the final PASS after checking the reviewer claims against source,
focused/full tests, and the real Claude-primary runtime receipt.
