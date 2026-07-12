# Independent Review

Round 1 completed only the fresh-context Claude vote. Arkcli did not satisfy the
required matrix: Kimi timed out and GLM's useful fail-open finding was recovered from
a parse-error tail. Round 2 produced a valid Kimi vote plus fresh-context Claude;
Kimi identified one BLOCKER and two related WARN items in unknown-destination and
legacy empty-asset enforcement. All were accepted, fixed, and reverified at 57/57.
GLM again failed strict parsing and remains a recorded backend limitation. A final
review then returned WARN with no BLOCKER. Five concrete hardening items were accepted:
current-turn direct-egress approval, non-Bash egress denial, auditable projection
errors, agent-id causal matching without a fixed time window, and explicit schema-v1
migration. Two excerpt/intent findings were dismissed with direct code and test
evidence. Because production code changed, one final current-hash review is pending;
Codex self-review does not count. That review's only BLOCKER was a truncated-bundle
claim that the per-asset merge setter was absent; the setter exists and is now frozen
as a dedicated artifact. Three WARN items were accepted: front mismatch projection,
negated direct-egress wording, and projection-time asset-token revalidation. They are
fixed and reverified at 57/57; one post-fix current-hash review remains pending.
The post-fix panel then had no valid arkcli vote (Kimi timeout, GLM parser failure)
and a fresh-context Claude WARN vote with no BLOCKER. Its one implementation issue,
unguarded `run_model.summary()`, was fixed fail-closed; direct asset-ledger rewriting
was also hardened based on its adversarial prompt. All tests remain 57/57. Arkcli is
now recorded unavailable for this final hash, so the required fallback is one final
fresh-context Claude-only review of the last delta.
The Claude-only fallback completed on bundle `0b06d9b4f8d6be88582cc65227ae74c37f319112`
with `WARN` and `Findings: (none)`. Its remaining notes are non-blocking edge cases or
the already-recorded live-Agent limitation. Independent review is complete for the
current code hash; arkcli unavailability remains explicit and is not counted as PASS.
