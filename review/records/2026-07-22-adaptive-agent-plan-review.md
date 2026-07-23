# Adaptive Agent Plan Independent Review

- Date: 2026-07-22
- Author/driver: Codex
- Synthesis owner: Codex
- Final reviewed candidate SHA-256: `cd74c5329ea1ec6658cee6c57bc807bdebdb0c1c8301fe3c52fd93488ddd51a8`
- Final candidate size: 83,982 bytes
- Final fresh-context Claude bundle SHA-1: `12ab0ac7f38d93fdeec90c9e3c201e62ee305290`
- Final evidence-index SHA-1: `21fffea0c03c97eaa3f3c6c1926f6daae1bdbc23`
- Final verdict: WARN, zero source findings
- Source blockers: none

## Matrix And Scope

The Codex-authored matrix was run against a frozen maintenance bundle whose
`reviewed.diff` control hash matched the candidate. Codex did not count as an
independent vote.

An initial `peer_review.py .` invocation was stopped because repository root was
misclassified as an empty live-run bundle. The valid bundle instead used an
explicit maintenance evidence ledger with the exact diff artifact and a
maintenance-specific review contract.

The arkcli panel returned WARN because `kimi-k2.7-code` timed out twice and GLM
produced partially unparseable/truncated output. Its only structured finding was
that the panel was partial; it produced no supported source finding. The final
fresh-context Claude Code CLI reviewer received the complete 83,982-byte diff,
had tools disabled, used a maintenance-specific rubric, and returned WARN with
zero findings. WARN reflects unchanged-dependency context limits, not an observed
defect in the candidate.

## Blind-Spot Dispositions

### BR-001 — unchanged work-plan validators

The reviewer could not inspect all unchanged implementations of
`normalize_lane`, `validate_plan`, reviewer topology, dependency-cycle, and
same-asset TARGET overlap validation. This is accepted as a reviewer context
limit, not dismissed as irrelevant. The candidate calls those existing owners
rather than cloning or weakening them. Their focused selftests explicitly cover
cycle rejection, one-to-one Reviewer topology, effect validation, and parallel
TARGET overlap; the final full suite passed 69/69.

### BR-002 — replan inheritance

`_remaining_replan_lanes` compares exact lane identity and dependencies against
the transaction-bound prior plan, requires receipt-derived completion, and only
removes inherited predecessors after that proof. Unknown or changed lanes are not
inherited. Proposal basis freshness and the existing replan tests passed. No code
change was made for a hypothetical prefix issue that the actual identity join
does not have.

### BR-003 — stale settlement uniqueness

The stale path delegates to the existing settlement owner and admits only the
unique Reviewer bound to an immutable assignment, lane, transaction plan digest,
and returned result digest. Negative tests cover stale Hunter, unrelated or
mutated Reviewer prompt/type, missing result, duplicate Reviewer, and wrong turn;
the real-driver receipt chain started no stale Hunter and no target action.

### BR-004 — natural-language denial coverage

The new normalization is intentionally bounded to clear action-before-target
denials such as `不访问任何目标`, plus equivalent English forms. Existing tests
also preserve the narrower positive localhost case containing
`不要访问任何非 localhost 目标`; it does not become a global target denial.
Speculating about unenumerated idioms is not evidence for broadening a security
regex, where false positives would also violate ordinary operator intent.

### BR-005 — compatibility command and evidence granularity

`commit-plan` remains an exact, bounded compatibility command that recomputes the
conservative seed and still passes through the authoritative work-plan owner. It
cannot accept arbitrary model lane JSON or bypass scope/effect/transaction
validation. Claude-primary docs and conformance route adaptive work through
`plan` plus `commit-proposal`; the compatibility path therefore does not cap the
new model path or mint weaker authority.

The maintenance bundle intentionally used one content-addressed diff artifact;
runtime validation is separately recorded in
`review/records/2026-07-22-adaptive-agent-plan-e2e.md`. Review-bundle granularity
does not change code correctness or serve as engagement evidence.

## Synthesis

Accept the candidate with WARN transparency. No independent reviewer identified
a concrete source defect or boundary bypass. The remaining notes are explicit
context limits covered by unchanged owner contracts, focused negative tests, the
69/69 suite, and the real Claude primary-driver receipt chain. No finding was
dismissed solely because it was inconvenient, and no partial arkcli result was
reported as a PASS.
