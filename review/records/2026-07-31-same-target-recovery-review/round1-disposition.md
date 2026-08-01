# Round 1 fresh-context Claude review disposition

- Date: 2026-07-31
- Reviewed framework fingerprint: `9bcaec9ada0a2d15`
- Reviewer session: `849c3fae-60d9-4151-9af9-0688dd429f19`
- Reviewer model: configured `deepseek-v4-flash[1m]`
- Tools: disabled
- arkcli: not used, per operator instruction
- Verdict: FAIL

The reviewer raised two blockers and five non-blocking gaps. No commit was made.

## Disposition

1. **Legacy binding-only receipts — accepted and fixed.** A real checkout
   receipt from before `5d0a99c` confirmed the binding-only shape. The terminal
   validator now accepts only its exact frozen session/prompt/transaction with
   no current claim, verifies the source bundle/hash, and rejects tamper or a
   half-modern profile-bearing receipt. Modern strict activation/profile gates
   remain unchanged.
2. **Cross-origin create — reviewer inference disproved, coverage added.** The
   unchanged create commit path writes the exact top-level receipt pair before
   pointer replacement. A new regression creates target B from active origin A,
   consumes the claim, switches the pointer, and proves post-bind via that pair.
3. **Missing-claim/effect gaps — fixed.** Same-target resume/set-active now
   always requires a claim even when `run_transition_requested=false`; candidate
   target/effect mismatch and stale frozen cross-effect fields fail closed.
4. **Typed error — fixed.** The missing-claim guard raises
   `SetupTransactionError(contract_claim_invalid)` directly rather than relying
   on an unchanged RuntimeError conversion.
5. **Activation branch and Hook E2E — covered.** Tests now call the terminal
   activation-attempt validator for cross/same-target activation, and a real
   UserPromptSubmit/PreToolUse subprocess claim is consumed by the transaction
   owner and passes post-bind.
6. **Exception/docs — fixed.** Post-bind catches `ValueError` defensively; docs
   distinguish Hook-bound original pairs, direct-CLI unbound receipts, legacy
   binding-only compatibility, cross-origin create, and modern same-run
   reconciliation.

The corrected framework fingerprint is `0113b8c3814ef296`. It requires a new
fresh-context review; this FAIL record is not an approval record.
