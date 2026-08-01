# Hints

> Conditional artifact — operator steering injected at runtime. Create or append
> when the operator gives direction (in chat or otherwise); a run with no operator
> steering does not need it. The point is to move operator judgement OUT of
> ephemeral chat INTO the run's audit trail, where it is re-read every cycle and
> cannot be forgotten under momentum.
>
> Discipline:
> - Re-read this file every cycle (part of the Reason pass). A `pending` hint is
>   operator steering not yet acted on — do not let it rot.
> - Absorb by `Kind`:
>   - **directive** (do / skip / prioritize / open / close a front) — controlling:
>     act on it. An operator instruction overrides the soft constraints; it never
>     overrides the hard `.claude/hooks/` boundary.
>   - **lead / claim** about the target ("X looks injectable") — a lead (<= 0.5),
>     NOT a Fact. Verify through the evidence gate; operator suspicion is not
>     evidence (this is where Xunji stays stricter than a raw human-hint absorb).
>   - **constraint** ("skip brute-force", "don't touch prod data") — a soft rule
>     the operator set for this run; honour it until they lift it.
> - When you act on a hint, set `Status: absorbed` and link the decision / front /
>   hypothesis it fed (or record why it was declined).

## HINT-001

- Time:
- From: operator
- Kind: directive / lead / constraint
- Hint:                       # the steering, verbatim where the wording matters
- Status: pending / absorbed
- Absorbed by:                # D-xxx that acted on it, the front/hypothesis it opened, or why declined
