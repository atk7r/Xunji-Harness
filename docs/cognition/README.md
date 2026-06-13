# Cognition Notes

These notes are judgment discipline for the autonomous Claude Code driver. They
are not an execution framework, exploit cookbook, payload library, or
multi-agent orchestration design.

## Why This Exists

Past false positives came from the same root problem: a signal was treated as a
conclusion too early.

- A length difference was treated as a content difference.
- A real but blocked weakness was treated as exploitable impact.
- A successful login was treated as authorized asset ownership.
- Page-native behavior was treated as evidence caused by the test.

The fix is not more methodology. The fix is better attribution and stricter
confirmation.

## Dual Mind

The project keeps one autonomous driver with two internal phases:

- Red-team phase: expand the search space, do not stop at the first blocker,
  and ask whether separate clues can form a verifiable risk.
- Hunter phase: distrust every early conclusion, attribute the signal, check
  benign explanations, and refuse confirmation when evidence is thin.

These phases are not two agents and do not imply orchestration. They are a
thinking discipline for one driver.

## Grounding and Variant Analysis

The dominant failure mode of LLMs in security work is hallucination — inventing
a vulnerability that does not exist. The defense is grounding: anchor every
hypothesis in an observed fact, not in speculation.

- Prefer hypotheses anchored in something you actually observed — a banner,
  response behavior, an identified product or version, a real error — over
  open-ended guesses. Treat a purely speculative hypothesis as lower priority
  until an observation grounds it.
- Variant analysis beats open-ended hunting. Once a concrete technology,
  product, or version is identified, reasoning about its known weak points and
  recently-patched-vulnerability variants is far more tractable than guessing in
  the open. A known starting point removes ambiguity and is where current models
  are strongest. (This is knowledge-and-reasoning, not a payload library or a
  fixed checklist — derive the specific check from the specific technology.)
- Keep reasoning tied to observable behavior. When a step's result is ambiguous,
  get one more grounding observation before believing it, rather than reasoning
  further on an unverified premise.

## Evidence Confidence

| Certainty | Meaning | Allowed conclusion |
| --- | --- | --- |
| `1.0` | Direct, reproducible, boundary-clear evidence. | Confirmed. |
| `0.8` | Stable controlled difference with enough comparison or replay. | Confirmed. |
| `0.5` | Suspicious signal without enough baseline, replay, or impact. | Suspected. |
| `0.3` | Page clue, one-sided observation, inference, timeout, redirect, block page, or environmental noise. | Not confirmed. |

The default confirmation threshold is `certainty >= 0.8`.

## Vulnerability Chains

Web-layer findings often combine (组合利用): one confirmed finding's proven
output state satisfies another finding's precondition. Chaining is first-class —
it is how low-severity atoms compose into a high-impact finding — but it carries
its own discipline:

- Weakest-hop gate: a chain is only as strong as its weakest hop. Every hop must
  be a confirmed evidence item (`certainty >= 0.8`); if any hop is merely
  suspected, the whole chain is suspected, not confirmed.
- Terminal proof node: a high-impact proven state (RCE proven, admin reached)
  ENDS the chain for proof purposes. Record it. The destructive final action and
  data exfiltration / 拖库 are hard rules — never. Going further (persistence, a
  webshell, pivoting) is operator-gated — only with the operator's consent.
- Default: prove an SSRF / RCE hop by reachability to the target state. Pivoting
  from it into the host or internal network is operator-gated (ask the operator
  first), not a boundary violation.
- Record edges in `chains.md`; the atoms still report individually. Composite
  severity is usually higher than any single hop alone.

## Attribution Checks

Before treating a signal as proof, answer:

- Was this caused by the current verification action?
- Did the page or environment already contain this signal?
- Is there a normal explanation such as encoding, reflection, dynamic content,
  caching, access control, gateway behavior, or test data?
- Could the vulnerable-looking response be deceptive — a honeypot, instrumented
  decoy, or gateway stub that presents a convincing weakness it does not
  actually have? A single convincing observation cannot rule this out; require
  controlled replay or a second independent signal before confirming.
- Is the asset definitely in scope and owned by the target program?
- Is the weakness merely present, or is impact actually demonstrated?

If the answer is unclear, keep the finding as suspected and record the missing
evidence in the run ledger.

## Stop / Continue

Blocked does not mean finished. Classify the stop:

- Type A: a tool, context, permission, or evidence gap caused the failure. Try
  one smaller safe verification step.
- Type B: the route has been sufficiently explored and more work would only
  consume context. Stop or record the dead end.

Confirmed findings stop at proof. Target exploration should not stop just
because the first path failed.

## Wrong-Depth Smells

Shallow work is not the only failure. The opposite failure is wrong-depth work:
the agent keeps pushing one attractive front after the barrier is already
classified.

Watch for these signs:

- It tries many variants against the same routing, WAF, auth, or network
  barrier without new evidence.
- It labels the first block as Type A and never re-evaluates after repeated
  failures.
- It stays on one technology stack because it looks high value, while other
  safe open fronts are ignored.
- It treats remembered variant ideas as progress even when the barrier class is
  unchanged.
- It does not write the material difference between the next attempt and the
  previous failed attempts.

Correction:

- classify the barrier
- update the failure budget
- trigger Reviewer Mode
- pivot unless the next step has a material difference and a clear evidence
  expectation

## Shallow Work Smells

Watch for these signs that the agent is not digging deeply enough:

- It summarizes the target before maintaining open fronts.
- It asks the user what vulnerability class to test next while safe fronts are
  still open.
- It expands assets but does not pick a high-value front to pursue.
- It treats first-pass banner, version, or page observations as sufficient.
- It stops after WAF, login, CAS, redirect, or missing credentials without Type
  A/B reasoning.
- It records a suspicious signal but never defines what would confirm or reject
  it.
- It writes a report before `frontier.md`, `hypotheses.md`, `evidence.md`, and
  `false_positive.md` agree.

The correction is not a fixed checklist. The correction is to update
`frontier.md`, choose the next front autonomously, and record the choice in
`decisions.md`.

## What Not To Absorb

Do not import:

- exploit playbooks
- payload expansion
- multi-agent attack orchestration
- arbitrary shell, arbitrary HTTP, or unrestricted browser control as project
  primitives
- destructive verification
- model confidence as a replacement for cited evidence

What can be absorbed is judgment discipline: discovery/verification separation,
evidence grading, failure classification, and resistance to environment-induced
false beliefs.

## Grounding Knowledge Is Not a Weapon

The project itself is a weapon, and authored, target-specific weaponization is
free (see "gate effects, not methods"). This section scopes something narrower:
the **grounding knowledge base and the framework architecture** must stay grounding
+ reasoning — they must not be turned into target-agnostic weapons / automation.
Those are different things and must not be conflated:

- Allowed (grounding): recognition signatures for a technology, its known
  weak-point anchors, CVE / CNVD references, and verification notes — the
  variant-analysis input that frontier work relies on. A reasoning driver
  consults it contextually after it has identified the technology.
- Forbidden HERE (target-agnostic weapons / automation baked into knowledge or
  framework): exploit playbooks, payload libraries, scanner wrappers, a JSON
  orchestrator, and mechanical fixed checklists that run regardless of the
  target. (Target-SPECIFIC authored exploitation is free — it lives in
  `poc_library/` and the driver's authored code, not in `knowledge/`.)

The test: does the artifact carry knowledge a reasoning driver looks up for a
specific identified target (allowed), or does it carry weapons / steps that
execute the same way regardless of target (forbidden)? Grounding knowledge makes
reasoning sharper; it must never become a checklist the driver runs blindly.
