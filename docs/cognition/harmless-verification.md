# Harmless-verification recipes (prove-and-stop, operationalized)

"Prove the vulnerability genuinely exists, without causing damage" is not a slogan — it
has concrete recipes. Below are techniques distilled from real engagements that push a
"suspected" finding to "confirmed / rejected" **without harming anyone**. Core idea:
**expose the flaw through response behavior, without triggering the flaw's harmful effect.**

## Five recipes

1. **A non-existent object in place of a real one.**
   When testing password-reset / change-password endpoints, use an **obviously
   non-existent fake account** — the backend changes nothing for anyone, but the response
   (parameter-validation order, whether it "succeeds", the error code) reveals **whether it
   validates**.
   > Engagement: forgetPwd with a fake account + empty/wrong code → backend returns
   > 4001/500 rather than "success" → proves there is no "empty-code-changes-password"
   > trivial bypass, and no real user's password was ever changed.

2. **Non-production / obviously invalid values.**
   When a field wants a phone / email / amount / target address, use **obviously fake**
   ones (`13800000000`, `example.com`, `0.01`, an unreachable internal IP) — you still see
   the endpoint's behavior, without sending a real SMS, making a real transfer, or really
   reaching anyone.

3. **Read-only probe: prove existence, do not extract data.**
   Unauthenticated access / privilege escalation: prove that "an object/data item that
   should not be reachable **exists**" and stop — do **not** pull its content, do not bulk
   enumerate (database dump is a hard boundary). One object's reachability = proof; the full
   dataset = harm.

4. **Single shot, no loop.**
   Captcha / login / send-type endpoints: a **single** observation of the behavior suffices
   (is the code reflected, is the account enumerable, is there rate limiting). **Never loop**
   — SMS bombing, captcha brute-force, login brute-force are all high-frequency flooding
   (hard boundary). If the final judgment of "is the code logic sound" truly requires many
   attempts → hand it to the operator to assess rate/lockout, then execute under authorization.

5. **Test the logic branch, not the harmful effect.**
   Command injection / RCE: a single `id`/`whoami` echo proving execution is enough — do not
   drop a shell, do not persist, do not pivot. Change-password / change-permission / delete:
   prove "the capability exists" (writable / reachable / role attribute) rather than actually
   changing/deleting.

## Decision boundary (when you must stop and hand to the operator)

The harmless recipes cover the **vast majority of existence proofs**. But the following may
**only be done by the operator, on authorized / own test accounts**:
- real change-password / change-permission / delete (integrity damage, irreversible);
- anything that requires many attempts to judge (brute-force / spraying, hits flooding);
- anything requiring a real user's cooperation (e.g. QR-login hijack needs a human to scan);
- internal-network exploitation / lateral movement beyond the web layer (operator-gated).

These go into the report's "why not pursued deeper" + are delivered as an author-and-handoff
PoC (see `docs/templates/poc-report.md`).

## In one line

**Harmless verification = use fake / invalid / single-shot / read-only inputs and let the
endpoint's own response confess whether the flaw is there — while real destruction, bulk
extraction, looping, and cross-layer work all go to the operator.** Prove what can be proven
harmlessly; for what cannot, honestly mark "unconfirmed + pending operator" — never overstep
or overstate to manufacture a conclusion.
