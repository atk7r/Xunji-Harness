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
- The grounding base **is** where those weak-point anchors live — consult it on a
  fingerprint hit, don't re-derive a known stack from memory. After an observation
  grounds a product (you recognized the stack while attacking it, or `classify_hosts`
  tagged it `kb:<id>`), Root freezes the exact saved artifact and matching local
  `knowledge/*.md` path into Agent context; the Agent uses built-in Read only on
  those paths. Read at most one
  matching local weaponized/xday entry only when the current privacy/model-egress
  boundary permits it. The helper matcher CLIs remain offline developer tools, not
  live capabilities. Consult **after** a recognition match and adapt to the target —
  never pre-load the base and walk it as a checklist (the blind scanner the project
  rejects).
- The flywheel has a **write-back end**, not just a read end. A clearly
  fingerprinted miss is the base's blind spot, but the engagement turn records the
  artifact, proposed ID, and deferred gap only. Curate or seed the entry in a
  separate, explicitly authorized repository-maintenance turn so the next run can
  recognize it. Capture on the miss and fill later; never turn live writeback into
  target evidence or a payload dump.
- **Anchor every hypothesis on the precise vuln-class term**, not a vague description
  ("SQLi" not "fuzz the param", "IDOR" not "broken access", "path traversal" not "read a
  file"): the exact class name localizes the model's knowledge and retrieves the right
  weak-point anchor. The public `_lexicon.md` scaffold carries only generic canonical names;
  product-specific vocabulary and entries stay local. The class must be **justified by an
  observed surface signal** — never fire
  a class the target gives no signal for (that is the blind scanner the project rejects).
- Keep reasoning tied to observable behavior. When a step's result is ambiguous,
  get one more grounding observation before believing it, rather than reasoning
  further on an unverified premise.

## Evidence Confidence

This table is the **canonical** certainty scale for the whole project. Other files
(`CLAUDE.md`, `docs/WORKFLOW.md`, templates) cite the `>= 0.8` threshold but must
not restate or redefine the levels — change them here, in one place.

| Certainty | Meaning | Allowed conclusion |
| --- | --- | --- |
| `1.0` | Direct, reproducible, boundary-clear evidence. | Confirmed. |
| `0.8` | Stable controlled difference with enough comparison or replay. | Confirmed. |
| `0.5` | Suspicious signal without enough baseline, replay, or impact. | Suspected. |
| `0.3` | Page clue, one-sided observation, inference, timeout, redirect, block page, or environmental noise. | Not confirmed. |

The default confirmation threshold is `certainty >= 0.8`.

### Certainty Anchor Examples

These concrete anchors calibrate the four-level scale for the most common Xunji scenarios:

| Scenario | Certainty | Why |
|----------|-----------|-----|
| Single observation / redirect / block page / timeout / environment artifact | 0.3 | Never confirmation on their own |
| Version matches CVE but exploit path NOT verified (no PoC run, no target test) | 0.3 | Phenomenon only — theoretical possibility; AC:H CVEs default here |
| Version matches CVE + exploit PRECONDITIONS confirmed NOT met on target | 0.3 | CVE exists but environment rules it out; report as phenomenon |
| Version matches + exploit path determined (code analysis complete) but NOT run | 0.5 | Candidate — stronger signal, ready to test |
| Version matches + PoC validated locally (off-target) | 0.5 | Candidate — works somewhere, not confirmed here |
| Exploit executed on target + expected behavior observed + control verified | 0.8 | Confirmed — reportable |
| Two independent methods confirm + control verified + artifact cross-check passed | 1.0 | Maximum certainty |

Two discipline rules that apply to ALL entries (learned the hard way — ujs_20260619):

- **Verify before scoring ≥ 0.8.** A product/version read off metadata, a default/example
  template, or a single boilerplate signal is a `≤ 0.5` lead until cross-checked against the
  live UI + version-specific paths. (FP-001: "EOL Shibboleth v2.x" asserted at 0.8 from the
  shipped *example* metadata — a false positive that verification refuted.)
- **Negatives and environment claims meet the SAME artifact bar as positive confirmations.** A
  refutation / "blocked" / "campus-only" claim at ≥ 0.8 must cite a SAVED artifact that actually
  substantiates it (e.g. the differential response bodies, not an unrelated homepage). If you only
  have prose, it is ≤ 0.5. (codex caught E-010/E-013/E-021/E-022 marked 0.8 with prose-only or
  non-substantiating artifacts.) Run the independent/heterogeneous reviewer (`peer_review --into-run`)
  **periodically during the hunt** — after any ≥ 0.8 assignment or false positive — not only at closure.
  Codex backend requires its own dedicated proxy (`CODEX_PROXY` env or `tools/harness/codex_proxy.conf`);
  see `review/independent-reviewer.md` "Codex 代理（必须）".

## Vulnerability Chains

Web-layer findings often combine (chaining): one confirmed finding's proven
output state satisfies another finding's precondition. Chaining is first-class —
it is how low-severity atoms compose into a high-impact finding — but it carries
its own discipline:

- Weakest-hop gate: a chain is only as strong as its weakest hop. Every hop must
  be a confirmed evidence item (`certainty >= 0.8`); if any hop is merely
  suspected, the whole chain is suspected, not confirmed.
- Terminal proof node: a high-impact proven state (RCE proven, admin reached)
  ENDS the chain for proof purposes. Record it. The destructive final action and
  data exfiltration / database dump are hard rules — never. Going further (persistence, a
  webshell, pivoting) is operator-gated — only with the operator's consent.
- Default: prove an SSRF / RCE hop by reachability to the target state. Pivoting
  from it into the host or internal network is operator-gated (ask the operator
  first), not a boundary violation.
- Record edges in `chains.md`; the atoms still report individually. Composite
  severity is usually higher than any single hop alone.

## Attribution Checks

Before treating a signal as proof, run the attribution checklist in
`docs/cognition/reference.md` (load in Hunter phase): rule out self-caused /
pre-existing / benign (encoding, caching, access control, gateway) / deceptive-decoy
explanations, confirm the asset is in scope + owned, and present-vs-impact-demonstrated.
Unclear → keep the finding suspected, record the missing evidence in the run ledger.

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
- It lumps assets by hostname/IP proximity without checking whether they serve
  different business roles. Threat role mismatch between same-IP or same-hostname-pattern
  assets is a no-lump signal — they MUST be separate fronts.
- It stops after a high-value finding and leaves the remaining (especially
  low-value) reachable assets only fingerprinted, never driven to a verdict —
  "examined" lumped as "tested". Prioritise high-value, then auto-continue the
  low-value ones (cheap breadth via `tools/scan.py`); every reachable asset gets a
  verdict (deferred-with-reason counts), one is not skipped.
- It lets recon `[review]` / high-value / management assets disappear into prose.
  Those assets need an `E-xxx` entry even when the result is negative, blocked, or
  current-egress unreachable; otherwise the evidence ledger cannot prove they were
  actually touched.
- It marks an asset `deferred` ("need creds" / "low value") **without an attack
  attempt** — treating `deferred` as a free escape hatch (the *deferred-is-the-new-lump*
  hole). For real attack surface (a login form), attack the unauth layer (SQLi / user
  enum / default creds / bypass) and record an `E-xxx` first — its result counts whether
  it lands, is hardened, or is egress-blocked; only the post-auth depth is creds-gated.
- It tunnels deep on one attractive app before the breadth pass (preliminary
  surface-detection of *every* asset, high-value then low-value) is complete.
- It treats first-pass banner, version, or page observations as sufficient.
- On a SPA it calls endpoints "enumerated" from a partially-fetched JS set — confirm
  `tools/fetch_assets.py` reports every referenced chunk fetched (N==M) before
  believing enumeration is complete; a missed webpack chunk is how a real run walked
  past an account-takeover endpoint.
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

## Knowledge: Grounding vs Weaponized — never a blind scanner

**Use payload knowledge to attack** — a reasoning attacker, **not a payload scanner**.
The forbidden thing is **not weaponization**; it is the **blind scanner / playbook**
(knowledge fired the same way regardless of target) + **publishing a turnkey kit**. Look
knowledge up **after** identifying a target, **adapt** it, confirm through the evidence
gate; never pre-load and fire it blind (payload or not). The two-axis detail (use-pattern
vs publication; grounding tier ships, weaponized tier is held-not-pushed) is in
`docs/cognition/reference.md` — load it when handling the knowledge base.

## Exploit Preconditions

When a CVE is identified and the target's version matches, record the exploit
preconditions as a separate field (not folded into certainty):

- `ExploitPreconditions: met | not-met | unknown`
- `met` = all conditions for the exploit are confirmed present on target
- `not-met` = at least one required condition is confirmed absent (e.g. "2FA not enabled", "REST route not registered")
- `unknown` = version matches but preconditions have not been checked

This prevents the "version matches CVE = confirmed vulnerability" error and
gives the certainty rating a concrete basis. When preconditions are `not-met`,
certainty MUST be ≤ 0.3 regardless of CVSS score.
