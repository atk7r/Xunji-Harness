# Direct-default route and proxy-confirmation recovery review

Verdict: WARN
diff_fingerprint: 7005fb9a16676ee9
reviewed_diff: 7005fb9a16676ee9

Date: 2026-08-10
Author/synthesizer: Codex
Independent reviewer: fresh-context Claude Code, no tools
Final disposition: ACCEPTED WITH RECORDED LIMITATIONS

## Scope and decision

This maintenance change replaces proxy-default target egress with a typed,
direct-default route. Proxy is selected only by an affirmative current operator
turn. Explicit proxy failure stops automatic retry and requires a newer operator
turn before another proxy attempt. Local settlement/control text remains local
data even when it mentions `XUNJI_PROXY_REQUIRED=0`.

The behavior is accepted after independent review found and the author fixed
multiple route-language and selector gaps. The final fresh-context vote is WARN
with no concrete outbound fail-open. Its remaining warning is an intentional
fail-closed availability tradeoff: an unrelated negative clause after an explicit
proxy vote can freeze the route offline and require a clearer operator turn.

## Mechanical verification

- Python compilation: PASS for proxy, guard, turn contract, context pack, probe,
  render, scan, CDN comparison, and capability registry modules.
- Focused matrix: proxy, guard, context pack, probe, render, scan, capability
  registry, Hook, command-shape, and template checks PASS. `turn_contract` has
  only the seven SessionEnd assertions listed under limitations; all proxy/route
  assertions PASS.
- Exact-final sanitized-public-tree matrix: 67 passed, 3 failed in 120.5 seconds.
  Failing suites:
  `setup_transaction`, `turn_contract`, `xunji_statusline`.
- Registered-target coverage: all 11 target-capability scripts are exactly the
  same 11 scripts in `PROXY_AWARE_TARGET_TOOLS`; neither side has an uncovered
  member.
- `git diff --check`: PASS.

## Claude-primary real-driver verification

Isolated sanitized public candidate, DeepSeek-backed Claude Code session
`4dee08bd-25db-41ff-b3ac-c109d6e288f8`:

- the real transcript contains one tool use only, exact argv
  `python3 tools/turn_contract.py --selftest`;
- the Hook admitted that command; turn contract returned nonzero only for the
  same seven SessionEnd assertions;
- negated proxy language cannot mint authority, exact selector binding,
  route-less legacy offline behavior, newer-turn-only proxy recovery, and attached
  natural-language proxy route compilation all passed;
- no file edit, target/network request, run transition, Agent, or Cron action.

## Independent review and dispositions

External assistance was disabled by local policy, so the Codex-author matrix used
fresh-context, no-tools Claude Code only. The first exact tracked-diff review
(`3d60c5d7-84aa-4a93-b115-c9d19a4588dc`) returned BLOCKER for negated proxy
phrases and `--proxy=URL`. Targeted reruns then identified residual negation,
post-clause retraction, direct/proxy conflict, invalid-capability selector, and
direct-denial cases. Each was reproduced and converted into a regression before
the next review; attempts that exhausted model output/budget produced no verdict
and were not counted.

The final exact-current route compiler/gate review
(`b198b6b8-6e1a-4d9a-9a20-1883e26e460b`) returned WARN with no concrete outbound
fail-open. Final dispositions:

1. Proxy authority now requires a full affirmative clause. Explicit proxy denial,
   pre-vote ambiguity, post-vote retraction/non-affirmative proxy text, and any
   direct/proxy conflict freeze `offline`; no vote defaults to direct.
2. Direct tokens and denials are structural rather than a verb allowlist. Both
   `--proxy URL` and `--proxy=URL`, duplicate/mixed env sources, offline mode, and
   direct/proxy env inversion are checked in typed and invalid-capability paths.
3. The selected proxy route alone scopes pause observation and confirmation; all
   11 registered target scripts are covered by the route-aware set.
4. The accepted WARN is conservative offline overmatching after a proxy vote.
   It can require the operator to restate the route, but cannot start target I/O.

## Known unrelated limitations

The exact-final matrix still has these existing SessionEnd/session-selection
failures, outside the proxy route surface:

- `setup_transaction` suite failure family;
- seven `turn_contract` SessionEnd assertions;
- two `xunji_statusline` SessionEnd/resume-selection assertions.

No live target validation was performed. The result proves framework behavior
through deterministic selftests and an isolated primary-driver path; it is not
evidence about any live target or proxy endpoint.
