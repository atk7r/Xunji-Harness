# Frozen Artifact Reference Recovery Review

Verdict: PASS

reviewed_diff: 4ad8f6e2d1bf5359

- Date: 2026-08-01
- Author/synthesizer: Codex
- Independent reviewer: fresh-context Claude Code / DeepSeek
- Final review session: `68feb68b-439d-41b4-9b12-bb09ac8bf315`
- Review boundary: operator explicitly required no arkcli. The independent vote is
  therefore Claude-only; the missing heterogeneous arkcli panel is a recorded
  limitation, not a substituted Codex self-review.

## Reviewed scope

- `tools/workers.py`
- `.claude/agents/xunji-hunter.md`
- `.claude/agents/xunji-reviewer.md`
- `docs/templates/agents/web-hunter.md`
- `docs/templates/agents/review.md`
- `docs/WORKFLOW-reference.md`
- the 2026-08-01 checkpoint and artifact-contract hunk in `docs/ARCHITECTURE.md`

The staged patch is byte-identical to the isolated candidate diff (SHA-256
`4ad8f6e2d1bf5359a88c576f840ccae7b9c4aa384fa286db7fb65e5a53eb3cd4`).
Unrelated dirty and untracked worktree material is excluded.

## Root cause and repair

The prior interrupted-Reviewer-Start recovery was not the failing path. Hunter
and Reviewer had both returned and their bytes were durably frozen. The later
target `accept-candidate` gate could parse only complete `evidence/...` paths,
while three immutable Hunter/Reviewer pairs used different compressed artifact
shapes. The strict identical-set gate consequently saw 0/1, 1/7, and 5/5 body
references and could not settle the lanes.

The repair keeps exact set equality, evidence-directory containment, file
existence, and replay wire/saved-body validation intact. It adds a narrow,
artifact-block-scoped compatibility grammar for exact directory anchors plus
safe basenames, exact-run-bound ellipses, affirmative replay pairing, and unique
Reviewer stems. Negative/excluded/absent declarations do not contribute refs;
paths and tokens are masked before semantic negation checks; contradictory pair
declarations fail closed; blank-line block boundaries prevent later commentary
from changing the set. New Hunter/Reviewer instructions require complete body
and sidecar paths and do not authorize compatibility shorthand.

## Verification

- Isolated exact candidate: `python3 tools/selftest_all.py` — 69 passed, 0 failed.
- Isolated exact candidate: `python3 tools/bench.py --selftest` — passed, including
  the checked-in 18/18 clean benchmark assertions.
- Focused workers/templates, rules, syntax, and `git diff --check` — passed.
- Final Claude primary-driver session
  `fa3cde7d-54b8-42b5-ade2-34ff3c696848` ran the focused/rules/diff checks through
  real Hooks. One compound command was denied by exact-argv enforcement and the
  driver recovered with the registered bare command. Transcript inspection found
  no Edit/Write, Agent, run creation/activation, target request, or active-pointer
  effect.
- Read-only application to the immutable live pairs remains exact:
  A-web-hunter/A-review-004 = 24 refs / 12 replay sidecars; 005 = 14/7; 006 =
  10/5. No live assignment, draft, receipt, pointer, evidence ledger, or closure
  state was written.

## Independent review history and dispositions

- Two `tools/peer_review.py --backend claude` attempts returned ERROR without a
  verdict and were not counted.
- Session `86291700-a639-48a2-a410-bc9722247a3d` returned WARN. Its valid findings
  (ordinary prose alias collision, negated replay mention, ambiguous stems, and
  compatibility-document wording) were repaired and regression-tested. Its claim
  that current-run non-evidence prose matched the evidence regex was disproved by
  a direct test and retained as a rejected finding.
- Session `8457bf12-7a60-419b-9b88-f4437778fc83` returned WARN. Negated stem,
  ellipsis, directory basename, later pair contradiction, exact-run binding,
  absent sidecar, cross-run, and non-artifact-section cases were added or tightened.
- Session `5503eb21-be0a-4deb-aaae-6bd3c7f182b5` returned non-blocking WARN. Its
  real lexical false-rejection and per-line-pair observations were repaired by
  token/path masking, semantic negation, declaration-line stem restriction, and
  generalized pair contradiction tests.
- Session `c89ce606-0df5-48e8-8be4-d66da955c409` exceeded the CLI output limit
  before producing a verdict and was not counted.
- Final tools-disabled, no-edit session
  `68feb68b-439d-41b4-9b12-bb09ac8bf315` reviewed the complete exact diff and
  returned `Verdict: PASS`, `Blocking findings: none`. It confirmed every prior
  WARN disposition. Its remaining observations are non-blocking fail-closed or
  contrived compatibility edges: an all-negated empty block, annotations such as
  `404 not found`, and the absence of checked-in copies of the real 004..006 bytes.
  These do not weaken exact-set, containment, file, or replay integrity gates and
  were explicitly judged not to require reopening this change.

## Closure decision

PASS for this maintenance patch. It repairs the authoritative disposition path,
does not mutate the live run, preserves fail-closed evidence admission, and has
an exact fingerprint-bound independent review. Runtime settlement of the three
live lanes remains a separate operator-authorized EXECUTE action after this
framework commit.
