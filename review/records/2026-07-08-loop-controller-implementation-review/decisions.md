# Decisions

## D-001 Post-Fix Evidence Strength

- Decision: Treat the loop/controller artifacts as maintenance candidate evidence, not confirmed vulnerability findings or confirmed real-target yield.
- Rationale: The supporting artifacts are local diffs, selftests, source audits, bundle review, and no-write smoke checks with certainty 0.3-0.5.
- Consequence: `report.md` Driver Answers are bounded to covered code paths and exercised regressions.

## D-002 Post-Fix Reviewer Blocker

- Decision: Accept the post-fix PR-001 BLOCKER and change categorical Yes/No answers into bounded maintenance-review conclusions.
- Rationale: The evidence ledger contains no confirmed entries, so categorical claims overstated what the review bundle could prove.
- Consequence: The follow-up rerun reached WARN with no BLOCKER.

## D-003 Adjacent Optimization Scope

- Decision: Keep the adjacent Agent Board, threat-hypothesis, `js_inventory`, and benchmark canary changes in the same maintenance commit.
- Rationale: They are part of the same autonomous discovery control-plane improvement, but they are not proof of higher real-target finding yield.
- Consequence: The report now calls out this adjacent scope explicitly.
