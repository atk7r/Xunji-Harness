# Decisions

## D-001 - Maintenance review scope

- Status: REVIEW_ONLY
- Decision: This scope reviews closure enforcement code; it is not a live engagement closure.
- Completion marker: absent by design
- Required exit: independent review of the frozen bundle plus full regression
- Migration: prose-only reviews from older runs intentionally become stale and
  must be regenerated through the current foreground `peer_review.py --into-run`
  receipt path; they are not silently grandfathered.
