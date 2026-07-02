# Chains

> Conditional artifact — create this file only when one confirmed finding's
> proven output state satisfies another finding's precondition (vulnerability
> combination / 组合利用). A chain-free run does not need it.
>
> Rules (see `docs/cognition/README.md` "Vulnerability Chains"):
> - A chain is only as strong as its weakest hop: every hop must be a confirmed
>   evidence item (certainty >= 0.8), or the whole chain is `suspected`.
> - Prove the chain reaches the sensitive terminal STATE, then stop — do not run
>   the destructive final action.
> - Default: prove an SSRF / RCE hop by reachability. Pivoting into the host or
>   internal network is operator-gated (ask first), not a boundary violation; the
>   destructive final action and 拖库 remain hard rules.

## C-001

- Goal state:                # what the composed chain demonstrates (e.g. account takeover)
- Hops (ordered):
  - Hop 1: <H-/E- ids> — proves: <state unlocked> — certainty:
  - Hop 2: <H-/E- ids> — precondition met by Hop 1 — proves: — certainty:
- Weakest hop certainty:     # the chain's confirmation gate; < 0.8 => chain is suspected only
- Terminal node:             # proven state that ENDS the chain (e.g. RCE proven / admin reached)
- Composite severity:        # usually higher than any single hop alone
- Status: open / confirmed / rejected
