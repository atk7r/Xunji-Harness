# Same-target lifecycle recovery independent review

Verdict: PASS
reviewed_diff: 0113b8c3814ef296

- Date: 2026-07-31
- Reviewer: fresh-context Claude Code `2.1.201`
- Model: configured `deepseek-v4-flash[1m]`
- Session: `ec494403-8f4b-4e7b-bac3-b3c4e3176af1`
- Tools: disabled (`--tools ""`)
- arkcli: not used, per operator instruction
- Prompt SHA-256: `35aa32e11afe2bb34399a3c5210977db99c373d4be7cf5fdbd32d490d1a711d9`
- Raw result SHA-256: `b15b08beb416925f0c5bf50ad7b26902e4bc2624e0b5280bd05c14d94c4b8df6`

The reviewer checked the corrected exact framework diff after Round 1's FAIL.
It found all seven prior findings resolved: same-target claim mint/consume,
narrow legacy binding-only compatibility, cross-origin original receipt proof,
the three modern post-bind alternatives, same-target activation/candidate/cross-
effect fail-closed behavior, typed missing-claim errors, cross-layer regressions,
and truthful docs/migration scope. It reported no blocker and no required source
change.

Non-blocking observations retained for synthesis:

- cross-target activation without a Hook claim still has the pre-existing direct
  local-CLI contract-transfer compatibility path; normal Hook cross-target create
  is receipt-bound and covered, while this patch intentionally fixes the
  same-target false-success shape
- pre-effect-profile binding-only receipts require `run_name` and authorize only
  their frozen historical turn; they do not gain modern fresh-effect authority
- unexpected validator exception types hard-deny rather than rendering the
  friendly `XUNJI_E_NEW_RUN_SETUP_REQUIRED` message

Full Round 1/2 raw results and disposition are stored under
`review/records/2026-07-31-same-target-recovery-review/`. Codex authored the patch
and did not count as its own independent reviewer.
