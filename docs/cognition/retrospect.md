# Retrospect Notes

Record false positives, retreats, and confirmation failures. Each retrospective should answer:

- What the hypothesis was at the time.
- Which link in the evidence chain was missing.
- Which signal came from a controlled action, and which signal might come from the
  environment itself.
- Whether the Verifier should return `needs_more_evidence`, `rejected`, or
  `confirmed_candidate`.
- What the smallest safe next action is.

Experience that succeeds and is stably reusable can be collected into
`docs/cognition/cases/`, then a human decides whether it enters long-term memory.
